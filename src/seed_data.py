import json
import random
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call fighter_gen's generation
# primitives for the archetype-biased backfill of the 5 existing
# seeded fighters. fighter_gen is pure-Python (no tkinter, no I/O
# beyond the optional conn argument), so importing it here is safe.
import sys
sys.path.insert(0, str(BASE_DIR))
import fighter_gen  # noqa: E402

def one(conn, sql, params=()):
    return conn.execute(sql, params).lastrowid

# ----------------------------------------------------------------
# Default contract seeders (Task ID 9). Each fighter and the seeded
# commentator (Nina Cross) gets a default 12-month exclusive contract
# tying them to their promotion. This replaces the implicit
# `fighters.current_promotion_id` FK with an explicit, queryable
# contract row that has a start_date, end_date, salary, exclusivity,
# and status — the foundation for Task ID 13 (free agency + signings)
# and Task ID 25 (rival promotion AI poaching).
#
# Defaults:
#   start_date: the sim's current_date (2026-07-20 per the seeded
#     simulation_clock).
#   end_date:   start_date + 365 days.
#   salary:     50000.0 (placeholder - Task 20 finances will add real
#     per-fighter salary negotiation).
#   bonus_structure: NULL (Task 13 will populate).
#   buyout_clause: NULL (Task 25 will populate for rival AI poaching).
#   exclusive_flag: 1 (fighter can't fight for other promotions while
#     under contract).
#   status: 'active'.
#   fighter contract_type: 'standard'.
# ----------------------------------------------------------------

def _seed_default_fighter_contract(conn, fighter_id, promotion_id, start_date="2026-07-20"):
    """Create a default 12-month exclusive fighter contract.

    Inserts one row into `contracts` (target_type='fighter') and one
    row into `fighter_contracts` (contract_type='standard'). Returns
    the new contract_id.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=365)
    end_date = end_dt.strftime("%Y-%m-%d")
    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('fighter', ?, ?, ?, 50000.0, 1, 'active')",
        (promotion_id, start_date, end_date),
    ).lastrowid
    conn.execute(
        "INSERT INTO fighter_contracts (contract_id, fighter_id, "
        "contract_type) VALUES (?, ?, 'standard')",
        (contract_id, fighter_id),
    )
    return contract_id


def _seed_default_staff_contract(conn, staff_id, promotion_id, role, start_date="2026-07-20"):
    """Create a default 12-month staff contract.

    Inserts one row into `contracts` (target_type='staff') and one
    row into `staff_contracts` with the given role. Returns the new
    contract_id. Symmetric to `_seed_default_fighter_contract` but
    for the staff subtype.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=365)
    end_date = end_dt.strftime("%Y-%m-%d")
    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('staff', ?, ?, ?, 50000.0, 1, 'active')",
        (promotion_id, start_date, end_date),
    ).lastrowid
    conn.execute(
        "INSERT INTO staff_contracts (contract_id, staff_id, "
        "contract_role) VALUES (?, ?, ?)",
        (contract_id, staff_id, role),
    )
    return contract_id


# ----------------------------------------------------------------
# Initial ranking seeder (Task ID 10). Each fighter gets an initial
# `rankings` row at rating=1000.0 in their current weight class and
# current promotion. This is the starting ELO baseline — everyone
# enters at the same rating, and `_update_rankings_after_resolution()`
# in app.py adjusts ratings on every fight resolution. Foundation
# for Task ID 11 (titles), Task ID 14 (regen — new fighters enter at
# the bottom at 1000.0), and Task ID 22 (rivalries — ranking
# proximity boosts heat).
# ----------------------------------------------------------------

def _seed_initial_ranking(conn, fighter_id, weight_class_id, promotion_id):
    """Create an initial rankings row for a fighter.

    Inserts one row into `rankings` with rating=1000.0,
    fights_count=0, wins=0, losses=0, draws=0. Uses INSERT OR IGNORE
    so the seed is idempotent — re-running seed_data.py after a
    partial failure won't crash on the UNIQUE (fighter_id,
    weight_class_id, promotion_id) constraint. Returns the ranking_id
    (or None if the row already existed and INSERT OR IGNORE skipped).
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO rankings (fighter_id, weight_class_id, "
        "promotion_id, rating, fights_count, wins, losses, draws) "
        "VALUES (?, ?, ?, 1000.0, 0, 0, 0, 0)",
        (fighter_id, weight_class_id, promotion_id),
    )
    return cur.lastrowid


# ----------------------------------------------------------------
# Vacant title seeder (Task ID 11). One title per (promotion,
# weight_class) pair. The title starts vacant — the first title
# fight (is_title_fight=1 — the canonical check since v2.2.0 / Task
# pre-B2-fix; the legacy `bout_type='title_fight'` comparison is
# DEPRECATED but kept for backward compatibility) transfers the belt
# to the winner via `_resolve_title_after_fight()` in app.py. The
# seed creates two titles (AC Lightweight + RFL Lightweight) so the
# title-transfer logic can be exercised end-to-end on the first
# resolve.
# Foundation for Task 8's schedule_next_event() (future: champion
# vs #1 contender), Task 14 (regen — retiring champions vacate),
# Task 22 (rivalries — title fight rivalries are the most heated).
# ----------------------------------------------------------------

def _seed_vacant_title(conn, promotion_id, weight_class_id):
    """Create a vacant title for a promotion's weight class.

    Called by the seed for every (promotion, weight_class) pair. The
    title starts vacant (current_champion_fighter_id IS NULL,
    is_vacant=1). The first title fight (is_title_fight=1 — the
    canonical check since v2.2.0 / Task pre-B2-fix; the legacy
    `bout_type='title_fight'` comparison is DEPRECATED but kept for
    backward compatibility) will transfer the belt to the winner via
    _resolve_title_after_fight() in app.py.

    Uses INSERT OR IGNORE so the seed is idempotent — re-running
    seed_data.py won't crash on the UNIQUE (promotion_id,
    weight_class_id) constraint. Returns the title_id (or None if
    the row already existed).
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO titles (promotion_id, weight_class_id, "
        "current_champion_fighter_id, champion_since_date, "
        "title_reigns_count, title_defenses_count, is_vacant) "
        "VALUES (?, ?, NULL, NULL, 0, 0, 1)",
        (promotion_id, weight_class_id),
    )
    return cur.lastrowid


