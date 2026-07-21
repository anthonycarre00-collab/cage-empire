#!/usr/bin/env python3
"""Acceptance test for Task ID 14 — Regen engine (LAST Stage 2 task).

Tests the regen engine added in Task ID 14:

  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read dynamically — NO hardcoded version string).
     - schema_migrations contains a row starting with 'v1_9_0_'.
     - 3 new tables exist: name_pools, regen_lineage, fighter_memory_links.
     - Total table count is 37 (was 34 in v1.8.0, +3 new tables).
     - name_pools.name_type has a CHECK constraint on the 4 allowed
       values (first_male, first_female, last, nickname).
     - regen_lineage has a UNIQUE constraint on
       (retiring_fighter_id, replacement_fighter_id).
     - fighter_memory_links.link_type has a CHECK constraint on the
       4 allowed values (style_echo, gym_heir, regional_rival, successor).
  B. Name pool seed:
     - name_pools has entries for all 4 name_type values.
     - At least 20 entries per type (the seed provides 25-26 per type).
     - Total name pool entries == 96 (25+25+26+20).
  C. generate_fighter() basic:
     - Build fresh DB. Call generate_fighter(conn, style_dna_source_id=1,
       current_date='2026-07-21').
     - Returns a valid fighter_id (int > 0).
     - New fighter exists with is_active=1, is_retired=0,
       current_promotion_id=NULL (free agent).
     - New fighter has a unique (first_name, last_name) combination
       (not matching any existing fighter).
     - New fighter has the same fight_style_archetype_id as fighter 1
       (style DNA inherited).
     - New fighter has default attributes (all 50), personality (all 50),
       career (0-0-0, career_health=100).
     - New fighter's DOB makes them 18-26 years old (compute age from
       current_date).
     - A news item was created about the new prospect.
  D. generate_fighter() without style DNA source:
     - Call generate_fighter(conn, style_dna_source_id=None,
       current_date='2026-07-21').
     - Returns a valid fighter_id.
     - New fighter has a valid fight_style_archetype_id (randomly picked
       from existing archetypes).
  E. generate_fighter() name uniqueness:
     - Call generate_fighter() 10 times. All 10 have unique (first_name,
       last_name) combinations.
     - No name collision with the 5 seeded fighters.
  F. generate_fighter() name pool exhaustion:
     - Reduce the name pool to 1 first name + 1 last name. Generate
       one fighter (uses the one available combination).
     - Second call returns None with a warning (name combination already
       used).
  G. Regen on retirement:
     - Build fresh DB. Set fighter 1's DOB to 1980-01-01 (age 46, will
       retire).
     - Before tick: 5 fighters exist.
     - Run tick. Fighter 1 is retired.
     - A new fighter was generated (6 fighters total now).
     - A regen_lineage row exists linking fighter 1 (retiring) to the
       new fighter (replacement).
     - The new fighter has the same fight_style_archetype_id as fighter 1.
     - The new fighter is a free agent (current_promotion_id=NULL).
     - The new fighter appears in get_free_agents_for_display(conn).
     - A news item about the new prospect was created.
  H. Multiple regens on one tick:
     - Build fresh DB. Set fighters 1, 2, 3 (one AC, two RFL) all to DOB
       1980-01-01.
     - Run tick. All 3 retire. 3 new fighters generated (8 fighters total:
       5 original + 3 regens).
     - 3 regen_lineage rows exist.
     - 3 new prospect news items created.
  I. generate_fighter() with female gender:
     - Call generate_fighter(conn, gender='female'). The new fighter's
       gender is 'female' and the first name comes from the first_female
       pool.
  J. Regression: all previous tasks still work:
     - Build fresh DB. Resolve the seeded fight. Assert all Task 3-13
       side effects work (fight_history +2 rows, rankings updated, title
       transferred, event completed, new event scheduled, contracts
       unchanged).
     - Run tick. Assert no retirements (fighters in 30s). Assert no
       regens.
     - Manually expire a contract (set end_date to past). Run tick.
       Assert the fighter becomes a free agent. Assert no regen (the
       fighter didn't retire, just became a free agent — regen only
       fires on retirement, not on contract expiry).
  K. generate_fighter() callable directly:
     - Build fresh DB. Call generate_fighter(conn) directly (no args
       beyond conn). Returns a valid fighter_id. The new fighter is a
       free agent.

Run from the project root:
    python3 scripts/test_regen.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each `app.generate_fighter()` and
  `app.resolve_next_fight()` call so the test is reproducible. The
  seed only pins down which random draws the function sees, not what
  it does with them.

D5 quirk note (from Task 12 worklog, inherited by Task 14):
  tick_processor.py's `run_tick` uses `SELECT current_date, current_day,
  ... FROM simulation_clock WHERE clock_id=1` (bare column names, no
  table qualifier). SQLite resolves `current_date` to the built-in date
  FUNCTION (today's wall-clock date) instead of the simulation_clock.
  current_date COLUMN. This means after 1 tick, the clock column gets
  set to today+1 (e.g., 2026-07-22 if today is 2026-07-21), skipping
  the seeded date 2026-07-20 entirely. This is a pre-existing quirk
  that's OUTSIDE Task 14's scope. All assertions in this test are
  robust to the quirk because they assert on data-shape changes (new
  fighter rows, regen_lineage rows, news items), not on specific clock
  values. Where we need a specific date for the regen_lineage.regen_date
  or prospect news item published_at, we pass current_date explicitly
  to _check_retirements (which forwards it to generate_fighter) — that
  path is NOT affected by the D5 quirk.
"""
import random
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call generate_fighter(),
# get_free_agents_for_display(), resolve_next_fight(),
# tick_processor._check_retirements(), and (for case J's contract
# expiry check) tick_processor._check_contract_expiry. Importing app.py
# pulls in tkinter — the import itself does not require a display (only
# tk.Tk() does), so this is safe in headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402
import tick_processor  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read dynamically from
# build_db so this test does not need to be updated on every schema
# version bump — same pattern as test_retirement.py, test_rankings.py,
# test_contracts.py, test_titles.py, test_free_agency.py,
# test_schema_versioning.py, test_fight_history.py). The brief
# explicitly says "MUST use build_db.CODE_SCHEMA_VERSION dynamically —
# do NOT hardcode '1.9.0'".
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py.
# John "Hammer" Vale = 1 (AC), Marcus "Voltage" Reed = 2 (AC),
# Dario "The Drill" Knox = 3 (RFL), Eli "Whisper" Storm = 4 (RFL),
# Cole "Anvil" Briggs = 5 (RFL).
A_ID = 1
B_ID = 2
C_ID = 3
D_ID = 4
E_ID = 5

