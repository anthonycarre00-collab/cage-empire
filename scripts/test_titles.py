#!/usr/bin/env python3
"""Acceptance test for Task ID 11 — Titles (third Stage 2 task).

Tests the titles system added in Task ID 11:

  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read dynamically — no hardcoded version string).
     - schema_migrations contains a migration starting with 'v1_6_0_'.
     - `titles` table exists with 9 expected columns.
     - CHECK constraints fire on is_vacant=2, title_reigns_count=-1,
       title_defenses_count=-1.
     - UNIQUE constraint fires on duplicate (promotion_id, weight_class_id).
  B. Seed:
     - 2 titles exist (1 AC Lightweight + 1 RFL Lightweight).
     - Both titles are vacant (is_vacant=1, current_champion_fighter_id
       IS NULL).
     - Both titles have title_reigns_count=0, title_defenses_count=0.
     - Seeded main event fight has bout_type='title_fight'.
  C. Vacant title + non-draw → winner becomes champion:
     - Build fresh DB. Set fighter 1 attrs all-90, fighter 2 all-30.
     - Before: AC Lightweight title is vacant.
     - Resolve. After: title NOT vacant, champion=fighter 1,
       champion_since_date='2026-08-15', reigns=1, defenses=0.
     - fight_history rows for this fight have title_at_stake=1.
  D. Held title + champion wins → defense incremented:
     - Build fresh DB. Resolve fight 1 (f1 wins vacant title).
     - Convert auto-scheduled fight 2 to title_fight. Resolve.
     - After: champion still f1, defenses=1, reigns still 1.
  E. Held title + contender wins → title changes hands:
     - Build fresh DB. Resolve fight 1 (f1 wins vacant title).
     - Swap attrs: f1 all-30, f2 all-90. Convert fight 2 to title_fight.
       Resolve. After: champion=f2, champion_since_date=fight 2's date,
       reigns=2, defenses=0.
  F. Held title + draw → champion retains, no defense:
     - Build fresh DB. Resolve fight 1 (f1 wins vacant title).
     - Set both to 50/50. Convert fight 2 to title_fight. Resolve
       repeatedly (rebuilding each time with a different seed) until a
       draw occurs. SKIP if no draw in 20 tries.
     - When draw: champion still f1, defenses still 0, reigns still 1.
  G. Vacant title + draw → stays vacant:
     - Build fresh DB. Set both to 50/50. Resolve fight 1 (seeded
       title_fight). Rebuild + re-resolve with different seeds until a
       draw occurs. SKIP if no draw in 20 tries.
     - When draw: title still vacant, reigns still 0.
  H. Non-title fight → no title change:
     - Build fresh DB. UPDATE seeded fight's bout_type to 'main_event'.
     - Resolve. After: title still vacant.
     - fight_history rows have title_at_stake=0.
  I. _resolve_title_after_fight() callable directly:
     - Call with non-existent fight_id → returns None, no crash.
     - Call with valid fight_id but bout_type='main_event' → None.
     - Call with valid fight_id, bout_type='title_fight', but non-
       existent (promotion_id, weight_class_id) → None (no title row).
  J. Regression: fight_history, rankings, event_lifecycle, event_scheduler,
     contracts all still work. Resolving the seeded title fight:
     - fight_history has 2 new rows with title_at_stake=1.
     - rankings updated (both fighters' fights_count=1, ratings diverged).
     - events.status='completed'.
     - new event auto-scheduled.
     - contracts unchanged.
     - AC Lightweight title has a champion.
  K. UI smoke (optional, SKIP in headless):
     - Try App(). If TclError, SKIP. Else: verify existing tabs work.
       (No new Titles tab in this task.) Destroy app.

Run from the project root:
    python3 scripts/test_titles.py

Exit code 0 = all PASS, 1 = any FAIL (case K SKIP is not a fail).
The script rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each `app.resolve_next_fight()` call
  so the test is reproducible. The seed only pins down which random
  draws the resolver sees, not what it does with them.
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

# Make src/ importable so we can call resolve_next_fight(),
# _resolve_title_after_fight(), and (for case K) construct App()
# directly. Importing app.py pulls in tkinter — the import itself
# does not require a display (only tk.Tk() does), so this is safe
# in headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read dynamically from
# build_db so this test does not need to be updated on every schema
# version bump — same pattern the supervisor applied to
# test_fight_history.py, test_schema_versioning.py, test_contracts.py,
# and test_rankings.py).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py (Alpha Combat's two fighters).
# John "Hammer" Vale = 1 (red corner), Marcus "Voltage" Reed = 2 (blue).
A_ID = 1
B_ID = 2

# Seeded event date from src/seed_data.py — used for assertions.
# HW8.1: the seeded event now follows simulation_clock.current_date
# (was hardcoded "2026-08-15" while the fresh-DB clock started at
# "2026-08-14"). The fresh-DB clock is GAME_START_DATE = "2026-01-01"
# (per build_db.py), so the seeded event is now dated "2026-01-01".
SEEDED_EVENT_DATE = "2026-01-01"

# Auto-scheduled next event is 4 weeks after the seeded event.
# 2026-01-01 + 28 days = 2026-01-29.
AUTO_SCHEDULED_EVENT_DATE = "2026-01-29"


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_rankings.py / test_contracts.py /
    test_event_scheduler.py so all tests share the same setup contract:
    a fresh DB with 2 promotions (Alpha Combat + Rival Fight League),
    5 fighters (2 AC + 3 RFL), 1 staff member (Nina Cross), 1 event,
    1 title_fight (the seeded main event, changed in Task 11 from
    'main_event' to 'title_fight'), 6 contracts (5 fighter + 1 staff),
    5 rankings rows (all at 1000.0), 2 titles (both vacant — AC
    Lightweight + RFL Lightweight).
    """
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


