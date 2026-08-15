#!/usr/bin/env python3
"""Phase 1.5 — Task 1.5C-seed-data (Group C): seed missing data.

This is the FINAL Group C reconciliation script for the world DB.
It seeds the 5 data tables that came back empty from Phase 1
(training_camps, suspensions, fighter_memory_links, show_ratings,
finance_transactions) and back-fills the new staff.gym_id column
for the 300 existing coaches (the schema migration itself is in
build_db.py: _migrate_v3_9_0_add_staff_gym_id, applied via
`python3 src/build_db.py --migrate`).

CONVENTIONS compliance:
  §5  — One table-group per task. This script seeds 5 EXISTING
        tables + back-fills 1 NEW column. The new column
        (staff.gym_id) is the ONLY schema change in this task
        (Fix C6). The other 5 fixes are pure data inserts into
        tables that already exist (their migrations ran in
        earlier tasks: training_camps v2.5.0, suspensions v3.4.0,
        fighter_memory_links v2.6.0, show_ratings v3.6.0,
        finance_transactions v3.0.0).
  §13 — Design Law (5 pillars):
        - C1 training_camps  → Investment (fighters develop between
          fights; the camp is the development unit)
        - C2 suspensions     → Conflict (a banned fighter is a
          scandal; the title picture is reshuffled in their absence)
        - C3 fighter_memory_links → Legacy (style_echo links are the
          machinery that surfaces "fighting style reminiscent of
          legend X" stories — the torch-passing thread)
        - C4 show_ratings    → Stories (every show gets a verdict;
          the great cards become "an instant classic")
        - C5 finance_transactions → Empire Builder (a promotion's
          balance sheet is the unit of empire)
        - C6 staff.gym_id    → Investment (coaches are tied to gyms;
          a gym with a great coach is where prospects develop)
  §14 — Voice layer. show_ratings.rating_description uses the voice
        descriptor from src/show_rating.py._describe_rating (5 tiers,
        no raw numbers). Suspension news items use voice descriptors
        for the fighter's career stage (voice.describe_career_stage),
        no raw suspension counts or day counts in player-facing text.
        The suspensions.description column is an admin note (not
        player-facing per src/suspensions.py §14).
  §16 — Migration workflow. The schema change is implemented as an
        idempotent migration in build_db.py (_migrate_v3_9_0_add_
        staff_gym_id, registered in MIGRATIONS list, CODE_SCHEMA_
        VERSION bumped 3.8.0 → 3.9.0 MINOR). This script does NOT
        modify schema — it back-fills data only.

IDEMPOTENCY:
  - training_camps:    no UNIQUE constraint; this script checks
                        `existing fighter camp count` before
                        inserting. A re-run is a no-op if camps
                        already exist (it counts existing rows
                        before inserting).
  - suspensions:        no UNIQUE; checks `existing count >= 8` and
                        skips if so.
  - fighter_memory_links: UNIQUE (fighter_id, linked_fighter_id,
                        link_type). Uses INSERT OR IGNORE — re-runs
                        are no-ops.
  - show_ratings:       UNIQUE (event_id). Uses INSERT OR IGNORE.
  - finance_transactions: no UNIQUE; checks `existing count` per
                        promotion and skips if opening_balance
                        already exists for that promotion.
  - staff.gym_id:       checks `coaches with NULL gym_id` count
                        and only updates the ones still unassigned.

USAGE:
    python3 scripts/group_c_seed.py            # all 6 fixes
    python3 scripts/group_c_seed.py --check    # report counts, no writes
"""
import sys
import os
import sqlite3
import random
import argparse
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

# Imports from src/
import build_db  # noqa: E402  — for CODE_SCHEMA_VERSION sanity check
import show_rating  # noqa: E402 — for _describe_rating voice descriptor
import voice  # noqa: E402 — for describe_career_stage (suspension news)


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# Sanity: this script expects the world DB to already be at v3.9.0.
# The migration (applied via `python3 src/build_db.py --migrate`)
# adds the staff.gym_id column. If we're at an older version, abort.
EXPECTED_SCHEMA_VERSION = "3.9.0"

# Camp focus options (per the training_camps CHECK constraint).
# Per-archetype focus maps — each archetype has 2-3 "natural" focuses
# that a fighter of that style would pick for a camp. Strikers don't
# usually pick 'grappling' camps; submission specialists don't
# usually pick 'striking' camps. 'general' + 'conditioning' are
# universal fallbacks.
ARCHETYPE_FOCUS = {
    1: ["general", "conditioning", "striking"],          # Balanced
    2: ["striking", "clinch", "general"],                # Striker
    3: ["grappling", "submission", "general"],           # Grappler
    4: ["wrestling", "clinch", "conditioning"],          # Wrestler
    5: ["striking", "conditioning", "general"],          # Brawler
    6: ["striking", "clinch", "general"],                # Counter-Striker
    7: ["submission", "grappling", "general"],           # Submission Specialist
}
DEFAULT_FOCUS = "general"

