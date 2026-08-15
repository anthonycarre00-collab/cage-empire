#!/usr/bin/env python3
"""CR-11 acceptance test — fight engine result-type distribution.

Verifies the doctor_stoppage fix (docs/CR10_14_FIX_PLAN.md §2) by
running 100 random sim-fights against a copy of the world DB and
checking the result_type distribution falls within target ranges.

Pipeline:
  1. Copy data/cage_empire.db → data/cage_empire_balance_test.db
     (so the world DB is never modified).
  2. Pick 100 random fighter pairs (same weight class per pair, mix
     of weight classes + skill levels across the 100).
  3. Create ONE new event + 100 new fights + 200 fight_participants
     on that event (so the event stays "scheduled" until all 100
     fights are resolved — no auto-schedule_next_event side effects
     mid-run).
  4. Call app.resolve_next_fight(conn) 100 times — this is the same
     function the sim uses (it picks the lowest-fight_id unresolved
     fight, runs the beat-level engine, writes fight_history +
     rankings + news + commentary, returns the fight_id).
  5. Read result_type from each fight, tally the distribution.
  6. Print a distribution table with target ranges + PASS/FAIL.

Acceptance:
  - No single result_type > 50% (was 54% doctor_stoppage).
  - Each result_type within ±10% of its target per CR-11 §2.3.

Exit code 0 = PASS, 1 = FAIL.

Run from project root:
    python3 scripts/test_fight_engine_balance.py
"""
import os
import random
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
WORLD_DB = PROJECT_DIR / "data" / "cage_empire.db"
TEST_DB = PROJECT_DIR / "data" / "cage_empire_balance_test.db"

os.environ["CAGE_EMPIRE_DB_PATH"] = str(TEST_DB)
os.environ.setdefault("CAGE_EMPIRE_ALLOW_FRESH", "1")

sys.path.insert(0, str(SRC_DIR))

# Importing app.py pulls in tkinter. The import itself does not require
# a display (only tk.Tk() does), so this is safe in headless contexts
# (mirrors scripts/test_fight_resolver.py).
import app  # noqa: E402


N_FIGHTS = 100
RANDOM_SEED = 42  # reproducible: pins which random pairs + RNG draws

# Target distribution per docs/CR10_14_FIX_PLAN.md §2.3.
# Each entry: (label, result_type(s), target_lo, target_hi, acceptable_lo, acceptable_hi)
# "Acceptable" = target ± 10pp (per spec "Acceptable tolerance: ±10% per category").
# Pass/fail uses the ACCEPTABLE range. The raw target range is shown for context.
TARGETS = [
    # label                  types                     tgt_lo  tgt_hi  acc_lo  acc_hi
    ("KO/TKO",             ("ko_tko",),                25,     35,     15,     45),
    ("Submission",         ("submission",),            10,     20,      0,     30),
    ("Unanimous decision", ("unanimous_decision",),    25,     40,     15,     50),
    ("Split decision",     ("split_decision",),         5,     10,      0,     20),
    ("Doctor stoppage",    ("doctor_stoppage",),        3,     10,      0,     20),
    ("Draw",               ("draw",),                   1,      5,      0,     15),
    ("DQ",                 ("dq",),                     0,      3,      0,     13),
]

# Hard cap: no single result_type > 50% (was 54% doctor_stoppage pre-fix).
MAX_RESULT_TYPE_SHARE = 50


def copy_world_db():
    """Copy the world DB to a throwaway test DB (idempotent)."""
    if not WORLD_DB.exists():
        print(f"FAIL: world DB not found at {WORLD_DB}")
        sys.exit(1)
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.copy2(WORLD_DB, TEST_DB)
    print(f"Copied world DB → {TEST_DB} ({TEST_DB.stat().st_size // 1024} KB)")


