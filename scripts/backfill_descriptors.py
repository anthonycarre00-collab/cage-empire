#!/usr/bin/env python3
"""CLEANUP-AND-FIX Bug 6: Backfill missing fighter_descriptors.

The audit found that 31% of fighters (2000/6450) have no
fighter_descriptors row. The audit spec limits the fix to ACTIVE
fighters (is_active=1, is_retired=0) — retired fighters are
historical placeholders without fighter_attributes, so they cannot
be descriptorized without first backfilling their attributes (which
is out of scope for this task).

For each active fighter with no fighter_descriptors row, this script
calls fight_engine.update_fighter_descriptor_snapshot(conn, fid)
which INSERT OR REPLACEs the descriptor row.

Idempotent: skips fighters that already have a descriptor row.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"


def backfill(conn: sqlite3.Connection) -> dict:
    missing = conn.execute(
        "SELECT f.fighter_id FROM fighters f "
        "WHERE f.is_active=1 AND f.is_retired=0 "
        "  AND NOT EXISTS (SELECT 1 FROM fighter_descriptors fd "
        "                   WHERE fd.fighter_id=f.fighter_id)"
    ).fetchall()

    # Lazy import — fight_engine is under src/services/. The import
    # pulls in voice + interpretation modules which require src/ on
    # sys.path.
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    from services.fight_engine import update_fighter_descriptor_snapshot

    updated = 0
    errors = []
    for (fid,) in missing:
        try:
            update_fighter_descriptor_snapshot(conn, fid)
            updated += 1
        except Exception as e:
            errors.append((fid, type(e).__name__, str(e)))
            conn.rollback()
    conn.commit()
    return {"missing": len(missing), "updated": updated, "errors": errors}


def main():
    db_path = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(DB_PATH)))
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    try:
        result = backfill(conn)
    finally:
        conn.close()

    print(f"fighter_descriptors backfill: "
          f"{result['updated']}/{result['missing']} active fighters "
          f"descriptorized.")
    if result["errors"]:
        print(f"  {len(result['errors'])} errors:")
        for (fid, etype, emsg) in result["errors"][:5]:
            print(f"    fighter_id={fid}: {etype}: {emsg}")
    if result["missing"] == 0:
        print("  (No active fighters missing descriptors — DB already "
              "covered. 2000 retired fighters without descriptors are "
              "out of scope: they lack fighter_attributes, which "
              "update_fighter_descriptor_snapshot() requires.)")


if __name__ == "__main__":
    main()
