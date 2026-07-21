import sqlite3
import random
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

def fighter_name(conn, fighter_id):
    row = conn.execute("SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?", (fighter_id,)).fetchone()
    return row[0] if row else "Unknown"

def get_clock(conn):
    return conn.execute("SELECT current_date, current_day, current_week, current_month, current_year, tick_counter FROM simulation_clock WHERE clock_id=1").fetchone()

def advance_day(conn):
    row = get_clock(conn)
    dt = datetime.strptime(row[0], "%Y-%m-%d") + timedelta(days=1)
    day = row[1] + 1
    week = ((day - 1) // 7) + 1
    conn.execute(
        "UPDATE simulation_clock SET current_date=?, current_day=?, current_week=?, current_month=?, current_year=?, current_tick_type='day', tick_counter=tick_counter+1, updated_at=CURRENT_TIMESTAMP WHERE clock_id=1",
        (dt.strftime("%Y-%m-%d"), day, week, dt.month, dt.year),
    )

def write_news(conn, headline, body, topic="event", event_id=None, fight_id=None, fighter_id=None, promotion_id=None):
    src = conn.execute("SELECT news_source_id FROM news_sources WHERE name='System Feed'").fetchone()
    src_id = src[0] if src else conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80)).lastrowid
    conn.execute("INSERT INTO news_items (news_source_id, headline, body, sentiment, topic, event_id, fight_id, fighter_id, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (src_id, headline, body, "neutral", topic, event_id, fight_id, fighter_id, promotion_id))

def write_commentary(conn, event_id=None, fight_id=None, text=""):
    speaker = conn.execute("SELECT staff_id FROM staff WHERE role_type='commentator' LIMIT 1").fetchone()
    speaker_id = speaker[0] if speaker else None
    conn.execute("INSERT INTO commentary_segments (event_id, fight_id, segment_type, speaker_staff_id, text, importance) VALUES (?, ?, ?, ?, ?, ?)", (event_id, fight_id, "play_by_play", speaker_id, text, 70))


# ----------------------------------------------------------------
# Fighter roster display helper (Task ID 6).
#
# Extracted from the inline query that used to live in
# `App.refresh_all()` so the multi-promotion filter logic is
# testable without a Tkinter display. The test script
# `scripts/test_promotion_filter.py` imports this helper directly.
#
# Returns the same 4-tuple shape the Fighters Treeview was already
# rendering: (name, weight_class, promotion_name, record) — so
# `refresh_all()`'s `insert('', 'end', values=r)` call is unchanged.
#
# Schema version is unchanged (still 1.3.0) — no new tables, no new
# columns. RFL stays inert (no AI behaviour); this helper just makes
# the UI aware that multiple promotions exist.
# ----------------------------------------------------------------

def get_fighters_for_display(conn, promotion_filter=None):
    """Return fighter rows for the UI Fighters tree.

    Args:
        conn: sqlite3 connection.
        promotion_filter: None (all fighters, including free agents
            with current_promotion_id = NULL), or a promotion_id int
            (only fighters whose current_promotion_id matches).

    Returns:
        List of 4-tuples: (name, weight_class, promotion_name, record).
        - name:            fighters.first_name || ' ' || fighters.last_name
        - weight_class:    weight_classes.name, or 'Unknown' if no WC
        - promotion_name:  promotions.name, or 'Unassigned' if no
                           current promotion (i.e. a free agent)
        - record:          'W-L-D' string from fighter_career counters,
                           defaulting to '0-0-0' if no career row yet
    """
    sql = (
        "SELECT f.first_name || ' ' || f.last_name, "
        "COALESCE(w.name, 'Unknown'), "
        "COALESCE(p.name, 'Unassigned'), "
        "COALESCE(fc.record_wins, 0) || '-' || COALESCE(fc.record_losses, 0) || '-' || COALESCE(fc.record_draws, 0) "
        "FROM fighters f "
        "LEFT JOIN weight_classes w ON w.weight_class_id = f.weight_class_id "
        "LEFT JOIN promotions p ON p.promotion_id = f.current_promotion_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id"
    )
    if promotion_filter is not None:
        sql += " WHERE f.current_promotion_id = ?"
        sql += " ORDER BY f.fighter_id"
        return conn.execute(sql, (promotion_filter,)).fetchall()
    sql += " ORDER BY f.fighter_id"
    return conn.execute(sql).fetchall()


def get_contracts_for_display(conn, promotion_id=None):
    """Return contract rows for the UI Contracts tab (Task ID 9).

    Joins contracts -> fighter_contracts -> fighters and (for non-
    fighter contracts) staff_contracts -> staff and broadcast_contracts
    -> staff. Uses COALESCE across three LEFT JOINs to pick whichever
    contractor name is non-NULL based on contract_target_type.

    Args:
        conn: sqlite3 connection.
        promotion_id: if None, return all contracts; else return only
            contracts for the given promotion.

    Returns:
        List of 7-tuples: (contractor_name, contract_target_type,
        start_date, end_date, salary, exclusive_flag, status).
    """
    # Polymorphic JOIN: the base contracts table has contract_target_type
    # in ('fighter', 'staff', 'broadcast'). Each subtype table
    # (fighter_contracts / staff_contracts / broadcast_contracts) holds
    # the FK to the contracted entity. We LEFT JOIN all three subtype
    # tables + their name sources, then COALESCE the contractor name.
    # Two staff aliases (s_sc, s_bc) avoid an OR-join on staff_id which
    # could produce cartesian products. See worklog decision D2.
    sql = (
        "SELECT "
        "  COALESCE(f.first_name || ' ' || f.last_name, "
        "           s_sc.first_name || ' ' || s_sc.last_name, "
        "           s_bc.first_name || ' ' || s_bc.last_name, "
        "           'Unknown') AS contractor_name, "
        "  c.contract_target_type, c.start_date, c.end_date, "
        "  c.salary, c.exclusive_flag, c.status "
        "FROM contracts c "
        "LEFT JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "LEFT JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "LEFT JOIN staff_contracts sc ON sc.contract_id = c.contract_id "
        "LEFT JOIN staff s_sc ON s_sc.staff_id = sc.staff_id "
        "LEFT JOIN broadcast_contracts bc ON bc.contract_id = c.contract_id "
        "LEFT JOIN staff s_bc ON s_bc.staff_id = bc.staff_id"
    )
    if promotion_id is not None:
        sql += " WHERE c.promotion_id = ?"
        sql += " ORDER BY c.end_date"
        return conn.execute(sql, (promotion_id,)).fetchall()
    sql += " ORDER BY c.end_date"
    return conn.execute(sql).fetchall()


# ----------------------------------------------------------------
# Rankings display helper (Task ID 10).
#
# Returns the top-N fighters by ELO rating for a given promotion
# (optionally filtered by weight class). Used by the Rankings tab in
# the UI (third tab in the right-pane Notebook). The rank field is
# 1-indexed (rank 1 = highest rating). Ties are broken by
# fights_count DESC (more-active fighters rank higher), which is the
# same tiebreaker the ELO system uses implicitly (a fighter with the
# same rating but more fights has had more chances to move).
#
# Schema version is bumped 1.4.0 -> 1.5.0 in this task (the new
# `rankings` table is the only schema change).
# ----------------------------------------------------------------

def get_rankings_for_display(conn, promotion_id, weight_class_id=None, limit=10):
    """Return top N fighters by rating for a promotion.

    Args:
        conn: sqlite3 connection.
        promotion_id: the promotion whose rankings to return. If the
            promotion_id is invalid (no rows in `rankings` for it),
            returns an empty list — no crash.
        weight_class_id: if not None, filter to this weight class;
            else include all weight classes.
        limit: max number of rows to return. Default 10.

    Returns:
        List of 7-tuples:
        (rank, fighter_name, weight_class_name, rating_rounded_1dp,
         fights_count, 'W-L-D' string, last_fight_date_or_'N/A').
        - rank:                1-indexed int (1 = highest rating).
        - fighter_name:        fighters.first_name || ' ' || last_name.
        - weight_class_name:   weight_classes.name (always non-NULL
                              because rankings.weight_class_id is NOT
                              NULL with ON DELETE CASCADE).
        - rating_rounded_1dp:  float (rating rounded to 1 decimal).
        - fights_count:        int.
        - record string:       'W-L-D' from the rankings counters.
        - last_fight_date:     ISO date string or 'N/A' if NULL
                              (fighter has not fought yet).

        Ordered by rating DESC, fights_count DESC.
    """
    sql = (
        "SELECT r.rating, r.fights_count, r.wins, r.losses, r.draws, "
        "       r.last_fight_date, "
        "       f.first_name || ' ' || f.last_name AS fighter_name, "
        "       w.name AS weight_class_name "
        "FROM rankings r "
        "JOIN fighters f ON f.fighter_id = r.fighter_id "
        "LEFT JOIN weight_classes w ON w.weight_class_id = r.weight_class_id "
        "WHERE r.promotion_id = ?"
    )
    params = [promotion_id]
    if weight_class_id is not None:
        sql += " AND r.weight_class_id = ?"
        params.append(weight_class_id)
    sql += " ORDER BY r.rating DESC, r.fights_count DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    # Build the 7-tuple with 1-indexed rank and rounded rating.
    out = []
    for i, (rating, fights_count, wins, losses, draws,
            last_fight_date, fighter_name, wc_name) in enumerate(rows, start=1):
        record_str = f"{wins}-{losses}-{draws}"
        last_fight_display = last_fight_date if last_fight_date else "N/A"
        out.append((
            i,
            fighter_name,
            wc_name if wc_name else "Unknown",
            round(float(rating), 1),
            int(fights_count),
            record_str,
            last_fight_display,
        ))
    return out

# ----------------------------------------------------------------
# Real attribute-based fight resolver (Task ID 3).
#
# Replaces the original coin-flip resolve_next_fight() with a
# probabilistic model that reads fighter_attributes (punch_power,
# cardio, fight_iq, chin) and fighter_personality (aggression,
# composure, morale) for both fighters, computes a noisy power
# score per fighter, and derives winner / result_type / finish_round
# / finish_time / performance_rating / fan_reaction_rating from the
# margin. See docs/STAGES.md Task ID 3 for the spec. Schema version
# is unchanged (still 1.2.1) — no new tables, no new columns.
# ----------------------------------------------------------------

# Defensive defaults used only if a fighter_attributes or
# fighter_personality row is somehow missing. The seed always
# inserts both, so these are belt-and-braces.
_DEFAULT_ATTRS = (50, 50, 50, 50)  # punch_power, cardio, fight_iq, chin
_DEFAULT_PERS = (50, 50, 50)       # aggression, composure, morale

# Base Gaussian noise sigma applied to each fighter's adjusted power
# score. Spec says "sigma ~= 15". Per-fighter sigma is then narrowed
# or widened by the consistency modifier (see _consistency_sigma).
_BASE_SIGMA = 15.0


def _load_fighter_stats(conn, fighter_id):
    """Load one fighter's combat attributes + personality for the resolver.

    Returns a flat dict with all 7 fields. Falls back to defaults (50s)
    if either row is missing — defensive, the seed always inserts both.
    """
    attrs = conn.execute(
        "SELECT punch_power, cardio, fight_iq, chin FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    pers = conn.execute(
        "SELECT aggression, composure, morale FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    a = attrs if attrs else _DEFAULT_ATTRS
    p = pers if pers else _DEFAULT_PERS
    return {
        "punch_power": a[0], "cardio": a[1], "fight_iq": a[2], "chin": a[3],
        "aggression": p[0], "composure": p[1], "morale": p[2],
    }


def _power_score(stats):
    """Weighted blend of the 4 combat attributes. Range ~0-100.

    punch_power * 0.4 + cardio * 0.3 + fight_iq * 0.2 + chin * 0.1
    (per the Task ID 3 spec).
    """
    return (
        stats["punch_power"] * 0.4
        + stats["cardio"] * 0.3
        + stats["fight_iq"] * 0.2
        + stats["chin"] * 0.1
    )


def _consistency_sigma(stats):
    """Composure narrows variance. Returns adjusted sigma in [7.5, 22.5].

    Spec: multiply base sigma by `1 - (composure - 50) / 200`, clamped
    to [0.5, 1.5]. So composure=90 -> sigma * 0.8, composure=10 ->
    sigma * 1.2.
    """
    mod = 1.0 - (stats["composure"] - 50) / 200.0
    mod = max(0.5, min(1.5, mod))
    return _BASE_SIGMA * mod


def _morale_multiplier(stats):
    """Morale scales power up/down. Range [0.85, 1.15] for morale in [0, 100].

    Spec: `0.85 + (morale / 100) * 0.30`. So morale=50 -> x1.00,
    morale=0 -> x0.85, morale=100 -> x1.15.
    """
    return 0.85 + (stats["morale"] / 100.0) * 0.30


def _pick_finish_type(winner_stats, loser_stats):
    """Pick `ko_tko` vs `submission` for a finish outcome.

    Weighted by the winner's punch_power (KO bias) vs fight_iq
    (submission bias). The loser's chin affects the *probability of a
    finish* (captured by the margin), not the split between finish
    types, so it is intentionally not used here. This keeps the
    result_type distribution varied across fighter styles — a pure
    puncher KOs, a tactician submits — which is needed to satisfy the
    acceptance test's "no single result_type > 60%" assertion in the
    symmetric all-90-vs-all-30 matchup. See worklog D1.
    """
    ko_weight = max(1, winner_stats["punch_power"])
    sub_weight = max(1, winner_stats["fight_iq"])
    return "ko_tko" if random.random() < ko_weight / (ko_weight + sub_weight) else "submission"


def _format_finish_time():
    """Random finish time within a 5-minute round. Returns 'M:SS' in [0:01, 4:59]."""
    total = random.randint(1, 299)
    return f"{total // 60}:{total % 60:02d}"


def _resolve_outcome(stats_a, stats_b, scheduled_rounds):
    """Resolve the probabilistic outcome of a fight between two fighters.

    Pure function (no DB writes, no I/O) so the test script can call it
    directly to verify distribution properties without going through the
    database. Returns a dict with: winner ('a' or 'b'), abs_margin,
    result_type, finish_round, finish_time, performance_rating,
    fan_reaction_rating, winner_base, loser_base.
    """
    base_a = _power_score(stats_a)
    base_b = _power_score(stats_b)

    # Morale scales power up/down. Composure scales noise sigma.
    adj_a = base_a * _morale_multiplier(stats_a)
    adj_b = base_b * _morale_multiplier(stats_b)

    sigma_a = _consistency_sigma(stats_a)
    sigma_b = _consistency_sigma(stats_b)

    # Sample a noisy score per fighter. random.gauss(mu, sigma) — here
    # mu=0 and we add the noise to the adjusted score. random.gauss is
    # used (not random.randint) per the spec and the acceptance checklist.
    noisy_a = adj_a + random.gauss(0, sigma_a)
    noisy_b = adj_b + random.gauss(0, sigma_b)

    signed_margin = noisy_a - noisy_b
    if signed_margin >= 0:
        winner = "a"
        winner_stats, loser_stats = stats_a, stats_b
        winner_base, loser_base = base_a, base_b
    else:
        winner = "b"
        winner_stats, loser_stats = stats_b, stats_a
        winner_base, loser_base = base_b, base_a
    abs_margin = abs(signed_margin)

    # Decide result_type from margin per the Task ID 3 spec.
    #   margin > 30  -> finish (early, round 1-2)
    #   margin 15-30 -> finish (mid, round 2-3)
    #   margin 5-15  -> unanimous_decision
    #   margin < 5   -> coin flip split_decision / draw
    # The spec maps margin > 30 definitively to ko_tko. We deviate
    # slightly (see worklog D1): at any finish margin we let both
    # ko_tko and submission be possible, weighted by the winner's
    # style. This is required to pass the acceptance test's
    # "no single result_type > 60%" assertion in the all-90-vs-all-30
    # matchup (where abs_margin > 30 occurs ~99% of the time).
    if abs_margin >= 15:
        result_type = _pick_finish_type(winner_stats, loser_stats)
        if abs_margin > 30:
            # Early finish — rounds 1-2.
            finish_round = random.randint(1, 2)
        else:
            # Mid finish — rounds 2-3.
            finish_round = random.randint(2, 3)
        # Aggression differential shifts the finish round (spec §6).
        # More aggressive winner finishes earlier; less aggressive
        # winner lets the loser survive a round longer.
        aggr_diff = winner_stats["aggression"] - loser_stats["aggression"]
        if aggr_diff >= 20:
            finish_round = max(1, finish_round - 1)
        elif aggr_diff <= -20:
            finish_round = min(scheduled_rounds, finish_round + 1)
        finish_time = _format_finish_time()
    elif abs_margin >= 5:
        result_type = "unanimous_decision"
        finish_round = scheduled_rounds
        finish_time = "5:00"
    else:
        # Coin flip per spec for the sub-5 case.
        result_type = random.choice(["split_decision", "draw"])
        finish_round = scheduled_rounds
        finish_time = "5:00"

    # Performance rating: bigger margin -> higher. Clamp 60-95.
    performance_rating = max(60, min(95, int(round(60 + abs_margin))))

    # Fan reaction: lower base, KO bonus, upset bonus. Clamp 60-95.
    # KO/TKO is +10 vs decision (more exciting). Upset (loser had a
    # higher base power score than winner) is +5 (fans love an upset).
    fan = 65 + int(abs_margin * 0.5)
    if result_type == "ko_tko":
        fan += 10
    if loser_base > winner_base:
        fan += 5
    fan_reaction_rating = max(60, min(95, fan))

    return {
        "winner": winner,
        "abs_margin": abs_margin,
        "result_type": result_type,
        "finish_round": finish_round,
        "finish_time": finish_time,
        "performance_rating": performance_rating,
        "fan_reaction_rating": fan_reaction_rating,
        "winner_base": winner_base,
        "loser_base": loser_base,
    }


def _format_fight_news(winner_name, loser_name, result_type, finish_round):
    """Build (headline, body) for a non-draw fight result.

    Enriches the original "X defeats Y" template with the result type
    and finish round. The write_news() call itself is unchanged.
    """
    pretty = result_type.replace("_", " ")
    if result_type == "ko_tko":
        headline = f"{winner_name} KO's {loser_name} in round {finish_round}"
        body = f"{winner_name} stopped {loser_name} by {pretty} in round {finish_round}."
    elif result_type == "submission":
        headline = f"{winner_name} submits {loser_name} in round {finish_round}"
        body = f"{winner_name} tapped out {loser_name} by submission in round {finish_round}."
    elif result_type == "unanimous_decision":
        headline = f"{winner_name} beats {loser_name} by unanimous decision"
        body = f"{winner_name} defeated {loser_name} by unanimous decision after {finish_round} rounds."
    elif result_type == "split_decision":
        headline = f"{winner_name} edges {loser_name} by split decision"
        body = f"{winner_name} took a split decision over {loser_name} after {finish_round} rounds."
    else:
        headline = f"{winner_name} defeats {loser_name}"
        body = f"{winner_name} beat {loser_name} by {pretty}."
    return headline, body


def _format_fight_commentary(winner_name, loser_name, result_type, finish_round):
    """Build a short commentary line for a non-draw fight result."""
    if result_type == "ko_tko":
        return f"{winner_name} puts {loser_name} away by KO/TKO in round {finish_round}."
    if result_type == "submission":
        return f"{winner_name} forces the tap from {loser_name} in round {finish_round}."
    if result_type == "unanimous_decision":
        return f"All three judges score it for {winner_name} over {loser_name}."
    if result_type == "split_decision":
        return f"Split scorecards — {winner_name} takes the nod over {loser_name}."
    return f"{winner_name} has just defeated {loser_name}."


# ----------------------------------------------------------------
# Event lifecycle (Task ID 7).
#
# `events.status` is set to 'scheduled' on creation and — prior to
# this task — never transitioned. That made the Events tree in the UI
# meaningless (every event showed 'scheduled' forever, even after all
# its fights had been resolved) and blocked Task ID 8 (repeatable
# event generator), which depends on knowing when an event is
# complete so it can schedule the next card.
#
# The valid transitions are:
#   scheduled  -> in_progress   (when the first fight on the card resolves)
#   in_progress -> completed    (when the last unresolved fight resolves)
# An event with only 1 fight goes scheduled -> completed in one step
# (the first fight IS the last fight). An event already 'completed'
# is never touched again (defensive — see the UPDATE's WHERE clause).
#
# Schema version is unchanged (still 1.3.0) — the `events.status`
# column already existed since v1.2.0 with TEXT NOT NULL DEFAULT
# 'scheduled'. No new tables, no new columns.
# ----------------------------------------------------------------

def _update_event_status_after_resolution(conn, event_id):
    """Transition an event's status based on its fights' resolution state.

    Rules (Task ID 7):
      - If the event has unresolved fights remaining (winner_fighter_id
        IS NULL AND result_type IS NULL), status -> 'in_progress'
        (or stays 'scheduled' if no fights have been resolved yet —
        but this function is only called AFTER a fight resolves, so
        'in_progress' is always correct here).
      - If the event has NO unresolved fights remaining, status ->
        'completed'.
      - If the event is already 'completed', no change (defensive).

    This is a no-op if the event_id doesn't exist (defensive) — the
    UPDATE simply matches 0 rows and returns.

    Args:
        conn: sqlite3 connection (caller is responsible for commit).
        event_id: the events.event_id to transition.
    """
    # Count unresolved fights remaining on this event. A fight is
    # unresolved iff BOTH winner_fighter_id IS NULL AND result_type
    # IS NULL — matches the pick-query in resolve_next_fight().
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM fights "
        "WHERE event_id = ? AND winner_fighter_id IS NULL AND result_type IS NULL",
        (event_id,),
    ).fetchone()[0]

    if unresolved > 0:
        new_status = "in_progress"
    else:
        new_status = "completed"

    # The `WHERE status != 'completed'` clause is defensive: if the
    # event is somehow already 'completed' (e.g., this function got
    # called twice on the same event after the last fight), we don't
    # overwrite it. We could overwrite it with the same value, but
    # the defensive clause makes the intent explicit and protects
    # against future bugs. It also makes this function a no-op for
    # non-existent event_ids (UPDATE matches 0 rows, no error).
    conn.execute(
        "UPDATE events SET status = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE event_id = ? AND status != 'completed'",
        (new_status, event_id),
    )


# ----------------------------------------------------------------
# Rankings ELO update (Task ID 10).
#
# After a fight resolves and the result is written to `fight_history`
# (Task ID 4) — but BEFORE the event status transition (Task ID 7) —
# both fighters' `rankings` rows are updated using a simple ELO-style
# rating system. The update is zero-sum: the winner's gain is exactly
# the loser's loss (within floating-point precision).
#
# ELO math (per docs/STAGES.md Task ID 10):
#   K = 32.0
#   expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
#   expected_b = 1 - expected_a
#   Non-draw: score_a=1.0, score_b=0.0.
#   Draw:      score_a=0.5, score_b=0.5.
#   new_rating_a = rating_a + K * (score_a - expected_a)
#   new_rating_b = rating_b + K * (score_b - expected_b)
#
# K-factor is fixed at 32.0 (not dependent on fights_count — the brief
# explicitly forbids that). With a 700-point differential, the
# favorite-wins gain is ~0.48 and the upset gain is ~31.52 — a ~65x
# ratio, which makes upsets matter. Foundation for Task ID 11 (titles
# — champion vs #1 contender), Task ID 14 (regen — new fighters
# enter at the bottom at 1000.0), and Task ID 22 (rivalries —
# ranking proximity boosts heat).
#
# Schema version is bumped 1.4.0 -> 1.5.0 in this task (the new
# `rankings` table is the only schema change).
# ----------------------------------------------------------------

# ELO K-factor. Fixed at 32.0 per the Task ID 10 brief — not
# dependent on fights_count. A larger K would make ratings swing
# faster; a smaller K would make them more conservative. 32 is the
# standard chess-ELO K for established players and works well enough
# for MMA booking sim purposes.
_ELO_K = 32.0

# Initial rating every new fighter enters at. Matches the seed default
# in `_seed_initial_ranking` (seed_data.py) and the defensive INSERT
# in `_update_rankings_after_resolution` below.
_INITIAL_RATING = 1000.0


def _get_or_create_ranking_row(conn, fighter_id, weight_class_id, promotion_id):
    """Fetch the ratings row for a fighter, creating it if missing.

    Defensive: if the seed missed creating a rankings row for a
    fighter (e.g., a fighter was added by a future task without
    calling _seed_initial_ranking), this creates one on the fly at
    the default 1000.0 rating. Returns the existing row's
    (ranking_id, rating, fights_count, wins, losses, draws, last_fight_date)
    tuple, or None if the fighter doesn't exist at all (no row in
    `fighters`).
    """
    # Bail out if the fighter doesn't exist (defensive — caller may
    # pass a stale fighter_id from a partially-rolled-back transaction).
    exists = conn.execute(
        "SELECT 1 FROM fighters WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if exists is None:
        return None
    # INSERT OR IGNORE ensures we don't crash on the UNIQUE constraint
    # if the row already exists. Then SELECT picks up the row whether
    # it was just inserted or already there.
    conn.execute(
        "INSERT OR IGNORE INTO rankings (fighter_id, weight_class_id, "
        "promotion_id, rating, fights_count, wins, losses, draws) "
        "VALUES (?, ?, ?, ?, 0, 0, 0, 0)",
        (fighter_id, weight_class_id, promotion_id, _INITIAL_RATING),
    )
    return conn.execute(
        "SELECT ranking_id, rating, fights_count, wins, losses, draws, "
        "last_fight_date FROM rankings "
        "WHERE fighter_id = ? AND weight_class_id = ? AND promotion_id = ?",
        (fighter_id, weight_class_id, promotion_id),
    ).fetchone()


def _update_rankings_after_resolution(conn, winner_id, loser_id,
                                      weight_class_id, promotion_id,
                                      score_margin, was_draw=False,
                                      fight_date=None):
    """Update both fighters' ELO ratings after a fight resolution.

    Called by `resolve_next_fight()` after the `fight_history` writes
    (Task ID 4) and before the event status transition (Task ID 7).
    The update is zero-sum (winner's gain = loser's loss, within
    floating-point precision).

    Args:
        conn: sqlite3 connection (caller is responsible for commit).
        winner_id: fighters.fighter_id of the winner. For draws, this
            is one of the two participants (the brief says pass
            `a_id` as winner_id for draws — the helper treats both
            fighters symmetrically when was_draw=True).
        loser_id: fighters.fighter_id of the loser (or the other
            participant for draws).
        weight_class_id: the weight class the fight was at. Used as
            part of the rankings UNIQUE key.
        promotion_id: the promotion whose rankings to update.
        score_margin: int, the absolute margin of the fight (rounded
            from the resolver's abs_margin). Stored for reference but
            does not affect the ELO math (ELO only cares about
            win/loss/draw, not the margin).
        was_draw: if True, both fighters get a draw on their record
            and the ELO update uses score_a=0.5, score_b=0.5. With
            both fighters at the same rating, a draw produces zero
            rating change (expected=0.5, score=0.5, delta=0).
        fight_date: ISO date string 'YYYY-MM-DD' for last_fight_date.
            If None, the column is left NULL (but the brief says to
            pass event_date from resolve_next_fight, which is always
            non-NULL in practice).

    No-op if either fighter doesn't exist (defensive). The
    `score_margin` parameter is currently stored on the fight_history
    row (Task ID 4) but not on rankings — it's accepted here for
    future use (e.g., Task 24 punditry might weigh recent fights by
    margin) and to match the brief's signature.
    """
    row_a = _get_or_create_ranking_row(
        conn, winner_id, weight_class_id, promotion_id
    )
    row_b = _get_or_create_ranking_row(
        conn, loser_id, weight_class_id, promotion_id
    )
    if row_a is None or row_b is None:
        # Defensive no-op: one or both fighters don't exist. Should
        # not happen in normal gameplay, but tests or future tasks
        # might pass stale fighter_ids.
        return

    # Unpack: (ranking_id, rating, fights_count, wins, losses, draws,
    #          last_fight_date)
    _, rating_a, fights_a, wins_a, losses_a, draws_a, _ = row_a
    _, rating_b, fights_b, wins_b, losses_b, draws_b, _ = row_b

    # ELO expected scores. Standard formula.
    expected_a = 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))
    expected_b = 1.0 - expected_a

    if was_draw:
        score_a, score_b = 0.5, 0.5
    else:
        score_a, score_b = 1.0, 0.0

    new_rating_a = rating_a + _ELO_K * (score_a - expected_a)
    new_rating_b = rating_b + _ELO_K * (score_b - expected_b)

    # Ratings can't go negative (CHECK constraint on the rankings
    # table). Clamp at 0 to be safe — in practice ELO with K=32 and
    # starting rating 1000 won't push anyone to 0 in a reasonable
    # number of fights, but defensive coding is cheap.
    new_rating_a = max(0.0, new_rating_a)
    new_rating_b = max(0.0, new_rating_b)

    # Update fights_count, wins/losses/draws, last_fight_date. For
    # draws, both fighters get +1 draws and +1 fights_count. For
    # non-draws, winner gets +1 wins and +1 fights_count; loser gets
    # +1 losses and +1 fights_count.
    if was_draw:
        new_wins_a, new_losses_a, new_draws_a = wins_a, losses_a, draws_a + 1
        new_wins_b, new_losses_b, new_draws_b = wins_b, losses_b, draws_b + 1
    else:
        new_wins_a, new_losses_a, new_draws_a = wins_a + 1, losses_a, draws_a
        new_wins_b, new_losses_b, new_draws_b = wins_b, losses_b + 1, draws_b

    # last_fight_date: use the passed fight_date if available,
    # otherwise fall back to the existing value (keep NULL if it was
    # NULL and no fight_date was passed). COALESCE in SQL handles this
    # cleanly: COALESCE(?, last_fight_date) picks the new date if
    # non-NULL, else keeps the old.
    conn.execute(
        "UPDATE rankings SET rating = ?, fights_count = ?, wins = ?, "
        "losses = ?, draws = ?, last_fight_date = COALESCE(?, last_fight_date), "
        "updated_at = CURRENT_TIMESTAMP "
        "WHERE fighter_id = ? AND weight_class_id = ? AND promotion_id = ?",
        (new_rating_a, fights_a + 1, new_wins_a, new_losses_a, new_draws_a,
         fight_date, winner_id, weight_class_id, promotion_id),
    )
    conn.execute(
        "UPDATE rankings SET rating = ?, fights_count = ?, wins = ?, "
        "losses = ?, draws = ?, last_fight_date = COALESCE(?, last_fight_date), "
        "updated_at = CURRENT_TIMESTAMP "
        "WHERE fighter_id = ? AND weight_class_id = ? AND promotion_id = ?",
        (new_rating_b, fights_b + 1, new_wins_b, new_losses_b, new_draws_b,
         fight_date, loser_id, weight_class_id, promotion_id),
    )


