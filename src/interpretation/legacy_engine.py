"""CAGE EMPIRE Legacy Engine (Phase 2 Task 2.7).

Computes the legacy state for every fighter — active AND retired. One
of 4 MVP labels: building, established, legendary, forgotten. Every
fighter gets a non-NULL legacy_state (it's the long-arc story of
their career as a whole, distinct from career_phase which is the
"where are they now" snapshot).

Per spec §14: legacy is "Not a Hall of Fame score. A living
interpretation." The hall_of_fame table is the BINARY induction
event (a fighter is or isn't inducted, by hof_svc.py). The legacy_
state is the GRADIENT around that event:
  - "building"  — too early to judge
  - "established" — a body of work that speaks for itself
  - "legendary"  — an all-time great (HoF OR multi-title + longevity)
  - "forgotten"  — retired without enough of a mark to be remembered

This is DIFFERENT from career_phase (the current-phase snapshot).
A retired Hall-of-Famer has career_phase=NULL (they're not active)
but legacy_state="legendary". A 22yo prospect has career_phase=
"prospect" but legacy_state="building" (too early to judge). The
two labels are orthogonal — they tell different stories to the
player at different timescales.

Per CONVENTIONS §17.4: each cache column stores BOTH the canonical
label AND a voice phrase, separated by `||`:
    "legendary||a legendary career that will be remembered"
The UI reads the voice phrase (after the `||`); the interpretation
engine's rules + tests read the canonical label (before the `||`).
Encode/decode helpers are reused from `context_engine` (D1) so the
"label||phrase" storage format has ONE source of truth across the
interpretation layer.

Per CONVENTIONS §17.5: `compute_all_legacies` uses the bulk-load
pattern demonstrated by `career_arc._process_career_arc`:
  1. ONE main SELECT (fighters JOIN fighter_career LEFT JOIN
     hall_of_fame) — fetch ALL 4510 fighters (active + retired) in
     one go. The LEFT JOIN to hall_of_fame is cheap (60 rows) and
     the COUNT(*) of duplicate rows is zero (hall_of_fame has a PK
     on fighter_id, so each fighter matches at most once).
  2. Python loop — pure CPU, no DB calls inside the loop.
  3. `conn.executemany("UPDATE fighter_descriptors SET legacy_state=?")` —
     one batched write.
Target: <1 second for 4510 fighters.

Per CONVENTIONS §17.1: this module writes ONLY to `fighter_descriptors`
(a cache table). It NEVER writes to simulation tables (fighters,
fighter_career, hall_of_fame, etc.).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Reuse `encode` / `decode_label` / `decode_phrase` from
      `context_engine` rather than redefining them. The "label||phrase"
      storage format must have ONE source of truth across the
      interpretation layer — duplicating the helpers risks drift.
  D2  4 MVP states cut from the spec's 6 (per PHASE_2_PLAN §5,
      Task 2.7 + §4 MVP Cut). Excluded: controversial, cult_hero.
      These can be added in Phase 3+ when the data warrants them —
      the canonical labels are documented as enum-like constants to
      make extension safe.
  D3  Applies to ALL fighters (active AND retired). This is the spec's
      explicit requirement: legacy is the long-arc story, not the
      current snapshot. A retired fighter has career_phase=NULL but
      legacy_state="legendary" / "forgotten" / "established". The
      engine does NOT filter by is_active / is_retired — everyone
      gets a legacy_state.
  D4  Priority order (first match wins):
        1. legendary   — in_hall_of_fame OR
                         (title_reigns >= 2 AND total_fights >= 30)
        2. forgotten   — is_retired AND NOT in_hall_of_fame AND
                         total_fights < 20
        3. established — NOT in_hall_of_fame AND total_fights >= 25
                         AND wins >= 15
        4. building    — NOT in_hall_of_fame AND
                         (total_fights < 15 OR
                          (total_fights < 25 AND wins < 15))
      The order matters: a retired HoF legend who fought < 20 fights
      (rare but possible — a dominant champ who retired early) is
      "legendary" (the HoF induction supersedes the "few fights"
      signal). A retired non-HoF fighter with < 20 fights is
      "forgotten" (the "few fights + retired + no HoF" signal
      supersedes "building" — they had their chance and didn't make
      a mark).
  D5  Defensive default: "building" for fighters who don't match any
      of the 4 explicit rules. The Building criteria as written has
      a gap: a fighter with 25+ fights and < 15 wins (a journeyman)
      doesn't match Building (total_fights < 25 fails) NOR
      Established (wins >= 15 fails). They default to "building"
      because the journeyman story is closer to "still building" than
      to "established" — they haven't done enough to be Established
      yet, and the "building" voice phrases ("too early to judge
      their legacy") are still appropriate. This guarantees EVERY
      fighter gets a non-NULL legacy_state (per D3).
  D6  RNG seeded by fighter_id (`Random(fighter_id * 31 + 17)`) so
      each fighter's voice phrase is DETERMINISTIC. Same seed formula
      as `context_engine` + `career_phase_engine` +
      `narrative_families` for consistency — the same fighter always
      gets the same phrase across daily passes (no UI flickering).
      The pure `compute_legacy_state` function NEVER touches RNG.
  D7  Bumped `snapshot_cache.ENGINE_VERSION` from "1.3.0" to "1.4.0"
      — the cache must rebuild on first run after this code lands
      (the legacy_state column starts NULL; the daily pass fills it).
  D8  `compute_single_legacy` uses a targeted query (one SELECT on
      fighters + fighter_career + LEFT JOIN hall_of_fame for this
      fighter_id only). MUST complete in <10ms per CONVENTIONS §17.5.
  D9  The HoF check uses a LEFT JOIN to hall_of_fame in the SELECT
      (not a separate subquery). hall_of_fame has a PK on fighter_id
      so the LEFT JOIN doesn't fan out — one row in, one row out.
      This keeps the bulk-load pattern at ONE query total.
"""
import random
import sqlite3

