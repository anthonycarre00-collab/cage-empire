"""CAGE EMPIRE Fighter Suspensions (Phase B — B1).

Fighter suspensions for drug test failures, behavioral incidents,
post-fight brawls, and other commission / promotion infractions.
Entirely event-bus-driven (CONVENTIONS §15.4) — no inline side
effects added to resolve_next_fight or run_tick. Subscribes to
FIGHT_RESOLVED (rolls the dice on each fight) and TICK_ADVANCED
(clears suspensions whose end_date has passed). Per docs/FULL_BUILD_
AUDIT.md §9a.

CONVENTIONS compliance:
  §5  — One table-group per task. The `suspensions` table is the
        single group this task adds (along with its writer — this
        module — and its reader — app._pick_matchup).
  §13 — Design Law: suspensions strengthen Conflict (a fighter
        caught cheating is a generational scandal; a champion
        suspended creates an immediate power vacuum) and Stories
        (the clearance news writes a "return from the wilderness"
        narrative — the player remembers the comeback). A suspended
        champion is anticipation incarnate — what happens to the
        title? Will the contender get stripped or wait? Every
        suspension opens a thread the player wants to resolve.
  §14 — Voice Layer: NO raw attribute values, suspension counts,
        or day counts appear in any player-facing text. The
        duration_days column is INTERNAL — the news text uses word-
        form phrases ("six months", "the rest of the year", "an
        extended ban") and voice.describe_career_stage for the
        fighter's narrative context ("the reigning champion fails
        a drug test" reads very differently from "an unproven
        prospect fails a drug test"). The description column is
        an admin note, never displayed.
  §15 — Event Bus: the suspension system is entirely event-driven.
        It subscribes to FIGHT_RESOLVED (random trigger) and
        TICK_ADVANCED (recovery scan). It does NOT add any inline
        side effects to resolve_next_fight or run_tick — the
        suspension writes happen as a downstream subscriber.

SUSPENSION RATES (rare by design — per the brief):
  drug_test_failure  : 1% per fight  (commission drug testing)
  behavior           : 0.5% per fight (higher for high-aggression
                                      + low-discipline fighters)

These rates are deliberately low. A 1% chance per fight means the
average 4000-fighter world sees ~1-2 drug test failures per real-
world week of simulation (4000 fighters * ~0.05 fights/week * 0.01
= ~2/week). The rarity is what makes each suspension a story — if
they happened every fight, they'd be background noise.

MORALE + MARKETABILITY IMPACT (per the brief):
  drug_test_failure  : morale -20, marketability -15 (career hit)
  behavior           : morale -10                 (reputation hit)

The morale drop is applied via fighter_personality.morale (which
the fight engine reads via _load_fighter_stats). The marketability
drop is applied via fighters.marketability. Both are clamped to
their valid ranges by the same helpers used elsewhere.

USAGE:
  from suspensions import register_subscribers
  register_subscribers()  # call once at startup (UI App.__init__,
                          # test setup). Safe to call multiple times.
  # The suspension system processes events automatically via the bus.
  # Direct reader: is_fighter_suspended(conn, fighter_id) for any
  # caller that needs to check (used by app._pick_matchup's SQL).
"""

import random
from datetime import datetime, timedelta


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# Suspension trigger probabilities (per fight, per the brief). These
# are RARE — a suspension is a big story, not background noise. The
# behavior chance is bumped for high-aggression + low-discipline
# fighters (the "loose cannon" multiplier below).
DRUG_TEST_FAILURE_CHANCE = 0.01   # 1% per fight
BEHAVIOR_BASE_CHANCE     = 0.005  # 0.5% per fight (base)

# The "loose cannon" multiplier. A fighter with aggression >= 70 AND
# discipline <= 30 gets BEHAVIOR_BASE_CHANCE * this multiplier as
# their behavior-suspension chance. The brief says "higher for high-
# aggression + low-discipline fighters" — 3x keeps it rare (1.5%
# for these fighters) but makes the loose-cannon archetype actually
# feel loose-cannon.
LOOSE_CANNON_MULT        = 3.0
LOOSE_CANNON_AGGRESSION  = 70
LOOSE_CANNON_DISCIPLINE  = 30