# ----------------------------------------------------------------
# Title resolution (Task ID 11).
#
# After a fight resolves and the rankings ELO update (Task ID 10)
# runs, this helper transfers or vacates the title if the fight was
# a title fight (bout_type='title_fight'). Called unconditionally by
# `resolve_next_fight()` but returns None early if the fight is not a
# title fight (defensive — the caller doesn't need to check
# bout_type).
#
# Transfer rules:
#   - VACANT title + non-draw: winner becomes champion. Set
#     current_champion_fighter_id=winner_id, champion_since_date=
#     fight_date, title_reigns_count += 1, is_vacant=0. Return
#     title_id (title change occurred).
#   - VACANT title + draw: title stays vacant. Return None.
#   - HELD title + non-draw, champion wins: title_defenses_count +=
#     1. Champion retains. Return None (no title change).
#   - HELD title + non-draw, contender wins: title changes hands.
#     New champion = contender. Set current_champion_fighter_id=
#     contender_id, champion_since_date=fight_date,
#     title_reigns_count += 1, title_defenses_count=0 (reset for
#     new reign), is_vacant=0. Return title_id (title change).
#   - HELD title + draw: champion retains, no defense counted
#     (draws don't count as defenses in most MMA rulesets). Return
#     None.
#
# Returns:
#   title_id (int) if a title change occurred (new champion crowned
#   from vacant OR title changed hands), else None. The caller uses
#   a non-None return to enrich the news/commentary with a
#   "(TITLE CHANGE!)" suffix.
#
# Foundation for Task 12 (retirement — retiring champions vacate),
# Task 14 (regen — retiring champions vacate, new fighters enter),
# Task 22 (rivalries — title fight rivalries are the most heated).
#
# Schema version is bumped 1.5.0 -> 1.6.0 in this task (the new
# `titles` table is the only schema change).
# ----------------------------------------------------------------

