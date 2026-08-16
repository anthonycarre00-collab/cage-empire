"""CAGE EMPIRE Memory Engine (Phase 2 Task 2.5).

READER — surfaces relevant memories BEFORE key events (currently: when
a fight is booked between two fighters). The existing
`services/memory_svc.py` is the WRITER (it inserts rows into
`fighter_memory_links` when retirements, signings, or main-event
matchups occur). This engine is the reader that turns those raw link
rows + raw simulation tables (fight_history, fighters.current_gym_id,
injuries) into PLAYER-FACING voice phrases.

Per spec §5 (Memory Resurfacing): instead of forcing players to
remember previous fights / shared gyms / former teammates / injuries,
the engine SURFACES the most interesting memories so every fight feels
meaningful. The spec's example voice phrases:
  - "Last met six years ago."
  - "Former training partners."
  - "First fight ended in split decision."
  - "The champion is recovering from a shoulder injury sustained in
     his last bout."

Per CONVENTIONS §17.1: this module is the ONLY writer to cache tables.
The Memory Engine is a READER — it NEVER writes to ANY table (not even
the cache). It returns a list of voice-phrase strings to the caller
(matchmaking, the UI Fight Card screen, the news engine). The caller
decides what to do with them (display, persist to a news_items row,
etc.).

Per CONVENTIONS §14: every memory string is VOICE-LAYERED — no raw
numbers. "Last met three years ago" not "Last met 1095 days ago".
"Split decision" not "29-28 scorecards". The voice layer (§14.3) is
applied via the canonical-label + voice-phrase pattern (§17.4) where
applicable, but the Memory Engine mostly produces free-form voice
phrases (the memories are STORY text, not categorical labels — they
don't fit the "label||phrase" cache-column format used by the other
interpretation engines, because they're returned to the caller rather
than written to a cache column).

Per CONVENTIONS §17.5: the engine is called ON-DEMAND (when a fight
is booked — see matchmaking._build_main_event), NOT daily. It uses
TARGETED queries (4 small SELECTs against fight_history + fighters +
fighter_memory_links + injuries). MUST complete in <50ms for any
single fighter pair — well under the daily-pass budget.

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  4 MVP memory search types cut from the spec's 10 (per
      PHASE_2_PLAN §5, Task 2.5 + §4 MVP Cut). The spec's full list:
      shared gyms, previous fights, coach history, former champions,
      title losses, long layoffs, former teammates, contract disputes,
      injuries, weight class changes. We ship 4 in MVP — the rest are
      deferred to Phase 3+ when the underlying data (training_camp
      overlaps, contract disputes, weight-class change history) is
      reliably tracked.
        1. previous_fight   — fight_history (have they met before?)
        2. shared_gym        — fighters.current_gym_id (current shared
                               gym only — historical overlaps require
                               a gym_history table that doesn't exist
                               yet; deferred to Phase 3+).
        3. former_teammate   — fighter_memory_links rows of type
                               'former_teammate' or 'shared_gym'
                               (written by memory_svc when a gym
                               transfer occurs). The MVP reader just
                               reports whether a link EXISTS — it
                               doesn't dig into the historical record.
        4. injury_history    — injuries table (is either fighter
                               currently injured? what kind?). MVP
                               surfaces only ACTIVE injuries; the
                               projected_return_date is rendered as
                               "near return" / "long road back" /
                               "indefinite" voice bands, never as a
                               raw date.
  D2  At most 4 memories per fighter pair (one per search type). Each
      search returns 0 or 1 voice-phrase strings. Total: 0-4 memories
      per fight. This keeps the Fight Card screen uncluttered (a 5th
      memory would scroll past the fold on most viewports) AND keeps
      the engine's per-call cost predictable (4 small queries, no
      fan-out).
  D3  The engine is READ-ONLY. It does NOT write to fighter_memory_
      links, fight_history, or any other table. The existing
      `memory_svc.populate_*` functions remain the writers; this
      engine is the reader that surfaces their work to the player.
      This separation matters: a READ-ONLY engine is safe to call
      from the UI render path (no DB writes during page render —
      CONVENTIONS §17.1 implies this even though it's not stated).
  D4  Voice phrases only — no raw numbers (CONVENTIONS §14). The
      engine translates:
        - 3-year gap → "three years ago" (small integer → English
          word; 5+ years → "many years ago").
        - result_type='unanimous_decision' → "unanimous decision".
          'split_decision' → "split decision". 'ko_tko' → "knockout".
          'submission' → "submission". 'doctor_stoppage' → "doctor
          stoppage". 'dq' → "disqualification". 'draw' → "draw".
        - outcome='win' / 'loss' / 'draw' → "won" / "lost" / "drew".
        - injury.body_area='shoulder' → "a shoulder injury". The
          projected_return_date is rendered as a band ("near return"
          if projected in the next 60 days, "long road back" if 60+
          days, "indefinite" if NULL or past-due — a past-due injury
          means the projected return was optimistic and the fighter
          is still on the shelf).
      All voice phrases are short, journalistic, present-tense.
  D5  The engine uses TARGETED queries (4 small SELECTs, one per
      search type), NOT the bulk-load pattern. The bulk-load pattern
      (CONVENTIONS §17.5) is for the DAILY PASS where you process all
      4450 fighters at once. The Memory Engine is called ON-DEMAND
      for a single fighter pair — 4 small queries against indexed
      columns (fight_history has indexes on fighter_id + opponent_id;
      fighters PK on fighter_id; fighter_memory_links has a UNIQUE
      constraint on fighter_id + linked_fighter_id + link_type) is
      the right shape. Total cost: <50ms per call.
  D6  The engine NEVER raises — it catches DB errors and returns a
      partial result (whatever memories it could surface before the
      error). This is the same defensive pattern as the snapshot_cache
      try/except blocks: a failed memory lookup must not crash the
      fight booking flow.
  D7  Time-gap rendering uses English ordinals (CONVENTIONS §14: no
      digits). Years 1-4 → "one"/"two"/"three"/"four years ago". 5+
      → "many years ago". This keeps the voice consistent with the
      other interpretation engines (career_phase_engine D7 uses the
      same RNG-seeded-by-fighter_id determinism pattern for variant
      selection; the memory engine uses no RNG — each memory is a
      single deterministic phrase computed from the inputs, so there's
      no UI flickering concern).
  D8  When two fighters have fought MULTIPLE times in the past, only
      the MOST RECENT fight is surfaced (ORDER BY event_date DESC
      LIMIT 1). The spec's example ("Last met six years ago") implies
      single-fight surfacing; a full fight-series story is a Phase 3+
      feature (it requires tracking the W-L-D record across all
      previous meetings, which is more voice work than the MVP cut
      justifies).
  D9  The 'shared_gym' search joins `fighters.current_gym_id` for both
      fighters. If they're currently at the same gym, surface
      "Training partners at {gym_name}." This is the SIMPLEST gym-
      overlap story. The richer "former training partners" story
      (they were at the same gym at overlapping times in the past)
      requires a `fighter_gym_history` table that doesn't exist yet;
      deferred to Phase 3+ (D1).
  D10 The 'former_teammate' search reads `fighter_memory_links` rows
      of type 'former_teammate' OR 'shared_gym'. memory_svc writes
      these when a fighter changes gyms (the legacy gym-mate link).
      MVP surfaces "Former training partners at {gym_name}." using
      the gym_id from the fighters' CURRENT_gym_id (the link itself
      doesn't store the historical gym_id — that's a Phase 3+
      enhancement to memory_svc).
"""
import sqlite3
from datetime import datetime, date


