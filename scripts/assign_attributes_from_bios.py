#!/usr/bin/env python3
"""CAGE EMPIRE — Intelligent attribute assignment from fighter bios.

Takes the 4000 parsed fighter profiles (data/parsed_fighters.json)
and assigns 26 fighter_attributes + 20 fighter_personality traits +
potential based on the BIO TEXT, not just the style archetype.

This replaces the random archetype-based generation in
scripts/seed_world_phase3.py with a bio-driven approach. The bios
contain rich signal:
  - "champion", "title challenger", "title contender" → high potential
  - "flames out", "bust", "never quite" → low potential
  - "KO power", "knockout threat", "fight-ending" → high punch_power
  - "iron chin", "hard to rock", "durable" → high chin
  - "submission specialist", "grappling ace" → high submission_offense
  - "wrestling", "takedowns", "control" → high takedown_offense
  - "cardio machine", "paces", "endless" → high cardio
  - "veteran", "grizzled" → age-based adjustments
  - "prospect", "young gun" → high potential variance

Output: data/assigned_attributes.json — a list of 4000 dicts, each
with fighter_id + 26 attribute values + 20 personality values +
potential. Ready to be written to the world DB by
scripts/rebuild_world_with_bios.py.

CONVENTIONS compliance:
  §6  — Smoke test protocol. Run forensic_db_check.py after writing
        to verify the new attributes are balanced.
  §13 — Design Law: Discovery pillar — bio-driven attributes mean
        the fighter's bio ACCURATELY reflects their skills. The
        player reads the bio and trusts it.
  §14 — Voice Layer: this script writes RAW attribute values (0-100)
        to the DB. The voice layer (src/voice.py) translates these
        to descriptors when the UI displays them. No §14 violation —
        the player never sees raw numbers from this script.
  §18 — Effective ceiling: potential × age_factor × health_factor ×
        personality_factor. Potential is NOT guaranteed success.
        This script assigns potential based on bio language, but
        the effective ceiling is computed elsewhere.
"""
import json
import re
import random
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_DIR / "data" / "parsed_fighters.json"
OUTPUT_FILE = PROJECT_DIR / "data" / "assigned_attributes.json"

# ============================================================
# ATTRIBUTE COLUMNS (26 — per fighter_attributes table)
# ============================================================
ATTRIBUTE_COLUMNS = [
    "punch_power", "cardio", "fight_iq", "chin", "punch_accuracy",
    "kick_power", "kick_accuracy", "head_movement", "footwork",
    "clinch_striking", "clinch_offense", "clinch_defense",
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "adaptability",
]

# ============================================================
# PERSONALITY COLUMNS (20 — per fighter_personality table)
# ============================================================
PERSONALITY_COLUMNS = [
    "aggression", "composure", "morale", "risk_taking", "killer_instinct",
    "grit", "discipline", "patience", "ambition", "loyalty",
    "charisma", "attention_seeking", "coachability", "professionalism",
    "ego", "resilience", "sportsmanship", "travel_comfort", "focus",
    "fatigue_tolerance",
]


# ============================================================
# BIO KEYWORD SIGNALS → attribute adjustments
# ============================================================
# Each entry: (regex_pattern, {attribute: adjustment})
# Adjustments are ADDITIVE — multiple matches stack.
# Positive = boost, negative = penalty.

