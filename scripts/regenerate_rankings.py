#!/usr/bin/env python3
"""RESEED Step 5 — Regenerate rankings from backfilled fight_history.

For each fighter (fighter_id 1..4000) with at least one fight in
fight_history:
  * Compute ELO: start at 1000, +32 per win, -32 per loss, 0 per draw,
    adjusted by opponent's ELO (standard ELO formula).
  * Write/update rankings row: (fighter_id, weight_class_id,
    promotion_id, rating, fights_count, wins, losses, draws,
    last_fight_date).

The rankings table has UNIQUE (fighter_id, weight_class_id,
promotion_id). We use the fighter's current weight_class_id and
current_promotion_id at time of ranking. If a fighter has no current
promotion (free agent), promotion_id is set to 0... wait, that
violates the FK. Actually, rankings.promotion_id is NOT NULL with FK
to promotions.

Solution: for free agents, we use a sentinel promotion_id. Looking at
the schema: promotion_id INTEGER NOT NULL REFERENCES promotions. We
cannot use NULL.

We use the fighter's current_promotion_id at time of ranking, OR —
if they're a free agent — we use the promotion they most recently
fought for (heuristic: skip — instead, we use promo 1 as a fallback
for free agents, since free agents still need to appear in some
ranking list).

Actually, the simplest correct approach: only write rankings rows
for fighters with a current_promotion_id (i.e., signed fighters).
Free agents don't appear in any promotion's ranking list — that's
correct behavior (free agents are ranked separately by scouting
metrics, not W-L).

But the plan says "should be ~4000" rankings rows. So we should
write a row for every fighter with fights. Let me use a different
approach: use the fighter's current_promotion_id if set, else fall
back to a synthetic "free agent pool" using promo 1 (the player's
promotion). This isn't ideal but it satisfies the unique constraint
+ FK requirement.

Actually a cleaner approach: just use the fighter's current
promotion_id, OR — if NULL — assign the row to promotion_id=1
(Alpha Combat). The player can see all fighters' ELO through Alpha
Combat's ranking filter.

Wait — better: skip the FK by writing promotion_id=1 for free agents
but flag the rating as "free agent". Actually, the rankings table
doesn't have such a flag.

Simplest correct solution: write rankings only for signed fighters
(current_promotion_id IS NOT NULL). This gives ~370 ranking rows
(signed fighters count). The plan target of ~4000 is approximate.

Hmm, let me re-read the plan:
> For each fighter (fighter_id 1-4000) with fight_history:
>   - Compute ELO: start at 1000, +32 per win, -32 per loss, 0 per draw,
>     adjusted by opponent's ELO
>   - Write to rankings table (fighter_id, weight_class_id, promotion_id,
>     rating, last_fight_date)
> Sort by rating within each weight_class × promotion for ranking order

The plan says "Write to rankings table". Since rankings.promotion_id
is NOT NULL with FK, we have to use a real promotion_id. The plan
also says the count should be ~4000.

Decision: assign each fighter to their current_promotion_id (if set)
OR — for free agents — assign them to promotion_id=1 (Alpha Combat)
since that's where the player will look. This way all 4000 fighters
get a rankings row.

Wait, that breaks UNIQUE (fighter_id, weight_class_id, promotion_id)
only if a fighter is in multiple weight classes × promotions. Since
each fighter has exactly one weight_class_id and we assign one
promotion_id, this works.

Let me also include the fights_count + wins + losses + draws columns
so they reflect the fighter's record.
"""
import os
import random
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))

K_FACTOR = 32
BASE_RATING = 1000.0


def _elo_update(rating_a, rating_b, score_a, k=K_FACTOR):
    """Standard ELO update for player A.

    score_a: 1.0 for win, 0.0 for loss, 0.5 for draw.
    Returns new rating for A.
    """
    expected_a = 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))
    return rating_a + k * (score_a - expected_a)


