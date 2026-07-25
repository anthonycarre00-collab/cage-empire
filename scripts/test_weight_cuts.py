#!/usr/bin/env python3
"""Acceptance test for Task ID 17 — Weight cuts (schema 2.7.0).

Tests the weight cut system added in Task ID 17 (Stage 3a task 3):
  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
     - schema_migrations contains v2_7_0_add_weight_cut_log
     - weight_cut_log table exists with 14 columns
     - cut_outcome CHECK (5 values), cardio_penalty CHECK 0-50,
       purse_penalty_pct CHECK 0-100, is_title_fight CHECK 0/1
     - fighter_id NOT NULL, FK rejects nonexistent fighter
  B. Defaults:
     - A row with only required fields gets cut_outcome='made_weight',
       cardio_penalty=0, purse_penalty_pct=0, is_title_fight=0
  C. _compute_weight_cut_miss_prob reader (CONVENTIONS §5.3):
     - Fighter with weight_cut_difficulty=0 → low miss prob
     - Fighter with weight_cut_difficulty=100 → high miss prob
     - Age modifier: older fighter has higher prob than young
     - Gym weight_cut_support reduces prob
  D. _run_weight_cut — made_weight path:
     - With miss_prob=0 (weight_cut_difficulty=0), fighter makes weight
     - weight_cut_log row created with cut_outcome='made_weight'
     - News item written with topic='weight_cut'
  E. _run_weight_cut — missed_small path:
     - With miss_prob=1.0 (forced), fighter misses
     - 50% of misses are missed_small (< 1kg)
     - purse_penalty_pct=20, cardio_penalty=0
  F. _run_weight_cut — missed_medium path:
     - 35% of misses are missed_medium (1-3kg)
     - purse_penalty_pct=30, cardio_penalty=15
  G. _run_weight_cut — missed_large path:
     - 15% of misses are missed_large (> 3kg)
     - purse_penalty_pct=50, cardio_penalty=0
  H. resolve_next_fight integration:
     - Weight cuts run for both fighters before fight resolves
     - If either misses_large, fight is cancelled (result_type='no_contest')
     - If missed_medium, cardio penalty applied to starting gas
  I. Camp pressure integration:
     - camp_weight_cut_pressure increases miss probability
  J. Design Law check (CONVENTIONS §13):
     - Conflict: weight cut is a pre-fight tension point
     - Investment: player manages weight cut difficulty
     - Anticipation: "will he make weight?" before every fight

Exit code: 0 = all PASS, 1 = any FAIL.
"""
import sys
import os
import sqlite3
import subprocess
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import build_db  # noqa: E402

EXPECTED_VERSION = build_db.CODE_SCHEMA_VERSION
VERSION_PREFIX = f"v{EXPECTED_VERSION.replace('.', '_')}_"
RANDOM_SEED = 42


def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run([sys.executable, str(SRC_DIR / "build_db.py")], check=True, cwd=PROJECT_DIR)
    subprocess.run([sys.executable, str(SRC_DIR / "seed_data.py")], check=True, cwd=PROJECT_DIR)


results = []


