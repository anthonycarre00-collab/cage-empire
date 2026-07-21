#!/usr/bin/env python3
"""Acceptance test for Task ID 8 — repeatable event generator.

This script:
  1. Builds a fresh DB (drop + rebuild + seed).
  2. Test case A — Single-fight event triggers scheduling:
     - Before: assert 1 event exists (the seeded one).
     - Call app.resolve_next_fight(conn), commit.
     - After: assert 2 events exist (original + 1 new).
     - Assert original event's status is 'completed'.
     - Assert new event's status is 'scheduled'.
     - Assert new event's date is 2026-08-15 + 28 days = 2026-09-12.
     - Assert new event's promotion_id matches the original.
     - Assert new event has at least 1 fight with exactly 2 participants.
     - Assert the 2 participants are distinct fighter_ids.
     - Assert both participants have current_promotion_id = Alpha Combat.
  3. Test case B — Multi-fight event triggers scheduling only on
     last fight:
     - Build a fresh DB again.
     - Add 2 extra fights to the seeded event (3 fights total).
     - Resolve fight 1: assert still 1 event (no scheduling yet).
     - Resolve fight 2: assert still 1 event (no scheduling yet).
     - Resolve fight 3: assert now 2 events (scheduling triggered).
     - Assert the new event's status is 'scheduled'.
  4. Test case C — No infinite loop:
     - Continuing from case A (2 events: original 'completed' + new
       'scheduled' with 1 unresolved fight).
     - Resolve the new event's fight: assert 3 events total (the new
       event is now 'completed', ANOTHER new event was scheduled).
     - Assert exactly 1 new event was created per resolution.
  5. Test case D — Loop continues for at least 3 cycles:
     - Continuing from case C (3 events).
     - Resolve 3rd event's fight: assert 4 events total.
     - Resolve 4th event's fight: assert 5 events total.
     - Verify event dates increment by ~28 days each time:
       2026-08-15, 2026-09-12, 2026-10-10, 2026-11-07, 2026-12-05.
  6. Test case E — Not enough fighters:
     - Fresh DB. Create a new promotion "Solo Promoters" with only
       1 fighter.
     - Call app.schedule_next_event(conn, solo_promo_id, ...) directly.
     - Capture stdout. Assert: returns None. Assert: no new event was
       created. Assert: a warning was printed.
  7. Test case F — schedule_next_event() is callable directly:
     - Fresh DB.
     - Call app.schedule_next_event(conn, alpha_combat_id, ...) directly.
     - Assert: returns valid event_id (int > 0).
     - Assert: new event exists with date '2026-09-12'.
     - Assert: new event has 1 fight with 2 distinct AC participants.
     - Assert: new event's status is 'scheduled'.
  8. Test case G — Regression: fight_history and event_lifecycle
     still work:
     - Continuing from case D (5 events total, 4 completed, 1
       scheduled).
     - Assert fight_history has 8 rows (2 per fight x 4 resolved
       fights).
     - Assert each resolved fight_id has exactly 2 fight_history rows.
     - Assert fighter_career counters for AC fighters (1 and 2) match
       their fight_history row counts.
  9. Prints a PASS/FAIL summary table.
  10. Exits 0 = all PASS, 1 = any FAIL.

Run from the project root:
    python3 scripts/test_event_scheduler.py

The script only rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.

Reproducibility note (mirrors `test_event_lifecycle.py` and
`test_fight_history.py`):
  `random.seed(42)` is set before each `app.resolve_next_fight()` call
  so the test is reproducible. The seed does not weaken the test — if
  the resolver's logic, the event lifecycle code, or the scheduler's
  matchmaking changes, the same seed produces a different sequence of
  outcomes and the assertions catch the regression. The seed only pins
  down which random draws the resolver and the scheduler see, not what
  they do with them.
"""
import contextlib
import io
import random
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
# Backup path used to preserve case A's DB state across case B's
# fresh-DB rebuild. Cases C, D, G continue from case A's state per
# the brief; case B rebuilds the DB independently and must not
# destroy case A's data.
DB_BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.case_a_backup.db"

# Make src/ importable so we can call resolve_next_fight() and
# schedule_next_event() directly without going through the Tkinter UI.
sys.path.insert(0, str(SRC_DIR))

