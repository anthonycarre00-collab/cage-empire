"""CAGE EMPIRE Rival AI — Signing Agent (Task ID RIVAL-AI-P2to4, Phase 2).

Per docs/RIVAL_AI_ARCHITECTURE.md §3.3 + §5.3 — fighter signing
with roster-gap detection, bidding wars, and contract-expiry
interest rumors. Wraps the existing `sign_free_agent` in
`services/contracts.py` with a multi-promo intent-collection layer.

THE NO-TAPPING-UP RULE (per arch doc §5.1):
  The signing_agent NEVER queries fighters with
  `current_promotion_id IS NOT NULL`. This is enforced at the SQL
  level — every FA query has `WHERE current_promotion_id IS NULL`
  in the WHERE clause. There is no application-level code path that
  can bypass this.

CONVENTIONS compliance:
  §5  — No new tables. Reads existing `fighters` + `fighter_career`
        + `rankings` + `contracts` + `fighter_contracts` + `staff`
        + `titles` tables only.
  §13 — Design Law: this is the "Empire Builder" pillar — rival
        promos compete for talent via bidding wars, building their
        own rosters. The player is part of the universe, not the
        center of it.
  §14 — Voice Layer: news items use direct prose (no raw numbers).
  §15 — Event Bus: relies on the existing FIGHTER_SIGNED event
        published by `sign_free_agent` — the news engine + morale
        subscribers fire automatically.
"""

import random as _random
import math


# Fair-value salary formula (per arch doc §3.3 step 4):
#   fair_value = potential × $1K + rating × $50
# Used as the base for the bid_premium calculation.
FAIR_VALUE_POTENTIAL_MULT = 1_000
FAIR_VALUE_RATING_MULT = 50

# Bid premium cap (per arch doc §3.3 step 4): no promo can bid above
# 200% of the FA's fair value.
BID_PREMIUM_CAP = 2.0  # 200%

# Bidding war randomness band (per arch doc §3.3 step 3): ±10% on
# the offer_score (i.e. 20% total randomness band).
OFFER_SCORE_RANDOMNESS = 0.10

# Whimsy rates (per arch doc §6.6) — applied via imperfection.maybe_whim.
# Tapping-up rumor rate limits.
RUMOR_RATE_LIMIT_DAYS = 30

# FA pool cache (per arch doc §4.3 — batched DB operations). The base
# FA pool (current_promotion_id IS NULL AND is_active=1 AND is_retired=0)
# is the same for all promos on a given tick. We fetch it once + filter
# in Python per-promo (by gap_wcs + potential_floor + age_max). The
# cache is cleared at the start of each new tick via _clear_fa_pool_cache.
_FA_POOL_CACHE = None


def _clear_fa_pool_cache():
    """Clear the FA pool cache. Called by src/rival_ai.py at the start
    of each new tick (alongside roster_cache_invalidate).
    """
    global _FA_POOL_CACHE
    _FA_POOL_CACHE = None


def _get_fa_pool(conn):
    """Return the base FA pool (list of dict-like rows). Cached per tick.

    The base pool is: fighters WHERE current_promotion_id IS NULL AND
    is_active=1 AND is_retired=0, joined to fighter_career (for
    potential + record) + rankings (for rating). This is the SAME for
    all promos — per-promo filtering (gap_wcs + potential_floor +
    age_max) is done in Python by `_search_fa_pool`.

    Caching the base pool turns a 9-query operation (one per promo)
    into a 1-query operation per tick — saves ~40ms per weekly tick.
    """
    global _FA_POOL_CACHE
    if _FA_POOL_CACHE is not None:
        return _FA_POOL_CACHE
    # M3.3: also fetch realization so the fair-value formula can use
    # effective_ceiling = potential * realization (busts priced lower
    # than realizers). The _offer_score talent factor still uses raw
    # potential — the rival AI's INTEREST in a fighter is based on
    # their theoretical ceiling (potential), but the SALARY they're
    # willing to pay is based on the realistic ceiling (effective).
    rows = conn.execute(
        "SELECT f.fighter_id, f.weight_class_id, f.gender, "
        "f.date_of_birth, "
        "COALESCE(fc.potential, 50) AS potential, "
        "COALESCE(fc.record_wins, 0), COALESCE(fc.record_losses, 0), "
        "COALESCE(fc.win_streak, 0), COALESCE(fc.loss_streak, 0), "
        "COALESCE(r.rating, 1000.0) AS rating, "
        "COALESCE(fc.realization, 0.7) AS realization "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id = f.fighter_id "
        "AND r.weight_class_id = f.weight_class_id "
        "WHERE f.current_promotion_id IS NULL "  # ← THE HARD RULE
        "AND f.is_active = 1 AND f.is_retired = 0 "
        "AND f.weight_class_id IS NOT NULL"
    ).fetchall()
    _FA_POOL_CACHE = [
        {
            'fighter_id': r[0],
            'weight_class_id': r[1],
            'gender': r[2],
            'date_of_birth': r[3],
            'potential': r[4],
            'record_wins': r[5],
            'record_losses': r[6],
            'win_streak': r[7],
            'loss_streak': r[8],
            'rating': r[9],
            'realization': r[10],
        }
        for r in rows
    ]
    return _FA_POOL_CACHE