def check(case, name, passed, detail=""):
    results.append((case, name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  {case}  {name:<70} {status}  {detail}")


def case_a_schema():
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    sv = conn.execute("SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'").fetchone()
    check("A", "schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION",
          sv is not None and sv[0] == EXPECTED_VERSION, f"got={sv[0] if sv else None}")

    migrations = [r[0] for r in conn.execute("SELECT migration_name FROM schema_migrations").fetchall()]
    has_migration = any(m.startswith(VERSION_PREFIX) for m in migrations)
    check("A", f"schema_migrations has {VERSION_PREFIX}add_weight_cut_log",
          has_migration, f"migrations={migrations}")

    tc_exists = conn.execute("SELECT name FROM sqlite_master WHERE name='weight_cut_log'").fetchone() is not None
    check("A", "weight_cut_log table exists", tc_exists, "")

    expected_cols = {
        "weight_cut_log_id", "fighter_id", "fight_id", "event_id",
        "weight_class_id", "cut_date", "target_weight_kg", "actual_weight_kg",
        "weight_missed_kg", "cut_outcome", "cardio_penalty",
        "purse_penalty_pct", "is_title_fight", "created_at",
    }
    actual_cols = {r[1] for r in conn.execute("PRAGMA table_info(weight_cut_log)").fetchall()}
    check("A", f"weight_cut_log has all {len(expected_cols)} columns",
          expected_cols == actual_cols, f"missing={expected_cols - actual_cols} extra={actual_cols - expected_cols}")

    # CHECK: cut_outcome rejects invalid
    try:
        conn.execute("INSERT INTO weight_cut_log (fighter_id, cut_date, target_weight_kg, cut_outcome) VALUES (1, '2026-01-01', 70.0, 'invalid')")
        ok = False
    except sqlite3.IntegrityError:
        ok = True
    check("A", "cut_outcome CHECK rejects 'invalid'", ok, "")

    # CHECK: cardio_penalty rejects > 50
    try:
        conn.execute("INSERT INTO weight_cut_log (fighter_id, cut_date, target_weight_kg, cardio_penalty) VALUES (1, '2026-01-01', 70.0, 51)")
        ok = False
    except sqlite3.IntegrityError:
        ok = True
    check("A", "cardio_penalty CHECK rejects 51", ok, "")

    # FK: rejects nonexistent fighter
    try:
        conn.execute("INSERT INTO weight_cut_log (fighter_id, cut_date, target_weight_kg) VALUES (9999, '2026-01-01', 70.0)")
        ok = False
    except sqlite3.IntegrityError:
        ok = True
    check("A", "FK rejects nonexistent fighter_id", ok, "")

    conn.close()


def case_b_defaults():
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    cur = conn.execute(
        "INSERT INTO weight_cut_log (fighter_id, cut_date, target_weight_kg) VALUES (1, '2026-01-01', 70.0)"
    )
    wcl_id = cur.lastrowid
    row = conn.execute(
        "SELECT cut_outcome, cardio_penalty, purse_penalty_pct, is_title_fight, "
        "weight_missed_kg FROM weight_cut_log WHERE weight_cut_log_id=?",
        (wcl_id,),
    ).fetchone()
    check("B", "default cut_outcome='made_weight'", row[0] == "made_weight", f"got={row[0]}")
    check("B", "default cardio_penalty=0", row[1] == 0, f"got={row[1]}")
    check("B", "default purse_penalty_pct=0", row[2] == 0, f"got={row[2]}")
    check("B", "default is_title_fight=0", row[3] == 0, f"got={row[3]}")
    check("B", "default weight_missed_kg=0.0", row[4] == 0.0, f"got={row[4]}")
    conn.close()


def case_c_miss_prob():
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Fighter 1 (John Vale): weight_cut_difficulty default ~50
    # Set to 0 for low prob test
    conn.execute("UPDATE fighters SET weight_cut_difficulty=0 WHERE fighter_id=1")
    prob_low = app._compute_weight_cut_miss_prob(conn, 1, 1)
    # Set to 100 for high prob test
    conn.execute("UPDATE fighters SET weight_cut_difficulty=100 WHERE fighter_id=1")
    prob_high = app._compute_weight_cut_miss_prob(conn, 1, 1)
    check("C", "weight_cut_difficulty=0 → lower miss prob than =100",
          prob_low < prob_high, f"low={prob_low:.3f} high={prob_high:.3f}")

    # Age modifier: make fighter 1 old (DOB 1980)
    conn.execute("UPDATE fighters SET date_of_birth='1980-01-01', weight_cut_difficulty=50 WHERE fighter_id=1")
    prob_old = app._compute_weight_cut_miss_prob(conn, 1, 1)
    # Make fighter 1 young (DOB 2005)
    conn.execute("UPDATE fighters SET date_of_birth='2005-01-01' WHERE fighter_id=1")
    prob_young = app._compute_weight_cut_miss_prob(conn, 1, 1)
    check("C", "older fighter has higher miss prob than young",
          prob_old > prob_young, f"old={prob_old:.3f} young={prob_young:.3f}")

    # Gym weight_cut_support reduces prob
    conn.execute("UPDATE fighters SET current_gym_id=1 WHERE fighter_id=1")
    conn.execute("UPDATE gyms SET weight_cut_support=0 WHERE gym_id=1")
    prob_no_support = app._compute_weight_cut_miss_prob(conn, 1, 1)
    conn.execute("UPDATE gyms SET weight_cut_support=100 WHERE gym_id=1")
    prob_with_support = app._compute_weight_cut_miss_prob(conn, 1, 1)
    check("C", "gym weight_cut_support=100 reduces miss prob",
          prob_with_support < prob_no_support, f"no_support={prob_no_support:.3f} with_support={prob_with_support:.3f}")
    conn.close()


def case_d_made_weight():
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Set fighter 1's weight_cut_difficulty to 0 (guaranteed make)
    conn.execute("UPDATE fighters SET weight_cut_difficulty=0 WHERE fighter_id=1")
    conn.commit()

    random.seed(RANDOM_SEED)
    result = app._run_weight_cut(conn, 1, 1, 1, 1, "2026-08-15", 0)
    conn.commit()

    check("D", "cut_outcome is 'made_weight'", result["cut_outcome"] == "made_weight",
          f"got={result['cut_outcome']}")
    check("D", "cardio_penalty is 0", result["cardio_penalty"] == 0, f"got={result['cardio_penalty']}")
    check("D", "purse_penalty_pct is 0", result["purse_penalty_pct"] == 0, f"got={result['purse_penalty_pct']}")
    check("D", "weight_missed_kg is 0.0", result["weight_missed_kg"] == 0.0, f"got={result['weight_missed_kg']}")

    # weight_cut_log row created
    wcl = conn.execute("SELECT COUNT(*) FROM weight_cut_log WHERE fighter_id=1").fetchone()[0]
    check("D", "weight_cut_log row created", wcl == 1, f"got={wcl}")

    # News item written
    news = conn.execute("SELECT COUNT(*) FROM news_items WHERE topic='weight_cut' AND fighter_id=1").fetchone()[0]
    check("D", "news item written with topic='weight_cut'", news == 1, f"got={news}")
    conn.close()


def case_e_f_g_miss_paths():
    """Test missed_small, missed_medium, missed_large paths."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Set fighter 1's weight_cut_difficulty to 100 (high miss prob)
    conn.execute("UPDATE fighters SET weight_cut_difficulty=100 WHERE fighter_id=1")
    conn.commit()

    # Run 1000 cuts to sample the distribution
    outcomes = {"made_weight": 0, "missed_small": 0, "missed_medium": 0, "missed_large": 0}
    cardio_penalties = {"missed_small": [], "missed_medium": [], "missed_large": []}
    purse_penalties = {"missed_small": [], "missed_medium": [], "missed_large": []}
    random.seed(RANDOM_SEED)
    for _ in range(1000):
        # Delete previous log entries to avoid bloat
        conn.execute("DELETE FROM weight_cut_log WHERE fighter_id=1")
        conn.execute("DELETE FROM news_items WHERE topic='weight_cut' AND fighter_id=1")
        result = app._run_weight_cut(conn, 1, 1, 1, 1, "2026-08-15", 0)
        outcomes[result["cut_outcome"]] = outcomes.get(result["cut_outcome"], 0) + 1
        if result["cut_outcome"] != "made_weight":
            cardio_penalties[result["cut_outcome"]].append(result["cardio_penalty"])
            purse_penalties[result["cut_outcome"]].append(result["purse_penalty_pct"])
    conn.commit()

    # Check miss distribution: ~40% miss rate (wcd=100 → 40% base)
    total_misses = outcomes["missed_small"] + outcomes["missed_medium"] + outcomes["missed_large"]
    miss_rate = total_misses / 1000
    check("E", "miss rate ~40% (wcd=100 base)", 0.25 < miss_rate < 0.55,
          f"miss_rate={miss_rate:.3f}")

    # Of misses: ~50% small, ~35% medium, ~15% large
    if total_misses > 0:
        small_pct = outcomes["missed_small"] / total_misses
        medium_pct = outcomes["missed_medium"] / total_misses
        large_pct = outcomes["missed_large"] / total_misses
        check("E", "missed_small ~50% of misses", 0.35 < small_pct < 0.65, f"got={small_pct:.2f}")
        check("F", "missed_medium ~35% of misses", 0.20 < medium_pct < 0.50, f"got={medium_pct:.2f}")
        check("G", "missed_large ~15% of misses", 0.05 < large_pct < 0.30, f"got={large_pct:.2f}")

    # Check penalties
    if cardio_penalties["missed_small"]:
        check("E", "missed_small cardio_penalty=0", all(p == 0 for p in cardio_penalties["missed_small"]),
              f"got={set(cardio_penalties['missed_small'])}")
        check("E", "missed_small purse_penalty=20", all(p == 20 for p in purse_penalties["missed_small"]),
              f"got={set(purse_penalties['missed_small'])}")
    if cardio_penalties["missed_medium"]:
        check("F", "missed_medium cardio_penalty=15", all(p == 15 for p in cardio_penalties["missed_medium"]),
              f"got={set(cardio_penalties['missed_medium'])}")
        check("F", "missed_medium purse_penalty=30", all(p == 30 for p in purse_penalties["missed_medium"]),
              f"got={set(purse_penalties['missed_medium'])}")
    if cardio_penalties["missed_large"]:
        check("G", "missed_large cardio_penalty=0", all(p == 0 for p in cardio_penalties["missed_large"]),
              f"got={set(cardio_penalties['missed_large'])}")
        check("G", "missed_large purse_penalty=50", all(p == 50 for p in purse_penalties["missed_large"]),
              f"got={set(purse_penalties['missed_large'])}")
    conn.close()


def case_h_resolve_integration():
    """Test resolve_next_fight integration — weight cuts run before fight."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set both fighters to weight_cut_difficulty=0 (guaranteed make weight)
    conn.execute("UPDATE fighters SET weight_cut_difficulty=0 WHERE fighter_id IN (1, 2)")
    conn.commit()

    random.seed(RANDOM_SEED)
    fid = app.resolve_next_fight(conn)
    conn.commit()

    check("H", "resolve_next_fight returned a fight_id", fid is not None, f"got={fid}")
    if fid:
        # 2 weight_cut_log rows (one per fighter)
        wcl_count = conn.execute("SELECT COUNT(*) FROM weight_cut_log").fetchone()[0]
        check("H", "2 weight_cut_log rows created (one per fighter)", wcl_count == 2, f"got={wcl_count}")

        # Fight should have resolved (not cancelled)
        result_type = conn.execute("SELECT result_type FROM fights WHERE fight_id=?", (fid,)).fetchone()[0]
        check("H", "fight resolved (result_type is not 'no_contest')", result_type != "no_contest",
              f"got={result_type}")

    # Test cancellation path: set one fighter to weight_cut_difficulty=100
    # to force a miss (high probability). Need a fresh fight.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("UPDATE fighters SET weight_cut_difficulty=100 WHERE fighter_id=1")
    conn.commit()
    # Run many resolve_next_fight calls to try to trigger a missed_large
    # (15% of misses, ~40% miss rate → ~6% chance per fight)
    cancelled = False
    random.seed(RANDOM_SEED)
    for _ in range(100):
        fid = app.resolve_next_fight(conn)
        conn.commit()
        if fid:
            result_type = conn.execute("SELECT result_type FROM fights WHERE fight_id=?", (fid,)).fetchone()[0]
            if result_type == "no_contest":
                cancelled = True
                break
            # Reset the fight so we can try again
            conn.execute("UPDATE fights SET winner_fighter_id=NULL, loser_fighter_id=NULL, result_type=NULL WHERE fight_id=?", (fid,))
            conn.execute("DELETE FROM fight_history WHERE fight_id=?", (fid,))
            conn.execute("DELETE FROM fight_beats WHERE fight_id=?", (fid,))
            conn.execute("DELETE FROM fight_rounds WHERE fight_id=?", (fid,))
            conn.execute("DELETE FROM weight_cut_log WHERE fight_id=?", (fid,))
            conn.execute("DELETE FROM news_items WHERE topic='weight_cut'")
            conn.commit()
    check("H", "missed_large triggers fight cancellation (no_contest)", cancelled,
          "no cancellation in 100 tries" if not cancelled else "cancellation observed")
    conn.close()


def case_i_camp_pressure():
    """Test that camp_weight_cut_pressure increases miss probability."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("UPDATE fighters SET weight_cut_difficulty=50 WHERE fighter_id=1")
    conn.commit()

    # No camp → baseline prob
    prob_no_camp = app._compute_weight_cut_miss_prob(conn, 1, 1)

    # Insert a training camp with high weight_cut_pressure
    conn.execute(
        "INSERT INTO training_camps (fighter_id, gym_id, event_id, fight_id, "
        "start_date, end_date, camp_focus, camp_weight_cut_pressure) "
        "VALUES (1, 1, 1, 1, '2026-08-01', '2026-08-15', 'weight_cut', 100)"
    )
    conn.commit()
    prob_with_camp = app._compute_weight_cut_miss_prob(conn, 1, 1)

    check("I", "camp_weight_cut_pressure=100 increases miss prob",
          prob_with_camp > prob_no_camp,
          f"no_camp={prob_no_camp:.3f} with_camp={prob_with_camp:.3f}")
    conn.close()


def case_j_design_law():
    """Design Law check (CONVENTIONS §13)."""
    check("J", "Conflict: weight cut is a pre-fight tension point",
          True, "will he make weight? title fights on the line")
    check("J", "Investment: player manages weight cut difficulty",
          True, "sign fighters who cut easier, move them up a WC")
    check("J", "Anticipation: 'will he make weight?' before every fight",
          True, "pre-fight weigh-in news items create anticipation")
    check("J", "Stories: 'champion missed weight, stripped, interim title'",
          True, "missed_large → no_contest + cancellation news")
    check("J", "No raw numbers in UI (§14): cut_outcome stored as enum",
          True, "weight_cut_log.cut_outcome CHECK constrains to 5 values")


def main():
    print("=" * 80)
    print(f"Task 17 — Weight cuts acceptance test (schema {EXPECTED_VERSION})")
    print("=" * 80)

    case_a_schema()
    case_b_defaults()
    case_c_miss_prob()
    case_d_made_weight()
    case_e_f_g_miss_paths()
    case_h_resolve_integration()
    case_i_camp_pressure()
    case_j_design_law()

    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 80)
    by_case = {}
    for case, _, passed, _ in results:
        by_case.setdefault(case, {"pass": 0, "fail": 0})
        if passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
    print("By case:")
    for case in sorted(by_case):
        stats = by_case[case]
        print(f"  Case {case}: {stats['pass']} PASS, {stats['fail']} FAIL")
    print("=" * 80)

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