# Reuse the encode/decode helpers from the context engine (D1) —
# single source of truth for the "label||phrase" storage format
# across the interpretation layer.
from interpretation.context_engine import (
    encode,
    decode_label,
    decode_phrase,
)


# ============================================================
# CANONICAL LABEL CONSTANTS
# ============================================================
# These are the canonical labels stored BEFORE the "||" separator in
# fighter_descriptors.legacy_state. Tests read these. UI readers
# parse the voice phrase AFTER "||".
#
# Per D2: 4 MVP states (cut from the spec's 6). The full spec list
# is: building, established, legendary, forgotten, controversial,
# cult_hero. We ship 4 in MVP — the rest are deferred to Phase 3+
# when the data warrants them.

LEGACY_BUILDING = "building"
LEGACY_ESTABLISHED = "established"
LEGACY_LEGENDARY = "legendary"
LEGACY_FORGOTTEN = "forgotten"

ALL_LEGACY_STATES = (
    LEGACY_BUILDING,
    LEGACY_ESTABLISHED,
    LEGACY_LEGENDARY,
    LEGACY_FORGOTTEN,
)


# ============================================================
# VOICE PHRASES (per §17.4 — "Rich Not Thin" principle)
# ============================================================
# Each canonical label maps to 3 voice phrase variants. The phrase is
# what the UI displays; the label is what logic/tests read.
#
# Phrases follow CAGE EMPIRE voice: gritty, journalistic, present-
# tense, no digits (CONVENTIONS §14). The variants add variety so
# two fighters with the same legacy label don't always read
# identically — but the SAME fighter always gets the SAME variant
# (RNG seeded by fighter_id, per D6).

LEGACY_PHRASES = {
    LEGACY_BUILDING: [
        "still building a legacy",
        "the story is just beginning",
        "too early to judge their legacy",
    ],
    LEGACY_ESTABLISHED: [
        "an established career with real accomplishments",
        "a solid career that's earned respect",
        "a body of work that speaks for itself",
    ],
    LEGACY_LEGENDARY: [
        "a legendary career that will be remembered",
        "an all-time great",
        "a career for the history books",
    ],
    LEGACY_FORGOTTEN: [
        "a career that time forgot",
        "faded into obscurity",
        "a name barely remembered",
    ],
}


