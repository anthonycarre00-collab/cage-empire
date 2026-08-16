#!/usr/bin/env python3
"""Phase 4 (PHASE4-IMPLEMENT) — re-apply all Phase 4 DB changes on a clean DB.

This is the canonical Phase 4 DB application script. It:
  1. Adds 4 small venues for Mexico (the only small-promo nation lacking them)
  2. Runs scripts/reassign_venues_by_tier.py to assign tier-appropriate venues
  3. Runs scripts/phase4_rebackfill_and_reset.py to wipe + re-backfill
     finance_transactions + reset all promo cash to starting values

Idempotent: re-running on an already-Phase-4 DB is safe (venue INSERTs
use INSERT OR IGNORE; reassignment is a no-op if venues already match;
backfill wipes + rewrites finance_transactions cleanly; cash reset is
always idempotent).

Usage:
    python3 scripts/phase4_apply_all.py
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# 4 small venues to add for Mexico (only nation missing small-tier venues)
NEW_MEXICO_VENUES = [
    # (city_id, name, capacity, venue_type)
    (72, "Tlatelolco Ballroom",     2200, "ballroom"),
    (72, "Centro Historico Hall",   1800, "ballroom"),
    (75, "Guadalajara Armory",      1500, "ballroom"),
    (75, "Lopez Mateos Hall",       2000, "theater"),
]


def add_mexico_venues() -> None:
    """Add 4 small venues for Mexico (idempotent via name uniqueness check)."""
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    added = 0
    skipped = 0
    for city_id, name, cap, vtype in NEW_MEXICO_VENUES:
        existing = cur.execute(
            "SELECT 1 FROM venues WHERE name=?", (name,),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        cur.execute(
            "INSERT INTO venues (city_id, name, capacity, venue_type, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (city_id, name, cap, vtype),
        )
        added += 1
        print(f"  + {name} (cap={cap}, {vtype}) in city_id={city_id}")
    db.commit()
    db.close()
    print(f"Mexico venues: {added} added, {skipped} already present")


def run_script(script_name: str) -> int:
    """Run a sibling script and return its exit code."""
    script_path = PROJECT_DIR / "scripts" / script_name
    print(f"\n=== Running {script_name} ===")
    result = subprocess.run(
        ["python3", str(script_path)],
        cwd=str(PROJECT_DIR),
    )
    return result.returncode


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        return 1

    print("=== Step 1: Add 4 small venues for Mexico ===")
    add_mexico_venues()

    print("\n=== Step 2: Reassign venues by tier ===")
    rc = run_script("reassign_venues_by_tier.py")
    if rc != 0:
        print(f"ERROR: venue reassignment exited {rc}", file=sys.stderr)
        return rc

    print("\n=== Step 3: Re-backfill finance_transactions + reset cash ===")
    rc = run_script("phase4_rebackfill_and_reset.py")
    if rc != 0:
        print(f"ERROR: backfill+reset exited {rc}", file=sys.stderr)
        return rc

    print("\n=== Phase 4 DB changes applied successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
