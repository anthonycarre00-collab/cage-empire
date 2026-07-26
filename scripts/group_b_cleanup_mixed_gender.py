#!/usr/bin/env python3
"""CAGE EMPIRE — Phase 1.5 Group B B4-cleanup: defensive cleanup of
pre-existing mixed-gender fights.

This script is a defensive cleanup applied as part of B4 (gender
separation). The PHASE_1_5_PLAN.md incorrectly claimed "0 mixed-gender
fights in history ✓" — the actual data has 3167 unique mixed-gender
fights (6334 fight_history rows). The brief's verification step
explicitly requires "0 mixed-gender fights in history", so this
cleanup is required to make verification pass.

Root cause (D2):
  - 1211 active MALE fighters are in FEMALE WCs (WC9 Featherweight,
    WC10 Bantamweight, WC11 Flyweight). This is a seed bug from
    seed_world_phase3_from_profiles.py — the `_lookup_weight_class_id`
    function does NOT filter by gender, so it picks the first WC
    matching the name. At seed time, the male Featherweight/
    Bantamweight/Flyweight WCs (WC6/7/8) did not exist (they're the
    "empty" WCs that B1 just populated). So all "Featherweight"
    lookups returned WC9 (the only Featherweight WC at seed time),
    landing male fighters in the female WC.
  - These wrong-gender male fighters in female WCs were then booked
    against correctly-assigned female opponents, producing 3167
    mixed-gender fights (6334 fight_history rows counting both sides).

Fix:
  1. Reassign 1211 wrong-gender fighters from female WCs (9/10/11)
     to the correct-gender equivalent WC (6/7/8) — by WC name lookup.
     Also reassign the fighters' rankings rows + titles (if any) to
     the new WC.
  2. Delete the 3167 mixed-gender fights. The CASCADE on
     fights.fight_id auto-deletes:
       - fight_history rows (FK fight_id ON DELETE CASCADE)
       - fight_participants rows (FK fight_id ON DELETE CASCADE)
       - event_cards rows (FK fight_id ON DELETE CASCADE)
  3. Recompute affected fighters' records (wins, losses, draws, win_
     streak, loss_streak) from their remaining fight_history rows.
  4. Recompute affected rankings rows (wins, losses, draws,
     fights_count, last_fight_date) to match.
  5. Re-run B3 logic to zero out any new ghost-record free agents
     (fighters whose records dropped to 0 because their only fights
     were mixed-gender and got deleted).

Idempotency:
  - The reassignment is guarded — only touches fighters whose gender
    doesn't match their WC's gender. After reassignment, no rows
    match, so re-running is a no-op.
  - The mixed-gender fight deletion is guarded — only deletes fights
    where the two fighters have different genders. After deletion,
    no rows match, so re-running is a no-op.
  - The record recompute is idempotent — it sets the records to match
    the actual fight_history counts, which are stable once the
    cleanup is applied.

CONVENTIONS compliance:
  §1   — No schema change (data-only fix).
  §5   — No new tables.
  §6   — Smoke test: run forensic_db_check.py after.
  §13  — Design Law: strengthens Conflict (no factually impossible
         mixed-gender fights in history) + Legacy (records reflect
         reality).
  §16.9 — Backup the DB before running.

Usage:
    python3 scripts/group_b_cleanup_mixed_gender.py            # apply
    python3 scripts/group_b_cleanup_mixed_gender.py --check    # report only
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


# ----------------------------------------------------------------
# Step 1: Reassign wrong-gender fighters to correct WC.
# ----------------------------------------------------------------

# Map of female WC ID → male WC ID (by name lookup).
# Female Featherweight (WC9) → Male Featherweight (WC6)
# Female Bantamweight (WC10) → Male Bantamweight (WC7)
# Female Flyweight (WC11) → Male Flyweight (WC8)
FEMALE_TO_MALE_WC = {9: 6, 10: 7, 11: 8}
# Reverse map (in case we ever need to reassign female fighters in
# male WCs — currently 0 such cases, but defensive).
MALE_TO_FEMALE_WC = {v: k for k, v in FEMALE_TO_MALE_WC.items()}


def find_wrong_gender_fighters(conn):
    """Find active fighters whose gender doesn't match their WC's gender.

    Returns a list of (fighter_id, fighter_gender, current_wc_id,
    wc_gender, target_wc_id) tuples.
    """
    rows = conn.execute(
        """
        SELECT f.fighter_id, f.gender, f.weight_class_id, wc.gender
        FROM fighters f
        JOIN weight_classes wc ON f.weight_class_id = wc.weight_class_id
        WHERE f.is_active = 1
          AND f.gender != wc.gender
        """,
    ).fetchall()
    out = []
    for fid, fgender, wc_id, wc_gender in rows:
        if fgender == 'male' and wc_gender == 'female' and wc_id in FEMALE_TO_MALE_WC:
            target_wc = FEMALE_TO_MALE_WC[wc_id]
        elif fgender == 'female' and wc_gender == 'male' and wc_id in MALE_TO_FEMALE_WC:
            target_wc = MALE_TO_FEMALE_WC[wc_id]
        else:
            # No clear target — skip (defensive — would need manual
            # handling). Log for visibility.
            print(f"  WARNING: fighter F{fid} gender={fgender} in "
                  f"WC{wc_id} (gender={wc_gender}) — no clear target "
                  f"WC, skipping.")
            continue
        out.append((fid, fgender, wc_id, wc_gender, target_wc))
    return out


def fix_wrong_gender_fighters(conn, check_only=False):
    """Reassign wrong-gender fighters to their correct-gender WC.

    Updates: fighters.weight_class_id, rankings.weight_class_id,
    titles.current_champion_fighter_id stays (no champion changes —
    we just relabel the WC). If the fighter is a current champion of
    a title in the wrong WC, the title itself moves to the new WC
    (since titles are tied to WC).

    Returns the count of fighters reassigned (or would-be reassigned).
    """
    wrong = find_wrong_gender_fighters(conn)
    print(f"[B4-cleanup] Wrong-gender active fighters found: {len(wrong)}")
    if not wrong:
        return 0
    if check_only:
        # Sample 5 for visibility
        for fid, fgender, wc_id, wc_gender, target_wc in wrong[:5]:
            print(f"  sample F{fid} ({fgender}) in WC{wc_id} ({wc_gender}) "
                  f"→ target WC{target_wc}")
        return len(wrong)

    n_reassigned = 0
    for fid, fgender, wc_id, wc_gender, target_wc in wrong:
        # Update the fighter's WC.
        conn.execute(
            "UPDATE fighters SET weight_class_id=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE fighter_id=?",
            (target_wc, fid),
        )
        # Update the fighter's rankings rows — move them to the new WC.
        # Keep the rating, wins, losses, draws, fights_count, last_fight_date.
        conn.execute(
            "UPDATE rankings SET weight_class_id=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE fighter_id=? AND weight_class_id=?",
            (target_wc, fid, wc_id),
        )
        # If the fighter is a current champion of a title in the old
        # WC, that title is now in the wrong WC. Move the title to
        # the new WC. But the title is also tied to a promotion — and
        # there might already be a title for the (promotion, new_wc)
        # pair. In that case, vacate the old title (set champion=NULL,
        # is_vacant=1) and leave the existing new_wc title alone.
        # This is defensive — wrong-gender champions are rare (we'll
        # log if it happens).
        champ_titles = conn.execute(
            "SELECT title_id, promotion_id FROM titles "
            "WHERE current_champion_fighter_id=? AND weight_class_id=?",
            (fid, wc_id),
        ).fetchall()
        for title_id, promo_id in champ_titles:
            existing_in_new_wc = conn.execute(
                "SELECT title_id FROM titles "
                "WHERE promotion_id=? AND weight_class_id=?",
                (promo_id, target_wc),
            ).fetchone()
            if existing_in_new_wc:
                # Vacate the old title — don't move it (would violate
                # the UNIQUE(promotion_id, weight_class_id) constraint.
                conn.execute(
                    "UPDATE titles SET current_champion_fighter_id=NULL, "
                    "champion_since_date=NULL, is_vacant=1, "
                    "updated_at=CURRENT_TIMESTAMP WHERE title_id=?",
                    (title_id,),
                )
                print(f"  NOTE: vacated title T{title_id} (was held by "
                      f"F{fid} in WC{wc_id}) — title in WC{target_wc} "
                      f"already exists for promo P{promo_id}.")
            else:
                # Move the title to the new WC.
                conn.execute(
                    "UPDATE titles SET weight_class_id=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE title_id=?",
                    (target_wc, title_id),
                )
                print(f"  NOTE: moved title T{title_id} from WC{wc_id} "
                      f"to WC{target_wc} (champion F{fid} reassigned).")
        n_reassigned += 1
    print(f"[B4-cleanup] Reassigned {n_reassigned} wrong-gender fighters "
          f"to correct-gender WCs.")
    return n_reassigned


# ----------------------------------------------------------------
# Step 2: Delete mixed-gender fights.
# ----------------------------------------------------------------

def find_mixed_gender_fights(conn):
    """Return the set of fight_ids where the two participants have
    different genders."""
    rows = conn.execute(
        """
        SELECT DISTINCT fh.fight_id
        FROM fight_history fh
        JOIN fighters f1 ON fh.fighter_id = f1.fighter_id
        JOIN fighters f2 ON fh.opponent_id = f2.fighter_id
        WHERE f1.gender != f2.gender
        """,
    ).fetchall()
    return [r[0] for r in rows]


def delete_mixed_gender_fights(conn, check_only=False):
    """Delete mixed-gender fights + cascade (fight_history, fight_
    participants, event_cards auto-deleted via FK CASCADE).

    Returns the count of fights deleted (or would-be deleted).
    """
    fight_ids = find_mixed_gender_fights(conn)
    print(f"[B4-cleanup] Mixed-gender fights found: {len(fight_ids)}")
    if not fight_ids:
        return 0
    if check_only:
        # Sample 5 for visibility
        for fid in fight_ids[:5]:
            row = conn.execute(
                """
                SELECT fh.fight_id, f1.first_name, f1.last_name, f1.gender,
                       f2.first_name, f2.last_name, f2.gender, fh.event_date
                FROM fight_history fh
                JOIN fighters f1 ON fh.fighter_id = f1.fighter_id
                JOIN fighters f2 ON fh.opponent_id = f2.fighter_id
                WHERE fh.fight_id=? LIMIT 1
                """,
                (fid,),
            ).fetchone()
            print(f"  sample fight F{row[0]}: {row[1]} {row[2]} ({row[3]}) "
                  f"vs {row[4]} {row[5]} ({row[6]}) on {row[7]}")
        return len(fight_ids)

    # Delete in batches to avoid SQL parameter limits (~999 in older
    # SQLite; modern SQLite handles 32766, but batched is safer).
    BATCH_SIZE = 500
    n_deleted = 0
    for i in range(0, len(fight_ids), BATCH_SIZE):
        batch = fight_ids[i:i + BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        # Delete the fights — FK CASCADE auto-deletes fight_history,
        # fight_participants, event_cards.
        cur = conn.execute(
            f"DELETE FROM fights WHERE fight_id IN ({placeholders})",
            batch,
        )
        n_deleted += cur.rowcount
        conn.commit()
    print(f"[B4-cleanup] Deleted {n_deleted} mixed-gender fights "
          f"(+ cascade fight_history + fight_participants + event_cards).")
    return n_deleted


# ----------------------------------------------------------------
# Step 3: Recompute affected fighters' records from remaining
# fight_history.
# ----------------------------------------------------------------

def recompute_fighter_records(conn, check_only=False):
    """Recompute record_wins/losses/draws + win_streak/loss_streak for
    all active fighters from their remaining fight_history rows.

    Also updates rankings rows (wins/losses/draws/fights_count/
    last_fight_date) to match.

    Returns count of fighters whose records changed.
    """
    # Get all active fighters with at least 1 remaining fight_history
    # row OR who HAD a record before (so we can detect changes).
    rows = conn.execute(
        """
        SELECT f.fighter_id,
               fc.record_wins, fc.record_losses, fc.record_draws,
               fc.win_streak, fc.loss_streak
        FROM fighters f
        LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        WHERE f.is_active = 1
        """,
    ).fetchall()
    print(f"[B4-cleanup] Active fighters to evaluate: {len(rows)}")
    if check_only:
        return len(rows)

    n_changed = 0
    for fid, old_w, old_l, old_d, old_ws, old_ls in rows:
        # Compute new records from fight_history.
        # fight_history.outcome is 'win', 'loss', or 'draw'.
        win_count = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fighter_id=? AND outcome='win'",
            (fid,),
        ).fetchone()[0]
        loss_count = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fighter_id=? AND outcome='loss'",
            (fid,),
        ).fetchone()[0]
        draw_count = conn.execute(
            "SELECT COUNT(*) FROM fight_history WHERE fighter_id=? AND outcome='draw'",
            (fid,),
        ).fetchone()[0]

        # Compute current streak by walking fight_history in reverse
        # chronological order. The streak ends at the first non-matching
        # outcome.
        history = conn.execute(
            "SELECT outcome FROM fight_history WHERE fighter_id=? "
            "ORDER BY event_date DESC, fight_history_id DESC",
            (fid,),
        ).fetchall()
        new_ws = 0
        new_ls = 0
        if history:
            last_outcome = history[0][0]
            if last_outcome == 'win':
                for outcome, in history:
                    if outcome == 'win':
                        new_ws += 1
                    else:
                        break
            elif last_outcome == 'loss':
                for outcome, in history:
                    if outcome == 'loss':
                        new_ls += 1
                    else:
                        break
            # draws don't start a streak — streak stays 0

        # Check if anything changed.
        old_w = old_w or 0
        old_l = old_l or 0
        old_d = old_d or 0
        old_ws = old_ws or 0
        old_ls = old_ls or 0
        if (win_count != old_w or loss_count != old_l or
                draw_count != old_d or new_ws != old_ws or
                new_ls != old_ls):
            conn.execute(
                "UPDATE fighter_career SET record_wins=?, record_losses=?, "
                "record_draws=?, win_streak=?, loss_streak=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
                (win_count, loss_count, draw_count, new_ws, new_ls, fid),
            )
            n_changed += 1

        # Update rankings rows for this fighter (across all
        # promotion_id + weight_class_id combinations — there may be
        # multiple rankings rows if the fighter fought in multiple
        # promotions over their career).
        conn.execute(
            "UPDATE rankings SET wins=?, losses=?, draws=?, "
            "fights_count=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE fighter_id=?",
            (win_count, loss_count, draw_count,
             win_count + loss_count + draw_count, fid),
        )
        # Update last_fight_date from the most recent fight_history row.
        last_fight = conn.execute(
            "SELECT MAX(event_date) FROM fight_history WHERE fighter_id=?",
            (fid,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE rankings SET last_fight_date=? WHERE fighter_id=?",
            (last_fight, fid),
        )

    conn.commit()
    print(f"[B4-cleanup] Recomputed records for {n_changed} fighters "
          f"(of {len(rows)} active).")
    return n_changed


# ----------------------------------------------------------------
# Step 4: Re-run B3 logic to zero out any new ghost-record free agents.
# (Imports the function from group_b_reconcile.py to avoid duplication.)
# ----------------------------------------------------------------

def zero_new_ghost_records(conn, check_only=False):
    """Zero out any remaining ghost-record free agents.

    After the mixed-gender fight deletion, some free agents may have
    records > 0 but no fight_history (their only fights were mixed-
    gender and got deleted). Zero them out per B3 logic.
    """
    sys.path.insert(0, str(PROJECT_DIR / "scripts"))
    # Import the B3 function from group_b_reconcile.
    try:
        from group_b_reconcile import fix_b3_zero_ghost_records
    except ImportError:
        # Fallback — inline the logic.
        return _zero_ghost_records_inline(conn, check_only)
    return fix_b3_zero_ghost_records(conn, check_only=check_only)


def _zero_ghost_records_inline(conn, check_only=False):
    """Inline fallback for the B3 ghost-record zeroing logic."""
    ghost_ids = [r[0] for r in conn.execute(
        """
        SELECT f.fighter_id FROM fighters f
        JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
        WHERE f.is_active = 1
          AND f.current_promotion_id IS NULL
          AND (fc.record_wins > 0 OR fc.record_losses > 0
               OR fc.record_draws > 0)
          AND NOT EXISTS (
              SELECT 1 FROM fight_history fh
              WHERE fh.fighter_id = f.fighter_id
          )
        """,
    ).fetchall()]
    print(f"[B4-cleanup] Ghost-record free agents found: {len(ghost_ids)}")
    if not ghost_ids or check_only:
        return len(ghost_ids)
    cur = conn.execute(
        """
        UPDATE fighter_career
        SET record_wins=0, record_losses=0, record_draws=0,
            win_streak=0, loss_streak=0, updated_at=CURRENT_TIMESTAMP
        WHERE fighter_id IN (
            SELECT f.fighter_id FROM fighters f
            WHERE f.is_active = 1 AND f.current_promotion_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM fight_history fh
                  WHERE fh.fighter_id = f.fighter_id
              )
        )
        AND (record_wins > 0 OR record_losses > 0 OR record_draws > 0
             OR win_streak > 0 OR loss_streak > 0)
        """,
    )
    conn.commit()
    print(f"[B4-cleanup] Zeroed records for {cur.rowcount} ghost-record "
          f"free agents.")
    return cur.rowcount


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1.5 Group B B4-cleanup: mixed-gender fight cleanup.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report-only mode — no DB writes.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("CAGE EMPIRE — Phase 1.5 Group B B4-cleanup: Mixed-Gender Fights")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Mode: {'CHECK ONLY' if args.check else 'APPLY'}")
    print()
    print("NOTE: per CONVENTIONS §16.9, back up the DB before running.")
    print("  cp data/cage_empire.db data/cage_empire.db.backup-<name>")
    print()

    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    print("--- Step 1: Reassign wrong-gender fighters to correct WC ---")
    fix_wrong_gender_fighters(conn, check_only=args.check)
    print()

    print("--- Step 2: Delete mixed-gender fights (+ cascade) ---")
    delete_mixed_gender_fights(conn, check_only=args.check)
    print()

    print("--- Step 3: Recompute affected fighters' records ---")
    recompute_fighter_records(conn, check_only=args.check)
    print()

    print("--- Step 4: Zero out new ghost-record free agents ---")
    zero_new_ghost_records(conn, check_only=args.check)
    print()

    if not args.check:
        conn.commit()
        print("Committed.")
    else:
        print("Check-only mode — no commit.")

    # Verify.
    print()
    print("=== Verification ===")
    mixed = conn.execute(
        """
        SELECT COUNT(*) FROM fight_history fh
        JOIN fighters f1 ON fh.fighter_id = f1.fighter_id
        JOIN fighters f2 ON fh.opponent_id = f2.fighter_id
        WHERE f1.gender != f2.gender
        """,
    ).fetchone()[0]
    print(f"Mixed-gender fight_history rows remaining: {mixed}")

    wrong_gender = conn.execute(
        """
        SELECT COUNT(*) FROM fighters f
        JOIN weight_classes wc ON f.weight_class_id = wc.weight_class_id
        WHERE f.is_active = 1 AND f.gender != wc.gender
        """,
    ).fetchone()[0]
    print(f"Active wrong-gender fighters remaining: {wrong_gender}")

    ghosts = conn.execute(
        """
        SELECT COUNT(*) FROM fighters f
        JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
        WHERE f.is_active = 1 AND f.current_promotion_id IS NULL
        AND (fc.record_wins > 0 OR fc.record_losses > 0)
        AND NOT EXISTS (SELECT 1 FROM fight_history fh WHERE fh.fighter_id = f.fighter_id)
        """,
    ).fetchone()[0]
    print(f"Ghost-record free agents remaining: {ghosts}")

    conn.close()


if __name__ == "__main__":
    main()
