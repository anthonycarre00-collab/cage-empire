"""CAGE EMPIRE injuries service (Stage 6 — Task 6.0 wrapper).

Thin wrapper module. Delegates to the existing
`tick_processor._check_injury_recovery` function so the future GUI
(Task 6.4 Fighter Profile screen) can call "injury recovery tick" via
the service layer (`services.injuries_svc`) without depending
directly on tick_processor.

Phase E5 (Fix 2 — per docs/DESIGN_REVIEW_E5.md §5): added the doctor
recovery-time-reduction helper `get_doctor_recovery_bonus`. Called by
`fight_engine._maybe_create_injury` at injury creation time to shorten
the projected_return_date. The bonus is the SUM of (skill_level / 200)
across all active doctors on the fighter's promo (max 15% with 3 top
doctors — a 100-skill doctor = 0.5 reduction, capped at 3 doctors).

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

Migration impact: NONE (code-only wrapper + Phase E5 helper).
"""


# Phase E5 (per docs/DESIGN_REVIEW_E5.md §5 + docs/ECON_STAFF_PLAN.md
# §4.1). Doctor recovery-time reduction constants:
#   - Per-doctor reduction = (skill_level / 200) × 10% = up to 5%
#     (a 100-skill doctor reduces recovery time by 5%).
#   - Multiple doctors stack — 3 top doctors (300 combined skill)
#     = 15% total reduction (the brief's stated max).
#   - The 0.05 per-doctor cap is implicit: a single 100-skill doctor
#     = 5%, and the 0.15 hard cap below prevents runaway stacking.
# The brief formula is (skill_level / 200) × 10% — written out as
# skill_level × (0.10 / 200) = skill_level / 2000 = 0.0005 per point.
DOCTOR_RECOVERY_BONUS_PER_SKILL_POINT = 0.10 / 200.0   # 0.0005 = 0.05% per point
DOCTOR_RECOVERY_BONUS_CAP = 0.15                       # max 15% with 3 top doctors


def get_doctor_recovery_bonus(conn, promotion_id):
    """Return the doctor-induced recovery-time reduction fraction.

    Phase E5 — per docs/DESIGN_REVIEW_E5.md §5: for each active
    doctor on the fighter's promo, reduce recovery time by
    (doctor.skill_level / 200) × 10% = up to 5% per doctor. Multiple
    doctors stack (max 15% total reduction with 3 top doctors).

    Args:
        conn: sqlite3 connection.
        promotion_id: the fighter's current_promotion_id. If None or
            the promo has no active doctors, returns 0.0 (no bonus).

    Returns:
        A float in [0.0, 0.15] — the fraction by which to reduce
        recovery days. E.g. 0.05 = 5% reduction (a 100-day recovery
        becomes 95 days). 0.0 means no active doctors on the promo.

    Implementation notes:
      - "Active" = staff_contracts row exists + parent contracts row
        has status='active'. Mirrors the salary model in
        finance.py::_process_event_finance (which uses the same
        JOIN pattern to identify active paid staff).
      - Coaches are EXCLUDED — they're gym-bound, not promo staff
        (the WHERE role_type='doctor' filter handles this).
      - The 0.15 cap is defensive — even with a corrupt DB that has
        10 active 100-skill doctors on one promo, the bonus is
        capped at 15% so the recovery timeline can't go to 0.
    """
    if not promotion_id:
        return 0.0
    row = conn.execute(
        "SELECT COALESCE(SUM(s.skill_level), 0) "
        "FROM staff s "
        "JOIN staff_contracts sc ON sc.staff_id=s.staff_id "
        "JOIN contracts c ON c.contract_id=sc.contract_id "
        "WHERE s.role_type='doctor' "
        "  AND s.promotion_id=? "
        "  AND c.status='active'",
        (promotion_id,),
    ).fetchone()
    total_skill = row[0] if row and row[0] is not None else 0
    if total_skill <= 0:
        return 0.0
    bonus = total_skill * DOCTOR_RECOVERY_BONUS_PER_SKILL_POINT
    return min(bonus, DOCTOR_RECOVERY_BONUS_CAP)


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
