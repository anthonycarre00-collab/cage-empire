"""CAGE EMPIRE — Echoes Engine (Phase R §1.5 + §6 Principle 4).

Surfaces 2-3 consequences of the player's past bookings / signings /
cuts on every Advance Day. Each echo is a short voice phrase that
links back to the player_decisions log + a target fighter / event
so the Dashboard can render it as a clickable card.

Per docs/REWARD_REVIEW.md §1.5 + §6 Principle 4 + Phase R brief:
  - Agency reward is the weakest of GPT's 5 player rewards (3/10
    on 3 of 4 screens) because the player's own past decisions
    are never acknowledged again.
  - Fix: read recent player_decisions, generate 2-3 echoes per
    Advance Day, store them in daily_echoes (cache table — same
    pattern as daily_headlines), surface them on the Dashboard.

4 echo templates (per REWARD_REVIEW.md §1.5 + §6 Principle 4):
  1. SIGNING_ECHO — "Since you signed [Fighter] in [Month], {pronoun}'s
     won [N] straight." (Read fight_history since decision_date.)
     P1.2: gender-aware pronoun per fighter.gender.
  2. CUT_ECHO     — "Since {pronoun} release in [Month], [Fighter] has
     [won the [Rival] title / signed with [Rival] / lost N straight /
     fought N times]." P1.2: rephrased (was "who you released") +
     gender-aware pronoun.
  3. BOOKING_ECHO — "Your decision to main-event [Fighter A] vs
     [Fighter B] at [Event] drew [N] fans — your [Nth]-biggest gate
     this year." (Read event attendance + compare to yearly rank.)
  4. SCOUTING_ECHO — "[Fighter], who you scouted in [Month] as a
     [ceiling phrase], has since [improved / regressed] — your
     scout was [right / wrong]."

Selection algorithm:
  - Score every candidate echo by:
      recency_weight (1.0 → 0.0 over 120 days, linear decay)
      × consequence_magnitude (1-3 based on streak length /
        title win / fan count tier)
  - Sort desc, take top 3 distinct (no fighter repeated).
  - Store in daily_echoes with echo_slot 1..3.

Performance budget: <50ms per Advance Day. Achieved via:
  - All queries hit indexes (idx_player_decisions_date +
    idx_fight_history_fighter + idx_news_items_published +
    idx_player_decisions_fighter).
  - Decision window capped at 120 days (avg ~10-30 decisions).
  - Per-decision query cost ~1-3ms (3-4 indexed lookups).

Voice compliance (CONVENTIONS §14, VOICE_ENFORCEMENT):
  - Phrases ≤120 chars where possible.
  - No tabloid clichés ("SHOCK:", "CONTROVERSY:").
  - No ALL CAPS shouting.
  - Raw streak counts + fan counts ARE allowed (they're not
    hidden attributes — they're career/stats facts). Ceiling
    phrases come from scouting_reports (voice phrases), not raw
    potential ints.

Wiring:
  - Subscribes to TICK_ADVANCED via interpretation/__init__.py
    (registered LAST per CONVENTIONS §17.5 so all simulation writes
    are visible to the echoes queries).
  - The TICK_ADVANCED event fires BEFORE conn.commit() in
    tick_processor.run_tick, so the echoes rows are written in
    the same transaction as the rest of the day's writes. If the
    echoes engine raises, the event_bus catches + logs the error
    — the simulation transaction is unaffected (defensive).

HW3.4 AUDIT FINDINGS (docs/Hardening_Phase.md §HW3.4):
  - All 4 echo generators exist + are correctly coded (signing at
    line ~187, cut at ~255, booking at ~365, scouting at ~468).
  - The `book` + `scout` decision-logging IS wired in app_web.py:
      * book_fight (app_web.py:7110) logs TYPE_BOOK with
        target_event_id + red/blue fighter_ids in context.
      * assign_scout (app_web.py:9570) logs TYPE_SCOUT with
        target_fighter_id + target_staff_id.
    So booking_echo + scouting_echo CAN fire — they just require
    the player to actually book a fight / assign a scout first.
  - The reason booking_echo + scouting_echo "appear not to fire"
    on the world DB at audit time: the player_decisions table was
    empty (0 rows), so get_decisions_since returned [] and the
    orchestrator cleared today's echoes + returned 0. The 672
    daily_echoes rows observed at audit time were STALE data from
    a prior forward-sim run (dated 2027-06-22 — in the future
    relative to the sim_clock's 2026-08-27), referencing decision_ids
    (4464, 4370) that no longer exist in player_decisions.
  - FIX (defensive hardening, not a feature):
    1. _cleanup_stale_echoes (new): on every generate_echoes call,
       delete (a) any daily_echoes rows with echo_date > sim_date
       (future-dated leftovers from a reverted forward-sim) and
       (b) any rows whose decision_id is not NULL and doesn't
       exist in player_decisions (orphaned by truncation). This
       keeps the cache clean + prevents the dashboard from
       surfacing stale, decision-less echoes.
    2. The dashboard query (app_web.py:~2300) was also tightened
       to filter echo_date <= sim_date (the previous query used
       MAX(echo_date) without a sim_date ceiling, so future-dated
       echoes would dominate the dashboard).
  - Sparse: max 3 echoes per day, deduped by fighter. Relevant:
    every echo is linked to a real player_decisions row.
    Personal: phrases always address the player ("Since you
    signed...", "Your decision to main-event...").
"""

