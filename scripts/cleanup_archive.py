#!/usr/bin/env python3
"""P4.1 — Archive cleanup: remove 0-fight completed events.

Per docs/COMPREHENSIVE_FIX_PLAN.md Group E #22:
  The Archive contains 171 completed events with 0 fights — seed
  artifacts, not real events. They confuse the player (an event in
  the past with no card, no result, no rating) and skew every
  per-event average (events per promotion, fan rating, etc.).

This script:
  1. Finds all events with status='completed' AND zero rows in
     fights (LEFT JOIN fights → COUNT=0).
  2. Deletes dependent rows first:
     - show_ratings rows for those events (cascade by hand — SQLite
       doesn't enforce FK cascades on this schema).
     - news_items rows tied to those events.
     - fight_participants rows would only exist if there were
       fights — but there are 0, so nothing to delete. We still
       guard against orphan fight_participants rows for safety.
  3. Deletes the event rows.
  4. Prints a summary: "Deleted N 0-fight events (and M show_ratings
     rows, K news_items rows)".

Idempotent — running twice is safe (the second run finds 0 events
to delete).

Usage:
  python scripts/cleanup_archive.py            # default DB
  python scripts/cleanup_archive.py path/to.db
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_DIR / "data" / "cage_empire.db"


def cleanup_zero_fight_events(db_path: Path | str = DEFAULT_DB,
                              *, dry_run: bool = False) -> dict:
    """Delete all completed events with 0 fights.

    Returns a summary dict:
      {events_deleted, show_ratings_deleted, news_items_deleted, event_ids}
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # Find the 0-fight completed events.
        rows = conn.execute(
            """
            SELECT e.event_id
            FROM events e
            LEFT JOIN fights f ON f.event_id = e.event_id
            WHERE e.status = 'completed'
            GROUP BY e.event_id
            HAVING COUNT(f.fight_id) = 0
            """
        ).fetchall()
        event_ids = [r[0] for r in rows]

        if not event_ids:
            return {
                "events_deleted": 0,
                "show_ratings_deleted": 0,
                "news_items_deleted": 0,
                "event_ids": [],
            }

        placeholders = ",".join("?" for _ in event_ids)

        # Count dependents (for reporting).
        sr_count = conn.execute(
            f"SELECT COUNT(*) FROM show_ratings WHERE event_id IN ({placeholders})",
            event_ids,
        ).fetchone()[0]
        ni_count = conn.execute(
            f"SELECT COUNT(*) FROM news_items WHERE event_id IN ({placeholders})",
            event_ids,
        ).fetchone()[0]

        if dry_run:
            return {
                "events_deleted": len(event_ids),
                "show_ratings_deleted": sr_count,
                "news_items_deleted": ni_count,
                "event_ids": event_ids,
                "dry_run": True,
            }

        # Delete dependents first, then events.
        conn.execute(
            f"DELETE FROM show_ratings WHERE event_id IN ({placeholders})",
            event_ids,
        )
        conn.execute(
            f"DELETE FROM news_items WHERE event_id IN ({placeholders})",
            event_ids,
        )
        # Defensive: orphan fight_participants (shouldn't exist if 0
        # fights, but the foreign key chain might have residue).
        conn.execute(
            f"""
            DELETE FROM fight_participants
            WHERE fight_id IN (
              SELECT fight_id FROM fights WHERE event_id IN ({placeholders})
            )
            """,
            event_ids,
        )
        conn.execute(
            f"DELETE FROM fights WHERE event_id IN ({placeholders})",
            event_ids,
        )
        conn.execute(
            f"DELETE FROM events WHERE event_id IN ({placeholders})",
            event_ids,
        )
        conn.commit()

        return {
            "events_deleted": len(event_ids),
            "show_ratings_deleted": sr_count,
            "news_items_deleted": ni_count,
            "event_ids": event_ids,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    db_path = Path(argv[0]) if argv else DEFAULT_DB

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"[cleanup_archive] DB: {db_path}")
    print(f"[cleanup_archive] Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    result = cleanup_zero_fight_events(db_path, dry_run=dry_run)
    print(
        f"[cleanup_archive] Deleted {result['events_deleted']} 0-fight events "
        f"(and {result['show_ratings_deleted']} show_ratings rows, "
        f"{result['news_items_deleted']} news_items rows)."
    )
    if dry_run and result["event_ids"]:
        preview = result["event_ids"][:10]
        print(f"[cleanup_archive] First 10 event_ids: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
