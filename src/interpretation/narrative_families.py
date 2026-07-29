"""CAGE EMPIRE Narrative Families Engine (Phase 2 Task 2.4).

Computes the narrative family for every active fighter — at most ONE
of 4 MVP labels: prodigy, veteran, fallen_champion, cinderella_story.
A fighter whose state doesn't match any rule gets NULL (no family).

Narrative families are HIGHER-ORDER story archetypes that layer ABOVE
the career_phase label. A fighter's career_phase="prospect" tells you
WHERE they are in their career; their narrative_family="prodigy" tells
you the STORY being told about them right now (a hot prospect turning
heads, the wunderkind everyone's talking about). Not every prospect is
a prodigy — only the ones on a hot streak. Not every veteran is a
"Veteran family" — only the ones whose momentum has flattened or
faded (a veteran on a 4-fight win streak is a "Veteran on a late
surge", which is a different story the engine doesn't tell yet).

Per CONVENTIONS §17.4: each cache column stores BOTH the canonical
label AND a voice phrase, separated by `||`:
    "prodigy||a prodigy turning heads early"
The UI reads the voice phrase (after the `||`); the interpretation
engine's rules + tests read the canonical label (before the `||`).
Encode/decode helpers are reused from `context_engine` (D1) so the
"label||phrase" storage format has ONE source of truth across the
interpretation layer.

Per CONVENTIONS §17.5: `compute_all_families` uses the bulk-load
pattern demonstrated by `career_arc._process_career_arc`:
  1. ONE main SELECT (fighter_descriptors JOIN fighters JOIN
     fighter_career) — fetch all 4450 active fighters in one go. The
     momentum + career_phase columns are already populated by the
     context_engine (Task 2.2) and career_phase_engine (Task 2.3)
     daily passes that ran IMMEDIATELY BEFORE this one in
     `snapshot_cache._interpret_fighters`.
  2. Python loop — pure CPU, no DB calls inside the loop.
  3. `conn.executemany("UPDATE fighter_descriptors SET narrative_family=?")` —
     one batched write.
Target: <1 second for 4450 active fighters.

Per CONVENTIONS §17.1: this module writes ONLY to `fighter_descriptors`
(a cache table). It NEVER writes to simulation tables (fighters,
fighter_career, rankings, titles, contracts, etc.).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Reuse `encode` / `decode_label` / `decode_phrase` from
      `context_engine` rather than redefining them. The "label||phrase"
      storage format must have ONE source of truth across the
      interpretation layer — duplicating the helpers risks drift.
  D2  4 MVP families cut from the spec's 14 (per PHASE_2_PLAN §5,
      Task 2.4 + §4 MVP Cut). Excluded: gatekeeper, dynasty, dark_
      horse, late_bloomer, redemption_arc, final_run, changing_of_
      the_guard, giant_killer, nearly_man, champion_in_waiting.
      These can be added in Phase 3+ when the data warrants them —
      the canonical labels are documented as enum-like constants to
      make extension safe.
  D3  At most ONE family per fighter (or NULL). This is the spec's
      "first match wins" rule — a prodigy who is also a fallen
      champion (impossible by criteria, but in principle) is classified
      as the FIRST matching rule in the priority order, not as a
      composite label. This keeps the UI label readable ("The Prodigy"
      is one story; "The Prodigy / Fallen Champion" is noise).
  D4  Priority order (first match wins):
        1. prodigy           — career_phase=prospect AND
                               momentum in (very_high, high)
        2. fallen_champion   — career_phase=declining AND
                               title_reigns > 0 AND
                               momentum in (falling, collapsing)
        3. cinderella_story  — career_phase=rising_contender AND
                               momentum=very_high AND age >= 28
        4. veteran           — career_phase=veteran AND
                               momentum in (stable, falling)
      The order matters: a former champion who is declining + falling
      is "fallen_champion" (the more specific story supersedes the
      generic "veteran on a down slope" story). A 28yo rising
      contender on a 5-fight streak is "cinderella_story" (the late-
      bloomer story) rather than no label at all. A young prospect on
      a hot streak is "prodigy" — the wunderkind story is the FIRST
      thing players should hear about a 21yo knockout artist.
  D5  NULL is a valid outcome. Most fighters will NOT match any family
      — a 30yo rising_contender on a 2-fight win streak (momentum=
      stable) doesn't fit any of the 4 MVP archetypes. That's fine:
      the UI shows the career_phase + momentum phrases but no family
      label. The full spec's 14 families would cover more of these
      cases; the MVP cut deliberately ships thin (per §4: "~40% of
      the content volume with ~80% of the player-perceived value").
  D6  Skip inactive OR retired fighters (`is_active=0 OR is_retired=1`)
      — same filter as `context_engine.compute_all_fighters`. The
      narrative_family only makes sense for active fighters (career_
      phase + momentum are NULL for retired fighters; the legacy_
      engine handles the post-retirement story). The 60 HoF legends
      keep their NULL narrative_family.
  D7  RNG seeded by fighter_id (`Random(fighter_id * 31 + 17)`) so
      each fighter's voice phrase is DETERMINISTIC. Same seed formula
      as `context_engine` + `career_phase_engine` for consistency —
      the same fighter always gets the same phrase across daily passes
      (no UI flickering). The pure `compute_narrative_family` function
      NEVER touches RNG.
  D8  Bumped `snapshot_cache.ENGINE_VERSION` from "1.2.0" to "1.3.0"
      — the cache must rebuild on first run after this code lands
      (the narrative_family column starts NULL; the daily pass fills
      it).
  D9  `compute_single_family` uses targeted queries (NOT the bulk
      pattern). It MUST complete in <10ms per CONVENTIONS §17.5 —
      a single SELECT on fighter_descriptors + JOIN fighters +
      fighter_career is plenty fast. No champion_set or rank_map
      needed (this engine doesn't use those).
"""
import random
import sqlite3
from datetime import datetime

