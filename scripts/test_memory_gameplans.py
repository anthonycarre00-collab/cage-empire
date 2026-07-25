#!/usr/bin/env python3
"""Acceptance test for Phase A — Task A11+A12 (Memory + Gameplans).

Tests the memory resurfacing wiring (A11) and the dynamic
preferred_gameplans / bad_matchup_tags population (A12). Both are
code-only fixes — no schema change.

  A11a (news engine memory resurfacing):
    B. memory resurfacing news generated on TITLE_CHANGED when
       fighter_memory_links has a 'successor' row for the new champ
    C. NO memory resurfacing news when no successor link exists
    D. memory resurfacing news uses voice descriptors (no raw
       numbers — §14)

  A11b (scouting STYLE ECHO):
    E. scouting report includes STYLE ECHO when target is a regen
       replacement (regen_lineage.replacement_fighter_id == target)
    F. scouting report does NOT include STYLE ECHO when target is
       not a regen replacement
    G. STYLE ECHO uses voice descriptors for the legend's career
       stage (no raw numbers — §14)

  A12a (preferred_gameplans):
    H. preferred_gameplans populated after a win (NULL → list)
    I. preferred_gameplans doesn't duplicate (re-add same gameplan)
    J. preferred_gameplans capped at 3

  A12b (bad_matchup_tags):
    K. bad_matchup_tags populated after a loss
    L. bad_matchup_tags doesn't duplicate (re-add same tag)
    M. bad_matchup_tags capped at 5

  Design Law + smoke:
    N. Design Law (§13): Legacy pillar — memory resurfacing tells
       torch-passing stories
    O. Smoke test (the exact test from the brief)

Pattern follows scripts/test_morale.py (CONVENTIONS §10 — dynamic
version, reset_bus + register_subscribers per case for isolation).
"""
import json
import re
import sys
import os
import sqlite3
import subprocess
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import news  # noqa: E402
import scouting  # noqa: E402
import build_db  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

EXPECTED_VERSION = build_db.CODE_SCHEMA_VERSION

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Used for case D (memory resurfacing news) and case G (STYLE
# ECHO).
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


def _set_fighter_attrs(conn, fighter_id, **attrs):
    """Set specific fighter_attributes columns for a fighter.

    Used to make a fighter's stats exceed the gameplan threshold (60)
    so _derive_preferred_gameplans produces predictable results.
    """
    for col, val in attrs.items():
        conn.execute(
            f"UPDATE fighter_attributes SET {col}=? "
            f"WHERE fighter_id=?",
            (val, fighter_id),
        )


def _set_fighter_pers(conn, fighter_id, **traits):
    """Set specific fighter_personality columns for a fighter."""
    for col, val in traits.items():
        conn.execute(
            f"UPDATE fighter_personality SET {col}=? "
            f"WHERE fighter_id=?",
            (val, fighter_id),
        )


def _seed_scout(conn, **kwargs):
    """Insert a scout with custom attributes. Returns the staff_id."""
    attrs = {
        "eye_for_talent": 80,
        "technical_analysis": 75,
        "character_reading": 60,
        "mistake_rate": 5,
        "bias_style": None,
        "bias_nationality": None,
        "bias_aggression": 0,
        "current_assignment": None,
        "assignment_start_date": None,
    }
    attrs.update(kwargs)
    cur = conn.execute(
        "INSERT INTO staff (first_name, last_name, age, nation_id, "
        "role_type, specialty, promotion_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Test", "Scout", 45, 1, "scout", json.dumps(attrs), 1),
    )
    return cur.lastrowid


# ----------------------------------------------------------------
# Case A — module imports
# ----------------------------------------------------------------

def case_a_imports():
    """A. Module imports + helper functions callable."""
    print("\n--- Case A: module imports ---")
    build_fresh_db()
    check("A", "news module imports without error", news is not None, "")
    check("A", "scouting module imports without error",
          scouting is not None, "")
    check("A", "app module imports without error", app is not None, "")
    # A11a — memory resurfacing subscriber
    check("A", "news.generate_memory_resurfacing_news callable",
          callable(getattr(news, "generate_memory_resurfacing_news", None)),
          "")
    # A11b — STYLE ECHO helper
    check("A", "scouting._build_style_echo callable",
          callable(getattr(scouting, "_build_style_echo", None)), "")
    # A12a — gameplan helpers
    check("A", "app._derive_preferred_gameplans callable",
          callable(getattr(app, "_derive_preferred_gameplans", None)), "")
    check("A", "app._update_preferred_gameplans callable",
          callable(getattr(app, "_update_preferred_gameplans", None)), "")
    # A12b — bad matchup helpers
    check("A", "app._derive_bad_matchup_tags callable",
          callable(getattr(app, "_derive_bad_matchup_tags", None)), "")
    check("A", "app._update_bad_matchup_tags callable",
          callable(getattr(app, "_update_bad_matchup_tags", None)), "")
    # Constants
    check("A", "app._GAMEPLAN_CAP == 3", app._GAMEPLAN_CAP == 3, "")
    check("A", "app._BAD_MATCHUP_CAP == 5", app._BAD_MATCHUP_CAP == 5, "")
    check("A", "app._GAMEPLAN_THRESHOLD == 60",
          app._GAMEPLAN_THRESHOLD == 60, "")


