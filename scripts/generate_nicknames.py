#!/usr/bin/env python3
"""RESEED Step 1 — Generate realistic, mostly-unique nicknames for ~40%
of the 4000 fighters in the DB.

Strategy
  * Only ~40% of fighters get a nickname (use fighter_id % 5 in {0,1}
    → 40% deterministic slice).
  * For nicknamed fighters, the nickname is built from:
      - Top 1-2 attributes (elite descriptors for 80+ values)
      - Mental archetype (from CSV — Steady/Balanced, Grinder, etc.)
      - Career tier (Elite / Contender / Prospect / etc.)
      - Fighting style (Brawler / Wrestler / Striker ...)
  * Large word bank: 90+ adjectives × 90+ nouns = 8100+ combinations.
  * Collision avoidance: track usage; if a nickname has been used
    2+ times already, force a re-roll (try up to 5 alternatives).
  * A small pool of generic MMA nicknames ("The Hammer", "Pitbull",
    "Ice") is allowed to repeat up to 3 times each (realistic).
  * Target: <10% repetition among nicknamed fighters.
  * Output: writes directly to fighters.nickname (NULL otherwise).
"""
import csv
import os
import random
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))
CSV_PATH = PROJECT_DIR / "data" / "fighter_seed_rebuild.csv"

# ---------------------------------------------------------------------------
# Word banks — designed to be combinatorial (90×90 = 8100 unique pairs)
# ---------------------------------------------------------------------------

ADJECTIVES = [
    "Iron", "Steel", "Granite", "Marble", "Obsidian", "Crimson",
    "Golden", "Silver", "Bronze", "Copper", "Jade", "Onyx",
    "Midnight", "Twilight", "Dawn", "Dusk", "Aurora", "Eclipse",
    "Shadow", "Silent", "Savage", "Brutal", "Relentless", "Merciless",
    "Ruthless", "Fearless", "Restless", "Wild", "Feral", "Venomous",
    "Toxic", "Electric", "Lightning", "Thunder", "Storm", "Cyclone",
    "Hurricane", "Blizzard", "Frost", "Frozen", "Arctic", "Glacial",
    "Burning", "Blazing", "Smoldering", "Ashen", "Charred", "Molten",
    "Shattered", "Twisted", "Crooked", "Ancient", "Eternal", "Immortal",
    "Wise", "Quick", "Swift", "Rapid", "Heavy", "Massive",
    "Giant", "Colossal", "Compact", "Whispering", "Howling", "Roaring",
    "Snarling", "Biting", "Clawing", "Striking", "Crushing", "Smashing",
    "Shattering", "Lethal", "Deadly", "Fatal", "Final", "Sudden",
    "Surgical", "Precise", "Dead-Eye", "Cold-Blooded", "Hot-Headed",
    "Stone", "Diamond", "Platinum", "Titanium", "Velvet", "Silk",
    "Hammered", "Forged", "Tempered", "Polished", "Rusted", "Volatile",
    "Calm", "Patient", "Hidden", "Phantom", "Ghostly", "Ethereal",
]

NOUNS = [
    "Anvil", "Hammer", "Mallet", "Sledge", "Axe", "Hatchet", "Blade",
    "Sword", "Dagger", "Saber", "Machete", "Cleaver", "Scythe",
    "Viper", "Cobra", "Python", "Rattler", "Mamba", "Asp", "Boa",
    "Wolf", "Lynx", "Panther", "Leopard", "Tiger", "Lion", "Cougar",
    "Bear", "Grizzly", "Bison", "Bull", "Rhino", "Mammoth", "Boar",
    "Hawk", "Eagle", "Falcon", "Owl", "Raven", "Crow", "Vulture",
    "Shark", "Barracuda", "Stingray", "Octopus", "Squid", "Piranha", "Orca",
    "Scorpion", "Tarantula", "Wasp", "Hornet", "Centipede", "Mantis",
    "Storm", "Tempest", "Cyclone", "Tornado", "Hurricane", "Typhoon", "Monsoon",
    "Inferno", "Wildfire", "Eruption", "Avalanche", "Landslide", "Tsunami",
    "Phantom", "Specter", "Ghost", "Echo", "Mirage", "Illusion",
    "Bulldozer", "Juggernaut", "Titan", "Colossus", "Goliath", "Atlas",
    "Maverick", "Renegade", "Outlaw", "Bandit", "Marauder", "Pirate",
    "Sniper", "Assassin", "Hunter", "Stalker", "Predator", "Reaper",
    "Engine", "Machine", "Mechanism", "Forge", "Furnace", "Crucible",
    "Wall", "Fortress", "Citadel", "Bastion", "Bunker", "Rampart",
]