# Reuse the encode/decode helpers + age computation from the context
# engine (D1) — single source of truth for the "label||phrase" storage
# format across the interpretation layer. Also reuse the momentum /
# career_phase canonical-label constants so we never typo a label
# string and silently break the rules.
from interpretation.context_engine import (
    encode,
    decode_label,
    decode_phrase,
    _compute_age,
    MOMENTUM_VERY_HIGH,
    MOMENTUM_HIGH,
    MOMENTUM_STABLE,
    MOMENTUM_FALLING,
    MOMENTUM_COLLAPSING,
)
from interpretation.career_phase_engine import (
    PHASE_PROSPECT,
    PHASE_RISING_CONTENDER,
    PHASE_VETERAN,
    PHASE_DECLINING,
)


# ============================================================
# CANONICAL LABEL CONSTANTS
# ============================================================
# These are the canonical labels stored BEFORE the "||" separator in
# fighter_descriptors.narrative_family. Tests read these. UI readers
# parse the voice phrase AFTER "||".
#
# Per D2: 4 MVP families (cut from the spec's 14). The full spec
# list is: prodigy, gatekeeper, fallen_champion, cinderella_story,
# veteran, dynasty, dark_horse, late_bloomer, redemption_arc,
# final_run, changing_of_the_guard, giant_killer, nearly_man,
# champion_in_waiting. We ship 4 in MVP — the rest are deferred to
# Phase 3+ when the data warrants them.

FAMILY_PRODIGY = "prodigy"
FAMILY_VETERAN = "veteran"
FAMILY_FALLEN_CHAMPION = "fallen_champion"
FAMILY_CINDERELLA_STORY = "cinderella_story"

ALL_FAMILIES = (
    FAMILY_PRODIGY,
    FAMILY_VETERAN,
    FAMILY_FALLEN_CHAMPION,
    FAMILY_CINDERELLA_STORY,
)


# ============================================================
# VOICE PHRASES (per §17.4 — "Rich Not Thin" principle)
# ============================================================
# Each canonical label maps to 3 voice phrase variants. The phrase is
# what the UI displays; the label is what logic/tests read.
#
# Phrases follow CAGE EMPIRE voice: gritty, journalistic, present-
# tense, no digits (CONVENTIONS §14). The variants add variety so
# two fighters with the same family label don't always read
# identically — but the SAME fighter always gets the SAME variant
# (RNG seeded by fighter_id, per D7).

FAMILY_PHRASES = {
    FAMILY_PRODIGY: [
        "a prodigy turning heads early",
        "the wunderkind everyone's talking about",
        "a can't-miss prospect with star written all over him",
    ],
    FAMILY_VETERAN: [
        "a grizzled veteran who refuses to fade quietly",
        "an old warhorse still saddling up",
        "a veteran who's been around the block more times than he can count",
    ],
    FAMILY_FALLEN_CHAMPION: [
        "a fallen champion searching for past glory",
        "a former king now fighting to stay relevant",
        "the ghost of a champion past",
    ],
    FAMILY_CINDERELLA_STORY: [
        "a Cinderella story defying the odds",
        "nobody saw this coming — an improbable rise",
        "the ultimate underdog story unfolding in real time",
    ],
}


