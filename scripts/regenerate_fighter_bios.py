#!/usr/bin/env python3
"""CR-14: Regenerate fighter bios to match actual DB records.

CAGE EMPIRE — Fix Plan for DB Audit Issue #5 (CR-14).
Reference: docs/CR10_14_FIX_PLAN.md §5 (CR-14 — Bio regeneration).

PROBLEM (verified by supervisor audit, docs/DB_REVIEW_AUDIT.md §3):
- fighter_bios table has 4477 bios. All textually unique. But 11 of 14
  sampled bios mention records that contradict fighter_career (e.g.,
  bio says "31 professional fights" but DB shows 2-0).
- Bios were generated against an earlier dataset (before fighter_career
  was finalized). They reference records, fight counts, win streaks,
  etc. that no longer match.

FIX:
- For each fighter, re-query their ACTUAL data (fighter_career, fighter_
  attributes, personality_archetypes, style_archetypes, fight_history,
  titles, gyms, weight_classes, nations, fighter_descriptors) and
  regenerate the bio using voice-compliant templates that REFERENCE the
  actual data.
- UPDATE fighter_bios (preserve fighter_id — UPDATE, not INSERT).
- Set bio_tone based on the fighter's career_phase (decoded from the
  "label||phrase" cache format in fighter_descriptors.career_phase).
- Idempotent: deterministic templates, no RNG. Re-running the script
  produces the same bios.

USAGE:
    python scripts/regenerate_fighter_bios.py

CONSTRAINTS:
- DB backup taken first: data/cage_empire.db.bak.pre-bio-regen.
- Performance: <30s for 4477 fighters.
- Voice compliance: no tabloid clichés, no ALL CAPS, 200-400 chars,
  pronouns match gender, references only ACTUAL data.
- No raw potential exposure: bios do NOT mention the fighter's
  potential integer. The career_phase phrase (voice-tiered) is OK.

DEVIATION FROM TASK SPEC (documented):
- The task spec §5.3 (in this task description) suggested bio_tone
  values like 'hopeful', 'determined', 'confident', 'weathered',
  'steady', 'reflective'. However, fighter_bios.bio_tone has a CHECK
  constraint that only allows: 'neutral', 'unproven_prospect',
  'grizzled_veteran', 'champion_reign', 'fallen_contender',
  'journeyman', 'cult_hero', 'mid_carder', 'late_bloomer', 'enforcer'.
  Inserting 'hopeful' etc. would raise a CHECK constraint violation.
  This script maps career_phase → the closest allowed bio_tone value:
    - prospect         → unproven_prospect
    - rising_contender → mid_carder
    - champion         → champion_reign
    - veteran          → grizzled_veteran
    - gatekeeper       → journeyman
    - declining        → fallen_contender
    - (null/unknown)   → neutral
"""
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.db.bak.pre-bio-regen"

# ============================================================
# CAREER PHASE → BIO_TONE MAPPING
# ============================================================
# fighter_bios.bio_tone is constrained by a CHECK to 10 values. We map
# each canonical career_phase label (decoded from the
# "label||phrase" cache in fighter_descriptors.career_phase) to the
# closest allowed tone. See DEVIATION note in module docstring.
CAREER_PHASE_TO_TONE = {
    "prospect":         "unproven_prospect",
    "rising_contender": "mid_carder",
    "champion":         "champion_reign",
    "veteran":          "grizzled_veteran",
    "gatekeeper":       "journeyman",
    "declining":        "fallen_contender",
}

DEFAULT_TONE = "neutral"