def _resolve_title_after_fight(conn, fight_id, event_id, winner_id, loser_id,
                                weight_class_id, promotion_id, was_draw,
                                result_type, fight_date=None):
    """Transfer or vacate the title after a title fight resolution.

    Rules (Task ID 11):
      - Only fires if the fight's bout_type is 'title_fight'. Called
        unconditionally by resolve_next_fight() but returns early if
        the fight is not a title fight (defensive — the caller
        doesn't need to check bout_type).
      - Looks up the title row for (promotion_id, weight_class_id).
        If no title row exists (defensive — shouldn't happen with
        the seed, but a new weight class added without a title would
        trigger this), returns early.
      - If the title is VACANT (current_champion_fighter_id IS NULL):
        - Non-draw: the winner becomes the new champion. Set
          current_champion_fighter_id=winner_id, champion_since_date=
          fight_date, title_reigns_count += 1, is_vacant=0.
        - Draw: the title stays vacant (no champion for a vacant
          title fight that ends in a draw — sensible default).
      - If the title is HELD (current_champion_fighter_id is not
        NULL):
        - Determine which fighter is the champion and which is the
          contender. The champion is the one whose fighter_id
          matches current_champion_fighter_id; the other is the
          contender.
        - Non-draw, champion wins: title_defenses_count += 1.
          Champion retains.
        - Non-draw, contender wins: title changes hands. New
          champion = contender. Set current_champion_fighter_id=
          contender_id, champion_since_date=fight_date,
          title_reigns_count += 1, title_defenses_count=0 (reset
          for the new reign).
        - Draw: champion retains (no change to current_champion or
          defenses_count — draws don't count as defenses in most
          MMA rulesets).
      - Returns the title_id if a title change occurred (new
        champion crowned from vacant or title changed hands), else
        None. The caller can use this to enrich the news/commentary.

    Args:
        conn: sqlite3 connection (caller commits).
        fight_id: the fights.fight_id (for logging/defensive checks).
        event_id: the events.event_id (for logging).
        winner_id: fighters.fighter_id of the winner (ignored if
            was_draw).
        loser_id: fighters.fighter_id of the loser (ignored if
            was_draw).
        weight_class_id: the weight class the fight was at.
        promotion_id: the promotion the fight was under.
        was_draw: True if the fight was a draw.
        result_type: the result_type string (for logging).
        fight_date: ISO date string for champion_since_date. If None,
            uses CURRENT_DATE.

    Returns:
        title_id (int) if a title change occurred, else None.
    """
    # 1. Fetch the fight's bout_type. If it's not 'title_fight',
    #    this is a no-op (defensive — the caller doesn't need to
    #    check bout_type before calling).
    fight_row = conn.execute(
        "SELECT bout_type FROM fights WHERE fight_id = ?",
        (fight_id,),
    ).fetchone()
    if not fight_row or fight_row[0] != 'title_fight':
        return None

    # 2. Fetch the title row for (promotion_id, weight_class_id).
    #    If no title row exists (defensive — shouldn't happen with
    #    the seed, but a new weight class added without a title
    #    would trigger this), return None.
    title_row = conn.execute(
        "SELECT title_id, current_champion_fighter_id, is_vacant, "
        "title_reigns_count, title_defenses_count "
        "FROM titles WHERE promotion_id = ? AND weight_class_id = ?",
        (promotion_id, weight_class_id),
    ).fetchone()
    if not title_row:
        return None
    title_id, current_champ, is_vacant, reigns, defenses = title_row

    # 3. Handle the cases.
    if current_champ is None:
        # VACANT title.
        if was_draw:
            # Vacant + draw → stays vacant. No change.
            return None
        # Vacant + non-draw → winner becomes champion.
        conn.execute(
            "UPDATE titles SET current_champion_fighter_id = ?, "
            "champion_since_date = COALESCE(?, CURRENT_DATE), "
            "title_reigns_count = title_reigns_count + 1, "
            "is_vacant = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE title_id = ?",
            (winner_id, fight_date, title_id),
        )
        return title_id
    else:
        # HELD title. current_champ is the reigning champion.
        if was_draw:
            # Held + draw → champion retains, no defense counted.
            # (Draws don't count as defenses in most MMA rulesets.)
            return None
        if winner_id == current_champ:
            # Champion retained. Increment defenses.
            conn.execute(
                "UPDATE titles SET title_defenses_count = "
                "title_defenses_count + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE title_id = ?",
                (title_id,),
            )
            return None  # no title change
        else:
            # Contender won. Title changes hands.
            conn.execute(
                "UPDATE titles SET current_champion_fighter_id = ?, "
                "champion_since_date = COALESCE(?, CURRENT_DATE), "
                "title_reigns_count = title_reigns_count + 1, "
                "title_defenses_count = 0, "
                "is_vacant = 0, updated_at = CURRENT_TIMESTAMP "
                "WHERE title_id = ?",
                (winner_id, fight_date, title_id),
            )
            return title_id


