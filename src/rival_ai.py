"""CAGE EMPIRE Rival Promotion AI System (Task ID 25).

The user's concern: rival promotions were inert. Only the player's
promotion (promotion_id=1, Alpha Combat) scheduled events and
resolved fights. Rival promotions sat on their rosters doing nothing
— the world felt static outside the player's bubble.

This module gives every rival promotion its own booking loop:
  - Schedule events (call app.schedule_next_event)
  - Resolve fights (call app.resolve_next_fight with promotion_id)
  - Sign free agents (call app.sign_free_agent)

Driven by the existing promotions.ai_aggression (0-100) and
ai_spending_style ('conservative' / 'balanced' / 'aggressive')
columns — no schema change required (both columns have existed since
v2.0.0 / Task 14.6, seeded by world_phase2).

Entirely event-bus-driven (CONVENTIONS §15.4 — no new inline side
effects added to run_tick). Subscribes to TICK_ADVANCED.

  On EVERY tick (daily):
    For each rival promotion (promotion_id != 1):
      1. If the promotion has any scheduled event whose event_date
         <= current_date (i.e. the show is tonight or already past)
         AND that event has unresolved fights, resolve ALL unresolved
         fights on that event in a single tick. An MMA event is a
         SINGLE-NIGHT SHOW — the whole card resolves on the evening
         of event_date, not spread across weeks.

  On WEEKLY ticks (current_day % 7 == 0 — matches the cadence used
  by morale, agent_offers, and other weekly systems):
    For each rival promotion (promotion_id != 1):
      1. If the promotion has no scheduled event, call
         schedule_next_event to book the next card.
      2. 10% chance per week of signing a free agent (if roster < 50).

The AI's booking decisions are influenced by ai_aggression:
  Low (0-30): conservative — schedule events every 6 weeks (slower
              cadence, safer matchmaking — favors veterans).
  Medium (31-60): balanced — every 4 weeks (default cadence).
  High (61-100): aggressive — every 2 weeks (faster cadence, pushes
                 prospects into action sooner, riskier matchmaking).

The AI's free agent signings are influenced by ai_spending_style:
  'conservative': only signs free agents with potential >= 50.
  'balanced': signs any free agent with potential >= 30.
  'aggressive': signs any free agent (including low-potential gambles).

The AI uses the SAME schedule_next_event + resolve_next_fight +
sign_free_agent functions the player uses. This means ALL the event
bus subscribers (news, social, morale, finance, punditry) fire for
rival promotion fights too — creating a living world where things
happen across all promotions, not just the player's.

CRITICAL: the rival AI does NOT resolve fights for the player's
promotion (promotion_id=1). The player resolves their own fights
manually via the UI "Resolve Fight" button. The AI only handles
rival promotions. This is enforced by the promotion_id != 1 filter
in _process_rival_promotions and by passing promotion_id=X to
resolve_next_fight (which filters the pick-query to that promotion).

DESIGN DECISIONS (FIX-Critical, v3.7.x):
  - SINGLE-NIGHT RESOLUTION. The OLD code resolved ONE fight per
    weekly tick per rival promotion (a 5-fight card took 5 weeks).
    That's not how MMA works — an event is one evening. The new
    code resolves ALL fights on an event in a single tick, the
    moment the event's event_date has arrived (event_date <=
    current_date). This means a 10-fight RFL card resolves in ONE
    tick (the night of the show), not 10 ticks.
  - Daily event-date check. We poll every tick (not just weekly)
    for events whose event_date has arrived. This is cheap (one
    SELECT per rival promotion per tick) and prevents the situation
    where an event is scheduled for a Tuesday but no resolution
    fires until the next weekly tick (a Saturday). The show must
    go on, on its scheduled date.
  - Weekly scheduling + free agent signing. The schedule_next_event
    + sign_free_agent loops remain weekly — they don't need to fire
    daily (scheduling an event a few days earlier vs later is
    imperceptible; free agent signings weekly is already enough
    fluidity).

CONVENTIONS compliance:
  §5  — One table-group per task. NO new table — this module reads
        existing promotions.ai_aggression + ai_spending_style (both
        added v2.0.0) and reuses existing schedule_next_event,
        resolve_next_fight, sign_free_agent functions.
  §13 — Design Law: Conflict (rival promotions now run cards, build
        champions, create storylines the player notices — "the
        featherweight over in RFL just knocked out his third in a
        row" or "RFL booked an upset, the champ is gone"). Puppet
        Master fantasy ("the sport evolves" — now it actually does,
        outside the player's promotion). Empire Builder (the player
        has real rivals competing for prestige, talent, and fan
        attention — no longer alone in a static world).
  §14 — Voice Layer: the rival AI writes NO player-facing text
        directly. It uses existing functions (schedule_next_event,
        resolve_next_fight, sign_free_agent) that already route
        through the voice layer for their news items. The fight
        results, signing news, and event hype all flow through the
        news engine subscribers that already use voice descriptors.
  §15 — Event Bus: entirely event-driven. Subscribes to TICK_ADVANCED.
        Does NOT modify run_tick or resolve_next_fight (only adds
        an optional promotion_id parameter to the pick-query, which
        is backward-compatible — see resolve_next_fight docstring).

USAGE:
  from rival_ai import register_subscribers
  register_subscribers()  # call once at startup (UI App.__init__,
                          # test setup). Safe to call multiple times.

DESIGN DECISIONS (FIX-Critical, updated):
  - Daily event-date check (cheap SELECT) + single-night resolution.
    An MMA event resolves ALL its fights the evening of event_date —
    the OLD weekly-resolution pattern was unrealistic (spread a card
    across weeks). Now the show goes on, on its scheduled date.
  - Weekly scheduling + free agent signing. schedule_next_event +
    sign_free_agent remain weekly (scheduling cadence doesn't need
    daily granularity; free agent signings weekly is enough).
  - The AI uses EXISTING functions — no reimplemented matchmaking,
    no reimplemented fight resolution. This is critical: it means
    every event bus subscriber fires for rival fights, creating a
    truly living world (rival news, rival social posts, rival
    punditry analyses, rival morale swings, etc.).
  - The 10% free-agent-signing chance is per WEEK per rival
    promotion (not per day). With ~8 rival promotions, that's ~0.8
    signings per sim week on average — enough to keep rival rosters
    fluid without dominating the free agent market.
  - The 50-fighter roster cap is defensive — a rival promotion
    booking 1 event per 2-6 weeks doesn't need more than 50 fighters.
    The cap prevents roster bloat (and the processor cost of picking
    matchups from huge rosters).
  - ai_aggression influences scheduling cadence (high = faster) but
    NOT matchmaking — _pick_matchup is random for now (Task 10 will
    add ranking-proximity; Task 22 will add rivalry logic). The
    aggression → cadence mapping gives the player-visible difference
    between a conservative rival (1 card every 6 weeks) and an
    aggressive one (1 card every 2 weeks).
  - We lazy-import app inside the subscriber (not at module load) to
    avoid a circular dependency (app.py imports register_subscribers
    at App.__init__ — if rival_ai imported app at module load, the
    import would fail when app.py is first loaded).

PHASE 1 ADDITION (Task RIVAL-AI-P1):
  - On the first TICK_ADVANCED after v3.14.0 migration, the
    subscriber calls `services.rival_ai.archetypes.assign_all_
    archetypes(conn)` to populate the 3 new columns
    (`promotions.ai_archetype` + `ai_scheduling_day_of_week` +
    `ai_budget_state='NORMAL'`). This is a one-time operation —
    subsequent ticks see ai_archetype is set and skip the
    assignment. The function prints a one-line summary:
       "[rival_ai] Assigned archetypes: RFL=Major League, Pacific
        Rim=Regional Power, ..."

PHASE 2-4 ADDITION (Task RIVAL-AI-P2to4):
  - The dispatch now runs the NEW archetype-aware decision modules
    alongside the existing weekly loop (KEPT as fallback per the
    directive "Keep all EXISTING logic as fallback — don't break
    what works"). The cadence map:
      DAILY:    event resolution (existing) + archetype-aware event
                scheduling for promos whose ai_scheduling_day_of_week
                matches today (NEW). 1-2 promos per daily tick
                (round-robin per arch doc §4.2).
      WEEKLY:   signing evaluation + bidding war resolution (NEW)
                + tapping-up rumor generation (NEW) + the OLD 10%
                signing loop (KEPT for tests + as a fallback).
      MONTHLY:  cutting review (NEW) + budget review (NEW).
      QUARTERLY: staff review (NEW) + archetype re-evaluation (NEW).
  - The NEW paths use the rival_ai package's decision modules:
      services.rival_ai.event_scheduler.schedule_next_event_for_rival
      services.rival_ai.signing_agent.evaluate_signing_intents +
        resolve_bidding_wars + evaluate_contract_expiry_interest
      services.rival_ai.cutting_agent.evaluate_cuts
      services.rival_ai.staff_manager.evaluate_staff_changes
      services.rival_ai.budget_manager.review_budget
      services.rival_ai.archetypes.assign_archetype (quarterly re-eval)
  - The OLD weekly loop uses the existing ai_aggression / ai_
    spending_style logic. It runs AFTER the NEW signing path so
    the bidding-war winners are committed before the OLD path's
    FA SELECT (preventing double-signing of the same fighter).
  - All NEW paths are wrapped in try/except so a failure can't
    crash the rival AI loop. The OLD paths continue to run on
    failure (defensive — the world keeps spinning).
  - The new `services/rival_ai/` package ships with FULL logic
    for all 7 decision modules (event_scheduler, matchmaker,
    signing_agent, cutting_agent, staff_manager, budget_manager,
    imperfection) per the arch doc spec.
"""