def clear_pre_existing_unresolved_fights(conn):
    """Delete unresolved fights + participants from the world DB copy.

    The world DB has a handful of unresolved fights (left over from the
    90-day audit sim run). They have lower fight_ids than my new test
    fights, so resolve_next_fight would pick them first — contaminating
    the distribution with non-test matchups. Deleting them (and their
    participants, via the FK ON DELETE CASCADE) ensures only my 100
    test fights are eligible for resolution.
    """
    cur = conn.execute(
        "DELETE FROM fight_participants WHERE fight_id IN "
        "(SELECT fight_id FROM fights WHERE winner_fighter_id IS NULL "
        "AND result_type IS NULL)"
    )
    n_part = cur.rowcount
    cur = conn.execute(
        "DELETE FROM fights WHERE winner_fighter_id IS NULL "
        "AND result_type IS NULL"
    )
    n_fights = cur.rowcount
    conn.commit()
    if n_fights:
        print(f"Cleared {n_fights} pre-existing unresolved fights "
              f"({n_part} participants) from world DB copy.")


def pick_random_pairs(conn, n=100, seed=RANDOM_SEED):
    """Pick n random same-weight-class fighter pairs.

    Samples one weight class per pair (uniform across the 13 weight
    classes — gives a mix of weight classes across the 100 pairs),
    then samples 2 distinct fighters from that class. Skill levels
    mix naturally because the world DB has fighters across the
    full attribute range (avg ~52, std ~15).
    """
    rng = random.Random(seed)
    # Weight classes with at least 2 fighters.
    wc_rows = conn.execute(
        "SELECT wc.weight_class_id, wc.name, COUNT(f.fighter_id) AS c "
        "FROM weight_classes wc JOIN fighters f ON f.weight_class_id=wc.weight_class_id "
        "GROUP BY wc.weight_class_id HAVING c >= 2 ORDER BY wc.weight_class_id"
    ).fetchall()
    if not wc_rows:
        print("FAIL: no weight classes with >=2 fighters found.")
        sys.exit(1)
    print(f"Sampling {n} pairs across {len(wc_rows)} weight classes (uniform per pair).")
    pairs = []
    for _ in range(n):
        wc_id, wc_name, _c = rng.choice(wc_rows)
        # Pick 2 distinct fighters from this weight class.
        fighter_rows = conn.execute(
            "SELECT fighter_id FROM fighters WHERE weight_class_id=? "
            "ORDER BY fighter_id",
            (wc_id,),
        ).fetchall()
        ids = [r[0] for r in fighter_rows]
        a, b = rng.sample(ids, 2)
        pairs.append((a, b, wc_id, wc_name))
    return pairs


def create_balance_event_and_fights(conn, pairs):
    """Create 1 event + N fights + 2N participants on that event.

    Putting all 100 fights on ONE event keeps the event in 'scheduled'
    status until all fights resolve (event only auto-completes when
    every fight has a winner) — prevents schedule_next_event from
    firing mid-run and creating extra fights that would interfere
    with the lowest-fight_id pick order.

    Uses high event_id + fight_id offsets (1_000_000) so they don't
    collide with auto-scheduled next-event rows.
    """
    # Pick a deterministic venue/market/promo from the existing world.
    row = conn.execute(
        "SELECT promotion_id, venue_id, market_id FROM events "
        "ORDER BY event_id LIMIT 1"
    ).fetchone()
    if row is None:
        print("FAIL: no existing events to borrow venue/market/promo from.")
        sys.exit(1)
    promo_id, venue_id, market_id = row

    # Use a future event_date so we don't clash with the sim clock's
    # "today" (which would trigger tick processing side effects).
    event_date = "2099-12-31"
    event_name = "CR-11 Balance Test Event"
    event_id = conn.execute(
        "INSERT INTO events (promotion_id, venue_id, market_id, "
        "event_name, event_date, event_type, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
        (promo_id, venue_id, market_id, event_name, event_date, "fight_night"),
    ).lastrowid

    fight_ids = []
    for idx, (a_id, b_id, wc_id, _wc_name) in enumerate(pairs):
        card_slot = "prelim"
        bout_type = "prelim"
        fight_id = conn.execute(
            "INSERT INTO fights (event_id, weight_class_id, bout_type, "
            "card_slot, is_title_fight, round_limit, scheduled_rounds) "
            "VALUES (?, ?, ?, ?, 0, 3, 3)",
            (event_id, wc_id, bout_type, card_slot),
        ).lastrowid
        conn.execute(
            "INSERT INTO fight_participants (fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'red', 0)",
            (fight_id, a_id),
        )
        conn.execute(
            "INSERT INTO fight_participants (fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'blue', 0)",
            (fight_id, b_id),
        )
        fight_ids.append(fight_id)
    conn.commit()
    print(f"Created event_id={event_id} with {len(fight_ids)} fights.")
    return event_id, fight_ids