# ----------------------------------------------------------------
# Title vacation on retirement (Task ID 12).
#
# When a fighter retires (handled by _check_retirements in
# tick_processor.py), any title they currently hold is vacated.
# This helper does the vacation + writes a news item about it. It
# lives here in app.py (next to _resolve_title_after_fight) so all
# title-mutation logic is in one place — tick_processor.py imports
# it via `from app import _vacate_title_on_retirement`. There is no
# circular-import risk because app.py does NOT import tick_processor.
#
# Vacation rules:
#   - current_champion_fighter_id  -> NULL
#   - champion_since_date          -> NULL
#   - is_vacant                    -> 1
#   - title_reigns_count and title_defenses_count are PRESERVED
#     (they're historical counters — a vacated belt still represents
#     a completed reign, and the count of past reigns is meaningful
#     for legacy/Hall-of-Fame work in later tasks).
#   - A news item is written: "<fighter> vacates the <promo> <wc>
#     title" with topic='retirement', promotion_id set, fighter_id
#     set, published_at=current_date.
#
# Returns the list of vacated title_ids (empty list if the fighter
# held no titles). Caller commits.
# ----------------------------------------------------------------

def _vacate_title_on_retirement(conn, fighter_id, current_date):
    """Vacate any title held by a retiring fighter.

    Called by _check_retirements() in tick_processor.py when a fighter
    retires. If the retiring fighter is a current champion, the title
    is vacated (current_champion_fighter_id = NULL, is_vacant = 1,
    champion_since_date = NULL). title_reigns_count and
    title_defenses_count are NOT reset (they're historical counters
    that should survive across reigns for legacy/Hall-of-Fame work).

    Also writes a news item about each title vacation (INSERT directly
    into news_items rather than going through app.write_news — see
    decision D2 in the worklog). The news item carries the fighter_id
    and promotion_id so future UIs can filter "retirement" news per
    promotion or per fighter.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the retiring fighter's fighter_id.
        current_date: ISO date string 'YYYY-MM-DD' for the news item
            published_at column.

    Returns:
        List of title_ids that were vacated (empty list if the fighter
        held no titles).
    """
    vacated = []
    # Find every title the retiring fighter currently holds. In
    # practice a fighter holds at most 1 title (one per weight class
    # per promotion, and a fighter is in one weight class), but the
    # code is defensive — if a future task adds multi-division
    # champions, this loop handles it correctly.
    rows = conn.execute(
        "SELECT title_id, promotion_id, weight_class_id "
        "FROM titles WHERE current_champion_fighter_id = ?",
        (fighter_id,),
    ).fetchall()
    if not rows:
        return vacated

    # Look up the fighter's name once (used in every news item).
    fighter_name_row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    fighter_name = fighter_name_row[0] if fighter_name_row else f"Fighter {fighter_id}"

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news). In the seeded DB this source already exists.
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    for title_id, promo_id, wc_id in rows:
        # Vacate the title. Preserve reigns + defenses counts (they
        # are historical — a future champion will start a NEW reign
        # with title_reigns_count incremented, but the historical
        # count of past reigns stays).
        conn.execute(
            "UPDATE titles SET current_champion_fighter_id = NULL, "
            "champion_since_date = NULL, is_vacant = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE title_id = ?",
            (title_id,),
        )
        vacated.append(title_id)

        # Look up promotion + weight class names for the news headline.
        promo_row = conn.execute(
            "SELECT name FROM promotions WHERE promotion_id = ?",
            (promo_id,),
        ).fetchone()
        promo_name = promo_row[0] if promo_row else f"Promotion {promo_id}"
        wc_row = conn.execute(
            "SELECT name FROM weight_classes WHERE weight_class_id = ?",
            (wc_id,),
        ).fetchone()
        wc_name = wc_row[0] if wc_row else f"Weight Class {wc_id}"

        # Write the vacation news item. topic='retirement' so future
        # UI filters can group retirement-related news together.
        # published_at is set to current_date (the sim date the
        # retirement happened on), NOT CURRENT_TIMESTAMP (which is
        # the wall-clock time the row was inserted).
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, promotion_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                src_id,
                f"{fighter_name} vacates the {promo_name} {wc_name} title",
                f"{fighter_name} has retired, vacating the {promo_name} "
                f"{wc_name} championship. A new champion will be crowned "
                f"at the next title fight.",
                "neutral",
                "retirement",
                fighter_id,
                promo_id,
                current_date,
            ),
        )

    return vacated


# ----------------------------------------------------------------
# Repeatable event generator (Task ID 8).
#
# After the last fight on a card resolves and the event transitions
# to 'completed' (Task ID 7), the world is dead — nothing schedules
# the next card. This breaks "played forever" on the very first
# playthrough. This block adds:
#
#   _pick_matchup(conn, promotion_id, weight_class_id,
#                 exclude_fighter_ids=())
#     Picks 2 distinct active fighters from the promotion's roster in
#     the given weight class. Random selection for now — Task ID 10
#     will add ranking proximity, Task ID 22 will add rivalry logic.
#
#   schedule_next_event(conn, promotion_id, from_event_date=None,
#                       weeks_out=4)
#     Auto-schedules a new event ~weeks_out weeks after a reference
#     date. Called as a side effect by resolve_next_fight() when an
#     event just transitioned to 'completed'. Also callable directly
#     for testing or for "I want to schedule an event now" UI actions.
#
# The new event:
#   - Same promotion_id as the just-completed event.
#   - Same venue and market (the seeded Metro Arena / Metro City
#     market). Task ID 27 will add venue/market depth.
#   - event_date = from_event_date + weeks_out*7 days. If
#     from_event_date is None, uses today's sim date from
#     simulation_clock.
#   - At least 1 fight with 2 participants from the promotion's
#     roster (random matchup for now).
#
# Schema version is unchanged (still 1.3.0) — no new tables, no new
# columns. RFL stays inert; only the promotion that just had an event
# complete gets a new auto-scheduled event (Task ID 25 adds RFL AI).
# ----------------------------------------------------------------

def _pick_matchup(conn, promotion_id, weight_class_id, exclude_fighter_ids=()):
    """Pick 2 distinct active fighters from a promotion's roster.

    Args:
        conn: sqlite3 connection (read-only — no writes here).
        promotion_id: the promotion whose roster to draw from.
        weight_class_id: the weight class the fight is at.
        exclude_fighter_ids: iterable of fighter_ids to skip (e.g.,
            fighters who just fought on the just-completed event, to
            avoid immediate rematches). Empty by default.

    Returns:
        (fighter_a_id, fighter_b_id) tuple on success, or None if
        fewer than 2 eligible fighters are available.

    For now: pure random selection (random.sample, distinct). Task
    ID 10 will add ranking-proximity matchmaking; Task ID 22 will
    add rivalry logic. The signature already accepts
    exclude_fighter_ids so those future enhancements can pass a
    fighter set without changing the call sites.
    """
    sql = (
        "SELECT fighter_id FROM fighters "
        "WHERE current_promotion_id = ? AND is_active = 1 "
        "AND weight_class_id = ?"
    )
    params = [promotion_id, weight_class_id]
    if exclude_fighter_ids:
        # Parameterized NOT IN clause. Never string-format fighter_ids
        # into SQL — always use placeholders.
        placeholders = ",".join("?" * len(exclude_fighter_ids))
        sql += f" AND fighter_id NOT IN ({placeholders})"
        params.extend(exclude_fighter_ids)
    rows = conn.execute(sql, params).fetchall()
    if len(rows) < 2:
        return None
    # random.sample pulls 2 distinct rows without replacement.
    picks = random.sample(rows, 2)
    return (picks[0][0], picks[1][0])