def get_promotion_id(conn, name):
    """Look up a promotion_id by name. Raises if the promotion is missing."""
    row = conn.execute(
        "SELECT promotion_id FROM promotions WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"promotion {name!r} not found in seeded DB")
    return row[0]


def get_weight_class_id(conn, name="Lightweight"):
    """Look up a weight_class_id by name. Raises if missing."""
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"weight_class {name!r} not found in seeded DB")
    return row[0]


def set_fighter_attrs(conn, fighter_id, attr_val, pers_val):
    """Set all 4 attributes and all 3 personality traits to the given values."""
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=?, cardio=?, fight_iq=?, "
        "chin=?, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (attr_val, attr_val, attr_val, attr_val, fighter_id),
    )
    conn.execute(
        "UPDATE fighter_personality SET aggression=?, composure=?, morale=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (pers_val, pers_val, pers_val, fighter_id),
    )


def get_title_row(conn, promotion_id, weight_class_id):
    """Fetch the title row for (promotion_id, weight_class_id).

    Returns (title_id, current_champion_fighter_id, champion_since_date,
    title_reigns_count, title_defenses_count, is_vacant) or None.
    """
    return conn.execute(
        "SELECT title_id, current_champion_fighter_id, champion_since_date, "
        "title_reigns_count, title_defenses_count, is_vacant "
        "FROM titles WHERE promotion_id=? AND weight_class_id=?",
        (promotion_id, weight_class_id),
    ).fetchone()


