#!/usr/bin/env python3
"""Phase 8 (PHASE8-A-ECONOMICS) — re-apply economics model + reset cash.

Applies the Phase 8 Group A economics changes (A1: tier-scaled venue
cost multiplier, A2: raised small promo broadcast revenue floor, A3:
reduced small promo fighter purse multiplier 0.5→0.3, A4: small promo
starting cash $5M→$8M) to the existing DB.

The finance model constants live in `src/finance.py` — those constants
are read at runtime by `_process_event_finance_impl`. To refresh the
existing finance_transactions rows (which reflect the OLD model from
when each event was first processed), this script:

  1. Backs up the DB to `data/cage_empire.db.backup-pre-phase8`.
  2. Wipes all finance_transactions rows.
  3. Re-runs `scripts/backfill_finance_transactions.py` — re-processes
     every completed event with the NEW Phase 8 finance model.
  4. Resets all promo cash to the new starting values (Major=$50M,
     Mid=$10M, Small=$8M). This is the post-A4 starting band. The
     backfill step above mutated cash with historical P&L deltas; the
     reset undoes those deltas so the player starts a fresh sim with
     each promo at its tier's standard starting cash.
  5. Prints per-event avg profit by tier for events since 2026-01-01
     so we can verify the small promo avg profit is in the target
     band of -$10K to +$30K (was -$95K pre-Phase 8).

Idempotent: re-running produces the same result (backup file is
overwritten only if missing; finance_transactions are wiped clean;
cash is reset to the same starting values).

Usage:
    python3 scripts/phase8_apply_economics.py
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.db.backup-pre-phase8"
BACKFILL_SCRIPT = PROJECT_DIR / "scripts" / "backfill_finance_transactions.py"

# Phase 8 (PHASE8-A-ECONOMICS) — post-A4 starting cash band.
# Small raised from $5M to $8M (was $2M before NEWS-FINANCE-GYM-LEGACY
# Issue 7.3, then $5M post-Phase 4, now $8M post-Phase 8).
TIER_STARTING_CASH = {
    "major": 50_000_000,
    "mid":   10_000_000,
    "small":  10_000_000,  # PHASE9-B: was 8_000_000, raised to 10M for sustainability
}
TIER_STARTING_CASH_FALLBACK = 10_000_000  # for unknown tier — be generous (PHASE9-B)


def backup_db() -> int:
    """Copy DB to backup-pre-phase8 if not already backed up."""
    if BACKUP_PATH.exists():
        print(f"  Backup already exists: {BACKUP_PATH} (skipping)")
        return 0
    print(f"  Copying {DB_PATH.name} → {BACKUP_PATH.name}")
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"  Backup OK ({BACKUP_PATH.stat().st_size:,} bytes)")
    return 0


def wipe_finance_transactions(db: sqlite3.Connection) -> tuple[int, int]:
    """Delete all finance_transactions rows. Returns (before, after) counts."""
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM finance_transactions")
    before = cur.fetchone()[0]
    print(f"  Before: {before:,} finance_transactions rows")
    cur.execute("DELETE FROM finance_transactions")
    db.commit()
    cur.execute("SELECT COUNT(*) FROM finance_transactions")
    after = cur.fetchone()[0]
    print(f"  After:  {after:,} finance_transactions rows")
    return before, after


def reset_cash(db: sqlite3.Connection) -> int:
    """Reset all promo cash to the Phase 8 starting values."""
    cur = db.cursor()
    rows = cur.execute(
        "SELECT promotion_id, name, size_tier, current_cash "
        "FROM promotions ORDER BY size_tier, promotion_id",
    ).fetchall()
    n_updated = 0
    for pid, name, tier, old_cash in rows:
        new_cash = TIER_STARTING_CASH.get(tier, TIER_STARTING_CASH_FALLBACK)
        print(
            f"  P{pid} ({tier or '?':6s}): "
            f"{(name or '')[:30]:30s} "
            f"${old_cash:>13,.0f} → ${new_cash:>13,.0f}"
        )
        cur.execute(
            "UPDATE promotions SET current_cash=?, "
            "financial_state='HEALTHY', is_rebuilding=0, "
            "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
            (new_cash, pid),
        )
        n_updated += 1
    db.commit()
    return n_updated


def run_backfill() -> int:
    """Run scripts/backfill_finance_transactions.py as a subprocess."""
    print(f"  Running {BACKFILL_SCRIPT.name} ...")
    result = subprocess.run(
        ["python3", str(BACKFILL_SCRIPT)],
        cwd=str(PROJECT_DIR),
    )
    return result.returncode


def print_verification(db: sqlite3.Connection) -> None:
    """Per-event avg profit by tier + final promo state."""
    cur = db.cursor()
    print()
    print("=== Verification: per-event avg economics since 2026-01-01 ===")
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
    print(f"  {'tier':6s} | {'events':>6s} | {'avg_rev':>14s} | "
          f"{'avg_exp':>14s} | {'avg_profit':>14s}")
    print(f"  {'-'*6} | {'-'*6} | {'-'*14} | {'-'*14} | {'-'*14}")
    for r in rows:
        rev = r[2] or 0
        exp = r[3] or 0
        n = r[1] or 1
        profit_per_event = (rev + exp) / n
        marker = ""
        if r[0] == "small":
            if -10000 <= profit_per_event <= 30000:
                marker = " [PASS — in target band -$10K to +$30K]"
            else:
                marker = " [FAIL — outside target band -$10K to +$30K]"
        print(
            f"  {(r[0] or '?'):6s} | {r[1]:>6d} | "
            f"${rev/n:>13,.0f} | ${exp/n:>13,.0f} | "
            f"${profit_per_event:>13,.0f}{marker}"
        )

    print()
    print("=== Final promo state ===")
    rows = cur.execute(
        "SELECT promotion_id, name, size_tier, current_cash, "
        "financial_state FROM promotions "
        "ORDER BY size_tier, promotion_id",
    ).fetchall()
    n_healthy = 0
    n_total = 0
    for pid, name, tier, cash, state in rows:
        n_total += 1
        if state == "HEALTHY":
            n_healthy += 1
        print(
            f"  P{pid} ({tier or '?':6s}): "
            f"{(name or '')[:30]:30s} "
            f"cash=${cash:>13,.0f} state={state}"
        )
    print(f"\n  Healthy: {n_healthy}/{n_total} promos")


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    if not BACKFILL_SCRIPT.exists():
        print(f"ERROR: backfill script not found: {BACKFILL_SCRIPT}",
              file=sys.stderr)
        return 1

    print("=== Step 1: Backup DB ===")
    backup_db()

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        print()
        print("=== Step 2: Wipe all finance_transactions ===")
        wipe_finance_transactions(db)

        print()
        print("=== Step 3: Reset all promo cash to Phase 8 starting values ===")
        n = reset_cash(db)
        print(f"  Reset {n} promos to starting cash (small=$10M, mid=$10M, major=$50M)")
    finally:
        db.close()

    print()
    print("=== Step 4: Re-run backfill_finance_transactions.py ===")
    rc = run_backfill()
    if rc != 0:
        print(f"ERROR: backfill script exited {rc}", file=sys.stderr)
        return rc

    print()
    print("=== Step 5: Reset cash again (undo backfill's historical deltas) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        n = reset_cash(db)
        print(f"  Reset {n} promos to starting cash again (post-backfill)")
        db.commit()

        print()
        print("=== Step 6: Verification ===")
        print_verification(db)
    finally:
        db.close()

    print()
    print("=== Phase 8 economics applied successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
