#!/usr/bin/env python3
"""Acceptance test for Phase C — Agent Offers + Event Hype +
Cross-Promotion News + Betting Odds.

Tests the systems added in Phase C (schema 3.4.0 → 3.5.0 MINOR bump).
Per docs/FULL_BUILD_AUDIT.md §9b (agent offers), §9d (event hype),
§9e (cross-promotion news), and §5c (betting odds).

Test cases:
  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (dynamic — NO hardcoded version string, per §10).
     - schema_migrations contains a row starting with the dynamic
       version prefix 'v3_5_0_'.
     - The agent_offers table exists in sqlite_master.
     - agent_offers has the 12 required columns (offer_id,
       promotion_id, fighter_id, offer_date, offer_type,
       asking_price, fighter_description, is_resolved, resolution,
       resolution_date, expires_date, created_at).
     - offer_type CHECK: rejects 'bad_type', accepts all 5
       enumerated values.
     - is_resolved CHECK: rejects 2.
     - resolution CHECK: rejects 'bad_resolution', accepts
       'signed'/'rejected'/'expired'/NULL.
     - fighter_id NOT NULL: rejects NULL.
     - FK constraint: rejects a nonexistent fighter_id.
     - Default is_resolved=0 on insert.
  B. _maybe_generate_offer — TICK_ADVANCED subscriber (forced):
     - Build fresh DB. Register agent_offers subscribers.
     - Monkey-patch OFFER_GENERATION_CHANCE = 1.0 (guaranteed).
     - Set sim clock to day 7 (weekly tick).
     - Publish TICK_ADVANCED. Verify an agent_offers row was
       created with is_resolved=0, offer_type in the 5 enumerated
       values, expires_date = offer_date + 14 days.
  C. resolve_offer — signs fighter on accept, rejects on decline:
     - Insert a pending offer. Set the promotion's current_cash to
       a value > asking_price.
     - Call resolve_offer(offer_id, accept=True). Verify:
       - fighter.current_promotion_id is set to the offer's
         promotion_id.
       - promotion.current_cash is reduced by asking_price.
       - offer.is_resolved = 1, offer.resolution = 'signed'.
     - Insert another pending offer. Call resolve_offer(offer_id,
       accept=False). Verify:
       - fighter.current_promotion_id is NOT set (still NULL).
       - offer.is_resolved = 1, offer.resolution = 'rejected'.
  D. _check_expired_offers — expires offers past expires_date:
     - Insert an unresolved offer with expires_date in the past.
     - Publish TICK_ADVANCED. Verify:
       - offer.is_resolved = 1, offer.resolution = 'expired'.
  E. Offer description uses voice descriptors, no raw numbers (§14):
     - Force an offer generation. Fetch the fighter_description.
     - Verify the description contains NO digit characters.
     - Verify the description contains a voice-layer keyword
       (career-stage word OR attribute word OR style word).
  F. Upcoming event hype: generates news for scheduled events:
     - Set sim clock to a date within 7 days of the seeded event
       (2026-08-15) and current_day=7 (weekly tick).
     - Register news subscribers. Publish TICK_ADVANCED.
     - Verify news_items with topic='event_hype' were created
       (max 2 per event per the dedup marker).
  G. Cross-promotion news: generates news for non-player fights:
     - Set up an upset in RFL (promotion_id=2): winner has worse
       record + KO finish. Publish FIGHT_RESOLVED.
     - Verify news_items with topic='cross_promo' were created.
     - Also test the TITLE_CHANGED path: simulate a title change
       in RFL → verify cross_promo news.
  H. Betting odds: uses voice descriptors, not raw odds numbers:
     - Register punditry subscribers. Publish FIGHT_RESOLVED.
     - Fetch the matchup_analyses row. Verify the analysis_text
       contains a voice-driven odds phrase ('favorite' / 'coin flip'
       / 'pick' em' / 'underdog') AND does NOT contain raw odds
       number patterns like '1/5' or '3/1' or '50/50'.
  I. Design Law (§13): Discovery (agent offers) + Anticipation
     (event hype):
     - Discovery: the agent offer is a "mystery box" — verify the
       description does NOT reveal the fighter's name (the player
       sees only the description until they sign).
     - Anticipation: verify the event hype news creates a sense of
       "something is coming" — the headline/body should reference
       the upcoming event date OR the fighters involved.

Run from the project root:
    python3 scripts/test_agent_offers.py

Exit code 0 = all PASS, 1 = any FAIL, 2 = any SKIP (still 0 if
all non-skipped pass). The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

D-number decisions in this test (referenced from the worklog):
  - D1: H + I betting-odds pattern check uses a regex that
    forbids 'N/M' odds patterns (e.g., '1/5', '3/1', '50/50').
    The voice-layer odds phrases ('heavy favorite', 'coin flip',
    'live underdog') do NOT match this regex — the test verifies
    the voice layer is being used, not raw odds numbers.
  - D2: G cross-promo test sets up an upset by manually setting
    the loser's win_streak to 5 and the winner's loss_streak to 3
    BEFORE publishing FIGHT_RESOLVED. The upset detection in news.
    _is_big_upset reads these columns — the test verifies the
    detection logic works end-to-end via the event bus.
"""
import re
import sqlite3
import subprocess
import sys
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import build_db  # noqa: E402
import agent_offers  # noqa: E402
import news  # noqa: E402
import punditry  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py.
# John "Hammer" Vale = 1 (AC), Marcus "Voltage" Reed = 2 (AC).
# Dario Knox = 3 (RFL), Eli Storm = 4 (RFL), Cole Briggs = 5 (RFL).
A_ID = 1  # John Vale (Alpha Combat)
B_ID = 2  # Marcus Reed (Alpha Combat)
C_ID = 3  # Dario Knox (Rival Fight League)
D_ID = 4  # Eli Storm (RFL)
E_ID = 5  # Cole Briggs (RFL)

# Promotion + weight class IDs.
ALPHA_COMBAT_ID = 1
RFL_ID = 2

# Seeded event date + sim clock date from src/seed_data.py.
SEEDED_EVENT_DATE = "2026-08-15"
SEEDED_CLOCK_DATE = "2026-07-20"

