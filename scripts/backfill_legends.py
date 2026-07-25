#!/usr/bin/env python3
"""CAGE EMPIRE — Backfill retired legends' attributes/personality/career (Stage 6 prep).

The world seed (scripts/seed_world_phase5.py) creates 60 retired Hall
of Fame legends as historical figures — they have fighter rows and
hall_of_fame entries, but NO fighter_attributes, fighter_personality,
or fighter_career rows. This was acceptable when the legends were
purely historical (display-only), but the upcoming GUI Hall of Fame
screen (Task 6.11) needs to show their stats, career arc, and
personality for the "compare to current fighter" feature.

This script backfills the missing rows for all retired fighters
who lack them. It generates plausible stats based on:
  - The legend's fight_history record (wins/losses/draws + result types)
  - Their hall_of_fame inductee category (champion, pioneer, etc.)
  - Their style_archetype (Striker → high striking attrs, etc.)
  - Their personality_archetype

The generated stats are "frozen" — they represent the legend at
their peak (since they're retired, the stats don't need to evolve).
The potential is set equal to their best attribute (they've already
achieved their ceiling — that's why they're in the Hall of Fame).

Usage:
    python3 scripts/backfill_legends.py
    python3 scripts/backfill_legends.py --dry-run  # show what would be backfilled

CONVENTIONS compliance:
  §6  — Smoke test protocol. Run forensic_db_check.py before and
        after to verify the backfill.
  §13 — Design Law: Legacy pillar — the Hall of Fame screen tells
        the story of the sport's history. Legends need stats for
        the "compare to current" feature.
  §14 — Voice Layer: this script writes RAW attribute values (0-100)
        to the DB. The voice layer (src/voice.py) translates these
        to descriptors when the UI displays them. No §14 violation —
        the player never sees raw numbers from this script.
"""
import sys
import sqlite3
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

DRY_RUN = "--dry-run" in sys.argv


def get_legends_needing_backfill(conn):
    """Return list of fighter_ids for retired fighters missing attributes."""
    return [r[0] for r in conn.execute(
        "SELECT f.fighter_id FROM fighters f "
        "LEFT JOIN fighter_attributes fa ON f.fighter_id = fa.fighter_id "
        "WHERE f.is_retired = 1 AND fa.fighter_id IS NULL "
        "ORDER BY f.fighter_id"
    ).fetchall()]


def get_legend_record(conn, fighter_id):
    """Get the legend's career record from fighter_career (legends have
    no fight_history rows — their record is a summary in fighter_career)."""
    row = conn.execute(
        "SELECT record_wins, record_losses, record_draws "
        "FROM fighter_career WHERE fighter_id = ?",
        (fighter_id,)
    ).fetchone()
    if not row:
        return (0, 0, 0, 0)
    wins, losses, draws = row
    return (wins, losses, draws, wins + losses + draws)


def get_legend_finish_profile(conn, fighter_id):
    """Legends have no fight_history rows, so we can't compute finish
    profile from data. Return a neutral profile — the style archetype
    will drive the attribute generation instead."""
    return (0.33, 0.33, 0.34)  # neutral: 1/3 KO, 1/3 sub, 1/3 decision


def get_legend_archetypes(conn, fighter_id):
    """Get style + personality archetype IDs."""
    return conn.execute(
        "SELECT fight_style_archetype_id, personality_archetype_id "
        "FROM fighters WHERE fighter_id = ?",
        (fighter_id,)
    ).fetchone()


def generate_attributes(record, finish_profile, style_archetype_id, rng):
    """Generate 26 attribute values (0-100) based on record + style.

    Legends are ABOVE average (they're in the Hall of Fame). The
    base range is 60-85, with peaks at 90+ for their specialty.
    """
    wins, losses, draws, total = record
    ko_pct, sub_pct, dec_pct = finish_profile

    # Base level: legends are above average. Win rate adjusts the base.
    win_rate = wins / total if total > 0 else 0.5
    base = 60 + int(win_rate * 20)  # 60-80 base depending on win rate

    # Start with all attributes at base
    attrs = {col: base + rng.randint(-5, 5) for col in [
        "punch_power", "cardio", "fight_iq", "chin", "punch_accuracy",
        "kick_power", "kick_accuracy", "head_movement", "footwork",
        "clinch_striking", "clinch_offense", "clinch_defense",
        "takedown_offense", "takedown_defense", "top_control", "bottom_game",
        "submission_offense", "submission_defense", "scramble_ability",
        "cage_wrestling", "recovery_rate", "speed_explosiveness", "strength",
        "durability", "flexibility", "adaptability",
    ]}

    # Style archetype boosts (style_archetype_id: 1=Balanced, 2=Striker,
    # 3=Grappler, 4=Wrestler, 5=Brawler, 6=Counter-Striker, 7=Submission Specialist)
    if style_archetype_id == 2:  # Striker
        for col in ["punch_power", "kick_power", "punch_accuracy",
                    "kick_accuracy", "head_movement", "footwork"]:
            attrs[col] = min(95, attrs[col] + 15)
    elif style_archetype_id == 3:  # Grappler
        for col in ["takedown_offense", "clinch_offense", "top_control",
                    "submission_offense", "cage_wrestling"]:
            attrs[col] = min(95, attrs[col] + 15)
    elif style_archetype_id == 4:  # Wrestler
        for col in ["takedown_offense", "takedown_defense", "top_control",
                    "cage_wrestling", "strength"]:
            attrs[col] = min(95, attrs[col] + 15)
    elif style_archetype_id == 5:  # Brawler
        for col in ["punch_power", "chin", "durability", "strength"]:
            attrs[col] = min(95, attrs[col] + 15)
        attrs["fight_iq"] = max(30, attrs["fight_iq"] - 10)
    elif style_archetype_id == 6:  # Counter-Striker
        for col in ["head_movement", "footwork", "fight_iq",
                    "punch_accuracy", "speed_explosiveness"]:
            attrs[col] = min(95, attrs[col] + 15)
    elif style_archetype_id == 7:  # Submission Specialist
        for col in ["submission_offense", "submission_defense",
                    "bottom_game", "scramble_ability", "fight_iq"]:
            attrs[col] = min(95, attrs[col] + 15)

    # Finish profile boosts (KO-heavy → more power, sub-heavy → more sub skills)
    if ko_pct > 0.5:
        attrs["punch_power"] = min(95, attrs["punch_power"] + 10)
        attrs["chin"] = min(95, attrs["chin"] + 5)
    if sub_pct > 0.5:
        attrs["submission_offense"] = min(95, attrs["submission_offense"] + 10)
        attrs["scramble_ability"] = min(95, attrs["scramble_ability"] + 5)
    if dec_pct > 0.5:
        attrs["cardio"] = min(95, attrs["cardio"] + 10)
        attrs["fight_iq"] = min(95, attrs["fight_iq"] + 5)

    # Clamp all to 0-100
    for col in attrs:
        attrs[col] = max(10, min(100, attrs[col]))

    return attrs


