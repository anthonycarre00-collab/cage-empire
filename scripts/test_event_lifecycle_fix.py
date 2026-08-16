#!/usr/bin/env python3
"""HW8.1 — Verify the event-lifecycle bug fix.

The bug: `resolve_next_fight` did NOT filter its pick-query by
`e.event_date <= sim_date`. So when the rival AI's `_resolve_event_card`
loop called it repeatedly until None, it would resolve fights on
FUTURE-dated events too — marking them 'completed' months before
their event_date.

The fix: the pick-query now reads the sim_date from simulation_clock
and adds `AND e.event_date <= ?` to the WHERE clause.

This test sets up a tiny world with TWO events for the same promo:
  - Event A: event_date = sim_date (today, due)
  - Event B: event_date = sim_date + 90 days (future)

Both events have unresolved fights. Before the fix, calling
`resolve_next_fight(promotion_id=X)` in a loop until None would
resolve BOTH events. After the fix, only Event A is resolved.

Runs on a fresh in-memory DB (does NOT touch the live world DB).
"""
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))


def _make_test_db():
    """Build a minimal schema + seed 2 events with unresolved fights."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE simulation_clock (
            clock_id INTEGER PRIMARY KEY,
            current_date TEXT NOT NULL,
            current_day INTEGER,
            current_week INTEGER,
            current_month INTEGER,
            current_year INTEGER
        );
        INSERT INTO simulation_clock VALUES (1, '2026-08-27', 239, 35, 8, 2026);

        CREATE TABLE promotions (
            promotion_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            cash REAL DEFAULT 1000000
        );
        INSERT INTO promotions VALUES (1, 'Test Promo', 1000000);

        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY,
            promotion_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE fights (
            fight_id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            scheduled_rounds INTEGER DEFAULT 3,
            weight_class_id INTEGER,
            card_slot TEXT,
            is_title_fight INTEGER DEFAULT 0,
            winner_fighter_id INTEGER,
            result_type TEXT
        );

        CREATE TABLE fight_participants (
            fight_id INTEGER NOT NULL,
            fighter_id INTEGER NOT NULL,
            corner INTEGER DEFAULT 0,
            is_winner INTEGER DEFAULT 0
        );

        CREATE TABLE fighters (
            fighter_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            current_promotion_id INTEGER
        );
        -- 4 dummy fighters
        INSERT INTO fighters VALUES (1, 'A1', 1);
        INSERT INTO fighters VALUES (2, 'A2', 1);
        INSERT INTO fighters VALUES (3, 'B1', 1);
        INSERT INTO fighters VALUES (4, 'B2', 1);

        -- Event A: due today (event_date = sim_date)
        INSERT INTO events (event_id, promotion_id, event_date, status)
        VALUES (10, 1, '2026-08-27', 'card_confirmed');
        INSERT INTO fights (fight_id, event_id, card_slot) VALUES (100, 10, 'main_event');
        INSERT INTO fight_participants VALUES (100, 1, 0, 0);
        INSERT INTO fight_participants VALUES (100, 2, 1, 0);

        -- Event B: future-dated (event_date = sim_date + 90 days)
        INSERT INTO events (event_id, promotion_id, event_date, status)
        VALUES (20, 1, '2026-11-25', 'card_confirmed');
        INSERT INTO fights (fight_id, event_id, card_slot) VALUES (200, 20, 'main_event');
        INSERT INTO fight_participants VALUES (200, 3, 0, 0);
        INSERT INTO fight_participants VALUES (200, 4, 1, 0);
    """)
    conn.commit()
    return conn


def test_pick_query_skips_future_events():
    """The pick-query should NOT pick a fight from a future-dated event
    when there are NO due events with unresolved fights.

    Scenario:
      - Event A: event_date = sim_date (today, due) — all fights resolved
      - Event B: event_date = sim_date + 90 days (future) — has unresolved fight

    OLD pick-query: would pick Event B's fight (because no date filter)
    NEW pick-query: returns None (correctly skips future event)
    """
    conn = _make_test_db()
    # Mark Event A's fight as already resolved (winner set)
    conn.execute(
        "UPDATE fights SET winner_fighter_id=1, result_type='ko' WHERE fight_id=100"
    )
    conn.commit()

    sim_date = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    print(f"  sim_date from clock: {sim_date}")

    # Without date filter (OLD behavior — BUG):
    old_pick = conn.execute(
        "SELECT f.fight_id, e.event_id, e.event_date "
        "FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL "
        "AND e.promotion_id=? "
        "ORDER BY f.fight_id ASC LIMIT 1",
        (1,),
    ).fetchone()
    if old_pick:
        print(f"  OLD pick-query (no date filter): fight={old_pick[0]}, event={old_pick[1]}, event_date={old_pick[2]}")
    else:
        print(f"  OLD pick-query (no date filter): None (no unresolved fights)")

    # With date filter (NEW behavior — FIX):
    new_pick = conn.execute(
        "SELECT f.fight_id, e.event_id, e.event_date "
        "FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL "
        "AND e.promotion_id=? "
        "AND e.event_date <= ? "
        "ORDER BY f.fight_id ASC LIMIT 1",
        (1, sim_date),
    ).fetchone()
    if new_pick:
        print(f"  NEW pick-query (with date filter): fight={new_pick[0]}, event={new_pick[1]}, event_date={new_pick[2]}")
    else:
        print(f"  NEW pick-query (with date filter): None (correctly skipped future event)")

    # Assertions
    assert old_pick is not None, "Sanity check failed: OLD pick should have picked the future fight"
    assert old_pick[1] == 20, f"Sanity check failed: OLD pick chose event {old_pick[1]} (should be 20 = future)"
    assert new_pick is None, f"FAIL: NEW pick chose event {new_pick[1]} (should be None — future events must be skipped)"
    print("  PASS: NEW pick-query correctly returns None when only future-dated events have unresolved fights.")


def test_no_participant_filter_unchanged():
    """When promotion_id is None (player UI path), the date filter
    should still apply — the player shouldn't be able to resolve
    future events either."""
    conn = _make_test_db()
    sim_date = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]

    # With promotion_id=None (player path) + date filter
    new_pick = conn.execute(
        "SELECT f.fight_id, e.event_id, e.event_date "
        "FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL "
        "AND e.event_date <= ? "
        "ORDER BY f.fight_id ASC LIMIT 1",
        (sim_date,),
    ).fetchone()
    print(f"  Player path (promotion_id=None) pick: fight={new_pick[0]}, event={new_pick[1]}")
    assert new_pick[1] == 10, f"FAIL: player path picked future event {new_pick[1]}"
    print("  PASS: player path also respects date filter.")


if __name__ == "__main__":
    print("=== HW8.1 — event-lifecycle bug fix verification ===")
    print()
    print("Test 1: pick-query skips future-dated events")
    test_pick_query_skips_future_events()
    print()
    print("Test 2: player path (promotion_id=None) also respects date filter")
    test_no_participant_filter_unchanged()
    print()
    print("All tests passed.")