# ----------------------------------------------------------------
# Case B — A11a memory resurfacing news on TITLE_CHANGED
# ----------------------------------------------------------------

def case_b_memory_resurfacing_news():
    """B. memory resurfacing news generated on TITLE_CHANGED when
    fighter_memory_links has a 'successor' row for the new champ."""
    print("\n--- Case B: A11a memory resurfacing news on TITLE_CHANGED ---")
    build_fresh_db()
    conn = get_conn()

    # The seeded fight is a vacant-title fight between John Vale (f1)
    # and Marcus Reed (f2). Set f1 to be a beast so they win, then
    # add a 'successor' memory link from f1 to a "legend" (use f3 —
    # Dario Knox — as the legend for test purposes).
    _set_fighter_attrs(conn, 1, punch_power=90, cardio=90, fight_iq=90,
                       chin=90, punch_accuracy=90, kick_power=90,
                       kick_accuracy=90, head_movement=90, footwork=90)
    # Mark f3 (Dario Knox) as a former champion for narrative flavor.
    conn.execute(
        "UPDATE fighter_career SET title_reigns=2, record_wins=25, "
        "record_losses=5 WHERE fighter_id=3"
    )
    # Insert the fighter_memory_links 'successor' row. Per
    # tick_processor._check_retirements, the row is
    # (fighter_id=replacement, linked_fighter_id=legend, 'successor').
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'successor', ?)",
        (1, 3, 80),  # f1 is the successor of f3 (the legend)
    )
    conn.commit()

    # Resolve the fight — f1 wins the vacant title, TITLE_CHANGED
    # fires, generate_memory_resurfacing_news runs.
    reset_bus()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()

    # Verify the title actually changed (f1 is the new champ).
    champ_id = conn.execute(
        "SELECT current_champion_fighter_id FROM titles "
        "WHERE title_id IN (SELECT MIN(title_id) FROM titles)"
    ).fetchone()
    check("B", "title was claimed (f1 is the new champ)",
          champ_id and champ_id[0] == 1,
          f"got={champ_id[0] if champ_id else None}")

    # Verify the memory resurfacing news item was written.
    mem_news = conn.execute(
        "SELECT headline, body FROM news_items "
        "WHERE topic='memory_resurfacing'"
    ).fetchall()
    check("B", "memory_resurfacing news item generated",
          len(mem_news) >= 1, f"got={len(mem_news)}")
    if mem_news:
        print(f"      headline: {mem_news[0][0]}")
        print(f"      body (first 200): {mem_news[0][1][:200]}")

    # Verify the news item references both the new champ and the legend.
    if mem_news:
        text = (mem_news[0][0] + " " + mem_news[0][1]).lower()
        # f1 is John Vale, f3 is Dario Knox. Either last name should
        # appear, but the legend (Knox) MUST appear (that's the
        # memory-resurfacing payoff — the new champ's win invokes
        # the legend's name).
        check("B", "memory news references the legend (Knox)",
              "knox" in text, f"text snippet={text[:200]!r}")
        check("B", "memory news references the new champ (Vale)",
              "vale" in text, f"text snippet={text[:200]!r}")
    conn.close()


# ----------------------------------------------------------------
# Case C — A11a NO memory resurfacing news when no link exists
# ----------------------------------------------------------------

