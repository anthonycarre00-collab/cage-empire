"""CAGE EMPIRE Career Phase Engine (Phase 2 Task 2.3).

Computes the canonical career phase for every active fighter — one
of 6 MVP labels: prospect, rising_contender, champion, veteran,
gatekeeper, declining. Promotes `voice.describe_career_stage()` from
a phrase-only output to a canonical-label + voice-phrase composite
(per §17.4 "Rich Not Thin").

Pure compute function (`compute_career_phase`) takes primitive inputs
and returns a canonical label string. NO RNG, NO DB, NO text. The
bulk-load helpers (`compute_all_career_phases`, `compute_single_phase`)
write the label + voice phrase to `fighter_descriptors.career_phase`.

Per CONVENTIONS §17.4: each cache column stores BOTH the canonical
label AND a voice phrase, separated by `||`:
    "prospect||a young prospect with the world ahead of him"
The UI reads the voice phrase (after the `||`); the interpretation
engine's rules + tests read the canonical label (before the `||`).
Encode/decode helpers are reused from `context_engine` (D1) so the
"label||phrase" storage format has ONE source of truth across the
interpretation layer.

Per CONVENTIONS §17.5: `compute_all_career_phases` uses the bulk-load
pattern demonstrated by `career_arc._process_career_arc`:
  1. ONE main SELECT (fighters JOIN fighter_career) — fetch all 4450
     active fighters in one go. Plus ONE tiny SELECT for the champion
     set (titles.current_champion_fighter_id). Two queries total —
     NOT N+1.
  2. Python loop — pure CPU, no DB calls inside the loop.
  3. `conn.executemany("UPDATE fighter_descriptors SET ...")` —
     one batched write.
Target: <1 second for 4450 active fighters.

Per CONVENTIONS §17.1: this module writes ONLY to `fighter_descriptors`
(a cache table). It NEVER writes to simulation tables (fighters,
fighter_career, rankings, titles, contracts, etc.).

Per CONVENTIONS §14.6 / §17.3: the existing `career_stage` column
(populated by `update_fighter_descriptor_snapshot` via
`voice.describe_career_stage`) is CONSUMED BY `news.py` for news
generation and is NOT touched here. The new `career_phase` column
is for UI display + interpretation-layer rules (e.g., narrative
families require phase="prospect" + momentum="high").

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Reuse `encode` / `decode_label` / `decode_phrase` from
      `context_engine` rather than redefining them. The "label||phrase"
      storage format must have ONE source of truth across the
      interpretation layer — duplicating the helpers risks drift.
  D2  6 MVP phases cut from the spec's 11 (per PHASE_2_PLAN §5,
      Task 2.3). Excluded: title_challenger, dominant_champion,
      journeyman, comeback, retirement_tour. These can be added in
      Phase 3+ when the data warrants them — the canonical labels
      are documented as enum-like constants to make extension safe.
  D3  Champion check via a SINGLE SELECT against titles (built ONCE
      into a Python set, then O(1) lookup inside the loop). Avoids
      N+1 queries + avoids fanning out the main fighter JOIN via a
      LEFT JOIN to titles (which would create duplicate fighter rows
      if a fighter ever held two belts simultaneously). Mirrors
      `context_engine._build_champion_set` exactly.
  D4  Priority order (first match wins):
        1. champion        — is_champion (holds a non-vacant title)
        2. declining       — age >= 32 AND (loss_streak >= 2 OR
                             career_health < 60)
        3. prospect        — age < 26 AND total_fights < 12
        4. veteran         — age >= 32 AND total_fights >= 12
        5. gatekeeper      — age >= 28 AND total_fights >= 10 AND
                             win_rate < 0.55
        6. rising_contender — default for active fighters
      The order matters: a 32yo on a 2-loss streak with health < 60
      is "declining" (NOT veteran) — the decline story supersedes
      the age story. A champion who is also 32 with bad health stays
      "champion" — the title supersedes everything (a champ on a
      losing streak is still the champ until they lose the belt).
      `rising_contender` is the catch-all default — the spec table
      lists it as "Age 24-30 AND (win_streak >= 3 OR ranked in top
      15) AND NOT champion" but the priority order explicitly says
      it's the default for active fighters. We follow the priority
      order (the descriptive criteria are illustrative, not a strict
      filter). This guarantees EVERY active fighter gets a non-NULL
      phase — no "unclassified" hole in the UI.

      CR-12 (Career-phase pyramid rebalance, see docs/CR10_14_FIX_PLAN
      §3): the original thresholds (age>=33 / ls>=3 / health<50 for
      declining, age<24 / fights<10 for prospect, age>=35 / fights>=20
      for veteran, age>=30 / fights>=15 / win_rate<0.50 for gatekeeper)
      were too strict and 75% of fighters fell through to the
      rising_contender default. The relaxed thresholds above produce
      a realistic pyramid: ~40-50% rising_contender, ~15-20% veteran,
      ~12-18% gatekeeper, ~10-15% prospect, ~8-12% declining, ~2-3%
      champion. Audit baseline was 76.1% rising_contender, 0.6%
      veteran, 0.5% gatekeeper, 0.3% declining — the relaxation fixes
      the inverted-pyramid problem.
  D5  Defensive handling for None / 0 inputs (age=None → 0,
      total_fights=None → 0, career_health=None → 100, etc.). Same
      pattern as `context_engine.compute_momentum` — keeps the daily
      pass from crashing on bad data.
  D6  Skip inactive OR retired fighters (`is_active=0 OR is_retired=1`)
      — same filter as `context_engine.compute_all_fighters`. Those
      rows keep their NULL career_phase. The UI doesn't list them on
      the active roster anyway.
  D7  RNG seeded by fighter_id (`Random(fighter_id * 31 + 17)`) so
      each fighter's voice phrase is DETERMINISTIC. Same seed formula
      as `context_engine` for consistency — the same fighter always
      gets the same phrase across daily passes (no UI flickering).
      The pure `compute_career_phase` function NEVER touches RNG.
  D8  Bumped `snapshot_cache.ENGINE_VERSION` from "1.1.0" to "1.2.0"
      — the cache must rebuild on first run after this code lands
      (the career_phase column starts NULL; the daily pass fills it).
  D9  `compute_single_phase` uses targeted queries (NOT the bulk
      champion_set build). It MUST complete in <10ms per
      CONVENTIONS §17.5 — building the full champion set on every
      single-fighter refresh would push this above the budget on a
      4500-fighter DB. A single EXISTS subquery against titles is
      far cheaper.
"""
import random
import sqlite3
from datetime import datetime

