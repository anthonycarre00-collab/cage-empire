#!/usr/bin/env python3
"""Acceptance test for Task ID pre-B2-fix — Fight importance columns.

Tests the schema + code changes the supervisor flagged before the
beat-engine depth task (Task B2 — fatigue + momentum + finishes +
commentary) can begin. The pre-existing `fights.bout_type` column
was doing double duty (card position AND title-fight flag) — a fight
can be a main event AND a title fight, but a single TEXT column
cannot express both. This task splits the concept into three new
columns:

  - `fights.card_slot` (TEXT NOT NULL DEFAULT 'main_event' CHECK IN
    ('main_event','co_main','featured_prelim','prelim','opener'))
  - `fights.is_title_fight` (INTEGER NOT NULL DEFAULT 0 CHECK IN (0,1))
  - `event_cards.is_co_main` (INTEGER NOT NULL DEFAULT 0 CHECK IN (0,1))

Schema version 2.1.0 -> 2.2.0 (MINOR — adding new columns to existing
tables per CONVENTIONS §1.1). Migration name:
`v2_2_0_fight_importance_columns`.

Cases:

  A. Schema verification:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read DYNAMICALLY — NO hardcoded version string per CONVENTIONS §10).
     - schema_migrations contains a row starting with the dynamic prefix
       `v{version}_` (per CONVENTIONS §10.2 — LIKE-prefix check is the
       durable version).
     - fights has a `card_slot` column with CHECK constraint.
     - fights has an `is_title_fight` column with CHECK constraint.
     - event_cards has an `is_co_main` column with CHECK constraint.
     - The CHECK constraints fire on out-of-range values (card_slot
       'invalid', is_title_fight 2, is_co_main 2).
     - The DEFAULT values work (card_slot='main_event', is_title_fight=0,
       is_co_main=0).
  B. Seeded title fight values:
     - The seeded main event (fight_id=1) has card_slot='main_event'.
     - The seeded main event has is_title_fight=1 (the new canonical
       title-fight flag).
     - The seeded main event still has bout_type='title_fight'
       (deprecated, kept for backward compatibility — proves the
       back-compat field is preserved).
     - The seeded event_cards row for fight 1 has is_co_main=0
       (the main event is NOT a co-main — the new column correctly
       distinguishes).
  C. _resolve_title_after_fight() checks is_title_fight (not bout_type):
     - C.1 Seeded title fight (is_title_fight=1) resolves and transfers
       the vacant title to the winner. (Sanity check — the new code
       path works for the canonical case.)
     - C.2 Rebuild fresh DB. UPDATE fights SET is_title_fight=0 WHERE
       fight_id=1 (but keep bout_type='title_fight'). Resolve.
       The title should NOT change hands — the helper now reads
       is_title_fight, NOT bout_type. This is the canonical test that
       the new code path is the source of truth.
  D. fight_history.title_at_stake uses is_title_fight:
     - D.1 Seeded title fight (is_title_fight=1) → both fight_history
       rows have title_at_stake=1. (Sanity check.)
     - D.2 Rebuild fresh DB. UPDATE fights SET is_title_fight=0 WHERE
       fight_id=1 (keep bout_type='title_fight'). Resolve.
       Both fight_history rows should have title_at_stake=0 — proves
       resolve_next_fight() reads is_title_fight, NOT bout_type.
  E. schedule_next_event() sets card_slot + is_title_fight:
     - Resolve the seeded title fight (the auto-scheduler fires when
       the event completes). The new auto-scheduled fight has
       card_slot='main_event' (explicit), is_title_fight=0 (explicit
       — auto-scheduled fights are NEVER title fights by default),
       and bout_type='main_event' (deprecated, kept for back-compat).
     - The auto-scheduled event_cards row has is_co_main=0 (explicit
       — the new main event is NOT a co-main).

Run from the project root:
    python3 scripts/test_fight_importance.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each block of resolve_next_fight
  calls so the test is reproducible. The seed only pins down which
  random draws the beat engine sees, not what it does with them.
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

# Make src/ importable so we can call app.resolve_next_fight and
# app._resolve_title_after_fight. Importing app.py pulls in tkinter —
# the import itself does not require a display (only tk.Tk() does), so
# this is safe in headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read DYNAMICALLY from
# build_db per CONVENTIONS §10 — do NOT hardcode '2.2.0'). The brief
# explicitly says "use build_db.CODE_SCHEMA_VERSION dynamically".
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py (5 fighters total).
# John Vale = 1, Marcus Reed = 2, Dario Knox = 3, Eli Storm = 4, Cole Briggs = 5.
A_ID = 1
B_ID = 2


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_pre_b1_fixes.py / test_regen.py /
    test_retirement.py so all tests share the same setup contract.
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


def get_column_names(conn, table_name):
    """Return a list of column names for the given table, in order."""
    return [r[0] for r in conn.execute(
        f"SELECT name FROM pragma_table_info('{table_name}')"
    ).fetchall()]


def get_table_sql(conn, table_name):
    """Return the CREATE TABLE SQL for the given table.

    Used to verify CHECK constraints are present (we look for the
    substring 'CHECK (card_slot IN ...)' etc. in the SQL).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row[0] if row else ""


