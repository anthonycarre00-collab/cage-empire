import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

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
# fight (bout_type='title_fight') transfers the belt to the winner
# via `_resolve_title_after_fight()` in app.py. The seed creates
# two titles (AC Lightweight + RFL Lightweight) so the title-
# transfer logic can be exercised end-to-end on the first resolve.
# Foundation for Task 8's schedule_next_event() (future: champion
# vs #1 contender), Task 14 (regen — retiring champions vacate),
# Task 22 (rivalries — title fight rivalries are the most heated).
# ----------------------------------------------------------------

def _seed_vacant_title(conn, promotion_id, weight_class_id):
    """Create a vacant title for a promotion's weight class.

    Called by the seed for every (promotion, weight_class) pair. The
    title starts vacant (current_champion_fighter_id IS NULL,
    is_vacant=1). The first title fight (bout_type='title_fight')
    will transfer the belt to the winner via _resolve_title_after_fight()
    in app.py.

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
        promo_id = one(conn, "INSERT INTO promotions (name, size_tier, nation_id, region_id) VALUES (?, ?, ?, ?)", ("Alpha Combat", "major", nation_id, region_id))
        gym_id = one(conn, "INSERT INTO gyms (name, city_id, nation_id, region_id) VALUES (?, ?, ?, ?)", ("Ironhouse Gym", city_id, nation_id, region_id))
        style_id = one(conn, "INSERT INTO style_archetypes (name, description) VALUES (?, ?)", ("Balanced", "Well-rounded"))
        pers_id = one(conn, "INSERT INTO personality_archetypes (name, description) VALUES (?, ?)", ("Calm", "Composed"))

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

        staff_id = one(conn, "INSERT INTO staff (first_name, last_name, age, nation_id, role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)", ("Nina", "Cross", 41, nation_id, "commentator", "analysis", promo_id))
        conn.execute("INSERT INTO broadcast_staff (staff_id, on_air_role) VALUES (?, ?)", (staff_id, "play_by_play"))
        _seed_default_staff_contract(conn, staff_id, promo_id, role="commentator")  # Task ID 9
        conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80))

        # ----------------------------------------------------------------
        # Seed a vacant title for AC Lightweight (Task ID 11). The
        # first title fight (bout_type='title_fight') transfers the
        # belt to the winner via _resolve_title_after_fight() in
        # app.py. The seeded main event below is a title fight so the
        # title-transfer logic is exercised end-to-end on the first
        # resolve.
        # ----------------------------------------------------------------
        _seed_vacant_title(conn, promo_id, wc_id)  # Task ID 11

        event_id = one(conn, "INSERT INTO events (promotion_id, venue_id, market_id, event_name, event_date, event_type) VALUES (?, ?, ?, ?, ?, ?)", (promo_id, venue_id, market_id, "Alpha Combat: Test Night", "2026-08-15", "fight_night"))
        fight_id = one(conn, "INSERT INTO fights (event_id, weight_class_id, bout_type, round_limit, scheduled_rounds) VALUES (?, ?, ?, ?, ?)", (event_id, wc_id, "title_fight", 3, 3))
        conn.execute("INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)", (fight_id, fighter_ids[0], "red"))
        conn.execute("INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)", (fight_id, fighter_ids[1], "blue"))
        conn.execute("INSERT INTO event_cards (event_id, fight_id, card_position, card_tier, is_main_event) VALUES (?, ?, ?, ?, ?)", (event_id, fight_id, 1, "main_event", 1))

        # ----------------------------------------------------------------
        # Second promotion (Rival Fight League) — inert for now, no AI
        # behaviour. Wired in per the advisor's recommendation: getting
        # the multi-promotion data shape in early is cheap; retrofitting
        # it after more systems are built is expensive. AI behaviour
        # comes in Task ID 25.
        # ----------------------------------------------------------------
        rfl_promo_id = one(conn, "INSERT INTO promotions (name, size_tier, nation_id, region_id) VALUES (?, ?, ?, ?)", ("Rival Fight League", "mid", nation_id, region_id))
        rfl_gym_id = one(conn, "INSERT INTO gyms (name, city_id, nation_id, region_id) VALUES (?, ?, ?, ?)", ("Steelcrest Gym", city_id, nation_id, region_id))

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

        conn.commit()
        print("Seeded database.")
        print(f"  Alpha Combat: {len(fighter_ids)} fighters, 1 event, 1 fight scheduled")
        print(f"  Rival Fight League: {len(rfl_fighter_ids)} fighters (inert, no events)")
        print(f"  Contracts: {len(fighter_ids) + len(rfl_fighter_ids)} fighter contracts + 1 staff contract")
        print(f"  Rankings: {len(fighter_ids) + len(rfl_fighter_ids)} initial ranking rows (all at 1000.0)")
        print(f"  Titles: 2 vacant (1 per promotion per weight class)")
        print(f"  Name pool: {MALE_FIRST_COUNT + FEMALE_FIRST_COUNT + LAST_COUNT + NICKNAME_COUNT} names "
              f"({MALE_FIRST_COUNT} male first, {FEMALE_FIRST_COUNT} female first, "
              f"{LAST_COUNT} last, {NICKNAME_COUNT} nicknames)")

if __name__ == "__main__":
    main()
