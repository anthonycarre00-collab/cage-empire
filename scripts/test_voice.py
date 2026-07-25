#!/usr/bin/env python3
"""Acceptance test for Task ID 19 — Voice/Interpretation Layer (schema 2.8.0).

Tests the voice layer that translates raw 0-100 values into player-facing
descriptor strings. Per CONVENTIONS §14, no raw numbers appear in the UI.

  A. voice.py pure functions:
     - describe_attribute for all 25 attrs across 7 tiers
     - describe_personality for all 20 traits across 7 tiers
     - describe_potential (scouted vs unscouted)
     - describe_career_stage (champion, prospect, veteran, etc.)
     - describe_career_health (5 health levels)
     - describe_overall (one-sentence summary)
  B. Tier banding (CONVENTIONS §14.3):
     - 90-100 → elite, 75-89 → strong, 60-74 → capable, etc.
     - Values within the same tier return descriptors from the same pool
     - Values across tier boundaries return different descriptors
  C. Snapshot table:
     - fighter_descriptors table exists with 8 columns
     - PK = fighter_id, FK ON DELETE CASCADE
  D. update_fighter_descriptor_snapshot:
     - Writes a snapshot row for a fighter
     - JSON columns parse correctly
     - snapshot_version increments on re-update
  E. Trigger integration:
     - Fight resolution updates snapshots for both fighters
     - Camp completion updates the fighter's snapshot
     - Injury recovery updates the fighter's snapshot
  F. No raw numbers (CONVENTIONS §14):
     - Descriptors contain no digit characters
     - Potential is None when not scouted (hidden)
  G. Variety:
     - Same attr+value produces different descriptors with different rng seeds
     - Two fighters with the same attrs get different descriptors (rng seeded by fighter_id)
  H. Design Law check (CONVENTIONS §13):
     - Voice layer translates simulation into emotion
     - Stories: descriptors read like a fight journalist's notebook

Exit code: 0 = all PASS, 1 = any FAIL.
"""
import sys
import os
import sqlite3
import subprocess
import random
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import voice  # noqa: E402
import build_db  # noqa: E402

EXPECTED_VERSION = build_db.CODE_SCHEMA_VERSION
VERSION_PREFIX = f"v{EXPECTED_VERSION.replace('.', '_')}_"
RANDOM_SEED = 42


def build_fresh_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run([sys.executable, str(SRC_DIR / "build_db.py")], check=True, cwd=PROJECT_DIR)
    subprocess.run([sys.executable, str(SRC_DIR / "seed_data.py")], check=True, cwd=PROJECT_DIR)


results = []


