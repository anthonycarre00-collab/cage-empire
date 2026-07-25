#!/usr/bin/env python3
"""Acceptance test for Phase 1 — Fix 1.4 (Hall of Fame induction).

Tests the new `src/services/hof_svc.py` module that subscribes to
FIGHTER_RETIRED and inducts qualifying fighters into `hall_of_fame`.

  Case A — module imports + register_subscribers
  Case B — eligible fighter (title_reigns >= 2) gets inducted on
           FIGHTER_RETIRED
  Case C — induction news item written with topic='hall_of_fame'
  Case D — ineligible fighter (title_reigns=0, wins=5) NOT inducted
  Case E — idempotency: already-inducted fighter not re-inducted
  Case F — career_summary has NO raw numbers (CONVENTIONS §14)
  Case G — career_highlights formatted as bullet list (•)
  Case H — eligibility variants (wins >= 30 OR wins >= 20 + reigns >= 1)
  Case I — Design Law (§13): Legacy pillar — HoF induction is how
           the world remembers what the player built

Pattern follows scripts/test_memory_gameplans.py (Case A-H structure,
check() function, dynamic version pattern per CONVENTIONS §10).
"""
import re
import sys
import sqlite3
import subprocess
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

import build_db  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402
from services.hof_svc import (  # noqa: E402
    register_subscribers,
    induce_fighter_into_hof,
    _is_eligible_for_hof,
    _generate_career_summary,
    _generate_career_highlights,
)

EXPECTED_VERSION = build_db.CODE_SCHEMA_VERSION

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Used for case F (career_summary has no raw numbers).
_DIGIT_RE = re.compile(r"[0-9]")

results = []


