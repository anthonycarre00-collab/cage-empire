#!/usr/bin/env python3
"""P4.3 — Replace champions with bad attributes.

Per docs/COMPREHENSIVE_FIX_PLAN.md Group F #24:
  Champions were seeded randomly — some have power=36, iq=38 (below
  average) yet hold a title. This is unrealistic: a champion should
  be one of the strongest fighters in their division.

This script:
  1. For each non-vacant title (is_vacant=0), looks up the current
     champion's fighter_attributes and computes the average across
     all 26 attribute columns.
  2. If the champion's avg attribute < 45 (below average), finds the
     highest-rated fighter in the same WC+promo by ELO rating (from
     the rankings table) — excluding the current champion.
  3. Updates the titles row:
     - current_champion_fighter_id → new champion
     - champion_since_date → today's sim date
     - title_reigns_count += 1 (new reign)
     - title_defenses_count = 0 (reset for the new reign)
  4. Writes a news item announcing the title change (topic='title').

Idempotent: running twice is safe — the second run finds no champions
with avg < 45 (they've all been replaced).

Usage:
  python scripts/fix_champions.py            # default DB
  python scripts/fix_champions.py path/to.db
  python scripts/fix_champions.py --dry-run  # report only, no writes
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_DIR / "data" / "cage_empire.db"

# Avg-attribute threshold (per spec: "below 45 (below average)").
AVG_ATTR_THRESHOLD = 45.0

# The 26 attribute columns from fighter_attributes.
ATTR_COLS = [
    "punch_power", "cardio", "fight_iq", "chin", "punch_accuracy",
    "kick_power", "kick_accuracy", "head_movement", "footwork",
    "clinch_striking", "clinch_offense", "clinch_defense",
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling", "recovery_rate", "speed_explosiveness",
    "strength", "durability", "flexibility", "adaptability",
]


def _champion_avg_attr(conn, fighter_id):
    """Return the avg of all 26 attributes for a fighter, or None."""
    if not fighter_id:
        return None
    sum_expr = " + ".join(f"COALESCE({c}, 0)" for c in ATTR_COLS)
    row = conn.execute(
        f"SELECT ({sum_expr}) / {len(ATTR_COLS)}.0 "
        f"FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else None


def _highest_rated_fighter(conn, promo_id, wc_id, exclude_fighter_id):
    """Return (fighter_id, name, rating) for the highest-rated fighter
    in the given WC+promo (by rankings.rating DESC, fighter_id ASC as
    a tiebreaker). Excludes exclude_fighter_id. Returns None if no
    other fighter is ranked.
    """
    row = conn.execute(
        """
        SELECT r.fighter_id, r.rating,
               f.first_name || ' ' || f.last_name AS name
        FROM rankings r
        JOIN fighters f ON f.fighter_id = r.fighter_id
        WHERE r.promotion_id=? AND r.weight_class_id=?
          AND r.fighter_id != ?
        ORDER BY r.rating DESC, r.fighter_id ASC
        LIMIT 1
        """,
        (promo_id, wc_id, exclude_fighter_id or -1),
    ).fetchone()
    if not row:
        return None
    return {"fighter_id": row[0], "rating": row[1], "name": row[2]}


def _sim_date(conn):
    """Return the current sim date (YYYY-MM-DD) from the clock."""
    row = conn.execute(
        "SELECT current_date FROM simulation_clock LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _ensure_system_feed_source(conn):
    """Return the System Feed news_source_id, creating it if missing."""
    row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO news_sources (name, credibility, sensationalism, "
        "bias, regional_reach, reliability, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("System Feed", 70, 40, 50, 60, 80, 80),
    ).lastrowid


def _write_title_change_news(conn, promo_id, wc_id, old_champ_name,
                              new_champ_name, new_champ_id, sim_date,
                              promo_name, wc_name):
    """Write a topic='title' news item announcing the title change."""
    src_id = _ensure_system_feed_source(conn)
    headline = (
        f"{promo_name} {wc_name} title installed: {new_champ_name} "
        f"elevated to champion"
    )
    body = (
        f"Reviewing the {promo_name} {wc_name} ranks, the promotion "
        f"has installed {new_champ_name} as the recognized champion. "
        f"The previous titleholder, {old_champ_name}, has been "
        f"stripped of the belt — the brass opting to align the title "
        f"with the division's top contender rather than wait for the "
        f"old champion's form to return. {new_champ_name} carries the "
        f"belt into the next defense as the man to beat at {wc_name}."
    )
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "neutral", "title",
         new_champ_id, promo_id, sim_date),
    )


def fix_champions(db_path: Path | str = DEFAULT_DB,
                  *, dry_run: bool = False) -> dict:
    """Replace champions with bad attributes.

    Returns a summary dict:
      {titles_checked, replaced, skipped, replacements: [...]}
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        # All non-vacant titles + champion info.
        title_rows = conn.execute(
            """
            SELECT t.title_id, t.promotion_id, t.weight_class_id,
                   t.current_champion_fighter_id,
                   f.first_name || ' ' || f.last_name AS champ_name,
                   p.name AS promo_name,
                   wc.name AS wc_name
            FROM titles t
            JOIN fighters f ON f.fighter_id = t.current_champion_fighter_id
            JOIN promotions p ON p.promotion_id = t.promotion_id
            JOIN weight_classes wc ON wc.weight_class_id = t.weight_class_id
            WHERE t.is_vacant = 0
            """
        ).fetchall()

        replaced = []
        skipped = []
        for (title_id, promo_id, wc_id, champ_fid, champ_name,
             promo_name, wc_name) in title_rows:
            avg_attr = _champion_avg_attr(conn, champ_fid)
            if avg_attr is None:
                skipped.append({
                    "title_id": title_id, "reason": "no attr row",
                    "champ_name": champ_name, "promo_name": promo_name,
                    "wc_name": wc_name,
                })
                continue
            if avg_attr >= AVG_ATTR_THRESHOLD:
                skipped.append({
                    "title_id": title_id, "reason": "avg attr OK",
                    "champ_name": champ_name, "promo_name": promo_name,
                    "wc_name": wc_name, "avg_attr": round(avg_attr, 1),
                })
                continue
            # Find the highest-rated fighter (excluding current champ).
            best = _highest_rated_fighter(conn, promo_id, wc_id, champ_fid)
            if not best:
                skipped.append({
                    "title_id": title_id, "reason": "no alternative",
                    "champ_name": champ_name, "promo_name": promo_name,
                    "wc_name": wc_name, "avg_attr": round(avg_attr, 1),
                })
                continue
            replaced.append({
                "title_id": title_id, "promo_name": promo_name,
                "wc_name": wc_name,
                "old_champ": champ_name,
                "old_avg_attr": round(avg_attr, 1),
                "new_champ": best["name"],
                "new_rating": round(best["rating"], 1),
            })

            if dry_run:
                continue

            sim_date = _sim_date(conn)
            # Update the titles row.
            conn.execute(
                """
                UPDATE titles
                SET current_champion_fighter_id=?,
                    champion_since_date=?,
                    title_defenses_count=0,
                    title_reigns_count=title_reigns_count + 1,
                    updated_at=CURRENT_TIMESTAMP
                WHERE title_id=?
                """,
                (best["fighter_id"], sim_date, title_id),
            )
            # Write the news item.
            _write_title_change_news(
                conn, promo_id, wc_id, champ_name, best["name"],
                best["fighter_id"], sim_date, promo_name, wc_name,
            )

        if not dry_run:
            conn.commit()

        return {
            "titles_checked": len(title_rows),
            "replaced": len(replaced),
            "skipped": len(skipped),
            "replacements": replaced,
            "skipped_details": skipped,
            "dry_run": dry_run,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    db_path = Path(argv[0]) if argv else DEFAULT_DB

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"[fix_champions] DB: {db_path}")
    print(f"[fix_champions] Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"[fix_champions] Avg-attr threshold: {AVG_ATTR_THRESHOLD}")

    result = fix_champions(db_path, dry_run=dry_run)
    print(
        f"[fix_champions] Checked {result['titles_checked']} non-vacant "
        f"titles. Replaced {result['replaced']}, skipped {result['skipped']}."
    )
    for r in result["replacements"][:10]:
        print(
            f"  • {r['promo_name']} {r['wc_name']}: "
            f"{r['old_champ']} (avg={r['old_avg_attr']}) → "
            f"{r['new_champ']} (elo={r['new_rating']})"
        )
    if len(result["replacements"]) > 10:
        print(f"  ... and {len(result['replacements']) - 10} more.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
