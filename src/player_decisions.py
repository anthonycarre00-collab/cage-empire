"""CAGE EMPIRE — Player Decisions Log (Phase R, §6 Principle 4).

Append-only log of every player action whose consequence should
"echo" back to the player later. The Dashboard's "ECHOES" section
(src/interpretation/echoes_engine.py) and the Fighter Profile's
"Your History with [Fighter]" section both read from this log.

Per docs/REWARD_REVIEW.md §1.5 + §6 + Phase R brief:
  - The Agency reward is the weakest of GPT's 5 player rewards
    (3/10 on 3 of 4 screens) because the player's own past
    bookings/signings/cuts are never surfaced again.
  - Fix: log every player action (sign / cut / book / scout /
    staff moves / financial levers), then surface 2-3 echoes per
    Advance Day + per-fighter decision history.

Schema (added v3.16.0, see build_db._migrate_v3_16_0_add_player_
decisions_and_echoes):
  decision_id         PK AUTOINCREMENT
  decision_type       TEXT NOT NULL CHECK (10 values)
  target_fighter_id   INTEGER nullable
  target_staff_id     INTEGER nullable
  target_event_id     INTEGER nullable
  target_promo_id     INTEGER nullable
  decision_date       TEXT NOT NULL (sim date YYYY-MM-DD)
  context_json        TEXT (arbitrary per-decision context)
  created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

Public API:
  log_decision(conn, decision_type, target_fighter_id=None,
               target_staff_id=None, target_event_id=None,
               target_promo_id=None, context=None)
    → int decision_id (or None on failure)
  get_recent_decisions(conn, limit=50, decision_type=None)
    → list of dicts (most-recent-first)
  get_decisions_for_fighter(conn, fighter_id)
    → list of dicts (oldest-first — natural for a "your history
      with X" timeline)
  get_decisions_since(conn, days_back)
    → list of dicts (oldest-first — used by the Echoes engine to
      pick which past decisions to surface today)

CONVENTIONS compliance:
  §15 — Event Bus: this module does NOT subscribe to events. It's
        a pure helper called by app_web.py at the moment the player
        takes an action (synchronous, inline with the click handler).
  §17 — Cache vs Source: this is a SOURCE table (the player's own
        history), not a cache. Other modules may read it freely.
  §13 — Design Law: the Investment fantasy (the player's progress
        is preserved + acknowledged) requires the log to survive
        save/load. Save_load already dumps the entire DB, so this
        works for free.

Backfill (backfill_player_decisions_for_promo):
  Called once after the migration lands (or on first player_promo_id
  selection). Synthesizes 'sign' + 'cut' decisions from existing
  contracts + news_items so the echoes + per-fighter history aren't
  empty on the first Advance Day after a player picks a promo.
"""

import json
import sqlite3
from datetime import datetime, timedelta


# ----------------------------------------------------------------
# Decision type constants — match the CHECK constraint in the
# player_decisions table (build_db._migrate_v3_16_0_*). Exported
# so callers don't typo strings.
# ----------------------------------------------------------------
TYPE_SIGN = "sign"
TYPE_CUT = "cut"
TYPE_BOOK = "book"
TYPE_SCOUT = "scout"
TYPE_HIRE_STAFF = "hire_staff"
TYPE_FIRE_STAFF = "fire_staff"
TYPE_ASSIGN_STAFF = "assign_staff"
TYPE_SET_TICKET_PRICE = "set_ticket_price"
TYPE_SET_MARKETING = "set_marketing"
TYPE_NEGOTIATE_CONTRACT = "negotiate_contract"

ALL_TYPES = frozenset({
    TYPE_SIGN, TYPE_CUT, TYPE_BOOK, TYPE_SCOUT,
    TYPE_HIRE_STAFF, TYPE_FIRE_STAFF, TYPE_ASSIGN_STAFF,
    TYPE_SET_TICKET_PRICE, TYPE_SET_MARKETING, TYPE_NEGOTIATE_CONTRACT,
})


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _read_sim_date(conn):
    """Return the current sim date as a YYYY-MM-DD string.

    Falls back to None if simulation_clock is missing — log_decision
    then returns None (the caller should defend against this but in
    practice the clock always exists once the world is built).
    """
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else None


