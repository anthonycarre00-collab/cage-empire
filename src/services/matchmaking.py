"""CAGE EMPIRE matchmaking service (Stage 6 — Task 6.0).

Extracted from src/app.py. Contains all event scheduling + card building
+ training-camp orchestration. Functions kept verbatim (no behaviour,
name, or signature changes).

Public API (called by App + tests):
- schedule_next_event(conn, promotion_id, from_event_date=None, weeks_out=4)
- _pick_matchup(conn, promotion_id, weight_class_id, exclude_fighter_ids=())

Card-build helpers:
- _get_available_fighters_for_card, _group_available_by_wc,
  _build_main_event, _build_co_main, _build_featured_prelim, _build_prelim

Camp helpers (called by tick_processor + App):
- _create_training_camp, _get_camp_fatigue_for_event,
  _pick_camp_focus_for_archetype
- Constants: _ARCHETYPE_NAME_TO_CAMP_FOCUS, _CAMP_FOCUS_ATTRS,
  _CAMP_LEAD_DAYS

Event-naming helpers:
- _get_event_naming_style, _build_event_name
- Constants: EVENT_NAME_THEMES, EVENT_THEMES,
  _CARD_SIZE_BY_TIER, _FEATURED_PRELIM_COUNT_BY_TIER,
  _REST_PERIOD_DAYS, _TITLE_FIGHT_ROUNDS, _NON_TITLE_FIGHT_ROUNDS

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it reads/writes the existing `events`, `fights`,
        `event_cards`, `training_camps`, `fighters` tables only.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass
        after extraction.
  §13 — Design Law: pillar Kingmaker ("I create stars" — matchmaking
        is the machinery of star-creation).
  §14 — Voice Layer: N/A — no player-facing text (event names use
        literal theme strings, not voice descriptors; future
        enhancement).
  §15 — Event Bus: schedule_next_event creates events + fights; the
        FIGHT_RESOLVED + EVENT_COMPLETED events are published by
        resolve_next_fight + _update_event_status_after_resolution
        (in services/fight_engine.py), NOT by this module.

Migration impact: NONE (code-only refactor).
"""
import sqlite3
import json
import random
from datetime import datetime, timedelta

from services.clock import fighter_name


def _pick_matchup(conn, promotion_id, weight_class_id, exclude_fighter_ids=()):
    """Pick 2 distinct active fighters from a promotion's roster.

    Args:
        conn: sqlite3 connection (read-only — no writes here).
        promotion_id: the promotion whose roster to draw from.
        weight_class_id: the weight class the fight is at.
        exclude_fighter_ids: iterable of fighter_ids to skip (e.g.,
            fighters who just fought on the just-completed event, to
            avoid immediate rematches). Empty by default.

    Returns:
        (fighter_a_id, fighter_b_id) tuple on success, or None if
        fewer than 2 eligible fighters are available.

    For now: pure random selection (random.sample, distinct). Task
    ID 10 will add ranking-proximity matchmaking; Task ID 22 will
    add rivalry logic. The signature already accepts
    exclude_fighter_ids so those future enhancements can pass a
    fighter set without changing the call sites.

    v2.4.0 (Task 15): also excludes fighters with active injuries
    (`is_active = 1` in the injuries table). An injured fighter
    cannot be booked — the medical staff hasn't cleared them to
    return. This is the reader required by CONVENTIONS §5.3 (every
    new table must ship with at least one reader).

    Phase 1.5 Fix B4 (gender check): also filters by gender. The
    weight_class_id is already gender-specific (each WC has a
    `gender` column = 'male' or 'female' in the weight_classes
    table), so this filter is REDUNDANT — but the brief asks for
    it as a defensive measure: an explicit `f.gender = ?` clause
    makes it impossible for a mixed-gender fight to be booked even
    if a future bug puts a fighter in the wrong WC. The gender is
    looked up from the weight_classes table by weight_class_id.
    """
    # Phase 1.5 Fix B4: explicit gender check — no mixed-gender fights
    # can be booked. Look up the WC's gender and filter fighters by it.
    wc_row = conn.execute(
        "SELECT gender FROM weight_classes WHERE weight_class_id = ?",
        (weight_class_id,),
    ).fetchone()
    wc_gender = wc_row[0] if wc_row else 'male'  # defensive default

    sql = (
        "SELECT fighter_id FROM fighters "
        "WHERE current_promotion_id = ? AND is_active = 1 "
        "AND weight_class_id = ? "
        # Phase 1.5 Fix B4: explicit gender check — no mixed-gender
        # fights can be booked. Redundant with weight_class_id (which
        # is gender-specific) but defensive: catches any future bug
        # that puts a fighter in a wrong-gender WC.
        "AND gender = ? "
        "AND fighter_id NOT IN (SELECT fighter_id FROM injuries WHERE is_active = 1)"
        # v3.4.0 (Phase B): also exclude fighters with active
        # suspensions. A suspended fighter cannot be booked — the
        # commission / promotion hasn't cleared them to compete.
        # Parallel to the injury exclusion above. The reader is
        # src/suspensions.py:is_fighter_suspended (CONVENTIONS §5.3
        # — every new table ships with at least one reader; the
        # SQL form here is the in-query equivalent for efficiency).
        " AND fighter_id NOT IN (SELECT fighter_id FROM suspensions WHERE is_active = 1)"
    )
    params = [promotion_id, weight_class_id, wc_gender]
    if exclude_fighter_ids:
        # Parameterized NOT IN clause. Never string-format fighter_ids
        # into SQL — always use placeholders.
        placeholders = ",".join("?" * len(exclude_fighter_ids))
        sql += f" AND fighter_id NOT IN ({placeholders})"
        params.extend(exclude_fighter_ids)
    rows = conn.execute(sql, params).fetchall()
    if len(rows) < 2:
        return None
    # random.sample pulls 2 distinct rows without replacement. Both
    # rows are guaranteed same-gender by the WHERE clause above.
    picks = random.sample(rows, 2)
    return (picks[0][0], picks[1][0])


# ----------------------------------------------------------------
# Training camps (Task ID 16).
#
# `_ARCHETYPE_NAME_TO_CAMP_FOCUS` maps the 7 seeded style archetype
# names to the 8 enumerated camp_focus values (the 8th value,
# 'weight_cut', is reserved for Task 17 — weight cuts — and is not
# used by the archetype mapping). `_CAMP_FOCUS_ATTRS` maps each
# camp_focus to the pool of fighter_attributes the camp upgrades on
# completion. Both maps are read by tick_processor._check_training_
# camps (the tick-time camp progress / completion helper), so they
# live here next to the writer (_create_training_camp below) and the
# reader (_get_camp_fatigue_for_event further below) per the "table
# ships with code" rule (CONVENTIONS §5.3).
#
# The camp lifecycle:
#   1. schedule_next_event (below) creates one training_camps row per
#      booked fighter when a new event is auto-scheduled. start_date =
#      event_date - 14 days; end_date = event_date; camp_focus from
#      the fighter's style archetype.
#   2. tick_processor._check_training_camps progresses each active
#      camp on every tick within [start_date, end_date]: fatigue +2-5,
#      morale fluctuates, injury_risk accumulates. If injury_risk > 80
#      a training injury is created via the Task 15 injuries table.
#   3. On the tick where current_date == end_date, the camp completes:
#      2-4 attributes are upgraded by +1 to +3 (capped at potential),
#      a completion news item is written, is_active=0 is_completed=1.
#   4. resolve_next_fight (further below) reads the camp's camp_fatigue
#      via _get_camp_fatigue_for_event and applies the brief's "Fatigue
#      > 50 = reduced starting gas" rule: starting gas = 100 - max(0,
#      camp_fatigue - 50), floored at 50.
# ----------------------------------------------------------------

# Maps the 7 seeded style_archetypes.name values to camp_focus. The
# 8th camp_focus value 'weight_cut' is reserved for Task 17 (weight
# cuts) and is NOT mapped from any archetype — it will be used when
# the weight-cut system creates a separate camp-type entry. The
# default 'general' is used for unknown / NULL archetypes (defensive
# — generate_fighter in app.py picks a random archetype, so this
# fallback only fires if a future archetype is added without updating
# this map).