# ============================================================
# VOICE PHRASE PICKER
# ============================================================

def get_family_phrase(family, rng=None):
    """Pick a voice phrase for the narrative family label (per §17.4).

    Args:
        family: canonical narrative family label (one of FAMILY_*),
            or None (no family).
        rng: optional random.Random for deterministic selection. If
            None, uses the global random (NOT deterministic — caller
            should pass an rng seeded by fighter_id for stable
            phrases across daily passes).

    Returns:
        A voice phrase string, or None if family is None. Falls back
        to the prodigy variants if the label is unrecognized
        (defensive — should not happen).
    """
    if family is None:
        return None
    if rng is None:
        rng = random
    variants = FAMILY_PHRASES.get(family, FAMILY_PHRASES[FAMILY_PRODIGY])
    return rng.choice(variants)


# ============================================================
# PURE COMPUTE FUNCTION — no DB, no RNG, no text
# ============================================================
# This is the canonical narrative family computer. It takes primitive
# inputs (canonical label strings + ints) and returns a canonical
# family label string OR None. No DB access, no RNG. The DB-write
# helpers (compute_all_families, compute_single_family) call this
# after loading + decoding the inputs.

def compute_narrative_family(career_phase, momentum, age, title_reigns):
    """Compute the canonical narrative family label (or None).

    Per spec §4 (Narrative Families) + the priority order in D4:

      Priority (first match wins; NULL if none match — D5):
        1. prodigy           — career_phase=prospect AND
                               momentum in (very_high, high)
        2. fallen_champion   — career_phase=declining AND
                               title_reigns > 0 AND
                               momentum in (falling, collapsing)
        3. cinderella_story  — career_phase=rising_contender AND
                               momentum=very_high AND age >= 28
        4. veteran           — career_phase=veteran AND
                               momentum in (stable, falling)

    The priority order matters because the rules are partially
    overlapping in momentum space (a veteran on a falling streak
    COULD also match fallen_champion if they held a title — but
    fallen_champion requires career_phase=declining, NOT veteran, so
    there's no actual overlap by phase). The order is a defensive
    safeguard: if Phase 3+ adds a rule that DOES overlap, the first
    match wins (per D3).

    Per the spec, a fighter can have AT MOST ONE family. NULL is a
    valid outcome (D5) — most fighters won't match any of the 4 MVP
    families. The UI shows their career_phase + momentum phrases but
    no family label.

    Defensive: None inputs are tolerated (career_phase=None → no
    match → None; momentum=None → no match → None; age=None → 0;
    title_reigns=None → 0). This keeps the daily pass from crashing
    on bad data.

    Args:
        career_phase: canonical career phase label string
            (e.g., "prospect"), or None.
        momentum: canonical momentum label string
            (e.g., "very_high"), or None.
        age: int (>= 0). Fighter's current age.
        title_reigns: int (>= 0). Number of title reigns the fighter
            has held in their career.

    Returns:
        Canonical narrative family label string (one of FAMILY_*
        constants), or None if no rule matches.
    """
    age = age or 0
    title_reigns = title_reigns or 0

    # 1. prodigy — prospect on a hot streak. The wunderkind story.
    #    Requires the prospect phase (young, few fights) AND high or
    #    very_high momentum (winning streak). A cold prospect (momentum
    #    = stable/falling/collapsing) is NOT a prodigy — they're just
    #    a prospect.
    if career_phase == PHASE_PROSPECT and momentum in (
            MOMENTUM_VERY_HIGH, MOMENTUM_HIGH):
        return FAMILY_PRODIGY

    # 2. fallen_champion — a former titleholder in decline. The
    #    "searching for past glory" story. Requires the declining
    #    phase (age + streak/health decline) AND title_reigns > 0
    #    (they actually held a belt at some point) AND falling or
    #    collapsing momentum. A declining fighter who never held a
    #    title is just declining — the "fallen" requires the prior
    #    "rise" to a title.
    if (career_phase == PHASE_DECLINING
            and title_reigns > 0
            and momentum in (MOMENTUM_FALLING, MOMENTUM_COLLAPSING)):
        return FAMILY_FALLEN_CHAMPION

    # 3. cinderella_story — a late-blooming rising contender on a
    #    blazing hot streak. The "nobody saw this coming" story.
    #    Requires the rising_contender phase, very_high momentum
    #    (5+ win streak), AND age >= 28 (late bloomer — a 22yo on a
    #    hot streak is a prodigy, not a Cinderella story). The age
    #    threshold is what makes this story resonate: an older
    #    fighter coming out of nowhere.
    if (career_phase == PHASE_RISING_CONTENDER
            and momentum == MOMENTUM_VERY_HIGH
            and age >= 28):
        return FAMILY_CINDERELLA_STORY

    # 4. veteran — a grizzled veteran on a flat or declining streak.
    #    The "refuses to fade quietly" story. Requires the veteran
    #    phase (age >= 35, 20+ fights) AND stable or falling momentum.
    #    A veteran on a 5-fight win streak (very_high) is a DIFFERENT
    #    story — a "veteran on a late surge" — which the MVP doesn't
    #    tell. They fall through to None (D5).
    if career_phase == PHASE_VETERAN and momentum in (
            MOMENTUM_STABLE, MOMENTUM_FALLING):
        return FAMILY_VETERAN

    # 5. No match — NULL is a valid outcome (D5). The UI shows their
    #    career_phase + momentum phrases but no family label.
    return None


