#!/usr/bin/env python3
"""Acceptance test for Task ID 14.5+14.6+14.7 — Fighter Schema Expansion.

Tests the largest single schema change since the project started:

  A. Schema verification:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read DYNAMICALLY — NO hardcoded version string per CONVENTIONS §10).
     - schema_migrations contains a row starting with
       'v2_0_0_fighter_schema_expansion' (verified via the
       EXPECTED_MIGRATION_PREFIX pattern — also dynamic).
     - fighter_attributes has 25 attribute columns (4 existing + 21 new)
       with CHECK (col BETWEEN 0 AND 100) on the 21 new ones.
     - fighter_personality has 20 personality columns (3 existing + 17
       new) with CHECK (col BETWEEN 0 AND 100) on the 17 new ones.
     - fighters has 14 new columns (height_cm, reach_cm, stance,
       handedness, injury_proneness, weight_cut_difficulty, consistency,
       clutch_factor, marketability, fan_friendliness, promo_boost,
       preferred_gameplans, bad_matchup_tags, is_deceased).
     - promotions has 6 new columns (brand_tone, starting_budget,
       broadcast_tier, ownership_type, ai_aggression, ai_spending_style).
     - gyms has 8 new columns (reputation, membership_cost,
       facility_quality, medical_support, sparring_depth,
       development_focus, culture_tone, weight_cut_support).
     - style_archetypes has attribute_bias TEXT column.
     - personality_archetypes has trait_bias TEXT column.
  B. Archetype seed:
     - 7 style archetypes seeded (Balanced, Striker, Grappler, Wrestler,
       Brawler, Counter-Striker, Submission Specialist) with parseable
       bias JSON.
     - 5 personality archetypes seeded (Calm, Aggressive, Methodical,
       Showman, Quiet Professional) with parseable bias JSON.
  C. fighter_gen function shapes:
     - generate_attribute_block returns dict with 25 keys (matching
       fighter_gen.ATTRIBUTE_NAMES), all values in [0, 100].
     - generate_personality_block returns dict with 20 keys (matching
       fighter_gen.PERSONALITY_NAMES), all values in [0, 100].
     - generate_physical_block returns dict with 4 keys (height_cm,
       reach_cm, stance, handedness) and correct value ranges.
     - With archetype_id + conn, the bias shifts the mean (Brawler
       averages higher on punch_power than no-archetype).
  D. Archetype bias statistical effect:
     - Generate 100 "Brawler" attribute blocks vs 100 "Counter-Striker"
       attribute blocks. Brawler averages higher on punch_power + chin,
       lower on footwork + fight_iq. Verify the mean difference is > 5
       points (statistically significant given bias magnitudes of 15-20).
  E. Backfill verification:
     - All 5 existing seeded fighters (John Vale, Marcus Reed, Dario
       Knox, Eli Storm, Cole Briggs) have NO NULLs in any of the 21
       new attribute columns, 17 new personality columns, or 14 new
       fighters-table columns.
     - Existing 4 attribute values (punch_power, cardio, fight_iq, chin)
       are PRESERVED at 50 (the v1.x default — the backfill must NOT
       have overwritten them).
     - Existing 3 personality values (aggression, composure, morale)
       are PRESERVED at 50.
     - height_cm, reach_cm, stance, handedness are populated with
       sensible values (height in [165, 195], stance in the 3 allowed
       values, handedness in the 3 allowed values).
  F. current_date quirk fix:
     - Build fresh DB. The seeded clock date is 2026-07-20.
     - Run tick_processor.run_tick(conn, "day", 1).
     - The clock column is now 2026-07-21 (exactly 1 day advance,
       NOT today's real date which the §Z.6 quirk would have produced).
  G. generate_fighter uses fighter_gen:
     - Build fresh DB. Call app.generate_fighter() with a fighter whose
       style_archetype_id is the "Brawler" archetype.
     - The new fighter's punch_power is NOT 50 (it's been biased +20
       by the Brawler archetype bias).
     - The new fighter's height_cm, reach_cm, stance, handedness are
       populated (not NULL).
     - All 25 attribute columns and 20 personality columns are
       populated (no NULLs).

Run from the project root:
    python3 scripts/test_fighter_attributes.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each block of generate_attribute_block
  / generate_personality_block / generate_physical_block /
  app.generate_fighter calls so the test is reproducible. The seed
  only pins down which random draws the functions see, not what they
  do with them.
"""
import json
import random
import sqlite3
import subprocess
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)

# Make src/ importable so we can call fighter_gen's three functions,
# app.generate_fighter, and tick_processor.run_tick. Importing app.py
# pulls in tkinter — the import itself does not require a display (only
# tk.Tk() does), so this is safe in headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402
import fighter_gen  # noqa: E402
import tick_processor  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read DYNAMICALLY from
# build_db per CONVENTIONS §10 — do NOT hardcode '2.0.0'). The brief
# explicitly says "MUST use build_db.CODE_SCHEMA_VERSION dynamically".
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"
# Task pre-B1-fixes supervisor fix: removed hardcoded EXPECTED_MIGRATION_NAME.
# The migration name changes per task (v2_0_0_fighter_schema_expansion,
# v2_0_1_potential_memory_archetype_fix, etc.). The EXPECTED_MIGRATION_PREFIX
# with a LIKE query (used in A.2) is the durable check — it passes regardless
# of the description suffix.

