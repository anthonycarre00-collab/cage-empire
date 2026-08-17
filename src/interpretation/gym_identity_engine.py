"""Gym Identity Engine — populates gym_descriptors cache table.

Per CONVENTIONS §17.1 (Snapshot Rule), Office Mode UI screens must read
from `gym_descriptors` (the cache table), NOT from the `gyms`
simulation table directly. This engine is the ONLY writer to
`gym_descriptors`. It runs as part of the daily interpretation pass
(snapshot_cache.run_daily_interpretation_pass → _interpret_gyms →
compute_all_gym_descriptors) and is idempotent — INSERT OR REPLACE.

Per CONVENTIONS §14 (Voice Layer — no raw 0-100 numbers in player-
facing UI) + §17.1, the engine derives 5 voice-phrase fields from
the `gyms` table's raw 0-100 ratings + the gym's name (used to
infer a pseudo-specialty — striking/grappling/wrestling/mixed). The
fields:
  - identity_label           short label like "The Striking Lab"
  - known_for                voice phrase: what the gym is known for
  - produces                 voice phrase: fighter archetype produced
  - weakness                 voice phrase: what the gym lacks
  - development_rating_desc  voice phrase for facility_quality tier

Voice phrases follow the same tier system as the helpers in
`src/app_web.py`:
  - `_reputation_phrase(rep)` (app_web.py:210) — 80/60/40/20 tiers
  - `_gym_quality_phrase(quality)` (app_web.py:429) — 90/75/60/40/0
  - `_gym_culture_label(tone)` (app_web.py:462)

To keep this module self-contained (testable without booting the
web app — per the task spec recommendation), the tier thresholds
are COPIED here as constants + a `_tier_phrase` helper, with a
comment referencing the original helpers. If `app_web.py` ever
retunes its thresholds, update the constants below in tandem.

Per CONVENTIONS §17.5 (performance): the bulk-load pattern is used —
ONE SELECT fetches all ~329 gyms, a Python loop derives the 5 fields
per gym (pure CPU, no DB calls), and ONE `executemany` writes them.
Target: <50ms for 329 gyms (well under the <1s daily-pass budget).

Per CONVENTIONS §17.3: this module NEVER writes to simulation tables
(`gyms`, `fighters`, etc.). It writes ONLY to `gym_descriptors`.
"""
import random
import sqlite3


# ============================================================
# TIER CONSTANTS
# ============================================================
# Mirrors `app_web.py:_gym_quality_phrase` (90/75/60/40/0-39) for the
# 5-tier quality mapping, expanded to 6 tiers (adds 20-39 vs 0-19
# split) for richer `development_rating_desc` phrases per the task
# spec. The thresholds for the OTHER 5 ratings (reputation,
# medical_support, sparring_depth, development_focus,
# weight_cut_support) use the SAME 6-tier system for consistency.
#
# TIER_BOUNDARIES — ordered (threshold, tier_name) pairs, highest
# first. `_tier` walks this list and returns the first tier whose
# threshold the value meets/exceeds.
TIER_WORLD_CLASS = "world_class"  # 90-100
TIER_ELITE       = "elite"        # 75-89
TIER_SOLID       = "solid"        # 60-74
TIER_ADEQUATE    = "adequate"     # 40-59
TIER_POOR        = "poor"         # 20-39
TIER_ABYSMAL     = "abysmal"      # 0-19

TIER_BOUNDARIES = (
    (90, TIER_WORLD_CLASS),
    (75, TIER_ELITE),
    (60, TIER_SOLID),
    (40, TIER_ADEQUATE),
    (20, TIER_POOR),
    (0,  TIER_ABYSMAL),
)

# 3-tier bands for `known_for` + `produces` (simpler — those fields
# only need a high/mid/low split per the task spec examples).
#   HIGH  ≥75   elite / feared / elite-level
#   MID   40-74 solid / well-rounded / competent
#   LOW   <40   basic / teaches the basics / scrappy
TIER_HIGH = "high"
TIER_MID  = "mid"
TIER_LOW  = "low"


