"""CAGE EMPIRE Rival AI — Imperfection Engine (Task ID RIVAL-AI-P2to4, Phase 4).

Per docs/RIVAL_AI_ARCHITECTURE.md §6 — the 6 imperfection mechanisms
that make the AI "realistic, not flawless" (the user's explicit
caveat). These are PURE FUNCTIONS called by the other Phase 2-3
modules; they are NOT a separate tick.

The 6 mechanisms (per arch doc §6):
  1. Archetype bias       — each archetype makes CONSISTENT errors of
                            its own kind. This is BUILT INTO the
                            ARCHETYPES dict in archetypes.py — the
                            `bid_premium_pct` / `matchmaking_safe_pct`
                            / `cut_aggressiveness` / `signing_age_max`
                            constants ARE the bias. No separate logic
                            needed; this module documents the linkage.
  2. Recency bias         — recent event result shifts behaviour for
                            1-2 sim-weeks (hit → aggressive, flop →
                            conservative). Implemented as
                            `recency_bias_modifier` which returns a
                            dict of multiplier keys applied to the
                            archetype dict by the caller.
  3. Loyalty              — veteran / coach / re-signing loyalty rules.
                            Implemented as `loyalty_threshold_bonus`
                            (for cutting_agent) + `re_signing_bonus`
                            (for signing_agent).
  4. Matchup mistakes     — the head-scratcher path in matchmaker.
                            The matchmaker module implements this via
                            `_bias_injector`; this module documents
                            the linkage + provides the whimsy roll.
  5. Budget mistakes      — Rising Star overspend + crisis panic
                            signings. The signing_agent + budget_manager
                            implement this; this module provides the
                            `maybe_whim` decision point.
  6. Whimsy               — 5-15% of decisions are "whims" (random
                            non-optimal actions). Implemented as
                            `maybe_whim` which the other modules call
                            at the start of their decision functions.

CONVENTIONS compliance:
  §5  — No new tables. Reads existing `show_ratings` + `contracts` +
        `fighter_contracts` tables only.
  §14 — Voice Layer: N/A — no player-facing text. Pure helpers.
  §15 — Event Bus: N/A — pure functions, no subscribers.
"""

import random as _random
import math
from datetime import datetime, timedelta


# Per-decision whimsy budgets (per arch doc §6.6 table). These are
# the WHIMSY RATES BY DECISION TYPE — applied on top of the archetype's
# base `whimsy_pct`. The decision_type overrides the archetype's
# whimsy_pct for the matchmaking decision (which is more player-
# visible) and the budget decision (less player-visible).
WHIMSY_PCT_BY_DECISION = {
    'event_scheduling': None,   # use archetype.whimsy_pct (5-12%)
    'matchmaking':      0.20,   # 20% — higher, most player-visible
    'signing':          None,   # use archetype.whimsy_pct (8-12%)
    'cutting':          0.10,   # 10% — "going in a different direction"
    'staff':            0.10,   # 10% — "name hire" whim
    'budget':           0.05,   # 5% — pick a random adjacent state
}


# Recency bias window (per arch doc §6.2). The modifier decays after
# 14 sim-days — events older than 14 days no longer shift behaviour.
RECENCY_BIAS_WINDOW_DAYS = 14

# Hit / flop thresholds (per arch doc §6.2). An event with
# overall_rating > HIT_RATING is a "hit"; < FLOP_RATING is a "flop".
HIT_RATING = 75
FLOP_RATING = 40


def maybe_whim(archetype, decision_type, rng=None):
    """Return True if this decision should be a "whim" (random non-
    optimal action).

    Per arch doc §6.6:
        roll = rng.random()
        if roll < whimsy_pct_for_this_decision:
            return True  # pick from the whim pool instead of normal logic
        return False

    The whimsy_pct for the decision comes from `WHIMSY_PCT_BY_DECISION`.
    If the entry is None, falls back to the archetype's base
    `whimsy_pct` (so each archetype's personality still applies).

    Args:
        archetype: the archetype dict (for whimsy_pct). May be None —
            returns False (defensive — a missing archetype shouldn't
            trigger whims).
        decision_type: 'event_scheduling' / 'matchmaking' / 'signing'
            / 'cutting' / 'staff' / 'budget'.
        rng: optional random.Random instance. Defaults to a fresh
            instance (caller should pass a seeded rng for
            reproducibility in tests).

    Returns:
        True if the decision should be a whim; False otherwise.
    """
    if archetype is None:
        return False
    whimsy_pct = WHIMSY_PCT_BY_DECISION.get(decision_type)
    if whimsy_pct is None:
        whimsy_pct = archetype.get('whimsy_pct', 0.0)
    if not whimsy_pct:
        return False
    rng = rng or _random.Random()
    return rng.random() < whimsy_pct


