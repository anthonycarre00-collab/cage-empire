#!/usr/bin/env python3
"""CLEANUP-AND-FIX Bug 1: Reconcile rivalries counter drift.

The audit found that 86 of 343 rivalries show a 0-0 head-to-head
record despite fights_count > 0 — the per-fighter win/loss/draw
counters drifted out of sync with fight_history.

This script:
  1. For each rivalry (fighter_a_id, fighter_b_id), counts fights
     from fight_history where fighter_id=A and opponent_id=B (one
     perspective per fight is enough — every fight produces 2 rows,
     one for each fighter, with mirrored outcomes).
  2. Recomputes fighter_a_wins (A's 'win' rows), fighter_b_wins
     (A's 'loss' rows, since A losing = B winning), draws (A's
     'draw' rows).
  3. UPDATEs the rivalries row with the recomputed values.

Idempotent: running twice produces the same result.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"


def reconcile(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT rivalry_id, fighter_a_id, fighter_b_id, "
        "fights_count, fighter_a_wins, fighter_b_wins, draws "
        "FROM rivalries"
    ).fetchall()

    updated = 0
    unchanged = 0
    mismatches = []
    for (rivalry_id, a_id, b_id, fc, aw, bw, dr) in rows:
        # Count from A's perspective only — every fight produces 2
        # fight_history rows (one for each fighter), so this avoids
        # double-counting.
        outcomes = conn.execute(
            "SELECT outcome, COUNT(*) FROM fight_history "
            "WHERE fighter_id = ? AND opponent_id = ? "
            "GROUP BY outcome",
            (a_id, b_id),
        ).fetchall()
        outcome_map = {o: c for o, c in outcomes}
        new_aw = int(outcome_map.get("win", 0))
        new_bw = int(outcome_map.get("loss", 0))
        new_dr = int(outcome_map.get("draw", 0))
        new_fc = new_aw + new_bw + new_dr

        if (new_fc, new_aw, new_bw, new_dr) != (fc, aw, bw, dr):
            conn.execute(
                "UPDATE rivalries SET fights_count=?, fighter_a_wins=?, "
                "fighter_b_wins=?, draws=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE rivalry_id=?",
                (new_fc, new_aw, new_bw, new_dr, rivalry_id),
            )
            updated += 1
            if fc != new_fc or aw != new_aw or bw != new_bw or dr != new_dr:
                mismatches.append(
                    (rivalry_id, a_id, b_id, (fc, aw, bw, dr),
                     (new_fc, new_aw, new_bw, new_dr))
                )
        else:
            unchanged += 1

    conn.commit()
    return {
        "total": len(rows),
        "updated": updated,
        "unchanged": unchanged,
        "sample_mismatches": mismatches[:10],
    }


def main():
    db_path = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(DB_PATH)))
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    try:
        result = reconcile(conn)
    finally:
        conn.close()

    print(f"Rivalries reconciled: {result['updated']}/{result['total']} "
          f"updated, {result['unchanged']} unchanged.")
    if result["sample_mismatches"]:
        print("\nSample mismatches (rivalry_id, A, B, "
              "old (fc,aw,bw,dr) -> new (fc,aw,bw,dr)):")
        for m in result["sample_mismatches"]:
            print(f"  {m[0]}: {m[1]} vs {m[2]}: {m[3]} -> {m[4]}")


if __name__ == "__main__":
    main()
