#!/usr/bin/env python3
"""World seed Phase 3 (FROM PROFILES): 4,000 fighters from the supervisor's attached profiles.

Run AFTER Phase 1 (geography + WCs + names) and Phase 2 (gyms + promos).
REPLACES scripts/seed_world_phase3.py — uses the 4000 fighter profiles
the supervisor attached (download/fighter_image_prompts.txt) as the
foundation, with intelligent attribute assignment from bio keywords.

This script:
  1. Loads data/parsed_fighters.json (4000 fighters with bios)
  2. Loads data/assigned_attributes.json (26 attrs + 20 pers + potential per fighter)
  3. For each fighter:
     - Looks up nation_id, weight_class_id, style_archetype_id,
       personality_archetype_id from the DB
     - Assigns to a promotion (major/mid/small/free agent distribution)
     - Assigns to a gym (based on nation + style)
     - Generates date_of_birth from age
     - Generates physical stats (height from profile, reach from height)
     - Inserts into fighters + fighter_attributes + fighter_personality +
       fighter_career + rankings

Per docs/WORLD_SEED_ANALYSIS.md Phase 3. Per CONVENTIONS §16.8.

Usage:
    python scripts/seed_world_phase3_from_profiles.py

Prerequisites:
    python scripts/parse_fighter_profiles.py
    python scripts/assign_attributes_from_bios.py
"""
import sqlite3
import sys
import json
import random
from pathlib import Path
from datetime import date, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
PARSED_FILE = PROJECT_DIR / "data" / "parsed_fighters.json"
ATTRIBUTES_FILE = PROJECT_DIR / "data" / "assigned_attributes.json"

sys.path.insert(0, str(PROJECT_DIR / "src"))

random.seed(20260725)  # reproducible

# ----------------------------------------------------------------
# Distribution targets (matches original phase3).
# ----------------------------------------------------------------
PROMOTION_ROSTER_SIZES = {
    "major": 900,    # Alpha Combat Federation
    "mid":   450,    # 3 mid promos × 450
    "small": 200,    # 6 small promos × 200
    "free_agent": 550,
}
# Total: 900 + 1350 + 1200 + 550 = 4000

BATCH_SIZE = 100


def _lookup_nation_id(conn, nation_name):
    """Look up nation_id by name. Returns None if not found."""
    row = conn.execute(
        "SELECT nation_id FROM nations WHERE name=? OR name=?",
        (nation_name, nation_name.lower())
    ).fetchone()
    if row:
        return row[0]
    # Try partial match
    row = conn.execute(
        "SELECT nation_id FROM nations WHERE name LIKE ?",
        (f"%{nation_name}%",)
    ).fetchone()
    return row[0] if row else None


def _lookup_weight_class_id(conn, wc_name, gender):
    """Look up weight_class_id by name + gender."""
    # Try exact match
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=?",
        (wc_name,)
    ).fetchone()
    if row:
        return row[0]
    # Try with gender suffix
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name LIKE ?",
        (f"%{wc_name}%",)
    ).fetchone()
    return row[0] if row else None


def _lookup_archetype_id(conn, table, name):
    """Look up style_archetype_id or personality_archetype_id by name."""
    row = conn.execute(
        f"SELECT {table}_id FROM {table}s WHERE name=?",
        (name,)
    ).fetchone()
    if row:
        return row[0]
    # Try LIKE
    row = conn.execute(
        f"SELECT {table}_id FROM {table}s WHERE name LIKE ?",
        (f"%{name}%",)
    ).fetchone()
    return row[0] if row else None


