#!/usr/bin/env python3
"""Generate fighter image generation prompts for ALL active fighters.

Outputs a single file with one AI image generation prompt per fighter.
Each prompt includes:
  - Unique fighter ID
  - Physical description (height, weight class, nationality, ethnicity)
  - Age, gender, stance, handedness
  - Style archetype (informs body type, posture, attire)
  - Personality archetype (informs facial expression)
  - Nickname (if any)
  - Consistent photorealistic style directives
  - Full body MMA pose OR portrait expression (alternating)
  - Varied ring attire (shorts, gloves, colors)
  - Varied backgrounds (cage, gym, backstage, ring walkout)

The prompts are designed for Midjourney / DALL-E / Stable Diffusion.
Each prompt is self-contained — the image gen doesn't need any other
context.

Usage:
    python scripts/generate_image_prompts.py
"""
import sqlite3
import json
import random
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
OUTPUT_PATH = PROJECT_DIR / "download" / "fighter_image_prompts.txt"

random.seed(20260723)

# Consistent style directives for ALL prompts
STYLE_DIRECTIVE = (
    "photorealistic, ultra-detailed, professional photography, "
    "8K, sharp focus, studio lighting, MMA fighter portrait, "
    "athletic physique, realistic skin texture, professional quality"
)

# Attire variations
ATTIRE_VARIATIONS = [
    "black MMA shorts with red trim, red 4oz gloves, barefoot",
    "blue fight shorts with white stripe, blue gloves, barefoot",
    "white shorts with black logo, black gloves, barefoot",
    "green shorts with gold trim, black gloves, barefoot",
    "black shorts with white stripes, red gloves, barefoot",
    "red shorts with black trim, black gloves, barefoot",
    "gray shorts with blue accents, blue gloves, barefoot",
    "camo shorts, black gloves, barefoot",
    "gold shorts with black trim, black gloves, barefoot",
    "navy blue shorts with white stars, red gloves, barefoot",
]

# Background variations
BACKGROUND_VARIATIONS = [
    "standing in an MMA cage with chain-link fence background",
    "in a professional gym with heavy bags and training equipment",
    "backstage corridor with concrete walls and dim lighting",
    "walking out to the cage with crowd visible in background",
    "center of the octagon under bright arena lights",
    "in a dark studio with dramatic side lighting",
    "against a brick wall in an urban setting",
    "in a locker room with lockers and bench visible",
]

# Pose variations (full body)
POSE_VARIATIONS_FULL_BODY = [
    "standing in fighting stance with fists raised, weight on back foot",
    "mid-kick with right leg extended, arms in guard position",
    "standing tall with arms crossed, confident expression",
    "crouched in wrestling stance, hands extended for a takedown",
    "shadow boxing with left jab extended, right hand at chin",
    "standing with one fist raised toward camera, other at side",
    "in a wide stance with both fists up, ready to engage",
    "walking forward with hands at sides, intense stare",
    "kneeling on one knee with head bowed, fist on ground",
    "standing on the cage fence with arms raised in victory",
]

# Portrait expression variations
EXPRESSION_VARIATIONS = [
    "intense stare directly at camera, jaw clenched, no smile",
    "slight smirk, one eyebrow raised, confident look",
    "stone-faced, unblinking, intimidating presence",
    "slight smile, relaxed but alert, warrior's calm",
    "fierce expression, nostrils flared, ready to fight",
    "cold, calculating eyes, slight frown, focused",
    "wide-eyed intensity, mouth slightly open, aggressive",
    "serene expression, almost peaceful, zen-like calm",
    "snarling, teeth slightly visible, pure aggression",
    "head slightly tilted, evaluating, analytical gaze",
]

# Body type descriptions by weight class
BODY_TYPE_BY_WC = {
    "Heavyweight": "massive, heavily muscled, broad-shouldered, powerful build",
    "Light Heavyweight": "very muscular, athletic, well-defined, strong frame",
    "Middleweight": "lean and muscular, defined abs, athletic build",
    "Welterweight": "lean, wiry, cut definition, fast-twitch build",
    "Lightweight": "lean and cut, low body fat, compact muscular build",
    "Featherweight": "very lean, sinewy, low body fat, angular features",
    "Bantamweight": "small but extremely lean, defined, compact",
    "Flyweight": "small, lean, wiry, very low body fat",
    "Strawweight": "small, petite but toned, athletic (female)",
    "Atomweight": "very small, petite, lean (female)",
}

# Ethnicity hints by nation (for facial features)
ETHNICITY_BY_NATION = {
    "United States": "American, diverse ethnicity",
    "Brazil": "Brazilian, mixed Afro-European-Indigenous features",
    "Japan": "Japanese, East Asian features",
    "Russia": "Russian, Slavic features",
    "United Kingdom": "British, Celtic/Anglo-Saxon features",
    "Mexico": "Mexican, Mestizo features",
    "Canada": "Canadian, diverse ethnicity",
    "Australia": "Australian, diverse ethnicity",
    "Ireland": "Irish, Celtic features, fair skin",
    "Nigeria": "Nigerian, West African features",
    "France": "French, European features",
    "Germany": "German, Central European features",
    "Poland": "Polish, Slavic features",
    "Sweden": "Swedish, Nordic features, fair complexion",
    "South Korea": "Korean, East Asian features",
    "China": "Chinese, East Asian features",
    "Cuba": "Cuban, mixed Afro-Caribbean features",
    "Argentina": "Argentine, Latin European features",
    "Netherlands": "Dutch, Northern European features",
    "Dagestan": "Dagestani, Caucasus Mountain features",
}