BIO_SIGNALS = [
    # === STRIKING SIGNALS ===
    (r"one-punch knockout|fight-ending power|knockout threat|KO power|knockout artist",
     {"punch_power": +18, "speed_explosiveness": +8}),
    (r"iron chin|hard to rock|durable chin|takes a punch|eats shots",
     {"chin": +18, "durability": +10}),
    (r"heavy hands|concussive power|fight-ending",
     {"punch_power": +15}),
    (r"crisp striker|technical striker|clean strikes|precise",
     {"punch_accuracy": +12, "head_movement": +8, "footwork": +8}),
    (r"kicking game|devastating kicks|leg kicks|head kicks|calf kicks",
     {"kick_power": +15, "kick_accuracy": +12}),
    (r"footwork|angles|elusive|hard to hit|slips punches",
     {"footwork": +15, "head_movement": +12}),
    (r"head movement|slips|weaves|rolls",
     {"head_movement": +15}),
    (r"fast hands|hand speed|lightning hands|quick hands",
     {"speed_explosiveness": +15, "punch_accuracy": +8}),
    (r"counter.?striker|counter punching|fights going backwards",
     {"fight_iq": +12, "head_movement": +10, "punch_accuracy": +8}),

    # === GRAPPLING / WRESTLING SIGNALS ===
    (r"submission specialist|submission ace|jiu jitsu|BJJ|grappling ace",
     {"submission_offense": +18, "scramble_ability": +10, "bottom_game": +10}),
    (r"wrestling|wrestler|takedown|double leg|single leg|shot",
     {"takedown_offense": +15, "cage_wrestling": +12, "top_control": +10}),
    (r"control specialist|smothering|grinds|top game|ground and pound|GnP",
     {"top_control": +15, "cage_wrestling": +10}),
    (r"scramble|scrambling|transitions|chain wrestling",
     {"scramble_ability": +15, "adaptability": +8}),
    (r"submission defense|hard to submit|never been submitted",
     {"submission_defense": +15}),
    (r"takedown defense|sprawl|stops takedowns|defensive wrestling",
     {"takedown_defense": +15}),
    (r"clinch|dirty boxing|against the cage|wall and stall",
     {"clinch_offense": +12, "clinch_defense": +10, "cage_wrestling": +10}),

    # === PHYSICAL / ATHLETIC SIGNALS ===
    (r"cardio machine|endless|never tires|paces|deep gas tank|cardio for days",
     {"cardio": +18, "fatigue_tolerance": +10}),
    (r"explosive|athletic freak|freak athlete|explosiveness",
     {"speed_explosiveness": +15, "strength": +8}),
    (r"strong|powerful|brute strength|physical specimen",
     {"strength": +15, "durability": +8}),
    (r"flexible|agile|nimble|rubber guard",
     {"flexibility": +15, "scramble_ability": +8}),
    (r"recovery|recovers quickly|bounces back",
     {"recovery_rate": +15}),
    (r"iron body|takes punishment|eats shots|warrior",
     {"durability": +15, "chin": +8}),

    # === MENTAL / FIGHT IQ SIGNALS ===
    (r"fight IQ|high IQ|smart fighter|cerebral|strategist|game planner",
     {"fight_iq": +18, "adaptability": +10}),
    (r"adaptable|adjusts|makes adjustments|reads the fight",
     {"adaptability": +15, "fight_iq": +8}),
    (r"veteran savvy|experienced|crafty veteran|wily",
     {"fight_iq": +12, "composure": +10}),
    (r"prospect|young gun|up and comer|rising star|blue chip",
     {}),  # no direct attribute boost — handled via potential + age
    (r"raw|green|needs development|work in progress|rough around the edges",
     {"fight_iq": -8, "adaptability": -5}),

    # === CAREER STAGE / POTENTIAL SIGNALS ===
    (r"champion|title holder|reigning|defends the title|title reign",
     {"potential": +10}),  # champions are elite
    (r"title challenger|title contender|top contender|number one contender",
     {"potential": +5}),
    (r"future champion|could be champion|champion in waiting",
     {"potential": +15}),
    (r"flames out|bust|never quite|never lived up|unfulfilled|wasted potential",
     {"potential": -15}),
    (r"journeyman|gatekeeper|career backup|test the prospects",
     {"potential": -5}),
    (r"elite|world-class|top of the division|best in the world",
     {"potential": +12}),

    # === PERSONALITY SIGNALS (from bio) ===
    (r"aggressive|presses the pace|comes forward|swarms|pressure fighter",
     {"aggression": +15, "risk_taking": +8}),
    (r"calm|composed|patient|measured|unflappable|ice in veins",
     {"composure": +15, "patience": +10}),
    (r"showman|entertainer|crowd pleaser|fans love|charismatic|crowd favorite",
     {"charisma": +15, "attention_seeking": +12}),
    (r"professional|class act|respects the game|humble|no nonsense",
     {"professionalism": +15, "sportsmanship": +12}),
    (r"controversial|trash talk|brash|cocky|arrogant|ego",
     {"ego": +15, "attention_seeking": +10}),
    (r"gritty|grinder|never gives up|warrior|tough|resilient",
     {"grit": +15, "resilience": +12}),
    (r"disciplined|hard worker|gym rat|dedicated|obsessive",
     {"discipline": +15, "work_ethic": +12} if "work_ethic" in PERSONALITY_COLUMNS else {"discipline": +15}),
    (r"killer instinct|finishes|goes for the kill|finishes hurt fighters",
     {"killer_instinct": +15}),
    (r"loyal|gym loyal|stays with|loyal to",
     {"loyalty": +15}),
    (r"coachable|coachable|listens to corner|takes direction",
     {"coachability": +15}),
]


