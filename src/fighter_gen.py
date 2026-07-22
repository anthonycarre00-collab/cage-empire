"""Fighter generation primitives (added in v2.0.0, Task 14.5+14.6+14.7;
extended in v2.0.1, Task pre-B1-fixes).

Four pure-ish functions used by:

  * `seed_data.py` — to backfill the 5 existing seeded fighters with the
    21 new attribute columns, 17 new personality columns, and 14 new
    fighters-table columns added in this schema expansion. (v2.0.1
    adds a separate deterministic backfill for `potential` — see
    `seed_data._backfill_potential_title_reigns`.)
  * `app.generate_fighter()` — Task 14's regen function. Previously it
    INSERTed all-50 defaults; now it uses these functions to produce
    archetype-biased attribute and personality blocks (v2.0.0) AND a
    randomly-distributed `potential` value (v2.0.1) so regen
    prospects feel like real fighters, not generic 50s, and so the
    Talent Hunter fantasy is preserved (elite prospects are rare).

The bias system:

  * `style_archetypes.attribute_bias` is a JSON column holding a dict
    like `{"punch_power": 10, "takedown_defense": -5}`. When
    `generate_attribute_block(archetype_id, conn)` is called with a
    non-None archetype_id and a live connection, the bias is loaded
    and applied to the base value of 50. (v2.0.1 softened all biases
    ~40-50% — max absolute bias is now 10, was 20.)
  * `personality_archetypes.trait_bias` is the same idea for the
    personality block.
  * The formula for every attribute/trait is:

        value = clamp(50 + bias.get(col, 0) + random.randint(-8, 8), 0, 100)

    The +/-8 noise floor keeps fighters within an archetype distinct
    (no two Brawlers will be identical) while the bias gives the
    archetype its identity (Brawlers average ~60 punch_power, ~58 chin
    with the softened +10/+8 biases).

The potential distribution (v2.0.1, Task pre-B1-fixes):

  `generate_potential()` returns a value 0-100 using this distribution:
    - 10% chance: elite potential (70-90) — "that kid from Mexico"
      rare prospects.
    - 30% chance: solid potential (50-69) — can become contenders
      with development.
    - 60% chance: limited potential (25-49) — journeymen who plateau
      early.

  Scarcity makes elite prospects exciting to find. The Talent Hunter
  fantasy (CAGE_EMPIRE_SOUL.md Fantasy 1) depends on this: if every
  fighter could reach 100 in every attribute, "discovering greatness"
  is meaningless — every prospect is potentially great. With the
  distribution above, ~1 in 10 regen prospects is elite, and the
  player has to scout to find them (Task 18, future, will add
  scouting uncertainty on top of this).

The 4 functions are deliberately kept side-effect-free (no DB writes).
Callers own the INSERT/UPDATE so the same primitives can be reused by
the seed (backfill), by regen (Task 14), and by future tasks (Task 18
scouting reports will generate "scout-estimated" attribute blocks that
the player can compare against the real values; Task 16 training
camps will read `potential` to compute diminishing-returns growth
toward the ceiling).

Design Law check (CONVENTIONS.md §13):
  - Discovery (Fantasy 1: Talent Hunter): the bias system means regen
    prospects arrive with a *style identity* — a Brawler replacement
    for a retiring Brawler feels like a Brawler, not a generic 50/50
    prospect. Players can spot "this kid hits hard" from day one.
    v2.0.1 ADDS the `potential` distribution on top — now players
    also have to discover whether a hard-hitting Brawler prospect
    has the *ceiling* to become a champion or is just a journeyman
    who hits hard. The Talent Hunter fantasy now has TWO dimensions
    to scout: style (visible immediately via biased attributes) and
    potential (hidden until scouted — Task 18 will add this).
  - Growth (Fantasy 2 + 3): the 25 attributes are the substrate that
    future training camps (Task 16), scouting (Task 18), and the voice
    layer (Task 19) will grow, scout, and describe. Without these
    columns, those tasks have nothing to act on. v2.0.1 ADDS the
    `potential` ceiling that training camps will push attributes
    toward with diminishing returns — without it, every fighter has
    unlimited growth and the development fantasy collapses.
  - Legacy (Fantasy 5): the `title_reigns` counter (set by
    _resolve_title_after_fight, read by the retirement path) drives
    the memory-resurfacing logic — only champions get the
    "reminiscent of former champion {name}" treatment. Reserving
    memory resurfacing for champions makes the comparison
    meaningful: it's a stamp of greatness, not noise.
"""