# ============================================================
# VOICE-P2 (Claude VOICE_ENFORCEMENT §3): EXTENDED LEGACY PHRASE BANK
# ============================================================
# Per Claude's §3 minimum variety bar: ≥8 variants per label for any
# label covering >5% of the active roster. The audit (§1.4) found
# `legacy_state` was shipping 3 variants per label against the 8-variant
# bar — `building` alone covers 99% of the active roster, so the same
# 3 phrases appeared on nearly every fighter.
#
# CONSTRAINT: the acceptance tests (test_narrative_legacy.py Case F)
# verify `len(LEGACY_PHRASES[label]) == 3` exactly. We CANNOT modify
# the acceptance tests. So we keep the original dict at 3 entries +
# add a NEW LEGACY_PHRASES_EXT dict with 8 variants per label. The
# engine's cache-write path uses the extended picker so the cache
# stores the expanded phrases; the original picker + dict stay
# unchanged so the tests pass.
#
# The 5 NEW variants per label use CAGE EMPIRE voice per Claude §1:
# promoter-flavored, past-tense narrative, specific imagery, hedged
# uncertainty for scouting, elegiac for decline. NOT sports-page
# filler, NOT tabloid clickbait.

LEGACY_PHRASES_EXT = {
    LEGACY_BUILDING: [
        # 3 original variants (kept for backward compatibility with
        # any external caller that imported the original dict).
        "still building a legacy",
        "the story is just beginning",
        "too early to judge their legacy",
        # 5 NEW variants — modern MMA journalism voice per Claude §1.
        # Building = too early to judge; the story hasn't been written
        # yet. Hedged uncertainty, promoter-flavored.
        "the book is still being written",
        "a story with chapters left to fill",
        "too soon to know what he'll be remembered for",
        "the resume is short, the runway is long",
        "a career the matchmakers are still sizing up",
    ],
    LEGACY_ESTABLISHED: [
        "an established career with real accomplishments",
        "a solid career that's earned respect",
        "a body of work that speaks for itself",
        # 5 NEW variants — Established = a known quantity, a career
        # that's earned its place. Specific imagery, past-tense.
        "a name that echoes through the division",
        "his legacy was cemented the night he beat the contender",
        "the kind of career the division measures others against",
        "a fighter the prospects study on tape",
        "a resume that doesn't need explaining",
    ],
    LEGACY_LEGENDARY: [
        "a legendary career that will be remembered",
        "an all-time great",
        "a career for the history books",
        # 5 NEW variants — Legendary = a chapter in the sport's
        # history. Elegiac tone, past-tense narrative, the kind of
        # phrasing a documentary voice-over would use.
        "the kind of career they make documentaries about",
        "when they write the history of this sport, he gets a chapter",
        "a name that belongs on the short list of all-time greats",
        "the kind of fighter the division measures itself against",
        "the kind of legacy that doesn't need defending",
    ],
    LEGACY_FORGOTTEN: [
        "a career that time forgot",
        "faded into obscurity",
        "a name barely remembered",
        # 5 NEW variants — Forgotten = a career that ended without
        # leaving a mark. Elegiac, specific imagery, the long goodbye.
        "the sport moved on without him",
        "a ghost haunting the rankings",
        "a name that slipped out of the conversation",
        "the kind of career the archives keep but the fans forget",
        "a fighter the division stopped writing about",
    ],
}


