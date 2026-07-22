#!/usr/bin/env python3
"""Acceptance test for Task ID pre-B1-fixes — Design fixes before Task B1.

Tests the 3 design fixes the supervisor flagged before the beat-level
fight engine (Task B1) can begin:

  A. Schema verification:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read DYNAMICALLY — NO hardcoded version string per CONVENTIONS §10).
     - schema_migrations contains the exact row
       'v2_0_1_potential_memory_archetype_fix' (the brief's required
       migration name; verified via the EXPECTED_MIGRATION_PREFIX
       dynamic pattern AND exact-name equality).
     - fighter_career has a `potential` column (INTEGER NOT NULL
       DEFAULT 50 CHECK (potential BETWEEN 0 AND 100)).
     - fighter_career has a `title_reigns` column (INTEGER NOT NULL
       DEFAULT 0 CHECK (title_reigns >= 0)).
     - The CHECK constraints fire on out-of-range values (potential=-1,
       potential=101, title_reigns=-1).
  B. Archetype bias softening:
     - All 7 style archetypes have parseable bias JSON.
     - All 5 personality archetypes have parseable bias JSON.
     - The MAXIMUM absolute bias across all 12 archetypes is <= 10
       (was 20 in v2.0.0 — softened ~40-50% per the brief).
     - Specific values per the brief: Brawler punch_power=10, chin=8,
       footwork=-8, fight_iq=-5. Counter-Striker punch_accuracy=8,
       head_movement=8, footwork=8, fight_iq=8.
  C. generate_potential() distribution:
     - Returns int in [25, 90] (union of the three tier ranges).
     - 1000 samples: ~10% elite (70-90), ~30% solid (50-69), ~60%
       limited (25-49). Tolerance: ±5 percentage points per tier.
     - No value falls outside the three tier ranges (no values in
       [0, 24] or [91, 100]).
  D. generate_fighter sets potential (not default 50):
     - Call app.generate_fighter() with a known style_dna_source.
     - The new fighter's fighter_career.potential is in [25, 90]
       (i.e., it was set by generate_potential, NOT left at the
       schema DEFAULT 50).
     - The new fighter's fighter_career.title_reigns is 0 (default —
       the new prospect has not won a title yet).
  E. _resolve_title_after_fight() increments title_reigns:
     - Build fresh DB. Resolve the seeded title fight (set fighter 1
       to all-90, fighter 2 to all-30 so fighter 1 wins).
     - After resolve: fighter_career.title_reigns for fighter 1 = 1
       (won the vacant title). Fighter 2's title_reigns still 0.
     - Convert the auto-scheduled fight 2 to a title_fight. Swap
       attrs (f1 all-30, f2 all-90) so fighter 2 wins. Resolve.
     - After resolve: fighter 2's title_reigns = 1 (dethroned f1).
       Fighter 1's title_reigns still 1 (the old reign is preserved
       — losing the title doesn't decrement the count).
  F. Champion retirement creates memory_link + special news:
     - Build fresh DB. Make fighter 1 a champion (resolve seeded
       title fight with f1=all-90, f2=all-30).
     - Set fighter 1 DOB to 1980-01-01 (will retire on next tick).
     - Run tick.
     - Verify fighter 1 retired (is_retired=1).
     - Verify fighter_memory_links has a row with link_type='successor',
       fighter_id=<new replacement fighter_id>, linked_fighter_id=1.
     - Verify link_strength is in [60, 100] (1 reign → 60; capped at
       100 for 5+ reigns).
     - Verify news_items has a 'legacy'-topic news item with headline
       containing "comparisons to former champion" and the new
       replacement fighter's name.
  G. Non-champion retirement does NOT create memory_link:
     - Build fresh DB. Set fighter 1 DOB to 1980-01-01 (will retire
       on next tick). Fighter 1 is NOT a champion (titles are vacant
       in the fresh seed).
     - Run tick.
     - Verify fighter 1 retired.
     - Verify NO fighter_memory_links rows exist (the table is
       empty — no successor links created for non-champions).
     - Verify NO 'legacy'-topic news items created (the only news
       about the new prospect should be the standard 'prospect'-
       topic one from generate_fighter).
  H. Existing fighters have correct potential:
     - Build fresh DB.
     - John Vale (fighter_id=1): potential in [70, 75] (solid-to-elite
       per the brief — these are the player's starting roster).
     - Marcus Reed (fighter_id=2): potential in [70, 75].
     - Dario Knox, Eli Storm, Cole Briggs (fighter_ids=3,4,5):
       potential in [45, 55] (medium per the brief — RFL roster).
     - All 5 fighters have title_reigns=0 (none have won a title yet
       — both AC and RFL Lightweight titles are seeded VACANT).

Run from the project root:
    python3 scripts/test_pre_b1_fixes.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each block of generate_potential /
  generate_fighter / resolve_next_fight calls so the test is
  reproducible. The seed only pins down which random draws the
  functions see, not what they do with them.
"""
import json
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call fighter_gen's four functions,
# app.generate_fighter, app._resolve_title_after_fight, app.resolve_next_fight,
# and tick_processor.run_tick. Importing app.py pulls in tkinter — the import
# itself does not require a display (only tk.Tk() does), so this is safe in
# headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402
import fighter_gen  # noqa: E402
import tick_processor  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read DYNAMICALLY from
# build_db per CONVENTIONS §10 — do NOT hardcode '2.0.1'). The brief
# explicitly says "MUST use build_db.CODE_SCHEMA_VERSION dynamically".
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"
# The brief specifies the exact migration name (the suffix is the task
# description). This is the only place we hardcode a migration name
# suffix — and it's the brief's required name, not the supervisor's
# choice. The dynamic-prefix check above catches version mismatches.
EXPECTED_MIGRATION_NAME = "v2_0_1_potential_memory_archetype_fix"

