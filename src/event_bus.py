"""CAGE EMPIRE Event Bus (Task 18.5).

A lightweight in-memory pub/sub system that decouples game systems
from the monolithic resolve_next_fight() and _check_retirements()
functions. Per CONVENTIONS §15, the event bus is infrastructure that
supports every system.

ARCHITECTURE:
  - No DB table for events themselves — the bus is in-memory, per-
    connection. Events are dicts with a 'type' key + event-specific
    data. Subscribers are functions that take (conn, event) and
    execute synchronously in registration order. The caller commits
    after all subscribers have run.
  - HW2.1 (v3.29.0): subscriber errors + per-tick counters are now
    PERSISTED to the `simulation_tick_health` table (one row per
    tick). The bus itself accumulates errors in memory during a tick
    via reset_tick_stats() / get_tick_stats(); the tick_processor.
    run_tick() helper writes the summary row at tick end. This means
    a subscriber that throws on EVERY tick is now visible in the DB
    (not just in console scroll), and compute_world_health() (HW2.4)
    can flag the world as DEGRADED based on recent tick_health rows.

USAGE:
  from event_bus import EventBus, Events

  bus = EventBus()

  # Register a subscriber
  bus.subscribe(Events.FIGHT_RESOLVED, my_rankings_updater)

  # Publish an event (calls all subscribers synchronously)
  bus.publish(conn, {
      'type': Events.FIGHT_RESOLVED,
      'fight_id': 42,
      'winner_id': 1,
      'loser_id': 2,
      'result_type': 'ko_tko',
      ...
  })

EVENT LIFECYCLE:
  1. A game action (resolve_next_fight, run_tick, etc.) publishes events.
  2. Each subscriber runs synchronously, in registration order.
  3. If a subscriber raises, the bus catches it, logs the error to
     stderr (existing behavior) AND accumulates it in the per-tick
     stats list (NEW HW2.1) so tick_processor.run_tick can persist
     it to simulation_tick_health at tick end. The bus then continues
     to the next subscriber (defensive — one broken subscriber
     shouldn't crash the whole game).
  4. The caller commits after publish() returns.

DESIGN DECISIONS:
  - Synchronous (not async) — CAGE EMPIRE is a single-threaded sim.
    Async would add complexity for no benefit.
  - In-memory (not DB-backed) for events — events are transient. The
    DB stores the RESULTS of events (fight_history, rankings, titles,
    etc.), not the events themselves. HW2.1 adds a per-tick summary
    row to simulation_tick_health, but that's a summary, not an
    event-by-event audit log.
  - Subscriber errors are caught, printed to stderr (existing), AND
    accumulated in the bus's _tick_stats list (NEW HW2.1) so the
    tick_processor can persist them. A broken subscriber shouldn't
    prevent other subscribers from running.
"""


# ----------------------------------------------------------------
# Event type constants. Using strings (not enums) for simplicity —
# they're just dict keys.
# ----------------------------------------------------------------

