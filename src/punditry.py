"""CAGE EMPIRE Punditry System (Task 24, refined Phase A — A9).

Matchup analysis (the pundit's pre-fight prediction for a fighter
pair), entirely event-bus-driven (Task 18.5). Subscribes to
FIGHT_RESOLVED and writes voice-layer-driven analysis rows to the
`matchup_analyses` table (added in v3.3.0).

CONVENTIONS compliance:
  §13 — Design Law: every analysis tells a story. The pundit doesn't
        say "fighter A has 78 punch_power and fighter B has 42 chin"
        — the pundit says "the striker has the edge on the feet —
        Reed's questionable takedown defense could be his undoing."
        Strengthens Conflict (the matchup is the conflict to come)
        and Anticipation (the player sees the pundit's prediction
        before the fight and wants to see if the pundit was right).
  §14 — Voice Layer: NO raw attribute values, potential numbers, or
        internal ratings appear in any player-facing analysis text.
        Fighter attributes are described via voice.describe_attribute
        (top-2 descriptors per fighter); career stage via voice.
        describe_career_stage. Confidence and excitement are stored
        as 0-100 INTEGER columns (the pundit's own rating, not a
        fighter attribute), but the analysis_text uses word forms
        ("Confidence: moderate" / "Expect fireworks") — no digit
        characters anywhere in the prose.
  §15 — Event Bus: the punditry system is entirely event-driven. It
        subscribes to FIGHT_RESOLVED published by resolve_next_fight;
        no new inline side effects are added to that function
        (§15.4). The existing side effects remain untouched.

PRE-FIGHT vs POST-FIGHT TIMING (A9):
  The brief considered generating the analysis BEFORE the fight
  resolves (publishing a new FIGHT_ABOUT_TO_START event from
  resolve_next_fight's start). The pragmatic approach (chosen for
  A9) keeps the FIGHT_RESOLVED subscriber — the analysis is still
  generated using pre-fight data, because:

    1. fighter_attributes is NOT updated by resolve_next_fight — the
       beat engine reads attributes, it doesn't write them. So the
       attribute descriptors in the analysis reflect the true pre-
       fight state. The predicted_winner + style_edge + excitement
       score + upset risk are all computed from fighter_attributes,
       so they reflect the pre-fight matchup.
    2. fighter_career IS updated by resolve_next_fight (record_wins/
       losses, streaks, career_health) — the career stage descriptor
       reflects slightly-post-fight state. This is the minor drift
       the existing comment notes. A fighter whose win streak
       crosses a band boundary (e.g., 4→5 wins) might see their
       career stage shift from "contender" to "rising contender",
       but the pundit's take doesn't materially change.
    3. fighter_personality is updated by the morale system (Phase
       A1) — but only the `morale` column. The pundit doesn't use
       morale (it uses aggression, composure, killer_instinct —
       none of which are updated post-fight by the morale system).
       So the personality-driven analysis (excitement score from
       aggression + killer_instinct, etc.) reflects pre-fight state.

  Net effect: the analysis reads as "here's what the pundits thought
  going in" — attribute-accurate, with a one-fight-of-drift on the
  career stage. Acceptable per the brief. A future task could
  publish FIGHT_ABOUT_TO_START and migrate the subscriber to it;
  the current approach is a deliberate pragmatic choice.

  The registration order in app.py's App.__init__ places the
  punditry subscriber BEFORE the morale subscriber — so on
  FIGHT_RESOLVED, the punditry subscriber runs first (reading the
  pre-morale-change state). The morale subscriber then runs and
  applies the win/loss morale swings. This minimizes the post-fight
  drift the pundit sees.

ANALYSIS LOGIC:
  Predicted winner — compare avg of 5 key attributes
    (punch_power, cardio, fight_iq, chin, takedown_offense) for
    both fighters. Higher avg = predicted winner. Gaussian noise
    (σ=10) added to simulate pundit uncertainty.
  Predicted method — based on both fighters' style archetypes.
    Striker vs Striker → "KO/TKO". Grappler vs Striker →
    "submission or KO". Wrestler vs anyone → "decision".
    Submission Specialist vs anyone → "submission". Other combos
    → "decision or late finish".
  Confidence — 50-90% based on the attribute gap. Small gap =
    50-60%, large gap = 80-90%. Stored as confidence_pct (INTEGER
    0-100). Text uses word forms ("moderate", "strong").
  Style edge — voice descriptor for who has the edge where
    ("the striker has the edge on the feet" / "the wrestler
    dominates on the ground").
  Excitement score — based on both fighters' aggression +
    punch_power + killer_instinct. High = "fireworks expected".
    Low = "technical affair". Stored as excitement_score (INTEGER
    0-100). Text uses word forms.
  Upset risk — if the underdog has high potential or a style that
    matches up well, "upset alert". Stored as upset_risk (TEXT
    phrase). Text uses word forms ("real", "possible", "low").
  Analysis text — full prose analysis using voice descriptors. NO
    raw numbers (§14). The pundit's pre-fight breakdown.

USAGE:
  from punditry import register_subscribers
  register_subscribers()  # call once at startup (UI / tests)

  # The system automatically processes FIGHT_RESOLVED via the bus.
  # Readers:
  from punditry import get_matchup_analysis, get_recent_analyses
  row = get_matchup_analysis(conn, fighter_a_id, fighter_b_id,
                              fight_id)
  rows = get_recent_analyses(conn, fighter_id, limit=10)

The system is ADDITIVE — existing inline side effects in
resolve_next_fight remain untouched (§15.4)."""

import random
from datetime import datetime

from voice import (
    describe_attribute,
    describe_career_stage,
    describe_personality,
    _tier_for,
)


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# All 25 attribute names — matches the column order in
# fighter_attributes (see build_db.py).
_ATTR_NAMES = [
    "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
    "head_movement", "footwork", "clinch_striking", "clinch_offense",
    "clinch_defense", "takedown_offense", "takedown_defense",
    "top_control", "bottom_game", "submission_offense",
    "submission_defense", "scramble_ability", "cage_wrestling",
    "cardio", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "fight_iq", "chin", "adaptability",
]

# The 5 key attributes the pundit weights for the predicted-winner
# comparison (per the brief). Higher avg = predicted winner.
_KEY_ATTRS = (
    "punch_power", "cardio", "fight_iq", "chin", "takedown_offense",
)