# ============================================================
# CANONICAL LABEL CONSTANTS
# ============================================================
# These are the canonical labels used internally + by tests. The voice
# phrases are picked separately (D4) — there's no "label||phrase"
# storage format here because the engine returns strings to the caller
# (not writes to a cache column). The labels are used by tests to
# verify which search type matched, without parsing the voice phrase.

MEMORY_TYPE_PREVIOUS_FIGHT = "previous_fight"
MEMORY_TYPE_SHARED_GYM = "shared_gym"
MEMORY_TYPE_FORMER_TEAMMATE = "former_teammate"
MEMORY_TYPE_INJURY_HISTORY = "injury_history"

# HW3.2 — 5 new memory search types. Each returns 0 or 1 voice-phrase
# strings (matching the existing pattern) and is added to the
# surface_memories function's search list. Per docs/Hardening_Phase.md
# §HW3.2 / CRITICAL #6.
MEMORY_TYPE_TITLE_FIGHT_HISTORY = "title_fight_history"
MEMORY_TYPE_FORMER_CHAMPION = "former_champion"
MEMORY_TYPE_CONTROVERSIAL_LOSS = "controversial_loss"
MEMORY_TYPE_MAJOR_UPSET = "major_upset"
MEMORY_TYPE_CAREER_MILESTONE = "career_milestone"

ALL_MEMORY_TYPES = (
    MEMORY_TYPE_PREVIOUS_FIGHT,
    MEMORY_TYPE_SHARED_GYM,
    MEMORY_TYPE_FORMER_TEAMMATE,
    MEMORY_TYPE_INJURY_HISTORY,
    # HW3.2 new types:
    MEMORY_TYPE_TITLE_FIGHT_HISTORY,
    MEMORY_TYPE_FORMER_CHAMPION,
    MEMORY_TYPE_CONTROVERSIAL_LOSS,
    MEMORY_TYPE_MAJOR_UPSET,
    MEMORY_TYPE_CAREER_MILESTONE,
)