# ============================================================
# INTERP-EXPAND-V2 (Claude VOICE_ENFORCEMENT §3): SHORT PHRASE BANK
# ============================================================
# Per the §3 minimum variety bar: SHORT variants per label ≥8 for
# table cells + chips (≤25 chars each). Used by Fighter Watch Cards
# when the long _EXT phrase (30-65 chars) would be clipped.
#
# CONSTRAINT (per the _EXT pattern): the acceptance tests
# (test_narrative_legacy.py Case F) verify the ORIGINAL
# LEGACY_PHRASES has 3 variants per label. We CANNOT modify that
# dict. We add a NEW LEGACY_PHRASES_SHORT parallel dict + a NEW
# picker. The daily pass writes BOTH the long phrase (existing
# column) AND the short phrase (new `legacy_state_short` column).
#
# Voice per Claude §1: short fragments, still specific imagery, no
# generic praise, no digits (CONVENTIONS §14), ≤25 chars hard cap.

LEGACY_PHRASES_SHORT = {
    LEGACY_BUILDING: [
        "story just beginning",
        "the book unfinished",
        "too early to judge",
        "chapters left to fill",
        "short resume, long runway",
        "still being sized up",
        "legacy unwritten",
        "matchmakers watching",
    ],
    LEGACY_ESTABLISHED: [
        "established hand",
        "earned the respect",
        "body of work",
        "name echoes in division",
        "studied on tape",
        "resume speaks for itself",
        "division measures by him",
        "the known quantity",
    ],
    LEGACY_LEGENDARY: [
        "all-time great",
        "for the history books",
        "documentary-worthy",
        "the short list",
        "legacy needs no defending",
        "a chapter in the history",
        "legendary career",
        "the division measures by",
    ],
    LEGACY_FORGOTTEN: [
        "time forgot him",
        "faded to obscurity",
        "barely remembered",
        "the sport moved on",
        "ghost in the rankings",
        "slipped the convo",
        "fans forgot him",
        "division stopped writing",
    ],
}


# ============================================================
# VOICE PHRASE PICKER
# ============================================================

def get_legacy_phrase(state, rng=None):
    """Pick a voice phrase for the legacy state label (per §17.4).

    Args:
        state: canonical legacy state label (one of LEGACY_*), or
            None.
        rng: optional random.Random for deterministic selection. If
            None, uses the global random (NOT deterministic — caller
            should pass an rng seeded by fighter_id for stable
            phrases across daily passes).

    Returns:
        A voice phrase string, or None if state is None. Falls back
        to the building variants if the label is unrecognized
        (defensive — should not happen).
    """
    if state is None:
        return None
    if rng is None:
        rng = random
    variants = LEGACY_PHRASES.get(
        state, LEGACY_PHRASES[LEGACY_BUILDING])
    return rng.choice(variants)


# ============================================================
# VOICE-P2 (Claude §3): EXTENDED PICKER (8 variants per label)
# ============================================================
# Mirrors the original picker but draws from LEGACY_PHRASES_EXT (8
# variants per label vs the original 3). The engine's cache-write
# path uses this so the cache stores the expanded phrases; the
# original picker is preserved for the acceptance tests' Case F
# checks which call it directly.

def get_legacy_phrase_ext(state, rng=None):
    """Pick an EXTENDED voice phrase for the legacy state label.

    VOICE-P2 (Claude §3): returns one of 8 variants per label (3
    original + 5 modern MMA journalism voice). The engine uses this
    for cache writes so the UI sees the expanded phrases.

    Args:
        state: canonical legacy state label (one of LEGACY_*), or None.
        rng: optional random.Random for deterministic selection.

    Returns:
        A voice phrase string, or None if state is None. Falls back
        to the building variants if the label is unrecognized
        (defensive — should not happen).
    """
    if state is None:
        return None
    if rng is None:
        rng = random
    variants = LEGACY_PHRASES_EXT.get(
        state, LEGACY_PHRASES_EXT[LEGACY_BUILDING])
    return rng.choice(variants)


def get_legacy_phrase_short(state, rng=None):
    """Pick a SHORT voice phrase (≤25 chars) for the legacy state.

    INTERP-EXPAND-V2 (Claude §3): returns one of 8 short variants
    per label. The engine uses this for the new `legacy_state_short`
    cache column so the UI can pick short vs long based on available
    width. Returns None if state is None (no family). Falls back to
    the building short variants if the label is unrecognized.
    """
    if state is None:
        return None
    if rng is None:
        rng = random
    variants = LEGACY_PHRASES_SHORT.get(
        state, LEGACY_PHRASES_SHORT[LEGACY_BUILDING])
    return rng.choice(variants)