def _pick_promotion_id(conn, fighter_idx, total_fighters, rng):
    """Assign a fighter to a promotion based on the distribution targets.

    Distribution (matches original phase3):
      - First 900 fighters → major promo (Alpha Combat, id=1)
      - Next 1350 fighters → 3 mid promos (450 each)
      - Next 1200 fighters → 6 small promos (200 each)
      - Last 550 fighters → free agents (promotion_id=NULL)
    """
    if fighter_idx < 900:
        # Major
        promos = conn.execute(
            "SELECT promotion_id FROM promotions WHERE size_tier='major' ORDER BY promotion_id"
        ).fetchall()
        return promos[0][0] if promos else 1
    elif fighter_idx < 2250:
        # Mid (3 promos × 450)
        promos = conn.execute(
            "SELECT promotion_id FROM promotions WHERE size_tier='mid' ORDER BY promotion_id"
        ).fetchall()
        if not promos:
            return None
        # Distribute 450 per promo
        idx_in_mid = fighter_idx - 900
        promo_idx = idx_in_mid // 450
        return promos[min(promo_idx, len(promos) - 1)][0]
    elif fighter_idx < 3450:
        # Small (6 promos × 200)
        promos = conn.execute(
            "SELECT promotion_id FROM promotions WHERE size_tier='small' ORDER BY promotion_id"
        ).fetchall()
        if not promos:
            return None
        idx_in_small = fighter_idx - 2250
        promo_idx = idx_in_small // 200
        return promos[min(promo_idx, len(promos) - 1)][0]
    else:
        # Free agent
        return None


def _pick_gym_id(conn, nation_id, style_arch_id, rng):
    """Pick a gym based on nation + style. Returns None if no suitable gym."""
    if nation_id is None:
        return None
    # Try to find a gym in the same nation
    rows = conn.execute(
        "SELECT gym_id FROM gyms WHERE nation_id=? ORDER BY RANDOM()",
        (nation_id,)
    ).fetchall()
    if rows:
        return rows[0][0]
    # Fall back to any gym
    rows = conn.execute("SELECT gym_id FROM gyms ORDER BY RANDOM()").fetchall()
    return rows[0][0] if rows else None


def _pick_birth_city_id(conn, nation_id, rng):
    """Pick a birth city from the fighter's nation."""
    if nation_id is None:
        return None
    rows = conn.execute(
        "SELECT city_id FROM cities WHERE nation_id=? ORDER BY RANDOM()",
        (nation_id,)
    ).fetchall()
    return rows[0][0] if rows else None


def _gen_date_of_birth(age, current_date, rng):
    """Generate a date_of_birth from age."""
    # current_date is a string like "2026-07-25"
    try:
        year = int(current_date[:4])
    except (ValueError, TypeError):
        year = 2026
    birth_year = year - age
    # Random month + day
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{birth_year}-{month:02d}-{day:02d}"


def _gen_reach_from_height(height_cm, rng):
    """Generate reach (wingspan) from height. Typically height ± 5cm."""
    return height_cm + rng.randint(-5, 10)


