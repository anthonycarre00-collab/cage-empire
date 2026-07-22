#!/usr/bin/env python3
"""World seed Phase 2: Gyms, Promotions, Staff.

Run AFTER Phase 1 (geography + weight classes + name pools must exist).
Idempotent — re-running inserts OR IGNOREs existing rows.

Creates:
  - ~300 gyms (15-20 elite, 60 national, 100 regional, 125 local)
    with distinct identities (facility_quality, medical_support,
    sparring_depth, development_focus, culture_tone, weight_cut_support)
  - 10 promotions (1 major player-target, 3 mid-tier, 6 small regional)
    with size_tier, broadcast_tier, budget, reputation, ai_aggression
  - ~250 staff (1 head coach per gym + 1 GM per promotion +
    2-3 commentators per promotion + 1 doctor + 1 cutman per promotion)

Per docs/WORLD_SEED_ANALYSIS.md Phase 2. Per CONVENTIONS §16.8, this
is a seed script — no schema changes.

Usage:
    python scripts/seed_world_phase2.py
"""
import sqlite3
import sys
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

random.seed(20260722)  # reproducible world

# ----------------------------------------------------------------
# Gym name components — used to generate distinct, believable gym names.
# ----------------------------------------------------------------
GYM_NAME_PREFIXES = [
    "Iron", "Steel", "Black", "Wolf", "Tiger", "Lion", "Eagle", "Bear",
    "Cobra", "Viper", "Dragon", "Phoenix", "Thunder", "Storm", "Savage",
    "Brutal", "Elite", "Apex", "Alpha", "Prime", "Royal", "Crown",
    "Kings", "Empire", "Legion", "Vanguard", "Forge", "Anvil", "Hammer",
    "Granite", "Ironworks", "Combat", "Fight", "Warrior", "Champion",
    "Victory", "Triumph", "Honor", "Glory", "Valor", "Martial",
    "Spartan", "Samurai", "Bushi", "Ronin", "Yamato", "Tatami",
    "Asahi", "Fusion", "Matrix", "NextGen", "Rising", "Nova",
    "Summit", "Peak", "Pinnacle", "Apex", "Summit", "Apex",
    "Coastal", "Harbor", "Riverside", "Downtown", "Uptown", "Midtown",
    "Northside", "Southside", "Eastside", "Westside", "Bay", "Hill",
    "Mountain", "Valley", "Forest", "Desert", "Ocean", "Sunset",
]
GYM_NAME_SUFFIXES = [
    "MMA", "Combat", "Fight Team", "Academy", "Gym", "Training Center",
    "Martial Arts", "Fight Club", "Training Camp", "Dojo", "Studio",
    "Lab", "Institute", "Training Center", "Gym & Spa", "Athletic",
    "Performance", "Conditioning", "Wrestling", "BJJ", "Boxing",
    "Striking", "Grappling", "Mixed Martial Arts", "Combat Sports",
]
CULTURE_TONES = ["balanced", "disciplined", "loose", "predator"]


