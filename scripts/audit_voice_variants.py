#!/usr/bin/env python3
"""Supplementary audit: scan ALL descriptor variants for digit characters.

The primary audit (audit_voice.py) only checks the seed-picked variant
per attr×value. A tier can have up to 3 variants — if only one contains
a digit, the primary audit might miss it (depending on rng.choice).

This script enumerates every variant string in:
  - ATTRIBUTE_DESCRIPTORS (26 attrs × 7 tiers × 2-3 variants)
  - PERSONALITY_DESCRIPTORS (20 traits × 7 tiers × 2-3 variants)
  - POTENTIAL_DESCRIPTORS (7 tiers × 2-3 variants)
  - All hardcoded phrases inside describe_career_stage, describe_career_health
  - _ARCHETYPE_NOUN, _NUM_WORDS

and flags any string containing a digit character (CONVENTIONS §14 violation).
"""
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

import voice  # noqa: E402

DIGIT_RE = re.compile(r"\d")
violations = []


def check(label, s):
    if not isinstance(s, str):
        return
    if DIGIT_RE.search(s):
        violations.append((label, s))


# 1. ATTRIBUTE_DESCRIPTORS
for attr, tiers in voice.ATTRIBUTE_DESCRIPTORS.items():
    for tier, variants in tiers.items():
        for v in variants:
            check(f"ATTRIBUTE[{attr!r}][{tier}]", v)

# 2. PERSONALITY_DESCRIPTORS
for trait, tiers in voice.PERSONALITY_DESCRIPTORS.items():
    for tier, variants in tiers.items():
        for v in variants:
            check(f"PERSONALITY[{trait!r}][{tier}]", v)

# 3. POTENTIAL_DESCRIPTORS
for tier, variants in voice.POTENTIAL_DESCRIPTORS.items():
    for v in variants:
        check(f"POTENTIAL[{tier}]", v)

# 4. _ARCHETYPE_NOUN
for sa, noun in voice._ARCHETYPE_NOUN.items():
    check(f"_ARCHETYPE_NOUN[{sa!r}]", noun)

# 5. _NUM_WORDS values
for n, word in voice._NUM_WORDS.items():
    check(f"_NUM_WORDS[{n}]", word)

# 6. Hardcoded phrase lists in describe_career_stage / describe_career_health
# (Scrape by importing source and walking _pick([...]) literals is complex;
#  instead we just call the functions with many inputs.)
import random
rng = random.Random(0)
# describe_career_stage — many state combinations
for age in [18, 20, 22, 25, 28, 30, 33, 36, 40, 45]:
    for w in [0, 3, 5, 10, 15, 20, 25, 30, 40]:
        for l in [0, 1, 3, 5, 10, 15, 20]:
            for d in [0]:
                for champ in [False, True]:
                    for reigns in [0, 1, 2, 3, 5]:
                        for ws in [0, 1, 2, 3, 5, 7]:
                            for ls in [0, 1, 3, 5]:
                                s = voice.describe_career_stage(age, w, l, d, champ, reigns, ws, ls, rng)
                                check(f"describe_career_stage(age={age},w={w},l={l},champ={champ},reigns={reigns},ws={ws},ls={ls})", s)

# describe_career_health — every integer 0..100
for h in range(0, 101):
    s = voice.describe_career_health(h, rng)
    check(f"describe_career_health({h})", s)

# describe_overall — varied profiles
profiles = []
for sa in voice._ARCHETYPE_NOUN.keys():
    for ws in [0, 2, 3, 5, 10]:
        for ls in [0, 3, 5]:
            profiles.append({
                "first_name": "Test", "last_name": "Case", "nickname": "Nick",
                "age": 28, "record_wins": 15, "record_losses": 5, "record_draws": 0,
                "is_champion": False, "title_reigns": 0, "win_streak": ws, "loss_streak": ls,
                "career_health": 75, "style_archetype_name": sa,
                "key_attributes": {"punch_power": 85, "chin": 80, "cardio": 70},
            })
for i, p in enumerate(profiles):
    s = voice.describe_overall(p, rng)
    check(f"describe_overall(profile#{i}, sa={p['style_archetype_name']}, ws={p['win_streak']}, ls={p['loss_streak']})", s)

print("=" * 80)
print("Variant-level digit audit (Task 6.0.6 supplementary)")
print("=" * 80)
print(f"Scanned:")
print(f"  ATTRIBUTE_DESCRIPTORS: {sum(len(v) for t in voice.ATTRIBUTE_DESCRIPTORS.values() for v in t.values())} variant strings")
print(f"  PERSONALITY_DESCRIPTORS: {sum(len(v) for t in voice.PERSONALITY_DESCRIPTORS.values() for v in t.values())} variant strings")
print(f"  POTENTIAL_DESCRIPTORS: {sum(len(v) for v in voice.POTENTIAL_DESCRIPTORS.values())} variant strings")
print(f"  describe_career_stage calls: ~10,000+")
print(f"  describe_career_health calls: 101 (every value 0-100)")
print(f"  describe_overall calls: {len(profiles)}")
print()
if violations:
    print(f"FOUND {len(violations)} digit violations (CONVENTIONS §14):")
    # Deduplicate by string content
    seen = set()
    for label, s in violations:
        if s not in seen:
            seen.add(s)
            print(f"  - {label!r}: {s!r}")
    sys.exit(1)
else:
    print("OK: 0 digit violations found in any descriptor variant.")
    sys.exit(0)
