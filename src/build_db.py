from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "cage_empire.db"

# Schema version — see docs/CONVENTIONS.md for the versioning rules.
# Bump this on every schema change. Format: MAJOR.MINOR.PATCH.
#
# v2.0.0 (Task 14.5+14.6+14.7) — MAJOR bump. First major version,
# marking the transition from the thin skeleton (4 attributes, 3
# personality traits, coin-flip-equivalent resolver) to real
# simulation depth (25 attributes, 20 personality traits, full
# physical + meta columns on fighters, AI-tuning columns on
# promotions, training-camp-relevant columns on gyms, archetype
# bias JSON for variety in regen). 68 new columns across 6 existing
# tables + 2 archetype tables, plus a new module src/fighter_gen.py,
# plus the long-flagged current_date SQLite quirk fix (§Z.6). No new
# tables, no columns removed — this is purely an additive expansion
# (the MAJOR bump is for the depth-of-sim significance, not for any
# breaking change to existing data shape).
CODE_SCHEMA_VERSION = "2.0.0"


def _parse_version(v):
    """Parse a semver string 'MAJOR.MINOR.PATCH' into a tuple of ints.

    Each dotted component is parsed by extracting its leading digit
    prefix as an int. This means '1.0.0-beta' parses as (1, 0, 0) —
    the prerelease suffix '-beta' on the PATCH component is silently
    dropped. This is a deliberate simplification: in practice, schema
    versions are always plain MAJOR.MINOR.PATCH (no prereleases), and
    the brief explicitly allows 'pad and compare ints' handling for
    the '1.0.0-beta' edge case (see docs/STAGES.md Task ID 5 case 7,
    option A). Trade-off: '1.0.0-beta' compares equal to '1.0.0'.
    """
    nums = []
    for part in v.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        nums.append(int(digits) if digits else 0)
    return tuple(nums)


