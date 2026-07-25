#!/usr/bin/env python3
"""Acceptance test for Task ID 6 — promotion filter dropdown.

Tests the multi-promotion awareness added to `src/app.py`:

  A. All fighters (no filter) — `get_fighters_for_display(conn, None)`
     returns 5 rows (2 Alpha Combat + 3 Rival Fight League).
  B. Alpha Combat only — filter by AC's promotion_id, returns 2 rows,
     every row's promotion name (3rd column) == "Alpha Combat".
  C. Rival Fight League only — filter by RFL's promotion_id, returns
     3 rows, every row's promotion name == "Rival Fight League".
  D. Invalid promotion_id — `get_fighters_for_display(conn, 99999)`
     returns an empty list (no crash).
  E. Free agent (NULL promotion) — inserts a fighter with no
     current_promotion_id plus the matching attribute/personality/
     career rows. With filter=None the result grows to 6 rows and
     the free agent's row shows "Unassigned" as the promotion name.
     Filtering by Alpha Combat still returns 2 rows (the free agent
     is excluded).
  F. UI integration smoke test (optional) — attempts to construct
     `App()` without calling `mainloop()`. Sets the filter, calls
     `refresh_all()`, and asserts the Fighters tree's row count
     matches the filter. Skipped cleanly in headless environments
     via `try/except (_tkinter.TclError, ImportError)` — cases A-E
     must always run and pass regardless.

Run from the project root:
    python3 scripts/test_promotion_filter.py

Exit code 0 = all PASS, 1 = any FAIL (SKIP for case F is not a fail).
The script rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.
"""
import sqlite3
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)

# Make src/ importable so we can call get_fighters_for_display() and
# (for case F) construct App() directly without going through the
# launcher script. Importing app.py pulls in tkinter — the import
# itself does not require a display (only tk.Tk() does), so this is
# safe in headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_fight_resolver.py / test_fight_history.py
    so all three tests share the same setup contract: a fresh DB with
    2 promotions (Alpha Combat + Rival Fight League), 5 fighters
    (2 AC + 3 RFL), 1 event, 1 fight.
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


# --------------------------------------------------------------------
# Cases A-E — pure DB / helper tests (no Tkinter display required).
# These MUST always run and pass, regardless of whether a display is
# available.
# --------------------------------------------------------------------

def case_a_all_fighters(conn):
    """A. All fighters (no filter) -> 5 rows."""
    rows = app.get_fighters_for_display(conn, None)
    expected = 5  # 2 Alpha Combat + 3 Rival Fight League
    passed = len(rows) == expected
    return passed, (
        f"expected {expected} rows (2 AC + 3 RFL), got {len(rows)}"
    ), rows


def case_b_alpha_combat_only(conn, alpha_combat_id):
    """B. Alpha Combat filter -> 2 rows, all promotion name == 'Alpha Combat'."""
    rows = app.get_fighters_for_display(conn, alpha_combat_id)
    count_ok = len(rows) == 2
    names_ok = all(r[2] == "Alpha Combat" for r in rows)
    passed = count_ok and names_ok
    detail = (
        f"expected 2 rows all with promo='Alpha Combat'; "
        f"got {len(rows)} rows, promo names={[r[2] for r in rows]}"
    )
    return passed, detail, rows


def case_c_rfl_only(conn, rfl_id):
    """C. Rival Fight League filter -> 3 rows, all promo == 'Rival Fight League'."""
    rows = app.get_fighters_for_display(conn, rfl_id)
    count_ok = len(rows) == 3
    names_ok = all(r[2] == "Rival Fight League" for r in rows)
    passed = count_ok and names_ok
    detail = (
        f"expected 3 rows all with promo='Rival Fight League'; "
        f"got {len(rows)} rows, promo names={[r[2] for r in rows]}"
    )
    return passed, detail, rows


def case_d_invalid_promotion_id(conn):
    """D. Invalid promotion_id (99999) -> empty list, no crash."""
    try:
        rows = app.get_fighters_for_display(conn, 99999)
    except Exception as e:
        return False, f"crashed: {type(e).__name__}: {e}", []
    passed = len(rows) == 0
    return passed, f"expected 0 rows, got {len(rows)}", rows


