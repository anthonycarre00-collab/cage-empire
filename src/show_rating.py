"""CAGE EMPIRE Show Rating Engine (Stage 5 — Task 26).

Computes per-event fan / commercial / excitement / quality / overall
ratings after each event completes. Entirely event-bus-driven per
CONVENTIONS §15.4 — no inline side effects added to resolve_next_fight.

SUBSCRIPTION:
  - EVENT_COMPLETED (published by app._update_event_status_after_
    resolution when an event transitions to 'completed'). This fires
    exactly once per event — no idempotency guard needed beyond the
    UNIQUE(event_id) constraint on the show_ratings table.

    The brief says "Subscribe to FIGHT_RESOLVED. When an event
    completes (all fights resolved), compute show ratings". The
    parenthetical clarifies the semantic intent — "when the event
    completes". EVENT_COMPLETED is the event bus event that fires
    exactly when an event completes (already published by app.py),
    so it's the natural choice. Subscribing to FIGHT_RESOLVED would
    require an "is this event already completed?" + "have we
    already rated this event?" guard on every fire — see finance.py
    for the pattern. EVENT_COMPLETED avoids the guard entirely.
    Documented as D1 in the worklog.

RATING AXES (each 0-100, CHECK BETWEEN 0 AND 100):

  fan_rating — how much fans enjoyed the show.
    Inputs: finishes (KO/sub) vs decisions, fight excitement (beats
    + damage), title fights, rivalry fights on the card.
    - More finishes = higher fan rating.
    - More exciting fights (high damage, knockdowns, near-finishes)
      = higher.
    - Title fights = +10 bonus.
    - Rivalry fights (heat > 50) = +5 bonus.

  commercial_rating — how well the show did commercially.
    Inputs: total fighter marketability on the card, broadcast tier,
    attendance (from finance ticket_sales).
    - Higher marketability fighters = higher commercial rating.
    - PPV broadcast = +20, streaming = +10, regional TV = +5.

  excitement_rating — how action-packed the show was.
    Inputs: avg beats per fight, avg damage per fight, number of
    knockdowns, number of near-finishes.
    - More action = higher excitement.

  quality_rating — how technically skilled the fights were.
    Inputs: avg fighter attributes (higher = better technique),
    fight_iq of participants, number of clean techniques landed.
    - Better fighters = higher quality.

  overall_rating — weighted average:
    fan 30% + commercial 20% + excitement 25% + quality 25%.

VOICE LAYER (CONVENTIONS §14): rating_description is a voice-layer
descriptor. NO raw rating numbers appear in any player-facing text.
The 5 rating axes are stored as raw ints in show_ratings (for the
future post-event summary panel), but the news item + the
rating_description column use descriptors only:
  - 90+: "an instant classic that fans will talk about for years"
  - 75-89: "a highly entertaining show that delivered on expectations"
  - 60-74: "a solid night of fights with some memorable moments"
  - 40-59: "a decent show that failed to produce many highlights"
  - <40:   "a lackluster card that left fans wanting more"

DESIGN LAW (CONVENTIONS §13):
  - Investment: the player's investment in matchmaking, building
    stars, and booking good cards is REWARDED — a great card
    produces "an instant classic". The dopamine loop closes.
  - Stories: every show gets a verdict. The player remembers the
    great cards ("the night Vale knocked out Reed for the title —
    an instant classic") and the duds ("a lackluster card that
    left fans wanting more"). The show ratings ARE the storyline
    of the promotion's history.
  - Anticipation: after a great card, the player wants the next
    one to be even better. After a dud, the player wants to
    rebound. The ratings create the "what's next?" thread.

USAGE:
  from show_rating import register_subscribers
  register_subscribers()  # call once at startup (UI App.__init__,
                          # test setup). Safe to call multiple times.
  # The show rating system processes events automatically via the bus.
  # No need to call any function directly.
"""

import sqlite3


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# Broadcast tier bonuses for commercial_rating (per the brief).
_BROADCAST_BONUS = {
    "ppv_global":    20,
    "streaming":     10,
    "tv_regional":   5,
    "local_stream":  0,
}

