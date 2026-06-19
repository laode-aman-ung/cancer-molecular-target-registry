"""
CMTR Monitoring Dashboard — tampilan Rich di terminal.
Jalankan: python -m cmtr.monitoring.dashboard
"""

import os
import sqlite3
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from rich.text import Text

console = Console()


def _conn(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _safe(conn, sql, default=0):
    try:
        row = conn.execute(sql).fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception:
        return default


def show(db_path: str = "data/cmtr.db"):
    conn = _conn(db_path)
    if conn is None:
        console.print(Panel(
            "[yellow]Database belum ada. Jalankan pipeline terlebih dahulu.[/yellow]\n"
            "[dim]python -m cmtr.pipeline uniprot[/dim]",
            title="CMTR Dashboard", border_style="yellow"
        ))
        return

    console.rule("[bold cyan]CMTR — Cancer Molecular Target Registry[/bold cyan]")
    console.print(f"[dim]Database: {os.path.abspath(db_path)}  |  Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n")

    # ── Dashboard 1: Data Growth ──────────────────────────────────────────────
    total_targets   = _safe(conn, "SELECT COUNT(*) FROM targets")
    total_cancers   = _safe(conn, "SELECT COUNT(DISTINCT cancer_type) FROM associated_cancers")
    total_pdb       = _safe(conn, "SELECT COUNT(*) FROM pdb_structures")
    total_inhibitors= _safe(conn, "SELECT COUNT(*) FROM inhibitors")
    total_refs      = _safe(conn, "SELECT COUNT(*) FROM references_")
    total_pathways  = _safe(conn, "SELECT COUNT(DISTINCT pathway_name) FROM pathways")

    t1 = Table(title="Dashboard 1 — Data Growth", box=box.SIMPLE_HEAD, style="cyan")
    t1.add_column("Metric", style="bold")
    t1.add_column("Count", justify="right", style="green")
    t1.add_row("Total Targets",    f"{total_targets:,}")
    t1.add_row("Cancer Types",     f"{total_cancers:,}")
    t1.add_row("PDB Structures",   f"{total_pdb:,}")
    t1.add_row("Inhibitors",       f"{total_inhibitors:,}")
    t1.add_row("References",       f"{total_refs:,}")
    t1.add_row("Unique Pathways",  f"{total_pathways:,}")
    console.print(t1)

    # ── Dashboard 2: Coverage per source ─────────────────────────────────────
    def coverage_pct(has_field_sql, total):
        n = _safe(conn, has_field_sql)
        return f"{n:,} / {total:,} ({n/total*100:.1f}%)" if total else "—"

    t2 = Table(title="Dashboard 2 — Source Coverage", box=box.SIMPLE_HEAD, style="cyan")
    t2.add_column("Source", style="bold")
    t2.add_column("Targets Synced", justify="right")
    t2.add_row("UniProt",      coverage_pct("SELECT COUNT(*) FROM targets WHERE last_synced_uniprot IS NOT NULL", total_targets))
    t2.add_row("PDB",          coverage_pct("SELECT COUNT(*) FROM targets WHERE last_synced_pdb IS NOT NULL", total_targets))
    t2.add_row("ChEMBL",       coverage_pct("SELECT COUNT(*) FROM targets WHERE last_synced_chembl IS NOT NULL", total_targets))
    t2.add_row("Open Targets", coverage_pct("SELECT COUNT(*) FROM targets WHERE last_synced_opentargets IS NOT NULL", total_targets))
    t2.add_row("PubMed",       coverage_pct("SELECT COUNT(*) FROM targets WHERE last_synced_pubmed IS NOT NULL", total_targets))
    console.print(t2)

    # ── Dashboard 3: Completeness ─────────────────────────────────────────────
    def pct(sql):
        n = _safe(conn, sql)
        return f"{n/total_targets*100:.1f}%" if total_targets else "—"

    t3 = Table(title="Dashboard 3 — Field Completeness", box=box.SIMPLE_HEAD, style="cyan")
    t3.add_column("Field", style="bold")
    t3.add_column("Weight")
    t3.add_column("Filled %", justify="right")
    t3.add_row("Gene Symbol",   "10", pct("SELECT COUNT(*) FROM targets WHERE gene_symbol!=''"))
    t3.add_row("UniProt ID",    "10", pct("SELECT COUNT(*) FROM targets WHERE uniprot_id!=''"))
    t3.add_row("Protein Name",  "10", pct("SELECT COUNT(*) FROM targets WHERE protein_name!=''"))
    t3.add_row("PDB Struct.",   "20", pct("SELECT COUNT(DISTINCT target_id) FROM pdb_structures"))
    t3.add_row("Pathway",       "20", pct("SELECT COUNT(DISTINCT target_id) FROM pathways"))
    t3.add_row("Disease Assoc.","15", pct("SELECT COUNT(DISTINCT target_id) FROM associated_cancers"))
    t3.add_row("Inhibitor",     "15", pct("SELECT COUNT(DISTINCT target_id) FROM inhibitors"))
    console.print(t3)

    # ── Dashboard 4: Freshness ────────────────────────────────────────────────
    t4 = Table(title="Dashboard 4 — Freshness", box=box.SIMPLE_HEAD, style="cyan")
    t4.add_column("Source", style="bold")
    t4.add_column("Last Sync", justify="right")
    t4.add_column("Status")
    for src in ["uniprot", "pdb", "chembl", "opentargets", "pubmed"]:
        row = conn.execute(
            "SELECT finished_at, status FROM sync_log WHERE source=? AND status='success' ORDER BY finished_at DESC LIMIT 1",
            (src,)
        ).fetchone()
        if row and row["finished_at"]:
            ts = row["finished_at"][:19]
            status_txt = Text("OK", style="green")
        else:
            ts = "Never"
            status_txt = Text("NOT RUN", style="dim")
        t4.add_row(src.capitalize(), ts, status_txt)
    console.print(t4)

    # ── Dashboard 5: Data Quality ─────────────────────────────────────────────
    dup_rate = 0.0  # duplikat ditangani oleh UNIQUE constraint, tapi kita hitung gene_symbol duplikat sebagai proxy
    dup_genes = _safe(conn, "SELECT COUNT(*)-COUNT(DISTINCT gene_symbol) FROM targets WHERE gene_symbol!=''")
    dup_rate = (dup_genes / total_targets * 100) if total_targets else 0
    missing_protein = _safe(conn, "SELECT COUNT(*) FROM targets WHERE protein_name='' OR protein_name IS NULL")
    missing_pct = (missing_protein / total_targets * 100) if total_targets else 0

    t5 = Table(title="Dashboard 5 — Data Quality", box=box.SIMPLE_HEAD, style="cyan")
    t5.add_column("KPI", style="bold")
    t5.add_column("Value", justify="right")
    t5.add_column("Target")
    dup_color = "green" if dup_rate < 5 else "red"
    miss_color = "green" if missing_pct < 20 else "red"
    t5.add_row("Duplicate Gene Rate",    Text(f"{dup_rate:.1f}%", style=dup_color), "< 5%")
    t5.add_row("Missing Protein Name",   Text(f"{missing_pct:.1f}%", style=miss_color), "< 20%")
    pending_sql = "SELECT COUNT(*) FROM targets WHERE validation_status='pending'"
    t5.add_row("Validation Status", f"pending={_safe(conn, pending_sql)}", "—")
    console.print(t5)

    # ── Dashboard 6: Source Health (sync_log) ────────────────────────────────
    t6 = Table(title="Dashboard 6 — Source Health", box=box.SIMPLE_HEAD, style="cyan")
    t6.add_column("Source", style="bold")
    t6.add_column("Last Run")
    t6.add_column("Result", justify="right")
    t6.add_column("Fetched", justify="right")
    for src in ["uniprot", "pdb", "chembl", "opentargets", "pubmed"]:
        row = conn.execute(
            "SELECT status, records_fetched, finished_at FROM sync_log WHERE source=? ORDER BY started_at DESC LIMIT 1",
            (src,)
        ).fetchone()
        if row:
            color = "green" if row["status"] == "success" else ("red" if row["status"] == "error" else "yellow")
            t6.add_row(src.capitalize(), (row["finished_at"] or "")[:19],
                       Text(row["status"].upper(), style=color), str(row["records_fetched"] or 0))
        else:
            t6.add_row(src.capitalize(), "—", Text("NOT RUN", style="dim"), "0")
    console.print(t6)

    conn.close()
    console.print()


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "data/cmtr.db"
    show(db)