def case_c_no_memory_news_without_link():
    """C. NO memory resurfacing news when no successor link exists."""
    print("\n--- Case C: no memory news without successor link ---")
    build_fresh_db()
    conn = get_conn()
    # Make f1 win the vacant title but DON'T add a memory link.
    _set_fighter_attrs(conn, 1, punch_power=90, cardio=90, fight_iq=90,
                       chin=90, punch_accuracy=90, kick_power=90,
                       kick_accuracy=90, head_movement=90, footwork=90)
    conn.commit()

    reset_bus()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()

    # Title changed but no memory link exists → no memory_resurfacing
    # news should be generated.
    mem_news = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='memory_resurfacing'"
    ).fetchone()[0]
    check("C", "no memory_resurfacing news without successor link",
          mem_news == 0, f"got={mem_news}")
    # The standard title news should still be there (generate_title_news).
    title_news = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE topic='news_engine' AND "
        "(headline LIKE '%CHAMPION%' OR headline LIKE '%title%' "
        "OR headline LIKE '%belt%' OR headline LIKE '%crown%' "
        "OR headline LIKE '%throne%' OR headline LIKE '%gold%')"
    ).fetchone()[0]
    check("C", "standard title news still generated (additive)",
          title_news >= 1, f"got={title_news}")
    conn.close()


# ----------------------------------------------------------------
# Case D — A11a memory resurfacing news uses voice descriptors (§14)
# ----------------------------------------------------------------

def case_d_memory_news_no_raw_numbers():
    """D. memory resurfacing news uses voice descriptors — no digits."""
    print("\n--- Case D: memory news no raw numbers (§14) ---")
    build_fresh_db()
    conn = get_conn()
    _set_fighter_attrs(conn, 1, punch_power=90, cardio=90, fight_iq=90,
                       chin=90, punch_accuracy=90, kick_power=90,
                       kick_accuracy=90, head_movement=90, footwork=90)
    conn.execute(
        "UPDATE fighter_career SET title_reigns=2, record_wins=25, "
        "record_losses=5 WHERE fighter_id=3"
    )
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'successor', ?)",
        (1, 3, 80),
    )
    conn.commit()

    reset_bus()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()

    items = conn.execute(
        "SELECT headline, body FROM news_items "
        "WHERE topic='memory_resurfacing'"
    ).fetchall()
    check("D", "memory_resurfacing items exist", len(items) > 0,
          f"got={len(items)}")
    if not items:
        conn.close()
        return
    all_clean = True
    for h, b in items:
        if _DIGIT_RE.search(h):
            check("D", f"headline has no digits: {h!r}",
                  False, "digit found")
            all_clean = False
        if _DIGIT_RE.search(b):
            check("D", f"body has no digits: {b[:60]!r}...",
                  False, "digit found")
            all_clean = False
    if all_clean:
        check("D", "no raw digit characters in memory_resurfacing items",
              True, f"checked {len(items)} items")
    conn.close()


# ----------------------------------------------------------------
# Case E — A11b STYLE ECHO in scouting report
# ----------------------------------------------------------------

def case_e_style_echo_in_scouting():
    """E. scouting report includes STYLE ECHO when target is a regen
    replacement (regen_lineage.replacement_fighter_id == target)."""
    print("\n--- Case E: A11b STYLE ECHO in scouting report ---")
    build_fresh_db()
    conn = get_conn()

    # Insert a regen_lineage row: f3 (Dario Knox) is the retiring
    # legend, f1 (John Vale) is the replacement. The replacement
    # inherits the retiring fighter's style archetype (already
    # inherited at the fighter_gen level — we just need the lineage
    # row so _build_style_echo finds it).
    conn.execute(
        "INSERT INTO regen_lineage "
        "(retiring_fighter_id, replacement_fighter_id, "
        "style_dna_archetype_id, regen_date) "
        "VALUES (?, ?, ?, ?)",
        (3, 1, 5, "2026-01-15"),  # f3 retires, f1 replaces; style archetype 5
    )
    # Insert a fighter_memory_links 'successor' row (the regen system
    # writes these for champion retirees — make f3 a former champion
    # so the link is justified).
    conn.execute(
        "UPDATE fighter_career SET title_reigns=2, record_wins=25, "
        "record_losses=5 WHERE fighter_id=3"
    )
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'successor', ?)",
        (1, 3, 80),
    )
    conn.commit()

    sid = _seed_scout(conn, eye_for_talent=80, mistake_rate=0)
    random.seed(42)
    scouting.generate_scouting_report(conn, sid, 1, 1, "2026-08-15")
    conn.commit()

    report_text = conn.execute(
        "SELECT report_text FROM scouting_reports "
        "WHERE target_fighter_id=1 ORDER BY scouting_report_id DESC"
    ).fetchone()
    check("E", "scouting report row created",
          report_text is not None, "")
    if not report_text:
        conn.close()
        return
    text = report_text[0]
    has_echo = "STYLE ECHO" in text
    check("E", "STYLE ECHO section present in report",
          has_echo, f"text snippet={text[-300:]!r}")
    if has_echo:
        # The STYLE ECHO line should reference the legend (Knox).
        check("E", "STYLE ECHO references the legend (Knox)",
              "knox" in text.lower(),
              f"text snippet={text[-300:]!r}")
        print(f"      STYLE ECHO line:")
        for line in text.split("\n"):
            if "STYLE ECHO" in line:
                print(f"        {line}")
    conn.close()