import json
import random


# ----------------------------------------------------------------
# Column-name registries. These MUST match the column names in
# build_db.py's fighter_attributes and fighter_personality table
# definitions. Keeping them as module-level constants lets the new
# acceptance test (scripts/test_fighter_attributes.py) import them
# directly so a column-name typo fails the test rather than silently
# producing a wrong-shape dict.
# ----------------------------------------------------------------

# The 4 existing attributes (preserved across the migration — their
# values are NOT touched by backfill). Listed first so callers that
# want to preserve them can slice them off.
EXISTING_ATTRIBUTE_NAMES = [
    "punch_power", "cardio", "fight_iq", "chin",
]

# The 21 new attributes added in v2.0.0. All CHECK (BETWEEN 0 AND 100).
NEW_ATTRIBUTE_NAMES = [
    # Striking
    "punch_accuracy", "kick_power", "kick_accuracy", "head_movement",
    # Range
    "footwork", "clinch_striking", "clinch_offense", "clinch_defense",
    # Grappling
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling",
    # Physical
    "recovery_rate", "speed_explosiveness", "strength", "durability",
    "flexibility",
    # Mental
    "adaptability",
]

# The full 25-attribute block (existing 4 + new 21). Order matters for
# documentation purposes (existing first, then new), but callers should
# treat this as a set — the dict returned by generate_attribute_block
# uses these names as keys, so callers can look up by name regardless
# of order.
ATTRIBUTE_NAMES = EXISTING_ATTRIBUTE_NAMES + NEW_ATTRIBUTE_NAMES

# The 3 existing personality fields (preserved across the migration).
EXISTING_PERSONALITY_NAMES = [
    "aggression", "composure", "morale",
]

# The 17 new personality fields added in v2.0.0. All CHECK (0-100).
NEW_PERSONALITY_NAMES = [
    # Temperament
    "risk_taking", "killer_instinct", "grit", "discipline", "patience",
    # Career
    "ambition", "loyalty", "charisma", "attention_seeking",
    "coachability", "professionalism",
    # Resilience
    "ego", "resilience", "sportsmanship", "travel_comfort",
    # Dynamic
    "focus", "fatigue_tolerance",
]

