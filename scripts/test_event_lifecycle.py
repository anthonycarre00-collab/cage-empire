#!/usr/bin/env python3
"""Acceptance test for Task ID 7 — event lifecycle transitions.

This script:
  1. Builds a fresh DB (drop + rebuild + seed).
  2. Test case A — Single-fight event goes scheduled -> completed:
     - The seeded event (Alpha Combat: Test Night, 2026-08-15) has
       exactly 1 fight.
     - Before resolution: assert events.status == 'scheduled'.
     - Call app.resolve_next_fight(conn), commit.
     - After resolution: assert events.status == 'completed'.
     - Assert events.event_date is unchanged (still '2026-08-15').
  3. Test case B — Multi-fight event goes
     scheduled -> in_progress -> in_progress -> completed:
     - Build a fresh DB again so the seeded fight is unresolved.
     - Add 2 more fights to the same event (3 fights total) via the
       `add_extra_fight()` helper.
     - Before any resolution: assert events.status == 'scheduled'.
     - Resolve fight 1: assert events.status == 'in_progress'
       (2 unresolved fights remaining).
     - Resolve fight 2: assert events.status == 'in_progress'
       (1 unresolved fight remaining).
     - Resolve fight 3: assert events.status == 'completed'
       (0 unresolved fights remaining).
  4. Test case C — Already-completed event is not modified
     (defensive clause):
     - Continuing from case B (event is 'completed'), call
       _update_event_status_after_resolution(conn, event_id) directly.
     - Assert events.status is still 'completed'.
  5. Test case D — Non-existent event_id is a no-op:
     - Call _update_event_status_after_resolution(conn, 99999).
     - Assert no exception is raised.
     - Assert the row count of events is unchanged.
  6. Test case E — Regression: fight_history still works:
     - Continuing from case B, assert fight_history has 6 rows
       (2 per fight x 3 fights).
     - Assert fighter_career.record_wins + record_losses + record_draws
       for each fighter (1 and 2) matches their fight_history row count.
  7. Prints a PASS/FAIL summary table.
  8. Exits 0 = all PASS, 1 = any FAIL.

Run from the project root:
    python3 scripts/test_event_lifecycle.py

The script only rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.

Reproducibility note (mirrors `test_fight_resolver.py` and
`test_fight_history.py`):
  `random.seed(42)` is set before each `app.resolve_next_fight()` call
  so the test is reproducible. The seed does not weaken the test — if
  the resolver's logic or the event lifecycle code changes, the same
  seed produces a different sequence of outcomes and the assertions
  catch the regression. The seed only pins down which random draws the
  resolver sees, not what it does with them.
"""
import random
import sqlite3
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)

# Make src/ importable so we can call resolve_next_fight() and
# _update_event_status_after_resolution() directly without going
# through the Tkinter UI.
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

# Seeded event values from src/seed_data.py — used for assertions.
SEEDED_EVENT_NAME = "Alpha Combat: Test Night"
SEEDED_EVENT_DATE = "2026-08-15"

# Non-existent event_id used by case D — never assigned by AUTOINCREMENT
# in a freshly-seeded DB (only event_id=1 exists after seed).
NONEXISTENT_EVENT_ID = 99999


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

    Helper for case B — adds a 'prelim' bout to the seeded event so
    we can test the in_progress transition (which requires more than
    1 fight on the card). The fight_participants UNIQUE constraint is
    on (fight_id, fighter_id), NOT on corner — so two different
    fight_ids can both have fighter 1 in the red corner, which is
    exactly what we want for the multi-fight test.

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