# Suspension type templates. Per src/suspensions.py:
#   drug_test_failure: 6-12 months (180-365 days)
#   behavior: 3-6 months (90-180 days)
#   missed_weight_repeat: 30-60 days (medical-style; brief)
#   post_fight_brawl: 90-180 days (behavioral)
#   social_media_violation: 30-90 days (behavioral)
# Per the brief: 3 USADA-style + 3 medical + 2 behavioral = 8 total.
# 'medical' isn't in the suspensions CHECK constraint — we use
# 'missed_weight_repeat' is wrong; the closest is 'drug_test_failure'
# but that's not medical. Looking at the CHECK constraint values:
#   'drug_test_failure', 'behavior', 'missed_weight_repeat',
#   'post_fight_brawl', 'social_media_violation'
# There's no 'medical' value. The brief says "3 medical (medical
# suspension from a recent fight, 30-60 day duration)" — but the
# schema doesn't support 'medical' as a type. D1: interpret "medical"
# as 'post_fight_brawl' (closest behavioral analog for a fight
# aftermath) — actually, the brief said medical = "medical
# suspension from a recent fight", which is a commission medical
# suspension (concussion, broken bone). The closest schema value is
# 'post_fight_brawl' (fight aftermath) — but that's not medical
# either. D1 decision: use 'behavior' for the medical suspensions
# with a description that explains the medical nature (concussion
# protocol, etc.). The description column captures the specifics;
# the type column is the closest schema value. See worklog for D1.
SUSPENSION_TEMPLATES = [
    # (suspension_type, duration_min, duration_max, description, news_topic_prefix)
    ("drug_test_failure", 180, 365,
     "USADA drug test failure — metabolites of a banned substance detected.",
     "drug test failure"),
    ("drug_test_failure", 180, 365,
     "Out-of-competition drug test failure — the fighter has been "
     "pulled from competition pending a full investigation.",
     "drug test failure"),
    ("drug_test_failure", 180, 365,
     "In-competition drug test failure — elevated testosterone "
     "ratio flagged by the commission lab.",
     "drug test failure"),
    # 3 "medical" suspensions (D1: encoded as 'behavior' since the
    # schema has no 'medical' value; description is the medical
    # context).
    ("behavior", 30, 60,
     "Commission medical suspension — concussion protocol following "
     "a first-round knockout loss. The fighter is medically "
     "ineligible to compete for the duration.",
     "medical suspension"),
    ("behavior", 30, 60,
     "Commission medical suspension — orbital fracture sustained in "
     "the bout requires surgical repair. The fighter is medically "
     "ineligible to compete until cleared by a ringside physician.",
     "medical suspension"),
    ("behavior", 30, 60,
     "Commission medical suspension — suspected MCL tear. The "
     "fighter is on an extended medical hold pending MRI results.",
     "medical suspension"),
    # 2 behavioral suspensions (disciplinary)
    ("post_fight_brawl", 90, 180,
     "Disciplinary suspension — incited a post-fight brawl at the "
     "previous event. The commission has handed down a stiff ban.",
     "disciplinary suspension"),
    ("social_media_violation", 90, 180,
     "Disciplinary suspension — repeated social media violations "
     "including threats against officials and opponents. The "
     "promotion and commission acted jointly.",
     "disciplinary suspension"),
]

# Finance transaction types (per the finance_transactions CHECK):
#   'ticket_sales', 'broadcast_revenue', 'merchandise',
#   'fighter_purse', 'venue_rental', 'staff_salary',
#   'medical_cost', 'signing_bonus', 'weight_cut_penalty',
#   'sponsorship', 'bonus_payment'
# Per the brief: opening_balance isn't in the CHECK constraint.
# D2: Use 'sponsorship' as the closest analog for "opening balance"
# — actually no. Looking more carefully: opening_balance isn't a
# valid type. D2: skip the opening_balance transaction; instead
# create a 'sponsorship' transaction equal to the starting_budget
# dated at sim start (represents the initial capital injection
# from sponsors / investors). Document as D2. This stays within the
# schema's CHECK constraint while still giving the Finance screen
# a starting point (the sponsorship row appears as the earliest
# transaction in the log, dated before any other).
FINANCE_TRANSACTION_TYPES = [
    "ticket_sales",
    "broadcast_revenue",
    "merchandise",
    "fighter_purse",   # negative — paying a fighter
    "venue_rental",    # negative — paying for a venue
    "staff_salary",    # negative — paying staff
    "medical_cost",    # negative — paying medical bills
    "signing_bonus",   # negative — paying a signing bonus
    "sponsorship",     # positive — sponsor income
    "bonus_payment",   # negative — paying a performance bonus
]