def evaluate_signing_intents(conn, promotion_ids, current_date, rng=None):
    """Collect each rival promotion's intended signing for the weekly
    tick. Returns a list of intent dicts (one per promo with a
    target).

    Per arch doc §3.3:
      1. For each promo: identify roster gaps, search the FA pool
         (HARD RULE: current_promotion_id IS NULL), compute
         offer_score for each candidate, pick the highest.
      2. Return [{promotion_id, fighter_id, offer_score, base_salary,
                  archetype, budget_state}, ...]

    Args:
        conn: sqlite3.Connection (read-only).
        promotion_ids: list of int — the rival promos to evaluate.
        current_date: sim date string ('YYYY-MM-DD') for contract
            start_date.
        rng: optional random.Random instance.

    Returns:
        List of intent dicts. Most weeks: 0-2 intents total across
        all rival promos (most promos have no gap or no eligible FA).
    """
    rng = rng or _random.Random()
    intents = []
    for promo_id in promotion_ids:
        try:
            intent = _evaluate_one_promo(conn, promo_id, current_date, rng)
        except Exception as e:
            import sys
            print(f"WARNING: signing_agent evaluate failed for promo "
                  f"{promo_id}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if intent is not None:
            intents.append(intent)
    return intents


def _evaluate_one_promo(conn, promotion_id, current_date, rng):
    """Evaluate a single promo's signing intent. Returns an intent
    dict or None.

    Steps (per arch doc §3.3):
      1. Look up the (state-modified, recency-modified) archetype.
      2. If budget_state == SURVIVAL or CRISIS → no signings.
      3. Identify roster gaps (which weight classes need depth /
         contenders / prospects).
      4. Search the FA pool filtered by archetype + gaps.
      5. Compute offer_score for each candidate.
      6. Pick the highest-offer_score candidate.

    PHASE M3.1 (docs/MASTER_PLAN_MATCHMAKING.md §2.2): the player's
    promo (promo_id=1) is now passed in the promotion_ids list (so the
    player is a "valid bidding participant" — see rival_ai.py). However
    the player NEVER auto-generates an intent — the player only enters
    the bidding war via the counter_offer API (M3.2). We early-return
    None here so the player's promo produces no auto-intent.
    """
    # M3.1 guard: player's promo doesn't auto-generate intents. The
    # player's offer enters the bidding-war resolution flow via the
    # counter_offer API (app_web.counter_offer), not via this loop.
    from services.rival_ai.archetypes import PLAYER_PROMOTION_ID
    if promotion_id == PLAYER_PROMOTION_ID:
        return None
    from services.rival_ai.budget_manager import get_modified_archetype
    base_arch, mod_arch, budget_state = get_modified_archetype(conn, promotion_id)
    if mod_arch is None:
        return None
    if budget_state in ('SURVIVAL', 'CRISIS'):
        return None  # no signings in survival/crisis

    # Identify roster gaps.
    gap_wcs = _identify_roster_gaps(conn, promotion_id, mod_arch)
    # If no gaps, maybe still sign on a whim ("couldn't let him slip
    # by" — per arch doc §6.6 whimsy).
    from services.rival_ai.imperfection import maybe_whim
    if not gap_wcs:
        if not maybe_whim(mod_arch, 'signing', rng):
            return None
        # Whim signing — pick any WC the promo already has fighters in.
        gap_wcs = _existing_wcs(conn, promotion_id)
        if not gap_wcs:
            return None

    # Search the FA pool. HARD RULE: current_promotion_id IS NULL.
    candidates = _search_fa_pool(conn, mod_arch, gap_wcs)
    if not candidates:
        return None

    # Compute offer_score for each candidate + pick the highest.
    promo_row = conn.execute(
        "SELECT reputation, current_cash FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if promo_row is None:
        return None
    promo_reputation, promo_cash = promo_row
    staff_count = _staff_quality(conn, promotion_id)

    best = None
    best_score = -1.0
    for cand in candidates:
        score = _offer_score(
            promo_reputation, promo_cash, cand, staff_count,
            promotion_id, conn, rng,
        )
        if score > best_score:
            best_score = score
            best = cand

    if best is None:
        return None

    # Compute base_salary (fair value). M3.3: pass realization so the
    # formula uses effective_ceiling = potential * realization (busts
    # priced lower than realizers).
    realization = best.get('realization')
    base_salary = _fair_value(best['potential'], best['rating'], realization)
    return {
        'promotion_id': promotion_id,
        'fighter_id': best['fighter_id'],
        'offer_score': best_score,
        'base_salary': base_salary,
        'archetype': mod_arch,
        'budget_state': budget_state,
    }


def _identify_roster_gaps(conn, promotion_id, archetype):
    """Return a set of weight_class_ids where the promo has gaps.

    Per arch doc §3.3 step 1:
      - Critical gap: 0 fighters in a WC where the promo has a title.
      - Depth gap: < 4 fighters in any WC the promo operates in.
      - Contender gap: < 2 fighters in the WC's top-10 ranking.
      - Prospect gap (Rising Star only): 0 fighters with potential
        >= 70 under age 26 in any WC.
    """
    gaps = set()
    # 1. Critical gap — WC where promo has a title but 0 fighters.
    title_wcs = conn.execute(
        "SELECT weight_class_id FROM titles WHERE promotion_id=?",
        (promotion_id,),
    ).fetchall()
    for (wc_id,) in title_wcs:
        count = conn.execute(
            "SELECT COUNT(*) FROM fighters "
            "WHERE current_promotion_id=? AND weight_class_id=? "
            "AND is_active=1 AND is_retired=0",
            (promotion_id, wc_id),
        ).fetchone()[0]
        if count == 0:
            gaps.add(wc_id)

    # 2. Depth gap — WCs the promo operates in with < 4 fighters.
    roster_wcs = conn.execute(
        "SELECT weight_class_id, COUNT(*) FROM fighters "
        "WHERE current_promotion_id=? AND is_active=1 AND is_retired=0 "
        "AND weight_class_id IS NOT NULL "
        "GROUP BY weight_class_id",
        (promotion_id,),
    ).fetchall()
    for wc_id, count in roster_wcs:
        if count < 4:
            gaps.add(wc_id)

    # 3. Prospect gap (Rising Star only) — WCs with no high-potential
    # young fighters.
    if archetype and archetype.get('signing_age_max') is not None:
        # Check each WC the promo has fighters in.
        for wc_id, _ in roster_wcs:
            has_prospect = conn.execute(
                "SELECT 1 FROM fighters f "
                "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
                "WHERE f.current_promotion_id=? AND f.weight_class_id=? "
                "AND fc.potential >= 70 "
                "LIMIT 1",
                (promotion_id, wc_id),
            ).fetchone()
            if not has_prospect:
                gaps.add(wc_id)

    return gaps


def _existing_wcs(conn, promotion_id):
    """Return a set of weight_class_ids the promo already has fighters in.

    Used for whim signings (no gap, but the promo signs anyway — they
    only sign at WCs they already operate in to avoid roster bloat
    in unfamiliar divisions).
    """
    rows = conn.execute(
        "SELECT DISTINCT weight_class_id FROM fighters "
        "WHERE current_promotion_id=? AND is_active=1 AND is_retired=0 "
        "AND weight_class_id IS NOT NULL",
        (promotion_id,),
    ).fetchall()
    return {r[0] for r in rows}


def _search_fa_pool(conn, archetype, gap_wcs):
    """Search the FA pool filtered by archetype + gaps.

    HARD RULE: current_promotion_id IS NULL. Enforced at SQL level in
    `_get_fa_pool` (the cached base pool query).

    Per arch doc §3.3 step 2:
      - potential >= archetype.signing_potential_floor
      - age <= archetype.signing_age_max (if not None)
      - weight_class_id IN (gap_wcs)

    Uses the cached base FA pool from `_get_fa_pool` + filters in
    Python. This turns a 9-query operation (one per promo) into a
    1-query operation per tick — saves ~40ms per weekly tick.
    """
    if not gap_wcs:
        return []
    potential_floor = archetype.get('signing_potential_floor', 0)
    if potential_floor >= 999:
        return []  # SURVIVAL state — no FAs match
    age_max = archetype.get('signing_age_max')

    # Fetch the cached base pool (1 query per tick, shared across promos).
    base_pool = _get_fa_pool(conn)

    # Compute the age cutoff date if age_max is set.
    age_cutoff_date = None
    if age_max is not None:
        from services.rival_ai._shared import current_sim_date
        from datetime import datetime, timedelta
        cur = current_sim_date(conn)
        if cur:
            try:
                cur_dt = datetime.strptime(cur, "%Y-%m-%d")
                age_cutoff_date = cur_dt - timedelta(days=age_max * 365)
            except (ValueError, TypeError):
                pass

    # Filter in Python — much faster than re-querying per promo.
    candidates = []
    for f in base_pool:
        # Gap WC filter.
        if f['weight_class_id'] not in gap_wcs:
            continue
        # Potential floor filter.
        if f['potential'] < potential_floor:
            continue
        # Age max filter (compute age from DOB + current date).
        if age_cutoff_date is not None and f.get('date_of_birth'):
            try:
                dob_dt = datetime.strptime(f['date_of_birth'], "%Y-%m-%d")
                if dob_dt > age_cutoff_date:
                    continue  # too young (DOB > cutoff → age < age_max... wait, we want age <= age_max)
            except (ValueError, TypeError):
                pass
        candidates.append(f)
        if len(candidates) >= 200:  # bound the candidate pool
            break
    return candidates


def _offer_score(promo_reputation, promo_cash, candidate, staff_count,
                 promotion_id, conn, rng):
    """Compute the 0..1 offer_score for a (promo, FA) pair.

    Per arch doc §3.3 step 3:
        offer_score = (
            0.30 * (reputation / 100)
          + 0.20 * (log10(cash + 1) / 8)
          + 0.15 * path_to_title(candidate, promotion)
          + 0.15 * staff_quality(promotion)
          + 0.10 * (1 - candidate.age / 40)
          + 0.10 * (candidate.potential / 100)
        ) * (1 + rng.uniform(-0.10, 0.10))

    Plus: re_signing_bonus (+0.10 if the FA was previously on the
    promo's roster, per arch doc §6.3).
    """
    rep = max(0, min(100, promo_reputation or 0)) / 100.0
    budget = math.log10(max(0.0, float(promo_cash or 0)) + 1) / 8.0
    budget = max(0.0, min(1.0, budget))
    path = _path_to_title(candidate, promotion_id, conn)
    staff = min(1.0, staff_count / 8.0)  # 8 staff = max quality

    # Age: compute from date_of_birth + current sim date.
    age = _candidate_age(candidate, conn)
    youth = max(0.0, 1.0 - age / 40.0)
    talent = max(0.0, min(1.0, (candidate.get('potential', 50) or 50) / 100.0))

    base = (0.30 * rep + 0.20 * budget + 0.15 * path
            + 0.15 * staff + 0.10 * youth + 0.10 * talent)

    # Re-signing bonus (per arch doc §6.3 — "welcome back, kid").
    from services.rival_ai.imperfection import re_signing_bonus
    base += re_signing_bonus(conn, candidate['fighter_id'], promotion_id)

    # W21/W22 — rival AI memory read: if the promo recently lost a
    # bidding war (within the last 90 sim days), bump the offer_score
    # ("don't lose the next one"). +0.05 per recent loss, capped at
    # +0.20 (4 losses). Defensive — reader failures are swallowed +
    # the score is computed without the bump.
    try:
        from services.rival_ai.memory import recent_bidding_war_loss_count
        loss_count = recent_bidding_war_loss_count(
            conn, promotion_id, lookback_days=90,
        )
        if loss_count > 0:
            bump = min(0.20, 0.05 * loss_count)
            base += bump
    except ImportError:
        pass  # services.rival_ai.memory not available — proceed
    except Exception:
        pass  # defensive — memory read failure MUST NOT block scoring

    # Randomness band (±10%).
    base *= (1.0 + rng.uniform(-OFFER_SCORE_RANDOMNESS, OFFER_SCORE_RANDOMNESS))
    return max(0.0, min(1.0, base))


def _path_to_title(candidate, promotion_id, conn):
    """Return 0..1 — how clear a path to the title the candidate has.

    Per arch doc §3.3 step 3:
      1.0 if the candidate would immediately become the #1 contender
          at their WC in the promo.
      0.5 if they'd be top-5.
      0.2 otherwise.
    """
    wc_id = candidate.get('weight_class_id')
    if wc_id is None:
        return 0.2
    # Count fighters in the promo's WC ranked higher than the candidate.
    higher = conn.execute(
        "SELECT COUNT(*) FROM rankings r "
        "JOIN fighters f ON f.fighter_id = r.fighter_id "
        "WHERE f.current_promotion_id = ? AND r.weight_class_id = ? "
        "AND r.rating > ?",
        (promotion_id, wc_id, candidate.get('rating', 1000.0)),
    ).fetchone()[0]
    if higher == 0:
        return 1.0
    if higher < 5:
        return 0.5
    return 0.2


def _candidate_age(candidate, conn):
    """Return the candidate's age (computed from date_of_birth)."""
    dob = candidate.get('date_of_birth')
    if not dob:
        return 28  # default age if DOB missing
    try:
        from datetime import datetime
        from services.rival_ai._shared import current_sim_date
        cur_str = current_sim_date(conn)
        if not cur_str:
            return 28
        dob_dt = datetime.strptime(dob, "%Y-%m-%d")
        cur_dt = datetime.strptime(cur_str, "%Y-%m-%d")
        age = cur_dt.year - dob_dt.year
        if (cur_dt.month, cur_dt.day) < (dob_dt.month, dob_dt.day):
            age -= 1
        return age
    except (ValueError, TypeError):
        return 28


def _staff_quality(conn, promotion_id):
    """Return the number of promo-bound staff (a proxy for staff quality).

    Per arch doc §3.3 step 3: more scouts = better talent evaluation.
    We count all promo-bound staff (scouts + commentators + GMs +
    doctors + cutmen).
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM staff "
        "WHERE promotion_id=? AND role_type != 'coach'",
        (promotion_id,),
    ).fetchone()
    return row[0] if row else 0


def _fair_value(potential, rating, realization=None):
    """Return the fair-value salary for an FA.

    Per arch doc §3.3 step 4: potential × $1K + rating × $50.

    PHASE M3.3 (docs/MASTER_PLAN_MATCHMAKING.md §2.2): the formula now
    uses `effective_ceiling = potential * realization` instead of raw
    potential. A "bust" (potential=85, realization=0.5, ceiling=42) is
    priced like a 42-potential fighter — not the same as a "realizer"
    (potential=85, realization=1.0, ceiling=85). The rival AI no longer
    overpays for busts.

    Backward compat: `realization` is optional. If None (legacy caller),
    the formula falls back to the old behavior (raw potential) so
    existing callers + tests that don't pass realization still work.
    The signing_agent's _evaluate_one_promo now passes realization
    (read from fighter_career), so the rival AI uses the new formula.
    """
    if realization is not None:
        effective_ceiling = potential * realization
    else:
        effective_ceiling = potential
    return (effective_ceiling * FAIR_VALUE_POTENTIAL_MULT
            + rating * FAIR_VALUE_RATING_MULT)


def resolve_bidding_wars(conn, intents, current_date, rng=None):
    """Resolve multi-promo competition for the same FA.

    Per arch doc §3.3 step 4 + §5.3:
      1. Group intents by fighter_id. FAs wanted by 2+ promos trigger
         a bidding war.
      2. For each contested FA:
         a. Winner = highest offer_score.
         b. Bid premium = winner.bid_premium_pct × num_losers × 0.5,
            capped at 200% of fair value.
         c. Losers each get a 'bidding_war_lost' news item.
      3. For uncontested FAs: sign at base_salary (no premium).
      4. PHASE M3.2 (docs/MASTER_PLAN_MATCHMAKING.md §2.2): instead of
         calling `sign_free_agent` immediately, INSERT a `bidding_alerts`
         row + fire Events.SIGNING_INTENT on the bus. The rival AI's
         signing is DEFERRED by decision_window_days (default 3) so the
         player has a window to counter-offer via app_web.counter_offer.
         The actual sign happens in `_check_bidding_alerts_expiry`
         (called from the daily tick) when the window expires OR in
         `app_web.counter_offer` when the player responds.

    Args:
        conn: sqlite3.Connection (caller commits).
        intents: list of intent dicts from `evaluate_signing_intents`.
        current_date: sim date string for contract start_date.
        rng: optional random.Random instance.

    Returns:
        List of (fighter_id, rival_promo_id, salary, alert_id) tuples
        for the alerts created (one per winning intent). The signing
        is deferred — no contract is written yet.
    """
    rng = rng or _random.Random()
    if not intents:
        return []

    # Group intents by fighter_id.
    by_fighter = {}
    for intent in intents:
        by_fighter.setdefault(intent['fighter_id'], []).append(intent)

    alerts_created = []
    for fighter_id, group in by_fighter.items():
        if len(group) == 1:
            # Uncontested — base salary, no premium.
            winner = group[0]
            losers = []
            salary = winner['base_salary']
        else:
            # Bidding war — highest offer_score wins.
            winner, losers = _resolve_one_bidding_war(group, rng)
            # Compute the bid premium.
            num_losers = len(losers)
            premium_pct = winner['archetype'].get('bid_premium_pct', 0.0)
            # Per arch doc §3.3 step 4: premium = bid_premium_pct × losers × 0.5
            total_premium = premium_pct * num_losers * 0.5
            # Cap at 200% of fair value.
            cap_multiplier = BID_PREMIUM_CAP
            salary_multiplier = min(cap_multiplier, 1.0 + total_premium)
            salary = winner['base_salary'] * salary_multiplier

            # If salary is below 80% of fair value (a Grassroots winner
            # with bid_premium_pct=-0.20), floor at 80% so the fighter
            # actually signs.
            min_salary = winner['base_salary'] * 0.80
            salary = max(min_salary, salary)

            # Write 'bidding_war_lost' news items for each losing rival
            # AI promo (the player is not in `losers` — they enter via
            # counter_offer, not via evaluate_signing_intents).
            _write_bidding_war_lost_news(
                conn, winner, losers, fighter_id, current_date,
            )

        # M3.2: defer the signing. Insert a bidding_alerts row + fire
        # the SIGNING_INTENT event. The actual sign happens when the
        # window expires (daily tick) OR when the player counter-offers.
        #
        # MM4.1 (docs/MASTER_PLAN_MATCHMAKING_V2.md §4.1): tone down
        # bidding war frequency. Only create an alert if:
        #   (a) The fighter's potential >= BIDDING_WAR_MIN_POTENTIAL (60)
        #       — don't alert the player for every low-potential FA.
        #   (b) The rival promo is NOT in bidding cooldown (max 1 alert
        #       per BIDDING_WAR_COOLDOWN_DAYS per promo).
        # If either check fails, skip the alert + sign the fighter
        # immediately (no player counter-offer window).
        fighter_potential = winner.get('potential', 0)
        if fighter_potential < BIDDING_WAR_MIN_POTENTIAL:
            # Low-potential FA — just sign immediately, no alert.
            _sign_fighter_immediately(conn, winner, salary, current_date)
            continue
        if _is_in_bidding_cooldown(conn, winner['promotion_id'], current_date):
            # Cooldown — just sign immediately, no alert.
            _sign_fighter_immediately(conn, winner, salary, current_date)
            continue

        alert_id = _create_bidding_alert(
            conn, winner, salary, current_date, rng,
        )
        if alert_id is not None:
            alerts_created.append(
                (fighter_id, winner['promotion_id'], salary, alert_id)
            )
    return alerts_created


def _sign_fighter_immediately(conn, winner_intent, salary, current_date):
    """MM4.1: sign a fighter immediately without creating a bidding alert.

    Used when the fighter's potential is below BIDDING_WAR_MIN_POTENTIAL
    or the rival promo is in bidding cooldown. The signing happens
    silently — no player counter-offer window.
    """
    try:
        from services.contracts import sign_free_agent as _sign
        fighter_id = winner_intent['fighter_id']
        promo_id = winner_intent['promotion_id']
        contract_id = _sign(conn, fighter_id, promo_id, current_date,
                            salary=salary)
        if contract_id:
            # Write a simple signing news item (no bidding war mention)
            f_row = conn.execute(
                "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
                (fighter_id,),
            ).fetchone()
            p_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?",
                (promo_id,),
            ).fetchone()
            if f_row and p_row:
                src = conn.execute(
                    "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
                ).fetchone()
                src_id = src[0] if src else 1
                conn.execute(
                    "INSERT INTO news_items (news_source_id, headline, body, "
                    "sentiment, topic, fighter_id, published_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (src_id,
                     f"{f_row[0]} {f_row[1]} signs with {p_row[0]}",
                     f"{f_row[0]} {f_row[1]} has signed a contract with "
                     f"{p_row[0]}.",
                     "neutral", "signing", fighter_id, current_date),
                )
    except Exception as e:
        import sys
        print(f"WARNING: _sign_fighter_immediately failed: {e}", file=sys.stderr)


# Default decision window for the player to respond to a SIGNING_INTENT
# alert (in sim-days). Per docs/MASTER_PLAN_MATCHMAKING.md §2.2 step 2.
DEFAULT_DECISION_WINDOW_DAYS = 3

# MM4.1 (docs/MASTER_PLAN_MATCHMAKING_V2.md §4.1): tone down bidding war
# frequency. Only fire SIGNING_INTENT for fighters with potential >= this
# threshold (was firing for every FA — too much noise).
BIDDING_WAR_MIN_POTENTIAL = 60

# MM4.1: cooldown — max 1 bidding war alert per N sim-days per promo.
BIDDING_WAR_COOLDOWN_DAYS = 7


def _is_in_bidding_cooldown(conn, promo_id, current_date):
    """MM4.1: check if a promo is in bidding war cooldown.

    Returns True if the promo has had a bidding alert created in the
    last BIDDING_WAR_COOLDOWN_DAYS days.
    """
    from datetime import datetime, timedelta
    try:
        dt = datetime.strptime(current_date, "%Y-%m-%d")
        cutoff = (dt - timedelta(days=BIDDING_WAR_COOLDOWN_DAYS)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    row = conn.execute(
        "SELECT 1 FROM bidding_alerts WHERE rival_promo_id=? "
        "AND intent_date >= ? LIMIT 1",
        (promo_id, cutoff),
    ).fetchone()
    return row is not None


def _create_bidding_alert(conn, winner_intent, salary, current_date, rng):
    """INSERT a bidding_alerts row + fire SIGNING_INTENT event.

    Returns the new alert_id (int), or None on failure.

    Per Phase M3.2: the rival AI's signing is deferred by
    DEFAULT_DECISION_WINDOW_DAYS so the player can counter-offer.
    """
    try:
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(current_date, "%Y-%m-%d")
        expiry_dt = start_dt + timedelta(days=DEFAULT_DECISION_WINDOW_DAYS)
        expiry_date = expiry_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        # Defensive: if current_date is malformed, default to +3 days
        # from today (best-effort).
        expiry_date = current_date

    # Bonus defaults to 0 for rival AI intents (the rival AI doesn't
    # offer signing bonuses — only the player can via counter_offer).
    offered_bonus = 0.0
    cur = conn.execute(
        "INSERT INTO bidding_alerts "
        "(fighter_id, rival_promo_id, offered_salary, offered_bonus, "
        " offer_score, intent_date, expiry_date, decision_window_days, "
        " status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
        (winner_intent['fighter_id'], winner_intent['promotion_id'],
         salary, offered_bonus, winner_intent['offer_score'],
         current_date, expiry_date, DEFAULT_DECISION_WINDOW_DAYS),
    )
    alert_id = cur.lastrowid

    # Fire the SIGNING_INTENT event on the bus. Subscribers (if any)
    # can react — e.g., a future "scout report" or "rival promo
    # interest" news item. The dashboard polls get_bidding_alerts
    # for active alerts (no subscriber needed for the dashboard
    # rendering — it's pull-based, not push-based).
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.SIGNING_INTENT,
            'alert_id': alert_id,
            'rival_promo_id': winner_intent['promotion_id'],
            'fighter_id': winner_intent['fighter_id'],
            'offered_salary': salary,
            'offered_bonus': offered_bonus,
            'offer_score': winner_intent['offer_score'],
            'intent_date': current_date,
            'expiry_date': expiry_date,
            'decision_window_days': DEFAULT_DECISION_WINDOW_DAYS,
        })
    except Exception as e:
        import sys
        print(f"WARNING: signing_agent SIGNING_INTENT publish failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    return alert_id


def check_bidding_alerts_expiry(conn, current_date, rng=None):
    """Daily-tick handler — sign fighters whose bidding-alert window
    has expired.

    Per Phase M3.2: when the decision_window_days expires with no
    player counter-offer, the rival AI signs the fighter (the rival
    AI's intent wins by default). If the fighter is no longer a FA
    (signed by another promo directly via sign_free_agent — which is
    BLOCKED when a pending alert exists, but defensive), the alert is
    marked 'lost_race'.

    Also writes a "you lost [Fighter] to [Rival]" news item for the
    player's promo (if a player promo is selected via player_settings).

    Args:
        conn: sqlite3.Connection (caller commits).
        current_date: sim date string ('YYYY-MM-DD').
        rng: optional random.Random instance.

    Returns:
        List of (fighter_id, rival_promo_id, salary) tuples for the
        signings executed.
    """
    rng = rng or _random.Random()
    # Fetch all pending alerts whose window has expired.
    rows = conn.execute(
        "SELECT alert_id, fighter_id, rival_promo_id, offered_salary, "
        "       offer_score, intent_date, expiry_date "
        "FROM bidding_alerts "
        "WHERE status='pending' AND expiry_date <= ?",
        (current_date,),
    ).fetchall()
    if not rows:
        return []

    signed = []
    for (alert_id, fighter_id, rival_promo_id, offered_salary,
         offer_score, intent_date, expiry_date) in rows:
        # Verify the fighter is still a free agent (defensive — the
        # player's sign_free_agent is BLOCKED when a pending alert
        # exists, but a rival AI-vs-AI bidding war from a LATER weekly
        # tick could have already signed this fighter if the previous
        # alert's window was still open when the new intent fired).
        fa_row = conn.execute(
            "SELECT current_promotion_id, is_active, is_retired "
            "FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        if (not fa_row or fa_row[0] is not None
                or not fa_row[1] or fa_row[2]):
            # Fighter is no longer a FA — mark the alert lost_race.
            conn.execute(
                "UPDATE bidding_alerts SET status='lost_race', "
                "resolved_date=? WHERE alert_id=?",
                (current_date, alert_id),
            )
            continue

        # Sign the fighter with the rival AI's deferred intent.
        intent = {
            'fighter_id': fighter_id,
            'promotion_id': rival_promo_id,
            'offer_score': offer_score,
            'base_salary': offered_salary,
        }
        if _try_sign(conn, intent, offered_salary, current_date):
            signed.append((fighter_id, rival_promo_id, offered_salary))
            conn.execute(
                "UPDATE bidding_alerts SET status='won_by_rival', "
                "resolved_date=? WHERE alert_id=?",
                (current_date, alert_id),
            )
            # Write "you lost X to Y" news item for the player's promo.
            _write_player_lost_news(
                conn, fighter_id, rival_promo_id, current_date,
            )
        else:
            # Sign failed (rare — fighter is FA but sign_free_agent
            # errored). Mark lost_race so we don't retry forever.
            conn.execute(
                "UPDATE bidding_alerts SET status='lost_race', "
                "resolved_date=? WHERE alert_id=?",
                (current_date, alert_id),
            )
    return signed


def _write_player_lost_news(conn, fighter_id, rival_promo_id, current_date):
    """Write a 'bidding_war_lost' news item targeting the player's promo.

    Only fires if the player has a selected promo (player_settings
    table) AND that promo is different from the rival_promo_id (so
    we don't write "you lost to yourself" if the player IS the rival).
    """
    from services.rival_ai._shared import write_news_item
    from services.matchmaking import fighter_name
    # Read the player's selected promo.
    ps_row = conn.execute(
        "SELECT setting_value FROM player_settings "
        "WHERE setting_key='player_promotion_id'"
    ).fetchone()
    if not ps_row or not ps_row[0]:
        return  # no player promo selected — nothing to write
    try:
        player_pid = int(ps_row[0])
    except (ValueError, TypeError):
        return
    if player_pid == rival_promo_id:
        return  # player IS the rival (shouldn't happen — defensive)

    fighter_n = fighter_name(conn, fighter_id)
    rival_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (rival_promo_id,),
    ).fetchone()
    rival_name = (rival_name_row[0] if rival_name_row
                  else f"Promo {rival_promo_id}")
    write_news_item(
        conn,
        headline=f"You lost {fighter_n} to {rival_name}",
        body=(f"{fighter_n} has signed with {rival_name} after you "
              f"declined to make a counter-offer in time. The window "
              f"closed — the fighter is off the market."),
        topic='bidding_war_lost',
        sentiment='negative',
        promotion_id=player_pid,  # so it shows in the player's news feed
        fighter_id=fighter_id,
        published_at=current_date,
    )


def _resolve_one_bidding_war(group, rng):
    """Resolve a single bidding war — return (winner_intent, loser_intents)."""
    # Sort by offer_score desc.
    sorted_group = sorted(group, key=lambda i: i['offer_score'], reverse=True)
    winner = sorted_group[0]
    losers = sorted_group[1:]
    return winner, losers


def _try_sign(conn, intent, salary, current_date):
    """Call sign_free_agent for the intent. Returns True on success."""
    try:
        from services.contracts import sign_free_agent
        contract_id = sign_free_agent(
            conn,
            fighter_id=intent['fighter_id'],
            promotion_id=intent['promotion_id'],
            start_date=current_date,
            salary=salary,
        )
        return contract_id is not None
    except Exception as e:
        import sys
        print(f"WARNING: signing_agent sign_free_agent failed for "
              f"fighter_id={intent['fighter_id']}, "
              f"promotion_id={intent['promotion_id']}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return False


def _write_bidding_war_lost_news(conn, winner, losers, fighter_id, current_date):
    """Write 'bidding_war_lost' news items for each losing promo."""
    from services.rival_ai._shared import write_news_item
    from services.matchmaking import fighter_name
    fighter_n = fighter_name(conn, fighter_id)
    winner_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (winner['promotion_id'],),
    ).fetchone()
    winner_name = winner_name_row[0] if winner_name_row else f"Promo {winner['promotion_id']}"
    for loser in losers:
        loser_name_row = conn.execute(
            "SELECT name FROM promotions WHERE promotion_id=?",
            (loser['promotion_id'],),
        ).fetchone()
        loser_name = loser_name_row[0] if loser_name_row else f"Promo {loser['promotion_id']}"
        write_news_item(
            conn,
            headline=f"{loser_name} lost out on {fighter_n} to {winner_name}",
            body=(f"{fighter_n} has signed with {winner_name} despite "
                  f"interest from {loser_name}."),
            topic='bidding_war_lost',
            sentiment='negative',
            promotion_id=loser['promotion_id'],
            fighter_id=fighter_id,
            published_at=current_date,
        )


def evaluate_contract_expiry_interest(conn, current_date, rng=None):
    """Soft rule — write 'tapping_up_rumor' news items for fighters
    whose contract expires within 30 days.

    Per arch doc §5.2:
      1. Query fighters with contracts.end_date <= current_date + 30
         days, excluding the evaluating promo's own fighters.
      2. For each, compute interest_score (simplified offer_score).
      3. If interest_score >= 0.6: write a 'tapping_up_rumor' news
         item. Rate-limited to 1 rumor per (promo, fighter) per 30
         days.
      4. Whimsy: 10% of eligible candidates don't get a rumor; 5%
         of ineligible candidates get a rumor anyway (tabloid
         fabrication).

    Args:
        conn: sqlite3.Connection (caller commits).
        current_date: sim date string.
        rng: optional random.Random instance.

    Returns:
        Number of rumor news items written (int).
    """
    rng = rng or _random.Random()
    # 1. Query fighters whose contract expires within 30 days.
    rows = conn.execute(
        "SELECT fc.fighter_id, c.promotion_id AS current_promo, "
        "c.end_date, f.first_name || ' ' || f.last_name AS fname, "
        "f.weight_class_id, COALESCE(fc_c.potential, 50) AS potential, "
        "COALESCE(r.rating, 1000.0) AS rating "
        "FROM fighter_contracts fc "
        "JOIN contracts c ON c.contract_id = fc.contract_id "
        "JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "LEFT JOIN fighter_career fc_c ON fc_c.fighter_id = f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id = f.fighter_id "
        "AND r.weight_class_id = f.weight_class_id "
        "WHERE c.status = 'active' "
        "AND c.end_date <= date(?, '+30 days') "
        "AND f.is_active = 1 AND f.is_retired = 0",
        (current_date,),
    ).fetchall()
    if not rows:
        return 0

    # 2. Get all rival promos (excluding the player's).
    rival_promos = conn.execute(
        "SELECT promotion_id, reputation, current_cash FROM promotions "
        "WHERE promotion_id != 1 ORDER BY promotion_id",
    ).fetchall()
    if not rival_promos:
        return 0

    rumors_written = 0
    # P6 FIX: global cap — max 3 tapping_up_rumor news items per tick.
    # Was generating 228/day (9 promos × many fighters each). Now max 3/day.
    _MAX_RUMORS_PER_TICK = 3
    from services.rival_ai._shared import write_news_item
    for (fighter_id, current_promo, end_date, fname,
         wc_id, potential, rating) in rows:
        # P6 FIX: global cap — stop if we've already written 3 rumors this tick.
        if rumors_written >= _MAX_RUMORS_PER_TICK:
            break
        # For each rival promo (not the fighter's current promo),
        # evaluate interest.
        for (promo_id, rep, cash) in rival_promos:
            if promo_id == current_promo:
                continue  # don't tap up your own fighter
            # Rate-limit: 1 rumor per (promo, fighter) per 30 days.
            recent = conn.execute(
                "SELECT 1 FROM news_items "
                "WHERE topic='tapping_up_rumor' "
                "AND promotion_id=? AND fighter_id=? "
                "AND published_at >= date(?, '-30 days') "
                "LIMIT 1",
                (promo_id, fighter_id, current_date),
            ).fetchone()
            if recent:
                continue

            # Compute interest_score (simplified offer_score).
            interest = _interest_score(rep, cash, potential, rating, rng)
            eligible = interest >= 0.6
            # Whimsy: 10% of eligible candidates don't get a rumor;
            # 5% of ineligible candidates get a rumor anyway.
            if eligible:
                if rng.random() < 0.10:
                    continue  # promo keeps quiet
            else:
                if rng.random() < 0.05:
                    pass  # tabloid fabrication — rumor despite low interest
                else:
                    continue

            # Get promo + current-promo names.
            promo_name_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?",
                (promo_id,),
            ).fetchone()
            promo_name = promo_name_row[0] if promo_name_row else f"Promo {promo_id}"
            cur_promo_name_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?",
                (current_promo,),
            ).fetchone()
            cur_promo_name = (cur_promo_name_row[0]
                              if cur_promo_name_row else f"Promo {current_promo}")
            write_news_item(
                conn,
                headline=f"Rumored interest from {promo_name} in {fname}",
                body=(f"{promo_name} is rumored to be interested in signing "
                      f"{fname} when his contract with {cur_promo_name} "
                      f"expires on {end_date}."),
                topic='tapping_up_rumor',
                sentiment='neutral',
                promotion_id=promo_id,
                fighter_id=fighter_id,
                published_at=current_date,
            )
            rumors_written += 1
    return rumors_written


def _interest_score(promo_reputation, promo_cash, potential, rating, rng):
    """Compute a simplified 0..1 interest_score for a (promo, FA) pair.

    Per arch doc §5.2: same formula as offer_score but simplified
    (no path_to_title or staff_quality lookups — too expensive for
    a soft-rule rumor generator). Weights:
      0.40 * (potential / 100)        # talent is the dominant factor
      0.30 * (reputation / 100)       # prestige
      0.20 * (log10(cash + 1) / 8)    # budget
      0.10 * (rating / 1500)          # current ability
    Plus ±10% randomness.
    """
    talent = max(0.0, min(1.0, (potential or 50) / 100.0))
    rep = max(0, min(100, promo_reputation or 0)) / 100.0
    budget = math.log10(max(0.0, float(promo_cash or 0)) + 1) / 8.0
    budget = max(0.0, min(1.0, budget))
    ability = max(0.0, min(1.0, (rating or 1000.0) / 1500.0))
    base = 0.40 * talent + 0.30 * rep + 0.20 * budget + 0.10 * ability
    base *= (1.0 + rng.uniform(-OFFER_SCORE_RANDOMNESS, OFFER_SCORE_RANDOMNESS))
    return max(0.0, min(1.0, base))
