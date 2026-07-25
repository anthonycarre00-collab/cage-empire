#!/usr/bin/env python3
"""Acceptance test for Task ID 5 — schema version-check gate in build_db.py.

Tests 7 cases (per docs/STAGES.md Task ID 5):

  1. Fresh DB path:           no DB file  -> build_db.py runs cleanly,
                                         produces schema_version=1.3.0.
  2. Same-version rebuild:    DB at 1.3.0 -> runs cleanly, prints
                                         "Rebuilding same schema version 1.3.0.".
  3. Upgrade rebuild:         DB at 1.2.1 -> runs cleanly, prints
                                         "Upgrading schema: 1.2.1 -> 1.3.0",
                                         resulting DB has 1.3.0.
  4. Refuse newer version:    DB at 9.9.9 -> MUST raise RuntimeError with
                                         "9.9.9" and "1.3.0" in the message.
                                         DB file untouched.
  5. No schema_meta table:    DB with tables but no schema_meta -> runs
                                         cleanly (prints a warning, proceeds).
  6. Corrupt DB:              non-SQLite garbage file -> runs cleanly
                                         (treats as no version, rebuilds).
  7. Semver comparison unit tests: directly tests _parse_version and
                                         _compare_versions, including the
                                         1.10.0 > 1.9.0 case that string
                                         comparison gets wrong, and the
                                         1.0.0-beta no-crash case.

Cases 1-6 invoke build_db.py as a real subprocess (so the RuntimeError
in case 4 is observed as a non-zero exit code + traceback in stderr).
Case 7 imports _parse_version / _compare_versions directly from
build_db via sys.path.insert.

Run from the project root:
    python3 scripts/test_schema_versioning.py

Exit code 0 = all PASS, 1 = any FAIL. The script only touches the DB
at data/cage_empire.db (rebuilds it multiple times) — it does not
modify any source files.
"""
import sqlite3
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)

EXPECTED_CODE_VERSION = None  # set after build_db import below

# Make src/ importable so we can call _parse_version / _compare_versions
# directly for case 7. Importing build_db does NOT execute main() (it's
# guarded by `if __name__ == "__main__"`), so this is safe.
sys.path.insert(0, str(SRC_DIR))
import build_db  # noqa: E402

# Dynamic schema version (Task ID 9 supervisor fix). Reading this from
# build_db means this test does not need to be updated on every schema
# version bump.
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def run_build_db():
    """Invoke build_db.py as a subprocess.

    Returns (returncode, stdout, stderr) so the caller can verify
    behavior including the RuntimeError exit code in case 4.
    """
    proc = subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def read_schema_version():
    """Read schema_meta.schema_version from the DB.

    Returns None if no DB, no schema_meta table, no row, or DB is
    corrupt. Mirrors build_db._read_on_disk_schema_version but is
    intentionally re-implemented here so the test does not depend
    on the helper it is testing.
    """
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            )
            if cur.fetchone() is None:
                return None
            row = conn.execute(
                "SELECT schema_version FROM schema_meta WHERE schema_name=?",
                ("cage_empire",),
            ).fetchone()
            return row[0] if row else None
    except sqlite3.DatabaseError:
        return None


