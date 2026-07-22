#!/usr/bin/env python3
"""World seed Phase 3: 4,000 unique fighters.

Run AFTER Phase 1 (geography + WCs + names) and Phase 2 (gyms + promos).
Idempotent — re-running skips fighters already inserted.

Creates 4,000 fighters distributed across:
  - Weight classes: more at middle weights (LW, WW, MW), fewer at extremes (HW, SW)
  - Promotions: major=300, mid=150 each, small=50 each, free agents=400
  - Career stages: prospect (15%), developing (25%), prime (30%), declining (20%), veteran (10%)
  - Each fighter gets: full 25 attrs + 20 personality + physical + potential + archetype + gym

Each fighter is UNIQUE per the user directive — no two fighters share the
same first+last+nickname combination. Names are drawn from the region-
tagged name pool (Brazilian fighters get Brazilian names, etc.).

Per docs/WORLD_SEED_ANALYSIS.md Phase 3. Per CONVENTIONS §16.8.

Usage:
    python scripts/seed_world_phase3.py
"""
import sqlite3
import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(PROJECT_DIR / "src"))

import fighter_gen  # noqa: E402

random.seed(20260723)  # reproducible world — distinct from Phase 2's seed

# ----------------------------------------------------------------
# Distribution targets.
# ----------------------------------------------------------------
TARGET_FIGHTER_COUNT = 4000

# Promotion roster sizes (sums to ~4000 with free agents)
# major: 1 promo × 900 = 900
# mid:   3 promos × 450 = 1350
# small: 6 promos × 200 = 1200
# free agents: 550
# total: 900 + 1350 + 1200 + 550 = 4000
PROMOTION_ROSTER_SIZES = {
    "major": 900,    # Alpha Combat Federation — the player's promotion
    "mid":   450,    # RFL, Pacific Rim, European Fight Network (3 promos × 450 = 1350)
    "small": 200,    # 6 promos × 200 = 1200
}
FREE_AGENT_COUNT = 550  # unsigned — available for the player to sign

# Career stage distribution (15/25/30/20/10 = 100%)
CAREER_STAGE_WEIGHTS = [
    ("prospect",   0.15),   # age 18-22, 0-5 fights
    ("developing", 0.25),   # age 23-27, 5-12 fights
    ("prime",      0.30),   # age 28-32, 12-25 fights
    ("declining",  0.20),   # age 33-37, 20-32 fights
    ("veteran",    0.10),   # age 38-43, 28-45 fights
]

# Weight class distribution — more at middle weights, fewer at extremes.
# Format: weight_class_name -> relative weight (not absolute count)
WC_DISTRIBUTION_WEIGHTS_MALE = {
    "Heavyweight":          6,    # few big men
    "Light Heavyweight":    8,
    "Middleweight":        12,
    "Welterweight":        14,    # most populous men's class
    "Lightweight":         15,    # most populous men's class
    "Featherweight":       12,
    "Bantamweight":        10,
    "Flyweight":            7,
}
WC_DISTRIBUTION_WEIGHTS_FEMALE = {
    "Featherweight":        4,   # thin
    "Bantamweight":         6,
    "Flyweight":            8,
    "Strawweight":         10,   # most populous women's class
    "Atomweight":           4,   # thin
}

# Gender split: 88% male, 12% female (real-world UFC ratio is ~85/15)
GENDER_MALE_PCT = 0.88

# Archetype distribution — weighted toward balanced, fewer specialists.
# These are the BASE weights; national tendency overrides adjust them
# per-fighter based on birth nation (Brazil → more Grapplers, Dagestan
# → more Wrestlers, etc.).
ARCHETYPE_WEIGHTS = {
    "Balanced":              25,
    "Striker":               18,
    "Grappler":              15,
    "Wrestler":              15,
    "Brawler":               10,
    "Counter-Striker":       10,
    "Submission Specialist":  7,
}

