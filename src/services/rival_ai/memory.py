"""CAGE EMPIRE Rival AI — Memory (Task ID HW10-W21W22).

W21/W22 feedback from GPT:
  W21 — "Rival AI should react to its own previous results."
  W22 — "Rival promotions should remember past interactions."

The rival AI used to be STATELESS PER TICK — every rival promo
scheduled events, signed free agents, and resolved fights without
remembering its own past results, bidding wars lost, fighters
signed/released, or title histories. This module gives every rival
promo a memory log (rival_ai_memory table, v3.34.0).

Each row is one memory of a specific type:
  event_result       — promo's event resolved (with rating + profit)
  signing_missed     — promo showed intent but lost the FA
  signing_won        — promo signed a free agent
  title_loss         — promo's champion was dethroned
  title_win          — promo crowned a new champion
  bidding_war_lost   — promo lost a bidding war to another promo
  bidding_war_won    — promo won a bidding war
  fighter_released   — promo released a fighter
  rivalry_fuelled    — promo gained a rivalry boost (e.g. on a
                       competitor's bankruptcy)

Salience (0..100, default 50) decays -1/week; rows at salience=0 are
DELETED (forgotten — old memories shouldn't bloat the table).

This module is split into:
  - WRITERS  — `write_memory` + helpers called by event-bus
               subscribers in src/rival_ai.py (one writer per memory
               type, with the right default salience).
  - READERS  — defensive lookup helpers used by the decision
               functions in event_scheduler / signing_agent /
               cutting_agent. Readers NEVER raise — they return
               neutral defaults on any DB error so a memory read
               failure can't crash the rival AI loop.
  - DECAY    — `decay_all_memories`, called weekly by a TICK_ADVANCED
               subscriber in src/rival_ai.py. Single UPDATE + DELETE
               per week — O(rows) but bounded by the weekly decay
               (rows that hit 0 are deleted, so the table reaches
               steady-state at ~1 year × promo_count × memories/week).

CONVENTIONS compliance:
  §5  — One table-group per task. This module owns rival_ai_memory
        (added v3.34.0). No other tables touched.
  §13 — Design Law: Conflict + Puppet Master + Empire Builder —
        rival promos now act on their own past results (don't book
        after a flop, don't lose the next bidding war, cut the
        dethroned champion). The world feels alive across promos.
  §14 — Voice Layer: context_json is internal state, never rendered
        in the UI directly. The rival AI's memory influences its
        decisions, which manifest as news items / events / signings
        that already go through the voice layer.
  §15 — Event Bus: writers are called from event-bus subscribers
        in src/rival_ai.py. No new event types. The decay function
        is called from a TICK_ADVANCED subscriber.
"""

import json


# ----------------------------------------------------------------
# Default salience by memory_type.
#
# Writers can override per-call, but these defaults reflect how
# strongly each memory should influence future decisions:
#   title_win       = 80  (champions are remembered a long time)
#   title_loss      = 70  (the dethroning stings — guides cutting)
#   bidding_war_lost= 60  (don't lose the next one — decays in ~60w)
#   bidding_war_won = 60  (the win is a confidence boost)
#   event_result    = 50  (neutral — record + let reader judge flop)
#   rivalry_fuelled = 50  (neutral — record the bankruptcy signal)
#   signing_won     = 40  (mild — the fighter's here now, not a memory)
#   fighter_released= 40  (mild — the fighter's gone, low influence)
#   signing_missed  = 30  (low — intent without result, weak signal)
# ----------------------------------------------------------------
DEFAULT_SALIENCE = {
    'event_result': 50,
    'signing_missed': 30,
    'signing_won': 40,
    'title_loss': 70,
    'title_win': 80,
    'bidding_war_lost': 60,
    'bidding_war_won': 60,
    'fighter_released': 40,
    'rivalry_fuelled': 50,
}


# ----------------------------------------------------------------
# WRITERS
# ----------------------------------------------------------------

