import sqlite3
import json
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta

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


if __name__ == "__main__":
    # PYWEBVIEW-BUILD: the CustomTkinter UI has been migrated to a
    # pywebview desktop app (src/app_web.py). This file remains the
    # home of the game-logic helpers (_vacate_title_on_retirement,
    # generate_fighter, _CAMP_FOCUS_ATTRS, etc.) that tick_processor
    # imports — but it is NO LONGER the user-facing entry point.
    #
    # NEWS-FINANCE-GYM-LEGACY Issue 9 — the legacy Tkinter UI
    # (src/ui_legacy/) has been removed entirely. The web UI
    # (src/app_web.py + src/web/) is the only UI; it has full
    # save/load support via the save_game / load_game API methods.
    # To launch the game:
    #   python src/app_web.py
    # Delegate to the pywebview entry point.
    from app_web import main as _web_main
    _web_main()
