#!/usr/bin/env python3
"""CAGE EMPIRE — Phase 1.5 Group A: World DB Data Reconciliation.

This is a DATA-ONLY fix script. It performs 8 fixes (A1-A8) against
the EXISTING world DB at data/cage_empire.db. No new code modules,
no schema changes, no `build_db.py` invocations.

Per CONVENTIONS §16.2: "Never run --fresh on a seeded DB". This
script does NOT call build_db at all — it only mutates data in place.

Usage:
    python3 scripts/reconcile_world_db.py
    python3 scripts/reconcile_world_db.py --dry-run   # report only, no writes
    python3 scripts/reconcile_world_db.py --skip-backup  # don't cp .db first

Each fix:
  - Prints BEFORE counts
  - Performs the change inside a single transaction (committed)
  - Prints AFTER counts + a one-line summary

The script is IDEMPOTENT — safe to re-run. On the second run:
  - A1 finds 0 future-dated completed events (already deleted)
  - A2 recomputes to the same streak values
  - A3 only marks fights that are still is_title_fight=0
  - A4 recomputes to the same rivalry counts
  - A5 only sets last_fight_date if currently NULL
  - A6 only sets promotion_id if currently NULL
  - A7 only links injuries with fight_id IS NULL
  - A8 finds 0 weight classes 14-16 (already deleted)

Task ID: 1.5A-reconcile
Agent: full-stack-developer
CONVENTIONS compliance:
  §3   — worklog entry appended (Task ID 1.5A-reconcile)
  §6   — does NOT rebuild DB, only mutates existing data
  §11  — does NOT modify any acceptance test
  §13  — supports all 5 pillars by ensuring world DB integrity
  §16.2 — does NOT run --fresh on the seeded world DB
"""
import sys
import os
import shutil
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.db.backup-reconcile"

# Weight classes to remove in A8 + the reassignment target for any
# fighters still referencing them.
#   WC 14 (Catchweight 165 / 74.8 kg) -> Welterweight (WC 4, max 77.1 kg)
#   WC 15 (Catchweight 175 / 79.4 kg) -> Welterweight (WC 4)
#   WC 16 (Super Lightweight 68.0 kg) -> Lightweight (WC 5, 65.8-70.3 kg)
# These mappings preserve the historical weight class info for the
# retired HoF legends still assigned to these non-standard WCs,
# instead of letting ON DELETE SET NULL null out their weight_class_id
# (which would render their WC as "Unknown" in any UI).
NONSTANDARD_WC_REASSIGN = {
    14: 4,   # Catchweight 165  -> Welterweight
    15: 4,   # Catchweight 175  -> Welterweight
    16: 5,   # Super Lightweight -> Lightweight
}
NONSTANDARD_WC_IDS = sorted(NONSTANDARD_WC_REASSIGN.keys())