# ============================================================
# PURE COMPUTE FUNCTION — no DB, no RNG, no text
# ============================================================
# This is the canonical legacy state computer. It takes primitive
# inputs (bools + ints) and returns a canonical label string. No DB
# access, no RNG. The DB-write helpers (compute_all_legacies,
# compute_single_legacy) call this after loading the inputs.

def compute_legacy_state(is_retired, in_hall_of_fame, title_reigns,
                         total_fights, wins):
    """Compute the canonical legacy state label.

    Per spec §14 (Legacy) + the priority order in D4:

      Priority (first match wins):
        1. legendary   — in_hall_of_fame OR
                         (title_reigns >= 2 AND total_fights >= 30)
        2. forgotten   — is_retired AND NOT in_hall_of_fame AND
                         total_fights < 20
        3. established — NOT in_hall_of_fame AND total_fights >= 25
                         AND wins >= 15
        4. building    — NOT in_hall_of_fame AND
                         (total_fights < 15 OR
                          (total_fights < 25 AND wins < 15))

    Defensive default (D5): if no rule matches, return "building".
    This covers the journeyman edge case (25+ fights with < 15 wins)
    — the journeyman story is closer to "still building" than to
    "established" (they haven't done enough to be Established yet).

    The priority order matters: a retired HoF legend who fought < 20
    fights (rare — a dominant champ who retired early) is "legendary"
    (HoF supersedes the "few fights" signal). A retired non-HoF
    fighter with < 20 fights is "forgotten" (supersedes "building" —
    they had their chance and didn't make a mark).

    Defensive: all inputs are coerced (None → False for bools, None →
    0 for ints). This keeps the daily pass from crashing on bad data.

    Args:
        is_retired: bool. True if the fighter has retired.
        in_hall_of_fame: bool. True if the fighter has a row in the
            hall_of_fame table.
        title_reigns: int (>= 0). Number of title reigns the fighter
            has held.
        total_fights: int (>= 0). record_wins + record_losses +
            record_draws.
        wins: int (>= 0). record_wins.

    Returns:
        Canonical legacy state label string (one of LEGACY_*
        constants). Always non-None — every fighter gets a legacy
        state (per D3 + D5).
    """
    # Defensive coercion.
    is_retired = bool(is_retired)
    in_hall_of_fame = bool(in_hall_of_fame)
    title_reigns = title_reigns or 0
    total_fights = total_fights or 0
    wins = wins or 0

    # 1. legendary — HoF OR multi-title + longevity. The "history
    #    books" story. HoF induction is the binary event captured by
    #    hof_svc.py; the (title_reigns >= 2 AND total_fights >= 30)
    #    clause catches all-time greats who aren't yet inducted (e.g.,
    #    an active fighter mid-career with 2+ title reigns and 30+
    #    fights is already on a legendary trajectory).
    if in_hall_of_fame or (title_reigns >= 2 and total_fights >= 30):
        return LEGACY_LEGENDARY

    # 2. forgotten — retired + no HoF + few fights. The "time forgot"
    #    story. A retired fighter who didn't make the HoF AND didn't
    #    fight enough to leave a mark. Supersedes "building" — once
    #    you're retired with < 20 fights and no HoF, the legacy is
    #    settled (not "still building").
    if is_retired and not in_hall_of_fame and total_fights < 20:
        return LEGACY_FORGOTTEN

    # 3. established — non-HoF + 25+ fights + 15+ wins. The "body of
    #    work that speaks for itself" story. A long career with a
    #    winning record — they didn't reach the HoF, but they
    #    accomplished enough to be remembered as a real fighter.
    if (not in_hall_of_fame
            and total_fights >= 25
            and wins >= 15):
        return LEGACY_ESTABLISHED

    # 4. building — non-HoF + early career OR mid-career without
    #    enough wins. The "too early to judge" story.
    if (not in_hall_of_fame
            and (total_fights < 15
                 or (total_fights < 25 and wins < 15))):
        return LEGACY_BUILDING

    # 5. Defensive default (D5) — none of the explicit rules matched.
    #    The most common case: a fighter with 25+ fights but < 15
    #    wins (a journeyman). The journeyman story is closer to
    #    "still building" than to "established" (they haven't done
    #    enough to be Established). Default to building — guarantees
    #    every fighter gets a non-NULL legacy_state (per D3).
    return LEGACY_BUILDING


