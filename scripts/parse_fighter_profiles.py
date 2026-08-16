#!/usr/bin/env python3
"""CAGE EMPIRE — Parse fighter_image_prompts.txt → structured fighter data.

The supervisor attached 4000 fighter profiles (with rich bios, ages,
styles, personalities, stances, nations) in
download/fighter_image_prompts.txt. These should be the FOUNDATION
of the world DB — not the random archetype-based generation that
scripts/seed_world_phase3.py currently uses.

This parser extracts structured data from each fighter profile:
  - Fighter ID (1-4000)
  - Name + nickname
  - Age, gender, height, weight class, nation
  - Style archetype, personality archetype, stance, handedness
  - Full bio text (used for intelligent attribute assignment)

Output: a JSON file at data/parsed_fighters.json containing a list
of 4000 fighter dicts, ready for the attribute assignment script
(scripts/assign_attributes_from_bios.py).

CONVENTIONS compliance:
  §6  — Smoke test protocol. This is a parsing utility, not a test.
  §13 — Design Law: Discovery pillar — the fighter profiles are the
        raw material the player discovers. Better bios → better
        attribute assignment → better stories.
  §14 — Voice Layer: this script extracts RAW data only. The voice
        layer translates the resulting attributes to descriptors
        when the UI displays them.
"""
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_DIR / "download" / "fighter_image_prompts.txt"
OUTPUT_FILE = PROJECT_DIR / "data" / "parsed_fighters.json"


def parse_fighter_profiles(text):
    """Parse the fighter_image_prompts.txt file into a list of dicts.

    Each fighter profile looks like:
        --- FIGHTER #1: Hiroki Nakamura "Mist" ---
        Age: 18 | Gender: male | Height: 175cm | WC: Welterweight | Nation: Japan
        Style: Brawler | Personality: Calm | Stance: southpaw | Handedness: right
        Bio: There's a version of the future where Hiroki Nakamura 'Mist' is a champion. ...
        PROMPT #1: ... (ignored — image generation, not gameplay data)
    """
    fighters = []

    # Split on the fighter header pattern
    # Pattern: --- FIGHTER #N: Name "Nickname" ---  OR  --- FIGHTER #N: Name ---
    profile_pattern = re.compile(
        r'^---\s*FIGHTER\s*#(\d+):\s*(.+?)\s*---\s*$',
        re.MULTILINE
    )

    matches = list(profile_pattern.finditer(text))
    print(f"Found {len(matches)} fighter profiles")

    for i, match in enumerate(matches):
        fighter_id = int(match.group(1))
        name_line = match.group(2).strip()

        # Extract nickname if present (in quotes)
        nickname = None
        nick_match = re.search(r'"([^"]+)"', name_line)
        if nick_match:
            nickname = nick_match.group(1)
            name = name_line.replace(f'"{nickname}"', '').strip()
        else:
            name = name_line

        # Split name into first/last (some have only one name)
        name_parts = name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else name
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        # Get the content between this match and the next (or EOF)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        # Extract attributes line: "Age: 18 | Gender: male | Height: 175cm | WC: Welterweight | Nation: Japan"
        attrs_match = re.search(
            r'Age:\s*(\d+)\s*\|\s*Gender:\s*(\w+)\s*\|\s*Height:\s*(\d+)cm\s*\|\s*WC:\s*([\w\s]+?)\s*\|\s*Nation:\s*(.+?)$',
            block, re.MULTILINE
        )
        if not attrs_match:
            print(f"  WARNING: fighter #{fighter_id} ({name}) — could not parse attributes line")
            continue

        age = int(attrs_match.group(1))
        gender = attrs_match.group(2)
        height_cm = int(attrs_match.group(3))
        weight_class = attrs_match.group(4).strip()
        nation = attrs_match.group(5).strip()

        # Extract style line: "Style: Brawler | Personality: Calm | Stance: southpaw | Handedness: right"
        # Note: Personality can be multi-word ("Quiet Professional")
        style_match = re.search(
            r'Style:\s*([\w\s-]+?)\s*\|\s*Personality:\s*([\w\s]+?)\s*\|\s*Stance:\s*(\w+)\s*\|\s*Handedness:\s*(\w+)',
            block
        )
        if not style_match:
            print(f"  WARNING: fighter #{fighter_id} ({name}) — could not parse style line")
            continue

        style = style_match.group(1).strip()
        personality = style_match.group(2).strip()
        stance = style_match.group(3).strip()
        handedness = style_match.group(4).strip()

        # Extract bio: "Bio: ... " until the next "PROMPT #" line
        bio_match = re.search(r'Bio:\s*(.+?)(?=\n\s*PROMPT\s*#|\Z)', block, re.DOTALL)
        bio = bio_match.group(1).strip() if bio_match else ""
        # Truncate bio at "..." if it's a truncation point (the source uses "..." to indicate truncation)
        # Actually keep the full bio — it's the signal for attribute assignment

        fighter = {
            "fighter_id": fighter_id,
            "first_name": first_name,
            "last_name": last_name,
            "nickname": nickname,
            "age": age,
            "gender": gender,
            "height_cm": height_cm,
            "weight_class": weight_class,
            "nation": nation,
            "style_archetype": style,
            "personality_archetype": personality,
            "stance": stance,
            "handedness": handedness,
            "bio": bio,
        }
        fighters.append(fighter)

    return fighters