# ============================================================
# PSEUDO-SPECIALTY DERIVATION (from gym name keywords)
# ============================================================
# The `gyms` table has NO `specialty` column (the Phase 6 task spec
# assumed one). The actual differentiator on `gyms` is `culture_tone`
# (balanced / disciplined / loose / predator). For voice-phrase
# derivation we want a TRAINING-MODE specialty (striking / grappling
# / wrestling / mixed) — derived from the gym's NAME keyword scan.
#
# Priority order (first match wins — most specific first):
#   1. "BJJ" / "Jiu Jitsu" / "Grappling"  → grappling
#   2. "Wrestling"                         → wrestling
#   3. "Boxing" / "Muay Thai" / "Striking" → striking
#   4. "MMA" / "Mixed Martial Arts"        → mixed
#   5. (default)                           → mixed
# Keywords are matched case-insensitively as whole-word substrings
# (e.g., "Striking" matches "Bushi Striking" but not "Ironstrike").

_SPECIALTY_STRIKING  = "striking"
_SPECIALTY_GRAPPLING = "grappling"
_SPECIALTY_WRESTLING = "wrestling"
_SPECIALTY_MIXED     = "mixed"

# (keyword_lower, specialty) — first match wins.
_NAME_KEYWORD_PATTERNS = (
    ("bjj",              _SPECIALTY_GRAPPLING),
    ("jiu jitsu",        _SPECIALTY_GRAPPLING),
    ("grappling",        _SPECIALTY_GRAPPLING),
    ("submission",       _SPECIALTY_GRAPPLING),
    ("wrestling",        _SPECIALTY_WRESTLING),
    ("boxing",           _SPECIALTY_STRIKING),
    ("muay thai",        _SPECIALTY_STRIKING),
    ("striking",         _SPECIALTY_STRIKING),
    ("mma",              _SPECIALTY_MIXED),
    ("mixed martial",    _SPECIALTY_MIXED),
    ("combat sports",    _SPECIALTY_MIXED),
    ("mixed",            _SPECIALTY_MIXED),
)


def _derive_specialty(name):
    """Derive a pseudo-specialty (striking/grappling/wrestling/mixed)
    from the gym's NAME by keyword scan.

    The `gyms` table has no `specialty` column — the task spec assumed
    one. This helper infers one from gym-name keywords (e.g.,
    "Bushi Striking" → striking, "Summit Wrestling" → wrestling,
    "Black BJJ" → grappling, "Eagle MMA" → mixed).

    Args:
        name: gym name string (may be None / empty).

    Returns:
        one of "striking", "grappling", "wrestling", "mixed".
    """
    if not name:
        return _SPECIALTY_MIXED
    lname = name.lower()
    for keyword, specialty in _NAME_KEYWORD_PATTERNS:
        # Whole-word match (boundary check) so "mma" doesn't match
        # "gamma" or "summa". Use a simple char-before/after check
        # rather than regex for speed + to avoid regex metachar issues.
        idx = lname.find(keyword)
        while idx != -1:
            before = lname[idx - 1] if idx > 0 else " "
            after_idx = idx + len(keyword)
            after = lname[after_idx] if after_idx < len(lname) else " "
            # Word boundary: surrounding chars are non-alphanumeric.
            if (not before.isalnum()) and (not after.isalnum()):
                return specialty
            idx = lname.find(keyword, idx + 1)
    return _SPECIALTY_MIXED


# ============================================================
# TIER PHRASE HELPER
# ============================================================
def _tier(value, default=0):
    """Return the tier name for a 0-100 value (6-tier system).

    Mirrors the band logic of `app_web.py:_gym_quality_phrase` (which
    uses a 5-tier 90/75/60/40/0 system) but with a 6th band (20-39 vs
    0-19) for richer `development_rating_desc` phrases.

    Args:
        value:   int 0-100 (or None — treated as 0).
        default: fallback int if value is None / unparseable.

    Returns:
        one of TIER_WORLD_CLASS / TIER_ELITE / TIER_SOLID /
        TIER_ADEQUATE / TIER_POOR / TIER_ABYSMAL.
    """
    if value is None:
        v = default
    else:
        try:
            v = int(value)
        except (TypeError, ValueError):
            v = default
    v = max(0, min(100, v))
    for threshold, tier_name in TIER_BOUNDARIES:
        if v >= threshold:
            return tier_name
    return TIER_ABYSMAL  # defensive — v >= 0 always matches the last entry