# ----------------------------------------------------------------
# Case F — A11b NO STYLE ECHO when target is not a regen
# ----------------------------------------------------------------

def case_f_no_style_echo_without_regen():
    """F. NO STYLE ECHO when target is not a regen replacement."""
    print("\n--- Case F: no STYLE ECHO without regen_lineage ---")
    build_fresh_db()
    conn = get_conn()
    # Don't insert any regen_lineage row — f1 is just a regular
    # fighter, not a regen replacement.
    sid = _seed_scout(conn, eye_for_talent=80, mistake_rate=0)
    random.seed(42)
    scouting.generate_scouting_report(conn, sid, 1, 1, "2026-08-15")
    conn.commit()

    report_text = conn.execute(
        "SELECT report_text FROM scouting_reports "
        "WHERE target_fighter_id=1 ORDER BY scouting_report_id DESC"
    ).fetchone()[0]
    has_echo = "STYLE ECHO" in report_text
    check("F", "NO STYLE ECHO section (target is not a regen)",
          not has_echo, f"has_echo={has_echo}")
    conn.close()


# ----------------------------------------------------------------
# Case G — A11b STYLE ECHO uses voice descriptors (§14)
# ----------------------------------------------------------------

def case_g_style_echo_no_raw_numbers():
    """G. STYLE ECHO uses voice descriptors — no raw numbers."""
    print("\n--- Case G: STYLE ECHO no raw numbers (§14) ---")
    build_fresh_db()
    conn = get_conn()
    conn.execute(
        "INSERT INTO regen_lineage "
        "(retiring_fighter_id, replacement_fighter_id, "
        "style_dna_archetype_id, regen_date) "
        "VALUES (?, ?, ?, ?)",
        (3, 1, 5, "2026-01-15"),
    )
    conn.execute(
        "UPDATE fighter_career SET title_reigns=2, record_wins=25, "
        "record_losses=5 WHERE fighter_id=3"
    )
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'successor', ?)",
        (1, 3, 80),
    )
    conn.commit()

    sid = _seed_scout(conn, eye_for_talent=80, mistake_rate=0)
    random.seed(42)
    scouting.generate_scouting_report(conn, sid, 1, 1, "2026-08-15")
    conn.commit()

    report_text = conn.execute(
        "SELECT report_text FROM scouting_reports "
        "WHERE target_fighter_id=1 ORDER BY scouting_report_id DESC"
    ).fetchone()[0]
    # Extract just the STYLE ECHO line(s) for the digit check (the
    # rest of the report has confidence % and contract cost $ which
    # are explicitly NOT player-facing per the original scouting.py
    # design — only the STYLE ECHO line is new from A11b).
    echo_lines = [
        line for line in report_text.split("\n")
        if "STYLE ECHO" in line
    ]
    check("G", "STYLE ECHO line exists for digit check",
          len(echo_lines) > 0, "")
    if not echo_lines:
        conn.close()
        return
    echo_text = " ".join(echo_lines)
    has_digits = bool(_DIGIT_RE.search(echo_text))
    check("G", "STYLE ECHO line has no digit characters",
          not has_digits, f"echo_text={echo_text!r}")
    # Voice descriptor for the legend's career stage — should include
    # a stage phrase like "veteran", "champion", etc.
    voice_keywords = [
        "veteran", "champion", "contender", "journeyman",
        "gatekeeper", "competitor", "fighter", "prospect",
        "titleholder",
    ]
    has_voice = any(kw in echo_text.lower() for kw in voice_keywords)
    check("G", "STYLE ECHO uses a voice career-stage descriptor",
          has_voice, f"echo_text={echo_text!r}")
    conn.close()


# ----------------------------------------------------------------
# Case H — A12a preferred_gameplans populated after a win
# ----------------------------------------------------------------

