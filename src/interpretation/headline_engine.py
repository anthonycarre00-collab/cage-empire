"""CAGE EMPIRE Headline Engine (Phase 2 Task 2.6).

Generates 4 MVP daily headlines from interpreted state, written to the
`daily_headlines` table at the end of the daily interpretation pass.

Per spec §8 (Headline Generation) + PHASE_2_PLAN §5 Task 2.6: each day,
generate:
  1. Top Story         — the biggest narrative of the day
  2. Upset of the Week — biggest upset in the last 7 days (if any)
  3. Fastest Rising    — fighter with the best momentum improvement
  4. Biggest Fall      — fighter with the worst momentum decline

The spec lists 8 headline types; we ship 4 in MVP (per §4 MVP Cut —
~40% content volume, ~80% player-perceived value). The 4 deferred
types (contract_drama, gym_of_month, veteran_watch, prospect_watch)
are tracked by the daily_headlines CHECK constraint (added in v3.11.0)
so adding them in Phase 3+ requires only engine code — no schema change.

Per CONVENTIONS §17.1: this module is the ONLY writer to the
`daily_headlines` cache table (alongside snapshot_cache, which is the
orchestrator). It NEVER writes to simulation tables (fighters, fight_
history, rankings, etc.). It READS from fighter_descriptors + fight_
history + rankings — those reads are safe (the interpretation layer
is allowed to read anything; it just can't WRITE to simulation tables).

Per CONVENTIONS §14: every headline_text + body_text is VOICE-LAYERED
— no raw numbers. "The fallen champion's reign crumbles" not
"record_wins went from 18 to 18-3". The voice layer (§14.3) is applied
via free-form voice phrases (NOT the "label||phrase" cache-column
format used by the other interpretation engines — the daily_headlines
table stores the text directly, not a label).

Per CONVENTIONS §17.5: the engine runs at the end of the daily pass
(after context_engine + career_phase + narrative_families + legacy
have all populated fighter_descriptors). MUST complete in <100ms for
the 4 headlines (4 small SELECTs against indexed columns — well under
the daily-pass budget).

Idempotency: each headline is written with INSERT OR REPLACE against
the UNIQUE (headline_date, headline_type) constraint. Re-running the
engine for the same date overwrites the 4 rows (the snapshot_version
column would increment if we tracked it — for MVP we just overwrite
with created_at=CURRENT_TIMESTAMP). This means the daily pass is safe
to re-run on the same day (e.g., during testing) without producing
duplicate headlines.

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  4 MVP headline types cut from the spec's 8 (per PHASE_2_PLAN
      §5, Task 2.6 + §4 MVP Cut). The 4 deferred types
      (contract_drama, gym_of_month, veteran_watch, prospect_watch)
      are CHECK'd in the daily_headlines schema (added in v3.11.0) so
      Phase 3+ can add them without a schema change.
  D2  Top Story priority order (first match wins):
        1. fallen_champion    — career_phase=declining + title_reigns>0
                                + momentum in (falling, collapsing)
        2. prodigy             — career_phase=prospect + momentum in
                                (very_high, high)
        3. cinderella_story    — career_phase=rising_contender +
                                momentum=very_high + age>=28
        4. veteran             — career_phase=veteran + momentum in
                                (stable, falling)
      The priority reflects narrative weight: a fallen champion IS
      the top story (the king is dead), a prodigy is next (the future
      is now), a cinderella story is third (the underdog is rising),
      a veteran is fourth (the old guard holds on). If NO fighter
      matches any family, the headline is skipped (NULL fighter_id,
      body_text="A quiet day across the promotions.").
  D3  Upset of the Week uses the rankings.rating column as the
      "expected winner" proxy. The fight_history table records
      (fighter_id, opponent_id, outcome) — we look for fights in the
      last 7 days where the WINNER had a LOWER rating than the LOSER
      (the upset). The "biggest" upset = the largest rating gap
      favoring the loser. If no fights in the last 7 days, this
      headline is skipped. The rating is rendered as a voice band
      ("underdog" / "heavy underdog" / "shocking upset") per §14.
  D4  Fastest Rising: query fighter_descriptors for momentum='very_
      high' AND career_phase='prospect' (the canonical prodigy
      criteria — a young fighter on a hot streak). If none match,
      fall back to momentum='high' AND career_phase='prospect' (a
      prospect on a smaller streak). If still none, fall back to
      momentum='very_high' (any fighter on a 5+ win streak). The
      fallback chain ensures the headline almost always has a
      subject. Deterministic tiebreaker: lowest fighter_id (stable
      across daily passes — no UI flickering).
  D5  Biggest Fall: query fighter_descriptors for momentum='collapsing'
      (3+ loss streak). If none match, fall back to momentum='falling'
      (2 loss streak). If still none, skip the headline (a day with
      no falling fighters is a quiet day). Same deterministic
      tiebreaker: lowest fighter_id.
  D6  Each headline is written with INSERT OR REPLACE against the
      UNIQUE (headline_date, headline_type) constraint. This makes
      the engine IDEMPOTENT — re-running for the same date replaces
      the 4 rows, doesn't duplicate them. Important for testing + for
      the daily pass (which may run multiple times on the same day
      during bulk-tick).
  D7  Voice phrases only (CONVENTIONS §14). The headline_text is
      short + punchy (think newspaper headline — verb-driven, no
      digits). The body_text is 1-2 sentences expanding on the
      headline. Both use voice bands, not raw numbers.
  D8  The engine NEVER raises — a failed headline write is caught +
      logged. The daily pass must not crash because one headline
      failed. Same defensive pattern as the memory_engine + the other
      interpretation engines.
  D9  The engine reads the canonical-label prefix from fighter_
      descriptors columns via the `decode_label` helper (reused from
      context_engine — single source of truth for the "label||phrase"
      format). This is the SAME pattern as narrative_families + legacy
      _engine — the bulk-load writes "label||phrase", readers parse
      out the label for rule logic.
  D10 The engine is called by snapshot_cache._generate_headlines at
      the END of the daily pass (after fighter_descriptors is fully
      populated). If the daily pass is skipped (e.g., bulk-tick mode),
      headlines are also skipped — they're derived from fighter_
      descriptors, so they're only as fresh as the last daily pass.
"""
import sqlite3
from datetime import datetime, timedelta


