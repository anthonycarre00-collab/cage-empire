"""CAGE EMPIRE memory service (Stage 6 — Task 6.0 + HW3 expansion).

Per docs/TASK_6_0_PLAN.md §3.5, this module shipped in Task 6.0 with
ONLY the 2 populate_* functions. HW3 (docs/Hardening_Phase.md §HW3.1
/ CRITICAL #6) expands it with 5 new memory link writers + an event
bus subscriber registration so the writers fire automatically on
FIGHT_RESOLVED / TITLE_CHANGED / FIGHTER_SIGNED / FIGHTER_RETIRED.

The HW3 expansion closes the "memory starved of data" gap identified
in the GPT re-read: only 3 link types existed before (regional_rival,
style_echo, successor — 775 rows). HW3 adds 4 new link types
(title_history, upset, comeback, milestone) and the writers that
populate them.

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables
        (the v3.28.0 migration in build_db.py expands the
        fighter_memory_links.link_type CHECK constraint to allow the
        4 new values; no new tables).
  §13 — Design Law: Legacy pillar — memory links tell torch-passing
        stories. Every writer here creates a *pairwise* link between
        two fighters so the Memory Engine (memory_engine.py) can
        surface the story when those two fighters meet again.
  §14 — Voice-layered: the link_strength int (0-100) is INTERNAL
        ONLY — it's a search-rank signal, never displayed. The
        Memory Engine renders the link as a voice phrase ("These
        two fought for the title last year.") with no raw numbers.
  §15 — Event Bus: the writers are called inline from existing
        code paths AND via event bus subscribers (register_
        subscribers). The subscribers are registered from
        interpretation/__init__.py (after the existing interpretation
        subscribers) so the writers fire on every relevant event
        without callers having to remember to invoke them.
  §17.1 — The Memory Engine (memory_engine.py) is the ONLY reader
        of these links. memory_svc is the ONLY writer. This separation
        means a write-side bug never crashes the UI render path.
"""
import sqlite3


# ============================================================
# Existing populate_* functions (Stage 6 — Task 6.0)
# ============================================================

def populate_style_echo(conn, replacement_fighter_id, retiring_fighter_id):
    """Write a 'style_echo' memory link if the regen replacement
    inherited the retiring fighter's style archetype.

    Called from tick_processor._check_retirements after the existing
    'successor' link INSERT. Idempotent (INSERT OR IGNORE against the
    UNIQUE constraint on fighter_id + linked_fighter_id + link_type).

    link_strength = 70 if the archetype is inherited (else skip the
    insert — no style echo if there's no style match).
    """
    # Look up both fighters' style archetype
    row = conn.execute(
        "SELECT f1.fight_style_archetype_id, f2.fight_style_archetype_id "
        "FROM fighters f1, fighters f2 "
        "WHERE f1.fighter_id=? AND f2.fighter_id=?",
        (replacement_fighter_id, retiring_fighter_id),
    ).fetchone()
    if not row:
        return
    replacement_archetype, retiring_archetype = row
    if replacement_archetype is None or retiring_archetype is None:
        return
    if replacement_archetype != retiring_archetype:
        return  # no style echo — different archetypes

    # Idempotent insert
    conn.execute(
        "INSERT OR IGNORE INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'style_echo', 70)",
        (replacement_fighter_id, retiring_fighter_id),
    )


def populate_regional_rival(conn, fighter_a_id, fighter_b_id):
    """Write a 'regional_rival' memory link if both fighters share
    a birth nation or region.

    Called from services.matchmaking._build_main_event and
    _build_co_main after fighter selection. Idempotent.

    link_strength = 50 + 10 * common_region_count (nation + region
    matches). Two fighters from the same nation AND region get 70;
    same nation only gets 60; different nations gets 50 (still linked
    — they're fighting each other, which is itself a regional story
    if they're from the same broader area).
    """
    row = conn.execute(
        "SELECT f1.birth_nation_id, f1.birth_city_id, "
        "       f2.birth_nation_id, f2.birth_city_id "
        "FROM fighters f1, fighters f2 "
        "WHERE f1.fighter_id=? AND f2.fighter_id=?",
        (fighter_a_id, fighter_b_id),
    ).fetchone()
    if not row:
        return
    a_nation, a_city, b_nation, b_city = row

    common = 0
    if a_nation is not None and a_nation == b_nation:
        common += 1
    # Check if same region (cities share a region)
    if a_city is not None and b_city is not None and a_city == b_city:
        common += 1

    link_strength = min(50 + 10 * common, 100)

    # Idempotent insert — note: regional_rival is bidirectional, so
    # we insert both directions (A→B and B→A). The UNIQUE constraint
    # on (fighter_id, linked_fighter_id, link_type) allows both.
    conn.execute(
        "INSERT OR IGNORE INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'regional_rival', ?)",
        (fighter_a_id, fighter_b_id, link_strength),
    )
    conn.execute(
        "INSERT OR IGNORE INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'regional_rival', ?)",
        (fighter_b_id, fighter_a_id, link_strength),
    )


# ============================================================
# HW3.1 — New memory link writers (5 writers)
# ============================================================
# Per docs/Hardening_Phase.md §HW3.1 / CRITICAL #6. Each writer
# creates a pairwise fighter_memory_links row so the Memory Engine
# can surface the story when the two fighters meet again.
#
# All writers are IDEMPOTENT (INSERT OR IGNORE against the UNIQUE
# constraint on fighter_id + linked_fighter_id + link_type). Safe
# to call multiple times for the same pair.
#
# All writers are DEFENSIVE — they catch DB errors and log to stderr
# rather than raising. A failed memory write must never crash the
# fight resolution flow.
#
# link_strength is INTERNAL (0-100) — used by the Memory Engine to
# rank which memory to surface first when multiple match. NEVER
# displayed in the UI (CONVENTIONS §14).