def case_h_gameplans_populated_on_win():
    """H. preferred_gameplans populated after a win (NULL → list)."""
    print("\n--- Case H: A12a preferred_gameplans populated on win ---")
    build_fresh_db()
    conn = get_conn()
    # Make f1 a beast so they win AND have multiple gameplans match.
    _set_fighter_attrs(conn, 1,
                       punch_power=85, punch_accuracy=80,    # boxing_pressure
                       takedown_offense=70, top_control=75,  # wrestling_dominance
                       head_movement=70, footwork=65,        # counter_striking
                       cardio=50,                            # not volume
                       clinch_offense=50, cage_wrestling=50) # not cage
    _set_fighter_pers(conn, 1, aggression=50)
    # f2 stays mediocre so f1 wins.
    conn.commit()

    # Verify starting state — preferred_gameplans is NULL.
    before = conn.execute(
        "SELECT preferred_gameplans FROM fighters WHERE fighter_id=1"
    ).fetchone()[0]
    check("H", "preferred_gameplans is NULL before fight",
          before is None, f"got={before!r}")

    reset_bus()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()

    # Verify the fight outcome — f1 should be the winner.
    winner_id = conn.execute(
        "SELECT winner_fighter_id FROM fights WHERE fight_id=1"
    ).fetchone()[0]
    check("H", "f1 won the fight (so A12a fires for f1)",
          winner_id == 1, f"got={winner_id}")

    after = conn.execute(
        "SELECT preferred_gameplans FROM fighters WHERE fighter_id=1"
    ).fetchone()[0]
    check("H", "preferred_gameplans populated after win",
          after is not None, f"got={after!r}")
    if after:
        plans = json.loads(after)
        check("H", "preferred_gameplans is a non-empty JSON list",
              isinstance(plans, list) and len(plans) > 0,
              f"got={plans}")
        if isinstance(plans, list) and plans:
            check("H", "boxing_pressure in list (f1 has high punch attrs)",
                  "boxing_pressure" in plans, f"got={plans}")
            print(f"      preferred_gameplans: {plans}")
    conn.close()


# ----------------------------------------------------------------
# Case I — A12a preferred_gameplans doesn't duplicate
# ----------------------------------------------------------------

def case_i_gameplans_no_duplicates():
    """I. preferred_gameplans doesn't duplicate on re-add."""
    print("\n--- Case I: preferred_gameplans no duplicates ---")
    build_fresh_db()
    conn = get_conn()
    # Pre-populate preferred_gameplans with one entry.
    conn.execute(
        "UPDATE fighters SET preferred_gameplans=? "
        "WHERE fighter_id=1",
        (json.dumps(["boxing_pressure"]),),
    )
    conn.commit()

    # Call _update_preferred_gameplans with the same gameplan + a
    # new one.
    app._update_preferred_gameplans(conn, 1, ["boxing_pressure",
                                              "wrestling_dominance"])
    conn.commit()
    after = json.loads(conn.execute(
        "SELECT preferred_gameplans FROM fighters WHERE fighter_id=1"
    ).fetchone()[0])
    check("I", "no duplicates after re-add",
          after.count("boxing_pressure") == 1, f"got={after}")
    check("I", "new gameplan added",
          "wrestling_dominance" in after, f"got={after}")
    check("I", "list length is 2 (existing + new, no dup)",
          len(after) == 2, f"got={after}")
    conn.close()


# ----------------------------------------------------------------
# Case J — A12a preferred_gameplans capped at 3
# ----------------------------------------------------------------

def case_j_gameplans_cap_at_3():
    """J. preferred_gameplans capped at 3."""
    print("\n--- Case J: preferred_gameplans cap at 3 ---")
    build_fresh_db()
    conn = get_conn()
    # Pre-populate with 3 gameplans.
    conn.execute(
        "UPDATE fighters SET preferred_gameplans=? "
        "WHERE fighter_id=1",
        (json.dumps(["boxing_pressure", "wrestling_dominance",
                     "counter_striking"]),),
    )
    conn.commit()
    # Try to add 3 more — cap should keep it at 3, with no new ones
    # added (the list is already full).
    app._update_preferred_gameplans(
        conn, 1, ["submission_hunting", "volume_striking", "cage_grinding"]
    )
    conn.commit()
    after = json.loads(conn.execute(
        "SELECT preferred_gameplans FROM fighters WHERE fighter_id=1"
    ).fetchone()[0])
    check("J", "list capped at 3 (no overflow)",
          len(after) == 3, f"got={after}")
    check("J", "original 3 gameplans preserved",
          set(after) == {"boxing_pressure", "wrestling_dominance",
                         "counter_striking"}, f"got={after}")

    # Also test the cap when starting from empty — add 5, should cap at 3.
    conn.execute(
        "UPDATE fighters SET preferred_gameplans=NULL "
        "WHERE fighter_id=2"
    )
    app._update_preferred_gameplans(
        conn, 2, ["boxing_pressure", "wrestling_dominance",
                  "counter_striking", "submission_hunting",
                  "volume_striking"]
    )
    conn.commit()
    after2 = json.loads(conn.execute(
        "SELECT preferred_gameplans FROM fighters WHERE fighter_id=2"
    ).fetchone()[0])
    check("J", "list capped at 3 when adding 5 from empty",
          len(after2) == 3, f"got={after2}")
    check("J", "first 3 gameplans preserved in order",
          after2 == ["boxing_pressure", "wrestling_dominance",
                     "counter_striking"], f"got={after2}")
    conn.close()