# Gaussian noise σ (per the brief: "Gaussian noise (±10) to simulate
# pundit uncertainty"). random.gauss(0, 10) gives roughly ±10 68% of
# the time, ±20 95% of the time — simulating the pundit's blind spots.
_PUNDIT_NOISE_SIGMA = 10.0

# Confidence range (per the brief: "50-90% based on the attribute gap.
# Small gap = 50-60%, large gap = 80-90%.").
_CONF_MIN = 50
_CONF_MAX = 90

# Excitement score range (0-100 — schema CHECK). The excitement score
# is computed from both fighters' aggression + punch_power +
# killer_instinct, averaged across both fighters.
_EXCITEMENT_MIN = 0
_EXCITEMENT_MAX = 100

# Style archetype name → noun phrase (mirrors voice._ARCHETYPE_NOUN).
# Used in style_edge text and method lookup.
_ARCHETYPE_NOUN = {
    "Balanced":              "well-rounded fighter",
    "Striker":               "striker",
    "Grappler":              "grappler",
    "Wrestler":              "wrestler",
    "Brawler":               "brawler",
    "Counter-Striker":       "counter-striker",
    "Submission Specialist": "submission specialist",
}

# Style archetype name → short adjective form for style_edge text
# ("the striker has the edge on the feet" / "the wrestler dominates
# on the ground"). Falls back to "fighter" for unknown archetypes.
_ARCHETYPE_ADJ = {
    "Balanced":              "well-rounded",
    "Striker":               "striker",
    "Grappler":              "grappler",
    "Wrestler":              "wrestler",
    "Brawler":               "brawler",
    "Counter-Striker":       "counter-striker",
    "Submission Specialist": "submission artist",
}


# ----------------------------------------------------------------
# Word-form helpers (CONVENTIONS §14 — no digit characters)
# ----------------------------------------------------------------

def _confidence_word(pct, rng=None):
    """Convert a 0-100 confidence_pct to a word form.

    Per the brief: 80-90 = strong/high, 65-79 = moderate/solid,
    50-64 = guarded/cautious, <50 = low/shaky. The example in the
    brief uses "moderate" — the most common word form.
    """
    if rng is None:
        rng = random
    if pct >= 80:
        return rng.choice(["strong", "high", "firm"])
    if pct >= 65:
        return rng.choice(["moderate", "solid", "measured"])
    if pct >= 50:
        return rng.choice(["guarded", "cautious", "tepid"])
    return rng.choice(["low", "shaky", "uncertain"])


def _excitement_phrase(score, rng=None):
    """Convert a 0-100 excitement_score to a word-form phrase.

    Returns a full phrase like "Expect fireworks" or "Expect a
    technical affair". Used as the excitement_clause slot in the
    analysis_text template (no digit characters per §14).
    """
    if rng is None:
        rng = random
    if score >= 80:
        return rng.choice([
            "Expect fireworks",
            "Buckle up — fireworks written all over this one",
            "Get ready for explosions",
        ])
    if score >= 65:
        return rng.choice([
            "Expect an action-packed affair",
            "Should be a lively one",
            "Both men come to fight",
        ])
    if score >= 45:
        return rng.choice([
            "Expect a measured affair",
            "A tactical battle is likely",
            "Pace will be controlled",
        ])
    return rng.choice([
        "Expect a technical affair",
        "A patient, tactical battle is likely",
        "Don't expect a slugfest",
    ])


def _betting_odds_phrase(confidence_pct, upset_risk_level, rng=None):
    """Phase C — convert confidence_pct + upset_risk_level to a
    voice-driven betting-odds phrase.

    Per the Phase C brief:
      confidence 90%+ → "heavy favorite"
      confidence 75-89% → "clear favorite"
      confidence 60-74% → "slight favorite"
      confidence 50-59% → "pick'em"
      upset_risk 'high' → "upset alert"

    The odds are expressed in CAGE EMPIRE voice, NOT as raw numbers:
      "Vale is the heavy favorite"  not  "Vale 1/5"
      "This one's a coin flip"      not  "50/50"
      "Reed is a live underdog"     not  "Reed 3/1"

    The function returns a SHORT phrase (no fighter name — the caller
    will prepend the favorite's name in the analysis_text). The
    upset_risk_level 'high' case overrides the confidence-based
    phrase (an "upset alert" is the more important signal — the
    player needs to know the underdog has a real chance).

    Args:
        confidence_pct: 0-100 INTEGER (the pundit's confidence in
            the predicted winner). Used to pick the favorite tier.
        upset_risk_level: 'high' / 'moderate' / 'low'. If 'high',
            the function returns an "upset alert" phrase instead
            of the confidence-based favorite phrase.
        rng: optional random.Random for variant selection.

    Returns:
        A short phrase like "the heavy favorite" / "a clear favorite"
        / "the slight favorite" / "a coin flip" / "a live underdog".
        NO digit characters per §14.
    """
    if rng is None:
        rng = random
    # Upset alert overrides the confidence-based phrase. The underdog
    # has a real chance — the player should hear "live underdog"
    # rather than "slight favorite".
    if upset_risk_level == "high":
        return rng.choice([
            "a live underdog", "a real threat to spring the upset",
            "genuine upset material",
        ])
    if confidence_pct >= 90:
        return rng.choice([
            "the heavy favorite", "an overwhelming favorite",
            "a massive favorite",
        ])
    if confidence_pct >= 75:
        return rng.choice([
            "the clear favorite", "a solid favorite",
            "a comfortable favorite",
        ])
    if confidence_pct >= 60:
        return rng.choice([
            "the slight favorite", "a narrow favorite",
            "a slight edge",
        ])
    # 50-59% — pick'em / coin flip.
    return rng.choice([
        "a coin flip", "pick'em", "a toss-up",
        "even money", "too close to call",
    ])