# Style archetype body language hints
STYLE_BODY_LANGUAGE = {
    "Balanced": "balanced stance, composed posture",
    "Striker": "hands high in guard, weight forward on balls of feet",
    "Grappler": "lower center of gravity, hands ready to shoot",
    "Wrestler": "crouched slightly forward, powerful legs, hands low",
    "Brawler": "wide stance, chin tucked, hands loose and ready",
    "Counter-Striker": "weight on back foot, hands relaxed, ready to slip",
    "Submission Specialist": "lean and flexible, long limbs, relaxed posture",
}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    fighters = conn.execute(
        "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
        "f.gender, f.date_of_birth, f.height_cm, f.reach_cm, "
        "f.stance, f.handedness, "
        "sa.name AS style_archetype, pa.name AS personality_archetype, "
        "wc.name AS weight_class_name, wc.max_weight_kg, wc.gender AS wc_gender, "
        "n.name AS nation_name, "
        "fb.bio_text, fb.bio_tone "
        "FROM fighters f "
        "LEFT JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
        "LEFT JOIN personality_archetypes pa ON pa.personality_archetype_id=f.personality_archetype_id "
        "LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
        "LEFT JOIN nations n ON n.nation_id=f.birth_nation_id "
        "LEFT JOIN fighter_bios fb ON fb.fighter_id=f.fighter_id "
        "WHERE f.is_retired=0 "
        "ORDER BY f.fighter_id"
    ).fetchall()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("CAGE EMPIRE — Fighter Image Generation Prompts\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Total fighters: {len(fighters)}\n")
        f.write("=" * 80 + "\n\n")
        f.write("INSTRUCTIONS FOR IMAGE GENERATION:\n")
        f.write("Each prompt below is self-contained. Copy the entire prompt\n")
        f.write("(starting with 'PROMPT:') into your image generator.\n")
        f.write("Prompts alternate between full-body MMA poses and portrait\n")
        f.write("close-ups for variety. All prompts use a consistent\n")
        f.write("photorealistic style directive.\n")
        f.write("=" * 80 + "\n\n")

        for i, row in enumerate(fighters):
            (fid, first, last, nick, gender, dob, height_cm, reach_cm,
             stance, handedness, sa_name, pa_name, wc_name, wc_max_kg,
             wc_gender, nation_name, bio_text, bio_tone) = row

            # Compute age
            age = 30
            if dob:
                try:
                    age = 2026 - int(dob[:4])
                except (ValueError, TypeError):
                    pass

            # Build the prompt
            gender_str = "male" if gender == "male" else "female"
            ethnicity = ETHNICITY_BY_NATION.get(nation_name, "mixed ethnicity")
            body_type = BODY_TYPE_BY_WC.get(wc_name, "athletic MMA build")
            body_lang = STYLE_BODY_LANGUAGE.get(sa_name, "balanced MMA stance")
            attire = random.choice(ATTIRE_VARIATIONS)
            background = random.choice(BACKGROUND_VARIATIONS)

            # Alternate between full-body and portrait
            is_full_body = (i % 3 != 0)  # 2/3 full body, 1/3 portrait
            if is_full_body:
                pose = random.choice(POSE_VARIATIONS_FULL_BODY)
                shot_type = "full body shot"
            else:
                expr = random.choice(EXPRESSION_VARIATIONS)
                shot_type = "close-up portrait, head and shoulders"
                pose = expr

            # Build name string
            name_str = f"{first} {last}"
            if nick:
                name_str += f' "{nick}"'

            # Build the prompt text
            prompt_parts = [
                f"PROMPT #{fid}: {name_str}",
                f"[Fighter ID: {fid}]",
                f"A {age}-year-old {gender_str} MMA fighter of {ethnicity} descent",
                f"from {nation_name or 'unknown nation'}",
                f"Height: {height_cm}cm, Weight class: {wc_name} (max {wc_max_kg}kg)",
                f"Fight style: {sa_name}, Stance: {stance}",
                f"Body type: {body_type}",
                f"Physical: {height_cm}cm tall, {body_lang}",
                f"{shot_type}, {pose}",
                f"Wearing: {attire}",
                f"Background: {background}",
                STYLE_DIRECTIVE,
            ]

            prompt = ", ".join(prompt_parts) + "."

            # Add metadata
            f.write(f"--- FIGHTER #{fid}: {name_str} ---\n")
            f.write(f"Age: {age} | Gender: {gender_str} | Height: {height_cm}cm | "
                    f"WC: {wc_name} | Nation: {nation_name}\n")
            f.write(f"Style: {sa_name} | Personality: {pa_name} | "
                    f"Stance: {stance} | Handedness: {handedness}\n")
            if bio_text:
                f.write(f"Bio: {bio_text[:200]}...\n")
            f.write(f"\n{prompt}\n\n")

    print(f"Generated {len(fighters)} fighter image prompts to {OUTPUT_PATH}")
    print(f"File size: {OUTPUT_PATH.stat().st_size / 1024:.1f} KB")
    conn.close()


if __name__ == "__main__":
    main()
