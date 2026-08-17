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
# v1.3.0 — Task 2.4 (Narrative Families) landed: compute_all_
# families / compute_single_family now write narrative_family. On
# first run after this code lands, the engine-version mismatch
# triggers a full cache rebuild (narrative_family starts NULL).
# v1.4.0 — Task 2.7 (Legacy Engine) landed: compute_all_legacies /
# compute_single_legacy now write legacy_state. On first run after
# this code lands, the engine-version mismatch triggers a full
# cache rebuild (legacy_state starts NULL).
# v1.5.0 — Task 2.6 (Headline Engine) landed: generate_daily_headlines
# now writes 4 daily headlines (top_story, upset_of_week,
# fastest_rising, biggest_fall) to the daily_headlines table. The
# headlines are derived from fighter_descriptors, so they're only as
# fresh as the last daily pass — they're regenerated on every daily
# pass via INSERT OR REPLACE (idempotent — re-running for the same
# date overwrites, doesn't duplicate). The Memory Engine (Task 2.5)
# is a reader called on-demand (when a fight is booked), NOT wired
# into the daily pass — it doesn't write to any cache table.
#
# Phase 0 (UI Redesign Rev 3, 2026-07-30): bumped 1.5.0 → 1.6.0 to
# force a full cache rebuild on the next daily pass. Per the
# Interpretation Layer Audit (docs/UI_REDESIGN_INTERPRETATION_AUDIT.md),
# the _EXT 8-variant pickers (commit 1149538) were added without
# bumping ENGINE_VERSION, so the version-mismatch rebuild logic never
# triggered — the production DB still held the original 3-variant
# picker output. This bump cuts perceived repetition ~60% for
# momentum / pressure / career_phase (the heaviest-bucket columns).
# No schema change required — the rebuild just re-runs the existing
# _EXT pickers and overwrites the stale cache rows. Idempotent.
#
# VOICE-P2 (Claude VOICE_ENFORCEMENT §3 + §5.3, 2026-10-18): bumped
# 1.6.0 → 1.7.0 to force another full cache rebuild. The legacy_engine
# + narrative_families modules now ship LEGACY_PHRASES_EXT and
# FAMILY_PHRASES_EXT banks (8 variants per label, vs the original 3).
# Without this bump, the version-mismatch rebuild logic won't trigger
# and the production DB will keep shipping the 3-variant phrases
# (verified live: legacy_state has 3 distinct phrases per label,
# narrative_family has 2-3, vs Claude's §3 bar of ≥8). This bump
# cuts perceived repetition another ~60% for legacy_state + narrative_
# family (the two columns still on the 3-variant original pickers).
# No schema change required. Idempotent.
#
# INTERP-EXPAND-V2 (Claude VOICE_ENFORCEMENT §3 + §5.3, 2026-12-04):
# bumped 1.7.0 → 1.8.0 to force ANOTHER full cache rebuild. This task
# ships:
#   1. 5 new SHORT-variant columns on fighter_descriptors
#      (momentum_short, pressure_short, career_phase_short,
#      narrative_family_short, legacy_state_short) — schema v3.15.0.
#   2. 4 new SHORT phrase banks (MOMENTUM_PHRASES_SHORT,
#      PRESSURE_PHRASES_SHORT, PHASE_PHRASES_SHORT,
#      FAMILY_PHRASES_SHORT, LEGACY_PHRASES_SHORT) with 8 ≤25-char
#      variants per label, for Fighter Watch Cards (the LONG _EXT
#      phrases were getting clipped at 35-65 chars).
#   3. Show rating descriptions expanded 5 → 8 per tier (5 tiers × 8
#      = 40 distinct descriptions, was 5).
#   4. News headline templates expanded for top 5 topics
#      (news_engine, career_arc, weight_cut, injury, training) —
#      each from 1-6 templates → 8+ templates.
# Without this bump, the version-mismatch rebuild logic won't trigger
# and the production DB will keep shipping the LONG-only phrases (no
# SHORT columns populated) + the 5-variant show_rating descriptions
# + the lower-template-count news headlines. This bump forces all
# 4450 active fighters + 60 retired legends to be re-interpreted
# with the new SHORT pickers, populating the 5 new columns in one go.
# Schema change REQUIRES the v3.15.0 migration to land first — the
# migration is in build_db._migrate_v3_15_0_add_fighter_descriptor_
# short_columns.
#
# CR-12 (Career-phase pyramid rebalance, 2027-01 — see docs/CR10_14_
# FIX_PLAN §3): bumped 1.8.0 → 1.9.0 to force a full cache rebuild.
# The career_phase_engine D4 priority-order thresholds were relaxed
# (declining: age 33→32 / ls 3→2 / health 50→60; prospect: age <24
# →<26 / fights <10→<12; veteran: age 35→32 / fights 20→12; gate-
# keeper: age 30→28 / fights 15→10 / win_rate <0.50→<0.55). Without
# this bump the production DB would keep shipping the stale career_
# phase values from the audit baseline (76.1% rising_contender,
# 0.6% veteran, 0.5% gatekeeper, 0.3% declining) instead of the
# relaxed-threshold pyramid (~40-50% rising_contender, ~15-20%
# veteran, ~12-18% gatekeeper, ~8-12% declining, ~10-15% prospect,
# ~2-3% champion). career_phase_short is derived from the same
# label + RNG seed so it's also stale — both columns rebuild on
# the next daily pass. Idempotent. No schema change required.
#
# ENGINE_VERSION coordination note (Subagent G — CR-10): Subagent G
# is also expected to bump ENGINE_VERSION (for the attribute re-seed
# in CR-10). As of this commit, G has NOT bumped yet (last commit
# on main: 081972c, ENGINE_VERSION was 1.8.0). If G commits a bump
# after this one, the supervisor resolves any merge conflict —
# whoever's bump lands SECOND becomes the active version + the
# earlier bump's rebuild is subsumed (the rebuild is idempotent).
# The career_phase + attribute_descriptors caches will both rebuild
# on the next daily pass after whichever bump lands last.
#
# CR-10 G.4 (Training-camp re-seed, 2027-01 — see docs/CR10_14_FIX_
# PLAN §1.3): the v3.20.0 migration re-seeded all 26 fighter_
# attributes columns down by 15 (clamp at 25) for active fighters.
# The attribute_descriptors cache column in fighter_descriptors is
# STALE — it references the pre-reseed (higher) attribute values.
# A full cache rebuild is required to regenerate descriptors from
# the post-reseed attributes.
#
# Per docs/CR10_14_FIX_PLAN.md §6, "snapshot_cache.py has ONE
# ENGINE_VERSION constant. Whoever commits first bumps it; the
# second subagent sees the new version + doesn't need to bump
# again." Subagent I (CR-12) committed first (commit afc2166) +
# bumped 1.8.0 → 1.9.0. This 1.9.0 bump is SUFFICIENT for CR-10's
# cache-rebuild requirement too — the daily interpretation pass
# rebuilds ALL descriptor columns (career_phase, career_phase_short,
# attribute_descriptors, momentum, etc.) on a single version
# mismatch. No further bump is needed here; the G.4 deliverable is
# satisfied by Subagent I's CR-12 bump. This comment block documents
# the G.4 acceptance: the cache will rebuild on the next daily pass
# after the v3.20.0 migration runs, regenerating attribute_descriptors
# from the freshly-lowered attribute values.
#
# PHASE6-A1 (Gym Identity Engine, 2026-08-17 — see docs/PHASE6_PLAN.md
# Task A1): bumped 1.9.0 → 1.10.0 to force a full cache rebuild on the
# next daily pass. The gym_identity_engine has LANDED — it populates
# the gym_descriptors cache table (previously 0 rows) with 5 voice-
# phrase fields per gym (identity_label, known_for, produces,
# weakness, development_rating_desc). Without this bump, the version-
# mismatch rebuild logic won't trigger + the gym_descriptors table
# stays empty (Fix #4 — gyms screen HIGH violation — can't ship until
# the cache is populated). The bump also rebuilds the fighter_descriptors
# cache (already populated — the rebuild is idempotent + correct),
# regenerating any descriptors derived from gym identity (none today,
# but future engine revisions may add such cross-references). No
# schema change required — gym_descriptors was created in v3.10.0
# (Task 2.1) + has just been empty until now.
ENGINE_VERSION = "1.10.0"