def case_e_free_agent(conn, alpha_combat_id):
    """E. Free agent (NULL current_promotion_id) shows under 'All' but not under any single promo.

    Inserts a fighter with no current_promotion_id plus the matching
    fighter_attributes / fighter_personality / fighter_career rows
    (using the same default-value INSERT pattern as seed_data.py).
    Then:
      - filter=None -> 6 rows (5 + 1 free agent), free agent row's
        promotion name is 'Unassigned'.
      - filter=alpha_combat_id -> still 2 rows (free agent excluded).
    """
    # Look up the weight_class_id + archetype_ids the seed used so the
    # free agent looks like a normal fighter except for the missing
    # current_promotion_id. We pass current_promotion_id=NULL.
    wc = conn.execute("SELECT weight_class_id FROM weight_classes LIMIT 1").fetchone()
    style = conn.execute("SELECT style_archetype_id FROM style_archetypes LIMIT 1").fetchone()
    pers = conn.execute("SELECT personality_archetype_id FROM personality_archetypes LIMIT 1").fetchone()
    gym = conn.execute("SELECT gym_id FROM gyms LIMIT 1").fetchone()
    city = conn.execute("SELECT city_id FROM cities LIMIT 1").fetchone()
    nation = conn.execute("SELECT nation_id FROM nations LIMIT 1").fetchone()
    if not (wc and style and pers and gym and city and nation):
        return False, "seed lookup failed (missing WC/style/pers/gym/city/nation)", []

    free_first, free_last, free_nick = "Tommy", "Rogue", "Wildcard"
    free_dob = "1990-01-01"
    free_id = conn.execute(
        """
        INSERT INTO fighters (
            first_name, last_name, nickname, gender, date_of_birth,
            birth_city_id, birth_nation_id, residence_city_id, residence_nation_id,
            weight_class_id, current_gym_id, current_promotion_id,
            fight_style_archetype_id, personality_archetype_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (free_first, free_last, free_nick, "male", free_dob,
         city[0], nation[0], city[0], nation[0],
         wc[0], gym[0], style[0], pers[0]),
    ).lastrowid
    # Match seed_data.py's pattern: each fighter gets one row in each
    # of fighter_attributes / fighter_personality / fighter_career,
    # using the default values defined in build_db.py.
    conn.execute("INSERT INTO fighter_attributes (fighter_id) VALUES (?)", (free_id,))
    conn.execute("INSERT INTO fighter_personality (fighter_id) VALUES (?)", (free_id,))
    conn.execute("INSERT INTO fighter_career (fighter_id) VALUES (?)", (free_id,))
    conn.commit()

    # filter=None: should now be 6 rows.
    rows_all = app.get_fighters_for_display(conn, None)
    count_all_ok = len(rows_all) == 6
    # The free agent's row should show "Unassigned" as the promotion
    # name (3rd column, index 2). Find the row by name.
    free_row = next((r for r in rows_all if r[0] == f"{free_first} {free_last}"), None)
    if free_row is None:
        return False, "free agent row not found in filter=None result", rows_all
    name_ok = free_row[2] == "Unassigned"

    # filter=alpha_combat_id: should still be 2 rows (free agent excluded).
    rows_ac = app.get_fighters_for_display(conn, alpha_combat_id)
    count_ac_ok = len(rows_ac) == 2

    passed = count_all_ok and name_ok and count_ac_ok
    detail = (
        f"filter=None -> {len(rows_all)} rows (expected 6); "
        f"free agent promo name = {free_row[2]!r} (expected 'Unassigned'); "
        f"filter=AC -> {len(rows_ac)} rows (expected 2)"
    )
    return passed, detail, rows_all


# --------------------------------------------------------------------
# Case F — UI integration smoke test.
# Skipped cleanly in headless environments via try/except. Cases A-E
# must always pass regardless of whether case F runs.
# --------------------------------------------------------------------

def case_f_ui_smoke(alpha_combat_id):
    """F. UI smoke test: construct App, set filter, refresh, check tree.

    Tries to construct App() without calling mainloop(). If the
    environment has no display (headless CI), or tkinter is missing
    entirely, this is skipped with a clear message rather than failing
    the test. After constructing App(), we:
      - set app.current_promotion_filter = alpha_combat_id, refresh,
        assert Fighters tree has 2 entries.
      - set app.current_promotion_filter = None, refresh, assert
        Fighters tree has 6 entries (case E's free agent persists in
        the DB from earlier in the run).
      - destroy the app.
    """
    try:
        # Re-import tkinter here so the ImportError case is local to
        # this function — the module-level `import app` already
        # imported tkinter, but if tkinter is missing entirely the
        # module-level import would have failed before we got here.
        # The _tkinter.TclError path is the realistic one in headless
        # environments.
        app_instance = app.App()
    except Exception as e:
        # Catch both ImportError (tkinter not installed) and
        # _tkinter.TclError (no $DISPLAY). Anything else is a real
        # bug — let it propagate so the test fails loudly. But the
        # two expected skip-reasons are by far the most common in
        # sandbox / CI environments.
        if isinstance(e, (_tkinter_TclError, ImportError)):
            return None, f"SKIP — no display available ({type(e).__name__})", None
        return False, f"App() crashed: {type(e).__name__}: {e}", None

    try:
        # Set filter to Alpha Combat, refresh, check Fighters tree.
        app_instance.current_promotion_filter = alpha_combat_id
        app_instance.refresh_all()
        n_ac = len(app_instance.fighters.get_children())
        ac_ok = n_ac == 2

        # Reset filter to None (all promotions), refresh, check tree.
        # Should be 6 because case E added a free agent that persists.
        app_instance.current_promotion_filter = None
        app_instance.refresh_all()
        n_all = len(app_instance.fighters.get_children())
        all_ok = n_all == 6

        passed = ac_ok and all_ok
        detail = (
            f"filter=AC -> {n_ac} tree rows (expected 2); "
            f"filter=None -> {n_all} tree rows (expected 6 incl. free agent)"
        )
        return passed, detail, None
    finally:
        try:
            app_instance.destroy()
        except Exception:
            pass


# Lazy import of _tkinter — only needed inside case F's exception
# handler. Wrapped so that if _tkinter itself is unavailable (which
# would imply `import tkinter` already failed at module load time),
# we don't get a NameError on the isinstance() check.
try:
    import _tkinter as _tkinter_mod
    _tkinter_TclError = _tkinter_mod.TclError
except ImportError:
    # If _tkinter is missing, tkinter itself can't be imported, so
    # the module-level `import app` would already have failed before
    # we reached case F. This branch is purely defensive.
    _tkinter_TclError = type("_MissingTclError", (Exception,), {})


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    rfl_id = get_promotion_id(conn, "Rival Fight League")

    sep = "=" * 80
    print(sep)
    print("TASK 6 PROMOTION FILTER ACCEPTANCE TEST")
    print(sep)
    print(f"Alpha Combat promotion_id   = {alpha_combat_id}")
    print(f"Rival Fight League promo_id = {rfl_id}")
    print(sep)
    print(f"{'Case':<70} {'Result':<8} Detail")
    print("-" * 120)

    results = []  # list of (case_name, status, detail)

    # Case A
    passed, detail, _ = case_a_all_fighters(conn)
    status = "PASS" if passed else "FAIL"
    results.append(("A. All fighters (no filter) -> 5 rows", passed, status, detail))
    print(f"{'A. All fighters (no filter) -> 5 rows':<70} {status:<8} {detail}")

    # Case B
    passed, detail, _ = case_b_alpha_combat_only(conn, alpha_combat_id)
    status = "PASS" if passed else "FAIL"
    results.append(("B. Alpha Combat filter -> 2 rows, all 'Alpha Combat'", passed, status, detail))
    print(f"{'B. Alpha Combat filter -> 2 rows, all Alpha Combat':<70} {status:<8} {detail}")

    # Case C
    passed, detail, _ = case_c_rfl_only(conn, rfl_id)
    status = "PASS" if passed else "FAIL"
    results.append(("C. RFL filter -> 3 rows, all 'Rival Fight League'", passed, status, detail))
    print(f"{'C. RFL filter -> 3 rows, all Rival Fight League':<70} {status:<8} {detail}")

    # Case D
    passed, detail, _ = case_d_invalid_promotion_id(conn)
    status = "PASS" if passed else "FAIL"
    results.append(("D. Invalid promotion_id (99999) -> empty list", passed, status, detail))
    print(f"{'D. Invalid promotion_id (99999) -> empty list':<70} {status:<8} {detail}")

    # Case E
    passed, detail, _ = case_e_free_agent(conn, alpha_combat_id)
    status = "PASS" if passed else "FAIL"
    results.append(("E. Free agent (NULL promo) shows under All only", passed, status, detail))
    print(f"{'E. Free agent (NULL promo) shows under All only':<70} {status:<8} {detail}")

    # Case F (optional — skips cleanly if no display)
    f_status, f_detail, _ = case_f_ui_smoke(alpha_combat_id)
    if f_status is None:
        results.append(("F. UI smoke test (App construction + filter)", None, "SKIP", f_detail))
        print(f"{'F. UI smoke test (App construction + filter)':<70} {'SKIP':<8} {f_detail}")
    else:
        status = "PASS" if f_status else "FAIL"
        results.append(("F. UI smoke test (App construction + filter)", f_status, status, f_detail))
        print(f"{'F. UI smoke test (App construction + filter)':<70} {status:<8} {f_detail}")

    print(sep)
    print("SUMMARY")
    print(sep)
    n_pass = 0
    n_fail = 0
    n_skip = 0
    for case_name, passed, status, detail in results:
        print(f"  [{status}] {case_name}")
        print(f"         {detail}")
        if status == "PASS":
            n_pass += 1
        elif status == "FAIL":
            n_fail += 1
        elif status == "SKIP":
            n_skip += 1
    print()
    print(f"Total: {n_pass} PASS, {n_fail} FAIL, {n_skip} SKIP")
    print(sep)

    # Cases A-E must always pass. Case F is optional and may SKIP.
    cases_a_e_ok = all(
        r[1] for r in results[:5]
    )
    case_f_ok = results[5][1] is None or results[5][1]  # SKIP or PASS

    if cases_a_e_ok and case_f_ok:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