PERSONALITY_NAMES = EXISTING_PERSONALITY_NAMES + NEW_PERSONALITY_NAMES


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _clamp(value, lo=0, hi=100):
    """Clamp `value` to the inclusive range [lo, hi].

    Pure helper, no side effects. Used for every attribute/trait
    generation so values stay within the CHECK-constraint bounds
    (0-100 for attributes/traits, 0-100 for physical stats like
    height/reach which fall well inside the range anyway).
    """
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _load_json_bias(conn, table, id_col, bias_col, archetype_id):
    """Load + parse a JSON bias column for a single archetype row.

    Returns `{}` (empty dict, no bias applied) when:
      * `conn` is None (caller asked for an unbiased block), or
      * `archetype_id` is None (no archetype specified), or
      * the archetype row has no bias set (NULL or empty string), or
      * the JSON fails to parse (defensive — bad seed data shouldn't
        crash generation; we log nothing and fall back to no bias).

    Returns the parsed dict otherwise. Never raises.
    """
    if conn is None or archetype_id is None:
        return {}
    row = conn.execute(
        f"SELECT {bias_col} FROM {table} WHERE {id_col}=?",
        (archetype_id,),
    ).fetchone()
    if row is None:
        return {}
    raw = row[0]
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        # Defensive: a corrupt JSON in attribute_bias should not crash
        # fighter generation. Treat as no bias and continue.
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _generate_block(column_names, bias):
    """Generate a {col: value} dict for the given column list + bias.

    Pure helper — no DB access, no I/O. Used by both
    generate_attribute_block and generate_personality_block so the
    bias + noise formula lives in exactly one place.

    Formula per the task brief (STAGES.md §14.5):
        value = clamp(50 + bias.get(col, 0) + random.randint(-8, 8), 0, 100)

    The +/-8 noise floor is small enough that the archetype's identity
    (Brawler hits hard, Counter-Striker dodges well) is preserved
    across 100-sample averages but large enough that no two fighters
    within an archetype are identical.
    """
    out = {}
    for col in column_names:
        bias_value = bias.get(col, 0)
        noise = random.randint(-8, 8)
        out[col] = _clamp(50 + bias_value + noise, 0, 100)
    return out


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def generate_attribute_block(archetype_id=None, conn=None):
    """Generate a 25-attribute block, optionally biased by archetype.

    Args:
        archetype_id: the style_archetype_id to load attribute_bias
            from. If None or if conn is None, no bias is applied
            (pure 50 + noise for every column).
        conn: open sqlite3 connection. Required to load the bias. If
            None, the block is generated without bias (useful for tests
            that want to verify the noise floor without setting up a
            DB).

    Returns:
        dict with all 25 ATTRIBUTE_NAMES as keys, each value an int
        in [0, 100]. The existing 4 attributes (punch_power, cardio,
        fight_iq, chin) are also in the dict — callers that need to
        PRESERVE existing values (e.g., the seed backfill) must
        override those 4 keys with the preserved values before
        INSERT/UPDATE.
    """
    bias = _load_json_bias(
        conn, "style_archetypes", "style_archetype_id",
        "attribute_bias", archetype_id,
    ) if conn is not None else {}
    return _generate_block(ATTRIBUTE_NAMES, bias)


def generate_personality_block(archetype_id=None, conn=None):
    """Generate a 20-personality block, optionally biased by archetype.

    Args:
        archetype_id: the personality_archetype_id to load trait_bias
            from. If None or if conn is None, no bias is applied.
        conn: open sqlite3 connection. Required to load the bias.

    Returns:
        dict with all 20 PERSONALITY_NAMES as keys, each value an int
        in [0, 100]. The existing 3 fields (aggression, composure,
        morale) are also in the dict — callers that need to PRESERVE
        existing values must override those 3 keys with the preserved
        values before INSERT/UPDATE.
    """
    bias = _load_json_bias(
        conn, "personality_archetypes", "personality_archetype_id",
        "trait_bias", archetype_id,
    ) if conn is not None else {}
    return _generate_block(PERSONALITY_NAMES, bias)