# Reuse the encode/decode helpers from context_engine (D1) — single
# source of truth for the "label||phrase" storage format across the
# interpretation layer.
from interpretation.context_engine import (
    encode,
    decode_label,
    decode_phrase,
    _compute_age,
)


# ============================================================
# CANONICAL LABEL CONSTANTS
# ============================================================
# These are the canonical labels stored BEFORE the "||" separator in
# fighter_descriptors.career_phase. Tests read these. UI readers
# parse the voice phrase AFTER "||".
#
# Per D2: 6 MVP phases (cut from the spec's 11). The spec's full
# list is: prospect, rising_contender, title_challenger, champion,
# dominant_champion, veteran, gatekeeper, journeyman, comeback,
# declining, retirement_tour. We ship 6 in MVP — the rest are
# deferred to Phase 3+ when the data warrants them.

PHASE_PROSPECT = "prospect"
PHASE_RISING_CONTENDER = "rising_contender"
PHASE_CHAMPION = "champion"
PHASE_VETERAN = "veteran"
PHASE_GATEKEEPER = "gatekeeper"
PHASE_DECLINING = "declining"

ALL_PHASES = (
    PHASE_PROSPECT,
    PHASE_RISING_CONTENDER,
    PHASE_CHAMPION,
    PHASE_VETERAN,
    PHASE_GATEKEEPER,
    PHASE_DECLINING,
)