class Events:
    """Event type constants for the CAGE EMPIRE event bus."""

    # Fight lifecycle
    FIGHT_RESOLVED = "fight_resolved"
    FIGHT_CANCELLED = "fight_cancelled"  # weight cut cancellation
    TITLE_CHANGED = "title_changed"      # new champion or vacated
    EVENT_COMPLETED = "event_completed"  # all fights on an event resolved

    # Fighter lifecycle
    FIGHTER_RETIRED = "fighter_retired"
    FIGHTER_SIGNED = "fighter_signed"    # free agent signed by promotion
    FIGHTER_GENERATED = "fighter_generated"  # regen replacement spawned

    # Rival AI bidding wars (Phase M3.2 — docs/MASTER_PLAN_MATCHMAKING.md
    # §2.2). Fired when a rival AI decides to pursue a free agent. The
    # player has decision_window_days to make a counter-offer via the
    # counter_offer API. If the player doesn't respond, the rival AI
    # signs the fighter when the window expires.
    SIGNING_INTENT = "signing_intent"

    # Staff lifecycle (Phase M2 — docs/MASTER_PLAN_MATCHMAKING.md §2.3).
    # Staff NEVER aged, NEVER retired, NEVER died, and their contracts
    # NEVER expired. Phase M2 builds the lifecycle.
    #   STAFF_RETIRED          — fired on the annual tick (Jan 1) when
    #                            a staff member's retirement roll
    #                            succeeds. Payload: staff_id,
    #                            role_type, promotion_id, current_date.
    #                            Subscribers: news.generate_staff_
    #                            retired_news (richer career-retirement
    #                            item with voice descriptors).
    #   STAFF_DIED             — reserved for a future phase (death is
    #                            very rare and out of scope for M2 per
    #                            the brief). Defined here so the
    #                            constant exists when the logic lands.
    STAFF_RETIRED = "staff_retired"
    STAFF_DIED = "staff_died"

    # Staff contract lifecycle (Phase M2.4 — docs/MASTER_PLAN_MATCHMAKING.md
    # §2.3). Extends _check_contract_expiry to handle staff_contracts.
    #   STAFF_CONTRACT_EXPIRING — fired when a player-promo staff
    #                            contract's end_date is reached (so
    #                            the UI can alert the player to renew
    #                            or lose the staff). Payload: staff_id,
    #                            contract_id, promotion_id, end_date.
    #   STAFF_CONTRACT_EXPIRED  — fired when a staff contract actually
    #                            expires (status='expired') and the
    #                            staff becomes a free agent. Payload:
    #                            staff_id, contract_id, promotion_id,
    #                            current_date.
    STAFF_CONTRACT_EXPIRING = "staff_contract_expiring"
    STAFF_CONTRACT_EXPIRED = "staff_contract_expired"

    # Contract lifecycle
    CONTRACT_EXPIRED = "contract_expired"

    # Training / development
    CAMP_COMPLETED = "camp_completed"
    CAMP_INJURY = "camp_injury"          # training injury during camp

    # Injury lifecycle
    INJURY_CREATED = "injury_created"    # fight or training injury
    INJURY_RECOVERED = "injury_recovered"

    # Weight cuts
    WEIGHT_CUT_COMPLETED = "weight_cut_completed"

    # Scouting
    SCOUT_REPORT_GENERATED = "scout_report_generated"

    # Descriptor snapshots (generic "fighter changed" event)
    FIGHTER_STATE_CHANGED = "fighter_state_changed"

    # Tick lifecycle
    TICK_ADVANCED = "tick_advanced"

    # Promotion lifecycle
    PROMOTION_BANKRUPT = "promotion_bankrupt"  # cash < 0 for 2+ months