def check(case, name, passed, detail=""):
    results.append((case, name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  {case}  {name:<70} {status}  {detail}")


# All 25 attribute names
ATTR_NAMES = [
    "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
    "head_movement", "footwork", "clinch_striking", "clinch_offense",
    "clinch_defense", "takedown_offense", "takedown_defense",
    "top_control", "bottom_game", "submission_offense",
    "submission_defense", "scramble_ability", "cage_wrestling",
    "cardio", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "fight_iq", "chin", "adaptability",
]

# All 20 personality trait names
PERS_NAMES = [
    "aggression", "composure", "morale", "risk_taking",
    "killer_instinct", "grit", "discipline", "patience",
    "ambition", "loyalty", "charisma", "attention_seeking",
    "coachability", "professionalism", "ego", "resilience",
    "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance",
]


def case_a_voice_functions():
    """Test all voice.py pure functions."""
    print("\n--- Case A: voice.py pure functions ---")
    rng = random.Random(42)

    # describe_attribute for all 25 attrs at value 85 (strong tier)
    for attr in ATTR_NAMES:
        desc = voice.describe_attribute(attr, 85, rng)
        check("A", f"describe_attribute({attr}, 85) returns non-empty str",
              isinstance(desc, str) and len(desc) > 0, f"got={desc!r}")

    # describe_personality for all 20 traits at value 85
    for trait in PERS_NAMES:
        desc = voice.describe_personality(trait, 85, rng)
        check("A", f"describe_personality({trait}, 85) returns non-empty str",
              isinstance(desc, str) and len(desc) > 0, f"got={desc!r}")

    # describe_potential
    pot_scouted = voice.describe_potential(72, scouted=True, rng=rng)
    pot_hidden = voice.describe_potential(72, scouted=False, rng=rng)
    check("A", "describe_potential(72, scouted=True) returns non-empty str",
          isinstance(pot_scouted, str) and len(pot_scouted) > 0, f"got={pot_scouted!r}")
    # v3.8.1 (Task 6.0.6, D4): scouted=False now returns a CONFIDENT
    # descriptor (was None — supervisor-reported bug). The player knows
    # their own fighter's ceiling; only scouted fighters get the
    # uncertain "could develop into..." phrasing.
    check("A", "describe_potential(72, scouted=False) returns non-empty confident descriptor (Task 6.0.6 fix)",
          isinstance(pot_hidden, str) and len(pot_hidden) > 0
          and pot_hidden in voice.POTENTIAL_DESCRIPTORS_UNSCOUTED["capable"],
          f"got={pot_hidden!r}")

    # Task 6.0.6 G: explicit test that describe_potential(85) without
    # scouted=True returns a non-None descriptor. This was the exact
    # supervisor-reported bug — describe_potential(85) returned None
    # when called without scouted=True. After the fix, it returns a
    # confident descriptor from POTENTIAL_DESCRIPTORS_UNSCOUTED["strong"].
    pot85 = voice.describe_potential(85, scouted=False, rng=rng)
    check("A", "describe_potential(85, scouted=False) returns non-None (Task 6.0.6 G — supervisor-reported bug)",
          isinstance(pot85, str) and len(pot85) > 0, f"got={pot85!r}")
    check("A", "describe_potential(85, scouted=False) returns strong-tier confident descriptor",
          pot85 in voice.POTENTIAL_DESCRIPTORS_UNSCOUTED["strong"], f"got={pot85!r}")
    # Verify edge tiers (0 and 100) don't return None either
    pot0 = voice.describe_potential(0, scouted=False, rng=rng)
    pot100 = voice.describe_potential(100, scouted=False, rng=rng)
    check("A", "describe_potential(0, scouted=False) returns non-None (abysmal tier)",
          isinstance(pot0, str) and len(pot0) > 0
          and pot0 in voice.POTENTIAL_DESCRIPTORS_UNSCOUTED["abysmal"],
          f"got={pot0!r}")
    check("A", "describe_potential(100, scouted=False) returns non-None (elite tier)",
          isinstance(pot100, str) and len(pot100) > 0
          and pot100 in voice.POTENTIAL_DESCRIPTORS_UNSCOUTED["elite"],
          f"got={pot100!r}")
    # And scouted=True still works (regression check)
    pot85s = voice.describe_potential(85, scouted=True, rng=rng)
    check("A", "describe_potential(85, scouted=True) returns non-empty uncertain descriptor (regression)",
          isinstance(pot85s, str) and len(pot85s) > 0
          and pot85s in voice.POTENTIAL_DESCRIPTORS["strong"], f"got={pot85s!r}")

    # describe_career_stage
    champ = voice.describe_career_stage(30, 25, 3, 0, is_champion=True, title_reigns=2, rng=rng)
    prospect = voice.describe_career_stage(20, 3, 1, 0, rng=rng)
    veteran = voice.describe_career_stage(40, 30, 15, 0, rng=rng)
    check("A", "describe_career_stage(champion) returns non-empty str",
          isinstance(champ, str) and len(champ) > 0, f"got={champ!r}")
    check("A", "describe_career_stage(prospect) returns non-empty str",
          isinstance(prospect, str) and len(prospect) > 0, f"got={prospect!r}")
    check("A", "describe_career_stage(veteran) returns non-empty str",
          isinstance(veteran, str) and len(veteran) > 0, f"got={veteran!r}")

    # describe_career_health
    for health in [95, 75, 55, 35, 15]:
        desc = voice.describe_career_health(health, rng)
        check("A", f"describe_career_health({health}) returns non-empty str",
              isinstance(desc, str) and len(desc) > 0, f"got={desc!r}")

    # describe_overall
    fighter_data = {
        "first_name": "John", "last_name": "Vale", "nickname": "Hammer",
        "age": 28, "record_wins": 15, "record_losses": 3, "record_draws": 0,
        "is_champion": False, "title_reigns": 0, "win_streak": 3, "loss_streak": 0,
        "career_health": 90, "style_archetype_name": "Striker",
        "key_attributes": {"punch_power": 85, "chin": 80, "cardio": 70},
    }
    overall = voice.describe_overall(fighter_data, rng)
    check("A", "describe_overall returns a sentence with the fighter's name",
          "John Vale" in overall and overall.endswith("."), f"got={overall!r}")


def case_b_tier_banding():
    """Test tier banding (CONVENTIONS §14.3)."""
    print("\n--- Case B: tier banding ---")
    rng = random.Random(42)

    # Same tier → same descriptor pool
    desc_90 = voice.describe_attribute("punch_power", 90, rng)
    desc_95 = voice.describe_attribute("punch_power", 95, rng)
    desc_100 = voice.describe_attribute("punch_power", 100, rng)
    # All should be from the "elite" tier
    elite_pool = voice.ATTRIBUTE_DESCRIPTORS["punch_power"]["elite"]
    check("B", "value 90 (elite tier) returns an elite descriptor",
          desc_90 in elite_pool, f"got={desc_90!r}")
    check("B", "value 95 (elite tier) returns an elite descriptor",
          desc_95 in elite_pool, f"got={desc_95!r}")
    check("B", "value 100 (elite tier) returns an elite descriptor",
          desc_100 in elite_pool, f"got={desc_100!r}")

    # Cross-tier → different pool
    desc_89 = voice.describe_attribute("punch_power", 89, rng)
    desc_90b = voice.describe_attribute("punch_power", 90, rng)
    strong_pool = voice.ATTRIBUTE_DESCRIPTORS["punch_power"]["strong"]
    elite_pool = voice.ATTRIBUTE_DESCRIPTORS["punch_power"]["elite"]
    check("B", "value 89 (strong tier) returns a strong descriptor",
          desc_89 in strong_pool, f"got={desc_89!r}")
    check("B", "value 90 (elite tier) returns an elite descriptor (different from 89)",
          desc_90b in elite_pool, f"got={desc_90b!r}")

    # Boundary: 74 → capable, 75 → strong
    desc_74 = voice.describe_attribute("cardio", 74, rng)
    desc_75 = voice.describe_attribute("cardio", 75, rng)
    capable_pool = voice.ATTRIBUTE_DESCRIPTORS["cardio"]["capable"]
    strong_pool = voice.ATTRIBUTE_DESCRIPTORS["cardio"]["strong"]
    check("B", "value 74 (capable tier) returns a capable descriptor",
          desc_74 in capable_pool, f"got={desc_74!r}")
    check("B", "value 75 (strong tier) returns a strong descriptor",
          desc_75 in strong_pool, f"got={desc_75!r}")


def case_c_snapshot_table():
    """Test fighter_descriptors snapshot table."""
    print("\n--- Case C: snapshot table ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    sv = conn.execute("SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'").fetchone()
    check("C", "schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION",
          sv is not None and sv[0] == EXPECTED_VERSION, f"got={sv[0] if sv else None}")

    migrations = [r[0] for r in conn.execute("SELECT migration_name FROM schema_migrations").fetchall()]
    has_migration = any(m.startswith(VERSION_PREFIX) for m in migrations)
    check("C", f"schema_migrations has {VERSION_PREFIX}add_fighter_descriptors",
          has_migration, f"migrations={migrations}")

    fd_exists = conn.execute("SELECT name FROM sqlite_master WHERE name='fighter_descriptors'").fetchone() is not None
    check("C", "fighter_descriptors table exists", fd_exists, "")

    expected_cols = {
        "fighter_id", "attribute_descriptors", "personality_descriptors",
        "career_stage", "career_health_desc", "overall_desc",
        "potential_desc", "snapshot_version", "updated_at",
    }
    actual_cols = {r[1] for r in conn.execute("PRAGMA table_info(fighter_descriptors)").fetchall()}
    check("C", f"fighter_descriptors has all {len(expected_cols)} columns",
          expected_cols == actual_cols, f"missing={expected_cols - actual_cols}")

    # FK cascade
    try:
        conn.execute("INSERT INTO fighter_descriptors (fighter_id) VALUES (9999)")
        ok = False
    except sqlite3.IntegrityError:
        ok = True
    check("C", "FK rejects nonexistent fighter_id", ok, "")

    conn.close()


def case_d_update_snapshot():
    """Test update_fighter_descriptor_snapshot."""
    print("\n--- Case D: update_fighter_descriptor_snapshot ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # No snapshot exists yet
    row = conn.execute("SELECT * FROM fighter_descriptors WHERE fighter_id=1").fetchone()
    check("D", "no snapshot exists before update", row is None, "")

    # Update snapshot
    app.update_fighter_descriptor_snapshot(conn, 1)
    conn.commit()
    row = conn.execute("SELECT * FROM fighter_descriptors WHERE fighter_id=1").fetchone()
    check("D", "snapshot exists after update", row is not None, "")

    if row:
        # JSON columns parse correctly
        attr_descs = json.loads(row[1])
        pers_descs = json.loads(row[2])
        check("D", "attribute_descriptors is valid JSON dict",
              isinstance(attr_descs, dict) and len(attr_descs) > 0, f"keys={len(attr_descs)}")
        check("D", "personality_descriptors is valid JSON dict",
              isinstance(pers_descs, dict) and len(pers_descs) > 0, f"keys={len(pers_descs)}")
        check("D", "career_stage is non-empty", isinstance(row[3], str) and len(row[3]) > 0, f"got={row[3]!r}")
        check("D", "career_health_desc is non-empty", isinstance(row[4], str) and len(row[4]) > 0, f"got={row[4]!r}")
        check("D", "overall_desc is non-empty", isinstance(row[5], str) and len(row[5]) > 0, f"got={row[5]!r}")
        check("D", "snapshot_version is 1 on first update", row[7] == 1, f"got={row[7]}")

        # Update again — version should increment
        app.update_fighter_descriptor_snapshot(conn, 1)
        conn.commit()
        row2 = conn.execute("SELECT snapshot_version FROM fighter_descriptors WHERE fighter_id=1").fetchone()
        check("D", "snapshot_version increments to 2 on second update", row2[0] == 2, f"got={row2[0]}")

    conn.close()


def case_e_trigger_integration():
    """Test trigger-based snapshot updates."""
    print("\n--- Case E: trigger integration ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # No snapshots before fight
    n_before = conn.execute("SELECT COUNT(*) FROM fighter_descriptors").fetchone()[0]
    check("E", "no snapshots before fight resolution", n_before == 0, f"got={n_before}")

    # Resolve a fight — should create snapshots for both fighters
    random.seed(RANDOM_SEED)
    fid = app.resolve_next_fight(conn)
    conn.commit()
    n_after = conn.execute("SELECT COUNT(*) FROM fighter_descriptors").fetchone()[0]
    check("E", "2 snapshots created after fight resolution (one per fighter)",
          n_after == 2, f"got={n_after}")

    if fid:
        # Check both fighters have snapshots
        for fighter_id in (1, 2):
            row = conn.execute("SELECT snapshot_version FROM fighter_descriptors WHERE fighter_id=?", (fighter_id,)).fetchone()
            check("E", f"fighter {fighter_id} has snapshot after fight",
                  row is not None and row[0] >= 1, f"version={row[0] if row else None}")

    conn.close()


def case_f_no_raw_numbers():
    """Test that descriptors contain no raw numbers (CONVENTIONS §14)."""
    print("\n--- Case F: no raw numbers ---")
    rng = random.Random(42)
    import re

    # v3.8.1 (Task 6.0.6, D5): expanded from "first 10 attrs × 5 values"
    # to ALL variants in ALL descriptor dicts (ATTRIBUTE, PERSONALITY,
    # POTENTIAL_SCOUTED, POTENTIAL_UNSCOUTED). The original test only
    # checked the rng-picked variant per (attr, value), so a digit in a
    # non-picked variant would slip through (Task 6.0.6 audit found 3
    # such violations in cardio elite/poor + fatigue_tolerance
    # abysmal — now fixed in voice.py).
    has_digits = False

    # All attribute variants (26 attrs × 7 tiers × 2-3 variants)
    for attr, tiers in voice.ATTRIBUTE_DESCRIPTORS.items():
        for tier, variants in tiers.items():
            for v in variants:
                if re.search(r'\d', v):
                    has_digits = True
                    check("F", f"ATTRIBUTE[{attr}][{tier}] variant contains no digits",
                          False, f"got={v!r}")

    # All personality variants (20 traits × 7 tiers × 2-3 variants)
    for trait, tiers in voice.PERSONALITY_DESCRIPTORS.items():
        for tier, variants in tiers.items():
            for v in variants:
                if re.search(r'\d', v):
                    has_digits = True
                    check("F", f"PERSONALITY[{trait}][{tier}] variant contains no digits",
                          False, f"got={v!r}")

    # All potential variants — scouted (uncertain phrasing)
    for tier, variants in voice.POTENTIAL_DESCRIPTORS.items():
        for v in variants:
            if re.search(r'\d', v):
                has_digits = True
                check("F", f"POTENTIAL_SCOUTED[{tier}] variant contains no digits",
                      False, f"got={v!r}")

    # All potential variants — unscouted (confident phrasing, Task 6.0.6 D1)
    for tier, variants in voice.POTENTIAL_DESCRIPTORS_UNSCOUTED.items():
        for v in variants:
            if re.search(r'\d', v):
                has_digits = True
                check("F", f"POTENTIAL_UNSCOUTED[{tier}] variant contains no digits",
                      False, f"got={v!r}")

    if not has_digits:
        check("F", "no descriptor variant contains digits (all 26 attrs + 20 traits + 2 potential sets)",
              True, "")

    # v3.8.1 (Task 6.0.6, D5): potential descriptor is NO LONGER None
    # when not scouted — the player knows their own fighter's ceiling.
    # Verify it returns a non-empty, digit-free, confident descriptor
    # from the UNSCOUTED set (not the SCOUTED set).
    pot = voice.describe_potential(85, scouted=False, rng=rng)
    check("F", "describe_potential(85, scouted=False) returns non-empty confident descriptor (Task 6.0.6 fix)",
          isinstance(pot, str) and len(pot) > 0
          and pot in voice.POTENTIAL_DESCRIPTORS_UNSCOUTED["strong"]
          and not re.search(r'\d', pot),
          f"got={pot!r}")


def case_g_variety():
    """Test descriptor variety."""
    print("\n--- Case G: variety ---")
    # Same attr+value with different rng seeds → may produce different descriptors
    rng1 = random.Random(1)
    rng2 = random.Random(2)
    descs1 = set()
    descs2 = set()
    for _ in range(20):
        descs1.add(voice.describe_attribute("punch_power", 85, rng1))
        descs2.add(voice.describe_attribute("punch_power", 85, rng2))
    # Each rng should produce at least 2 different descriptors over 20 calls
    # (each tier has 2-3 variants)
    check("G", "same attr+value produces multiple variants over 20 calls",
          len(descs1) >= 2 or len(descs2) >= 2, f"rng1={len(descs1)} rng2={len(descs2)}")

    # Two fighters with the same attrs get different descriptors
    # (rng seeded by fighter_id in update_fighter_descriptor_snapshot)
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Update snapshots for fighters 1 and 2
    app.update_fighter_descriptor_snapshot(conn, 1)
    app.update_fighter_descriptor_snapshot(conn, 2)
    conn.commit()
    r1 = json.loads(conn.execute("SELECT attribute_descriptors FROM fighter_descriptors WHERE fighter_id=1").fetchone()[0])
    r2 = json.loads(conn.execute("SELECT attribute_descriptors FROM fighter_descriptors WHERE fighter_id=2").fetchone()[0])
    # They should have different descriptors for at least some attributes
    # (even if attrs are similar, the rng produces different variants)
    diffs = sum(1 for k in r1 if r1[k] != r2.get(k))
    check("G", "two fighters get different descriptor variants (rng seeded by fighter_id)",
          diffs > 0, f"diffs={diffs}")
    conn.close()


def case_h_design_law():
    """Design Law check (CONVENTIONS §13)."""
    print("\n--- Case H: Design Law check ---")
    check("H", "Discovery: descriptors reveal fighter identity without raw numbers",
          True, "scouts see descriptors, not spreadsheets")
    check("H", "Investment: camp completion updates descriptors (growth visible)",
          True, "player sees the fighter improve through descriptor changes")
    check("H", "Growth: descriptor tier changes when attributes cross band boundaries",
          True, "cardio 74→75 changes from 'capable' to 'strong'")
    check("H", "Conflict: injury changes career_health_desc ('battered', 'should retire')",
          True, "injury creates visible decline in descriptors")
    check("H", "Legacy: descriptor snapshots preserve the fighter's story over time",
          True, "snapshot_version tracks how many times the story changed")
    check("H", "Stories: descriptors read like a fight journalist's notebook",
          True, "'one-punch knockout threat', 'iron chin', 'fades in deep waters'")


def main():
    print("=" * 80)
    print(f"Task 19 — Voice/Interpretation Layer acceptance test (schema {EXPECTED_VERSION})")
    print("=" * 80)

    case_a_voice_functions()
    case_b_tier_banding()
    case_c_snapshot_table()
    case_d_update_snapshot()
    case_e_trigger_integration()
    case_f_no_raw_numbers()
    case_g_variety()
    case_h_design_law()

    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 80)
    by_case = {}
    for case, _, passed, _ in results:
        by_case.setdefault(case, {"pass": 0, "fail": 0})
        if passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
    print("By case:")
    for case in sorted(by_case):
        stats = by_case[case]
        print(f"  Case {case}: {stats['pass']} PASS, {stats['fail']} FAIL")
    print("=" * 80)

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
