"""CAGE EMPIRE Rivalries System (Task 22, extended Phase A — A2 + A3 + A8).

Pairwise rivalries between fighters, entirely event-bus-driven
(Task 18.5). Subscribes to FIGHT_RESOLVED, TITLE_CHANGED, and
TICK_ADVANCED and writes voice-layer-driven rivalry records to the
`rivalries` table (added in v3.2.0).

CONVENTIONS compliance:
  §13 — Design Law: every rivalry tells a story. A rivalry isn't a
        hidden flag on a fight; it's a tracked relationship with a
        heat level, an origin narrative, head-to-head fight counts,
        and a type (callout / bad_blood / title_rivalry /
        rematch_hungry / style_clash / disrespect /
        stolen_opportunity). Strengthens Conflict (rivalries drive
        rematches and bad blood) and Anticipation (the player sees
        rivalries simmering and wants to book the rematch).
  §14 — Voice Layer: NO raw attribute values, heat numbers, or
        internal ratings appear in any rivalry description text.
        Fighter descriptions come from voice.describe_career_stage
        (career stage descriptor only — the player sees "reigning
        champion" vs "top prospect", not "age 32 vs age 24"). Origin
        narratives use word forms ("social media callouts", "a
        weight-cut miss", "a controversial decision") — no digit
        characters anywhere.
  §15 — Event Bus: the rivalries system is entirely event-driven. It
        subscribes to events published by resolve_next_fight and
        run_tick; no new inline side effects are added to those
        functions (§15.4). The existing side effects remain
        untouched. The fight engine (resolve_next_fight in app.py) is
        NOT modified per the brief — readers (get_rivalry,
        get_active_rivalries) are provided for the A8 fight-engine
        modifier (heat > 70 → +aggression, -composure).

RIVALRY HEAT ESCALATION:
  Each callout/trash_talk social post between rivals: +5 heat
  Each fight between rivals: +15 heat
  Title fight between rivals: +25 heat
  Weight cut miss against a rival: +10 heat
  Apology social post: -15 heat (A2: bumped from -10)
  Heat caps at 100 (CHECK + code clamp)

RIVALRY HEAT DECAY (A2):
  On each weekly tick (current_day % 7 == 0), every active rivalry
  loses -1 heat. Below heat=20, the rivalry goes dormant
  (is_active=0). Dormant rivalries are preserved (no DELETE) and
  re-activate automatically when a fresh escalation bumps heat back
  above 20.

SAME-ROSTER RESTRICTIONS (A3):
  Callouts/trash-talk posts only graduate into a tracked rivalry
  when the fighter pair is in the same promotion. Cross-promotion
  callouts are allowed only for same-weight-class pairs with a 5%
  chance (the rare inter-promotion superfight). Free agents (no
  current_promotion_id) bypass the gate — they can call out anyone.

USAGE:
  from rivalries import register_subscribers
  register_subscribers()  # call once at startup (UI / tests)

  # The system automatically processes events via the bus. Readers:
  from rivalries import get_rivalry, get_active_rivalries
  row = get_rivalry(conn, fighter_a_id, fighter_b_id)
  rows = get_active_rivalries(conn, fighter_id)

The system is ADDITIVE — existing inline side effects in
resolve_next_fight and run_tick remain untouched (§15.4)."""

import random
from datetime import datetime

from voice import describe_career_stage


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# Minimum number of callout/trash_talk social posts between two
# fighters required for the TICK_ADVANCED beef scan to spawn a new
# 'callout' rivalry. Picked so a single impulsive callout doesn't
# create a rivalry — both fighters need to engage for the beef to
# escalate (matches the directional beef logic in social.py).
_MIN_BEEF_POSTS_FOR_RIVALRY = 3

# Heat deltas (CONVENTIONS §15.4 — purely additive to the rivalry
# heat column; the CHECK constraint clamps to [0, 100] and the code
# clamps before UPDATE to keep the CHECK from ever failing).
_HEAT_CALLOUT_POST = +5     # callout or trash_talk social post between rivals
_HEAT_FIGHT_BETWEEN_RIVALS = +15
_HEAT_TITLE_FIGHT_BETWEEN_RIVALS = +25
_HEAT_WEIGHT_CUT_MISS = +10
_HEAT_APOLOGY_POST = -15    # apology reduces heat (de-escalation) — A2: bumped from -10 to -15

# Maximum heat value (mirrors the CHECK constraint).
_MAX_HEAT = 100
_MIN_HEAT = 0

# A2 — weekly heat decay. Active rivalries lose -1 heat per sim week
# (days that are multiples of 7). When heat drops below the dormancy
# threshold, is_active is set to 0 (dormant). A dormant rivalry keeps
# its row (the history is preserved) but no longer qualifies as
# "active" for fight-engine modifiers (A8) or news/social targeting.
_HEAT_WEEKLY_DECAY = -1
_HEAT_DORMANCY_THRESHOLD = 20