_ARCHETYPE_NAME_TO_CAMP_FOCUS = {
    "Balanced": "general",
    "Striker": "striking",
    "Grappler": "grappling",
    "Wrestler": "wrestling",
    "Brawler": "striking",
    "Counter-Striker": "striking",
    "Submission Specialist": "submission",
}

# Maps each camp_focus to the pool of fighter_attributes that the
# camp upgrades on completion. All attribute names MUST be in the
# _FIGHTER_ATTR_COLUMNS whitelist (defensive — the completion helper
# in tick_processor string-formats these into UPDATE SQL after
# checking the whitelist; the whitelist check is the safety net).
#
# Striking → punch / kick power + accuracy + head_movement (the 5
#   stand-up attributes — a striking camp sharpens the weapons).
# Grappling → takedown + top_control + submission offense/defense
#   (the 5 ground-work attributes — a grappling camp rounds out the
#   mat game).
# Wrestling → takedown_offense + top_control + cage_wrestling +
#   strength (the 4 wrestling-specific attributes — a wrestling camp
#   builds the grinding top game).
# Conditioning → cardio + recovery_rate + durability (the 3 physical
#   stamina attributes — a conditioning camp builds the engine).
# Submission → submission_offense + submission_defense + bottom_game
#   + flexibility (the 4 submission-specific attributes — a
#   submission camp sharpens the tap-or-pass game).
# Clinch → clinch_striking + clinch_offense + clinch_defense +
#   cage_wrestling (the 4 clinch-phase attributes — a clinch camp
#   builds the dirty-boxing + takedown-clinch game).
# General → punch_power + cardio + fight_iq + chin + footwork +
#   strength (6 well-rounded attributes — a general camp polishes
#   the fundamentals).
# Weight_cut → cardio + recovery_rate (Task 17 territory — a weight-
#   cut camp manages the cut's impact on the engine. For now this
#   pool is used only if the player or AI explicitly schedules a
#   weight_cut camp, which the current code does not).



_CAMP_FOCUS_ATTRS = {
    "striking":   ["punch_power", "punch_accuracy", "kick_power",
                   "kick_accuracy", "head_movement"],
    "grappling":  ["takedown_offense", "takedown_defense", "top_control",
                   "submission_offense", "submission_defense"],
    "wrestling":  ["takedown_offense", "top_control", "cage_wrestling",
                   "strength"],
    "conditioning": ["cardio", "recovery_rate", "durability"],
    "submission": ["submission_offense", "submission_defense",
                   "bottom_game", "flexibility"],
    "clinch":     ["clinch_striking", "clinch_offense", "clinch_defense",
                   "cage_wrestling"],
    "general":    ["punch_power", "cardio", "fight_iq", "chin",
                   "footwork", "strength"],
    "weight_cut": ["cardio", "recovery_rate"],
}

# How many days before the event the camp starts (~2 weeks per the
# Task 16 brief). camp_duration_days = 14. The camp ends on the
# event_date itself (the gains apply on the same tick the event is
# scheduled for — by the time the player clicks Resolve Fight, the
# camp has completed and the improved attributes are in effect).



_CAMP_LEAD_DAYS = 14





def _pick_camp_focus_for_archetype(conn, style_archetype_id):
    """Return the camp_focus string for a fighter's style archetype.

    Looks up the style_archetypes.name for the given id and maps it
    via _ARCHETYPE_NAME_TO_CAMP_FOCUS. Returns 'general' for unknown
    / NULL / missing archetypes (defensive — generate_fighter picks
    a random archetype, but a future code path might insert a fighter
    without one).

    Args:
        conn: sqlite3 connection (read-only — no writes here).
        style_archetype_id: the fighter's fight_style_archetype_id
            (NULL is allowed and returns 'general').

    Returns:
        One of the 8 camp_focus values (always 'general' or one of
        the 7 archetype-mapped values — 'weight_cut' is never returned
        here since it's reserved for Task 17's weight-cut camps).
    """
    if style_archetype_id is None:
        return "general"
    row = conn.execute(
        "SELECT name FROM style_archetypes WHERE style_archetype_id=?",
        (style_archetype_id,),
    ).fetchone()
    if row is None:
        return "general"
    name = row[0]
    return _ARCHETYPE_NAME_TO_CAMP_FOCUS.get(name, "general")





def _create_training_camp(conn, fighter_id, gym_id, event_id, fight_id,
                          event_date, style_archetype_id):
    """Create one training_camps row for a fighter scheduled to fight.

    Called by schedule_next_event (below) for each of the 2 booked
    fighters, AFTER the event + fight + participants + event_cards
    rows are INSERTed. The camp represents the ~2-week training block
    the fighter attends at their gym leading up to the fight.

    Camp fields:
      - start_date = event_date - _CAMP_LEAD_DAYS (14 days before).
      - end_date = event_date (camp ends on fight day — the gains
        apply on the same tick as the event, before the player
        resolves the fight).
      - camp_duration_days = _CAMP_LEAD_DAYS (14).
      - camp_focus = derived from style_archetype_id via
        _pick_camp_focus_for_archetype.
      - camp_morale = 50 (schema DEFAULT — fluctuates during the
        camp via _check_training_camps in tick_processor).
      - camp_fatigue = 0 (schema DEFAULT — accrues during the camp).
      - camp_injury_risk = 0 (schema DEFAULT — accumulates during
        the camp).
      - camp_weight_cut_pressure = 0 (schema DEFAULT — Task 17 will
        populate this).
      - is_active = 1, is_completed = 0.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter attending the camp.
        gym_id: the gym where the camp is held (the fighter's
            current_gym_id at scheduling time — recorded here so
            that if the fighter changes gyms mid-camp, the camp
            still uses the original gym's stats for progression).
        event_id: the event the camp is preparing the fighter for.
        fight_id: the fight the camp is preparing the fighter for.
        event_date: 'YYYY-MM-DD' — the event's date. Used to compute
            start_date and end_date.
        style_archetype_id: the fighter's fight_style_archetype_id
            — drives the camp_focus selection.

    Returns:
        The new training_camp_id (int) on success, or None if the
        INSERT failed (defensive — shouldn't happen unless the DB is
        in a weird state).
    """
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        print(f"Warning: could not create training camp — invalid "
              f"event_date {event_date!r}.")
        return None
    start_dt = event_dt - timedelta(days=_CAMP_LEAD_DAYS)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    end_date_str = event_date
    camp_focus = _pick_camp_focus_for_archetype(conn, style_archetype_id)
    cur = conn.execute(
        "INSERT INTO training_camps (fighter_id, gym_id, event_id, "
        "fight_id, start_date, end_date, camp_duration_days, "
        "camp_focus) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (fighter_id, gym_id, event_id, fight_id,
         start_date_str, end_date_str, _CAMP_LEAD_DAYS, camp_focus),
    )
    return cur.lastrowid





def _get_camp_fatigue_for_event(conn, fighter_id, event_id):
    """Return the camp_fatigue for a fighter's most recent camp on an event.

    Called by resolve_next_fight (below) to apply the brief's "Fatigue
    > 50 = reduced starting gas" rule. Reads the most recent
    training_camps row for the (fighter_id, event_id) pair. Returns
    0 if no camp exists (e.g., the seeded fight — schedule_next_event
    hasn't been called for it yet, so no camp was created).

    Args:
        conn: sqlite3 connection (read-only — no writes here).
        fighter_id: the fighter whose camp fatigue we want.
        event_id: the event the camp prepared them for.

    Returns:
        The camp_fatigue integer (0-100), or 0 if no camp exists.
    """
    row = conn.execute(
        "SELECT camp_fatigue FROM training_camps "
        "WHERE fighter_id=? AND event_id=? "
        "ORDER BY training_camp_id DESC LIMIT 1",
        (fighter_id, event_id),
    ).fetchone()
    return row[0] if row else 0


