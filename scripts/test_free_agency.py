#!/usr/bin/env python3
"""Acceptance test for Task ID 13 — Free agency + signings (fifth Stage 2 task).

Tests the free-agency system added in Task ID 13:

  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read dynamically — NO hardcoded version string).
     - schema_migrations contains a row starting with 'v1_8_0_'.
     - No new tables (still 34 — Task 13 adds no tables, only the
       existing `contracts`, `fighter_contracts`, and `fighters` are
       used).
     - All seeded contracts have status='active' and end_date='2027-07-20'.
  B. Contract expiry on tick:
     - Build fresh DB. Manually set one fighter's contract end_date to
       '2026-07-19' (before the current sim date of 2026-07-20).
     - Run tick_processor.run_tick(conn) (advances to 2026-07-21 or
       later — see D5 quirk note in test_retirement.py).
     - The contract's status is now 'expired'.
     - The fighter's current_promotion_id is NULL (free agent).
     - A free-agency news item was created.
  C. Multiple contracts expire on one tick:
     - Build fresh DB. Set all 5 fighter contracts' end_dates to
       '2026-07-19'.
     - Run tick. Assert all 5 contracts are 'expired'. Assert all 5
       fighters have current_promotion_id = NULL. Assert 5 free-agent
       news items created.
  D. Staff contract expiry:
     - Build fresh DB. Set the staff contract (Nina Cross, contract_id=3)
       end_date to '2026-07-19'.
     - Run tick. Assert the staff contract is 'expired'. Assert NO
       free-agent news item was created (only fighter contracts get
       free-agency news).
  E. sign_free_agent() function (success):
     - Build fresh DB. Manually set fighter 1's current_promotion_id=NULL
       (make them a free agent).
     - Call app.sign_free_agent(conn, fighter_id=1, promotion_id=2,
       start_date='2026-07-21') (sign to RFL).
     - Assert return value is a valid contract_id (int > 0).
     - Assert fighter 1's current_promotion_id is now 2.
     - Assert a new contract exists with status='active',
       start_date='2026-07-21', end_date='2027-07-21' (365 days later),
       salary=50000.0, exclusive_flag=1.
     - Assert a fighter_contracts row links the new contract to fighter 1.
     - Assert a news item was created: "John Vale signs with Rival Fight
       League".
  F. sign_free_agent() rejects non-free-agents:
     - Build fresh DB. Fighter 1 is signed to AC (current_promotion_id=1).
     - Call app.sign_free_agent(conn, fighter_id=1, promotion_id=2,
       start_date='2026-07-21').
     - Assert return value is None (fighter is already signed).
     - Assert fighter 1's current_promotion_id is still 1 (unchanged).
     - Assert no new contract created (count unchanged).
     - Assert no news item created.
  G. sign_free_agent() rejects retired fighters:
     - Build fresh DB. Set fighter 1's DOB to 1980-01-01 (age 46, will
       retire). Run tick to retire them.
     - Call app.sign_free_agent(conn, fighter_id=1, promotion_id=2,
       start_date='2026-07-21').
     - Assert return value is None (fighter is retired).
     - Assert no new contract created.
  H. get_free_agents_for_display() helper:
     - Build fresh DB. No free agents (all fighters signed). Assert
       helper returns empty list.
     - Manually set fighter 1's current_promotion_id=NULL. Assert helper
       returns 1 row with fighter 1's name.
     - Manually set fighter 2's current_promotion_id=NULL. Assert helper
       returns 2 rows.
     - Set fighter 1's is_active=0 (inactive). Assert helper returns 1
       row (fighter 2 only — inactive fighters are excluded).
     - Set fighter 2's is_retired=1. Assert helper returns 0 rows
       (retired fighters are excluded).
  I. Free Agents tab does NOT respect promotion filter:
     - This case is documented (not testable via a UI in headless mode).
       The helper signature does NOT take a promotion_filter parameter
       (unlike get_fighters_for_display and get_contracts_for_display).
       Free agents have NO promotion, so they're available to sign with
       ANY promotion. The Free Agents tab always shows all free agents
       regardless of the current_promotion_filter dropdown. This is
       intentional.
  J. Retired fighter's contract expiry doesn't make them a free agent:
     - Build fresh DB. Set fighter 1's DOB to 1980-01-01 (will retire).
       Set fighter 1's contract end_date to '2026-07-19' (will expire).
       Run tick.
     - Assert fighter 1 is retired (is_retired=1, is_active=0).
     - Assert fighter 1's contract is 'expired'.
     - Assert fighter 1's current_promotion_id is NOT NULL (they're
       retired, not a free agent — the expiry logic skips the
       current_promotion_id=NULL update for retired fighters).
     - Assert NO free-agent news item for fighter 1 (only retirement
       news).
  K. Regression: fight_history, rankings, titles, contracts, retirement,
     event lifecycle, event scheduler still work:
     - Build fresh DB. Resolve the seeded fight. Assert all Task 3-12
       side effects still work.
     - Run tick. Assert no contracts expired (end_date is 2027-07-20,
       well past the sim date). Assert no retirements (fighters in
       their 30s).
  L. UI smoke (optional, SKIPs in headless):
     - Try App(). If TclError, SKIP. Else: verify the Free Agents tab
       exists, verify it's empty (no free agents at seed), verify the
       Sign button exists. Destroy app.

Run from the project root:
    python3 scripts/test_free_agency.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each `app.resolve_next_fight()` call
  so the test is reproducible. The seed only pins down which random
  draws the resolver sees, not what it does with them.

D5 quirk note (from Task 12 worklog):
  tick_processor.py's `run_tick` uses `SELECT current_date, current_day,
  ... FROM simulation_clock WHERE clock_id=1` (bare column names, no
  table qualifier). SQLite resolves `current_date` to the built-in date
  FUNCTION (today's wall-clock date) instead of the simulation_clock.
  current_date COLUMN. This means after 1 tick, the clock column gets
  set to today+1 (e.g., 2026-07-22 if today is 2026-07-21), skipping
  the seeded date 2026-07-20 entirely. This is a pre-existing quirk
  that's OUTSIDE Task 13's scope. All assertions in this test are
  robust to the quirk because they don't assert specific clock values —
  they assert contract-status changes, fighter-promotion changes, and
  news-item creation, all of which happen on the new tick regardless
  of what specific date the clock ends up at.
"""
import random
import shutil
import sqlite3
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
DB_BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.db.bak"