# A3 — same-roster restrictions. Cross-promotion callouts are only
# allowed between fighters in the same weight class, with a small
# probability. Inter-promotion beefs generate extra hype but are
# rare — most callouts stay within a promotion's roster.
_CROSS_PROMO_CALLOUT_CHANCE = 0.05

# Close-decision threshold — score_margin <= this in a decision
# result triggers 'rematch_hungry' rivalry creation.
_CLOSE_DECISION_MARGIN = 2

# Valid rivalry types (matches the CHECK constraint on rivalries).
VALID_RIVALRY_TYPES = (
    "callout", "bad_blood", "title_rivalry", "rematch_hungry",
    "style_clash", "disrespect", "stolen_opportunity",
)

# Word-form helpers (no digit characters per CONVENTIONS §14).
# Maps rivalry_type → noun phrase used in the description template.
_TYPE_PHRASE = {
    "callout":            "callout-driven",
    "bad_blood":          "bad blood",
    "title_rivalry":      "title",
    "rematch_hungry":     "rematch-hungry",
    "style_clash":        "style-clash",
    "disrespect":         "disrespect-fueled",
    "stolen_opportunity": "stolen-opportunity",
}


# ----------------------------------------------------------------
# Fighter / promotion data helpers (mirror news.py + social.py)
# ----------------------------------------------------------------

