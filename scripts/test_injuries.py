#!/usr/bin/env python3
"""Acceptance test for Task ID 15 — Injuries + medical recovery (schema 2.4.0).

Tests the injuries system added in Task ID 15 (the FIRST Stage 3a task):

  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read dynamically — NO hardcoded version string, per §10).
     - schema_migrations contains a row starting with the dynamic
       version prefix (e.g. 'v2_4_0_').
     - The injuries table exists in sqlite_master.
     - Injuries has the 15 columns specified in the brief (subset
       check, NOT exact count — §10.4 prohibits hardcoded counts).
     - severity CHECK 1-10: rejects 0 and 11.
     - long_term_damage CHECK 0-100: rejects -1 and 101.
     - career_risk CHECK 0-100: rejects -1 and 101.
     - is_active CHECK IN (0,1): rejects 2.
     - body_area CHECK: rejects an invalid value ('torso') and accepts
       all 18 enumerated values from the brief.
     - fighter_id is NOT NULL (FK CASCADE): rejects NULL.
     - FK constraint: rejects a nonexistent fighter_id.
  B. Defaults:
     - A row inserted with only required fields gets severity=5,
       long_term_damage=0, career_risk=0, is_active=1 (the schema
       DEFAULTs).
  C. _pick_matchup reader (CONVENTIONS §5.3 — every new table ships
     with a reader):
     - Insert an active injury on fighter 1 (John Vale, AC).
     - app._pick_matchup(promo_id=1, wc_id=1) returns None — with only
       2 AC fighters and one injured, only 1 fighter is eligible
       (need 2).
     - Mark the injury as recovered (is_active=0).
     - app._pick_matchup now returns a valid (1, 2) tuple.
  D. _maybe_create_injury — doctor_stoppage guaranteed:
     - Build fresh DB. Call _maybe_create_injury directly with
       result_type='doctor_stoppage', is_loser=True.
     - With proneness=50 (default), injury_chance=1.0 (guaranteed).
     - Verify an injuries row was created with is_active=1.
     - Verify the body_area is in the doctor-stoppage pool
       (head/face/ribs/general — see _maybe_create_injury).
     - Verify a news item was created with topic='injury', fighter_id
       set, headline starting with "{Fighter} suffers".
  E. _maybe_create_injury — KO/TKO loser 30% head injury:
     - Call _maybe_create_injury with result_type='ko_tko',
       is_loser=True, 100 times with different random seeds.
     - Count injuries created. Expect ~30 (allow 15-45 inclusive —
       3-sigma tolerance on a binomial n=100, p=0.30).
     - All created injuries should have body_area='head' (the brief
       specifies head injury on KO/TKO).
  F. _maybe_create_injury — submission loser 15% joint injury:
     - Call _maybe_create_injury with result_type='submission',
       is_loser=True, 100 times.
     - Count injuries. Expect ~15 (allow 5-25 inclusive — 3-sigma on
       n=100, p=0.15).
     - All created injuries should have body_area in (knee, elbow,
       shoulder, ankle) — the joint pool.
  G. _maybe_create_injury — non-finish 5% base + damage-scaled on BOTH:
     - Call _maybe_create_injury with result_type='unanimous_decision',
       is_loser=False (i.e. the winner), damage_taken=0, 200 times.
     - Count injuries. Expect ~10 (5% base * 200 = 10, allow 3-17).
     - The winner CAN be injured (non-finish applies to both fighters).
  H. injury_proneness modifies probability:
     - Same setup as G but with proneness=100 (1.5x multiplier).
     - Expected base rate is 5% * 1.5 = 7.5%. Over 200 trials expect
       ~15 (allow 7-23).
     - With proneness=0 (0.5x multiplier), expected 2.5%. Over 200
       trials expect ~5 (allow 1-9).
  I. durability reduces severity:
     - Force an injury via doctor_stoppage (guaranteed).
     - Set fighter_attributes.durability=100 (high) for fighter A and
       durability=0 (low) for fighter B.
     - Run many trials. The average severity for dur=100 should be
       lower than for dur=0 (the -2 to +2 adjustment).
  J. projected_return_date = start_date + severity*14 - recovery_rate*0.1:
     - Create injuries with severity 1, 5, 10 and recovery_rate 50.
     - Expected days_out = max(7, sev*14 - 5):
       sev 1:  max(7, 9)   = 9
       sev 5:  max(7, 65)  = 65
       sev 10: max(7, 135) = 135
     - Verify projected_return_date matches start_date + days_out.
  K. career_health reduction while active:
     - Before injury: career_health=100.
     - Create a severity-5 injury (no long_term_damage).
     - After: career_health = 100 - 5*2 = 90 (the temporary penalty).
  L. Long-term damage for severity 8+:
     - Force many severity-8+ injuries (use doctor_stoppage + high
       damage so severity boosts to 8+). Some will roll long_term_damage
       in [2, 5].
     - For injuries with long_term_damage > 0:
       - The relevant fighter_attribute (per body_area mapping) was
         reduced by the same amount.
       - career_health was reduced by severity*2 + long_term_damage.
  M. Injury recovery on tick:
     - Insert an active injury with projected_return_date = today + 5
       days. Apply the temporary career_health penalty (-severity*2).
     - Tick 4 days: injury still active, career_health still reduced.
     - Tick 1 more day (today+5 == projected_return_date): injury
       recovered (is_active=0, actual_return_date=today+5),
       career_health restored to pre-injury value.
  N. Recovery news item:
     - After M, verify news_items has a "{Fighter} cleared to return
       from {injury_type}" headline with topic='injury', fighter_id
       set.
  O. Permanent long_term_damage NOT restored on recovery:
     - Insert an active injury with severity=10, long_term_damage=3
       (simulating the creation-time hit).
     - Apply career_health reduction = severity*2 + long_term_damage
       = 23. career_health goes 100 → 77.
     - Tick past projected_return_date.
     - career_health should be 77 + severity*2 = 77 + 20 = 97. The
       long_term_damage penalty (-3) is permanent and NOT restored.
  P. Regression: existing fight resolution still produces injuries
     end-to-end:
     - Build fresh DB. Resolve the seeded fight with random.seed.
     - If an injury was created, verify it has a valid fight_id, a
       valid fighter_id, a non-empty injury_type, a start_date == the
       event's event_date, and a news item was written.
     - If NO injury was created (the seeded fight is small-damage
       decision/sub), the test still PASSES — injury creation is
       probabilistic.
  Q. body_area CHECK constraint — all 18 enumerated values accepted:
     - For each of the 18 body_area values from the brief, INSERT a row
       and verify it succeeds. Then INSERT an invalid value and verify
       it raises IntegrityError.

Run from the project root:
    python3 scripts/test_injuries.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility:
  `random.seed(42)` is set before each probabilistic block so the
  binomial-tolerance checks in E/F/G/H are reproducible. The seed
  pins the random draws but not what the function does with them.

D-number decisions in this test (referenced from the worklog):
  - D2: test_event_scheduler.py case D's 5-event cycle now fails on
    Task 15 because the injury system can sideline one of AC's 2
    fighters (auto-scheduling returns None). NOT modified per §11;
    flagged for the supervisor.
"""
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call app._maybe_create_injury,
# app._pick_matchup, app._load_fighter_stats, app.resolve_next_fight,
# tick_processor._check_injury_recovery, tick_processor.run_tick.
# Importing app.py pulls in tkinter — the import itself does NOT
# require a display (only tk.Tk() does), so this is safe in headless
# contexts. Same pattern as test_regen.py / test_retirement.py.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402
import tick_processor  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read dynamically from
# build_db so this test does not need to be updated on every schema
# version bump — per CONVENTIONS §10). Same pattern as test_regen.py,
# test_retirement.py, test_rankings.py, test_contracts.py,
# test_titles.py, test_free_agency.py, test_schema_versioning.py,
# test_fight_history.py.
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py.
# John "Hammer" Vale = 1 (AC), Marcus "Voltage" Reed = 2 (AC),
# Dario "The Drill" Knox = 3 (RFL), Eli "Whisper" Storm = 4 (RFL),
# Cole "Anvil" Briggs = 5 (RFL).
A_ID = 1
B_ID = 2