def recency_bias_modifier(conn, promotion_id, current_date=None):
    """Return a modifier dict for the promo's recent event results.

    Per arch doc §6.2:
      1. Query the promo's events completed in the last 14 sim-days.
      2. For each event, read its show_ratings.overall_rating.
      3. Hit event (overall > 75):
         - bid_premium_pct × 1.2
         - matchmaking_safe_pct - 0.10
         - cut_aggressiveness × 0.8
      4. Flop event (overall < 40):
         - bid_premium_pct × 0.5
         - matchmaking_safe_pct + 0.10
         - cut_aggressiveness × 1.2
      5. Multiple events in the window compound (2 hits = 2× upshift,
         capped at +50% above archetype baseline).
      6. The modifier decays after 14 sim-days.

    The returned dict has keys matching archetype constant names.
    Callers apply the multipliers via `apply_recency_to_archetype`.

    Args:
        conn: sqlite3.Connection (read-only).
        promotion_id: the rival promo.
        current_date: sim date string. Defaults to current sim date.

    Returns:
        Dict like {'bid_premium_pct': 1.2, 'matchmaking_safe_pct': -0.10,
        'cut_aggressiveness': 0.8}. Empty dict if no recent events.
    """
    if current_date is None:
        from services.rival_ai._shared import current_sim_date
        current_date = current_sim_date(conn)
    if not current_date:
        return {}

    try:
        cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {}
    cutoff_date = (cur_dt - timedelta(days=RECENCY_BIAS_WINDOW_DAYS)).strftime("%Y-%m-%d")

    # Pull all show_ratings for the promo's events completed in the
    # last 14 sim-days. LEFT JOIN show_ratings so events without a
    # rating row (shouldn't happen post-v3.6.0, but defensive) get
    # an overall_rating of 50 (NORMAL — no shift).
    rows = conn.execute(
        "SELECT COALESCE(sr.overall_rating, 50) AS overall "
        "FROM events e "
        "LEFT JOIN show_ratings sr ON sr.event_id = e.event_id "
        "WHERE e.promotion_id = ? AND e.status = 'completed' "
        "AND e.event_date >= ? AND e.event_date <= ?",
        (promotion_id, cutoff_date, current_date),
    ).fetchall()
    if not rows:
        return {}

    hits = sum(1 for (overall,) in rows if overall >= HIT_RATING)
    flops = sum(1 for (overall,) in rows if overall <= FLOP_RATING)

    if hits == 0 and flops == 0:
        return {}

    # Compound: each hit multiplies bid_premium_pct by 1.2 (cap 1.5
    # = ~2 hits). Each flop multiplies by 0.5 (cap 0.25 = ~2 flops).
    # The cap matches arch doc §6.2 "capped at +50% above baseline"
    # — for flops we cap at -50% below baseline (0.5 multiplier).
    bid_mult = 1.0
    for _ in range(hits):
        bid_mult = min(1.5, bid_mult * 1.2)
    for _ in range(flops):
        bid_mult = max(0.5, bid_mult * 0.5)

    # matchmaking_safe_pct shifts by ±0.10 per event, clamped to [0.20, 0.95].
    safe_shift = 0.0
    safe_shift -= 0.10 * hits   # hits → riskier matchmaking (lower safe_pct)
    safe_shift += 0.10 * flops  # flops → conservative (higher safe_pct)

    # cut_aggressiveness compounds like bid_mult (hits keep veterans, flops panic-cut).
    cut_mult = 1.0
    for _ in range(hits):
        cut_mult = max(0.5, cut_mult * 0.8)
    for _ in range(flops):
        cut_mult = min(1.5, cut_mult * 1.2)

    return {
        'bid_premium_pct': bid_mult,
        'matchmaking_safe_pct': safe_shift,  # additive shift (caller adds, not multiplies)
        'cut_aggressiveness': cut_mult,
        'budget_state_shift': 1 if hits > flops else (-1 if flops > hits else 0),
    }