import random


# ----------------------------------------------------------------
# Player promotion — the AI never touches this one.
# ----------------------------------------------------------------

PLAYER_PROMOTION_ID = 1


# ----------------------------------------------------------------
# AI tuning constants (per the brief).
# ----------------------------------------------------------------

# Weekly cadence — rival AI runs only on weekly ticks (current_day
# % 7 == 0). Matches morale, agent_offers, and other weekly systems.
WEEKLY_TICK_MODULUS = 7

# Free-agent signing chance per rival promotion per week. 10% per
# the brief — with ~8 rival promotions, that's ~0.8 signings per
# sim week on average. Enough to keep rival rosters fluid without
# dominating the free agent market.
FREE_AGENT_SIGN_CHANCE = 0.10

# Roster cap — a rival promotion booking 1 event per 2-6 weeks
# doesn't need more than 50 fighters. Prevents roster bloat.
MAX_ROSTER_SIZE = 50

# Per-aggression scheduling cadence (weeks between events).
# Low aggression (0-30): 6 weeks (slow, conservative).
# Medium (31-60): 4 weeks (default — same as the player's auto-
# scheduled events).
# High (61-100): 2 weeks (fast, aggressive — pushes prospects).
LOW_AGGRESSION_MAX = 30
HIGH_AGGRESSION_MIN = 61

WEEKS_OUT_LOW = 6
WEEKS_OUT_MEDIUM = 4
WEEKS_OUT_HIGH = 2

# Per-spending-style potential thresholds for free agent signing.
# 'conservative': only signs solid-or-better free agents.
# 'balanced': signs any free agent with at least some potential.
# 'aggressive': signs anyone (including low-potential gambles).
POTENTIAL_FLOOR_CONSERVATIVE = 50
POTENTIAL_FLOOR_BALANCED = 30
POTENTIAL_FLOOR_AGGRESSIVE = 0  # no floor — gambles welcome


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _is_weekly_tick(conn):
    """Return True if the current sim day is a weekly tick boundary.

    Matches morale._is_weekly_tick (current_day % 7 == 0). The weekly
    cadence spreads rival AI actions across the sim calendar — daily
    would flood the news feed with rival results.
    """
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not row or row[0] is None:
        return False
    return (row[0] % WEEKLY_TICK_MODULUS) == 0


def _weeks_out_for_aggression(ai_aggression):
    """Return the weeks_out scheduling interval for an ai_aggression value.

    Low (0-30): 6 weeks. Medium (31-60): 4 weeks. High (61-100): 2 weeks.
    """
    if ai_aggression is None:
        return WEEKS_OUT_MEDIUM
    if ai_aggression <= LOW_AGGRESSION_MAX:
        return WEEKS_OUT_LOW
    if ai_aggression >= HIGH_AGGRESSION_MIN:
        return WEEKS_OUT_HIGH
    return WEEKS_OUT_MEDIUM