# Make src/ importable so we can call sign_free_agent(),
# get_free_agents_for_display(), resolve_next_fight(),
# tick_processor._check_contract_expiry(), and (for case L) construct
# App() directly. Importing app.py pulls in tkinter — the import itself
# does not require a display (only tk.Tk() does), so this is safe in
# headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402
import tick_processor  # noqa: E402

# Lazy import of _tkinter — only needed inside case L's exception
# handler. Wrapped so that if _tkinter itself is unavailable (which
# would imply `import tkinter` already failed at module load time),
# we substitute a placeholder exception type so the except clause
# still works.
try:
    import _tkinter as _tkinter_mod
    _tkinter_TclError = _tkinter_mod.TclError
except Exception:
    _tkinter_TclError = type("_MissingTclError", (Exception,), {})

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read dynamically from
# build_db so this test does not need to be updated on every schema
# version bump — same pattern as test_retirement.py, test_rankings.py,
# test_contracts.py, test_titles.py, test_schema_versioning.py,
# test_fight_history.py). The brief explicitly says "MUST use
# build_db.CODE_SCHEMA_VERSION dynamically — do NOT hardcode '1.8.0'".
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

# Seeded contract IDs (from build_db + seed_data order):
#   contract 1 = fighter 1 (John Vale, AC)
#   contract 2 = fighter 2 (Marcus Reed, AC)
#   contract 3 = staff (Nina Cross, AC) — the staff contract
#   contract 4 = fighter 3 (Dario Knox, RFL)
#   contract 5 = fighter 4 (Eli Storm, RFL)
#   contract 6 = fighter 5 (Cole Briggs, RFL)
A_CONTRACT_ID = 1
B_CONTRACT_ID = 2
NINA_STAFF_CONTRACT_ID = 3
C_CONTRACT_ID = 4
D_CONTRACT_ID = 5
E_CONTRACT_ID = 6

# Seeded event date from src/seed_data.py — used for assertions.
SEEDED_EVENT_DATE = "2026-08-15"

# Seeded clock date + post-tick dates. Because of the D5 quirk
# (see module docstring), the clock column after 1 tick is today+1,
# not 2026-07-21. We don't assert specific clock values — we only
# use these in test setup where we pass an explicit date to
# _check_contract_expiry or to sign_free_agent.
SEEDED_CLOCK_DATE = "2026-07-20"

# Total tables at v1.8.0 (Task 13 adds NO new tables). This constant
# documents the expected count; if it changes, this test should fail
# (which would flag a regression — Task 13 was supposed to be table-
# free). Verified against the smoke test output.
# REMOVED Task ID 14 supervisor fix: EXPECTED_TABLE_COUNT = 34 was
# hardcoded and broke when Task 14 added 3 new tables. The table-count
# assertion has been removed from case A — see comment below.

# Seeded contract count: 5 fighter contracts + 1 staff contract = 6.
EXPECTED_SEEDED_CONTRACT_COUNT = 6


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_retirement.py / test_rankings.py /
    test_contracts.py / test_event_scheduler.py / test_titles.py so all
    tests share the same setup contract: a fresh DB with 2 promotions
    (Alpha Combat + Rival Fight League), 5 fighters (2 AC + 3 RFL),
    1 staff member (Nina Cross), 1 event, 1 title_fight (the seeded
    main event), 6 contracts (5 fighter + 1 staff), 5 rankings rows
    (all at 1000.0), 2 titles (both vacant — AC Lightweight + RFL
    Lightweight). All 5 fighters have is_retired=0 (none retirement-
    eligible at seed time).
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


def set_fighter_attrs(conn, fighter_id, attr_val, pers_val):
    """Set all 4 attributes and all 3 personality traits to the given values."""
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=?, cardio=?, fight_iq=?, "
        "chin=?, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (attr_val, attr_val, attr_val, attr_val, fighter_id),
    )
    conn.execute(
        "UPDATE fighter_personality SET aggression=?, composure=?, morale=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (pers_val, pers_val, pers_val, fighter_id),
    )


def set_dob(conn, fighter_id, dob):
    """Set a fighter's date_of_birth to the given 'YYYY-MM-DD' string."""
    conn.execute(
        "UPDATE fighters SET date_of_birth=? WHERE fighter_id=?",
        (dob, fighter_id),
    )


