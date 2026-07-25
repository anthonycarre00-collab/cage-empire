"""CAGE EMPIRE injuries service (Stage 6 — Task 6.0 wrapper).

Thin wrapper module. Delegates to the existing
`tick_processor._check_injury_recovery` function so the future GUI
(Task 6.4 Fighter Profile screen) can call "injury recovery tick" via
the service layer (`services.injuries_svc`) without depending
directly on tick_processor.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer injury query helpers to Task 6.4 Fighter Profile screen).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of tick_processor (injuries,
        fighter_career).
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Hard Knocks pillar — injuries are the lasting
        consequences of fight careers (a torn ACL at 32 haunts the
        fighter even after recovery).
  §14 — Voice Layer: N/A — no player-facing text in this wrapper.
  §15 — Event Bus: tick_processor._check_injury_recovery writes a
        clearance news item inline (preserved verbatim via
        delegation). The function itself publishes nothing on the
        event bus.

Migration impact: NONE (code-only wrapper).
"""


def progress_injuries(conn):
    """Thin wrapper that delegates to tick_processor._check_injury_recovery.

    Note: _check_injury_recovery takes (conn, current_date) in
    tick_processor, NOT just (conn). The wrapper here preserves the
    brief's literal signature (single `conn` arg) by reading the
    current sim date from the simulation_clock row before delegating.
    This matches the pattern used by services.clock.advance_day
    (which also reads the clock before delegating to run_tick).
    """
    from tick_processor import _check_injury_recovery
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id = 1"
    ).fetchone()
    current_date = row[0] if row else None
    if current_date is None:
        return []  # defensive — no clock row, nothing to recover
    return _check_injury_recovery(conn, current_date)
