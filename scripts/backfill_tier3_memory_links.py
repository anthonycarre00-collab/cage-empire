#!/usr/bin/env python3
"""TIER3-MISSING §T3.4 (W17) — Backfill the 8 new memory link types
from historical data.

The new link types added in v3.36.0 (previous_fights, former_teammates,
old_gyms, former_champions, controversial_losses, injuries, promotions,
old_events) are written by event-bus subscribers on new events. This
script backfills them from the existing historical record so the
Memory Engine can surface them immediately.

Backfill rules (per T3.4 brief):
  1. previous_fights      — for every pair of fighters who have fought
                            each other before, write a bidirectional
                            'previous_fights' link.
  2. controversial_losses — for every fight with result_type in
                            ('split_decision', 'doctor_stoppage'),
                            write a bidirectional link between the
                            loser and winner.
  3. old_events           — for every title fight (is_title_fight=1),
                            write a self-link for both fighters.
  4. former_champions     — for every fighter who USED to hold a title
                            (titles table row where current_champion_
                            fighter_id IS NULL but the fighter was a
                            previous champion) — approximated by
                            finding every fighter who lost a title
                            fight (title fight loser).
  5. injuries             — for every fighter with at least one row
                            in injuries (active or historical), write
                            a self-link.
  6. promotions           — for every fighter who has been signed to
                            a promotion (current_promotion_id IS NOT
                            NULL), write a self-link. This is a
                            SUPERSET of "fighters who changed promo"
                            — every signed fighter "changed from no
                            promo to a promo" at least once.
  7. former_teammates     — SKIPPED (no fighter_gym_history table to
                            detect gym changes; the writers are wired
                            for forward use only per the brief's
                            "if it exists" qualifier).
  8. old_gyms             — SKIPPED (same as former_teammates).

Idempotent: every INSERT uses OR IGNORE against the UNIQUE
constraint on (fighter_id, linked_fighter_id, link_type). Re-runs
are safe — already-existing links are skipped.

DB backup: the script makes a timestamped backup of the DB before
writing (unless --no-backup is passed).

Run from the project root:
    python3 scripts/backfill_tier3_memory_links.py            # live DB
    python3 scripts/backfill_tier3_memory_links.py --dry-run  # report only
    python3 scripts/backfill_tier3_memory_links.py --no-backup  # skip backup

Refs docs/OPTIMIZATION_PLAN_TIER1_3.md §T3.4 (W17).
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
    write_previous_fights_link,
    write_former_teammates_links_on_gym_change,
    write_old_gyms_link,
    write_former_champions_link,
    write_controversial_losses_link,
    write_injuries_link,
    write_promotions_link,
    write_old_events_link,
)


def backup_db(db_path):
    """Make a timestamped backup of the DB before writing."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_suffix(
        f".db.bak.pre-tier3-backfill-{timestamp}"
    )
    shutil.copy2(str(db_path), str(backup_path))
    print(f"  DB backup: {backup_path}")
    return backup_path


def backfill_previous_fights(conn):
    """For every pair of fighters who have fought each other before,
    write a bidirectional 'previous_fights' link.

    Returns: dict with counts {pairs_found, links_written}.
    """
    print("\n  [1/6] Backfilling previous_fights links...")
    # Find every distinct (fighter_id, opponent_id) pair in
    # fight_history. Each pair has at least 1 row from fighter_id's
    # perspective + 1 row from opponent_id's perspective (the
    # fight_history table has one row per fighter per fight). We
    # use DISTINCT to deduplicate + only keep pairs where fighter_id
    # < opponent_id (to avoid processing both A→B and B→A).
    rows = conn.execute(
        """
        SELECT DISTINCT fighter_id, opponent_id
        FROM fight_history
        WHERE fighter_id IS NOT NULL
          AND opponent_id IS NOT NULL
          AND fighter_id < opponent_id
        """
    ).fetchall()

    pairs_found = len(rows)
    links_written = 0
    for fighter_a, fighter_b in rows:
        # write_previous_fights_link writes bidirectional A→B + B→A.
        n = write_previous_fights_link(conn, fighter_a, fighter_b)
        links_written += n

    print(f"    fighter pairs found:           {pairs_found}")
    print(f"    previous_fights links written: {links_written}")
    return {"pairs_found": pairs_found, "written": links_written}