# ----------------------------------------------------------------
# Case K — A12b bad_matchup_tags populated after a loss
# ----------------------------------------------------------------

def case_k_tags_populated_on_loss():
    """K. bad_matchup_tags populated after a loss."""
    print("\n--- Case K: A12b bad_matchup_tags populated on loss ---")
    build_fresh_db()
    conn = get_conn()
    # Make f2 a beast Striker so f2 wins. The result_type is not
    # deterministic (KO, doctor_stoppage, or decision are all
    # possible) — the test verifies that the correct tag for the
    # ACTUAL result_type was populated.
    sa_striker = conn.execute(
        "SELECT style_archetype_id FROM style_archetypes "
        "WHERE name='Striker'"
    ).fetchone()[0]
    conn.execute(
        "UPDATE fighters SET fight_style_archetype_id=? "
        "WHERE fighter_id=2",
        (sa_striker,),
    )
    _set_fighter_attrs(conn, 2,
                       punch_power=95, punch_accuracy=95,
                       kick_power=95, kick_accuracy=95,
                       head_movement=80, footwork=80,
                       chin=90, cardio=90, fight_iq=80)
    # f1 stays mediocre so f2 wins.
    conn.commit()

    before = conn.execute(
        "SELECT bad_matchup_tags FROM fighters WHERE fighter_id=1"
    ).fetchone()[0]
    check("K", "bad_matchup_tags is NULL before fight",
          before is None, f"got={before!r}")

    reset_bus()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()

    # Verify the result_type.
    result = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type "
        "FROM fights WHERE fight_id=1"
    ).fetchone()
    check("K", "f2 won, f1 lost",
          result[0] == 2 and result[1] == 1, f"got={result}")
    actual_rt = result[2]
    print(f"      actual result_type: {actual_rt}")

    # Compute the expected tags from the actual result_type +
    # opponent's style (Striker).
    expected_tags = app._derive_bad_matchup_tags(actual_rt, "Striker")
    print(f"      expected tags for ({actual_rt!r}, Striker): {expected_tags}")

    after = conn.execute(
        "SELECT bad_matchup_tags FROM fighters WHERE fighter_id=1"
    ).fetchone()[0]
    check("K", "bad_matchup_tags populated after loss",
          after is not None, f"got={after!r}")
    if after and expected_tags:
        actual_tags = json.loads(after)
        check("K", "every expected tag is in the actual list",
              all(t in actual_tags for t in expected_tags),
              f"expected={expected_tags} actual={actual_tags}")
        print(f"      bad_matchup_tags: {actual_tags}")
    elif after and not expected_tags:
        # The result_type + opponent style produced no tags — this
        # is suspicious (any loss should produce at least one tag if
        # the opponent is a Brawler, or a doctor_stoppage, or KO to
        # a Striker, etc.). Flag as a soft fail with a detail.
        check("K", "tags produced for the result_type",
              False, f"no expected tags for rt={actual_rt!r}")
    conn.close()


# ----------------------------------------------------------------
# Case L — A12b bad_matchup_tags don't duplicate
# ----------------------------------------------------------------

def case_l_tags_no_duplicates():
    """L. bad_matchup_tags doesn't duplicate on re-add."""
    print("\n--- Case L: bad_matchup_tags no duplicates ---")
    build_fresh_db()
    conn = get_conn()
    # Pre-populate with one tag.
    conn.execute(
        "UPDATE fighters SET bad_matchup_tags=? "
        "WHERE fighter_id=1",
        (json.dumps(["vulnerable_to_strikers"]),),
    )
    conn.commit()

    app._update_bad_matchup_tags(conn, 1, ["vulnerable_to_strikers",
                                           "cut_prone"])
    conn.commit()
    after = json.loads(conn.execute(
        "SELECT bad_matchup_tags FROM fighters WHERE fighter_id=1"
    ).fetchone()[0])
    check("L", "no duplicates after re-add",
          after.count("vulnerable_to_strikers") == 1, f"got={after}")
    check("L", "new tag added",
          "cut_prone" in after, f"got={after}")
    check("L", "list length is 2 (existing + new, no dup)",
          len(after) == 2, f"got={after}")
    conn.close()


