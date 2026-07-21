import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "mma_booking_sim_v1_2.db"

def one(conn, sql, params=()):
    return conn.execute(sql, params).lastrowid

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

        staff_id = one(conn, "INSERT INTO staff (first_name, last_name, age, nation_id, role_type, specialty, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?)", ("Nina", "Cross", 41, nation_id, "commentator", "analysis", promo_id))
        conn.execute("INSERT INTO broadcast_staff (staff_id, on_air_role) VALUES (?, ?)", (staff_id, "play_by_play"))
        conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80))

        event_id = one(conn, "INSERT INTO events (promotion_id, venue_id, market_id, event_name, event_date, event_type) VALUES (?, ?, ?, ?, ?, ?)", (promo_id, venue_id, market_id, "Alpha Combat: Test Night", "2026-08-15", "fight_night"))
        fight_id = one(conn, "INSERT INTO fights (event_id, weight_class_id, bout_type, round_limit, scheduled_rounds) VALUES (?, ?, ?, ?, ?)", (event_id, wc_id, "main_event", 3, 3))
        conn.execute("INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)", (fight_id, fighter_ids[0], "red"))
        conn.execute("INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)", (fight_id, fighter_ids[1], "blue"))
        conn.execute("INSERT INTO event_cards (event_id, fight_id, card_position, card_tier, is_main_event) VALUES (?, ?, ?, ?, ?)", (event_id, fight_id, 1, "main_event", 1))

        conn.commit()
        print("Seeded database.")

if __name__ == "__main__":
    main()