def main():
    print("=" * 72)
    print("CAGE EMPIRE — World Seed Phase 3 (FROM PROFILES)")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Parsed fighters: {PARSED_FILE}")
    print(f"Assigned attributes: {ATTRIBUTES_FILE}")
    print()

    if not PARSED_FILE.exists():
        print(f"FATAL: {PARSED_FILE} not found. Run scripts/parse_fighter_profiles.py first.")
        sys.exit(2)
    if not ATTRIBUTES_FILE.exists():
        print(f"FATAL: {ATTRIBUTES_FILE} not found. Run scripts/assign_attributes_from_bios.py first.")
        sys.exit(2)

    # Load parsed fighters + assigned attributes
    with open(PARSED_FILE, "r", encoding="utf-8") as f:
        fighters = json.load(f)
    with open(ATTRIBUTES_FILE, "r", encoding="utf-8") as f:
        attributes = json.load(f)

    print(f"Loaded {len(fighters)} parsed fighters")
    print(f"Loaded {len(attributes)} assigned attribute sets")

    if len(fighters) != len(attributes):
        print(f"WARNING: count mismatch — {len(fighters)} fighters vs {len(attributes)} attribute sets")

    # Build a lookup: fighter_id → attributes
    attr_lookup = {a["fighter_id"]: a for a in attributes}

    # Connect to DB
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Get current sim date
    clock_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    current_date = clock_row[0] if clock_row else "2026-07-25"

    # Check if fighters already exist
    existing = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    if existing > 0:
        print(f"\nNOTE: {existing} fighters already exist in DB.")
        print("This script will ADD to them (not replace). For a clean rebuild, run:")
        print("  python src/build_db.py --fresh")
        print("  python scripts/seed_world_phase1.py")
        print("  python scripts/seed_world_phase2.py")
        print("  python scripts/seed_world_phase3_from_profiles.py  # THIS SCRIPT")
        response = input("\nContinue and add fighters? [y/N]: ")
        if response.lower() != 'y':
            print("Aborted.")
            return

    # Stats
    n_created = 0
    n_skipped = 0
    n_no_nation = 0
    n_no_wc = 0
    n_no_style = 0
    n_no_pers = 0
    batch_count = 0

    print(f"\nCreating {len(fighters)} fighters from profiles...")

    for i, fighter in enumerate(fighters):
        fid = fighter["fighter_id"]
        attrs_data = attr_lookup.get(fid)
        if not attrs_data:
            n_skipped += 1
            continue

        # Look up nation
        nation_name = fighter.get("nation", "")
        nation_id = _lookup_nation_id(conn, nation_name)
        if nation_id is None:
            n_no_nation += 1
            # Fall back to US
            nation_id = _lookup_nation_id(conn, "United States")

        # Look up weight class
        wc_name = fighter.get("weight_class", "")
        gender = fighter.get("gender", "male")
        wc_id = _lookup_weight_class_id(conn, wc_name, gender)
        if wc_id is None:
            n_no_wc += 1
            # Fall back to Lightweight
            wc_id = _lookup_weight_class_id(conn, "Lightweight", gender) or 1

        # Look up style archetype
        style_name = fighter.get("style_archetype", "Balanced")
        style_arch_id = _lookup_archetype_id(conn, "style_archetype", style_name)
        if style_arch_id is None:
            n_no_style += 1
            style_arch_id = 1  # Balanced

        # Look up personality archetype
        pers_name = fighter.get("personality_archetype", "Calm")
        pers_arch_id = _lookup_archetype_id(conn, "personality_archetype", pers_name)
        if pers_arch_id is None:
            n_no_pers += 1
            pers_arch_id = 1  # Calm

        # Pick promotion + gym + birth city
        promo_id = _pick_promotion_id(conn, i, len(fighters), random)
        gym_id = _pick_gym_id(conn, nation_id, style_arch_id, random)
        birth_city_id = _pick_birth_city_id(conn, nation_id, random)

        # Generate date_of_birth from age
        age = fighter.get("age", 28)
        dob = _gen_date_of_birth(age, current_date, random)

        # Physical stats
        height_cm = fighter.get("height_cm", 175)
        reach_cm = _gen_reach_from_height(height_cm, random)
        stance = fighter.get("stance", "orthodox")
        handedness = fighter.get("handedness", "right")

        # Name
        first = fighter.get("first_name", "Unknown")
        last = fighter.get("last_name", "")
        nickname = fighter.get("nickname")

        # Generate a record based on age + potential
        potential = attrs_data.get("potential", 50)
        rng_for_record = random.Random(fid * 31 + 17)
        if age <= 22:
            wins = rng_for_record.randint(0, 5)
            losses = rng_for_record.randint(0, 5)
            draws = rng_for_record.randint(0, 1)
        elif age <= 27:
            wins = rng_for_record.randint(2, 10)
            losses = rng_for_record.randint(1, 8)
            draws = rng_for_record.randint(0, 2)
        elif age <= 32:
            wins = rng_for_record.randint(5, 20)
            losses = rng_for_record.randint(2, 12)
            draws = rng_for_record.randint(0, 3)
        elif age <= 37:
            wins = rng_for_record.randint(8, 25)
            losses = rng_for_record.randint(5, 18)
            draws = rng_for_record.randint(0, 4)
        else:
            wins = rng_for_record.randint(10, 35)
            losses = rng_for_record.randint(8, 25)
            draws = rng_for_record.randint(0, 5)

        # Career health based on age
        if age <= 27:
            career_health = 100
        elif age <= 32:
            career_health = random.randint(85, 100)
        elif age <= 37:
            career_health = random.randint(70, 90)
        else:
            career_health = random.randint(50, 75)

        # Win/loss streaks
        win_streak = wins - losses if wins > losses else 0
        loss_streak = losses - wins if losses > wins else 0
        win_streak = min(win_streak, random.randint(0, 5))
        loss_streak = min(loss_streak, random.randint(0, 4))

        # Insert fighter row
        cur = conn.execute(
            "INSERT INTO fighters (first_name, last_name, nickname, gender, "
            "date_of_birth, birth_city_id, birth_nation_id, "
            "weight_class_id, current_gym_id, current_promotion_id, "
            "fight_style_archetype_id, personality_archetype_id, "
            "is_active, is_retired, height_cm, reach_cm, stance, handedness, "
            "injury_proneness, weight_cut_difficulty, consistency, "
            "clutch_factor, marketability, fan_friendliness, promo_boost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (first, last, nickname, gender, dob,
             birth_city_id, nation_id, wc_id, gym_id, promo_id,
             style_arch_id, pers_arch_id,
             height_cm, reach_cm, stance, handedness,
             random.randint(20, 80),  # injury_proneness
             random.randint(20, 80),  # weight_cut_difficulty
             random.randint(40, 80),  # consistency
             random.randint(40, 80),  # clutch_factor
             random.randint(30, 90),  # marketability
             random.randint(30, 90),  # fan_friendliness
             random.randint(20, 80),  # promo_boost
             ),
        )
        new_fighter_id = cur.lastrowid

        # Insert fighter_attributes (26 columns from assigned_attributes.json)
        attr_cols = [c for c in attrs_data.keys()
                     if c not in ("fighter_id", "_personality", "potential")]
        attr_vals = [attrs_data[c] for c in attr_cols]
        placeholders = ", ".join(["?"] * len(attr_cols))
        col_list = ", ".join(attr_cols)
        conn.execute(
            f"INSERT INTO fighter_attributes (fighter_id, {col_list}) "
            f"VALUES (?, {placeholders})",
            (new_fighter_id, *attr_vals),
        )

        # Insert fighter_personality (20 columns from _personality dict)
        pers_data = attrs_data.get("_personality", {})
        pers_cols = list(pers_data.keys())
        pers_vals = list(pers_data.values())
        placeholders = ", ".join(["?"] * len(pers_cols))
        col_list = ", ".join(pers_cols)
        conn.execute(
            f"INSERT INTO fighter_personality (fighter_id, {col_list}) "
            f"VALUES (?, {placeholders})",
            (new_fighter_id, *pers_vals),
        )

        # Insert fighter_career
        conn.execute(
            "INSERT INTO fighter_career (fighter_id, record_wins, record_losses, "
            "record_draws, win_streak, loss_streak, career_health, potential, "
            "title_reigns) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (new_fighter_id, wins, losses, draws, max(0, win_streak),
             max(0, loss_streak), career_health, potential),
        )

        # Insert ranking row
        elo = 1000 + (wins - losses) * 8 + random.randint(-30, 30)
        conn.execute(
            "INSERT OR IGNORE INTO rankings (fighter_id, weight_class_id, "
            "promotion_id, rating, fights_count, wins, losses, draws) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_fighter_id, wc_id, promo_id, elo,
             wins + losses + draws, wins, losses, draws),
        )

        n_created += 1
        batch_count += 1
        if batch_count >= BATCH_SIZE:
            conn.commit()
            print(f"  {n_created}/{len(fighters)}...", flush=True)
            batch_count = 0

    conn.commit()
    print(f"\nDone. Created {n_created} fighters.")
    print(f"  Skipped (no attributes): {n_skipped}")
    print(f"  No nation found (fell back to US): {n_no_nation}")
    print(f"  No weight class found (fell back to LW): {n_no_wc}")
    print(f"  No style archetype found (fell back to Balanced): {n_no_style}")
    print(f"  No personality archetype found (fell back to Calm): {n_no_pers}")

    # Verify
    total = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    print(f"\nTotal fighters in DB: {total}")

    conn.close()


if __name__ == "__main__":
    main()
