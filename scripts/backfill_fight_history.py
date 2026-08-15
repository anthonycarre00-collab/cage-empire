#!/usr/bin/env python3
"""RESEED Step 4 — Backfill fight_history for all 4000 real fighters.

For each fighter with suggested_total_fights > 0, generate
suggested_wins + suggested_losses + suggested_draws fight_history
rows.

Rules:
  * ~30% of opponents are DB fighters (fighter_id 1..4000, same
    weight_class_id, similar career tier).
  * ~70% of opponents are grey-name fighters (fighter_id 4451..6450,
    same weight_class_id).
  * Result-type distribution (per row):
        ko_tko 35%, submission 20%, unanimous_decision 30%,
        split_decision 10%, draw 3%, dq 1%, no_contest 1%
  * Outcome derives from result_type: ko_tko/submission/UD/SD/dq →
    win OR loss (decided by fighter's W-L-D allocation); draw →
    draw; no_contest → nc.
  * Fight dates spread between debut age (17-23) and current age,
    random dates.
  * Elite/Contender fighters: ~2-3 title fights (title_at_stake=1).
  * Each fight_history row references a synthetic fight_id (100000+)
    so we don't collide with real `fights` table rows (1..~2000).

Plan note: "Do NOT create fights table rows or events — just
fight_history (this is historical record, not simulated fights)."
"""
import csv
import os
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))
CSV_PATH = PROJECT_DIR / "data" / "fighter_seed_rebuild.csv"

SIM_DATE = date(2026, 7, 20)  # matches simulation_clock.current_date

# Synthetic fight_id range — well above existing fights rows.
SYNTH_FIGHT_ID_START = 100_000

# Result-type weights (per outcome).
# For wins / losses (each): pick from this distribution.
RESULT_TYPE_WEIGHTS_WIN_LOSS = [
    ("ko_tko", 35),
    ("submission", 20),
    ("unanimous_decision", 30),
    ("split_decision", 10),
    ("dq", 1),
]
# Draw and NC are determined by outcome.
DRAW_RESULT_TYPE = "draw"
NC_RESULT_TYPE = "no_contest"

# Result-type finish_round + finish_time templates by result_type.
FINISH_TEMPLATES = {
    "ko_tko":              [(1, "0:30"), (1, "1:15"), (1, "2:45"), (2, "1:30"), (2, "3:20"), (3, "2:10")],
    "submission":          [(1, "1:20"), (1, "2:55"), (2, "0:45"), (2, "3:15"), (3, "1:40")],
    "unanimous_decision":  [(3, "5:00"), (3, "5:00"), (3, "5:00")],  # always full fight
    "split_decision":      [(3, "5:00"), (3, "5:00")],
    "draw":                [(3, "5:00"), (3, "5:00")],
    "dq":                  [(1, "2:30"), (2, "1:45"), (1, "4:15")],
    "no_contest":          [(1, "1:00"), (2, "2:30"), (1, "0:45")],
}

# Tier → title-fight frequency (per fighter career).
TIER_TITLE_FIGHT_COUNT = {
    "Elite":     (2, 3),
    "Contender": (2, 3),
    "Gatekeeper": (1, 2),
    "Fringe":    (0, 1),
    "Prospect":  (0, 1),
    "Unproven":  (0, 0),
    "DecliningVet": (1, 2),
}


def _parse_dob(dob_str):
    try:
        y, m, d = dob_str.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _pick_weighted(items_weights, rng):
    """Pick a single item using weighted random."""
    total = sum(w for _, w in items_weights)
    r = rng.random() * total
    cumulative = 0
    for item, w in items_weights:
        cumulative += w
        if r < cumulative:
            return item
    return items_weights[-1][0]  # fallback


