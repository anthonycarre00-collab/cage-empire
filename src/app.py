import sqlite3
import json
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
import os
DB_PATH = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(PROJECT_DIR / "data" / "cage_empire.db")))

# ============================================================
# Stage 6 (Task 6.0) — re-export block.
# These names are extracted to src/services/*.py modules but kept
# importable from `app` for backwards-compat (tests, tick_processor,
# agent_offers, rival_ai, morale, career_arc, mods). The block ALSO
# serves module-scope name resolution for the App class body further
# below, which uses `advance_day`, `resolve_next_fight`,
# `sign_free_agent`, etc. as bare names. Per Plan agent Fix #9, this
# block MUST live at module scope (NOT inside a function/conditional).
# ============================================================
from services.clock import (
    fighter_name,
    get_clock,
    advance_day,
)

from services.matchmaking import (
    schedule_next_event,
    _pick_matchup,
    _build_main_event,
    _build_co_main,
    _build_featured_prelim,
    _build_prelim,
    _get_available_fighters_for_card,
    _group_available_by_wc,
    _get_event_naming_style,
    _build_event_name,
    EVENT_NAME_THEMES,
    EVENT_THEMES,
    # Camp helpers (used by tick_processor + App)
    _create_training_camp,
    _get_camp_fatigue_for_event,
    _pick_camp_focus_for_archetype,
    _ARCHETYPE_NAME_TO_CAMP_FOCUS,
    _CAMP_FOCUS_ATTRS,
    _CAMP_LEAD_DAYS,
    # Card-size + rest-period constants
    _CARD_SIZE_BY_TIER,
    _FEATURED_PRELIM_COUNT_BY_TIER,
    _REST_PERIOD_DAYS,
    _TITLE_FIGHT_ROUNDS,
    _NON_TITLE_FIGHT_ROUNDS,
)

from services.fight_engine import (
    # Public functions
    resolve_next_fight,
    resolve_round,
    update_fighter_descriptor_snapshot,
    # Beat engine internals (used by tests)
    _load_fighter_stats,
    _compute_beat_scores,
    _compute_gas_cost,
    _recover_gas_between_rounds,
    _compute_fight_importance,
    _compute_pressure_response,
    _compute_pressure_modifier,
    _ko_threshold,
    _ko_finish_probability,
    _submission_score,
    _doctor_stoppage_threshold,
    _check_corner_stoppage,
    _check_dq,
    _pick_action_type,
    _compute_damage,
    _resolve_beat_outcome,
    _maybe_transition_phase,
    _select_commentary_beats,
    _maybe_create_injury,
    _run_weight_cut,
    _compute_weight_cut_miss_prob,
    _resolve_title_after_fight,
    _update_event_status_after_resolution,
    _get_or_create_ranking_row,
    _update_rankings_after_resolution,
    # Gameplan derivation (used by tests)
    _derive_preferred_gameplans,
    _derive_bad_matchup_tags,
    _update_preferred_gameplans,
    _update_bad_matchup_tags,
    _opponent_style_archetype_name,
    # Constants (used by tests + tick_processor + agent_offers)
    _FIGHTER_ATTR_COLUMNS,
    _FIGHTER_PERS_COLUMNS,
    _ELO_K,
    _INITIAL_RATING,
    _INJURY_BASE_DAYS_PER_SEVERITY,
    _INJURY_CAREER_HEALTH_MULT,
    _INJURY_MIN_DAYS_OUT,
    _INJURY_RECOVERY_RATE_DAYS_PER_POINT,
    _GAMEPLAN_THRESHOLD,
    _GAMEPLAN_CAP,
    _BAD_MATCHUP_CAP,
    _BEAT_COMMENTARY_TEMPLATES,
    PHASE_ATTRS,
    PHASE_ACTIONS,
)

from services.contracts import (
    get_contracts_for_display,
    get_free_agents_for_display,
    sign_free_agent,
)

from services.retirement_svc import (
    generate_fighter,
    _vacate_title_on_retirement,
)

