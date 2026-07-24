"""CAGE EMPIRE Venues / Markets Deeper Simulation (Stage 5 — Task 27).

Adds deeper market simulation via event-bus subscribers. Code-only —
NO schema change (uses existing `markets` + `venues` + `events`
tables). Per CONVENTIONS §15.4 — entirely event-bus-driven, no new
inline side effects added to resolve_next_fight or run_tick.

The existing `markets` table has: market_id, city_id, market_type,
heat_level (0-100), created_at, updated_at. The existing `venues`
table has: venue_id, city_id, name, capacity, created_at, updated_at.

The finance system (Task 20) already uses market_heat for ticket
pricing and fill rates. This deeper simulation makes those numbers
DYNAMIC over time — a market that keeps getting good shows becomes
a hotter MMA market (more ticket sales next time). Per the brief:

  - After each event at a venue (EVENT_COMPLETED subscriber):
    - Successful events (high fan rating) → +2 heat.
    - Poor events (low fan rating) → -1 heat.
    - Middling events (fan rating 40-69) → no change.
    - Reads fan_rating from show_ratings (Task 26 writes this).

  - On monthly tick (TICK_ADVANCED subscriber):
    - Hot markets (heat 80+) slowly cool toward 70.
    - Cold markets (heat <30) slowly warm toward 40.
    - Drift is ±1 per month (SLOW — takes many events to shift a
      market significantly).

This means markets evolve over time — a market that hosts a series
of great shows becomes a hotter MMA market (higher ticket prices,
higher fill rates via finance.py's _compute_fill_rate). A market
that hosts poor shows cools down. And without any events, hot
markets cool (fans get complacent) while cold markets warm (new
fans discover the sport). This creates the dynamic-world feel the
Soul document mandates.

VOICE LAYER (CONVENTIONS §14): this system produces NO player-facing
text. Market heat is internal state that feeds finance calculations
(ticket pricing, fill rates) and the descriptor snapshot. No raw
numbers leak because the system writes no prose of its own.

DESIGN LAW (CONVENTIONS §13):
  - Investment: the player's investment in booking good cards in a
    specific market pays off — that market grows hotter, generating
    more revenue for future events. The "build a regional empire"
    fantasy is now a real sim state.
  - Anticipation: a market that's heating up creates the "next show
    there will be even bigger" thread. A cooling market creates the
    "I need to book a better card there to re-ignite the fanbase"
    thread.
  - Stories: venues + markets now have a history. "Metro City was
    once a hot MMA market, but a string of lackluster cards cooled
    the fans" — that's a story, not just numbers moving.

USAGE:
  from venues import register_subscribers
  register_subscribers()  # call once at startup
  # The venues system processes events automatically via the bus.
  # No need to call any function directly.
"""


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# Fan-rating thresholds for market heat adjustment (per the brief).
# Successful events (high fan rating) → +2 heat. Poor events (low
# fan rating) → -1 heat. Middling events → no change.
SUCCESS_FAN_RATING_THRESHOLD = 70  # >= 70 → +2 heat
POOR_FAN_RATING_THRESHOLD = 40     # < 40 → -1 heat

# Heat adjustment deltas.
SUCCESS_HEAT_DELTA = +2
POOR_HEAT_DELTA = -1

# Monthly drift thresholds (per the brief).
# Hot markets (heat 80+) slowly cool toward 70.
# Cold markets (heat <30) slowly warm toward 40.
HOT_MARKET_THRESHOLD = 80   # >= 80 → cool by 1 (toward 70)
HOT_MARKET_FLOOR = 70       # never cool below 70
COLD_MARKET_THRESHOLD = 30  # < 30 → warm by 1 (toward 40)
COLD_MARKET_CEILING = 40    # never warm above 40

# Monthly tick interval (every 30 sim days).
MONTHLY_TICK_INTERVAL_DAYS = 30


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _clamp_heat(v):
    """Clamp a heat value to [0, 100]."""
    return max(0, min(100, int(v)))


# ----------------------------------------------------------------
# EVENT_COMPLETED subscriber — market heat adjustment
# ----------------------------------------------------------------