# ----------------------------------------------------------------
# TICK-REENGINEER (Fix 1) — Dirty-fighter tracking.
#
# Module-level set of fighter_ids whose interpretation cache rows
# were invalidated by an event (FIGHT_RESOLVED, FIGHTER_SIGNED,
# FIGHTER_RETIRED, INJURY_RECOVERED, TITLE_CHANGED, CONTRACT_
# EXPIRED) since the last daily pass. The 4 event-bus subscribers
# in interpretation/__init__.py call refresh_fighter(conn, fid)
# immediately (per-event refresh — the cache is updated in-step
# with the simulation transaction). They ALSO call mark_fighter_
# dirty(fid) so the next daily pass knows the fighter was touched.
#
# On the daily pass (run_daily_interpretation_pass), the dirty set
# is consumed:
#   - Non-weekly tick + dirty set non-empty → targeted refresh of
#     only those fighters (the per-event refresh already did the
#     work, but this is a safety-net re-refresh to catch anything
#     the event path missed due to a transient error).
#   - Weekly tick (current_day % 7 == 0) OR engine_version mismatch
#     OR meta row missing → full rebuild (the existing 4 450-fighter
#     pass). Catches anything the per-event path missed across the
#     whole week.
#
# The dirty set is cleared at the end of every daily pass.
#
# Performance impact (PERF_ARCH_AUDIT §4.5): the full pass costs
# ~333 ms / tick. The targeted path costs ~5-15 ms / tick (5-20
# fighters × 0.7 ms). On weekly ticks the full pass still runs
# (~333 ms once every 7 ticks = ~47 ms amortized), so the average
# per-tick interpretation cost drops from 333 ms → ~55 ms — a 6×
# improvement on the post-commit step.
# ----------------------------------------------------------------
_dirty_fighters: set[int] = set()


