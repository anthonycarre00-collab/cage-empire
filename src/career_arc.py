"""CAGE EMPIRE Natural Career Arc System (Task ID Stage5-25+CareerArc).

Closes the "frozen attribute" gap the user identified: fighter growth
was only affected by training/camps and long-term injury damage. A
20-year-old prospect should see slight natural improvement in
speed/explosiveness just from maturing physically. A 36-year-old
veteran should see natural decline in cardio, speed, chin, durability
— even without injuries. This is the slow current beneath the camp-
driven growth; without it, careers feel frozen between fights.

This is subtle, ORGANIC change. The brief: "+/-1 per month per
attribute, with random chance. Over a year that's 0-12 per attribute.
Over a 10-year career, that's significant but gradual."

Three age bands:
  Growth (18-27): physical maturation + technical learning. Random
    chance per month (NOT guaranteed — some prospects plateau young,
    others fill out unexpectedly). Capped at effective_ceiling (the
    same formula training camps use: potential * age_factor *
    health_factor * personality_factor).
  Prime (28-29): no natural change. Only camp-based growth applies.
    A fighter in their prime is who they are.
  Decline (30+): age-graded decay, accelerating with each threshold.
    - cardio: -1/month after age 32 (80% chance)
    - speed_explosiveness: -1/month after age 34 (70% chance)
    - chin: -1/month after age 35 (60% chance — chins crack with age)
    - durability: -1/month after age 36 (70% chance)
    - recovery_rate: -1/month after age 33 (75% chance)
    - flexibility: -1/month after age 35 (60% chance)
    Decline is NOT capped — aging breaks through the effective_ceiling
    (that's the whole point of decline — father time wins).

Some fighters age gracefully (lucky RNG), some fall off a cliff (unlucky
RNG). The "he's never the same after 35" stories come from this system.
The "still going strong at 38" stories come from this system too.

Entirely event-bus-driven (CONVENTIONS §15.4 — no new inline side
effects added to run_tick). Subscribes to TICK_ADVANCED. Detects a
MONTHLY tick (current_day % 30 == 0 — chosen to avoid heavy processor
use on every daily tick; ~12 monthly ticks per sim year). Updates
only ACTIVE fighters (is_active=1, is_retired=0).

CONVENTIONS compliance:
  §5  — One table-group per task. NO new table — this module updates
        the existing fighter_attributes table (the writer is this
        subscriber; the reader is everywhere that already reads
        fighter_attributes — the fight engine, scouting, etc.).
  §13 — Design Law: Growth (fighters develop over a career, not just
        in camps — the "prospect matures into contender" storyline).
        Legacy (the veteran fading creates the "last run?" and
        "passing the torch" storylines — careers have natural arcs
        that compound with title reigns and rivalries into the
        memories the player collects).
  §14 — Voice Layer: the rare "father time catches up" news item
        uses voice.describe_career_stage for the fighter's career-
        stage descriptor. NO raw attribute numbers, age-as-int, or
        delta values appear in the news text. The player sees
        "grizzled veteran shows signs of slowing down" — NOT
        "Cardio -5, Age 35".
  §15 — Event Bus: entirely event-driven. Subscribes to TICK_ADVANCED.
        Does NOT modify run_tick or resolve_next_fight.

USAGE:
  from career_arc import register_subscribers
  register_subscribers()  # call once at startup (UI App.__init__,
                          # test setup). Safe to call multiple times.

DESIGN DECISIONS:
  - Monthly cadence (not daily) — daily would be 30x heavier on the
    processor with no perceptual difference. ~12 monthly ticks per
    sim year is enough granularity for an organic-feeling arc.
  - Random chance per attribute per month — NOT deterministic. This
    creates the "age gracefully / fall off a cliff" variance. Two
    34-year-olds in the same month can have totally different
    decline outcomes.
  - Growth is capped at effective_ceiling (same formula as camps).
    Decline is NOT capped — a fighter can decline well below their
    ceiling (and below 50 — the schema DEFAULT for v2.0.0 columns
    with CHECK 0-100). The CHECK floor is 0, so we floor at 0.
  - We do NOT touch attributes the fighter hasn't been training
    during the growth phase. This is GENERAL maturation (speed,
    strength, fight_iq) — not focused improvement (camps do that).
    The decline phase, by contrast, hits specific age-vulnerable
    attributes regardless of training — father time doesn't care
    what you've been working on.
  - News items are RARE — only generated for fighters declining 5+
    points in a single month. This avoids news spam (with ~4000
    active fighters, even a 1% rate would be 40 news items per
    month). The 5+ point threshold catches the "cliff" declines
    that matter narratively.
  - We refresh the descriptor snapshot after each fighter's update
    so the UI sees the new attribute tier immediately.
"""

