"""CAGE EMPIRE clock service (Stage 6 — Task 6.0).

Extracted from src/app.py lines 13-37 (3 functions, ~25 lines).

Smallest fundamental module — the sim clock + fighter name lookup.
Both are used by App (bare names), tick_processor, and tests.

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it reads/writes the existing `simulation_clock` + `fighters`
        tables only.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass
        after extraction.
  §13 — Design Law: this is plumbing (no player-facing text). The
        clock is the heartbeat of the sim; pillar: Growth (careers
        progress as ticks advance).
  §14 — Voice Layer: N/A — no player-facing text.
  §15 — Event Bus: `advance_day` delegates to `tick_processor.run_tick`
        which publishes Events.TICK_ADVANCED. This module publishes
        nothing itself.

Migration impact: NONE (code-only refactor).
"""
from datetime import datetime, timedelta


def fighter_name(conn, fighter_id):
    row = conn.execute("SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?", (fighter_id,)).fetchone()
    return row[0] if row else "Unknown"


def get_clock(conn):
    # v2.0.0 (Task 14.7): qualify current_date (and the other clock
    # columns, for consistency) as simulation_clock.current_date etc.
    # to avoid the pre-existing SQLite quirk (§Z.6 in
    # SCHEMA_DRIFT_AUDIT.md) where bare `current_date` resolves to
    # SQLite's built-in date FUNCTION (today's wall-clock date)
    # instead of the simulation_clock.current_date COLUMN. This
    # caused the sim clock to jump from the seeded 2026-07-20 to
    # today+1 on the first tick — see the new acceptance test
    # test_fighter_attributes.py case F for the regression check.
    return conn.execute("SELECT simulation_clock.current_date, simulation_clock.current_day, simulation_clock.current_week, simulation_clock.current_month, simulation_clock.current_year, simulation_clock.tick_counter FROM simulation_clock WHERE clock_id=1").fetchone()


def advance_day(conn):
    """Advance the simulation by one day.

    Thin wrapper that delegates to tick_processor.run_tick(conn).
    run_tick handles:
      - Updating simulation_clock (current_date += 1 day, etc.)
      - _check_retirements (birthday-gated, probability-based)
      - _check_training_camps (progress + complete)
      - _check_injury_recovery (clear is_active when recovered)
      - _check_contract_expiry (free agents)
      - Publishing Events.TICK_ADVANCED on the event bus
      - conn.commit()

    Per CONVENTIONS §15.4, the orchestration stays in run_tick —
    advance_day is just a thin wrapper so the UI has a single
    function to call. Per Phase 1 Fix 1.2.
    """
    from tick_processor import run_tick
    return run_tick(conn)