def set_schema_version(v):
    """Update schema_meta.schema_version (for case 3 and case 4 setup).

    Assumes a DB with a schema_meta table already exists.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE schema_meta SET schema_version=? WHERE schema_name='cage_empire'",
            (v,),
        )
        conn.commit()


def delete_db():
    """Remove the DB file if it exists."""
    if DB_PATH.exists():
        DB_PATH.unlink()


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------
# Case 1 — fresh DB path
# --------------------------------------------------------------------

def case_1_fresh_db():
    delete_db()
    rc, out, err = run_build_db()
    actual_version = read_schema_version()
    passed = (rc == 0) and (actual_version == EXPECTED_CODE_VERSION)
    return passed, {
        "case": "1. Fresh DB path (no file -> rebuild -> 1.3.0)",
        "expected": f"rc=0, schema_version={EXPECTED_CODE_VERSION}",
        "actual": f"rc={rc}, schema_version={actual_version!r}",
        "stdout": out.strip(),
        "stderr": err.strip(),
    }


# --------------------------------------------------------------------
# Case 2 — same-version rebuild
# --------------------------------------------------------------------

def case_2_same_version_rebuild():
    # Precondition: DB at 1.3.0 (from case 1 or a fresh build).
    if read_schema_version() != EXPECTED_CODE_VERSION:
        delete_db()
        run_build_db()
    rc, out, err = run_build_db()
    expected_text = f"Rebuilding same schema version {EXPECTED_CODE_VERSION}."
    actual_version = read_schema_version()
    passed = (rc == 0) and (expected_text in out) and (actual_version == EXPECTED_CODE_VERSION)
    return passed, {
        "case": "2. Same-version rebuild (1.3.0 -> 1.3.0)",
        "expected": f"rc=0, stdout contains {expected_text!r}, schema_version={EXPECTED_CODE_VERSION}",
        "actual": f"rc={rc}, schema_version={actual_version!r}",
        "stdout": out.strip(),
        "stderr": err.strip(),
    }


# --------------------------------------------------------------------
# Case 3 — upgrade rebuild
# --------------------------------------------------------------------

def case_3_upgrade_rebuild():
    # Start from a clean build, then manually downgrade the
    # on-disk version to 1.2.1 to simulate an older DB.
    delete_db()
    run_build_db()
    set_schema_version("1.2.1")
    # Sanity check: version is now 1.2.1.
    assert read_schema_version() == "1.2.1", "setup failed: version not 1.2.1"
    rc, out, err = run_build_db()
    # Task 16.6: the message changed from "Upgrading schema" to
    # "Rebuilding schema" to match the dual-mode --fresh / --migrate
    # workflow. --fresh is the default and still rebuilds (drops +
    # recreates) when the on-disk version is older; --migrate is the
    # new path that preserves data.
    expected_text = f"Rebuilding schema: 1.2.1 -> {EXPECTED_CODE_VERSION}"
    actual_version = read_schema_version()
    passed = (rc == 0) and (expected_text in out) and (actual_version == EXPECTED_CODE_VERSION)
    return passed, {
        "case": "3. Upgrade rebuild (1.2.1 -> current, --fresh default)",
        "expected": f"rc=0, stdout contains {expected_text!r}, schema_version={EXPECTED_CODE_VERSION}",
        "actual": f"rc={rc}, schema_version={actual_version!r}",
        "stdout": out.strip(),
        "stderr": err.strip(),
    }


# --------------------------------------------------------------------
# Case 4 — refuse newer version
# --------------------------------------------------------------------

def case_4_refuse_newer_version():
    # Start from a clean 1.3.0 build, then manually upgrade the
    # on-disk version to 9.9.9 (simulating a newer build_db.py having
    # written this schema).
    delete_db()
    run_build_db()
    set_schema_version("9.9.9")
    # Sanity check: version is now 9.9.9.
    assert read_schema_version() == "9.9.9", "setup failed: version not 9.9.9"

    # Snapshot mtime + size to verify the file is not modified when
    # the gate refuses. mtime alone could be flaky on filesystems with
    # coarse mtime resolution; the schema_version re-read is the
    # strong guarantee, mtime/size are secondary sanity checks.
    stat_before = DB_PATH.stat()
    mtime_before = stat_before.st_mtime
    size_before = stat_before.st_size

    rc, out, err = run_build_db()

    stat_after = DB_PATH.stat()
    mtime_after = stat_after.st_mtime
    size_after = stat_after.st_size
    actual_version = read_schema_version()

    combined_output = out + err
    passed = (
        rc != 0
        and "9.9.9" in combined_output
        and EXPECTED_CODE_VERSION in combined_output
        and actual_version == "9.9.9"
        and mtime_after == mtime_before
        and size_after == size_before
    )
    return passed, {
        "case": f"4. Refuse newer version (9.9.9 > {EXPECTED_CODE_VERSION})",
        "expected": (
            f"rc!=0, output contains '9.9.9' and '{EXPECTED_CODE_VERSION}', "
            "DB untouched (schema_version still 9.9.9, "
            "mtime + size unchanged)"
        ),
        "actual": (
            f"rc={rc}, schema_version={actual_version!r}, "
            f"mtime_changed={mtime_after != mtime_before}, "
            f"size_changed={size_after != size_before}"
        ),
        "stdout": out.strip(),
        "stderr": err.strip(),
    }


# --------------------------------------------------------------------
# Case 5 — no schema_meta table
# --------------------------------------------------------------------

def case_5_no_schema_meta_table():
    delete_db()
    ensure_data_dir()
    # Create a fresh sqlite DB with one unrelated table (no schema_meta).
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.execute("INSERT INTO unrelated VALUES (42)")
        conn.commit()
    rc, out, err = run_build_db()
    actual_version = read_schema_version()
    # The brief says "prints a warning, then proceeds". The helper
    # prints "Warning: no schema_meta table in ...".
    passed = (
        rc == 0
        and actual_version == EXPECTED_CODE_VERSION
        and "Warning" in out
        and "schema_meta" in out
    )
    return passed, {
        "case": "5. No schema_meta table (warning printed, rebuild proceeds)",
        "expected": (
            f"rc=0, stdout contains 'Warning' and 'schema_meta', "
            f"schema_version={EXPECTED_CODE_VERSION} after rebuild"
        ),
        "actual": f"rc={rc}, schema_version={actual_version!r}",
        "stdout": out.strip(),
        "stderr": err.strip(),
    }


# --------------------------------------------------------------------
# Case 6 — corrupt DB
# --------------------------------------------------------------------

def case_6_corrupt_db():
    delete_db()
    ensure_data_dir()
    # Write non-SQLite garbage to the DB path. build_db.py must treat
    # this as no version and allow the rebuild.
    DB_PATH.write_text("not a database\n")
    rc, out, err = run_build_db()
    actual_version = read_schema_version()
    passed = (rc == 0) and (actual_version == EXPECTED_CODE_VERSION)
    return passed, {
        "case": "6. Corrupt DB (non-SQLite garbage, treated as no version)",
        "expected": f"rc=0, schema_version={EXPECTED_CODE_VERSION} after rebuild",
        "actual": f"rc={rc}, schema_version={actual_version!r}",
        "stdout": out.strip(),
        "stderr": err.strip(),
    }


# --------------------------------------------------------------------
# Case 7 — semver comparison unit tests
# --------------------------------------------------------------------

def case_7_version_helpers():
    """Directly test _parse_version and _compare_versions."""
    sub_results = []

    def check(name, actual, expected):
        passed = actual == expected
        sub_results.append((name, passed, actual, expected))
        return passed

    # _parse_version
    check("_parse_version('1.3.0') == (1, 3, 0)",
          build_db._parse_version("1.3.0"), (1, 3, 0))

    # _compare_versions — basic
    check("_compare_versions('1.3.0', '1.3.0') == 0",
          build_db._compare_versions("1.3.0", "1.3.0"), 0)
    check("_compare_versions('1.3.0', '1.2.1') == 1",
          build_db._compare_versions("1.3.0", "1.2.1"), 1)
    check("_compare_versions('1.2.1', '1.3.0') == -1",
          build_db._compare_versions("1.2.1", "1.3.0"), -1)

    # _compare_versions — the case string comparison would get wrong
    check("_compare_versions('1.10.0', '1.9.0') == 1  (string-cmp would get this wrong)",
          build_db._compare_versions("1.10.0", "1.9.0"), 1)
    check("_compare_versions('2.0.0', '1.99.99') == 1",
          build_db._compare_versions("2.0.0", "1.99.99"), 1)

    # _compare_versions — the 1.0.0-beta prerelease case.
    # Must not crash. We chose "pad and compare ints" (decision D1 in
    # agent-ctx/5-full-stack-developer.md) — '1.0.0-beta' parses as
    # (1, 0, 0) and compares equal to '1.0.0'. The brief's case 7 only
    # requires "should not crash", so any non-crashing result is
    # acceptable; we also assert the documented == 0 result for
    # regression protection.
    try:
        result = build_db._compare_versions("1.0.0", "1.0.0-beta")
        crashed = False
        crash_msg = None
    except Exception as e:
        result = None
        crashed = True
        crash_msg = f"{type(e).__name__}: {e}"
    check("_compare_versions('1.0.0', '1.0.0-beta') does not crash",
          crashed, False)
    check("_compare_versions('1.0.0', '1.0.0-beta') == 0  (prerelease dropped, decision D1)",
          result, 0)

    all_passed = all(p for _, p, _, _ in sub_results)
    n_sub_pass = sum(1 for _, p, _, _ in sub_results if p)
    n_sub_total = len(sub_results)
    actual_str = f"{n_sub_pass}/{n_sub_total} sub-checks passed"
    if crashed:
        actual_str += f" (crash: {crash_msg})"
    return all_passed, {
        "case": "7. Semver comparison unit tests (_parse_version + _compare_versions)",
        "expected": f"{n_sub_total} sub-checks all pass",
        "actual": actual_str,
        "sub_results": sub_results,
    }


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 76
    print(sep)
    print("TASK 5 SCHEMA VERSIONING ACCEPTANCE TEST")
    print(f"Code schema version: {EXPECTED_CODE_VERSION}")
    print(sep)
    print()

    cases = [
        case_1_fresh_db,
        case_2_same_version_rebuild,
        case_3_upgrade_rebuild,
        case_4_refuse_newer_version,
        case_5_no_schema_meta_table,
        case_6_corrupt_db,
        case_7_version_helpers,
    ]

    results = []
    for case_fn in cases:
        passed, info = case_fn()
        results.append((passed, info))
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {info['case']}")
        print(f"        expected: {info['expected']}")
        print(f"        actual:   {info['actual']}")
        if info.get("stdout"):
            for line in info["stdout"].splitlines()[-3:]:
                print(f"        stdout:   {line}")
        if info.get("stderr"):
            for line in info["stderr"].splitlines()[-3:]:
                print(f"        stderr:   {line}")
        if "sub_results" in info:
            for sub_name, sub_passed, sub_actual, sub_expected in info["sub_results"]:
                sub_status = "PASS" if sub_passed else "FAIL"
                print(f"        [{sub_status}] {sub_name}")
                if not sub_passed:
                    print(f"                expected: {sub_expected!r}")
                    print(f"                actual:   {sub_actual!r}")
        print()

    print(sep)
    print("SUMMARY")
    print(sep)
    n_pass = sum(1 for p, _ in results if p)
    n_total = len(results)
    for passed, info in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {info['case']}")
    print()
    print(f"Total: {n_pass} / {n_total} cases passed")
    print(sep)
    if n_pass == n_total:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
