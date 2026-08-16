"""CAGE EMPIRE Rival AI — Matchmaker (Task ID RIVAL-AI-P2to4, Phase 2).

Per docs/RIVAL_AI_ARCHITECTURE.md §3.2 — biased matchup scoring +
card assembly for rival events. Wraps the existing player-facing
`_build_main_event` / `_build_co_main` / `_build_featured_prelim` /
`_build_prelim` functions in `services/matchmaking.py` and injects
archetype-aware imperfection (15-50% non-optimal matchups).

The matchmaker REUSES the existing card-builder functions for the
"safe path" (the optimal champ-vs-#1 main event). For the
"showcase" + "head-scratcher" paths (per arch doc §3.2), it picks
pairings using the matchup scoring function + the bias injector.

CONVENTIONS compliance:
  §5  — No new tables. Reads existing `fighters` + `fighter_career`
        + `rankings` + `titles` + `fight_history` + `rivalries` only.
  §13 — Design Law: this is the "Conflict" pillar — rival promos put
        on their own cards, build their own champions, create their
        own storylines (the player notices via the news feed).
  §14 — Voice Layer: N/A — no player-facing text (the news items
        come from the event_scheduler's "scheduling announcement").
  §15 — Event Bus: N/A — no subscribers. Called by event_scheduler.
"""

import random as _random
from datetime import datetime, timedelta


# Per arch doc §3.2 — the matchup scoring formula weights.
SCORE_WEIGHT_MARKETABILITY = 35.0
SCORE_WEIGHT_COMPETITIVENESS = 30.0
SCORE_WEIGHT_STORYLINE = 20.0
SCORE_WEIGHT_DEVELOPMENT = 15.0

# Top-N sample sizes per card slot (per arch doc §3.2 "Card assembly").
# These drive how many candidate pairs the bias injector considers
# before picking. Higher N for prelims (more flexibility); lower N
# for the main event (only the best contenders should be considered).
TOP_N_BY_SLOT = {
    'main_event':      5,
    'co_main':         8,
    'featured_prelim': 12,
    'prelim':          20,  # all available — prelims fill to card_size
}