# ----------------------------------------------------------------
# TIER1-365DAY (2027-02) — Dirty-for-rebuild tracking.
#
# SEPARATE from _dirty_fighters above. This set tracks fighters
# whose ATTRIBUTES changed in a way that crossed a voice-tier
# boundary during the monthly career_arc pass (tier_crossed=True
# or pers_tier_crossed=True in career_arc._process_career_arc).
# These fighters need a full interpretation refresh on the next
# weekly rebuild — but the OTHER 4400+ fighters whose attributes
# didn't cross a tier boundary don't.
#
# Why a separate set? _dirty_fighters is consumed on EVERY daily
# pass (targeted refresh). _fighters_dirty_for_rebuild is consumed
# ONLY on the weekly rebuild tick. The weekly tick used to call
# _interpret_fighters (ALL 4450 fighters, ~333ms). Now it calls
# _interpret_dirty_fighters (only the dirty-for-rebuild subset,
# typically 50-200 fighters, ~15-50ms). This drops the weekly-tick
# interpretation cost by ~10×.
#
# The set is cleared at the end of every weekly dirty rebuild.
# Engine-version-mismatch rebuilds still do the TRUE full rebuild
# (all 4450 fighters) — those are rare (only when ENGINE_VERSION
# is bumped).
# ----------------------------------------------------------------
_fighters_dirty_for_rebuild: set[int] = set()


def mark_fighter_dirty(fighter_id: int) -> None:
    """Mark a fighter as needing re-interpretation on the next daily pass.

    Called by the event-bus subscribers in interpretation/__init__.py
    (FIGHT_RESOLVED, FIGHTER_SIGNED, FIGHTER_RETIRED, INJURY_RECOVERED,
    TITLE_CHANGED, CONTRACT_EXPIRED). The subscriber ALSO calls
    refresh_fighter(conn, fighter_id) immediately — the dirty-set
    entry is a safety-net backstop so the next daily pass can
    re-refresh the fighter (in case the per-event refresh missed
    something due to a transient error or because the cache meta
    row is being recomputed).
    """
    if fighter_id is None:
        return
    try:
        _dirty_fighters.add(int(fighter_id))
    except (TypeError, ValueError):
        pass  # defensive — non-int fighter_id silently ignored


