"""CAGE EMPIRE Rival AI — Staff Manager (Task ID RIVAL-AI-P2to4, Phase 3).

Per docs/RIVAL_AI_ARCHITECTURE.md §3.5 — staff hiring/firing for
promotion-bound staff (scout, commentator, doctor, cutman,
general_manager). Coaches are gym-bound (managed by the gym system,
not the rival AI — see arch doc §Q5 + the v3.14.0 coach-gym backfill
in build_db.py).

Fires QUARTERLY (current_day % 84 == 0) on the TICK_ADVANCED
subscriber in src/rival_ai.py. For each rival promo, evaluates the
staff for hire/fire decisions, applies the loyalty + recency bias
rules, and writes news items.

CONVENTIONS compliance:
  §5  — No new tables. Reads/writes existing `staff` + `staff_contracts`
        + `contracts` + `scouting_reports` tables only.
  §13 — Design Law: this is the "Empire Builder" pillar — rival promos
        invest in scouts (better talent eval), commentators (brand
        voice), doctors (medical care), cutmen (corner staff).
  §14 — Voice Layer: news items use direct prose (no raw numbers).
  §15 — Event Bus: N/A — no subscribers. Called by src/rival_ai.py's
        TICK_ADVANCED dispatch.
"""

import random as _random
from datetime import datetime, timedelta


# Role-based salary model (mirrors the v3.14.0 staff_contracts backfill
# in src/build_db.py — kept in sync so hired staff get the same salary
# as backfilled staff).
STAFF_SALARY_BY_ROLE = {
    "general_manager": 80000.0,
    "doctor":          60000.0,
    "commentator":     50000.0,
    "scout":           45000.0,
    "cutman":          40000.0,
}

# Default contract duration (1 year, matches the seed).
STAFF_CONTRACT_DURATION_DAYS = 365

# Fire-eligibility thresholds (per arch doc §3.5).
SCOUT_USEFUL_REPORT_THRESHOLD = 2     # < 2 useful reports in 90 days → fire-eligible
SCOUT_TENURE_FIRE_FLOOR_DAYS = 180    # don't fire scouts in their first 6 months
DOCTOR_INJURY_RATE_THRESHOLD = 0.30   # 30% above league avg → fire-eligible

# Whimsy roll for actually firing fire-eligible staff (per arch doc
# §3.5: "30% whimsy roll — most get one more quarter to turn it around").
FIRE_WHIMSY_ROLL = 0.30

# Loyalty protection threshold (per arch doc §3.5: tenure >= 365 days
# → +1 quarter grace period before firing).
LOYALTY_TENURE_DAYS = 365

# Injury-rate comparison: compute the league-average injury rate over
# the last quarter. If the promo's rate is > 30% above the league
# avg, the medical staff is fire-eligible (recency bias — often
# unfairly, since injuries are mostly fighter-driven).
INJURY_LOOKBACK_DAYS = 90


def evaluate_staff_changes(conn, promotion_id, archetype=None, current_date=None, rng=None):
    """Evaluate the promo's staff for hire/fire decisions.

    Per arch doc §3.5:
      1. Fire evaluation (per role):
         - Scout: < 2 useful reports (potential >= 60) in 90 days AND
           tenure >= 180 days → fire-eligible.
         - Commentator: never fired (voice of the brand).
         - Doctor / cutman: promo's injury rate > 30% above league
           average last quarter → fire-eligible (recency bias).
         - General_manager: never fired.
         - 30% whimsy roll on fire-eligible staff (most get "one more
           quarter").
         - Loyalty: tenure >= 365 days → +1 quarter grace period
           before firing.
      2. Hire evaluation:
         - Compare current staff counts to archetype.staff_target.
         - For each role below target: check budget (cash >= 2 ×
           monthly staff commitment). Hire if affordable + has
           development need.
         - Generate a new staff row + a staff_contracts row.
      3. News items: hire = positive sentiment, fire = neutral.

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the rival promo evaluating staff.
        archetype: optional pre-fetched archetype dict (for staff_target).
        current_date: sim date string. Defaults to current sim date.
        rng: optional random.Random instance.

    Returns:
        Dict {'hired': [staff_id, ...], 'fired': [staff_id, ...]}.
    """
    rng = rng or _random.Random()
    if current_date is None:
        from services.rival_ai._shared import current_sim_date
        current_date = current_sim_date(conn)
    if not current_date:
        return {'hired': [], 'fired': []}

    # Resolve the (state-modified, recency-modified) archetype.
    if archetype is None:
        from services.rival_ai.budget_manager import get_modified_archetype
        _, archetype, budget_state = get_modified_archetype(conn, promotion_id)
        if archetype is None:
            return {'hired': [], 'fired': []}
    else:
        from services.rival_ai.budget_manager import get_budget_state
        budget_state = get_budget_state(conn, promotion_id)

    # 1. Fire evaluation.
    fired = _evaluate_fires(conn, promotion_id, archetype, current_date, rng, budget_state)

    # 2. Hire evaluation.
    hired = _evaluate_hires(conn, promotion_id, archetype, current_date, rng, budget_state)

    return {'hired': hired, 'fired': fired}