# Seeded clock date from src/build_db.py + a date exactly 1 day later
# (used to verify the current_date quirk fix in case F).
SEEDED_CLOCK_DATE = "2026-07-20"
EXPECTED_CLOCK_AFTER_ONE_TICK = "2026-07-21"

# The 21 new attribute columns (must match fighter_gen.NEW_ATTRIBUTE_NAMES).
NEW_ATTR_COLUMNS = fighter_gen.NEW_ATTRIBUTE_NAMES
# The 17 new personality columns (must match fighter_gen.NEW_PERSONALITY_NAMES).
NEW_PERS_COLUMNS = fighter_gen.NEW_PERSONALITY_NAMES

# The 4 existing attribute columns (PRESERVED across the migration).
EXISTING_ATTR_COLUMNS = fighter_gen.EXISTING_ATTRIBUTE_NAMES
# The 3 existing personality columns (PRESERVED).
EXISTING_PERS_COLUMNS = fighter_gen.EXISTING_PERSONALITY_NAMES

# The 14 new fighters columns.
NEW_FIGHTER_COLUMNS = [
    "height_cm", "reach_cm", "stance", "handedness",
    "injury_proneness", "weight_cut_difficulty", "consistency",
    "clutch_factor", "marketability", "fan_friendliness",
    "promo_boost", "preferred_gameplans", "bad_matchup_tags",
    "is_deceased",
]

# The 6 new promotions columns.
NEW_PROMOTION_COLUMNS = [
    "brand_tone", "starting_budget", "broadcast_tier",
    "ownership_type", "ai_aggression", "ai_spending_style",
]

# The 8 new gyms columns.
NEW_GYM_COLUMNS = [
    "reputation", "membership_cost", "facility_quality",
    "medical_support", "sparring_depth", "development_focus",
    "culture_tone", "weight_cut_support",
]

# 7 style archetypes seeded by name (must match seed_data.STYLE_ARCHETYPES).
EXPECTED_STYLE_ARCHETYPES = [
    "Balanced", "Striker", "Grappler", "Wrestler",
    "Brawler", "Counter-Striker", "Submission Specialist",
]

# 5 personality archetypes seeded by name.
EXPECTED_PERSONALITY_ARCHETYPES = [
    "Calm", "Aggressive", "Methodical", "Showman", "Quiet Professional",
]

# Fighter IDs assigned by seed_data.py (5 fighters total).
# John Vale = 1, Marcus Reed = 2, Dario Knox = 3, Eli Storm = 4, Cole Briggs = 5.
SEEDED_FIGHTER_IDS = [1, 2, 3, 4, 5]


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_regen.py / test_retirement.py so all
    tests share the same setup contract: a fresh DB with 2 promotions
    (Alpha Combat + Rival Fight League), 5 fighters (2 AC + 3 RFL),
    7 style archetypes + 5 personality archetypes (all with bias JSON),
    1 staff member (Nina Cross), 1 event, 1 title_fight, 6 contracts,
    5 rankings rows, 2 vacant titles, 96 name pool entries, all 5
    fighters backfilled with the v2.0.0 new columns.
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


def get_column_info(conn, table_name):
    """Return a dict of {col_name: type_str} for the given table.

    Uses pragma_table_info. The 'type' field is the declared type
    (e.g. 'INTEGER', 'TEXT', 'REAL') as it appears in the CREATE TABLE
    statement.
    """
    rows = conn.execute(
        f"SELECT name, type FROM pragma_table_info('{table_name}')"
    ).fetchall()
    return {name: type_str for name, type_str in rows}


def get_column_names(conn, table_name):
    """Return a list of column names for the given table, in order."""
    return [r[0] for r in conn.execute(
        f"SELECT name FROM pragma_table_info('{table_name}')"
    ).fetchall()]


