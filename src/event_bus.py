"""CAGE EMPIRE Event Bus (Task 18.5).

A lightweight in-memory pub/sub system that decouples game systems
from the monolithic resolve_next_fight() and _check_retirements()
functions. Per CONVENTIONS §15, the event bus is infrastructure that
supports every system.

ARCHITECTURE:
  - No DB table — the bus is in-memory, per-connection.
  - Events are dicts with a 'type' key + event-specific data.
  - Subscribers are functions that take (conn, event) and execute
    synchronously in registration order.
  - The caller commits after all subscribers have run.

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
  3. If a subscriber raises, the bus catches it, logs the error, and
     continues to the next subscriber (defensive — one broken subscriber
     shouldn't crash the whole game).
  4. The caller commits after publish() returns.

DESIGN DECISIONS:
  - Synchronous (not async) — CAGE EMPIRE is a single-threaded sim.
    Async would add complexity for no benefit.
  - In-memory (not DB-backed) — events are transient. The DB stores
    the RESULTS of events (fight_history, rankings, titles, etc.),
    not the events themselves.
  - No event history table — if we need audit trail, the existing
    tables (fight_history, news_items, etc.) serve that purpose.
  - Subscriber errors are caught and logged — a broken subscriber
    shouldn't prevent other subscribers from running. The error is
    printed to stderr for debugging.
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


class EventBus:
    """In-memory pub/sub event bus for CAGE EMPIRE.

    The bus is created once per connection (or per game session) and
    shared across all systems. Subscribers register for event types;
    publishers emit events that trigger all registered subscribers.

    Thread safety: NOT thread-safe. CAGE EMPIRE is single-threaded.
    """

    def __init__(self):
        self._subscribers = {}  # event_type → list of (name, fn) tuples

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

    def publish(self, conn, event):
        """Publish an event to all subscribers.

        Calls each registered subscriber synchronously in registration
        order. If a subscriber raises an exception, the error is caught,
        printed to stderr, and the next subscriber is called (defensive
        — one broken subscriber shouldn't crash the game).

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
        for name, fn in subscribers:
            try:
                fn(conn, event)
            except Exception as e:
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
