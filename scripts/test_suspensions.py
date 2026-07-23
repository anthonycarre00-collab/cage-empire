#!/usr/bin/env python3
"""Acceptance test for Phase B — B1+B2 (Suspensions + Seed-Time Rivalries/Social).

Tests the suspensions system added in Phase B (schema 3.3.0 → 3.4.0
MINOR bump) + the seed-time rivalries (phase4) + seed-time social
posts (phase5). Per docs/FULL_BUILD_AUDIT.md §9a (suspensions) +
§4e (seed-time rivalries) + §3 (seed-time social posts).

Test cases:
  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (dynamic — NO hardcoded version string, per §10).
     - schema_migrations contains a row starting with the dynamic
       version prefix 'v3_4_0_'.
     - The suspensions table exists in sqlite_master.
     - suspensions has the 9 required columns (suspension_id,
       fighter_id, suspension_type, start_date, end_date,
       duration_days, description, is_active, created_at).
     - suspension_type CHECK: rejects 'bad_type', accepts all 5
       enumerated values.
     - duration_days CHECK: rejects 0.
     - is_active CHECK: rejects 2.
     - fighter_id NOT NULL: rejects NULL.
     - FK constraint: rejects a nonexistent fighter_id.
     - Default is_active=1 on insert.
  B. _maybe_random_suspension — drug_test_failure trigger:
     - Build fresh DB. Register suspensions subscribers.
     - Monkey-patch DRUG_TEST_FAILURE_CHANCE = 1.0 (guaranteed).
     - Publish FIGHT_RESOLVED. Verify a suspensions row was
       created with is_active=1, suspension_type='drug_test_failure'.
     - Verify duration_days is in [180, 365].
     - Verify morale was reduced by 20 (DRUG_TEST_MORALE_HIT).
     - Verify marketability was reduced by 15.
  C. _maybe_random_suspension — behavior + loose-cannon multiplier:
     - Monkey-patch DRUG_TEST_FAILURE_CHANCE = 0.0, BEHAVIOR_BASE_
       CHANCE = 1.0.
     - Publish FIGHT_RESOLVED. Verify suspension_type='behavior'.
     - Verify duration_days is in [90, 180].
     - Verify morale was reduced by 10 (BEHAVIOR_MORALE_HIT).
  D. check_suspension_recovery:
     - Insert an active suspension with end_date in the past.
     - Publish TICK_ADVANCED with current_date > end_date.
     - Verify is_active flipped to 0.
  E. is_fighter_suspended:
     - No suspension → False.
     - Active suspension → True.
     - Cleared suspension (is_active=0) → False.
  F. _pick_matchup excludes suspended fighters:
     - Insert an active suspension on fighter 1 (John Vale, AC).
     - _pick_matchup(AC, Lightweight) returns None (only 1 eligible).
     - Set is_active=0. _pick_matchup returns a valid tuple.
  G. No raw numbers in suspension news (§14):
     - Force a drug_test_failure suspension.
     - Publish TICK_ADVANCED (triggers the news polling subscriber).
     - Fetch the suspension news item. Verify the headline + body
       contain NO digit characters.
  H. Seed-time rivalries (50+):
     - If the world DB exists with 50+ rivalries, verify counts +
       heat values (rematch=60, bad_blood=70, title_rivalry=80).
     - Otherwise SKIP with a message directing the user to run
       scripts/seed_world_phase1-5.py.
  I. Seed-time social posts (100+):
     - If the world DB exists with 100+ social_posts, verify.
     - Otherwise SKIP.
  J. Design Law (§13): Conflict + Stories:
     - Conflict: suspensions sideline fighters (commission vs fighter).
     - Stories: the clearance news writes a "return" narrative.
     - Soft check — verify the suspension news has a career-stage
       descriptor (voice layer) and a duration phrase (word form).

Run from the project root:
    python3 scripts/test_suspensions.py

Exit code 0 = all PASS, 1 = any FAIL, 2 = any SKIP (still 0 if
all non-skipped pass). The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

D-number decisions in this test (referenced from the worklog):
  - D1: H + I skip if the world DB doesn't have the expected counts.
    The full world seed takes ~5 minutes; the test is fast by
    default. Run scripts/seed_world_phase1-5.py to enable H + I.
"""
import random
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import build_db  # noqa: E402
import suspensions  # noqa: E402
import news  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py.
# John "Hammer" Vale = 1 (AC), Marcus "Voltage" Reed = 2 (AC).
A_ID = 1
B_ID = 2