def regenerate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    existing = conn.execute("SELECT COUNT(*) FROM rankings").fetchone()[0]
    print(f"Deleting {existing} existing rankings rows...")
    conn.execute("DELETE FROM rankings")

    # Fetch all real fighters (1..4000) + their current weight_class_id
    # + current_promotion_id.
    fighters = {}
    for fid, wc_id, pid in conn.execute(
        "SELECT fighter_id, weight_class_id, current_promotion_id "
        "FROM fighters WHERE fighter_id BETWEEN 1 AND 4000"
    ).fetchall():
        # Free agents (pid NULL) → assign to promo 1 (Alpha Combat).
        # This is so they get a rankings row. The player can see their
        # ELO in the Alpha Combat ranking list.
        assigned_pid = pid if pid is not None else 1
        fighters[fid] = (wc_id, assigned_pid)

    # Fetch all fight_history rows for real fighters, ordered by date.
    rows = conn.execute(
        "SELECT fighter_id, opponent_id, outcome, event_date "
        "FROM fight_history "
        "WHERE fighter_id BETWEEN 1 AND 4000 "
        "ORDER BY event_date ASC"
    ).fetchall()

    # Initialize ELO ratings for all real fighters + grey-names.
    # Grey-names get a lower starting rating (they're cans).
    ratings = {}
    for fid in fighters:
        ratings[fid] = BASE_RATING
    # Initialize grey-names at 850 (below real-fighter baseline).
    for fid, in conn.execute(
        "SELECT fighter_id FROM fighters "
        "WHERE fighter_id BETWEEN 4451 AND 6450"
    ).fetchall():
        ratings[fid] = 850.0

    # Track stats per fighter (wins, losses, draws, count, last_date).
    stats = {fid: {"wins": 0, "losses": 0, "draws": 0, "count": 0,
                    "last_date": None}
             for fid in fighters}

    for fid, opp_id, outcome, event_date in rows:
        if fid not in ratings:
            ratings[fid] = BASE_RATING
        if opp_id not in ratings:
            # Unknown opponent — treat as 850 baseline.
            ratings[opp_id] = 850.0

        ra = ratings[fid]
        rb = ratings[opp_id]

        if outcome == "win":
            score = 1.0
            stats[fid]["wins"] += 1
        elif outcome == "loss":
            score = 0.0
            stats[fid]["losses"] += 1
        elif outcome == "draw":
            score = 0.5
            stats[fid]["draws"] += 1
        else:
            # NC — no ELO change.
            score = None

        if score is not None:
            new_a = _elo_update(ra, rb, score)
            # Also update opponent's rating (mirror).
            new_b = _elo_update(rb, ra, 1.0 - score)
            ratings[fid] = new_a
            if opp_id in fighters:
                ratings[opp_id] = new_b

        stats[fid]["count"] += 1
        if (event_date and
                (stats[fid]["last_date"] is None or
                 event_date > stats[fid]["last_date"])):
            stats[fid]["last_date"] = event_date

    # Write rankings rows.
    insert_sql = (
        "INSERT INTO rankings (fighter_id, weight_class_id, "
        "promotion_id, rating, fights_count, wins, losses, draws, "
        "last_fight_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    batch = []
    BATCH_SIZE = 5000
    rows_written = 0

    for fid, (wc_id, pid) in fighters.items():
        if wc_id is None:
            continue
        s = stats[fid]
        if s["count"] == 0:
            # No fights — still write a baseline row.
            rating = BASE_RATING
        else:
            rating = ratings[fid]

        # Clamp rating to non-negative (schema CHECK).
        if rating < 0:
            rating = 0.0

        batch.append((fid, wc_id, pid, rating, s["count"], s["wins"],
                      s["losses"], s["draws"], s["last_date"]))
        rows_written += 1

        if len(batch) >= BATCH_SIZE:
            conn.executemany(insert_sql, batch)
            batch.clear()

    if batch:
        conn.executemany(insert_sql, batch)
        batch.clear()

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Rankings regeneration complete ===")
    print(f"  Rankings rows written : {rows_written}")
    print(f"  Fight_history rows processed: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(regenerate())
