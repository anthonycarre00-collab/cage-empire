"""CAGE EMPIRE Interpretation Layer (Phase 2).

The interpretation layer translates raw simulation state into
player-facing meaning, context, and stories. It NEVER modifies
simulation tables — only writes to *_descriptors cache tables.

Per CONVENTIONS §17:
  - Office Mode UI reads from *_descriptors ONLY
  - Fight Night UI reads from live fight_beats (exception)
  - The interpretation layer is the ONLY writer to cache tables

Architecture (see docs/PHASE_2_PLAN.md §2.1 + §2.2):

  snapshot_cache.py   ← the orchestrator
      run_daily_interpretation_pass(conn)   post-commit step in run_tick
      refresh_fighter(conn, fighter_id)     targeted single-fighter refresh

  Sub-engines (Tasks 2.2-2.8 — stubs for now, filled in by later tasks):
      context_engine.py            (Task 2.2)
      career_phase_engine.py       (Task 2.3)
      narrative_families.py        (Task 2.4)
      memory_engine.py             (Task 2.5)
      headline_engine.py           (Task 2.6)
      legacy_engine.py             (Task 2.7)
      gym_identity_engine.py       (Task 2.8)

This module's public API:
  - run_daily_interpretation_pass: called from tick_processor.run_tick
    AFTER conn.commit() (per CONVENTIONS §17.5).
  - refresh_fighter: called by the 4 event-bus subscribers below on
    FIGHT_RESOLVED / FIGHTER_RETIRED / TITLE_CHANGED / CONTRACT_EXPIRED.
  - register_subscribers: called once from src/ui/app.py __init__ to
    wire up the 4 event-bus subscribers. Registered LAST (after the
    existing 15) per CONVENTIONS §17.5.
"""
from interpretation.snapshot_cache import (
    run_daily_interpretation_pass,
    refresh_fighter,
    mark_fighter_dirty,
    mark_fighter_dirty_for_rebuild,
    clear_dirty_fighters,
    clear_fighters_dirty_for_rebuild,
)


__all__ = [
    "run_daily_interpretation_pass",
    "refresh_fighter",
    "mark_fighter_dirty",
    "mark_fighter_dirty_for_rebuild",
    "clear_dirty_fighters",
    "clear_fighters_dirty_for_rebuild",
    "register_subscribers",
]