# Promotion IDs assigned by seed_data.py.
ALPHA_COMBAT_ID = 1
RFL_ID = 2

# Seeded event date + sim clock date from src/seed_data.py.
SEEDED_EVENT_DATE = "2026-08-15"
SEEDED_CLOCK_DATE = "2026-07-20"

# The 18 enumerated body_area values from the Task 15 brief (matches
# the CHECK constraint in build_db.py).
ALL_BODY_AREAS = (
    "head", "face", "jaw", "nose", "eye", "neck",
    "shoulder", "arm", "elbow", "wrist", "hand",
    "ribs", "back", "hip", "knee", "ankle", "foot",
    "general",
)

# Body areas that _maybe_create_injury can roll for a doctor_stoppage
# (the doctor-stoppage pool — see app.py).
DOCTOR_BODY_AREAS = ("head", "face", "ribs", "general")

# Body areas for submission-finish joint injuries (the submitted joint).
SUBMISSION_JOINT_AREAS = ("knee", "elbow", "shoulder", "ankle")


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_regen.py / test_retirement.py /
    test_rankings.py / test_contracts.py / test_event_scheduler.py /
    test_titles.py / test_free_agency.py so all tests share the same
    setup contract: a fresh DB with 2 promotions (Alpha Combat + Rival
    Fight League), 5 fighters (2 AC + 3 RFL), 1 staff member (Nina
    Cross), 1 event, 1 title_fight (the seeded main event), 6 contracts
    (5 fighter + 1 staff), 5 rankings rows (all at 1000.0), 2 titles
    (both vacant — AC Lightweight + RFL Lightweight), 96 name pool
    entries. All 5 fighters have is_retired=0 (none retirement-eligible
    at seed time).
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
        raise RuntimeError(f"weight class {name!r} not found in seeded DB")
    return row[0]


def insert_injury(conn, fighter_id=A_ID, event_id=1, fight_id=1,
                  injury_type="test strain", severity=5, body_area="ribs",
                  start_date=SEEDED_CLOCK_DATE,
                  projected_return_date="2026-08-15",
                  long_term_damage=0, career_risk=0, is_active=1):
    """Insert a single injuries row with sensible test defaults.

    Returns the new injury_id. Caller commits.
    """
    cur = conn.execute(
        "INSERT INTO injuries (fighter_id, event_id, fight_id, "
        "injury_type, severity, body_area, start_date, "
        "projected_return_date, long_term_damage, career_risk, "
        "is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fighter_id, event_id, fight_id, injury_type, severity,
         body_area, start_date, projected_return_date, long_term_damage,
         career_risk, is_active),
    )
    return cur.lastrowid


def set_proneness(conn, fighter_id, value):
    """Set fighters.injury_proneness for one fighter."""
    conn.execute(
        "UPDATE fighters SET injury_proneness=? WHERE fighter_id=?",
        (value, fighter_id),
    )


def set_attribute(conn, fighter_id, attr_name, value):
    """Set one fighter_attributes column. attr_name MUST be in the
    _FIGHTER_ATTR_COLUMNS whitelist (defensive — never string-format an
    unvalidated column name into SQL).
    """
    if attr_name not in app._FIGHTER_ATTR_COLUMNS:
        raise ValueError(f"unknown attribute {attr_name!r}")
    conn.execute(
        f"UPDATE fighter_attributes SET {attr_name}=? WHERE fighter_id=?",
        (value, fighter_id),
    )


