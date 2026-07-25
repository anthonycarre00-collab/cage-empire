"""CAGE EMPIRE training service (Stage 6 — Task 6.0 wrapper).

Thin wrapper module. Delegates to the existing
`tick_processor._check_training_camps` function so the future GUI
(Task 6.6 Event Builder + Task 6.4 Fighter Profile) can call "training
camp progression" via the service layer (`services.training_svc`)
without depending directly on tick_processor.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer camp query helpers to Task 6.6 Event Builder).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of tick_processor
        (training_camps, fighter_attributes).
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Talent Hunter pillar — training camps are how
        prospects grow into contenders.
  §14 — Voice Layer: N/A — no player-facing text in this wrapper.
  §15 — Event Bus: tick_processor._check_training_camps publishes
        Events.TRAINING_CAMP_COMPLETED inline (Phase A5 behaviour,
        preserved verbatim via delegation).

Migration impact: NONE (code-only wrapper).
"""


def progress_camps(conn):
    """Thin wrapper that delegates to tick_processor._check_training_camps.

    Note: _check_training_camps takes (conn, current_date) in
    tick_processor, NOT just (conn). The wrapper here preserves the
    brief's literal signature (single `conn` arg) by reading the
    current sim date from the simulation_clock row before delegating.
    This matches the pattern used by services.clock.advance_day
    (which also reads the clock before delegating to run_tick).
    """
    from tick_processor import _check_training_camps
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id = 1"
    ).fetchone()
    current_date = row[0] if row else None
    if current_date is None:
        return  # defensive — no clock row, nothing to do
    return _check_training_camps(conn, current_date)