def get_table_sql(conn, table_name):
    """Return the CREATE TABLE SQL for the given table.

    Used to verify CHECK constraints are present (we look for the
    substring 'CHECK (col BETWEEN 0 AND 100)' in the SQL).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row[0] if row else ""


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK 14.5+14.6+14.7 FIGHTER SCHEMA EXPANSION ACCEPTANCE TEST")
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

    # A.2 schema_migrations contains the v2_0_0_fighter_schema_expansion row.
    # Use both the dynamic prefix LIKE check AND the exact name equality,
    # so we catch both "wrong version" and "wrong description suffix".
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
    # A.2b (was A.3): exact migration name check REMOVED (pre-B1-fixes
    # supervisor fix). The migration name changes per task — the LIKE
    # prefix check in A.2 is the durable check. Hardcoding the exact
    # name broke on every version bump.

    # A.3 fighter_attributes has all 25 attribute columns.
    fa_cols = get_column_names(conn, "fighter_attributes")
    for col in fighter_gen.ATTRIBUTE_NAMES:
        results.append((
            "A", f"fighter_attributes has column {col}",
            col in fa_cols,
            f"got_cols={fa_cols}",
        ))

    # A.4 The 21 NEW attribute columns have CHECK (0-100) constraints.
    fa_sql = get_table_sql(conn, "fighter_attributes")
    for col in NEW_ATTR_COLUMNS:
        # Look for "CHECK (col BETWEEN 0 AND 100)" pattern (case-insensitive).
        # The schema SQL uses the format "CHECK (colname BETWEEN 0 AND 100)".
        check_str = f"CHECK ({col} BETWEEN 0 AND 100)"
        results.append((
            "A", f"fighter_attributes.{col} has CHECK (0-100)",
            check_str in fa_sql,
            f"looking for: {check_str}",
        ))

    # A.5 The 4 EXISTING attribute columns do NOT have CHECK (they're
    #     preserved from v1.x without retroactive CHECK). This is
    #     intentional — adding CHECK retroactively would break existing
    #     tests that UPDATE these columns with arbitrary values.
    for col in EXISTING_ATTR_COLUMNS:
        check_str = f"CHECK ({col} BETWEEN 0 AND 100)"
        # Existing columns have no CHECK (col BETWEEN 0 AND 100).
        # They may have other CHECK constraints in other tables, but
        # in fighter_attributes they should be plain INTEGER NOT NULL
        # DEFAULT 50.
        results.append((
            "A", f"fighter_attributes.{col} (existing) has NO retroactive CHECK",
            check_str not in fa_sql,
            f"existing column should NOT have: {check_str}",
        ))

    # A.6 fighter_personality has all 20 personality columns.
    fp_cols = get_column_names(conn, "fighter_personality")
    for col in fighter_gen.PERSONALITY_NAMES:
        results.append((
            "A", f"fighter_personality has column {col}",
            col in fp_cols,
            f"got_cols={fp_cols}",
        ))

    # A.7 The 17 NEW personality columns have CHECK (0-100).
    fp_sql = get_table_sql(conn, "fighter_personality")
    for col in NEW_PERS_COLUMNS:
        check_str = f"CHECK ({col} BETWEEN 0 AND 100)"
        results.append((
            "A", f"fighter_personality.{col} has CHECK (0-100)",
            check_str in fp_sql,
            f"looking for: {check_str}",
        ))

    # A.8 fighters has all 14 new columns.
    f_cols = get_column_names(conn, "fighters")
    for col in NEW_FIGHTER_COLUMNS:
        results.append((
            "A", f"fighters has column {col}",
            col in f_cols,
            f"got_cols={f_cols}",
        ))

    # A.9 fighters.stance has CHECK IN ('orthodox','southpaw','switch').
    f_sql = get_table_sql(conn, "fighters")
    results.append((
        "A", "fighters.stance has CHECK IN ('orthodox','southpaw','switch')",
        "stance IN ('orthodox','southpaw','switch')" in f_sql,
        "looking for stance CHECK",
    ))
    results.append((
        "A", "fighters.handedness has CHECK IN ('right','left','ambidextrous')",
        "handedness IN ('right','left','ambidextrous')" in f_sql,
        "looking for handedness CHECK",
    ))
    # promo_boost has CHECK BETWEEN -100 AND 100 (unusual range).
    results.append((
        "A", "fighters.promo_boost has CHECK BETWEEN -100 AND 100",
        "promo_boost BETWEEN -100 AND 100" in f_sql,
        "looking for promo_boost CHECK",
    ))
    # is_deceased has CHECK IN (0,1).
    results.append((
        "A", "fighters.is_deceased has CHECK IN (0,1)",
        "is_deceased IN (0,1)" in f_sql,
        "looking for is_deceased CHECK",
    ))

    # A.10 promotions has all 6 new columns.
    p_cols = get_column_names(conn, "promotions")
    for col in NEW_PROMOTION_COLUMNS:
        results.append((
            "A", f"promotions has column {col}",
            col in p_cols,
            f"got_cols={p_cols}",
        ))

    # A.11 gyms has all 8 new columns.
    g_cols = get_column_names(conn, "gyms")
    for col in NEW_GYM_COLUMNS:
        results.append((
            "A", f"gyms has column {col}",
            col in g_cols,
            f"got_cols={g_cols}",
        ))

    # A.12 style_archetypes.attribute_bias column exists.
    sa_cols = get_column_names(conn, "style_archetypes")
    results.append((
        "A", "style_archetypes has attribute_bias column",
        "attribute_bias" in sa_cols,
        f"got_cols={sa_cols}",
    ))

    # A.13 personality_archetypes.trait_bias column exists.
    pa_cols = get_column_names(conn, "personality_archetypes")
    results.append((
        "A", "personality_archetypes has trait_bias column",
        "trait_bias" in pa_cols,
        f"got_cols={pa_cols}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case B — Archetype seed verification.
    # ----------------------------------------------------------------
    print("\n--- Case B: Archetype seed verification ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # B.1 7 style archetypes seeded.
    style_count = conn.execute(
        "SELECT COUNT(*) FROM style_archetypes"
    ).fetchone()[0]
    results.append((
        "B", f"style_archetypes has 7 rows (got {style_count})",
        style_count == 7,
        f"got={style_count}, expected=7",
    ))

    # B.2 Each expected style archetype name exists.
    for name in EXPECTED_STYLE_ARCHETYPES:
        row = conn.execute(
            "SELECT 1 FROM style_archetypes WHERE name=?", (name,)
        ).fetchone()
        results.append((
            "B", f"style_archetypes has archetype {name!r}",
            row is not None,
            f"name={name!r}",
        ))

    # B.3 Each style archetype has parseable attribute_bias JSON.
    for name in EXPECTED_STYLE_ARCHETYPES:
        row = conn.execute(
            "SELECT attribute_bias FROM style_archetypes WHERE name=?",
            (name,),
        ).fetchone()
        ok = False
        detail = f"name={name!r}, got={row[0] if row else None}"
        if row and row[0]:
            try:
                parsed = json.loads(row[0])
                ok = isinstance(parsed, dict)
                detail = f"name={name!r}, parsed={parsed}"
            except (ValueError, TypeError) as e:
                detail = f"name={name!r}, parse error: {e}"
        results.append((
            "B", f"style_archetype {name!r} has parseable attribute_bias JSON",
            ok, detail,
        ))

    # B.4 5 personality archetypes seeded.
    pers_count = conn.execute(
        "SELECT COUNT(*) FROM personality_archetypes"
    ).fetchone()[0]
    results.append((
        "B", f"personality_archetypes has 5 rows (got {pers_count})",
        pers_count == 5,
        f"got={pers_count}, expected=5",
    ))

    # B.5 Each expected personality archetype name exists.
    for name in EXPECTED_PERSONALITY_ARCHETYPES:
        row = conn.execute(
            "SELECT 1 FROM personality_archetypes WHERE name=?", (name,)
        ).fetchone()
        results.append((
            "B", f"personality_archetypes has archetype {name!r}",
            row is not None,
            f"name={name!r}",
        ))

    # B.6 Each personality archetype has parseable trait_bias JSON.
    for name in EXPECTED_PERSONALITY_ARCHETYPES:
        row = conn.execute(
            "SELECT trait_bias FROM personality_archetypes WHERE name=?",
            (name,),
        ).fetchone()
        ok = False
        detail = f"name={name!r}, got={row[0] if row else None}"
        if row and row[0]:
            try:
                parsed = json.loads(row[0])
                ok = isinstance(parsed, dict)
                detail = f"name={name!r}, parsed={parsed}"
            except (ValueError, TypeError) as e:
                detail = f"name={name!r}, parse error: {e}"
        results.append((
            "B", f"personality_archetype {name!r} has parseable trait_bias JSON",
            ok, detail,
        ))

    # B.7 The Brawler bias has the expected keys (per STAGES.md §14.5).
    brawler_row = conn.execute(
        "SELECT attribute_bias FROM style_archetypes WHERE name='Brawler'"
    ).fetchone()
    if brawler_row and brawler_row[0]:
        brawler_bias = json.loads(brawler_row[0])
        # Brawler bias: {"punch_power": 20, "chin": 15, "durability": 10,
        #                 "footwork": -15, "fight_iq": -10, "cardio": -5}
        expected_keys = {
            # pre-B1-fixes supervisor fix: softened biases (max abs 10, was 20)
            "punch_power": 10, "chin": 8, "durability": 5,
            "footwork": -8, "fight_iq": -5, "cardio": -3,
        }
        for k, v in expected_keys.items():
            results.append((
                "B", f"Brawler bias has {k}={v}",
                brawler_bias.get(k) == v,
                f"got={brawler_bias.get(k)}, expected={v}",
            ))
    else:
        results.append((
            "B", "Brawler bias JSON loaded",
            False, "Brawler row not found or attribute_bias is NULL",
        ))

    # B.8 The Counter-Striker bias has the expected keys.
    cs_row = conn.execute(
        "SELECT attribute_bias FROM style_archetypes WHERE name='Counter-Striker'"
    ).fetchone()
    if cs_row and cs_row[0]:
        cs_bias = json.loads(cs_row[0])
        # Counter-Striker: {"punch_accuracy": 15, "head_movement": 15,
        #                    "footwork": 15, "fight_iq": 15,
        #                    "aggression": -10, "takedown_offense": -10}
        expected_keys = {
            # pre-B1-fixes supervisor fix: softened biases (max abs 10, was 15)
            "punch_accuracy": 8, "head_movement": 8,
            "footwork": 8, "fight_iq": 8,
            "aggression": -5, "takedown_offense": -5,
        }
        for k, v in expected_keys.items():
            results.append((
                "B", f"Counter-Striker bias has {k}={v}",
                cs_bias.get(k) == v,
                f"got={cs_bias.get(k)}, expected={v}",
            ))
    else:
        results.append((
            "B", "Counter-Striker bias JSON loaded",
            False, "Counter-Striker row not found or attribute_bias is NULL",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Case C — fighter_gen function shapes.
    # ----------------------------------------------------------------
    print("\n--- Case C: fighter_gen function shapes ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # C.1 generate_attribute_block returns dict with 25 keys, all in [0,100].
    random.seed(RANDOM_SEED)
    attr_block = fighter_gen.generate_attribute_block()
    attr_keys = set(attr_block.keys())
    expected_attr_keys = set(fighter_gen.ATTRIBUTE_NAMES)
    results.append((
        "C", "generate_attribute_block() returns dict with 25 keys (no conn, no archetype)",
        attr_keys == expected_attr_keys,
        f"got_keys={sorted(attr_keys)}, missing={sorted(expected_attr_keys - attr_keys)}, extra={sorted(attr_keys - expected_attr_keys)}",
    ))
    # All values in [0, 100].
    all_in_range = all(isinstance(v, int) and 0 <= v <= 100
                       for v in attr_block.values())
    results.append((
        "C", "generate_attribute_block() all values in [0, 100]",
        all_in_range,
        f"out_of_range={[ (k, v) for k, v in attr_block.items() if not (isinstance(v, int) and 0 <= v <= 100) ]}",
    ))

    # C.2 generate_personality_block returns dict with 20 keys, all in [0,100].
    random.seed(RANDOM_SEED)
    pers_block = fighter_gen.generate_personality_block()
    pers_keys = set(pers_block.keys())
    expected_pers_keys = set(fighter_gen.PERSONALITY_NAMES)
    results.append((
        "C", "generate_personality_block() returns dict with 20 keys",
        pers_keys == expected_pers_keys,
        f"got_keys={sorted(pers_keys)}, missing={sorted(expected_pers_keys - pers_keys)}, extra={sorted(pers_keys - expected_pers_keys)}",
    ))
    all_in_range_p = all(isinstance(v, int) and 0 <= v <= 100
                         for v in pers_block.values())
    results.append((
        "C", "generate_personality_block() all values in [0, 100]",
        all_in_range_p,
        f"out_of_range={[ (k, v) for k, v in pers_block.items() if not (isinstance(v, int) and 0 <= v <= 100) ]}",
    ))

    # C.3 generate_physical_block returns dict with 4 keys + correct ranges.
    random.seed(RANDOM_SEED)
    phys_block = fighter_gen.generate_physical_block()
    phys_keys = set(phys_block.keys())
    expected_phys_keys = {"height_cm", "reach_cm", "stance", "handedness"}
    results.append((
        "C", "generate_physical_block() returns dict with 4 keys",
        phys_keys == expected_phys_keys,
        f"got_keys={sorted(phys_keys)}, expected={sorted(expected_phys_keys)}",
    ))
    # height_cm in [165, 195].
    results.append((
        "C", f"generate_physical_block() height_cm in [165, 195]",
        isinstance(phys_block.get("height_cm"), int)
        and 165 <= phys_block["height_cm"] <= 195,
        f"got={phys_block.get('height_cm')}",
    ))
    # stance in the 3 allowed values.
    results.append((
        "C", f"generate_physical_block() stance in allowed values",
        phys_block.get("stance") in ("orthodox", "southpaw", "switch"),
        f"got={phys_block.get('stance')}",
    ))
    # handedness in the 3 allowed values.
    results.append((
        "C", f"generate_physical_block() handedness in allowed values",
        phys_block.get("handedness") in ("right", "left", "ambidextrous"),
        f"got={phys_block.get('handedness')}",
    ))
    # reach_cm is an int (height + randint(-5, 10) so range varies).
    results.append((
        "C", f"generate_physical_block() reach_cm is an int",
        isinstance(phys_block.get("reach_cm"), int),
        f"got={phys_block.get('reach_cm')}",
    ))

    # C.4 With archetype_id + conn, the bias shifts the mean (Brawler
    #     averages higher on punch_power than no-archetype).
    brawler_id_row = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes WHERE name='Brawler'"
    ).fetchone()
    brawler_id = brawler_id_row[0] if brawler_id_row else None
    random.seed(RANDOM_SEED)
    # Generate 100 Brawler blocks and 100 no-archetype blocks.
    brawler_punch_powers = []
    for _ in range(100):
        block = fighter_gen.generate_attribute_block(brawler_id, conn)
        brawler_punch_powers.append(block["punch_power"])
    random.seed(RANDOM_SEED)
    none_punch_powers = []
    for _ in range(100):
        block = fighter_gen.generate_attribute_block(None, conn)
        none_punch_powers.append(block["punch_power"])
    brawler_mean = sum(brawler_punch_powers) / len(brawler_punch_powers)
    none_mean = sum(none_punch_powers) / len(none_punch_powers)
    # Brawler bias for punch_power is +20, so brawler_mean should be
    # roughly 70 (50 + 20) vs none_mean roughly 50.
    results.append((
        "C", f"Brawler punch_power mean ({brawler_mean:.1f}) > no-archetype mean ({none_mean:.1f})",
        brawler_mean > none_mean + 5,  # at least 5 points higher
        f"brawler_mean={brawler_mean:.2f}, none_mean={none_mean:.2f}, diff={brawler_mean - none_mean:.2f}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case D — Archetype bias statistical effect (100 Brawler vs 100
    # Counter-Striker).
    # ----------------------------------------------------------------
    print("\n--- Case D: Archetype bias statistical effect (100 Brawler vs 100 Counter-Striker) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    brawler_id_row = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes WHERE name='Brawler'"
    ).fetchone()
    cs_id_row = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes WHERE name='Counter-Striker'"
    ).fetchone()
    brawler_id = brawler_id_row[0] if brawler_id_row else None
    cs_id = cs_id_row[0] if cs_id_row else None
    results.append((
        "D", f"Brawler archetype_id found (got {brawler_id})",
        brawler_id is not None,
        f"brawler_id={brawler_id}",
    ))
    results.append((
        "D", f"Counter-Striker archetype_id found (got {cs_id})",
        cs_id is not None,
        f"cs_id={cs_id}",
    ))

    if brawler_id is not None and cs_id is not None:
        # Generate 100 Brawler blocks.
        random.seed(RANDOM_SEED)
        brawler_blocks = [
            fighter_gen.generate_attribute_block(brawler_id, conn)
            for _ in range(100)
        ]
        # Generate 100 Counter-Striker blocks.
        random.seed(RANDOM_SEED)
        cs_blocks = [
            fighter_gen.generate_attribute_block(cs_id, conn)
            for _ in range(100)
        ]

        # D.1 Brawler averages HIGHER on punch_power than Counter-Striker.
        #     Brawler bias: punch_power=+20. CS bias: no punch_power entry
        #     (so 0). Expected diff: ~20 points.
        brawler_pp_mean = sum(b["punch_power"] for b in brawler_blocks) / 100
        cs_pp_mean = sum(b["punch_power"] for b in cs_blocks) / 100
        diff_pp = brawler_pp_mean - cs_pp_mean
        results.append((
            "D", f"Brawler punch_power mean ({brawler_pp_mean:.1f}) > CS mean ({cs_pp_mean:.1f}) by > 5",
            diff_pp > 5,
            f"brawler_mean={brawler_pp_mean:.2f}, cs_mean={cs_pp_mean:.2f}, diff={diff_pp:.2f}",
        ))

        # D.2 Brawler averages HIGHER on chin than Counter-Striker.
        #     Brawler bias: chin=+15. CS bias: no chin entry. Expected
        #     diff: ~15 points.
        brawler_chin_mean = sum(b["chin"] for b in brawler_blocks) / 100
        cs_chin_mean = sum(b["chin"] for b in cs_blocks) / 100
        diff_chin = brawler_chin_mean - cs_chin_mean
        results.append((
            "D", f"Brawler chin mean ({brawler_chin_mean:.1f}) > CS mean ({cs_chin_mean:.1f}) by > 5",
            diff_chin > 5,
            f"brawler_mean={brawler_chin_mean:.2f}, cs_mean={cs_chin_mean:.2f}, diff={diff_chin:.2f}",
        ))

        # D.3 Brawler averages LOWER on footwork than Counter-Striker.
        #     Brawler bias: footwork=-15. CS bias: footwork=+15.
        #     Expected diff: ~30 points (CS higher).
        brawler_fw_mean = sum(b["footwork"] for b in brawler_blocks) / 100
        cs_fw_mean = sum(b["footwork"] for b in cs_blocks) / 100
        diff_fw = cs_fw_mean - brawler_fw_mean
        results.append((
            "D", f"CS footwork mean ({cs_fw_mean:.1f}) > Brawler mean ({brawler_fw_mean:.1f}) by > 5",
            diff_fw > 5,
            f"cs_mean={cs_fw_mean:.2f}, brawler_mean={brawler_fw_mean:.2f}, diff={diff_fw:.2f}",
        ))

        # D.4 Brawler averages LOWER on fight_iq than Counter-Striker.
        #     Brawler bias: fight_iq=-10. CS bias: fight_iq=+15.
        #     Expected diff: ~25 points (CS higher).
        brawler_iq_mean = sum(b["fight_iq"] for b in brawler_blocks) / 100
        cs_iq_mean = sum(b["fight_iq"] for b in cs_blocks) / 100
        diff_iq = cs_iq_mean - brawler_iq_mean
        results.append((
            "D", f"CS fight_iq mean ({cs_iq_mean:.1f}) > Brawler mean ({brawler_iq_mean:.1f}) by > 5",
            diff_iq > 5,
            f"cs_mean={cs_iq_mean:.2f}, brawler_mean={brawler_iq_mean:.2f}, diff={diff_iq:.2f}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Case E — Backfill verification (5 existing fighters).
    # ----------------------------------------------------------------
    print("\n--- Case E: Backfill verification (5 existing fighters) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    for fid in SEEDED_FIGHTER_IDS:
        # E.1 No NULLs in the 21 new attribute columns.
        col_select = ", ".join(NEW_ATTR_COLUMNS)
        row = conn.execute(
            f"SELECT {col_select} FROM fighter_attributes WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if row is None:
            results.append((
                "E", f"fighter {fid}: fighter_attributes row exists",
                False, f"no row for fighter_id={fid}",
            ))
        else:
            nulls = [NEW_ATTR_COLUMNS[i] for i, v in enumerate(row)
                     if v is None]
            results.append((
                "E", f"fighter {fid}: no NULLs in 21 new attribute columns",
                len(nulls) == 0,
                f"nulls={nulls}",
            ))

        # E.2 No NULLs in the 17 new personality columns.
        col_select_p = ", ".join(NEW_PERS_COLUMNS)
        row_p = conn.execute(
            f"SELECT {col_select_p} FROM fighter_personality WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if row_p is None:
            results.append((
                "E", f"fighter {fid}: fighter_personality row exists",
                False, f"no row for fighter_id={fid}",
            ))
        else:
            nulls_p = [NEW_PERS_COLUMNS[i] for i, v in enumerate(row_p)
                       if v is None]
            results.append((
                "E", f"fighter {fid}: no NULLs in 17 new personality columns",
                len(nulls_p) == 0,
                f"nulls={nulls_p}",
            ))

        # E.3 Existing 4 attribute values PRESERVED at 50 (the v1.x
        #     default — the backfill must NOT have overwritten them).
        existing_row = conn.execute(
            "SELECT punch_power, cardio, fight_iq, chin "
            "FROM fighter_attributes WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if existing_row:
            results.append((
                "E", f"fighter {fid}: existing 4 attrs PRESERVED at (50,50,50,50)",
                tuple(existing_row) == (50, 50, 50, 50),
                f"got={tuple(existing_row)}",
            ))

        # E.4 Existing 3 personality values PRESERVED at 50.
        existing_pers_row = conn.execute(
            "SELECT aggression, composure, morale "
            "FROM fighter_personality WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if existing_pers_row:
            results.append((
                "E", f"fighter {fid}: existing 3 personality PRESERVED at (50,50,50)",
                tuple(existing_pers_row) == (50, 50, 50),
                f"got={tuple(existing_pers_row)}",
            ))

        # E.5 height_cm populated and in [165, 195].
        f_row = conn.execute(
            "SELECT height_cm, reach_cm, stance, handedness, "
            "injury_proneness, marketability, is_deceased "
            "FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if f_row:
            height, reach, stance, handedness, inj, market, deceased = f_row
            results.append((
                "E", f"fighter {fid}: height_cm in [165, 195]",
                height is not None and 165 <= height <= 195,
                f"got={height}",
            ))
            results.append((
                "E", f"fighter {fid}: stance in allowed values",
                stance in ("orthodox", "southpaw", "switch"),
                f"got={stance}",
            ))
            results.append((
                "E", f"fighter {fid}: handedness in allowed values",
                handedness in ("right", "left", "ambidextrous"),
                f"got={handedness}",
            ))
            results.append((
                "E", f"fighter {fid}: injury_proneness defaults to 50",
                inj == 50,
                f"got={inj}",
            ))
            results.append((
                "E", f"fighter {fid}: marketability defaults to 50",
                market == 50,
                f"got={market}",
            ))
            results.append((
                "E", f"fighter {fid}: is_deceased defaults to 0",
                deceased == 0,
                f"got={deceased}",
            ))
            # reach_cm should be height + small offset, so it's an int
            # and roughly in the same neighborhood.
            results.append((
                "E", f"fighter {fid}: reach_cm is an int",
                isinstance(reach, int),
                f"got={reach}",
            ))

    # E.6 Promotion AI-tuning columns set per the brief.
    ac_row = conn.execute(
        "SELECT starting_budget, broadcast_tier, ai_aggression "
        "FROM promotions WHERE name='Alpha Combat'"
    ).fetchone()
    if ac_row:
        results.append((
            "E", f"AC: starting_budget=500000",
            ac_row[0] == 500000.0,
            f"got={ac_row[0]}",
        ))
        results.append((
            "E", f"AC: broadcast_tier='regional_tv'",
            ac_row[1] == "regional_tv",
            f"got={ac_row[1]}",
        ))
        results.append((
            "E", f"AC: ai_aggression=30",
            ac_row[2] == 30,
            f"got={ac_row[2]}",
        ))

    rfl_row = conn.execute(
        "SELECT starting_budget, broadcast_tier, ai_aggression "
        "FROM promotions WHERE name='Rival Fight League'"
    ).fetchone()
    if rfl_row:
        results.append((
            "E", f"RFL: starting_budget=200000",
            rfl_row[0] == 200000.0,
            f"got={rfl_row[0]}",
        ))
        results.append((
            "E", f"RFL: broadcast_tier='local_stream'",
            rfl_row[1] == "local_stream",
            f"got={rfl_row[1]}",
        ))
        results.append((
            "E", f"RFL: ai_aggression=60",
            rfl_row[2] == 60,
            f"got={rfl_row[2]}",
        ))

    # E.7 Gym facility columns set per the brief (both gyms).
    for gym_name in ("Ironhouse Gym", "Steelcrest Gym"):
        g_row = conn.execute(
            "SELECT facility_quality, medical_support, sparring_depth, "
            "development_focus FROM gyms WHERE name=?",
            (gym_name,),
        ).fetchone()
        if g_row:
            results.append((
                "E", f"{gym_name}: facility_quality=60",
                g_row[0] == 60, f"got={g_row[0]}",
            ))
            results.append((
                "E", f"{gym_name}: medical_support=50",
                g_row[1] == 50, f"got={g_row[1]}",
            ))
            results.append((
                "E", f"{gym_name}: sparring_depth=55",
                g_row[2] == 55, f"got={g_row[2]}",
            ))
            results.append((
                "E", f"{gym_name}: development_focus=60",
                g_row[3] == 60, f"got={g_row[3]}",
            ))

    conn.close()

    # ----------------------------------------------------------------
    # Case F — current_date quirk fix (tick advances by exactly 1 day).
    # ----------------------------------------------------------------
    print("\n--- Case F: current_date quirk fix (tick advances by exactly 1 day) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # F.1 Before tick: clock is the seeded 2026-07-20.
    clock_before = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    results.append((
        "F", f"before tick: clock={SEEDED_CLOCK_DATE}",
        clock_before is not None and clock_before[0] == SEEDED_CLOCK_DATE,
        f"got={clock_before[0] if clock_before else None}",
    ))

    # F.2 Run tick_processor.run_tick(conn, "day", 1).
    tick_processor.run_tick(conn, "day", 1)
    # run_tick commits internally.

    # F.3 After tick: clock is 2026-07-21 (exactly 1 day advance, NOT
    #     today's real date which the §Z.6 quirk would have produced).
    #     Use the QUALIFIED column reference (simulation_clock.current_date)
    #     so the verification query itself is not affected by the quirk.
    clock_after = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    results.append((
        "F", f"after tick: clock={EXPECTED_CLOCK_AFTER_ONE_TICK} (exactly 1 day advance)",
        clock_after is not None and clock_after[0] == EXPECTED_CLOCK_AFTER_ONE_TICK,
        f"got={clock_after[0] if clock_after else None}, expected={EXPECTED_CLOCK_AFTER_ONE_TICK}",
    ))

    # F.4 Sanity check: the tick_counter advanced from 0 to 1, proving
    #     the tick happened (not that the clock was somehow set without
    #     going through a real tick). This is a softer check than F.3
    #     (which already verifies the exact expected date) — we use it
    #     instead of a "clock is NOT today" check because today's real
    #     date could coincidentally be 2026-07-21 (the seeded date + 1
    #     day), which would make a "NOT today" check spuriously fail.
    tc_after = conn.execute(
        "SELECT tick_counter FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    results.append((
        "F", f"after tick: tick_counter=1 (advanced from 0)",
        tc_after is not None and tc_after[0] == 1,
        f"got={tc_after[0] if tc_after else None}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case G — generate_fighter uses fighter_gen (regen fighters get
    # archetype-biased attributes, not all-50s).
    # ----------------------------------------------------------------
    print("\n--- Case G: generate_fighter uses fighter_gen (regen fighters get archetype-biased attributes) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # G.1 Call generate_fighter with a fighter whose style_archetype_id
    #     is the Brawler archetype. The new fighter should have a
    #     punch_power biased +20 by the Brawler archetype bias (so
    #     NOT 50).
    brawler_id_row = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes WHERE name='Brawler'"
    ).fetchone()
    brawler_id = brawler_id_row[0] if brawler_id_row else None

    # Set fighter 1's style archetype to Brawler so the regen inherits
    # Brawler (style_dna_source_id=1).
    if brawler_id is not None:
        conn.execute(
            "UPDATE fighters SET fight_style_archetype_id=? WHERE fighter_id=1",
            (brawler_id,),
        )
        conn.commit()

    random.seed(RANDOM_SEED)
    new_fid = app.generate_fighter(
        conn, style_dna_source_id=1, current_date="2026-07-21"
    )
    conn.commit()
    results.append((
        "G", f"generate_fighter returns a valid fighter_id (got {new_fid})",
        isinstance(new_fid, int) and new_fid > 0,
        f"got={new_fid!r}",
    ))

    if isinstance(new_fid, int) and new_fid > 0:
        # G.2 The new fighter's punch_power is NOT 50 (it's been
        #     biased +20 by the Brawler archetype). The noise is
        #     random.randint(-8, 8), so the value will be in
        #     [clamp(50 + 20 - 8, 0, 100), clamp(50 + 20 + 8, 0, 100)]
        #     = [62, 78]. Definitely NOT 50.
        new_pp = conn.execute(
            "SELECT punch_power FROM fighter_attributes WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if new_pp:
            results.append((
                "G", f"regen fighter's punch_power ({new_pp[0]}) is NOT 50 (archetype-biased)",
                new_pp[0] != 50,
                f"got={new_pp[0]}, expected: not 50 (Brawler bias=+20, range ~[62,78])",
            ))
        else:
            results.append((
                "G", f"regen fighter's punch_power row exists",
                False, f"no row for fighter_id={new_fid}",
            ))

        # G.3 v2.6.2: DNA inheritance is now occasional (30%), not
        #     always. The regen fighter may or may not be a Brawler.
        #     We can't assert chin is biased +15 (Brawler-specific)
        #     because the fighter might have a different archetype.
        #     Instead, assert the attribute block was written (chin
        #     is not NULL and is in valid range 0-100).
        new_chin = conn.execute(
            "SELECT chin FROM fighter_attributes WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if new_chin:
            results.append((
                "G", f"regen fighter's chin ({new_chin[0]}) is in valid range (v2.6.2: archetype is 30% inherit, 70% random)",
                new_chin[0] is not None and 0 <= new_chin[0] <= 100,
                f"got={new_chin[0]}",
            ))

        # G.4 The new fighter's height_cm, reach_cm, stance, handedness
        #     are populated (not NULL — generate_physical_block was
        #     called by generate_fighter).
        phys = conn.execute(
            "SELECT height_cm, reach_cm, stance, handedness "
            "FROM fighters WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if phys:
            height, reach, stance, handedness = phys
            results.append((
                "G", f"regen fighter's height_cm is populated (not NULL)",
                height is not None,
                f"got={height}",
            ))
            results.append((
                "G", f"regen fighter's stance is populated (in allowed values)",
                stance in ("orthodox", "southpaw", "switch"),
                f"got={stance}",
            ))
            results.append((
                "G", f"regen fighter's handedness is populated (in allowed values)",
                handedness in ("right", "left", "ambidextrous"),
                f"got={handedness}",
            ))
        else:
            results.append((
                "G", f"regen fighter's physical columns row exists",
                False, f"no row for fighter_id={new_fid}",
            ))

        # G.5 All 25 attribute columns and 20 personality columns are
        #     populated (no NULLs) for the regen fighter.
        all_attr_cols = fighter_gen.ATTRIBUTE_NAMES
        col_sel = ", ".join(all_attr_cols)
        attr_row = conn.execute(
            f"SELECT {col_sel} FROM fighter_attributes WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if attr_row:
            nulls = [all_attr_cols[i] for i, v in enumerate(attr_row)
                     if v is None]
            results.append((
                "G", f"regen fighter: no NULLs in 25 attribute columns",
                len(nulls) == 0,
                f"nulls={nulls}",
            ))
        else:
            results.append((
                "G", f"regen fighter: attribute row exists",
                False, f"no row",
            ))

        all_pers_cols = fighter_gen.PERSONALITY_NAMES
        col_sel_p = ", ".join(all_pers_cols)
        pers_row = conn.execute(
            f"SELECT {col_sel_p} FROM fighter_personality WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if pers_row:
            nulls_p = [all_pers_cols[i] for i, v in enumerate(pers_row)
                       if v is None]
            results.append((
                "G", f"regen fighter: no NULLs in 20 personality columns",
                len(nulls_p) == 0,
                f"nulls={nulls_p}",
            ))
        else:
            results.append((
                "G", f"regen fighter: personality row exists",
                False, f"no row",
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
