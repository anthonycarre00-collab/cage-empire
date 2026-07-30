"""Performance profile: time each screen's refresh + key DB queries.

Usage:
    cd /home/z/my-project/cage_empire
    python -m scripts.perf.profile_screens

This script:
  1. Opens the world DB read-only.
  2. Times each hot DB query (roster, free_agents, dashboard sections,
     fighter profile query).
  3. Reports EXPLAIN QUERY PLAN for each so we can see what's missing
     an index.
  4. Counts table sizes for context.

No write access required — opens with uri=true&mode=ro so the world
DB is never at risk.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

# Resolve project root so we can import src/ modules.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"


def _open_ro() -> sqlite3.Connection:
    """Open the world DB read-only (no write risk)."""
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _time(label: str, fn, iters: int = 3) -> float:
    """Run fn() iters times, return median ms."""
    times = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    times.sort()
    median = times[len(times) // 2]
    print(f"  {label:60s}  {median:7.1f} ms")
    return median


def _explain(conn, label: str, sql: str, params=()):
    """Print EXPLAIN QUERY PLAN for a query."""
    print(f"\n  EXPLAIN — {label}")
    try:
        for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall():
            print(f"    {row[3]}")
    except sqlite3.Error as e:
        print(f"    (error: {e})")


def _table_counts(conn):
    """Print row counts for the hot tables."""
    print("\n=== Table sizes ===")
    tables = [
        "fighters", "fighter_descriptors", "fighter_career",
        "fighter_bios", "fighter_attributes", "fighter_personality",
        "fight_history", "fight_beats", "news_items", "daily_headlines",
        "titles", "rankings", "scouting_reports", "rivalries",
        "training_camps", "injuries", "suspensions",
    ]
    for t in tables:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:30s}  {n:>8,}")
        except sqlite3.Error:
            print(f"  {t:30s}  (missing)")


def profile_roster(conn):
    """Time the roster query — same SQL the RosterScreen runs."""
    print("\n=== Roster query (4450+ fighters, filtered by promotion) ===")
    promo_id = 1  # Alpha Combat Federation (largest promotion)
    sql = """
        SELECT f.fighter_id, f.first_name, f.last_name, f.nickname,
               f.date_of_birth,
               wc.name AS weight_class_name,
               n.name AS nation_name,
               g.name AS gym_name,
               fd.career_phase, fd.momentum, fd.narrative_family,
               fc.record_wins, fc.record_losses, fc.record_draws
        FROM fighters f
        LEFT JOIN weight_classes wc
          ON wc.weight_class_id = f.weight_class_id
        LEFT JOIN nations n
          ON n.nation_id = f.birth_nation_id
        LEFT JOIN gyms g
          ON g.gym_id = f.current_gym_id
        LEFT JOIN fighter_descriptors fd
          ON fd.fighter_id = f.fighter_id
        LEFT JOIN fighter_career fc
          ON fc.fighter_id = f.fighter_id
        WHERE f.current_promotion_id = ?
          AND f.is_active = 1
        ORDER BY f.fighter_id ASC
    """
    _time("roster query (promo=1)",
          lambda: conn.execute(sql, (promo_id,)).fetchall())
    _explain(conn, "roster query", sql, (promo_id,))

    # With gender filter
    sql_m = sql.replace(
        "AND f.is_active = 1",
        "AND f.is_active = 1 AND f.gender = 'M'",
    )
    _time("roster query (promo=1, male)",
          lambda: conn.execute(sql_m, (promo_id,)).fetchall())

    # With search term
    sql_s = sql.replace(
        "ORDER BY",
        "AND (f.first_name LIKE ? OR f.last_name LIKE ?) "
        "ORDER BY",
    )
    _time("roster query (promo=1, search 'a')",
          lambda: conn.execute(
              sql_s, (promo_id, "%a%", "%a%")).fetchall())


def profile_free_agents(conn):
    """Time the free-agents query."""
    print("\n=== Free Agents query (fighters with no promotion) ===")
    sql = """
        SELECT f.fighter_id, f.first_name, f.last_name, f.nickname,
               f.date_of_birth, f.weight_class_id,
               wc.name AS wc_name,
               fd.career_phase, fd.momentum, fd.narrative_family,
               fd.potential_desc,
               fc.record_wins, fc.record_losses, fc.record_draws
        FROM fighters f
        LEFT JOIN weight_classes wc
          ON wc.weight_class_id = f.weight_class_id
        LEFT JOIN fighter_descriptors fd
          ON fd.fighter_id = f.fighter_id
        LEFT JOIN fighter_career fc
          ON fc.fighter_id = f.fighter_id
        WHERE f.current_promotion_id IS NULL
          AND f.is_active = 1
        ORDER BY f.fighter_id ASC
    """
    _time("free agents query",
          lambda: conn.execute(sql).fetchall())
    _explain(conn, "free agents query", sql)


def profile_dashboard(conn):
    """Time the dashboard's hot queries."""
    print("\n=== Dashboard queries ===")
    # daily_headlines (latest per type)
    _time("daily_headlines (all)",
          lambda: conn.execute(
              "SELECT headline_type, fighter_id, headline_date "
              "FROM daily_headlines "
              "ORDER BY headline_date DESC, headline_type ASC"
          ).fetchall())
    _explain(conn, "daily_headlines",
             "SELECT headline_type, fighter_id, headline_date "
             "FROM daily_headlines "
             "ORDER BY headline_date DESC, headline_type ASC")

    # Hottest streak fighter
    sql_streak = """
        SELECT fd.fighter_id
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        WHERE f.is_active = 1 AND f.is_retired = 0
          AND SUBSTR(fd.momentum, 1,
                     INSTR(fd.momentum || '||', '||') - 1) = ?
        ORDER BY fd.fighter_id ASC
    """
    _time("hottest streak (very_high)",
          lambda: conn.execute(sql_streak, ("very_high",)).fetchall())
    _explain(conn, "hottest streak", sql_streak, ("very_high",))

    # News items (latest 20)
    _time("news_items (latest 20)",
          lambda: conn.execute(
              "SELECT headline, topic, published_at, fighter_id "
              "FROM news_items ORDER BY published_at DESC LIMIT 20"
          ).fetchall())
    _explain(conn, "news_items",
             "SELECT headline, topic, published_at, fighter_id "
             "FROM news_items ORDER BY published_at DESC LIMIT 20")

    # Champions (player promotion) — matches dashboard._refresh_champions SQL
    sql_champs = """
        SELECT wc.name, f.fighter_id, f.first_name, f.last_name
        FROM titles t
        JOIN weight_classes wc ON wc.weight_class_id = t.weight_class_id
        LEFT JOIN fighters f ON f.fighter_id = t.current_champion_fighter_id
        WHERE t.promotion_id=? AND t.is_vacant=0
          AND t.current_champion_fighter_id IS NOT NULL
        ORDER BY COALESCE(wc.display_order, wc.weight_class_id) ASC
    """
    _time("champions (promo=1)",
          lambda: conn.execute(sql_champs, (1,)).fetchall())
    _explain(conn, "champions", sql_champs, (1,))