def apply_recency_to_archetype(archetype, recency_mods):
    """Return a NEW archetype dict with the recency bias applied.

    Takes a (frozen) archetype dict + the modifier dict from
    `recency_bias_modifier` and returns a new (mutable) dict with
    the modifiers applied. Does NOT mutate the input archetype.

    Args:
        archetype: the frozen archetype dict (one of ARCHETYPES).
        recency_mods: dict from `recency_bias_modifier`. Empty dict
            returns the archetype unchanged (as a new dict).

    Returns:
        A new dict with the modifier multipliers / shifts applied.
    """
    if not archetype:
        return dict(archetype or {})
    out = dict(archetype)
    if not recency_mods:
        return out
    if 'bid_premium_pct' in recency_mods:
        out['bid_premium_pct'] = archetype['bid_premium_pct'] * recency_mods['bid_premium_pct']
    if 'matchmaking_safe_pct' in recency_mods:
        # Additive shift, clamped to [0.20, 0.95].
        new_safe = archetype['matchmaking_safe_pct'] + recency_mods['matchmaking_safe_pct']
        out['matchmaking_safe_pct'] = max(0.20, min(0.95, new_safe))
    if 'cut_aggressiveness' in recency_mods:
        out['cut_aggressiveness'] = max(0.05, min(0.95,
            archetype['cut_aggressiveness'] * recency_mods['cut_aggressiveness']))
    return out


