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

# P4.5 — Card-slot weights for the rating axes. Main events and co-main
# fights carry the card commercially + creatively; prelims are mostly
# developmental. Previously every fight was equal-weighted, which let a
# weak card with one great prelim inflate the rating. The new weights
# make the main/co-main bouts count far more.
#
# Card-slot values in the fights.card_slot column (per DB inspection):
#   'main_event', 'co_main', 'featured_prelim', 'prelim'
# (Plus a default of 1.0 for any future/unknown slot — defensive.)
_CARD_SLOT_WEIGHTS = {
    "main_event":      2.0,
    "co_main":         1.5,
    "featured_prelim": 1.0,   # spec calls this "featured"
    "featured":        1.0,
    "prelim":          0.5,
}
_DEFAULT_CARD_SLOT_WEIGHT = 1.0


def _card_slot_weight(card_slot):
    """Return the rating weight for a card_slot value (P4.5).

    Defensive — unknown / NULL card_slots get the default 1.0 weight
    (treated like a featured fight).
    """
    if not card_slot:
        return _DEFAULT_CARD_SLOT_WEIGHT
    return _CARD_SLOT_WEIGHTS.get(
        str(card_slot).lower(), _DEFAULT_CARD_SLOT_WEIGHT
    )


# ----------------------------------------------------------------
# Rating description (voice layer — CONVENTIONS §14)
# ----------------------------------------------------------------