# ============================================================
# STYLE ARCHETYPE BASE PATTERNS
# ============================================================
# Each style archetype gets a base attribute distribution. Bios
# then apply ADDITIVE adjustments on top.

STYLE_BASES = {
    "Striker": {
        "punch_power": 65, "punch_accuracy": 65, "kick_power": 60, "kick_accuracy": 60,
        "head_movement": 60, "footwork": 60, "cardio": 55,
        "takedown_offense": 35, "takedown_defense": 45,
        "submission_offense": 30, "submission_defense": 40,
        "clinch_striking": 55, "clinch_offense": 40, "clinch_defense": 45,
        "top_control": 35, "bottom_game": 35, "cage_wrestling": 40,
        "scramble_ability": 45, "fight_iq": 55, "adaptability": 50,
        "speed_explosiveness": 60, "strength": 50, "durability": 55,
        "flexibility": 50, "recovery_rate": 55,
    },
    "Counter-Striker": {
        "punch_power": 60, "punch_accuracy": 70, "kick_power": 55, "kick_accuracy": 60,
        "head_movement": 70, "footwork": 70, "cardio": 55,
        "takedown_offense": 35, "takedown_defense": 50,
        "submission_offense": 30, "submission_defense": 40,
        "clinch_striking": 50, "clinch_offense": 40, "clinch_defense": 45,
        "top_control": 35, "bottom_game": 35, "cage_wrestling": 40,
        "scramble_ability": 50, "fight_iq": 70, "adaptability": 60,
        "speed_explosiveness": 65, "strength": 50, "durability": 55,
        "flexibility": 55, "recovery_rate": 55,
    },
    "Brawler": {
        "punch_power": 75, "punch_accuracy": 45, "kick_power": 50, "kick_accuracy": 40,
        "head_movement": 35, "footwork": 35, "cardio": 50,
        "takedown_offense": 40, "takedown_defense": 45,
        "submission_offense": 35, "submission_defense": 45,
        "clinch_striking": 60, "clinch_offense": 55, "clinch_defense": 55,
        "top_control": 45, "bottom_game": 35, "cage_wrestling": 50,
        "scramble_ability": 40, "fight_iq": 40, "adaptability": 40,
        "speed_explosiveness": 55, "strength": 65, "durability": 70,
        "flexibility": 40, "recovery_rate": 55,
    },
    "Wrestler": {
        "punch_power": 50, "punch_accuracy": 50, "kick_power": 40, "kick_accuracy": 40,
        "head_movement": 40, "footwork": 45, "cardio": 60,
        "takedown_offense": 75, "takedown_defense": 75,
        "submission_offense": 50, "submission_defense": 60,
        "clinch_striking": 50, "clinch_offense": 65, "clinch_defense": 70,
        "top_control": 75, "bottom_game": 50, "cage_wrestling": 75,
        "scramble_ability": 65, "fight_iq": 55, "adaptability": 55,
        "speed_explosiveness": 60, "strength": 70, "durability": 60,
        "flexibility": 45, "recovery_rate": 60,
    },
    "Grappler": {
        "punch_power": 45, "punch_accuracy": 50, "kick_power": 40, "kick_accuracy": 45,
        "head_movement": 40, "footwork": 45, "cardio": 60,
        "takedown_offense": 65, "takedown_defense": 60,
        "submission_offense": 75, "submission_defense": 70,
        "clinch_striking": 45, "clinch_offense": 65, "clinch_defense": 65,
        "top_control": 70, "bottom_game": 75, "cage_wrestling": 60,
        "scramble_ability": 75, "fight_iq": 60, "adaptability": 60,
        "speed_explosiveness": 50, "strength": 55, "durability": 55,
        "flexibility": 65, "recovery_rate": 60,
    },
    "Submission Specialist": {
        "punch_power": 40, "punch_accuracy": 50, "kick_power": 40, "kick_accuracy": 45,
        "head_movement": 40, "footwork": 45, "cardio": 60,
        "takedown_offense": 60, "takedown_defense": 55,
        "submission_offense": 85, "submission_defense": 75,
        "clinch_striking": 40, "clinch_offense": 60, "clinch_defense": 60,
        "top_control": 70, "bottom_game": 80, "cage_wrestling": 55,
        "scramble_ability": 80, "fight_iq": 65, "adaptability": 65,
        "speed_explosiveness": 50, "strength": 50, "durability": 50,
        "flexibility": 75, "recovery_rate": 60,
    },
    "Balanced": {
        "punch_power": 55, "punch_accuracy": 55, "kick_power": 50, "kick_accuracy": 50,
        "head_movement": 50, "footwork": 50, "cardio": 55,
        "takedown_offense": 55, "takedown_defense": 55,
        "submission_offense": 55, "submission_defense": 55,
        "clinch_striking": 55, "clinch_offense": 55, "clinch_defense": 55,
        "top_control": 55, "bottom_game": 55, "cage_wrestling": 55,
        "scramble_ability": 55, "fight_iq": 60, "adaptability": 60,
        "speed_explosiveness": 55, "strength": 55, "durability": 55,
        "flexibility": 55, "recovery_rate": 55,
    },
}

