"""CAGE EMPIRE Rival AI — Event Scheduler (Task ID RIVAL-AI-P2to4, Phase 2).

Per docs/RIVAL_AI_ARCHITECTURE.md §3.1 — archetype-driven event
scheduling for rival promotions. Picks the event_date based on the
archetype's `event_window_days`, calls the rival matchmaker (§3.2)
to build the card, and inserts via the shared `_insert_event_and_card`
helper (extracted from `services/matchmaking.schedule_next_event`).

The scheduler REUSES the existing matchmaking helpers:
  - `_get_available_fighters_for_card` (roster query)
  - `_create_training_camp` (training camp creation per booked fighter)
  - `fighter_name` (event name builder)
It DOES NOT call the player-facing `schedule_next_event` (which
produces optimal cards). Instead it calls the rival matchmaker
which wraps the existing builders + adds bias.

CONVENTIONS compliance:
  §5  — No new tables. Reads/writes existing `events` + `fights` +
        `fight_participants` + `event_cards` + `training_camps`
        + `fighters` tables only.
  §13 — Design Law: rival promos schedule their own shows on their
        own cadence (Conflict + Puppet Master + Empire Builder).
  §14 — Voice Layer: news items use direct prose (no raw numbers).
  §15 — Event Bus: N/A — no subscribers. Called by src/rival_ai.py's
        TICK_ADVANCED dispatch on the promo's scheduling day.
"""

import random as _random
from datetime import datetime, timedelta


# Per arch doc §3.1 step 2 — venue cost by promotion size_tier.
# Major promos book big arenas; small promos book cheap halls.
VENUE_COST_BY_TIER = {
    'major': 200_000,
    'mid':    80_000,
    'small':  25_000,
}

# Per arch doc §3.1 step 2 — staff payout estimate per slot.
# Used to estimate event cost for the budget gate. The actual staff
# salaries come from the staff_contracts table (post-v3.14.0 backfill).
STAFF_PAYOUT_PER_SLOT = 5_000  # $5K per staff member per event

# Safety margin for the budget gate (per arch doc §3.1 step 2: "if
# cash < estimated cost × 1.2, skip this week").
BUDGET_GATE_SAFETY_MARGIN = 1.2

# Rival collision avoidance window (per arch doc §3.1 step 3: ±2 days).
RIVAL_COLLISION_WINDOW_DAYS = 2

# Max re-sample attempts for rival collision avoidance.
MAX_RESAMPLE_ATTEMPTS = 3


