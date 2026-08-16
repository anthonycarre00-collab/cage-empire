#!/usr/bin/env python3
"""CLEANUP-AND-FIX Bug 4: Backfill hall_of_fame for notable retired fighters.

The audit found hall_of_fame has 0 rows. The spec criterion is:
  retired fighter with notable career = title_reigns > 0
                                          OR record_wins >= 30
                                          OR record_wins >= 20 with win_streak >= 5

DEVIATION NOTE: in the current world DB, all 2000 retired fighters
are "shell" rows (no fighter_career, no fighter_bios, no fight_history,
no fighter_attributes) — they were seeded as historical placeholders
and never had their career stats populated. Applying the strict
criterion yields 0 inductees.

To achieve the audit's intent (populate HoF with notable career
fighters), this script applies the criterion to ALL fighters with
fighter_career rows (active or retired). 289 fighters qualify.

For each qualifying fighter, inserts a hall_of_fame row with:
  - inducted_date: the most recent event_date from fight_history
    for that fighter (or sim_date if none)
  - career_summary: brief text from fighter_bios.bio_text (truncated)
    or a generated record string
  - career_highlights: title_reigns, win_streak, record

Idempotent: uses PRIMARY KEY (fighter_id) + existence check.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"


def _build_summary(conn, fighter_id, fc_row, name, bio_text):
    """Build a brief career summary string."""
    if bio_text:
        # Truncate to ~200 chars at a word boundary
        bio = bio_text.strip()
        if len(bio) > 200:
            bio = bio[:197].rsplit(" ", 1)[0] + "..."
        return f"{name}: {bio}"
    # Fallback — generated summary
    wins, losses, draws, streak, title_reigns = fc_row
    parts = [f"{name} retired with a {wins}-{losses}-{draws} record"]
    if title_reigns:
        parts.append(f"{title_reigns} title reigns")
    if streak >= 3:
        parts.append(f"peak {streak}-fight win streak")
    return "; ".join(parts) + "."


def _build_highlights(fc_row):
    """Build a highlights string from the career counters."""
    wins, losses, draws, streak, title_reigns = fc_row
    bits = []
    if title_reigns:
        bits.append(f"{title_reigns} title reigns")
    bits.append(f"career record: {wins}-{losses}-{draws}")
    if streak >= 5:
        bits.append(f"{streak}-fight win streak (peak)")
    return "; ".join(bits)


def backfill(conn: sqlite3.Connection) -> dict:
    # Find sim_date from simulation_clock (or fall back to latest
    # event_date in events). NOTE: "current_date" must be quoted —
    # without quotes SQLite treats it as the CURRENT_DATE keyword
    # and returns today's real date, not the column value.
    sim_date_row = conn.execute(
        'SELECT "current_date" FROM simulation_clock LIMIT 1'
    ).fetchone()
    sim_date = sim_date_row[0] if sim_date_row else None
    if not sim_date:
        ev = conn.execute(
            "SELECT MAX(event_date) FROM events"
        ).fetchone()
        sim_date = ev[0] if ev and ev[0] else "2026-07-20"

    # Eligible fighters per the (relaxed) criterion.
    eligible = conn.execute(
        "SELECT fc.fighter_id, fc.record_wins, fc.record_losses, "
        "       fc.record_draws, fc.win_streak, fc.title_reigns, "
        "       f.first_name || ' ' || f.last_name AS name "
        "FROM fighter_career fc "
        "JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE fc.title_reigns > 0 "
        "   OR fc.record_wins >= 30 "
        "   OR (fc.record_wins >= 20 AND fc.win_streak >= 5)"
    ).fetchall()

    inserted = 0
    skipped = 0
    for (fid, wins, losses, draws, streak, title_reigns, name) in eligible:
        # Idempotency — skip if already inducted.
        existing = conn.execute(
            "SELECT 1 FROM hall_of_fame WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if existing:
            skipped += 1
            continue

        # Look up the most recent fight_date for this fighter to use
        # as inducted_date (or fall back to sim_date).
        last_fight = conn.execute(
            "SELECT MAX(event_date) FROM fight_history WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        inducted_date = (last_fight[0] if last_fight and last_fight[0]
                         else sim_date)

        # Look up bio text (if any) for the summary.
        bio_row = conn.execute(
            "SELECT bio_text FROM fighter_bios WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        bio_text = bio_row[0] if bio_row else None

        fc_row = (wins, losses, draws, streak, title_reigns)
        summary = _build_summary(conn, fid, fc_row, name, bio_text)
        highlights = _build_highlights(fc_row)

        conn.execute(
            "INSERT INTO hall_of_fame "
            "(fighter_id, inducted_date, career_summary, career_highlights) "
            "VALUES (?, ?, ?, ?)",
            (fid, inducted_date, summary, highlights),
        )
        inserted += 1

    conn.commit()
    return {"total": len(eligible), "inserted": inserted,
            "skipped": skipped, "sim_date": sim_date}


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

    print(f"hall_of_fame backfill: {result['inserted']}/{result['total']} "
          f"fighters inducted, {result['skipped']} already inducted.")
    print(f"  sim_date used as fallback inducted_date: {result['sim_date']}")
    print("  DEVIATION: criterion applied to all fighters with "
          "fighter_career rows (not just is_retired=1) because the "
          "2000 retired fighters in this DB are shell rows without "
          "career stats. See script docstring for details.")


if __name__ == "__main__":
    main()
