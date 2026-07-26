#!/usr/bin/env python3
"""CAGE EMPIRE — Phase 1.5 Group B: data-only reconciliation (Fixes B2 + B3).

Two idempotent data fixes against the existing world DB. NO schema
changes. NO fighter generation. Safe to re-run.

Fix B3 [HIGH]: Zero out ghost-record free agents.
  - Active fighters with current_promotion_id IS NULL, BUT with
    fighter_career.record_wins > 0 OR record_losses > 0, AND with
    ZERO rows in fight_history. These are "ghost records" — fictional
    W/L records that don't correspond to any actual fights.
  - Fix: set record_wins=0, record_losses=0, record_draws=0,
    win_streak=0, loss_streak=0. They're unsigned prospects with no
    pro fights — makes sense.

Fix B2 [LOW]: Re-roll 38 generic "Balanced"-archetype fighters.
  - Balanced fighters (style_archetype_id=1) whose 25-attribute block
    has population stdev < 2 — everything clustered 46-55. They're
    functionally generic and lack style identity (CONVENTIONS §13 —
    Discovery pillar).
  - Fix: re-roll attributes using fighter_gen.generate_attribute_block
    with the Balanced archetype bias, but with a wider random range
    so the new block has more variance. Existing 4 attrs (punch_power,
    cardio, fight_iq, chin) are PRESERVED per fighter_gen's contract
    (callers that need to preserve must override those keys).

CONVENTIONS compliance:
  §1   — No schema change (PATCH-level data fix only).
  §5   — One table-group per task. No new tables here.
  §6   — Smoke test: run forensic_db_check.py after writing.
  §13  — Design Law: Fix B2 strengthens Discovery (style identity);
         Fix B3 strengthens Legacy (records reflect reality).
  §16.9 — Backup the DB before running. (Operator responsibility —
         the brief tells the supervisor to do this; this script
         prints a reminder.)

Usage:
    python3 scripts/group_b_reconcile.py            # apply both fixes
    python3 scripts/group_b_reconcile.py --check    # report only, no writes
    python3 scripts/group_b_reconcile.py --only B3  # apply only B3

Idempotency:
    Both fixes are guarded — re-running is a no-op once the data is
    in the desired state. B3 only touches rows where the ghost-record
    pattern still matches; B2 only touches Balanced fighters whose
    attribute stdev is still < 2.
"""
import sqlite3
import statistics
import sys
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
SRC_DIR = PROJECT_DIR / "src"

sys.path.insert(0, str(SRC_DIR))
import fighter_gen  # noqa: E402  (for B2 re-roll)


# ----------------------------------------------------------------
# Fix B3: Zero out ghost-record free agents.
# ----------------------------------------------------------------

GHOST_RECORD_SQL = """
    SELECT f.fighter_id
    FROM fighters f
    JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
    WHERE f.is_active = 1
      AND f.current_promotion_id IS NULL
      AND (fc.record_wins > 0 OR fc.record_losses > 0 OR fc.record_draws > 0)
      AND NOT EXISTS (
          SELECT 1 FROM fight_history fh WHERE fh.fighter_id = f.fighter_id
      )
"""


def find_ghost_records(conn):
    """Return the list of fighter_ids matching the ghost-record pattern."""
    return [r[0] for r in conn.execute(GHOST_RECORD_SQL).fetchall()]