# ============================================================
# PERSONALITY ARCHETYPE BASE PATTERNS
# ============================================================

PERSONALITY_BASES = {
    "Aggressive": {
        "aggression": 75, "composure": 40, "risk_taking": 70, "killer_instinct": 70,
        "patience": 35, "ego": 55, "focus": 55,
    },
    "Calm": {
        "aggression": 45, "composure": 75, "risk_taking": 45, "killer_instinct": 55,
        "patience": 75, "ego": 45, "focus": 70,
    },
    "Methodical": {
        "aggression": 50, "composure": 65, "risk_taking": 45, "killer_instinct": 60,
        "patience": 75, "ego": 45, "focus": 75,
    },
    "Showman": {
        "aggression": 60, "composure": 50, "risk_taking": 65, "killer_instinct": 60,
        "patience": 40, "ego": 75, "charisma": 75, "attention_seeking": 75, "focus": 50,
    },
    "Quiet Professional": {
        "aggression": 50, "composure": 70, "risk_taking": 40, "killer_instinct": 55,
        "patience": 70, "ego": 35, "charisma": 45, "attention_seeking": 30,
        "professionalism": 75, "focus": 70,
    },
}


# ============================================================
# AGE-BASED ADJUSTMENTS (career arc)
# ============================================================
# Per career_arc.py: prime is 28-32, developing 18-27, declining 33+.
# These adjustments reflect where the fighter is in their career.