# Title fight bonus for fan_rating (per the brief).
_TITLE_FIGHT_BONUS = 10
_TITLE_FIGHT_BONUS_CAP = 20  # 2+ title fights → cap at +20

# Rivalry fight bonus for fan_rating (per the brief).
_RIVALRY_FIGHT_BONUS = 5
_RIVALRY_FIGHT_BONUS_CAP = 15  # 3+ rivalry fights → cap at +15

# Rivalry heat threshold (per the brief — "heat > 50").
_RIVALRY_HEAT_THRESHOLD = 50


# ----------------------------------------------------------------
# Rating description (voice layer — CONVENTIONS §14)
# ----------------------------------------------------------------

# Banded descriptors for the overall_rating. The bands are 5 tiers
# (90+, 75-89, 60-74, 40-59, <40). A rating of 90+ → "instant
# classic"; a rating of 50 → "decent show that failed to produce
# many highlights". The descriptors are short, evocative, and NEVER
# include the raw rating number per §14.
_RATING_DESCRIPTIONS = [
    (90,  "an instant classic that fans will talk about for years"),
    (75,  "a highly entertaining show that delivered on expectations"),
    (60,  "a solid night of fights with some memorable moments"),
    (40,  "a decent show that failed to produce many highlights"),
    (0,   "a lackluster card that left fans wanting more"),
]


def _describe_rating(overall):
    """Return the voice-layer descriptor for an overall rating.

    Args:
        overall: 0-100 integer.

    Returns:
        A descriptor string (no raw numbers per CONVENTIONS §14).
    """
    for threshold, desc in _RATING_DESCRIPTIONS:
        if overall >= threshold:
            return desc
    return _RATING_DESCRIPTIONS[-1][1]  # defensive


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _clamp(v, lo=0, hi=100):
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, int(v)))


def _get_event_fights(conn, event_id):
    """Return list of fight_id tuples for an event (resolved only).

    Returns a list of dicts with: fight_id, result_type, is_title_fight,
    fighter_a_id, fighter_b_id. Only fights with result_type IS NOT
    NULL (i.e. resolved) are included — unresolved fights shouldn't
    be on a 'completed' event, but defensive.
    """
    rows = conn.execute(
        "SELECT fight_id, result_type, is_title_fight, "
        "winner_fighter_id, loser_fighter_id "
        "FROM fights WHERE event_id=? AND result_type IS NOT NULL",
        (event_id,),
    ).fetchall()
    fights = []
    for fight_id, result_type, is_title_fight, winner_id, loser_id in rows:
        # Get the two participants
        p_rows = conn.execute(
            "SELECT fighter_id FROM fight_participants "
            "WHERE fight_id=? ORDER BY corner",
            (fight_id,),
        ).fetchall()
        fighter_a = p_rows[0][0] if len(p_rows) > 0 else None
        fighter_b = p_rows[1][0] if len(p_rows) > 1 else None
        fights.append({
            'fight_id': fight_id,
            'result_type': result_type,
            'is_title_fight': bool(is_title_fight),
            'winner_id': winner_id,
            'loser_id': loser_id,
            'fighter_a_id': fighter_a,
            'fighter_b_id': fighter_b,
        })
    return fights


def _count_finishes(fights):
    """Count fights ending in a finish (KO/TKO, submission, doctor
    stoppage, corner stoppage, or DQ — i.e. anything that's NOT a
    decision/draw/NC).

    Per the brief: "finishes (KO/sub) vs decisions". We interpret
    "finishes" broadly as "any non-decision result" — a doctor
    stoppage IS a finish in MMA parlance (the fight ended before
    the scheduled rounds, dramatically). The engine itself classifies
    'doctor_stoppage', 'corner_stoppage', 'dq' alongside 'ko_tko' and
    'submission' as finishes (app.py line 4874).
    """
    n = 0
    for f in fights:
        rt = (f.get('result_type') or '').lower()
        if rt in ('ko_tko', 'ko', 'tko', 'submission',
                  'doctor_stoppage', 'corner_stoppage', 'dq'):
            n += 1
    return n