# ============================================================
# ATTRIBUTE PRETTY-NAME MAPPING
# ============================================================
# fighter_attributes stores attributes in snake_case (punch_power,
# fight_iq, etc.). For the bio, we want readable attribute names.
# The fighter_descriptors.attribute_descriptors JSON column already
# holds voice phrases per attribute (e.g., "carries real knockout
# power"); we prefer those phrases when present, fall back to the
# prettified attribute name when not.
ATTR_PRETTY = {
    "punch_power":         "punch power",
    "cardio":              "cardio",
    "fight_iq":            "fight IQ",
    "chin":                "chin",
    "punch_accuracy":      "punch accuracy",
    "kick_power":          "kick power",
    "kick_accuracy":       "kick accuracy",
    "head_movement":       "head movement",
    "footwork":            "footwork",
    "clinch_striking":     "clinch striking",
    "clinch_offense":      "clinch offense",
    "clinch_defense":      "clinch defense",
    "takedown_offense":    "takedown offense",
    "takedown_defense":    "takedown defense",
    "top_control":         "top control",
    "bottom_game":         "bottom game",
    "submission_offense":  "submission offense",
    "submission_defense":  "submission defense",
    "scramble_ability":    "scramble ability",
    "cage_wrestling":      "cage wrestling",
    "recovery_rate":       "recovery rate",
    "speed_explosiveness": "speed and explosiveness",
    "strength":            "strength",
    "durability":          "durability",
    "flexibility":         "flexibility",
    "adaptability":        "adaptability",
}

# Attribute columns in fighter_attributes (excludes metadata cols).
ATTRIBUTE_COLUMNS = [
    "punch_power", "cardio", "fight_iq", "chin",
    "punch_accuracy", "kick_power", "kick_accuracy", "head_movement",
    "footwork", "clinch_striking", "clinch_offense", "clinch_defense",
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "adaptability",
]


# ============================================================
# HELPERS
# ============================================================

def _decode_label(stored_value):
    """Decode the canonical label from a stored "label||phrase" value.

    Mirrors src/interpretation/context_engine.decode_label — we
    reimplement here (rather than import) to keep this script
    standalone (no sys.path manipulation, no src dependency).
    """
    if not stored_value or "||" not in stored_value:
        return None
    return stored_value.split("||", 1)[0]


def _decode_phrase(stored_value):
    """Decode the voice phrase from a stored "label||phrase" value."""
    if not stored_value or "||" not in stored_value:
        return None
    return stored_value.split("||", 1)[1]


def _compute_age(dob_str, today_str):
    """Compute age in years from date_of_birth + today's date.

    Both args are ISO date strings (YYYY-MM-DD). Returns int.
    Defensive: if dob_str is NULL/empty, returns 0.
    """
    if not dob_str or not today_str:
        return 0
    try:
        dob_y, dob_m, dob_d = (int(x) for x in dob_str.split("-")[:3])
        today_y, today_m, today_d = (int(x) for x in today_str.split("-")[:3])
    except (ValueError, AttributeError):
        return 0
    age = today_y - dob_y
    # Subtract 1 if the birthday hasn't happened yet this year.
    if (today_m, today_d) < (dob_m, dob_d):
        age -= 1
    return age


def _format_record(wins, losses, draws):
    """Format a fighter's record as 'W-L' or 'W-L-D' (D only if >0)."""
    record = f"{wins}-{losses}"
    if draws and draws > 0:
        record += f"-{draws}"
    return record


def _top3_attributes(attr_row, attr_descriptor_json):
    """Return top 3 attributes by value as (pretty_name, phrase) tuples.

    Args:
        attr_row: sqlite3.Row from fighter_attributes (all 26 cols).
        attr_descriptor_json: parsed dict from
            fighter_descriptors.attribute_descriptors, or None.

    Returns:
        List of (pretty_name, phrase) tuples, top 3 by attribute value.
        Phrase is the voice phrase from descriptors if present, else
        the prettified attribute name.
    """
    if attr_row is None:
        return []
    # Build (col_name, value) list, sort by value desc, take top 3.
    pairs = []
    for col in ATTRIBUTE_COLUMNS:
        val = attr_row[col]
        if val is None:
            val = 0
        pairs.append((col, int(val)))
    pairs.sort(key=lambda x: -x[1])
    top3 = pairs[:3]

    # Look up descriptor phrase + prettified name.
    descriptors = attr_descriptor_json or {}
    result = []
    for col, _val in top3:
        phrase = descriptors.get(col)
        pretty = ATTR_PRETTY.get(col, col.replace("_", " "))
        if phrase:
            result.append((pretty, phrase))
        else:
            result.append((pretty, pretty))
    return result


# ============================================================
# BIO GENERATION (DETERMINISTIC — NO RNG)
# ============================================================