def generate_physical_block(weight_class_max_kg=None, gender='male'):
    """Generate height_cm, reach_cm, stance, handedness for a fighter.

    v2.6.3: height is now scaled by weight class. A Heavyweight (max
    120kg) averages ~191cm; a Flyweight (max 57kg) averages ~170cm.
    This produces realistic height-vs-weight-class distributions —
    previously every weight class used the same 178cm average, which
    meant 195cm Flyweights and 165cm Heavyweights (both unrealistic).

    The formula: base_height scales linearly with max_weight_kg from
    a minimum of 168cm (at 47kg, Atomweight) to a maximum of 193cm
    (at 120kg, Heavyweight). Female fighters are ~7cm shorter on
    average than their male equivalents (real-world UFC data).

    Args:
        weight_class_max_kg: the weight class's max_weight_kg. If None,
            defaults to 75kg (Welterweight-ish, the old behavior).
        gender: 'male' or 'female'. Female fighters are ~7cm shorter.

    Returns:
        dict with keys: height_cm (int), reach_cm (int), stance (str),
        handedness (str).
    """
    if weight_class_max_kg is None:
        weight_class_max_kg = 75.0  # default: Welterweight
    # Scale height from weight: 47kg→168cm, 120kg→193cm (male)
    # Linear interpolation: height = 168 + (weight - 47) * (193-168)/(120-47)
    base_height = 168 + (weight_class_max_kg - 47) * (25.0 / 73.0)
    if gender == 'female':
        base_height -= 7  # women are ~7cm shorter on average
    # Gaussian noise with std=5 (tighter than before since base is
    # now weight-class-specific, not universal)
    height_cm = _clamp(int(round(random.gauss(base_height, 5))), 155, 210)
    reach_cm = height_cm + random.randint(-5, 10)
    stance = random.choices(
        ['orthodox', 'southpaw', 'switch'], weights=[80, 15, 5]
    )[0]
    handedness = random.choices(
        ['right', 'left', 'ambidextrous'], weights=[85, 10, 5]
    )[0]
    return {
        "height_cm": height_cm,
        "reach_cm": reach_cm,
        "stance": stance,
        "handedness": handedness,
    }


# ----------------------------------------------------------------
# Nickname generator (added v2.6.3, forensic audit fix).
#
# The old approach used a fixed pool of 38 nicknames from the
# name_pools table, which meant each nickname was shared by ~43
# fighters. The new generator produces thousands of unique
# combinations based on the fighter's attributes, style, personality,
# and nation — producing relevant, varied, believable nicknames.
# ----------------------------------------------------------------

# Nickname components — combined to produce thousands of unique nicknames.
# Each component list is large enough that the cartesian product produces
# far more combinations than the 4000-fighter roster.

# Adjective + noun combos: "The Iron Hammer", "The Silent Viper", etc.
_NICK_ADJECTIVES = [
    "Iron", "Steel", "Stone", "Granite", "Brass", "Bronze", "Copper",
    "Silent", "Quiet", "Loud", "Wild", "Savage", "Brutal", "Ruthless",
    "Merciless", "Relentless", "Fearless", "Reckless", "Calm", "Cold",
    "Frozen", "Burning", "Blazing", "Dark", "Shadow", "Midnight", "Crimson",
    "Golden", "Silver", "Diamond", "Velvet", "Thunder", "Lightning", "Storm",
    " Desert", "Arctic", "Solar", "Lunar", "Cosmic", "Electric", "Magnetic",
    "Ancient", "Eternal", "Immortal", "Forbidden", "Hidden", "Lost", "Broken",
    "Rising", "Falling", "Sleeping", "Waking", "Hungry", "Starving", "Thirsty",
    "Young", "Old", "Bold", "Sly", "Swift", "Quick", "Slow", "Heavy", "Light",
    "Giant", "Tiny", "Massive", "Slender", "Broad", "Narrow", "Tall", "Short",
    "Proud", "Humble", "Noble", "Royal", "Common", "Sacred", "Cursed", "Blessed",
    "Forgotten", "Remembered", "Unnamed", "Nameless", "Faceless", "Timeless",
]

_NICK_NOUNS_ANIMAL = [
    "Viper", "Cobra", "Python", "Boa", "Wolf", "Bear", "Lion", "Tiger",
    "Panther", "Leopard", "Cheetah", "Jaguar", "Bull", "Stallion", "Mustang",
    "Falcon", "Hawk", "Eagle", "Owl", "Raven", "Crow", "Shark", "Barracuda",
    "Piranha", "Octopus", "Spider", "Scorpion", "Wasp", "Hornet", "Bee",
    "Mantis", "Dragon", "Phoenix", "Griffin", "Hydra", "Cerberus", "Minotaur",
    "Gargoyle", "Golem", "Titan", "Colossus", "Gladiator", "Centurion",
    "Samurai", "Ronin", "Bushi", "Berserker", "Marauder", "Raider", "Reaper",
    "Phantom", "Ghost", "Specter", "Wraith", "Demon", "Devil", "Fiend",
    "Machine", "Engine", "Hammer", "Anvil", "Forge", "Blade", "Edge",
    "Axe", "Mace", "Shield", "Wall", "Tower", "Fortress", "Castle",
    "Storm", "Hurricane", "Tornado", "Cyclone", "Typhoon", "Quake", "Avalanche",
    "Volcano", "Inferno", "Wildfire", "Frost", "Ice", "Stone", "Rock",
    "Mountain", "Cliff", "Peak", "Summit", "Abyss", "Void", "Eclipse",
]

