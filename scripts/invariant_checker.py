#!/usr/bin/env python3
"""CAGE EMPIRE — Invariant Checker (HW2.5 / W28).

Verifies 8 world-DB invariants that the simulation must always
satisfy. Distinct from forensic_db_check.py in that it focuses on
GAME-LOGIC invariants (every fight has 2 participants, no retired
fighter is scheduled, etc.) rather than SCHEMA invariants (every
fighter has a fighter_attributes row, no NULLs, etc.).

INVARIANTS CHECKED:
  1. Every fight has exactly 2 participants in fight_participants.
  2. Every event has a valid promotion_id (FK integrity).
  3. Every title has a valid champion (or is vacant).
  4. Every news_items.published_at <= simulation_clock.current_date.
  5. Every active fighter has a valid weight_class_id.
  6. No retired fighter is scheduled for a fight.
  7. No fight has winner_fighter_id = loser_fighter_id.
  8. Every finance_transaction references a valid promotion_id.

Usage:
    python3 scripts/invariant_checker.py
    python3 scripts/invariant_checker.py --verbose   # show every row
    python3 scripts/invariant_checker.py --db-path PATH

Exit codes:
    0 = all invariants hold
    1 = one or more invariants violated
    2 = script error (couldn't run)

CONVENTIONS compliance:
  §6  — Smoke test protocol. This is a diagnostic, not a test.
        Does NOT modify the DB.
  §13 — Design Law: infrastructure that supports every pillar by
        ensuring the world DB stays in a consistent state.
"""
import sys
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))


# Each invariant is (name, description, check_fn).
# check_fn(conn, verbose) returns (passed, count_violations, detail).
results = []
errors = []