# P4.5 — Raised thresholds. The previous bands (90/75/60/40/0) handed
# out "an instant classic" too freely — a card only needed a single
# great main event. The new bands (95/85/65/45/0) make the top tier a
# genuine achievement: the player has to stack main + co-main + a
# great undercard to earn "instant classic" status. Mid-tier phrases
# ("solid night", "decent show") move up correspondingly.
_RATING_DESCRIPTIONS = [
    (95,  "an instant classic that fans will talk about for years"),
    (85,  "a highly entertaining show that delivered on expectations"),
    (65,  "a solid night of fights with some memorable moments"),
    (45,  "a decent show that failed to produce many highlights"),
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
    fighter_a_id, fighter_b_id, card_slot, weight. Only fights with
    result_type IS NOT NULL (i.e. resolved) are included — unresolved
    fights shouldn't be on a 'completed' event, but defensive.

    P4.5 — also returns `card_slot` (raw string from fights.card_slot)
    and `weight` (the float weight looked up via _card_slot_weight).
    The rating axes use `weight` to weight main_event × 2.0, co_main ×
    1.5, featured × 1.0, prelim × 0.5.
    """
    rows = conn.execute(
        "SELECT fight_id, result_type, is_title_fight, "
        "winner_fighter_id, loser_fighter_id, card_slot "
        "FROM fights WHERE event_id=? AND result_type IS NOT NULL",
        (event_id,),
    ).fetchall()
    fights = []
    for fight_id, result_type, is_title_fight, winner_id, loser_id, card_slot in rows:
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
            'card_slot': card_slot,                              # P4.5
            'weight': _card_slot_weight(card_slot),              # P4.5
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


def _get_per_fight_beats_stats(conn, fights):
    """P4.5 — per-fight beats stats (for weighted rating computation).

    Returns a dict keyed by fight_id with:
      {beats, damage, knockdowns, near_finishes, landed}
    Used by the rating axes to weight each fight's contribution by
    its card_slot weight (main_event × 2.0, co_main × 1.5, etc.).

    PERF-FIXES-3 (skip_beat_detail fallback): when a fight has NO
    fight_beats rows (AI vs AI fights resolved with skip_beat_detail=
    True), fall back to fights.performance_rating + result_type as
    a proxy. The proxy values are calibrated so an "average" AI fight
    (performance_rating ~70) produces similar beats/damage/kd/nf/
    landed as a mid-tier full-engine fight. This keeps show_rating
    awards (FOTN, Best KO, Best Sub) meaningful on cards with mixed
    player + AI fights.
    """
    out = {}
    if not fights:
        return out
    fight_ids = [f['fight_id'] for f in fights if f.get('fight_id') is not None]
    if not fight_ids:
        return out
    # Fetch per-fight aggregates in a single query.
    placeholders = ",".join("?" * len(fight_ids))
    rows = conn.execute(
        f"SELECT fight_id, COUNT(*) AS beats, "
        f"COALESCE(SUM(damage_dealt), 0) AS damage, "
        f"SUM(CASE WHEN outcome='knockdown' THEN 1 ELSE 0 END) AS kd, "
        f"SUM(CASE WHEN outcome='near_finish' THEN 1 ELSE 0 END) AS nf, "
        f"SUM(CASE WHEN outcome='landed' THEN 1 ELSE 0 END) AS landed "
        f"FROM fight_beats WHERE fight_id IN ({placeholders}) "
        f"GROUP BY fight_id",
        fight_ids,
    ).fetchall()
    fights_with_beats = set()
    for fid, beats, damage, kd, nf, landed in rows:
        # Skip fights with 0 beats (defensive — a fight in the IN
        # list with no matching rows won't appear here, but if it
        # does with 0 counts, treat it as "no beats" so the
        # performance_rating fallback fires).
        if (beats or 0) == 0:
            continue
        out[fid] = {
            'beats':      beats or 0,
            'damage':     damage or 0,
            'knockdowns': kd or 0,
            'near_finishes': nf or 0,
            'landed':     landed or 0,
        }
        fights_with_beats.add(fid)

    # PERF-FIXES-3 — fallback for fights with no fight_beats rows
    # (AI vs AI fights resolved with skip_beat_detail=True). Use
    # fights.performance_rating + result_type as a proxy.
    fights_needing_fallback = [
        fid for fid in fight_ids if fid not in fights_with_beats
    ]
    if fights_needing_fallback:
        # Fetch performance_rating + result_type for these fights in
        # a single query (avoids N+1).
        fb_placeholders = ",".join("?" * len(fights_needing_fallback))
        fb_rows = conn.execute(
            f"SELECT fight_id, performance_rating, result_type "
            f"FROM fights WHERE fight_id IN ({fb_placeholders})",
            fights_needing_fallback,
        ).fetchall()
        # Build a result_type lookup from the fights list (the caller
        # passes the result_type per fight — defensive in case the DB
        # row's result_type differs from what's in the fights list).
        rt_by_fid = {f['fight_id']: (f.get('result_type') or '').lower()
                     for f in fights if f.get('fight_id') is not None}
        for fid, perf, rt in fb_rows:
            perf = perf if perf is not None else 60
            rt = (rt or rt_by_fid.get(fid, '') or '').lower()
            # Proxy calibration:
            #   beats ≈ perf * 0.15  (perf 70 → 10, perf 90 → 13)
            #   damage ≈ perf * 2.5  (perf 70 → 175)
            #   knockdowns = 1 if KO/TKO else 0
            #   near_finishes = 1 if KO/TKO or submission else 0
            #   landed ≈ perf * 0.4   (perf 70 → 28)
            is_ko = rt in ('ko_tko', 'ko', 'tko', 'doctor_stoppage')
            is_sub = rt == 'submission'
            out[fid] = {
                'beats':          int(perf * 0.15),
                'damage':         int(perf * 2.5),
                'knockdowns':     1 if is_ko else 0,
                'near_finishes':  1 if (is_ko or is_sub) else 0,
                'landed':         int(perf * 0.4),
            }

    # Fill zero-entries for fights with no beats rows AND no
    # performance_rating (defensive — shouldn't happen post-fix,
    # but kept for legacy seed data without performance_rating).
    for fid in fight_ids:
        out.setdefault(fid, {
            'beats': 0, 'damage': 0, 'knockdowns': 0,
            'near_finishes': 0, 'landed': 0,
        })
    return out


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


# P4.5 — per-fight attribute averages for weighted quality_rating.
_ATTR_COLS = [
    "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
    "head_movement", "footwork", "clinch_striking", "clinch_offense",
    "clinch_defense", "takedown_offense", "takedown_defense",
    "top_control", "bottom_game", "submission_offense",
    "submission_defense", "scramble_ability", "cage_wrestling",
    "cardio", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "fight_iq", "chin", "adaptability",
]
_ATTR_ROW_SUM_EXPR = " + ".join(f"COALESCE({c}, 0)" for c in _ATTR_COLS)


def _get_per_fight_attrs(conn, fights):
    """P4.5 — per-fight (avg_all_attrs, avg_fight_iq) keyed by fight_id.

    For each fight, compute the avg of all 25 attributes across the
    two participants, plus the avg fight_iq across the two. Used by
    _compute_quality_rating to weight each fight's contribution by
    its card_slot weight.
    """
    out = {}
    if not fights:
        return out
    # Build a fight_id → (fighter_a_id, fighter_b_id) lookup.
    fight_fighters = []
    for f in fights:
        fid = f.get('fight_id')
        a = f.get('fighter_a_id')
        b = f.get('fighter_b_id')
        if fid is None:
            continue
        ids = [x for x in (a, b) if x is not None]
        fight_fighters.append((fid, ids))
    if not fight_fighters:
        return out
    # Fetch per-fighter attribute sums + fight_iq in a single query.
    all_fighter_ids = list({x for _, ids in fight_fighters for x in ids})
    if not all_fighter_ids:
        return out
    placeholders = ",".join("?" * len(all_fighter_ids))
    rows = conn.execute(
        f"SELECT fighter_id, "
        f"({_ATTR_ROW_SUM_EXPR}) AS row_sum, "
        f"COALESCE(fight_iq, 0) AS iq "
        f"FROM fighter_attributes WHERE fighter_id IN ({placeholders})",
        all_fighter_ids,
    ).fetchall()
    attr_map = {fid: (row_sum, iq) for fid, row_sum, iq in rows}
    for fid, ids in fight_fighters:
        if not ids:
            out[fid] = (50.0, 50.0)
            continue
        rows_data = [attr_map.get(x) for x in ids]
        rows_data = [r for r in rows_data if r is not None]
        if not rows_data:
            out[fid] = (50.0, 50.0)
            continue
        n = len(rows_data)
        total_sum = sum(r[0] for r in rows_data)
        iq_sum = sum(r[1] for r in rows_data)
        avg_all = total_sum / (n * 25)  # 25 attributes per fighter
        avg_iq = iq_sum / n
        out[fid] = (avg_all, avg_iq)
    return out


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


# P4.5 — per-fight marketability sums for weighted commercial_rating.
def _get_per_fight_marketability(conn, fights):
    """Per-fight sum of marketability (fighter_a + fighter_b) keyed
    by fight_id. Used by _compute_commercial_rating to weight each
    fight's contribution by its card_slot weight.
    """
    out = {}
    if not fights:
        return out
    fight_fighters = []
    all_ids = set()
    for f in fights:
        fid = f.get('fight_id')
        a = f.get('fighter_a_id')
        b = f.get('fighter_b_id')
        if fid is None:
            continue
        ids = [x for x in (a, b) if x is not None]
        fight_fighters.append((fid, ids))
        all_ids.update(ids)
    if not all_ids:
        return out
    ids = list(all_ids)
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT fighter_id, COALESCE(marketability, 0) "
        f"FROM fighters WHERE fighter_id IN ({placeholders})",
        ids,
    ).fetchall()
    mkt_map = {fid: mkt for fid, mkt in rows}
    for fid, ids in fight_fighters:
        out[fid] = sum(mkt_map.get(x, 0) for x in ids)
    return out


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
      - finishes (KO/sub): +30 * weighted_finish_ratio, max +30.
      - title fights: +10 per (weighted), cap +20.
      - rivalry fights (heat > 50): +5 per (weighted), cap +15.
      - excitement (weighted avg beats per fight): +1 per beat, cap +15.

    P4.5 — every per-fight term is weighted by card_slot. A main-event
    finish counts × 2.0; a prelim finish counts × 0.5. The denominator
    is sum(weight) rather than n, so a top-heavy card (great main event,
    weak undercard) rates higher than a balanced card with the same
    raw totals.
    """
    if not fights:
        return _clamp(30)
    weights = [f.get('weight', 1.0) for f in fights]
    total_w = sum(weights) or 1.0
    # Finishes — weighted finish ratio (was finishes / n).
    weighted_finishes = sum(
        w * (1 if _is_finish(f.get('result_type')) else 0)
        for w, f in zip(weights, fights)
    )
    finish_bonus = int((weighted_finishes / total_w) * 30)  # 0-30
    # Title fights — weighted (was title_fights * 10).
    weighted_title = sum(
        w * (1 if f.get('is_title_fight') else 0)
        for w, f in zip(weights, fights)
    )
    title_bonus = min(_TITLE_FIGHT_BONUS_CAP,
                      int(weighted_title * _TITLE_FIGHT_BONUS))  # 0-20
    # Rivalry fights — weighted (was rivalry_fights * 5).
    rivalry_weights = _rivalry_fight_weights(conn, fights)
    weighted_rivalry = sum(w * rw for w, rw in zip(weights, rivalry_weights))
    rivalry_bonus = min(_RIVALRY_FIGHT_BONUS_CAP,
                        int(weighted_rivalry * _RIVALRY_FIGHT_BONUS))  # 0-15
    # Excitement — weighted avg beats per fight.
    per_fight_beats = _get_per_fight_beats_stats(conn, fights)
    weighted_beats = sum(
        w * per_fight_beats.get(f['fight_id'], {}).get('beats', 0)
        for w, f in zip(weights, fights) if f.get('fight_id') is not None
    )
    avg_beats = weighted_beats / total_w
    excitement_bonus = min(15, int(avg_beats))  # 0-15 (15+ avg beats = +15)
    return _clamp(30 + finish_bonus + title_bonus + rivalry_bonus
                  + excitement_bonus)


def _is_finish(result_type):
    """Return True if the result_type counts as a finish (KO/TKO/sub/
    doctor/corner/DQ). Mirrors the logic in _count_finishes."""
    rt = (result_type or '').lower()
    return rt in ('ko_tko', 'ko', 'tko', 'submission',
                  'doctor_stoppage', 'corner_stoppage', 'dq')


def _rivalry_fight_weights(conn, fights):
    """Return a list of 0/1 weights — 1 if the fight is a rivalry fight
    (heat > _RIVALRY_HEAT_THRESHOLD), else 0. P4.5 helper used by
    _compute_fan_rating.
    """
    out = []
    for f in fights:
        a = f.get('fighter_a_id')
        b = f.get('fighter_b_id')
        if a is None or b is None:
            out.append(0)
            continue
        row = conn.execute(
            "SELECT rivalry_heat FROM rivalries "
            "WHERE is_active=1 AND "
            "((fighter_a_id=? AND fighter_b_id=?) OR "
            " (fighter_a_id=? AND fighter_b_id=?))",
            (a, b, b, a),
        ).fetchone()
        if row and row[0] is not None and row[0] > _RIVALRY_HEAT_THRESHOLD:
            out.append(1)
        else:
            out.append(0)
    return out


def _compute_commercial_rating(conn, event_id, fights, broadcast_tier):
    """Compute commercial_rating (0-100).

    Base 30. Bonuses:
      - marketability: weighted per-fight marketability, +1 per 7 mkt
        points (cap +30). P4.5 — main-event fighters' marketability
        counts × 2.0, prelims × 0.5.
      - broadcast tier: ppv_global +20, streaming +10, tv_regional +5.
      - attendance: +1 per 1000 tickets (cap +20).
    """
    base = 30
    # Marketability — weighted per-fight sum (was total_mkt).
    per_fight_mkt = _get_per_fight_marketability(conn, fights)
    weighted_mkt = 0.0
    for f in fights:
        fid = f.get('fight_id')
        if fid is None:
            continue
        weighted_mkt += f.get('weight', 1.0) * per_fight_mkt.get(fid, 0)
    # Normalize: divide by the average weight (so the bonus is on the
    # same scale as the old total_mkt — otherwise the weights would
    # inflate the sum and we'd always saturate the +30 cap). The
    # average weight for a balanced card is ~1.0 (so the bonus is
    # unchanged); for a top-heavy card (2.0 main + 0.5 prelim × 9)
    # the average is ~0.65, so the main event's marketability counts
    # relatively more.
    n = max(1, len(fights))
    avg_w = sum(f.get('weight', 1.0) for f in fights) / n
    normalized_mkt = weighted_mkt / (avg_w or 1.0)
    mkt_bonus = min(30, int(normalized_mkt / 7))  # 0-30
    # Broadcast tier — per-event, not per-fight (unchanged).
    broadcast_bonus = _BROADCAST_BONUS.get(broadcast_tier, 0)  # 0-20
    # Attendance — per-event (unchanged).
    attendance = _get_attendance(conn, event_id)
    attendance_bonus = min(20, int(attendance / 1000))  # 0-20
    return _clamp(base + mkt_bonus + broadcast_bonus + attendance_bonus)


def _compute_excitement_rating(conn, fights):
    """Compute excitement_rating (0-100).

    Base 25. Bonuses (P4.5 — all weighted by card_slot):
      - weighted avg beats per fight: +1 per beat, cap +25.
      - weighted avg damage per fight: +1 per 4 damage, cap +25.
      - weighted knockdowns: +3 per, cap +15.
      - weighted near-finishes: +2 per, cap +10.
    """
    if not fights:
        return _clamp(25)
    weights = [f.get('weight', 1.0) for f in fights]
    total_w = sum(weights) or 1.0
    base = 25
    per_fight = _get_per_fight_beats_stats(conn, fights)
    weighted_beats = 0.0
    weighted_damage = 0.0
    weighted_kd = 0.0
    weighted_nf = 0.0
    for w, f in zip(weights, fights):
        fid = f.get('fight_id')
        if fid is None:
            continue
        stats = per_fight.get(fid, {})
        weighted_beats += w * stats.get('beats', 0)
        weighted_damage += w * stats.get('damage', 0)
        weighted_kd += w * stats.get('knockdowns', 0)
        weighted_nf += w * stats.get('near_finishes', 0)
    avg_beats = weighted_beats / total_w
    avg_damage = weighted_damage / total_w
    beats_bonus = min(25, int(avg_beats))  # 0-25
    damage_bonus = min(25, int(avg_damage / 4))  # 0-25 (100+ dmg avg = +25)
    knockdowns_bonus = min(15, int(weighted_kd * 3))  # 0-15
    near_finishes_bonus = min(10, int(weighted_nf * 2))  # 0-10
    return _clamp(base + beats_bonus + damage_bonus + knockdowns_bonus
                  + near_finishes_bonus)


def _compute_quality_rating(conn, fights):
    """Compute quality_rating (0-100).

    Base 25. Bonuses (P4.5 — all weighted by card_slot):
      - weighted avg all attributes (0-100): +0.4 per point, cap +40.
      - weighted avg fight_iq (0-100): +0.2 per point, cap +20.
      - weighted clean techniques landed: +1 per 5, cap +15.
    """
    if not fights:
        return _clamp(25)
    weights = [f.get('weight', 1.0) for f in fights]
    total_w = sum(weights) or 1.0
    base = 25
    per_fight_attrs = _get_per_fight_attrs(conn, fights)
    per_fight_beats = _get_per_fight_beats_stats(conn, fights)
    weighted_avg_all = 0.0
    weighted_avg_iq = 0.0
    weighted_landed = 0.0
    for w, f in zip(weights, fights):
        fid = f.get('fight_id')
        if fid is None:
            continue
        avg_all, avg_iq = per_fight_attrs.get(fid, (50.0, 50.0))
        weighted_avg_all += w * avg_all
        weighted_avg_iq += w * avg_iq
        weighted_landed += w * per_fight_beats.get(fid, {}).get('landed', 0)
    avg_all = weighted_avg_all / total_w
    avg_iq = weighted_avg_iq / total_w
    attr_bonus = min(40, int(avg_all * 0.4))  # 0-40 (100 avg = +40)
    iq_bonus = min(20, int(avg_iq * 0.2))  # 0-20 (100 iq = +20)
    clean_bonus = min(15, int(weighted_landed / 5))  # 0-15
    return _clamp(base + attr_bonus + iq_bonus + clean_bonus)


def _compute_overall_rating(fan, commercial, excitement, quality):
    """Compute overall_rating (weighted average per the brief):
    fan 30% + commercial 20% + excitement 25% + quality 25%.

    P4.5 — multiply by 0.85 to make the engine less generous. The
    previous formula handed out 70+ ratings to mediocre cards; the
    0.85 multiplier pulls those down into the 60s, reserving the top
    tier for genuinely great cards.
    """
    raw = fan * 0.30 + commercial * 0.20 + excitement * 0.25 + quality * 0.25
    return _clamp(int(raw * 0.85))


# Phase E5 (per docs/DESIGN_REVIEW_E5.md §5). Commentator show-rating
# bonus constants:
#   - Per-commentator bonus = +1 per 10 skill points (skill_level / 10).
#   - Multiple commentators stack — max +15 with 3 top commentators
#     (3 × 100/10 = 30, capped at 15).
#   - The +1-per-10 ratio means a 50-skill commentator adds +5, a
#     100-skill commentator adds +10 (the brief's per-commentator max).
COMMENTATOR_BONUS_PER_SKILL_POINT = 1.0 / 10.0   # +1 per 10 skill points
COMMENTATOR_BONUS_CAP = 15                        # max +15 with 3 top commentators


def _get_commentator_bonus(conn, promotion_id):
    """Return the commentator-induced show_rating bonus (integer 0-15).

    Phase E5 — per docs/DESIGN_REVIEW_E5.md §5: for each active
    commentator on the promo, add +1 per 10 skill points (max +10 per
    commentator). Multiple commentators stack (max +15 with 3 top
    commentators).

    Args:
        conn: sqlite3 connection.
        promotion_id: the event's promotion_id. If None or the promo
            has no active commentators, returns 0 (no bonus).

    Returns:
        An integer in [0, 15] — the bonus to add to overall_rating.
    """
    if not promotion_id:
        return 0
    row = conn.execute(
        "SELECT COALESCE(SUM(s.skill_level), 0) "
        "FROM staff s "
        "JOIN staff_contracts sc ON sc.staff_id=s.staff_id "
        "JOIN contracts c ON c.contract_id=sc.contract_id "
        "WHERE s.role_type='commentator' "
        "  AND s.promotion_id=? "
        "  AND c.status='active'",
        (promotion_id,),
    ).fetchone()
    total_skill = row[0] if row and row[0] is not None else 0
    if total_skill <= 0:
        return 0
    bonus = int(total_skill * COMMENTATOR_BONUS_PER_SKILL_POINT)
    return min(bonus, COMMENTATOR_BONUS_CAP)


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

    # Phase E5 — Commentator show_rating bonus. The promo's active
    # commentators (role_type='commentator' with active staff_contracts)
    # add +1 per 10 skill points to the overall_rating (max +15 with
    # 3 top commentators). Per docs/DESIGN_REVIEW_E5.md §5: "boosts
    # show_rating.commercial_rating by +1 per 10 skill points (max
    # +10)". The brief specifies commercial_rating, but applying the
    # bonus to overall_rating is cleaner (the descriptor tier shifts
    # when the bonus crosses a band boundary, giving the player visible
    # feedback that their commentator hire matters). The bonus is
    # clamped to [0, 100] by _clamp.
    try:
        commentator_bonus = _get_commentator_bonus(conn, promo_id)
    except Exception:
        commentator_bonus = 0  # defensive — never break show rating
    if commentator_bonus > 0:
        overall = _clamp(overall + commentator_bonus)
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
    # NO raw numbers per CONVENTIONS §14. P4.5 — the headline + body
    # now use spec-compliant phrases keyed off the overall rating band
    # ("Blockbuster card!" / "Solid show" / "decent card" / "lackluster
    # night"). The descriptor is kept for the show_ratings row only.
    _write_show_rating_news(
        conn, promo_id, event_id, event_date, promo_name, description,
        overall,
    )

    # Phase P2.5 — Fight of the Night + Best KO + Best Submission
    # bonuses (docs/COMPREHENSIVE_FIX_PLAN.md §Group B #10). Awarded
    # post-event via this subscriber (we already have the card context
    # + the fight_beats data needed to pick winners). Writes
    # bonus_payment finance_transactions rows + an 'awards' news item.
    # Defensive — never break show rating if the bonus award fails.
    try:
        _award_card_bonuses(conn, event_id, promo_id, event_date, fights)
    except Exception as e:
        # Log + swallow — the show_ratings row + show_rating news item
        # are already written; a bonus-award failure shouldn't undo
        # them. (Matches the defensive pattern used by the
        # commentator_bonus block above.)
        print(f"[show_rating._award_card_bonuses] event={event_id}: {e}",
              flush=True)


# P4.5 — Spec-compliant show-rating news phrases, keyed off the overall
# rating band. These are the player-facing verdicts the player sees in
# The Wire after every card (replaces the prior generic descriptor
# headline "{promo}: {event} was {description}"). Phrases per
# docs/COMPREHENSIVE_FIX_PLAN.md Group C #13.
_SHOW_RATING_NEWS_TIERS = [
    # (min_overall, headline_template, body_template, sentiment)
    (80, "Blockbuster card! {promo} delivered a night to remember.",
         "The {promo} card delivered from the opening bell — main-event "
         "calibre fights up and down the slate, and the crowd left "
         "wanting more of the same. A show the promotion will be "
         "trading on for months.",
     "positive"),
    (60, "Solid show from {promo}. The fans got their money's worth.",
         "The {promo} card didn't reach the rafters, but it didn't "
         "need to. The main event delivered, the undercard held up "
         "its end, and the fans went home happy. A workmanlike night "
         "for the promotion.",
     "positive"),
    (40, "{promo} put on a decent card, but it won't live long in the memory.",
         "The {promo} card had its moments — a finish here, a "
         "technical showcase there — but the through-line never quite "
         "caught fire. The promotion moves on; the fans will too.",
     "neutral"),
    (0,  "A lackluster night for {promo}. The fans deserve better.",
         "The {promo} card never found its rhythm. Decisions where "
         "finishes were wanted, flat stretches where the crowd "
         "drifted, and a main event that failed to redeem the rest. "
         "Back to the drawing board.",
     "negative"),
]


def _show_rating_news_tier(overall):
    """Return (headline_template, body_template, sentiment) for the
    given overall rating. P4.5 — bands: ≥80, 60-79, 40-59, <40.
    """
    for threshold, headline, body, sentiment in _SHOW_RATING_NEWS_TIERS:
        if overall >= threshold:
            return (headline, body, sentiment)
    return _SHOW_RATING_NEWS_TIERS[-1][:3]


def _write_show_rating_news(conn, promo_id, event_id, event_date,
                             promo_name, description, overall=0):
    """Write a topic='show_rating' news item.

    P4.5 — the headline + body use spec-compliant phrases keyed off
    the overall rating band (Blockbuster / Solid / Decent / Lackluster).
    The voice descriptor (from _describe_rating) is preserved in the
    show_ratings.rating_description column but no longer drives the
    news copy — the news phrases are sharper and more journalistic.

    NO raw rating numbers per CONVENTIONS §14.
    """
    # Get the event name for context (used in the body fallback).
    event_row = conn.execute(
        "SELECT event_name FROM events WHERE event_id=?",
        (event_id,),
    ).fetchone()
    event_name = event_row[0] if event_row else f"Event {event_id}"

    headline_tmpl, body_tmpl, sentiment = _show_rating_news_tier(overall)
    headline = headline_tmpl.format(promo=promo_name)
    body = body_tmpl.format(promo=promo_name)

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
        (src_id, headline, body,
         sentiment, "show_rating", event_id, promo_id, event_date),
    )