# Single-word nicknames (no "The"): "Ice", "Venom", "Havoc"
_NICK_SINGLE_WORDS = [
    "Ice", "Venom", "Havoc", "Chaos", "Mayhem", "Riot", "Tumult", "Clamor",
    "Echo", "Static", "Noise", "Silence", "Hush", "Whisper", "Roar", "Growl",
    "Snarl", "Bite", "Sting", "Strike", "Smash", "Crash", "Bash", "Clash",
    "Spark", "Flash", "Flare", "Glow", "Blaze", "Ember", "Ash", "Smoke",
    "Mist", "Fog", "Haze", "Dusk", "Dawn", "Noon", "Midnight", "Twilight",
    "Jinx", "Hex", "Curse", "Doom", "Ruin", "Wreck", "Scrap", "Junk",
    "Ace", "King", "Queen", "Jack", "Joker", "Deuce", "Trey", "Knave",
    "Zen", "Tao", "Karma", "Dharma", "Chi", "Ki", "Do", "Way",
    "Vibe", "Groove", "Flow", "Rhythm", "Beat", "Pulse", "Heart", "Soul",
    "Prime", "Apex", "Peak", "Crest", "Crown", "Throne", "Scepter", "Orb",
]

# Style-based nicknames: a Wrestler might be "The Takedown", a Striker "The Punch"
_NICK_STYLE_BASED = {
    "Wrestler": ["The Takedown", "The Grind", "The Smother", "The Slam", "The Throw", "The Pin", "The Cradle", "The Switch"],
    "Striker": ["The Punch", "The Kick", "The Combo", "The Cross", "The Jab", "The Hook", "The Uppercut", "The Headkick"],
    "Grappler": ["The Sweep", "The Pass", "The Mount", "The Roll", "The Flow", "The Transition", "The Scramble", "The Reverse"],
    "Submission Specialist": ["The Choke", "The Lock", "The Tap", "The Crank", "The Squeeze", "The Twist", "The Kimura", "The Guillotine"],
    "Brawler": ["The Brawl", "The Slugfest", "The War", "The Firefight", "The exchange", "The Scrap", "The Donnybrook", "The Ruckus"],
    "Counter-Striker": ["The Counter", "The Parry", "The Slip", "The Roll-Out", "The Pivot", "The Fade", "The Check", "The Catch"],
    "Balanced": ["The All-Rounder", "The Complete", "The Total", "The Well-Rounded", "The Versatile", "The Adaptable", "The Fluid", "The Seamless"],
}

# Nation-flavored nickname prefixes/suffixes (used 10% of the time for
# cultural flavor)
_NICK_NATION_FLAVOR = {
    "Brazil": ["Capoeira", "Berimbau", "Ginga", "Malicia", "Axé"],
    "Japan": ["Bushido", "Ronin", "Samurai", "Kamikaze", "Tatami"],
    "Russia": ["Siberian", "Taiga", "Frost", "Hammer", "Sickle"],
    "Dagestan": ["Eagle", "Mountain", "Wolf", "Caucasus", "Highlander"],
    "Mexico": ["Lucha", "Azteca", "Maya", "Lobo", "Guerrero"],
    "Ireland": ["Celtic", "Shamrock", "Gael", "Fenian", "Wolfhound"],
    "Netherlands": ["Tulip", "Dyke", "Windmill", "Lion", "Orange"],
    "Cuba": ["Havana", "Salsa", "Cigar", "Revolution", "Malecon"],
}


