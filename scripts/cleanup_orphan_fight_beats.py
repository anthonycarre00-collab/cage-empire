#!/usr/bin/env python3
"""TIER2-5YEAR §T2.1 — One-time cleanup of orphan fight_beats rows.

Background
----------
The Tier 1 worklog noted 53,503 orphan fight_beats: rows whose fight_id
points at a `fights` row whose `event_id` is missing from the `events`
table (a pre-existing data integrity issue from earlier HW8 cleanup).
These orphans don't grow (the daily fight_beats prune in
pruning_svc.py only deletes beats whose event IS in the events table
with status='completed' — so the orphans are never touched by it).

They're a fixed storage cost — they don't affect simulation correctness
because nothing reads them (no event → no UI lookup, no show_rating
recalculation, no morale "exciting fight" check). But they waste disk
space + slow down any full-table scan on fight_beats (e.g. ANALYZE,
schema diffs, backups).

This script is a ONE-TIME cleanup. It deletes:

    DELETE FROM fight_beats WHERE fight_id IN (
      SELECT f.fight_id FROM fights f
      LEFT JOIN events e ON e.event_id = f.event_id
      WHERE e.event_id IS NULL
    )

Batched (1000 rows per DELETE) to keep the WAL bounded + transaction
size sane. Idempotent: re-running on a clean DB is a no-op (the IN
subquery returns 0 rows).

Usage
-----
    python3 scripts/cleanup_orphan_fight_beats.py
    python3 scripts/cleanup_orphan_fight_beats.py --db PATH
    python3 scripts/cleanup_orphan_fight_beats.py --dry-run

Exit codes
----------
    0 — cleanup completed (or dry-run reported).
    2 — DB not found.
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

# Per pruning_svc.py — same batch size as the daily fight_beats prune.
_BATCH_SIZE = 1000


def _count_orphans(conn):
    """Return the count of orphan fight_beats rows."""
    row = conn.execute(
        "SELECT COUNT(*) FROM fight_beats fb "
        "JOIN fights f ON f.fight_id = fb.fight_id "
        "LEFT JOIN events e ON e.event_id = f.event_id "
        "WHERE e.event_id IS NULL"
    ).fetchone()
    return row[0] if row else 0


def _delete_orphan_batch(conn):
    """Delete one batch of orphan fight_beats. Returns rows deleted."""
    # SQLite doesn't support LIMIT in DELETE — use a subquery with LIMIT
    # to get the fight_ids, then delete all their beats.
    orphan_fights = conn.execute(
        "SELECT f.fight_id FROM fights f "
        "LEFT JOIN events e ON e.event_id = f.event_id "
        "WHERE e.event_id IS NULL "
        "LIMIT ?",
        (_BATCH_SIZE,),
    ).fetchall()
    if not orphan_fights:
        return 0
    fight_ids = [r[0] for r in orphan_fights]
    placeholders = ",".join("?" for _ in fight_ids)
    cur = conn.execute(
        f"DELETE FROM fight_beats WHERE fight_id IN ({placeholders})",
        fight_ids,
    )
    return cur.rowcount or 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report the orphan count but do not delete.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    print("=" * 76)
    print("CAGE EMPIRE — Orphan fight_beats cleanup (TIER2-5YEAR §T2.1)")
    print("=" * 76)
    print(f"  DB: {db}")
    print()

    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON;")

    # Pre-cleanup counts.
    total_before = conn.execute(
        "SELECT COUNT(*) FROM fight_beats"
    ).fetchone()[0]
    orphan_count = _count_orphans(conn)
    print(f"  fight_beats total (before): {total_before}")
    print(f"  orphan fight_beats:         {orphan_count}")
    print()

    if args.dry_run:
        print("  --dry-run: not deleting.")
        conn.close()
        return 0

    if orphan_count == 0:
        print("  No orphans to delete — nothing to do.")
        conn.close()
        return 0

    # Batched delete.
    print(f"  Deleting in batches of {_BATCH_SIZE}...")
    t0 = time.perf_counter()
    total_deleted = 0
    batch_num = 0
    while True:
        n = _delete_orphan_batch(conn)
        if n == 0:
            break
        conn.commit()
        total_deleted += n
        batch_num += 1
        if batch_num % 20 == 0:
            elapsed = time.perf_counter() - t0
            print(f"    batch {batch_num}: deleted {total_deleted} rows "
                  f"({elapsed:.1f}s elapsed)")
    elapsed = time.perf_counter() - t0

    # Post-cleanup counts.
    total_after = conn.execute(
        "SELECT COUNT(*) FROM fight_beats"
    ).fetchone()[0]
    orphans_after = _count_orphans(conn)
    print()
    print(f"  Deleted:                {total_deleted} rows "
          f"({batch_num} batches, {elapsed:.1f}s)")
    print(f"  fight_beats total (after): {total_after}")
    print(f"  orphan fight_beats (after): {orphans_after}")
    conn.close()

    if orphans_after != 0:
        print(f"  WARNING: {orphans_after} orphans remain — re-run the "
              "script to retry.", file=sys.stderr)
        return 1
    print("  OK — all orphans removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