import random
from datetime import datetime


# ----------------------------------------------------------------
# Age band thresholds (per the brief).
# ----------------------------------------------------------------

# Growth band: physical maturation + technical learning.
GROWTH_AGE_MIN = 18
GROWTH_AGE_MAX = 27

# Prime band: no natural change (only camp-based growth applies).
PRIME_AGE_MIN = 28
PRIME_AGE_MAX = 29

# Decline band: age-graded decay. Each attribute has its own onset.
# These mirror the real-world MMA aging curve — cardio goes first,
# then speed, then chin, then durability.
DECLINE_AGE_MIN = 30  # anything 30+ may be subject to some decline

# Per-attribute decline onset ages + monthly probability.
# The probabilities create the "some age well, some don't" variance.
# A 60% chance per month = ~7 hits per year on average. Over a 3-year
# decline window (e.g. chin 35-38), that's ~21 points of chin loss —
# enough to turn an "elite chin" into a "limited chin" without
# breaking the fighter instantly.
DECLINE_RULES = [
    # (attribute_name, onset_age, monthly_probability)
    ("cardio",              32, 0.80),
    ("recovery_rate",       33, 0.75),
    ("speed_explosiveness", 34, 0.70),
    ("chin",                35, 0.60),
    ("flexibility",         35, 0.60),
    ("durability",          36, 0.70),
]

# Growth probabilities (monthly chance per attribute).
# Physical maturation: speed + strength (70%).
# Technical learning: fight_iq (60% — fighters learn from being in
# the gym, even without a focused camp).
GROWTH_RULES = [
    # (attribute_name, monthly_probability)
    ("speed_explosiveness", 0.70),
    ("strength",            0.70),
    ("fight_iq",            0.60),
]

# News threshold — only generate "father time catches up" news for
# fighters declining 5+ attribute points in a single month. This is
# the "cliff" decline — the storyline-worthy collapse. Most monthly
# ticks generate no news at all.
DECLINE_NEWS_THRESHOLD = 5

# Attribute CHECK floor — the v2.0.0 columns have CHECK (0-100) so
# we floor at 0. (The 4 original columns — punch_power, cardio,
# fight_iq, chin — have no CHECK constraint retroactively, but we
# apply the same floor for consistency.)
ATTR_FLOOR = 0
ATTR_CEIL = 100  # upper bound — only used for growth ceiling calc

# Stage5-Final — personality field bounds for the monthly drift
# (fatigue_tolerance + travel_comfort). Matches the [10, 95] clamp
# used in morale.py for the same fields.
PERSONALITY_FLOOR = 10
PERSONALITY_CEIL = 95

# Age thresholds for the Stage5-Final personality drift.
#   fatigue_tolerance: -1/month after age 33 (body wears down —
#     fighters can't push through 5-round wars like they used to).
#   travel_comfort: +0.5/month for fighters UNDER 30 (young fighters
#     adapt to travel — first long flight is rough, the tenth is
#     routine). Stored as REAL for the 0.5 increments.
FATIGUE_TOLERANCE_DECLINE_AGE = 33
TRAVEL_COMFORT_GROWTH_AGE_MAX = 29  # under 30 → 0..29 inclusive


# ----------------------------------------------------------------
# Effective ceiling — replicates the formula in tick_processor.
# _check_training_camps (lines 615-664). Kept here to avoid a
# circular import (tick_processor imports from app; career_arc
# importing tick_processor would create an import cycle when
# career_arc is registered from app).
# ----------------------------------------------------------------

