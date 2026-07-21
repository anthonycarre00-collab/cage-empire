from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "cage_empire.db"

# Schema version — see docs/CONVENTIONS.md for the versioning rules.
# Bump this on every schema change. Format: MAJOR.MINOR.PATCH.
CODE_SCHEMA_VERSION = "1.4.0"


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
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS gyms (
    gym_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    city_id INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS style_archetypes (
    style_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS personality_archetypes (
    personality_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_attributes (
    fighter_attribute_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    punch_power INTEGER NOT NULL DEFAULT 50,
    cardio INTEGER NOT NULL DEFAULT 50,
    fight_iq INTEGER NOT NULL DEFAULT 50,
    chin INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_personality (
    fighter_personality_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    aggression INTEGER NOT NULL DEFAULT 50,
    composure INTEGER NOT NULL DEFAULT 50,
    morale INTEGER NOT NULL DEFAULT 50,
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
            (f"v{CODE_SCHEMA_VERSION.replace('.', '_')}_add_contracts",),
        )
        conn.execute("INSERT INTO simulation_clock (clock_id, current_date, current_day, current_week, current_month, current_year) VALUES (1, '2026-07-20', 1, 1, 7, 2026)")
        conn.commit()
    print(f"Rebuilt database at {DB_PATH}")
    print(f"Schema version: {CODE_SCHEMA_VERSION}")

if __name__ == "__main__":
    main()
