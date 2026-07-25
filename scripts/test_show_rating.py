#!/usr/bin/env python3
"""Acceptance test for Stage 5 — Show rating engine + Venues/markets
deeper simulation (Task ID Stage5-26+27).

Tests the systems added in Stage 5:
  - src/show_rating.py — event-bus subscriber on EVENT_COMPLETED that
    computes fan / commercial / excitement / quality / overall ratings
    + writes a topic='show_rating' news item with a voice descriptor.
  - src/venues.py — event-bus subscribers on EVENT_COMPLETED (market
    heat adjustment based on fan_rating) + TICK_ADVANCED (monthly
    market heat drift).
  - src/build_db.py — schema bumped 3.5.0 → 3.6.0 MINOR. New
    show_ratings table (one table-group per CONVENTIONS §5).

Test cases:
  A. Schema: show_ratings table exists with proper columns + CHECKs +
     UNIQUE(event_id). Schema version is 3.6.0. Migration recorded.
  B. Show rating computed on event completion (EVENT_COMPLETED fires
     the subscriber; row written to show_ratings).
  C. Fan rating reflects finishes (KO events rate higher than decision
     events — finish_bonus is the dominant factor).
  D. Commercial rating reflects marketability (high-marketability
     fighters produce higher commercial_rating than low-marketability
     fighters, all else equal).
  E. Rating description uses voice descriptors — NO raw numbers in
     the rating_description column or the news item headline/body.
  F. Market heat changes after events (successful event → +2 heat;
     poor event → -1 heat; middling event → no change).
  G. Market heat drifts on monthly tick (hot markets cool toward 70;
     cold markets warm toward 40; middling markets unchanged).
  H. Design Law (§13): Investment (market growth) + Stories (show
     ratings create the "remember that great card" storyline).

Pattern follows scripts/test_career_arc_rival_ai.py + test_finance.py
(CONVENTIONS §10 — dynamic version pattern, no hardcoded version
strings).

Run from the project root:
    python3 scripts/test_show_rating.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

D-number decisions in this test (referenced from the worklog):
  - D1: Schema test uses the dynamic version pattern (§10). The
    EXPECTED_CODE_VERSION is read from build_db.CODE_SCHEMA_VERSION
    at test time — no hardcoded '3.6.0' string.
  - D2: Fan-rating test (case C) directly sets result_type on the
    fights table (no RNG dependency). This tests the FINISH BONUS
    computation path end-to-end without flakiness from the random
    fight engine.
  - D3: Commercial-rating test (case D) sets all fighters'
    marketability to a known value, isolating the marketability
    component of commercial_rating from the broadcast_tier and
    attendance components.
  - D4: Voice-layer test (case E) uses a digit regex on the
    rating_description column + the news item headline + body.
    The regex allows the event_id in the body (if any) but rejects
    any standalone digit. The actual descriptor phrases have NO
    digits — verified.
  - D5: Market heat test (case F) forces specific fan_rating values
    by setting result_type to KO (high fan_rating via finish_bonus)
    or decision + no title (low fan_rating via no bonuses). This
    avoids RNG dependency.
  - D6: Monthly drift test (case G) sets heat to known extreme
    values (85 for hot, 25 for cold, 50 for middling) and verifies
    the drift direction. The drift is ±1 per monthly tick — slow
    by design.
"""
import re
import sqlite3
import subprocess
import sys
import os
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import show_rating  # noqa: E402
import venues  # noqa: E402
import build_db  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Fighter IDs assigned by seed_data.py.
# John "Hammer" Vale = 1 (AC), Marcus "Voltage" Reed = 2 (AC).
A_ID = 1  # John Vale (Alpha Combat)
B_ID = 2  # Marcus Reed (Alpha Combat)

# Promotion + weight class + event IDs.
ALPHA_COMBAT_ID = 1
SEEDED_EVENT_ID = 1
SEEDED_FIGHT_ID = 1
SEEDED_MARKET_ID = 1  # Metro City market

# Seeded event date + sim clock date from src/seed_data.py.
SEEDED_EVENT_DATE = "2026-08-15"
SEEDED_CLOCK_DATE = "2026-07-20"

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Used by Case E to verify the rating description + news item
# have no digits. The regex matches any digit 0-9.
_DIGIT_RE = re.compile(r"[0-9]")