def _row_to_dict(row):
    """Convert a player_decisions row tuple to a dict with sensible
    keys + a parsed `context` field (dict, not raw JSON string)."""
    if not row:
        return None
    d = {
        "decision_id": row[0],
        "decision_type": row[1],
        "target_fighter_id": row[2],
        "target_staff_id": row[3],
        "target_event_id": row[4],
        "target_promo_id": row[5],
        "decision_date": row[6],
        "context_json": row[7],
        "created_at": row[8],
    }
    # Parse context_json → context (dict). Empty/invalid → {}.
    if d["context_json"]:
        try:
            d["context"] = json.loads(d["context_json"])
        except Exception:
            d["context"] = {}
    else:
        d["context"] = {}
    return d


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def log_decision(conn, decision_type, target_fighter_id=None,
                 target_staff_id=None, target_event_id=None,
                 target_promo_id=None, context=None,
                 decision_date=None):
    """Append a row to player_decisions.

    Args:
        conn: sqlite3.Connection. Caller commits (this function does
            NOT call conn.commit() — it's designed to compose with
            the caller's existing transaction, e.g. sign_free_agent
            inserts the contract + the player_decisions row in one
            atomic transaction).
        decision_type: one of the TYPE_* constants. The CHECK
            constraint will reject anything else.
        target_fighter_id: optional int. NULL for staff / financial
            decisions.
        target_staff_id: optional int. NULL for fighter decisions.
        target_event_id: optional int. For 'book' decisions.
        target_promo_id: optional int. For cross-promo context (e.g.
            a rival promotion signing a fighter you cut).
        context: optional dict. Arbitrary per-decision context —
            signing cost, opponent id, offer terms, etc. Serialized
            to JSON. NEVER include raw potential ints (CONVENTIONS §14
            — the player shouldn't see "potential: 87" even in logs
            that might leak to the UI).
        decision_date: optional YYYY-MM-DD string. If None, reads
            the current sim date from the clock. Useful for backfill.

    Returns:
        int decision_id of the inserted row, or None on failure
        (invalid decision_type, missing clock, etc.).
    """
    if decision_type not in ALL_TYPES:
        print(f"[player_decisions] WARN: invalid decision_type "
              f"'{decision_type}' — must be one of {sorted(ALL_TYPES)}",
              flush=True)
        return None

    if decision_date is None:
        decision_date = _read_sim_date(conn)
    if not decision_date:
        # No clock — can't log. Defensive: caller should defend too.
        return None

    ctx_json = None
    if context is not None:
        try:
            ctx_json = json.dumps(context, default=str)
        except Exception:
            ctx_json = None

    try:
        cur = conn.execute(
            "INSERT INTO player_decisions "
            "(decision_type, target_fighter_id, target_staff_id, "
            " target_event_id, target_promo_id, decision_date, "
            " context_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (decision_type,
             target_fighter_id, target_staff_id,
             target_event_id, target_promo_id,
             decision_date, ctx_json),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError as e:
        # CHECK constraint violation, etc. — log + return None.
        print(f"[player_decisions] WARN: insert failed for "
              f"type={decision_type} date={decision_date}: {e}",
              flush=True)
        return None
    except Exception as e:
        print(f"[player_decisions] WARN: unexpected error: {e}",
              flush=True)
        return None