def _count_title_fights(fights):
    """Count title fights on the card."""
    return sum(1 for f in fights if f.get('is_title_fight'))


def _count_rivalry_fights(conn, fights):
    """Count fights where the two participants have an active rivalry
    with heat > _RIVALRY_HEAT_THRESHOLD (per the brief).
    """
    n = 0
    for f in fights:
        a = f.get('fighter_a_id')
        b = f.get('fighter_b_id')
        if a is None or b is None:
            continue
        # Rivalries are stored with fighter_a_id < fighter_b_id by
        # convention (UNIQUE constraint). Check both orders just in
        # case.
        row = conn.execute(
            "SELECT rivalry_heat FROM rivalries "
            "WHERE is_active=1 AND "
            "((fighter_a_id=? AND fighter_b_id=?) OR "
            " (fighter_a_id=? AND fighter_b_id=?))",
            (a, b, b, a),
        ).fetchone()
        if row and row[0] is not None and row[0] > _RIVALRY_HEAT_THRESHOLD:
            n += 1
    return n


def _get_beats_stats(conn, fight_ids):
    """Return (total_beats, total_damage, total_knockdowns,
    total_near_finishes, total_landed) across the given fights.
    """
    if not fight_ids:
        return (0, 0, 0, 0, 0)
    placeholders = ",".join("?" * len(fight_ids))
    row = conn.execute(
        f"SELECT COUNT(*) AS beats, "
        f"COALESCE(SUM(damage_dealt), 0) AS damage, "
        f"SUM(CASE WHEN outcome='knockdown' THEN 1 ELSE 0 END) AS kd, "
        f"SUM(CASE WHEN outcome='near_finish' THEN 1 ELSE 0 END) AS nf, "
        f"SUM(CASE WHEN outcome='landed' THEN 1 ELSE 0 END) AS landed "
        f"FROM fight_beats WHERE fight_id IN ({placeholders})",
        fight_ids,
    ).fetchone()
    return (
        row[0] or 0,
        row[1] or 0,
        row[2] or 0,
        row[3] or 0,
        row[4] or 0,
    )


def _get_avg_fighter_attrs(conn, fights):
    """Return (avg_all_attrs, avg_fight_iq) across all fighters on
    the card. avg_all_attrs is the mean of all 25 attribute values
    for all fighters; avg_fight_iq is the mean of just fight_iq.

    Returns (50, 50) if no fighters found (defensive).
    """
    fighter_ids = set()
    for f in fights:
        if f.get('fighter_a_id') is not None:
            fighter_ids.add(f['fighter_a_id'])
        if f.get('fighter_b_id') is not None:
            fighter_ids.add(f['fighter_b_id'])
    if not fighter_ids:
        return (50, 50)
    ids = list(fighter_ids)
    placeholders = ",".join("?" * len(ids))
    # The 25 attribute columns. Listed explicitly (no dynamic SQL
    # construction from user input — these are hardcoded column names).
    attr_cols = [
        "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
        "head_movement", "footwork", "clinch_striking", "clinch_offense",
        "clinch_defense", "takedown_offense", "takedown_defense",
        "top_control", "bottom_game", "submission_offense",
        "submission_defense", "scramble_ability", "cage_wrestling",
        "cardio", "recovery_rate", "speed_explosiveness", "strength",
        "durability", "flexibility", "fight_iq", "chin", "adaptability",
    ]
    # SUM() takes a single argument — we build a per-row sum expression
    # (COALESCE(col,0) + COALESCE(col,0) + ...) and then SUM that.
    # COALESCE handles NULL attribute values (treats them as 0).
    row_sum_expr = " + ".join(f"COALESCE({c}, 0)" for c in attr_cols)
    row = conn.execute(
        f"SELECT COUNT(*) AS n, "
        f"COALESCE(SUM({row_sum_expr}), 0) AS total_sum, "
        f"COALESCE(SUM(COALESCE(fight_iq, 0)), 0) AS iq_sum "
        f"FROM fighter_attributes WHERE fighter_id IN ({placeholders})",
        ids,
    ).fetchone()
    n_fighters = row[0] or 0
    if n_fighters == 0:
        return (50, 50)
    total_sum = row[1] or 0
    iq_sum = row[2] or 0
    avg_all = total_sum / (n_fighters * 25)  # 25 attributes per fighter
    avg_iq = iq_sum / n_fighters
    return (avg_all, avg_iq)


