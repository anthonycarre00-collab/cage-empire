from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "mma_booking_sim_v1_2.db"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

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
"""

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO simulation_clock (clock_id, current_date, current_day, current_week, current_month, current_year) VALUES (1, '2026-07-20', 1, 1, 7, 2026)")
        conn.commit()
    print(f"Rebuilt database at {DB_PATH}")

if __name__ == "__main__":
    main()