def _evaluate_fires(conn, promotion_id, archetype, current_date, rng, budget_state):
    """Evaluate the staff roster for fire-eligible members.

    Returns the list of staff_ids actually fired (after whimsy roll +
    loyalty grace period).
    """
    # Fetch all promo-bound staff (excluding coaches — gym-bound).
    staff_rows = conn.execute(
        "SELECT s.staff_id, s.role_type, s.specialty, s.age, "
        "sc.contract_id, c.start_date, c.salary "
        "FROM staff s "
        "LEFT JOIN staff_contracts sc ON sc.staff_id = s.staff_id "
        "LEFT JOIN contracts c ON c.contract_id = sc.contract_id "
        "AND c.status = 'active' "
        "WHERE s.promotion_id = ? AND s.role_type != 'coach'",
        (promotion_id,),
    ).fetchall()

    # Pre-compute the promo's injury rate vs the league average.
    promo_injury_rate = _compute_injury_rate(conn, promotion_id, current_date)
    league_injury_rate = _compute_league_injury_rate(conn, current_date)
    high_injury = (
        league_injury_rate > 0
        and promo_injury_rate > league_injury_rate * (1 + DOCTOR_INJURY_RATE_THRESHOLD)
    )

    fired = []
    for (staff_id, role_type, specialty, age, contract_id,
         start_date, salary) in staff_rows:
        if role_type in ('commentator', 'general_manager'):
            continue  # never fired (voice of the brand / firing yourself)

        # Compute tenure in days.
        tenure_days = _tenure_days(start_date, current_date)

        fire_eligible = False
        if role_type == 'scout':
            # < 2 useful reports (potential >= 60) in 90 days AND
            # tenure >= 180 days.
            useful_reports = _scout_performance(conn, staff_id, current_date)
            if (useful_reports < SCOUT_USEFUL_REPORT_THRESHOLD
                    and tenure_days >= SCOUT_TENURE_FIRE_FLOOR_DAYS):
                fire_eligible = True
        elif role_type in ('doctor', 'cutman'):
            # High injury rate → fire-eligible (recency bias).
            if high_injury:
                fire_eligible = True

        if not fire_eligible:
            continue

        # Loyalty protection: tenure >= 365 days → +1 quarter grace
        # period before firing. We approximate this as "if tenure >=
        # 365 days AND the contract started within the last 90 days,
        # give them one more quarter" — i.e., only fire long-tenured
        # staff if they've had at least one full quarter since their
        # "fire-eligibility" was triggered. Since we re-evaluate
        # quarterly, this means: if tenure >= 365 days, skip the fire
        # this quarter unless they've been fire-eligible for 2+
        # consecutive quarters (which we approximate by checking if
        # they have < 1 useful report in the last 180 days for scouts,
        # or if the promo's injury rate has been high for 180+ days
        # for medical staff).
        if tenure_days >= LOYALTY_TENURE_DAYS:
            # Give them one more quarter (the grace period). Only fire
            # if performance is REALLY bad (e.g., 0 useful reports in
            # 180 days for scouts).
            if role_type == 'scout':
                useful_180 = _scout_performance_window(
                    conn, staff_id, current_date, 180,
                )
                if useful_180 >= 1:
                    continue  # grace period — one more quarter
            else:
                # Medical staff — only fire if also high injury rate
                # over the last 180 days.
                rate_180 = _compute_injury_rate_window(
                    conn, promotion_id, current_date, 180,
                )
                if rate_180 < promo_injury_rate:
                    continue  # improving — grace period

        # 30% whimsy roll — most fire-eligible staff get one more
        # quarter to turn it around.
        if rng.random() > FIRE_WHIMSY_ROLL:
            continue  # one more quarter

        # Fire!
        _fire_staff(conn, staff_id, contract_id, role_type, promotion_id, current_date)
        fired.append(staff_id)
    return fired