def age_adjustments(age):
    """Return attribute adjustments based on age (career arc)."""
    if age <= 22:
        # Young — developing, raw, athletic but low fight IQ
        return {
            "speed_explosiveness": +8, "flexibility": +8, "recovery_rate": +8,
            "fight_iq": -10, "adaptability": -8, "durability": -5,
        }
    elif age <= 27:
        # Entering prime — slight boosts, still developing IQ
        return {
            "speed_explosiveness": +4, "recovery_rate": +4,
            "fight_iq": -3, "adaptability": -2,
        }
    elif age <= 32:
        # Prime — peak across the board
        return {
            "fight_iq": +5, "adaptability": +3, "strength": +3,
        }
    elif age <= 37:
        # Declining — losing speed, gaining savvy
        return {
            "speed_explosiveness": -8, "recovery_rate": -8, "cardio": -5,
            "durability": -5, "flexibility": -5,
            "fight_iq": +8, "adaptability": +5,
        }
    else:
        # Veteran — significant physical decline, high IQ
        return {
            "speed_explosiveness": -15, "recovery_rate": -15, "cardio": -10,
            "durability": -10, "flexibility": -10, "strength": -5,
            "fight_iq": +12, "adaptability": +8, "composure": +5,
        }


# ============================================================
# POTENTIAL INFERENCE
# ============================================================

def infer_potential(bio, style_archetype, age, rng):
    """Infer a fighter's potential (0-100) from their bio.

    Potential is the fighter's CEILING — what they could become at
    their peak. It's NOT their current ability (which is lower for
    young fighters, closer to potential for prime fighters).

    Bio signals:
      - "champion" / "future champion" / "elite" → 80-95
      - "title challenger" / "contender" → 70-85
      - "prospect" / "rising star" → 60-85 (high variance)
      - "journeyman" / "gatekeeper" → 40-55
      - "flames out" / "bust" → 30-45
      - default → 45-70 (most fighters are mid-tier)
    """
    bio_lower = bio.lower()

    # Start with a base potential based on style (some styles have
    # higher ceilings in MMA meta — strikers/wrestlers typically)
    base = 55

    # Apply bio signals
    if re.search(r"future champion|could be champion|champion in waiting|generational|future-great", bio_lower):
        base = rng.randint(82, 95)
    elif re.search(r"champion|title holder|reigning|defends the title|title reign", bio_lower):
        base = rng.randint(78, 92)
    elif re.search(r"elite|world-class|top of the division|best in the world", bio_lower):
        base = rng.randint(75, 88)
    elif re.search(r"title challenger|title contender|top contender|number one contender", bio_lower):
        base = rng.randint(70, 82)
    elif re.search(r"prospect|young gun|up and comer|rising star|blue chip", bio_lower):
        # Prospects have high variance — could be elite or could bust
        base = rng.randint(58, 85)
    elif re.search(r"flames out|bust|never quite|never lived up|unfulfilled|wasted potential", bio_lower):
        base = rng.randint(30, 45)
    elif re.search(r"journeyman|gatekeeper|career backup|test the prospects", bio_lower):
        base = rng.randint(40, 55)
    else:
        # Default — most fighters are mid-tier
        base = rng.randint(45, 70)

    # Age adjustment: young fighters with "prospect" language get
    # a slight boost (they have time to develop); older fighters
    # with "veteran" language get a slight penalty (they're past
    # their ceiling)
    if age <= 22 and re.search(r"prospect|young gun|up and comer", bio_lower):
        base = min(95, base + rng.randint(0, 5))
    elif age >= 38 and re.search(r"veteran|grizzled|wily|crafty", bio_lower):
        base = max(35, base - rng.randint(0, 8))

    return max(20, min(95, base))


# ============================================================
# MAIN ASSIGNMENT FUNCTION
# ============================================================