def backfill_controversial_losses(conn):
    """For every fight with result_type in ('split_decision',
    'doctor_stoppage'), write a bidirectional 'controversial_losses'
    link between loser and winner.

    Returns: dict with counts {fights_found, links_written}.
    """
    print("\n  [2/6] Backfilling controversial_losses links...")
    rows = conn.execute(
        """
        SELECT DISTINCT winner_fighter_id, loser_fighter_id
        FROM fights
        WHERE winner_fighter_id IS NOT NULL
          AND loser_fighter_id IS NOT NULL
          AND result_type IN ('split_decision', 'doctor_stoppage')
        """
    ).fetchall()

    fights_found = len(rows)
    links_written = 0
    for winner_id, loser_id in rows:
        n = write_controversial_losses_link(conn, loser_id, winner_id)
        links_written += n

    print(f"    controversial fights found:    {fights_found}")
    print(f"    controversial_losses written:  {links_written}")
    return {"fights_found": fights_found, "written": links_written}


def backfill_old_events(conn):
    """For every title fight (fights.is_title_fight=1), write an
    'old_events' self-link for both fighters.

    Returns: dict with counts {title_fights_found, links_written}.
    """
    print("\n  [3/6] Backfilling old_events links...")
    rows = conn.execute(
        """
        SELECT DISTINCT winner_fighter_id, loser_fighter_id
        FROM fights
        WHERE is_title_fight = 1
          AND winner_fighter_id IS NOT NULL
          AND loser_fighter_id IS NOT NULL
        """
    ).fetchall()

    title_fights_found = len(rows)
    links_written = 0
    for winner_id, loser_id in rows:
        # Self-link for BOTH fighters.
        n1 = write_old_events_link(conn, winner_id, event_type="title_fight")
        n2 = write_old_events_link(conn, loser_id, event_type="title_fight")
        links_written += n1 + n2

    print(f"    title fights found:      {title_fights_found}")
    print(f"    old_events links written: {links_written}")
    return {"title_fights_found": title_fights_found,
            "written": links_written}


def backfill_former_champions(conn):
    """For every fighter who LOST a title fight (the loser of a
    title fight is by definition a former champion — they held the
    belt going in OR they were the contender who failed to win it;
    strictly we want the former case, but the brief's intent is to
    flag fighters with title-fight history). Also include any
    current champions (they may lose the title later — the self-link
    is forward-looking).

    A more precise approach would query titles.history for former
    champions, but no such table exists. The closest approximation:
    find every fighter who LOST a title fight where the title
    actually changed hands (we can detect this via the
    title_reigns_count > 1 check on the titles table — but that
    requires knowing which title was at stake).

    Simpler approximation: every fighter who lost a title fight is
    a "former championship contender" — flag them all. This is a
    SUPERSET of "former champions" but captures the spirit of the
    memory type.

    Returns: dict with counts {fighters_found, links_written}.
    """
    print("\n  [4/6] Backfilling former_champions links...")
    # Find every fighter who lost a title fight. DISTINCT because
    # a fighter may have lost multiple title fights.
    rows = conn.execute(
        """
        SELECT DISTINCT loser_fighter_id
        FROM fights
        WHERE is_title_fight = 1
          AND loser_fighter_id IS NOT NULL
        """
    ).fetchall()

    fighters_found = len(rows)
    links_written = 0
    for (fighter_id,) in rows:
        n = write_former_champions_link(conn, fighter_id, title_id=None)
        links_written += n

    print(f"    title-fight losers found:     {fighters_found}")
    print(f"    former_champions links written: {links_written}")
    return {"fighters_found": fighters_found, "written": links_written}