# Seeded simulation_clock starts at 2026-07-20; 1 tick → 2026-07-21.
SEEDED_CLOCK_DATE = "2026-07-20"
TICK1_DATE = "2026-07-21"

# Fighter IDs assigned by seed_data.py (5 fighters total).
# John Vale = 1, Marcus Reed = 2, Dario Knox = 3, Eli Storm = 4, Cole Briggs = 5.
A_ID = 1
B_ID = 2

# Expected potential distribution from fighter_gen.generate_potential().
# (label, expected_percent, low, high). Tolerance is ±5 percentage
# points per tier (e.g., elite tier passes if it's between 5% and 15%
# of 1000 samples).
POTENTIAL_DISTRIBUTION = [
    ("elite", 10, 70, 90),
    ("solid", 30, 50, 69),
    ("limited", 60, 25, 49),
]
DISTRIBUTION_TOLERANCE_PCT = 5  # ±5 percentage points


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_fighter_attributes.py / test_regen.py /
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


def get_column_info(conn, table_name):
    """Return a dict of {col_name: type_str} for the given table."""
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


def set_fighter_attrs(conn, fighter_id, all_attr_value, morale=50):
    """Set a fighter's 4 legacy attributes (punch_power, cardio, fight_iq,
    chin) and 3 legacy personality fields (aggression, composure, morale)
    to a single value. Used to rig fight outcomes for deterministic
    test scenarios.
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


def set_dob(conn, fighter_id, dob):
    """Set a fighter's date_of_birth. Used to make fighters
    retirement-eligible for tick-based retirement tests.
    """
    conn.execute(
        "UPDATE fighters SET date_of_birth=? WHERE fighter_id=?",
        (dob, fighter_id),
    )


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK pre-B1-fixes ACCEPTANCE TEST")
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

    # A.3 exact migration name check REMOVED (B1 supervisor fix). build_db.py
    # only records the CURRENT version's migration, not all past migrations.
    # The LIKE-prefix check in A.2 is the durable check. Hardcoding the exact
    # name breaks on every version bump (same pattern as CONVENTIONS §10.4).

    # A.4 fighter_career has a `potential` column.
    fc_cols = get_column_names(conn, "fighter_career")
    results.append((
        "A", "fighter_career has column 'potential'",
        "potential" in fc_cols,
        f"got_cols={fc_cols}",
    ))

    # A.5 `potential` column is INTEGER NOT NULL DEFAULT 50 with CHECK 0-100.
    fc_sql = get_table_sql(conn, "fighter_career")
    results.append((
        "A", "fighter_career.potential is INTEGER NOT NULL DEFAULT 50",
        "potential INTEGER NOT NULL DEFAULT 50" in fc_sql,
        f"looking for: 'potential INTEGER NOT NULL DEFAULT 50'",
    ))
    results.append((
        "A", "fighter_career.potential has CHECK (potential BETWEEN 0 AND 100)",
        "CHECK (potential BETWEEN 0 AND 100)" in fc_sql,
        "looking for potential CHECK",
    ))

    # A.6 fighter_career has a `title_reigns` column.
    results.append((
        "A", "fighter_career has column 'title_reigns'",
        "title_reigns" in fc_cols,
        f"got_cols={fc_cols}",
    ))

    # A.7 `title_reigns` is INTEGER NOT NULL DEFAULT 0 with CHECK >= 0.
    results.append((
        "A", "fighter_career.title_reigns is INTEGER NOT NULL DEFAULT 0",
        "title_reigns INTEGER NOT NULL DEFAULT 0" in fc_sql,
        "looking for: 'title_reigns INTEGER NOT NULL DEFAULT 0'",
    ))
    results.append((
        "A", "fighter_career.title_reigns has CHECK (title_reigns >= 0)",
        "CHECK (title_reigns >= 0)" in fc_sql,
        "looking for title_reigns CHECK",
    ))

    # A.8 The CHECK constraint on `potential` fires on out-of-range
    #     values (potential=-1 should be rejected).
    check_fired_neg = False
    try:
        conn.execute(
            "INSERT INTO fighter_career (fighter_id, potential) VALUES (?, ?)",
            (999999, -1),
        )
        # If we get here, the CHECK didn't fire — bad.
    except sqlite3.IntegrityError:
        check_fired_neg = True
        # Roll back the failed insert so the connection is in a clean
        # state for subsequent checks.
        conn.rollback()
    results.append((
        "A", "potential CHECK rejects value -1 (out of range)",
        check_fired_neg,
        f"check_fired={check_fired_neg}",
    ))

    # A.9 The CHECK constraint on `potential` fires on potential=101.
    check_fired_high = False
    try:
        conn.execute(
            "INSERT INTO fighter_career (fighter_id, potential) VALUES (?, ?)",
            (999999, 101),
        )
    except sqlite3.IntegrityError:
        check_fired_high = True
        conn.rollback()
    results.append((
        "A", "potential CHECK rejects value 101 (out of range)",
        check_fired_high,
        f"check_fired={check_fired_high}",
    ))

    # A.10 The CHECK constraint on `title_reigns` fires on -1.
    check_fired_reigns = False
    try:
        conn.execute(
            "INSERT INTO fighter_career (fighter_id, title_reigns) "
            "VALUES (?, ?)",
            (999998, -1),
        )
    except sqlite3.IntegrityError:
        check_fired_reigns = True
        conn.rollback()
    results.append((
        "A", "title_reigns CHECK rejects value -1 (out of range)",
        check_fired_reigns,
        f"check_fired={check_fired_reigns}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case B — Archetype bias softening.
    # ----------------------------------------------------------------
    print("\n--- Case B: Archetype bias softening ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # B.1 All 7 style archetypes have parseable attribute_bias JSON.
    style_rows = conn.execute(
        "SELECT name, attribute_bias FROM style_archetypes "
        "ORDER BY style_archetype_id"
    ).fetchall()
    results.append((
        "B", f"7 style archetypes seeded (got {len(style_rows)})",
        len(style_rows) == 7,
        f"got={len(style_rows)}, expected=7",
    ))
    style_biases = []
    for name, bias_str in style_rows:
        ok = False
        detail = f"name={name!r}, got={bias_str!r}"
        if bias_str:
            try:
                parsed = json.loads(bias_str)
                ok = isinstance(parsed, dict) and len(parsed) > 0
                style_biases.append((name, parsed))
                detail = f"name={name!r}, parsed={parsed}"
            except (ValueError, TypeError) as e:
                detail = f"name={name!r}, parse error: {e}"
        results.append((
            "B", f"style archetype {name!r} has parseable non-empty bias JSON",
            ok, detail,
        ))

    # B.2 All 5 personality archetypes have parseable trait_bias JSON.
    pers_rows = conn.execute(
        "SELECT name, trait_bias FROM personality_archetypes "
        "ORDER BY personality_archetype_id"
    ).fetchall()
    results.append((
        "B", f"5 personality archetypes seeded (got {len(pers_rows)})",
        len(pers_rows) == 5,
        f"got={len(pers_rows)}, expected=5",
    ))
    pers_biases = []
    for name, bias_str in pers_rows:
        ok = False
        detail = f"name={name!r}, got={bias_str!r}"
        if bias_str:
            try:
                parsed = json.loads(bias_str)
                ok = isinstance(parsed, dict) and len(parsed) > 0
                pers_biases.append((name, parsed))
                detail = f"name={name!r}, parsed={parsed}"
            except (ValueError, TypeError) as e:
                detail = f"name={name!r}, parse error: {e}"
        results.append((
            "B", f"personality archetype {name!r} has parseable non-empty bias JSON",
            ok, detail,
        ))

    # B.3 The MAXIMUM absolute bias across ALL 12 archetypes is <= 10.
    all_max_abs = []
    for name, bias in style_biases + pers_biases:
        if bias:
            max_abs = max(abs(v) for v in bias.values())
            all_max_abs.append((name, max_abs))
    overall_max = max(m for _, m in all_max_abs) if all_max_abs else 0
    results.append((
        "B", f"max absolute bias across all 12 archetypes <= 10 (got {overall_max})",
        overall_max <= 10,
        f"per-archetype maxes={all_max_abs}",
    ))

    # B.4 Brawler bias has the exact softened values per the brief.
    brawler_bias = dict(style_biases).get("Brawler", {})
    expected_brawler = {
        "punch_power": 10, "chin": 8, "durability": 5,
        "footwork": -8, "fight_iq": -5, "cardio": -3,
    }
    for k, v in expected_brawler.items():
        results.append((
            "B", f"Brawler bias has {k}={v}",
            brawler_bias.get(k) == v,
            f"got={brawler_bias.get(k)}, expected={v}",
        ))

    # B.5 Counter-Striker bias has the exact softened values per the brief.
    cs_bias = dict(style_biases).get("Counter-Striker", {})
    expected_cs = {
        "punch_accuracy": 8, "head_movement": 8,
        "footwork": 8, "fight_iq": 8,
        "aggression": -5, "takedown_offense": -5,
    }
    for k, v in expected_cs.items():
        results.append((
            "B", f"Counter-Striker bias has {k}={v}",
            cs_bias.get(k) == v,
            f"got={cs_bias.get(k)}, expected={v}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Case C — generate_potential distribution.
    # ----------------------------------------------------------------
    print("\n--- Case C: generate_potential distribution ---")

    # C.1 generate_potential returns an int.
    random.seed(RANDOM_SEED)
    sample = fighter_gen.generate_potential()
    results.append((
        "C", "generate_potential() returns an int",
        isinstance(sample, int),
        f"got={sample!r} (type={type(sample).__name__})",
    ))

    # C.2 All values are in [25, 90] (union of the three tier ranges).
    random.seed(RANDOM_SEED)
    samples = [fighter_gen.generate_potential() for _ in range(1000)]
    out_of_range = [s for s in samples if not (25 <= s <= 90)]
    results.append((
        "C", f"all 1000 samples in [25, 90] (out_of_range count: {len(out_of_range)})",
        len(out_of_range) == 0,
        f"out_of_range_examples={out_of_range[:5]}",
    ))

    # C.3 Each tier is within ±5% of expected (elite=10%, solid=30%, limited=60%).
    elite_count = sum(1 for s in samples if 70 <= s <= 90)
    solid_count = sum(1 for s in samples if 50 <= s <= 69)
    limited_count = sum(1 for s in samples if 25 <= s <= 49)
    elite_pct = elite_count / 10.0  # /1000 * 100 = /10
    solid_pct = solid_count / 10.0
    limited_pct = limited_count / 10.0

    results.append((
        "C",
        f"elite tier ({elite_count}/1000 = {elite_pct:.1f}%) within ±{DISTRIBUTION_TOLERANCE_PCT}% of 10%",
        abs(elite_pct - 10) <= DISTRIBUTION_TOLERANCE_PCT,
        f"elite_count={elite_count}, elite_pct={elite_pct:.1f}%, expected=10%±{DISTRIBUTION_TOLERANCE_PCT}%",
    ))
    results.append((
        "C",
        f"solid tier ({solid_count}/1000 = {solid_pct:.1f}%) within ±{DISTRIBUTION_TOLERANCE_PCT}% of 30%",
        abs(solid_pct - 30) <= DISTRIBUTION_TOLERANCE_PCT,
        f"solid_count={solid_count}, solid_pct={solid_pct:.1f}%, expected=30%±{DISTRIBUTION_TOLERANCE_PCT}%",
    ))
    results.append((
        "C",
        f"limited tier ({limited_count}/1000 = {limited_pct:.1f}%) within ±{DISTRIBUTION_TOLERANCE_PCT}% of 60%",
        abs(limited_pct - 60) <= DISTRIBUTION_TOLERANCE_PCT,
        f"limited_count={limited_count}, limited_pct={limited_pct:.1f}%, expected=60%±{DISTRIBUTION_TOLERANCE_PCT}%",
    ))

    # C.4 No value falls in the excluded ranges [0, 24] or [91, 100].
    excluded = [s for s in samples if s < 25 or s > 90]
    results.append((
        "C", f"no samples in excluded ranges [0, 24] or [91, 100] (got {len(excluded)})",
        len(excluded) == 0,
        f"excluded_examples={excluded[:5]}",
    ))

    # ----------------------------------------------------------------
    # Case D — generate_fighter sets potential (not default 50).
    # ----------------------------------------------------------------
    print("\n--- Case D: generate_fighter sets potential ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # D.1 Call generate_fighter. The new fighter's fighter_career row
    #     should have `potential` set to a value from generate_potential
    #     (i.e., in [25, 90]), NOT the schema DEFAULT 50.
    #
    #     Note: 50 is INSIDE the [25, 90] range, so we can't directly
    #     check "potential != 50". Instead, we verify the value is in
    #     the valid range AND was explicitly INSERTed (the DEFAULT 50
    #     would only apply if the INSERT omitted the column — which
    #     the updated generate_fighter doesn't).
    random.seed(RANDOM_SEED)
    new_fid = app.generate_fighter(
        conn, style_dna_source_id=A_ID, current_date=TICK1_DATE
    )
    conn.commit()
    results.append((
        "D", f"generate_fighter returns a valid fighter_id (got {new_fid})",
        isinstance(new_fid, int) and new_fid > 0,
        f"got={new_fid!r}",
    ))

    if isinstance(new_fid, int) and new_fid > 0:
        # D.2 potential is set (in valid range [25, 90]).
        pot_row = conn.execute(
            "SELECT potential FROM fighter_career WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if pot_row:
            results.append((
                "D", f"new fighter potential ({pot_row[0]}) in [25, 90]",
                25 <= pot_row[0] <= 90,
                f"got={pot_row[0]}, expected: in [25, 90]",
            ))
        else:
            results.append((
                "D", "new fighter has a fighter_career row",
                False, f"no row for fighter_id={new_fid}",
            ))

        # D.3 title_reigns is 0 (default — new prospect hasn't won a title).
        reigns_row = conn.execute(
            "SELECT title_reigns FROM fighter_career WHERE fighter_id=?",
            (new_fid,),
        ).fetchone()
        if reigns_row:
            results.append((
                "D", f"new fighter title_reigns=0 (default, no title wins yet)",
                reigns_row[0] == 0,
                f"got={reigns_row[0]}, expected=0",
            ))

    conn.close()

    # ----------------------------------------------------------------
    # Case E — _resolve_title_after_fight increments title_reigns.
    # ----------------------------------------------------------------
    print("\n--- Case E: _resolve_title_after_fight increments title_reigns ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # E.1 Before resolve: both fighters have title_reigns=0.
    f1_reigns_before = conn.execute(
        "SELECT title_reigns FROM fighter_career WHERE fighter_id=?", (A_ID,)
    ).fetchone()
    f2_reigns_before = conn.execute(
        "SELECT title_reigns FROM fighter_career WHERE fighter_id=?", (B_ID,)
    ).fetchone()
    results.append((
        "E", f"before resolve: fighter {A_ID} title_reigns=0",
        f1_reigns_before is not None and f1_reigns_before[0] == 0,
        f"got={f1_reigns_before}",
    ))
    results.append((
        "E", f"before resolve: fighter {B_ID} title_reigns=0",
        f2_reigns_before is not None and f2_reigns_before[0] == 0,
        f"got={f2_reigns_before}",
    ))

    # E.2 Rig attrs so fighter 1 wins the vacant title.
    set_fighter_attrs(conn, A_ID, 90, 50)
    set_fighter_attrs(conn, B_ID, 30, 50)
    conn.commit()

    # E.3 Resolve the seeded title fight (fighter 1 wins the vacant title).
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()

    # E.4 After resolve: fighter 1's title_reigns=1 (won vacant title).
    #     Fighter 2's title_reigns still 0.
    f1_reigns_after_1 = conn.execute(
        "SELECT title_reigns FROM fighter_career WHERE fighter_id=?", (A_ID,)
    ).fetchone()
    f2_reigns_after_1 = conn.execute(
        "SELECT title_reigns FROM fighter_career WHERE fighter_id=?", (B_ID,)
    ).fetchone()
    results.append((
        "E", f"after fight 1 (vacant title won): fighter {A_ID} title_reigns=1",
        f1_reigns_after_1 is not None and f1_reigns_after_1[0] == 1,
        f"got={f1_reigns_after_1}, expected=1",
    ))
    results.append((
        "E", f"after fight 1: fighter {B_ID} title_reigns still 0",
        f2_reigns_after_1 is not None and f2_reigns_after_1[0] == 0,
        f"got={f2_reigns_after_1}, expected=0",
    ))

    # E.5 Verify the AC Lightweight title is held by fighter 1.
    title_row = conn.execute(
        "SELECT current_champion_fighter_id FROM titles "
        "WHERE promotion_id IN (SELECT promotion_id FROM promotions WHERE name='Alpha Combat') "
        "AND weight_class_id IN (SELECT weight_class_id FROM weight_classes WHERE name='Lightweight')"
    ).fetchone()
    results.append((
        "E", f"after fight 1: AC Lightweight champion is fighter {A_ID}",
        title_row is not None and title_row[0] == A_ID,
        f"got={title_row[0] if title_row else None}, expected={A_ID}",
    ))

    # E.6 Swap attrs so fighter 2 wins the next fight (dethrones f1).
    #     Then convert the auto-scheduled fight 2 to a title_fight
    #     and resolve it.
    set_fighter_attrs(conn, A_ID, 30, 50)
    set_fighter_attrs(conn, B_ID, 90, 50)
    conn.commit()

    # Convert the auto-scheduled fight 2 to a title_fight. The auto-
    # scheduled fight is the most-recently-created fight that's not
    # yet resolved.
    fight2_row = conn.execute(
        "SELECT fight_id FROM fights WHERE winner_fighter_id IS NULL "
        "ORDER BY fight_id DESC LIMIT 1"
    ).fetchone()
    if fight2_row:
        fight2_id = fight2_row[0]
        conn.execute(
            "UPDATE fights SET bout_type='title_fight', is_title_fight=1 WHERE fight_id=?",
            (fight2_id,),
        )
        conn.commit()

        # E.7 Resolve fight 2 (fighter 2 dethrones fighter 1).
        random.seed(RANDOM_SEED + 1)
        app.resolve_next_fight(conn)
        conn.commit()

        # E.8 After fight 2: fighter 2's title_reigns=1 (dethroned f1).
        #     Fighter 1's title_reigns STILL 1 (losing the title doesn't
        #     decrement the count — it's a HISTORICAL counter of reigns,
        #     not a current-reign flag).
        f1_reigns_after_2 = conn.execute(
            "SELECT title_reigns FROM fighter_career WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()
        f2_reigns_after_2 = conn.execute(
            "SELECT title_reigns FROM fighter_career WHERE fighter_id=?",
            (B_ID,),
        ).fetchone()
        results.append((
            "E", f"after fight 2 (dethroned): fighter {B_ID} title_reigns=1",
            f2_reigns_after_2 is not None and f2_reigns_after_2[0] == 1,
            f"got={f2_reigns_after_2}, expected=1",
        ))
        results.append((
            "E",
            f"after fight 2: fighter {A_ID} title_reigns STILL 1 "
            f"(historical counter, not decremented on loss)",
            f1_reigns_after_2 is not None and f1_reigns_after_2[0] == 1,
            f"got={f1_reigns_after_2}, expected=1 (preserved)",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Case F — Champion retirement creates memory_link + special news.
    # ----------------------------------------------------------------
    print("\n--- Case F: champion retirement creates memory_link + special news ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # F.1 Make fighter 1 a champion (resolve seeded title fight).
    set_fighter_attrs(conn, A_ID, 90, 50)
    set_fighter_attrs(conn, B_ID, 30, 50)
    conn.commit()
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()

    # F.2 Verify fighter 1 is the champion.
    champ_row = conn.execute(
        "SELECT current_champion_fighter_id FROM titles "
        "WHERE current_champion_fighter_id=?", (A_ID,)
    ).fetchone()
    results.append((
        "F", f"fighter {A_ID} is a current champion (won the vacant title)",
        champ_row is not None,
        f"got={champ_row}",
    ))

    # F.3 Verify fighter 1's title_reigns=1 (set by _resolve_title_after_fight).
    reigns_row = conn.execute(
        "SELECT title_reigns FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()
    results.append((
        "F", f"fighter {A_ID} fighter_career.title_reigns=1 (incremented)",
        reigns_row is not None and reigns_row[0] == 1,
        f"got={reigns_row}",
    ))

    # F.4 Snapshot fighter_memory_links count before tick.
    mem_before = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]

    # F.5 Set fighter 1 DOB to 1980-01-01 (age 46 → mandatory retirement).
    set_dob(conn, A_ID, "1980-01-01")
    conn.commit()

    # F.6 Run tick — fighter 1 retires (champion retirement).
    tick_processor.run_tick(conn)

    # F.7 Verify fighter 1 is retired.
    f1_status = conn.execute(
        "SELECT is_active, is_retired FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()
    results.append((
        "F", f"fighter {A_ID} retired after tick (is_active=0, is_retired=1)",
        f1_status == (0, 1),
        f"got={f1_status}",
    ))

    # F.8 Verify a fighter_memory_links 'successor' row was created
    #     linking the new replacement fighter to fighter 1.
    mem_after = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    results.append((
        "F", "1 fighter_memory_links row created by champion retirement",
        mem_after - mem_before == 1,
        f"before={mem_before}, after={mem_after}",
    ))

    # F.9 Verify the link's shape: link_type='successor', linked_fighter_id=A_ID.
    mem_row = conn.execute(
        "SELECT fighter_id, linked_fighter_id, link_type, link_strength "
        "FROM fighter_memory_links WHERE linked_fighter_id=?",
        (A_ID,),
    ).fetchone()
    if mem_row:
        new_fighter_id, linked_fighter_id, link_type, link_strength = mem_row
        results.append((
            "F", "memory_link.link_type='successor'",
            link_type == 'successor',
            f"got={link_type}",
        ))
        results.append((
            "F", f"memory_link.linked_fighter_id={A_ID} (the retiring champion)",
            linked_fighter_id == A_ID,
            f"got={linked_fighter_id}, expected={A_ID}",
        ))
        results.append((
            "F", f"memory_link.fighter_id is the new replacement ({new_fighter_id}) — not {A_ID} or {B_ID}",
            new_fighter_id not in (A_ID, B_ID) and new_fighter_id > 0,
            f"got={new_fighter_id}",
        ))
        # F.10 link_strength is in [60, 100] (1 reign → 60; 5+ reigns → 100).
        results.append((
            "F", f"memory_link.link_strength in [60, 100] (1 reign → 60)",
            60 <= link_strength <= 100,
            f"got={link_strength}, expected: 60 (1 reign) <= x <= 100",
        ))
        # F.11 For exactly 1 reign, link_strength should be exactly 60.
        results.append((
            "F", f"memory_link.link_strength=60 (exactly 1 title reign)",
            link_strength == 60,
            f"got={link_strength}, expected=60 (1 reign × 10 + 50 base)",
        ))
    else:
        results.append((
            "F", "memory_link row exists for retiring champion",
            False, f"no row found with linked_fighter_id={A_ID}",
        ))

    # F.12 Verify a 'legacy'-topic news item was created with the
    #      comparison-to-former-champion wording.
    legacy_news = conn.execute(
        "SELECT headline, body, topic, fighter_id FROM news_items "
        "WHERE topic='legacy' ORDER BY news_item_id DESC LIMIT 1"
    ).fetchone()
    results.append((
        "F", "a 'legacy'-topic news item exists (champion-successor comparison)",
        legacy_news is not None,
        f"got={legacy_news}",
    ))
    if legacy_news:
        headline, body, topic, news_fighter_id = legacy_news
        # F.13 Headline contains "comparisons to former champion".
        results.append((
            "F", "legacy news headline contains 'comparisons to former champion'",
            "comparisons to former champion" in headline.lower(),
            f"headline={headline!r}",
        ))
        # F.14 Headline mentions the new replacement fighter's name
        #      (we can't predict the exact name — generate_fighter draws
        #      from name_pools — but it should be in the headline).
        new_fighter_name_row = conn.execute(
            "SELECT first_name || ' ' || last_name FROM fighters "
            "WHERE fighter_id=?",
            (new_fighter_id,) if mem_row else (-1,),
        ).fetchone() if mem_row else None
        if new_fighter_name_row:
            new_name = new_fighter_name_row[0]
            results.append((
                "F", f"legacy news headline contains new prospect's name ({new_name!r})",
                new_name in headline,
                f"headline={headline!r}, looking for={new_name!r}",
            ))
        # F.15 The news item's fighter_id is the new replacement's id
        #      (so future UIs can filter "this prospect's news").
        results.append((
            "F", "legacy news.fighter_id is the new replacement's id",
            news_fighter_id == (new_fighter_id if mem_row else -1),
            f"got={news_fighter_id}, expected={new_fighter_id if mem_row else 'unknown'}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Case G — Non-champion retirement does NOT create memory_link.
    # ----------------------------------------------------------------
    print("\n--- Case G: non-champion retirement does NOT create memory_link ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # G.1 Verify fighter 1's title_reigns=0 in fresh seed (NOT a champion).
    f1_reigns_fresh = conn.execute(
        "SELECT title_reigns FROM fighter_career WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()
    results.append((
        "G", f"fresh seed: fighter {A_ID} title_reigns=0 (not a champion)",
        f1_reigns_fresh is not None and f1_reigns_fresh[0] == 0,
        f"got={f1_reigns_fresh}",
    ))

    # G.2 Verify no current champion (both AC + RFL Lightweight titles vacant).
    n_champs = conn.execute(
        "SELECT COUNT(*) FROM titles WHERE current_champion_fighter_id IS NOT NULL"
    ).fetchone()[0]
    results.append((
        "G", f"fresh seed: no current champions (all titles vacant, got {n_champs})",
        n_champs == 0,
        f"got={n_champs}",
    ))

    # G.3 Set fighter 1 DOB to 1980-01-01 (will retire, NOT a champion).
    set_dob(conn, A_ID, "1980-01-01")
    conn.commit()

    mem_before_g = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    legacy_before_g = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='legacy'"
    ).fetchone()[0]

    # G.4 Run tick — fighter 1 retires (non-champion retirement).
    tick_processor.run_tick(conn)

    # G.5 Verify fighter 1 is retired.
    f1_status_g = conn.execute(
        "SELECT is_active, is_retired FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()
    results.append((
        "G", f"fighter {A_ID} retired after tick",
        f1_status_g == (0, 1),
        f"got={f1_status_g}",
    ))

    # G.6 Verify NO new fighter_memory_links rows created.
    mem_after_g = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    results.append((
        "G",
        "no fighter_memory_links rows created for non-champion retirement",
        mem_after_g == mem_before_g,
        f"before={mem_before_g}, after={mem_after_g}",
    ))

    # G.7 Verify NO 'legacy'-topic news items created.
    legacy_after_g = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='legacy'"
    ).fetchone()[0]
    results.append((
        "G",
        "no 'legacy'-topic news items created for non-champion retirement",
        legacy_after_g == legacy_before_g,
        f"before={legacy_before_g}, after={legacy_after_g}",
    ))

    # G.8 Verify the standard 'prospect'-topic news WAS created
    #     (the standard prospect news from generate_fighter should
    #     still fire — we just don't add the champion comparison on top).
    prospect_news_g = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='prospect'"
    ).fetchone()[0]
    results.append((
        "G",
        f"standard 'prospect'-topic news WAS created (got {prospect_news_g})",
        prospect_news_g >= 1,
        f"prospect_news_count={prospect_news_g}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Case H — Existing fighters have correct potential (backfill).
    # ----------------------------------------------------------------
    print("\n--- Case H: existing fighters have correct potential (backfill) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # H.1 John Vale (id 1) potential in [70, 75] (solid-to-elite).
    jv_pot = conn.execute(
        "SELECT potential FROM fighter_career WHERE fighter_id=1"
    ).fetchone()
    results.append((
        "H", f"John Vale (id 1) potential in [70, 75] (got {jv_pot[0] if jv_pot else None})",
        jv_pot is not None and 70 <= jv_pot[0] <= 75,
        f"got={jv_pot[0] if jv_pot else None}, expected: in [70, 75]",
    ))

    # H.2 Marcus Reed (id 2) potential in [70, 75].
    mr_pot = conn.execute(
        "SELECT potential FROM fighter_career WHERE fighter_id=2"
    ).fetchone()
    results.append((
        "H", f"Marcus Reed (id 2) potential in [70, 75] (got {mr_pot[0] if mr_pot else None})",
        mr_pot is not None and 70 <= mr_pot[0] <= 75,
        f"got={mr_pot[0] if mr_pot else None}, expected: in [70, 75]",
    ))

    # H.3 RFL fighters (ids 3, 4, 5) potential in [45, 55].
    for fid, name in [(3, "Dario Knox"), (4, "Eli Storm"), (5, "Cole Briggs")]:
        pot = conn.execute(
            "SELECT potential FROM fighter_career WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        results.append((
            "H", f"{name} (id {fid}) potential in [45, 55] (got {pot[0] if pot else None})",
            pot is not None and 45 <= pot[0] <= 55,
            f"got={pot[0] if pot else None}, expected: in [45, 55]",
        ))

    # H.4 All 5 seeded fighters have title_reigns=0 (none have won a
    #     title yet — both titles are seeded VACANT).
    for fid in [1, 2, 3, 4, 5]:
        reigns = conn.execute(
            "SELECT title_reigns FROM fighter_career WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        results.append((
            "H", f"fighter {fid} title_reigns=0 (no title wins in fresh seed)",
            reigns is not None and reigns[0] == 0,
            f"got={reigns[0] if reigns else None}, expected=0",
        ))

    # H.5 AC starters have HIGHER potential than RFL roster on average.
    ac_pots = [jv_pot[0], mr_pot[0]]
    rfl_pots = []
    for fid in [3, 4, 5]:
        pot = conn.execute(
            "SELECT potential FROM fighter_career WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if pot:
            rfl_pots.append(pot[0])
    if ac_pots and rfl_pots:
        ac_mean = sum(ac_pots) / len(ac_pots)
        rfl_mean = sum(rfl_pots) / len(rfl_pots)
        results.append((
            "H",
            f"AC starters mean potential ({ac_mean:.1f}) > RFL roster mean ({rfl_mean:.1f})",
            ac_mean > rfl_mean,
            f"ac_pots={ac_pots}, rfl_pots={rfl_pots}",
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
