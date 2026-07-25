#!/usr/bin/env python3
"""Voice layer audit script (Task 6.0.6).

Audits every public describe_* function in src/voice.py against a range
of inputs (0, 10, 25, 40, 50, 60, 75, 85, 90, 100) and verifies:
  1. No None returned for valid inputs
  2. No empty string returned
  3. No raw digit characters in the output (CONVENTIONS §14)
  4. All 26 attributes × 7 tiers are covered
  5. All 20 personality traits × 7 tiers are covered

This is a one-shot audit script (NOT an acceptance test) — it prints
gaps and exits 0 if everything passes, 1 if any gap is found.
"""
import re
import random
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

import voice  # noqa: E402


# Per Task brief: 26 attribute names (matches test_voice.py + voice.py)
ATTR_NAMES = [
    "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
    "head_movement", "footwork", "clinch_striking", "clinch_offense",
    "clinch_defense", "takedown_offense", "takedown_defense",
    "top_control", "bottom_game", "submission_offense",
    "submission_defense", "scramble_ability", "cage_wrestling",
    "cardio", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "fight_iq", "chin", "adaptability",
]

PERS_NAMES = [
    "aggression", "composure", "morale", "risk_taking",
    "killer_instinct", "grit", "discipline", "patience",
    "ambition", "loyalty", "charisma", "attention_seeking",
    "coachability", "professionalism", "ego", "resilience",
    "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance",
]

# Per Task brief: test inputs at every tier boundary + middles
TEST_VALUES = [0, 10, 25, 40, 50, 60, 75, 85, 90, 100]

DIGIT_RE = re.compile(r"\d")


def is_bad(desc, allow_none=False):
    """Return (is_bad, reason). 'bad' = None when not allowed, empty, or
    contains a digit character (CONVENTIONS §14 violation)."""
    if desc is None:
        return (False, "ok") if allow_none else (True, "None")
    if not isinstance(desc, str):
        return True, f"non-str type={type(desc).__name__}"
    if len(desc) == 0:
        return True, "empty string"
    if DIGIT_RE.search(desc):
        return True, f"contains digit: {desc!r}"
    return False, "ok"


def audit_attribute_coverage():
    """Audit describe_attribute for all 26 attrs × 7 tiers."""
    print("\n=== Audit B: describe_attribute coverage (26 attrs × 10 values) ===")
    rng = random.Random(42)
    gaps = []
    for attr in ATTR_NAMES:
        for v in TEST_VALUES:
            desc = voice.describe_attribute(attr, v, rng)
            bad, reason = is_bad(desc)
            if bad:
                gaps.append((attr, v, reason, desc))
                print(f"  GAP  attr={attr!r} value={v}: {reason}")
    # Also confirm the dict has 7 tiers per attr
    for attr in ATTR_NAMES:
        tiers = voice.ATTRIBUTE_DESCRIPTORS.get(attr, {})
        missing_tiers = {"elite", "strong", "capable", "average", "limited", "poor", "abysmal"} - set(tiers.keys())
        if missing_tiers:
            gaps.append((attr, "MISSING_TIERS", str(missing_tiers), None))
            print(f"  GAP  attr={attr!r} missing tiers: {missing_tiers}")
    print(f"  → {len(ATTR_NAMES) * len(TEST_VALUES)} attr×value checks, {len(gaps)} gaps")
    return gaps


def audit_personality_coverage():
    """Audit describe_personality for all 20 traits × 7 tiers."""
    print("\n=== Audit C: describe_personality coverage (20 traits × 10 values) ===")
    rng = random.Random(42)
    gaps = []
    for trait in PERS_NAMES:
        for v in TEST_VALUES:
            desc = voice.describe_personality(trait, v, rng)
            bad, reason = is_bad(desc)
            if bad:
                gaps.append((trait, v, reason, desc))
                print(f"  GAP  trait={trait!r} value={v}: {reason}")
    for trait in PERS_NAMES:
        tiers = voice.PERSONALITY_DESCRIPTORS.get(trait, {})
        missing_tiers = {"elite", "strong", "capable", "average", "limited", "poor", "abysmal"} - set(tiers.keys())
        if missing_tiers:
            gaps.append((trait, "MISSING_TIERS", str(missing_tiers), None))
            print(f"  GAP  trait={trait!r} missing tiers: {missing_tiers}")
    print(f"  → {len(PERS_NAMES) * len(TEST_VALUES)} trait×value checks, {len(gaps)} gaps")
    return gaps