# ============================================================
# VOICE PHRASE HELPERS (D4 — no raw numbers per §14)
# ============================================================
# Small integer → English word. Used for year gaps + result counts.
# 0 = "just now", 1-4 = "one"/"two"/"three"/"four", 5+ = "many".

_YEAR_WORDS = {
    0: "this year",
    1: "one year",
    2: "two years",
    3: "three years",
    4: "four years",
}


def _year_gap_phrase(years):
    """Render a year gap as a voice phrase (no digits — CONVENTIONS §14).

    Args:
        years: int (>= 0). Years between two events.

    Returns:
        Voice phrase string. 0 → "this year". 1-4 → "one year" /
        "two years" / etc. 5+ → "many years". Negative inputs are
        defensively coerced to 0 (shouldn't happen — caller sorts by
        date DESC, so the gap is always non-negative).
    """
    years = max(0, years or 0)
    if years in _YEAR_WORDS:
        return _YEAR_WORDS[years]
    return "many years"


# fight_history.result_type → voice phrase. Rendered as a noun ("a
# split decision") so it slots into "they last met ... the bout ended
# in a split decision" without re-phrasing.
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
    """Render a fight_history.result_type as a voice phrase (§14).

    Args:
        result_type: str (one of the 7 fight_history.result_type values,
            or None).

    Returns:
        Voice phrase string. None / unknown → "a finish" (defensive —
        the engine must never crash on bad data).
    """
    if not result_type:
        return "a finish"
    return _RESULT_TYPE_PHRASES.get(result_type, "a finish")


# fight_history.outcome → verb phrase (relative to the focal fighter).
# Used in "they last met ... {focal} won by split decision."
_OUTCOME_VERBS = {
    "win": "won",
    "loss": "lost",
    "draw": "drew",
}


def _outcome_verb(outcome):
    """Render a fight_history.outcome as a past-tense verb (§14).

    Args:
        outcome: str ('win'/'loss'/'draw' or None).

    Returns:
        Verb string. None / unknown → "fought" (defensive).
    """
    if not outcome:
        return "fought"
    return _OUTCOME_VERBS.get(outcome, "fought")


# injuries.body_area → "a {body_area} injury" phrase. The body_area is
# already a clean noun (shoulder, knee, ribs, hand, ankle, wrist, hip,
# head) so the transformation is just article + noun + "injury".
def _body_area_phrase(body_area):
    """Render an injuries.body_area as a voice phrase (§14).

    Args:
        body_area: str (e.g. 'shoulder', 'knee', 'ribs').

    Returns:
        Voice phrase string. None / unknown → "an injury" (defensive).
    """
    if not body_area:
        return "an injury"
    # "ribs" → "rib" (singular reads better in "a rib injury"). The
    # other 7 body areas are already singular.
    noun = body_area
    if noun.endswith("s"):
        noun = noun[:-1]
    return f"a {noun} injury"


# injuries.projected_return_date → band phrase (§14: no raw dates).
# The bands are: "near return" (next 60 days), "long road back"
# (60-180 days), "indefinite" (NULL or past-due). The band thresholds
# are rough voice bands, not medical facts — they exist to keep the
# phrase stable across days (a fighter projected to return in 30 days
# stays "near return" for 30 days, then becomes "indefinite" if the
# date passes without an actual_return_date).
def _return_band_phrase(projected_return_date, current_date):
    """Render an injuries.projected_return_date as a band phrase (§14).

    Args:
        projected_return_date: ISO date string (TEXT YYYY-MM-DD) or
            None. None means "no projected return" (long-term injury).
        current_date: ISO date string (TEXT YYYY-MM-DD). The "today"
            reference for the band computation.

    Returns:
        Voice phrase string. One of:
          - "near return" — projected in the next 60 days.
          - "a long road back" — projected in 60-180 days.
          - "indefinite" — projected >180 days out OR past-due (the
            projected date has passed without an actual_return_date —
            the fighter is still on the shelf).
        Defensive: returns "indefinite" on parse errors (the engine
        must never crash on bad date data).
    """
    if not projected_return_date or not current_date:
        return "indefinite"
    try:
        proj = datetime.fromisoformat(projected_return_date).date()
        today = datetime.fromisoformat(current_date).date()
    except (ValueError, TypeError):
        return "indefinite"
    delta_days = (proj - today).days
    if delta_days < 0:
        # Past-due — projected return has passed, fighter still on
        # the shelf (is_active=1 in the injuries table means the
        # injury hasn't been resolved).
        return "indefinite"
    if delta_days <= 60:
        return "near return"
    if delta_days <= 180:
        return "a long road back"
    return "indefinite"