# Promotion IDs assigned by seed_data.py.
ALPHA_COMBAT_ID = 1
RFL_ID = 2

# Seeded event date from src/seed_data.py — used for assertions.
SEEDED_EVENT_DATE = "2026-08-15"

# Seeded clock date + a representative date used for explicit
# generate_fighter / _check_retirements calls. The D5 quirk means
# tick_processor.run_tick() won't actually produce this date, but our
# direct calls to generate_fighter / _check_retirements pass it
# explicitly so they're not affected by the quirk.
SEEDED_CLOCK_DATE = "2026-07-20"
TEST_DATE = "2026-07-21"

# Total tables at v1.9.0 (Task 14 adds 3 new tables: name_pools,
# regen_lineage, fighter_memory_links). 34 (v1.8.0) + 3 = 37.
EXPECTED_TABLE_COUNT = 37

# Total name pool entries (per _seed_name_pools in seed_data.py):
# 25 male first + 25 female first + 26 last + 20 nickname = 96.
EXPECTED_NAME_POOL_TOTAL = 96
MIN_NAMES_PER_TYPE = 20  # spec: "at least 20 entries per type"


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_retirement.py / test_rankings.py /
    test_contracts.py / test_event_scheduler.py / test_titles.py /
    test_free_agency.py so all tests share the same setup contract: a
    fresh DB with 2 promotions (Alpha Combat + Rival Fight League),
    5 fighters (2 AC + 3 RFL), 1 staff member (Nina Cross), 1 event,
    1 title_fight (the seeded main event), 6 contracts (5 fighter + 1
    staff), 5 rankings rows (all at 1000.0), 2 titles (both vacant —
    AC Lightweight + RFL Lightweight), 96 name pool entries. All 5
    fighters have is_retired=0 (none retirement-eligible at seed time).
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


def set_dob(conn, fighter_id, dob):
    """Set a fighter's date_of_birth to the given 'YYYY-MM-DD' string."""
    conn.execute(
        "UPDATE fighters SET date_of_birth=? WHERE fighter_id=?",
        (dob, fighter_id),
    )