# Duration ranges (in days). Per the brief:
#   drug_test_failure: 6-12 months  (180-365 days)
#   behavior:          3-6 months   (90-180 days)
# We pick a random day count within the range. The CHECK constraint
# on suspensions.duration_days enforces > 0.
DRUG_TEST_DURATION_MIN = 180
DRUG_TEST_DURATION_MAX = 365
BEHAVIOR_DURATION_MIN  = 90
BEHAVIOR_DURATION_MAX  = 180

# Morale + marketability penalties (per the brief). Applied directly
# to fighter_personality.morale + fighters.marketability on trigger.
DRUG_TEST_MORALE_HIT         = -20
DRUG_TEST_MARKETABILITY_HIT  = -15
BEHAVIOR_MORALE_HIT          = -10

# Morale bounds (mirror morale.py — same [10, 95] clamp so a
# suspension doesn't bottom out a fighter's morale to 0).
MORALE_FLOOR = 10
MORALE_CEIL  = 95

# Marketability bounds (mirror morale.py — [0, 100] is the natural
# range; we floor at 0 since marketability has no upper CHECK).
MARKETABILITY_FLOOR = 0
MARKETABILITY_CEIL  = 100


# ----------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------

def _clamp_morale(v):
    """Clamp morale to [MORALE_FLOOR, MORALE_CEIL] (mirrors morale.py)."""
    return max(MORALE_FLOOR, min(MORALE_CEIL, int(v)))


def _clamp_marketability(v):
    """Clamp marketability to [MARKETABILITY_FLOOR, MARKETABILITY_CEIL]."""
    return max(MARKETABILITY_FLOOR, min(MARKETABILITY_CEIL, int(v)))