def _generate_bio(d):
    """Generate a voice-compliant bio from actual fighter data.

    Args:
        d: dict with keys (see _load_fighter_data for source):
            first_name, last_name, nickname, gender, age,
            weight_class_name, nationality_name, stance,
            wins, losses, draws, win_streak, loss_streak,
            style_name, personality_name,
            career_phase_label, career_phase_phrase,
            is_champion, title_reigns, gym_name,
            top3_attrs (list of (pretty, phrase) tuples),
            total_fights

    Returns:
        (bio_text, bio_tone) tuple. bio_text is the new bio (200-400
        chars). bio_tone is one of the CHECK-constrained tones.
    """
    name = f"{d['first_name']} {d['last_name']}"
    nick = d.get('nickname')
    age = d['age']
    wc = d['weight_class_name'] or "unclassified"
    nat = d['nationality_name'] or "parts unknown"
    record = _format_record(d['wins'], d['losses'], d['draws'])
    style = (d['style_name'] or "balanced").lower()
    personality = (d['personality_name'] or "balanced").lower()
    career_phase_label = d.get('career_phase_label')
    phase_phrase = d.get('career_phase_phrase') or ""
    is_champion = bool(d.get('is_champion'))
    title_reigns = d.get('title_reigns') or 0
    gym = d.get('gym_name')
    top3 = d.get('top3_attrs') or []
    gender = (d.get('gender') or 'unknown').lower()

    # Pronoun helper — gender-aware.
    if gender == 'female':
        pronoun_subj = 'she'
        pronoun_poss = 'her'
    else:
        # Default to male pronouns for 'male' and 'unknown' (the
        # vast majority of fighters in this DB are male).
        pronoun_subj = 'he'
        pronoun_poss = 'his'

    # ----- Opening line -----
    bio = f"{name}"
    if nick:
        bio += f" '{nick}'"
    bio += f" is a {age}-year-old {wc} from {nat}."

    # ----- Record line (ACTUAL, not invented) -----
    bio += f" {record} record"
    if d.get('win_streak', 0) >= 3:
        bio += f", on a {d['win_streak']}-fight win streak"
    elif d.get('loss_streak', 0) >= 3:
        bio += f", riding a {d['loss_streak']}-fight skid"
    bio += "."

    # ----- Style + personality line -----
    bio += f" Known as a {style} fighter, {personality} by nature."

    # ----- Attribute strength line (top 3 by value) -----
    if top3:
        attr_bits = [phrase for (_pretty, phrase) in top3 if phrase]
        if attr_bits:
            bio += " " + ", ".join(attr_bits) + "."

    # ----- Career phase line (voice phrase from interpretation layer) -----
    if phase_phrase:
        # Capitalize first letter of the phrase, ensure it ends with a
        # period. The phrase is a fragment like "a hungry prospect
        # learning on the job" — we capitalize + append period.
        phrase_clean = phase_phrase.strip().rstrip(".").strip()
        if phrase_clean:
            bio += f" {phrase_clean[0].upper()}{phrase_clean[1:]}."

    # ----- Title line (only if applicable) -----
    if is_champion:
        bio += f" Current {wc} champion."
    elif title_reigns > 0:
        # Voice-friendly: "1-time title holder" reads slightly off,
        # but the task spec specifies this phrasing — keep it.
        bio += f" Former {title_reigns}-time title holder."

    # ----- Gym line (only if gym present) -----
    if gym:
        bio += f" Trains at {gym}."

    # Determine bio_tone from career_phase label.
    bio_tone = CAREER_PHASE_TO_TONE.get(career_phase_label, DEFAULT_TONE)

    return bio, bio_tone


# ============================================================
# DATA LOADING (BULK — one SELECT, one Python loop)
# ============================================================