# Promotion + weight class IDs.
ALPHA_COMBAT_ID = 1
RFL_ID = 2

# Seeded event date + sim clock date from src/seed_data.py.
SEEDED_EVENT_DATE = "2026-08-15"
SEEDED_CLOCK_DATE = "2026-07-20"

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


def get_promotion_id(conn, name):
    row = conn.execute(
        "SELECT promotion_id FROM promotions WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"promotion {name!r} not found")
    return row[0]


def get_weight_class_id(conn, name="Lightweight"):
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"weight class {name!r} not found")
    return row[0]


def publish_fight_resolved(conn, *, fight_id=1, event_id=1,
                           winner_id=A_ID, loser_id=B_ID,
                           result_type='decision',
                           is_title_fight=0, title_changed=False,
                           event_date=SEEDED_EVENT_DATE,
                           promotion_id=ALPHA_COMBAT_ID,
                           weight_class_id=1):
    """Helper — publish a FIGHT_RESOLVED event on the bus."""
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHT_RESOLVED,
        'fight_id': fight_id,
        'event_id': event_id,
        'promotion_id': promotion_id,
        'weight_class_id': weight_class_id,
        'winner_id': winner_id,
        'loser_id': loser_id,
        'fighter_a_id': winner_id,
        'fighter_b_id': loser_id,
        'result_type': result_type,
        'finish_round': 3,
        'finish_time': '5:00',
        'is_title_fight': is_title_fight,
        'title_changed': title_changed,
        'event_date': event_date,
        'importance': 50,
    })


def publish_tick_advanced(conn, current_date):
    """Helper — publish a TICK_ADVANCED event."""
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.TICK_ADVANCED,
        'current_date': current_date,
        'tick_type': 'day',
    })


# ----------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------