def _potential_floor_for_style(ai_spending_style):
    """Return the minimum potential a free agent must have to be signed.

    'conservative': 50. 'balanced': 30. 'aggressive': 0 (no floor).
    Unknown / NULL defaults to 'balanced' (30).
    """
    if ai_spending_style == 'conservative':
        return POTENTIAL_FLOOR_CONSERVATIVE
    if ai_spending_style == 'aggressive':
        return POTENTIAL_FLOOR_AGGRESSIVE
    # 'balanced' or unknown — defensive default.
    return POTENTIAL_FLOOR_BALANCED


def _has_scheduled_event(conn, promotion_id):
    """Return True if the promotion has at least one event in 'scheduled'
    status (i.e. an upcoming event with unresolved fights).

    A promotion with no scheduled events needs schedule_next_event to
    be called. A promotion with a scheduled event already has its
    next card on the books — the AI should resolve its fights, not
    book another card on top.
    """
    row = conn.execute(
        "SELECT 1 FROM events WHERE promotion_id=? AND status='scheduled' "
        "LIMIT 1",
        (promotion_id,),
    ).fetchone()
    return row is not None


def _has_unresolved_fight(conn, promotion_id):
    """Return True if the promotion has at least one unresolved fight
    (winner_fighter_id IS NULL and result_type IS NULL).

    Used as a fast guard before the single-night-resolution loop —
    avoids the per-tick SELECT-then-resolve call when the promotion
    has no work to do.
    """
    row = conn.execute(
        "SELECT 1 FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE e.promotion_id=? AND f.winner_fighter_id IS NULL "
        "AND f.result_type IS NULL LIMIT 1",
        (promotion_id,),
    ).fetchone()
    return row is not None