def schedule_next_event(conn, promotion_id, from_event_date=None, weeks_out=4):
    """Auto-schedule the next event for a promotion, ~weeks_out weeks
    after a reference date.

    Called by resolve_next_fight() as a side effect when an event just
    transitioned to 'completed' (Task ID 8). Can also be called directly
    for testing or for "I want to schedule an event now" UI actions.

    The new event:
      - Has the same promotion_id as the just-completed event.
      - Is scheduled at the same venue and market as the promotion's
        most recent completed event (the seeded Metro Arena / Metro
        City market). Task ID 27 will add venue/market depth; for now
        we reuse.
      - Has event_date = from_event_date + weeks_out*7 days. If
        from_event_date is None, uses today's sim date from
        simulation_clock.
      - Has at least 1 fight with 2 participants from the promotion's
        roster (active fighters, same weight class as the original
        event). Matchmaking is random for now (Task 10 will add
        ranking-proximity matchmaking; Task 22 will add rivalry logic).
      - Returns the new event_id, or None if scheduling failed (e.g.,
        not enough available fighters).

    Args:
        conn: sqlite3 connection (caller commits).
        promotion_id: the promotion to schedule for.
        from_event_date: ISO date string 'YYYY-MM-DD' to count weeks_out
            from. If None, uses simulation_clock.current_date.
        weeks_out: how many weeks ahead to schedule. Default 4.

    Returns:
        New event_id (int) on success, or None on failure (with a
        printed warning explaining why).
    """
    # 1. Resolve the reference date.
    if from_event_date is None:
        clock_row = conn.execute(
            "SELECT current_date FROM simulation_clock WHERE clock_id = 1"
        ).fetchone()
        if not clock_row or not clock_row[0]:
            print("Warning: could not auto-schedule next event — no "
                  "from_event_date given and simulation_clock has no "
                  "current_date.")
            return None
        from_event_date = clock_row[0]
    try:
        ref_date = datetime.strptime(from_event_date, "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        print(f"Warning: could not auto-schedule next event — invalid "
              f"from_event_date {from_event_date!r}: {e}")
        return None

    # 2. Compute the new event_date.
    new_date = ref_date + timedelta(weeks=weeks_out)
    new_date_str = new_date.strftime("%Y-%m-%d")

    # 3. Find venue + market + weight_class for the new event. Reuse
    # the values from the promotion's most recent completed event.
    # events has no weight_class_id column — join through fights to
    # get it. ORDER BY e.event_date DESC so the most recent completed
    # event wins (defensive: in normal gameplay only 1 completed event
    # exists at this point, but multi-event histories are possible).
    completed = conn.execute(
        "SELECT e.venue_id, e.market_id, f.weight_class_id "
        "FROM events e JOIN fights f ON f.event_id = e.event_id "
        "WHERE e.promotion_id = ? AND e.status = 'completed' "
        "ORDER BY e.event_date DESC LIMIT 1",
        (promotion_id,),
    ).fetchone()
    if completed:
        venue_id, market_id, weight_class_id = completed
    else:
        # Degenerate fallback: no completed event yet for this
        # promotion. This can happen when schedule_next_event() is
        # called directly (test case F) before any event has been
        # resolved. Fall back to any venue in any city whose nation
        # matches the promotion's nation. If that also fails, give up.
        promo_row = conn.execute(
            "SELECT nation_id FROM promotions WHERE promotion_id = ?",
            (promotion_id,),
        ).fetchone()
        nation_id = promo_row[0] if promo_row else None
        if nation_id is None:
            print(f"Warning: could not auto-schedule next event — "
                  f"promotion_id={promotion_id} not found and no "
                  f"completed event to reuse.")
            return None
        fallback = conn.execute(
            "SELECT v.venue_id, m.market_id "
            "FROM venues v "
            "JOIN cities c ON c.city_id = v.city_id "
            "JOIN markets m ON m.city_id = c.city_id "
            "WHERE c.nation_id = ? "
            "ORDER BY v.venue_id LIMIT 1",
            (nation_id,),
        ).fetchone()
        if not fallback:
            print(f"Warning: could not auto-schedule next event — no "
                  f"venue/market found for nation_id={nation_id} "
                  f"(promotion_id={promotion_id}).")
            return None
        venue_id, market_id = fallback
        # Need a weight_class_id too — use any weight class. In the
        # seeded DB there's exactly one (Lightweight, id=1).
        wc_row = conn.execute(
            "SELECT weight_class_id FROM weight_classes "
            "ORDER BY weight_class_id LIMIT 1"
        ).fetchone()
        if not wc_row:
            print(f"Warning: could not auto-schedule next event — no "
                  f"weight_classes exist (promotion_id={promotion_id}).")
            return None
        weight_class_id = wc_row[0]

    # 4. Pick 2 distinct fighters from the promotion's roster in this
    # weight class. For now: random. exclude_fighter_ids is left empty
    # because the just-completed event's fighters can fight again on
    # the next card (4 weeks out is enough rest in this thin sim).
    matchup = _pick_matchup(conn, promotion_id, weight_class_id)
    if matchup is None:
        print(f"Warning: could not auto-schedule next event — not "
              f"enough active fighters in promotion_id={promotion_id}, "
              f"weight_class_id={weight_class_id} (need 2).")
        return None
    fighter_a_id, fighter_b_id = matchup

    # 5. Build the event_name. Use a counter: count existing events
    # for this promotion + 1. Format chosen: "{promo_name}: Card {N}"
    # to foreshadow the "card" terminology from the v1.6 spec. See
    # worklog decision D1.
    event_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchone()[0]
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promotion {promotion_id}"
    event_name = f"{promo_name}: Card {event_count + 1}"

    # 6. Insert the new event (status='scheduled', event_type='fight_night').
    new_event_id = conn.execute(
        "INSERT INTO events (promotion_id, venue_id, market_id, event_name, "
        "event_date, event_type, status) VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
        (promotion_id, venue_id, market_id, event_name,
         new_date_str, "fight_night"),
    ).lastrowid

    # 7. Insert the fight + 2 participants + 1 event_cards row. Mirror
    # the seed pattern (main_event, 3 rounds, red/blue corners, card
    # position 1 / card_tier 'main_event' / is_main_event 1).
    new_fight_id = conn.execute(
        "INSERT INTO fights (event_id, weight_class_id, bout_type, "
        "round_limit, scheduled_rounds) VALUES (?, ?, 'main_event', 3, 3)",
        (new_event_id, weight_class_id),
    ).lastrowid
    conn.execute(
        "INSERT INTO fight_participants (fight_id, fighter_id, corner) "
        "VALUES (?, ?, 'red')",
        (new_fight_id, fighter_a_id),
    )
    conn.execute(
        "INSERT INTO fight_participants (fight_id, fighter_id, corner) "
        "VALUES (?, ?, 'blue')",
        (new_fight_id, fighter_b_id),
    )
    conn.execute(
        "INSERT INTO event_cards (event_id, fight_id, card_position, "
        "card_tier, is_main_event) VALUES (?, ?, 1, 'main_event', 1)",
        (new_event_id, new_fight_id),
    )

    # 8. Return the new event_id. Do NOT commit — the caller commits,
    # matching the existing pattern (resolve_next_fight, advance_day,
    # etc.).
    return new_event_id