def check(name, description, passed, violations, detail=""):
    """Record an invariant check result."""
    results.append((name, description, passed, violations, detail))
    if not passed:
        errors.append((name, description, violations, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}: {detail}")


def _sim_date(conn):
    """Return the current sim date string (or None)."""
    try:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _has_table(conn, table):
    """Return True if the table exists."""
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


# ----------------------------------------------------------------
# Invariant 1: Every fight has exactly 2 participants in
# fight_participants.
# ----------------------------------------------------------------
def inv_1_fight_has_two_participants(conn, verbose=False):
    if not _has_table(conn, "fight_participants"):
        check("inv1_fight_two_participants",
              "Every fight has exactly 2 participants in fight_participants",
              False, -1, "fight_participants table missing")
        return
    # Fights with != 2 participants.
    bad = conn.execute(
        "SELECT f.fight_id, COUNT(fp.fighter_id) as cnt "
        "FROM fights f "
        "LEFT JOIN fight_participants fp ON f.fight_id = fp.fight_id "
        "GROUP BY f.fight_id "
        "HAVING cnt != 2"
    ).fetchall()
    # Also count fights with 0 participants (LEFT JOIN gives NULL → 0).
    zero = conn.execute(
        "SELECT COUNT(*) FROM fights f "
        "WHERE NOT EXISTS (SELECT 1 FROM fight_participants fp "
        "                  WHERE fp.fight_id = f.fight_id)"
    ).fetchone()[0]
    total_violations = len(bad)
    passed = (total_violations == 0)
    detail = (f"{total_violations} fights with != 2 participants "
              f"({zero} with 0)")
    check("inv1_fight_two_participants",
          "Every fight has exactly 2 participants in fight_participants",
          passed, total_violations, detail)
    if verbose and bad:
        for fight_id, cnt in bad[:10]:
            print(f"         fight {fight_id}: {cnt} participants")


# ----------------------------------------------------------------
# Invariant 2: Every event has a valid promotion_id (FK integrity).
# ----------------------------------------------------------------
def inv_2_event_valid_promotion(conn, verbose=False):
    if not _has_table(conn, "events"):
        check("inv2_event_valid_promotion",
              "Every event has a valid promotion_id",
              False, -1, "events table missing")
        return
    bad = conn.execute(
        "SELECT e.event_id, e.event_name, e.promotion_id "
        "FROM events e "
        "LEFT JOIN promotions p ON e.promotion_id = p.promotion_id "
        "WHERE p.promotion_id IS NULL"
    ).fetchall()
    passed = (len(bad) == 0)
    detail = (f"{len(bad)} events with invalid promotion_id"
              if bad else "all events reference valid promotions")
    check("inv2_event_valid_promotion",
          "Every event has a valid promotion_id",
          passed, len(bad), detail)
    if verbose and bad:
        for event_id, name, pid in bad[:10]:
            print(f"         event {event_id} ({name}): promotion_id={pid}")


# ----------------------------------------------------------------
# Invariant 3: Every title has a valid champion (or is vacant).
# ----------------------------------------------------------------
def inv_3_title_valid_champion(conn, verbose=False):
    if not _has_table(conn, "titles"):
        check("inv3_title_valid_champion",
              "Every title has a valid champion (or is vacant)",
              False, -1, "titles table missing")
        return
    # Active titles (is_vacant=0) must reference an existing fighter.
    bad = conn.execute(
        "SELECT t.title_id, t.weight_class_id, t.promotion_id, "
        "       t.current_champion_fighter_id "
        "FROM titles t "
        "LEFT JOIN fighters f ON t.current_champion_fighter_id = f.fighter_id "
        "WHERE t.is_vacant = 0 "
        "AND t.current_champion_fighter_id IS NOT NULL "
        "AND f.fighter_id IS NULL"
    ).fetchall()
    # Also: active titles must NOT have a NULL champion (is_vacant=0
    # but current_champion_fighter_id IS NULL is a state corruption).
    null_champ = conn.execute(
        "SELECT COUNT(*) FROM titles "
        "WHERE is_vacant = 0 AND current_champion_fighter_id IS NULL"
    ).fetchone()[0]
    total = len(bad) + null_champ
    passed = (total == 0)
    detail = (f"{len(bad)} titles with orphan champion + "
              f"{null_champ} active titles with NULL champion"
              if total else "all titles have valid champions or are vacant")
    check("inv3_title_valid_champion",
          "Every title has a valid champion (or is vacant)",
          passed, total, detail)
    if verbose and bad:
        for tid, wcid, pid, champ in bad[:10]:
            print(f"         title {tid} (wc={wcid} promo={pid}): "
                  f"champion_fighter_id={champ} (orphan)")


# ----------------------------------------------------------------
# Invariant 4: Every news_items.published_at <= sim current_date.
# ----------------------------------------------------------------
def inv_4_news_date_not_future(conn, verbose=False):
    if not _has_table(conn, "news_items"):
        check("inv4_news_date_not_future",
              "Every news_items.published_at <= simulation_clock.current_date",
              False, -1, "news_items table missing")
        return
    sim_date = _sim_date(conn)
    if not sim_date:
        check("inv4_news_date_not_future",
              "Every news_items.published_at <= simulation_clock.current_date",
              False, -1, "simulation_clock missing — cannot check")
        return
    bad = conn.execute(
        "SELECT news_item_id, headline, published_at FROM news_items "
        "WHERE published_at > ? ORDER BY published_at DESC LIMIT 50",
        (sim_date,),
    ).fetchall()
    passed = (len(bad) == 0)
    detail = (f"{len(bad)} news items with published_at > {sim_date}"
              if bad else f"all news items published_at <= {sim_date}")
    check("inv4_news_date_not_future",
          "Every news_items.published_at <= simulation_clock.current_date",
          passed, len(bad), detail)
    if verbose and bad:
        for nid, headline, pub in bad[:10]:
            print(f"         news {nid} ({headline!r}): published_at={pub}")


# ----------------------------------------------------------------
# Invariant 5: Every active fighter has a valid weight_class_id.
# ----------------------------------------------------------------
def inv_5_active_fighter_valid_weight_class(conn, verbose=False):
    if not _has_table(conn, "fighters"):
        check("inv5_active_fighter_valid_weight_class",
              "Every active fighter has a valid weight_class_id",
              False, -1, "fighters table missing")
        return
    # Active fighters (is_active=1, is_retired=0) whose weight_class_id
    # is NULL OR doesn't exist in weight_classes.
    bad = conn.execute(
        "SELECT f.fighter_id, f.first_name || ' ' || f.last_name, "
        "       f.weight_class_id "
        "FROM fighters f "
        "LEFT JOIN weight_classes wc ON f.weight_class_id = wc.weight_class_id "
        "WHERE f.is_active = 1 AND f.is_retired = 0 "
        "AND (f.weight_class_id IS NULL OR wc.weight_class_id IS NULL)"
    ).fetchall()
    passed = (len(bad) == 0)
    detail = (f"{len(bad)} active fighters with invalid weight_class_id"
              if bad else "all active fighters have valid weight_class_id")
    check("inv5_active_fighter_valid_weight_class",
          "Every active fighter has a valid weight_class_id",
          passed, len(bad), detail)
    if verbose and bad:
        for fid, name, wcid in bad[:10]:
            print(f"         fighter {fid} ({name}): weight_class_id={wcid}")


# ----------------------------------------------------------------
# Invariant 6: No retired fighter is scheduled for a fight.
# ----------------------------------------------------------------
def inv_6_no_retired_fighter_scheduled(conn, verbose=False):
    if not _has_table(conn, "fighters") or not _has_table(conn, "fights"):
        check("inv6_no_retired_fighter_scheduled",
              "No retired fighter is scheduled for a fight",
              False, -1, "fighters or fights table missing")
        return
    sim_date = _sim_date(conn)
    # Look at scheduled (unresolved) fights: winner_fighter_id IS NULL
    # means the fight hasn't happened yet. The fight's participants
    # (stored on fights.winner_fighter_id / loser_fighter_id for
    # resolved fights, OR on fight_participants for scheduled fights)
    # must not include any retired fighter.
    #
    # Check both columns on fights (the legacy storage) AND
    # fight_participants (the canonical storage post-HW1.2 backfill).
    bad_rows = []
    if sim_date:
        # Scheduled fights via the fights table (winner/loser columns
        # populated even for scheduled fights in some legacy paths).
        bad = conn.execute(
            "SELECT f.fight_id, f.winner_fighter_id, f.loser_fighter_id, "
            "       wf.is_retired as winner_retired, lf.is_retired as loser_retired, "
            "       wf.first_name || ' ' || wf.last_name as winner_name, "
            "       lf.first_name || ' ' || lf.last_name as loser_name "
            "FROM fights f "
            "JOIN events e ON f.event_id = e.event_id "
            "LEFT JOIN fighters wf ON f.winner_fighter_id = wf.fighter_id "
            "LEFT JOIN fighters lf ON f.loser_fighter_id = lf.fighter_id "
            "WHERE e.status IN ('scheduled', 'card_confirmed') "
            "AND e.event_date >= ? "
            "AND (wf.is_retired = 1 OR lf.is_retired = 1)",
            (sim_date,),
        ).fetchall()
        for row in bad:
            bad_rows.append(row)
    # Also check fight_participants (canonical storage).
    if _has_table(conn, "fight_participants") and sim_date:
        bad_fp = conn.execute(
            "SELECT DISTINCT fp.fight_id, fp.fighter_id, "
            "       f.first_name || ' ' || f.last_name, f.is_retired "
            "FROM fight_participants fp "
            "JOIN fights fi ON fp.fight_id = fi.fight_id "
            "JOIN events e ON fi.event_id = e.event_id "
            "JOIN fighters f ON fp.fighter_id = f.fighter_id "
            "WHERE e.status IN ('scheduled', 'card_confirmed') "
            "AND e.event_date >= ? "
            "AND f.is_retired = 1",
            (sim_date,),
        ).fetchall()
        bad_rows.extend(bad_fp)
    # Dedupe by (fight_id, fighter_id-ish).
    passed = (len(bad_rows) == 0)
    detail = (f"{len(bad_rows)} scheduled fights with retired fighter(s)"
              if bad_rows else "no retired fighters in scheduled fights")
    check("inv6_no_retired_fighter_scheduled",
          "No retired fighter is scheduled for a fight",
          passed, len(bad_rows), detail)
    if verbose and bad_rows:
        for row in bad_rows[:10]:
            print(f"         retired fighter in scheduled fight: {row}")


# ----------------------------------------------------------------
# Invariant 7: No fight has winner_fighter_id = loser_fighter_id.
# ----------------------------------------------------------------
def inv_7_no_self_fight(conn, verbose=False):
    if not _has_table(conn, "fights"):
        check("inv7_no_self_fight",
              "No fight has winner_fighter_id = loser_fighter_id",
              False, -1, "fights table missing")
        return
    bad = conn.execute(
        "SELECT fight_id, winner_fighter_id, loser_fighter_id "
        "FROM fights "
        "WHERE winner_fighter_id IS NOT NULL "
        "AND loser_fighter_id IS NOT NULL "
        "AND winner_fighter_id = loser_fighter_id"
    ).fetchall()
    passed = (len(bad) == 0)
    detail = (f"{len(bad)} fights where winner == loser"
              if bad else "no self-fights")
    check("inv7_no_self_fight",
          "No fight has winner_fighter_id = loser_fighter_id",
          passed, len(bad), detail)
    if verbose and bad:
        for fight_id, wid, lid in bad[:10]:
            print(f"         fight {fight_id}: winner=loser={wid}")


# ----------------------------------------------------------------
# Invariant 8: Every finance_transaction references a valid
# promotion_id.
# ----------------------------------------------------------------
def inv_8_finance_txn_valid_promotion(conn, verbose=False):
    if not _has_table(conn, "finance_transactions"):
        check("inv8_finance_txn_valid_promotion",
              "Every finance_transaction references a valid promotion_id",
              False, -1, "finance_transactions table missing")
        return
    # finance_transactions.promotion_id is nullable (some transactions
    # are not tied to a specific promotion). Only flag non-NULL
    # promotion_ids that don't exist in promotions.
    bad = conn.execute(
        "SELECT ft.transaction_id, ft.promotion_id, ft.description "
        "FROM finance_transactions ft "
        "LEFT JOIN promotions p ON ft.promotion_id = p.promotion_id "
        "WHERE ft.promotion_id IS NOT NULL "
        "AND p.promotion_id IS NULL"
    ).fetchall()
    passed = (len(bad) == 0)
    detail = (f"{len(bad)} finance_transactions with invalid promotion_id"
              if bad else "all finance_transactions reference valid promotions")
    check("inv8_finance_txn_valid_promotion",
          "Every finance_transaction references a valid promotion_id",
          passed, len(bad), detail)
    if verbose and bad:
        for tid, pid, desc in bad[:10]:
            print(f"         txn {tid} (promo={pid}): {desc!r}")


def main():
    print("=" * 72)
    print("CAGE EMPIRE — Invariant Checker (HW2.5 / W28)")
    print("=" * 72)
    # Allow --db-path override.
    db_path = DB_PATH
    if "--db-path" in sys.argv:
        idx = sys.argv.index("--db-path")
        if idx + 1 < len(sys.argv):
            db_path = Path(sys.argv[idx + 1])
    verbose = "--verbose" in sys.argv
    print(f"DB: {db_path}")
    print()

    if not db_path.exists():
        print(f"FATAL: DB file does not exist at {db_path}")
        sys.exit(2)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Run all 8 invariants.
    print("--- 8 invariants ---")
    inv_1_fight_has_two_participants(conn, verbose)
    inv_2_event_valid_promotion(conn, verbose)
    inv_3_title_valid_champion(conn, verbose)
    inv_4_news_date_not_future(conn, verbose)
    inv_5_active_fighter_valid_weight_class(conn, verbose)
    inv_6_no_retired_fighter_scheduled(conn, verbose)
    inv_7_no_self_fight(conn, verbose)
    inv_8_finance_txn_valid_promotion(conn, verbose)

    # Summary.
    print("\n" + "=" * 72)
    print("INVARIANT CHECKER SUMMARY")
    print("=" * 72)
    total = len(results)
    passed = sum(1 for r in results if r[2])
    failed = len(errors)
    print(f"Total invariants: {total}")
    print(f"  PASS: {passed}")
    print(f"  FAIL: {failed}")
    print()
    if errors:
        print("VIOLATIONS:")
        for name, desc, violations, detail in errors:
            print(f"  [FAIL] {name}: {detail}")
            print(f"         ({desc})")
        print()
        print("RESULT: FAILED — one or more invariants violated.")
        sys.exit(1)
    else:
        print("RESULT: ALL INVARIANTS HOLD — world DB is consistent.")
        sys.exit(0)


if __name__ == "__main__":
    main()