# Voice-layer show-rating descriptors (per src/show_rating.py).
# show_rating._describe_rating(overall) returns the right descriptor
# — we use that function directly to ensure consistency with the
# event-bus subscriber (no duplication of the descriptor table).


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _add_days(date_str, days):
    """Add `days` to an ISO date string, return ISO date string."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str


def _sub_days(date_str, days):
    """Subtract `days` from an ISO date string."""
    return _add_days(date_str, -days)


def _today(conn):
    """Return the sim clock's current_date."""
    row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else "2026-07-26"


def _ensure_system_feed(conn):
    """Get or create the System Feed news source. Returns news_source_id."""
    row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO news_sources (name, credibility, sensationalism, "
        "bias, regional_reach, reliability, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("System Feed", 70, 40, 50, 60, 80, 80),
    )
    return cur.lastrowid


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(v)))


# ----------------------------------------------------------------
# Fix C6 (data half): assign coaches to gyms.
# ----------------------------------------------------------------

def fix_c6_assign_coaches_to_gyms(conn, rng, check_only=False):
    """For each coach (role_type='coach'), assign to a gym.

    Match by nation_id if possible (the coach's nation_id matches
    a gym's nation_id). If no gym exists in the coach's nation,
    pick a random gym. Idempotent: skips coaches that already have
    gym_id set.
    """
    print("\n=== Fix C6 (data): assign coaches to gyms ===")

    coaches = conn.execute(
        "SELECT staff_id, nation_id FROM staff "
        "WHERE role_type='coach' AND gym_id IS NULL "
        "ORDER BY staff_id"
    ).fetchall()
    print(f"  Coaches without gym_id: {len(coaches)}")

    if check_only:
        return 0

    if not coaches:
        return 0

    # Pre-load gyms by nation for fast lookup.
    gyms_by_nation = {}
    all_gym_ids = []
    for gym_id, nation_id in conn.execute(
        "SELECT gym_id, nation_id FROM gyms ORDER BY gym_id"
    ).fetchall():
        all_gym_ids.append(gym_id)
        if nation_id is not None:
            gyms_by_nation.setdefault(nation_id, []).append(gym_id)

    n_assigned = 0
    for staff_id, nation_id in coaches:
        if nation_id is not None and nation_id in gyms_by_nation:
            gym_id = rng.choice(gyms_by_nation[nation_id])
        elif all_gym_ids:
            gym_id = rng.choice(all_gym_ids)
        else:
            # No gyms at all — leave gym_id NULL (defensive).
            continue
        conn.execute(
            "UPDATE staff SET gym_id=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE staff_id=? AND gym_id IS NULL",
            (gym_id, staff_id),
        )
        n_assigned += 1
    print(f"  Assigned: {n_assigned}")
    return n_assigned


# ----------------------------------------------------------------
# Fix C1: seed training_camps.
# ----------------------------------------------------------------

