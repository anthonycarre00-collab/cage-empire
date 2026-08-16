"""CAGE EMPIRE Rival AI package (Task ID RIVAL-AI-P2to4 — Phases 2-4).

This package is the home for the rival promotion AI decision
logic. Per docs/RIVAL_AI_ARCHITECTURE.md §7.1, the rival AI is split
into 7 thin modules, each owning one decision axis:

    archetypes.py        — §2  the 4-archetype system (Major League /
                           Regional Power / Grassroots / Rising Star)
                           + assign / get / assign_all helpers.
    event_scheduler.py   — §3.1 picks event_date + cadence (P2 SHIPPED)
    matchmaker.py        — §3.2 biased matchup scoring (P2 SHIPPED)
    signing_agent.py     — §3.3 roster gaps + bidding wars (P2 SHIPPED)
    cutting_agent.py     — §3.4 cut_risk + protective rules (P3 SHIPPED)
    staff_manager.py     — §3.5 hire/fire scouts/GMs/etc (P3 SHIPPED)
    budget_manager.py    — §3.6 SURVIVAL..EXPANSION state machine (P3 SHIPPED)
    imperfection.py      — §6   whimsy + recency bias + loyalty (P4 SHIPPED)
    _shared.py           — shared DB helpers (roster cache, etc.)

PHASING (per arch doc §7.5):
  - Phase 1 (RIVAL-AI-P1): foundation — archetypes + skeleton + stubs.
    DONE (shipped in the v3.14.0 migration).
  - Phase 2 (RIVAL-AI-P2to4): event_scheduler + matchmaker +
    signing_agent. DONE in this task.
  - Phase 3 (RIVAL-AI-P2to4): cutting_agent + staff_manager +
    budget_manager. DONE in this task.
  - Phase 4 (RIVAL-AI-P2to4): imperfection (whimsy + recency bias +
    loyalty) + tapping-up rumors + perf tuning. DONE in this task.

The package is imported lazily by `src/rival_ai.py` (the entry
point that subscribes to TICK_ADVANCED) to avoid a circular import
(app.py imports rival_ai at App.__init__, and the package modules
import services.matchmaking + services.contracts which themselves
import app). Lazy import matches the existing pattern.

CONVENTIONS compliance:
  §5  — One table-group per task. This package does NOT add tables;
        it inherits the table footprint of the systems it wraps
        (events, fights, contracts, staff, etc.). The Phase 1
        schema bump (v3.14.0) adds 3 columns to the existing
        `promotions` table — see docs/CONVENTIONS.md §1.1 (MINOR
        bump for additive column changes).
  §13 — Design Law: Conflict + Puppet Master + Empire Builder —
        rival promotions act on their own schedule (round-robin
        scheduling day per §4.2), pursue their own storylines
        (archetype bias), and pose a fair challenge scaled to
        their size (4-archetype system per §1.3).
  §14 — Voice Layer: inherited from the wrapped functions
        (sign_free_agent, schedule_next_event) + the
        `_shared.write_news_item` helper used by the bespoke
        news items (bidding_war_lost, tapping_up_rumor, release,
        staff, reclassified).
  §15 — Event Bus: the package is invoked by `src/rival_ai.py`'s
        TICK_ADVANCED subscriber. It publishes FIGHTER_STATE_CHANGED
        (via cutting_agent) + FIGHTER_SIGNED (via sign_free_agent,
        inherited). No new event types added (PROMOTION_RECLASSIFIED
        uses the existing news_items INSERT path instead of a new
        event type — keeps the event-bus contract stable).
  §16 — Migration: idempotent, version-bumped (v3.14.0). The
        migration adds columns guarded by `_has_column` and is
        safe to re-run.

PUBLIC API (Phases 1-4):
    from services.rival_ai import archetypes
    archetypes.assign_archetype(promotion_id, conn)
    archetypes.get_archetype(promotion_id, conn)
    archetypes.assign_all_archetypes(conn)
    archetypes.ARCHETYPES  # the 4-archetype dict literal

    from services.rival_ai import event_scheduler
    event_scheduler.schedule_next_event_for_rival(conn, promo_id, rng=...)

    from services.rival_ai import matchmaker
    matchmaker.build_card(conn, promo_id, event_date, archetype=..., rng=...)

    from services.rival_ai import signing_agent
    signing_agent.evaluate_signing_intents(conn, promo_ids, current_date)
    signing_agent.resolve_bidding_wars(conn, intents, current_date)
    signing_agent.evaluate_contract_expiry_interest(conn, current_date)

    from services.rival_ai import cutting_agent
    cutting_agent.evaluate_cuts(conn, promo_id, current_date=...)

    from services.rival_ai import staff_manager
    staff_manager.evaluate_staff_changes(conn, promo_id, current_date=...)

    from services.rival_ai import budget_manager
    budget_manager.review_budget(conn, promo_id, current_date)
    budget_manager.apply_state_modifiers(archetype, budget_state)
    budget_manager.get_modified_archetype(conn, promo_id)

    from services.rival_ai import imperfection
    imperfection.maybe_whim(archetype, decision_type, rng=...)
    imperfection.recency_bias_modifier(conn, promo_id, current_date)
    imperfection.loyalty_threshold_bonus(conn, fighter_id, promo_id)
    imperfection.re_signing_bonus(conn, fighter_id, promo_id)

    from services.rival_ai import memory
    memory.write_memory(conn, promo_id, 'event_result', current_date,
                        context={'event_id': event_id})
    memory.recent_event_result_memory(conn, promo_id)
    memory.decay_all_memories(conn)
"""

from services.rival_ai import (  # noqa: F401  (re-export)
    archetypes,
    event_scheduler,
    matchmaker,
    signing_agent,
    cutting_agent,
    staff_manager,
    budget_manager,
    imperfection,
    memory,
)

__all__ = [
    "archetypes",
    "event_scheduler",
    "matchmaker",
    "signing_agent",
    "cutting_agent",
    "staff_manager",
    "budget_manager",
    "imperfection",
    "memory",
]