# ----------------------------------------------------------------
# Full fight card construction (Task FIX-CardSystem).
#
# schedule_next_event builds a FULL CARD with 5-13 fights depending
# on promotion.size_tier, structured as:
#   - Main event (title fight if champion or vacant title available)
#   - Co-main event
#   - 2-3 featured prelims
#   - 3-8 prelims (fill the rest up to target card size)
#
# Matchmaking is "intelligent" (Kingmaker fantasy, Soul doc §3):
#   - Main event: champion vs #1 contender, OR #1 vs #2 for vacant title
#   - Co-main: next-best contender bout
#   - Featured prelims: mid-tier rated fighters
#   - Prelims: mix of prospects, journeymen, debuts, must-win fights
#
# Matchmaking rules (per the brief):
#   - Same weight class per fight (no featherweight vs heavyweight)
#   - Same promotion (no cross-promotion booking)
#   - Both fighters active (is_active=1, is_retired=0)
#   - Neither fighter injured (not in injuries WHERE is_active=1)
#   - Neither fighter suspended (not in suspensions WHERE is_active=1)
#   - Neither fighter fought in last 21 days (rest period)
#   - No fighter booked twice on the same card
#
# If there aren't enough available fighters for a full card, book as
# many as possible (don't crash). A 1-fight card is better than no card.
# ----------------------------------------------------------------

# Card size targets by promotion size_tier. Per the brief:
#   major: 10-13 fights (main event + co-main + 3 featured + 6-8 prelims)
#   mid:   7-9 fights   (main event + co-main + 2 featured + 4-5 prelims)
#   small: 5-6 fights   (main event + 1 featured + 3-4 prelims)
_CARD_SIZE_BY_TIER = {
    'major': (10, 13),
    'mid':   (7, 9),
    'small': (5, 6),
}

# Featured prelim count by size_tier. Per the brief:
#   major: 3 featured prelims
#   mid:   2 featured prelims
#   small: 1 featured prelim



_FEATURED_PRELIM_COUNT_BY_TIER = {
    'major': 3,
    'mid':   2,
    'small': 1,
}

# Rest period: fighters who fought in the last N days are not eligible.



_REST_PERIOD_DAYS = 60  # CR-BALANCE: was 21 (too short), then 90 (too long). 60 days = ~6 fights/year max.

# Title fights are 5 rounds; non-title fights are 3 rounds.



_TITLE_FIGHT_ROUNDS = 5



_NON_TITLE_FIGHT_ROUNDS = 3





