"""CAGE EMPIRE Snapshot Cache (Phase 2 Task 2.1).

The orchestrator that runs the daily interpretation pass. Calls
sub-engines (context_engine, career_phase_engine, etc.) and writes
their output to *_descriptors cache tables.

Per CONVENTIONS §17.5:
  - Runs as a POST-COMMIT step in tick_processor.run_tick (NOT a
    subscriber). This avoids event-bus ordering hazards and keeps
    the simulation transaction fast.
  - Must complete in <1 second for 4450 fighters. Requires the
    bulk-load pattern (one SELECT, Python loop, executemany UPDATE)
    demonstrated by career_arc._process_career_arc().
  - Targeted single-fighter refreshes (refresh_fighter, called by
    the 4 event-bus subscribers) take <10ms each.

Per CONVENTIONS §17.1 + §17.3:
  - Office Mode UI reads from *_descriptors + daily_headlines ONLY.
  - The interpretation layer is the ONLY writer to those tables.
  - Simulation tables (fighters, fighter_attributes, events, fights,
    rankings, titles, contracts, etc.) are NEVER written to.

This module is the SKELETON — sub-engine calls are stubs initially.
Tasks 2.2-2.8 fill in the actual logic:
  Task 2.2  context_engine.compute_momentum/pressure/trajectory
  Task 2.3  career_phase_engine.compute_career_phase
  Task 2.4  narrative_families.classify_fighter
  Task 2.5  memory_engine (reader — does NOT write here)
  Task 2.6  headline_engine.generate_daily_headlines
  Task 2.7  legacy_engine.compute_legacy_state
  Task 2.8  gym_identity_engine.compute_gym_descriptor

Until those tasks land, the daily pass is a no-op that:
  - Updates interpretation_cache_meta with the build date + count.
  - Leaves the 4 new cache tables empty (gym_descriptors,
    promotion_descriptors, division_descriptors, daily_headlines).
  - Leaves the 6 new columns on fighter_descriptors NULL.
"""
import sqlite3


# ----------------------------------------------------------------
# Engine version — bumped when the interpretation layer's logic
# changes in a way that invalidates existing cache rows (e.g., a new
# narrative family is added, the momentum thresholds are retuned).
# On mismatch with interpretation_cache_meta.engine_version, the
# daily pass should rebuild all caches from scratch.
#
# v1.0.0 = the skeleton (Task 2.1). Subsequent tasks bump this when
# their logic lands:
#   - Task 2.2 (Context Engine): bump to 1.1.0
#   - Task 2.3 (Career Phase): bump to 1.2.0
#   - Task 2.4 (Narrative Families): bump to 1.3.0
#   - Task 2.6 (Headlines): bump to 1.4.0
#   - Task 2.7 (Legacy): bump to 1.5.0
#   - Task 2.8 (Gym Identity): bump to 1.6.0
# ----------------------------------------------------------------
# v1.1.0 — Task 2.2 (Context Engine) landed: compute_all_fighters /
# compute_single_fighter now write momentum + pressure columns. On
# first run after this code lands, the engine-version mismatch
# triggers a full cache rebuild (the 6 new columns start NULL).
# v1.2.0 — Task 2.3 (Career Phase Engine) landed: compute_all_
# career_phases / compute_single_phase now write career_phase. On
# first run after this code lands, the engine-version mismatch
# triggers a full cache rebuild (career_phase starts NULL).
ENGINE_VERSION = "1.2.0"


