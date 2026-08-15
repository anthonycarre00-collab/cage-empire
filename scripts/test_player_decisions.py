#!/usr/bin/env python3
"""Acceptance test for Phase R (Reward Layer) — player_decisions module.

Tests the player_decisions helper API added in PHASE-R-REWARD-LAYER:

  A. log_decision writes a row with the correct decision_type,
     target_fighter_id, decision_date, and parsed context_json.
  B. log_decision rejects invalid decision_type (returns None, no
     row inserted — the CHECK constraint catches it).
  C. log_decision reads the sim clock when decision_date is None.
  D. get_recent_decisions returns rows newest-first + respects the
     limit + the decision_type filter.
  E. get_decisions_for_fighter returns rows oldest-first (timeline
     order for the Fighter Profile "Your History with [Fighter]"
     section).
  F. get_decisions_since filters by sim-date window.
  G. Backfill: backfill_player_decisions_for_promo synthesizes sign
     decisions for current roster + cut decisions for terminated
     contracts. Idempotent (second call is a no-op).

Run from the project root:
    python3 scripts/test_player_decisions.py

Exit code 0 = all PASS, 1 = any FAIL. Does NOT rebuild the DB —
operates on the existing data/cage_empire.db (creates the
player_decisions table via migration if needed, then cleans up
its test rows so subsequent runs are deterministic).
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

sys.path.insert(0, str(SRC_DIR))

import build_db  # noqa: E402
import player_decisions as pd  # noqa: E402


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_schema():
    """Apply any pending migrations (idempotent)."""
    conn = _connect()
    try:
        build_db._run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def _cleanup_test_rows(conn):
    """Remove test rows so the test is deterministic. Does NOT touch
    the simulation_clock (the test saves + restores it via
    _set_sim_date / _restore_sim_date)."""
    conn.execute("DELETE FROM player_decisions")
    conn.commit()


# Save the original sim_date so we can restore it at the end (the
# tests temporarily move the clock to make log_decision deterministic).
_ORIG_SIM_DATE = None


def _save_sim_date(conn):
    global _ORIG_SIM_DATE
    _ORIG_SIM_DATE = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]


def _restore_sim_date(conn):
    global _ORIG_SIM_DATE
    if _ORIG_SIM_DATE:
        conn.execute(
            "UPDATE simulation_clock SET current_date=? WHERE clock_id=1",
            (_ORIG_SIM_DATE,),
        )
        conn.commit()


def _set_sim_date(conn, sim_date):
    """Pin the sim clock so log_decision's default decision_date
    is deterministic."""
    conn.execute(
        "UPDATE simulation_clock SET current_date=? WHERE clock_id=1",
        (sim_date,),
    )
    conn.commit()


# ----------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------

def test_a_log_decision_basic():
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        _set_sim_date(conn, "2026-10-15")
        did = pd.log_decision(
            conn, pd.TYPE_SIGN,
            target_fighter_id=42,
            target_promo_id=1,
            context={"cost_value": 75000, "cost_display": "$75K"},
        )
        assert did, "log_decision returned None — insert failed"
        row = conn.execute(
            "SELECT decision_type, target_fighter_id, target_promo_id, "
            "       decision_date, context_json "
            "FROM player_decisions WHERE decision_id=?",
            (did,),
        ).fetchone()
        assert row[0] == "sign", f"expected 'sign', got {row[0]!r}"
        assert row[1] == 42
        assert row[2] == 1
        assert row[3] == "2026-10-15", \
            f"decision_date should be sim_date, got {row[3]!r}"
        ctx = json.loads(row[4])
        assert ctx["cost_value"] == 75000
        assert ctx["cost_display"] == "$75K"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


def test_b_log_decision_rejects_invalid_type():
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        _set_sim_date(conn, "2026-10-15")
        # 'bogus_type' is not in the CHECK constraint — log_decision
        # returns None and no row is inserted.
        did = pd.log_decision(conn, "bogus_type", target_fighter_id=1)
        assert did is None, \
            f"log_decision should return None for invalid type, got {did}"
        n = conn.execute("SELECT COUNT(*) FROM player_decisions").fetchone()[0]
        assert n == 0, f"expected 0 rows after invalid type, got {n}"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


def test_c_log_decision_reads_clock():
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        _set_sim_date(conn, "2027-03-22")
        did = pd.log_decision(
            conn, pd.TYPE_CUT,
            target_fighter_id=99,
            target_promo_id=2,
        )
        assert did, "log_decision returned None"
        row = conn.execute(
            "SELECT decision_date FROM player_decisions WHERE decision_id=?",
            (did,),
        ).fetchone()
        assert row[0] == "2027-03-22", \
            f"decision_date should be clock date, got {row[0]!r}"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


def test_d_get_recent_decisions_order_limit_filter():
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        # Insert 5 decisions with different dates + types.
        # NOTE: dates must be in the past or present relative to the
        # sim clock — get_recent_decisions doesn't filter by date, but
        # log_decision stores whatever decision_date we pass.
        for d, ttype in [("2026-09-01", pd.TYPE_SIGN),
                          ("2026-09-15", pd.TYPE_CUT),
                          ("2026-10-01", pd.TYPE_SIGN),
                          ("2026-10-10", pd.TYPE_SCOUT),
                          ("2026-10-20", pd.TYPE_SIGN)]:
            pd.log_decision(conn, ttype, target_fighter_id=1,
                            decision_date=d)
        conn.commit()

        # All 5, newest-first
        all_rows = pd.get_recent_decisions(conn, limit=50)
        assert len(all_rows) == 5, f"expected 5, got {len(all_rows)}"
        assert all_rows[0]["decision_date"] == "2026-10-20", \
            f"newest-first failed: {all_rows[0]['decision_date']}"
        assert all_rows[-1]["decision_date"] == "2026-09-01", \
            f"oldest-last failed: {all_rows[-1]['decision_date']}"

        # Limit
        limited = pd.get_recent_decisions(conn, limit=2)
        assert len(limited) == 2
        assert limited[0]["decision_date"] == "2026-10-20"
        assert limited[1]["decision_date"] == "2026-10-10"

        # Filter by type
        signs = pd.get_recent_decisions(conn, limit=50,
                                        decision_type=pd.TYPE_SIGN)
        assert len(signs) == 3, f"expected 3 signs, got {len(signs)}"
        for r in signs:
            assert r["decision_type"] == "sign"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


def test_e_get_decisions_for_fighter_timeline_order():
    """For the Fighter Profile 'Your History with X' section —
    must return oldest-first so the timeline reads top-to-bottom."""
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        # Fighter 7 was signed, then booked, then cut.
        pd.log_decision(conn, pd.TYPE_SIGN, target_fighter_id=7,
                        decision_date="2026-05-01")
        pd.log_decision(conn, pd.TYPE_BOOK, target_fighter_id=7,
                        target_event_id=123, decision_date="2026-06-15")
        pd.log_decision(conn, pd.TYPE_CUT, target_fighter_id=7,
                        decision_date="2026-08-01")
        conn.commit()

        rows = pd.get_decisions_for_fighter(conn, 7)
        assert len(rows) == 3, f"expected 3, got {len(rows)}"
        # Oldest-first
        assert rows[0]["decision_date"] == "2026-05-01"
        assert rows[0]["decision_type"] == "sign"
        assert rows[1]["decision_date"] == "2026-06-15"
        assert rows[1]["decision_type"] == "book"
        assert rows[2]["decision_date"] == "2026-08-01"
        assert rows[2]["decision_type"] == "cut"

        # Fighter with no decisions → empty list
        empty = pd.get_decisions_for_fighter(conn, 999999)
        assert empty == [], f"expected empty, got {empty}"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


def test_f_get_decisions_since_window():
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        _set_sim_date(conn, "2026-10-15")
        # Decisions: 1 inside 120d window, 1 outside, 1 just inside.
        pd.log_decision(conn, pd.TYPE_SIGN, target_fighter_id=1,
                        decision_date="2026-10-10")  # 5d ago — inside
        pd.log_decision(conn, pd.TYPE_SIGN, target_fighter_id=2,
                        decision_date="2026-06-01")  # >120d ago — outside
        pd.log_decision(conn, pd.TYPE_CUT, target_fighter_id=3,
                        decision_date="2026-06-20")  # ~117d ago — inside
        conn.commit()

        rows = pd.get_decisions_since(conn, days_back=120)
        # Oldest-first
        assert len(rows) == 2, f"expected 2 in window, got {len(rows)}"
        assert rows[0]["decision_date"] == "2026-06-20"
        assert rows[1]["decision_date"] == "2026-10-10"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


def test_g_backfill_idempotent():
    conn = _connect()
    try:
        _cleanup_test_rows(conn)
        # Find a promo with at least 1 active fighter for a meaningful
        # backfill. Promo 1 has 60 active fighters in the world DB.
        promo_row = conn.execute(
            "SELECT promotion_id FROM promotions ORDER BY promotion_id LIMIT 1"
        ).fetchone()
        if not promo_row:
            return True  # no promos — skip
        pid = promo_row[0]

        # First backfill run: should insert sign decisions for the
        # promo's roster + the marker row.
        r1 = pd.backfill_player_decisions_for_promo(conn, pid)
        assert not r1["skipped"], "first run should not be skipped"
        assert r1["signs_backfilled"] > 0, \
            f"expected signs_backfilled > 0, got {r1['signs_backfilled']}"
        n1 = conn.execute("SELECT COUNT(*) FROM player_decisions").fetchone()[0]
        assert n1 == r1["signs_backfilled"] + r1["cuts_backfilled"] + 1, \
            f"expected {r1['signs_backfilled'] + r1['cuts_backfilled'] + 1} " \
            f"rows (signs + cuts + marker), got {n1}"

        # Second run: should be a no-op (marker exists).
        r2 = pd.backfill_player_decisions_for_promo(conn, pid)
        assert r2["skipped"], "second run should be skipped (idempotent)"
        n2 = conn.execute("SELECT COUNT(*) FROM player_decisions").fetchone()[0]
        assert n2 == n1, f"row count changed on second run: {n1} → {n2}"

        # Force=True: re-runs (will double-insert sign decisions, but
        # that's OK for testing — the marker is updated).
        r3 = pd.backfill_player_decisions_for_promo(conn, pid, force=True)
        assert not r3["skipped"], "force=True should not skip"
        return True
    finally:
        _cleanup_test_rows(conn)
        conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

TESTS = [
    ("A. log_decision writes correct row", test_a_log_decision_basic),
    ("B. log_decision rejects invalid type", test_b_log_decision_rejects_invalid_type),
    ("C. log_decision reads sim clock", test_c_log_decision_reads_clock),
    ("D. get_recent_decisions: order + limit + filter",
     test_d_get_recent_decisions_order_limit_filter),
    ("E. get_decisions_for_fighter: oldest-first timeline",
     test_e_get_decisions_for_fighter_timeline_order),
    ("F. get_decisions_since: sim-date window",
     test_f_get_decisions_since_window),
    ("G. backfill_player_decisions_for_promo: idempotent",
     test_g_backfill_idempotent),
]


def main():
    _ensure_schema()
    conn = _connect()
    _save_sim_date(conn)
    conn.close()
    print(f"Testing player_decisions module (Phase R)")
    print(f"DB: {DB_PATH}")
    print(f"Schema version: {_connect().execute('SELECT schema_version FROM schema_meta').fetchone()[0]}")
    print()

    n_pass = 0
    n_fail = 0
    for label, fn in TESTS:
        try:
            ok = fn()
            if ok is None:
                ok = True
        except Exception as e:
            ok = False
            err = f"{type(e).__name__}: {e}"
        else:
            err = ""
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        if not ok:
            print(f"          {err}")
            n_fail += 1
        else:
            n_pass += 1

    # Restore the sim clock to its original state (the tests moved it
    # to make log_decision deterministic).
    conn = _connect()
    _restore_sim_date(conn)
    _cleanup_test_rows(conn)
    conn.close()

    print()
    print(f"Result: {n_pass}/{n_pass + n_fail} PASS")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