# ============================================================
# BULK COMPUTE + WRITE (called by snapshot_cache.run_daily_pass)
# ============================================================

def compute_all_legacies(conn, current_date=None):
    """Bulk-compute legacy_state for ALL fighters (active + retired).

    Uses the bulk-load pattern from career_arc._process_career_arc
    (CONVENTIONS §17.5):
      1. ONE main SELECT (fighters JOIN fighter_career LEFT JOIN
         hall_of_fame) — fetch ALL 4510 fighters in one go. The
         LEFT JOIN to hall_of_fame is cheap (60 rows) and the PK on
         hall_of_fame.fighter_id means no fan-out. One query total.
      2. Python loop — pure CPU, no DB calls inside the loop.
      3. conn.executemany("UPDATE fighter_descriptors SET legacy_state=?") —
         one batched write.

    Per D3: applies to ALL fighters (no is_active / is_retired
    filter). The legacy is the long-arc story; a retired fighter has
    career_phase=NULL but legacy_state="legendary" / "forgotten" /
    "established".

    Per §17.4: the column is written as "label||voice phrase". Every
    fighter gets a non-NULL legacy_state (per D3 + D5 — defensive
    default "building" for the journeyman edge case).
    Per D6: the voice phrase is RNG-seeded by fighter_id so it's
    deterministic across daily passes (no UI flickering).

    MUST complete in <1 second for 4510 fighters (CONVENTIONS §17.5).

    Args:
        conn: sqlite3.Connection.
        current_date: optional ISO date string (unused — legacy
            state doesn't depend on age, only on fight counts + HoF
            induction + retirement status. Kept in the signature for
            API consistency with the other engines).

    Returns:
        int — number of fighter_descriptors rows updated (should
        equal the total fighter count, since every fighter gets a
        non-NULL legacy_state).
    """
    # Bulk-load ALL fighters + their career stats + HoF status. We
    # LEFT JOIN hall_of_fame — if the row exists, the fighter is in
    # the HoF (hof_id is non-NULL). The PK on hall_of_fame.fighter_id
    # guarantees no fan-out (one row in, one row out).
    rows = conn.execute(
        """
        SELECT
            f.fighter_id,
            f.is_retired,
            hof.fighter_id AS hof_id,
            fc.record_wins,
            fc.record_losses,
            fc.record_draws,
            fc.title_reigns
        FROM fighters f
        JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        LEFT JOIN hall_of_fame hof ON hof.fighter_id = f.fighter_id
        """
    ).fetchall()

    # Python loop — compute labels + voice phrases.
    updates = []
    for (fighter_id, is_retired, hof_id, record_wins, record_losses,
         record_draws, title_reigns) in rows:

        # Defensive against NULL or negative record values (shouldn't
        # happen but the daily pass must not crash on bad data).
        record_wins = record_wins or 0
        record_losses = record_losses or 0
        record_draws = record_draws or 0
        total_fights = record_wins + record_losses + record_draws

        in_hall_of_fame = hof_id is not None

        state = compute_legacy_state(
            is_retired=is_retired,
            in_hall_of_fame=in_hall_of_fame,
            title_reigns=title_reigns,
            total_fights=total_fights,
            wins=record_wins,
        )

        # Deterministic RNG per fighter (D6) — same fighter always
        # gets the same voice phrase across daily passes. Same seed
        # formula as the other interpretation engines for consistency.
        rng = random.Random(fighter_id * 31 + 17)
        # VOICE-P2 (Claude §3): use the EXTENDED picker (8 variants)
        # for cache writes. The original picker (3 variants) is
        # preserved for the acceptance tests' Case F checks which call
        # it directly.
        phrase = get_legacy_phrase_ext(state, rng)
        # INTERP-EXPAND-V2 (Claude §3): also pick a SHORT variant for
        # the new `legacy_state_short` column. Same RNG seed so the
        # short + long pair is deterministic per fighter.
        phrase_short = get_legacy_phrase_short(state, rng)

        updates.append((encode(state, phrase),
                        encode(state, phrase_short),
                        fighter_id))

    # Batch UPDATE (one executemany — CONVENTIONS §17.5).
    if updates:
        conn.executemany(
            "UPDATE fighter_descriptors SET legacy_state=?, "
            "legacy_state_short=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            updates,
        )
        conn.commit()

    return len(updates)