def profile_fighter_profile(conn):
    """Time the fighter profile full JOIN query."""
    print("\n=== Fighter Profile query ===")
    sql = """
        SELECT f.fighter_id, f.first_name, f.last_name, f.nickname,
               f.weight_class_id, wc.name AS wc_name, wc.gender,
               f.current_gym_id, g.name AS gym_name,
               f.current_promotion_id, p.name AS promo_name,
               f.date_of_birth,
               fd.career_phase, fd.momentum, fd.pressure,
               fd.narrative_family, fd.legacy_state,
               fd.attribute_descriptors, fd.personality_descriptors,
               fd.overall_desc,
               fc.record_wins, fc.record_losses, fc.record_draws,
               fc.win_streak, fc.loss_streak, fc.title_reigns,
               fb.bio_text
        FROM fighters f
        LEFT JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id
        LEFT JOIN gyms g ON g.gym_id = f.current_gym_id
        LEFT JOIN promotions p ON p.promotion_id = f.current_promotion_id
        LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id
        LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        LEFT JOIN fighter_bios fb ON fb.fighter_id = f.fighter_id
        WHERE f.fighter_id = ?
    """
    _time("fighter profile query (id=4)",
          lambda: conn.execute(sql, (4,)).fetchone())
    _explain(conn, "fighter profile query", sql, (4,))

    # Recent fights — matches fighter_profile._refresh_recent_fights SQL
    sql_fights = """
        SELECT fh.event_date, fh.outcome, fh.result_type,
               fh.finish_round, fh.title_at_stake,
               opp.first_name, opp.last_name, opp.nickname
        FROM fight_history fh
        JOIN fighters opp ON opp.fighter_id = fh.opponent_id
        WHERE fh.fighter_id = ?
        ORDER BY fh.event_date DESC
        LIMIT 5
    """
    _time("recent fights (id=4)",
          lambda: conn.execute(sql_fights, (4,)).fetchall())
    _explain(conn, "recent fights", sql_fights, (4,))


def profile_advance_day(conn):
    """Estimate how long advance_day might take by timing its pieces."""
    print("\n=== Advance Day components (read-only estimates) ===")
    # Active fighters count (drives tick cost)
    n = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_active = 1"
    ).fetchone()[0]
    print(f"  active fighters: {n:,}")
    # Fighter descriptors count
    n_fd = conn.execute("SELECT COUNT(*) FROM fighter_descriptors").fetchone()[0]
    print(f"  fighter_descriptors: {n_fd:,}")
    # Daily headlines count
    n_hl = conn.execute("SELECT COUNT(*) FROM daily_headlines").fetchone()[0]
    print(f"  daily_headlines: {n_hl:,}")
    # News items count
    n_news = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    print(f"  news_items: {n_news:,}")


def main():
    print(f"CAGE EMPIRE — Performance Profile")
    print(f"DB: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        return 1
    conn = _open_ro()

    _table_counts(conn)
    profile_roster(conn)
    profile_free_agents(conn)
    profile_dashboard(conn)
    profile_fighter_profile(conn)
    profile_advance_day(conn)

    print("\n=== Done ===")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
