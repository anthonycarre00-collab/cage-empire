#!/usr/bin/env python3
"""RESEED Step 6 — Reseed titles.

For each promotion × weight_class where the promotion has ≥2 active
fighters:
  * Find the top-rated fighter (highest ELO from rankings).
  * Set as current_champion_fighter_id.
  * Set champion_since_date to a random date 1-12 months before
    sim_date.
  * Write/UPDATE titles table.

Promotions with <2 fighters in a weight class: title remains vacant
(is_vacant=1, current_champion_fighter_id=NULL).
"""
import os
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

SIM_DATE = date(2026, 7, 20)


def reseed():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    # For each title row, vacate it first.
    print("Vacating all titles...")
    conn.execute(
        "UPDATE titles SET current_champion_fighter_id = NULL, "
        "champion_since_date = NULL, title_defenses_count = 0, "
        "is_vacant = 1"
    )

    # For each promotion × weight_class, count active fighters
    # currently signed to that promotion.
    promo_wc_groups = {}
    rows = conn.execute(
        "SELECT f.fighter_id, f.weight_class_id, f.current_promotion_id "
        "FROM fighters f "
        "WHERE f.fighter_id BETWEEN 1 AND 4000 "
        "AND f.is_active = 1 AND f.is_retired = 0 "
        "AND f.current_promotion_id IS NOT NULL "
        "AND f.weight_class_id IS NOT NULL"
    ).fetchall()
    for fid, wc_id, pid in rows:
        promo_wc_groups.setdefault((pid, wc_id), []).append(fid)

    print(f"Promotion × weight_class groups: {len(promo_wc_groups)}")

    # For each group with ≥2 fighters, find the top-rated fighter from
    # rankings + assign as champion.
    rng = random.Random(20260815)
    champions_assigned = 0
    vacant_groups = 0

    for (pid, wc_id), fighter_ids in promo_wc_groups.items():
        if len(fighter_ids) < 2:
            vacant_groups += 1
            continue

        # Find the top-rated fighter.
        # rankings has UNIQUE (fighter_id, weight_class_id, promotion_id),
        # so we match on all three.
        placeholders = ",".join("?" * len(fighter_ids))
        top_row = conn.execute(
            f"SELECT r.fighter_id, r.rating FROM rankings r "
            f"WHERE r.fighter_id IN ({placeholders}) "
            f"AND r.weight_class_id = ? AND r.promotion_id = ? "
            f"ORDER BY r.rating DESC LIMIT 1",
            (*fighter_ids, wc_id, pid),
        ).fetchone()

        if not top_row:
            # Fall back to rankings without the promotion filter
            # (handles free-agents-assigned-to-promo-1 edge case).
            top_row = conn.execute(
                f"SELECT r.fighter_id, r.rating FROM rankings r "
                f"WHERE r.fighter_id IN ({placeholders}) "
                f"AND r.weight_class_id = ? "
                f"ORDER BY r.rating DESC LIMIT 1",
                (*fighter_ids, wc_id),
            ).fetchone()

        if not top_row:
            vacant_groups += 1
            continue

        champ_id = top_row[0]
        # Random date 1-12 months before sim_date.
        months_back = rng.randint(1, 12)
        # Approximate months as 30-day increments.
        since_date = SIM_DATE - timedelta(days=months_back * 30 + rng.randint(0, 29))
        if since_date > SIM_DATE:
            since_date = SIM_DATE - timedelta(days=30)

        # Update or insert the title row.
        existing = conn.execute(
            "SELECT title_id FROM titles "
            "WHERE promotion_id = ? AND weight_class_id = ?",
            (pid, wc_id),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE titles SET current_champion_fighter_id = ?, "
                "champion_since_date = ?, is_vacant = 0, "
                "title_reigns_count = ?, title_defenses_count = ?, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE title_id = ?",
                (champ_id, since_date.isoformat(),
                 rng.randint(1, 3),  # title_reigns_count
                 rng.randint(0, 4),  # title_defenses_count
                 existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO titles (promotion_id, weight_class_id, "
                "current_champion_fighter_id, champion_since_date, "
                "title_reigns_count, title_defenses_count, is_vacant) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (pid, wc_id, champ_id, since_date.isoformat(),
                 rng.randint(1, 3),
                 rng.randint(0, 4)),
            )

        champions_assigned += 1

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Title reseed complete ===")
    print(f"  Champions assigned : {champions_assigned}")
    print(f"  Vacant groups (≥2 required): {vacant_groups}")
    print(f"  Total promo×wc groups: {len(promo_wc_groups)}")
    return 0


if __name__ == "__main__":
    sys.exit(reseed())
