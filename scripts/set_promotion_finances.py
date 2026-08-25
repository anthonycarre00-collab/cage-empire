#!/usr/bin/env python3
"""RESEED Step 9 — Set promotion finances.

  * Set current_cash by size_tier:
      major (P1)        : $50,000,000
      mid   (P2-P4)     : $10,000,000 each
      small (P5-P10)    : $8,000,000 each   (Phase 8 PHASE8-A-ECONOMICS —
                                            was $5M; raised to give small
                                            promos ~60% more runway — the
                                            Phase 7 5y soak showed -$6.1M
                                            cumulative loss on $5M start)
  * Write opening-balance finance_transactions rows.
      DEVIATION: finance_transactions.transaction_type has a CHECK
      constraint that does NOT include 'opening_balance' (it would
      require a schema migration, which the plan forbids). We use
      'sponsorship' instead — same direction (inflow) and matches
      the existing 10 finance_transactions rows (all 'sponsorship').
  * Set financial_state='HEALTHY' for all promos.
  * Set reputation=50, fan_trust=50 for all promos (per plan).
"""
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

SIM_DATE = date(2026, 7, 20)

CASH_BY_TIER = {
    "major": 50_000_000,
    "mid":   10_000_000,
    "small":  8_000_000,  # Phase 8 PHASE8-A-ECONOMICS — was 5_000_000 (and 2_000_000 before NEWS-FINANCE-GYM-LEGACY Issue 7.3)
}


def set_finances():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    # Delete existing opening-balance transactions so re-runs are
    # idempotent. We can identify them by description match.
    cur = conn.execute(
        "DELETE FROM finance_transactions "
        "WHERE description = 'Opening balance (reseed)'"
    )
    print(f"Deleted {cur.rowcount} prior opening-balance transactions")

    promos = conn.execute(
        "SELECT promotion_id, name, size_tier FROM promotions "
        "ORDER BY promotion_id"
    ).fetchall()

    tx_count = 0
    for pid, name, size_tier in promos:
        cash = CASH_BY_TIER.get(size_tier, 2_000_000)
        # Update promotion cash + state + reputation + fan_trust.
        conn.execute(
            "UPDATE promotions SET current_cash = ?, "
            "financial_state = 'HEALTHY', reputation = 50, "
            "fan_trust = 50, updated_at = CURRENT_TIMESTAMP "
            "WHERE promotion_id = ?",
            (cash, pid),
        )

        # Write opening-balance transaction (using 'sponsorship' type).
        conn.execute(
            "INSERT INTO finance_transactions (promotion_id, "
            "transaction_type, amount, description, transaction_date) "
            "VALUES (?, 'sponsorship', ?, 'Opening balance (reseed)', ?)",
            (pid, cash, SIM_DATE.isoformat()),
        )
        tx_count += 1
        print(f"  promo {pid:2d} ({name}, {size_tier}): "
              f"${cash:>12,} - HEALTHY")

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Promotion finances set ===")
    print(f"  Promotions updated      : {len(promos)}")
    print(f"  Opening-balance tx rows : {tx_count}")
    return 0


if __name__ == "__main__":
    sys.exit(set_finances())