def write_news(conn, headline, body, topic="event", event_id=None, fight_id=None, fighter_id=None, promotion_id=None):
    src = conn.execute("SELECT news_source_id FROM news_sources WHERE name='System Feed'").fetchone()
    src_id = src[0] if src else conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80)).lastrowid
    conn.execute("INSERT INTO news_items (news_source_id, headline, body, sentiment, topic, event_id, fight_id, fighter_id, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (src_id, headline, body, "neutral", topic, event_id, fight_id, fighter_id, promotion_id))

def write_commentary(conn, event_id=None, fight_id=None, text=""):
    speaker = conn.execute("SELECT staff_id FROM staff WHERE role_type='commentator' LIMIT 1").fetchone()
    speaker_id = speaker[0] if speaker else None
    conn.execute("INSERT INTO commentary_segments (event_id, fight_id, segment_type, speaker_staff_id, text, importance) VALUES (?, ?, ?, ?, ?, ?)", (event_id, fight_id, "play_by_play", speaker_id, text, 70))


# ----------------------------------------------------------------
# Fighter roster display helper (Task ID 6).
#
# Extracted from the inline query that used to live in
# `App.refresh_all()` so the multi-promotion filter logic is
# testable without a Tkinter display. The test script
# `scripts/test_promotion_filter.py` imports this helper directly.
#
# Returns the same 4-tuple shape the Fighters Treeview was already
# rendering: (name, weight_class, promotion_name, record) — so
# `refresh_all()`'s `insert('', 'end', values=r)` call is unchanged.
#
# Schema version is unchanged (still 1.3.0) — no new tables, no new
# columns. RFL stays inert (no AI behaviour); this helper just makes
# the UI aware that multiple promotions exist.
# ----------------------------------------------------------------

def get_fighters_for_display(conn, promotion_filter=None):
    """Return fighter rows for the UI Fighters tree.

    Args:
        conn: sqlite3 connection.
        promotion_filter: None (all fighters, including free agents
            with current_promotion_id = NULL), or a promotion_id int
            (only fighters whose current_promotion_id matches).

    Returns:
        List of 4-tuples: (name, weight_class, promotion_name, record).
        - name:            fighters.first_name || ' ' || fighters.last_name
        - weight_class:    weight_classes.name, or 'Unknown' if no WC
        - promotion_name:  promotions.name, or 'Unassigned' if no
                           current promotion (i.e. a free agent)
        - record:          'W-L-D' string from fighter_career counters,
                           defaulting to '0-0-0' if no career row yet
    """
    sql = (
        "SELECT f.first_name || ' ' || f.last_name, "
        "COALESCE(w.name, 'Unknown'), "
        "COALESCE(p.name, 'Unassigned'), "
        "COALESCE(fc.record_wins, 0) || '-' || COALESCE(fc.record_losses, 0) || '-' || COALESCE(fc.record_draws, 0) "
        "FROM fighters f "
        "LEFT JOIN weight_classes w ON w.weight_class_id = f.weight_class_id "
        "LEFT JOIN promotions p ON p.promotion_id = f.current_promotion_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id"
    )
    if promotion_filter is not None:
        sql += " WHERE f.current_promotion_id = ?"
        sql += " ORDER BY f.fighter_id"
        return conn.execute(sql, (promotion_filter,)).fetchall()
    sql += " ORDER BY f.fighter_id"
    return conn.execute(sql).fetchall()


# ----------------------------------------------------------------
# Rankings display helper (Task ID 10).
#
# Returns the top-N fighters by ELO rating for a given promotion
# (optionally filtered by weight class). Used by the Rankings tab in
# the UI (third tab in the right-pane Notebook). The rank field is
# 1-indexed (rank 1 = highest rating). Ties are broken by
# fights_count DESC (more-active fighters rank higher), which is the
# same tiebreaker the ELO system uses implicitly (a fighter with the
# same rating but more fights has had more chances to move).
#
# Schema version is bumped 1.4.0 -> 1.5.0 in this task (the new
# `rankings` table is the only schema change).
# ----------------------------------------------------------------

def get_rankings_for_display(conn, promotion_id, weight_class_id=None, limit=10):
    """Return top N fighters by rating for a promotion.

    Args:
        conn: sqlite3 connection.
        promotion_id: the promotion whose rankings to return. If the
            promotion_id is invalid (no rows in `rankings` for it),
            returns an empty list — no crash.
        weight_class_id: if not None, filter to this weight class;
            else include all weight classes.
        limit: max number of rows to return. Default 10.

    Returns:
        List of 7-tuples:
        (rank, fighter_name, weight_class_name, rating_rounded_1dp,
         fights_count, 'W-L-D' string, last_fight_date_or_'N/A').
        - rank:                1-indexed int (1 = highest rating).
        - fighter_name:        fighters.first_name || ' ' || last_name.
        - weight_class_name:   weight_classes.name (always non-NULL
                              because rankings.weight_class_id is NOT
                              NULL with ON DELETE CASCADE).
        - rating_rounded_1dp:  float (rating rounded to 1 decimal).
        - fights_count:        int.
        - record string:       'W-L-D' from the rankings counters.
        - last_fight_date:     ISO date string or 'N/A' if NULL
                              (fighter has not fought yet).

        Ordered by rating DESC, fights_count DESC.
    """
    sql = (
        "SELECT r.rating, r.fights_count, r.wins, r.losses, r.draws, "
        "       r.last_fight_date, "
        "       f.first_name || ' ' || f.last_name AS fighter_name, "
        "       w.name AS weight_class_name "
        "FROM rankings r "
        "JOIN fighters f ON f.fighter_id = r.fighter_id "
        "LEFT JOIN weight_classes w ON w.weight_class_id = r.weight_class_id "
        "WHERE r.promotion_id = ?"
    )
    params = [promotion_id]
    if weight_class_id is not None:
        sql += " AND r.weight_class_id = ?"
        params.append(weight_class_id)
    sql += " ORDER BY r.rating DESC, r.fights_count DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    # Build the 7-tuple with 1-indexed rank and rounded rating.
    out = []
    for i, (rating, fights_count, wins, losses, draws,
            last_fight_date, fighter_name, wc_name) in enumerate(rows, start=1):
        record_str = f"{wins}-{losses}-{draws}"
        last_fight_display = last_fight_date if last_fight_date else "N/A"
        out.append((
            i,
            fighter_name,
            wc_name if wc_name else "Unknown",
            round(float(rating), 1),
            int(fights_count),
            record_str,
            last_fight_display,
        ))
    return out

# ----------------------------------------------------------------
# Beat-level fight engine (Task B1, schema v2.1.0).
#
# Replaces the single-resolution `_resolve_outcome()` from Task 3
# with a beat-level round simulation. A "beat" is one discrete
# exchange within a round. Each round generates 12-28 beats
# (pace-driven by the fighters' aggression + speed_explosiveness +
# cardio + discipline). Each beat's outcome is computed from the
# attributes relevant to its current phase (standing, clinch, cage,
# ground_top, ground_bottom, scramble). `fight_rounds` aggregate
# columns become computed sums over that round's `fight_beats` rows.
# After all scheduled rounds complete, decision scoring (10-point
# must, unanimous / split / draw) picks the fight winner.
#
# B1 does NOT have mid-round finishes (KO/submission). ALL fights go
# to decision. B2 will add fatigue, momentum, finishes, commentary
# beat selection.
#
# All existing side effects of `resolve_next_fight()` are PRESERVED
# (fight_history, rankings, titles, event lifecycle,
# schedule_next_event, news, commentary). Only the resolution
# mechanism changes — the `fights` table's winner_fighter_id /
# loser_fighter_id / result_type / finish_round / finish_time /
# performance_rating / fan_reaction_rating columns are populated
# exactly as before, just with decision-flavored values
# (result_type in {'unanimous_decision', 'split_decision', 'draw'},
# finish_round = scheduled_rounds, finish_time = '5:00').
#
# See docs/STAGES.md Stage 2.5 "Detailed task brief: B1" for the
# full brief and acceptance checklist. See
# docs/STAGE3_EXPANSION_PLAN.md Part 2 for the engine mechanics
# spec (beat count formula, phase-to-attribute mapping, phase
# transitions, decision scoring).
# ----------------------------------------------------------------

# The 25 combat attributes loaded per fighter. The first 4 are the
# original Task 3 attrs (preserved without CHECK constraints so
# existing tests can UPDATE them with arbitrary values); the other
# 22 are the v2.0.0 expansion attrs (CHECK 0-100). The beat engine
# reads all 25 — different phases use different subsets per the
# PHASE_ATTRS mapping below.



class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MMA Booking Sim")
        self.geometry("1280x760")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        # v3.0.0 (Task 23): register the news engine subscribers on
        # the global event bus. The news engine writes rich, voice-
        # layer-driven news items in response to FIGHT_RESOLVED,
        # TITLE_CHANGED, and TICK_ADVANCED events (CONVENTIONS §15.4
        # — additive, no inline side effects added to resolve_next_
        # fight). Lazy-import to avoid importing news at module load
        # (news.py imports voice + event_bus; keeping the import
        # inside __init__ means a missing news.py wouldn't break the
        # rest of the app for unrelated reasons). The register call
        # is idempotent at the bus level — subscribe() just appends
        # to a list; calling it multiple times would add duplicate
        # subscribers but App is only instantiated once per session.
        try:
            from news import register_subscribers as _register_news
            _register_news()
        except ImportError:
            pass  # news.py not available — legacy behavior
        # v3.1.0 (Task 21): register the social media subscribers on
        # the global event bus. The social system writes fighter
        # posts to the social_posts table in response to FIGHT_RESOLVED,
        # TITLE_CHANGED, and TICK_ADVANCED events (CONVENTIONS §15.4
        # — additive, no inline side effects added to resolve_next_
        # fight). Lazy-import for the same reasons as news.py above.
        try:
            from social import register_subscribers as _register_social
            _register_social()
        except ImportError:
            pass  # social.py not available — legacy behavior
        # v3.2.0 (Task 22): register the rivalries subscribers on the
        # global event bus. The rivalries system writes pairwise
        # rivalry records to the rivalries table in response to
        # FIGHT_RESOLVED (close decisions, weight cut misses, fights
        # between existing rivals), TITLE_CHANGED (title changes
        # hands → title_rivalry), and TICK_ADVANCED (accumulated
        # social_posts callouts/trash_talks spawn 'callout'
        # rivalries). All descriptions use voice descriptors per
        # CONVENTIONS §14 — no raw numbers. The fight engine
        # (resolve_next_fight in app.py) is NOT modified per the
        # brief — readers (get_rivalry, get_active_rivalries) are
        # provided for a future task to consume when wiring rivalry
        # heat into the beat engine (high heat → +aggression,
        # -composure modifiers). Lazy import for the same reasons as
        # news.py / social.py above.
        try:
            from rivalries import register_subscribers as _register_rivalries
            _register_rivalries()
        except ImportError:
            pass  # rivalries.py not available — legacy behavior
        # v3.3.0 (Task 24): register the punditry subscribers on the
        # global event bus. The punditry system writes matchup analyses
        # (the pundit's pre-fight prediction for a fighter pair) to the
        # matchup_analyses table in response to FIGHT_RESOLVED events
        # (CONVENTIONS §15.4 — additive, no inline side effects added
        # to resolve_next_fight). The analysis is generated
        # retroactively after the fight resolves — it describes the
        # pre-fight matchup, written for the news feed so the player
        # sees "here's what the pundits thought going in." All analysis
        # text uses voice descriptors per CONVENTIONS §14 — no raw
        # numbers in any analysis_text, style_edge, or upset_risk
        # string. Lazy import for the same reasons as news.py /
        # social.py / rivalries.py above.
        try:
            from punditry import register_subscribers as _register_punditry
            _register_punditry()
        except ImportError:
            pass  # punditry.py not available — legacy behavior
        # Phase A (Task A1+A10): register the morale + dynamic-fields
        # subscribers on the global event bus. The morale system
        # updates fighter_personality.morale (which the fight engine
        # reads via _load_fighter_stats) and the fighters.* meta-fields
        # (marketability, fan_friendliness, consistency, clutch_factor,
        # promo_boost, injury_proneness, weight_cut_difficulty) in
        # response to FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED,
        # CAMP_COMPLETED, CAMP_INJURY, and FIGHT_CANCELLED events
        # (CONVENTIONS §15.4 — additive, no inline side effects added
        # to resolve_next_fight or run_tick). Lazy import for the same
        # reasons as news.py / social.py / rivalries.py / punditry.py
        # above. Before this task, fighter_personality.morale was set
        # at seed time and never updated — breaking the dopamine loop
        # the Soul document mandates (wins boost morale → next fight
        # gets a boost → more wins). Now the loop is closed.
        try:
            from morale import register_subscribers as _register_morale
            _register_morale()
        except ImportError:
            pass  # morale.py not available — legacy behavior
        # v3.4.0 (Phase B): register the suspensions subscribers on
        # the global event bus. The suspensions system writes
        # `suspensions` rows in response to FIGHT_RESOLVED (random
        # drug-test / behavior trigger — rare events that generate
        # big stories per docs/FULL_BUILD_AUDIT.md §9a) and clears
        # them on TICK_ADVANCED (when end_date has passed). The
        # news engine writes the player-facing narrative via a
        # separate TICK_ADVANCED polling subscriber (news.
        # generate_suspension_news). app._pick_matchup reads the
        # suspensions table (SQL `NOT IN (SELECT fighter_id FROM
        # suspensions WHERE is_active = 1)`) to exclude suspended
        # fighters from booking — parallel to the existing injury
        # exclusion. CONVENTIONS §15.4 — additive, no inline side
        # effects added to resolve_next_fight or run_tick. Lazy
        # import for the same reasons as news.py / social.py /
        # rivalries.py / punditry.py / morale.py above.
        try:
            from suspensions import register_subscribers as _register_suspensions
            _register_suspensions()
        except ImportError:
            pass  # suspensions.py not available — legacy behavior
        # v3.5.0 (Phase C): register the agent offers subscribers on
        # the global event bus. The agent offers system writes
        # `agent_offers` rows in response to TICK_ADVANCED (weekly
        # 10% chance of generating a new offer for the player's
        # promotion — the "Talent Hunter" gamble per CAGE_EMPIRE_SOUL
        # Fantasy 1) and clears expired offers on every tick (offers
        # past their 14-day expiry are marked resolution='expired').
        # The resolve_offer helper is called directly by the UI when
        # the player clicks Accept/Reject — NOT a subscriber. The
        # news engine is NOT invoked on offer creation (the player
        # sees the offer in the UI directly — no narrative needed
        # for a "your agent calls you" moment). CONVENTIONS §15.4 —
        # additive, no inline side effects added to run_tick. Lazy
        # import for the same reasons as news.py / social.py /
        # rivalries.py / punditry.py / morale.py / suspensions.py
        # above. The fighter_description is built from voice-layer
        # descriptors (CONVENTIONS §14 — no raw attributes, potential,
        # or career state in any player-facing text).
        try:
            from agent_offers import register_subscribers as _register_agent_offers
            _register_agent_offers()
        except ImportError:
            pass  # agent_offers.py not available — legacy behavior
        # v3.6.0 (Stage 5 — Task 25 + Career Arc): register the
        # career arc + rival promotion AI subscribers on the global
        # event bus. The career arc system applies natural attribute
        # growth (age 18-27) and decline (age 30+) on monthly ticks
        # — closes the "frozen attributes" gap the user identified
        # (fighters grew only via camps and injuries, never naturally
        # over a career). The rival AI system runs booking loops for
        # every rival promotion (promotion_id != 1) on weekly ticks:
        # schedules events, resolves ONE fight per week per rival
        # promotion (spreads results for narrative pacing), and signs
        # free agents based on ai_aggression + ai_spending_style.
        # Both systems are entirely event-bus-driven (CONVENTIONS
        # §15.4 — no new inline side effects added to run_tick or
        # resolve_next_fight). The rival AI uses the EXISTING
        # schedule_next_event + resolve_next_fight (now with an
        # optional promotion_id parameter) + sign_free_agent
        # functions — so all the event bus subscribers (news, social,
        # morale, finance, punditry) fire for rival promotion fights
        # too, creating a living world across all promotions. Lazy
        # import for the same reasons as news.py / social.py /
        # rivalries.py / punditry.py / morale.py / suspensions.py /
        # agent_offers.py above.
        try:
            from career_arc import register_subscribers as _register_career_arc
            _register_career_arc()
        except ImportError:
            pass  # career_arc.py not available — legacy behavior
        try:
            from rival_ai import register_subscribers as _register_rival_ai
            _register_rival_ai()
        except ImportError:
            pass  # rival_ai.py not available — legacy behavior
        # v3.6.0 (Stage 5 — Task 26 + 27 Show rating + Venues deeper
        # simulation): register the show rating + venues subscribers
        # on the global event bus. The show rating system computes
        # fan / commercial / excitement / quality / overall ratings
        # after each event completes (EVENT_COMPLETED subscriber) and
        # writes a show_ratings row + a topic='show_rating' news item
        # with a voice-layer descriptor (CONVENTIONS §14 — no raw
        # numbers). The venues system reads fan_rating to adjust
        # market heat (successful events +2, poor events -1) and
        # drifts market heat on monthly ticks (hot markets cool
        # toward 70, cold markets warm toward 40). Both systems are
        # entirely event-bus-driven (CONVENTIONS §15.4 — no new
        # inline side effects added to resolve_next_fight or run_tick).
        # REGISTRATION ORDER MATTERS: show_rating must register
        # BEFORE venues so that on each EVENT_COMPLETED, the
        # show_ratings row is written before venues tries to read it.
        # Lazy import for the same reasons as news.py / social.py /
        # rivalries.py / punditry.py / morale.py / suspensions.py /
        # agent_offers.py / career_arc.py / rival_ai.py above.
        try:
            from show_rating import register_subscribers as _register_show_rating
            _register_show_rating()
        except ImportError:
            pass  # show_rating.py not available — legacy behavior
        try:
            from venues import register_subscribers as _register_venues
            _register_venues()
        except ImportError:
            pass  # venues.py not available — legacy behavior
        # v3.6.0 (Stage 5 — Task ID Stage5-SaveLoad): register the
        # save/load auto-save subscriber on the global event bus.
        # The auto_save subscriber fires on every TICK_ADVANCED and,
        # on every 30th sim day (monthly), writes a rotating backup
        # of the DB file to data/saves/autosave_*.db (keeping only
        # the last 3 — the "rotating" pattern). The save is SILENT
        # (no news item, no print — background operation per the
        # brief) and entirely event-bus-driven (CONVENTIONS §15.4 —
        # no new inline side effects added to run_tick). save_game
        # calls conn.commit() before shutil.copy2 so the auto-save
        # captures the post-tick state (run_tick commits AFTER
        # bus.publish; without this commit, the auto-save would
        # capture the pre-tick state). Lazy import for the same
        # reasons as news.py / social.py / rivalries.py / punditry.
        # py / morale.py / suspensions.py / agent_offers.py /
        # career_arc.py / rival_ai.py / show_rating.py / venues.py
        # above. This task adds NO new tables — the DB IS the save
        # state (per the brief). save_game + load_game + list_saves
        # + delete_save are the public API for manual save/load
        # (called by a future UI Save/Load panel).
        try:
            from save_load import register_subscribers as _register_save_load
            _register_save_load()
        except ImportError:
            pass  # save_load.py not available — legacy behavior
        # v3.7.0 (Stage 5 — Task Stage5-Final): register the player
        # settings module. The player_settings module is NOT event-
        # bus-driven — settings are read by other systems (news feed
        # filter, auto-save cadence, difficulty, voice descriptors
        # toggle) at their own cadence. register_subscribers is a
        # NO-OP, but we call it for parity with the 12 other
        # register_subscribers calls above (so App.__init__ has a
        # uniform "register every module" pattern). The player_
        # settings table is created by build_db.py's _migrate_v3_7_0
        # _add_player_settings + seeded with 6 defaults. CONVENTIONS
        # §15.4 — additive, no inline side effects added to run_tick
        # or resolve_next_fight. Lazy import for the same reasons as
        # the 12 modules above.
        try:
            from player_settings import register_subscribers as _register_player_settings
            _register_player_settings()
        except ImportError:
            pass  # player_settings.py not available — legacy behavior
        # v3.7.1 (FIX-VoiceRep): register the dynamic reputation
        # module. The reputation system wires the two "frozen field"
        # gaps in promotions.reputation + gyms.reputation — both
        # were set at seed time and never updated by game events.
        # Now: EVENT_COMPLETED → promotion rep (show rating based) +
        # bankruptcy check; TITLE_CHANGED → promo +1 + champ's gym
        # +3; FIGHT_RESOLVED → winner's gym +1, KO-loser's gym -1;
        # CAMP_COMPLETED → gym +0.5; TICK_ADVANCED → drug-test
        # scandal scan (promo -3 per drug_test_failure suspension).
        # All clamped to [10, 95]. Entirely event-bus-driven (§15.4
        # — no new inline side effects). REGISTRATION ORDER MATTERS:
        # this module must register AFTER show_rating, finance, and
        # suspensions so their rows exist before this module reads
        # them on the same event. The order above (show_rating →
        # venues → save_load → player_settings → reputation) places
        # this AFTER show_rating + finance + suspensions, so the
        # show_ratings row, finance transactions, and suspensions
        # rows are all written before this module's subscribers
        # fire. Lazy import for the same reasons as the 13 modules
        # above.
        try:
            from reputation import register_subscribers as _register_reputation
            _register_reputation()
        except ImportError:
            pass  # reputation.py not available — legacy behavior
        # Phase 1 — Fix 1.4: Hall of Fame induction subscriber.
        # Subscribes to FIGHTER_RETIRED and inducts qualifying
        # fighters into hall_of_fame. Without this, the 60 seeded
        # legends are the only HoF inductees forever — every champion
        # the player develops would be forgotten on retirement
        # (Historian fantasy collapse). Lazy import for the same
        # reasons as the 14 modules above.
        try:
            from services.hof_svc import register_subscribers as _register_hof_svc
            _register_hof_svc()
        except ImportError:
            pass  # services/hof_svc.py not available — legacy behavior
        # Promotion filter state (Task ID 6). None = all promotions
        # (including free agents with current_promotion_id = NULL);
        # an int = restrict the Fighters tree to that promotion_id.
        # Default is "All Promotions" so the UI opens showing every
        # fighter across every promotion.
        self.current_promotion_filter = None
        # Parallel list mapping the combobox's selected index to a
        # promotion_id (or None for the "All Promotions" sentinel).
        # Populated by refresh_all() alongside the combobox values.
        self._promo_filter_ids = [None]
        self.build_ui()
        self.refresh_all()

    def build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill='x')
        ttk.Button(top, text="Advance Day", command=self.on_advance_day).pack(side='left', padx=4)
        ttk.Button(top, text="Resolve Fight", command=self.on_resolve_fight).pack(side='left', padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side='left', padx=4)

        # Promotion filter (Task ID 6) — lets the player focus the
        # Fighters tree on one promotion's roster. None = all
        # promotions. Defaults to "All Promotions". The dropdown
        # values are refreshed from the DB on every refresh_all() call
        # so promotions added by future tasks (or removed via free-
        # agency, Task ID 13) are reflected automatically. The
        # current selection is preserved across refreshes if the
        # promotion still exists; otherwise it resets to "All".
        ttk.Label(top, text="Filter:").pack(side='left', padx=(12, 4))
        self.promo_filter_var = tk.StringVar()
        self.promo_filter_combo = ttk.Combobox(
            top, textvariable=self.promo_filter_var, state='readonly',
            width=22, values=["All Promotions"]
        )
        self.promo_filter_combo.current(0)
        # <<ComboboxSelected>> only fires on user interaction, not on
        # programmatic .set()/.current() calls — so calling refresh_all()
        # from inside the handler (which re-populates the combobox)
        # does NOT cause infinite recursion. Verified empirically by
        # the smoke test.
        self.promo_filter_combo.bind("<<ComboboxSelected>>", self.on_promo_filter_change)
        self.promo_filter_combo.pack(side='left', padx=4)

        self.clock_var = tk.StringVar()
        ttk.Label(top, textvariable=self.clock_var, font=("Segoe UI", 11, "bold")).pack(side='right')

        main = ttk.Panedwindow(self, orient='horizontal')
        main.pack(fill='both', expand=True, padx=8, pady=8)

        left = ttk.Frame(main, padding=6)
        center = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=2)
        main.add(center, weight=2)
        main.add(right, weight=2)

        ttk.Label(left, text="Fighters", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fighters = ttk.Treeview(left, columns=('name','wc','promo','record'), show='headings', height=16)
        for c,w in [('name',170),('wc',110),('promo',140),('record',100)]:
            self.fighters.heading(c, text=c.title())
            self.fighters.column(c, width=w, anchor='w')
        self.fighters.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(center, text="Events", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.events = ttk.Treeview(center, columns=('date','name','status'), show='headings', height=8)
        for c,w in [('date',110),('name',250),('status',120)]:
            self.events.heading(c, text=c.title())
            self.events.column(c, width=w, anchor='w')
        self.events.pack(fill='x', pady=(6,10))

        ttk.Label(center, text="Fights", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fights = ttk.Treeview(center, columns=('id','matchup','wc','result'), show='headings', height=10)
        for c,w in [('id',60),('matchup',260),('wc',110),('result',120)]:
            self.fights.heading(c, text=c.title())
            self.fights.column(c, width=w, anchor='w')
        self.fights.pack(fill='both', expand=True, pady=(6,0))

        # ----------------------------------------------------------------
        # Right pane: ttk.Notebook with two tabs (Task ID 9).
        #
        # Layout choice (worklog decision D1): the existing News + Commentary
        # Listboxes are moved into a "News & Commentary" tab, and a new
        # "Contracts" tab holds a read-only Treeview of the player's
        # promotion's active contracts. This preserves the 3-pane layout
        # (left=fighters / center=events+fights / right=notebook) while
        # adding the Contracts surface without taking screen real estate
        # away from News + Commentary. The Contracts tab respects the
        # same current_promotion_filter as the Fighters tree (Task ID 6)
        # so the player can scope the contracts list to a single promotion.
        # ----------------------------------------------------------------
        right_notebook = ttk.Notebook(right)
        right_notebook.pack(fill='both', expand=True)

        # Tab 1: News & Commentary (existing widgets, moved into the tab).
        news_tab = ttk.Frame(right_notebook)
        right_notebook.add(news_tab, text="News & Commentary")
        ttk.Label(news_tab, text="News", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.news = tk.Listbox(news_tab, height=14)
        self.news.pack(fill='both', expand=True, pady=(6, 0))
        ttk.Label(news_tab, text="Commentary", font=("Segoe UI", 11, "bold")).pack(anchor='w', pady=(10, 0))
        self.commentary = tk.Listbox(news_tab, height=6)
        self.commentary.pack(fill='both', expand=True, pady=(6, 0))

        # Tab 2: Contracts (new in Task ID 9). Read-only Treeview with
        # columns: contractor, type, start, end, salary, exclusive,
        # status. Populated by refresh_all() via get_contracts_for_display.
        contracts_tab = ttk.Frame(right_notebook)
        right_notebook.add(contracts_tab, text="Contracts")
        ttk.Label(contracts_tab, text="Active Contracts", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.contracts = ttk.Treeview(
            contracts_tab,
            columns=('contractor', 'type', 'start', 'end', 'salary', 'exclusive', 'status'),
            show='headings', height=18
        )
        for c, w in [('contractor', 150), ('type', 80), ('start', 90), ('end', 90),
                     ('salary', 80), ('exclusive', 70), ('status', 90)]:
            self.contracts.heading(c, text=c.title())
            self.contracts.column(c, width=w, anchor='w')
        self.contracts.pack(fill='both', expand=True, pady=(6, 0))

        # Tab 3: Rankings (new in Task ID 10). Read-only Treeview with
        # columns: rank, fighter, weight_class, rating, fights, record,
        # last_fight. Populated by refresh_all() via
        # get_rankings_for_display. When current_promotion_filter is
        # None ("All Promotions"), the rankings tab falls back to the
        # first promotion's rankings — the helper requires a
        # promotion_id and "all promotions' rankings combined" is not
        # meaningful under ELO (ratings are per-promotion). This
        # fallback is documented in refresh_all().
        rankings_tab = ttk.Frame(right_notebook)
        right_notebook.add(rankings_tab, text="Rankings")
        ttk.Label(rankings_tab, text="Top 10 by ELO Rating", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.rankings = ttk.Treeview(
            rankings_tab,
            columns=('rank', 'fighter', 'weight_class', 'rating', 'fights', 'record', 'last_fight'),
            show='headings', height=18
        )
        for c, w in [('rank', 50), ('fighter', 150), ('weight_class', 110),
                     ('rating', 70), ('fights', 60), ('record', 80), ('last_fight', 90)]:
            self.rankings.heading(c, text=c.title())
            self.rankings.column(c, width=w, anchor='w')
        self.rankings.pack(fill='both', expand=True, pady=(6, 0))

        # ----------------------------------------------------------------
        # Tab 4: Free Agents (new in Task ID 13). Shows fighters with
        # no current promotion (current_promotion_id IS NULL,
        # is_active=1, is_retired=0). The player can sign them to the
        # current promotion via the "Sign Selected" button. The Sign
        # button calls on_sign_free_agent() which calls
        # sign_free_agent() with the player's current promotion filter
        # (or the first promotion if "All Promotions" is selected).
        #
        # IMPORTANT: the Free Agents tab does NOT respect the promotion
        # filter — free agents are not bound to any promotion, so they're
        # available to sign with ANY promotion. The UI always shows all
        # free agents regardless of the current_promotion_filter dropdown.
        # This is intentional and documented (case I of test_free_agency).
        #
        # The Treeview item iid is the fighter_id (so the Sign button can
        # read it directly from tree.selection()[0] instead of doing a
        # fragile name lookup). The values are the remaining 4 fields:
        # (name, weight_class, record, age).
        # ----------------------------------------------------------------
        free_agents_tab = ttk.Frame(right_notebook)
        right_notebook.add(free_agents_tab, text="Free Agents")
        # Top row: label + Sign button.
        fa_top = ttk.Frame(free_agents_tab)
        fa_top.pack(fill='x', pady=(0, 4))
        ttk.Label(fa_top, text="Available Free Agents",
                  font=("Segoe UI", 11, "bold")).pack(side='left')
        self.sign_button = ttk.Button(
            fa_top, text="Sign Selected", command=self.on_sign_free_agent
        )
        self.sign_button.pack(side='right')
        # Treeview. The item iid is the fighter_id (set in refresh_all).
        self.free_agents = ttk.Treeview(
            free_agents_tab,
            columns=('name', 'weight_class', 'record', 'age'),
            show='headings', height=18
        )
        for c, w in [('name', 160), ('weight_class', 110),
                     ('record', 80), ('age', 50)]:
            self.free_agents.heading(c, text=c.title())
            self.free_agents.column(c, width=w, anchor='w')
        self.free_agents.pack(fill='both', expand=True, pady=(4, 0))

    def clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def refresh_all(self):
        row = get_clock(self.conn)
        self.clock_var.set(f"{row[0]} | Day {row[1]} | Week {row[2]} | Month {row[3]} | Year {row[4]} | Ticks {row[5]}")

        # ----------------------------------------------------------------
        # Refresh promotion filter dropdown from DB (Task ID 6).
        # Promotions may be added by future tasks (e.g. scout-driven
        # expansion) or removed (fighters become free agents, Task ID
        # 13). The dropdown is rebuilt on every refresh so it always
        # reflects the current DB state. The user's current selection
        # is preserved if the promotion still exists; otherwise the
        # filter resets to "All Promotions" so the UI never ends up
        # pointing at a deleted promotion_id.
        # ----------------------------------------------------------------
        current_selection = self.promo_filter_var.get() or "All Promotions"
        promo_names = ["All Promotions"]
        promo_ids = [None]  # parallel list: None for "All", else promotion_id
        for pid, pname in self.conn.execute(
            "SELECT promotion_id, name FROM promotions ORDER BY promotion_id"
        ):
            promo_names.append(pname)
            promo_ids.append(pid)
        self.promo_filter_combo['values'] = promo_names
        if current_selection in promo_names:
            # Re-select the same promotion the user had picked.
            # .set() does NOT fire <<ComboboxSelected>> (Tkinter only
            # fires that on user interaction), so no recursion here.
            self.promo_filter_combo.set(current_selection)
        else:
            self.promo_filter_combo.current(0)
            self.current_promotion_filter = None
        # Store the parallel id list so on_promo_filter_change can map
        # the combobox's selected index -> promotion_id.
        self._promo_filter_ids = promo_ids

        self.clear_tree(self.fighters)
        self.clear_tree(self.events)
        self.clear_tree(self.fights)
        self.clear_tree(self.contracts)
        self.clear_tree(self.rankings)
        self.clear_tree(self.free_agents)
        self.news.delete(0, tk.END)
        self.commentary.delete(0, tk.END)

        for r in get_fighters_for_display(self.conn, self.current_promotion_filter):
            self.fighters.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT event_date, event_name, status FROM events ORDER BY event_date"):
            self.events.insert('', 'end', values=r)

        for r in self.conn.execute("""
            SELECT f.fight_id,
                   COALESCE(a.first_name || ' ' || a.last_name, 'TBD') || ' vs ' || COALESCE(b.first_name || ' ' || b.last_name, 'TBD'),
                   COALESCE(w.name, 'Unknown'),
                   COALESCE(f.result_type, 'pending')
            FROM fights f
            LEFT JOIN fight_participants pa ON pa.fight_id=f.fight_id AND pa.corner='red'
            LEFT JOIN fight_participants pb ON pb.fight_id=f.fight_id AND pb.corner='blue'
            LEFT JOIN fighters a ON a.fighter_id=pa.fighter_id
            LEFT JOIN fighters b ON b.fighter_id=pb.fighter_id
            LEFT JOIN weight_classes w ON w.weight_class_id=f.weight_class_id
            ORDER BY f.fight_id
        """):
            self.fights.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT headline FROM news_items ORDER BY news_item_id DESC LIMIT 10"):
            self.news.insert(tk.END, r[0])
        for r in self.conn.execute("SELECT text FROM commentary_segments ORDER BY commentary_segment_id DESC LIMIT 10"):
            self.commentary.insert(tk.END, r[0])

        # Populate Contracts tab (Task ID 9). Uses the same promotion
        # filter as the Fighters tree - if a specific promotion is
        # selected, show only that promotion's contracts; else show all.
        for r in get_contracts_for_display(self.conn, self.current_promotion_filter):
            self.contracts.insert('', 'end', values=r)

        # Populate Rankings tab (Task ID 10). The helper requires a
        # promotion_id — when current_promotion_filter is None ("All
        # Promotions"), we fall back to the first promotion's
        # rankings. Cross-promotion combined rankings are not
        # meaningful under ELO (ratings are per-promotion); a future
        # task could add a pound-for-pound view that normalizes
        # across promotions, but that's out of scope for Task 10.
        if self.current_promotion_filter is not None:
            rankings_promo_id = self.current_promotion_filter
        else:
            # Fall back to the first promotion (lowest promotion_id).
            first_promo = self.conn.execute(
                "SELECT promotion_id FROM promotions ORDER BY promotion_id LIMIT 1"
            ).fetchone()
            rankings_promo_id = first_promo[0] if first_promo else None
        if rankings_promo_id is not None:
            for r in get_rankings_for_display(self.conn, rankings_promo_id):
                self.rankings.insert('', 'end', values=r)

        # Populate Free Agents tab (Task ID 13). The helper returns
        # 5-tuples (fighter_id, name, weight_class, record, age). The
        # fighter_id is used as the Treeview item iid (so the Sign
        # button can read it directly from tree.selection()[0] without
        # a fragile name lookup), and the remaining 4 fields are the
        # display values.
        #
        # IMPORTANT: the Free Agents tab does NOT respect the promotion
        # filter — free agents are not bound to any promotion, so
        # they're available to sign with ANY promotion. The UI always
        # shows all free agents regardless of the
        # current_promotion_filter dropdown. This is intentional and
        # documented (case I of test_free_agency).
        for r in get_free_agents_for_display(self.conn):
            # r is (fighter_id, name, wc, record, age). Use fighter_id
            # (str'd, since ttk Treeview iids are strings) as the iid.
            self.free_agents.insert(str(r[0]), 'end', values=r[1:])

    def on_promo_filter_change(self, event=None):
        """Handle promotion filter dropdown change (Task ID 6).

        Reads the combobox's currently selected index, looks up the
        corresponding promotion_id in the parallel `_promo_filter_ids`
        list (set by `refresh_all()` when the dropdown was last
        populated), stores it in `current_promotion_filter`, and
        triggers a full refresh — which re-runs the fighter query
        through `get_fighters_for_display` with the new filter applied.

        Index 0 is always "All Promotions" -> filter = None. Any
        other index maps to a promotion_id int.

        Note: `refresh_all()` re-populates the combobox as a side
        effect, but `<<ComboboxSelected>>` only fires on user
        interaction (not on programmatic `.set()`), so there is no
        infinite recursion here.
        """
        idx = self.promo_filter_combo.current()
        if idx <= 0:
            self.current_promotion_filter = None
        else:
            # Defensive: bounds-check against the parallel list. If
            # the combobox is somehow out of sync with the list (e.g.
            # refresh hasn't run yet), fall back to "All Promotions".
            if 0 <= idx < len(self._promo_filter_ids):
                self.current_promotion_filter = self._promo_filter_ids[idx]
            else:
                self.current_promotion_filter = None
        self.refresh_all()

    def on_advance_day(self):
        try:
            advance_day(self.conn)
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

    def on_resolve_fight(self):
        try:
            if resolve_next_fight(self.conn) is None:
                messagebox.showinfo("Resolve Fight", "No unresolved fights found.")
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

    def on_sign_free_agent(self):
        """Sign the selected free agent to the player's promotion (Task ID 13).

        Reads the selected Treeview item's iid (which is the fighter_id
        — see refresh_all()), determines the player's promotion (the
        current_promotion_filter if set, else the first promotion in
        the DB), reads the current sim date for the contract start, and
        calls sign_free_agent(). On success, commits, refreshes the UI,
        and shows a confirmation messagebox. On failure (fighter not a
        free agent, retired, etc.), shows an error messagebox and rolls
        back.

        The fighter_id-as-iid approach is cleaner than looking up the
        fighter by name (which would be fragile if names aren't unique
        — see worklog decision D1). The Treeview stores display values
        (name, wc, record, age) but the iid is the fighter_id.
        """
        selection = self.free_agents.selection()
        if not selection:
            messagebox.showinfo("Sign Free Agent", "Select a free agent first.")
            return
        # The iid is the fighter_id (str'd by Tkinter). Convert back to int.
        try:
            fighter_id = int(selection[0])
        except (ValueError, TypeError):
            messagebox.showerror(
                "Sign Free Agent",
                f"Could not parse fighter_id from selection {selection!r}.",
            )
            return

        # Determine the player's promotion. For now, use the current
        # promotion filter (if set), else the first promotion. A future
        # task will add a proper "player promotion" concept (Task 25 —
        # rival promotion AI implies the player IS one of the
        # promotions, not "all promotions").
        player_promo_id = self.current_promotion_filter
        if player_promo_id is None:
            first_promo = self.conn.execute(
                "SELECT promotion_id FROM promotions ORDER BY promotion_id LIMIT 1"
            ).fetchone()
            player_promo_id = first_promo[0] if first_promo else None
        if player_promo_id is None:
            messagebox.showerror(
                "Sign Free Agent",
                "No promotion available to sign to.",
            )
            return

        # Read the current sim date for the contract start. Uses
        # get_clock (line 17) — note this is affected by the pre-existing
        # D5 current_date quirk (bare SELECT current_date resolves to
        # the built-in date function), but for the UI this is
        # acceptable. The qualified-column fix is only applied to the
        # new get_free_agents_for_display helper.
        clock_row = get_clock(self.conn)
        start_date = clock_row[0] if clock_row else None
        if not start_date:
            messagebox.showerror(
                "Sign Free Agent",
                "Could not read current sim date from simulation_clock.",
            )
            return

        # Get the fighter's name for the confirmation messagebox.
        fighter_name_row = self.conn.execute(
            "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        fighter_name = (fighter_name_row[0]
                        if fighter_name_row
                        else f"Fighter {fighter_id}")

        try:
            contract_id = sign_free_agent(
                self.conn, fighter_id, player_promo_id, start_date
            )
            if contract_id is None:
                messagebox.showerror(
                    "Sign Free Agent",
                    f"Could not sign {fighter_name} (see console for details).",
                )
                return
            self.conn.commit()
            messagebox.showinfo(
                "Sign Free Agent",
                f"Signed {fighter_name} to a 12-month contract.",
            )
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    # PYWEBVIEW-BUILD: the CustomTkinter UI has been migrated to a
    # pywebview desktop app (src/app_web.py). The old CTk shell lived
    # in src/ui/app.py but has been archived to src/ui_legacy/app.py.
    # This file remains the home of the game-logic helpers (_vacate_
    # title_on_retirement, generate_fighter, _CAMP_FOCUS_ATTRS, etc.)
    # that tick_processor imports — but it is NO LONGER the user-
    # facing entry point.
    #
    # To launch the OLD tkinter App (legacy debugging only):
    #   python src/app.py --legacy
    # To launch the archived CTk shell (will likely fail — deps moved):
    #   python src/ui_legacy/app.py
    # To launch the NEW pywebview app (default):
    #   python src/app_web.py
    if "--legacy" in sys.argv:
        App().mainloop()
    else:
        # Delegate to the new pywebview entry point.
        from app_web import main as _web_main
        _web_main()