# ----------------------------------------------------------------
# Name pool seeder (Task ID 14). Seeds the `name_pools` table with
# first names (male + female), last names, and nicknames. The regen
# engine (generate_fighter in app.py) draws from these pools when a
# fighter retires — the new replacement fighter inherits the retiring
# fighter's fight_style_archetype_id (style DNA) but gets a fresh
# identity from the name pools.
#
# Pool sizes (kept modest on purpose — the seed is a starting point,
# not an exhaustive registry; the mod tools in Task 29 will let users
# import larger name packs):
#   - 25 male first names (Aaron..Zane)
#   - 25 female first names (Aria..Zoe)
#   - 26 last names (Adams..Zhang)
#   - 20 nicknames (The Hammer..Vortex)
#
# Total: 96 name pool entries. Each (name_type, name_value) pair is
# UNIQUE so re-seeding is idempotent (INSERT OR IGNORE).
#
# Note on uniqueness: the spec calls for a separate `used_names`
# table to prevent duplicate fighter names. We chose to check
# uniqueness against the existing `fighters` table (first_name +
# last_name combination) in generate_fighter() instead. This is
# simpler and avoids a redundant table — see build_db.py's name_pools
# schema comment for the full rationale.
# ----------------------------------------------------------------

# Module-level constants so the seed summary print in main() can
# reference the counts without duplicating the lists.
MALE_FIRST_COUNT = 25
FEMALE_FIRST_COUNT = 25
LAST_COUNT = 26
NICKNAME_COUNT = 20


def _seed_name_pools(conn):
    """Seed the name_pools table with initial name data (Task ID 14).

    Inserts 25 male first names, 25 female first names, 26 last names,
    and 20 nicknames. Uses INSERT OR IGNORE so the seed is idempotent
    — re-running seed_data.py won't crash on the UNIQUE (name_type,
    name_value) constraint.

    Returns the total number of name pool entries inserted (96 if all
    were new, fewer if some already existed from a prior partial run).
    """
    male_firsts = ["Aaron", "Brian", "Carlos", "Diego", "Ethan", "Frank", "George",
                   "Hiro", "Ivan", "Jake", "Kai", "Liam", "Miguel", "Nathan",
                   "Omar", "Pablo", "Quinn", "Ryan", "Sergio", "Tyler", "Victor",
                   "William", "Xavier", "Yuki", "Zane"]
    female_firsts = ["Aria", "Bianca", "Carmen", "Diana", "Elena", "Fatima",
                     "Grace", "Hana", "Isabel", "Jade", "Keiko", "Luna",
                     "Maya", "Nadia", "Olivia", "Priya", "Quinn", "Rosa",
                     "Sakura", "Tara", "Uma", "Valentina", "Willow", "Yara", "Zoe"]
    lasts = ["Adams", "Brennan", "Castillo", "Diaz", "Evans", "Fischer", "Garcia",
             "Hayashi", "Ibrahim", "Jensen", "Kim", "Lopez", "Martinez", "Nakamura",
             "O'Brien", "Patel", "Quinn", "Rivera", "Silva", "Tanaka", "Ueda",
             "Vargas", "Walsh", "Xu", "Yamamoto", "Zhang"]
    nicknames = ["The Hammer", "Voltage", "The Drill", "Whisper", "Anvil",
                 "The Storm", "Ice", "The Wolf", "Shadow", "Titan",
                 "The Kid", "Smasher", "Venom", "The Bull", "Phoenix",
                 "Razor", "The Ghost", "Fury", "The Cobra", "Vortex"]

    for name in male_firsts:
        conn.execute(
            "INSERT OR IGNORE INTO name_pools (name_type, name_value) "
            "VALUES ('first_male', ?)",
            (name,),
        )
    for name in female_firsts:
        conn.execute(
            "INSERT OR IGNORE INTO name_pools (name_type, name_value) "
            "VALUES ('first_female', ?)",
            (name,),
        )
    for name in lasts:
        conn.execute(
            "INSERT OR IGNORE INTO name_pools (name_type, name_value) "
            "VALUES ('last', ?)",
            (name,),
        )
    for name in nicknames:
        conn.execute(
            "INSERT OR IGNORE INTO name_pools (name_type, name_value) "
            "VALUES ('nickname', ?)",
            (name,),
        )

    return len(male_firsts) + len(female_firsts) + len(lasts) + len(nicknames)