def _evaluate_hires(conn, promotion_id, archetype, current_date, rng, budget_state):
    """Compare current staff counts to archetype.staff_target + hire
    to fill gaps if budget allows.

    Returns the list of staff_ids hired.
    """
    # No hires in SURVIVAL / CRISIS state.
    if budget_state in ('SURVIVAL', 'CRISIS'):
        return []

    staff_target = archetype.get('staff_target', {})
    if not staff_target:
        return []

    # Current staff counts per role.
    current_counts = {}
    for (role_type, count) in conn.execute(
        "SELECT role_type, COUNT(*) FROM staff "
        "WHERE promotion_id=? AND role_type != 'coach' "
        "GROUP BY role_type",
        (promotion_id,),
    ).fetchall():
        current_counts[role_type] = count

    # Budget check: cash >= 2 × monthly staff commitment.
    from services.rival_ai._shared import promotion_cash
    cash = promotion_cash(conn, promotion_id)
    monthly_staff_commitment = _monthly_staff_commitment(conn, promotion_id)
    if cash < 2 * monthly_staff_commitment and monthly_staff_commitment > 0:
        return []  # can't afford new hires

    hired = []
    for role_type, target_count in staff_target.items():
        current_count = current_counts.get(role_type, 0)
        if current_count >= target_count:
            continue
        # Phase M2.3 (docs/MASTER_PLAN_MATCHMAKING.md §2.3): before
        # generating a FRESH staff, try to HIRE an existing free-agent
        # staff of this role. This closes the FA cycle — when a staff
        # retires (M2.2) + a replacement is generated (M2.3), the
        # replacement goes into the Staff Market (promotion_id=NULL).
        # The rival AI picks them up here on the next quarterly tick
        # if the promo still has a gap. This produces the "torch-
        # passing" narrative without hard-coding the replacement into
        # the retiring staff's promo.
        fa_staff_id = _try_hire_free_agent_staff(
            conn, promotion_id, role_type, current_date, rng,
        )
        if fa_staff_id is not None:
            hired.append(fa_staff_id)
            continue  # gap filled for this role this quarter
        # No free-agent staff of this role available — generate a
        # fresh one. Hire 1 staff per quarter per role (don't try
        # to fill the whole gap in one tick — produces a more
        # gradual buildup).
        new_staff_id = _hire_staff(
            conn, promotion_id, role_type, archetype, current_date, rng,
        )
        if new_staff_id is not None:
            hired.append(new_staff_id)
    return hired


def _scout_performance(conn, scout_id, current_date):
    """Return the number of useful scouting reports (potential >= 60)
    produced by `scout_id` in the last 90 days.

    Per arch doc §3.5 fire evaluation. Reads the `scouting_reports`
    table — currently 0 rows (no scout has been assigned yet post-
    v3.9.0), so this returns 0 for all scouts. Once the player starts
    assigning scouts, this will start returning real numbers. For
    RIVAL AI scouts, this returns 0 because the rival AI doesn't
    assign scouts (no scouting_svc call) — but the function still
    works for player scouts (and is the right hook for future
    AI-driven scouting).
    """
    return _scout_performance_window(conn, scout_id, current_date, 90)


def _scout_performance_window(conn, scout_id, current_date, days):
    """Return the number of useful reports in the last `days` days."""
    rows = conn.execute(
        "SELECT COUNT(*) FROM scouting_reports "
        "WHERE scout_id = ? "
        "AND report_date >= date(?, ?) "
        "AND (estimated_potential LIKE '%high%' "
        "     OR estimated_potential LIKE '%elite%' "
        "     OR contract_cost_estimate >= 60000)",
        (scout_id, current_date, f'-{days} days'),
    ).fetchone()
    return rows[0] if rows else 0


def _compute_injury_rate(conn, promotion_id, current_date):
    """Return the promo's injury rate (injuries per fight) in the last
    90 days. Used by the medical-staff fire evaluation.
    """
    return _compute_injury_rate_window(conn, promotion_id, current_date, 90)