# ----------------------------------------------------------------
# Promotions — 10 total. 1 major (player's), 3 mid, 6 small.
# Real-world-inspired tiering: major = UFC-scale, mid = Bellator/PFL-scale,
# small = regional show scale.
# ----------------------------------------------------------------
PROMOTIONS = [
    # (name, size_tier, nation_name, broadcast_tier, ownership_type, reputation, fan_trust, current_cash, starting_budget, ai_aggression, ai_spending_style, brand_tone)
    # MAJOR (1) — the player's promotion
    ("Alpha Combat Federation", "major", "United States", "ppv_global",
     "private", 85, 75, 50000000, 80000000, 30, "balanced", "prestige"),
    # MID-TIER (3)
    ("Rival Fight League",     "mid", "United States", "streaming",
     "private", 65, 60, 15000000, 25000000, 50, "aggressive", "spectacle"),
    ("Pacific Rim Championship","mid", "Japan", "tv_regional",
     "private", 60, 65, 12000000, 20000000, 45, "balanced", "tradition"),
    ("European Fight Network", "mid", "United Kingdom", "streaming",
     "private", 62, 58, 10000000, 18000000, 40, "conservative", "technical"),
    # SMALL (6) — regional promotions
    ("South American Warriors",  "small", "Brazil", "local_stream",
     "private", 45, 55, 3000000, 5000000, 60, "aggressive", "gritty"),
    ("Mexican Boxing & Brawl",   "small", "Mexico", "local_stream",
     "private", 40, 50, 2000000, 4000000, 65, "aggressive", "action"),
    ("Nordic Fight Nights",      "small", "Sweden", "local_stream",
     "private", 42, 60, 2500000, 4000000, 35, "conservative", "technical"),
    ("Eastern Bloc Combat",      "small", "Russia", "tv_regional",
     "private", 48, 45, 4000000, 6000000, 55, "aggressive", "hardcore"),
    ("Australian Outback Fights","small", "Australia", "local_stream",
     "private", 38, 55, 2000000, 3500000, 50, "balanced", "casual"),
    ("French Savate Championship","small", "France", "local_stream",
     "private", 35, 50, 1800000, 3000000, 30, "conservative", "traditional"),
]


def _gen_gym_name(rng):
    """Generate a unique-ish gym name from prefix + suffix."""
    p = rng.choice(GYM_NAME_PREFIXES)
    s = rng.choice(GYM_NAME_SUFFIXES)
    return f"{p} {s}"


def _gen_gym_specs(tier, rng):
    """Return (facility_quality, medical_support, sparring_depth,
    development_focus, culture_tone, weight_cut_support, reputation,
    membership_cost) for a gym of the given tier.

    Tier distribution:
      elite:    facility 85-98, medical 80-95, sparring 85-98, dev 85-98
      national: facility 65-85, medical 60-80, sparring 65-85, dev 65-85
      regional: facility 45-70, medical 45-70, sparring 50-75, dev 50-75
      local:    facility 25-55, medical 30-55, sparring 35-60, dev 35-60
    """
    if tier == "elite":
        f, m, s, d = (rng.randint(85, 98) for _ in range(4))
        rep = rng.randint(80, 98)
        cost = rng.uniform(150, 350)
    elif tier == "national":
        f = rng.randint(65, 85)
        m = rng.randint(60, 80)
        s = rng.randint(65, 85)
        d = rng.randint(65, 85)
        rep = rng.randint(60, 80)
        cost = rng.uniform(80, 180)
    elif tier == "regional":
        f, m, s, d = (rng.randint(45, 70), rng.randint(45, 70), rng.randint(50, 75), rng.randint(50, 75))
        rep = rng.randint(35, 60)
        cost = rng.uniform(40, 100)
    else:  # local
        f, m, s, d = (rng.randint(25, 55), rng.randint(30, 55), rng.randint(35, 60), rng.randint(35, 60))
        rep = rng.randint(15, 40)
        cost = rng.uniform(20, 60)
    culture = rng.choice(CULTURE_TONES)
    weight_cut = rng.randint(40, 90) if tier in ("elite", "national") else rng.randint(20, 60)
    return (f, m, s, d, culture, weight_cut, rep, cost)


