#!/usr/bin/env python3
"""RESEED Step 7 — Reseed rivalries.

Find all fighter pairs who've fought 2+ times (from backfilled
fight_history, both fighters in DB 1..4000). Create rivalry rows:
  * bad_blood    : pairs with a split_decision or DQ in their history
  * title_rivalry: pairs who fought for a title (title_at_stake=1)
  * rematch_hungry : pairs with 1-1 or 0-0-1 record
  * callout      : ~5% of remaining pairs (random)

Target: ~300-400 rivalries total.
Heat levels: bad_blood=70, title_rivalry=60, rematch_hungry=40, callout=30
"""
import os
import random
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

HEAT_BY_TYPE = {
    "bad_blood": 70,
    "title_rivalry": 60,
    "rematch_hungry": 40,
    "callout": 30,
}

CALLOUT_RATE = 0.05  # 5% of remaining pairs


def reseed():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    existing = conn.execute("SELECT COUNT(*) FROM rivalries").fetchone()[0]
    print(f"Deleting {existing} existing rivalries...")
    conn.execute("DELETE FROM rivalries")

    # Pull all fight_history rows where BOTH fighters are real DB
    # fighters (id 1..4000). For each fight, we have one row from the
    # fighter's perspective (fighter_id, opponent_id, outcome,
    # result_type, title_at_stake, event_date).
    rows = conn.execute(
        "SELECT fighter_id, opponent_id, outcome, result_type, "
        "title_at_stake, event_date FROM fight_history "
        "WHERE fighter_id BETWEEN 1 AND 4000 "
        "AND opponent_id BETWEEN 1 AND 4000"
    ).fetchall()

    print(f"DB-vs-DB fight_history rows: {len(rows)}")

    # Build pair → list of fight rows.
    # Pair key: (min_id, max_id) so each pair is counted once.
    # For each row, also normalize to (pair, fighter_id, outcome).
    pairs = {}  # (a, b) → list of (fighter_id, outcome, result_type, title, date)

    for fid, opp_id, outcome, rt, title, ev_date in rows:
        a, b = (fid, opp_id) if fid < opp_id else (opp_id, fid)
        key = (a, b)
        pairs.setdefault(key, []).append(
            (fid, outcome, rt, title, ev_date)
        )

    print(f"Distinct DB-vs-DB pairs: {len(pairs)}")

    # Filter to pairs who've fought 2+ times.
    multi_pairs = {k: v for k, v in pairs.items() if len(v) >= 2}
    print(f"Pairs with 2+ fights: {len(multi_pairs)}")

    rng = random.Random(20260815)

    # Classify each multi-fight pair.
    bad_blood = []
    title_rivalry = []
    rematch_hungry = []
    callout = []

    for (a, b), fights in multi_pairs.items():
        # Count wins/losses/draws for fighter a.
        a_wins = sum(1 for fid, o, _, _, _ in fights
                     if fid == a and o == "win")
        a_losses = sum(1 for fid, o, _, _, _ in fights
                       if fid == a and o == "loss")
        draws = sum(1 for _, o, _, _, _ in fights if o == "draw")

        has_sd = any(rt == "split_decision" for _, _, rt, _, _ in fights)
        has_dq = any(rt == "dq" for _, _, rt, _, _ in fights)
        has_title = any(t == 1 for _, _, _, t, _ in fights)

        if has_sd or has_dq:
            bad_blood.append((a, b, fights))
        elif has_title:
            title_rivalry.append((a, b, fights))
        elif a_wins == a_losses or (a_wins == 0 and a_losses == 0 and draws >= 1):
            rematch_hungry.append((a, b, fights))
        else:
            # Eligible for callout (random 5%).
            if rng.random() < CALLOUT_RATE:
                callout.append((a, b, fights))

    print(f"Classified:")
    print(f"  bad_blood     : {len(bad_blood)}")
    print(f"  title_rivalry : {len(title_rivalry)}")
    print(f"  rematch_hungry: {len(rematch_hungry)}")
    print(f"  callout       : {len(callout)}")

    # Insert rivalries.
    insert_sql = (
        "INSERT INTO rivalries "
        "(fighter_a_id, fighter_b_id, rivalry_heat, rivalry_type, "
        "origin_event, origin_description, fights_count, "
        "fighter_a_wins, fighter_b_wins, draws, is_active, "
        "last_escalation_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)"
    )

    batch = []
    total_inserted = 0

    def _make_row(a, b, fights, rtype):
        heat = HEAT_BY_TYPE[rtype]
        a_wins = sum(1 for fid, o, _, _, _ in fights
                     if fid == a and o == "win")
        b_wins = sum(1 for fid, o, _, _, _ in fights
                     if fid == b and o == "win")
        draws = sum(1 for _, o, _, _, _ in fights if o == "draw")
        # Find latest fight date.
        last_date = None
        for _, _, _, _, d in fights:
            if d and (last_date is None or d > last_date):
                last_date = d

        origins = {
            "bad_blood": ("split_decision_or_dq",
                          "Bad blood from a controversial finish."),
            "title_rivalry": ("title_fight",
                              "These two have history with a title on the line."),
            "rematch_hungry": ("close_series",
                               "Series is even — fans want the tiebreaker."),
            "callout": ("callout",
                        "One called out the other after a recent win."),
        }
        origin_event, desc = origins[rtype]
        return (a, b, heat, rtype, origin_event, desc,
                len(fights), a_wins, b_wins, draws, last_date)

    for a, b, fights in bad_blood:
        batch.append(_make_row(a, b, fights, "bad_blood"))
    for a, b, fights in title_rivalry:
        batch.append(_make_row(a, b, fights, "title_rivalry"))
    for a, b, fights in rematch_hungry:
        batch.append(_make_row(a, b, fights, "rematch_hungry"))
    for a, b, fights in callout:
        batch.append(_make_row(a, b, fights, "callout"))

    if batch:
        conn.executemany(insert_sql, batch)
        total_inserted = len(batch)

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Rivalry reseed complete ===")
    print(f"  Total rivalries inserted: {total_inserted}")
    return 0


if __name__ == "__main__":
    sys.exit(reseed())