def audit_describe_potential():
    """Audit describe_potential for both scouted=True and scouted=False."""
    print("\n=== Audit E: describe_potential (10 values × scouted True/False) ===")
    rng = random.Random(42)
    gaps = []
    # scouted=True should never return None
    for v in TEST_VALUES:
        desc = voice.describe_potential(v, scouted=True, rng=rng)
        bad, reason = is_bad(desc)
        if bad:
            gaps.append(("scouted=True", v, reason, desc))
            print(f"  GAP  scouted=True value={v}: {reason}  got={desc!r}")
    # scouted=False should ALSO never return None (the bug we are auditing/fixing)
    for v in TEST_VALUES:
        desc = voice.describe_potential(v, scouted=False, rng=rng)
        bad, reason = is_bad(desc)
        if bad:
            gaps.append(("scouted=False", v, reason, desc))
            print(f"  GAP  scouted=False value={v}: {reason}  got={desc!r}")
    print(f"  → {2 * len(TEST_VALUES)} checks, {len(gaps)} gaps")
    return gaps


def audit_describe_career_stage():
    """Audit describe_career_stage across varied fighter states."""
    print("\n=== Audit: describe_career_stage (10 states) ===")
    rng = random.Random(42)
    # 10 diverse fighter states
    states = [
        # (age, w, l, d, is_champ, reigns, ws, ls)
        (20, 3, 0, 0, False, 0, 3, 0),    # young prospect
        (22, 5, 1, 0, False, 0, 2, 0),    # rising prospect
        (25, 10, 2, 0, False, 0, 4, 0),   # contender
        (28, 15, 3, 0, True, 1, 3, 0),    # reigning champ
        (30, 20, 5, 0, True, 3, 5, 0),    # dominant multi-time champ
        (32, 22, 10, 0, False, 0, 1, 2),  # sliding contender
        (35, 25, 15, 0, False, 0, 3, 0),  # late bloomer
        (38, 30, 18, 0, False, 0, 0, 4),  # fallen veteran
        (40, 35, 20, 0, False, 0, 1, 1),  # grizzled vet
        (26, 12, 8, 0, False, 0, 1, 1),   # journeyman
    ]
    gaps = []
    for i, s in enumerate(states):
        desc = voice.describe_career_stage(*s, rng=rng)
        bad, reason = is_bad(desc)
        if bad:
            gaps.append((i, s, reason, desc))
            print(f"  GAP  state#{i} {s}: {reason}  got={desc!r}")
        else:
            print(f"  OK   state#{i} {s} → {desc!r}")
    print(f"  → {len(states)} checks, {len(gaps)} gaps")
    return gaps


def audit_describe_career_health():
    """Audit describe_career_health for 10 health values."""
    print("\n=== Audit: describe_career_health (10 values) ===")
    rng = random.Random(42)
    gaps = []
    for v in TEST_VALUES:
        desc = voice.describe_career_health(v, rng)
        bad, reason = is_bad(desc)
        if bad:
            gaps.append((v, reason, desc))
            print(f"  GAP  health={v}: {reason}  got={desc!r}")
        else:
            print(f"  OK   health={v} → {desc!r}")
    print(f"  → {len(TEST_VALUES)} checks, {len(gaps)} gaps")
    return gaps


def audit_describe_overall():
    """Audit describe_overall for varied fighter_data."""
    print("\n=== Audit: describe_overall (5 fighter profiles) ===")
    rng = random.Random(42)
    profiles = [
        {  # champion
            "first_name": "John", "last_name": "Vale", "nickname": "Hammer",
            "age": 30, "record_wins": 20, "record_losses": 3, "record_draws": 0,
            "is_champion": True, "title_reigns": 1, "win_streak": 5, "loss_streak": 0,
            "career_health": 90, "style_archetype_name": "Striker",
            "key_attributes": {"punch_power": 95, "chin": 85, "cardio": 80},
        },
        {  # prospect
            "first_name": "Marcus", "last_name": "Reed", "nickname": "",
            "age": 22, "record_wins": 5, "record_losses": 0, "record_draws": 0,
            "is_champion": False, "title_reigns": 0, "win_streak": 5, "loss_streak": 0,
            "career_health": 100, "style_archetype_name": "Wrestler",
            "key_attributes": {"takedown_offense": 88, "top_control": 82, "cardio": 75},
        },
        {  # veteran
            "first_name": "Old", "last_name": "Veteran", "nickname": "Iron",
            "age": 38, "record_wins": 32, "record_losses": 18, "record_draws": 0,
            "is_champion": False, "title_reigns": 0, "win_streak": 0, "loss_streak": 3,
            "career_health": 45, "style_archetype_name": "Brawler",
            "key_attributes": {"punch_power": 70, "chin": 65, "durability": 50},
        },
        {  # mid-card
            "first_name": "Mid", "last_name": "Card", "nickname": "",
            "age": 28, "record_wins": 14, "record_losses": 10, "record_draws": 0,
            "is_champion": False, "title_reigns": 0, "win_streak": 1, "loss_streak": 0,
            "career_health": 75, "style_archetype_name": "Balanced",
            "key_attributes": {"fight_iq": 70, "cardio": 65, "adaptability": 60},
        },
        {  # sliding
            "first_name": "Sliding", "last_name": "Star", "nickname": "",
            "age": 33, "record_wins": 22, "record_losses": 8, "record_draws": 0,
            "is_champion": False, "title_reigns": 0, "win_streak": 0, "loss_streak": 4,
            "career_health": 60, "style_archetype_name": "Counter-Striker",
            "key_attributes": {"head_movement": 78, "punch_accuracy": 72, "footwork": 70},
        },
    ]
    gaps = []
    for i, fd in enumerate(profiles):
        desc = voice.describe_overall(fd, rng)
        bad, reason = is_bad(desc)
        if bad:
            gaps.append((i, reason, desc))
            print(f"  GAP  profile#{i}: {reason}  got={desc!r}")
        else:
            print(f"  OK   profile#{i} → {desc!r}")
    print(f"  → {len(profiles)} checks, {len(gaps)} gaps")
    return gaps