def mark_fighter_dirty_for_rebuild(fighter_id: int) -> None:
    """Mark a fighter as needing re-interpretation on the next WEEKLY
    rebuild tick.

    TIER1-365DAY (2027-02): called by career_arc._process_career_arc
    when a fighter's attribute change crossed a voice-tier boundary
    (tier_crossed=True or pers_tier_crossed=True). The weekly
    rebuild tick (current_day % 7 == 0) used to rebuild ALL 4450
    active fighters (~333ms). Now it rebuilds only the dirty-for-
    rebuild subset (typically 50-200 fighters, ~15-50ms).

    Distinct from mark_fighter_dirty (which targets the DAILY pass).
    Both can be called for the same fighter — the daily refresh
    re-touches the fighter immediately, the weekly rebuild re-
    refreshes them again as a safety net (catches any drift between
    the daily refresh and the bulk career-arc changes that landed
    later in the month).
    """
    if fighter_id is None:
        return
    try:
        _fighters_dirty_for_rebuild.add(int(fighter_id))
    except (TypeError, ValueError):
        pass  # defensive — non-int fighter_id silently ignored


def clear_dirty_fighters() -> None:
    """Clear the dirty-fighter set.

    Called at the end of run_daily_interpretation_pass (the daily
    pass has either re-refreshed each dirty fighter via the targeted
    path, OR done a full rebuild which subsumes them). Also exposed
    publicly so tests can reset state between runs.
    """
    _dirty_fighters.clear()


def clear_fighters_dirty_for_rebuild() -> None:
    """Clear the dirty-for-rebuild set.

    Called at the end of _interpret_dirty_fighters (the weekly dirty
    rebuild has re-refreshed each fighter in the set). Also exposed
    publicly so tests can reset state between runs.
    """
    _fighters_dirty_for_rebuild.clear()


def get_dirty_fighter_count() -> int:
    """Return the current size of the dirty-fighter set (for diagnostics)."""
    return len(_dirty_fighters)


def get_fighters_dirty_for_rebuild_count() -> int:
    """Return the current size of the dirty-for-rebuild set (for diagnostics)."""
    return len(_fighters_dirty_for_rebuild)


def _should_full_rebuild(conn, current_date: str) -> bool:
    """Decide whether the daily pass should do a full 4 450-fighter rebuild
    or a targeted refresh of only the dirty fighters.

    Returns True (full rebuild) when ANY of:
      1. The interpretation_cache_meta row is missing (fresh DB or
         first run after a schema reset — every fighter's cache row
         starts NULL and must be populated).
      2. The cached engine_version != snapshot_cache.ENGINE_VERSION
         (the interpretation logic changed — every cache row is
         stale and must be recomputed with the new logic).
      3. The simulation_clock.current_day is a multiple of 7 — the
         weekly re-baseline. Catches anything the per-event refresh
         path missed across the whole week (per PERF_ARCH_AUDIT §4.5).

    Returns False (targeted refresh only) otherwise — the per-event
    subscribers have already refreshed the dirty fighters, and the
    daily pass just needs to re-touch them as a safety net + write
    fresh headlines + meta.

    Args:
        conn: sqlite3.Connection.
        current_date: ISO date string for the current sim day.

    Returns:
        bool — True for full rebuild, False for targeted refresh.
    """
    # 1. + 2. — engine_version mismatch (covers "meta row missing"
    # because a missing row returns None, which != ENGINE_VERSION).
    try:
        row = conn.execute(
            "SELECT engine_version, current_day "
            "FROM interpretation_cache_meta, simulation_clock "
            "WHERE interpretation_cache_meta.meta_id=1 "
            "AND simulation_clock.clock_id=1"
        ).fetchone()
    except sqlite3.Error:
        # Defensive — if either table is missing (shouldn't happen
        # post-v3.10.0), default to full rebuild.
        return True
    if row is None or row[0] is None or row[0] != ENGINE_VERSION:
        return True

    # 3. — weekly re-baseline (current_day % 7 == 0). On day 0
    # (before any tick has run), the modulo is 0 too — but day 0
    # also has no meta row, so case 1 already returned True above.
    current_day = row[1]
    if current_day is None:
        return True
    try:
        if int(current_day) % 7 == 0:
            return True
    except (TypeError, ValueError):
        return True

    return False


