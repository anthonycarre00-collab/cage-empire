#!/usr/bin/env python3
"""Phase 4 (PHASE4-IMPLEMENT) — re-backfill finance_transactions + reset cash.

After changing finance.py (PPV buyrate, tier-scaled title/ME bonus,
tightened show-quality multipliers) and reassigning venues by tier,
the existing finance_transactions rows reflect the OLD model. To get
accurate historicals with the NEW model:

  1. DELETE all finance_transactions
  2. Re-run backfill_finance_transactions.py (re-processes all completed
     events with the new model)
  3. Reset all promo cash to realistic starting values (Major=$50M,
     Mid=$10M, Small=$5M) — the backfill re-applies historical txn
     deltas to cash, which we don't want for a clean starting state.

The reset values match Phase 3's post-backfill state so the player
starts with realistic cash reserves that reflect a new game state.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
BACKFILL_SCRIPT = PROJECT_DIR / "scripts" / "backfill_finance_transactions.py"

# Realistic starting cash per size_tier (matches Phase 3 signoff state).
# Phase 8 (PHASE8-A-ECONOMICS) — raised Small from $5M → $8M to give
# small promos ~60% more runway (5y soak showed -$6.1M cumulative loss
# on $5M starting cash → $5M-$6.1M = -$1.1M bankrupt. With $8M-$6.1M
# = $1.9M remaining, promos survive to year 5 even at the old per-event
# loss; combined with A1-A3 fixes (per-event loss reduced to ~$0), the
# buffer is robust).
TIER_STARTING_CASH = {
    "major": 50_000_000,
    "mid":   10_000_000,
    "small":  8_000_000,
}


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        return 1

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    print("=== Step 1: Wipe all finance_transactions ===")
    cur.execute("SELECT COUNT(*) FROM finance_transactions")
    before = cur.fetchone()[0]
    print(f"  Before: {before:,} rows")
    cur.execute("DELETE FROM finance_transactions")
    db.commit()
    cur.execute("SELECT COUNT(*) FROM finance_transactions")
    after = cur.fetchone()[0]
    print(f"  After: {after:,} rows")

    print()
    print("=== Step 2: Reset all promo cash to starting values ===")
    rows = cur.execute(
        "SELECT promotion_id, name, size_tier, current_cash FROM promotions "
        "ORDER BY size_tier, promotion_id",
    ).fetchall()
    for r in rows:
        new_cash = TIER_STARTING_CASH.get(r["size_tier"], 8_000_000)
        print(
            f"  P{r['promotion_id']} ({r['size_tier']:6s}): "
            f"{r['name'][:30]:30s} cash ${r['current_cash']:>13,.0f} → "
            f"${new_cash:>13,.0f}"
        )
        cur.execute(
            "UPDATE promotions SET current_cash=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE promotion_id=?",
            (new_cash, r["promotion_id"]),
        )
    db.commit()

    db.close()

    print()
    print("=== Step 3: Re-run backfill_finance_transactions.py ===")
    result = subprocess.run(
        ["python3", str(BACKFILL_SCRIPT)],
        cwd=str(PROJECT_DIR),
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"  ERROR: backfill script exited {result.returncode}",
              file=sys.stderr)
        return result.returncode

    print()
    print("=== Step 4: Reset cash again (undo backfill's historical deltas) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    rows = cur.execute(
        "SELECT promotion_id, name, size_tier, current_cash FROM promotions "
        "ORDER BY size_tier, promotion_id",
    ).fetchall()
    for r in rows:
        new_cash = TIER_STARTING_CASH.get(r["size_tier"], 8_000_000)
        print(
            f"  P{r['promotion_id']} ({r['size_tier']:6s}): "
            f"{r['name'][:30]:30s} cash ${r['current_cash']:>13,.0f} → "
            f"${new_cash:>13,.0f}"
        )
        cur.execute(
            "UPDATE promotions SET current_cash=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE promotion_id=?",
            (new_cash, r["promotion_id"]),
        )
    db.commit()

    print()
    print("=== Step 5: Verify final state ===")
    rows = cur.execute(
        """
        SELECT p.size_tier,
               COUNT(DISTINCT e.event_id) AS events,
               SUM(CASE WHEN ft.amount > 0 THEN ft.amount ELSE 0 END) AS total_rev,
               SUM(CASE WHEN ft.amount < 0 THEN ft.amount ELSE 0 END) AS total_exp
        FROM events e
        JOIN promotions p ON p.promotion_id = e.promotion_id
        LEFT JOIN finance_transactions ft ON ft.event_id = e.event_id
        WHERE e.status = 'completed'
          AND e.event_date >= '2026-01-01'
        GROUP BY p.size_tier
        ORDER BY p.size_tier
        """,
    ).fetchall()
    print("Per-event avg economics (events since 2026-01-01):")
    for r in rows:
        rev = r["total_rev"] or 0
        exp = r["total_exp"] or 0
        n = r["events"] or 1
        print(
            f"  {r['size_tier']:6s}: {r['events']:>3} events | "
            f"avg_rev=${rev/n:>10,.0f} | "
            f"avg_exp=${exp/n:>10,.0f} | "
            f"avg_profit=${(rev+exp)/n:>10,.0f}"
        )

    print()
    print("Final promo cash:")
    rows = cur.execute(
        "SELECT promotion_id, name, size_tier, current_cash, financial_state "
        "FROM promotions ORDER BY size_tier, promotion_id",
    ).fetchall()
    for r in rows:
        print(
            f"  P{r['promotion_id']} ({r['size_tier']:6s}): "
            f"{r['name'][:30]:30s} cash=${r['current_cash']:>13,.0f} "
            f"state={r['financial_state']}"
        )

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