# Mental-archetype → adjective/noun overrides
MENTAL_OVERRIDE = {
    "Bottler - underperforms tools": (["Choker", "Fragile", "Cracking", "Cracking"], ["Glass", "Paper", "Tinder"]),
    "Fragile - fades under pressure": (["Fading", "Wilting", "Faltering", "Crumbling"], ["Candle", "Flame", "Spark"]),
    "Grinder - overperforms tools": (["Relentless", "Tireless", "Unyielding", "Relentless"], ["Engine", "Machine", "Millstone"]),
    "Winner - clutch": (["Clutch", "Cold-Blooded", "Pressure", "Iced"], ["Finisher", "Closer", "Executioner"]),
    "Steady/Balanced": (["Steady", "Solid", "Reliable", "Grounded"], ["Rock", "Anchor", "Boulder"]),
}

TIER_ADJ_BIAS = {
    "Elite":         ["Champion", "King", "Emperor", "Conqueror", "Dominant"],
    "Contender":     ["Hungry", "Rising", "Prime", "Peaking", "Ascendant"],
    "Prospect":      ["Rising", "Young", "Next-Gen", "Future", "Budding"],
    "Unproven":      ["Green", "Raw", "Unknown", "Wildcard", "Untested"],
    "Gatekeeper":    ["Tested", "Veteran", "Seasoned", "Battle-Scarred"],
    "Fringe":        ["Scrappy", "Underdog", "Long-Shot", "Cinderella"],
    "DecliningVet":  ["Fading", "Veteran", "Weathered", "Battle-Tested"],
}

STYLE_NOUN_BIAS = {
    "Brawler":          ["Brawler", "Slugger", "Bomber", "Knuckler", "Haymaker"],
    "Wrestler":         ["Wrestler", "Tackler", "Mat-Boss", "Smesh", "Takedown"],
    "Striker":          ["Striker", "Sniper", "Sharpshooter", "Marksman", "Stylist"],
    "Grappler":         ["Grappler", "Tangler", "Choker", "Squeezer", "Knot"],
    "Submission Specialist": ["Finisher", "Closer", "Vice", "Latchet", "Triangle"],
    "Counter-Striker":  ["Counter", "Echo", "Mirror", "Phantom", "Riposte"],
    "Balanced":         ["All-Rounder", "Complete", "Total", "Swiss-Army", "Toolkit"],
}

ATTR_DESCRIPTORS = {
    "punch_power":         ["Power", "Smasher", "Bomber"],
    "punch_accuracy":      ["Precision", "Sharpshooter", "Marksman"],
    "kick_power":          ["Kicker", "Boot", "Mule"],
    "kick_accuracy":       ["Sniper", "Sharpshooter", "Surgical"],
    "head_movement":       ["Slippery", "Phantom", "Ghost"],
    "footwork":            ["Footwork", "Dancer", "Drifter"],
    "cardio":              ["Engine", "Marathoner", "Diesel"],
    "takedown_offense":    ["Takedown", "Smesh", "Penetration"],
    "takedown_defense":    ["Wall", "Fortress", "Sprawl"],
    "submission_offense":  ["Sub-Master", "Closer", "Squeezer"],
    "submission_defense":  ["Escape", "Houdini", "Slippery"],
    "clinch_striking":     ["Clinch", "Dirty-Boxer", "Plummer"],
    "clinch_offense":      ["Dirty", "Plummer", "Smotherer"],
    "clinch_defense":      ["Sticky", "Trap", "Glue"],
    "top_control":         ["Smother", "Blanket", "Anvil"],
    "bottom_game":         ["Guard", "Sweeper", "Spider"],
    "cage_wrestling":      ["Fence", "Wall-Walker", "Pressure"],
    "scramble_ability":    ["Scrambler", "Tumbler", "Cat"],
    "fight_iq":            ["Brain", "Professor", "Tactician"],
    "adaptability":        ["Chameleon", "Shifter", "Mimic"],
    "speed_explosiveness": ["Lightning", "Bolt", "Detonator"],
    "strength":            ["Bull", "Hercules", "Titan"],
    "durability":          ["Iron-Chin", "Granite", "Bedrock"],
    "flexibility":         ["Rubber", "Elastic", "Contortionist"],
    "recovery_rate":       ["Phoenix", "Comeback", "Resurgent"],
    "chin":                ["Iron-Chin", "Bedrock", "Anvil"],
}