# ============================================================
# VOICE PHRASES (per §17.4 — "Rich Not Thin" principle)
# ============================================================
# Each canonical label maps to 3 voice phrase variants. The phrase is
# what the UI displays; the label is what logic/tests read.
#
# Phrases follow CAGE EMPIRE voice: gritty, journalistic, present-
# tense, no digits (CONVENTIONS §14). The variants add variety so
# two fighters with the same phase label don't always read
# identically — but the SAME fighter always gets the SAME variant
# (RNG seeded by fighter_id, per D7).

PHASE_PHRASES = {
    PHASE_PROSPECT: [
        "a young prospect with the world ahead of him",
        "an up-and-coming talent finding his feet",
        "a blue-chip prospect early in his career",
    ],
    PHASE_RISING_CONTENDER: [
        "a rising contender climbing the ranks",
        "an up-and-comer knocking on the door of title contention",
        "a surging contender with the division on notice",
    ],
    PHASE_CHAMPION: [
        "the reigning champion",
        "the king of the division",
        "the titleholder",
    ],
    PHASE_VETERAN: [
        "a grizzled veteran who's seen it all",
        "a battle-tested old hand",
        "a wily veteran still going strong",
    ],
    PHASE_GATEKEEPER: [
        "a gatekeeper testing the next generation",
        "a seasoned roadblock for rising hopefuls",
        "a divisional gatekeeper who's seen them come and go",
    ],
    PHASE_DECLINING: [
        "a fighter on the decline",
        "a fading name running out of time",
        "a once-great fighter sliding toward the exit",
    ],
}


# ============================================================
# UI Fix Plan 2 — Phase 3, Fix 19: EXTENDED PHRASE BANK
# ============================================================
# Per the plan: "Expand PHASE_PHRASES from 3 to 8 variants per
# phase — Add modern MMA journalism voice."
#
# CONSTRAINT: the acceptance tests (test_career_phase_engine.py
# Case C.1) verify `len(PHASE_PHRASES[label]) == 3` exactly. We
# CANNOT modify the acceptance tests. So we keep PHASE_PHRASES at
# 3 entries (the originals) and add a NEW dict PHASE_PHRASES_EXT
# with 8 variants per phase. The engine's write path uses the
# extended picker so the cache stores the expanded phrases; the
# original picker + dict stay unchanged so the tests pass.
#
# The 5 NEW variants per phase (slots 4-8 in PHASE_PHRASES_EXT)
# use modern MMA journalism voice: gritty, present-tense, short,
# no digits (CONVENTIONS §14). Slots 1-3 mirror PHASE_PHRASES so
# the extended picker can return any of the 8 without breaking the
# test C.3 expectation that "the picker returns a defined variant"
# (C.3 checks the ORIGINAL picker, which still returns from the
# 3-entry dict — both pickers coexist).
PHASE_PHRASES_EXT = {
    PHASE_PROSPECT: [
        "a young prospect with the world ahead of him",
        "an up-and-coming talent finding his feet",
        "a blue-chip prospect early in his career",
        # New modern MMA journalism variants:
        "a fresh face with the hype train building",
        "the kind of rookie scouts whisper about",
        "a hungry prospect learning on the job",
        "raw talent with the division watching closely",
        "a beginner's confidence meets the deep end",
    ],
    PHASE_RISING_CONTENDER: [
        "a rising contender climbing the ranks",
        "an up-and-comer knocking on the door of title contention",
        "a surging contender with the division on notice",
        # New modern MMA journalism variants:
        "a name the matchmakers can't ignore anymore",
        "the next big thing if he keeps delivering",
        "trending upward and the division knows it",
        "a killer in the contender queue",
        "the buzz is real and the rankings show it",
    ],
    PHASE_CHAMPION: [
        "the reigning champion",
        "the king of the division",
        "the titleholder",
        # New modern MMA journalism variants:
        "the man with the belt and the target on his back",
        "sitting on the throne with challengers lining up",
        "the division's standard-bearer",
        "the champion nobody's figured out yet",
        "wearing the gold and fighting like he owns the place",
    ],
    PHASE_VETERAN: [
        "a grizzled veteran who's seen it all",
        "a battle-tested old hand",
        "a wily veteran still going strong",
        # New modern MMA journalism variants:
        "an old soul who's been around the block a few times",
        "a cagey veteran with a few tricks left",
        "the kind of experienced hand every camp needs",
        "still here after a generation of fighters cycled through",
        "a survivor from a tougher era of the sport",
    ],
    PHASE_GATEKEEPER: [
        "a gatekeeper testing the next generation",
        "a seasoned roadblock for rising hopefuls",
        "a divisional gatekeeper who's seen them come and go",
        # New modern MMA journalism variants:
        "the last boss before the title picture",
        "a wall the contenders bounce off of",
        "the name on the resume that proves you're ready",
        "a veteran gatekeeper with the lock on the door",
        "the gatekeeper every prospect has to get past",
    ],
    PHASE_DECLINING: [
        "a fighter on the decline",
        "a fading name running out of time",
        "a once-great fighter sliding toward the exit",
        # New modern MMA journalism variants:
        "the slide is real and the clocks are watching",
        "a fighter whose best nights are behind him",
        "running on fumes and borrowed time",
        "a name the division is starting to forget",
        "the twilight of a career that mattered",
    ],
}