def fix_c1_seed_training_camps(conn, rng, check_only=False):
    """Seed training_camps rows.

    Two batches:
      1. Active camps for fighters with a scheduled fight. (0 such
         fighters in the current world DB — there are 0 scheduled
         events. The check is here for forward-compatibility.)
         For each, create a training_camps row with start_date 14
         days before the event date, end_date 1 day before, status
         active, is_completed=0.
      2. ~50 historical COMPLETED camps for random active fighters.
         These are for historical flavor — past camps that already
         finished. status completed (is_active=0, is_completed=1),
         dates in the past, camp_focus appropriate to archetype.
    """
    print("\n=== Fix C1: seed training_camps ===")

    existing = conn.execute("SELECT COUNT(*) FROM training_camps").fetchone()[0]
    print(f"  Existing training_camps rows: {existing}")

    if check_only:
        return 0, 0

    today = _today(conn)
    n_active = 0
    n_completed = 0

    # ---- Batch 1: active camps for fighters with scheduled fights ----
    # Find fighters scheduled to fight on an upcoming (status='scheduled')
    # event. Each fight_participant row on a scheduled event = one
    # fighter who needs a training camp.
    scheduled = conn.execute(
        "SELECT DISTINCT fp.fighter_id, f.current_gym_id, "
        "       f.fight_style_archetype_id, e.event_date, e.event_id, "
        "       fi.fight_id "
        "FROM fight_participants fp "
        "JOIN fights fi ON fi.fight_id=fp.fight_id "
        "JOIN events e ON e.event_id=fi.event_id "
        "JOIN fighters f ON f.fighter_id=fp.fighter_id "
        "WHERE e.status='scheduled' "
        "AND e.event_date > ? "
        "ORDER BY fp.fighter_id",
        (today,),
    ).fetchall()
    print(f"  Fighters with scheduled fights: {len(scheduled)}")

    for (fighter_id, gym_id, archetype_id, event_date,
         event_id, fight_id) in scheduled:
        if gym_id is None:
            continue  # can't camp without a gym
        start_date = _sub_days(event_date, 14)
        end_date = _sub_days(event_date, 1)
        duration_days = 13
        focus = rng.choice(
            ARCHETYPE_FOCUS.get(archetype_id, [DEFAULT_FOCUS])
        )
        # Camp spec values — fresh camp, low fatigue, mid morale.
        morale = rng.randint(45, 65)
        fatigue = rng.randint(0, 15)
        injury_risk = rng.randint(0, 15)
        weight_cut_pressure = rng.randint(0, 30)
        conn.execute(
            "INSERT INTO training_camps "
            "(fighter_id, gym_id, event_id, fight_id, start_date, "
            " end_date, camp_duration_days, camp_focus, camp_morale, "
            " camp_fatigue, camp_injury_risk, camp_weight_cut_pressure, "
            " is_active, is_completed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)",
            (fighter_id, gym_id, event_id, fight_id, start_date,
             end_date, duration_days, focus, morale, fatigue,
             injury_risk, weight_cut_pressure),
        )
        n_active += 1
    print(f"  Active camps created: {n_active}")

    # ---- Batch 2: ~50 historical completed camps ----
    # Idempotency: skip entirely if the table already has 50+ rows
    # (a re-run should not duplicate the historical batch).
    if existing >= 50:
        print(f"  Historical camps already seeded (>=50) — skipping.")
        return n_active, n_completed

    # Pick 50 random active fighters with a non-NULL gym_id and a
    # non-NULL archetype_id. (We need the archetype to pick a focus.)
    candidates = conn.execute(
        "SELECT fighter_id, current_gym_id, fight_style_archetype_id "
        "FROM fighters "
        "WHERE is_active=1 AND current_gym_id IS NOT NULL "
        "AND fight_style_archetype_id IS NOT NULL "
        "ORDER BY RANDOM() LIMIT 50"
    ).fetchall()
    print(f"  Candidates for historical camps: {len(candidates)}")

    for (fighter_id, gym_id, archetype_id) in candidates:
        # Camp ended 30-180 days ago; duration 14-21 days.
        end_offset = rng.randint(30, 180)
        duration = rng.randint(14, 21)
        end_date = _sub_days(today, end_offset)
        start_date = _sub_days(end_date, duration)
        focus = rng.choice(
            ARCHETYPE_FOCUS.get(archetype_id, [DEFAULT_FOCUS])
        )
        morale = rng.randint(40, 75)
        fatigue = rng.randint(10, 40)
        injury_risk = rng.randint(0, 20)
        weight_cut_pressure = rng.randint(0, 30)
        # Camp result summary — short admin note (not player-facing
        # directly; the news engine produces the player-facing
        # narrative when a camp completes).
        summaries = [
            "Completed without incident — modest attribute gains.",
            "Solid camp — fighter reported feeling sharp.",
            "Heavy sparring week — accumulated some fatigue.",
            "Tactical focus on cage wrestling — coach pleased.",
            "Conditioning emphasis — cardio gains expected.",
            "Striking focus — combinations tightened.",
        ]
        conn.execute(
            "INSERT INTO training_camps "
            "(fighter_id, gym_id, event_id, fight_id, start_date, "
            " end_date, camp_duration_days, camp_focus, camp_morale, "
            " camp_fatigue, camp_injury_risk, camp_weight_cut_pressure, "
            " attribute_changes, camp_result_summary, "
            " is_active, is_completed) "
            "VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, 1)",
            (fighter_id, gym_id, start_date, end_date,
             duration, focus, morale, fatigue, injury_risk,
             weight_cut_pressure, rng.choice(summaries)),
        )
        n_completed += 1
    print(f"  Historical completed camps created: {n_completed}")
    return n_active, n_completed


# ----------------------------------------------------------------
# Fix C2: seed suspensions + news items.
# ----------------------------------------------------------------

