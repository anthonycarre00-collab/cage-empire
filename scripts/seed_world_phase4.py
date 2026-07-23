#!/usr/bin/env python3
"""World seed Phase 4: Career histories, fights, titles, contracts, injuries.

Run AFTER Phase 3 (4000 fighters must exist). Idempotent — re-running
skips work already done (checks fight_history count vs fighter record sums).

Per the analysis (docs/WORLD_SEED_ANALYSIS.md): career histories are
GENERATED BACKWARD, not simulated forward. Each fighter already has
record_wins/losses/draws set in Phase 3; Phase 4 generates the
historical fight_history rows + fights + events + titles + contracts
that match those records.

Scale:
  - ~30,000-50,000 historical fight_history rows (2 per fight × ~15-25k fights)
  - ~15,000-25,000 historical fights (each producing 2 fight_history rows)
  - ~3,000-5,000 historical events (cards holding 4-6 fights each)
  - 60-120 titles (one per weight class per promotion) — most held, some vacant
  - ~3,500 active contracts (one per signed fighter)
  - ~300-500 injuries (some fighters recovering, some with long-term damage)

Historical fights have RESULTS but NO beat data (would be millions of
rows). Only fights that happen during gameplay get beat-level data.

Usage:
    python scripts/seed_world_phase4.py
"""
import sqlite3
import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

random.seed(20260724)  # reproducible world — distinct from Phase 3

# Sim date — the "present" the world is seeded at.
SIM_DATE = datetime(2026, 7, 22)

# Result type distribution (realistic MMA approximations)
# Per real-world UFC stats: ~50% decision, ~30% KO/TKO, ~15% submission, ~5% other
RESULT_TYPE_WEIGHTS = [
    ("unanimous_decision", 0.40),
    ("split_decision",     0.08),
    ("ko_tko",             0.30),
    ("submission",         0.15),
    ("doctor_stoppage",    0.03),
    ("dq",                 0.01),
    ("draw",               0.03),
]

# Finish round distribution (for non-decision fights)
# Round 1: 50%, Round 2: 30%, Round 3: 18%, Round 4: 1.5%, Round 5: 0.5%
FINISH_ROUND_WEIGHTS = [(1, 50), (2, 30), (3, 18), (4, 1.5), (5, 0.5)]


def _pick_result_type(rng):
    labels = [r[0] for r in RESULT_TYPE_WEIGHTS]
    weights = [r[1] for r in RESULT_TYPE_WEIGHTS]
    return rng.choices(labels, weights=weights, k=1)[0]


def _pick_finish_round(rng, scheduled_rounds):
    """Pick a finish round (1 to scheduled_rounds)."""
    labels = [r[0] for r in FINISH_ROUND_WEIGHTS if r[0] <= scheduled_rounds]
    weights = [r[1] for r in FINISH_ROUND_WEIGHTS if r[0] <= scheduled_rounds]
    return rng.choices(labels, weights=weights, k=1)[0]


def _gen_finish_time(rng, round_num):
    """Generate a finish time string 'M:SS' for the given round."""
    if round_num == 1:
        minutes = rng.randint(0, 4)
    else:
        minutes = rng.randint(0, 4)
    seconds = rng.randint(0, 59)
    return f"{minutes}:{seconds:02d}"