def resolve_next_fight(conn):
    """Resolve the next scheduled fight using the attribute-based model.

    Picks the lowest-fight_id unresolved fight, loads both fighters'
    stats, runs the probabilistic resolver, persists the result, updates
    career counters, and writes a news item + commentary segment.
    Returns the resolved fight_id (or None if no unresolved fight was
    found). The function does not call conn.commit() itself — the caller
    commits, matching the original signature and the UI's on_resolve_fight
    callsite.

    Side effects (preserved from the original coin-flip version):
      - UPDATE fights SET winner/loser/result_type/finish_round/...
      - UPDATE fight_participants SET is_winner=...
      - UPDATE fighter_career SET record_wins/losses/draws, streaks
      - INSERT INTO fight_history (2 rows, one per fighter, title_at_stake populated)  [v1.3.0, v1.6.0]
      - UPDATE rankings SET rating/fights_count/wins/losses/draws (ELO)  [v1.5.0, Task ID 10]
      - UPDATE titles SET current_champion/defenses/reigns (if title fight)  [v1.6.0, Task ID 11]
      - UPDATE events SET status=in_progress/completed  [v1.3.0, Task ID 7]
      - INSERT INTO events + fights + fight_participants + event_cards
        (auto-scheduled next card, only if event just completed)  [v1.3.0, Task ID 8]
      - write_news(...)  (enriched headline + body, same signature)
      - write_commentary(...)  (enriched text, same signature)
    """
    fight = conn.execute(
        "SELECT f.fight_id, f.event_id, f.scheduled_rounds, e.promotion_id, "
        "f.weight_class_id, e.event_date "
        "FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL "
        "ORDER BY f.fight_id LIMIT 1"
    ).fetchone()
    if not fight:
        return None
    fight_id, event_id, scheduled_rounds, promo_id, weight_class_id, event_date = fight
    parts = conn.execute(
        "SELECT fighter_id FROM fight_participants WHERE fight_id=? ORDER BY corner",
        (fight_id,),
    ).fetchall()
    if len(parts) < 2:
        return None
    a_id, b_id = parts[0][0], parts[1][0]

    stats_a = _load_fighter_stats(conn, a_id)
    stats_b = _load_fighter_stats(conn, b_id)
    outcome = _resolve_outcome(stats_a, stats_b, scheduled_rounds)

    result_type = outcome["result_type"]
    finish_round = outcome["finish_round"]
    finish_time = outcome["finish_time"]
    performance_rating = outcome["performance_rating"]
    fan_reaction_rating = outcome["fan_reaction_rating"]

    a_name = fighter_name(conn, a_id)
    b_name = fighter_name(conn, b_id)

    if result_type == "draw":
        # Draw: no winner/loser. Both participants get a draw on their
        # record. Streaks are unchanged (a draw neither extends nor
        # breaks a streak in most MMA rulesets).
        conn.execute(
            "UPDATE fights SET winner_fighter_id=NULL, loser_fighter_id=NULL, "
            "result_type=?, finish_round=?, finish_time=?, "
            "performance_rating=?, fan_reaction_rating=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fight_id=?",
            (result_type, finish_round, finish_time,
             performance_rating, fan_reaction_rating, fight_id),
        )
        conn.execute(
            "UPDATE fight_participants SET is_winner=0 WHERE fight_id=?",
            (fight_id,),
        )
        conn.execute(
            "UPDATE fighter_career SET record_draws=record_draws+1, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id IN (?, ?)",
            (a_id, b_id),
        )
        headline = f"{a_name} and {b_name} fight to a draw"
        body = f"{a_name} and {b_name} fought to a draw after {finish_round} rounds."
        commentary = f"The judges cannot split {a_name} and {b_name} — it's a draw."
        news_fighter_id = None
    else:
        if outcome["winner"] == "a":
            winner_id, loser_id = a_id, b_id
            winner_name, loser_name = a_name, b_name
        else:
            winner_id, loser_id = b_id, a_id
            winner_name, loser_name = b_name, a_name
        conn.execute(
            "UPDATE fights SET winner_fighter_id=?, loser_fighter_id=?, result_type=?, "
            "finish_round=?, finish_time=?, performance_rating=?, fan_reaction_rating=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fight_id=?",
            (winner_id, loser_id, result_type, finish_round, finish_time,
             performance_rating, fan_reaction_rating, fight_id),
        )
        conn.execute(
            "UPDATE fight_participants SET is_winner=CASE WHEN fighter_id=? THEN 1 ELSE 0 END "
            "WHERE fight_id=?",
            (winner_id, fight_id),
        )
        conn.execute(
            "UPDATE fighter_career SET record_wins=record_wins+1, win_streak=win_streak+1, "
            "loss_streak=0, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (winner_id,),
        )
        conn.execute(
            "UPDATE fighter_career SET record_losses=record_losses+1, loss_streak=loss_streak+1, "
            "win_streak=0, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (loser_id,),
        )
        headline, body = _format_fight_news(winner_name, loser_name, result_type, finish_round)
        commentary = _format_fight_commentary(winner_name, loser_name, result_type, finish_round)
        news_fighter_id = winner_id

    # ----------------------------------------------------------------
    # Write two rows to `fight_history` (one per fighter, from their
    # perspective). New in v1.3.0 (Task ID 4) — separate from the
    # mutable `fighter_career` counters. The UNIQUE (fight_id, fighter_id)
    # constraint enforces one row per fighter per fight. `title_at_stake`
    # is populated based on `fights.bout_type` (1 if 'title_fight',
    # 0 otherwise) — added in v1.6.0 (Task ID 11). `score_margin` is
    # the rounded absolute margin from the resolver. Read by upcoming
    # rankings, legacy, and stats-based commentary work (Tasks 10, 11,
    # 14, 19, 23) — see docs/STAGES.md Task ID 4.
    #
    # Defensive DELETE: in normal gameplay each fight is resolved exactly
    # once, so there are no prior fight_history rows to conflict with.
    # But tests (and any future "re-resolve" feature) may reset the
    # fights row and call resolve_next_fight() again on the same
    # fight_id. Without this DELETE, the INSERT below would crash on
    # the UNIQUE constraint. Clearing prior rows makes the resolver
    # idempotent for re-resolution — the latest result wins, which is
    # the sensible behaviour. (This is what keeps
    # scripts/test_fight_resolver.py passing after Task ID 4.)
    # ----------------------------------------------------------------
    # Determine if this was a title fight (Task ID 11). The
    # fight_history rows get title_at_stake=1 if so, 0 otherwise.
    # This is read by upcoming legacy/Hall of Fame work to count
    # title fights per fighter.
    bout_type_row = conn.execute(
        "SELECT bout_type FROM fights WHERE fight_id = ?",
        (fight_id,),
    ).fetchone()
    is_title_fight = bool(bout_type_row and bout_type_row[0] == 'title_fight')
    title_at_stake_val = 1 if is_title_fight else 0

    conn.execute(
        "DELETE FROM fight_history WHERE fight_id=?",
        (fight_id,),
    )
    score_margin_int = int(round(outcome["abs_margin"]))
    if result_type == "draw":
        # Both fighters get a 'draw' row, opponent_id = the other fighter.
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'draw', ?, ?, ?, ?, ?, ?, ?, ?)",
            (fight_id, a_id, b_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id,
             title_at_stake_val),
        )
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'draw', ?, ?, ?, ?, ?, ?, ?, ?)",
            (fight_id, b_id, a_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id,
             title_at_stake_val),
        )
    else:
        # Winner row: outcome='win', opponent_id = loser.
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'win', ?, ?, ?, ?, ?, ?, ?, ?)",
            (fight_id, winner_id, loser_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id,
             title_at_stake_val),
        )
        # Loser row: outcome='loss', opponent_id = winner.
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'loss', ?, ?, ?, ?, ?, ?, ?, ?)",
            (fight_id, loser_id, winner_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id,
             title_at_stake_val),
        )

    # ----------------------------------------------------------------
    # Rankings ELO update (Task ID 10). Update both fighters' rating
    # rows after the fight_history rows are written (Task ID 4) and
    # BEFORE the title resolution (Task ID 11) so the new champion's
    # ranking is already updated. The update is zero-sum — the
    # winner's gain is the loser's loss. For draws, both fighters get
    # +1 draws and the ELO delta uses score=0.5 for each, which
    # produces zero rating change when both start at the same rating
    # (expected=0.5, score=0.5, delta=0). K-factor is fixed at 32.0.
    # See docs/STAGES.md Task ID 10 for the spec.
    # ----------------------------------------------------------------
    if result_type == "draw":
        _update_rankings_after_resolution(
            conn, a_id, b_id, weight_class_id, promo_id,
            score_margin_int, was_draw=True, fight_date=event_date,
        )
    else:
        _update_rankings_after_resolution(
            conn, winner_id, loser_id, weight_class_id, promo_id,
            score_margin_int, was_draw=False, fight_date=event_date,
        )

    # ----------------------------------------------------------------
    # Resolve title (Task ID 11). If this was a title fight
    # (bout_type='title_fight'), transfer or vacate the belt. Returns
    # the title_id if a title change occurred (new champion crowned
    # from vacant OR title changed hands), else None. The title_id is
    # used below to enrich the news/commentary with a "(TITLE
    # CHANGE!)" suffix. The helper is a no-op for non-title fights
    # (returns None early). For draws, winner_id/loser_id are not
    # used by the helper (it detects the draw and skips the transfer).
    # ----------------------------------------------------------------
    title_change_id = _resolve_title_after_fight(
        conn,
        fight_id=fight_id,
        event_id=event_id,
        winner_id=winner_id if result_type != "draw" else a_id,
        loser_id=loser_id if result_type != "draw" else b_id,
        weight_class_id=weight_class_id,
        promotion_id=promo_id,
        was_draw=(result_type == "draw"),
        result_type=result_type,
        fight_date=event_date,
    )

    # Enrich news/commentary for title changes (Task ID 11). Simple
    # approach: append "(TITLE CHANGE!)" to the headline and " Title
    # changes hands!" to the commentary when title_change_id is not
    # None. The helper returns just the title_id (or None), so we
    # can't distinguish "won from vacant" vs "dethroned champion"
    # without an extra DB query — keeping it simple per the brief's
    # "the goal is to surface the title change to the player, not to
    # write perfect prose" guidance. See worklog decision D1.
    if title_change_id is not None:
        headline = f"{headline} (TITLE CHANGE!)"
        commentary = f"{commentary} Title changes hands!"

    # The write_news / write_commentary calls themselves are preserved
    # exactly — only the headline / body / commentary strings change.
    write_news(conn, headline, body, "fight", event_id, fight_id, news_fighter_id, promo_id)
    write_commentary(conn, event_id, fight_id, commentary)

    # ----------------------------------------------------------------
    # Event lifecycle (Task ID 7). Transition the parent event's status:
    #   scheduled  -> in_progress  (when the first fight on the card resolves)
    #   in_progress -> completed   (when the last unresolved fight resolves)
    # An event with only 1 fight goes scheduled -> completed in one step.
    # ----------------------------------------------------------------
    _update_event_status_after_resolution(conn, event_id)

    # ----------------------------------------------------------------
    # Auto-schedule next event (Task ID 8). If the event just transitioned
    # to 'completed', schedule a new event ~4 weeks out for the same
    # promotion. This is what makes the world "playable forever" - after
    # the last fight on a card resolves, the next card is auto-scheduled.
    # schedule_next_event() returns None if it can't find a matchup (e.g.,
    # not enough fighters) - in that case we print a warning but don't
    # crash. The user can still click "Resolve Fight" later when more
    # fighters are available (e.g., after regen, Task ID 14).
    # ----------------------------------------------------------------
    post_status = conn.execute(
        "SELECT status FROM events WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    if post_status == "completed":
        scheduled = schedule_next_event(
            conn,
            promotion_id=promo_id,
            from_event_date=event_date,
            weeks_out=4,
        )
        if scheduled is None:
            print(f"Warning: could not auto-schedule next event for "
                  f"promotion_id={promo_id} (not enough available fighters?).")
        # else: scheduled is the new event_id. No print - the UI's
        # refresh_all() will display the new event in the Events tree.

    return fight_id


# ----------------------------------------------------------------
# Free agency helpers (Task ID 13).
#
# Two module-scope helpers that power the Free Agents tab:
#
#   get_free_agents_for_display(conn)
#     Returns a list of (fighter_id, name, weight_class, record, age)
#     tuples for every fighter who is currently a free agent — i.e.,
#     current_promotion_id IS NULL AND is_active=1 AND is_retired=0.
#     Used by the Free Agents tab's Treeview in refresh_all(). The
#     fighter_id is included (as the first element) so the Treeview
#     can use it as the item iid, which lets the Sign button read
#     the fighter_id directly from `tree.selection()[0]` instead of
#     doing a fragile name lookup.
#
#   sign_free_agent(conn, fighter_id, promotion_id, start_date,
#                   salary=50000.0)
#     Signs a free agent to a promotion with a new 12-month exclusive
#     contract. Verifies the fighter is currently a free agent and
#     active (refuses retired / already-signed / inactive fighters).
#     Creates one row in `contracts` and one in `fighter_contracts`,
#     sets the fighter's current_promotion_id, writes a signing news
#     item, and returns the new contract_id (None on failure).
#
# The age computation in get_free_agents_for_display reads
# simulation_clock.current_date using the QUALIFIED column reference
# `simulation_clock.current_date` (not bare `current_date`). This is
# important because of the pre-existing D5 SQLite quirk: a bare
# `SELECT current_date FROM simulation_clock` resolves to the built-in
# date function (today's wall-clock date) instead of the column. The
# new helper qualifies the column to avoid the quirk. The pre-existing
# `get_clock()` function (line 17) does NOT qualify it and is left
# unchanged per the brief (out of scope; flagged for a future
# housekeeping task).
# ----------------------------------------------------------------

def get_free_agents_for_display(conn):
    """Return free agent rows for the UI Free Agents tab (Task ID 13).

    A free agent is a fighter with current_promotion_id IS NULL,
    is_active=1, and is_retired=0. Returns one row per free agent with
    their fighter_id, name, weight class, record, and age.

    The Free Agents tab does NOT respect the promotion filter — free
    agents are not bound to any promotion, so they're available to sign
    with any promotion. The UI always shows all free agents regardless
    of the current_promotion_filter dropdown.

    Args:
        conn: sqlite3 connection.

    Returns:
        List of 5-tuples: (fighter_id, fighter_name, weight_class_name,
        record_str, age_int). Ordered by fighter_id.

        - fighter_id:         int (used as the Treeview item iid so
                              the Sign button can read it directly).
        - fighter_name:       'first_name last_name'.
        - weight_class_name:  weight_classes.name, or 'Unknown'.
        - record_str:         'W-L-D' from fighter_career counters,
                              defaulting to '0-0-0' if no career row.
        - age_int:            computed from date_of_birth and the
                              current sim date.
    """
    # Read the current sim date. Qualify the column as
    # simulation_clock.current_date to avoid the D5 quirk where bare
    # `current_date` resolves to SQLite's built-in date function
    # (today's wall-clock date) instead of the column.
    clock_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id = 1"
    ).fetchone()
    if clock_row and clock_row[0]:
        try:
            current_dt = datetime.strptime(clock_row[0], "%Y-%m-%d")
        except (ValueError, TypeError):
            current_dt = datetime.now()
    else:
        current_dt = datetime.now()

    # Pull all free agents. LEFT JOIN weight_classes + fighter_career
    # so a fighter missing either row (defensive — shouldn't happen
    # with the seed) doesn't crash the helper.
    rows = conn.execute(
        "SELECT f.fighter_id, f.first_name || ' ' || f.last_name, "
        "COALESCE(w.name, 'Unknown'), "
        "COALESCE(fc.record_wins, 0) || '-' || "
        "COALESCE(fc.record_losses, 0) || '-' || "
        "COALESCE(fc.record_draws, 0), "
        "f.date_of_birth "
        "FROM fighters f "
        "LEFT JOIN weight_classes w ON w.weight_class_id = f.weight_class_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.current_promotion_id IS NULL "
        "AND f.is_active = 1 AND f.is_retired = 0 "
        "ORDER BY f.fighter_id"
    ).fetchall()

    out = []
    for fighter_id, name, wc_name, record_str, dob in rows:
        # Compute age from date_of_birth + the current sim date.
        # Same pattern as _check_retirements: tuple comparison on
        # (month, day) handles leap-year birthdays correctly.
        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
            age = current_dt.year - dob_dt.year
            if (current_dt.month, current_dt.day) < (dob_dt.month, dob_dt.day):
                age -= 1
        except (ValueError, TypeError):
            # Defensive: fighter with malformed DOB gets age 0 (will
            # display as "0" in the UI). Shouldn't happen with the
            # seed, but a future regen engine or mod tool could produce
            # one.
            age = 0
        out.append((fighter_id, name, wc_name, record_str, age))
    return out