def build_card(conn, promotion_id, event_date, archetype=None, rng=None):
    """Build a fight card for a rival promotion's event.

    Per arch doc §3.2:
      1. Fetch the available-fighters pool via the existing
         `_get_available_fighters_for_card` (filtered by event_date).
      2. Group by weight class via `_group_available_by_wc`.
      3. For each card slot (main_event → co_main → featured_prelims →
         prelims), apply the bias injector:
            - safe_pct of the time:    use the existing optimal
                                       builder (champ vs #1 etc.)
            - (1-safe_pct)*0.6:        showcase (high marketability,
                                       low competitiveness)
            - (1-safe_pct)*0.4:        head-scratcher (random pair,
                                       ignores score — may produce
                                       grappler-vs-grappler, squashes,
                                       rematches-too-soon)
      4. Return a list of 5-13 fight dicts.

    Args:
        conn: sqlite3.Connection (read-only — no INSERTs here).
        promotion_id: the rival promotion whose roster to build from.
        event_date: the event's date string ('YYYY-MM-DD'), used to
            filter fighter availability (rest days, injuries,
            suspensions, already-booked).
        archetype: optional pre-fetched archetype dict (already
            state-modified + recency-modified by the caller via
            budget_manager.get_modified_archetype). If None, looks
            up via `archetypes.get_archetype` (unmodified).
        rng: optional random.Random instance for reproducibility.

    Returns:
        List of fight dicts (length = archetype.card_size[0]..[1]).
        Empty list if no eligible fighters.
    """
    if archetype is None:
        from services.rival_ai.archetypes import get_archetype
        archetype = get_archetype(promotion_id, conn)
        if archetype is None:
            return []
    rng = rng or _random.Random()

    # Reuse the existing roster query (4-way LEFT JOIN over fighters
    # + fighter_career + rankings + injuries + suspensions). The
    # result is cached per (promotion_id, event_date) by the
    # _shared.roster_cache helpers.
    from services.rival_ai._shared import (
        roster_cache_get, roster_cache_put,
    )
    available = roster_cache_get(promotion_id, event_date)
    if available is None:
        from services.matchmaking import _get_available_fighters_for_card
        available = _get_available_fighters_for_card(
            conn, promotion_id, before_date=event_date,
        )
        roster_cache_put(promotion_id, event_date, available)

    if len(available) < 2:
        return []

    # MM3.3 parity — Last-minute rejection for rival AI. If the event
    # is ≤14 days away, filter out fighters who would reject short-
    # notice bouts based on personality (high professionalism + low
    # risk_taking = rejects). This ensures the rival AI follows the
    # same rules as the player's book_fight (which checks willingness
    # at booking time). Per docs/MASTER_PLAN_MATCHMAKING_V2.md §3.3.
    from datetime import datetime, timedelta
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d")
        sim_row = conn.execute(
            "SELECT current_date FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        sim_date = sim_row[0] if sim_row else event_date
        sim_dt = datetime.strptime(sim_date, "%Y-%m-%d")
        days_until_event = (event_dt - sim_dt).days
    except (ValueError, TypeError):
        days_until_event = 30  # defensive — assume not short notice

    if days_until_event <= 14:
        # Short notice — filter out fighters who would reject
        available = _filter_short_notice_rejections(conn, available, days_until_event)
        if len(available) < 2:
            return []

    # Compute age for each fighter (used by development_value).
    _augment_with_age(conn, available)

    # Group available fighters by weight class.
    from services.matchmaking import _group_available_by_wc, _same_gender
    fighters_by_wc = _group_available_by_wc(available)

    # Resolve card size from the (possibly modified) archetype.
    target_min, target_max = archetype['card_size']
    booked_ids = set()
    card_fights = []

    # ---- Main event ----
    main_event = _build_slot_with_bias(
        conn, promotion_id, fighters_by_wc, booked_ids,
        slot='main_event', archetype=archetype, rng=rng,
        title_pct=archetype['main_event_title_pct'],
    )
    if main_event is None:
        return []  # can't book a main event → no card
    card_fights.append(main_event)
    booked_ids.add(main_event['fighter_a'])
    booked_ids.add(main_event['fighter_b'])
    main_event_wc = main_event['weight_class_id']

    # ---- Co-main event (exclude main event's WC for variety) ----
    if len(card_fights) < target_max:
        co_main = _build_slot_with_bias(
            conn, promotion_id, fighters_by_wc, booked_ids,
            slot='co_main', archetype=archetype, rng=rng,
            exclude_wc=main_event_wc,
        )
        if co_main is not None:
            card_fights.append(co_main)
            booked_ids.add(co_main['fighter_a'])
            booked_ids.add(co_main['fighter_b'])

    # ---- Featured prelims (1-3 depending on card size) ----
    featured_count = 2 if target_max >= 7 else 1
    for i in range(featured_count):
        if len(card_fights) >= target_max:
            break
        exclude_wc = main_event_wc if i == 0 else None
        fp = _build_slot_with_bias(
            conn, promotion_id, fighters_by_wc, booked_ids,
            slot='featured_prelim', archetype=archetype, rng=rng,
            exclude_wc=exclude_wc,
        )
        if fp is None and exclude_wc is not None:
            fp = _build_slot_with_bias(
                conn, promotion_id, fighters_by_wc, booked_ids,
                slot='featured_prelim', archetype=archetype, rng=rng,
                exclude_wc=None,
            )
        if fp is None:
            break
        card_fights.append(fp)
        booked_ids.add(fp['fighter_a'])
        booked_ids.add(fp['fighter_b'])

    # ---- Prelims (fill the rest up to target_max) ----
    while len(card_fights) < target_max:
        pr = _build_slot_with_bias(
            conn, promotion_id, fighters_by_wc, booked_ids,
            slot='prelim', archetype=archetype, rng=rng,
        )
        if pr is None:
            break
        card_fights.append(pr)
        booked_ids.add(pr['fighter_a'])
        booked_ids.add(pr['fighter_b'])

    # Defensive: ensure at least target_min fights if possible.
    return card_fights


def _augment_with_age(conn, available):
    """Mutate each fighter dict in `available` to add an `age` key
    computed from the fighter's date_of_birth + the current sim date.

    Used by `development_value` (which checks age <= 26 for prospects)
    + `_is_gatekeeper` (which checks age >= 30). The base
    `_get_available_fighters_for_card` query doesn't include age.
    """
    from services.rival_ai._shared import current_sim_date
    cur_str = current_sim_date(conn)
    if not cur_str:
        return
    try:
        cur_dt = datetime.strptime(cur_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return
    # Batch fetch DOBs in a single query (avoid N+1).
    fighter_ids = [f['fighter_id'] for f in available]
    if not fighter_ids:
        return
    placeholders = ",".join("?" * len(fighter_ids))
    rows = conn.execute(
        f"SELECT fighter_id, date_of_birth FROM fighters "
        f"WHERE fighter_id IN ({placeholders})",
        fighter_ids,
    ).fetchall()
    dob_by_id = {fid: dob for (fid, dob) in rows}
    for f in available:
        dob = dob_by_id.get(f['fighter_id'])
        if not dob:
            f['age'] = 0
            continue
        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
            age = cur_dt.year - dob_dt.year
            if (cur_dt.month, cur_dt.day) < (dob_dt.month, dob_dt.day):
                age -= 1
            f['age'] = age
        except (ValueError, TypeError):
            f['age'] = 0


def _build_slot_with_bias(conn, promotion_id, fighters_by_wc, booked_ids,
                          slot, archetype, rng, exclude_wc=None,
                          title_pct=None):
    """Pick one fight for a card slot, applying the bias injector.

    Per arch doc §3.2:
      - safe_pct of the time:    use the existing optimal builder.
      - (1-safe_pct)*0.6:        showcase (high marketability, low
                                 competitiveness — the prospect-vs-can).
      - (1-safe_pct)*0.4:        head-scratcher (random pair).

    For the main_event slot, if `title_pct` is set and the rng roll
    lands below it, we REQUIRE a title fight (champion vs #1) via
    the existing `_build_main_event` — this is the "safe path" forced
    for the main event so title fights happen at the archetype's
    expected rate.

    Returns the fight dict (with card_slot set) or None.
    """
    safe_pct = archetype['matchmaking_safe_pct']
    showcase_pct = (1.0 - safe_pct) * 0.6
    head_scratcher_pct = (1.0 - safe_pct) * 0.4

    roll = rng.random()
    # Main event title-fight enforcement.
    if (slot == 'main_event' and title_pct is not None
            and roll < title_pct):
        # Force the optimal title-fight main event (the existing
        # _build_main_event picks champion vs #1 contender or vacant
        # title). This is the "70% of main events are title fights"
        # rule from arch doc §2.2.
        from services.matchmaking import _build_main_event
        fight = _build_main_event(conn, promotion_id, fighters_by_wc, booked_ids)
        if fight is not None:
            fight['card_slot'] = 'main_event'
            return fight
        # No title fight possible → fall through to non-title main event.

    if roll < safe_pct:
        # Safe path — use the existing optimal builder.
        fight = _safe_path_build(conn, promotion_id, fighters_by_wc,
                                  booked_ids, slot, exclude_wc)
        if fight is not None:
            return fight
        # Fallback: no safe-path fight possible → try showcase.

    if roll < safe_pct + showcase_pct:
        # Showcase path — high marketability, low competitiveness.
        fight = _showcase_pair(fighters_by_wc, booked_ids, exclude_wc, rng)
        if fight is not None:
            fight['card_slot'] = slot
            fight['is_title_fight'] = 0
            fight['scheduled_rounds'] = _rounds_for_slot(slot)
            return fight

    # Head-scratcher path — random pair (ignores score).
    fight = _head_scratcher_pair(fighters_by_wc, booked_ids, exclude_wc, rng)
    if fight is not None:
        fight['card_slot'] = slot
        fight['is_title_fight'] = 0
        fight['scheduled_rounds'] = _rounds_for_slot(slot)
        return fight

    # Final fallback: try the safe path (any matchup is better than
    # an empty slot). If even that fails, return None.
    return _safe_path_build(conn, promotion_id, fighters_by_wc,
                             booked_ids, slot, exclude_wc)


def _safe_path_build(conn, promotion_id, fighters_by_wc, booked_ids,
                      slot, exclude_wc):
    """Use the existing player-facing card builders for the 'safe path'.

    Delegates to:
      - main_event:      services.matchmaking._build_main_event
      - co_main:         services.matchmaking._build_co_main
      - featured_prelim: services.matchmaking._build_featured_prelim
      - prelim:          services.matchmaking._build_prelim

    The existing builders produce optimal matchups (champ vs #1,
    highest-rated pairs, etc.). Returns the fight dict (with card_slot
    set) or None.
    """
    from services.matchmaking import (
        _build_main_event, _build_co_main, _build_featured_prelim, _build_prelim,
    )
    if slot == 'main_event':
        fight = _build_main_event(conn, promotion_id, fighters_by_wc, booked_ids)
    elif slot == 'co_main':
        fight = _build_co_main(fighters_by_wc, booked_ids, exclude_wc=exclude_wc)
    elif slot == 'featured_prelim':
        fight = _build_featured_prelim(fighters_by_wc, booked_ids, exclude_wc=exclude_wc)
    else:  # prelim
        fight = _build_prelim(fighters_by_wc, booked_ids)
    if fight is not None:
        fight['card_slot'] = slot
    return fight


def _showcase_pair(fighters_by_wc, booked_ids, exclude_wc, rng):
    """Pick a 'showcase' pair: high marketability, low competitiveness.

    Per arch doc §3.2 showcase path: the prospect-vs-can fight. The
    matchmaker picks a pair where:
      - One fighter has high rating (the prospect/star)
      - The other has lower rating (the showcase opponent)
      - Same weight class + same gender (defensive)

    We score all candidate pairs by marketability - competitiveness
    (high marketability bonus, low competitiveness bonus) and pick
    from the top-N.
    """
    candidates = _collect_candidate_pairs(fighters_by_wc, booked_ids, exclude_wc)
    if not candidates:
        return None
    # Score each pair: high marketability - low competitiveness.
    scored = []
    for (f_a, f_b) in candidates:
        market = _marketability(f_a, f_b)
        comp = _competitiveness(f_a, f_b)
        # Showcase score: high market + (1 - competitiveness).
        sc = market * 0.6 + (1.0 - comp) * 0.4
        scored.append((sc, f_a, f_b))
    scored.sort(key=lambda x: x[0], reverse=True)
    # Pick from top-N (N=5 for showcase).
    top = scored[:5]
    if not top:
        return None
    _, f_a, f_b = rng.choice(top)
    return {
        'weight_class_id': f_a['weight_class_id'],
        'fighter_a': f_a['fighter_id'],
        'fighter_b': f_b['fighter_id'],
    }


def _head_scratcher_pair(fighters_by_wc, booked_ids, exclude_wc, rng):
    """Pick a 'head-scratcher' pair: random pair ignoring score.

    Per arch doc §6.4 matchup mistakes: this is the path that
    intentionally books BAD matchups 5-20% of the time:
      - Boring stylistic clashes (grappler vs grappler)
      - Squashes (top contender vs rookie)
      - Rematches too soon
      - Ranking inversions

    We don't try to pick a *specific* bad matchup type — we just
    ignore score + pick a random pair from the candidate pool. The
    randomness naturally produces all 4 mistake types over time.
    """
    candidates = _collect_candidate_pairs(fighters_by_wc, booked_ids, exclude_wc)
    if not candidates:
        return None
    f_a, f_b = rng.choice(candidates)
    return {
        'weight_class_id': f_a['weight_class_id'],
        'fighter_a': f_a['fighter_id'],
        'fighter_b': f_b['fighter_id'],
    }


def _collect_candidate_pairs(fighters_by_wc, booked_ids, exclude_wc):
    """Yield (fighter_a, fighter_b) pairs eligible for matchmaking.

    For each weight class (excluding `exclude_wc`), pair up the top-N
    available fighters (excluding `booked_ids`). Returns a list of
    (f_a, f_b) tuples — each pair is same-gender (defensive).

    Limits the candidate pool to avoid combinatorial explosion: only
    the top-8 fighters per WC are considered (sorted by rating desc).
    """
    from services.matchmaking import _same_gender
    pairs = []
    for wc_id, fighters in fighters_by_wc.items():
        if exclude_wc is not None and wc_id == exclude_wc:
            continue
        avail = [f for f in fighters if f['fighter_id'] not in booked_ids]
        # Sort by rating desc + take top-8 (keeps the pool bounded).
        avail.sort(key=lambda f: f.get('rating', 1000.0), reverse=True)
        avail = avail[:8]
        if len(avail) < 2:
            continue
        # Pair each fighter with up to 3 same-gender partners.
        for i, f_a in enumerate(avail):
            count = 0
            for j, f_b in enumerate(avail):
                if i == j:
                    continue
                if not _same_gender(f_a, f_b):
                    continue
                pairs.append((f_a, f_b))
                count += 1
                if count >= 3:
                    break
    return pairs


def _filter_short_notice_rejections(conn, available, days_until_event):
    """MM3.3 parity — filter out fighters who would reject short-notice bouts.

    Mirrors the player's book_fight willingness check: fighters with
    high professionalism + low risk_taking reject short-notice fights.
    This ensures the rival AI follows the same rules as the player.

    Per docs/MASTER_PLAN_MATCHMAKING_V2.md §3.3.
    """
    if not available:
        return available
    # Batch-fetch personality for all available fighters
    fighter_ids = [f['fighter_id'] for f in available]
    if not fighter_ids:
        return available
    placeholders = ",".join("?" * len(fighter_ids))
    pers_rows = conn.execute(
        f"SELECT fighter_id, risk_taking, ambition, professionalism, patience "
        f"FROM fighter_personality WHERE fighter_id IN ({placeholders})",
        fighter_ids,
    ).fetchall()
    pers_map = {r[0]: {'risk_taking': r[1], 'ambition': r[2],
                       'professionalism': r[3], 'patience': r[4]}
                for r in pers_rows}

    filtered = []
    for f in available:
        fid = f['fighter_id']
        p = pers_map.get(fid)
        if p is None:
            # No personality data — assume willing (defensive)
            filtered.append(f)
            continue
        # Same willingness formula as book_fight (app_web.py MM3.3)
        willingness = 50
        willingness += ((p.get('risk_taking') or 50) - 50) * 0.3
        willingness += ((p.get('ambition') or 50) - 50) * 0.2
        willingness -= ((p.get('professionalism') or 50) - 50) * 0.3
        willingness -= ((p.get('patience') or 50) - 50) * 0.2
        if willingness >= 30:
            filtered.append(f)
        # else: fighter rejects short-notice — exclude from available
    return filtered


def _marketability(fighter_a, fighter_b):
    """Compute the 0..1 marketability score for a pair.

    Delegates to the canonical ``interpretation.marketability.
    pairwise_marketability`` (Tier 2 / W38 — one authoritative
    calculation per meaning). The legacy signature is preserved —
    accepts the matchmaker's pre-loaded fighter dicts (the canonical
    function supports both dicts and IDs; passing ``conn=None`` tells
    it to use the dicts verbatim without a DB round-trip).

    Per arch doc §3.2:
        marketability(A, B) =
            clamp((rating_A + rating_B) / 2 / 1500, 0, 1)
          + 0.20 if either fighter has win_streak >= 3
          + 0.15 if either is a current champion
          + 0.10 if both have reputation >= 70
        (capped at 1.0)
    """
    # Lazy import — keeps matchmaker importable in headless test
    # setups where the interpretation package may not be wired.
    try:
        from interpretation.marketability import pairwise_marketability
        return pairwise_marketability(None, fighter_a, fighter_b)
    except ImportError:
        # Fallback — original implementation (verbatim).
        rating_a = fighter_a.get('rating', 1000.0)
        rating_b = fighter_b.get('rating', 1000.0)
        base = ((rating_a + rating_b) / 2.0) / 1500.0
        base = max(0.0, min(1.0, base))
        if fighter_a.get('win_streak', 0) >= 3 or fighter_b.get('win_streak', 0) >= 3:
            base += 0.20
        # "Current champion" check would need a titles lookup — skip for
        # performance (the +/- 0.15 is a minor factor; the safe path's
        # _build_main_event handles title fights explicitly).
        if fighter_a.get('potential', 0) >= 70 and fighter_b.get('potential', 0) >= 70:
            base += 0.10  # reputation proxy — both have star potential
        return min(1.0, base)


def _competitiveness(fighter_a, fighter_b):
    """Compute the 0..1 competitiveness score for a pair.

    Per arch doc §3.2:
        competitiveness(A, B) = 1 - abs(rating_A - rating_B) / 400
        # 1 if equal, 0 if 400+ apart
    """
    rating_a = fighter_a.get('rating', 1000.0)
    rating_b = fighter_b.get('rating', 1000.0)
    diff = abs(rating_a - rating_b)
    return max(0.0, 1.0 - diff / 400.0)


def _rounds_for_slot(slot):
    """Return the scheduled_rounds for a card slot.

    Main event title fights = 5 rounds (handled by _build_main_event).
    All other fights = 3 rounds (the _NON_TITLE_FIGHT_ROUNDS constant
    in services.matchmaking).
    """
    from services.matchmaking import _NON_TITLE_FIGHT_ROUNDS
    return _NON_TITLE_FIGHT_ROUNDS


def _matchup_score(fighter_a, fighter_b, conn=None):
    """Compute the 0-100 matchup score for a fighter pair.

    Per arch doc §3.2:
        score = 35 * marketability(A,B)
              + 30 * competitiveness(A,B)
              + 20 * storyline(A,B)
              + 15 * development_value(A,B)

    Each component is a 0..1 float; the weighted sum gives 0..100.

    Args:
        fighter_a, fighter_b: dict-like rows from the roster cache
            (must include rating, weight_class_id, gender, win_streak,
            loss_streak, potential, age, reputation, style_archetype).
        conn: optional sqlite3.Connection for storyline lookups
            (common opponents, active rivalries).

    Returns:
        Float 0..100.
    """
    market = _marketability(fighter_a, fighter_b)
    comp = _competitiveness(fighter_a, fighter_b)
    story = 0.5  # default — only computed if conn is provided
    dev = 0.5    # default
    if conn is not None:
        try:
            from services.rival_ai.imperfection import (
                storyline_score, development_value,
            )
            story = storyline_score(
                conn,
                fighter_a['fighter_id'],
                fighter_b['fighter_id'],
                fighter_a.get('weight_class_id'),
            )
            dev = development_value(fighter_a, fighter_b)
        except Exception:
            pass
    score = (
        SCORE_WEIGHT_MARKETABILITY * market
        + SCORE_WEIGHT_COMPETITIVENESS * comp
        + SCORE_WEIGHT_STORYLINE * story
        + SCORE_WEIGHT_DEVELOPMENT * dev
    )
    return max(0.0, min(100.0, score))


def _bias_injector(candidates, archetype, slot, exclude_weight_class=None,
                   rng=None):
    """Apply the archetype bias to a candidate-pair list.

    Per arch doc §3.2 "Realistic imperfection":
        safe_pct = archetype.matchmaking_safe_pct
        showcase_pct = (1 - safe_pct) * 0.6
        head_scratcher_pct = (1 - safe_pct) * 0.4

        roll = rng.random()
        if roll < safe_pct:               pick highest-scored pair
        elif roll < safe_pct + showcase_pct: pick a showcase pair
        else:                              pick a random pair (head-scratcher)

    Args:
        candidates: list of (score, fight_dict) tuples, sorted desc.
        archetype: the archetype dict (for safe_pct).
        slot: 'main_event' / 'co_main' / 'featured_prelim' / 'prelim'
            (drives the top-N sample size).
        exclude_weight_class: optional weight_class_id to exclude
            (for co_main variety — exclude the main event's WC).
        rng: optional random.Random instance.

    Returns:
        One fight dict (the selected pair), or None if candidates
        is empty.
    """
    if not candidates:
        return None
    rng = rng or _random.Random()
    safe_pct = archetype['matchmaking_safe_pct']
    showcase_pct = (1.0 - safe_pct) * 0.6
    # head_scratcher_pct = (1 - safe_pct) * 0.4 (the remainder)

    roll = rng.random()
    if roll < safe_pct:
        # Safe path — pick the highest-scored pair.
        return candidates[0][1]
    elif roll < safe_pct + showcase_pct:
        # Showcase — pick from top-N (higher-scored pairs but not
        # necessarily the absolute top).
        top_n = TOP_N_BY_SLOT.get(slot, 5)
        top = candidates[:top_n]
        if not top:
            return candidates[0][1]
        return rng.choice(top)[1]
    else:
        # Head-scratcher — pick a random pair from the entire pool.
        return rng.choice(candidates)[1]
