#!/usr/bin/env python3
"""TIER3-MISSING §T3.2 (W29) — Economic reconciliation script.

For each promotion, for each month of sim time, this script:
  1. Computes opening_cash (the cumulative cash position at the
     start of the month = initial_cash + SUM(all txns before this
     month).
  2. Sums all revenue transactions in the month (amount > 0).
  3. Sums all expense transactions in the month (amount < 0).
  4. Computes expected_closing = opening + revenue + expenses
     (expenses are negative, so this is opening + net).
  5. Compares to actual closing_cash. The only "actual" snapshot
     available is promotions.current_cash (the live value at the
     end of the sim). For prior months, the chained expected_
     closing IS the next month's opening — there's no independent
     actual to compare against. The DISCREPANCY is only flagged
     for the FINAL month (current sim month), where the chained
     expected closing is compared to promotions.current_cash.

Flagging rule (per the brief): difference > $1.

The script does NOT modify the DB — it's a read-only diagnostic.

Report fields:
  - Total promotions checked.
  - Total months checked (sum of months with any txn activity
    across all promos).
  - Total discrepancies found (promotions where the final-month
    expected closing != actual current_cash by > $1).

Run from the project root:
    python3 scripts/economic_reconciliation.py
    python3 scripts/economic_reconciliation.py --db-path PATH
    python3 scripts/economic_reconciliation.py --verbose  # show every month

Exit codes:
    0 = report generated (may or may not have discrepancies)
    2 = script error (couldn't run)

CONVENTIONS compliance:
  §6  — Smoke test protocol. This is a diagnostic, not a test.
        Does NOT modify the DB.
  §13 — Design Law: Investment pillar — promotions' cash positions
        must be auditable so the player can trust the economic
        simulation.
  §14 — Voice Layer: N/A — raw numbers ARE allowed in this report
        (it's a measurement / diagnostic, not player-facing text).
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

# Revenue txn_types (amount > 0 expected). Per the finance.py
# _record_transaction helper, revenue amounts are positive and
# expense amounts are negative. We use the SIGN of the amount to
# classify, not the txn_type (defensive — a misclassified txn_type
# would still be correctly classified by sign).
REVENUE_TXN_TYPES = {
    "ticket_sales", "broadcast_revenue", "merchandise",
    "sponsorship", "concessions",
}
EXPENSE_TXN_TYPES = {
    "fighter_purse", "venue_rental", "staff_salary",
    "medical_cost", "signing_bonus", "weight_cut_penalty",
    "bonus_payment", "marketing", "show_quality_adjustment",
}

# Flagging threshold (per the brief: difference > $1).
DISCREPANCY_THRESHOLD = 1.0


def _month_key(date_str):
    """Convert 'YYYY-MM-DD' to 'YYYY-MM' (the month key)."""
    if not date_str or len(date_str) < 7:
        return None
    return date_str[:7]


def _get_initial_cash(conn, promotion_id):
    """Get the initial cash position for a promotion.

    The initial cash is the SUM of all finance_transactions on
    the FIRST day the promotion has any txn activity (typically
    2026-01-01 — the seed sponsorship date). This represents the
    "starting capital" the promotion had before any monthly
    activity.

    If the promotion has NO txns at all, return 0.0 (defensive).

    Returns: (initial_cash, first_date_str).
    """
    row = conn.execute(
        """
        SELECT MIN(transaction_date)
        FROM finance_transactions
        WHERE promotion_id = ?
        """,
        (promotion_id,),
    ).fetchone()
    first_date = row[0] if row else None
    if not first_date:
        return 0.0, None
    # Sum all txns on the first date (the seed sponsorship is
    # typically a single big positive amount, but there could
    # be multiple seed-time txns on the same date).
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM finance_transactions
        WHERE promotion_id = ? AND transaction_date = ?
        """,
        (promotion_id, first_date),
    ).fetchone()
    initial_cash = row[0] if row else 0.0
    return initial_cash, first_date


def _get_monthly_txns(conn, promotion_id):
    """Get all finance_transactions for a promotion, grouped by
    YYYY-MM month key.

    Returns: dict month_key → {'revenue': float, 'expenses': float,
    'count': int}.
    """
    rows = conn.execute(
        """
        SELECT transaction_date, amount
        FROM finance_transactions
        WHERE promotion_id = ?
        ORDER BY transaction_date
        """,
        (promotion_id,),
    ).fetchall()
    monthly = {}
    for date_str, amount in rows:
        month_key = _month_key(date_str)
        if not month_key:
            continue
        if month_key not in monthly:
            monthly[month_key] = {"revenue": 0.0, "expenses": 0.0,
                                  "count": 0}
        if amount is None:
            continue
        if amount >= 0:
            monthly[month_key]["revenue"] += amount
        else:
            monthly[month_key]["expenses"] += amount  # negative
        monthly[month_key]["count"] += 1
    return monthly