def get_recent_decisions(conn, limit=50, decision_type=None):
    """Return the N most recent decisions (newest-first).

    Args:
        conn: sqlite3.Connection.
        limit: int, default 50. Capped at 500 to keep query cheap.
        decision_type: optional filter (one of TYPE_*). None = all.

    Returns:
        list of dicts (see _row_to_dict). Empty list on error or if
        no rows match.
    """
    limit = max(1, min(int(limit or 50), 500))
    sql = ("SELECT decision_id, decision_type, target_fighter_id, "
           "target_staff_id, target_event_id, target_promo_id, "
           "decision_date, context_json, created_at "
           "FROM player_decisions")
    params = []
    if decision_type is not None:
        sql += " WHERE decision_type = ?"
        params.append(decision_type)
    sql += " ORDER BY decision_date DESC, decision_id DESC LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        print(f"[player_decisions] get_recent_decisions failed: {e}",
              flush=True)
        return []
    return [_row_to_dict(r) for r in rows]


def get_decisions_for_fighter(conn, fighter_id):
    """Return every decision that targeted `fighter_id` (oldest-first).

    Used by the Fighter Profile's "Your History with [Fighter]"
    section (Phase R §4). Returns a chronological timeline of every
    sign / cut / book / scout decision the player has made about
    this fighter.

    Args:
        conn: sqlite3.Connection.
        fighter_id: int.

    Returns:
        list of dicts (see _row_to_dict). Empty list on error or if
        no decisions exist for this fighter.
    """
    try:
        rows = conn.execute(
            "SELECT decision_id, decision_type, target_fighter_id, "
            "target_staff_id, target_event_id, target_promo_id, "
            "decision_date, context_json, created_at "
            "FROM player_decisions "
            "WHERE target_fighter_id = ? "
            "ORDER BY decision_date ASC, decision_id ASC",
            (fighter_id,),
        ).fetchall()
    except Exception as e:
        print(f"[player_decisions] get_decisions_for_fighter failed: "
              f"{e}", flush=True)
        return []
    return [_row_to_dict(r) for r in rows]


def get_decisions_since(conn, days_back=120):
    """Return all decisions from the last N sim days (oldest-first).

    Used by the Echoes engine (src/interpretation/echoes_engine.py)
    to pick which past decisions to surface today. The default 120-day
    window matches the Echoes engine's "decay horizon" — decisions
    older than 120 days have decayed to near-zero echo weight and
    aren't worth re-surfacing.

    Args:
        conn: sqlite3.Connection.
        days_back: int, default 120.

    Returns:
        list of dicts (see _row_to_dict). Empty list on error or if
        no decisions exist in the window.
    """
    days_back = max(1, int(days_back or 120))
    try:
        rows = conn.execute(
            "SELECT decision_id, decision_type, target_fighter_id, "
            "target_staff_id, target_event_id, target_promo_id, "
            "decision_date, context_json, created_at "
            "FROM player_decisions "
            "WHERE decision_date >= date("
            "  (SELECT simulation_clock.current_date "
            "   FROM simulation_clock WHERE clock_id=1), "
            "  ?) "
            "ORDER BY decision_date ASC, decision_id ASC",
            (f"-{days_back} days",),
        ).fetchall()
    except Exception as e:
        print(f"[player_decisions] get_decisions_since failed: {e}",
              flush=True)
        return []
    return [_row_to_dict(r) for r in rows]


# ----------------------------------------------------------------
# Backfill — synthesize historical decisions from existing data.
# Called once after the migration lands, or on first player_promo_id
# selection. Idempotent: a backfill marker row prevents re-runs.
# ----------------------------------------------------------------

_BACKFILL_MARKER_TYPE = "_backfill_marker"  # not in CHECK — stored in context_json

_BACKFILL_CONTEXT_KEY = "_backfill_run"


