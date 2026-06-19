import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS targets (
    target_id       TEXT PRIMARY KEY,
    gene_symbol     TEXT NOT NULL,
    protein_name    TEXT,
    uniprot_id      TEXT UNIQUE NOT NULL,
    organism        TEXT DEFAULT 'Homo sapiens',
    target_class    TEXT,
    function_desc   TEXT,
    sequence        TEXT,
    sequence_length INTEGER,
    evidence_score  REAL,
    confidence_score REAL,
    validation_status TEXT DEFAULT 'pending',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    last_synced_uniprot TEXT,
    last_synced_pdb     TEXT,
    last_synced_chembl  TEXT,
    last_synced_opentargets TEXT,
    last_synced_pubmed  TEXT
);

CREATE TABLE IF NOT EXISTS associated_cancers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL REFERENCES targets(target_id) ON DELETE CASCADE,
    cancer_type TEXT NOT NULL,
    source      TEXT,
    evidence_score REAL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(target_id, cancer_type, source)
);

CREATE TABLE IF NOT EXISTS pathways (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL REFERENCES targets(target_id) ON DELETE CASCADE,
    pathway_id  TEXT,
    pathway_name TEXT NOT NULL,
    source      TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(target_id, pathway_name, source)
);

CREATE TABLE IF NOT EXISTS pdb_structures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL REFERENCES targets(target_id) ON DELETE CASCADE,
    pdb_id      TEXT NOT NULL,
    resolution  REAL,
    method      TEXT,
    chain_id    TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT,
    UNIQUE(target_id, pdb_id)
);

CREATE TABLE IF NOT EXISTS inhibitors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id       TEXT NOT NULL REFERENCES targets(target_id) ON DELETE CASCADE,
    chembl_id       TEXT,
    compound_name   TEXT NOT NULL,
    bioactivity_type TEXT,
    bioactivity_value REAL,
    bioactivity_unit TEXT,
    source          TEXT DEFAULT 'chembl',
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(target_id, chembl_id)
);

CREATE TABLE IF NOT EXISTS references_ (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL REFERENCES targets(target_id) ON DELETE CASCADE,
    pubmed_id   TEXT,
    doi         TEXT,
    title       TEXT,
    journal     TEXT,
    year        INTEGER,
    source      TEXT DEFAULT 'pubmed',
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(target_id, pubmed_id)
);

CREATE TABLE IF NOT EXISTS source_id_mapping (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL REFERENCES targets(target_id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(target_id, source_name)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,
    records_fetched INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    started_at  TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_targets_gene ON targets(gene_symbol);
CREATE INDEX IF NOT EXISTS idx_targets_uniprot ON targets(uniprot_id);
CREATE INDEX IF NOT EXISTS idx_cancers_target ON associated_cancers(target_id);
CREATE INDEX IF NOT EXISTS idx_inhibitors_target ON inhibitors(target_id);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()
    logger.info("Database initialized at %s", db_path)
    return conn


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