def backfill():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}", file=sys.stderr)
        return 1

    # Load CSV: fighter_id → record + tier + age
    csv_data = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                fid = int(row["fighter_id"])
            except (ValueError, KeyError):
                continue
            csv_data[fid] = {
                "wins": int(row.get("suggested_wins") or 0),
                "losses": int(row.get("suggested_losses") or 0),
                "draws": int(row.get("suggested_draws") or 0),
                "tier": (row.get("career_tier") or "").strip(),
                "age": int(row.get("age") or 25),
            }

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    # DELETE all existing fight_history rows (we're reseeding).
    existing = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    print(f"Deleting {existing} existing fight_history rows...")
    conn.execute("DELETE FROM fight_history")

    # Pre-build per-weight-class opponent pools.
    # Real DB fighters (1..4000) by weight_class_id.
    real_by_wc = {}
    for fid, wc_id in conn.execute(
        "SELECT fighter_id, weight_class_id FROM fighters "
        "WHERE fighter_id BETWEEN 1 AND 4000 AND weight_class_id IS NOT NULL"
    ).fetchall():
        real_by_wc.setdefault(wc_id, []).append(fid)

    # Grey-name fighters (4451..6450) by weight_class_id.
    grey_by_wc = {}
    for fid, wc_id in conn.execute(
        "SELECT fighter_id, weight_class_id FROM fighters "
        "WHERE fighter_id BETWEEN 4451 AND 6450 AND weight_class_id IS NOT NULL"
    ).fetchall():
        grey_by_wc.setdefault(wc_id, []).append(fid)

    # Fighter → weight_class_id map (for real fighters).
    fighter_wc = {}
    for fid, wc_id in conn.execute(
        "SELECT fighter_id, weight_class_id FROM fighters "
        "WHERE fighter_id BETWEEN 1 AND 4000"
    ).fetchall():
        fighter_wc[fid] = wc_id

    # Fighter → DOB
    fighter_dob = {}
    for fid, dob in conn.execute(
        "SELECT fighter_id, date_of_birth FROM fighters "
        "WHERE fighter_id BETWEEN 1 AND 4000"
    ).fetchall():
        fighter_dob[fid] = _parse_dob(dob)

    rng = random.Random(20260815)

    fight_id_counter = SYNTH_FIGHT_ID_START
    total_rows = 0
    fighters_processed = 0
    title_fights_total = 0
    db_vs_db_total = 0
    db_vs_grey_total = 0
    rows_skipped_no_opponent = 0

    insert_sql = (
        "INSERT INTO fight_history "
        "(fight_id, fighter_id, opponent_id, outcome, result_type, "
        "finish_round, finish_time, event_date, weight_class_id, "
        "title_at_stake) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    batch = []
    BATCH_SIZE = 5000

    for fid in range(1, 4001):
        meta = csv_data.get(fid)
        if not meta:
            continue
        wins = meta["wins"]
        losses = meta["losses"]
        draws = meta["draws"]
        total = wins + losses + draws
        if total == 0:
            continue  # fighter has no fights

        wc_id = fighter_wc.get(fid)
        if wc_id is None:
            continue

        dob = fighter_dob.get(fid)
        if dob is None:
            continue

        # Debut age: random 17-23 (with floor at fighter's age - total_years_span)
        # The fighter must have been at least ~17 at debut.
        age_now = SIM_DATE.year - dob.year
        debut_age = rng.randint(17, min(23, max(17, age_now - 1)))
        debut_date = date(dob.year + debut_age, dob.month, dob.day)
        # If debut is after sim_date (young fighter), clamp.
        if debut_date > SIM_DATE:
            debut_date = date(dob.year + 17, dob.month, dob.day)
        if debut_date > SIM_DATE:
            debut_date = SIM_DATE - timedelta(days=365)

        # Build the list of fights for this fighter.
        # Each fight: (outcome, result_type, title_at_stake)
        fights_list = []

        # Wins
        for _ in range(wins):
            rt = _pick_weighted(RESULT_TYPE_WEIGHTS_WIN_LOSS, rng)
            fights_list.append(("win", rt, 0))
        # Losses
        for _ in range(losses):
            rt = _pick_weighted(RESULT_TYPE_WEIGHTS_WIN_LOSS, rng)
            fights_list.append(("loss", rt, 0))
        # Draws
        for _ in range(draws):
            fights_list.append(("draw", DRAW_RESULT_TYPE, 0))

        # Sprinkle in NCs (~1% of total). Take a random non-title fight
        # and convert it to an NC (outcome='nc', result_type='no_contest').
        # NCs don't count in W-L-D record so we ADD them as extra rows.
        nc_count = max(0, int(total * 0.01))
        for _ in range(nc_count):
            fights_list.append(("nc", NC_RESULT_TYPE, 0))

        # Title fights: mark N fights (from wins/losses) as title_at_stake=1.
        # Prefer Elite/Contender tiers with the (lo, hi) range.
        tier = meta["tier"]
        lo, hi = TIER_TITLE_FIGHT_COUNT.get(tier, (0, 0))
        if lo > 0 and total >= 4:
            n_title = rng.randint(lo, hi)
            # Pick n_title random win/loss rows (not draws/NCs) and flag.
            eligible_indices = [
                i for i, f in enumerate(fights_list)
                if f[0] in ("win", "loss")
            ]
            rng.shuffle(eligible_indices)
            for i in eligible_indices[:n_title]:
                outcome, rt, _ = fights_list[i]
                fights_list[i] = (outcome, rt, 1)
            title_fights_total += n_title

        # Assign fight dates: spread between debut_date and SIM_DATE,
        # roughly chronological.
        fight_dates = []
        span_days = (SIM_DATE - debut_date).days
        if span_days < 30:
            span_days = 30
        for i in range(len(fights_list)):
            # Spread evenly with jitter.
            base = i / max(1, len(fights_list) - 1)
            jitter = rng.uniform(-0.05, 0.05)
            frac = max(0.0, min(1.0, base + jitter))
            days = int(frac * span_days)
            d = debut_date + timedelta(days=days)
            if d > SIM_DATE:
                d = SIM_DATE
            fight_dates.append(d)

        # Shuffle fights so dates don't perfectly match W-L-D order.
        # But keep dates sorted chronologically.
        fight_dates.sort()
        rng.shuffle(fights_list)

        # Generate each fight row.
        for i, (outcome, rt, title) in enumerate(fights_list):
            event_date = fight_dates[i]

            # Choose opponent type.
            is_db_opponent = rng.random() < 0.30
            opponent_id = None
            if is_db_opponent:
                # Real DB opponent — same weight class.
                pool = real_by_wc.get(wc_id, [])
                # Exclude self.
                pool = [o for o in pool if o != fid]
                if pool:
                    opponent_id = rng.choice(pool)
                    db_vs_db_total += 1
                else:
                    # Fall back to grey-name.
                    grey_pool = grey_by_wc.get(wc_id, [])
                    if grey_pool:
                        opponent_id = rng.choice(grey_pool)
                        db_vs_grey_total += 1
                    else:
                        rows_skipped_no_opponent += 1
                        continue
            else:
                grey_pool = grey_by_wc.get(wc_id, [])
                if grey_pool:
                    opponent_id = rng.choice(grey_pool)
                    db_vs_grey_total += 1
                else:
                    # Fall back to DB opponent.
                    pool = [o for o in real_by_wc.get(wc_id, []) if o != fid]
                    if pool:
                        opponent_id = rng.choice(pool)
                        db_vs_db_total += 1
                    else:
                        rows_skipped_no_opponent += 1
                        continue

            # Finish round + time.
            templates = FINISH_TEMPLATES.get(rt, [(3, "5:00")])
            finish_round, finish_time = rng.choice(templates)

            batch.append((
                fight_id_counter, fid, opponent_id, outcome, rt,
                finish_round, finish_time, event_date.isoformat(),
                wc_id, title,
            ))
            fight_id_counter += 1
            total_rows += 1

            if len(batch) >= BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()

        fighters_processed += 1

    if batch:
        conn.executemany(insert_sql, batch)
        batch.clear()

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Fight history backfill complete ===")
    print(f"  Fighters processed      : {fighters_processed}")
    print(f"  Total rows inserted     : {total_rows}")
    print(f"  DB-vs-DB fights         : {db_vs_db_total}")
    print(f"  DB-vs-grey fights       : {db_vs_grey_total}")
    print(f"  Title fights (at_stake=1): {title_fights_total}")
    print(f"  Rows skipped (no opp)   : {rows_skipped_no_opponent}")
    print(f"  Synthetic fight_id range: {SYNTH_FIGHT_ID_START} .. {fight_id_counter - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(backfill())
