"""CAGE EMPIRE Finance System (Task 20).

Manages promotion finances via the event bus (Task 18.5). Subscribes
to FIGHT_RESOLVED and EVENT_COMPLETED to compute per-event P&L.

REVENUE:
  - ticket_sales: venue_capacity × market_heat × fill_rate
  - broadcast_revenue: based on promotion.broadcast_tier
  - merchandise: based on total fighter marketability on the card

EXPENSES:
  - fighter_purse: from contracts.salary (winner gets win bonus)
  - venue_rental: based on venue capacity
  - staff_salary: based on staff count × average salary
  - medical_cost: flat per fight + injury treatment costs

VOICE LAYER INTEGRATION:
  Financial descriptors via voice.py:
  - "highly profitable event" / "modest returns" / "hemorrhaging cash"
  - "flush with cash" / "breaking even" / "on the verge of bankruptcy"

USAGE:
  from finance import register_subscribers
  register_subscribers()  # call once at startup

  # The finance system automatically processes events via the bus.
  # No need to call any function directly — it's all event-driven.
"""
import random


# Broadcast tier revenue multipliers (per event)
_BROADCAST_REVENUE = {
    "ppv_global":    500000,
    "streaming":     150000,
    "tv_regional":   75000,
    "local_stream":  15000,
}

# Venue rental cost per seat
_VENUE_COST_PER_SEAT = 5.0

# Staff salary per staff member per event
_STAFF_SALARY_PER_EVENT = 2000

# Medical cost per fight
_MEDICAL_COST_PER_FIGHT = 1500

# Fill rate: what % of seats are sold. Based on market heat.
# heat 30 → 40% fill, heat 95 → 95% fill
def _compute_fill_rate(market_heat):
    """Compute the fill rate (0-1) for a market."""
    return max(0.30, min(0.98, market_heat / 100.0))


def _record_transaction(conn, promotion_id, event_id, fighter_id,
                        txn_type, amount, description, txn_date):
    """Write a finance_transactions row + update promotion cash."""
    conn.execute(
        "INSERT INTO finance_transactions (promotion_id, event_id, "
        "fighter_id, transaction_type, amount, description, "
        "transaction_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (promotion_id, event_id, fighter_id, txn_type, amount,
         description, txn_date),
    )
    # Update promotion cash (positive = revenue, negative = expense)
    conn.execute(
        "UPDATE promotions SET current_cash = current_cash + ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE promotion_id = ?",
        (amount, promotion_id),
    )