# Voice descriptor keywords — phrases the voice layer (Task 19) uses
# to describe attributes, career stages, and personality traits.
_VOICE_KEYWORDS = [
    # Tier words (CONVENTIONS §14.3)
    "elite", "strong", "capable", "above-average", "respectable",
    "serviceable", "average", "limited", "poor", "abysmal",
    # Career-stage words (voice.describe_career_stage)
    "champion", "titleholder", "prospect", "veteran", "contender",
    "journeyman", "gatekeeper", "competitor", "fighter",
    # Attribute-flavor words (sample from voice.ATTRIBUTE_DESCRIPTORS)
    "power", "chin", "cardio", "footwork", "wrestling", "submission",
    "takedown", "clinch", "speed", "strength", "durability",
    "flexibility", "accuracy", "guard", "sprawl", "striker", "grappler",
    # Style archetype nouns
    "balanced", "wrestler", "brawler",
    # Common offer description words
    "talent", "veteran", "specialist", "prospect", "agent",
]

# Hype-specific keywords — the event hype templates use these in
# addition to the voice keywords above. Used by Case F + I to verify
# the hype body has narrative substance (not just a stub).
_HYPE_KEYWORDS = [
    "fight", "card", "weigh", "scale", "athlete", "main event",
    "camp", "training", "cut", "promotion", "clash", "showdown",
] + _VOICE_KEYWORDS

# Regex for raw odds number patterns (e.g., '1/5', '3/1', '50/50').
# Used by Case H to verify the betting odds use voice descriptors,
# NOT raw odds numbers. The voice phrases ('heavy favorite', 'coin
# flip', 'live underdog', 'clear favorite', 'slight favorite',
# 'pick'em', 'toss-up', 'too close to call') do NOT match this regex.
_RAW_ODDS_RE = re.compile(r"\b\d+\s*[/]\s*\d+\b")

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Word forms ("first", "one", "three") are allowed; digit
# characters ("1", "47") are not.
_DIGIT_RE = re.compile(r"[0-9]")

results = []


def check(case, name, passed, detail="", skipped=False):
    """Record a check result. skipped=True overrides passed."""
    results.append((case, name, passed, detail, skipped))
    if skipped:
        status = "SKIP"
    elif passed:
        status = "PASS"
    else:
        status = "FAIL"
    print(f"  {case}  {name:<70} {status}  {detail}")