def _tier_3(value):
    """Return HIGH / MID / LOW tier for a 0-100 value (3-band system).

    Used by `known_for` + `produces` — the task spec examples only
    distinguish 3 tiers (high-rep / mid-rep / low-rep).

    Args:
        value: int 0-100 (or None — treated as 0).

    Returns:
        TIER_HIGH (≥75) / TIER_MID (40-74) / TIER_LOW (<40).
    """
    if value is None:
        v = 0
    else:
        try:
            v = int(value)
        except (TypeError, ValueError):
            v = 0
    v = max(0, min(100, v))
    if v >= 75:
        return TIER_HIGH
    if v >= 40:
        return TIER_MID
    return TIER_LOW


# ============================================================
# IDENTITY LABEL — short label like "The Striking Lab"
# ============================================================
# Per task spec: SHORT label (≤6 words), not a phrase. Derived from
# pseudo-specialty. Fallback: the gym's actual name (if no specialty
# keyword matched, "mixed" is the default → use the actual name).
#
# The labels are deterministic per specialty — no RNG here. Two
# striking gyms get the same label "The Striking Lab" — the gym's
# actual NAME disambiguates them on the gyms screen (rendered
# alongside identity_label per the task spec wiring done in Task B4).

_IDENTITY_LABEL_BY_SPECIALTY = {
    _SPECIALTY_STRIKING:  "The Striking Lab",
    _SPECIALTY_GRAPPLING: "The Grappling Academy",
    _SPECIALTY_WRESTLING: "The Wrestling Room",
    _SPECIALTY_MIXED:     "The Complete Fighter Gym",
}


def _identity_label(specialty, name):
    """Short label like 'The Striking Lab'.

    Args:
        specialty: pseudo-specialty (striking/grappling/wrestling/mixed).
        name:      the gym's actual name (fallback if specialty unknown).

    Returns:
        short label string (≤6 words).
    """
    label = _IDENTITY_LABEL_BY_SPECIALTY.get(specialty)
    if label:
        return label
    # Defensive — unknown specialty falls back to the gym's actual
    # name (per task spec fallback rule).
    return (name or "The Gym").strip() or "The Gym"


# ============================================================
# KNOWN_FOR — voice phrase: what the gym is known for
# ============================================================
# Per task spec: 5-15 words, derived from specialty + reputation tier
# (3 tiers: high ≥75 / mid 40-74 / low <40). Each (specialty, tier)
# pair has 3 voice-phrase variants — RNG seeded by gym_id (per the
# convention established by context_engine + legacy_engine) so the
# same gym always gets the same phrase across daily passes (no UI
# flickering) but two gyms with the same specialty+reputation tier
# don't read identically.

_KNOWN_FOR_PHRASES = {
    _SPECIALTY_STRIKING: {
        TIER_HIGH: [
            "produces elite strikers feared across the division",
            "a reputation built on devastating knockout artists",
            "the camp where championship-level striking is forged",
        ],
        TIER_MID: [
            "develops solid striking fundamentals",
            "a reliable finishing school for stand-up specialists",
            "turns out competent, well-drilled boxers and kickers",
        ],
        TIER_LOW: [
            "teaches the basics of striking",
            "a grassroots gym where stance and form come first",
            "where novice fighters learn to throw a clean jab",
        ],
    },
    _SPECIALTY_GRAPPLING: {
        TIER_HIGH: [
            "produces elite grapplers who dominate on the mat",
            "a conveyor belt for submission specialists and ADCC hopefuls",
            "the region's premier destination for high-level jiu-jitsu",
        ],
        TIER_MID: [
            "develops solid ground fundamentals",
            "a steady producer of competent submission hunters",
            "turns out grapplers who can hold their own on the mat",
        ],
        TIER_LOW: [
            "teaches the basics of grappling",
            "where newcomers first learn to shrimp and bridge",
            "a grassroots gym building ground game from the ground up",
        ],
    },
    _SPECIALTY_WRESTLING: {
        TIER_HIGH: [
            "produces elite wrestlers who dictate where the fight goes",
            "a factory for Division-I-caliber takedown artists",
            "the camp that turns wrestlers into dominant MMA pressure fighters",
        ],
        TIER_MID: [
            "develops solid wrestling fundamentals",
            "a reliable producer of competent takedown artists",
            "turns out fighters who control the clinch and the cage",
        ],
        TIER_LOW: [
            "teaches the basics of wrestling",
            "where novices first learn to shoot a clean double-leg",
            "a grassroots gym building takedown defense from day one",
        ],
    },
    _SPECIALTY_MIXED: {
        TIER_HIGH: [
            "produces well-rounded fighters comfortable in every phase",
            "a factory for complete mixed-martial-artists",
            "the camp where contenders are built, not just trained",
        ],
        TIER_MID: [
            "develops well-rounded fundamentals across all disciplines",
            "a steady producer of competent all-phase fighters",
            "turns out athletes who can strike, grapple, and wrestle",
        ],
        TIER_LOW: [
            "teaches the basics of mixed martial arts",
            "where first-timers learn the building blocks of MMA",
            "a grassroots gym giving new fighters a solid foundation",
        ],
    },
}


