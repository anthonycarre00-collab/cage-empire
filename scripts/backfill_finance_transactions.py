#!/usr/bin/env python3
"""Backfill promo 1's missing finance_transactions (Phase E1.3).

Per docs/ECON_STAFF_PLAN.md §0 + §1.5 bug #1 — promo 1 (the player's
promo, "Alpha Combat Federation") had exactly 1 finance_transactions
row ($80M sponsorship opening-balance seed on 2026-01-01) despite
431 completed events in the DB. Every event the player ran from the
GUI produced zero finance rows because `finance.register_subscribers`
was never called from `src/app_web.py` (the GUI entry point).

Phase E1.1 (commit 46223c7) wires the registration. This script
retroactively generates finance_transactions for every promo-1
completed event that has no existing rows, by calling
`finance._process_event_finance(conn, event)` directly.

IDEMPOTENT — the function itself checks for an existing
`ticket_sales` row for the event_id and bails if found. Running this
script twice is a no-op the second time.

BACKUP — `cp data/cage_empire.db data/cage_empire.db.bak.pre-e1-backfill`
was taken before the first run (mandatory per Phase E1.3 spec).

Usage:
    python scripts/backfill_finance_transactions.py
    python scripts/backfill_finance_transactions.py --promo-id 1   # default
    python scripts/backfill_finance_transactions.py --dry-run      # no writes
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

import finance  # noqa: E402  (after sys.path setup)


def find_events_to_backfill(conn, promo_id):
    """Find completed events for `promo_id` with no finance_transactions.

    The idempotency key is the existence of a `ticket_sales` row for
    the event_id (matches the check inside _process_event_finance at
    line ~108 of src/finance.py).
    """
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
    """Call _process_event_finance for one event + return row/cash delta.

    Returns (rows_added, cash_delta). Both 0 if the function bailed
    (e.g. status check failed or idempotency hit).

    Commits per-event so a failure halfway through doesn't lose the
    work already done.
    """
    rows_before = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    cash_before_row = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id = ?",
        (promo_id,),
    ).fetchone()
    cash_before = cash_before_row[0] if cash_before_row else 0.0

    # Call finance directly. The function does NOT commit — the caller
    # owns the transaction.
    finance._process_event_finance(conn, {
        'type': 'event_completed',
        'event_id': event_id,
        'promotion_id': promo_id,
    })
    conn.commit()

    rows_after = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    cash_after_row = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id = ?",
        (promo_id,),
    ).fetchone()
    cash_after = cash_after_row[0] if cash_after_row else 0.0

    return (rows_after - rows_before), (cash_after - cash_before)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill promo 1's missing finance_transactions.",
    )
    parser.add_argument("--promo-id", type=int, default=1,
                        help="promotion_id to backfill (default: 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="don't commit — just report what would happen")
    args = parser.parse_args()
    promo_id = args.promo_id

    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(2)

    if not args.dry_run:
        # Sanity-check the backup exists (mandatory per Phase E1.3).
        bak = DB_PATH.parent / (DB_PATH.name + ".bak.pre-e1-backfill")
        if not bak.exists():
            print(f"WARNING: backup file {bak.name} not found. "
                  f"Run `cp {DB_PATH.name} {bak.name}` before backfill.",
                  file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    events = find_events_to_backfill(conn, promo_id)
    print(f"[backfill] promo {promo_id}: {len(events)} completed events "
          f"with no finance_transactions rows")

    before_count = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE promotion_id = ?",
        (promo_id,),
    ).fetchone()[0]
    before_cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id = ?",
        (promo_id,),
    ).fetchone()[0]
    print(f"[backfill] BEFORE: promo {promo_id} has {before_count} "
          f"finance_transactions rows, current_cash=${before_cash:,.2f}")

    if args.dry_run:
        print("[backfill] DRY RUN — no writes will be committed")
        print()
        print(f"SUMMARY (dry-run): Would backfill {len(events)} events "
              f"for promo {promo_id}.")
        print(f"(Each completed event typically writes 7-9 "
              f"finance_transactions rows: ticket_sales, broadcast_revenue,")
        print(f"merchandise, fighter_purse x N, venue_rental, "
              f"staff_salary, medical_cost, + weight_cut_penalty x N.)")
        conn.close()
        sys.exit(0)

    rows_generated = 0
    cash_impact = 0.0
    events_backfilled = 0
    errors = 0

    for event_id, ev_promo_id, event_date in events:
        try:
            rows_delta, cash_delta = backfill_one(
                conn, event_id, ev_promo_id,
            )
            if rows_delta > 0:
                events_backfilled += 1
                rows_generated += rows_delta
                cash_impact += cash_delta
        except Exception as e:
            errors += 1
            print(f"[backfill] ERROR on event_id={event_id} "
                  f"({event_date}): {type(e).__name__}: {e}",
                  file=sys.stderr)
            # Roll back any partial writes for this event + keep going.
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass

    after_count = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE promotion_id = ?",
        (promo_id,),
    ).fetchone()[0]
    after_cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id = ?",
        (promo_id,),
    ).fetchone()[0]

    print(f"[backfill] AFTER:  promo {promo_id} has {after_count} "
          f"finance_transactions rows, current_cash=${after_cash:,.2f}")
    print(f"[backfill] errors: {errors}")
    print()
    print(f"SUMMARY: Backfilled {events_backfilled} events, generated "
          f"{rows_generated} finance_transactions rows, total cash "
          f"impact on promo {promo_id}: ${cash_impact:,.2f}")

    conn.close()
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
