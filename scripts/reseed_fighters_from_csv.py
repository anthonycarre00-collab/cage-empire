#!/usr/bin/env python3
"""RESEED Step 2 — Load Claude's CSV (4000 fighters) + overwrite the
skill/personality/record/bio/style/promotion/gym columns for fighter_id
1..4000.

CRITICAL RULES:
  * DO NOT overwrite physicals: weight_class_id, height_cm,
    birth_nation_id, residence_nation_id, gender, date_of_birth,
    first_name, last_name. These are preserved from the existing DB.
  * DO NOT store seed-time tools: career_tier, mental_archetype,
    mental_score, overall_current. They are used by other scripts
    (nickname generation, fight_history backfill) but never written
    to the DB.
  * Zero new columns. Zero migrations.

Roster caps applied per promotion tier:
  * major  (P1)        : cap 70   → rest → free agent
  * mid    (P2/P3/P4)  : cap 50   → rest → free agent
  * small  (P5..P9)    : cap 30   → rest → free agent
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
# Style + personality tag → archetype_id maps
# ---------------------------------------------------------------------------
STYLE_NAME_TO_ID = {
    "Balanced": 1,
    "Striker": 2,
    "Grappler": 3,
    "Wrestler": 4,
    "Brawler": 5,
    "Counter-Striker": 6,
    "Submission Specialist": 7,
}

PERSONALITY_TAG_TO_ID = {
    "Calm": 1,
    "Aggressive": 2,
    "Methodical": 3,
    "Showman": 4,
    "Quiet Professional": 5,
}

# CSV promotion label → (db promotion_id, size_tier, cap)
PROMO_MAP = {
    "P1": (1, "major", 70),
    "P2": (2, "mid", 50),
    "P3": (3, "mid", 50),
    "P4": (4, "mid", 50),
    "P5": (5, "small", 30),
    "P6": (6, "small", 30),
    "P7": (7, "small", 30),
    "P8": (8, "small", 30),
    "P9": (9, "small", 30),
    "P10": (10, "small", 30),
}

# 26 skill columns (CSV column name == fighter_attributes column name)
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

# 20 personality columns — strip "personality_" prefix from CSV header
PERSONALITY_COLS = [
    "aggression", "composure", "risk_taking", "killer_instinct",
    "patience", "ego", "focus", "morale",
    "grit", "discipline", "ambition", "loyalty",
    "charisma", "attention_seeking", "coachability", "professionalism",
    "resilience", "sportsmanship", "travel_comfort", "fatigue_tolerance",
]


def _clamp(v, lo=0, hi=100):
    try:
        v = int(v)
    except (ValueError, TypeError):
        return lo
    return max(lo, min(hi, v))


def _career_health(tier, age):
    """100 for young/prime, 80 for decline (age>=34), 60 for DecliningVet."""
    if tier == "DecliningVet":
        return 60
    if age >= 34:
        return 80
    return 100


def _compute_streaks(wins, losses, draws, rng):
    """Random but plausible win_streak/loss_streak given record."""
    if wins + losses + draws == 0:
        return 0, 0
    # Bias toward short streaks; cap by total wins/losses available.
    max_w = min(wins, 8)
    max_l = min(losses, 5)
    ws = rng.randint(0, max_w) if max_w > 0 else 0
    ls = rng.randint(0, max_l) if max_l > 0 else 0
    return ws, ls


def _load_gym_lookup(conn):
    """Return dict {name_lower: gym_id} for existing gyms."""
    out = {}
    for gym_id, name in conn.execute("SELECT gym_id, name FROM gyms").fetchall():
        out[name.strip().lower()] = gym_id
    return out


def _create_gym(conn, name, city_id):
    """Insert a new gym row. Uses city_id provided (must be a valid city)."""
    # Default facility values from schema defaults — only set name+city_id+nation_id
    cur = conn.execute(
        "INSERT INTO gyms (name, city_id) VALUES (?, ?)",
        (name, city_id),
    )
    return cur.lastrowid


def _pick_default_city(conn):
    """Return some city_id to use as a default for new gyms (any non-null)."""
    row = conn.execute(
        "SELECT city_id FROM cities ORDER BY city_id LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def reseed():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    # Performance: one big transaction.
    conn.isolation_level = None
    conn.execute("BEGIN")

    # Read existing fighters (1..4000) — preserve physicals.
    # We only need fighter_id for existence check; the UPDATE statements
    # below will match by fighter_id.
    existing_ids = {
        r[0] for r in conn.execute(
            "SELECT fighter_id FROM fighters WHERE fighter_id BETWEEN 1 AND 4000"
        ).fetchall()
    }
    print(f"Found {len(existing_ids)} existing fighters (id 1..4000)")

    gym_lookup = _load_gym_lookup(conn)
    default_city = _pick_default_city(conn)
    new_gym_count = 0

    # Per-promo running counter for cap enforcement.
    promo_counts = {pid: 0 for pid in range(1, 11)}

    rng = random.Random(20260815)  # deterministic reseed

    rows_processed = 0
    free_agent_count = 0
    signed_count = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                fid = int(row["fighter_id"])
            except (ValueError, KeyError):
                continue
            if fid not in existing_ids:
                # Fighter not in current DB (shouldn't happen for 1..4000).
                continue

            # --- Promotion assignment with cap enforcement -----------
            promo_label = (row.get("promotion_id") or "").strip()
            assigned_promo = None
            if promo_label in PROMO_MAP:
                pid, _tier, cap = PROMO_MAP[promo_label]
                if promo_counts[pid] < cap:
                    assigned_promo = pid
                    promo_counts[pid] += 1
                    signed_count += 1
                else:
                    # Overflow → free agent
                    free_agent_count += 1
            else:
                free_agent_count += 1

            # --- Style + personality archetype -----------------------
            style_id = STYLE_NAME_TO_ID.get(row.get("style", "").strip())
            pers_id = PERSONALITY_TAG_TO_ID.get(
                row.get("personality_tag", "").strip()
            )

            # --- Stance / handedness (with schema CHECK) -------------
            stance = (row.get("stance") or "").strip().lower()
            if stance not in ("orthodox", "southpaw", "switch"):
                stance = "orthodox"
            handedness = (row.get("handedness") or "").strip().lower()
            if handedness not in ("right", "left", "ambidextrous"):
                handedness = "right"

            # --- Gym lookup / create ---------------------------------
            camp = (row.get("camp") or "").strip()
            gym_id = None
            if camp and camp.lower() != "independent camp":
                gym_id = gym_lookup.get(camp.lower())
                if gym_id is None and default_city is not None:
                    # Create new gym (rare — most camp names map to existing).
                    gym_id = _create_gym(conn, camp, default_city)
                    gym_lookup[camp.lower()] = gym_id
                    new_gym_count += 1
            elif camp and camp.lower() == "independent camp":
                # Independent — no gym assignment.
                gym_id = None

            # --- Update fighters row (preserve physicals) ------------
            conn.execute(
                """UPDATE fighters SET
                       current_promotion_id = ?,
                       current_gym_id = ?,
                       fight_style_archetype_id = ?,
                       personality_archetype_id = ?,
                       stance = ?,
                       handedness = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE fighter_id = ?""",
                (assigned_promo, gym_id, style_id, pers_id,
                 stance, handedness, fid),
            )

            # --- fighter_attributes (26 columns) ---------------------
            set_clause = ", ".join(f"{c} = ?" for c in SKILL_COLS)
            params = [_clamp(row[c]) for c in SKILL_COLS]
            params.append(fid)
            conn.execute(
                f"UPDATE fighter_attributes SET {set_clause}, "
                "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
                params,
            )

            # --- fighter_personality (20 columns) --------------------
            set_clause = ", ".join(
                f"{c} = ?" for c in PERSONALITY_COLS
            )
            params = [
                _clamp(row["personality_" + c]) for c in PERSONALITY_COLS
            ]
            params.append(fid)
            conn.execute(
                f"UPDATE fighter_personality SET {set_clause}, "
                "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
                params,
            )

            # --- fighter_career (record + potential + streaks + health)
            wins = int(row.get("suggested_wins") or 0)
            losses = int(row.get("suggested_losses") or 0)
            draws = int(row.get("suggested_draws") or 0)
            potential = _clamp(row.get("potential") or 50, 0, 100)
            try:
                age = int(row.get("age") or 25)
            except ValueError:
                age = 25
            tier = (row.get("career_tier") or "").strip()
            health = _career_health(tier, age)
            ws, ls = _compute_streaks(wins, losses, draws, rng)

            conn.execute(
                """UPDATE fighter_career SET
                       record_wins = ?, record_losses = ?, record_draws = ?,
                       win_streak = ?, loss_streak = ?,
                       career_health = ?, potential = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE fighter_id = ?""",
                (wins, losses, draws, ws, ls, health, potential, fid),
            )

            # --- fighter_bios (bio_text) -----------------------------
            bio = (row.get("bio") or "").strip()
            # Determine tone from career_tier
            tone_map = {
                "Elite": "champion_reign",
                "Contender": "champion_reign",
                "Prospect": "unproven_prospect",
                "Unproven": "unproven_prospect",
                "Gatekeeper": "mid_carder",
                "Fringe": "journeyman",
                "DecliningVet": "grizzled_veteran",
            }
            tone = tone_map.get(tier, "neutral")
            # bio_tone CHECK constraint lists allowed values; if not
            # present, fall back to 'neutral'.
            allowed_tones = {
                "neutral", "unproven_prospect", "grizzled_veteran",
                "champion_reign", "fallen_contender", "journeyman",
                "cult_hero", "mid_carder", "late_bloomer", "enforcer",
            }
            if tone not in allowed_tones:
                tone = "neutral"

            # UPSERT into fighter_bios (PK = fighter_id).
            conn.execute(
                """INSERT INTO fighter_bios (fighter_id, bio_text, bio_tone)
                   VALUES (?, ?, ?)
                   ON CONFLICT(fighter_id) DO UPDATE SET
                       bio_text = excluded.bio_text,
                       bio_tone = excluded.bio_tone,
                       updated_at = CURRENT_TIMESTAMP""",
                (fid, bio, tone),
            )

            rows_processed += 1

    conn.execute("COMMIT")
    conn.close()

    print(f"\n=== Reseed fighters from CSV: complete ===")
    print(f"  Rows processed      : {rows_processed}")
    print(f"  Fighters signed     : {signed_count}")
    print(f"  Free agents (overflow): {free_agent_count}")
    print(f"  New gyms created    : {new_gym_count}")
    print(f"  Promo assignment counts:")
    for pid in range(1, 11):
        print(f"    promo {pid:2d}: {promo_counts.get(pid, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(reseed())