def schedule_next_event_for_rival(conn, promotion_id, archetype=None, rng=None):
    """Schedule the next event for a rival promotion.

    Per arch doc §3.1:
      1. Guard: skip if the promo already has a scheduled event OR
         the last completed event was < archetype.event_cadence_days
         ago.
      2. Budget gate: estimate event cost. If cash < cost × 1.2, skip
         this week (SURVIVAL mode — see budget_manager).
      3. Pick event_date: sample uniformly from
         [today + event_window_days[0], today + event_window_days[1]].
         Apply rival collision avoidance (re-sample if another promo
         has a scheduled event within ±2 days; max 3 attempts).
      4. Build the card via `services.rival_ai.matchmaker.build_card`.
      5. Insert via `_insert_event_and_card`.
      6. Write a "scheduling announcement" news item with the main event.

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the rival promotion scheduling the event.
        archetype: optional pre-fetched archetype dict (from
            `archetypes.get_archetype` or `budget_manager.get_modified_
            archetype`). If None, the function will look it up via
            `budget_manager.get_modified_archetype` (which applies
            state + recency modifiers).
        rng: optional random.Random instance.

    Returns:
        The new event_id (int), or None if no event was scheduled
        (guard clause tripped / budget gate failed / no eligible
        fighters).
    """
    rng = rng or _random.Random()

    # 1. Resolve the (state-modified, recency-modified) archetype.
    if archetype is None:
        from services.rival_ai.budget_manager import get_modified_archetype
        _, archetype, budget_state = get_modified_archetype(conn, promotion_id)
        if archetype is None:
            return None
        # CRISIS: don't schedule events (handle_crisis cancelled them).
        if budget_state == 'CRISIS':
            return None
    else:
        from services.rival_ai.budget_manager import get_budget_state
        budget_state = get_budget_state(conn, promotion_id)
        if budget_state == 'CRISIS':
            return None

    # 2. Guard: skip if promo already has a scheduled event.
    if _has_scheduled_event(conn, promotion_id):
        return None

    # 3. Guard: skip if last completed event was < cadence_days ago.
    if not _cadence_elapsed(conn, promotion_id, archetype['event_cadence_days']):
        return None

    # W21/W22 — rival AI memory read: if the promo's most recent
    # event_result memory was a FLOP (overall_rating < 40 OR profit
    # < 0), suppress scheduling for this cycle (don't book another
    # show too soon after a flop). The memory decays weekly, so this
    # gate naturally lifts after ~1-2 cycles of decay. Defensive —
    # any DB error in the reader is swallowed + scheduling proceeds
    # normally (the world keeps spinning even if the memory read
    # fails).
    try:
        from services.rival_ai.memory import recent_event_result_memory
        recent = recent_event_result_memory(conn, promotion_id, limit=1)
        if recent:
            ctx = recent[0].get('context', {}) or {}
            overall = ctx.get('overall_rating')
            profit = ctx.get('profit')
            flop = False
            if overall is not None and overall < 40:
                flop = True
            if profit is not None and profit < 0:
                flop = True
            if flop:
                return None  # suppress — don't book after a flop
    except ImportError:
        pass  # services.rival_ai.memory not available — proceed
    except Exception:
        pass  # defensive — memory read failure MUST NOT block scheduling

    # 4. Budget gate: estimate event cost.
    estimated_cost = estimate_event_cost(conn, promotion_id, archetype)
    cash = _promotion_cash(conn, promotion_id)
    if cash < estimated_cost * BUDGET_GATE_SAFETY_MARGIN:
        # SURVIVAL mode — skip this week. The budget_manager will
        # update ai_budget_state on the monthly review.
        return None

    # 5. Pick event_date with rival collision avoidance.
    current_date = _current_sim_date(conn)
    if not current_date:
        return None
    event_date = _pick_event_date(conn, promotion_id, archetype, current_date, rng)
    if event_date is None:
        return None

    # 6. Build the card via the rival matchmaker.
    from services.rival_ai.matchmaker import build_card
    card_fights = build_card(conn, promotion_id, event_date, archetype, rng)
    if not card_fights:
        return None  # not enough eligible fighters

    # 7. Build the event name.
    event_name = _build_event_name(conn, promotion_id, card_fights[0])

    # 8. Insert via the shared helper (events + fights + participants
    # + event_cards + training_camps in a single transaction).
    event_id = _insert_event_and_card(
        conn, promotion_id, event_date, card_fights, event_name,
    )
    if event_id is None:
        return None

    # 9. Write a scheduling announcement news item.
    _write_scheduling_news(conn, promotion_id, event_id, event_date, card_fights[0])

    return event_id