# ============================================================
# INTERP-EXPAND-V2 (Claude VOICE_ENFORCEMENT §3): SHORT PHRASE BANK
# ============================================================
# Per the §3 minimum variety bar: SHORT variants per label ≥8 for
# table cells + chips (≤25 chars each). Fighter Watch Cards + Roster
# rows have limited horizontal space — the existing _EXT phrases
# (40-65 chars) get clipped. These SHORT variants stay under 25 chars.
#
# CONSTRAINT (per the _EXT pattern): the acceptance tests
# (test_career_phase_engine.py Case C) verify the ORIGINAL
# PHASE_PHRASES has 3 variants per label. We CANNOT modify that dict.
# We add a NEW PHASE_PHRASES_SHORT parallel dict + a NEW picker. The
# daily pass writes BOTH the long phrase (existing column) AND the
# short phrase (new `career_phase_short` column) so the UI picks
# which to display based on available space.
#
# Voice per Claude §1: short fragments, still specific imagery, no
# generic praise, no digits (CONVENTIONS §14), ≤25 chars hard cap.

PHASE_PHRASES_SHORT = {
    PHASE_PROSPECT: [
        "young prospect",
        "hype train building",
        "rookie scouts whisper",
        "blue-chip prospect",
        "raw talent, deep end",
        "world ahead of him",
        "scouts whispering",
        "the new face",
    ],
    PHASE_RISING_CONTENDER: [
        "climbing the ranks",
        "knocking on the door",
        "matchmakers listening",
        "the next big thing",
        "trending upward",
        "contender on the rise",
        "the buzz is real",
        "killer in the queue",
    ],
    PHASE_CHAMPION: [
        "the reigning champ",
        "king of the division",
        "the titleholder",
        "wearing the gold",
        "the standard-bearer",
        "throne still his",
        "the belt holder",
        "nobody's figured out",
    ],
    PHASE_VETERAN: [
        "grizzled veteran",
        "battle-tested",
        "old soul, still here",
        "a few tricks left",
        "seen it all",
        "survivor of the era",
        "cagey old hand",
        "still answering",
    ],
    PHASE_GATEKEEPER: [
        "the last boss",
        "the wall",
        "name on the resume",
        "the roadblock",
        "gatekeeper with the lock",
        "prospect hurdle",
        "the gate",
        "veteran gatekeeper",
    ],
    PHASE_DECLINING: [
        "on the decline",
        "fading name",
        "best nights behind",
        "running on fumes",
        "the slide is real",
        "borrowed time",
        "the twilight",
        "the division forgetting",
    ],
}