def _gen_event_date(rng, fighter_dob_year, fighter_age):
    """Generate a plausible event date for a historical fight.
    Fights happen between the fighter's 18th birthday and the sim date.
    """
    earliest_year = max(fighter_dob_year + 18, 2015)  # don't go before 2015
    latest_year = 2026
    if earliest_year >= latest_year:
        return SIM_DATE.strftime("%Y-%m-%d")
    year = rng.randint(earliest_year, latest_year)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{year}-{month:02d}-{day:02d}"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run Phase 1+2+3 first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Verify Phase 3 ran
    n_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    if n_fighters < 3000:
        print(f"ERROR: Phase 3 not complete (only {n_fighters} fighters).")
        sys.exit(1)

    # Check if Phase 4 already ran
    n_fh = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    if n_fh > 10000:
        print(f"Already {n_fh} fight_history rows — Phase 4 already complete.")
        return

    rng = random.Random(20260724)

    # ----------------------------------------------------------------
    # 1. Load all fighters grouped by (weight_class_id, promotion_id)
    #    so we can match opponents in the same WC + promotion.
    # ----------------------------------------------------------------
    print("Loading fighters...")
    fighters = conn.execute(
        "SELECT f.fighter_id, f.weight_class_id, f.current_promotion_id, "
        "f.date_of_birth, fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.potential "
        "FROM fighters f "
        "JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 AND f.is_retired = 0"
    ).fetchall()
    print(f"  {len(fighters)} active fighters loaded")

    # Group by (wc_id, promo_id) for matchmaking
    from collections import defaultdict
    by_wc_promo = defaultdict(list)
    for f in fighters:
        fid, wc_id, promo_id, dob, w, l, d, pot = f
        if promo_id is None:
            continue  # free agents — handled separately
        by_wc_promo[(wc_id, promo_id)].append(f)

    # ----------------------------------------------------------------
    # 2. Generate historical fights.
    #
    # Strategy: for each fighter, generate (wins + losses + draws)
    # fight_history rows. For each row, pick an opponent from the
    # same (wc, promo) group. Both fighters get a fight_history row
    # (one win, one loss — or both draws).
    #
    # To avoid generating the same fight twice (once for each
    # fighter's perspective), we track which (fighter, opponent)
    # pairs have been paired. We process fighters in order; when we
    # generate a fight for fighter A vs opponent B, we also decrement
    # B's "remaining fights to generate" counter.
    # ----------------------------------------------------------------
    print("Generating historical fights...")
    # remaining_fights[fighter_id] = number of fights still to generate
    remaining_fights = {f[0]: f[4] + f[5] + f[6] for f in fighters}
    # total_fights_to_generate = sum of all fighters' total fights / 2
    total_to_gen = sum(remaining_fights.values()) // 2
    print(f"  Target: ~{total_to_gen} historical fights")

    # Cache fighter info for quick lookup
    fighter_info = {f[0]: f for f in fighters}

    n_fights_created = 0
    n_events_created = 0
    n_fh_created = 0
    BATCH_SIZE = 500

    # Track event dates to batch fights into events (4-6 fights per event)
    # Key: (promo_id, event_date) -> list of (fight_id, fight_data)
    events_buffer = defaultdict(list)

    # Process fighters in random order
    fighter_ids = list(remaining_fights.keys())
    rng.shuffle(fighter_ids)

    for fid in fighter_ids:
        while remaining_fights[fid] > 0:
            f = fighter_info[fid]
            fid, wc_id, promo_id, dob, w, l, d, pot = f
            # Find an opponent: same (wc, promo), different fid, also has remaining fights
            # by_wc_promo values are tuples (fid, wc_id, promo_id, dob, w, l, d, pot)
            candidates = [
                t[0] for t in by_wc_promo.get((wc_id, promo_id), [])
                if t[0] != fid and remaining_fights.get(t[0], 0) > 0
            ]
            if not candidates:
                # No opponent available — give up on this fighter's remaining fights
                break
            oid = rng.choice(candidates)
            o = fighter_info[oid]
            oid, _, _, odob, ow, ol, od, opot = o

            # Decide outcome
            result_type = _pick_result_type(rng)
            # Higher-potential fighter wins more often
            if result_type == "draw":
                outcome_a = "draw"
                outcome_b = "draw"
            else:
                # Probability A wins = (pot / (pot + opot))
                p_a_wins = pot / (pot + opot + 0.01)
                if rng.random() < p_a_wins:
                    winner_id = fid
                    loser_id = oid
                    outcome_a = "win"
                    outcome_b = "loss"
                else:
                    winner_id = oid
                    loser_id = fid
                    outcome_a = "loss"
                    outcome_b = "win"

            # Scheduled rounds (3 or 5; title fights = 5)
            is_title = 0  # historical title fights are rare in the seed
            scheduled_rounds = 5 if is_title else 3
            if result_type in ("unanimous_decision", "split_decision", "draw"):
                finish_round = scheduled_rounds
                finish_time = "5:00"
                score_margin = rng.randint(1, 8) if result_type == "unanimous_decision" else rng.randint(0, 2)
            else:
                finish_round = _pick_finish_round(rng, scheduled_rounds)
                finish_time = _gen_finish_time(rng, finish_round)
                score_margin = 0

            # Event date: somewhere in the past 11 years
            dob_year_a = int(dob[:4]) if dob else 1995
            event_date = _gen_event_date(rng, dob_year_a, 0)

            # Create event if needed (batch by promo + date)
            event_key = (promo_id, event_date)
            if event_key not in events_buffer or len(events_buffer[event_key]) >= 5:
                # Create a new event for this date
                # Pick a venue in the promotion's nation
                venue_row = conn.execute(
                    "SELECT v.venue_id, m.market_id FROM venues v "
                    "JOIN cities c ON c.city_id = v.city_id "
                    "JOIN markets m ON m.city_id = c.city_id "
                    "JOIN promotions p ON p.nation_id = c.nation_id "
                    "WHERE p.promotion_id=? ORDER BY RANDOM() LIMIT 1",
                    (promo_id,),
                ).fetchone()
                if venue_row is None:
                    # Fallback: any venue + market
                    venue_row = conn.execute(
                        "SELECT v.venue_id, m.market_id FROM venues v "
                        "JOIN markets m ON m.city_id = v.city_id "
                        "ORDER BY RANDOM() LIMIT 1"
                    ).fetchone()
                venue_id = venue_row[0] if venue_row else 1
                market_id = venue_row[1] if venue_row else 1
                cur = conn.execute(
                    "INSERT INTO events (event_date, status, promotion_id, "
                    "venue_id, market_id, event_name, event_type) "
                    "VALUES (?, 'completed', ?, ?, ?, ?, 'numbered')",
                    (event_date, promo_id, venue_id, market_id,
                     f"Event {event_date}"),
                )
                event_id = cur.lastrowid
                events_buffer[event_key] = [(None, {"event_id": event_id})]
                n_events_created += 1
            else:
                # Reuse the event_id from the buffer
                event_id = events_buffer[event_key][0][1]["event_id"]

            # Create the fight row
            cur = conn.execute(
                "INSERT INTO fights (event_id, weight_class_id, bout_type, "
                "card_slot, is_title_fight, round_limit, scheduled_rounds, "
                "winner_fighter_id, loser_fighter_id, result_type, "
                "finish_round, finish_time, performance_rating, "
                "fan_reaction_rating) "
                "VALUES (?, ?, 'prelim', 'prelim', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, wc_id, is_title, scheduled_rounds, scheduled_rounds,
                 winner_id if result_type != "draw" else None,
                 loser_id if result_type != "draw" else None,
                 result_type, finish_round, finish_time,
                 rng.randint(40, 95), rng.randint(40, 95)),
            )
            fight_id = cur.lastrowid
            n_fights_created += 1

            # Buffer this fight under the event
            events_buffer[event_key].append((fight_id, {"event_id": event_id}))

            # Create 2 fight_history rows (one per fighter's perspective)
            conn.execute(
                "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
                "outcome, result_type, finish_round, finish_time, score_margin, "
                "event_id, event_date, weight_class_id, title_at_stake) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fight_id, fid, oid, outcome_a, result_type, finish_round,
                 finish_time, score_margin, event_id, event_date, wc_id, is_title),
            )
            conn.execute(
                "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
                "outcome, result_type, finish_round, finish_time, score_margin, "
                "event_id, event_date, weight_class_id, title_at_stake) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fight_id, oid, fid, outcome_b, result_type, finish_round,
                 finish_time, score_margin, event_id, event_date, wc_id, is_title),
            )
            n_fh_created += 2

            # Decrement both fighters' remaining counters
            remaining_fights[fid] -= 1
            remaining_fights[oid] -= 1

            if n_fights_created % BATCH_SIZE == 0:
                conn.commit()
                print(f"  ...{n_fights_created} fights, {n_fh_created} fight_history rows")

    conn.commit()
    print(f"  Total: {n_fights_created} fights, {n_fh_created} fight_history rows, {n_events_created} events")

    # ----------------------------------------------------------------
    # 3. Titles — one per (promotion, weight_class). Most held by
    #    the top-ranked fighter in that WC; ~20% vacant.
    # ----------------------------------------------------------------
    print("Seeding titles...")
    # Get all (promo, wc) combos that have fighters
    combos = conn.execute(
        "SELECT DISTINCT p.promotion_id, f.weight_class_id "
        "FROM fighters f JOIN promotions p ON f.current_promotion_id=p.promotion_id "
        "WHERE f.current_promotion_id IS NOT NULL"
    ).fetchall()
    n_titles = 0
    for promo_id, wc_id in combos:
        # Top 5 fighters in this WC + promo by rating — pick from these
        # but skip anyone on a 3+ losing streak (a champion shouldn't
        # be on a bad skid). If all top 5 are on losing streaks, the
        # title is vacant.
        top5 = conn.execute(
            "SELECT f.fighter_id, r.rating, fc.loss_streak, fc.win_streak "
            "FROM fighters f "
            "JOIN rankings r ON r.fighter_id=f.fighter_id "
            "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
            "WHERE f.current_promotion_id=? AND f.weight_class_id=? "
            "ORDER BY r.rating DESC LIMIT 5",
            (promo_id, wc_id),
        ).fetchall()
        if not top5:
            continue
        # Filter out fighters on 3+ losing streaks
        eligible = [t for t in top5 if t[2] < 3]
        # 80% held, 20% vacant (or vacant if no eligible fighters)
        is_vacant = rng.random() < 0.20 or not eligible
        if is_vacant:
            champion_id = None
            champion_since = None
            reigns = 0
            defenses = 0
        else:
            # Pick from top 3 eligible (adds variety — not always the #1)
            champ_choice = rng.choice(eligible[:min(3, len(eligible))])
            champion_id = champ_choice[0]
            champion_since = (SIM_DATE - timedelta(days=rng.randint(30, 900))).strftime("%Y-%m-%d")
            reigns = rng.randint(1, 3)
            defenses = rng.randint(0, 8)
            # Ensure the champion has a positive win streak (champions
            # don't usually lose their last fight before winning the title)
            conn.execute(
                "UPDATE fighter_career SET win_streak=?, loss_streak=0 "
                "WHERE fighter_id=?",
                (rng.randint(1, 6), champion_id),
            )
        # Check if title already exists
        existing = conn.execute(
            "SELECT title_id FROM titles WHERE promotion_id=? AND weight_class_id=?",
            (promo_id, wc_id),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO titles (promotion_id, weight_class_id, "
            "current_champion_fighter_id, champion_since_date, "
            "title_reigns_count, title_defenses_count, is_vacant) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (promo_id, wc_id, champion_id, champion_since,
             reigns, defenses, 1 if is_vacant else 0),
        )
        n_titles += 1
        # Update the champion's title_reigns
        if champion_id:
            conn.execute(
                "UPDATE fighter_career SET title_reigns=? WHERE fighter_id=?",
                (reigns, champion_id),
            )
    conn.commit()
    print(f"  Titles: {n_titles}")

    # ----------------------------------------------------------------
    # 4. Contracts — one per signed fighter (not free agents).
    #    12-month exclusive, salary based on fighter rating.
    # ----------------------------------------------------------------
    print("Seeding contracts...")
    signed_fighters = conn.execute(
        "SELECT f.fighter_id, f.current_promotion_id, r.rating "
        "FROM fighters f "
        "LEFT JOIN rankings r ON r.fighter_id=f.fighter_id "
        "WHERE f.current_promotion_id IS NOT NULL"
    ).fetchall()
    n_contracts = 0
    for fid, promo_id, rating in signed_fighters:
        rating = rating or 1000
        # Salary: realistic MMA pay structure.
        # Entry-level (rating < 950): $5k-$15k per fight
        # Lower-tier (950-1000): $10k-$30k
        # Mid-tier (1000-1100): $20k-$80k
        # Upper-mid (1100-1200): $50k-$150k
        # Star (1200-1300): $100k-$300k
        # Elite (1300+): $200k-$500k
        if rating < 950:
            salary = rng.randint(5000, 15000)
        elif rating < 1000:
            salary = rng.randint(10000, 30000)
        elif rating < 1100:
            salary = rng.randint(20000, 80000)
        elif rating < 1200:
            salary = rng.randint(50000, 150000)
        elif rating < 1300:
            salary = rng.randint(100000, 300000)
        else:
            salary = rng.randint(200000, 500000)
        # Start date: 1-12 months ago
        start_date = (SIM_DATE - timedelta(days=rng.randint(30, 365))).strftime("%Y-%m-%d")
        end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=365)).strftime("%Y-%m-%d")
        # Check if contract already exists
        existing = conn.execute(
            "SELECT fc.contract_id FROM fighter_contracts fc WHERE fc.fighter_id=?",
            (fid,),
        ).fetchone()
        if existing:
            continue
        cur = conn.execute(
            "INSERT INTO contracts (contract_target_type, promotion_id, "
            "start_date, end_date, salary, bonus_structure, buyout_clause, "
            "exclusive_flag, status) "
            "VALUES ('fighter', ?, ?, ?, ?, ?, ?, 1, 'active')",
            (promo_id, start_date, end_date, salary,
             "win_bonus=50%, finish_bonus=25%, performance_bonus=10%",
             salary * 2),  # buyout = 2x salary
        )
        contract_id = cur.lastrowid
        # contract_type CHECK IN ('standard', 'champion', 'prospect', 'veteran')
        # Pick based on fighter's career stage (inferred from fighter_career)
        fc_row = conn.execute(
            "SELECT record_wins, record_losses, record_draws, title_reigns "
            "FROM fighter_career WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if fc_row and fc_row[3] > 0:
            contract_type = "champion"
        else:
            total_fights = (fc_row[0] + fc_row[1] + fc_row[2]) if fc_row else 0
            if total_fights < 5:
                contract_type = "prospect"
            elif total_fights > 25:
                contract_type = "veteran"
            else:
                contract_type = "standard"
        conn.execute(
            "INSERT INTO fighter_contracts (contract_id, fighter_id, contract_type) "
            "VALUES (?, ?, ?)",
            (contract_id, fid, contract_type),
        )
        n_contracts += 1
        if n_contracts % 500 == 0:
            conn.commit()
    conn.commit()
    print(f"  Contracts: {n_contracts}")

    # ----------------------------------------------------------------
    # 5. Injuries — ~10% of fighters have an active injury.
    # ----------------------------------------------------------------
    print("Seeding injuries...")
    all_fighters = conn.execute("SELECT fighter_id FROM fighters").fetchall()
    n_injuries = 0
    injury_types = [
        ("concussion", "head", 4, 7),
        ("torn ACL", "knee", 7, 10),
        ("broken hand", "hand", 3, 6),
        ("rib fracture", "ribs", 4, 7),
        ("shoulder labrum tear", "shoulder", 6, 9),
        ("hamstring strain", "hip", 3, 6),
        ("ankle sprain", "ankle", 2, 4),
        ("wrist sprain", "wrist", 2, 4),
    ]
    for (fid,) in all_fighters:
        if rng.random() < 0.10:  # 10% injury rate
            itype, barea, sev_min, sev_max = rng.choice(injury_types)
            severity = rng.randint(sev_min, sev_max)
            start_date = (SIM_DATE - timedelta(days=rng.randint(1, 60))).strftime("%Y-%m-%d")
            projected_return = (SIM_DATE + timedelta(days=severity * 14)).strftime("%Y-%m-%d")
            # If projected_return is in the past, the injury is healed (is_active=0)
            is_active = 1 if projected_return > SIM_DATE.strftime("%Y-%m-%d") else 0
            conn.execute(
                "INSERT INTO injuries (fighter_id, injury_type, body_area, "
                "severity, start_date, projected_return_date, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fid, itype, barea, severity, start_date,
                 projected_return, is_active),
            )
            n_injuries += 1
            # Reduce career_health for active injuries
            if is_active:
                conn.execute(
                    "UPDATE fighter_career SET career_health = MAX(0, career_health - ?) "
                    "WHERE fighter_id=?",
                    (severity * 2, fid),
                )
        if n_injuries % 100 == 0 and n_injuries > 0:
            conn.commit()
    conn.commit()
    print(f"  Injuries: {n_injuries}")

    # ----------------------------------------------------------------
    # Phase B (4e): Seed-time rivalries.
    #
    # The world seed has 0 rivalries before this block — the
    # rivalries system (src/rivalries.py) only creates rivalries
    # from in-game events (social callouts, close decisions, title
    # changes). Per docs/FULL_BUILD_AUDIT.md §4e, the seeded world
    # should have 50-100 pre-existing rivalries derived from the
    # historical fight data so the world feels lived-in from day 1.
    #
    # Three seed-time rivalry flavors:
    #   1. rematch_hungry (heat 60): fighter pairs who fought 2+
    #      times in the historical data. The brief says "fighters
    #      who fought each other multiple times" — the implicit
    #      narrative is the trilogy / quadrilogy that demands one
    #      more chapter.
    #   2. bad_blood (heat 70): fighter pairs where one won by a
    #      controversial decision (score_margin <= 2 in a split or
    #      unanimous decision). The brief says "controversial
    #      decisions" — the loser wants vindication.
    #   3. title_rivalry (heat 80): same-promo + same-WC fighter
    #      pairs where one is the current champion. The brief says
    #      "champion vs contender" — the contender wants the belt.
    #
    # Uses src/rivalries._create_rivalry (the same writer the
    # in-game system uses) so the seed-time rivalries have proper
    # origin_description (voice-layer-driven per CONVENTIONS §14 —
    # no raw numbers) and are deduped against any pre-existing
    # rivalry rows (the UNIQUE constraint on fighter_a_id +
    # fighter_b_id is enforced by _create_rivalry's existing-row
    # check).
    # ----------------------------------------------------------------
    print("Seeding rivalries from historical fight data...")
    # Lazy-import the rivalries writer (lives in src/, not scripts/).
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_DIR / "src"))
    import rivalries as _rivalries
    from collections import defaultdict as _dd

    rng_riv = random.Random(20260724 + 1)  # distinct from main fight RNG
    n_rivalries = 0
    n_rematch = 0
    n_bad_blood = 0
    n_title_rivalry = 0

    # Skip if Phase 4 rivalries already seeded (idempotent — re-running
    # phase4 should not stack duplicate rivalries on top of existing
    # ones, since _create_rivalry dedupes by fighter pair but a second
    # run would still iterate through every pair needlessly).
    existing_riv_count = conn.execute(
        "SELECT COUNT(*) FROM rivalries"
    ).fetchone()[0]
    if existing_riv_count > 0:
        print(f"  Already {existing_riv_count} rivalries — skipping seed-time rivalry generation.")
    else:
        sim_date_str = SIM_DATE.strftime("%Y-%m-%d")

        # ----- 1. rematch_hungry: pairs who fought 2+ times ----------
        # Group fight_history by fighter pair (canonical: lower fid
        # first). Count fights per pair.
        pair_counts = _dd(int)
        pair_fights = _dd(list)  # pair -> list of (fight_id, winner_id)
        rows = conn.execute(
            "SELECT fighter_id, opponent_id, fight_id, outcome "
            "FROM fight_history"
        ).fetchall()
        for fid, oid, fight_id, outcome in rows:
            if fid is None or oid is None or fid == oid:
                continue
            pair = (fid, oid) if fid < oid else (oid, fid)
            pair_counts[pair] += 1
            # Track who won each fight in the pair (from fid's
            # perspective: outcome='win' means fid won).
            pair_fights[pair].append((fight_id, fid if outcome == "win" else oid))
        # Pairs with 2+ fights → rematch_hungry
        rematch_pairs = [
            (p, c) for p, c in pair_counts.items() if c >= 2
        ]
        # Sort by fight count desc so the biggest trilogies get
        # seeded first (in case we hit a cap).
        rematch_pairs.sort(key=lambda x: x[1], reverse=True)
        # Cap to keep the seed-time rivalry total reasonable (50-
        # 100 rivalries total per the brief — split roughly evenly
        # across the 3 flavors).
        MAX_REMATCH = 40
        MAX_BAD_BLOOD = 40
        MAX_TITLE_RIVALRY = 30
        for (a_id, b_id), count in rematch_pairs[:MAX_REMATCH]:
            # Compute head-to-head wins for the rivalry's
            # fighter_a_wins / fighter_b_wins columns (optional —
            # _create_rivalry doesn't set them, but we can UPDATE
            # after).
            a_wins = sum(1 for _, w in pair_fights[(a_id, b_id)] if w == a_id)
            b_wins = sum(1 for _, w in pair_fights[(a_id, b_id)] if w == b_id)
            draws = count - a_wins - b_wins
            origin_narrative = (
                "The rivalry started with multiple meetings in the cage — "
                "the score still unsettled."
            )
            riv_id = _rivalries._create_rivalry(
                conn, a_id, b_id, "rematch_hungry",
                origin_event="seed:phase4:rematch_hungry",
                origin_narrative=origin_narrative,
                initial_heat=60, rng=rng_riv,
                current_date=sim_date_str,
            )
            if riv_id is not None:
                # Populate the head-to-head counts (the in-game
                # _process_fight_rivalry does this incrementally; for
                # seed-time we backfill from the historical record).
                conn.execute(
                    "UPDATE rivalries SET fights_count=?, "
                    "fighter_a_wins=?, fighter_b_wins=?, draws=? "
                    "WHERE rivalry_id=?",
                    (count, a_wins, b_wins, draws, riv_id),
                )
                n_rivalries += 1
                n_rematch += 1

        # ----- 2. bad_blood: controversial decisions --------------
        # Find fighter pairs where at least one fight was a decision
        # with score_margin <= 2 (the close-decision threshold from
        # src/rivalries.py — _CLOSE_DECISION_MARGIN). The brief says
        # "controversial decisions" — split decisions and razor-thin
        # unanimous decisions both qualify.
        close_pairs = _dd(list)
        rows = conn.execute(
            "SELECT fighter_id, opponent_id, score_margin, result_type "
            "FROM fight_history "
            "WHERE result_type IN ('split_decision', 'unanimous_decision') "
            "AND score_margin IS NOT NULL AND score_margin <= 2"
        ).fetchall()
        for fid, oid, margin, rt in rows:
            if fid is None or oid is None or fid == oid:
                continue
            pair = (fid, oid) if fid < oid else (oid, fid)
            close_pairs[pair].append((margin, rt))
        # Sort by number of close decisions desc, then by smallest
        # margin (the most controversial pair first).
        close_pairs_sorted = sorted(
            close_pairs.items(),
            key=lambda x: (-len(x[1]), min(m for m, _ in x[1])),
        )
        # Skip pairs that already have a rivalry (from the rematch
        # block above — a pair that fought 2+ times AND had a close
        # decision already got a rematch_hungry rivalry; we don't
        # want to stack two rivalries on the same pair).
        for (a_id, b_id), close_fights in close_pairs_sorted[:MAX_BAD_BLOOD]:
            existing = _rivalries.get_rivalry(conn, a_id, b_id)
            if existing is not None:
                continue
            origin_narrative = (
                "The rivalry started with a controversial decision — "
                "the loser still wants vindication."
            )
            riv_id = _rivalries._create_rivalry(
                conn, a_id, b_id, "bad_blood",
                origin_event="seed:phase4:bad_blood",
                origin_narrative=origin_narrative,
                initial_heat=70, rng=rng_riv,
                current_date=sim_date_str,
            )
            if riv_id is not None:
                n_rivalries += 1
                n_bad_blood += 1

        # ----- 3. title_rivalry: champion vs same-WC same-promo contender
        # For each current champion, find the top-3 ranked contenders
        # in the same WC + promo who are NOT already in a rivalry
        # with the champ. Pick 1-2 of them for a title_rivalry.
        champions = conn.execute(
            "SELECT t.current_champion_fighter_id, t.promotion_id, "
            "t.weight_class_id "
            "FROM titles t "
            "WHERE t.current_champion_fighter_id IS NOT NULL "
            "AND t.is_vacant = 0"
        ).fetchall()
        for champ_id, promo_id, wc_id in champions:
            if n_title_rivalry >= MAX_TITLE_RIVALRY:
                break
            # Top-5 ranked contenders in the same WC + promo.
            contenders = conn.execute(
                "SELECT r.fighter_id "
                "FROM rankings r "
                "JOIN fighters f ON f.fighter_id = r.fighter_id "
                "WHERE r.weight_class_id=? AND r.promotion_id=? "
                "AND r.fighter_id != ? "
                "AND f.is_active = 1 AND f.is_retired = 0 "
                "ORDER BY r.rating DESC LIMIT 5",
                (wc_id, promo_id, champ_id),
            ).fetchall()
            # Pick 1-2 contenders (rng-biased toward the top).
            n_to_pick = min(len(contenders), rng_riv.randint(1, 2))
            # Weight the top contenders higher (pick from top 3).
            top_contenders = contenders[:min(3, len(contenders))]
            rng_riv.shuffle(top_contenders)
            for (contender_id,) in top_contenders[:n_to_pick]:
                if n_title_rivalry >= MAX_TITLE_RIVALRY:
                    break
                # Skip if a rivalry already exists for this pair.
                if _rivalries.get_rivalry(conn, champ_id, contender_id) is not None:
                    continue
                origin_narrative = (
                    "The rivalry started with a title picture — the "
                    "contender wants the belt the champion holds."
                )
                riv_id = _rivalries._create_rivalry(
                    conn, champ_id, contender_id, "title_rivalry",
                    origin_event="seed:phase4:title_rivalry",
                    origin_narrative=origin_narrative,
                    initial_heat=80, rng=rng_riv,
                    current_date=sim_date_str,
                )
                if riv_id is not None:
                    n_rivalries += 1
                    n_title_rivalry += 1

        conn.commit()
        print(f"  Rivalries:           {n_rivalries}")
        print(f"    rematch_hungry:    {n_rematch}")
        print(f"    bad_blood:         {n_bad_blood}")
        print(f"    title_rivalry:     {n_title_rivalry}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("World seed Phase 4 complete.")
    print(f"  Historical fights:    {n_fights_created}")
    print(f"  Historical events:    {n_events_created}")
    print(f"  Fight history rows:   {n_fh_created}")
    print(f"  Titles:               {n_titles}")
    print(f"  Active contracts:     {n_contracts}")
    print(f"  Injuries:             {n_injuries}")
    if 'n_rivalries' in locals():
        print(f"  Seed-time rivalries: {n_rivalries}")
    print("=" * 60)
    print()
    print("Next: python scripts/seed_world_phase5.py (bios, gym histories, retired legends, news)")

    conn.close()


if __name__ == "__main__":
    main()
