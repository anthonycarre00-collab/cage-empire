#!/usr/bin/env python3
"""CLEANUP-AND-FIX Bug 2: Reset unrealistic promotion cash balances.

The audit found Alpha Combat Federation (a Major promotion) with
$1.97B in cash — a value no real-world MMA promotion holds. This
script resets all promotions' current_cash to realistic starting
values based on size_tier:

  Major = $50,000,000
  Mid   = $10,000,000
  Small = $5,000,000

Idempotent: running twice produces the same result.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"

CASH_BY_TIER = {
    "major": 50_000_000.0,
    "mid":   10_000_000.0,
    "small":  5_000_000.0,
}


def reset_cash(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT promotion_id, name, size_tier, current_cash "
        "FROM promotions"
    ).fetchall()
    updates = []
    for (pid, name, tier, old_cash) in rows:
        new_cash = CASH_BY_TIER.get(tier)
        if new_cash is None:
            print(f"  WARN: promotion {pid} ({name}) has unknown "
                  f"size_tier={tier!r} — skipping")
            continue
        if old_cash != new_cash:
            conn.execute(
                "UPDATE promotions SET current_cash=?, updated_at="
                "CURRENT_TIMESTAMP WHERE promotion_id=?",
                (new_cash, pid),
            )
            updates.append((pid, name, tier, old_cash, new_cash))
    conn.commit()
    return {"total": len(rows), "updated": len(updates), "details": updates}


def main():
    db_path = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(DB_PATH)))
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    try:
        result = reset_cash(conn)
    finally:
        conn.close()

    print(f"Promotions cash reset: {result['updated']}/{result['total']} "
          f"updated.")
    for (pid, name, tier, old_cash, new_cash) in result["details"]:
        print(f"  {pid} {name} ({tier}): "
              f"${old_cash:,.0f} -> ${new_cash:,.0f}")


if __name__ == "__main__":
    main()