# ----------------------------------------------------------------
# Archetype seeder (added v2.0.0, Task 14.5; softened v2.0.1,
# Task pre-B1-fixes). Seeds 7 style archetypes + 5 personality
# archetypes with bias JSON. The bias JSON is consumed by
# fighter_gen.generate_attribute_block /
# generate_personality_block to produce archetype-distinct fighters.
#
# Existing archetypes (Balanced, Calm) get their bias JSON added via
# UPDATE; new archetypes are INSERTed. INSERT OR IGNORE makes the
# seeder idempotent across re-runs.
#
# Bias values were SOFTENED ~40-50% in v2.0.1 (Task pre-B1-fixes):
# the maximum absolute bias dropped from 20 (Brawler punch_power,
# Wrestler takedown_offense, Submission Specialist submission_offense,
# Showman charisma/attention_seeking) to 10 (Brawler punch_power,
# Aggressive aggression, Showman charisma/attention_seeking). Modern
# MMA fighters at the highest level are well-rounded; archetypes
# should be tendencies, not extremes — a Brawler should hit a bit
# harder and take a better shot, but not be helpless on the feet or
# gas after 1 round.
#
# The new acceptance test scripts/test_pre_b1_fixes.py case D asserts
# that the maximum absolute bias across all 12 archetypes is <= 10.
# The existing test_fighter_attributes.py case D statistical check
# (Brawler averages higher on punch_power/chin and lower on
# footwork/fight_iq than Counter-Striker, with a > 5 threshold) STILL
# passes with the softened biases (margins of 10, 8, 16, 13 — all
# > 5). The case B.7 / B.8 exact-value assertions in
# test_fighter_attributes.py DO break with the softened biases; per
# CONVENTIONS §11 these are flagged as D2 / D3 in the worklog and
# left for the supervisor to fix.
# ----------------------------------------------------------------

# (name, description, bias_json_str). 7 rows = 1 existing (Balanced)
# + 6 new. The names match the brief verbatim — the new acceptance
# test looks up style_archetypes by name. SOFTENED bias values per
# Task pre-B1-fixes brief.
STYLE_ARCHETYPES = [
    ("Balanced", "Well-rounded",
     json.dumps({"punch_power": 3, "cardio": 3, "fight_iq": 3})),
    ("Striker", "Stand-up specialist",
     json.dumps({"punch_power": 8, "kick_power": 8,
                 "punch_accuracy": 5, "head_movement": 5,
                 "takedown_defense": -5, "submission_offense": -5})),
    ("Grappler", "Ground fighter",
     json.dumps({"takedown_offense": 8, "top_control": 8,
                 "submission_offense": 8,
                 "punch_power": -3, "kick_power": -3,
                 "head_movement": -3})),
    ("Wrestler", "Takedown-and-control artist",
     json.dumps({"takedown_offense": 10, "top_control": 8,
                 "cage_wrestling": 8, "strength": 5,
                 "submission_offense": -5, "kick_power": -5})),
    ("Brawler", "Pressure puncher with a chin",
     json.dumps({"punch_power": 10, "chin": 8, "durability": 5,
                 "footwork": -8, "fight_iq": -5, "cardio": -3})),
    ("Counter-Striker", "Evasive sharpshooter",
     json.dumps({"punch_accuracy": 8, "head_movement": 8,
                 "footwork": 8, "fight_iq": 8,
                 "aggression": -5, "takedown_offense": -5})),
    ("Submission Specialist", "Tap-or-pass specialist",
     json.dumps({"submission_offense": 10, "bottom_game": 8,
                 "flexibility": 8,
                 "punch_power": -5, "chin": -3})),
]

# (name, description, bias_json_str). 5 rows = 1 existing (Calm) +
# 4 new. Note the brief says "5 total, 2 existing + 3 new" but the
# actual v1.9.0 seed only had 1 personality archetype (Calm); we add
# 4 new for a total of 5. This matches the brief's "5 personality
# archetypes" count. SOFTENED bias values per Task pre-B1-fixes
# brief — max absolute bias is now 10 (was 20).
PERSONALITY_ARCHETYPES = [
    ("Calm", "Composed",
     json.dumps({"composure": 8, "aggression": -5, "patience": 5})),
    ("Aggressive", "High-pressure, finish-hunting",
     json.dumps({"aggression": 10, "killer_instinct": 8,
                 "patience": -8, "discipline": -3})),
    ("Methodical", "Patient game-planner",
     json.dumps({"discipline": 8, "patience": 10,
                 "fight_iq": 5, "risk_taking": -5})),
    ("Showman", "Crowd-pleaser with an ego",
     json.dumps({"charisma": 10, "attention_seeking": 10,
                 "ego": 5, "sportsmanship": -5})),
    ("Quiet Professional", "Let-the-work-speak type",
     json.dumps({"coachability": 8, "professionalism": 8,
                 "discipline": 5, "attention_seeking": -8})),
]