def fix_c2_seed_suspensions(conn, rng, check_only=False):
    """Seed 8 active suspensions + suspension news items.

    Per the brief: 3 USADA-style (drug_test_failure, 6-12 month),
    3 medical (encoded as 'behavior' per D1, 30-60 day), 2
    behavioral (post_fight_brawl / social_media_violation, 3-6
    month). For each, write a topic='suspension' news item using
    voice.describe_career_stage (no raw numbers per §14).
    """
    print("\n=== Fix C2: seed suspensions ===")

    existing = conn.execute("SELECT COUNT(*) FROM suspensions").fetchone()[0]
    print(f"  Existing suspensions rows: {existing}")
    if existing >= 8:
        print("  Already seeded — skipping.")
        return 0

    if check_only:
        return 0

    today = _today(conn)
    src_id = _ensure_system_feed(conn)

    # Pick 8 fighters to suspend. Use active fighters with a
    # current_promotion_id (so the news has a promotion context).
    # Avoid fighters already suspended.
    candidates = conn.execute(
        "SELECT fighter_id, first_name, last_name, current_promotion_id, "
        "       birth_nation_id, fight_style_archetype_id "
        "FROM fighters "
        "WHERE is_active=1 AND current_promotion_id IS NOT NULL "
        "AND fighter_id NOT IN (SELECT fighter_id FROM suspensions "
        "                       WHERE is_active=1) "
        "ORDER BY RANDOM() LIMIT 8"
    ).fetchall()
    print(f"  Candidates for suspension: {len(candidates)}")
    if not candidates:
        return 0

    n_created = 0
    for idx, (fighter_id, first, last, promo_id, nation_id,
              archetype_id) in enumerate(candidates):
        template = SUSPENSION_TEMPLATES[idx % len(SUSPENSION_TEMPLATES)]
        (susp_type, dur_min, dur_max, description,
         news_topic_prefix) = template
        duration_days = rng.randint(dur_min, dur_max)

        # start_date: 5-30 days ago (recent — so end_date is still
        # in the future for the "active" period).
        start_offset = rng.randint(5, 30)
        start_date = _sub_days(today, start_offset)
        end_date = _add_days(start_date, duration_days)

        # If end_date is in the past, push it forward so the
        # suspension is still active (forensic check 4.4 requires
        # is_active=1 suspensions have end_date >= today).
        if end_date < today:
            # Bump end_date to today + (remaining days). We do this
            # by simply recomputing start_date as today - 5.
            start_date = _sub_days(today, 5)
            end_date = _add_days(start_date, duration_days)

        # Insert the suspension row.
        conn.execute(
            "INSERT INTO suspensions "
            "(fighter_id, suspension_type, start_date, end_date, "
            " duration_days, description, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (fighter_id, susp_type, start_date, end_date,
             duration_days, description),
        )
        n_created += 1

        # Write a topic='suspension' news item. Per §14, NO raw
        # numbers in the headline or body. The fighter's career
        # stage + suspension reason is enough narrative. We use
        # voice.describe_career_stage to get a career-stage phrase
        # (NOT a digit age).
        # Career-stage inputs: age, wins, losses, draws, is_champ,
        # title_reigns, win_streak, loss_streak.
        career_row = conn.execute(
            "SELECT f.date_of_birth, fc.record_wins, fc.record_losses, "
            "       fc.record_draws, fc.win_streak, fc.loss_streak, "
            "       fc.title_reigns "
            "FROM fighters f "
            "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
            "WHERE f.fighter_id=?",
            (fighter_id,),
        ).fetchone()
        is_champ = conn.execute(
            "SELECT 1 FROM titles "
            "WHERE current_champion_fighter_id=? AND is_vacant=0",
            (fighter_id,),
        ).fetchone() is not None
        if career_row:
            (dob, wins, losses, draws, ws, ls, tr) = career_row
            age = None
            if dob:
                try:
                    born = datetime.strptime(dob, "%Y-%m-%d")
                    today_dt = datetime.strptime(today, "%Y-%m-%d")
                    age = (today_dt - born).days // 365
                except (ValueError, TypeError):
                    age = 30
            career_stage = voice.describe_career_stage(
                age or 30, wins or 0, losses or 0, draws or 0,
                is_champ, tr or 0, ws or 0, ls or 0, rng,
            )
        else:
            career_stage = "competitor"

        # Voice-only headline — no digit characters anywhere.
        # The news_topic_prefix ("drug test failure", "medical
        # suspension", "disciplinary suspension") tells the story.
        headline = (
            f"{first} {last} hit with {news_topic_prefix}"
        )
        body = (
            f"{first} {last}, {career_stage}, has been suspended "
            f"following a {news_topic_prefix}. The commission "
            f"handed down the ruling earlier today; the fighter "
            f"will be ineligible to compete until the ban is served. "
            f"Promotion officials are reviewing how the absence "
            f"reshuffles the title picture."
        )
        conn.execute(
            "INSERT INTO news_items "
            "(news_source_id, headline, body, sentiment, topic, "
            " fighter_id, promotion_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, "negative", "suspension",
             fighter_id, promo_id, start_date),
        )

    print(f"  Suspensions created: {n_created}")
    print(f"  Suspension news items written: {n_created}")
    return n_created


# ----------------------------------------------------------------
# Fix C3: seed fighter_memory_links for HoF legends.
# ----------------------------------------------------------------