def estimate_event_cost(conn, promotion_id, archetype):
    """Estimate the cost of scheduling an event for the promo.

    Per arch doc §3.1 step 2:
        fighter_payouts ≈ monthly_commitment / 4  (one week of salaries)
        venue_cost       ≈ archetype-determined ($200K major / $80K mid / $25K small)
        staff_payouts    ≈ archetype.staff_target total × $5K
        total            = fighter_payouts + venue_cost + staff_payouts

    Returns the total estimated cost (REAL, in dollars). Used by the
    budget gate in `schedule_next_event_for_rival`.
    """
    # Fighter salaries — annual / 12 / 4 (one week of monthly salaries).
    fighter_row = conn.execute(
        "SELECT COALESCE(SUM(c.salary), 0) FROM contracts c "
        "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "WHERE c.promotion_id = ? AND c.status = 'active' "
        "AND c.contract_target_type = 'fighter'",
        (promotion_id,),
    ).fetchone()
    fighter_salaries_annual = float(fighter_row[0]) if fighter_row else 0.0
    fighter_payouts = fighter_salaries_annual / 12.0 / 4.0

    # Venue cost — based on size_tier.
    promo_row = conn.execute(
        "SELECT size_tier FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    size_tier = (promo_row[0] if promo_row else 'small') or 'small'
    venue_cost = VENUE_COST_BY_TIER.get(size_tier.lower(), VENUE_COST_BY_TIER['small'])

    # Staff payouts — archetype.staff_target total × $5K.
    staff_target = archetype.get('staff_target', {})
    staff_count = sum(staff_target.values()) if staff_target else 0
    staff_payouts = staff_count * STAFF_PAYOUT_PER_SLOT

    return fighter_payouts + venue_cost + staff_payouts


def _insert_event_and_card(conn, promotion_id, event_date, fights, event_name):
    """Shared INSERT helper extracted from
    `services.matchmaking.schedule_next_event` (lines ~1300-1490).

    INSERTs:
        - 1 events row (status='scheduled', venue reused from the
          promo's last completed event, or a fallback)
        - N fights rows (5-13 per card_size)
        - N fight_participants rows (2 per fight)
        - N event_cards rows (card_slot per fight)
        - 2N training_camps rows (via _create_training_camp)

    Single transaction — caller commits. Returns the new event_id.

    This mirrors the INSERT block in schedule_next_event (lines
    1387-1489) WITHOUT the matchmaking logic — the caller passes a
    pre-built card. This lets the rival AI use its own matchmaker
    while reusing the same INSERT path.
    """
    # Resolve venue + market — reuse the promo's most recent completed
    # event's venue/market (matches the existing schedule_next_event
    # behaviour). Falls back to any venue in the promo's nation.
    completed = conn.execute(
        "SELECT e.venue_id, e.market_id "
        "FROM events e JOIN fights f ON f.event_id = e.event_id "
        "WHERE e.promotion_id = ? AND e.status = 'completed' "
        "ORDER BY e.event_date DESC LIMIT 1",
        (promotion_id,),
    ).fetchone()
    if completed:
        venue_id, market_id = completed
    else:
        # Fallback: any venue in the promo's nation.
        promo_row = conn.execute(
            "SELECT nation_id FROM promotions WHERE promotion_id=?",
            (promotion_id,),
        ).fetchone()
        nation_id = promo_row[0] if promo_row else None
        if nation_id is None:
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
            return None
        venue_id, market_id = fallback

    # INSERT the events row.
    new_event_id = conn.execute(
        "INSERT INTO events (promotion_id, venue_id, market_id, event_name, "
        "event_date, event_type, status) VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
        (promotion_id, venue_id, market_id, event_name,
         event_date, "fight_night"),
    ).lastrowid

    # INSERT each fight + 2 participants + 1 event_cards row + 2
    # training_camps rows.
    from services.matchmaking import _create_training_camp
    for position, fight in enumerate(fights, start=1):
        new_fight_id = conn.execute(
            "INSERT INTO fights (event_id, weight_class_id, bout_type, "
            "card_slot, is_title_fight, round_limit, scheduled_rounds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_event_id, fight['weight_class_id'], fight['card_slot'],
             fight['card_slot'], fight.get('is_title_fight', 0), 3,
             fight.get('scheduled_rounds', 3)),
        ).lastrowid
        conn.execute(
            "INSERT INTO fight_participants (fight_id, fighter_id, corner) "
            "VALUES (?, ?, 'red')",
            (new_fight_id, fight['fighter_a']),
        )
        conn.execute(
            "INSERT INTO fight_participants (fight_id, fighter_id, corner) "
            "VALUES (?, ?, 'blue')",
            (new_fight_id, fight['fighter_b']),
        )
        conn.execute(
            "INSERT INTO event_cards (event_id, fight_id, card_position, "
            "card_tier, is_main_event, is_co_main) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (new_event_id, new_fight_id, position, fight['card_slot'],
             1 if fight['card_slot'] == 'main_event' else 0,
             1 if fight['card_slot'] == 'co_main' else 0),
        )
        # Training camps for both booked fighters.
        for fid in (fight['fighter_a'], fight['fighter_b']):
            f_row = conn.execute(
                "SELECT current_gym_id, fight_style_archetype_id "
                "FROM fighters WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if f_row is None:
                continue
            f_gym_id, f_archetype_id = f_row
            if f_gym_id is None:
                continue
            try:
                _create_training_camp(
                    conn,
                    fighter_id=fid,
                    gym_id=f_gym_id,
                    event_id=new_event_id,
                    fight_id=new_fight_id,
                    event_date=event_date,
                    style_archetype_id=f_archetype_id,
                )
            except Exception:
                pass  # defensive — a camp failure shouldn't fail the card

    return new_event_id


# ----------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------

def _has_scheduled_event(conn, promotion_id):
    """Return True if the promo already has a 'scheduled' event."""
    row = conn.execute(
        "SELECT 1 FROM events WHERE promotion_id=? AND status='scheduled' "
        "LIMIT 1",
        (promotion_id,),
    ).fetchone()
    return row is not None


def _cadence_elapsed(conn, promotion_id, cadence_days):
    """Return True if at least `cadence_days` have passed since the
    promo's last completed event (or since the seed date if no events
    have been completed yet).
    """
    current_date = _current_sim_date(conn)
    if not current_date:
        return True  # defensive — no sim clock, allow scheduling
    last_row = conn.execute(
        "SELECT event_date FROM events "
        "WHERE promotion_id=? AND status='completed' "
        "ORDER BY event_date DESC LIMIT 1",
        (promotion_id,),
    ).fetchone()
    if last_row is None or not last_row[0]:
        return True  # no completed events yet → cadence elapsed
    try:
        last_dt = datetime.strptime(last_row[0], "%Y-%m-%d")
        cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
        return (cur_dt - last_dt).days >= cadence_days
    except (ValueError, TypeError):
        return True


def _pick_event_date(conn, promotion_id, archetype, current_date, rng):
    """Sample an event_date from the archetype's window with rival
    collision avoidance.

    Per arch doc §3.1 step 3:
      - Sample uniformly from [today + window[0], today + window[1]].
      - If any other promo has a scheduled event within ±2 days,
        re-sample (max 3 attempts).
      - 15% chance to ignore collision (counter-programming whim).
    """
    try:
        cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    win_min, win_max = archetype['event_window_days']
    for attempt in range(MAX_RESAMPLE_ATTEMPTS):
        offset = rng.randint(win_min, win_max)
        event_dt = cur_dt + timedelta(days=offset)
        event_date = event_dt.strftime("%Y-%m-%d")
        # 15% chance to ignore collision (counter-programming whim).
        if rng.random() < 0.15:
            return event_date
        if not _has_rival_collision(conn, promotion_id, event_date):
            return event_date
    # All attempts collided — take the last sample anyway (collision
    # is allowed but discouraged per arch doc §3.1).
    return event_date


def _has_rival_collision(conn, promotion_id, event_date):
    """Return True if any OTHER promo has a scheduled event within
    ±RIVAL_COLLISION_WINDOW_DAYS of `event_date`.
    """
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    low = (event_dt - timedelta(days=RIVAL_COLLISION_WINDOW_DAYS)).strftime("%Y-%m-%d")
    high = (event_dt + timedelta(days=RIVAL_COLLISION_WINDOW_DAYS)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT 1 FROM events "
        "WHERE promotion_id != ? AND status='scheduled' "
        "AND event_date >= ? AND event_date <= ? "
        "LIMIT 1",
        (promotion_id, low, high),
    ).fetchone()
    return row is not None


def _build_event_name(conn, promotion_id, main_event_fight):
    """Build the event name. Format: "{Promo} {N}: {FighterA} vs {FighterB}".

    Mirrors the existing schedule_next_event naming (the 70% default
    format). The number = promo's event count + 1.
    """
    from services.matchmaking import fighter_name
    promo_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_row[0] if promo_row else f"Promotion {promotion_id}"
    event_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()[0]
    me_a_name = fighter_name(conn, main_event_fight['fighter_a'])
    me_b_name = fighter_name(conn, main_event_fight['fighter_b'])
    return f"{promo_name} {event_count + 1}: {me_a_name} vs {me_b_name}"


def _write_scheduling_news(conn, promotion_id, event_id, event_date, main_event_fight):
    """Write a 'scheduling announcement' news item with the main event."""
    from services.rival_ai._shared import write_news_item
    from services.matchmaking import fighter_name
    promo_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_row[0] if promo_row else f"Promotion {promotion_id}"
    me_a_name = fighter_name(conn, main_event_fight['fighter_a'])
    me_b_name = fighter_name(conn, main_event_fight['fighter_b'])
    is_title = main_event_fight.get('is_title_fight', 0)
    if is_title:
        headline = f"{promo_name} books title main event: {me_a_name} vs {me_b_name}"
        body = (f"{promo_name} has announced its next event for {event_date}, "
                f"headlined by a title fight between {me_a_name} and {me_b_name}.")
    else:
        headline = f"{promo_name} announces next event: {me_a_name} vs {me_b_name}"
        body = (f"{promo_name} has announced its next event for {event_date}, "
                f"headlined by {me_a_name} vs {me_b_name}.")
    write_news_item(
        conn,
        headline=headline,
        body=body,
        topic='event_hype',
        sentiment='positive',
        promotion_id=promotion_id,
        event_id=event_id,
        published_at=_current_sim_date(conn),
    )


# ----------------------------------------------------------------
# DB helpers (mirrored from src/rival_ai.py + _shared.py to keep
# this module self-contained — avoids importing the parent module
# which would create a circular dependency through app.py).
# ----------------------------------------------------------------

def _current_sim_date(conn):
    """Return the current sim date string ('YYYY-MM-DD')."""
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else None


def _promotion_cash(conn, promotion_id):
    """Return promotions.current_cash (REAL), or 0.0 if missing."""
    row = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0