def _get_total_marketability(conn, fights):
    """Return the sum of marketability for all fighters on the card."""
    fighter_ids = set()
    for f in fights:
        if f.get('fighter_a_id') is not None:
            fighter_ids.add(f['fighter_a_id'])
        if f.get('fighter_b_id') is not None:
            fighter_ids.add(f['fighter_b_id'])
    if not fighter_ids:
        return 0
    ids = list(fighter_ids)
    placeholders = ",".join("?" * len(ids))
    row = conn.execute(
        f"SELECT COALESCE(SUM(marketability), 0) FROM fighters "
        f"WHERE fighter_id IN ({placeholders})",
        ids,
    ).fetchone()
    return row[0] or 0


def _get_attendance(conn, event_id):
    """Return the ticket-sales attendance for an event.

    Two paths:
      1. If finance.py has already recorded a ticket_sales transaction
         for this event (it subscribes to FIGHT_RESOLVED), parse the
         description "N tickets × $price" for the exact attendance.
      2. If finance hasn't run yet (registration order, or finance
         isn't wired in — App.__init__ does NOT auto-register finance),
         compute the attendance on-the-fly using the same formula
         finance.py uses (venue_capacity × fill_rate, where fill_rate
         = market_heat / 100 clamped to [0.30, 0.98]).

    This makes show_rating self-contained — it doesn't depend on
    finance being registered first.
    """
    # Path 1: read from finance_transactions if available.
    row = conn.execute(
        "SELECT description FROM finance_transactions "
        "WHERE event_id=? AND transaction_type='ticket_sales'",
        (event_id,),
    ).fetchone()
    if row and row[0]:
        # Description format: "12345 tickets × $50"
        try:
            n_str = row[0].split(" tickets")[0].strip()
            return int(n_str)
        except (ValueError, IndexError):
            pass  # fall through to path 2

    # Path 2: compute on-the-fly using the finance formula.
    event_row = conn.execute(
        "SELECT v.capacity, m.heat_level "
        "FROM events e "
        "LEFT JOIN venues v ON v.venue_id=e.venue_id "
        "LEFT JOIN markets m ON m.market_id=e.market_id "
        "WHERE e.event_id=?",
        (event_id,),
    ).fetchone()
    if not event_row:
        return 0
    venue_cap, market_heat = event_row
    venue_cap = venue_cap or 5000
    market_heat = market_heat if market_heat is not None else 50
    fill_rate = max(0.30, min(0.98, market_heat / 100.0))
    return int(venue_cap * fill_rate)


# ----------------------------------------------------------------
# Rating computation (5 axes)
# ----------------------------------------------------------------

def _compute_fan_rating(conn, fights):
    """Compute fan_rating (0-100).

    Base 30. Bonuses:
      - finishes (KO/sub): +30 * (finishes / total_fights), max +30.
      - title fights: +10 per, cap +20.
      - rivalry fights (heat > 50): +5 per, cap +15.
      - excitement (avg beats per fight): +1 per beat, cap +15.
    """
    n = max(1, len(fights))
    base = 30
    # Finishes
    finishes = _count_finishes(fights)
    finish_bonus = int((finishes / n) * 30)  # 0-30
    # Title fights
    title_fights = _count_title_fights(fights)
    title_bonus = min(_TITLE_FIGHT_BONUS_CAP,
                      title_fights * _TITLE_FIGHT_BONUS)  # 0-20
    # Rivalry fights
    rivalry_fights = _count_rivalry_fights(conn, fights)
    rivalry_bonus = min(_RIVALRY_FIGHT_BONUS_CAP,
                        rivalry_fights * _RIVALRY_FIGHT_BONUS)  # 0-15
    # Excitement (avg beats per fight)
    fight_ids = [f['fight_id'] for f in fights]
    total_beats, _, _, _, _ = _get_beats_stats(conn, fight_ids)
    avg_beats = total_beats / n
    excitement_bonus = min(15, int(avg_beats))  # 0-15 (15+ avg beats = +15)
    return _clamp(base + finish_bonus + title_bonus + rivalry_bonus
                  + excitement_bonus)