def _is_engine_version_mismatch(conn) -> bool:
    """Return True iff the cached engine_version != ENGINE_VERSION
    (or the interpretation_cache_meta row is missing).

    TIER1-365DAY (2027-02): used by run_daily_interpretation_pass to
    distinguish between the two flavors of "full rebuild":
      - Engine-version mismatch (or missing meta row) → TRUE full
        rebuild of ALL 4450 active fighters via _interpret_fighters.
        Rare — only fires when ENGINE_VERSION is bumped or on a
        fresh DB. Cost ~333ms.
      - Weekly tick (current_day % 7 == 0) but engine_version
        matches → DIRTY rebuild of only fighters in the
        _fighters_dirty_for_rebuild set via _interpret_dirty_
        fighters. Common — fires once every 7 ticks. Cost ~15-50ms.

    _should_full_rebuild returns True for EITHER case. This helper
    disambiguates: returns True iff the cause was an engine-version
    mismatch (or missing meta row). Returns False otherwise —
    meaning _should_full_rebuild returned True because of the
    weekly-tick check (case 3 in _should_full_rebuild).

    Args:
        conn: sqlite3.Connection.

    Returns:
        bool — True if cached engine_version != ENGINE_VERSION or
        meta row missing; False otherwise.
    """
    try:
        row = conn.execute(
            "SELECT engine_version "
            "FROM interpretation_cache_meta "
            "WHERE interpretation_cache_meta.meta_id=1"
        ).fetchone()
    except sqlite3.Error:
        # Defensive — table missing → treat as mismatch (force
        # full rebuild to repopulate the cache from scratch).
        return True
    if row is None or row[0] is None or row[0] != ENGINE_VERSION:
        return True
    return False