def register_subscribers():
    """Register interpretation layer subscribers on the event bus.

    Subscribes to 6 events for targeted single-fighter refresh:
      FIGHT_RESOLVED    → refresh both fighters who fought + mark dirty
      FIGHTER_RETIRED   → refresh the retiring fighter + mark dirty
      TITLE_CHANGED     → refresh new + dethroned champion + mark dirty
      CONTRACT_EXPIRED  → refresh the fighter + mark dirty
      FIGHTER_SIGNED    → refresh the signed fighter + mark dirty (NEW
                          in TICK-REENGINEER — previously the signing
                          subscriber was missing, so signed fighters'
                          momentum/pressure weren't refreshed until the
                          next daily pass).
      INJURY_RECOVERED  → refresh the recovered fighter + mark dirty
                          (NEW in TICK-REENGINEER — previously the
                          injury-recovery subscriber was missing, so
                          fighters returning from injury kept stale
                          legacy_state until the next daily pass).

    PHASE-R (Reward Layer §1.5 + §6): also registers the echoes_engine
    subscriber on TICK_ADVANCED so the daily_echoes cache refreshes on
    every Advance Day. Registered LAST per CONVENTIONS §17.5 so all
    simulation writes are visible to the echoes queries (fight_history,
    news_items, contracts are all committed before the TICK_ADVANCED
    event fires).

    The full daily pass runs as a POST-COMMIT step in
    tick_processor.run_tick (NOT as a TICK_ADVANCED subscriber). This
    avoids event-bus ordering hazards and keeps the simulation
    transaction fast (per CONVENTIONS §17.5).

    TICK-REENGINEER (Fix 1, PERF_ARCH_AUDIT §4.5): the daily pass
    now has two modes — full rebuild (weekly + on engine-version
    mismatch) and targeted refresh (non-weekly ticks, only dirty
    fighters). The dirty-set entries written by these subscribers
    are consumed by run_daily_interpretation_pass's targeted path.

    This function is safe to call multiple times — duplicate
    subscriptions would just result in the subscriber running N times
    (the bus has no dedup), but in practice it's called exactly once
    from src/ui/app.py __init__.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.FIGHT_RESOLVED, _on_fight_resolved,
                  name="interpretation.fight_resolved")
    bus.subscribe(Events.FIGHTER_RETIRED, _on_fighter_retired,
                  name="interpretation.fighter_retired")
    bus.subscribe(Events.TITLE_CHANGED, _on_title_changed,
                  name="interpretation.title_changed")
    bus.subscribe(Events.CONTRACT_EXPIRED, _on_contract_expired,
                  name="interpretation.contract_expired")
    bus.subscribe(Events.FIGHTER_SIGNED, _on_fighter_signed,
                  name="interpretation.fighter_signed")
    bus.subscribe(Events.INJURY_RECOVERED, _on_injury_recovered,
                  name="interpretation.injury_recovered")

    # PHASE-R (Reward Layer): echoes_engine — refreshes the daily_echoes
    # cache on every Advance Day so the Dashboard's ECHOES section
    # surfaces fresh consequences of the player's past decisions.
    # Registered LAST (after the 6 fighter-refresh subscribers) so all
    # fighter_descriptors updates from those subscribers are visible
    # to the echoes queries (e.g. the scouting echo reads career_phase
    # which may have just been refreshed by FIGHT_RESOLVED).
    try:
        from interpretation.echoes_engine import (
            register_subscribers as _register_echoes,
        )
        _register_echoes()
    except Exception as e:
        import sys
        print(f"WARNING: interpretation.echoes_engine register failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # HW3 (Memory + Echoes Expansion): memory_svc writers — writes
    # title_history / upset / comeback / milestone links when
    # FIGHT_RESOLVED / TITLE_CHANGED / FIGHTER_SIGNED fire. The
    # writers are idempotent (INSERT OR IGNORE) so duplicate events
    # are safe. Registered AFTER echoes_engine so the echoes layer's
    # reads see the memory writes from this same tick (the echoes
    # engine doesn't currently read memory links, but the ordering
    # is forward-compatible).
    try:
        from services.memory_svc import (
            register_subscribers as _register_memory_svc,
        )
        _register_memory_svc()
    except Exception as e:
        import sys
        print(f"WARNING: services.memory_svc register failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)


def _on_fight_resolved(conn, event):
    """Subscriber for FIGHT_RESOLVED — refresh both fighters' snapshots.

    The event payload (published by services/fight_engine.py:resolve_
    next_fight) includes:
      fight_id, event_id, promotion_id, weight_class_id,
      winner_id, loser_id, fighter_a_id, fighter_b_id,
      result_type, finish_round, finish_time, is_title_fight,
      title_changed, event_date, importance

    We refresh BOTH fighter_a_id and fighter_b_id (NOT just the winner)
    because both fighters' momentum / pressure / career_phase changed
    as a result of the fight (the loser's streak went down, the
    winner's went up). On a draw, both still need a refresh.
    """
    a_id = event.get("fighter_a_id")
    b_id = event.get("fighter_b_id")
    # Defensive: if the event doesn't include the new-style keys (older
    # publishers), fall back to winner_id / loser_id — at least one of
    # them is non-None on a non-draw resolution.
    if a_id is None and b_id is None:
        a_id = event.get("winner_id")
        b_id = event.get("loser_id")
    for fid in (a_id, b_id):
        if fid:
            try:
                refresh_fighter(conn, fid)
            except Exception as e:
                # Defensive — a single failed refresh must not crash
                # the event bus dispatch for downstream subscribers.
                # The bus ALSO catches subscriber exceptions, but we
                # log here with fighter context for easier debugging.
                import sys
                print(f"WARNING: interpretation.refresh_fighter("
                      f"fighter_id={fid}) failed on FIGHT_RESOLVED: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
            # TICK-REENGINEER (Fix 1): mark the fighter dirty so the
            # next daily pass picks them up in the targeted refresh
            # path (safety net in case the per-event refresh missed
            # something due to a transient error).
            mark_fighter_dirty(fid)


def _on_fighter_retired(conn, event):
    """Subscriber for FIGHTER_RETIRED — refresh the retiring fighter.

    Retirement changes the fighter's legacy_state + narrative_family
    (e.g., a champion retires as a "Fallen Champion" or "Veteran"
    depending on the exit). The retiring fighter's snapshot is
    refreshed so the post-retirement descriptor (read from the Hall
    of Fame screen + retired-fighter lists) reflects the new narrative.

    The event payload (published by tick_processor._check_retirements)
    includes: fighter_id, retirement_date, replacement_id (if regen).
    """
    fighter_id = event.get("fighter_id")
    if fighter_id:
        try:
            refresh_fighter(conn, fighter_id)
        except Exception as e:
            import sys
            print(f"WARNING: interpretation.refresh_fighter("
                  f"fighter_id={fighter_id}) failed on FIGHTER_"
                  f"RETIRED: {type(e).__name__}: {e}", file=sys.stderr)
        # TICK-REENGINEER (Fix 1): mark dirty for the daily pass.
        mark_fighter_dirty(fighter_id)


def _on_title_changed(conn, event):
    """Subscriber for TITLE_CHANGED — refresh new + dethroned champion.

    A title change is a major narrative event for both fighters:
      - The new champion's career_phase shifts (e.g., to "champion"
        or "dominant_champion") and their narrative_family may change
        (e.g., to "Prodigy" if they're young, or "Cinderella Story"
        if they were a long-shot underdog).
      - The dethroned champion's career_phase shifts (e.g., to
        "declining" or "veteran") and their narrative_family may
        change (e.g., to "Fallen Champion").

    The TITLE_CHANGED event payload (published by
    services/fight_engine.py:resolve_next_fight) includes:
      title_id, fight_id, event_id, promotion_id, weight_class_id

    The new champion is the current titles.current_champion_fighter_id
    (already updated by resolve_next_fight BEFORE this event fires).
    The dethroned champion is the loser of the title fight — we look
    it up via fights.loser_fighter_id (title fights are always
    non-draws).
    """
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")

    # New champion — from the (already-updated) titles row.
    new_champ = None
    if title_id:
        row = conn.execute(
            "SELECT current_champion_fighter_id FROM titles WHERE title_id=?",
            (title_id,),
        ).fetchone()
        if row:
            new_champ = row[0]

    # Dethroned champion — loser of the title fight. Title fights are
    # always non-draws (resolve_next_fight enforces this), so
    # loser_fighter_id is non-NULL.
    dethroned = None
    if fight_id:
        row = conn.execute(
            "SELECT loser_fighter_id FROM fights WHERE fight_id=?",
            (fight_id,),
        ).fetchone()
        if row:
            dethroned = row[0]

    for fid in (new_champ, dethroned):
        if fid:
            try:
                refresh_fighter(conn, fid)
            except Exception as e:
                import sys
                print(f"WARNING: interpretation.refresh_fighter("
                      f"fighter_id={fid}) failed on TITLE_CHANGED: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
            # TICK-REENGINEER (Fix 1): mark dirty for the daily pass.
            mark_fighter_dirty(fid)


def _on_contract_expired(conn, event):
    """Subscriber for CONTRACT_EXPIRED — refresh the fighter whose
    contract expired.

    Contract expiry changes the fighter's context (they're now a free
    agent, no longer under a promotion's protection), which can shift
    their pressure reading + public narrative ("contract_drama"
    headline candidate). The single-fighter refresh is cheap (~5ms)
    and ensures the UI shows the up-to-date descriptor immediately.

    The event payload (published by tick_processor._check_contract_
    expiry) includes: fighter_id, contract_id, promotion_id,
    expiry_date.
    """
    fighter_id = event.get("fighter_id")
    if fighter_id:
        try:
            refresh_fighter(conn, fighter_id)
        except Exception as e:
            import sys
            print(f"WARNING: interpretation.refresh_fighter("
                  f"fighter_id={fighter_id}) failed on CONTRACT_"
                  f"EXPIRED: {type(e).__name__}: {e}", file=sys.stderr)
        # TICK-REENGINEER (Fix 1): mark dirty for the daily pass.
        mark_fighter_dirty(fighter_id)


def _on_fighter_signed(conn, event):
    """Subscriber for FIGHTER_SIGNED — refresh the signed fighter.

    A signing changes the fighter's context (they're now under a
    promotion's protection, with a contract + salary), which can
    shift their pressure reading ("contract_security" headline
    candidate) and their narrative_family (a long-time free agent
    finally signing might classify as a "Cinderella Story"). The
    single-fighter refresh is cheap (~5 ms) and ensures the UI
    shows the up-to-date descriptor immediately on the Roster /
    Fighter Profile screens.

    TICK-REENGINEER (Fix 1): this subscriber is NEW — previously
    the interpretation layer didn't subscribe to FIGHTER_SIGNED,
    so a signed fighter's momentum / pressure / career_phase /
    narrative_family weren't refreshed until the next daily pass.
    With this subscriber + the targeted daily pass, signed fighters'
    cache rows are fresh immediately.

    The event payload (published by services/contracts.sign_free_
    agent) includes: fighter_id, promotion_id, contract_id,
    current_date, event_date.
    """
    fighter_id = event.get("fighter_id")
    if fighter_id:
        try:
            refresh_fighter(conn, fighter_id)
        except Exception as e:
            import sys
            print(f"WARNING: interpretation.refresh_fighter("
                  f"fighter_id={fighter_id}) failed on FIGHTER_"
                  f"SIGNED: {type(e).__name__}: {e}", file=sys.stderr)
        # TICK-REENGINEER (Fix 1): mark dirty for the daily pass.
        mark_fighter_dirty(fighter_id)


def _on_injury_recovered(conn, event):
    """Subscriber for INJURY_RECOVERED — refresh the recovered fighter.

    Injury recovery restores fighter_career.career_health by
    severity*2 (the temporary penalty applied at injury creation
    time). The career_health change can shift the fighter's
    legacy_state (a fighter at 100 health is "building" or
    "established"; one at 50 health after multiple injuries is
    closer to "forgotten"). The single-fighter refresh ensures the
    UI shows the up-to-date descriptor immediately on the Fighter
    Profile screen.

    TICK-REENGINEER (Fix 1): this subscriber is NEW — previously
    the interpretation layer didn't subscribe to INJURY_RECOVERED,
    so a returning fighter's legacy_state stayed stale until the
    next daily pass. With this subscriber + the targeted daily
    pass, recovered fighters' cache rows are fresh immediately.

    The event payload (published by tick_processor._check_injury_
    recovery) includes: injury_id, fighter_id, current_date,
    event_date.
    """
    fighter_id = event.get("fighter_id")
    if fighter_id:
        try:
            refresh_fighter(conn, fighter_id)
        except Exception as e:
            import sys
            print(f"WARNING: interpretation.refresh_fighter("
                  f"fighter_id={fighter_id}) failed on INJURY_"
                  f"RECOVERED: {type(e).__name__}: {e}", file=sys.stderr)
        # TICK-REENGINEER (Fix 1): mark dirty for the daily pass.
        mark_fighter_dirty(fighter_id)
