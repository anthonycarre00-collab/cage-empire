"""CAGE EMPIRE contracts service (Stage 6 — Task 6.0).

Extracted from src/app.py (3 functions, ~290 lines including docstrings):
  - get_contracts_for_display  (was app.py:177 — UI reader)
  - get_free_agents_for_display (was app.py:345 — UI reader)
  - sign_free_agent             (was app.py:427 — UI action)

These are the contract / free-agency functions used by the App class
and by tests. Per docs/TASK_6_0_PLAN.md §1.1, they are thematically
grouped here (away from the matchmaking + fight-engine code that
moved in Steps 2-3) so Task 6.8 (Contracts screen) and Task 6.4
(Fighter Profile / Free Agents tab) can import them from a single
cohesive module.

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it reads/writes the existing `contracts`, `fighter_contracts`,
        `fighters`, `news_items`, and `news_sources` tables only.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass
        after extraction (see worklog).
  §13 — Design Law: this is the Talent Hunter pillar (signing free
        agents is the player's primary roster-shaping action).
  §14 — Voice Layer: N/A — no player-facing attribute text. The news
        headlines written by sign_free_agent use direct fighter +
        promotion names, not voice descriptors.
  §15 — Event Bus: sign_free_agent publishes Events.FIGHTER_SIGNED
        inline (Phase A5 behaviour, preserved verbatim). The 2
        display readers publish nothing.

Migration impact: NONE (code-only refactor).
"""
from datetime import datetime, timedelta


def get_contracts_for_display(conn, promotion_id=None):
    """Return contract rows for the UI Contracts tab (Task ID 9).

    Joins contracts -> fighter_contracts -> fighters and (for non-
    fighter contracts) staff_contracts -> staff and broadcast_contracts
    -> staff. Uses COALESCE across three LEFT JOINs to pick whichever
    contractor name is non-NULL based on contract_target_type.

    Args:
        conn: sqlite3 connection.
        promotion_id: if None, return all contracts; else return only
            contracts for the given promotion.

    Returns:
        List of 7-tuples: (contractor_name, contract_target_type,
        start_date, end_date, salary, exclusive_flag, status).
    """
    # Polymorphic JOIN: the base contracts table has contract_target_type
    # in ('fighter', 'staff', 'broadcast'). Each subtype table
    # (fighter_contracts / staff_contracts / broadcast_contracts) holds
    # the FK to the contracted entity. We LEFT JOIN all three subtype
    # tables + their name sources, then COALESCE the contractor name.
    # Two staff aliases (s_sc, s_bc) avoid an OR-join on staff_id which
    # could produce cartesian products. See worklog decision D2.
    sql = (
        "SELECT "
        "  COALESCE(f.first_name || ' ' || f.last_name, "
        "           s_sc.first_name || ' ' || s_sc.last_name, "
        "           s_bc.first_name || ' ' || s_bc.last_name, "
        "           'Unknown') AS contractor_name, "
        "  c.contract_target_type, c.start_date, c.end_date, "
        "  c.salary, c.exclusive_flag, c.status "
        "FROM contracts c "
        "LEFT JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "LEFT JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "LEFT JOIN staff_contracts sc ON sc.contract_id = c.contract_id "
        "LEFT JOIN staff s_sc ON s_sc.staff_id = sc.staff_id "
        "LEFT JOIN broadcast_contracts bc ON bc.contract_id = c.contract_id "
        "LEFT JOIN staff s_bc ON s_bc.staff_id = bc.staff_id"
    )
    if promotion_id is not None:
        sql += " WHERE c.promotion_id = ?"
        sql += " ORDER BY c.end_date"
        return conn.execute(sql, (promotion_id,)).fetchall()
    sql += " ORDER BY c.end_date"
    return conn.execute(sql).fetchall()


