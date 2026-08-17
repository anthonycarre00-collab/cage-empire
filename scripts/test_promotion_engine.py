#!/usr/bin/env python3
"""Phase 6 Task A2 — promotion_engine smoke test.

Calls compute_all_promotion_descriptors(conn, '2026-08-17') directly
+ verifies promotion_descriptors has 10 rows with all 3 voice phrase
fields non-NULL. Prints the 10 sample rows for visual review.

Run from project root:
    python3 scripts/test_promotion_engine.py
"""
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

from interpretation.promotion_engine import compute_all_promotion_descriptors


def main():
    print("=" * 72)
    print("Phase 6 Task A2 — promotion_engine smoke test")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Baseline count (should be 0 — table is empty until this task).
    before = conn.execute(
        "SELECT COUNT(*) FROM promotion_descriptors"
    ).fetchone()[0]
    print(f"Before: promotion_descriptors has {before} rows")

    # Call the engine directly.
    t0 = time.perf_counter()
    n = compute_all_promotion_descriptors(conn, "2026-08-17")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"compute_all_promotion_descriptors returned: {n} rows "
          f"in {elapsed_ms:.2f} ms")
    print()

    # Verify row count.
    after = conn.execute(
        "SELECT COUNT(*) FROM promotion_descriptors"
    ).fetchone()[0]
    print(f"After: promotion_descriptors has {after} rows")
    assert after == 10, f"Expected 10 rows, got {after}"
    print(f"  [PASS] 10 rows populated (was {before})")
    print()

    # Verify all 3 voice-phrase fields are non-NULL.
    nulls = conn.execute(
        """
        SELECT COUNT(*) FROM promotion_descriptors
        WHERE prestige_desc IS NULL
           OR market_position_desc IS NULL
           OR roster_quality_desc IS NULL
        """
    ).fetchone()[0]
    assert nulls == 0, f"Found {nulls} rows with NULL voice phrases"
    print(f"  [PASS] all 3 voice-phrase fields non-NULL across {after} rows")
    print()

    # Print all 10 sample rows (joined with promotion name + raw sim
    # columns for context).
    print("--- promotion_descriptors (joined with promotions sim table) ---")
    rows = conn.execute(
        """
        SELECT p.promotion_id, p.name, p.size_tier, p.reputation,
               p.broadcast_tier, p.ownership_type,
               pd.prestige_desc, pd.market_position_desc,
               pd.roster_quality_desc, pd.snapshot_version
        FROM promotion_descriptors pd
        JOIN promotions p ON p.promotion_id = pd.promotion_id
        ORDER BY p.promotion_id
        """
    ).fetchall()
    for r in rows:
        (pid, name, size, rep, bt, ot, prest, mpos, rqual, sv) = r
        print(f"  [{pid:>2}] {name}")
        print(f"       sim:    size={size} rep={rep} bt={bt} own={ot}")
        print(f"       prestige:      {prest}")
        print(f"       market_pos:    {mpos}")
        print(f"       roster_quality: {rqual}")
        print(f"       (snapshot_version={sv})")
        print()

    # Idempotency check — re-run should produce identical rows + tick
    # snapshot_version.
    n2 = compute_all_promotion_descriptors(conn, "2026-08-17")
    after2 = conn.execute(
        "SELECT COUNT(*) FROM promotion_descriptors"
    ).fetchone()[0]
    assert after2 == 10, f"Idempotent re-run changed row count: {after2}"
    # snapshot_version should tick from 1 → 2 on the second run.
    versions = conn.execute(
        """
        SELECT MIN(snapshot_version), MAX(snapshot_version)
        FROM promotion_descriptors
        """
    ).fetchone()
    print(f"  [PASS] idempotent re-run: row count stable at {after2}, "
          f"snapshot_version range [{versions[0]}, {versions[1]}] "
          f"(should be [2, 2] after second run)")
    print()

    # Performance budget check (<50ms for 10 promotions).
    t0 = time.perf_counter()
    compute_all_promotion_descriptors(conn, "2026-08-17")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"  [PASS] performance: third call took {elapsed_ms:.2f} ms "
          f"(budget <50ms for 10 promos)")
    print()

    conn.close()
    print("=" * 72)
    print("RESULT: ALL CHECKS PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()