# National tendency overrides. Each nation gets a dict of archetype →
# weight bonus (added to the base weight). A nation with strong BJJ
# culture (Brazil) gets +20 to Grappler + +15 to Submission Specialist.
# A nation with strong wrestling culture (Dagestan, Russia) gets +25 to
# Wrestler. This produces realistic national tendencies: ~30% of
# Brazilian fighters are Grapplers (vs ~15% baseline), ~35% of Dagestani
# fighters are Wrestlers (vs ~15% baseline).
NATION_ARCHETYPE_OVERRIDES = {
    "Brazil":       {"Grappler": 20, "Submission Specialist": 15, "Striker": 5},
    "Dagestan":     {"Wrestler": 30, "Grappler": 10},
    "Russia":       {"Wrestler": 15, "Grappler": 10, "Submission Specialist": 5},
    "Japan":        {"Striker": 10, "Wrestler": 5, "Submission Specialist": 8},
    "Netherlands":  {"Striker": 20, "Counter-Striker": 10},
    "Cuba":         {"Striker": 15, "Wrestler": 10},
    "Mexico":       {"Striker": 10, "Brawler": 15},
    "United States":{"Wrestler": 10, "Striker": 5, "Balanced": 5},
    "United Kingdom":{"Striker": 12, "Brawler": 8},
    "Ireland":      {"Striker": 15, "Brawler": 10},
    "Nigeria":      {"Striker": 12, "Brawler": 8},
    "South Korea":  {"Striker": 8, "Wrestler": 8, "Submission Specialist": 5},
    "Australia":    {"Striker": 8, "Grappler": 5, "Balanced": 5},
    "Canada":       {"Wrestler": 8, "Balanced": 5},
    "France":       {"Striker": 10, "Submission Specialist": 8},
    "Germany":      {"Wrestler": 10, "Striker": 5},
    "Poland":       {"Striker": 8, "Brawler": 8},
    "Sweden":       {"Wrestler": 10, "Striker": 5},
    "China":        {"Striker": 8, "Wrestler": 8, "Submission Specialist": 5},
    "Argentina":    {"Grappler": 10, "Striker": 8},
}

# Personality archetype distribution
PERSONALITY_ARCHETYPE_WEIGHTS = {
    "Calm":              25,
    "Aggressive":        20,
    "Methodical":        20,
    "Showman":           20,
    "Quiet Professional":15,
}


def _pick_weight_class(rng, gender, conn):
    """Pick a weight_class_id based on gender + distribution weights."""
    if gender == "male":
        weights = WC_DISTRIBUTION_WEIGHTS_MALE
    else:
        weights = WC_DISTRIBUTION_WEIGHTS_FEMALE
    names = list(weights.keys())
    w = list(weights.values())
    chosen_name = rng.choices(names, weights=w, k=1)[0]
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=? AND gender=?",
        (chosen_name, gender),
    ).fetchone()
    return row[0] if row else None


def _pick_career_stage(rng):
    """Pick a career stage based on the weights above."""
    labels = [s[0] for s in CAREER_STAGE_WEIGHTS]
    weights = [s[1] for s in CAREER_STAGE_WEIGHTS]
    return rng.choices(labels, weights=weights, k=1)[0]


def _gen_age_for_stage(stage, rng):
    """Generate an age appropriate for the career stage."""
    if stage == "prospect":
        return rng.randint(18, 22)
    elif stage == "developing":
        return rng.randint(23, 27)
    elif stage == "prime":
        return rng.randint(28, 32)
    elif stage == "declining":
        return rng.randint(33, 37)
    else:  # veteran
        return rng.randint(38, 43)