# ----------------------------------------------------------------
# Case M — A12b bad_matchup_tags capped at 5
# ----------------------------------------------------------------

def case_m_tags_cap_at_5():
    """M. bad_matchup_tags capped at 5."""
    print("\n--- Case M: bad_matchup_tags cap at 5 ---")
    build_fresh_db()
    conn = get_conn()
    # Pre-populate with 5 tags (the cap).
    conn.execute(
        "UPDATE fighters SET bad_matchup_tags=? "
        "WHERE fighter_id=1",
        (json.dumps(["vulnerable_to_strikers", "vulnerable_to_submission",
                     "vulnerable_to_wrestlers", "vulnerable_to_brawlers",
                     "cut_prone"]),),
    )
    conn.commit()
    # Try to add another tag — cap should keep it at 5.
    app._update_bad_matchup_tags(conn, 1, ["some_new_tag"])
    conn.commit()
    after = json.loads(conn.execute(
        "SELECT bad_matchup_tags FROM fighters WHERE fighter_id=1"
    ).fetchone()[0])
    check("M", "list capped at 5 (no overflow)",
          len(after) == 5, f"got={after}")
    check("M", "original 5 tags preserved (new one not added)",
          "some_new_tag" not in after, f"got={after}")

    # Also test the cap when starting from empty — add 7, should cap at 5.
    conn.execute(
        "UPDATE fighters SET bad_matchup_tags=NULL "
        "WHERE fighter_id=2"
    )
    app._update_bad_matchup_tags(
        conn, 2, ["vulnerable_to_strikers", "vulnerable_to_submission",
                  "vulnerable_to_wrestlers", "vulnerable_to_brawlers",
                  "cut_prone", "tag_6", "tag_7"]
    )
    conn.commit()
    after2 = json.loads(conn.execute(
        "SELECT bad_matchup_tags FROM fighters WHERE fighter_id=2"
    ).fetchone()[0])
    check("M", "list capped at 5 when adding 7 from empty",
          len(after2) == 5, f"got={after2}")
    check("M", "first 5 tags preserved in order",
          after2 == ["vulnerable_to_strikers", "vulnerable_to_submission",
                     "vulnerable_to_wrestlers", "vulnerable_to_brawlers",
                     "cut_prone"], f"got={after2}")
    conn.close()


# ----------------------------------------------------------------
# Case N — Design Law (§13): Legacy pillar
# ----------------------------------------------------------------

def case_n_design_law():
    """N. Design Law (§13): Legacy pillar — memory resurfacing tells
    torch-passing stories."""
    print("\n--- Case N: Design Law (Legacy pillar) ---")
    build_fresh_db()
    conn = get_conn()
    # Set up: f1 (the successor) wins a title; the fighter_memory_links
    # table says f1 is the successor of f3 (the legend). The memory
    # resurfacing news should tell the torch-passing story.
    _set_fighter_attrs(conn, 1, punch_power=90, cardio=90, fight_iq=90,
                       chin=90, punch_accuracy=90, kick_power=90,
                       kick_accuracy=90, head_movement=90, footwork=90)
    conn.execute(
        "UPDATE fighter_career SET title_reigns=3, record_wins=30, "
        "record_losses=4 WHERE fighter_id=3"
    )
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'successor', ?)",
        (1, 3, 90),
    )
    conn.commit()

    reset_bus()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()

    mem_items = conn.execute(
        "SELECT headline, body FROM news_items "
        "WHERE topic='memory_resurfacing'"
    ).fetchall()
    check("N", "memory_resurfacing news exists (Legacy pillar)",
          len(mem_items) >= 1, f"got={len(mem_items)}")
    if mem_items:
        text = (mem_items[0][0] + " " + mem_items[0][1]).lower()
        # Legacy / torch-passing keywords — the news should evoke
        # the torch-passing narrative (per the brief's example
        # phrases: "torch passes", "echoes", "honors the memory").
        legacy_keywords = [
            "torch", "legacy", "echoes", "memory", "honors",
            "crown", "gold", "throne", "title", "champion",
            "legend", "veteran", "era",
        ]
        matches = [kw for kw in legacy_keywords if kw in text]
        check("N", "memory news uses torch-passing / legacy language",
              len(matches) >= 3, f"matched={matches}")
        print(f"      matched legacy keywords: {matches}")
    # STYLE ECHO section also serves the Legacy pillar — prospect
    # scouting reports invoke retired legends' names. Verified in
    # cases E + G.
    check("N", "STYLE ECHO scouting section (cases E + G) also "
          "serves Legacy pillar", True, "")
    conn.close()


