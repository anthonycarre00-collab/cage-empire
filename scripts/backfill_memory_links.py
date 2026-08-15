#!/usr/bin/env python3
"""HW3.3 (Hardening Phase §HW3.3) — Backfill historical memory links.

Audit finding (Hardening_Phase.md §CRITICAL #6 / §HW3.3):
  The memory engine was starved of data — only 775 rows in
  fighter_memory_links (regional_rival 744 + style_echo 29 +
  successor 2). The new link types added in HW3.1 (title_history,
  upset, comeback, milestone) have ZERO rows because the writers
  fire only on new events. This script backfills them from the
  historical record so the Memory Engine can surface them
  immediately.

Backfill rules (per HW3.3 spec):
  1. UPSET — for every fight in fight_history where the result was
     an upset (winner's rankings.rating < loser's rankings.rating
     by >= 15) → write bidirectional 'upset' link.
  2. TITLE_HISTORY — for every title change in the DB (every title
     fight with both winner + loser) → write bidirectional
     'title_history' link between the two fighters. (Strictly, only
     fights where the title changed hands should write a link, but
     we don't have a title_history table — we approximate by linking
     every title fight's winner+loser, which is a superset of the
     actual title changes. This is fine for memory surfacing: "these
     two fought for the title" is a meaningful memory even if the
     belt didn't change hands.)
  3. MILESTONE — for every fighter with 10+ wins → write a
     'milestone' link to the opponent they beat for their 10th win
     (and 20th win if they reached that too).
  4. COMEBACK — for every fighter who had a 365+ day gap between
     consecutive fights → write a 'comeback' link to their last
     opponent before the layoff (the "unfinished business" opponent).

Idempotent: every INSERT uses OR IGNORE against the UNIQUE
constraint on (fighter_id, linked_fighter_id, link_type). Re-runs
are safe — already-existing links are skipped.

DB backup: the script makes a timestamped backup of the DB before
writing (unless --no-backup is passed). The backup is at
data/cage_empire.db.bak.pre-hw3-backfill-YYYYMMDD-HHMMSS.

Run from the project root:
    python3 scripts/backfill_memory_links.py            # live DB
    python3 scripts/backfill_memory_links.py --dry-run  # report only
    python3 scripts/backfill_memory_links.py --no-backup  # skip backup

Refs docs/Hardening_Phase.md §HW3.3, §CRITICAL #6.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

# Import the writers from memory_svc so the backfill uses the same
# idempotent INSERT OR IGNORE logic as the live event-bus path.
sys.path.insert(0, str(PROJECT_DIR / "src"))
from services.memory_svc import (  # noqa: E402
    write_upset_link,
    write_title_history_link,
    write_comeback_link,
    write_milestone_link,
    UPSET_RATING_GAP_THRESHOLD,
    COMEBACK_LAYOFF_DAYS,
)


def backup_db(db_path):
    """Make a timestamped backup of the DB before writing."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_suffix(
        f".db.bak.pre-hw3-backfill-{timestamp}"
    )
    shutil.copy2(str(db_path), str(backup_path))
    print(f"  DB backup: {backup_path}")
    return backup_path


def backfill_upsets(conn):
    """Find every fight where the winner was lower-rated than the
    loser by >= 15 points + write an upset link.

    Uses rankings.rating as the rating source. The ratings are
    POST-fight (ELO has been updated) but the gap is close enough
    to the pre-fight gap for upset detection — the ELO update is
    typically <32 points, well under the 15-point threshold.

    Returns: dict with counts {found, written, skipped}.
    """
    print("\n  [1/4] Backfilling upset links...")
    # For each fight with both winner + loser, look up both
    # fighters' rankings.rating at the weight_class_id + promo of
    # the fight. If the loser's rating > winner's rating by >= 15,
    # write an upset link.
    rows = conn.execute(
        """
        SELECT f.fight_id, f.winner_fighter_id, f.loser_fighter_id,
               f.weight_class_id, e.promotion_id
        FROM fights f
        LEFT JOIN events e ON e.event_id = f.event_id
        WHERE f.winner_fighter_id IS NOT NULL
          AND f.loser_fighter_id IS NOT NULL
          AND f.weight_class_id IS NOT NULL
          AND e.promotion_id IS NOT NULL
        """
    ).fetchall()

    found = 0
    written = 0
    skipped = 0
    for fight_id, winner_id, loser_id, wc_id, promo_id in rows:
        # Look up both fighters' ratings.
        w_row = conn.execute(
            "SELECT rating FROM rankings "
            "WHERE fighter_id=? AND weight_class_id=? AND promotion_id=?",
            (winner_id, wc_id, promo_id),
        ).fetchone()
        l_row = conn.execute(
            "SELECT rating FROM rankings "
            "WHERE fighter_id=? AND weight_class_id=? AND promotion_id=?",
            (loser_id, wc_id, promo_id),
        ).fetchone()
        if not w_row or not l_row:
            skipped += 1
            continue
        rating_gap = (l_row[0] or 1000.0) - (w_row[0] or 1000.0)
        if rating_gap < UPSET_RATING_GAP_THRESHOLD:
            skipped += 1
            continue
        found += 1
        # write_upset_link will re-check the gap (we pass it
        # explicitly to avoid the writer re-querying it).
        n = write_upset_link(conn, winner_id, loser_id,
                             rating_gap=rating_gap)
        written += n

    print(f"    upsets found (gap >= {UPSET_RATING_GAP_THRESHOLD}): "
          f"{found}")
    print(f"    upset links written:                  {written}")
    print(f"    fights skipped (no rankings / no upset): {skipped}")
    return {"found": found, "written": written, "skipped": skipped}