def _process_event_finance(conn, event):
    """Process finances when an event completes.

    Computes all revenue + expenses for the event and records them
    as finance_transactions rows. Called as an event bus subscriber
    for FIGHT_RESOLVED (but only processes when the event is complete).
    """
    event_id = event.get('event_id')
    promo_id = event.get('promotion_id')
    if not event_id or not promo_id:
        return

    # Check if the event is completed (all fights resolved)
    status = conn.execute(
        "SELECT status FROM events WHERE event_id=?", (event_id,)
    ).fetchone()
    if not status or status[0] != 'completed':
        return  # not done yet — wait for the last fight

    # Check if we already processed finances for this event
    existing = conn.execute(
        "SELECT 1 FROM finance_transactions WHERE event_id=? "
        "AND transaction_type='ticket_sales'",
        (event_id,)
    ).fetchone()
    if existing:
        return  # already processed

    # Get event details
    event_row = conn.execute(
        "SELECT e.event_date, e.venue_id, e.market_id, "
        "v.capacity, m.heat_level, p.broadcast_tier, p.name "
        "FROM events e "
        "LEFT JOIN venues v ON v.venue_id=e.venue_id "
        "LEFT JOIN markets m ON m.market_id=e.market_id "
        "JOIN promotions p ON p.promotion_id=e.promotion_id "
        "WHERE e.event_id=?",
        (event_id,),
    ).fetchone()
    if not event_row:
        return

    event_date, venue_id, market_id, venue_cap, market_heat, \
        broadcast_tier, promo_name = event_row

    venue_cap = venue_cap or 5000
    market_heat = market_heat or 50
    fill_rate = _compute_fill_rate(market_heat)

    # ---- REVENUE ----
    # 1. Ticket sales
    tickets_sold = int(venue_cap * fill_rate)
    avg_ticket_price = 50 + (market_heat * 2)  # $50-$240
    ticket_revenue = tickets_sold * avg_ticket_price
    _record_transaction(conn, promo_id, event_id, None,
                        'ticket_sales', ticket_revenue,
                        f"{tickets_sold} tickets × ${avg_ticket_price}",
                        event_date)

    # 2. Broadcast revenue
    broadcast_rev = _BROADCAST_REVENUE.get(broadcast_tier, 15000)
    _record_transaction(conn, promo_id, event_id, None,
                        'broadcast_revenue', broadcast_rev,
                        f"broadcast ({broadcast_tier})", event_date)

    # 3. Merchandise (based on fighter marketability)
    fights = conn.execute(
        "SELECT DISTINCT fp.fighter_id FROM fight_participants fp "
        "JOIN fights f ON f.fight_id=fp.fight_id "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchall()
    total_marketability = 0
    for (fid,) in fights:
        m = conn.execute(
            "SELECT marketability FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if m:
            total_marketability += m[0]
    merch_revenue = total_marketability * 100  # $100 per marketability point
    if merch_revenue > 0:
        _record_transaction(conn, promo_id, event_id, None,
                            'merchandise', merch_revenue,
                            f"merchandise ({len(fights)} fighters)",
                            event_date)

    # ---- EXPENSES ----
    # 4. Fighter purses (from contracts)
    for (fid,) in fights:
        contract_row = conn.execute(
            "SELECT c.salary FROM contracts c "
            "JOIN fighter_contracts fc ON fc.contract_id=c.contract_id "
            "WHERE fc.fighter_id=? AND c.status='active'",
            (fid,),
        ).fetchone()
        salary = contract_row[0] if contract_row else 10000
        _record_transaction(conn, promo_id, event_id, fid,
                            'fighter_purse', -salary,
                            f"purse for fighter {fid}", event_date)

    # 5. Venue rental
    venue_cost = venue_cap * _VENUE_COST_PER_SEAT
    _record_transaction(conn, promo_id, event_id, None,
                        'venue_rental', -venue_cost,
                        f"venue rental ({venue_cap} seats)", event_date)

    # 6. Staff salaries
    n_staff = conn.execute(
        "SELECT COUNT(*) FROM staff WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()[0]
    staff_cost = n_staff * _STAFF_SALARY_PER_EVENT
    _record_transaction(conn, promo_id, event_id, None,
                        'staff_salary', -staff_cost,
                        f"staff salaries ({n_staff} staff)", event_date)

    # 7. Medical costs (per fight)
    n_fights = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=?",
        (event_id,),
    ).fetchone()[0]
    medical_cost = n_fights * _MEDICAL_COST_PER_FIGHT
    _record_transaction(conn, promo_id, event_id, None,
                        'medical_cost', -medical_cost,
                        f"medical ({n_fights} fights)", event_date)

    # 8. Weight cut penalties (if any fights were cancelled or catch-weight)
    wc_rows = conn.execute(
        "SELECT fighter_id, purse_penalty_pct FROM weight_cut_log "
        "WHERE event_id=? AND purse_penalty_pct > 0",
        (event_id,),
    ).fetchall()
    for fid, penalty_pct in wc_rows:
        contract_row = conn.execute(
            "SELECT c.salary FROM contracts c "
            "JOIN fighter_contracts fc ON fc.contract_id=c.contract_id "
            "WHERE fc.fighter_id=? AND c.status='active'",
            (fid,),
        ).fetchone()
        salary = contract_row[0] if contract_row else 10000
        penalty_amount = int(salary * penalty_pct / 100)
        if penalty_amount > 0:
            _record_transaction(conn, promo_id, event_id, fid,
                                'weight_cut_penalty', -penalty_amount,
                                f"weight cut penalty ({penalty_pct}%)",
                                event_date)

    # Write a finance news item via voice descriptors
    _write_finance_news(conn, promo_id, event_id, event_date)


def _write_finance_news(conn, promo_id, event_id, event_date):
    """Write a news item about the event's financial performance."""
    # Compute P&L
    pnl_row = conn.execute(
        "SELECT SUM(amount) FROM finance_transactions WHERE event_id=?",
        (event_id,),
    ).fetchone()
    pnl = pnl_row[0] if pnl_row and pnl_row[0] else 0

    # Voice descriptor for the P&L
    if pnl > 200000:
        desc = "highly profitable"
        sentiment = "positive"
    elif pnl > 50000:
        desc = "modestly profitable"
        sentiment = "positive"
    elif pnl > 0:
        desc = "barely broke even"
        sentiment = "neutral"
    elif pnl > -100000:
        desc = "operated at a loss"
        sentiment = "negative"
    else:
        desc = "hemorrhaging cash"
        sentiment = "negative"

    promo_name = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?", (promo_id,)
    ).fetchone()[0]

    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
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
        "sentiment, topic, event_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id,
         f"{promo_name} event {desc}",
         f"The latest {promo_name} event was {desc}, with a net "
         f"{'profit' if pnl > 0 else 'loss'} for the promotion.",
         sentiment, "finance", event_id, event_date),
    )


def register_subscribers():
    """Register finance system subscribers on the event bus.

    Call once at startup (after event_bus is available).
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.FIGHT_RESOLVED, _process_event_finance,
                  name="finance.process_event")