def _seed_archetypes(conn):
    """Seed 7 style + 5 personality archetypes with bias JSON.

    Uses INSERT OR IGNORE so the existing Balanced/Calm rows from
    prior task versions are preserved (their autoincrement IDs stay
    1 and 1). Then UPDATEs every row's attribute_bias / trait_bias
    column to the seeded JSON value — this is what populates the
    bias for the existing Balanced/Calm rows (which were inserted
    without bias in v1.x).

    Returns the (style_count, personality_count) tuple (always
    (7, 5) on a fresh seed).
    """
    for name, desc, bias_json in STYLE_ARCHETYPES:
        conn.execute(
            "INSERT OR IGNORE INTO style_archetypes "
            "(name, description, attribute_bias) VALUES (?, ?, ?)",
            (name, desc, bias_json),
        )
        # UPDATE in case the row already existed (from a prior partial
        # seed) without the bias column populated.
        conn.execute(
            "UPDATE style_archetypes SET description=?, attribute_bias=? "
            "WHERE name=?",
            (desc, bias_json, name),
        )
    for name, desc, bias_json in PERSONALITY_ARCHETYPES:
        conn.execute(
            "INSERT OR IGNORE INTO personality_archetypes "
            "(name, description, trait_bias) VALUES (?, ?, ?)",
            (name, desc, bias_json),
        )
        conn.execute(
            "UPDATE personality_archetypes SET description=?, trait_bias=? "
            "WHERE name=?",
            (desc, bias_json, name),
        )
    return len(STYLE_ARCHETYPES), len(PERSONALITY_ARCHETYPES)


# ----------------------------------------------------------------
# Fighter backfill helper (added v2.0.0, Task 14.5). After the
# schema expansion, the 5 existing seeded fighters have NULL or
# default-50 values for the 21 new attribute columns, 17 new
# personality columns, and 14 new fighters-table columns. This
# helper fills them in using fighter_gen's archetype-biased
# generation, while PRESERVING the existing 4 attribute values
# (punch_power, cardio, fight_iq, chin) and 3 personality values
# (aggression, composure, morale) per the brief's "PRESERVED" rule.
# ----------------------------------------------------------------

# The 21 new attribute columns (matches fighter_gen.NEW_ATTRIBUTE_NAMES
# — duplicated here as a static tuple so the UPDATE SQL is built
# without an extra module-level lookup at runtime).
_NEW_ATTR_COLUMNS = tuple(fighter_gen.NEW_ATTRIBUTE_NAMES)
_NEW_PERS_COLUMNS = tuple(fighter_gen.NEW_PERSONALITY_NAMES)


