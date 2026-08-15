#!/usr/bin/env python3
"""FIGHT-ENGINE-TUNE — Fight distribution acceptance test.

Verifies the Issue 1-4 fight-engine fixes by running 200 fights
(100 full-engine + 100 simplified-engine) on a fresh copy of the
reseeded world DB and asserting the result_type distribution
falls within target ranges.

Targets (per the brief):
  - KO/TKO          20-40%
  - Submission      10-25%
  - Decision (UD+SD) 35-55%
  - Split decision  < 15%   (subset of Decision)
  - NULL results    = 0%

The test mixes full-engine fights (player path) with simplified-
engine fights (rival-AI path) so the distribution reflects the
REAL mix the simulation produces over time (rival AI auto-resolves
~80% of fights via the simplified path; the player resolves the
remaining ~20% via the full beat engine).

Pipeline:
  1. Copy data/cage_empire.db -> data/cage_empire_dist_test.db
     (so the world DB is never modified).
  2. Clear pre-existing unresolved fights with event_date <= sim_date.
  3. Pick 200 random same-weight-class fighter pairs.
  4. Create ONE event + 200 fights + 400 participants on that event
     (using a sim_date-aligned event_date so the resolve_next_fight
     pick-query selects them — the pick-query filters by
     event_date <= sim_date for the rival-AI path).
  5. Resolve 100 fights with the full beat engine
     (skip_beat_detail=False) + 100 with the simplified engine
     (skip_beat_detail=True).
  6. Tally the result_type distribution + assert all targets.

Exit code 0 = PASS, 1 = FAIL.

Run from project root:
    python3 scripts/test_fight_distribution.py
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
TEST_DB = PROJECT_DIR / "data" / "cage_empire_dist_test.db"

os.environ["CAGE_EMPIRE_DB_PATH"] = str(TEST_DB)
os.environ.setdefault("CAGE_EMPIRE_ALLOW_FRESH", "1")

sys.path.insert(0, str(SRC_DIR))

# Importing app.py pulls in tkinter. The import itself does not require
# a display (only tk.Tk() does), so this is safe in headless contexts.
import app  # noqa: E402


N_FIGHTS_FULL = 100         # player path (full beat engine)
N_FIGHTS_SIMPLIFIED = 100   # rival-AI path (simplified engine)
RANDOM_SEED = 42            # reproducible: pins which random pairs + RNG draws

# Target distribution (per the FIGHT-ENGINE-TUNE brief).
# Each entry: (label, result_type(s), min_pct, max_pct).
TARGETS = [
    # label                  result_types                  min_pct  max_pct
    ("KO/TKO",              ("ko_tko",),                    20,     40),
    ("Submission",          ("submission",),                10,     25),
    ("Decision (UD+SD)",    ("unanimous_decision",
                             "split_decision"),              35,     55),
    ("Split decision",      ("split_decision",),             0,     15),
    ("NULL result_type",    (None,),                        0,      0),  # special-cased
]


def copy_world_db():
    """Copy the world DB to a throwaway test DB (idempotent)."""
    if not WORLD_DB.exists():
        print(f"FAIL: world DB not found at {WORLD_DB}")
        sys.exit(1)
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.copy2(WORLD_DB, TEST_DB)
    print(f"Copied world DB -> {TEST_DB} ({TEST_DB.stat().st_size // 1024} KB)")


def clear_pre_existing_unresolved_fights(conn):
    """Delete unresolved fights whose event_date <= sim_date.

    The world DB has a handful of unresolved fights. They have lower
    fight_ids than my new test fights, so resolve_next_fight would
    pick them first — contaminating the distribution with non-test
    matchups. Deleting them ensures only my 200 test fights are
    eligible for resolution.
    """
    sim_date_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = sim_date_row[0] if sim_date_row else "2026-07-20"

    cur = conn.execute(
        "DELETE FROM fight_participants WHERE fight_id IN ("
        "  SELECT f.fight_id FROM fights f "
        "  JOIN events e ON e.event_id=f.event_id "
        "  WHERE f.winner_fighter_id IS NULL "
        "  AND f.result_type IS NULL "
        "  AND e.event_date <= ?)",
        (sim_date,),
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


def pick_random_pairs(conn, n, seed=RANDOM_SEED):
    """Pick n random same-weight-class fighter pairs."""
    rng = random.Random(seed)
    wc_rows = conn.execute(
        "SELECT wc.weight_class_id, COUNT(f.fighter_id) "
        "FROM weight_classes wc "
        "JOIN fighters f ON f.weight_class_id=wc.weight_class_id "
        "WHERE f.is_active=1 AND f.is_retired=0 "
        "GROUP BY wc.weight_class_id "
        "HAVING COUNT(f.fighter_id) >= 2"
    ).fetchall()
    if not wc_rows:
        print("FAIL: no weight classes with >=2 active fighters found.")
        sys.exit(1)
    print(f"Sampling {n} pairs across {len(wc_rows)} weight classes.")
    pairs = []
    for _ in range(n):
        wc_id, _c = rng.choice(wc_rows)
        ids = [r[0] for r in conn.execute(
            "SELECT fighter_id FROM fighters "
            "WHERE weight_class_id=? AND is_active=1 AND is_retired=0",
            (wc_id,),
        ).fetchall()]
        a, b = rng.sample(ids, 2)
        pairs.append((a, b, wc_id))
    return pairs


def create_event_and_fights(conn, pairs, label):
    """Create 1 event + N fights + 2N participants on that event.

    Uses a sim_date-aligned event_date so the resolve_next_fight
    pick-query (which filters by event_date <= sim_date for the
    rival-AI path) selects these test fights.
    """
    sim_date = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]

    row = conn.execute(
        "SELECT promotion_id, venue_id, market_id FROM events "
        "ORDER BY event_id LIMIT 1"
    ).fetchone()
    if row is None:
        print("FAIL: no existing events to borrow venue/market/promo from.")
        sys.exit(1)
    promo_id, venue_id, market_id = row

    event_id = conn.execute(
        "INSERT INTO events (promotion_id, venue_id, market_id, "
        "event_name, event_date, event_type, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
        (promo_id, venue_id, market_id,
         f"FIGHT-ENGINE-TUNE {label}", sim_date, "fight_night"),
    ).lastrowid

    fight_ids = []
    for a_id, b_id, wc_id in pairs:
        fight_id = conn.execute(
            "INSERT INTO fights (event_id, weight_class_id, bout_type, "
            "card_slot, is_title_fight, round_limit, scheduled_rounds) "
            "VALUES (?, ?, ?, ?, 0, 3, 3)",
            (event_id, wc_id, "prelim", "prelim"),
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
    print(f"Created event_id={event_id} ({label}) with {len(fight_ids)} fights.")
    return event_id, fight_ids


def run_fights(conn, n, skip_beat_detail, label):
    """Resolve n fights via resolve_next_fight.

    Returns a list of (fight_id, result_type, winner_id).
    """
    random.seed(RANDOM_SEED)
    results = []
    for i in range(n):
        fid = app.resolve_next_fight(conn, skip_beat_detail=skip_beat_detail)
        conn.commit()
        if fid is None:
            print(f"FAIL: resolve_next_fight returned None on iteration {i} ({label})")
            sys.exit(1)
        row = conn.execute(
            "SELECT fight_id, result_type, winner_fighter_id FROM fights WHERE fight_id=?",
            (fid,),
        ).fetchone()
        results.append(row)
        if (i + 1) % 25 == 0:
            print(f"  ...{label}: resolved {i+1}/{n}")
    return results


def print_distribution(full_results, simp_results):
    """Print the result-type distribution + PASS/FAIL per target."""
    all_results = full_results + simp_results
    n = len(all_results)
    result_types = Counter(r[1] for r in all_results)  # None counts too

    sep = "=" * 88
    print(sep)
    print(f"FIGHT-ENGINE-TUNE DISTRIBUTION TEST — {n} fights "
          f"({len(full_results)} full + {len(simp_results)} simplified)")
    print(sep)

    # Per-engine breakdown.
    print(f"\n{'Engine':<14}{'Result type':<24}{'Count':>8}{'%':>10}")
    print("-" * 56)
    for label, results in (("FULL", full_results), ("SIMPLIFIED", simp_results)):
        c = Counter(r[1] for r in results)
        sub_n = len(results)
        for rt, count in c.most_common():
            rt_str = "(NULL)" if rt is None else rt
            print(f"{label:<14}{rt_str:<24}{count:>8}{count/sub_n*100:>9.1f}%")
        print("-" * 56)

    # Combined distribution.
    print(f"\n{'Result type':<24}{'Count':>8}{'%':>10}  {'Target':>14}  Status")
    print("-" * 88)
    overall_ok = True
    for label, types, min_pct, max_pct in TARGETS:
        count = sum(result_types.get(t, 0) for t in types)
        pct = count / n * 100
        target_str = f"{min_pct}-{max_pct}%" if min_pct != max_pct else f"{min_pct}%"
        ok = min_pct <= pct <= max_pct
        status = "PASS" if ok else "FAIL"
        if not ok:
            overall_ok = False
        type_str = "(NULL)" if types == (None,) else "+".join(types)
        print(f"{type_str:<24}{count:>8}{pct:>9.1f}%  {target_str:>14}  {status}")

    # List any "other" result_types not in TARGETS.
    known = set()
    for _label, types, _lo, _hi in TARGETS:
        known.update(t for t in types if t is not None)
    extras = {t: c for t, c in result_types.items() if t not in known and t is not None}
    if extras:
        print("-" * 88)
        print("Other (un-categorized) result types:")
        for t, c in sorted(extras.items(), key=lambda x: -x[1]):
            print(f"  {t:<22} {c:>6} {c / n * 100:>6.1f}%")

    print(sep)
    return overall_ok


def main():
    copy_world_db()
    conn = sqlite3.connect(TEST_DB)
    conn.execute("PRAGMA foreign_keys = ON;")

    clear_pre_existing_unresolved_fights(conn)

    # Pick 200 random pairs (100 for full + 100 for simplified).
    pairs_full = pick_random_pairs(conn, N_FIGHTS_FULL, seed=RANDOM_SEED)
    pairs_simp = pick_random_pairs(conn, N_FIGHTS_SIMPLIFIED, seed=RANDOM_SEED + 1)

    _evt1, _fids1 = create_event_and_fights(conn, pairs_full, "FULL")
    _evt2, _fids2 = create_event_and_fights(conn, pairs_simp, "SIMPLIFIED")

    print(f"\nResolving {N_FIGHTS_FULL} fights with the FULL beat engine "
          f"(skip_beat_detail=False)...")
    full_results = run_fights(conn, N_FIGHTS_FULL, skip_beat_detail=False, label="FULL")

    print(f"\nResolving {N_FIGHTS_SIMPLIFIED} fights with the SIMPLIFIED engine "
          f"(skip_beat_detail=True)...")
    simp_results = run_fights(conn, N_FIGHTS_SIMPLIFIED, skip_beat_detail=True, label="SIMPLIFIED")

    ok = print_distribution(full_results, simp_results)

    # Hard check: NULL result_type count.
    null_count = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE winner_fighter_id IS NOT NULL "
        "AND result_type IS NULL"
    ).fetchone()[0]
    print(f"\nNULL result_type fights (hard check): {null_count}")
    if null_count != 0:
        ok = False
        print(f"  FAIL: expected 0 NULL result_type fights, got {null_count}")

    print()
    if ok:
        print("OVERALL: PASS — all FIGHT-ENGINE-TUNE distribution targets met.")
        sys.exit(0)
    else:
        print("OVERALL: FAIL — one or more distribution targets not met.")
        sys.exit(1)


if __name__ == "__main__":
    main()
