#!/usr/bin/env python3
"""Acceptance test for Stage 5 — Save/Load System (Task ID Stage5-SaveLoad).

Tests the save/load functionality added in Stage 5:
  - src/save_load.py — save_game, load_game, list_saves, delete_save,
    auto_save (TICK_ADVANCED subscriber), register_subscribers.
  - src/app.py — App.__init__ wires save_load.register_subscribers
    (lazy import, defensive except ImportError).
  - src/build_db.py — NO schema change (per the brief: "Do NOT add
    new tables — the DB IS the save state").

Test cases:
  A. save_game creates a .db file in data/saves/
  B. save_game writes metadata JSON
  C. load_game restores the DB (verify data matches)
  D. list_saves returns save info
  E. delete_save removes the file
  F. auto_save fires on TICK_ADVANCED (monthly)
  G. auto_save keeps only 3 rotating saves
  H. Design Law (§13): Investment (player's progress is preserved)

Pattern follows scripts/test_show_rating.py + test_agent_offers.py
(CONVENTIONS §10 — dynamic version pattern, no hardcoded version
strings).

Run from the project root:
    python3 scripts/test_save_load.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` and writes test artifacts to `data/saves/`
(which is gitignored). All test artifacts are cleaned up at the end.

D-number decisions in this test (referenced from the worklog):
  - D1 (cleanup between cases): the test clears data/saves/ at the
    start of each case to ensure deterministic results. Without this,
    auto_save files from a previous case would inflate the list_saves
    count and break the rotation assertions in case G.
  - D2 (load_game verification): the test modifies the DB (deletes
    events + advances clock), then loads a save and verifies the
    events count + sim_date match the saved state. This tests the
    ROUND-TRIP: save → modify → load → verify the modifications are
    undone.
  - D3 (auto_save cadence test): the test sets simulation_clock.
    current_day to a known value (30, 60, 90, 120) via direct SQL,
    then publishes a TICK_ADVANCED event. The auto_save subscriber
    reads current_day from the DB (not from the event payload) to
    decide whether to fire. This makes the test deterministic —
    no RNG, no real-time wait.
  - D4 (rotation test uses mtime, not filename): auto_save generates
    unique filenames with a wall-clock timestamp (autosave_<sim_date>
    _<YYYYMMDD_HHMMSS>.db). The test fires 4 auto-saves in rapid
    succession (same wall-clock second is possible), so filename
    sorting would be unstable. _prune_autosaves sorts by mtime DESC
    and deletes the oldest. The test asserts the file COUNT is 3,
    not the specific filenames (which are wall-clock-dependent).
  - D5 (Design Law test uses an integrated scenario): case H signs
    a free agent, advances the clock by 30 days, and deducts cash
    (simulating player progress). Then saves, makes further
    modifications, loads the save, and verifies ALL the progress
    is restored (the fighter is still signed, the clock is still
    advanced, the cash is still deducted). This tests the holistic
    Investment pillar — the player's choices persist across save/
    load.
"""
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
SAVES_DIR = PROJECT_DIR / "data" / "saves"
sys.path.insert(0, str(SRC_DIR))

import build_db  # noqa: E402
import save_load  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION

# Player promotion ID (Alpha Combat in the small seed — the player's
# promotion per the project convention).
PLAYER_PROMOTION_ID = 1

# Seeded sim date from src/seed_data.py (2026-07-20).
SEEDED_SIM_DATE = "2026-07-20"
SEEDED_CLOCK_DAY = 1

results = []


def check(case, name, passed, detail="", skipped=False):
    """Record a check result. skipped=True overrides passed."""
    results.append((case, name, passed, detail, skipped))
    if skipped:
        status = "SKIP"
    elif passed:
        status = "PASS"
    else:
        status = "FAIL"
    print(f"  {case}  {name:<70} {status}  {detail}")


