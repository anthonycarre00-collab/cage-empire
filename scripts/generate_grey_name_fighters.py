#!/usr/bin/env python3
"""RESEED Step 3 — Generate ~2000 grey-name opponents.

These fighters exist ONLY so fight_history.opponent_id can reference
them. They have:
  * first_name, last_name (from name_pools)
  * weight_class_id (random from existing weight classes)
  * gender (random)
  * date_of_birth (random, age 25-45 at sim start)
  * is_active=0, is_retired=1
  * NO attributes, NO personality, NO career, NO bio

They NEVER appear in roster screens or free agent lists (filtered out
by is_active=1 AND is_retired=0 everywhere).
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

SIM_DATE = date(2026, 7, 20)  # matches simulation_clock.current_date
GREY_NAME_COUNT = 2000


def _pick_name(conn, name_type, region=None):
    """Pick a random name from name_pools. Returns the value or None."""
    sql = "SELECT name_value FROM name_pools WHERE name_type=?"
    params = [name_type]
    if region:
        sql += " AND region=?"
        params.append(region)
    sql += " ORDER BY RANDOM() LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def generate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    # Determine starting fighter_id — must be > existing 4450 (so
    # 4451..6450). This is the explicit range the plan specifies.
    max_existing = conn.execute(
        "SELECT COALESCE(MAX(fighter_id), 0) FROM fighters"
    ).fetchone()[0]
    print(f"Max existing fighter_id: {max_existing}")

    start_id = max(4451, max_existing + 1)
    print(f"Starting grey-name fighter_id: {start_id}")

    # Pick a real weight class for each grey-name — use the distribution
    # of weight classes among the 4000 real fighters so grey-names match
    # the weight classes that real fighters actually compete in.
    wc_rows = conn.execute(
        "SELECT weight_class_id FROM fighters "
        "WHERE fighter_id BETWEEN 1 AND 4000 AND weight_class_id IS NOT NULL"
    ).fetchall()
    if not wc_rows:
        print("ERROR: no weight_class_id found in fighters 1..4000", file=sys.stderr)
        return 1
    wc_pool = [r[0] for r in wc_rows]

    # Gender pool — match real distribution.
    gender_pool = [r[0] for r in conn.execute(
        "SELECT gender FROM fighters WHERE fighter_id BETWEEN 1 AND 4000"
    ).fetchall()]

    rng = random.Random(20260815)

    inserted = 0
    skipped = 0
    # Bulk insert in batches.
    sql = (
        "INSERT INTO fighters (first_name, last_name, nickname, gender, "
        "date_of_birth, weight_class_id, is_active, is_retired, "
        "birth_nation_id, residence_nation_id) "
        "VALUES (?, ?, NULL, ?, ?, ?, 0, 1, ?, ?)"
    )

    batch = []
    for i in range(GREY_NAME_COUNT):
        fid = start_id + i
        # First, check if this fid already exists (idempotent re-runs).
        existing = conn.execute(
            "SELECT 1 FROM fighters WHERE fighter_id=?", (fid,)
        ).fetchone()
        if existing:
            skipped += 1
            continue

        # Pick gender → determines which name pool to draw from.
        gender = rng.choice(gender_pool)
        if gender == "female":
            first = _pick_name(conn, "first_female")
        else:
            first = _pick_name(conn, "first_male")
        if not first:
            first = "Unknown"
        last = _pick_name(conn, "last") or "Fighter"

        # Random DOB: age 25-45 at sim_date
        age_years = rng.randint(25, 45)
        # Random month/day offset so DOB spreads across the year.
        try:
            dob = SIM_DATE.replace(year=SIM_DATE.year - age_years)
        except ValueError:
            # Feb 29 edge case
            dob = SIM_DATE.replace(year=SIM_DATE.year - age_years, day=28)
        # Random month/day
        rand_days = rng.randint(0, 364)
        dob = dob - timedelta(days=rand_days)

        wc_id = rng.choice(wc_pool)

        # Nation — pick a random nation_id from nations table
        n_row = conn.execute(
            "SELECT nation_id FROM nations ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        nation_id = n_row[0] if n_row else None

        batch.append((first, last, gender, dob.isoformat(), wc_id,
                      nation_id, nation_id))
        inserted += 1

    if batch:
        conn.executemany(sql, batch)

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Grey-name fighter generation complete ===")
    print(f"  Inserted : {inserted}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Range    : fighter_id {start_id} .. {start_id + GREY_NAME_COUNT - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(generate())