def run_daily_interpretation_pass(conn):
    """Run the daily interpretation pass.

    Called from tick_processor.run_tick AFTER conn.commit() (per
    CONVENTIONS §17.5). Writes to fighter_descriptors (the 6 new
    columns added in v3.10.0), gym_descriptors, promotion_descriptors,
    division_descriptors, daily_headlines, and updates
    interpretation_cache_meta.

    Per CONVENTIONS §17: NEVER writes to simulation tables.

    TICK-REENGINEER (Fix 1, PERF_ARCH_AUDIT §4.5): the pass now has
    two modes — full rebuild and targeted refresh. See
    _should_full_rebuild() for the decision logic. On non-weekly
    ticks (the common case), only the dirty fighters (those touched
    by an event-bus subscriber since the last pass) are re-refreshed
    — typically 5-20 fighters instead of all 4 450. This drops the
    per-tick interpretation cost from ~333 ms → ~10-15 ms (a 25×
    improvement on the post-commit step).

    Performance budget:
      - Full rebuild: <1 second for 4 450 active fighters + 300 gyms
        + 10 promotions + 80 divisions + 4 headlines. Uses the
        bulk-load pattern (one SELECT, Python loop, executemany
        UPDATE) per career_arc._process_career_arc.
      - Targeted refresh: <50 ms for ~20 dirty fighters (refresh_
        fighter is ~0.7 ms each) + headlines + meta.

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
    # 1. Fighter interpretation.
    # ----------------------------------------------------------------
    # TICK-REENGINEER (Fix 1): pick the mode.
    #   - Full rebuild: re-run all 4 sub-engines across all 4 450
    #     fighters. Expensive (~333 ms) but catches anything the
    #     event-driven path missed.
    #   - Targeted refresh: re-run refresh_fighter on the dirty
    #     set only. Cheap (~10-15 ms) and correct because the per-
    #     event subscribers already did the heavy lifting.
    # Either way, the daily_headlines + meta rows are updated below.
    #
    # TIER1-365DAY (2027-02): the "full rebuild" branch is now
    # further split:
    #   - TRUE full rebuild (engine_version mismatch or missing meta
    #     row) → _interpret_fighters (ALL 4450 fighters, ~333ms).
    #     Rare — fires only when ENGINE_VERSION is bumped or on a
    #     fresh DB.
    #   - WEEKLY dirty rebuild (current_day % 7 == 0, engine_version
    #     matches) → _interpret_dirty_fighters (only fighters in
    #     _fighters_dirty_for_rebuild, ~15-50ms). Common — fires
    #     once every 7 ticks. The dirty-for-rebuild set is populated
    #     by career_arc._process_career_arc when a fighter's attribute
    #     change crossed a voice-tier boundary (tier_crossed=True or
    #     pers_tier_crossed=True). The other ~4400 fighters whose
    #     attributes didn't cross a tier boundary don't need a refresh
    #     (their cached descriptors are still valid).
    full_rebuild = _should_full_rebuild(conn, current_date)
    if full_rebuild:
        if _is_engine_version_mismatch(conn):
            _interpret_fighters(conn, current_date)  # ALL fighters
        else:
            _interpret_dirty_fighters(conn, current_date)  # only dirty
    else:
        _refresh_dirty_fighters(conn)

    # ----------------------------------------------------------------
    # 2. Gym interpretation.
    # ----------------------------------------------------------------
    # Gym identity is a daily-pass concern (not a per-event one) —
    # the per-fight refresh_fighter path doesn't touch gym_descriptors.
    # Always run the gym pass, regardless of full vs targeted mode.
    _interpret_gyms(conn, current_date)

    # ----------------------------------------------------------------
    # 3. Promotion interpretation.
    # ----------------------------------------------------------------
    _interpret_promotions(conn, current_date)

    # ----------------------------------------------------------------
    # 4. Division interpretation.
    # ----------------------------------------------------------------
    _interpret_divisions(conn, current_date)

    # ----------------------------------------------------------------
    # 5. Daily headlines.
    # ----------------------------------------------------------------
    # Headlines are derived from fighter_descriptors, so they're
    # only as fresh as the last fighter refresh. They're regenerated
    # on every daily pass (idempotent INSERT OR REPLACE) — the player
    # expects fresh "today's top story" on every Advance Day.
    _generate_headlines(conn, current_date)

    # ----------------------------------------------------------------
    # 6. Update cache meta (always — even in targeted mode).
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

    # Clear the dirty-fighter set — the daily pass has either re-
    # refreshed each dirty fighter (targeted mode) or done a full
    # rebuild (which subsumes them). Either way, the set is stale
    # by the next tick.
    clear_dirty_fighters()


def _refresh_dirty_fighters(conn):
    """Targeted refresh — re-run refresh_fighter on each dirty fighter.

    Called from run_daily_interpretation_pass on non-weekly ticks
    (the common case). The per-event subscribers have ALREADY called
    refresh_fighter(conn, fid) when each event fired (FIGHT_RESOLVED,
    FIGHTER_SIGNED, etc.) — this re-refresh is a safety net that
    catches anything the per-event path missed (e.g., a transient
    error during the event-driven refresh, or a fighter whose
    descriptor snapshot was invalidated by a downstream write that
    happened after the per-event refresh).

    Cheap: ~0.7 ms × N dirty fighters (typically 5-20 per tick).
    """
    # Snapshot the set so iteration is safe even if refresh_fighter
    # somehow re-enters mark_fighter_dirty (it shouldn't, but the
    # defensive copy costs nothing).
    dirty = list(_dirty_fighters)
    for fid in dirty:
        try:
            refresh_fighter(conn, fid)
        except Exception as e:
            import sys
            print(f"WARNING: _refresh_dirty_fighters: refresh_fighter("
                  f"fighter_id={fid}) failed: {type(e).__name__}: {e}",
                  file=sys.stderr)


def _interpret_dirty_fighters(conn, current_date):
    """Weekly dirty rebuild — refresh only the fighters in
    _fighters_dirty_for_rebuild.

    TIER1-365DAY (2027-02): replaces the unconditional weekly
    _interpret_fighters call (which rebuilt ALL 4450 active fighters
    on every 7th tick, ~333ms). Now only fighters whose attributes
    crossed a voice-tier boundary since the last weekly rebuild are
    refreshed (~15-50ms for 50-200 fighters).

    The dirty-for-rebuild set is populated by career_arc._process_
    career_arc when tier_crossed=True or pers_tier_crossed=True
    (i.e., when the monthly career-arc tick changed an attribute
    in a way that shifts the fighter's voice-tier label, which in
    turn shifts the descriptor strings produced by the context /
    phase / family / legacy sub-engines).

    After refreshing all dirty fighters, the set is cleared. The
    next weekly rebuild will only refresh fighters newly dirtied
    between now and then.

    Args:
        conn: sqlite3.Connection.
        current_date: ISO date string for the current sim day
            (passed for interface symmetry with _interpret_fighters;
            refresh_fighter reads the date from simulation_clock
            internally, so this is currently unused).
    """
    # Snapshot the set so iteration is safe even if refresh_fighter
    # somehow re-enters mark_fighter_dirty_for_rebuild (it shouldn't,
    # but the defensive copy costs nothing).
    dirty = list(_fighters_dirty_for_rebuild)
    if not dirty:
        # Nothing to refresh — the weekly rebuild is a no-op this
        # tick. This is the common case early in a soak (no monthly
        # career-arc tick has fired yet to populate the set).
        return
    for fid in dirty:
        try:
            refresh_fighter(conn, fid)
        except Exception as e:
            import sys
            print(f"WARNING: _interpret_dirty_fighters: refresh_fighter("
                  f"fighter_id={fid}) failed: {type(e).__name__}: {e}",
                  file=sys.stderr)
    # Clear the set — the weekly rebuild has re-refreshed each
    # fighter in it. The next weekly rebuild will only refresh
    # fighters newly dirtied between now and then.
    clear_fighters_dirty_for_rebuild()


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

    # Task 2.4 — refresh narrative_family for this single fighter.
    # Same try/except pattern — a single failed family refresh must
    # not roll back the work already done. If the narrative_families
    # engine isn't available (older code), this silently no-ops.
    try:
        from interpretation.narrative_families import compute_single_family
        compute_single_family(conn, fighter_id)
    except ImportError:
        pass  # Task 2.4 not landed yet — no-op.
    except Exception as e:
        import sys
        print(f"WARNING: narrative_families.compute_single_family("
              f"fighter_id={fighter_id}) failed in refresh_fighter: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # Task 2.7 — refresh legacy_state for this single fighter.
    # Same try/except pattern. Applies to active AND retired fighters
    # (the engine's internal logic handles both — no is_active filter
    # at the refresh site).
    try:
        from interpretation.legacy_engine import compute_single_legacy
        compute_single_legacy(conn, fighter_id)
    except ImportError:
        pass  # Task 2.7 not landed yet — no-op.
    except Exception as e:
        import sys
        print(f"WARNING: legacy_engine.compute_single_legacy("
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
    # Task 2.4 — narrative_family (4 MVP families: prodigy, veteran,
    # fallen_champion, cinderella_story). Depends on momentum (Task 2.2)
    # + career_phase (Task 2.3) being populated FIRST — the bulk-load
    # reads those columns from fighter_descriptors.
    try:
        from interpretation.narrative_families import compute_all_families
        compute_all_families(conn)
    except Exception as e:
        print(f"Warning: narrative families failed: {e}", flush=True)
    # Task 2.7 — legacy_state (4 MVP states: building, established,
    # legendary, forgotten). Applies to ALL fighters (active + retired).
    # Independent of momentum/career_phase — runs last in the daily pass.
    try:
        from interpretation.legacy_engine import compute_all_legacies
        compute_all_legacies(conn)
    except Exception as e:
        print(f"Warning: legacy engine failed: {e}", flush=True)


def _interpret_gyms(conn, current_date):
    """Compute gym identity summaries via the gym_identity_engine.

    Populates `gym_descriptors` with 5 voice-phrase fields per gym
    (identity_label, known_for, produces, weakness,
    development_rating_desc) derived from the `gyms` simulation
    table's raw 0-100 ratings + the gym's name (used to infer a
    pseudo-specialty — striking/grappling/wrestling/mixed).

    Phase 6 Task A1 (2026-08-17): the gym_identity_engine has
    LANDED. The previous skeleton's `try/except ImportError` guard
    is removed — the engine is now a hard dependency. If the import
    fails, it's a real bug (the file is missing or broken), not a
    "task not landed yet" state.

    Per CONVENTIONS §17.1: the engine writes ONLY to
    gym_descriptors (a cache table). It NEVER writes to the `gyms`
    simulation table.

    Per CONVENTIONS §17.5: uses the bulk-load pattern (ONE SELECT +
    Python loop + ONE executemany INSERT OR REPLACE) — target <50ms
    for ~329 gyms. Idempotent: safe to re-run on the same date or
    across daily passes.

    Args:
        conn:         sqlite3.Connection.
        current_date: ISO date string (unused — gym identity doesn't
                      depend on the sim date. Kept for API symmetry
                      with the other interpretation sub-engines which
                      DO take current_date: context_engine, career_
                      phase_engine, etc.).
    """
    from interpretation.gym_identity_engine import compute_all_gym_descriptors
    compute_all_gym_descriptors(conn, current_date)


def _interpret_promotions(conn, current_date):
    """Compute promotion summaries via the promotion_engine.

    Populates `promotion_descriptors` with 3 voice-phrase fields per
    promotion (prestige_desc, market_position_desc, roster_quality_
    desc) derived from the `promotions` table's reputation + broadcast
    tier + ownership_type + size_tier + the average roster quality
    (joined from `fighter_descriptors.overall_desc`).

    Phase 6 Task A2 (2026-08-17): the promotion_engine has LANDED.
    The previous skeleton's `try/except ImportError` guard is removed
    — the engine is now a hard dependency. If the import fails, it's
    a real bug (the file is missing or broken), not a "task not landed
    yet" state.

    Per CONVENTIONS §17.1: the engine writes ONLY to
    promotion_descriptors (a cache table). It NEVER writes to the
    `promotions` simulation table.

    Per CONVENTIONS §17.5: uses the bulk-load pattern (ONE SELECT +
    Python loop + ONE executemany INSERT OR REPLACE) — target <50ms
    for ~10 promotions. Idempotent: safe to re-run on the same date
    or across daily passes.

    Args:
        conn:         sqlite3.Connection.
        current_date: ISO date string (unused — promotion descriptors
                      don't depend on the sim date. Kept for API
                      symmetry with the other interpretation sub-
                      engines which DO take current_date).
    """
    from interpretation.promotion_engine import compute_all_promotion_descriptors
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
    """Generate daily headlines via the Headline Engine (Task 2.6).

    Per CONVENTIONS §17.5 + the task spec for Task 2.6, the headline
    engine runs at the END of the daily interpretation pass (after
    fighter_descriptors is fully populated by context_engine +
    career_phase + narrative_families + legacy). It writes 4 daily
    headlines (top_story, upset_of_week, fastest_rising,
    biggest_fall) to the daily_headlines table via INSERT OR REPLACE
    (idempotent — re-running for the same date overwrites, doesn't
    duplicate).

    Per the task spec: the call is wrapped in try/except Exception so
    a single failed headline-engine run doesn't crash the daily pass.
    The other cache writes (fighter_descriptors, gym_descriptors,
    etc.) have already committed by this point.
    """
    try:
        from interpretation.headline_engine import generate_daily_headlines
        generate_daily_headlines(conn, current_date)
    except ImportError:
        pass  # headline_engine not landed yet — skeleton no-op.
    except Exception as e:
        print(f"Warning: headline engine failed: {e}", flush=True)
