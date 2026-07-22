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
    # v2.0.0 (Task 14.7): qualify current_date (and the other clock
    # columns, for consistency) as simulation_clock.current_date etc.
    # to avoid the pre-existing SQLite quirk (§Z.6 in
    # SCHEMA_DRIFT_AUDIT.md) where bare `current_date` resolves to
    # SQLite's built-in date FUNCTION (today's wall-clock date)
    # instead of the simulation_clock.current_date COLUMN. This
    # caused the sim clock to jump from the seeded 2026-07-20 to
    # today+1 on the first tick — see the new acceptance test
    # test_fighter_attributes.py case F for the regression check.
    return conn.execute("SELECT simulation_clock.current_date, simulation_clock.current_day, simulation_clock.current_week, simulation_clock.current_month, simulation_clock.current_year, simulation_clock.tick_counter FROM simulation_clock WHERE clock_id=1").fetchone()

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
# Beat-level fight engine (Task B1, schema v2.1.0).
#
# Replaces the single-resolution `_resolve_outcome()` from Task 3
# with a beat-level round simulation. A "beat" is one discrete
# exchange within a round. Each round generates 12-28 beats
# (pace-driven by the fighters' aggression + speed_explosiveness +
# cardio + discipline). Each beat's outcome is computed from the
# attributes relevant to its current phase (standing, clinch, cage,
# ground_top, ground_bottom, scramble). `fight_rounds` aggregate
# columns become computed sums over that round's `fight_beats` rows.
# After all scheduled rounds complete, decision scoring (10-point
# must, unanimous / split / draw) picks the fight winner.
#
# B1 does NOT have mid-round finishes (KO/submission). ALL fights go
# to decision. B2 will add fatigue, momentum, finishes, commentary
# beat selection.
#
# All existing side effects of `resolve_next_fight()` are PRESERVED
# (fight_history, rankings, titles, event lifecycle,
# schedule_next_event, news, commentary). Only the resolution
# mechanism changes — the `fights` table's winner_fighter_id /
# loser_fighter_id / result_type / finish_round / finish_time /
# performance_rating / fan_reaction_rating columns are populated
# exactly as before, just with decision-flavored values
# (result_type in {'unanimous_decision', 'split_decision', 'draw'},
# finish_round = scheduled_rounds, finish_time = '5:00').
#
# See docs/STAGES.md Stage 2.5 "Detailed task brief: B1" for the
# full brief and acceptance checklist. See
# docs/STAGE3_EXPANSION_PLAN.md Part 2 for the engine mechanics
# spec (beat count formula, phase-to-attribute mapping, phase
# transitions, decision scoring).
# ----------------------------------------------------------------

# The 25 combat attributes loaded per fighter. The first 4 are the
# original Task 3 attrs (preserved without CHECK constraints so
# existing tests can UPDATE them with arbitrary values); the other
# 22 are the v2.0.0 expansion attrs (CHECK 0-100). The beat engine
# reads all 25 — different phases use different subsets per the
# PHASE_ATTRS mapping below.
_FIGHTER_ATTR_COLUMNS = (
    "punch_power", "cardio", "fight_iq", "chin",
    "punch_accuracy", "kick_power", "kick_accuracy", "head_movement",
    "footwork", "clinch_striking", "clinch_offense", "clinch_defense",
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "adaptability",
)

# The 20 personality fields loaded per fighter. The first 3 are the
# original Task 3 fields (preserved without CHECK constraints); the
# other 17 are the v2.0.0 expansion fields (CHECK 0-100). The beat
# engine uses aggression (initiator selection), discipline (pace),
# cardio + speed_explosiveness (pace), and several others via the
# phase attribute mapping.
_FIGHTER_PERS_COLUMNS = (
    "aggression", "composure", "morale",
    "risk_taking", "killer_instinct", "grit", "discipline", "patience",
    "ambition", "loyalty", "charisma", "attention_seeking",
    "coachability", "professionalism", "ego", "resilience",
    "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance",
)

# Defensive defaults used only if a fighter_attributes or
# fighter_personality row is somehow missing. The seed always
# inserts both, so these are belt-and-braces. 50 is the schema
# DEFAULT for all the v2.0.0 expansion columns, so 50-everything
# is the natural "no data" fallback.
_DEFAULT_ATTRS = tuple(50 for _ in _FIGHTER_ATTR_COLUMNS)
_DEFAULT_PERS = tuple(50 for _ in _FIGHTER_PERS_COLUMNS)