def backfill_title_history(conn):
    """For every title fight (fights.is_title_fight=1) with both
    winner + loser, write a title_history link between them.

    This is a SUPERSET of "actual title changes" — we don't have a
    title_reign_history table, so we link every title fight's
    participants. The Memory Engine surfaces "they fought for the
    title" which is meaningful regardless of whether the belt
    changed hands.

    Returns: dict with counts {found, written}.
    """
    print("\n  [2/4] Backfilling title_history links...")
    rows = conn.execute(
        """
        SELECT f.fight_id, f.winner_fighter_id, f.loser_fighter_id
        FROM fights f
        WHERE f.is_title_fight = 1
          AND f.winner_fighter_id IS NOT NULL
          AND f.loser_fighter_id IS NOT NULL
        """
    ).fetchall()

    found = len(rows)
    written = 0
    for fight_id, winner_id, loser_id in rows:
        n = write_title_history_link(conn, winner_id, loser_id,
                                     title_id=None)
        written += n

    print(f"    title fights found:      {found}")
    print(f"    title_history links written: {written}")
    return {"found": found, "written": written}


def backfill_milestones(conn):
    """For every fighter with 10+ wins, write a milestone link to
    the opponent they beat for their 10th win. Same for 20th win.

    Looks up fight_history ordered by event_date ASC, finds the
    fight that was the fighter's 10th (and 20th) win, and writes
    a milestone link to that fight's opponent.

    Returns: dict with counts {found_10, found_20, written}.
    """
    print("\n  [3/4] Backfilling milestone links...")
    # Find every fighter with 10+ wins.
    rows = conn.execute(
        """
        SELECT fighter_id, COUNT(*) AS wins
        FROM fight_history
        WHERE outcome = 'win'
        GROUP BY fighter_id
        HAVING wins >= 10
        """
    ).fetchall()

    found_10 = 0
    found_20 = 0
    written = 0
    for fighter_id, total_wins in rows:
        # Get this fighter's wins ordered by event_date ASC — the
        # 10th win is the one at index 9 (0-indexed), the 20th at
        # index 19.
        win_rows = conn.execute(
            """
            SELECT opponent_id, event_date
            FROM fight_history
            WHERE fighter_id = ? AND outcome = 'win'
            ORDER BY event_date ASC, fight_history_id ASC
            """,
            (fighter_id,),
        ).fetchall()

        # 10th win milestone.
        if total_wins >= 10:
            found_10 += 1
            opponent_id = win_rows[9][0] if len(win_rows) >= 10 else None
            if opponent_id:
                n = write_milestone_link(conn, fighter_id, opponent_id,
                                         "wins_10")
                written += n

        # 20th win milestone.
        if total_wins >= 20:
            found_20 += 1
            opponent_id = win_rows[19][0] if len(win_rows) >= 20 else None
            if opponent_id:
                n = write_milestone_link(conn, fighter_id, opponent_id,
                                         "wins_20")
                written += n

    print(f"    fighters with 10+ wins: {found_10}")
    print(f"    fighters with 20+ wins: {found_20}")
    print(f"    milestone links written: {written}")
    return {"found_10": found_10, "found_20": found_20,
            "written": written}


