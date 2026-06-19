"""
ChEMBL Connector — ambil target-ligand mapping & bioactivity.

Strategi:
- Untuk setiap target di DB (dengan uniprot_id), cari ChEMBL target ID via UniProt accession
- Fetch bioactivity (IC50, Ki, Kd) dengan standard_relation "="
- Rate limit: 1 req/s (konservatif, tanpa API key)
- Simpan ke tabel inhibitors + source_id_mapping
"""

import logging
import sqlite3
from datetime import datetime, timezone

from cmtr.connectors.base import fetch_json
from cmtr.db.schema import get_conn
from cmtr.utils.resume import mark_interrupted, commit_target

logger = logging.getLogger(__name__)

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
PAGE_SIZE = 100
BIOACTIVITY_TYPES = "IC50,Ki,Kd,EC50"


def _get_chembl_target_id(uniprot_id: str) -> str | None:
    """Cari ChEMBL target ID dari UniProt accession. Ambil SINGLE PROTEIN saja."""
    url = f"{CHEMBL_BASE}/target.json"
    data = fetch_json(url, params={
        "target_components__accession": uniprot_id,
        "target_type": "SINGLE PROTEIN",
        "limit": 1,
    }, source="chembl")
    targets = data.get("targets", [])
    if not targets:
        return None
    return targets[0].get("target_chembl_id")


def _fetch_activities(chembl_target_id: str) -> list[dict]:
    """Fetch semua bioactivity records untuk satu ChEMBL target ID."""
    url = f"{CHEMBL_BASE}/activity.json"
    activities = []
    offset = 0

    while True:
        data = fetch_json(url, params={
            "target_chembl_id": chembl_target_id,
            "standard_type__in": BIOACTIVITY_TYPES,
            "standard_relation": "=",
            "limit": PAGE_SIZE,
            "offset": offset,
        }, source="chembl")

        batch = data.get("activities", [])
        activities.extend(batch)

        page_meta = data.get("page_meta", {})
        if not page_meta.get("next"):
            break
        offset += PAGE_SIZE

        if offset > 5000:  # hard cap per target untuk prototype
            logger.warning("[chembl] capping activities at 5000 for %s", chembl_target_id)
            break

    return activities


def _upsert_inhibitors(conn: sqlite3.Connection, target_id: str, activities: list[dict], now: str) -> int:
    inserted = 0
    for act in activities:
        chembl_id = act.get("molecule_chembl_id", "")
        compound_name = act.get("molecule_pref_name") or chembl_id
        bio_type = act.get("standard_type", "")
        bio_value = act.get("standard_value")
        bio_unit = act.get("standard_units", "")

        if not chembl_id:
            continue

        try:
            bio_value_float = float(bio_value) if bio_value is not None else None
        except (ValueError, TypeError):
            bio_value_float = None

        cur = conn.execute("""
            INSERT OR IGNORE INTO inhibitors
                (target_id, chembl_id, compound_name, bioactivity_type, bioactivity_value, bioactivity_unit, source, created_at)
            VALUES (?,?,?,?,?,?,'chembl',?)
        """, (target_id, chembl_id, compound_name, bio_type, bio_value_float, bio_unit, now))
        inserted += cur.rowcount

    return inserted


def run(db_path: str) -> dict:
    """
    Jalankan ChEMBL connector.
    Untuk setiap target yang belum di-sync ke ChEMBL, fetch dan simpan inhibitor data.
    """
    conn = get_conn(db_path)
    now = datetime.now(timezone.utc).isoformat()

    mark_interrupted(conn, "chembl")
    log_id = conn.execute(
        "INSERT INTO sync_log (source, status, started_at) VALUES ('chembl','running',?)",
        (now,),
    ).lastrowid
    conn.commit()

    # last_synced_chembl IS NULL = belum diproses (termasuk yang interrupted)
    rows = conn.execute("""
        SELECT target_id, uniprot_id FROM targets
        WHERE last_synced_chembl IS NULL AND uniprot_id != ''
        ORDER BY target_id
    """).fetchall()
    logger.info("[chembl] targets to process: %d", len(rows))

    total_targets = 0
    total_fetched = 0
    total_inserted = 0
    no_chembl_id = 0

    try:
        for row in rows:
            target_id = row["target_id"]
            uniprot_id = row["uniprot_id"]

            # Cari ChEMBL target ID
            chembl_target_id = _get_chembl_target_id(uniprot_id)
            if not chembl_target_id:
                logger.debug("[chembl] no ChEMBL target for UniProt %s", uniprot_id)
                no_chembl_id += 1
                commit_target(conn, target_id, "last_synced_chembl", now)
                continue

            # Simpan mapping
            conn.execute("""
                INSERT OR REPLACE INTO source_id_mapping (target_id, source_name, source_id, created_at)
                VALUES (?,?,?,?)
            """, (target_id, "chembl", chembl_target_id, now))

            # Fetch activities
            activities = _fetch_activities(chembl_target_id)
            total_fetched += len(activities)

            inserted = _upsert_inhibitors(conn, target_id, activities, now)
            total_inserted += inserted

            commit_target(conn, target_id, "last_synced_chembl", now)
            total_targets += 1

            if total_targets % 50 == 0:
                logger.info(
                    "[chembl] progress — targets=%d fetched=%d inserted=%d no_id=%d",
                    total_targets, total_fetched, total_inserted, no_chembl_id,
                )

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE sync_log SET status='success', records_fetched=?,
            records_inserted=?, finished_at=? WHERE id=?
        """, (total_fetched, total_inserted, finished, log_id))
        conn.commit()
        logger.info(
            "[chembl] done — targets=%d fetched=%d inserted=%d no_id=%d",
            total_targets, total_fetched, total_inserted, no_chembl_id,
        )

    except Exception as exc:
        logger.error("[chembl] failed: %s", exc)
        conn.execute("""
            UPDATE sync_log SET status='error', error_message=?, finished_at=? WHERE id=?
        """, (str(exc), datetime.now(timezone.utc).isoformat(), log_id))
        conn.commit()
        raise
    finally:
        conn.close()

    return {
        "targets_processed": total_targets,
        "activities_fetched": total_fetched,
        "inhibitors_inserted": total_inserted,
        "no_chembl_id": no_chembl_id,
    }
