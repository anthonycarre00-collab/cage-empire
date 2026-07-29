#!/usr/bin/env python3
"""CAGE EMPIRE — Backfill missing fighter_descriptors snapshots (Phase 2 Task 2.0c).

The world seed (scripts/seed_world_phase3.py) created 4000 original
fighters, each of which got a fighter_descriptors snapshot row during
seeding (the seed script calls voice.build_descriptor_snapshot() and
inserts the row directly). Then Phase 1.5 Group B added 450 new
active fighters (B1 — populated the 3 empty male weight classes) and
Group A8 + the HoF seeding added 60 retired Hall of Fame legends —
but NEITHER group got fighter_descriptors rows. They were added to
the fighters table without the descriptor snapshot being computed.

This script closes that gap. It:
  1. Finds every active fighter with no fighter_descriptors row
     (expected: 450 Group B fighters).
  2. Finds every retired legend with no fighter_descriptors row
     (expected: 60 HoF legends — they got backfilled attributes via
     scripts/backfill_legends.py in Stage 6 prep, but that script
     only backfills attributes/personality/career; it doesn't compute
     the descriptor snapshot).
  3. For each, calls update_fighter_descriptor_snapshot(conn,
     fighter_id) — the standard trigger-path function from
     services.fight_engine.py that reads fighter_attributes,
     fighter_personality, fighter_career, computes voice descriptors,
     and INSERT-or-REPLACEs the row.

After this script runs, every fighter (active + retired) has a
fighter_descriptors row, so Office Mode UI screens can rely on
SELECT-from-fighter_descriptors without needing a NULL fallback.

NOTE: The 6 new interpretation columns added in v3.10.0
(momentum, pressure, career_phase, narrative_family,
public_narrative, legacy_state) are NOT populated by this script.
They default to NULL — they'll be filled by the daily interpretation
pass in subsequent Phase 2 tasks (2.2/2.3/2.4/2.7). This script
only ensures the BASE descriptor snapshot exists (attribute_descriptors,
personality_descriptors, career_stage, career_health_desc, overall_desc).

Usage:
    python3 scripts/backfill_missing_snapshots.py
    python3 scripts/backfill_missing_snapshots.py --dry-run  # show counts only

CONVENTIONS compliance:
  §5  — One table-group per task. This script writes to ONE existing
        table (fighter_descriptors — cache table per §17.3) and reads
        from simulation tables (fighters, fighter_attributes,
        fighter_personality, fighter_career — read-only). No schema
        changes (the migration already ran in build_db.py
        _migrate_v3_10_0_extend_fighter_descriptors).
  §6  — Smoke test protocol. Run forensic_db_check.py before and
        after to verify the backfill.
  §14 — Voice layer. update_fighter_descriptor_snapshot calls
        voice.build_descriptor_snapshot() which produces voice-phrased
        descriptors (no raw numbers). The snapshot is what the UI
        displays — no §14 violation.
  §16 — Migration workflow. This script is the data-backfill
        companion to the schema migration. It's idempotent (LEFT
        JOIN ... IS NULL guard) and safe to re-run.
  §17 — UI Snapshot Rule. fighter_descriptors is a CACHE table —
        the interpretation layer is the ONLY writer. This script
        uses the same writer function the simulation uses on
        trigger events (update_fighter_descriptor_snapshot), so it
        respects the writer contract.
"""
import sys
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
SRC_DIR = PROJECT_DIR / "src"

DRY_RUN = "--dry-run" in sys.argv

# Make src/ importable so we can import services.fight_engine.
# This mirrors the pattern in scripts/group_c_seed.py.
sys.path.insert(0, str(SRC_DIR))

# Import the standard descriptor-snapshot writer. This is the SAME
# function the simulation calls on FIGHT_RESOLVED / TRAINING_CAMP_COMPLETED
# / INURY_CREATED / TITLE_CHANGED events — using it here keeps the
# backfill consistent with the live trigger path (no bespoke writer
# that could drift from the real one).
from services.fight_engine import update_fighter_descriptor_snapshot  # noqa: E402


def get_active_fighters_missing_descriptors(conn):
    """Return list of fighter_ids for active fighters with no descriptor row."""
    return [r[0] for r in conn.execute(
        "SELECT f.fighter_id FROM fighters f "
        "LEFT JOIN fighter_descriptors fd ON f.fighter_id = fd.fighter_id "
        "WHERE f.is_active = 1 AND fd.fighter_id IS NULL "
        "ORDER BY f.fighter_id"
    ).fetchall()]