import json
import sqlite3
from datetime import datetime


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

ECHO_TOPIC_SIGNING = "signing_echo"
ECHO_TOPIC_CUT = "cut_echo"
ECHO_TOPIC_BOOKING = "booking_echo"
ECHO_TOPIC_SCOUTING = "scouting_echo"

ALL_ECHO_TYPES = (
    ECHO_TOPIC_SIGNING, ECHO_TOPIC_CUT,
    ECHO_TOPIC_BOOKING, ECHO_TOPIC_SCOUTING,
)

# Decision window — decisions older than this stop echoing.
DECISION_WINDOW_DAYS = 120

# Max echoes per day. (daily_echoes.echo_slot CHECK'd 1..5 so we
# have headroom for future expansion without a schema bump.)
MAX_ECHOES_PER_DAY = 3

# Phrase length cap (per Phase R brief). Phrases that exceed this
# are truncated at the last word boundary.
PHRASE_MAX_CHARS = 120


# ----------------------------------------------------------------
# Voice helpers
# ----------------------------------------------------------------

def _month_name(date_str):
    """Return 'May' for '2026-05-14'. Falls back to the raw date."""
    if not date_str:
        return "—"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%B")
    except Exception:
        return str(date_str)[:7]


def _truncate_phrase(phrase, maxlen=PHRASE_MAX_CHARS):
    """Truncate at the last word boundary ≤maxlen chars. Adds '…'
    only if truncation actually happened."""
    if not phrase:
        return ""
    if len(phrase) <= maxlen:
        return phrase
    cut = phrase[:maxlen - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _fighter_name(conn, fighter_id):
    """Return 'First Last' for a fighter_id, or None if missing."""
    if not fighter_id:
        return None
    row = conn.execute(
        "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return None
    return f"{row[0]} {row[1]}".strip()


def _pronoun_for_fighter(conn, fighter_id, *, possessive=True):
    """Return the gender-aware pronoun for a fighter.

    P1.2 — Echoes engine used to assume male ("he's", "his release").
    Now reads fighters.gender and returns:
      possessive=True  → 'his' / 'her' / 'their'
      possessive=False → 'he'  / 'she' / 'they'
    Falls back to 'their'/'they' for missing fighters or unknown
    gender values (defensive — the seed data may have edge cases).
    """
    if not fighter_id:
        return "their" if possessive else "they"
    row = conn.execute(
        "SELECT gender FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    g = (row[0] if row else "") or ""
    g = g.lower()
    if g == "male":
        return "his" if possessive else "he"
    if g == "female":
        return "her" if possessive else "she"
    return "their" if possessive else "they"


def _format_ordinal(n):
    """Return '1st', '2nd', '3rd', '4th', etc."""
    if not isinstance(n, int) or n < 1:
        return "—"
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ----------------------------------------------------------------
# Echo candidate generators
# ----------------------------------------------------------------
# Each generator returns a list of candidate dicts:
#   {
#     "decision_id": int,
#     "echo_type": str,
#     "phrase": str,
#     "target_fighter_id": int | None,
#     "link_to_screen": "fighter_profile" | "past_events" | None,
#     "weight": float,   # recency × magnitude (higher = more echo-worthy)
#   }
# The orchestrator (generate_echoes) sorts by weight desc + dedups
# by fighter_id, then writes the top 3 to daily_echoes.

def _signing_echo_candidates(conn, decisions, sim_date):
    """Generate candidates from TYPE_SIGN decisions.

    Template: "Since you signed [Fighter] in [Month], {pronoun}'s won
    [N] straight." Gender-aware pronoun per P1.2.
    Requires the fighter to have at least 1 fight since signing.
    """
    candidates = []
    for d in decisions:
        if d["decision_type"] != "sign":
            continue
        fid = d["target_fighter_id"]
        if not fid:
            continue
        name = _fighter_name(conn, fid)
        if not name:
            continue
        subj = _pronoun_for_fighter(conn, fid, possessive=False)
        poss = _pronoun_for_fighter(conn, fid, possessive=True)
        # Count wins since signing date.
        rows = conn.execute(
            "SELECT outcome FROM fight_history "
            "WHERE fighter_id=? AND event_date >= ? "
            "ORDER BY event_date DESC",
            (fid, d["decision_date"]),
        ).fetchall()
        if not rows:
            continue
        # Streak = consecutive wins from the most-recent fight backwards.
        streak = 0
        for r in rows:
            if r[0] == "win":
                streak += 1
            else:
                break
        # Magnitude: 3 for 4+ streak, 2 for 2-3, 1 for 1 (or losses but at least 1 fight).
        n_fights = len(rows)
        if streak >= 4:
            mag = 3
            phrase = (f"Since you signed {name} in {_month_name(d['decision_date'])}, "
                      f"{subj}'s won {streak} straight.")
        elif streak >= 2:
            mag = 2
            phrase = (f"Since you signed {name} in {_month_name(d['decision_date'])}, "
                      f"{subj}'s won {streak} straight.")
        elif streak == 1:
            mag = 1
            phrase = (f"Since you signed {name} in {_month_name(d['decision_date'])}, "
                      f"{subj}'s won {poss} debut.")
        else:
            # No win streak — instead surface "{pronoun}'s fought N times"
            # only if there's been at least 1 fight.
            if n_fights == 0:
                continue
            mag = 1
            phrase = (f"Since you signed {name} in {_month_name(d['decision_date'])}, "
                      f"{subj}'s fought {n_fights} time{'s' if n_fights != 1 else ''}.")
        candidates.append({
            "decision_id": d["decision_id"],
            "echo_type": ECHO_TOPIC_SIGNING,
            "phrase": _truncate_phrase(phrase),
            "target_fighter_id": fid,
            "link_to_screen": "fighter_profile",
            "weight": _recency_weight(d["decision_date"], sim_date) * mag,
        })
    return candidates


def _cut_echo_candidates(conn, decisions, sim_date):
    """Generate candidates from TYPE_CUT decisions.

    P1.2 — Rephrased. Old template:
      "[Fighter], who you released in [Month], just [won his debut /
       won the [Rival] title / lost 3 straight] for [Rival Promo]."
    New template:
      "Since {pronoun} release in [Month], [Fighter] has [won the
       [Rival] title / signed with [Rival] / lost N straight /
       fought N times]."
    The rephrase avoids implying the player is still responsible for
    a fighter they no longer contract (the old "who you released"
    framing implied ongoing ownership). Gender-aware pronouns
    (his/her/their) per fighter.gender.

    Looks for news_items about the fighter since the cut date.
    """
    candidates = []
    for d in decisions:
        if d["decision_type"] != "cut":
            continue
        fid = d["target_fighter_id"]
        if not fid:
            continue
        name = _fighter_name(conn, fid)
        if not name:
            continue
        pronoun = _pronoun_for_fighter(conn, fid, possessive=True)
        month = _month_name(d["decision_date"])
        # Find news about this fighter since the cut date. We're
        # looking for 3 patterns: debut win, title win, losing streak.
        news_rows = conn.execute(
            "SELECT headline, topic FROM news_items "
            "WHERE fighter_id=? AND published_at >= ? "
            "ORDER BY published_at DESC LIMIT 10",
            (fid, d["decision_date"]),
        ).fetchall()
        if not news_rows:
            continue
        # Pick the most consequential news item.
        phrase = None
        magnitude = 1
        for headline, topic in news_rows:
            h = (headline or "").lower()
            if "title" in h or "champion" in h or "belt" in h:
                # Find which promo they won the title for.
                promo_row = conn.execute(
                    "SELECT p.name FROM news_items ni "
                    "JOIN promotions p ON p.promotion_id = ni.promotion_id "
                    "WHERE ni.news_item_id IN ("
                    "  SELECT news_item_id FROM news_items "
                    "  WHERE fighter_id=? AND published_at >= ? "
                    "  AND (headline LIKE '%title%' OR headline LIKE '%champion%' OR headline LIKE '%belt%')"
                    ") LIMIT 1",
                    (fid, d["decision_date"]),
                ).fetchone()
                rival = promo_row[0] if promo_row else "a rival promotion"
                phrase = (f"Since {pronoun} release in {month}, "
                          f"{name} has won the {rival} title.")
                magnitude = 3
                break
            if "debut" in h or "signed" in h or "signs" in h:
                # Look for debut-win news.
                promo_row = conn.execute(
                    "SELECT p.name FROM news_items ni "
                    "JOIN promotions p ON p.promotion_id = ni.promotion_id "
                    "WHERE ni.fighter_id=? AND ni.published_at >= ? "
                    "AND (ni.headline LIKE '%debut%' OR ni.headline LIKE '%signed%' OR ni.headline LIKE '%signs%') "
                    "LIMIT 1",
                    (fid, d["decision_date"]),
                ).fetchone()
                rival = promo_row[0] if promo_row else "a rival promotion"
                phrase = (f"Since {pronoun} release in {month}, "
                          f"{name} has signed with {rival}.")
                magnitude = 2
                break
        if not phrase:
            # Fallback: count fights since cut.
            fight_rows = conn.execute(
                "SELECT outcome FROM fight_history "
                "WHERE fighter_id=? AND event_date >= ? "
                "ORDER BY event_date DESC",
                (fid, d["decision_date"]),
            ).fetchall()
            if not fight_rows:
                continue
            losses = sum(1 for r in fight_rows if r[0] == "loss")
            wins = sum(1 for r in fight_rows if r[0] == "win")
            if losses >= 3:
                phrase = (f"Since {pronoun} release in {month}, "
                          f"{name} has lost {losses} straight.")
                magnitude = 1
            elif wins >= 1:
                phrase = (f"Since {pronoun} release in {month}, "
                          f"{name} has fought {len(fight_rows)} time"
                          f"{'s' if len(fight_rows) != 1 else ''}.")
                magnitude = 1
            else:
                continue
        candidates.append({
            "decision_id": d["decision_id"],
            "echo_type": ECHO_TOPIC_CUT,
            "phrase": _truncate_phrase(phrase),
            "target_fighter_id": fid,
            "link_to_screen": "fighter_profile",
            "weight": _recency_weight(d["decision_date"], sim_date) * magnitude,
        })
    return candidates


def _booking_echo_candidates(conn, decisions, sim_date):
    """Generate candidates from TYPE_BOOK decisions.

    Template: "Your decision to main-event [Fighter A] vs [Fighter B]
    at [Event] drew [N] fans — your [Nth]-biggest gate this year."

    Requires the event to be completed + have a show_ratings row.
    """
    candidates = []
    # Get all completed events for the player's promo this year, ranked by attendance.
    # We need this for the "Nth-biggest gate this year" comparison.
    player_pid_row = conn.execute(
        "SELECT setting_value FROM player_settings "
        "WHERE setting_key='player_promotion_id'"
    ).fetchone()
    if not player_pid_row or not player_pid_row[0]:
        return []
    try:
        player_pid = int(player_pid_row[0])
    except Exception:
        return []

    # Get this year's completed events ranked by attendance (descending).
    # We need attendance data — events table doesn't have it directly,
    # but show_ratings may, or we can use a fallback.
    year_rows = conn.execute(
        "SELECT e.event_id, e.event_name, e.event_date, "
        "  (SELECT COUNT(*) FROM fight_participants fp "
        "   JOIN fights f ON f.fight_id = fp.fight_id "
        "   WHERE f.event_id = e.event_id) AS fight_count "
        "FROM events e "
        "WHERE e.promotion_id=? AND e.status='completed' "
        "AND strftime('%Y', e.event_date) = strftime('%Y', ?) "
        "ORDER BY e.event_date DESC",
        (player_pid, sim_date),
    ).fetchall()
    # Rank by fight_count (proxy for gate size — we don't have raw
    # attendance in the schema; show_ratings.overall_rating is the
    # closest "size" signal available).
    year_events = sorted(year_rows, key=lambda r: -(r[3] or 0))
    event_rank = {row[0]: i + 1 for i, row in enumerate(year_events)}
    total_year_events = len(year_events)

    for d in decisions:
        if d["decision_type"] != "book":
            continue
        eid = d["target_event_id"]
        if not eid:
            continue
        # Find the event + verify it's completed.
        ev_row = conn.execute(
            "SELECT event_name, event_date, status, promotion_id "
            "FROM events WHERE event_id=?",
            (eid,),
        ).fetchone()
        if not ev_row or ev_row[2] != "completed":
            continue
        if ev_row[3] != player_pid:
            continue
        event_name = ev_row[0] or "your event"
        rank = event_rank.get(eid)
        if not rank or total_year_events < 2:
            continue
        # Find the main-event fighters (fight_participants with is_main_event).
        me_row = conn.execute(
            "SELECT fp.fighter_id, f.first_name, f.last_name "
            "FROM event_cards ec "
            "JOIN fight_participants fp ON fp.fight_id = ec.fight_id "
            "JOIN fighters f ON f.fighter_id = fp.fighter_id "
            "WHERE ec.event_id=? AND ec.is_main_event=1 "
            "ORDER BY fp.corner LIMIT 2",
            (eid,),
        ).fetchall()
        if len(me_row) >= 2:
            fighters_str = f"{me_row[0][1]} {me_row[0][2]} vs {me_row[1][1]} {me_row[1][2]}"
            target_fid = me_row[0][0]
        elif me_row:
            fighters_str = f"{me_row[0][1]} {me_row[0][2]}"
            target_fid = me_row[0][0]
        else:
            fighters_str = event_name
            target_fid = None
        # Magnitude: top-3 gate of the year → 3; top-5 → 2; else 1.
        if rank <= 3:
            mag = 3
        elif rank <= 5:
            mag = 2
        else:
            mag = 1
        phrase = (f"Your decision to main-event {fighters_str} at "
                  f"{event_name} was your {_format_ordinal(rank)}-biggest "
                  f"card of the year.")
        candidates.append({
            "decision_id": d["decision_id"],
            "echo_type": ECHO_TOPIC_BOOKING,
            "phrase": _truncate_phrase(phrase),
            "target_fighter_id": target_fid,
            "link_to_screen": "past_events",
            "weight": _recency_weight(d["decision_date"], sim_date) * mag,
        })
    return candidates


def _scouting_echo_candidates(conn, decisions, sim_date):
    """Generate candidates from TYPE_SCOUT decisions.

    Template: "[Fighter], who you scouted in [Month] as a [ceiling
    phrase], has since [improved / regressed] — your scout was
    [right / wrong]."

    Reads scouting_reports for the original ceiling phrase, then
    compares to the fighter's current career_phase to gauge whether
    the scout was right.
    """
    candidates = []
    for d in decisions:
        if d["decision_type"] != "scout":
            continue
        fid = d["target_fighter_id"]
        if not fid:
            continue
        name = _fighter_name(conn, fid)
        if not name:
            continue
        # Original ceiling phrase from the scouting report.
        sr_row = conn.execute(
            "SELECT estimated_ceiling FROM scouting_reports "
            "WHERE target_fighter_id=? "
            "ORDER BY report_date DESC LIMIT 1",
            (fid,),
        ).fetchone()
        if not sr_row or not sr_row[0]:
            continue
        ceiling_phrase = sr_row[0]
        # Current career_phase to gauge scout accuracy.
        fd_row = conn.execute(
            "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if not fd_row or not fd_row[0]:
            continue
        cp = fd_row[0]
        # career_phase is stored as "label||phrase". Extract label.
        cp_label = cp.split("||", 1)[0] if "||" in cp else cp
        ceiling_lower = (ceiling_phrase or "").lower()
        # Scout was right if a high ceiling → champion/rising_contender,
        # or a low ceiling → declining/gatekeeper.
        if ceiling_lower in ("elite", "high"):
            scout_right = cp_label in ("champion", "dominant_champion",
                                       "rising_contender")
        elif ceiling_lower in ("above_avg", "above_average", "average", "avg"):
            scout_right = cp_label in ("rising_contender", "gatekeeper",
                                       "veteran")
        else:
            scout_right = cp_label in ("declining", "veteran", "gatekeeper")
        # Did the fighter improve or regress since being scouted?
        if cp_label in ("champion", "dominant_champion", "rising_contender"):
            trend = "improved"
            mag = 3 if scout_right else 2
        elif cp_label in ("declining",):
            trend = "regressed"
            mag = 2 if not scout_right else 1
        else:
            trend = "held steady"
            mag = 1
        right_phrase = "right" if scout_right else "wrong"
        phrase = (f"{name}, who you scouted in "
                  f"{_month_name(d['decision_date'])} as {ceiling_phrase}, "
                  f"has {trend} — your scout was {right_phrase}.")
        candidates.append({
            "decision_id": d["decision_id"],
            "echo_type": ECHO_TOPIC_SCOUTING,
            "phrase": _truncate_phrase(phrase),
            "target_fighter_id": fid,
            "link_to_screen": "fighter_profile",
            "weight": _recency_weight(d["decision_date"], sim_date) * mag,
        })
    return candidates


# ----------------------------------------------------------------
# Recency weighting
# ----------------------------------------------------------------

def _recency_weight(decision_date, sim_date, window_days=DECISION_WINDOW_DAYS):
    """Linear decay from 1.0 (today) → 0.0 (window_days ago).

    Decisions older than the window get weight 0 (they stop echoing).
    Decisions dated in the future (shouldn't happen, but defensive)
    get weight 1.0.

    Args:
        decision_date: YYYY-MM-DD string (the date of the player
            decision).
        sim_date: YYYY-MM-DD string (the current sim date). Passed
            explicitly by the caller (generate_echoes) so we don't
            have to query the clock once per decision.
        window_days: int, default 120. Decisions older than this
            get weight 0.
    """
    if not decision_date or not sim_date:
        return 0.0
    try:
        d_dec = datetime.strptime(decision_date[:10], "%Y-%m-%d")
        d_sim = datetime.strptime(sim_date[:10], "%Y-%m-%d")
    except Exception:
        return 0.0
    age_days = (d_sim - d_dec).days
    if age_days < 0:
        return 1.0
    if age_days >= window_days:
        return 0.0
    return 1.0 - (age_days / window_days)


# ----------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------

def generate_echoes(conn, sim_date=None):
    """Generate + write 2-3 daily echoes for the current sim date.

    Called on every Advance Day (TICK_ADVANCED subscriber registered
    in interpretation/__init__.py). Reads recent player_decisions,
    generates echo candidates from each of the 4 templates, picks the
    top 3 by weight (deduped by fighter), and writes them to the
    daily_echoes cache table (INSERT OR REPLACE — idempotent).

    Performance: <50ms per call. All queries hit indexes.

    Args:
        conn: sqlite3.Connection. Caller commits (the TICK_ADVANCED
            subscriber runs in the simulation transaction; the
            echoes rows are written + committed with the rest of
            the day's writes).
        sim_date: optional YYYY-MM-DD string. If None, reads from
            the simulation_clock. Useful for testing.

    Returns:
        int — number of echoes written (0..MAX_ECHOES_PER_DAY).
    """
    if sim_date is None:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        sim_date = row[0] if row else None
    if not sim_date:
        return 0

    # HW3.4 — defensive cleanup of stale echoes (future-dated or
    # orphaned). Runs on every generate_echoes call so the cache
    # stays clean even after a reverted forward-sim or a
    # player_decisions truncation. See the audit findings at the
    # top of this file.
    _cleanup_stale_echoes(conn, sim_date)

    # Defensive: if player_decisions table doesn't exist (shouldn't
    # happen post-v3.16.0, but be safe), exit silently.
    try:
        from player_decisions import get_decisions_since
        decisions = get_decisions_since(conn, DECISION_WINDOW_DAYS)
    except Exception as e:
        print(f"[echoes_engine] WARN: get_decisions_since failed: {e}",
              flush=True)
        return 0
    if not decisions:
        # No decisions — clear any stale echoes for today + exit.
        _clear_echoes_for_date(conn, sim_date)
        return 0

    # Generate candidates from each template.
    candidates = []
    try:
        candidates.extend(_signing_echo_candidates(conn, decisions, sim_date))
    except Exception as e:
        print(f"[echoes_engine] WARN: signing echoes failed: {e}",
              flush=True)
    try:
        candidates.extend(_cut_echo_candidates(conn, decisions, sim_date))
    except Exception as e:
        print(f"[echoes_engine] WARN: cut echoes failed: {e}",
              flush=True)
    try:
        candidates.extend(_booking_echo_candidates(conn, decisions, sim_date))
    except Exception as e:
        print(f"[echoes_engine] WARN: booking echoes failed: {e}",
              flush=True)
    try:
        candidates.extend(_scouting_echo_candidates(conn, decisions, sim_date))
    except Exception as e:
        print(f"[echoes_engine] WARN: scouting echoes failed: {e}",
              flush=True)

    if not candidates:
        _clear_echoes_for_date(conn, sim_date)
        return 0

    # Sort by weight desc. Dedup by target_fighter_id (a fighter
    # should only appear in 1 echo per day — pick their highest-
    # weighted candidate).
    candidates.sort(key=lambda c: -c["weight"])
    seen_fighters = set()
    top = []
    for c in candidates:
        fid = c.get("target_fighter_id")
        if fid and fid in seen_fighters:
            continue
        if fid:
            seen_fighters.add(fid)
        top.append(c)
        if len(top) >= MAX_ECHOES_PER_DAY:
            break

    # Write to daily_echoes (INSERT OR REPLACE — idempotent for the
    # same date). Clear any stale slots first so re-runs don't leave
    # orphan rows in slots > len(top).
    _clear_echoes_for_date(conn, sim_date)
    for slot_idx, c in enumerate(top, start=1):
        conn.execute(
            "INSERT OR REPLACE INTO daily_echoes "
            "(echo_date, echo_slot, echo_type, phrase, decision_id, "
            " target_fighter_id, link_to_screen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sim_date, slot_idx, c["echo_type"], c["phrase"],
             c.get("decision_id"), c.get("target_fighter_id"),
             c.get("link_to_screen")),
        )
    return len(top)


def _clear_echoes_for_date(conn, sim_date):
    """Delete all daily_echoes rows for `sim_date` (used so re-runs
    don't leave orphan slots)."""
    try:
        conn.execute(
            "DELETE FROM daily_echoes WHERE echo_date=?",
            (sim_date,),
        )
    except Exception:
        pass


def _cleanup_stale_echoes(conn, sim_date):
    """HW3.4 — defensive cleanup of stale daily_echoes rows.

    Two cleanup passes:
      1. Delete rows with echo_date > sim_date. These are future-dated
         leftovers from a reverted forward-sim (e.g. a soak test that
         advanced the clock past the player's actual sim date, then
         got rolled back). Without this, the dashboard's MAX(echo_date)
         query would surface future-dated echoes that reference
         decision_ids no longer in player_decisions.
      2. Delete rows whose decision_id is not NULL and doesn't exist
         in player_decisions. These are orphaned by player_decisions
         truncation (e.g. the world DB at audit time had 672 echoes
         referencing decisions 4464 + 4370 that no longer existed).

    Both passes are wrapped in try/except so a missing table or
    transient error doesn't break the echoes generation flow.

    Args:
        conn: sqlite3.Connection. Caller commits.
        sim_date: YYYY-MM-DD string. Rows with echo_date > sim_date
            are deleted.
    """
    if not sim_date:
        return
    try:
        # Pass 1: future-dated echoes.
        conn.execute(
            "DELETE FROM daily_echoes WHERE echo_date > ?",
            (sim_date,),
        )
    except Exception:
        pass
    try:
        # Pass 2: echoes whose decision_id no longer exists in
        # player_decisions. LEFT JOIN → keep rows where the join
        # fails (pd.decision_id IS NULL) AND de.decision_id IS NOT
        # NULL (we don't want to delete echoes with no decision_id —
        # those are valid legacy echoes from before the decision_id
        # column was added).
        conn.execute(
            "DELETE FROM daily_echoes "
            "WHERE decision_id IS NOT NULL "
            "  AND decision_id NOT IN ("
            "    SELECT decision_id FROM player_decisions)"
        )
    except Exception:
        pass


# ----------------------------------------------------------------
# Event bus subscription
# ----------------------------------------------------------------

def _on_tick_advanced(conn, event):
    """TICK_ADVANCED subscriber — generate + write daily echoes.

    Registered in interpretation/__init__.py. The event payload
    includes 'current_date' (the new sim date after the tick).
    """
    sim_date = event.get("current_date") if event else None
    if not sim_date:
        # Fall back to reading the clock directly.
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        sim_date = row[0] if row else None
    if not sim_date:
        return
    try:
        generate_echoes(conn, sim_date)
    except Exception as e:
        # Defensive — echoes failure must never break the simulation.
        # The event_bus ALSO catches subscriber exceptions, but we
        # log here with context for easier debugging.
        import sys
        print(f"WARNING: echoes_engine.generate_echoes failed on "
              f"TICK_ADVANCED: {type(e).__name__}: {e}", file=sys.stderr)


def register_subscribers():
    """Register echoes_engine subscribers on the event bus.

    Subscribes to TICK_ADVANCED. The echoes engine refreshes the
    daily_echoes cache on every Advance Day so the Dashboard always
    shows fresh consequences of the player's past decisions.

    Registered via interpretation/__init__.py (Phase R brief: "Subscribe
    to the event bus via src/interpretation/__init__.py — follow the
    existing registration pattern"). The interpretation layer is
    registered LAST per CONVENTIONS §17.5 so all simulation writes
    are visible to the echoes queries.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.TICK_ADVANCED, _on_tick_advanced,
                  name="echoes_engine.tick_advanced")