def _known_for(specialty, reputation, rng):
    """Voice phrase: what the gym is known for.

    Args:
        specialty:  pseudo-specialty (striking/grappling/wrestling/mixed).
        reputation: 0-100 reputation int.
        rng:        random.Random instance (seeded by gym_id — caller
                    passes it in so the seed convention lives in ONE
                    place: the bulk-load loop).

    Returns:
        voice phrase string (5-15 words).
    """
    tier = _tier_3(reputation)
    phrases = _KNOWN_FOR_PHRASES.get(specialty) or \
              _KNOWN_FOR_PHRASES[_SPECIALTY_MIXED]
    variants = phrases.get(tier) or phrases[TIER_MID]
    return rng.choice(variants)


# ============================================================
# PRODUCES — voice phrase: fighter archetype produced
# ============================================================
# Per task spec: voice phrase for the fighter archetype the gym tends
# to produce, derived from specialty + development_focus (3 tiers:
# high ≥75 / mid 40-74 / low <40). 3 variants per (specialty, tier)
# pair — RNG seeded by gym_id (same convention as _known_for).

_PRODUCES_PHRASES = {
    _SPECIALTY_STRIKING: {
        TIER_HIGH: [
            "technical kickboxers with elite footwork",
            "pressure strikers who fight behind a stiff jab",
            "muay thai specialists with fight-ending elbows and knees",
        ],
        TIER_MID: [
            "well-rounded strikers",
            "competent boxers who mix kicks effectively",
            "steady-handed kickboxers with solid cage IQ",
        ],
        TIER_LOW: [
            "brawlers who rely on power",
            "scrappy stand-up fighters who wing overhands",
            "raw-handed strikers still learning to keep their guard up",
        ],
    },
    _SPECIALTY_GRAPPLING: {
        TIER_HIGH: [
            "submission hunters with elite guard passing",
            "back-takers who finish fights from rear mount",
            "high-level grapplers who chain submissions fluidly",
        ],
        TIER_MID: [
            "grapplers with competent top control",
            "ground-and-pound artists who work from side control",
            "submission-aware fighters who can win on the mat",
        ],
        TIER_LOW: [
            "grapplers who muscle out of bad positions",
            "raw ground fighters who survive more than they threaten",
            "blue-collar mat workers still learning submission setups",
        ],
    },
    _SPECIALTY_WRESTLING: {
        TIER_HIGH: [
            "elite wrestlers with chain-wrestling pedigrees",
            "takedown artists who grind opponents against the cage",
            "Division-I wrestlers who dictate every exchange",
        ],
        TIER_MID: [
            "competent wrestlers who control where the fight goes",
            "clinch-friendly fighters who mix takedowns into their game",
            "ground-and-pound wrestlers who win the positional battle",
        ],
        TIER_LOW: [
            "raw wrestlers who spam doubles",
            "grinders who muscle opponents down without setup",
            "stamina-first wrestlers still learning to chain their shots",
        ],
    },
    _SPECIALTY_MIXED: {
        TIER_HIGH: [
            "complete fighters who threaten in every phase",
            "well-rounded contenders with no obvious weaknesses",
            "versatile athletes who blend striking, wrestling, and grappling",
        ],
        TIER_MID: [
            "well-rounded fighters with a competent baseline in every phase",
            "balanced rosters who can win striking or grappling exchanges",
            "steady all-phase athletes with no glaring holes",
        ],
        TIER_LOW: [
            "raw all-rounders still figuring out their identity",
            "jacks-of-all-trades who haven't mastered anything yet",
            "generalists learning to put the pieces together",
        ],
    },
}


