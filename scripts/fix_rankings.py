#!/usr/bin/env python3
"""P4.2 — Audit duplicate rankings + document the tiebreaker fix.

Per docs/COMPREHENSIVE_FIX_PLAN.md Group F #23:
  The `rankings` table has no `rank` column — rank is derived from
  `rating` (ELO). Multiple fighters with the same ELO rating get the
  same rank, which surfaces as "two #5s in the same division" on the
  Rankings screen.

The fix lives in `app_web.py::get_rankings_data` — the SQL ORDER BY
now breaks rating ties via fighter_id ASC, and the Python rank
assignment is sequential (1, 2, 3, ...) so no two fighters share a
rank. This script does NOT modify the rankings table (the rank is
derived at read time — adding a `rank` column would just create a
second source of truth that could drift).

What this script does:
  1. Audits the rankings table for rating collisions (groups of
     fighters in the same WC+promo sharing the same ELO rating).
  2. Reports how many collisions exist + how many top-15 slots would
     have been affected under the old (no-tiebreaker) display logic.
  3. Verifies the new tiebreaker (rating DESC, fighter_id ASC) would
     resolve every collision to a unique rank.

Usage:
  python scripts/fix_rankings.py            # audit + report
  python scripts/fix_rankings.py path/to.db
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_DIR / "data" / "cage_empire.db"


def audit_rankings(db_path: Path | str = DEFAULT_DB) -> dict:
    """Audit the rankings table for rating collisions.

    Returns:
      {
        total_rows,
        collision_groups,        # groups of (promo, wc, rating) with >1 fighter
        collision_fighters,      # total fighters involved in collisions
        top15_collisions,        # groups where the collision is within top-15
        top15_collision_fighters,
        tiebreaker_resolves_all, # bool — does fighter_id ASC break every tie?
      }
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        total_rows = conn.execute(
            "SELECT COUNT(*) FROM rankings"
        ).fetchone()[0]

        # All rating-collision groups.
        collision_rows = conn.execute(
            """
            SELECT promotion_id, weight_class_id, rating, COUNT(*) AS cnt
            FROM rankings
            GROUP BY promotion_id, weight_class_id, rating
            HAVING cnt > 1
            ORDER BY promotion_id, weight_class_id, rating DESC
            """
        ).fetchall()
        collision_groups = len(collision_rows)
        collision_fighters = sum(r[3] for r in collision_rows)

        # For each collision group, check whether ANY of the tied
        # fighters is in the top-15 (by rating DESC) for that WC+promo.
        # If so, the collision would have surfaced on the Rankings
        # screen under the old display logic.
        top15_collisions = 0
        top15_collision_fighters = 0
        for promo_id, wc_id, rating, cnt in collision_rows:
            # Find the rank-15 cutoff rating for this WC+promo.
            # If the colliding rating is >= the 15th-highest rating,
            # at least one tied fighter is in the top 15.
            row = conn.execute(
                """
                SELECT rating FROM rankings
                WHERE promotion_id=? AND weight_class_id=?
                ORDER BY rating DESC, fighter_id ASC
                LIMIT 1 OFFSET 14
                """,
                (promo_id, wc_id),
            ).fetchone()
            cutoff_rating = row[0] if row else None
            if cutoff_rating is None:
                # Fewer than 15 fighters — everyone is in the "top 15".
                top15_collisions += 1
                top15_collision_fighters += cnt
            elif rating >= cutoff_rating:
                top15_collisions += 1
                top15_collision_fighters += cnt

        # Tiebreaker resolution check: for each collision group,
        # verify the tied fighters have distinct fighter_ids (which
        # they must, since fighter_id is part of the rankings primary
        # key in practice — but defensive).
        tiebreaker_resolves_all = True
        for promo_id, wc_id, rating, cnt in collision_rows:
            distinct_ids = conn.execute(
                """
                SELECT COUNT(DISTINCT fighter_id) FROM rankings
                WHERE promotion_id=? AND weight_class_id=? AND rating=?
                """,
                (promo_id, wc_id, rating),
            ).fetchone()[0]
            if distinct_ids != cnt:
                tiebreaker_resolves_all = False
                break

        return {
            "total_rows": total_rows,
            "collision_groups": collision_groups,
            "collision_fighters": collision_fighters,
            "top15_collisions": top15_collisions,
            "top15_collision_fighters": top15_collision_fighters,
            "tiebreaker_resolves_all": tiebreaker_resolves_all,
            "collision_samples": [
                {"promo_id": r[0], "weight_class_id": r[1],
                 "rating": r[2], "count": r[3]}
                for r in collision_rows[:10]
            ],
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    db_path = Path(argv[0]) if argv else DEFAULT_DB

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"[fix_rankings] DB: {db_path}")
    print("[fix_rankings] NOTE: this script audits only — the actual")
    print("                  tiebreaker fix lives in app_web.py:")
    print("                  ORDER BY rating DESC, fighter_id ASC")
    print("                  (sequential rank 1..N — no two fighters")
    print("                  share a rank).")

    result = audit_rankings(db_path)
    print()
    print(f"  Total rankings rows:           {result['total_rows']}")
    print(f"  Rating-collision groups:       {result['collision_groups']}")
    print(f"  Fighters in collisions:        {result['collision_fighters']}")
    print(f"  Top-15 collision groups:       {result['top15_collisions']}")
    print(f"  Top-15 collision fighters:     {result['top15_collision_fighters']}")
    print(f"  Tiebreaker resolves all:       {result['tiebreaker_resolves_all']}")
    if result["collision_samples"]:
        print("  Sample collision groups (promo, wc, rating, count):")
        for s in result["collision_samples"]:
            print(f"    promo={s['promo_id']} wc={s['weight_class_id']} "
                  f"rating={s['rating']} count={s['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