def _backfill_fighter_v2(conn, fighter_id, style_archetype_id,
                        pers_archetype_id):
    """Backfill a single existing fighter with v2.0.0 new columns.

    Preserves:
      - fighter_attributes: punch_power, cardio, fight_iq, chin
      - fighter_personality: aggression, composure, morale

    Fills via fighter_gen (archetype-biased):
      - 21 new attribute columns (from generate_attribute_block)
      - 17 new personality columns (from generate_personality_block)

    Fills via fighter_gen.generate_physical_block:
      - height_cm, reach_cm, stance, handedness on the fighters table

    Leaves at schema defaults (sensible per the brief):
      - injury_proneness, weight_cut_difficulty, consistency,
        clutch_factor, marketability, fan_friendliness (all 50)
      - promo_boost (0)
      - preferred_gameplans, bad_matchup_tags (NULL)
      - is_deceased (0)

    This helper is called by the seed immediately after the original
    `INSERT INTO fighter_attributes (fighter_id) VALUES (?)` (which
    sets all 25 attribute columns to their DEFAULT 50). The backfill
    UPDATEs only the 21 new attribute columns and 17 new personality
    columns, leaving the 4+3 existing ones at their preserved values.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter to backfill.
        style_archetype_id: the fighter's fight_style_archetype_id
            (drives the attribute bias).
        pers_archetype_id: the fighter's personality_archetype_id
            (drives the personality bias).

    Returns:
        None. Side effects: 2 UPDATEs to fighter_attributes /
        fighter_personality, 1 UPDATE to fighters.
    """
    # 1. Generate the attribute block (25 keys) and override the 4
    #    existing keys with their PRESERVED values (read from the DB
    #    so the backfill is correct even if a future change seeds
    #    non-default values for the existing 4).
    attrs_full = fighter_gen.generate_attribute_block(
        style_archetype_id, conn
    )
    existing_attrs = conn.execute(
        "SELECT punch_power, cardio, fight_iq, chin "
        "FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if existing_attrs is not None:
        attrs_full["punch_power"] = existing_attrs[0]
        attrs_full["cardio"] = existing_attrs[1]
        attrs_full["fight_iq"] = existing_attrs[2]
        attrs_full["chin"] = existing_attrs[3]

    # 2. UPDATE only the 21 new attribute columns. We use the
    #    attrs_full dict's values for the 21 new keys (the 4 existing
    #    keys are in the dict but we exclude them from the SET clause
    #    to avoid touching them — preserves them exactly).
    set_clause_attrs = ", ".join(
        f"{col}=?" for col in _NEW_ATTR_COLUMNS
    )
    params_attrs = [attrs_full[col] for col in _NEW_ATTR_COLUMNS]
    params_attrs.append(fighter_id)
    conn.execute(
        f"UPDATE fighter_attributes SET {set_clause_attrs}, "
        f"updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        params_attrs,
    )

    # 3. Generate the personality block (20 keys) and override the 3
    #    existing keys with their PRESERVED values.
    pers_full = fighter_gen.generate_personality_block(
        pers_archetype_id, conn
    )
    existing_pers = conn.execute(
        "SELECT aggression, composure, morale "
        "FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if existing_pers is not None:
        pers_full["aggression"] = existing_pers[0]
        pers_full["composure"] = existing_pers[1]
        pers_full["morale"] = existing_pers[2]

    # 4. UPDATE only the 17 new personality columns.
    set_clause_pers = ", ".join(
        f"{col}=?" for col in _NEW_PERS_COLUMNS
    )
    params_pers = [pers_full[col] for col in _NEW_PERS_COLUMNS]
    params_pers.append(fighter_id)
    conn.execute(
        f"UPDATE fighter_personality SET {set_clause_pers}, "
        f"updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        params_pers,
    )

    # 5. Fill the physical columns (height_cm, reach_cm, stance,
    #    handedness) on the fighters table. The meta columns
    #    (injury_proneness, marketability, etc.) are left at their
    #    schema DEFAULT 50 / 0 / NULL — sensible per the brief.
    physical = fighter_gen.generate_physical_block()
    conn.execute(
        "UPDATE fighters SET height_cm=?, reach_cm=?, stance=?, "
        "handedness=?, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (physical["height_cm"], physical["reach_cm"],
         physical["stance"], physical["handedness"], fighter_id),
    )


# ----------------------------------------------------------------
# Potential + title_reigns backfill (added v2.0.1, Task pre-B1-fixes).
# The 5 existing seeded fighters get a hand-picked `potential` value
# (not random) so the starting roster has a known, sensible shape:
#   - John Vale + Marcus Reed (AC, the player's starting roster):
#     higher potential (70-75) — these are the fighters the player
#     sees first and develops. Giving them solid-to-elite potential
#     makes the first ~50 hours of playthrough rewarding rather
#     than punishing.
#   - Dario Knox, Eli Storm, Cole Briggs (RFL, the inert rival
#     promotion's roster): medium potential (45-55) — these are
#     journeymen-of-the-rival-promotion caliber. When RFL becomes
#     AI-controlled in Task 25, the player will face these (and
#     sign them as free agents when their contracts expire) — the
#     medium potential means they're useful but not stars.
#
# `title_reigns` is left at the schema DEFAULT 0 for all 5 seeded
# fighters — none of them have actually won a title yet (both AC
# and RFL Lightweight titles are seeded VACANT). The first title
# fight the player resolves will increment the winner's
# title_reigns via _resolve_title_after_fight() in app.py.
#
# The backfill uses a hand-picked (deterministic) value per fighter
# rather than calling fighter_gen.generate_potential() because the
# seed should produce the SAME world every time (idempotent). Random
# potential in the seed would mean a fresh rebuild changes which
# seeded fighters are "elite" — that's bad for testing and bad for
# the player's mental model. Random potential is reserved for the
# regen path (app.generate_fighter) where each new prospect SHOULD
# be a surprise.
# ----------------------------------------------------------------

# Fighter ID -> potential value for the 5 seeded fighters.
# John Vale (1) and Marcus Reed (2): 70-75 (solid-to-elite).
# Dario Knox (3), Eli Storm (4), Cole Briggs (5): 45-55 (limited-
# to-solid). Hand-picked deterministic values within the brief's
# ranges so the seed is idempotent across rebuilds.
_SEEDED_FIGHTER_POTENTIAL = {
    1: 72,  # John Vale — solid-to-elite (in [70, 75])
    2: 71,  # Marcus Reed — solid-to-elite (in [70, 75])
    3: 50,  # Dario Knox — medium (in [45, 55])
    4: 47,  # Eli Storm — medium (in [45, 55])
    5: 53,  # Cole Briggs — medium (in [45, 55])
}


def _backfill_potential_title_reigns(conn):
    """Backfill `potential` for the 5 seeded fighters.

    Sets `fighter_career.potential` for each of the 5 seeded fighters
    (fighter_ids 1-5) to the hand-picked value in
    _SEEDED_FIGHTER_POTENTIAL. `title_reigns` is left at the schema
    DEFAULT 0 — none of the seeded fighters have won a title yet.

    Idempotent: safe to call multiple times. Uses UPDATE which is a
    no-op if the value is already correct.

    Args:
        conn: sqlite3 connection (caller commits).

    Returns:
        None. Side effects: 5 UPDATEs to fighter_career.
    """
    for fighter_id, potential in _SEEDED_FIGHTER_POTENTIAL.items():
        conn.execute(
            "UPDATE fighter_career SET potential=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (potential, fighter_id),
        )

def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        if conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0] > 0:
            print("Already seeded.")
            return

        nation_id = one(conn, "INSERT INTO nations (name, language) VALUES (?, ?)", ("Northland", "English"))
        region_id = one(conn, "INSERT INTO regions (name, style_preferences, fan_preferences) VALUES (?, ?, ?)", ("East Coast", "boxing, pressure", "rivalries"))
        wc_id = one(conn, "INSERT INTO weight_classes (name, min_weight_kg, max_weight_kg) VALUES (?, ?, ?)", ("Lightweight", 65.8, 70.3))
        city_id = one(conn, "INSERT INTO cities (nation_id, region_id, name, population) VALUES (?, ?, ?, ?)", (nation_id, region_id, "Metro City", 2500000))
        market_id = one(conn, "INSERT INTO markets (city_id, market_type) VALUES (?, ?)", (city_id, "major"))
        venue_id = one(conn, "INSERT INTO venues (city_id, name, capacity) VALUES (?, ?, ?)", (city_id, "Metro Arena", 18000))

        # ----------------------------------------------------------------
        # Promotions (v2.0.0, Task 14.6). The 6 new columns added in
        # this task get promotion-specific values per the brief:
        #   AC (player promotion): broadcast_tier='regional_tv',
        #     starting_budget=500000, ai_aggression=30 (low — the
        #     player controls AC, not the AI). ownership_type='startup',
        #     brand_tone='standard', ai_spending_style='balanced' (the
        #     schema defaults — left implicit).
        #   RFL (future AI rival, Task 25): broadcast_tier='local_stream',
        #     starting_budget=200000, ai_aggression=60 (more aggressive
        #     — RFL will be the AI-controlled rival that pushes the
        #     player). ownership_type, brand_tone, ai_spending_style
        #     use schema defaults.
        # current_cash is left at the schema default (0) for now —
        # Task 20 (finances) will give promotions real cash positions.
        # ----------------------------------------------------------------
        promo_id = one(conn,
            "INSERT INTO promotions (name, size_tier, nation_id, region_id, "
            "starting_budget, broadcast_tier, ai_aggression) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Alpha Combat", "major", nation_id, region_id,
             500000.0, "regional_tv", 30))
        gym_id = one(conn,
            "INSERT INTO gyms (name, city_id, nation_id, region_id, "
            "facility_quality, medical_support, sparring_depth, development_focus) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Ironhouse Gym", city_id, nation_id, region_id,
             60, 50, 55, 60))

        # ----------------------------------------------------------------
        # Seed all 7 style + 5 personality archetypes with bias JSON
        # (v2.0.0, Task 14.5). The 1 existing archetype per table
        # (Balanced, Calm) is preserved at ID 1; the 6+4 new ones get
        # IDs 2-7 and 2-5 respectively. _seed_archetypes returns the
        # (style_count, personality_count) tuple for the seed summary.
        # ----------------------------------------------------------------
        style_count, pers_count = _seed_archetypes(conn)
        # Look up the Balanced + Calm archetype IDs (always 1 on a
        # fresh seed — _seed_archetypes uses INSERT OR IGNORE which
        # preserves existing IDs).
        style_id = conn.execute(
            "SELECT style_archetype_id FROM style_archetypes WHERE name='Balanced'"
        ).fetchone()[0]
        pers_id = conn.execute(
            "SELECT personality_archetype_id FROM personality_archetypes "
            "WHERE name='Calm'"
        ).fetchone()[0]

        fighters = [
            ("John", "Vale", "Hammer", "male", "1994-05-11"),
            ("Marcus", "Reed", "Voltage", "male", "1992-09-03"),
        ]

        fighter_ids = []
        for first, last, nick, gender, dob in fighters:
            fid = one(conn, """
                INSERT INTO fighters (
                    first_name, last_name, nickname, gender, date_of_birth,
                    birth_city_id, birth_nation_id, residence_city_id, residence_nation_id,
                    weight_class_id, current_gym_id, current_promotion_id,
                    fight_style_archetype_id, personality_archetype_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (first, last, nick, gender, dob, city_id, nation_id, city_id, nation_id, wc_id, gym_id, promo_id, style_id, pers_id))
            fighter_ids.append(fid)
            conn.execute("INSERT INTO fighter_attributes (fighter_id) VALUES (?)", (fid,))
            conn.execute("INSERT INTO fighter_personality (fighter_id) VALUES (?)", (fid,))
            conn.execute("INSERT INTO fighter_career (fighter_id) VALUES (?)", (fid,))
            _seed_default_fighter_contract(conn, fid, promo_id)  # Task ID 9
            _seed_initial_ranking(conn, fid, wc_id, promo_id)    # Task ID 10
            # v2.0.0 backfill: fill the 21 new attribute columns,
            # 17 new personality columns, and 4 physical columns
            # (height/reach/stance/handedness) with archetype-biased
            # generated values. The 4 existing attribute values and
            # 3 existing personality values are PRESERVED (the
            # backfill reads them from the DB and overrides the
            # generated dict's keys before UPDATE).
            _backfill_fighter_v2(conn, fid, style_id, pers_id)

        staff_id = one(conn, "INSERT INTO staff (first_name, last_name, age, nation_id, role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)", ("Nina", "Cross", 41, nation_id, "commentator", "analysis", promo_id))
        conn.execute("INSERT INTO broadcast_staff (staff_id, on_air_role) VALUES (?, ?)", (staff_id, "play_by_play"))
        _seed_default_staff_contract(conn, staff_id, promo_id, role="commentator")  # Task ID 9
        # Phase A (A4): 'System Feed' is now seeded by build_db._build_fresh
        # alongside the 4 new sources (The Cage Wire, MMA Analytica,
        # Social Sphere, The Pundit's Desk). INSERT OR IGNORE here so the
        # seed is idempotent against the fresh-build seed (a re-seed on
        # an already-seeded DB doesn't crash on the UNIQUE constraint).
        conn.execute("INSERT OR IGNORE INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80))

        # ----------------------------------------------------------------
        # Seed a vacant title for AC Lightweight (Task ID 11). The
        # first title fight (is_title_fight=1 — the canonical check
        # since v2.2.0 / Task pre-B2-fix; the legacy
        # `bout_type='title_fight'` comparison is DEPRECATED but kept
        # for backward compatibility) transfers the belt to the winner
        # via _resolve_title_after_fight() in app.py. The seeded main
        # event below is a title fight so the title-transfer logic is
        # exercised end-to-end on the first resolve.
        # ----------------------------------------------------------------
        _seed_vacant_title(conn, promo_id, wc_id)  # Task ID 11

        event_id = one(conn, "INSERT INTO events (promotion_id, venue_id, market_id, event_name, event_date, event_type) VALUES (?, ?, ?, ?, ?, ?)", (promo_id, venue_id, market_id, "Alpha Combat: Test Night", "2026-08-15", "fight_night"))
        # v2.2.0 (Task pre-B2-fix): the seeded title-fight INSERT now
        # also sets `card_slot='main_event'` and `is_title_fight=1`
        # explicitly (the deprecated `bout_type='title_fight'` is kept
        # for backward compatibility — external readers that still
        # check bout_type keep working). The new columns are the
        # canonical signal that app.py reads; bout_type is a redundant
        # back-compat field.
        fight_id = one(conn, "INSERT INTO fights (event_id, weight_class_id, bout_type, card_slot, is_title_fight, round_limit, scheduled_rounds) VALUES (?, ?, ?, ?, ?, ?, ?)", (event_id, wc_id, "title_fight", "main_event", 1, 3, 3))
        conn.execute("INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)", (fight_id, fighter_ids[0], "red"))
        conn.execute("INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)", (fight_id, fighter_ids[1], "blue"))
        # event_cards: explicit is_co_main=0 (the seeded main event is
        # the main event, not the co-main). v2.2.0 added the is_co_main
        # column; the seed sets it explicitly so the row is unambiguous
        # even if a future task changes the column DEFAULT.
        conn.execute("INSERT INTO event_cards (event_id, fight_id, card_position, card_tier, is_main_event, is_co_main) VALUES (?, ?, ?, ?, ?, ?)", (event_id, fight_id, 1, "main_event", 1, 0))

        # ----------------------------------------------------------------
        # Second promotion (Rival Fight League) — inert for now, no AI
        # behaviour. Wired in per the advisor's recommendation: getting
        # the multi-promotion data shape in early is cheap; retrofitting
        # it after more systems are built is expensive. AI behaviour
        # comes in Task ID 25.
        #
        # v2.0.0 (Task 14.6): RFL gets the AI-tuning columns that Task 25
        # will read. Per the brief: broadcast_tier='local_stream'
        # (smaller than AC's 'regional_tv'), starting_budget=200000
        # (smaller than AC's 500000), ai_aggression=60 (more aggressive
        # than AC's 30 — RFL will be the AI-controlled rival that pushes
        # the player once Task 25 wires up the AI behaviour).
        # ----------------------------------------------------------------
        rfl_promo_id = one(conn,
            "INSERT INTO promotions (name, size_tier, nation_id, region_id, "
            "starting_budget, broadcast_tier, ai_aggression) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Rival Fight League", "mid", nation_id, region_id,
             200000.0, "local_stream", 60))
        rfl_gym_id = one(conn,
            "INSERT INTO gyms (name, city_id, nation_id, region_id, "
            "facility_quality, medical_support, sparring_depth, development_focus) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Steelcrest Gym", city_id, nation_id, region_id,
             60, 50, 55, 60))

        rfl_fighters = [
            ("Dario", "Knox", "The Drill", "male", "1993-11-22"),
            ("Eli", "Storm", "Whisper", "male", "1995-02-08"),
            ("Cole", "Briggs", "Anvil", "male", "1991-07-30"),
        ]
        rfl_fighter_ids = []
        for first, last, nick, gender, dob in rfl_fighters:
            fid = one(conn, """
                INSERT INTO fighters (
                    first_name, last_name, nickname, gender, date_of_birth,
                    birth_city_id, birth_nation_id, residence_city_id, residence_nation_id,
                    weight_class_id, current_gym_id, current_promotion_id,
                    fight_style_archetype_id, personality_archetype_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (first, last, nick, gender, dob, city_id, nation_id, city_id, nation_id, wc_id, rfl_gym_id, rfl_promo_id, style_id, pers_id))
            rfl_fighter_ids.append(fid)
            conn.execute("INSERT INTO fighter_attributes (fighter_id) VALUES (?)", (fid,))
            conn.execute("INSERT INTO fighter_personality (fighter_id) VALUES (?)", (fid,))
            conn.execute("INSERT INTO fighter_career (fighter_id) VALUES (?)", (fid,))
            _seed_default_fighter_contract(conn, fid, rfl_promo_id)  # Task ID 9
            _seed_initial_ranking(conn, fid, wc_id, rfl_promo_id)   # Task ID 10
            # v2.0.0 backfill (same as for AC fighters above).
            _backfill_fighter_v2(conn, fid, style_id, pers_id)

        # ----------------------------------------------------------------
        # Seed a vacant title for RFL Lightweight (Task ID 11).
        # Symmetric to the AC Lightweight title above. RFL has no
        # events scheduled (inert), so the title stays vacant until
        # a future task schedules an RFL title fight.
        # ----------------------------------------------------------------
        _seed_vacant_title(conn, rfl_promo_id, wc_id)  # Task ID 11

        # ----------------------------------------------------------------
        # Seed the name pools (Task ID 14). The regen engine
        # (generate_fighter in app.py) draws from these pools when a
        # fighter retires. 96 entries: 25 male firsts + 25 female
        # firsts + 26 lasts + 20 nicknames. Uses INSERT OR IGNORE so
        # re-seeding is idempotent.
        # ----------------------------------------------------------------
        _seed_name_pools(conn)  # Task ID 14

        # ----------------------------------------------------------------
        # Backfill `potential` for the 5 seeded fighters (v2.0.1,
        # Task pre-B1-fixes). John Vale + Marcus Reed get solid-to-
        # elite potential (72, 71); the 3 RFL fighters get medium
        # potential (50, 47, 53). `title_reigns` is left at the
        # schema DEFAULT 0 (none have won a title yet). Runs AFTER
        # all 5 fighters' fighter_career rows have been INSERTed.
        # ----------------------------------------------------------------
        _backfill_potential_title_reigns(conn)  # Task pre-B1-fixes

        conn.commit()
        print("Seeded database.")
        print(f"  Promotions: 2 (Alpha Combat [player, regional_tv, ai_aggression=30], "
              f"Rival Fight League [future AI rival, local_stream, ai_aggression=60])")
        print(f"  Gyms: 2 (Ironhouse Gym, Steelcrest Gym — both facility_quality=60)")
        print(f"  Archetypes: {style_count} style (Balanced, Striker, Grappler, Wrestler, "
              f"Brawler, Counter-Striker, Submission Specialist) + {pers_count} personality "
              f"(Calm, Aggressive, Methodical, Showman, Quiet Professional) — all with bias JSON")
        print(f"  Alpha Combat: {len(fighter_ids)} fighters, 1 event, 1 fight scheduled")
        print(f"  Rival Fight League: {len(rfl_fighter_ids)} fighters (inert, no events)")
        print(f"  Contracts: {len(fighter_ids) + len(rfl_fighter_ids)} fighter contracts + 1 staff contract")
        print(f"  Rankings: {len(fighter_ids) + len(rfl_fighter_ids)} initial ranking rows (all at 1000.0)")
        print(f"  Titles: 2 vacant (1 per promotion per weight class)")
        print(f"  Name pool: {MALE_FIRST_COUNT + FEMALE_FIRST_COUNT + LAST_COUNT + NICKNAME_COUNT} names "
              f"({MALE_FIRST_COUNT} male first, {FEMALE_FIRST_COUNT} female first, "
              f"{LAST_COUNT} last, {NICKNAME_COUNT} nicknames)")
        print(f"  Backfill: {len(fighter_ids) + len(rfl_fighter_ids)} existing fighters "
              f"backfilled with archetype-biased attributes (21 new attrs + 17 new traits "
              f"+ 4 physical columns per fighter); existing 4 attrs + 3 traits PRESERVED")
        print(f"  Potential (v2.0.1): {len(fighter_ids) + len(rfl_fighter_ids)} fighters "
              f"backfilled — AC starters (John Vale, Marcus Reed) get solid-to-elite (70-75); "
              f"RFL roster gets medium (45-55)")

if __name__ == "__main__":
    main()