def set_career_health(conn, fighter_id, health):
    """Set a fighter's career_health (fighter_career.career_health)."""
    conn.execute(
        "UPDATE fighter_career SET career_health=? WHERE fighter_id=?",
        (health, fighter_id),
    )


def get_fighter_status(conn, fighter_id):
    """Return (is_active, is_retired, current_promotion_id) for the fighter."""
    row = conn.execute(
        "SELECT is_active, is_retired, current_promotion_id "
        "FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return tuple(row) if row else None


def expire_contract_end_date(conn, contract_id, end_date="2026-07-19"):
    """Set a contract's start/end dates so end_date is in the past.

    The contracts table has a CHECK constraint `end_date >= start_date`,
    so we can't just set end_date='2026-07-19' (which would be < the
    seeded start_date '2026-07-20'). We also set start_date to a year
    earlier so the constraint is satisfied. Used by cases B/C/D/J.
    """
    conn.execute(
        "UPDATE contracts SET start_date=?, end_date=? WHERE contract_id=?",
        ("2025-07-19", end_date, contract_id),
    )


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():

    # v2 retirement: probability-based. Force retirement for deterministic testing.
    import tick_processor as _tp_mod
    def _force_ret(age, career_health, loss_streak, total_fights, is_champion, wins, losses):
        return 1.0 if age >= 35 else 0.0
    _tp_mod._compute_retirement_probability = _force_ret
    sep = "=" * 80
    print(sep)
    print("TASK 13 FREE AGENCY ACCEPTANCE TEST")
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

    # migration name starts with 'v1_8_0_' (LIKE prefix check).
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

    # Table count check removed (Task ID 14 supervisor fix). The original
    # assertion checked that Task 13 added no new tables (EXPECTED_TABLE_COUNT=34).
    # That guarantee was correct for Task 13 but is now obsolete — Task 14
    # intentionally added 3 new tables (name_pools, regen_lineage,
    # fighter_memory_links), bringing the count to 37. Hardcoding any count
    # would break on every future schema change. The test's purpose is to
    # verify free agency behavior, not table count.

    # All seeded contracts have status='active' and end_date='2027-07-20'.
    bad_contracts = conn.execute(
        "SELECT contract_id, status, end_date FROM contracts "
        "WHERE status != 'active' OR end_date != '2027-07-20'"
    ).fetchall()
    results.append((
        "A",
        "all seeded contracts have status='active' and end_date='2027-07-20'",
        len(bad_contracts) == 0,
        f"bad={bad_contracts}",
    ))

    # Total contract count is 6 (5 fighter + 1 staff).
    n_contracts = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    results.append((
        "A",
        f"seeded contract count == {EXPECTED_SEEDED_CONTRACT_COUNT}",
        n_contracts == EXPECTED_SEEDED_CONTRACT_COUNT,
        f"got={n_contracts}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case B — Contract expiry on tick (single fighter contract).
    # ----------------------------------------------------------------
    print("\n--- Case B: contract expiry on tick (single fighter contract) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set fighter 1's contract (contract_id=1) end_date to 2026-07-19
    # (before the current sim date of 2026-07-20).
    expire_contract_end_date(conn, A_CONTRACT_ID, "2026-07-19")
    conn.commit()

    # Capture pre-tick state for comparison.
    pre_status = conn.execute(
        "SELECT status FROM contracts WHERE contract_id=?", (A_CONTRACT_ID,)
    ).fetchone()[0]
    pre_promo = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    pre_news_count = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]
    results.append((
        "B",
        "pre-tick: contract status='active', fighter signed, no signing news",
        pre_status == "active" and pre_promo == ALPHA_COMBAT_ID
        and pre_news_count == 0,
        f"status={pre_status}, promo={pre_promo}, news={pre_news_count}",
    ))

    # Run one tick. Due to the D5 quirk the clock column will become
    # today+1 (e.g., 2026-07-22 if today is 2026-07-21) — but the
    # contract-expiry logic uses the NEW sim date, which is well past
    # 2026-07-19, so the contract will expire regardless.
    tick_processor.run_tick(conn)

    # Contract status is now 'expired'.
    post_status = conn.execute(
        "SELECT status FROM contracts WHERE contract_id=?",
        (A_CONTRACT_ID,),
    ).fetchone()[0]
    results.append((
        "B",
        f"contract {A_CONTRACT_ID} status='expired' after tick",
        post_status == "expired",
        f"got={post_status}",
    ))

    # Fighter 1's current_promotion_id is NULL (free agent).
    post_promo = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "B",
        f"fighter {A_ID} current_promotion_id=NULL (free agent) after tick",
        post_promo is None,
        f"got={post_promo}",
    ))

    # A free-agency news item was created.
    free_agency_news = conn.execute(
        "SELECT headline FROM news_items "
        "WHERE topic='signing' AND headline LIKE '%free agent%' "
        "AND fighter_id=?",
        (A_ID,),
    ).fetchall()
    results.append((
        "B",
        f"free-agency news item created for fighter {A_ID}",
        len(free_agency_news) == 1,
        f"got={free_agency_news}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case C — Multiple contracts expire on one tick.
    # ----------------------------------------------------------------
    print("\n--- Case C: multiple contracts expire on one tick ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set all 5 fighter contracts' end_dates to 2026-07-19. The staff
    # contract (Nina Cross) is left alone (case D tests staff expiry
    # separately).
    for cid in (A_CONTRACT_ID, B_CONTRACT_ID, C_CONTRACT_ID,
                D_CONTRACT_ID, E_CONTRACT_ID):
        expire_contract_end_date(conn, cid, "2026-07-19")
    conn.commit()

    tick_processor.run_tick(conn)

    # All 5 fighter contracts are 'expired'.
    expired_fighter_contracts = conn.execute(
        "SELECT contract_id FROM contracts "
        "WHERE status='expired' AND contract_target_type='fighter' "
        "ORDER BY contract_id"
    ).fetchall()
    results.append((
        "C",
        "all 5 fighter contracts are 'expired' after tick",
        len(expired_fighter_contracts) == 5,
        f"got={len(expired_fighter_contracts)} contracts: "
        f"{[r[0] for r in expired_fighter_contracts]}",
    ))

    # All 5 fighters have current_promotion_id = NULL.
    n_free_agents = conn.execute(
        "SELECT COUNT(*) FROM fighters "
        "WHERE current_promotion_id IS NULL "
        "AND is_active=1 AND is_retired=0"
    ).fetchone()[0]
    results.append((
        "C",
        "all 5 fighters have current_promotion_id=NULL (free agents)",
        n_free_agents == 5,
        f"got={n_free_agents}",
    ))

    # 5 free-agent news items created.
    n_fa_news = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='signing' AND headline LIKE '%free agent%'"
    ).fetchone()[0]
    results.append((
        "C",
        "5 free-agent news items created",
        n_fa_news == 5,
        f"got={n_fa_news}",
    ))

    # Staff contract (Nina Cross) is NOT expired (we didn't touch it).
    nina_status = conn.execute(
        "SELECT status FROM contracts WHERE contract_id=?",
        (NINA_STAFF_CONTRACT_ID,),
    ).fetchone()[0]
    results.append((
        "C",
        f"staff contract {NINA_STAFF_CONTRACT_ID} still 'active' (untouched)",
        nina_status == "active",
        f"got={nina_status}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case D — Staff contract expiry.
    # ----------------------------------------------------------------
    print("\n--- Case D: staff contract expiry (Nina Cross) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set the staff contract (Nina Cross, contract_id=3) end_date to
    # 2026-07-19. Leave the fighter contracts alone.
    expire_contract_end_date(conn, NINA_STAFF_CONTRACT_ID, "2026-07-19")
    conn.commit()

    # Capture pre-tick signing-news count.
    pre_signing_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]

    tick_processor.run_tick(conn)

    # Staff contract is 'expired'.
    nina_status = conn.execute(
        "SELECT status FROM contracts WHERE contract_id=?",
        (NINA_STAFF_CONTRACT_ID,),
    ).fetchone()[0]
    results.append((
        "D",
        f"staff contract {NINA_STAFF_CONTRACT_ID} status='expired' after tick",
        nina_status == "expired",
        f"got={nina_status}",
    ))

    # NO free-agent news item was created (staff contracts don't get
    # free-agency news — only fighter contracts do).
    post_signing_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]
    results.append((
        "D",
        "no free-agency news item for staff contract expiry",
        post_signing_news == pre_signing_news,
        f"pre={pre_signing_news}, post={post_signing_news}",
    ))

    # No fighter contracts were affected (they're all still 'active').
    active_fighter_contracts = conn.execute(
        "SELECT COUNT(*) FROM contracts "
        "WHERE status='active' AND contract_target_type='fighter'"
    ).fetchone()[0]
    results.append((
        "D",
        "all 5 fighter contracts still 'active' (staff expiry doesn't affect them)",
        active_fighter_contracts == 5,
        f"got={active_fighter_contracts}",
    ))

    # All 5 fighters still have their current_promotion_id set (none
    # became free agents).
    n_free_agents = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE current_promotion_id IS NULL"
    ).fetchone()[0]
    results.append((
        "D",
        "no fighters became free agents (staff expiry doesn't affect fighters)",
        n_free_agents == 0,
        f"got={n_free_agents}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case E — sign_free_agent() function (success).
    # ----------------------------------------------------------------
    print("\n--- Case E: sign_free_agent() function (success) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Manually set fighter 1's current_promotion_id=NULL (make them a
    # free agent). This simulates what _check_contract_expiry would do
    # on a contract expiry.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()

    # Capture pre-sign state.
    pre_contract_count = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    pre_signing_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]

    # Sign fighter 1 to RFL (promotion_id=2) with start_date='2026-07-21'.
    contract_id = app.sign_free_agent(
        conn, fighter_id=A_ID, promotion_id=RFL_ID,
        start_date="2026-07-21",
    )
    conn.commit()

    # Return value is a valid contract_id (int > 0).
    results.append((
        "E",
        "sign_free_agent returns valid contract_id (int > 0)",
        isinstance(contract_id, int) and contract_id > 0,
        f"got={contract_id!r} (type={type(contract_id).__name__})",
    ))

    # Fighter 1's current_promotion_id is now 2 (RFL).
    post_promo = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "E",
        f"fighter {A_ID} current_promotion_id={RFL_ID} (RFL) after signing",
        post_promo == RFL_ID,
        f"got={post_promo}",
    ))

    # New contract exists with the correct fields.
    contract_row = conn.execute(
        "SELECT contract_target_type, promotion_id, start_date, end_date, "
        "salary, exclusive_flag, status FROM contracts WHERE contract_id=?",
        (contract_id,),
    ).fetchone()
    if contract_row:
        target_type, promo_id, start_date, end_date, salary, excl, status = contract_row
        results.append((
            "E",
            f"new contract {contract_id}: target_type='fighter', "
            f"promo={RFL_ID}, start='2026-07-21', end='2027-07-21', "
            f"salary=50000.0, exclusive=1, status='active'",
            (target_type == "fighter" and promo_id == RFL_ID
             and start_date == "2026-07-21" and end_date == "2027-07-21"
             and salary == 50000.0 and excl == 1 and status == "active"),
            f"got={contract_row}",
        ))
    else:
        results.append((
            "E",
            f"new contract {contract_id} exists",
            False,
            "contract row not found",
        ))

    # Fighter_contracts row links the new contract to fighter 1.
    fc_row = conn.execute(
        "SELECT fighter_id, contract_type FROM fighter_contracts "
        "WHERE contract_id=?",
        (contract_id,),
    ).fetchone()
    results.append((
        "E",
        f"fighter_contracts row links contract {contract_id} to fighter {A_ID}",
        fc_row is not None and fc_row[0] == A_ID and fc_row[1] == "standard",
        f"got={fc_row}",
    ))

    # Contract count increased by 1.
    post_contract_count = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    results.append((
        "E",
        "contract count increased by 1",
        post_contract_count == pre_contract_count + 1,
        f"pre={pre_contract_count}, post={post_contract_count}",
    ))

    # A signing news item was created: "John Vale signs with Rival Fight League".
    signing_news = conn.execute(
        "SELECT headline, fighter_id, promotion_id FROM news_items "
        "WHERE topic='signing' AND fighter_id=? AND promotion_id=? "
        "AND headline LIKE '%signs%'",
        (A_ID, RFL_ID),
    ).fetchall()
    results.append((
        "E",
        f"signing news item created (fighter {A_ID}, promo {RFL_ID})",
        len(signing_news) == 1,
        f"got={signing_news}",
    ))

    # The headline mentions "John Vale" and "Rival Fight League".
    if signing_news:
        headline = signing_news[0][0]
        results.append((
            "E",
            "signing news headline contains 'John Vale' and 'Rival Fight League'",
            "John Vale" in headline and "Rival Fight League" in headline,
            f"headline={headline!r}",
        ))
    else:
        results.append((
            "E",
            "signing news headline contains 'John Vale' and 'Rival Fight League'",
            False,
            "no signing news found",
        ))

    # Signing news count increased by 1 (only the signing news, no
    # free-agency news because we set current_promotion_id=NULL directly
    # without going through _check_contract_expiry).
    post_signing_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]
    results.append((
        "E",
        "signing news count increased by 1",
        post_signing_news == pre_signing_news + 1,
        f"pre={pre_signing_news}, post={post_signing_news}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case F — sign_free_agent() rejects non-free-agents.
    # ----------------------------------------------------------------
    print("\n--- Case F: sign_free_agent() rejects non-free-agents ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Fighter 1 is signed to AC (current_promotion_id=1) — not a free
    # agent. (This is the seed state.)

    pre_contract_count = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    pre_signing_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]

    # Try to sign fighter 1 to RFL. Should return None.
    contract_id = app.sign_free_agent(
        conn, fighter_id=A_ID, promotion_id=RFL_ID,
        start_date="2026-07-21",
    )
    conn.commit()

    results.append((
        "F",
        "sign_free_agent returns None for already-signed fighter",
        contract_id is None,
        f"got={contract_id!r}",
    ))

    # Fighter 1's current_promotion_id is still 1 (unchanged).
    post_promo = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "F",
        f"fighter {A_ID} current_promotion_id unchanged (still {ALPHA_COMBAT_ID})",
        post_promo == ALPHA_COMBAT_ID,
        f"got={post_promo}",
    ))

    # No new contract created (count unchanged).
    post_contract_count = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    results.append((
        "F",
        "no new contract created (count unchanged)",
        post_contract_count == pre_contract_count,
        f"pre={pre_contract_count}, post={post_contract_count}",
    ))

    # No news item created (signing news count unchanged).
    post_signing_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='signing'"
    ).fetchone()[0]
    results.append((
        "F",
        "no news item created (signing news count unchanged)",
        post_signing_news == pre_signing_news,
        f"pre={pre_signing_news}, post={post_signing_news}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case G — sign_free_agent() rejects retired fighters.
    # ----------------------------------------------------------------
    print("\n--- Case G: sign_free_agent() rejects retired fighters ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set fighter 1's DOB to 1980-01-01 (age 46, will retire). Run
    # tick to retire them. Note: the tick will also expire fighter 1's
    # contract if its end_date is in the past — but the seeded end_date
    # is 2027-07-20, so the contract stays 'active'. Only the retirement
    # fires. However, since the fighter is retired, the contract expiry
    # logic would skip the current_promotion_id=NULL update (case J
    # verifies this). For this case, we just want fighter 1 to be
    # retired — we don't care about the contract.
    set_dob(conn, A_ID, "1980-07-21")
    conn.commit()
    tick_processor.run_tick(conn)

    # Verify fighter 1 is retired.
    status = get_fighter_status(conn, A_ID)
    results.append((
        "G",
        f"fighter {A_ID} is retired (is_retired=1, is_active=0) before signing",
        status is not None and status[0] == 0 and status[1] == 1,
        f"got={status}",
    ))

    pre_contract_count = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]

    # Try to sign retired fighter 1 to RFL. Should return None.
    contract_id = app.sign_free_agent(
        conn, fighter_id=A_ID, promotion_id=RFL_ID,
        start_date="2026-07-21",
    )
    conn.commit()

    results.append((
        "G",
        "sign_free_agent returns None for retired fighter",
        contract_id is None,
        f"got={contract_id!r}",
    ))

    # No new contract created (count unchanged).
    post_contract_count = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    results.append((
        "G",
        "no new contract created (count unchanged)",
        post_contract_count == pre_contract_count,
        f"pre={pre_contract_count}, post={post_contract_count}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case H — get_free_agents_for_display() helper.
    # ----------------------------------------------------------------
    print("\n--- Case H: get_free_agents_for_display() helper ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # No free agents at seed (all fighters signed).
    rows = app.get_free_agents_for_display(conn)
    results.append((
        "H",
        "no free agents at seed (helper returns empty list)",
        rows == [],
        f"got={len(rows)} rows: {rows}",
    ))

    # Set fighter 1's current_promotion_id=NULL. Helper returns 1 row.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()
    rows = app.get_free_agents_for_display(conn)
    results.append((
        "H",
        f"1 free agent after setting fighter {A_ID} current_promotion_id=NULL",
        len(rows) == 1 and rows[0][0] == A_ID,
        f"got={len(rows)} rows: {rows}",
    ))

    # The row contains the fighter's name.
    if rows:
        name = rows[0][1]
        results.append((
            "H",
            f"free agent row contains fighter name ('John Vale')",
            name == "John Vale",
            f"got={name!r}",
        ))
    else:
        results.append((
            "H",
            "free agent row contains fighter name ('John Vale')",
            False,
            "no rows to check",
        ))

    # Set fighter 2's current_promotion_id=NULL. Helper returns 2 rows.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=?",
        (B_ID,),
    )
    conn.commit()
    rows = app.get_free_agents_for_display(conn)
    results.append((
        "H",
        f"2 free agents after setting fighter {B_ID} current_promotion_id=NULL",
        len(rows) == 2,
        f"got={len(rows)} rows: {[r[0] for r in rows]}",
    ))

    # Set fighter 1's is_active=0 (inactive). Helper returns 1 row
    # (fighter 2 only — inactive fighters are excluded).
    conn.execute(
        "UPDATE fighters SET is_active=0 WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()
    rows = app.get_free_agents_for_display(conn)
    results.append((
        "H",
        f"1 free agent after setting fighter {A_ID} is_active=0 (inactive excluded)",
        len(rows) == 1 and rows[0][0] == B_ID,
        f"got={len(rows)} rows: {[r[0] for r in rows]}",
    ))

    # Set fighter 2's is_retired=1. Helper returns 0 rows (retired
    # fighters are excluded).
    conn.execute(
        "UPDATE fighters SET is_retired=1 WHERE fighter_id=?",
        (B_ID,),
    )
    conn.commit()
    rows = app.get_free_agents_for_display(conn)
    results.append((
        "H",
        f"0 free agents after setting fighter {B_ID} is_retired=1 (retired excluded)",
        rows == [],
        f"got={len(rows)} rows: {rows}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case I — Free Agents tab does NOT respect promotion filter.
    # ----------------------------------------------------------------
    print("\n--- Case I: Free Agents tab does NOT respect promotion filter ---")
    # This case is documented rather than runtime-tested. The helper
    # signature does NOT take a promotion_filter parameter (unlike
    # get_fighters_for_display and get_contracts_for_display), which is
    # the structural proof that the Free Agents tab does NOT respect
    # the promotion filter. Free agents have NO promotion, so they're
    # available to sign with ANY promotion.

    # Inspect the helper's signature.
    import inspect
    sig = inspect.signature(app.get_free_agents_for_display)
    params = list(sig.parameters.keys())
    results.append((
        "I",
        "get_free_agents_for_display signature has no promotion_filter param",
        params == ["conn"],
        f"params={params}",
    ))

    # Compare to get_fighters_for_display (which DOES take a filter).
    sig_f = inspect.signature(app.get_fighters_for_display)
    params_f = list(sig_f.parameters.keys())
    results.append((
        "I",
        "get_fighters_for_display signature DOES take a promotion_filter param",
        "promotion_filter" in params_f,
        f"params={params_f}",
    ))

    # Runtime check: build a fresh DB, set fighter 1 as a free agent,
    # call the helper, verify it returns the fighter regardless of what
    # promotion filter "would be" applied (the helper doesn't even know
    # about a filter — it always returns all free agents).
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=?",
        (A_ID,),
    )
    conn.commit()
    rows = app.get_free_agents_for_display(conn)
    results.append((
        "I",
        "helper returns the free agent regardless of any 'filter' concept",
        len(rows) == 1 and rows[0][0] == A_ID,
        f"got={len(rows)} rows",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case J — Retired fighter's contract expiry doesn't make
    # them a free agent.
    # ----------------------------------------------------------------
    print("\n--- Case J: retired fighter's contract expiry doesn't make "
          "them a free agent ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set fighter 1's DOB to 1980-01-01 (age 46, will retire on tick).
    # AND set fighter 1's contract end_date to 2026-07-19 (will expire
    # on tick). Both retirement and contract expiry will fire on the
    # same tick.
    set_dob(conn, A_ID, "1980-07-21")
    expire_contract_end_date(conn, A_CONTRACT_ID, "2026-07-19")
    conn.commit()

    tick_processor.run_tick(conn)

    # Fighter 1 is retired.
    status = get_fighter_status(conn, A_ID)
    results.append((
        "J",
        f"fighter {A_ID} is retired (is_retired=1, is_active=0)",
        status is not None and status[0] == 0 and status[1] == 1,
        f"got={status}",
    ))

    # Fighter 1's contract is 'expired'.
    contract_status = conn.execute(
        "SELECT status FROM contracts WHERE contract_id=?",
        (A_CONTRACT_ID,),
    ).fetchone()[0]
    results.append((
        "J",
        f"fighter {A_ID}'s contract is 'expired'",
        contract_status == "expired",
        f"got={contract_status}",
    ))

    # Fighter 1's current_promotion_id is NOT NULL (they're retired,
    # not a free agent — the expiry logic skips the
    # current_promotion_id=NULL update for retired fighters).
    post_promo = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "J",
        f"fighter {A_ID} current_promotion_id is NOT NULL (retired, not free agent)",
        post_promo is not None,
        f"got={post_promo}",
    ))

    # No free-agent news item for fighter 1 (only retirement news).
    fa_news = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='signing' AND headline LIKE '%free agent%' "
        "AND fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "J",
        f"no free-agent news item for fighter {A_ID} (only retirement news)",
        fa_news == 0,
        f"got={fa_news}",
    ))

    # A retirement news item WAS created (verify _check_retirements ran).
    ret_news = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='retirement' AND fighter_id=?",
        (A_ID,),
    ).fetchone()[0]
    results.append((
        "J",
        f"retirement news item WAS created for fighter {A_ID} "
        f"(retirement still fires even though contract also expired)",
        ret_news == 1,
        f"got={ret_news}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case K — Regression: Tasks 3-12 side effects still work +
    # no spurious contract expirations / retirements on a normal tick.
    # ----------------------------------------------------------------
    print("\n--- Case K: regression (Tasks 3-12 still work, no spurious "
          "expirations) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Jack fighter 1 to all-90 and fighter 2 to all-30 so the seeded
    # title fight resolves with a non-draw winner (and therefore
    # transfers the title + updates the rankings). Without this, the
    # 50/50 default stats can produce a draw, which leaves the title
    # vacant and the rankings unchanged (draws produce zero ELO delta
    # when both fighters start at the same rating). Same setup that
    # test_retirement.py case L uses for its regression test.
    set_fighter_attrs(conn, A_ID, 90, 50)
    set_fighter_attrs(conn, B_ID, 30, 50)
    conn.commit()

    # Resolve the seeded fight (Task 3-11 side effects fire).
    random.seed(RANDOM_SEED)
    fight_id = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "K",
        "resolve_next_fight returns a fight_id (Tasks 3-11 still work)",
        fight_id is not None,
        f"got={fight_id}",
    ))

    # fight_history has 2 new rows (one per fighter).
    n_fh = conn.execute(
        "SELECT COUNT(*) FROM fight_history WHERE fight_id=?",
        (fight_id,),
    ).fetchone()[0]
    results.append((
        "K",
        "fight_history has 2 new rows for the resolved fight (Task 4)",
        n_fh == 2,
        f"got={n_fh}",
    ))

    # The event transitioned to 'completed' (Task 7 — only 1 fight on
    # the seeded card, so it goes scheduled -> completed in one step).
    event_status = conn.execute(
        "SELECT status FROM events WHERE event_id="
        "(SELECT event_id FROM fights WHERE fight_id=?)",
        (fight_id,),
    ).fetchone()[0]
    results.append((
        "K",
        "seeded event transitioned to 'completed' (Task 7)",
        event_status == "completed",
        f"got={event_status}",
    ))

    # A new event was auto-scheduled (Task 8 — when an event completes,
    # schedule_next_event fires).
    n_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    results.append((
        "K",
        "new event auto-scheduled (Task 8) — events count is 2",
        n_events == 2,
        f"got={n_events}",
    ))

    # Rankings were updated (Task 10 — both fighters' ELO ratings
    # changed from the seed 1000.0; with a non-draw outcome, both
    # ratings move).
    rankings_at_1000 = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE rating=1000.0 "
        "AND promotion_id=?",
        (ALPHA_COMBAT_ID,),
    ).fetchone()[0]
    results.append((
        "K",
        "rankings updated (no AC rows still at 1000.0 after non-draw)",
        rankings_at_1000 == 0,
        f"got={rankings_at_1000} rows still at 1000.0",
    ))

    # The seeded title fight transferred the belt to the winner (Task 11).
    n_vacant = conn.execute(
        "SELECT COUNT(*) FROM titles WHERE is_vacant=1 AND promotion_id=?",
        (ALPHA_COMBAT_ID,),
    ).fetchone()[0]
    results.append((
        "K",
        "AC Lightweight title is no longer vacant (Task 11 — title transferred)",
        n_vacant == 0,
        f"got={n_vacant} vacant",
    ))

    # Run tick. No contracts should expire (end_date 2027-07-20 is well
    # past the sim date). No retirements (fighters in their early 30s).
    pre_active_contracts = conn.execute(
        "SELECT COUNT(*) FROM contracts WHERE status='active'"
    ).fetchone()[0]
    pre_retired = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_retired=1"
    ).fetchone()[0]

    tick_processor.run_tick(conn)

    post_active_contracts = conn.execute(
        "SELECT COUNT(*) FROM contracts WHERE status='active'"
    ).fetchone()[0]
    post_retired = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_retired=1"
    ).fetchone()[0]
    results.append((
        "K",
        "no contracts expired on a normal tick (end_date 2027-07-20 is far future)",
        post_active_contracts == pre_active_contracts,
        f"pre={pre_active_contracts}, post={post_active_contracts}",
    ))
    results.append((
        "K",
        "no retirements on a normal tick (fighters in their 30s)",
        post_retired == pre_retired == 0,
        f"pre={pre_retired}, post={post_retired}",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case L — UI smoke test (optional, SKIPs cleanly in headless).
    # ----------------------------------------------------------------
    print("\n--- Case L: UI smoke test ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Close the test conn before constructing App() — App() opens its
    # own conn, and having two connections to the same SQLite file is
    # fine but redundant.
    conn.close()

    l_skipped = False
    try:
        app_instance = app.App()
    except _tkinter_TclError as e:
        print(f"  SKIP — no display available ({type(e).__name__})")
        l_skipped = True
    except Exception as e:
        results.append((
            "L",
            "App() constructs without crashing",
            False,
            f"App() crashed: {type(e).__name__}: {e}",
        ))
        l_skipped = True  # nothing else to test in case L
    else:
        try:
            # Verify self.free_agents Treeview widget exists.
            has_fa_widget = hasattr(app_instance, "free_agents")
            results.append((
                "L",
                "App() has self.free_agents Treeview widget",
                has_fa_widget,
                f"hasattr={has_fa_widget}",
            ))

            # Verify the Sign button exists.
            has_sign_button = hasattr(app_instance, "sign_button")
            results.append((
                "L",
                "App() has self.sign_button widget",
                has_sign_button,
                f"hasattr={has_sign_button}",
            ))

            # Free Agents tree is empty at seed (no free agents — all
            # 5 fighters are signed to their respective promotions).
            n_fa = len(app_instance.free_agents.get_children())
            results.append((
                "L",
                "Free Agents tree is empty at seed (no free agents)",
                n_fa == 0,
                f"got={n_fa}",
            ))

            # The right-pane notebook has 4 tabs (News & Commentary,
            # Contracts, Rankings, Free Agents).
            tabs = app_instance.nametowidget(
                app_instance.free_agents.master.master
            )
            # tabs should be the ttk.Notebook. .tabs() returns the list
            # of child tab window IDs; .tab(tab_id, 'text') returns the
            # tab's text label.
            try:
                tab_texts = []
                for tab_id in tabs.tabs():
                    tab_texts.append(tabs.tab(tab_id, "text"))
                results.append((
                    "L",
                    f"right-pane notebook has 4 tabs: "
                    f"News & Commentary, Contracts, Rankings, Free Agents",
                    len(tab_texts) == 4 and "Free Agents" in tab_texts,
                    f"got={tab_texts}",
                ))
            except Exception as e:
                results.append((
                    "L",
                    "right-pane notebook has 4 tabs (tab enumeration)",
                    False,
                    f"failed to enumerate tabs: {type(e).__name__}: {e}",
                ))

            # Manually set a free agent and refresh — Free Agents tree
            # should now have 1 row.
            app_instance.conn.execute(
                "UPDATE fighters SET current_promotion_id=NULL "
                "WHERE fighter_id=?",
                (A_ID,),
            )
            app_instance.conn.commit()
            app_instance.refresh_all()
            n_fa_after = len(app_instance.free_agents.get_children())
            results.append((
                "L",
                f"Free Agents tree has 1 row after setting fighter {A_ID} "
                f"as a free agent",
                n_fa_after == 1,
                f"got={n_fa_after}",
            ))

            # The Treeview item iid is the fighter_id (so the Sign
            # button can read it directly from selection[0]).
            children = app_instance.free_agents.get_children()
            if children:
                iid = children[0]
                results.append((
                    "L",
                    f"Free Agents tree item iid is the fighter_id ('{A_ID}')",
                    iid == str(A_ID),
                    f"got={iid!r}",
                ))
            else:
                results.append((
                    "L",
                    "Free Agents tree item iid is the fighter_id",
                    False,
                    "no children to check",
                ))

            # Reset fighter 1's promotion so we don't leave the DB in
            # a weird state for any subsequent inspection.
            app_instance.conn.execute(
                "UPDATE fighters SET current_promotion_id=? "
                "WHERE fighter_id=?",
                (ALPHA_COMBAT_ID, A_ID),
            )
            app_instance.conn.commit()
        finally:
            try:
                app_instance.destroy()
            except Exception:
                pass

    if l_skipped:
        # Append SKIP entries for the case-L checks so the summary
        # table reflects that they were not run.
        for name in (
            "App() has self.free_agents Treeview widget",
            "App() has self.sign_button widget",
            "Free Agents tree is empty at seed (no free agents)",
            "right-pane notebook has 4 tabs",
            "Free Agents tree has 1 row after setting fighter 1 as a free agent",
            "Free Agents tree item iid is the fighter_id",
        ):
            results.append(("L", name, None, "skipped — no display available"))

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