def backfill_player_decisions_for_promo(conn, player_promo_id,
                                        force=False):
    """Synthesize historical sign/cut decisions for the player's promo.

    The world DB has 60 fighters on promo 1's roster (and a handful
    of terminated contracts for fighters now free agents). Without
    a backfill, the Echoes section + "Your History" section would
    be empty on the first Advance Day after the player picks a promo
    — the player wouldn't see echoes of their existing roster.

    Backfill rules (per Phase R brief):
      - For each fighter currently on the player's roster: log a
        'sign' decision with decision_date = the fighter's earliest
        active contract.start_date for that promo (or, if no contract
        exists, the sim clock date — defensive).
      - For each fighter currently a free agent with a terminated
        contract for this promo: log a 'cut' decision with
        decision_date = the contract.end_date (or updated_at).

    Idempotency: the first backfill run inserts a single
    'sign' decision with context={"_backfill_run": True,
    "promo_id": player_promo_id}. Subsequent calls check for that
    marker and exit early unless force=True.

    Args:
        conn: sqlite3.Connection. Caller commits.
        player_promo_id: int. The player's promotion_id.
        force: bool, default False. If True, re-run even if the
            backfill marker already exists.

    Returns:
        dict with counts: {"signs_backfilled": N, "cuts_backfilled": M,
                           "skipped": bool}.
    """
    if not player_promo_id:
        return {"signs_backfilled": 0, "cuts_backfilled": 0, "skipped": True}

    # Idempotency check: look for the backfill marker row.
    if not force:
        existing = conn.execute(
            "SELECT decision_id FROM player_decisions "
            "WHERE context_json LIKE ? LIMIT 1",
            (f'%"{_BACKFILL_CONTEXT_KEY}": true%',),
        ).fetchone()
        if existing:
            return {"signs_backfilled": 0, "cuts_backfilled": 0,
                    "skipped": True}

    sim_date = _read_sim_date(conn)
    signs = 0
    cuts = 0

    # ---- Backfill 'sign' decisions for current roster ----
    # Find every fighter currently on the player's roster + their
    # earliest active contract start_date for that promo.
    roster_rows = conn.execute(
        "SELECT f.fighter_id, "
        "  (SELECT MIN(c.start_date) "
        "   FROM fighter_contracts fc "
        "   JOIN contracts c ON c.contract_id = fc.contract_id "
        "   WHERE fc.fighter_id = f.fighter_id "
        "     AND c.promotion_id = ? "
        "     AND c.status = 'active') AS earliest_start "
        "FROM fighters f "
        "WHERE f.current_promotion_id = ? "
        "  AND f.is_active = 1",
        (player_promo_id, player_promo_id),
    ).fetchall()
    for fid, earliest_start in roster_rows:
        sign_date = earliest_start or sim_date
        log_decision(
            conn, TYPE_SIGN,
            target_fighter_id=fid,
            target_promo_id=player_promo_id,
            decision_date=sign_date,
            context={"backfilled": True, "promo_id": player_promo_id},
        )
        signs += 1

    # ---- Backfill 'cut' decisions for terminated contracts ----
    # Find every fighter with a terminated contract for this promo
    # who is currently a free agent (current_promotion_id IS NULL).
    # Use contract.end_date as the cut date (or updated_at as fallback).
    cut_rows = conn.execute(
        "SELECT fc.fighter_id, c.end_date, c.updated_at "
        "FROM fighter_contracts fc "
        "JOIN contracts c ON c.contract_id = fc.contract_id "
        "JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE c.promotion_id = ? "
        "  AND c.status = 'terminated' "
        "  AND f.current_promotion_id IS NULL "
        "  AND f.is_active = 1 "
        "  AND f.is_retired = 0",
        (player_promo_id,),
    ).fetchall()
    for fid, end_date, updated_at in cut_rows:
        cut_date = end_date or (updated_at or sim_date)
        log_decision(
            conn, TYPE_CUT,
            target_fighter_id=fid,
            target_promo_id=player_promo_id,
            decision_date=cut_date,
            context={"backfilled": True, "promo_id": player_promo_id},
        )
        cuts += 1

    # ---- Write the backfill marker (so we don't re-run) ----
    log_decision(
        conn, TYPE_SIGN,  # use any valid type for the marker
        target_promo_id=player_promo_id,
        decision_date=sim_date,
        context={_BACKFILL_CONTEXT_KEY: True,
                 "promo_id": player_promo_id,
                 "signs": signs, "cuts": cuts},
    )

    return {"signs_backfilled": signs, "cuts_backfilled": cuts,
            "skipped": False}