def _gen_record_for_stage(stage, potential, rng):
    """Generate (wins, losses, draws) appropriate for the career stage
    and the fighter's potential. High-potential fighters win more;
    low-potential fighters lose more. Veterans have more total fights.
    """
    if stage == "prospect":
        total = rng.randint(2, 6)
    elif stage == "developing":
        total = rng.randint(6, 14)
    elif stage == "prime":
        total = rng.randint(14, 26)
    elif stage == "declining":
        total = rng.randint(22, 34)
    else:  # veteran
        total = rng.randint(30, 48)
    # Win rate based on potential: 90+ potential = 80% win rate, 50 = 55%, 25 = 35%
    win_rate = 0.35 + (potential - 25) * 0.0083  # 0.35 at 25, 0.65 at 61, ~0.80 at 90
    win_rate = max(0.20, min(0.85, win_rate))
    wins = int(round(total * win_rate))
    losses = total - wins
    draws = max(0, rng.randint(0, 1) if total > 10 else 0)
    if draws > 0 and losses > 0:
        losses -= draws
    return (wins, max(0, losses), draws)


def _pick_archetype(rng, conn, nation_name=None):
    """Pick a style_archetype_id based on the weighted distribution,
    adjusted by national tendency overrides if nation_name is provided.
    """
    weights = dict(ARCHETYPE_WEIGHTS)
    if nation_name and nation_name in NATION_ARCHETYPE_OVERRIDES:
        for arch, bonus in NATION_ARCHETYPE_OVERRIDES[nation_name].items():
            weights[arch] = weights.get(arch, 0) + bonus
    names = list(weights.keys())
    w = list(weights.values())
    chosen_name = rng.choices(names, weights=w, k=1)[0]
    row = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes WHERE name=?",
        (chosen_name,),
    ).fetchone()
    return row[0] if row else 1


def _pick_personality_archetype(rng, conn):
    """Pick a personality_archetype_id based on the weighted distribution."""
    names = list(PERSONALITY_ARCHETYPE_WEIGHTS.keys())
    weights = list(PERSONALITY_ARCHETYPE_WEIGHTS.values())
    chosen_name = rng.choices(names, weights=weights, k=1)[0]
    row = conn.execute(
        "SELECT personality_archetype_id FROM personality_archetypes WHERE name=?",
        (chosen_name,),
    ).fetchone()
    return row[0] if row else 1


def _pick_name(nation_name, gender, rng, conn, used_names):
    """Pick a unique (first, last) for a fighter from the nation's name
    pool. Returns (first, last, nickname, gender_str).

    CRITICAL: uniqueness is tracked on (first, last) only — nickname is
    NOT part of the uniqueness key, because the player sees "First Last"
    in the UI, not "First 'Nickname' Last". Two fighters with the same
    first+last but different nicknames would still look identical in a
    roster list.
    """
    gender_str = "male" if gender == "male" else "female"
    name_type = f"first_{gender_str}"
    first_rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type=? AND region=?",
        (name_type, nation_name),
    ).fetchall()
    last_rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='last' AND region=?",
        (nation_name,),
    ).fetchall()
    nick_rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='nickname'",
    ).fetchall()
    firsts = [r[0] for r in first_rows]
    lasts = [r[0] for r in last_rows]
    nicks = [r[0] for r in nick_rows]
    if not firsts:
        firsts = ["John"] if gender_str == "male" else ["Jane"]
    if not lasts:
        lasts = ["Smith"]
    if not nicks:
        nicks = ["The Fighter"]
    # Try up to 100 times to get a unique (first, last) combo
    for _ in range(100):
        first = rng.choice(firsts)
        last = rng.choice(lasts)
        key = (first, last)
        if key not in used_names:
            used_names.add(key)
            # 40% chance of having a nickname
            has_nick = rng.random() < 0.40
            nick = rng.choice(nicks) if has_nick else None
            return (first, last, nick, gender_str)
    # Fallback: if we still can't find a unique combo (small name pool),
    # append a roman-numeral-style suffix to the last name.
    for suffix in ("Jr", "II", "III", "IV", "V"):
        new_last = f"{last} {suffix}"
        if (first, new_last) not in used_names:
            used_names.add((first, new_last))
            return (first, new_last, None, gender_str)
    # Last resort: random number
    suffix = rng.randint(1, 999)
    new_last = f"{last}{suffix}"
    used_names.add((first, new_last))
    return (first, new_last, None, gender_str)