def _compute_commercial_rating(conn, event_id, fights, broadcast_tier):
    """Compute commercial_rating (0-100).

    Base 30. Bonuses:
      - marketability: +1 per 7 marketability points (cap +30).
      - broadcast tier: ppv_global +20, streaming +10, tv_regional +5.
      - attendance: +1 per 1000 tickets (cap +20).
    """
    base = 30
    # Marketability
    total_mkt = _get_total_marketability(conn, fights)
    mkt_bonus = min(30, int(total_mkt / 7))  # 0-30
    # Broadcast tier
    broadcast_bonus = _BROADCAST_BONUS.get(broadcast_tier, 0)  # 0-20
    # Attendance
    attendance = _get_attendance(conn, event_id)
    attendance_bonus = min(20, int(attendance / 1000))  # 0-20
    return _clamp(base + mkt_bonus + broadcast_bonus + attendance_bonus)


def _compute_excitement_rating(conn, fights):
    """Compute excitement_rating (0-100).

    Base 25. Bonuses:
      - avg beats per fight: +1 per beat, cap +25.
      - avg damage per fight: +1 per 4 damage, cap +25.
      - knockdowns: +3 per, cap +15.
      - near-finishes: +2 per, cap +10.
    """
    n = max(1, len(fights))
    base = 25
    fight_ids = [f['fight_id'] for f in fights]
    total_beats, total_damage, total_kd, total_nf, _ = \
        _get_beats_stats(conn, fight_ids)
    avg_beats = total_beats / n
    avg_damage = total_damage / n
    beats_bonus = min(25, int(avg_beats))  # 0-25
    damage_bonus = min(25, int(avg_damage / 4))  # 0-25 (100+ dmg avg = +25)
    knockdowns_bonus = min(15, total_kd * 3)  # 0-15 (5+ KDs = +15)
    near_finishes_bonus = min(10, total_nf * 2)  # 0-10 (5+ NFs = +10)
    return _clamp(base + beats_bonus + damage_bonus + knockdowns_bonus
                  + near_finishes_bonus)


def _compute_quality_rating(conn, fights):
    """Compute quality_rating (0-100).

    Base 25. Bonuses:
      - avg all attributes (0-100): +0.4 per point, cap +40 (100+ = +40).
      - avg fight_iq (0-100): +0.2 per point, cap +20 (100+ = +20).
      - clean techniques landed: +1 per 5, cap +15 (75+ = +15).
    """
    n = max(1, len(fights))
    base = 25
    avg_all, avg_iq = _get_avg_fighter_attrs(conn, fights)
    attr_bonus = min(40, int(avg_all * 0.4))  # 0-40 (100 avg = +40)
    iq_bonus = min(20, int(avg_iq * 0.2))  # 0-20 (100 iq = +20)
    fight_ids = [f['fight_id'] for f in fights]
    _, _, _, _, total_landed = _get_beats_stats(conn, fight_ids)
    clean_bonus = min(15, int(total_landed / 5))  # 0-15 (75+ = +15)
    return _clamp(base + attr_bonus + iq_bonus + clean_bonus)


def _compute_overall_rating(fan, commercial, excitement, quality):
    """Compute overall_rating (weighted average per the brief):
    fan 30% + commercial 20% + excitement 25% + quality 25%.
    """
    return _clamp(
        fan * 0.30 + commercial * 0.20 + excitement * 0.25 + quality * 0.25
    )


# ----------------------------------------------------------------
# EVENT_COMPLETED subscriber
# ----------------------------------------------------------------