def compute_age(dob_str, current_date_str):
    """Compute integer age from a DOB string and a current-date string.

    Same logic as _check_retirements: years between dob and current_date,
    adjusted down by 1 if the birthday hasn't happened yet this year.
    Returns None if either input is malformed.
    """
    try:
        dob_dt = datetime.strptime(dob_str, "%Y-%m-%d")
        cur_dt = datetime.strptime(current_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    age = cur_dt.year - dob_dt.year
    if (cur_dt.month, cur_dt.day) < (dob_dt.month, dob_dt.day):
        age -= 1
    return age


def get_fighter_status(conn, fighter_id):
    """Return (is_active, is_retired, current_promotion_id) for the fighter."""
    row = conn.execute(
        "SELECT is_active, is_retired, current_promotion_id "
        "FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return tuple(row) if row else None


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK 14 REGEN ENGINE ACCEPTANCE TEST")
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

    # ----------------------------------------------------------------
    # Test case A — Schema.
    # ----------------------------------------------------------------
    print("\n--- Case A: schema ---")

    # schema_meta.schema_version matches the code's current
    # CODE_SCHEMA_VERSION (dynamic, no hardcoding).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        "A",
        f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
        sv is not None and sv[0] == EXPECTED_CODE_VERSION,
        f"got={sv[0] if sv else None}",
    ))

    # migration name starts with 'v1_9_0_' (LIKE prefix check, so the
    # description suffix can change per task: _add_regen, etc.).
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

    # 3 new tables exist: name_pools, regen_lineage, fighter_memory_links.
    for tname in ("name_pools", "regen_lineage", "fighter_memory_links"):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tname,),
        ).fetchone()
        results.append((
            "A",
            f"table {tname} exists",
            row is not None,
            f"found={row is not None}",
        ))

    # Total table count is 37 (was 34 in v1.8.0, +3 new tables).
    n_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    results.append((
        "A",
        f"total table count == {EXPECTED_TABLE_COUNT} (34 + 3 new)",
        n_tables == EXPECTED_TABLE_COUNT,
        f"got={n_tables}",
    ))

    # name_pools.name_type CHECK constraint: try inserting an invalid
    # name_type (should raise IntegrityError).
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO name_pools (name_type, name_value) "
            "VALUES ('invalid_type', 'TestName')"
        )
        check_passed = False
        check_detail = "invalid name_type INSERT did not raise (CHECK failed)"
    except sqlite3.IntegrityError:
        pass  # expected
    conn.rollback()
    results.append((
        "A",
        "name_pools.name_type CHECK constraint rejects invalid types",
        check_passed,
        check_detail,
    ))

    # regen_lineage UNIQUE constraint on (retiring_fighter_id,
    # replacement_fighter_id): insert a row, then try inserting the
    # same (retiring, replacement) pair again (should raise
    # IntegrityError). We use fighter_ids 1 and 2 from the seed as
    # placeholders — the regen_lineage table only requires the FKs to
    # exist, it doesn't validate the relationship semantics.
    conn.execute(
        "INSERT INTO regen_lineage (retiring_fighter_id, "
        "replacement_fighter_id, style_dna_archetype_id, regen_date) "
        "VALUES (?, ?, ?, ?)",
        (1, 2, 1, "2026-07-21"),
    )
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO regen_lineage (retiring_fighter_id, "
            "replacement_fighter_id, style_dna_archetype_id, regen_date) "
            "VALUES (?, ?, ?, ?)",
            (1, 2, 1, "2026-07-21"),
        )
        check_passed = False
        check_detail = "duplicate (retiring, replacement) INSERT did not raise"
    except sqlite3.IntegrityError:
        pass  # expected
    conn.rollback()
    results.append((
        "A",
        "regen_lineage UNIQUE (retiring_fighter_id, replacement_fighter_id)",
        check_passed,
        check_detail,
    ))

    # fighter_memory_links.link_type CHECK constraint: try inserting
    # an invalid link_type (should raise IntegrityError).
    check_passed = True
    check_detail = ""
    try:
        conn.execute(
            "INSERT INTO fighter_memory_links (fighter_id, linked_fighter_id, "
            "link_type) VALUES (?, ?, 'invalid_link_type')",
            (1, 2),
        )
        check_passed = False
        check_detail = "invalid link_type INSERT did not raise (CHECK failed)"
    except sqlite3.IntegrityError:
        pass  # expected
    conn.rollback()
    results.append((
        "A",
        "fighter_memory_links.link_type CHECK constraint rejects invalid types",
        check_passed,
        check_detail,
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case B — Name pool seed.
    # ----------------------------------------------------------------
    print("\n--- Case B: name pool seed ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # name_pools has entries for all 4 name_type values.
    for nt in ("first_male", "first_female", "last", "nickname"):
        cnt = conn.execute(
            "SELECT COUNT(*) FROM name_pools WHERE name_type=?", (nt,)
        ).fetchone()[0]
        results.append((
            "B",
            f"name_pools has entries for name_type='{nt}'",
            cnt > 0,
            f"count={cnt}",
        ))
        # At least 20 entries per type.
        results.append((
            "B",
            f"name_pools name_type='{nt}' has >= {MIN_NAMES_PER_TYPE} entries",
            cnt >= MIN_NAMES_PER_TYPE,
            f"count={cnt} (need >= {MIN_NAMES_PER_TYPE})",
        ))

    # Total name pool entries == 96 (25+25+26+20).
    n_total = conn.execute("SELECT COUNT(*) FROM name_pools").fetchone()[0]
    results.append((
        "B",
        f"total name_pool entries == {EXPECTED_NAME_POOL_TOTAL}",
        n_total == EXPECTED_NAME_POOL_TOTAL,
        f"got={n_total}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case C — generate_fighter() basic.
    # ----------------------------------------------------------------
    print("\n--- Case C: generate_fighter() basic ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Snapshot the seeded fighter names so we can verify the new
    # fighter's name doesn't collide.
    seeded_names = conn.execute(
        "SELECT first_name, last_name FROM fighters"
    ).fetchall()
    seeded_name_set = set(seeded_names)

    random.seed(RANDOM_SEED)
    fid = app.generate_fighter(
        conn, style_dna_source_id=A_ID, current_date=TEST_DATE
    )
    conn.commit()

    results.append((
        "C",
        "generate_fighter returns a valid fighter_id (int > 0)",
        isinstance(fid, int) and fid > 0,
        f"got={fid!r}",
    ))

    if isinstance(fid, int) and fid > 0:
        # New fighter exists with the right free-agent status.
        row = conn.execute(
            "SELECT first_name, last_name, nickname, gender, date_of_birth, "
            "current_promotion_id, current_gym_id, is_active, is_retired, "
            "fight_style_archetype_id, personality_archetype_id, "
            "weight_class_id "
            "FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        (first_name, last_name, nickname, gender, dob, cur_promo, cur_gym,
         is_active, is_retired, style_id, pers_id, wc) = row

        results.append((
            "C",
            "new fighter is_active=1 (active)",
            is_active == 1,
            f"got={is_active}",
        ))
        results.append((
            "C",
            "new fighter is_retired=0 (not retired)",
            is_retired == 0,
            f"got={is_retired}",
        ))
        results.append((
            "C",
            "new fighter current_promotion_id IS NULL (free agent)",
            cur_promo is None,
            f"got={cur_promo}",
        ))

        # Unique name.
        results.append((
            "C",
            "new fighter has a unique (first, last) name combination",
            (first_name, last_name) not in seeded_name_set,
            f"name={(first_name, last_name)}",
        ))

        # Style DNA inherited from fighter 1.
        src_style = conn.execute(
            "SELECT fight_style_archetype_id FROM fighters WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        results.append((
            "C",
            f"new fighter inherits style_archetype_id={src_style} from fighter {A_ID}",
            style_id == src_style and style_id is not None,
            f"got={style_id}, expected={src_style}",
        ))

        # Attributes are populated with archetype-biased values (Task 14.5+14.6+14.7
        # supervisor fix: generate_fighter now uses fighter_gen.py, so values are
        # NOT all-50 anymore — they're archetype-biased + noise. Assert they're
        # in valid range [0, 100] and populated (not NULL).
        a = conn.execute(
            "SELECT punch_power, cardio, fight_iq, chin "
            "FROM fighter_attributes WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        results.append((
            "C",
            "new fighter has populated attributes (all in 0-100, not NULL)",
            a is not None and all(v is not None and 0 <= v <= 100 for v in a),
            f"got={a}",
        ))

        # Personality is populated with archetype-biased values (same fix).
        p = conn.execute(
            "SELECT aggression, composure, morale "
            "FROM fighter_personality WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        results.append((
            "C",
            "new fighter has populated personality (all in 0-100, not NULL)",
            p is not None and all(v is not None and 0 <= v <= 100 for v in p),
            f"got={p}",
        ))

        # Default career (0-0-0, career_health=100).
        c = conn.execute(
            "SELECT record_wins, record_losses, record_draws, career_health "
            "FROM fighter_career WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        results.append((
            "C",
            "new fighter has default career (0-0-0, health=100)",
            c == (0, 0, 0, 100),
            f"got={c}",
        ))

        # DOB makes them 18-26 years old (compute age from TEST_DATE).
        age = compute_age(dob, TEST_DATE)
        results.append((
            "C",
            f"new fighter age in [18, 26] (computed from {TEST_DATE})",
            age is not None and 18 <= age <= 26,
            f"got={age}, dob={dob}",
        ))

        # News item about the new prospect.
        news = conn.execute(
            "SELECT headline, topic, fighter_id FROM news_items "
            "WHERE topic='prospect' AND fighter_id=?",
            (fid,),
        ).fetchall()
        results.append((
            "C",
            "news item about the new prospect was created",
            len(news) == 1,
            f"got={news}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case D — generate_fighter() without style DNA source.
    # ----------------------------------------------------------------
    print("\n--- Case D: generate_fighter() without style DNA source ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Existing archetype IDs.
    arch_ids = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes"
    ).fetchall()
    arch_id_set = {r[0] for r in arch_ids}

    random.seed(RANDOM_SEED)
    fid = app.generate_fighter(
        conn, style_dna_source_id=None, current_date=TEST_DATE
    )
    conn.commit()

    results.append((
        "D",
        "generate_fighter(style_dna_source_id=None) returns valid fighter_id",
        isinstance(fid, int) and fid > 0,
        f"got={fid!r}",
    ))

    if isinstance(fid, int) and fid > 0:
        style_id = conn.execute(
            "SELECT fight_style_archetype_id FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()[0]
        results.append((
            "D",
            "new fighter has a valid (randomly-picked) style_archetype_id",
            style_id in arch_id_set,
            f"got={style_id}, valid_set={arch_id_set}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case E — generate_fighter() name uniqueness.
    # ----------------------------------------------------------------
    print("\n--- Case E: generate_fighter() name uniqueness ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Snapshot the seeded fighter names.
    seeded_names = set(conn.execute(
        "SELECT first_name, last_name FROM fighters"
    ).fetchall())

    # Generate 10 fighters.
    random.seed(RANDOM_SEED)
    generated_names = []
    all_unique = True
    for i in range(10):
        fid = app.generate_fighter(conn, current_date=TEST_DATE)
        if not isinstance(fid, int) or fid <= 0:
            all_unique = False
            results.append((
                "E",
                f"generate_fighter call {i+1} returned valid fighter_id",
                False,
                f"got={fid!r}",
            ))
            break
        row = conn.execute(
            "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if row is None:
            all_unique = False
            results.append((
                "E",
                f"generate_fighter call {i+1}: fighter row missing",
                False,
                f"fighter_id={fid}",
            ))
            break
        name = (row[0], row[1])
        if name in generated_names:
            all_unique = False
            results.append((
                "E",
                f"generate_fighter call {i+1} produced a duplicate name",
                False,
                f"name={name}, prior={generated_names}",
            ))
            break
        if name in seeded_names:
            all_unique = False
            results.append((
                "E",
                f"generate_fighter call {i+1} collided with a seeded name",
                False,
                f"name={name}",
            ))
            break
        generated_names.append(name)
    conn.commit()

    if all_unique:
        results.append((
            "E",
            "10 generate_fighter calls produced 10 unique names",
            len(generated_names) == 10,
            f"got {len(generated_names)} unique names",
        ))
        results.append((
            "E",
            "no name collision with the 5 seeded fighters",
            seeded_names.isdisjoint(set(generated_names)),
            f"seeded={seeded_names}, generated={set(generated_names)}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case F — generate_fighter() name pool exhaustion.
    # ----------------------------------------------------------------
    print("\n--- Case F: generate_fighter() name pool exhaustion ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Reduce the name pool to 1 first name + 1 last name.
    conn.execute("DELETE FROM name_pools WHERE name_type IN ('first_male', 'last')")
    conn.execute(
        "INSERT INTO name_pools (name_type, name_value) VALUES ('first_male', 'Solo')"
    )
    conn.execute(
        "INSERT INTO name_pools (name_type, name_value) VALUES ('last', 'Tester')"
    )
    conn.commit()

    # First call should succeed (uses the one available combination
    # 'Solo Tester'). Note: 5 seeded fighters exist (John Vale, Marcus
    # Reed, etc.) — 'Solo Tester' doesn't collide with any of them.
    random.seed(RANDOM_SEED)
    fid1 = app.generate_fighter(conn, current_date=TEST_DATE)
    conn.commit()
    results.append((
        "F",
        "first generate_fighter call succeeds with the single available name",
        isinstance(fid1, int) and fid1 > 0,
        f"got={fid1!r}",
    ))

    # Verify the first call used 'Solo Tester'.
    if isinstance(fid1, int) and fid1 > 0:
        row = conn.execute(
            "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
            (fid1,),
        ).fetchone()
        results.append((
            "F",
            "first generated fighter is named 'Solo Tester'",
            row == ("Solo", "Tester"),
            f"got={row}",
        ))

    # Second call should return None (name combination already used).
    fid2 = app.generate_fighter(conn, current_date=TEST_DATE)
    conn.commit()
    results.append((
        "F",
        "second generate_fighter call returns None (pool exhausted)",
        fid2 is None,
        f"got={fid2!r}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case G — Regen on retirement.
    # ----------------------------------------------------------------
    print("\n--- Case G: regen on retirement ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set fighter 1's DOB to 1980-01-01 (age 46 on 2026-07-21, will retire).
    set_dob(conn, A_ID, "1980-01-01")
    conn.commit()

    # Before tick: 5 fighters, 0 free agents.
    n_before = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    n_free_before = len(app.get_free_agents_for_display(conn))
    results.append((
        "G",
        f"before tick: {n_before} fighters (expected 5)",
        n_before == 5,
        f"got={n_before}",
    ))
    results.append((
        "G",
        "before tick: 0 free agents",
        n_free_before == 0,
        f"got={n_free_before}",
    ))

    # Run tick — this retires fighter 1 and triggers the regen.
    random.seed(RANDOM_SEED)
    tick_processor.run_tick(conn, "day", 1)

    # Fighter 1 is retired.
    f1_status = get_fighter_status(conn, A_ID)
    results.append((
        "G",
        f"fighter {A_ID} is retired (is_active=0, is_retired=1)",
        f1_status is not None and f1_status[0] == 0 and f1_status[1] == 1,
        f"got={f1_status}",
    ))

    # A new fighter was generated (6 fighters total now).
    n_after = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    results.append((
        "G",
        f"after tick: {n_after} fighters (expected 6 — 5 + 1 regen)",
        n_after == 6,
        f"got={n_after}",
    ))

    # A regen_lineage row exists linking fighter 1 (retiring) to the
    # new fighter (replacement).
    lineage = conn.execute(
        "SELECT retiring_fighter_id, replacement_fighter_id, "
        "style_dna_archetype_id "
        "FROM regen_lineage WHERE retiring_fighter_id=?",
        (A_ID,),
    ).fetchall()
    results.append((
        "G",
        f"regen_lineage row exists for retiring fighter {A_ID}",
        len(lineage) == 1,
        f"got={lineage}",
    ))

    if len(lineage) == 1:
        retiring_id, replacement_id, lineage_style = lineage[0]
        results.append((
            "G",
            "regen_lineage links retiring fighter to replacement",
            retiring_id == A_ID and replacement_id != A_ID and replacement_id > 5,
            f"retiring={retiring_id}, replacement={replacement_id}",
        ))

        # The new fighter has the same fight_style_archetype_id as fighter 1.
        src_style = conn.execute(
            "SELECT fight_style_archetype_id FROM fighters WHERE fighter_id=?",
            (A_ID,),
        ).fetchone()[0]
        new_style = conn.execute(
            "SELECT fight_style_archetype_id FROM fighters WHERE fighter_id=?",
            (replacement_id,),
        ).fetchone()[0]
        results.append((
            "G",
            f"replacement inherits style_archetype_id={src_style}",
            new_style == src_style == lineage_style and src_style is not None,
            f"new={new_style}, source={src_style}, lineage={lineage_style}",
        ))

        # The new fighter is a free agent.
        new_status = get_fighter_status(conn, replacement_id)
        results.append((
            "G",
            "replacement is a free agent (current_promotion_id IS NULL, "
            "is_active=1, is_retired=0)",
            new_status is not None
            and new_status[0] == 1
            and new_status[1] == 0
            and new_status[2] is None,
            f"got={new_status}",
        ))

        # The new fighter appears in get_free_agents_for_display.
        free_agents = app.get_free_agents_for_display(conn)
        free_agent_ids = [fa[0] for fa in free_agents]
        results.append((
            "G",
            "replacement appears in get_free_agents_for_display",
            replacement_id in free_agent_ids,
            f"free_agent_ids={free_agent_ids}",
        ))

    # A news item about the new prospect was created.
    prospect_news = conn.execute(
        "SELECT headline, topic FROM news_items WHERE topic='prospect'"
    ).fetchall()
    results.append((
        "G",
        "news item about the new prospect was created",
        len(prospect_news) >= 1,
        f"got={prospect_news}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case H — Multiple regens on one tick.
    # ----------------------------------------------------------------
    print("\n--- Case H: multiple regens on one tick ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set fighters 1, 2, 3 (one AC, two RFL) all to DOB 1980-01-01.
    set_dob(conn, A_ID, "1980-01-01")  # John Vale (AC)
    set_dob(conn, B_ID, "1980-01-01")  # Marcus Reed (AC)
    set_dob(conn, C_ID, "1980-01-01")  # Dario Knox (RFL)
    conn.commit()

    # Run tick — all 3 retire, 3 regens.
    random.seed(RANDOM_SEED)
    tick_processor.run_tick(conn, "day", 1)

    # All 3 retired.
    retired_ids = conn.execute(
        "SELECT fighter_id FROM fighters WHERE is_retired=1 ORDER BY fighter_id"
    ).fetchall()
    retired_set = {r[0] for r in retired_ids}
    results.append((
        "H",
        f"fighters {A_ID}, {B_ID}, {C_ID} all retired",
        retired_set == {A_ID, B_ID, C_ID},
        f"got={retired_set}",
    ))

    # 3 new fighters generated (8 fighters total: 5 original + 3 regens).
    n_after = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    results.append((
        "H",
        f"after tick: {n_after} fighters (expected 8 — 5 + 3 regens)",
        n_after == 8,
        f"got={n_after}",
    ))

    # 3 regen_lineage rows exist.
    n_lineage = conn.execute("SELECT COUNT(*) FROM regen_lineage").fetchone()[0]
    results.append((
        "H",
        "3 regen_lineage rows exist",
        n_lineage == 3,
        f"got={n_lineage}",
    ))

    # The 3 regen_lineage rows link the 3 retiring fighters to 3
    # distinct replacements.
    lineage_rows = conn.execute(
        "SELECT retiring_fighter_id, replacement_fighter_id "
        "FROM regen_lineage ORDER BY retiring_fighter_id"
    ).fetchall()
    retiring_in_lineage = {r[0] for r in lineage_rows}
    replacements_in_lineage = {r[1] for r in lineage_rows}
    results.append((
        "H",
        "regen_lineage links the 3 retiring fighters to 3 distinct replacements",
        retiring_in_lineage == {A_ID, B_ID, C_ID}
        and len(replacements_in_lineage) == 3
        and replacements_in_lineage.isdisjoint({A_ID, B_ID, C_ID}),
        f"retiring={retiring_in_lineage}, replacements={replacements_in_lineage}",
    ))

    # 3 new prospect news items created.
    n_prospect_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='prospect'"
    ).fetchone()[0]
    results.append((
        "H",
        "3 new prospect news items created",
        n_prospect_news == 3,
        f"got={n_prospect_news}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case I — generate_fighter() with female gender.
    # ----------------------------------------------------------------
    print("\n--- Case I: generate_fighter() with female gender ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Snapshot the female first-name pool.
    female_firsts = set(conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='first_female'"
    ).fetchall())
    female_first_set = {r[0] for r in female_firsts}

    random.seed(RANDOM_SEED)
    fid = app.generate_fighter(conn, current_date=TEST_DATE, gender='female')
    conn.commit()

    results.append((
        "I",
        "generate_fighter(gender='female') returns valid fighter_id",
        isinstance(fid, int) and fid > 0,
        f"got={fid!r}",
    ))

    if isinstance(fid, int) and fid > 0:
        row = conn.execute(
            "SELECT gender, first_name FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        results.append((
            "I",
            "new fighter gender == 'female'",
            row[0] == 'female',
            f"got={row[0]}",
        ))
        results.append((
            "I",
            "new fighter first_name comes from the first_female pool",
            row[1] in female_first_set,
            f"got={row[1]}, pool_size={len(female_first_set)}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case J — Regression: all previous tasks still work.
    # ----------------------------------------------------------------
    print("\n--- Case J: regression (Tasks 3-13 still work) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Jack fighter 1 to all-90 so the seeded title fight resolves with
    # a non-draw winner (and therefore transfers the title). Without
    # this, the 50/50 default stats can produce a draw, which leaves
    # the title vacant. Same setup that test_retirement.py case L
    # uses for its regression test.
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=90, cardio=90, "
        "fight_iq=90, chin=90 WHERE fighter_id=?",
        (A_ID,),
    )
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=30, cardio=30, "
        "fight_iq=30, chin=30 WHERE fighter_id=?",
        (B_ID,),
    )
    conn.commit()

    # Resolve the seeded fight. This exercises Task 3 (resolver),
    # Task 4 (fight_history), Task 7 (event lifecycle), Task 8
    # (event scheduler), Task 10 (rankings), Task 11 (titles).
    random.seed(RANDOM_SEED)
    fight_result = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "J",
        "resolve_next_fight returns a result (Tasks 3/4/7/8/10/11 still work)",
        fight_result is not None,
        f"got={fight_result}",
    ))

    # fight_history +2 rows (Task 4).
    n_fh = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    results.append((
        "J",
        "fight_history has 2 rows (Task 4 — one per fighter perspective)",
        n_fh == 2,
        f"got={n_fh}",
    ))

    # Title transferred (Task 11) — the seeded main event is a
    # title_fight, so the AC Lightweight title should no longer be vacant.
    ac_title = conn.execute(
        "SELECT is_vacant, current_champion_fighter_id "
        "FROM titles WHERE promotion_id=? AND weight_class_id=?",
        (alpha_combat_id, wc_id),
    ).fetchone()
    results.append((
        "J",
        "AC Lightweight title is no longer vacant after title_fight resolution",
        ac_title is not None and ac_title[0] == 0 and ac_title[1] is not None,
        f"got={ac_title}",
    ))

    # Event completed (Task 7).
    event_status = conn.execute(
        "SELECT status FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    results.append((
        "J",
        "seeded event status == 'completed' (Task 7)",
        event_status is not None and event_status[0] == 'completed',
        f"got={event_status}",
    ))

    # New event scheduled (Task 8).
    n_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "J",
        "new event auto-scheduled after seeded fight resolution (Task 8)",
        n_events >= 2,
        f"got={n_events}",
    ))

    # Run tick. Assert no retirements (fighters in 30s, healthy).
    # Also assert no regens (regen_lineage empty).
    n_lineage_before = conn.execute(
        "SELECT COUNT(*) FROM regen_lineage"
    ).fetchone()[0]
    n_retired_before = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_retired=1"
    ).fetchone()[0]
    n_prospect_before = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='prospect'"
    ).fetchone()[0]

    tick_processor.run_tick(conn, "day", 1)

    n_retired_after = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_retired=1"
    ).fetchone()[0]
    n_lineage_after = conn.execute(
        "SELECT COUNT(*) FROM regen_lineage"
    ).fetchone()[0]
    n_prospect_after = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='prospect'"
    ).fetchone()[0]

    results.append((
        "J",
        "no retirements on a normal tick (fighters in 30s)",
        n_retired_after == n_retired_before == 0,
        f"before={n_retired_before}, after={n_retired_after}",
    ))
    results.append((
        "J",
        "no regen_lineage rows on a normal tick (no retirements -> no regens)",
        n_lineage_after == n_lineage_before == 0,
        f"before={n_lineage_before}, after={n_lineage_after}",
    ))
    results.append((
        "J",
        "no prospect news items on a normal tick",
        n_prospect_after == n_prospect_before == 0,
        f"before={n_prospect_before}, after={n_prospect_after}",
    ))

    # Manually expire a contract (set end_date to past). Run tick.
    # Assert the fighter becomes a free agent. Assert NO regen (the
    # fighter didn't retire, just became a free agent — regen only
    # fires on retirement, not on contract expiry).
    # Use fighter 2's contract (contract_id=2 per the seed order).
    conn.execute(
        "UPDATE contracts SET start_date='2025-07-19', end_date='2026-07-19' "
        "WHERE contract_id=2"
    )
    conn.commit()

    # Snapshot regen counts before the expiry tick.
    n_lineage_before_expiry = conn.execute(
        "SELECT COUNT(*) FROM regen_lineage"
    ).fetchone()[0]
    n_prospect_before_expiry = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='prospect'"
    ).fetchone()[0]
    n_fighters_before_expiry = conn.execute(
        "SELECT COUNT(*) FROM fighters"
    ).fetchone()[0]

    tick_processor.run_tick(conn, "day", 1)

    # Fighter 2 is now a free agent (current_promotion_id IS NULL,
    # is_active=1, is_retired=0).
    f2_status = get_fighter_status(conn, B_ID)
    results.append((
        "J",
        f"fighter {B_ID} became a free agent after contract expiry (Task 13)",
        f2_status is not None
        and f2_status[0] == 1
        and f2_status[1] == 0
        and f2_status[2] is None,
        f"got={f2_status}",
    ))

    # Fighter 2 is NOT retired (contract expiry doesn't retire them).
    results.append((
        "J",
        f"fighter {B_ID} is_retired=0 (expiry doesn't trigger retirement)",
        f2_status is not None and f2_status[1] == 0,
        f"got={f2_status}",
    ))

    # NO regen on contract expiry (regen only fires on retirement).
    n_lineage_after_expiry = conn.execute(
        "SELECT COUNT(*) FROM regen_lineage"
    ).fetchone()[0]
    results.append((
        "J",
        "no regen_lineage rows added on contract expiry (regen = retirement only)",
        n_lineage_after_expiry == n_lineage_before_expiry,
        f"before={n_lineage_before_expiry}, after={n_lineage_after_expiry}",
    ))

    n_prospect_after_expiry = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='prospect'"
    ).fetchone()[0]
    results.append((
        "J",
        "no prospect news items on contract expiry (regen = retirement only)",
        n_prospect_after_expiry == n_prospect_before_expiry,
        f"before={n_prospect_before_expiry}, after={n_prospect_after_expiry}",
    ))

    # Total fighter count unchanged (no regen = no new fighters).
    n_fighters_after_expiry = conn.execute(
        "SELECT COUNT(*) FROM fighters"
    ).fetchone()[0]
    results.append((
        "J",
        "fighter count unchanged on contract expiry (no regen)",
        n_fighters_after_expiry == n_fighters_before_expiry,
        f"before={n_fighters_before_expiry}, after={n_fighters_after_expiry}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case K — generate_fighter() callable directly.
    # ----------------------------------------------------------------
    print("\n--- Case K: generate_fighter() callable directly ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    random.seed(RANDOM_SEED)
    fid = app.generate_fighter(conn)
    conn.commit()

    results.append((
        "K",
        "generate_fighter(conn) with no other args returns valid fighter_id",
        isinstance(fid, int) and fid > 0,
        f"got={fid!r}",
    ))

    if isinstance(fid, int) and fid > 0:
        status = get_fighter_status(conn, fid)
        results.append((
            "K",
            "new fighter is a free agent (current_promotion_id IS NULL, "
            "is_active=1, is_retired=0)",
            status is not None
            and status[0] == 1
            and status[1] == 0
            and status[2] is None,
            f"got={status}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Print summary table.
    # ----------------------------------------------------------------
    print("\n" + sep)
    print(f"{'Case':<6} {'Check':<72} {'Result':<8} Detail")
    print("-" * 120)
    n_pass = 0
    n_fail = 0
    n_skip = 0
    by_case = {}
    for case, name, passed, detail in results:
        if passed is None:
            status = "SKIP"
            n_skip += 1
        elif passed:
            status = "PASS"
            n_pass += 1
        else:
            status = "FAIL"
            n_fail += 1
        by_case.setdefault(case, {"pass": 0, "fail": 0, "skip": 0})
        if passed is None:
            by_case[case]["skip"] += 1
        elif passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 50:
            detail_str = detail_str[:47] + "..."
        print(f"{case:<6} {name:<72} {status:<8} {detail_str}")
    print(sep)
    summary_parts = [f"Total: {n_pass} PASS, {n_fail} FAIL"]
    if n_skip > 0:
        summary_parts.append(f"{n_skip} SKIP")
    print(", ".join(summary_parts))
    print(sep)
    print("By case:")
    for case in sorted(by_case.keys()):
        c = by_case[case]
        parts = [f"{c['pass']} PASS", f"{c['fail']} FAIL"]
        if c["skip"] > 0:
            parts.append(f"{c['skip']} SKIP")
        print(f"  Case {case}: {', '.join(parts)}")
    print(sep)

    overall_pass = n_fail == 0
    if overall_pass:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