def fix_c3_seed_memory_links(conn, rng, check_only=False):
    """Seed fighter_memory_links (style_echo) for HoF legends.

    For each HoF inductee, find 1-2 active fighters with the same
    style_archetype_id and create a 'style_echo' link (fighter_id=
    active_fighter, linked_fighter_id=HoF_legend, link_strength=70).

    Per the brief, "1-2 active fighters with the same style_
    archetype_id". The HoF inductees were seeded (Phase 5) WITHOUT
    a fight_style_archetype_id — they all have NULL. D3: backfill
    each HoF fighter's archetype_id deterministically based on
    fighter_id (so the same HoF gets the same archetype on re-run).
    This is a data reconciliation step that makes the C3 fix work
    end-to-end. Without it, no HoF legend could ever be linked to
    an active fighter via style_echo (the populate_style_echo
    function in src/services/memory_svc.py early-returns on NULL
    archetypes).

    The backfill uses (fighter_id mod 7) + 1 to pick an archetype_id
    in {1..7}. This is deterministic and evenly distributed across
    the 7 archetypes. After backfill, the 60 HoF legends are
    distributed ~8-9 per archetype, which mirrors the active-fighter
    distribution (the active roster has 362-900 fighters per
    archetype).
    """
    print("\n=== Fix C3: seed fighter_memory_links for HoF legends ===")

    existing = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    print(f"  Existing fighter_memory_links rows: {existing}")

    if check_only:
        return 0

    # D3: backfill HoF fighters' archetype_id if NULL.
    hof_null_archetype = conn.execute(
        "SELECT COUNT(*) FROM hall_of_fame h "
        "JOIN fighters f ON f.fighter_id=h.fighter_id "
        "WHERE f.fight_style_archetype_id IS NULL"
    ).fetchone()[0]
    print(f"  HoF legends with NULL archetype_id: {hof_null_archetype}")
    if hof_null_archetype > 0:
        for (fid,) in conn.execute(
            "SELECT f.fighter_id FROM hall_of_fame h "
            "JOIN fighters f ON f.fighter_id=h.fighter_id "
            "WHERE f.fight_style_archetype_id IS NULL"
        ).fetchall():
            # Deterministic pick: (fighter_id mod 7) + 1.
            archetype_id = ((fid - 1) % 7) + 1
            conn.execute(
                "UPDATE fighters SET fight_style_archetype_id=?, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE fighter_id=?",
                (archetype_id, fid),
            )
        print(f"  Backfilled archetype_id for {hof_null_archetype} HoF legends")

    # For each HoF legend, find 1-2 active fighters with the same
    # archetype and create style_echo links.
    hof_legends = conn.execute(
        "SELECT h.fighter_id, f.fight_style_archetype_id "
        "FROM hall_of_fame h "
        "JOIN fighters f ON f.fighter_id=h.fighter_id "
        "WHERE f.fight_style_archetype_id IS NOT NULL"
    ).fetchall()
    print(f"  HoF legends to process: {len(hof_legends)}")

    n_links = 0
    for (legend_id, archetype_id) in hof_legends:
        # Idempotency: skip legends that already have 2+ style_echo
        # links (the brief says "1-2 active fighters per legend" —
        # if we already created 2, don't add more on a re-run).
        existing_for_legend = conn.execute(
            "SELECT COUNT(*) FROM fighter_memory_links "
            "WHERE linked_fighter_id=? AND link_type='style_echo'",
            (legend_id,),
        ).fetchone()[0]
        if existing_for_legend >= 2:
            continue

        # Pick 1-2 active fighters with the same archetype (not the
        # legend themselves). RANDOM() ensures variety on each run,
        # but INSERT OR IGNORE makes re-runs idempotent.
        n_targets = rng.randint(1, 2)
        targets = conn.execute(
            "SELECT fighter_id FROM fighters "
            "WHERE is_active=1 AND fighter_id != ? "
            "AND fight_style_archetype_id=? "
            "ORDER BY RANDOM() LIMIT ?",
            (legend_id, archetype_id, n_targets),
        ).fetchall()
        for (active_id,) in targets:
            cur = conn.execute(
                "INSERT OR IGNORE INTO fighter_memory_links "
                "(fighter_id, linked_fighter_id, link_type, link_strength) "
                "VALUES (?, ?, 'style_echo', 70)",
                (active_id, legend_id),
            )
            if cur.rowcount > 0:
                n_links += 1
    print(f"  style_echo memory links created: {n_links}")
    return n_links


# ----------------------------------------------------------------
# Fix C4: seed show_ratings for historical events.
# ----------------------------------------------------------------