def _compute_show_ratings(conn, event):
    """Subscriber for EVENT_COMPLETED — compute show ratings.

    Computes all 5 rating axes + a voice-layer rating_description,
    writes a show_ratings row (UNIQUE event_id → idempotent), and
    writes a topic='show_rating' news item with the descriptor.
    """
    event_id = event.get('event_id')
    promo_id = event.get('promotion_id')
    if not event_id or not promo_id:
        return

    # Defensive idempotency: if a show_ratings row already exists
    # for this event_id (UNIQUE constraint), skip. EVENT_COMPLETED
    # fires exactly once per event transition, so this should never
    # fire — but the guard is here for robustness.
    existing = conn.execute(
        "SELECT 1 FROM show_ratings WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if existing:
        return

    # Get the event's broadcast tier (for commercial_rating).
    event_row = conn.execute(
        "SELECT e.event_date, p.broadcast_tier, p.name "
        "FROM events e "
        "JOIN promotions p ON p.promotion_id=e.promotion_id "
        "WHERE e.event_id=?",
        (event_id,),
    ).fetchone()
    if not event_row:
        return
    event_date, broadcast_tier, promo_name = event_row
    broadcast_tier = broadcast_tier or 'local_stream'

    # Get the event's resolved fights.
    fights = _get_event_fights(conn, event_id)
    if not fights:
        # No resolved fights — nothing to rate. Skip (defensive;
        # shouldn't happen on a 'completed' event, but if it does,
        # we don't write a meaningless 50/50/50/50/50 rating).
        return

    # Compute the 5 rating axes.
    fan = _compute_fan_rating(conn, fights)
    commercial = _compute_commercial_rating(
        conn, event_id, fights, broadcast_tier
    )
    excitement = _compute_excitement_rating(conn, fights)
    quality = _compute_quality_rating(conn, fights)
    overall = _compute_overall_rating(fan, commercial, excitement, quality)
    description = _describe_rating(overall)

    # Write the show_ratings row.
    conn.execute(
        "INSERT INTO show_ratings "
        "(event_id, promotion_id, fan_rating, commercial_rating, "
        "excitement_rating, quality_rating, overall_rating, "
        "rating_description) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, promo_id, fan, commercial, excitement, quality,
         overall, description),
    )

    # Write a topic='show_rating' news item with the voice descriptor.
    # NO raw numbers per CONVENTIONS §14. The headline + body use
    # the descriptor only. The body adds context (promotion name +
    # event name) but no rating numbers.
    _write_show_rating_news(
        conn, promo_id, event_id, event_date, promo_name, description
    )


def _write_show_rating_news(conn, promo_id, event_id, event_date,
                             promo_name, description):
    """Write a topic='show_rating' news item.

    The headline + body use the voice descriptor (no raw rating
    numbers per CONVENTIONS §14). The event_id + promotion_id are
    set so the news item can be filtered/joined to the event.
    """
    # Get the event name for context.
    event_row = conn.execute(
        "SELECT event_name FROM events WHERE event_id=?",
        (event_id,),
    ).fetchone()
    event_name = event_row[0] if event_row else f"Event {event_id}"

    # Sentiment based on the descriptor tier (positive / neutral /
    # negative). The descriptor itself doesn't reveal the tier to
    # the player, but the sentiment field is internal (used for
    # filtering / sorting in the news feed UI).
    if "instant classic" in description:
        sentiment = "positive"
    elif "highly entertaining" in description:
        sentiment = "positive"
    elif "solid night" in description:
        sentiment = "positive"
    elif "decent show" in description:
        sentiment = "neutral"
    else:  # "lackluster"
        sentiment = "negative"

    # Get or create the System Feed news source (matches finance.py
    # pattern — System Feed is the official inline-news source).
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, event_id, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (src_id,
         f"{promo_name}: {event_name} was {description}",
         f"The {promo_name} event '{event_name}' was {description}. "
         f"Fans are talking about the card — for better or worse.",
         sentiment, "show_rating", event_id, promo_id, event_date),
    )


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def register_subscribers():
    """Register the show rating system subscribers on the event bus.

    Call once at startup (after event_bus is available). Safe to
    call multiple times (each call appends a subscriber; if the bus
    is reset between calls, the subscriber count stays at 1).
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.EVENT_COMPLETED, _compute_show_ratings,
                  name="show_rating.compute_ratings")