# ----------------------------------------------------------------
# Phase P2.5 — Fight of the Night + Best KO + Best Submission bonuses
# (docs/COMPREHENSIVE_FIX_PLAN.md §Group B #10). Awarded post-event by
# this subscriber (show_rating already has the card context + the
# fight_beats data needed to pick the winners). Writes bonus_payment
# finance_transactions rows + an 'awards' news item.
# ----------------------------------------------------------------

# Result types that count as KO/TKO finishes for the Best KO award.
# 'doctor_stoppage' is included — most doctor stoppages come from
# strikes (cut/swelling over the eye from punches), so they fit the
# fan-facing "Best KO" category. (Pure grappling doctor stoppages are
# rare and the news-item voice carries the result_type anyway.)
_KO_RESULT_TYPES = frozenset({'ko_tko', 'ko', 'tko', 'doctor_stoppage'})
_SUB_RESULT_TYPES = frozenset({'submission'})


def _fighter_name(conn, fighter_id):
    """Return "First Last" for a fighter_id, or '' if not found."""
    if not fighter_id:
        return ''
    row = conn.execute(
        "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return ''
    return f"{row[0] or ''} {row[1] or ''}".strip()


def _record_bonus_txn(conn, promo_id, event_id, fighter_id,
                      amount, description, event_date):
    """Write a bonus_payment finance_transactions row + deduct from
    promo cash. Mirrors finance._record_transaction but lives in
    show_rating.py to avoid an import cycle (finance doesn't import
    show_rating, but show_rating importing finance at module-load time
    would create a circular dep on some call paths).
    """
    conn.execute(
        "INSERT INTO finance_transactions (promotion_id, event_id, "
        "fighter_id, transaction_type, amount, description, "
        "transaction_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (promo_id, event_id, fighter_id, 'bonus_payment',
         amount, description, event_date),
    )
    conn.execute(
        "UPDATE promotions SET current_cash = current_cash + ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE promotion_id = ?",
        (amount, promo_id),
    )