def backfill_injuries(conn):
    """For every fighter with at least one row in injuries (active
    or historical), write an 'injuries' self-link.

    Returns: dict with counts {fighters_found, links_written}.
    """
    print("\n  [5/6] Backfilling injuries links...")
    rows = conn.execute(
        """
        SELECT DISTINCT fighter_id
        FROM injuries
        WHERE fighter_id IS NOT NULL
        """
    ).fetchall()

    fighters_found = len(rows)
    links_written = 0
    for (fighter_id,) in rows:
        n = write_injuries_link(conn, fighter_id, injury_id=None)
        links_written += n

    print(f"    injured fighters found:  {fighters_found}")
    print(f"    injuries links written:  {links_written}")
    return {"fighters_found": fighters_found, "written": links_written}


def backfill_promotions(conn):
    """For every fighter who has been signed to a promotion
    (current_promotion_id IS NOT NULL), write a 'promotions'
    self-link.

    This is a SUPERSET of "fighters who changed promo" — every
    signed fighter "changed from no promo to a promo" at least
    once. The brief's intent is to flag fighters with promotion-
    change history; flagging all signed fighters captures this
    intent for the world DB (every signed fighter has at least one
    promo change in their history).

    Returns: dict with counts {fighters_found, links_written}.
    """
    print("\n  [6/6] Backfilling promotions links...")
    rows = conn.execute(
        """
        SELECT fighter_id
        FROM fighters
        WHERE current_promotion_id IS NOT NULL
          AND is_active = 1
        """
    ).fetchall()

    fighters_found = len(rows)
    links_written = 0
    for (fighter_id,) in rows:
        n = write_promotions_link(conn, fighter_id,
                                  old_promotion_id=None)
        links_written += n

    print(f"    signed fighters found:   {fighters_found}")
    print(f"    promotions links written: {links_written}")
    return {"fighters_found": fighters_found, "written": links_written}


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

    print(f"  TIER3-MISSING backfill_tier3_memory_links")
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
        print(f"    {lt:25s} {n}")

    if args.dry_run:
        # Even in dry-run, run the backfill functions but in a
        # transaction we'll roll back.
        print("\n  --dry-run: no writes will be committed.")
        try:
            backfill_previous_fights(conn)
            backfill_controversial_losses(conn)
            backfill_old_events(conn)
            backfill_former_champions(conn)
            backfill_injuries(conn)
            backfill_promotions(conn)
        finally:
            conn.rollback()
        print("\n  --dry-run complete. No rows written.")
        conn.close()
        return 0

    # Make a backup before writing.
    if not args.no_backup:
        backup_db(db)

    # Run the 6 backfills (former_teammates + old_gyms are skipped
    # — no fighter_gym_history table to detect gym changes).
    prev = backfill_previous_fights(conn)
    cont = backfill_controversial_losses(conn)
    old_e = backfill_old_events(conn)
    form_ch = backfill_former_champions(conn)
    inj = backfill_injuries(conn)
    prom = backfill_promotions(conn)

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
        print(f"    {lt:25s} {n}")
    print(f"\n  delta: +{after_total - before_total} rows")

    # Summary.
    total_written = (prev["written"] + cont["written"] + old_e["written"]
                     + form_ch["written"] + inj["written"]
                     + prom["written"])
    print(f"\n  SUMMARY:")
    print(f"    previous_fights links written:      {prev['written']}")
    print(f"    controversial_losses links written: {cont['written']}")
    print(f"    old_events links written:           {old_e['written']}")
    print(f"    former_champions links written:     {form_ch['written']}")
    print(f"    injuries links written:             {inj['written']}")
    print(f"    promotions links written:           {prom['written']}")
    print(f"    total new links:                    {total_written}")

    # Count distinct link_types after backfill (should include the
    # 8 new T3.4 types if any rows were written).
    new_types_present = sum(
        1 for lt, _n in after_by_type
        if lt in ("previous_fights", "former_teammates", "old_gyms",
                  "former_champions", "controversial_losses",
                  "injuries", "promotions", "old_events")
    )
    print(f"\n  T3.4 new link_types with >=1 row: "
          f"{new_types_present}/8")

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