def _betting_odds_sentence(favorite_last, underdog_last, odds_phrase,
                            rng=None):
    """Phase C — build a full betting-odds sentence for the analysis.

    Combines the favorite's (or underdog's) last name with the odds
    phrase to form a sentence like:
      "Vale is the heavy favorite."
      "This one's a coin flip."
      "Reed is a live underdog."

    The sentence is voice-layer-driven — NO raw odds numbers per §14.
    Used as a separate sentence appended to the analysis_text (so
    the betting odds are clearly visible in the news feed).

    Args:
        favorite_last: the favorite's last name (used when odds_phrase
            is a favorite-tier phrase like "the heavy favorite").
        underdog_last: the underdog's last name (used when odds_phrase
            is an underdog phrase like "a live underdog").
        odds_phrase: the phrase returned by _betting_odds_phrase.
        rng: optional random.Random.
    """
    if rng is None:
        rng = random
    if odds_phrase in ("a coin flip", "pick'em", "a toss-up",
                        "even money", "too close to call"):
        # Pick'em phrasing — doesn't name a favorite.
        return rng.choice([
            f"This one's {odds_phrase} — too close to call on paper.",
            f"On paper, it's {odds_phrase}. The oddsmakers are split.",
            f"The betting line says {odds_phrase} — neither fighter "
            f"is a clear pick.",
        ])
    if "underdog" in odds_phrase or "upset" in odds_phrase:
        # Underdog phrasing — names the UNDERDOG (not the favorite).
        return rng.choice([
            f"But {underdog_last} is {odds_phrase} — don't sleep on the upset.",
            f"Still, {underdog_last} is {odds_phrase} — the upset is live.",
            f"That said, {underdog_last} is {odds_phrase} — the upset "
            f"alert is real.",
        ])
    # Favorite phrasing — names the favorite.
    return rng.choice([
        f"{favorite_last} is {odds_phrase} on the betting line.",
        f"The oddsmakers have {favorite_last} as {odds_phrase}.",
        f"On paper, {favorite_last} is {odds_phrase}.",
        f"The betting line favors {favorite_last} — {odds_phrase}, "
        f"by the numbers.",
    ])


def _upset_phrase(risk_level, rng=None):
    """Convert a risk level ('high'/'moderate'/'low') to a word form.

    Returns a single word used in the "Upset risk: {word}." sentence.
    Mirrors the brief example: "Upset risk: real."
    """
    if rng is None:
        rng = random
    if risk_level == "high":
        return rng.choice(["real", "genuine", "live", "significant"])
    if risk_level == "moderate":
        return rng.choice(["possible", "moderate", "worth watching"])
    return rng.choice(["low", "slim", "minimal"])


def _article_for(word):
    """Return 'an' if word starts with a vowel sound, else 'a'.

    Same heuristic as news._article_for — covers the common cases in
    voice.describe_career_stage (e.g., "an elite champion", "a reigning
    champion"). Not perfect for unusual cases but good enough for
    punditry prose.
    """
    if not word:
        return "a"
    first = word[0].lower()
    if first in "aeiou":
        return "an"
    return "a"


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