class EventBus:
    """In-memory pub/sub event bus for CAGE EMPIRE.

    The bus is created once per connection (or per game session) and
    shared across all systems. Subscribers register for event types;
    publishers emit events that trigger all registered subscribers.

    Thread safety: NOT thread-safe. CAGE EMPIRE is single-threaded.
    """

    def __init__(self):
        self._subscribers = {}  # event_type → list of (name, fn) tuples
        # HW2.1: per-tick stats accumulated across all publish() calls
        # between reset_tick_stats() and get_tick_stats(). The tick_
        # processor calls reset_tick_stats() at the start of run_tick
        # and get_tick_stats() at the end to write the simulation_tick_
        # health summary row.
        self._tick_stats = {
            "invoked": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
        }

    def subscribe(self, event_type, subscriber_fn, name=None):
        """Register a subscriber for an event type.

        Args:
            event_type: one of the Events.* constants (or any string).
            subscriber_fn: a function (conn, event) → None. Called
                synchronously when an event of this type is published.
            name: optional name for debugging. Defaults to the function's
                __name__.

        Returns:
            None.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        sub_name = name or getattr(subscriber_fn, '__name__', 'anonymous')
        self._subscribers[event_type].append((sub_name, subscriber_fn))

    def unsubscribe(self, event_type, subscriber_fn):
        """Remove a subscriber. Useful for testing."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                (name, fn) for name, fn in self._subscribers[event_type]
                if fn != subscriber_fn
            ]

    def reset_tick_stats(self):
        """HW2.1: Clear the per-tick stats counters.

        Called by tick_processor.run_tick at the START of each tick
        (before any subscribers fire). After this call, _tick_stats is
        zeroed; subsequent publish() calls accumulate into it.
        """
        self._tick_stats = {
            "invoked": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
        }

    def get_tick_stats(self):
        """HW2.1: Return a snapshot of the per-tick stats.

        Called by tick_processor.run_tick at the END of each tick (after
        all subscribers have fired) to write the simulation_tick_health
        summary row. The returned dict has keys:
            invoked, succeeded, failed (ints)
            errors (list of dicts: subscriber, event_type, error_type,
                    error_message, traceback, sim_date)

        Returns:
            dict (a shallow copy so the caller can mutate without
            affecting the bus's internal state).
        """
        return {
            "invoked": self._tick_stats["invoked"],
            "succeeded": self._tick_stats["succeeded"],
            "failed": self._tick_stats["failed"],
            "errors": list(self._tick_stats["errors"]),
        }

    def publish(self, conn, event):
        """Publish an event to all subscribers.

        Calls each registered subscriber synchronously in registration
        order. If a subscriber raises an exception, the error is:
          (a) printed to stderr (existing behavior — preserves the
              pre-HW2.1 dev-console trail),
          (b) accumulated in self._tick_stats["errors"] (NEW HW2.1)
              so tick_processor.run_tick can persist it to the
              simulation_tick_health table at tick end.

        Per-tick counters (invoked/succeeded/failed) are also
        incremented (NEW HW2.1) so the tick health row records how
        many subscribers ran and how many failed.

        The next subscriber is always called (defensive — one broken
        subscriber shouldn't crash the game).

        Args:
            conn: sqlite3 connection (passed to each subscriber).
            event: dict with at least a 'type' key.
        """
        event_type = event.get('type')
        if event_type is None:
            import sys
            print(f"WARNING: event has no 'type' key: {event}", file=sys.stderr)
            return

        subscribers = self._subscribers.get(event_type, [])
        import sys
        import traceback as _tb
        for name, fn in subscribers:
            self._tick_stats["invoked"] += 1
            try:
                fn(conn, event)
                self._tick_stats["succeeded"] += 1
            except Exception as e:
                self._tick_stats["failed"] += 1
                # Build the error record. sim_date comes from the
                # event payload if present (TICK_ADVANCED carries
                # current_date) or from the simulation_clock table
                # as a fallback.
                sim_date = event.get('current_date')
                if not sim_date:
                    try:
                        _row = conn.execute(
                            "SELECT simulation_clock.current_date "
                            "FROM simulation_clock WHERE clock_id=1"
                        ).fetchone()
                        sim_date = _row[0] if _row else None
                    except Exception:
                        sim_date = None
                err = {
                    "subscriber": name,
                    "event_type": event_type,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "traceback": _tb.format_exc(),
                    "sim_date": sim_date,
                }
                self._tick_stats["errors"].append(err)
                print(f"WARNING: subscriber '{name}' failed on event "
                      f"'{event_type}': {type(e).__name__}: {e}",
                      file=sys.stderr)

    def subscriber_count(self, event_type=None):
        """Return the number of registered subscribers.

        Args:
            event_type: if None, returns total across all event types.
        """
        if event_type is None:
            return sum(len(subs) for subs in self._subscribers.values())
        return len(self._subscribers.get(event_type, []))

    def registered_events(self):
        """Return a set of all event types that have subscribers."""
        return set(self._subscribers.keys())


# ----------------------------------------------------------------
# Global bus instance. Created once at module load. All systems
# import this instance and register their subscribers.
#
# The bus is populated by _register_default_subscribers() which is
# called lazily on first access (or explicitly by the caller). This
# avoids circular import issues — subscribers are registered after
# all modules are loaded.
# ----------------------------------------------------------------

_bus = None


def get_bus():
    """Get the global EventBus instance (lazy singleton).

    On first call, creates the bus and registers the default
    subscribers (all existing side-effect functions from app.py and
    tick_processor.py).
    """
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_bus():
    """Reset the global bus (for testing)."""
    global _bus
    _bus = EventBus()