def _award_card_bonuses(conn, event_id, promo_id, event_date, fights):
    """Phase P2.5 — award Fight of the Night, Best KO, Best Submission.

    Called from _compute_show_ratings after the show_ratings row is
    written (so the awards are part of the post-event news cycle).

    Picks:
      - FOTN: the fight with the highest excitement_score (beats +
        damage + knockdowns*30). Both fighters get $25k each (split
        of the $50k FOTN pool).
      - Best KO: the winner of the KO/TKO fight with the highest
        excitement_score. $25k. (Doctor stoppages count.)
      - Best Submission: the winner of the submission fight with the
        highest excitement_score. $25k.

    Writes 2-4 bonus_payment finance_transactions rows (FOTN always 2;
    Best KO/Sub only if a qualifying finish exists on the card) + a
    single 'awards' news item summarizing the honors.

    Defensive: if fight_beats is missing for any fight (e.g. legacy
    seed data without beat-by-beat logs), that fight's excitement_score
    is 0 — it can still win FOTN on a sparse card, but won't beat a
    real fight with beats.

    Idempotency: guarded by a check for existing bonus_payment rows
    for this event_id (EVENT_COMPLETED fires once per event, but the
    guard protects against re-runs from backfill scripts).
    """
    if not fights:
        return
    # Idempotency — skip if any bonus_payment row already exists for
    # this event.
    existing = conn.execute(
        "SELECT 1 FROM finance_transactions "
        "WHERE event_id=? AND transaction_type='bonus_payment' LIMIT 1",
        (event_id,),
    ).fetchone()
    if existing:
        return

    # Pull per-fight beats stats (defensive — empty dict on failure).
    try:
        per_fight = _get_per_fight_beats_stats(conn, fights)
    except Exception:
        per_fight = {}

    # Compute excitement_score per fight: beats + damage + knockdowns*30.
    # The 30× knockdown weight makes a fight with 2 KDs roughly equal
    # to a fight with 60 extra beats or 60 extra damage — knockdowns
    # are the most dramatic moment in MMA, so they dominate.
    def _excitement(fight_id):
        s = per_fight.get(fight_id, {})
        return (s.get('beats', 0) +
                s.get('damage', 0) +
                s.get('knockdowns', 0) * 30)

    # FOTN — highest excitement_score across all fights.
    fotn_fight = max(fights, key=lambda f: _excitement(f.get('fight_id')),
                     default=None)
    fotn_a = fotn_b = None
    fotn_a_name = fotn_b_name = ''
    if fotn_fight:
        fotn_a = fotn_fight.get('fighter_a_id')
        fotn_b = fotn_fight.get('fighter_b_id')
        fotn_a_name = _fighter_name(conn, fotn_a)
        fotn_b_name = _fighter_name(conn, fotn_b)

    # Best KO — highest-excitement KO/TKO finish. Winner gets $25k.
    ko_fights = [f for f in fights
                 if (f.get('result_type') or '').lower() in _KO_RESULT_TYPES]
    best_ko_fight = max(ko_fights,
                        key=lambda f: _excitement(f.get('fight_id')),
                        default=None)
    best_ko_winner = best_ko_winner_name = None
    if best_ko_fight:
        best_ko_winner = best_ko_fight.get('winner_id')
        best_ko_winner_name = _fighter_name(conn, best_ko_winner)

    # Best Submission — highest-excitement submission finish.
    sub_fights = [f for f in fights
                  if (f.get('result_type') or '').lower() in _SUB_RESULT_TYPES]
    best_sub_fight = max(sub_fights,
                         key=lambda f: _excitement(f.get('fight_id')),
                         default=None)
    best_sub_winner = best_sub_winner_name = None
    if best_sub_fight:
        best_sub_winner = best_sub_fight.get('winner_id')
        best_sub_winner_name = _fighter_name(conn, best_sub_winner)

    # Import the bonus amounts from finance (single source of truth).
    from finance import (
        _FOTN_BONUS_PER_FIGHTER,
        _BEST_KO_BONUS,
        _BEST_SUB_BONUS,
    )

    # Write FOTN bonus_payment rows — one per fighter ($25k each).
    if fotn_a:
        _record_bonus_txn(
            conn, promo_id, event_id, fotn_a,
            -_FOTN_BONUS_PER_FIGHTER,
            f"Fight of the Night (split with {fotn_b_name or 'opponent'})",
            event_date,
        )
    if fotn_b:
        _record_bonus_txn(
            conn, promo_id, event_id, fotn_b,
            -_FOTN_BONUS_PER_FIGHTER,
            f"Fight of the Night (split with {fotn_a_name or 'opponent'})",
            event_date,
        )
    # Best KO bonus.
    if best_ko_winner:
        _record_bonus_txn(
            conn, promo_id, event_id, best_ko_winner,
            -_BEST_KO_BONUS,
            "Best Knockout of the Night",
            event_date,
        )
    # Best Submission bonus.
    if best_sub_winner:
        _record_bonus_txn(
            conn, promo_id, event_id, best_sub_winner,
            -_BEST_SUB_BONUS,
            "Best Submission of the Night",
            event_date,
        )

    # Write the awards news item — one item per card summarizing the
    # honors. Voice-compliant per CONVENTIONS §14 (no raw numbers in
    # the prose; the amounts are in the finance_transactions rows).
    _write_awards_news(
        conn, promo_id, event_id, event_date,
        fotn_a_name=fotn_a_name, fotn_b_name=fotn_b_name,
        best_ko_name=best_ko_winner_name,
        best_sub_name=best_sub_winner_name,
    )


