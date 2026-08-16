#!/usr/bin/env python3
"""Acceptance test for Task ID 9 — Contracts (first Stage 2 task).

Tests the contracts group added in Task ID 9:

  A. Schema:
     - schema_meta.schema_version == '1.4.0'
     - schema_migrations contains 'v1_4_0_add_contracts'
     - All 4 new tables exist: contracts, fighter_contracts,
       staff_contracts, broadcast_contracts
     - contracts table has 12 expected columns
     - CHECK constraints fire on:
         * contract_target_type='invalid'
         * end_date < start_date
         * salary < 0
         * status='invalid_status'
         * exclusive_flag=2 (not 0 or 1)
  B. Seed:
     - 5 fighter_contracts (2 AC + 3 RFL)
     - 1 staff_contract (Nina Cross)
     - 0 broadcast_contracts
     - 6 total contracts
     - Each fighter_contract's contract.promotion_id matches the
       fighter's current_promotion_id
     - All contracts: start_date='2026-07-20', end_date='2027-07-20',
       salary=50000.0, exclusive_flag=1, status='active'
     - All fighter_contracts: contract_type='standard'
     - The 1 staff_contract: contract_role='commentator'
  C. get_contracts_for_display() helper:
     - No filter: returns 6 rows
     - AC filter: returns 3 rows (2 fighters + 1 staff)
     - RFL filter: returns 3 rows (3 RFL fighters, no staff)
     - Invalid promotion_id=99999: returns empty list (no crash)
     - Each row is a 7-tuple (contractor_name, contract_target_type,
       start_date, end_date, salary, exclusive_flag, status)
  D. UI smoke test (optional, SKIPs cleanly in headless):
     - App() constructs without crashing
     - self.contracts Treeview widget exists
     - Set current_promotion_filter=AC, refresh, assert 3 entries
     - Set current_promotion_filter=None, refresh, assert 6 entries
  E. Regression: fight_history, event lifecycle, event scheduler
     still work:
     - Call resolve_next_fight(conn)
     - Assert fight_history has 2 new rows
     - Assert events.status for seeded event is 'completed'
     - Assert a new event was auto-scheduled (Task 8 hook)
     - Assert contracts table is unchanged (no new contracts created
       by fight resolution — Task 13 will add contract effects)

Run from the project root:
    python3 scripts/test_contracts.py

Exit code 0 = all PASS, 1 = any FAIL (case D SKIP is not a fail).
The script rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each `app.resolve_next_fight()` call
  so the test is reproducible. The seed only pins down which random
  draws the resolver sees, not what it does with them.
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
# Backup path used to preserve case A/B/C's DB state across case E's
# independent DB rebuild (case E rebuilds the DB from scratch).
DB_BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.case_abc_backup.db"

# Make src/ importable so we can call get_contracts_for_display() and
# (for case D) construct App() directly without going through the
# Tkinter UI. Importing app.py pulls in tkinter — the import itself
# does not require a display (only tk.Tk() does), so this is safe in
# headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name (dynamic — Task ID 10 supervisor fix).
# Reading CODE_SCHEMA_VERSION from build_db means this test does not need
# to be updated on every schema version bump. The migration name follows
# the convention v{MAJOR}_{MINOR}_{PATCH}_{desc} - we use a LIKE prefix
# so the test doesn't break when the description suffix changes per task
# (e.g., _add_contracts, _add_rankings, _add_titles).
EXPECTED_SCHEMA_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_SCHEMA_VERSION.replace('.', '_')}_"

# Expected contract defaults from seed_data.py.
# HW8.1: contracts use build_db.GAME_START_DATE (= "2026-01-01" since
# HW2.3) — was "2026-07-20" before HW2.3. The test was stale.
EXPECTED_START_DATE = "2026-01-01"
EXPECTED_END_DATE = "2027-01-01"  # start_date + 365 days
EXPECTED_SALARY = 50000.0
EXPECTED_EXCLUSIVE_FLAG = 1
EXPECTED_STATUS = "active"
EXPECTED_FIGHTER_CONTRACT_TYPE = "standard"
EXPECTED_STAFF_ROLE = "commentator"

# Expected contract counts after seeding.
EXPECTED_FIGHTER_CONTRACTS = 5  # 2 AC + 3 RFL
EXPECTED_STAFF_CONTRACTS = 1    # Nina Cross
EXPECTED_BROADCAST_CONTRACTS = 0
EXPECTED_TOTAL_CONTRACTS = 6    # 5 fighter + 1 staff


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_promotion_filter.py / test_event_scheduler.py
    so all tests share the same setup contract: a fresh DB with
    2 promotions (Alpha Combat + Rival Fight League), 5 fighters
    (2 AC + 3 RFL), 1 staff member (Nina Cross), 1 event, 1 fight,
    6 contracts (5 fighter + 1 staff).
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


# Lazy import of _tkinter — only needed inside case D's exception
# handler. Wrapped so that if _tkinter itself is unavailable (which
# would imply `import tkinter` already failed at module load time),
# we don't get a NameError on the isinstance() check.
try:
    import _tkinter as _tkinter_mod
    _tkinter_TclError = _tkinter_mod.TclError
except ImportError:
    _tkinter_TclError = type("_MissingTclError", (Exception,), {})


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK 9 CONTRACTS ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail).
    results = []

    # ----------------------------------------------------------------
    # Build a fresh DB. Used by cases A, B, C, D.
    # ----------------------------------------------------------------
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    rfl_id = get_promotion_id(conn, "Rival Fight League")

    print(f"Alpha Combat promotion_id   = {alpha_combat_id}")
    print(f"Rival Fight League promo_id = {rfl_id}")

    # ----------------------------------------------------------------
    # Test case A — Schema.
    # ----------------------------------------------------------------
    print("\n--- Case A: schema ---")

    # schema_meta.schema_version == '1.4.0'.
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        "A",
        f"schema_meta.schema_version == '{EXPECTED_SCHEMA_VERSION}'",
        sv is not None and sv[0] == EXPECTED_SCHEMA_VERSION,
        f"got={sv[0] if sv else None}",
    ))

    # schema_migrations contains a row for the current version's
    # migration (e.g., v1_4_0_add_contracts, v1_5_0_add_rankings, etc.).
    # Use a LIKE prefix so the test doesn't break on description changes.
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

    # All 4 new tables exist.
    for table_name in ("contracts", "fighter_contracts",
                        "staff_contracts", "broadcast_contracts"):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        results.append((
            "A",
            f"table '{table_name}' exists",
            exists is not None,
            f"found={exists}",
        ))

    # contracts table has the 12 expected columns.
    expected_cols = {
        "contract_id", "contract_target_type", "promotion_id",
        "start_date", "end_date", "salary", "bonus_structure",
        "buyout_clause", "exclusive_flag", "status",
        "created_at", "updated_at",
    }
    actual_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(contracts)"
    ).fetchall()}
    results.append((
        "A",
        f"contracts table has all {len(expected_cols)} expected columns",
        expected_cols.issubset(actual_cols),
        f"missing={expected_cols - actual_cols}, extra={actual_cols - expected_cols}",
    ))

    # CHECK constraint: contract_target_type='invalid' -> IntegrityError.
    try:
        conn.execute(
            "INSERT INTO contracts (contract_target_type, promotion_id, "
            "start_date, end_date) VALUES ('invalid', ?, '2026-01-01', '2026-12-31')",
            (alpha_combat_id,),
        )
        results.append((
            "A",
            "CHECK contract_target_type rejects 'invalid'",
            False,
            "INSERT succeeded but should have raised IntegrityError",
        ))
    except sqlite3.IntegrityError as e:
        results.append((
            "A",
            "CHECK contract_target_type rejects 'invalid'",
            True,
            f"raised IntegrityError: {e}",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK contract_target_type rejects 'invalid'",
            False,
            f"raised {type(e).__name__} (expected IntegrityError): {e}",
        ))

    # CHECK constraint: end_date < start_date -> IntegrityError.
    try:
        conn.execute(
            "INSERT INTO contracts (contract_target_type, promotion_id, "
            "start_date, end_date) VALUES ('fighter', ?, '2027-01-01', '2026-01-01')",
            (alpha_combat_id,),
        )
        results.append((
            "A",
            "CHECK end_date >= start_date rejects end < start",
            False,
            "INSERT succeeded but should have raised IntegrityError",
        ))
    except sqlite3.IntegrityError as e:
        results.append((
            "A",
            "CHECK end_date >= start_date rejects end < start",
            True,
            f"raised IntegrityError: {e}",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK end_date >= start_date rejects end < start",
            False,
            f"raised {type(e).__name__} (expected IntegrityError): {e}",
        ))

    # CHECK constraint: salary < 0 -> IntegrityError.
    try:
        conn.execute(
            "INSERT INTO contracts (contract_target_type, promotion_id, "
            "start_date, end_date, salary) VALUES "
            "('fighter', ?, '2026-01-01', '2026-12-31', -1.0)",
            (alpha_combat_id,),
        )
        results.append((
            "A",
            "CHECK salary >= 0 rejects salary=-1",
            False,
            "INSERT succeeded but should have raised IntegrityError",
        ))
    except sqlite3.IntegrityError as e:
        results.append((
            "A",
            "CHECK salary >= 0 rejects salary=-1",
            True,
            f"raised IntegrityError: {e}",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK salary >= 0 rejects salary=-1",
            False,
            f"raised {type(e).__name__} (expected IntegrityError): {e}",
        ))

    # CHECK constraint: status='invalid_status' -> IntegrityError.
    try:
        conn.execute(
            "INSERT INTO contracts (contract_target_type, promotion_id, "
            "start_date, end_date, status) VALUES "
            "('fighter', ?, '2026-01-01', '2026-12-31', 'invalid_status')",
            (alpha_combat_id,),
        )
        results.append((
            "A",
            "CHECK status rejects 'invalid_status'",
            False,
            "INSERT succeeded but should have raised IntegrityError",
        ))
    except sqlite3.IntegrityError as e:
        results.append((
            "A",
            "CHECK status rejects 'invalid_status'",
            True,
            f"raised IntegrityError: {e}",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK status rejects 'invalid_status'",
            False,
            f"raised {type(e).__name__} (expected IntegrityError): {e}",
        ))

    # CHECK constraint: exclusive_flag=2 (not 0 or 1) -> IntegrityError.
    try:
        conn.execute(
            "INSERT INTO contracts (contract_target_type, promotion_id, "
            "start_date, end_date, exclusive_flag) VALUES "
            "('fighter', ?, '2026-01-01', '2026-12-31', 2)",
            (alpha_combat_id,),
        )
        results.append((
            "A",
            "CHECK exclusive_flag rejects value=2",
            False,
            "INSERT succeeded but should have raised IntegrityError",
        ))
    except sqlite3.IntegrityError as e:
        results.append((
            "A",
            "CHECK exclusive_flag rejects value=2",
            True,
            f"raised IntegrityError: {e}",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK exclusive_flag rejects value=2",
            False,
            f"raised {type(e).__name__} (expected IntegrityError): {e}",
        ))

    # Roll back any partial inserts from the failed-CHECK attempts so
    # the next case starts from a clean state.
    conn.rollback()

    # ----------------------------------------------------------------
    # Test case B — Seed.
    # ----------------------------------------------------------------
    print("\n--- Case B: seed ---")

    # 5 fighter_contracts (2 AC + 3 RFL).
    n_fc = conn.execute("SELECT COUNT(*) FROM fighter_contracts").fetchone()[0]
    results.append((
        "B",
        f"fighter_contracts has {EXPECTED_FIGHTER_CONTRACTS} rows "
        f"(2 AC + 3 RFL)",
        n_fc == EXPECTED_FIGHTER_CONTRACTS,
        f"got={n_fc}",
    ))

    # 1 staff_contract (Nina Cross).
    n_sc = conn.execute("SELECT COUNT(*) FROM staff_contracts").fetchone()[0]
    results.append((
        "B",
        f"staff_contracts has {EXPECTED_STAFF_CONTRACTS} row "
        f"(Nina Cross)",
        n_sc == EXPECTED_STAFF_CONTRACTS,
        f"got={n_sc}",
    ))

    # 0 broadcast_contracts.
    n_bc = conn.execute("SELECT COUNT(*) FROM broadcast_contracts").fetchone()[0]
    results.append((
        "B",
        f"broadcast_contracts has {EXPECTED_BROADCAST_CONTRACTS} rows",
        n_bc == EXPECTED_BROADCAST_CONTRACTS,
        f"got={n_bc}",
    ))

    # 6 total contracts (5 fighter + 1 staff).
    n_total = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    results.append((
        "B",
        f"contracts has {EXPECTED_TOTAL_CONTRACTS} total rows "
        f"(5 fighter + 1 staff)",
        n_total == EXPECTED_TOTAL_CONTRACTS,
        f"got={n_total}",
    ))

    # Each fighter_contract's contract.promotion_id matches the
    # fighter's current_promotion_id.
    mismatched = conn.execute(
        "SELECT fc.fighter_contract_id, c.promotion_id, f.current_promotion_id "
        "FROM fighter_contracts fc "
        "JOIN contracts c ON c.contract_id = fc.contract_id "
        "JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE c.promotion_id != f.current_promotion_id"
    ).fetchall()
    results.append((
        "B",
        "every fighter_contract's contract.promotion_id matches "
        "fighter.current_promotion_id",
        len(mismatched) == 0,
        f"mismatched rows={mismatched}",
    ))

    # All contracts: start_date, end_date, salary, exclusive_flag, status.
    bad_dates = conn.execute(
        "SELECT contract_id, start_date, end_date FROM contracts "
        "WHERE start_date != ? OR end_date != ?",
        (EXPECTED_START_DATE, EXPECTED_END_DATE),
    ).fetchall()
    results.append((
        "B",
        f"every contract: start_date='{EXPECTED_START_DATE}', "
        f"end_date='{EXPECTED_END_DATE}'",
        len(bad_dates) == 0,
        f"bad rows={bad_dates}",
    ))

    bad_salary = conn.execute(
        "SELECT contract_id, salary FROM contracts WHERE salary != ?",
        (EXPECTED_SALARY,),
    ).fetchall()
    results.append((
        "B",
        f"every contract: salary={EXPECTED_SALARY}",
        len(bad_salary) == 0,
        f"bad rows={bad_salary}",
    ))

    bad_excl = conn.execute(
        "SELECT contract_id, exclusive_flag FROM contracts "
        "WHERE exclusive_flag != ?",
        (EXPECTED_EXCLUSIVE_FLAG,),
    ).fetchall()
    results.append((
        "B",
        f"every contract: exclusive_flag={EXPECTED_EXCLUSIVE_FLAG}",
        len(bad_excl) == 0,
        f"bad rows={bad_excl}",
    ))

    bad_status = conn.execute(
        "SELECT contract_id, status FROM contracts WHERE status != ?",
        (EXPECTED_STATUS,),
    ).fetchall()
    results.append((
        "B",
        f"every contract: status='{EXPECTED_STATUS}'",
        len(bad_status) == 0,
        f"bad rows={bad_status}",
    ))

    # All fighter_contracts: contract_type='standard'.
    bad_type = conn.execute(
        "SELECT fighter_contract_id, contract_type FROM fighter_contracts "
        "WHERE contract_type != ?",
        (EXPECTED_FIGHTER_CONTRACT_TYPE,),
    ).fetchall()
    results.append((
        "B",
        f"every fighter_contract: contract_type='{EXPECTED_FIGHTER_CONTRACT_TYPE}'",
        len(bad_type) == 0,
        f"bad rows={bad_type}",
    ))

    # The 1 staff_contract: contract_role='commentator'.
    sc_row = conn.execute(
        "SELECT staff_contract_id, contract_role FROM staff_contracts"
    ).fetchone()
    results.append((
        "B",
        f"the 1 staff_contract: contract_role='{EXPECTED_STAFF_ROLE}'",
        sc_row is not None and sc_row[1] == EXPECTED_STAFF_ROLE,
        f"row={sc_row}",
    ))

    # bonus_structure and buyout_clause default to NULL (not set by
    # the seed — Tasks 13 and 25 will populate them).
    n_null_bonus = conn.execute(
        "SELECT COUNT(*) FROM contracts WHERE bonus_structure IS NOT NULL "
        "OR buyout_clause IS NOT NULL"
    ).fetchone()[0]
    results.append((
        "B",
        "bonus_structure and buyout_clause are NULL on every contract "
        "(placeholder for Tasks 13 and 25)",
        n_null_bonus == 0,
        f"non-NULL rows={n_null_bonus}",
    ))

    # ----------------------------------------------------------------
    # Test case C — get_contracts_for_display() helper.
    # ----------------------------------------------------------------
    print("\n--- Case C: get_contracts_for_display() helper ---")

    # No filter: returns 6 rows.
    rows_all = app.get_contracts_for_display(conn)
    results.append((
        "C",
        f"no filter: returns {EXPECTED_TOTAL_CONTRACTS} rows",
        len(rows_all) == EXPECTED_TOTAL_CONTRACTS,
        f"got={len(rows_all)}",
    ))

    # Every row is a 7-tuple.
    bad_arity = [r for r in rows_all if len(r) != 7]
    results.append((
        "C",
        "every row is a 7-tuple (contractor_name, type, start, end, "
        "salary, exclusive, status)",
        len(bad_arity) == 0,
        f"bad rows={bad_arity}",
    ))

    # AC filter: returns 3 rows (2 fighters + 1 staff).
    rows_ac = app.get_contracts_for_display(conn, alpha_combat_id)
    results.append((
        "C",
        f"AC filter: returns 3 rows (2 fighters + 1 staff)",
        len(rows_ac) == 3,
        f"got={len(rows_ac)}",
    ))
    # All 3 AC contract rows are for AC's promotion_id (verified by
    # counting fighter names + the staff name 'Nina Cross').
    contractor_names_ac = sorted(r[0] for r in rows_ac)
    expected_ac_names = sorted(["John Vale", "Marcus Reed", "Nina Cross"])
    results.append((
        "C",
        f"AC filter: contractor names match AC roster "
        f"({expected_ac_names})",
        contractor_names_ac == expected_ac_names,
        f"got={contractor_names_ac}",
    ))

    # RFL filter: returns 3 rows (3 RFL fighters, no staff).
    rows_rfl = app.get_contracts_for_display(conn, rfl_id)
    results.append((
        "C",
        f"RFL filter: returns 3 rows (3 RFL fighters, no staff)",
        len(rows_rfl) == 3,
        f"got={len(rows_rfl)}",
    ))
    contractor_names_rfl = sorted(r[0] for r in rows_rfl)
    expected_rfl_names = sorted(["Dario Knox", "Eli Storm", "Cole Briggs"])
    results.append((
        "C",
        f"RFL filter: contractor names match RFL roster "
        f"({expected_rfl_names})",
        contractor_names_rfl == expected_rfl_names,
        f"got={contractor_names_rfl}",
    ))
    # All RFL rows have contract_target_type='fighter'.
    rfl_types_ok = all(r[1] == "fighter" for r in rows_rfl)
    results.append((
        "C",
        "RFL filter: every row has contract_target_type='fighter' "
        "(no staff in RFL)",
        rfl_types_ok,
        f"types={[r[1] for r in rows_rfl]}",
    ))

    # Invalid promotion_id=99999: returns empty list (no crash).
    try:
        rows_invalid = app.get_contracts_for_display(conn, 99999)
        results.append((
            "C",
            "invalid promotion_id=99999: returns empty list, no crash",
            len(rows_invalid) == 0,
            f"got={len(rows_invalid)} rows",
        ))
    except Exception as e:
        results.append((
            "C",
            "invalid promotion_id=99999: returns empty list, no crash",
            False,
            f"crashed: {type(e).__name__}: {e}",
        ))

    # ----------------------------------------------------------------
    # Backup case A/B/C state for case E (which rebuilds the DB).
    # ----------------------------------------------------------------
    conn.close()
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, DB_BACKUP_PATH)

    # ----------------------------------------------------------------
    # Test case D — UI smoke test (optional, SKIPs cleanly in headless).
    # ----------------------------------------------------------------
    print("\n--- Case D: UI smoke test ---")
    d_skipped = False
    try:
        app_instance = app.App()
    except _tkinter_TclError as e:
        print(f"  SKIP — no display available ({type(e).__name__})")
        d_skipped = True
    except Exception as e:
        results.append((
            "D",
            "App() constructs without crashing",
            False,
            f"App() crashed: {type(e).__name__}: {e}",
        ))
        d_skipped = True  # nothing else to test in case D
    else:
        try:
            # Verify self.contracts Treeview widget exists.
            has_contracts_widget = hasattr(app_instance, "contracts")
            results.append((
                "D",
                "App() has self.contracts Treeview widget",
                has_contracts_widget,
                f"hasattr={has_contracts_widget}",
            ))

            # Set filter to AC, refresh, assert Contracts tree has 3 entries.
            app_instance.current_promotion_filter = alpha_combat_id
            app_instance.refresh_all()
            n_ac = len(app_instance.contracts.get_children())
            results.append((
                "D",
                "filter=AC: Contracts tree has 3 entries",
                n_ac == 3,
                f"got={n_ac}",
            ))

            # Set filter to None, refresh, assert Contracts tree has 6.
            app_instance.current_promotion_filter = None
            app_instance.refresh_all()
            n_all = len(app_instance.contracts.get_children())
            results.append((
                "D",
                "filter=None: Contracts tree has 6 entries",
                n_all == EXPECTED_TOTAL_CONTRACTS,
                f"got={n_all}",
            ))

            # Set filter to RFL, refresh, assert Contracts tree has 3.
            app_instance.current_promotion_filter = rfl_id
            app_instance.refresh_all()
            n_rfl = len(app_instance.contracts.get_children())
            results.append((
                "D",
                "filter=RFL: Contracts tree has 3 entries",
                n_rfl == 3,
                f"got={n_rfl}",
            ))
        finally:
            try:
                app_instance.destroy()
            except Exception:
                pass

    # ----------------------------------------------------------------
    # Test case E — Regression: fight_history, event lifecycle,
    # event scheduler still work + contracts unchanged.
    # ----------------------------------------------------------------
    print("\n--- Case E: regression — fight_history + event lifecycle "
          "+ event scheduler + contracts unchanged ---")

    # Restore case A/B/C's DB state (6 contracts, 1 event scheduled).
    if DB_PATH.exists():
        DB_PATH.unlink()
    shutil.copy2(DB_BACKUP_PATH, DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Before: snapshot the contracts table count.
    contracts_before = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    fh_before = conn.execute(
        "SELECT COUNT(*) FROM fight_history"
    ).fetchone()[0]
    events_before = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]

    # Resolve the seeded fight. Seed RNG for reproducibility.
    random.seed(RANDOM_SEED)
    resolved = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "E",
        "resolve_next_fight returned a fight_id",
        resolved is not None,
        f"fight_id={resolved}",
    ))

    # fight_history has 2 new rows.
    fh_after = conn.execute(
        "SELECT COUNT(*) FROM fight_history"
    ).fetchone()[0]
    results.append((
        "E",
        "fight_history has 2 new rows after resolution",
        fh_after - fh_before == 2,
        f"before={fh_before}, after={fh_after}, delta={fh_after - fh_before}",
    ))

    # Seeded event's status is 'completed'.
    seeded_status = conn.execute(
        "SELECT status FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    results.append((
        "E",
        "seeded event's status is 'completed' after resolution",
        seeded_status is not None and seeded_status[0] == "completed",
        f"got={seeded_status[0] if seeded_status else None}",
    ))

    # A new event was auto-scheduled (Task 8 hook).
    events_after = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    results.append((
        "E",
        "1 new event auto-scheduled (Task 8 hook)",
        events_after - events_before == 1,
        f"before={events_before}, after={events_after}, "
        f"delta={events_after - events_before}",
    ))

    # The new event's status is 'scheduled'.
    new_event = conn.execute(
        "SELECT event_id, status FROM events ORDER BY event_id DESC LIMIT 1"
    ).fetchone()
    results.append((
        "E",
        "new event's status is 'scheduled'",
        new_event is not None and new_event[1] == "scheduled",
        f"row={new_event}",
    ))

    # Contracts table is unchanged (no new contracts created by fight
    # resolution — Task 13 will add contract effects).
    contracts_after = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    results.append((
        "E",
        "contracts table unchanged after fight resolution "
        "(Task 13 will add contract effects)",
        contracts_after == contracts_before,
        f"before={contracts_before}, after={contracts_after}",
    ))

    # fighter_contracts / staff_contracts / broadcast_contracts also
    # unchanged.
    fc_after = conn.execute(
        "SELECT COUNT(*) FROM fighter_contracts"
    ).fetchone()[0]
    sc_after = conn.execute(
        "SELECT COUNT(*) FROM staff_contracts"
    ).fetchone()[0]
    bc_after = conn.execute(
        "SELECT COUNT(*) FROM broadcast_contracts"
    ).fetchone()[0]
    results.append((
        "E",
        "fighter_contracts / staff_contracts / broadcast_contracts "
        "all unchanged",
        fc_after == EXPECTED_FIGHTER_CONTRACTS
        and sc_after == EXPECTED_STAFF_CONTRACTS
        and bc_after == EXPECTED_BROADCAST_CONTRACTS,
        f"fc={fc_after}, sc={sc_after}, bc={bc_after}",
    ))

    conn.close()

    # Clean up the backup file now that we're done with it.
    if DB_BACKUP_PATH.exists():
        DB_BACKUP_PATH.unlink()

    # ----------------------------------------------------------------
    # Print summary table.
    # ----------------------------------------------------------------
    print("\n" + sep)
    print(f"{'Case':<6} {'Check':<72} {'Result':<8} Detail")
    print("-" * 120)
    n_pass = 0
    n_fail = 0
    by_case = {}
    for case, name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        else:
            n_fail += 1
        by_case.setdefault(case, {"pass": 0, "fail": 0})
        if passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 50:
            detail_str = detail_str[:47] + "..."
        print(f"{case:<6} {name:<72} {status:<8} {detail_str}")
    if d_skipped and not any(c == "D" for c, _, _, _ in results):
        print(f"{'D':<6} {'UI smoke test (App construction + Contracts tab)':<72} "
              f"{'SKIP':<8} no display available")
    print(sep)
    print(f"Total: {n_pass} PASS, {n_fail} FAIL"
          + (" (+ case D skipped)" if d_skipped else ""))
    print(sep)
    print("By case:")
    for case in sorted(by_case.keys()):
        c = by_case[case]
        print(f"  Case {case}: {c['pass']} PASS, {c['fail']} FAIL")
    if d_skipped:
        print(f"  Case D: SKIP (no display available)")
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
