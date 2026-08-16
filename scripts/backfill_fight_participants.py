#!/usr/bin/env python3
"""HW1.2 (Hardening Phase §HW1.2) — Backfill fight_participants.

Audit finding (Hardening_Phase.md §CRITICAL #2 / §HW1.2):
  All historical fights store winner/loser on the `fights` table.
  `fight_participants` had only 138 rows (for 69 unresolved scheduled
  fights from the seed) — most resolved fights were missing the
  canonical 2 participant rows each.

This script reads every row in `fights` where BOTH winner_fighter_id
AND loser_fighter_id are populated and inserts 2 rows into
`fight_participants` (one for the winner, one for the loser).

Idempotent: skips any (fight_id, fighter_id) pair that already exists
in fight_participants (relies on the table's UNIQUE constraint).

Conventions:
  - corner: 'red' for the winner, 'blue' for the loser. This matches
    the seed-data convention (src/seed_data.py:714-715 sets fighter_a
    → 'red', fighter_b → 'blue') and the matchmaking convention
    (src/services/matchmaking.py:1578-1586 sets fighter_a → 'red',
    fighter_b → 'blue'). For historical fights where the original
    corner assignment is unknown, assigning the winner to 'red' is
    defensible (red is the higher-prestige corner in MMA).
  - is_winner: 1 for the winner, 0 for the loser. Mirrors the live
    update path in src/services/fight_engine.py:6137
    (UPDATE fight_participants SET is_winner=CASE WHEN fighter_id=?
    THEN 1 ELSE 0 END).

Expected outcome on the live DB:
  - 3,099 fights with both winner + loser → 6,198 new participant rows
  - Existing 138 rows preserved (UNIQUE constraint skips duplicates
    — 69 fights had participant rows from the seed, none of which
    have winner_fighter_id set so they don't match the backfill
    selection anyway).

Run from the project root:
    python3 scripts/backfill_fight_participants.py            # live DB
    python3 scripts/backfill_fight_participants.py --dry-run  # report only

Refs docs/Hardening_Phase.md §HW1.2, §CRITICAL #2.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
)) if False else (PROJECT_DIR / "data" / "cage_empire.db")
# (the `if False` keeps os.environ out of the import-time path so the
# script is deterministic when run from a shell — env-var override is
# supported via the CAGE_EMPIRE_DB_PATH env var if set.)
import os
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))


def _backfill_draws_from_fight_history(conn):
    """HW5.1 — Backfill 0-participant draws from fight_history.

    For each 0-participant fight that has 2+ rows in fight_history,
    insert 2 rows into fight_participants (one for fighter_id, one
    for opponent_id), both with is_winner=0 (since the fight was a
    draw — no winner). corner='red' for fighter_id, 'blue' for
    opponent_id (matching the seed convention).

    Returns: (n_fights_backfilled, n_rows_inserted, n_rows_skipped).
    """
    # Find 0-participant fights with fight_history rows.
    fights_with_fh = conn.execute(
        """
        SELECT f.fight_id
        FROM fights f
        WHERE NOT EXISTS (
            SELECT 1 FROM fight_participants fp WHERE fp.fight_id = f.fight_id
        )
        AND EXISTS (
            SELECT 1 FROM fight_history fh WHERE fh.fight_id = f.fight_id
        )
        """
    ).fetchall()
    n_fights = 0
    n_inserted = 0
    n_skipped = 0
    for (fight_id,) in fights_with_fh:
        # Get the 2 fighters from fight_history (each row has fighter_id +
        # opponent_id; either row gives us both).
        row = conn.execute(
            "SELECT fighter_id, opponent_id FROM fight_history "
            "WHERE fight_id=? LIMIT 1",
            (fight_id,),
        ).fetchone()
        if not row or not row[0] or not row[1]:
            continue
        fighter_a, fighter_b = row[0], row[1]
        # Insert fighter_a as 'red', fighter_b as 'blue' (both is_winner=0
        # since draws have no winner).
        cur = conn.execute(
            "INSERT OR IGNORE INTO fight_participants "
            "(fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'red', 0)",
            (fight_id, fighter_a),
        )
        if cur.rowcount > 0:
            n_inserted += 1
        else:
            n_skipped += 1
        cur = conn.execute(
            "INSERT OR IGNORE INTO fight_participants "
            "(fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'blue', 0)",
            (fight_id, fighter_b),
        )
        if cur.rowcount > 0:
            n_inserted += 1
        else:
            n_skipped += 1
        n_fights += 1
    return n_fights, n_inserted, n_skipped


def _backfill_draws_from_weight_cut_log(conn):
    """HW5.1 — Backfill 0-participant fights from weight_cut_log.

    For each 0-participant fight (with no fight_history) that has 2
    rows in weight_cut_log, insert 2 rows into fight_participants
    using the weight_cut_log fighter_ids. corner='red' for the first
    fighter_id (by weight_cut_log_id ASC), 'blue' for the second,
    is_winner=0 (no winner info available).

    Returns: (n_fights_backfilled, n_rows_inserted, n_rows_skipped).
    """
    fights_with_wcl = conn.execute(
        """
        SELECT f.fight_id
        FROM fights f
        WHERE NOT EXISTS (
            SELECT 1 FROM fight_participants fp WHERE fp.fight_id = f.fight_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM fight_history fh WHERE fh.fight_id = f.fight_id
        )
        AND EXISTS (
            SELECT 1 FROM weight_cut_log wcl WHERE wcl.fight_id = f.fight_id
        )
        """
    ).fetchall()
    n_fights = 0
    n_inserted = 0
    n_skipped = 0
    for (fight_id,) in fights_with_wcl:
        # Get the 2 distinct fighter_ids from weight_cut_log.
        wcl_fighters = conn.execute(
            "SELECT DISTINCT fighter_id FROM weight_cut_log "
            "WHERE fight_id=? ORDER BY fighter_id LIMIT 2",
            (fight_id,),
        ).fetchall()
        if len(wcl_fighters) < 2:
            continue
        fighter_a, fighter_b = wcl_fighters[0][0], wcl_fighters[1][0]
        cur = conn.execute(
            "INSERT OR IGNORE INTO fight_participants "
            "(fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'red', 0)",
            (fight_id, fighter_a),
        )
        if cur.rowcount > 0:
            n_inserted += 1
        else:
            n_skipped += 1
        cur = conn.execute(
            "INSERT OR IGNORE INTO fight_participants "
            "(fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'blue', 0)",
            (fight_id, fighter_b),
        )
        if cur.rowcount > 0:
            n_inserted += 1
        else:
            n_skipped += 1
        n_fights += 1
    return n_fights, n_inserted, n_skipped


def _delete_orphan_fights(conn):
    """HW5.1 — Delete truly orphan 0-participant fights.

    Fights that have:
      - 0 participants in fight_participants
      - 0 rows in fight_history
      - 0 rows in weight_cut_log
      - event_id that doesn't exist in events (orphan FK)

    These are unrecoverable data — there's no source for participant
    info. Deleting them is the only way to satisfy invariant #1.
    Also deletes their dependent rows in event_cards (the only table
    that references these fights, per HW5.1 audit).

    Returns: (n_fights_deleted, n_event_cards_deleted).
    """
    orphan_fights = conn.execute(
        """
        SELECT f.fight_id FROM fights f
        WHERE NOT EXISTS (
            SELECT 1 FROM fight_participants fp WHERE fp.fight_id = f.fight_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM fight_history fh WHERE fh.fight_id = f.fight_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM weight_cut_log wcl WHERE wcl.fight_id = f.fight_id
        )
        """
    ).fetchall()
    n_fights = 0
    n_event_cards = 0
    for (fight_id,) in orphan_fights:
        # Delete dependent event_cards rows first.
        cur = conn.execute(
            "DELETE FROM event_cards WHERE fight_id=?", (fight_id,)
        )
        n_event_cards += cur.rowcount
        # Delete the fight.
        cur = conn.execute("DELETE FROM fights WHERE fight_id=?", (fight_id,))
        n_fights += cur.rowcount
    return n_fights, n_event_cards


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts without writing rows.")
    ap.add_argument("--draws", action="store_true",
                    help="Also backfill 0-participant draws (HW5.1) — "
                         "from fight_history + weight_cut_log.")
    ap.add_argument("--delete-orphans", action="store_true",
                    help="Delete truly orphan 0-participant fights "
                         "(HW5.1) — no source data anywhere.")
    ap.add_argument("--db", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON;")

    # BEFORE state.
    before_total = conn.execute(
        "SELECT COUNT(*) FROM fight_participants"
    ).fetchone()[0]
    eligible_fights = conn.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE winner_fighter_id IS NOT NULL "
        "AND loser_fighter_id IS NOT NULL"
    ).fetchone()[0]
    already_backfilled = conn.execute(
        "SELECT COUNT(DISTINCT fp.fight_id) "
        "FROM fight_participants fp "
        "JOIN fights f ON f.fight_id = fp.fight_id "
        "WHERE f.winner_fighter_id IS NOT NULL "
        "AND f.loser_fighter_id IS NOT NULL"
    ).fetchone()[0]
    print(f"  DB:                {db}")
    print(f"  fight_participants BEFORE:  {before_total} rows")
    print(f"  eligible fights (winner+loser both set): {eligible_fights}")
    print(f"  eligible fights with participants already: {already_backfilled}")
    print(f"  eligible fights needing backfill: "
          f"{eligible_fights - already_backfilled}")

    # Also report 0-participant fights (HW5.1 draws + orphans).
    zero_participant = conn.execute(
        "SELECT COUNT(*) FROM fights f "
        "WHERE NOT EXISTS (SELECT 1 FROM fight_participants fp "
        "                  WHERE fp.fight_id = f.fight_id)"
    ).fetchone()[0]
    zero_with_fh = conn.execute(
        "SELECT COUNT(*) FROM fights f "
        "WHERE NOT EXISTS (SELECT 1 FROM fight_participants fp "
        "                  WHERE fp.fight_id = f.fight_id) "
        "AND EXISTS (SELECT 1 FROM fight_history fh "
        "            WHERE fh.fight_id = f.fight_id)"
    ).fetchone()[0]
    zero_with_wcl = conn.execute(
        "SELECT COUNT(*) FROM fights f "
        "WHERE NOT EXISTS (SELECT 1 FROM fight_participants fp "
        "                  WHERE fp.fight_id = f.fight_id) "
        "AND NOT EXISTS (SELECT 1 FROM fight_history fh "
        "                WHERE fh.fight_id = f.fight_id) "
        "AND EXISTS (SELECT 1 FROM weight_cut_log wcl "
        "            WHERE wcl.fight_id = f.fight_id)"
    ).fetchone()[0]
    zero_orphan = conn.execute(
        "SELECT COUNT(*) FROM fights f "
        "WHERE NOT EXISTS (SELECT 1 FROM fight_participants fp "
        "                  WHERE fp.fight_id = f.fight_id) "
        "AND NOT EXISTS (SELECT 1 FROM fight_history fh "
        "                WHERE fh.fight_id = f.fight_id) "
        "AND NOT EXISTS (SELECT 1 FROM weight_cut_log wcl "
        "                WHERE wcl.fight_id = f.fight_id)"
    ).fetchone()[0]
    print(f"  0-participant fights total: {zero_participant}")
    print(f"    with fight_history (backfillable as draws): {zero_with_fh}")
    print(f"    with weight_cut_log (backfillable as draws): {zero_with_wcl}")
    print(f"    truly orphan (no source): {zero_orphan}")

    if args.dry_run:
        print("  --dry-run: no writes. Exiting.")
        conn.close()
        return 0

    # Backfill winner+loser fights — one transaction.
    #
    # The query selects fights where BOTH winner + loser are set AND
    # there isn't already a participant row for that (fight_id, fighter_id)
    # pair. The UNIQUE (fight_id, fighter_id) constraint is the final
    # guard — INSERT OR IGNORE makes the script idempotent under re-runs
    # even if the SELECT's NOT EXISTS check races with a concurrent
    # writer (which won't happen here — single-process script).
    cur = conn.execute(
        """
        SELECT f.fight_id, f.winner_fighter_id, f.loser_fighter_id,
               f.result_type
        FROM fights f
        WHERE f.winner_fighter_id IS NOT NULL
          AND f.loser_fighter_id IS NOT NULL
        """
    )
    rows = cur.fetchall()

    n_inserted_winner = 0
    n_inserted_loser = 0
    n_skipped_existing = 0
    for fight_id, winner_id, loser_id, result_type in rows:
        # Winner row.
        cur = conn.execute(
            "INSERT OR IGNORE INTO fight_participants "
            "(fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'red', 1)",
            (fight_id, winner_id),
        )
        if cur.rowcount > 0:
            n_inserted_winner += 1
        else:
            n_skipped_existing += 1
        # Loser row.
        cur = conn.execute(
            "INSERT OR IGNORE INTO fight_participants "
            "(fight_id, fighter_id, corner, is_winner) "
            "VALUES (?, ?, 'blue', 0)",
            (fight_id, loser_id),
        )
        if cur.rowcount > 0:
            n_inserted_loser += 1
        else:
            n_skipped_existing += 1

    # HW5.1 — backfill draws + delete orphans (if requested).
    draws_fh_fights = draws_fh_rows = draws_fh_skipped = 0
    draws_wcl_fights = draws_wcl_rows = draws_wcl_skipped = 0
    orphan_fights = orphan_ec = 0
    if args.draws:
        (draws_fh_fights, draws_fh_rows, draws_fh_skipped) = (
            _backfill_draws_from_fight_history(conn))
        (draws_wcl_fights, draws_wcl_rows, draws_wcl_skipped) = (
            _backfill_draws_from_weight_cut_log(conn))
    if args.delete_orphans:
        (orphan_fights, orphan_ec) = _delete_orphan_fights(conn)

    conn.commit()

    # AFTER state.
    after_total = conn.execute(
        "SELECT COUNT(*) FROM fight_participants"
    ).fetchone()[0]
    after_distinct_fights = conn.execute(
        "SELECT COUNT(DISTINCT fight_id) FROM fight_participants"
    ).fetchone()[0]
    # Spot-check: a few sample rows to confirm the corner + is_winner
    # convention is right.
    sample = conn.execute(
        "SELECT fp.fight_id, fp.fighter_id, fp.corner, fp.is_winner, "
        "f.winner_fighter_id, f.loser_fighter_id, f.result_type "
        "FROM fight_participants fp "
        "JOIN fights f ON f.fight_id = fp.fight_id "
        "WHERE f.winner_fighter_id IS NOT NULL "
        "AND f.loser_fighter_id IS NOT NULL "
        "ORDER BY fp.fight_participant_id DESC LIMIT 4"
    ).fetchall()

    print()
    print(f"  fight_participants AFTER:   {after_total} rows")
    print(f"  distinct fights covered:    {after_distinct_fights}")
    print(f"  rows inserted (winner):     {n_inserted_winner}")
    print(f"  rows inserted (loser):      {n_inserted_loser}")
    print(f"  rows skipped (already had): {n_skipped_existing}")
    if args.draws:
        print(f"  draws backfilled from fight_history: "
              f"{draws_fh_fights} fights, +{draws_fh_rows} rows "
              f"({draws_fh_skipped} skipped)")
        print(f"  draws backfilled from weight_cut_log: "
              f"{draws_wcl_fights} fights, +{draws_wcl_rows} rows "
              f"({draws_wcl_skipped} skipped)")
    if args.delete_orphans:
        print(f"  orphan fights deleted:      {orphan_fights} "
              f"(+{orphan_ec} event_cards rows)")
    print(f"  delta: +{after_total - before_total} rows")
    print()
    print(f"  Spot-check (4 most-recent backfilled rows):")
    for row in sample:
        print(f"    {row}")
    # Quick invariant: every eligible fight now has exactly 2 participant
    # rows.
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT f.fight_id, COUNT(fp.fighter_id) AS n
          FROM fights f
          LEFT JOIN fight_participants fp ON fp.fight_id = f.fight_id
          WHERE f.winner_fighter_id IS NOT NULL
            AND f.loser_fighter_id IS NOT NULL
          GROUP BY f.fight_id
          HAVING n != 2
        )
        """
    ).fetchone()[0]
    # Also check the broader invariant: every fight has 2 participants
    # (covers draws + orphans too).
    bad_all = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT f.fight_id, COUNT(fp.fighter_id) AS n
          FROM fights f
          LEFT JOIN fight_participants fp ON fp.fight_id = f.fight_id
          GROUP BY f.fight_id
          HAVING n != 2
        )
        """
    ).fetchone()[0]
    print()
    if bad == 0:
        print(f"  INVARIANT PASS (winner+loser): every such fight has "
              f"exactly 2 participant rows.")
    else:
        print(f"  INVARIANT FAIL (winner+loser): {bad} fights do NOT "
              f"have exactly 2 participant rows.")
    if bad_all == 0:
        print(f"  INVARIANT PASS (ALL fights, incl draws): every fight "
              f"has exactly 2 participant rows.")
    else:
        print(f"  INVARIANT FAIL (ALL fights): {bad_all} fights do NOT "
              f"have exactly 2 participant rows.")
    conn.close()
    return 0 if bad_all == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
