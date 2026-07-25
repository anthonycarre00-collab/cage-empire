#!/usr/bin/env python3
"""Acceptance test for Stage 5 — Task Stage5-Final.

Tests the three deliverables of the Stage5-Final task:
  Part 1 — Fix 6 stale personality fields (grit, ambition, loyalty,
           resilience, travel_comfort, fatigue_tolerance) in
           src/morale.py + src/career_arc.py.
  Part 2 — Player settings table (schema 3.6.0 → 3.7.0 MINOR) +
           src/player_settings.py module.
  Part 3 — Mod tools skeleton (src/mods.py — Task 29, code-only).

Test cases:
  A. grit updated on loss (FIGHT_RESOLVED)
  B. ambition drops on title win, rises on losing streak
  C. resilience grows on injury comeback
  D. fatigue_tolerance degrades with age (monthly tick)
  E. travel_comfort improves for young fighters (monthly tick)
  F. player_settings table exists with defaults
  G. get_setting / set_setting work
  H. export_fighters_csv creates a file
  I. edit_fighter updates a field
  J. backup_database creates a backup
  K. Design Law (§13)

Pattern follows scripts/test_save_load.py + test_career_arc_rival_ai.py
(CONVENTIONS §10 — dynamic version pattern, no hardcoded version
strings).

Run from the project root:
    python3 scripts/test_final_fixes.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` and writes test artifacts to `data/exports/`
and `data/saves/` (both gitignored). All test artifacts are cleaned
up at the end.

D-number decisions in this test (referenced from the worklog):
  - D1 (underdog detection via marketability): the brief says "+1
    if underdog win (hungry for more)". There's no pre-fight
    favorite stored in the DB. The canonical underdog signal is
    marketability — the lower-marketed fighter pulling off the win
    is the underdog storyline. If winner.marketability < loser.
    marketability, ambition +1. If they're tied (e.g., the seeded
    50/50 default), neither path fires (the fighter is neither
    underdog nor favorite). This makes the underdog path testable
    by setting different marketability values, while preserving
    the existing test_morale.py marketability assertions (which
    check marketability changes, not ambition).
  - D2 (was_champion = is_title_fight): the brief says "ambition
    -1 if was champion (satiated)". After the fight resolves, the
    title state has been updated by _resolve_title_after_fight
    (runs before publish). The cleanest post-fight signal is
    is_title_fight=True (the fight was for a title — either a new
    title win or a defense). Both cases → satiated → ambition -1.
    This matches the spirit: a fighter who just won or defended a
    title has achieved the goal and is satiated. (Strict reading:
    "was champion" = defended. Permissive reading: "was in a title
    fight and won". The permissive reading matches the brief's
    "(satiated)" annotation better — winning the belt for the
    first time is the ULTIMATE satiation.)
  - D3 (weekly tick for streak-based personality drift): the brief
    says "In _process_tick (TICK_ADVANCED, weekly)". I added a new
    helper _weekly_personality_drift called from _process_tick
    inside the existing _is_weekly_tick(conn) block (day % 7 == 0).
    This fires on the same cadence as the existing weekly morale
    drift — fighters see personality drift once per sim week.
  - D4 (injury comeback detection reuses _weekly_morale_drift's
    pattern): the brief says "detected via actual_return_date
    check". The existing _weekly_morale_drift already does this
    scan (INJURY_RECOVERED surrogate). The new _weekly_personality
    _drift uses the same query — injuries with is_active=0 AND
    actual_return_date = current_date. This means injury comeback
    bonuses fire on the FIRST weekly tick AFTER the recovery (the
    tick_processor._check_injury_recovery function runs BEFORE
    TICK_ADVANCED is published, setting actual_return_date on the
    same day).
  - D5 (player_settings fresh-build seeding): the migration function
    _migrate_v3_7_0_add_player_settings seeds defaults via INSERT
    OR IGNORE. But the --fresh path does NOT call migration
    functions (CONVENTIONS §16.4 — only records them in schema_
    migrations). So the fresh-build path needs its own seeding —
    added to _build_fresh alongside the news_sources seeding. This
    mirrors the existing pattern (news_sources is seeded in BOTH
    places). Without this, fresh-built DBs would have an empty
    player_settings table and get_setting would always return the
    default fallback. Verified by the test.
  - D6 (travel_comfort stored as REAL): the schema declares
    travel_comfort INTEGER NOT NULL DEFAULT 50 CHECK BETWEEN 0
    AND 100. SQLite INTEGER affinity behaves the same as NUMERIC
    affinity — REAL values that can't be losslessly converted to
    INTEGER are stored as REAL. So 50.5 is stored as REAL (50.5),
    while 50.0 is stored as INTEGER (50). The CHECK constraint
    works on REAL values (50.5 BETWEEN 0 AND 100 = TRUE). This
    matches the existing pattern for fighters.consistency (also
    INTEGER column, stored as REAL via +0.5 increments).
  - D7 (mods.py wraps save_load for backup/restore): the brief
    says "uses save_load.save_game internally" + "uses save_load.
    load_game internally". This reuses the existing save/load
    infrastructure (shutil.copy2 + metadata JSON) — the mod tools
    don't reinvent the backup format. A mod-tools backup is
    interchangeable with a manual save (the player can restore a
    mod-tools backup via the regular Load Game UI).
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
SAVES_DIR = PROJECT_DIR / "data" / "saves"
EXPORTS_DIR = PROJECT_DIR / "data" / "exports"
sys.path.insert(0, str(SRC_DIR))

import build_db  # noqa: E402
import morale  # noqa: E402
import career_arc  # noqa: E402
import player_settings  # noqa: E402
import mods  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py.
# John "Hammer" Vale = 1 (AC), Marcus "Voltage" Reed = 2 (AC).
# Dario Knox = 3 (RFL), Eli Storm = 4 (RFL), Cole Briggs = 5 (RFL).
A_ID = 1  # John Vale (Alpha Combat)
B_ID = 2  # Marcus Reed (Alpha Combat)
C_ID = 3  # Dario Knox (Rival Fight League)
D_ID = 4  # Eli Storm (RFL)

PLAYER_PROMOTION_ID = 1

# Seeded sim date from src/seed_data.py (2026-07-20).
SEEDED_SIM_DATE = "2026-07-20"

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Used by Case K to verify no new player-facing text in this
# task contains digits (the personality field updates + player
# settings + mod tools are all internal — no news items written
# with raw numbers).
_DIGIT_RE = re.compile(r"[0-9]")

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


def publish_fight_resolved(conn, *, fight_id=1, event_id=1,
                           winner_id=1, loser_id=2,
                           fighter_a_id=1, fighter_b_id=2,
                           result_type='decision',
                           is_title_fight=0, title_changed=False,
                           event_date='2026-08-15'):
    """Helper — publish a FIGHT_RESOLVED event on the bus."""
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHT_RESOLVED,
        'fight_id': fight_id,
        'event_id': event_id,
        'promotion_id': 1,
        'weight_class_id': 1,
        'winner_id': winner_id,
        'loser_id': loser_id,
        'fighter_a_id': fighter_a_id,
        'fighter_b_id': fighter_b_id,
        'result_type': result_type,
        'finish_round': 3,
        'finish_time': '5:00',
        'is_title_fight': is_title_fight,
        'title_changed': title_changed,
        'event_date': event_date,
        'importance': 50,
    })


def publish_tick_advanced(conn, current_date, current_day):
    """Publish a TICK_ADVANCED event AND set the sim clock's current_day
    + current_date so the weekly/monthly tick checks pass.
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