def get_free_agents_for_display(conn):
    """Return free agent rows for the UI Free Agents tab (Task ID 13).

    A free agent is a fighter with current_promotion_id IS NULL,
    is_active=1, and is_retired=0. Returns one row per free agent with
    their fighter_id, name, weight class, record, and age.

    The Free Agents tab does NOT respect the promotion filter — free
    agents are not bound to any promotion, so they're available to sign
    with any promotion. The UI always shows all free agents regardless
    of the current_promotion_filter dropdown.

    Args:
        conn: sqlite3 connection.

    Returns:
        List of 5-tuples: (fighter_id, fighter_name, weight_class_name,
        record_str, age_int). Ordered by fighter_id.

        - fighter_id:         int (used as the Treeview item iid so
                              the Sign button can read it directly).
        - fighter_name:       'first_name last_name'.
        - weight_class_name:  weight_classes.name, or 'Unknown'.
        - record_str:         'W-L-D' from fighter_career counters,
                              defaulting to '0-0-0' if no career row.
        - age_int:            computed from date_of_birth and the
                              current sim date.
    """
    # Read the current sim date. Qualify the column as
    # simulation_clock.current_date to avoid the D5 quirk where bare
    # `current_date` resolves to SQLite's built-in date function
    # (today's wall-clock date) instead of the column.
    clock_row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id = 1"
    ).fetchone()
    if clock_row and clock_row[0]:
        try:
            current_dt = datetime.strptime(clock_row[0], "%Y-%m-%d")
        except (ValueError, TypeError):
            current_dt = datetime.now()
    else:
        current_dt = datetime.now()

    # Pull all free agents. LEFT JOIN weight_classes + fighter_career
    # so a fighter missing either row (defensive — shouldn't happen
    # with the seed) doesn't crash the helper.
    rows = conn.execute(
        "SELECT f.fighter_id, f.first_name || ' ' || f.last_name, "
        "COALESCE(w.name, 'Unknown'), "
        "COALESCE(fc.record_wins, 0) || '-' || "
        "COALESCE(fc.record_losses, 0) || '-' || "
        "COALESCE(fc.record_draws, 0), "
        "f.date_of_birth "
        "FROM fighters f "
        "LEFT JOIN weight_classes w ON w.weight_class_id = f.weight_class_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.current_promotion_id IS NULL "
        "AND f.is_active = 1 AND f.is_retired = 0 "
        "ORDER BY f.fighter_id"
    ).fetchall()

    out = []
    for fighter_id, name, wc_name, record_str, dob in rows:
        # Compute age from date_of_birth + the current sim date.
        # Same pattern as _check_retirements: tuple comparison on
        # (month, day) handles leap-year birthdays correctly.
        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
            age = current_dt.year - dob_dt.year
            if (current_dt.month, current_dt.day) < (dob_dt.month, dob_dt.day):
                age -= 1
        except (ValueError, TypeError):
            # Defensive: fighter with malformed DOB gets age 0 (will
            # display as "0" in the UI). Shouldn't happen with the
            # seed, but a future regen engine or mod tool could produce
            # one.
            age = 0
        out.append((fighter_id, name, wc_name, record_str, age))
    return out