# Reuse the decode_label helper from context_engine (D9) — single
# source of truth for the "label||phrase" storage format.
from interpretation.context_engine import decode_label


# ============================================================
# HEADLINE TYPE CONSTANTS
# ============================================================
# These match the CHECK'd enum on daily_headlines.headline_type (added
# in v3.11.0). Tests read these; the engine writes them.

HEADLINE_TOP_STORY = "top_story"
HEADLINE_UPSET_OF_WEEK = "upset_of_week"
HEADLINE_FASTEST_RISING = "fastest_rising"
HEADLINE_BIGGEST_FALL = "biggest_fall"

ALL_HEADLINE_TYPES = (
    HEADLINE_TOP_STORY,
    HEADLINE_UPSET_OF_WEEK,
    HEADLINE_FASTEST_RISING,
    HEADLINE_BIGGEST_FALL,
)


# ============================================================
# MAIN ENTRY POINT — generate_daily_headlines
# ============================================================

def generate_daily_headlines(conn, current_date=None):
    """Generate 4 daily headlines from interpreted state.

    Per spec §8 + PHASE_2_PLAN §5 Task 2.6: runs at the end of the
    daily interpretation pass (after fighter_descriptors is fully
    populated by context_engine + career_phase + narrative_families +
    legacy). Writes 4 headlines to the daily_headlines table.

    Per D6: IDEMPOTENT — each headline is written with INSERT OR
    REPLACE against UNIQUE (headline_date, headline_type). Re-running
    for the same date replaces, doesn't duplicate.

    Per D8: NEVER raises — a failed headline write is caught + logged.
    The daily pass must not crash because one headline failed.

    Args:
        conn: sqlite3.Connection.
        current_date: optional ISO date string. If None, read from
            simulation_clock (the normal case — caller is the daily
            pass).

    Returns:
        int — number of headlines written (0-4). 4 = all headlines
        generated; fewer = some were skipped (e.g., no upsets in the
        last 7 days → upset_of_week skipped).
    """
    # 1. Resolve current_date from simulation_clock if not provided.
    if current_date is None:
        try:
            row = conn.execute(
                "SELECT simulation_clock.current_date "
                "FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            current_date = row[0] if row else None
        except sqlite3.Error:
            current_date = None
    if not current_date:
        from datetime import date as _date
        current_date = _date.today().isoformat()

    written = 0

    # Each headline is a separate try/except (D8) — a single failed
    # headline must not abort the others. The engine writes what it
    # can + logs the failures.
    for headline_type, generator in (
        (HEADLINE_TOP_STORY, _generate_top_story),
        (HEADLINE_UPSET_OF_WEEK, _generate_upset_of_week),
        (HEADLINE_FASTEST_RISING, _generate_fastest_rising),
        (HEADLINE_BIGGEST_FALL, _generate_biggest_fall),
    ):
        try:
            headline = generator(conn, current_date)
            if headline is None:
                # No subject for this headline type today — skip
                # (don't write a row). This is a valid outcome per
                # D2/D3/D5 — e.g., no upsets in the last 7 days.
                continue
            _write_headline(conn, current_date, headline_type,
                            headline)
            written += 1
        except Exception as e:
            import sys
            print(f"WARNING: headline_engine {headline_type} failed: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)

    conn.commit()
    return written


# ============================================================
# HEADLINE 1 — Top Story
# ============================================================

def _generate_top_story(conn, current_date):
    """Generate the Top Story headline.

    Per D2: query fighter_descriptors for narrative_family != NULL,
    pick the most interesting (fallen_champion > prodigy > cinderella
    > veteran). The priority reflects narrative weight.

    Returns the headline dict (headline_text, body_text, fighter_id)
    or None if no fighter matches any family.
    """
    # Bulk-load all fighters with a non-NULL narrative_family. We
    # decode the canonical label from the "label||phrase" storage
    # format (D9) to apply the priority order.
    rows = conn.execute(
        """
        SELECT fd.fighter_id, fd.narrative_family,
               f.first_name, f.last_name
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        WHERE fd.narrative_family IS NOT NULL
          AND f.is_active = 1 AND f.is_retired = 0
        """
    ).fetchall()

    if not rows:
        # No narrative families today — skip the top story.
        return None

    # Priority order (D2): fallen_champion > prodigy > cinderella >
    # veteran. We assign a priority rank to each label + pick the
    # lowest-rank fighter (deterministic tiebreaker: lowest fighter_id).
    priority = {
        "fallen_champion": 1,
        "prodigy": 2,
        "cinderella_story": 3,
        "veteran": 4,
    }

    best = None  # (rank, fighter_id, label, name)
    for fighter_id, narrative_family, first_name, last_name in rows:
        label = decode_label(narrative_family)
        rank = priority.get(label)
        if rank is None:
            continue  # unrecognized family — skip (defensive)
        name = f"{first_name} {last_name}".strip() or "The fighter"
        candidate = (rank, fighter_id, label, name)
        if best is None or (candidate[0], candidate[1]) < (best[0], best[1]):
            best = candidate

    if best is None:
        return None

    _rank, fighter_id, label, name = best

    # Voice phrases (D7 — no digits per §14). Each family has its own
    # headline + body voice phrase.
    if label == "fallen_champion":
        return {
            "headline_text": f"The fallen champion's reign crumbles",
            "body_text": (f"{name} — once the king of the division — "
                          f"slides further from glory. The crown is "
                          f"fading fast."),
            "fighter_id": fighter_id,
        }
    if label == "prodigy":
        return {
            "headline_text": f"The prodigy turns heads again",
            "body_text": (f"{name} keeps proving the hype is real. "
                          f"The division's brightest young talent "
                          f"continues to surge."),
            "fighter_id": fighter_id,
        }
    if label == "cinderella_story":
        return {
            "headline_text": f"Nobody saw this rise coming",
            "body_text": (f"{name} — once an afterthought — is now "
                          f"the division's most improbable contender. "
                          f"The Cinderella story rolls on."),
            "fighter_id": fighter_id,
        }
    if label == "veteran":
        return {
            "headline_text": f"The veteran refuses to fade",
            "body_text": (f"{name} — grizzled, battle-tested, still "
                          f"going — proves there's life in the old "
                          f"warhorse yet."),
            "fighter_id": fighter_id,
        }
    # Defensive — should never reach here (the priority filter above
    # excludes unrecognized labels).
    return None


# ============================================================
# HEADLINE 2 — Upset of the Week
# ============================================================

def _generate_upset_of_week(conn, current_date):
    """Generate the Upset of the Week headline.

    Per D3: query fight_history for fights in the last 7 days where
    the winner had a LOWER rankings.rating than the loser. The
    "biggest" upset = the largest rating gap favoring the loser. If
    no fights in the last 7 days, skip.

    The rating is rendered as a voice band ("underdog" / "heavy
    underdog" / "shocking upset") per §14.
    """
    # Compute the date 7 days ago.
    try:
        today = datetime.fromisoformat(current_date).date()
    except (ValueError, TypeError):
        return None
    week_ago = today - timedelta(days=7)
    week_ago_str = week_ago.isoformat()

    # Look up fights in the last 7 days where the winner had a lower
    # rating than the loser. We join fight_history (twice — once for
    # the winner, once for the loser) to rankings to get both ratings.
    # The upset = winner.rating < loser.rating; the magnitude =
    # loser.rating - winner.rating (positive — the bigger, the bigger
    # the upset).
    row = conn.execute(
        """
        SELECT win.fighter_id AS winner_id,
               win.opponent_id AS loser_id,
               win.event_date,
               win.result_type,
               wf.first_name AS winner_first,
               wf.last_name AS winner_last,
               lf.first_name AS loser_first,
               lf.last_name AS loser_last,
               wr.rating AS winner_rating,
               lr.rating AS loser_rating
        FROM fight_history win
        JOIN fighters wf ON wf.fighter_id = win.fighter_id
        JOIN fighters lf ON lf.fighter_id = win.opponent_id
        LEFT JOIN rankings wr ON wr.fighter_id = win.fighter_id
        LEFT JOIN rankings lr ON lr.fighter_id = win.opponent_id
        WHERE win.outcome = 'win'
          AND win.event_date > ?
          AND win.event_date <= ?
          AND wr.rating IS NOT NULL
          AND lr.rating IS NOT NULL
          AND wr.rating < lr.rating
        ORDER BY (lr.rating - wr.rating) DESC
        LIMIT 1
        """,
        (week_ago_str, current_date),
    ).fetchone()

    if not row:
        return None

    (winner_id, loser_id, _event_date, result_type,
     winner_first, winner_last, loser_first, loser_last,
     winner_rating, loser_rating) = row

    rating_gap = (loser_rating or 0) - (winner_rating or 0)
    winner_name = f"{winner_first} {winner_last}".strip() or "The winner"
    loser_name = f"{loser_first} {loser_last}".strip() or "The loser"
    result_phrase = _result_type_phrase(result_type)

    # Voice band for the upset magnitude (D3 — no raw rating numbers
    # per §14). 0-25 points = "underdog"; 25-50 = "heavy underdog";
    # 50+ = "shocking upset".
    if rating_gap >= 50:
        upset_band = "a shocking upset"
    elif rating_gap >= 25:
        upset_band = "a heavy underdog"
    else:
        upset_band = "an underdog"

    return {
        "headline_text": f"{winner_name} stuns {loser_name}",
        "body_text": (f"{winner_name} pulled off {upset_band} this "
                      f"week, finishing {loser_name} by "
                      f"{result_phrase}. The division takes notice."),
        "fighter_id": winner_id,
    }


# ============================================================
# HEADLINE 3 — Fastest Rising
# ============================================================

def _generate_fastest_rising(conn, current_date):
    """Generate the Fastest Rising headline.

    Per D4: query fighter_descriptors for momentum='very_high' AND
    career_phase='prospect' (the canonical prodigy criteria). If
    none match, fall back to momentum='high' AND career_phase=
    'prospect'. If still none, fall back to momentum='very_high'
    (any fighter on a 5+ win streak). Deterministic tiebreaker:
    lowest fighter_id.
    """
    # Fallback chain (D4). Each query uses the bulk-load pattern
    # (single SELECT) with a deterministic ORDER BY fighter_id LIMIT 1
    # tiebreaker.
    for momentum_filter, career_filter in (
        ("very_high", "prospect"),
        ("high", "prospect"),
        ("very_high", None),  # any career_phase
    ):
        row = _find_fighter_by_labels(conn, momentum_filter,
                                      career_filter)
        if row:
            fighter_id, first_name, last_name = row
            name = f"{first_name} {last_name}".strip() or "The fighter"
            return {
                "headline_text": f"{name} is rising fast",
                "body_text": (f"The hottest hand in the division "
                              f"belongs to {name}. The surge "
                              f"continues — opponents take notice."),
                "fighter_id": fighter_id,
            }
    return None


# ============================================================
# HEADLINE 4 — Biggest Fall
# ============================================================

def _generate_biggest_fall(conn, current_date):
    """Generate the Biggest Fall headline.

    Per D5: query fighter_descriptors for momentum='collapsing' (3+
    loss streak). If none match, fall back to momentum='falling' (2
    loss streak). If still none, skip the headline. Deterministic
    tiebreaker: lowest fighter_id.
    """
    for momentum_filter in ("collapsing", "falling"):
        row = _find_fighter_by_labels(conn, momentum_filter, None)
        if row:
            fighter_id, first_name, last_name = row
            name = f"{first_name} {last_name}".strip() or "The fighter"
            return {
                "headline_text": f"{name} is sliding fast",
                "body_text": (f"The fall continues for {name}. "
                              f"Once a name to fear — now a fighter "
                              f"searching for answers."),
                "fighter_id": fighter_id,
            }
    return None


# ============================================================
# HELPER — find a fighter by decoded momentum + career_phase labels
# ============================================================

def _find_fighter_by_labels(conn, momentum_label, career_phase_label):
    """Find the lowest-fighter_id active fighter matching the given
    decoded momentum + career_phase labels.

    Per D9: the fighter_descriptors columns store "label||voice phrase"
    — we need to filter on the LABEL (before the "||"), not the
    phrase. SQLite's SUBSTR + INSTR does the parsing inline:

        SUBSTR(momentum, 1, INSTR(momentum || '||', '||') - 1)

    This returns the substring before the first "||" — the canonical
    label. We compare it to the desired label.

    Args:
        conn: sqlite3.Connection.
        momentum_label: canonical momentum label (e.g. "very_high").
        career_phase_label: canonical career_phase label, or None to
            skip the career_phase filter.

    Returns:
        (fighter_id, first_name, last_name) tuple, or None.
    """
    # Build the WHERE clause. The momentum filter is always applied;
    # the career_phase filter is conditional.
    sql = """
        SELECT fd.fighter_id, f.first_name, f.last_name
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        WHERE f.is_active = 1 AND f.is_retired = 0
          AND SUBSTR(fd.momentum, 1,
                     INSTR(fd.momentum || '||', '||') - 1) = ?
    """
    params = [momentum_label]
    if career_phase_label is not None:
        sql += ("  AND SUBSTR(fd.career_phase, 1, "
                "INSTR(fd.career_phase || '||', '||') - 1) = ?\n")
        params.append(career_phase_label)
    sql += "        ORDER BY fd.fighter_id ASC LIMIT 1\n"

    return conn.execute(sql, params).fetchone()


# ============================================================
# HELPER — voice phrase for fight_history.result_type
# ============================================================
# Reused by the Upset of the Week headline. Same translation as the
# memory_engine uses (kept here as a local copy so this module is
# self-contained — no risk of a future refactor to memory_engine
# silently breaking headline generation).

_RESULT_TYPE_PHRASES = {
    "unanimous_decision": "unanimous decision",
    "split_decision": "split decision",
    "ko_tko": "knockout",
    "submission": "submission",
    "doctor_stoppage": "doctor stoppage",
    "dq": "disqualification",
    "draw": "draw",
}


def _result_type_phrase(result_type):
    """Render a fight_history.result_type as a voice phrase (§14)."""
    if not result_type:
        return "a finish"
    return _RESULT_TYPE_PHRASES.get(result_type, "a finish")


# ============================================================
# HELPER — write a headline row (INSERT OR REPLACE for idempotency)
# ============================================================

def _write_headline(conn, current_date, headline_type, headline):
    """Write a single headline row to daily_headlines.

    Per D6: uses INSERT OR REPLACE against UNIQUE (headline_date,
    headline_type) for idempotency. Re-running for the same date
    overwrites the row — doesn't duplicate.

    Args:
        conn: sqlite3.Connection.
        current_date: ISO date string.
        headline_type: one of HEADLINE_*.
        headline: dict with keys 'headline_text', 'body_text',
            'fighter_id'.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_headlines
            (headline_date, headline_type, headline_text,
             body_text, fighter_id, snapshot_version, created_at)
        VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        """,
        (current_date, headline_type,
         headline["headline_text"],
         headline.get("body_text"),
         headline.get("fighter_id")),
    )