def get_retired_legends_missing_descriptors(conn):
    """Return list of fighter_ids for retired legends with no descriptor row."""
    return [r[0] for r in conn.execute(
        "SELECT f.fighter_id FROM fighters f "
        "LEFT JOIN fighter_descriptors fd ON f.fighter_id = fd.fighter_id "
        "WHERE f.is_retired = 1 AND fd.fighter_id IS NULL "
        "ORDER BY f.fighter_id"
    ).fetchall()]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        active_missing = get_active_fighters_missing_descriptors(conn)
        legends_missing = get_retired_legends_missing_descriptors(conn)

        total_before = conn.execute(
            "SELECT COUNT(*) FROM fighter_descriptors"
        ).fetchone()[0]
        total_fighters = conn.execute(
            "SELECT COUNT(*) FROM fighters"
        ).fetchone()[0]

        print(f"fighter_descriptors rows before: {total_before}")
        print(f"Total fighters: {total_fighters}")
        print(f"Active fighters missing descriptors: {len(active_missing)}")
        print(f"Retired legends missing descriptors: {len(legends_missing)}")
        print(f"Total to backfill: {len(active_missing) + len(legends_missing)}")

        if DRY_RUN:
            print("\n--dry-run: no changes made.")
            return

        if not active_missing and not legends_missing:
            print("\nNothing to backfill — all fighters already have descriptors.")
            return

        backfilled_active = 0
        backfilled_legends = 0
        skipped = 0

        # Backfill active fighters first (the larger group).
        print(f"\nBackfilling {len(active_missing)} active fighters...")
        for i, fighter_id in enumerate(active_missing, 1):
            try:
                update_fighter_descriptor_snapshot(conn, fighter_id)
                backfilled_active += 1
            except Exception as e:
                skipped += 1
                print(f"  WARN: fighter_id={fighter_id} skipped: {e}")
                conn.rollback()
                continue
            if i % 50 == 0:
                conn.commit()
                print(f"  ... {i}/{len(active_missing)}")
        conn.commit()

        # Then backfill retired legends.
        print(f"\nBackfilling {len(legends_missing)} retired legends...")
        for i, fighter_id in enumerate(legends_missing, 1):
            try:
                update_fighter_descriptor_snapshot(conn, fighter_id)
                backfilled_legends += 1
            except Exception as e:
                skipped += 1
                print(f"  WARN: fighter_id={fighter_id} skipped: {e}")
                conn.rollback()
                continue
            if i % 20 == 0:
                conn.commit()
                print(f"  ... {i}/{len(legends_missing)}")
        conn.commit()

        total_after = conn.execute(
            "SELECT COUNT(*) FROM fighter_descriptors"
        ).fetchone()[0]
        still_missing_active = conn.execute(
            "SELECT COUNT(*) FROM fighters f "
            "LEFT JOIN fighter_descriptors fd ON f.fighter_id = fd.fighter_id "
            "WHERE f.is_active = 1 AND fd.fighter_id IS NULL"
        ).fetchone()[0]
        still_missing_legends = conn.execute(
            "SELECT COUNT(*) FROM fighters f "
            "LEFT JOIN fighter_descriptors fd ON f.fighter_id = fd.fighter_id "
            "WHERE f.is_retired = 1 AND fd.fighter_id IS NULL"
        ).fetchone()[0]

        total_backfilled = backfilled_active + backfilled_legends
        print()
        print("=" * 60)
        print(f"Backfilled {total_backfilled} fighter snapshots "
              f"({backfilled_active} active + {backfilled_legends} legends)")
        if skipped:
            print(f"Skipped {skipped} (errors — see WARN lines above)")
        print(f"fighter_descriptors rows: {total_before} -> {total_after}")
        print(f"Still missing (active): {still_missing_active}")
        print(f"Still missing (legends): {still_missing_legends}")
        print(f"Total fighters: {total_fighters} | "
              f"Total descriptors: {total_after}")
        if still_missing_active == 0 and still_missing_legends == 0:
            print("OK: every fighter now has a descriptor snapshot.")
        else:
            print("WARN: some fighters are still missing descriptors.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