def fix_b3_zero_ghost_records(conn, check_only=False):
    """Zero out the career records of ghost-record free agents.

    Returns the count of fighters updated (or would-be updated if
    check_only=True).
    """
    ghost_ids = find_ghost_records(conn)
    print(f"[B3] Ghost-record free agents found: {len(ghost_ids)}")
    if not ghost_ids:
        return 0
    if check_only:
        # Sample 5 for visibility
        for fid in ghost_ids[:5]:
            row = conn.execute(
                "SELECT f.first_name, f.last_name, fc.record_wins, "
                "fc.record_losses, fc.record_draws, fc.win_streak, "
                "fc.loss_streak FROM fighters f JOIN fighter_career fc "
                "ON f.fighter_id=fc.fighter_id WHERE f.fighter_id=?",
                (fid,),
            ).fetchone()
            print(f"  sample F{fid}: {row[0]} {row[1]} record="
                  f"{row[2]}-{row[3]}-{row[4]} Wstreak={row[5]} Lstreak={row[6]}")
        return len(ghost_ids)

    # Apply the fix — zero out the records.
    # Use a single UPDATE with a subquery for efficiency (one round-trip).
    cur = conn.execute(
        """
        UPDATE fighter_career
        SET record_wins = 0,
            record_losses = 0,
            record_draws = 0,
            win_streak = 0,
            loss_streak = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE fighter_id IN (
            SELECT f.fighter_id
            FROM fighters f
            WHERE f.is_active = 1
              AND f.current_promotion_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM fight_history fh
                  WHERE fh.fighter_id = f.fighter_id
              )
        )
        AND (record_wins > 0 OR record_losses > 0 OR record_draws > 0
             OR win_streak > 0 OR loss_streak > 0)
        """,
    )
    n_updated = cur.rowcount
    # Also zero out the matching rankings rows (they carry wins/losses/
    # draws/fights_count that should be 0 for these ghost-record fighters).
    # Only touch rankings rows for the ghost-record fighters — and only
    # those with non-zero counts.
    cur2 = conn.execute(
        """
        UPDATE rankings
        SET wins = 0,
            losses = 0,
            draws = 0,
            fights_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE fighter_id IN (
            SELECT f.fighter_id
            FROM fighters f
            WHERE f.is_active = 1
              AND f.current_promotion_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM fight_history fh
                  WHERE fh.fighter_id = f.fighter_id
              )
        )
        AND (wins > 0 OR losses > 0 OR draws > 0 OR fights_count > 0)
        """,
    )
    n_rankings_updated = cur2.rowcount
    print(f"[B3] Zeroed fighter_career records for {n_updated} ghost-record "
          f"free agents.")
    print(f"[B3] Zeroed rankings rows for {n_rankings_updated} "
          f"ghost-record free agents.")
    return n_updated


# ----------------------------------------------------------------
# Fix B2: Re-roll 38 generic "Balanced"-archetype fighters.
# ----------------------------------------------------------------

# Attribute column order — must match fighter_attributes table.
ATTR_COLS = fighter_gen.ATTRIBUTE_NAMES  # 25 columns


def find_generic_balanced(conn, stdev_threshold=2.0):
    """Find Balanced-archetype fighters whose 25-attr block has
    population stdev < threshold. Returns list of (fighter_id, vals)."""
    col_select = ", ".join(f"fa.{c}" for c in ATTR_COLS)
    sql = (
        f"SELECT fa.fighter_id, {col_select} "
        f"FROM fighter_attributes fa "
        f"JOIN fighters f ON fa.fighter_id = f.fighter_id "
        f"WHERE f.fight_style_archetype_id = 1"  # Balanced
    )
    out = []
    for row in conn.execute(sql).fetchall():
        fid = row[0]
        vals = row[1:]
        if statistics.pstdev(vals) < stdev_threshold:
            out.append((fid, vals))
    return out