def check(case, name, passed, detail=""):
    results.append((case, name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  {case}  {name:<70} {status}  {detail}")


def build_fresh_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run([sys.executable, str(SRC_DIR / "build_db.py")],
                   check=True, cwd=PROJECT_DIR)
    subprocess.run([sys.executable, str(SRC_DIR / "seed_data.py")],
                   check=True, cwd=PROJECT_DIR)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _set_career(conn, fighter_id, wins=0, losses=0, draws=0,
                title_reigns=0, win_streak=0, loss_streak=0,
                career_health=80):
    """Set a fighter's fighter_career row to the given values."""
    conn.execute(
        "UPDATE fighter_career SET record_wins=?, record_losses=?, "
        "record_draws=?, title_reigns=?, win_streak=?, loss_streak=?, "
        "career_health=? WHERE fighter_id=?",
        (wins, losses, draws, title_reigns, win_streak, loss_streak,
         career_health, fighter_id),
    )


def _set_attrs(conn, fighter_id, **attrs):
    """Set specific fighter_attributes columns for a fighter."""
    for col, val in attrs.items():
        conn.execute(
            f"UPDATE fighter_attributes SET {col}=? "
            f"WHERE fighter_id=?",
            (val, fighter_id),
        )


def _retire(conn, fighter_id):
    """Mark a fighter as retired (is_active=0, is_retired=1)."""
    conn.execute(
        "UPDATE fighters SET is_active=0, is_retired=1 "
        "WHERE fighter_id=?",
        (fighter_id,),
    )


# ----------------------------------------------------------------
# Case A — module imports + register_subscribers
# ----------------------------------------------------------------

def case_a_imports():
    """A. Module imports + register_subscribers runs without error."""
    print("\n--- Case A: module imports + register_subscribers ---")
    build_fresh_db()
    reset_bus()
    # register_subscribers should run without error
    try:
        register_subscribers()
        check("A", "register_subscribers() runs without error",
              True, "")
    except Exception as e:
        check("A", "register_subscribers() runs without error",
              False, f"{type(e).__name__}: {e}")
        return

    # Verify the subscriber is registered on FIGHTER_RETIRED
    bus = get_bus()
    count = bus.subscriber_count(Events.FIGHTER_RETIRED)
    check("A", "FIGHTER_RETIRED subscriber registered",
          count >= 1, f"got={count}")

    # Verify the public API is callable
    check("A", "induce_fighter_into_hof callable",
          callable(induce_fighter_into_hof), "")
    check("A", "_is_eligible_for_hof callable",
          callable(_is_eligible_for_hof), "")
    check("A", "_generate_career_summary callable",
          callable(_generate_career_summary), "")
    check("A", "_generate_career_highlights callable",
          callable(_generate_career_highlights), "")


# ----------------------------------------------------------------
# Case B — eligible fighter (title_reigns >= 2) gets inducted
# ----------------------------------------------------------------

def case_b_eligible_inducted():
    """B. Eligible fighter (title_reigns=2) gets inducted on
    FIGHTER_RETIRED."""
    print("\n--- Case B: eligible fighter (title_reigns=2) inducted ---")
    build_fresh_db()
    conn = get_conn()

    # Make fighter 1 (John Vale) an eligible retiree:
    # - title_reigns = 2 (multi-time champion — eligibility criterion #1)
    # - 25 wins, 5 losses (a respectable career)
    # - 35 years old, plenty of fights → "grizzled veteran" stage
    _set_career(conn, 1, wins=25, losses=5, title_reigns=2,
                win_streak=0, loss_streak=0, career_health=60)
    _set_attrs(conn, 1, punch_power=85, chin=80, cardio=70,
               fight_iq=75, punch_accuracy=80)
    _retire(conn, 1)
    conn.commit()

    # Get HoF count before
    before = conn.execute("SELECT COUNT(*) FROM hall_of_fame").fetchone()[0]
    check("B", "hall_of_fame empty before induction",
          before == 0, f"got={before}")

    # Register the subscriber and publish FIGHTER_RETIRED
    reset_bus()
    register_subscribers()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()

    # Verify the fighter was inducted
    after = conn.execute("SELECT COUNT(*) FROM hall_of_fame").fetchone()[0]
    check("B", "hall_of_fame count incremented",
          after == before + 1, f"before={before} after={after}")

    row = conn.execute(
        "SELECT fighter_id, inducted_date, career_summary, "
        "career_highlights FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()
    check("B", "inducted row exists for fighter_id=1",
          row is not None, f"got={row}")
    if row:
        fid, inducted, summary, highlights = row
        check("B", "inducted_date is the sim date",
              inducted == '2026-07-25', f"got={inducted}")
        check("B", "career_summary is non-empty",
              bool(summary and summary.strip()),
              f"len={len(summary) if summary else 0}")
        check("B", "career_highlights is non-empty",
              bool(highlights and highlights.strip()),
              f"len={len(highlights) if highlights else 0}")
        if summary:
            print(f"      summary: {summary[:120]}")
        if highlights:
            print(f"      highlights (first 200): {highlights[:200]}")
    conn.close()


# ----------------------------------------------------------------
# Case C — induction news item written with topic='hall_of_fame'
# ----------------------------------------------------------------

def case_c_induction_news():
    """C. Induction news item written with topic='hall_of_fame'."""
    print("\n--- Case C: induction news item with topic='hall_of_fame' ---")
    build_fresh_db()
    conn = get_conn()

    _set_career(conn, 1, wins=25, losses=5, title_reigns=2,
                career_health=60)
    _set_attrs(conn, 1, punch_power=85, chin=80)
    _retire(conn, 1)
    conn.commit()

    reset_bus()
    register_subscribers()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()

    # Verify the induction news item was written
    news = conn.execute(
        "SELECT headline, body, topic, fighter_id, published_at "
        "FROM news_items WHERE topic='hall_of_fame' "
        "AND fighter_id=1"
    ).fetchall()
    check("C", "induction news item written (topic='hall_of_fame')",
          len(news) >= 1, f"got={len(news)}")

    if news:
        headline, body, topic, fid, pub = news[0]
        check("C", "headline mentions 'Hall of Fame'",
              "Hall of Fame" in headline, f"headline={headline!r}")
        check("C", "headline mentions fighter name",
              "Vale" in headline, f"headline={headline!r}")
        check("C", "body is non-empty",
              bool(body and body.strip()), f"len={len(body) if body else 0}")
        check("C", "published_at is the sim date",
              pub == '2026-07-25', f"got={pub}")
        print(f"      headline: {headline}")
        print(f"      body (first 200): {body[:200] if body else ''}")
    conn.close()


# ----------------------------------------------------------------
# Case D — ineligible fighter NOT inducted
# ----------------------------------------------------------------

def case_d_ineligible_skipped():
    """D. Ineligible fighter (title_reigns=0, wins=5) NOT inducted."""
    print("\n--- Case D: ineligible fighter NOT inducted ---")
    build_fresh_db()
    conn = get_conn()

    # Fighter 1: 5 wins, 0 titles → not eligible
    _set_career(conn, 1, wins=5, losses=10, title_reigns=0,
                career_health=70)
    _retire(conn, 1)
    conn.commit()

    # Verify _is_eligible_for_hof returns False
    eligible = _is_eligible_for_hof(conn, 1)
    check("D", "_is_eligible_for_hof(fighter with 5 wins, 0 reigns) = False",
          eligible is False, f"got={eligible}")

    # Publish FIGHTER_RETIRED — should NOT induce
    reset_bus()
    register_subscribers()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()

    row = conn.execute(
        "SELECT 1 FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()
    check("D", "ineligible fighter NOT in hall_of_fame",
          row is None, f"got={row}")

    # Verify NO hall_of_fame news was written for this fighter
    news = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='hall_of_fame' AND fighter_id=1"
    ).fetchone()[0]
    check("D", "no hall_of_fame news for ineligible fighter",
          news == 0, f"got={news}")
    conn.close()


# ----------------------------------------------------------------
# Case E — idempotency: already-inducted fighter not re-inducted
# ----------------------------------------------------------------

def case_e_idempotent():
    """E. Idempotency: inducting an already-inducted fighter does NOT
    create a duplicate."""
    print("\n--- Case E: idempotency — no duplicate induction ---")
    build_fresh_db()
    conn = get_conn()

    _set_career(conn, 1, wins=25, losses=5, title_reigns=2,
                career_health=60)
    _set_attrs(conn, 1, punch_power=85, chin=80)
    _retire(conn, 1)
    conn.commit()

    reset_bus()
    register_subscribers()
    bus = get_bus()

    # First publish — should induce
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()
    after_first = conn.execute(
        "SELECT COUNT(*) FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()[0]
    news_after_first = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='hall_of_fame' AND fighter_id=1"
    ).fetchone()[0]
    check("E", "first publish inducts the fighter",
          after_first == 1, f"got={after_first}")
    check("E", "first publish writes 1 induction news item",
          news_after_first == 1, f"got={news_after_first}")

    # Second publish — should be a no-op (idempotent)
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()
    after_second = conn.execute(
        "SELECT COUNT(*) FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()[0]
    news_after_second = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='hall_of_fame' AND fighter_id=1"
    ).fetchone()[0]
    check("E", "second publish does NOT create a 2nd hall_of_fame row",
          after_second == 1, f"got={after_second}")
    check("E", "second publish does NOT create a 2nd news item",
          news_after_second == 1, f"got={news_after_second}")
    conn.close()


# ----------------------------------------------------------------
# Case F — career_summary has NO raw numbers (§14)
# ----------------------------------------------------------------

def case_f_no_raw_numbers():
    """F. career_summary has NO raw numbers (CONVENTIONS §14).

    Uses the digit regex pattern from other tests (re.compile(r"[0-9]")).
    Career stats (wins/losses/reigns) are OK in career_highlights —
    they're career stats, not attribute values. Only career_summary
    must be digit-free.
    """
    print("\n--- Case F: career_summary has no raw numbers (§14) ---")
    build_fresh_db()
    conn = get_conn()

    # Make fighter 1 an eligible retiree with rich attributes so
    # describe_overall produces a non-trivial summary.
    _set_career(conn, 1, wins=28, losses=5, draws=0, title_reigns=3,
                win_streak=0, loss_streak=0, career_health=55)
    _set_attrs(conn, 1, punch_power=90, chin=85, cardio=75,
               fight_iq=80, punch_accuracy=85)
    _retire(conn, 1)
    conn.commit()

    reset_bus()
    register_subscribers()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()

    row = conn.execute(
        "SELECT career_summary FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()
    check("F", "career_summary row exists",
          row is not None and row[0] is not None, f"got={row}")
    if row and row[0]:
        summary = row[0]
        has_digit = bool(_DIGIT_RE.search(summary))
        check("F", "career_summary has NO raw digit characters (§14)",
              not has_digit,
              f"summary={summary[:120]!r}")
        print(f"      summary: {summary}")
    conn.close()


# ----------------------------------------------------------------
# Case G — career_highlights formatted as bullet list (•)
# ----------------------------------------------------------------

def case_g_highlights_bullet_list():
    """G. career_highlights formatted as a bullet list (•)."""
    print("\n--- Case G: career_highlights is a bullet list ---")
    build_fresh_db()
    conn = get_conn()

    _set_career(conn, 1, wins=28, losses=5, title_reigns=3,
                career_health=55)
    _set_attrs(conn, 1, punch_power=90, chin=85)
    _retire(conn, 1)
    conn.commit()

    reset_bus()
    register_subscribers()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()

    row = conn.execute(
        "SELECT career_highlights FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()
    check("G", "career_highlights row exists",
          row is not None and row[0] is not None, f"got={row}")
    if row and row[0]:
        highlights = row[0]
        # Should have at least 2 bullet points (reigns + record + stage)
        bullet_count = highlights.count("•")
        check("G", "career_highlights has at least 3 bullet points",
              bullet_count >= 3, f"got={bullet_count}")

        # Should mention the title reigns (career stat — OK per §14)
        check("G", "career_highlights mentions 'champion' or 'title'",
              "champion" in highlights.lower()
              or "title" in highlights.lower()
              or "belt" in highlights.lower(),
              f"highlights={highlights[:200]!r}")

        # Should mention the career record (W-L or W-L-D format)
        # Look for the pattern "NN-NN" or "NN-NN-NN"
        record_match = re.search(r"\d+-\d+(-\d+)?", highlights)
        check("G", "career_highlights mentions the W-L(-D) record",
              record_match is not None,
              f"highlights={highlights[:200]!r}")

        # Should mention the career stage descriptor (Retired as ...)
        check("G", "career_highlights mentions 'Retired as' (career stage)",
              "Retired as" in highlights,
              f"highlights={highlights[:200]!r}")

        print(f"      highlights:\n        " +
              "\n        ".join(highlights.split("\n")))
    conn.close()


# ----------------------------------------------------------------
# Case H — eligibility variants
# ----------------------------------------------------------------

def case_h_eligibility_variants():
    """H. Eligibility variants:
       - title_reigns >= 2 → eligible (covered in case B)
       - wins >= 30 → eligible (longevity + success)
       - wins >= 20 AND title_reigns >= 1 → eligible
       - wins >= 20 AND title_reigns = 0 → NOT eligible
       - wins = 19 AND title_reigns = 1 → NOT eligible
    """
    print("\n--- Case H: eligibility variants ---")
    build_fresh_db()
    conn = get_conn()

    # Use 3 different fighters (1, 2, 3 from the minimal seed) for
    # the 3 eligibility variants. The minimal seed has 5 fighters.

    # Fighter 1: wins=32, title_reigns=0 → eligible (wins >= 30)
    _set_career(conn, 1, wins=32, losses=10, title_reigns=0,
                career_health=60)
    eligible_1 = _is_eligible_for_hof(conn, 1)
    check("H", "wins=32, reigns=0 → eligible (wins >= 30)",
          eligible_1 is True, f"got={eligible_1}")

    # Fighter 2: wins=22, title_reigns=1 → eligible (wins >= 20 +
    # reigns >= 1)
    _set_career(conn, 2, wins=22, losses=8, title_reigns=1,
                career_health=65)
    eligible_2 = _is_eligible_for_hof(conn, 2)
    check("H", "wins=22, reigns=1 → eligible (wins >= 20 + reigns >= 1)",
          eligible_2 is True, f"got={eligible_2}")

    # Fighter 3: wins=22, title_reigns=0 → NOT eligible
    _set_career(conn, 3, wins=22, losses=8, title_reigns=0,
                career_health=65)
    eligible_3 = _is_eligible_for_hof(conn, 3)
    check("H", "wins=22, reigns=0 → NOT eligible",
          eligible_3 is False, f"got={eligible_3}")

    # Fighter 4: wins=19, title_reigns=1 → NOT eligible
    _set_career(conn, 4, wins=19, losses=5, title_reigns=1,
                career_health=70)
    eligible_4 = _is_eligible_for_hof(conn, 4)
    check("H", "wins=19, reigns=1 → NOT eligible",
          eligible_4 is False, f"got={eligible_4}")

    # Fighter 5: wins=30, title_reigns=0 → eligible (boundary)
    _set_career(conn, 5, wins=30, losses=15, title_reigns=0,
                career_health=55)
    eligible_5 = _is_eligible_for_hof(conn, 5)
    check("H", "wins=30 (boundary), reigns=0 → eligible",
          eligible_5 is True, f"got={eligible_5}")

    # End-to-end: retire fighters 1, 2 (eligible) + 3, 4 (not eligible)
    # and publish FIGHTER_RETIRED for each. Fighters 1 and 2 should
    # be inducted; fighters 3 and 4 should not.
    for fid in (1, 2, 3, 4, 5):
        _retire(conn, fid)
    conn.commit()

    reset_bus()
    register_subscribers()
    bus = get_bus()
    for fid in (1, 2, 3, 4, 5):
        bus.publish(conn, {
            'type': Events.FIGHTER_RETIRED,
            'fighter_id': fid,
            'current_date': '2026-07-25',
        })
    conn.commit()

    inducted = conn.execute(
        "SELECT fighter_id FROM hall_of_fame "
        "WHERE fighter_id IN (1,2,3,4,5) ORDER BY fighter_id"
    ).fetchall()
    inducted_ids = [r[0] for r in inducted]
    # Fighters 1, 2, 5 are eligible → should be inducted.
    # Fighters 3, 4 are not eligible → should NOT be inducted.
    check("H", "eligible fighters 1, 2, 5 inducted",
          set(inducted_ids) == {1, 2, 5},
          f"got={inducted_ids}")
    conn.close()


# ----------------------------------------------------------------
# Case I — Design Law (§13): Legacy pillar
# ----------------------------------------------------------------

def case_i_design_law():
    """I. Design Law (§13): Legacy pillar — HoF induction is how
    the world remembers what the player built.

    The Historian fantasy (CAGE_EMPIRE_SOUL.md Fantasy 4) requires
    that every champion the player develops is remembered on
    retirement. Without this fix, the 60 seeded legends are the
    only HoF inductees forever. This case verifies the Historian
    fantasy is now functional: a player-developed champion (high
    title_reigns, generated during gameplay) is inducted on
    retirement with a voice-layered career summary that captures
    their story.
    """
    print("\n--- Case I: Design Law (§13) Legacy pillar ---")
    build_fresh_db()
    conn = get_conn()

    # Simulate a "player-developed champion" — a fighter the player
    # scouted, signed, developed, and led to 3 title reigns over a
    # long career.
    _set_career(conn, 1, wins=35, losses=8, draws=1, title_reigns=3,
                win_streak=0, loss_streak=0, career_health=50)
    _set_attrs(conn, 1, punch_power=92, chin=88, cardio=78,
               fight_iq=85, punch_accuracy=88)
    _retire(conn, 1)
    conn.commit()

    reset_bus()
    register_subscribers()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.FIGHTER_RETIRED,
        'fighter_id': 1,
        'fighter_name': 'John Vale',
        'current_date': '2026-07-25',
    })
    conn.commit()

    # Verify the fighter is in the HoF
    inducted = conn.execute(
        "SELECT career_summary, career_highlights "
        "FROM hall_of_fame WHERE fighter_id=1"
    ).fetchone()
    check("I", "player-developed champion inducted into HoF",
          inducted is not None, "")

    if inducted:
        summary, highlights = inducted
        # The career_summary should be a meaningful narrative line
        # (not just a placeholder). At least 40 characters.
        check("I", "career_summary is a meaningful narrative (>= 40 chars)",
              len(summary) >= 40, f"len={len(summary)}")

        # The career_summary should NOT be the generic fallback
        # ("A career worth remembering...") — it should use
        # voice.describe_overall which produces a fighter-specific
        # summary.
        check("I", "career_summary is fighter-specific (not generic fallback)",
              "A career worth remembering" not in summary,
              f"summary={summary[:120]!r}")

        # The career_highlights should mention the title reigns
        # (the player's investment in this champion paid off).
        check("I", "career_highlights mentions title reigns",
              "champion" in highlights.lower()
              or "title" in highlights.lower()
              or "belt" in highlights.lower(),
              f"highlights={highlights[:200]!r}")

        # The career_highlights should mention the career stage
        # descriptor (the fighter's story arc — "grizzled veteran",
        # "battle-tested veteran", etc.)
        check("I", "career_highlights mentions career stage descriptor",
              "Retired as" in highlights,
              f"highlights={highlights[:200]!r}")

        print(f"      Final HoF entry:")
        print(f"        summary:    {summary}")
        print(f"        highlights: {highlights.replace(chr(10), chr(10) + '          ')}")
    conn.close()


# ----------------------------------------------------------------
# main()
# ----------------------------------------------------------------

def main():
    print("=" * 80)
    print(f"Phase 1 — Fix 1.4 (Hall of Fame induction) acceptance test")
    print(f"schema {EXPECTED_VERSION}, no schema change")
    print("=" * 80)
    case_a_imports()
    case_b_eligible_inducted()
    case_c_induction_news()
    case_d_ineligible_skipped()
    case_e_idempotent()
    case_f_no_raw_numbers()
    case_g_highlights_bullet_list()
    case_h_eligibility_variants()
    case_i_design_law()
    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 80)
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