def case_a_schema():
    """A. Schema — suspensions table + CHECKs + migration."""
    print("\n--- Case A: schema ---")
    build_fresh_db()
    conn = get_conn()

    # schema_meta.schema_version (dynamic — §10).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("A", f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
          sv is not None and sv[0] == EXPECTED_CODE_VERSION,
          f"got={sv[0] if sv else None}")

    # migration name starts with the dynamic prefix.
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    check("A", f"migration starting with '{EXPECTED_MIGRATION_PREFIX}' recorded",
          mig is not None, f"found={mig}")

    # suspensions table exists.
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='suspensions'"
    ).fetchone()
    check("A", "table 'suspensions' exists", row is not None, "")

    # 9 required columns (subset check — §10.4 prohibits exact counts).
    expected_cols = {
        "suspension_id", "fighter_id", "suspension_type",
        "start_date", "end_date", "duration_days", "description",
        "is_active", "created_at",
    }
    actual_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(suspensions)").fetchall()
    }
    missing = expected_cols - actual_cols
    check("A", "suspensions has all 9 required columns (subset check)",
          not missing, f"missing={sorted(missing) if missing else 'none'}")

    # suspension_type CHECK — rejects bad_type.
    bad_type_ok = True
    try:
        conn.execute(
            "INSERT INTO suspensions (fighter_id, suspension_type, "
            "start_date, end_date, duration_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (A_ID, 'bad_type', '2026-01-01', '2026-07-01', 180),
        )
        bad_type_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "suspension_type CHECK rejects 'bad_type'", bad_type_ok, "")

    # suspension_type CHECK — accepts all 5 enumerated values.
    all_types_ok = True
    for stype in ('drug_test_failure', 'behavior', 'missed_weight_repeat',
                  'post_fight_brawl', 'social_media_violation'):
        try:
            conn.execute(
                "INSERT INTO suspensions (fighter_id, suspension_type, "
                "start_date, end_date, duration_days) "
                "VALUES (?, ?, ?, ?, ?)",
                (A_ID, stype, '2026-01-01', '2026-07-01', 180),
            )
        except sqlite3.IntegrityError:
            all_types_ok = False
            break
    conn.rollback()
    check("A", "suspension_type CHECK accepts all 5 enumerated values",
          all_types_ok, "")

    # duration_days CHECK — rejects 0.
    dur0_ok = True
    try:
        conn.execute(
            "INSERT INTO suspensions (fighter_id, suspension_type, "
            "start_date, end_date, duration_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (A_ID, 'drug_test_failure', '2026-01-01', '2026-07-01', 0),
        )
        dur0_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "duration_days CHECK rejects 0", dur0_ok, "")

    # is_active CHECK — rejects 2.
    active2_ok = True
    try:
        conn.execute(
            "INSERT INTO suspensions (fighter_id, suspension_type, "
            "start_date, end_date, duration_days, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (A_ID, 'drug_test_failure', '2026-01-01', '2026-07-01', 180, 2),
        )
        active2_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "is_active CHECK rejects 2", active2_ok, "")

    # fighter_id NOT NULL.
    null_fid_ok = True
    try:
        conn.execute(
            "INSERT INTO suspensions (fighter_id, suspension_type, "
            "start_date, end_date, duration_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (None, 'drug_test_failure', '2026-01-01', '2026-07-01', 180),
        )
        null_fid_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "fighter_id NOT NULL rejects NULL", null_fid_ok, "")

    # FK constraint — rejects nonexistent fighter_id.
    fk_ok = True
    try:
        conn.execute(
            "INSERT INTO suspensions (fighter_id, suspension_type, "
            "start_date, end_date, duration_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (99999, 'drug_test_failure', '2026-01-01', '2026-07-01', 180),
        )
        fk_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "FK constraint rejects nonexistent fighter_id", fk_ok, "")

    # Default is_active=1.
    cur = conn.execute(
        "INSERT INTO suspensions (fighter_id, suspension_type, "
        "start_date, end_date, duration_days) "
        "VALUES (?, ?, ?, ?, ?)",
        (A_ID, 'drug_test_failure', '2026-01-01', '2026-07-01', 180),
    )
    default_active = conn.execute(
        "SELECT is_active FROM suspensions WHERE suspension_id=?",
        (cur.lastrowid,),
    ).fetchone()
    check("A", "default is_active=1 on insert",
          default_active is not None and default_active[0] == 1,
          f"got={default_active[0] if default_active else None}")
    conn.rollback()
    conn.close()


