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
effects added to run_tick). Subscribes to TICK_ADVANCED. Detects a
WEEKLY tick (current_day % 7 == 0 — matches the cadence used by
morale, agent_offers, and other weekly systems). On weekly ticks:

  For each rival promotion (promotion_id != 1):
    1. If the promotion has no scheduled event, call
       schedule_next_event to book the next card.
    2. If the promotion has unresolved fights, call
       resolve_next_fight(promotion_id=X) ONCE per weekly tick.
       This spreads rival results over days/weeks (narrative pacing
       — rival results trickle in, not dumped all at once).
    3. 10% chance per week of signing a free agent (if roster < 50).

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

DESIGN DECISIONS:
  - Weekly cadence (not daily) — daily would resolve too many rival
    fights per week, flooding the news feed. Weekly = 1 fight per
    rival promotion per week = a manageable trickle of rival news.
  - ONE fight per weekly tick per rival promotion (not all of them)
    — spreads rival results over days/weeks for narrative pacing.
    A 5-fight RFL card resolves over 5 weekly ticks, not all at once.
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

    The AI resolves ONE such fight per weekly tick — spreads results
    over days/weeks for narrative pacing.
    """
    row = conn.execute(
        "SELECT 1 FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE e.promotion_id=? AND f.winner_fighter_id IS NULL "
        "AND f.result_type IS NULL LIMIT 1",
        (promotion_id,),
    ).fetchone()
    return row is not None


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


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber — rival promotion AI
# ----------------------------------------------------------------

def _process_rival_promotions(conn, event):
    """Subscriber for TICK_ADVANCED — rival promotion booking loop.

    Fires only on weekly ticks (current_day % 7 == 0). For each rival
    promotion (promotion_id != PLAYER_PROMOTION_ID):
      1. If no scheduled event exists, call schedule_next_event with
         the promotion's ai_aggression-derived weeks_out.
      2. If unresolved fights exist, call resolve_next_fight with
         promotion_id=X — ONCE per weekly tick (spreads results for
         narrative pacing).
      3. 10% chance per week of signing a free agent (if roster < 50),
         filtered by ai_spending_style potential floor.

    The function does NOT commit — the caller (run_tick) commits
    after publish() returns, matching the established pattern.

    Lazy-imports app inside the function (not at module load) to
    avoid a circular dependency — app.py imports register_subscribers
    at App.__init__, so rival_ai cannot import app at module load
    without creating an import cycle.
    """
    if not _is_weekly_tick(conn):
        return

    # Lazy-import app functions (avoids circular dependency).
    from app import schedule_next_event, resolve_next_fight, sign_free_agent

    # Fetch all rival promotions + their AI tuning columns.
    rival_rows = conn.execute(
        "SELECT promotion_id, ai_aggression, ai_spending_style "
        "FROM promotions WHERE promotion_id != ?",
        (PLAYER_PROMOTION_ID,),
    ).fetchall()

    rng = random.Random()

    for (promo_id, ai_aggression, ai_spending_style) in rival_rows:
        if promo_id is None:
            continue

        # 1. Schedule an event if the promotion has none.
        if not _has_scheduled_event(conn, promo_id):
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

        # 2. Resolve ONE unresolved fight (if any). Spreads results
        # over days/weeks for narrative pacing — a 5-fight card
        # resolves over 5 weekly ticks, not all at once.
        if _has_unresolved_fight(conn, promo_id):
            try:
                resolve_next_fight(conn, promotion_id=promo_id)
            except Exception as e:
                import sys
                print(f"WARNING: rival_ai resolve_next_fight failed "
                      f"for promotion_id={promo_id}: {type(e).__name__}: {e}",
                      file=sys.stderr)

        # 3. 10% chance per week of signing a free agent (if roster
        # < 50 — defensive cap against roster bloat).
        roster_size = _roster_size(conn, promo_id)
        if roster_size < MAX_ROSTER_SIZE and rng.random() < FREE_AGENT_SIGN_CHANCE:
            _maybe_sign_free_agent(
                conn, promo_id, ai_spending_style, rng,
                sign_free_agent,
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
      TICK_ADVANCED → _process_rival_promotions (weekly tick —
                      current_day % 7 == 0)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.TICK_ADVANCED, _process_rival_promotions,
        name="rival_ai.process_rival_promotions",
    )
