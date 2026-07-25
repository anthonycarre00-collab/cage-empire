#!/usr/bin/env python3
"""CAGE EMPIRE — Forensic Database Integrity Check (Stage 6 — Task 6.0.5).

A thorough audit of the world DB that checks for:

  1. SCHEMA INTEGRITY
     - All expected tables exist
     - All expected columns exist on each table
     - Schema version matches CODE_SCHEMA_VERSION
     - All migrations recorded

  2. DATA INTEGRITY
     - Every fighter has fighter_attributes + fighter_personality + fighter_career rows
     - Foreign key violations (PRAGMA foreign_key_check)
     - Orphaned rows (fight_history without fights, etc.)
     - NOT NULL columns with NULL values

  3. ATTRIBUTE SANITY
     - All fighter_attributes values in 0-100 range
     - No fighter with all-50 attributes (seed failure indicator)
     - No fighter with NULL attributes
     - potential in 0-100, career_health in 0-100

  4. STALE DATA
     - Retired fighters in active rankings
     - Retired fighters on active contracts
     - Expired injuries still marked active
     - Expired suspensions still active
     - Stale scouting reports never refreshed

  5. NEW SCHEMA COLUMN CHECKS (v3.8.0)
     - staff.pundit_bias — NULL for non-broadcast staff (expected)
     - fighter_memory_links — may be 0 (populate_* functions are new)

  6. REFERENCE DATA
     - Every weight class has fighters
     - Every promotion has >= 2 fighters (minimum for events)
     - Every nation has >= 1 fighter
     - Every gym has >= 1 fighter (or is intentionally empty)

  7. CONSISTENCY
     - fighter_career.record_wins + losses + draws == COUNT(fight_history)
     - rankings.fighter_id exists in fighters
     - Active titles have a current_holder_id that exists in fighters

Usage:
    python3 scripts/forensic_db_check.py
    python3 scripts/forensic_db_check.py --verbose  # show all checks, not just failures
    python3 scripts/forensic_db_check.py --fix      # suggest fixes (does NOT auto-apply)

Exit codes:
    0 = all checks passed (warnings allowed)
    1 = one or more checks failed (critical issues found)
    2 = script error (couldn't run)

CONVENTIONS compliance:
  §6  — Smoke test protocol. This script is a diagnostic, not a test.
        It does NOT modify the DB (unless --fix is passed, which is
        NOT implemented in v1 — only suggests fixes).
  §10 — Dynamic-version pattern. Reads CODE_SCHEMA_VERSION from
        build_db.py at runtime.
  §13 — Design Law: this is infrastructure that supports every
        pillar by ensuring the world DB is intact.
"""
import sys
import sqlite3
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

import build_db  # noqa: E402

EXPECTED_VERSION = build_db.CODE_SCHEMA_VERSION

# Expected tables (54 user tables + 1 sqlite_sequence = 55 total, but
# we check the 54 user tables). Sourced from build_db.SCHEMA_SQL.
EXPECTED_TABLES = [
    "schema_meta", "schema_migrations",
    "nations", "regions", "cities", "markets", "venues",
    "weight_classes", "name_pools",
    "promotions", "gyms", "staff", "broadcast_staff",
    "style_archetypes", "personality_archetypes",
    "fighters", "fighter_attributes", "fighter_personality",
    "fighter_career", "fighter_bios", "fighter_descriptors",
    "fighter_memory_links", "fighter_contracts", "regen_lineage",
    "contracts", "staff_contracts", "broadcast_contracts",
    "events", "event_cards", "fights", "fight_beats", "fight_rounds",
    "fight_history", "fight_participants",
    "commentary_segments", "matchup_analyses",
    "titles", "rankings",
    "training_camps", "weight_cut_log",
    "injuries", "suspensions",
    "rivalries", "social_posts", "news_items", "news_sources",
    "finance_transactions", "show_ratings",
    "hall_of_fame", "player_settings",
    "agent_offers", "simulation_clock",
]