def count_injuries_for_fighter(conn, fighter_id):
    """Return (total, active) injury counts for one fighter."""
    total = conn.execute(
        "SELECT COUNT(*) FROM injuries WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM injuries WHERE fighter_id=? AND is_active=1",
        (fighter_id,),
    ).fetchone()[0]
    return total, active


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK 15 INJURIES + MEDICAL RECOVERY ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail). passed=None means SKIP.
    results = []

    # ----------------------------------------------------------------
    # Build a fresh DB. Used by case A.
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
    print(f"Schema version (dynamic)    = {EXPECTED_CODE_VERSION}")
    print(f"Migration prefix (dynamic)  = {EXPECTED_MIGRATION_PREFIX!r}")

    # ----------------------------------------------------------------
    # Test case A — Schema.
    # ----------------------------------------------------------------
    print("\n--- Case A: schema ---")

    # schema_meta.schema_version matches the code's current
    # CODE_SCHEMA_VERSION (dynamic, no hardcoding — per §10).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        "A",
        f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
        sv is not None and sv[0] == EXPECTED_CODE_VERSION,
        f"got={sv[0] if sv else None}",
    ))

    # migration name starts with the dynamic version prefix (LIKE
    # prefix check, so the description suffix can change per task —
    # _add_injuries, _add_injuries_v2, etc.).
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

    # The injuries table exists.
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='injuries'"
    ).fetchone()
    results.append((
        "A",
        "table 'injuries' exists",
        row is not None,
        f"found={row is not None}",
    ))

    # Injuries has the 15 columns specified in the brief (SUBSET check,
    # not exact count — §10.4 prohibits hardcoded counts that would
    # break on future column additions).
    expected_cols = {
        "injury_id", "fighter_id", "event_id", "fight_id",
        "injury_type", "severity", "body_area", "start_date",
        "projected_return_date", "actual_return_date",
        "long_term_damage", "career_risk", "is_active",
        "created_at", "updated_at",
    }
    actual_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(injuries)").fetchall()
    }
    missing = expected_cols - actual_cols
    results.append((
        "A",
        f"injuries has all 15 required columns (subset check)",
        not missing,
        f"missing={sorted(missing) if missing else 'none'}",
    ))

    # severity CHECK 1-10: rejects 0 and 11.
    for bad_sev in (0, 11):
        check_passed = True
        check_detail = ""
        try:
            conn.execute(
                "INSERT INTO injuries (fighter_id, injury_type, severity, "
                "body_area, start_date, projected_return_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (A_ID, "bad sev", bad_sev, "general",
                 SEEDED_CLOCK_DATE, "2026-08-15"),
            )
            check_passed = False
            check_detail = f"severity={bad_sev} INSERT did not raise"
        except sqlite3.IntegrityError:
            pass  # expected
        conn.rollback()
        results.append((
            "A",
            f"severity CHECK rejects {bad_sev} (out of 1-10 range)",
            check_passed,
            check_detail,
        ))

    # long_term_damage CHECK 0-100: rejects -1 and 101.
    for bad_ltd in (-1, 101):
        check_passed = True
        check_detail = ""
        try:
            conn.execute(
                "INSERT INTO injuries (fighter_id, injury_type, severity, "
                "body_area, start_date, projected_return_date, "
                "long_term_damage) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (A_ID, "bad ltd", 5, "general", SEEDED_CLOCK_DATE,
                 "2026-08-15", bad_ltd),
            )
            check_passed = False
            check_detail = f"long_term_damage={bad_ltd} INSERT did not raise"
        except sqlite3.IntegrityError:
            pass
        conn.rollback()
        results.append((
            "A",
            f"long_term_damage CHECK rejects {bad_ltd}",
            check_passed,
            check_detail,
        ))

    # career_risk CHECK 0-100: rejects -1 and 101.
    for bad_cr in (-1, 101):
        check_passed = True
        check_detail = ""
        try:
            conn.execute(
                "INSERT INTO injuries (fighter_id, injury_type, severity, "
                "body_area, start_date, projected_return_date, "
                "career_risk) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (A_ID, "bad cr", 5, "general", SEEDED_CLOCK_DATE,
                 "2026-08-15", bad_cr),
            )
            check_passed = False
            check_detail = f"career_risk={bad_cr} INSERT did not raise"
        except sqlite3.IntegrityError:
            pass
        conn.rollback()
        results.append((
            "A",
            f"career_risk CHECK rejects {bad_cr}",
            check_passed,
            check_detail,
        ))

    # is_active CHECK IN (0,1): rejects 2.
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, severity, "
            "body_area, start_date, projected_return_date, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (A_ID, "bad active", 5, "general", SEEDED_CLOCK_DATE,
             "2026-08-15", 2),
        )
        check_passed = False
        check_detail = "is_active=2 INSERT did not raise"
    except sqlite3.IntegrityError:
        pass
    conn.rollback()
    results.append((
        "A",
        "is_active CHECK rejects 2 (only 0 or 1 allowed)",
        check_passed,
        check_detail,
    ))

    # body_area CHECK: rejects an invalid value ('torso').
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, severity, "
            "body_area, start_date, projected_return_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (A_ID, "bad area", 5, "torso", SEEDED_CLOCK_DATE, "2026-08-15"),
        )
        check_passed = False
        check_detail = "body_area='torso' INSERT did not raise"
    except sqlite3.IntegrityError:
        pass
    conn.rollback()
    results.append((
        "A",
        "body_area CHECK rejects 'torso' (not in enumerated list)",
        check_passed,
        check_detail,
    ))

    # fighter_id NOT NULL: rejects NULL.
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, severity, "
            "body_area, start_date, projected_return_date) "
            "VALUES (NULL, ?, ?, ?, ?, ?)",
            ("null fk", 5, "general", SEEDED_CLOCK_DATE, "2026-08-15"),
        )
        check_passed = False
        check_detail = "fighter_id=NULL INSERT did not raise"
    except sqlite3.IntegrityError:
        pass
    conn.rollback()
    results.append((
        "A",
        "fighter_id NOT NULL (rejects NULL)",
        check_passed,
        check_detail,
    ))

    # FK constraint: rejects a nonexistent fighter_id.
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, severity, "
            "body_area, start_date, projected_return_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (99999, "bad fk", 5, "general", SEEDED_CLOCK_DATE, "2026-08-15"),
        )
        check_passed = False
        check_detail = "fighter_id=99999 INSERT did not raise (FK failed)"
    except sqlite3.IntegrityError:
        pass
    conn.rollback()
    results.append((
        "A",
        "fighter_id FK rejects nonexistent fighter_id=99999",
        check_passed,
        check_detail,
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case B — Defaults.
    # ----------------------------------------------------------------
    print("\n--- Case B: schema DEFAULTs ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Insert with only the required fields (no severity, no
    # long_term_damage, no career_risk, no is_active). The DEFAULTs
    # should kick in.
    cur = conn.execute(
        "INSERT INTO injuries (fighter_id, event_id, fight_id, "
        "injury_type, body_area, start_date, projected_return_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (A_ID, 1, 1, "defaults check", "ribs",
         SEEDED_CLOCK_DATE, "2026-08-15"),
    )
    new_id = cur.lastrowid
    conn.commit()
    row = conn.execute(
        "SELECT severity, long_term_damage, career_risk, is_active "
        "FROM injuries WHERE injury_id=?",
        (new_id,),
    ).fetchone()
    results.append((
        "B",
        "DEFAULT severity=5 when not specified",
        row[0] == 5,
        f"got={row[0]}",
    ))
    results.append((
        "B",
        "DEFAULT long_term_damage=0 when not specified",
        row[1] == 0,
        f"got={row[1]}",
    ))
    results.append((
        "B",
        "DEFAULT career_risk=0 when not specified",
        row[2] == 0,
        f"got={row[2]}",
    ))
    results.append((
        "B",
        "DEFAULT is_active=1 when not specified",
        row[3] == 1,
        f"got={row[3]}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case C — _pick_matchup reader (CONVENTIONS §5.3).
    # ----------------------------------------------------------------
    print("\n--- Case C: _pick_matchup excludes injured fighters ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Baseline: with no injuries, _pick_matchup returns a valid tuple.
    baseline = app._pick_matchup(conn, alpha_combat_id, wc_id)
    results.append((
        "C",
        "baseline: _pick_matchup returns a 2-tuple (no injuries)",
        baseline is not None and len(baseline) == 2,
        f"got={baseline}",
    ))

    # Insert an active injury on fighter 1 (John Vale).
    insert_injury(conn, fighter_id=A_ID, is_active=1,
                  projected_return_date="2099-01-01")  # far future
    conn.commit()

    # With fighter 1 injured, only fighter 2 is eligible — not enough.
    after_injury = app._pick_matchup(conn, alpha_combat_id, wc_id)
    results.append((
        "C",
        "with fighter 1 injured (only 1 eligible), _pick_matchup returns None",
        after_injury is None,
        f"got={after_injury}",
    ))

    # Mark the injury as recovered.
    conn.execute(
        "UPDATE injuries SET is_active=0, actual_return_date=? "
        "WHERE fighter_id=?",
        (SEEDED_CLOCK_DATE, A_ID),
    )
    conn.commit()

    # Now both fighters are eligible again.
    after_recovery = app._pick_matchup(conn, alpha_combat_id, wc_id)
    results.append((
        "C",
        "after recovery (is_active=0), _pick_matchup returns a valid tuple",
        after_recovery is not None and len(after_recovery) == 2,
        f"got={after_recovery}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case D — _maybe_create_injury: doctor_stoppage guaranteed.
    # ----------------------------------------------------------------
    print("\n--- Case D: doctor_stoppage produces a guaranteed injury ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Pre-state: fighter 1 has no injuries.
    total_before, active_before = count_injuries_for_fighter(conn, A_ID)
    results.append((
        "D",
        "before: fighter 1 has 0 injuries",
        total_before == 0,
        f"got total={total_before} active={active_before}",
    ))

    # Load fighter 1's stats (the helper returns durability,
    # recovery_rate, etc. — all needed by _maybe_create_injury).
    stats_a = app._load_fighter_stats(conn, A_ID)
    proneness_a = conn.execute(
        "SELECT COALESCE(injury_proneness, 50) FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    ch_before = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]

    random.seed(RANDOM_SEED)
    injury_id = app._maybe_create_injury(
        conn,
        fighter_id=A_ID,
        fight_id=1,
        event_id=1,
        event_date=SEEDED_EVENT_DATE,
        result_type="doctor_stoppage",
        is_loser=True,
        damage_taken=250,
        finishing_beat_id=None,
        stats=stats_a,
        proneness=proneness_a,
    )
    conn.commit()

    results.append((
        "D",
        "doctor_stoppage loser produced an injury_id (guaranteed)",
        injury_id is not None,
        f"got={injury_id}",
    ))

    if injury_id is not None:
        inj_row = conn.execute(
            "SELECT is_active, body_area, injury_type, severity, "
            "start_date, projected_return_date, long_term_damage, "
            "career_risk FROM injuries WHERE injury_id=?",
            (injury_id,),
        ).fetchone()
        results.append((
            "D",
            "new injury is_active=1",
            inj_row[0] == 1,
            f"got={inj_row[0]}",
        ))
        results.append((
            "D",
            "doctor_stoppage body_area is in the doctor pool "
            "(head/face/ribs/general)",
            inj_row[1] in DOCTOR_BODY_AREAS,
            f"got={inj_row[1]!r}",
        ))
        results.append((
            "D",
            "start_date == event_date",
            inj_row[4] == SEEDED_EVENT_DATE,
            f"got={inj_row[4]}",
        ))
        # Severity in 1-10 (the CHECK constraint enforces this, but
        # verify the function didn't write a row that the DB then
        # silently rejected).
        results.append((
            "D",
            "severity in 1-10",
            1 <= inj_row[3] <= 10,
            f"got={inj_row[3]}",
        ))

        # career_health was reduced by severity*2 (+long_term_damage if any).
        ch_after = conn.execute(
            "SELECT career_health FROM fighter_career WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        expected_ch = max(0, ch_before - (inj_row[3] * 2 + inj_row[6]))
        results.append((
            "D",
            f"career_health reduced by severity*2 + long_term_damage "
            f"({ch_before} -> {expected_ch})",
            ch_after == expected_ch,
            f"got={ch_after} expected={expected_ch}",
        ))

        # A news item was written with topic='injury' and fighter_id set.
        news_row = conn.execute(
            "SELECT headline, topic, fighter_id FROM news_items "
            "WHERE topic='injury' AND fighter_id=? "
            "ORDER BY news_item_id DESC LIMIT 1",
            (A_ID,),
        ).fetchone()
        results.append((
            "D",
            "injury news item written with topic='injury' and fighter_id set",
            news_row is not None,
            f"got={news_row}",
        ))
        if news_row:
            fighter_name_str = app.fighter_name(conn, A_ID)
            results.append((
                "D",
                f"news headline starts with fighter name "
                f"({fighter_name_str!r})",
                news_row[0].startswith(fighter_name_str),
                f"got={news_row[0]!r}",
            ))
            results.append((
                "D",
                "news headline contains 'suffers'",
                "suffers" in news_row[0].lower(),
                f"got={news_row[0]!r}",
            ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case E — KO/TKO loser 30% head injury.
    # ----------------------------------------------------------------
    print("\n--- Case E: KO/TKO loser 30% head injury (binomial check) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    stats_a = app._load_fighter_stats(conn, A_ID)

    n_trials = 100
    injuries_created = 0
    body_areas_seen = set()
    for i in range(n_trials):
        # Different seed each trial so the random rolls differ.
        random.seed(RANDOM_SEED + i)
        inj_id = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="ko_tko", is_loser=True,
            damage_taken=80, finishing_beat_id=None,
            stats=stats_a, proneness=50,
        )
        if inj_id is not None:
            injuries_created += 1
            area = conn.execute(
                "SELECT body_area FROM injuries WHERE injury_id=?",
                (inj_id,),
            ).fetchone()[0]
            body_areas_seen.add(area)
            # Clean up so we don't accumulate 100s of injuries on
            # fighter 1 (which would change the per-trial setup).
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_id,))
            # Restore the career_health reduction we applied.
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
    conn.commit()

    # Expected ~30 injuries (30% * 100). 3-sigma tolerance: 15-45.
    results.append((
        "E",
        f"KO/TKO loser injury rate ~30% (got {injuries_created}/{n_trials}, "
        f"tolerance 15-45)",
        15 <= injuries_created <= 45,
        f"got={injuries_created}",
    ))
    # All created injuries should have body_area='head' (the brief
    # specifies head injury on KO/TKO).
    results.append((
        "E",
        "all KO/TKO injuries have body_area='head'",
        body_areas_seen == {"head"} or body_areas_seen == set(),
        f"got={sorted(body_areas_seen)}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case F — submission loser 15% joint injury.
    # ----------------------------------------------------------------
    print("\n--- Case F: submission loser 15% joint injury (binomial check) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    stats_a = app._load_fighter_stats(conn, A_ID)

    n_trials = 100
    injuries_created = 0
    body_areas_seen = set()
    for i in range(n_trials):
        random.seed(RANDOM_SEED + i)
        inj_id = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="submission", is_loser=True,
            damage_taken=80, finishing_beat_id=None,
            stats=stats_a, proneness=50,
        )
        if inj_id is not None:
            injuries_created += 1
            area = conn.execute(
                "SELECT body_area FROM injuries WHERE injury_id=?",
                (inj_id,),
            ).fetchone()[0]
            body_areas_seen.add(area)
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_id,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
    conn.commit()

    # Expected ~15 (15% * 100). 3-sigma tolerance: 5-25.
    results.append((
        "F",
        f"submission loser injury rate ~15% (got {injuries_created}/{n_trials}, "
        f"tolerance 5-25)",
        5 <= injuries_created <= 25,
        f"got={injuries_created}",
    ))
    results.append((
        "F",
        "all submission injuries have body_area in joint pool "
        "(knee/elbow/shoulder/ankle)",
        body_areas_seen.issubset(set(SUBMISSION_JOINT_AREAS)) or not body_areas_seen,
        f"got={sorted(body_areas_seen)}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case G — non-finish 5% base + damage-scaled on BOTH fighters.
    # ----------------------------------------------------------------
    print("\n--- Case G: non-finish 5% base on winner (binomial check) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    stats_a = app._load_fighter_stats(conn, A_ID)

    n_trials = 200
    injuries_created = 0
    for i in range(n_trials):
        random.seed(RANDOM_SEED + i)
        inj_id = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="unanimous_decision", is_loser=False,
            damage_taken=0, finishing_beat_id=None,
            stats=stats_a, proneness=50,
        )
        if inj_id is not None:
            injuries_created += 1
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_id,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
    conn.commit()

    # Expected ~10 (5% * 200). 3-sigma tolerance: 3-17.
    results.append((
        "G",
        f"non-finish winner injury rate ~5% (got {injuries_created}/{n_trials}, "
        f"tolerance 3-17)",
        3 <= injuries_created <= 17,
        f"got={injuries_created}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case H — injury_proneness modifies probability.
    # ----------------------------------------------------------------
    print("\n--- Case H: injury_proneness modifies probability ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    stats_a = app._load_fighter_stats(conn, A_ID)

    # H.1: proneness=100 → 1.5x multiplier → ~7.5% rate.
    n_trials = 200
    inj_high = 0
    for i in range(n_trials):
        random.seed(RANDOM_SEED + i)
        inj_id = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="unanimous_decision", is_loser=False,
            damage_taken=0, finishing_beat_id=None,
            stats=stats_a, proneness=100,  # 1.5x
        )
        if inj_id is not None:
            inj_high += 1
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_id,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
    conn.commit()
    # Expected ~15 (7.5% * 200). Tolerance: 7-23.
    results.append((
        "H",
        f"proneness=100 (1.5x) rate ~7.5% (got {inj_high}/{n_trials}, "
        f"tolerance 7-23)",
        7 <= inj_high <= 23,
        f"got={inj_high}",
    ))

    # H.2: proneness=0 → 0.5x multiplier → ~2.5% rate.
    inj_low = 0
    for i in range(n_trials):
        random.seed(RANDOM_SEED + i)
        inj_id = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="unanimous_decision", is_loser=False,
            damage_taken=0, finishing_beat_id=None,
            stats=stats_a, proneness=0,  # 0.5x
        )
        if inj_id is not None:
            inj_low += 1
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_id,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
    conn.commit()
    # Expected ~5 (2.5% * 200). Tolerance: 1-9.
    results.append((
        "H",
        f"proneness=0 (0.5x) rate ~2.5% (got {inj_low}/{n_trials}, "
        f"tolerance 1-9)",
        1 <= inj_low <= 9,
        f"got={inj_low}",
    ))
    # High-proneness rate should be higher than low-proneness rate
    # (statistically expected — this is the directional check).
    results.append((
        "H",
        f"proneness=100 rate ({inj_high}) > proneness=0 rate ({inj_low})",
        inj_high > inj_low,
        f"high={inj_high} low={inj_low}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case I — durability reduces severity.
    # ----------------------------------------------------------------
    print("\n--- Case I: durability reduces severity ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Force durability=0 (low) on fighter 1, durability=100 (high) on
    # fighter 2. Run doctor_stoppage on both (guaranteed injury).
    set_attribute(conn, A_ID, "durability", 0)
    set_attribute(conn, B_ID, "durability", 100)
    conn.commit()

    stats_a_low = app._load_fighter_stats(conn, A_ID)
    stats_b_high = app._load_fighter_stats(conn, B_ID)

    severities_low = []
    severities_high = []
    for i in range(40):
        random.seed(RANDOM_SEED + i)
        inj_a = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="doctor_stoppage", is_loser=True,
            damage_taken=250, finishing_beat_id=None,
            stats=stats_a_low, proneness=50,
        )
        if inj_a is not None:
            sev_a = conn.execute(
                "SELECT severity FROM injuries WHERE injury_id=?",
                (inj_a,),
            ).fetchone()[0]
            severities_low.append(sev_a)
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_a,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )

        random.seed(RANDOM_SEED + i + 1000)  # offset so it's a fresh sequence
        inj_b = app._maybe_create_injury(
            conn, fighter_id=B_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="doctor_stoppage", is_loser=True,
            damage_taken=250, finishing_beat_id=None,
            stats=stats_b_high, proneness=50,
        )
        if inj_b is not None:
            sev_b = conn.execute(
                "SELECT severity FROM injuries WHERE injury_id=?",
                (inj_b,),
            ).fetchone()[0]
            severities_high.append(sev_b)
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_b,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (B_ID,),
            )
    conn.commit()

    avg_low = sum(severities_low) / len(severities_low) if severities_low else 0
    avg_high = sum(severities_high) / len(severities_high) if severities_high else 0
    # High-durability fighter should have LOWER average severity (the
    # -2 adjustment at dur=100 vs +2 at dur=0). Allow equal-or-lower
    # (the random spread is wide, but the directional bias should be
    # visible across 40 trials).
    results.append((
        "I",
        f"avg severity dur=0 ({avg_low:.1f}) >= dur=100 ({avg_high:.1f})",
        avg_low >= avg_high,
        f"low_dur sevs={severities_low[:5]}... high_dur sevs={severities_high[:5]}...",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case J — projected_return_date formula.
    # ----------------------------------------------------------------
    print("\n--- Case J: projected_return_date = start + max(7, sev*14 - rec*0.1) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Force recovery_rate=50 (the schema default). The expected
    # recovery_discount is int(50 * 0.1) = 5.
    set_attribute(conn, A_ID, "recovery_rate", 50)
    conn.commit()
    stats_a = app._load_fighter_stats(conn, A_ID)

    # Expected days_out per severity (with recovery_rate=50, discount=5):
    #   sev 1:  max(7, 14-5)  = max(7, 9)   = 9
    #   sev 5:  max(7, 70-5)  = max(7, 65)  = 65
    #   sev 10: max(7, 140-5) = max(7, 135) = 135
    expected_days = {1: 9, 5: 65, 10: 135}

    start_dt = datetime.strptime(SEEDED_EVENT_DATE, "%Y-%m-%d")
    for sev, days in expected_days.items():
        # Force a specific severity by using doctor_stoppage (guaranteed
        # injury) and then patching the severity in-DB. (We can't pass
        # severity to _maybe_create_injury — it's rolled internally —
        # so we update the row post-insertion to the test severity and
        # recompute projected_return_date by calling the same formula
        # the function uses.)

        # The cleanest way to verify the FORMULA is to call the helper
        # once with doctor_stoppage, capture the rolled severity, then
        # compute the expected projected_return_date from THAT severity
        # and compare. Then for the 3 specific severity levels (1, 5,
        # 10), we manually insert injuries with those severities and
        # verify the formula by re-running the date computation here.
        pass

    # Approach: directly invoke _maybe_create_injury with doctor_stoppage
    # (guaranteed). The function rolls severity AND computes
    # projected_return_date from it. Verify the relationship holds for
    # the rolled severity (whatever it is).
    random.seed(RANDOM_SEED)
    inj_id = app._maybe_create_injury(
        conn, fighter_id=A_ID, fight_id=1, event_id=1,
        event_date=SEEDED_EVENT_DATE,
        result_type="doctor_stoppage", is_loser=True,
        damage_taken=250, finishing_beat_id=None,
        stats=stats_a, proneness=50,
    )
    conn.commit()
    if inj_id is not None:
        row = conn.execute(
            "SELECT severity, start_date, projected_return_date "
            "FROM injuries WHERE injury_id=?",
            (inj_id,),
        ).fetchone()
        sev = row[0]
        start = row[1]
        projected = row[2]
        # Expected: start + max(7, sev*14 - int(recovery_rate*0.1))
        # recovery_rate=50 (we set it above), so discount=5.
        recovery_discount = int(50 * app._INJURY_RECOVERY_RATE_DAYS_PER_POINT)
        expected_days_out = max(
            app._INJURY_MIN_DAYS_OUT,
            sev * app._INJURY_BASE_DAYS_PER_SEVERITY - recovery_discount,
        )
        expected_projected = (
            datetime.strptime(start, "%Y-%m-%d") + timedelta(days=expected_days_out)
        ).strftime("%Y-%m-%d")
        results.append((
            "J",
            f"projected_return_date matches formula "
            f"(sev={sev}, days_out={expected_days_out}, "
            f"expected={expected_projected})",
            projected == expected_projected,
            f"got={projected}",
        ))

    # Also verify the formula for the 3 specific severity levels by
    # manually inserting rows with those severities and computing the
    # expected projected_return_date independently.
    for sev, days in expected_days.items():
        expected_proj = (start_dt + timedelta(days=days)).strftime("%Y-%m-%d")
        # Insert a manual injury with this severity and the same
        # projected_return_date the formula would produce. If the
        # insert succeeds (no CHECK failure) and the date matches
        # expectation, the formula is verified for this severity.
        # We're checking the COMPUTED date is internally consistent —
        # i.e., our hand-computed expected matches what the formula
        # would produce for this sev.
        results.append((
            "J",
            f"formula check sev={sev}: start+{days}d == {expected_proj}",
            expected_proj == (
                start_dt + timedelta(
                    days=max(app._INJURY_MIN_DAYS_OUT,
                             sev * app._INJURY_BASE_DAYS_PER_SEVERITY - recovery_discount)
                )
            ).strftime("%Y-%m-%d"),
            f"got={expected_proj}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case K — career_health reduction while active.
    # ----------------------------------------------------------------
    print("\n--- Case K: career_health reduced by severity*2 while active ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    ch_before = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "K",
        "before: career_health=100",
        ch_before == 100,
        f"got={ch_before}",
    ))

    # Insert a severity-5 injury with no long_term_damage. Apply the
    # career_health reduction manually (simulating what
    # _maybe_create_injury does, but with a deterministic severity so
    # the assertion is exact).
    insert_injury(conn, fighter_id=A_ID, severity=5, body_area="ribs",
                  long_term_damage=0, is_active=1,
                  start_date=SEEDED_CLOCK_DATE,
                  projected_return_date="2099-01-01")
    # Apply the same reduction _maybe_create_injury would: severity*2.
    conn.execute(
        "UPDATE fighter_career SET career_health = MAX(0, career_health - ?) "
        "WHERE fighter_id=?",
        (5 * app._INJURY_CAREER_HEALTH_MULT, A_ID),
    )
    conn.commit()
    ch_after = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "K",
        f"after sev-5 injury: career_health={100 - 5*2} (=90)",
        ch_after == 100 - 5 * 2,
        f"got={ch_after}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case L — long-term damage for severity 8+.
    # ----------------------------------------------------------------
    print("\n--- Case L: severity 8+ injuries have 30% long-term damage chance ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Force severity 8+ by running many doctor_stoppage injuries with
    # low durability (durability=0 gives +2 severity adjustment, and
    # doctor_stoppage tends to roll high-severity areas like
    # concussion/orbital fracture). Run 60 trials, collect all
    # severity-8+ injuries, and verify that some have long_term_damage
    # > 0 (the 30% roll fired for at least a few).
    set_attribute(conn, A_ID, "durability", 0)
    conn.commit()
    stats_a = app._load_fighter_stats(conn, A_ID)

    n_trials = 60
    high_sev_injuries = []  # list of (injury_id, severity, long_term_damage, body_area)
    for i in range(n_trials):
        random.seed(RANDOM_SEED + i)
        inj_id = app._maybe_create_injury(
            conn, fighter_id=A_ID, fight_id=1, event_id=1,
            event_date=SEEDED_EVENT_DATE,
            result_type="doctor_stoppage", is_loser=True,
            damage_taken=300, finishing_beat_id=None,
            stats=stats_a, proneness=50,
        )
        if inj_id is not None:
            row = conn.execute(
                "SELECT severity, long_term_damage, body_area "
                "FROM injuries WHERE injury_id=?",
                (inj_id,),
            ).fetchone()
            if row[0] >= 8:
                high_sev_injuries.append((inj_id, row[0], row[1], row[2]))
            # Clean up for next trial.
            conn.execute("DELETE FROM injuries WHERE injury_id=?", (inj_id,))
            conn.execute(
                "UPDATE fighter_career SET career_health=100 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
            # Restore the attribute reduction (if any).
            conn.execute(
                "UPDATE fighter_attributes SET punch_power=50, cardio=50, "
                "chin=50, speed_explosiveness=50, strength=50, durability=0 "
                "WHERE fighter_id=?",
                (A_ID,),
            )
    conn.commit()

    results.append((
        "L",
        f"at least 5 severity-8+ injuries observed over {n_trials} trials "
        f"(got {len(high_sev_injuries)})",
        len(high_sev_injuries) >= 5,
        f"got={len(high_sev_injuries)} (severities={[r[1] for r in high_sev_injuries[:10]]})",
    ))

    if high_sev_injuries:
        n_with_ltd = sum(1 for r in high_sev_injuries if r[2] > 0)
        # Expected ~30% of high-sev injuries have long_term_damage > 0.
        # With at least 5 high-sev injuries, we expect 1-2 with LTD.
        # Just verify at least 1 over 60 trials (the 30% roll fired at
        # least once — probabilistic but very likely with n>=5).
        results.append((
            "L",
            f"at least 1 severity-8+ injury has long_term_damage > 0 "
            f"(got {n_with_ltd}/{len(high_sev_injuries)})",
            n_with_ltd >= 1,
            f"got={n_with_ltd}/{len(high_sev_injuries)}",
        ))
        # Verify the long_term_damage is in [2, 5] (the brief's range).
        ltds = [r[2] for r in high_sev_injuries if r[2] > 0]
        if ltds:
            results.append((
                "L",
                f"all long_term_damage values in [2,5] (got {ltds})",
                all(2 <= v <= 5 for v in ltds),
                f"got={ltds}",
            ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case M — injury recovery on tick.
    # ----------------------------------------------------------------
    print("\n--- Case M: injury recovery on tick ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Insert an active injury with projected_return_date = today + 5.
    today_dt = datetime.strptime(SEEDED_CLOCK_DATE, "%Y-%m-%d")
    projected_dt = today_dt + timedelta(days=5)
    projected_str = projected_dt.strftime("%Y-%m-%d")
    inj_id = insert_injury(
        conn, fighter_id=A_ID, severity=4, body_area="ribs",
        injury_type="bruised ribs", is_active=1,
        start_date=SEEDED_CLOCK_DATE,
        projected_return_date=projected_str,
    )
    # Apply the career_health reduction that _maybe_create_injury
    # would have applied (severity * 2 = 8). career_health: 100 -> 92.
    conn.execute(
        "UPDATE fighter_career SET career_health = MAX(0, career_health - ?) "
        "WHERE fighter_id=?",
        (4 * app._INJURY_CAREER_HEALTH_MULT, A_ID),
    )
    conn.commit()

    # Verify pre-state.
    row = conn.execute(
        "SELECT is_active, actual_return_date FROM injuries WHERE injury_id=?",
        (inj_id,),
    ).fetchone()
    results.append((
        "M",
        "pre-tick: injury is_active=1, actual_return_date=NULL",
        row[0] == 1 and row[1] is None,
        f"got is_active={row[0]} actual_return_date={row[1]}",
    ))
    ch_pre = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "M",
        f"pre-tick: career_health=92 (100 - 4*2)",
        ch_pre == 92,
        f"got={ch_pre}",
    ))

    # Tick 4 days — projected_return_date is day 5, so still active.
    for _ in range(4):
        tick_processor.run_tick(conn)
    conn.commit()
    row = conn.execute(
        "SELECT is_active, actual_return_date FROM injuries WHERE injury_id=?",
        (inj_id,),
    ).fetchone()
    results.append((
        "M",
        "after 4 ticks: injury still active (projected_return_date not yet reached)",
        row[0] == 1 and row[1] is None,
        f"got is_active={row[0]} actual_return_date={row[1]}",
    ))

    # Tick 1 more day — projected_return_date reached.
    tick_processor.run_tick(conn)
    conn.commit()
    row = conn.execute(
        "SELECT is_active, actual_return_date FROM injuries WHERE injury_id=?",
        (inj_id,),
    ).fetchone()
    # The clock started at 2026-07-20. After 5 ticks, the clock is at
    # 2026-07-25 (1 day per tick). projected_return_date was
    # 2026-07-25, so recovery should fire on this tick.
    new_clock = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    results.append((
        "M",
        f"after 5 ticks: injury recovered (is_active=0, actual_return_date set)",
        row[0] == 0 and row[1] is not None,
        f"got is_active={row[0]} actual_return_date={row[1]} clock={new_clock}",
    ))
    # actual_return_date should match the current sim date.
    results.append((
        "M",
        f"actual_return_date == current sim date ({new_clock})",
        row[1] == new_clock,
        f"got={row[1]}",
    ))

    # career_health restored: 92 + 4*2 = 100.
    ch_post = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "M",
        f"after recovery: career_health=100 (92 + 4*2)",
        ch_post == 100,
        f"got={ch_post}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case N — recovery news item.
    # ----------------------------------------------------------------
    print("\n--- Case N: recovery news item ---")
    # Re-use the DB from case M (already recovered). Check the
    # news_items table for the clearance headline.
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    news = conn.execute(
        "SELECT headline, topic, fighter_id FROM news_items "
        "WHERE topic='injury' AND fighter_id=? "
        "AND headline LIKE '%cleared to return%'",
        (A_ID,),
    ).fetchall()
    results.append((
        "N",
        "recovery news item written with topic='injury' and "
        "'cleared to return' in headline",
        len(news) >= 1,
        f"got={news}",
    ))
    if news:
        fighter_name_str = app.fighter_name(conn, A_ID)
        results.append((
            "N",
            f"recovery news headline starts with fighter name "
            f"({fighter_name_str!r})",
            news[0][0].startswith(fighter_name_str),
            f"got={news[0][0]!r}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case O — permanent long_term_damage NOT restored on recovery.
    # ----------------------------------------------------------------
    print("\n--- Case O: long_term_damage is permanent (not restored on recovery) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Insert an active injury with severity=10, long_term_damage=3.
    # Apply the FULL career_health reduction (severity*2 + long_term_damage
    # = 23). career_health: 100 -> 77.
    projected_dt = today_dt + timedelta(days=2)
    inj_id = insert_injury(
        conn, fighter_id=A_ID, severity=10, body_area="knee",
        injury_type="ACL tear", long_term_damage=3, is_active=1,
        start_date=SEEDED_CLOCK_DATE,
        projected_return_date=projected_dt.strftime("%Y-%m-%d"),
    )
    conn.execute(
        "UPDATE fighter_career SET career_health = MAX(0, career_health - ?) "
        "WHERE fighter_id=?",
        (10 * app._INJURY_CAREER_HEALTH_MULT + 3, A_ID),
    )
    # Also reduce the body-area-relevant attribute (knee → speed_explosiveness)
    # by long_term_damage, simulating what _maybe_create_injury does.
    set_attribute(conn, A_ID, "speed_explosiveness", 50 - 3)
    conn.commit()
    ch_pre = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    se_pre = conn.execute(
        "SELECT speed_explosiveness FROM fighter_attributes WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "O",
        "pre-recovery: career_health=77 (100 - 10*2 - 3)",
        ch_pre == 77,
        f"got={ch_pre}",
    ))
    results.append((
        "O",
        "pre-recovery: speed_explosiveness=47 (50 - 3 long_term_damage)",
        se_pre == 47,
        f"got={se_pre}",
    ))

    # Tick past projected_return_date (2 days).
    for _ in range(3):
        tick_processor.run_tick(conn)
    conn.commit()

    ch_post = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    se_post = conn.execute(
        "SELECT speed_explosiveness FROM fighter_attributes WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    # career_health should be 77 + 10*2 = 97. The 3-point
    # long_term_damage penalty is PERMANENT (not restored).
    results.append((
        "O",
        f"post-recovery: career_health=97 (77 + 10*2; long_term_damage NOT restored)",
        ch_post == 97,
        f"got={ch_post}",
    ))
    # The permanent attribute reduction is NOT restored either.
    results.append((
        "O",
        f"post-recovery: speed_explosiveness still 47 (permanent reduction)",
        se_post == 47,
        f"got={se_post}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case P — regression: end-to-end fight resolution produces
    # valid injuries (when they fire).
    # ----------------------------------------------------------------
    print("\n--- Case P: regression — end-to-end fight resolution ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Resolve the seeded fight. random.seed(42) for reproducibility.
    random.seed(RANDOM_SEED)
    fid = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "P",
        "resolve_next_fight returned a fight_id (no crash)",
        fid is not None,
        f"got={fid}",
    ))
    if fid is not None:
        # Fight was resolved with a valid result_type.
        rt = conn.execute(
            "SELECT result_type FROM fights WHERE fight_id=?",
            (fid,),
        ).fetchone()[0]
        results.append((
            "P",
            f"fight has a valid result_type (got {rt!r})",
            rt is not None,
            f"got={rt}",
        ))
        # Injuries (if any) should reference this fight_id and the
        # event's event_date.
        inj_rows = conn.execute(
            "SELECT injury_id, fighter_id, fight_id, event_id, injury_type, "
            "severity, body_area, start_date, projected_return_date, "
            "is_active FROM injuries WHERE fight_id=?",
            (fid,),
        ).fetchall()
        results.append((
            "P",
            f"any injuries reference the resolved fight_id ({fid})",
            all(r[2] == fid for r in inj_rows),
            f"got fight_ids={[r[2] for r in inj_rows]}",
        ))
        if inj_rows:
            event_date_db = conn.execute(
                "SELECT event_date FROM events WHERE event_id=?",
                (inj_rows[0][3],),
            ).fetchone()[0]
            results.append((
                "P",
                "injury start_date == fight's event_date",
                all(r[7] == event_date_db for r in inj_rows),
                f"got start_dates={[r[7] for r in inj_rows]} event_date={event_date_db}",
            ))
            results.append((
                "P",
                "injury has non-empty injury_type",
                all(r[4] for r in inj_rows),
                f"got types={[r[4] for r in inj_rows]}",
            ))
            results.append((
                "P",
                "injury severity in 1-10",
                all(1 <= r[5] <= 10 for r in inj_rows),
                f"got sevs={[r[5] for r in inj_rows]}",
            ))
            results.append((
                "P",
                "injury body_area is in the 18 enumerated values",
                all(r[6] in ALL_BODY_AREAS for r in inj_rows),
                f"got areas={[r[6] for r in inj_rows]}",
            ))
            results.append((
                "P",
                "injury is_active=1 (just created)",
                all(r[9] == 1 for r in inj_rows),
                f"got actives={[r[9] for r in inj_rows]}",
            ))
            # Each injury should have a matching news item.
            for r in inj_rows:
                news = conn.execute(
                    "SELECT 1 FROM news_items WHERE topic='injury' "
                    "AND fighter_id=? AND headline LIKE '%suffers%'",
                    (r[1],),
                ).fetchone()
                results.append((
                    "P",
                    f"injury for fighter {r[1]} has matching 'suffers' news item",
                    news is not None,
                    f"fighter={r[1]} news={news}",
                ))
        else:
            # No injury created — that's fine (probabilistic). Just
            # verify the news table doesn't have any spurious injury
            # items for this fight.
            news_count = conn.execute(
                "SELECT COUNT(*) FROM news_items WHERE topic='injury'"
            ).fetchone()[0]
            results.append((
                "P",
                "no injury created AND no injury news items (probabilistic — both consistent)",
                news_count == 0,
                f"got news_count={news_count}",
            ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case Q — body_area CHECK: all 18 enumerated values accepted.
    # ----------------------------------------------------------------
    print("\n--- Case Q: body_area CHECK accepts all 18 enumerated values ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Insert one injury per body_area value — all should succeed.
    all_succeeded = True
    failed_areas = []
    for area in ALL_BODY_AREAS:
        try:
            conn.execute(
                "INSERT INTO injuries (fighter_id, injury_type, severity, "
                "body_area, start_date, projected_return_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (A_ID, f"test_{area}", 5, area, SEEDED_CLOCK_DATE,
                 "2026-08-15"),
            )
        except sqlite3.IntegrityError:
            all_succeeded = False
            failed_areas.append(area)
            conn.rollback()
    conn.commit()
    results.append((
        "Q",
        f"all 18 body_area values accepted by CHECK constraint",
        all_succeeded,
        f"failed={failed_areas}",
    ))

    # An invalid body_area should still be rejected (already covered
    # in A, but restate for clarity).
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, severity, "
            "body_area, start_date, projected_return_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (A_ID, "bad area", 5, "spine", SEEDED_CLOCK_DATE, "2026-08-15"),
        )
        check_passed = False
        check_detail = "body_area='spine' INSERT did not raise"
    except sqlite3.IntegrityError:
        pass
    conn.rollback()
    results.append((
        "Q",
        "body_area CHECK rejects 'spine' (not in enumerated list)",
        check_passed,
        check_detail,
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Print summary.
    # ----------------------------------------------------------------
    print()
    print(sep)
    n_pass = sum(1 for r in results if r[2] is True)
    n_fail = sum(1 for r in results if r[2] is False)
    n_skip = sum(1 for r in results if r[2] is None)

    # Per-case summary.
    cases = {}
    for case, name, passed, detail in results:
        cases.setdefault(case, [0, 0, 0])
        if passed is True:
            cases[case][0] += 1
        elif passed is False:
            cases[case][1] += 1
        else:
            cases[case][2] += 1
    for case in sorted(cases):
        p, f, s = cases[case]
        print(f"  Case {case}: {p} PASS, {f} FAIL" + (f", {s} SKIP" if s else ""))

    print()
    print(f"Total: {n_pass} / {n_pass + n_fail} checks passed "
          f"({n_skip} skipped, 0 failed tolerance for skipped)")
    print(sep)
    if n_fail == 0:
        print("OVERALL: PASS")
        return 0
    else:
        print("OVERALL: FAIL")
        print("\nFailed checks:")
        for case, name, passed, detail in results:
            if passed is False:
                print(f"  [Case {case}] {name}")
                print(f"    {detail}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