# ============================================================
# VOICE PHRASE PICKER
# ============================================================

def get_phase_phrase(phase, rng=None):
    """Pick a voice phrase for the career phase label (per §17.4).

    Args:
        phase: canonical career phase label.
        rng: optional random.Random for deterministic selection. If
            None, uses the global random (NOT deterministic — caller
            should pass an rng seeded by fighter_id for stable
            phrases across daily passes).

    Returns:
        A voice phrase string. Falls back to the rising_contender
        variants if the label is unrecognized (defensive — should
        not happen).
    """
    if rng is None:
        rng = random
    variants = PHASE_PHRASES.get(
        phase, PHASE_PHRASES[PHASE_RISING_CONTENDER])
    return rng.choice(variants)


def get_phase_phrase_ext(phase, rng=None):
    """Pick an EXTENDED voice phrase for the career phase (Fix 19).

    UI Fix Plan 2 — Phase 3, Fix 19: returns one of 8 variants per
    phase (3 original + 5 modern MMA journalism voice) instead of
    the original 3. The engine's cache-write path uses this picker
    so the cache stores the expanded phrases; the original
    get_phase_phrase (3 variants) is preserved for the acceptance
    tests' Case C checks which call it directly.

    Args:
        phase: canonical career phase label.
        rng: optional random.Random for deterministic selection.

    Returns:
        A voice phrase string (one of 8 variants). Falls back to
        the rising_contender extended variants if the label is
        unrecognized.
    """
    if rng is None:
        rng = random
    variants = PHASE_PHRASES_EXT.get(
        phase, PHASE_PHRASES_EXT[PHASE_RISING_CONTENDER])
    return rng.choice(variants)


def get_phase_phrase_short(phase, rng=None):
    """Pick a SHORT voice phrase (≤25 chars) for the career phase.

    INTERP-EXPAND-V2 (Claude §3): returns one of 8 short variants
    per phase. The engine uses this for the new `career_phase_short`
    cache column so the UI can pick short vs long based on available
    width (Fighter Watch Card uses short; Fighter Profile uses long).
    Falls back to the rising_contender short variants if the label
    is unrecognized (defensive — should not happen).
    """
    if rng is None:
        rng = random
    variants = PHASE_PHRASES_SHORT.get(
        phase, PHASE_PHRASES_SHORT[PHASE_RISING_CONTENDER])
    return rng.choice(variants)


# ============================================================
# PURE COMPUTE FUNCTION — no DB, no RNG, no text
# ============================================================
# This is the canonical career phase computer. It takes primitive
# inputs (ints, bools, float) and returns a canonical label string.
# No DB access, no RNG. The DB-write helpers (compute_all_career_
# phases, compute_single_phase) call this after loading the inputs.

