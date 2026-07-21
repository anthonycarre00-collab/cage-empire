#!/usr/bin/env python3
"""Acceptance test for Task ID 4 — fight_history table.

This script:
  1.  Builds a fresh DB (drop + rebuild + seed).
  2.  Verifies the `fight_history` table exists and that
      `schema_meta.schema_version == '1.3.0'`.
  3.  Jacks fighter A (id=1, John Vale) up to all-90 attributes +
      personality so A wins reliably — step 6 of the brief requires the
      first resolution to produce a non-draw (win + loss), and with
      default 50/50 fighters a draw is ~12% likely on any one shot.
  4.  Resolves the seeded fight (fight_id=1) via `app.resolve_next_fight`.
  5.  Asserts `fight_history` has exactly 2 rows for fight_id=1.
  6.  Asserts one row has outcome='win' and the other has outcome='loss'.
  7.  Asserts the winner's row has fighter_id=winner_fighter_id and
      opponent_id=loser_fighter_id (and symmetric for the loser's row).
  8.  Asserts score_margin, result_type, finish_round, finish_time,
      event_id, event_date, weight_class_id are all non-NULL on both
      rows. Also asserts title_at_stake=0 on both rows (placeholder for
      Task ID 11).
  9.  Asserts `fighter_career.record_wins + record_losses + record_draws`
      for each fighter matches their `fight_history` row count for that
      fight (1 each).
  10. Re-resolves 4 more times via a `reset_fight()` helper that creates
      a NEW fight_id each time (see helper docstring for why — the
      UNIQUE (fight_id, fighter_id) constraint on `fight_history` makes
      re-resolving the same fight_id impossible). After 5 total
      resolutions:
      - Asserts `fight_history` has exactly 10 rows total (2 × 5).
      - Asserts `fighter_career` counters for fighters 1 + 2 sum to 10.
  11. Draw path: sets both fighters' attributes AND personality to
      identical 50/50 values (maximises draw probability), re-seeds the
      RNG to 42, and re-resolves up to 20 times until a draw occurs.
      When a draw occurs:
      - Asserts both `fight_history` rows for that fight have
        outcome='draw'.
      - Asserts `fighter_career.record_draws` incremented for both
        fighters.
      If no draw occurs in 20 tries, prints a warning and skips the
      draw-path assertions (the rest of the test must still pass).
  12. Prints a PASS/FAIL summary table.
  13. Exits 0 = PASS, 1 = FAIL.

Run from the project root:
    python3 scripts/test_fight_history.py

The script only rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.

Reproducibility note (mirrors `test_fight_resolver.py`):
  `random.seed(42)` is set before the step-4 resolution loop AND before
  the step-11 draw loop. The seed does not weaken the test — if the
  resolver's logic or the fight_history writes change, the same seed
  produces a different sequence of outcomes and the assertions catch
  the regression. The seed only pins down which random draws the
  resolver sees, not what it does with them.
"""
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call resolve_next_fight() directly
# without going through the Tkinter UI.
sys.path.insert(0, str(SRC_DIR))

# Importing app.py pulls in tkinter. The import itself does not require
# a display (only tk.Tk() does), so this is safe in headless contexts.
import app  # noqa: E402
import build_db  # noqa: E402

# Dynamic schema version + migration name (Task ID 9 supervisor fix).
# Reading these from build_db means this test does not need to be
# updated on every schema version bump. The migration name follows
# the convention v{MAJOR}_{MINOR}_{PATCH}_{desc} - we only check
# that the current version's migration is recorded, not the specific
# description string.
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

N_TOTAL_RESOLUTIONS = 5                # 1 initial + 4 re-resolutions
N_TOTAL_FIGHT_HISTORY_ROWS = 10        # 2 rows per fight × 5 fights
MAX_DRAW_TRIES = 20

# Fighter IDs assigned by seed_data.py (Alpha Combat's two fighters).
# John "Hammer" Vale = 1 (red corner), Marcus "Voltage" Reed = 2 (blue).
A_ID = 1
B_ID = 2


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