def run_daily_interpretation_pass(conn):
    """Run the full daily interpretation pass.

    Called from tick_processor.run_tick AFTER conn.commit() (per
    CONVENTIONS §17.5). Writes to fighter_descriptors (the 6 new
    columns added in v3.10.0), gym_descriptors, promotion_descriptors,
    division_descriptors, daily_headlines, and updates
    interpretation_cache_meta.

    Per CONVENTIONS §17: NEVER writes to simulation tables.

    Performance budget: <1 second for 4450 active fighters + 300 gyms
    + 10 promotions + 80 divisions + 4 headlines. Requires the bulk-
    load pattern (one SELECT, Python loop, executemany UPDATE) per
    career_arc._process_career_arc.

    Skeleton behavior (Task 2.1): the 5 sub-engine calls are stubs.
    Only interpretation_cache_meta is updated. The actual cache
    writes are added in Tasks 2.2-2.8.

    Args:
        conn: sqlite3.Connection. Caller has ALREADY committed the
            simulation transaction (run_tick commits at the end of
            each step). This function opens its OWN transaction via
            conn.commit() at the end — if it raises, the cache
            transaction is rolled back by sqlite3's context manager
            semantics (caller is responsible for cleanup).

    Returns:
        None. Side effect: cache tables updated + committed.
    """
    # Read the simulation date. Defensive — if simulation_clock is
    # somehow missing, fall back to today's wall-clock date so the
    # pass doesn't crash (the cache is still useful for testing).
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if row is None:
        # No simulation_clock row — this is a fresh/test DB. Use
        # today's date as a fallback (the cache is still useful for
        # UI development against test DBs).
        from datetime import date as _date
        current_date = _date.today().isoformat()
    else:
        current_date = row[0]

    # ----------------------------------------------------------------
    # 1. Fighter interpretation (bulk-load pattern).
    # ----------------------------------------------------------------
    # TODO (Tasks 2.2-2.4, 2.7): compute momentum, pressure,
    # career_phase, narrative_family, public_narrative, legacy_state
    # via the sub-engines and batch UPDATE fighter_descriptors.
    # For now, this is a stub — the 6 new columns stay NULL until
    # the sub-engines are implemented.
    _interpret_fighters(conn, current_date)

    # ----------------------------------------------------------------
    # 2. Gym interpretation.
    # ----------------------------------------------------------------
    # TODO (Task 2.8): gym_identity_engine.compute_gym_descriptor()
    # for every gym; batch UPSERT into gym_descriptors.
    _interpret_gyms(conn, current_date)

    # ----------------------------------------------------------------
    # 3. Promotion interpretation.
    # ----------------------------------------------------------------
    # TODO: compute prestige_desc, market_position_desc,
    # roster_quality_desc for every promotion; batch UPSERT into
    # promotion_descriptors.
    _interpret_promotions(conn, current_date)

    # ----------------------------------------------------------------
    # 4. Division interpretation.
    # ----------------------------------------------------------------
    # TODO: compute depth_desc + competitiveness_desc for every
    # (promotion, weight_class) pair; batch UPSERT into
    # division_descriptors.
    _interpret_divisions(conn, current_date)

    # ----------------------------------------------------------------
    # 5. Daily headlines.
    # ----------------------------------------------------------------
    # TODO (Task 2.6): headline_engine.generate_daily_headlines()
    # for the 4 MVP headline types (top_story, upset_of_week,
    # fastest_rising, biggest_fall); INSERT OR REPLACE into
    # daily_headlines.
    _generate_headlines(conn, current_date)

    # ----------------------------------------------------------------
    # 6. Update cache meta (always — even in skeleton mode).
    # ----------------------------------------------------------------
    # Records engine_version + last_built_date + last_built_fighter_
    # count. On next run, the daily pass compares engine_version to
    # detect logic changes that require a full cache rebuild.
    # ----------------------------------------------------------------
    fighter_count = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_active=1"
    ).fetchone()[0]
    conn.execute(
        "INSERT OR REPLACE INTO interpretation_cache_meta "
        "(meta_id, engine_version, last_built_date, "
        " last_built_fighter_count, updated_at) "
        "VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)",
        (ENGINE_VERSION, current_date, fighter_count),
    )
    conn.commit()


