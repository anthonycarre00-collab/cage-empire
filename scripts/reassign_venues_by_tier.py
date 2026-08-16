#!/usr/bin/env python3
"""Phase 4 (PHASE4-IMPLEMENT) — reassign venues by promo size_tier.

Problem: small promos are using 10K-18K seat arenas (Moscow Coliseum
13,205; Manaus Coliseum 14,278; etc.) which is unrealistic for regional
MMA promotions and produces absurd ticket revenue (~$300K/event on a
"small" promo). Real small/regional promotions fight in 800-3,000 seat
venues (armories, ballrooms, small theaters).

Fix: for each event, pick a tier-appropriate venue from the promo's
nation. The capacity bands:

  - Major: 8,000 - 18,500 seats (UFC-level arena)
  - Mid:   3,000 - 8,000 seats (regional arena / theater)
  - Small: 1,500 - 5,000 seats (armory / ballroom / small theater)

If no venue in the promo's nation falls in the tier's band, fall back
to the closest available capacity (any venue in the nation), then to
the closest venue globally. Log every fallback for visibility.

Idempotent: re-running on an already-reassigned DB is a no-op (events
whose venue is already tier-appropriate stay put).

Usage:
    python scripts/reassign_venues_by_tier.py            # apply
    python scripts/reassign_venues_by_tier.py --dry-run  # preview only
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Resolve DB path relative to this script (works from any CWD).
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cage_empire.db"

# Capacity bands per size_tier (min, max) — inclusive.
TIER_BANDS = {
    "major": (8000, 18500),
    "mid":   (3000, 8000),
    "small": (1500, 5000),
}


def pick_venue_for_event(cur, promo_id: int, size_tier: str,
                         event_id: int) -> tuple[int | None, str]:
    """Pick a tier-appropriate venue for the given promo + event.

    Returns (venue_id, reason) where reason explains the choice:
      'tier_match_in_nation' — found venue in band within promo's nation
      'closest_in_nation'    — no venue in band, picked closest in nation
      'tier_match_global'    — no venue in nation, picked from any nation
      'no_change'            — current venue already in band
      'no_venue_found'       — no venues at all (shouldn't happen)
    """
    # Get the promo's nation_id so we can prefer same-nation venues.
    row = cur.execute(
        "SELECT nation_id FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()
    if not row:
        return None, "no_venue_found"
    nation_id = row[0]

    # Get the event's current venue_id so we can skip if already in band.
    cur.execute(
        "SELECT venue_id FROM events WHERE event_id=?", (event_id,),
    )
    cur_venue_row = cur.fetchone()
    cur_venue_id = cur_venue_row[0] if cur_venue_row else None

    band = TIER_BANDS.get(size_tier)
    if not band:
        return cur_venue_id, "no_change"  # unknown tier — leave alone
    min_cap, max_cap = band

    # If current venue is already in band, no change needed.
    if cur_venue_id is not None:
        cur_cap_row = cur.execute(
            "SELECT capacity FROM venues WHERE venue_id=?",
            (cur_venue_id,),
        ).fetchone()
        if cur_cap_row and min_cap <= cur_cap_row[0] <= max_cap:
            return cur_venue_id, "no_change"

    # Prefer the LARGEST venue in the band within the promo's nation —
    # maximizes ticket revenue while staying tier-appropriate. Use a
    # deterministic ordering (venue_id ASC as tiebreaker) so re-runs
    # produce identical results.
    candidates = cur.execute(
        """
        SELECT v.venue_id, v.capacity
        FROM venues v
        JOIN cities c ON c.city_id = v.city_id
        WHERE c.nation_id = ?
          AND v.capacity BETWEEN ? AND ?
        ORDER BY v.capacity DESC, v.venue_id ASC
        """,
        (nation_id, min_cap, max_cap),
    ).fetchall()
    if candidates:
        # Pick deterministically based on event_id so different events
        # for the same promo spread across multiple venues (avoids
        # every event in the same small arena — would look weird).
        chosen = candidates[event_id % len(candidates)]
        return chosen[0], "tier_match_in_nation"

    # Fallback 1: closest capacity venue in the promo's nation.
    fallback = cur.execute(
        """
        SELECT v.venue_id, v.capacity,
               ABS(v.capacity - ?) AS dist
        FROM venues v
        JOIN cities c ON c.city_id = v.city_id
        WHERE c.nation_id = ?
        ORDER BY dist ASC, v.venue_id ASC
        LIMIT 1
        """,
        ((min_cap + max_cap) // 2, nation_id),
    ).fetchone()
    if fallback:
        return fallback[0], f"closest_in_nation(cap={fallback[1]})"

    # Fallback 2: any venue globally in the band.
    fallback = cur.execute(
        """
        SELECT venue_id, capacity
        FROM venues
        WHERE capacity BETWEEN ? AND ?
        ORDER BY capacity DESC, venue_id ASC
        """,
        (min_cap, max_cap),
    ).fetchall()
    if fallback:
        chosen = fallback[event_id % len(fallback)]
        return chosen[0], "tier_match_global"

    # Fallback 3: closest venue globally.
    fallback = cur.execute(
        """
        SELECT venue_id, capacity,
               ABS(capacity - ?) AS dist
        FROM venues
        ORDER BY dist ASC, venue_id ASC
        LIMIT 1
        """,
        ((min_cap + max_cap) // 2,),
    ).fetchone()
    if fallback:
        return fallback[0], f"closest_global(cap={fallback[1]})"

    return None, "no_venue_found"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing to the DB.",
    )
    parser.add_argument(
        "--db", type=Path, default=DB_PATH,
        help=f"Path to cage_empire.db (default: {DB_PATH}).",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        return 1

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # Build the work list: every event with its promo's size_tier.
    events = cur.execute(
        """
        SELECT e.event_id, e.promotion_id, p.size_tier, p.name AS promo_name
        FROM events e
        JOIN promotions p ON p.promotion_id = e.promotion_id
        ORDER BY e.event_id
        """,
    ).fetchall()

    changes_by_tier = {"major": 0, "mid": 0, "small": 0}
    no_change_by_tier = {"major": 0, "mid": 0, "small": 0}
    fallback_log: list[str] = []
    total_events = 0

    for ev in events:
        total_events += 1
        new_venue, reason = pick_venue_for_event(
            cur, ev["promotion_id"], ev["size_tier"], ev["event_id"],
        )
        if new_venue is None:
            fallback_log.append(
                f"  event_id={ev['event_id']} promo={ev['promo_name']} "
                f"tier={ev['size_tier']}: NO VENUE FOUND — skipped"
            )
            continue
        if reason == "no_change":
            no_change_by_tier[ev["size_tier"]] = no_change_by_tier.get(
                ev["size_tier"], 0,
            ) + 1
            continue

        # Apply (or preview) the change.
        if not args.dry_run:
            cur.execute(
                "UPDATE events SET venue_id=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE event_id=?",
                (new_venue, ev["event_id"]),
            )
        changes_by_tier[ev["size_tier"]] = changes_by_tier.get(
            ev["size_tier"], 0,
        ) + 1

        # Log any non-ideal fallbacks.
        if reason not in ("tier_match_in_nation", "no_change"):
            fallback_log.append(
                f"  event_id={ev['event_id']} promo={ev['promo_name']} "
                f"tier={ev['size_tier']}: fallback={reason} "
                f"new_venue_id={new_venue}"
            )

    if not args.dry_run:
        db.commit()

    # Print summary.
    print(f"=== Venue reassignment {'(DRY RUN)' if args.dry_run else 'COMPLETE'} ===")
    print(f"Total events processed: {total_events}")
    for tier in ("major", "mid", "small"):
        ch = changes_by_tier.get(tier, 0)
        nc = no_change_by_tier.get(tier, 0)
        print(f"  {tier:6s}: {ch:>5} reassigned | {nc:>5} already in band")
    if fallback_log:
        print()
        print(f"=== Fallbacks ({len(fallback_log)} events) ===")
        for line in fallback_log[:50]:
            print(line)
        if len(fallback_log) > 50:
            print(f"  ... ({len(fallback_log) - 50} more)")
    else:
        print("No fallbacks — all reassigned events got tier-appropriate venues.")

    # Post-state: avg venue cap by tier.
    print()
    print("=== Post-state: avg venue capacity by tier ===")
    rows = cur.execute(
        """
        SELECT p.size_tier,
               COUNT(DISTINCT e.event_id) AS events,
               MIN(v.capacity) AS min_cap,
               MAX(v.capacity) AS max_cap,
               AVG(v.capacity) AS avg_cap
        FROM events e
        JOIN promotions p ON p.promotion_id = e.promotion_id
        JOIN venues v ON v.venue_id = e.venue_id
        GROUP BY p.size_tier
        ORDER BY p.size_tier
        """,
    ).fetchall()
    for r in rows:
        print(
            f"  {r['size_tier']:6s}: {r['events']:>4} events | "
            f"min={r['min_cap']:>5} max={r['max_cap']:>5} "
            f"avg={r['avg_cap']:>8,.0f}"
        )

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