def generate_nickname(attrs=None, pers=None, style_archetype_name=None,
                      nation_name=None, rng=None):
    """Generate a unique, relevant nickname for a fighter.

    The nickname is chosen based on the fighter's attributes, personality,
    style archetype, and nation — producing relevant, varied nicknames
    instead of the old fixed-pool approach.

    Selection logic (in priority order):
      1. 15% chance: style-based nickname (e.g. Wrestler → "The Takedown")
      2. 10% chance: nation-flavored nickname (e.g. Brazil → "Ginga")
      3. 25% chance: attribute-based nickname (high punch_power → "The Hammer")
      4. 20% chance: personality-based (high aggression → "The Predator")
      5. 30% chance: adjective + animal noun ("The Iron Viper")

    40% of fighters get NO nickname (None) — not every fighter has one
    in real life.

    Args:
        attrs: dict of fighter_attributes (25 keys). If None, skip
            attribute-based nicknames.
        pers: dict of fighter_personality (20 keys). If None, skip
            personality-based nicknames.
        style_archetype_name: str like "Wrestler", "Striker". If None,
            skip style-based nicknames.
        nation_name: str like "Brazil". If None, skip nation-flavored.
        rng: random.Random instance. If None, use the global random.

    Returns:
        A nickname string, or None (no nickname).
    """
    import random as _r
    rng = rng or _r

    # 40% of fighters get no nickname
    if rng.random() < 0.40:
        return None

    # 15% chance: style-based
    if style_archetype_name and style_archetype_name in _NICK_STYLE_BASED and rng.random() < 0.15:
        return rng.choice(_NICK_STYLE_BASED[style_archetype_name])

    # 10% chance: nation-flavored
    if nation_name and nation_name in _NICK_NATION_FLAVOR and rng.random() < 0.10:
        flavor = rng.choice(_NICK_NATION_FLAVOR[nation_name])
        return f"The {flavor}"

    # 25% chance: attribute-based (requires attrs dict)
    if attrs and rng.random() < 0.25:
        # Find the fighter's standout attribute (highest above 60)
        standout = None
        standout_val = 0
        attr_nick_map = {
            "punch_power": ["The Hammer", "The Fist", "The Knuckle", "The Sledgehammer"],
            "kick_power": ["The Kick", "The Boot", "The Shin", "The Baseball Bat"],
            "submission_offense": ["The Choker", "The Trap", "The Python", "The Anaconda"],
            "takedown_offense": ["The Takedown", "The Dump", "The Lift", "The Slam"],
            "chin": ["The Chin", "The Iron Jaw", "The Concrete Head", "The Anvil"],
            "durability": ["The Tank", "The Wall", "The Fortress", "The Bunker"],
            "cardio": ["The Engine", "The Machine", "The Energizer", "The Marathon"],
            "speed_explosiveness": ["The Flash", "The Bolt", "The Spark", "The Comet"],
            "fight_iq": ["The Brain", "The Professor", "The Architect", "The Chessmaster"],
            "head_movement": ["The Ghost", "The Shadow", "The Mirage", "The Phantom"],
            "footwork": ["The Dancer", "The Ballerina", "The Tap Dancer", "The Prancer"],
            "strength": ["The Ox", "The Bull", "The Beast", "The Titan"],
            "recovery_rate": ["The Phoenix", "The Comeback Kid", "The Survivor", "The Indestructible"],
        }
        for attr_name, nick_list in attr_nick_map.items():
            val = attrs.get(attr_name, 50)
            if val > standout_val and val >= 65:
                standout = attr_name
                standout_val = val
        if standout:
            return rng.choice(attr_nick_map[standout])

    # 20% chance: personality-based (requires pers dict)
    if pers and rng.random() < 0.20:
        pers_nick_map = {
            "aggression": [("The Predator", 75), ("The Berserker", 80), ("The aggressor", 70)],
            "composure": [("Ice", 75), ("The Cool Hand", 80), ("The Stoic", 70)],
            "killer_instinct": [("The Finisher", 75), ("The Killer", 80), ("The Executioner", 85)],
            "discipline": [("The Methodical", 75), ("The Technician", 80), ("The Perfectionist", 85)],
            "charisma": [("The Showman", 75), ("The Star", 80), ("The Spotlight", 85)],
            "grit": [("The Grinder", 75), ("The Iron Will", 80), ("The Indomitable", 85)],
        }
        for trait_name, options in pers_nick_map.items():
            val = pers.get(trait_name, 50)
            for nick, threshold in options:
                if val >= threshold:
                    return nick

    # 30% chance: adjective + animal noun ("The Iron Viper")
    if rng.random() < 0.30:
        adj = rng.choice(_NICK_ADJECTIVES).strip()
        noun = rng.choice(_NICK_NOUNS_ANIMAL)
        return f"The {adj} {noun}"

    # Fallback: single word
    return rng.choice(_NICK_SINGLE_WORDS)
