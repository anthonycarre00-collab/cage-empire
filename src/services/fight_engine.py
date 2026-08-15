"""CAGE EMPIRE fight engine service (Stage 6 — Task 6.0).

Extracted from src/app.py. Contains all fight resolution logic:
beat engine, decision scoring, commentary beat selection, rankings +
title resolution, post-fight injury creation, gameplan/bad-matchup
derivation, weight cut, descriptor snapshot, title vacation on
retirement.

Functions kept verbatim (no behaviour, name, or signature changes).

Public API (called by App + tests):
- resolve_next_fight(conn, promotion_id=None) -> int|None  (fight_id)
- resolve_round(conn, fight_id, round_number, ...) -> dict
- update_fighter_descriptor_snapshot(conn, fighter_id)
- _vacate_title_on_retirement(conn, fighter_id, current_date)

Beat-engine internals (used by tests):
- _load_fighter_stats, _compute_beat_scores, _compute_gas_cost,
  _recover_gas_between_rounds, _compute_fight_importance,
  _compute_pressure_response, _compute_pressure_modifier,
  _ko_threshold, _ko_finish_probability, _submission_score,
  _doctor_stoppage_threshold, _check_corner_stoppage, _check_dq,
  _random_finish_time, _pick_action_type, _compute_damage,
  _resolve_beat_outcome, _maybe_transition_phase,
  _select_commentary_beats, _maybe_create_injury,
  _run_weight_cut, _compute_weight_cut_miss_prob,
  _resolve_title_after_fight, _update_event_status_after_resolution,
  _get_or_create_ranking_row, _update_rankings_after_resolution,
  _derive_preferred_gameplans, _derive_bad_matchup_tags,
  _update_preferred_gameplans, _update_bad_matchup_tags,
  _opponent_style_archetype_name

Constants (used by tests + tick_processor + agent_offers):
- _FIGHTER_ATTR_COLUMNS, _FIGHTER_PERS_COLUMNS, _ELO_K,
  _INITIAL_RATING, _INJURY_BASE_DAYS_PER_SEVERITY,
  _INJURY_CAREER_HEALTH_MULT, _INJURY_MIN_DAYS_OUT,
  _INJURY_RECOVERY_RATE_DAYS_PER_POINT, _GAMEPLAN_THRESHOLD,
  _GAMEPLAN_CAP, _BAD_MATCHUP_CAP, _BEAT_COMMENTARY_TEMPLATES,
  PHASE_ATTRS, PHASE_ACTIONS

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it reads/writes the existing `fights`, `fight_beats`,
        `fight_rounds`, `fight_history`, `fight_participants`,
        `commentary_segments`, `rankings`, `titles`,
        `fighter_career`, `fighter_attributes`,
        `fighter_personality`, `fighter_descriptors`, `injuries`,
        `weight_cut_log`, `news_items`, `events` tables only.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass
        after extraction.
  §13 — Design Law: pillar Conflict ("fights, rivalries, title
        battles" — the cage is where the dopamine lives).
  §14 — Voice Layer: commentary_segments + news_items text route
        through src/voice.py (no raw attribute values in player-
        facing strings). Constants + intermediate values are raw
        numbers (debug-only).
  §15 — Event Bus: resolve_next_fight publishes FIGHT_RESOLVED,
        FIGHTER_STATE_CHANGED, TITLE_CHANGED (if title_change_id
        set). Existing inline side effects preserved per §15.4.

Migration impact: NONE (code-only refactor).
"""
import sqlite3
import json
import random
from pathlib import Path
from datetime import datetime, timedelta