def build_fresh_db():
    """Drop + rebuild + seed the DB (small seed_data, not world seed)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True, cwd=PROJECT_DIR,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True, cwd=PROJECT_DIR,
    )


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def clean_saves_dir():
    """Delete all files in data/saves/ (the directory itself is preserved).

    D1 — called at the start of each case to ensure deterministic
    results. The directory is recreated by save_load._ensure_saves_dir
    on the next save_game call if it doesn't exist.
    """
    if SAVES_DIR.exists():
        for child in SAVES_DIR.iterdir():
            if child.is_file():
                try:
                    child.unlink()
                except OSError:
                    pass


def publish_tick_advanced(conn, current_date, current_day):
    """Publish a TICK_ADVANCED event AND set the sim clock's current_day
    + current_date so the auto_save cadence check passes.

    D3 — auto_save reads current_day from the DB (not from the event
    payload). So we must UPDATE the clock BEFORE publishing the event.
    """
    conn.execute(
        "UPDATE simulation_clock SET current_day=?, current_date=? "
        "WHERE clock_id=1",
        (current_day, current_date),
    )
    conn.commit()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.TICK_ADVANCED,
        'current_date': current_date,
        'tick_type': 'day',
    })


# ----------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------

def case_a_save_creates_db_file():
    """A. save_game creates a .db file in data/saves/."""
    print("\n--- Case A: save_game creates a .db file ---")
    build_fresh_db()
    clean_saves_dir()
    conn = get_conn()

    save_name = save_load.save_game(conn, save_name="test_save_a")
    save_db_path = SAVES_DIR / f"{save_name}.db"

    check("A", "save_game returns the sanitized save_name",
          save_name == "test_save_a", f"got={save_name!r}")
    check("A", "save_game creates data/saves/ directory",
          SAVES_DIR.exists() and SAVES_DIR.is_dir(), "")
    check("A", "save_game creates a .db file in data/saves/",
          save_db_path.exists() and save_db_path.is_file(),
          f"path={save_db_path}")
    # Verify the saved DB file is a valid SQLite DB.
    try:
        test_conn = sqlite3.connect(str(save_db_path))
        row = test_conn.execute(
            "SELECT COUNT(*) FROM fighters"
        ).fetchone()
        test_conn.close()
        check("A", "saved .db file is a valid SQLite DB",
              row is not None and row[0] >= 0, f"fighter_count={row[0] if row else 'None'}")
    except sqlite3.Error as e:
        check("A", "saved .db file is a valid SQLite DB",
              False, f"sqlite3.Error: {e}")

    # Verify the saved DB file is non-trivial (has actual data).
    saved_size = save_db_path.stat().st_size
    check("A", "saved .db file has non-zero size",
          saved_size > 0, f"size={saved_size} bytes")

    # Verify save_name=None generates a timestamped name.
    auto_name = save_load.save_game(conn, save_name=None)
    check("A", "save_game(None) generates a non-empty name",
          bool(auto_name) and auto_name.startswith("save_"),
          f"got={auto_name!r}")
    auto_db_path = SAVES_DIR / f"{auto_name}.db"
    check("A", "save_game(None) creates a .db file",
          auto_db_path.exists(), f"path={auto_db_path}")

    conn.close()


def case_b_save_writes_metadata_json():
    """B. save_game writes metadata JSON."""
    print("\n--- Case B: save_game writes metadata JSON ---")
    build_fresh_db()
    clean_saves_dir()
    conn = get_conn()

    # Advance the sim clock so the sim_date is deterministic + non-default.
    new_date = "2026-08-15"
    conn.execute(
        "UPDATE simulation_clock SET current_date=?, current_day=? "
        "WHERE clock_id=1",
        (new_date, 26),
    )
    # Update the player promotion's cash to a known value.
    conn.execute(
        "UPDATE promotions SET current_cash=? WHERE promotion_id=?",
        (45_000_000, PLAYER_PROMOTION_ID),
    )
    conn.commit()

    save_name = save_load.save_game(conn, save_name="meta_test")
    meta_path = SAVES_DIR / f"{save_name}.json"

    check("B", "save_game creates a .json metadata file",
          meta_path.exists() and meta_path.is_file(),
          f"path={meta_path}")

    # Verify the metadata JSON has all the required fields per the brief.
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        check("B", "metadata JSON is valid JSON", False, f"error: {e}")
        conn.close()
        return
    check("B", "metadata JSON is valid JSON", True)

    required_keys = {
        "save_name", "timestamp", "sim_date", "promotion_name",
        "current_cash", "fighter_count", "event_count", "schema_version",
    }
    actual_keys = set(meta.keys())
    check("B", f"metadata JSON has all required fields",
          required_keys.issubset(actual_keys),
          f"missing={required_keys - actual_keys}")

    # Verify individual field values.
    check("B", "metadata save_name matches the requested name",
          meta.get("save_name") == "meta_test",
          f"got={meta.get('save_name')!r}")
    check("B", "metadata sim_date matches the DB sim_date",
          meta.get("sim_date") == new_date,
          f"got={meta.get('sim_date')!r} expected={new_date!r}")
    check("B", "metadata promotion_name is non-empty",
          bool(meta.get("promotion_name")),
          f"got={meta.get('promotion_name')!r}")
    check("B", "metadata current_cash matches the DB value",
          meta.get("current_cash") == 45_000_000,
          f"got={meta.get('current_cash')}")
    # Fighter count + event count should match the seeded values.
    expected_fighters = conn.execute(
        "SELECT COUNT(*) FROM fighters"
    ).fetchone()[0]
    expected_events = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    check("B", "metadata fighter_count matches the DB count",
          meta.get("fighter_count") == expected_fighters,
          f"got={meta.get('fighter_count')} expected={expected_fighters}")
    check("B", "metadata event_count matches the DB count",
          meta.get("event_count") == expected_events,
          f"got={meta.get('event_count')} expected={expected_events}")
    check("B", "metadata schema_version matches the code version",
          meta.get("schema_version") == EXPECTED_CODE_VERSION,
          f"got={meta.get('schema_version')!r} expected={EXPECTED_CODE_VERSION!r}")
    # Timestamp should be a valid ISO datetime.
    try:
        datetime.fromisoformat(meta.get("timestamp"))
        ts_valid = True
    except (TypeError, ValueError):
        ts_valid = False
    check("B", "metadata timestamp is a valid ISO datetime",
          ts_valid, f"got={meta.get('timestamp')!r}")

    conn.close()


def case_c_load_restores_db():
    """C. load_game restores the DB (verify data matches).

    D2 — the test saves state, then MODIFIES the DB (deletes events +
    advances the clock), then loads the save and verifies the events
    count + sim_date match the SAVED state (not the modified state).
    """
    print("\n--- Case C: load_game restores the DB ---")
    build_fresh_db()
    clean_saves_dir()
    conn = get_conn()

    # Capture the original state.
    orig_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    orig_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    orig_sim_date = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    orig_cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]

    # Save the current state.
    save_load.save_game(conn, save_name="restore_test")
    conn.close()

    # Modify the DB to simulate "player kept playing" — delete events,
    # advance the clock, change cash.
    conn = get_conn()
    conn.execute("DELETE FROM events")
    conn.execute(
        "UPDATE simulation_clock SET current_date='2027-12-31', "
        "current_day=500 WHERE clock_id=1"
    )
    conn.execute(
        "UPDATE promotions SET current_cash=1 WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    )
    # Also delete some fighters (defensive — cascade should handle it).
    conn.execute("DELETE FROM fighters WHERE fighter_id > 3")
    conn.commit()
    conn.close()

    # Verify the modifications took effect.
    conn = get_conn()
    mod_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    mod_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    check("C", "pre-load: events were deleted (modified state)",
          mod_events == 0, f"events={mod_events}")
    check("C", "pre-load: clock was advanced (modified state)",
          conn.execute(
              "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
          ).fetchone()[0] == "2027-12-31",
          "")
    conn.close()

    # Load the save — this should overwrite the DB with the saved state.
    new_conn = save_load.load_game("restore_test")

    # Verify the loaded state matches the ORIGINAL (pre-modification) state.
    loaded_fighters = new_conn.execute(
        "SELECT COUNT(*) FROM fighters"
    ).fetchone()[0]
    loaded_events = new_conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    loaded_sim_date = new_conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    loaded_cash = new_conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]

    check("C", "load_game returns a sqlite3.Connection",
          isinstance(new_conn, sqlite3.Connection), "")
    check("C", "loaded DB has the original fighter count",
          loaded_fighters == orig_fighters,
          f"loaded={loaded_fighters} orig={orig_fighters}")
    check("C", "loaded DB has the original event count (modifications undone)",
          loaded_events == orig_events,
          f"loaded={loaded_events} orig={orig_events} modified={mod_events}")
    check("C", "loaded DB has the original sim_date (clock restored)",
          loaded_sim_date == orig_sim_date,
          f"loaded={loaded_sim_date!r} orig={orig_sim_date!r}")
    check("C", "loaded DB has the original promotion cash",
          loaded_cash == orig_cash,
          f"loaded={loaded_cash} orig={orig_cash}")
    # foreign_keys pragma should be ON (per the load_game contract).
    fk = new_conn.execute("PRAGMA foreign_keys").fetchone()
    check("C", "loaded DB connection has PRAGMA foreign_keys = ON",
          fk[0] == 1, f"foreign_keys={fk[0]}")

    new_conn.close()

    # Verify load_game raises FileNotFoundError for a non-existent save.
    try:
        save_load.load_game("nonexistent_save_xyz")
        check("C", "load_game raises FileNotFoundError for missing save",
              False, "no exception raised")
    except FileNotFoundError:
        check("C", "load_game raises FileNotFoundError for missing save",
              True, "")
    except Exception as e:
        check("C", "load_game raises FileNotFoundError for missing save",
              False, f"got {type(e).__name__}: {e}")


def case_d_list_saves_returns_info():
    """D. list_saves returns save info."""
    print("\n--- Case D: list_saves returns save info ---")
    build_fresh_db()
    clean_saves_dir()
    conn = get_conn()

    # Save two games with known names.
    save_load.save_game(conn, save_name="save_one")
    save_load.save_game(conn, save_name="save_two")

    saves = save_load.list_saves()

    check("D", "list_saves returns a list",
          isinstance(saves, list), f"type={type(saves).__name__}")
    check("D", "list_saves returns 2 saves (we created 2)",
          len(saves) == 2, f"count={len(saves)}")

    # Verify each save dict has the required keys.
    required_keys = {
        "name", "timestamp", "sim_date", "promotion", "cash",
        "fighters", "events", "schema_version", "is_autosave", "db_path",
    }
    if saves:
        first = saves[0]
        actual_keys = set(first.keys())
        check("D", "each save dict has all required keys",
              required_keys.issubset(actual_keys),
              f"missing={required_keys - actual_keys}")

    # Verify the two known save names are in the list.
    names = {s["name"] for s in saves}
    check("D", "list_saves includes 'save_one'",
          "save_one" in names, f"names={names}")
    check("D", "list_saves includes 'save_two'",
          "save_two" in names, f"names={names}")

    # Verify is_autosave flag is False for manual saves.
    for s in saves:
        if s["name"] in ("save_one", "save_two"):
            check("D", f"is_autosave=False for {s['name']!r}",
                  s["is_autosave"] is False, f"got={s['is_autosave']}")

    # Verify list_saves returns saves sorted by timestamp DESC (newest
    # first). save_two was created AFTER save_one, so save_two should
    # be first.
    if len(saves) == 2:
        # Timestamps might be equal if both saves happened in the same
        # second. Sort stability is the best we can assert.
        ts0 = saves[0].get("timestamp") or ""
        ts1 = saves[1].get("timestamp") or ""
        check("D", "list_saves sorted by timestamp DESC (newest first)",
              ts0 >= ts1, f"ts0={ts0!r} ts1={ts1!r}")

    # Verify list_saves returns [] when the saves dir is empty.
    clean_saves_dir()
    empty = save_load.list_saves()
    check("D", "list_saves returns [] when no saves exist",
          empty == [], f"got={empty}")

    conn.close()


def case_e_delete_save_removes_file():
    """E. delete_save removes the file."""
    print("\n--- Case E: delete_save removes the file ---")
    build_fresh_db()
    clean_saves_dir()
    conn = get_conn()

    save_load.save_game(conn, save_name="to_delete")
    db_path = SAVES_DIR / "to_delete.db"
    json_path = SAVES_DIR / "to_delete.json"

    check("E", "pre-delete: .db file exists",
          db_path.exists(), f"path={db_path}")
    check("E", "pre-delete: .json file exists",
          json_path.exists(), f"path={json_path}")

    # Delete the save.
    deleted = save_load.delete_save("to_delete")
    check("E", "delete_save returns True for an existing save",
          deleted is True, f"got={deleted}")
    check("E", "delete_save removes the .db file",
          not db_path.exists(), f"path={db_path}")
    check("E", "delete_save removes the .json file",
          not json_path.exists(), f"path={json_path}")

    # Verify the save no longer appears in list_saves.
    saves = save_load.list_saves()
    check("E", "deleted save is not in list_saves",
          all(s["name"] != "to_delete" for s in saves),
          f"names={[s['name'] for s in saves]}")

    # Delete a non-existent save — should return False, no crash.
    deleted_again = save_load.delete_save("to_delete")
    check("E", "delete_save returns False for a non-existent save",
          deleted_again is False, f"got={deleted_again}")

    # Delete with a save_name that has unsafe chars — should be
    # sanitized and not crash.
    save_load.save_game(conn, save_name="safe name with spaces")
    # The sanitized name should be "safe_name_with_spaces".
    sanitized_db = SAVES_DIR / "safe_name_with_spaces.db"
    check("E", "save_game sanitizes unsafe chars in save_name",
          sanitized_db.exists(), f"path={sanitized_db}")
    deleted_sanitized = save_load.delete_save("safe name with spaces")
    check("E", "delete_save with unsafe chars removes the file",
          deleted_sanitized is True, "")
    check("E", "post-delete: sanitized .db file is gone",
          not sanitized_db.exists(), "")

    conn.close()


def case_f_auto_save_fires_on_tick_advanced():
    """F. auto_save fires on TICK_ADVANCED (monthly).

    D3 — set simulation_clock.current_day to 30 (a monthly tick),
    publish TICK_ADVANCED, verify an autosave file appears.
    """
    print("\n--- Case F: auto_save fires on TICK_ADVANCED (monthly) ---")
    build_fresh_db()
    clean_saves_dir()
    # Reset the bus to clear prior registrations, then register ONLY
    # the save_load subscriber (isolating auto_save from other systems'
    # TICK_ADVANCED subscribers that might write news items, etc.).
    reset_bus()
    save_load.register_subscribers()

    conn = get_conn()

    # Day 1 (seeded) — should NOT trigger auto-save (1 % 30 != 0).
    publish_tick_advanced(conn, "2026-07-21", 2)
    autosave_count_day2 = len(list(SAVES_DIR.glob("autosave_*.db")))
    check("F", "day 2 (not multiple of 30) → no auto-save",
          autosave_count_day2 == 0,
          f"count={autosave_count_day2}")

    # Day 30 — SHOULD trigger auto-save (30 % 30 == 0).
    publish_tick_advanced(conn, "2026-08-18", 30)
    autosave_count_day30 = len(list(SAVES_DIR.glob("autosave_*.db")))
    check("F", "day 30 (multiple of 30) → auto-save fires",
          autosave_count_day30 == 1,
          f"count={autosave_count_day30}")

    # Day 31 — should NOT trigger auto-save (31 % 30 != 0).
    publish_tick_advanced(conn, "2026-08-19", 31)
    autosave_count_day31 = len(list(SAVES_DIR.glob("autosave_*.db")))
    check("F", "day 31 (not multiple of 30) → no new auto-save",
          autosave_count_day31 == 1,
          f"count={autosave_count_day31}")

    # Day 60 — SHOULD trigger another auto-save.
    publish_tick_advanced(conn, "2026-09-17", 60)
    autosave_count_day60 = len(list(SAVES_DIR.glob("autosave_*.db")))
    check("F", "day 60 (multiple of 30) → 2nd auto-save fires",
          autosave_count_day60 == 2,
          f"count={autosave_count_day60}")

    # Verify the auto-save file has a corresponding .json metadata.
    autosave_jsons = list(SAVES_DIR.glob("autosave_*.json"))
    check("F", "auto-save writes a .json metadata file",
          len(autosave_jsons) >= 1,
          f"json_count={len(autosave_jsons)}")

    # Verify the auto-save name starts with the AUTOSAVE_PREFIX.
    autosave_dbs = list(SAVES_DIR.glob("autosave_*.db"))
    if autosave_dbs:
        first_name = autosave_dbs[0].stem  # filename without .db
        check("F", "auto-save filename starts with 'autosave_'",
              first_name.startswith("autosave_"),
              f"name={first_name!r}")
        # list_saves should tag it as is_autosave=True.
        saves = save_load.list_saves()
        autosave_entries = [s for s in saves if s["is_autosave"]]
        check("F", "list_saves tags auto-saves with is_autosave=True",
              len(autosave_entries) >= 1,
              f"autosave_entries={len(autosave_entries)}")
    else:
        check("F", "auto-save filename starts with 'autosave_'",
              False, "no autosave files found")

    # Verify auto-save is SILENT — capture stdout/stderr to ensure
    # no print to stdout (errors to stderr are OK per the brief).
    # We re-fire a non-monthly tick and check no stdout output.
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        publish_tick_advanced(conn, "2026-09-18", 61)
    check("F", "auto_save is SILENT (no stdout output on non-monthly tick)",
          buf.getvalue() == "",
          f"stdout={buf.getvalue()!r}")

    # And on a monthly tick — also silent.
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        publish_tick_advanced(conn, "2026-10-17", 90)
    check("F", "auto_save is SILENT (no stdout output on monthly tick)",
          buf2.getvalue() == "",
          f"stdout={buf2.getvalue()!r}")

    conn.close()


def case_g_auto_save_keeps_only_3_rotating():
    """G. auto_save keeps only 3 rotating saves.

    D4 — fire 4+ auto-saves, verify only 3 remain. The pruning is
    by mtime (wall-clock), so the test asserts the COUNT, not the
    specific filenames.
    """
    print("\n--- Case G: auto_save keeps only 3 rotating saves ---")
    build_fresh_db()
    clean_saves_dir()
    reset_bus()
    save_load.register_subscribers()

    conn = get_conn()

    # Fire 4 monthly ticks. Each tick triggers an auto-save. After
    # the 4th, _prune_autosaves should delete the oldest, leaving 3.
    # Sleep briefly between ticks to ensure distinct mtimes (the
    # filesystem mtime resolution can be 1 second on some systems).
    monthly_days = [30, 60, 90, 120]
    monthly_dates = ["2026-08-18", "2026-09-17", "2026-10-17", "2026-11-16"]

    for i, (day, date) in enumerate(zip(monthly_days, monthly_dates)):
        publish_tick_advanced(conn, date, day)
        # Small sleep to ensure distinct mtimes (D4).
        time.sleep(0.05)
        count = len(list(SAVES_DIR.glob("autosave_*.db")))
        if i < 2:  # first 3 ticks (i=0,1,2): 1, 2, 3 autosaves
            check("G", f"after tick {i+1}: {i+1} auto-save(s) (no prune yet)",
                  count == i + 1, f"count={count}")
        elif i == 2:  # 3rd tick: exactly 3 autosaves (at the limit)
            check("G", f"after tick {i+1}: 3 auto-saves (at limit)",
                  count == 3, f"count={count}")
        else:  # 4th tick (i=3): should still be 3 (oldest pruned)
            check("G", f"after tick {i+1}: still 3 auto-saves (rotated)",
                  count == 3, f"count={count}")

    # Fire one more (5th monthly tick) to be sure.
    publish_tick_advanced(conn, "2026-12-16", 150)
    time.sleep(0.05)
    final_count = len(list(SAVES_DIR.glob("autosave_*.db")))
    check("G", "after 5 monthly ticks: still 3 auto-saves (rotation holds)",
          final_count == 3, f"count={final_count}")

    # Verify the metadata JSONs are also pruned (count of .json files
    # should match the .db count). HW5.2 writes BOTH a .json AND a
    # .meta.json sidecar per save — count them separately to confirm
    # both are pruned (and that .meta.json files don't inflate the
    # legacy .json glob).
    all_json_files = list(SAVES_DIR.glob("autosave_*.json"))
    # .meta.json files end in ".meta.json" — they ALSO match the
    # "autosave_*.json" glob because both end in ".json". Separate
    # them out.
    meta_json_files = [p for p in all_json_files
                       if p.name.endswith(".meta.json")]
    plain_json_files = [p for p in all_json_files
                        if not p.name.endswith(".meta.json")]
    check("G", "auto-save rotation prunes .json metadata files too",
          len(plain_json_files) == final_count,
          f"json_count={len(plain_json_files)} db_count={final_count}")
    # HW5.2 — .meta.json sidecars are also pruned (one per save).
    check("G", "auto-save rotation prunes .meta.json sidecars too (HW5.2)",
          len(meta_json_files) == final_count,
          f"meta_json_count={len(meta_json_files)} db_count={final_count}")

    # Verify the surviving auto-saves are the NEWEST (by sim_date).
    # The 3 survivors should be from the latest 3 monthly ticks:
    # days 60, 90, 120, 150 → wait, we fired 5 ticks total (days 30,
    # 60, 90, 120, 150). The 3 survivors should be the latest 3:
    # days 90, 120, 150.
    surviving_saves = [s for s in save_load.list_saves() if s["is_autosave"]]
    surviving_sim_dates = sorted({s["sim_date"] for s in surviving_saves})
    expected_survivors = {"2026-10-17", "2026-11-16", "2026-12-16"}
    check("G", "surviving auto-saves are the 3 newest (by sim_date)",
          set(surviving_sim_dates) == expected_survivors,
          f"got={surviving_sim_dates} expected={sorted(expected_survivors)}")

    # Verify manual saves are NOT pruned (only auto-saves are).
    save_load.save_game(conn, save_name="manual_save_1")
    save_load.save_game(conn, save_name="manual_save_2")
    # Fire another auto-save to trigger another prune cycle.
    publish_tick_advanced(conn, "2027-01-15", 180)
    time.sleep(0.05)
    manual_db_1 = SAVES_DIR / "manual_save_1.db"
    manual_db_2 = SAVES_DIR / "manual_save_2.db"
    check("G", "manual saves are NOT pruned (save 1 survives)",
          manual_db_1.exists(), f"path={manual_db_1}")
    check("G", "manual saves are NOT pruned (save 2 survives)",
          manual_db_2.exists(), f"path={manual_db_2}")
    # Auto-save count still 3.
    final_autosave_count = len(list(SAVES_DIR.glob("autosave_*.db")))
    check("G", "auto-save count remains 3 after manual saves added",
          final_autosave_count == 3,
          f"count={final_autosave_count}")

    conn.close()


def case_h_design_law_investment():
    """H. Design Law (§13): Investment (player's progress is preserved).

    D5 — integrated scenario: sign a free agent, advance the clock,
    deduct cash (simulating player progress). Save. Make further
    modifications. Load. Verify ALL progress is restored.
    """
    print("\n--- Case H: Design Law — Investment (progress preserved) ---")
    build_fresh_db()
    clean_saves_dir()
    reset_bus()
    save_load.register_subscribers()

    conn = get_conn()

    # --- Set up "player progress" ---
    # 1. Sign a free agent (set their current_promotion_id to the
    #    player's promotion). Pick a free agent from the seeded DB
    #    (fighters with current_promotion_id IS NULL or != player's).
    # In the small seed, all 5 fighters are signed to AC or RFL.
    # For the test, we'll mark fighter_id=3 (Dario Knox, RFL) as
    # a free agent first, then sign him to AC.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=3"
    )
    conn.commit()
    free_agent_count_before = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE current_promotion_id IS NULL"
    ).fetchone()[0]
    check("H", "setup: created a free agent (fighter_id=3)",
          free_agent_count_before == 1,
          f"free_agents={free_agent_count_before}")

    # Sign him to the player's promotion (the "Investment" — the
    # player scouted + signed this fighter).
    conn.execute(
        "UPDATE fighters SET current_promotion_id=? WHERE fighter_id=3",
        (PLAYER_PROMOTION_ID,),
    )
    # Advance the clock by 30 sim days (player kept playing).
    conn.execute(
        "UPDATE simulation_clock SET current_date='2026-08-19', "
        "current_day=31 WHERE clock_id=1"
    )
    # Deduct cash (the player spent money on the signing).
    conn.execute(
        "UPDATE promotions SET current_cash=50000 WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    )
    # Add a new event (player scheduled a show).
    conn.execute(
        "INSERT INTO events (promotion_id, venue_id, market_id, "
        "event_name, event_date, event_type, status) "
        "VALUES (?, 1, 1, 'Test Event', '2026-09-15', 'fight_night', 'scheduled')",
        (PLAYER_PROMOTION_ID,),
    )
    conn.commit()

    # Capture the "progress" state.
    progress_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    progress_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    progress_sim_date = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    progress_cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]
    progress_signed = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE current_promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]

    check("H", "progress: clock advanced to 2026-08-19",
          progress_sim_date == "2026-08-19", f"got={progress_sim_date}")
    check("H", "progress: cash deducted to 50000",
          progress_cash == 50000, f"got={progress_cash}")
    check("H", "progress: free agent signed to player promotion",
          progress_signed >= 1, f"signed={progress_signed}")
    check("H", "progress: new event scheduled",
          progress_events >= 1, f"events={progress_events}")

    # --- Save the game ---
    save_name = save_load.save_game(conn, save_name="progress_save")
    check("H", "save_game succeeds for the progress save",
          save_name == "progress_save", f"got={save_name}")
    conn.close()

    # --- "Catastrophe" — wipe the DB entirely ---
    # (Simulating: the player closes the game without saving, then
    # the DB gets corrupted / reset.)
    conn = get_conn()
    conn.execute("DELETE FROM events")
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL "
        "WHERE current_promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    )
    conn.execute(
        "UPDATE simulation_clock SET current_date='2026-07-20', "
        "current_day=1 WHERE clock_id=1"
    )
    conn.execute(
        "UPDATE promotions SET current_cash=0 WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    )
    conn.commit()
    wiped_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    wiped_sim_date = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    wiped_cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]
    check("H", "catastrophe: events wiped",
          wiped_events == 0, f"events={wiped_events}")
    check("H", "catastrophe: clock reset to 2026-07-20",
          wiped_sim_date == "2026-07-20", f"got={wiped_sim_date}")
    check("H", "catastrophe: cash reset to 0",
          wiped_cash == 0, f"got={wiped_cash}")
    conn.close()

    # --- Load the save — the "Investment" is preserved ---
    new_conn = save_load.load_game("progress_save")
    restored_events = new_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    restored_sim_date = new_conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    restored_cash = new_conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]
    restored_signed = new_conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE current_promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]
    restored_fighters = new_conn.execute(
        "SELECT COUNT(*) FROM fighters"
    ).fetchone()[0]

    # The Investment pillar: the player's progress is preserved.
    check("H", "Investment: events restored (progress preserved)",
          restored_events == progress_events,
          f"restored={restored_events} progress={progress_events} wiped={wiped_events}")
    check("H", "Investment: sim_date restored (progress preserved)",
          restored_sim_date == progress_sim_date,
          f"restored={restored_sim_date!r} progress={progress_sim_date!r}")
    check("H", "Investment: cash restored (progress preserved)",
          restored_cash == progress_cash,
          f"restored={restored_cash} progress={progress_cash} wiped={wiped_cash}")
    check("H", "Investment: signed fighter still signed (progress preserved)",
          restored_signed == progress_signed,
          f"restored={restored_signed} progress={progress_signed}")
    check("H", "Investment: fighter roster intact (progress preserved)",
          restored_fighters == progress_fighters,
          f"restored={restored_fighters} progress={progress_fighters}")

    # --- Anticipation (the "what's next?" thread) ---
    # The restored DB has a scheduled event — the player can keep
    # playing from where they left off. The sim is in the SAME state
    # as when they saved. This is the foundation of the Historian
    # fantasy: the player can come back tomorrow to the empire they
    # built today.
    scheduled_events = new_conn.execute(
        "SELECT COUNT(*) FROM events WHERE status='scheduled'"
    ).fetchone()[0]
    check("H", "Anticipation: scheduled events preserved (player can resume)",
          scheduled_events >= 1, f"scheduled={scheduled_events}")

    # --- Historian fantasy foundation ---
    # The fighter the player signed is still in their roster. The
    # career history, attribute gains, and title reigns from this
    # session are all preserved in the save. Tomorrow, the player
    # can load this save and see the empire they built.
    signed_fighter = new_conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id=3"
    ).fetchone()
    check("H", "Historian: signed fighter preserved in roster",
          signed_fighter is not None and signed_fighter[0],
          f"fighter={signed_fighter}")

    # --- Event bus (CONVENTIONS §15.4) ---
    # save_load registers 1 TICK_ADVANCED subscriber (auto_save).
    bus = get_bus()
    tick_subs = bus.subscriber_count(Events.TICK_ADVANCED)
    check("H", f"Event bus: save_load TICK_ADVANCED subscriber registered",
          tick_subs >= 1, f"TICK_ADVANCED subs={tick_subs}")

    new_conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print(f"Stage 5 — Save/Load System (Task ID Stage5-SaveLoad)")
    print(f"(schema {EXPECTED_CODE_VERSION}, no schema change in this task)")
    print(sep)

    try:
        case_a_save_creates_db_file()
        case_b_save_writes_metadata_json()
        case_c_load_restores_db()
        case_d_list_saves_returns_info()
        case_e_delete_save_removes_file()
        case_f_auto_save_fires_on_tick_advanced()
        case_g_auto_save_keeps_only_3_rotating()
        case_h_design_law_investment()
    finally:
        # Clean up test artifacts so we don't leave save files lying
        # around in data/saves/ (which is gitignored, but cleaner to
        # leave nothing).
        clean_saves_dir()

    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2] and not r[4])
    n_fail = sum(1 for r in results if not r[2] and not r[4])
    n_skip = sum(1 for r in results if r[4])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL, {n_skip} SKIP")
    print("=" * 80)
    # Exit 0 if no failures (skips are OK).
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