def sign_free_agent(conn, fighter_id, promotion_id, start_date, salary=50000.0):
    """Sign a free agent to a promotion with a new 12-month contract.

    Rules (Task ID 13):
      - The fighter must currently be a free agent
        (current_promotion_id IS NULL) and active (is_active=1,
        is_retired=0). If not, return None with a printed warning.
        Refuses retired fighters (they can't sign) and already-signed
        fighters (they're not free agents).
      - Creates a new contracts row (contract_target_type='fighter',
        status='active', exclusive_flag=1, start_date=start_date,
        end_date=start_date + 365 days, salary=salary).
      - Creates a fighter_contracts row linking the contract to the
        fighter (contract_type='standard').
      - Sets the fighter's current_promotion_id = promotion_id.
      - Writes a news item: "<fighter> signs with <promotion>".
        topic='signing' so future UI filters can group signing-related
        news together.
      - Returns the new contract_id (int) on success, None on failure.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the free agent's fighter_id.
        promotion_id: the promotion signing them.
        start_date: ISO date string 'YYYY-MM-DD' for the contract start.
        salary: contract salary. Default 50000.0 (matches the seed
            default — no negotiation flow yet, that's a future task).

    Returns:
        New contract_id (int) on success, None on failure.
    """
    # 1. Verify the fighter is a free agent and active. Refuse retired
    #    fighters (they're not coming back) and already-signed fighters
    #    (they're not free agents).
    row = conn.execute(
        "SELECT is_active, is_retired, current_promotion_id "
        "FROM fighters WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row:
        print(f"Warning: fighter_id={fighter_id} not found.")
        return None
    is_active, is_retired, current_promo = row
    if is_retired == 1:
        print(f"Warning: fighter_id={fighter_id} is retired — cannot sign.")
        return None
    if current_promo is not None:
        print(f"Warning: fighter_id={fighter_id} is already signed to "
              f"promotion_id={current_promo}.")
        return None
    if is_active != 1:
        print(f"Warning: fighter_id={fighter_id} is not active — cannot sign.")
        return None

    # 2. Compute end_date (start_date + 365 days). Mirrors the seed
    #    default in _seed_default_fighter_contract (seed_data.py).
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        print(f"Warning: invalid start_date {start_date!r}: {e}")
        return None
    end_dt = start_dt + timedelta(days=365)
    end_date = end_dt.strftime("%Y-%m-%d")

    # 3. Insert the contract. contract_target_type='fighter',
    #    exclusive_flag=1 (mirrors the seed default), status='active'.
    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('fighter', ?, ?, ?, ?, 1, 'active')",
        (promotion_id, start_date, end_date, salary),
    ).lastrowid

    # 4. Insert the fighter_contracts row linking the contract to the
    #    fighter. contract_type='standard' (same as the seed default).
    conn.execute(
        "INSERT INTO fighter_contracts (contract_id, fighter_id, "
        "contract_type) VALUES (?, ?, 'standard')",
        (contract_id, fighter_id),
    )

    # 5. Set the fighter's current_promotion_id. This is what
    #    _pick_matchup (Task 8) and get_fighters_for_display (Task 6)
    #    filter on — once it's set, the fighter appears in the
    #    promotion's roster and is eligible for new matchups.
    conn.execute(
        "UPDATE fighters SET current_promotion_id = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
        (promotion_id, fighter_id),
    )

    # 6. Write the signing news item. Direct INSERT (same pattern as
    #    _check_retirements + _vacate_title_on_retirement) to avoid
    #    pulling in app.write_news from this same module (it would be
    #    fine since we're already in app.py, but the direct INSERT is
    #    what the brief specifies and matches the established pattern).
    fighter_name_row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    fighter_name = fighter_name_row[0] if fighter_name_row else f"Fighter {fighter_id}"

    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id = ?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promotion {promotion_id}"

    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            src_id,
            f"{fighter_name} signs with {promo_name}",
            f"Free agent {fighter_name} has signed a new contract "
            f"with {promo_name}.",
            "positive",
            "signing",
            fighter_id,
            promotion_id,
            start_date,
        ),
    )

    # Phase A5 — publish FIGHTER_SIGNED on the event bus. The news
    # engine subscribes to write a richer signing news item with
    # voice descriptors (career stage + attribute summary). The
    # morale system also subscribes (+3 morale on signing — a fresh
    # start is a morale lift). The event payload includes the
    # contract_id so subscribers can look up contract terms if
    # needed (e.g., a future "biggest contract of the year" news
    # item).
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.FIGHTER_SIGNED,
            'fighter_id': fighter_id,
            'promotion_id': promotion_id,
            'contract_id': contract_id,
            'current_date': start_date,
            'event_date': start_date,
        })
    except ImportError:
        pass

    return contract_id