def _produces(specialty, development_focus, rng):
    """Voice phrase: the fighter archetype the gym produces.

    Args:
        specialty:          pseudo-specialty.
        development_focus:  0-100 development_focus int.
        rng:                random.Random instance (gym_id-seeded).

    Returns:
        voice phrase string.
    """
    tier = _tier_3(development_focus)
    phrases = _PRODUCES_PHRASES.get(specialty) or \
              _PRODUCES_PHRASES[_SPECIALTY_MIXED]
    variants = phrases.get(tier) or phrases[TIER_MID]
    return rng.choice(variants)


# ============================================================
# WEAKNESS — voice phrase for the gym's weakest aspect
# ============================================================
# Per task spec: find the WEAKEST of the 6 ratings (reputation,
# facility_quality, medical_support, sparring_depth,
# development_focus, weight_cut_support). If the weakest is <40,
# return the matching voice phrase. If all 6 ratings are ≥40, return
# "no glaring weakness — a well-rounded operation".
#
# Tie-breaking: when two ratings tie at the minimum, the FIRST one
# in the iteration order wins (we iterate in the priority order
# below — medical_support, sparring_depth, weight_cut_support,
# facility_quality, development_focus, reputation — to surface the
# most actionable weakness first; medical/sparring/weight-cut
# weaknesses are more visible to players than facility/dev ones).
#
# Voice phrases per rating (the "weakness <40" case):
#   medical_support      → "medical support leaves fighters recovering on their own"
#   sparring_depth       → "sparring partners are scarce, limiting live drilling"
#   weight_cut_support   → "weight cuts are largely DIY, risky for big fights"
#   facility_quality     → "facilities are aging and under-equipped"
#   development_focus    → "training lacks structure, fighters plateau early"
#   reputation           → "the gym's reputation hasn't drawn serious talent"

# Iteration order — most actionable weakness first (matches task spec
# order). When two ratings tie at the minimum, this order decides.
_WEAKNESS_RATINGS_ORDER = (
    ("medical_support",    "medical support leaves fighters recovering on their own"),
    ("sparring_depth",     "sparring partners are scarce, limiting live drilling"),
    ("weight_cut_support", "weight cuts are largely DIY, risky for big fights"),
    ("facility_quality",   "facilities are aging and under-equipped"),
    ("development_focus",  "training lacks structure, fighters plateau early"),
    ("reputation",         "the gym's reputation hasn't drawn serious talent"),
)

# Phrase for the "all ratings ≥40" case — the gym has no glaring
# weakness. RNG-seeded variant pick so two well-rounded gyms don't
# read identically (same convention as _known_for / _produces).
_NO_GLARING_WEAKNESS_PHRASES = (
    "no glaring weakness — a well-rounded operation",
    "a complete camp with no obvious holes in the toolkit",
    "well-equipped across the board, no red flags to flag",
    "solid in every phase — a balanced, professional outfit",
)


def _weakness(ratings, rng):
    """Voice phrase for the gym's weakest aspect.

    Args:
        ratings: dict of {rating_name: 0-100 int} — must contain all
                 6 keys (reputation, facility_quality, medical_support,
                 sparring_depth, development_focus, weight_cut_support).
        rng:     random.Random instance (gym_id-seeded — used only for
                 the "no glaring weakness" case to pick a variant).

    Returns:
        voice phrase string.
    """
    # Find the minimum rating across the 6 dimensions, in priority
    # order (so ties break toward the most-actionable weakness).
    min_val = None
    min_phrase = None
    for name, phrase in _WEAKNESS_RATINGS_ORDER:
        val = ratings.get(name, 50)
        if val is None:
            val = 50
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = 50
        if min_val is None or val < min_val:
            min_val = val
            min_phrase = phrase

    # If the weakest rating is below the 40-tier threshold, return
    # its weakness phrase. Otherwise the gym is well-rounded.
    if min_val is not None and min_val < 40:
        return min_phrase
    return rng.choice(_NO_GLARING_WEAKNESS_PHRASES)