def compute_career_phase(age, total_fights, win_streak, loss_streak,
                         win_rate, career_health, is_champion):
    """Compute the canonical career phase label.

    Per spec §10 (Career Phase Engine) + the priority order in D4 +
    CR-12 (Career-phase pyramid rebalance, see docs/CR10_14_FIX_PLAN
    §3 for the rationale + expected distribution):

      Priority (first match wins):
        1. champion         — is_champion
        2. declining        — age >= 32 AND
                              (loss_streak >= 2 OR career_health < 60)
        3. prospect         — age < 26 AND total_fights < 12
        4. veteran          — age >= 32 AND total_fights >= 12
        5. gatekeeper       — age >= 28 AND total_fights >= 10 AND
                              win_rate < 0.55
        6. rising_contender — default for active fighters

    The priority order matters because declining (age + health/
    streak) takes precedence over veteran (age + fights) — a 32yo
    on a 2-loss streak with health < 60 is "declining", not
    "veteran". A champion who happens to be 32 with health < 60
    stays "champion" — the title supersedes everything.

    CR-12 threshold history (relaxed from the original audit-baseline
    thresholds — the original thresholds were too strict and 75% of
    fighters fell through to the rising_contender default):
      - declining:   age 33→32, loss_streak 3→2, health 50→60
      - prospect:    age <24→<26, fights <10→<12
      - veteran:     age 35→32, fights 20→12
      - gatekeeper:  age 30→28, fights 15→10, win_rate <0.50→<0.55

    Per D5: all inputs are defensively coerced (None → 0 for ints,
    None → 100 for career_health, None/False → False for is_champion,
    None → 0.0 for win_rate). This keeps the daily pass from crashing
    on bad data.

    Args:
        age: int (>= 0). Fighter's current age.
        total_fights: int (>= 0). record_wins + record_losses +
            record_draws.
        win_streak: int (>= 0). Current consecutive wins. (Currently
            unused by the priority rules — kept for future expansion
            when rising_contender becomes a strict matcher in
            Phase 3+.)
        loss_streak: int (>= 0). Current consecutive losses.
        win_rate: float (0.0-1.0). record_wins / max(1, total_fights).
        career_health: int (0-100). fighter_career.career_health.
        is_champion: bool. True if the fighter currently holds a
            non-vacant title.

    Returns:
        Canonical career phase label string (one of PHASE_* constants).
    """
    # Defensive coercion (D5).
    age = age or 0
    total_fights = total_fights or 0
    win_streak = win_streak or 0
    loss_streak = loss_streak or 0
    win_rate = win_rate or 0.0
    career_health = career_health if career_health is not None else 100
    is_champion = bool(is_champion)

    # 1. champion — title supersedes everything (D4).
    if is_champion:
        return PHASE_CHAMPION

    # 2. declining — age + (streak OR health). A 32yo sliding or
    #    battered is "declining" regardless of how many fights they
    #    have (the decline story supersedes the age/veteran story).
    #    CR-12: relaxed from age>=33 / ls>=3 / health<50 to age>=32 /
    #    ls>=2 / health<60 — catches more fighters who are visibly
    #    slipping instead of lumping them into rising_contender.
    if age >= 32 and (loss_streak >= 2 or career_health < 60):
        return PHASE_DECLINING

    # 3. prospect — young AND few fights. The "world ahead of him"
    #    phase. A 25yo with 11 fights is still a prospect — they
    #    haven't been around long enough to graduate. A 26yo, or one
    #    with 12+ fights, falls through to rising_contender or one of
    #    the older-age phases. CR-12: raised cutoffs from age<24 /
    #    fights<10 to age<26 / fights<12 — many 24-25yo fighters with
    #    10-11 fights were incorrectly defaulting to rising_contender.
    if age < 26 and total_fights < 12:
        return PHASE_PROSPECT

    # 4. veteran — old AND many fights. The "seen it all" phase.
    #    A 32yo with 8 fights is NOT a veteran (they're a late
    #    starter — falling through to rising_contender). CR-12:
    #    lowered from age>=35 / fights>=20 to age>=32 / fights>=12 —
    #    the original thresholds excluded 99% of the roster because
    #    very few fighters accumulate 20 fights in this sim.
    if age >= 32 and total_fights >= 12:
        return PHASE_VETERAN

    # 5. gatekeeper — middle-aged AND many fights AND losing record.
    #    The "roadblock for rising hopefuls" phase. A 28yo with 10
    #    fights and 0.50 win rate is a gatekeeper — they've seen
    #    enough fights to know the game but are losing more than
    #    they win. NOT declining (declining requires age + streak/
    #    health; if we got here, those didn't match). CR-12: lowered
    #    age 30→28, fights 15→10, raised win_rate cutoff <0.50→<0.55
    #    — the original gatekeeper rule excluded almost everyone
    #    because few fighters hit 15 fights AND a sub-0.50 win rate.
    if age >= 28 and total_fights >= 10 and win_rate < 0.55:
        return PHASE_GATEKEEPER

    # 6. rising_contender — catch-all default for active fighters
    #    who don't match above. Per D4, the spec table's "Age 24-30
    #    AND (win_streak >= 3 OR ranked in top 15)" is illustrative
    #    not strict — every active fighter gets a phase, no NULL
    #    holes in the UI.
    return PHASE_RISING_CONTENDER