def fix_b2_reroll_generic_balanced(conn, check_only=False, seed=20260726):
    """Re-roll attributes for the 38 generic Balanced-archetype fighters.

    Uses fighter_gen.generate_attribute_block(archetype_id=1, conn=conn)
    which applies the Balanced bias (punch_power +3, cardio +3, fight_iq
    +3) plus the standard ±8 noise floor. To add MORE variance than the
    default ±8 noise, we layer an additional ±10 spread on top.

    The existing 4 attrs (punch_power, cardio, fight_iq, chin) are
    PRESERVED per fighter_gen's documented contract — these are the
    "existing attributes" the v2.0.0 migration preserved across the
    schema expansion, and overwriting them would violate that invariant.
    (Real fix: the generic-ness is in the 21 NEW attrs, which are all
    clustered 46-55; the 4 existing attrs may legitimately be 46-55 if
    the original bio-driven assignment produced that result. We re-roll
    ONLY the 21 new attrs.)

    Idempotent: only touches Balanced fighters whose stdev is still < 2.
    After re-rolling, stdev will be > 2 (the wider variance guarantees
    it), so re-running is a no-op.

    Returns count of fighters re-rolled (or would-be re-rolled).
    """
    generic = find_generic_balanced(conn, stdev_threshold=2.0)
    print(f"[B2] Generic Balanced-archetype fighters (stdev<2): "
          f"{len(generic)}")
    if not generic:
        return 0
    if check_only:
        for fid, vals in generic[:5]:
            print(f"  sample F{fid}: first 5 attrs = {vals[:5]}, "
                  f"stdev={statistics.pstdev(vals):.2f}")
        return len(generic)

    rng = random.Random(seed)  # reproducible
    # Save + restore random's state so we don't perturb the global RNG
    # for any downstream code that runs after this script.
    saved_state = random.getstate()
    random.setstate(rng.getstate())
    try:
        n_updated = 0
        for fid, old_vals in generic:
            # Generate a new attribute block with Balanced bias.
            new_block = fighter_gen.generate_attribute_block(
                archetype_id=1, conn=conn,
            )
            # Layer ADDITIONAL variance on top of the ±8 noise — the
            # brief explicitly says "Add more variance (use a wider
            # random range)". Add ±10 extra noise to the 21 new attrs
            # (NOT the 4 existing attrs — preserved per contract).
            for col in fighter_gen.NEW_ATTRIBUTE_NAMES:
                extra = random.randint(-10, 10)
                new_val = fighter_gen._clamp(new_block[col] + extra, 0, 100)
                new_block[col] = new_val

            # PRESERVE the 4 existing attrs (punch_power, cardio,
            # fight_iq, chin) — set them back to the old values.
            for i, col in enumerate(fighter_gen.EXISTING_ATTRIBUTE_NAMES):
                new_block[col] = old_vals[i]

            # Sanity check: the new block should now have stdev > 2
            new_stdev = statistics.pstdev(list(new_block.values()))
            if new_stdev < 2.0:
                # Defensive — shouldn't happen with ±10 extra noise,
                # but if it does, force more variance by perturbing
                # the top 5 attrs by +5/-5.
                cols_sorted = sorted(new_block.keys())
                for j, col in enumerate(cols_sorted[:5]):
                    new_block[col] = fighter_gen._clamp(
                        new_block[col] + 5, 0, 100)
                for j, col in enumerate(cols_sorted[-5:]):
                    new_block[col] = fighter_gen._clamp(
                        new_block[col] - 5, 0, 100)

            # Build UPDATE statement for the 25 attr columns.
            set_clause = ", ".join(f"{c} = ?" for c in ATTR_COLS)
            set_clause += ", updated_at = CURRENT_TIMESTAMP"
            params = [new_block[c] for c in ATTR_COLS] + [fid]
            conn.execute(
                f"UPDATE fighter_attributes SET {set_clause} "
                f"WHERE fighter_id = ?",
                params,
            )
            n_updated += 1
        print(f"[B2] Re-rolled attributes for {n_updated} generic "
              f"Balanced-archetype fighters.")
    finally:
        # Restore the global random state.
        random.setstate(saved_state)

    return n_updated


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Phase 1.5 Group B reconciliation (Fixes B2 + B3).",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report-only mode — no DB writes.",
    )
    parser.add_argument(
        "--only", choices=["B2", "B3"], default=None,
        help="Apply only the specified fix.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("CAGE EMPIRE — Phase 1.5 Group B Reconciliation (Fixes B2 + B3)")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Mode: {'CHECK ONLY' if args.check else 'APPLY'}")
    if args.only:
        print(f"Only: {args.only}")
    print()
    print("NOTE: per CONVENTIONS §16.9, back up the DB before running.")
    print("  cp data/cage_empire.db data/cage_empire.db.backup-<name>")
    print()

    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    if args.only in (None, "B3"):
        fix_b3_zero_ghost_records(conn, check_only=args.check)
        print()

    if args.only in (None, "B2"):
        fix_b2_reroll_generic_balanced(conn, check_only=args.check)
        print()

    if not args.check:
        conn.commit()
        print("Committed.")
    else:
        print("Check-only mode — no commit.")

    # Verify
    print()
    print("=== Verification ===")
    ghosts_after = find_ghost_records(conn)
    print(f"Ghost records remaining: {len(ghosts_after)}")
    generic_after = find_generic_balanced(conn, stdev_threshold=2.0)
    print(f"Generic Balanced fighters remaining (stdev<2): "
          f"{len(generic_after)}")

    conn.close()


if __name__ == "__main__":
    main()
