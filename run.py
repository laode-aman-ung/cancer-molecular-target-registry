#!/usr/bin/env python
"""
CMTR — Entry point utama.

Penggunaan:
  python run.py pipeline [uniprot|all] [--incremental]
  python run.py dashboard [--db data/cmtr.db]
  python run.py scheduler
"""

import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "pipeline":
        from cmtr.pipeline import run_uniprot, run_pdb, run_chembl, run_all
        connector = sys.argv[2] if len(sys.argv) > 2 else "all"
        incremental = "--incremental" in sys.argv
        if connector == "uniprot":
            run_uniprot(incremental=incremental)
        elif connector == "pdb":
            run_pdb()
        elif connector == "chembl":
            run_chembl()
        else:
            run_all(incremental=incremental)

    elif cmd == "dashboard":
        import os
        db = "data/cmtr.db"
        for arg in sys.argv[2:]:
            if arg.startswith("--db"):
                db = arg.split("=")[-1] if "=" in arg else sys.argv[sys.argv.index(arg)+1]
        from cmtr.monitoring.dashboard import show
        show(db)

    elif cmd == "scheduler":
        import scheduler as sched_module  # noqa: F401

    else:
        print(f"Perintah tidak dikenal: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