def reset_fight(conn, old_fight_id):
    """Schedule a new unresolved fight with the same matchup as `old_fight_id`.

    Adapted from `scripts/test_fight_resolver.py`'s `reset_fight()`. The
    original resets the existing `fights` row so the same `fight_id` can
    be re-resolved. That approach does NOT work for `fight_history`
    testing: the `UNIQUE (fight_id, fighter_id)` constraint on
    `fight_history` means re-resolving the same `fight_id` would either
    crash (regular `INSERT`) or no-op (`INSERT OR IGNORE` / `INSERT OR
    REPLACE`). To accumulate 2 NEW `fight_history` rows per resolution
    (required by the brief's "10 rows total after 5 fights" assertion),
    we need a NEW `fight_id` each time.

    This helper:
      1. Reads the old fight's `event_id`, `weight_class_id`,
         `bout_type`, `round_limit`, `scheduled_rounds`, and its 2
         participants (`fighter_id`, `corner`).
      2. Inserts a NEW `fights` row (AUTOINCREMENT assigns a new
         `fight_id`).
      3. Inserts NEW `fight_participants` rows for the new `fight_id`.
      4. Does NOT touch `fighter_career` (counters accumulate across
         resolutions — this is intentional, per the brief).
      5. Does NOT delete the old `fights` row (its `fight_history` rows
         must survive for the cumulative row-count assertions; the old
         `fights` row already has `result_type` set so it will not be
         re-picked by `resolve_next_fight`).

    Returns the new `fight_id`.
    """
    old = conn.execute(
        "SELECT event_id, weight_class_id, bout_type, round_limit, scheduled_rounds "
        "FROM fights WHERE fight_id=?",
        (old_fight_id,),
    ).fetchone()
    if old is None:
        raise ValueError(f"fight_id={old_fight_id} not found")
    event_id, wc_id, bout_type, round_limit, scheduled_rounds = old

    parts = conn.execute(
        "SELECT fighter_id, corner FROM fight_participants "
        "WHERE fight_id=? ORDER BY corner",
        (old_fight_id,),
    ).fetchall()
    if len(parts) < 2:
        raise ValueError(f"fight_id={old_fight_id} has fewer than 2 participants")

    new_fight_id = conn.execute(
        "INSERT INTO fights (event_id, weight_class_id, bout_type, "
        "round_limit, scheduled_rounds) VALUES (?, ?, ?, ?, ?)",
        (event_id, wc_id, bout_type, round_limit, scheduled_rounds),
    ).lastrowid

    for fighter_id, corner in parts:
        conn.execute(
            "INSERT INTO fight_participants (fight_id, fighter_id, corner) "
            "VALUES (?, ?, ?)",
            (new_fight_id, fighter_id, corner),
        )

    conn.commit()
    return new_fight_id