def _compute_injury_rate_window(conn, promotion_id, current_date, days):
    """Return the promo's injury rate in the last `days` days."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT i.injury_id), COUNT(DISTINCT f.fight_id) "
        "FROM injuries i "
        "LEFT JOIN fights f ON f.event_id = i.event_id "
        "LEFT JOIN events e ON e.event_id = f.event_id "
        "WHERE e.promotion_id = ? "
        "AND i.start_date >= date(?, ?)",
        (promotion_id, current_date, f'-{days} days'),
    ).fetchone()
    if not row or row[1] == 0:
        return 0.0
    return row[0] / float(row[1])


def _compute_league_injury_rate(conn, current_date):
    """Return the league-wide injury rate in the last 90 days."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT i.injury_id), COUNT(DISTINCT f.fight_id) "
        "FROM injuries i "
        "LEFT JOIN fights f ON f.event_id = i.event_id "
        "WHERE i.start_date >= date(?, '-90 days')",
        (current_date,),
    ).fetchone()
    if not row or row[1] == 0:
        return 0.0
    return row[0] / float(row[1])


def _monthly_staff_commitment(conn, promotion_id):
    """Return the promo's monthly staff salary commitment (sum of
    active staff_contracts salaries / 12).
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(c.salary), 0) FROM contracts c "
        "JOIN staff_contracts sc ON sc.contract_id = c.contract_id "
        "WHERE c.promotion_id = ? AND c.status = 'active' "
        "AND c.contract_target_type = 'staff'",
        (promotion_id,),
    ).fetchone()
    return float(row[0]) / 12.0 if row else 0.0


def _tenure_days(start_date, current_date):
    """Return the number of days between start_date and current_date."""
    if not start_date or not current_date:
        return 0
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
        return (cur_dt - start_dt).days
    except (ValueError, TypeError):
        return 0


def _hire_staff(conn, promotion_id, role_type, archetype, current_date, rng):
    """Generate + INSERT a new staff row + staff_contract for the
    given role.

    Mirrors the seed pattern in `scripts/seed_world_phase2.py`:
      - Random name from name_pools (first_male + last_name).
      - Random age 28-55.
      - Role-appropriate specialty (matches the seed's specialty values).
      - Salary per the v3.14.0 staff_contracts backfill model.
    """
    # Pick a random name from name_pools.
    first_row = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='first_male' "
        "ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    last_row = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='last_name' "
        "ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    first_name = first_row[0] if first_row else "John"
    last_name = last_row[0] if last_row else "Doe"
    age = rng.randint(28, 55)

    # Role-appropriate specialty (matches the seed values).
    specialty_by_role = {
        'scout': '{"eye_for_talent": 50, "technical_analysis": 50, "character_reading": 50, "mistake_rate": 15, "bias_style": "Balanced", "bias_nationality": null, "bias_aggression": 0, "current_assignment": null, "assignment_start_date": null}',
        'commentator': 'play_by_play',
        'doctor': 'sports_medicine',
        'cutman': 'cuts_and_swelling',
        'general_manager': 'operations',
    }
    specialty = specialty_by_role.get(role_type, 'general')

    # INSERT the staff row.
    staff_id = conn.execute(
        "INSERT INTO staff (first_name, last_name, age, role_type, specialty, "
        "promotion_id) VALUES (?, ?, ?, ?, ?, ?)",
        (first_name, last_name, age, role_type, specialty, promotion_id),
    ).lastrowid

    # INSERT the contracts row + staff_contracts row.
    salary = STAFF_SALARY_BY_ROLE.get(role_type, 50000.0)
    try:
        start_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=STAFF_CONTRACT_DURATION_DAYS)
    end_date = end_dt.strftime("%Y-%m-%d")

    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('staff', ?, ?, ?, ?, 1, 'active')",
        (promotion_id, current_date, end_date, salary),
    ).lastrowid
    conn.execute(
        "INSERT INTO staff_contracts (contract_id, staff_id, contract_role) "
        "VALUES (?, ?, ?)",
        (contract_id, staff_id, role_type),
    )

    # Write a "hire" news item.
    from services.rival_ai._shared import write_news_item
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"
    role_display = role_type.replace('_', ' ').title()
    write_news_item(
        conn,
        headline=f"{promo_name} hires {role_display} {first_name} {last_name}",
        body=(f"{promo_name} has hired {first_name} {last_name} as a new "
              f"{role_display.lower()}."),
        topic='staff',
        sentiment='positive',
        promotion_id=promotion_id,
        published_at=current_date,
    )
    return staff_id


def _try_hire_free_agent_staff(conn, promotion_id, role_type, current_date, rng):
    """Phase M2.3 — try to hire an existing free-agent staff of the
    given role before generating a fresh one.

    Looks for a staff row with promotion_id=NULL AND role_type=?
    AND age in [28, 65] (working-age range — same bounds as _hire_staff
    uses for fresh hires). If found, signs them to the promo via a
    new staff_contract + writes a "hires" news item (same pattern as
    _hire_staff, but no new staff row INSERT — the staff already
    exists).

    This closes the FA cycle: when a staff retires (M2.2) and a
    replacement is generated (M2.3), the replacement goes into the
    Staff Market as a free agent. The rival AI picks them up here
    on the next quarterly tick if the promo still has a gap. This
    produces the "torch-passing" narrative without hard-coding the
    replacement into the retiring staff's promo.

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the rival promo doing the hiring.
        role_type: the role to fill ('commentator', 'doctor', etc.).
        current_date: sim date string for the contract start_date.
        rng: random.Random instance.

    Returns:
        The hired staff_id (int) on success, None if no free-agent
        staff of this role is currently available.
    """
    # Find a free-agent staff of this role. Exclude coaches (gym-
    # bound, not promo-hireable) and staff outside the working-age
    # range. ORDER BY RANDOM() so different promos hiring the same
    # role on the same tick get different staff (no two promos sign
    # the same FA).
    row = conn.execute(
        "SELECT staff_id, first_name, last_name, skill_level "
        "FROM staff "
        "WHERE promotion_id IS NULL AND role_type=? "
        "AND age BETWEEN 28 AND 65 "
        "ORDER BY RANDOM() LIMIT 1",
        (role_type,),
    ).fetchone()
    if row is None:
        return None  # no FA staff of this role available
    staff_id, first_name, last_name, skill_level = row

    # Sign them: create a contracts row + staff_contracts row.
    salary = STAFF_SALARY_BY_ROLE.get(role_type, 50000.0)
    try:
        start_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=STAFF_CONTRACT_DURATION_DAYS)
    end_date = end_dt.strftime("%Y-%m-%d")

    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('staff', ?, ?, ?, ?, 1, 'active')",
        (promotion_id, current_date, end_date, salary),
    ).lastrowid
    conn.execute(
        "INSERT INTO staff_contracts (contract_id, staff_id, contract_role) "
        "VALUES (?, ?, ?)",
        (contract_id, staff_id, role_type),
    )

    # Update the staff row to assign them to the promo.
    conn.execute(
        "UPDATE staff SET promotion_id=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE staff_id=?",
        (promotion_id, staff_id),
    )

    # Write the hire news item — same pattern as _hire_staff.
    from services.rival_ai._shared import write_news_item
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"
    role_display = role_type.replace('_', ' ').title()
    write_news_item(
        conn,
        headline=f"{promo_name} hires {role_display} {first_name} {last_name}",
        body=(f"{promo_name} has hired {first_name} {last_name} as a "
              f"{role_display.lower()}. The signing fills a vacancy "
              f"on the promotion's staff roster."),
        topic='staff',
        sentiment='positive',
        promotion_id=promotion_id,
        published_at=current_date,
    )
    return staff_id


def _fire_staff(conn, staff_id, contract_id, role_type, promotion_id, current_date):
    """Fire a staff member — UPDATE staff.promotion_id=NULL,
    contracts.status='terminated', write a 'staff' news item.
    """
    # UPDATE staff — remove from promo.
    conn.execute(
        "UPDATE staff SET promotion_id=NULL, updated_at=CURRENT_TIMESTAMP "
        "WHERE staff_id=?",
        (staff_id,),
    )
    # UPDATE contracts — terminate.
    if contract_id is not None:
        conn.execute(
            "UPDATE contracts SET status='terminated', "
            "updated_at=CURRENT_TIMESTAMP WHERE contract_id=?",
            (contract_id,),
        )
    # Write the fire news item.
    staff_row = conn.execute(
        "SELECT first_name, last_name FROM staff WHERE staff_id=?",
        (staff_id,),
    ).fetchone()
    fname = f"{staff_row[0]} {staff_row[1]}" if staff_row else f"Staff {staff_id}"
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"
    role_display = role_type.replace('_', ' ').title()
    from services.rival_ai._shared import write_news_item
    write_news_item(
        conn,
        headline=f"{promo_name} parts ways with {role_display} {fname}",
        body=(f"{promo_name} has parted ways with {fname}, formerly the "
              f"promo's {role_display.lower()}."),
        topic='staff',
        sentiment='neutral',
        promotion_id=promotion_id,
        published_at=current_date,
    )