def _get_morale(conn, fighter_id):
    """Return the fighter's current morale (default 50 if no row)."""
    row = conn.execute(
        "SELECT morale FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 50


def _set_morale(conn, fighter_id, new_morale):
    """Update a fighter's morale (clamped to [10, 95])."""
    clamped = _clamp_morale(new_morale)
    conn.execute(
        "UPDATE fighter_personality SET morale=? WHERE fighter_id=?",
        (clamped, fighter_id),
    )


def _get_marketability(conn, fighter_id):
    """Return the fighter's current marketability (default 50)."""
    row = conn.execute(
        "SELECT marketability FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 50


def _set_marketability(conn, fighter_id, new_marketability):
    """Update a fighter's marketability (clamped to [0, 100])."""
    clamped = _clamp_marketability(new_marketability)
    conn.execute(
        "UPDATE fighters SET marketability=? WHERE fighter_id=?",
        (clamped, fighter_id),
    )


def _get_personality(conn, fighter_id, trait):
    """Return one fighter_personality trait value (default 50)."""
    if trait not in ("aggression", "discipline", "composure",
                     "killer_instinct", "ego"):
        # Defensive — only allow the traits we actually read.
        raise ValueError(f"refusing to read unknown personality trait {trait!r}")
    row = conn.execute(
        f"SELECT {trait} FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 50


def _add_days(date_str, days):
    """Add `days` to an ISO date string, return ISO date string.

    Returns the original date_str if parsing fails (defensive — the
    seed DB sometimes has weird dates on historical rows).
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str


def _today(conn):
    """Return the sim clock's current_date (or a sensible default)."""
    row = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock "
        "WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else "2026-08-15"


# ----------------------------------------------------------------
# Reader — used by app._pick_matchup (SQL excludes via NOT IN)
# ----------------------------------------------------------------

def is_fighter_suspended(conn, fighter_id):
    """Return True if the fighter has an ACTIVE suspension.

    A fighter is suspended if any row in `suspensions` has
    fighter_id == fighter_id AND is_active == 1. Cleared
    suspensions (is_active=0) don't count — the fighter is free
    to book again.

    This is the reader required by CONVENTIONS §5.3 (every new
    table ships with at least one reader). app._pick_matchup
    uses the SQL form `AND fighter_id NOT IN (SELECT fighter_id
    FROM suspensions WHERE is_active = 1)` directly — this Python
    helper is for tests + any other caller that wants the same
    check without re-implementing the SQL.
    """
    row = conn.execute(
        "SELECT 1 FROM suspensions "
        "WHERE fighter_id=? AND is_active=1",
        (fighter_id,),
    ).fetchone()
    return row is not None


# ----------------------------------------------------------------
# Writer — FIGHT_RESOLVED subscriber
# ----------------------------------------------------------------

def _maybe_random_suspension(conn, event):
    """FIGHT_RESOLVED subscriber — roll the dice on each resolved fight.

    Per the brief:
      - 1% chance of drug_test_failure on EITHER fighter (winner
        or loser — drug tests are administered to both, but we
        roll once per fight to keep the math simple).
      - 0.5% chance of behavior suspension (higher for high-
        aggression + low-discipline fighters).

    On trigger:
      - drug_test_failure: 6-12 month suspension, morale -20,
        marketability -15.
      - behavior: 3-6 month suspension, morale -10.

    Writes the suspensions row. The news engine subscriber
    (news.generate_suspension_news) polls for new suspensions on
    TICK_ADVANCED and writes the news item — see src/news.py.

    Defensive — early-returns if the event is missing required
    fields (winner_id, loser_id, event_date). The trigger is
    probabilistic, so for testing this function can be monkey-
    patched or called directly with a forced probability.
    """
    rng = random.Random()

    winner_id = event.get("winner_id")
    loser_id  = event.get("loser_id")
    event_date = event.get("event_date") or _today(conn)
    fight_id   = event.get("fight_id")
    event_id   = event.get("event_id")
    promotion_id = event.get("promotion_id")

    if not winner_id or not loser_id:
        return

    # Pick which fighter (winner or loser) is the candidate for the
    # suspension roll. We roll ONCE per fight — a single random
    # fighter (winner or loser) is the "subject" of the dice roll.
    # This keeps the rate math clean: 1% per fight, not 2% per fight.
    # (A drug test failure affects one fighter, not both.)
    candidate_id = rng.choice([winner_id, loser_id])

    # Drug test failure: 1% per fight, flat rate. The brief says
    # "1% per fight" — no personality modifier for drug tests
    # (anyone can get caught).
    if rng.random() < DRUG_TEST_FAILURE_CHANCE:
        duration_days = rng.randint(
            DRUG_TEST_DURATION_MIN, DRUG_TEST_DURATION_MAX,
        )
        _create_suspension(
            conn, candidate_id, "drug_test_failure",
            duration_days, event_date, fight_id=fight_id,
            event_id=event_id, promotion_id=promotion_id,
            rng=rng,
        )
        # Apply morale + marketability hits.
        morale = _get_morale(conn, candidate_id)
        _set_morale(conn, candidate_id, morale + DRUG_TEST_MORALE_HIT)
        marketability = _get_marketability(conn, candidate_id)
        _set_marketability(
            conn, candidate_id,
            marketability + DRUG_TEST_MARKETABILITY_HIT,
        )
        return

    # Behavior: 0.5% base, 3x (1.5%) for high-aggression + low-
    # discipline fighters (the "loose cannon" archetype — per the
    # brief). The bump makes the loose-cannon archetype actually
    # feel loose-cannon — a fighter with aggression 85 + discipline
    # 20 is ~3x more likely to draw a behavior suspension than a
    # measured fighter.
    behavior_chance = BEHAVIOR_BASE_CHANCE
    aggression = _get_personality(conn, candidate_id, "aggression")
    discipline = _get_personality(conn, candidate_id, "discipline")
    if (aggression >= LOOSE_CANNON_AGGRESSION
            and discipline <= LOOSE_CANNON_DISCIPLINE):
        behavior_chance *= LOOSE_CANNON_MULT

    if rng.random() < behavior_chance:
        duration_days = rng.randint(
            BEHAVIOR_DURATION_MIN, BEHAVIOR_DURATION_MAX,
        )
        _create_suspension(
            conn, candidate_id, "behavior",
            duration_days, event_date, fight_id=fight_id,
            event_id=event_id, promotion_id=promotion_id,
            rng=rng,
        )
        # Apply morale hit (no marketability hit for behavior —
        # the brief only specifies morale -10 for behavior).
        morale = _get_morale(conn, candidate_id)
        _set_morale(conn, candidate_id, morale + BEHAVIOR_MORALE_HIT)


def _create_suspension(conn, fighter_id, suspension_type, duration_days,
                       start_date, fight_id=None, event_id=None,
                       promotion_id=None, rng=None, description=None):
    """Insert one suspensions row. Caller commits.

    Args:
        conn: sqlite3.Connection (caller commits).
        fighter_id: the suspended fighter.
        suspension_type: one of the 5 CHECK values.
        duration_days: integer > 0 (CHECK constraint).
        start_date: ISO date string (typically the fight's event_date).
        fight_id, event_id, promotion_id: stored in the description
            admin note for audit trail (NOT player-facing — the news
            engine subscriber writes the player-facing narrative).
        rng: unused here (kept for API symmetry with _maybe_random).
        description: optional admin note. Auto-built if None.

    Returns the new suspension_id.

    Defensive — guards against the same fighter getting a second
    active suspension for the same type (rare, but possible if the
    RNG fires twice in close succession). If an active suspension
    of the same type already exists, this is a no-op and returns
    the existing suspension_id.
    """
    # Idempotency guard: don't stack two active suspensions of the
    # same type on one fighter. A fresh suspension of a different
    # type IS allowed (e.g., a fighter could pick up a behavior
    # suspension while serving a drug-test ban — though in practice
    # the FIGHT_RESOLVED subscriber won't fire on a suspended
    # fighter because _pick_matchup excludes them).
    existing = conn.execute(
        "SELECT suspension_id FROM suspensions "
        "WHERE fighter_id=? AND suspension_type=? AND is_active=1",
        (fighter_id, suspension_type),
    ).fetchone()
    if existing:
        return existing[0]

    end_date = _add_days(start_date, duration_days)
    if description is None:
        # Admin note (NOT player-facing). Captures context for
        # debugging — which fight, which event, which promotion.
        description = (
            f"Auto-generated on fight_id={fight_id} "
            f"event_id={event_id} promotion_id={promotion_id}"
        )

    cur = conn.execute(
        "INSERT INTO suspensions "
        "(fighter_id, suspension_type, start_date, end_date, "
        " duration_days, description, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (fighter_id, suspension_type, start_date, end_date,
         duration_days, description),
    )
    return cur.lastrowid


# ----------------------------------------------------------------
# Recovery — TICK_ADVANCED subscriber
# ----------------------------------------------------------------

def check_suspension_recovery(conn, event):
    """TICK_ADVANCED subscriber — clear suspensions whose end_date passed.

    Scans `suspensions` for rows where is_active=1 AND end_date <
    current_date. For each, sets is_active=0 (cleared) and writes
    a clearance news item via the news engine (the polling
    subscriber in news.py picks up new is_active=0 transitions).

    The clearance news writes the "return from the wilderness"
    narrative — the fighter comes back, the player sees the news
    item, the fighter becomes bookable again. This is the
    narrative payoff for the suspension arc.

    Defensive — early-returns if event has no current_date (the
    TICK_ADVANCED event always has one, but tests may not).
    """
    current_date = event.get("current_date")
    if not current_date:
        return

    # Find all active suspensions whose end_date has passed.
    # end_date is stored as ISO date string (YYYY-MM-DD), so string
    # comparison works (it's lexically ordered the same as date order).
    expired = conn.execute(
        "SELECT suspension_id, fighter_id, suspension_type, "
        "start_date, end_date, duration_days "
        "FROM suspensions WHERE is_active=1 AND end_date < ?",
        (current_date,),
    ).fetchall()

    for (susp_id, fighter_id, susp_type, start_date,
         end_date, duration_days) in expired:
        # Clear the suspension.
        conn.execute(
            "UPDATE suspensions SET is_active=0 WHERE suspension_id=?",
            (susp_id,),
        )
        # The clearance news item is written by the news engine
        # subscriber (news.generate_suspension_clearance_news) which
        # polls for newly-cleared suspensions on the same TICK_ADVANCED
        # event. We DON'T write the news here — that would be an
        # inline side effect (CONVENTIONS §15.4). The subscriber in
        # news.py handles it (separation of concerns: this module
        # manages the suspension state; news.py manages the narrative).


# ----------------------------------------------------------------
# Registration
# ----------------------------------------------------------------

def register_subscribers():
    """Register all suspensions subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior registrations.

    Subscribes to:
      FIGHT_RESOLVED → _maybe_random_suspension
      TICK_ADVANCED  → check_suspension_recovery
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.FIGHT_RESOLVED, _maybe_random_suspension,
        name="suspensions.maybe_random_suspension",
    )
    bus.subscribe(
        Events.TICK_ADVANCED, check_suspension_recovery,
        name="suspensions.check_suspension_recovery",
    )