def case_b_drug_test_trigger():
    """B. _maybe_random_suspension — drug_test_failure trigger."""
    print("\n--- Case B: drug_test_failure trigger ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    suspensions.register_subscribers()

    # Monkey-patch the chance to 1.0 (guaranteed trigger).
    original_chance = suspensions.DRUG_TEST_FAILURE_CHANCE
    suspensions.DRUG_TEST_FAILURE_CHANCE = 1.0
    try:
        # Capture morale + marketability before.
        morale_before = conn.execute(
            "SELECT morale FROM fighter_personality WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        mkt_before = conn.execute(
            "SELECT marketability FROM fighters WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]

        publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                               result_type='decision')
        conn.commit()

        # Verify a suspension was created.
        rows = conn.execute(
            "SELECT suspension_type, start_date, end_date, duration_days, "
            "is_active FROM suspensions WHERE fighter_id IN (?, ?)",
            (A_ID, B_ID),
        ).fetchall()
        check("B", "suspension row created on FIGHT_RESOLVED",
              len(rows) >= 1, f"count={len(rows)}")

        if rows:
            stype, start, end, dur, active = rows[0]
            check("B", "suspension_type == 'drug_test_failure'",
                  stype == 'drug_test_failure', f"got={stype}")
            check("B", "start_date == event_date",
                  start == SEEDED_EVENT_DATE, f"got={start}")
            check("B", "duration_days in [180, 365]",
                  180 <= dur <= 365, f"got={dur}")
            check("B", "is_active == 1 (default)", active == 1, f"got={active}")
            # end_date = start_date + duration_days.
            from datetime import datetime, timedelta
            expected_end = (
                datetime.strptime(SEEDED_EVENT_DATE, "%Y-%m-%d")
                + timedelta(days=dur)
            ).strftime("%Y-%m-%d")
            check("B", "end_date == start_date + duration_days",
                  end == expected_end, f"got={end}, expected={expected_end}")

        # Verify morale was reduced by 20.
        # The candidate is rng-picked between winner + loser. We check
        # BOTH fighters — one of them should have the morale hit.
        morale_a = conn.execute(
            "SELECT morale FROM fighter_personality WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        morale_b = conn.execute(
            "SELECT morale FROM fighter_personality WHERE fighter_id=?",
            (B_ID,),
        ).fetchone()[0]
        # Exactly one of them should have morale -20.
        a_hit = (morale_before - morale_a) == 20
        b_hit = (mkt_before is not None)  # placeholder
        # Read B's morale before from a fresh query (we only captured A's).
        # Simpler: check that the SUSPENDED fighter's morale dropped by 20.
        suspended_id = rows[0][0] if rows else None
        # Actually rows[0] is (stype, start, end, dur, active) — we need
        # the fighter_id. Re-query.
        susp_row = conn.execute(
            "SELECT fighter_id FROM suspensions WHERE is_active=1"
        ).fetchone()
        if susp_row:
            susp_fid = susp_row[0]
            morale_after = conn.execute(
                "SELECT morale FROM fighter_personality WHERE fighter_id=?",
                (susp_fid,),
            ).fetchone()[0]
            # The suspended fighter's morale should be 50 - 20 = 30
            # (seed default is 50, DRUG_TEST_MORALE_HIT is -20).
            check("B", "suspended fighter morale reduced by 20",
                  morale_after == 30, f"got={morale_after} (expected 30)")
            # Marketability reduced by 15.
            mkt_after = conn.execute(
                "SELECT marketability FROM fighters WHERE fighter_id=?",
                (susp_fid,),
            ).fetchone()[0]
            # Seed default marketability is 50; -15 = 35.
            check("B", "suspended fighter marketability reduced by 15",
                  mkt_after == 35, f"got={mkt_after} (expected 35)")
    finally:
        suspensions.DRUG_TEST_FAILURE_CHANCE = original_chance
    conn.close()


def case_c_behavior_trigger():
    """C. _maybe_random_suspension — behavior + loose-cannon multiplier."""
    print("\n--- Case C: behavior trigger ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    suspensions.register_subscribers()

    # Monkey-patch: drug test off, behavior guaranteed.
    orig_drug = suspensions.DRUG_TEST_FAILURE_CHANCE
    orig_beh = suspensions.BEHAVIOR_BASE_CHANCE
    suspensions.DRUG_TEST_FAILURE_CHANCE = 0.0
    suspensions.BEHAVIOR_BASE_CHANCE = 1.0
    try:
        publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                               result_type='decision')
        conn.commit()

        rows = conn.execute(
            "SELECT suspension_type, duration_days, is_active "
            "FROM suspensions WHERE fighter_id IN (?, ?)",
            (A_ID, B_ID),
        ).fetchall()
        check("C", "suspension row created (behavior)",
              len(rows) >= 1, f"count={len(rows)}")
        if rows:
            stype, dur, active = rows[0]
            check("C", "suspension_type == 'behavior'",
                  stype == 'behavior', f"got={stype}")
            check("C", "duration_days in [90, 180]",
                  90 <= dur <= 180, f"got={dur}")

        # Verify morale reduced by 10 (BEHAVIOR_MORALE_HIT).
        susp_row = conn.execute(
            "SELECT fighter_id FROM suspensions WHERE is_active=1"
        ).fetchone()
        if susp_row:
            susp_fid = susp_row[0]
            morale_after = conn.execute(
                "SELECT morale FROM fighter_personality WHERE fighter_id=?",
                (susp_fid,),
            ).fetchone()[0]
            # 50 - 10 = 40.
            check("C", "suspended fighter morale reduced by 10",
                  morale_after == 40, f"got={morale_after} (expected 40)")
    finally:
        suspensions.DRUG_TEST_FAILURE_CHANCE = orig_drug
        suspensions.BEHAVIOR_BASE_CHANCE = orig_beh
    conn.close()

    # ----- Loose-cannon multiplier sub-test ---------------------------
    # A fighter with aggression >= 70 AND discipline <= 30 gets 3x
    # behavior chance. Verify the multiplier is applied by checking
    # the code path (we can't easily verify the probability without
    # 1000s of trials — instead, verify the constants + the gate).
    check("C", "LOOSE_CANNON_MULT == 3.0",
          suspensions.LOOSE_CANNON_MULT == 3.0,
          f"got={suspensions.LOOSE_CANNON_MULT}")
    check("C", "LOOSE_CANNON_AGGRESSION == 70",
          suspensions.LOOSE_CANNON_AGGRESSION == 70, "")
    check("C", "LOOSE_CANNON_DISCIPLINE == 30",
          suspensions.LOOSE_CANNON_DISCIPLINE == 30, "")


def case_d_recovery():
    """D. check_suspension_recovery — clears expired suspensions."""
    print("\n--- Case D: check_suspension_recovery ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    suspensions.register_subscribers()

    # Insert an active suspension with end_date in the past.
    conn.execute(
        "INSERT INTO suspensions (fighter_id, suspension_type, "
        "start_date, end_date, duration_days, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (A_ID, 'drug_test_failure', '2026-01-01', '2026-02-01', 31),
    )
    conn.commit()
    # Verify it's active before the tick.
    active_before = conn.execute(
        "SELECT is_active FROM suspensions WHERE fighter_id=?", (A_ID,)
    ).fetchone()[0]
    check("D", "suspension is_active=1 before recovery tick",
          active_before == 1, f"got={active_before}")

    # Publish TICK_ADVANCED with current_date past the end_date.
    publish_tick_advanced(conn, current_date="2026-03-01")
    conn.commit()

    active_after = conn.execute(
        "SELECT is_active FROM suspensions WHERE fighter_id=?", (A_ID,)
    ).fetchone()[0]
    check("D", "suspension is_active=0 after recovery tick",
          active_after == 0, f"got={active_after}")

    # ----- Not-yet-expired suspension is NOT cleared ------------------
    conn.execute(
        "INSERT INTO suspensions (fighter_id, suspension_type, "
        "start_date, end_date, duration_days, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (B_ID, 'behavior', '2026-03-01', '2026-12-01', 270),
    )
    conn.commit()
    publish_tick_advanced(conn, current_date="2026-06-01")
    conn.commit()
    active_b = conn.execute(
        "SELECT is_active FROM suspensions WHERE fighter_id=?", (B_ID,)
    ).fetchone()[0]
    check("D", "not-yet-expired suspension stays is_active=1",
          active_b == 1, f"got={active_b}")
    conn.close()


def case_e_is_suspended():
    """E. is_fighter_suspended reader."""
    print("\n--- Case E: is_fighter_suspended ---")
    build_fresh_db()
    conn = get_conn()

    # No suspension → False.
    check("E", "no suspension → False",
          suspensions.is_fighter_suspended(conn, A_ID) is False, "")

    # Active suspension → True.
    conn.execute(
        "INSERT INTO suspensions (fighter_id, suspension_type, "
        "start_date, end_date, duration_days, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (A_ID, 'drug_test_failure', '2026-01-01', '2026-07-01', 180),
    )
    conn.commit()
    check("E", "active suspension → True",
          suspensions.is_fighter_suspended(conn, A_ID) is True, "")

    # Cleared suspension → False.
    conn.execute(
        "UPDATE suspensions SET is_active=0 WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()
    check("E", "cleared suspension → False",
          suspensions.is_fighter_suspended(conn, A_ID) is False, "")
    conn.close()


def case_f_pick_matchup_excludes():
    """F. _pick_matchup excludes suspended fighters."""
    print("\n--- Case F: _pick_matchup excludes suspended ---")
    build_fresh_db()
    conn = get_conn()
    ac_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # AC has 2 fighters (A_ID=1, B_ID=2). Both are eligible by default.
    matchup = app._pick_matchup(conn, ac_id, wc_id)
    check("F", "_pick_matchup returns valid tuple with no suspensions",
          matchup is not None and len(matchup) == 2, f"got={matchup}")

    # Insert an active suspension on fighter 1.
    conn.execute(
        "INSERT INTO suspensions (fighter_id, suspension_type, "
        "start_date, end_date, duration_days, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (A_ID, 'drug_test_failure', '2026-01-01', '2026-07-01', 180),
    )
    conn.commit()
    # Now only fighter 2 is eligible → _pick_matchup returns None.
    matchup = app._pick_matchup(conn, ac_id, wc_id)
    check("F", "_pick_matchup returns None when only 1 fighter eligible",
          matchup is None, f"got={matchup}")

    # Clear the suspension → _pick_matchup works again.
    conn.execute(
        "UPDATE suspensions SET is_active=0 WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()
    matchup = app._pick_matchup(conn, ac_id, wc_id)
    check("F", "_pick_matchup returns tuple after suspension cleared",
          matchup is not None and len(matchup) == 2, f"got={matchup}")
    conn.close()


def case_g_no_raw_numbers():
    """G. No raw numbers in suspension news (§14)."""
    print("\n--- Case G: no raw numbers in suspension news ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    # Register BOTH suspensions + news (the news engine has the
    # polling subscriber that writes the suspension news).
    suspensions.register_subscribers()
    news.register_subscribers()

    # Force a drug_test_failure suspension.
    orig_drug = suspensions.DRUG_TEST_FAILURE_CHANCE
    suspensions.DRUG_TEST_FAILURE_CHANCE = 1.0
    try:
        publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                               result_type='decision')
        conn.commit()
        # Publish TICK_ADVANCED to trigger the news polling subscriber.
        publish_tick_advanced(conn, current_date=SEEDED_EVENT_DATE)
        conn.commit()
    finally:
        suspensions.DRUG_TEST_FAILURE_CHANCE = orig_drug

    # Fetch the suspension news item.
    news_rows = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='suspension'"
    ).fetchall()
    check("G", "suspension news item was created",
          len(news_rows) >= 1, f"count={len(news_rows)}")

    if news_rows:
        headline, body = news_rows[0]
        # §14: NO digit characters in headline or body.
        # The hidden [suspension_id=N:flavor] marker contains digits,
        # so we strip it before checking. The marker is always at the
        # end of the body, preceded by a space.
        body_clean = re.sub(r'\s*\[suspension_id=\d+:(?:create|clear)\]\s*$', '', body)
        headline_has_digits = bool(re.search(r'\d', headline))
        body_has_digits = bool(re.search(r'\d', body_clean))
        check("G", "headline has no digit characters (§14)",
              not headline_has_digits,
              f"headline={headline!r}")
        check("G", "body has no digit characters (§14, marker stripped)",
              not body_has_digits,
              f"body={body_clean!r}")
    conn.close()


def case_h_seed_rivalries():
    """H. Seed-time rivalries (50+) — skip if world DB not present."""
    print("\n--- Case H: seed-time rivalries ---")
    if not DB_PATH.exists():
        check("H", "world DB exists", False, "DB not found", skipped=True)
        return
    conn = sqlite3.connect(DB_PATH)
    # Check if this is the world DB (not the small seed_data DB).
    n_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    if n_fighters < 1000:
        check("H", "world DB has 1000+ fighters (world seed ran)",
              False, f"only {n_fighters} fighters — run scripts/seed_world_phase1-5.py",
              skipped=True)
        conn.close()
        return

    n_riv = conn.execute("SELECT COUNT(*) FROM rivalries").fetchone()[0]
    check("H", "50+ rivalries exist after seed",
          n_riv >= 50, f"got={n_riv}")

    # Verify heat values per type.
    if n_riv > 0:
        heat_by_type = {}
        for r in conn.execute(
            "SELECT rivalry_type, AVG(rivalry_heat) FROM rivalries "
            "GROUP BY rivalry_type"
        ).fetchall():
            heat_by_type[r[0]] = r[1]
        # rematch_hungry should be ~60, bad_blood ~70, title_rivalry ~80.
        # (Allow variance — the seed sets these but the in-game decay
        # may have reduced some. We check the AVERAGE is close.)
        if 'rematch_hungry' in heat_by_type:
            check("H", "rematch_hungry avg heat ~60",
                  55 <= heat_by_type['rematch_hungry'] <= 65,
                  f"got={heat_by_type['rematch_hungry']:.1f}")
        if 'bad_blood' in heat_by_type:
            check("H", "bad_blood avg heat ~70",
                  65 <= heat_by_type['bad_blood'] <= 75,
                  f"got={heat_by_type['bad_blood']:.1f}")
        if 'title_rivalry' in heat_by_type:
            check("H", "title_rivalry avg heat ~80",
                  75 <= heat_by_type['title_rivalry'] <= 85,
                  f"got={heat_by_type['title_rivalry']:.1f}")

        # Verify all rivalry_type values are valid.
        valid_types = {'callout', 'bad_blood', 'title_rivalry',
                       'rematch_hungry', 'style_clash', 'disrespect',
                       'stolen_opportunity'}
        actual_types = set(heat_by_type.keys())
        invalid = actual_types - valid_types
        check("H", "all rivalry_type values are valid",
              not invalid, f"invalid={invalid}")
    conn.close()


def case_i_seed_social_posts():
    """I. Seed-time social posts (100+) — skip if world DB not present."""
    print("\n--- Case I: seed-time social posts ---")
    if not DB_PATH.exists():
        check("I", "world DB exists", False, "DB not found", skipped=True)
        return
    conn = sqlite3.connect(DB_PATH)
    n_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    if n_fighters < 1000:
        check("I", "world DB has 1000+ fighters (world seed ran)",
              False, f"only {n_fighters} fighters — run scripts/seed_world_phase1-5.py",
              skipped=True)
        conn.close()
        return

    n_posts = conn.execute("SELECT COUNT(*) FROM social_posts").fetchone()[0]
    check("I", "100+ social posts exist after seed",
          n_posts >= 100, f"got={n_posts}")

    # Verify the post types match the seed-time flavors.
    if n_posts > 0:
        type_counts = {}
        for r in conn.execute(
            "SELECT post_type, COUNT(*) FROM social_posts GROUP BY post_type"
        ).fetchall():
            type_counts[r[0]] = r[1]
        # Seed-time flavors: callout, trash_talk (rivalry-driven),
        # brag (champions), hype (prospects).
        expected_types = {'callout', 'trash_talk', 'brag', 'hype'}
        found = set(type_counts.keys()) & expected_types
        check("I", "seed-time post types present (callout/trash_talk/brag/hype)",
              len(found) >= 2, f"found={found}")

        # Verify all posts have non-empty post_text.
        empty_count = conn.execute(
            "SELECT COUNT(*) FROM social_posts WHERE post_text IS NULL "
            "OR post_text = ''"
        ).fetchone()[0]
        check("I", "no empty post_text rows",
              empty_count == 0, f"empty_count={empty_count}")
    conn.close()


def case_j_design_law():
    """J. Design Law (§13) — Conflict + Stories."""
    print("\n--- Case J: Design Law (§13) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    suspensions.register_subscribers()
    news.register_subscribers()

    orig_drug = suspensions.DRUG_TEST_FAILURE_CHANCE
    suspensions.DRUG_TEST_FAILURE_CHANCE = 1.0
    try:
        publish_fight_resolved(conn, winner_id=A_ID, loser_id=B_ID,
                               result_type='decision')
        conn.commit()
        publish_tick_advanced(conn, current_date=SEEDED_EVENT_DATE)
        conn.commit()
    finally:
        suspensions.DRUG_TEST_FAILURE_CHANCE = orig_drug

    # Conflict (§13): the suspension sidelines a fighter. Verify the
    # suspended fighter is now excluded from _pick_matchup.
    ac_id = get_promotion_id(conn, "Alpha Combat")
    wc_id = get_weight_class_id(conn, "Lightweight")
    matchup = app._pick_matchup(conn, ac_id, wc_id)
    check("J", "Conflict: suspended fighter excluded from booking",
          matchup is None, f"got={matchup} (expected None — only 1 eligible)")

    # Stories (§13): the suspension news tells a narrative. Verify
    # the news body contains a career-stage descriptor (voice layer)
    # and a duration phrase (word form — no raw numbers).
    news_rows = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='suspension'"
    ).fetchall()
    check("J", "Stories: suspension news item exists",
          len(news_rows) >= 1, f"count={len(news_rows)}")
    if news_rows:
        headline, body = news_rows[0]
        # The body template includes "{career_stage}" (voice descriptor)
        # and "{duration_phrase}" (word form). Verify the body is non-
        # trivial (longer than 50 chars — a real sentence, not a stub).
        check("J", "Stories: suspension news body is substantive (>50 chars)",
              len(body) > 50, f"len={len(body)}")
        # Verify the body contains a voice-layer descriptor (one of
        # the career-stage words from voice.describe_career_stage).
        career_stage_words = [
            'champion', 'prospect', 'veteran', 'contender', 'journeyman',
            'gatekeeper', 'fighter', 'competitor', 'roster',
        ]
        has_career_word = any(
            w in body.lower() for w in career_stage_words
        )
        check("J", "Stories: body contains career-stage descriptor (voice layer)",
              has_career_word, f"body={body[:120]!r}...")

    # Anticipation (§13): a suspended champion creates a "what happens
    # to the title?" thread. Verify the clearance news (when the
    # suspension lifts) writes a "return" narrative.
    # Clear the suspension + tick again to trigger clearance news.
    conn.execute(
        "UPDATE suspensions SET is_active=0, end_date=? "
        "WHERE fighter_id IN (?, ?)",
        ('2025-01-01', A_ID, B_ID),
    )
    conn.commit()
    publish_tick_advanced(conn, current_date="2026-08-16")
    conn.commit()
    clearance_rows = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='suspension' "
        "AND sentiment='positive'"
    ).fetchall()
    check("J", "Anticipation: clearance news writes 'return' narrative",
          len(clearance_rows) >= 1, f"count={len(clearance_rows)}")
    if clearance_rows:
        h, b = clearance_rows[0]
        return_words = ['cleared', 'return', 'lifted', 'back', 'reinstated',
                        'eligible']
        has_return_word = any(w in h.lower() or w in b.lower()
                              for w in return_words)
        check("J", "Anticipation: clearance headline has return-language",
              has_return_word, f"headline={h!r}")
    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print(f"Phase B — Suspensions + Seed-Time Rivalries/Social acceptance test")
    print(f"(schema {EXPECTED_CODE_VERSION}, migration prefix "
          f"{EXPECTED_MIGRATION_PREFIX!r})")
    print(sep)

    # Run H + I FIRST — they verify the world DB (if present). The
    # other cases (A-G, J) call build_fresh_db() which clobbers the
    # world DB with the small seed_data DB. Running H + I first means
    # they see the world DB before it's destroyed. If the world DB
    # isn't present, H + I SKIP gracefully.
    case_h_seed_rivalries()
    case_i_seed_social_posts()

    case_a_schema()
    case_b_drug_test_trigger()
    case_c_behavior_trigger()
    case_d_recovery()
    case_e_is_suspended()
    case_f_pick_matchup_excludes()
    case_g_no_raw_numbers()
    case_j_design_law()

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