# ============================================================
# BULK COMPUTE + WRITE (called by snapshot_cache.run_daily_pass)
# ============================================================

def compute_all_families(conn, current_date=None):
    """Bulk-compute narrative_family for all active fighters.

    Uses the bulk-load pattern from career_arc._process_career_arc
    (CONVENTIONS §17.5):
      1. ONE main SELECT (fighter_descriptors JOIN fighters JOIN
         fighter_career) — fetch all 4450 active fighters in one go.
         One query total — NOT N+1. The momentum + career_phase
         columns are already populated by the context_engine +
         career_phase_engine daily passes that run IMMEDIATELY BEFORE
         this one in snapshot_cache._interpret_fighters.
      2. Python loop — pure CPU, no DB calls inside the loop.
      3. conn.executemany("UPDATE fighter_descriptors SET narrative_family=?") —
         one batched write.

    Per §17.4: the column is written as "label||voice phrase" for
    fighters who match a family, OR NULL for fighters who don't (D5).
    Per D7: the voice phrase is RNG-seeded by fighter_id so it's
    deterministic across daily passes (no UI flickering).

    MUST complete in <1 second for 4450 active fighters (CONVENTIONS
    §17.5).

    Args:
        conn: sqlite3.Connection.
        current_date: optional ISO date string. If None, read from
            simulation_clock (the normal case — caller is the daily
            interpretation pass).

    Returns:
        int — number of fighter_descriptors rows UPDATED WITH A
        FAMILY (i.e., fighters who matched one of the 4 rules).
        Fighters who matched no rule are written NULL — they are NOT
        counted here (they're a "no-op" write). The caller can verify
        the column is no longer NULL by querying the DB directly.
    """
    # 1. Resolve current_date from simulation_clock if not provided.
    if current_date is None:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        if row is None:
            from datetime import date as _date
            current_date = _date.today().isoformat()
        else:
            current_date = row[0]

    # 2. Bulk-load all active (non-retired) fighters + their stored
    #    momentum + career_phase + DOB + title_reigns. We JOIN
    #    fighter_descriptors (for momentum + career_phase) to fighters
    #    (for DOB + active/retired filter) to fighter_career (for
    #    title_reigns). This is ONE SELECT — the bulk-load pattern.
    rows = conn.execute(
        """
        SELECT
            fd.fighter_id,
            fd.momentum,
            fd.career_phase,
            f.date_of_birth,
            fc.title_reigns
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        JOIN fighter_career fc ON fc.fighter_id = fd.fighter_id
        WHERE f.is_active = 1 AND f.is_retired = 0
        """
    ).fetchall()

    # 3. Python loop — compute family labels + voice phrases.
    #    Two batches: family-matched fighters (label||phrase writes)
    #    and no-match fighters (NULL writes — ensures rows that
    #    PREVIOUSLY had a family but no longer match get cleared,
    #    e.g., a prodigy who cooled off to stable momentum).
    family_updates = []
    null_updates = []
    for (fighter_id, stored_momentum, stored_career_phase, dob,
         title_reigns) in rows:

        # Decode the canonical labels from the stored "label||phrase"
        # values written by the context_engine + career_phase_engine.
        # If either is NULL (shouldn't happen for active fighters —
        # the prior daily passes populate them — but defensive), no
        # rule will match and the fighter gets a NULL family.
        momentum = decode_label(stored_momentum)
        career_phase = decode_label(stored_career_phase)

        # Compute age (defensive default 28 — same as context_engine
        # D8 — keeps the daily pass from crashing on bad DOB data).
        age = _compute_age(dob, current_date)

        family = compute_narrative_family(
            career_phase=career_phase,
            momentum=momentum,
            age=age,
            title_reigns=title_reigns,
        )

        if family is None:
            # No match — write NULL (D5). This clears any previously-
            # stored family so the UI doesn't show a stale label.
            null_updates.append((fighter_id,))
            continue

        # Deterministic RNG per fighter (D7) — same fighter always
        # gets the same voice phrase across daily passes. Same seed
        # formula as context_engine + career_phase_engine for
        # consistency.
        rng = random.Random(fighter_id * 31 + 17)
        phrase = get_family_phrase(family, rng)

        family_updates.append((encode(family, phrase), fighter_id))

    # 4. Batch UPDATEs (two executemanys — CONVENTIONS §17.5).
    if family_updates:
        conn.executemany(
            "UPDATE fighter_descriptors SET narrative_family=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            family_updates,
        )
    if null_updates:
        conn.executemany(
            "UPDATE fighter_descriptors SET narrative_family=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            null_updates,
        )
    if family_updates or null_updates:
        conn.commit()

    return len(family_updates)


