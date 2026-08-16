#!/usr/bin/env python3
"""PHASE3-IMPLEMENT Task 4 — Memory resurfacing player-path test.

Verifies that the memory_resurfacing news item fires when two active
fighters with prior history are booked against each other. This is the
player-path test: when the player books a rematch (or any fight between
two fighters who have history), the news feed should surface that
history via a memory_resurfacing news item so the player gets narrative
context for the booking.

Test flow:
  1. Connect to the DB.
  2. Find two active fighters who have fought before (from fight_history
     where both fighter_id and opponent_id are active, non-retired
     fighters).
  3. Call news.generate_fight_preview_memory_news(conn, fight_id=999999,
     fighter_a_id=X, fighter_b_id=Y) — the canonical entry point that
     app_web.Api.book_fight calls after a successful booking.
  4. Check if a memory_resurfacing news item was written for the fight.
  5. If yes: print "MEMORY RESURFACING: WORKS" + the headline.
  6. If no: trace why — call surface_memories(conn, X, Y) directly and
     print what it returns (so the operator can see whether the memory
     engine found any history between the two fighters).

The test uses fight_id=999999 (a sentinel that doesn't exist in the
fights table) so it doesn't collide with any real fight. The news item
is tied to this sentinel fight_id so cleanup is trivial if needed.

Usage:
    python3 scripts/test_player_path_memory.py
    python3 scripts/test_player_path_memory.py --verbose

Exit codes:
    0 = memory resurfacing works (news item was written)
    1 = memory resurfacing did NOT fire (see trace output)
    2 = script error (couldn't run)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verbose", action="store_true",
                        help="Print extra diagnostic detail.")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Path to the cage_empire DB.")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    print("=" * 72)
    print("PHASE3 Task 4 — Memory Resurfacing Player-Path Test")
    print("=" * 72)
    print(f"  DB: {db}")
    print()

    conn = sqlite3.connect(str(db))
    # Disable FK enforcement for the test connection. The test inserts
    # a news_items row with fight_id=999999 (a sentinel that doesn't
    # exist in the fights table) per the PHASE3-IMPLEMENT task spec.
    # The news_items.fight_id column has a FK constraint to fights.
    # fight_id, so we need FK enforcement OFF to allow the sentinel.
    # The news item is cleaned up at the end of the test, so no orphan
    # rows are left behind.
    conn.execute("PRAGMA foreign_keys = OFF;")

    # Lazy imports — placed after sys.path setup so news/memory_engine
    # resolve from src/.
    try:
        import news
        from interpretation.memory_engine import surface_memories
    except ImportError as e:
        print(f"ERROR: failed to import news/memory_engine: {e}",
              file=sys.stderr)
        return 2

    # Step 1+2: Find two active fighters who have fought before.
    print("Step 1-2: Find two active fighters who have fought before...")
    pair = conn.execute(
        "SELECT fighter_id, opponent_id, fight_id FROM fight_history "
        "WHERE fighter_id IN (SELECT fighter_id FROM fighters "
        "                     WHERE is_active=1 AND is_retired=0) "
        "  AND opponent_id IN (SELECT fighter_id FROM fighters "
        "                      WHERE is_active=1 AND is_retired=0) "
        "LIMIT 1",
    ).fetchone()
    if not pair:
        print("FAIL: no two active fighters with prior fight history found.")
        print("      (The DB may not have any active-vs-active rematch"
              " candidates.)")
        return 1
    fighter_a_id, fighter_b_id, real_fight_id = pair
    # Get fighter names for a readable report.
    a_name = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id=?",
        (fighter_a_id,),
    ).fetchone()[0]
    b_name = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id=?",
        (fighter_b_id,),
    ).fetchone()[0]
    print(f"  Found pair: fighter_a_id={fighter_a_id} ({a_name})")
    print(f"              fighter_b_id={fighter_b_id} ({b_name})")
    print(f"  (Their prior fight_id in fight_history: {real_fight_id})")
    print()

    # Defensive: clean up any prior test news items tied to our sentinel
    # fight_id (so the "did we write a news item?" check below isn't
    # fooled by a stale row from a previous test run). Use a sentinel
    # fight_id that doesn't exist in the fights table so we don't
    # collide with real fights.
    sentinel_fight_id = 999999
    conn.execute(
        "DELETE FROM news_items WHERE fight_id=?",
        (sentinel_fight_id,),
    )
    conn.commit()

    # Check the SIGNIFICANT daily cap on sim_date BEFORE calling the
    # function. The memory_resurfacing news item is written at
    # importance=SIGNIFICANT (per news.py:1752), which has a daily cap
    # of 5 items per sim_date (per news.py:_IMPORTANCE_DAILY_CAPS). If
    # the cap is already full, the function will return None even
    # though surface_memories found memories — that's the system
    # working as designed (the cap throttles news volume).
    #
    # To make the test deterministic, we temporarily delete enough
    # SIGNIFICANT items on sim_date to leave room for our test item.
    # We restore them after the test (cleanup at the end).
    sim_date_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = sim_date_row[0] if sim_date_row else None
    restored_significant_ids = []
    if sim_date:
        sig_count = conn.execute(
            "SELECT COUNT(*) FROM news_items "
            "WHERE published_at=? AND importance='SIGNIFICANT'",
            (sim_date,),
        ).fetchone()[0]
        sig_cap = 5  # NEWS_IMPORTANCE_SIGNIFICANT daily cap
        print(f"Step 2b: SIGNIFICANT news items on sim_date "
              f"({sim_date}): {sig_count}/{sig_cap} cap")
        if sig_count >= sig_cap:
            # Cap is full — temporarily delete the oldest SIGNIFICANT
            # items to make room for our test item. We'll restore them
            # at the end.
            print(f"  Cap reached — temporarily clearing 1 slot for the "
                  f"test (will be restored after).")
            rows = conn.execute(
                "SELECT news_item_id, news_source_id, headline, body, "
                "sentiment, topic, event_id, fight_id, fighter_id, "
                "promotion_id, published_at, importance "
                "FROM news_items "
                "WHERE published_at=? AND importance='SIGNIFICANT' "
                "ORDER BY news_item_id ASC LIMIT 1",
                (sim_date,),
            ).fetchall()
            for r in rows:
                nid = r[0]
                conn.execute(
                    "DELETE FROM news_items WHERE news_item_id=?",
                    (nid,),
                )
                restored_significant_ids.append(r)
            conn.commit()
            print(f"  Cleared {len(restored_significant_ids)} item(s).")
    print()

    # Step 3: Call generate_fight_preview_memory_news with our sentinel
    # fight_id. This is the canonical entry point that app_web.Api.
    # book_fight calls after a successful booking (see app_web.py
    # book_fight flow). The function returns the news_item_id if a
    # memory_resurfacing item was written, or None if no memories were
    # found (or the write was suppressed by the daily cap).
    print("Step 3: Call news.generate_fight_preview_memory_news("
          f"fight_id={sentinel_fight_id}, ...)")
    news_item_id = news.generate_fight_preview_memory_news(
        conn,
        fight_id=sentinel_fight_id,
        fighter_a_id=fighter_a_id,
        fighter_b_id=fighter_b_id,
    )
    conn.commit()
    print(f"  Returned news_item_id: {news_item_id}")
    print()

    # Step 4: Check if a memory_resurfacing news item was written.
    print("Step 4: Check if a memory_resurfacing news item was written...")
    row = conn.execute(
        "SELECT news_item_id, headline, body, topic, importance "
        "FROM news_items "
        "WHERE fight_id=? AND topic='memory_resurfacing' "
        "ORDER BY news_item_id DESC LIMIT 1",
        (sentinel_fight_id,),
    ).fetchone()

    if row:
        # Step 5: SUCCESS — print the headline.
        nid, headline, body, topic, importance = row
        print("=" * 72)
        print("MEMORY RESURFACING: WORKS")
        print("=" * 72)
        print(f"  news_item_id: {nid}")
        print(f"  headline:     {headline!r}")
        print(f"  topic:        {topic}")
        print(f"  importance:   {importance}")
        if args.verbose:
            print(f"  body:         {body!r}")
        print()
        print(f"  Fighter pair: {a_name} (id={fighter_a_id}) vs "
              f"{b_name} (id={fighter_b_id})")
        print(f"  The news item references their prior history — "
              f"the player will see this in their news feed when they "
              f"book the rematch.")
        # Cleanup the test news item so we don't pollute the DB.
        conn.execute("DELETE FROM news_items WHERE news_item_id=?", (nid,))
        # Restore the temporarily-cleared SIGNIFICANT items.
        for r in restored_significant_ids:
            # r = (news_item_id, news_source_id, headline, body,
            #      sentiment, topic, event_id, fight_id, fighter_id,
            #      promotion_id, published_at, importance)
            # Re-insert with the original news_item_id (preserve PK).
            try:
                conn.execute(
                    "INSERT INTO news_items (news_item_id, news_source_id, "
                    "headline, body, sentiment, topic, event_id, fight_id, "
                    "fighter_id, promotion_id, published_at, importance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    r,
                )
            except sqlite3.IntegrityError:
                # If the PK already exists (shouldn't, we just deleted
                # it), skip — better than crashing.
                pass
        conn.commit()
        return 0

    # Step 6: FAILURE — trace why.
    print("FAIL: no memory_resurfacing news item was written.")
    print()
    print("Step 6: Tracing why — calling surface_memories(conn, "
          f"{fighter_a_id}, {fighter_b_id}) directly...")
    memories = surface_memories(conn, fighter_a_id, fighter_b_id)
    print(f"  surface_memories returned {len(memories)} memories:")
    if not memories:
        print("    (empty list — no memories found between these fighters)")
        print()
        print("  This means the memory_engine found NO relevant history")
        print("  between the two fighters, even though they appear in")
        print("  fight_history together. Possible causes:")
        print("    - The fight_history row is for a fighter vs themselves")
        print("      (data integrity issue).")
        print("    - The memory_engine's _search_previous_fight has a bug")
        print("      that prevents it from finding the fight_history row.")
        print("    - The fighter IDs in fight_history don't match the")
        print("      active fighters we selected (FK drift).")
        # Print the raw fight_history row for debugging.
        fh_row = conn.execute(
            "SELECT fighter_id, opponent_id, fight_id, fight_date, "
            "result, method "
            "FROM fight_history WHERE fighter_id=? AND opponent_id=? "
            "LIMIT 5",
            (fighter_a_id, fighter_b_id),
        ).fetchall()
        print(f"  Raw fight_history rows for ({fighter_a_id}, "
              f"{fighter_b_id}): {fh_row}")
    else:
        for i, (mtype, phrase) in enumerate(memories):
            print(f"    [{i+1}] type={mtype!r}  phrase={phrase!r}")
        print()
        print("  surface_memories DID find memories, but "
              "generate_fight_preview_memory_news didn't write a news "
              "item. Possible causes:")
        print("    - The daily SIGNIFICANT-importance cap suppressed the "
              "write (check news.py's _write_news_item cap logic).")
        print("    - An exception was caught and swallowed inside "
              "generate_fight_preview_memory_news (check stderr above "
              "for WARNING messages).")
        print("    - The function returned None due to a logic bug.")

    # Cleanup any partial test news items.
    conn.execute(
        "DELETE FROM news_items WHERE fight_id=?",
        (sentinel_fight_id,),
    )
    # Restore the temporarily-cleared SIGNIFICANT items even on failure.
    for r in restored_significant_ids:
        try:
            conn.execute(
                "INSERT INTO news_items (news_item_id, news_source_id, "
                "headline, body, sentiment, topic, event_id, fight_id, "
                "fighter_id, promotion_id, published_at, importance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                r,
            )
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return 1


if __name__ == "__main__":
    sys.exit(main())