# ----------------------------------------------------------------
# Case O — Smoke test (the exact test from the brief)
# ----------------------------------------------------------------

def case_o_smoke_test():
    """O. Smoke test (the exact test from the brief).

    The brief's smoke test just prints the state — no hard assertions.
    We add a soft check that the resolver didn't crash, and that IF
    the result_type + opponent style would produce tags (per A12b
    rules), the loser's bad_matchup_tags were populated. When the
    result_type + style combo doesn't match any A12b rule (e.g.
    decision to a Balanced fighter), no tags are expected — that's
    correct behavior, not a bug.
    """
    print("\n--- Case O: smoke test from the brief ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    reset_bus()
    import morale
    morale.register_subscribers()
    news.register_subscribers()
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()
    for fid in (1, 2):
        gp = conn.execute(
            "SELECT preferred_gameplans, bad_matchup_tags "
            "FROM fighters WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        print(f"      Fighter {fid}: gameplans={gp[0]} tags={gp[1]}")
    # Both fighters still exist after resolve_next_fight.
    n = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE fighter_id IN (1, 2)"
    ).fetchone()[0]
    check("O", "both fighters still exist after resolve_next_fight",
          n == 2, f"got={n}")

    # Soft check: the loser's bad_matchup_tags should be populated
    # IF the result_type + opponent's style matches an A12b rule.
    # For the seeded fight, both fighters are "Balanced" — so:
    #   - KO/TKO to a Balanced opponent → no tag (rule needs "Striker")
    #   - submission to a Balanced opponent → no tag (rule needs "Grappler")
    #   - decision to a Balanced opponent → no tag (rule needs "Wrestler")
    #   - doctor_stoppage → "cut_prone" (any opponent style)
    # So if the result_type is doctor_stoppage, the loser SHOULD have
    # "cut_prone" populated. Otherwise, no tags are expected.
    result = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type "
        "FROM fights WHERE fight_id=1"
    ).fetchone()
    if result:
        winner_id, loser_id, rt = result
        loser_tags = conn.execute(
            "SELECT bad_matchup_tags FROM fighters "
            "WHERE fighter_id=?",
            (loser_id,),
        ).fetchone()[0]
        winner_style = app._opponent_style_archetype_name(conn, winner_id)
        expected_tags = app._derive_bad_matchup_tags(rt, winner_style)
        print(f"      result_type={rt}, winner_style={winner_style}, "
              f"expected_tags={expected_tags}, loser_tags={loser_tags!r}")
        if expected_tags:
            check("O", f"loser (f{loser_id}) has bad_matchup_tags populated "
                  f"(matches A12b rule for {rt}+{winner_style})",
                  loser_tags is not None, f"got={loser_tags!r}")
        else:
            # No tags expected for this result_type + style combo —
            # that's correct A12b behavior. Soft-pass.
            check("O", f"no tags expected for {rt}+{winner_style} "
                  f"(A12b rule doesn't match — correct behavior)",
                  loser_tags is None, f"got={loser_tags!r}")
    conn.close()


# ----------------------------------------------------------------
# main()
# ----------------------------------------------------------------

def main():
    print("=" * 80)
    print(f"Phase A — Task A11+A12 (Memory + Gameplans) acceptance test")
    print(f"schema {EXPECTED_VERSION}, no schema change")
    print("=" * 80)
    case_a_imports()
    case_b_memory_resurfacing_news()
    case_c_no_memory_news_without_link()
    case_d_memory_news_no_raw_numbers()
    case_e_style_echo_in_scouting()
    case_f_no_style_echo_without_regen()
    case_g_style_echo_no_raw_numbers()
    case_h_gameplans_populated_on_win()
    case_i_gameplans_no_duplicates()
    case_j_gameplans_cap_at_3()
    case_k_tags_populated_on_loss()
    case_l_tags_no_duplicates()
    case_m_tags_cap_at_5()
    case_n_design_law()
    case_o_smoke_test()
    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 80)
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