def _age_factor(age):
    """Age factor for effective ceiling (matches tick_processor)."""
    if age <= 27:
        return 1.0
    if age <= 30:
        return 0.95
    if age <= 33:
        return 0.80
    if age <= 36:
        return 0.60
    return 0.35


def _health_factor(career_health):
    """Health factor for effective ceiling (matches tick_processor)."""
    if career_health >= 90:
        return 1.0
    if career_health >= 70:
        return 0.90
    if career_health >= 50:
        return 0.70
    if career_health >= 30:
        return 0.40
    return 0.15


def _effective_ceiling(potential, age, career_health,
                       discipline, coachability):
    """Compute the effective ceiling (matches tick_processor formula).

    effective_ceiling = potential * age_factor * health_factor *
                        personality_factor

    Floors at 10 (matches tick_processor).
    """
    personality_factor = (discipline + coachability) / 200.0
    ceiling = int(potential * _age_factor(age)
                  * _health_factor(career_health)
                  * personality_factor)
    return max(10, ceiling)


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _is_monthly_tick(conn):
    """Return True if the current sim day is a monthly tick boundary.

    We use current_day % 30 == 0 (day 30, 60, 90, ...) — roughly
    monthly. The sim advances 1 day per tick, so this fires ~12 times
    per sim year. Heavy enough for organic-feeling change, light
    enough to keep the processor idle on most ticks.
    """
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not row or row[0] is None:
        return False
    return (row[0] % 30) == 0