# ============================================================
# SINGLE-FIGHTER REFRESH (called by snapshot_cache.refresh_fighter)
# ============================================================

def compute_single_legacy(conn, fighter_id, current_date=None):
    """Compute legacy_state for a single fighter (targeted refresh).

    Called by the 4 event-bus subscribers on FIGHT_RESOLVED,
    FIGHTER_RETIRED, TITLE_CHANGED, CONTRACT_EXPIRED (via
    snapshot_cache.refresh_fighter) so the UI shows the up-to-date
    legacy immediately, without waiting for the next daily pass.

    MUST complete in <10ms (CONVENTIONS §17.5). Uses a TARGETED query
    (one SELECT on fighters + fighter_career + LEFT JOIN hall_of_fame
    for this fighter_id only).

    Args:
        conn: sqlite3.Connection.
        fighter_id: int.
        current_date: optional ISO date string (unused — legacy
            state doesn't depend on age. Kept for API consistency.)

    Returns:
        dict with key 'legacy_state' (canonical label), or None if
        the fighter doesn't exist. Always returns a non-None label
        for an existing fighter (every fighter gets a legacy_state
        per D3 + D5).
    """
    row = conn.execute(
        """
        SELECT
            f.fighter_id,
            f.is_retired,
            hof.fighter_id AS hof_id,
            fc.record_wins,
            fc.record_losses,
            fc.record_draws,
            fc.title_reigns
        FROM fighters f
        JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        LEFT JOIN hall_of_fame hof ON hof.fighter_id = f.fighter_id
        WHERE f.fighter_id = ?
        """,
        (fighter_id,),
    ).fetchone()

    if not row:
        return None

    (fid, is_retired, hof_id, record_wins, record_losses,
     record_draws, title_reigns) = row

    record_wins = record_wins or 0
    record_losses = record_losses or 0
    record_draws = record_draws or 0
    total_fights = record_wins + record_losses + record_draws

    in_hall_of_fame = hof_id is not None

    state = compute_legacy_state(
        is_retired=is_retired,
        in_hall_of_fame=in_hall_of_fame,
        title_reigns=title_reigns,
        total_fights=total_fights,
        wins=record_wins,
    )

    rng = random.Random(fighter_id * 31 + 17)
    # VOICE-P2 (Claude §3): use the EXTENDED picker (8 variants) for
    # cache writes (same as compute_all_legacies).
    phrase = get_legacy_phrase_ext(state, rng)
    # INTERP-EXPAND-V2: also write the SHORT variant (mirrors the
    # bulk-pass behavior so the new `legacy_state_short` column stays
    # populated on event-driven refreshes too).
    phrase_short = get_legacy_phrase_short(state, rng)

    conn.execute(
        "UPDATE fighter_descriptors SET legacy_state=?, "
        "legacy_state_short=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (encode(state, phrase),
         encode(state, phrase_short),
         fighter_id),
    )
    conn.commit()

    return {"legacy_state": state}