#
# `generate_potential()` returns the fighter's growth ceiling. The
# distribution makes elite prospects rare and exciting to find:
#   - 10% elite (70-90): "that kid from Mexico" — the Talent Hunter
#     fantasy's payoff.
#   - 30% solid (50-69): can become contenders with development.
#   - 60% limited (25-49): journeymen who plateau early.
#
# This is the second dimension of scouting (style identity is the
# first — visible immediately via biased attributes). Potential is
# HIDDEN from the player until Task 18 (scouting) adds scout-estimated
# reports; for now, the player sees the raw value in the DB. The
# distribution's importance is for the underlying simulation: training
# camps (Task 16, future) will read `potential` and apply diminishing
# returns as attributes approach the ceiling, so a 25-potential
# journeyman physically cannot become a 90-punch-power killer no
# matter how many camps they do.
# ----------------------------------------------------------------

# Distribution buckets. The weights MUST sum to 100 (random.choices
# normalizes, but asserting the sum keeps the intent obvious).
# Range boundaries are INCLUSIVE on both ends.
POTENTIAL_DISTRIBUTION = [
    # (label, weight_percent, low, high)
    ("elite", 10, 70, 90),
    ("solid", 30, 50, 69),
    ("limited", 60, 25, 49),
]


def generate_potential():
    """Generate a `potential` value (0-100) using the rare-elite distribution.

    Distribution (Task pre-B1-fixes brief):
      - 10% chance: elite potential in [70, 90]
      - 30% chance: solid potential in [50, 69]
      - 60% chance: limited potential in [25, 49]

    Returns:
        int in [25, 90]. Always within the union of the three ranges
        above — i.e., values in [50, 69] are valid (solid), values
        below 50 are limited, values above 69 are elite. Values in
        [0, 24] and [91, 100] are NEVER returned (the brief's ranges
        deliberately exclude them — a 0-potential fighter would be
        unplayable, and a 91-100 potential would be too generous for
        the "elite" tier ceiling).

    Pure function — no I/O, no side effects. Callers (app.generate_fighter)
    INSERT the returned value into fighter_career.potential.

    The acceptance test scripts/test_pre_b1_fixes.py case C asserts
    the distribution holds over 1000 samples (within +/- 5% tolerance
    per tier).
    """
    labels = [bucket[0] for bucket in POTENTIAL_DISTRIBUTION]
    weights = [bucket[1] for bucket in POTENTIAL_DISTRIBUTION]
    chosen = random.choices(labels, weights=weights, k=1)[0]
    for label, _, low, high in POTENTIAL_DISTRIBUTION:
        if label == chosen:
            return random.randint(low, high)
    # Defensive: should never reach here (chosen always matches one
    # of the labels). Returns the middle-of-the-road 50 as a safe
    # fallback if it somehow does.
    return 50