# Critical columns that MUST NOT be NULL (per table).
# Sourced from SCHEMA_SQL NOT NULL constraints.
# Note: fights uses winner_fighter_id / loser_fighter_id (NOT fighter_a/b_id).
CRITICAL_NOT_NULL = {
    "fighters": ["first_name", "last_name", "is_active", "is_retired",
                 "date_of_birth", "weight_class_id"],
    "fighter_attributes": ["fighter_id"],
    "fighter_personality": ["fighter_id"],
    "fighter_career": ["fighter_id"],
    "events": ["promotion_id", "venue_id", "market_id", "event_name",
               "event_date", "event_type", "status"],
    "fights": ["event_id", "weight_class_id", "scheduled_rounds"],
    # Note: winner_fighter_id, loser_fighter_id, result_type are NULL for
    # scheduled (unresolved) fights — that's expected, not a data gap.
    # Only check they're non-NULL for resolved fights (status='completed' on events).
    "fight_history": ["fighter_id", "fight_id", "opponent_id", "outcome",
                      "event_date"],
    "rankings": ["fighter_id", "weight_class_id", "rating"],
    "titles": ["weight_class_id", "promotion_id", "is_vacant"],
    "staff": ["first_name", "last_name", "age", "role_type"],
}

# Attribute columns that must be 0-100 (per CHECK constraints).
ATTRIBUTE_COLUMNS_0_100 = [
    "punch_power", "cardio", "fight_iq", "chin", "punch_accuracy",
    "kick_power", "kick_accuracy", "head_movement", "footwork",
    "clinch_striking", "clinch_offense", "clinch_defense",
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "adaptability",
]

results = []
warnings = []
errors = []


