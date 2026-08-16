"""CAGE EMPIRE Rival AI — Budget Manager (Task ID RIVAL-AI-P2to4, Phase 3).

Per docs/RIVAL_AI_ARCHITECTURE.md §3.6 — the 5-state budget machine
(SURVIVAL / CONSERVATIVE / NORMAL / EXPANSION / CRISIS) + crisis
handling. Reads `promotions.current_cash` + monthly expenses +
projected income to compute `cash_runway_months`, then assigns a
state and applies state-driven modifiers to the other decision
modules via `apply_state_modifiers`.

Fires MONTHLY (current_day % 28 == 0) on the TICK_ADVANCED
subscriber in src/rival_ai.py. The monthly review updates
`promotions.ai_budget_state`; the other Phase 2-3 modules read this
column at decision time + apply the modifiers via
`apply_state_modifiers(archetype, budget_state)`.

CONVENTIONS compliance:
  §5  — No new tables. Reads existing `contracts` + `staff_contracts`
        + `fighter_contracts` + `finance_transactions` + `promotions`
        tables only.
  §13 — Design Law: the budget machine is the "Empire Builder" pillar
        — rival promos must manage their cash or face crisis. The
        state machine produces visible storylines (crisis → ownership
        change → cash injection).
  §14 — Voice Layer: news items use direct prose (no raw numbers per
        CONVENTIONS §14.5) — e.g. "{Promo} enters financial crisis"
        rather than "cash=$50K, runway=0.4 months".
  §15 — Event Bus: N/A — no subscribers. The monthly review is called
        directly by src/rival_ai.py's TICK_ADVANCED dispatch.
"""

import random as _random


# The 5 budget states (per arch doc §3.6). Stored as
# `promotions.ai_budget_state` (TEXT). The migration + this module
# normalize to UPPERCASE on write.
BUDGET_STATES = ("SURVIVAL", "CONSERVATIVE", "NORMAL", "EXPANSION", "CRISIS")

# State assignment thresholds (per arch doc §3.6 step 2):
#   cash_runway_months < 1.0   → SURVIVAL
#   1.0 <= runway < 3.0        → CONSERVATIVE
#   3.0 <= runway < 6.0        → NORMAL
#   runway >= 6.0              → EXPANSION
# CRISIS is a meta-state triggered by 2 consecutive SURVIVAL months
# + cash < expenses × 0.5 (per arch doc §3.6 step 4).
SURVIVAL_RUNWAY_MAX = 1.0
CONSERVATIVE_RUNWAY_MAX = 3.0
NORMAL_RUNWAY_MAX = 6.0

# CRISIS escape hatch (per arch doc §3.6 step 4 + §Q4 default).
# After 2 consecutive SURVIVAL months AND cash < expenses × 0.5,
# the promo enters CRISIS. After another month still in CRISIS,
# an "ownership change" fires: a $2M-$5M cash injection + a news
# item. This avoids true bankruptcy.
CRISIS_CASH_INJECTION_MIN = 2_000_000
CRISIS_CASH_INJECTION_MAX = 5_000_000

# Survivable-consecutive-months tracker. We persist this via the
# news_items table — count of 'crisis_warning' news items in the
# last 60 days for this promo. This avoids a schema bump (no new
# column needed) and the news items themselves provide the audit
# trail.
CRISIS_WARNING_TOPIC = 'crisis_warning'
CRISIS_OWNERSHIP_TOPIC = 'ownership_change'