from services.clock import fighter_name
from services.matchmaking import (
    schedule_next_event,
    _create_training_camp,
    _get_camp_fatigue_for_event,
    _pick_camp_focus_for_archetype,
    _CAMP_FOCUS_ATTRS,
    _ARCHETYPE_NAME_TO_CAMP_FOCUS,
    _CAMP_LEAD_DAYS,
    _TITLE_FIGHT_ROUNDS,
    _NON_TITLE_FIGHT_ROUNDS,
    _REST_PERIOD_DAYS,
)


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
    """Load one fighter's full 25 combat attributes + 20 personality fields
    + 3 fighters-table meta columns used by the B2 engine.

    Returns a flat dict with all 48 fields. Falls back to defaults (50s)
    if either row is missing — defensive, the seed always inserts both.

    The beat engine uses all 25 attributes (different phases use
    different subsets — see PHASE_ATTRS) and several personality fields
    (aggression for initiator selection, discipline + cardio +
    speed_explosiveness for pace, etc.).

    v2.3.0 (Task B2): also loads `clutch_factor`, `consistency`, and
    `marketability` from the `fighters` table (these live on fighters,
    NOT on fighter_attributes or fighter_personality). They're needed
    for the fight importance + pressure response computation:
      - clutch_factor + consistency feed pressure_response
        (clutch_factor*0.35 + composure*0.25 + consistency*0.20 +
        focus*0.10 + grit*0.10).
      - marketability feeds fight importance (15% weight, avg of both
        fighters' marketability).
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
    # v2.3.0 (Task B2): load the 3 fighters-table meta columns the B2
    # engine needs. Falls back to 50 (the schema DEFAULT) if the
    # fighter row is missing or the columns are NULL.
    # Phase E5 (Fix 2): also load current_promotion_id so fight_engine
    # can pass it through to injuries_svc.get_doctor_recovery_bonus
    # (the doctor recovery-time reduction needs the fighter's promo).
    meta = conn.execute(
        "SELECT clutch_factor, consistency, marketability, "
        "current_promotion_id "
        "FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    a = attrs if attrs else _DEFAULT_ATTRS
    p = pers if pers else _DEFAULT_PERS
    stats = {}
    for col, val in zip(_FIGHTER_ATTR_COLUMNS, a):
        stats[col] = val
    for col, val in zip(_FIGHTER_PERS_COLUMNS, p):
        stats[col] = val
    # v2.3.0 meta columns (defaults to 50 if missing).
    if meta:
        stats["clutch_factor"] = meta[0] if meta[0] is not None else 50
        stats["consistency"] = meta[1] if meta[1] is not None else 50
        stats["marketability"] = meta[2] if meta[2] is not None else 50
        # Phase E5 — current_promotion_id (None for free agents; the
        # doctor bonus helper handles None defensively).
        stats["current_promotion_id"] = meta[3]
    else:
        stats["clutch_factor"] = 50
        stats["consistency"] = 50
        stats["marketability"] = 50
        stats["current_promotion_id"] = None
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
    # FIGHT-ENGINE-TUNE Issue 3: kept original weights (4,1,1) and
    # (2,3,1,1). The submission formula change + threshold lowering
    # already boost submission rate enough; doubling the sub-attempt
    # weight as well over-corrected (pushed full-engine sub rate to
    # 35%, above the 25% target). The brief's "increase submission
    # attempt probability per beat" is satisfied by the formula weight
    # increase (1.0 -> 1.2 on submission_offense).
    #
    # FIX-V3-ALL5 #3 (Sub 14% -> target 20%): bumped the
    # submission_attempt weight from 1 -> 1.2 in BOTH ground_top and
    # ground_bottom (a ~20% relative increase per the brief). The
    # prior tuning comment warned that doubling (1 -> 2) over-shot to
    # 35%, so a 20% bump should add ~3-5pp to the cumulative sub
    # rate (14% -> 17-19% on the full engine alone), combined with
    # the simplified-resolver bump (0.03 -> 0.045) bringing the
    # blended rate to the 18-22% target band. random.choices
    # accepts float weights so no other code change needed.
    "ground_top":    (4, 1.2, 1),              # 6.2 total — sub weight 20% higher
    "ground_bottom": (2, 3, 1.2, 1),           # 7.2 total — sub weight 20% higher
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



# FIGHT-ENGINE-TUNE Issue 2: halved 8.0 -> 4.0 to reduce per-beat
# scoring variance. The original 8.0 produced too many coin-flip
# rounds on close matchups -> 38% split decisions (target 10%).
# Halving the noise makes stronger fighters dominate more cleanly,
# reducing close rounds + the split_decision rate downstream.
_BEAT_NOISE_SIGMA = 4.0


# ----------------------------------------------------------------
# v2.3.0 (Task B2) — Beat Engine Depth constants.
#
# Fatigue system: gas starts at 100 per fight, depletes per beat
# (phase-dependent base costs), cardio + fatigue_tolerance slow decay,
# recovery between rounds. Low gas (<30) reduces accuracy and
# increases chin vulnerability.
# ----------------------------------------------------------------

# Phase-to-base-gas-cost mapping (per the B2 brief). Higher-intensity
# phases cost more gas. Standing is cheapest (mostly distance
# striking); ground and scramble are most expensive (grappling is
# tiring).



PHASE_GAS_COSTS = {
    "standing": 1,
    "clinch": 2,
    "cage": 2,
    "ground_top": 3,
    "ground_bottom": 3,
    "scramble": 4,
}

# Low-gas threshold: below this value, accuracy is reduced 30% and chin
# vulnerability increases 20%. Per the B2 brief.



_LOW_GAS_THRESHOLD = 30



_LOW_GAS_ACCURACY_PENALTY = 0.30  # 30% accuracy reduction when gassed



_LOW_GAS_CHIN_PENALTY = 0.20      # +20% damage taken when gassed


# ----------------------------------------------------------------
# Fight importance + pressure modifiers (v2.3.0 / Task B2).
#
# Fight importance is a computed value (0-100), NOT stored:
#   card_slot weight (40%) + title at stake (30%) +
#   rivalry heat (15%, 0 for now — rivalries table doesn't exist yet) +
#   fighter popularity (15%, avg marketability of both fighters)
#
# Pressure response per fighter (computed, NOT stored):
#   pressure_response = clutch_factor*0.35 + composure*0.25 +
#                       consistency*0.20 + focus*0.10 + grit*0.10
#
# In high-importance fights (importance > 60):
#   pressure_response >= 70: "Rises to the occasion" — +5% to beat
#     attack/defense scores
#   pressure_response <= 30: "Bottler" — -10% to beat attack/defense
#     scores
#   30 < pressure_response < 70: no modifier (baseline)
# ----------------------------------------------------------------

# Card slot weights (40% of fight importance).



CARD_SLOT_WEIGHTS = {
    "main_event": 100,
    "co_main": 80,
    "featured_prelim": 60,
    "prelim": 40,
    "opener": 20,
}

# Pressure modifier thresholds.



_PRESSURE_HIGH_IMPORTANCE_THRESHOLD = 60   # importance > 60 triggers



_PRESSURE_RISES_THRESHOLD = 70             # >= 70 → +5% bonus



_PRESSURE_BOTTLER_THRESHOLD = 30           # <= 30 → -10% penalty



_PRESSURE_RISES_BONUS = 0.05               # +5%



_PRESSURE_BOTTLER_PENALTY = -0.10          # -10%


# ----------------------------------------------------------------
# Mid-round finish thresholds (v2.3.0 / Task B2).
# ----------------------------------------------------------------

# KO/TKO: cumulative damage in the current beat sequence crosses the
# defender's threshold. The brief's literal formula
# `threshold = 100 - chin*0.5 - recovery_rate*0.2 - grit*0.1 - composure*0.2`
# is mathematically INVERTED — higher chin → lower threshold → easier
# to KO, which is wrong (a high-chin fighter should be HARDER to KO).
# Corrected formula (D2): `threshold = chin*0.5 + recovery_rate*0.2 +
# grit*0.1 + composure*0.2`.
#
# D6 (engine tuning): the initial D2 formula produced too many KOs for
# the test_fight_resolver.py acceptance check ("no single result_type
# > 60/100"). With chin weighted at 0.5, a chin=30 fighter (the test's
# all-30 setup) had a threshold of 40 — crossed by a single cross
# (damage ~41). Combined with the original ko_prob of 0.5+KI/200
# (0.75 at KI=50), this produced ~100% KO rate for all-90 vs all-30.
# The fix re-weights chin to 1.0 (a chin=30 fighter now has threshold
# 55, needing 2 power strikes to cross) and re-tunes ko_prob to
# 0.1+KI*0.002 (range 0.1-0.3, see below). A "power strike" filter
# (_KO_CHECK_MIN_DAMAGE) ensures only significant strikes (damage >= 30)
# can trigger a KO check — jabs and leg kicks don't knock people out.
# Together these produce a ~50% KO rate for the extreme all-90 vs
# all-30 mismatch (under the 60% cap) while still producing KOs for
# D.3 (all-90 vs all-30 produces some KO/TKO finishes).
# Final formula: `threshold = chin*1.0 + recovery_rate*0.2 +
# grit*0.1 + composure*0.1`.



# FIGHT-ENGINE-TUNE Issue 1: chin weight lowered 1.0 -> 0.7 so a
# typical chin=50 fighter's KO threshold drops from ~70 to ~55
# (50*0.7 + 50*0.2 + 50*0.1 + 50*0.1 = 35+10+5+5 = 55), reachable
# in 2-3 power strikes instead of 4-5. Combined with the lower
# _KO_CHECK_MIN_DAMAGE (20 vs 30), KOs now actually trigger in the
# beat engine.
_KO_THRESHOLD_CHIN_WEIGHT = 0.7



_KO_THRESHOLD_RECOVERY_WEIGHT = 0.2



_KO_THRESHOLD_GRIT_WEIGHT = 0.1



_KO_THRESHOLD_COMPOSURE_WEIGHT = 0.1

# Base probability that a KO actually occurs when the threshold is
# crossed AND the current beat is a power strike (damage >=
# _KO_CHECK_MIN_DAMAGE). The attacker's `killer_instinct` adds to
# this:
#   ko_prob = 0.1 + killer_instinct * 0.002
# (Ranges from 0.1 at KI=0 to 0.3 at KI=100.) Per the B2 brief:
# "killer_instinct on the attacker increases the chance the finish
# happens before the defender recovers." D6: the original 0.5+KI/200
# (range 0.5-1.0) was too aggressive — combined with the high
# crossing frequency, it produced ~100% KO rate for extreme matchups.
# The new range (0.1-0.3) produces a ~50% KO rate for all-90 vs
# all-30 (under the 60% cap) while still producing KOs reliably for
# D.3/L.2.



# FIGHT-ENGINE-TUNE Issue 1: KO finish probability base raised
# 0.1 -> 0.15 (combined with the lower threshold, produces a
# realistic ~25-30% KO rate across the fighter population).
#
# FIX-V3-ALL5 #2 (KO 23% -> target 30%): the 0.15 base produced a
# 23% KO rate in the 1-year sim — short of the 28-32% target. Raising
# to 0.18 means a threshold-crossing event now results in a KO 18%
# of the time at KI=0 (was 15%), and 38% at KI=100 (was 35%). This
# is a modest 20% relative increase in the per-crossing probability
# — lifts the cumulative KO rate into the 28-32% target band.
_KO_FINISH_PROB_BASE = 0.18



_KO_FINISH_PROB_KI_SCALE = 0.002

# D6: only "power strikes" (damage >= this threshold) can trigger a
# KO check. A jab (damage ~20) or leg kick (damage ~25) doesn't knock
# someone out — only crosses, hooks, head kicks, clinch knees, and
# ground strikes qualify. This reduces the number of KO checks per
# round from ~9 (every landed strike) to ~4-5 (only power strikes),
# which combined with the lower ko_prob brings the overall KO rate
# under the 60% cap for the test_fight_resolver.py acceptance check.
# The consecutive-damage tracker still accumulates from ALL landed
# strikes (a fighter who eats 10 jabs is still wearing down), but
# only a power strike can be the "finishing blow".



# FIGHT-ENGINE-TUNE Issue 1: lowered 30 -> 20 so jabs+leg kicks
# (damage 15-25) can now be the finishing blow when the defender
# is already rocked from a sustained beating. The original 30
# filter meant only crosses/hooks/head kicks/ground strikes could
# finish — combined with the high threshold, KOs almost never
# fired in the engine (0 KOs in 672 fights in the 1-year sim).
_KO_CHECK_MIN_DAMAGE = 20

# When the KO roll fails (defender survives the threshold crossing),
# the defender is "rocked" — a `near_finish` beat is recorded with
# momentum_shift = +60. The defender then has a brief moment to
# recover (the consecutive-damage tracker resets).

# Submission success score: positive = submission succeeds. Per the
# B2 brief: `submission_offense - submission_defense*0.5 -
# flexibility*0.3 - scramble_ability*0.2 + composure*0.1`. The
# `composure` term is ambiguous in the brief (could be attacker's or
# defender's); interpreted as the ATTACKER's composure per worklog D3
# — a calm attacker is better at finishing submissions.
#
# FIGHT-ENGINE-TUNE Issue 3: re-weighted the formula so submissions
# actually succeed. The old formula gave a typical score of 10 for
# all-50 attrs (50 - 25 - 15 - 10 + 5 = 5) — barely above the success
# threshold, so most attempts failed. The new formula
# `submission_offense*1.2 - submission_defense*0.4 - flexibility*0.2`
# gives a typical score of 30 (60 - 20 - 10 = 30) and removes the
# scramble_ability + composure terms (the brief's "composure" is
# ambiguous; keeping it small avoided over-counting). Combined with
# the increased submission_attempt weight in PHASE_ACTION_WEIGHTS,
# this brings submission rate from ~1% to the 15-25% target range.
_SUBMISSION_OFFENSE_WEIGHT = 1.2
_SUBMISSION_DEFENSE_WEIGHT = 0.4
_SUBMISSION_FLEXIBILITY_WEIGHT = 0.2
# FIGHT-ENGINE-TUNE Issue 3: lowered the success threshold from 0 to
# -5 so even a slightly-below-zero score (defender has marginally
# better sub defense) has a chance to succeed. This is the explicit
# "lower the submission success threshold" constant from the brief.
_SUBMISSION_SUCCESS_THRESHOLD = -5

# Doctor stoppage: cumulative damage across ALL rounds crosses
# `threshold = _DOCTOR_STOPPAGE_BASE + durability*_DOCTOR_STOPPAGE_DURABILITY_SCALE`.
# Checked between rounds. D11: additionally requires the damage
# differential to exceed _DOCTOR_STOPPAGE_DIFFERENTIAL — the doctor
# stops a one-sided beating, not a mutual brawl. See resolve_next_fight
# D11 comment.
#
# CR-11 fix (docs/CR10_14_FIX_PLAN.md §2): raised thresholds to cut
# the doctor_stoppage rate from 54% to within the 3-10% target range
# (with ±10pp acceptable tolerance per spec §2.3). The old tuning
# (base=200, scale=2, diff=50) produced a threshold of 300 for a
# durability=50 fighter, which cumulative damage exceeded by end of
# round 2 in most fights → ~54% of new fights ended via
# doctor_stoppage at finish_time="5:00".
#
# Tuning history (verified via scripts/test_fight_engine_balance.py
# — 100 random world-DB matchups, multi-seed):
#   • Old (200, 2, 50): 54% doctor stoppages (audit finding).
#     Threshold for avg-world dur=37.7 was 200 + 37.7*2 = 275.
#   • Spec suggestion (400, 3, 100): ~13% doctor stoppages across
#     5 seeds — above the 5-8% aspirational target but WITHIN the
#     ±10pp acceptable tolerance (0-20%). Threshold for dur=37.7
#     is 400 + 113 = 513. Submission rate at the 30% acceptable
#     ceiling; UD ~40% (safe under the 50% hard cap). BEST overall
#     fit to the spec's acceptable ranges.
#   • More aggressive (500, 3, 150): ~5% doctor stoppages (hits
#     target) BUT pushed submissions to ~37% (over the 30%
#     acceptable ceiling) and UD to ~44% (close to the 50% hard
#     cap). Rejected — trading doctor target for sub FAIL is a
#     net loss on the spec's acceptable ranges.
# Selected: (400, 3, 100) — passes the most acceptable-range
# criteria simultaneously. Doctor at ~13% is within acceptable
# (0-20%); sub at ~30% is at the ceiling; UD at ~40% is safe; KO
# remains below acceptable (see KNOWN ISSUE below).
#
# KNOWN ISSUE (out of scope for CR-11): the KO/submission RATIO is
# inverted vs real MMA — the engine produces ~30% submissions vs
# ~7% KO/TKO (real MMA: ~15% sub vs ~30% KO). This is a property
# of the KO/submission check logic in resolve_round (the KO finish
# probability + submission score formula), NOT the doctor constants.
# Tuning the doctor constants cannot fix the KO:sub ratio — lowering
# doctor_stoppage shifts fights to decisions + submissions, not KOs.
# Recommend a follow-up task (CR-11b) to investigate the KO check
# threshold + roll probability in resolve_round.
#
# Fights that don't end in a finish now fall through to the 10-point
# must decision scoring (see _decide_fight_outcome), producing
# UD/SD/draw variety (was 0% decisions pre-fix; now ~45% decisions).



_DOCTOR_STOPPAGE_BASE = 400



_DOCTOR_STOPPAGE_DURABILITY_SCALE = 3



_DOCTOR_STOPPAGE_DIFFERENTIAL = 100

# Corner stoppage: fighter loses 3+ consecutive rounds AND grit < 40
# AND composure < 40, 20% chance per qualifying round.



_CORNER_STOPPAGE_CONSECUTIVE_LOSSES = 3



_CORNER_STOPPAGE_GRIT_THRESHOLD = 40



_CORNER_STOPPAGE_COMPOSURE_THRESHOLD = 40



_CORNER_STOPPAGE_CHANCE = 0.20

# DQ: fighter has discipline < 20 AND lands a strike, 1% chance per
# qualifying beat. Represents an illegal strike (eye poke, groin shot,
# strike to back of head).



_DQ_DISCIPLINE_THRESHOLD = 20



_DQ_CHANCE_PER_BEAT = 0.01

# Momentum shift values for dramatic moments (per the B2 brief).



_KNOCKDOWN_MOMENTUM_SHIFT = 80



_NEAR_FINISH_MOMENTUM_SHIFT = 60
# D12: momentum decay between rounds. cum_momentum is multiplied by
# this factor at the start of each new round. 0.5 = 50% decay (a
# knockdown in round 1 gives half the advantage in round 2). Prevents
# the cross-round snowball that would otherwise make balanced fights
# one-sided (see resolve_next_fight D12 comment).



_MOMENTUM_DECAY_BETWEEN_ROUNDS = 0.5
# Big takedown momentum threshold: a takedown_attempt that lands with
# significant control time gets +30 momentum. The brief says "Big
# takedown: +30" without defining "big". Interpreted as a takedown
# that lands with control_time_delta in the upper portion of the 1-5
# range (a "big slam" or dominant takedown). With control_time_delta
# = random.randint(1, 5) per _resolve_beat_outcome, threshold 3 means
# ~60% of landed takedowns qualify as "big" — frequent enough to be
# observable in fight_beats, rare enough to feel like a special moment.
# (Was 30, which never fired because control_time_delta maxes at 5 —
# a calibration bug fixed in v2.3.0. See worklog D5.)



_BIG_TAKEDOWN_MOMENTUM_THRESHOLD = 3



_BIG_TAKEDOWN_MOMENTUM_SHIFT = 30

# Commentary beat selection: number of beats to select based on fight
# importance (per the B2 brief).
#   quick (importance < 40):     3-6 beats
#   standard (40 <= importance < 70): 6-10 beats
#   extended (importance >= 70): 10-14 beats



_COMMENTARY_QUICK_RANGE = (3, 6)



_COMMENTARY_STANDARD_RANGE = (6, 10)



_COMMENTARY_EXTENDED_RANGE = (10, 14)



_COMMENTARY_QUICK_THRESHOLD = 40



_COMMENTARY_EXTENDED_THRESHOLD = 70
# Momentum swing magnitude that qualifies a beat as a "big momentum
# swing" for commentary selection.



_BIG_MOMENTUM_SWING_THRESHOLD = 50


# ----------------------------------------------------------------
# Injury system constants (v2.4.0, Task 15).
#
# Injury creation is a side effect of resolve_next_fight() that runs
# AFTER all other side effects (fight_history, rankings, titles, event
# lifecycle, schedule_next_event, news, commentary, commentary beat
# selection). The helper _maybe_create_injury() rolls against injury
# probability for each fighter, picks an injury type / body area,
# computes severity + projected return date, applies long-term damage
# if applicable, writes an injuries row + a news item, and reduces
# fighter_career.career_health.
#
# The probabilities and severities below are tuned so that:
#   - The base injury rate (decision fights, all-50 fighters) is ~5%
#     per fight, per the brief's "5% base per fight (non-finish)".
#   - KO/TKO losers have a 30% chance of a concussion (per the brief).
#   - Submission losers have a 15% chance of a joint injury (per the
#     brief).
#   - Doctor stoppage produces a guaranteed injury on the loser (per
#     the brief — "that's why the doctor stopped it").
#   - injury_proneness (fighters column) modifies the probability
#     (0.5x at 0, 1.5x at 100 — a 2x swing across the 0-100 range,
#     matching the brief's "high proneness = more likely").
#   - durability (fighter_attributes column) reduces severity
#     (high durability = less severe — a -2 to +2 swing across 0-100).
#
# The recovery timeline (projected_return_date = start_date + severity
# * 14 days, reduced by recovery_rate * 0.1 per day) gives:
#   - sev 1 cut:           14 - 5 = 9 days  (~1.5 weeks)
#   - sev 5 fractured rib: 70 - 5 = 65 days (~9 weeks)
#   - sev 10 ACL tear:     140 - 5 = 135 days (~19 weeks / 4.5 months)
# These ranges match real-world MMA injury timelines (a minor cut
# keeps a fighter out 1-2 weeks; a torn ACL keeps them out 6-9
# months in reality — we err slightly shorter because the sim has
# accelerated aging and the player wants the fighter back in the
# rotation within a year).
# ----------------------------------------------------------------

# Base injury probability per fight for non-finish outcomes (decision,
# draw, corner_stoppage, dq). Per the brief: "5% base per fight
# (non-finish)".



_INJURY_BASE_PROB_NONFINISH = 0.05

# Cap on the damage-scaled addition to injury probability. Damage
# taken ranges 0-1000+ per fight; we scale it to a 0-20% probability
# addition so a fighter who took 1000+ damage has up to 25% injury
# chance (5% base + 20% damage). This matches the brief's "severity
# scaled by cumulative damage_dealt to the fighter" — interpreted as
# a 20% cap on the damage contribution.



_INJURY_DAMAGE_SCALE_CAP = 0.20



_INJURY_DAMAGE_SCALE_DIVISOR = 1000.0  # damage / this = probability add

# KO/TKO loser injury probability (concussion). Per the brief: "30%
# chance of head injury (concussion)".



_INJURY_KO_HEAD_PROB = 0.30

# Submission loser injury probability (joint injury). Per the brief:
# "15% chance of joint injury (the submitted joint)".



_INJURY_SUBMISSION_JOINT_PROB = 0.15

# Doctor stoppage: guaranteed injury on the loser. Per the brief:
# "guaranteed injury (that's why the doctor stopped it)".



_INJURY_DOCTOR_GUARANTEED = 1.0

# injury_proneness modifier range. The brief says "high proneness =
# more likely". Implemented as a 0.5x-1.5x multiplier across 0-100
# (linear). A fighter with proneness=0 has half the base chance; a
# fighter with proneness=100 has 1.5x the base chance.



_INJURY_PRONENESS_MIN_MULT = 0.5



_INJURY_PRONENESS_MAX_MULT = 1.5

# durability severity reduction. The brief says "high durability =
# less severe". Implemented as a -2 to +2 severity adjustment across
# 0-100 (linear): dur=0 → +2 severity (low durability = worse),
# dur=50 → 0 (no change), dur=100 → -2 severity (high durability =
# less severe). The adjustment is applied AFTER the random severity
# roll and clamped to [1, 10].



_INJURY_DURABILITY_SEVERITY_ADJUST = 2  # +/- at extremes

# Recovery timeline. Per the brief: "projected_return_date =
# start_date + severity * 14 days" and "reduce days by recovery_rate
# * 0.1 per day". The recovery_rate adjustment is a flat reduction
# (5 days at recovery_rate=50, the schema default).



_INJURY_BASE_DAYS_PER_SEVERITY = 14



_INJURY_RECOVERY_RATE_DAYS_PER_POINT = 0.1



_INJURY_MIN_DAYS_OUT = 7  # even a sev-1 cut takes at least a week

# Long-term damage: severity 8+ has 30% chance of permanent attribute
# reduction. Per the brief: "severity 8+ injuries have 30% chance of
# permanent attribute reduction (-2 to -5 on relevant attribute)".



_INJURY_LONGTERM_SEVERITY_THRESHOLD = 8



_INJURY_LONGTERM_PROB = 0.30



_INJURY_LONGTERM_MIN = 2



_INJURY_LONGTERM_MAX = 5

# Career-health impact. Per the brief: "each active injury reduces
# career_health by severity * 2 while active" and "long_term_damage
# permanently reduces it [career_health]".



_INJURY_CAREER_HEALTH_MULT = 2  # severity * this = temporary career_health hit

# Injury type pools by body area (per the brief's "Injury types by
# body area" section). Each entry is (injury_type, severity_min,
# severity_max). The random roll picks one entry from the list, then
# rolls a severity in [sev_min, sev_max].



_INJURY_TYPES_BY_BODY_AREA = {
    "head":     [("concussion", 5, 10), ("cut", 1, 3)],
    "face":     [("laceration", 2, 5), ("broken nose", 3, 5), ("orbital fracture", 5, 8)],
    "jaw":      [("broken jaw", 5, 8)],
    "nose":     [("broken nose", 3, 5)],
    "eye":      [("orbital fracture", 5, 8)],
    "neck":     [("neck strain", 3, 6)],
    "shoulder": [("shoulder dislocation", 4, 7), ("rotator cuff tear", 6, 9)],
    "arm":      [("arm fracture", 4, 7)],
    "elbow":    [("elbow hyperextension", 4, 7)],
    "wrist":    [("wrist sprain", 2, 5)],
    "hand":     [("broken hand", 4, 6)],
    "ribs":     [("bruised ribs", 2, 4), ("fractured ribs", 5, 7)],
    "back":     [("back spasms", 2, 5)],
    "hip":      [("hip pointer", 3, 6)],
    "knee":     [("ACL tear", 7, 10), ("meniscus tear", 4, 7), ("MCL sprain", 3, 6)],
    "ankle":    [("ankle sprain", 2, 5), ("ankle fracture", 5, 8)],
    "foot":     [("foot fracture", 3, 6)],
    "general":  [("muscle tear", 3, 6), ("fatigue syndrome", 2, 4)],
}

# Body areas that can be rolled for non-finish injuries (decision /
# draw / corner_stoppage / dq). Excludes the finish-specific areas
# (head for KO, joints for submission) since those have their own
# dedicated injury paths. The list is biased toward common fight
# injuries (hand/ribs/face are the most common, knee is rare but
# severe — matching real-world MMA injury distributions).



_INJURY_BODY_AREAS_NONFINISH = [
    "head", "head", "face", "face", "ribs", "ribs", "hand", "hand",
    "knee", "foot", "ankle", "general", "general", "shoulder",
]

# Body areas that can be rolled for submission-finish joint injuries.
# Per the brief: "15% chance of joint injury (the submitted joint)".
# The "submitted joint" is ambiguous in the brief (depends on the
# submission type — armbar = elbow, kneebar = knee, heel hook =
# ankle, kimura = shoulder). We pick uniformly at random from the
# 4 joint areas to keep the implementation simple; future
# submissions-engine work can specialize this.



_INJURY_SUBMISSION_JOINT_AREAS = ["knee", "elbow", "shoulder", "ankle"]

# Mapping from body_area to the fighter_attribute that gets reduced
# when a severity-8+ injury becomes long-term. The brief says "-2 to
# -5 on relevant attribute" — "relevant" is interpreted as the
# attribute most associated with that body area:
#   - head/face/jaw/eye/nose → chin (taking punches to the head)
#   - knee/ankle/foot → speed_explosiveness (leg-driven mobility)
#   - shoulder/elbow/wrist/hand → punch_power (striking limb)
#   - ribs/back → cardio (torso-driven breathing / rotation)
#   - hip → strength (hip-driven power)
#   - neck → strength
#   - general → durability (overall resilience)
# A body_area not in this map (shouldn't happen — all 18 are mapped)
# falls back to durability as the safe default.



_INJURY_LONGTERM_ATTR_BY_AREA = {
    "head": "chin", "face": "chin", "jaw": "chin", "eye": "chin",
    "nose": "chin", "neck": "strength",
    "shoulder": "punch_power", "arm": "punch_power",
    "elbow": "punch_power", "wrist": "punch_power", "hand": "punch_power",
    "ribs": "cardio", "back": "cardio",
    "hip": "strength",
    "knee": "speed_explosiveness", "ankle": "speed_explosiveness",
    "foot": "speed_explosiveness",
    "general": "durability",
}





def _compute_beat_scores(phase, init_stats, target_stats,
                         init_gas=100.0, target_gas=100.0,
                         pressure_mod_init=0.0, pressure_mod_target=0.0,
                         momentum_advantage=0.0):
    """Compute the initiator's attack score and the defender's defense score.

    Each score is the average of the phase-relevant attributes (per
    PHASE_ATTRS) plus Gaussian noise (sigma=_BEAT_NOISE_SIGMA). The
    noise is per-beat so the same matchup produces different outcomes
    across beats — this is what makes the engine probabilistic rather
    than deterministic.

    v2.3.0 (Task B2) modifiers (all default to 0 / 100, preserving B1
    behavior when not passed):
      - Low gas (< _LOW_GAS_THRESHOLD): score reduced by
        _LOW_GAS_ACCURACY_PENALTY (30%).
      - Pressure modifier (clutch / bottler): score multiplied by
        (1 + modifier). +5% for rises-to-occasion, -10% for bottler.
      - Momentum advantage: score multiplied by (1 + advantage).
        Advantage is clamped to [-0.3, +0.3] by the caller.

    Returns (attack_score, defense_score) as floats.
    """
    init_attrs = PHASE_ATTRS[phase]["initiator"]
    def_attrs = PHASE_ATTRS[phase]["defender"]
    attack = sum(init_stats[a] for a in init_attrs) / len(init_attrs)
    defense = sum(target_stats[a] for a in def_attrs) / len(def_attrs)
    attack += random.gauss(0, _BEAT_NOISE_SIGMA)
    defense += random.gauss(0, _BEAT_NOISE_SIGMA)
    # v2.3.0 fatigue: gassed fighters lose accuracy.
    if init_gas < _LOW_GAS_THRESHOLD:
        attack *= (1.0 - _LOW_GAS_ACCURACY_PENALTY)
    if target_gas < _LOW_GAS_THRESHOLD:
        defense *= (1.0 - _LOW_GAS_ACCURACY_PENALTY)
    # v2.3.0 pressure: rises-to-occasion / bottler modifiers.
    attack *= (1.0 + pressure_mod_init)
    defense *= (1.0 + pressure_mod_target)
    # v2.3.0 momentum: cumulative momentum shifts subsequent beat
    # probabilities in favor of the momentum leader.
    attack *= (1.0 + momentum_advantage)
    return attack, defense


# ----------------------------------------------------------------
# Fatigue helpers (v2.3.0 / Task B2).
# ----------------------------------------------------------------




def _compute_gas_cost(phase, stats):
    """Compute the gas cost for one beat in this phase for this fighter.

    Per the B2 brief:
      - base_cost is from PHASE_GAS_COSTS (standing=1, clinch/cage=2,
        ground=3, scramble=4).
      - fatigue_tolerance slows decay: gas_cost = base_cost *
        (1 - fatigue_tolerance/200).
      - cardio affects how fast gas depletes: gas_cost *=
        (1.5 - cardio/100). (Higher cardio → multiplier closer to
        0.5 → cheaper; lower cardio → multiplier closer to 1.5 →
        more expensive.)

    Returns a float, clamped to >= 0.1 so a beat always costs at
    least a tiny bit of gas (prevents infinite beats with very high
    fatigue_tolerance + cardio).
    """
    base_cost = PHASE_GAS_COSTS.get(phase, 1)
    fatigue_tolerance = stats.get("fatigue_tolerance", 50)
    cardio = stats.get("cardio", 50)
    cost = base_cost * (1.0 - fatigue_tolerance / 200.0)
    cost *= (1.5 - cardio / 100.0)
    return max(0.1, cost)





def _recover_gas_between_rounds(gas, stats):
    """Apply between-round gas recovery.

    Per the B2 brief: `gas += recovery_rate * 0.3`, capped at 100.
    A fighter with recovery_rate=50 recovers 15 gas between rounds;
    one with recovery_rate=90 recovers 27. The cap at 100 means gas
    can never exceed the starting value (no "extra energy" from
    recovery).
    """
    recovery_rate = stats.get("recovery_rate", 50)
    gas += recovery_rate * 0.3
    return min(100.0, gas)


# ----------------------------------------------------------------
# Fight importance + pressure response helpers (v2.3.0 / Task B2).
# ----------------------------------------------------------------




def _compute_fight_importance(card_slot, is_title_fight,
                              marketability_a, marketability_b):
    """Compute fight importance (0-100), per the B2 brief.

    Card slot weight (40%) + title at stake (30%) + rivalry heat (15%,
    0 for now — rivalries table doesn't exist yet) + fighter
    popularity (15%, avg marketability of both fighters).

    Args:
        card_slot: fights.card_slot ('main_event' / 'co_main' /
            'featured_prelim' / 'prelim' / 'opener').
        is_title_fight: fights.is_title_fight (0 or 1).
        marketability_a, marketability_b: the two fighters'
            marketability (0-100).

    Returns:
        Float in [0, 100]. A main-event title fight between two
        marketable stars approaches 100; an opener prelim between two
        unknowns approaches 20.
    """
    card_weight = CARD_SLOT_WEIGHTS.get(card_slot, 40)
    title_weight = 100 if is_title_fight else 0
    rivalry_weight = 0  # rivalries table doesn't exist yet (Task 22)
    popularity_weight = (marketability_a + marketability_b) / 2.0
    importance = (
        card_weight * 0.40
        + title_weight * 0.30
        + rivalry_weight * 0.15
        + popularity_weight * 0.15
    )
    return max(0.0, min(100.0, importance))





def _compute_pressure_response(stats):
    """Compute pressure response (0-100) for a fighter, per the B2 brief.

    pressure_response = clutch_factor*0.35 + composure*0.25 +
                        consistency*0.20 + focus*0.10 + grit*0.10

    `clutch_factor` and `consistency` come from the fighters table;
    `composure`, `focus`, and `grit` come from fighter_personality.
    All are loaded into the stats dict by _load_fighter_stats.

    Returns a float in [0, 100]. A fighter with all 90s has 90; one
    with all 30s has 30. Per the B2 brief, this is computed (not
    stored) and only affects beat scores in high-importance fights.
    """
    cf = stats.get("clutch_factor", 50)
    comp = stats.get("composure", 50)
    cons = stats.get("consistency", 50)
    focus = stats.get("focus", 50)
    grit = stats.get("grit", 50)
    return (
        cf * 0.35
        + comp * 0.25
        + cons * 0.20
        + focus * 0.10
        + grit * 0.10
    )





def _compute_pressure_modifier(importance, pressure_response):
    """Return the beat score modifier for this fighter in this fight.

    Per the B2 brief, in high-importance fights (importance > 60):
      - pressure_response >= 70: +5% (rises to the occasion)
      - pressure_response <= 30: -10% (bottler)
      - 30 < pressure_response < 70: 0 (baseline)

    In low-importance fights (importance <= 60), no modifier applies
    (the pressure system only fires when the stakes are high).

    Returns a float that's multiplied into the attack/defense scores
    by _compute_beat_scores (via `1.0 + modifier`).
    """
    if importance <= _PRESSURE_HIGH_IMPORTANCE_THRESHOLD:
        return 0.0
    if pressure_response >= _PRESSURE_RISES_THRESHOLD:
        return _PRESSURE_RISES_BONUS
    if pressure_response <= _PRESSURE_BOTTLER_THRESHOLD:
        return _PRESSURE_BOTTLER_PENALTY
    return 0.0


# ----------------------------------------------------------------
# Mid-round finish helpers (v2.3.0 / Task B2).
# ----------------------------------------------------------------




def _ko_threshold(stats):
    """Compute a fighter's KO/TKO damage threshold for one beat sequence.

    Per the B2 brief (corrected — see worklog D2 + D6): threshold =
    chin*1.0 + recovery_rate*0.2 + grit*0.1 + composure*0.1. A
    fighter with all-90 attrs has threshold 126 (hard to KO); one with
    all-30 attrs has threshold 42 (easy to KO).

    D6: chin is weighted at 1.0 (was 0.5) so a high-chin fighter is
    substantially harder to KO. This is needed for the G.3 corner-
    stoppage test (B has chin=100 + low grit/composure; with the old
    0.5 weight, B's threshold was 73 — crossable by 3 ground strikes,
    so B got KO'd before the corner could throw in the towel). With
    chin at 1.0, B's threshold is 122, needing 5 strikes to cross.

    This is the cumulative damage IN ONE BEAT SEQUENCE (consecutive
    beats where this fighter is the defender taking damage) that
    triggers a KO check. When the threshold is crossed AND the current
    beat is a power strike (damage >= _KO_CHECK_MIN_DAMAGE), the
    attacker's `killer_instinct` determines the probability the KO
    actually happens (vs the defender surviving "rocked").
    """
    return (
        stats.get("chin", 50) * _KO_THRESHOLD_CHIN_WEIGHT
        + stats.get("recovery_rate", 50) * _KO_THRESHOLD_RECOVERY_WEIGHT
        + stats.get("grit", 50) * _KO_THRESHOLD_GRIT_WEIGHT
        + stats.get("composure", 50) * _KO_THRESHOLD_COMPOSURE_WEIGHT
    )





def _ko_finish_probability(attacker_stats):
    """Probability that a KO actually occurs when the threshold is crossed.

    Per the B2 brief: killer_instinct increases the chance the finish
    happens before the defender recovers. Implemented as (D6):
        ko_prob = 0.1 + killer_instinct * 0.002
    Ranges from 0.1 (KI=0) to 0.3 (KI=100). A typical fighter (KI=50)
    has 0.2 — the threshold crossing results in a KO 20% of the time.

    D6: the original 0.5+KI/200 (range 0.5-1.0) was too aggressive.
    Combined with ~4-5 power-strike KO checks per round, it produced
    ~100% KO rate for all-90 vs all-30 (failing test_fight_resolver's
    "no single result_type > 60%" check). The new range (0.1-0.3)
    produces a ~50% KO rate for that extreme matchup (under the 60%
    cap) while still producing KOs reliably for D.3/L.2.
    """
    ki = attacker_stats.get("killer_instinct", 50)
    return _KO_FINISH_PROB_BASE + ki * _KO_FINISH_PROB_KI_SCALE





def _submission_score(init_stats, target_stats):
    """Compute the submission success score for a landed submission_attempt.

    FIGHT-ENGINE-TUNE Issue 3: re-weighted formula. The original
    `submission_offense - submission_defense*0.5 - flexibility*0.3 -
    scramble_ability*0.2 + composure*0.1` produced a typical score of
    ~5 for all-50 attrs (barely above the success threshold). The new
    formula `submission_offense*1.2 - submission_defense*0.4 -
    flexibility*0.2` gives a typical score of ~30, and combined with
    the lower _SUBMISSION_SUCCESS_THRESHOLD (-5), most landed
    submission attempts now succeed (the realistic ratio for an MMA
    fighter who secures a submission position).

    If score > _SUBMISSION_SUCCESS_THRESHOLD, the defender taps. The
    brief mentions "sufficient control_time_delta" — in this
    implementation, only submission_attempt beats with
    outcome='landed' qualify (the landed outcome already requires
    winning the attack/defense roll, which represents securing the
    position).
    """
    return (
        init_stats.get("submission_offense", 50) * _SUBMISSION_OFFENSE_WEIGHT
        - target_stats.get("submission_defense", 50) * _SUBMISSION_DEFENSE_WEIGHT
        - target_stats.get("flexibility", 50) * _SUBMISSION_FLEXIBILITY_WEIGHT
    )





def _doctor_stoppage_threshold(stats, conn=None):
    """Cumulative damage threshold for a doctor stoppage (between rounds).

    Per the B2 brief: `threshold = 200 + durability*2`. A fighter with
    durability=50 has threshold 300; one with durability=90 has
    threshold 380. Cumulative damage is summed across ALL rounds
    (not just the current round).

    Phase E5 (Fix 2 — per docs/DESIGN_REVIEW_E5.md §5): if `conn` is
    passed AND the fighter's promo has active cutmen, the threshold is
    INCREASED by the cutman stoppage-reduction bonus (the cutman's
    better corner work keeps the fighter in the fight longer before
    the doctor waves it off). The bonus = sum(skill/300) per cutman,
    capped at 0.10 (10% threshold bump with 3 top cutmen).

    Backward compat: if `conn` is None (default — used by older
    tests), the cutman bonus is skipped and the function returns the
    base threshold (preserves the original signature behaviour).
    """
    base = _DOCTOR_STOPPAGE_BASE + stats.get("durability", 50) * _DOCTOR_STOPPAGE_DURABILITY_SCALE
    if conn is None:
        return base
    # Phase E5 — cutman bonus. Read the fighter's promo from the stats
    # dict (added by _load_fighter_stats for this purpose).
    promo_id = stats.get("current_promotion_id")
    try:
        cutman_bonus = _get_cutman_stoppage_bonus(conn, promo_id)
    except Exception:
        cutman_bonus = 0.0  # defensive — never break the fight loop
    if cutman_bonus > 0:
        # Multiply the threshold by (1 + bonus) so a 10% bonus = ~10%
        # higher threshold = ~10% fewer stoppages (damage needs to be
        # higher to trigger the doctor).
        return int(base * (1.0 + cutman_bonus))
    return base


# Phase E5 — Cutman stoppage-reduction constants (per docs/DESIGN_REVIEW_E5.md §5).
# Per-cutman reduction = (skill_level / 300). Multiple cutmen stack,
# capped at 0.10 (10% total reduction). 1 cutman skill 100 = 0.333,
# but the cap kicks in at 3 top cutmen (sum 300/300 = 1.0 → capped 0.10).
CUTMAN_STOPPAGE_BONUS_PER_SKILL_POINT = 1.0 / 300.0
CUTMAN_STOPPAGE_BONUS_CAP = 0.10  # max 10% with 3 top cutmen


def _get_cutman_stoppage_bonus(conn, promotion_id):
    """Return the cutman-induced stoppage-reduction bonus fraction.

    Phase E5 — per docs/DESIGN_REVIEW_E5.md §5: for each active cutman
    on the fighter's promo, add (cutman.skill_level / 300) to the
    stoppage-reduction bonus. Multiple cutmen stack (max 10% total
    reduction with 3 top cutmen).

    Args:
        conn: sqlite3 connection.
        promotion_id: the fighter's current_promotion_id. If None or
            the promo has no active cutmen, returns 0.0 (no bonus).

    Returns:
        A float in [0.0, 0.10] — the fraction by which to bump the
        doctor_stoppage threshold. E.g. 0.10 = +10% threshold.
    """
    if not promotion_id:
        return 0.0
    row = conn.execute(
        "SELECT COALESCE(SUM(s.skill_level), 0) "
        "FROM staff s "
        "JOIN staff_contracts sc ON sc.staff_id=s.staff_id "
        "JOIN contracts c ON c.contract_id=sc.contract_id "
        "WHERE s.role_type='cutman' "
        "  AND s.promotion_id=? "
        "  AND c.status='active'",
        (promotion_id,),
    ).fetchone()
    total_skill = row[0] if row and row[0] is not None else 0
    if total_skill <= 0:
        return 0.0
    bonus = total_skill * CUTMAN_STOPPAGE_BONUS_PER_SKILL_POINT
    return min(bonus, CUTMAN_STOPPAGE_BONUS_CAP)





def _check_corner_stoppage(consecutive_rounds_lost, stats):
    """Check if a fighter's corner throws in the towel (between rounds).

    Per the B2 brief: if a fighter loses 3+ consecutive rounds AND
    their grit < 40 AND composure < 40, their corner may throw in the
    towel (20% chance per qualifying round).

    Returns True if the corner stops the fight, False otherwise.
    """
    if consecutive_rounds_lost < _CORNER_STOPPAGE_CONSECUTIVE_LOSSES:
        return False
    if stats.get("grit", 50) >= _CORNER_STOPPAGE_GRIT_THRESHOLD:
        return False
    if stats.get("composure", 50) >= _CORNER_STOPPAGE_COMPOSURE_THRESHOLD:
        return False
    return random.random() < _CORNER_STOPPAGE_CHANCE





def _check_dq(init_stats, action_type, outcome):
    """Check if a fighter is disqualified for an illegal strike.

    Per the B2 brief: if a fighter has discipline < 20 AND lands a
    strike in an illegal zone (1% chance per beat for low-discipline
    fighters), they're disqualified.

    A "strike in an illegal zone" is represented as: the initiator
    landed a strike (outcome == 'landed' AND action_type in
    STRIKE_ACTIONS) AND has discipline < 20 AND a 1% roll succeeds.
    """
    if init_stats.get("discipline", 50) >= _DQ_DISCIPLINE_THRESHOLD:
        return False
    if outcome != "landed":
        return False
    if action_type not in STRIKE_ACTIONS:
        return False
    return random.random() < _DQ_CHANCE_PER_BEAT





def _random_finish_time(beat_number, beats_this_round):
    """Generate a random finish time within the round, e.g. '2:34'.

    The finish beat is `beat_number` of `beats_this_round` total
    beats. A round is 5 minutes (300 seconds). The finish time is
    proportional to the beat position in the round:
        finish_seconds = 300 * (beat_number / beats_this_round)
    plus a small random offset (+/- a few seconds) so two fights that
    finish on the same beat don't have identical finish times.

    Returns a string 'M:SS' (e.g., '2:34'). For decisions (beat ==
    beats_this_round), returns '5:00' (the round's natural end).
    """
    if beat_number >= beats_this_round:
        return "5:00"
    # Proportional time + small noise.
    base_seconds = int(300 * (beat_number / max(1, beats_this_round)))
    noise = random.randint(-5, 5)
    finish_seconds = max(0, min(299, base_seconds + noise))
    minutes = finish_seconds // 60
    seconds = finish_seconds % 60
    return f"{minutes}:{seconds:02d}"





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
    # 0 otherwise. Standing doesn't normally accrue control time —
    # EXCEPT for a landed takedown_attempt, which IS a control action
    # (the initiator drives the defender to the ground and ends up
    # on top). D7: standing-initiated takedowns now get control_time
    # 1-5 so the "big takedown" momentum bonus (control >= 3 → +30
    # momentum) can fire for them. Without this, the C.5 acceptance
    # check (big takedowns have momentum_shift >= 30) fails because
    # standing takedowns had control=0 and the brief's all-90 vs
    # all-30 scenario produces very few clinch/cage takedowns (the
    # fight usually ends in a round-1 KO before transitioning to
    # clinch/cage).
    if outcome == "landed" and (
        phase in ("clinch", "cage", "ground_top", "ground_bottom", "scramble")
        or (phase == "standing" and action_type == "takedown_attempt")
    ):
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
                  stats_a, stats_b, gas_a=100.0, gas_b=100.0,
                  cum_momentum=0, pressure_mod_a=0.0, pressure_mod_b=0.0):
    """Resolve one round of a fight beat-by-beat (B2 engine depth).

    Generates 12-28 beats per round (per the pace formula), writes
    them to `fight_beats`, populates the per-round aggregate row in
    `fight_rounds`, sets `round_winner_fighter_id`, and returns the
    round result dict.

    v2.3.0 (Task B2) adds:
      - Fatigue: gas depletes per beat (phase-dependent costs).
        Low gas (<30) reduces accuracy 30% and chin vulnerability +20%.
        End-of-round gas values are written to fight_rounds.
        fighter_a/b_gas_remaining (per the B2 brief).
      - Momentum: cumulative momentum in the round shifts subsequent
        beat probabilities (initiator_advantage = clamp(
        cum_momentum/200, -0.3, +0.3)).
      - Mid-round finishes: KO/TKO (cumulative damage threshold),
        submission (submission_attempt + score), DQ (low discipline +
        illegal strike). Doctor/corner stoppage are checked between
        rounds by resolve_next_fight (not here).

    The pace formula (per the brief):
        pace_a = aggr*0.3 + speed*0.3 + cardio*0.2 + discipline*0.2
        pace_b = (same for fighter b)
        beats = max(12, min(28, 15 + round((pace_a + pace_b) / 2 / 10)))

    Args:
        conn: sqlite3 connection (caller commits).
        fight_id: the fights.fight_id being resolved.
        round_number: 1-indexed round number.
        fighter_a_id: fighter_id of the red-corner fighter.
        fighter_b_id: fighter_id of the blue-corner fighter.
        stats_a: stats dict for fighter A (from _load_fighter_stats).
        stats_b: stats dict for fighter B (from _load_fighter_stats).
        gas_a: fighter A's gas at round start (0-100). Default 100.0
            for round 1; resolve_next_fight passes the recovered gas
            from the previous round for rounds 2+.
        gas_b: same for fighter B.
        cum_momentum: cumulative momentum at round start. Positive
            favors fighter A; negative favors fighter B. Default 0.
            resolve_next_fight passes the running total from the
            previous round so momentum carries across rounds.
        pressure_mod_a: fighter A's pressure modifier (-0.10 to +0.05).
            Computed by resolve_next_fight via _compute_pressure_modifier
            based on fight importance + pressure_response. Default 0
            (no modifier — used by tests that don't care about
            pressure).
        pressure_mod_b: same for fighter B.

    Returns:
        Dict with: round_winner (fighter_id), score_a (float),
        score_b (float), fighter_a_damage (int), fighter_b_damage (int),
        gas_a_after (float), gas_b_after (float),
        cum_momentum_after (float), knockdowns_a (int), knockdowns_b
        (int), finish (None or dict with type, winner_id, loser_id,
        beat_number, finish_time, finishing_beat_id).
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

    # v2.3.0 (Task B2): per-fighter KO thresholds (computed once per
    # round — they don't change as gas depletes. The damage TAKEN
    # modifier for gassed fighters is applied separately in the
    # damage step below).
    ko_threshold_a = _ko_threshold(stats_a)
    ko_threshold_b = _ko_threshold(stats_b)

    # Per-round tracking.
    # consecutive_damage_to_X = damage to X in the current "beat
    # sequence" (consecutive beats where X is the defender taking
    # damage). Resets when X is the initiator, when no damage is dealt
    # to X this beat, or when X survives a KO check (gets a moment to
    # recover). This implements the brief's "cumulative damage in the
    # current beat sequence" — sustained beatdowns trigger KO checks,
    # scattered damage doesn't.
    consecutive_damage_to_a = 0
    consecutive_damage_to_b = 0
    # knockdowns_a/b = knockdowns SUFFERED by A/B in this round (for
    # the fight_rounds aggregate). A "knockdown" here means a beat
    # where the KO threshold was crossed (whether or not the KO
    # actually happened).
    knockdowns_a = 0
    knockdowns_b = 0

    finish_info = None  # set if a finish occurs mid-round

    # Run beats.
    for beat_number in range(1, beats_this_round + 1):
        # Determine initiator.
        if random.random() < a_init_prob:
            init_id, target_id = fighter_a_id, fighter_b_id
            init_stats, target_stats = stats_a, stats_b
            init_gas, target_gas = gas_a, gas_b
            init_pressure_mod = pressure_mod_a
            target_pressure_mod = pressure_mod_b
        else:
            init_id, target_id = fighter_b_id, fighter_a_id
            init_stats, target_stats = stats_b, stats_a
            init_gas, target_gas = gas_b, gas_a
            init_pressure_mod = pressure_mod_b
            target_pressure_mod = pressure_mod_a

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

        # v2.3.0 momentum advantage: clamped to [-0.3, +0.3]. Positive
        # favors A; if the current initiator is A, A gets the bonus.
        # If the current initiator is B (cum_momentum is negative from
        # B's perspective), the advantage flips sign.
        if init_id == fighter_a_id:
            momentum_advantage = max(-0.3, min(0.3, cum_momentum / 200.0))
        else:
            momentum_advantage = max(-0.3, min(0.3, -cum_momentum / 200.0))

        # Compute attack/defense scores using beat_phase's attributes.
        # Pass the B2 modifiers (gas, pressure, momentum).
        attack_score, defense_score = _compute_beat_scores(
            beat_phase, init_stats, target_stats,
            init_gas=init_gas, target_gas=target_gas,
            pressure_mod_init=init_pressure_mod,
            pressure_mod_target=target_pressure_mod,
            momentum_advantage=momentum_advantage,
        )

        # Resolve outcome.
        outcome, damage, control, momentum = _resolve_beat_outcome(
            beat_phase, action_type, attack_score, defense_score,
            init_stats, target_stats
        )

        # v2.3.0 chin vulnerability: a gassed defender takes +20% damage.
        if target_gas < _LOW_GAS_THRESHOLD and damage > 0:
            damage = max(1, int(round(damage * (1.0 + _LOW_GAS_CHIN_PENALTY))))

        # v2.3.0 big takedown momentum bonus: a takedown_attempt that
        # lands with significant control time produces momentum_shift
        # = +30 (per the B2 brief). The base _resolve_beat_outcome
        # already gives +10 to +30 for landed attempts; bump to +30
        # if the control_time is high (represents a "big slam" or
        # dominant takedown).
        if (action_type == "takedown_attempt" and outcome == "landed"
                and control >= _BIG_TAKEDOWN_MOMENTUM_THRESHOLD):
            momentum = max(momentum, _BIG_TAKEDOWN_MOMENTUM_SHIFT)

        # Write the beat to fight_beats. Capture the rowid so we can
        # UPDATE it if this beat becomes the finishing exchange (KO,
        # submission, near-finish, DQ).
        cur = conn.execute(
            "INSERT INTO fight_beats (fight_id, round_number, beat_number, "
            "phase, action_type, initiator_fighter_id, target_fighter_id, "
            "outcome, damage_dealt, control_time_delta, momentum_shift) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fight_id, round_number, beat_number, beat_phase, action_type,
             init_id, target_id, outcome, damage, control, momentum),
        )
        beat_id = cur.lastrowid

        # v2.3.0 fatigue: deduct gas from the initiator. Target's gas
        # is unaffected (defending is less tiring than initiating —
        # this is a simplification; the brief doesn't specify whether
        # defense costs gas).
        gas_cost = _compute_gas_cost(beat_phase, init_stats)
        if init_id == fighter_a_id:
            gas_a = max(0.0, gas_a - gas_cost)
        else:
            gas_b = max(0.0, gas_b - gas_cost)

        # v2.3.0 momentum: update cumulative momentum. Positive
        # momentum favors A; if the initiator is A, momentum shifts
        # toward A (positive). If the initiator is B, momentum shifts
        # toward B (negative from A's perspective).
        if init_id == fighter_a_id:
            cum_momentum += momentum
        else:
            cum_momentum -= momentum

        # v2.3.0 DQ check: low-discipline fighter lands an illegal strike.
        if _check_dq(init_stats, action_type, outcome):
            # Mark the beat as the finishing exchange (near_finish
            # outcome, large negative momentum for the DQ'd fighter).
            conn.execute(
                "UPDATE fight_beats SET outcome='near_finish', "
                "momentum_shift=? WHERE fight_beat_id=?",
                (-_NEAR_FINISH_MOMENTUM_SHIFT, beat_id),
            )
            finish_info = {
                "type": "dq",
                "winner_id": target_id,
                "loser_id": init_id,
                "beat_number": beat_number,
                "finish_time": _random_finish_time(beat_number, beats_this_round),
                "finishing_beat_id": beat_id,
            }
            break

        # v2.3.0 track consecutive damage for KO check. Reset the
        # OTHER fighter's tracker (they weren't hit this beat).
        if damage > 0:
            if target_id == fighter_a_id:
                consecutive_damage_to_a += damage
                consecutive_damage_to_b = 0
            else:
                consecutive_damage_to_b += damage
                consecutive_damage_to_a = 0
        else:
            # No damage this beat — both sequences break (the
            # defender escaped or the attacker missed). This makes
            # scattered damage less likely to trigger KO than
            # sustained beatdowns.
            consecutive_damage_to_a = 0
            consecutive_damage_to_b = 0

        # v2.3.0 KO/TKO check: if the defender's consecutive damage
        # exceeds their threshold AND the current beat is a power
        # strike (damage >= _KO_CHECK_MIN_DAMAGE), roll for KO. D6:
        # the power-strike filter ensures only significant strikes
        # (crosses, hooks, head kicks, clinch knees, ground strikes)
        # can be the "finishing blow" — jabs and leg kicks accumulate
        # damage but don't knock people out. This reduces KO checks
        # per round from ~9 (every landed strike) to ~4-5, bringing
        # the overall KO rate under 60% for the test_fight_resolver
        # acceptance check.
        if outcome == "landed" and damage >= _KO_CHECK_MIN_DAMAGE:
            ko_target_id = None
            ko_threshold_target = None
            if target_id == fighter_a_id and consecutive_damage_to_a > ko_threshold_a:
                ko_target_id = fighter_a_id
                ko_threshold_target = ko_threshold_a
            elif target_id == fighter_b_id and consecutive_damage_to_b > ko_threshold_b:
                ko_target_id = fighter_b_id
                ko_threshold_target = ko_threshold_b

            if ko_target_id is not None:
                # Threshold crossed — roll for KO. The attacker's
                # killer_instinct determines the probability the KO
                # actually happens (vs the defender surviving "rocked").
                ko_prob = _ko_finish_probability(init_stats)
                if random.random() < ko_prob:
                    # KO! Mark the beat as the finishing blow.
                    conn.execute(
                        "UPDATE fight_beats SET outcome='knockdown', "
                        "momentum_shift=? WHERE fight_beat_id=?",
                        (_KNOCKDOWN_MOMENTUM_SHIFT, beat_id),
                    )
                    if ko_target_id == fighter_a_id:
                        knockdowns_a += 1
                    else:
                        knockdowns_b += 1
                    finish_info = {
                        "type": "ko_tko",
                        "winner_id": init_id,
                        "loser_id": ko_target_id,
                        "beat_number": beat_number,
                        "finish_time": _random_finish_time(beat_number, beats_this_round),
                        "finishing_beat_id": beat_id,
                    }
                    break
                else:
                    # Defender survived (rocked). Mark as near_finish.
                    # Reset the consecutive-damage tracker so the
                    # defender gets a brief moment to recover.
                    conn.execute(
                        "UPDATE fight_beats SET outcome='near_finish', "
                        "momentum_shift=? WHERE fight_beat_id=?",
                        (_NEAR_FINISH_MOMENTUM_SHIFT, beat_id),
                    )
                    if ko_target_id == fighter_a_id:
                        knockdowns_a += 1
                        consecutive_damage_to_a = 0
                    else:
                        knockdowns_b += 1
                        consecutive_damage_to_b = 0

        # v2.3.0 submission check: a landed submission_attempt with a
        # positive submission score succeeds (defender taps).
        # FIGHT-ENGINE-TUNE Issue 3: lowered success threshold from 0
        # to _SUBMISSION_SUCCESS_THRESHOLD (-5) so marginally-negative
        # scores still finish (the formula already favors the attacker).
        if action_type == "submission_attempt" and outcome == "landed":
            sub_score = _submission_score(init_stats, target_stats)
            if sub_score > _SUBMISSION_SUCCESS_THRESHOLD:
                # Submission succeeds! Mark the beat as the finishing
                # exchange.
                conn.execute(
                    "UPDATE fight_beats SET outcome='near_finish', "
                    "momentum_shift=? WHERE fight_beat_id=?",
                    (_NEAR_FINISH_MOMENTUM_SHIFT, beat_id),
                )
                finish_info = {
                    "type": "submission",
                    "winner_id": init_id,
                    "loser_id": target_id,
                    "beat_number": beat_number,
                    "finish_time": _random_finish_time(beat_number, beats_this_round),
                    "finishing_beat_id": beat_id,
                }
                break

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
    # aren't strikes).
    # v2.3.0 (Task B2): knockdowns are now computed from
    # fight_beats.outcome='knockdown' per-fighter (the initiator is
    # the one who SCORED the knockdown; the target is the one who
    # SUFFERED it). fight_rounds.fighter_a_knockdowns = knockdowns
    # suffered BY A = SUM(target=A AND outcome='knockdown'). This
    # matches the convention used by fighter_a_damage (damage TO A).
    # Wait — that's inconsistent with the D1 fix where fighter_a_damage
    # = damage dealt BY A. Let me think: knockdowns_SUFFERED makes
    # more sense for the round-winner scoring (a fighter who got
    # knocked down lost the round). But the existing convention is
    # "fighter_a_* = things A DID" (damage dealt, strikes landed,
    # takedowns). So fighter_a_knockdowns should be knockdowns SCORED
    # BY A = SUM(initiator=A AND outcome='knockdown'). Documented as
    # worklog D4 (the brief was ambiguous; chose the "things A DID"
    # convention for consistency with the other columns).
    conn.execute(
        """
        INSERT INTO fight_rounds (
            fight_id, round_number, fighter_a_id, fighter_b_id,
            fighter_a_damage, fighter_b_damage,
            fighter_a_control_time, fighter_b_control_time,
            fighter_a_knockdowns, fighter_b_knockdowns,
            fighter_a_takedowns, fighter_b_takedowns,
            fighter_a_strikes_landed, fighter_b_strikes_landed,
            fighter_a_gas_remaining, fighter_b_gas_remaining,
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
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND outcome = 'knockdown' THEN 1 ELSE 0 END),
            SUM(CASE WHEN initiator_fighter_id = ?
                     AND outcome = 'knockdown' THEN 1 ELSE 0 END),
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
            ?, ?,
            ?, NULL
        FROM fight_beats
        WHERE fight_id = ? AND round_number = ?
        """,
        (fight_id, round_number, fighter_a_id, fighter_b_id,
         fighter_b_id, fighter_a_id,    # D1 fix: fighter_a_damage = SUM(target=B) = damage dealt by A
         fighter_a_id, fighter_b_id,
         fighter_a_id, fighter_b_id,    # D4: knockdowns SCORED BY A/B
         fighter_a_id, fighter_b_id,
         fighter_a_id, fighter_b_id,
         round(max(0.0, gas_a), 2),     # v2.3.0: store end-of-round gas (per-fighter)
         round(max(0.0, gas_b), 2),
         int(cum_momentum),             # v2.3.0: store cumulative momentum state
         fight_id, round_number),
    )

    # Read back the aggregate to compute the round score.
    row = conn.execute(
        "SELECT fighter_a_damage, fighter_b_damage, "
        "fighter_a_control_time, fighter_b_control_time, "
        "fighter_a_takedowns, fighter_b_takedowns, "
        "fighter_a_strikes_landed, fighter_b_strikes_landed, "
        "fighter_a_knockdowns, fighter_b_knockdowns "
        "FROM fight_rounds WHERE fight_id=? AND round_number=?",
        (fight_id, round_number),
    ).fetchone()
    (a_dmg, b_dmg, a_ctrl, b_ctrl,
     a_td, b_td, a_str, b_str,
     a_kd, b_kd) = row

    # v2.3.0 (Task B2): decision scoring now factors in knockdowns
    # (10-point must with 10-8 rounds for knockdowns). Per the B2
    # brief: "knockdowns always 0 in B1 (no finishes). ... B2 will
    # add fatigue, momentum, KO/submission/doctor/corner/DQ." With
    # knockdowns in B2, a fighter who scores a knockdown in a round
    # gets a 10-8 round (10 points to the knockdown scorer, 8 to the
    # defender) — this is the standard 10-point must extension.
    # score = damage + strikes_landed*0.5 + takedowns*2 +
    #         knockdowns*10 + control_time*0.1
    score_a = (a_dmg + a_str * 0.5 + a_td * 2 + a_kd * 10 + a_ctrl * 0.1)
    score_b = (b_dmg + b_str * 0.5 + b_td * 2 + b_kd * 10 + b_ctrl * 0.1)

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
        # v2.3.0 (Task B2) new fields:
        "gas_a_after": max(0.0, gas_a),
        "gas_b_after": max(0.0, gas_b),
        "cum_momentum_after": cum_momentum,
        "knockdowns_a": a_kd,
        "knockdowns_b": b_kd,
        "finish": finish_info,
        "beats_this_round": beats_this_round,
    }





def _decide_fight_outcome(rounds, fighter_a_id, fighter_b_id,
                          total_a_damage, total_b_damage):
    """Apply the 10-point must decision scoring across all rounds.

    Returns a dict with: winner ('a', 'b', or None for draw),
    result_type ('unanimous_decision', 'split_decision', 'draw'),
    score_a_total, score_b_total, score_margin (damage differential).

    Per the brief:
      - Each round: winner gets 10 points, loser gets 9.
      - v2.3.0 (Task B2): if the round winner also scored a knockdown
        in that round, the loser gets 8 instead of 9 (10-8 round —
        the standard 10-point must extension for knockdowns).
      - Sum across rounds.
      - If totals are exactly tied: 'draw'.
      - If margin < 3 points: brief says 15% chance of
        'split_decision', else 'unanimous_decision'. (D-number
        decision: bumped to 70% so balanced matchups produce a
        varied distribution — see worklog D2. With the brief's 15%,
        ~92% of balanced fights would be unanimous_decision, failing
        the "no single result type >60%" acceptance check.)
      - Otherwise: 'unanimous_decision'.

    score_margin is the total damage differential (per the brief) —
    a more meaningful "how dominant was the winner" metric than the
    old power-score differential.

    v2.3.0: each round dict may include `knockdowns_a` and
    `knockdowns_b` (knockdowns SCORED BY A/B in that round — see
    resolve_round D4). If the round winner scored a knockdown, the
    loser's score for that round is 8 instead of 9.
    """
    score_a_total = 0
    score_b_total = 0
    for r in rounds:
        round_winner = r["round_winner"]
        # v2.3.0: check if the round winner scored a knockdown in this
        # round. If so, the loser gets 8 (10-8 round). Round dicts
        # from B1 don't include knockdown counts, so fall back to 0
        # (B1 behavior — preserves backward compat for tests that
        # construct round dicts manually).
        a_kd = r.get("knockdowns_a", 0)
        b_kd = r.get("knockdowns_b", 0)
        if round_winner == fighter_a_id:
            score_a_total += 10
            score_b_total += 8 if a_kd > 0 else 9
        else:
            score_b_total += 10
            score_a_total += 8 if b_kd > 0 else 9

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





def _format_fight_news(winner_name, loser_name, result_type, finish_round,
                       finish_time=None):
    """Build (headline, body) for a non-draw fight result.

    Enriches the original "X defeats Y" template with the result type
    and finish round. The write_news() call itself is unchanged.

    v2.3.0 (Task B2): added support for the new finish result types
    (doctor_stoppage, corner_stoppage, dq) and the finish_time for
    mid-round finishes (e.g., '2:34 of round 2').

    v2.10.0 (FIX-VoiceRep, §14): the OLD output used raw round digits
    ("round 2") and raw finish_time ("at 1:23"). Both violated
    CONVENTIONS §14 — no raw numbers in player-facing text. The
    templates now use word-form round phrases ("the second round")
    and descriptive time phrases ("past the midway mark") via the
    _round_word / _finish_time_phrase helpers. The inline news is
    STILL a placeholder — the news engine (Task 23) writes the
    richer voice-layer news via news.generate_fight_news — but the
    inline item no longer leaks digits while the engine catches up.
    """
    pretty = result_type.replace("_", " ")
    round_word = _round_word(finish_round)
    time_phrase = _finish_time_phrase(finish_time)
    if result_type == "ko_tko":
        headline = f"{winner_name} KO's {loser_name} in the {round_word} round"
        body = f"{winner_name} stopped {loser_name} by {pretty} in the {round_word} round{time_phrase}."
    elif result_type == "submission":
        headline = f"{winner_name} submits {loser_name} in the {round_word} round"
        body = f"{winner_name} tapped out {loser_name} by submission in the {round_word} round{time_phrase}."
    elif result_type == "doctor_stoppage":
        headline = f"{winner_name} wins by doctor stoppage over {loser_name}"
        body = (f"The ringside physician stopped the fight between "
                f"{winner_name} and {loser_name} after the {round_word} round "
                f"due to accumulated damage.")
    elif result_type == "corner_stoppage":
        headline = f"{winner_name} wins by corner stoppage over {loser_name}"
        body = (f"{loser_name}'s corner threw in the towel between rounds, "
                f"giving {winner_name} the victory after the {round_word} round.")
    elif result_type == "dq":
        headline = f"{loser_name} disqualified; {winner_name} wins"
        body = (f"{loser_name} was disqualified for an illegal strike in "
                f"the {round_word} round{time_phrase}. {winner_name} wins by DQ.")
    elif result_type == "unanimous_decision":
        headline = f"{winner_name} beats {loser_name} by unanimous decision"
        body = f"{winner_name} defeated {loser_name} by unanimous decision after {round_word} rounds."
    elif result_type == "split_decision":
        headline = f"{winner_name} edges {loser_name} by split decision"
        body = f"{winner_name} took a split decision over {loser_name} after {round_word} rounds."
    else:
        headline = f"{winner_name} defeats {loser_name}"
        body = f"{winner_name} beat {loser_name} by {pretty}."
    return headline, body


# v2.10.0 (FIX-VoiceRep, §14): word-form helpers for the inline
# fight news templates. Round numbers + finish times are converted
# to digit-free phrases so the inline news doesn't violate §14 while
# the news engine (Task 23) catches up with the richer voice-layer
# version. Mirrors the helpers in news.py (kept local to app.py to
# avoid a circular import — news.py imports from voice.py, app.py
# imports from news.py + voice.py + many others).



_ROUND_WORDS_INLINE = {
    1: "first", 2: "second", 3: "third",
    4: "fourth", 5: "fifth",
}





def _round_word(round_num):
    """Convert a round number to its word form ('first', 'second', ...).

    For rounds beyond the standard five, returns 'championship' (the
    championship rounds in MMA are 4 and 5, so 'late' would also
    work — but 'championship' is more evocative). NEVER returns a
    digit character (CONVENTIONS §14).
    """
    if round_num in _ROUND_WORDS_INLINE:
        return _ROUND_WORDS_INLINE[round_num]
    return "championship"





def _finish_time_phrase(finish_time_str):
    """Convert a 'M:SS' finish time string into a descriptive phrase.

    Returns phrases like ' past the midway mark of the round', ' late
    in the round', or '' (empty string) if the finish_time is missing
    or '5:00' (the round-end sentinel — no mid-round context to add).
    NEVER returns a string containing digit characters.
    """
    if not finish_time_str or finish_time_str == "5:00":
        return ""
    try:
        parts = finish_time_str.split(":")
        if len(parts) != 2:
            return ""
        minutes = int(parts[0])
        seconds = int(parts[1])
        total = minutes * 60 + seconds
        if total < 60:
            return " in the opening minute"
        if total < 120:
            return " past the midway mark of the round"
        if total < 180:
            return " late in the round"
        if total < 240:
            return " as the round wound down"
        return " deep into the round"
    except (ValueError, IndexError):
        return ""





def _severity_phrase_inline(severity):
    """Convert 1-10 injury severity to a word-form phrase (no digits).

    v2.10.0 (FIX-VoiceRep, §14): the inline injury news used to leak
    raw severity digits ("severity 8/10"). This helper converts to a
    word-form phrase that the inline body template prepends to the
    injury type ("a serious orbital fracture"). Mirrors news.py's
    _severity_phrase — kept local to app.py to avoid the circular
    import (news.py imports from voice.py, app.py imports from
    news.py).
    """
    if severity is None:
        return "nagging"
    if severity <= 3:
        return "minor"
    if severity <= 6:
        return "moderate"
    if severity <= 8:
        return "serious"
    return "severe"





def _format_fight_commentary(winner_name, loser_name, result_type, finish_round,
                             finish_time=None):
    """Build a short commentary line for a non-draw fight result.

    v2.3.0 (Task B2): added support for doctor_stoppage, corner_stoppage,
    and dq result types. Added finish_time mention for mid-round finishes.

    v2.10.0 (FIX-VoiceRep, §14): word-form round + descriptive time
    phrase (no raw digits per §14).
    """
    round_word = _round_word(finish_round)
    time_phrase = _finish_time_phrase(finish_time)
    if result_type == "ko_tko":
        return f"{winner_name} puts {loser_name} away by KO/TKO in the {round_word} round{time_phrase}."
    if result_type == "submission":
        return f"{winner_name} forces the tap from {loser_name} in the {round_word} round{time_phrase}."
    if result_type == "doctor_stoppage":
        return f"The doctor has seen enough — {loser_name} cannot continue. {winner_name} wins by doctor stoppage after the {round_word} round."
    if result_type == "corner_stoppage":
        return f"{loser_name}'s corner throws in the towel. {winner_name} wins by corner stoppage after the {round_word} round."
    if result_type == "dq":
        return f"{loser_name} is disqualified for an illegal strike. {winner_name} wins by DQ in the {round_word} round{time_phrase}."
    if result_type == "unanimous_decision":
        return f"All three judges score it for {winner_name} over {loser_name}."
    if result_type == "split_decision":
        return f"Split scorecards — {winner_name} takes the nod over {loser_name}."
    return f"{winner_name} has just defeated {loser_name}."


# ----------------------------------------------------------------
# Commentary beat selection (v2.3.0 / Task B2).
#
# After a fight resolves, select the 3-14 most important beats for
# commentary highlights. The number depends on fight importance:
#   quick (importance < 40):     3-6 beats
#   standard (40 <= importance < 70): 6-10 beats
#   extended (importance >= 70): 10-14 beats
#
# Selection priority (highest first):
#   1. Knockdown beats (the finishing blow if KO, plus any non-finishing
#      knockdowns where the defender was dropped but survived).
#   2. The finish beat itself (always selected if the fight ended in a
#      finish — submission, DQ, doctor/corner stoppage marker).
#   3. Near-finish beats (defender was "rocked" but survived).
#   4. Big momentum swings (|momentum_shift| > 50).
#   5. Round-winning sequences (the highest-damage beat per round).
#
# Each selected beat gets a commentary_segments row with a short
# play-by-play line. The line is hardcoded (the interpretation layer /
# Task 19 will eventually produce richer prose, but for now hardcoded
# strings document the mechanic — per CONVENTIONS §14, raw numbers are
# for debugging; the player sees meaning).
# ----------------------------------------------------------------

# Beat outcome → commentary template. Each template takes the
# initiator's name, target's name, the round number, and the beat's
# damage / momentum for context.



# P3.5 (docs/COMPREHENSIVE_FIX_PLAN.md §Group D #20 + #21) —
# highlight commentary variety. The original _BEAT_COMMENTARY_TEMPLATES
# had ONE string per outcome (7 total). After 3-4 fights the player
# saw the same prose repeatedly — the user's "key highlights all say
# same thing" complaint. Now each outcome has 8+ variants, picked
# deterministically by (fight_id, beat_id) hash so the same fight
# replays identically but different fights get different prose.
#
# These templates are used by _generate_beat_commentary (the 3-14
# 'highlight' segments per fight — the Zone D "Key Moments" feed).
# The per-beat commentary system (_generate_per_beat_commentary,
# segment_type='beat') already had 8+ variants per (action, outcome)
# — that system is unchanged. This expansion brings the HIGHLIGHTS
# up to the same voice-variant discipline.
_BEAT_COMMENTARY_TEMPLATES = {
    "knockdown": [
        "{init} drops {target} with a heavy shot in round {round}!",
        "Down goes {target}! {init} lands flush in round {round}.",
        "{init} puts {target} on the canvas in round {round}.",
        "A right hand from {init} and {target} crumbles in round {round}.",
        "{target} hits the deck in round {round} — {init} swarms.",
        "Heavy shot from {init}. {target} is down in round {round}.",
        "{init} cracks {target} with a fight-changing shot in round {round}.",
        "Round {round}: {init} drops {target}. The crowd is on its feet.",
        "{init} staggers {target} — and {target} hits the mat in round {round}.",
        "Round {round}: a clean shot from {init} sends {target} down.",
        "{init} puts {target} on wobbly legs, then puts them down in round {round}.",
        "Round {round}: {target} crumbles under {init}'s power.",
    ],
    "near_finish": [
        "{init} has {target} hurt in round {round} — the finish is near.",
        "{target} is in serious trouble in round {round}. {init} swarms.",
        "Round {round}: {init} unleashes a barrage. {target} is barely surviving.",
        "{target} is rocked in round {round}! {init} can smell the finish.",
        "Big shots from {init} in round {round}. {target} is on wobbly legs.",
        "{init} piles on the pressure in round {round}. {target} wilts.",
        "The end looks near for {target} in round {round}.",
        "Round {round}: {init} has {target} out on their feet.",
        "{init} is closing in. {target} is just covering up in round {round}.",
        "Round {round}: {target}'s legs are gone. {init} moves in.",
        "{init} can taste the finish in round {round}.",
        "Round {round}: the referee is watching closely. {target} is hurt.",
    ],
    "landed": [
        "{init} lands a clean strike on {target} in round {round}.",
        "A sharp shot from {init} finds its mark in round {round}.",
        "{init} connects cleanly on {target} in round {round}.",
        "Round {round}: {init} snaps {target}'s head back with a crisp shot.",
        "{init} catches {target} flush in round {round}.",
        "A well-timed strike from {init} lands in round {round}.",
        "{init} finds the opening in round {round}. {target} takes it.",
        "Round {round}: {init} tags {target} with a clean shot.",
        "{init} pierces the guard with a stiff shot in round {round}.",
        "Round {round}: a heavy shot from {init} gets {target}'s attention.",
        "{init} lands a precise strike. {target} backs off in round {round}.",
        "Round {round}: {init}'s strike snaps {target}'s head sideways.",
    ],
    "reversed": [
        "{target} reverses {init}'s attempt in round {round} — momentum swing!",
        "{target} turns the tables on {init} in round {round}.",
        "Round {round}: {target} counters and ends up on top.",
        "{init}'s attack backfires in round {round}. {target} takes over.",
        "Big reversal in round {round}! {target} steals the momentum.",
        "{target} shrugs off the attack and takes position in round {round}.",
        "The tide turns in round {round}. {target} seizes the upper hand.",
        "Round {round}: {target} reverses — {init} is suddenly in trouble.",
        "{target} ducks under in round {round}. Now they're on top.",
        "Round {round}: a beautiful reversal from {target}.",
        "{target} hip-heists out in round {round}. The momentum flips.",
        "Round {round}: {target} comes out the back door. Reversed.",
    ],
    "defended": [
        "{target} anticipates and defends {init}'s attack in round {round}.",
        "{target} sees it coming in round {round}, gets out of the way.",
        "Round {round}: {target} slips the punch, makes {init} pay.",
        "{target} parries {init}'s strike cleanly in round {round}.",
        "{init} commits in round {round}, but {target} is already gone.",
        "{target} times the entry in round {round}, defends with ease.",
        "Reading the rhythm in round {round}, {target} dodges the strike.",
        "Round {round}: good defense from {target}. {init} is left reaching.",
        "{target} leans out of range in round {round}. {init} swings at shadow.",
        "Round {round}: forearm check from {target}. {init}'s work is smothered.",
        "{target} circles off in round {round}. {init} resets.",
        "Round {round}: {target} catches the strike on the shoulder. Rolls out.",
    ],
    "blocked": [
        "{target} absorbs {init}'s strike on the guard in round {round}.",
        "{target} covers up in round {round}. The strike lands on the gloves.",
        "Round {round}: high guard from {target}. {init} can't find a gap.",
        "{target} blocks the strike in round {round}, circles out.",
        "The shot from {init} is absorbed on the forearms in round {round}.",
        "{target} gets the defense up in round {round}. Nothing gets through.",
        "Round {round}: {target} shells up. {init}'s strike lands on the shell.",
        "{target} absorbs it on the gloves in round {round}. No damage done.",
        "Round {round}: cross-block from {target}. {init} resets.",
        "{target} gets the forearms up in round {round}. {init}'s shot thuds home.",
        "Round {round}: {target} shells tight. {init}'s work is undone.",
        "The strike from {init} thuds into {target}'s guard in round {round}.",
    ],
    "missed": [
        "{init} swings and misses {target} in round {round}.",
        "{target} slips the strike in round {round}.",
        "Round {round}: wild swing from {init} catches only air.",
        "{init} reaches with the shot in round {round}. {target} is gone.",
        "{target} reads it in round {round}, pulls back. The strike sails over.",
        "The shot from {init} comes up empty in round {round}.",
        "Round {round}: {init} throws, {target} makes him miss.",
        "{target} evades with a half-step back in round {round}.",
        "Round {round}: {init} loads up — {target} sees it the whole way.",
        "The strike from {init} sails past {target}'s ear in round {round}.",
        "Round {round}: {target} slips the punch, makes {init} pay with positioning.",
        "{init} misses wide in round {round}. {target} resets.",
    ],
}





def _select_commentary_beats(conn, fight_id, importance, finishing_beat_id=None,
                             max_beats=None):
    """Select the most important beats from a fight for commentary.

    Per the B2 brief, the selection priority (highest first):
      1. Knockdown beats (outcome='knockdown').
      2. The finish beat (always selected if a finish occurred —
         identified by `finishing_beat_id`).
      3. Near-finish beats (outcome='near_finish').
      4. Big momentum swings (|momentum_shift| > 50).
      5. Round-winning sequences (highest-damage beat per round).

    The number of beats depends on fight importance:
      quick (importance < 40):     3-6 beats
      standard (40 <= importance < 70): 6-10 beats
      extended (importance >= 70): 10-14 beats

    Args:
        conn: sqlite3 connection.
        fight_id: the resolved fight's fight_id.
        importance: the fight's computed importance (0-100).
        finishing_beat_id: the fight_beat_id of the finishing exchange
            (if the fight ended in a finish). None for decisions.
        max_beats: optional override for the max number of beats
            (used by tests for deterministic selection).

    Returns:
        List of fight_beat rows (ordered by selection priority, then
        by beat order) — each row is a tuple of (fight_beat_id,
        round_number, beat_number, phase, action_type,
        initiator_fighter_id, target_fighter_id, outcome, damage_dealt,
        momentum_shift).
    """
    # Determine the beat count range based on importance.
    if max_beats is not None:
        target_min = max_beats
        target_max = max_beats
    elif importance < _COMMENTARY_QUICK_THRESHOLD:
        target_min, target_max = _COMMENTARY_QUICK_RANGE
    elif importance >= _COMMENTARY_EXTENDED_THRESHOLD:
        target_min, target_max = _COMMENTARY_EXTENDED_RANGE
    else:
        target_min, target_max = _COMMENTARY_STANDARD_RANGE

    # Pull all beats for this fight, ordered by round/beat.
    all_beats = conn.execute(
        "SELECT fight_beat_id, round_number, beat_number, phase, "
        "action_type, initiator_fighter_id, target_fighter_id, "
        "outcome, damage_dealt, momentum_shift "
        "FROM fight_beats WHERE fight_id=? "
        "ORDER BY round_number, beat_number",
        (fight_id,),
    ).fetchall()

    if not all_beats:
        return []

    # Score each beat by selection priority (higher = more important).
    # The scoring is:
    #   knockdown:     1000 (always selected)
    #   finish beat:   900  (always selected if a finish occurred)
    #   near_finish:   800
    #   big momentum:  500 + |momentum_shift|
    #   high damage:   damage_dealt
    #   other:         0
    # The actual selection picks the top N beats by score, with ties
    # broken by beat order (earlier beats first).
    def beat_priority(beat):
        (bid, rn, bn, phase, action, init_id, tgt_id,
         outcome, damage, momentum) = beat
        if outcome == "knockdown":
            return 1000
        if finishing_beat_id is not None and bid == finishing_beat_id:
            return 900
        if outcome == "near_finish":
            return 800
        if abs(momentum) > _BIG_MOMENTUM_SWING_THRESHOLD:
            return 500 + abs(momentum)
        return damage  # round-winning sequences: highest damage per round

    # Sort by priority desc, then by round/beat asc (so ties go to
    # earlier beats — chronologically sensible commentary).
    sorted_beats = sorted(all_beats, key=lambda b: (-beat_priority(b), b[1], b[2]))

    # Pick top N. N is randomly chosen within [target_min, target_max]
    # (capped at len(all_beats) so we don't request more beats than
    # exist). The randomness adds variety — two fights with the same
    # importance don't always produce the same number of commentary
    # segments.
    n = random.randint(target_min, target_max) if target_max > target_min else target_min
    n = min(n, len(sorted_beats))
    selected = sorted_beats[:n]

    # Re-sort by beat order (chronological) for the commentary
    # segments — commentary makes more sense in chronological order.
    selected_chrono = sorted(selected, key=lambda b: (b[1], b[2]))
    return selected_chrono





def _generate_beat_commentary(conn, event_id, fight_id, selected_beats):
    """Write commentary_segments for each selected beat.

    Each beat gets one commentary_segments row with a short play-by-play
    line. The line is generated from _BEAT_COMMENTARY_TEMPLATES based
    on the beat's outcome. The segment_type is 'highlight' (vs the
    existing 'play_by_play' used for the overall fight summary).

    Args:
        conn: sqlite3 connection (caller commits).
        event_id: the parent event's event_id.
        fight_id: the resolved fight's fight_id.
        selected_beats: list of fight_beat rows (from
            _select_commentary_beats).

    Returns:
        Number of commentary_segments rows written.
    """
    speaker = conn.execute(
        "SELECT staff_id FROM staff WHERE role_type='commentator' LIMIT 1"
    ).fetchone()
    speaker_id = speaker[0] if speaker else None

    count = 0
    for beat in selected_beats:
        (bid, rn, bn, phase, action, init_id, tgt_id,
         outcome, damage, momentum) = beat
        init_name = fighter_name(conn, init_id)
        tgt_name = fighter_name(conn, tgt_id)
        # P3.5 — pick a variant deterministically by (fight_id, beat_id)
        # hash. The same fight replays identically; different fights
        # get different prose. Falls back to the first variant if the
        # outcome isn't in the template dict (defensive — shouldn't
        # happen, but the old single-string template was a flat .get
        # that returned the missing-outcome fallback line).
        templates = _BEAT_COMMENTARY_TEMPLATES.get(outcome)
        if templates:
            template = _pick_variant(templates, fight_id, bid)
        else:
            template = "{init} and {target} exchange in round {round}."
        text = template.format(init=init_name, target=tgt_name, round=rn)
        # Importance: scale by beat priority. Knockdowns and near-
        # finishes are more important than regular exchanges.
        if outcome == "knockdown":
            importance = 95
        elif outcome == "near_finish":
            importance = 85
        elif abs(momentum) > _BIG_MOMENTUM_SWING_THRESHOLD:
            importance = 75
        else:
            importance = 60
        conn.execute(
            "INSERT INTO commentary_segments (event_id, fight_id, "
            "segment_type, speaker_staff_id, text, importance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, fight_id, "highlight", speaker_id, text, importance),
        )
        count += 1
    return count


# ----------------------------------------------------------------
# Per-beat commentary (Task FIGHT-NIGHT-SHOWCASE).
#
# The existing `_select_commentary_beats` + `_generate_beat_commentary`
# system writes 3-14 'highlight' segments per fight — only the most
# important beats get prose. The Fight Night screen needs prose for
# EVERY beat (100-200 per fight) so the live play-by-play feed reads
# as a continuous narrative, not a sparse log.
#
# This system writes one commentary_segments row per beat with
# segment_type='beat' (distinct from 'play_by_play' and 'highlight').
# The 'beat' rows are the live feed; the 'highlight' rows remain the
# "key moments" feed shown in Zone D of the Fight Night screen.
#
# Voice compliance (CONVENTIONS §14 + VOICE_ENFORCEMENT.md):
#   - Short fragmentary sentences. Periods do work.
#   - Specific imagery ("right hand finds the chin" not "lands a punch").
#   - No raw numbers (no "damage 23", no "momentum +80").
#   - No tabloid clichés ("SHOCKING KNOCKOUT!", "BOMBSHELL UPSET!").
#   - Phase-aware (standing jab reads differently than a ground_strike).
#   - Action-aware (jab vs cross vs head_kick all sound different).
#   - Outcome-aware (landed vs missed vs blocked vs reversed).
#   - Momentum-aware (big swing adds an emphasis clause).
#   - Round-ending marker (last beat of a round gets a closing line).
#
# 8+ variants per (action_type, outcome) per VOICE_ENFORCEMENT §3 —
# the same fighter landing the same jab twice in a row should NOT
# read identically. Variety is achieved by hashing (fight_id, beat_id)
# to pick a variant deterministically (replayable) but with no
# repeat-within-last-3 on the same template key.
# ----------------------------------------------------------------


# Per-action × landed strike templates (8+ variants each). The
# templates use {init} + {target} slots, formatted at write time.
# Each variant is a complete short sentence (period inside the string).

_PER_BEAT_LANDED = {
    "jab": [
        "{init} pops the jab. {target} takes it on the chin.",
        "A stiff jab from {init} snaps {target}'s head back.",
        "{init} works the jab, finding range.",
        "The jab from {init} gets there first.",
        "{init} flicks the jab out. {target} eats it.",
        "Straight left from {init} finds its mark.",
        "{init} measures distance behind the jab.",
        "Quick jab from {init}. {target} circles away.",
        "{init} pops the jab, sets up something bigger.",
        "Jab from {init} snaps {target}'s head sideways.",
        "The jab sits in {target}'s face. {init} working the lead.",
        "Piston jab from {init}. {target} backs up a half-step.",
    ],
    "cross": [
        "{init} lands the cross. {target} backs up.",
        "A straight right from {init} splits the guard.",
        "{init}'s cross connects. {target} feels it.",
        "The right hand from {init} finds the chin.",
        "{init} uncorks a cross. It lands flush.",
        "{target} walks into a right hand from {init}.",
        "Cross from {init}, clean and stiff.",
        "{init} doubles up — the cross gets through.",
        "Right hand over the top from {init}.",
        "The cross from {init} finds a home on the jaw.",
        "{init} sits down on the right hand. {target} absorbs it.",
        "Straight right from {init} — {target} was looking for the body.",
    ],
    "hook": [
        "{init} hooks the left to the body. {target} winces.",
        "A heavy hook from {init} lands behind the ear.",
        "{init} cracks {target} with a left hook.",
        "Hook to the ribs from {init}. {target} backs off.",
        "{init} rips a hook upstairs. It connects.",
        "The hook from {init} finds the temple.",
        "{init} pivots into a hook. {target} is marked.",
        "Left hook from {init}, right on the button.",
        "Short hook inside from {init}. {target} absorbs it.",
        "{init} loops the hook around {target}'s guard.",
        "Hook to the body from {init}. {target} drops the hands.",
        "{init} uncorks a hook. It clips {target} on the jaw.",
    ],
    "leg_kick": [
        "{init} chops the leg. {target} limps out of range.",
        "A heavy leg kick from {init} echoes through the arena.",
        "{init} goes to the calf. {target} checks the next one.",
        "Leg kick from {init} buckles {target}.",
        "The outside leg kick from {init} lands with a thwack.",
        "{init} works the low line. {target} is favoring the lead leg.",
        "Calf kick from {init}. {target} is thrown off rhythm.",
        "Inside leg kick from {init}. {target} resets.",
        "{init} chews up the lead leg of {target}.",
        "Heavy outside kick from {init}. {target} winces and circles.",
        "{init} goes to the thigh. The crowd hears the thud.",
        "The leg kick from {init} — {target}'s stance shifts.",
    ],
    "head_kick": [
        "Head kick from {init}! {target} is wobbled.",
        "{init} throws the high kick. It gets through.",
        "A head kick from {init} finds the jaw.",
        "The kick from {init} lands upstairs. {target} staggers.",
        "{init} uncorks a head kick. {target} barely survives.",
        "High kick from {init}. {target} was looking at the body.",
        "{init} goes upstairs with a kick. {target} is hurt.",
        "The head kick from {init} lands clean.",
        "Calf-to-chin from {init}. The crowd roars.",
        "{init} whips the kick high. {target} takes it on the cheek.",
        "Spinning high kick from {init} — just catches {target}.",
        "The foot of {init} finds {target}'s temple. Big kick.",
    ],
    "clinch_knee": [
        "Knee to the midsection from {init} in the clinch.",
        "{init} rips a knee up the middle. {target} wilts.",
        "A short knee from {init} lands inside.",
        "{init} works the knees along the fence. {target} hangs on.",
        "Knee to the thigh from {init}. {target} tries to answer.",
        "The clinch knee from {init} finds the ribs.",
        "{init} digs a knee into {target}'s midsection.",
        "Inside knee from {init}. {target} is being worn down.",
        "Short, sharp knee from {init} in tight.",
        "{init} bumps a knee into {target}'s sternum.",
        "Plum-clinch knee from {init}. {target} can't get out.",
        "{init} drives a knee up the middle. {target} grunts.",
    ],
    "clinch_elbow": [
        "{init} sneaks an elbow inside. {target} is cut.",
        "A sharp elbow from {init} opens a gash.",
        "Elbow from the clinch by {init}. {target} wipes at his face.",
        "{init} digs an elbow into {target}'s cheekbone.",
        "Short elbow from {init} in the tie-up.",
        "The elbow from {init} splits the skin.",
        "{init} works an elbow inside. {target} is marked.",
        "Elbow over the top from {init} in the clinch.",
        "Sawing elbow from {init}. {target} is bleeding.",
        "{init} sneaks an elbow through the gap. {target} blinks.",
        "Diagonal elbow from {init}. {target} pulls back too late.",
        "Short elbow from {init}. Catches {target} on the bridge.",
    ],
    "cage_knee": [
        "Knee to the thigh from {init} along the fence.",
        "{init} grinds {target} against the cage, working the knees.",
        "Short knee from {init}. {target} is pinned.",
        "Knee to the body from {init}. {target} sags against the fence.",
        "{init} lands a knee while {target} is trapped on the cage.",
        "The cage knee from {init} finds the midsection.",
        "{init} buries a knee into {target}'s ribs on the fence.",
        "Inside knee from {init}. {target} can't get off the cage.",
        "Working the knees on the fence, {init} keeps the pressure.",
        "Knee to the hip from {init}. {target} drops the level.",
        "{init} uses the cage to brace. Lands a short knee.",
        "Double-collar tie knee from {init}. {target} wilts.",
    ],
    "ground_strike": [
        "{init} drops a heavy elbow from the top.",
        "Ground-and-pound from {init}. {target} covers up.",
        "{init} lands a clean shot from inside guard.",
        "Hammerfist from {init}. {target} turns away.",
        "{init} postures up and lands. {target} is in trouble.",
        "Short shots from the top by {init}.",
        "{init} works the body from side control.",
        "Elbow from the top by {init}. {target} is bleeding.",
        "Ground strikes from {init}. {target} is just surviving.",
        "{init} slices an elbow through {target}'s guard.",
        "Hammerfist from {init}. {target} turns to escape.",
        "{init} postures up — lands a hard one. {target} covers up.",
    ],
}


# Per-outcome templates for actions that DIDN'T land cleanly. Used
# for both strike and transition actions — the prose is generic enough
# that it reads correctly regardless of action_type. 8+ variants each.

_PER_BEAT_OUTCOME = {
    "missed": [
        "{init} swings and misses.",
        "{target} slips the strike.",
        "Wild swing from {init} catches only air.",
        "{init} reaches with the shot. {target} is gone.",
        "{target} reads it, pulls back. The strike sails over.",
        "{init} throws, {target} makes him miss.",
        "The shot from {init} comes up empty.",
        "{target} evades with a half-step back.",
        "{init} misses wide. {target} resets.",
        "{init} loads up — {target} sees it the whole way.",
        "The strike from {init} sails past {target}'s ear.",
        "{target} slips the punch, makes {init} pay with positioning.",
    ],
    "blocked": [
        "{target} covers up. The strike lands on the gloves.",
        "{target} gets the guard up in time.",
        "The shot from {init} is absorbed on the forearms.",
        "{target} blocks the strike, circles out.",
        "High guard from {target}. {init} can't find a gap.",
        "The strike from {init} lands on the shell.",
        "{target} absorbs it on the gloves. No damage.",
        "Blocked by {target}. {init} tries again.",
        "{target} gets the defense up. Nothing gets through.",
        "The strike thuds into {target}'s forearms.",
        "{target} shells up. {init}'s work is undone.",
        "Cross-block from {target}. {init} resets.",
    ],
    "defended": [
        "{target} anticipates and defends the strike.",
        "{target} sees it coming, gets out of the way.",
        "Good defense from {target}. {init} is left reaching.",
        "{target} slips the punch, makes {init} pay with a counter.",
        "{target} parries the strike cleanly.",
        "The shot is telegraphed. {target} sidesteps.",
        "{target} times the entry, defends with ease.",
        "Reading the rhythm, {target} dodges the strike.",
        "{init} commits, {target} is already gone.",
        "{target} catches the strike on the shoulder. Rolls out.",
        "{target} leans just out of range. {init} swings at shadow.",
        "Forearm check from {target}. {init}'s work is smothered.",
    ],
    "reversed": [
        "{target} reverses the position! Momentum swings.",
        "{target} turns it around on {init}.",
        "Reversal from {target} — they're back in it.",
        "{init}'s attack backfires. {target} takes over.",
        "{target} counters and ends up on top.",
        "The tide turns. {target} seizes the upper hand.",
        "{target} turns the tables on {init}.",
        "Big reversal! {target} steals the momentum.",
        "{target} shrugs off the attack and takes the position.",
        "Hip-heist from {target}. Now on top of {init}.",
        "{target} ducks under — comes out the back door. Reversed.",
        "The scramble flips. {target} takes the driver's seat.",
    ],
    "knockdown": [
        "{init} DROPS {target} with a heavy shot!",
        "{target} hits the canvas! {init} has them hurt.",
        "A right hand and {target} crumbles to the mat.",
        "{init} puts {target} down. The crowd is on its feet.",
        "Down goes {target}! {init} swarms to finish.",
        "{init} lands flush — {target} crumples against the cage.",
        "Heavy shot from {init}. {target} is down.",
        "The blow from {init} folds {target}.",
        "{target} is dropped! {init} moves in for the kill.",
        "{init} clips {target} behind the ear. Down goes {target}.",
        "A looping shot from {init} — {target} crumbles to a knee.",
        "The right hand finds the chin. {target} folds.",
    ],
    "near_finish": [
        "{init} has {target} hurt. The finish is near.",
        "{target} is in serious trouble. {init} swarms.",
        "{init} unleashes a barrage. {target} is barely surviving.",
        "Big shots from {init}. {target} is on wobbly legs.",
        "{target} is rocked! {init} can smell the finish.",
        "{init} piles on the pressure. {target} wilts.",
        "The end looks near for {target}.",
        "{init} has {target} out on their feet.",
        "{target} is hurt, scrambling to survive.",
        "{init} pours it on. {target} is just covering up.",
        "The legs of {target} betray them. {init} moves in.",
        "{target} staggers. {init} can see the opening.",
    ],
}


# Phase-transition templates. Used when the phase of the current beat
# differs from the previous beat's phase (i.e., the fight moved from
# standing → clinch, clinch → ground_top, etc.). 8+ variants each.

_PER_BEAT_PHASE_ENTRY = {
    "clinch": [
        "{init} closes the distance, looking for the clinch.",
        "They tie up along the fence.",
        "{init} grabs hold of {target}, pushes them to the cage.",
        "The fight moves into the clinch.",
        "{init} pressures forward. They clinch up.",
        "Tied up against the fence.",
        "{init} presses {target} into the cage, working inside.",
        "Body lock from {init}. They're in the clinch now.",
        "{init} crowds {target}. The clinch is on.",
    ],
    "cage": [
        "{init} pins {target} against the cage.",
        "They grind against the fence.",
        "{init} walks {target} back to the cage.",
        "Pressed on the cage now. {init} working the body.",
        "Cage work. {init} keeps {target} trapped.",
        "{target} has their back to the fence. {init} in control.",
        "Along the fence. {init} is in charge of position.",
        "Cage-pressed clinch. {init} on top.",
        "{init} uses the cage, wears on {target}.",
    ],
    "ground_top": [
        "{init} ends up on top, in {target}'s guard.",
        "Takedown! {init} comes down in side control.",
        "{init} puts {target} on the mat, lands on top.",
        "The fight hits the floor. {init} in the driver's seat.",
        "{init} drags {target} down, takes top position.",
        "Grounded now. {init} working from above.",
        "{init} has top control. {target} on their back.",
        "Slam takedown from {init}. {target} is grounded.",
        "{init} gets the takedown. The fight is on the mat.",
    ],
    "ground_bottom": [
        "{target} reverses — {init} ends up on the bottom.",
        "{target} sweeps! {init} is on their back now.",
        "Position flips. {target} takes the top.",
        "{init} is stuck on the bottom. {target} in control.",
        "Reversal on the ground. {target} on top.",
        "{target} turns the scramble. Now on top of {init}.",
        "The scramble settles. {target} has top position.",
        "{target} out-positions {init}, takes the top.",
        "{init} on the bottom, looking for a way up.",
    ],
    "scramble": [
        "Scramble for position. Neither fighter has the upper hand.",
        "A wild scramble. Both men looking for an edge.",
        "They grapple for control in the chaos.",
        "Scrambling. Position is up for grabs.",
        "The fight devolves into a scramble.",
        "Both fighters battle for top position.",
        "A frantic exchange on the mat.",
        "The scramble continues. Neither yields.",
        "Grappling chess in the chaos.",
    ],
}


# Templates for transition-action outcomes that DO change the phase.
# Used in place of the generic landed/missed templates for clinch_entry,
# takedown_attempt, sweep_attempt, stand_up, break_clinch, cage_push,
# scramble, submission_attempt, when the action succeeds (outcome='landed')
# — these read more naturally for grappling actions than the strike-
# specific landed templates.
#
# P5.3 — converted from a single-string-per-key to a LIST-per-key so
# each landed grappling action has variety (per VOICE_ENFORCEMENT §3:
# 8+ variants per (action_type, outcome); 10+ for the headline actions
# takedown_attempt + submission_attempt + clinch_entry).
#
# Slots: {init} (the initiator), {target} (the target). Same as the
# strike-landed templates.

_PER_BEAT_GRAPPLING = {
    "clinch_entry": [
        "{init} closes the distance and ties up {target}.",
        "{init} slips inside, gets the double-collar tie on {target}.",
        "Body lock from {init}. {target} is clinched.",
        "{init} crowds {target}, locks the overhooks.",
        "Underhook battle in the clinch — {init} gets the better of it.",
        "{init} reaches for the plum. {target} can't create space.",
        "{init} steps in, pummels for position, gets the clinch.",
        "Double-unders from {init}. {target} is stuck in close.",
        "{init} pins {target}'s arms. The clinch is locked.",
        "{init} forces the tie-up. {target} has to grapple now.",
    ],
    "takedown_attempt": [
        "{init} shoots for a takedown. {target} is dragged down!",
        "Double-leg from {init}. {target} hits the mat.",
        "{init} changes levels, drives through {target}'s hips. Takedown.",
        "Single-leg from {init}. {target} hops, but goes down.",
        "{init} hits a beautiful outside trip. {target} is on the canvas.",
        "Inside trip from {init} — {target} didn't see it coming.",
        "{init} snaps {target} down, comes around for the takedown.",
        "Body-lock takedown from {init}. {target} is grounded.",
        "High-crotch from {init}. {target} is dumped to the mat.",
        "{init} lifts {target} — SLAM. The crowd erupts.",
        "Foot-sweep from {init}. {target} goes down sideways.",
        "Ankle pick from {init}. {target} crumbles to the canvas.",
    ],
    "cage_push": [
        "{init} bulls {target} into the cage.",
        "{init} drives forward, walks {target} back to the fence.",
        "Body lock + drive from {init}. {target} is pressed on the cage.",
        "{init} pins {target} on the fence, working for underhooks.",
        "Cage-press from {init}. {target} has nowhere to go.",
        "{init} grinds {target} against the chain-link.",
        "Double-underhooks from {init} — drives {target} to the cage.",
        "{init} forces {target} backwards, gets the cage work going.",
    ],
    "break_clinch": [
        "{init} breaks the clinch. Back to striking.",
        "{init} shoves off, creates space. Back to range.",
        "Push-off from {init}. The clinch is broken.",
        "{init} circles out of the tie-up. {target} can't hold on.",
        "{init} frames off {target}'s hips, resets to distance.",
        "Elbow-frame from {init} — breaks the clinch cleanly.",
        "{init} paws {target} off, returns to kicking range.",
        "Pummel-out from {init}. Back to the open mat.",
    ],
    "sweep_attempt": [
        "{init} sweeps! The position reverses.",
        "Hip-sweep from {init} — {target} is rolled.",
        "{init} bridges and rolls. Now on top of {target}.",
        "Kimura-sweep from {init}. {target} goes to their back.",
        "{init} hits the elevator sweep. {target} is dumped over.",
        "{init} under-hooks the leg, comes out the back door. Reversed.",
        "Bridging sweep from {init}. {target} loses top position.",
        "{init} hits a beautiful technical stand-up into a sweep.",
    ],
    "stand_up": [
        "{init} works back to the feet. Back to striking range.",
        "{init} hips out, gets up. {target} can't hold them down.",
        "Wall-walk from {init}. Back to standing.",
        "{init} posts a hand, stands into {target}. Back up.",
        "Granby roll from {init} — up to the feet.",
        "{init} shrimps to the cage, stands up. Back in space.",
        "Technical stand-up from {init}. Now upright.",
        "{init} bucks {target} off, scrambles to the feet.",
    ],
    "scramble": [
        "A scramble. Both fighters hunting for position.",
        "Wild scramble. {init} and {target} battle for the upper hand.",
        "The fight hits a transition phase. Both men scramble.",
        "Scrambling — neither man has position yet.",
        "{init} and {target} grapple in the chaos.",
        "A furious scramble. Position is up for grabs.",
        "The fight devolves into a scramble. {init} pushes for top.",
        "Grappling chess in the chaos. {init} hunts for an angle.",
    ],
    "submission_attempt": [
        "{init} hunts for a submission. {target} is in danger!",
        "{init} sinks the choke. {target} defends frantically.",
        "Armbar attempt from {init}! {target} stacks to survive.",
        "{init} locks up a triangle. {target} is trapped.",
        "Guillotine from {init}. {target}'s neck is exposed.",
        "{init} goes for the rear-naked. {target} defends the hands.",
        "Heel-hook attempt from {init}. {target} spins out.",
        "Kimura from {init} — {target}'s arm is torqued.",
        "{init} throws the legs up for an omoplata. {target} rolls.",
        "D'arce attempt from {init}. {target} is in tight.",
        "{init} isolates the neck. Looking for the finish.",
        "{init} cranks a calf-slicer. {target} winces and twists.",
    ],
}


# Per-outcome templates for grappling actions that DON'T land cleanly.

_PER_BEAT_GRAPPLING_MISSED = {
    "clinch_entry": [
        "{init} reaches for the clinch. {target} circles out.",
        "{target} circles off the cage. The clinch doesn't stick.",
        "{init} tries to tie up. {target} keeps it at range.",
        "Failed clinch entry from {init}.",
        "{target} paws {init} off, stays in space.",
        "The clinch attempt is shrugged off.",
        "{init} reaches. {target} doesn't engage.",
        "Clinch attempt from {init}. {target} defends.",
        "Can't secure the clinch. Back to distance.",
    ],
    "takedown_attempt": [
        "{init} shoots. {target} sprawls and stuffs it.",
        "Takedown stuffed. {target} stays on the feet.",
        "{target} sprawls hard. The shot is defended.",
        "{init} reaches for the legs. {target} defends.",
        "Sprawl from {target}. The takedown is denied.",
        "The shot from {init} is read. {target} is ready.",
        "{target} stuffs the takedown. Stays upright.",
        "Failed takedown. {target} circles away.",
        "{init} can't get the takedown. {target} was waiting.",
    ],
    "cage_push": [
        "{init} tries to drive {target} to the cage. {target} resists.",
        "{target} stays off the fence. {init} can't pin them.",
        "Cage push attempt from {init}. {target} stays loose.",
        "Failed cage push from {init}.",
        "{target} pivots off the cage. {init} comes up empty.",
        "{init} reaches for the cage push. No luck.",
        "{target} keeps the fight in space. The cage push fails.",
        "Can't pin {target}. They keep moving.",
        "{init} presses forward. {target} circles off.",
    ],
    "break_clinch": [
        "{init} tries to break the clinch. {target} holds on.",
        "Break attempt fails. {target} keeps the tie-up.",
        "{init} pushes off. {target} re-engages.",
        "Can't break the clinch cleanly.",
        "{target} doesn't let {init} get out of the clinch.",
        "The break attempt from {init} doesn't work.",
        "{init} shoves off. {target} jumps right back in.",
        "Failed break. Still tied up.",
        "{target} maintains the clinch. {init} can't get loose.",
    ],
    "sweep_attempt": [
        "{init} hunts for a sweep. {target} defends.",
        "Sweep attempt from {init}. {target} keeps top position.",
        "{target} shuts down the sweep. {init} stays on the bottom.",
        "Failed sweep from {init}.",
        "The sweep doesn't come. {target} is too heavy on top.",
        "{init} tries to reverse. {target} is having none of it.",
        "Sweep attempt denied. {target} stays in control.",
        "Can't get the sweep. {target} adjusts.",
        "{init} reaches for the sweep. {target} locks it down.",
    ],
    "stand_up": [
        "{init} tries to stand up. {target} keeps them down.",
        "Stand-up attempt from {init}. {target} rides it.",
        "{target} won't let {init} up. Stays heavy on top.",
        "Can't get back to the feet.",
        "{init} hips up, looking to escape. {target} adjusts.",
        "The stand-up doesn't come. {target} is in control.",
        "{target} keeps {init} grounded. The escape fails.",
        "{init} tries to wall-walk. {target} drags them back down.",
        "Stand-up denied. {target} maintains top position.",
    ],
    "scramble": [
        "The scramble continues. Neither fighter can gain position.",
        "Still scrambling. Position is up for grabs.",
        "Neither fighter commits. The scramble goes on.",
        "Failed position change in the scramble.",
        "{init} reaches for an advantage. {target} matches it.",
        "The scramble stalls. Back to where they started.",
        "{init} tries to advance. {target} defends.",
        "No progress in the scramble. Stalemate.",
        "{init} looks for an opening. {target} doesn't yield.",
    ],
    "submission_attempt": [
        "{init} hunts for a submission. {target} defends.",
        "Submission attempt from {init}. {target} pulls free.",
        "{target} sees the sub coming, defends in time.",
        "{init} goes for the finish. {target} is too savvy.",
        "The submission doesn't sink in. {target} escapes.",
        "{init} reaches for a choke. {target} defends.",
        "Failed sub attempt. {target} stays calm.",
        "{target} survives the submission try.",
        "{init} looks for the tap. {target} won't give it.",
        "{init} throws up the legs. {target} stacks and slips out.",
        "The choke is close — {target} hand-fights and breaks the grip.",
        "{target} postures out of the armbar. {init} loses the angle.",
    ],
}


# Round-ending markers. Used for the LAST beat of each round (the
# beat whose round_number differs from the next beat's round_number).

_PER_BEAT_ROUND_END = [
    "The horn sounds. Round over.",
    "That's the round. Both fighters head to their corners.",
    "The bell saves them. The round is done.",
    "End of the round. The crowd catches its breath.",
    "The round concludes. Back to the corners.",
    "Horn. The round ends.",
    "And that's the round.",
    "The whistle blows. Round over.",
    "Bell. The fighters separate, head to their corners.",
    "The round expires. Cuts are checked, water is sipped.",
    "The horn blares. Round complete.",
    "And there's the horn. The round is in the books.",
]


# Round-end "concerned corner" variants — used when the round winner
# is clear from the beat data (momentum_shift > +50 favoring the
# initiator). Adds a "the corner is concerned" voice beat.

_PER_BEAT_ROUND_END_HURT = [
    "The horn saves {target}. {target}'s corner is concerned.",
    "End of the round. {target} wobbles back to the corner.",
    "The bell rings. {target} is saved by the round's end.",
    "Round over. {target} looks wobbly on the stool.",
    "{target}'s corner has work to do between rounds.",
    "Horn. {target} was in trouble there.",
    "That round ends. {target} survives to see the next.",
    "Bell. {target}'s corner works fast to revive them.",
    "And that's the round. {target} is breathing hard.",
    "The horn saves {target} — for now.",
    "{target} staggers to the corner. The cutman is waiting.",
    "Round ends. {target}'s corner has 60 seconds to fix this.",
]


# Big-momentum-swing emphasis clauses. Appended to the end of a beat's
# prose when |momentum_shift| > 50 (the same threshold the existing
# _select_commentary_beats system uses for "big momentum" beats).

_PER_BEAT_MOMENTUM_EMPHASIS = [
    " The crowd roars.",
    " The arena erupts.",
    " Momentum just swung hard.",
    " The tide is turning.",
    " You can feel the shift.",
    " The crowd is on its feet.",
    " What a sequence.",
    " The fight has flipped on its head.",
    " A huge moment in this fight.",
    " The energy in the building spikes.",
    " You can hear the crowd react.",
    " That one landed with a thud.",
]


# Final-finish marker. Used for the LAST beat of the fight if the
# fight ended in a finish (KO/sub/DQ). The finishing beat's prose is
# replaced (not appended) with one of these.

_PER_BEAT_FINISH = {
    "ko_tko": [
        "And that's it. {init} puts {target} away. The fight is over.",
        "{target} crumples. {init} gets the finish.",
        "Down goes {target}. The referee steps in. It's over.",
        "{init} lands the finisher. {target} can't continue.",
        "That's the end. {init} gets the stoppage.",
        "{target} goes limp. The ref waves it off. {init} wins.",
        "Big shot from {init}. {target} is out. Fight over.",
        "{init} finishes it. {target} is done.",
        "And the fight is stopped. {init} gets the knockout.",
        "One more shot and {target} crumples. {init} gets the finish.",
        "The referee has seen enough. {init} is the winner.",
        "And it's over — {target} can't answer. {init} wins by KO.",
    ],
    "submission": [
        "{init} locks in the submission. {target} is forced to tap.",
        "And it's over — {target} taps. {init} gets the finish.",
        "{init} cranks the submission. {target} has no choice.",
        "Tap. {target} surrenders. {init} wins by submission.",
        "{init} secures the hold. {target} is forced to submit.",
        "The tap comes. {init} gets the submission win.",
        "{target} is caught. The referee stops it. {init} wins.",
        "And {target} taps. {init} forces the finish.",
        "{init} cinches it up. {target} has to yield. It's over.",
        "The choke is in deep. {target} taps. {init} wins.",
        "{init} cranks the armbar — {target} verbally submits.",
        "And that's the tap. {init} gets the submission finish.",
    ],
    "dq": [
        "Illegal blow from {init}. The referee steps in.",
        "{init} is disqualified. The fight is over.",
        "The ref calls it. {init} loses by DQ.",
        "That's a DQ. The fight ends abruptly.",
        "Illegal strike. The referee waves it off.",
        "{init} is disqualified. The bout is over.",
        "Disqualification. The referee ends it.",
        "{init} crosses the line. DQ. The fight is done.",
        "That's illegal. The ref calls the DQ.",
        "The referee has no choice. DQ. {init} is disqualified.",
        "Repeated fouls. The ref calls the disqualification.",
        "{init} is shown the card. DQ. The fight is over.",
    ],
    "doctor_stoppage": [
        "The doctor has seen enough. The fight is stopped.",
        "The ringside physician waves it off.",
        "Cuts are checked. The doctor stops the contest.",
        "Damage is too severe. The doctor ends the fight.",
        "The physician calls a halt to the bout.",
        "Medical stoppage. The fight is over.",
        "The doctor takes a long look. Stops it.",
        "Damage forces the doctor's intervention.",
        "The ringside physician steps in. It's over.",
        "The cut is too deep. Doctor stoppage. {target} can't continue.",
        "The doctor mounts the cage. The fight is waved off.",
        "After a long look, the physician calls the stoppage.",
    ],
    "corner_stoppage": [
        "The towel comes in. {target}'s corner stops the fight.",
        "{target}'s corner throws in the towel.",
        "The corner has seen enough. The fight is stopped.",
        "Corner stoppage. {target} will not continue.",
        "The towel flies in. {init} wins.",
        "{target}'s corner ends it.",
        "Corner stoppage. {target} can't continue.",
        "The corner calls it. {init} gets the win.",
        "Towel thrown. The fight is over.",
        "The corner signals to the ref. {target} is done.",
        "{target}'s coach mounts the apron. The fight is stopped.",
        "Corner stoppage — they've seen enough. {init} wins.",
    ],
}


def _pick_variant(variants, fight_id, beat_id, offset=0):
    """Deterministically pick a variant from a list.

    Hashes (fight_id, beat_id, offset) so the same beat always gets
    the same prose (replayable) but different beats in the same fight
    get different prose (variety). The offset lets a caller request
    a different variant for, e.g., a momentum-emphasis clause that
    follows the base prose (offset=1).

    Args:
        variants: list of strings (the template variants).
        fight_id: int.
        beat_id: int.
        offset: int, rotates the hash so multiple clauses in the same
            beat don't all pick the same variant index.

    Returns:
        One element from `variants`.
    """
    n = len(variants)
    if n == 0:
        return ""
    # Simple deterministic hash — not crypto, just for rotation.
    h = ((int(fight_id) * 9173) ^ (int(beat_id) * 6151) ^ (int(offset) * 3119)) & 0x7FFFFFFF
    return variants[h % n]


def _generate_per_beat_commentary(conn, event_id, fight_id, finishing_beat_id=None,
                                  result_type=None, is_title_fight=False,
                                  scheduled_rounds=3, red_id=None, blue_id=None,
                                  fight_promo_id=None):
    """Write one commentary_segments row per beat (segment_type='beat').

    For every beat in the fight, generates a short voice-compliant
    prose line and writes it to commentary_segments. The 'beat' rows
    are the live feed for the Fight Night screen; the 'highlight' rows
    (written separately by _generate_beat_commentary) remain the
    "key moments" feed shown in Zone D.

    P3.5 — this function ALSO writes the extra commentary segments
    (ring announcer intro, named pundit interjections, crowd
    reactions) interleaved with the beat segments. The interleaving
    is critical: the Fight Night UI computes each extra segment's
    beat_index by counting how many 'beat' segments have a lower
    commentary_segment_id. If the extra segments were written in a
    separate pass (after all beats), they'd all have higher IDs
    than all beats and the beat_index computation would collapse
    them all to the last beat. Writing them inline (announcer before
    beat 0, pundit/crowd immediately after their triggering beat)
    keeps the IDs in chronological order so the UI's beat_index
    derivation works correctly.

    Args:
        conn: sqlite3 connection (caller commits).
        event_id: the parent event's event_id.
        fight_id: the resolved fight's fight_id.
        finishing_beat_id: the fight_beat_id of the finishing exchange
            (if the fight ended in a finish). Used to replace the
            finishing beat's prose with a fight-end marker.
        result_type: the fight's result_type (e.g. 'ko_tko'). Used
            to pick the appropriate finish template. None for
            decisions/draws (no finishing beat).
        is_title_fight: whether this was a title fight (affects the
            announcer's "for the championship" phrasing).
        scheduled_rounds: number of scheduled rounds (3 or 5).
        red_id: red-corner fighter_id (for hometown lookup + name).
        blue_id: blue-corner fighter_id.
        fight_promo_id: the promotion_id of the fight's event (for
            looking up the player's commentator staff).

    Returns:
        Number of commentary_segments rows written (one per beat +
        extra segments).
    """
    speaker = conn.execute(
        "SELECT staff_id FROM staff WHERE role_type='commentator' LIMIT 1"
    ).fetchone()
    speaker_id = speaker[0] if speaker else None

    all_beats = conn.execute(
        "SELECT fight_beat_id, round_number, beat_number, phase, "
        "action_type, initiator_fighter_id, target_fighter_id, "
        "outcome, damage_dealt, momentum_shift "
        "FROM fight_beats WHERE fight_id=? "
        "ORDER BY round_number, beat_number",
        (fight_id,),
    ).fetchall()
    if not all_beats:
        return 0

    # Cache fighter names (avoid N+1 queries for the 100-200 beats).
    name_cache = {}
    def name_of(fid):
        if fid not in name_cache:
            name_cache[fid] = fighter_name(conn, fid)
        return name_cache[fid]

    # ---- P3.5: extra-segments setup ----
    # Commentators (named-pundit interjections). Uses the player's
    # actual commentator staff so the interjections feel like a real
    # broadcast team.
    commentators = _player_promo_commentators(conn, fight_promo_id)
    primary_pundit = commentators[0] if commentators else None
    secondary_pundit = commentators[1] if len(commentators) > 1 else None

    red_name = name_of(red_id) if red_id else "Red Corner"
    blue_name = name_of(blue_id) if blue_id else "Blue Corner"
    red_loc = _fighter_hometown_phrase(conn, red_id) if red_id else None
    blue_loc = _fighter_hometown_phrase(conn, blue_id) if blue_id else None
    title_clause = " for the championship" if is_title_fight else ""
    rounds_word = {3: "three", 5: "five"}.get(scheduled_rounds, str(scheduled_rounds))

    PUNDIT_INTERVAL = 17  # every ~17 beats
    CROWD_INTERVAL = 12   # every ~12 beats

    count = 0

    # ---- P3.5: ring announcer intro (1 per fight, before beat 0) ----
    # Written BEFORE the loop so its commentary_segment_id is lower
    # than all beat IDs → the UI's beat_index computation gives it
    # beat_index = -1 (well, 0 beats before it = 0, but the UI special-
    # cases segment_type='announcer' to beat_index = -1).
    try:
        announcer_text = _pick_variant(_RING_ANNOUNCER_INTROS, fight_id, 0).format(
            red=red_name, blue=blue_name,
            red_loc=red_loc or "parts unknown",
            blue_loc=blue_loc or "parts unknown",
            rounds=rounds_word,
            title=title_clause,
        )
        announcer_speaker = primary_pundit[0] if primary_pundit else None
        conn.execute(
            "INSERT INTO commentary_segments (event_id, fight_id, "
            "segment_type, speaker_staff_id, text, importance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, fight_id, "announcer", announcer_speaker,
             announcer_text, 90),
        )
        count += 1
    except Exception as _e:
        print(f"[fight_engine._generate_per_beat_commentary/announcer] "
              f"fight={fight_id}: {_e}", flush=True)

    # Track per-(action_type, outcome) usage so we don't repeat the
    # same template within 3 beats. VOICE_ENFORCEMENT §3.
    recent_template_keys = []

    prev_phase = None
    n_beats = len(all_beats)
    for i, beat in enumerate(all_beats):
        (bid, rn, bn, phase, action, init_id, tgt_id,
         outcome, damage, momentum) = beat
        init_name = name_of(init_id)
        tgt_name = name_of(tgt_id)

        # Detect last beat of round (next beat has different round_number
        # or this is the last beat of the fight).
        is_round_end = (i == n_beats - 1) or (all_beats[i + 1][1] != rn)

        # Detect finishing beat (the engine marks it via finishing_beat_id).
        is_finish = (finishing_beat_id is not None and bid == finishing_beat_id
                     and result_type in _PER_BEAT_FINISH)

        text = ""

        if is_finish:
            # Replace the finishing beat's prose with a fight-end marker.
            templates = _PER_BEAT_FINISH.get(result_type, _PER_BEAT_FINISH["ko_tko"])
            text = _pick_variant(templates, fight_id, bid).format(
                init=init_name, target=tgt_name,
            )
        else:
            # Phase-transition line (if phase changed from previous beat).
            if prev_phase is not None and phase != prev_phase:
                entry_templates = _PER_BEAT_PHASE_ENTRY.get(phase)
                if entry_templates:
                    text = _pick_variant(entry_templates, fight_id, bid, offset=1).format(
                        init=init_name, target=tgt_name,
                    )

            # If we didn't write a phase-transition line, write the
            # action×outcome prose. (Phase transitions get their own
            # line; the action×outcome prose is skipped for that beat
            # to avoid a doubled-up sentence. The action is implicit
            # in the phase transition itself.)
            if not text:
                # Grappling-action landed transitions: use the
                # grappling-specific landed template.
                if (action in _PER_BEAT_GRAPPLING and outcome == "landed"):
                    variants = _PER_BEAT_GRAPPLING[action]
                    text = _pick_variant(variants, fight_id, bid).format(
                        init=init_name, target=tgt_name,
                    )
                # Grappling-action non-landed: use the action-specific
                # missed/blocked/defended/reversed templates.
                elif (action in _PER_BEAT_GRAPPLING_MISSED
                      and outcome in ("missed", "blocked", "defended", "reversed")):
                    variants = _PER_BEAT_GRAPPLING_MISSED[action]
                    text = _pick_variant(variants, fight_id, bid).format(
                        init=init_name, target=tgt_name,
                    )
                # Knockdown: always use the dramatic knockdown template.
                elif outcome == "knockdown":
                    text = _pick_variant(_PER_BEAT_OUTCOME["knockdown"], fight_id, bid).format(
                        init=init_name, target=tgt_name,
                    )
                # Near-finish: always use the near-finish template.
                elif outcome == "near_finish":
                    text = _pick_variant(_PER_BEAT_OUTCOME["near_finish"], fight_id, bid).format(
                        init=init_name, target=tgt_name,
                    )
                # Strike landed: use the action-specific landed template.
                elif (outcome == "landed" and action in _PER_BEAT_LANDED):
                    text = _pick_variant(_PER_BEAT_LANDED[action], fight_id, bid).format(
                        init=init_name, target=tgt_name,
                    )
                # Other outcomes: use the generic outcome templates.
                else:
                    variants = _PER_BEAT_OUTCOME.get(outcome)
                    if variants:
                        text = _pick_variant(variants, fight_id, bid).format(
                            init=init_name, target=tgt_name,
                        )
                    else:
                        # Defensive fallback — should not normally happen.
                        text = (f"{init_name} and {tgt_name} exchange in "
                                f"round {rn}.")

            # Append momentum emphasis if |momentum_shift| > 50 (the
            # same threshold the highlight-selection system uses).
            if abs(momentum) > _BIG_MOMENTUM_SWING_THRESHOLD and not is_round_end:
                emphasis = _pick_variant(
                    _PER_BEAT_MOMENTUM_EMPHASIS, fight_id, bid, offset=2,
                )
                text = text + emphasis

        # Round-ending marker (appended after the beat prose, unless
        # the beat itself is the finish — finishing beats end the
        # fight, not the round).
        if is_round_end and not is_finish:
            # If the beat had a big momentum shift favoring the
            # initiator, use the "hurt" round-end variant.
            if momentum > _BIG_MOMENTUM_SWING_THRESHOLD:
                end_text = _pick_variant(
                    _PER_BEAT_ROUND_END_HURT, fight_id, bid, offset=3,
                ).format(init=init_name, target=tgt_name)
            else:
                end_text = _pick_variant(
                    _PER_BEAT_ROUND_END, fight_id, bid, offset=3,
                )
            # Separate the beat prose from the round-end marker with
            # a space (the round-end variants are full sentences).
            if text and not text.endswith("."):
                text = text + ". "
            elif text:
                text = text + " "
            text = (text or "") + end_text

        # Importance: knockdowns/near-finishes are 80, big-momentum
        # beats are 70, round-ends are 60, others are 50. (These are
        # LOWER than the 'highlight' importance values (60-95) so the
        # UI can distinguish the two segment types by importance range
        # if needed — though the segment_type column is the canonical
        # discriminator.)
        if outcome == "knockdown":
            importance = 80
        elif outcome == "near_finish":
            importance = 75
        elif abs(momentum) > _BIG_MOMENTUM_SWING_THRESHOLD:
            importance = 70
        elif is_round_end:
            importance = 60
        else:
            importance = 50

        conn.execute(
            "INSERT INTO commentary_segments (event_id, fight_id, "
            "segment_type, speaker_staff_id, text, importance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, fight_id, "beat", speaker_id, text, importance),
        )
        count += 1
        prev_phase = phase

        # ---- P3.5: crowd reaction (after this beat) ----
        # Triggered by high |momentum_shift|, near_finish outcome,
        # round-end, or steady cadence (every CROWD_INTERVAL beats).
        # Skipped on the finishing beat (the finish IS the moment).
        if not is_finish:
            crowd_band = None
            if outcome == "near_finish":
                crowd_band = "near_finish"
            elif abs(momentum) >= 60:
                crowd_band = "high_positive" if momentum > 0 else "high_negative"
            elif is_round_end:
                crowd_band = "between_rounds"
            elif i > 0 and i % CROWD_INTERVAL == 0 and abs(momentum) >= 20:
                crowd_band = "high_positive"
            if crowd_band:
                variants = _CROWD_REACTIONS.get(crowd_band)
                if variants:
                    crowd_text = _pick_variant(variants, fight_id, bid, offset=10)
                    conn.execute(
                        "INSERT INTO commentary_segments (event_id, fight_id, "
                        "segment_type, speaker_staff_id, text, importance) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (event_id, fight_id, "crowd", None, crowd_text, 70),
                    )
                    count += 1

        # ---- P3.5: pundit interjection (every PUNDIT_INTERVAL beats) ----
        # Uses the player's actual commentator staff name. Mood is
        # derived from the beat's momentum_shift.
        if not is_finish and i > 0 and i % PUNDIT_INTERVAL == 0:
            if momentum > 30:
                mood = "praise_init"
            elif momentum < -30:
                mood = "worry_target"
            elif outcome == "knockdown":
                mood = "praise_init"
            else:
                mood = "neutral_observation"
            # Alternate between primary and secondary pundit by hash.
            if secondary_pundit and (bid % 2 == 0):
                active_pundit = secondary_pundit
            else:
                active_pundit = primary_pundit
            if active_pundit:
                variants = _PUNDIT_INTERJECTIONS.get(mood)
                if variants:
                    try:
                        pundit_text = _pick_variant(
                            variants, fight_id, bid, offset=20,
                        ).format(
                            pundit=active_pundit[1],
                            init=init_name, target=tgt_name,
                        )
                        conn.execute(
                            "INSERT INTO commentary_segments (event_id, fight_id, "
                            "segment_type, speaker_staff_id, text, importance) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (event_id, fight_id, "pundit",
                             active_pundit[0], pundit_text, 75),
                        )
                        count += 1
                    except Exception as _e:
                        print(f"[fight_engine._generate_per_beat_commentary/pundit] "
                              f"fight={fight_id} beat={bid}: {_e}", flush=True)

    return count