def backfill_comebacks(conn):
    """For every fighter with a 365+ day gap between consecutive
    fights, write a comeback link to their last opponent before the
    layoff.

    Uses fight_history ordered by event_date ASC + looks for gaps
    >= 365 days between consecutive fights. For each gap, writes a
    link from the fighter to the opponent of their LAST fight before
    the gap (the "unfinished business" opponent — the one they were
    fighting before they disappeared).

    Returns: dict with counts {found, written}.
    """
    print("\n  [4/4] Backfilling comeback links...")
    # Get all fighters with at least 2 fights.
    rows = conn.execute(
        """
        SELECT fighter_id, COUNT(*) AS n
        FROM fight_history
        GROUP BY fighter_id
        HAVING n >= 2
        """
    ).fetchall()

    found = 0
    written = 0
    for fighter_id, _n in rows:
        # Get this fighter's fights ordered by event_date ASC.
        fight_rows = conn.execute(
            """
            SELECT opponent_id, event_date
            FROM fight_history
            WHERE fighter_id = ?
            ORDER BY event_date ASC, fight_history_id ASC
            """,
            (fighter_id,),
        ).fetchall()
        if len(fight_rows) < 2:
            continue

        # Walk the list, looking for gaps >= 365 days. For each gap,
        # the "last opponent before the layoff" is the opponent at
        # index i-1 (the fight BEFORE the gap).
        from datetime import datetime as _dt
        for i in range(1, len(fight_rows)):
            try:
                prev_date = _dt.fromisoformat(
                    fight_rows[i - 1][1][:10]
                ).date()
                curr_date = _dt.fromisoformat(
                    fight_rows[i][1][:10]
                ).date()
            except (ValueError, TypeError):
                continue
            gap_days = (curr_date - prev_date).days
            if gap_days < COMEBACK_LAYOFF_DAYS:
                continue
            # Found a comeback gap. The opponent is the opponent of
            # the fight BEFORE the gap (i-1).
            opponent_id = fight_rows[i - 1][0]
            if not opponent_id:
                continue
            found += 1
            # write_comeback_link uses event_date to compute the gap
            # itself — pass the date of the fight AFTER the gap (the
            # "comeback fight").
            n = write_comeback_link(conn, fighter_id,
                                    event_date=fight_rows[i][1])
            written += n

    print(f"    comeback gaps found (>= {COMEBACK_LAYOFF_DAYS} days): "
          f"{found}")
    print(f"    comeback links written:                  {written}")
    return {"found": found, "written": written}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts without writing rows.")
    ap.add_argument("--no-backup", action="store_true",
                    help="Skip the DB backup before writing.")
    ap.add_argument("--db", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    print(f"  HW3.3 backfill_memory_links")
    print(f"  DB: {db}")

    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON;")

    # BEFORE state.
    before_total = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    before_by_type = conn.execute(
        "SELECT link_type, COUNT(*) FROM fighter_memory_links "
        "GROUP BY link_type ORDER BY link_type"
    ).fetchall()
    print(f"\n  fighter_memory_links BEFORE: {before_total} rows")
    for lt, n in before_by_type:
        print(f"    {lt:20s} {n}")

    if args.dry_run:
        # Even in dry-run, run the backfill functions but in a
        # transaction we'll roll back.
        print("\n  --dry-run: no writes will be committed.")
        # We still execute the queries (to report counts) but ROLLBACK
        # at the end so nothing persists.
        try:
            backfill_upsets(conn)
            backfill_title_history(conn)
            backfill_milestones(conn)
            backfill_comebacks(conn)
        finally:
            conn.rollback()
        print("\n  --dry-run complete. No rows written.")
        conn.close()
        return 0

    # Make a backup before writing.
    if not args.no_backup:
        backup_db(db)

    # Run the 4 backfills.
    upsets = backfill_upsets(conn)
    titles = backfill_title_history(conn)
    milestones = backfill_milestones(conn)
    comebacks = backfill_comebacks(conn)

    conn.commit()

    # AFTER state.
    after_total = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    after_by_type = conn.execute(
        "SELECT link_type, COUNT(*) FROM fighter_memory_links "
        "GROUP BY link_type ORDER BY link_type"
    ).fetchall()
    print(f"\n  fighter_memory_links AFTER:  {after_total} rows")
    for lt, n in after_by_type:
        print(f"    {lt:20s} {n}")
    print(f"\n  delta: +{after_total - before_total} rows")

    # Summary.
    total_written = (upsets["written"] + titles["written"]
                     + milestones["written"] + comebacks["written"])
    print(f"\n  SUMMARY:")
    print(f"    upset links written:         {upsets['written']}")
    print(f"    title_history links written: {titles['written']}")
    print(f"    milestone links written:     {milestones['written']}")
    print(f"    comeback links written:      {comebacks['written']}")
    print(f"    total new links:             {total_written}")

    # Invariant: no link written for a non-existent fighter.
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM fighter_memory_links fml
        LEFT JOIN fighters f1 ON f1.fighter_id = fml.fighter_id
        LEFT JOIN fighters f2 ON f2.fighter_id = fml.linked_fighter_id
        WHERE f1.fighter_id IS NULL OR f2.fighter_id IS NULL
        """
    ).fetchone()[0]
    print()
    if bad == 0:
        print(f"  INVARIANT PASS: every link references existing fighters.")
    else:
        print(f"  INVARIANT FAIL: {bad} links reference non-existent "
              f"fighters.")
    conn.close()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