def write_memory(conn, promotion_id, memory_type, memory_date,
                 target_fighter_id=None, target_promotion_id=None,
                 context=None, salience=None):
    """INSERT a rival_ai_memory row + return the new memory_id.

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the rival promo that owns this memory.
        memory_type: one of the 9 enums in the CHECK constraint.
        memory_date: sim date string 'YYYY-MM-DD'.
        target_fighter_id: optional — the fighter involved.
        target_promotion_id: optional — the OTHER promo involved.
        context: optional dict — arbitrary JSON-serializable context
            (e.g. for event_result: {event_id, wins, losses,
            fan_rating, profit}). Stored as context_json.
        salience: optional int 0..100. Defaults to DEFAULT_SALIENCE
            for the memory_type.

    Returns:
        The new memory_id (int), or None on failure.
    """
    if salience is None:
        salience = DEFAULT_SALIENCE.get(memory_type, 50)
    # Clamp salience to [0, 100] — defensive against callers passing
    # out-of-range values.
    salience = max(0, min(100, int(salience)))
    context_json = None
    if context is not None:
        try:
            # No `default=str` — non-serializable objects (datetime,
            # custom class instances) fall through to the except
            # branch + the context is stored as NULL. This is the
            # defensive choice: a non-serializable context is a
            # writer bug, and storing NULL keeps the memory row
            # intact (the readers tolerate missing context_json).
            context_json = json.dumps(context)
        except (TypeError, ValueError):
            # Defensive — if the context isn't JSON-serializable,
            # store None rather than crashing the subscriber.
            context_json = None
    cur = conn.execute(
        "INSERT INTO rival_ai_memory "
        "(promotion_id, memory_type, target_fighter_id, "
        " target_promotion_id, memory_date, context_json, salience) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (promotion_id, memory_type, target_fighter_id,
         target_promotion_id, memory_date, context_json, salience),
    )
    return cur.lastrowid


def record_event_result(conn, promotion_id, event_id, event_date,
                        wins=0, losses=0, fan_rating=None,
                        overall_rating=None, profit=None):
    """Write an 'event_result' memory for a promo whose event just
    resolved.

    Called by the EVENT_COMPLETED subscriber in src/rival_ai.py.
    Captures the event's outcome so the event_scheduler reader can
    detect a recent flop ("don't book another show too soon after a
    flop") and avoid stacking another card on a roster that just
    fought.

    All metrics are optional — the caller passes whatever it could
    compute cheaply. The context_json just stores the dict; readers
    tolerate missing keys.
    """
    context = {
        'event_id': event_id,
        'wins': wins,
        'losses': losses,
    }
    if fan_rating is not None:
        context['fan_rating'] = fan_rating
    if overall_rating is not None:
        context['overall_rating'] = overall_rating
    if profit is not None:
        context['profit'] = profit
    return write_memory(
        conn, promotion_id, 'event_result', event_date,
        context=context,
    )


def record_signing_won(conn, promotion_id, fighter_id, signing_date):
    """Write a 'signing_won' memory for a promo that just signed a
    free agent.

    Called by the FIGHTER_SIGNED subscriber in src/rival_ai.py.
    The fighter is now on the roster — the memory is a low-salience
    record that the promo DID make this move (useful for future
    "the promo hasn't signed anyone in 6 months" style queries).
    """
    return write_memory(
        conn, promotion_id, 'signing_won', signing_date,
        target_fighter_id=fighter_id,
    )


def record_bidding_war_lost(conn, promotion_id, fighter_id,
                             target_promo_id, loss_date):
    """Write a 'bidding_war_lost' memory for a rival promo that lost
    a bidding war (the fighter signed elsewhere).

    Called by the FIGHTER_SIGNED subscriber in src/rival_ai.py —
    when a fighter signs with promo X, the subscriber scans pending
    bidding_alerts rows for that fighter (where rival_promo_id != X)
    and writes a bidding_war_lost memory for each losing rival.
    This catches BOTH the player-counter-offer case (player wins)
    AND the direct-sign case (player signs via sign_free_agent,
    bypassing the alert).

    target_promo_id is the promo that actually signed the fighter —
    useful for future "we keep losing to RFL" queries.
    """
    context = {
        'fighter_id': fighter_id,
        'won_by_promotion_id': target_promo_id,
    }
    return write_memory(
        conn, promotion_id, 'bidding_war_lost', loss_date,
        target_fighter_id=fighter_id,
        target_promotion_id=target_promo_id,
        context=context,
    )