def main():
    sep = "=" * 80
    print(sep)
    print("TASK 7 EVENT LIFECYCLE ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail).
    results = []

    # ----------------------------------------------------------------
    # Test case A — Single-fight event goes scheduled -> completed.
    # ----------------------------------------------------------------
    print("\n--- Case A: single-fight event -> scheduled -> completed ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Verify the seeded event exists and has exactly 1 fight.
    seeded = conn.execute(
        "SELECT event_id, event_name, event_date, status FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    results.append((
        "A",
        "seeded event exists",
        seeded is not None,
        f"row={seeded}",
    ))
    event_id_a, event_name_a, event_date_a, status_a_before = seeded
    results.append((
        "A",
        "seeded event_name == 'Alpha Combat: Test Night'",
        event_name_a == SEEDED_EVENT_NAME,
        f"got={event_name_a!r}",
    ))
    results.append((
        "A",
        "seeded event_date == '2026-08-15'",
        event_date_a == SEEDED_EVENT_DATE,
        f"got={event_date_a!r}",
    ))
    results.append((
        "A",
        "events.status == 'scheduled' before resolution",
        status_a_before == "scheduled",
        f"got={status_a_before!r}",
    ))

    n_fights_a = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=?", (event_id_a,)
    ).fetchone()[0]
    results.append((
        "A",
        "seeded event has exactly 1 fight",
        n_fights_a == 1,
        f"got={n_fights_a}",
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

    status_a_after = conn.execute(
        "SELECT status FROM events WHERE event_id=?", (event_id_a,)
    ).fetchone()[0]
    results.append((
        "A",
        "events.status == 'completed' after resolution (1-fight event)",
        status_a_after == "completed",
        f"got={status_a_after!r}",
    ))

    # Assert event_date is unchanged after completion.
    event_date_a_after = conn.execute(
        "SELECT event_date FROM events WHERE event_id=?", (event_id_a,)
    ).fetchone()[0]
    results.append((
        "A",
        "events.event_date unchanged after completion (still '2026-08-15')",
        event_date_a_after == SEEDED_EVENT_DATE,
        f"got={event_date_a_after!r}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case B — Multi-fight event goes
    #   scheduled -> in_progress -> in_progress -> completed.
    # ----------------------------------------------------------------
    print("\n--- Case B: multi-fight event -> scheduled -> in_progress"
          " -> in_progress -> completed ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    seeded = conn.execute(
        "SELECT event_id, event_date, status FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    event_id_b, event_date_b, status_b_before = seeded

    # Verify starting state.
    results.append((
        "B",
        "events.status == 'scheduled' before any resolution",
        status_b_before == "scheduled",
        f"got={status_b_before!r}",
    ))

    # Add 2 more fights to the same event so it has 3 fights total.
    # The seeded fight has weight_class_id — read it from fight_id=1.
    seeded_fight = conn.execute(
        "SELECT weight_class_id FROM fights WHERE event_id=? ORDER BY fight_id LIMIT 1",
        (event_id_b,),
    ).fetchone()
    weight_class_id_b = seeded_fight[0]

    extra_fight_id_1 = add_extra_fight(conn, event_id_b, weight_class_id_b, A_ID, B_ID)
    extra_fight_id_2 = add_extra_fight(conn, event_id_b, weight_class_id_b, A_ID, B_ID)
    conn.commit()

    n_fights_b = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=?", (event_id_b,)
    ).fetchone()[0]
    results.append((
        "B",
        "event has exactly 3 fights after adding 2 extras",
        n_fights_b == 3,
        f"got={n_fights_b}",
    ))

    n_unresolved_b = conn.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE event_id=? AND winner_fighter_id IS NULL AND result_type IS NULL",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "event has 3 unresolved fights before any resolution",
        n_unresolved_b == 3,
        f"got={n_unresolved_b}",
    ))

    # Resolve fight 1 (lowest fight_id first per the pick-query).
    # Expected: 2 unresolved fights remaining -> status='in_progress'.
    random.seed(RANDOM_SEED)
    resolved_b1 = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "B",
        "resolution 1 returned a fight_id",
        resolved_b1 is not None,
        f"fight_id={resolved_b1}",
    ))
    status_b_after_1 = conn.execute(
        "SELECT status FROM events WHERE event_id=?", (event_id_b,)
    ).fetchone()[0]
    results.append((
        "B",
        "events.status == 'in_progress' after resolving fight 1 of 3",
        status_b_after_1 == "in_progress",
        f"got={status_b_after_1!r}",
    ))
    n_unresolved_b_after_1 = conn.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE event_id=? AND winner_fighter_id IS NULL AND result_type IS NULL",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "2 unresolved fights remaining after resolution 1",
        n_unresolved_b_after_1 == 2,
        f"got={n_unresolved_b_after_1}",
    ))

    # Resolve fight 2. Expected: 1 unresolved fight remaining -> still 'in_progress'.
    resolved_b2 = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "B",
        "resolution 2 returned a fight_id",
        resolved_b2 is not None,
        f"fight_id={resolved_b2}",
    ))
    status_b_after_2 = conn.execute(
        "SELECT status FROM events WHERE event_id=?", (event_id_b,)
    ).fetchone()[0]
    results.append((
        "B",
        "events.status == 'in_progress' after resolving fight 2 of 3",
        status_b_after_2 == "in_progress",
        f"got={status_b_after_2!r}",
    ))
    n_unresolved_b_after_2 = conn.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE event_id=? AND winner_fighter_id IS NULL AND result_type IS NULL",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "1 unresolved fight remaining after resolution 2",
        n_unresolved_b_after_2 == 1,
        f"got={n_unresolved_b_after_2}",
    ))

    # Resolve fight 3. Expected: 0 unresolved fights remaining -> 'completed'.
    resolved_b3 = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "B",
        "resolution 3 returned a fight_id",
        resolved_b3 is not None,
        f"fight_id={resolved_b3}",
    ))
    status_b_after_3 = conn.execute(
        "SELECT status FROM events WHERE event_id=?", (event_id_b,)
    ).fetchone()[0]
    results.append((
        "B",
        "events.status == 'completed' after resolving fight 3 of 3",
        status_b_after_3 == "completed",
        f"got={status_b_after_3!r}",
    ))
    n_unresolved_b_after_3 = conn.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE event_id=? AND winner_fighter_id IS NULL AND result_type IS NULL",
        (event_id_b,),
    ).fetchone()[0]
    results.append((
        "B",
        "0 unresolved fights remaining after resolution 3",
        n_unresolved_b_after_3 == 0,
        f"got={n_unresolved_b_after_3}",
    ))

    # Sanity check: the three resolved fight_ids should be distinct and
    # ascending (pick-query is ORDER BY f.fight_id LIMIT 1).
    fight_ids_resolved = [resolved_b1, resolved_b2, resolved_b3]
    results.append((
        "B",
        "resolved 3 distinct fight_ids in ascending order",
        len(set(fight_ids_resolved)) == 3 and fight_ids_resolved == sorted(fight_ids_resolved),
        f"got={fight_ids_resolved}",
    ))

    # ----------------------------------------------------------------
    # Test case C — Already-completed event is not modified
    # (defensive WHERE status != 'completed' clause).
    # Continuing from case B's DB — the event is now 'completed'.
    # ----------------------------------------------------------------
    print("\n--- Case C: already-completed event is not modified ---")

    # Capture state before the direct call.
    status_c_before = conn.execute(
        "SELECT status, updated_at FROM events WHERE event_id=?", (event_id_b,)
    ).fetchone()
    status_c_before_value, updated_at_c_before = status_c_before

    # Call the helper directly. The defensive WHERE clause should make
    # this a no-op even though it would otherwise set status='completed'
    # again (which is the same value — but the UPDATE matches 0 rows
    # because of the WHERE status != 'completed' clause).
    app._update_event_status_after_resolution(conn, event_id_b)
    conn.commit()

    status_c_after = conn.execute(
        "SELECT status, updated_at FROM events WHERE event_id=?", (event_id_b,)
    ).fetchone()
    status_c_after_value, updated_at_c_after = status_c_after

    results.append((
        "C",
        "events.status still 'completed' after direct helper call",
        status_c_after_value == "completed",
        f"got={status_c_after_value!r}",
    ))
    # The defensive WHERE clause means the UPDATE matched 0 rows, so
    # updated_at should NOT have changed. This is the strongest check
    # that the defensive clause actually fired.
    results.append((
        "C",
        "events.updated_at unchanged (defensive UPDATE matched 0 rows)",
        updated_at_c_after == updated_at_c_before,
        f"before={updated_at_c_before!r}, after={updated_at_c_after!r}",
    ))

    # ----------------------------------------------------------------
    # Test case D — Non-existent event_id is a no-op.
    # ----------------------------------------------------------------
    print("\n--- Case D: non-existent event_id is a no-op ---")

    # Capture event count before the call.
    events_count_d_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # Call the helper with a non-existent event_id. No exception should
    # be raised — the UPDATE simply matches 0 rows.
    no_exception_d = True
    try:
        app._update_event_status_after_resolution(conn, NONEXISTENT_EVENT_ID)
        conn.commit()
    except Exception as e:
        no_exception_d = False
        exc_detail_d = f"{type(e).__name__}: {e}"
    else:
        exc_detail_d = "no exception raised"

    results.append((
        "D",
        f"helper called with event_id={NONEXISTENT_EVENT_ID} raised no exception",
        no_exception_d,
        exc_detail_d,
    ))

    events_count_d_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "D",
        "events row count unchanged after non-existent event_id call",
        events_count_d_after == events_count_d_before,
        f"before={events_count_d_before}, after={events_count_d_after}",
    ))

    # ----------------------------------------------------------------
    # Test case E — Regression: fight_history still works.
    # Continuing from case B's DB — 3 fights resolved, event completed.
    # ----------------------------------------------------------------
    print("\n--- Case E: regression — fight_history still works ---")

    # fight_history should have 6 rows total (2 per fight x 3 fights).
    total_fh_e = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    results.append((
        "E",
        "fight_history has 6 rows total (2 per fight x 3 fights)",
        total_fh_e == 6,
        f"got={total_fh_e}",
    ))

    # Each fight should have exactly 2 fight_history rows.
    for fid in (resolved_b1, resolved_b2, resolved_b3):
        n = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fight_id=?", (fid,)
        ).fetchone()[0]
        results.append((
            "E",
            f"fight_id={fid} has exactly 2 fight_history rows",
            n == 2,
            f"got={n}",
        ))

    # Assert fighter_career.record_wins + record_losses + record_draws
    # for each fighter (1 and 2) matches their fight_history row count.
    # Fighters 1 and 2 are the only fighters on this event — each
    # appears in all 3 fights, so each should have 3 fight_history rows.
    for fighter_id in (A_ID, B_ID):
        fc = conn.execute(
            "SELECT record_wins, record_losses, record_draws "
            "FROM fighter_career WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        career_sum = fc[0] + fc[1] + fc[2]
        fh_rows = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()[0]
        results.append((
            "E",
            f"fighter {fighter_id}: career sum ({career_sum}) matches fight_history rows ({fh_rows})",
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
    for case, name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        else:
            n_fail += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 50:
            detail_str = detail_str[:47] + "..."
        print(f"{case:<6} {name:<72} {status:<8} {detail_str}")
    print(sep)
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
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
