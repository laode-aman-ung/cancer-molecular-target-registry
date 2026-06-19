"""
PubMed Connector — ambil metadata & abstract referensi ilmiah via NCBI E-utilities.

Strategi:
- Untuk setiap target, search PubMed: "{gene_symbol}[Gene] AND cancer[Title/Abstract]"
- Ambil metadata (PMID, title, journal, year, DOI) — BUKAN full-text (sesuai lisensi §3b)
- Simpan ke tabel references_
- Rate limit: 3 req/s tanpa API key, 10 req/s dengan NCBI_API_KEY di .env
- Cap: 100 referensi per target untuk prototype
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone

from cmtr.connectors.base import fetch_json
from cmtr.db.schema import get_conn
from cmtr.utils.rate_limiter import LIMITERS, RateLimiter
from cmtr.utils.resume import mark_interrupted, commit_target

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_REFS_PER_TARGET = 100
BATCH_SIZE = 50  # ESummary batch


def _get_limiter() -> RateLimiter:
    """Gunakan 10 req/s jika ada API key, 3 req/s jika tidak."""
    api_key = os.getenv("NCBI_API_KEY", "")
    if api_key:
        return RateLimiter(requests_per_second=10.0, source="pubmed")
    return LIMITERS["pubmed"]


def _search_pmids(gene_symbol: str, api_key: str = "") -> list[str]:
    """ESearch: cari PMIDs untuk gen terkait kanker."""
    params = {
        "db": "pubmed",
        "term": f"{gene_symbol}[Gene] AND cancer[Title/Abstract]",
        "retmax": MAX_REFS_PER_TARGET,
        "retmode": "json",
        "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key

    data = fetch_json(f"{EUTILS_BASE}/esearch.fcgi", params=params, source="pubmed")
    return data.get("esearchresult", {}).get("idlist", [])


def _fetch_summaries(pmids: list[str], api_key: str = "") -> list[dict]:
    """ESummary: ambil metadata untuk batch PMIDs."""
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key

    data = fetch_json(f"{EUTILS_BASE}/esummary.fcgi", params=params, source="pubmed")
    result = data.get("result", {})

    summaries = []
    for pmid in pmids:
        doc = result.get(pmid, {})
        if not doc or doc.get("error"):
            continue

        # Ekstrak DOI dari articleids
        doi = ""
        for aid in doc.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break

        year_str = doc.get("pubdate", "")[:4]
        try:
            year = int(year_str) if year_str.isdigit() else None
        except ValueError:
            year = None

        summaries.append({
            "pubmed_id": pmid,
            "title": doc.get("title", "")[:500],
            "journal": doc.get("source", "")[:200],
            "year": year,
            "doi": doi[:200],
        })
    return summaries


def _upsert_references(conn: sqlite3.Connection, target_id: str,
                        summaries: list[dict], now: str) -> int:
    inserted = 0
    for s in summaries:
        cur = conn.execute("""
            INSERT OR IGNORE INTO references_
                (target_id, pubmed_id, doi, title, journal, year, source, created_at)
            VALUES (?,?,?,?,?,?,'pubmed',?)
        """, (target_id, s["pubmed_id"], s["doi"], s["title"],
               s["journal"], s["year"], now))
        inserted += cur.rowcount
    return inserted


def run(db_path: str) -> dict:
    """Jalankan PubMed connector."""
    conn = get_conn(db_path)
    now = datetime.now(timezone.utc).isoformat()
    api_key = os.getenv("NCBI_API_KEY", "")

    if api_key:
        logger.info("[pubmed] menggunakan NCBI API key (10 req/s)")
    else:
        logger.info("[pubmed] tanpa API key (3 req/s) — daftar di https://www.ncbi.nlm.nih.gov/account/")

    mark_interrupted(conn, "pubmed")
    log_id = conn.execute(
        "INSERT INTO sync_log (source, status, started_at) VALUES ('pubmed','running',?)",
        (now,),
    ).lastrowid
    conn.commit()

    rows = conn.execute("""
        SELECT target_id, gene_symbol FROM targets
        WHERE last_synced_pubmed IS NULL AND gene_symbol != ''
        ORDER BY target_id
    """).fetchall()
    logger.info("[pubmed] targets to process: %d", len(rows))

    total_targets = total_fetched = total_inserted = no_results = 0

    try:
        for row in rows:
            target_id = row["target_id"]
            gene_symbol = row["gene_symbol"]

            pmids = _search_pmids(gene_symbol, api_key)
            if not pmids:
                no_results += 1
                commit_target(conn, target_id, "last_synced_pubmed", now)
                continue

            summaries = _fetch_summaries(pmids, api_key)
            total_fetched += len(summaries)

            inserted = _upsert_references(conn, target_id, summaries, now)
            total_inserted += inserted

            commit_target(conn, target_id, "last_synced_pubmed", now)
            total_targets += 1

            if total_targets % 50 == 0:
                logger.info(
                    "[pubmed] progress — targets=%d fetched=%d inserted=%d no_results=%d",
                    total_targets, total_fetched, total_inserted, no_results,
                )

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE sync_log SET status='success', records_fetched=?,
            records_inserted=?, finished_at=? WHERE id=?
        """, (total_fetched, total_inserted, finished, log_id))
        conn.commit()
        logger.info("[pubmed] done — targets=%d fetched=%d inserted=%d no_results=%d",
                    total_targets, total_fetched, total_inserted, no_results)

    except Exception as exc:
        logger.error("[pubmed] failed: %s", exc)
        conn.execute("""
            UPDATE sync_log SET status='error', error_message=?, finished_at=? WHERE id=?
        """, (str(exc), datetime.now(timezone.utc).isoformat(), log_id))
        conn.commit()
        raise
    finally:
        conn.close()

    return {
        "targets_processed": total_targets,
        "refs_fetched": total_fetched,
        "refs_inserted": total_inserted,
        "no_results": no_results,
    }
