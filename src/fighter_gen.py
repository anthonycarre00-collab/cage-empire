"""Fighter generation primitives (added in v2.0.0, Task 14.5+14.6+14.7).

Three pure-ish functions used by:

  * `seed_data.py` — to backfill the 5 existing seeded fighters with the
    21 new attribute columns, 17 new personality columns, and 14 new
    fighters-table columns added in this schema expansion.
  * `app.generate_fighter()` — Task 14's regen function. Previously it
    INSERTed all-50 defaults; now it uses these functions to produce
    archetype-biased attribute and personality blocks so regen
    prospects feel like real fighters, not generic 50s.

The bias system:

  * `style_archetypes.attribute_bias` is a JSON column holding a dict
    like `{"punch_power": 15, "takedown_defense": -10}`. When
    `generate_attribute_block(archetype_id, conn)` is called with a
    non-None archetype_id and a live connection, the bias is loaded
    and applied to the base value of 50.
  * `personality_archetypes.trait_bias` is the same idea for the
    personality block.
  * The formula for every attribute/trait is:

        value = clamp(50 + bias.get(col, 0) + random.randint(-8, 8), 0, 100)

    The +/-8 noise floor keeps fighters within an archetype distinct
    (no two Brawlers will be identical) while the bias gives the
    archetype its identity (Brawlers average ~70 punch_power, ~65 chin).

The 3 functions are deliberately kept side-effect-free (no DB writes).
Callers own the INSERT/UPDATE so the same primitives can be reused by
the seed (backfill), by regen (Task 14), and by future tasks (Task 18
scouting reports will generate "scout-estimated" attribute blocks that
the player can compare against the real values).

Design Law check (CONVENTIONS.md §13):
  - Discovery (Fantasy 1: Talent Hunter): the bias system means regen
    prospects arrive with a *style identity* — a Brawler replacement
    for a retiring Brawler feels like a Brawler, not a generic 50/50
    prospect. Players can spot "this kid hits hard" from day one.
  - Growth (Fantasy 2 + 3): the 25 attributes are the substrate that
    future training camps (Task 16), scouting (Task 18), and the voice
    layer (Task 19) will grow, scout, and describe. Without these
    columns, those tasks have nothing to act on.
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


def generate_physical_block():
    """Generate height_cm, reach_cm, stance, handedness for a fighter.

    Per the task brief (STAGES.md §14.5):
      - Height: normal distribution around 178cm, bounded to [165, 195].
        Uses random.gauss(178, 7) and clamps to the bounds. The std of
        7 means ~68% of fighters fall in [171, 185], ~95% in [164, 192]
        — close to a real-life MMA roster distribution.
      - Reach: height_cm + random.randint(-5, 10). Most fighters have
        a reach close to their height (apes-index ~0); the +10/-5
        skew lets the occasional long-armed outlier emerge.
      - Stance: 80% orthodox, 15% southpaw, 5% switch. Matches the
        real-world MMA distribution.
      - Handedness: 85% right, 10% left, 5% ambidextrous.

    Returns:
        dict with keys: height_cm (int 165-195), reach_cm (int),
        stance (str), handedness (str). reach_cm is computed from
        height_cm and may fall outside [165, 195] — that's correct
        (a 165cm fighter with a long reach could have reach=175).
    """
    height_cm = _clamp(int(round(random.gauss(178, 7))), 165, 195)
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
