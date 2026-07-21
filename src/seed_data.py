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

        staff_id = one(conn, "INSERT INTO staff (first_name, last_name, age, nation_id, role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)", ("Nina", "Cross", 41, nation_id, "commentator", "analysis", promo_id))
        conn.execute("INSERT INTO broadcast_staff (staff_id, on_air_role) VALUES (?, ?)", (staff_id, "play_by_play"))
        _seed_default_staff_contract(conn, staff_id, promo_id, role="commentator")  # Task ID 9
        conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80))

        event_id = one(conn, "INSERT INTO events (promotion_id, venue_id, market_id, event_name, event_date, event_type) VALUES (?, ?, ?, ?, ?, ?)", (promo_id, venue_id, market_id, "Alpha Combat: Test Night", "2026-08-15", "fight_night"))
        fight_id = one(conn, "INSERT INTO fights (event_id, weight_class_id, bout_type, round_limit, scheduled_rounds) VALUES (?, ?, ?, ?, ?)", (event_id, wc_id, "main_event", 3, 3))
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

        conn.commit()
        print("Seeded database.")
        print(f"  Alpha Combat: {len(fighter_ids)} fighters, 1 event, 1 fight scheduled")
        print(f"  Rival Fight League: {len(rfl_fighter_ids)} fighters (inert, no events)")
        print(f"  Contracts: {len(fighter_ids) + len(rfl_fighter_ids)} fighter contracts + 1 staff contract")

if __name__ == "__main__":
    main()
