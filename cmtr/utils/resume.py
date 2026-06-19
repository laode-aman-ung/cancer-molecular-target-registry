"""
Resume helper — utilitas untuk checkpoint-based resumability.

Setiap connector memakai pola:
1. Tandai sync_log 'running' yang tergantung sebagai 'interrupted' saat mulai
2. Commit per target (bukan per batch) agar checkpoint selalu up-to-date
3. Query WHERE last_synced_X IS NULL memastikan target yang sudah selesai dilewati
"""

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def mark_interrupted(conn: sqlite3.Connection, source: str):
    """Tandai semua sync_log 'running' yang tergantung sebagai 'interrupted'."""
    now = datetime.now(timezone.utc).isoformat()
    affected = conn.execute("""
        UPDATE sync_log SET status='interrupted', finished_at=?, error_message='Process was interrupted'
        WHERE source=? AND status='running'
    """, (now, source)).rowcount
    if affected:
        logger.info("[%s] %d interrupted run(s) ditandai", source, affected)
    conn.commit()


def commit_target(conn: sqlite3.Connection, target_id: str, source_col: str, now: str):
    """Update last_synced dan langsung commit — checkpoint per target."""
    conn.execute(
        f"UPDATE targets SET {source_col}=?, updated_at=? WHERE target_id=?",
        (now, now, target_id),
    )
    conn.commit()