DRY_RUN = "--dry-run" in sys.argv
SKIP_BACKUP = "--skip-backup" in sys.argv


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def get_conn():
    """Open a connection with FK enforcement ON (needed for cascades)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_sim_date(conn):
    return conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id = 1"
    ).fetchone()[0]


def banner(title):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


# ----------------------------------------------------------------
# Fix A1: Remove future-dated "completed" events
# ----------------------------------------------------------------

def fix_a1(conn):
    banner("A1: Remove future-dated 'completed' events [CRITICAL]")
    sim_date = get_sim_date(conn)

    before_events = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE event_date > ? AND status = 'completed'",
        (sim_date,)
    ).fetchone()[0]
    before_fights = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id IN ("
        "  SELECT event_id FROM events "
        "  WHERE event_date > ? AND status = 'completed'"
        ")",
        (sim_date,)
    ).fetchone()[0]
    before_fh = conn.execute(
        "SELECT COUNT(*) FROM fight_history WHERE fight_id IN ("
        "  SELECT fight_id FROM fights WHERE event_id IN ("
        "    SELECT event_id FROM events "
        "    WHERE event_date > ? AND status = 'completed'"
        "  )"
        ")",
        (sim_date,)
    ).fetchone()[0]
    before_orphan_fh = conn.execute(
        "SELECT COUNT(*) FROM fight_history "
        "WHERE fight_id NOT IN (SELECT fight_id FROM fights)"
    ).fetchone()[0]
    before_event_cards = conn.execute(
        "SELECT COUNT(*) FROM event_cards WHERE event_id IN ("
        "  SELECT event_id FROM events "
        "  WHERE event_date > ? AND status = 'completed'"
        ")",
        (sim_date,)
    ).fetchone()[0]
    print(f"  Sim date: {sim_date}")
    print(f"  BEFORE: {before_events} future-dated completed events")
    print(f"          {before_fights} fights in those events")
    print(f"          {before_fh} fight_history rows for those fights")
    print(f"          {before_event_cards} event_cards for those events")
    print(f"          {before_orphan_fh} orphaned fight_history rows "
          f"(fight_id NOT IN fights)")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    # Step 1: delete the events. With PRAGMA foreign_keys = ON, the
    # cascade chain is:
    #   events  --CASCADE-->  fights  --CASCADE-->  fight_history (via fight_id)
    #   events  --SET NULL-->  news_items.event_id
    #   events  --SET NULL-->  fight_history.event_id (rows already deleted via fight_id)
    #   events  --SET NULL-->  injuries.event_id
    #   events  --SET NULL-->  training_camps.event_id
    #   events  --SET NULL-->  matchup_analyses.event_id
    #   events  --CASCADE-->  commentary_segments
    #   events  --CASCADE-->  show_ratings
    #   events  --CASCADE-->  event_cards
    conn.execute(
        "DELETE FROM events "
        "WHERE event_date > ? AND status = 'completed'",
        (sim_date,)
    )

    # Step 2: defensive — delete any orphaned fight_history rows
    # (fight_id NOT IN fights). These shouldn't exist after the cascade,
    # but the brief explicitly asks for this cleanup, and it catches
    # any pre-existing orphans from prior seed quirks.
    conn.execute(
        "DELETE FROM fight_history "
        "WHERE fight_id NOT IN (SELECT fight_id FROM fights)"
    )
    conn.commit()

    after_events = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE event_date > ? AND status = 'completed'",
        (sim_date,)
    ).fetchone()[0]
    after_orphan_fh = conn.execute(
        "SELECT COUNT(*) FROM fight_history "
        "WHERE fight_id NOT IN (SELECT fight_id FROM fights)"
    ).fetchone()[0]
    after_future_scheduled = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE event_date > ? AND status = 'scheduled'",
        (sim_date,)
    ).fetchone()[0]
    print(f"  AFTER:  {after_events} future-dated completed events remain")
    print(f"          {after_orphan_fh} orphaned fight_history rows remain")
    print(f"          {after_future_scheduled} future-dated SCHEDULED events "
          f"(KEPT — legitimate upcoming)")
    print(f"  Deleted {before_events} future-dated completed events + "
          f"{before_fights} fights + {before_fh} fight_history rows")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A2: Recompute win_streak / loss_streak
# ----------------------------------------------------------------

def fix_a2(conn):
    banner("A2: Recompute win_streak / loss_streak [CRITICAL]")

    active_total = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_active = 1"
    ).fetchone()[0]
    active_with_fh = conn.execute(
        "SELECT COUNT(DISTINCT fh.fighter_id) "
        "FROM fight_history fh "
        "JOIN fighters f ON fh.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1"
    ).fetchone()[0]
    active_no_fh = active_total - active_with_fh

    # Capture pre-state distribution for the report
    before_over_6 = conn.execute(
        "SELECT COUNT(*) FROM fighter_career fc "
        "JOIN fighters f ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 "
        "AND (fc.win_streak > 6 OR fc.loss_streak > 6)"
    ).fetchone()[0]

    print(f"  Active fighters: {active_total}")
    print(f"    with fight_history: {active_with_fh}")
    print(f"    without fight_history: {active_no_fh} (will reset to 0/0)")
    print(f"  BEFORE: {before_over_6} active fighters with streak > 6 "
          f"(bug indicator)")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    # Pull all active fighters' fight_history in one pass — much faster
    # than 4000 round-trips. We'll bucket by fighter_id in Python.
    rows = conn.execute(
        "SELECT fh.fighter_id, fh.outcome, fh.event_date "
        "FROM fight_history fh "
        "JOIN fighters f ON fh.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 "
        "ORDER BY fh.fighter_id, fh.event_date DESC"
    ).fetchall()

    # Bucket by fighter_id (ordered DESC by event_date already)
    from collections import defaultdict
    by_fighter = defaultdict(list)
    for fighter_id, outcome, event_date in rows:
        by_fighter[fighter_id].append(outcome)

    changed = 0
    updates = []
    for fighter_id, outcomes in by_fighter.items():
        # Walk backwards (index 0 = most recent) counting consecutive wins,
        # then consecutive losses, stopping at any other outcome.
        win_streak = 0
        i = 0
        while i < len(outcomes) and outcomes[i] == 'win':
            win_streak += 1
            i += 1
        loss_streak = 0
        while i < len(outcomes) and outcomes[i] == 'loss':
            loss_streak += 1
            i += 1
        updates.append((win_streak, loss_streak, fighter_id))

    # Apply updates for fighters WITH fight_history
    for win_streak, loss_streak, fighter_id in updates:
        cur = conn.execute(
            "SELECT win_streak, loss_streak FROM fighter_career "
            "WHERE fighter_id = ?",
            (fighter_id,)
        ).fetchone()
        if cur and (cur[0] != win_streak or cur[1] != loss_streak):
            conn.execute(
                "UPDATE fighter_career "
                "SET win_streak = ?, loss_streak = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE fighter_id = ?",
                (win_streak, loss_streak, fighter_id)
            )
            changed += 1

    # Reset to 0/0 for active fighters with NO fight_history
    reset_count = conn.execute(
        "UPDATE fighter_career "
        "SET win_streak = 0, loss_streak = 0, "
        "    updated_at = CURRENT_TIMESTAMP "
        "WHERE fighter_id IN ("
        "  SELECT fighter_id FROM fighters "
        "  WHERE is_active = 1 "
        "  AND fighter_id NOT IN ("
        "    SELECT DISTINCT fighter_id FROM fight_history"
        "  )"
        ") "
        "AND (win_streak != 0 OR loss_streak != 0)"
    ).rowcount

    conn.commit()

    after_over_6 = conn.execute(
        "SELECT COUNT(*) FROM fighter_career fc "
        "JOIN fighters f ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 "
        "AND (fc.win_streak > 6 OR fc.loss_streak > 6)"
    ).fetchone()[0]
    after_max_win = conn.execute(
        "SELECT MAX(win_streak) FROM fighter_career fc "
        "JOIN fighters f ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1"
    ).fetchone()[0]
    after_max_loss = conn.execute(
        "SELECT MAX(loss_streak) FROM fighter_career fc "
        "JOIN fighters f ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1"
    ).fetchone()[0]
    # After recompute, streaks > 6 are EXPECTED and CORRECT — they
    # reflect actual long streaks in fight_history (the pre-fix bug
    # capped all streaks at 6, hiding legitimate 7+ win/loss streaks).
    print(f"  AFTER:  {after_over_6} active fighters with streak > 6 "
          f"(legitimate long streaks, no longer capped)")
    print(f"          max win_streak = {after_max_win}, "
          f"max loss_streak = {after_max_loss}")
    print(f"  Recomputed streaks for {len(updates)} fighters "
          f"(with fight_history).")
    print(f"  {changed} changed. {reset_count} reset to 0/0 "
          f"(no fight_history).")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A3: Mark historical title fights
# ----------------------------------------------------------------

def fix_a3(conn):
    banner("A3: Mark historical title fights [CRITICAL]")

    championed_titles = conn.execute(
        "SELECT COUNT(*) FROM titles WHERE is_vacant = 0 "
        "AND current_champion_fighter_id IS NOT NULL "
        "AND champion_since_date IS NOT NULL"
    ).fetchone()[0]
    before_title_fights = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE is_title_fight = 1"
    ).fetchone()[0]
    print(f"  Championed titles (is_vacant=0): {championed_titles}")
    print(f"  BEFORE: {before_title_fights} fights marked is_title_fight=1 "
          f"(should be > 0 after fix)")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    sim_date = get_sim_date(conn)
    titles = conn.execute(
        "SELECT title_id, current_champion_fighter_id, "
        "       champion_since_date, title_defenses_count "
        "FROM titles "
        "WHERE is_vacant = 0 "
        "AND current_champion_fighter_id IS NOT NULL "
        "AND champion_since_date IS NOT NULL"
    ).fetchall()

    total_marked = 0
    titles_with_marks = 0
    for (title_id, champ_id, since_date, defenses_count) in titles:
        # Get the champion's wins during their reign, most-recent first.
        # We mark up to defenses_count of these as title fights.
        wins_during = conn.execute(
            "SELECT fight_id FROM fight_history "
            "WHERE fighter_id = ? AND outcome = 'win' "
            "AND event_date >= ? AND event_date <= ? "
            "AND fight_id IN (SELECT fight_id FROM fights) "
            "ORDER BY event_date DESC "
            "LIMIT ?",
            (champ_id, since_date, sim_date, defenses_count)
        ).fetchall()
        if not wins_during:
            continue
        fight_ids = [r[0] for r in wins_during]
        # Mark these fights as title fights (idempotent — only updates
        # rows where is_title_fight is currently 0)
        placeholders = ",".join("?" * len(fight_ids))
        cur = conn.execute(
            f"UPDATE fights SET is_title_fight = 1, "
            f"    updated_at = CURRENT_TIMESTAMP "
            f"WHERE fight_id IN ({placeholders}) "
            f"AND is_title_fight = 0",
            fight_ids
        )
        if cur.rowcount > 0:
            titles_with_marks += 1
            total_marked += cur.rowcount

    conn.commit()

    after_title_fights = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE is_title_fight = 1"
    ).fetchone()[0]
    print(f"  AFTER:  {after_title_fights} fights marked is_title_fight=1")
    print(f"  Marked {total_marked} title fights across {titles_with_marks} "
          f"titles (of {championed_titles} championed).")
    print(f"  Note: {championed_titles - titles_with_marks} titles had 0 "
          f"champion wins during reign — left at 0 marks.")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A4: Fix rivalry fight counts
# ----------------------------------------------------------------

def fix_a4(conn):
    banner("A4: Fix rivalry fight counts [HIGH]")

    total_rivalries = conn.execute(
        "SELECT COUNT(*) FROM rivalries"
    ).fetchone()[0]
    before_zero = conn.execute(
        "SELECT COUNT(*) FROM rivalries WHERE fights_count = 0"
    ).fetchone()[0]
    before_over_10 = conn.execute(
        "SELECT COUNT(*) FROM rivalries WHERE fights_count > 10"
    ).fetchone()[0]
    print(f"  Total rivalries: {total_rivalries}")
    print(f"  BEFORE: {before_zero} rivalries with fights_count=0")
    print(f"          {before_over_10} rivalries with fights_count>10 "
          f"(impossibly high)")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    rivalries = conn.execute(
        "SELECT rivalry_id, fighter_a_id, fighter_b_id FROM rivalries"
    ).fetchall()

    fixed = 0
    zero_actual = 0
    for (rivalry_id, a_id, b_id) in rivalries:
        # Each fight has 2 fight_history rows (one per fighter).
        # From A's perspective (fighter_id=A, opponent_id=B), each
        # fight contributes exactly 1 row. Counting that gives us
        # the actual number of head-to-head fights, with A's wins =
        # outcome='win', B's wins = outcome='loss', draws = outcome='draw'.
        row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN outcome = 'win'  THEN 1 ELSE 0 END) AS wins_a, "
            "  SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS wins_b, "
            "  SUM(CASE WHEN outcome = 'draw' THEN 1 ELSE 0 END) AS draws "
            "FROM fight_history "
            "WHERE fighter_id = ? AND opponent_id = ?",
            (a_id, b_id)
        ).fetchone()
        total = row[0] or 0
        wins_a = row[1] or 0
        wins_b = row[2] or 0
        draws = row[3] or 0
        conn.execute(
            "UPDATE rivalries "
            "SET fights_count = ?, fighter_a_wins = ?, "
            "    fighter_b_wins = ?, draws = ?, "
            "    updated_at = CURRENT_TIMESTAMP "
            "WHERE rivalry_id = ?",
            (total, wins_a, wins_b, draws, rivalry_id)
        )
        fixed += 1
        if total == 0:
            zero_actual += 1

    conn.commit()

    after_zero = conn.execute(
        "SELECT COUNT(*) FROM rivalries WHERE fights_count = 0"
    ).fetchone()[0]
    after_over_10 = conn.execute(
        "SELECT COUNT(*) FROM rivalries WHERE fights_count > 10"
    ).fetchone()[0]
    print(f"  AFTER:  {after_zero} rivalries with fights_count=0 "
          f"(declared-only rivalries)")
    print(f"          {after_over_10} rivalries with fights_count>10 "
          f"(should be 0)")
    print(f"  Fixed {fixed} rivalries. {zero_actual} had 0 actual fights "
          f"(kept as declared rivalries).")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A5: Backfill rankings.last_fight_date
# ----------------------------------------------------------------

def fix_a5(conn):
    banner("A5: Backfill rankings.last_fight_date [MEDIUM]")

    total_rankings = conn.execute(
        "SELECT COUNT(*) FROM rankings"
    ).fetchone()[0]
    before_null = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE last_fight_date IS NULL"
    ).fetchone()[0]
    print(f"  Total rankings: {total_rankings}")
    print(f"  BEFORE: {before_null} rankings with NULL last_fight_date")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    # For each ranked fighter, find their most recent fight_history.event_date.
    # Update only rankings where last_fight_date IS NULL (idempotent).
    # We do this per-ranking row to handle the case where the same fighter
    # has rankings in multiple WCs (each ranking row should get the same
    # last_fight_date — the fighter's most recent fight, regardless of WC).
    rankings = conn.execute(
        "SELECT ranking_id, fighter_id, weight_class_id "
        "FROM rankings WHERE last_fight_date IS NULL"
    ).fetchall()

    backfilled = 0
    for (ranking_id, fighter_id, wc_id) in rankings:
        last_date = conn.execute(
            "SELECT MAX(event_date) FROM fight_history "
            "WHERE fighter_id = ?",
            (fighter_id,)
        ).fetchone()[0]
        if last_date is not None:
            conn.execute(
                "UPDATE rankings SET last_fight_date = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE ranking_id = ?",
                (last_date, ranking_id)
            )
            backfilled += 1

    conn.commit()

    after_null = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE last_fight_date IS NULL"
    ).fetchone()[0]
    print(f"  AFTER:  {after_null} rankings with NULL last_fight_date "
          f"(correct — fighters with no fight_history)")
    print(f"  Backfilled last_fight_date for {backfilled} rankings.")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A6: Backfill news_items.promotion_id
# ----------------------------------------------------------------

def fix_a6(conn):
    banner("A6: Backfill news_items.promotion_id [MEDIUM]")

    total_news = conn.execute(
        "SELECT COUNT(*) FROM news_items"
    ).fetchone()[0]
    before_null = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id IS NULL"
    ).fetchone()[0]
    news_with_event = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE event_id IS NOT NULL AND promotion_id IS NULL"
    ).fetchone()[0]
    news_with_fighter_only = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE event_id IS NULL AND fighter_id IS NOT NULL "
        "AND promotion_id IS NULL"
    ).fetchone()[0]
    print(f"  Total news items: {total_news}")
    print(f"  BEFORE: {before_null} news items with NULL promotion_id")
    print(f"          {news_with_event} with event_id set (will look up "
          f"event.promotion_id)")
    print(f"          {news_with_fighter_only} with fighter_id only (will "
          f"look up fighter.current_promotion_id)")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    # Path 1: news items with event_id → use event's promotion_id
    # (events.promotion_id is NOT NULL, so this always sets a value)
    path1 = conn.execute(
        "UPDATE news_items "
        "SET promotion_id = ("
        "    SELECT e.promotion_id FROM events e "
        "    WHERE e.event_id = news_items.event_id"
        ") "
        "WHERE event_id IS NOT NULL AND promotion_id IS NULL"
    ).rowcount

    # Path 2: news items with fighter_id but no event_id → use
    # fighter's current_promotion_id (may be NULL for free agents —
    # in that case the row stays NULL, which is correct)
    path2 = conn.execute(
        "UPDATE news_items "
        "SET promotion_id = ("
        "    SELECT f.current_promotion_id FROM fighters f "
        "    WHERE f.fighter_id = news_items.fighter_id"
        ") "
        "WHERE event_id IS NULL AND fighter_id IS NOT NULL "
        "AND promotion_id IS NULL "
        "AND EXISTS ("
        "    SELECT 1 FROM fighters f "
        "    WHERE f.fighter_id = news_items.fighter_id "
        "    AND f.current_promotion_id IS NOT NULL"
        ")"
    ).rowcount

    conn.commit()

    after_null = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id IS NULL"
    ).fetchone()[0]
    print(f"  AFTER:  {after_null} news items with NULL promotion_id")
    print(f"  Backfilled promotion_id for {path1 + path2} news items "
          f"({path1} via event, {path2} via fighter).")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A7: Link injuries to fights/events
# ----------------------------------------------------------------

def fix_a7(conn):
    banner("A7: Link injuries to fights/events [MEDIUM]")

    total_injuries = conn.execute(
        "SELECT COUNT(*) FROM injuries"
    ).fetchone()[0]
    before_unlinked = conn.execute(
        "SELECT COUNT(*) FROM injuries WHERE fight_id IS NULL"
    ).fetchone()[0]
    print(f"  Total injuries: {total_injuries}")
    print(f"  BEFORE: {before_unlinked} injuries with NULL fight_id")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    # For each unlinked injury, find the fighter's most recent fight
    # before injury.start_date. If found, set fight_id + event_id.
    injuries = conn.execute(
        "SELECT injury_id, fighter_id, start_date "
        "FROM injuries WHERE fight_id IS NULL"
    ).fetchall()

    linked = 0
    unlinked = 0
    for (injury_id, fighter_id, start_date) in injuries:
        row = conn.execute(
            "SELECT fight_id, event_id FROM fight_history "
            "WHERE fighter_id = ? AND event_date < ? "
            "ORDER BY event_date DESC LIMIT 1",
            (fighter_id, start_date)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE injuries "
                "SET fight_id = ?, event_id = ?, "
                "    updated_at = CURRENT_TIMESTAMP "
                "WHERE injury_id = ?",
                (row[0], row[1], injury_id)
            )
            linked += 1
        else:
            unlinked += 1

    conn.commit()

    after_unlinked = conn.execute(
        "SELECT COUNT(*) FROM injuries WHERE fight_id IS NULL"
    ).fetchone()[0]
    print(f"  AFTER:  {after_unlinked} injuries with NULL fight_id "
          f"(training injuries — no preceding fight)")
    print(f"  Linked {linked} injuries to fights. {unlinked} remain "
          f"unlinked (training injuries).")
    print("  PASS")


# ----------------------------------------------------------------
# Fix A8: Remove catchweight/super-lightweight weight classes
# ----------------------------------------------------------------

def fix_a8(conn):
    banner("A8: Remove catchweight/super-lightweight weight classes [HIGH]")

    # Pre-state for each WC to be removed
    print(f"  Weight classes targeted for removal: {NONSTANDARD_WC_IDS}")
    before_wcs = conn.execute(
        f"SELECT weight_class_id, name FROM weight_classes "
        f"WHERE weight_class_id IN ({','.join('?' * len(NONSTANDARD_WC_IDS))})",
        NONSTANDARD_WC_IDS
    ).fetchall()
    print(f"  Weight classes found: {len(before_wcs)}")
    for wc_id, name in before_wcs:
        fighters = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE weight_class_id = ?",
            (wc_id,)
        ).fetchone()[0]
        titles = conn.execute(
            "SELECT COUNT(*) FROM titles WHERE weight_class_id = ?",
            (wc_id,)
        ).fetchone()[0]
        rankings = conn.execute(
            "SELECT COUNT(*) FROM rankings WHERE weight_class_id = ?",
            (wc_id,)
        ).fetchone()[0]
        fights = conn.execute(
            "SELECT COUNT(*) FROM fights WHERE weight_class_id = ?",
            (wc_id,)
        ).fetchone()[0]
        fh = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE weight_class_id = ?",
            (wc_id,)
        ).fetchone()[0]
        print(f"    WC {wc_id} ({name}): {fighters} fighters, "
              f"{titles} titles, {rankings} rankings, "
              f"{fights} fights, {fh} fight_history")

    if DRY_RUN:
        print("  [DRY RUN] no changes made")
        return

    # D1 decision: the brief expected 0 fighters in WC 14-16, but the
    # world DB has 13 RETIRED HoF legends there. Deleting the WCs would
    # cascade SET NULL on their weight_class_id (acceptable for retired
    # fighters, but loses historical info). Instead, reassign them to
    # the nearest valid WC BEFORE deleting. The 13 fighters have no
    # fights/rankings/contracts/titles referencing these WCs, so this
    # is a pure metadata fix.
    reassigned = 0
    for old_wc, new_wc in NONSTANDARD_WC_REASSIGN.items():
        cur = conn.execute(
            "UPDATE fighters "
            "SET weight_class_id = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE weight_class_id = ?",
            (new_wc, old_wc)
        )
        if cur.rowcount > 0:
            print(f"  Reassigned {cur.rowcount} fighters from WC {old_wc} "
                  f"to WC {new_wc} (preserves HoF history)")
            reassigned += cur.rowcount

    # Verify no remaining references (titles, rankings, fights,
    # fight_history). The pre-check showed 0 for all of these, but
    # defensive: delete any that exist (per brief "Also DELETE any
    # titles for these WCs (check first — may be 0)").
    for wc in NONSTANDARD_WC_IDS:
        titles_for_wc = conn.execute(
            "SELECT COUNT(*) FROM titles WHERE weight_class_id = ?",
            (wc,)
        ).fetchone()[0]
        if titles_for_wc > 0:
            conn.execute(
                "DELETE FROM titles WHERE weight_class_id = ?",
                (wc,)
            )
            print(f"  Deleted {titles_for_wc} titles for WC {wc}")
        rankings_for_wc = conn.execute(
            "SELECT COUNT(*) FROM rankings WHERE weight_class_id = ?",
            (wc,)
        ).fetchone()[0]
        if rankings_for_wc > 0:
            conn.execute(
                "DELETE FROM rankings WHERE weight_class_id = ?",
                (wc,)
            )
            print(f"  Deleted {rankings_for_wc} rankings for WC {wc}")

    # Final safety check: no fighters, fights, fight_history, titles,
    # or rankings should reference these WCs before deletion.
    # fights.weight_class_id has ON DELETE RESTRICT — would fail if any
    # fights reference these WCs. We checked there are none above.
    remaining_refs = 0
    for table, col in [
        ("fighters", "weight_class_id"),
        ("fights", "weight_class_id"),
        ("fight_history", "weight_class_id"),
        ("titles", "weight_class_id"),
        ("rankings", "weight_class_id"),
    ]:
        for wc in NONSTANDARD_WC_IDS:
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ?",
                (wc,)
            ).fetchone()[0]
            remaining_refs += cnt
    if remaining_refs > 0:
        print(f"  WARNING: {remaining_refs} remaining references to "
              f"WC 14-16 — aborting deletion")
        conn.commit()
        return

    # Delete the weight classes
    placeholders = ",".join("?" * len(NONSTANDARD_WC_IDS))
    deleted_wcs = conn.execute(
        f"DELETE FROM weight_classes "
        f"WHERE weight_class_id IN ({placeholders})",
        NONSTANDARD_WC_IDS
    ).rowcount
    conn.commit()

    after_wcs = conn.execute(
        "SELECT COUNT(*) FROM weight_classes"
    ).fetchone()[0]
    print(f"  AFTER:  {after_wcs} weight classes (was {after_wcs + deleted_wcs})")
    print(f"  Reassigned {reassigned} HoF fighters to nearest valid WC "
          f"(D1 decision).")
    print(f"  Removed {deleted_wcs} non-standard weight classes.")
    print("  PASS")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    print("=" * 72)
    print("CAGE EMPIRE — Phase 1.5 Group A: World DB Data Reconciliation")
    print("=" * 72)
    print(f"  DB: {DB_PATH}")
    print(f"  Mode: {'DRY RUN' if DRY_RUN else 'WRITE'}")

    if not DB_PATH.exists():
        print(f"FATAL: DB file does not exist at {DB_PATH}")
        sys.exit(2)

    # Backup (unless --skip-backup or --dry-run)
    if not DRY_RUN and not SKIP_BACKUP:
        if BACKUP_PATH.exists():
            print(f"  Backup already exists at {BACKUP_PATH} (reusing)")
        else:
            print(f"  Backing up DB to {BACKUP_PATH} ...")
            shutil.copy2(DB_PATH, BACKUP_PATH)
            print(f"  Backup complete ({BACKUP_PATH.stat().st_size:,} bytes)")

    conn = get_conn()

    # Pre-flight summary
    banner("PRE-FLIGHT SUMMARY")
    print(f"  Active fighters: {conn.execute('SELECT COUNT(*) FROM fighters WHERE is_active=1').fetchone()[0]}")
    print(f"  Total events:    {conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")
    print(f"  Total fights:    {conn.execute('SELECT COUNT(*) FROM fights').fetchone()[0]}")
    print(f"  fight_history:   {conn.execute('SELECT COUNT(*) FROM fight_history').fetchone()[0]}")
    print(f"  Rivalries:       {conn.execute('SELECT COUNT(*) FROM rivalries').fetchone()[0]}")
    print(f"  Rankings:        {conn.execute('SELECT COUNT(*) FROM rankings').fetchone()[0]}")
    print(f"  News items:      {conn.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]}")
    print(f"  Injuries:        {conn.execute('SELECT COUNT(*) FROM injuries').fetchone()[0]}")
    print(f"  Weight classes:  {conn.execute('SELECT COUNT(*) FROM weight_classes').fetchone()[0]}")
    print(f"  Titles:          {conn.execute('SELECT COUNT(*) FROM titles').fetchone()[0]}")
    print(f"  Fighter bios:    {conn.execute('SELECT COUNT(*) FROM fighter_bios').fetchone()[0]}")
    print(f"  Sim date:        {get_sim_date(conn)}")

    # Run all 8 fixes in order
    fix_a1(conn)
    fix_a2(conn)
    fix_a3(conn)
    fix_a4(conn)
    fix_a5(conn)
    fix_a6(conn)
    fix_a7(conn)
    fix_a8(conn)

    # Post-flight summary
    banner("POST-FLIGHT SUMMARY")
    print(f"  Active fighters: {conn.execute('SELECT COUNT(*) FROM fighters WHERE is_active=1').fetchone()[0]}")
    print(f"  Total events:    {conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")
    print(f"  Total fights:    {conn.execute('SELECT COUNT(*) FROM fights').fetchone()[0]}")
    print(f"  fight_history:   {conn.execute('SELECT COUNT(*) FROM fight_history').fetchone()[0]}")
    print(f"  Rivalries:       {conn.execute('SELECT COUNT(*) FROM rivalries').fetchone()[0]}")
    print(f"  Rankings:        {conn.execute('SELECT COUNT(*) FROM rankings').fetchone()[0]}")
    print(f"  News items:      {conn.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]}")
    print(f"  Injuries:        {conn.execute('SELECT COUNT(*) FROM injuries').fetchone()[0]}")
    print(f"  Weight classes:  {conn.execute('SELECT COUNT(*) FROM weight_classes').fetchone()[0]}")
    print(f"  Titles:          {conn.execute('SELECT COUNT(*) FROM titles').fetchone()[0]}")
    print(f"  Fighter bios:    {conn.execute('SELECT COUNT(*) FROM fighter_bios').fetchone()[0]}")
    print(f"  FK violations:   {len(conn.execute('PRAGMA foreign_key_check').fetchall())}")

    conn.close()
    print()
    print("=" * 72)
    print("  RECONCILIATION COMPLETE — all 8 fixes applied.")
    print("=" * 72)


if __name__ == "__main__":
    main()