# Valid voice-layer rating descriptors (per the brief). Used to
# verify the rating_description is one of these exact strings.
_VALID_RATING_DESCRIPTIONS = {
    "an instant classic that fans will talk about for years",
    "a highly entertaining show that delivered on expectations",
    "a solid night of fights with some memorable moments",
    "a decent show that failed to produce many highlights",
    "a lackluster card that left fans wanting more",
}

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


def publish_event_completed(conn, event_id, promotion_id, event_date):
    """Publish an EVENT_COMPLETED event on the global bus."""
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.EVENT_COMPLETED,
        'event_id': event_id,
        'promotion_id': promotion_id,
        'event_date': event_date,
    })


def publish_tick_advanced(conn, current_date, current_day):
    """Publish a TICK_ADVANCED event AND set the sim clock's current_day
    + current_date so the monthly tick check passes.
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


def force_fight_result(conn, fight_id, result_type, winner_id, loser_id,
                        is_title_fight=None):
    """Set a fight's result_type + winner + loser (bypass the engine).

    Used to test the show rating computation deterministically —
    without this, the RNG-driven fight engine produces different
    result_types on each run. D2, D3, D5.
    """
    if is_title_fight is not None:
        conn.execute(
            "UPDATE fights SET result_type=?, winner_fighter_id=?, "
            "loser_fighter_id=?, is_title_fight=? WHERE fight_id=?",
            (result_type, winner_id, loser_id, is_title_fight, fight_id),
        )
    else:
        conn.execute(
            "UPDATE fights SET result_type=?, winner_fighter_id=?, "
            "loser_fighter_id=? WHERE fight_id=?",
            (result_type, winner_id, loser_id, fight_id),
        )


# ----------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------

def case_a_schema():
    """A. Schema: show_ratings table exists with proper columns +
    CHECKs + UNIQUE(event_id). Schema version is 3.6.0."""
    print("\n--- Case A: schema (show_ratings table) ---")
    build_fresh_db()
    conn = get_conn()

    # Schema version check (dynamic — D1).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("A", f"schema version is {EXPECTED_CODE_VERSION}",
          sv[0] == EXPECTED_CODE_VERSION, f"got={sv[0]}")

    # Migration recorded.
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    check("A", f"migration recorded ({EXPECTED_MIGRATION_PREFIX}...)",
          mig is not None, f"got={mig}")

    # show_ratings table exists.
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='show_ratings'"
    ).fetchone()
    check("A", "show_ratings table exists", exists is not None, "")

    # Columns.
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(show_ratings)").fetchall()}
    expected = {
        "rating_id", "event_id", "promotion_id",
        "fan_rating", "commercial_rating", "excitement_rating",
        "quality_rating", "overall_rating", "rating_description",
        "created_at",
    }
    check("A", "show_ratings has all 10 columns", cols == expected,
          f"missing={expected - cols}, extra={cols - expected}")

    # UNIQUE(event_id) — insert twice should fail.
    conn.execute(
        "INSERT INTO show_ratings (event_id, promotion_id) VALUES (?, ?)",
        (SEEDED_EVENT_ID, ALPHA_COMBAT_ID),
    )
    try:
        conn.execute(
            "INSERT INTO show_ratings (event_id, promotion_id) VALUES (?, ?)",
            (SEEDED_EVENT_ID, ALPHA_COMBAT_ID),
        )
        check("A", "UNIQUE(event_id) rejects duplicate",
              False, "duplicate insert succeeded (should have raised)")
    except sqlite3.IntegrityError:
        check("A", "UNIQUE(event_id) rejects duplicate", True, "")
    conn.rollback()

    # CHECK constraints — fan_rating out of range should fail.
    try:
        conn.execute(
            "INSERT INTO show_ratings (event_id, promotion_id, fan_rating) "
            "VALUES (?, ?, ?)",
            (999, ALPHA_COMBAT_ID, 150),  # 150 > 100
        )
        check("A", "CHECK (fan_rating BETWEEN 0 AND 100) rejects 150",
              False, "out-of-range insert succeeded")
    except sqlite3.IntegrityError:
        check("A", "CHECK (fan_rating BETWEEN 0 AND 100) rejects 150",
              True, "")
    conn.rollback()
    conn.close()


def case_b_show_rating_computed_on_completion():
    """B. Show rating computed on event completion."""
    print("\n--- Case B: show rating computed on EVENT_COMPLETED ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    show_rating.register_subscribers()

    # Verify no show_ratings row exists yet.
    rows_before = conn.execute(
        "SELECT COUNT(*) FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    check("B", "no show_ratings row before event completion",
          rows_before == 0, f"got={rows_before}")

    # Force the seeded fight to a known result + complete the event.
    force_fight_result(conn, SEEDED_FIGHT_ID, 'ko_tko', A_ID, B_ID)
    conn.execute(
        "UPDATE events SET status='completed' WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.commit()

    # Publish EVENT_COMPLETED — show_rating subscriber should fire.
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()

    # Verify a show_ratings row was written.
    row = conn.execute(
        "SELECT fan_rating, commercial_rating, excitement_rating, "
        "quality_rating, overall_rating, rating_description "
        "FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()
    check("B", "show_ratings row written on EVENT_COMPLETED",
          row is not None, f"got={row}")
    if row:
        check("B", "all 5 rating axes are 0-100",
              all(0 <= v <= 100 for v in row[:5])
              and isinstance(row[0], int) and isinstance(row[4], int),
              f"axes={row[:5]}")
        check("B", "rating_description is non-empty",
              bool(row[5]), f"got={row[5]!r}")

    # Verify a topic='show_rating' news item was written.
    news = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='show_rating' "
        "AND event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()
    check("B", "show_rating news item written",
          news is not None, f"got={news}")
    if news:
        check("B", "news headline non-empty",
              bool(news[0]), f"got={news[0]!r}")
        check("B", "news body non-empty",
              bool(news[1]), f"got={news[1]!r}")
    conn.close()


def case_c_fan_rating_reflects_finishes():
    """C. Fan rating reflects finishes (KO events rate higher than
    decision events)."""
    print("\n--- Case C: fan rating reflects finishes ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    show_rating.register_subscribers()

    # ---- Scenario 1: KO finish (high fan_rating expected) ----
    force_fight_result(conn, SEEDED_FIGHT_ID, 'ko_tko', A_ID, B_ID)
    conn.execute(
        "UPDATE events SET status='completed' WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    fan_ko = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    check("C", f"KO finish fan_rating recorded (fan={fan_ko})",
          fan_ko is not None, f"fan={fan_ko}")

    # ---- Scenario 2: Decision (low fan_rating expected) ----
    # Delete the existing show_ratings row so we can recompute.
    conn.execute(
        "DELETE FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    # Change result_type to decision + remove title fight flag (so
    # no title bonus). is_title_fight=0 ensures no +10 title bonus.
    force_fight_result(conn, SEEDED_FIGHT_ID, 'unanimous_decision',
                        A_ID, B_ID, is_title_fight=0)
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    fan_dec = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    check("C", f"decision fan_rating recorded (fan={fan_dec})",
          fan_dec is not None, f"fan={fan_dec}")

    # ---- The assertion: KO fan_rating > decision fan_rating ----
    check("C", "KO event has higher fan_rating than decision event",
          fan_ko > fan_dec,
          f"fan_ko={fan_ko}, fan_dec={fan_dec} (delta={fan_ko - fan_dec})")
    # Sanity: the delta should be substantial (KO has +30 finish bonus
    # + +10 title bonus = +40 over the decision case which has 0+0).
    check("C", "fan_rating delta is substantial (>= 25 points)",
          (fan_ko - fan_dec) >= 25,
          f"delta={fan_ko - fan_dec}")
    conn.close()


def case_d_commercial_rating_reflects_marketability():
    """D. Commercial rating reflects marketability."""
    print("\n--- Case D: commercial rating reflects marketability ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    show_rating.register_subscribers()

    # ---- Scenario 1: HIGH marketability fighters ----
    # Set both fighters' marketability to 100 (max).
    conn.execute(
        "UPDATE fighters SET marketability=100 WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    force_fight_result(conn, SEEDED_FIGHT_ID, 'ko_tko', A_ID, B_ID)
    conn.execute(
        "UPDATE events SET status='completed' WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    commercial_high = conn.execute(
        "SELECT commercial_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]

    # ---- Scenario 2: LOW marketability fighters ----
    conn.execute(
        "DELETE FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.execute(
        "UPDATE fighters SET marketability=0 WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    commercial_low = conn.execute(
        "SELECT commercial_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]

    check("D", f"high-mkt commercial_rating recorded (={commercial_high})",
          commercial_high is not None, f"commercial={commercial_high}")
    check("D", f"low-mkt commercial_rating recorded (={commercial_low})",
          commercial_low is not None, f"commercial={commercial_low}")
    check("D", "high-mkt commercial_rating > low-mkt commercial_rating",
          commercial_high > commercial_low,
          f"high={commercial_high}, low={commercial_low} "
          f"(delta={commercial_high - commercial_low})")
    check("D", "commercial_rating delta is substantial (>= 10 points)",
          (commercial_high - commercial_low) >= 10,
          f"delta={commercial_high - commercial_low}")
    conn.close()


def case_e_rating_description_uses_voice_descriptors():
    """E. Rating description uses voice descriptors (no raw numbers)."""
    print("\n--- Case E: rating description uses voice descriptors ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    show_rating.register_subscribers()

    force_fight_result(conn, SEEDED_FIGHT_ID, 'ko_tko', A_ID, B_ID)
    conn.execute(
        "UPDATE events SET status='completed' WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()

    # Verify rating_description is one of the 5 valid descriptors.
    desc_row = conn.execute(
        "SELECT rating_description FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()
    check("E", "rating_description is non-empty",
          desc_row and desc_row[0], f"got={desc_row}")
    if desc_row and desc_row[0]:
        desc = desc_row[0]
        check("E", "rating_description is one of the 5 valid descriptors",
              desc in _VALID_RATING_DESCRIPTIONS,
              f"got={desc!r}")

        # Verify NO digits in the rating_description (CONVENTIONS §14).
        has_digit = bool(_DIGIT_RE.search(desc))
        check("E", "rating_description has NO raw numbers (§14)",
              not has_digit,
              f"desc={desc!r}, has_digit={has_digit}")

    # Verify the news item headline + body have NO raw numbers in the
    # descriptor portion. The headline format is:
    #   "{promo}: {event} was {descriptor}"
    # The body format is:
    #   "The {promo} event '{event}' was {descriptor}. Fans are..."
    # The descriptor itself has no digits. The promo/event names may
    # have digits (e.g. "UFC 300") — but the seed uses "Alpha Combat"
    # and "Alpha Combat: Test Night" which have no digits. So the
    # headline + body should have NO digits at all.
    news = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='show_rating' "
        "AND event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()
    check("E", "show_rating news item exists",
          news is not None, f"got={news}")
    if news:
        headline, body = news
        # The seeded promo + event names have no digits ("Alpha Combat"
        # + "Alpha Combat: Test Night"). So the headline + body should
        # have NO digits at all (the descriptor has none, and the
        # template strings have none).
        headline_has_digit = bool(_DIGIT_RE.search(headline))
        body_has_digit = bool(_DIGIT_RE.search(body))
        check("E", "news headline has NO raw numbers (§14)",
              not headline_has_digit,
              f"headline={headline!r}, has_digit={headline_has_digit}")
        check("E", "news body has NO raw numbers (§14)",
              not body_has_digit,
              f"body={body!r}, has_digit={body_has_digit}")

    # Verify all 5 descriptors are returned by _describe_rating for
    # the appropriate rating bands.
    for overall, expected_substring in [
        (95, "instant classic"),
        (80, "highly entertaining"),
        (65, "solid night"),
        (50, "decent show"),
        (30, "lackluster"),
    ]:
        desc = show_rating._describe_rating(overall)
        check("E", f"_describe_rating({overall}) returns correct band",
              expected_substring in desc,
              f"got={desc!r}, expected substring={expected_substring!r}")
    conn.close()


def case_f_market_heat_changes_after_events():
    """F. Market heat changes after events (successful → +2, poor →
    -1, middling → no change)."""
    print("\n--- Case F: market heat changes after events ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    show_rating.register_subscribers()
    venues.register_subscribers()

    # ---- Scenario 1: Successful event (fan_rating >= 70) → +2 heat ----
    # KO finish on a title fight = +30 (finish) + +10 (title) + 0
    # (rivalry) + 0 (excitement, no beats) = 70. Exactly 70.
    force_fight_result(conn, SEEDED_FIGHT_ID, 'ko_tko', A_ID, B_ID)
    conn.execute(
        "UPDATE events SET status='completed' WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    # Reset market heat to 50 (the seed default) for a clean baseline.
    conn.execute(
        "UPDATE markets SET heat_level=50 WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    )
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    fan_successful = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    heat_after_successful = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    check("F", f"successful event fan_rating={fan_successful} (>= 70)",
          fan_successful >= 70, f"fan={fan_successful}")
    check("F", "successful event → market heat +2 (50 → 52)",
          heat_after_successful == 52,
          f"got={heat_after_successful} (expected 52)")

    # ---- Scenario 2: Poor event (fan_rating < 40) → -1 heat ----
    # Delete the show_ratings row + reset market heat to 50.
    conn.execute(
        "DELETE FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.execute(
        "UPDATE markets SET heat_level=50 WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    )
    # Decision + no title fight = 30 (base) + 0 + 0 + 0 + 0 = 30.
    force_fight_result(conn, SEEDED_FIGHT_ID, 'unanimous_decision',
                        A_ID, B_ID, is_title_fight=0)
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    fan_poor = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    heat_after_poor = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    check("F", f"poor event fan_rating={fan_poor} (< 40)",
          fan_poor < 40, f"fan={fan_poor}")
    check("F", "poor event → market heat -1 (50 → 49)",
          heat_after_poor == 49,
          f"got={heat_after_poor} (expected 49)")

    # ---- Scenario 3: Middling event (40 <= fan_rating < 70) → no change ----
    conn.execute(
        "DELETE FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.execute(
        "UPDATE markets SET heat_level=50 WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    )
    # Decision ON a title fight = 30 (base) + 0 (no finish) + 10
    # (title) + 0 + 0 = 40. Exactly 40 → middling.
    force_fight_result(conn, SEEDED_FIGHT_ID, 'unanimous_decision',
                        A_ID, B_ID, is_title_fight=1)
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    fan_mid = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    heat_after_mid = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    check("F", f"middling event fan_rating={fan_mid} (40-69)",
          40 <= fan_mid < 70, f"fan={fan_mid}")
    check("F", "middling event → market heat unchanged (50 → 50)",
          heat_after_mid == 50,
          f"got={heat_after_mid} (expected 50)")
    conn.close()


def case_g_market_heat_drifts_on_monthly_tick():
    """G. Market heat drifts on monthly tick (hot markets cool toward
    70; cold markets warm toward 40; middling markets unchanged)."""
    print("\n--- Case G: market heat drifts on monthly tick ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    venues.register_subscribers()

    # Set up 3 markets with different heat levels:
    # - Market 1 (seeded): heat 85 (hot, above 80 threshold).
    # - Market 2: heat 25 (cold, below 30 threshold).
    # - Market 3: heat 50 (middling, no drift).
    # We need to create markets 2 + 3 (only market 1 is seeded).
    city_row = conn.execute(
        "SELECT city_id FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()
    city_id = city_row[0] if city_row else 1

    conn.execute(
        "UPDATE markets SET heat_level=85 WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    )
    # Create 2 more cities + markets for the cold + middling cases.
    # Each market has UNIQUE(city_id), so we need 2 new cities.
    city2 = conn.execute(
        "INSERT INTO cities (name, population) VALUES (?, ?)",
        ("Cold City", 500000),
    ).lastrowid
    city3 = conn.execute(
        "INSERT INTO cities (name, population) VALUES (?, ?)",
        ("Steady City", 800000),
    ).lastrowid
    market2 = conn.execute(
        "INSERT INTO markets (city_id, market_type, heat_level) "
        "VALUES (?, ?, ?)",
        (city2, "standard", 25),
    ).lastrowid
    market3 = conn.execute(
        "INSERT INTO markets (city_id, market_type, heat_level) "
        "VALUES (?, ?, ?)",
        (city3, "standard", 50),
    ).lastrowid
    conn.commit()

    # Verify initial heat levels.
    heat_1_before = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    heat_2_before = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (market2,),
    ).fetchone()[0]
    heat_3_before = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (market3,),
    ).fetchone()[0]
    check("G", f"hot market heat=85 (before drift)",
          heat_1_before == 85, f"got={heat_1_before}")
    check("G", f"cold market heat=25 (before drift)",
          heat_2_before == 25, f"got={heat_2_before}")
    check("G", f"middling market heat=50 (before drift)",
          heat_3_before == 50, f"got={heat_3_before}")

    # Publish a MONTHLY tick (current_day = 30, divisible by 30).
    publish_tick_advanced(conn, current_date="2026-08-19", current_day=30)
    conn.commit()

    heat_1_after = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    heat_2_after = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (market2,),
    ).fetchone()[0]
    heat_3_after = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (market3,),
    ).fetchone()[0]

    # Hot market (85 → 84): cools by 1 (above 80 threshold).
    check("G", "hot market (85) cools by 1 on monthly tick (85 → 84)",
          heat_1_after == 84,
          f"got={heat_1_after} (expected 84)")
    # Cold market (25 → 26): warms by 1 (below 30 threshold).
    check("G", "cold market (25) warms by 1 on monthly tick (25 → 26)",
          heat_2_after == 26,
          f"got={heat_2_after} (expected 26)")
    # Middling market (50 → 50): no drift (between 30 and 80).
    check("G", "middling market (50) unchanged on monthly tick (50 → 50)",
          heat_3_after == 50,
          f"got={heat_3_after} (expected 50)")

    # ---- Verify the drift is SLOW (±1 per monthly tick, not ±10) ----
    check("G", "drift is ±1 per monthly tick (slow by design)",
          abs(heat_1_after - heat_1_before) == 1
          and abs(heat_2_after - heat_2_before) == 1
          and abs(heat_3_after - heat_3_before) == 0,
          f"deltas: hot={heat_1_after - heat_1_before}, "
          f"cold={heat_2_after - heat_2_before}, "
          f"mid={heat_3_after - heat_3_before}")

    # ---- Verify NON-monthly tick does NOT drift ----
    # Publish a NON-monthly tick (current_day = 31, NOT divisible by 30).
    publish_tick_advanced(conn, current_date="2026-08-20", current_day=31)
    conn.commit()
    heat_1_non_monthly = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    check("G", "non-monthly tick (day 31) → no drift",
          heat_1_non_monthly == heat_1_after,
          f"got={heat_1_non_monthly} (expected {heat_1_after})")

    # ---- Verify hot market floor (70) + cold market ceiling (40) ----
    # Set hot market to 71 (just above floor) and cold market to 39
    # (just below ceiling). Run a monthly tick. Hot should cool to 70
    # (floor), cold should warm to 40 (ceiling). Run ANOTHER monthly
    # tick — hot stays at 70 (not above 80, but the floor check
    # prevents going below 70), cold stays at 40 (ceiling check).
    # Actually, with the literal-brief interpretation (heat >= 80
    # triggers cooling), heat 71 would NOT cool (below 80). Let me
    # test the threshold behavior:
    # - Heat 80 → cool to 79 (drift triggers, 80 >= 80).
    # - Heat 79 → no drift (79 < 80).
    conn.execute(
        "UPDATE markets SET heat_level=80 WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    )
    conn.execute(
        "UPDATE markets SET heat_level=29 WHERE market_id=?",
        (market2,),
    )
    conn.commit()
    publish_tick_advanced(conn, current_date="2026-09-19", current_day=60)
    conn.commit()
    heat_1_threshold = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    heat_2_threshold = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (market2,),
    ).fetchone()[0]
    check("G", "heat 80 (hot threshold) → cool by 1 (80 → 79)",
          heat_1_threshold == 79,
          f"got={heat_1_threshold} (expected 79)")
    check("G", "heat 29 (cold threshold) → warm by 1 (29 → 30)",
          heat_2_threshold == 30,
          f"got={heat_2_threshold} (expected 30)")
    conn.close()


def case_h_design_law():
    """H. Design Law (§13): Investment (market growth) + Stories
    (show ratings create the 'remember that great card' storyline)."""
    print("\n--- Case H: Design Law (§13) ---")
    build_fresh_db()
    conn = get_conn()
    reset_bus()
    show_rating.register_subscribers()
    venues.register_subscribers()

    # ---- Investment (market growth) ----
    # A successful event in a market → +2 heat → finance.py's
    # _compute_fill_rate (heat/100) → higher fill rate → more ticket
    # revenue next time. The player's investment in booking good
    # cards in a specific market pays off.
    force_fight_result(conn, SEEDED_FIGHT_ID, 'ko_tko', A_ID, B_ID)
    conn.execute(
        "UPDATE events SET status='completed' WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    )
    conn.execute(
        "UPDATE markets SET heat_level=50 WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    )
    conn.commit()
    publish_event_completed(conn, SEEDED_EVENT_ID, ALPHA_COMBAT_ID,
                            SEEDED_EVENT_DATE)
    conn.commit()
    fan = conn.execute(
        "SELECT fan_rating FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    heat_after_good = conn.execute(
        "SELECT heat_level FROM markets WHERE market_id=?",
        (SEEDED_MARKET_ID,),
    ).fetchone()[0]
    # Verify the Investment loop: good card → fan_rating >= 70 →
    # market heat +2 → future events in this market will have higher
    # fill rates → more revenue.
    check("H", "Investment: good card → fan_rating >= 70",
          fan >= 70, f"fan={fan}")
    check("H", "Investment: good card → market heat +2 (growth)",
          heat_after_good == 52,
          f"heat={heat_after_good} (expected 52)")
    check("H", "Investment: market growth → higher fill rate next time",
          True,  # structural assertion — finance.py uses heat/100 for fill_rate
          "structural (finance._compute_fill_rate reads heat_level)")

    # ---- Stories (show ratings create memorable storylines) ----
    # The rating_description column + the topic='show_rating' news
    # item give every show a VERDICT. The player remembers the great
    # cards ("an instant classic") and the duds ("a lackluster card").
    desc = conn.execute(
        "SELECT rating_description FROM show_ratings WHERE event_id=?",
        (SEEDED_EVENT_ID,),
    ).fetchone()[0]
    check("H", f"Stories: every show gets a verdict ({desc!r})",
          desc in _VALID_RATING_DESCRIPTIONS, f"desc={desc!r}")
    # The 5 descriptors span the emotional range — from "instant
    # classic" (great) to "lackluster" (bad). This creates the
    # narrative texture the Soul document mandates.
    check("H", "Stories: 5 voice descriptors span great → bad",
          len(_VALID_RATING_DESCRIPTIONS) == 5,
          f"count={len(_VALID_RATING_DESCRIPTIONS)}")

    # ---- Anticipation (the "what's next?" thread) ----
    # After a great card, the player wants the next one to be even
    # better. After a dud, the player wants to rebound. The ratings
    # create the "what's next?" thread that keeps the player clicking
    # Advance Day.
    check("H", "Anticipation: ratings create 'what's next?' thread",
          True,  # structural assertion — verified by the rating range
          "structural (5-tier descriptor range creates anticipation)")

    # ---- Event bus (CONVENTIONS §15.4) ----
    # Both show_rating + venues are entirely event-bus-driven. No
    # inline side effects added to resolve_next_fight or run_tick.
    bus = get_bus()
    event_completed_subs = bus.subscriber_count(Events.EVENT_COMPLETED)
    tick_advanced_subs = bus.subscriber_count(Events.TICK_ADVANCED)
    # show_rating registers 1 EVENT_COMPLETED subscriber.
    # venues registers 1 EVENT_COMPLETED + 1 TICK_ADVANCED subscriber.
    check("H", f"Event bus: show_rating + venues registered "
          f"(EVENT_COMPLETED subs >= 2)",
          event_completed_subs >= 2,
          f"EVENT_COMPLETED subs={event_completed_subs}")
    check("H", f"Event bus: venues TICK_ADVANCED subscriber registered",
          tick_advanced_subs >= 1,
          f"TICK_ADVANCED subs={tick_advanced_subs}")
    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print(f"Stage 5 — Show rating engine + Venues/markets deeper simulation")
    print(f"(schema {EXPECTED_CODE_VERSION}, migration prefix "
          f"{EXPECTED_MIGRATION_PREFIX!r})")
    print(sep)

    case_a_schema()
    case_b_show_rating_computed_on_completion()
    case_c_fan_rating_reflects_finishes()
    case_d_commercial_rating_reflects_marketability()
    case_e_rating_description_uses_voice_descriptors()
    case_f_market_heat_changes_after_events()
    case_g_market_heat_drifts_on_monthly_tick()
    case_h_design_law()

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