# Importing app.py pulls in tkinter. The import itself does not require
# a display (only tk.Tk() does), so this is safe in headless contexts.
import app  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Fighter IDs assigned by seed_data.py (Alpha Combat's two fighters).
# John "Hammer" Vale = 1 (red corner), Marcus "Voltage" Reed = 2 (blue).
A_ID = 1
B_ID = 2

# Alpha Combat is the first promotion seeded by seed_data.py — its
# promotion_id is 1.
ALPHA_COMBAT_PROMO_ID = 1

# Seeded event values from src/seed_data.py — used for assertions.
SEEDED_EVENT_NAME = "Alpha Combat: Test Night"
SEEDED_EVENT_DATE = "2026-08-15"

# weeks_out default for schedule_next_event — Task ID 8 brief specifies 4.
DEFAULT_WEEKS_OUT = 4

# Expected new event date when scheduled DEFAULT_WEEKS_OUT weeks after
# the seeded event's 2026-08-15 date.
EXPECTED_NEW_DATE_STR = "2026-09-12"  # 2026-08-15 + 28 days


def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True,
        cwd=PROJECT_DIR,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True,
        cwd=PROJECT_DIR,
    )


def add_extra_fight(conn, event_id, weight_class_id, fighter_a_id, fighter_b_id,
                    corner_a='red', corner_b='blue'):
    """Insert a fight + 2 fight_participants on the given event.

    Adapted (copy/paste) from `scripts/test_event_lifecycle.py`'s
    helper of the same name — per the brief, this test does NOT import
    from the other test. Adds a 'prelim' bout to the seeded event so we
    can test the multi-fight scheduling case (which requires more than
    1 fight on the card before the trigger fires). The
    fight_participants UNIQUE constraint is on (fight_id, fighter_id),
    NOT on corner — so two different fight_ids can both have fighter 1
    in the red corner.

    Returns the new fight_id.
    """
    fight_id = conn.execute(
        "INSERT INTO fights (event_id, weight_class_id, bout_type, round_limit, scheduled_rounds) "
        "VALUES (?, ?, 'prelim', 3, 3)",
        (event_id, weight_class_id),
    ).lastrowid
    conn.execute(
        "INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)",
        (fight_id, fighter_a_id, corner_a),
    )
    conn.execute(
        "INSERT INTO fight_participants (fight_id, fighter_id, corner) VALUES (?, ?, ?)",
        (fight_id, fighter_b_id, corner_b),
    )
    return fight_id


def add_solo_promotion_with_one_fighter(conn):
    """Insert a new promotion "Solo Promoters" with exactly 1 fighter.

    For test case E — needs a promotion whose roster is too small to
    schedule a fight (need 2, have 1). Mirrors seed_data.py's pattern:
    inserts into promotions, fighters, fighter_attributes,
    fighter_personality, fighter_career.

    Returns (solo_promo_id, solo_fighter_id).
    """
    # Reuse the seeded nation/region/city/weight_class/gym/style/pers
    # so the FKs resolve. The seeded values come from seed_data.py:
    #   nation_id=1, region_id=1, city_id=1, weight_class_id=1,
    #   gym_id=1, style_id=1, pers_id=1.
    solo_promo_id = conn.execute(
        "INSERT INTO promotions (name, size_tier, nation_id, region_id) "
        "VALUES (?, ?, ?, ?)",
        ("Solo Promoters", "small", 1, 1),
    ).lastrowid
    solo_fighter_id = conn.execute(
        "INSERT INTO fighters ("
        "    first_name, last_name, nickname, gender, date_of_birth,"
        "    birth_city_id, birth_nation_id, residence_city_id, residence_nation_id,"
        "    weight_class_id, current_gym_id, current_promotion_id,"
        "    fight_style_archetype_id, personality_archetype_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Lone", "Wolf", "Solo", "male", "1990-01-01",
         1, 1, 1, 1, 1, 1, solo_promo_id, 1, 1),
    ).lastrowid
    conn.execute(
        "INSERT INTO fighter_attributes (fighter_id) VALUES (?)",
        (solo_fighter_id,),
    )
    conn.execute(
        "INSERT INTO fighter_personality (fighter_id) VALUES (?)",
        (solo_fighter_id,),
    )
    conn.execute(
        "INSERT INTO fighter_career (fighter_id) VALUES (?)",
        (solo_fighter_id,),
    )
    conn.commit()
    return solo_promo_id, solo_fighter_id