# ============================================================
# SINGLE-FIGHTER REFRESH (called by snapshot_cache.refresh_fighter)
# ============================================================

def compute_single_family(conn, fighter_id, current_date=None):
    """Compute narrative_family for a single fighter (targeted refresh).

    Called by the 4 event-bus subscribers on FIGHT_RESOLVED,
    FIGHTER_RETIRED, TITLE_CHANGED, CONTRACT_EXPIRED (via
    snapshot_cache.refresh_fighter) so the UI shows the up-to-date
    family immediately, without waiting for the next daily pass.

    MUST complete in <10ms (CONVENTIONS §17.5). Uses a TARGETED query
    (one SELECT on fighter_descriptors JOIN fighters JOIN fighter_
    career for this fighter_id only).

    Args:
        conn: sqlite3.Connection.
        fighter_id: int.
        current_date: optional ISO date string.

    Returns:
        dict with key 'narrative_family' (canonical label or None),
        or None if the fighter doesn't exist / is retired / is
        inactive (we don't compute families for non-active fighters
        per D6).
    """
    if current_date is None:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        current_date = row[0] if row else None
    if not current_date:
        from datetime import date as _date
        current_date = _date.today().isoformat()

    row = conn.execute(
        """
        SELECT
            fd.fighter_id,
            fd.momentum,
            fd.career_phase,
            f.date_of_birth,
            f.is_active,
            f.is_retired,
            fc.title_reigns
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        JOIN fighter_career fc ON fc.fighter_id = fd.fighter_id
        WHERE fd.fighter_id = ?
        """,
        (fighter_id,),
    ).fetchone()

    if not row:
        return None

    (fid, stored_momentum, stored_career_phase, dob, is_active,
     is_retired, title_reigns) = row

    # Per D6: skip inactive OR retired fighters. Their narrative_
    # family is NULL — the legacy_engine handles the post-retirement
    # story.
    if not is_active or is_retired:
        # Clear any previously-stored family (defensive — shouldn't
        # happen since retirement fires a refresh that lands NULL
        # here, but a stale row could persist if the engine version
        # changed).
        conn.execute(
            "UPDATE fighter_descriptors SET narrative_family=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (fighter_id,),
        )
        conn.commit()
        return {"narrative_family": None}

    momentum = decode_label(stored_momentum)
    career_phase = decode_label(stored_career_phase)
    age = _compute_age(dob, current_date)

    family = compute_narrative_family(
        career_phase=career_phase,
        momentum=momentum,
        age=age,
        title_reigns=title_reigns,
    )

    if family is None:
        # No match — write NULL (D5).
        conn.execute(
            "UPDATE fighter_descriptors SET narrative_family=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (fighter_id,),
        )
        conn.commit()
        return {"narrative_family": None}

    rng = random.Random(fighter_id * 31 + 17)
    phrase = get_family_phrase(family, rng)

    conn.execute(
        "UPDATE fighter_descriptors SET narrative_family=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (encode(family, phrase), fighter_id),
    )
    conn.commit()

    return {"narrative_family": family}