def _fighter_full_name(conn, fighter_id):
    """Return 'John Vale' or 'John "Hammer" Vale' for a fighter."""
    if fighter_id is None:
        return "Unknown Fighter"
    row = conn.execute(
        "SELECT first_name, last_name, nickname FROM fighters "
        "WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "Unknown Fighter"
    first, last, nick = row
    if nick:
        return f'{first} "{nick}" {last}'
    return f"{first} {last}"


def _fighter_age(conn, fighter_id, current_date=None):
    """Compute a fighter's age based on DOB and a reference date."""
    row = conn.execute(
        "SELECT date_of_birth FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row or not row[0]:
        return 30
    dob_str = row[0]
    ref_str = current_date
    if ref_str is None:
        clock = conn.execute(
            "SELECT simulation_clock.current_date FROM simulation_clock "
            "WHERE clock_id=1"
        ).fetchone()
        ref_str = clock[0] if clock else "2026-08-15"
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d")
        ref = datetime.strptime(ref_str, "%Y-%m-%d")
        age = ref.year - dob.year
        if (ref.month, ref.day) < (dob.month, dob.day):
            age -= 1
        return age
    except (ValueError, TypeError):
        return 30


def _fighter_career_stage(conn, fighter_id, rng=None, current_date=None):
    """Return the fighter's career stage descriptor (voice layer)."""
    if fighter_id is None:
        return "roster fighter"
    row = conn.execute(
        "SELECT fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.title_reigns, "
        "fc.career_health, "
        "EXISTS(SELECT 1 FROM titles t "
        "       WHERE t.current_champion_fighter_id = f.fighter_id) AS is_champ "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "roster fighter"
    wins, losses, draws, ws, ls, reigns, health, is_champ = row
    age = _fighter_age(conn, fighter_id, current_date=current_date)
    return describe_career_stage(
        age,
        wins or 0, losses or 0, draws or 0,
        is_champion=bool(is_champ),
        title_reigns=reigns or 0,
        win_streak=ws or 0, loss_streak=ls or 0,
        rng=rng,
    )


# ----------------------------------------------------------------
# Canonical pair ordering
# ----------------------------------------------------------------

def _canonical_pair(a_id, b_id):
    """Return (lower_id, higher_id) for canonical rivalry pair ordering.

    The rivalries table has UNIQUE (fighter_a_id, fighter_b_id) — we
    always store the lower fighter_id as fighter_a_id so the same
    pair can't be stored twice (once as A,B and once as B,A).
    """
    if a_id is None or b_id is None:
        return (None, None)
    if a_id == b_id:
        return (None, None)
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


# ----------------------------------------------------------------
# Readers (per CONVENTIONS §5.3 — every new table must ship with a
# reader). Used by the upcoming fight-engine integration task to
# apply rivalry-heat modifiers (the brief says: high heat > 70 →
# both fighters get +aggression, -composure; title_rivalry → extra
# importance/hype).
# ----------------------------------------------------------------

def get_rivalry(conn, fighter_a_id, fighter_b_id):
    """Return the rivalry row for a fighter pair, or None.

    The two fighter IDs can be passed in any order — the function
    canonicalizes them before querying.

    Returns a sqlite3.Row (or tuple, depending on row_factory) with
    all rivalries columns: rivalry_id, fighter_a_id, fighter_b_id,
    rivalry_heat, rivalry_type, origin_event, origin_description,
    fights_count, fighter_a_wins, fighter_b_wins, draws, is_active,
    last_escalation_date, created_at, updated_at.
    """
    a, b = _canonical_pair(fighter_a_id, fighter_b_id)
    if a is None:
        return None
    return conn.execute(
        "SELECT * FROM rivalries "
        "WHERE fighter_a_id=? AND fighter_b_id=?",
        (a, b),
    ).fetchone()


def get_active_rivalries(conn, fighter_id):
    """Return all active rivalries involving the given fighter.

    Returns a list of rivalry rows (one per active rivalry the
    fighter is part of). Includes both directions (fighter_id may be
    fighter_a_id OR fighter_b_id on the row). The rival's fighter_id
    can be derived as (fighter_a_id + fighter_b_id) - fighter_id.
    """
    if fighter_id is None:
        return []
    return conn.execute(
        "SELECT * FROM rivalries "
        "WHERE is_active = 1 "
        "AND (fighter_a_id = ? OR fighter_b_id = ?) "
        "ORDER BY rivalry_heat DESC",
        (fighter_id, fighter_id),
    ).fetchall()


def get_rivalry_heat(conn, fighter_a_id, fighter_b_id):
    """Return the rivalry heat (0-100) for a fighter pair, or 0.

    Convenience reader for the upcoming fight-engine integration
    task. Returns 0 if no rivalry exists (no heat modifier).
    """
    row = get_rivalry(conn, fighter_a_id, fighter_b_id)
    if row is None:
        return 0
    # sqlite3.Row supports both index and key access — be defensive.
    try:
        return row["rivalry_heat"] or 0
    except (KeyError, IndexError, TypeError):
        # tuple fallback — rivalry_heat is column index 2
        return row[2] if len(row) > 2 else 0


# ----------------------------------------------------------------
# Internal: rivalry creation / escalation helpers
# ----------------------------------------------------------------

def _clamp_heat(value):
    """Clamp a heat value to [0, 100] (matches CHECK constraint)."""
    return max(_MIN_HEAT, min(_MAX_HEAT, value))


def _build_origin_description(conn, fighter_a_id, fighter_b_id,
                              rivalry_type, origin_narrative,
                              rng=None, current_date=None):
    """Build a voice-layer-driven rivalry description (no raw numbers).

    Returns a string like:
      "A bad blood rivalry between John Vale (reigning champion) and
       Marcus Reed (top prospect). The rivalry started with a weight-
       cut miss before their fight."

    The {rivalry_type_phrase} comes from _TYPE_PHRASE (CONVENTIONS §14
    — no digit characters). The {career_stage_a} / {career_stage_b}
    come from voice.describe_career_stage.
    """
    name_a = _fighter_full_name(conn, fighter_a_id)
    name_b = _fighter_full_name(conn, fighter_b_id)
    stage_a = _fighter_career_stage(
        conn, fighter_a_id, rng=rng, current_date=current_date,
    )
    stage_b = _fighter_career_stage(
        conn, fighter_b_id, rng=rng, current_date=current_date,
    )
    type_phrase = _TYPE_PHRASE.get(rivalry_type, "simmering")
    return (
        f"A {type_phrase} rivalry between {name_a} ({stage_a}) and "
        f"{name_b} ({stage_b}). {origin_narrative}"
    )


def _create_rivalry(conn, fighter_a_id, fighter_b_id, rivalry_type,
                    origin_event, origin_narrative, initial_heat=50,
                    rng=None, current_date=None):
    """Create a new rivalry row. Returns the rivalry_id, or None if
    the row already exists (defensive — caller should check first)
    or the pair is invalid.

    Args:
        conn: sqlite3.Connection (caller commits).
        fighter_a_id, fighter_b_id: the two fighter IDs (any order —
            canonicalized internally).
        rivalry_type: one of VALID_RIVALRY_TYPES.
        origin_event: short context marker (e.g., 'social_media',
            'fight:{fight_id}', 'title_change:{title_id}'). Stored
            in the origin_event column for audit trail.
        origin_narrative: the trailing sentence of the description
            (e.g., "The rivalry started with callouts on social
            media.") — combined with the type phrase and fighter
            names + career stages via _build_origin_description.
        initial_heat: starting heat value (default 50). Clamped to
            [0, 100].
        rng: optional random.Random for voice descriptor variety.
        current_date: optional reference date for age computation.
    """
    if rivalry_type not in VALID_RIVALRY_TYPES:
        return None
    a, b = _canonical_pair(fighter_a_id, fighter_b_id)
    if a is None:
        return None
    # Defensive: if the rivalry already exists, do nothing (caller
    # should have called get_rivalry first — but be safe).
    existing = conn.execute(
        "SELECT rivalry_id FROM rivalries "
        "WHERE fighter_a_id=? AND fighter_b_id=?",
        (a, b),
    ).fetchone()
    if existing:
        return existing[0]
    description = _build_origin_description(
        conn, a, b, rivalry_type, origin_narrative,
        rng=rng, current_date=current_date,
    )
    heat = _clamp_heat(initial_heat)
    cur = conn.execute(
        "INSERT INTO rivalries "
        "(fighter_a_id, fighter_b_id, rivalry_heat, rivalry_type, "
        " origin_event, origin_description, last_escalation_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (a, b, heat, rivalry_type, origin_event, description,
         current_date),
    )
    return cur.lastrowid


def _escalate_rivalry(conn, fighter_a_id, fighter_b_id, heat_delta,
                      current_date=None, increment_fights=False,
                      winner_id=None, is_draw=False):
    """Apply a heat delta + optional fight-count increment to an
    existing rivalry.

    Args:
        conn: sqlite3.Connection (caller commits).
        fighter_a_id, fighter_b_id: the pair (any order).
        heat_delta: signed int to add to rivalry_heat (clamped to
            [0, 100] before UPDATE).
        current_date: ISO date string for last_escalation_date.
        increment_fights: if True, increment fights_count and update
            fighter_a_wins / fighter_b_wins / draws based on
            winner_id + is_draw.
        winner_id: the winner's fighter_id (used only if
            increment_fights=True). None for draws.
        is_draw: if True, increment draws (winner_id is ignored).
    """
    a, b = _canonical_pair(fighter_a_id, fighter_b_id)
    if a is None:
        return
    row = conn.execute(
        "SELECT rivalry_id, rivalry_heat, is_active FROM rivalries "
        "WHERE fighter_a_id=? AND fighter_b_id=?",
        (a, b),
    ).fetchone()
    if not row:
        return
    rivalry_id, current_heat, is_active = row
    new_heat = _clamp_heat((current_heat or 0) + heat_delta)
    # A2 — re-activate dormant rivalries when heat is bumped back
    # above the dormancy threshold (e.g., a fresh callout post). This
    # is the inverse of _decay_rivalry_heat's dormancy logic. Together
    # they form a hysteresis loop: decay sends a quiet rivalry to
    # sleep, escalation wakes it back up when the beef resumes.
    reactivate = (not is_active) and (new_heat >= _HEAT_DORMANCY_THRESHOLD)

    def _do_update(sql, params):
        """Execute the UPDATE; if reactivate=True, also flip is_active=1."""
        conn.execute(sql, params)
        if reactivate:
            conn.execute(
                "UPDATE rivalries SET is_active=1, "
                "updated_at=CURRENT_TIMESTAMP WHERE rivalry_id=?",
                (rivalry_id,),
            )

    if increment_fights:
        # Determine which side won. winner_id maps to fighter_a or b.
        if is_draw:
            _do_update(
                "UPDATE rivalries SET rivalry_heat=?, "
                "fights_count = fights_count + 1, "
                "draws = draws + 1, "
                "last_escalation_date=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE rivalry_id=?",
                (new_heat, current_date, rivalry_id),
            )
        elif winner_id is not None:
            if winner_id == a:
                win_col = "fighter_a_wins"
            elif winner_id == b:
                win_col = "fighter_b_wins"
            else:
                # winner isn't in this rivalry — defensive no-op for
                # the win column but still bump fights_count + heat.
                _do_update(
                    "UPDATE rivalries SET rivalry_heat=?, "
                    "fights_count = fights_count + 1, "
                    "last_escalation_date=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE rivalry_id=?",
                    (new_heat, current_date, rivalry_id),
                )
                return
            _do_update(
                f"UPDATE rivalries SET rivalry_heat=?, "
                f"fights_count = fights_count + 1, "
                f"{win_col} = {win_col} + 1, "
                f"last_escalation_date=?, updated_at=CURRENT_TIMESTAMP "
                f"WHERE rivalry_id=?",
                (new_heat, current_date, rivalry_id),
            )
        else:
            # No winner and not a draw — defensive. Just bump heat.
            _do_update(
                "UPDATE rivalries SET rivalry_heat=?, "
                "last_escalation_date=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE rivalry_id=?",
                (new_heat, current_date, rivalry_id),
            )
    else:
        _do_update(
            "UPDATE rivalries SET rivalry_heat=?, "
            "last_escalation_date=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE rivalry_id=?",
            (new_heat, current_date, rivalry_id),
        )


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber — scans social_posts for accumulated
# beefs and escalates / creates rivalries accordingly.
# ----------------------------------------------------------------

def _check_social_beefs(conn, event):
    """Subscriber for TICK_ADVANCED — scans social_posts for beefs.

    On each tick:
      1. For each existing rivalry, count callout/trash_talk posts
         and apology posts between the two rivals since
         last_escalation_date. Apply +5 per callout/trash_talk and
         -10 per apology. Update last_escalation_date.
      2. For pairs of fighters with 3+ callout/trash_talk posts
         between them and NO existing rivalry, create a new 'callout'
         rivalry with initial heat = 50.

    The scan is bidirectional — a callout from A→B counts the same
    as one from B→A (the rivalry is symmetric, even if the beef
    escalation column on social_posts is directional).
    """
    current_date = event.get("current_date")
    if not current_date:
        return

    rng = random.Random()

    # ---- Step 1: escalate existing rivalries based on new posts ----
    # since their last_escalation_date.
    rivalries = conn.execute(
        "SELECT rivalry_id, fighter_a_id, fighter_b_id, "
        "last_escalation_date FROM rivalries WHERE is_active = 1"
    ).fetchall()
    for (rivalry_id, a_id, b_id, last_esc) in rivalries:
        # Count callout/trash_talk posts between the pair since
        # last_escalation_date (or all-time if NULL).
        if last_esc:
            aggressive_posts = conn.execute(
                "SELECT COUNT(*) FROM social_posts "
                "WHERE ((fighter_id=? AND target_fighter_id=?) "
                "   OR (fighter_id=? AND target_fighter_id=?)) "
                "AND post_type IN ('callout','trash_talk') "
                "AND post_date > ?",
                (a_id, b_id, b_id, a_id, last_esc),
            ).fetchone()[0]
            apology_posts = conn.execute(
                "SELECT COUNT(*) FROM social_posts "
                "WHERE ((fighter_id=? AND target_fighter_id=?) "
                "   OR (fighter_id=? AND target_fighter_id=?)) "
                "AND post_type = 'apology' "
                "AND post_date > ?",
                (a_id, b_id, b_id, a_id, last_esc),
            ).fetchone()[0]
        else:
            aggressive_posts = conn.execute(
                "SELECT COUNT(*) FROM social_posts "
                "WHERE ((fighter_id=? AND target_fighter_id=?) "
                "   OR (fighter_id=? AND target_fighter_id=?)) "
                "AND post_type IN ('callout','trash_talk')",
                (a_id, b_id, b_id, a_id),
            ).fetchone()[0]
            apology_posts = conn.execute(
                "SELECT COUNT(*) FROM social_posts "
                "WHERE ((fighter_id=? AND target_fighter_id=?) "
                "   OR (fighter_id=? AND target_fighter_id=?)) "
                "AND post_type = 'apology'",
                (a_id, b_id, b_id, a_id),
            ).fetchone()[0]

        heat_delta = (
            aggressive_posts * _HEAT_CALLOUT_POST
            + apology_posts * _HEAT_APOLOGY_POST
        )
        if heat_delta != 0:
            _escalate_rivalry(
                conn, a_id, b_id, heat_delta,
                current_date=current_date,
            )

    # ---- Step 2: discover new rivalries from accumulated beefs ----
    # Find pairs of fighters with 3+ callout/trash_talk posts between
    # them that don't yet have a rivalry row. Use a GROUP BY across
    # both directions of the (fighter_id, target_fighter_id) pair.
    # Canonical ordering (lower, higher) is computed in Python so
    # the pair count is symmetric.
    #
    # A3 — same-roster restrictions. Callouts across promotions are
    # only allowed if both fighters are in the same weight class AND
    # a 5% random gate passes (the rare inter-promotion superfight
    # callout). Cross-promo pairs that fail this gate are skipped —
    # the beef stays on social_posts (so the heat is recorded) but
    # doesn't graduate into a tracked rivalry.
    candidate_pairs = {}
    posts = conn.execute(
        "SELECT fighter_id, target_fighter_id FROM social_posts "
        "WHERE post_type IN ('callout','trash_talk') "
        "AND target_fighter_id IS NOT NULL "
        "AND fighter_id IS NOT NULL "
        "AND fighter_id != target_fighter_id"
    ).fetchall()
    for fighter_id, target_id in posts:
        a, b = _canonical_pair(fighter_id, target_id)
        if a is None:
            continue
        candidate_pairs.setdefault((a, b), 0)
        candidate_pairs[(a, b)] += 1

    for (a_id, b_id), count in candidate_pairs.items():
        if count < _MIN_BEEF_POSTS_FOR_RIVALRY:
            continue
        # Skip if a rivalry already exists (active or inactive — we
        # don't want to create duplicates that violate the UNIQUE
        # constraint).
        existing = conn.execute(
            "SELECT 1 FROM rivalries "
            "WHERE fighter_a_id=? AND fighter_b_id=?",
            (a_id, b_id),
        ).fetchone()
        if existing:
            continue
        # A3 — cross-promotion gate. Same-promotion pairs always pass.
        # Cross-promotion pairs require same weight class + 5% chance.
        if not _cross_promo_callout_allowed(conn, a_id, b_id, rng=rng):
            continue
        # Create a new 'callout' rivalry. The origin narrative uses
        # word forms (no digit characters per §14).
        if count <= 4:
            count_phrase = "several"
        elif count <= 8:
            count_phrase = "a string of"
        else:
            count_phrase = "a barrage of"
        origin_narrative = (
            f"The rivalry started with {count_phrase} callouts and "
            f"trash-talk posts on social media."
        )
        _create_rivalry(
            conn, a_id, b_id, "callout",
            origin_event="social_media",
            origin_narrative=origin_narrative,
            initial_heat=50,
            rng=rng, current_date=current_date,
        )


def _cross_promo_callout_allowed(conn, a_id, b_id, rng=None):
    """A3 — gate cross-promotion callouts.

    Returns True if:
      - both fighters share the same current_promotion_id, OR
      - the fighters are in different promotions BUT share the same
        weight_class_id AND a 5% random gate passes (the rare
        inter-promotion superfight callout).

    Returns False otherwise. Free agents (current_promotion_id IS
    NULL) are treated as "any promotion" — they can call out anyone
    in any weight class (a free agent has nothing to lose and is
    hunting for any fight). This avoids the corner case where a
    free agent's callouts never spawn a rivalry.
    """
    if rng is None:
        rng = random.Random()
    row = conn.execute(
        "SELECT a.current_promotion_id, a.weight_class_id, "
        "b.current_promotion_id, b.weight_class_id "
        "FROM fighters a, fighters b "
        "WHERE a.fighter_id=? AND b.fighter_id=?",
        (a_id, b_id),
    ).fetchone()
    if not row:
        return False
    promo_a, wc_a, promo_b, wc_b = row
    # Free agents (no promotion) bypass the gate.
    if promo_a is None or promo_b is None:
        return True
    # Same promotion — always allowed.
    if promo_a == promo_b:
        return True
    # Cross-promotion — same weight class + 5% chance.
    if wc_a is None or wc_b is None or wc_a != wc_b:
        return False
    return rng.random() < _CROSS_PROMO_CALLOUT_CHANCE


def _is_weekly_tick(conn):
    """Return True if the current sim day is a multiple of 7 (weekly tick).

    Mirrors morale._is_weekly_tick — the sim runs daily, so we treat
    days 7, 14, 21, ... as the weekly tick for heat decay.
    """
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not row or row[0] is None:
        return False
    return (row[0] % 7) == 0


def _decay_rivalry_heat(conn, event):
    """A2 — weekly TICK_ADVANCED subscriber that decays rivalry heat.

    Runs only on weekly ticks (current_day % 7 == 0). For each active
    rivalry:
      - Apply -1 heat (the natural cooling of a feud that isn't being
        fueled by fresh callouts, fights, or news).
      - If heat drops below _HEAT_DORMANCY_THRESHOLD (20), set
        is_active=0 (dormant). The rivalry row is preserved — its
        history (fights_count, head-to-head wins, origin story)
        remains queryable, but it no longer qualifies as "active"
        for fight-engine modifiers (A8) or news targeting.

    A dormant rivalry can be re-activated by a fresh callout/trash_talk
    post: the _check_social_beefs subscriber will count new posts and
    apply +5 heat per post, but does NOT re-activate the is_active
    flag. Re-activation happens here — if a post lifts the heat back
    above the threshold on a subsequent weekly tick, the rivalry
    becomes active again. (A fight between rivals in _process_fight_
    rivalry also bumps heat but doesn't re-activate; this subscriber
    picks that up on the next weekly tick.)

    This subscriber fires BEFORE _check_social_beefs in registration
    order so the decay is applied first, then any fresh-callout heat
    is layered on top — net effect: a rivalry that's actively being
    fueled stays hot; one that's gone quiet cools off.
    """
    if not _is_weekly_tick(conn):
        return

    current_date = event.get("current_date")
    rows = conn.execute(
        "SELECT rivalry_id, rivalry_heat FROM rivalries "
        "WHERE is_active = 1"
    ).fetchall()
    for rivalry_id, current_heat in rows:
        current_heat = current_heat if current_heat is not None else 0
        new_heat = _clamp_heat(current_heat + _HEAT_WEEKLY_DECAY)
        if new_heat < _HEAT_DORMANCY_THRESHOLD:
            # Cool below the dormancy line — set inactive. The row
            # is preserved (we don't DELETE — the history matters
            # for legacy/news lookups).
            conn.execute(
                "UPDATE rivalries SET rivalry_heat=?, is_active=0, "
                "updated_at=CURRENT_TIMESTAMP WHERE rivalry_id=?",
                (new_heat, rivalry_id),
            )
        elif new_heat != current_heat:
            conn.execute(
                "UPDATE rivalries SET rivalry_heat=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE rivalry_id=?",
                (new_heat, rivalry_id),
            )


# ----------------------------------------------------------------
# FIGHT_RESOLVED subscriber — updates rivalry record after a fight
# between rivals, or creates a new rivalry if the fight was
# rivalry-worthy (close decision, weight cut miss).
# ----------------------------------------------------------------

def _process_fight_rivalry(conn, event):
    """Subscriber for FIGHT_RESOLVED — updates or creates rivalries.

    For a resolved fight:
      1. If a rivalry exists between the two fighters:
         - Increment fights_count, fighter_a/b_wins, or draws.
         - Apply +15 heat (or +25 if it was a title fight).
      2. Check weight_cut_log for the fight — if either fighter
         missed weight, apply +10 heat to the rivalry (or create a
         'bad_blood' rivalry if none exists).
      3. If no rivalry exists but the fight was a close/controversial
         decision (score_margin small), create a 'rematch_hungry'
         rivalry.

    The fight engine (resolve_next_fight in app.py) is NOT modified
    — this subscriber reads the fight_history + weight_cut_log rows
    that resolve_next_fight already writes.
    """
    rng = random.Random()
    fight_id = event.get("fight_id")
    winner_id = event.get("winner_id")
    loser_id = event.get("loser_id")
    result_type = event.get("result_type", "") or ""
    is_title = event.get("is_title_fight", False)
    event_date = event.get("event_date")
    a_id = event.get("fighter_a_id")
    b_id = event.get("fighter_b_id")

    # For draws, winner_id and loser_id are None — fall back to
    # fighter_a_id / fighter_b_id from the event.
    if winner_id is None or loser_id is None:
        if a_id is None or b_id is None:
            return  # nothing to work with
        is_draw = (result_type == "draw")
    else:
        is_draw = False

    # Canonicalize the pair for rivalry lookups.
    pair_a, pair_b = _canonical_pair(a_id, b_id)
    if pair_a is None:
        return

    existing = get_rivalry(conn, pair_a, pair_b)

    # ---- Step 1: update existing rivalry with fight result ----
    if existing is not None:
        heat_delta = (
            _HEAT_TITLE_FIGHT_BETWEEN_RIVALS if is_title
            else _HEAT_FIGHT_BETWEEN_RIVALS
        )
        _escalate_rivalry(
            conn, pair_a, pair_b, heat_delta,
            current_date=event_date,
            increment_fights=True,
            winner_id=winner_id,
            is_draw=is_draw,
        )

    # ---- Step 2: weight cut miss → +10 heat (existing) or bad_blood ----
    # Check the weight_cut_log for this fight. If either fighter
    # missed weight (cut_outcome IN ('missed_small','missed_medium',
    # 'missed_large','cancelled')), apply the heat delta or create a
    # bad_blood rivalry.
    if fight_id is not None:
        wc_misses = conn.execute(
            "SELECT fighter_id, cut_outcome FROM weight_cut_log "
            "WHERE fight_id=? "
            "AND cut_outcome IN ('missed_small','missed_medium',"
            "                    'missed_large','cancelled')",
            (fight_id,),
        ).fetchall()
        if wc_misses:
            if existing is not None:
                _escalate_rivalry(
                    conn, pair_a, pair_b, _HEAT_WEIGHT_CUT_MISS,
                    current_date=event_date,
                )
            else:
                # Create a new bad_blood rivalry from the weight cut
                # miss. The narrative names the offender by last
                # name (no digit characters per §14).
                offender_id = wc_misses[0][0]
                offender_last = conn.execute(
                    "SELECT last_name FROM fighters WHERE fighter_id=?",
                    (offender_id,),
                ).fetchone()
                offender_last = (
                    offender_last[0] if offender_last else "One fighter"
                )
                origin_narrative = (
                    f"The rivalry started when {offender_last} missed "
                    f"weight before their fight — bad blood from the "
                    f"scale."
                )
                _create_rivalry(
                    conn, pair_a, pair_b, "bad_blood",
                    origin_event=f"fight:{fight_id}:weight_cut_miss",
                    origin_narrative=origin_narrative,
                    initial_heat=55,
                    rng=rng, current_date=event_date,
                )
                # Apply the fight-result escalation too (the fight
                # happened between new rivals).
                _escalate_rivalry(
                    conn, pair_a, pair_b,
                    _HEAT_FIGHT_BETWEEN_RIVALS,
                    current_date=event_date,
                    increment_fights=True,
                    winner_id=winner_id,
                    is_draw=is_draw,
                )
                existing = get_rivalry(conn, pair_a, pair_b)

    # ---- Step 3: close decision → rematch_hungry (new rivalry) ----
    # Only create if no rivalry exists yet AND the result was a
    # close decision (score_margin <= _CLOSE_DECISION_MARGIN).
    if existing is None and not is_draw and result_type == "decision":
        if fight_id is not None:
            # Pull score_margin from fight_history (the row for the
            # winner — they have the positive margin; the loser's
            # row has the negative margin, so we take ABS).
            margin_row = conn.execute(
                "SELECT score_margin FROM fight_history "
                "WHERE fight_id=? AND outcome='win' LIMIT 1",
                (fight_id,),
            ).fetchone()
            if margin_row and margin_row[0] is not None:
                margin = abs(margin_row[0])
                if margin <= _CLOSE_DECISION_MARGIN:
                    origin_narrative = (
                        "The rivalry started with a narrow decision "
                        "that demanded a rematch — the judges split "
                        "by the slimmest of margins."
                    )
                    _create_rivalry(
                        conn, pair_a, pair_b, "rematch_hungry",
                        origin_event=f"fight:{fight_id}:close_decision",
                        origin_narrative=origin_narrative,
                        initial_heat=55,
                        rng=rng, current_date=event_date,
                    )
                    _escalate_rivalry(
                        conn, pair_a, pair_b,
                        _HEAT_FIGHT_BETWEEN_RIVALS,
                        current_date=event_date,
                        increment_fights=True,
                        winner_id=winner_id,
                        is_draw=False,
                    )


# ----------------------------------------------------------------
# TITLE_CHANGED subscriber — creates a title_rivalry between the
# new champion and the former champion (if dethroned, not vacant-
# claim).
# ----------------------------------------------------------------

def _process_title_rivalry(conn, event):
    """Subscriber for TITLE_CHANGED — creates a title_rivalry.

    When a title changes hands (reigns_count > 1, meaning a champion
    was dethroned rather than a vacant title being claimed), creates
    or escalates a 'title_rivalry' between the new champion and the
    former champion. The rivalry is the narrative spine of the
    division — "the champion who lost his belt wants it back" is one
    of the strongest story engines in MMA.
    """
    rng = random.Random()
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")
    event_date = event.get("event_date") or _today_from_clock(conn)

    if not title_id or not fight_id:
        return

    title_row = conn.execute(
        "SELECT current_champion_fighter_id, champion_since_date, "
        "title_reigns_count, is_vacant FROM titles WHERE title_id=?",
        (title_id,),
    ).fetchone()
    if not title_row:
        return
    champ_id, since_date, reigns_count, _is_vacant_now = title_row
    if not champ_id:
        return  # title is currently vacant — no rivalry to build

    fight_row = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type "
        "FROM fights WHERE fight_id=?",
        (fight_id,),
    ).fetchone()
    if not fight_row:
        return
    winner_id, loser_id, _rt = fight_row
    if winner_id != champ_id:
        # Defensive: title says champ is X, fight says winner is Y.
        winner_id = champ_id
    if loser_id is None:
        return  # vacant-claim or draw — no former champion

    # Vacant claim vs dethroning: reigns_count == 1 means this is
    # the title's first reign (was vacant, now claimed). We only
    # build a title_rivalry when a champion was DETHRONED.
    is_vacant_claim = (reigns_count is None or reigns_count == 1)
    if is_vacant_claim:
        return

    # We have a dethroning — winner_id is the new champ, loser_id is
    # the former champ. Create or escalate the title_rivalry.
    existing = get_rivalry(conn, winner_id, loser_id)
    if existing is not None:
        # Escalate — this is another chapter in an existing rivalry.
        _escalate_rivalry(
            conn, winner_id, loser_id,
            _HEAT_TITLE_FIGHT_BETWEEN_RIVALS,
            current_date=since_date or event_date,
            increment_fights=True,
            winner_id=winner_id,
            is_draw=False,
        )
        # If the existing rivalry wasn't already typed as
        # title_rivalry, upgrade it (title change is the strongest
        # signal that this is a title_rivalry now).
        try:
            existing_type = existing["rivalry_type"]
        except (KeyError, IndexError, TypeError):
            existing_type = existing[3] if len(existing) > 3 else None
        if existing_type != "title_rivalry":
            pair = _canonical_pair(winner_id, loser_id)
            conn.execute(
                "UPDATE rivalries SET rivalry_type='title_rivalry', "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE fighter_a_id=? AND fighter_b_id=?",
                pair,
            )
        return

    # No existing rivalry — create a fresh title_rivalry.
    origin_narrative = (
        "The rivalry started when the title changed hands between "
        "them — the former champion wants the belt back."
    )
    _create_rivalry(
        conn, winner_id, loser_id, "title_rivalry",
        origin_event=f"title_change:{title_id}",
        origin_narrative=origin_narrative,
        initial_heat=70,
        rng=rng, current_date=since_date or event_date,
    )
    # Record the head-to-head fight result on the new rivalry.
    _escalate_rivalry(
        conn, winner_id, loser_id,
        _HEAT_FIGHT_BETWEEN_RIVALS,
        current_date=since_date or event_date,
        increment_fights=True,
        winner_id=winner_id,
        is_draw=False,
    )


def _today_from_clock(conn):
    """Return today's date from the simulation_clock, or a fallback."""
    row = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock "
        "WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else "2026-08-15"


# ----------------------------------------------------------------
# REGISTRATION
# ----------------------------------------------------------------

def register_subscribers():
    """Register all rivalries subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior
    registrations.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    # A2 — register the heat decay subscriber FIRST so it runs before
    # _check_social_beefs on every weekly tick. This lets decay apply
    # first, then any fresh-callout heat from the beef scan layers on
    # top. Net effect: a rivalry being fueled stays hot; one that's
    # gone quiet cools off and may go dormant.
    bus.subscribe(
        Events.TICK_ADVANCED, _decay_rivalry_heat,
        name="rivalries.decay_rivalry_heat",
    )
    bus.subscribe(
        Events.TICK_ADVANCED, _check_social_beefs,
        name="rivalries.check_social_beefs",
    )
    bus.subscribe(
        Events.FIGHT_RESOLVED, _process_fight_rivalry,
        name="rivalries.process_fight_rivalry",
    )
    bus.subscribe(
        Events.TITLE_CHANGED, _process_title_rivalry,
        name="rivalries.process_title_rivalry",
    )