def convert_next_fight_to_title_fight(conn):
    """Find the lowest-fight_id unresolved fight and set its bout_type to
    'title_fight'. Returns the fight_id, or None if no unresolved fight
    was found.

    Used by cases D/E/F to convert the auto-scheduled main_event fight
    (created by schedule_next_event after the first resolve) into a
    title fight so the second resolve exercises the title-defense /
    title-change logic.
    """
    row = conn.execute(
        "SELECT fight_id FROM fights "
        "WHERE winner_fighter_id IS NULL AND result_type IS NULL "
        "ORDER BY fight_id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    fight_id = row[0]
    conn.execute(
        "UPDATE fights SET bout_type='title_fight', is_title_fight=1 WHERE fight_id=?",
        (fight_id,),
    )
    return fight_id


# Lazy import of _tkinter — only needed inside case K's exception
# handler. Wrapped so that if _tkinter itself is unavailable (which
# would imply `import tkinter` already failed at module load time),
# we don't get a NameError on the isinstance() check.
try:
    import _tkinter as _tkinter_mod
    _tkinter_TclError = _tkinter_mod.TclError
except ImportError:
    _tkinter_TclError = type("_MissingTclError", (Exception,), {})


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK 11 TITLES ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail). passed=None means SKIP.
    results = []

    # ----------------------------------------------------------------
    # Build a fresh DB. Used by cases A, B.
    # ----------------------------------------------------------------
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    rfl_id = get_promotion_id(conn, "Rival Fight League")
    wc_id = get_weight_class_id(conn, "Lightweight")

    print(f"Alpha Combat promotion_id   = {alpha_combat_id}")
    print(f"Rival Fight League promo_id = {rfl_id}")
    print(f"Lightweight weight_class_id = {wc_id}")

    # ----------------------------------------------------------------
    # Test case A — Schema.
    # ----------------------------------------------------------------
    print("\n--- Case A: schema ---")

    # schema_meta.schema_version matches the code's current
    # CODE_SCHEMA_VERSION (dynamic, no hardcoding).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        "A",
        f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
        sv is not None and sv[0] == EXPECTED_CODE_VERSION,
        f"got={sv[0] if sv else None}",
    ))

    # migration name starts with 'v1_6_0_' (LIKE prefix check, so the
    # description suffix can change per task: _add_titles, etc.).
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    results.append((
        "A",
        f"migration starting with '{EXPECTED_MIGRATION_PREFIX}' recorded",
        mig is not None,
        f"found={mig}",
    ))

    # `titles` table exists.
    titles_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='titles'"
    ).fetchone()[0]
    results.append((
        "A",
        "titles table exists",
        titles_count == 1,
        f"found={titles_count}",
    ))

    # `titles` table has 9 expected columns.
    expected_cols = {
        "title_id", "promotion_id", "weight_class_id",
        "current_champion_fighter_id", "champion_since_date",
        "title_reigns_count", "title_defenses_count",
        "is_vacant", "created_at", "updated_at",
    }
    actual_cols = {r[1] for r in conn.execute("PRAGMA table_info(titles)").fetchall()}
    results.append((
        "A",
        f"titles has 10 expected columns ({sorted(expected_cols)})",
        actual_cols == expected_cols,
        f"got={sorted(actual_cols)}",
    ))

    # CHECK constraint: is_vacant=2 → IntegrityError.
    try:
        conn.execute(
            "INSERT INTO titles (promotion_id, weight_class_id, is_vacant) "
            "VALUES (?, ?, 2)",
            (alpha_combat_id, wc_id),
        )
        results.append((
            "A",
            "CHECK is_vacant IN (0,1): is_vacant=2 raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "CHECK is_vacant IN (0,1): is_vacant=2 raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK is_vacant IN (0,1): is_vacant=2 raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # CHECK constraint: title_reigns_count=-1 → IntegrityError.
    try:
        conn.execute(
            "INSERT INTO titles (promotion_id, weight_class_id, "
            "title_reigns_count) VALUES (?, ?, -1)",
            (alpha_combat_id, wc_id),
        )
        results.append((
            "A",
            "CHECK title_reigns_count >= 0: -1 raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "CHECK title_reigns_count >= 0: -1 raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK title_reigns_count >= 0: -1 raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # CHECK constraint: title_defenses_count=-1 → IntegrityError.
    try:
        conn.execute(
            "INSERT INTO titles (promotion_id, weight_class_id, "
            "title_defenses_count) VALUES (?, ?, -1)",
            (alpha_combat_id, wc_id),
        )
        results.append((
            "A",
            "CHECK title_defenses_count >= 0: -1 raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "CHECK title_defenses_count >= 0: -1 raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK title_defenses_count >= 0: -1 raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # UNIQUE constraint: duplicate (promotion_id, weight_class_id)
    # → IntegrityError. The seed already created a title for AC
    # Lightweight, so inserting another should fail.
    try:
        conn.execute(
            "INSERT INTO titles (promotion_id, weight_class_id) VALUES (?, ?)",
            (alpha_combat_id, wc_id),
        )
        results.append((
            "A",
            "UNIQUE (promotion_id, weight_class_id): "
            "duplicate raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "UNIQUE (promotion_id, weight_class_id): "
            "duplicate raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "UNIQUE (promotion_id, weight_class_id): "
            "duplicate raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # ----------------------------------------------------------------
    # Test case B — Seed.
    # ----------------------------------------------------------------
    print("\n--- Case B: seed ---")

    # 2 titles exist.
    n_titles = conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
    results.append((
        "B",
        "titles has 2 rows after seed (1 AC + 1 RFL)",
        n_titles == 2,
        f"got={n_titles}",
    ))

    # Both titles are vacant.
    ac_title = get_title_row(conn, alpha_combat_id, wc_id)
    rfl_title = get_title_row(conn, rfl_id, wc_id)
    results.append((
        "B",
        "AC Lightweight title is vacant (is_vacant=1, champion IS NULL)",
        ac_title is not None and ac_title[5] == 1 and ac_title[1] is None,
        f"row={ac_title}",
    ))
    results.append((
        "B",
        "RFL Lightweight title is vacant (is_vacant=1, champion IS NULL)",
        rfl_title is not None and rfl_title[5] == 1 and rfl_title[1] is None,
        f"row={rfl_title}",
    ))

    # Both titles have reigns=0, defenses=0.
    results.append((
        "B",
        "AC title: reigns=0, defenses=0",
        ac_title is not None and ac_title[3] == 0 and ac_title[4] == 0,
        f"reigns={ac_title[3] if ac_title else None}, "
        f"defenses={ac_title[4] if ac_title else None}",
    ))
    results.append((
        "B",
        "RFL title: reigns=0, defenses=0",
        rfl_title is not None and rfl_title[3] == 0 and rfl_title[4] == 0,
        f"reigns={rfl_title[3] if rfl_title else None}, "
        f"defenses={rfl_title[4] if rfl_title else None}",
    ))

    # Seeded main event fight has bout_type='title_fight'.
    seeded_bout_type = conn.execute(
        "SELECT bout_type FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()
    results.append((
        "B",
        "seeded main event has bout_type='title_fight'",
        seeded_bout_type is not None and seeded_bout_type[0] == "title_fight",
        f"got={seeded_bout_type[0] if seeded_bout_type else None}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case C — Vacant title + non-draw → winner becomes champion.
    # ----------------------------------------------------------------
    print("\n--- Case C: vacant title + non-draw → winner becomes champion ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Before: AC Lightweight title is vacant.
    title_before = get_title_row(conn, alpha_combat_id, wc_id)
    results.append((
        "C",
        "before resolve: AC Lightweight title is vacant",
        title_before is not None and title_before[5] == 1
        and title_before[1] is None,
        f"row={title_before}",
    ))

    # Set fighter 1 attrs all-90, fighter 2 attrs all-30. f1 wins reliably.
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    resolved = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "C",
        "resolve_next_fight returned a fight_id",
        resolved is not None,
        f"fight_id={resolved}",
    ))

    # Determine the winner (should be fighter 1 with all-90 vs all-30).
    fight_row = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type "
        "FROM fights WHERE fight_id=?",
        (resolved,),
    ).fetchone()
    fight_winner_id, fight_loser_id, fight_result_type = fight_row
    results.append((
        "C",
        "fight resolved with a non-draw result",
        fight_result_type != "draw" and fight_winner_id is not None,
        f"winner={fight_winner_id}, loser={fight_loser_id}, "
        f"result_type={fight_result_type}",
    ))

    # After: AC Lightweight title is NO LONGER vacant.
    title_after = get_title_row(conn, alpha_combat_id, wc_id)
    results.append((
        "C",
        "after resolve: AC Lightweight title is NO LONGER vacant "
        "(is_vacant=0)",
        title_after is not None and title_after[5] == 0,
        f"is_vacant={title_after[5] if title_after else None}",
    ))

    # current_champion_fighter_id == the winner (fighter 1).
    results.append((
        "C",
        f"current_champion_fighter_id == winner ({fight_winner_id})",
        title_after is not None and title_after[1] == fight_winner_id,
        f"champion={title_after[1] if title_after else None}",
    ))

    # champion_since_date == '2026-08-15' (the seeded event's date).
    results.append((
        "C",
        f"champion_since_date == '{SEEDED_EVENT_DATE}'",
        title_after is not None and title_after[2] == SEEDED_EVENT_DATE,
        f"got={title_after[2] if title_after else None}",
    ))

    # title_reigns_count == 1 (new reign).
    results.append((
        "C",
        "title_reigns_count == 1 (new reign)",
        title_after is not None and title_after[3] == 1,
        f"got={title_after[3] if title_after else None}",
    ))

    # title_defenses_count == 0 (just won it, no defenses yet).
    results.append((
        "C",
        "title_defenses_count == 0 (no defenses yet)",
        title_after is not None and title_after[4] == 0,
        f"got={title_after[4] if title_after else None}",
    ))

    # fight_history rows for this fight have title_at_stake=1 (both rows).
    fh_rows = conn.execute(
        "SELECT fighter_id, title_at_stake FROM fight_history "
        "WHERE fight_id=?",
        (resolved,),
    ).fetchall()
    results.append((
        "C",
        "fight_history rows have title_at_stake=1 (both rows)",
        len(fh_rows) == 2 and all(r[1] == 1 for r in fh_rows),
        f"rows={fh_rows}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case D — Held title + champion wins → defense incremented.
    # ----------------------------------------------------------------
    print("\n--- Case D: held title + champion wins → defense incremented ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Step 1: f1 wins the vacant title (f1 all-90, f2 all-30).
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)  # fight 1: f1 wins vacant title
    conn.commit()

    title_after_f1 = get_title_row(conn, alpha_combat_id, wc_id)
    results.append((
        "D",
        "setup: f1 won the vacant title (champion=f1, reigns=1, defenses=0)",
        title_after_f1 is not None and title_after_f1[1] == A_ID
        and title_after_f1[3] == 1 and title_after_f1[4] == 0,
        f"row={title_after_f1}",
    ))

    # Step 2: convert the auto-scheduled fight 2 (main_event) to a
    # title_fight. The auto-scheduler (Task 8) created fight 2 with
    # f1 vs f2 (the only 2 AC fighters), bout_type='main_event'.
    fight2_id = convert_next_fight_to_title_fight(conn)
    conn.commit()
    results.append((
        "D",
        "converted auto-scheduled fight to title_fight",
        fight2_id is not None,
        f"fight_id={fight2_id}",
    ))

    # Step 3: resolve fight 2. f1 still all-90, so f1 wins (retains).
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()

    title_after_d = get_title_row(conn, alpha_combat_id, wc_id)
    # Champion still f1.
    results.append((
        "D",
        "after defense: champion is still f1 (retained)",
        title_after_d is not None and title_after_d[1] == A_ID,
        f"champion={title_after_d[1] if title_after_d else None}",
    ))
    # title_defenses_count == 1 (one successful defense).
    results.append((
        "D",
        "title_defenses_count == 1 (one successful defense)",
        title_after_d is not None and title_after_d[4] == 1,
        f"got={title_after_d[4] if title_after_d else None}",
    ))
    # title_reigns_count still 1 (same reign).
    results.append((
        "D",
        "title_reigns_count still 1 (same reign)",
        title_after_d is not None and title_after_d[3] == 1,
        f"got={title_after_d[3] if title_after_d else None}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case E — Held title + contender wins → title changes hands.
    # ----------------------------------------------------------------
    print("\n--- Case E: held title + contender wins → title changes hands ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Step 1: f1 wins the vacant title (f1 all-90, f2 all-30).
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)  # fight 1: f1 wins vacant title
    conn.commit()

    title_after_f1_e = get_title_row(conn, alpha_combat_id, wc_id)
    results.append((
        "E",
        "setup: f1 won the vacant title (champion=f1)",
        title_after_f1_e is not None and title_after_f1_e[1] == A_ID,
        f"row={title_after_f1_e}",
    ))

    # Step 2: SWAP attrs — f1 all-30, f2 all-90 — so f2 wins fight 2.
    set_fighter_attrs(conn, A_ID, 30, 30)
    set_fighter_attrs(conn, B_ID, 90, 90)
    conn.commit()

    # Convert the auto-scheduled fight 2 to a title_fight.
    fight2_id_e = convert_next_fight_to_title_fight(conn)
    conn.commit()
    results.append((
        "E",
        "converted auto-scheduled fight to title_fight",
        fight2_id_e is not None,
        f"fight_id={fight2_id_e}",
    ))

    # Step 3: resolve fight 2. f2 all-90, so f2 wins (contender wins).
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()

    # Verify f2 actually won fight 2 (defensive — pick the resolved fight).
    fight2_result = conn.execute(
        "SELECT winner_fighter_id, result_type FROM fights "
        "WHERE result_type IS NOT NULL ORDER BY fight_id DESC LIMIT 1"
    ).fetchone()
    results.append((
        "E",
        "f2 won fight 2 (contender won the title fight)",
        fight2_result is not None and fight2_result[0] == B_ID
        and fight2_result[1] != "draw",
        f"winner={fight2_result[0] if fight2_result else None}, "
        f"result={fight2_result[1] if fight2_result else None}",
    ))

    title_after_e = get_title_row(conn, alpha_combat_id, wc_id)
    # Champion is now f2 (title changed hands).
    results.append((
        "E",
        "after upset: champion is f2 (title changed hands)",
        title_after_e is not None and title_after_e[1] == B_ID,
        f"champion={title_after_e[1] if title_after_e else None}",
    ))
    # champion_since_date == the second fight's date.
    # The auto-scheduled event 2 has event_date = '2026-09-12'.
    fight2_event_date = conn.execute(
        "SELECT e.event_date FROM fights f JOIN events e "
        "ON e.event_id = f.event_id WHERE f.fight_id=?",
        (fight2_id_e,),
    ).fetchone()
    expected_since = fight2_event_date[0] if fight2_event_date else None
    results.append((
        "E",
        f"champion_since_date == fight 2's date ({expected_since})",
        title_after_e is not None and title_after_e[2] == expected_since,
        f"got={title_after_e[2] if title_after_e else None}",
    ))
    # title_reigns_count == 2 (second reign).
    results.append((
        "E",
        "title_reigns_count == 2 (second reign)",
        title_after_e is not None and title_after_e[3] == 2,
        f"got={title_after_e[3] if title_after_e else None}",
    ))
    # title_defenses_count == 0 (new reign, no defenses).
    results.append((
        "E",
        "title_defenses_count == 0 (new reign, no defenses)",
        title_after_e is not None and title_after_e[4] == 0,
        f"got={title_after_e[4] if title_after_e else None}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case F — Held title + draw → champion retains, no defense.
    # ----------------------------------------------------------------
    print("\n--- Case F: held title + draw → champion retains, no defense ---")

    # For case F, we need a draw on a title fight where f1 is the
    # champion. Each attempt: rebuild the DB, resolve fight 1 (f1
    # wins vacant title), convert fight 2 to title_fight, set both
    # to 50/50, resolve fight 2 with a different seed each attempt.
    # If a draw occurs, assert. If no draw in 20 tries, SKIP.
    f_draw_found = False
    f_title_after = None
    for attempt in range(20):
        build_fresh_db()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON;")
        alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
        wc_id = get_weight_class_id(conn, "Lightweight")

        # Setup: f1 wins vacant title.
        set_fighter_attrs(conn, A_ID, 90, 90)
        set_fighter_attrs(conn, B_ID, 30, 30)
        conn.commit()
        random.seed(RANDOM_SEED)
        app.resolve_next_fight(conn)
        conn.commit()

        # Verify setup worked (f1 is champion).
        title_setup = get_title_row(conn, alpha_combat_id, wc_id)
        if title_setup is None or title_setup[1] != A_ID:
            conn.close()
            continue  # setup failed, try again

        # Convert fight 2 to title_fight.
        fight2_id_f = convert_next_fight_to_title_fight(conn)
        if fight2_id_f is None:
            conn.close()
            continue

        # Set both to 50/50 for draw likelihood.
        set_fighter_attrs(conn, A_ID, 50, 50)
        set_fighter_attrs(conn, B_ID, 50, 50)
        conn.commit()

        # Resolve fight 2 with a different seed each attempt.
        random.seed(RANDOM_SEED + attempt)
        app.resolve_next_fight(conn)
        conn.commit()

        # Check if fight 2 was a draw.
        rt = conn.execute(
            "SELECT result_type FROM fights WHERE fight_id=?",
            (fight2_id_f,),
        ).fetchone()
        if rt and rt[0] == "draw":
            f_draw_found = True
            f_title_after = get_title_row(conn, alpha_combat_id, wc_id)
            break
        conn.close()

    if f_draw_found:
        results.append((
            "F",
            f"draw occurred on title fight within 20 tries",
            True,
            f"attempt={attempt}, title_row={f_title_after}",
        ))
        # Champion still f1 (retained).
        results.append((
            "F",
            "after draw: champion is still f1 (retained)",
            f_title_after is not None and f_title_after[1] == A_ID,
            f"champion={f_title_after[1] if f_title_after else None}",
        ))
        # title_defenses_count still 0 (draws don't count as defenses).
        results.append((
            "F",
            "title_defenses_count still 0 (draws don't count as defenses)",
            f_title_after is not None and f_title_after[4] == 0,
            f"got={f_title_after[4] if f_title_after else None}",
        ))
        # title_reigns_count still 1 (same reign).
        results.append((
            "F",
            "title_reigns_count still 1 (same reign)",
            f_title_after is not None and f_title_after[3] == 1,
            f"got={f_title_after[3] if f_title_after else None}",
        ))
        conn.close()
    else:
        print("  SKIP — no draw occurred on a title fight in 20 tries")
        results.append((
            "F",
            "draw occurred on title fight within 20 tries",
            None,  # SKIP
            "no draw in 20 tries",
        ))

    # ----------------------------------------------------------------
    # Test case G — Vacant title + draw → stays vacant.
    # ----------------------------------------------------------------
    print("\n--- Case G: vacant title + draw → stays vacant ---")

    # For case G, we need a draw on the seeded title fight (fight 1)
    # while the title is still vacant. Each attempt: rebuild the DB,
    # set both to 50/50, resolve fight 1 with a different seed.
    # If a draw occurs, assert. If no draw in 20 tries, SKIP.
    g_draw_found = False
    g_title_after = None
    for attempt in range(20):
        build_fresh_db()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON;")
        alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
        wc_id = get_weight_class_id(conn, "Lightweight")

        # Set both to 50/50 for draw likelihood.
        set_fighter_attrs(conn, A_ID, 50, 50)
        set_fighter_attrs(conn, B_ID, 50, 50)
        conn.commit()

        # Resolve fight 1 (the seeded title fight) with a different
        # seed each attempt.
        random.seed(RANDOM_SEED + attempt)
        app.resolve_next_fight(conn)
        conn.commit()

        # Check if fight 1 was a draw.
        rt = conn.execute(
            "SELECT result_type FROM fights WHERE fight_id=1"
        ).fetchone()
        if rt and rt[0] == "draw":
            g_draw_found = True
            g_title_after = get_title_row(conn, alpha_combat_id, wc_id)
            break
        conn.close()

    if g_draw_found:
        results.append((
            "G",
            f"draw occurred on vacant title fight within 20 tries",
            True,
            f"attempt={attempt}, title_row={g_title_after}",
        ))
        # Title still vacant.
        results.append((
            "G",
            "after draw: title still vacant (is_vacant=1, champion IS NULL)",
            g_title_after is not None and g_title_after[5] == 1
            and g_title_after[1] is None,
            f"is_vacant={g_title_after[5] if g_title_after else None}, "
            f"champion={g_title_after[1] if g_title_after else None}",
        ))
        # title_reigns_count still 0.
        results.append((
            "G",
            "title_reigns_count still 0",
            g_title_after is not None and g_title_after[3] == 0,
            f"got={g_title_after[3] if g_title_after else None}",
        ))
        conn.close()
    else:
        print("  SKIP — no draw occurred on the vacant title fight in 20 tries")
        results.append((
            "G",
            "draw occurred on vacant title fight within 20 tries",
            None,  # SKIP
            "no draw in 20 tries",
        ))

    # ----------------------------------------------------------------
    # Test case H — Non-title fight → no title change.
    # ----------------------------------------------------------------
    print("\n--- Case H: non-title fight → no title change ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Change the seeded fight's bout_type to 'main_event' (not 'title_fight').
    conn.execute("UPDATE fights SET bout_type='main_event', is_title_fight=0 WHERE fight_id=1")
    conn.commit()

    # Set f1 all-90 so the resolve is a non-draw.
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()

    # Title still vacant (no change — the fight wasn't a title fight).
    title_after_h = get_title_row(conn, alpha_combat_id, wc_id)
    results.append((
        "H",
        "after non-title fight: title still vacant",
        title_after_h is not None and title_after_h[5] == 1
        and title_after_h[1] is None,
        f"row={title_after_h}",
    ))

    # fight_history rows have title_at_stake=0.
    fh_rows_h = conn.execute(
        "SELECT fighter_id, title_at_stake FROM fight_history WHERE fight_id=1"
    ).fetchall()
    results.append((
        "H",
        "fight_history rows have title_at_stake=0 (non-title fight)",
        len(fh_rows_h) == 2 and all(r[1] == 0 for r in fh_rows_h),
        f"rows={fh_rows_h}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case I — _resolve_title_after_fight() callable directly.
    # ----------------------------------------------------------------
    print("\n--- Case I: _resolve_title_after_fight() callable directly ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # I.1: Call with non-existent fight_id → returns None, no crash.
    try:
        ret = app._resolve_title_after_fight(
            conn,
            fight_id=99999,  # non-existent
            event_id=1,
            winner_id=A_ID,
            loser_id=B_ID,
            weight_class_id=wc_id,
            promotion_id=alpha_combat_id,
            was_draw=False,
            result_type="ko_tko",
            fight_date=SEEDED_EVENT_DATE,
        )
        results.append((
            "I",
            "non-existent fight_id (99999) → returns None, no crash",
            ret is None,
            f"got={ret}",
        ))
    except Exception as e:
        results.append((
            "I",
            "non-existent fight_id (99999) → returns None, no crash",
            False,
            f"crashed: {type(e).__name__}: {e}",
        ))

    # I.2: Call with valid fight_id but bout_type='main_event' → None.
    # Change the seeded fight's bout_type to 'main_event'.
    conn.execute("UPDATE fights SET bout_type='main_event', is_title_fight=0 WHERE fight_id=1")
    conn.commit()
    try:
        ret = app._resolve_title_after_fight(
            conn,
            fight_id=1,  # valid, but bout_type='main_event'
            event_id=1,
            winner_id=A_ID,
            loser_id=B_ID,
            weight_class_id=wc_id,
            promotion_id=alpha_combat_id,
            was_draw=False,
            result_type="ko_tko",
            fight_date=SEEDED_EVENT_DATE,
        )
        results.append((
            "I",
            "valid fight_id, bout_type='main_event' → returns None "
            "(no-op for non-title fights)",
            ret is None,
            f"got={ret}",
        ))
    except Exception as e:
        results.append((
            "I",
            "valid fight_id, bout_type='main_event' → returns None",
            False,
            f"crashed: {type(e).__name__}: {e}",
        ))

    # I.3: Call with valid fight_id, bout_type='title_fight', but
    # non-existent (promotion_id, weight_class_id) → None (no title row).
    # Use a non-existent promotion_id (99999) — no title row exists
    # for that (promotion_id, weight_class_id) combination.
    conn.execute("UPDATE fights SET bout_type='title_fight' WHERE fight_id=1")
    conn.commit()
    try:
        ret = app._resolve_title_after_fight(
            conn,
            fight_id=1,
            event_id=1,
            winner_id=A_ID,
            loser_id=B_ID,
            weight_class_id=wc_id,
            promotion_id=99999,  # non-existent promotion
            was_draw=False,
            result_type="ko_tko",
            fight_date=SEEDED_EVENT_DATE,
        )
        results.append((
            "I",
            "valid fight_id, bout_type='title_fight', non-existent "
            "promotion_id → returns None (no title row)",
            ret is None,
            f"got={ret}",
        ))
    except Exception as e:
        results.append((
            "I",
            "valid fight_id, bout_type='title_fight', non-existent "
            "promotion_id → returns None",
            False,
            f"crashed: {type(e).__name__}: {e}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case J — Regression: fight_history, rankings, event_lifecycle,
    # event_scheduler, contracts all still work. AC Lightweight title
    # has a champion after resolving the seeded title fight.
    # ----------------------------------------------------------------
    print("\n--- Case J: regression (fh + rankings + lifecycle + scheduler "
          "+ contracts + title) ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Jack fighter 1 to all-90 so the resolve produces a non-draw
    # and the title transfers to f1.
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    # Snapshot before resolution.
    fh_before = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    events_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    contracts_before = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    rankings_fights_before = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE fights_count = 0"
    ).fetchone()[0]  # all 5 rows start at fights_count=0
    title_before_j = get_title_row(conn, alpha_combat_id, wc_id)

    random.seed(RANDOM_SEED)
    resolved = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "J",
        "resolve_next_fight returned a fight_id",
        resolved is not None,
        f"fight_id={resolved}",
    ))

    # fight_history has 2 new rows with title_at_stake=1 (Task 4 + 11).
    fh_after = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    fh_title_vals = [r[0] for r in conn.execute(
        "SELECT title_at_stake FROM fight_history WHERE fight_id=?",
        (resolved,),
    ).fetchall()]
    results.append((
        "J",
        "fight_history has 2 new rows with title_at_stake=1 (Task 4 + 11)",
        fh_after - fh_before == 2 and len(fh_title_vals) == 2
        and all(v == 1 for v in fh_title_vals),
        f"fh_delta={fh_after - fh_before}, title_at_stake_vals={fh_title_vals}",
    ))

    # Rankings updated (Task 10) — both fighters' fights_count=1.
    rankings_fights_after = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE fights_count = 0"
    ).fetchone()[0]
    results.append((
        "J",
        "rankings: 2 rows updated (fights_count 0 → 1) (Task 10)",
        rankings_fights_before - rankings_fights_after == 2,
        f"before_fights_0={rankings_fights_before}, "
        f"after_fights_0={rankings_fights_after}",
    ))
    # And both updated rows have rating != 1000.0.
    updated_rankings = conn.execute(
        "SELECT fighter_id, rating FROM rankings "
        "WHERE fights_count > 0 ORDER BY fighter_id"
    ).fetchall()
    results.append((
        "J",
        "the 2 updated rankings rows have rating != 1000.0",
        len(updated_rankings) == 2
        and all(r[1] != 1000.0 for r in updated_rankings),
        f"rows={updated_rankings}",
    ))

    # Seeded event's status is 'completed' (Task 7).
    seeded_status = conn.execute(
        "SELECT status FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    results.append((
        "J",
        "seeded event's status is 'completed' (Task 7)",
        seeded_status is not None and seeded_status[0] == "completed",
        f"got={seeded_status[0] if seeded_status else None}",
    ))

    # A new event was auto-scheduled (Task 8).
    events_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "J",
        "1 new event auto-scheduled (Task 8)",
        events_after - events_before == 1,
        f"before={events_before}, after={events_after}",
    ))

    # Contracts table unchanged (Task 9).
    contracts_after = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    results.append((
        "J",
        "contracts table unchanged (Task 9)",
        contracts_after == contracts_before,
        f"before={contracts_before}, after={contracts_after}",
    ))

    # AC Lightweight title has a champion (Task 11).
    title_after_j = get_title_row(conn, alpha_combat_id, wc_id)
    results.append((
        "J",
        "AC Lightweight title has a champion (Task 11)",
        title_after_j is not None and title_after_j[5] == 0
        and title_after_j[1] is not None,
        f"row={title_after_j}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case K — UI smoke test (optional, SKIPs cleanly in headless).
    # ----------------------------------------------------------------
    print("\n--- Case K: UI smoke test ---")
    k_skipped = False
    build_fresh_db()
    try:
        app_instance = app.App()
    except (_tkinter_TclError, AttributeError) as e:
        print(f"  SKIP — no display available ({type(e).__name__})")
        k_skipped = True
    except Exception as e:
        results.append((
            "K",
            "App() constructs without crashing",
            False,
            f"App() crashed: {type(e).__name__}: {e}",
        ))
        k_skipped = True  # nothing else to test in case K
    else:
        try:
            # Verify the existing tabs still work. No new Titles tab
            # in this task — the brief says "just write the table and
            # the writer for now".
            has_news = hasattr(app_instance, "news")
            has_contracts = hasattr(app_instance, "contracts")
            has_rankings = hasattr(app_instance, "rankings")
            results.append((
                "K",
                "App() has news + contracts + rankings widgets "
                "(existing tabs still work)",
                has_news and has_contracts and has_rankings,
                f"news={has_news}, contracts={has_contracts}, "
                f"rankings={has_rankings}",
            ))
        finally:
            try:
                app_instance.destroy()
            except Exception:
                pass

    # ----------------------------------------------------------------
    # Print summary table.
    # ----------------------------------------------------------------
    print("\n" + sep)
    print(f"{'Case':<6} {'Check':<72} {'Result':<8} Detail")
    print("-" * 120)
    n_pass = 0
    n_fail = 0
    n_skip = 0
    by_case = {}
    for case, name, passed, detail in results:
        if passed is None:
            status = "SKIP"
            n_skip += 1
        elif passed:
            status = "PASS"
            n_pass += 1
        else:
            status = "FAIL"
            n_fail += 1
        by_case.setdefault(case, {"pass": 0, "fail": 0, "skip": 0})
        if passed is None:
            by_case[case]["skip"] += 1
        elif passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 50:
            detail_str = detail_str[:47] + "..."
        print(f"{case:<6} {name:<72} {status:<8} {detail_str}")
    if k_skipped and not any(c == "K" for c, _, _, _ in results):
        print(f"{'K':<6} {'UI smoke test (App construction + existing tabs)':<72} "
              f"{'SKIP':<8} no display available")
    print(sep)
    summary_parts = [f"Total: {n_pass} PASS, {n_fail} FAIL"]
    if n_skip > 0:
        summary_parts.append(f"{n_skip} SKIP")
    if k_skipped:
        summary_parts.append("(+ case K skipped — no display)")
    print(", ".join(summary_parts))
    print(sep)
    print("By case:")
    for case in sorted(by_case.keys()):
        c = by_case[case]
        parts = [f"{c['pass']} PASS", f"{c['fail']} FAIL"]
        if c["skip"] > 0:
            parts.append(f"{c['skip']} SKIP")
        print(f"  Case {case}: {', '.join(parts)}")
    if k_skipped and "K" not in by_case:
        print(f"  Case K: SKIP (no display available)")
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
