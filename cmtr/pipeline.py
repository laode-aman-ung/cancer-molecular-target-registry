"""
CMTR Pipeline runner — jalankan connector secara manual atau terjadwal.
"""

import logging
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/cmtr.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/cmtr_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_uniprot(incremental: bool = False):
    from cmtr.db.schema import init_db
    from cmtr.connectors.uniprot import run as uniprot_run
    init_db(DB_PATH)
    logger.info("=== UniProt Collector START (incremental=%s) ===", incremental)
    stats = uniprot_run(DB_PATH, incremental=incremental)
    logger.info("=== UniProt Collector DONE: %s ===", stats)
    return stats


def run_pdb():
    from cmtr.db.schema import init_db
    from cmtr.connectors.pdb import run as pdb_run
    init_db(DB_PATH)
    logger.info("=== PDB Connector START ===")
    stats = pdb_run(DB_PATH)
    logger.info("=== PDB Connector DONE: %s ===", stats)
    return stats


def run_chembl():
    from cmtr.db.schema import init_db
    from cmtr.connectors.chembl import run as chembl_run
    init_db(DB_PATH)
    logger.info("=== ChEMBL Connector START ===")
    stats = chembl_run(DB_PATH)
    logger.info("=== ChEMBL Connector DONE: %s ===", stats)
    return stats


def run_all(incremental: bool = False):
    results = {}
    results["uniprot"] = run_uniprot(incremental=incremental)
    results["pdb"] = run_pdb()
    results["chembl"] = run_chembl()
    # Fase berikutnya: OpenTargets, PubMed
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CMTR Pipeline Runner")
    parser.add_argument("connector", nargs="?", default="all",
                        choices=["all", "uniprot", "pdb", "chembl"],
                        help="Connector yang dijalankan (default: all)")
    parser.add_argument("--incremental", action="store_true",
                        help="Mode incremental (hanya ambil data baru sejak sync terakhir)")
    args = parser.parse_args()

    if args.connector == "uniprot":
        run_uniprot(incremental=args.incremental)
    elif args.connector == "pdb":
        run_pdb()
    elif args.connector == "chembl":
        run_chembl()
    else:
        run_all(incremental=args.incremental)