# Generic MMA nicknames — allowed to repeat up to 3 times each.
GENERIC_NICKNAMES = [
    "The Hammer", "Pitbull", "Ice", "The Titan", "The Bullet",
    "The Predator", "The Outlaw", "The Beast", "The Dragon",
    "The Hurricane", "The Sniper", "The Engine", "The Anvil",
    "The Wolf", "The Lion", "The Cobra", "The Bull", "The Phenom",
    "The Truth", "The Machine",
]

GENERIC_MAX_REPEAT = 3
COMBINATORIAL_MAX_REPEAT = 1  # never repeat a combinatorial nickname


def _top_attributes(attrs_dict, n=2, threshold=80):
    eligible = [(k, v) for k, v in attrs_dict.items()
                if v >= threshold and k in ATTR_DESCRIPTORS]
    eligible.sort(key=lambda x: -x[1])
    return [k for k, _ in eligible[:n]]


def _build_candidates(attrs, mental_arch, tier, style, rng, k=8):
    """Generate up to k candidate nicknames (in priority order).

    Each candidate is unique-ish; the caller picks the first that
    passes the usage check.
    """
    cands = []

    top_attrs = _top_attributes(attrs, n=2, threshold=80)

    # Pool of "preferred" parts based on fighter's profile
    pref_adj = set()
    pref_noun = set()

    for ta in top_attrs:
        for w in ATTR_DESCRIPTORS.get(ta, []):
            pref_adj.add(w)
            pref_noun.add(w)

    if mental_arch in MENTAL_OVERRIDE:
        adj_list, noun_list = MENTAL_OVERRIDE[mental_arch]
        for w in adj_list:
            pref_adj.add(w)
        for w in noun_list:
            pref_noun.add(w)

    if tier in TIER_ADJ_BIAS:
        for w in TIER_ADJ_BIAS[tier]:
            pref_adj.add(w)

    if style in STYLE_NOUN_BIAS:
        for w in STYLE_NOUN_BIAS[style]:
            pref_noun.add(w)

    pref_adj = list(pref_adj) if pref_adj else []
    pref_noun = list(pref_noun) if pref_noun else []

    # Candidate 1: "The {preferred_adj} {preferred_noun}"
    if pref_adj and pref_noun:
        cands.append(f"The {rng.choice(pref_adj)} {rng.choice(pref_noun)}")

    # Candidate 2: "{preferred_noun}" (single word)
    if pref_noun:
        cands.append(rng.choice(pref_noun))

    # Candidate 3-5: "The {random_adj} {preferred_noun}"
    if pref_noun:
        for _ in range(3):
            cands.append(f"The {rng.choice(ADJECTIVES)} {rng.choice(pref_noun)}")

    # Candidate 6-8: "The {random_adj} {random_noun}"
    for _ in range(3):
        cands.append(f"The {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}")

    # Candidate 9: pure adjective
    cands.append(rng.choice(ADJECTIVES))

    # Candidate 10: generic nickname
    cands.append(rng.choice(GENERIC_NICKNAMES))

    # Deduplicate while preserving order
    seen = set()
    out = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def generate():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}", file=sys.stderr)
        return 1

    csv_data = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                fid = int(row["fighter_id"])
            except (ValueError, KeyError):
                continue
            csv_data[fid] = {
                "tier": (row.get("career_tier") or "").strip(),
                "mental_arch": (row.get("mental_archetype") or "").strip(),
                "style": (row.get("style") or "").strip(),
            }

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.isolation_level = None
    conn.execute("BEGIN")

    # Wipe all existing nicknames first.
    conn.execute("UPDATE fighters SET nickname = NULL")

    SKILL_COLS = [
        "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
        "head_movement", "footwork", "cardio",
        "takedown_offense", "takedown_defense",
        "submission_offense", "submission_defense",
        "clinch_striking", "clinch_offense", "clinch_defense",
        "top_control", "bottom_game", "cage_wrestling", "scramble_ability",
        "fight_iq", "adaptability",
        "speed_explosiveness", "strength", "durability", "flexibility",
        "recovery_rate", "chin",
    ]
    col_select = ", ".join(SKILL_COLS)
    rows = conn.execute(
        f"SELECT fighter_id, {col_select} FROM fighter_attributes "
        "WHERE fighter_id BETWEEN 1 AND 4000 ORDER BY fighter_id"
    ).fetchall()

    rng = random.Random(20260815)

    nicknamed = 0
    skipped = 0
    nickname_counts = {}  # nickname → count

    # Generic-nickname counter (separate cap)
    generic_used = {n: 0 for n in GENERIC_NICKNAMES}

    GENERIC_SET = set(GENERIC_NICKNAMES)

    for row in rows:
        fid = row[0]
        attrs = {col: row[i + 1] for i, col in enumerate(SKILL_COLS)}

        if fid % 5 not in (0, 1):
            skipped += 1
            continue

        meta = csv_data.get(fid, {})
        tier = meta.get("tier", "")
        mental_arch = meta.get("mental_arch", "")
        style = meta.get("style", "")

        candidates = _build_candidates(attrs, mental_arch, tier, style, rng)

        chosen = None
        for cand in candidates:
            count = nickname_counts.get(cand, 0)
            if cand in GENERIC_SET:
                if generic_used[cand] < GENERIC_MAX_REPEAT:
                    chosen = cand
                    generic_used[cand] += 1
                    break
            else:
                if count < COMBINATORIAL_MAX_REPEAT:
                    chosen = cand
                    break

        if chosen is None:
            # Fallback: try random "The {adj} {noun}" combinations until
            # we find one that hasn't been used yet (combinatorial bank
            # is 90+×90+ = 8100+, so for 1600 fighters there's plenty
            # of headroom).
            for _ in range(50):
                cand = f"The {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
                if nickname_counts.get(cand, 0) < COMBINATORIAL_MAX_REPEAT:
                    chosen = cand
                    break
            if chosen is None:
                # Last-ditch: 3-word combination
                chosen = f"The {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)} {rng.choice(ADJECTIVES)}"

        conn.execute(
            "UPDATE fighters SET nickname = ? WHERE fighter_id = ?",
            (chosen, fid),
        )
        nicknamed += 1
        nickname_counts[chosen] = nickname_counts.get(chosen, 0) + 1

    conn.execute("COMMIT")
    conn.close()

    total = nicknamed
    distinct = len(nickname_counts)
    repeated = sum(1 for n, c in nickname_counts.items() if c > 1)
    max_count = max(nickname_counts.values()) if nickname_counts else 0
    repetition_rate = (total - distinct) / total * 100 if total else 0

    print(f"=== Nickname generation complete ===")
    print(f"  Total nicknamed   : {total}")
    print(f"  Skipped (no nick) : {skipped}")
    print(f"  Distinct nicknames: {distinct}")
    print(f"  Repeated nicknames: {repeated}")
    print(f"  Repetition rate   : {repetition_rate:.2f}% (target <10%)")
    print(f"  Most repeated     : {max_count}x")
    top5 = sorted(nickname_counts.items(), key=lambda x: -x[1])[:5]
    print(f"  Top 5 repeated    : {top5}")
    return 0


if __name__ == "__main__":
    sys.exit(generate())