def main():
    print("=" * 72)
    print("CAGE EMPIRE — Fighter Profile Parser")
    print("=" * 72)
    print(f"Input:  {INPUT_FILE}")
    print(f"Output: {OUTPUT_FILE}")
    print()

    if not INPUT_FILE.exists():
        print(f"FATAL: input file not found at {INPUT_FILE}")
        sys.exit(2)

    text = INPUT_FILE.read_text(encoding="utf-8")
    print(f"Read {len(text):,} characters")

    fighters = parse_fighter_profiles(text)
    print(f"\nParsed {len(fighters)} fighters")

    if not fighters:
        print("FATAL: no fighters parsed — check the input file format")
        sys.exit(1)

    # Show a few samples
    print("\n=== Sample parsed fighters ===")
    for f in fighters[:3]:
        print(f"  #{f['fighter_id']}: {f['first_name']} {f['last_name']}"
              + (f" \"{f['nickname']}\"" if f['nickname'] else ""))
        print(f"    Age {f['age']} | {f['gender']} | {f['height_cm']}cm | {f['weight_class']} | {f['nation']}")
        print(f"    Style: {f['style_archetype']} | Pers: {f['personality_archetype']} | Stance: {f['stance']}")
        print(f"    Bio (first 100 chars): {f['bio'][:100]}...")
        print()

    # Write JSON output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(fighters, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(fighters)} fighters to {OUTPUT_FILE}")
    print(f"File size: {OUTPUT_FILE.stat().st_size:,} bytes")

    # Summary stats
    print("\n=== Summary stats ===")
    styles = {}
    personalities = {}
    nations = {}
    weight_classes = {}
    age_buckets = {"18-22": 0, "23-27": 0, "28-32": 0, "33-37": 0, "38+": 0}
    for f in fighters:
        styles[f["style_archetype"]] = styles.get(f["style_archetype"], 0) + 1
        personalities[f["personality_archetype"]] = personalities.get(f["personality_archetype"], 0) + 1
        nations[f["nation"]] = nations.get(f["nation"], 0) + 1
        weight_classes[f["weight_class"]] = weight_classes.get(f["weight_class"], 0) + 1
        age = f["age"]
        if age <= 22: age_buckets["18-22"] += 1
        elif age <= 27: age_buckets["23-27"] += 1
        elif age <= 32: age_buckets["28-32"] += 1
        elif age <= 37: age_buckets["33-37"] += 1
        else: age_buckets["38+"] += 1

    print(f"Styles: {dict(sorted(styles.items(), key=lambda x: -x[1]))}")
    print(f"Personalities: {dict(sorted(personalities.items(), key=lambda x: -x[1]))}")
    print(f"Nations (top 10): {dict(sorted(nations.items(), key=lambda x: -x[1])[:10])}")
    print(f"Weight classes: {dict(sorted(weight_classes.items(), key=lambda x: -x[1]))}")
    print(f"Age buckets: {age_buckets}")


if __name__ == "__main__":
    main()
