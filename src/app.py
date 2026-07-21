import sqlite3
import random
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

def fighter_name(conn, fighter_id):
    row = conn.execute("SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?", (fighter_id,)).fetchone()
    return row[0] if row else "Unknown"

def get_clock(conn):
    return conn.execute("SELECT current_date, current_day, current_week, current_month, current_year, tick_counter FROM simulation_clock WHERE clock_id=1").fetchone()

def advance_day(conn):
    row = get_clock(conn)
    dt = datetime.strptime(row[0], "%Y-%m-%d") + timedelta(days=1)
    day = row[1] + 1
    week = ((day - 1) // 7) + 1
    conn.execute(
        "UPDATE simulation_clock SET current_date=?, current_day=?, current_week=?, current_month=?, current_year=?, current_tick_type='day', tick_counter=tick_counter+1, updated_at=CURRENT_TIMESTAMP WHERE clock_id=1",
        (dt.strftime("%Y-%m-%d"), day, week, dt.month, dt.year),
    )

def write_news(conn, headline, body, topic="event", event_id=None, fight_id=None, fighter_id=None, promotion_id=None):
    src = conn.execute("SELECT news_source_id FROM news_sources WHERE name='System Feed'").fetchone()
    src_id = src[0] if src else conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80)).lastrowid
    conn.execute("INSERT INTO news_items (news_source_id, headline, body, sentiment, topic, event_id, fight_id, fighter_id, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (src_id, headline, body, "neutral", topic, event_id, fight_id, fighter_id, promotion_id))

def write_commentary(conn, event_id=None, fight_id=None, text=""):
    speaker = conn.execute("SELECT staff_id FROM staff WHERE role_type='commentator' LIMIT 1").fetchone()
    speaker_id = speaker[0] if speaker else None
    conn.execute("INSERT INTO commentary_segments (event_id, fight_id, segment_type, speaker_staff_id, text, importance) VALUES (?, ?, ?, ?, ?, ?)", (event_id, fight_id, "play_by_play", speaker_id, text, 70))

def resolve_next_fight(conn):
    fight = conn.execute("SELECT f.fight_id, f.event_id, e.promotion_id FROM fights f JOIN events e ON e.event_id=f.event_id WHERE f.winner_fighter_id IS NULL ORDER BY f.fight_id LIMIT 1").fetchone()
    if not fight:
        return None
    fight_id, event_id, promo_id = fight
    parts = conn.execute("SELECT fighter_id FROM fight_participants WHERE fight_id=? ORDER BY corner", (fight_id,)).fetchall()
    if len(parts) < 2:
        return None
    a_id, b_id = parts[0][0], parts[1][0]
    winner_id, loser_id = (a_id, b_id) if random.randint(1, 100) > 50 else (b_id, a_id)
    result_type = random.choice(["unanimous_decision", "ko_tko", "submission"])
    conn.execute(
        "UPDATE fights SET winner_fighter_id=?, loser_fighter_id=?, result_type=?, finish_round=?, finish_time=?, performance_rating=?, fan_reaction_rating=?, updated_at=CURRENT_TIMESTAMP WHERE fight_id=?",
        (winner_id, loser_id, result_type, random.randint(1, 3), "5:00", random.randint(60, 95), random.randint(60, 95), fight_id),
    )
    conn.execute("UPDATE fight_participants SET is_winner=CASE WHEN fighter_id=? THEN 1 ELSE 0 END WHERE fight_id=?", (winner_id, fight_id))
    conn.execute("UPDATE fighter_career SET record_wins=record_wins+1, win_streak=win_streak+1, loss_streak=0, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?", (winner_id,))
    conn.execute("UPDATE fighter_career SET record_losses=record_losses+1, loss_streak=loss_streak+1, win_streak=0, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?", (loser_id,))
    wn = fighter_name(conn, winner_id)
    ln = fighter_name(conn, loser_id)
    write_news(conn, f"{wn} defeats {ln}", f"{wn} beat {ln} by {result_type.replace('_', ' ')}.", "fight", event_id, fight_id, winner_id, promo_id)
    write_commentary(conn, event_id, fight_id, f"{wn} has just defeated {ln}.")
    return fight_id

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MMA Booking Sim")
        self.geometry("1280x760")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.build_ui()
        self.refresh_all()

    def build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill='x')
        ttk.Button(top, text="Advance Day", command=self.on_advance_day).pack(side='left', padx=4)
        ttk.Button(top, text="Resolve Fight", command=self.on_resolve_fight).pack(side='left', padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side='left', padx=4)
        self.clock_var = tk.StringVar()
        ttk.Label(top, textvariable=self.clock_var, font=("Segoe UI", 11, "bold")).pack(side='right')

        main = ttk.Panedwindow(self, orient='horizontal')
        main.pack(fill='both', expand=True, padx=8, pady=8)

        left = ttk.Frame(main, padding=6)
        center = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=2)
        main.add(center, weight=2)
        main.add(right, weight=2)

        ttk.Label(left, text="Fighters", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fighters = ttk.Treeview(left, columns=('name','wc','promo','record'), show='headings', height=16)
        for c,w in [('name',170),('wc',110),('promo',140),('record',100)]:
            self.fighters.heading(c, text=c.title())
            self.fighters.column(c, width=w, anchor='w')
        self.fighters.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(center, text="Events", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.events = ttk.Treeview(center, columns=('date','name','status'), show='headings', height=8)
        for c,w in [('date',110),('name',250),('status',120)]:
            self.events.heading(c, text=c.title())
            self.events.column(c, width=w, anchor='w')
        self.events.pack(fill='x', pady=(6,10))

        ttk.Label(center, text="Fights", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fights = ttk.Treeview(center, columns=('id','matchup','wc','result'), show='headings', height=10)
        for c,w in [('id',60),('matchup',260),('wc',110),('result',120)]:
            self.fights.heading(c, text=c.title())
            self.fights.column(c, width=w, anchor='w')
        self.fights.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(right, text="News", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.news = tk.Listbox(right, height=18)
        self.news.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(right, text="Commentary", font=("Segoe UI", 11, "bold")).pack(anchor='w', pady=(10,0))
        self.commentary = tk.Listbox(right, height=8)
        self.commentary.pack(fill='both', expand=True, pady=(6,0))

    def clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def refresh_all(self):
        row = get_clock(self.conn)
        self.clock_var.set(f"{row[0]} | Day {row[1]} | Week {row[2]} | Month {row[3]} | Year {row[4]} | Ticks {row[5]}")
        self.clear_tree(self.fighters)
        self.clear_tree(self.events)
        self.clear_tree(self.fights)
        self.news.delete(0, tk.END)
        self.commentary.delete(0, tk.END)

        for r in self.conn.execute("""
            SELECT f.first_name || ' ' || f.last_name, COALESCE(w.name,'Unknown'), COALESCE(p.name,'Unassigned'),
                   COALESCE(fc.record_wins,0) || '-' || COALESCE(fc.record_losses,0) || '-' || COALESCE(fc.record_draws,0)
            FROM fighters f
            LEFT JOIN weight_classes w ON w.weight_class_id=f.weight_class_id
            LEFT JOIN promotions p ON p.promotion_id=f.current_promotion_id
            LEFT JOIN fighter_career fc ON fc.fighter_id=f.fighter_id
            ORDER BY f.fighter_id
        """):
            self.fighters.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT event_date, event_name, status FROM events ORDER BY event_date"):
            self.events.insert('', 'end', values=r)

        for r in self.conn.execute("""
            SELECT f.fight_id,
                   COALESCE(a.first_name || ' ' || a.last_name, 'TBD') || ' vs ' || COALESCE(b.first_name || ' ' || b.last_name, 'TBD'),
                   COALESCE(w.name, 'Unknown'),
                   COALESCE(f.result_type, 'pending')
            FROM fights f
            LEFT JOIN fight_participants pa ON pa.fight_id=f.fight_id AND pa.corner='red'
            LEFT JOIN fight_participants pb ON pb.fight_id=f.fight_id AND pb.corner='blue'
            LEFT JOIN fighters a ON a.fighter_id=pa.fighter_id
            LEFT JOIN fighters b ON b.fighter_id=pb.fighter_id
            LEFT JOIN weight_classes w ON w.weight_class_id=f.weight_class_id
            ORDER BY f.fight_id
        """):
            self.fights.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT headline FROM news_items ORDER BY news_item_id DESC LIMIT 10"):
            self.news.insert(tk.END, r[0])
        for r in self.conn.execute("SELECT text FROM commentary_segments ORDER BY commentary_segment_id DESC LIMIT 10"):
            self.commentary.insert(tk.END, r[0])

    def on_advance_day(self):
        try:
            advance_day(self.conn)
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

    def on_resolve_fight(self):
        try:
            if resolve_next_fight(self.conn) is None:
                messagebox.showinfo("Resolve Fight", "No unresolved fights found.")
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    App().mainloop()