# One big SELECT that joins all the tables we need. This avoids N+1
# queries for 4477 fighters. The champion set is fetched in a separate
# small SELECT (titles.current_champion_fighter_id).
FIGHTER_SELECT_SQL = """
SELECT
    f.fighter_id,
    f.first_name,
    f.last_name,
    f.nickname,
    f.gender,
    f.date_of_birth,
    f.stance,
    f.weight_class_id,
    wc.name                AS weight_class_name,
    n.name                 AS nationality_name,
    g.name                 AS gym_name,
    sa.name                AS style_name,
    pa.name                AS personality_name,
    c.record_wins,
    c.record_losses,
    c.record_draws,
    c.win_streak,
    c.loss_streak,
    c.career_health,
    c.title_reigns,
    d.career_phase,
    d.attribute_descriptors,
    fa.*,
    (SELECT COUNT(*) FROM fight_history fh WHERE fh.fighter_id = f.fighter_id) AS total_fights
FROM fighters f
LEFT JOIN weight_classes wc ON f.weight_class_id = wc.weight_class_id
LEFT JOIN nations        n  ON f.birth_nation_id = n.nation_id
LEFT JOIN gyms           g  ON f.current_gym_id  = g.gym_id
LEFT JOIN style_archetypes         sa ON f.fight_style_archetype_id      = sa.style_archetype_id
LEFT JOIN personality_archetypes   pa ON f.personality_archetype_id      = pa.personality_archetype_id
LEFT JOIN fighter_career   c  ON f.fighter_id = c.fighter_id
LEFT JOIN fighter_descriptors d ON f.fighter_id = d.fighter_id
LEFT JOIN fighter_attributes  fa ON f.fighter_id = fa.fighter_id
ORDER BY f.fighter_id
"""

CHAMPION_SELECT_SQL = """
SELECT DISTINCT current_champion_fighter_id
FROM titles
WHERE is_vacant = 0
  AND current_champion_fighter_id IS NOT NULL
"""

SIM_DATE_SELECT_SQL = """
SELECT current_date FROM simulation_clock WHERE clock_id = 1
"""


def _load_fighter_data(conn):
    """Bulk-load all fighter data + champion set in 2 queries.

    Returns:
        List of dicts, one per fighter, with all fields needed by
        _generate_bio. Champion set is injected as 'is_champion' bool.
    """
    cur = conn.cursor()

    # Get current sim date (for age computation).
    row = cur.execute(SIM_DATE_SELECT_SQL).fetchone()
    today_str = row[0] if row else None

    # Get champion fighter_id set.
    champion_ids = {r[0] for r in cur.execute(CHAMPION_SELECT_SQL)}

    # Bulk-load all fighter data.
    fighters = []
    for r in cur.execute(FIGHTER_SELECT_SQL):
        # Parse attribute_descriptors JSON.
        ad_json_str = r["attribute_descriptors"] if "attribute_descriptors" in r.keys() else None
        try:
            attr_descriptors = json.loads(ad_json_str) if ad_json_str else {}
        except (json.JSONDecodeError, TypeError):
            attr_descriptors = {}

        # Compute top 3 attributes from the row's attribute columns.
        top3 = _top3_attributes(r, attr_descriptors)

        # Decode career_phase label + phrase from "label||phrase" cache.
        career_phase_raw = r["career_phase"] if "career_phase" in r.keys() else None
        career_phase_label = _decode_label(career_phase_raw)
        career_phase_phrase = _decode_phrase(career_phase_raw)

        # Compute age.
        age = _compute_age(r["date_of_birth"], today_str)

        fighters.append({
            "fighter_id":            r["fighter_id"],
            "first_name":            r["first_name"],
            "last_name":             r["last_name"],
            "nickname":              r["nickname"],
            "gender":                r["gender"],
            "age":                   age,
            "stance":                r["stance"],
            "weight_class_name":     r["weight_class_name"],
            "nationality_name":      r["nationality_name"],
            "gym_name":              r["gym_name"],
            "style_name":            r["style_name"],
            "personality_name":      r["personality_name"],
            "wins":                  r["record_wins"] or 0,
            "losses":                r["record_losses"] or 0,
            "draws":                 r["record_draws"] or 0,
            "win_streak":            r["win_streak"] or 0,
            "loss_streak":           r["loss_streak"] or 0,
            "career_health":         r["career_health"] or 100,
            "title_reigns":          r["title_reigns"] or 0,
            "career_phase_label":    career_phase_label,
            "career_phase_phrase":   career_phase_phrase,
            "top3_attrs":            top3,
            "total_fights":          r["total_fights"] or 0,
            "is_champion":           r["fighter_id"] in champion_ids,
        })

    return fighters


# ============================================================
# DB BACKUP + MAIN
# ============================================================