def _events_due_for_resolution(conn, promotion_id, current_date):
    """Return the list of (event_id, event_date) tuples for events owned
    by `promotion_id` whose event_date <= current_date AND that still
    have at least one unresolved fight.

    An event whose event_date has arrived (or already passed) is "due" —
    the show is tonight (or was tonight) and the unresolved fights on
    the card should ALL be resolved in a single tick. We require at
    least one unresolved fight in the event so we don't keep looping
    over already-completed events (a no-op).

    Returns events in event_id ASC order so older cards resolve first
    (defensive — shouldn't matter since each card resolves fully in
    one tick, but keeps the audit trail tidy).
    """
    if not current_date:
        return []
    rows = conn.execute(
        "SELECT e.event_id, e.event_date FROM events e "
        "WHERE e.promotion_id=? AND e.event_date <= ? "
        "AND e.status != 'completed' "
        "AND EXISTS ("
        "  SELECT 1 FROM fights f "
        "  WHERE f.event_id=e.event_id "
        "  AND f.winner_fighter_id IS NULL "
        "  AND f.result_type IS NULL"
        ") "
        "ORDER BY e.event_id ASC",
        (promotion_id, current_date),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _resolve_event_card(conn, promotion_id, resolve_next_fight_fn):
    """Resolve ALL unresolved fights on the promotion's NEXT due event
    in a single tick (the night of the show).

    Loops `resolve_next_fight(promotion_id=X)` until it returns None
    (no more unresolved fights on any of the promotion's events whose
    event_date <= current_date). Each call commits inside
    resolve_next_fight's caller (run_tick commits after publish()).

    PERF-FIXES-3: passes `skip_beat_detail=True` to resolve_next_fight
    so AI vs AI fights skip the per-beat engine + commentary writes
    (saves ~80-250 INSERTs per AI fight). The player's own fights are
    NOT affected — they're resolved via app_web.resolve_next_fight
    with the default `skip_beat_detail=False`. The simplified
    resolver produces the same result_type + winner distribution;
    show_rating + morale fall back to fights.performance_rating
    when fight_beats is empty.

    Defensive — any single fight resolution failure (e.g. a corrupt
    fight row missing participants) is logged and breaks the loop,
    so one bad fight doesn't block resolution of the rest of the card
    on the next tick. The failed fight is skipped (the next tick will
    re-attempt it; if it's truly stuck, the SHOW will hang on that
    fight — flagging as a known edge case for future debugging).
    """
    while True:
        try:
            fid = resolve_next_fight_fn(
                conn, promotion_id=promotion_id,
                skip_beat_detail=True,
            )
        except Exception as e:
            import sys
            print(f"WARNING: rival_ai resolve_next_fight failed "
                  f"for promotion_id={promotion_id}: "
                  f"{type(e).__name__}: {e}",
                  file=sys.stderr)
            break
        if fid is None:
            break  # no more unresolved fights on this promotion


def _roster_size(conn, promotion_id):
    """Return the number of active fighters on the promotion's roster."""
    row = conn.execute(
        "SELECT COUNT(*) FROM fighters "
        "WHERE current_promotion_id=? AND is_active=1 AND is_retired=0",
        (promotion_id,),
    ).fetchone()
    return row[0] if row else 0


def _current_sim_date(conn):
    """Return the current sim date string from simulation_clock."""
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else None


def _current_sim_day(conn):
    """Return the current sim day (int >= 1) from simulation_clock.

    Used by the monthly/quarterly tick checks (current_day % 28 == 0,
    current_day % 84 == 0) + the round-robin scheduling day-of-week
    computation (((current_day - 1) % 7) + 1).
    """
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else 0


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber — rival promotion AI
# ----------------------------------------------------------------

def _process_rival_promotions(conn, event):
    """Subscriber for TICK_ADVANCED — rival promotion booking loop.

    On EVERY tick (daily):
      For each rival promotion (promotion_id != PLAYER_PROMOTION_ID):
        - If the promotion has any scheduled event whose event_date
          <= current_date AND that event has unresolved fights,
          resolve ALL unresolved fights on that event in a single
          tick (the show goes on, on its scheduled date).

    On WEEKLY ticks (current_day % 7 == 0):
      For each rival promotion (promotion_id != PLAYER_PROMOTION_ID):
        1. If no scheduled event exists, call schedule_next_event
           with the promotion's ai_aggression-derived weeks_out.
        2. 10% chance per week of signing a free agent (if roster
           < 50), filtered by ai_spending_style potential floor.

    PHASE 1 ADDITION (Task RIVAL-AI-P1): on the first tick (when any
    rival promo's ai_archetype column is NULL), call
    `services.rival_ai.archetypes.assign_all_archetypes(conn)` to
    populate the 3 new v3.14.0 columns (ai_archetype +
    ai_scheduling_day_of_week + ai_budget_state='NORMAL'). This is a
    one-time operation — subsequent ticks see ai_archetype is set and
    skip the assignment. Phase 2 will replace this dispatch with
    archetype-aware scheduling + signing; Phase 1 keeps the existing
    ai_aggression / ai_spending_style logic UNCHANGED so the world
    keeps spinning while the foundation is laid.

    The function does NOT commit — the caller (run_tick) commits
    after publish() returns, matching the established pattern.

    Lazy-imports app inside the function (not at module load) to
    avoid a circular dependency — app.py imports register_subscribers
    at App.__init__, so rival_ai cannot import app at module load
    without creating an import cycle.
    """
    current_date = event.get('current_date') or _current_sim_date(conn)

    # ---- PHASE 1: First-tick archetype assignment ------------------
    # If ANY rival promo has ai_archetype IS NULL, this is the first
    # AI tick (or the DB was just migrated to v3.14.0). Populate the
    # 3 new columns via services.rival_ai.archetypes.assign_all_archetypes.
    # The function prints a one-line summary like:
    #   "[rival_ai] Assigned archetypes: RFL=Major League, Pacific
    #    Rim=Regional Power, ..."
    # Cheap SELECT (1 row, indexed) — sub-millisecond on subsequent
    # ticks. Phase 2 will move this into the dispatch loop + add
    # archetype-aware scheduling.
    try:
        from services.rival_ai.archetypes import assign_all_archetypes
        unassigned = conn.execute(
            "SELECT 1 FROM promotions "
            "WHERE promotion_id != ? AND ai_archetype IS NULL "
            "LIMIT 1",
            (PLAYER_PROMOTION_ID,),
        ).fetchone()
        if unassigned is not None:
            assign_all_archetypes(conn)
    except ImportError:
        # services.rival_ai package not available — legacy behavior
        # (Phase 1 not yet deployed). The existing ai_aggression /
        # ai_spending_style logic below runs unmodified.
        pass
    except Exception as e:
        # Defensive — archetype assignment failure MUST NOT crash the
        # rival AI. The existing scheduling + signing loop runs
        # unmodified; Phase 2 will retry the assignment on the next
        # tick when the bug is fixed.
        import sys
        print(f"WARNING: rival_ai archetype assignment failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)

    # Lazy-import app functions (avoids circular dependency).
    from app import schedule_next_event, resolve_next_fight, sign_free_agent

    # ---- PHASE 2-4: Clear roster cache at tick start ----------------
    # Per arch doc §4.4 — the per-(promotion_id, date) roster cache
    # is invalidated at the start of each new tick. FIGHT_RESOLVED /
    # FIGHTER_SIGNED / INJURY_CREATED / INJURY_RECOVERED subscribers
    # invalidate per-promo entries mid-tick; this is the catch-all.
    try:
        from services.rival_ai._shared import roster_cache_invalidate
        roster_cache_invalidate()
    except ImportError:
        pass
    # Clear the FA pool cache too (per arch doc §4.3 — batched DB
    # operations). The base FA pool is fetched once per tick + cached;
    # clearing at tick start ensures FIGHTER_SIGNED events from the
    # previous tick are reflected.
    try:
        from services.rival_ai.signing_agent import _clear_fa_pool_cache
        _clear_fa_pool_cache()
    except ImportError:
        pass

    # Fetch all rival promotions + their AI tuning columns ONCE per
    # tick (the loop touches all of them in two phases: daily resolve
    # + weekly schedule/sign).
    rival_rows = conn.execute(
        "SELECT promotion_id, ai_aggression, ai_spending_style, "
        "ai_scheduling_day_of_week "
        "FROM promotions WHERE promotion_id != ?",
        (PLAYER_PROMOTION_ID,),
    ).fetchall()

    # ---- DAILY PHASE: single-night event resolution -----------------
    # On every tick, check each rival promotion for events whose
    # event_date <= current_date AND that have unresolved fights.
    # When found, resolve ALL the fights on that event in one go (the
    # show is tonight — an MMA event is a single-night card, not a
    # week-by-week trickle). Cheap SELECT per promo per tick.
    for (promo_id, _aggression, _spending_style, _sched_day) in rival_rows:
        if promo_id is None:
            continue
        due_events = _events_due_for_resolution(
            conn, promo_id, current_date,
        )
        if not due_events:
            continue
        # Resolve each due event's full card. resolve_next_fight picks
        # the lowest-fight_id unresolved fight across the promotion's
        # events (with the promotion_id filter), so looping until it
        # returns None drains ALL unresolved fights on ALL due events
        # — typically one event per promo per tick, but defensive in
        # case two events somehow stacked up.
        _resolve_event_card(conn, promo_id, resolve_next_fight)

    # ---- DAILY PHASE: archetype-aware event scheduling (NEW P2) -----
    # Per arch doc §4.2 — only promos whose ai_scheduling_day_of_week
    # matches today's day-of-week run their full decision engine.
    # This spreads work across the week (round-robin: 1-2 promos per
    # daily tick). Cheap SELECT per promo per tick.
    rng = random.Random()
    current_day = _current_sim_day(conn)
    today_dow = ((current_day - 1) % 7) + 1 if current_day > 0 else 1
    # Track which promos the NEW daily path tried today — the OLD
    # weekly loop skips these (the NEW path either succeeded, in which
    # case _has_scheduled_event handles it, or failed, in which case
    # the OLD loop's schedule_next_event would also fail with the
    # same "no eligible fighters" warning — wasted work).
    _daily_path_tried = set()
    for (promo_id, _aggr, _style, sched_day) in rival_rows:
        if promo_id is None or sched_day is None:
            continue
        if sched_day != today_dow:
            continue
        _daily_path_tried.add(promo_id)
        try:
            from services.rival_ai.event_scheduler import (
                schedule_next_event_for_rival,
            )
            schedule_next_event_for_rival(conn, promo_id, rng=rng)
        except ImportError:
            pass  # services.rival_ai.event_scheduler not available
        except Exception as e:
            import sys
            print(f"WARNING: rival_ai schedule_next_event_for_rival "
                  f"failed for promotion_id={promo_id}: "
                  f"{type(e).__name__}: {e}",
                  file=sys.stderr)

    # ---- WEEKLY PHASE: scheduling + free agent signing --------------
    # Only on weekly ticks (current_day % 7 == 0). Scheduling cadence
    # doesn't need daily granularity (a few days' difference is
    # imperceptible). Free agent signings weekly is already enough
    # fluidity (10% per promo per week × ~8 rival promos ≈ 0.8
    # signings per sim week).
    if not _is_weekly_tick(conn):
        return

    # ---- WEEKLY PHASE: signing evaluation + bidding wars (NEW P2) ---
    # Per arch doc §3.3 + §5.3 — collect all rival promos' intended
    # signings, resolve bidding wars for contested FAs, then sign
    # the winners via the existing sign_free_agent. The OLD 10%
    # signing loop runs AFTER (KEPT for tests + as a fallback).
    #
    # PHASE M3.1 (docs/MASTER_PLAN_MATCHMAKING.md §2.2): removed the
    # player-promo exclusion from the signing-intent path. The
    # rival_rows SELECT still excludes promo_id=1 (the player's promo)
    # so the daily/weekly scheduling + resolve loops still skip the
    # player (those are player-driven via the UI). BUT for the signing
    # intents path we now EXPLICITLY add the player's promo_id to the
    # list — this makes the player a valid bidding participant. The
    # player doesn't auto-generate intents (their promo has no
    # archetype, so _evaluate_one_promo returns None), but their
    # counter-offers (submitted via the new counter_offer API in M3.2)
    # get added to the bidding-war resolution flow as a competing
    # intent for the same fighter.
    try:
        from services.rival_ai.signing_agent import (
            evaluate_signing_intents, resolve_bidding_wars,
            evaluate_contract_expiry_interest,
        )
        promo_ids = [pid for (pid, _, _, _) in rival_rows if pid is not None]
        # M3.1: include the player's promo as a valid bidding
        # participant. evaluate_signing_intents will not generate an
        # auto-intent for the player (no archetype), but the player's
        # counter-offers (added later by counter_offer API) compete in
        # the same resolution flow.
        if PLAYER_PROMOTION_ID not in promo_ids:
            promo_ids.append(PLAYER_PROMOTION_ID)
        if promo_ids:
            intents = evaluate_signing_intents(
                conn, promo_ids, current_date, rng,
            )
            resolve_bidding_wars(conn, intents, current_date, rng)
            evaluate_contract_expiry_interest(conn, current_date, rng)
    except ImportError:
        pass  # services.rival_ai.signing_agent not available
    except Exception as e:
        import sys
        print(f"WARNING: rival_ai signing_agent failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)

    # ---- WEEKLY PHASE: OLD scheduling + 10% signing loop (FALLBACK) -
    for (promo_id, ai_aggression, ai_spending_style, _sched_day) in rival_rows:
        if promo_id is None:
            continue

        # 1. Schedule an event if the promotion has none (OLD path,
        #    kept as fallback for promos whose daily-path didn't fire
        #    or failed). Uses the player's schedule_next_event which
        #    produces optimal cards — the NEW daily path produces
        #    biased cards via the rival matchmaker.
        #    Skip promos the NEW daily path already tried today
        #    (avoids redundant schedule_next_event calls that would
        #    fail with the same "no eligible fighters" warning).
        if (promo_id not in _daily_path_tried
                and not _has_scheduled_event(conn, promo_id)):
            weeks_out = _weeks_out_for_aggression(ai_aggression)
            try:
                schedule_next_event(
                    conn, promotion_id=promo_id,
                    from_event_date=None, weeks_out=weeks_out,
                )
            except Exception as e:
                # Defensive — a scheduling failure (no eligible
                # fighters, no venue) shouldn't crash the AI loop.
                # The promotion just skips this week and tries again
                # next week.
                import sys
                print(f"WARNING: rival_ai schedule_next_event failed "
                      f"for promotion_id={promo_id}: {type(e).__name__}: {e}",
                      file=sys.stderr)

        # 2. 10% chance per week of signing a free agent (if roster
        # < 50 — defensive cap against roster bloat). KEPT for tests
        # + as a fallback when the NEW signing_agent finds no
        # roster gaps (the OLD path picks a random FA matching the
        # spending_style potential floor).
        roster_size = _roster_size(conn, promo_id)
        if roster_size < MAX_ROSTER_SIZE and rng.random() < FREE_AGENT_SIGN_CHANCE:
            _maybe_sign_free_agent(
                conn, promo_id, ai_spending_style, rng,
                sign_free_agent,
            )

    # ---- MONTHLY PHASE: cutting + budget review (NEW P3) ------------
    # Per arch doc §3.4 + §3.6 — runs on current_day % 28 == 0. For
    # each rival promo: evaluate cuts (cut_risk scoring + protections
    # + archetype aggressiveness) + review budget (3-state machine +
    # crisis handling). Cheap per-promo (~12ms cut + ~4ms budget).
    if current_day > 0 and current_day % 28 == 0:
        _run_monthly_phase(conn, rival_rows, current_date, rng)

    # ---- QUARTERLY PHASE: staff + archetype re-eval (NEW P3+P4) -----
    # Per arch doc §3.5 + §3.7 — runs on current_day % 84 == 0. For
    # each rival promo: evaluate staff (hire/fire scouts/GMs/etc) +
    # re-evaluate the archetype (a Grassroots that grew may graduate
    # to Regional Power — produces a news item).
    if current_day > 0 and current_day % 84 == 0:
        _run_quarterly_phase(conn, rival_rows, current_date, rng)


def _run_monthly_phase(conn, rival_rows, current_date, rng):
    """Run the monthly cutting + budget review for all rival promos.

    Per arch doc §3.4 + §3.6. Called by _process_rival_promotions on
    current_day % 28 == 0. Wrapped in try/except so a single promo's
    failure doesn't block the rest.
    """
    for (promo_id, _, _, _) in rival_rows:
        if promo_id is None:
            continue
        # Cutting review.
        try:
            from services.rival_ai.cutting_agent import evaluate_cuts
            evaluate_cuts(conn, promo_id, current_date=current_date, rng=rng)
        except ImportError:
            pass
        except Exception as e:
            import sys
            print(f"WARNING: rival_ai cutting_agent failed for "
                  f"promotion_id={promo_id}: {type(e).__name__}: {e}",
                  file=sys.stderr)
        # Budget review.
        try:
            from services.rival_ai.budget_manager import review_budget
            review_budget(conn, promo_id, current_date)
        except ImportError:
            pass
        except Exception as e:
            import sys
            print(f"WARNING: rival_ai budget_manager failed for "
                  f"promotion_id={promo_id}: {type(e).__name__}: {e}",
                  file=sys.stderr)


def _run_quarterly_phase(conn, rival_rows, current_date, rng):
    """Run the quarterly staff review + archetype re-eval for all rival
    promos.

    Per arch doc §3.5 + §3.7. Called by _process_rival_promotions on
    current_day % 84 == 0. Wrapped in try/except so a single promo's
    failure doesn't block the rest.
    """
    for (promo_id, _, _, _) in rival_rows:
        if promo_id is None:
            continue
        # Staff review (hire/fire).
        try:
            from services.rival_ai.staff_manager import evaluate_staff_changes
            evaluate_staff_changes(conn, promo_id, current_date=current_date, rng=rng)
        except ImportError:
            pass
        except Exception as e:
            import sys
            print(f"WARNING: rival_ai staff_manager failed for "
                  f"promotion_id={promo_id}: {type(e).__name__}: {e}",
                  file=sys.stderr)
        # Archetype re-evaluation.
        try:
            from services.rival_ai.archetypes import assign_archetype, ARCHETYPE_DISPLAY_NAMES
            old_row = conn.execute(
                "SELECT ai_archetype FROM promotions WHERE promotion_id=?",
                (promo_id,),
            ).fetchone()
            old_archetype = old_row[0] if old_row else None
            new_archetype = assign_archetype(promo_id, conn)
            if (new_archetype != old_archetype
                    and old_archetype is not None
                    and new_archetype is not None):
                _write_reclassification_news(
                    conn, promo_id, old_archetype, new_archetype, current_date,
                )
        except ImportError:
            pass
        except Exception as e:
            import sys
            print(f"WARNING: rival_ai archetype re-eval failed for "
                  f"promotion_id={promo_id}: {type(e).__name__}: {e}",
                  file=sys.stderr)


def _write_reclassification_news(conn, promotion_id, old_archetype,
                                  new_archetype, current_date):
    """Write a 'promo reclassified' news item when a promo's archetype
    changes (quarterly re-eval per arch doc §3.7).

    Upgrade: "{Promo} has been elevated to {New} status after a strong quarter."
    Downgrade: "{Promo} has been reclassified as {New} after a difficult quarter."
    """
    from services.rival_ai._shared import write_news_item
    from services.rival_ai.archetypes import ARCHETYPE_DISPLAY_NAMES
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"
    old_display = ARCHETYPE_DISPLAY_NAMES.get(old_archetype, old_archetype)
    new_display = ARCHETYPE_DISPLAY_NAMES.get(new_archetype, new_archetype)
    # Determine upgrade vs downgrade via the order in BUDGET_STATES-
    # like ordering (grassroots < rising_star < regional_power <
    # major_league).
    order = ['grassroots', 'rising_star', 'regional_power', 'major_league']
    old_idx = order.index(old_archetype) if old_archetype in order else 0
    new_idx = order.index(new_archetype) if new_archetype in order else 0
    if new_idx > old_idx:
        headline = f"{promo_name} elevated to {new_display} status"
        body = (f"{promo_name} has been elevated to {new_display} status "
                f"after a strong quarter, reflecting the promotion's growth "
                f"from its previous {old_display} standing.")
        sentiment = 'positive'
    else:
        headline = f"{promo_name} reclassified as {new_display}"
        body = (f"{promo_name} has been reclassified as {new_display} after "
                f"a difficult quarter, down from its previous {old_display} "
                f"standing.")
        sentiment = 'neutral'
    write_news_item(
        conn,
        headline=headline,
        body=body,
        topic='reclassified',
        sentiment=sentiment,
        promotion_id=promotion_id,
        published_at=current_date,
    )


def _maybe_sign_free_agent(conn, promotion_id, ai_spending_style, rng,
                            sign_free_agent_fn):
    """Pick + sign a free agent for a rival promotion.

    Filter by ai_spending_style potential floor:
      'conservative': potential >= 50
      'balanced':     potential >= 30
      'aggressive':   no floor (potential >= 0)

    Picks one matching free agent at random and calls sign_free_agent
    to create the contract + news item. The FIGHTER_SIGNED event is
    published by sign_free_agent (not here) — the news engine + morale
    system subscribers fire automatically.

    Args:
        conn: sqlite3 connection (caller commits).
        promotion_id: the rival promotion signing the free agent.
        ai_spending_style: 'conservative' / 'balanced' / 'aggressive'.
        rng: random.Random instance.
        sign_free_agent_fn: app.sign_free_agent (passed in to avoid
            re-importing app inside this helper).
    """
    potential_floor = _potential_floor_for_style(ai_spending_style)
    current_date = _current_sim_date(conn)
    if not current_date:
        return  # no sim date — can't start a contract

    # Pick a free agent matching the spending-style potential floor.
    # A free agent is a fighter with current_promotion_id IS NULL,
    # is_active=1, is_retired=0.
    rows = conn.execute(
        "SELECT f.fighter_id FROM fighters f "
        "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "WHERE f.current_promotion_id IS NULL "
        "AND f.is_active=1 AND f.is_retired=0 "
        "AND fc.potential >= ?",
        (potential_floor,),
    ).fetchall()
    if not rows:
        return  # no eligible free agents this week

    fighter_id = rng.choice(rows)[0]
    try:
        sign_free_agent_fn(
            conn, fighter_id=fighter_id,
            promotion_id=promotion_id,
            start_date=current_date,
        )
    except Exception as e:
        # Defensive — sign_free_agent refuses retired / already-signed
        # fighters. If the picked fighter became ineligible between
        # the SELECT and the call (race condition shouldn't happen in
        # a single-threaded sim, but be defensive), skip silently.
        import sys
        print(f"WARNING: rival_ai sign_free_agent failed for "
              f"fighter_id={fighter_id}, promotion_id={promotion_id}: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)


# ----------------------------------------------------------------
# Registration
# ----------------------------------------------------------------

def register_subscribers():
    """Register the rival AI subscriber on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior registrations.

    Subscribes to:
      TICK_ADVANCED → _process_rival_promotions (every tick: daily
                      event resolution; weekly: scheduling + signing)
      TICK_ADVANCED → _decay_rival_ai_memory (weekly: salience decay
                      for rival_ai_memory rows; same pattern as
                      rivalries._decay_rivalry_heat)

    W21/W22 (rival AI memory) — additional subscribers that WRITE
    memories when something happens to a rival promo:
      EVENT_COMPLETED    → _on_event_completed_memory (writes an
                            'event_result' memory for the promo that
                            ran the event, with attendance/profit)
      FIGHTER_SIGNED     → _on_fighter_signed_memory (writes a
                            'signing_won' memory for the signing promo
                            AND 'bidding_war_lost' memories for any
                            other rival promo with a pending alert
                            for that fighter — catches both the
                            player-counter-offer case AND the direct-
                            sign case)
      TITLE_CHANGED      → _on_title_changed_memory (writes a
                            'title_win' memory if the promo gained a
                            champion + a 'title_loss' memory if a
                            champion was dethroned)
      PROMOTION_BANKRUPT → _on_promotion_bankrupt_memory (writes a
                            'rivalry_fuelled' memory for every OTHER
                            rival promo — the bankruptcy is an
                            opportunity for competitors)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.TICK_ADVANCED, _process_rival_promotions,
        name="rival_ai.process_rival_promotions",
    )
    # W21/W22 — rival AI memory subscribers. Each writer is wrapped
    # in its own try/except INSIDE the function body so a memory-
    # write failure can't crash the event-bus subscriber chain (the
    # rival AI loop + the news engine + morale + etc. all run on the
    # same bus — a broken subscriber would break the whole game).
    bus.subscribe(
        Events.EVENT_COMPLETED, _on_event_completed_memory,
        name="rival_ai.memory.event_completed",
    )
    bus.subscribe(
        Events.FIGHTER_SIGNED, _on_fighter_signed_memory,
        name="rival_ai.memory.fighter_signed",
    )
    bus.subscribe(
        Events.TITLE_CHANGED, _on_title_changed_memory,
        name="rival_ai.memory.title_changed",
    )
    bus.subscribe(
        Events.PROMOTION_BANKRUPT, _on_promotion_bankrupt_memory,
        name="rival_ai.memory.promotion_bankrupt",
    )
    # Weekly salience decay — runs on the same weekly tick boundary
    # as rivalries._decay_rivalry_heat. Same -1/week pattern; rows at
    # salience=0 are DELETEd (forgotten).
    bus.subscribe(
        Events.TICK_ADVANCED, _decay_rival_ai_memory,
        name="rival_ai.memory.decay",
    )


# ----------------------------------------------------------------
# W21/W22 — rival AI memory subscribers.
#
# Each subscriber writes one or more memories to rival_ai_memory.
# All subscribers are DEFENSIVE — a memory-write failure is logged
# to stderr + swallowed (the rival AI loop + the rest of the event
# bus subscribers continue running). The memory writes are AFTER
# the main work (the event already resolved, the fighter already
# signed, the title already changed, the promo already bankrupted)
# so a write failure doesn't roll back the primary action.
# ----------------------------------------------------------------

def _current_sim_date(conn):
    """Return the current sim date string, or None on failure."""
    try:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _on_event_completed_memory(conn, event):
    """EVENT_COMPLETED subscriber — write an 'event_result' memory
    for the promo whose event just resolved.

    The event payload (published by fight_engine._update_event_status)
    carries {type, event_id, promotion_id, event_date}. We enrich
    the memory's context_json with the event's wins/losses +
    show_ratings + net profit so the event_scheduler reader can
    detect a recent flop ("don't book another show too soon after a
    flop").

    Player-promo events (promotion_id=1) ARE recorded too — the
    player's promo is a valid "rival" from the AI's perspective
    (future cross-promo booking decisions could read these). If this
    is undesired, the guard `if promo_id == PLAYER_PROMOTION_ID:
    return` would skip player-promo memories; left in for now per
    the spec's "rival promo's event resolved" wording.
    """
    try:
        from services.rival_ai import memory
        event_id = event.get('event_id')
        promo_id = event.get('promotion_id')
        event_date = event.get('event_date') or _current_sim_date(conn)
        if event_id is None or promo_id is None or not event_date:
            return
        # Compute cheap context — wins/losses from fights, ratings
        # from show_ratings, profit from finance_transactions.
        wins_losses = conn.execute(
            "SELECT "
            "SUM(CASE WHEN f.winner_fighter_id IS NOT NULL THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN f.result_type IS NOT NULL AND f.winner_fighter_id IS NULL THEN 1 ELSE 0 END) "
            "FROM fights f WHERE f.event_id=?",
            (event_id,),
        ).fetchone()
        wins = wins_losses[0] if wins_losses and wins_losses[0] else 0
        losses = wins_losses[1] if wins_losses and wins_losses[1] else 0
        # show_ratings — single row per event (UNIQUE constraint).
        rating_row = conn.execute(
            "SELECT fan_rating, overall_rating FROM show_ratings "
            "WHERE event_id=?",
            (event_id,),
        ).fetchone()
        fan_rating = rating_row[0] if rating_row else None
        overall_rating = rating_row[1] if rating_row else None
        # Net profit — sum of all finance_transactions for this event.
        profit_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) "
            "FROM finance_transactions WHERE event_id=?",
            (event_id,),
        ).fetchone()
        profit = float(profit_row[0]) if profit_row else 0.0
        memory.record_event_result(
            conn, promo_id, event_id, event_date,
            wins=wins, losses=losses,
            fan_rating=fan_rating, overall_rating=overall_rating,
            profit=profit,
        )
    except ImportError:
        pass  # services.rival_ai.memory not available — skip silently
    except Exception as e:
        import sys
        print(f"WARNING: rival_ai.memory EVENT_COMPLETED writer failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)


def _on_fighter_signed_memory(conn, event):
    """FIGHTER_SIGNED subscriber — write 'signing_won' memory for the
    signing promo + 'bidding_war_lost' memories for any other rival
    promo with a pending bidding_alerts row for this fighter.

    The event payload (published by contracts.sign_free_agent)
    carries {type, fighter_id, promotion_id, contract_id,
    current_date, event_date}.

    The bidding_war_lost scan catches BOTH:
      - The player-counter-offer case (player wins via app_web.
        counter_offer — the alert is marked 'won_by_player' there,
        but we re-check here defensively in case the alert wasn't
        marked).
      - The direct-sign case (the player OR another rival signed
        via sign_free_agent while the alert was pending).
    Pending alerts that match are marked 'lost_race' so we don't
    double-write the memory on a subsequent FIGHTER_SIGNED for the
    same fighter.
    """
    try:
        from services.rival_ai import memory
        fighter_id = event.get('fighter_id')
        signing_promo_id = event.get('promotion_id')
        sign_date = event.get('current_date') or event.get('event_date') \
            or _current_sim_date(conn)
        if fighter_id is None or signing_promo_id is None or not sign_date:
            return
        # 1. Write 'signing_won' for the signing promo.
        memory.record_signing_won(
            conn, signing_promo_id, fighter_id, sign_date,
        )
        # 2. Scan pending bidding_alerts for OTHER rival promos that
        # were pursuing this fighter. Each one is a bidding_war_lost.
        pending = conn.execute(
            "SELECT alert_id, rival_promo_id FROM bidding_alerts "
            "WHERE fighter_id=? AND status='pending' "
            "AND rival_promo_id != ?",
            (fighter_id, signing_promo_id),
        ).fetchall()
        for (alert_id, rival_promo_id) in pending:
            # Defensive: only write the memory if the rival promo
            # isn't the player (player doesn't need a memory — the
            # AI loop skips them anyway).
            if rival_promo_id == PLAYER_PROMOTION_ID:
                continue
            memory.record_bidding_war_lost(
                conn, rival_promo_id, fighter_id,
                signing_promo_id, sign_date,
            )
            # Mark the alert resolved so we don't double-write on a
            # subsequent FIGHTER_SIGNED for the same fighter (should
            # never happen since the fighter is now signed, but
            # defensive).
            conn.execute(
                "UPDATE bidding_alerts SET status='lost_race', "
                "resolved_date=? WHERE alert_id=?",
                (sign_date, alert_id),
            )
    except ImportError:
        pass
    except Exception as e:
        import sys
        print(f"WARNING: rival_ai.memory FIGHTER_SIGNED writer failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)


def _on_title_changed_memory(conn, event):
    """TITLE_CHANGED subscriber — write 'title_win' and/or 'title_loss'
    memories for the promo whose title just changed hands.

    The event payload (published by fight_engine.resolve_next_fight)
    carries {type, title_id (the titles.title_id), fight_id,
    event_id, promotion_id, weight_class_id}.

    Logic:
      - The promo that owns the title (promotion_id in the payload)
        always gets a 'title_win' memory (their fighter is now the
        champion, even if crowned from vacant — the memory captures
        "we have a champion on this date").
      - If the title was HELD before (not vacant) and the champion
        changed hands, the SAME promo ALSO gets a 'title_loss'
        memory for the FORMER champion. (Titles are per-promo — the
        new champion is on the same promo's roster.)
      - The winner_id / loser_id come from the fight row (looked up
        via fight_id).
    """
    try:
        from services.rival_ai import memory
        title_id = event.get('title_id')
        fight_id = event.get('fight_id')
        promo_id = event.get('promotion_id')
        wc_id = event.get('weight_class_id')
        title_date = _current_sim_date(conn)
        if title_id is None or fight_id is None or promo_id is None:
            return
        if not title_date:
            return
        # Look up the fight to get winner + loser.
        fight_row = conn.execute(
            "SELECT winner_fighter_id, loser_fighter_id "
            "FROM fights WHERE fight_id=?",
            (fight_id,),
        ).fetchone()
        if not fight_row:
            return
        winner_id, loser_id = fight_row
        # 1. 'title_win' for the new champion (the winner of the
        # title fight, or None if crowned from vacant — though the
        # TITLE_CHANGED event only fires on a change, so winner_id
        # is usually set).
        if winner_id is not None:
            memory.record_title_win(
                conn, promo_id, winner_id, title_date,
                weight_class_id=wc_id,
            )
        # 2. 'title_loss' for the FORMER champion (the loser of the
        # title fight — they were dethroned). Only write if there
        # WAS a former champion (i.e., the loser was the champ, not
        # a vacant-title fight).
        if loser_id is not None:
            memory.record_title_loss(
                conn, promo_id, loser_id, title_date,
                weight_class_id=wc_id,
            )
    except ImportError:
        pass
    except Exception as e:
        import sys
        print(f"WARNING: rival_ai.memory TITLE_CHANGED writer failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)


def _on_promotion_bankrupt_memory(conn, event):
    """PROMOTION_BANKRUPT subscriber — write a 'rivalry_fuelled'
    memory for every OTHER rival promo (the bankruptcy is an
    opportunity for competitors).

    The event payload (published by reputation._fire_bankruptcy_failure)
    carries {type, promotion_id, promo_name, released_fighter_ids,
    staff_contracts_voided, is_rebuilding, cash_reset}.

    The bankruptcy removes a competitor from the market + floods the
    FA pool with released fighters — both are opportunities for the
    surviving promos. The memory is a low-stakes signal (salience 50)
    that "a rival just went down" — future readers could use it to
    raise signing aggression or lower scheduling caution.

    Writes one row per surviving rival promo (promotion_id != the
    bankrupt one AND != the player's promo — the player doesn't need
    a memory, they drive their own decisions).
    """
    try:
        from services.rival_ai import memory
        bankrupt_promo_id = event.get('promotion_id')
        bankrupt_date = _current_sim_date(conn)
        if bankrupt_promo_id is None or not bankrupt_date:
            return
        # Fetch all OTHER rival promos (exclude the bankrupt one +
        # the player's promo).
        rows = conn.execute(
            "SELECT promotion_id FROM promotions "
            "WHERE promotion_id != ? AND promotion_id != ?",
            (bankrupt_promo_id, PLAYER_PROMOTION_ID),
        ).fetchall()
        for (survivor_promo_id,) in rows:
            memory.record_rivalry_fuelled(
                conn, survivor_promo_id, bankrupt_promo_id,
                bankrupt_date, reason='bankruptcy',
            )
    except ImportError:
        pass
    except Exception as e:
        import sys
        print(f"WARNING: rival_ai.memory PROMOTION_BANKRUPT writer failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)


def _decay_rival_ai_memory(conn, event):
    """Weekly TICK_ADVANCED subscriber — decay all rival_ai_memory
    salience by -1; DELETE rows whose salience hits 0 (forgotten).

    Mirrors rivalries._decay_rivalry_heat — same weekly gate
    (current_day % 7 == 0), same -1/step decay. The DELETE-on-0
    semantics differ from rivalries (which keeps dormant rows for
    history) — memories are explicitly short-term state, not history.
    """
    if not _is_weekly_tick(conn):
        return
    try:
        from services.rival_ai import memory
        memory.decay_all_memories(conn)
    except ImportError:
        pass
    except Exception as e:
        import sys
        print(f"WARNING: rival_ai.memory decay failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)