def record_title_win(conn, promotion_id, fighter_id, title_date,
                     weight_class_id=None):
    """Write a 'title_win' memory for a promo that crowned a new
    champion.

    Called by the TITLE_CHANGED subscriber in src/rival_ai.py.
    High salience (80) — title wins are long-remembered.
    """
    context = {'weight_class_id': weight_class_id} if weight_class_id else {}
    return write_memory(
        conn, promotion_id, 'title_win', title_date,
        target_fighter_id=fighter_id,
        context=context,
        salience=DEFAULT_SALIENCE['title_win'],
    )


def record_title_loss(conn, promotion_id, fighter_id, title_date,
                      weight_class_id=None):
    """Write a 'title_loss' memory for a promo whose champion was
    dethroned.

    Called by the TITLE_CHANGED subscriber in src/rival_ai.py. The
    target_fighter_id is the FORMER champion (the one who lost the
    belt) — the cutting_agent reader uses this to raise cut_risk for
    fighters who recently lost a title ("they've peaked").
    """
    context = {'weight_class_id': weight_class_id} if weight_class_id else {}
    return write_memory(
        conn, promotion_id, 'title_loss', title_date,
        target_fighter_id=fighter_id,
        context=context,
        salience=DEFAULT_SALIENCE['title_loss'],
    )


def record_rivalry_fuelled(conn, promotion_id, target_promo_id,
                            fuel_date, reason='bankruptcy'):
    """Write a 'rivalry_fuelled' memory for a promo that just gained
    a competitive edge (e.g. a rival went bankrupt).

    Called by the PROMOTION_BANKRUPT subscriber in src/rival_ai.py
    — writes one row per OTHER rival promo (the bankruptcy is an
    opportunity for competitors). Neutral salience (50).
    """
    context = {'reason': reason}
    return write_memory(
        conn, promotion_id, 'rivalry_fuelled', fuel_date,
        target_promotion_id=target_promo_id,
        context=context,
    )


def record_fighter_released(conn, promotion_id, fighter_id, release_date):
    """Write a 'fighter_released' memory for a promo that just cut a
    fighter.

    Called from the cutting_agent (after the cut commits). Low
    salience (40) — the fighter's gone, the memory is mostly a
    record of "we let this one go" for future re-signing decisions.
    """
    return write_memory(
        conn, promotion_id, 'fighter_released', release_date,
        target_fighter_id=fighter_id,
    )


# ----------------------------------------------------------------
# READERS
#
# All readers are DEFENSIVE — they catch any DB error and return a
# neutral default (None / 0 / False / []). A memory-read failure
# MUST NOT crash the rival AI loop (the world keeps spinning).
# ----------------------------------------------------------------

def _current_sim_date(conn):
    """Return the current sim date string, or None on failure."""
    try:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _shift_date(date_str, days):
    """Return date_str shifted by `days` days (int can be negative).

    Returns None on parse failure. Uses datetime — keeps the reader
    logic independent of SQLite's date() function (which works fine,
    but the explicit Python version is easier to read + test).
    """
    if not date_str:
        return None
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def recent_event_result_memory(conn, promotion_id, limit=3):
    """Return the promo's most recent 'event_result' memories
    (newest first).

    Used by event_scheduler.schedule_next_event_for_rival to detect
    a recent flop ("don't book another show too soon after a flop").
    The reader checks the most recent memory's overall_rating — if
    it's < 40 (a flop), the scheduler suppresses scheduling for one
    cycle.

    Returns:
        List of dicts: {memory_id, memory_date, salience, context}.
        `context` is the parsed JSON dict (or {} if missing/invalid).
        Empty list on any error.
    """
    try:
        rows = conn.execute(
            "SELECT memory_id, memory_date, salience, context_json "
            "FROM rival_ai_memory "
            "WHERE promotion_id=? AND memory_type='event_result' "
            "ORDER BY memory_date DESC LIMIT ?",
            (promotion_id, limit),
        ).fetchall()
        return [_decode_row(r) for r in rows]
    except Exception:
        return []


