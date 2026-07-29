#!/usr/bin/env python3
"""Fix roster sizes to realistic levels.

Real MMA promotion roster sizes:
  - Major (UFC-level): 50-70 fighters (not 1002!)
  - Mid (Bellator/ONE-level): 30-50 fighters
  - Small (regional): 10-25 fighters
  - Free agents: the rest (should be the LARGEST pool)

Current state (broken):
  Alpha Combat (major): 1002
  RFL (mid): 501
  Pacific Rim (mid): 501
  European Fight Network (mid): 501
  6 small promos: 224 each
  Free agents: 601

Target state (realistic):
  Alpha Combat (major): 60 fighters
  RFL (mid): 40 fighters
  Pacific Rim (mid): 40 fighters
  European Fight Network (mid): 40 fighters
  6 small promos: 15 each = 90
  Free agents: 4450 - 270 = 4180

This makes free agents the dominant pool (like real MMA — most
fighters are unsigned, looking for their shot).
"""
import sqlite3
import random
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cage_empire.db"

# Target roster sizes per promotion tier
TARGET_ROSTERS = {
    "major": 60,
    "mid": 40,
    "small": 15,
}


def main():
    print("=" * 60)
    print("CAGE EMPIRE — Roster Size Fix")
    print("=" * 60)

    # Back up DB first
    backup_path = DB_PATH.parent / "cage_empire.db.backup-roster-fix"
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backed up DB to {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Get all promotions with their tiers
    promos = conn.execute(
        "SELECT promotion_id, name, size_tier FROM promotions ORDER BY promotion_id"
    ).fetchall()

    print(f"\nFound {len(promos)} promotions")

    # For each promotion, trim the roster to the target size
    # Fighters removed from the roster become free agents (current_promotion_id = NULL)
    # but KEEP their contracts (the contract is a separate table — we're just
    # unassigning them from the promotion's active roster, like releasing them).
    # Actually, for realism: released fighters should have their contracts
    # expired/terminated. But that's complex. For now, just set
    # current_promotion_id = NULL (they become free agents).
    # Their fighter_contracts rows stay but are effectively voided.

    total_released = 0
    for promo_id, promo_name, size_tier in promos:
        target = TARGET_ROSTERS.get(size_tier, 20)

        # Get current roster
        roster = conn.execute(
            "SELECT fighter_id FROM fighters WHERE current_promotion_id=? AND is_active=1 ORDER BY fighter_id",
            (promo_id,)
        ).fetchall()
        current_size = len(roster)

        if current_size <= target:
            print(f"  {promo_name:40s} ({size_tier}): {current_size} (OK, target={target})")
            continue

        # Need to release (current_size - target) fighters
        to_release = current_size - target

        # Pick which fighters to release: prefer releasing lower-ranked / older / more losses
        # (realistic — promotions cut fighters who are losing or aging)
        # For simplicity, release the ones with the most losses
        release_candidates = conn.execute(
            """SELECT f.fighter_id FROM fighters f
               JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
               WHERE f.current_promotion_id=? AND f.is_active=1
               ORDER BY fc.record_losses DESC, fc.career_health ASC
               LIMIT ?""",
            (promo_id, to_release)
        ).fetchall()

        released_ids = [r[0] for r in release_candidates]

        # Set them as free agents
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id IN (%s)" %
            ",".join("?" * len(released_ids)),
            released_ids
        )

        # Also void their active contracts
        conn.execute(
            """UPDATE contracts SET status='terminated' 
               WHERE contract_id IN (
                   SELECT fc.contract_id FROM fighter_contracts fc
                   WHERE fc.fighter_id IN (%s)
               )""" % ",".join("?" * len(released_ids)),
            released_ids
        )

        total_released += to_release
        print(f"  {promo_name:40s} ({size_tier}): {current_size} → {target} (released {to_release})")

    conn.commit()

    # Verify
    print(f"\nTotal released to free agency: {total_released}")
    print("\nNew roster sizes:")
    for r in conn.execute("""
        SELECT p.name, p.size_tier, COUNT(f.fighter_id) as roster_size
        FROM promotions p
        LEFT JOIN fighters f ON p.promotion_id = f.current_promotion_id AND f.is_active=1
        GROUP BY p.promotion_id ORDER BY roster_size DESC
    """):
        print(f"  {r[0]:40s} tier={r[1]:8s} roster={r[2]}")

    fa = conn.execute("SELECT COUNT(*) FROM fighters WHERE current_promotion_id IS NULL AND is_active=1").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM fighters WHERE is_active=1").fetchone()[0]
    print(f"\nFree agents: {fa}")
    print(f"Total active: {total}")
    print(f"Under contract: {total - fa}")

    # Rebuild interpretation layer (momentum, pressure, career_phase, etc.)
    # for all fighters since their promotion status changed
    print("\nRebuilding interpretation layer...")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies

    n1 = compute_all_fighters(conn)
    print(f"  Context engine: {n1} fighters updated")
    n2 = compute_all_career_phases(conn)
    print(f"  Career phases: {n2} fighters updated")
    n3 = compute_all_families(conn)
    print(f"  Narrative families: {n3} fighters updated")
    n4 = compute_all_legacies(conn)
    print(f"  Legacy states: {n4} fighters updated")

    conn.commit()
    conn.close()
    print("\nDone! Roster sizes are now realistic.")


if __name__ == "__main__":
    main()