def fix_c4_seed_show_ratings(conn, rng, check_only=False):
    """Seed show_ratings for ~500 historical completed events.

    For each sampled event:
      - Generate fan_rating (50-90), commercial_rating (40-80),
        excitement_rating (50-95), quality_rating (50-85).
      - Compute overall_rating as a weighted average:
        fan 30% + commercial 20% + excitement 25% + quality 25%.
        (Mirrors src/show_rating.py._compute_overall_rating.)
      - Generate rating_description via show_rating._describe_rating
        (5 tiers, NO raw numbers per §14).
      - INSERT OR IGNORE (idempotent — UNIQUE event_id).
    """
    print("\n=== Fix C4: seed show_ratings ===")

    existing = conn.execute("SELECT COUNT(*) FROM show_ratings").fetchone()[0]
    print(f"  Existing show_ratings rows: {existing}")

    if check_only:
        return 0

    # Sample 500 completed events that don't already have a
    # show_ratings row.
    sample = conn.execute(
        "SELECT e.event_id, e.promotion_id, e.event_date "
        "FROM events e "
        "WHERE e.status='completed' "
        "AND e.event_id NOT IN (SELECT event_id FROM show_ratings) "
        "ORDER BY RANDOM() LIMIT 500"
    ).fetchall()
    print(f"  Sampled events: {len(sample)}")

    n_created = 0
    for (event_id, promo_id, event_date) in sample:
        fan = rng.randint(50, 90)
        commercial = rng.randint(40, 80)
        excitement = rng.randint(50, 95)
        quality = rng.randint(50, 85)
        # Weighted overall (mirror src/show_rating.py formula).
        overall = _clamp(
            fan * 0.30 + commercial * 0.20
            + excitement * 0.25 + quality * 0.25
        )
        description = show_rating._describe_rating(overall)
        cur = conn.execute(
            "INSERT OR IGNORE INTO show_ratings "
            "(event_id, promotion_id, fan_rating, commercial_rating, "
            " excitement_rating, quality_rating, overall_rating, "
            " rating_description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, promo_id, fan, commercial, excitement,
             quality, overall, description),
        )
        if cur.rowcount > 0:
            n_created += 1
    print(f"  show_ratings rows created: {n_created}")
    return n_created


# ----------------------------------------------------------------
# Fix C5: seed finance_transactions.
# ----------------------------------------------------------------