def _fighter_last_name(conn, fighter_id):
    """Return just the fighter's last name (for in-prose mentions)."""
    if fighter_id is None:
        return "Unknown"
    row = conn.execute(
        "SELECT last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else "Unknown"


def _fighter_age(conn, fighter_id, current_date=None):
    """Compute a fighter's age based on DOB and a reference date.

    If current_date is None, falls back to the simulation_clock's
    current_date (qualified column to avoid the SQLite quirk per
    CONVENTIONS §Z.6).
    """
    if fighter_id is None:
        return 30
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
    """Return the fighter's career stage descriptor (voice layer).

    Uses voice.describe_career_stage with the fighter's observable
    state (age, record, champion status, streaks). Does NOT reveal
    hidden potential.
    """
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


def _fighter_style_archetype_name(conn, fighter_id):
    """Return the fighter's style archetype name (e.g., 'Striker').

    Returns 'Balanced' as a defensive fallback if the fighter has no
    archetype or the archetype row is missing.
    """
    if fighter_id is None:
        return "Balanced"
    row = conn.execute(
        "SELECT sa.name FROM fighters f "
        "LEFT JOIN style_archetypes sa "
        "  ON sa.style_archetype_id = f.fight_style_archetype_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] else "Balanced"


def _fighter_attribute_block(conn, fighter_id):
    """Return a dict of {attr_name: value} for the fighter's 25 attrs.

    Returns an empty dict if the fighter has no fighter_attributes
    row (defensive — shouldn't happen for any real fighter, but the
    callers handle it).
    """
    if fighter_id is None:
        return {}
    cols_sql = ", ".join(_ATTR_NAMES)
    row = conn.execute(
        f"SELECT {cols_sql} FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return {}
    return {name: (val if val is not None else 50)
            for name, val in zip(_ATTR_NAMES, row)}


def _fighter_personality_block(conn, fighter_id):
    """Return a dict of {trait_name: value} for the fighter's 20 traits."""
    if fighter_id is None:
        return {}
    row = conn.execute(
        "SELECT aggression, composure, morale, risk_taking, "
        "killer_instinct, grit, discipline, patience, ambition, "
        "loyalty, charisma, attention_seeking, coachability, "
        "professionalism, ego, resilience, sportsmanship, "
        "travel_comfort, focus, fatigue_tolerance "
        "FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return {}
    keys = (
        "aggression", "composure", "morale", "risk_taking",
        "killer_instinct", "grit", "discipline", "patience",
        "ambition", "loyalty", "charisma", "attention_seeking",
        "coachability", "professionalism", "ego", "resilience",
        "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance",
    )
    return {k: (v if v is not None else 50) for k, v in zip(keys, row)}


def _fighter_potential(conn, fighter_id):
    """Return the fighter's potential (0-100) or 50 as defensive default.

    NOTE: potential is HIDDEN from the player per the voice layer
    directive (§14). The punditry system uses potential INTERNALLY to
    compute upset_risk (an underdog with high potential = upset alert).
    The potential value itself is NEVER exposed in the analysis_text
    or any other player-facing string.
    """
    if fighter_id is None:
        return 50
    row = conn.execute(
        "SELECT potential FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 50


def _fighter_top_descriptors(conn, fighter_id, n=2, rng=None):
    """Return n voice descriptors for the fighter's top attributes.

    Picks the n highest-value attributes from fighter_attributes and
    returns noun-phrase descriptors for each (via _attribute_noun_phrase,
    which uses voice._tier_for for tier classification). The descriptors
    are guaranteed to be noun phrases (e.g., "elite power", "strong
    cardio", "average chin") so they fit grammatically into template
    slots like "brings {attr1} and {attr2}".

    Falls back to ["a serviceable skill set"] (single descriptor) if
    attributes are missing.
    """
    if fighter_id is None:
        return ["a serviceable skill set"]
    attrs = _fighter_attribute_block(conn, fighter_id)
    if not attrs:
        return ["a serviceable skill set"]
    paired = sorted(
        attrs.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    descs = []
    for attr_name, value in paired:
        if len(descs) >= n:
            break
        # Use _attribute_noun_phrase (voice._tier_for + adjective map)
        # so the descriptor is always a noun phrase — fits grammatically
        # into "brings {attr1} and {attr2}" slots. The voice layer is
        # still being used (via _tier_for) for tier classification.
        d = _attribute_noun_phrase(attr_name, value)
        if d:
            descs.append(d)
    if not descs:
        return ["a serviceable skill set"]
    return descs


def _fighter_weakest_descriptor(conn, fighter_id, rng=None):
    """Return a voice descriptor for the fighter's WEAKEST attribute.

    Used in the style_edge sentence: "Reed's questionable takedown
    defense could be his undoing." Picks the lowest-value attribute
    and returns a noun-phrase descriptor (e.g., "questionable takedown
    defense" / "shaky chin" / "limited cardio"). Falls back to
    "an untested skill set" if attributes are missing.

    Uses voice._tier_for to classify the value into a tier, then maps
    the tier to a pundit adjective ("questionable" for limited, "shaky"
    for poor, etc.). This guarantees a grammatical noun phrase that
    fits the "{underdog_last}'s {underdog_weakness} could be his
    undoing" template slot — the random voice.describe_attribute
    variants can be verb phrases ("can be taken down") which would
    be ungrammatical in that slot.
    """
    if fighter_id is None:
        return "an untested skill set"
    attrs = _fighter_attribute_block(conn, fighter_id)
    if not attrs:
        return "an untested skill set"
    paired = sorted(attrs.items(), key=lambda x: x[1])  # ascending
    attr_name, value = paired[0]
    return _attribute_noun_phrase(attr_name, value)


# ----------------------------------------------------------------
# Attribute noun-phrase helpers
# ----------------------------------------------------------------

# Map style_archetype name → short noun phrase for use in prose.
# (mirrors voice._ARCHETYPE_NOUN but local for direct access.)
_ATTR_NOUN = {
    "punch_power":         "power",
    "punch_accuracy":      "precision",
    "kick_power":          "kick power",
    "kick_accuracy":       "kick accuracy",
    "head_movement":       "head movement",
    "footwork":            "footwork",
    "clinch_striking":     "clinch striking",
    "clinch_offense":      "clinch offense",
    "clinch_defense":      "clinch defense",
    "takedown_offense":    "wrestling",
    "takedown_defense":    "takedown defense",
    "top_control":         "top control",
    "bottom_game":         "guard work",
    "submission_offense":  "submission game",
    "submission_defense":  "submission defense",
    "scramble_ability":    "scrambling",
    "cage_wrestling":      "cage wrestling",
    "cardio":              "cardio",
    "recovery_rate":       "recovery",
    "speed_explosiveness": "explosiveness",
    "strength":            "strength",
    "durability":          "durability",
    "flexibility":         "flexibility",
    "fight_iq":            "fight IQ",
    "chin":                "chin",
    "adaptability":        "adaptability",
}

# Map voice tier → pundit adjective for noun phrases. These are the
# adjectives the pundit uses when describing a fighter's attribute as
# a noun ("elite power" / "questionable takedown defense"). The voice
# layer's _tier_for classifies the value into a tier; we map the tier
# to a single adjective that's grammatical as a noun modifier.
_TIER_ADJECTIVE = {
    "elite":    "elite",
    "strong":   "strong",
    "capable":  "capable",
    "average":  "average",
    "limited":  "questionable",   # synonym used by pundits for "limited"
    "poor":     "shaky",
    "abysmal":  "abysmal",
}


def _attr_name_as_noun(attr_name):
    """Convert an attribute column name to a noun phrase for prose.

    'punch_power' → 'power', 'takedown_defense' → 'takedown defense',
    'fight_iq' → 'fight IQ', 'cardio' → 'cardio', etc. Falls back to
    the underscore→space conversion for unmapped attributes.
    """
    return _ATTR_NOUN.get(attr_name, attr_name.replace("_", " "))


def _attribute_noun_phrase(attr_name, value):
    """Build a noun-phrase descriptor for an attribute value.

    Returns phrases like "elite power", "questionable takedown
    defense", "average chin". Uses voice._tier_for to classify the
    value into a tier, then maps the tier to a pundit adjective.
    Always returns a noun phrase (adjective + noun) that fits
    grammatically into "{fighter}'s {descriptor} could be his undoing"
    or "{fighter}'s {descriptor} should carry him" template slots.
    """
    tier = _tier_for(value)
    adj = _TIER_ADJECTIVE.get(tier, "average")
    noun = _attr_name_as_noun(attr_name)
    return f"{adj} {noun}"


def _fighter_top_strength_noun_phrase(conn, fighter_id):
    """Return a noun-phrase descriptor for the fighter's TOP attribute.

    Used in "{favorite_last}'s {strength} should carry him" slots.
    Picks the highest-value attribute and returns a noun phrase like
    "elite power" or "strong cardio". Falls back to "experience" if
    attributes are missing (the brief's example uses "Vale's
    experience should carry him" — "experience" is a safe fallback
    that fits the slot grammatically).
    """
    if fighter_id is None:
        return "experience"
    attrs = _fighter_attribute_block(conn, fighter_id)
    if not attrs:
        return "experience"
    paired = sorted(attrs.items(), key=lambda x: x[1], reverse=True)
    attr_name, value = paired[0]
    return _attribute_noun_phrase(attr_name, value)


# ----------------------------------------------------------------
# Analysis-logic helpers
# ----------------------------------------------------------------

def _compute_predicted_winner(conn, fighter_a_id, fighter_b_id, rng=None):
    """Compare avg of 5 key attributes (with Gaussian noise) → winner.

    Returns (winner_id, loser_id, attribute_gap) where attribute_gap
    is the unsigned difference between the two fighters' (noisy)
    averages — used by _compute_confidence.
    """
    if rng is None:
        rng = random
    a_attrs = _fighter_attribute_block(conn, fighter_a_id)
    b_attrs = _fighter_attribute_block(conn, fighter_b_id)
    a_avg = sum(a_attrs.get(k, 50) for k in _KEY_ATTRS) / len(_KEY_ATTRS)
    b_avg = sum(b_attrs.get(k, 50) for k in _KEY_ATTRS) / len(_KEY_ATTRS)
    # Gaussian noise (per the brief: "±10" — σ=10).
    a_noisy = a_avg + rng.gauss(0, _PUNDIT_NOISE_SIGMA)
    b_noisy = b_avg + rng.gauss(0, _PUNDIT_NOISE_SIGMA)
    if a_noisy >= b_noisy:
        return fighter_a_id, fighter_b_id, abs(a_noisy - b_noisy)
    return fighter_b_id, fighter_a_id, abs(a_noisy - b_noisy)


def _compute_predicted_method(style_a, style_b, rng=None):
    """Pick a predicted-method label based on style archetypes.

    Per the brief:
      - Striker vs Striker → "KO/TKO"
      - Grappler vs Striker → "submission or KO"
      - Wrestler vs anyone → "decision"
    Extended for all 7 archetypes:
      - Submission Specialist vs anyone → "submission"
      - Brawler involved → "KO/TKO"
      - Counter-Striker vs Striker → "KO/TKO"
      - Balanced involved (no clear style clash) → "decision or late finish"
    """
    if rng is None:
        rng = random
    styles = {style_a, style_b}
    # Wrestler → decision (controls pace, grinds out wins).
    if "Wrestler" in styles:
        return "decision"
    # Submission Specialist → submission (hunts the finish on the ground).
    if "Submission Specialist" in styles:
        return "submission"
    # Grappler vs Striker / Brawler / Counter-Striker → sub or KO.
    if "Grappler" in styles and styles & {"Striker", "Brawler",
                                          "Counter-Striker"}:
        return "submission or KO"
    # Two strikers (Striker / Brawler / Counter-Striker) → KO/TKO.
    striker_types = {"Striker", "Brawler", "Counter-Striker"}
    if styles <= striker_types and len(styles) >= 1:
        return "KO/TKO"
    # Anything involving Balanced (no clear style clash).
    return "decision or late finish"


def _compute_confidence(attribute_gap):
    """Convert the attribute gap to a confidence_pct (50-90).

    Per the brief: "Small gap = 50-60%, large gap = 80-90%." Linear
    interpolation: gap=0 → 50, gap=20+ → 90. Clamped to [50, 90].
    """
    if attribute_gap < 0:
        attribute_gap = 0
    # Map gap 0-20 to confidence 50-90 (linear).
    pct = _CONF_MIN + (attribute_gap / 20.0) * (_CONF_MAX - _CONF_MIN)
    pct = int(round(pct))
    return max(_CONF_MIN, min(_CONF_MAX, pct))


def _compute_excitement(conn, fighter_a_id, fighter_b_id):
    """Compute excitement_score (0-100) from aggression + punch_power +
    killer_instinct across both fighters.

    Per the brief: "based on both fighters' aggression + punch_power
    + kill_instinct. High = 'fireworks expected'. Low = 'technical
    affair'." Averaged across both fighters, then across the 3 inputs.
    """
    a_attrs = _fighter_attribute_block(conn, fighter_a_id)
    b_attrs = _fighter_attribute_block(conn, fighter_b_id)
    a_pers = _fighter_personality_block(conn, fighter_a_id)
    b_pers = _fighter_personality_block(conn, fighter_b_id)
    # Aggregation: average across both fighters AND 3 inputs.
    values = [
        a_attrs.get("punch_power", 50),
        b_attrs.get("punch_power", 50),
        a_pers.get("aggression", 50),
        b_pers.get("aggression", 50),
        a_pers.get("killer_instinct", 50),
        b_pers.get("killer_instinct", 50),
    ]
    score = int(round(sum(values) / len(values)))
    return max(_EXCITEMENT_MIN, min(_EXCITEMENT_MAX, score))


def _compute_upset_risk(conn, favorite_id, underdog_id, attribute_gap):
    """Classify upset risk as 'high', 'moderate', or 'low'.

    Per the brief: "if the underdog has high potential or a style
    that matches up well, 'upset alert'." We use two signals:
      1. Underdog's potential (from fighter_career) — high potential
         (>70) suggests the underdog has the ceiling to spring an
         upset.
      2. Attribute gap — a smaller gap means the underdog is closer
         to the favorite on paper, so an upset is more plausible.
    Combined: high risk = underdog potential >70 AND gap <5; moderate
    risk = underdog potential >60 OR gap <10; low risk = otherwise.
    """
    underdog_potential = _fighter_potential(conn, underdog_id)
    if underdog_potential >= 70 and attribute_gap < 5:
        return "high"
    if underdog_potential >= 60 or attribute_gap < 10:
        return "moderate"
    return "low"


def _compute_style_edge(conn, favorite_id, underdog_id, rng=None):
    """Build the style_edge phrase (voice-layer-driven, no raw numbers).

    Picks the most lopsided attribute matchup between the two fighters
    and phrases it as "the {archetype_noun} has the edge on the
    {domain}" — e.g., "the striker has the edge on the feet" or "the
    wrestler dominates on the ground".

    The domain (feet / ground / clinch / pace) is inferred from which
    attribute group shows the biggest gap.
    """
    if rng is None:
        rng = random
    fav_attrs = _fighter_attribute_block(conn, favorite_id)
    und_attrs = _fighter_attribute_block(conn, underdog_id)
    fav_style = _fighter_style_archetype_name(conn, favorite_id)
    und_style = _fighter_style_archetype_name(conn, underdog_id)
    fav_noun = _ARCHETYPE_NOUN.get(fav_style, "fighter")

    # Domain groups: each maps a set of attributes to a domain phrase.
    domain_groups = {
        "on the feet":     ("punch_power", "punch_accuracy", "kick_power",
                            "kick_accuracy", "head_movement", "footwork"),
        "in the clinch":   ("clinch_striking", "clinch_offense",
                            "clinch_defense", "cage_wrestling"),
        "on the ground":   ("takedown_offense", "takedown_defense",
                            "top_control", "bottom_game",
                            "submission_offense", "submission_defense",
                            "scramble_ability"),
        "in the cardio game": ("cardio", "recovery_rate", "fatigue_tolerance"),
    }

    # Find the domain where the favorite's avg advantage is largest.
    best_domain = None
    best_gap = -1.0
    for domain, attrs in domain_groups.items():
        fav_avg = sum(fav_attrs.get(a, 50) for a in attrs) / len(attrs)
        und_avg = sum(und_attrs.get(a, 50) for a in attrs) / len(attrs)
        gap = fav_avg - und_avg
        if gap > best_gap:
            best_gap = gap
            best_domain = domain

    # If the favorite doesn't have a clear edge anywhere (best_gap <= 0),
    # the underdog has the edge in the best domain — flip the phrasing.
    if best_gap <= 0:
        und_noun = _ARCHETYPE_NOUN.get(und_style, "fighter")
        return (
            f"The {und_noun} could surprise in {best_domain} — "
            f"the matchup is closer than it looks on paper"
        )

    # Strong edge (>15 avg gap) → "dominates"; moderate (>5) → "has
    # the edge"; small (>=0) → "edges".
    if best_gap >= 15:
        verb = "dominates"
    elif best_gap >= 5:
        verb = "has the edge"
    else:
        verb = "narrowly edges"

    return f"The {fav_noun} {verb} {best_domain}"


# ----------------------------------------------------------------
# Analysis text builder
# ----------------------------------------------------------------

# Body templates for the analysis_text. Each template uses {name_a}
# / {name_b} / {stage_a} / {stage_b} / {art_a} / {art_b} (career-stage
# articles) / {attr_a1} / {attr_a2} / {attr_b1} / {attr_b2} (top-2
# attribute descriptors per fighter) / {style_edge} (the style_edge
# phrase) / {underdog_last} / {underdog_weakness} / {excitement_phrase}
# / {favorite_last} / {favorite_strength} / {underdog_strength} /
# {confidence_word} / {upset_word} slots. NO digit characters anywhere
# (CONVENTIONS §14).
_ANALYSIS_TEXT_TEMPLATES = [
    # Variant 1 — the brief's example pattern.
    "{name_a}, {art_a} {stage_a}, brings {attr_a1} and {attr_a2} into "
    "this matchup against {name_b}, {art_b} {stage_b}, with {attr_b1} "
    "and {attr_b2}. {style_edge} — {underdog_last}'s {underdog_weakness} "
    "could be {underdog_pronoun} undoing. {excitement_phrase} — both "
    "fighters come forward. {favorite_last}'s {favorite_strength} "
    "should carry {favorite_pronoun}, but {underdog_last}'s "
    "{underdog_strength} could flip the script in the later rounds. "
    "Confidence: {confidence_word}. Upset risk: {upset_word}.",

    # Variant 2 — underdog-first framing (for the upset-alert case).
    "{name_a}, {art_a} {stage_a}, brings {attr_a1} and {attr_a2} to "
    "the cage against {name_b}, {art_b} {stage_b}, carrying {attr_b1} "
    "and {attr_b2}. {style_edge}. {excitement_phrase} when the bell "
    "rings. {favorite_last}'s {favorite_strength} is the difference on "
    "paper, but {underdog_last}'s {underdog_strength} is the kind of "
    "X-factor that flips predictions on their head — and "
    "{underdog_pronoun} {underdog_weakness} is the question mark. "
    "Confidence: {confidence_word}. Upset risk: {upset_word}.",

    # Variant 3 — neutral framing (no underdog/favorite framing bias).
    "The matchup pits {name_a}, {art_a} {stage_a} with {attr_a1} and "
    "{attr_a2}, against {name_b}, {art_b} {stage_b}, who brings "
    "{attr_b1} and {attr_b2}. {style_edge}. {excitement_phrase} — "
    "{favorite_last}'s {favorite_strength} is the deciding factor on "
    "paper, though {underdog_last}'s {underdog_strength} keeps things "
    "interesting if the fight drags into deep waters. "
    "{underdog_last}'s {underdog_weakness} is the soft spot the "
    "favorite will target. Confidence: {confidence_word}. Upset risk: "
    "{upset_word}.",

    # Variant 4 — veteran-vs-prospect flavor (used when one is older
    # and more experienced than the other).
    "{name_a}, {art_a} {stage_a}, brings {attr_a1} and {attr_a2} into "
    "the cage. {name_b}, {art_b} {stage_b}, answers with {attr_b1} "
    "and {attr_b2}. {style_edge}. {excitement_phrase}. {favorite_last}'s "
    "{favorite_strength} should be the difference — but "
    "{underdog_last}'s {underdog_strength} is the kind of weapon that "
    "can erase a paper edge in a single exchange, and "
    "{underdog_pronoun} {underdog_weakness} is the lingering question. "
    "Confidence: {confidence_word}. Upset risk: {upset_word}.",
]


def _pronoun_for(conn, fighter_id):
    """Return 'his' / 'her' / 'their' based on the fighter's gender.

    Defensive — defaults to 'their' for unknown gender or missing
    fighter (avoids gender assumption in punditry prose).
    """
    if fighter_id is None:
        return "their"
    row = conn.execute(
        "SELECT gender FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "their"
    gender = (row[0] or "").lower()
    if gender == "male":
        return "his"
    if gender == "female":
        return "her"
    return "their"


def _pronoun_object_for(conn, fighter_id):
    """Return 'him' / 'her' / 'them' (object pronoun) by gender.

    Used in '{favorite_last}'s {strength} should carry {pronoun}' slots
    where the object pronoun is grammatically required (vs. the
    possessive 'his/her/their' returned by _pronoun_for).
    """
    if fighter_id is None:
        return "them"
    row = conn.execute(
        "SELECT gender FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "them"
    gender = (row[0] or "").lower()
    if gender == "male":
        return "him"
    if gender == "female":
        return "her"
    return "them"


def _build_analysis_text(conn, fighter_a_id, fighter_b_id, favorite_id,
                         underdog_id, style_edge, excitement_score,
                         confidence_pct, upset_risk_level, rng=None):
    """Build the full prose analysis_text using voice descriptors.

    Returns a multi-sentence string with NO digit characters per
    CONVENTIONS §14. Uses the template variants in
    _ANALYSIS_TEXT_TEMPLATES for variety.
    """
    if rng is None:
        rng = random
    # Fighter names + career stages.
    name_a = _fighter_full_name(conn, fighter_a_id)
    name_b = _fighter_full_name(conn, fighter_b_id)
    stage_a = _fighter_career_stage(conn, fighter_a_id, rng=rng)
    stage_b = _fighter_career_stage(conn, fighter_b_id, rng=rng)
    # Top-2 attribute descriptors per fighter.
    a_descs = _fighter_top_descriptors(conn, fighter_a_id, n=2, rng=rng)
    b_descs = _fighter_top_descriptors(conn, fighter_b_id, n=2, rng=rng)
    # Pad to exactly 2 descriptors per fighter (defensive).
    while len(a_descs) < 2:
        a_descs.append("a serviceable skill set")
    while len(b_descs) < 2:
        b_descs.append("a serviceable skill set")
    # Favorite's top strength (noun-phrase descriptor for grammar).
    favorite_strength = _fighter_top_strength_noun_phrase(conn, favorite_id)
    # Underdog's top strength + weakest descriptor (noun phrases).
    underdog_strength = _fighter_top_strength_noun_phrase(conn, underdog_id)
    underdog_weakness = _fighter_weakest_descriptor(conn, underdog_id, rng=rng)
    # Last names (for in-prose mentions).
    favorite_last = _fighter_last_name(conn, favorite_id)
    underdog_last = _fighter_last_name(conn, underdog_id)
    # Pronouns.
    favorite_pronoun = _pronoun_object_for(conn, favorite_id)
    underdog_pronoun = _pronoun_for(conn, underdog_id)
    # Word forms for confidence + excitement + upset.
    confidence_word = _confidence_word(confidence_pct, rng=rng)
    excitement_phrase = _excitement_phrase(excitement_score, rng=rng)
    upset_word = _upset_phrase(upset_risk_level, rng=rng)
    # Articles for career stages.
    art_a = _article_for(stage_a)
    art_b = _article_for(stage_b)

    template = rng.choice(_ANALYSIS_TEXT_TEMPLATES)
    base_text = template.format(
        name_a=name_a, name_b=name_b,
        stage_a=stage_a, stage_b=stage_b,
        art_a=art_a, art_b=art_b,
        attr_a1=a_descs[0], attr_a2=a_descs[1],
        attr_b1=b_descs[0], attr_b2=b_descs[1],
        style_edge=style_edge,
        underdog_last=underdog_last,
        underdog_weakness=underdog_weakness,
        underdog_pronoun=underdog_pronoun,
        excitement_phrase=excitement_phrase,
        favorite_last=favorite_last,
        favorite_strength=favorite_strength,
        favorite_pronoun=favorite_pronoun,
        underdog_strength=underdog_strength,
        confidence_word=confidence_word,
        upset_word=upset_word,
    )

    # Phase C — append a betting-odds sentence to the analysis_text.
    # The odds are derived from confidence_pct + upset_risk_level and
    # expressed in CAGE EMPIRE voice (NO raw odds numbers per §14).
    # The sentence is a separate addition so the betting line is
    # clearly visible in the news feed — the player sees "Vale is the
    # heavy favorite on the betting line" or "This one's a coin flip"
    # without having to parse the confidence_pct integer.
    odds_phrase = _betting_odds_phrase(
        confidence_pct, upset_risk_level, rng=rng,
    )
    odds_sentence = _betting_odds_sentence(
        favorite_last, underdog_last, odds_phrase, rng=rng,
    )
    return base_text + " " + odds_sentence


# ----------------------------------------------------------------
# Public API — analysis generator
# ----------------------------------------------------------------

def generate_matchup_analysis(conn, fighter_a_id, fighter_b_id,
                              fight_id=None, event_id=None, rng=None):
    """Generate a matchup analysis for a fighter pair.

    The core function. Compares both fighters' attributes using voice
    descriptors, predicts winner/method, computes excitement score +
    upset risk, and writes a row to matchup_analyses. Returns the
    analysis dict.

    Args:
        conn: sqlite3.Connection (caller commits).
        fighter_a_id, fighter_b_id: the two fighter IDs (any order —
            the table stores them as-is; UNIQUE includes fight_id so
            the same pair can be analyzed for different fights).
        fight_id: optional — the scheduled fight this analysis is
            for. If None, the analysis is for a hypothetical matchup
            (UNIQUE constraint allows NULL fight_id).
        event_id: optional — denormalized for convenience (the news
            feed can filter analyses by event without a JOIN).
        rng: optional random.Random for reproducible analysis (tests
            pass a seeded RNG).

    Returns:
        A dict with keys: analysis_id, fighter_a_id, fighter_b_id,
        fight_id, event_id, predicted_winner, predicted_method,
        confidence_pct, style_edge, excitement_score, upset_risk,
        analysis_text. Returns None if the analysis couldn't be
        generated (e.g., either fighter is missing).
    """
    if rng is None:
        rng = random
    if fighter_a_id is None or fighter_b_id is None:
        return None
    if fighter_a_id == fighter_b_id:
        return None

    # Predicted winner (with Gaussian noise for pundit uncertainty).
    favorite_id, underdog_id, attribute_gap = _compute_predicted_winner(
        conn, fighter_a_id, fighter_b_id, rng=rng,
    )

    # Predicted method (based on style archetypes).
    style_a = _fighter_style_archetype_name(conn, fighter_a_id)
    style_b = _fighter_style_archetype_name(conn, fighter_b_id)
    predicted_method = _compute_predicted_method(style_a, style_b, rng=rng)

    # Confidence (50-90 based on attribute gap).
    confidence_pct = _compute_confidence(attribute_gap)

    # Style edge (voice-layer-driven phrase).
    style_edge = _compute_style_edge(
        conn, favorite_id, underdog_id, rng=rng,
    )

    # Excitement score (0-100 based on aggression + punch_power +
    # killer_instinct across both fighters).
    excitement_score = _compute_excitement(
        conn, fighter_a_id, fighter_b_id,
    )

    # Upset risk (high / moderate / low based on underdog's potential +
    # attribute gap).
    upset_risk_level = _compute_upset_risk(
        conn, favorite_id, underdog_id, attribute_gap,
    )

    # Predicted winner — store the fighter's full name (no digit
    # characters per §14).
    predicted_winner = _fighter_full_name(conn, favorite_id)

    # Upset risk — store a phrase (no digit characters). The
    # _upset_phrase helper picks a word form ("real" / "possible" /
    # "low"); we expand it to a full phrase for the stored column.
    upset_word = _upset_phrase(upset_risk_level, rng=rng)
    if upset_risk_level == "high":
        upset_risk = f"upset alert — {upset_word} risk"
    elif upset_risk_level == "moderate":
        upset_risk = f"{upset_word} upset risk"
    else:
        upset_risk = f"{upset_word} upset risk — the favorite should hold"

    # Analysis text (full prose, voice-layer-driven, no raw numbers).
    analysis_text = _build_analysis_text(
        conn, fighter_a_id, fighter_b_id, favorite_id, underdog_id,
        style_edge, excitement_score, confidence_pct,
        upset_risk_level, rng=rng,
    )

    # Insert the row (UNIQUE constraint may fire if the same analysis
    # is generated twice for the same fight — defensive INSERT OR
    # REPLACE so re-resolution doesn't crash).
    cur = conn.execute(
        "INSERT OR REPLACE INTO matchup_analyses "
        "(fighter_a_id, fighter_b_id, fight_id, event_id, "
        " predicted_winner, predicted_method, confidence_pct, "
        " style_edge, excitement_score, upset_risk, analysis_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fighter_a_id, fighter_b_id, fight_id, event_id,
         predicted_winner, predicted_method, confidence_pct,
         style_edge, excitement_score, upset_risk, analysis_text),
    )
    analysis_id = cur.lastrowid
    return {
        "analysis_id": analysis_id,
        "fighter_a_id": fighter_a_id,
        "fighter_b_id": fighter_b_id,
        "fight_id": fight_id,
        "event_id": event_id,
        "predicted_winner": predicted_winner,
        "predicted_method": predicted_method,
        "confidence_pct": confidence_pct,
        "style_edge": style_edge,
        "excitement_score": excitement_score,
        "upset_risk": upset_risk,
        "analysis_text": analysis_text,
    }


# ----------------------------------------------------------------
# Readers (per CONVENTIONS §5.3 — every new table must ship with a
# reader). Used by the upcoming UI tab + future show-rating engine
# to surface pundit takes on a fight.
# ----------------------------------------------------------------

def get_matchup_analysis(conn, fighter_a_id, fighter_b_id, fight_id=None):
    """Return the matchup_analysis row for a fight pair, or None.

    The two fighter IDs can be passed in any order — the function
    queries both directions. If fight_id is provided, only the
    analysis tied to that fight is returned (UNIQUE constraint
    guarantees at most one). If fight_id is None, the most recent
    analysis for the pair is returned.
    """
    if fighter_a_id is None or fighter_b_id is None:
        return None
    if fighter_a_id == fighter_b_id:
        return None
    if fight_id is not None:
        return conn.execute(
            "SELECT * FROM matchup_analyses "
            "WHERE fight_id=? "
            "AND ((fighter_a_id=? AND fighter_b_id=?) "
            "  OR (fighter_a_id=? AND fighter_b_id=?))",
            (fight_id, fighter_a_id, fighter_b_id,
             fighter_b_id, fighter_a_id),
        ).fetchone()
    # No fight_id — most recent analysis for the pair.
    return conn.execute(
        "SELECT * FROM matchup_analyses "
        "WHERE ((fighter_a_id=? AND fighter_b_id=?) "
        "   OR (fighter_a_id=? AND fighter_b_id=?)) "
        "ORDER BY created_at DESC LIMIT 1",
        (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
    ).fetchone()


def get_recent_analyses(conn, fighter_id, limit=10):
    """Return recent matchup_analyses involving the fighter.

    Returns a list of analysis rows (most recent first), limited to
    `limit` rows. Includes both directions (fighter_id may be
    fighter_a_id OR fighter_b_id on the row).
    """
    if fighter_id is None:
        return []
    return conn.execute(
        "SELECT * FROM matchup_analyses "
        "WHERE fighter_a_id=? OR fighter_b_id=? "
        "ORDER BY created_at DESC LIMIT ?",
        (fighter_id, fighter_id, limit),
    ).fetchall()


def get_event_analyses(conn, event_id):
    """Return all matchup_analyses for a given event.

    Used by the post-event news feed / UI tab to show all the pundit
    takes on a single event's fights.
    """
    if event_id is None:
        return []
    return conn.execute(
        "SELECT * FROM matchup_analyses WHERE event_id=? "
        "ORDER BY analysis_id",
        (event_id,),
    ).fetchall()


# ----------------------------------------------------------------
# FIGHT_RESOLVED subscriber — generates the analysis retroactively
# (per the brief: "subscribe to FIGHT_RESOLVED and generate the
# analysis retroactively (the analysis describes the pre-fight
# matchup, written after the fight for the news feed)").
# ----------------------------------------------------------------

def _process_scheduled_fight(conn, event):
    """Subscriber for FIGHT_RESOLVED — generates a matchup analysis.

    The analysis is the pundit's pre-fight prediction, written after
    the fight resolves so it appears in the news feed as "here's what
    the pundits thought going in." Reads the fighter_attributes +
    fighter_personality + fighter_career tables for both fighters and
    generates a voice-layer-driven analysis row.

    Defensive — silently returns if the event is missing required
    fields (fighter_a_id / fighter_b_id). Uses a fresh RNG per call
    for variety (the test case D variety check verifies at least
    three distinct analyses over multiple calls).
    """
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    a_id = event.get("fighter_a_id")
    b_id = event.get("fighter_b_id")
    if a_id is None or b_id is None:
        return
    if a_id == b_id:
        return
    rng = random.Random()  # fresh RNG per call for variety
    generate_matchup_analysis(
        conn, a_id, b_id, fight_id=fight_id, event_id=event_id, rng=rng,
    )


# ----------------------------------------------------------------
# REGISTRATION
# ----------------------------------------------------------------

def register_subscribers():
    """Register all punditry subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior
    registrations.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.FIGHT_RESOLVED, _process_scheduled_fight,
        name="punditry.process_scheduled_fight",
    )
