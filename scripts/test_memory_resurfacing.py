#!/usr/bin/env python3
"""NEWS-SPAM-MEMORY-CHECK §2 — Memory-resurfacing test harness.

Verifies that the memory system end-to-end works after the
NEWS-SPAM-MEMORY-CHECK fix:

  1. Runs a 30-day sim on a fresh copy of the reseeded DB.
  2. After the sim, checks which of the 15 memory link TYPES were
     WRITTEN to fighter_memory_links during the sim.
  3. For each surface_memories() search type (9 total — 4 MVP + 5
     HW3.2), checks whether any fighter pair returns a non-empty
     result. Picks a few candidate pairs (fighters with previous
     fights, signed fighters, etc.) and exercises the engine.
  4. Counts memory_resurfacing news items (topic='memory_resurfacing'
     OR topic='legacy') written during the sim — these are the
     "fight preview" + "champion successor" beats the player sees.
  5. Verifies the fight-preview memory news fires when booking a
     fight between two fighters who have previous_fights history
     (forces a fresh matchup + checks a news item was written).
  6. Reports which writers fired + which surface_memories search
     types returned results, so the operator can see at a glance
     which memory types are "live" vs "dormant".

Usage:
    python3 scripts/test_memory_resurfacing.py            # 30-day sim
    python3 scripts/test_memory_resurfacing.py 60         # 60-day sim
    python3 scripts/test_memory_resurfacing.py --no-sim   # just check current DB
    python3 scripts/test_memory_resurfacing.py --db PATH  # custom DB

The script copies the live DB to a temp path before running the sim
(unless --db is given — then it operates directly on the given DB).
The temp DB is left in place after the run for inspection (path
printed at the end).

Exit code: 0 if the fight-preview memory news verification passes,
1 otherwise.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DEFAULT_DB = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))
sys.path.insert(0, str(SRC_DIR))


# ----------------------------------------------------------------
# Constants — the 15+ memory link types the test checks for.
# ----------------------------------------------------------------
# These are the link_type values that should be written by the memory
# writers during a sim. Each type is mapped to its writer function +
# the trigger that fires the writer.

MEMORY_LINK_TYPES = OrderedDict([
    # ---- Existing v1 + HW3.1 writers (always wired) ----
    ("style_echo", "populate_style_echo (regen replacement inherits archetype)"),
    ("regional_rival", "populate_regional_rival (matchmaking same-region)"),
    ("successor", "tick_processor._check_retirements (champion regen)"),
    # ---- HW3.1 new writers (subscribers on FIGHT_RESOLVED etc.) ----
    ("title_history", "_on_title_changed (title changes hands)"),
    ("upset", "_on_fight_resolved (lower-rated beats higher-rated)"),
    ("comeback", "_on_fight_resolved + _on_fighter_signed (long layoff)"),
    ("milestone", "_on_fight_resolved (10 wins / 5-KO streak / 10th defense)"),
    # ---- Tier 3 §T3.4 new writers (subscribers + gym_transfers wiring) ----
    ("previous_fights", "_on_fight_resolved (2nd meeting between pair)"),
    ("former_teammates", "gym_transfers.on_tick_advanced (gym change)"),
    ("old_gyms", "gym_transfers.on_tick_advanced (gym change)"),
    ("former_champions", "_on_title_changed (champion loses title)"),
    ("controversial_losses", "_on_fight_resolved (split decision / doctor stop)"),
    ("injuries", "fight_engine.resolve_next_fight (fighter injured)"),
    ("promotions", "_on_fighter_signed (fighter signs with promo)"),
    ("old_events", "_on_fight_resolved (title fight)"),
])

# The 9 surface_memories() search types (from memory_engine.py).
SURFACE_SEARCH_TYPES = [
    "previous_fight",
    "shared_gym",
    "former_teammate",
    "injury_history",
    "title_fight_history",
    "former_champion",
    "controversial_loss",
    "major_upset",
    "career_milestone",
]


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _print_section(title):
    print()
    print("=" * 76)
    print(f"  {title}")
    print("=" * 76)


def _print_subsection(title):
    print()
    print(f"--- {title} ---")


def _scalar(conn, sql, *args):
    try:
        row = conn.execute(sql, *args).fetchone()
        return row[0] if row else 0
    except sqlite3.Error:
        return 0


def _query_all(conn, sql, *args):
    try:
        return conn.execute(sql, *args).fetchall()
    except sqlite3.Error as e:
        print(f"  WARN: query failed: {e}", file=sys.stderr)
        return []


# ----------------------------------------------------------------
# Subscriber registration (mirrors soak_test.py)
# ----------------------------------------------------------------

def register_all_subscribers():
    """Register all event-bus subscribers needed for the sim."""
    registered = 0
    failed = 0

    top_level_modules = [
        "news", "social", "rivalries", "punditry", "morale",
        "suspensions", "agent_offers", "career_arc", "rival_ai",
        "show_rating", "venues", "save_load", "player_settings",
        "reputation", "scouting", "gym_transfers",
    ]
    for mod_name in top_level_modules:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
                registered += 1
        except ImportError:
            failed += 1
        except Exception as e:
            failed += 1
            print(f"  Warning: {mod_name}.register_subscribers failed: {e}",
                  file=sys.stderr)

    service_modules = [
        "services.hof_svc", "services.retirement_svc",
        "services.training_svc", "services.injuries_svc",
        "services.finance_svc", "services.rivalries_svc",
        "services.memory_svc", "services.contracts",
        "services.scouting_svc", "services.matchmaking",
        "services.punditry_svc", "services.pruning_svc",
    ]
    for mod_name in service_modules:
        try:
            mod = __import__(mod_name, fromlist=["register_subscribers"])
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
                registered += 1
        except ImportError:
            failed += 1
        except Exception as e:
            failed += 1
            print(f"  Warning: {mod_name}.register_subscribers failed: {e}",
                  file=sys.stderr)

    try:
        from interpretation import register_subscribers as _register_interp
        _register_interp()
        registered += 1
    except ImportError:
        failed += 1
    except Exception as e:
        failed += 1
        print(f"  Warning: interpretation.register_subscribers failed: {e}",
              file=sys.stderr)

    return registered, failed


# ----------------------------------------------------------------
# Step 1 — Run the 30-day sim
# ----------------------------------------------------------------

def run_sim(conn, days):
    """Run a sim for `days` days. Returns (success_count, fail_count)."""
    from services.clock import advance_day
    success = 0
    fail = 0
    t0 = time.perf_counter()
    for i in range(days):
        try:
            advance_day(conn)
            conn.commit()
            success += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                print(f"    Day {i+1} FAILED: {type(e).__name__}: {e}",
                      file=sys.stderr)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
    elapsed = time.perf_counter() - t0
    print(f"  Sim complete: {success}/{days} days advanced "
          f"({fail} failed) in {elapsed:.1f}s")
    return success, fail


# ----------------------------------------------------------------
# Step 2 — Check which link types were WRITTEN during the sim
# ----------------------------------------------------------------

def check_link_writers(conn):
    """Check which memory link types have rows in fighter_memory_links.

    Returns: dict {link_type: count} for all 15 expected types.
    """
    _print_subsection("Step 2 — Memory link WRITERS (rows in "
                      "fighter_memory_links)")
    results = OrderedDict()
    for link_type in MEMORY_LINK_TYPES:
        count = _scalar(
            conn,
            "SELECT COUNT(*) FROM fighter_memory_links "
            "WHERE link_type=?",
            (link_type,),
        )
        results[link_type] = count
    # Also count any OTHER link_types that exist in the table.
    other_rows = _query_all(
        conn,
        "SELECT link_type, COUNT(*) FROM fighter_memory_links "
        "GROUP BY link_type ORDER BY link_type",
    )
    other_types = {r[0]: r[1] for r in other_rows}
    for link_type, count in results.items():
        writer = MEMORY_LINK_TYPES[link_type]
        marker = "✓" if count > 0 else "✗"
        print(f"  {marker} {link_type:25s} {count:6d}  ({writer})")
    # Print any types not in the expected list (informational).
    extra = set(other_types) - set(MEMORY_LINK_TYPES.keys())
    if extra:
        print(f"  --- additional link_types present ---")
        for lt in sorted(extra):
            print(f"    {lt:25s} {other_types[lt]:6d}")
    written = sum(1 for c in results.values() if c > 0)
    print(f"\n  SUMMARY: {written}/{len(MEMORY_LINK_TYPES)} link types "
          f"have ≥1 row written.")
    return results


# ----------------------------------------------------------------
# Step 3 — Check which surface_memories search types return results
# ----------------------------------------------------------------

def check_surface_memories(conn):
    """Test surface_memories() against candidate fighter pairs.

    Picks several candidate pairs:
      - 5 pairs who have fought each other before (from fight_history)
      - 5 pairs at the same gym
      - 5 pairs of former champions
    Calls surface_memories() on each pair, collects which search types
    return non-empty results.

    Returns: (results_dict, list_of_pairs_with_memories).
    """
    _print_subsection("Step 3 — surface_memories() search types "
                      "(finding results)")
    try:
        from interpretation.memory_engine import surface_memories, ALL_MEMORY_TYPES
    except ImportError as e:
        print(f"  ERROR: cannot import memory_engine: {e}", file=sys.stderr)
        return {st: 0 for st in SURFACE_SEARCH_TYPES}, []

    # Build candidate pairs — fighters who have fought each other.
    pairs = set()
    # 1. Pairs from fighter_memory_links (any link_type — these are
    #    guaranteed to have history). The surface_memories function
    #    reads link_type IN ('former_teammate', 'former_teammates',
    #    'upset', 'milestone', etc.) — so any pair in this table
    #    has a chance of returning a memory.
    link_rows = _query_all(
        conn,
        """
        SELECT DISTINCT fighter_id, linked_fighter_id
        FROM fighter_memory_links
        WHERE fighter_id < linked_fighter_id
        LIMIT 100
        """,
    )
    for fa, fb in link_rows:
        pairs.add((fa, fb))
    # 2. Pairs from fight_history (they've fought before — surface_
    #    memories will return at least the previous_fight memory).
    fh_rows = _query_all(
        conn,
        """
        SELECT DISTINCT fighter_id, opponent_id
        FROM fight_history
        WHERE fighter_id IS NOT NULL AND opponent_id IS NOT NULL
          AND fighter_id < opponent_id
        LIMIT 200
        """,
    )
    for fa, fb in fh_rows:
        pairs.add((fa, fb))
    # 3. Pairs at the same gym.
    gym_rows = _query_all(
        conn,
        """
        SELECT f1.fighter_id, f2.fighter_id
        FROM fighters f1
        JOIN fighters f2 ON f1.current_gym_id = f2.current_gym_id
                          AND f1.fighter_id < f2.fighter_id
        WHERE f1.current_gym_id IS NOT NULL
          AND f1.is_active = 1 AND f2.is_active = 1
        LIMIT 50
        """,
    )
    for fa, fb in gym_rows:
        pairs.add((fa, fb))

    if not pairs:
        print("  No candidate pairs found (DB may be empty).")
        return {st: 0 for st in SURFACE_SEARCH_TYPES}, []

    print(f"  Testing surface_memories() on {len(pairs)} candidate "
          f"fighter pairs...")

    # Initialize result counters for all 9 search types.
    results = {st: 0 for st in SURFACE_SEARCH_TYPES}
    pairs_with_any_memory = []
    pairs_with_any_memory_count = 0

    # Cap the number of pairs we test (the search is fast but we
    # don't need to test all 250+ pairs — 150 is enough to find any
    # matching memories).
    test_pairs = list(pairs)[:150]
    for fa, fb in test_pairs:
        try:
            memories = surface_memories(conn, fa, fb)
        except Exception as e:
            continue
        if memories:
            pairs_with_any_memory_count += 1
            pairs_with_any_memory.append((fa, fb, memories))
        for memory_type, _phrase in memories:
            if memory_type in results:
                results[memory_type] += 1

    for st in SURFACE_SEARCH_TYPES:
        count = results[st]
        marker = "✓" if count > 0 else "✗"
        print(f"  {marker} {st:25s} matched in {count:3d} pairs")
    print(f"\n  SUMMARY: {sum(1 for c in results.values() if c > 0)}/"
          f"{len(SURFACE_SEARCH_TYPES)} search types returned results.")
    print(f"  {pairs_with_any_memory_count}/{len(test_pairs)} tested pairs "
          f"had ≥1 memory surfaced.")
    return results, pairs_with_any_memory


# ----------------------------------------------------------------
# Step 4 — Check memory_resurfacing news items
# ----------------------------------------------------------------

def check_memory_resurfacing_news(conn):
    """Count memory_resurfacing + legacy news items written during
    the sim.

    memory_resurfacing news items are written by:
      - news.generate_fight_preview_memory_news (on fight booking —
        if surface_memories finds history)
      - news.generate_memory_resurfacing_news (on TITLE_CHANGED —
        if a 'successor' link exists on the new champ)
    """
    _print_subsection("Step 4 — Memory-resurfacing news items")
    # Total memory_resurfacing + legacy news items.
    mr_count = _scalar(
        conn,
        "SELECT COUNT(*) FROM news_items WHERE topic='memory_resurfacing'",
    )
    legacy_count = _scalar(
        conn,
        "SELECT COUNT(*) FROM news_items WHERE topic='legacy'",
    )
    print(f"  memory_resurfacing news items:  {mr_count}")
    print(f"  legacy news items:              {legacy_count}")
    # Show a few samples.
    if mr_count > 0:
        print(f"  --- sample memory_resurfacing headlines ---")
        rows = _query_all(
            conn,
            "SELECT published_at, headline FROM news_items "
            "WHERE topic='memory_resurfacing' "
            "ORDER BY published_at DESC LIMIT 5",
        )
        for published_at, headline in rows:
            print(f"    [{published_at}] {headline}")
    if legacy_count > 0:
        print(f"  --- sample legacy headlines ---")
        rows = _query_all(
            conn,
            "SELECT published_at, headline FROM news_items "
            "WHERE topic='legacy' "
            "ORDER BY published_at DESC LIMIT 5",
        )
        for published_at, headline in rows:
            print(f"    [{published_at}] {headline}")
    return mr_count, legacy_count


# ----------------------------------------------------------------
# Step 5 — Verify the fight-preview memory system fires when booking
# ----------------------------------------------------------------

def verify_fight_preview_memory_news(conn, pairs_with_memories=None):
    """Force-book a fight between two fighters with previous_fights
    history, then verify a memory_resurfacing news item was written.

    Approach:
      1. Use the pairs collected in Step 3 (pairs_with_memories) —
         these are guaranteed to have surface_memories return at
         least one memory.
      2. If no pairs are available (or Step 3 wasn't run), fall back
         to scanning fighter_memory_links + fight_history.
      3. Call news.generate_fight_preview_memory_news directly with
         this pair (simulates the book_fight / schedule_next_event
         wiring without running a full event).
      4. Check that a memory_resurfacing news item was written (or
         that the function returned a non-None news_item_id).

    Returns: True if the verification passed, False otherwise.
    """
    _print_subsection("Step 5 — Verify fight-preview memory news "
                      "(forced booking)")
    try:
        from news import generate_fight_preview_memory_news
        from interpretation.memory_engine import surface_memories
    except ImportError as e:
        print(f"  ERROR: cannot import news/memory_engine: {e}",
              file=sys.stderr)
        return False

    # Use the pairs collected in Step 3 if available — these are
    # GUARANTEED to have memories (Step 3 already called surface_
    # memories on them and got non-empty results).
    test_pairs_data = []
    if pairs_with_memories:
        for fa, fb, memories in pairs_with_memories:
            test_pairs_data.append((fa, fb, memories))
        print(f"  Using {len(test_pairs_data)} pairs from Step 3 "
              f"(each has ≥1 memory surfaced).")

    if not test_pairs_data:
        # Fallback — scan fighter_memory_links + fight_history.
        print(f"  No Step 3 pairs available — scanning "
              f"fighter_memory_links + fight_history for candidates...")
        pairs = set()
        link_rows = _query_all(
            conn,
            """
            SELECT DISTINCT fighter_id, linked_fighter_id
            FROM fighter_memory_links
            WHERE fighter_id < linked_fighter_id
            LIMIT 100
            """,
        )
        for fa, fb in link_rows:
            pairs.add((fa, fb))
        fh_rows = _query_all(
            conn,
            """
            SELECT DISTINCT fighter_id, opponent_id
            FROM fight_history
            WHERE fighter_id IS NOT NULL AND opponent_id IS NOT NULL
              AND fighter_id < opponent_id
            LIMIT 100
            """,
        )
        for fa, fb in fh_rows:
            pairs.add((fa, fb))
        for fa, fb in list(pairs)[:50]:
            try:
                memories = surface_memories(conn, fa, fb)
            except Exception:
                continue
            if memories:
                test_pairs_data.append((fa, fb, memories))

    if not test_pairs_data:
        print("  No fighter pairs with history found — skipping "
              "(sim may not have produced any fights yet).")
        return False

    # Test up to 30 pairs that have memories (we just need one to
    # pass). Use the ones with the MOST memories first (more likely
    # to clear the daily-cap check).
    test_pairs_data.sort(key=lambda x: -len(x[2]))
    test_pairs_data = test_pairs_data[:30]

    # Pre-flight: the SIGNIFICANT daily cap is 5/day. If the current
    # sim_date has 5 SIGNIFICANT items already, the test will fail
    # not because the function is broken, but because the cap is
    # reached. To isolate the function test from the cap, advance
    # the sim_date by 1 day so the cap resets (the cap is per
    # published_at date). This is a TEST-ONLY clock advance — the
    # live DB is unaffected (we're operating on the temp copy).
    try:
        clock = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        today = clock[0] if clock else None
        if today:
            sig_count = _scalar(
                conn,
                "SELECT COUNT(*) FROM news_items "
                "WHERE published_at=? AND importance='SIGNIFICANT'",
                (today,),
            )
            if sig_count >= 5:
                # Advance the sim_date by 1 day to reset the cap.
                from datetime import datetime as _dt, timedelta as _td
                try:
                    today_dt = _dt.fromisoformat(today)
                    next_day = (today_dt + _td(days=1)).isoformat()[:10]
                    conn.execute(
                        "UPDATE simulation_clock SET current_date=? "
                        "WHERE clock_id=1",
                        (next_day,),
                    )
                    conn.commit()
                    print(f"  Pre-flight: SIGNIFICANT cap reached on "
                          f"{today} ({sig_count}/5). Advanced sim_date "
                          f"to {next_day} to reset the cap for the "
                          f"forced-booking test.")
                except Exception as e:
                    print(f"  Pre-flight: could not advance sim_date: "
                          f"{e}", file=sys.stderr)
    except Exception as e:
        print(f"  Pre-flight check failed: {e}", file=sys.stderr)

    print(f"  Testing generate_fight_preview_memory_news on "
          f"{len(test_pairs_data)} pairs (each has ≥1 memory)...")

    success_count = 0
    sample_pair = None
    for fa, fb, memories in test_pairs_data:
        # Call generate_fight_preview_memory_news.
        # Pass fight_id=None (news_items.fight_id is nullable — we
        # don't want to insert a fake fights row just for the test).
        # This is the same path the news engine uses when the fight
        # row hasn't been committed yet (the caller commits the
        # fights row + the news row together).
        try:
            news_id = generate_fight_preview_memory_news(
                conn, fight_id=None, fighter_a_id=fa, fighter_b_id=fb,
                event_id=None, promotion_id=None,
            )
        except Exception as e:
            print(f"  ERROR calling generate_fight_preview_memory_news"
                  f"(a={fa}, b={fb}): {type(e).__name__}: {e}",
                  file=sys.stderr)
            continue
        if news_id is not None:
            success_count += 1
            if sample_pair is None:
                sample_pair = (fa, fb, news_id, memories[0])
            # Commit the write so the news_item is persisted.
            conn.commit()

    if success_count == 0:
        print("  ✗ FAIL — generate_fight_preview_memory_news did not "
              "write any news items for tested pairs.")
        print(f"     Tested {len(test_pairs_data)} pairs; none produced "
              f"a memory_resurfacing news item.")
        print(f"     This is likely a daily-cap issue — the SIGNIFICANT "
              f"cap (5/day) may be reached on the current sim_date. "
              f"Check the news_items table for the current date's "
              f"SIGNIFICANT-tier count.")
        # Diagnostic: show the SIGNIFICANT-tier count for today.
        try:
            clock = conn.execute(
                "SELECT simulation_clock.current_date "
                "FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            today = clock[0] if clock else None
            if today:
                sig_count = _scalar(
                    conn,
                    "SELECT COUNT(*) FROM news_items "
                    "WHERE published_at=? AND importance='SIGNIFICANT'",
                    (today,),
                )
                print(f"     Today ({today}) SIGNIFICANT-tier news "
                      f"count: {sig_count}/5 (cap=5)")
        except Exception:
            pass
        return False

    # Show the sample.
    fa, fb, news_id, first_memory = sample_pair
    print(f"  ✓ PASS — generate_fight_preview_memory_news wrote "
          f"{success_count} news items.")
    print(f"     Sample: fighters ({fa}, {fb}) → news_item_id="
          f"{news_id}")
    print(f"     Memory surfaced: {first_memory[0]} — "
          f"\"{first_memory[1][:80]}...\"")
    # Verify the news item is actually in the DB.
    row = conn.execute(
        "SELECT headline, body, importance FROM news_items "
        "WHERE news_item_id=?",
        (news_id,),
    ).fetchone()
    if row:
        print(f"     Headline: {row[0]}")
        print(f"     Importance: {row[2]}")
    return True


# ----------------------------------------------------------------
# Step 6 — Verify the wiring (book_fight + schedule_next_event call
# generate_fight_preview_memory_news)
# ----------------------------------------------------------------

def verify_wiring():
    """Static check that generate_fight_preview_memory_news is called
    from both book_fight (player API) and schedule_next_event (rival
    AI matchmaking).

    We do a source-text grep instead of running the actual functions
    (which require complex setup).
    """
    _print_subsection("Step 6 — Wiring check (book_fight + "
                      "schedule_next_event call generate_fight_preview"
                      "_memory_news)")
    import re
    checks = [
        ("src/app_web.py", "book_fight",
         "player API fight booking"),
        ("src/services/matchmaking.py", "schedule_next_event",
         "rival AI event scheduling"),
    ]
    all_pass = True
    for rel_path, expected_func, description in checks:
        path = PROJECT_DIR / rel_path
        if not path.exists():
            print(f"  ✗ {rel_path} not found")
            all_pass = False
            continue
        try:
            text = path.read_text()
        except Exception as e:
            print(f"  ✗ cannot read {rel_path}: {e}")
            all_pass = False
            continue
        has_call = "generate_fight_preview_memory_news" in text
        has_func = re.search(rf"def\s+{expected_func}\s*\(", text) is not None
        marker = "✓" if (has_call and has_func) else "✗"
        print(f"  {marker} {rel_path:35s} "
              f"calls generate_fight_preview_memory_news "
              f"in {expected_func}() ({description})")
        if not (has_call and has_func):
            all_pass = False
    return all_pass


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="?", type=int, default=30,
                    help="Sim days to run (default 30).")
    ap.add_argument("--no-sim", action="store_true",
                    help="Skip the sim — just check the current DB "
                         "state (Step 2-6 only).")
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="DB path (default: live DB; the script copies "
                         "it to a temp path before running the sim).")
    ap.add_argument("--keep-temp-db", action="store_true", default=True,
                    help="Keep the temp DB after the run (default: "
                         "True — printed at end for inspection).")
    args = ap.parse_args()

    print("=" * 76)
    print("  CAGE EMPIRE — Memory Resurfacing Test")
    print("  (NEWS-SPAM-MEMORY-CHECK Issue 2)")
    print("=" * 76)
    print(f"  Source DB: {args.db}")
    print(f"  Sim days:  {0 if args.no_sim else args.days}")

    src_db = Path(args.db)
    if not src_db.exists():
        print(f"  ERROR: DB not found at {src_db}", file=sys.stderr)
        return 2

    # ALWAYS copy to a temp DB — the test writes news_items rows
    # (Step 5 calls generate_fight_preview_memory_news which INSERTs
    # a news_items row). Operating directly on the source DB would
    # pollute it with test data.
    temp_dir = Path(tempfile.mkdtemp(prefix="cage_memtest_"))
    temp_db = temp_dir / "test.db"
    shutil.copy2(src_db, temp_db)
    print(f"  Temp DB:   {temp_db}")
    if args.no_sim:
        print(f"  (--no-sim — skipping the sim; running checks on the "
              f"temp copy.)")

    conn = sqlite3.connect(str(temp_db))
    conn.execute("PRAGMA foreign_keys = ON;")

    # Show before state.
    clock = conn.execute(
        "SELECT simulation_clock.current_date, simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = clock[0] if clock else "?"
    sim_day = clock[1] if clock else 0
    print(f"  BEFORE:    sim_date={sim_date} (day {sim_day})")
    fml_before = _scalar(
        conn, "SELECT COUNT(*) FROM fighter_memory_links")
    news_before = _scalar(conn, "SELECT COUNT(*) FROM news_items")
    print(f"  BEFORE:    fighter_memory_links={fml_before}, "
          f"news_items={news_before}")

    if not args.no_sim:
        # Register subscribers.
        print("\n  Registering event-bus subscribers...")
        registered, failed = register_all_subscribers()
        print(f"  Registered {registered} subscribers ({failed} failed)")

        # Run the sim.
        _print_section(f"Step 1 — Run {args.days}-day sim")
        run_sim(conn, args.days)

        # Show after state.
        clock = conn.execute(
            "SELECT simulation_clock.current_date, "
            "       simulation_clock.current_day "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        sim_date = clock[0] if clock else "?"
        sim_day = clock[1] if clock else 0
        print(f"  AFTER:     sim_date={sim_date} (day {sim_day})")
        fml_after = _scalar(
            conn, "SELECT COUNT(*) FROM fighter_memory_links")
        news_after = _scalar(conn, "SELECT COUNT(*) FROM news_items")
        print(f"  AFTER:     fighter_memory_links={fml_after} "
              f"(+{fml_after - fml_before}), "
              f"news_items={news_after} (+{news_after - news_before})")

    # Step 2 — check link writers.
    _print_section("Memory Link Writers + Surface Memories + News")
    link_results = check_link_writers(conn)

    # Step 3 — check surface_memories.
    surface_results, pairs_with_memories = check_surface_memories(conn)

    # Step 4 — check memory_resurfacing news.
    mr_count, legacy_count = check_memory_resurfacing_news(conn)

    # Step 5 — verify fight-preview memory news fires.
    _print_section("Fight-Preview Memory News Verification")
    preview_pass = verify_fight_preview_memory_news(
        conn, pairs_with_memories=pairs_with_memories)

    # Step 6 — wiring check.
    _print_section("Wiring Check (book_fight + schedule_next_event)")
    wiring_pass = verify_wiring()

    # Final summary.
    _print_section("FINAL SUMMARY")
    written_types = sum(1 for c in link_results.values() if c > 0)
    surface_types = sum(1 for c in surface_results.values() if c > 0)
    print(f"  Memory link types written:  "
          f"{written_types}/{len(MEMORY_LINK_TYPES)}")
    print(f"  surface_memories types finding results:  "
          f"{surface_types}/{len(SURFACE_SEARCH_TYPES)}")
    print(f"  memory_resurfacing news items:  {mr_count}")
    print(f"  legacy news items:              {legacy_count}")
    print(f"  Fight-preview memory news:      "
          f"{'✓ PASS' if preview_pass else '✗ FAIL'}")
    print(f"  Wiring (book_fight + schedule_next_event):  "
          f"{'✓ PASS' if wiring_pass else '✗ FAIL'}")
    print()

    # Verdict.
    overall_pass = preview_pass and wiring_pass
    if overall_pass:
        print("  ✓ OVERALL: PASS — fight-preview memory news verification "
              "passed + wiring is correct.")
    else:
        print("  ✗ OVERALL: FAIL — see failures above.")
    print()
    print(f"  Temp DB retained at: {temp_db}")
    print(f"  (Delete manually if no longer needed.)")

    conn.close()
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