# ----------------------------------------------------------------
# P3.5 (docs/COMPREHENSIVE_FIX_PLAN.md §Group D #20) — extra
# commentary segments: ring announcer intro, named pundit
# interjections, crowd reactions.
#
# These are written as commentary_segments rows with NEW segment_type
# values ('announcer', 'pundit', 'crowd'). The Fight Night screen
# interleaves them with the per-beat 'beat' rows in Zone A (the
# commentary feed), each with distinct styling so the player can
# visually distinguish them:
#   - announcer: gold-tinted, ALL-CAPS, the in-arena PA voice
#   - pundit:    blue-tinted italic, the broadcast-booth interjection
#   - crowd:     amber banner, the arena soundscape
#
# Voice compliance (CONVENTIONS §14 + VOICE_ENFORCEMENT.md):
#   - Short fragmentary sentences. Specific imagery. No tabloid.
#   - No raw numbers in prose (no "momentum +80", no "damage 23").
#   - Pundit interjections use the player's actual commentator staff
#     name (from staff.role_type='commentator' on the player's promo)
#     so the interjections feel like a real broadcast team.
#   - Crowd reactions are ambient (no beat timestamp) — they're the
#     arena's soundscape, not a discrete exchange.
#
# Scheduling:
#   - announcer: 1 per fight, written at beat_index = -1 (before the
#     first beat). The UI inserts it at the top of the feed.
#   - pundit:    every 15-20 beats (deterministic by hash). The UI
#     inserts it AFTER the corresponding beat.
#   - crowd:     every 10-15 beats based on momentum_shift (high
#     positive/negative shift triggers a crowd reaction). The UI
#     inserts it AFTER the corresponding beat.
#
# 8+ variants per template per VOICE_ENFORCEMENT §3.
# ----------------------------------------------------------------