def audit_build_descriptor_snapshot():
    """Audit build_descriptor_snapshot returns a complete dict."""
    print("\n=== Audit: build_descriptor_snapshot (1 sample fighter) ===")
    rng = random.Random(42)
    attrs = {name: 50 + (i * 3) % 50 for i, name in enumerate(ATTR_NAMES)}
    pers = {name: 40 + (i * 5) % 60 for i, name in enumerate(PERS_NAMES)}
    fighter_data = {
        "first_name": "Snap", "last_name": "Shot", "nickname": "",
        "age": 28, "record_wins": 15, "record_losses": 5, "record_draws": 0,
        "is_champion": False, "title_reigns": 0, "win_streak": 2, "loss_streak": 0,
        "career_health": 80, "style_archetype_name": "Striker",
    }
    snap = voice.build_descriptor_snapshot(attrs, pers, fighter_data, rng)
    gaps = []
    if not isinstance(snap, dict):
        gaps.append(("not a dict", type(snap).__name__))
        print(f"  GAP  snapshot is not a dict: {type(snap).__name__}")
    else:
        required_keys = {"attribute_descriptors", "personality_descriptors",
                         "career_stage", "career_health", "potential_descriptor", "overall"}
        missing = required_keys - set(snap.keys())
        if missing:
            gaps.append(("missing keys", str(missing)))
            print(f"  GAP  snapshot missing keys: {missing}")
        # Check each attribute descriptor
        for attr, desc in snap.get("attribute_descriptors", {}).items():
            bad, reason = is_bad(desc)
            if bad:
                gaps.append((f"attr {attr}", reason))
                print(f"  GAP  attr={attr!r}: {reason}  got={desc!r}")
        # Check each personality descriptor
        for trait, desc in snap.get("personality_descriptors", {}).items():
            bad, reason = is_bad(desc)
            if bad:
                gaps.append((f"trait {trait}", reason))
                print(f"  GAP  trait={trait!r}: {reason}  got={desc!r}")
        # Check career_stage, career_health, overall
        for k in ("career_stage", "career_health", "overall"):
            bad, reason = is_bad(snap.get(k))
            if bad:
                gaps.append((k, reason))
                print(f"  GAP  {k}: {reason}  got={snap.get(k)!r}")
        # potential_descriptor: allow None per current implementation
        pd = snap.get("potential_descriptor")
        if pd is not None:
            bad, reason = is_bad(pd)
            if bad:
                gaps.append(("potential_descriptor", reason))
                print(f"  GAP  potential_descriptor: {reason}  got={pd!r}")
    print(f"  → 1 snapshot, {len(gaps)} gaps")
    return gaps


def main():
    print("=" * 80)
    print("Voice layer audit (Task 6.0.6)")
    print("=" * 80)

    all_gaps = []
    all_gaps += audit_attribute_coverage()
    all_gaps += audit_personality_coverage()
    all_gaps += audit_describe_potential()
    all_gaps += audit_describe_career_stage()
    all_gaps += audit_describe_career_health()
    all_gaps += audit_describe_overall()
    all_gaps += audit_build_descriptor_snapshot()

    print("\n" + "=" * 80)
    if all_gaps:
        print(f"AUDIT FAILED: {len(all_gaps)} gaps found")
        for g in all_gaps:
            print(f"  - {g}")
        sys.exit(1)
    else:
        print("AUDIT PASSED: 0 gaps found")
        sys.exit(0)


if __name__ == "__main__":
    main()
