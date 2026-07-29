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
from interpretation.snapshot_cache import run_daily_interpretation_pass, refresh_fighter


__all__ = [
    "run_daily_interpretation_pass",
    "refresh_fighter",
    "register_subscribers",
]


def register_subscribers():
    """Register interpretation layer subscribers on the event bus.

    Subscribes to 4 events for targeted single-fighter refresh:
      FIGHT_RESOLVED   → refresh both fighters who fought
      FIGHTER_RETIRED  → refresh the retiring fighter
      TITLE_CHANGED    → refresh the new champion + the dethroned champion
      CONTRACT_EXPIRED → refresh the fighter whose contract expired

    The full daily pass runs as a POST-COMMIT step in
    tick_processor.run_tick (NOT as a TICK_ADVANCED subscriber). This
    avoids event-bus ordering hazards and keeps the simulation
    transaction fast (per CONVENTIONS §17.5).

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