# ============================================================
# DEVELOPMENT_RATING_DESC — facility_quality tier voice phrase
# ============================================================
# Per task spec: voice phrase for facility_quality tier. Uses the
# same tier thresholds as `app_web.py:_gym_quality_phrase` (5-tier
# 90/75/60/40/0), expanded with a 6th band (20-39 vs 0-19) for richer
# description per the task spec's exact 6-phrase list:
#   90-100 → "world-class facility, the gold standard"
#   75-89  → "elite facilities that rival any major camp"
#   60-74  → "solid facilities that meet professional standards"
#   40-59  → "adequate facilities with room to grow"
#   20-39  → "below-average facilities that limit development"
#   0-19   → "bare-bones facilities, a hand-to-mouth operation"
#
# The phrases are DETERMINISTIC per tier (no RNG) — they're short,
# and the same gym with the same facility_quality should always
# read the same (matching `_gym_quality_phrase`'s deterministic
# behavior in app_web.py).

_DEV_RATING_BY_TIER = {
    TIER_WORLD_CLASS: "world-class facility, the gold standard",
    TIER_ELITE:       "elite facilities that rival any major camp",
    TIER_SOLID:       "solid facilities that meet professional standards",
    TIER_ADEQUATE:    "adequate facilities with room to grow",
    TIER_POOR:        "below-average facilities that limit development",
    TIER_ABYSMAL:     "bare-bones facilities, a hand-to-mouth operation",
}


def _development_rating_desc(facility_quality):
    """Voice phrase for facility_quality tier.

    Args:
        facility_quality: 0-100 int.

    Returns:
        voice phrase string (one of 6 deterministic phrases).
    """
    return _DEV_RATING_BY_TIER[_tier(facility_quality)]


# ============================================================
# ENGINE_VERSION helper — read interpretation_cache_meta
# ============================================================
# Per task spec: read interpretation_cache_meta.engine_version
# (currently "1.10.0" after the snapshot_cache.ENGINE_VERSION bump
# in this same task). Store as integer.
#
# Convention (matches fighter_descriptors.snapshot_version): the
# cache table's snapshot_version is an INCREMENTING COUNTER —
# `COALESCE((SELECT snapshot_version + 1 ...), 1)` — that ticks
# on every refresh. We follow the same pattern via SQL rather than
# reading engine_version into Python. This keeps the snapshot_
# version meaningful as a "how many times has this gym been
# re-interpreted" counter — consistent with fighter_descriptors.
#
# Reading interpretation_cache_meta.engine_version into a separate
# Python variable is NOT needed because the SQL COALESCE pattern
# handles the increment + initial-value cases atomically. The
# engine_version mismatch check (snapshot_cache._should_full_rebuild)
# already triggers a full cache rebuild when ENGINE_VERSION bumps,
# which is the actual cache-invalidation signal — snapshot_version
# is just a per-row monotonic counter, not a version stamp.