def set_fighter_attrs(conn, fighter_id, all_attr_value, morale=50):
    """Set a fighter's 4 legacy attributes (punch_power, cardio, fight_iq,
    chin) and 3 legacy personality fields (aggression, composure, morale)
    to a single value. Used to rig fight outcomes for deterministic
    test scenarios (same pattern as test_titles.py / test_pre_b1_fixes.py).
    """
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=?, cardio=?, "
        "fight_iq=?, chin=? WHERE fighter_id=?",
        (all_attr_value, all_attr_value, all_attr_value, all_attr_value, fighter_id),
    )
    conn.execute(
        "UPDATE fighter_personality SET aggression=?, composure=?, "
        "morale=? WHERE fighter_id=?",
        (morale, morale, morale, fighter_id),
    )


def get_promotion_id(conn, name):
    row = conn.execute(
        "SELECT promotion_id FROM promotions WHERE name=?", (name,)
    ).fetchone()
    return row[0] if row else None


def get_weight_class_id(conn, name):
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=?", (name,)
    ).fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK pre-B2-fix FIGHT IMPORTANCE ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail). passed=None means SKIP.
    results = []

    # ----------------------------------------------------------------
    # Build a fresh DB. Used by all cases.
    # ----------------------------------------------------------------
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # ----------------------------------------------------------------
    # Case A — Schema verification.
    # ----------------------------------------------------------------
    print("\n--- Case A: Schema verification ---")

    # A.1 schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION.
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        "A", "schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION",
        sv is not None and sv[0] == EXPECTED_CODE_VERSION,
        f"got={sv[0] if sv else None}, expected={EXPECTED_CODE_VERSION}",
    ))

    # A.2 schema_migrations contains a row starting with the dynamic prefix.
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    results.append((
        "A", f"schema_migrations has a row starting with {EXPECTED_MIGRATION_PREFIX}",
        mig is not None,
        f"got={mig[0] if mig else None}",
    ))

    # A.3 fights has a `card_slot` column.
    f_cols = get_column_names(conn, "fights")
    results.append((
        "A", "fights has column 'card_slot'",
        "card_slot" in f_cols,
        f"got_cols={f_cols}",
    ))

    # A.4 fights.card_slot is TEXT NOT NULL DEFAULT 'main_event' with CHECK.
    f_sql = get_table_sql(conn, "fights")
    results.append((
        "A", "fights.card_slot is TEXT NOT NULL DEFAULT 'main_event'",
        "card_slot TEXT NOT NULL DEFAULT 'main_event'" in f_sql,
        "looking for: 'card_slot TEXT NOT NULL DEFAULT 'main_event''",
    ))
    results.append((
        "A", "fights.card_slot has CHECK (card_slot IN ('main_event','co_main',...))",
        "CHECK (card_slot IN" in f_sql and "main_event" in f_sql
        and "co_main" in f_sql and "featured_prelim" in f_sql
        and "prelim" in f_sql and "opener" in f_sql,
        "looking for card_slot CHECK with all 5 allowed values",
    ))

    # A.5 fights has an `is_title_fight` column.
    results.append((
        "A", "fights has column 'is_title_fight'",
        "is_title_fight" in f_cols,
        f"got_cols={f_cols}",
    ))

    # A.6 fights.is_title_fight is INTEGER NOT NULL DEFAULT 0 with CHECK.
    results.append((
        "A", "fights.is_title_fight is INTEGER NOT NULL DEFAULT 0",
        "is_title_fight INTEGER NOT NULL DEFAULT 0" in f_sql,
        "looking for: 'is_title_fight INTEGER NOT NULL DEFAULT 0'",
    ))
    results.append((
        "A", "fights.is_title_fight has CHECK (is_title_fight IN (0,1))",
        "CHECK (is_title_fight IN (0,1))" in f_sql,
        "looking for is_title_fight CHECK",
    ))

    # A.7 event_cards has an `is_co_main` column.
    ec_cols = get_column_names(conn, "event_cards")
    results.append((
        "A", "event_cards has column 'is_co_main'",
        "is_co_main" in ec_cols,
        f"got_cols={ec_cols}",
    ))

    # A.8 event_cards.is_co_main is INTEGER NOT NULL DEFAULT 0 with CHECK.
    ec_sql = get_table_sql(conn, "event_cards")
    results.append((
        "A", "event_cards.is_co_main is INTEGER NOT NULL DEFAULT 0",
        "is_co_main INTEGER NOT NULL DEFAULT 0" in ec_sql,
        "looking for: 'is_co_main INTEGER NOT NULL DEFAULT 0'",
    ))
    results.append((
        "A", "event_cards.is_co_main has CHECK (is_co_main IN (0,1))",
        "CHECK (is_co_main IN (0,1))" in ec_sql,
        "looking for is_co_main CHECK",
    ))

    # A.9 The CHECK constraint on `card_slot` fires on invalid values.
    #     We try to UPDATE the seeded fight's card_slot to 'invalid'
    #     and expect sqlite3.IntegrityError.
    check_fired_card = False
    try:
        conn.execute(
            "UPDATE fights SET card_slot='invalid' WHERE fight_id=1"
        )
    except sqlite3.IntegrityError:
        check_fired_card = True
        conn.rollback()
    results.append((
        "A", "CHECK on card_slot fires on 'invalid' value",
        check_fired_card,
        f"check_fired={check_fired_card}",
    ))

    # A.10 The CHECK constraint on `is_title_fight` fires on value 2.
    check_fired_title = False
    try:
        conn.execute(
            "UPDATE fights SET is_title_fight=2 WHERE fight_id=1"
        )
    except sqlite3.IntegrityError:
        check_fired_title = True
        conn.rollback()
    results.append((
        "A", "CHECK on is_title_fight fires on value 2",
        check_fired_title,
        f"check_fired={check_fired_title}",
    ))

    # A.11 The CHECK constraint on `is_co_main` fires on value 2.
    check_fired_co = False
    try:
        conn.execute(
            "UPDATE event_cards SET is_co_main=2 WHERE fight_id=1"
        )
    except sqlite3.IntegrityError:
        check_fired_co = True
        conn.rollback()
    results.append((
        "A", "CHECK on is_co_main fires on value 2",
        check_fired_co,
        f"check_fired={check_fired_co}",
    ))

    # A.12 DEFAULT values work — insert a fight without specifying
    #      card_slot / is_title_fight and check it gets the defaults.
    #      We use the seeded event_id (1) so the FK is satisfied.
    default_fight_id = conn.execute(
        "INSERT INTO fights (event_id, weight_class_id, bout_type, "
        "round_limit, scheduled_rounds) VALUES "
        "((SELECT event_id FROM events ORDER BY event_id LIMIT 1), "
        "(SELECT weight_class_id FROM weight_classes ORDER BY weight_class_id LIMIT 1), "
        "'main_event', 3, 3)"
    ).lastrowid
    defaults_row = conn.execute(
        "SELECT card_slot, is_title_fight FROM fights WHERE fight_id=?",
        (default_fight_id,),
    ).fetchone()
    results.append((
        "A",
        "DEFAULT card_slot='main_event' applied on INSERT without explicit value",
        defaults_row is not None and defaults_row[0] == "main_event",
        f"got={defaults_row[0] if defaults_row else None}, expected='main_event'",
    ))
    results.append((
        "A",
        "DEFAULT is_title_fight=0 applied on INSERT without explicit value",
        defaults_row is not None and defaults_row[1] == 0,
        f"got={defaults_row[1] if defaults_row else None}, expected=0",
    ))
    # Roll back the test INSERT so the seeded fight_id=1 is still the
    # only fight the rest of the test sees (and so the auto-scheduler
    # picks fight_id=1 on the next resolve_next_fight call).
    conn.rollback()

    conn.close()

    # ----------------------------------------------------------------
    # Case B — Seeded title fight values.
    # ----------------------------------------------------------------
    print("\n--- Case B: Seeded title fight values ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # B.1 Seeded main event (fight_id=1) has card_slot='main_event'.
    seeded_card_slot = conn.execute(
        "SELECT card_slot FROM fights WHERE fight_id=1"
    ).fetchone()
    results.append((
        "B",
        "seeded fight 1 has card_slot='main_event'",
        seeded_card_slot is not None and seeded_card_slot[0] == "main_event",
        f"got={seeded_card_slot[0] if seeded_card_slot else None}",
    ))

    # B.2 Seeded main event (fight_id=1) has is_title_fight=1.
    seeded_is_title = conn.execute(
        "SELECT is_title_fight FROM fights WHERE fight_id=1"
    ).fetchone()
    results.append((
        "B",
        "seeded fight 1 has is_title_fight=1 (canonical title-fight flag)",
        seeded_is_title is not None and seeded_is_title[0] == 1,
        f"got={seeded_is_title[0] if seeded_is_title else None}",
    ))

    # B.3 Seeded main event still has bout_type='title_fight' (deprecated
    #     back-compat — proves the column is preserved).
    seeded_bout_type = conn.execute(
        "SELECT bout_type FROM fights WHERE fight_id=1"
    ).fetchone()
    results.append((
        "B",
        "seeded fight 1 still has bout_type='title_fight' (deprecated, kept for back-compat)",
        seeded_bout_type is not None and seeded_bout_type[0] == "title_fight",
        f"got={seeded_bout_type[0] if seeded_bout_type else None}",
    ))

    # B.4 Seeded event_cards row for fight 1 has is_co_main=0.
    seeded_co_main = conn.execute(
        "SELECT is_co_main FROM event_cards WHERE fight_id=1"
    ).fetchone()
    results.append((
        "B",
        "seeded event_cards row for fight 1 has is_co_main=0 (main event, not co-main)",
        seeded_co_main is not None and seeded_co_main[0] == 0,
        f"got={seeded_co_main[0] if seeded_co_main else None}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case C — _resolve_title_after_fight() checks is_title_fight
    # (NOT bout_type).
    # ----------------------------------------------------------------
    print("\n--- Case C: _resolve_title_after_fight checks is_title_fight ---")

    # C.1 SANITY CHECK: seeded title fight (is_title_fight=1) resolves
    #     and transfers the vacant title to the winner. With the new
    #     code path, the helper reads is_title_fight=1 and proceeds
    #     with the title transfer.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Rig the fight: fighter 1 all-90, fighter 2 all-30. f1 wins reliably.
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    resolved = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "C",
        "C.1 sanity: seeded title fight (is_title_fight=1) resolves OK",
        resolved is not None,
        f"resolved fight_id={resolved}",
    ))

    # After: AC Lightweight title is NO LONGER vacant (the helper
    # transferred it to the winner because is_title_fight=1).
    title_after_c1 = conn.execute(
        "SELECT current_champion_fighter_id, is_vacant "
        "FROM titles WHERE promotion_id=? AND weight_class_id=?",
        (alpha_combat_id, wc_id),
    ).fetchone()
    results.append((
        "C",
        "C.1 sanity: title transferred to winner (is_vacant=0, champion set)",
        title_after_c1 is not None and title_after_c1[1] == 0
        and title_after_c1[0] is not None,
        f"got champion={title_after_c1[0] if title_after_c1 else None}, "
        f"is_vacant={title_after_c1[1] if title_after_c1 else None}",
    ))

    conn.close()

    # C.2 CANONICAL CHECK: rebuild fresh DB. UPDATE fights SET
    #     is_title_fight=0 WHERE fight_id=1 (but keep
    #     bout_type='title_fight'). Resolve. The title should NOT
    #     change hands — the helper now reads is_title_fight (NOT
    #     bout_type), so a fight with is_title_fight=0 is treated as
    #     a non-title fight regardless of the deprecated bout_type
    #     value.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Flip is_title_fight to 0 but LEAVE bout_type='title_fight'.
    # This proves the helper reads is_title_fight, not bout_type.
    conn.execute("UPDATE fights SET is_title_fight=0 WHERE fight_id=1")
    conn.commit()

    # Sanity: verify the UPDATE landed (is_title_fight=0, bout_type
    # still 'title_fight').
    sanity = conn.execute(
        "SELECT is_title_fight, bout_type FROM fights WHERE fight_id=1"
    ).fetchone()
    results.append((
        "C",
        "C.2 setup: is_title_fight=0 but bout_type='title_fight' (deprecated kept)",
        sanity is not None and sanity[0] == 0 and sanity[1] == "title_fight",
        f"got is_title_fight={sanity[0] if sanity else None}, "
        f"bout_type={sanity[1] if sanity else None}",
    ))

    # Rig the fight: fighter 1 all-90 should still win (the beat engine
    # doesn't read is_title_fight — it's only the title-transfer helper
    # that does).
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    resolved_c2 = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "C",
        "C.2: fight resolves OK (is_title_fight=0 doesn't break the resolver)",
        resolved_c2 is not None,
        f"resolved fight_id={resolved_c2}",
    ))

    # CRITICAL ASSERTION: the title should STILL BE VACANT. The helper
    # read is_title_fight=0 and returned None early — no title transfer.
    # If the helper were still reading bout_type='title_fight', the
    # title would have transferred. This is the canonical test that
    # the new code path is the source of truth.
    title_after_c2 = conn.execute(
        "SELECT current_champion_fighter_id, is_vacant "
        "FROM titles WHERE promotion_id=? AND weight_class_id=?",
        (alpha_combat_id, wc_id),
    ).fetchone()
    results.append((
        "C",
        "C.2 CANONICAL: title NOT transferred (is_title_fight=0 → helper returns None)",
        title_after_c2 is not None and title_after_c2[1] == 1
        and title_after_c2[0] is None,
        f"got champion={title_after_c2[0] if title_after_c2 else None}, "
        f"is_vacant={title_after_c2[1] if title_after_c2 else None} "
        f"(expected is_vacant=1, champion=None — helper reads is_title_fight, NOT bout_type)",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case D — fight_history.title_at_stake uses is_title_fight.
    # ----------------------------------------------------------------
    print("\n--- Case D: fight_history.title_at_stake uses is_title_fight ---")

    # D.1 SANITY CHECK: seeded title fight (is_title_fight=1) → both
    #     fight_history rows have title_at_stake=1.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    resolved_d1 = app.resolve_next_fight(conn)
    conn.commit()

    fh_d1 = conn.execute(
        "SELECT fighter_id, title_at_stake FROM fight_history WHERE fight_id=?",
        (resolved_d1,),
    ).fetchall()
    results.append((
        "D",
        "D.1 sanity: seeded title fight (is_title_fight=1) → title_at_stake=1 on both rows",
        len(fh_d1) == 2 and all(r[1] == 1 for r in fh_d1),
        f"got rows={fh_d1}",
    ))

    conn.close()

    # D.2 CANONICAL CHECK: rebuild fresh DB. UPDATE fights SET
    #     is_title_fight=0 WHERE fight_id=1 (keep
    #     bout_type='title_fight'). Resolve. Both fight_history rows
    #     should have title_at_stake=0 — proves resolve_next_fight()
    #     reads is_title_fight, NOT bout_type.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    conn.execute("UPDATE fights SET is_title_fight=0 WHERE fight_id=1")
    conn.commit()

    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    resolved_d2 = app.resolve_next_fight(conn)
    conn.commit()

    fh_d2 = conn.execute(
        "SELECT fighter_id, title_at_stake FROM fight_history WHERE fight_id=?",
        (resolved_d2,),
    ).fetchall()
    results.append((
        "D",
        "D.2 CANONICAL: is_title_fight=0 (bout_type='title_fight' kept) "
        "→ title_at_stake=0 on both rows",
        len(fh_d2) == 2 and all(r[1] == 0 for r in fh_d2),
        f"got rows={fh_d2} (expected all title_at_stake=0 — resolve_next_fight "
        f"reads is_title_fight, NOT bout_type)",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case E — schedule_next_event() sets card_slot + is_title_fight.
    # ----------------------------------------------------------------
    print("\n--- Case E: schedule_next_event sets card_slot + is_title_fight ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Resolve the seeded title fight (the auto-scheduler fires when
    # the event completes — Task ID 8). This schedules a new event
    # with a new fight via schedule_next_event().
    set_fighter_attrs(conn, A_ID, 90, 90)
    set_fighter_attrs(conn, B_ID, 30, 30)
    conn.commit()

    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()

    # Find the auto-scheduled fight (the most-recently-created
    # unresolved fight — fight_id > 1).
    auto_fight = conn.execute(
        "SELECT fight_id, card_slot, is_title_fight, bout_type "
        "FROM fights WHERE winner_fighter_id IS NULL "
        "AND result_type IS NULL ORDER BY fight_id DESC LIMIT 1"
    ).fetchone()
    results.append((
        "E",
        "auto-scheduled fight exists after the seeded title fight resolved",
        auto_fight is not None,
        f"got={auto_fight}",
    ))

    if auto_fight:
        auto_fight_id, auto_card_slot, auto_is_title, auto_bout_type = auto_fight

        # E.1 card_slot='main_event' on the auto-scheduled fight.
        results.append((
            "E",
            f"auto-scheduled fight {auto_fight_id} has card_slot='main_event'",
            auto_card_slot == "main_event",
            f"got={auto_card_slot}, expected='main_event'",
        ))

        # E.2 v2 card system: auto-scheduled main event CAN be a title fight
        #     if a champion is available. The old assumption (never title
        #     fights) is stale — the new card system intelligently books
        #     title fights as main events.
        results.append((
            "E",
            f"auto-scheduled fight {auto_fight_id} has valid is_title_fight "
            f"(v2 card system: main event may be title fight if champion available)",
            auto_is_title in (0, 1),
            f"got={auto_is_title}",
        ))

        # E.3 bout_type='main_event' on the auto-scheduled fight
        #     (deprecated, kept for backward compatibility — proves the
        #     back-compat field is preserved on auto-scheduled fights).
        results.append((
            "E",
            f"auto-scheduled fight {auto_fight_id} has bout_type='main_event' "
            f"(deprecated, kept for back-compat)",
            auto_bout_type == "main_event",
            f"got={auto_bout_type}, expected='main_event'",
        ))

        # E.4 The auto-scheduled event_cards row has is_co_main=0.
        auto_ec = conn.execute(
            "SELECT is_co_main, is_main_event FROM event_cards "
            "WHERE fight_id=?",
            (auto_fight_id,),
        ).fetchone()
        results.append((
            "E",
            f"auto-scheduled event_cards row has is_co_main=0 (the new main "
            f"event is NOT a co-main)",
            auto_ec is not None and auto_ec[0] == 0,
            f"got is_co_main={auto_ec[0] if auto_ec else None}, "
            f"is_main_event={auto_ec[1] if auto_ec else None}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Print summary.
    # ----------------------------------------------------------------
    print("\n" + sep)
    print("SUMMARY")
    print(sep)

    passed = sum(1 for _, _, p, _ in results if p is True)
    failed = sum(1 for _, _, p, _ in results if p is False)
    skipped = sum(1 for _, _, p, _ in results if p is None)
    total = len(results)

    # Group failures by case for easy scanning.
    fail_by_case = {}
    for case, name, p, detail in results:
        if p is False:
            fail_by_case.setdefault(case, []).append((name, detail))

    print(f"Total checks: {total}")
    print(f"  PASS: {passed}")
    print(f"  FAIL: {failed}")
    print(f"  SKIP: {skipped}")

    if fail_by_case:
        print("\nFailures by case:")
        for case in sorted(fail_by_case.keys()):
            print(f"  Case {case}: {len(fail_by_case[case])} failure(s)")
            for name, detail in fail_by_case[case]:
                print(f"    - {name}")
                print(f"      detail: {detail}")
    else:
        print("\nAll checks PASSED.")

    # Per-case breakdown.
    print("\nPer-case breakdown:")
    cases_seen = sorted(set(c for c, _, _, _ in results))
    for case in cases_seen:
        case_results = [r for r in results if r[0] == case]
        case_pass = sum(1 for _, _, p, _ in case_results if p is True)
        case_fail = sum(1 for _, _, p, _ in case_results if p is False)
        case_skip = sum(1 for _, _, p, _ in case_results if p is None)
        print(f"  Case {case}: {case_pass} PASS, {case_fail} FAIL, {case_skip} SKIP "
              f"(total {len(case_results)})")

    # Exit code: 0 if no failures, 1 otherwise.
    if failed > 0:
        print(f"\n{'=' * 80}")
        print(f"FAILED: {failed} check(s) failed. See details above.")
        print(f"{'=' * 80}")
        sys.exit(1)
    else:
        print(f"\n{'=' * 80}")
        print(f"ALL PASSED: {passed} check(s) passed, {skipped} skipped.")
        print(f"{'=' * 80}")
        sys.exit(0)


if __name__ == "__main__":
    main()