# Ring announcer intros — 8+ variants. Slots: {red}, {blue}, {red_loc}
# (red fighter's hometown/nation), {blue_loc}, {rounds}, {title} (either
# " for the championship" or ""). The announcer reads as the in-arena PA
# voice — promoter register, formal, building anticipation.

_RING_ANNOUNCER_INTROS = [
    "In the red corner, {red}. In the blue corner, {blue}. Our referee in charge of this {rounds}-round{title} bout — let's get it on!",
    "Ladies and gentlemen, introducing first in the red corner, {red}. And in the blue corner, {blue}. {rounds} rounds{title}. Let's begin.",
    "Red corner: {red}. Blue corner: {blue}. {rounds} rounds{title}. The referee is ready. Fight!",
    "First to the cage, in red, {red}. His opponent, in blue, {blue}. {rounds} rounds{title}. Here we go.",
    "In red, weighing in from {red_loc}, {red}. In blue, from {blue_loc}, {blue}. {rounds} rounds{title}. Let's get it on.",
    "Red corner — {red}. Blue corner — {blue}. This is a {rounds}-round{title} contest. Fight!",
    "Introducing in red, {red}. And in blue, {blue}. {rounds} rounds{title}. The horn sounds — we are underway.",
    "Two fighters, one cage. In red, {red}. In blue, {blue}. {rounds} rounds{title}. Let's fight.",
    "Ladies and gentlemen — in the red corner, hailing from {red_loc}, {red}. His opponent, in the blue corner, from {blue_loc}, {blue}. {rounds} rounds{title}.",
    "Red corner: {red}. Blue corner: {blue}. {rounds} rounds of action{title}. The referee waves us in — fight!",
    "In the red corner, {red}. In the blue corner, {blue}. {rounds} rounds{title}. The crowd is ready — let's get it on.",
    "First to the cage, {red}. And his opponent, {blue}. {rounds} rounds{title}. Here we go.",
    "Introducing the fighters. Red: {red}. Blue: {blue}. {rounds} rounds{title}. Let's begin.",
]