def main():
    sep = "=" * 80
    print(sep)
    print("TASK 8 REPEATABLE EVENT GENERATOR ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail).
    results = []

    # ----------------------------------------------------------------
    # Test case A — Single-fight event triggers scheduling.
    # ----------------------------------------------------------------
    print("\n--- Case A: single-fight event triggers scheduling ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Before: assert 1 event exists (the seeded one).
    n_events_a_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "A",
        "1 event exists before resolution (the seeded one)",
        n_events_a_before == 1,
        f"got={n_events_a_before}",
    ))

    seeded_a = conn.execute(
        "SELECT event_id, event_date, status, promotion_id "
        "FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    seeded_event_id_a, seeded_date_a, seeded_status_a, seeded_promo_a = seeded_a
    results.append((
        "A",
        "seeded event_date == '2026-08-15'",
        seeded_date_a == SEEDED_EVENT_DATE,
        f"got={seeded_date_a!r}",
    ))
    results.append((
        "A",
        "seeded events.status == 'scheduled' before resolution",
        seeded_status_a == "scheduled",
        f"got={seeded_status_a!r}",
    ))

    # Resolve the single fight. Seed RNG for reproducibility.
    random.seed(RANDOM_SEED)
    resolved_a = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "A",
        "resolve_next_fight returned a fight_id",
        resolved_a is not None,
        f"fight_id={resolved_a}",
    ))

    # After: assert 2 events exist.
    n_events_a_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "A",
        "2 events exist after resolution (original + 1 new)",
        n_events_a_after == 2,
        f"got={n_events_a_after}",
    ))

    # Original event status is 'completed'.
    original_status_a = conn.execute(
        "SELECT status FROM events WHERE event_id = ?",
        (seeded_event_id_a,),
    ).fetchone()[0]
    results.append((
        "A",
        "original event's status is 'completed' after resolution",
        original_status_a == "completed",
        f"got={original_status_a!r}",
    ))

    # New event status is 'scheduled'.
    new_event_a = conn.execute(
        "SELECT event_id, event_date, status, promotion_id "
        "FROM events WHERE event_id != ? ORDER BY event_id",
        (seeded_event_id_a,),
    ).fetchone()
    results.append((
        "A",
        "new event exists (different from original)",
        new_event_a is not None,
        f"row={new_event_a}",
    ))
    new_event_id_a, new_date_a, new_status_a, new_promo_a = new_event_a
    results.append((
        "A",
        "new event's status is 'scheduled'",
        new_status_a == "scheduled",
        f"got={new_status_a!r}",
    ))

    # New event's date is 2026-08-15 + 28 days = 2026-09-12.
    expected_date = (
        datetime.strptime(SEEDED_EVENT_DATE, "%Y-%m-%d")
        + timedelta(weeks=DEFAULT_WEEKS_OUT)
    ).strftime("%Y-%m-%d")
    results.append((
        "A",
        f"new event's date is {expected_date} (seeded + 28 days)",
        new_date_a == expected_date,
        f"got={new_date_a!r}, expected={expected_date!r}",
    ))

    # New event's promotion_id matches the original (Alpha Combat).
    results.append((
        "A",
        "new event's promotion_id matches original (Alpha Combat)",
        new_promo_a == seeded_promo_a,
        f"new={new_promo_a}, original={seeded_promo_a}",
    ))

    # New event has at least 1 fight with exactly 2 participants.
    n_fights_new_a = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id = ?",
        (new_event_id_a,),
    ).fetchone()[0]
    results.append((
        "A",
        "new event has at least 1 fight",
        n_fights_new_a >= 1,
        f"got={n_fights_new_a}",
    ))
    fight_id_new_a = conn.execute(
        "SELECT fight_id FROM fights WHERE event_id = ? ORDER BY fight_id LIMIT 1",
        (new_event_id_a,),
    ).fetchone()[0]
    n_parts_new_a = conn.execute(
        "SELECT COUNT(*) FROM fight_participants WHERE fight_id = ?",
        (fight_id_new_a,),
    ).fetchone()[0]
    results.append((
        "A",
        "new event's fight has exactly 2 participants",
        n_parts_new_a == 2,
        f"got={n_parts_new_a}",
    ))

    # The 2 participants are distinct fighter_ids.
    part_ids_a = [r[0] for r in conn.execute(
        "SELECT fighter_id FROM fight_participants WHERE fight_id = ?",
        (fight_id_new_a,),
    ).fetchall()]
    results.append((
        "A",
        "the 2 participants are distinct fighter_ids",
        len(set(part_ids_a)) == 2,
        f"got={part_ids_a}",
    ))

    # Both participants have current_promotion_id = Alpha Combat's promo_id.
    # Count fighters whose id is in (id1, id2) AND whose current_promotion_id
    # matches. If both are AC fighters, the count should be 2.
    ac_count = conn.execute(
        "SELECT COUNT(*) FROM fighters "
        "WHERE fighter_id IN (?, ?) AND current_promotion_id = ?",
        (part_ids_a[0], part_ids_a[1], ALPHA_COMBAT_PROMO_ID),
    ).fetchone()[0]
    results.append((
        "A",
        "both participants have current_promotion_id = Alpha Combat",
        ac_count == 2,
        f"got {ac_count}/2 in Alpha Combat",
    ))

    # Stash case A's key ids for cases C, D, G (which continue from
    # case A's state per the brief). We close the connection and
    # back up the DB file because case B (next) rebuilds the DB
    # independently — without a backup, case B's rebuild would
    # destroy case A's data and break cases C/D/G.
    case_a_seeded_event_id = seeded_event_id_a
    case_a_new_event_id = new_event_id_a
    case_a_resolved_fight_ids = [resolved_a]
    conn.close()
    # Save a backup copy of the DB file so we can restore case A's
    # state after case B does its own fresh-DB rebuild.
    if DB_BACKUP_PATH.exists():
        DB_BACKUP_PATH.unlink()
    shutil.copy2(DB_PATH, DB_BACKUP_PATH)

    # ----------------------------------------------------------------
    # Test case B — Multi-fight event triggers scheduling only on
    # last fight.
    # ----------------------------------------------------------------
    print("\n--- Case B: multi-fight event triggers scheduling only on "
          "last fight ---")
    build_fresh_db()
    conn_b = sqlite3.connect(DB_PATH)
    conn_b.execute("PRAGMA foreign_keys = ON;")

    seeded_b = conn_b.execute(
        "SELECT e.event_id, f.weight_class_id FROM events e JOIN fights f "
        "ON f.event_id = e.event_id "
        "ORDER BY e.event_id LIMIT 1"
    ).fetchone()
    event_id_b, weight_class_id_b = seeded_b

    # Add 2 extra fights to the same event so it has 3 fights total.
    add_extra_fight(conn_b, event_id_b, weight_class_id_b, A_ID, B_ID)
    add_extra_fight(conn_b, event_id_b, weight_class_id_b, A_ID, B_ID)
    conn_b.commit()

    n_unresolved_b_before = conn_b.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE event_id = ? AND winner_fighter_id IS NULL "
        "AND result_type IS NULL",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "event has 3 unresolved fights before any resolution",
        n_unresolved_b_before == 3,
        f"got={n_unresolved_b_before}",
    ))

    n_events_b_before = conn_b.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "B",
        "1 event exists before any resolution",
        n_events_b_before == 1,
        f"got={n_events_b_before}",
    ))

    # Resolve fight 1: still 1 event (no scheduling yet, status=
    # 'in_progress' because 2 unresolved fights remain).
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn_b)
    conn_b.commit()
    n_events_b_after_1 = conn_b.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "B",
        "1 event still exists after resolving fight 1 of 3",
        n_events_b_after_1 == 1,
        f"got={n_events_b_after_1}",
    ))
    status_b_after_1 = conn_b.execute(
        "SELECT status FROM events WHERE event_id = ?",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "events.status == 'in_progress' after resolving fight 1 of 3",
        status_b_after_1 == "in_progress",
        f"got={status_b_after_1!r}",
    ))

    # Resolve fight 2: still 1 event (no scheduling yet, status=
    # 'in_progress' because 1 unresolved fight remains).
    app.resolve_next_fight(conn_b)
    conn_b.commit()
    n_events_b_after_2 = conn_b.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "B",
        "1 event still exists after resolving fight 2 of 3",
        n_events_b_after_2 == 1,
        f"got={n_events_b_after_2}",
    ))
    status_b_after_2 = conn_b.execute(
        "SELECT status FROM events WHERE event_id = ?",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "events.status == 'in_progress' after resolving fight 2 of 3",
        status_b_after_2 == "in_progress",
        f"got={status_b_after_2!r}",
    ))

    # Resolve fight 3: 2 events (scheduling triggered, original status=
    # 'completed', new event 'scheduled').
    app.resolve_next_fight(conn_b)
    conn_b.commit()
    n_events_b_after_3 = conn_b.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "B",
        "2 events exist after resolving fight 3 of 3 (scheduling triggered)",
        n_events_b_after_3 == 2,
        f"got={n_events_b_after_3}",
    ))
    status_b_after_3 = conn_b.execute(
        "SELECT status FROM events WHERE event_id = ?",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "events.status == 'completed' after resolving fight 3 of 3",
        status_b_after_3 == "completed",
        f"got={status_b_after_3!r}",
    ))
    # The new event scheduled by fight 3's resolution should be
    # 'scheduled'.
    new_event_b = conn_b.execute(
        "SELECT status FROM events WHERE event_id != ? ORDER BY event_id",
        (event_id_b,),
    ).fetchone()
    results.append((
        "B",
        "new event's status is 'scheduled'",
        new_event_b is not None and new_event_b[0] == "scheduled",
        f"row={new_event_b}",
    ))

    conn_b.close()

    # ----------------------------------------------------------------
    # Test case C — No infinite loop.
    # Continuing from case A's DB (2 events: 1 'completed' + 1
    # 'scheduled' with 1 unresolved fight). Restore case A's backup
    # so case B's fresh-DB rebuild doesn't break cases C/D/G.
    # ----------------------------------------------------------------
    print("\n--- Case C: no infinite loop (exactly 1 new event per "
          "resolution) ---")
    # Restore case A's DB file from the backup.
    if DB_PATH.exists():
        DB_PATH.unlink()
    shutil.copy2(DB_BACKUP_PATH, DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    n_events_c_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "C",
        "2 events exist before resolving new event's fight",
        n_events_c_before == 2,
        f"got={n_events_c_before}",
    ))

    # Resolve the new event's fight. This transitions it to 'completed'
    # AND triggers scheduling of ANOTHER new event.
    random.seed(RANDOM_SEED)
    resolved_c = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "C",
        "resolve_next_fight returned a fight_id",
        resolved_c is not None,
        f"fight_id={resolved_c}",
    ))

    n_events_c_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "C",
        "3 events exist after resolving new event's fight "
        "(new event completed + ANOTHER new event scheduled)",
        n_events_c_after == 3,
        f"got={n_events_c_after}",
    ))

    # Exactly 1 new event was created (3 - 2 = 1).
    results.append((
        "C",
        "exactly 1 new event created per resolution (no infinite loop)",
        n_events_c_after - n_events_c_before == 1,
        f"delta={n_events_c_after - n_events_c_before}",
    ))

    # The new event (just resolved) should now be 'completed'.
    case_a_new_event_status_c = conn.execute(
        "SELECT status FROM events WHERE event_id = ?",
        (case_a_new_event_id,),
    ).fetchone()[0]
    results.append((
        "C",
        "case A's new event's status is now 'completed'",
        case_a_new_event_status_c == "completed",
        f"got={case_a_new_event_status_c!r}",
    ))

    # The newest event should be 'scheduled'.
    newest_event_c = conn.execute(
        "SELECT status FROM events ORDER BY event_id DESC LIMIT 1"
    ).fetchone()[0]
    results.append((
        "C",
        "newest event's status is 'scheduled'",
        newest_event_c == "scheduled",
        f"got={newest_event_c!r}",
    ))

    case_a_resolved_fight_ids.append(resolved_c)

    # ----------------------------------------------------------------
    # Test case D — Loop continues for at least 3 cycles.
    # Continuing from case C (3 events: 2 'completed' + 1 'scheduled').
    # Resolve 3rd event's fight -> 4 events. Resolve 4th event's fight
    # -> 5 events. Verify dates increment by ~28 days.
    # ----------------------------------------------------------------
    print("\n--- Case D: loop continues for at least 3 cycles ---")

    # Resolve 3rd event's fight.
    random.seed(RANDOM_SEED)
    resolved_d1 = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "D",
        "resolve_next_fight (cycle 3) returned a fight_id",
        resolved_d1 is not None,
        f"fight_id={resolved_d1}",
    ))
    n_events_d_after_cycle3 = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    results.append((
        "D",
        "4 events exist after 3rd cycle resolution",
        n_events_d_after_cycle3 == 4,
        f"got={n_events_d_after_cycle3}",
    ))
    case_a_resolved_fight_ids.append(resolved_d1)

    # Resolve 4th event's fight.
    resolved_d2 = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "D",
        "resolve_next_fight (cycle 4) returned a fight_id",
        resolved_d2 is not None,
        f"fight_id={resolved_d2}",
    ))
    n_events_d_after_cycle4 = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    results.append((
        "D",
        "5 events exist after 4th cycle resolution",
        n_events_d_after_cycle4 == 5,
        f"got={n_events_d_after_cycle4}",
    ))
    case_a_resolved_fight_ids.append(resolved_d2)

    # Verify event dates increment by exactly 28 days each time.
    # Expected: 2026-08-15, 2026-09-12, 2026-10-10, 2026-11-07,
    # 2026-12-05.
    expected_dates = []
    base = datetime.strptime(SEEDED_EVENT_DATE, "%Y-%m-%d")
    for i in range(5):
        d = base + timedelta(days=28 * i)
        expected_dates.append(d.strftime("%Y-%m-%d"))

    actual_dates = [r[0] for r in conn.execute(
        "SELECT event_date FROM events ORDER BY event_id"
    ).fetchall()]
    results.append((
        "D",
        f"event dates increment by 28 days: {expected_dates}",
        actual_dates == expected_dates,
        f"got={actual_dates}",
    ))

    # The newest (5th) event should be 'scheduled'; the 4th event
    # should be 'completed'.
    status_by_id = [
        r[0] for r in conn.execute(
            "SELECT status FROM events ORDER BY event_id"
        ).fetchall()
    ]
    results.append((
        "D",
        "5th event's status is 'scheduled' (just auto-scheduled)",
        status_by_id[4] == "scheduled",
        f"got={status_by_id[4]!r}",
    ))
    results.append((
        "D",
        "4th event's status is 'completed' (resolved in cycle 4)",
        status_by_id[3] == "completed",
        f"got={status_by_id[3]!r}",
    ))

    # Close case D's connection and re-save the backup so case G can
    # restore this state after cases E and F rebuild the DB.
    conn.close()
    if DB_BACKUP_PATH.exists():
        DB_BACKUP_PATH.unlink()
    shutil.copy2(DB_PATH, DB_BACKUP_PATH)

    # ----------------------------------------------------------------
    # Test case E — Not enough fighters.
    # ----------------------------------------------------------------
    print("\n--- Case E: not enough fighters (returns None, no new "
          "event, prints warning) ---")
    build_fresh_db()
    conn_e = sqlite3.connect(DB_PATH)
    conn_e.execute("PRAGMA foreign_keys = ON;")

    solo_promo_id, solo_fighter_id = add_solo_promotion_with_one_fighter(conn_e)

    # Verify the setup.
    solo_fighters_count = conn_e.execute(
        "SELECT COUNT(*) FROM fighters WHERE current_promotion_id = ?",
        (solo_promo_id,),
    ).fetchone()[0]
    results.append((
        "E",
        "Solo Promoters has exactly 1 fighter in roster",
        solo_fighters_count == 1,
        f"got={solo_fighters_count}",
    ))

    n_events_e_before = conn_e.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "E",
        "1 event exists before direct schedule_next_event call",
        n_events_e_before == 1,
        f"got={n_events_e_before}",
    ))

    # Capture stdout so we can assert a warning was printed.
    captured_e = io.StringIO()
    with contextlib.redirect_stdout(captured_e):
        return_e = app.schedule_next_event(
            conn_e,
            solo_promo_id,
            from_event_date="2026-08-15",
            weeks_out=DEFAULT_WEEKS_OUT,
        )
    conn_e.commit()

    results.append((
        "E",
        "schedule_next_event returned None (not enough fighters)",
        return_e is None,
        f"got={return_e}",
    ))

    n_events_e_after = conn_e.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "E",
        "events count unchanged (no new event created)",
        n_events_e_after == n_events_e_before,
        f"before={n_events_e_before}, after={n_events_e_after}",
    ))

    captured_text_e = captured_e.getvalue()
    # The warning should contain a recognizable substring. Match
    # either "not enough" (from the _pick_matchup-failed branch) or
    # "could not auto-schedule" (the prefix common to all warning
    # branches).
    warning_has_signal = (
        "not enough" in captured_text_e.lower()
        or "could not auto-schedule" in captured_text_e.lower()
    )
    results.append((
        "E",
        "warning printed to stdout (contains 'not enough' or "
        "'could not auto-schedule')",
        warning_has_signal,
        f"captured={captured_text_e!r}",
    ))

    conn_e.close()

    # ----------------------------------------------------------------
    # Test case F — schedule_next_event() is callable directly.
    # ----------------------------------------------------------------
    print("\n--- Case F: schedule_next_event() callable directly ---")
    build_fresh_db()
    conn_f = sqlite3.connect(DB_PATH)
    conn_f.execute("PRAGMA foreign_keys = ON;")

    n_events_f_before = conn_f.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    results.append((
        "F",
        "1 event exists before direct schedule_next_event call",
        n_events_f_before == 1,
        f"got={n_events_f_before}",
    ))

    # Call schedule_next_event directly. No completed event exists
    # for Alpha Combat yet — this exercises the "no completed event"
    # fallback path. The fallback looks up the promotion's nation_id,
    # then any venue in any city in that nation. The seeded Alpha
    # Combat is in Northland (nation_id=1) at Metro Arena (venue_id=1)
    # in Metro City (market_id=1).
    random.seed(RANDOM_SEED)
    return_f = app.schedule_next_event(
        conn_f,
        ALPHA_COMBAT_PROMO_ID,
        from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT,
    )
    conn_f.commit()

    results.append((
        "F",
        "schedule_next_event returned a valid event_id (int > 0)",
        isinstance(return_f, int) and return_f > 0,
        f"got={return_f} (type={type(return_f).__name__})",
    ))

    n_events_f_after = conn_f.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    results.append((
        "F",
        "2 events exist after direct schedule_next_event call",
        n_events_f_after == 2,
        f"got={n_events_f_after}",
    ))

    # The new event should have date 2026-09-12.
    new_event_f = conn_f.execute(
        "SELECT event_id, event_date, status, promotion_id "
        "FROM events WHERE event_id != ? ORDER BY event_id",
        (1,),  # seeded event_id is 1
    ).fetchone()
    results.append((
        "F",
        "new event exists",
        new_event_f is not None,
        f"row={new_event_f}",
    ))
    if new_event_f:
        new_event_id_f, new_date_f, new_status_f, new_promo_f = new_event_f
        results.append((
            "F",
            f"new event's date is {EXPECTED_NEW_DATE_STR} "
            "(2026-08-15 + 28 days)",
            new_date_f == EXPECTED_NEW_DATE_STR,
            f"got={new_date_f!r}",
        ))
        results.append((
            "F",
            "new event's status is 'scheduled'",
            new_status_f == "scheduled",
            f"got={new_status_f!r}",
        ))
        results.append((
            "F",
            "new event's promotion_id is Alpha Combat",
            new_promo_f == ALPHA_COMBAT_PROMO_ID,
            f"got={new_promo_f}",
        ))

        # New event has 1 fight with 2 distinct AC participants.
        n_fights_f = conn_f.execute(
            "SELECT COUNT(*) FROM fights WHERE event_id = ?",
            (new_event_id_f,),
        ).fetchone()[0]
        results.append((
            "F",
            "new event has exactly 1 fight",
            n_fights_f == 1,
            f"got={n_fights_f}",
        ))
        fight_id_f = conn_f.execute(
            "SELECT fight_id FROM fights WHERE event_id = ? "
            "ORDER BY fight_id LIMIT 1",
            (new_event_id_f,),
        ).fetchone()[0]
        n_parts_f = conn_f.execute(
            "SELECT COUNT(*) FROM fight_participants WHERE fight_id = ?",
            (fight_id_f,),
        ).fetchone()[0]
        results.append((
            "F",
            "new event's fight has exactly 2 participants",
            n_parts_f == 2,
            f"got={n_parts_f}",
        ))
        part_ids_f = [r[0] for r in conn_f.execute(
            "SELECT fighter_id FROM fight_participants WHERE fight_id = ?",
            (fight_id_f,),
        ).fetchall()]
        results.append((
            "F",
            "the 2 participants are distinct fighter_ids",
            len(set(part_ids_f)) == 2,
            f"got={part_ids_f}",
        ))
        ac_count_f = conn_f.execute(
            "SELECT COUNT(*) FROM fighters "
            "WHERE fighter_id IN (?, ?) AND current_promotion_id = ?",
            (part_ids_f[0], part_ids_f[1], ALPHA_COMBAT_PROMO_ID),
        ).fetchone()[0]
        results.append((
            "F",
            "both participants have current_promotion_id = Alpha Combat",
            ac_count_f == 2,
            f"got {ac_count_f}/2 in Alpha Combat",
        ))

    conn_f.close()

    # ----------------------------------------------------------------
    # Test case G — Regression: fight_history and event_lifecycle
    # still work.
    # Continuing from case D (5 events total, 4 completed, 1
    # scheduled). 4 fights have been resolved, so fight_history should
    # have 8 rows.
    # ----------------------------------------------------------------
    print("\n--- Case G: regression — fight_history + event_lifecycle "
          "still work ---")
    # Restore case D's DB state (5 events, 4 completed, 1 scheduled)
    # from the backup, since cases E and F rebuilt the DB.
    if DB_PATH.exists():
        DB_PATH.unlink()
    shutil.copy2(DB_BACKUP_PATH, DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Clean up the backup file now that we're done with it.
    if DB_BACKUP_PATH.exists():
        DB_BACKUP_PATH.unlink()

    n_events_g = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "G",
        "5 events total (4 completed + 1 scheduled)",
        n_events_g == 5,
        f"got={n_events_g}",
    ))

    # fight_history should have 8 rows (2 per fight x 4 resolved fights).
    total_fh_g = conn.execute(
        "SELECT COUNT(*) FROM fight_history"
    ).fetchone()[0]
    results.append((
        "G",
        "fight_history has 8 rows total (2 per fight x 4 resolved fights)",
        total_fh_g == 8,
        f"got={total_fh_g}",
    ))

    # Each resolved fight_id (1, 2, 3, 4) has exactly 2 fight_history
    # rows. The 5th fight_id (5) is unresolved — it should have 0
    # fight_history rows.
    for fid in case_a_resolved_fight_ids:
        n = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fight_id = ?",
            (fid,),
        ).fetchone()[0]
        results.append((
            "G",
            f"fight_id={fid} has exactly 2 fight_history rows",
            n == 2,
            f"got={n}",
        ))

    # Assert fighter_career counters for AC fighters (1 and 2) match
    # their fight_history row counts. Each fighter appears in all 4
    # resolved fights, so each should have 4 fight_history rows.
    for fighter_id in (A_ID, B_ID):
        fc = conn.execute(
            "SELECT record_wins, record_losses, record_draws "
            "FROM fighter_career WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        career_sum = fc[0] + fc[1] + fc[2]
        fh_rows = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()[0]
        results.append((
            "G",
            f"fighter {fighter_id}: career sum ({career_sum}) matches "
            f"fight_history rows ({fh_rows})",
            career_sum == fh_rows,
            f"wins={fc[0]}, losses={fc[1]}, draws={fc[2]}, fh_rows={fh_rows}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Print summary table.
    # ----------------------------------------------------------------
    print("\n" + sep)
    print(f"{'Case':<6} {'Check':<72} {'Result':<8} Detail")
    print("-" * 120)
    n_pass = 0
    n_fail = 0
    by_case = {}
    for case, name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        else:
            n_fail += 1
        by_case.setdefault(case, {"pass": 0, "fail": 0})
        if passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 50:
            detail_str = detail_str[:47] + "..."
        print(f"{case:<6} {name:<72} {status:<8} {detail_str}")
    print(sep)
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print(sep)
    print("By case:")
    for case in sorted(by_case.keys()):
        c = by_case[case]
        print(f"  Case {case}: {c['pass']} PASS, {c['fail']} FAIL")
    print(sep)

    overall_pass = n_fail == 0
    if overall_pass:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