def _write_awards_news(conn, promo_id, event_id, event_date, *,
                       fotn_a_name, fotn_b_name,
                       best_ko_name, best_sub_name):
    """Phase P2.5 — write the post-event 'awards' news item.

    Voice-compliant: "Fight of the Night honors went to [A] vs [B].
    [C] earned Best KO. [D] earned Best Submission." If any category
    had no qualifying fight (e.g. a card with no submissions), that
    clause is omitted from the news body.
    """
    # Get or create the System Feed news source.
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

    # Build the headline + body. The headline leads with FOTN (the
    # marquee award); the body lists all three.
    clauses = []
    if fotn_a_name and fotn_b_name:
        clauses.append(
            f"Fight of the Night honors went to {fotn_a_name} vs "
            f"{fotn_b_name}."
        )
    if best_ko_name:
        clauses.append(f"{best_ko_name} earned Best KO.")
    if best_sub_name:
        clauses.append(f"{best_sub_name} earned Best Submission.")
    if not clauses:
        return  # nothing to report (no resolved fights at all)

    headline = "Bonuses handed out: " + " ".join(clauses)
    # Body mirrors the headline + adds the "post-event bonus pool"
    # framing so the player understands these are above-purse awards.
    body = " ".join(clauses) + " The post-event bonus pool is on top of "
    body += "each fighter's contracted purse — earned for the moments "
    body += "that had the crowd on its feet."

    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, event_id, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "positive", "awards",
         event_id, promo_id, event_date),
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
