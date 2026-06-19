"""
PDB Connector — ambil detail struktur 3D dari RCSB PDB.

Strategi:
- Baca semua pdb_id yang sudah ada di tabel pdb_structures (diisi dari UniProt cross-ref)
- Untuk setiap pdb_id yang belum punya detail (resolution IS NULL), fetch dari RCSB REST API
- Rate limit: 5 req/s (konservatif)
- Batch GraphQL untuk efisiensi (fetch banyak IDs sekaligus)
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Iterator

import requests

from cmtr.connectors.base import SESSION
from cmtr.db.schema import get_conn
from cmtr.utils.rate_limiter import LIMITERS

logger = logging.getLogger(__name__)

RCSB_ENTRY_URL = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
RCSB_GRAPHQL_URL = "https://data.rcsb.org/graphql"
BATCH_SIZE = 50  # GraphQL batch query


def _fetch_batch_graphql(pdb_ids: list[str]) -> dict:
    """Fetch detail untuk banyak PDB ID sekaligus via GraphQL."""
    LIMITERS["pdb"].wait()

    # Build GraphQL query untuk multiple entries
    id_list = ", ".join(f'"{p}"' for p in pdb_ids)
    query = f"""
    {{
      entries(entry_ids: [{id_list}]) {{
        rcsb_id
        struct {{
          title
        }}
        exptl {{
          method
        }}
        refine {{
          ls_d_res_high
        }}
        rcsb_entry_info {{
          polymer_entity_count
          deposited_atom_count
        }}
      }}
    }}
    """
    resp = SESSION.post(RCSB_GRAPHQL_URL, json={"query": query}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    entries = data.get("data", {}).get("entries", []) or []
    return {e["rcsb_id"]: e for e in entries if e}


def _parse_entry(entry: dict) -> dict:
    pdb_id = entry.get("rcsb_id", "")
    title = (entry.get("struct") or {}).get("title", "")

    exptl = entry.get("exptl") or [{}]
    method = exptl[0].get("method", "") if exptl else ""

    refine = entry.get("refine") or []
    resolution = refine[0].get("ls_d_res_high") if refine else None

    return {
        "pdb_id": pdb_id,
        "title": title,
        "method": method,
        "resolution": resolution,
    }


def _iter_pending_pdb_ids(conn: sqlite3.Connection) -> Iterator[list[str]]:
    """Yield batch pdb_id yang belum ada detail resolusinya."""
    rows = conn.execute(
        "SELECT DISTINCT pdb_id FROM pdb_structures WHERE resolution IS NULL ORDER BY pdb_id"
    ).fetchall()
    ids = [r[0] for r in rows]
    logger.info("[pdb] total pending structures: %d", len(ids))
    for i in range(0, len(ids), BATCH_SIZE):
        yield ids[i : i + BATCH_SIZE]


def run(db_path: str) -> dict:
    """
    Jalankan PDB connector — update detail resolusi & method untuk semua struktur yang sudah ada.
    """
    conn = get_conn(db_path)
    now = datetime.now(timezone.utc).isoformat()

    log_id = conn.execute(
        "INSERT INTO sync_log (source, status, started_at) VALUES ('pdb','running',?)",
        (now,),
    ).lastrowid
    conn.commit()

    fetched = updated = errors = 0
    try:
        for batch_ids in _iter_pending_pdb_ids(conn):
            try:
                entries = _fetch_batch_graphql(batch_ids)
            except requests.HTTPError as exc:
                logger.warning("[pdb] batch fetch error: %s — skipping batch", exc)
                errors += len(batch_ids)
                continue

            for pdb_id in batch_ids:
                fetched += 1
                raw = entries.get(pdb_id)
                if not raw:
                    logger.debug("[pdb] no data for %s", pdb_id)
                    continue
                parsed = _parse_entry(raw)
                conn.execute(
                    """UPDATE pdb_structures
                       SET resolution=?, method=?, updated_at=?
                       WHERE pdb_id=?""",
                    (parsed["resolution"], parsed["method"], now, pdb_id),
                )
                updated += 1

            conn.commit()
            logger.info(
                "[pdb] progress — fetched=%d updated=%d errors=%d",
                fetched, updated, errors,
            )

        # Update last_synced_pdb di targets yang punya setidaknya satu struktur
        conn.execute("""
            UPDATE targets SET last_synced_pdb=?, updated_at=?
            WHERE target_id IN (SELECT DISTINCT target_id FROM pdb_structures)
        """, (now, now))
        conn.commit()

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE sync_log SET status='success', records_fetched=?,
            records_updated=?, finished_at=? WHERE id=?
        """, (fetched, updated, finished, log_id))
        conn.commit()
        logger.info("[pdb] done — fetched=%d updated=%d errors=%d", fetched, updated, errors)

    except Exception as exc:
        logger.error("[pdb] failed: %s", exc)
        conn.execute("""
            UPDATE sync_log SET status='error', error_message=?, finished_at=? WHERE id=?
        """, (str(exc), datetime.now(timezone.utc).isoformat(), log_id))
        conn.commit()
        raise
    finally:
        conn.close()

    return {"fetched": fetched, "updated": updated, "errors": errors}
