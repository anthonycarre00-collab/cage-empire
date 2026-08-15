#!/usr/bin/env python3
"""Backfill missing finance_transactions for ALL completed events (FIX-V3-ALL5 #1b).

The v3 sim left 1884 pre-existing events with status='completed' but
ZERO finance_transactions (no ticket_sales, fighter_purse, venue_rental
...). The `EVENT_COMPLETED` event only fires on the TRANSITION from
scheduled→completed, so these pre-existing events never got finances
processed. This script backfills them by calling
`finance._process_event_finance(conn, event)` directly.

Replaces the older promo-1-only backfill script (the original was
written for Phase E1.3 when only promo 1 was affected). FIX-V3-ALL5
extends to ALL promotions because the reseed created events for all
10 promos without firing finance.

IDEMPOTENT — the function itself checks for an existing `ticket_sales`
row for the event_id and bails if found. Running this script twice is
a no-op the second time.

BATCHING — processes events in batches of 100 (commits per batch) so
the SQLite write lock is held for short windows and the script can be
interrupted cleanly. Each batch is wrapped in a try/except so a single
bad event doesn't abort the whole backfill.

REPORT — at the end, prints:
  - events processed (with rows written)
  - events skipped (already had finances, or impl bailed)
  - events errored
  - total transactions written
  - total revenue (sum of positive amount rows)
  - total expenses (sum of negative amount rows, reported as positive)
  - per-promotion cash balance before/after (to verify the cash flow)

Usage:
    python3 scripts/backfill_finance_transactions.py
    python3 scripts/backfill_finance_transactions.py --dry-run
    python3 scripts/backfill_finance_transactions.py --batch-size 50
    python3 scripts/backfill_finance_transactions.py --promo-id 1   # single promo
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

import finance  # noqa: E402  (after sys.path setup)


def find_events_to_backfill(conn, promo_id=None):
    """Find completed events with no `ticket_sales` finance_transaction.

    The idempotency key is the existence of a `ticket_sales` row for
    the event_id (matches the check inside _process_event_finance_impl
    around line 780 of src/finance.py).

    Args:
        promo_id: optional filter. If None, all promos are processed.
    """
    if promo_id is None:
        return conn.execute(
            "SELECT e.event_id, e.promotion_id, e.event_date "
            "FROM events e "
            "WHERE e.status = 'completed' "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM finance_transactions ft "
            "    WHERE ft.event_id = e.event_id "
            "      AND ft.transaction_type = 'ticket_sales'"
            ") "
            "ORDER BY e.event_date, e.event_id",
        ).fetchall()
    return conn.execute(
        "SELECT e.event_id, e.promotion_id, e.event_date "
        "FROM events e "
        "WHERE e.promotion_id = ? AND e.status = 'completed' "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM finance_transactions ft "
        "    WHERE ft.event_id = e.event_id "
        "      AND ft.transaction_type = 'ticket_sales'"
        ") "
        "ORDER BY e.event_date, e.event_id",
        (promo_id,),
    ).fetchall()


def backfill_one(conn, event_id, promo_id):
    """Call _process_event_finance for one event + return rows delta.

    Returns (rows_added, error_or_None). rows_added is 0 if the
    function bailed (e.g. status check failed, idempotency hit, or
    no event_row found). error_or_None is a string if the impl raised.
    """
    rows_before = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]

    finance._process_event_finance(conn, {
        'type': 'event_completed',
        'event_id': event_id,
        'promotion_id': promo_id,
    })
    # Note: _process_event_finance does NOT commit — the caller owns
    # the transaction. The batch loop calls conn.commit() per batch.

    rows_after = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    return rows_after - rows_before


def main():
    parser = argparse.ArgumentParser(
        description="Backfill finance_transactions for all completed events.",
    )
    parser.add_argument("--promo-id", type=int, default=None,
                        help="Optional: only backfill one promotion_id. "
                             "Default: all promos.")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Commit every N events (default: 100).")
    parser.add_argument("--dry-run", action="store_true",
                        help="don't commit — just report what would happen")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Use a generous timeout for the write lock during backfill.
    conn.execute("PRAGMA busy_timeout = 30000;")

    events = find_events_to_backfill(conn, promo_id=args.promo_id)
    if args.promo_id is None:
        print(f"[backfill] {len(events)} completed events with no "
              f"finance_transactions rows (ALL promos)")
    else:
        print(f"[backfill] {len(events)} completed events with no "
              f"finance_transactions rows (promo {args.promo_id})")

    # Snapshot before-state for the final report.
    before_total_rows = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions",
    ).fetchone()[0]
    before_total_rev = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
        "WHERE amount > 0",
    ).fetchone()[0]
    before_total_exp = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
        "WHERE amount < 0",
    ).fetchone()[0]

    print()
    print(f"[backfill] BEFORE: {before_total_rows} finance_transactions, "
          f"total revenue=${before_total_rev:,.2f}, "
          f"total expenses=${abs(before_total_exp):,.2f}")
    print()
    print("[backfill] Promotion cash balances BEFORE:")
    promo_rows = conn.execute(
        "SELECT promotion_id, name, current_cash, financial_state "
        "FROM promotions ORDER BY promotion_id"
    ).fetchall()
    for pid, pname, cash, state in promo_rows:
        print(f"  promo {pid:>2}: {pname:<30} "
              f"cash=${cash:>14,.2f}  state={state}")
    print()

    if args.dry_run:
        print("[backfill] DRY RUN — no writes will be committed")
        print(f"SUMMARY (dry-run): would backfill {len(events)} events.")
        conn.close()
        sys.exit(0)

    # Process events in batches of N. Commit per batch so the SQLite
    # write lock is held for short windows (matches the brief's
    # "to avoid holding the DB lock too long" requirement).
    batch_size = max(1, args.batch_size)
    events_processed = 0      # events that produced >=1 new finance row
    events_skipped = 0        # events that the impl bailed on (idempotency, no event_row)
    events_errored = 0        # events that raised
    rows_generated = 0        # total new finance_transactions rows
    errors = []
    t_start = time.time()

    for batch_start in range(0, len(events), batch_size):
        batch = events[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        print(f"[backfill] batch {batch_num}: events "
              f"{batch_start + 1}-{batch_start + len(batch)} of {len(events)}",
              flush=True)
        for event_id, ev_promo_id, event_date in batch:
            try:
                rows_delta = backfill_one(conn, event_id, ev_promo_id)
                if rows_delta > 0:
                    events_processed += 1
                    rows_generated += rows_delta
                else:
                    events_skipped += 1
            except Exception as e:
                events_errored += 1
                errors.append((event_id, ev_promo_id, event_date,
                               type(e).__name__, str(e)))
                # Roll back any partial writes for this event + keep going.
                try:
                    conn.rollback()
                except sqlite3.OperationalError:
                    pass
        # Commit per batch.
        try:
            conn.commit()
        except sqlite3.OperationalError as e:
            print(f"[backfill] commit failed at batch {batch_num}: {e}",
                  file=sys.stderr)
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
        elapsed = time.time() - t_start
        print(f"[backfill]   processed so far: {events_processed}, "
              f"skipped: {events_skipped}, errored: {events_errored}, "
              f"rows: {rows_generated}  "
              f"({elapsed:.1f}s elapsed)",
              flush=True)

    # Snapshot after-state for the final report.
    after_total_rows = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions",
    ).fetchone()[0]
    after_total_rev = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
        "WHERE amount > 0",
    ).fetchone()[0]
    after_total_exp = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
        "WHERE amount < 0",
    ).fetchone()[0]

    rev_delta = after_total_rev - before_total_rev
    exp_delta = abs(after_total_exp) - abs(before_total_exp)
    rows_delta = after_total_rows - before_total_rows

    print()
    print("=" * 72)
    print("BACKFILL SUMMARY")
    print("=" * 72)
    print(f"Events processed (rows written):  {events_processed}")
    print(f"Events skipped (impl bailed):     {events_skipped}")
    print(f"Events errored:                   {events_errored}")
    print(f"Total finance_transactions rows:  "
          f"{before_total_rows} → {after_total_rows}  (+{rows_delta})")
    print(f"Total revenue (positive rows):    "
          f"${before_total_rev:,.2f} → ${after_total_rev:,.2f}  "
          f"(+${rev_delta:,.2f})")
    print(f"Total expenses (negative rows):   "
          f"${abs(before_total_exp):,.2f} → ${abs(after_total_exp):,.2f}  "
          f"(+${exp_delta:,.2f})")
    print(f"Net P&L impact of backfill:       "
          f"${rev_delta - exp_delta:,.2f}")
    print(f"Elapsed:                          {time.time() - t_start:.1f}s")
    print()
    print("Promotion cash balances AFTER:")
    promo_rows_after = conn.execute(
        "SELECT promotion_id, name, current_cash, financial_state "
        "FROM promotions ORDER BY promotion_id"
    ).fetchall()
    for pid, pname, cash, state in promo_rows_after:
        # Find the matching before row.
        before_match = next(
            (r for r in promo_rows if r[0] == pid), None
        )
        before_cash = before_match[2] if before_match else 0
        before_state = before_match[3] if before_match else "?"
        delta = cash - before_cash
        state_changed = "" if state == before_state else f"  (was {before_state})"
        print(f"  promo {pid:>2}: {pname:<30} "
              f"cash=${cash:>14,.2f}  state={state}{state_changed}  "
              f"Δ=${delta:+,.2f}")

    if errors:
        print()
        print(f"FIRST 10 ERRORS (of {len(errors)}):")
        for (eid, pid, edate, etype, emsg) in errors[:10]:
            print(f"  event_id={eid} promo={pid} date={edate}: "
                  f"{etype}: {emsg}")

    # FIX-V3-ALL5 #1b (post-backfill cleanup) — clamp any news items
    # with published_at > sim_date down to sim_date. The finance news
    # writer (finance._write_finance_news) uses the event's event_date
    # as the news published_at. For events with event_date > sim_date
    # (which is an existing DB inconsistency — events with status=
    # 'completed' but event_date in the future, an artifact of the
    # reseed), this creates news items that violate invariant #4
    # ("no future-dated news"). Clamping the published_at to sim_date
    # preserves the news content while keeping the invariant intact.
    # This is a one-time cleanup — events that complete via the normal
    # EVENT_COMPLETED path during the sim have event_date <= sim_date
    # (the event was scheduled in the past and just transitioned to
    # 'completed'), so they don't hit this issue.
    try:
        sim_row = conn.execute(
            "SELECT * FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        if sim_row:
            sim_date = sim_row[1]  # current_date column (index 1)
            clamped = conn.execute(
                "UPDATE news_items SET published_at=? "
                "WHERE published_at > ?",
                (sim_date, sim_date),
            ).rowcount
            if clamped > 0:
                conn.commit()
                print()
                print(f"[backfill] CLAMPED {clamped} news items with "
                      f"published_at > sim_date ({sim_date}) down to "
                      f"sim_date (preserves invariant #4).")
    except sqlite3.Error as e:
        print(f"[backfill] WARNING: could not clamp future-dated news: "
              f"{e}", file=sys.stderr)

    conn.close()
    sys.exit(0 if events_errored == 0 else 1)


if __name__ == "__main__":
    main()