def generate_personality(rng):
    """Generate 20 personality trait values (0-100) for a retired legend.

    Per the fighter_personality table schema (20 traits).
    """
    traits = {}
    for col in ["aggression", "composure", "morale", "risk_taking",
                "killer_instinct", "grit", "discipline", "patience",
                "ambition", "loyalty", "charisma", "attention_seeking",
                "coachability", "professionalism", "ego", "resilience",
                "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance"]:
        traits[col] = 50 + rng.randint(-15, 25)  # legends tend to be above average
    # morale is irrelevant for retired legends — set to 50 (neutral)
    traits["morale"] = 50
    return traits


def generate_career(conn, fighter_id, record, attrs, rng):
    """Generate fighter_career row for a retired legend.

    Legends already have fighter_career rows (created by the seed with
    record_wins/losses/draws + potential + title_reigns). We only need
    to UPDATE the potential to match the generated attributes (since we
    just generated attrs based on their record). The career_health
    stays at 0 (retired). title_reigns stays as-is (seeded correctly).
    """
    # Potential = max attribute (legends achieved their ceiling)
    potential = max(attrs.values())

    return {
        "fighter_id": fighter_id,
        "potential": potential,
        "career_health": 0,  # retired
        "title_reigns": None,  # keep existing — will use UPDATE, not INSERT
    }


def backfill_legend(conn, fighter_id, rng):
    """Backfill attributes + personality + career for one legend."""
    record = get_legend_record(conn, fighter_id)
    finish_profile = get_legend_finish_profile(conn, fighter_id)
    style_arch_id, pers_arch_id = get_legend_archetypes(conn, fighter_id)

    attrs = generate_attributes(record, finish_profile, style_arch_id, rng)
    personality = generate_personality(rng)
    career = generate_career(conn, fighter_id, record, attrs, rng)

    if DRY_RUN:
        print(f"  [DRY RUN] fighter_id={fighter_id} record={record[0]}-{record[1]}-{record[2]} "
              f"style={style_arch_id} potential={career['potential']}")
        return

    # Insert fighter_attributes
    attr_cols = list(attrs.keys())
    attr_vals = [attrs[c] for c in attr_cols]
    placeholders = ", ".join(["?"] * len(attr_cols))
    conn.execute(
        f"INSERT INTO fighter_attributes (fighter_id, {', '.join(attr_cols)}) "
        f"VALUES (?, {placeholders})",
        [fighter_id] + attr_vals
    )

    # Insert fighter_personality
    pers_cols = list(personality.keys())
    pers_vals = [personality[c] for c in pers_cols]
    placeholders = ", ".join(["?"] * len(pers_cols))
    conn.execute(
        f"INSERT INTO fighter_personality (fighter_id, {', '.join(pers_cols)}) "
        f"VALUES (?, {placeholders})",
        [fighter_id] + pers_vals
    )

    # Update fighter_career potential (legends already have career rows
    # from the seed — we just update potential to match the generated attrs)
    conn.execute(
        "UPDATE fighter_career SET potential = ?, career_health = 0 "
        "WHERE fighter_id = ?",
        (career["potential"], career["fighter_id"])
    )


def main():
    print("=" * 72)
    print("CAGE EMPIRE — Backfill Retired Legends' Attributes")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'APPLY'}")
    print()

    if not DB_PATH.exists():
        print(f"FATAL: DB file does not exist at {DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    legends = get_legends_needing_backfill(conn)
    print(f"Legends needing backfill: {len(legends)}")
    print()

    if not legends:
        print("All retired legends already have attributes. Nothing to do.")
        return

    rng = random.Random(42)  # deterministic seed for reproducibility

    for fighter_id in legends:
        backfill_legend(conn, fighter_id, rng)

    if not DRY_RUN:
        conn.commit()
        print()
        print(f"Backfilled {len(legends)} legends.")
        print("Run scripts/forensic_db_check.py to verify.")

    conn.close()


if __name__ == "__main__":
    main()