def _pick_gym(nation_id, rng, conn):
    """Pick a gym_id in the fighter's nation. Returns None if no gym
    exists in the nation (rare — every nation has at least one city).
    """
    rows = conn.execute(
        "SELECT gym_id FROM gyms WHERE nation_id=?",
        (nation_id,),
    ).fetchall()
    if not rows:
        # Fallback: any gym
        rows = conn.execute("SELECT gym_id FROM gyms").fetchall()
        if not rows:
            return None
    return rng.choice([r[0] for r in rows])


def _pick_birth_location(nation_name, rng, conn):
    """Pick a (birth_city_id, birth_nation_id) for a fighter. Uses
    weighted city selection (bigger cities more likely).
    """
    nid_row = conn.execute(
        "SELECT nation_id FROM nations WHERE name=?", (nation_name,)
    ).fetchone()
    if nid_row is None:
        return (None, None)
    nation_id = nid_row[0]
    # Get cities in this nation, weighted by population
    rows = conn.execute(
        "SELECT city_id, population FROM cities WHERE nation_id=?",
        (nation_id,),
    ).fetchall()
    if not rows:
        return (None, nation_id)
    weighted = []
    for cid, pop in rows:
        weight = max(1, int(pop / 100000))
        weighted.extend([cid] * weight)
    return (rng.choice(weighted), nation_id)


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run Phase 1 + Phase 2 first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Verify Phase 1 + 2 ran
    n_nations = conn.execute("SELECT COUNT(*) FROM nations").fetchone()[0]
    n_gyms = conn.execute("SELECT COUNT(*) FROM gyms").fetchone()[0]
    n_promos = conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
    n_names = conn.execute("SELECT COUNT(*) FROM name_pools").fetchone()[0]
    if n_nations < 10 or n_gyms < 100 or n_promos < 5 or n_names < 1000:
        print(f"ERROR: Phase 1+2 not complete (nations={n_nations}, gyms={n_gyms}, promos={n_promos}, names={n_names}).")
        sys.exit(1)

    # Check existing fighter count
    existing = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    if existing >= TARGET_FIGHTER_COUNT:
        print(f"Already {existing} fighters — Phase 3 already complete.")
        return

    # Get nations list (for distribution)
    nations = [r[0] for r in conn.execute(
        "SELECT name FROM nations"
    ).fetchall()]
    # Weight nations by MMA relevance (USA/Brazil/Japan/Russia/Dagestan get more)
    NATION_WEIGHTS = {
        "United States": 25, "Brazil": 18, "Japan": 8, "Russia": 8,
        "Dagestan": 6, "United Kingdom": 6, "Mexico": 4, "Canada": 4,
        "Australia": 3, "Ireland": 3, "Nigeria": 3, "France": 2,
        "Germany": 2, "Poland": 2, "Sweden": 2, "South Korea": 2,
        "China": 2, "Cuba": 1, "Argentina": 1, "Netherlands": 2,
    }
    weighted_nations = []
    for n in nations:
        w = NATION_WEIGHTS.get(n, 1)
        weighted_nations.extend([n] * w)

    # Get promotions by tier
    promos_by_tier = {"major": [], "mid": [], "small": []}
    for row in conn.execute(
        "SELECT promotion_id, size_tier, nation_id FROM promotions"
    ).fetchall():
        promos_by_tier[row[1]].append((row[0], row[2]))

    # Track used names for uniqueness — on (first, last) only per the
    # _pick_name docstring (nickname is NOT part of the uniqueness key).
    used_names = set()
    # Pre-load any existing names (in case of partial run)
    for r in conn.execute(
        "SELECT first_name, last_name FROM fighters"
    ).fetchall():
        used_names.add((r[0], r[1]))

    rng = random.Random(20260723)

    # ----------------------------------------------------------------
    # Build the assignment plan: (promotion_id_or_None, count) tuples
    # ----------------------------------------------------------------
    assignments = []  # list of (promotion_id, count, nation_hint_or_None)
    # Major promo (1 promo × 300 fighters)
    for promo_id, nation_id in promos_by_tier["major"]:
        assignments.append((promo_id, PROMOTION_ROSTER_SIZES["major"], nation_id))
    # Mid promos (3 × 150)
    for promo_id, nation_id in promos_by_tier["mid"]:
        assignments.append((promo_id, PROMOTION_ROSTER_SIZES["mid"], nation_id))
    # Small promos (6 × 50)
    for promo_id, nation_id in promos_by_tier["small"]:
        assignments.append((promo_id, PROMOTION_ROSTER_SIZES["small"], nation_id))
    # Free agents (400, no promotion)
    assignments.append((None, FREE_AGENT_COUNT, None))

    total_target = sum(a[1] for a in assignments)
    print(f"Target: {total_target} fighters ({TARGET_FIGHTER_COUNT} expected)")

    # ----------------------------------------------------------------
    # Generate fighters
    # ----------------------------------------------------------------
    print("Generating fighters...")
    n_created = 0
    batch_count = 0
    BATCH_SIZE = 200  # commit every 200 fighters

    for promo_id, count, nation_hint in assignments:
        for _ in range(count):
            # Pick nation (prefer the promotion's nation if given)
            if nation_hint and rng.random() < 0.6:
                # Look up nation name
                nname_row = conn.execute(
                    "SELECT name FROM nations WHERE nation_id=?", (nation_hint,)
                ).fetchone()
                nation_name = nname_row[0] if nname_row else rng.choice(weighted_nations)
            else:
                nation_name = rng.choice(weighted_nations)
            nid_row = conn.execute(
                "SELECT nation_id FROM nations WHERE name=?", (nation_name,)
            ).fetchone()
            nation_id = nid_row[0] if nid_row else 1

            # Gender
            gender = "male" if rng.random() < GENDER_MALE_PCT else "female"

            # Career stage + age
            stage = _pick_career_stage(rng)
            age = _gen_age_for_stage(stage, rng)
            # date_of_birth: sim date 2026-07-22 minus age years (approx)
            dob_year = 2026 - age
            dob_month = rng.randint(1, 12)
            dob_day = rng.randint(1, 28)
            date_of_birth = f"{dob_year}-{dob_month:02d}-{dob_day:02d}"

            # Pick name (first + last only — nickname generated separately)
            first, last, _, gender_str = _pick_name(
                nation_name, gender, rng, conn, used_names
            )

            # Archetypes — style archetype weighted by national tendency
            style_arch_id = _pick_archetype(rng, conn, nation_name)
            pers_arch_id = _pick_personality_archetype(rng, conn)

            # Weight class
            wc_id = _pick_weight_class(rng, gender_str, conn)
            if wc_id is None:
                continue  # skip if no matching WC (shouldn't happen)

            # Get weight class max_weight_kg for height scaling
            wc_max_kg = conn.execute(
                "SELECT max_weight_kg FROM weight_classes WHERE weight_class_id=?",
                (wc_id,),
            ).fetchone()[0]

            # Generate attribute + personality blocks (uses archetype bias)
            attrs = fighter_gen.generate_attribute_block(style_arch_id, conn)
            pers = fighter_gen.generate_personality_block(pers_arch_id, conn)
            physical = fighter_gen.generate_physical_block(wc_max_kg, gender_str)
            potential = fighter_gen.generate_potential()

            # Generate nickname dynamically (v2.6.3 — was from fixed pool of 38)
            style_arch_name = conn.execute(
                "SELECT name FROM style_archetypes WHERE style_archetype_id=?",
                (style_arch_id,),
            ).fetchone()[0]
            nickname = fighter_gen.generate_nickname(
                attrs=attrs, pers=pers,
                style_archetype_name=style_arch_name,
                nation_name=nation_name, rng=rng,
            )

            # Widen personality variation — fighter_gen produces values in
            # ~32-68 range (50 + ±10 bias + ±8 noise). Real fighters have
            # more extreme personalities (a Brawler should have aggression
            # 70-90, a Methodical fighter should have patience 70-90).
            # Scale each personality value AWAY from 50 by a random factor
            # (1.3-2.0x the distance from 50), clamped to [10, 95].
            for k in pers:
                base = pers[k]
                dist_from_50 = base - 50
                scale = rng.uniform(1.3, 2.0)
                widened = int(50 + dist_from_50 * scale + rng.randint(-5, 5))
                pers[k] = max(10, min(95, widened))

            # Scale attributes UP toward potential for prime/declining/veteran
            # (a 32-year-old prime fighter has grown into their potential).
            # v2.6.2: tightened growth factors so veterans diverge MORE
            # from their potential — an elite veteran (potential 85) should
            # have attributes in the 68-81 range, a limited veteran
            # (potential 30) should stay around 25-30. This makes the
            # career arc visible: by prime, you can read a fighter's
            # ceiling from their attributes (but by then they have a
            # fight record too).
            if stage in ("prime", "declining", "veteran"):
                growth_factor = 0.80 + rng.uniform(0, 0.15)  # 80-95% of potential reached
                for k in attrs:
                    target = int(potential * growth_factor + rng.randint(-4, 4))
                    attrs[k] = max(attrs[k], min(100, target))
            elif stage == "developing":
                growth_factor = 0.55 + rng.uniform(0, 0.20)  # 55-75% of potential reached
                for k in attrs:
                    target = int(potential * growth_factor + rng.randint(-3, 3))
                    attrs[k] = max(attrs[k], min(100, target))
            # prospects keep their base attributes (haven't grown yet) —
            # this is the KEY scouting mechanic: an 18-year-old elite
            # prospect and an 18-year-old limited prospect have the same
            # attributes. You can't tell them apart without scouting.

            # Career record
            wins, losses, draws = _gen_record_for_stage(stage, potential, rng)

            # Pick gym — NOT all fighters get one. Per user directive,
            # some fighters enter without a home gym (they train
            # independently or are between gyms). Future gym-joining
            # logic will use personality + attributes + age to decide.
            # For now:
            #   - Signed fighters: 85% get a gym (15% are between gyms)
            #   - Free agents: 50% get a gym (50% train independently)
            if promo_id is None:
                # Free agent
                gym_id = _pick_gym(nation_id, rng, conn) if rng.random() < 0.50 else None
            else:
                # Signed fighter
                gym_id = _pick_gym(nation_id, rng, conn) if rng.random() < 0.85 else None

            # Birth location
            birth_city_id, birth_nation_id = _pick_birth_location(nation_name, rng, conn)

            # Derive fighter career fields
            win_streak = max(0, rng.randint(0, 6) if stage in ("prime", "developing") else rng.randint(-2, 2))
            loss_streak = max(0, -win_streak if win_streak < 0 else (rng.randint(0, 4) if stage in ("declining", "veteran") else 0))
            career_health = 100
            if stage == "declining":
                career_health = rng.randint(70, 90)
            elif stage == "veteran":
                career_health = rng.randint(50, 75)

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
                (first, last, nickname, gender_str, date_of_birth,
                 birth_city_id, birth_nation_id, wc_id, gym_id, promo_id,
                 style_arch_id, pers_arch_id,
                 physical["height_cm"], physical["reach_cm"],
                 physical["stance"], physical["handedness"],
                 rng.randint(20, 80),  # injury_proneness
                 rng.randint(20, 80),  # weight_cut_difficulty
                 rng.randint(40, 80),  # consistency
                 rng.randint(40, 80),  # clutch_factor
                 rng.randint(30, 90),  # marketability
                 rng.randint(30, 90),  # fan_friendliness
                 rng.randint(20, 80),  # promo_boost
                 ),
            )
            fighter_id = cur.lastrowid

            # Insert fighter_attributes
            attr_cols = list(attrs.keys())
            attr_vals = list(attrs.values())
            placeholders = ", ".join(["?"] * len(attr_cols))
            col_list = ", ".join(attr_cols)
            conn.execute(
                f"INSERT INTO fighter_attributes (fighter_id, {col_list}) "
                f"VALUES (?, {placeholders})",
                (fighter_id, *attr_vals),
            )

            # Insert fighter_personality
            pers_cols = list(pers.keys())
            pers_vals = list(pers.values())
            placeholders = ", ".join(["?"] * len(pers_cols))
            col_list = ", ".join(pers_cols)
            conn.execute(
                f"INSERT INTO fighter_personality (fighter_id, {col_list}) "
                f"VALUES (?, {placeholders})",
                (fighter_id, *pers_vals),
            )

            # Insert fighter_career
            conn.execute(
                "INSERT INTO fighter_career (fighter_id, record_wins, record_losses, "
                "record_draws, win_streak, loss_streak, career_health, potential, "
                "title_reigns) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (fighter_id, wins, losses, draws, max(0, win_streak),
                 loss_streak, career_health, potential),
            )

            # Insert ranking row (rating 1000 base + adjustment for record)
            elo = 1000 + (wins - losses) * 8 + rng.randint(-30, 30)
            conn.execute(
                "INSERT OR IGNORE INTO rankings (fighter_id, weight_class_id, "
                "promotion_id, rating, fights_count, wins, losses, draws) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (fighter_id, wc_id, promo_id, elo,
                 wins + losses + draws, wins, losses, draws),
            )

            n_created += 1
            batch_count += 1
            if batch_count >= BATCH_SIZE:
                conn.commit()
                batch_count = 0
                print(f"  ...{n_created} fighters created")

    conn.commit()
    final_count = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    print(f"  Total fighters: {final_count}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("World seed Phase 3 complete.")
    print(f"  Fighters:    {final_count}")
    print()
    # By gender
    for g in ("male", "female"):
        n = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE gender=?", (g,)
        ).fetchone()[0]
        print(f"  {g} fighters: {n}")
    # By career stage (inferred from age)
    print()
    print("  By age group (career stage proxy):")
    for label, lo, hi in [
        ("prospect (18-22)", 18, 22),
        ("developing (23-27)", 23, 27),
        ("prime (28-32)", 28, 32),
        ("declining (33-37)", 33, 37),
        ("veteran (38-43)", 38, 43),
    ]:
        n = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE date_of_birth >= ? AND date_of_birth <= ?",
            (f"{2026-hi}-01-01", f"{2026-lo}-12-31"),
        ).fetchone()[0]
        print(f"    {label}: {n}")
    # By weight class (top 5)
    print()
    print("  By weight class (top 8):")
    for r in conn.execute(
        "SELECT wc.name, wc.gender, COUNT(*) FROM fighters f "
        "JOIN weight_classes wc ON f.weight_class_id=wc.weight_class_id "
        "GROUP BY wc.weight_class_id ORDER BY COUNT(*) DESC LIMIT 8"
    ).fetchall():
        print(f"    {r[0]} ({r[1]}): {r[2]}")
    # By promotion
    print()
    print("  By promotion:")
    for r in conn.execute(
        "SELECT p.name, p.size_tier, COUNT(*) FROM fighters f "
        "LEFT JOIN promotions p ON f.current_promotion_id=p.promotion_id "
        "GROUP BY p.promotion_id ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {r[0] or 'Free Agents'} ({r[1] or 'n/a'}): {r[2]}")
    print("=" * 60)
    print()
    print("Next: python scripts/seed_world_phase4.py (career histories, fights, titles, contracts)")

    conn.close()


if __name__ == "__main__":
    main()