def _compare_versions(a, b):
    """Return -1 if a < b, 0 if a == b, +1 if a > b. Semver comparison.

    Splits on '.', compares each component as an int. Pads shorter
    tuples with zeros (so '1.3' == '1.3.0'). Correctly handles
    '1.10.0' > '1.9.0' (string comparison would get this wrong, which
    is the whole reason this helper exists).
    """
    ta, tb = _parse_version(a), _parse_version(b)
    # Pad to equal length (in case one has more components than the other).
    n = max(len(ta), len(tb))
    ta += (0,) * (n - len(ta))
    tb += (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def _read_on_disk_schema_version(db_path):
    """Return the on-disk schema_version string, or None if it cannot be read.

    Returns None when:
      - the DB file does not exist, or
      - the DB has no schema_meta table (prints a warning), or
      - schema_meta exists but has no row for schema_name='cage_empire'
        (prints a warning), or
      - the DB file is corrupt / unreadable (silent — treated as no
        version, allows rebuild).

    Uses mode=ro URI to open the DB read-only, which avoids creating
    WAL/journal files just for the version check and works cleanly on
    Windows where file locking is stricter. See docs/CONVENTIONS.md
    §1.4 (Task ID 5).
    """
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            )
            if cur.fetchone() is None:
                print(f"Warning: no schema_meta table in {db_path} — "
                      f"proceeding with rebuild (treating as pre-versioning DB).")
                return None
            row = conn.execute(
                "SELECT schema_version FROM schema_meta WHERE schema_name=?",
                ("cage_empire",),
            ).fetchone()
            if row is None:
                print(f"Warning: schema_meta exists but no row for "
                      f"schema_name='cage_empire' — proceeding with rebuild.")
                return None
            return row[0]
    except sqlite3.DatabaseError:
        # Corrupt or unreadable DB — treat as no version, allow rebuild.
        return None


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------
-- Schema meta & versioning (restored in v1.2.1, see
-- docs/CONVENTIONS.md §1 for the rules).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    schema_name    TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS simulation_clock (
    clock_id INTEGER PRIMARY KEY CHECK (clock_id = 1),
    current_date TEXT NOT NULL,
    current_day INTEGER NOT NULL,
    current_week INTEGER NOT NULL,
    current_month INTEGER NOT NULL,
    current_year INTEGER NOT NULL,
    current_tick_type TEXT NOT NULL DEFAULT 'day',
    tick_counter INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS nations (
    nation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    language TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS regions (
    region_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    style_preferences TEXT,
    fan_preferences TEXT,
    market_growth INTEGER NOT NULL DEFAULT 50 CHECK (market_growth BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS weight_classes (
    weight_class_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    min_weight_kg REAL,
    max_weight_kg REAL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS cities (
    city_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    population INTEGER,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (nation_id, name)
);

CREATE TABLE IF NOT EXISTS markets (
    market_id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL UNIQUE REFERENCES cities(city_id) ON DELETE CASCADE,
    market_type TEXT NOT NULL DEFAULT 'standard',
    heat_level INTEGER NOT NULL DEFAULT 50 CHECK (heat_level BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS promotions (
    promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    size_tier TEXT NOT NULL DEFAULT 'small',
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    current_cash REAL NOT NULL DEFAULT 0,
    reputation INTEGER NOT NULL DEFAULT 50 CHECK (reputation BETWEEN 0 AND 100),
    fan_trust INTEGER NOT NULL DEFAULT 50 CHECK (fan_trust BETWEEN 0 AND 100),
    -- 6 new columns added v2.0.0 (Task 14.6). These were flagged as
    -- THIN in SCHEMA_DRIFT_AUDIT.md §Z.4 and are needed by:
    --   - Task 25 (rival promotion AI) — ai_aggression + ai_spending_style
    --   - Task 20 (finances) + Task 26 (show rating) — broadcast_tier
    --   - Task 23 (news engine) — brand_tone for promotion voice
    -- brand_tone + broadcast_tier + ownership_type + ai_spending_style
    -- are TEXT with no CHECK constraint (allowed values are open-ended
    -- for future expansion); ai_aggression has a CHECK (0-100) like the
    -- other 0-100 promotion columns above.
    brand_tone TEXT NOT NULL DEFAULT 'standard',
    starting_budget REAL NOT NULL DEFAULT 0,
    broadcast_tier TEXT NOT NULL DEFAULT 'local_stream',
    ownership_type TEXT NOT NULL DEFAULT 'startup',
    ai_aggression INTEGER NOT NULL DEFAULT 50 CHECK (ai_aggression BETWEEN 0 AND 100),
    ai_spending_style TEXT NOT NULL DEFAULT 'balanced',
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS gyms (
    gym_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    city_id INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    -- 8 new columns added v2.0.0 (Task 14.6). Flagged THIN in
    -- SCHEMA_DRIFT_AUDIT.md §C — needed by Task 16 (training camps)
    -- and Task 17 (weight cuts). All 5 INTEGER columns have CHECK
    -- (0-100) like the other 0-100 gym-relevant columns. culture_tone
    -- is open-ended TEXT (future values: 'disciplined', 'loose',
    -- 'predator', etc.). membership_cost is REAL (currency, in
    -- dollars) — Task 20 finances will use it.
    reputation INTEGER NOT NULL DEFAULT 50 CHECK (reputation BETWEEN 0 AND 100),
    membership_cost REAL NOT NULL DEFAULT 0,
    facility_quality INTEGER NOT NULL DEFAULT 50 CHECK (facility_quality BETWEEN 0 AND 100),
    medical_support INTEGER NOT NULL DEFAULT 50 CHECK (medical_support BETWEEN 0 AND 100),
    sparring_depth INTEGER NOT NULL DEFAULT 50 CHECK (sparring_depth BETWEEN 0 AND 100),
    development_focus INTEGER NOT NULL DEFAULT 50 CHECK (development_focus BETWEEN 0 AND 100),
    culture_tone TEXT NOT NULL DEFAULT 'balanced',
    weight_cut_support INTEGER NOT NULL DEFAULT 50 CHECK (weight_cut_support BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS style_archetypes (
    style_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    -- attribute_bias (added v2.0.0, Task 14.5) holds a JSON dict
    -- mapping attribute names to +/- integer bias values, e.g.
    -- {"punch_power": 15, "takedown_defense": -10}. Used by
    -- fighter_gen.generate_attribute_block(archetype_id, conn) when
    -- generating new fighters (regen) or backfilling existing ones.
    -- Nullable — old code that doesn't set it gets NULL, which
    -- fighter_gen treats as "no bias" (equivalent to {}).
    -- See docs/STAGES.md §14.5 for the 7 seeded bias values.
    attribute_bias TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS personality_archetypes (
    personality_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    -- trait_bias (added v2.0.0, Task 14.5) — symmetric to
    -- style_archetypes.attribute_bias but for personality fields.
    -- Used by fighter_gen.generate_personality_block(archetype_id, conn).
    trait_bias TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighters (
    fighter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    nickname TEXT,
    gender TEXT NOT NULL DEFAULT 'unknown',
    date_of_birth TEXT NOT NULL,
    birth_city_id INTEGER REFERENCES cities(city_id) ON DELETE SET NULL,
    birth_nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    residence_city_id INTEGER REFERENCES cities(city_id) ON DELETE SET NULL,
    residence_nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    weight_class_id INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,
    current_gym_id INTEGER REFERENCES gyms(gym_id) ON DELETE SET NULL,
    current_promotion_id INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    fight_style_archetype_id INTEGER REFERENCES style_archetypes(style_archetype_id) ON DELETE SET NULL,
    personality_archetype_id INTEGER REFERENCES personality_archetypes(personality_archetype_id) ON DELETE SET NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    is_retired INTEGER NOT NULL DEFAULT 0 CHECK (is_retired IN (0,1)),
    -- 14 new columns added v2.0.0 (Task 14.6). Flagged THIN in
    -- SCHEMA_DRIFT_AUDIT.md §Z.3. Needed by:
    --   - Task 15 (injuries) — injury_proneness
    --   - Task 17 (weight cuts) — weight_cut_difficulty
    --   - Task 19 (voice layer) — height_cm, reach_cm, stance,
    --     handedness, marketability, fan_friendliness
    --   - Task 20 (finances) + Task 26 (show rating) — marketability,
    --     fan_friendliness, promo_boost
    --   - Death/career-end system — is_deceased
    --   - Task 24 (matchup analysis) — preferred_gameplans,
    --     bad_matchup_tags (JSON arrays)
    -- height_cm and reach_cm are nullable INTEGER (no CHECK) — a
    -- future regen or import path might not have these. stance and
    -- handedness have CHECK constraints matching the brief. The 6
    -- 0-100 INTEGER columns follow the same pattern as the existing
    -- is_active/is_retired CHECK columns. promo_boost is the only
    -- column that allows -100..100 (it's a delta, not a 0-100 score).
    -- preferred_gameplans and bad_matchup_tags are TEXT (JSON arrays);
    -- NULL is allowed and means "no preference" / "no known bad
    -- matchups" respectively.
    height_cm INTEGER,
    reach_cm INTEGER,
    stance TEXT CHECK (stance IN ('orthodox','southpaw','switch')),
    handedness TEXT CHECK (handedness IN ('right','left','ambidextrous')),
    injury_proneness INTEGER NOT NULL DEFAULT 50 CHECK (injury_proneness BETWEEN 0 AND 100),
    weight_cut_difficulty INTEGER NOT NULL DEFAULT 50 CHECK (weight_cut_difficulty BETWEEN 0 AND 100),
    consistency INTEGER NOT NULL DEFAULT 50 CHECK (consistency BETWEEN 0 AND 100),
    clutch_factor INTEGER NOT NULL DEFAULT 50 CHECK (clutch_factor BETWEEN 0 AND 100),
    marketability INTEGER NOT NULL DEFAULT 50 CHECK (marketability BETWEEN 0 AND 100),
    fan_friendliness INTEGER NOT NULL DEFAULT 50 CHECK (fan_friendliness BETWEEN 0 AND 100),
    promo_boost INTEGER NOT NULL DEFAULT 0 CHECK (promo_boost BETWEEN -100 AND 100),
    preferred_gameplans TEXT,
    bad_matchup_tags TEXT,
    is_deceased INTEGER NOT NULL DEFAULT 0 CHECK (is_deceased IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_attributes (
    fighter_attribute_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    -- Existing 4 attributes (preserved across the v2.0.0 migration —
    -- their values are NOT touched by the backfill). No CHECK
    -- constraint is added retroactively, to avoid breaking existing
    -- tests that UPDATE these columns with arbitrary values like
    -- 90/30/50 (test_fight_resolver, test_fight_history, etc.).
    punch_power INTEGER NOT NULL DEFAULT 50,
    cardio INTEGER NOT NULL DEFAULT 50,
    fight_iq INTEGER NOT NULL DEFAULT 50,
    chin INTEGER NOT NULL DEFAULT 50,
    -- 21+ new attributes added v2.0.0 (Task 14.5). All CHECK (0-100)
    -- per the brief — these are NEW columns so adding CHECK constraints
    -- is safe (no existing data to violate). The fighter_gen module
    -- generates values via clamp(50 + bias + noise), so they will
    -- always satisfy the CHECK. The 5 groups per STAGES.md §14.5:
    --   Striking:  punch_accuracy, kick_power, kick_accuracy, head_movement
    --   Range:     footwork, clinch_striking, clinch_offense, clinch_defense
    --   Grappling: takedown_offense, takedown_defense, top_control,
    --              bottom_game, submission_offense, submission_defense,
    --              scramble_ability, cage_wrestling
    --   Physical:  recovery_rate, speed_explosiveness, strength,
    --              durability, flexibility
    --   Mental:    adaptability
    -- Note: the brief says "21 new columns" but the column-name list
    -- contains 22 names (4+4+8+5+1=22). Implemented all 22 from the
    -- list — the column-name list is the authoritative spec. The
    -- "21" in the brief's prose is an off-by-one typo. See worklog
    -- decision D1 for the full explanation.
    punch_accuracy INTEGER NOT NULL DEFAULT 50 CHECK (punch_accuracy BETWEEN 0 AND 100),
    kick_power INTEGER NOT NULL DEFAULT 50 CHECK (kick_power BETWEEN 0 AND 100),
    kick_accuracy INTEGER NOT NULL DEFAULT 50 CHECK (kick_accuracy BETWEEN 0 AND 100),
    head_movement INTEGER NOT NULL DEFAULT 50 CHECK (head_movement BETWEEN 0 AND 100),
    footwork INTEGER NOT NULL DEFAULT 50 CHECK (footwork BETWEEN 0 AND 100),
    clinch_striking INTEGER NOT NULL DEFAULT 50 CHECK (clinch_striking BETWEEN 0 AND 100),
    clinch_offense INTEGER NOT NULL DEFAULT 50 CHECK (clinch_offense BETWEEN 0 AND 100),
    clinch_defense INTEGER NOT NULL DEFAULT 50 CHECK (clinch_defense BETWEEN 0 AND 100),
    takedown_offense INTEGER NOT NULL DEFAULT 50 CHECK (takedown_offense BETWEEN 0 AND 100),
    takedown_defense INTEGER NOT NULL DEFAULT 50 CHECK (takedown_defense BETWEEN 0 AND 100),
    top_control INTEGER NOT NULL DEFAULT 50 CHECK (top_control BETWEEN 0 AND 100),
    bottom_game INTEGER NOT NULL DEFAULT 50 CHECK (bottom_game BETWEEN 0 AND 100),
    submission_offense INTEGER NOT NULL DEFAULT 50 CHECK (submission_offense BETWEEN 0 AND 100),
    submission_defense INTEGER NOT NULL DEFAULT 50 CHECK (submission_defense BETWEEN 0 AND 100),
    scramble_ability INTEGER NOT NULL DEFAULT 50 CHECK (scramble_ability BETWEEN 0 AND 100),
    cage_wrestling INTEGER NOT NULL DEFAULT 50 CHECK (cage_wrestling BETWEEN 0 AND 100),
    recovery_rate INTEGER NOT NULL DEFAULT 50 CHECK (recovery_rate BETWEEN 0 AND 100),
    speed_explosiveness INTEGER NOT NULL DEFAULT 50 CHECK (speed_explosiveness BETWEEN 0 AND 100),
    strength INTEGER NOT NULL DEFAULT 50 CHECK (strength BETWEEN 0 AND 100),
    durability INTEGER NOT NULL DEFAULT 50 CHECK (durability BETWEEN 0 AND 100),
    flexibility INTEGER NOT NULL DEFAULT 50 CHECK (flexibility BETWEEN 0 AND 100),
    adaptability INTEGER NOT NULL DEFAULT 50 CHECK (adaptability BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_personality (
    fighter_personality_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    -- Existing 3 personality fields (preserved across the v2.0.0
    -- migration — their values are NOT touched by the backfill). No
    -- CHECK constraint added retroactively, to avoid breaking existing
    -- tests that UPDATE these columns (test_fight_resolver, etc.).
    aggression INTEGER NOT NULL DEFAULT 50,
    composure INTEGER NOT NULL DEFAULT 50,
    morale INTEGER NOT NULL DEFAULT 50,
    -- 17 new personality fields added v2.0.0 (Task 14.5). All CHECK
    -- (0-100). The 4 groups per STAGES.md §14.5:
    --   Temperament: risk_taking, killer_instinct, grit, discipline, patience
    --   Career:      ambition, loyalty, charisma, attention_seeking,
    --                coachability, professionalism
    --   Resilience:  ego, resilience, sportsmanship, travel_comfort
    --   Dynamic:     focus, fatigue_tolerance
    risk_taking INTEGER NOT NULL DEFAULT 50 CHECK (risk_taking BETWEEN 0 AND 100),
    killer_instinct INTEGER NOT NULL DEFAULT 50 CHECK (killer_instinct BETWEEN 0 AND 100),
    grit INTEGER NOT NULL DEFAULT 50 CHECK (grit BETWEEN 0 AND 100),
    discipline INTEGER NOT NULL DEFAULT 50 CHECK (discipline BETWEEN 0 AND 100),
    patience INTEGER NOT NULL DEFAULT 50 CHECK (patience BETWEEN 0 AND 100),
    ambition INTEGER NOT NULL DEFAULT 50 CHECK (ambition BETWEEN 0 AND 100),
    loyalty INTEGER NOT NULL DEFAULT 50 CHECK (loyalty BETWEEN 0 AND 100),
    charisma INTEGER NOT NULL DEFAULT 50 CHECK (charisma BETWEEN 0 AND 100),
    attention_seeking INTEGER NOT NULL DEFAULT 50 CHECK (attention_seeking BETWEEN 0 AND 100),
    coachability INTEGER NOT NULL DEFAULT 50 CHECK (coachability BETWEEN 0 AND 100),
    professionalism INTEGER NOT NULL DEFAULT 50 CHECK (professionalism BETWEEN 0 AND 100),
    ego INTEGER NOT NULL DEFAULT 50 CHECK (ego BETWEEN 0 AND 100),
    resilience INTEGER NOT NULL DEFAULT 50 CHECK (resilience BETWEEN 0 AND 100),
    sportsmanship INTEGER NOT NULL DEFAULT 50 CHECK (sportsmanship BETWEEN 0 AND 100),
    travel_comfort INTEGER NOT NULL DEFAULT 50 CHECK (travel_comfort BETWEEN 0 AND 100),
    focus INTEGER NOT NULL DEFAULT 50 CHECK (focus BETWEEN 0 AND 100),
    fatigue_tolerance INTEGER NOT NULL DEFAULT 50 CHECK (fatigue_tolerance BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_career (
    fighter_career_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    record_wins INTEGER NOT NULL DEFAULT 0,
    record_losses INTEGER NOT NULL DEFAULT 0,
    record_draws INTEGER NOT NULL DEFAULT 0,
    win_streak INTEGER NOT NULL DEFAULT 0,
    loss_streak INTEGER NOT NULL DEFAULT 0,
    career_health INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS staff (
    staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    age INTEGER NOT NULL,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    role_type TEXT NOT NULL,
    specialty TEXT,
    promotion_id INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS broadcast_staff (
    broadcast_staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL UNIQUE REFERENCES staff(staff_id) ON DELETE CASCADE,
    on_air_role TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    venue_id INTEGER NOT NULL REFERENCES venues(venue_id) ON DELETE RESTRICT,
    market_id INTEGER NOT NULL REFERENCES markets(market_id) ON DELETE RESTRICT,
    event_name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fights (
    fight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    weight_class_id INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE RESTRICT,
    bout_type TEXT NOT NULL,
    round_limit INTEGER NOT NULL DEFAULT 3,
    scheduled_rounds INTEGER NOT NULL DEFAULT 3,
    winner_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    loser_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    result_type TEXT,
    finish_round INTEGER,
    finish_time TEXT,
    performance_rating INTEGER,
    fan_reaction_rating INTEGER,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fight_participants (
    fight_participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE RESTRICT,
    corner TEXT NOT NULL,
    is_winner INTEGER NOT NULL DEFAULT 0 CHECK (is_winner IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, fighter_id)
);

CREATE TABLE IF NOT EXISTS event_cards (
    event_card_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    fight_id INTEGER NOT NULL UNIQUE REFERENCES fights(fight_id) ON DELETE CASCADE,
    card_position INTEGER NOT NULL,
    card_tier TEXT NOT NULL,
    is_main_event INTEGER NOT NULL DEFAULT 0 CHECK (is_main_event IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS news_sources (
    news_source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    credibility INTEGER NOT NULL DEFAULT 50,
    sensationalism INTEGER NOT NULL DEFAULT 50,
    bias INTEGER NOT NULL DEFAULT 50,
    regional_reach INTEGER NOT NULL DEFAULT 50,
    reliability INTEGER NOT NULL DEFAULT 50,
    frequency INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS news_items (
    news_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_source_id INTEGER NOT NULL REFERENCES news_sources(news_source_id) ON DELETE RESTRICT,
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    sentiment TEXT NOT NULL DEFAULT 'neutral',
    topic TEXT NOT NULL,
    event_id INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    promotion_id INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    published_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS commentary_segments (
    commentary_segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
    fight_id INTEGER REFERENCES fights(fight_id) ON DELETE CASCADE,
    segment_type TEXT NOT NULL,
    speaker_staff_id INTEGER REFERENCES staff(staff_id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- fight_history (added in v1.3.0, Task ID 4).
-- Per-fighter, per-fight history row — separate from the mutable
-- `fighter_career` counters. Two rows are written per resolved fight
-- (one per fighter, from their perspective). Required by upcoming
-- rankings, legacy, and stats-based commentary work (Tasks 10, 11,
-- 14, 19, 23) — reconstructing it later from `record_wins` would be
-- impossible. See docs/STAGES.md Task ID 4 for the brief.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fight_history (
    fight_history_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id           INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    fighter_id         INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    opponent_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    outcome            TEXT NOT NULL CHECK (outcome IN ('win','loss','draw','nc')),
    result_type        TEXT,
    finish_round       INTEGER,
    finish_time        TEXT,
    score_margin       INTEGER,
    event_id           INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    event_date         TEXT,
    weight_class_id    INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,
    title_at_stake     INTEGER NOT NULL DEFAULT 0 CHECK (title_at_stake IN (0,1)),
    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, fighter_id)
);

-- ----------------------------------------------------------------
-- Contracts (added in v1.4.0, Task ID 9).
-- 4 tables: contracts (polymorphic base) + fighter_contracts +
-- staff_contracts + broadcast_contracts (subtype tables). The base
-- table holds the common fields (promotion_id, dates, salary,
-- exclusivity, status); the subtype tables hold the FK to the
-- contracted entity (fighter / staff / broadcast_staff).
-- Polymorphic-association pattern: contracts.contract_target_type
-- is 'fighter' / 'staff' / 'broadcast', and the corresponding
-- subtype table has the FK. This avoids a single nullable FK column
-- on the base table (which would have no FK constraint).
-- See docs/SCHEMA_DRIFT_AUDIT.md §F and docs/STAGES.md Task ID 9.
-- Foundation for Task ID 13 (free agency + signings) and Task ID 25
-- (rival promotion AI poaching).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contracts (
    contract_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_target_type TEXT NOT NULL CHECK (contract_target_type IN ('fighter', 'staff', 'broadcast')),
    promotion_id         INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    start_date           TEXT NOT NULL,
    end_date             TEXT NOT NULL,
    salary               REAL NOT NULL DEFAULT 0 CHECK (salary >= 0),
    bonus_structure      TEXT,
    buyout_clause        REAL,
    exclusive_flag       INTEGER NOT NULL DEFAULT 1 CHECK (exclusive_flag IN (0, 1)),
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'terminated', 'renegotiating')),
    created_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS fighter_contracts (
    fighter_contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         INTEGER NOT NULL UNIQUE REFERENCES contracts(contract_id) ON DELETE CASCADE,
    fighter_id          INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    contract_type       TEXT NOT NULL DEFAULT 'standard' CHECK (contract_type IN ('standard', 'champion', 'prospect', 'veteran')),
    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS staff_contracts (
    staff_contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id       INTEGER NOT NULL UNIQUE REFERENCES contracts(contract_id) ON DELETE CASCADE,
    staff_id          INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    contract_role     TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS broadcast_contracts (
    broadcast_contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id           INTEGER NOT NULL UNIQUE REFERENCES contracts(contract_id) ON DELETE CASCADE,
    staff_id              INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    network_name          TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- Rankings (added in v1.5.0, Task ID 10).
-- One row per fighter per weight class per promotion. Auto-updated
-- on fight resolution by `_update_rankings_after_resolution()` in
-- app.py using a simple ELO-style rating system (K=32, zero-sum).
-- Foundation for Task ID 11 (titles — champion vs #1 contender),
-- Task ID 14 (regen — new fighters enter at the bottom at rating
-- 1000.0), and Task ID 22 (rivalries — ranking proximity boosts
-- heat). The `rankings` UNIQUE (fighter_id, weight_class_id,
-- promotion_id) constraint ensures one row per fighter per WC per
-- promotion; the same fighter fighting in two promotions gets two
-- ranking rows (cross-promotional ranking is out of scope until
-- Task 25+). See docs/SCHEMA_DRIFT_AUDIT.md §K and
-- docs/STAGES.md Task ID 10.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rankings (
    ranking_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    weight_class_id INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE CASCADE,
    promotion_id    INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    rating          REAL NOT NULL DEFAULT 1000.0 CHECK (rating >= 0),
    fights_count    INTEGER NOT NULL DEFAULT 0 CHECK (fights_count >= 0),
    wins            INTEGER NOT NULL DEFAULT 0 CHECK (wins >= 0),
    losses          INTEGER NOT NULL DEFAULT 0 CHECK (losses >= 0),
    draws           INTEGER NOT NULL DEFAULT 0 CHECK (draws >= 0),
    last_fight_date TEXT,
    created_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_id, weight_class_id, promotion_id)
);

-- ----------------------------------------------------------------
-- Titles (added in v1.6.0, Task ID 11).
-- One row per belt per promotion per weight class. Tracks the
-- current champion, when they won it, how many defenses they've
-- made, and whether the title is vacant. Foundation for Task 8's
-- schedule_next_event() (future: champion vs #1 contender), Task
-- 14 (regen - retiring champions vacate), Task 22 (rivalries -
-- title fight rivalries are the most heated).
--
-- A title is "vacant" when current_champion_fighter_id IS NULL.
-- The seed creates all titles as vacant. The first title fight
-- transfers the belt to the winner. Subsequent title fights are
-- the champion defending against a contender. If a champion
-- retires (Task 12) or leaves (Task 13), the title is vacated.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS titles (
    title_id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id                 INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    weight_class_id              INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE CASCADE,
    current_champion_fighter_id  INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    champion_since_date          TEXT,
    title_reigns_count           INTEGER NOT NULL DEFAULT 0 CHECK (title_reigns_count >= 0),
    title_defenses_count         INTEGER NOT NULL DEFAULT 0 CHECK (title_defenses_count >= 0),
    is_vacant                    INTEGER NOT NULL DEFAULT 1 CHECK (is_vacant IN (0, 1)),
    created_at                   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at                   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (promotion_id, weight_class_id)
);

-- ----------------------------------------------------------------
-- Name pools + regen lineage (added in v1.9.0, Task ID 14).
-- When a fighter retires, a replacement is generated from the name
-- pools with a similar style DNA. The new fighter enters as a free
-- agent (current_promotion_id=NULL, is_active=1, is_retired=0) and
-- appears in Task 13's Free Agents tab, ready to be signed by any
-- promotion. regen_lineage tracks which retiring fighter spawned
-- which replacement (for future memory-resurfacing features in
-- Stage 3+). fighter_memory_links exists in this task but is NOT
-- populated — memory resurfacing (style echoes, gym heirs, regional
-- rivals, successors) is a future enhancement that will write to
-- this table without needing a schema change.
--
-- Note on `used_names`: the spec calls for a separate `used_names`
-- table to prevent duplicate fighter names. We chose to check
-- uniqueness against the existing `fighters` table (first_name +
-- last_name combination) instead. This is simpler, avoids a
-- redundant table, and stays correct when fighters are deleted
-- (their names become available again, which matches the design
-- intent — the world doesn't keep a permanent name registry). The
-- generate_fighter() function in app.py implements this check.
-- See docs/SCHEMA_DRIFT_AUDIT.md §M and docs/STAGES.md Task ID 14.
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS name_pools (
    name_pool_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name_type       TEXT NOT NULL CHECK (name_type IN ('first_male', 'first_female', 'last', 'nickname')),
    name_value      TEXT NOT NULL,
    region          TEXT,
    created_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (name_type, name_value)
);

CREATE TABLE IF NOT EXISTS regen_lineage (
    regen_lineage_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    retiring_fighter_id    INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    replacement_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    style_dna_archetype_id INTEGER REFERENCES style_archetypes(style_archetype_id) ON DELETE SET NULL,
    regen_date             TEXT NOT NULL,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (retiring_fighter_id, replacement_fighter_id)
);

CREATE TABLE IF NOT EXISTS fighter_memory_links (
    memory_link_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    link_type         TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor')),
    link_strength     INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_id, linked_fighter_id, link_type)
);
"""

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- version-check gate (Task ID 5) ---------------------------
    # See docs/CONVENTIONS.md §1.4. Prevents an older build_db.py
    # from silently clobbering a newer schema. This is the gate that
    # closes the 37 -> 24 table drift that already happened twice.
    # The check happens BEFORE the DB_PATH.unlink() call so that
    # refusing does not destroy the on-disk schema.
    on_disk = _read_on_disk_schema_version(DB_PATH)
    if on_disk is not None:
        cmp = _compare_versions(on_disk, CODE_SCHEMA_VERSION)
        if cmp > 0:
            raise RuntimeError(
                f"Refusing to rebuild: on-disk schema version {on_disk} is newer "
                f"than code version {CODE_SCHEMA_VERSION}. This would silently "
                f"destroy schema work. Either:\n"
                f"  (a) upgrade build_db.py to support the newer schema, or\n"
                f"  (b) delete {DB_PATH} manually if you really want to start fresh."
            )
        elif cmp < 0:
            print(f"Upgrading schema: {on_disk} -> {CODE_SCHEMA_VERSION} (rebuilding).")
        else:
            print(f"Rebuilding same schema version {CODE_SCHEMA_VERSION}.")
    # ---- end version-check gate -----------------------------------

    if DB_PATH.exists():
        DB_PATH.unlink()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL)
        # Record the schema version + migration (see docs/CONVENTIONS.md §1).
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (schema_name, schema_version) VALUES (?, ?)",
            ("cage_empire", CODE_SCHEMA_VERSION),
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (?)",
            (f"v{CODE_SCHEMA_VERSION.replace('.', '_')}_fighter_schema_expansion",),
        )
        conn.execute("INSERT INTO simulation_clock (clock_id, current_date, current_day, current_week, current_month, current_year) VALUES (1, '2026-07-20', 1, 1, 7, 2026)")
        conn.commit()
    print(f"Rebuilt database at {DB_PATH}")
    print(f"Schema version: {CODE_SCHEMA_VERSION}")

if __name__ == "__main__":
    main()