def loyalty_threshold_bonus(conn, fighter_id, promotion_id):
    """Return the +threshold bonus for a fighter's cut_risk based on
    tenure (the "veteran loyalty" rule per arch doc §6.3).

    Per arch doc §6.3 rule 1:
        tenure_months = months since the fighter's contract start_date
        if tenure_months >= 24:
            return +10  # cut_risk threshold raised from 65 to 75
        return 0

    The tenure is measured from the fighter's CURRENT active contract
    with this promotion (the most recent start_date).

    Args:
        conn: sqlite3.Connection (read-only).
        fighter_id: the fighter being evaluated for cutting.
        promotion_id: the promo considering the cut.

    Returns:
        Int (0 or 10).
    """
    row = conn.execute(
        "SELECT c.start_date FROM contracts c "
        "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "WHERE fc.fighter_id = ? AND c.promotion_id = ? "
        "AND c.status = 'active' "
        "ORDER BY c.start_date DESC LIMIT 1",
        (fighter_id, promotion_id),
    ).fetchone()
    if row is None or not row[0]:
        return 0
    try:
        start_dt = datetime.strptime(row[0], "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    # Compute the sim clock's current date so tenure is measured
    # against the in-game clock (not wall-clock).
    from services.rival_ai._shared import current_sim_date
    cur_str = current_sim_date(conn)
    if not cur_str:
        return 0
    try:
        cur_dt = datetime.strptime(cur_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    # Months between start_date and current_date. Approximation:
    # (year_diff * 12) + month_diff. Days-level precision is overkill
    # for the 24-month threshold.
    tenure_months = (cur_dt.year - start_dt.year) * 12 + (cur_dt.month - start_dt.month)
    if tenure_months >= 24:
        return 10
    return 0


def re_signing_bonus(conn, fighter_id, promotion_id):
    """Return the +offer_score bonus for re-signing a former roster
    member (the "welcome back, kid" rule per arch doc §6.3).

    Per arch doc §6.3 rule 3:
        if the fighter was previously on the promo's roster (has a
        terminated contract with this promotion_id):
            return +0.10  # offer_score bonus
        return 0.0

    We look for ANY contract (terminated or expired) linking the
    fighter to this promotion — including the historical contracts
    that the seed created before the fighter was cut / left via
    free agency.

    Args:
        conn: sqlite3.Connection (read-only).
        fighter_id: the FA being evaluated.
        promotion_id: the promo evaluating the signing.

    Returns:
        Float (0.0 or 0.10).
    """
    row = conn.execute(
        "SELECT 1 FROM contracts c "
        "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "WHERE fc.fighter_id = ? AND c.promotion_id = ? "
        "LIMIT 1",
        (fighter_id, promotion_id),
    ).fetchone()
    if row is None:
        return 0.0
    return 0.10


# ----------------------------------------------------------------
# Storyline + development_value helpers (per arch doc §3.2).
#
# These are used by the matchmaker's _matchup_score function. They
# implement the storyline() + development_value() components from
# the matchup scoring formula.
# ----------------------------------------------------------------

def storyline_score(conn, fighter_a_id, fighter_b_id, weight_class_id=None):
    """Compute the 0..1 storyline score for a fighter pair.

    Per arch doc §3.2:
        storyline(A, B) =
            0.5 if they share a common opponent in the last 12 months
          + 0.3 if they have an active rivalry row (heat >= 40)
          + 0.2 if it's a rematch of a fight >90 days ago
          (capped at 1.0)

    Args:
        conn: sqlite3.Connection (read-only).
        fighter_a_id, fighter_b_id: the fighters being paired.
        weight_class_id: optional WC for the rivalry check.

    Returns:
        Float 0..1.
    """
    score = 0.0
    # 1. Common opponent in the last 12 months (0.5).
    common = conn.execute(
        "SELECT COUNT(DISTINCT fh_a.opponent_id) "
        "FROM fight_history fh_a "
        "JOIN fight_history fh_b ON fh_b.opponent_id = fh_a.opponent_id "
        "WHERE fh_a.fighter_id = ? AND fh_b.fighter_id = ? "
        "AND fh_a.event_date >= date(COALESCE((SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1), '2026-01-01'), '-12 months')",
        (fighter_a_id, fighter_b_id),
    ).fetchone()
    if common and common[0] > 0:
        score += 0.5

    # 2. Active rivalry row with heat >= 40 (0.3).
    rivalry = conn.execute(
        "SELECT 1 FROM rivalries "
        "WHERE is_active = 1 AND rivalry_heat >= 40 "
        "AND ((fighter_a_id = ? AND fighter_b_id = ?) "
        "     OR (fighter_a_id = ? AND fighter_b_id = ?)) "
        "LIMIT 1",
        (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
    ).fetchone()
    if rivalry:
        score += 0.3

    # 3. Rematch of a fight >90 days ago (0.2).
    rematch = conn.execute(
        "SELECT MIN(fh.event_date) FROM fight_history fh "
        "WHERE fh.fighter_id = ? AND fh.opponent_id = ?",
        (fighter_a_id, fighter_b_id),
    ).fetchone()
    if rematch and rematch[0]:
        try:
            last_dt = datetime.strptime(rematch[0], "%Y-%m-%d")
            from services.rival_ai._shared import current_sim_date
            cur_str = current_sim_date(conn)
            if cur_str:
                cur_dt = datetime.strptime(cur_str, "%Y-%m-%d")
                if (cur_dt - last_dt).days >= 90:
                    score += 0.2
        except (ValueError, TypeError):
            pass

    return min(1.0, score)


def development_value(fighter_a, fighter_b):
    """Compute the 0..1 development_value score for a fighter pair.

    Per arch doc §3.2:
        development_value(A, B) =
            0.5 if one fighter has potential >= 75 AND age <= 26
          + 0.3 if the other fighter is a "gatekeeper" (rating 1100-1300,
                 record .500-.700, age 30+)
          + 0.2 if it's the prospect's first main-card slot
          (capped at 1.0)

    The "first main-card slot" check is omitted here — the caller
    (matchmaker) tracks booked_ids per card and can pass that info
    via the fighter dicts. The first 2 components are computed here.

    Args:
        fighter_a, fighter_b: dict-like rows from the roster cache.
            Expected keys: potential, age (computed), rating,
            record_wins, record_losses, record_draws.

    Returns:
        Float 0..1.
    """
    score = 0.0
    # Identify which fighter is the "prospect" (potential >= 75, age <= 26).
    a_is_prospect = (
        fighter_a.get('potential', 0) >= 75
        and fighter_a.get('age', 99) <= 26
    )
    b_is_prospect = (
        fighter_b.get('potential', 0) >= 75
        and fighter_b.get('age', 99) <= 26
    )
    if a_is_prospect or b_is_prospect:
        score += 0.5
        # The "other" fighter (the gatekeeper) is the non-prospect.
        gatekeeper = fighter_b if a_is_prospect else fighter_a
        if _is_gatekeeper(gatekeeper):
            score += 0.3
    return min(1.0, score)


def _is_gatekeeper(fighter):
    """Return True if the fighter matches the 'gatekeeper' profile
    (rating 1100-1300, record .500-.700, age 30+).

    Per arch doc §3.2.
    """
    rating = fighter.get('rating', 1000.0)
    if not (1100 <= rating <= 1300):
        return False
    wins = fighter.get('record_wins', 0)
    losses = fighter.get('record_losses', 0)
    total = wins + losses
    if total < 5:  # not enough fights to qualify
        return False
    win_pct = wins / total
    if not (0.40 <= win_pct <= 0.70):  # .500-.700 means roughly even
        return False
    age = fighter.get('age', 0)
    return age >= 30
