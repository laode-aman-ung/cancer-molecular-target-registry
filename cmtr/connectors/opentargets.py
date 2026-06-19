"""
Open Targets Connector — ambil disease-target association score.

Strategi:
- Untuk setiap target di DB, cari Ensembl gene ID via gene_symbol search
- Verifikasi dengan mencocokkan UniProt accession
- Fetch disease associations (score >= 0.1) dan simpan ke associated_cancers
- Rate limit: 2 req/s (konservatif)
"""

import logging
import sqlite3
from datetime import datetime, timezone

from cmtr.connectors.base import SESSION
from cmtr.db.schema import get_conn
from cmtr.utils.rate_limiter import LIMITERS
from cmtr.utils.resume import mark_interrupted, commit_target

logger = logging.getLogger(__name__)

OT_GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"
MIN_SCORE = 0.1       # hanya ambil association dengan evidence score >= threshold
MAX_DISEASES = 200    # cap per target untuk prototype
PAGE_SIZE = 50


def _post(query: str) -> dict:
    LIMITERS["opentargets"].wait()
    resp = SESSION.post(OT_GRAPHQL, json={"query": query}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise ValueError(f"GraphQL error: {data['errors']}")
    return data.get("data", {})


def _get_ensembl_id(gene_symbol: str, uniprot_id: str) -> str | None:
    """Cari Ensembl gene ID via gene symbol, verifikasi dengan UniProt accession."""
    query = f"""
    {{
      search(queryString: "{gene_symbol}", entityNames: ["target"], page: {{index: 0, size: 5}}) {{
        hits {{
          object {{
            ... on Target {{
              id
              approvedSymbol
              proteinIds {{ id source }}
            }}
          }}
        }}
      }}
    }}
    """
    try:
        data = _post(query)
        hits = data.get("search", {}).get("hits", [])
        for hit in hits:
            obj = hit.get("object", {})
            symbol = obj.get("approvedSymbol", "").upper()
            ensembl_id = obj.get("id", "")
            # Cocokkan symbol atau UniProt accession
            protein_ids = [p["id"] for p in obj.get("proteinIds", [])
                           if p["source"] in ("uniprot_swissprot", "uniprot_trembl")]
            if symbol == gene_symbol.upper() or uniprot_id in protein_ids:
                return ensembl_id
    except Exception as exc:
        logger.debug("[opentargets] ensembl lookup failed for %s: %s", gene_symbol, exc)
    return None


def _fetch_associations(ensembl_id: str) -> list[dict]:
    """Fetch disease associations untuk satu Ensembl gene ID."""
    associations = []
    offset = 0

    while True:
        query = f"""
        {{
          target(ensemblId: "{ensembl_id}") {{
            associatedDiseases(
              page: {{index: {offset // PAGE_SIZE}, size: {PAGE_SIZE}}}
            ) {{
              count
              rows {{
                disease {{ id name }}
                score
              }}
            }}
          }}
        }}
        """
        try:
            data = _post(query)
            rows = data.get("target", {}).get("associatedDiseases", {}).get("rows", [])
        except Exception as exc:
            logger.warning("[opentargets] fetch failed for %s: %s", ensembl_id, exc)
            break

        for row in rows:
            score = row.get("score", 0)
            if score < MIN_SCORE:
                continue
            associations.append({
                "disease_id": row["disease"]["id"],
                "disease_name": row["disease"]["name"],
                "score": score,
            })

        offset += PAGE_SIZE
        if len(rows) < PAGE_SIZE or offset >= MAX_DISEASES:
            break

    return associations


def _upsert_associations(conn: sqlite3.Connection, target_id: str,
                          associations: list[dict], now: str) -> int:
    inserted = 0
    for assoc in associations:
        cur = conn.execute("""
            INSERT OR IGNORE INTO associated_cancers
                (target_id, cancer_type, source, evidence_score, created_at)
            VALUES (?,?,?,?,?)
        """, (target_id, assoc["disease_name"], "opentargets", assoc["score"], now))
        inserted += cur.rowcount
    return inserted


def run(db_path: str) -> dict:
    """Jalankan Open Targets connector."""
    conn = get_conn(db_path)
    now = datetime.now(timezone.utc).isoformat()

    mark_interrupted(conn, "opentargets")
    log_id = conn.execute(
        "INSERT INTO sync_log (source, status, started_at) VALUES ('opentargets','running',?)",
        (now,),
    ).lastrowid
    conn.commit()

    rows = conn.execute("""
        SELECT target_id, gene_symbol, uniprot_id FROM targets
        WHERE last_synced_opentargets IS NULL AND gene_symbol != ''
        ORDER BY target_id
    """).fetchall()
    logger.info("[opentargets] targets to process: %d", len(rows))

    total_targets = no_ensembl = total_fetched = total_inserted = 0

    try:
        for row in rows:
            target_id = row["target_id"]
            gene_symbol = row["gene_symbol"]
            uniprot_id = row["uniprot_id"]

            ensembl_id = _get_ensembl_id(gene_symbol, uniprot_id)
            if not ensembl_id:
                logger.debug("[opentargets] no Ensembl ID for %s", gene_symbol)
                no_ensembl += 1
                commit_target(conn, target_id, "last_synced_opentargets", now)
                continue

            # Simpan Ensembl ID ke mapping
            conn.execute("""
                INSERT OR REPLACE INTO source_id_mapping (target_id, source_name, source_id, created_at)
                VALUES (?,?,?,?)
            """, (target_id, "opentargets", ensembl_id, now))

            associations = _fetch_associations(ensembl_id)
            total_fetched += len(associations)

            inserted = _upsert_associations(conn, target_id, associations, now)
            total_inserted += inserted

            commit_target(conn, target_id, "last_synced_opentargets", now)
            total_targets += 1

            if total_targets % 50 == 0:
                logger.info(
                    "[opentargets] progress — targets=%d fetched=%d inserted=%d no_id=%d",
                    total_targets, total_fetched, total_inserted, no_ensembl,
                )

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE sync_log SET status='success', records_fetched=?,
            records_inserted=?, finished_at=? WHERE id=?
        """, (total_fetched, total_inserted, finished, log_id))
        conn.commit()
        logger.info("[opentargets] done — targets=%d fetched=%d inserted=%d no_id=%d",
                    total_targets, total_fetched, total_inserted, no_ensembl)

    except Exception as exc:
        logger.error("[opentargets] failed: %s", exc)
        conn.execute("""
            UPDATE sync_log SET status='error', error_message=?, finished_at=? WHERE id=?
        """, (str(exc), datetime.now(timezone.utc).isoformat(), log_id))
        conn.commit()
        raise
    finally:
        conn.close()

    return {
        "targets_processed": total_targets,
        "associations_fetched": total_fetched,
        "associations_inserted": total_inserted,
        "no_ensembl_id": no_ensembl,
    }
