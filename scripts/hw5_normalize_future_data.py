#!/usr/bin/env python3
"""HW5.1 — Normalise future-dated data (news, social_posts, events,
daily_echoes).

Audit finding (Hardening_Phase.md §HW5.1 / inv4 of
invariant_checker):
  The simulation_clock is at 2026-08-27, but the DB contains data
  dated 2027-06-22 → 2027-07-06 — leftovers from a previous sim
  advance that got rolled back (a "dead timeline"). Specifically:
    - 520 news_items with published_at > sim_date
    - 10 events with event_date > sim_date
    - 672 daily_echoes with echo_date > sim_date
    - 0 social_posts with post_date > sim_date (already clean)

  These future-dated rows break invariant #4 (news_date_not_future)
  and cause the dashboard "stale echoes" bug documented in HW3.4
  (future-dated echoes with orphan decision_ids dominate the
  dashboard).

  Per the HW5.1 spec ("50 future-dated news items → either delete or
  mark as scheduled"), the simplest correct fix is to DELETE them.
  These rows are NOT scheduled content (the sim has no scheduling
  system) — they're dead-timeline residue. Marking them as
  "scheduled" would require a new schema column, and they'd never
  fire anyway (no tick will advance past sim_date in normal play
  without overwriting them).

Idempotent: safe to re-run. If run after the first invocation, it
will report 0 rows affected.

Conventions:
  - Does NOT touch the sim_clock.
  - Does NOT touch news_items with published_at <= sim_date.
  - Backs up the DB to data/cage_empire.db.bak.pre-hw5-normalize-*
    before any writes (defensive — if a future agent disagrees with
    the deletion, the rows are recoverable).

Run from the project root:
    python3 scripts/hw5_normalize_future_data.py            # live DB
    python3 scripts/hw5_normalize_future_data.py --dry-run  # report only

Refs docs/Hardening_Phase.md §HW5.1, invariant #4.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))


def _sim_date(conn):
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts without writing rows.")
    ap.add_argument("--db", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    # Connect + read sim_date FIRST (before any backup/writes).
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON;")
    sim_date = _sim_date(conn)
    if not sim_date:
        print("ERROR: simulation_clock has no current_date — refusing "
              "to run (would delete everything).", file=sys.stderr)
        return 2
    print(f"  DB:        {db}")
    print(f"  sim_date:  {sim_date}")
    print()

    # Count future-dated rows in each affected table.
    n_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE published_at > ?",
        (sim_date,),
    ).fetchone()[0]
    n_social = conn.execute(
        "SELECT COUNT(*) FROM social_posts WHERE post_date > ?",
        (sim_date,),
    ).fetchone()[0]
    n_events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_date > ?",
        (sim_date,),
    ).fetchone()[0]
    n_echoes = conn.execute(
        "SELECT COUNT(*) FROM daily_echoes WHERE echo_date > ?",
        (sim_date,),
    ).fetchone()[0]
    # Also check daily_headlines (the legacy daily-headline table).
    n_headlines = 0
    try:
        n_headlines = conn.execute(
            "SELECT COUNT(*) FROM daily_headlines WHERE headline_date > ?",
            (sim_date,),
        ).fetchone()[0]
    except sqlite3.OperationalError:
        # daily_headlines may use a different column name; try
        # 'day' or 'date'.
        try:
            n_headlines = conn.execute(
                "SELECT COUNT(*) FROM daily_headlines WHERE date > ?",
                (sim_date,),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass

    print("  Future-dated rows (would be DELETED):")
    print(f"    news_items    (published_at > sim_date): {n_news}")
    print(f"    social_posts  (post_date > sim_date):    {n_social}")
    print(f"    events        (event_date > sim_date):   {n_events}")
    print(f"    daily_echoes  (echo_date > sim_date):    {n_echoes}")
    print(f"    daily_headlines (date > sim_date):       {n_headlines}")
    print()

    if args.dry_run:
        print("  --dry-run: no writes. Exiting.")
        conn.close()
        return 0

    # Backup the DB before writes (defensive — recoverable).
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db.parent / f"{db.name}.bak.pre-hw5-normalize-{ts}"
    shutil.copy2(db, backup_path)
    print(f"  Backed up DB → {backup_path.name}")
    print()

    # Delete future-dated rows.
    # news_items
    cur = conn.execute(
        "DELETE FROM news_items WHERE published_at > ?",
        (sim_date,),
    )
    n_news_deleted = cur.rowcount
    # social_posts (defensive — should be 0 already)
    cur = conn.execute(
        "DELETE FROM social_posts WHERE post_date > ?",
        (sim_date,),
    )
    n_social_deleted = cur.rowcount
    # events — also delete dependent rows first (fights, event_cards,
    # fight_history, matchup_analyses, weight_cut_log). These cascade
    # via FK if PRAGMA foreign_keys = ON; we set it above. But some
    # rows might have orphan fight_ids without FK enforcement on
    # sqlite_sequence — defensive: delete children explicitly.
    # Get the future event_ids first.
    future_event_ids = [r[0] for r in conn.execute(
        "SELECT event_id FROM events WHERE event_date > ?",
        (sim_date,),
    ).fetchall()]
    n_events_deleted = 0
    if future_event_ids:
        # Delete dependent rows first (these tables don't have ON
        # DELETE CASCADE in the schema — defensive cleanup).
        for child_table, child_col in [
            ("fights", "event_id"),
            ("event_cards", "event_id"),
            ("fight_history", "event_id"),
            ("matchup_analyses", "event_id"),
            ("weight_cut_log", "event_id"),
            ("daily_echoes", "event_id"),
        ]:
            try:
                conn.execute(
                    f"DELETE FROM {child_table} WHERE {child_col} IN "
                    f"({','.join('?' * len(future_event_ids))})",
                    future_event_ids,
                )
            except sqlite3.OperationalError:
                # Table might not have this column — skip.
                pass
        # Now delete the events themselves.
        cur = conn.execute(
            f"DELETE FROM events WHERE event_id IN "
            f"({','.join('?' * len(future_event_ids))})",
            future_event_ids,
        )
        n_events_deleted = cur.rowcount
    # daily_echoes — delete future-dated echoes (independent of events).
    cur = conn.execute(
        "DELETE FROM daily_echoes WHERE echo_date > ?",
        (sim_date,),
    )
    n_echoes_deleted = cur.rowcount
    # daily_headlines (defensive)
    n_headlines_deleted = 0
    if n_headlines > 0:
        try:
            cur = conn.execute(
                "DELETE FROM daily_headlines WHERE headline_date > ?",
                (sim_date,),
            )
            n_headlines_deleted = cur.rowcount
        except sqlite3.OperationalError:
            try:
                cur = conn.execute(
                    "DELETE FROM daily_headlines WHERE date > ?",
                    (sim_date,),
                )
                n_headlines_deleted = cur.rowcount
            except sqlite3.OperationalError:
                pass

    conn.commit()
    print("  Deleted rows:")
    print(f"    news_items:      {n_news_deleted}")
    print(f"    social_posts:    {n_social_deleted}")
    print(f"    events:          {n_events_deleted}")
    print(f"    daily_echoes:    {n_echoes_deleted}")
    print(f"    daily_headlines: {n_headlines_deleted}")
    print()

    # Verify.
    n_news_after = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE published_at > ?",
        (sim_date,),
    ).fetchone()[0]
    n_events_after = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_date > ?",
        (sim_date,),
    ).fetchone()[0]
    n_echoes_after = conn.execute(
        "SELECT COUNT(*) FROM daily_echoes WHERE echo_date > ?",
        (sim_date,),
    ).fetchone()[0]
    print("  Verification (should all be 0):")
    print(f"    future-dated news_items:   {n_news_after}")
    print(f"    future-dated events:       {n_events_after}")
    print(f"    future-dated daily_echoes: {n_echoes_after}")
    ok = (n_news_after == 0 and n_events_after == 0
          and n_echoes_after == 0)
    if ok:
        print()
        print("  ✓ ALL future-dated data normalised.")
    else:
        print()
        print("  ⚠ Some future-dated data remains — investigate.")
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