def _compute_age(dob_str, current_date_str):
    """Compute a fighter's age as of current_date.

    Args:
        dob_str: ISO date 'YYYY-MM-DD' (fighters.date_of_birth).
        current_date_str: ISO date 'YYYY-MM-DD' (sim current_date).

    Returns:
        int age, or None if dob is missing/invalid.
    """
    if not dob_str or not current_date_str:
        return None
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d")
        cur = datetime.strptime(current_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    age = cur.year - dob.year
    # Adjust if the birthday hasn't happened yet this year.
    if (cur.month, cur.day) < (dob.month, dob.day):
        age -= 1
    return age


def _fighter_name(conn, fighter_id):
    """Return 'First Last' for a fighter, or 'Fighter N' fallback."""
    row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else f"Fighter {fighter_id}"


def _get_news_source_id(conn):
    """Return the System Feed news_source_id (creating it if missing).

    Mirrors the pattern in app.sign_free_agent + agent_offers — the
    'System Feed' is the canonical source for non-promotion-specific
    system news.
    """
    row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO news_sources (name, credibility, sensationalism, "
        "bias, regional_reach, reliability, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("System Feed", 70, 40, 50, 60, 80, 80),
    ).lastrowid


def _refresh_snapshot(conn, fighter_id):
    """Refresh the fighter's descriptor snapshot (lazy-import to avoid
    circular dependency with app.py)."""
    try:
        from app import update_fighter_descriptor_snapshot
        update_fighter_descriptor_snapshot(conn, fighter_id)
    except ImportError:
        pass  # defensive — app.py not available (headless test?)


def _describe_career_stage_for_news(conn, fighter_id, age):
    """Build a voice-driven career-stage descriptor for the news item.

    Uses voice.describe_career_stage (§14 — no raw numbers in news
    text). Loads the fighter's record + champion status so the
    descriptor reflects their actual career arc ('reigning champion'
    vs 'grizzled veteran' vs 'top prospect').
    """
    try:
        import voice
    except ImportError:
        return "veteran fighter"  # defensive fallback
    row = conn.execute(
        "SELECT fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.title_reigns, fc.win_streak, fc.loss_streak "
        "FROM fighter_career fc WHERE fc.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "veteran fighter"
    wins, losses, draws, reigns, ws, ls = row
    is_champion = conn.execute(
        "SELECT 1 FROM titles WHERE current_champion_fighter_id=?",
        (fighter_id,),
    ).fetchone() is not None
    rng = random.Random(fighter_id)
    stage = voice.describe_career_stage(
        age, wins or 0, losses or 0, draws or 0,
        is_champion=is_champion,
        title_reigns=reigns or 0,
        win_streak=ws or 0,
        loss_streak=ls or 0,
        rng=rng,
    )
    return stage


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber — natural career arc
# ----------------------------------------------------------------

def _process_career_arc(conn, event):
    """Subscriber for TICK_ADVANCED — natural growth + decline.

    Fires only on monthly ticks (current_day % 30 == 0). For each
    active fighter (is_active=1, is_retired=0):
      - Compute age as of current_date.
      - Growth band (18-27): roll per-attribute chance; on hit, +1
        capped at effective_ceiling.
      - Decline band (30+): roll per-attribute chance; on hit, -1
        (uncapped — goes below effective_ceiling, floored at 0).
      - Prime band (28-29): no change.
      - Refresh the descriptor snapshot.
      - If 5+ attribute points declined in a single month, write a
        "father time catches up" news item.
    """
    if not _is_monthly_tick(conn):
        return

    current_date = event.get('current_date')
    if not current_date:
        return

    rng = random.Random()

    # Fetch all active fighters + their attributes + career meta in
    # one query (avoids N+1 queries for 4000-fighter rosters).
    rows = conn.execute(
        "SELECT f.fighter_id, f.date_of_birth, "
        "fc.potential, fc.career_health, fc.title_reigns, "
        "fp.discipline, fp.coachability "
        "FROM fighters f "
        "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "JOIN fighter_personality fp ON fp.fighter_id=f.fighter_id "
        "WHERE f.is_active=1 AND f.is_retired=0"
    ).fetchall()

    for (fighter_id, dob, potential, career_health, title_reigns,
         discipline, coachability) in rows:
        age = _compute_age(dob, current_date)
        if age is None:
            continue  # missing DOB — can't compute age

        potential = potential if potential is not None else 50
        career_health = career_health if career_health is not None else 100
        discipline = discipline if discipline is not None else 50
        coachability = coachability if coachability is not None else 50

        # Compute the effective ceiling ONCE per fighter — used by
        # the growth phase only. Decline ignores the ceiling.
        ceiling = _effective_ceiling(
            potential, age, career_health, discipline, coachability,
        )

        total_decline = 0
        total_growth = 0

        # ---- GROWTH BAND (18-27) ----
        if GROWTH_AGE_MIN <= age <= GROWTH_AGE_MAX:
            for attr_name, prob in GROWTH_RULES:
                if rng.random() < prob:
                    cur_val = conn.execute(
                        f"SELECT {attr_name} FROM fighter_attributes "
                        "WHERE fighter_id=?",
                        (fighter_id,),
                    ).fetchone()
                    if not cur_val:
                        continue
                    cur = cur_val[0] if cur_val[0] is not None else 50
                    # Cap at effective_ceiling — natural maturation
                    # cannot exceed what the fighter's potential +
                    # age + health + personality allow.
                    new_val = min(ceiling, cur + 1)
                    if new_val > cur:
                        conn.execute(
                            f"UPDATE fighter_attributes SET {attr_name}=?, "
                            "updated_at=CURRENT_TIMESTAMP "
                            "WHERE fighter_id=?",
                            (new_val, fighter_id),
                        )
                        total_growth += (new_val - cur)

        # ---- DECLINE BAND (30+) ----
        elif age >= DECLINE_AGE_MIN:
            for attr_name, onset_age, prob in DECLINE_RULES:
                if age < onset_age:
                    continue
                if rng.random() < prob:
                    cur_val = conn.execute(
                        f"SELECT {attr_name} FROM fighter_attributes "
                        "WHERE fighter_id=?",
                        (fighter_id,),
                    ).fetchone()
                    if not cur_val:
                        continue
                    cur = cur_val[0] if cur_val[0] is not None else 50
                    # NOT capped at effective_ceiling — decline goes
                    # below it. Floored at 0 (the schema CHECK).
                    new_val = max(ATTR_FLOOR, cur - 1)
                    if new_val < cur:
                        conn.execute(
                            f"UPDATE fighter_attributes SET {attr_name}=?, "
                            "updated_at=CURRENT_TIMESTAMP "
                            "WHERE fighter_id=?",
                            (new_val, fighter_id),
                        )
                        total_decline += (cur - new_val)

        # ---- Stage5-Final — personality field monthly drift ----
        # fatigue_tolerance: -1/month after age 33 (body wears down).
        # travel_comfort: +0.5/month for fighters under 30 (young
        #   fighters adapt to travel). Stored as REAL.
        # All changes capped at [PERSONALITY_FLOOR=10, PERSONALITY_CEIL=95]
        # per the brief — tighter than the schema's 0-100 CHECK.
        pers_changed = False
        if age >= FATIGUE_TOLERANCE_DECLINE_AGE:
            row = conn.execute(
                "SELECT fatigue_tolerance FROM fighter_personality "
                "WHERE fighter_id=?",
                (fighter_id,),
            ).fetchone()
            if row:
                cur_ft = row[0] if row[0] is not None else 50
                new_ft = max(PERSONALITY_FLOOR, int(cur_ft) - 1)
                if new_ft != cur_ft:
                    conn.execute(
                        "UPDATE fighter_personality "
                        "SET fatigue_tolerance=? WHERE fighter_id=?",
                        (new_ft, fighter_id),
                    )
                    pers_changed = True
        if age <= TRAVEL_COMFORT_GROWTH_AGE_MAX:
            row = conn.execute(
                "SELECT travel_comfort FROM fighter_personality "
                "WHERE fighter_id=?",
                (fighter_id,),
            ).fetchone()
            if row:
                cur_tc = row[0] if row[0] is not None else 50
                # Preserve REAL type if the current value is REAL
                # (e.g., 50.5 + 0.5 = 51.0 — keep as float).
                base_tc = float(cur_tc) if not isinstance(cur_tc, float) else cur_tc
                new_tc = min(float(PERSONALITY_CEIL), base_tc + 0.5)
                if new_tc != cur_tc:
                    conn.execute(
                        "UPDATE fighter_personality "
                        "SET travel_comfort=? WHERE fighter_id=?",
                        (new_tc, fighter_id),
                    )
                    pers_changed = True

        # ---- Refresh the descriptor snapshot (one pass per fighter
        # that actually changed). Skip the refresh if no attributes
        # changed this month — saves work on the 80%+ of monthly
        # ticks where the RNG didn't fire for this fighter.
        if total_growth > 0 or total_decline > 0 or pers_changed:
            _refresh_snapshot(conn, fighter_id)

        # ---- NEWS: "father time catches up" for cliff declines ----
        # Only fires for fighters losing 5+ attribute points in a
        # single month — the storyline-worthy collapse. Most monthly
        # ticks generate no news at all (with ~4000 fighters, a
        # looser threshold would spam the feed).
        if total_decline >= DECLINE_NEWS_THRESHOLD:
            _write_decline_news(conn, fighter_id, age, current_date)


def _write_decline_news(conn, fighter_id, age, current_date):
    """Write a 'father time catches up' news item for a cliff decline.

    Uses voice.describe_career_stage for the career-stage descriptor
    (§14 — no raw numbers in news text). The player sees
    "Father time catches up with John Vale — the grizzled veteran
    shows signs of slowing down" — NOT "John Vale: cardio -2, chin
    -3, durability -1, age 35".

    The news item is written with topic='career_arc' so future UI
    filters can group career-arc news together. sentiment='negative'
    — a decline is bad news for the fighter (and the player if they
    own the fighter).
    """
    src_id = _get_news_source_id(conn)
    name = _fighter_name(conn, fighter_id)
    stage_desc = _describe_career_stage_for_news(conn, fighter_id, age)

    headline = f"Father time catches up with {name}"
    body = (f"{name} — the {stage_desc} — shows signs of slowing "
            f"down. The miles are starting to show, and the version "
            f"that built the reputation isn't the version in the gym "
            f"anymore.")

    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "negative", "career_arc",
         fighter_id, current_date),
    )


# ----------------------------------------------------------------
# Registration
# ----------------------------------------------------------------

def register_subscribers():
    """Register the career arc subscriber on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior registrations.

    Subscribes to:
      TICK_ADVANCED → _process_career_arc (monthly tick — current_day
                      % 30 == 0)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.TICK_ADVANCED, _process_career_arc,
        name="career_arc.process_career_arc",
    )