def reconcile_promotion(conn, promotion_id, promotion_name,
                        current_sim_date, verbose=False):
    """Reconcile a single promotion's cash position month-by-month.

    Returns: dict with reconciliation results.
    """
    initial_cash, first_date = _get_initial_cash(conn, promotion_id)
    monthly_txns = _get_monthly_txns(conn, promotion_id)

    # Read the actual current_cash from promotions table.
    row = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    actual_current_cash = row[0] if row else 0.0

    # Walk the months in chronological order. The opening_cash for
    # the first month is 0 (we treat the initial seed sponsorship
    # as the FIRST month's revenue, not as opening balance). This
    # matches the brief's "opening_cash = finance_transactions or
    # promotions.current_cash at month start" — for the first
    # month, there's no prior month to chain from, so opening = 0
    # and the seed sponsorship shows up as month-1 revenue.
    #
    # Actually, re-reading the brief: "opening_cash (from finance_
    # transactions or promotions.current_cash at month start)".
    # The seed sponsorship IS a finance_transaction, so it should
    # be treated as month-1 revenue (not as opening_cash). The
    # opening_cash for month 1 is 0 (the promo had no cash before
    # the seed sponsorship arrived).
    months_checked = 0
    chained_cash = 0.0
    month_details = []
    for month_key in sorted(monthly_txns.keys()):
        txns = monthly_txns[month_key]
        opening = chained_cash
        revenue = txns["revenue"]
        expenses = txns["expenses"]
        # expected_closing = opening + revenue + expenses (expenses
        # are already negative — so this is opening + net).
        expected_closing = opening + revenue + expenses
        months_checked += 1
        if verbose:
            month_details.append({
                "month": month_key,
                "opening": opening,
                "revenue": revenue,
                "expenses": expenses,
                "expected_closing": expected_closing,
                "txn_count": txns["count"],
            })
        chained_cash = expected_closing

    # The FINAL chained_cash is the expected current_cash. Compare
    # to the actual current_cash from promotions table.
    expected_current_cash = chained_cash
    discrepancy = actual_current_cash - expected_current_cash
    has_discrepancy = abs(discrepancy) > DISCREPANCY_THRESHOLD

    return {
        "promotion_id": promotion_id,
        "promotion_name": promotion_name,
        "initial_cash": initial_cash,
        "first_txn_date": first_date,
        "months_checked": months_checked,
        "expected_current_cash": expected_current_cash,
        "actual_current_cash": actual_current_cash,
        "discrepancy": discrepancy,
        "has_discrepancy": has_discrepancy,
        "month_details": month_details,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db-path", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    ap.add_argument("--verbose", action="store_true",
                    help="Show per-month details for each promotion.")
    args = ap.parse_args()

    db = Path(args.db_path)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    print(f"  TIER3-MISSING economic_reconciliation")
    print(f"  DB: {db}")

    conn = sqlite3.connect(str(db))

    # Read the current sim date (the "as of" date for the
    # reconciliation).
    sim_date_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    current_sim_date = sim_date_row[0] if sim_date_row else "unknown"

    # Get all promotions.
    promos = conn.execute(
        "SELECT promotion_id, name FROM promotions ORDER BY promotion_id"
    ).fetchall()

    print(f"  Sim date (as-of): {current_sim_date}")
    print(f"  Promotions to reconcile: {len(promos)}")
    print()

    total_promos = 0
    total_months = 0
    total_discrepancies = 0
    results = []
    for promo_id, promo_name in promos:
        result = reconcile_promotion(conn, promo_id, promo_name,
                                     current_sim_date,
                                     verbose=args.verbose)
        results.append(result)
        total_promos += 1
        total_months += result["months_checked"]
        if result["has_discrepancy"]:
            total_discrepancies += 1

    # Print the per-promotion summary.
    print(f"  {'Promotion':<32s} {'Months':>6s} {'Expected':>15s} "
          f"{'Actual':>15s} {'Discrepancy':>15s} {'Status':>10s}")
    print(f"  {'-'*32} {'-'*6} {'-'*15} {'-'*15} {'-'*15} {'-'*10}")
    for r in results:
        status = "FAIL" if r["has_discrepancy"] else "OK"
        print(f"  {r['promotion_name']:<32s} {r['months_checked']:>6d} "
              f"${r['expected_current_cash']:>13,.2f} "
              f"${r['actual_current_cash']:>13,.2f} "
              f"${r['discrepancy']:>+13,.2f} {status:>10s}")

    print()
    print(f"  SUMMARY:")
    print(f"    Total promotions checked:  {total_promos}")
    print(f"    Total months checked:      {total_months}")
    print(f"    Total discrepancies found: {total_discrepancies}")
    print(f"    Discrepancy threshold:     > ${DISCREPANCY_THRESHOLD:.2f}")

    if args.verbose:
        for r in results:
            if not r["month_details"]:
                continue
            print()
            print(f"  --- {r['promotion_name']} (id={r['promotion_id']}) "
                  f"---")
            print(f"    {'Month':<8s} {'Opening':>14s} {'Revenue':>14s} "
                  f"{'Expenses':>14s} {'Closing':>14s} {'Txns':>5s}")
            for m in r["month_details"]:
                print(f"    {m['month']:<8s} ${m['opening']:>12,.2f} "
                      f"${m['revenue']:>12,.2f} ${m['expenses']:>12,.2f} "
                      f"${m['expected_closing']:>12,.2f} "
                      f"{m['txn_count']:>5d}")

    conn.close()
    print()
    if total_discrepancies == 0:
        print(f"  RECONCILIATION PASS: all {total_promos} promotions "
              f"reconcile within ${DISCREPANCY_THRESHOLD:.2f}.")
    else:
        print(f"  RECONCILIATION FAIL: {total_discrepancies}/{total_promos} "
              f"promotions have a discrepancy > ${DISCREPANCY_THRESHOLD:.2f}.")
        print(f"  Likely causes (informational):")
        print(f"    - Direct UPDATE to promotions.current_cash without a")
        print(f"      matching finance_transactions row (the most common")
        print(f"      cause — the sim advances cash via UPDATE in some")
        print(f"      code paths without going through _record_transaction).")
        print(f"    - Pruning of old finance_transactions rows (the v3.31.0")
        print(f"      pruning service does NOT prune finance_transactions,")
        print(f"      but a manual cleanup script may have).")
        print(f"    - Manual DB edits (e.g. fix_champions.py,")
        print(f"      fix_quality_assignment.py) that update cash without")
        print(f"      recording a transaction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