def fix_c5_seed_finance(conn, rng, check_only=False):
    """Seed finance_transactions for each promotion.

    Per the brief:
      - opening balance transaction (D2: encoded as 'sponsorship'
        type since 'opening_balance' isn't in the CHECK constraint).
        Amount = promotion.starting_budget. Description = "Opening
        balance (initial capital injection from sponsors and
        investors)."
      - 5-10 historical transactions per promotion, dated in the
        past. Types: fighter_purse (negative), venue_rental
        (negative), staff_salary (negative), broadcast_revenue
        (positive), ticket_sales (positive). The mix represents a
        promotion's normal operating cash flow.
    """
    print("\n=== Fix C5: seed finance_transactions ===")

    existing = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions"
    ).fetchone()[0]
    print(f"  Existing finance_transactions rows: {existing}")

    if check_only:
        return 0

    today = _today(conn)
    promotions = conn.execute(
        "SELECT promotion_id, name, starting_budget, current_cash "
        "FROM promotions ORDER BY promotion_id"
    ).fetchall()
    print(f"  Promotions: {len(promotions)}")

    n_created = 0
    for (promo_id, name, starting_budget, current_cash) in promotions:
        # Check if this promotion already has a 'sponsorship' transaction
        # dated at sim start (the D2 opening-balance analog).
        has_opening = conn.execute(
            "SELECT 1 FROM finance_transactions "
            "WHERE promotion_id=? AND transaction_type='sponsorship' "
            "AND description LIKE 'Opening balance%' "
            "LIMIT 1",
            (promo_id,),
        ).fetchone()
        if not has_opening:
            # D2: encode the opening balance as 'sponsorship' type.
            opening_date = _sub_days(today, 365)  # 1 year ago
            conn.execute(
                "INSERT INTO finance_transactions "
                "(promotion_id, transaction_type, amount, description, "
                " transaction_date) "
                "VALUES (?, 'sponsorship', ?, ?, ?)",
                (promo_id, starting_budget,
                 "Opening balance (initial capital injection from "
                 "sponsors and investors).",
                 opening_date),
            )
            n_created += 1

        # 5-10 historical transactions per promotion.
        # Idempotency: skip if this promotion already has 5+ historical
        # (non-opening) transactions.
        existing_txn_count = conn.execute(
            "SELECT COUNT(*) FROM finance_transactions "
            "WHERE promotion_id=? "
            "AND NOT (transaction_type='sponsorship' "
            "         AND description LIKE 'Opening balance%')",
            (promo_id,),
        ).fetchone()[0]
        if existing_txn_count >= 5:
            continue

        n_txn = rng.randint(5, 10)
        for _ in range(n_txn):
            txn_type = rng.choice(FINANCE_TRANSACTION_TYPES)
            # Skip 'sponsorship' for the random historical ones
            # (we don't want to double-count the opening balance).
            if txn_type == "sponsorship":
                txn_type = "ticket_sales"
            # Date: random in the last 365 days.
            offset = rng.randint(1, 360)
            txn_date = _sub_days(today, offset)

            # Amount: varies by type. Positive for revenue
            # (ticket_sales, broadcast_revenue, merchandise,
            # bonus_payment-as-revenue — actually 'bonus_payment' is
            # a payout). Negative for expenses (fighter_purse,
            # venue_rental, staff_salary, medical_cost,
            # signing_bonus, weight_cut_penalty).
            revenue_types = {
                "ticket_sales", "broadcast_revenue", "merchandise"
            }
            # Bonus_payment is a payout (negative).
            # Sponsorship is revenue (positive) but we skip it above.
            if txn_type in revenue_types:
                # Revenue — scale to promotion's size. Small promos
                # have smaller revenues; large promos have bigger.
                # Use starting_budget / 100 as a scaling factor.
                scale = max(starting_budget / 100.0, 10000)
                amount = round(rng.uniform(0.2, 1.5) * scale, 2)
            else:
                # Expense — same scale.
                scale = max(starting_budget / 200.0, 5000)
                amount = -round(rng.uniform(0.3, 2.0) * scale, 2)

            # Description templates per type.
            descs = {
                "ticket_sales": f"Ticket sales revenue ({name} event)",
                "broadcast_revenue": f"Broadcast rights revenue ({name})",
                "merchandise": f"Merchandise sales ({name})",
                "fighter_purse": "Fighter purse payout",
                "venue_rental": "Venue rental fee",
                "staff_salary": "Staff salary payment",
                "medical_cost": "Medical expenses (event-night care)",
                "signing_bonus": "Fighter signing bonus",
                "weight_cut_penalty": "Weight-cut penalty payout",
                "bonus_payment": "Performance bonus payout",
            }
            desc = descs.get(txn_type, txn_type)

            conn.execute(
                "INSERT INTO finance_transactions "
                "(promotion_id, transaction_type, amount, description, "
                " transaction_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (promo_id, txn_type, amount, desc, txn_date),
            )
            n_created += 1

    print(f"  finance_transactions rows created: {n_created}")
    return n_created


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1.5 — Group C: seed missing data."
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report current counts, no writes.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("CAGE EMPIRE — Phase 1.5 Group C: Seed Missing Data")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Code schema version: {build_db.CODE_SCHEMA_VERSION}")
    print(f"Expected schema version: {EXPECTED_SCHEMA_VERSION}")

    if not DB_PATH.exists():
        print(f"FATAL: DB file does not exist at {DB_PATH}")
        sys.exit(2)

    # Sanity check: confirm the DB is at the expected schema version.
    # The migration (build_db.py --migrate) must be run BEFORE this
    # script. If the DB is at an older version, abort — staff.gym_id
    # won't exist and the C6 data back-fill will fail.
    conn = get_conn()
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    if not sv or sv[0] != EXPECTED_SCHEMA_VERSION:
        print(f"FATAL: DB schema version is {sv}, expected {EXPECTED_SCHEMA_VERSION}.")
        print("       Run `python3 src/build_db.py --migrate` first.")
        sys.exit(2)

    # Fighter-count guard (CONVENTIONS §16.8 world DB protection).
    fighter_count = conn.execute(
        "SELECT COUNT(*) FROM fighters"
    ).fetchone()[0]
    print(f"Fighters in DB: {fighter_count}")
    if fighter_count < 1000:
        print(f"WARNING: low fighter count ({fighter_count}). "
              f"This script targets the world DB (4000+ fighters).")

    rng = random.Random(20260726)  # deterministic seed for reproducibility

    print("\n--- Pre-fix counts ---")
    for table in ("training_camps", "suspensions", "fighter_memory_links",
                  "show_ratings", "finance_transactions"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n}")
    coaches_no_gym = conn.execute(
        "SELECT COUNT(*) FROM staff WHERE role_type='coach' "
        "AND gym_id IS NULL"
    ).fetchone()[0]
    print(f"  coaches without gym_id: {coaches_no_gym}")

    # Run all 6 fixes.
    fix_c6_assign_coaches_to_gyms(conn, rng, check_only=args.check)
    fix_c1_seed_training_camps(conn, rng, check_only=args.check)
    fix_c2_seed_suspensions(conn, rng, check_only=args.check)
    fix_c3_seed_memory_links(conn, rng, check_only=args.check)
    fix_c4_seed_show_ratings(conn, rng, check_only=args.check)
    fix_c5_seed_finance(conn, rng, check_only=args.check)

    if not args.check:
        conn.commit()
        print("\n--- Committed ---")

    print("\n--- Post-fix counts ---")
    for table in ("training_camps", "suspensions", "fighter_memory_links",
                  "show_ratings", "finance_transactions"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n}")
    coaches_no_gym = conn.execute(
        "SELECT COUNT(*) FROM staff WHERE role_type='coach' "
        "AND gym_id IS NULL"
    ).fetchone()[0]
    print(f"  coaches without gym_id: {coaches_no_gym}")
    coaches_with_gym = conn.execute(
        "SELECT COUNT(*) FROM staff WHERE role_type='coach' "
        "AND gym_id IS NOT NULL"
    ).fetchone()[0]
    print(f"  coaches with gym_id: {coaches_with_gym}")

    print("\n--- Active fighter check ---")
    active = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_active=1 AND is_retired=0"
    ).fetchone()[0]
    print(f"  Active fighters (preserved): {active}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