def main():
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    sep = "=" * 80
    print(sep)
    print("TASK 4 FIGHT_HISTORY ACCEPTANCE TEST")
    print(sep)

    # Two buckets: fatal checks (must pass) and draw-path checks (only
    # fatal if a draw actually occurs — see step 11 / module docstring).
    fatal_results = []      # list of (name, passed, detail)
    draw_path_results = []  # list of (name, passed, detail)
    draw_path_skipped = False

    # ----------------------------------------------------------------
    # Step 2: verify fight_history table exists.
    # ----------------------------------------------------------------
    fh_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='fight_history'"
    ).fetchone()[0]
    fatal_results.append((
        "fight_history table exists",
        fh_count == 1,
        f"found={fh_count}",
    ))

    # ----------------------------------------------------------------
    # Step 3: verify schema_meta.schema_version matches the code's
    # current CODE_SCHEMA_VERSION (dynamic, Task ID 9 supervisor fix).
    # ----------------------------------------------------------------
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    sv_ok = sv is not None and sv[0] == EXPECTED_CODE_VERSION
    fatal_results.append((
        f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
        sv_ok,
        f"got={sv[0] if sv else None}",
    ))

    # Also verify the migration name is recorded. We check that SOME
    # migration is recorded (the current version's), without hardcoding
    # the description suffix (which changes per task: _add_fight_history,
    # _add_contracts, etc.).
    expected_migration_prefix = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (expected_migration_prefix + "%",),
    ).fetchone()
    fatal_results.append((
        f"migration starting with '{expected_migration_prefix}' recorded",
        mig is not None,
        f"found={mig}",
    ))

    # ----------------------------------------------------------------
    # Step 4 prep: jack fighter A (id=1) up to all-90 attributes +
    # personality so A wins reliably. With default 50/50 fighters, the
    # first resolution has ~12% chance of being a draw, which would
    # fail step 6's win/loss assertion. Jacking A to all-90 (vs B at
    # default 50) makes A win ~99.4% of the time — well above the
    # threshold for a deterministic test.
    # ----------------------------------------------------------------
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=90, cardio=90, fight_iq=90, chin=90, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (A_ID,),
    )
    conn.execute(
        "UPDATE fighter_personality SET aggression=90, composure=90, morale=90, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()

    # ----------------------------------------------------------------
    # Step 4: resolve the seeded fight (seed=42 for reproducibility).
    # ----------------------------------------------------------------
    random.seed(RANDOM_SEED)
    first_fight_id = app.resolve_next_fight(conn)
    conn.commit()
    fatal_results.append((
        "first resolution returned a fight_id",
        first_fight_id is not None,
        f"fight_id={first_fight_id}",
    ))

    # ----------------------------------------------------------------
    # Step 5: assert fight_history has exactly 2 rows for this fight.
    # ----------------------------------------------------------------
    row_count = conn.execute(
        "SELECT COUNT(*) FROM fight_history WHERE fight_id=?",
        (first_fight_id,),
    ).fetchone()[0]
    fatal_results.append((
        f"fight_history has 2 rows for fight_id={first_fight_id}",
        row_count == 2,
        f"got={row_count}",
    ))

    # ----------------------------------------------------------------
    # Step 6: assert one row has outcome='win' and the other 'loss'.
    # ----------------------------------------------------------------
    outcomes = [r[0] for r in conn.execute(
        "SELECT outcome FROM fight_history WHERE fight_id=? ORDER BY fighter_id",
        (first_fight_id,),
    ).fetchall()]
    win_loss_ok = sorted(outcomes) == ["loss", "win"]
    fatal_results.append((
        "one row outcome='win', one row outcome='loss'",
        win_loss_ok,
        f"outcomes={outcomes}",
    ))

    # ----------------------------------------------------------------
    # Step 7: assert winner's row has fighter_id=winner, opponent_id=loser
    # (and symmetric for the loser's row).
    # ----------------------------------------------------------------
    fights_row = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type, finish_round, finish_time "
        "FROM fights WHERE fight_id=?",
        (first_fight_id,),
    ).fetchone()
    winner_id, loser_id, result_type, finish_round, finish_time = fights_row

    winner_fh = conn.execute(
        "SELECT fighter_id, opponent_id, outcome FROM fight_history "
        "WHERE fight_id=? AND outcome='win'",
        (first_fight_id,),
    ).fetchone()
    loser_fh = conn.execute(
        "SELECT fighter_id, opponent_id, outcome FROM fight_history "
        "WHERE fight_id=? AND outcome='loss'",
        (first_fight_id,),
    ).fetchone()
    winner_ok = (
        winner_fh is not None
        and winner_fh[0] == winner_id
        and winner_fh[1] == loser_id
    )
    loser_ok = (
        loser_fh is not None
        and loser_fh[0] == loser_id
        and loser_fh[1] == winner_id
    )
    fatal_results.append((
        "winner row: fighter_id=winner, opponent_id=loser",
        winner_ok,
        f"expected fighter_id={winner_id}, opponent_id={loser_id}; got={winner_fh}",
    ))
    fatal_results.append((
        "loser row: fighter_id=loser, opponent_id=winner",
        loser_ok,
        f"expected fighter_id={loser_id}, opponent_id={winner_id}; got={loser_fh}",
    ))

    # ----------------------------------------------------------------
    # Step 8: assert score_margin, result_type, finish_round, finish_time,
    # event_id, event_date, weight_class_id are all non-NULL on both rows.
    # Also assert title_at_stake=0 (placeholder for Task ID 11).
    # ----------------------------------------------------------------
    cols_to_check = [
        "score_margin", "result_type", "finish_round", "finish_time",
        "event_id", "event_date", "weight_class_id",
    ]
    rows = conn.execute(
        "SELECT score_margin, result_type, finish_round, finish_time, "
        "event_id, event_date, weight_class_id FROM fight_history "
        "WHERE fight_id=?",
        (first_fight_id,),
    ).fetchall()
    all_non_null = len(rows) == 2 and all(v is not None for r in rows for v in r)
    fatal_results.append((
        f"all 7 columns non-NULL on both rows ({', '.join(cols_to_check)})",
        all_non_null,
        f"rows={rows}",
    ))

    title_vals = [r[0] for r in conn.execute(
        "SELECT title_at_stake FROM fight_history WHERE fight_id=?",
        (first_fight_id,),
    ).fetchall()]
    # Task ID 11 supervisor fix: the seeded main event is now a title fight
    # (bout_type='title_fight'), so fight_history rows get title_at_stake=1.
    # The original "title_at_stake=0 placeholder" assertion was correct for
    # Tasks 4-10 (before titles existed) but is now stale. This is the same
    # pattern as the dynamic-version fixes in Tasks 9 and 10's sign-offs.
    fatal_results.append((
        "title_at_stake=1 on both rows (seeded fight is a title_fight since Task 11)",
        title_vals == [1, 1],
        f"got={title_vals}",
    ))

    # ----------------------------------------------------------------
    # Step 9: assert fighter_career counters match fight_history row
    # count for each fighter (for this fight, each fighter has 1 row).
    # ----------------------------------------------------------------
    for fid in (A_ID, B_ID):
        fc = conn.execute(
            "SELECT record_wins, record_losses, record_draws "
            "FROM fighter_career WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        career_sum = fc[0] + fc[1] + fc[2]
        fh_rows = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fighter_id=? AND fight_id=?",
            (fid, first_fight_id),
        ).fetchone()[0]
        fatal_results.append((
            f"fighter {fid}: career sum ({career_sum}) matches fight_history rows ({fh_rows})",
            career_sum == fh_rows,
            f"wins={fc[0]}, losses={fc[1]}, draws={fc[2]}, fh_rows={fh_rows}",
        ))

    # ----------------------------------------------------------------
    # Step 10: re-resolve 4 more times. reset_fight() creates a new
    # fight_id each time so fight_history can accumulate (see helper
    # docstring for the rationale).
    # ----------------------------------------------------------------
    current_fight_id = first_fight_id
    for i in range(4):
        current_fight_id = reset_fight(conn, current_fight_id)
        resolved = app.resolve_next_fight(conn)
        conn.commit()
        ok = resolved is not None
        fatal_results.append((
            f"re-resolution {i + 2}/5 returned a fight_id",
            ok,
            f"fight_id={resolved}",
        ))
        if not ok:
            break

    # After 5 total resolutions: fight_history should have 10 rows.
    total_fh = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    fatal_results.append((
        f"fight_history has {N_TOTAL_FIGHT_HISTORY_ROWS} rows total after 5 resolutions",
        total_fh == N_TOTAL_FIGHT_HISTORY_ROWS,
        f"got={total_fh}",
    ))

    # fighter_career counters for fighters 1 + 2 sum to 10.
    fc_a = conn.execute(
        "SELECT record_wins, record_losses, record_draws FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()
    fc_b = conn.execute(
        "SELECT record_wins, record_losses, record_draws FROM fighter_career WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()
    career_total = (fc_a[0] + fc_a[1] + fc_a[2]) + (fc_b[0] + fc_b[1] + fc_b[2])
    fatal_results.append((
        f"fighter_career counters for fighters {A_ID}+{B_ID} sum to {N_TOTAL_FIGHT_HISTORY_ROWS}",
        career_total == N_TOTAL_FIGHT_HISTORY_ROWS,
        f"A: w={fc_a[0]}, l={fc_a[1]}, d={fc_a[2]}; "
        f"B: w={fc_b[0]}, l={fc_b[1]}, d={fc_b[2]}; sum={career_total}",
    ))

    # ----------------------------------------------------------------
    # Step 11: draw path. Set both fighters' attributes AND personality
    # to identical 50/50 values (maximises draw probability), re-seed
    # RNG=42, and resolve up to 20 times until a draw occurs.
    # ----------------------------------------------------------------
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=50, cardio=50, fight_iq=50, chin=50, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    conn.execute(
        "UPDATE fighter_personality SET aggression=50, composure=50, morale=50, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    conn.commit()

    # Capture record_draws before the draw loop.
    draws_a_before = conn.execute(
        "SELECT record_draws FROM fighter_career WHERE fighter_id=?", (A_ID,)
    ).fetchone()[0]
    draws_b_before = conn.execute(
        "SELECT record_draws FROM fighter_career WHERE fighter_id=?", (B_ID,)
    ).fetchone()[0]

    random.seed(RANDOM_SEED)
    draw_fight_id = None
    draw_loop_fight_id = current_fight_id
    for i in range(MAX_DRAW_TRIES):
        draw_loop_fight_id = reset_fight(conn, draw_loop_fight_id)
        resolved = app.resolve_next_fight(conn)
        conn.commit()
        if resolved is None:
            continue
        row = conn.execute(
            "SELECT result_type FROM fights WHERE fight_id=?", (resolved,)
        ).fetchone()
        if row and row[0] == "draw":
            draw_fight_id = resolved
            break

    if draw_fight_id is None:
        print(f"\nWARNING: no draw occurred in {MAX_DRAW_TRIES} tries — "
              "skipping draw-path assertions (non-fatal per the brief).")
        draw_path_skipped = True
    else:
        # Assert both fight_history rows for the draw fight have outcome='draw'.
        draw_outcomes = [r[0] for r in conn.execute(
            "SELECT outcome FROM fight_history WHERE fight_id=? ORDER BY fighter_id",
            (draw_fight_id,),
        ).fetchall()]
        draw_path_results.append((
            f"draw fight_id={draw_fight_id}: both rows outcome='draw'",
            draw_outcomes == ["draw", "draw"],
            f"outcomes={draw_outcomes}",
        ))

        # Assert fighter_career.record_draws incremented for both fighters.
        draws_a_after = conn.execute(
            "SELECT record_draws FROM fighter_career WHERE fighter_id=?", (A_ID,)
        ).fetchone()[0]
        draws_b_after = conn.execute(
            "SELECT record_draws FROM fighter_career WHERE fighter_id=?", (B_ID,)
        ).fetchone()[0]
        draw_path_results.append((
            f"fighter {A_ID} record_draws incremented",
            draws_a_after > draws_a_before,
            f"before={draws_a_before}, after={draws_a_after}",
        ))
        draw_path_results.append((
            f"fighter {B_ID} record_draws incremented",
            draws_b_after > draws_b_before,
            f"before={draws_b_before}, after={draws_b_after}",
        ))

    # ----------------------------------------------------------------
    # Print summary table.
    # ----------------------------------------------------------------
    print(sep)
    print(f"{'Check':<70} {'Result':<8} Detail")
    print("-" * 120)
    n_pass = 0
    n_fail = 0
    for name, passed, detail in fatal_results + draw_path_results:
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        else:
            n_fail += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 60:
            detail_str = detail_str[:57] + "..."
        print(f"{name:<70} {status:<8} {detail_str}")
    if draw_path_skipped:
        print(f"{'draw-path checks':<70} {'SKIP':<8} no draw in {MAX_DRAW_TRIES} tries")
    print(sep)
    print(f"Passed: {n_pass} / {n_pass + n_fail}"
          + (f" (+ draw-path skipped)" if draw_path_skipped else ""))
    print(sep)

    # Overall: all fatal checks must pass, AND either the draw path was
    # skipped OR all draw-path checks passed.
    fatal_pass = all(r[1] for r in fatal_results)
    draw_path_pass = draw_path_skipped or all(r[1] for r in draw_path_results)
    overall_pass = fatal_pass and draw_path_pass

    if overall_pass:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