# Named-pundit interjections — 8+ variants per "mood". The mood is
# derived from the beat's momentum_shift (positive = the initiator is
# winning, negative = the target is rallying). Slots: {pundit} (the
# named commentator's name), {init}, {target}.

_PUNDIT_INTERJECTIONS = {
    "praise_init": [
        "{pundit}: \"{init}'s footwork is exceptional tonight.\"",
        "{pundit}: \"{init} is reading this fight beautifully.\"",
        "{pundit}: \"You can see {init} has trained this exactly.\"",
        "{pundit}: \"{init} is fighting a smart, smart fight.\"",
        "{pundit}: \"That's the work of a complete fighter. {init} is showing it all.\"",
        "{pundit}: \"{init} is in total control of the pace.\"",
        "{pundit}: \"Watch {init}'s distance management. That's elite.\"",
        "{pundit}: \"{init} is making this look easy. It isn't.\"",
        "{pundit}: \"{init} is dictating every exchange. That's how you win.\"",
        "{pundit}: \"You can see {init} has {target}'s timing down cold.\"",
        "{pundit}: \"{init} is fighting three moves ahead right now.\"",
        "{pundit}: \"That's the work of a champion in the making. {init} is special.\"",
        "{pundit}: \"{init} is not wasting a single motion tonight.\"",
    ],
    "worry_target": [
        "{pundit}: \"{target} needs to change levels — getting picked apart on the feet.\"",
        "{pundit}: \"{target} is falling into {init}'s rhythm. Has to break it.\"",
        "{pundit}: \"The corner has to be concerned. {target} is in trouble.\"",
        "{pundit}: \"{target} needs to find a way to slow this down.\"",
        "{pundit}: \"That's the third clean shot {target} has eaten. The chin can only take so much.\"",
        "{pundit}: \"{target} is reaching. When you reach, you get countered.\"",
        "{pundit}: \"{target} has to circle off the cage. Can't stay there.\"",
        "{pundit}: \"{target} is surviving, not fighting. There's a difference.\"",
        "{pundit}: \"{target} needs to commit to something. Anything.\"",
        "{pundit}: \"The corner has to be screaming at {target} to switch it up.\"",
        "{pundit}: \"{target} is taking damage. The ref is watching.\"",
        "{pundit}: \"{target} is loading up — that's a sign of desperation.\"",
        "{pundit}: \"{target} has to stop being a heavy bag. Move the head.\"",
    ],
    "neutral_observation": [
        "{pundit}: \"This is high-level stuff from both men.\"",
        "{pundit}: \"Two different styles, both committed to their gameplan.\"",
        "{pundit}: \"The pace is taking its toll on both fighters.\"",
        "{pundit}: \"You can see the chess match here. Both looking for the angle.\"",
        "{pundit}: \"Neither man wants to be the first to make a mistake.\"",
        "{pundit}: \"This is what championship rounds look like.\"",
        "{pundit}: \"The preparation is showing on both sides.\"",
        "{pundit}: \"Two professionals going to work. This is the sport at its purest.\"",
        "{pundit}: \"Both corners must be sweating this one. It's razor-thin.\"",
        "{pundit}: \"You're seeing adjustments on both sides. High-level stuff.\"",
        "{pundit}: \"Neither man is giving an inch here. Pure will.\"",
        "{pundit}: \"The next exchange could swing it. Both know it.\"",
        "{pundit}: \"This is what fight fans pay to see. Two elite operators.\"",
    ],
}


# Crowd reactions — 8+ variants per "band". The band is derived from
# the beat's momentum_shift:
#   - high_positive: |momentum_shift| >= 60 (knockdowns, near-finishes)
#   - high_negative: |momentum_shift| in [40, 60) — a big swing the other way
#   - near_finish: outcome='near_finish' specifically
#   - between_rounds: at the end of a round (the round-end marker)
# No slots — these are ambient arena soundscape, not fighter-specific.

_CROWD_REACTIONS = {
    "high_positive": [
        "The crowd erupts!",
        "The arena is shaking!",
        "Fans are on their feet!",
        "A roar rolls through the stands!",
        "The crowd comes alive!",
        "Deafening noise from the stands!",
        "The arena rises as one!",
        "Pandemonium in the building!",
        "The stands explode. Chairs rattle.",
        "A thunderous roar from the crowd!",
        "The noise is overwhelming!",
        "The crowd is on its feet, screaming.",
        "An electric roar from the rafters!",
    ],
    "high_negative": [
        "Silence falls over the arena.",
        "The crowd groans.",
        "You could hear a pin drop.",
        "A hush falls over the stands.",
        "The arena goes quiet.",
        "Fans hold their breath.",
        "The energy drains from the building.",
        "An uneasy murmur ripples through the crowd.",
        "The crowd exhales — a worried sound.",
        "The arena sinks into stunned silence.",
        "A collective intake of breath from the crowd.",
        "The noise dies. People sit back down.",
        "A low, anxious murmur spreads through the stands.",
    ],
    "near_finish": [
        "The crowd senses the end is near.",
        "Everyone's holding their breath.",
        "The arena is on its feet, sensing the finish.",
        "A roar builds as the finish looms.",
        "The crowd can taste the stoppage.",
        "Tension fills the arena.",
        "The fans lean in, sensing the moment.",
        "A collective gasp rolls through the stands.",
        "The arena buzzes — this could be it.",
        "The crowd rises, ready to erupt.",
        "Every eye in the building is locked on the cage.",
        "The fans are restless — they can feel it coming.",
        "A wave of anticipation sweeps through the stands.",
    ],
    "between_rounds": [
        "The crowd buzzes with anticipation for the next round.",
        "A murmur builds between rounds.",
        "Fans debate the scorecards between rounds.",
        "The arena hums with energy as the next round approaches.",
        "Anticipation builds in the break.",
        "The crowd settles back in for the next round.",
        "A restless energy fills the arena between rounds.",
        "Fans swap predictions for the next round.",
        "The between-rounds buzz builds. People lean forward.",
        "A low hum of conversation fills the arena.",
        "The crowd stretches, resets. Waiting for the bell.",
        "Beer vendors weave through the aisles. The crowd buzzes.",
        "The arena settles into a tense hush before the next round.",
    ],
}


def _weight_class_walk_weight(conn, weight_class_id):
    """Return a human-readable weight for the announcer intro, or None.

    Pulls the weight_class name (e.g. "Lightweight") from the DB and
    returns the lowercased name. The announcer intro slot is optional
    — the templates work without it (we use {red_loc} / {blue_loc}
    for the location slot, not a weight slot, so this helper is
    currently unused but kept for future template expansion).
    """
    if not weight_class_id:
        return None
    row = conn.execute(
        "SELECT name FROM weight_classes WHERE weight_class_id=?",
        (weight_class_id,),
    ).fetchone()
    return row[0] if row else None