def run_fights(conn, fight_ids):
    """Resolve each fight in fight_id order via resolve_next_fight.

    Returns a list of (fight_id, result_type, winner_id, finish_round, finish_time).
    """
    random.seed(RANDOM_SEED)  # pin the engine's RNG draws for reproducibility
    results = []
    for i, expected_fid in enumerate(fight_ids, 1):
        resolved = app.resolve_next_fight(conn)
        if resolved is None:
            print(f"FAIL: resolve_next_fight returned None on iteration {i}")
            sys.exit(1)
        conn.commit()
        row = conn.execute(
            "SELECT fight_id, result_type, winner_fighter_id, "
            "finish_round, finish_time FROM fights WHERE fight_id=?",
            (resolved,),
        ).fetchone()
        actual_fid, result_type, winner_id, finish_round, finish_time = row
        if actual_fid != expected_fid:
            print(f"WARN: iter {i} resolved fight_id={actual_fid} (expected {expected_fid})")
        results.append((actual_fid, result_type, winner_id, finish_round, finish_time))
        if i % 10 == 0:
            print(f"  ...resolved {i}/{len(fight_ids)}")
    return results


def print_distribution(results):
    """Print the result-type distribution table + PASS/FAIL per category."""
    result_types = Counter(r[1] for r in results)
    n = len(results)
    sep = "=" * 86
    print(sep)
    print(f"CR-11 FIGHT ENGINE BALANCE TEST — {n} SIM-FIGHTS")
    print(sep)
    print(f"{'Result type':<22} {'Count':>6} {'%':>7}  {'Target':>10}  {'Acceptable':>12}  Status")
    print("-" * 86)

    overall_ok = True
    for label, types, tgt_lo, tgt_hi, acc_lo, acc_hi in TARGETS:
        count = sum(result_types.get(t, 0) for t in types)
        pct = count / n * 100
        target_str = f"{tgt_lo}-{tgt_hi}%"
        acc_str = f"{acc_lo}-{acc_hi}%"
        ok = acc_lo <= pct <= acc_hi
        status = "PASS" if ok else "FAIL"
        if not ok:
            overall_ok = False
        print(f"{label:<22} {count:>6} {pct:>6.1f}%  {target_str:>10}  {acc_str:>12}  {status}")

    # Also list any "other" result_types not in TARGETS.
    known = set()
    for _label, types, _tlo, _thi, _alo, _ahi in TARGETS:
        known.update(types)
    extras = {t: c for t, c in result_types.items() if t not in known}
    if extras:
        print("-" * 86)
        print("Other (un-categorized) result types:")
        for t, c in sorted(extras.items(), key=lambda x: -x[1]):
            print(f"  {t:<22} {c:>6} {c / n * 100:>6.1f}%")

    print("-" * 86)
    # Hard cap assertion: no single result_type > 50%.
    max_rt_name, max_rt_count = max(result_types.items(), key=lambda x: x[1])
    max_pct = max_rt_count / n * 100
    cap_ok = max_pct <= MAX_RESULT_TYPE_SHARE
    cap_status = "PASS" if cap_ok else "FAIL"
    if not cap_ok:
        overall_ok = False
    print(f"Hard cap (no single type > {MAX_RESULT_TYPE_SHARE}%):  "
          f"top='{max_rt_name}' {max_rt_count}/{n} = {max_pct:.1f}%  {cap_status}")
    print(sep)
    return overall_ok


def main():
    copy_world_db()
    conn = sqlite3.connect(TEST_DB)
    conn.execute("PRAGMA foreign_keys = ON;")

    clear_pre_existing_unresolved_fights(conn)
    pairs = pick_random_pairs(conn, n=N_FIGHTS, seed=RANDOM_SEED)
    _event_id, fight_ids = create_balance_event_and_fights(conn, pairs)
    results = run_fights(conn, fight_ids)
    ok = print_distribution(results)

    print()
    if ok:
        print("OVERALL: PASS — all result-type categories within target ranges.")
        sys.exit(0)
    else:
        print("OVERALL: FAIL — one or more result-type categories out of range.")
        sys.exit(1)


if __name__ == "__main__":
    main()