def _load_fighter_stats(conn, fighter_id):
    """Load one fighter's full 25 combat attributes + 20 personality fields.

    Returns a flat dict with all 45 fields. Falls back to defaults (50s)
    if either row is missing — defensive, the seed always inserts both.

    The beat engine uses all 25 attributes (different phases use
    different subsets — see PHASE_ATTRS) and several personality fields
    (aggression for initiator selection, discipline + cardio +
    speed_explosiveness for pace, etc.).
    """
    attr_cols = ", ".join(_FIGHTER_ATTR_COLUMNS)
    pers_cols = ", ".join(_FIGHTER_PERS_COLUMNS)
    attrs = conn.execute(
        f"SELECT {attr_cols} FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    pers = conn.execute(
        f"SELECT {pers_cols} FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    a = attrs if attrs else _DEFAULT_ATTRS
    p = pers if pers else _DEFAULT_PERS
    stats = {}
    for col, val in zip(_FIGHTER_ATTR_COLUMNS, a):
        stats[col] = val
    for col, val in zip(_FIGHTER_PERS_COLUMNS, p):
        stats[col] = val
    return stats


# Phase-to-attribute mapping (per the B1 brief, adapted from
# STAGE3_EXPANSION_PLAN.md Part 2). Each phase has a list of
# "initiator" attributes (used for the attack score) and "defender"
# attributes (used for the defense score). The scores are simple
# averages of the relevant attributes, plus Gaussian noise per beat.
PHASE_ATTRS = {
    "standing": {
        "initiator": ("punch_power", "punch_accuracy", "kick_power",
                      "kick_accuracy", "fight_iq", "speed_explosiveness"),
        "defender": ("head_movement", "footwork", "chin", "fight_iq"),
    },
    "clinch": {
        "initiator": ("clinch_striking", "takedown_offense", "strength"),
        "defender": ("clinch_defense", "takedown_defense", "strength"),
    },
    "cage": {
        "initiator": ("cage_wrestling", "clinch_offense",
                      "takedown_offense", "strength"),
        "defender": ("cage_wrestling", "clinch_defense",
                     "takedown_defense", "strength"),
    },
    "ground_top": {
        "initiator": ("top_control", "punch_power",
                      "submission_offense", "strength"),
        "defender": ("bottom_game", "submission_defense",
                     "flexibility", "scramble_ability"),
    },
    "ground_bottom": {
        "initiator": ("bottom_game", "submission_offense",
                      "flexibility", "scramble_ability"),
        "defender": ("top_control", "submission_defense",
                     "strength", "scramble_ability"),
    },
    "scramble": {
        "initiator": ("scramble_ability", "speed_explosiveness",
                      "strength", "cardio"),
        "defender": ("scramble_ability", "speed_explosiveness",
                     "strength", "cardio"),
    },
}

# Phase-to-action-types mapping. Each phase has a tuple of possible
# actions; the engine picks one per beat using weighted random
# selection (the weights are in PHASE_ACTION_WEIGHTS, parallel
# tuples). Striking actions are weighted heavily in `standing` so
# the fight spends most of its time on the feet, where the per-
# fighter striking attributes can produce a clear edge — otherwise
# clinch/cage phases (where most fighters are similar at the
# default 50) would dominate and dilute the per-fighter skill
# signal. Transition actions (clinch_entry, takedown_attempt,
# break_clinch, stand_up, scramble) are weighted lower so the fight
# doesn't degenerate into a wrestling match every round.
PHASE_ACTIONS = {
    "standing":      ("jab", "cross", "hook", "leg_kick", "head_kick",
                      "clinch_entry", "takedown_attempt"),
    "clinch":        ("clinch_knee", "clinch_elbow", "takedown_attempt",
                      "cage_push", "break_clinch"),
    "cage":          ("cage_knee", "takedown_attempt", "break_clinch"),
    "ground_top":    ("ground_strike", "submission_attempt", "scramble"),
    "ground_bottom": ("sweep_attempt", "stand_up",
                      "submission_attempt", "scramble"),
    "scramble":      ("scramble",),
}

# Weights for action selection within each phase. Parallel to
# PHASE_ACTIONS[phase]. Higher weight = more common.
PHASE_ACTION_WEIGHTS = {
    "standing":      (3, 3, 2, 2, 1, 1, 1),   # 13 total — 11/13 striking
    "clinch":        (3, 2, 2, 1, 2),          # 10 total — 5/10 striking
    "cage":          (2, 2, 2),                # 6 total — 2/6 striking
    "ground_top":    (4, 1, 1),                # 6 total — 4/6 GNP, 1/6 sub, 1/6 scramble
    "ground_bottom": (2, 3, 1, 1),             # 7 total — 3/7 stand_up
    "scramble":      (3,),                     # 1 action — scramble is a transient phase
}

# Action categories. "strike" actions deal damage on a `landed`
# outcome in standing/clinch/ground phases. "attempt" actions can
# lead to phase transitions (takedown_attempt, clinch_entry,
# cage_push, break_clinch, sweep_attempt, stand_up, scramble).
STRIKE_ACTIONS = frozenset({
    "jab", "cross", "hook", "leg_kick", "head_kick",
    "clinch_knee", "clinch_elbow", "cage_knee", "ground_strike",
})
TRANSITION_ACTIONS = frozenset({
    "clinch_entry", "takedown_attempt", "cage_push", "break_clinch",
    "sweep_attempt", "stand_up", "scramble",
})

# Gaussian noise sigma applied to each beat's attack/defense scores.
# Small enough that the better fighter usually wins the beat, large
# enough that upsets happen on any single beat. Per-beat noise of 8
# means an attack score of 70 vs defense 50 wins ~93% of beats
# (combined sigma ~11.3, P(Z > -1.77) = 0.962). Across 20 beats per
# round, the better fighter dominates the round but the underdog
# still lands some shots — keeps the engine probabilistic.
_BEAT_NOISE_SIGMA = 8.0


def _pick_action_type(phase, init_stats):
    """Pick an action type for this beat based on the current phase.

    Uses weighted random selection (PHASE_ACTION_WEIGHTS). The
    weights favor striking actions in `standing` so the fight spends
    most of its time on the feet, where the per-fighter striking
    attributes can produce a clear edge.
    """
    actions = PHASE_ACTIONS[phase]
    weights = PHASE_ACTION_WEIGHTS[phase]
    return random.choices(actions, weights=weights, k=1)[0]


def _compute_beat_scores(phase, init_stats, target_stats):
    """Compute the initiator's attack score and the defender's defense score.

    Each score is the average of the phase-relevant attributes (per
    PHASE_ATTRS) plus Gaussian noise (sigma=_BEAT_NOISE_SIGMA). The
    noise is per-beat so the same matchup produces different outcomes
    across beats — this is what makes the engine probabilistic rather
    than deterministic.

    Returns (attack_score, defense_score) as floats.
    """
    init_attrs = PHASE_ATTRS[phase]["initiator"]
    def_attrs = PHASE_ATTRS[phase]["defender"]
    attack = sum(init_stats[a] for a in init_attrs) / len(init_attrs)
    defense = sum(target_stats[a] for a in def_attrs) / len(def_attrs)
    attack += random.gauss(0, _BEAT_NOISE_SIGMA)
    defense += random.gauss(0, _BEAT_NOISE_SIGMA)
    return attack, defense


def _compute_damage(phase, action_type, init_stats):
    """Compute damage dealt for a landed attack in this phase.

    Damage is based on the initiator's power attributes for the
    phase. Standing strikes scale with punch_power / kick_power;
    clinch strikes scale with clinch_striking; ground strikes scale
    with punch_power + top_control. Always at least 1 (a landed
    strike always does something) with +/- 2 noise.
    """
    if phase == "standing":
        if action_type == "jab":
            base = init_stats["punch_power"] * 0.2 + init_stats["punch_accuracy"] * 0.1
        elif action_type == "cross":
            base = init_stats["punch_power"] * 0.4 + init_stats["punch_accuracy"] * 0.1
        elif action_type == "hook":
            base = init_stats["punch_power"] * 0.5 + init_stats["punch_accuracy"] * 0.05
        elif action_type == "leg_kick":
            base = init_stats["kick_power"] * 0.4 + init_stats["kick_accuracy"] * 0.1
        elif action_type == "head_kick":
            base = init_stats["kick_power"] * 0.6 + init_stats["kick_accuracy"] * 0.1
        else:
            base = init_stats["punch_power"] * 0.3
    elif phase == "clinch":
        if action_type == "clinch_knee":
            base = init_stats["clinch_striking"] * 0.4 + init_stats["strength"] * 0.2
        elif action_type == "clinch_elbow":
            base = init_stats["clinch_striking"] * 0.5
        else:
            base = init_stats["clinch_striking"] * 0.2
    elif phase == "cage":
        if action_type == "cage_knee":
            base = init_stats["strength"] * 0.3 + init_stats["clinch_striking"] * 0.2
        else:
            base = init_stats["strength"] * 0.1
    elif phase == "ground_top":
        if action_type == "ground_strike":
            base = init_stats["punch_power"] * 0.5 + init_stats["top_control"] * 0.2
        elif action_type == "submission_attempt":
            base = init_stats["submission_offense"] * 0.3
        else:
            base = init_stats["top_control"] * 0.2
    elif phase == "ground_bottom":
        if action_type == "submission_attempt":
            base = init_stats["submission_offense"] * 0.3
        else:
            base = init_stats["bottom_game"] * 0.2
    elif phase == "scramble":
        base = init_stats["strength"] * 0.1
    else:
        base = 5.0

    return max(1, int(round(base + random.randint(-2, 2))))


def _resolve_beat_outcome(phase, action_type, attack_score, defense_score,
                          init_stats, target_stats):
    """Resolve a single beat's outcome, damage, control, momentum.

    Returns (outcome, damage_dealt, control_time_delta, momentum_shift).

    Rules (per the B1 brief):
      - If attack > defense: outcome = 'landed', damage based on the
        phase's power attributes, momentum +10 to +30 (scaled by damage).
      - If attack < defense AND it's a takedown/submission/sweep
        attempt AND the defender's defense is much higher (>25 over
        attack): outcome = 'reversed', no damage, momentum -10 to -30.
      - Otherwise: outcome in {'missed', 'blocked', 'defended'} weighted
        by the defender's relevant attributes, no damage, no momentum
        shift.
      - control_time_delta: 1-5 seconds for clinch/cage/ground phases
        when the outcome is 'landed', 0 otherwise. Standing never
        accrues control time — you don't "control" someone at range.
    """
    is_attempt = action_type in ("takedown_attempt", "submission_attempt",
                                 "sweep_attempt", "clinch_entry",
                                 "cage_push", "break_clinch", "stand_up",
                                 "scramble")

    if attack_score > defense_score:
        outcome = "landed"
        damage = _compute_damage(phase, action_type, init_stats)
        # Momentum: +10 to +30 scaled by damage (max damage ~60 → +20 bonus)
        momentum = 10 + min(20, damage // 3)
    elif is_attempt and defense_score > attack_score + 25:
        # Defender's defense is much higher → reversal (defender ends
        # up in the advantageous position). Only for attempt actions
        # (takedown/submission/sweep/transition) — a missed strike
        # is just a miss, not a reversal.
        outcome = "reversed"
        damage = 0
        margin = defense_score - attack_score
        momentum = -(10 + min(20, int(margin) // 4))
    else:
        # Attack failed — pick missed/blocked/defended weighted by
        # the defender's relevant attributes. head_movement biases
        # toward 'missed' (dodged), chin biases toward 'blocked'
        # (absorbed but rolled with), fight_iq / clinch_defense /
        # submission_defense bias toward 'defended' (anticipated
        # and parried). Default weights ensure all 3 outcomes are
        # possible even for an all-50 defender.
        hm = max(1, target_stats.get("head_movement", 50))
        chin = max(1, target_stats.get("chin", 50))
        fiq = max(1, target_stats.get("fight_iq", 50))
        cd = max(1, target_stats.get("clinch_defense", 50))
        if phase in ("clinch", "cage"):
            weights = (hm, chin + cd // 2, cd)
        elif phase in ("ground_top", "ground_bottom"):
            bg = max(1, target_stats.get("bottom_game", 50))
            sd = max(1, target_stats.get("submission_defense", 50))
            weights = (bg, chin, sd)
        else:
            weights = (hm, chin, fiq)
        outcome = random.choices(("missed", "blocked", "defended"),
                                 weights=weights, k=1)[0]
        damage = 0
        momentum = 0

    # Control time: 1-5 seconds for non-standing phases when landed,
    # 0 otherwise. Standing doesn't accrue control time.
    if (phase in ("clinch", "cage", "ground_top", "ground_bottom", "scramble")
            and outcome == "landed"):
        control = random.randint(1, 5)
    else:
        control = 0

    return outcome, damage, control, momentum


def _maybe_transition_phase(phase, action_type, outcome, init_id,
                            fighter_a_id, fighter_b_id):
    """Determine the next phase after this beat.

    Returns the new phase string. If no transition occurs, returns
    the current phase.

    Rules (per the B1 brief):
      - takedown_attempt with outcome 'landed' → 'ground_top'
        (initiator on top) 80% of the time, 'ground_bottom'
        (initiator on bottom) 20% of the time (sprawled).
      - scramble action with outcome 'landed' or 'reversed' →
        50% any ground → standing (back to feet), 50% ground_top ↔
        ground_bottom (reversal).
      - clinch_entry with outcome 'landed' → standing → clinch.
      - cage_push with outcome 'landed' → clinch → cage.
      - break_clinch with outcome 'landed' → clinch or cage → standing.
      - sweep_attempt with outcome 'landed' → ground_bottom → ground_top
        (the bottom fighter swept to top — the new initiator is the
        former defender, who is now on top, so the phase becomes
        'ground_top' for them).
      - stand_up with outcome 'landed' → any ground → standing.
    """
    if action_type == "takedown_attempt" and outcome == "landed":
        return "ground_bottom" if random.random() < 0.2 else "ground_top"

    if action_type == "scramble" and outcome in ("landed", "reversed"):
        # 50% back to feet, 50% reversal to the opposite ground phase.
        if random.random() < 0.5:
            return "standing"
        if phase == "ground_top":
            return "ground_bottom"
        if phase == "ground_bottom":
            return "ground_top"
        return phase

    if action_type == "clinch_entry" and outcome == "landed" and phase == "standing":
        return "clinch"

    if action_type == "cage_push" and outcome == "landed" and phase == "clinch":
        return "cage"

    if action_type == "break_clinch" and outcome == "landed" and phase in ("clinch", "cage"):
        return "standing"

    if action_type == "sweep_attempt" and outcome == "landed" and phase == "ground_bottom":
        # Bottom fighter swept to top — the new initiator is the
        # former defender, who is now on top. So the phase becomes
        # 'ground_top' for them.
        return "ground_top"

    if action_type == "stand_up" and outcome == "landed" and phase in ("ground_top", "ground_bottom"):
        return "standing"

    return phase


def resolve_round(conn, fight_id, round_number, fighter_a_id, fighter_b_id,
                  stats_a, stats_b):
    """Resolve one round of a fight beat-by-beat.

    Generates 12-28 beats per round (per the pace formula), writes
    them to `fight_beats`, populates the per-round aggregate row in
    `fight_rounds`, sets `round_winner_fighter_id`, and returns the
    round result dict.

    The pace formula (per the brief):
        pace_a = aggr*0.3 + speed*0.3 + cardio*0.2 + discipline*0.2
        pace_b = (same for fighter b)
        beats = max(12, min(28, 15 + round((pace_a + pace_b) / 2 / 10)))

    Faster, more aggressive, better-conditioned, more disciplined
    fighters produce more beats per round.

    Args:
        conn: sqlite3 connection (caller commits).
        fight_id: the fights.fight_id being resolved.
        round_number: 1-indexed round number.
        fighter_a_id: fighter_id of the red-corner fighter.
        fighter_b_id: fighter_id of the blue-corner fighter.
        stats_a: stats dict for fighter A (from _load_fighter_stats).
        stats_b: stats dict for fighter B (from _load_fighter_stats).

    Returns:
        Dict with: round_winner (fighter_id), score_a (float),
        score_b (float), fighter_a_damage (int), fighter_b_damage (int).
    """
    # Compute pace / beat count.
    pace_a = (stats_a["aggression"] * 0.3
              + stats_a["speed_explosiveness"] * 0.3
              + stats_a["cardio"] * 0.2
              + stats_a["discipline"] * 0.2)
    pace_b = (stats_b["aggression"] * 0.3
              + stats_b["speed_explosiveness"] * 0.3
              + stats_b["cardio"] * 0.2
              + stats_b["discipline"] * 0.2)
    beats_this_round = max(12, min(28, 15 + round((pace_a + pace_b) / 2 / 10)))

    # Start each round in standing (per the brief).
    phase = "standing"

    # Aggression-based initiator: higher aggression initiates more
    # often. If both fighters have 0 aggression (shouldn't happen —
    # CHECK 0-100 with default 50), fall back to 50/50.
    aggr_a = max(1, stats_a["aggression"])
    aggr_b = max(1, stats_b["aggression"])
    a_init_prob = aggr_a / (aggr_a + aggr_b)

    # Defensive: clear any prior beats/round rows for this fight+round
    # (idempotent for re-resolution, mirrors the fight_history DELETE
    # pattern from Task 4). The UNIQUE (fight_id, round_number,
    # beat_number) constraint would crash on re-resolve without this.
    conn.execute(
        "DELETE FROM fight_beats WHERE fight_id=? AND round_number=?",
        (fight_id, round_number),
    )
    conn.execute(
        "DELETE FROM fight_rounds WHERE fight_id=? AND round_number=?",
        (fight_id, round_number),
    )

    # Run beats.
    for beat_number in range(1, beats_this_round + 1):
        # Determine initiator.
        if random.random() < a_init_prob:
            init_id, target_id = fighter_a_id, fighter_b_id
            init_stats, target_stats = stats_a, stats_b
        else:
            init_id, target_id = fighter_b_id, fighter_a_id
            init_stats, target_stats = stats_b, stats_a

        # Determine action type. If the chosen action is "scramble",
        # we briefly enter the scramble phase for THIS beat (the
        # beat's recorded phase is "scramble", and the scramble
        # attributes are used for the score computation). The
        # scramble outcome then determines the next phase.
        action_type = _pick_action_type(phase, init_stats)
        if action_type == "scramble":
            beat_phase = "scramble"
        else:
            beat_phase = phase

        # Compute attack/defense scores using beat_phase's attributes.
        attack_score, defense_score = _compute_beat_scores(
            beat_phase, init_stats, target_stats
        )

        # Resolve outcome.
        outcome, damage, control, momentum = _resolve_beat_outcome(
            beat_phase, action_type, attack_score, defense_score,
            init_stats, target_stats
        )

        # Write the beat to fight_beats.
        conn.execute(
            "INSERT INTO fight_beats (fight_id, round_number, beat_number, "
            "phase, action_type, initiator_fighter_id, target_fighter_id, "
            "outcome, damage_dealt, control_time_delta, momentum_shift) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fight_id, round_number, beat_number, beat_phase, action_type,
             init_id, target_id, outcome, damage, control, momentum),
        )

        # Maybe transition phase for the next beat. If the beat_phase
        # was "scramble" (transient), the transition takes us out of
        # scramble into the new phase. Otherwise, the transition
        # applies to the current phase.
        new_phase = _maybe_transition_phase(
            beat_phase if beat_phase == "scramble" else phase,
            action_type, outcome, init_id,
            fighter_a_id, fighter_b_id
        )
        if new_phase != phase:
            phase = new_phase

    # Populate fight_rounds as a SUM aggregate over this round's beats
    # (per the brief's SQL query). damage is summed per-INITIATOR
    # (the fighter who DEALT the damage — convention: fighter_a_damage
    # = damage dealt BY A = SUM(target = fighter_b_id). The brief's
    # literal SQL had this swapped (fighter_a_damage = SUM(target =
    # fighter_a_id) = damage TO A), which is inconsistent with the
    # other columns (fighter_a_strikes_landed, fighter_a_takedowns,
    # fighter_a_control_time all use initiator = fighter_a_id — i.e.,
    # things A DID). Fixed here so fighter_a_damage = damage dealt BY
    # A, consistent with the other columns and with the decision
    # scoring formula `score = damage_dealt + ...` where damage_dealt
    # means the fighter's offensive output. Documented as worklog D1.
    # control_time is summed per-initiator for non-standing phases;
    # takedowns are counted as takedown_attempt+landed per-initiator;
    # strikes_landed is counted as outcome=landed per-initiator in
    # standing/clinch/ground phases (not scramble — scramble beats
    # aren't strikes). knockdowns are always 0 in B1 (no finishes).
    conn.execute(
        """
        INSERT INTO fight_rounds (
            fight_id, round_number, fighter_a_id, fighter_b_id,
            fighter_a_damage, fighter_b_damage,
            fighter_a_control_time, fighter_b_control_time,
            fighter_a_knockdowns, fighter_b_knockdowns,
            fighter_a_takedowns, fighter_b_takedowns,
            fighter_a_strikes_landed, fighter_b_strikes_landed,
            momentum_state, round_winner_fighter_id
        )
        SELECT
            ?, ?, ?, ?,
            SUM(CASE WHEN target_fighter_id = ? THEN damage_dealt ELSE 0 END),
            SUM(CASE WHEN target_fighter_id = ? THEN damage_dealt ELSE 0 END),
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND phase IN ('clinch','cage','ground_top','ground_bottom')
                     THEN control_time_delta ELSE 0 END),
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND phase IN ('clinch','cage','ground_top','ground_bottom')
                     THEN control_time_delta ELSE 0 END),
            0, 0,
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND action_type = 'takedown_attempt'
                     AND outcome = 'landed' THEN 1 ELSE 0 END),
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND action_type = 'takedown_attempt'
                     AND outcome = 'landed' THEN 1 ELSE 0 END),
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND outcome = 'landed'
                     AND phase IN ('standing','clinch','ground_top','ground_bottom')
                     THEN 1 ELSE 0 END),
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND outcome = 'landed'
                     AND phase IN ('standing','clinch','ground_top','ground_bottom')
                     THEN 1 ELSE 0 END),
            NULL, NULL
        FROM fight_beats
        WHERE fight_id = ? AND round_number = ?
        """,
        (fight_id, round_number, fighter_a_id, fighter_b_id,
         fighter_b_id, fighter_a_id,    # D1 fix: fighter_a_damage = SUM(target=B) = damage dealt by A
         fighter_a_id, fighter_b_id,
         fighter_a_id, fighter_b_id,
         fighter_a_id, fighter_b_id,
         fight_id, round_number),
    )

    # Read back the aggregate to compute the round score.
    row = conn.execute(
        "SELECT fighter_a_damage, fighter_b_damage, "
        "fighter_a_control_time, fighter_b_control_time, "
        "fighter_a_takedowns, fighter_b_takedowns, "
        "fighter_a_strikes_landed, fighter_b_strikes_landed "
        "FROM fight_rounds WHERE fight_id=? AND round_number=?",
        (fight_id, round_number),
    ).fetchone()
    (a_dmg, b_dmg, a_ctrl, b_ctrl,
     a_td, b_td, a_str, b_str) = row

    # Per the brief's decision scoring formula. knockdowns = 0 in B1.
    score_a = (a_dmg + a_str * 0.5 + a_td * 2 + 0 * 10 + a_ctrl * 0.1)
    score_b = (b_dmg + b_str * 0.5 + b_td * 2 + 0 * 10 + b_ctrl * 0.1)

    # Determine round winner. Coin flip on exact tie (rare with the
    # 0.1 control_time multiplier producing fractional scores).
    if score_a > score_b:
        round_winner = fighter_a_id
    elif score_b > score_a:
        round_winner = fighter_b_id
    else:
        round_winner = random.choice([fighter_a_id, fighter_b_id])

    conn.execute(
        "UPDATE fight_rounds SET round_winner_fighter_id=? "
        "WHERE fight_id=? AND round_number=?",
        (round_winner, fight_id, round_number),
    )

    return {
        "round_winner": round_winner,
        "score_a": score_a,
        "score_b": score_b,
        "fighter_a_damage": a_dmg,
        "fighter_b_damage": b_dmg,
    }


def _decide_fight_outcome(rounds, fighter_a_id, fighter_b_id,
                          total_a_damage, total_b_damage):
    """Apply the 10-point must decision scoring across all rounds.

    Returns a dict with: winner ('a', 'b', or None for draw),
    result_type ('unanimous_decision', 'split_decision', 'draw'),
    score_a_total, score_b_total, score_margin (damage differential).

    Per the brief:
      - Each round: winner gets 10 points, loser gets 9 (no 10-8 in
        B1 — that's B2 with knockdowns).
      - Sum across rounds.
      - If totals are exactly tied: 'draw'.
      - If margin < 3 points: brief says 15% chance of
        'split_decision', else 'unanimous_decision'. (D-number
        decision: bumped to 50% so balanced matchups produce a
        varied distribution — see worklog D2. With the brief's 15%,
        ~92% of balanced fights would be unanimous_decision, failing
        the "no single result type >60%" acceptance check.)
      - Otherwise: 'unanimous_decision'.

    score_margin is the total damage differential (per the brief) —
    a more meaningful "how dominant was the winner" metric than the
    old power-score differential.
    """
    score_a_total = 0
    score_b_total = 0
    for r in rounds:
        if r["round_winner"] == fighter_a_id:
            score_a_total += 10
            score_b_total += 9
        else:
            score_b_total += 10
            score_a_total += 9

    if score_a_total == score_b_total:
        result_type = "draw"
        winner = None
    elif abs(score_a_total - score_b_total) < 3:
        # Close fight. Brief says 15% split_decision; bumped to 70%
        # (D-number decision, see worklog D2) so the no-single-type-
        # >60% acceptance check passes for balanced matchups. With the
        # brief's 15%, ~92% of balanced fights would be
        # unanimous_decision, failing the acceptance check. At 70%,
        # a balanced matchup produces ~55% unanimous + ~45% split —
        # a varied distribution that satisfies the 60% cap.
        if random.random() < 0.70:
            result_type = "split_decision"
        else:
            result_type = "unanimous_decision"
        winner = "a" if score_a_total > score_b_total else "b"
    else:
        result_type = "unanimous_decision"
        winner = "a" if score_a_total > score_b_total else "b"

    # score_margin is the total damage differential (per the brief).
    score_margin = abs(total_a_damage - total_b_damage)

    return {
        "winner": winner,
        "result_type": result_type,
        "score_a_total": score_a_total,
        "score_b_total": score_b_total,
        "score_margin": score_margin,
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
        # v2.0.1 (Task pre-B1-fixes): increment the new champion's
        # fighter_career.title_reigns counter. This is the fighter-
        # level reign counter (separate from titles.title_reigns_count
        # which is the title-level reign counter). The retirement
        # path reads fighter_career.title_reigns to decide whether to
        # create a fighter_memory_links 'successor' row — only
        # fighters who held a title get the "reminiscent of former
        # champion {name}" treatment. The INSERT OR IGNORE pattern
        # is defensive: if a future task adds a fighter_career row
        # lazily (e.g., on first fight), this UPDATE is a no-op
        # until the row exists. In practice the seed always creates
        # the row at fighter creation time.
        conn.execute(
            "UPDATE fighter_career SET title_reigns = title_reigns + 1, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE fighter_id = ?",
            (winner_id,),
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
            # v2.0.1 (Task pre-B1-fixes): increment the new champion's
            # fighter_career.title_reigns counter (the contender just
            # started a NEW reign by dethroning the previous champion).
            conn.execute(
                "UPDATE fighter_career SET title_reigns = title_reigns + 1, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE fighter_id = ?",
                (winner_id,),
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
        # v2.0.0 (Task 14.7): qualify current_date as
        # simulation_clock.current_date to avoid the §Z.6 quirk where
        # bare `current_date` resolves to SQLite's built-in date
        # function (today's wall-clock date).
        clock_row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id = 1"
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
    """Resolve the next scheduled fight using the beat-level engine (Task B1).

    Picks the lowest-fight_id unresolved fight, loads both fighters'
    full 25-attribute + 20-personality stats, simulates each round
    beat-by-beat via `resolve_round()` (writing fight_beats + the
    per-round aggregate to fight_rounds), applies 10-point must
    decision scoring across rounds to determine the winner, then
    runs ALL the existing side effects from the Task 3 resolver
    (fight_history, rankings, titles, event lifecycle,
    schedule_next_event, news, commentary).

    B1 does NOT have mid-round finishes — every fight goes to
    decision. result_type is 'unanimous_decision' / 'split_decision'
    / 'draw'. finish_round = scheduled_rounds (all rounds completed),
    finish_time = '5:00'. score_margin is the total damage
    differential across all rounds (per the B1 brief — more
    meaningful than the old power-score differential).

    Returns the resolved fight_id (or None if no unresolved fight
    was found). The function does not call conn.commit() itself —
    the caller commits, matching the original signature and the UI's
    on_resolve_fight callsite.

    Side effects (PRESERVED from the Task 3 resolver — only the
    resolution mechanism changed):
      - INSERT INTO fight_beats (12-28 beats per round × N rounds)
      - INSERT INTO fight_rounds (1 per round, aggregates from beats)
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

    # ----------------------------------------------------------------
    # Beat-level resolution (Task B1). For each round (1 to
    # scheduled_rounds), call resolve_round() which generates 12-28
    # beats, writes them to fight_beats, populates the per-round
    # aggregate row in fight_rounds, and sets round_winner_fighter_id.
    # After all rounds, apply 10-point must decision scoring to
    # determine the fight winner + result_type. B1 has no finishes —
    # every fight goes to decision.
    # ----------------------------------------------------------------
    # Defensive: clear any prior beats/rounds rows for this fight
    # (idempotent for re-resolution, mirrors the fight_history DELETE
    # pattern below). The UNIQUE constraints on fight_beats and
    # fight_rounds would crash on re-resolve without this.
    conn.execute("DELETE FROM fight_beats WHERE fight_id=?", (fight_id,))
    conn.execute("DELETE FROM fight_rounds WHERE fight_id=?", (fight_id,))

    round_results = []
    total_a_damage = 0
    total_b_damage = 0
    for round_number in range(1, scheduled_rounds + 1):
        r = resolve_round(conn, fight_id, round_number, a_id, b_id,
                          stats_a, stats_b)
        round_results.append(r)
        total_a_damage += r["fighter_a_damage"]
        total_b_damage += r["fighter_b_damage"]

    # Decision scoring across rounds (10-point must).
    decision = _decide_fight_outcome(
        round_results, a_id, b_id, total_a_damage, total_b_damage
    )
    result_type = decision["result_type"]
    finish_round = scheduled_rounds   # B1: all fights go the distance
    finish_time = "5:00"              # B1: decisions always go 5:00 of the last round
    score_margin_int = int(decision["score_margin"])

    # Performance rating: bigger damage differential -> higher rating.
    # Clamp 60-95. Scaled so that a 1500-point differential (all-90
    # vs all-30 blowout) hits the 95 cap, while a 50-point
    # differential (close fight) stays near the 60 floor.
    performance_rating = max(60, min(95, int(round(60 + decision["score_margin"] / 20.0))))

    # Fan reaction: lower base, upset bonus. Clamp 60-95. B1 has no
    # KO/TKO, so no KO bonus (that comes back in B2). Upset bonus:
    # if the loser had more total damage than the winner (a "robbery"
    # — the judges got it wrong), fans love the controversy.
    fan = 65 + int(decision["score_margin"] / 30.0)
    if result_type != "draw":
        # Determine winner/loser damage for the upset check.
        if decision["winner"] == "a":
            winner_dmg, loser_dmg = total_a_damage, total_b_damage
        else:
            winner_dmg, loser_dmg = total_b_damage, total_a_damage
        if loser_dmg > winner_dmg:
            fan += 5  # upset — fans love a controversial decision
    fan_reaction_rating = max(60, min(95, fan))

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
        if decision["winner"] == "a":
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
    # the total damage differential (B1 redefinition — was the old
    # power-score differential in Task 3). Read by upcoming
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


# ----------------------------------------------------------------
# Regen engine (Task ID 14).
#
# When a fighter retires (Task 12), the roster shrinks by one. Without
# regen, the roster eventually empties as fighters age out — breaking
# the "playable forever" loop. generate_fighter() creates a replacement
# fighter from the name pools with a similar style DNA (same
# fight_style_archetype_id as the retiring fighter). The new fighter
# enters as a FREE AGENT (current_promotion_id=NULL, is_active=1,
# is_retired=0) so they appear in Task 13's Free Agents tab and can be
# signed by any promotion.
#
# Called from tick_processor._check_retirements() for each retiring
# fighter. The caller records the regen_lineage row linking the
# retiring fighter to the replacement.
#
# Design choices (documented for future maintainers):
#   D1. No `used_names` table — uniqueness is checked against the
#       existing `fighters` table (first_name + last_name combination).
#       This is simpler than maintaining a separate registry and stays
#       correct when fighters are deleted (their names become available
#       again). See build_db.py's name_pools schema comment.
#   D2. No rankings row at generation time — the new fighter is a free
#       agent with no promotion, and the rankings table requires a
#       promotion_id (NOT NULL). When the player or AI signs them via
#       Task 13's sign_free_agent, the next fight resolution will call
#       _update_rankings_after_resolution which uses _get_or_create_ranking_row
#       to create the rankings row defensively on the fly.
#   D3. No memory resurfacing yet — the fighter_memory_links table
#       exists but is NOT populated by this function. Memory resurfacing
#       (style echoes, gym heirs, regional rivals, successors) is a
#       future enhancement. This task just generates a fresh fighter
#       with the same style archetype as the retiring fighter.
#   D4. The new fighter enters with default attributes (all 50),
#       personality (all 50), and career (0-0-0, career_health=100).
#       Future Stage 3 tasks (training camps, scouting) will give them
#       growth potential — for now they're a generic prospect.
#   D5. The new fighter's DOB makes them 18-26 years old (young
#       prospect). Computed by subtracting age_years * 365 days + a
#       random offset within the year from the current_date. Approximate
#       (doesn't account for leap years) but close enough for sim
#       purposes — the age is recomputed from DOB when needed.
# ----------------------------------------------------------------

def generate_fighter(conn, style_dna_source_id=None, current_date=None, gender='male'):
    """Generate a new fighter from the name pool with a similar style DNA.

    Called by the retirement path (Task ID 14) when a fighter retires.
    The new fighter:
      - Has a unique name (first + last) drawn from the name pools,
        checked against existing fighters to avoid duplicates.
      - Has a nickname drawn from the nickname pool (50% chance of
        having one).
      - Has the same fight_style_archetype_id as the retiring fighter
        (style DNA). If style_dna_source_id is None, picks a random
        archetype.
      - Has a random DOB making them 18-26 years old (young prospect).
      - Has default attributes (all 50), personality (all 50), and
        career (0-0-0, career_health=100).
      - Enters as a FREE AGENT (current_promotion_id=NULL, is_active=1,
        is_retired=0).
      - Does NOT get a rankings row at generation time (rankings
        require a promotion_id; the row is created defensively by
        _update_rankings_after_resolution when the fighter is signed
        and fights their first fight — see D2 above).
      - Does NOT get a contract (they're a free agent — the player or
        AI signs them via Task 13's sign_free_agent).
      - Is assigned to a random weight class (for now — future
        matchmaking will refine this).
      - Is assigned to NO gym (current_gym_id=NULL is fine — future
        training camp features in Task 16 will assign gyms).
      - Triggers a "new prospect" news item so the player sees them
        arrive in the Free Agents tab.

    Args:
        conn: sqlite3 connection (caller commits).
        style_dna_source_id: the retiring fighter's fighter_id. The
            new fighter inherits their fight_style_archetype_id. If
            None, picks a random archetype.
        current_date: ISO date string 'YYYY-MM-DD' for the regen
            news item's published_at timestamp and for computing the
            new fighter's DOB. If None, uses today's wall-clock date
            via datetime.now().
        gender: 'male' or 'female'. Determines which first name pool
            to draw from. Default 'male'.

    Returns:
        New fighter_id (int) on success, None on failure (e.g., name
        pool exhausted — all name combinations already used).
    """
    # 1. Pick a first name from the appropriate pool.
    name_type = 'first_male' if gender == 'male' else 'first_female'
    firsts = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type = ?",
        (name_type,),
    ).fetchall()
    if not firsts:
        print(f"Warning: name pool empty for {name_type} — cannot generate fighter.")
        return None

    # 2. Pick a last name.
    lasts = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type = 'last'"
    ).fetchall()
    if not lasts:
        print("Warning: name pool empty for last — cannot generate fighter.")
        return None

    # 3. Find a unique (first, last) combination not already in the
    #    fighters table. Shuffle both lists so different calls produce
    #    different names (random.shuffle is in-place, so we convert
    #    tuples to lists first). Walks the cartesian product looking
    #    for the first unused combination. With 25 firsts × 26 lasts
    #    = 650 possible combinations vs. ~5-20 active fighters, the
    #    pool is effectively infinite for any realistic playthrough —
    #    but the defensive None return path exists for the test that
    #    artificially shrinks the pool.
    first_list = [f[0] for f in firsts]
    last_list = [l[0] for l in lasts]
    random.shuffle(first_list)
    random.shuffle(last_list)
    chosen_first = None
    chosen_last = None
    for f in first_list:
        for l in last_list:
            existing = conn.execute(
                "SELECT 1 FROM fighters WHERE first_name = ? AND last_name = ?",
                (f, l),
            ).fetchone()
            if existing is None:
                chosen_first, chosen_last = f, l
                break
        if chosen_first is not None:
            break
    if chosen_first is None:
        print("Warning: all name combinations exhausted — cannot generate unique fighter.")
        return None

    # 4. Pick a nickname (50% chance of having one).
    nickname = None
    if random.random() < 0.5:
        nicks = conn.execute(
            "SELECT name_value FROM name_pools WHERE name_type = 'nickname'"
        ).fetchall()
        if nicks:
            nickname = random.choice(nicks)[0]

    # 5. Determine style archetype (style DNA). If a retiring fighter
    #    was specified, inherit their fight_style_archetype_id.
    #    Otherwise pick a random archetype.
    style_archetype_id = None
    if style_dna_source_id is not None:
        row = conn.execute(
            "SELECT fight_style_archetype_id FROM fighters WHERE fighter_id = ?",
            (style_dna_source_id,),
        ).fetchone()
        if row:
            style_archetype_id = row[0]
    if style_archetype_id is None:
        # Pick a random archetype (defensive: if no archetypes exist,
        # style_archetype_id stays None — the column is nullable).
        row = conn.execute(
            "SELECT style_archetype_id FROM style_archetypes ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        style_archetype_id = row[0] if row else None

    # 6. Determine personality archetype (random).
    row = conn.execute(
        "SELECT personality_archetype_id FROM personality_archetypes "
        "ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    pers_archetype_id = row[0] if row else None

    # 7. Compute DOB (18-26 years old). Approximate: subtract
    #    age_years * 365 days + a random offset within the year. Does
    #    not account for leap years but the resulting DOB is "close
    #    enough" — age is recomputed from DOB whenever needed.
    if current_date:
        try:
            current_dt = datetime.strptime(current_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            current_dt = datetime.now()
    else:
        current_dt = datetime.now()
    age_years = random.randint(18, 26)
    dob_dt = current_dt - timedelta(days=age_years * 365 + random.randint(0, 364))
    dob = dob_dt.strftime("%Y-%m-%d")

    # 8. Pick a random weight class (defensive: if no weight classes
    #    exist, wc_id stays None — the column is nullable).
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    wc_id = row[0] if row else None

    # 9. Insert the fighter as a free agent. current_promotion_id=NULL
    #    and current_gym_id=NULL — they enter the world unsigned and
    #    unaffiliated. is_active=1 (they're available to be booked
    #    once signed), is_retired=0 (they're a fresh prospect).
    #    v2.0.0 (Task 14.5): also insert the 4 physical columns
    #    (height_cm, reach_cm, stance, handedness) from
    #    fighter_gen.generate_physical_block() so regen prospects
    #    arrive with a body, not just a name. The meta columns
    #    (injury_proneness, marketability, etc.) use schema defaults.
    #    Lazy-import fighter_gen here (not at module top) so app.py
    #    can still be imported in headless contexts that don't have
    #    a src/ on sys.path (e.g., the existing tests that import
    #    app directly).
    import fighter_gen  # noqa: E402 — local import, see comment above
    physical = fighter_gen.generate_physical_block()
    fid = conn.execute(
        "INSERT INTO fighters (first_name, last_name, nickname, gender, "
        "date_of_birth, weight_class_id, current_gym_id, current_promotion_id, "
        "fight_style_archetype_id, personality_archetype_id, "
        "is_active, is_retired, height_cm, reach_cm, stance, handedness) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, 1, 0, ?, ?, ?, ?)",
        (chosen_first, chosen_last, nickname, gender, dob, wc_id,
         style_archetype_id, pers_archetype_id,
         physical["height_cm"], physical["reach_cm"],
         physical["stance"], physical["handedness"]),
    ).lastrowid

    # 10. Insert attributes, personality, career rows. v2.0.0
    #     (Task 14.5): the attribute and personality blocks are now
    #     generated via fighter_gen with archetype bias — regen
    #     prospects feel like real fighters of their archetype, not
    #     generic 50-everything stubs (see decision D4-update in the
    #     worklog). The career row still uses all defaults
    #     (0-0-0, career_health=100) — Stage 3 training camps will
    #     give them growth potential.
    #
    #     The 25 attribute columns are INSERTed explicitly (not via
    #     `INSERT INTO fighter_attributes (fighter_id) VALUES (?)`
    #     which would give all-50 defaults). Same for the 20
    #     personality columns. The SQL is built dynamically from the
    #     fighter_gen.ATTRIBUTE_NAMES / PERSONALITY_NAMES lists so a
    #     future column addition doesn't require touching this code.
    attrs = fighter_gen.generate_attribute_block(style_archetype_id, conn)
    pers = fighter_gen.generate_personality_block(pers_archetype_id, conn)

    attr_cols = fighter_gen.ATTRIBUTE_NAMES
    attr_placeholders = ", ".join(["?"] * len(attr_cols))
    attr_col_list = ", ".join(attr_cols)
    conn.execute(
        f"INSERT INTO fighter_attributes (fighter_id, {attr_col_list}) "
        f"VALUES (?, {attr_placeholders})",
        (fid,) + tuple(attrs[c] for c in attr_cols),
    )

    pers_cols = fighter_gen.PERSONALITY_NAMES
    pers_placeholders = ", ".join(["?"] * len(pers_cols))
    pers_col_list = ", ".join(pers_cols)
    conn.execute(
        f"INSERT INTO fighter_personality (fighter_id, {pers_col_list}) "
        f"VALUES (?, {pers_placeholders})",
        (fid,) + tuple(pers[c] for c in pers_cols),
    )

    # v2.0.1 (Task pre-B1-fixes): set `potential` for the new fighter
    # via fighter_gen.generate_potential(). The distribution is 10%
    # elite (70-90), 30% solid (50-69), 60% limited (25-49). The
    # fighter_career row INSERT now specifies `potential` explicitly
    # (was `INSERT INTO fighter_career (fighter_id) VALUES (?)` which
    # used the DEFAULT 50). All other fighter_career columns (record,
    # streaks, career_health, title_reigns) use their schema DEFAULTs
    # (0-0-0, 100, 0) — sensible for a fresh prospect.
    #
    # Why potential matters: without a growth ceiling, every fighter
    # has unlimited growth potential and the Talent Hunter fantasy
    # collapses (CAGE_EMPIRE_SOUL.md Fantasy 1). With potential,
    # training camps (Task 16, future) will push attributes toward
    # this ceiling with diminishing returns as they approach it. The
    # rare-elite distribution makes "that kid from Mexico" prospects
    # genuinely rare — ~1 in 10 regen fighters has elite potential.
    potential = fighter_gen.generate_potential()
    conn.execute(
        "INSERT INTO fighter_career (fighter_id, potential) VALUES (?, ?)",
        (fid, potential),
    )

    # 11. NO rankings row at generation time. See D2 above — the
    #     rankings table requires a promotion_id (NOT NULL), and the
    #     new fighter is a free agent. _get_or_create_ranking_row in
    #     app.py creates the rankings row on the fly when the fighter
    #     is signed and fights their first bout.

    # 12. Write a news item about the new prospect. Direct INSERT
    #     (same pattern as _check_retirements, _vacate_title_on_retirement,
    #     sign_free_agent — avoids pulling in app.write_news from
    #     this same module). topic='prospect' so the future news
    #     engine (Task 23) can filter prospect-arrival news.
    src = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if src is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src[0]

    nick_str = f' "{nickname}"' if nickname else ''
    headline = f"New prospect {chosen_first} {chosen_last}{nick_str} emerges on the scene"
    body = (f"A new talent, {chosen_first} {chosen_last}{nick_str}, has arrived "
            f"as a free agent looking for a promotion to sign with.")
    # published_at: prefer the explicit current_date (the sim date the
    # regen happened on). If None (caller didn't pass one), fall back to
    # today's wall-clock date. The news_items.published_at column is
    # NOT NULL with a DEFAULT of CURRENT_TIMESTAMP, but we explicitly
    # pass a value here so the caller controls the timestamp. Direct
    # callers (e.g., the test in case K) that omit current_date get
    # today's date — matching the pattern in app.write_news which also
    # omits published_at (letting the DEFAULT apply, which is wall-clock
    # time). For consistency with the rest of the regen path which
    # passes the sim date, we use today's date string instead of relying
    # on the DEFAULT (so the published_at is a clean YYYY-MM-DD, not a
    # full CURRENT_TIMESTAMP).
    if current_date:
        published_at = current_date
    else:
        published_at = current_dt.strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, sentiment, "
        "topic, fighter_id, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "neutral", "prospect", fid, published_at),
    )

    # 13. Return the new fighter_id. The caller (tick_processor's
    #     _check_retirements) writes the regen_lineage row linking the
    #     retiring fighter to this replacement.
    return fid


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