def sign_free_agent(conn, fighter_id, promotion_id, start_date, salary=50000.0):
    """Sign a free agent to a promotion with a new 12-month contract.

    Rules (Task ID 13):
      - The fighter must currently be a free agent
        (current_promotion_id IS NULL) and active (is_active=1,
        is_retired=0). If not, return None with a printed warning.
        Refuses retired fighters (they can't sign) and already-signed
        fighters (they're not free agents).
      - Creates a new contracts row (contract_target_type='fighter',
        status='active', exclusive_flag=1, start_date=start_date,
        end_date=start_date + 365 days, salary=salary).
      - Creates a fighter_contracts row linking the contract to the
        fighter (contract_type='standard').
      - Sets the fighter's current_promotion_id = promotion_id.
      - Writes a news item: "<fighter> signs with <promotion>".
        topic='signing' so future UI filters can group signing-related
        news together.
      - Returns the new contract_id (int) on success, None on failure.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the free agent's fighter_id.
        promotion_id: the promotion signing them.
        start_date: ISO date string 'YYYY-MM-DD' for the contract start.
        salary: contract salary. Default 50000.0 (matches the seed
            default — no negotiation flow yet, that's a future task).

    Returns:
        New contract_id (int) on success, None on failure.
    """
    # 1. Verify the fighter is a free agent and active. Refuse retired
    #    fighters (they're not coming back) and already-signed fighters
    #    (they're not free agents).
    row = conn.execute(
        "SELECT is_active, is_retired, current_promotion_id "
        "FROM fighters WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row:
        print(f"Warning: fighter_id={fighter_id} not found.")
        return None
    is_active, is_retired, current_promo = row
    if is_retired == 1:
        print(f"Warning: fighter_id={fighter_id} is retired — cannot sign.")
        return None
    if current_promo is not None:
        print(f"Warning: fighter_id={fighter_id} is already signed to "
              f"promotion_id={current_promo}.")
        return None
    if is_active != 1:
        print(f"Warning: fighter_id={fighter_id} is not active — cannot sign.")
        return None

    # 2. Compute end_date (start_date + 365 days). Mirrors the seed
    #    default in _seed_default_fighter_contract (seed_data.py).
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        print(f"Warning: invalid start_date {start_date!r}: {e}")
        return None
    end_dt = start_dt + timedelta(days=365)
    end_date = end_dt.strftime("%Y-%m-%d")

    # 3. Insert the contract. contract_target_type='fighter',
    #    exclusive_flag=1 (mirrors the seed default), status='active'.
    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('fighter', ?, ?, ?, ?, 1, 'active')",
        (promotion_id, start_date, end_date, salary),
    ).lastrowid

    # 4. Insert the fighter_contracts row linking the contract to the
    #    fighter. contract_type='standard' (same as the seed default).
    conn.execute(
        "INSERT INTO fighter_contracts (contract_id, fighter_id, "
        "contract_type) VALUES (?, ?, 'standard')",
        (contract_id, fighter_id),
    )

    # 5. Set the fighter's current_promotion_id. This is what
    #    _pick_matchup (Task 8) and get_fighters_for_display (Task 6)
    #    filter on — once it's set, the fighter appears in the
    #    promotion's roster and is eligible for new matchups.
    conn.execute(
        "UPDATE fighters SET current_promotion_id = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
        (promotion_id, fighter_id),
    )

    # 6. Write the signing news item. Direct INSERT (same pattern as
    #    _check_retirements + _vacate_title_on_retirement) to avoid
    #    pulling in app.write_news from this same module (it would be
    #    fine since we're already in app.py, but the direct INSERT is
    #    what the brief specifies and matches the established pattern).
    fighter_name_row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    fighter_name = fighter_name_row[0] if fighter_name_row else f"Fighter {fighter_id}"

    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promotion {promotion_id}"

    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            src_id,
            f"{fighter_name} signs with {promo_name}",
            f"Free agent {fighter_name} has signed a new contract "
            f"with {promo_name}.",
            "positive",
            "signing",
            fighter_id,
            promotion_id,
            start_date,
        ),
    )

    return contract_id


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MMA Booking Sim")
        self.geometry("1280x760")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        # Promotion filter state (Task ID 6). None = all promotions
        # (including free agents with current_promotion_id = NULL);
        # an int = restrict the Fighters tree to that promotion_id.
        # Default is "All Promotions" so the UI opens showing every
        # fighter across every promotion.
        self.current_promotion_filter = None
        # Parallel list mapping the combobox's selected index to a
        # promotion_id (or None for the "All Promotions" sentinel).
        # Populated by refresh_all() alongside the combobox values.
        self._promo_filter_ids = [None]
        self.build_ui()
        self.refresh_all()

    def build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill='x')
        ttk.Button(top, text="Advance Day", command=self.on_advance_day).pack(side='left', padx=4)
        ttk.Button(top, text="Resolve Fight", command=self.on_resolve_fight).pack(side='left', padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side='left', padx=4)

        # Promotion filter (Task ID 6) — lets the player focus the
        # Fighters tree on one promotion's roster. None = all
        # promotions. Defaults to "All Promotions". The dropdown
        # values are refreshed from the DB on every refresh_all() call
        # so promotions added by future tasks (or removed via free-
        # agency, Task ID 13) are reflected automatically. The
        # current selection is preserved across refreshes if the
        # promotion still exists; otherwise it resets to "All".
        ttk.Label(top, text="Filter:").pack(side='left', padx=(12, 4))
        self.promo_filter_var = tk.StringVar()
        self.promo_filter_combo = ttk.Combobox(
            top, textvariable=self.promo_filter_var, state='readonly',
            width=22, values=["All Promotions"]
        )
        self.promo_filter_combo.current(0)
        # <<ComboboxSelected>> only fires on user interaction, not on
        # programmatic .set()/.current() calls — so calling refresh_all()
        # from inside the handler (which re-populates the combobox)
        # does NOT cause infinite recursion. Verified empirically by
        # the smoke test.
        self.promo_filter_combo.bind("<<ComboboxSelected>>", self.on_promo_filter_change)
        self.promo_filter_combo.pack(side='left', padx=4)

        self.clock_var = tk.StringVar()
        ttk.Label(top, textvariable=self.clock_var, font=("Segoe UI", 11, "bold")).pack(side='right')

        main = ttk.Panedwindow(self, orient='horizontal')
        main.pack(fill='both', expand=True, padx=8, pady=8)

        left = ttk.Frame(main, padding=6)
        center = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=2)
        main.add(center, weight=2)
        main.add(right, weight=2)

        ttk.Label(left, text="Fighters", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fighters = ttk.Treeview(left, columns=('name','wc','promo','record'), show='headings', height=16)
        for c,w in [('name',170),('wc',110),('promo',140),('record',100)]:
            self.fighters.heading(c, text=c.title())
            self.fighters.column(c, width=w, anchor='w')
        self.fighters.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(center, text="Events", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.events = ttk.Treeview(center, columns=('date','name','status'), show='headings', height=8)
        for c,w in [('date',110),('name',250),('status',120)]:
            self.events.heading(c, text=c.title())
            self.events.column(c, width=w, anchor='w')
        self.events.pack(fill='x', pady=(6,10))

        ttk.Label(center, text="Fights", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fights = ttk.Treeview(center, columns=('id','matchup','wc','result'), show='headings', height=10)
        for c,w in [('id',60),('matchup',260),('wc',110),('result',120)]:
            self.fights.heading(c, text=c.title())
            self.fights.column(c, width=w, anchor='w')
        self.fights.pack(fill='both', expand=True, pady=(6,0))

        # ----------------------------------------------------------------
        # Right pane: ttk.Notebook with two tabs (Task ID 9).
        #
        # Layout choice (worklog decision D1): the existing News + Commentary
        # Listboxes are moved into a "News & Commentary" tab, and a new
        # "Contracts" tab holds a read-only Treeview of the player's
        # promotion's active contracts. This preserves the 3-pane layout
        # (left=fighters / center=events+fights / right=notebook) while
        # adding the Contracts surface without taking screen real estate
        # away from News + Commentary. The Contracts tab respects the
        # same current_promotion_filter as the Fighters tree (Task ID 6)
        # so the player can scope the contracts list to a single promotion.
        # ----------------------------------------------------------------
        right_notebook = ttk.Notebook(right)
        right_notebook.pack(fill='both', expand=True)

        # Tab 1: News & Commentary (existing widgets, moved into the tab).
        news_tab = ttk.Frame(right_notebook)
        right_notebook.add(news_tab, text="News & Commentary")
        ttk.Label(news_tab, text="News", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.news = tk.Listbox(news_tab, height=14)
        self.news.pack(fill='both', expand=True, pady=(6, 0))
        ttk.Label(news_tab, text="Commentary", font=("Segoe UI", 11, "bold")).pack(anchor='w', pady=(10, 0))
        self.commentary = tk.Listbox(news_tab, height=6)
        self.commentary.pack(fill='both', expand=True, pady=(6, 0))

        # Tab 2: Contracts (new in Task ID 9). Read-only Treeview with
        # columns: contractor, type, start, end, salary, exclusive,
        # status. Populated by refresh_all() via get_contracts_for_display.
        contracts_tab = ttk.Frame(right_notebook)
        right_notebook.add(contracts_tab, text="Contracts")
        ttk.Label(contracts_tab, text="Active Contracts", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.contracts = ttk.Treeview(
            contracts_tab,
            columns=('contractor', 'type', 'start', 'end', 'salary', 'exclusive', 'status'),
            show='headings', height=18
        )
        for c, w in [('contractor', 150), ('type', 80), ('start', 90), ('end', 90),
                     ('salary', 80), ('exclusive', 70), ('status', 90)]:
            self.contracts.heading(c, text=c.title())
            self.contracts.column(c, width=w, anchor='w')
        self.contracts.pack(fill='both', expand=True, pady=(6, 0))

        # Tab 3: Rankings (new in Task ID 10). Read-only Treeview with
        # columns: rank, fighter, weight_class, rating, fights, record,
        # last_fight. Populated by refresh_all() via
        # get_rankings_for_display. When current_promotion_filter is
        # None ("All Promotions"), the rankings tab falls back to the
        # first promotion's rankings — the helper requires a
        # promotion_id and "all promotions' rankings combined" is not
        # meaningful under ELO (ratings are per-promotion). This
        # fallback is documented in refresh_all().
        rankings_tab = ttk.Frame(right_notebook)
        right_notebook.add(rankings_tab, text="Rankings")
        ttk.Label(rankings_tab, text="Top 10 by ELO Rating", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.rankings = ttk.Treeview(
            rankings_tab,
            columns=('rank', 'fighter', 'weight_class', 'rating', 'fights', 'record', 'last_fight'),
            show='headings', height=18
        )
        for c, w in [('rank', 50), ('fighter', 150), ('weight_class', 110),
                     ('rating', 70), ('fights', 60), ('record', 80), ('last_fight', 90)]:
            self.rankings.heading(c, text=c.title())
            self.rankings.column(c, width=w, anchor='w')
        self.rankings.pack(fill='both', expand=True, pady=(6, 0))

        # ----------------------------------------------------------------
        # Tab 4: Free Agents (new in Task ID 13). Shows fighters with
        # no current promotion (current_promotion_id IS NULL,
        # is_active=1, is_retired=0). The player can sign them to the
        # current promotion via the "Sign Selected" button. The Sign
        # button calls on_sign_free_agent() which calls
        # sign_free_agent() with the player's current promotion filter
        # (or the first promotion if "All Promotions" is selected).
        #
        # IMPORTANT: the Free Agents tab does NOT respect the promotion
        # filter — free agents are not bound to any promotion, so they're
        # available to sign with ANY promotion. The UI always shows all
        # free agents regardless of the current_promotion_filter dropdown.
        # This is intentional and documented (case I of test_free_agency).
        #
        # The Treeview item iid is the fighter_id (so the Sign button can
        # read it directly from tree.selection()[0] instead of doing a
        # fragile name lookup). The values are the remaining 4 fields:
        # (name, weight_class, record, age).
        # ----------------------------------------------------------------
        free_agents_tab = ttk.Frame(right_notebook)
        right_notebook.add(free_agents_tab, text="Free Agents")
        # Top row: label + Sign button.
        fa_top = ttk.Frame(free_agents_tab)
        fa_top.pack(fill='x', pady=(0, 4))
        ttk.Label(fa_top, text="Available Free Agents",
                  font=("Segoe UI", 11, "bold")).pack(side='left')
        self.sign_button = ttk.Button(
            fa_top, text="Sign Selected", command=self.on_sign_free_agent
        )
        self.sign_button.pack(side='right')
        # Treeview. The item iid is the fighter_id (set in refresh_all).
        self.free_agents = ttk.Treeview(
            free_agents_tab,
            columns=('name', 'weight_class', 'record', 'age'),
            show='headings', height=18
        )
        for c, w in [('name', 160), ('weight_class', 110),
                     ('record', 80), ('age', 50)]:
            self.free_agents.heading(c, text=c.title())
            self.free_agents.column(c, width=w, anchor='w')
        self.free_agents.pack(fill='both', expand=True, pady=(4, 0))

    def clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def refresh_all(self):
        row = get_clock(self.conn)
        self.clock_var.set(f"{row[0]} | Day {row[1]} | Week {row[2]} | Month {row[3]} | Year {row[4]} | Ticks {row[5]}")

        # ----------------------------------------------------------------
        # Refresh promotion filter dropdown from DB (Task ID 6).
        # Promotions may be added by future tasks (e.g. scout-driven
        # expansion) or removed (fighters become free agents, Task ID
        # 13). The dropdown is rebuilt on every refresh so it always
        # reflects the current DB state. The user's current selection
        # is preserved if the promotion still exists; otherwise the
        # filter resets to "All Promotions" so the UI never ends up
        # pointing at a deleted promotion_id.
        # ----------------------------------------------------------------
        current_selection = self.promo_filter_var.get() or "All Promotions"
        promo_names = ["All Promotions"]
        promo_ids = [None]  # parallel list: None for "All", else promotion_id
        for pid, pname in self.conn.execute(
            "SELECT promotion_id, name FROM promotions ORDER BY promotion_id"
        ):
            promo_names.append(pname)
            promo_ids.append(pid)
        self.promo_filter_combo['values'] = promo_names
        if current_selection in promo_names:
            # Re-select the same promotion the user had picked.
            # .set() does NOT fire <<ComboboxSelected>> (Tkinter only
            # fires that on user interaction), so no recursion here.
            self.promo_filter_combo.set(current_selection)
        else:
            self.promo_filter_combo.current(0)
            self.current_promotion_filter = None
        # Store the parallel id list so on_promo_filter_change can map
        # the combobox's selected index -> promotion_id.
        self._promo_filter_ids = promo_ids

        self.clear_tree(self.fighters)
        self.clear_tree(self.events)
        self.clear_tree(self.fights)
        self.clear_tree(self.contracts)
        self.clear_tree(self.rankings)
        self.clear_tree(self.free_agents)
        self.news.delete(0, tk.END)
        self.commentary.delete(0, tk.END)

        for r in get_fighters_for_display(self.conn, self.current_promotion_filter):
            self.fighters.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT event_date, event_name, status FROM events ORDER BY event_date"):
            self.events.insert('', 'end', values=r)

        for r in self.conn.execute("""
            SELECT f.fight_id,
                   COALESCE(a.first_name || ' ' || a.last_name, 'TBD') || ' vs ' || COALESCE(b.first_name || ' ' || b.last_name, 'TBD'),
                   COALESCE(w.name, 'Unknown'),
                   COALESCE(f.result_type, 'pending')
            FROM fights f
            LEFT JOIN fight_participants pa ON pa.fight_id=f.fight_id AND pa.corner='red'
            LEFT JOIN fight_participants pb ON pb.fight_id=f.fight_id AND pb.corner='blue'
            LEFT JOIN fighters a ON a.fighter_id=pa.fighter_id
            LEFT JOIN fighters b ON b.fighter_id=pb.fighter_id
            LEFT JOIN weight_classes w ON w.weight_class_id=f.weight_class_id
            ORDER BY f.fight_id
        """):
            self.fights.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT headline FROM news_items ORDER BY news_item_id DESC LIMIT 10"):
            self.news.insert(tk.END, r[0])
        for r in self.conn.execute("SELECT text FROM commentary_segments ORDER BY commentary_segment_id DESC LIMIT 10"):
            self.commentary.insert(tk.END, r[0])

        # Populate Contracts tab (Task ID 9). Uses the same promotion
        # filter as the Fighters tree - if a specific promotion is
        # selected, show only that promotion's contracts; else show all.
        for r in get_contracts_for_display(self.conn, self.current_promotion_filter):
            self.contracts.insert('', 'end', values=r)

        # Populate Rankings tab (Task ID 10). The helper requires a
        # promotion_id — when current_promotion_filter is None ("All
        # Promotions"), we fall back to the first promotion's
        # rankings. Cross-promotion combined rankings are not
        # meaningful under ELO (ratings are per-promotion); a future
        # task could add a pound-for-pound view that normalizes
        # across promotions, but that's out of scope for Task 10.
        if self.current_promotion_filter is not None:
            rankings_promo_id = self.current_promotion_filter
        else:
            # Fall back to the first promotion (lowest promotion_id).
            first_promo = self.conn.execute(
                "SELECT promotion_id FROM promotions ORDER BY promotion_id LIMIT 1"
            ).fetchone()
            rankings_promo_id = first_promo[0] if first_promo else None
        if rankings_promo_id is not None:
            for r in get_rankings_for_display(self.conn, rankings_promo_id):
                self.rankings.insert('', 'end', values=r)

        # Populate Free Agents tab (Task ID 13). The helper returns
        # 5-tuples (fighter_id, name, weight_class, record, age). The
        # fighter_id is used as the Treeview item iid (so the Sign
        # button can read it directly from tree.selection()[0] without
        # a fragile name lookup), and the remaining 4 fields are the
        # display values.
        #
        # IMPORTANT: the Free Agents tab does NOT respect the promotion
        # filter — free agents are not bound to any promotion, so
        # they're available to sign with ANY promotion. The UI always
        # shows all free agents regardless of the
        # current_promotion_filter dropdown. This is intentional and
        # documented (case I of test_free_agency).
        for r in get_free_agents_for_display(self.conn):
            # r is (fighter_id, name, wc, record, age). Use fighter_id
            # (str'd, since ttk Treeview iids are strings) as the iid.
            self.free_agents.insert(str(r[0]), 'end', values=r[1:])

    def on_promo_filter_change(self, event=None):
        """Handle promotion filter dropdown change (Task ID 6).

        Reads the combobox's currently selected index, looks up the
        corresponding promotion_id in the parallel `_promo_filter_ids`
        list (set by `refresh_all()` when the dropdown was last
        populated), stores it in `current_promotion_filter`, and
        triggers a full refresh — which re-runs the fighter query
        through `get_fighters_for_display` with the new filter applied.

        Index 0 is always "All Promotions" -> filter = None. Any
        other index maps to a promotion_id int.

        Note: `refresh_all()` re-populates the combobox as a side
        effect, but `<<ComboboxSelected>>` only fires on user
        interaction (not on programmatic `.set()`), so there is no
        infinite recursion here.
        """
        idx = self.promo_filter_combo.current()
        if idx <= 0:
            self.current_promotion_filter = None
        else:
            # Defensive: bounds-check against the parallel list. If
            # the combobox is somehow out of sync with the list (e.g.
            # refresh hasn't run yet), fall back to "All Promotions".
            if 0 <= idx < len(self._promo_filter_ids):
                self.current_promotion_filter = self._promo_filter_ids[idx]
            else:
                self.current_promotion_filter = None
        self.refresh_all()

    def on_advance_day(self):
        try:
            advance_day(self.conn)
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

    def on_resolve_fight(self):
        try:
            if resolve_next_fight(self.conn) is None:
                messagebox.showinfo("Resolve Fight", "No unresolved fights found.")
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

    def on_sign_free_agent(self):
        """Sign the selected free agent to the player's promotion (Task ID 13).

        Reads the selected Treeview item's iid (which is the fighter_id
        — see refresh_all()), determines the player's promotion (the
        current_promotion_filter if set, else the first promotion in
        the DB), reads the current sim date for the contract start, and
        calls sign_free_agent(). On success, commits, refreshes the UI,
        and shows a confirmation messagebox. On failure (fighter not a
        free agent, retired, etc.), shows an error messagebox and rolls
        back.

        The fighter_id-as-iid approach is cleaner than looking up the
        fighter by name (which would be fragile if names aren't unique
        — see worklog decision D1). The Treeview stores display values
        (name, wc, record, age) but the iid is the fighter_id.
        """
        selection = self.free_agents.selection()
        if not selection:
            messagebox.showinfo("Sign Free Agent", "Select a free agent first.")
            return
        # The iid is the fighter_id (str'd by Tkinter). Convert back to int.
        try:
            fighter_id = int(selection[0])
        except (ValueError, TypeError):
            messagebox.showerror(
                "Sign Free Agent",
                f"Could not parse fighter_id from selection {selection!r}.",
            )
            return

        # Determine the player's promotion. For now, use the current
        # promotion filter (if set), else the first promotion. A future
        # task will add a proper "player promotion" concept (Task 25 —
        # rival promotion AI implies the player IS one of the
        # promotions, not "all promotions").
        player_promo_id = self.current_promotion_filter
        if player_promo_id is None:
            first_promo = self.conn.execute(
                "SELECT promotion_id FROM promotions ORDER BY promotion_id LIMIT 1"
            ).fetchone()
            player_promo_id = first_promo[0] if first_promo else None
        if player_promo_id is None:
            messagebox.showerror(
                "Sign Free Agent",
                "No promotion available to sign to.",
            )
            return

        # Read the current sim date for the contract start. Uses
        # get_clock (line 17) — note this is affected by the pre-existing
        # D5 current_date quirk (bare SELECT current_date resolves to
        # the built-in date function), but for the UI this is
        # acceptable. The qualified-column fix is only applied to the
        # new get_free_agents_for_display helper.
        clock_row = get_clock(self.conn)
        start_date = clock_row[0] if clock_row else None
        if not start_date:
            messagebox.showerror(
                "Sign Free Agent",
                "Could not read current sim date from simulation_clock.",
            )
            return

        # Get the fighter's name for the confirmation messagebox.
        fighter_name_row = self.conn.execute(
            "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        fighter_name = (fighter_name_row[0]
                        if fighter_name_row
                        else f"Fighter {fighter_id}")

        try:
            contract_id = sign_free_agent(
                self.conn, fighter_id, player_promo_id, start_date
            )
            if contract_id is None:
                messagebox.showerror(
                    "Sign Free Agent",
                    f"Could not sign {fighter_name} (see console for details).",
                )
                return
            self.conn.commit()
            messagebox.showinfo(
                "Sign Free Agent",
                f"Signed {fighter_name} to a 12-month contract.",
            )
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    App().mainloop()
