#!/usr/bin/env python3
"""HW8.4 — Cleanup future-dated news items left in the world DB.

After HW5.1 ran, the world DB was clean. But subsequent sim ticks
(before HW8.1 was applied) generated ~89 future-dated news items
via news callsites that don't clamp published_at to sim_date (the
news engine, signing news, small_reward news, etc.). These are the
SAME class of bug as HW5.4 (social post_date) but for other news
writers.

This script:
  1. Counts future-dated news_items (audit info).
  2. Backs up the DB to data/cage_empire.db.bak.pre-hw8-cleanup-*.
  3. Deletes news_items WHERE published_at > sim_date.
  4. Reports the deletion.

Idempotent: safe to re-run. If run when the DB is clean, it will
report 0 rows affected + not create a backup.

Usage:
    python3 scripts/hw8_cleanup_future_dated.py
    python3 scripts/hw8_cleanup_future_dated.py --dry-run
    python3 scripts/hw8_cleanup_future_dated.py --db /path/to/db
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_DIR / "data" / "cage_empire.db"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help="Path to the DB file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report counts without deleting")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))

    # Get sim_date
    sim_date_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not sim_date_row or not sim_date_row[0]:
        print("ERROR: no simulation_clock row found", file=sys.stderr)
        return 1
    sim_date = sim_date_row[0]
    print(f"sim_date: {sim_date}")
    print()

    # Audit: count future-dated news by topic
    print("--- Future-dated news_items by topic ---")
    rows = conn.execute(
        "SELECT topic, COUNT(*) FROM news_items "
        "WHERE published_at > ? GROUP BY topic ORDER BY 2 DESC",
        (sim_date,),
    ).fetchall()
    total = 0
    for topic, n in rows:
        print(f"  {topic:30s} {n}")
        total += n
    print(f"  {'TOTAL':30s} {total}")
    print()

    if total == 0:
        print("DB is already clean. Nothing to do.")
        conn.close()
        return 0

    if args.dry_run:
        print(f"[dry-run] Would delete {total} future-dated news_items.")
        conn.close()
        return 0

    # Backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.name}.bak.pre-hw8-cleanup-{timestamp}"
    print(f"Backing up DB to {backup_path}")
    shutil.copy2(str(db_path), str(backup_path))

    # Delete
    cur = conn.execute(
        "DELETE FROM news_items WHERE published_at > ?",
        (sim_date,),
    )
    n_deleted = cur.rowcount
    conn.commit()
    print(f"Deleted {n_deleted} future-dated news_items.")
    print()

    # Verify
    n_remaining = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE published_at > ?",
        (sim_date,),
    ).fetchone()[0]
    print(f"Remaining future-dated news_items: {n_remaining}")
    print()

    # Also check future-dated events (defensive — should be 0 after HW5.1)
    n_future_events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_date > ?",
        (sim_date,),
    ).fetchone()[0]
    print(f"Future-dated events (any status): {n_future_events}")
    if n_future_events > 0:
        print("  (HW8.1 prevents new future-dated events from being marked COMPLETED,")
        print("   but pre-existing future-dated SCHEDULED events are legitimate")
        print("   calendar items. Only COMPLETED future-dated events are bugs.)")
        n_future_completed = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_date > ? AND status='completed'",
            (sim_date,),
        ).fetchone()[0]
        print(f"  Future-dated COMPLETED events (bug): {n_future_completed}")

    conn.close()
    print()
    print("HW8.4 cleanup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