def _get_available_fighters_for_card(conn, promotion_id,
                                     rest_days=_REST_PERIOD_DAYS,
                                     before_date=None,
                                     event_id=None):
    """Return all fighters eligible to be booked on a new card.

    Eligibility:
      - current_promotion_id = promotion_id (same promotion)
      - is_active = 1
      - is_retired = 0
      - weight_class_id IS NOT NULL (must have a weight class)
      - Not currently injured (no active injuries row)
      - Not currently suspended (no active suspensions row)
      - Has not fought in the last `rest_days` days (rest period —
        checked against rankings.last_fight_date, relative to the
        new event's date)
      - MM3.1 (docs/MASTER_PLAN_MATCHMAKING_V2.md §3.1): NOT already
        booked on another scheduled event within ±7 days of this
        event's date. Prevents double-booking a fighter across two
        cards in the same week.

    Returns a list of dicts with keys: fighter_id, weight_class_id,
    gender, rating (ELO from rankings, default 1000.0), record_wins,
    record_losses, record_draws, win_streak, loss_streak, potential,
    last_fight_date, camp_status.

    Args:
        conn: sqlite3 connection (read-only — no writes here).
        promotion_id: the promotion whose roster to draw from.
        rest_days: minimum days since the fighter's last fight.
            Default 21 (per the brief).
        before_date: ISO date string 'YYYY-MM-DD' of the new event's
            date. The rest period is measured relative to this date
            (a fighter who fought on 2026-08-15 is eligible for a
            new event on 2026-09-12, since 28 >= 21 days). If None,
            falls back to simulation_clock.current_date (used by
            callers that don't have a specific event date yet).
        event_id: optional int — the event_id whose card is being
            built. Used by the MM3.1 cross-event booking check so we
            can exclude the THIS-event's existing bookings from the
            ±7-day exclusion (those are filtered separately by the
            caller via the booked_ids set). None means "no specific
            event" (treated as a brand-new card with no prior
            bookings to exclude).

    Returns:
        List of fighter-dict rows. Empty list if no fighters are
        eligible.

    Phase 1.5 Fix B4 (gender check): the SELECT now includes
    `f.gender` so the downstream card-build functions can enforce
    the same-gender constraint defensively. The weight_class_id is
    already gender-specific (each WC has a `gender` column), so this
    is a redundant check — but it makes the gender filter explicit
    and impossible to forget. See `_assert_same_gender` (used by the
    build functions).

    MM3.1 (cross-event booking check): if `event_id` AND `before_date`
    are both provided, fighters already booked on another scheduled
    event within ±7 days of `before_date` are excluded. This is the
    fix for the "double-booked across two cards in the same week"
    gap flagged in RESEARCH_MATCHMAKING_CURRENT_STATE.md §3.2 GAP 1.

    MM3.2 (camp status): each fighter dict now includes a
    `camp_status` field with one of three values:
      - "ready"          — fighter has a completed training_camps
                            row in the last 30 days (proper camp
                            done, ready to fight).
      - "needs_camp"     — no recent camp AND the event is > 14
                            days away (camp can still be run; the
                            fighter shows a "needs camp" warning chip
                            but is bookable).
      - "short_notice"   — no recent camp AND the event is ≤ 14
                            days away (camp cannot fit; the fighter
                            MAY reject per MM3.3 personality check at
                            book_fight time).
    The `before_date` is used as the event date for this calculation.
    If `before_date` is None, defaults to "ready" (defensive — older
    callers that don't pass a date shouldn't be blocked).
    """
    rows = conn.execute(
        "SELECT f.fighter_id, f.weight_class_id, f.gender, "
        "COALESCE(r.rating, 1000.0) AS rating, "
        "COALESCE(fc.record_wins, 0), COALESCE(fc.record_losses, 0), "
        "COALESCE(fc.record_draws, 0), COALESCE(fc.win_streak, 0), "
        "COALESCE(fc.loss_streak, 0), COALESCE(fc.potential, 50), "
        "r.last_fight_date "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id = f.fighter_id "
        "  AND r.weight_class_id = f.weight_class_id "
        "  AND r.promotion_id = f.current_promotion_id "
        "WHERE f.current_promotion_id = ? "
        "  AND f.is_active = 1 "
        "  AND f.is_retired = 0 "
        "  AND f.weight_class_id IS NOT NULL "
        "  AND f.fighter_id NOT IN "
        "    (SELECT fighter_id FROM injuries WHERE is_active = 1) "
        "  AND f.fighter_id NOT IN "
        "    (SELECT fighter_id FROM suspensions WHERE is_active = 1)",
        (promotion_id,),
    ).fetchall()

    # MM3.1 — Cross-event booking check. Exclude fighters already
    # booked on ANY scheduled event within ±7 days of this event's
    # date (per docs/MASTER_PLAN_MATCHMAKING_V2.md §3.1). The
    # exclusion is computed once for the whole roster (set lookup
    # is O(1) per fighter). The THIS-event's own bookings are NOT
    # excluded here (the caller filters those via booked_ids);
    # we exclude only OTHER events' bookings.
    cross_event_booked_ids = set()
    if before_date:
        try:
            xrows = conn.execute(
                "SELECT DISTINCT fp.fighter_id "
                "FROM fight_participants fp "
                "JOIN fights f ON f.fight_id = fp.fight_id "
                "JOIN events e ON e.event_id = f.event_id "
                "WHERE e.status = 'scheduled' "
                "  AND e.event_id != ? "
                "  AND ABS(julianday(e.event_date) - julianday(?)) <= 7",
                (event_id or 0, before_date),
            ).fetchall()
            cross_event_booked_ids = {r[0] for r in xrows if r[0]}
        except Exception:
            # Defensive — if the join fails (e.g., a missing column
            # on a partial migration), fall back to no cross-event
            # exclusion (older behavior). Better to show the fighter
            # than to crash the roster query.
            cross_event_booked_ids = set()

    # MM3.2 — Training camp status. The camp-status logic uses two
    # reference dates:
    #   1. camp_ready_cutoff_date = event_date - 30 days. A fighter
    #      with a training_camps row whose end_date >= this cutoff
    #      has "completed a camp in the last 30 days" → 'ready'.
    #   2. short_notice_threshold_date = sim_today + 14 days. If the
    #      event_date <= this threshold (i.e., the event is within
    #      14 days of today), fighters without a recent camp fall to
    #      'short_notice' (may reject per MM3.3); otherwise they're
    #      'needs_camp' (camp can still fit before the event).
    camp_ready_cutoff_date = None
    is_short_notice_event = False
    if before_date:
        try:
            ev_dt = datetime.strptime(before_date, "%Y-%m-%d")
            camp_ready_cutoff_date = (ev_dt - timedelta(days=30)).strftime("%Y-%m-%d")
            # Resolve "today" (the sim's current_date). Falls back to
            # the simulation_clock row; if neither is parseable we
            # treat the event as NOT short-notice (defensive — older
            # callers shouldn't be blocked).
            today_str = None
            try:
                crow = conn.execute(
                    "SELECT simulation_clock.current_date "
                    "FROM simulation_clock WHERE clock_id=1"
                ).fetchone()
                today_str = crow[0] if crow else None
            except Exception:
                today_str = None
            if today_str:
                try:
                    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
                    days_to_event = (ev_dt - today_dt).days
                    # days_to_event can be negative if the event is in
                    # the past (shouldn't happen for a 'scheduled'
                    # event, but defensive). Treat as short-notice.
                    is_short_notice_event = days_to_event <= 14
                except (ValueError, TypeError):
                    is_short_notice_event = False
        except (ValueError, TypeError):
            pass
    # Cache of fighter_ids with a completed camp in the last 30 days.
    # Built once (1 query), checked per-fighter via set lookup.
    camp_ready_ids = set()
    if camp_ready_cutoff_date:
        try:
            crows = conn.execute(
                "SELECT DISTINCT fighter_id FROM training_camps "
                "WHERE is_completed = 1 "
                "  AND end_date >= ?",
                (camp_ready_cutoff_date,),
            ).fetchall()
            camp_ready_ids = {r[0] for r in crows if r[0]}
        except Exception:
            camp_ready_ids = set()

    # Resolve the reference date for the 21-day rest check. Prefer
    # before_date (the new event's date) — this lets us book fighters
    # whose last fight was AFTER the current sim date (e.g., the just-
    # completed event is dated 2026-08-15 but the sim clock is still
    # at 2026-07-21 — the rest period is measured relative to the NEW
    # event's date 2026-09-12, not the sim clock). Falls back to
    # simulation_clock.current_date for callers without a specific
    # event date.
    ref_date_str = before_date
    if ref_date_str is None:
        clock_row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        ref_date_str = clock_row[0] if clock_row else None
    ref_dt = None
    if ref_date_str:
        try:
            ref_dt = datetime.strptime(ref_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            ref_dt = None

    available = []
    for row in rows:
        # Phase 1.5 Fix B4: gender is now in the SELECT (3rd column).
        (fighter_id, weight_class_id, gender, rating,
         wins, losses, draws, win_streak, loss_streak, potential,
         last_fight_date) = row
        # Rest period: skip fighters who fought in the last `rest_days`
        # days BEFORE the new event's date. If we can't parse the date
        # or there's no reference date, be lenient and include the
        # fighter (defensive — the seed may not populate last_fight_date
        # for all fighters).
        if last_fight_date and ref_dt:
            try:
                last_dt = datetime.strptime(last_fight_date, "%Y-%m-%d")
                if (ref_dt - last_dt).days < rest_days:
                    continue
            except (ValueError, TypeError):
                pass  # bad date — be lenient and include the fighter
        # MM3.1 — Cross-event booking check. Skip fighters already
        # booked on another scheduled event within ±7 days.
        if fighter_id in cross_event_booked_ids:
            continue
        # MM3.2 — Compute camp_status for this fighter.
        if not camp_ready_cutoff_date:
            camp_status = 'ready'  # no event date — defensive default
        elif fighter_id in camp_ready_ids:
            camp_status = 'ready'
        elif is_short_notice_event:
            # Event is ≤ 14 days away — short notice.
            camp_status = 'short_notice'
        else:
            # Event is > 14 days away — camp can still fit.
            camp_status = 'needs_camp'
        available.append({
            'fighter_id': fighter_id,
            'weight_class_id': weight_class_id,
            # Phase 1.5 Fix B4: explicit gender — no mixed-gender fights
            # can be booked. Available to the build functions for
            # defensive same-gender assertions.
            'gender': gender,
            'rating': rating,
            'record_wins': wins,
            'record_losses': losses,
            'record_draws': draws,
            'win_streak': win_streak,
            'loss_streak': loss_streak,
            'potential': potential,
            'last_fight_date': last_fight_date,
            # MM3.2 — camp_status: 'ready' / 'needs_camp' / 'short_notice'.
            'camp_status': camp_status,
        })
    return available





def _group_available_by_wc(fighters):
    """Group a list of available-fighter dicts by weight_class_id.

    Returns dict: weight_class_id -> list of fighter dicts.
    """
    by_wc = {}
    for f in fighters:
        by_wc.setdefault(f['weight_class_id'], []).append(f)
    return by_wc



def _same_gender(f1, f2):
    """Phase 1.5 Fix B4: defensive same-gender check.

    Returns True if both fighter dicts have the same 'gender' value.
    Returns False if either is missing 'gender' (defensive — old code
    paths that don't populate 'gender' should NOT silently match
    mixed-gender fighters; they should fail this check and the build
    function will skip to the next pair).

    Used by _build_main_event / _build_co_main / _build_featured_prelim
    / _build_prelim as a redundant safety net on top of the WC grouping
    (weight_class_id is already gender-specific, so two fighters in the
    same WC are by definition the same gender — but this makes the
    constraint EXPLICIT and impossible to silently violate).
    """
    g1 = f1.get('gender')
    g2 = f2.get('gender')
    if g1 is None or g2 is None:
        # Defensive: if gender is missing from either fighter dict,
        # fail safe — don't book the matchup. The build function will
        # skip to the next available pair.
        return False
    return g1 == g2





def _build_main_event(conn, promotion_id, fighters_by_wc, booked_ids):
    """Build the main event fight.

    Per the brief:
      1. If the promotion has a champion (any WC, not vacant): book
         the champion vs the #1 contender (highest-ELO challenger
         who is available).
      2. If no champion (vacant title): book #1 vs #2 contenders for
         the vacant title.
      3. If not enough ranked fighters (or no title at all): book the
         two highest-rated available fighters in the same weight class.

    Main event is 5 rounds (scheduled_rounds=5) if a title is on the
    line, 3 rounds otherwise. is_title_fight=1 if a title is on the
    line.

    Returns a fight dict (with keys: weight_class_id, fighter_a,
    fighter_b, card_slot, is_title_fight, scheduled_rounds) or None
    if can't book.
    """
    # Look at all titles for this promotion, find the best title fight.
    title_rows = conn.execute(
        "SELECT title_id, weight_class_id, current_champion_fighter_id, "
        "is_vacant FROM titles WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchall()

    for title_id, wc_id, champion_id, is_vacant in title_rows:
        if wc_id not in fighters_by_wc:
            continue
        wc_fighters = [f for f in fighters_by_wc[wc_id]
                       if f['fighter_id'] not in booked_ids]
        wc_fighters.sort(key=lambda f: f['rating'], reverse=True)

        if not is_vacant and champion_id is not None:
            # Champion defending — find champion (if available) + top
            # contender. The champion must be in the available pool
            # (not injured, not suspended, rested).
            champion = next((f for f in wc_fighters
                             if f['fighter_id'] == champion_id), None)
            if champion is None:
                continue  # champion not available — try next title
            # Phase 1.5 Fix B4: explicit gender check — no mixed-gender
            # fights can be booked. Pair the champion with the highest-
            # rated same-gender contender. (Redundant given WC grouping,
            # but defensive — a future bug in WC seeding could other-
            # wise slip a mixed-gender matchup past the WC filter.)
            contenders = [f for f in wc_fighters
                          if f['fighter_id'] != champion_id
                          and _same_gender(champion, f)]
            if not contenders:
                continue  # no same-gender contender available
            return {
                'weight_class_id': wc_id,
                'fighter_a': champion['fighter_id'],
                'fighter_b': contenders[0]['fighter_id'],
                'card_slot': 'main_event',
                'is_title_fight': 1,
                'scheduled_rounds': _TITLE_FIGHT_ROUNDS,
            }
        elif is_vacant:
            # Vacant title — book #1 vs #2 contenders for the belt.
            # Phase 1.5 Fix B4: defensive same-gender check — only
            # pair contenders of the same gender.
            if len(wc_fighters) < 2:
                continue
            f1 = wc_fighters[0]
            f2 = next((f for f in wc_fighters[1:]
                       if _same_gender(f1, f)), None)
            if f2 is None:
                continue  # no same-gender #2 contender
            return {
                'weight_class_id': wc_id,
                'fighter_a': f1['fighter_id'],
                'fighter_b': f2['fighter_id'],
                'card_slot': 'main_event',
                'is_title_fight': 1,
                'scheduled_rounds': _TITLE_FIGHT_ROUNDS,
            }

    # No title fight possible — book the two highest-rated fighters
    # in the same weight class (non-title main event).
    # Phase 1.5 Fix B4: defensive same-gender check applies here too.
    by_wc_avail = {}
    for wc_id, fighters in fighters_by_wc.items():
        avail = [f for f in fighters if f['fighter_id'] not in booked_ids]
        avail.sort(key=lambda f: f['rating'], reverse=True)
        if len(avail) >= 2:
            by_wc_avail[wc_id] = avail
    if not by_wc_avail:
        return None
    # Pick the WC with the highest top-2 rating sum — but only pair
    # same-gender fighters (Phase 1.5 Fix B4).
    best = None
    for wc_id, fs in by_wc_avail.items():
        # Find the highest-rated same-gender pair within this WC.
        pair = None
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                if _same_gender(fs[i], fs[j]):
                    pair = (fs[i], fs[j])
                    break
            if pair:
                break
        if pair is None:
            continue
        top2_sum = pair[0]['rating'] + pair[1]['rating']
        if best is None or top2_sum > best[0]:
            best = (top2_sum, wc_id, pair[0], pair[1])
    if best is None:
        return None
    _, wc_id, f1, f2 = best
    return {
        'weight_class_id': wc_id,
        'fighter_a': f1['fighter_id'],
        'fighter_b': f2['fighter_id'],
        'card_slot': 'main_event',
        'is_title_fight': 0,
        'scheduled_rounds': _NON_TITLE_FIGHT_ROUNDS,
    }





def _build_co_main(fighters_by_wc, booked_ids, exclude_wc=None):
    """Build the co-main event: next 2 best-rated in same WC.

    3 rounds, is_title_fight=0. exclude_wc skips a WC (for variety
    — we don't want the entire main card in one weight class).
    Returns fight dict or None.

    Phase 1.5 Fix B4: defensive same-gender check — only pairs
    fighters of the same gender. Redundant with WC grouping (each WC
    is gender-specific) but defensive against future bugs.
    """
    by_wc_avail = {}
    for wc_id, fighters in fighters_by_wc.items():
        if exclude_wc is not None and wc_id == exclude_wc:
            continue
        avail = [f for f in fighters if f['fighter_id'] not in booked_ids]
        avail.sort(key=lambda f: f['rating'], reverse=True)
        if len(avail) >= 2:
            by_wc_avail[wc_id] = avail
    if not by_wc_avail:
        # Fallback: try including the excluded WC (any matchup is
        # better than no co-main).
        if exclude_wc is not None:
            return _build_co_main(fighters_by_wc, booked_ids, exclude_wc=None)
        return None
    # Phase 1.5 Fix B4: explicit gender check — find the highest-rated
    # same-gender pair within each WC, then pick the WC with the best
    # top-2 sum.
    best = None
    for wc_id, fs in by_wc_avail.items():
        pair = None
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                if _same_gender(fs[i], fs[j]):
                    pair = (fs[i], fs[j])
                    break
            if pair:
                break
        if pair is None:
            continue
        top2_sum = pair[0]['rating'] + pair[1]['rating']
        if best is None or top2_sum > best[0]:
            best = (top2_sum, wc_id, pair[0], pair[1])
    if best is None:
        return None
    _, wc_id, f1, f2 = best
    return {
        'weight_class_id': wc_id,
        'fighter_a': f1['fighter_id'],
        'fighter_b': f2['fighter_id'],
        'card_slot': 'co_main',
        'is_title_fight': 0,
        'scheduled_rounds': _NON_TITLE_FIGHT_ROUNDS,
    }





def _build_featured_prelim(fighters_by_wc, booked_ids, exclude_wc=None):
    """Build a featured prelim: mid-tier rated in same WC.

    3 rounds, is_title_fight=0. exclude_wc skips a WC for variety.
    Returns fight dict or None.

    Phase 1.5 Fix B4: defensive same-gender check — only pairs
    fighters of the same gender. Redundant with WC grouping but
    defensive.
    """
    by_wc_avail = {}
    for wc_id, fighters in fighters_by_wc.items():
        if exclude_wc is not None and wc_id == exclude_wc:
            continue
        avail = [f for f in fighters if f['fighter_id'] not in booked_ids]
        avail.sort(key=lambda f: f['rating'], reverse=True)
        if len(avail) >= 2:
            by_wc_avail[wc_id] = avail
    if not by_wc_avail:
        return None
    # Phase 1.5 Fix B4: explicit gender check — pick the WC with the
    # highest top-2 same-gender rating sum.
    best = None
    for wc_id, fs in by_wc_avail.items():
        pair = None
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                if _same_gender(fs[i], fs[j]):
                    pair = (fs[i], fs[j])
                    break
            if pair:
                break
        if pair is None:
            continue
        top2_sum = pair[0]['rating'] + pair[1]['rating']
        if best is None or top2_sum > best[0]:
            best = (top2_sum, wc_id, pair[0], pair[1])
    if best is None:
        return None
    _, wc_id, f1, f2 = best
    return {
        'weight_class_id': wc_id,
        'fighter_a': f1['fighter_id'],
        'fighter_b': f2['fighter_id'],
        'card_slot': 'featured_prelim',
        'is_title_fight': 0,
        'scheduled_rounds': _NON_TITLE_FIGHT_ROUNDS,
    }





def _build_prelim(fighters_by_wc, booked_ids):
    """Build a prelim: mix of prospects, journeymen, debuts, must-wins.

    3 rounds, is_title_fight=0. Returns fight dict or None.

    Priority: weight classes with debuts (0-0 records) or must-win
    fighters (loss_streak >= 2) are preferred — this is where the
    "prospect development" and "must-win fight" storylines live
    (Kingmaker fantasy).

    Phase 1.5 Fix B4: defensive same-gender check — only pairs
    fighters of the same gender. Redundant with WC grouping but
    defensive.
    """
    by_wc_avail = {}
    for wc_id, fighters in fighters_by_wc.items():
        avail = [f for f in fighters if f['fighter_id'] not in booked_ids]
        if len(avail) >= 2:
            by_wc_avail[wc_id] = avail
    if not by_wc_avail:
        return None

    # Priority: WC with debuts (0-0 records) or must-win fighters
    # (loss_streak >= 2). This is where the prospect-development
    # and must-win storylines live.
    def wc_priority(item):
        wc_id, fs = item
        has_debut = any(
            (f['record_wins'] + f['record_losses'] + f['record_draws']) == 0
            for f in fs)
        has_must_win = any(f['loss_streak'] >= 2 for f in fs)
        return (has_debut, has_must_win, len(fs))

    sorted_wcs = sorted(by_wc_avail.items(), key=wc_priority, reverse=True)
    for wc_id, fs in sorted_wcs:
        # Within this WC, prefer prospect (high potential) — sort by
        # potential desc and pick top 2 same-gender fighters (Phase
        # 1.5 Fix B4). This gives the "prospect development" storyline
        # a chance to fire (the prospect gets matched against the next-
        # available fighter, who may be a journeyman or another
        # prospect).
        fs_sorted = sorted(fs, key=lambda f: f['potential'], reverse=True)
        # Phase 1.5 Fix B4: explicit gender check — find the highest-
        # potential same-gender pair within this WC.
        f1 = fs_sorted[0]
        f2 = next((f for f in fs_sorted[1:] if _same_gender(f1, f)), None)
        if f2 is None:
            continue  # no same-gender partner for the top prospect
        return {
            'weight_class_id': wc_id,
            'fighter_a': f1['fighter_id'],
            'fighter_b': f2['fighter_id'],
            'card_slot': 'prelim',
            'is_title_fight': 0,
            'scheduled_rounds': _NON_TITLE_FIGHT_ROUNDS,
        }
    return None


# ----------------------------------------------------------------
# Event naming (FIX-VoiceRep — event naming variety;
# FIX-Critical — expanded to 200+ themes + player setting).
#
# Per the brief, schedule_next_event should produce varied event
# names instead of always using "{Promo} {N}: {FighterA} vs
# {FighterB}". Real MMA promotions mix recognizable numbered shows
# with themed names ("UFC 300: Pereira vs Hill" but also "UFC Fight
# Night: Whittaker vs Aliskerov" and themed shows like "UFC 281:
# Adesanya vs Pereira"). 70% of events use the default recognizable
# format; 30% use a themed name. The themed names use a curated
# list of MMA-appropriate theme words (single-word evocative nouns
# that read like a PPV subtitle). The themes are digit-free per
# CONVENTIONS §14.
#
# FIX-Critical (Issue 5): the OLD list had 25 themes — too thin
# (the same theme would repeat within a few sim weeks). Expanded
# to 200+ themes grouped by tone (Aggressive, Epic, Dark, Combat,
# Drama, Elements, Mythic). Also added the `event_naming_style`
# player setting ('numbered' / 'themed' / 'mixed') so the player
# can pick their preferred format. Default 'mixed' preserves the
# OLD 70/30 split behavior for backward compatibility.
# ----------------------------------------------------------------

# Themed event name prefixes (per the brief). 70/30 split — the
# default recognizable format dominates so the player can always
# identify the main event at a glance, with occasional themed
# shows for variety. The two default variants are functionally
# identical (same "{promo} {num}: {a} vs {b}" output) but listed
# twice to weight the default at ~70%. Used ONLY when the player's
# event_naming_style setting is 'mixed' (the default).



EVENT_NAME_THEMES = [
    "{promo} {num}: {a} vs {b}",   # default (70% — listed twice)
    "{promo} {num}: {a} vs {b}",   # default
    "{promo} {num}: {theme}",      # themed (30%)
]

# Curated theme words (FIX-Critical, expanded from 25 → 200+).
# Grouped by tone per the brief — the groups are documentation
# only (the picker treats them as one flat list). All single-word
# (or short-phrase) nouns, no digits. Used by _build_event_name
# when the player's event_naming_style is 'themed' or 'mixed'.



EVENT_THEMES = [
    # ---- Aggressive (13) --------------------------------------
    "Annihilation", "Bloodbath", "Carnage", "Decimation", "Destruction",
    "Domination", "Extermination", "Obliteration", "Onslaught", "Rampage",
    "Retribution", "Vengeance", "Wrath",
    # ---- Epic (11) --------------------------------------------
    "Ascension", "Conquest", "Crown", "Dynasty", "Empire",
    "Genesis", "Legacy", "Legend", "Throne", "Triumph", "Victory",
    # ---- Dark (12) --------------------------------------------
    "Abyss", "Blackout", "Catacombs", "Darkness", "Eclipse",
    "Fallout", "Haunted", "Inferno", "Nightmare", "Shadows",
    "Underworld", "Void",
    # ---- Combat (19) ------------------------------------------
    "Battlefield", "Beatdown", "Brawl", "Clash", "Collision",
    "Combat", "Crossfire", "Fight Night", "Ground War", "Heavy Hitters",
    "Melee", "No Quarter", "Rumble", "Showdown", "Slugfest",
    "Stranglehold", "Uprising", "Warpath", "Warfare",
    # ---- Drama (19) -------------------------------------------
    "Betrayal", "Breaking Point", "Crossroads", "Curtain Call", "Defiance",
    "Desperation", "Divide", "Fracture", "Judgment", "Last Stand",
    "No Escape", "Pressure Point", "Reckoning", "Redemption",
    "Resurrection", "Revolution", "Ruin", "Turmoil", "Unforgiven",
    # ---- Elements (13) ----------------------------------------
    "Avalanche", "Blizzard", "Cyclone", "Earthquake", "Firestorm",
    "Hurricane", "Lightning", "Monsoon", "Thunder", "Tornado",
    "Tsunami", "Volcano", "Wildfire",
    # ---- Mythic (13) ------------------------------------------
    "Apocalypse", "Armageddon", "Cerberus", "Colossus", "Doomsday",
    "Goliath", "Hydra", "Leviathan", "Odin", "Phoenix",
    "Ragnarok", "Titan", "Valkyrie",
    # ---- Additional curated (extras to exceed the 200+ target) ----
    # Aggressive-adjacent.
    "Aggression", "Backlash", "Berserk", "Brutality", "Crusher",
    "Fury", "Hammer", "Havoc", "Hostile", "Malice",
    "Menace", "Outrage", "Punishment", "Riot", "Savage",
    "Slaughter", "Storm", "Tempest", "Tyranny",
    # Combat-adjacent.
    "Battleground", "Bell", "Blockbuster", "Bravado", "Cage",
    "Championship", "Combat Zone", "Contender", "Duel", "Eliminator",
    "Final Bell", "Fighters Edge", "Fighters Path", "Final Round",
    "First Blood", "Grand Prix", "Heavyweight", "Knockout", "Main Event",
    "Marquee", "Matchup", "Maul", "No Mercy",
    "Pit", "Prize Fight", "Quake", "Riot Act",
    "Smash", "Title Bout", "Title Shot", "Takedown", "Tournament",
    "Turf War", "Unleashed", "Vendetta", "War Zone", "Whirlwind",
    # Drama / storyline-adjacent.
    "Betrayed", "Brink", "Challenger", "Champions Path", "Climax",
    "Confrontation", "Crisis", "Crucible", "Culmination",
    "Curtain", "Decider", "Destiny", "Doubt", "Endgame",
    "Final Verdict", "Fork In The Road", "Fury Road",
    "Heartbreak", "Honor", "Heart", "Last Rites", "Last Word",
    "Limit", "Line In The Sand", "Moment Of Truth", "Nemesis", "New Beginning",
    "Overture", "Pinnacle", "Point Of No Return", "Reckoning Day",
    "Rematch", "Retaliation", "Rivalry", "Rough Justice", "Roundtable",
    "Showtime", "Sin", "Standoff", "Standpoint", "Summit",
    "Survival", "Tide", "Toll", "Trial",
    "Tribulation", "Truth", "Ultimatum", "Vow", "Zero Hour",
    # Original 25 themes (kept for continuity — they're fan favorites).
    "Unforgiven", "Cataclysm", "Ignition",
    "Bad Blood", "Crushing Blow", "Iron Fist",
    "Ground Zero", "Battle Ground", "Collision Course",
]





def _get_event_naming_style(conn):
    """Read the player's event_naming_style setting (FIX-Critical Issue 5).

    Returns one of: 'numbered', 'themed', 'mixed'. Defaults to 'mixed'
    (preserves the OLD 70/30 split behavior for backward compatibility).
    Lazy-imports player_settings to avoid a module-load circular
    dependency. Defensive — any error (missing table, missing module,
    invalid value) falls back to 'mixed'.
    """
    try:
        from player_settings import get_setting
        style = get_setting(conn, 'event_naming_style', default='mixed')
        if style in ('numbered', 'themed', 'mixed'):
            return style
    except Exception:
        pass  # defensive — missing table / module, fall back to default
    return 'mixed'





def _build_event_name(promo_name, event_num, me_a_name, me_b_name,
                      rng=None, conn=None):
    """Pick an event name with player-controlled variety (FIX-Critical).

    The player's event_naming_style setting (in player_settings)
    controls the template selection:
      'numbered' → "{promo} {num}: {a} vs {b}" (always — the recognizable
                   default so the player can always identify the main
                   event at a glance).
      'themed'   → "{promo} {num}: {theme}" (always — every event gets
                   a themed subtitle from the 200+ EVENT_THEMES list).
      'mixed'    → 70% numbered, 30% themed (the default — preserves
                   the OLD behavior for backward compatibility with
                   existing tests + the established look-and-feel).

    Special case: a promotion's FIRST event (event_num == 1) ALWAYS
    uses the numbered format. Real promotions always use the
    "{Promo} 1: {a} vs {b}" format for their debut — themed names
    don't appear until later events. This also keeps the test suite
    deterministic: tests that schedule the first event for a new
    promotion (e.g., test_card_system.py case J with seed=42) get
    the default format without RNG flakiness.

    Args:
        promo_name: promotion name (e.g., "Alpha Combat").
        event_num: 1-based event count for this promotion (next event
            after the debut is event 2).
        me_a_name, me_b_name: main event fighter names (used by the
            numbered format; ignored by the themed format).
        rng: optional random.Random. If None, uses the GLOBAL random
            module (so callers who set random.seed() — including
            existing tests — get a deterministic result that respects
            their seed).
        conn: optional sqlite3 connection. If provided, the function
            reads the player's event_naming_style setting. If None or
            the setting is missing, falls back to 'mixed' (the
            backward-compatible default).

    Returns:
        The event name string (e.g., "Alpha Combat 3: Vale vs Reed"
        or "Alpha Combat 3: Reckoning").
    """
    # First event of a promotion always uses the default recognizable
    # format. This matches real-world promotion behavior (UFC 1,
    # Bellator 1, etc. — never themed) and keeps the test suite
    # deterministic.
    if event_num <= 1:
        return "{promo} {num}: {a} vs {b}".format(
            promo=promo_name, num=event_num,
            a=me_a_name, b=me_b_name,
        )

    # Read the player's preferred naming style (FIX-Critical Issue 5).
    naming_style = 'mixed'
    if conn is not None:
        naming_style = _get_event_naming_style(conn)

    # Pick the template based on the style.
    # 'mixed' preserves the OLD behavior (70% numbered / 30% themed)
    # by using the EVENT_NAME_THEMES list (2 numbered + 1 themed →
    # 67%/33%, close enough to the brief's 70/30 — and matches every
    # existing test's expected behavior).
    if naming_style == 'numbered':
        template = "{promo} {num}: {a} vs {b}"
    elif naming_style == 'themed':
        template = "{promo} {num}: {theme}"
    else:  # 'mixed' (the default + fallback)
        if rng is None:
            import random as _rng
            template = _rng.choice(EVENT_NAME_THEMES)
        else:
            template = rng.choice(EVENT_NAME_THEMES)

    if "{theme}" in template:
        if rng is None:
            import random as _rng
            theme = _rng.choice(EVENT_THEMES)
        else:
            theme = rng.choice(EVENT_THEMES)
        return template.format(
            promo=promo_name, num=event_num, theme=theme,
        )
    return template.format(
        promo=promo_name, num=event_num,
        a=me_a_name, b=me_b_name,
    )





def schedule_next_event(conn, promotion_id, from_event_date=None, weeks_out=4):
    """Auto-schedule the next event for a promotion, ~weeks_out weeks
    after a reference date. Builds a FULL FIGHT CARD with 5-13 fights
    depending on promotion.size_tier (Task FIX-CardSystem).

    Card structure (per the brief):
      - Main event (card_slot='main_event', is_title_fight=1 if champion
        or vacant title available, scheduled_rounds=5 if title fight)
      - Co-main event (card_slot='co_main', 3 rounds, is_title_fight=0)
      - 2-3 featured prelims (card_slot='featured_prelim', 3 rounds)
      - 3-8 prelims (card_slot='prelim', 3 rounds)

    Card size by promotion size_tier:
      - major: 10-13 fights
      - mid:   7-9 fights
      - small: 5-6 fights

    Matchmaking (Kingmaker fantasy, Soul doc §3):
      - Main event: champion vs #1 contender (title defense), OR #1 vs
        #2 for vacant title, OR top 2 rated (non-title)
      - Co-main: next 2 best-rated (different WC for variety if possible)
      - Featured prelims: mid-tier rated (different WC for variety)
      - Prelims: mix of prospects, journeymen, debuts, must-win fighters

    Matchmaking rules:
      - Same weight class per fight (no featherweight vs heavyweight)
      - Same promotion (no cross-promotion booking)
      - Both fighters active (is_active=1, is_retired=0)
      - Neither fighter injured (not in injuries WHERE is_active=1)
      - Neither fighter suspended (not in suspensions WHERE is_active=1)
      - Neither fighter fought in last 21 days (rest period)
      - No fighter booked twice on the same card

    If there aren't enough available fighters for a full card, book as
    many as possible (don't crash). A 1-fight card is better than no card.

    Event name format: "{Promotion Name} {Number}: {FighterA} vs
    {FighterB}" where Number = promotion's event count + 1, and
    FighterA/FighterB are the main event fighters.

    Called by resolve_next_fight() as a side effect when an event just
    transitioned to 'completed' (Task ID 8). Can also be called directly
    for testing or for "I want to schedule an event now" UI actions.

    Args:
        conn: sqlite3 connection (caller commits).
        promotion_id: the promotion to schedule for.
        from_event_date: ISO date string 'YYYY-MM-DD' to count weeks_out
            from. If None, uses simulation_clock.current_date.
        weeks_out: how many weeks ahead to schedule. Default 4.

    Returns:
        New event_id (int) on success, or None on failure (with a
        printed warning explaining why).
    """
    # 1. Resolve the reference date.
    if from_event_date is None:
        # v2.0.0 (Task 14.7): qualify current_date as
        # simulation_clock.current_date to avoid the §Z.6 quirk where
        # bare `current_date` resolves to SQLite's built-in date
        # function (today's wall-clock date).
        clock_row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id = 1"
        ).fetchone()
        if not clock_row or not clock_row[0]:
            print("Warning: could not auto-schedule next event — no "
                  "from_event_date given and simulation_clock has no "
                  "current_date.")
            return None
        from_event_date = clock_row[0]
    try:
        ref_date = datetime.strptime(from_event_date, "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        print(f"Warning: could not auto-schedule next event — invalid "
              f"from_event_date {from_event_date!r}: {e}")
        return None

    # 2. Compute the new event_date.
    new_date = ref_date + timedelta(weeks=weeks_out)
    new_date_str = new_date.strftime("%Y-%m-%d")

    # 3. Find venue + market for the new event. Reuse the values from
    # the promotion's most recent completed event. (The old code also
    # reused weight_class_id from the completed event — but the new
    # card-construction logic picks weight classes per fight based on
    # available fighters, so we no longer need a single weight_class_id
    # for the whole event. Each fight on the card has its own WC.)
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
        # Degenerate fallback: no completed event yet for this
        # promotion. This can happen when schedule_next_event() is
        # called directly (test case F) before any event has been
        # resolved. Fall back to any venue in any city whose nation
        # matches the promotion's nation. If that also fails, give up.
        promo_row = conn.execute(
            "SELECT nation_id, name, size_tier "
            "FROM promotions WHERE promotion_id = ?",
            (promotion_id,),
        ).fetchone()
        if promo_row is None:
            print(f"Warning: could not auto-schedule next event — "
                  f"promotion_id={promotion_id} not found and no "
                  f"completed event to reuse.")
            return None
        nation_id = promo_row[0]
        if nation_id is None:
            print(f"Warning: could not auto-schedule next event — "
                  f"promotion_id={promotion_id} has no nation_id and no "
                  f"completed event to reuse.")
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
            print(f"Warning: could not auto-schedule next event — no "
                  f"venue/market found for nation_id={nation_id} "
                  f"(promotion_id={promotion_id}).")
            return None
        venue_id, market_id = fallback

    # 4. Get promotion info (name, size_tier).
    promo_row = conn.execute(
        "SELECT name, size_tier FROM promotions WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchone()
    if promo_row is None:
        print(f"Warning: could not auto-schedule next event — "
              f"promotion_id={promotion_id} not found.")
        return None
    promo_name, size_tier = promo_row
    size_tier_key = (size_tier or 'small').lower()

    # 5. Determine target card size + featured prelim count from size_tier.
    target_min, target_max = _CARD_SIZE_BY_TIER.get(
        size_tier_key, _CARD_SIZE_BY_TIER['small'])
    featured_count = _FEATURED_PRELIM_COUNT_BY_TIER.get(
        size_tier_key, _FEATURED_PRELIM_COUNT_BY_TIER['small'])

    # 6. Get all available fighters (active, not injured, not suspended,
    # not fought in last 21 days). The rest period is measured relative
    # to the NEW event's date (a fighter who fought on 2026-08-15 is
    # eligible for a new event on 2026-09-12, since 28 >= 21 days).
    available = _get_available_fighters_for_card(
        conn, promotion_id, before_date=new_date_str)
    if len(available) < 2:
        print(f"Warning: could not auto-schedule next event — not "
              f"enough active fighters in promotion_id={promotion_id} "
              f"(need at least 2, got {len(available)}).")
        return None

    # 7. Group available fighters by weight class.
    fighters_by_wc = _group_available_by_wc(available)

    # 8. Build the card: main event → co-main → featured prelims →
    # prelims. Each fight picks 2 fighters in the same weight class
    # who have not been booked yet on this card.
    booked_ids = set()
    card_fights = []

    # 8a. Main event (title fight if possible).
    main_event = _build_main_event(conn, promotion_id, fighters_by_wc, booked_ids)
    if main_event is None:
        print(f"Warning: could not auto-schedule next event — could not "
              f"book a main event for promotion_id={promotion_id} "
              f"(no 2 available fighters in the same weight class).")
        return None
    # v3.8.0 (Task 6.0): populate regional_rival memory link if both
    # main-event fighters share a birth nation or region. Idempotent.
    # Per docs/TASK_6_0_PLAN.md §3.5, called inline after fighter
    # selection (matches how _check_retirements publishes
    # FIGHTER_RETIRED inline per CONVENTIONS §15.4). The call is in
    # schedule_next_event (the caller of _build_main_event) rather
    # than inside _build_main_event itself to keep _build_main_event
    # pure — see CRITICAL RULE "no signature changes" for _build_co_main
    # which doesn't take conn; same pattern applied here for symmetry.
    try:
        from services.memory_svc import populate_regional_rival
        populate_regional_rival(conn, main_event['fighter_a'], main_event['fighter_b'])
    except ImportError:
        pass
    card_fights.append(main_event)
    booked_ids.add(main_event['fighter_a'])
    booked_ids.add(main_event['fighter_b'])
    main_event_wc = main_event['weight_class_id']

    # 8b. Co-main event. Try a different WC for variety; fall back to
    # any WC if needed.
    if len(card_fights) < target_max:
        co_main = _build_co_main(fighters_by_wc, booked_ids,
                                 exclude_wc=main_event_wc)
        if co_main is not None:
            # v3.8.0 (Task 6.0): populate regional_rival memory link for
            # the co-main event. Idempotent. Same pattern as the main
            # event above. Called in schedule_next_event because
            # _build_co_main doesn't take conn (CRITICAL RULE: no
            # signature changes).
            try:
                from services.memory_svc import populate_regional_rival
                populate_regional_rival(conn, co_main['fighter_a'], co_main['fighter_b'])
            except ImportError:
                pass
            card_fights.append(co_main)
            booked_ids.add(co_main['fighter_a'])
            booked_ids.add(co_main['fighter_b'])

    # 8c. Featured prelims (2-3 fights, varying WCs for variety).
    for i in range(featured_count):
        if len(card_fights) >= target_max:
            break
        # Try to exclude the main event's WC for variety on the first
        # featured prelim. Subsequent ones pick the best WC available.
        exclude_wc = main_event_wc if i == 0 else None
        fp = _build_featured_prelim(fighters_by_wc, booked_ids,
                                    exclude_wc=exclude_wc)
        if fp is None and exclude_wc is not None:
            # Fallback: try without the exclusion.
            fp = _build_featured_prelim(fighters_by_wc, booked_ids,
                                        exclude_wc=None)
        if fp is None:
            break
        card_fights.append(fp)
        booked_ids.add(fp['fighter_a'])
        booked_ids.add(fp['fighter_b'])

    # 8d. Prelims (fill the rest up to target_max). Each prelim picks
    # 2 available fighters in the same WC, prioritizing prospects and
    # must-win fighters for the undercard storylines.
    while len(card_fights) < target_max:
        pr = _build_prelim(fighters_by_wc, booked_ids)
        if pr is None:
            break
        card_fights.append(pr)
        booked_ids.add(pr['fighter_a'])
        booked_ids.add(pr['fighter_b'])

    # 9. Build event_name with variety. 70% chance: the recognizable
    # default "{promo} {N}: {FighterA} vs {FighterB}" (so the player
    # can always identify the main event at a glance). 30% chance:
    # a themed name "{promo} {N}: {Theme}" (variety, like real
    # promotions — UFC does "UFC 300: Pereira vs Hill" but also
    # "UFC Fight Night: Whittaker vs Aliskerov" and themed shows
    # like "UFC 281: Adesanya vs Pereira"). Per the brief, the
    # themed names use a curated list of MMA-appropriate theme words.
    # The number is the promotion's event count + 1 (so the next
    # Alpha Combat event after their debut is "Alpha Combat 2: ...").
    event_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchone()[0]
    me_a_name = fighter_name(conn, main_event['fighter_a'])
    me_b_name = fighter_name(conn, main_event['fighter_b'])
    # FIX-Critical (Issue 5): pass `conn` so _build_event_name can
    # read the player's event_naming_style setting ('numbered' /
    # 'themed' / 'mixed'). Defaults to 'mixed' (the OLD 70/30 split)
    # for backward compatibility.
    event_name = _build_event_name(
        promo_name, event_count + 1, me_a_name, me_b_name, conn=conn,
    )

    # 10. Insert the new event (status='scheduled', event_type='fight_night').
    new_event_id = conn.execute(
        "INSERT INTO events (promotion_id, venue_id, market_id, event_name, "
        "event_date, event_type, status) VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
        (promotion_id, venue_id, market_id, event_name,
         new_date_str, "fight_night"),
    ).lastrowid

    # 11. Insert all fight rows + 2 participants each + 1 event_cards
    # row each. Also create training camps for all booked fighters
    # (existing behavior from Task 16 — preserves the camp progression
    # system that drives the Talent Hunter fantasy).
    # v2.2.0 (Task pre-B2-fix): card_slot + is_title_fight are the
    # canonical signals (bout_type is kept for backward compatibility —
    # we set bout_type = card_slot for external readers that still
    # check bout_type).
    for position, fight in enumerate(card_fights, start=1):
        new_fight_id = conn.execute(
            "INSERT INTO fights (event_id, weight_class_id, bout_type, "
            "card_slot, is_title_fight, round_limit, scheduled_rounds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_event_id, fight['weight_class_id'], fight['card_slot'],
             fight['card_slot'], fight['is_title_fight'], 3,
             fight['scheduled_rounds']),
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
        # Create training camps for both booked fighters. If a fighter
        # has no current_gym_id, the camp is skipped with a warning
        # (existing pattern — the fighter still gets to fight, just
        # without the camp progression / gain benefits).
        for fid in (fight['fighter_a'], fight['fighter_b']):
            f_row = conn.execute(
                "SELECT current_gym_id, fight_style_archetype_id "
                "FROM fighters WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if f_row is None:
                print(f"Warning: could not create training camp — fighter "
                      f"{fid} not found in fighters table.")
                continue
            f_gym_id, f_archetype_id = f_row
            if f_gym_id is None:
                print(f"Warning: fighter {fid} has no current_gym_id — "
                      f"skipping training camp creation (no home gym).")
                continue
            _create_training_camp(
                conn,
                fighter_id=fid,
                gym_id=f_gym_id,
                event_id=new_event_id,
                fight_id=new_fight_id,
                event_date=new_date_str,
                style_archetype_id=f_archetype_id,
            )

        # HW9.2 — wire memory resurfacing into the fight booking path.
        # After each fight is INSERTed, call surface_memories to find
        # any relevant history between the two fighters. If memories
        # are found, write a memory_resurfacing news item ("fight
        # preview" beat). This is the wiring that HW3.5 flagged as
        # missing — the engine + data existed but the caller wasn't
        # connected. The function is defensive (never raises, returns
        # None on any failure) so it can't crash the booking path.
        try:
            from news import generate_fight_preview_memory_news
            generate_fight_preview_memory_news(
                conn, fight_id=new_fight_id,
                fighter_a_id=fight['fighter_a'],
                fighter_b_id=fight['fighter_b'],
                event_id=new_event_id,
                promotion_id=promotion_id,
                published_at=new_date_str,
            )
        except Exception as e:
            import sys
            print(f"WARNING: generate_fight_preview_memory_news failed "
                  f"for fight_id={new_fight_id}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)

    # 12. Return the new event_id. Do NOT commit — the caller commits,
    # matching the existing pattern (resolve_next_fight, advance_day,
    # etc.).
    return new_event_id