def refresh_fighter(conn, fighter_id):
    """Refresh a single fighter's snapshot (targeted, <10ms).

    Called by the 4 event-bus subscribers (FIGHT_RESOLVED,
    FIGHTER_RETIRED, TITLE_CHANGED, CONTRACT_EXPIRED) registered in
    interpretation/__init__.py.

    Skeleton behavior (Task 2.1): calls the EXISTING
    update_fighter_descriptor_snapshot() (from services/fight_engine)
    which refreshes the 6 base descriptor columns
    (attribute_descriptors, personality_descriptors, career_stage,
    career_health_desc, overall_desc, potential_desc). The 6 NEW
    Phase 2 columns (momentum, pressure, career_phase,
    narrative_family, public_narrative, legacy_state) are NOT
    recomputed by this skeleton — they will be added when the
    Context Engine (Task 2.2) lands. Until then, they stay NULL
    between daily passes.

    The caller (event-bus dispatch) does NOT commit; this function
    commits its own work so the refresh is durable immediately
    (the player may view the fighter profile right after a fight
    resolves, before the next daily pass).

    Args:
        conn: sqlite3.Connection.
        fighter_id: the fighter whose snapshot to refresh.

    Returns:
        None. Side effect: fighter_descriptors row updated + committed.
    """
    # Lazy import to avoid a circular dependency at module load
    # (services.fight_engine imports voice, which imports a lot).
    from services.fight_engine import update_fighter_descriptor_snapshot
    update_fighter_descriptor_snapshot(conn, fighter_id)

    # Task 2.2 — refresh momentum + pressure for this single fighter.
    # Called BEFORE the commit so the descriptor snapshot + the
    # context labels land in the same transaction. If the context
    # engine isn't available (older code), this silently no-ops.
    # Defensive — a single failed context refresh must not roll back
    # the descriptor snapshot written above.
    try:
        from interpretation.context_engine import compute_single_fighter
        compute_single_fighter(conn, fighter_id)
    except ImportError:
        pass  # Task 2.2 not landed yet — no-op.
    except Exception as e:
        import sys
        print(f"WARNING: context_engine.compute_single_fighter("
              f"fighter_id={fighter_id}) failed in refresh_fighter: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # Task 2.3 — refresh career_phase for this single fighter.
    # Same try/except pattern as the context_engine block above —
    # a single failed phase refresh must not roll back the work
    # already done. If the career_phase engine isn't available
    # (older code), this silently no-ops.
    try:
        from interpretation.career_phase_engine import compute_single_phase
        compute_single_phase(conn, fighter_id)
    except ImportError:
        pass  # Task 2.3 not landed yet — no-op.
    except Exception as e:
        import sys
        print(f"WARNING: career_phase_engine.compute_single_phase("
              f"fighter_id={fighter_id}) failed in refresh_fighter: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    conn.commit()


# ----------------------------------------------------------------
# Sub-engine dispatchers (stubs for Task 2.1).
#
# Each function is the SINGLE entry point for its sub-engine within
# the daily pass. Sub-engines are lazy-imported so the skeleton
# doesn't fail to load when the sub-engine modules don't exist yet
# (they're created in Tasks 2.2-2.8).
# ----------------------------------------------------------------

def _interpret_fighters(conn, current_date):
    """Bulk-load all active fighters, compute interpretation, batch UPDATE.

    Per CONVENTIONS §17.5 + PHASE_2_PLAN.md §7, this MUST use the
    bulk-load pattern:
      1. One SELECT (fighters JOIN fighter_career JOIN rankings JOIN
         contracts) → fetch all 4450 rows.
      2. Python loop computing momentum / pressure (pure CPU, no DB
         calls inside the loop).
      3. executemany("UPDATE fighter_descriptors SET ...") → batch
         write.

    Task 2.2 (Context Engine) lands the momentum + pressure compute.
    career_phase / narrative_family / public_narrative / legacy_state
    remain NULL until Tasks 2.3, 2.4, 2.7 land. The stubs for those
    are added below as separate try/except blocks (each sub-engine
    is independently optional — no ImportError crashes the pass).
    """
    # Task 2.2 — momentum + pressure.
    try:
        from interpretation.context_engine import compute_all_fighters
        compute_all_fighters(conn, current_date)
    except ImportError:
        pass  # Task 2.2 not landed yet — no-op.
    # Task 2.3 — career_phase (stub until Task 2.3 lands).
    try:
        from interpretation.career_phase_engine import compute_all_career_phases
        compute_all_career_phases(conn, current_date)
    except ImportError:
        pass
    # Task 2.4 — narrative_family + public_narrative (stub until 2.4).
    try:
        from interpretation.narrative_families import classify_all_fighters
        classify_all_fighters(conn, current_date)
    except ImportError:
        pass
    # Task 2.7 — legacy_state (stub until Task 2.7 lands).
    try:
        from interpretation.legacy_engine import compute_all_legacy_states
        compute_all_legacy_states(conn, current_date)
    except ImportError:
        pass


def _interpret_gyms(conn, current_date):
    """Compute gym identity summaries.

    Skeleton (Task 2.1): no-op. The gym_descriptors table stays empty
    until Task 2.8 (gym_identity_engine) lands.
    """
    try:
        from interpretation.gym_identity_engine import compute_all_gym_descriptors
    except ImportError:
        return  # Task 2.8 not landed yet — skeleton no-op.
    compute_all_gym_descriptors(conn, current_date)


def _interpret_promotions(conn, current_date):
    """Compute promotion summaries.

    Skeleton (Task 2.1): no-op. The promotion_descriptors table stays
    empty until the promotion-descriptor sub-engine lands (no task
    explicitly assigned — may ship as part of Task 2.6 or as a
    follow-up).
    """
    try:
        from interpretation.promotion_engine import compute_all_promotion_descriptors
    except ImportError:
        return  # sub-engine not landed yet — skeleton no-op.
    compute_all_promotion_descriptors(conn, current_date)


def _interpret_divisions(conn, current_date):
    """Compute division (promotion × weight class) summaries.

    Skeleton (Task 2.1): no-op. The division_descriptors table stays
    empty until the division-descriptor sub-engine lands.
    """
    try:
        from interpretation.division_engine import compute_all_division_descriptors
    except ImportError:
        return  # sub-engine not landed yet — skeleton no-op.
    compute_all_division_descriptors(conn, current_date)


def _generate_headlines(conn, current_date):
    """Generate daily headlines.

    Skeleton (Task 2.1): no-op. The daily_headlines table stays empty
    until Task 2.6 (headline_engine) lands.
    """
    try:
        from interpretation.headline_engine import generate_daily_headlines
    except ImportError:
        return  # Task 2.6 not landed yet — skeleton no-op.
    generate_daily_headlines(conn, current_date)