def _adjust_market_heat(conn, event):
    """Subscriber for EVENT_COMPLETED — adjust market heat.

    Reads fan_rating from show_ratings (written by show_rating.py on
    the same EVENT_COMPLETED event — registration order matters:
    show_rating must register before venues in App.__init__).

    - fan_rating >= 70 → market heat +2 (successful event).
    - fan_rating < 40 → market heat -1 (poor event).
    - Otherwise → no change.

    Defensive: if no show_ratings row exists yet (shouldn't happen
    if registration order is correct, but defensive), skip the
    adjustment rather than guessing.
    """
    event_id = event.get('event_id')
    if not event_id:
        return

    # Read the fan_rating from show_ratings. If show_rating hasn't
    # run yet (registration order issue), skip — no adjustment.
    rating_row = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if not rating_row:
        return
    fan_rating = rating_row[0]
    if fan_rating is None:
        return

    # Determine the heat delta based on fan_rating.
    if fan_rating >= SUCCESS_FAN_RATING_THRESHOLD:
        delta = SUCCESS_HEAT_DELTA
    elif fan_rating < POOR_FAN_RATING_THRESHOLD:
        delta = POOR_HEAT_DELTA
    else:
        return  # middling show — no change

    # Get the market_id for this event.
    event_row = conn.execute(
        "SELECT market_id FROM events WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if not event_row or not event_row[0]:
        return
    market_id = event_row[0]

    # Apply the heat adjustment (clamped to [0, 100]).
    conn.execute(
        "UPDATE markets SET "
        "heat_level = MIN(100, MAX(0, heat_level + ?)), "
        "updated_at = CURRENT_TIMESTAMP "
        "WHERE market_id=?",
        (delta, market_id),
    )


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber — monthly market heat drift
# ----------------------------------------------------------------

def _drift_market_heat(conn, event):
    """Subscriber for TICK_ADVANCED — monthly market heat drift.

    Fires on every tick, but only acts on monthly ticks
    (current_day % 30 == 0). Per the brief:
      - Hot markets (heat >= 80) cool by 1 (toward 70, floor 70).
      - Cold markets (heat < 30) warm by 1 (toward 40, ceiling 40).
      - Middling markets (30-79) — no drift.

    The drift is SLOW (±1 per month). It takes many monthly ticks
    to shift a market significantly. This is intentional — markets
    shouldn't yo-yo.
    """
    # Only act on monthly ticks.
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not row or row[0] is None:
        return
    current_day = row[0]
    if (current_day % MONTHLY_TICK_INTERVAL_DAYS) != 0:
        return

    # Drift all markets. Iterate one at a time so each UPDATE is
    # conditional on the current heat (avoid a single bulk UPDATE
    # that would need a complex CASE expression).
    markets = conn.execute(
        "SELECT market_id, heat_level FROM markets"
    ).fetchall()
    for market_id, heat in markets:
        if heat is None:
            continue
        if heat >= HOT_MARKET_THRESHOLD:
            # Cool toward 70 (floor at 70 — never cool below 70).
            new_heat = max(HOT_MARKET_FLOOR, heat - 1)
        elif heat < COLD_MARKET_THRESHOLD:
            # Warm toward 40 (ceiling at 40 — never warm above 40).
            new_heat = min(COLD_MARKET_CEILING, heat + 1)
        else:
            continue  # middling market — no drift
        if new_heat != heat:
            conn.execute(
                "UPDATE markets SET heat_level=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE market_id=?",
                (new_heat, market_id),
            )


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def register_subscribers():
    """Register the venues/markets system subscribers on the event bus.

    Call once at startup (after event_bus is available). Safe to
    call multiple times.

    NOTE: show_rating.register_subscribers() MUST be called BEFORE
    this function (so show_rating fires first on EVENT_COMPLETED,
    writing the show_ratings row that this module's
    _adjust_market_heat reads). The App.__init__ registration order
    enforces this.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.EVENT_COMPLETED, _adjust_market_heat,
                  name="venues.adjust_market_heat")
    bus.subscribe(Events.TICK_ADVANCED, _drift_market_heat,
                  name="venues.drift_market_heat")