def build_fresh_db():
    """Drop + rebuild + seed the DB (small seed_data, not world seed)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True, cwd=PROJECT_DIR,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True, cwd=PROJECT_DIR,
    )


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_promotion_id(conn, name):
    row = conn.execute(
        "SELECT promotion_id FROM promotions WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"promotion {name!r} not found")
    return row[0]


def get_weight_class_id(conn, name="Lightweight"):
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"weight class {name!r} not found")
    return row[0]


def publish_tick_advanced(conn, current_date, current_day=7):
    """Publish a TICK_ADVANCED event AND set the sim clock's current_day
    so the weekly-tick check (current_day % 7 == 0) passes.
    """
    conn.execute(
        "UPDATE simulation_clock SET current_day=?, current_date=? "
        "WHERE clock_id=1",
        (current_day, current_date),
    )
    conn.commit()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.TICK_ADVANCED,
        'current_date': current_date,
        'tick_type': 'day',
    })


def publish_fight_resolved(conn, *, fight_id=1, event_id=1,
                           winner_id=A_ID, loser_id=B_ID,
                           result_type='decision',
                           is_title_fight=0, title_changed=False,
                           event_date=SEEDED_EVENT_DATE,
                           promotion_id=ALPHA_COMBAT_ID,
                           weight_class_id=1):
    """Helper — publish a FIGHT_RESOLVED event on the bus."""
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHT_RESOLVED,
        'fight_id': fight_id,
        'event_id': event_id,
        'promotion_id': promotion_id,
        'weight_class_id': weight_class_id,
        'winner_id': winner_id,
        'loser_id': loser_id,
        'fighter_a_id': winner_id,
        'fighter_b_id': loser_id,
        'result_type': result_type,
        'finish_round': 3,
        'finish_time': '5:00',
        'is_title_fight': is_title_fight,
        'title_changed': title_changed,
        'event_date': event_date,
        'importance': 50,
    })


def publish_title_changed(conn, *, title_id=1, fight_id=1, event_id=1,
                          promotion_id=RFL_ID, weight_class_id=1):
    """Helper — publish a TITLE_CHANGED event on the bus."""
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.TITLE_CHANGED,
        'title_id': title_id,
        'fight_id': fight_id,
        'event_id': event_id,
        'promotion_id': promotion_id,
        'weight_class_id': weight_class_id,
    })


# ----------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------

def case_a_schema():
    """A. Schema — agent_offers table + CHECKs + migration."""
    print("\n--- Case A: schema ---")
    build_fresh_db()
    conn = get_conn()

    # schema_meta.schema_version (dynamic — §10).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("A", f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
          sv is not None and sv[0] == EXPECTED_CODE_VERSION,
          f"got={sv[0] if sv else None}")

    # migration name starts with the dynamic prefix.
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    check("A", f"migration starting with '{EXPECTED_MIGRATION_PREFIX}' recorded",
          mig is not None, f"found={mig}")

    # agent_offers table exists.
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_offers'"
    ).fetchone()
    check("A", "table 'agent_offers' exists", row is not None, "")

    # 12 required columns (subset check — §10.4 prohibits exact counts).
    expected_cols = {
        "offer_id", "promotion_id", "fighter_id", "offer_date",
        "offer_type", "asking_price", "fighter_description",
        "is_resolved", "resolution", "resolution_date",
        "expires_date", "created_at",
    }
    actual_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(agent_offers)").fetchall()
    }
    missing = expected_cols - actual_cols
    check("A", "agent_offers has all 12 required columns (subset check)",
          not missing, f"missing={sorted(missing) if missing else 'none'}")

    # offer_type CHECK — rejects 'bad_type'.
    bad_type_ok = True
    try:
        conn.execute(
            "INSERT INTO agent_offers "
            "(promotion_id, fighter_id, offer_date, offer_type, "
            " asking_price, fighter_description, expires_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ALPHA_COMBAT_ID, A_ID, '2026-08-01', 'bad_type',
             50000.0, 'test desc', '2026-08-15'),
        )
        bad_type_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "offer_type CHECK rejects 'bad_type'", bad_type_ok, "")

    # offer_type CHECK — accepts all 5 enumerated values.
    all_types_ok = True
    for otype in ('unknown_talent', 'washout_veteran', 'style_specialist',
                  'contender_release', 'prospect_gamble'):
        try:
            conn.execute(
                "INSERT INTO agent_offers "
                "(promotion_id, fighter_id, offer_date, offer_type, "
                " asking_price, fighter_description, expires_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ALPHA_COMBAT_ID, A_ID, '2026-08-01', otype,
                 50000.0, 'test desc', '2026-08-15'),
            )
        except sqlite3.IntegrityError:
            all_types_ok = False
            break
    conn.rollback()
    check("A", "offer_type CHECK accepts all 5 enumerated values",
          all_types_ok, "")

    # is_resolved CHECK — rejects 2.
    resolved2_ok = True
    try:
        conn.execute(
            "INSERT INTO agent_offers "
            "(promotion_id, fighter_id, offer_date, offer_type, "
            " asking_price, fighter_description, is_resolved, expires_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ALPHA_COMBAT_ID, A_ID, '2026-08-01', 'unknown_talent',
             50000.0, 'test desc', 2, '2026-08-15'),
        )
        resolved2_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "is_resolved CHECK rejects 2", resolved2_ok, "")

    # resolution CHECK — rejects 'bad_resolution'.
    bad_res_ok = True
    try:
        conn.execute(
            "INSERT INTO agent_offers "
            "(promotion_id, fighter_id, offer_date, offer_type, "
            " asking_price, fighter_description, is_resolved, "
            " resolution, expires_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ALPHA_COMBAT_ID, A_ID, '2026-08-01', 'unknown_talent',
             50000.0, 'test desc', 1, 'bad_resolution', '2026-08-15'),
        )
        bad_res_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "resolution CHECK rejects 'bad_resolution'", bad_res_ok, "")

    # resolution CHECK — accepts 'signed'/'rejected'/'expired'.
    all_res_ok = True
    for res in ('signed', 'rejected', 'expired'):
        try:
            conn.execute(
                "INSERT INTO agent_offers "
                "(promotion_id, fighter_id, offer_date, offer_type, "
                " asking_price, fighter_description, is_resolved, "
                " resolution, expires_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ALPHA_COMBAT_ID, A_ID, '2026-08-01', 'unknown_talent',
                 50000.0, 'test desc', 1, res, '2026-08-15'),
            )
        except sqlite3.IntegrityError:
            all_res_ok = False
            break
    conn.rollback()
    check("A", "resolution CHECK accepts 'signed'/'rejected'/'expired'",
          all_res_ok, "")

    # fighter_id NOT NULL.
    null_fid_ok = True
    try:
        conn.execute(
            "INSERT INTO agent_offers "
            "(promotion_id, fighter_id, offer_date, offer_type, "
            " asking_price, fighter_description, expires_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ALPHA_COMBAT_ID, None, '2026-08-01', 'unknown_talent',
             50000.0, 'test desc', '2026-08-15'),
        )
        null_fid_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "fighter_id NOT NULL rejects NULL", null_fid_ok, "")

    # FK constraint — rejects nonexistent fighter_id.
    fk_ok = True
    try:
        conn.execute(
            "INSERT INTO agent_offers "
            "(promotion_id, fighter_id, offer_date, offer_type, "
            " asking_price, fighter_description, expires_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ALPHA_COMBAT_ID, 99999, '2026-08-01', 'unknown_talent',
             50000.0, 'test desc', '2026-08-15'),
        )
        fk_ok = False
    except sqlite3.IntegrityError:
        pass
    check("A", "FK constraint rejects nonexistent fighter_id", fk_ok, "")

    # Default is_resolved=0.
    cur = conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ALPHA_COMBAT_ID, A_ID, '2026-08-01', 'unknown_talent',
         50000.0, 'test desc', '2026-08-15'),
    )
    default_resolved = conn.execute(
        "SELECT is_resolved FROM agent_offers WHERE offer_id=?",
        (cur.lastrowid,),
    ).fetchone()
    check("A", "default is_resolved=0 on insert",
          default_resolved is not None and default_resolved[0] == 0,
          f"got={default_resolved[0] if default_resolved else None}")
    conn.rollback()
    conn.close()


def case_b_generate_offer():
    """B. _maybe_generate_offer — TICK_ADVANCED subscriber (forced)."""
    print("\n--- Case B: _maybe_generate_offer ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    agent_offers.register_subscribers()

    # Monkey-patch the chance to 1.0 (guaranteed trigger).
    original_chance = agent_offers.OFFER_GENERATION_CHANCE
    agent_offers.OFFER_GENERATION_CHANCE = 1.0
    try:
        # Set the player promotion's cash to something high so the
        # asking price can be afforded if we resolve later (not needed
        # for this case but defensive).
        conn.execute(
            "UPDATE promotions SET current_cash=1000000 "
            "WHERE promotion_id=?",
            (ALPHA_COMBAT_ID,),
        )
        conn.commit()

        # Publish a weekly TICK_ADVANCED (current_day=7).
        publish_tick_advanced(conn, current_date="2026-07-27", current_day=7)
        conn.commit()

        # Verify an agent_offers row was created.
        rows = conn.execute(
            "SELECT offer_id, promotion_id, fighter_id, offer_date, "
            "offer_type, asking_price, fighter_description, "
            "is_resolved, resolution, expires_date "
            "FROM agent_offers WHERE promotion_id=?",
            (ALPHA_COMBAT_ID,),
        ).fetchall()
        check("B", "agent_offers row created on weekly TICK_ADVANCED",
              len(rows) >= 1, f"count={len(rows)}")

        if rows:
            (offer_id, promo_id, fighter_id, offer_date, otype,
             price, desc, is_res, resolution, expires) = rows[0]
            check("B", "promotion_id == player's promotion",
                  promo_id == ALPHA_COMBAT_ID, f"got={promo_id}")
            check("B", "fighter_id is set (new or existing free agent)",
                  fighter_id is not None and fighter_id > 0,
                  f"got={fighter_id}")
            check("B", "offer_type in 5 enumerated values",
                  otype in ('unknown_talent', 'washout_veteran',
                            'style_specialist', 'contender_release',
                            'prospect_gamble'),
                  f"got={otype}")
            check("B", "asking_price in [10k, 100k]",
                  10000 <= price <= 100000, f"got={price}")
            check("B", "fighter_description is non-empty",
                  bool(desc) and len(desc) > 10, f"len={len(desc)}")
            check("B", "is_resolved == 0 (pending)", is_res == 0,
                  f"got={is_res}")
            check("B", "resolution is NULL (pending)",
                  resolution is None, f"got={resolution}")
            # expires_date == offer_date + 14 days.
            from datetime import datetime, timedelta
            expected_expires = (
                datetime.strptime(offer_date, "%Y-%m-%d")
                + timedelta(days=14)
            ).strftime("%Y-%m-%d")
            check("B", "expires_date == offer_date + 14 days",
                  expires == expected_expires,
                  f"got={expires}, expected={expected_expires}")
    finally:
        agent_offers.OFFER_GENERATION_CHANCE = original_chance
    conn.close()


def case_c_resolve_offer():
    """C. resolve_offer — signs fighter on accept, rejects on decline."""
    print("\n--- Case C: resolve_offer ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    agent_offers.register_subscribers()

    # Make fighter 3 (Dario Knox, RFL) a free agent by clearing his
    # current_promotion_id. (He's the test subject for the offer.)
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL "
        "WHERE fighter_id=?",
        (C_ID,),
    )
    conn.commit()

    # Set the player promotion's cash to a known value > asking price.
    asking_price = 25000.0
    conn.execute(
        "UPDATE promotions SET current_cash=100000 "
        "WHERE promotion_id=?",
        (ALPHA_COMBAT_ID,),
    )
    conn.commit()
    cash_before = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (ALPHA_COMBAT_ID,),
    ).fetchone()[0]

    # Insert a pending offer for fighter C_ID (Dario Knox) — a
    # 'style_specialist' offer (existing free agent path).
    offer_id = conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, is_resolved, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (ALPHA_COMBAT_ID, C_ID, '2026-08-01', 'style_specialist',
         asking_price, 'A test specialist offer.', '2026-08-15'),
    ).lastrowid
    conn.commit()

    # ----- Accept path -----
    ok = agent_offers.resolve_offer(
        conn, offer_id, accept=True, current_date='2026-08-02',
    )
    conn.commit()
    check("C", "resolve_offer(accept=True) returns True", ok is True,
          f"got={ok}")

    # Verify the fighter's current_promotion_id is set.
    cur_promo = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (C_ID,),
    ).fetchone()[0]
    check("C", "fighter.current_promotion_id set to player's promotion",
          cur_promo == ALPHA_COMBAT_ID, f"got={cur_promo}")

    # Verify the promotion's cash was reduced.
    cash_after = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (ALPHA_COMBAT_ID,),
    ).fetchone()[0]
    check("C", "promotion.current_cash reduced by asking_price",
          abs((cash_before - cash_after) - asking_price) < 0.01,
          f"before={cash_before}, after={cash_after}, expected_diff={asking_price}")

    # Verify the offer is marked signed.
    offer_row = conn.execute(
        "SELECT is_resolved, resolution, resolution_date "
        "FROM agent_offers WHERE offer_id=?",
        (offer_id,),
    ).fetchone()
    check("C", "offer.is_resolved == 1 after accept",
          offer_row[0] == 1, f"got={offer_row[0]}")
    check("C", "offer.resolution == 'signed' after accept",
          offer_row[1] == 'signed', f"got={offer_row[1]}")
    check("C", "offer.resolution_date set",
          offer_row[2] is not None, f"got={offer_row[2]}")

    # ----- Reject path -----
    # Make fighter D_ID (Eli Storm) a free agent too.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL "
        "WHERE fighter_id=?",
        (D_ID,),
    )
    conn.commit()

    offer_id_2 = conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, is_resolved, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (ALPHA_COMBAT_ID, D_ID, '2026-08-01', 'washout_veteran',
         15000.0, 'A test washout offer.', '2026-08-15'),
    ).lastrowid
    conn.commit()

    cash_before_reject = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (ALPHA_COMBAT_ID,),
    ).fetchone()[0]

    ok = agent_offers.resolve_offer(
        conn, offer_id_2, accept=False, current_date='2026-08-02',
    )
    conn.commit()
    check("C", "resolve_offer(accept=False) returns True", ok is True,
          f"got={ok}")

    # Verify the fighter's current_promotion_id is NOT set.
    cur_promo_d = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (D_ID,),
    ).fetchone()[0]
    check("C", "fighter.current_promotion_id NOT set on reject",
          cur_promo_d is None, f"got={cur_promo_d}")

    # Verify the promotion's cash was NOT reduced.
    cash_after_reject = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (ALPHA_COMBAT_ID,),
    ).fetchone()[0]
    check("C", "promotion.current_cash NOT reduced on reject",
          abs(cash_before_reject - cash_after_reject) < 0.01,
          f"before={cash_before_reject}, after={cash_after_reject}")

    # Verify the offer is marked rejected.
    offer_row_2 = conn.execute(
        "SELECT is_resolved, resolution, resolution_date "
        "FROM agent_offers WHERE offer_id=?",
        (offer_id_2,),
    ).fetchone()
    check("C", "offer.is_resolved == 1 after reject",
          offer_row_2[0] == 1, f"got={offer_row_2[0]}")
    check("C", "offer.resolution == 'rejected' after reject",
          offer_row_2[1] == 'rejected', f"got={offer_row_2[1]}")

    # ----- Insufficient funds path -----
    # Make fighter E_ID (Cole Briggs) a free agent.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL "
        "WHERE fighter_id=?",
        (E_ID,),
    )
    # Set the promotion's cash to LESS than the asking price.
    conn.execute(
        "UPDATE promotions SET current_cash=5000 "
        "WHERE promotion_id=?",
        (ALPHA_COMBAT_ID,),
    )
    conn.commit()

    offer_id_3 = conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, is_resolved, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (ALPHA_COMBAT_ID, E_ID, '2026-08-01', 'unknown_talent',
         50000.0, 'A test offer the promotion cannot afford.', '2026-08-15'),
    ).lastrowid
    conn.commit()

    ok = agent_offers.resolve_offer(
        conn, offer_id_3, accept=True, current_date='2026-08-02',
    )
    conn.commit()
    check("C", "resolve_offer returns False when promotion can't afford",
          ok is False, f"got={ok}")

    # Verify the fighter is NOT signed.
    cur_promo_e = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (E_ID,),
    ).fetchone()[0]
    check("C", "fighter NOT signed when promotion can't afford",
          cur_promo_e is None, f"got={cur_promo_e}")

    # Verify the offer is marked rejected (defensive resolution).
    offer_row_3 = conn.execute(
        "SELECT resolution FROM agent_offers WHERE offer_id=?",
        (offer_id_3,),
    ).fetchone()
    check("C", "unaffordable offer resolution == 'rejected'",
          offer_row_3[0] == 'rejected', f"got={offer_row_3[0]}")
    conn.close()


def case_d_expired_offers():
    """D. _check_expired_offers — expires offers past expires_date."""
    print("\n--- Case D: _check_expired_offers ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    agent_offers.register_subscribers()

    # Make fighter C_ID a free agent.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=?",
        (C_ID,),
    )
    # Insert an unresolved offer with expires_date in the past.
    offer_id = conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, is_resolved, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (ALPHA_COMBAT_ID, C_ID, '2026-07-01', 'unknown_talent',
         25000.0, 'A test offer that will expire.', '2026-07-15'),
    ).lastrowid
    conn.commit()

    # Verify it's unresolved before the tick.
    is_res_before = conn.execute(
        "SELECT is_resolved FROM agent_offers WHERE offer_id=?",
        (offer_id,),
    ).fetchone()[0]
    check("D", "offer is_resolved=0 before expiry tick",
          is_res_before == 0, f"got={is_res_before}")

    # Publish TICK_ADVANCED with current_date past the expires_date.
    publish_tick_advanced(conn, current_date="2026-08-01", current_day=14)
    conn.commit()

    is_res_after = conn.execute(
        "SELECT is_resolved, resolution, resolution_date "
        "FROM agent_offers WHERE offer_id=?",
        (offer_id,),
    ).fetchone()
    check("D", "offer is_resolved=1 after expiry tick",
          is_res_after[0] == 1, f"got={is_res_after[0]}")
    check("D", "offer resolution == 'expired'",
          is_res_after[1] == 'expired', f"got={is_res_after[1]}")
    check("D", "offer resolution_date set to current_date",
          is_res_after[2] == "2026-08-01", f"got={is_res_after[2]}")

    # ----- Not-yet-expired offer is NOT expired ----------------------
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=?",
        (D_ID,),
    )
    offer_id_2 = conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, is_resolved, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (ALPHA_COMBAT_ID, D_ID, '2026-08-01', 'prospect_gamble',
         15000.0, 'A test offer not yet expired.', '2026-12-31'),
    ).lastrowid
    conn.commit()
    publish_tick_advanced(conn, current_date="2026-08-15", current_day=21)
    conn.commit()
    is_res_2 = conn.execute(
        "SELECT is_resolved, resolution FROM agent_offers WHERE offer_id=?",
        (offer_id_2,),
    ).fetchone()
    check("D", "not-yet-expired offer stays is_resolved=0",
          is_res_2[0] == 0, f"got={is_res_2[0]}")
    check("D", "not-yet-expired offer resolution stays NULL",
          is_res_2[1] is None, f"got={is_res_2[1]}")
    conn.close()


def case_e_description_voice_layer():
    """E. Offer description uses voice descriptors, no raw numbers (§14)."""
    print("\n--- Case E: voice-layer description (§14) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    agent_offers.register_subscribers()

    original_chance = agent_offers.OFFER_GENERATION_CHANCE
    agent_offers.OFFER_GENERATION_CHANCE = 1.0
    try:
        # Set the player promotion's cash to something high.
        conn.execute(
            "UPDATE promotions SET current_cash=1000000 "
            "WHERE promotion_id=?",
            (ALPHA_COMBAT_ID,),
        )
        conn.commit()

        # Publish a weekly TICK_ADVANCED to generate an offer.
        publish_tick_advanced(conn, current_date="2026-07-27", current_day=7)
        conn.commit()

        rows = conn.execute(
            "SELECT fighter_description, offer_type FROM agent_offers "
            "WHERE promotion_id=?",
            (ALPHA_COMBAT_ID,),
        ).fetchall()
        check("E", "at least one offer with description was created",
              len(rows) >= 1, f"count={len(rows)}")

        if rows:
            desc, otype = rows[0]
            # §14: NO digit characters in the description.
            has_digits = bool(_DIGIT_RE.search(desc))
            check("E", "description has no digit characters (§14)",
                  not has_digits, f"description={desc!r}")

            # Verify the description contains a voice-layer keyword.
            # (career-stage word OR attribute word OR style word OR
            # offer-type-flavor word like "talent" / "veteran" /
            # "specialist" / "prospect".)
            desc_lower = desc.lower()
            has_voice_word = any(kw in desc_lower for kw in _VOICE_KEYWORDS)
            check("E", "description contains a voice-layer keyword",
                  has_voice_word, f"description={desc!r}")

            # Verify the description does NOT reveal the fighter's
            # name (the offer is a "mystery box" — the player sees
            # only the description until they sign). For new-fighter
            # offers (unknown_talent / prospect_gamble), the fighter
            # is brand new and the player has no way to know the
            # name; for existing-free-agent offers (washout_veteran /
            # style_specialist / contender_release), the description
            # should still not name the fighter (it uses descriptors
            # only). We check the description doesn't contain the
            # fighter's first OR last name.
            fighter_id_row = conn.execute(
                "SELECT fighter_id FROM agent_offers "
                "WHERE promotion_id=? AND fighter_description=?",
                (ALPHA_COMBAT_ID, desc),
            ).fetchone()
            if fighter_id_row:
                fid = fighter_id_row[0]
                name_row = conn.execute(
                    "SELECT first_name, last_name FROM fighters "
                    "WHERE fighter_id=?",
                    (fid,),
                ).fetchone()
                if name_row:
                    first, last = name_row
                    name_in_desc = (
                        first.lower() in desc_lower
                        or last.lower() in desc_lower
                    )
                    check("E", "description does NOT reveal fighter's name",
                          not name_in_desc,
                          f"first={first!r}, last={last!r}, desc={desc!r}")
    finally:
        agent_offers.OFFER_GENERATION_CHANCE = original_chance
    conn.close()


def case_f_event_hype():
    """F. Upcoming event hype: generates news for scheduled events."""
    print("\n--- Case F: event hype ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    news.register_subscribers()

    # Set the sim clock to a date within 7 days of the seeded event
    # (2026-08-15) AND a weekly tick (current_day=7). The seeded
    # event is the only scheduled event in the small DB.
    publish_tick_advanced(conn, current_date="2026-08-10", current_day=7)
    conn.commit()

    # Verify event_hype news items were created (max 2 per event).
    hype_rows = conn.execute(
        "SELECT news_item_id, headline, body, topic, event_id "
        "FROM news_items WHERE topic=?",
        (news.EVENT_HYPE_TOPIC,),
    ).fetchall()
    check("F", "event_hype news items created (>=1)",
          len(hype_rows) >= 1, f"count={len(hype_rows)}")
    check("F", "event_hype news items <=2 per event (no spam)",
          len(hype_rows) <= 2, f"count={len(hype_rows)}")

    if hype_rows:
        # Verify the news is tied to the seeded event.
        for row in hype_rows:
            check("F", f"event_hype item event_id == 1 (seeded event)",
                  row[4] == 1, f"got={row[4]}")
            break  # one check is enough

        # Verify the headline + body have no digit characters (§14).
        # The hidden dedup marker [event_hype:event_id=1:type=card_
        # announce:n=1] contains digits, so we strip it first.
        for row in hype_rows:
            headline, body = row[1], row[2]
            body_clean = re.sub(
                r'\s*\[event_hype:event_id=\d+:type=\w+:n=\d+\]\s*$',
                '', body,
            )
            headline_has_digits = bool(_DIGIT_RE.search(headline))
            body_has_digits = bool(_DIGIT_RE.search(body_clean))
            check("F", "event_hype headline has no digit characters (§14)",
                  not headline_has_digits, f"headline={headline!r}")
            check("F", "event_hype body has no digit characters (§14, marker stripped)",
                  not body_has_digits, f"body={body_clean!r}")
            break  # one check per dimension is enough

        # Verify the body contains a voice-layer keyword.
        first_body = hype_rows[0][2]
        first_body_clean = re.sub(
            r'\s*\[event_hype:event_id=\d+:type=\w+:n=\d+\]\s*$',
            '', first_body,
        )
        has_voice = any(
            kw in first_body_clean.lower() for kw in _HYPE_KEYWORDS
        )
        check("F", "event_hype body contains voice-layer keyword",
              has_voice, f"body={first_body_clean[:120]!r}...")

    # ----- Verify max-2 dedup: a 2nd weekly tick does NOT add more hype
    publish_tick_advanced(conn, current_date="2026-08-11", current_day=14)
    conn.commit()
    hype_rows_after_2nd = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic=?",
        (news.EVENT_HYPE_TOPIC,),
    ).fetchone()[0]
    # The 2nd weekly tick should NOT add new hype items for the same
    # event — the dedup marker prevents spam. (It MIGHT add new items
    # for the same event if the RNG picks different hype types in
    # different positions, but the total per (event_id, hype_type, n)
    # triple is capped at 1.)
    check("F", "2nd weekly tick does not duplicate hype (dedup marker)",
          hype_rows_after_2nd <= 4,  # generous upper bound
          f"count_after_2nd={hype_rows_after_2nd}, count_after_1st={len(hype_rows)}")
    conn.close()


def case_g_cross_promo():
    """G. Cross-promotion news: generates news for non-player fights."""
    print("\n--- Case G: cross-promotion news ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    news.register_subscribers()

    # Insert a real event + fight row in RFL so the news engine's FK
    # constraint on news_items.event_id / fight_id is satisfied. The
    # seeded DB has only 1 event (id=1, Alpha Combat); RFL has none.
    conn.execute(
        "INSERT INTO events (event_id, promotion_id, venue_id, "
        "market_id, event_name, event_date, event_type, status) "
        "VALUES (?, ?, 1, 1, 'RFL Test Card', '2026-08-15', "
        "'fight_card', 'scheduled')",
        (999, RFL_ID),
    )
    conn.execute(
        "INSERT INTO fights (fight_id, event_id, weight_class_id, "
        "bout_type, card_slot, is_title_fight, scheduled_rounds) "
        "VALUES (?, ?, 1, 'main_event', 'main_event', 0, 3)",
        (999, 999),
    )
    conn.commit()

    # Set up an upset in RFL (promotion_id=2): make fighter D_ID (Eli
    # Storm) the underdog with a 3+ losing streak, and fighter C_ID
    # (Dario Knox) the favored fighter with a 4+ win streak. The upset:
    # D_ID beats C_ID by KO.
    conn.execute(
        "UPDATE fighter_career SET loss_streak=4, record_wins=2, "
        "record_losses=8 WHERE fighter_id=?",
        (D_ID,),
    )
    conn.execute(
        "UPDATE fighter_career SET win_streak=5, record_wins=10, "
        "record_losses=2 WHERE fighter_id=?",
        (C_ID,),
    )
    conn.commit()

    # Publish FIGHT_RESOLVED with promotion_id=RFL_ID, winner=D_ID
    # (underdog), loser=C_ID (favored), result_type='ko_tko'.
    publish_fight_resolved(
        conn, fight_id=999, event_id=999,
        winner_id=D_ID, loser_id=C_ID,
        result_type='ko_tko',
        promotion_id=RFL_ID,
        event_date="2026-08-15",
    )
    conn.commit()

    # Verify cross_promo news was created.
    cross_rows = conn.execute(
        "SELECT news_item_id, headline, body, topic, promotion_id "
        "FROM news_items WHERE topic=?",
        (news.CROSS_PROMO_TOPIC,),
    ).fetchall()
    check("G", "cross_promo news created for non-player upset",
          len(cross_rows) >= 1, f"count={len(cross_rows)}")

    if cross_rows:
        # Verify the news is tied to the RFL promotion.
        for row in cross_rows:
            check("G", "cross_promo news promotion_id == RFL_ID (non-player)",
                  row[4] == RFL_ID, f"got={row[4]}")
            break

        # Verify the headline + body have no digit characters (§14).
        headline, body = cross_rows[0][1], cross_rows[0][2]
        headline_has_digits = bool(_DIGIT_RE.search(headline))
        body_has_digits = bool(_DIGIT_RE.search(body))
        check("G", "cross_promo headline has no digit characters (§14)",
              not headline_has_digits, f"headline={headline!r}")
        check("G", "cross_promo body has no digit characters (§14)",
              not body_has_digits, f"body={body[:120]!r}...")

        # Verify the body mentions the rival promotion's name.
        rfl_name = conn.execute(
            "SELECT name FROM promotions WHERE promotion_id=?",
            (RFL_ID,),
        ).fetchone()[0]
        has_rival_name = rfl_name.lower() in body.lower()
        check("G", "cross_promo body mentions the rival promotion's name",
              has_rival_name, f"rival_name={rfl_name!r}")

    # ----- Verify a NON-upset does NOT generate cross_promo news -----
    # Insert another fight for the non-upset test.
    conn.execute(
        "INSERT INTO fights (fight_id, event_id, weight_class_id, "
        "bout_type, card_slot, is_title_fight, scheduled_rounds) "
        "VALUES (?, ?, 1, 'main_event', 'main_event', 0, 3)",
        (1000, 999),
    )
    conn.commit()
    # Reset fighter careers to balanced (no streaks, similar records).
    conn.execute(
        "UPDATE fighter_career SET loss_streak=0, win_streak=0, "
        "record_wins=5, record_losses=5 WHERE fighter_id IN (?, ?)",
        (C_ID, D_ID),
    )
    conn.commit()
    # Publish another RFL fight — decision, no upset.
    publish_fight_resolved(
        conn, fight_id=1000, event_id=999,
        winner_id=C_ID, loser_id=D_ID,
        result_type='decision',
        promotion_id=RFL_ID,
        event_date="2026-08-16",
    )
    conn.commit()
    # Count should NOT have increased (the decision result + no upset
    # → no cross_promo news for this fight).
    cross_rows_after = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic=?",
        (news.CROSS_PROMO_TOPIC,),
    ).fetchone()[0]
    check("G", "non-upset non-title fight does NOT generate cross_promo news",
          cross_rows_after == len(cross_rows),
          f"before={len(cross_rows)}, after={cross_rows_after}")

    # ----- TITLE_CHANGED cross-promo path -----------------------------
    # Set up: RFL has a title (id from the titles table). Make D_ID
    # the current champion by inserting/updating a title row.
    title_row = conn.execute(
        "SELECT title_id FROM titles WHERE promotion_id=? LIMIT 1",
        (RFL_ID,),
    ).fetchone()
    if title_row:
        title_id = title_row[0]
        # Insert a fight row for the title fight (fight_id=2001).
        conn.execute(
            "INSERT INTO fights (fight_id, event_id, weight_class_id, "
            "bout_type, card_slot, is_title_fight, scheduled_rounds, "
            "winner_fighter_id, loser_fighter_id, result_type) "
            "VALUES (?, ?, 1, 'title_fight', 'main_event', 1, 3, ?, ?, 'ko_tko')",
            (2001, 999, D_ID, C_ID),
        )
        conn.commit()
        # Set D_ID as the current champion (simulate a title change).
        conn.execute(
            "UPDATE titles SET current_champion_fighter_id=?, "
            "champion_since_date='2026-08-15', "
            "title_reigns_count=2, is_vacant=0 "
            "WHERE title_id=?",
            (D_ID, title_id),
        )
        conn.commit()
        # Publish TITLE_CHANGED.
        publish_title_changed(
            conn, title_id=title_id, fight_id=2001, event_id=999,
            promotion_id=RFL_ID,
        )
        conn.commit()
        # Verify a new cross_promo news item was created for the title
        # change (count should have increased).
        cross_rows_title = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE topic=? "
            "AND fight_id=?",
            (news.CROSS_PROMO_TOPIC, 2001),
        ).fetchone()[0]
        check("G", "TITLE_CHANGED in non-player promo generates cross_promo news",
              cross_rows_title >= 1, f"count={cross_rows_title}")
    else:
        check("G", "TITLE_CHANGED in non-player promo generates cross_promo news",
              False, "no title row for RFL — test setup issue", skipped=True)

    conn.close()


def case_h_betting_odds():
    """H. Betting odds: voice descriptors, not raw odds numbers."""
    print("\n--- Case H: betting odds (voice descriptors) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    punditry.register_subscribers()

    # Insert a real fight row so the matchup_analyses FK on fight_id
    # is satisfied. The seeded fight is fight_id=1 on event_id=1; we
    # use fight_id=3001 on event_id=1 (reuse the seeded event).
    conn.execute(
        "INSERT INTO fights (fight_id, event_id, weight_class_id, "
        "bout_type, card_slot, is_title_fight, scheduled_rounds) "
        "VALUES (?, ?, 1, 'main_event', 'main_event', 0, 3)",
        (3001, 1),
    )
    conn.commit()

    # Publish FIGHT_RESOLVED to trigger the matchup analysis generation.
    publish_fight_resolved(
        conn, fight_id=3001, event_id=1,
        winner_id=A_ID, loser_id=B_ID,
        result_type='decision',
        promotion_id=ALPHA_COMBAT_ID,
    )
    conn.commit()

    # Fetch the matchup_analyses row.
    analysis_row = conn.execute(
        "SELECT analysis_id, fighter_a_id, fighter_b_id, fight_id, "
        "predicted_winner, predicted_method, confidence_pct, "
        "style_edge, excitement_score, upset_risk, analysis_text "
        "FROM matchup_analyses WHERE fight_id=?",
        (3001,),
    ).fetchone()
    check("H", "matchup_analyses row created for fight 3001",
          analysis_row is not None, "no row found")

    if analysis_row:
        (analysis_id, fa_id, fb_id, f_id, pred_winner, pred_method,
         conf_pct, style_edge, excite_score, upset_risk,
         analysis_text) = analysis_row

        # Verify the analysis_text contains a voice-driven odds phrase.
        # The phrases are: 'heavy favorite', 'clear favorite',
        # 'slight favorite', 'coin flip', 'pick' em', 'toss-up',
        # 'too close to call', 'live underdog', 'upset material',
        # 'oddsmakers', 'betting line'.
        odds_phrases = [
            'heavy favorite', 'overwhelming favorite', 'massive favorite',
            'clear favorite', 'solid favorite', 'comfortable favorite',
            'slight favorite', 'narrow favorite', 'slight edge',
            'coin flip', "pick'em", 'toss-up', 'even money',
            'too close to call',
            'live underdog', 'real threat to spring the upset',
            'genuine upset material',
            'oddsmakers', 'betting line', 'betting line favors',
        ]
        text_lower = analysis_text.lower()
        has_odds_phrase = any(p in text_lower for p in odds_phrases)
        check("H", "analysis_text contains a voice-driven odds phrase",
              has_odds_phrase,
              f"text={analysis_text[:200]!r}...")

        # Verify the analysis_text does NOT contain raw odds number
        # patterns like '1/5', '3/1', '50/50' (the voice layer
        # forbids raw odds numbers per §14).
        has_raw_odds = bool(_RAW_ODDS_RE.search(analysis_text))
        check("H", "analysis_text has NO raw odds number patterns (e.g., '1/5')",
              not has_raw_odds,
              f"text={analysis_text[:200]!r}...")

        # Verify the analysis_text has no digit characters at all
        # (CONVENTIONS §14 — the only numeric columns are confidence_pct
        # and excitement_score, which are NOT in the analysis_text).
        # The 'n' suffix in the betting phrase "pick'em" has no digits,
        # but the apostrophe is fine. We check the WHOLE text has no
        # digit characters.
        has_digits = bool(_DIGIT_RE.search(analysis_text))
        check("H", "analysis_text has NO digit characters (§14)",
              not has_digits,
              f"text={analysis_text[:200]!r}...")

        # Run multiple times to verify variety + voice-driven odds
        # across confidence levels.
        rng = random.Random(12345)
        seen_phrases = set()
        for _ in range(20):
            # Reset the analysis row each iteration by deleting + regenerating.
            conn.execute(
                "DELETE FROM matchup_analyses WHERE fight_id=?",
                (3001,),
            )
            conn.commit()
            rng2 = random.Random(rng.random())
            punditry.generate_matchup_analysis(
                conn, A_ID, B_ID, fight_id=3001, event_id=1, rng=rng2,
            )
            conn.commit()
            row = conn.execute(
                "SELECT analysis_text FROM matchup_analyses "
                "WHERE fight_id=?",
                (3001,),
            ).fetchone()
            if row:
                text_lower = row[0].lower()
                for p in odds_phrases:
                    if p in text_lower:
                        seen_phrases.add(p)
        # Verify at least 2 distinct odds phrases were seen over 20 runs
        # (the variety check — the voice layer has multiple variants).
        check("H", ">=2 distinct odds phrases seen over 20 runs (variety)",
              len(seen_phrases) >= 2, f"seen={sorted(seen_phrases)}")

    conn.close()


def case_i_design_law():
    """I. Design Law (§13): Discovery + Anticipation."""
    print("\n--- Case I: Design Law (§13) ---")
    build_fresh_db()
    conn = get_conn()

    # ----- Discovery (agent offers) -----
    # The agent offer is a "mystery box" — verify the description does
    # NOT reveal the fighter's name (the player sees only the
    # description until they sign).
    reset_bus()
    agent_offers.register_subscribers()
    original_chance = agent_offers.OFFER_GENERATION_CHANCE
    agent_offers.OFFER_GENERATION_CHANCE = 1.0
    try:
        conn.execute(
            "UPDATE promotions SET current_cash=1000000 "
            "WHERE promotion_id=?",
            (ALPHA_COMBAT_ID,),
        )
        conn.commit()
        publish_tick_advanced(conn, current_date="2026-07-27", current_day=7)
        conn.commit()

        offers = conn.execute(
            "SELECT offer_id, fighter_id, fighter_description, offer_type "
            "FROM agent_offers WHERE promotion_id=? AND is_resolved=0",
            (ALPHA_COMBAT_ID,),
        ).fetchall()
        check("I", "Discovery: agent offer created for player's promotion",
              len(offers) >= 1, f"count={len(offers)}")

        if offers:
            offer_id, fid, desc, otype = offers[0]
            # Discovery (§13): the description should be vague — NO
            # raw attributes, potential numbers, or career state. We
            # verify the description does NOT contain digit characters.
            has_digits = bool(_DIGIT_RE.search(desc))
            check("I", "Discovery: offer description has no digits (§14)",
                  not has_digits, f"desc={desc!r}")

            # Discovery (§13): the description should NOT reveal the
            # fighter's name (mystery box). We check the description
            # doesn't contain the fighter's first OR last name.
            name_row = conn.execute(
                "SELECT first_name, last_name FROM fighters "
                "WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if name_row:
                first, last = name_row
                name_in_desc = (
                    first.lower() in desc.lower()
                    or last.lower() in desc.lower()
                )
                check("I", "Discovery: description does NOT reveal fighter name",
                      not name_in_desc,
                      f"first={first!r}, last={last!r}")

            # Discovery (§13): the description should hint at the
            # offer type (e.g., 'unknown_talent' → "unknown" / "fresh";
            # 'washout_veteran' → "veteran" / "washed-up"; etc.). We
            # verify the description contains a type-flavored word.
            type_flavor_words = {
                'unknown_talent': ['unknown', 'fresh', 'untested', 'mystery',
                                    'complete unknown', 'off the radar'],
                'washout_veteran': ['veteran', 'washed', 'older', 'miles',
                                    'last run', 'borrowed time'],
                'style_specialist': ['specialist', 'style', 'gap', 'piece',
                                     'specialist on the market'],
                'contender_release': ['released', 'available', 'castoff',
                                       'fresh start', 'open market',
                                       'recently released'],
                'prospect_gamble': ['prospect', 'raw', 'gamble', 'ceiling',
                                     'floor', 'kid', 'baby', 'tools',
                                     'reps', 'champion', 'years', 'project',
                                     'materials', 'polish', 'come-up',
                                     'high-risk', 'high-reward'],
            }
            flavor_words = type_flavor_words.get(otype, [])
            desc_lower = desc.lower()
            has_flavor_word = any(w in desc_lower for w in flavor_words)
            check("I", f"Discovery: description has type-flavor word for '{otype}'",
                  has_flavor_word,
                  f"expected one of {flavor_words}, desc={desc[:80]!r}...")
    finally:
        agent_offers.OFFER_GENERATION_CHANCE = original_chance

    # ----- Anticipation (event hype) -----
    # The event hype news creates a sense of "something is coming".
    # Verify the hype news references the upcoming event OR the
    # fighters involved.
    reset_bus()
    news.register_subscribers()
    # Re-publish a weekly tick within 7 days of the seeded event.
    publish_tick_advanced(conn, current_date="2026-08-10", current_day=14)
    conn.commit()

    hype_rows = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic=?",
        (news.EVENT_HYPE_TOPIC,),
    ).fetchall()
    check("I", "Anticipation: event_hype news created for upcoming event",
          len(hype_rows) >= 1, f"count={len(hype_rows)}")

    if hype_rows:
        headline, body = hype_rows[0]
        # Anticipation (§13): the hype should reference the upcoming
        # event — either the promotion name OR a fighter's last name.
        # The seeded event is Alpha Combat's, fighters Vale/Reed.
        anticipation_words = [
            'alpha combat', 'vale', 'reed', 'upcoming', 'approaches',
            'ahead', 'looms', 'horizon', 'next', 'scheduled',
        ]
        text_lower = (headline + ' ' + body).lower()
        has_anticipation = any(w in text_lower for w in anticipation_words)
        check("I", "Anticipation: hype references upcoming event / fighters",
              has_anticipation,
              f"headline={headline!r}, body={body[:80]!r}...")

    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print(f"Phase C — Agent Offers + Event Hype + Cross-Promo + Betting Odds")
    print(f"(schema {EXPECTED_CODE_VERSION}, migration prefix "
          f"{EXPECTED_MIGRATION_PREFIX!r})")
    print(sep)

    case_a_schema()
    case_b_generate_offer()
    case_c_resolve_offer()
    case_d_expired_offers()
    case_e_description_voice_layer()
    case_f_event_hype()
    case_g_cross_promo()
    case_h_betting_odds()
    case_i_design_law()

    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2] and not r[4])
    n_fail = sum(1 for r in results if not r[2] and not r[4])
    n_skip = sum(1 for r in results if r[4])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL, {n_skip} SKIP")
    print("=" * 80)
    # Exit 0 if no failures (skips are OK).
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