# ============================================================
# PUBLIC API
# ============================================================
def compute_all_gym_descriptors(conn, current_date=None):
    """Populate `gym_descriptors` for all gyms.

    Per CONVENTIONS §17.5 (performance): uses the bulk-load pattern —
    ONE SELECT fetches all gyms + their 6 ratings + culture_tone +
    name. A Python loop derives the 5 voice-phrase fields per gym
    (pure CPU, no DB calls). ONE `executemany` writes the rows via
    INSERT OR REPLACE (idempotent — safe to re-run on the same date
    or across daily passes).

    Per CONVENTIONS §17.1: this is the ONLY writer to gym_descriptors.
    It writes ONLY to gym_descriptors — never to `gyms` (simulation
    table) or any other table.

    Per CONVENTIONS §17.3: the engine is idempotent. Re-running for
    the same date overwrites the existing rows (INSERT OR REPLACE).
    Re-running across daily passes is the normal usage pattern (the
    daily interpretation pass calls this once per tick).

    Args:
        conn:         sqlite3.Connection.
        current_date: ISO date string (unused — gym identity doesn't
                      depend on the sim date. Kept for API symmetry
                      with the other interpretation sub-engines which
                      DO take current_date: context_engine, career_
                      phase_engine, etc. The signature is fixed by
                      snapshot_cache._interpret_gyms which calls this
                      with (conn, current_date).).

    Returns:
        int — number of gym_descriptors rows written.
    """
    # ----------------------------------------------------------------
    # 1. ONE SELECT — fetch all gyms + their 6 ratings + name +
    #    culture_tone. The gyms table has ~329 rows so this is cheap.
    # ----------------------------------------------------------------
    rows = conn.execute(
        """
        SELECT g.gym_id, g.name,
               g.reputation, g.facility_quality, g.medical_support,
               g.sparring_depth, g.development_focus,
               g.weight_cut_support, g.culture_tone
        FROM gyms g
        ORDER BY g.gym_id
        """
    ).fetchall()

    if not rows:
        # No gyms in DB — nothing to do (defensive; should never
        # happen in a real game but keeps the engine crash-safe on
        # a fresh/test DB).
        return 0

    # ----------------------------------------------------------------
    # 2. Python loop — derive the 5 voice-phrase fields per gym.
    #    Pure CPU — no DB calls inside the loop.
    #
    #    RNG seed convention (per D6 from legacy_engine.py): each
    #    gym's RNG is seeded by `gym_id * 31 + 17` so the same gym
    #    always gets the same phrase variants across daily passes
    #    (no UI flickering). Same formula as the fighter engines
    #    for consistency across the interpretation layer.
    # ----------------------------------------------------------------
    rows_to_write = []
    for r in rows:
        (gym_id, name, reputation, facility_quality, medical_support,
         sparring_depth, development_focus, weight_cut_support,
         culture_tone) = r

        # Derive pseudo-specialty from gym name (the gyms table has
        # no `specialty` column — see _derive_specialty docstring).
        specialty = _derive_specialty(name)

        # Deterministic RNG per gym (D6 convention).
        rng = random.Random((gym_id or 0) * 31 + 17)

        # Derive the 5 voice-phrase fields.
        identity_label = _identity_label(specialty, name)
        known_for = _known_for(specialty, reputation, rng)
        produces = _produces(specialty, development_focus, rng)
        weakness = _weakness({
            "reputation":         reputation,
            "facility_quality":   facility_quality,
            "medical_support":    medical_support,
            "sparring_depth":     sparring_depth,
            "development_focus":  development_focus,
            "weight_cut_support": weight_cut_support,
        }, rng)
        development_rating_desc = _development_rating_desc(facility_quality)

        rows_to_write.append((
            gym_id,
            identity_label,
            known_for,
            produces,
            weakness,
            development_rating_desc,
        ))

    # ----------------------------------------------------------------
    # 3. ONE executemany — INSERT OR REPLACE into gym_descriptors.
    #    snapshot_version follows the fighter_descriptors convention:
    #    COALESCE((SELECT snapshot_version + 1 ...), 1) so it ticks
    #    on every refresh (1 on first write, 2/3/... on subsequent).
    #    updated_at uses the SQL CURRENT_TIMESTAMP function (not a
    #    Python datetime) so the timestamp is consistent with the
    #    rest of the interpretation layer's writes.
    # ----------------------------------------------------------------
    conn.executemany(
        """
        INSERT OR REPLACE INTO gym_descriptors
            (gym_id, identity_label, known_for, produces,
             weakness, development_rating_desc,
             snapshot_version, updated_at)
        VALUES (?, ?, ?, ?, ?, ?,
                COALESCE((SELECT snapshot_version + 1
                          FROM gym_descriptors
                          WHERE gym_id = ?), 1),
                CURRENT_TIMESTAMP)
        """,
        # Bind 6 fields + gym_id twice (once for the INSERT VALUES,
        # once for the COALESCE subquery's WHERE clause).
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[0]) for r in rows_to_write],
    )
    conn.commit()

    return len(rows_to_write)