def review_budget(conn, promotion_id, current_date=None):
    """Monthly budget review for a rival promotion.

    Per arch doc §3.6:
      1. Compute monthly_expenses (fighter salaries + staff salaries +
         venue costs from last 90 days).
      2. Compute projected monthly income (last 3 events' average
         revenue × expected events this month based on archetype
         cadence).
      3. cash_runway_months = current_cash / max(1, monthly_expenses).
      4. State assignment (see thresholds above).
      5. UPDATE promotions.ai_budget_state = new_state.
      6. CRISIS check: 2 consecutive SURVIVAL months + cash <
         expenses × 0.5 → CRISIS. Trigger crisis handling.
      7. Recency bias: hit event → state up 1 tier; flop → state down
         1 tier (the recency_bias_modifier from imperfection.py
         provides this; we apply the budget_state_shift key).

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the rival promo reviewing its budget.
        current_date: sim date string. Defaults to current sim date.

    Returns:
        The new budget state string (one of BUDGET_STATES).
    """
    if current_date is None:
        from services.rival_ai._shared import current_sim_date
        current_date = current_sim_date(conn)
    if not current_date:
        return 'NORMAL'

    # 1. Compute monthly expenses.
    monthly_expenses = _compute_monthly_expenses(conn, promotion_id, current_date)
    # 2. Compute current cash.
    from services.rival_ai._shared import promotion_cash
    cash = promotion_cash(conn, promotion_id)

    # 3. Cash runway.
    if monthly_expenses <= 0:
        runway = 999.0  # no expenses → infinite runway
    else:
        runway = cash / monthly_expenses

    # 4. State assignment.
    if runway < SURVIVAL_RUNWAY_MAX:
        new_state = 'SURVIVAL'
    elif runway < CONSERVATIVE_RUNWAY_MAX:
        new_state = 'CONSERVATIVE'
    elif runway < NORMAL_RUNWAY_MAX:
        new_state = 'NORMAL'
    else:
        new_state = 'EXPANSION'

    # 5. Recency bias: apply the budget_state_shift from imperfection.
    try:
        from services.rival_ai.imperfection import recency_bias_modifier
        recency = recency_bias_modifier(conn, promotion_id, current_date)
        shift = recency.get('budget_state_shift', 0)
        if shift != 0:
            state_order = ['SURVIVAL', 'CONSERVATIVE', 'NORMAL', 'EXPANSION']
            if new_state in state_order:
                idx = state_order.index(new_state)
                new_idx = max(0, min(len(state_order) - 1, idx + shift))
                new_state = state_order[new_idx]
    except Exception:
        pass  # defensive — recency bias is a "nice to have"

    # 6. CRISIS check: 2 consecutive SURVIVAL months + cash < expenses × 0.5.
    # We detect "2 consecutive SURVIVAL months" via the current
    # ai_budget_state (last month's state) + this month's SURVIVAL
    # assignment.
    prev_state_row = conn.execute(
        "SELECT ai_budget_state FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    prev_state = (prev_state_row[0] if prev_state_row else None) or 'NORMAL'
    if (new_state == 'SURVIVAL' and prev_state == 'SURVIVAL'
            and monthly_expenses > 0 and cash < monthly_expenses * 0.5):
        new_state = 'CRISIS'

    # 7. UPDATE the column.
    conn.execute(
        "UPDATE promotions SET ai_budget_state=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE promotion_id=?",
        (new_state, promotion_id),
    )

    # 8. CRISIS handling (if entered): cut top salaries + cancel event +
    #    news item. If still in CRISIS next month → ownership change.
    if new_state == 'CRISIS':
        _handle_crisis(conn, promotion_id, current_date, prev_state)

    return new_state


def _compute_monthly_expenses(conn, promotion_id, current_date):
    """Return the promo's monthly expenses (fighter + staff + venue).

    Per arch doc §3.6 step 1:
      - Fighter salaries: SUM(contracts.salary) WHERE status='active'
        AND target_type='fighter' AND promotion_id=?. Divided by 12
        (the salary column is annual).
      - Staff salaries: SUM(staff_contracts-linked contracts.salary)
        WHERE target_type='staff' AND status='active' AND
        promotion_id=?. Divided by 12.
      - Venue costs: SUM(finance_transactions.amount) WHERE
        transaction_type='expense' AND description LIKE '%venue%' in
        the last 90 days, divided by 3 (monthly average).

    Returns float (monthly expenses in dollars). Returns 0.0 if the
    promo has no expenses (shouldn't happen post-v3.14.0 backfill).
    """
    # Fighter salaries (annual → monthly).
    fighter_row = conn.execute(
        "SELECT COALESCE(SUM(c.salary), 0) FROM contracts c "
        "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE c.promotion_id = ? AND c.status = 'active' "
        "AND c.contract_target_type = 'fighter'",
        (promotion_id,),
    ).fetchone()
    fighter_salaries_annual = float(fighter_row[0]) if fighter_row else 0.0

    # Staff salaries (annual → monthly). The v3.14.0 backfill
    # populates these for all 75 promo-bound staff.
    staff_row = conn.execute(
        "SELECT COALESCE(SUM(c.salary), 0) FROM contracts c "
        "JOIN staff_contracts sc ON sc.contract_id = c.contract_id "
        "WHERE c.promotion_id = ? AND c.status = 'active' "
        "AND c.contract_target_type = 'staff'",
        (promotion_id,),
    ).fetchone()
    staff_salaries_annual = float(staff_row[0]) if staff_row else 0.0

    # Venue costs in last 90 days (monthly average).
    venue_row = conn.execute(
        "SELECT COALESCE(SUM(ABS(ft.amount)), 0) FROM finance_transactions ft "
        "WHERE ft.promotion_id = ? "
        "AND ft.transaction_type = 'expense' "
        "AND ft.transaction_date >= date(?, '-90 days') "
        "AND (ft.description LIKE '%venue%' OR ft.description LIKE '%facility%')",
        (promotion_id, current_date),
    ).fetchone()
    venue_quarterly = float(venue_row[0]) if venue_row else 0.0

    monthly = (fighter_salaries_annual / 12.0) + (staff_salaries_annual / 12.0) + (venue_quarterly / 3.0)
    return monthly


def compute_cash_runway(conn, promotion_id):
    """Return the cash runway in months (current_cash / monthly_expenses).

    Phase 3 helper. Convenience wrapper around
    `_compute_monthly_expenses` + `promotion_cash`.

    Returns:
        Float (months). Returns 999.0 if monthly_expenses is 0
        (a promo with no roster + no staff has infinite runway).
    """
    from services.rival_ai._shared import current_sim_date, promotion_cash
    cur_date = current_sim_date(conn)
    if not cur_date:
        return 999.0
    monthly = _compute_monthly_expenses(conn, promotion_id, cur_date)
    if monthly <= 0:
        return 999.0
    cash = promotion_cash(conn, promotion_id)
    return cash / monthly


def handle_crisis(conn, promotion_id, current_date=None):
    """CRISIS state handler — public alias for the internal
    `_handle_crisis` so test code can call it directly.

    See `_handle_crisis` for the full behaviour.
    """
    if current_date is None:
        from services.rival_ai._shared import current_sim_date
        current_date = current_sim_date(conn)
    prev_state_row = conn.execute(
        "SELECT ai_budget_state FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    prev_state = (prev_state_row[0] if prev_state_row else None) or 'CRISIS'
    _handle_crisis(conn, promotion_id, current_date, prev_state)


def _handle_crisis(conn, promotion_id, current_date, prev_state):
    """Internal CRISIS handler — top-3 salary cuts + staff trim +
    event cancellation + news item + ownership-change escape hatch.

    Per arch doc §3.6 step 4:
      - All signings halted (signing_agent reads ai_budget_state).
      - Top-3 highest-salary fighters put on cut list immediately.
      - All staff except 1 scout + 1 GM put on cut list.
      - Next scheduled event cancelled (status → 'cancelled').
      - News item: "{Promo} in financial crisis — major cuts expected."
      - If after another month still in CRISIS → ownership change
        (cosmetic news event) + $2M-$5M cash injection.

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the promo in crisis.
        current_date: sim date string.
        prev_state: the promo's previous ai_budget_state. If 'CRISIS',
            we trigger the ownership-change escape hatch.
    """
    from services.rival_ai._shared import write_news_item
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"

    if prev_state == 'CRISIS':
        # Already in CRISIS last month — trigger ownership change.
        # Cash injection + news item. Avoids true bankruptcy.
        rng = _random.Random()
        injection = rng.randint(CRISIS_CASH_INJECTION_MIN, CRISIS_CASH_INJECTION_MAX)
        conn.execute(
            "UPDATE promotions SET current_cash = current_cash + ?, "
            "ownership_type = 'new_ownership', "
            "updated_at = CURRENT_TIMESTAMP WHERE promotion_id = ?",
            (injection, promotion_id),
        )
        # Record the cash injection as a finance_transaction.
        conn.execute(
            "INSERT INTO finance_transactions "
            "(promotion_id, transaction_type, amount, description, transaction_date) "
            "VALUES (?, 'income', ?, 'Ownership change cash injection', ?)",
            (promotion_id, injection, current_date),
        )
        write_news_item(
            conn,
            headline=f"New ownership group takes over {promo_name}",
            body=(f"{promo_name} has been acquired by a new ownership group, "
                  f"bringing a major cash injection to stabilise the promotion "
                  f"after months of financial crisis."),
            topic=CRISIS_OWNERSHIP_TOPIC,
            sentiment='positive',
            promotion_id=promotion_id,
            published_at=current_date,
        )
        # Reset the state to CONSERVATIVE (the cash injection buys time).
        conn.execute(
            "UPDATE promotions SET ai_budget_state='CONSERVATIVE' "
            "WHERE promotion_id=?",
            (promotion_id,),
        )
        return

    # First month of CRISIS: cut top-3 salaries + cancel event + news item.
    # 1. Top-3 highest-salary fighters → release.
    top_fighters = conn.execute(
        "SELECT fc.fighter_id, c.contract_id, c.salary, "
        "f.first_name || ' ' || f.last_name "
        "FROM contracts c "
        "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE c.promotion_id = ? AND c.status = 'active' "
        "AND c.contract_target_type = 'fighter' "
        "ORDER BY c.salary DESC LIMIT 3",
        (promotion_id,),
    ).fetchall()
    for fighter_id, contract_id, salary, fname in top_fighters:
        conn.execute(
            "UPDATE fighters SET current_promotion_id = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
            (fighter_id,),
        )
        conn.execute(
            "UPDATE contracts SET status = 'terminated', "
            "updated_at = CURRENT_TIMESTAMP WHERE contract_id = ?",
            (contract_id,),
        )
        write_news_item(
            conn,
            headline=f"{promo_name} releases {fname} amid financial crisis",
            body=(f"{fname} has been released by {promo_name} as the "
                  f"promotion slashes costs to survive a financial crisis."),
            topic='release',
            sentiment='negative',
            promotion_id=promotion_id,
            fighter_id=fighter_id,
            published_at=current_date,
        )

    # 2. Cancel the next scheduled event (status → 'cancelled').
    next_event = conn.execute(
        "SELECT event_id, event_name FROM events "
        "WHERE promotion_id = ? AND status = 'scheduled' "
        "ORDER BY event_date ASC LIMIT 1",
        (promotion_id,),
    ).fetchone()
    if next_event:
        event_id, event_name = next_event
        conn.execute(
            "UPDATE events SET status='cancelled', "
            "updated_at=CURRENT_TIMESTAMP WHERE event_id=?",
            (event_id,),
        )

    # 3. News item: "{Promo} in financial crisis — major cuts expected."
    write_news_item(
        conn,
        headline=f"{promo_name} in financial crisis",
        body=(f"{promo_name} has entered a financial crisis. Top-paid "
              f"fighters have been released and the next event has been "
              f"cancelled as the promotion fights to survive."),
        topic=CRISIS_WARNING_TOPIC,
        sentiment='negative',
        promotion_id=promotion_id,
        event_id=next_event[0] if next_event else None,
        published_at=current_date,
    )


def apply_state_modifiers(archetype, budget_state):
    """Return a modified archetype dict with state-driven adjustments.

    Per arch doc §3.6 step 3:
        SURVIVAL:        card_size - 2, no signings, cut_aggr × 1.5
        CONSERVATIVE:    card_size - 1, critical-gap-only signings,
                         bid_premium × 0.5, cut_aggr × 1.2
        NORMAL:          archetype default (no modification)
        EXPANSION:       card_size + 1, bid_premium × 1.2, cut_aggr × 0.8
        CRISIS:          see handle_crisis (overrides everything)

    Args:
        archetype: the frozen archetype dict (one of ARCHETYPES).
        budget_state: one of BUDGET_STATES (case-insensitive — we
            normalize to UPPERCASE).

    Returns:
        A new (mutable) dict with the modifiers applied. Does NOT
        mutate the input archetype.
    """
    if not archetype:
        return dict(archetype or {})
    out = dict(archetype)
    state = (budget_state or 'NORMAL').upper()

    if state == 'SURVIVAL':
        # Smaller cards, no signings (signing_potential_floor = inf),
        # more aggressive cutting.
        cmin, cmax = archetype['card_size']
        out['card_size'] = (max(3, cmin - 2), max(3, cmax - 2))
        out['signing_potential_floor'] = 999  # impossibly high → no FAs match
        out['cut_aggressiveness'] = min(0.95, archetype['cut_aggressiveness'] * 1.5)
        out['bid_premium_pct'] = -0.50  # never bid; even if forced, walk away
    elif state == 'CONSERVATIVE':
        cmin, cmax = archetype['card_size']
        out['card_size'] = (max(3, cmin - 1), max(3, cmax - 1))
        out['bid_premium_pct'] = archetype['bid_premium_pct'] * 0.5
        out['cut_aggressiveness'] = min(0.95, archetype['cut_aggressiveness'] * 1.2)
    elif state == 'EXPANSION':
        cmin, cmax = archetype['card_size']
        out['card_size'] = (cmin + 1, cmax + 1)
        out['bid_premium_pct'] = archetype['bid_premium_pct'] * 1.2
        out['cut_aggressiveness'] = max(0.05, archetype['cut_aggressiveness'] * 0.8)
    elif state == 'CRISIS':
        # CRISIS overrides — same as SURVIVAL but even harsher. The
        # handle_crisis path already cancelled events + cut salaries;
        # we just make sure the archetype constants reflect "no new
        # spending, smallest possible cards".
        cmin, cmax = archetype['card_size']
        out['card_size'] = (3, max(3, cmin - 2))
        out['signing_potential_floor'] = 999
        out['cut_aggressiveness'] = 0.90
        out['bid_premium_pct'] = -0.50
    # NORMAL: no modification (out already equals archetype).
    return out


def get_budget_state(conn, promotion_id):
    """Return the promo's current ai_budget_state (UPPERCASE).

    Convenience reader used by event_scheduler / signing_agent /
    cutting_agent / staff_manager. Defaults to 'NORMAL' if NULL.
    """
    row = conn.execute(
        "SELECT ai_budget_state FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if row is None or not row[0]:
        return 'NORMAL'
    return row[0].upper()


def get_modified_archetype(conn, promotion_id):
    """Return the (archetype, modified_archetype, budget_state) triple.

    Convenience wrapper: looks up the promo's archetype + budget_state
    + applies the state modifiers + applies the recency bias. This is
    the SINGLE CALL most decision modules need at the start of their
    decision function — gives them the fully-modified archetype dict
    to read constants from.

    Returns:
        Tuple (base_archetype, modified_archetype, budget_state).
        base_archetype is the frozen dict from ARCHETYPES.
        modified_archetype is a new mutable dict with state + recency
        applied. budget_state is the current ai_budget_state string.
    """
    from services.rival_ai.archetypes import get_archetype
    from services.rival_ai._shared import current_sim_date
    from services.rival_ai.imperfection import (
        recency_bias_modifier, apply_recency_to_archetype,
    )
    base = get_archetype(promotion_id, conn)
    if base is None:
        return None, None, 'NORMAL'
    state = get_budget_state(conn, promotion_id)
    state_modified = apply_state_modifiers(base, state)
    cur_date = current_sim_date(conn)
    recency = recency_bias_modifier(conn, promotion_id, cur_date)
    final = apply_recency_to_archetype(state_modified, recency)
    return base, final, state