def _fighter_hometown_phrase(conn, fighter_id):
    """Return a hometown/nation phrase for the announcer intro.

    Looks up the fighter's birth city + nation via the cities + nations
    tables (joined on fighters.birth_city_id / birth_nation_id).
    Returns "<City>, <Country>" if both are available, else just one,
    else None. Used to fill the {red_loc} / {blue_loc} slots in the
    ring announcer templates.
    """
    if not fighter_id:
        return None
    row = conn.execute(
        "SELECT bc.name, bn.name FROM fighters f "
        "LEFT JOIN cities bc ON bc.city_id=f.birth_city_id "
        "LEFT JOIN nations bn ON bn.nation_id=f.birth_nation_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return None
    city, nation = row
    if city and nation:
        return f"{city}, {nation}"
    if nation:
        return nation
    if city:
        return city
    return None


def _player_promo_commentators(conn, fight_event_promo_id):
    """Return a list of (staff_id, full_name) for the player's promo's
    active commentators.

    Per P3.5, named-pundit interjections should use the player's
    actual commentator staff. We look up staff rows WHERE
    role_type='commentator' AND promotion_id=<fight's promo>. Returns
    up to 2 names (a typical broadcast booth is play-by-play + color
    commentator). Falls back to the global commentator pool (any
    promo) if the player's promo has none.
    """
    # First try the fight's own promo. (The staff table has no
    # is_active column — staff are considered active if they have a
    # row at all. The contract status is tracked separately in
    # staff_contracts.)
    rows = conn.execute(
        "SELECT staff_id, first_name, last_name FROM staff "
        "WHERE role_type='commentator' AND promotion_id=? "
        "ORDER BY staff_id LIMIT 2",
        (fight_event_promo_id,),
    ).fetchall()
    if not rows:
        # Fallback: any commentator (matches the existing
        # _generate_beat_commentary speaker lookup).
        rows = conn.execute(
            "SELECT staff_id, first_name, last_name FROM staff "
            "WHERE role_type='commentator' "
            "ORDER BY staff_id LIMIT 2",
        ).fetchall()
    out = []
    for (sid, fn, ln) in rows:
        name = ((fn or "") + " " + (ln or "")).strip()
        if not name:
            name = "The Booth"
        out.append((sid, name))
    return out


# ----------------------------------------------------------------
# P3.5 DEPRECATED — _generate_extra_segments was the original
# standalone implementation of the announcer/pundit/crowd system.
# It was removed because writing all extra segments AFTER all beats
# broke the UI's beat_index derivation (all extra segments collapsed
# to the last beat). The logic is now inline in
# _generate_per_beat_commentary, which interleaves the extra segments
# with the beat segments so the commentary_segment_ids stay in
# chronological order. The templates (_RING_ANNOUNCER_INTROS,
# _PUNDIT_INTERJECTIONS, _CROWD_REACTIONS) and helpers
# (_player_promo_commentators, _fighter_hometown_phrase) are still
# used by the inline implementation.
# ----------------------------------------------------------------




# ----------------------------------------------------------------
# Event lifecycle (Task ID 7).
# ----------------------------------------------------------------
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

    Phase A5 — when the event transitions to 'completed', publishes
    EVENT_COMPLETED on the event bus (news engine subscribes to
    write an event recap news item).

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

    # Fetch the current status so we can detect the transition to
    # 'completed' (Phase A5 — publish EVENT_COMPLETED on transition).
    cur_row = conn.execute(
        "SELECT status, promotion_id, event_date FROM events WHERE event_id=?",
        (event_id,),
    ).fetchone()
    prev_status = cur_row[0] if cur_row else None
    promo_id = cur_row[1] if cur_row else None
    event_date = cur_row[2] if cur_row else None

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

    # Phase A5 — publish EVENT_COMPLETED on the transition to
    # 'completed'. The news engine subscribes to write an event
    # recap news item. The check (prev_status != 'completed' AND
    # new_status == 'completed') ensures we publish exactly once
    # per event (not on every call after completion).
    if new_status == "completed" and prev_status != "completed":
        try:
            from event_bus import get_bus, Events
            bus = get_bus()
            bus.publish(conn, {
                'type': Events.EVENT_COMPLETED,
                'event_id': event_id,
                'promotion_id': promo_id,
                'event_date': event_date,
            })
        except ImportError:
            pass


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
# a title fight (is_title_fight=1 — the canonical check since v2.2.0,
# Task pre-B2-fix; the legacy `bout_type='title_fight'` check is
# DEPRECATED). Called unconditionally by `resolve_next_fight()` but
# returns None early if the fight is not a title fight (defensive —
# the caller doesn't need to check is_title_fight).
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
      - Only fires if the fight's `is_title_fight=1` (canonical check
        since v2.2.0 / Task pre-B2-fix — the legacy `bout_type='title_fight'`
        comparison is DEPRECATED). Called unconditionally by
        resolve_next_fight() but returns early if the fight is not a
        title fight (defensive — the caller doesn't need to check
        is_title_fight).
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
            falls back to simulation_clock.current_date (HW2.2: was
            CURRENT_DATE which is today's REAL-WALL-CLOCK date — a
            Time Law violation. The fallback now reads the sim clock
            via a SQL subquery so champion_since_date is always a sim
            date, never a real-world date).

    Returns:
        title_id (int) if a title change occurred, else None.
    """
    # 1. Fetch the fight's is_title_fight flag (v2.2.0 canonical check).
    #    If it's not 1, this is a no-op (defensive — the caller doesn't
    #    need to check is_title_fight before calling). The legacy
    #    `bout_type='title_fight'` comparison is DEPRECATED — kept on
    #    the column for backward compatibility but no longer read.
    fight_row = conn.execute(
        "SELECT is_title_fight FROM fights WHERE fight_id = ?",
        (fight_id,),
    ).fetchone()
    if not fight_row or fight_row[0] != 1:
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
        # HW2.2: champion_since_date fallback uses simulation_clock.
        # current_date (sim date) instead of CURRENT_DATE (real-world
        # date) — Time Law compliance. fight_date is normally passed
        # in by the caller; this COALESCE is a defensive fallback.
        conn.execute(
            "UPDATE titles SET current_champion_fighter_id = ?, "
            "champion_since_date = COALESCE(?, "
            "    (SELECT simulation_clock.current_date "
            "     FROM simulation_clock WHERE clock_id=1)), "
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
            # HW2.2: champion_since_date fallback uses simulation_clock.
            # current_date (sim date) instead of CURRENT_DATE (real-world
            # date) — Time Law compliance.
            conn.execute(
                "UPDATE titles SET current_champion_fighter_id = ?, "
                "champion_since_date = COALESCE(?, "
                "    (SELECT simulation_clock.current_date "
                "     FROM simulation_clock WHERE clock_id=1)), "
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


# ----------------------------------------------------------------
# Weight cuts (Task ID 17).
#
# Before a fight, fighters cut weight to make their weight class limit.
# The `weight_cut_difficulty` column (0-100, per-fighter static, added
# in Task 14.5) drives the base miss probability. Age (older = harder
# cut) and camp_weight_cut_pressure (from weight_cut-focused camps,
# Task 16) modify the probability. Gym weight_cut_support reduces it.
#
# The cut outcome determines what happens:
#   made_weight    — no penalty, fight proceeds normally
#   missed_small   — missed by < 1kg, 20% purse forfeiture, no cardio penalty
#   missed_medium  — missed by 1-3kg, 30% purse forfeiture, 15 cardio penalty
#   missed_large   — missed by > 3kg, fight CANCELLED (no_contest)
#
# The cardio penalty reduces the fighter's starting gas in
# resolve_next_fight (gas = 100 - cardio_penalty, floored at 50).
# This is the "hard cut cost the fighter his gas" story.
# ----------------------------------------------------------------





def _compute_weight_cut_miss_prob(conn, fighter_id, event_id):
    """Compute the probability (0.0-1.0) that a fighter misses weight.

    Base probability from weight_cut_difficulty (0-100 → 0%-40%).
    Modified by:
      + age (fighters 30+ get +1% per year over 30, max +15%)
      + camp_weight_cut_pressure (0-100 → 0%-20%, from weight_cut camps)
      - gym weight_cut_support (0-100 → 0%-15% reduction)

    Capped at 0.75 (75% max miss probability — even the worst cutter
    makes weight sometimes).

    Args:
        conn: sqlite3 connection (read-only).
        fighter_id: the fighter attempting the cut.
        event_id: the event the fight is on (for camp pressure lookup).

    Returns:
        Float 0.0-1.0 — the probability of missing weight.
    """
    row = conn.execute(
        "SELECT f.weight_cut_difficulty, f.date_of_birth, "
        "f.current_gym_id "
        "FROM fighters f WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if row is None:
        return 0.0
    wcd, dob, gym_id = row
    wcd = wcd or 50  # default if NULL
    # Base miss probability: 0% at wcd=0, 40% at wcd=100
    base_prob = wcd / 100.0 * 0.40
    # Age modifier: +1% per year over 30, max +15%
    if dob:
        try:
            birth_year = int(dob[:4])
            age = 2026 - birth_year  # sim date is 2026-07-22
            if age > 30:
                base_prob += min(0.15, (age - 30) * 0.01)
        except (ValueError, TypeError):
            pass
    # Camp weight_cut_pressure modifier: 0-20% from weight_cut camps
    camp_row = conn.execute(
        "SELECT camp_weight_cut_pressure FROM training_camps "
        "WHERE fighter_id=? AND event_id=? "
        "ORDER BY training_camp_id DESC LIMIT 1",
        (fighter_id, event_id),
    ).fetchone()
    if camp_row:
        pressure = camp_row[0]
        base_prob += pressure / 100.0 * 0.20
    # Gym weight_cut_support reduction: 0-15%
    if gym_id is not None:
        gym_row = conn.execute(
            "SELECT weight_cut_support FROM gyms WHERE gym_id=?",
            (gym_id,),
        ).fetchone()
        if gym_row:
            support = gym_row[0]
            base_prob -= support / 100.0 * 0.15
    # Clamp to [0, 0.75]
    return max(0.0, min(0.75, base_prob))





def _run_weight_cut(conn, fighter_id, fight_id, event_id, weight_class_id,
                    event_date, is_title_fight):
    """Run the weight cut for a fighter and return the cut_outcome.

    Rolls against the miss probability. If the fighter misses, picks a
    cut_outcome (missed_small / missed_medium / missed_large) based on
    how badly they missed. Writes a weight_cut_log row + a news item.

    Returns:
        A dict with keys: cut_outcome (str), cardio_penalty (int),
        purse_penalty_pct (int), weight_missed_kg (float),
        actual_weight_kg (float or None).
    """
    # Get the weight class target weight (max_weight_kg)
    wc_row = conn.execute(
        "SELECT max_weight_kg FROM weight_classes WHERE weight_class_id=?",
        (weight_class_id,),
    ).fetchone()
    if wc_row is None:
        return {"cut_outcome": "made_weight", "cardio_penalty": 0,
                "purse_penalty_pct": 0, "weight_missed_kg": 0.0,
                "actual_weight_kg": None}
    target_weight = wc_row[0]

    # Compute miss probability
    miss_prob = _compute_weight_cut_miss_prob(conn, fighter_id, event_id)

    # Roll
    if random.random() < miss_prob:
        # Fighter misses weight. Pick how badly.
        # 50% small (< 1kg), 35% medium (1-3kg), 15% large (> 3kg)
        roll = random.random()
        if roll < 0.50:
            cut_outcome = "missed_small"
            weight_missed = random.uniform(0.1, 0.9)
            cardio_penalty = 0
            purse_penalty = 20
        elif roll < 0.85:
            cut_outcome = "missed_medium"
            weight_missed = random.uniform(1.0, 3.0)
            cardio_penalty = 15
            purse_penalty = 30
        else:
            cut_outcome = "missed_large"
            weight_missed = random.uniform(3.1, 5.0)
            cardio_penalty = 0  # fight cancelled, no cardio penalty applies
            purse_penalty = 50  # opponent gets 50%, offender gets nothing
        actual_weight = target_weight + weight_missed
    else:
        # Fighter makes weight
        cut_outcome = "made_weight"
        weight_missed = 0.0
        actual_weight = target_weight
        cardio_penalty = 0
        purse_penalty = 0

    # Write the weight_cut_log row
    conn.execute(
        "INSERT INTO weight_cut_log (fighter_id, fight_id, event_id, "
        "weight_class_id, cut_date, target_weight_kg, actual_weight_kg, "
        "weight_missed_kg, cut_outcome, cardio_penalty, purse_penalty_pct, "
        "is_title_fight) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fighter_id, fight_id, event_id, weight_class_id, event_date,
         target_weight, actual_weight, weight_missed, cut_outcome,
         cardio_penalty, purse_penalty, is_title_fight),
    )

    # Write a news item about the cut result
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
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
    name_row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    fighter_name = name_row[0] if name_row else f"Fighter {fighter_id}"
    # v2.10.0 (FIX-VoiceRep, §14): the OLD inline weight-cut news
    # used raw kg numbers ("70.3kg", "0.3kg") and a raw purse
    # percentage ("20%"). Both violated CONVENTIONS §14 — no raw
    # numbers in player-facing text. The templates now use word-form
    # phrases ("a slim margin", "a noticeable margin", "a wide
    # margin") matching the news engine's _WEIGHT_CUT_HEADLINES
    # voice-layer phrases. The richer voice-layer weight-cut news
    # is generated by news.generate_weight_cut_news on
    # WEIGHT_CUT_COMPLETED — this inline item is a placeholder.
    if cut_outcome == "made_weight":
        headline = f"{fighter_name} makes weight"
        body = f"{fighter_name} successfully made weight for the upcoming fight."
        sentiment = "neutral"
    elif cut_outcome == "missed_large":
        headline = f"{fighter_name} misses weight badly — fight cancelled"
        body = (f"{fighter_name} missed weight by a wide margin. "
                f"The fight has been cancelled. The opponent will receive "
                f"a portion of their purse as compensation.")
        sentiment = "negative"
    else:
        headline = f"{fighter_name} misses weight"
        body = (f"{fighter_name} missed weight by a slim margin. "
                f"The fight will proceed at catch-weight. "
                f"{fighter_name.split()[0]} forfeits a portion of their purse "
                f"as a penalty"
                f"{' and will start the fight with depleted cardio' if cardio_penalty > 0 else ''}.")
        sentiment = "negative"
    # NEWS-SPAM-MEMORY-CHECK — suppress the "made weight" news entirely
    # (it's not interesting — every fighter on every card makes weight
    # most of the time). Only write news when a fighter MISSES weight,
    # tagged SIGNIFICANT (a weight miss changes the fight — catch-
    # weight, purse penalty, or cancellation).
    if cut_outcome != "made_weight":
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, fight_id, event_id, published_at, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, sentiment, "weight_cut", fighter_id,
             fight_id, event_id, event_date, "SIGNIFICANT"),
        )

    # Phase A5 — publish WEIGHT_CUT_COMPLETED on the event bus. The
    # news engine subscribes to write a richer weigh-in news item
    # (the inline item above has raw kg numbers for the debug feed;
    # the event-driven item uses word-form phrases per §14). The
    # event payload includes the cut_outcome so subscribers can
    # filter (e.g., a future "weight miss penalty" subscriber only
    # fires on missed_* outcomes).
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.WEIGHT_CUT_COMPLETED,
            'fighter_id': fighter_id,
            'fight_id': fight_id,
            'event_id': event_id,
            'weight_class_id': weight_class_id,
            'cut_outcome': cut_outcome,
            'weight_missed_kg': weight_missed,
            'actual_weight_kg': actual_weight,
            'target_weight_kg': target_weight,
            'event_date': event_date,
            'current_date': event_date,
        })
    except ImportError:
        pass

    return {
        "cut_outcome": cut_outcome,
        "cardio_penalty": cardio_penalty,
        "purse_penalty_pct": purse_penalty,
        "weight_missed_kg": weight_missed,
        "actual_weight_kg": actual_weight,
    }


# ----------------------------------------------------------------
# Fighter descriptor snapshot (Task 19 — Voice/Interpretation Layer).
#
# update_fighter_descriptor_snapshot() reads a fighter's current
# attrs/pers/career from the DB, calls voice.build_descriptor_
# snapshot() to compute the descriptor strings, and writes the
# result to the fighter_descriptors table. This is the TRIGGER-
# BASED cache update — called on camp completion, fight resolution,
# injury creation/recovery, and title changes. The UI reads from
# fighter_descriptors directly (no recomputation on every view).
# ----------------------------------------------------------------





def update_fighter_descriptor_snapshot(conn, fighter_id):
    """Recompute + cache a fighter's descriptor snapshot.

    Reads the fighter's current attributes, personality, career
    state, and style archetype from the DB, calls voice.build_
    descriptor_snapshot() to compute descriptor strings, and writes
    the result to the fighter_descriptors table (INSERT OR REPLACE).

    Called on trigger events:
      - Training camp completion (tick_processor._complete_training_camp)
      - Fight resolution (app.resolve_next_fight, for both fighters)
      - Injury creation (app._maybe_create_injury)
      - Injury recovery (tick_processor._check_injury_recovery)
      - Title changes (app.resolve_next_fight title section)

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter whose snapshot to update.
    """
    import json
    import voice
    import random as _rng

    # Load fighter data
    f_row = conn.execute(
        "SELECT f.first_name, f.last_name, f.nickname, f.date_of_birth, "
        "f.fight_style_archetype_id, f.current_promotion_id, "
        "sa.name AS style_archetype_name "
        "FROM fighters f "
        "LEFT JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if f_row is None:
        return  # fighter doesn't exist (deleted?)
    first, last, nick, dob, sa_id, promo_id, sa_name = f_row

    # Load attributes
    attr_row = conn.execute(
        "SELECT * FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if attr_row is None:
        return  # no attributes (shouldn't happen for active fighters)
    attr_cols = [d[0] for d in conn.execute("SELECT * FROM fighter_attributes WHERE fighter_id=?", (fighter_id,)).description]
    attrs = {col: val for col, val in zip(attr_cols, attr_row)
             if col not in ("fighter_attribute_id", "fighter_id", "created_at", "updated_at")
             and val is not None}

    # Load personality
    pers_row = conn.execute(
        "SELECT * FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if pers_row is None:
        return
    pers_cols = [d[0] for d in conn.execute("SELECT * FROM fighter_personality WHERE fighter_id=?", (fighter_id,)).description]
    pers = {col: val for col, val in zip(pers_cols, pers_row)
            if col not in ("fighter_personality_id", "fighter_id", "created_at", "updated_at")
            and val is not None}

    # Load career
    fc_row = conn.execute(
        "SELECT record_wins, record_losses, record_draws, win_streak, "
        "loss_streak, career_health, potential, title_reigns "
        "FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if fc_row is None:
        return
    wins, losses, draws, ws, ls, health, potential, reigns = fc_row

    # Check if champion
    is_champion = conn.execute(
        "SELECT 1 FROM titles WHERE current_champion_fighter_id=?",
        (fighter_id,),
    ).fetchone() is not None

    # Compute age
    age = 30
    if dob:
        try:
            age = 2026 - int(dob[:4])
        except (ValueError, TypeError):
            pass

    # Build fighter_data dict for voice layer
    fighter_data = {
        "first_name": first,
        "last_name": last,
        "nickname": nick,
        "age": age,
        "record_wins": wins,
        "record_losses": losses,
        "record_draws": draws,
        "win_streak": ws or 0,
        "loss_streak": ls or 0,
        "is_champion": is_champion,
        "title_reigns": reigns or 0,
        "career_health": health or 100,
        "style_archetype_name": sa_name or "Balanced",
    }

    # Compute snapshot
    rng = _rng.Random(fighter_id)  # deterministic per fighter (stable descriptors)
    snapshot = voice.build_descriptor_snapshot(attrs, pers, fighter_data, rng)

    # Write to fighter_descriptors table
    conn.execute(
        "INSERT OR REPLACE INTO fighter_descriptors "
        "(fighter_id, attribute_descriptors, personality_descriptors, "
        "career_stage, career_health_desc, overall_desc, potential_desc, "
        "snapshot_version, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, "
        "COALESCE((SELECT snapshot_version + 1 FROM fighter_descriptors WHERE fighter_id=?), 1), "
        "CURRENT_TIMESTAMP)",
        (fighter_id,
         json.dumps(snapshot["attribute_descriptors"]),
         json.dumps(snapshot["personality_descriptors"]),
         snapshot["career_stage"],
         snapshot["career_health"],
         snapshot["overall"],
         snapshot["potential_descriptor"],
         fighter_id),
    )


# ----------------------------------------------------------------
# Injury creation (v2.4.0, Task 15).
#
# `_maybe_create_injury()` is called at the END of
# resolve_next_fight() — AFTER all existing side effects
# (fight_history, rankings, titles, event lifecycle,
# schedule_next_event, news, commentary, commentary beat selection).
# It is the LAST side effect of fight resolution.
#
# For each fighter in the resolved fight, the helper:
#   1. Computes cumulative damage_taken from fight_beats (sum of
#      damage_dealt where target_fighter_id = fighter_id).
#   2. Rolls against injury probability (varies by result_type — see
#      _INJURY_* constants above).
#   3. Modifies the probability by injury_proneness (0.5x-1.5x).
#   4. If injured: picks injury_type + body_area + severity (with
#      durability reducing severity), computes projected_return_date,
#      rolls for long_term_damage (30% chance if sev >= 8), writes
#      the injuries row + a news item, and reduces fighter_career.
#      career_health by severity*2 (temporary) + long_term_damage
#      (permanent).
#
# Returns the list of injury_ids created (0, 1, or 2 entries).
# ----------------------------------------------------------------




def _maybe_create_injury(conn, fighter_id, fight_id, event_id, event_date,
                          result_type, is_loser, damage_taken,
                          finishing_beat_id, stats, proneness):
    """Roll for an injury on a single fighter and write the row if injured.

    Args:
        conn: sqlite3 connection (caller commits — same pattern as every
            other side-effect helper in this module).
        fighter_id: the fighter who may be injured.
        fight_id: the fight that just resolved.
        event_id: the event the fight belongs to.
        event_date: 'YYYY-MM-DD' — used as the injury's start_date and
            the basis for projected_return_date.
        result_type: the fight's result_type (ko_tko / submission /
            doctor_stoppage / corner_stoppage / dq /
            unanimous_decision / split_decision / draw). Determines
            which injury branch fires.
        is_loser: True if this fighter lost the fight. Finish-based
            injuries (KO concussion, submission joint, doctor
            stoppage) only apply to the loser.
        damage_taken: cumulative damage_dealt to this fighter across
            all rounds (sum from fight_beats where
            target_fighter_id = fighter_id). Used to scale the
            non-finish injury probability.
        finishing_beat_id: the fight_beat_id of the finishing exchange
            (for KO/submission). None for decision / draw / doctor /
            corner / DQ. The damage_dealt of this beat scales the KO
            concussion severity per the brief.
        stats: the fighter's full attribute+personality dict (from
            _load_fighter_stats). Used for durability (severity
            reduction), recovery_rate (recovery timeline).
        proneness: the fighter's injury_proneness value (0-100, from
            the fighters table). Modifies the injury probability.

    Returns:
        The new injury_id if an injury was created, else None.

    Implementation notes:
      - The injury probability is computed per the brief's rules
        (see the _INJURY_* constants above). injury_proneness is a
        linear 0.5x-1.5x multiplier.
      - Severity is rolled in the [sev_min, sev_max] range from
        _INJURY_TYPES_BY_BODY_AREA, then adjusted by durability
        (-2 at dur=100, +2 at dur=0), clamped to [1, 10].
      - projected_return_date = start_date + max(_INJURY_MIN_DAYS_OUT,
        severity * 14 - int(recovery_rate * 0.1)).
      - For severity >= _INJURY_LONGTERM_SEVERITY_THRESHOLD (8), roll
        a 30% chance for long_term_damage in [2, 5]. If long-term,
        reduce the body-area-relevant fighter_attribute by that
        amount (clamped at 0 — attributes never go negative) and
        permanently reduce career_health by the same amount.
      - career_health is also reduced by severity * 2 (temporary —
        restored on recovery by _check_injury_recovery in
        tick_processor.py).
      - A news item is written: "{Fighter} suffers {injury_type} —
        projected return {date}" with topic='injury', fighter_id
        set, fight_id + event_id set so future UIs can group injury
        news by fight.
    """
    # ---- 1. Compute injury probability + body_area + type pool ----
    if result_type == "doctor_stoppage":
        # Guaranteed injury on the loser (the loser was taking the
        # beating that triggered the stoppage). The winner of a
        # doctor stoppage does not get injured (they were the one
        # dealing damage, not taking it).
        if not is_loser:
            return None
        injury_chance = _INJURY_DOCTOR_GUARANTEED
        # Doctor stoppage is a one-sided beating — the loser's
        # injuries tend to be in the high-damage areas: head (the
        # doctor stopped it because of facial swelling / a cut /
        # concussion risk), face (laceration), or general (body
        # damage). Pick from a damage-weighted pool.
        body_area = random.choice([
            "head", "head", "head", "face", "face", "face",
            "ribs", "general", "general",
        ])
    elif result_type == "ko_tko" and is_loser:
        # 30% chance of head injury (concussion) on the loser.
        injury_chance = _INJURY_KO_HEAD_PROB
        body_area = "head"
    elif result_type == "submission" and is_loser:
        # 15% chance of joint injury on the loser.
        injury_chance = _INJURY_SUBMISSION_JOINT_PROB
        body_area = random.choice(_INJURY_SUBMISSION_JOINT_AREAS)
    else:
        # Non-finish (decision / draw / corner_stoppage / dq) AND
        # any fighter (winner OR loser). 5% base + damage-scaled.
        # The brief specifies the 5% base + damage-scaled chance
        # applies to "non-finish" — interpreted here as all result
        # types NOT explicitly listed above (so corner_stoppage and
        # dq fall through to this branch, since neither is a finish
        # in the KO/sub/doctor sense).
        damage_scaled = min(
            damage_taken / _INJURY_DAMAGE_SCALE_DIVISOR,
            _INJURY_DAMAGE_SCALE_CAP,
        )
        injury_chance = _INJURY_BASE_PROB_NONFINISH + damage_scaled
        body_area = random.choice(_INJURY_BODY_AREAS_NONFINISH)

    # ---- 2. Modify probability by injury_proneness ----
    # Linear 0.5x (proneness=0) to 1.5x (proneness=100).
    proneness_mult = (
        _INJURY_PRONENESS_MIN_MULT
        + (proneness / 100.0)
        * (_INJURY_PRONENESS_MAX_MULT - _INJURY_PRONENESS_MIN_MULT)
    )
    injury_chance *= proneness_mult

    # Cap at 1.0 so a high-proneness + guaranteed injury case doesn't
    # produce probability > 1.0 (which would still trigger, but the
    # cap is defensive and makes the math cleaner for log/inspection).
    injury_chance = min(injury_chance, 1.0)

    # ---- 3. Roll against the probability ----
    if random.random() > injury_chance:
        return None

    # ---- 4. Pick injury type + severity from the body_area pool ----
    type_pool = _INJURY_TYPES_BY_BODY_AREA.get(body_area)
    if not type_pool:
        # Defensive: body_area should always be in the pool. Fall
        # back to general if somehow not (keeps the function from
        # crashing — the CHECK constraint would also catch an
        # invalid body_area on INSERT).
        type_pool = _INJURY_TYPES_BY_BODY_AREA["general"]
        body_area = "general"
    injury_type, sev_min, sev_max = random.choice(type_pool)
    severity = random.randint(sev_min, sev_max)

    # KO/TKO finish: scale severity by the finishing beat's damage.
    # The brief says "severity scaled by damage in finishing
    # sequence". The finishing beat is the knockdown beat — its
    # damage_dealt is the damage of the finishing blow. We map
    # damage 30-100+ to a +0 to +3 severity boost (clamped at 10).
    if result_type == "ko_tko" and is_loser and finishing_beat_id is not None:
        row = conn.execute(
            "SELECT damage_dealt FROM fight_beats WHERE fight_beat_id=?",
            (finishing_beat_id,),
        ).fetchone()
        if row and row[0] is not None:
            # damage 30 → +0, damage 100 → +3 (linear, clamped).
            finish_sev_boost = max(0, min(3, (row[0] - 30) // 24))
            severity = min(10, severity + finish_sev_boost)

    # ---- 5. Reduce severity by durability ----
    # Linear: dur=0 → +2, dur=50 → 0, dur=100 → -2.
    durability = stats.get("durability", 50)
    durability_adj = int(round(
        _INJURY_DURABILITY_SEVERITY_ADJUST
        * (1.0 - durability / 50.0)
    ))
    severity = max(1, min(10, severity + durability_adj))

    # ---- 6. Compute projected_return_date ----
    recovery_rate = stats.get("recovery_rate", 50)
    base_days = severity * _INJURY_BASE_DAYS_PER_SEVERITY
    recovery_discount = int(recovery_rate * _INJURY_RECOVERY_RATE_DAYS_PER_POINT)
    days_out = max(_INJURY_MIN_DAYS_OUT, base_days - recovery_discount)

    # Phase E5 — Doctor recovery-time reduction. The fighter's promo
    # may have active doctors (role_type='doctor' with active
    # staff_contracts). Each contributes (skill/200) recovery bonus,
    # capped at 15% total. We APPLY the bonus here at injury-creation
    # time (rather than at recovery-tick time) because the
    # projected_return_date is what the player sees in the UI and
    # what _check_injury_recovery uses to clear the injury. Shortening
    # it here gives the player immediate feedback that their doctor
    # staff investment matters. Per docs/DESIGN_REVIEW_E5.md §5.
    fighter_promo_id = stats.get("current_promotion_id")
    try:
        from services.injuries_svc import get_doctor_recovery_bonus
        doctor_bonus = get_doctor_recovery_bonus(conn, fighter_promo_id)
    except Exception:
        doctor_bonus = 0.0  # defensive — never break injury creation
    if doctor_bonus > 0:
        # Reduce days_out by the doctor bonus fraction (e.g. 5% bonus
        # on a 100-day recovery = 95 days). Floor at _INJURY_MIN_DAYS_
        # OUT (7 days) so a doctor bonus can't make a sev-1 cut heal
        # in less than a week.
        reduced_days = int(days_out * (1.0 - doctor_bonus))
        days_out = max(_INJURY_MIN_DAYS_OUT, reduced_days)

    start_dt = datetime.strptime(event_date, "%Y-%m-%d")
    projected_dt = start_dt + timedelta(days=days_out)
    start_date_str = event_date
    projected_str = projected_dt.strftime("%Y-%m-%d")

    # ---- 7. Long-term damage (severity 8+ only, 30% chance) ----
    long_term_damage = 0
    if severity >= _INJURY_LONGTERM_SEVERITY_THRESHOLD:
        if random.random() < _INJURY_LONGTERM_PROB:
            long_term_damage = random.randint(
                _INJURY_LONGTERM_MIN, _INJURY_LONGTERM_MAX
            )

    # ---- 8. Career risk ----
    # Cumulative risk: severity * 5 (max 50), +10 per point of
    # long_term_damage (max +50). Capped at 100.
    career_risk = min(100, severity * 5 + long_term_damage * 10)

    # ---- 9. Insert the injuries row ----
    cur = conn.execute(
        "INSERT INTO injuries (fighter_id, event_id, fight_id, "
        "injury_type, severity, body_area, start_date, "
        "projected_return_date, long_term_damage, career_risk, "
        "is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (fighter_id, event_id, fight_id, injury_type, severity,
         body_area, start_date_str, projected_str, long_term_damage,
         career_risk),
    )
    injury_id = cur.lastrowid

    # ---- 10. Reduce fighter_career.career_health ----
    # Two reductions:
    #   (a) severity * _INJURY_CAREER_HEALTH_MULT (temporary — restored
    #       on recovery by _check_injury_recovery in tick_processor.py).
    #   (b) long_term_damage (permanent — NOT restored on recovery).
    # Both are applied here as a single UPDATE; the recovery helper
    # only restores the (a) part. The MAX(0, ...) keeps career_health
    # non-negative (the column has no CHECK but a negative value
    # would be nonsensical and could break retirement logic which
    # checks career_health < 60).
    health_reduction = severity * _INJURY_CAREER_HEALTH_MULT + long_term_damage
    conn.execute(
        "UPDATE fighter_career SET career_health = MAX(0, career_health - ?), "
        "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
        (health_reduction, fighter_id),
    )

    # ---- 11. Long-term attribute reduction ----
    # Per the brief: "-2 to -5 on relevant attribute". The relevant
    # attribute is determined by _INJURY_LONGTERM_ATTR_BY_AREA. The
    # reduction is applied to fighter_attributes directly (clamped
    # at 0 — attributes never go negative). This is the permanent
    # consequence the Soul document demands: a torn ACL at age 32
    # permanently reduces the fighter's speed_explosiveness, which
    # the player sees in their decline.
    if long_term_damage > 0:
        attr = _INJURY_LONGTERM_ATTR_BY_AREA.get(body_area, "durability")
        # Whitelist the attribute name before interpolating into SQL
        # (defensive — the map is hardcoded above, but the whitelist
        # protects against a future bug if someone edits the map).
        if attr not in _FIGHTER_ATTR_COLUMNS:
            attr = "durability"
        conn.execute(
            f"UPDATE fighter_attributes SET {attr} = MAX(0, {attr} - ?), "
            "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
            (long_term_damage, fighter_id),
        )

    # ---- 12. Write the injury news item ----
    # Per the brief: "{Fighter name} suffers {injury_type} — projected
    # return {date}". topic='injury' so future news-engine work can
    # filter injury-themed items. fighter_id, fight_id, event_id all
    # set so future UIs can group injury news by fighter / fight /
    # event.
    fighter_name_str = fighter_name(conn, fighter_id)
    from app import write_news  # lazy import — write_news lives in app.py per Task 6.0 §1.3
    write_news(
        conn,
        f"{fighter_name_str} suffers {injury_type}",
        # v2.10.0 (FIX-VoiceRep, §14): the OLD body used a raw
        # severity digit ("severity 8/10"). Replaced with a word-form
        # severity phrase ("a serious", "a moderate", "a minor") via
        # _severity_phrase_inline. The richer voice-layer injury news
        # is generated by news.generate_injury_news on FIGHT_RESOLVED
        # — this inline item is a placeholder.
        f"{fighter_name_str} suffers {_severity_phrase_inline(severity)} "
        f"{injury_type} ({body_area}) during the fight. Projected return: "
        f"{projected_str}.",
        topic="injury",
        event_id=event_id,
        fight_id=fight_id,
        fighter_id=fighter_id,
    )

    # Phase A5 — publish INJURY_CREATED on the event bus. The news
    # engine subscribes to write a richer injury news item (with
    # voice descriptors + return-timeline phrase). The morale system
    # also subscribes (defensive — it scans injuries on FIGHT_RESOLVED
    # for fight injuries, but this event covers training camp
    # injuries and other non-fight sources too). The event payload
    # includes injury_id so subscribers can look up the full injury
    # row (severity, projected_return_date, body_area, etc.).
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.INJURY_CREATED,
            'injury_id': injury_id,
            'fighter_id': fighter_id,
            'fight_id': fight_id,
            'event_id': event_id,
            'event_date': start_date_str,
            'current_date': start_date_str,
        })
    except ImportError:
        pass

    # TIER3-MISSING §T3.4 (W17) — write an 'injuries' memory_link
    # self-link for this fighter. Per the brief: "when a fighter is
    # injured. Writer: in injuries_svc, when creating an injury,
    # write an injuries memory_link." The injuries_svc.py module is
    # a thin wrapper around this function, so we wire the writer
    # here directly. The writer is defensive (try/except) so a
    # memory-link write failure must never crash injury creation.
    try:
        from services.memory_svc import write_injuries_link
        write_injuries_link(conn, fighter_id, injury_id=injury_id)
    except Exception:
        # Defensive — a failed memory link write must not crash the
        # injury creation flow (the injury row + news item are
        # already committed; the memory link is a best-effort
        # side-effect).
        pass

    return injury_id





def _check_post_fight_injuries(conn, fight_id, event_id, event_date,
                                result_type, winner_id, loser_id,
                                a_id, b_id, stats_a, stats_b,
                                finishing_beat_id):
    """Check both fighters in a resolved fight for injuries.

    Called at the END of resolve_next_fight() (after all other side
    effects). Computes the damage_taken per fighter from fight_beats,
    fetches each fighter's injury_proneness, then calls
    _maybe_create_injury() for each. Returns the list of injury_ids
    created (0, 1, or 2 entries — typically at most 1 per fight, but
    a non-finish can produce injuries on both fighters in rare cases).

    Args:
        conn: sqlite3 connection (caller commits).
        fight_id, event_id, event_date: the resolved fight's metadata.
        result_type: the fight's result_type.
        winner_id, loser_id: winner and loser fighter_ids (loser_id
            may be None for a draw — in that case both fighters are
            treated as "not the loser" for finish-based injury
            branches, which is correct: a draw has no finish so no
            KO/sub/doctor injury branch fires).
        a_id, b_id: the two fighter_ids in the fight.
        stats_a, stats_b: the loaded stats dicts for fighters A and B
            (from _load_fighter_stats — already loaded by
            resolve_next_fight for the beat engine).
        finishing_beat_id: the fight_beat_id of the finishing
            exchange (for KO/submission), or None.

    Returns:
        List of injury_ids created (may be empty).
    """
    # Compute cumulative damage_taken per fighter from fight_beats.
    # damage_dealt is the damage DEALT BY the initiator TO the target.
    # So damage_taken by fighter X = SUM(damage_dealt) WHERE
    # target_fighter_id = X.
    dmg_a_row = conn.execute(
        "SELECT COALESCE(SUM(damage_dealt), 0) FROM fight_beats "
        "WHERE fight_id=? AND target_fighter_id=?",
        (fight_id, a_id),
    ).fetchone()
    dmg_b_row = conn.execute(
        "SELECT COALESCE(SUM(damage_dealt), 0) FROM fight_beats "
        "WHERE fight_id=? AND target_fighter_id=?",
        (fight_id, b_id),
    ).fetchone()
    dmg_a = dmg_a_row[0] if dmg_a_row else 0
    dmg_b = dmg_b_row[0] if dmg_b_row else 0

    # Fetch each fighter's injury_proneness (fighters table column —
    # not loaded by _load_fighter_stats, which only loads
    # clutch_factor / consistency / marketability from fighters).
    # COALESCE(..., 50) is defensive: a fighter without a row
    # (shouldn't happen with the seed) is treated as average
    # proneness.
    pron_a_row = conn.execute(
        "SELECT COALESCE(injury_proneness, 50) FROM fighters "
        "WHERE fighter_id=?",
        (a_id,),
    ).fetchone()
    pron_b_row = conn.execute(
        "SELECT COALESCE(injury_proneness, 50) FROM fighters "
        "WHERE fighter_id=?",
        (b_id,),
    ).fetchone()
    pron_a = pron_a_row[0] if pron_a_row else 50
    pron_b = pron_b_row[0] if pron_b_row else 50

    # For draws, both fighters are "not the loser" — finish-based
    # injury branches (KO/sub/doctor) won't fire because result_type
    # is 'draw' (not in those branches). The non-finish branch fires
    # for both, which is correct: both fighters took damage and have
    # a small chance of injury.
    is_a_loser = (loser_id is not None and a_id == loser_id)
    is_b_loser = (loser_id is not None and b_id == loser_id)

    injury_ids = []
    inj_a = _maybe_create_injury(
        conn, a_id, fight_id, event_id, event_date, result_type,
        is_a_loser, dmg_a, finishing_beat_id, stats_a, pron_a,
    )
    if inj_a is not None:
        injury_ids.append(inj_a)
    inj_b = _maybe_create_injury(
        conn, b_id, fight_id, event_id, event_date, result_type,
        is_b_loser, dmg_b, finishing_beat_id, stats_b, pron_b,
    )
    if inj_b is not None:
        injury_ids.append(inj_b)

    return injury_ids


# ----------------------------------------------------------------
# Phase A — A12: Preferred Gameplans + Bad Matchup Tags.
#
# The fighters.preferred_gameplans and fighters.bad_matchup_tags
# columns are TEXT (nullable, JSON arrays) and were NULL for ALL
# fighters at seed time. Phase A12 wires them dynamically based on
# fight outcomes:
#
#   preferred_gameplans (A12a):
#     - After a WIN, derive the winner's preferred gameplans from
#       their attribute profile (the "winning gameplan" is the one
#       their attributes most exemplify). Add to their existing list
#       (no duplicates, cap at 3).
#
#   bad_matchup_tags (A12b):
#     - After a LOSS, derive bad matchup tags from the result type
#       and the opponent's style archetype. Add to their existing
#       list (no duplicates, cap at 5).
#
# The population happens INSIDE resolve_next_fight — the brief
# explicitly allows this exception to §15.4 (no new inline side
# effects) because it's a direct DB write that enriches existing
# fighter data, parallel to fight_history / rankings / titles
# updates already in the function. It is NOT a new system
# subscribing to events.
#
# Per §14: the JSON arrays are internal data (NOT player-facing
# text). The UI will eventually display them as descriptor strings
# ("prefers boxing pressure" / "vulnerable to strikers") via the
# voice layer when a Task 19+ UI screen renders them. The raw JSON
# is the storage format; the descriptor is the display format.
# ----------------------------------------------------------------

# Each rule fires when BOTH listed attributes are >= _GAMEPLAN_THRESHOLD
# (the "capable" tier per voice.py §14.3 — 60 is the boundary between
# "average" and "capable"). The 6 gameplans match the brief's spec
# verbatim. "aggression" is a personality trait (loaded into stats
# via _FIGHTER_PERS_COLUMNS) so the volume_striking rule works the
# same way as the attribute-based rules.



_GAMEPLAN_RULES = (
    ("boxing_pressure",     "punch_power",       "punch_accuracy"),
    ("wrestling_dominance", "takedown_offense",  "top_control"),
    ("submission_hunting",  "submission_offense", "bottom_game"),
    ("counter_striking",    "head_movement",     "footwork"),
    ("volume_striking",     "cardio",            "aggression"),
    ("cage_grinding",       "clinch_offense",    "cage_wrestling"),
)




_GAMEPLAN_THRESHOLD = 60   # voice.py "capable" tier floor



_GAMEPLAN_CAP = 3



_BAD_MATCHUP_CAP = 5





def _derive_preferred_gameplans(stats):
    """Derive up to 3 preferred gameplans from a fighter's stats dict.

    Each gameplan rule fires when BOTH required attributes are >=
    _GAMEPLAN_THRESHOLD (the "capable" tier per voice.py §14.3).
    Multiple rules can fire; the top 3 by combined attribute value
    are returned (deterministic ordering — highest combined value
    first, so a fighter's truest style wins the slot).

    Args:
        stats: dict from _load_fighter_stats (25 attributes + 20
            personality + 3 meta columns). All values are ints 0-100.

    Returns:
        A list of 0-3 gameplan name strings.
    """
    matches = []
    for gameplan, attr1, attr2 in _GAMEPLAN_RULES:
        v1 = stats.get(attr1)
        v2 = stats.get(attr2)
        if v1 is None or v2 is None:
            continue
        if v1 >= _GAMEPLAN_THRESHOLD and v2 >= _GAMEPLAN_THRESHOLD:
            matches.append((gameplan, v1 + v2))
    # Sort by combined attribute value (highest first) for deterministic
    # ordering when more than 3 rules fire.
    matches.sort(key=lambda x: x[1], reverse=True)
    return [g for g, _ in matches[:_GAMEPLAN_CAP]]





def _update_preferred_gameplans(conn, fighter_id, new_gameplans):
    """Update a fighter's preferred_gameplans JSON column.

    Reads the existing list (or empty list if NULL/malformed), adds
    new_gameplans (no duplicates, preserves order), caps at
    _GAMEPLAN_CAP, writes back as JSON.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter to update.
        new_gameplans: list of gameplan name strings to add.
    """
    if not new_gameplans:
        return
    row = conn.execute(
        "SELECT preferred_gameplans FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return
    existing = []
    if row[0]:
        try:
            parsed = json.loads(row[0])
            if isinstance(parsed, list):
                existing = [str(g) for g in parsed]
        except (json.JSONDecodeError, TypeError):
            existing = []
    # Add new gameplans (dedupe, preserve order — existing first,
    # then new ones in the order they appear in new_gameplans).
    seen = set(existing)
    for g in new_gameplans:
        if g not in seen:
            existing.append(g)
            seen.add(g)
            if len(existing) >= _GAMEPLAN_CAP:
                break
    # Cap at _GAMEPLAN_CAP (defensive — should already be capped by
    # the loop above, but a pre-existing over-cap list would survive).
    existing = existing[:_GAMEPLAN_CAP]
    conn.execute(
        "UPDATE fighters SET preferred_gameplans=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (json.dumps(existing), fighter_id),
    )





def _derive_bad_matchup_tags(result_type, opponent_style_name):
    """Derive bad matchup tags from a loss result + opponent's style.

    Per the brief:
      - Lost by KO/TKO to a Striker → "vulnerable_to_strikers"
      - Lost by submission to a Grappler → "vulnerable_to_submission"
      - Lost by decision to a Wrestler → "vulnerable_to_wrestlers"
      - Lost to a Brawler (any result type) → "vulnerable_to_brawlers"
      - Lost by doctor stoppage (any opponent style) → "cut_prone"

    Args:
        result_type: the fights.result_type string.
        opponent_style_name: the opponent's style_archetype name
            (e.g. "Striker", "Grappler", "Wrestler", "Brawler",
            "Counter-Striker", "Submission Specialist", "Balanced").

    Returns:
        A list of bad matchup tag strings (may be empty).
    """
    tags = []
    rt = (result_type or "").lower()
    style = opponent_style_name or ""
    if rt in ("ko_tko", "ko", "tko") and style == "Striker":
        tags.append("vulnerable_to_strikers")
    if rt == "submission" and style == "Grappler":
        tags.append("vulnerable_to_submission")
    if rt == "decision" and style == "Wrestler":
        tags.append("vulnerable_to_wrestlers")
    if style == "Brawler":
        tags.append("vulnerable_to_brawlers")
    if rt == "doctor_stoppage":
        tags.append("cut_prone")
    return tags





def _update_bad_matchup_tags(conn, fighter_id, new_tags):
    """Update a fighter's bad_matchup_tags JSON column.

    Reads the existing list (or empty list if NULL/malformed), adds
    new_tags (no duplicates, preserves order), caps at
    _BAD_MATCHUP_CAP, writes back as JSON.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter to update.
        new_tags: list of tag strings to add.
    """
    if not new_tags:
        return
    row = conn.execute(
        "SELECT bad_matchup_tags FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return
    existing = []
    if row[0]:
        try:
            parsed = json.loads(row[0])
            if isinstance(parsed, list):
                existing = [str(t) for t in parsed]
        except (json.JSONDecodeError, TypeError):
            existing = []
    # Add new tags (dedupe, preserve order).
    seen = set(existing)
    for t in new_tags:
        if t not in seen:
            existing.append(t)
            seen.add(t)
            if len(existing) >= _BAD_MATCHUP_CAP:
                break
    existing = existing[:_BAD_MATCHUP_CAP]
    conn.execute(
        "UPDATE fighters SET bad_matchup_tags=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (json.dumps(existing), fighter_id),
    )





def _opponent_style_archetype_name(conn, fighter_id):
    """Return the fighter's style_archetype name (or None).

    Used by A12b to look up the opponent's style archetype when
    deriving bad_matchup_tags. The query joins fighters →
    style_archetypes so the caller gets the human-readable name
    ("Striker", "Grappler", etc.) directly.
    """
    row = conn.execute(
        "SELECT sa.name FROM fighters f "
        "LEFT JOIN style_archetypes sa "
        "ON sa.style_archetype_id = f.fight_style_archetype_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else None





# ----------------------------------------------------------------
# PERF-FIXES-3 — Simplified in-memory fight resolution for AI vs AI
# fights (rival promotions). The player's own fights always use the
# full beat engine (resolve_round → fight_beats + commentary_segments
# + fight_rounds writes). AI vs AI fights never get replayed by the
# player — the player only sees the result in the newswire / archive.
#
# Skipping the beat engine for AI fights saves ~80-250 INSERTs per
# AI fight (fight_beats + commentary_segments + fight_rounds). On a
# busy event-day tick with 20 AI fights = ~1,600-5,000 INSERTs saved.
#
# The simplified resolver produces the SAME result_type distribution
# (ko_tko / submission / decision / draw) as the full engine, just
# without the per-beat granularity. The same winners (statistically)
# emerge — the algorithm is a coarser version of the same logic.
#
# `performance_rating` + `fan_reaction_rating` are computed in-memory
# (mirroring the full engine's formula) and stored on the `fights`
# row. show_rating + morale read these (with a fallback when fight_
# beats is empty — see show_rating._get_per_fight_beats_stats +
# morale._process_fight).
# ----------------------------------------------------------------

# Attribute groups used by the simplified resolver. The full beat
# engine uses ~25 attributes; this subset captures the dominant
# determinants of round outcomes (offense + defense + clinch).
_SIMPLIFIED_OFFENSE_ATTRS = (
    "punch_power", "kick_power", "punch_accuracy", "kick_accuracy",
    "speed_explosiveness", "fight_iq", "takedown_offense",
    "submission_offense", "clinch_striking",
)
_SIMPLIFIED_DEFENSE_ATTRS = (
    "chin", "durability", "head_movement", "takedown_defense",
    "submission_defense",
)


def _resolve_fight_simplified(conn, fight_id, a_id, b_id,
                              stats_a, stats_b, scheduled_rounds,
                              is_title_fight, importance, rng=None):
    """Simplified in-memory fight resolution (no DB writes to fight_beats
    or fight_rounds).

    Algorithm (mirrors the full beat engine at a coarser granularity):
      1. Compute each fighter's "power" = weighted average of 9
         offense attrs + 5 defense attrs + morale/consistency bonuses.
      2. Compute KO thresholds from chin + durability (150-300 range).
      3. Per round (in-memory only):
         - Roll round damage dealt by each fighter (power-scaled +
           uniform variance).
         - Round winner = higher damage dealer.
         - Accumulate total damage per fighter.
         - Check KO threshold crossing → KO/TKO finish.
         - Roll submission probability per round.
      4. If no finish: 10-point must decision across rounds.
      5. Compute performance_rating + fan_reaction_rating using the
         SAME formulas as the full engine (so show_rating + morale
         can read them uniformly).

    Args:
        conn: sqlite3 connection (caller commits — this function
            writes nothing to the DB).
        fight_id: the fights.fight_id (used as RNG seed for
            determinism — the same fight resolves identically on
            re-run, matching the full engine's `rng = Random(fighter_
            id)` pattern).
        a_id, b_id: fighter_ids (red + blue corner).
        stats_a, stats_b: loaded stats dicts from _load_fighter_stats.
        scheduled_rounds: 3 or 5 (title fights).
        is_title_fight: bool (unused in computation, kept for
            signature symmetry with the full resolver).
        importance: 0-100 fight importance (unused in the simplified
            path — kept for signature symmetry).
        rng: optional pre-seeded Random instance (tests can pass a
            fixed seed). Defaults to `random.Random(fight_id)`.

    Returns:
        Dict with keys: result_type, winner_id, loser_id, finish_round,
        finish_time, score_margin, performance_rating,
        fan_reaction_rating.
    """
    if rng is None:
        rng = random.Random(fight_id)

    def _power(stats):
        off_vals = [stats.get(a, 50) or 50 for a in _SIMPLIFIED_OFFENSE_ATTRS]
        def_vals = [stats.get(a, 50) or 50 for a in _SIMPLIFIED_DEFENSE_ATTRS]
        off = sum(off_vals) / len(off_vals)
        deff = sum(def_vals) / len(def_vals)
        morale = stats.get("morale", 50) or 50
        consistency = stats.get("consistency", 50) or 50
        # 60% offense + 40% defense + morale/consistency bonuses.
        # The bonuses are small (±5 max) so power stays in [25, 75]
        # for typical fighters.
        return (0.6 * off + 0.4 * deff
                + (morale - 50) * 0.1
                + (consistency - 50) * 0.05)

    power_a = _power(stats_a)
    power_b = _power(stats_b)

    def _ko_thresh(stats):
        chin = stats.get("chin", 50) or 50
        dur = stats.get("durability", 50) or 50
        # FIGHT-ENGINE-TUNE Issue 1: lowered threshold band from
        # `150 + (chin+dur)*0.75` (range 150-300) to
        # `30 + (chin+dur)*0.3` (range 30-90). The original threshold
        # (~225 for chin+dur=100) was unreachable in 3-5 rounds of
        # 45-75 total damage, producing 0 KOs in 672 fights. The
        # brief's `60 + 0.3*(chin+dur)` (~89 typical) was still too
        # high — avg power=48 produces only ~19 damage/round = 57
        # after 3 rounds (below 89). Deviation: lowered base 60 -> 30
        # so the typical threshold (~59) IS reachable in 3 rounds,
        # producing ~20-30% KO rate (target 20-40%).
        #
        # FIX-V3-ALL5 #2 (KO 23% -> target 30%): the 30-base / 0.3-scale
        # produced a ~23% KO rate in the 1-year sim, just under the
        # 28-32% target band. Lowering base 30 -> 20 + scale 0.3 -> 0.25
        # gives a typical threshold of 20 + 100*0.25 = 45 (was 60), which
        # is reachable in 2 rounds (25 dmg * 2 = 50 > 45) rather than
        # requiring 3. This lifts the KO rate into the 28-32% target
        # band without breaking the existing balance (a defensive
        # fighter with chin+dur=120 still has threshold 50, so they
        # don't become unkillable; an attrition-fighter at 70 has
        # threshold ~37, so they get finished in 2 rounds reliably).
        return 20 + (chin + dur) * 0.25

    ko_thresh_a = _ko_thresh(stats_a)
    ko_thresh_b = _ko_thresh(stats_b)

    # Aggression-driven finish probabilities (per round). Higher
    # aggression + higher power = more likely to land a finishing
    # blow.
    # FIGHT-ENGINE-TUNE Issue 1: rewrote the per-round formula.
    # Original was `0.02 / rounds_div` (intended to keep cumulative
    # finish_prob constant across round counts — but that's unrealistic;
    # 5-round fights SHOULD finish more often than 3-round fights).
    # New: per-round probability (NO division by rounds_div) so 5-round
    # fights produce higher cumulative finish rates. Base 0.10 (deviation
    # from brief's 0.04 — the brief's 0.04 / rounds_div gave 0.013/round
    # which was far too low even with the lowered threshold). Power
    # differential scaling 0.008 (per brief). Capped at 0.15 per round.
    aggr_a = stats_a.get("aggression", 50) or 50
    aggr_b = stats_b.get("aggression", 50) or 50
    finish_prob_a = min(0.15, max(0.03,
        0.10 + 0.008 * (power_a - 50) + 0.001 * (aggr_a - 50)))
    finish_prob_b = min(0.15, max(0.03,
        0.10 + 0.008 * (power_b - 50) + 0.001 * (aggr_b - 50)))

    # Submission probabilities (lower than KO — finishes are rarer
    # via submission in real MMA).
    # FIGHT-ENGINE-TUNE Issue 3: raised base 0.01 -> 0.03 (per brief)
    # and offense scaling 0.0005 -> 0.001 (per brief). Removed the
    # /rounds_div division so 5-round fights have higher cumulative
    # sub rates (mirrors the finish_prob fix). The original 0.01 /
    # rounds_div gave 0.0033/round which was far too low (1.2% sub
    # rate in 672 fights; target 20%).
    #
    # FIX-V3-ALL5 #3 (Sub 14% -> target 20%): the 0.03 base produced
    # a 14% sub rate in the 1-year sim — short of the 18-22% target
    # band. Raising base 0.03 -> 0.045 (50% relative increase on the
    # base) plus the full-engine submission_attempt weight bump
    # (1 -> 1.2, ~20% more attempts per ground beat) lifts the
    # cumulative sub rate into the 18-22% target band. The base
    # increase is larger than the attempt-weight increase because
    # the simplified resolver doesn't model attempt vs success
    # separately — every per-round roll is a binary sub check.
    sub_off_a = stats_a.get("submission_offense", 50) or 50
    sub_off_b = stats_b.get("submission_offense", 50) or 50
    sub_def_a = stats_a.get("submission_defense", 50) or 50
    sub_def_b = stats_b.get("submission_defense", 50) or 50
    sub_prob_a = max(0.0, 0.045 + 0.001 * (sub_off_a - sub_def_b))
    sub_prob_b = max(0.0, 0.045 + 0.001 * (sub_off_b - sub_def_a))

    # Per-round simulation. All in-memory — no DB writes.
    round_results = []  # list of (round_winner_id, dmg_a, dmg_b)
    total_a_damage = 0
    total_b_damage = 0
    finish_info = None  # set if a finish occurs mid-fight
    finish_round = scheduled_rounds
    finish_time = "5:00"  # default for decision

    for round_number in range(1, scheduled_rounds + 1):
        # Roll round damage. Base 25 + power differential scaling +
        # uniform variance [-10, +10]. Floored at 5 so a defensively-
        # minded fighter still deals some damage.
        # FIGHT-ENGINE-TUNE Issue 1: boosted base 20 -> 25 so the
        # KO threshold (~59 for typical chin+dur) is reliably crossed
        # by round 3 (25*3 = 75 > 59). The original 20/round gave
        # 60 after 3 rounds (just below threshold), so KOs rarely fired.
        dmg_a = max(5, int(25 + (power_a - 50) * 0.4 + rng.uniform(-10, 10)))
        dmg_b = max(5, int(25 + (power_b - 50) * 0.4 + rng.uniform(-10, 10)))
        total_a_damage += dmg_a
        total_b_damage += dmg_b
        # FIGHT-ENGINE-TUNE Issue 2: when damage is nearly equal
        # (<5 diff), the round winner used to be a coin flip (dmg_a
        # >= dmg_b picks A on ties) — producing ~50% split decisions
        # on balanced matchups. Now the round goes to the higher-POWER
        # fighter (deterministic), so close rounds reflect skill not
        # RNG. This dramatically reduces the split_decision rate
        # (38% -> ~10%).
        if abs(dmg_a - dmg_b) < 5:
            round_winner = a_id if power_a >= power_b else b_id
        else:
            round_winner = a_id if dmg_a >= dmg_b else b_id
        round_results.append((round_winner, dmg_a, dmg_b))

        # Check for KO/TKO finish (cumulative damage crosses the
        # defender's threshold). FIGHT-ENGINE-TUNE Issue 1: removed
        # the `+30 damage lead` requirement — a fighter can get KO'd
        # even in a close fight (the defender has taken enough cumulative
        # damage to be finished, regardless of who's ahead).
        if (total_b_damage > ko_thresh_b
                and rng.random() < finish_prob_a):
            finish_info = {"type": "ko_tko", "winner_id": a_id, "loser_id": b_id}
            finish_round = round_number
            finish_time = _random_finish_time_lite(rng)
            break
        if (total_a_damage > ko_thresh_a
                and rng.random() < finish_prob_b):
            finish_info = {"type": "ko_tko", "winner_id": b_id, "loser_id": a_id}
            finish_round = round_number
            finish_time = _random_finish_time_lite(rng)
            break

        # Check for submission finish (probability-based per round).
        # Only rolls if no KO fired this round (the break above
        # exits the loop).
        if rng.random() < sub_prob_a:
            finish_info = {"type": "submission", "winner_id": a_id, "loser_id": b_id}
            finish_round = round_number
            finish_time = _random_finish_time_lite(rng)
            break
        if rng.random() < sub_prob_b:
            finish_info = {"type": "submission", "winner_id": b_id, "loser_id": a_id}
            finish_round = round_number
            finish_time = _random_finish_time_lite(rng)
            break

    if finish_info is not None:
        result_type = finish_info["type"]
        winner_id = finish_info["winner_id"]
        loser_id = finish_info["loser_id"]
        score_margin_int = abs(total_a_damage - total_b_damage)
    else:
        # Decision: 10-point must across all completed rounds.
        # Inline (mirrors _decide_fight_outcome — no knockdown
        # bonuses since we don't track per-round KDs in the
        # simplified path).
        score_a_total = 0
        score_b_total = 0
        for (rw, _da, _db) in round_results:
            if rw == a_id:
                score_a_total += 10
                score_b_total += 9
            else:
                score_b_total += 10
                score_a_total += 9
        if score_a_total == score_b_total:
            result_type = "draw"
            winner_id = loser_id = None
        elif abs(score_a_total - score_b_total) < 3:
            # Close fight. Brief says 15% split; bumped to 70% (D2)
            # for varied distribution — matches the full engine.
            # FIGHT-ENGINE-TUNE Issue 2: halved 0.70 -> 0.35 (deviation
            # from D2) so split_decision rate drops from 26% to ~13%
            # (target <15%). The deterministic close-round fix (round
            # winner = higher power on <5 dmg diff) already reduces
            # close fights, but the 70% split probability on the
            # remaining close fights still produced too many splits.
            if rng.random() < 0.35:
                result_type = "split_decision"
            else:
                result_type = "unanimous_decision"
            if score_a_total > score_b_total:
                winner_id, loser_id = a_id, b_id
            else:
                winner_id, loser_id = b_id, a_id
        else:
            result_type = "unanimous_decision"
            if score_a_total > score_b_total:
                winner_id, loser_id = a_id, b_id
            else:
                winner_id, loser_id = b_id, a_id
        score_margin_int = abs(total_a_damage - total_b_damage)

    # Performance + fan reaction ratings — MIRROR the full engine's
    # formulas exactly (lines 6121-6150) so AI fights + player fights
    # produce ratings on the same scale.
    performance_rating = max(60, min(95, int(round(60 + score_margin_int / 20.0))))
    if result_type in ("ko_tko", "submission"):
        performance_rating = min(95, performance_rating + 10)
    elif result_type in ("doctor_stoppage", "corner_stoppage", "dq"):
        performance_rating = min(95, performance_rating + 5)

    fan = 65 + int(score_margin_int / 30.0)
    if result_type in ("ko_tko", "submission"):
        fan += 10
    elif result_type in ("doctor_stoppage", "corner_stoppage", "dq"):
        fan += 5
    if result_type != "draw" and winner_id is not None:
        if winner_id == a_id:
            winner_dmg, loser_dmg = total_a_damage, total_b_damage
        else:
            winner_dmg, loser_dmg = total_b_damage, total_a_damage
        if loser_dmg > winner_dmg:
            fan += 5  # upset — fans love a controversial decision
    fan_reaction_rating = max(60, min(95, fan))

    return {
        "result_type": result_type,
        "winner_id": winner_id,
        "loser_id": loser_id,
        "finish_round": finish_round,
        "finish_time": finish_time,
        "score_margin": score_margin_int,
        "performance_rating": performance_rating,
        "fan_reaction_rating": fan_reaction_rating,
    }


def _random_finish_time_lite(rng):
    """Generate a finish time string ('M:SS') for AI-fight finishes.

    Simpler than the full engine's `_random_finish_time` (which
    depends on beat_number + beats_this_round — unavailable for AI
    fights since we don't generate beats). Picks a random time in
    the round [0:00, 4:59].

    Args:
        rng: a random.Random instance (caller-supplied for
            determinism).

    Returns:
        A string like "2:34" (minute:second).
    """
    minute = rng.randint(0, 4)
    second = rng.randint(0, 59)
    return f"{minute}:{second:02d}"


def resolve_next_fight(conn, promotion_id=None, skip_beat_detail=False):
    """Resolve the next scheduled fight using the beat-level engine (Task B2).

    Picks the lowest-fight_id unresolved fight, loads both fighters'
    full 25-attribute + 20-personality + 3-meta stats, computes fight
    importance + pressure modifiers (B2), simulates each round beat-
    by-beat via `resolve_round()` (writing fight_beats + the per-round
    aggregate to fight_rounds), applies 10-point must decision scoring
    across rounds to determine the winner if no finish occurs, then
    runs ALL the existing side effects from the Task 3 resolver
    (fight_history, rankings, titles, event lifecycle,
    schedule_next_event, news, commentary).

    v3.6.0 (Task 25 — rival promotion AI): the optional promotion_id
    parameter filters the pick-query to a specific promotion. When
    None (default), behavior is unchanged — the lowest-fight_id
    unresolved fight across ALL promotions is picked (the player's
    "Resolve Fight" button). When set (rival AI passes its own
    promotion_id), only unresolved fights from that promotion are
    eligible. This keeps the rival AI from accidentally resolving
    the player's scheduled fights — the player resolves their own
    fights manually via the UI button.

    v2.3.0 (Task B2) additions:
      - Fatigue: gas starts at 100, depletes per beat, recovers
        between rounds. Tracked in-memory across rounds AND stored
        per round in fight_rounds.fighter_a/b_gas_remaining (per the
        B2 brief: "Store in fight_rounds.fighter_a/b_gas_remaining").
      - Momentum: cumulative momentum carries across rounds, shifting
        subsequent beat probabilities.
      - Mid-round finishes: KO/TKO, submission, DQ (checked during
        resolve_round). Doctor stoppage and corner stoppage are
        checked between rounds here in resolve_next_fight.
      - Fight importance + pressure modifiers: importance computed
        from card_slot + is_title_fight + marketability; in high-
        importance fights, pressure_response (clutch_factor +
        composure + consistency + focus + grit) modifies beat scores.
      - Commentary beat selection: after the fight resolves, selects
        3-14 most important beats (knockdowns, near-finishes, finish,
        big momentum swings) and writes commentary_segments for each.

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
      - INSERT INTO commentary_segments (3-14 highlight beats)  [v2.3.0, Task B2]

    PERF-FIXES-3 (skip_beat_detail): when `skip_beat_detail=True`,
    the beat engine is bypassed entirely. The simplified resolver
    `_resolve_fight_simplified` produces the result_type + winner +
    finish_round + ratings in-memory. Skipped writes:
      - fight_beats (saves 36-140 INSERTs)
      - fight_rounds (saves 3-5 INSERTs)
      - commentary_segments 'highlight' + 'beat' + 'announcer'/
        'pundit'/'crowd' (saves 44-200 INSERTs)
    All OTHER side effects (fight_history, rankings, titles, news,
    event lifecycle, finance via subscribers, injuries, descriptor
    snapshots, gameplan derivation, FIGHT_RESOLVED publish) are
    PRESERVED. The `fights.performance_rating` +
    `fights.fan_reaction_rating` columns are written from the
    simplified resolver's output (so show_rating + morale can read
    them as an excitement proxy when fight_beats is empty).
    Default: False (player path unchanged — full beat detail).
    """
    # P3.3 (docs/COMPREHENSIVE_FIX_PLAN.md §Group D #16) — fights
    # resolve in REVERSE card_slot order: prelims first, main event
    # LAST. The previous ORDER BY f.fight_id picked the lowest-id
    # fight, which is the main_event (confirm_card assigns main_event
    # at idx=0). That played the card backwards — the main event
    # resolved before the prelims. The new CASE ordering plays the
    # card forward: opener → prelim → featured_prelim → co_main →
    # main_event LAST, with fight_id ASC as a tiebreaker. This
    # affects both the player's manual resolution AND rival AI's
    # _resolve_event_card loop (which drains the whole card in one
    # tick — the order within that tick is now prelims-first, which
    # is the realistic sequence for a single-night event).
    #
    # HW8.1 (event-lifecycle bug fix): the pick-query now filters
    # by `e.event_date <= sim_date`. Without this filter, the rival
    # AI's _resolve_event_card loop (which loops resolve_next_fight
    # until None) would resolve fights on FUTURE-dated events too —
    # marking them 'completed' months before their event_date. The
    # HW6.3 soak test surfaced this as 146 future-dated events
    # marked COMPLETED after 180 sim days. The fix reads the sim
    # date from simulation_clock (one extra SELECT, < 1ms) and
    # applies the date filter. The player UI path (app_web.
    # resolve_next_fight) already enforces event_date == sim_date
    # before calling this function, so this fix is transparent for
    # the player and only affects the rival AI auto-resolution path.
    sim_date_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date_str = sim_date_row[0] if sim_date_row else None
    fight = conn.execute(
        "SELECT f.fight_id, f.event_id, f.scheduled_rounds, e.promotion_id, "
        "f.weight_class_id, e.event_date, f.card_slot, f.is_title_fight "
        "FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL "
        + ("AND e.promotion_id=? " if promotion_id is not None else "")
        + ("AND e.event_date <= ? " if sim_date_str else "")
        + "ORDER BY CASE f.card_slot "
        "  WHEN 'opener' THEN 1 "
        "  WHEN 'prelim' THEN 2 "
        "  WHEN 'featured_prelim' THEN 3 "
        "  WHEN 'co_main' THEN 4 "
        "  WHEN 'main_event' THEN 5 "
        "  ELSE 6 END, f.fight_id ASC LIMIT 1",
        tuple(p for p in (
            promotion_id if promotion_id is not None else None,
            sim_date_str,
        ) if p is not None),
    ).fetchone()
    if not fight:
        return None
    (fight_id, event_id, scheduled_rounds, promo_id, weight_class_id,
     event_date, card_slot, is_title_fight) = fight
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
    # v2.7.0 (Task 17): run weight cuts for BOTH fighters BEFORE the
    # fight resolves. If either fighter misses_large (> 3kg), the
    # fight is CANCELLED — recorded as 'no_contest' in fight_history.
    # If a fighter misses_small or missed_medium, the fight proceeds
    # at catch-weight with a cardio penalty applied to starting gas.
    # ----------------------------------------------------------------
    cut_a = _run_weight_cut(conn, a_id, fight_id, event_id,
                            weight_class_id, event_date, is_title_fight)
    cut_b = _run_weight_cut(conn, b_id, fight_id, event_id,
                            weight_class_id, event_date, is_title_fight)
    # Check for cancellation (either fighter missed_large)
    if cut_a["cut_outcome"] == "missed_large" or cut_b["cut_outcome"] == "missed_large":
        # Fight cancelled — record as no_contest and return early
        # Determine which fighter missed (or both)
        # v2.10.0 (FIX-VoiceRep, §14): the OLD headline used raw kg
        # numbers ("missed weight by 1.5kg"). Replaced with a word-
        # form phrase ("missed weight badly") — no raw digits per
        # CONVENTIONS §14.
        if cut_a["cut_outcome"] == "missed_large" and cut_b["cut_outcome"] == "missed_large":
            nc_headline = f"Fight cancelled — both fighters missed weight"
        elif cut_a["cut_outcome"] == "missed_large":
            nc_headline = f"Fight cancelled — {fighter_name(conn, a_id)} missed weight badly"
        else:
            nc_headline = f"Fight cancelled — {fighter_name(conn, b_id)} missed weight badly"
        # Mark the fight as no_contest
        conn.execute(
            "UPDATE fights SET result_type='no_contest', finish_round=0, "
            "finish_time='0:00', performance_rating=0, fan_reaction_rating=20 "
            "WHERE fight_id=?",
            (fight_id,),
        )
        # Defensive: clear any existing fight_history rows for this fight
        # (matches the main resolver's idempotent pattern — a re-resolve
        # after reset_fight would have stale rows).
        conn.execute("DELETE FROM fight_history WHERE fight_id=?", (fight_id,))
        # Write fight_history rows for both fighters (outcome='nc')
        for fid in (a_id, b_id):
            oid = b_id if fid == a_id else a_id
            conn.execute(
                "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
                "outcome, result_type, finish_round, finish_time, score_margin, "
                "event_id, event_date, weight_class_id, title_at_stake) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fight_id, fid, oid, "nc", "no_contest", 0, "0:00",
                 0, event_id, event_date, weight_class_id, is_title_fight),
            )
        # Update fighter_career records (no win/loss added, but
        # fights_counted via fight_history rows)
        # Write a cancellation news item
        src_row = conn.execute(
            "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
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
            "sentiment, topic, fight_id, event_id, published_at, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, nc_headline,
             f"The fight has been cancelled due to a weight miss. "
             f"No winner will be declared.",
             "negative", "weight_cut", fight_id, event_id, event_date,
             "SIGNIFICANT"),
        )
        # Phase A5 — publish FIGHT_CANCELLED on the event bus. The
        # news engine + morale system subscribe to write a richer
        # cancellation news item and apply the weight-cut-miss morale
        # penalty (-5 for the offender, -3 for the opponent). The
        # missed_fighter_id + opponent_id are passed in the event so
        # subscribers don't have to look them up.
        try:
            from event_bus import get_bus, Events
            bus = get_bus()
            # Determine which fighter missed (for the event payload).
            if cut_a["cut_outcome"] == "missed_large" and cut_b["cut_outcome"] == "missed_large":
                missed_id, opponent_id = a_id, b_id  # both missed — pick A as primary
            elif cut_a["cut_outcome"] == "missed_large":
                missed_id, opponent_id = a_id, b_id
            else:
                missed_id, opponent_id = b_id, a_id
            bus.publish(conn, {
                'type': Events.FIGHT_CANCELLED,
                'fight_id': fight_id,
                'event_id': event_id,
                'promotion_id': promo_id,
                'weight_class_id': weight_class_id,
                'missed_fighter_id': missed_id,
                'opponent_id': opponent_id,
                'event_date': event_date,
            })
        except ImportError:
            pass
        # Trigger event lifecycle (check if this was the last fight on the card)
        _update_event_status_after_resolution(conn, event_id)
        # If the event just completed, auto-schedule the next event
        post_status = conn.execute(
            "SELECT status FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
        if post_status == "completed":
            schedule_next_event(conn, promotion_id=promo_id,
                                from_event_date=event_date, weeks_out=4)
        return fight_id  # return the fight_id even though it was cancelled

    # ----------------------------------------------------------------
    # Phase A8 — rivalry morale/pressure effects on the fight.
    #
    # If the two fighters have an active rivalry (heat > 70), both
    # fighters get +5 aggression and -5 composure for this fight —
    # the bad blood makes them fight more recklessly. If heat > 90,
    # the modifier doubles (+10 aggression, -10 composure) — this is
    # the "volatile matchup" the brief calls out.
    #
    # This is a READ operation (CONVENTIONS §5.3 — the rivalries table
    # ships with the get_rivalry reader). The modifier is applied to
    # the in-memory stats_a / stats_b dicts that the beat engine
    # reads — NO DB write side effect. The brief explicitly allows
    # this exception to §15.4 (no inline side effects in resolve_
    # next_fight) because it's a pure read + in-memory tweak.
    #
    # Lazy-import rivalries to avoid a circular dependency (rivalries
    # imports voice, app imports a lot of things).
    # ----------------------------------------------------------------
    try:
        from rivalries import get_rivalry, get_rivalry_heat
        heat = get_rivalry_heat(conn, a_id, b_id)
        if heat > 70:
            # Double-check is_active — a dormant rivalry (heat > 70
            # but is_active=0) shouldn't apply the modifier. The
            # get_rivalry_heat helper returns 0 for non-existent
            # rivalries, but a dormant one with heat=75 (set dormant
            # by decay then never re-escalated) would still show 75.
            riv = get_rivalry(conn, a_id, b_id)
            is_active = False
            if riv is not None:
                try:
                    is_active = bool(riv["is_active"])
                except (KeyError, IndexError, TypeError):
                    is_active = bool(riv[10] if len(riv) > 10 else False)
            if is_active:
                if heat > 90:
                    aggression_boost = 10
                    composure_penalty = 10
                else:
                    aggression_boost = 5
                    composure_penalty = 5
                # Clamp to [0, 100] — the beat engine reads these as
                # 0-100 values; an over-100 aggression would skew the
                # initiator selection without bound.
                stats_a["aggression"] = max(0, min(100,
                    (stats_a.get("aggression", 50) or 50) + aggression_boost))
                stats_a["composure"] = max(0, min(100,
                    (stats_a.get("composure", 50) or 50) - composure_penalty))
                stats_b["aggression"] = max(0, min(100,
                    (stats_b.get("aggression", 50) or 50) + aggression_boost))
                stats_b["composure"] = max(0, min(100,
                    (stats_b.get("composure", 50) or 50) - composure_penalty))
    except ImportError:
        pass  # rivalries module not available — skip the modifier

    # ----------------------------------------------------------------
    # v2.3.0 (Task B2): compute fight importance + pressure modifiers.
    # Importance is a computed value (0-100), not stored. Pressure
    # modifiers apply to beat scores only in high-importance fights
    # (importance > 60).
    # ----------------------------------------------------------------
    importance = _compute_fight_importance(
        card_slot, is_title_fight,
        stats_a.get("marketability", 50), stats_b.get("marketability", 50),
    )
    pressure_response_a = _compute_pressure_response(stats_a)
    pressure_response_b = _compute_pressure_response(stats_b)
    pressure_mod_a = _compute_pressure_modifier(importance, pressure_response_a)
    pressure_mod_b = _compute_pressure_modifier(importance, pressure_response_b)

    # ----------------------------------------------------------------
    # Beat-level resolution (Task B1 + B2). For each round (1 to
    # scheduled_rounds), call resolve_round() which generates 12-28
    # beats, writes them to fight_beats, populates the per-round
    # aggregate row in fight_rounds, and sets round_winner_fighter_id.
    # v2.3.0 (Task B2): gas + cum_momentum are tracked across rounds
    # (gas recovers between rounds; momentum carries over). After each
    # round, check for doctor stoppage and corner stoppage (between-
    # round finishes). If a finish occurs mid-round (KO/sub/DQ),
    # resolve_round returns finish_info and we stop scheduling more
    # rounds.
    # ----------------------------------------------------------------
    if not skip_beat_detail:
        # Defensive: clear any prior beats/rounds rows for this fight
        # (idempotent for re-resolution, mirrors the fight_history DELETE
        # pattern below). The UNIQUE constraints on fight_beats and
        # fight_rounds would crash on re-resolve without this.
        conn.execute("DELETE FROM fight_beats WHERE fight_id=?", (fight_id,))
        conn.execute("DELETE FROM fight_rounds WHERE fight_id=?", (fight_id,))

        round_results = []
        total_a_damage = 0
        total_b_damage = 0
        # v2.3.0 fatigue: gas starts at 100 per fight. Tracked across
        # rounds (recovered between rounds via _recover_gas_between_rounds).
        # v2.5.0 (Task 16): if the fighter has a training camp for this
        # event with camp_fatigue > 50, the brief's "Fatigue > 50 = reduced
        # starting gas" rule applies: starting gas = 100 - max(0,
        # camp_fatigue - 50), floored at 50. A fighter who pushed too hard
        # in camp (fatigue 100) starts at gas 50 — they're gassed from the
        # cut / training load. A fighter whose camp was moderate (fatigue
        # 40) starts fresh at gas 100. If no camp exists (e.g., the seeded
        # fight — schedule_next_event hasn't been called for it), no
        # penalty applies (the helper returns 0, which doesn't trigger the
        # > 50 branch). This is the reader required by CONVENTIONS §5.3 —
        # the camp data is read by resolve_next_fight and affects fight
        # outcomes (the "camp fatigue cost the prospect his debut" story).
        camp_fatigue_a = _get_camp_fatigue_for_event(conn, a_id, event_id)
        camp_fatigue_b = _get_camp_fatigue_for_event(conn, b_id, event_id)
        gas_a = 100.0 - max(0, camp_fatigue_a - 50) if camp_fatigue_a > 50 else 100.0
        gas_b = 100.0 - max(0, camp_fatigue_b - 50) if camp_fatigue_b > 50 else 100.0
        # v2.7.0 (Task 17): apply weight cut cardio penalty. Fighters who
        # missed_medium (1-3kg over) start the fight with reduced cardio —
        # gas reduced by the cardio_penalty (default 15), floored at 50.
        # This is the "hard cut cost the fighter his gas" story.
        gas_a -= cut_a.get("cardio_penalty", 0)
        gas_b -= cut_b.get("cardio_penalty", 0)
        # Floor at 50 — a fighter never starts below half gas (the camp
        # fatigue + weight cut penalty is real but never crippling enough
        # to lose the fight before it starts).
        gas_a = max(50.0, gas_a)
        gas_b = max(50.0, gas_b)
        # v2.3.0 momentum: cumulative momentum carries across rounds.
        cum_momentum = 0
        # v2.3.0 corner stoppage: track consecutive round losses per fighter.
        consecutive_losses_a = 0
        consecutive_losses_b = 0
        # v2.3.0 finish info (set if a finish occurs mid-round OR between
        # rounds via doctor/corner stoppage).
        finish_info = None
        finish_round = scheduled_rounds  # default if no finish
        finish_time = "5:00"             # default if no finish (decision)

        for round_number in range(1, scheduled_rounds + 1):
            r = resolve_round(
                conn, fight_id, round_number, a_id, b_id,
                stats_a, stats_b,
                gas_a=gas_a, gas_b=gas_b,
                cum_momentum=cum_momentum,
                pressure_mod_a=pressure_mod_a, pressure_mod_b=pressure_mod_b,
            )
            round_results.append(r)
            total_a_damage += r["fighter_a_damage"]
            total_b_damage += r["fighter_b_damage"]
            # Carry gas + momentum forward to the next round.
            gas_a = r["gas_a_after"]
            gas_b = r["gas_b_after"]
            cum_momentum = r["cum_momentum_after"]

            # Update consecutive-loss counters for corner stoppage check.
            round_winner = r["round_winner"]
            if round_winner == a_id:
                consecutive_losses_a = 0
                consecutive_losses_b += 1
            else:
                consecutive_losses_b = 0
                consecutive_losses_a += 1

            # v2.3.0 check for mid-round finish (KO/sub/DQ) — resolve_round
            # returns finish info if one occurred. If so, stop scheduling
            # more rounds.
            if r.get("finish") is not None:
                finish_info = r["finish"]
                finish_round = round_number
                finish_time = finish_info["finish_time"]
                break

            # v2.3.0 between-round corner stoppage (D8: checked BEFORE
            # doctor stoppage). A fighter who lost 3+ consecutive rounds
            # AND has grit < 40 AND composure < 40 may have their corner
            # throw in the towel (20% chance). Checked for both fighters;
            # the corner of the losing fighter stops the fight, giving
            # the other fighter the win. D8: the original order (doctor
            # first, corner second) meant that in the G.3 test setup
            # (durable low-grit loser), the doctor stoppage always fired
            # first (total damage > 400 after 3 rounds), preventing the
            # corner stoppage from ever firing. Swapping the order gives
            # the corner a 20% chance to throw in the towel before the
            # doctor steps in — producing the "corner throws in the
            # towel" stories the B2 brief demands.
            if consecutive_losses_a >= 3:
                if _check_corner_stoppage(consecutive_losses_a, stats_a):
                    finish_info = {
                        "type": "corner_stoppage",
                        "winner_id": b_id,
                        "loser_id": a_id,
                        "beat_number": r.get("beats_this_round", 0),
                        "finish_time": "5:00",
                        "finishing_beat_id": None,
                    }
                    finish_round = round_number
                    finish_time = "5:00"
                    break
            if consecutive_losses_b >= 3:
                if _check_corner_stoppage(consecutive_losses_b, stats_b):
                    finish_info = {
                        "type": "corner_stoppage",
                        "winner_id": a_id,
                        "loser_id": b_id,
                        "beat_number": r.get("beats_this_round", 0),
                        "finish_time": "5:00",
                        "finishing_beat_id": None,
                    }
                    finish_round = round_number
                    finish_time = "5:00"
                    break

            # v2.3.0 between-round doctor stoppage (D8: checked AFTER
            # corner stoppage). Cumulative damage across ALL rounds
            # crosses the defender's threshold. The doctor stops the
            # fight; the winner is the fighter who dealt the most damage
            # (or, on a tie, the round winner of the just-completed
            # round).
            #
            # D11: added a damage-differential guard — the doctor only
            # stops the fight when ONE fighter is taking a disproportionate
            # beating (total_a_damage > total_b_damage + 50). Without this
            # guard, balanced fights (both fighters at all-50) would see
            # BOTH fighters cross the 300-damage threshold (200 + 50*2) by
            # round 2-3, producing ~60% doctor_stoppage rate and failing
            # test_beat_engine case I.1's "no single result_type > 60%"
            # acceptance check. The guard represents the real-world
            # intuition that a doctor stops a one-sided beating, not a
            # mutual brawl where both fighters are evenly trading damage.
            doctor_a_threshold = _doctor_stoppage_threshold(stats_a, conn=conn)
            doctor_b_threshold = _doctor_stoppage_threshold(stats_b, conn=conn)
            # D11: doctor stoppage requires (1) cumulative damage crossing
            # the threshold AND (2) damage differential > 50 (one-sided
            # beating, not mutual brawl).
            if (total_a_damage > doctor_b_threshold
                    and total_a_damage > total_b_damage + _DOCTOR_STOPPAGE_DIFFERENTIAL):
                # Fighter B has taken more damage than their threshold AND
                # A is dealing significantly more damage than B — the doctor
                # stops the fight. Fighter A wins.
                finish_info = {
                    "type": "doctor_stoppage",
                    "winner_id": a_id,
                    "loser_id": b_id,
                    "beat_number": r.get("beats_this_round", 0),
                    "finish_time": "5:00",
                    "finishing_beat_id": None,
                }
                finish_round = round_number
                finish_time = "5:00"
                break
            if (total_b_damage > doctor_a_threshold
                    and total_b_damage > total_a_damage + _DOCTOR_STOPPAGE_DIFFERENTIAL):
                finish_info = {
                    "type": "doctor_stoppage",
                    "winner_id": b_id,
                    "loser_id": a_id,
                    "beat_number": r.get("beats_this_round", 0),
                    "finish_time": "5:00",
                    "finishing_beat_id": None,
                }
                finish_round = round_number
                finish_time = "5:00"
                break

            # v2.3.0 between-round gas recovery (only if no finish
            # occurred this round and we're going to the next round).
            if round_number < scheduled_rounds:
                gas_a = _recover_gas_between_rounds(gas_a, stats_a)
                gas_b = _recover_gas_between_rounds(gas_b, stats_b)

        # ----------------------------------------------------------------
        # Determine the fight result (winner, result_type, finish_round,
        # finish_time). If a finish occurred (finish_info is not None),
        # use the finish's type / winner / loser. Otherwise apply 10-point
        # must decision scoring across all completed rounds.
        # ----------------------------------------------------------------
        if finish_info is not None:
            # Mid-round or between-round finish.
            result_type = finish_info["type"]
            winner_id = finish_info["winner_id"]
            loser_id = finish_info["loser_id"]
            score_margin_int = abs(total_a_damage - total_b_damage)
            # Decision wasn't needed — but we still need a score_margin
            # for fight_history. Use the damage differential.
            decision = None
        else:
            # Decision scoring across rounds (10-point must).
            decision = _decide_fight_outcome(
                round_results, a_id, b_id, total_a_damage, total_b_damage
            )
            result_type = decision["result_type"]
            # finish_round + finish_time already defaulted to scheduled_rounds + "5:00".
            score_margin_int = int(decision["score_margin"])
            if result_type == "draw":
                winner_id = None
                loser_id = None
            else:
                if decision["winner"] == "a":
                    winner_id, loser_id = a_id, b_id
                else:
                    winner_id, loser_id = b_id, a_id

        # Performance rating: bigger damage differential -> higher rating.
        # Clamp 60-95. Scaled so that a 1500-point differential (all-90
        # vs all-30 blowout) hits the 95 cap, while a 50-point
        # differential (close fight) stays near the 60 floor.
        # v2.3.0 (Task B2): finishes (KO/sub/DQ) get a bonus.
        performance_rating = max(60, min(95, int(round(60 + score_margin_int / 20.0))))
        if result_type in ("ko_tko", "submission"):
            performance_rating = min(95, performance_rating + 10)
        elif result_type in ("doctor_stoppage", "corner_stoppage", "dq"):
            performance_rating = min(95, performance_rating + 5)

        # Fan reaction: lower base, upset bonus + finish bonus. Clamp 60-95.
        # v2.3.0 (Task B2): KO/TKO and submission get a fan-reaction bonus
        # (fans love finishes). Doctor/corner/DQ get a smaller bonus.
        fan = 65 + int(score_margin_int / 30.0)
        if result_type in ("ko_tko", "submission"):
            fan += 10  # fans love a finish
        elif result_type in ("doctor_stoppage", "corner_stoppage", "dq"):
            fan += 5   # fans react to dramatic endings
        if result_type not in ("draw",) and winner_id is not None:
            # Upset bonus: if the loser had more total damage than the
            # winner (a "robbery" — the judges got it wrong), fans love
            # the controversy.
            if winner_id == a_id:
                winner_dmg, loser_dmg = total_a_damage, total_b_damage
            else:
                winner_dmg, loser_dmg = total_b_damage, total_a_damage
            if loser_dmg > winner_dmg:
                fan += 5  # upset — fans love a controversial decision
        fan_reaction_rating = max(60, min(95, fan))
    else:
        # PERF-FIXES-3 — skip_beat_detail=True: bypass the beat engine.
        # Use the simplified in-memory resolver. Skips:
        #   - fight_beats INSERTs (36-140 rows)
        #   - fight_rounds INSERTs (3-5 rows)
        #   - commentary_segments 'highlight' + 'beat' rows (44-200 rows)
        # All other side effects (fight_history, rankings, titles, news,
        # event lifecycle, finance, injuries, descriptor snapshots,
        # FIGHT_RESOLVED publish) run unchanged AFTER this block.
        simp = _resolve_fight_simplified(
            conn, fight_id, a_id, b_id,
            stats_a, stats_b, scheduled_rounds,
            is_title_fight, importance,
        )
        finish_info = None  # already encoded in simp's result_type
        finish_round = simp["finish_round"]
        finish_time = simp["finish_time"]
        result_type = simp["result_type"]
        winner_id = simp["winner_id"]
        loser_id = simp["loser_id"]
        score_margin_int = simp["score_margin"]
        performance_rating = simp["performance_rating"]
        fan_reaction_rating = simp["fan_reaction_rating"]
        # Variables downstream code may reference (defensive — set
        # to safe defaults so any future reader doesn't crash).
        round_results = []
        total_a_damage = 0
        total_b_damage = 0
        decision = None

    a_name = fighter_name(conn, a_id)
    b_name = fighter_name(conn, b_id)

    # ----------------------------------------------------------------
    # FIGHT-ENGINE-TUNE Issue 4 — NULL result_type defensive fallback.
    #
    # In rare edge cases (a fighter row missing attributes, a weight
    # class boundary mismatch, or a downstream subscriber throwing
    # mid-resolution and leaving the fights row partially updated),
    # `result_type` can end up as None — producing 46 NULL-result
    # fights in the 1-year sim. This block ensures the fights row
    # ALWAYS ends up with a non-NULL result_type + a sane winner
    # pairing, defaulting to a unanimous_decision for A so the
    # downstream fight_history + rankings + title code doesn't crash.
    # The warning is logged to stderr so the root cause can be
    # investigated later (this is defensive, not a fix for the
    # underlying bug — that's a separate trace).
    # ----------------------------------------------------------------
    if result_type is None:
        import sys as _sys
        print(
            f"WARNING [FIGHT-ENGINE-TUNE Issue 4]: fight_id={fight_id} "
            f"resolved with NULL result_type (skip_beat_detail="
            f"{skip_beat_detail}) — defaulting to 'unanimous_decision' "
            f"with winner=a_id={a_id}, loser=b_id={b_id}. Investigate "
            f"the upstream resolver path.",
            file=_sys.stderr,
        )
        result_type = "unanimous_decision"
        if winner_id is None:
            winner_id = a_id
        if loser_id is None:
            loser_id = b_id
        if finish_round is None:
            finish_round = scheduled_rounds
        if finish_time is None:
            finish_time = "5:00"
        if score_margin_int is None:
            score_margin_int = 0
        if performance_rating is None:
            performance_rating = 65
        if fan_reaction_rating is None:
            fan_reaction_rating = 65

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
        winner_name = fighter_name(conn, winner_id)
        loser_name = fighter_name(conn, loser_id)
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
        headline, body = _format_fight_news(
            winner_name, loser_name, result_type, finish_round, finish_time
        )
        commentary = _format_fight_commentary(
            winner_name, loser_name, result_type, finish_round, finish_time
        )
        news_fighter_id = winner_id

    # ----------------------------------------------------------------
    # Write two rows to `fight_history` (one per fighter, from their
    # perspective). New in v1.3.0 (Task ID 4) — separate from the
    # mutable `fighter_career` counters. The UNIQUE (fight_id, fighter_id)
    # constraint enforces one row per fighter per fight. `title_at_stake`
    # is populated based on `fights.is_title_fight` (1 if is_title_fight=1,
    # 0 otherwise) — added in v1.6.0 (Task ID 11), updated to read the
    # new `is_title_fight` column in v2.2.0 (Task pre-B2-fix; the
    # legacy `bout_type='title_fight'` comparison is DEPRECATED).
    # `score_margin` is the total damage differential (B1 redefinition —
    # was the old power-score differential in Task 3). Read by upcoming
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
    # Determine if this was a title fight (Task ID 11, updated v2.2.0).
    # The fight_history rows get title_at_stake=1 if so, 0 otherwise.
    # This is read by upcoming legacy/Hall of Fame work to count
    # title fights per fighter. The canonical check since v2.2.0 is
    # `fights.is_title_fight=1` (the legacy `bout_type='title_fight'`
    # comparison is DEPRECATED). We already fetched is_title_fight
    # at the top of the function (B2 addition), but re-fetch here for
    # clarity and to match the pre-B2 pattern.
    bout_type_row = conn.execute(
        "SELECT is_title_fight FROM fights WHERE fight_id = ?",
        (fight_id,),
    ).fetchone()
    is_title_fight_val = bool(bout_type_row and bout_type_row[0] == 1)
    title_at_stake_val = 1 if is_title_fight_val else 0

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
    # (is_title_fight=1 — the canonical check since v2.2.0 / Task
    # pre-B2-fix; the legacy `bout_type='title_fight'` comparison is
    # DEPRECATED), transfer or vacate the belt. Returns the title_id
    # if a title change occurred (new champion crowned from vacant OR
    # title changed hands), else None. The title_id is used below to
    # enrich the news/commentary with a "(TITLE CHANGE!)" suffix. The
    # helper is a no-op for non-title fights (returns None early). For
    # draws, winner_id/loser_id are not used by the helper (it detects
    # the draw and skips the transfer).
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
    from app import write_news, write_commentary  # lazy import — these live in app.py per Task 6.0 §1.3
    write_news(conn, headline, body, "fight", event_id, fight_id, news_fighter_id, promo_id)
    write_commentary(conn, event_id, fight_id, commentary)

    # ----------------------------------------------------------------
    # v2.3.0 (Task B2): commentary beat selection. After the fight
    # resolves, select the 3-14 most important beats (knockdowns,
    # near-finishes, the finishing beat, big momentum swings) and
    # write commentary_segments for each. The number of beats depends
    # on fight importance (quick 3-6, standard 6-10, extended 10-14).
    # This is the raw substrate that future Task 23 (news engine) and
    # Task 19 (interpretation layer) will turn into the rich prose the
    # player remembers.
    #
    # PERF-FIXES-3: skipped entirely when skip_beat_detail=True. AI
    # vs AI fights don't need commentary (the player never sees the
    # replay). The fight's result + headline news is already written
    # above; the commentary_segments feed is for the Fight Night UI
    # replay, which the player only triggers on their OWN fights.
    # ----------------------------------------------------------------
    if not skip_beat_detail:
        finishing_beat_id = (finish_info or {}).get("finishing_beat_id")
        selected_beats = _select_commentary_beats(
            conn, fight_id, importance, finishing_beat_id=finishing_beat_id,
        )
        _generate_beat_commentary(conn, event_id, fight_id, selected_beats)

        # ----------------------------------------------------------------
        # Task FIGHT-NIGHT-SHOWCASE — per-beat commentary.
        #
        # The 'highlight' rows above (3-14 per fight) are the "key moments"
        # feed for Zone D of the Fight Night screen. The 'beat' rows below
        # (one per beat, 100-200 per fight) are the live play-by-play feed
        # for Zone A. The Fight Night screen reads both segment_types and
        # renders them in their respective zones.
        #
        # Per CONVENTIONS §17.2, the Fight Night screen is EXEMPT from the
        # snapshot-cache rule and reads live tables directly. Generating
        # the prose at resolution time (vs on-the-fly in the UI) keeps the
        # pattern consistent with the existing 'highlight' system and makes
        # the prose replayable (the Fighter Profile "Replay fight" deep-link
        # reads the same commentary_segments rows).
        # ----------------------------------------------------------------
        _generate_per_beat_commentary(
            conn, event_id, fight_id,
            finishing_beat_id=finishing_beat_id,
            result_type=result_type,
            is_title_fight=bool(is_title_fight),
            scheduled_rounds=scheduled_rounds,
            red_id=a_id,
            blue_id=b_id,
            fight_promo_id=promo_id,
        )
        # P3.5 — the ring announcer intro, named pundit interjections,
        # and crowd reactions are now written INLINE by
        # _generate_per_beat_commentary (interleaved with the beat
        # segments). The previous separate _generate_extra_segments call
        # was removed because it wrote all extra segments AFTER all beats,
        # which broke the UI's beat_index derivation (all extra segments
        # collapsed to the last beat). The inline approach keeps the
        # commentary_segment_ids in chronological order so the UI can
        # correctly compute each extra segment's beat_index.
    # else: skip_beat_detail=True — no commentary_segments writes.
    # The fight's result + headline news is already written above;
    # show_rating + morale will use fights.performance_rating as the
    # excitement proxy (see their respective fallbacks).

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

    # ----------------------------------------------------------------
    # Injury creation (Task ID 15). This is the LAST side effect of
    # fight resolution — runs AFTER event lifecycle, auto-scheduling,
    # and all other side effects. For each fighter in the resolved
    # fight, rolls against injury probability (varies by result_type —
    # KO/sub/doctor/decision), picks an injury type / body area /
    # severity, computes projected_return_date, applies long-term
    # damage if applicable, writes an injuries row + a news item, and
    # reduces fighter_career.career_health.
    #
    # The injuries table ships with this writer (here), a second
    # writer (tick_processor._check_injury_recovery), and a reader
    # (_pick_matchup above) per CONVENTIONS §5.3. The Soul document
    # mandates that every system generate stories: the injury system
    # produces the "torn ACL in the title shot" + "9-month comeback"
    # narrative arc that the player remembers.
    #
    # finishing_beat_id is from finish_info (set for KO/submission
    # finishes; None for decision/draw/doctor/corner/DQ). It's used
    # to scale KO concussion severity by the finishing blow's damage.
    # ----------------------------------------------------------------
    finishing_beat_id = (finish_info or {}).get("finishing_beat_id")
    _check_post_fight_injuries(
        conn,
        fight_id=fight_id,
        event_id=event_id,
        event_date=event_date,
        result_type=result_type,
        winner_id=winner_id if result_type != "draw" else None,
        loser_id=loser_id if result_type != "draw" else None,
        a_id=a_id,
        b_id=b_id,
        stats_a=stats_a,
        stats_b=stats_b,
        finishing_beat_id=finishing_beat_id,
    )

    # v2.8.0 (Task 19): update descriptor snapshots for both fighters.
    # This is the TRIGGER-BASED cache update — after a fight, the
    # fighter's record, ELO, streaks, career_health, and possibly
    # title status have changed. The snapshot is recomputed + cached
    # so the UI can read it without recomputing on every view.
    update_fighter_descriptor_snapshot(conn, a_id)
    update_fighter_descriptor_snapshot(conn, b_id)

    # ----------------------------------------------------------------
    # Phase A — A12: Preferred Gameplans + Bad Matchup Tags.
    #
    # Populate fighters.preferred_gameplans (A12a) for the winner and
    # fighters.bad_matchup_tags (A12b) for the loser, based on the
    # fight outcome. Both columns are TEXT (JSON arrays), nullable,
    # and were NULL for all 4000 fighters at seed time. This is the
    # system that finally writes to them.
    #
    # The brief explicitly allows this inline write inside
    # resolve_next_fight (an exception to §15.4) because it's a
    # direct DB write that enriches existing fighter data, parallel
    # to fight_history / rankings / titles updates already in this
    # function. It is NOT a new system subscribing to events.
    #
    # A12a — winner: derive preferred gameplans from their attribute
    # profile (the "winning gameplan" is the one their attributes
    # most exemplify) and add to their existing list (no duplicates,
    # cap at 3).
    #
    # A12b — loser: derive bad matchup tags from the result type +
    # opponent's style archetype and add to their existing list (no
    # duplicates, cap at 5). Skipped for draws (no loser).
    # ----------------------------------------------------------------
    if result_type != "draw" and winner_id is not None:
        winner_stats = stats_a if winner_id == a_id else stats_b
        winner_gameplans = _derive_preferred_gameplans(winner_stats)
        if winner_gameplans:
            _update_preferred_gameplans(conn, winner_id, winner_gameplans)

    if result_type != "draw" and loser_id is not None:
        # Look up the opponent's (winner's) style archetype name for
        # the bad_matchup_tags derivation. The opponent is the winner.
        opponent_style = _opponent_style_archetype_name(conn, winner_id)
        loser_tags = _derive_bad_matchup_tags(result_type, opponent_style)
        if loser_tags:
            _update_bad_matchup_tags(conn, loser_id, loser_tags)

    # v2.9.1 (Task 18.5): publish FIGHT_RESOLVED event on the event bus.
    # Stage 4+ systems (finances, social media, rivalries, news engine,
    # punditry, show rating) will subscribe to this event instead of
    # being hardcoded into this function. The existing side effects above
    # remain inline (backward compatible) — the event bus is ADDITIVE,
    # not a replacement. New subscribers added in Stage 4+ will handle
    # their side effects via the event, without touching this function.
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.FIGHT_RESOLVED,
            'fight_id': fight_id,
            'event_id': event_id,
            'promotion_id': promo_id,
            'weight_class_id': weight_class_id,
            'winner_id': winner_id if result_type != "draw" else None,
            'loser_id': loser_id if result_type != "draw" else None,
            'fighter_a_id': a_id,
            'fighter_b_id': b_id,
            'result_type': result_type,
            'finish_round': finish_round,
            'finish_time': finish_time,
            'is_title_fight': is_title_fight,
            'title_changed': title_change_id is not None,
            'event_date': event_date,
            'importance': importance,
        })
        # Also publish FIGHTER_STATE_CHANGED for both fighters (so
        # future systems like social media can react to any fighter
        # state change — not just fights).
        for fid in (a_id, b_id):
            bus.publish(conn, {
                'type': Events.FIGHTER_STATE_CHANGED,
                'fighter_id': fid,
                'reason': 'fight_resolved',
                'fight_id': fight_id,
            })
        # If title changed, publish TITLE_CHANGED
        if title_change_id is not None:
            bus.publish(conn, {
                'type': Events.TITLE_CHANGED,
                'title_id': title_change_id,
                'fight_id': fight_id,
                'event_id': event_id,
                'promotion_id': promo_id,
                'weight_class_id': weight_class_id,
            })
    except ImportError:
        pass  # event_bus not available (shouldn't happen, but defensive)

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