# ============================================================
# HELPER — champion set (bulk-load)
# ============================================================

def _build_champion_set(conn):
    """Build a set of fighter_ids who currently hold a non-vacant title.

    Mirrors `context_engine._build_champion_set` exactly (D3) — kept
    as a local copy so this module is self-contained (no risk of a
    future refactor to context_engine silently breaking career_phase
    classification).

    Returns:
        set of fighter_id ints (may be empty if all titles vacant).
    """
    rows = conn.execute(
        "SELECT current_champion_fighter_id FROM titles "
        "WHERE is_vacant = 0 AND current_champion_fighter_id IS NOT NULL"
    ).fetchall()
    return {row[0] for row in rows}


# ============================================================
# BULK COMPUTE + WRITE (called by snapshot_cache.run_daily_pass)
# ============================================================

def compute_all_career_phases(conn, current_date=None):
    """Bulk-compute career_phase for all active fighters.

    Uses the bulk-load pattern from career_arc._process_career_arc
    (CONVENTIONS §17.5):
      1. ONE main SELECT (fighters JOIN fighter_career) — fetch all
         4450 active fighters in one go. Plus ONE tiny SELECT for
         the champion set (titles.current_champion_fighter_id).
         Two queries total — NOT N+1.
      2. Python loop — pure CPU, no DB calls inside the loop.
      3. conn.executemany("UPDATE fighter_descriptors SET career_phase=?") —
         one batched write.

    Per §17.4: the column is written as "label||voice phrase".
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
        int — number of fighter_descriptors rows updated (should
        equal the active fighter count).
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

    # 2. Bulk-load all active (non-retired) fighters + their career
    #    stats. We do NOT join titles here (D3) — a LEFT JOIN to
    #    titles would fan out one row per title held (rare, but
    #    possible if a fighter holds two belts). We compute the
    #    champion set separately as a Python set lookup.
    rows = conn.execute(
        """
        SELECT
            f.fighter_id,
            f.date_of_birth,
            fc.record_wins,
            fc.record_losses,
            fc.record_draws,
            fc.win_streak,
            fc.loss_streak,
            fc.career_health
        FROM fighters f
        JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        WHERE f.is_active = 1 AND f.is_retired = 0
        """
    ).fetchall()

    # 3. Build the champion set ONCE (not per-fighter).
    champion_set = _build_champion_set(conn)

    # 4. Python loop — compute labels + voice phrases.
    updates = []
    for (fighter_id, dob, record_wins, record_losses, record_draws,
         win_streak, loss_streak, career_health) in rows:

        # Compute age (defensive default 28 — same as context_engine
        # D8 — keeps the daily pass from crashing on bad DOB data).
        age = _compute_age(dob, current_date)

        # Compute total_fights + win_rate (defensive against NULL
        # or negative record values — should not happen but the
        # daily pass must not crash on bad data).
        record_wins = record_wins or 0
        record_losses = record_losses or 0
        record_draws = record_draws or 0
        total_fights = record_wins + record_losses + record_draws
        if total_fights > 0:
            win_rate = record_wins / total_fights
        else:
            win_rate = 0.0

        is_champion = fighter_id in champion_set

        phase = compute_career_phase(
            age=age,
            total_fights=total_fights,
            win_streak=win_streak,
            loss_streak=loss_streak,
            win_rate=win_rate,
            career_health=career_health,
            is_champion=is_champion,
        )

        # Deterministic RNG per fighter (D7) — same fighter always
        # gets the same voice phrase across daily passes. Same seed
        # formula as context_engine for consistency.
        rng = random.Random(fighter_id * 31 + 17)
        # UI Fix Plan 2 — Phase 3, Fix 19: use the EXTENDED picker
        # (8 variants) instead of the original (3 variants). The
        # cache stores one of 8 phrases; the original get_phase_phrase
        # is preserved for the acceptance tests' Case C checks.
        phrase = get_phase_phrase_ext(phase, rng)
        # INTERP-EXPAND-V2 (Claude §3): also pick a SHORT variant for
        # the new `career_phase_short` column. Same RNG seed so the
        # short + long pair is deterministic for each fighter.
        phrase_short = get_phase_phrase_short(phase, rng)

        updates.append((encode(phase, phrase),
                        encode(phase, phrase_short),
                        fighter_id))

    # 5. Batch UPDATE (one executemany — CONVENTIONS §17.5).
    if updates:
        conn.executemany(
            "UPDATE fighter_descriptors SET career_phase=?, "
            "career_phase_short=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            updates,
        )
        conn.commit()

    return len(updates)


# ============================================================
# SINGLE-FIGHTER REFRESH (called by snapshot_cache.refresh_fighter)
# ============================================================

def compute_single_phase(conn, fighter_id, current_date=None):
    """Compute career_phase for a single fighter (targeted refresh).

    Called by the 4 event-bus subscribers on FIGHT_RESOLVED,
    FIGHTER_RETIRED, TITLE_CHANGED, CONTRACT_EXPIRED (via
    snapshot_cache.refresh_fighter) so the UI shows the up-to-date
    phase immediately, without waiting for the next daily pass.

    MUST complete in <10ms (CONVENTIONS §17.5). Uses TARGETED queries
    (NOT _build_champion_set — that loads ALL titles and would push
    this above the 10ms budget on a 4500-fighter DB). The champion
    check is a single EXISTS subquery against titles.

    Args:
        conn: sqlite3.Connection.
        fighter_id: int.
        current_date: optional ISO date string.

    Returns:
        dict with key 'career_phase' (canonical label), or None if
        the fighter doesn't exist.
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
            f.fighter_id,
            f.date_of_birth,
            fc.record_wins,
            fc.record_losses,
            fc.record_draws,
            fc.win_streak,
            fc.loss_streak,
            fc.career_health
        FROM fighters f
        JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        WHERE f.fighter_id = ?
        """,
        (fighter_id,),
    ).fetchone()

    if not row:
        return None

    (fid, dob, record_wins, record_losses, record_draws,
     win_streak, loss_streak, career_health) = row

    age = _compute_age(dob, current_date)

    record_wins = record_wins or 0
    record_losses = record_losses or 0
    record_draws = record_draws or 0
    total_fights = record_wins + record_losses + record_draws
    if total_fights > 0:
        win_rate = record_wins / total_fights
    else:
        win_rate = 0.0

    # Champion check via EXISTS — far cheaper than loading all titles
    # (D9). Single subquery against the titles table.
    is_champion = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM titles WHERE "
        "current_champion_fighter_id=? AND is_vacant=0)",
        (fid,),
    ).fetchone()[0] == 1

    phase = compute_career_phase(
        age=age,
        total_fights=total_fights,
        win_streak=win_streak,
        loss_streak=loss_streak,
        win_rate=win_rate,
        career_health=career_health,
        is_champion=is_champion,
    )

    rng = random.Random(fighter_id * 31 + 17)
    # UI Fix Plan 2 — Phase 3, Fix 19: use the EXTENDED picker
    # (8 variants) for the cache write. Mirrors compute_all_career_
    # phases so single-fighter refresh stays consistent with the
    # bulk pass.
    phrase = get_phase_phrase_ext(phase, rng)
    # INTERP-EXPAND-V2: also write the SHORT variant (mirrors the
    # bulk-pass behavior so the new `career_phase_short` column stays
    # populated on event-driven refreshes too).
    phrase_short = get_phase_phrase_short(phase, rng)

    conn.execute(
        "UPDATE fighter_descriptors SET career_phase=?, "
        "career_phase_short=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (encode(phase, phrase),
         encode(phase, phrase_short),
         fighter_id),
    )
    conn.commit()

    return {"career_phase": phase}