def assign_attributes_for_fighter(fighter, rng):
    """Assign 26 attributes + 20 personality traits + potential for one fighter.

    Args:
        fighter: dict from parsed_fighters.json (has bio, style, personality, age, etc.)
        rng: random.Random instance (seeded per fighter for reproducibility)

    Returns:
        dict with fighter_id + 26 attribute values + 20 personality values + potential
    """
    bio = fighter.get("bio", "")
    bio_lower = bio.lower()
    style = fighter.get("style_archetype", "Balanced")
    personality = fighter.get("personality_archetype", "Calm")
    age = fighter.get("age", 28)

    # === STEP 1: Start with style archetype base ===
    attrs = dict(STYLE_BASES.get(style, STYLE_BASES["Balanced"]))

    # Fill any missing attributes with 50 (balanced default)
    for col in ATTRIBUTE_COLUMNS:
        if col not in attrs:
            attrs[col] = 50

    # === STEP 2: Apply personality archetype base ===
    pers = dict(PERSONALITY_BASES.get(personality, {}))
    for col in PERSONALITY_COLUMNS:
        if col not in pers:
            pers[col] = 50  # default

    # === STEP 3: Apply bio keyword signals ===
    bio_adjustments_attrs = defaultdict(int)
    bio_adjustments_pers = defaultdict(int)

    for pattern, adjustments in BIO_SIGNALS:
        if re.search(pattern, bio_lower):
            for key, adj in adjustments.items():
                if key == "potential":
                    # potential is handled separately
                    continue
                if key in attrs:
                    bio_adjustments_attrs[key] += adj
                elif key in pers:
                    bio_adjustments_pers[key] += adj

    # Apply bio adjustments
    for key, adj in bio_adjustments_attrs.items():
        attrs[key] = attrs.get(key, 50) + adj
    for key, adj in bio_adjustments_pers.items():
        pers[key] = pers.get(key, 50) + adj

    # === STEP 4: Apply age-based adjustments ===
    age_adj = age_adjustments(age)
    for key, adj in age_adj.items():
        if key in attrs:
            attrs[key] = attrs[key] + adj
        elif key in pers:
            pers[key] = pers[key] + adj

    # === STEP 5: Add small random variance (±5) for uniqueness ===
    for col in attrs:
        attrs[col] = attrs[col] + rng.randint(-5, 5)
    for col in pers:
        pers[col] = pers[col] + rng.randint(-5, 5)

    # === STEP 6: Clamp all values to 0-100 ===
    for col in attrs:
        attrs[col] = max(5, min(100, attrs[col]))  # floor at 5 (not 0 — even bad fighters have some skill)
    for col in pers:
        pers[col] = max(5, min(100, pers[col]))

    # === STEP 7: Infer potential ===
    potential = infer_potential(bio, style, age, rng)

    # === STEP 8: Adjust attributes toward potential ===
    # The fighter's CURRENT ability should be below their potential
    # (they haven't reached their ceiling yet). For young fighters,
    # current ability is much lower than potential. For prime fighters,
    # current ability is close to potential. For declining fighters,
    # current ability was at potential but is now declining.
    if age <= 22:
        # Young — current ability is 60-75% of potential
        factor = rng.uniform(0.60, 0.75)
    elif age <= 27:
        # Entering prime — 75-88% of potential
        factor = rng.uniform(0.75, 0.88)
    elif age <= 32:
        # Prime — 88-98% of potential
        factor = rng.uniform(0.88, 0.98)
    elif age <= 37:
        # Declining — 80-92% of potential (was at peak, now declining)
        factor = rng.uniform(0.80, 0.92)
    else:
        # Veteran — 70-85% of potential (significant decline)
        factor = rng.uniform(0.70, 0.85)

    # Scale attributes toward potential (but don't push them above it)
    for col in attrs:
        # The fighter's potential sets a soft ceiling
        ceiling = potential
        current = attrs[col]
        # If current is above ceiling, pull it down toward ceiling
        if current > ceiling:
            attrs[col] = max(ceiling - rng.randint(0, 5), current - rng.randint(5, 15))
        # Else, scale toward ceiling by the factor
        else:
            attrs[col] = int(current + (ceiling - current) * (1 - factor))

    # Re-clamp
    for col in attrs:
        attrs[col] = max(5, min(100, attrs[col]))

    # === BUILD RESULT ===
    result = {"fighter_id": fighter["fighter_id"]}
    result.update(attrs)
    result["_personality"] = pers  # personality traits (separate from attributes)
    result["potential"] = potential
    return result


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 72)
    print("CAGE EMPIRE — Intelligent Attribute Assignment from Bios")
    print("=" * 72)
    print(f"Input:  {INPUT_FILE}")
    print(f"Output: {OUTPUT_FILE}")
    print()

    if not INPUT_FILE.exists():
        print(f"FATAL: input file not found. Run scripts/parse_fighter_profiles.py first.")
        sys.exit(2)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        fighters = json.load(f)
    print(f"Loaded {len(fighters)} parsed fighters")

    # Assign attributes for each fighter
    print(f"\nAssigning attributes...")
    results = []
    for i, fighter in enumerate(fighters):
        # Deterministic RNG seeded by fighter_id (per Task 19 decision log)
        rng = random.Random(fighter["fighter_id"] * 31 + 17)
        result = assign_attributes_for_fighter(fighter, rng)
        results.append(result)
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(fighters)}...")

    print(f"\nAssigned attributes for {len(results)} fighters")

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size:,} bytes)")

    # === BALANCE ANALYSIS ===
    print("\n" + "=" * 72)
    print("BALANCE ANALYSIS")
    print("=" * 72)

    # Attribute distribution
    print("\n--- Attribute distribution (across all 4000 fighters) ---")
    for col in ATTRIBUTE_COLUMNS:
        values = [r[col] for r in results]
        avg = sum(values) / len(values)
        mn = min(values)
        mx = max(values)
        # Distribution buckets
        buckets = {"0-24": 0, "25-39": 0, "40-59": 0, "60-74": 0, "75-89": 0, "90-100": 0}
        for v in values:
            if v < 25: buckets["0-24"] += 1
            elif v < 40: buckets["25-39"] += 1
            elif v < 60: buckets["40-59"] += 1
            elif v < 75: buckets["60-74"] += 1
            elif v < 90: buckets["75-89"] += 1
            else: buckets["90-100"] += 1
        print(f"  {col:25s} avg={avg:5.1f} min={mn:3d} max={mx:3d}  "
              f"dist: {buckets}")

    # Potential distribution
    print("\n--- Potential distribution ---")
    potentials = [r["potential"] for r in results]
    pot_buckets = {"0-24": 0, "25-39": 0, "40-59": 0, "60-74": 0, "75-89": 0, "90-100": 0}
    for p in potentials:
        if p < 25: pot_buckets["0-24"] += 1
        elif p < 40: pot_buckets["25-39"] += 1
        elif p < 60: pot_buckets["40-59"] += 1
        elif p < 75: pot_buckets["60-74"] += 1
        elif p < 90: pot_buckets["75-89"] += 1
        else: pot_buckets["90-100"] += 1
    avg_pot = sum(potentials) / len(potentials)
    print(f"  avg={avg_pot:5.1f}  min={min(potentials)}  max={max(potentials)}")
    print(f"  distribution: {pot_buckets}")

    # Style-based averages
    print("\n--- Average attribute by style archetype ---")
    style_avgs = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(results):
        style = fighters[i]["style_archetype"]
        for col in ATTRIBUTE_COLUMNS:
            style_avgs[style][col].append(r[col])
    for style in sorted(style_avgs.keys()):
        print(f"  {style}:")
        for col in ["punch_power", "takedown_offense", "submission_offense", "fight_iq", "cardio"]:
            avg = sum(style_avgs[style][col]) / len(style_avgs[style][col])
            print(f"    {col:25s} avg={avg:5.1f}")


if __name__ == "__main__":
    main()