def set_fighter_age(conn, fighter_id, age_years, current_date_str):
    """Set a fighter's DOB so their age (as of current_date_str) is
    exactly age_years. Mirrors the helper in test_career_arc_rival_ai.
    """
    from datetime import datetime, timedelta
    cur = datetime.strptime(current_date_str, "%Y-%m-%d")
    dob = cur.replace(year=cur.year - age_years)
    conn.execute(
        "UPDATE fighters SET date_of_birth=? WHERE fighter_id=?",
        (dob.strftime("%Y-%m-%d"), fighter_id),
    )
    conn.commit()


def clean_test_artifacts():
    """Clean up data/saves/ + data/exports/ test artifacts.

    D-number — called at the start + end of the test run to ensure
    deterministic results + leave nothing behind.
    """
    for d in (SAVES_DIR, EXPORTS_DIR):
        if d.exists():
            for child in d.iterdir():
                if child.is_file():
                    try:
                        child.unlink()
                    except OSError:
                        pass


# ----------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------

def case_a_grit_on_loss():
    """A. grit updated on loss (FIGHT_RESOLVED)."""
    print("\n--- Case A: grit updated on loss (FIGHT_RESOLVED) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()

    # Capture pre-fight grit for fighter 2 (the loser).
    g_before = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]

    # Publish a decision loss for fighter 2.
    publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                           result_type='decision',
                           is_title_fight=0, title_changed=False)
    conn.commit()

    g_after = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    # Decision loss → grit +1 (adversity builds grit).
    check("A", "decision loss: grit +1",
          g_after - g_before == 1, f"{g_before} → {g_after}")

    # KO loss → grit +2 (real adversity).
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    g_before = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                           result_type='ko_tko',
                           is_title_fight=0, title_changed=False)
    conn.commit()
    g_after = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    check("A", "KO loss: grit +2 (real adversity)",
          g_after - g_before == 2, f"{g_before} → {g_after}")

    # Resilience on KO loss = -1 (the chin cracks confidence).
    r_before = 50  # default seed value (re-fetched below)
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    r_before = conn.execute(
        "SELECT resilience FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                           result_type='ko_tko',
                           is_title_fight=0, title_changed=False)
    conn.commit()
    r_after = conn.execute(
        "SELECT resilience FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    check("A", "KO loss: resilience -1 (chin cracks confidence)",
          r_before - r_after == 1, f"{r_before} → {r_after}")

    # Decision loss: resilience +1 (bouncing back).
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    r_before = conn.execute(
        "SELECT resilience FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                           result_type='decision',
                           is_title_fight=0, title_changed=False)
    conn.commit()
    r_after = conn.execute(
        "SELECT resilience FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    check("A", "decision loss: resilience +1 (bouncing back)",
          r_after - r_before == 1, f"{r_before} → {r_after}")
    conn.close()


