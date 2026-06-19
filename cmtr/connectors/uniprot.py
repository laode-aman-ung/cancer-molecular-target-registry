"""
UniProt Connector — mengambil protein manusia terkait kanker.

Strategi:
- Initial load: UniProt REST API dengan query disease:cancer, organism:human
- Incremental: filter modified_after tanggal last_synced
- Rate limit: 3 req/s (konservatif, tidak perlu API key)
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Iterator

from cmtr.connectors.base import fetch_json
from cmtr.db.schema import get_conn

logger = logging.getLogger(__name__)

UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
UNIPROT_ENTRY_URL = "https://rest.uniprot.org/uniprotkb/{accession}"

# Query: protein manusia terkait kanker (UniProt keyword IDs)
# KW-0656 = Proto-oncogene, KW-0043 = Tumor suppressor, KW-0965 = Oncoprotein
BASE_QUERY = "(reviewed:true) AND (organism_id:9606) AND (keyword:KW-0656 OR keyword:KW-0043 OR keyword:KW-0965)"

PAGE_SIZE = 500


def _parse_entry(entry: dict) -> dict:
    acc = entry.get("primaryAccession", "")
    gene_names = entry.get("genes", [])
    gene_symbol = gene_names[0].get("geneName", {}).get("value", "") if gene_names else ""

    protein = entry.get("proteinDescription", {})
    rec_name = protein.get("recommendedName", {})
    protein_name = rec_name.get("fullName", {}).get("value", "") if rec_name else ""
    if not protein_name:
        sub_names = protein.get("submissionNames", [])
        protein_name = sub_names[0].get("fullName", {}).get("value", "") if sub_names else ""

    # Function description
    comments = entry.get("comments", [])
    function_desc = ""
    for c in comments:
        if c.get("commentType") == "FUNCTION":
            texts = c.get("texts", [])
            if texts:
                function_desc = texts[0].get("value", "")
                break

    # Disease associations — field adalah diseaseId (string), bukan diseaseName.value
    cancers = []
    for c in comments:
        if c.get("commentType") == "DISEASE":
            disease = c.get("disease", {})
            disease_name = disease.get("diseaseId", "")
            if disease_name:
                cancers.append(disease_name)

    # Pathways (keywords)
    keywords = entry.get("keywords", [])
    pathways = [k["name"] for k in keywords if k.get("category") == "Biological process"]

    # Sequence
    seq_info = entry.get("sequence", {})
    sequence = seq_info.get("value", "")
    seq_length = seq_info.get("length", 0)

    # PDB cross-references
    pdb_ids = []
    db_refs = entry.get("uniProtKBCrossReferences", [])
    for ref in db_refs:
        if ref.get("database") == "PDB":
            pdb_ids.append(ref.get("id", ""))

    return {
        "uniprot_id": acc,
        "gene_symbol": gene_symbol,
        "protein_name": protein_name,
        "function_desc": function_desc,
        "cancers": cancers,
        "pathways": pathways,
        "pdb_ids": pdb_ids,
        "sequence": sequence,
        "sequence_length": seq_length,
    }


def _next_url_from_link_header(link_header: str) -> str | None:
    """Parse Link header dari UniProt: <url>; rel="next"
    UniProt menyertakan literal comma di dalam URL (untuk fields), jadi tidak boleh split by comma.
    Gunakan regex untuk ekstrak URL yang diikuti rel="next".
    """
    import re
    if not link_header:
        return None
    # Cari semua <url>; rel="..." blok
    matches = re.findall(r'<([^>]+)>\s*;\s*rel="([^"]+)"', link_header)
    for url, rel in matches:
        if rel == "next":
            return url
    return None


def _iter_pages(modified_after: str = None) -> Iterator[list]:
    """Yield batches of parsed entries dari UniProt, ikuti Link header untuk paginasi."""
    from cmtr.connectors.base import SESSION
    from cmtr.utils.rate_limiter import LIMITERS

    query = BASE_QUERY
    if modified_after:
        query += f" AND (date_modified:[{modified_after} TO *])"

    params = {
        "query": query,
        "format": "json",
        "size": PAGE_SIZE,
        "fields": "accession,gene_names,protein_name,cc_function,cc_disease,keyword,sequence,xref_pdb",
    }

    url = UNIPROT_SEARCH_URL
    page = 0
    limiter = LIMITERS["uniprot"]

    while url:
        limiter.wait()
        if page == 0:
            resp = SESSION.get(url, params=params, timeout=60)
        else:
            resp = SESSION.get(url, timeout=60)  # URL berikutnya sudah lengkap dari Link header
        resp.raise_for_status()

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        page += 1
        logger.info("[uniprot] page %d — %d entries", page, len(results))
        yield [_parse_entry(e) for e in results]

        url = _next_url_from_link_header(resp.headers.get("Link", ""))


def _upsert_target(conn: sqlite3.Connection, entry: dict, now: str):
    acc = entry["uniprot_id"]
    target_id = f"CMTR-{acc}"

    conn.execute("""
        INSERT INTO targets (target_id, gene_symbol, protein_name, uniprot_id,
            function_desc, sequence, sequence_length, last_synced_uniprot, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(uniprot_id) DO UPDATE SET
            gene_symbol=excluded.gene_symbol,
            protein_name=excluded.protein_name,
            function_desc=excluded.function_desc,
            sequence=excluded.sequence,
            sequence_length=excluded.sequence_length,
            last_synced_uniprot=excluded.last_synced_uniprot,
            updated_at=excluded.updated_at
    """, (
        target_id, entry["gene_symbol"], entry["protein_name"], acc,
        entry["function_desc"], entry["sequence"], entry["sequence_length"], now, now,
    ))

    # cancers
    for cancer in entry["cancers"]:
        conn.execute("""
            INSERT OR IGNORE INTO associated_cancers (target_id, cancer_type, source)
            VALUES (?,?,?)
        """, (target_id, cancer, "uniprot"))

    # pathways
    for pw in entry["pathways"]:
        conn.execute("""
            INSERT OR IGNORE INTO pathways (target_id, pathway_name, source)
            VALUES (?,?,?)
        """, (target_id, pw, "uniprot"))

    # pdb cross-refs
    for pdb_id in entry["pdb_ids"]:
        conn.execute("""
            INSERT OR IGNORE INTO pdb_structures (target_id, pdb_id)
            VALUES (?,?)
        """, (target_id, pdb_id))


def run(db_path: str, incremental: bool = False) -> dict:
    """
    Jalankan UniProt collector.
    Kembalikan dict statistik {fetched, inserted, updated}.
    """
    conn = get_conn(db_path)
    now = datetime.now(timezone.utc).isoformat()

    # Cek last sync untuk incremental
    modified_after = None
    if incremental:
        row = conn.execute(
            "SELECT finished_at FROM sync_log WHERE source='uniprot' AND status='success' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        if row and row["finished_at"]:
            modified_after = row["finished_at"][:10]  # YYYY-MM-DD
            logger.info("[uniprot] incremental mode, modified after %s", modified_after)

    log_id = conn.execute(
        "INSERT INTO sync_log (source, status, started_at) VALUES ('uniprot','running',?)",
        (now,)
    ).lastrowid
    conn.commit()

    fetched = inserted = updated = 0
    try:
        for batch in _iter_pages(modified_after):
            for entry in batch:
                fetched += 1
                # check if exists
                exists = conn.execute(
                    "SELECT 1 FROM targets WHERE uniprot_id=?", (entry["uniprot_id"],)
                ).fetchone()
                _upsert_target(conn, entry, now)
                if exists:
                    updated += 1
                else:
                    inserted += 1
            conn.commit()
            logger.info("[uniprot] progress — fetched=%d inserted=%d updated=%d", fetched, inserted, updated)

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE sync_log SET status='success', records_fetched=?,
            records_inserted=?, records_updated=?, finished_at=? WHERE id=?
        """, (fetched, inserted, updated, finished, log_id))
        conn.commit()
        logger.info("[uniprot] done — fetched=%d inserted=%d updated=%d", fetched, inserted, updated)

    except Exception as exc:
        logger.error("[uniprot] failed: %s", exc)
        conn.execute("""
            UPDATE sync_log SET status='error', error_message=?, finished_at=? WHERE id=?
        """, (str(exc), datetime.now(timezone.utc).isoformat(), log_id))
        conn.commit()
        raise
    finally:
        conn.close()

    return {"fetched": fetched, "inserted": inserted, "updated": updated}