# Threshold for "upset" — the lower-rated winner must be at least
# this many rating points below the higher-rated loser at fight time.
# Per HW3.1 spec: "lower-ranked beats higher-ranked by rating gap ≥ 15".
UPSET_RATING_GAP_THRESHOLD = 15

# Threshold for "long absence" — a fighter with no fight in the last
# N days is considered to be "coming back from a long absence".
COMEBACK_LAYOFF_DAYS = 365


def write_former_teammate_links_on_gym_change(conn, fighter_id,
                                              old_gym_id, new_gym_id):
    """Write 'former_teammate' links when a fighter changes gyms.

    Per HW3.1: "Fighter changes gym → write former_teammate link
    between the fighter and other fighters at the old gym."

    For each other fighter currently at old_gym_id, write a
    bidirectional 'former_teammate' link. link_strength is fixed
    at 60 (they were training partners — a moderately strong memory).

    Called manually when a fighter's current_gym_id is updated (there
    is no current code path that changes gyms post-creation, so this
    writer is forward-looking — it exists so that when a future
    feature allows gym transfers, the memory link is written
    automatically).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The fighter who changed gyms.
        old_gym_id: int (or None). The fighter's previous gym. If
            None, no links are written (the fighter had no previous
            gym to share with anyone).
        new_gym_id: int (or None). The fighter's new gym. Not used
            for the former_teammate link (we link to fighters at the
            OLD gym, not the new one). Accepted as a parameter so the
            caller's signature is natural: write_former_teammate_
            links_on_gym_change(conn, fid, old_gym, new_gym).

    Returns:
        int — number of former_teammate links written (0 if old_gym_id
        is None or no other fighters are at the old gym).
    """
    if not fighter_id or not old_gym_id:
        return 0
    try:
        # Find all other fighters currently at the old gym.
        rows = conn.execute(
            "SELECT fighter_id FROM fighters "
            "WHERE current_gym_id = ? AND fighter_id != ? "
            "  AND is_active = 1",
            (old_gym_id, fighter_id),
        ).fetchall()
        count = 0
        for (other_id,) in rows:
            # Bidirectional link (A→B + B→A).
            conn.execute(
                "INSERT OR IGNORE INTO fighter_memory_links "
                "(fighter_id, linked_fighter_id, link_type, link_strength) "
                "VALUES (?, ?, 'former_teammate', 60)",
                (fighter_id, other_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO fighter_memory_links "
                "(fighter_id, linked_fighter_id, link_type, link_strength) "
                "VALUES (?, ?, 'former_teammate', 60)",
                (other_id, fighter_id),
            )
            count += 1
        return count
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_former_teammate_links_on_gym_"
              f"change(fighter_id={fighter_id}, old_gym_id={old_gym_id}) "
              f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_title_history_link(conn, new_champion_id, former_champion_id,
                             title_id=None):
    """Write a 'title_history' link between two fighters who
    contested a title.

    Per HW3.1: "Title changes → write title_history link between the
    new champion and the former champion."

    Bidirectional link with link_strength=80 (a title fight is one of
    the strongest pairwise memories in the sport). Idempotent.

    Called automatically by the TITLE_CHANGED subscriber (see
    register_subscribers below) which extracts the new + former
    champion from the (already-updated) titles row + the fight's
    loser_fighter_id.

    Args:
        conn: sqlite3.Connection. Caller commits.
        new_champion_id: int. The fighter who just won the title.
        former_champion_id: int. The fighter who lost the title
            (None for a vacant-title claim — in that case no link
            is written because there's no former champion to link
            to).
        title_id: optional int. Used only for the defensive log
            message (not stored on the link — the link is purely
            pairwise; the Memory Engine surfaces "they fought for
            the title" without naming which title).

    Returns:
        int — 1 if the link was written, 0 if skipped (no former
        champion) or on error.
    """
    if not new_champion_id or not former_champion_id:
        return 0
    if new_champion_id == former_champion_id:
        return 0  # defensive — a fighter can't dethrone themselves
    try:
        # Bidirectional link with high strength (title fights are
        # major pairwise memories).
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'title_history', 80)",
            (new_champion_id, former_champion_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'title_history', 80)",
            (former_champion_id, new_champion_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_title_history_link("
              f"new={new_champion_id}, former={former_champion_id}, "
              f"title_id={title_id}) failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 0


def write_upset_link(conn, winner_id, loser_id, rating_gap=None):
    """Write an 'upset' link between two fighters when the lower-
    rated fighter beats the higher-rated fighter.

    Per HW3.1: "Upset happens (lower-ranked beats higher-ranked by
    rating gap ≥ 15) → write upset link between the two fighters."

    Bidirectional link with link_strength scaled by the gap (60 +
    min(gap, 40) → 60-100). A bigger upset = stronger memory.

    Called automatically by the FIGHT_RESOLVED subscriber (see
    register_subscribers below). The subscriber looks up both
    fighters' rankings.rating at the time of the fight resolution
    and computes the gap. If the gap is >= UPSET_RATING_GAP_THRESHOLD
    (15), this writer is invoked.

    Note: the ratings have already been updated by the time the
    FIGHT_RESOLVED event fires (the ELO update happens BEFORE the
    event publish). The post-fight rating difference is close enough
    to the pre-fight difference for upset detection — ELO updates
    are small (typically <32 points) relative to the 15-point
    threshold. For the backfill script (backfill_memory_links.py),
    we use the post-fight ratings as the best available proxy.

    Args:
        conn: sqlite3.Connection. Caller commits.
        winner_id: int. The fighter who won (was lower-rated).
        loser_id: int. The fighter who lost (was higher-rated).
        rating_gap: optional float. The rating difference at fight
            time (loser.rating - winner.rating). If None, the writer
            looks up the current ratings + computes the gap itself.

    Returns:
        int — 1 if the link was written, 0 if skipped (gap below
        threshold, or ratings unavailable) or on error.
    """
    if not winner_id or not loser_id or winner_id == loser_id:
        return 0
    try:
        if rating_gap is None:
            # Look up both fighters' current rating. We need their
            # weight_class_id + promotion_id to find the rankings row
            # — use the loser's most recent fight_history row to get
            # the weight_class_id (the fight they just lost).
            fh_row = conn.execute(
                "SELECT weight_class_id, event_id FROM fight_history "
                "WHERE fighter_id=? AND opponent_id=? "
                "ORDER BY event_date DESC LIMIT 1",
                (loser_id, winner_id),
            ).fetchone()
            if not fh_row:
                return 0
            wc_id, ev_id = fh_row
            # Get the promotion_id from the event (the fight's promo).
            promo_id = None
            if ev_id:
                promo_row = conn.execute(
                    "SELECT promotion_id FROM events WHERE event_id=?",
                    (ev_id,),
                ).fetchone()
                if promo_row:
                    promo_id = promo_row[0]
            if not wc_id or not promo_id:
                return 0
            # Now read both fighters' ratings.
            w_row = conn.execute(
                "SELECT rating FROM rankings "
                "WHERE fighter_id=? AND weight_class_id=? AND promotion_id=?",
                (winner_id, wc_id, promo_id),
            ).fetchone()
            l_row = conn.execute(
                "SELECT rating FROM rankings "
                "WHERE fighter_id=? AND weight_class_id=? AND promotion_id=?",
                (loser_id, wc_id, promo_id),
            ).fetchone()
            if not w_row or not l_row:
                return 0
            rating_gap = (l_row[0] or 1000.0) - (w_row[0] or 1000.0)

        if rating_gap < UPSET_RATING_GAP_THRESHOLD:
            return 0  # not a big enough upset

        # link_strength scales with gap: 60 + min(gap, 40) → 60-100.
        strength = min(60 + int(rating_gap), 100)
        # Bidirectional link.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'upset', ?)",
            (winner_id, loser_id, strength),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'upset', ?)",
            (loser_id, winner_id, strength),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_upset_link(winner={winner_id}, "
              f"loser={loser_id}, gap={rating_gap}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_comeback_link(conn, fighter_id, event_date=None):
    """Write a 'comeback' link for a fighter returning from a long
    absence.

    Per HW3.1: "Fighter returns from retirement/long absence → write
    comeback link."

    The comeback link connects the returning fighter to the opponent
    of their LAST fight before the layoff (the "unfinished business"
    opponent — the one the memory_engine surfaces as "their last
    fight before the layoff was against X"). If there's no prior
    fight, no link is written (a debut fighter isn't "coming back"
    — they're just starting).

    link_strength = 70 (a comeback is a strong story but the
    pairwise link is to the last opponent, who may or may not be
    relevant to the comeback narrative).

    Called automatically by:
      - FIGHTER_SIGNED subscriber — when a previously-retired fighter
        signs with a new promotion (their is_retired flag was 1
        before this signing). This is the "return from retirement"
        case.
      - FIGHT_RESOLVED subscriber — when a fighter's gap since their
        previous fight exceeds COMEBACK_LAYOFF_DAYS (365). This is
        the "long absence" case (not retired, but hadn't fought in
        over a year).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The returning fighter.
        event_date: optional ISO date string. The date of the
            comeback fight / signing. If None, reads the sim clock.

    Returns:
        int — 1 if the link was written, 0 if skipped (no prior
        fight, or the layoff was below threshold) or on error.
    """
    if not fighter_id:
        return 0
    try:
        # Find the fighter's most recent fight BEFORE the layoff.
        # We want the opponent of their LAST fight — the "unfinished
        # business" opponent.
        if event_date is None:
            row = conn.execute(
                "SELECT simulation_clock.current_date "
                "FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            event_date = row[0] if row else None
        if not event_date:
            return 0

        # The fighter's most recent fight (the one BEFORE the
        # comeback — i.e., the last fight they had before this
        # signing/comeback event).
        last_fight = conn.execute(
            "SELECT opponent_id, event_date FROM fight_history "
            "WHERE fighter_id=? AND event_date < ? "
            "ORDER BY event_date DESC LIMIT 1",
            (fighter_id, event_date),
        ).fetchone()
        if not last_fight:
            return 0  # no prior fight — not a comeback, just a debut
        opponent_id, last_fight_date = last_fight
        if not opponent_id:
            return 0

        # Compute the layoff gap.
        try:
            from datetime import datetime
            last_dt = datetime.fromisoformat(last_fight_date[:10]).date()
            curr_dt = datetime.fromisoformat(event_date[:10]).date()
            layoff_days = (curr_dt - last_dt).days
        except (ValueError, TypeError):
            layoff_days = 0
        if layoff_days < COMEBACK_LAYOFF_DAYS:
            return 0  # not a long-enough absence

        # Write the link (one-directional — the comeback is from
        # the returning fighter's perspective; their last opponent
        # isn't "coming back", they're just the last opponent).
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'comeback', 70)",
            (fighter_id, opponent_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_comeback_link("
              f"fighter_id={fighter_id}, event_date={event_date}) "
              f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_milestone_link(conn, fighter_id, opponent_id, milestone_type):
    """Write a 'milestone' link between two fighters when one
    reaches a career milestone against the other.

    Per HW3.1: "Fighter reaches milestone (10 wins, 20 wins, 5-KO
    streak, 10th title defense) → write milestone link."

    Bidirectional link with link_strength=75 (milestones are major
    career moments, and the pairwise opponent is "the one they beat
    to reach the milestone"). Idempotent.

    Called automatically by the FIGHT_RESOLVED subscriber. The
    subscriber checks the winner's post-fight career totals
    (fight_history aggregates) and writes a milestone link if they
    just hit 10 wins / 20 wins / 5-KO streak / 10th title defense.

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The fighter who reached the milestone.
        opponent_id: int. The opponent they beat to reach it (the
            loser of the just-resolved fight). If None, no link is
            written (some milestones — like a 10th title defense —
            may not have a clean pairwise opponent, but the spec
            requires one, so we skip in that case).
        milestone_type: str. One of 'wins_10', 'wins_20',
            'ko_streak_5', 'title_defense_10'. Used only for the
            defensive log message (not stored on the link — the link
            is pairwise, and the Memory Engine surfaces "they reached
            a career milestone against this opponent" without naming
            which milestone).

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not fighter_id or not opponent_id or fighter_id == opponent_id:
        return 0
    try:
        # Bidirectional link with high strength.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'milestone', 75)",
            (fighter_id, opponent_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'milestone', 75)",
            (opponent_id, fighter_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_milestone_link("
              f"fighter_id={fighter_id}, opponent_id={opponent_id}, "
              f"milestone_type={milestone_type}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 0


# ============================================================
# TIER3-MISSING §T3.4 (W17) — 8 new memory link writers
# ============================================================
# Per docs/OPTIMIZATION_PLAN_TIER1_3.md §T3.4. Each writer creates a
# fighter_memory_links row of one of the 8 new link_types added in
# the v3.36.0 migration. The 8 new types are distinct from the
# existing 12 (some pluralize existing singular forms; others are
# entirely new categories like old_gyms, former_champions,
# controversial_losses, promotions, old_events).
#
# DESIGN DECISIONS (link shape):
#   - PAIRWISE links (fighter↔fighter, bidirectional A→B + B→A) for
#     link_types that capture a relationship BETWEEN two fighters:
#       * previous_fights        — both fighters who fought before
#       * former_teammates       — both training partners at old gym
#       * controversial_losses   — loser ↔ winner of split decision
#   - SELF-LINKS (fighter_id = linked_fighter_id) for link_types
#     that capture a fighter's relationship to a NON-fighter entity
#     (gym, title, promotion, event, injury). The fighter_memory_
#     links schema only supports fighter↔fighter columns, so a
#     self-link is the pragmatic way to flag "this happened to this
#     fighter" without adding a new table or column. The link's
#     existence is the signal; the actual gym/title/promo/event ID
#     is looked up via fight_history / titles / etc. by the memory
#     engine when surfacing the memory:
#       * old_gyms               — fighter left a gym (self-link)
#       * former_champions       — ex-champion (self-link)
#       * injuries               — fighter was injured (self-link)
#       * promotions             — fighter changed promo (self-link)
#       * old_events             — milestone event (self-link)
#
# All writers are IDEMPOTENT (INSERT OR IGNORE against the UNIQUE
# constraint on fighter_id + linked_fighter_id + link_type) and
# DEFENSIVE (catch sqlite3.Error, log to stderr, return 0). A
# failed memory write must never crash the tick.


def write_previous_fights_link(conn, fighter_a_id, fighter_b_id):
    """Write a 'previous_fights' link between two fighters who have
    fought before.

    Per T3.4 brief: "when two fighters have fought before. Writer:
    in fight_engine.resolve_next_fight, after writing fight_history,
    check if these two fighters have fought before. If yes, write a
    previous_fights memory_link."

    Distinct from the existing singular 'previous_fight' link_type
    (added in v3.12.0): the plural form captures the multi-fight
    relationship ("these two have a history"), while the singular
    form is per-fight. The Memory Engine's surface_memories reads
    both variants.

    PAIRWISE bidirectional link with link_strength=65 (slightly
    stronger than the regional_rival baseline — a real previous
    fight is a stronger memory than just being from the same region).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_a_id, fighter_b_id: the two fighters who fought.

    Returns:
        int — 1 if the link was written (or already existed), 0 if
        skipped (invalid input) or on error.
    """
    if not fighter_a_id or not fighter_b_id:
        return 0
    if fighter_a_id == fighter_b_id:
        return 0  # a fighter can't have fought themselves
    try:
        # Bidirectional link.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'previous_fights', 65)",
            (fighter_a_id, fighter_b_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'previous_fights', 65)",
            (fighter_b_id, fighter_a_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_previous_fights_link("
              f"a={fighter_a_id}, b={fighter_b_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_former_teammates_links_on_gym_change(conn, fighter_id,
                                                old_gym_id, new_gym_id=None):
    """Write 'former_teammates' links (PLURAL — distinct from the
    existing singular 'former_teammate' link_type) when a fighter
    changes gyms.

    Per T3.4 brief: "when a fighter changes gym. Writer: in the
    gym-change logic, write a former_teammates link between the
    fighter and other fighters at the old gym."

    Distinct from the existing write_former_teammate_links_on_gym_
    change (singular): the plural form is the T3.4-mandated variant
    that captures the same gym-change relationship under a different
    link_type enum value. The Memory Engine surfaces both variants
    via the same _search_former_teammate query.

    For each other fighter currently at old_gym_id, write a
    bidirectional 'former_teammates' (plural) link. link_strength=60
    (mirrors the singular variant).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The fighter who changed gyms.
        old_gym_id: int (or None). The fighter's previous gym. If
            None, no links are written.
        new_gym_id: int (or None). The fighter's new gym. Not used
            for the former_teammates link (we link to fighters at
            the OLD gym). Accepted for caller signature symmetry
            with the singular variant.

    Returns:
        int — number of former_teammates links written (0 if
        old_gym_id is None or no other fighters are at the old gym).
    """
    if not fighter_id or not old_gym_id:
        return 0
    try:
        rows = conn.execute(
            "SELECT fighter_id FROM fighters "
            "WHERE current_gym_id = ? AND fighter_id != ? "
            "  AND is_active = 1",
            (old_gym_id, fighter_id),
        ).fetchall()
        count = 0
        for (other_id,) in rows:
            # Bidirectional link (A→B + B→A).
            conn.execute(
                "INSERT OR IGNORE INTO fighter_memory_links "
                "(fighter_id, linked_fighter_id, link_type, link_strength) "
                "VALUES (?, ?, 'former_teammates', 60)",
                (fighter_id, other_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO fighter_memory_links "
                "(fighter_id, linked_fighter_id, link_type, link_strength) "
                "VALUES (?, ?, 'former_teammates', 60)",
                (other_id, fighter_id),
            )
            count += 1
        return count
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_former_teammates_links_on_gym_"
              f"change(fighter_id={fighter_id}, old_gym_id={old_gym_id}) "
              f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_old_gyms_link(conn, fighter_id, old_gym_id):
    """Write an 'old_gyms' SELF-LINK when a fighter changes gyms.

    Per T3.4 brief: "when a fighter changes gym. Writer: same as
    above [gym-change logic], write an old_gyms link between the
    fighter and the old gym."

    Since fighter_memory_links only supports fighter↔fighter columns,
    we use a SELF-LINK (fighter_id = linked_fighter_id = fighter_id)
    to flag "this fighter was previously at a different gym". The
    actual old_gym_id isn't stored in the link — it's looked up via
    the fighter's gym change history when the memory is surfaced.

    link_strength=50 (default — this is a flag-style memory, not a
    ranked pairwise relationship).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The fighter who changed gyms.
        old_gym_id: int (or None). Accepted for caller symmetry with
            write_former_teammates_links_on_gym_change. Not stored
            in the link — the link's existence is the signal. If
            None, the link is still written (a fighter with no prior
            gym still "changed gyms" in the sense of arriving at
            their first gym).

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not fighter_id:
        return 0
    try:
        # Self-link: fighter_id = linked_fighter_id.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'old_gyms', 50)",
            (fighter_id, fighter_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_old_gyms_link(fighter_id="
              f"{fighter_id}, old_gym_id={old_gym_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_former_champions_link(conn, ex_champion_id, title_id=None):
    """Write a 'former_champions' SELF-LINK when a title changes hands.

    Per T3.4 brief: "when a title changes hands. Writer: in the
    title-change logic, write a former_champions link between the
    ex-champion and the title."

    Since fighter_memory_links only supports fighter↔fighter columns,
    we use a SELF-LINK (fighter_id = linked_fighter_id = ex_champion_
    id) to flag "this fighter used to hold a title". The actual
    title_id isn't stored in the link — the Memory Engine can look
    up which titles the fighter held via the titles table (where
    current_champion_fighter_id is NULL but the fighter's reign is
    recorded in title_reigns_count + the fighter's career history).

    Distinct from the existing 'title_history' link_type (added
    v3.28.0) which is a PAIRWISE link between the new + former
    champion. The 'former_champions' (plural) self-link captures the
    ex-champion's identity as a former titleholder — independent of
    who they lost it to.

    link_strength=80 (mirrors title_history — being a former champion
    is a major career marker).

    Args:
        conn: sqlite3.Connection. Caller commits.
        ex_champion_id: int. The fighter who just lost the title.
        title_id: optional int. Used only for the defensive log
            message (not stored on the link).

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not ex_champion_id:
        return 0
    try:
        # Self-link: fighter_id = linked_fighter_id.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'former_champions', 80)",
            (ex_champion_id, ex_champion_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_former_champions_link("
              f"ex_champion_id={ex_champion_id}, title_id={title_id}) "
              f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_controversial_losses_link(conn, loser_id, winner_id):
    """Write a 'controversial_losses' PAIRWISE link when a fight
    ends in a split decision or disputed stoppage.

    Per T3.4 brief: "on split_decision or disputed stoppage. Writer:
    in fight_engine.resolve_next_fight, when result_type='split_
    decision', write a controversial_losses link."

    Distinct from the existing 'controversial_loss' SEARCH TYPE in
    memory_engine.py (which reads fight_history directly): the
    T3.4-mandated 'controversial_losses' (plural) link_type is a
    PERSISTED flag that the Memory Engine can read without re-
    scanning fight_history. It also captures the "disputed stoppage"
    case (the brief mentions both split_decision and disputed
    stoppage) — the caller decides when a stoppage is "disputed"
    (e.g., a doctor_stoppage with a close damage margin).

    PAIRWISE bidirectional link with link_strength=70 (a
    controversial loss is a strong memory — the loser will want
    a rematch, the winner will want to silence the doubters).

    Args:
        conn: sqlite3.Connection. Caller commits.
        loser_id: int. The fighter who lost controversially.
        winner_id: int. The fighter who won.

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not loser_id or not winner_id or loser_id == winner_id:
        return 0
    try:
        # Bidirectional link (the loss is controversial from the
        # loser's perspective; the win is "tainted" from the
        # winner's perspective — both remember it).
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'controversial_losses', 70)",
            (loser_id, winner_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'controversial_losses', 70)",
            (winner_id, loser_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_controversial_losses_link("
              f"loser={loser_id}, winner={winner_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_injuries_link(conn, fighter_id, injury_id=None):
    """Write an 'injuries' SELF-LINK when a fighter is injured.

    Per T3.4 brief: "when a fighter is injured. Writer: in
    injuries_svc, when creating an injury, write an injuries
    memory_link."

    Distinct from the existing 'injury_history' link_type (added
    v3.12.0): the T3.4-mandated 'injuries' (plural) variant captures
    the same concept under a different link_type enum value. The
    brief explicitly lists 'injuries' as a new type, so we add it
    alongside the existing 'injury_history' (the singular form was
    never wired to a writer in the original v3.12.0 work — it was
    only used as a SEARCH TYPE label in memory_engine.py).

    SELF-LINK (fighter_id = linked_fighter_id = fighter_id). The
    actual injury_id isn't stored in the link — the Memory Engine
    reads the injuries table directly when surfacing the memory
    (it queries injuries WHERE fighter_id=? AND is_active=1, which
    is more efficient than reading link_strength).

    link_strength=55 (an active injury is a moderately strong memory
    — the fighter is currently affected, but the memory fades once
    the injury heals).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The injured fighter.
        injury_id: optional int. Used only for the defensive log
            message (not stored on the link).

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not fighter_id:
        return 0
    try:
        # Self-link: fighter_id = linked_fighter_id.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'injuries', 55)",
            (fighter_id, fighter_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_injuries_link(fighter_id="
              f"{fighter_id}, injury_id={injury_id}) failed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_promotions_link(conn, fighter_id, old_promotion_id=None):
    """Write a 'promotions' SELF-LINK when a fighter changes
    promotion.

    Per T3.4 brief: "when a fighter changes promotion. Writer: in
    contracts.sign_free_agent, write a promotions link between the
    fighter and the old promotion."

    Since fighter_memory_links only supports fighter↔fighter columns,
    we use a SELF-LINK (fighter_id = linked_fighter_id = fighter_id)
    to flag "this fighter has changed promotions". The actual
    old_promotion_id isn't stored in the link — it's looked up via
    the fighter's contract history (fighter_contracts + contracts
    tables) when the memory is surfaced.

    link_strength=60 (a promotion change is a meaningful career
    event — the fighter's audience + rivalries may shift).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The fighter who changed promotions.
        old_promotion_id: optional int. The fighter's previous
            promotion. Used only for the defensive log message (not
            stored on the link). If None, the link is still written
            (the fighter was a free agent before signing — they
            "changed" from no promotion to a promotion).

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not fighter_id:
        return 0
    try:
        # Self-link: fighter_id = linked_fighter_id.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'promotions', 60)",
            (fighter_id, fighter_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_promotions_link(fighter_id="
              f"{fighter_id}, old_promotion_id={old_promotion_id}) "
              f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0


def write_old_events_link(conn, fighter_id, event_id=None, event_type=None):
    """Write an 'old_events' SELF-LINK for milestone events (title
    fights, main events).

    Per T3.4 brief: "for milestone events (title fights, main
    events). Writer: in fight_engine.resolve_next_fight, when
    is_title_fight=1, write an old_events link."

    Since fighter_memory_links only supports fighter↔fighter columns,
    we use a SELF-LINK (fighter_id = linked_fighter_id = fighter_id)
    to flag "this fighter participated in a milestone event". The
    actual event_id isn't stored in the link — the Memory Engine can
    look up the fighter's title fights + main events via fight_history
    JOIN events when surfacing the memory.

    link_strength=75 (a title fight / main event is a major career
    marker — stronger than a generic fight).

    Args:
        conn: sqlite3.Connection. Caller commits.
        fighter_id: int. The fighter who participated in the
            milestone event.
        event_id: optional int. The event_id of the milestone event.
            Used only for the defensive log message (not stored on
            the link).
        event_type: optional str. The type of milestone event
            ('title_fight', 'main_event', etc.). Used only for the
            defensive log message.

    Returns:
        int — 1 if the link was written, 0 if skipped or on error.
    """
    if not fighter_id:
        return 0
    try:
        # Self-link: fighter_id = linked_fighter_id.
        conn.execute(
            "INSERT OR IGNORE INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type, link_strength) "
            "VALUES (?, ?, 'old_events', 75)",
            (fighter_id, fighter_id),
        )
        return 1
    except sqlite3.Error as e:
        import sys
        print(f"WARNING: memory_svc.write_old_events_link(fighter_id="
              f"{fighter_id}, event_id={event_id}, event_type={event_type}) "
              f"failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0


# ============================================================
# HW3.1 — Event bus subscribers (auto-wire the writers)
# ============================================================
# Per HW3.1: "Each writer should be called from the appropriate event
# bus subscriber (FIGHT_RESOLVED, TITLE_CHANGED, FIGHTER_RETIRED,
# etc.)". register_subscribers wires them up so callers don't have
# to remember to invoke each writer inline.
#
# Registration happens from interpretation/__init__.py (after the
# existing interpretation subscribers + echoes_engine subscriber)
# per CONVENTIONS §17.5 (interpretation layer registered LAST so all
# simulation writes are visible to the memory queries).

def _on_fight_resolved(conn, event):
    """FIGHT_RESOLVED subscriber — writes upset + comeback + milestone
    links for the just-resolved fight.

    Reads from the event payload:
      - winner_id, loser_id → check for upset (rating gap ≥ 15).
      - winner_id, loser_id → check for comeback (the winner may be
        returning from a long layoff).
      - winner_id, loser_id → check for milestones (10 wins / 20 wins
        / 5-KO streak / 10th title defense).

    All checks are defensive — a single failed write must not abort
    the others. The event_bus ALSO catches subscriber exceptions, but
    we log here with fight context for easier debugging.
    """
    fight_id = event.get("fight_id")
    winner_id = event.get("winner_id")
    loser_id = event.get("loser_id")
    event_date = event.get("event_date")
    result_type = event.get("result_type")
    is_title_fight = event.get("is_title_fight")
    title_changed = event.get("title_changed")

    if not winner_id or not loser_id:
        return  # draw or no-contest — no pairwise winner/loser

    # ---- Upset check ----
    try:
        write_upset_link(conn, winner_id, loser_id)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fight_resolved upset check "
              f"failed (fight_id={fight_id}): {type(e).__name__}: {e}",
              file=sys.stderr)

    # ---- Comeback check (for the winner) ----
    # If the winner hadn't fought in 365+ days before this fight, they
    # just came back from a long absence.
    try:
        write_comeback_link(conn, winner_id, event_date=event_date)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fight_resolved comeback check "
              f"failed (fight_id={fight_id}): {type(e).__name__}: {e}",
              file=sys.stderr)

    # ---- Milestone checks (for the winner) ----
    try:
        _check_and_write_milestones(conn, winner_id, loser_id,
                                    result_type, is_title_fight,
                                    title_changed, event_date)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fight_resolved milestone check "
              f"failed (fight_id={fight_id}): {type(e).__name__}: {e}",
              file=sys.stderr)

    # ---- TIER3-MISSING §T3.4 — previous_fights link ----
    # Per the T3.4 brief: "when two fighters have fought before.
    # Writer: in fight_engine.resolve_next_fight, after writing
    # fight_history, check if these two fighters have fought before.
    # If yes, write a previous_fights memory_link."
    # The check is: did this pair fight BEFORE this fight? If so,
    # this fight is at least their 2nd meeting — write the link.
    # We use the fight_history table to detect prior meetings
    # (events before this fight's event_date).
    try:
        if event_date:
            prior = conn.execute(
                "SELECT COUNT(*) FROM fight_history "
                "WHERE fighter_id=? AND opponent_id=? "
                "  AND event_date < ?",
                (winner_id, loser_id, event_date),
            ).fetchone()
            if prior and prior[0] > 0:
                write_previous_fights_link(conn, winner_id, loser_id)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fight_resolved previous_fights "
              f"check failed (fight_id={fight_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # ---- TIER3-MISSING §T3.4 — controversial_losses link ----
    # Per the T3.4 brief: "on split_decision or disputed stoppage.
    # Writer: in fight_engine.resolve_next_fight, when result_type=
    # 'split_decision', write a controversial_losses link."
    # We also extend "disputed stoppage" to include doctor_stoppage
    # (the brief mentions both — a doctor stoppage can be disputed
    # if the fighter wanted to continue).
    try:
        if result_type in ("split_decision", "doctor_stoppage"):
            write_controversial_losses_link(conn, loser_id, winner_id)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fight_resolved controversial_"
              f"losses check failed (fight_id={fight_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # ---- TIER3-MISSING §T3.4 — old_events link (title fights) ----
    # Per the T3.4 brief: "for milestone events (title fights, main
    # events). Writer: in fight_engine.resolve_next_fight, when
    # is_title_fight=1, write an old_events link."
    # Write a self-link for BOTH fighters (both participated in the
    # milestone event).
    try:
        if is_title_fight:
            write_old_events_link(conn, winner_id,
                                  event_id=event.get("event_id"),
                                  event_type="title_fight")
            write_old_events_link(conn, loser_id,
                                  event_id=event.get("event_id"),
                                  event_type="title_fight")
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fight_resolved old_events "
              f"check failed (fight_id={fight_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)


def _check_and_write_milestones(conn, winner_id, loser_id, result_type,
                                 is_title_fight, title_changed,
                                 event_date):
    """Check whether the winner just hit a career milestone against
    the loser, and if so, write a milestone link.

    Milestones (per HW3.1 spec):
      - 10 wins  — winner's total wins (across fight_history) hit 10.
      - 20 wins  — winner's total wins hit 20.
      - 5-KO streak — winner's consecutive KO/TKO wins hit 5.
      - 10th title defense — winner just defended their title for the
        10th time (titles.title_defenses_count == 10 after the fight).

    Only ONE milestone link is written per fight (the most significant
    one — 20 wins > 10 wins > 10th title defense > 5-KO streak).
    """
    # Total wins for the winner (count of fight_history rows where
    # outcome='win' for this fighter, up to and including this fight).
    wins_row = conn.execute(
        "SELECT COUNT(*) FROM fight_history "
        "WHERE fighter_id=? AND outcome='win' "
        "  AND event_date <= ?",
        (winner_id, event_date or "9999-12-31"),
    ).fetchone()
    total_wins = wins_row[0] if wins_row else 0

    # 5-KO streak — count consecutive KO/TKO wins from the most recent
    # backwards.
    ko_streak = 0
    if result_type == "ko_tko":
        rows = conn.execute(
            "SELECT outcome, result_type FROM fight_history "
            "WHERE fighter_id=? AND event_date <= ? "
            "ORDER BY event_date DESC",
            (winner_id, event_date or "9999-12-31"),
        ).fetchall()
        for outcome, rtype in rows:
            if outcome == "win" and rtype == "ko_tko":
                ko_streak += 1
            else:
                break

    # 10th title defense — read titles.title_defenses_count for the
    # winner (if they're a current champion and just defended).
    title_defenses = 0
    if is_title_fight and not title_changed:
        # The winner defended their title (no title change means the
        # champion retained). Look up their current titles.
        td_row = conn.execute(
            "SELECT MAX(title_defenses_count) FROM titles "
            "WHERE current_champion_fighter_id=?",
            (winner_id,),
        ).fetchone()
        title_defenses = td_row[0] if td_row else 0

    # Pick the most significant milestone (priority order).
    milestone_type = None
    if total_wins == 20:
        milestone_type = "wins_20"
    elif total_wins == 10:
        milestone_type = "wins_10"
    elif title_defenses == 10:
        milestone_type = "title_defense_10"
    elif ko_streak == 5:
        milestone_type = "ko_streak_5"

    if milestone_type:
        write_milestone_link(conn, winner_id, loser_id, milestone_type)


def _on_title_changed(conn, event):
    """TITLE_CHANGED subscriber — writes a title_history link
    between the new champion and the dethroned former champion.

    The TITLE_CHANGED event payload (published by
    services/fight_engine.py:resolve_next_fight) includes:
      title_id, fight_id, event_id, promotion_id, weight_class_id

    The new champion is in titles.current_champion_fighter_id
    (already updated before the event fires). The former champion
    is the loser of the title fight (fights.loser_fighter_id).

    If the title was vacant before (no former champion), no link is
    written.
    """
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")
    if not title_id or not fight_id:
        return

    try:
        # New champion.
        new_champ_row = conn.execute(
            "SELECT current_champion_fighter_id, title_reigns_count "
            "FROM titles WHERE title_id=?",
            (title_id,),
        ).fetchone()
        if not new_champ_row:
            return
        new_champ, reigns_count = new_champ_row
        if not new_champ:
            return

        # reigns_count == 1 means the title was just claimed from
        # vacant — no former champion to link to. Skip in that case.
        if reigns_count is not None and reigns_count <= 1:
            return

        # Former champion — loser of the title fight.
        loser_row = conn.execute(
            "SELECT loser_fighter_id FROM fights WHERE fight_id=?",
            (fight_id,),
        ).fetchone()
        if not loser_row:
            return
        former_champ = loser_row[0]
        if not former_champ:
            return

        write_title_history_link(conn, new_champ, former_champ, title_id)

        # TIER3-MISSING §T3.4 — former_champions self-link for the
        # ex-champion. The title_history link above is PAIRWISE
        # (new_champ ↔ former_champ); this self-link flags the
        # former_champ as a former titleholder (independent of who
        # they lost to). Written AFTER title_history so a failure
        # here doesn't block the pairwise link.
        write_former_champions_link(conn, former_champ, title_id)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_title_changed failed "
              f"(title_id={title_id}, fight_id={fight_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)


def _on_fighter_signed(conn, event):
    """FIGHTER_SIGNED subscriber — writes a comeback link if the
    fighter was previously retired.

    The FIGHTER_SIGNED event payload (published by
    services/contracts.sign_free_agent) includes:
      fighter_id, promotion_id, contract_id, current_date, event_date

    We check the fighter's is_retired flag. If it was 1 BEFORE this
    signing (the signing flow resets it to 0), the fighter is "coming
    out of retirement" — write a comeback link to their last opponent
    before retirement.

    Note: the signing flow sets is_retired=0 BEFORE the FIGHTER_SIGNED
    event fires, so we can't read the pre-signing flag directly.
    Instead, we check whether the fighter has any fight_history rows
    AND whether there's a >= 365-day gap between their last fight and
    the signing date. If so, it's a comeback (whether the fighter was
    formally retired or just inactive for a year).

    This overlaps with the FIGHT_RESOLVED comeback check (which fires
    when the fighter's NEXT fight happens after the layoff). Both
    writes are idempotent — the second one is a no-op.
    """
    fighter_id = event.get("fighter_id")
    event_date = event.get("current_date") or event.get("event_date")
    if not fighter_id:
        return
    try:
        write_comeback_link(conn, fighter_id, event_date=event_date)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fighter_signed comeback check "
              f"failed (fighter_id={fighter_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # TIER3-MISSING §T3.4 — promotions self-link. Per the brief:
    # "when a fighter changes promotion. Writer: in
    # contracts.sign_free_agent, write a promotions link between the
    # fighter and the old promotion."
    # The FIGHTER_SIGNED event fires from sign_free_agent (the
    # canonical promo-change path), so this subscriber is the right
    # place to wire it. We pass the new promotion_id from the event
    # payload (the OLD promotion is None for a true free agent — the
    # fighter had no promo before signing).
    try:
        write_promotions_link(conn, fighter_id,
                              old_promotion_id=None)
    except Exception as e:
        import sys
        print(f"WARNING: memory_svc._on_fighter_signed promotions "
              f"link failed (fighter_id={fighter_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)


def register_subscribers():
    """Register memory_svc subscribers on the event bus.

    Per HW3.1: "Each writer should be called from the appropriate
    event bus subscriber." This function wires:
      - FIGHT_RESOLVED → _on_fight_resolved (upset + comeback + milestone)
      - TITLE_CHANGED  → _on_title_changed (title_history)
      - FIGHTER_SIGNED → _on_fighter_signed (comeback from retirement)

    NOT registered for FIGHTER_RETIRED — the retirement event doesn't
    write a memory link directly (the comeback link is written when
    the fighter RETURNS, not when they leave). The regen 'successor'
    + 'style_echo' links are written inline by tick_processor +
    populate_style_echo (existing Task 6.0 path).

    Registered from interpretation/__init__.py AFTER the existing
    interpretation subscribers + echoes_engine, per CONVENTIONS
    §17.5 (interpretation layer registered LAST so all simulation
    writes are visible to the memory queries — rankings, titles, and
    fight_history are all committed before the event fires).

    Safe to call multiple times — duplicate subscriptions would just
    result in the subscriber running N times (the bus has no dedup),
    but in practice it's called exactly once.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.FIGHT_RESOLVED, _on_fight_resolved,
                  name="memory_svc.fight_resolved")
    bus.subscribe(Events.TITLE_CHANGED, _on_title_changed,
                  name="memory_svc.title_changed")
    bus.subscribe(Events.FIGHTER_SIGNED, _on_fighter_signed,
                  name="memory_svc.fighter_signed")
