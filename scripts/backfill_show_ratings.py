#!/usr/bin/env python3
"""CLEANUP-AND-FIX Bug 3: Backfill show_ratings for completed events.

The audit found that show_ratings has 0 rows despite 1884 completed
events in the DB. This script backfills show_ratings for each
completed event that has at least one resolved fight, using a
simplified version of the rating formula in src/show_rating.py:

  fan_rating        — base 30 + finishes*8 (KO/sub/doctor/DQ/corner)
                              + title_fights*5 + rivalry_fights*3, cap 100
  commercial_rating — base 35 + title_fights*3 (marketability proxy), cap 100
  excitement_rating — base 30 + finishes*7 + draws*1, cap 100
  quality_rating    — base 40 + decisions*1 (decision = technique),
                              cap 100
  overall_rating    — 30% fan + 20% commercial + 25% excitement
                              + 25% quality

This is a backfill-only approximation; the production
show_rating._compute_show_ratings() subscriber handles live events
going forward.

Idempotent: uses UNIQUE(event_id) on show_ratings + an explicit
existence check.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"

_FINISH_TYPES = {"ko_tko", "ko", "tko", "submission",
                 "doctor_stoppage", "corner_stoppage", "dq"}
_DECISION_TYPES = {"unanimous_decision", "split_decision", "majority_decision"}


def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, v))


def _describe(overall: int) -> str:
    if overall >= 90:
        return "an instant classic that fans will talk about for years"
    if overall >= 75:
        return "a highly entertaining show that delivered on expectations"
    if overall >= 60:
        return "a solid night of fights with some memorable moments"
    if overall >= 40:
        return "a decent show that failed to produce many highlights"
    return "a lackluster card that left fans wanting more"


def _compute_ratings(conn, event_id, promo_id, fights):
    """Compute the 5 rating axes from a list of fight rows.

    `fights` is a list of dicts: fight_id, result_type, is_title_fight,
    fighter_a_id, fighter_b_id.
    """
    if not fights:
        return None
    n = len(fights)
    finishes = sum(1 for f in fights
                   if (f["result_type"] or "").lower() in _FINISH_TYPES)
    decisions = sum(1 for f in fights
                    if (f["result_type"] or "").lower() in _DECISION_TYPES)
    draws = sum(1 for f in fights
                if (f["result_type"] or "").lower() == "draw")
    title_fights = sum(1 for f in fights if f["is_title_fight"])

    # Rivalry fights — count distinct (a,b) pairs with an active rivalry
    rivalry_fights = 0
    for f in fights:
        a, b = f["fighter_a_id"], f["fighter_b_id"]
        if a is None or b is None:
            continue
        row = conn.execute(
            "SELECT 1 FROM rivalries WHERE is_active=1 AND "
            "((fighter_a_id=? AND fighter_b_id=?) OR "
            " (fighter_a_id=? AND fighter_b_id=?))",
            (a, b, b, a),
        ).fetchone()
        if row:
            rivalry_fights += 1

    fan = _clamp(30 + finishes * 8 + title_fights * 5 + rivalry_fights * 3)
    commercial = _clamp(35 + title_fights * 3)
    excitement = _clamp(30 + finishes * 7 + draws * 1)
    quality = _clamp(40 + decisions * 1)
    overall = _clamp(
        int(round(0.30 * fan + 0.20 * commercial
                  + 0.25 * excitement + 0.25 * quality))
    )
    return (fan, commercial, excitement, quality, overall)


def backfill(conn: sqlite3.Connection) -> dict:
    # Completed events with at least one resolved fight and no
    # existing show_ratings row.
    events = conn.execute(
        "SELECT e.event_id, e.promotion_id "
        "FROM events e "
        "WHERE e.status='completed' "
        "  AND EXISTS (SELECT 1 FROM fights f "
        "              WHERE f.event_id=e.event_id "
        "                AND f.winner_fighter_id IS NOT NULL) "
        "  AND NOT EXISTS (SELECT 1 FROM show_ratings sr "
        "                   WHERE sr.event_id=e.event_id)"
    ).fetchall()

    inserted = 0
    skipped = 0
    for (event_id, promo_id) in events:
        fights_rows = conn.execute(
            "SELECT fight_id, result_type, is_title_fight, "
            "       winner_fighter_id, loser_fighter_id "
            "FROM fights WHERE event_id=?",
            (event_id,),
        ).fetchall()
        # Need fighter_a_id / fighter_b_id. Use fight_history as the
        # authoritative source — it stores (fighter_id, opponent_id)
        # for each fight, twice (mirrored).
        fights = []
        for (fid, rt, tf, winner, loser) in fights_rows:
            # The two participants are winner + loser (or for draws,
            # any two rows from fight_history with this fight_id).
            if winner and loser:
                a, b = winner, loser
            else:
                fh = conn.execute(
                    "SELECT fighter_id, opponent_id FROM fight_history "
                    "WHERE fight_id=? LIMIT 1",
                    (fid,),
                ).fetchone()
                if not fh:
                    continue
                a, b = fh[0], fh[1]
            fights.append({
                "fight_id": fid,
                "result_type": rt,
                "is_title_fight": bool(tf),
                "fighter_a_id": a,
                "fighter_b_id": b,
            })
        if not fights:
            skipped += 1
            continue

        ratings = _compute_ratings(conn, event_id, promo_id, fights)
        if ratings is None:
            skipped += 1
            continue
        fan, commercial, excitement, quality, overall = ratings
        description = _describe(overall)
        try:
            conn.execute(
                "INSERT INTO show_ratings "
                "(event_id, promotion_id, fan_rating, commercial_rating, "
                "excitement_rating, quality_rating, overall_rating, "
                "rating_description) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, promo_id, fan, commercial, excitement,
                 quality, overall, description),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # UNIQUE(event_id) — already exists; skip.
            skipped += 1

    conn.commit()
    return {"total": len(events), "inserted": inserted, "skipped": skipped}


def main():
    db_path = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(DB_PATH)))
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    try:
        result = backfill(conn)
    finally:
        conn.close()

    print(f"show_ratings backfill: {result['inserted']}/{result['total']} "
          f"events rated, {result['skipped']} skipped (no fights / "
          f"already rated).")


if __name__ == "__main__":
    main()