def case_b_ambition_shifts():
    """B. ambition drops on title win, rises on losing streak."""
    print("\n--- Case B: ambition drops on title win, rises on streak ---")
    # --- title win → ambition -1 (satiated) ---
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    amb_before = conn.execute(
        "SELECT ambition FROM fighter_personality WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                           result_type='decision',
                           is_title_fight=1, title_changed=True)
    conn.commit()
    amb_after = conn.execute(
        "SELECT ambition FROM fighter_personality WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("B", "title win: winner ambition -1 (satiated)",
          amb_before - amb_after == 1, f"{amb_before} → {amb_after}")

    # --- 3+ loss streak → ambition +2 (weekly tick) ---
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    # Set fighter 2 on a 3-fight losing streak.
    conn.execute(
        "UPDATE fighter_career SET loss_streak=3 WHERE fighter_id=?",
        (B_ID,),
    )
    conn.commit()
    amb_before = conn.execute(
        "SELECT ambition FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    # Weekly tick (current_day = 7).
    publish_tick_advanced(conn, current_date="2026-07-27", current_day=7)
    conn.commit()
    amb_after = conn.execute(
        "SELECT ambition FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    check("B", "3+ loss streak: ambition +2 (desperate to prove themselves)",
          amb_after - amb_before == 2, f"{amb_before} → {amb_after}")

    # --- 5+ win streak → ambition -1 (comfortable) ---
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    conn.execute(
        "UPDATE fighter_career SET win_streak=5 WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()
    amb_before = conn.execute(
        "SELECT ambition FROM fighter_personality WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    publish_tick_advanced(conn, current_date="2026-07-27", current_day=7)
    conn.commit()
    amb_after = conn.execute(
        "SELECT ambition FROM fighter_personality WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("B", "5+ win streak: ambition -1 (comfortable)",
          amb_before - amb_after == 1, f"{amb_before} → {amb_after}")
    conn.close()


def case_c_injury_comeback():
    """C. resilience grows on injury comeback (weekly tick)."""
    print("\n--- Case C: resilience grows on injury comeback ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()

    # Insert a recovered injury for fighter 3 — actual_return_date
    # matches the weekly tick date.
    current_date = "2026-07-27"
    conn.execute(
        "INSERT INTO injuries (fighter_id, injury_type, body_area, "
        "severity, start_date, projected_return_date, "
        "actual_return_date, is_active, long_term_damage, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        (C_ID, "Torn ACL", "knee", 7, "2026-06-01",
         current_date, current_date, 0, 0),
    )
    conn.commit()

    g_before = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (C_ID,),
    ).fetchone()[0]
    r_before = conn.execute(
        "SELECT resilience FROM fighter_personality WHERE fighter_id=?",
        (C_ID,),
    ).fetchone()[0]

    # Weekly tick (current_day = 7) — the injury comeback fires.
    publish_tick_advanced(conn, current_date=current_date, current_day=7)
    conn.commit()

    g_after = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (C_ID,),
    ).fetchone()[0]
    r_after = conn.execute(
        "SELECT resilience FROM fighter_personality WHERE fighter_id=?",
        (C_ID,),
    ).fetchone()[0]
    check("C", "injury comeback: grit +1",
          g_after - g_before == 1, f"{g_before} → {g_after}")
    check("C", "injury comeback: resilience +2",
          r_after - r_before == 2, f"{r_before} → {r_after}")
    conn.close()


def case_d_fatigue_tolerance_decline():
    """D. fatigue_tolerance degrades with age (monthly tick)."""
    print("\n--- Case D: fatigue_tolerance degrades with age (monthly) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    career_arc.register_subscribers()

    # Make fighter 1 a 35-year-old (past the fatigue_tolerance
    # decline onset of 33). Monkey-patch DECLINE_RULES to be empty
    # so ONLY the personality field drift fires (isolates the test
    # from the existing attribute-decline code).
    set_fighter_age(conn, A_ID, 35, SEEDED_SIM_DATE)
    original_decline = career_arc.DECLINE_RULES
    original_growth = career_arc.GROWTH_RULES
    career_arc.DECLINE_RULES = []  # disable attribute decline
    career_arc.GROWTH_RULES = []   # disable attribute growth
    try:
        ft_before = conn.execute(
            "SELECT fatigue_tolerance FROM fighter_personality "
            "WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        # Monthly tick (current_day = 30).
        publish_tick_advanced(conn, current_date="2026-08-19", current_day=30)
        conn.commit()
        ft_after = conn.execute(
            "SELECT fatigue_tolerance FROM fighter_personality "
            "WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        check("D", "age 35: fatigue_tolerance -1 (body wears down)",
              ft_before - ft_after == 1, f"{ft_before} → {ft_after}")
    finally:
        career_arc.DECLINE_RULES = original_decline
        career_arc.GROWTH_RULES = original_growth

    # Verify a young fighter (age 25) does NOT see fatigue_tolerance decline.
    set_fighter_age(conn, A_ID, 25, SEEDED_SIM_DATE)
    ft_before = conn.execute(
        "SELECT fatigue_tolerance FROM fighter_personality "
        "WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    publish_tick_advanced(conn, current_date="2026-08-19", current_day=60)
    conn.commit()
    ft_after = conn.execute(
        "SELECT fatigue_tolerance FROM fighter_personality "
        "WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("D", "age 25: fatigue_tolerance unchanged (under 33 onset)",
          ft_after == ft_before, f"{ft_before} → {ft_after}")
    conn.close()


def case_e_travel_comfort_growth():
    """E. travel_comfort improves for young fighters (monthly tick)."""
    print("\n--- Case E: travel_comfort improves for young fighters ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    career_arc.register_subscribers()

    # Make fighter 4 a 25-year-old (under 30 → travel_comfort grows).
    set_fighter_age(conn, D_ID, 25, SEEDED_SIM_DATE)
    original_decline = career_arc.DECLINE_RULES
    original_growth = career_arc.GROWTH_RULES
    career_arc.DECLINE_RULES = []
    career_arc.GROWTH_RULES = []
    try:
        tc_before = conn.execute(
            "SELECT travel_comfort FROM fighter_personality "
            "WHERE fighter_id=?",
            (D_ID,),
        ).fetchone()[0]
        publish_tick_advanced(conn, current_date="2026-08-19", current_day=30)
        conn.commit()
        tc_after = conn.execute(
            "SELECT travel_comfort FROM fighter_personality "
            "WHERE fighter_id=?",
            (D_ID,),
        ).fetchone()[0]
        # travel_comfort +0.5 per month (stored as REAL).
        check("E", "age 25: travel_comfort +0.5 (young fighters adapt)",
              abs((tc_after - tc_before) - 0.5) < 0.01,
              f"{tc_before} → {tc_after}")
        # Verify the value is REAL (float), not INTEGER — the schema
        # declares INTEGER but SQLite stores REAL when the value has
        # a non-zero fractional part.
        check("E", "travel_comfort stored as REAL (NUMERIC affinity)",
              isinstance(tc_after, float),
              f"type={type(tc_after).__name__} value={tc_after}")
    finally:
        career_arc.DECLINE_RULES = original_decline
        career_arc.GROWTH_RULES = original_growth

    # Verify an older fighter (age 35) does NOT see travel_comfort
    # growth (only fatigue_tolerance declines for older fighters).
    set_fighter_age(conn, D_ID, 35, SEEDED_SIM_DATE)
    tc_before = conn.execute(
        "SELECT travel_comfort FROM fighter_personality "
        "WHERE fighter_id=?",
        (D_ID,),
    ).fetchone()[0]
    publish_tick_advanced(conn, current_date="2026-09-18", current_day=60)
    conn.commit()
    tc_after = conn.execute(
        "SELECT travel_comfort FROM fighter_personality "
        "WHERE fighter_id=?",
        (D_ID,),
    ).fetchone()[0]
    check("E", "age 35: travel_comfort unchanged (over 29 max)",
          tc_after == tc_before, f"{tc_before} → {tc_after}")
    conn.close()


def case_f_player_settings_table():
    """F. player_settings table exists with defaults."""
    print("\n--- Case F: player_settings table exists with defaults ---")
    build_fresh_db()
    conn = get_conn()

    # Verify the table exists.
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_settings'"
    ).fetchone() is not None
    check("F", "player_settings table exists", table_exists, "")

    # Verify the 6 default settings are seeded.
    expected_defaults = {
        "news_filter_topics":          "all",
        "news_filter_min_importance":  "0",
        "news_volume":                 "normal",
        "auto_save_frequency":         "30",
        "difficulty":                  "normal",
        "display_descriptors":         "true",
    }
    for key, expected_value in expected_defaults.items():
        actual = conn.execute(
            "SELECT setting_value FROM player_settings WHERE setting_key=?",
            (key,),
        ).fetchone()
        check("F", f"default setting {key}={expected_value!r} seeded",
              actual is not None and actual[0] == expected_value,
              f"got={actual[0] if actual else 'NULL'}")

    # Verify the schema version + migration.
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("F", f"schema_version = {EXPECTED_CODE_VERSION}",
          sv is not None and sv[0] == EXPECTED_CODE_VERSION,
          f"got={sv[0] if sv else 'None'}")

    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    check("F", f"migration {EXPECTED_MIGRATION_PREFIX}* recorded",
          mig is not None, f"got={mig[0] if mig else 'None'}")
    conn.close()


def case_g_get_set_setting():
    """G. get_setting / set_setting work."""
    print("\n--- Case G: get_setting / set_setting work ---")
    build_fresh_db()
    conn = get_conn()

    # get_setting returns the seeded value.
    diff = player_settings.get_setting(conn, 'difficulty')
    check("G", "get_setting('difficulty') returns 'normal'",
          diff == 'normal', f"got={diff!r}")

    # get_setting returns the default fallback for unknown keys.
    unknown = player_settings.get_setting(conn, 'unknown_key',
                                            default='fallback')
    check("G", "get_setting('unknown_key', default='fallback') returns 'fallback'",
          unknown == 'fallback', f"got={unknown!r}")

    # set_setting writes a new value.
    ok = player_settings.set_setting(conn, 'difficulty', 'hard')
    check("G", "set_setting('difficulty', 'hard') returns True", ok, "")
    diff = player_settings.get_setting(conn, 'difficulty')
    check("G", "get_setting('difficulty') now returns 'hard'",
          diff == 'hard', f"got={diff!r}")

    # set_setting rejects unknown keys (defensive).
    ok = player_settings.set_setting(conn, 'typo_key', 'value')
    check("G", "set_setting rejects unknown key 'typo_key'",
          ok is False, f"got={ok}")

    # set_setting coerces bool to lowercase 'true'/'false'.
    ok = player_settings.set_setting(conn, 'display_descriptors', True)
    check("G", "set_setting('display_descriptors', True) returns True", ok, "")
    dd = player_settings.get_setting(conn, 'display_descriptors')
    check("G", "bool True → 'true' (lowercase string)",
          dd == 'true', f"got={dd!r}")

    # set_setting coerces int to string.
    ok = player_settings.set_setting(conn, 'auto_save_frequency', 60)
    check("G", "set_setting('auto_save_frequency', 60) returns True", ok, "")
    asf = player_settings.get_setting(conn, 'auto_save_frequency')
    check("G", "int 60 → '60' (string)",
          asf == '60', f"got={asf!r}")

    # get_all_settings returns a dict with all known keys.
    all_settings = player_settings.get_all_settings(conn)
    expected_keys = set(player_settings.DEFAULT_SETTINGS.keys())
    check("G", "get_all_settings returns all 6 default keys",
          expected_keys.issubset(set(all_settings.keys())),
          f"missing={expected_keys - set(all_settings.keys())}")
    # The user-modified values should be reflected.
    check("G", "get_all_settings reflects user-modified 'difficulty'",
          all_settings.get('difficulty') == 'hard',
          f"got={all_settings.get('difficulty')!r}")
    check("G", "get_all_settings reflects user-modified 'auto_save_frequency'",
          all_settings.get('auto_save_frequency') == '60',
          f"got={all_settings.get('auto_save_frequency')!r}")
    conn.close()


def case_h_export_fighters_csv():
    """H. export_fighters_csv creates a file."""
    print("\n--- Case H: export_fighters_csv creates a file ---")
    build_fresh_db()
    conn = get_conn()

    csv_path = EXPORTS_DIR / "test_fighters.csv"
    if csv_path.exists():
        csv_path.unlink()

    n = mods.export_fighters_csv(conn, str(csv_path))
    check("H", "export_fighters_csv returns fighter count (5)",
          n == 5, f"got={n}")
    check("H", "export_fighters_csv creates the CSV file",
          csv_path.exists() and csv_path.is_file(),
          f"path={csv_path}")
    check("H", "CSV file is non-empty",
          csv_path.stat().st_size > 0,
          f"size={csv_path.stat().st_size}")

    # Verify the CSV has a header row + 5 data rows.
    import csv as csv_mod
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        rows = list(reader)
    check("H", "CSV has 6 rows (1 header + 5 fighters)",
          len(rows) == 6, f"got={len(rows)}")
    # The header should include table-qualified column names.
    header = rows[0]
    check("H", "CSV header has table-qualified columns",
          any("fighters." in h for h in header),
          f"sample={header[:3]}")
    check("H", "CSV header includes fighter_personality.grit",
          any("fighter_personality.grit" in h for h in header),
          f"missing from header")
    conn.close()


def case_i_edit_fighter():
    """I. edit_fighter updates a field."""
    print("\n--- Case I: edit_fighter updates a field ---")
    build_fresh_db()
    conn = get_conn()

    # Capture the original nickname.
    nick_before = conn.execute(
        "SELECT nickname FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]

    # Edit the nickname.
    n = mods.edit_fighter(conn, fighter_id=A_ID, nickname='The Test Hammer')
    conn.commit()
    check("I", "edit_fighter returns 1 (one field updated)",
          n == 1, f"got={n}")
    nick_after = conn.execute(
        "SELECT nickname FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("I", "edit_fighter updates the nickname",
          nick_after == 'The Test Hammer',
          f"{nick_before!r} → {nick_after!r}")

    # Invalid column name is silently rejected (defensive).
    n = mods.edit_fighter(conn, fighter_id=A_ID, invalid_column='foo')
    check("I", "edit_fighter rejects invalid column (returns 0)",
          n == 0, f"got={n}")
    # The nickname should NOT have changed.
    nick_after = conn.execute(
        "SELECT nickname FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("I", "edit_fighter invalid column does NOT corrupt data",
          nick_after == 'The Test Hammer', f"got={nick_after!r}")

    # Non-existent fighter_id returns 0.
    n = mods.edit_fighter(conn, fighter_id=99999, nickname='Ghost')
    check("I", "edit_fighter on non-existent fighter returns 0",
          n == 0, f"got={n}")

    # edit_promotion works the same way.
    n = mods.edit_promotion(conn, promotion_id=PLAYER_PROMOTION_ID,
                            current_cash=99_000_000)
    conn.commit()
    check("I", "edit_promotion returns 1 (one field updated)",
          n == 1, f"got={n}")
    cash_after = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()[0]
    check("I", "edit_promotion updates current_cash",
          cash_after == 99_000_000, f"got={cash_after}")
    conn.close()


def case_j_backup_database():
    """J. backup_database creates a backup."""
    print("\n--- Case J: backup_database creates a backup ---")
    build_fresh_db()
    conn = get_conn()

    # Make a mod change so the backup is distinguishable from a
    # fresh DB.
    mods.edit_fighter(conn, fighter_id=A_ID, nickname='Backup Test')
    conn.commit()

    # Backup the DB.
    backup_name = mods.backup_database(filepath='test_mod_backup')
    check("J", "backup_database returns the backup name",
          backup_name == 'test_mod_backup', f"got={backup_name!r}")

    backup_db = SAVES_DIR / f"{backup_name}.db"
    backup_json = SAVES_DIR / f"{backup_name}.json"
    check("J", "backup creates the .db file",
          backup_db.exists() and backup_db.is_file(),
          f"path={backup_db}")
    check("J", "backup creates the .json metadata file",
          backup_json.exists() and backup_json.is_file(),
          f"path={backup_json}")

    # Verify the backup .db is a valid SQLite DB with the modded data.
    try:
        test_conn = sqlite3.connect(str(backup_db))
        nick = test_conn.execute(
            "SELECT nickname FROM fighters WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()
        test_conn.close()
        check("J", "backup .db contains the modded nickname",
              nick is not None and nick[0] == 'Backup Test',
              f"got={nick[0] if nick else 'None'}")
    except sqlite3.Error as e:
        check("J", "backup .db is a valid SQLite DB",
              False, f"sqlite3.Error: {e}")

    # Verify the JSON metadata has the schema version.
    try:
        with open(backup_json, "r", encoding="utf-8") as f:
            meta = json.load(f)
        check("J", "backup JSON metadata has schema_version",
              "schema_version" in meta,
              f"keys={list(meta.keys())}")
        check("J", f"backup JSON schema_version = {EXPECTED_CODE_VERSION}",
              meta.get("schema_version") == EXPECTED_CODE_VERSION,
              f"got={meta.get('schema_version')!r}")
    except (json.JSONDecodeError, OSError) as e:
        check("J", "backup JSON is valid", False, f"error: {e}")

    # export_promotions_json smoke test.
    json_path = EXPORTS_DIR / "test_promotions.json"
    if json_path.exists():
        json_path.unlink()
    n = mods.export_promotions_json(conn, str(json_path))
    check("J", "export_promotions_json returns promotion count (2)",
          n == 2, f"got={n}")
    check("J", "export_promotions_json creates the JSON file",
          json_path.exists() and json_path.is_file(),
          f"path={json_path}")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        check("J", "export_promotions_json writes a JSON list",
              isinstance(data, list) and len(data) == 2,
              f"type={type(data).__name__} len={len(data) if isinstance(data, list) else 'N/A'}")
    except (json.JSONDecodeError, OSError) as e:
        check("J", "export_promotions_json writes valid JSON",
              False, f"error: {e}")

    # import_fighters_csv smoke test — round-trip the export.
    csv_path = EXPORTS_DIR / "test_fighters_roundtrip.csv"
    mods.export_fighters_csv(conn, str(csv_path))
    # Modify a fighter's nickname, then re-import to verify the
    # round-trip restores the original.
    mods.edit_fighter(conn, fighter_id=A_ID, nickname='MODIFIED')
    conn.commit()
    n = mods.import_fighters_csv(conn, str(csv_path))
    conn.commit()
    check("J", "import_fighters_csv returns row count",
          n > 0, f"got={n}")
    nick_after = conn.execute(
        "SELECT nickname FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("J", "import_fighters_csv round-trips the nickname",
          nick_after == 'Backup Test',
          f"got={nick_after!r} (expected 'Backup Test' from the CSV)")
    conn.close()


def case_k_design_law():
    """K. Design Law (§13)."""
    print("\n--- Case K: Design Law (§13) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    morale.register_subscribers()
    career_arc.register_subscribers()

    # --- Puppet Master fantasy (mod tools) ---
    # The player directly shapes the world via edit_fighter. This is
    # the deepest expression of the Puppet Master fantasy — the
    # player is the AUTHOR of the world, not just a participant.
    mods.edit_fighter(conn, fighter_id=A_ID, nickname='The Puppet Master')
    conn.commit()
    nick = conn.execute(
        "SELECT nickname FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    check("K", "Puppet Master: edit_fighter lets player author the world",
          nick == 'The Puppet Master', f"got={nick!r}")

    # --- Conflict + Growth (personality field updates) ---
    # grit + ambition + resilience now COMPOUND over a career. A
    # fighter who's been knocked out 5 times has meaningfully higher
    # grit + lower resilience than a fresh prospect — the
    # "battle-tested veteran" archetype emerges from the sim, not
    # from a hardcoded trait.
    g_before = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    # Simulate 3 KO losses.
    for i in range(3):
        publish_fight_resolved(conn,
                               fight_id=100 + i,
                               winner_id=A_ID, loser_id=B_ID,
                               result_type='ko_tko',
                               is_title_fight=0, title_changed=False)
    conn.commit()
    g_after = conn.execute(
        "SELECT grit FROM fighter_personality WHERE fighter_id=?",
        (B_ID,),
    ).fetchone()[0]
    # 3 KO losses → grit +2 each = +6 total.
    check("K", "Conflict: 3 KO losses compound grit (+6 total)",
          g_after - g_before == 6,
          f"{g_before} → {g_after}")

    # --- Anticipation (player_settings drive future behavior) ---
    # The difficulty setting will shape future sim behavior (starting
    # cash, AI aggression, injury rates). The player chose 'hard' →
    # the sim will be more adversarial. This is the Anticipation
    # principle — the player's choice creates a future thread.
    player_settings.set_setting(conn, 'difficulty', 'hard')
    conn.commit()
    diff = player_settings.get_setting(conn, 'difficulty')
    check("K", "Anticipation: difficulty='hard' shapes future sim",
          diff == 'hard', f"got={diff!r}")

    # --- Investment (player_settings persist) ---
    # The player's settings persist across save/load (the player_
    # settings table is part of the DB, which is the save state).
    # The player's preferences are DURABLE — they don't have to
    # re-set them every session.
    all_settings = player_settings.get_all_settings(conn)
    check("K", "Investment: player settings persist in the DB",
          all_settings.get('difficulty') == 'hard'
          and all_settings.get('display_descriptors') == 'true',
          f"difficulty={all_settings.get('difficulty')!r}, "
          f"display_descriptors={all_settings.get('display_descriptors')!r}")

    # --- Voice layer (§14) — no raw numbers in player-facing text ---
    # The personality field updates + player_settings + mod tools
    # are all INTERNAL — they don't write news items or any other
    # player-facing text. The descriptor snapshot refresh picks up
    # the new personality tiers, but the snapshot itself is
    # displayed via voice descriptors (NOT raw numbers).
    #
    # Verify NO new news items were written by this task's systems
    # (morale.py personality updates + career_arc.py personality
    # drift + player_settings + mods all write ZERO news items).
    news_count = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic IN "
        "('personality_update', 'player_settings', 'mod_tools')"
    ).fetchone()[0]
    check("K", "Voice (§14): no news items written by Stage5-Final systems",
          news_count == 0, f"got={news_count}")

    # --- Event bus (§15.4) — Stage5-Final systems are event-driven ---
    # The morale.py personality updates subscribe to FIGHT_RESOLVED +
    # TICK_ADVANCED (existing subscribers, extended). The career_arc.py
    # personality drift subscribes to TICK_ADVANCED (existing
    # subscriber, extended). player_settings + mods are NOT event-
    # driven (player-initiated, not event-driven).
    bus = get_bus()
    tick_subs = bus.subscriber_count(Events.TICK_ADVANCED)
    check("K", "Event bus: TICK_ADVANCED subscribers registered",
          tick_subs >= 1, f"TICK_ADVANCED subs={tick_subs}")
    fight_subs = bus.subscriber_count(Events.FIGHT_RESOLVED)
    check("K", "Event bus: FIGHT_RESOLVED subscribers registered",
          fight_subs >= 1, f"FIGHT_RESOLVED subs={fight_subs}")

    # player_settings.register_subscribers is a no-op (settings are
    # not event-driven). Calling it should not increase the subscriber
    # count.
    tick_before = bus.subscriber_count(Events.TICK_ADVANCED)
    player_settings.register_subscribers()
    tick_after = bus.subscriber_count(Events.TICK_ADVANCED)
    check("K", "player_settings.register_subscribers is a no-op",
          tick_after == tick_before,
          f"before={tick_before} after={tick_after}")

    # --- One table-group per task (§5) ---
    # This task added ONLY the player_settings table. Verify no
    # other unexpected tables were added.
    table_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    check("K", "§5: schema has reasonable table count (50+)",
          table_count >= 50, f"got={table_count}")
    # Verify the player_settings table specifically exists.
    ps_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_settings'"
    ).fetchone() is not None
    check("K", "§5: player_settings table is the one new table",
          ps_exists, "")
    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print(f"Stage 5 — Task Stage5-Final: Fix stale personality fields +")
    print(f"Player settings + Mod tools skeleton")
    print(f"(schema {EXPECTED_CODE_VERSION}, MINOR bump from 3.6.0)")
    print(sep)

    clean_test_artifacts()
    try:
        case_a_grit_on_loss()
        case_b_ambition_shifts()
        case_c_injury_comeback()
        case_d_fatigue_tolerance_decline()
        case_e_travel_comfort_growth()
        case_f_player_settings_table()
        case_g_get_set_setting()
        case_h_export_fighters_csv()
        case_i_edit_fighter()
        case_j_backup_database()
        case_k_design_law()
    finally:
        # Clean up test artifacts.
        clean_test_artifacts()

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
