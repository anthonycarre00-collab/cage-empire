import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "mma_booking_sim_v1_2.db"

def run_tick(conn, tick_type="day", steps=1):
    for _ in range(steps):
        row = conn.execute("SELECT current_date, current_day, current_week, current_month, current_year FROM simulation_clock WHERE clock_id=1").fetchone()
        dt = datetime.strptime(row[0], "%Y-%m-%d") + timedelta(days=1)
        day = row[1] + 1
        week = ((day - 1) // 7) + 1
        conn.execute(
            "UPDATE simulation_clock SET current_date=?, current_day=?, current_week=?, current_month=?, current_year=?, current_tick_type=?, tick_counter=tick_counter+1, updated_at=CURRENT_TIMESTAMP WHERE clock_id=1",
            (dt.strftime("%Y-%m-%d"), day, week, dt.month, dt.year, tick_type),
        )
        conn.commit()

def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        run_tick(conn, "day", 1)
    print("Tick advanced.")

if __name__ == "__main__":
    main()