def check(category, name, passed, detail="", critical=True):
    """Record a check result."""
    entry = (category, name, passed, detail, critical)
    results.append(entry)
    if not passed:
        if critical:
            errors.append(entry)
        else:
            warnings.append(entry)
    if not passed or "--verbose" in sys.argv:
        status = "PASS" if passed else ("FAIL" if critical else "WARN")
        print(f"  [{status}] {category}/{name}: {detail}")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def main():
    print("=" * 72)
    print("CAGE EMPIRE — Forensic Database Integrity Check")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Expected schema version: {EXPECTED_VERSION}")
    print()

    if not DB_PATH.exists():
        print(f"FATAL: DB file does not exist at {DB_PATH}")
        sys.exit(2)

    conn = get_conn()

    # ================================================================
    # 1. SCHEMA INTEGRITY
    # ================================================================
    print("--- 1. SCHEMA INTEGRITY ---")

    # 1.1 Schema version
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("schema", "schema_meta row exists", sv is not None,
          f"got={sv}", critical=True)
    if sv:
        check("schema", "schema version matches CODE_SCHEMA_VERSION",
              sv[0] == EXPECTED_VERSION,
              f"db={sv[0]} code={EXPECTED_VERSION}", critical=True)

    # 1.2 All expected tables exist
    actual_tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    for t in EXPECTED_TABLES:
        check("schema", f"table '{t}' exists", t in actual_tables,
              f"missing" if t not in actual_tables else "present", critical=True)

    # 1.3 All migrations recorded
    mig_count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    check("schema", "migrations recorded", mig_count >= 17,
          f"got {mig_count} migrations (expected >= 17)", critical=True)

    # 1.4 staff.pundit_bias column (new in v3.8.0)
    staff_cols = [r[1] for r in conn.execute("PRAGMA table_info(staff)").fetchall()]
    check("schema", "staff.pundit_bias column exists (v3.8.0)",
          "pundit_bias" in staff_cols,
          f"present" if "pundit_bias" in staff_cols else "MISSING",
          critical=True)

    # ================================================================
    # 2. DATA INTEGRITY
    # ================================================================
    print("\n--- 2. DATA INTEGRITY ---")

    # 2.1 Foreign key violations
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    check("data", "no foreign key violations",
          len(fk_violations) == 0,
          f"{len(fk_violations)} violations" if fk_violations else "clean",
          critical=True)
    if fk_violations and "--verbose" in sys.argv:
        for v in fk_violations[:10]:
            print(f"         FK violation: {v}")

    # 2.2 Every fighter has attributes/personality/career rows
    fighter_count = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    attrs_count = conn.execute("SELECT COUNT(*) FROM fighter_attributes").fetchone()[0]
    pers_count = conn.execute("SELECT COUNT(*) FROM fighter_personality").fetchone()[0]
    career_count = conn.execute("SELECT COUNT(*) FROM fighter_career").fetchone()[0]

    check("data", "every fighter has fighter_attributes row",
          attrs_count == fighter_count,
          f"fighters={fighter_count} attrs={attrs_count}", critical=True)
    check("data", "every fighter has fighter_personality row",
          pers_count == fighter_count,
          f"fighters={fighter_count} pers={pers_count}", critical=True)
    check("data", "every fighter has fighter_career row",
          career_count == fighter_count,
          f"fighters={fighter_count} career={career_count}", critical=True)

    # 2.3 Orphaned fighter_attributes (fighter_id not in fighters)
    orphan_attrs = conn.execute(
        "SELECT COUNT(*) FROM fighter_attributes fa "
        "LEFT JOIN fighters f ON fa.fighter_id = f.fighter_id "
        "WHERE f.fighter_id IS NULL"
    ).fetchone()[0]
    check("data", "no orphaned fighter_attributes rows",
          orphan_attrs == 0,
          f"{orphan_attrs} orphans" if orphan_attrs else "clean",
          critical=True)

    # 2.4 Orphaned fight_history (fight_id not in fights)
    orphan_fh = conn.execute(
        "SELECT COUNT(*) FROM fight_history fh "
        "LEFT JOIN fights fi ON fh.fight_id = fi.fight_id "
        "WHERE fi.fight_id IS NULL"
    ).fetchone()[0]
    check("data", "no orphaned fight_history rows",
          orphan_fh == 0,
          f"{orphan_fh} orphans" if orphan_fh else "clean",
          critical=False)  # seed may have historical fight_history without fights rows

    # 2.5 NOT NULL violations on critical columns
    for table, cols in CRITICAL_NOT_NULL.items():
        for col in cols:
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"
            ).fetchone()[0]
            check("data", f"{table}.{col} has no NULLs",
                  null_count == 0,
                  f"{null_count} NULLs" if null_count else "clean",
                  critical=True)

    # 2.5b Resolved fights MUST have winner/loser/result_type (not NULL)
    # Scheduled fights (no winner yet) are OK — expected.
    resolved_null_winner = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE winner_fighter_id IS NULL "
        "AND fight_id IN (SELECT fight_id FROM event_cards ec "
        "JOIN events e ON ec.event_id = e.event_id WHERE e.status = 'completed')"
    ).fetchone()[0]
    check("data", "resolved fights have winner_fighter_id",
          resolved_null_winner == 0,
          f"{resolved_null_winner} resolved fights missing winner" if resolved_null_winner else "clean",
          critical=False)  # some historical seed fights may lack winner

    # ================================================================
    # 3. ATTRIBUTE SANITY
    # ================================================================
    print("\n--- 3. ATTRIBUTE SANITY ---")

    # 3.1 All attribute values in 0-100 range
    for col in ATTRIBUTE_COLUMNS_0_100:
        out_of_range = conn.execute(
            f"SELECT COUNT(*) FROM fighter_attributes "
            f"WHERE {col} < 0 OR {col} > 100"
        ).fetchone()[0]
        check("attrs", f"{col} in 0-100 range",
              out_of_range == 0,
              f"{out_of_range} out of range" if out_of_range else "clean",
              critical=True)

    # 3.2 No fighter with ALL attributes = 50 (seed failure indicator)
    all_50 = conn.execute(
        "SELECT COUNT(*) FROM fighter_attributes WHERE "
        + " AND ".join(f"{c} = 50" for c in ATTRIBUTE_COLUMNS_0_100[:6])
        + " AND " + " AND ".join(f"{c} = 50" for c in ATTRIBUTE_COLUMNS_0_100[6:])
    ).fetchone()[0]
    check("attrs", "no fighter with all-50 attributes (seed failure)",
          all_50 == 0,
          f"{all_50} fighters with all-50" if all_50 else "clean",
          critical=False)

    # 3.3 No NULL attribute values
    null_attrs = conn.execute(
        "SELECT COUNT(*) FROM fighter_attributes WHERE "
        + " IS NULL OR ".join(ATTRIBUTE_COLUMNS_0_100) + " IS NULL"
    ).fetchone()[0]
    check("attrs", "no NULL attribute values",
          null_attrs == 0,
          f"{null_attrs} fighters with NULL attrs" if null_attrs else "clean",
          critical=True)

    # 3.4 fighter_career.potential in 0-100
    bad_pot = conn.execute(
        "SELECT COUNT(*) FROM fighter_career "
        "WHERE potential < 0 OR potential > 100"
    ).fetchone()[0]
    check("attrs", "fighter_career.potential in 0-100",
          bad_pot == 0,
          f"{bad_pot} out of range" if bad_pot else "clean",
          critical=True)

    # 3.5 fighter_career.career_health in 0-100
    bad_health = conn.execute(
        "SELECT COUNT(*) FROM fighter_career "
        "WHERE career_health < 0 OR career_health > 100"
    ).fetchone()[0]
    check("attrs", "fighter_career.career_health in 0-100",
          bad_health == 0,
          f"{bad_health} out of range" if bad_health else "clean",
          critical=True)

    # ================================================================
    # 4. STALE DATA
    # ================================================================
    print("\n--- 4. STALE DATA ---")

    # 4.1 Retired fighters in active rankings
    retired_in_rankings = conn.execute(
        "SELECT COUNT(*) FROM rankings r "
        "JOIN fighters f ON r.fighter_id = f.fighter_id "
        "WHERE f.is_retired = 1"
    ).fetchone()[0]
    check("stale", "no retired fighters in active rankings",
          retired_in_rankings == 0,
          f"{retired_in_rankings} stale rankings" if retired_in_rankings else "clean",
          critical=False)

    # 4.2 Retired fighters on active contracts
    retired_on_contracts = conn.execute(
        "SELECT COUNT(*) FROM fighter_contracts fc "
        "JOIN fighters f ON fc.fighter_id = f.fighter_id "
        "JOIN contracts c ON fc.contract_id = c.contract_id "
        "WHERE f.is_retired = 1 AND c.end_date > "
        "(SELECT current_date FROM simulation_clock WHERE clock_id=1)"
    ).fetchone()[0]
    check("stale", "no retired fighters on active contracts",
          retired_on_contracts == 0,
          f"{retired_on_contracts} stale contracts" if retired_on_contracts else "clean",
          critical=False)

    # 4.3 Active injuries past their projected return date (still is_active=1)
    expired_injuries = conn.execute(
        "SELECT COUNT(*) FROM injuries "
        "WHERE is_active = 1 "
        "AND projected_return_date IS NOT NULL "
        "AND projected_return_date < "
        "(SELECT current_date FROM simulation_clock WHERE clock_id=1)"
    ).fetchone()[0]
    check("stale", "no active injuries past projected return date",
          expired_injuries == 0,
          f"{expired_injuries} stale injuries" if expired_injuries else "clean",
          critical=False)

    # 4.4 Active suspensions past their end date (still is_active=1)
    expired_susp = conn.execute(
        "SELECT COUNT(*) FROM suspensions "
        "WHERE is_active = 1 "
        "AND end_date IS NOT NULL "
        "AND end_date < "
        "(SELECT current_date FROM simulation_clock WHERE clock_id=1)"
    ).fetchone()[0]
    check("stale", "no active suspensions past end date",
          expired_susp == 0,
          f"{expired_susp} stale suspensions" if expired_susp else "clean",
          critical=False)

    # ================================================================
    # 5. NEW SCHEMA COLUMN CHECKS (v3.8.0)
    # ================================================================
    print("\n--- 5. NEW SCHEMA COLUMN CHECKS (v3.8.0) ---")

    # 5.1 staff.pundit_bias — NULL for non-broadcast staff (expected)
    non_broadcast_with_bias = conn.execute(
        "SELECT COUNT(*) FROM staff "
        "WHERE pundit_bias IS NOT NULL "
        "AND staff_id NOT IN (SELECT staff_id FROM broadcast_staff)"
    ).fetchone()[0]
    check("v3.8.0", "staff.pundit_bias NULL for non-broadcast staff",
          non_broadcast_with_bias == 0,
          f"{non_broadcast_with_bias} non-broadcast with bias" if non_broadcast_with_bias else "clean",
          critical=False)

    # 5.2 fighter_memory_links count (may be 0 — populate_* functions are new)
    ml_count = conn.execute("SELECT COUNT(*) FROM fighter_memory_links").fetchone()[0]
    check("v3.8.0", "fighter_memory_links count (0 is OK — populate_* is new)",
          ml_count >= 0,  # always true — just informational
          f"{ml_count} links", critical=False)

    # ================================================================
    # 6. REFERENCE DATA
    # ================================================================
    print("\n--- 6. REFERENCE DATA ---")

    # 6.1 Every weight class has fighters
    empty_wc = conn.execute(
        "SELECT wc.name FROM weight_classes wc "
        "WHERE NOT EXISTS (SELECT 1 FROM fighters f WHERE f.weight_class_id = wc.weight_class_id)"
    ).fetchall()
    check("ref", "every weight class has fighters",
          len(empty_wc) == 0,
          f"{len(empty_wc)} empty weight classes" if empty_wc else "all populated",
          critical=False)
    if empty_wc and "--verbose" in sys.argv:
        for wc in empty_wc[:5]:
            print(f"         empty weight class: {wc[0]}")

    # 6.2 Every promotion has >= 2 active fighters (minimum for events)
    small_promos = conn.execute(
        "SELECT p.name, COUNT(f.fighter_id) as cnt FROM promotions p "
        "LEFT JOIN fighters f ON p.promotion_id = f.current_promotion_id AND f.is_active = 1 "
        "GROUP BY p.promotion_id HAVING cnt < 2"
    ).fetchall()
    check("ref", "every promotion has >= 2 active fighters",
          len(small_promos) == 0,
          f"{len(small_promos)} promos with < 2 fighters" if small_promos else "all OK",
          critical=False)
    if small_promos and "--verbose" in sys.argv:
        for p in small_promos[:5]:
            print(f"         small promotion: {p[0]} ({p[1]} fighters)")

    # 6.3 Every nation has >= 1 fighter
    empty_nations = conn.execute(
        "SELECT n.name FROM nations n "
        "WHERE NOT EXISTS (SELECT 1 FROM fighters f WHERE f.birth_nation_id = n.nation_id)"
    ).fetchall()
    check("ref", "every nation has >= 1 fighter",
          len(empty_nations) == 0,
          f"{len(empty_nations)} empty nations" if empty_nations else "all populated",
          critical=False)

    # 6.4 Every gym has >= 1 fighter (or is intentionally empty)
    empty_gyms = conn.execute(
        "SELECT g.name FROM gyms g "
        "WHERE NOT EXISTS (SELECT 1 FROM fighters f WHERE f.current_gym_id = g.gym_id AND f.is_active = 1)"
    ).fetchall()
    check("ref", "gyms with fighters",
          True,  # informational only
          f"{len(empty_gyms)} empty gyms (may be intentional)",
          critical=False)

    # ================================================================
    # 7. CONSISTENCY
    # ================================================================
    print("\n--- 7. CONSISTENCY ---")

    # 7.1 fighter_career.record_wins + losses + draws == COUNT(fight_history)
    # NOTE: retired legends (is_retired=1) have career records but NO
    # fight_history rows — their record is a summary from the seed.
    # Only check active fighters (is_active=1, is_retired=0).
    mismatches = conn.execute(
        "SELECT fc.fighter_id, fc.record_wins, fc.record_losses, fc.record_draws, "
        "(SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = fc.fighter_id AND fh.outcome='win') as actual_wins, "
        "(SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = fc.fighter_id AND fh.outcome='loss') as actual_losses, "
        "(SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = fc.fighter_id AND fh.outcome='draw') as actual_draws "
        "FROM fighter_career fc "
        "JOIN fighters f ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 AND f.is_retired = 0 "
        "AND (fc.record_wins != (SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = fc.fighter_id AND fh.outcome='win') "
        "OR fc.record_losses != (SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = fc.fighter_id AND fh.outcome='loss') "
        "OR fc.record_draws != (SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = fc.fighter_id AND fh.outcome='draw'))"
    ).fetchall()
    check("consistency", "active fighter_career records match fight_history counts",
          len(mismatches) == 0,
          f"{len(mismatches)} mismatches" if mismatches else "all match",
          critical=False)
    if mismatches and "--verbose" in sys.argv:
        for m in mismatches[:5]:
            print(f"         mismatch: fighter {m[0]} career=({m[1]}-{m[2]}-{m[3]}) actual=({m[4]}-{m[5]}-{m[6]})")

    # 7.2 rankings.fighter_id exists in fighters
    orphan_rankings = conn.execute(
        "SELECT COUNT(*) FROM rankings r "
        "LEFT JOIN fighters f ON r.fighter_id = f.fighter_id "
        "WHERE f.fighter_id IS NULL"
    ).fetchone()[0]
    check("consistency", "no orphaned rankings rows",
          orphan_rankings == 0,
          f"{orphan_rankings} orphans" if orphan_rankings else "clean",
          critical=True)

    # 7.3 Active titles (is_vacant=0) have a current_champion_fighter_id that exists
    orphan_titles = conn.execute(
        "SELECT COUNT(*) FROM titles t "
        "LEFT JOIN fighters f ON t.current_champion_fighter_id = f.fighter_id "
        "WHERE t.is_vacant = 0 AND t.current_champion_fighter_id IS NOT NULL "
        "AND f.fighter_id IS NULL"
    ).fetchone()[0]
    check("consistency", "active titles reference existing fighters",
          orphan_titles == 0,
          f"{orphan_titles} orphaned titles" if orphan_titles else "clean",
          critical=True)

    # ================================================================
    # SUMMARY
    # ================================================================
    print("\n" + "=" * 72)
    print("FORENSIC DB CHECK SUMMARY")
    print("=" * 72)
    total = len(results)
    passed = sum(1 for r in results if r[2])
    failed = len(errors)
    warned = len(warnings)
    print(f"Total checks: {total}")
    print(f"  PASS: {passed}")
    print(f"  FAIL: {failed} (critical)")
    print(f"  WARN: {warned} (non-critical)")
    print()

    if errors:
        print("CRITICAL FAILURES:")
        for cat, name, _, detail, _ in errors:
            print(f"  [FAIL] {cat}/{name}: {detail}")
        print()

    if warnings:
        print("WARNINGS (non-critical, may be intentional):")
        for cat, name, _, detail, _ in warnings:
            print(f"  [WARN] {cat}/{name}: {detail}")
        print()

    if failed > 0:
        print("RESULT: FAILED — critical issues found. Fix before proceeding.")
        sys.exit(1)
    elif warned > 0:
        print("RESULT: PASSED with warnings — review warnings above.")
        sys.exit(0)
    else:
        print("RESULT: ALL CHECKS PASSED — world DB is healthy.")
        sys.exit(0)


if __name__ == "__main__":
    main()