def _backup_db():
    """Copy data/cage_empire.db to data/cage_empire.db.bak.pre-bio-regen.

    Refuses to overwrite an existing backup — we want the FIRST pre-
    regen state preserved across re-runs (idempotent regen, not
    idempotent backup). If a backup already exists, we leave it in
    place and continue.
    """
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(2)
    if BACKUP_PATH.exists():
        print(f"Backup already exists at {BACKUP_PATH} (leaving in place).")
        return
    shutil.copy2(DB_PATH, BACKUP_PATH)
    size_mb = BACKUP_PATH.stat().st_size / (1024 * 1024)
    print(f"Backup taken: {BACKUP_PATH} ({size_mb:.1f} MB)")


def main():
    """Entry point — backup DB, regenerate all bios, print summary."""
    print("=" * 60)
    print("CR-14: Regenerate fighter bios to match DB records")
    print("Reference: docs/CR10_14_FIX_PLAN.md §5")
    print("=" * 60)

    _backup_db()

    t_start = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    print("Loading fighter data (single bulk SELECT)...")
    fighters = _load_fighter_data(conn)
    print(f"  loaded {len(fighters)} fighters")

    print("Generating + writing bios...")
    updates = []
    for fd in fighters:
        bio_text, bio_tone = _generate_bio(fd)
        updates.append((bio_text, bio_tone, fd["fighter_id"]))

    cur = conn.cursor()
    cur.executemany(
        "UPDATE fighter_bios "
        "SET bio_text = ?, bio_tone = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE fighter_id = ?",
        updates,
    )
    rows_updated = cur.rowcount
    conn.commit()
    t_elapsed = time.time() - t_start

    print(f"  updated {rows_updated} bios in {t_elapsed:.2f}s")

    # ----- Summary + 5 sample bios -----
    print()
    print("=" * 60)
    print(f"Regenerated {rows_updated} bios. Sample 5:")
    print("=" * 60)
    # Deterministic sample: first 5 fighters (IDs 1-5).
    sample_fids = [fd["fighter_id"] for fd in fighters[:5]]
    sample_data = {fd["fighter_id"]: fd for fd in fighters[:5]}
    for fid in sample_fids:
        row = cur.execute(
            "SELECT bio_text, bio_tone FROM fighter_bios WHERE fighter_id = ?",
            (fid,),
        ).fetchone()
        fd = sample_data[fid]
        name = f"{fd['first_name']} {fd['last_name']}"
        if fd['nickname']:
            name += f" '{fd['nickname']}'"
        expected_rec = _format_record(fd['wins'], fd['losses'], fd['draws'])
        print(f"\n  [fid={fid}] {name} — expected record {expected_rec}")
        print(f"  tone: {row['bio_tone']}")
        print(f"  bio ({len(row['bio_text'])} chars):")
        print(f"    {row['bio_text']}")

    # ----- Length distribution check -----
    print()
    print("=" * 60)
    print("Bio length distribution (target: 200-400 chars):")
    print("=" * 60)
    lens = [r[0] for r in cur.execute("SELECT length(bio_text) FROM fighter_bios")]
    n = len(lens)
    in_range = sum(1 for L in lens if 200 <= L <= 400)
    below = sum(1 for L in lens if L < 200)
    above = sum(1 for L in lens if L > 400)
    avg = sum(lens) / max(1, n)
    print(f"  total bios:    {n}")
    print(f"  in 200-400:    {in_range} ({100*in_range/n:.1f}%)")
    print(f"  below 200:     {below} ({100*below/n:.1f}%)")
    print(f"  above 400:     {above} ({100*above/n:.1f}%)")
    print(f"  avg length:    {avg:.0f} chars")
    print(f"  min / max:     {min(lens)} / {max(lens)}")

    # ----- Tone distribution check -----
    print()
    print("=" * 60)
    print("bio_tone distribution after regen:")
    print("=" * 60)
    for r in cur.execute(
        "SELECT bio_tone, COUNT(*) FROM fighter_bios GROUP BY bio_tone "
        "ORDER BY COUNT(*) DESC"
    ):
        print(f"  {r[0]:<25} {r[1]}")

    conn.close()
    print()
    print(f"DONE. {rows_updated} bios regenerated in {t_elapsed:.2f}s.")
    print(f"Backup at: {BACKUP_PATH}")


if __name__ == "__main__":
    main()
