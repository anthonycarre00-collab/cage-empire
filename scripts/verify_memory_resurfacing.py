#!/usr/bin/env python3
"""Verify memory resurfacing fires for fighters with previous-fight history (FIX-V3-ALL5 #5).

This is a SHORT, FOCUSED verification script. It does NOT modify the
memory resurfacing code (the brief explicitly forbids that). It only:

  1. Finds two fighters A, B who have fought each other before
     (a fight_history row exists with fighter_id=A, opponent_id=B).
  2. Calls `news.generate_fight_preview_memory_news(conn, fight_id=999,
     fighter_a_id=A, fighter_b_id=B)` on the LIVE world DB.
  3. Checks whether a `topic='memory_resurfacing'` news item was
     written for fight_id=999.
  4. If yes — system works. If no — traces WHY by calling
     `surface_memories(A, B)` directly and reporting the result.

Because the function reads the simulation_clock for published_at, the
news item is dated at the current sim_date — invariant #4 (no
future-dated news) is preserved.

The script writes ONE news item to the live DB (then reports its
news_item_id). The caller can delete it via:
    DELETE FROM news_items WHERE fight_id=999;
if they want a clean state.

Usage:
    python3 scripts/verify_memory_resurfacing.py
    python3 scripts/verify_memory_resurfacing.py --db PATH
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


def main():
    parser = argparse.ArgumentParser(
        description="Verify memory resurfacing fires for known rival pairs.",
    )
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="path to the world DB (default: live DB)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: DB not found at {db_path}", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    # ----- Step 1: find a fighter pair with previous-fight history -----
    # Pick a pair that has fought at least once (any outcome).
    pair_row = conn.execute(
        """
        SELECT fighter_id, opponent_id, outcome, result_type, event_date
        FROM fight_history
        WHERE fighter_id IS NOT NULL
          AND opponent_id IS NOT NULL
          AND fighter_id != opponent_id
          AND fighter_id > 0
          AND opponent_id > 0
          AND EXISTS (SELECT 1 FROM fighters WHERE fighter_id = fighter_id)
          AND EXISTS (SELECT 1 FROM fighters WHERE fighter_id = opponent_id)
        ORDER BY event_date DESC
        LIMIT 1
        """,
    ).fetchone()
    if not pair_row:
        print("FAIL: could not find a fighter pair with previous-fight "
              "history in fight_history.")
        print("       This itself is a data issue — the reseeded DB should "
              "have ~80K fight_history rows.")
        conn.close()
        sys.exit(1)

    fighter_a_id, fighter_b_id, outcome, result_type, event_date = pair_row
    name_a = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?",
        (fighter_a_id,),
    ).fetchone()
    name_b = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?",
        (fighter_b_id,),
    ).fetchone()
    name_a = name_a[0] if name_a else f"#{fighter_a_id}"
    name_b = name_b[0] if name_b else f"#{fighter_b_id}"

    print(f"Step 1: Found previous-fight pair:")
    print(f"  fighter_a_id={fighter_a_id} ({name_a})")
    print(f"  fighter_b_id={fighter_b_id} ({name_b})")
    print(f"  prior outcome: {outcome} via {result_type} on {event_date}")
    print()

    # ----- Step 2: call generate_fight_preview_memory_news -----
    # Clean any stale row with fight_id=999 first so the test is clean.
    conn.execute("DELETE FROM news_items WHERE fight_id=999;")
    conn.commit()

    import news
    print("Step 2: Calling news.generate_fight_preview_memory_news("
          f"fight_id=999, fighter_a_id={fighter_a_id}, fighter_b_id={fighter_b_id})")
    news_id = news.generate_fight_preview_memory_news(
        conn, fight_id=999, fighter_a_id=fighter_a_id,
        fighter_b_id=fighter_b_id,
    )
    conn.commit()
    print(f"  -> returned news_item_id: {news_id}")
    print()

    # ----- Step 3: check if a memory_resurfacing news item was written -----
    written_row = conn.execute(
        """
        SELECT news_item_id, headline, body, topic, importance, published_at
        FROM news_items
        WHERE fight_id=999 AND topic='memory_resurfacing'
        """,
    ).fetchone()

    if written_row:
        print("Step 3: SUCCESS — memory_resurfacing news item written.")
        nid, headline, body, topic, importance, pub_at = written_row
        print(f"  news_item_id: {nid}")
        print(f"  headline:     {headline}")
        print(f"  body:         {body}")
        print(f"  topic:        {topic}")
        print(f"  importance:   {importance}")
        print(f"  published_at: {pub_at}")
        conn.close()
        sys.exit(0)

    # ----- Step 4: trace WHY surface_memories returned empty -----
    print("Step 3: news.generate_fight_preview_memory_news did NOT write "
          "a memory_resurfacing news item.")
    print()
    print("Step 4: Tracing why — calling surface_memories directly.")
    try:
        from interpretation.memory_engine import surface_memories
    except ImportError as e:
        print(f"  FAIL: could not import surface_memories: {e}")
        conn.close()
        sys.exit(1)

    try:
        memories = surface_memories(conn, fighter_a_id, fighter_b_id)
    except Exception as e:
        print(f"  FAIL: surface_memories raised: {type(e).__name__}: {e}")
        conn.close()
        sys.exit(1)

    print(f"  surface_memories returned {len(memories) if memories else 0} "
          f"memories.")
    if memories:
        for i, (m_type, m_phrase) in enumerate(memories):
            print(f"    [{i}] type={m_type} phrase={m_phrase!r}")
        print()
        print("  => surface_memories DID return results, but "
              "generate_fight_preview_memory_news did not write a news item.")
        print("     Likely causes (without inspecting the code further):")
        print("     - The news item was suppressed by the daily importance "
              "cap (HW4.3).")
        print("     - The news item was downgraded to BACKGROUND and then "
              "suppressed by the BACKGROUND cap.")
        print("     Check the news_items table for any row with fight_id=999 "
              "(any topic).")
        any_row = conn.execute(
            "SELECT news_item_id, topic, importance, published_at "
            "FROM news_items WHERE fight_id=999",
        ).fetchall()
        if any_row:
            print(f"  Found {len(any_row)} news_items with fight_id=999:")
            for r in any_row:
                print(f"    id={r[0]} topic={r[1]} importance={r[2]} "
                      f"published_at={r[3]}")
        else:
            print("  NO news_items with fight_id=999 found — the call was "
                  "suppressed before INSERT.")
    else:
        print()
        print("  => surface_memories returned an empty list. Tracing "
              "individual searches...")
        # Try each search type separately.
        from interpretation.memory_engine import (
            _search_previous_fight,
        )
        try:
            # Get current_date from sim clock.
            sim_row = conn.execute(
                "SELECT current_date FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            current_date = sim_row[0] if sim_row else None
            print(f"  current_date (from simulation_clock): {current_date}")
            if current_date is None:
                print("  WARN: simulation_clock has no current_date — "
                      "memory_engine may bail.")
            print()
            print(f"  _search_previous_fight(a={fighter_a_id}, b={fighter_b_id}):")
            phrase = _search_previous_fight(
                conn, fighter_a_id, fighter_b_id, current_date,
            )
            print(f"    -> {phrase!r}")
            if phrase is None:
                # Check the raw fight_history query.
                direct = conn.execute(
                    "SELECT COUNT(*) FROM fight_history "
                    "WHERE fighter_id=? AND opponent_id=?",
                    (fighter_a_id, fighter_b_id),
                ).fetchone()[0]
                print(f"  Direct fight_history count "
                      f"(fighter_id={fighter_a_id}, opponent_id={fighter_b_id}): "
                      f"{direct}")
                if direct > 0:
                    sample = conn.execute(
                        "SELECT outcome, result_type, event_date "
                        "FROM fight_history "
                        "WHERE fighter_id=? AND opponent_id=? "
                        "ORDER BY event_date DESC LIMIT 1",
                        (fighter_a_id, fighter_b_id),
                    ).fetchone()
                    print(f"  Sample row: outcome={sample[0]} "
                          f"result_type={sample[1]} event_date={sample[2]}")
                    print("  => fight_history has data but "
                          "_search_previous_fight returned None — "
                          "investigate the function logic.")
                else:
                    print("  => fight_history has NO row for this pair "
                          "(data issue).")
        except Exception as e:
            print(f"  FAIL tracing _search_previous_fight: "
                  f"{type(e).__name__}: {e}")

    conn.close()
    sys.exit(1)


if __name__ == "__main__":
    main()