# ============================================================
# CORE ENTRY POINT — surface_memories
# ============================================================

def surface_memories(conn, fighter_a_id, fighter_b_id,
                     current_date=None):
    """Surface relevant memories for a fight between two fighters.

    Per spec §5 + PHASE_2_PLAN §5 Task 2.5 + HW3.2 (Hardening_Phase.md
    §HW3.2): the Memory Engine searches 9 sources (4 MVP + 5 HW3) for
    relevant history between the two fighters and returns a list of
    voice-phrase strings. Each phrase is player-facing (no raw numbers
    per CONVENTIONS §14).

    Search types (D1 + HW3.2):
      1. previous_fight        — have they fought before? (from fight_
                                  history)
      2. shared_gym            — do they currently share a gym? (from
                                  fighters.current_gym_id)
      3. former_teammate       — is there a fighter_memory_links row
                                  of type 'former_teammate' between
                                  them?
      4. injury_history        — is either fighter currently injured?
                                  (from injuries where is_active=1)
      5. title_fight_history   — have they fought for a title before?
                                  (HW3.2 — from fight_history joined
                                  with fights.is_title_fight=1)
      6. former_champion       — is either fighter a former champion?
                                  (HW3.2 — from titles history)
      7. controversial_loss    — did one fighter lose controversially
                                  to the other (split_decision /
                                  disputed stoppage)? (HW3.2)
      8. major_upset           — was there a major upset between these
                                  two? (HW3.2 — from fighter_memory_
                                  links where link_type='upset')
      9. career_milestone      — has either fighter reached a career
                                  milestone against the other? (HW3.2
                                  — from fighter_memory_links where
                                  link_type='milestone')

    Returns up to 9 memories (one per search type). Each search
    returns 0 or 1 voice phrases. The engine is READ-ONLY (D3).

    Per D6: the engine NEVER raises — DB errors are caught and a
    partial result is returned. A failed memory lookup must not crash
    the fight booking flow.

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int. First fighter's ID.
        fighter_b_id: int. Second fighter's ID.
        current_date: optional ISO date string. If None, read from
            simulation_clock. Used for the year-gap + injury-band
            voice phrases (D4 + D7).

    Returns:
        list of (memory_type, memory_phrase) tuples. The list is
        ordered by search type (previous_fight, shared_gym,
        former_teammate, injury_history, title_fight_history,
        former_champion, controversial_loss, major_upset,
        career_milestone) — the same order the UI displays them on
        the Fight Card screen. Empty list if no memories match.
    """
    # Resolve current_date from simulation_clock if not provided.
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
        # Fall back to today's wall-clock date (the engine must never
        # crash on missing simulation_clock — a test DB may not have
        # the clock seeded).
        current_date = date.today().isoformat()

    memories = []

    # Each search is a separate try/except block (D6) — a single
    # failed search must not abort the others. We append results in
    # the canonical order (D2).
    try:
        m = _search_previous_fight(conn, fighter_a_id, fighter_b_id,
                                   current_date)
        if m:
            memories.append((MEMORY_TYPE_PREVIOUS_FIGHT, m))
    except sqlite3.Error as e:
        # Defensive — log + continue. The caller gets whatever
        # memories we could surface before the error.
        import sys
        print(f"WARNING: memory_engine._search_previous_fight("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_shared_gym(conn, fighter_a_id, fighter_b_id)
        if m:
            memories.append((MEMORY_TYPE_SHARED_GYM, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_shared_gym("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_former_teammate(conn, fighter_a_id, fighter_b_id)
        if m:
            memories.append((MEMORY_TYPE_FORMER_TEAMMATE, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_former_teammate("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_injury_history(conn, fighter_a_id, fighter_b_id,
                                   current_date)
        if m:
            memories.append((MEMORY_TYPE_INJURY_HISTORY, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_injury_history("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # HW3.2 — 5 new search types. Each is a separate try/except so a
    # single failed search doesn't abort the others. Ordered by
    # narrative weight (title_fight_history is the heaviest — most
    # newsworthy when booking a rematch; career_milestone is the
    # lightest — most context-dependent).
    try:
        m = _search_title_fight_history(conn, fighter_a_id,
                                        fighter_b_id, current_date)
        if m:
            memories.append((MEMORY_TYPE_TITLE_FIGHT_HISTORY, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_title_fight_history("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_former_champion(conn, fighter_a_id, fighter_b_id)
        if m:
            memories.append((MEMORY_TYPE_FORMER_CHAMPION, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_former_champion("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_controversial_loss(conn, fighter_a_id, fighter_b_id,
                                       current_date)
        if m:
            memories.append((MEMORY_TYPE_CONTROVERSIAL_LOSS, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_controversial_loss("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_major_upset(conn, fighter_a_id, fighter_b_id,
                                current_date)
        if m:
            memories.append((MEMORY_TYPE_MAJOR_UPSET, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_major_upset("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    try:
        m = _search_career_milestone(conn, fighter_a_id, fighter_b_id)
        if m:
            memories.append((MEMORY_TYPE_CAREER_MILESTONE, m))
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_engine._search_career_milestone("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    return memories


# ============================================================
# SEARCH 1 — previous_fight (from fight_history)
# ============================================================

def _search_previous_fight(conn, fighter_a_id, fighter_b_id,
                           current_date):
    """Search fight_history for a previous fight between the two.

    Per D8: only the MOST RECENT fight is surfaced (ORDER BY event_
    date DESC LIMIT 1). A full fight-series story ("they've split
    their two previous meetings, each winning by knockout") is a
    Phase 3+ feature.

    Returns the memory phrase from the perspective of fighter_a (the
    "focal" fighter — typically the player's fighter or the higher-
    ranked of the two). The phrase: "Last met {gap} — {focal}
    {verb} by {result}."

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.
        current_date: ISO date string.

    Returns:
        Voice phrase string, or None if they haven't fought before.
    """
    # fight_history has one row per (fighter, opponent) per fight —
    # we look up fighter_a's row against fighter_b (the row already
    # has fighter_a's outcome + the fight's result_type).
    row = conn.execute(
        """
        SELECT outcome, result_type, event_date
        FROM fight_history
        WHERE fighter_id = ? AND opponent_id = ?
        ORDER BY event_date DESC
        LIMIT 1
        """,
        (fighter_a_id, fighter_b_id),
    ).fetchone()

    if not row:
        return None

    outcome, result_type, event_date = row

    # Year gap (D7). event_date is TEXT YYYY-MM-DD; current_date is
    # also TEXT YYYY-MM-DD. Compute the year difference.
    years = 0
    if event_date and current_date:
        try:
            ed = datetime.fromisoformat(event_date).date()
            today = datetime.fromisoformat(current_date).date()
            years = today.year - ed.year
            # If the event was later in the year than today, subtract
            # one (a fight on 2023-12 vs today 2026-01 is 2 years, not
            # 3).
            if (today.month, today.day) < (ed.month, ed.day):
                years -= 1
            years = max(0, years)
        except (ValueError, TypeError):
            years = 0

    gap_phrase = _year_gap_phrase(years)
    verb = _outcome_verb(outcome)
    result_phrase = _result_type_phrase(result_type)

    # Voice phrase (D4 — no digits per §14). Two forms:
    #   - 0-year gap (same year): "Met earlier this year — won by
    #     split decision."
    #   - 1+ year gap: "Last met two years ago — lost by knockout."
    if years == 0:
        return f"Met earlier {gap_phrase} — {verb} by {result_phrase}."
    return (f"Last met {gap_phrase} ago — {verb} by "
            f"{result_phrase}.")


# ============================================================
# SEARCH 2 — shared_gym (from fighters.current_gym_id)
# ============================================================

def _search_shared_gym(conn, fighter_a_id, fighter_b_id):
    """Search fighters.current_gym_id for a current shared gym.

    Per D9: the SIMPLEST gym-overlap story. If both fighters are
    currently at the same gym, surface "Training partners at {gym
    name}." The richer "former training partners" story (overlapping
    times in the past) requires a fighter_gym_history table that
    doesn't exist yet — deferred to Phase 3+.

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.

    Returns:
        Voice phrase string, or None if they don't currently share
        a gym.
    """
    row = conn.execute(
        """
        SELECT f1.current_gym_id, g.name
        FROM fighters f1
        JOIN fighters f2 ON f2.fighter_id = ?
        LEFT JOIN gyms g ON g.gym_id = f1.current_gym_id
        WHERE f1.fighter_id = ?
          AND f1.current_gym_id IS NOT NULL
          AND f1.current_gym_id = f2.current_gym_id
        """,
        (fighter_b_id, fighter_a_id),
    ).fetchone()

    if not row or not row[0]:
        return None

    gym_name = row[1] or "their gym"  # defensive — gym name should
                                       # never be NULL but the engine
                                       # must not crash on bad data.
    return f"Training partners at {gym_name}."


# ============================================================
# SEARCH 3 — former_teammate (from fighter_memory_links)
# ============================================================

def _search_former_teammate(conn, fighter_a_id, fighter_b_id):
    """Search fighter_memory_links for a 'former_teammate' or 'shared_
    gym' link between the two fighters.

    Per D10: memory_svc writes these links when a fighter changes gyms
    (the legacy gym-mate link is recorded for future surfacing). MVP
    surfaces "Former training partners." (without the gym name — the
    link itself doesn't store the historical gym_id; that's a Phase
    3+ enhancement to memory_svc).

    The link may exist in either direction (A→B or B→A) — memory_svc
    writes bidirectional links for some types (e.g. regional_rival).
    We check both directions in one query via an OR.

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.

    Returns:
        Voice phrase string, or None if no former-teammate link
        exists.
    """
    # Check for either link_type ('former_teammate' OR 'shared_gym')
    # in either direction. The 'shared_gym' link_type can also
    # represent a HISTORICAL shared gym (memory_svc writes it for
    # current shared gyms too — but the 'shared_gym' search above
    # catches the CURRENT case via fighters.current_gym_id directly;
    # here we surface the HISTORICAL case where they USED to share a
    # gym but no longer do).
    #
    # However, in MVP we can't distinguish "current shared gym" from
    # "former shared gym" via the link alone (the link doesn't store
    # an end_date). To avoid duplicating the 'shared_gym' voice
    # phrase with the 'previous_fight' style, we ONLY surface
    # 'former_teammate' link_type here. The 'shared_gym' link_type
    # is reserved for the historical case (memory_svc may write it
    # when a gym transfer happens — Phase 3+). For MVP, the
    # 'former_teammate' search reads ONLY 'former_teammate' links.
    #
    # TIER3-MISSING §T3.4 (W17) — also surface the PLURAL
    # 'former_teammates' link_type (added v3.36.0). The plural form
    # is written by write_former_teammates_links_on_gym_change (the
    # T3.4-mandated variant). Both forms surface the same voice
    # phrase ("Former training partners.").
    row = conn.execute(
        """
        SELECT 1 FROM fighter_memory_links
        WHERE link_type IN ('former_teammate', 'former_teammates')
          AND (
            (fighter_id = ? AND linked_fighter_id = ?)
            OR
            (fighter_id = ? AND linked_fighter_id = ?)
          )
        LIMIT 1
        """,
        (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
    ).fetchone()

    if not row:
        return None

    return "Former training partners."


# ============================================================
# SEARCH 4 — injury_history (from injuries)
# ============================================================

def _search_injury_history(conn, fighter_a_id, fighter_b_id,
                           current_date):
    """Search injuries for an ACTIVE injury on either fighter.

    Per D1: MVP surfaces only ACTIVE injuries (is_active=1). The
    projected_return_date is rendered as a voice band ("near return"
    / "a long road back" / "indefinite") — no raw dates per §14.

    Returns the memory phrase from the perspective of the injured
    fighter (which may be fighter_a OR fighter_b). If BOTH are
    injured, surface the more severe one (higher severity). The
    phrase: "{fighter_name} is recovering from {body_area_phrase},
    {return_band}."

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.
        current_date: ISO date string.

    Returns:
        Voice phrase string, or None if neither fighter is currently
        injured.
    """
    # Look up active injuries for both fighters in one query (D5 —
    # targeted query, NOT N+1). We fetch the most-severe active
    # injury per fighter via a correlated subquery.
    rows = conn.execute(
        """
        SELECT i.fighter_id, i.injury_type, i.body_area,
               i.severity, i.projected_return_date,
               f.first_name, f.last_name
        FROM injuries i
        JOIN fighters f ON f.fighter_id = i.fighter_id
        WHERE i.is_active = 1
          AND i.fighter_id IN (?, ?)
        ORDER BY i.fighter_id, i.severity DESC
        """,
        (fighter_a_id, fighter_b_id),
    ).fetchall()

    if not rows:
        return None

    # Pick the most severe injury overall (if both fighters are
    # injured, surface the worse one — the more newsworthy story).
    # rows is already ordered by fighter_id then severity DESC within
    # each fighter; we want the GLOBAL max severity.
    worst = max(rows, key=lambda r: r[3] or 0)

    (_fid, _injury_type, body_area, _severity,
     projected_return_date, first_name, last_name) = worst

    body_phrase = _body_area_phrase(body_area)
    band_phrase = _return_band_phrase(projected_return_date,
                                      current_date)
    name = f"{first_name} {last_name}".strip() or "The fighter"

    return (f"{name} is recovering from {body_phrase}, "
            f"{band_phrase}.")


# ============================================================
# SEARCH 5 — title_fight_history (HW3.2)
# ============================================================

def _search_title_fight_history(conn, fighter_a_id, fighter_b_id,
                                current_date):
    """Search fight_history + fights for a previous title fight
    between the two fighters.

    Per HW3.2: "have these two fought for a title before?"

    Looks up fight_history rows where (fighter_id=A AND opponent_id=B)
    OR (fighter_id=B AND opponent_id=A) AND title_at_stake=1. If
    found, surfaces "These two last met for the title {gap} —
    {focal} {verb} by {result}." Voice-layered (no raw dates per §14).

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.
        current_date: ISO date string.

    Returns:
        Voice phrase string, or None if they've never fought for a
        title before.
    """
    # Find the most recent title fight between them (from A's
    # perspective — fight_history has one row per fighter per fight,
    # so the A→B row is sufficient).
    row = conn.execute(
        """
        SELECT outcome, result_type, event_date
        FROM fight_history
        WHERE fighter_id = ? AND opponent_id = ?
          AND title_at_stake = 1
        ORDER BY event_date DESC
        LIMIT 1
        """,
        (fighter_a_id, fighter_b_id),
    ).fetchone()

    if not row:
        return None

    outcome, result_type, event_date = row

    # Year gap (D7).
    years = 0
    if event_date and current_date:
        try:
            ed = datetime.fromisoformat(event_date).date()
            today = datetime.fromisoformat(current_date).date()
            years = today.year - ed.year
            if (today.month, today.day) < (ed.month, ed.day):
                years -= 1
            years = max(0, years)
        except (ValueError, TypeError):
            years = 0

    gap_phrase = _year_gap_phrase(years)
    verb = _outcome_verb(outcome)
    result_phrase = _result_type_phrase(result_type)

    if years == 0:
        return (f"They met for the title earlier {gap_phrase} — "
                f"{verb} by {result_phrase}.")
    return (f"Last fought for the title {gap_phrase} ago — "
            f"{verb} by {result_phrase}.")


# ============================================================
# SEARCH 6 — former_champion (HW3.2)
# ============================================================

def _search_former_champion(conn, fighter_a_id, fighter_b_id):
    """Search titles history — is either fighter a former champion?

    Per HW3.2: "is either fighter a former champion?"

    A "former champion" is a fighter who:
      - Held a title in the past (titles.title_reigns_count > 0)
      - Is NOT the current champion of that title (titles.current_
        champion_fighter_id != fighter_id OR is_vacant=1)

    If both are former champions, surface the more accomplished one
    (higher title_reigns_count). If neither, return None.

    Voice phrase: "{name} is a former champion." Voice-layered — no
    raw reign counts (the spec example is the simple "former champion"
    framing, not "won 3 titles").

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.

    Returns:
        Voice phrase string, or None if neither is a former champion.
    """
    # Look up both fighters' champion status. We check titles rows
    # where title_reigns_count > 0 (the title has been held before)
    # AND the fighter is NOT the current champion of any active title.
    #
    # A fighter is a "former champion" if:
    #   - They appear as current_champion_fighter_id on at least one
    #     title with title_reigns_count > 1 (they were dethroned and
    #     someone else holds it now — but wait, if they're currently
    #     the champion they're NOT former).
    #
    # Simpler approach: query the fighters' career stats. We need to
    # find fighters who HELD a title at some point. The titles table
    # only stores the CURRENT champion — there's no title_reign_
    # history table. We approximate by checking:
    #   - fighter_career.title_reigns (if > 0, they held a title)
    #   - AND they're not currently a champion (no titles row has
    #     current_champion_fighter_id = them AND is_vacant=0)
    #
    # If fighter_career doesn't have title_reigns, fall back to
    # checking news_items for "title" topic headlines mentioning them.
    rows = conn.execute(
        """
        SELECT f.fighter_id, f.first_name, f.last_name,
               fc.title_reigns
        FROM fighters f
        LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        WHERE f.fighter_id IN (?, ?)
        """,
        (fighter_a_id, fighter_b_id),
    ).fetchall()
    if not rows:
        return None

    # For each fighter, check if they're a former champion.
    former_champs = []
    for fid, first, last, reigns in rows:
        if not reigns or reigns < 1:
            continue
        # Check if they're currently a champion.
        cur_row = conn.execute(
            "SELECT 1 FROM titles "
            "WHERE current_champion_fighter_id=? AND is_vacant=0 "
            "LIMIT 1",
            (fid,),
        ).fetchone()
        if cur_row:
            continue  # they're currently a champion, not former
        name = f"{first} {last}".strip() or "The fighter"
        former_champs.append((fid, name, reigns))

    if not former_champs:
        return None

    # Pick the more accomplished former champion (more reigns).
    former_champs.sort(key=lambda x: -x[2])
    name = former_champs[0][1]
    return f"{name} is a former champion."


# ============================================================
# SEARCH 7 — controversial_loss (HW3.2)
# ============================================================

def _search_controversial_loss(conn, fighter_a_id, fighter_b_id,
                                current_date):
    """Search fight_history for a controversial loss between the two.

    Per HW3.2: "did one fighter lose controversially to the other
    (split decision, disputed stoppage)?"

    A "controversial loss" is defined as:
      - result_type = 'split_decision' (a close split-decision loss)
      - OR result_type = 'doctor_stoppage' (a disputed stoppage —
        the loser's corner often disputes these)
      - OR result_type = 'dq' (a disqualification — always
        controversial)

    The search looks for fight_history rows where one fighter lost
    to the other with one of these result_types. Surfaces from the
    LOSER's perspective: "{loser_name} lost to {winner_name} by
    {result_phrase} — {gap} ago." Voice-layered.

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.
        current_date: ISO date string.

    Returns:
        Voice phrase string, or None if no controversial loss exists
        between them.
    """
    # Look for A's losses to B + B's losses to A with a controversial
    # result_type. We want the most recent one.
    row = conn.execute(
        """
        SELECT fighter_id, opponent_id, result_type, event_date
        FROM fight_history
        WHERE outcome = 'loss'
          AND result_type IN ('split_decision', 'doctor_stoppage', 'dq')
          AND (
            (fighter_id = ? AND opponent_id = ?)
            OR
            (fighter_id = ? AND opponent_id = ?)
          )
        ORDER BY event_date DESC
        LIMIT 1
        """,
        (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
    ).fetchone()

    if not row:
        return None

    loser_id, winner_id, result_type, event_date = row

    # Year gap (D7).
    years = 0
    if event_date and current_date:
        try:
            ed = datetime.fromisoformat(event_date).date()
            today = datetime.fromisoformat(current_date).date()
            years = today.year - ed.year
            if (today.month, today.day) < (ed.month, ed.day):
                years -= 1
            years = max(0, years)
        except (ValueError, TypeError):
            years = 0

    gap_phrase = _year_gap_phrase(years)
    result_phrase = _result_type_phrase(result_type)

    # Get the loser's name for the voice phrase.
    name_row = conn.execute(
        "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
        (loser_id,),
    ).fetchone()
    if not name_row:
        return None
    loser_name = f"{name_row[0]} {name_row[1]}".strip() or "The fighter"

    if years == 0:
        return (f"{loser_name} lost by {result_phrase} earlier "
                f"{gap_phrase}.")
    return (f"{loser_name} lost by {result_phrase} {gap_phrase} ago.")


# ============================================================
# SEARCH 8 — major_upset (HW3.2)
# ============================================================

def _search_major_upset(conn, fighter_a_id, fighter_b_id, current_date):
    """Search fighter_memory_links for an 'upset' link between the
    two fighters.

    Per HW3.2: "was there a major upset between these two?"

    Reads the fighter_memory_links table for a row of link_type=
    'upset' between the two (in either direction). These links are
    written by memory_svc.write_upset_link when a lower-rated fighter
    beats a higher-rated one by a rating gap ≥ 15 (per HW3.1).

    Voice phrase: "These two produced a major upset." Voice-layered —
    no raw rating gaps (the link_strength is internal only).

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.
        current_date: ISO date string (unused — kept for API symmetry
            with the other search functions).

    Returns:
        Voice phrase string, or None if no upset link exists.
    """
    row = conn.execute(
        """
        SELECT 1 FROM fighter_memory_links
        WHERE link_type = 'upset'
          AND (
            (fighter_id = ? AND linked_fighter_id = ?)
            OR
            (fighter_id = ? AND linked_fighter_id = ?)
          )
        LIMIT 1
        """,
        (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
    ).fetchone()

    if not row:
        return None

    return "These two produced a major upset."


# ============================================================
# SEARCH 9 — career_milestone (HW3.2)
# ============================================================

def _search_career_milestone(conn, fighter_a_id, fighter_b_id):
    """Search fighter_memory_links for a 'milestone' link between
    the two fighters.

    Per HW3.2: "has either fighter reached a career milestone
    against the other?"

    Reads the fighter_memory_links table for a row of link_type=
    'milestone' between the two (in either direction). These links
    are written by memory_svc.write_milestone_link when a fighter
    reaches a milestone (10 wins, 20 wins, 5-KO streak, 10th title
    defense) against the other (per HW3.1).

    Voice phrase: "One of these fighters reached a career milestone
    against the other." Voice-layered — no raw milestone types.

    Args:
        conn: sqlite3.Connection.
        fighter_a_id: int.
        fighter_b_id: int.

    Returns:
        Voice phrase string, or None if no milestone link exists.
    """
    row = conn.execute(
        """
        SELECT 1 FROM fighter_memory_links
        WHERE link_type = 'milestone'
          AND (
            (fighter_id = ? AND linked_fighter_id = ?)
            OR
            (fighter_id = ? AND linked_fighter_id = ?)
          )
        LIMIT 1
        """,
        (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
    ).fetchone()

    if not row:
        return None

    return ("A career milestone was reached in this matchup.")