def _decode_row(row):
    """Decode a memory row into a dict with parsed context_json."""
    memory_id, memory_date, salience, context_json = row
    context = {}
    if context_json:
        try:
            context = json.loads(context_json)
        except (ValueError, TypeError):
            context = {}
    return {
        'memory_id': memory_id,
        'memory_date': memory_date,
        'salience': salience,
        'context': context,
    }


def recent_bidding_war_loss_count(conn, promotion_id, lookback_days=90):
    """Return the count of 'bidding_war_lost' memories within the
    last `lookback_days` sim days.

    Used by signing_agent._evaluate_one_promo to raise the
    offer_score ("we lost a bidding war recently — don't lose the
    next one"). The +0.05 boost per recent loss is applied in the
    signing_agent's _offer_score function.

    Returns:
        Int count. 0 on any error.
    """
    try:
        cur_date = _current_sim_date(conn)
        if not cur_date:
            return 0
        cutoff = _shift_date(cur_date, -lookback_days)
        if not cutoff:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM rival_ai_memory "
            "WHERE promotion_id=? AND memory_type='bidding_war_lost' "
            "AND memory_date >= ?",
            (promotion_id, cutoff),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def fighter_has_recent_title_loss(conn, promotion_id, fighter_id,
                                   lookback_days=180):
    """Return True if `fighter_id` has a 'title_loss' memory on this
    promo's books within the last `lookback_days` sim days.

    Used by cutting_agent.evaluate_cuts to raise cut_risk for
    fighters who recently lost a title ("they've peaked — cut them
    while they still have trade value"). The +20 cut_risk bump is
    applied in cutting_agent's _cut_risk_score.

    Returns:
        Bool. False on any error.
    """
    try:
        cur_date = _current_sim_date(conn)
        if not cur_date:
            return False
        cutoff = _shift_date(cur_date, -lookback_days)
        if not cutoff:
            return False
        row = conn.execute(
            "SELECT 1 FROM rival_ai_memory "
            "WHERE promotion_id=? AND memory_type='title_loss' "
            "AND target_fighter_id=? AND memory_date >= ? "
            "LIMIT 1",
            (promotion_id, fighter_id, cutoff),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def strongest_memories(conn, promotion_id, limit=5):
    """Return the promo's top-N highest-salience memories.

    Indexed by idx_rival_ai_memory_promo_salience. Useful for a
    future "what does this promo remember most strongly?" UI view.
    Currently unused (kept for future readers), but documents the
    index's purpose.

    Returns:
        List of dicts (newest first by memory_date, top-N by salience).
    """
    try:
        rows = conn.execute(
            "SELECT memory_id, memory_date, salience, context_json "
            "FROM rival_ai_memory "
            "WHERE promotion_id=? "
            "ORDER BY salience DESC, memory_date DESC LIMIT ?",
            (promotion_id, limit),
        ).fetchall()
        return [_decode_row(r) for r in rows]
    except Exception:
        return []


# ----------------------------------------------------------------
# DECAY
# ----------------------------------------------------------------

def decay_all_memories(conn):
    """Weekly TICK_ADVANCED subscriber — decay all memory salience
    by -1; DELETE rows whose salience hits 0 (forgotten).

    Per the spec: "Salience decay is weekly (current_day % 7 == 0),
    same as rivalries." The weekly gate is enforced by the caller
    (the subscriber in src/rival_ai.py calls _is_weekly_tick first,
    then this function).

    Single UPDATE + single DELETE per week. O(rows) but bounded —
    rows that hit 0 are deleted, so the table reaches steady-state
    at roughly:
        memories_per_week × 50 weeks = max rows
    (50 = default salience; higher-salience memories persist longer).

    Returns:
        (n_decayed, n_forgotten) — counts of rows updated + deleted.
    """
    cur = conn.execute(
        "UPDATE rival_ai_memory SET salience = salience - 1 "
        "WHERE salience > 0"
    )
    n_decayed = cur.rowcount if cur.rowcount is not None else 0
    cur = conn.execute(
        "DELETE FROM rival_ai_memory WHERE salience <= 0"
    )
    n_forgotten = cur.rowcount if cur.rowcount is not None else 0
    return (n_decayed, n_forgotten)
