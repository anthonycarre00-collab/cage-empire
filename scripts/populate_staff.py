#!/usr/bin/env python3
"""RESEED Step 8 — Populate additional staff.

Generates:
  * 10 matchmakers (1 per promotion) — currently MISSING entirely
  * 10 more scouts (total 30, 3 per promo) — promo currently has 2
  * 10 more cutmen (total 20, 2 per promo) — promo currently has 1

Each staff member:
  * first_name, last_name from name_pools
  * age 30-55
  * nation_id matching the promotion's nation_id
  * role_type ('matchmaker' / 'scout' / 'cutman')
  * promotion_id (matches the promo)
  * skill_level (major=70-85, mid=55-70, small=40-60)
  * salary_ask (proportional to skill: $40K-$120K)
  * contract_length_ask (2-3 years)

Also creates:
  * contracts row (contract_target_type='staff', 12-month active)
  * staff_contracts row (contract_role = role_type)
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

# (role_type, per_promo_count) — each promo gets this many of each.
ROLE_PLAN = [
    ("matchmaker", 1),  # 10 total (currently 0)
    ("scout", 1),       # 10 more (currently 2 per promo, will be 3)
    ("cutman", 1),      # 10 more (currently 1 per promo, will be 2)
]


def _skill_for_tier(tier, rng):
    if tier == "major":
        return rng.randint(70, 85)
    if tier == "mid":
        return rng.randint(55, 70)
    # small
    return rng.randint(40, 60)


def _salary_for_skill(skill):
    """$40K-$120K, scaled by skill (40 → $40K, 85 → $120K)."""
    base = 40000
    span = 80000
    # 40..85 → 0..1
    frac = max(0.0, min(1.0, (skill - 40) / 45.0))
    return round(base + frac * span, -3)  # round to nearest $1K


def _pick_name(conn, name_type):
    row = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type=? "
        "ORDER BY RANDOM() LIMIT 1",
        (name_type,),
    ).fetchone()
    return row[0] if row else None


def populate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    promos = conn.execute(
        "SELECT promotion_id, size_tier, nation_id FROM promotions "
        "ORDER BY promotion_id"
    ).fetchall()
    print(f"Promotions: {len(promos)}")

    rng = random.Random(20260815)

    staff_inserted = 0
    contracts_inserted = 0

    # 12-month contract starting at sim_date.
    start_date = SIM_DATE.isoformat()
    end_date = (SIM_DATE + timedelta(days=365)).isoformat()

    for pid, size_tier, promo_nation in promos:
        for role_type, count in ROLE_PLAN:
            for _ in range(count):
                # Pick gender at random → first name from correct pool.
                gender = rng.choice(["male", "female"])
                first = _pick_name(
                    conn,
                    "first_female" if gender == "female" else "first_male"
                ) or "Unknown"
                last = _pick_name(conn, "last") or "Staff"
                age = rng.randint(30, 55)
                skill = _skill_for_tier(size_tier, rng)
                salary = _salary_for_skill(skill)
                contract_len = rng.randint(2, 3)

                # Insert staff row.
                cur = conn.execute(
                    "INSERT INTO staff (first_name, last_name, age, "
                    "nation_id, role_type, promotion_id, skill_level, "
                    "salary_ask, contract_length_ask) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (first, last, age, promo_nation, role_type, pid,
                     skill, salary, contract_len),
                )
                staff_id = cur.lastrowid
                staff_inserted += 1

                # Insert contracts row.
                cur = conn.execute(
                    "INSERT INTO contracts (contract_target_type, "
                    "promotion_id, start_date, end_date, salary, "
                    "exclusive_flag, status) "
                    "VALUES ('staff', ?, ?, ?, ?, 1, 'active')",
                    (pid, start_date, end_date, salary),
                )
                contract_id = cur.lastrowid
                contracts_inserted += 1

                # Insert staff_contracts row.
                conn.execute(
                    "INSERT INTO staff_contracts (contract_id, "
                    "staff_id, contract_role) VALUES (?, ?, ?)",
                    (contract_id, staff_id, role_type),
                )

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Staff population complete ===")
    print(f"  New staff rows       : {staff_inserted}")
    print(f"  New contracts rows   : {contracts_inserted}")
    return 0


if __name__ == "__main__":
    sys.exit(populate())