def _gen_staff_name(nation_name, rng, conn):
    """Pick a first + last name from the name_pools table for the given nation."""
    rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='first_male' AND region=? "
        "ORDER BY RANDOM() LIMIT 1",
        (nation_name,),
    ).fetchall()
    male_firsts = [r[0] for r in rows] or ["John"]
    rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='last' AND region=? "
        "ORDER BY RANDOM() LIMIT 1",
        (nation_name,),
    ).fetchall()
    lasts = [r[0] for r in rows] or ["Smith"]
    return rng.choice(male_firsts), rng.choice(lasts)


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run `python src/build_db.py` then `python scripts/seed_world_phase1.py` first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Verify Phase 1 ran
    n_nations = conn.execute("SELECT COUNT(*) FROM nations").fetchone()[0]
    n_cities = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    if n_nations < 10 or n_cities < 50:
        print(f"ERROR: Phase 1 not run (nations={n_nations}, cities={n_cities}).")
        sys.exit(1)

    # ----------------------------------------------------------------
    # 1. Promotions (10)
    # ----------------------------------------------------------------
    print("Seeding promotions...")
    for (name, size_tier, nation_name, broadcast_tier, ownership, rep,
         fan_trust, cash, budget, ai_agg, ai_spend, brand_tone) in PROMOTIONS:
        nid = conn.execute(
            "SELECT nation_id FROM nations WHERE name=?", (nation_name,)
        ).fetchone()
        if nid is None:
            print(f"  SKIP promotion {name!r}: nation {nation_name!r} not found")
            continue
        nation_id = nid[0]
        # Pick a region in this nation (first one for HQ)
        rid = conn.execute(
            "SELECT region_id FROM regions WHERE nation_id=? ORDER BY region_id LIMIT 1",
            (nation_id,),
        ).fetchone()
        region_id = rid[0] if rid else None
        # Check existence by name (UNIQUE)
        existing = conn.execute(
            "SELECT promotion_id FROM promotions WHERE name=?", (name,)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO promotions (name, size_tier, nation_id, region_id, "
            "current_cash, reputation, fan_trust, brand_tone, starting_budget, "
            "broadcast_tier, ownership_type, ai_aggression, ai_spending_style) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, size_tier, nation_id, region_id, cash, rep, fan_trust,
             brand_tone, budget, broadcast_tier, ownership, ai_agg, ai_spend),
        )
    conn.commit()
    promo_count = conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
    print(f"  Promotions: {promo_count}")

    # ----------------------------------------------------------------
    # 2. Gyms (~300)
    # ----------------------------------------------------------------
    print("Seeding gyms...")
    # Target distribution: 18 elite, 60 national, 100 regional, 122 local = 300
    tier_targets = [("elite", 18), ("national", 60), ("regional", 100), ("local", 122)]
    # Get all cities (weighted by population — bigger cities get more gyms)
    cities = conn.execute(
        "SELECT city_id, nation_id, region_id, population FROM cities"
    ).fetchall()
    # Build a weighted list: each city appears N times where N = pop/100k (min 1)
    weighted_cities = []
    for cid, nid, rid, pop in cities:
        weight = max(1, int(pop / 100000))
        for _ in range(weight):
            weighted_cities.append((cid, nid, rid))
    rng = random.Random(20260722)

    used_names = set()
    existing_gym_names = {r[0] for r in conn.execute("SELECT name FROM gyms").fetchall()}
    used_names.update(existing_gym_names)

    # ----------------------------------------------------------------
    # FIRST: ensure every nation with cities has at least 2 gyms.
    # The population-weighted distribution below can leave small nations
    # (Ireland, Cuba, Dagestan, Sweden) with 0 gyms, which breaks
    # realism — fighters from those nations would have no home gym.
    # We seed a minimum of 2 "local" tier gyms per nation before the
    # weighted distribution runs.
    # ----------------------------------------------------------------
    nations_with_cities = conn.execute(
        "SELECT DISTINCT n.nation_id, n.name FROM nations n "
        "JOIN cities c ON c.nation_id=n.nation_id"
    ).fetchall()
    for nation_id, nation_name in nations_with_cities:
        existing = conn.execute(
            "SELECT COUNT(*) FROM gyms WHERE nation_id=?", (nation_id,)
        ).fetchone()[0]
        min_gyms = 3  # ensure at least 3 gyms per nation
        while existing < min_gyms:
            # Pick a city in this nation
            city_row = conn.execute(
                "SELECT city_id, region_id FROM cities WHERE nation_id=? "
                "ORDER BY RANDOM() LIMIT 1",
                (nation_id,),
            ).fetchone()
            if city_row is None:
                break
            cid, rid = city_row
            name = _gen_gym_name(rng)
            tries = 0
            while name in used_names and tries < 10:
                name = _gen_gym_name(rng)
                tries += 1
            if name in used_names:
                break
            used_names.add(name)
            # Local tier specs for minimum-coverage gyms
            f, m, s, d = (rng.randint(25, 55), rng.randint(30, 55), rng.randint(35, 60), rng.randint(35, 60))
            rep = rng.randint(15, 40)
            cost = rng.uniform(20, 60)
            culture = rng.choice(CULTURE_TONES)
            weight_cut = rng.randint(20, 60)
            conn.execute(
                "INSERT INTO gyms (name, city_id, nation_id, region_id, "
                "reputation, membership_cost, facility_quality, "
                "medical_support, sparring_depth, development_focus, "
                "culture_tone, weight_cut_support) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, cid, nation_id, rid, rep, cost, f, m, s, d, culture, weight_cut),
            )
            existing += 1

    # Now run the weighted distribution for the remaining target counts
    # (subtract the minimum-coverage gyms already created from the local target)
    local_already = conn.execute(
        "SELECT COUNT(*) FROM gyms"
    ).fetchone()[0]
    # Recalculate tier targets — reduce 'local' by what we already created
    tier_targets_adjusted = []
    for tier, target_count in tier_targets:
        if tier == "local":
            # Estimate how many local gyms we already created (rough: all minimum-coverage gyms are local)
            remaining = max(0, target_count - local_already)
            tier_targets_adjusted.append((tier, remaining))
        else:
            tier_targets_adjusted.append((tier, target_count))

    for tier, target_count in tier_targets_adjusted:
        n_created = 0
        attempts = 0
        while n_created < target_count and attempts < target_count * 5:
            attempts += 1
            # Pick a city (weighted)
            cid, nid, rid = rng.choice(weighted_cities)
            # Generate a unique gym name
            name = _gen_gym_name(rng)
            tries = 0
            while name in used_names and tries < 10:
                name = _gen_gym_name(rng)
                tries += 1
            if name in used_names:
                continue  # give up on this attempt
            used_names.add(name)
            # Generate specs for this tier
            specs = _gen_gym_specs(tier, rng)
            (facility, medical, sparring, dev_focus, culture,
             weight_cut, reputation, cost) = specs
            conn.execute(
                "INSERT INTO gyms (name, city_id, nation_id, region_id, "
                "reputation, membership_cost, facility_quality, "
                "medical_support, sparring_depth, development_focus, "
                "culture_tone, weight_cut_support) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, cid, nid, rid, reputation, cost, facility,
                 medical, sparring, dev_focus, culture, weight_cut),
            )
            n_created += 1
    conn.commit()
    gym_count = conn.execute("SELECT COUNT(*) FROM gyms").fetchone()[0]
    print(f"  Gyms: {gym_count}")

    # ----------------------------------------------------------------
    # 3. Staff (~300)
    #    - 1 head coach per gym (role='coach', specialty='head_coach')
    #    - 1 GM per promotion (role='general_manager')
    #    - 2-3 commentators per promotion (role='commentator')
    #    - 1 doctor per promotion (role='doctor')
    #    - 1 cutman per promotion (role='cutman')
    # ----------------------------------------------------------------
    print("Seeding staff...")
    # Coaches: one per gym
    gyms_data = conn.execute(
        "SELECT gym_id, nation_id, city_id FROM gyms"
    ).fetchall()
    for gym_id, nation_id, city_id in gyms_data:
        # Get nation name for name pool lookup
        nation_name = conn.execute(
            "SELECT name FROM nations WHERE nation_id=?", (nation_id,)
        ).fetchone()
        nation_name = nation_name[0] if nation_name else "United States"
        first, last = _gen_staff_name(nation_name, rng, conn)
        # Coach age: 35-65
        age = rng.randint(35, 65)
        # Specialty based on the gym's region style_preferences
        region_row = conn.execute(
            "SELECT r.style_preferences FROM gyms g JOIN regions r ON g.region_id=r.region_id WHERE g.gym_id=?",
            (gym_id,),
        ).fetchone()
        style_pref = region_row[0] if region_row and region_row[0] else "all_around"
        # Map style_pref to a coach specialty
        if "bjj" in style_pref or "submission" in style_pref:
            specialty = "bjj"
        elif "wrestling" in style_pref or "sambo" in style_pref:
            specialty = "wrestling"
        elif "boxing" in style_pref or "striking" in style_pref or "kickboxing" in style_pref:
            specialty = "striking"
        elif "judo" in style_pref:
            specialty = "judo"
        else:
            specialty = "mma"
        # Coaches don't have a promotion_id (they're at a gym, not a promotion)
        # The staff table has promotion_id but for coaches we leave it NULL.
        # The gym link isn't in the staff table — we'll need to add it via
        # a separate concept. For now, store gym_id in specialty field as
        # a hint (e.g. "head_coach:bjj:gym_id=42"). Actually, the staff
        # table doesn't have a gym_id column — we'll just note the gym
        # in the specialty.
        conn.execute(
            "INSERT INTO staff (first_name, last_name, age, nation_id, "
            "role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (first, last, age, nation_id, "coach", f"head_coach:{specialty}"),
        )
    # Promotion staff: GM, commentators, doctor, cutman
    promos = conn.execute(
        "SELECT promotion_id, nation_id FROM promotions"
    ).fetchall()
    for promo_id, nation_id in promos:
        nation_name = conn.execute(
            "SELECT name FROM nations WHERE nation_id=?", (nation_id,)
        ).fetchone()
        nation_name = nation_name[0] if nation_name else "United States"
        # GM (1)
        first, last = _gen_staff_name(nation_name, rng, conn)
        conn.execute(
            "INSERT INTO staff (first_name, last_name, age, nation_id, "
            "role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (first, last, rng.randint(40, 60), nation_id,
             "general_manager", "operations", promo_id),
        )
        # Commentators (2-3)
        n_comm = rng.randint(2, 3)
        for _ in range(n_comm):
            first, last = _gen_staff_name(nation_name, rng, conn)
            conn.execute(
                "INSERT INTO staff (first_name, last_name, age, nation_id, "
                "role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (first, last, rng.randint(30, 55), nation_id,
                 "commentator", "play_by_play", promo_id),
            )
        # Doctor (1)
        first, last = _gen_staff_name(nation_name, rng, conn)
        conn.execute(
            "INSERT INTO staff (first_name, last_name, age, nation_id, "
            "role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (first, last, rng.randint(35, 60), nation_id,
             "doctor", "sports_medicine", promo_id),
        )
        # Cutman (1)
        first, last = _gen_staff_name(nation_name, rng, conn)
        conn.execute(
            "INSERT INTO staff (first_name, last_name, age, nation_id, "
            "role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (first, last, rng.randint(30, 55), nation_id,
             "cutman", "cuts_and_swelling", promo_id),
        )
    conn.commit()
    staff_count = conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
    print(f"  Staff: {staff_count}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("World seed Phase 2 complete.")
    print(f"  Promotions: {promo_count}")
    print(f"  Gyms:       {gym_count}")
    print(f"  Staff:      {staff_count}")
    # Tier breakdown
    for tier in ("elite", "national", "regional", "local"):
        # No tier column in gyms — infer from reputation
        pass
    print()
    # Promotion breakdown
    for tier in ("major", "mid", "small"):
        n = conn.execute(
            "SELECT COUNT(*) FROM promotions WHERE size_tier=?", (tier,)
        ).fetchone()[0]
        print(f"  {tier} promotions: {n}")
    # Staff breakdown
    for role in ("coach", "general_manager", "commentator", "doctor", "cutman"):
        n = conn.execute(
            "SELECT COUNT(*) FROM staff WHERE role_type=?", (role,)
        ).fetchone()[0]
        print(f"  {role} staff: {n}")
    print("=" * 60)
    print()
    print("Next: python scripts/seed_world_phase3.py (4000 fighters)")

    conn.close()


if __name__ == "__main__":
    main()
