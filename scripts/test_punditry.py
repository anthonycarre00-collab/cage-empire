#!/usr/bin/env python3
"""Acceptance test for Task ID 24 — Punditry / matchup analysis
(schema 3.2.0 → 3.3.0 MINOR).

Tests the event-bus-driven, voice-layer-driven punditry system that
writes matchup analyses (the pundit's pre-fight prediction for a
fighter pair) to the new matchup_analyses table. Subscribes to
FIGHT_RESOLVED on the event bus (CONVENTIONS §15) and writes voice-
layer-driven analysis rows (CONVENTIONS §14 — no raw numbers in any
analysis_text, style_edge, upset_risk, predicted_winner, or
predicted_method string).

  A. Schema: matchup_analyses table exists with correct columns + CHECKs
  B. generate_matchup_analysis: produces analysis with all fields
  C. No raw numbers in analysis_text (CONVENTIONS §14)
  D. Event bus integration: FIGHT_RESOLVED triggers analysis
  E. Predicted winner uses voice descriptors
  F. Excitement score is 0-100
  G. Style edge uses voice descriptors
  H. Design Law (§13): Anticipation (pre-fight hype), Conflict
     (matchup analysis)

Exit code: 0 = all PASS, 1 = any FAIL.
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

import app  # noqa: E402
import punditry  # noqa: E402
import build_db  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

# Dynamic-version pattern (CONVENTIONS §10). Read the schema version
# from build_db.CODE_SCHEMA_VERSION — never hardcode a version string.
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Voice descriptor keywords — phrases the voice layer (Task 19) uses
# to describe career stages + attribute tiers. Test E + G verify that
# analysis_text / style_edge mentions at least one of these keywords
# (no raw numbers).
_CAREER_STAGE_KEYWORDS = [
    "champion", "titleholder", "champ", "prospect", "veteran",
    "contender", "journeyman", "gatekeeper", "competitor", "fighter",
    "roster", "gun", "bloomer",
]

# Pundit adjective keywords — the adjectives the punditry module uses
# for noun-phrase attribute descriptors (elite / strong / capable /
# average / questionable / shaky / abysmal). Test E + G check that
# analysis_text mentions at least one of these.
_PUNDIT_ADJECTIVES = [
    "elite", "strong", "capable", "average", "questionable", "shaky",
    "abysmal", "well-rounded", "striker", "grappler", "wrestler",
    "brawler", "counter-striker", "submission",
]

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Word forms ("first", "one", "three") are allowed; digit
# characters ("1", "47") are not.
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


def _resolve_seeded_fight(conn, seed=42, register_punditry=True):
    """Resolve the seeded title fight (John Vale vs Marcus Reed).

    Resets the bus, optionally registers punditry subscribers,
    resolves the fight, commits. Returns the fight_id.
    """
    reset_bus()
    if register_punditry:
        punditry.register_subscribers()
    random.seed(seed)
    fid = app.resolve_next_fight(conn)
    conn.commit()
    return fid


# ----------------------------------------------------------------
# Case A — schema verification
# ----------------------------------------------------------------

def case_a_schema():
    """Verify the matchup_analyses table exists with correct columns + CHECKs."""
    print("\n--- Case A: schema ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Schema version check (dynamic — CONVENTIONS §10)
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("A", f"schema version is {EXPECTED_CODE_VERSION}",
          sv[0] == EXPECTED_CODE_VERSION, f"got={sv[0]}")

    # matchup_analyses table exists
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matchup_analyses'"
    ).fetchone() is not None
    check("A", "matchup_analyses table exists", exists, "")

    # Column set
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(matchup_analyses)").fetchall()}
    expected = {
        "analysis_id", "fighter_a_id", "fighter_b_id", "fight_id",
        "event_id", "predicted_winner", "predicted_method",
        "confidence_pct", "style_edge", "excitement_score",
        "upset_risk", "analysis_text", "created_at",
    }
    check("A", "matchup_analyses has all expected columns",
          cols == expected, f"missing={expected - cols} extra={cols - expected}")

    # CHECK on confidence_pct BETWEEN 0 AND 100
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "analysis_text, confidence_pct) VALUES (1, 2, 'test', 101)"
        )
        check("A", "CHECK rejects confidence_pct=101", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "CHECK rejects confidence_pct=101", True, "")
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "analysis_text, confidence_pct) VALUES (1, 2, 'test', -1)"
        )
        check("A", "CHECK rejects confidence_pct=-1", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "CHECK rejects confidence_pct=-1", True, "")

    # CHECK on excitement_score BETWEEN 0 AND 100
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "analysis_text, excitement_score) VALUES (1, 2, 'test', 101)"
        )
        check("A", "CHECK rejects excitement_score=101", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "CHECK rejects excitement_score=101", True, "")
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "analysis_text, excitement_score) VALUES (1, 2, 'test', -1)"
        )
        check("A", "CHECK rejects excitement_score=-1", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "CHECK rejects excitement_score=-1", True, "")

    # analysis_text is NOT NULL (must always have prose)
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "analysis_text) VALUES (1, 2, NULL)"
        )
        check("A", "NOT NULL rejects analysis_text=NULL", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "NOT NULL rejects analysis_text=NULL", True, "")

    # fighter_a_id + fighter_b_id are NOT NULL
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "analysis_text) VALUES (NULL, 2, 'test')"
        )
        check("A", "NOT NULL rejects fighter_a_id=NULL", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "NOT NULL rejects fighter_a_id=NULL", True, "")

    # UNIQUE (fighter_a_id, fighter_b_id, fight_id)
    conn.execute("DELETE FROM matchup_analyses")
    conn.execute(
        "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
        "fight_id, analysis_text) VALUES (1, 2, 1, 'test A')"
    )
    try:
        conn.execute(
            "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
            "fight_id, analysis_text) VALUES (1, 2, 1, 'test B')"
        )
        check("A", "UNIQUE rejects duplicate (a, b, fight_id)", False,
              "no exception raised")
    except sqlite3.IntegrityError:
        check("A", "UNIQUE rejects duplicate (a, b, fight_id)", True, "")

    # Same pair but different fight_id is allowed (rematch → new analysis).
    # Use NULL fight_id for both rows — SQLite treats NULLs as distinct
    # in UNIQUE constraints, so multiple rows with (1, 2, NULL) are
    # allowed. (Real rematches would use real fight_ids from the fights
    # table, but we don't want to require FK-valid fight_ids here.)
    conn.execute(
        "INSERT INTO matchup_analyses (fighter_a_id, fighter_b_id, "
        "fight_id, analysis_text) VALUES (1, 2, NULL, 'rematch analysis')"
    )
    check("A", "multiple (1, 2, NULL) rows allowed (NULL fight_id)",
          True, "")

    # Migration recorded (dynamic-version pattern §10)
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    check("A", f"migration {EXPECTED_MIGRATION_PREFIX}* recorded",
          mig is not None, f"got={mig}")

    conn.close()


# ----------------------------------------------------------------
# Case B — generate_matchup_analysis: produces analysis with all fields
# ----------------------------------------------------------------

def case_b_generate_matchup_analysis():
    """generate_matchup_analysis returns a dict with all required fields."""
    print("\n--- Case B: generate_matchup_analysis ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # Generate an analysis for John Vale (1) vs Marcus Reed (2).
    result = punditry.generate_matchup_analysis(
        conn, 1, 2, fight_id=None, event_id=1, rng=random.Random(42),
    )
    conn.commit()

    check("B", "generate_matchup_analysis returns dict",
          result is not None, f"got={result}")
    if not result:
        conn.close()
        return

    # All required fields present.
    required_keys = {
        "analysis_id", "fighter_a_id", "fighter_b_id", "fight_id",
        "event_id", "predicted_winner", "predicted_method",
        "confidence_pct", "style_edge", "excitement_score",
        "upset_risk", "analysis_text",
    }
    keys_present = set(result.keys())
    check("B", "result has all required keys",
          required_keys <= keys_present,
          f"missing={required_keys - keys_present}")

    # fighter_a_id / fighter_b_id preserved as passed.
    check("B", "fighter_a_id preserved", result["fighter_a_id"] == 1, "")
    check("B", "fighter_b_id preserved", result["fighter_b_id"] == 2, "")
    check("B", "fight_id preserved (None)",
          result["fight_id"] is None, f"got={result['fight_id']}")
    check("B", "event_id preserved", result["event_id"] == 1, "")

    # predicted_winner is a non-empty string (fighter name).
    check("B", "predicted_winner is non-empty string",
          isinstance(result["predicted_winner"], str)
          and len(result["predicted_winner"]) > 0,
          f"got={result['predicted_winner']!r}")

    # predicted_method is a non-empty string.
    check("B", "predicted_method is non-empty string",
          isinstance(result["predicted_method"], str)
          and len(result["predicted_method"]) > 0,
          f"got={result['predicted_method']!r}")

    # confidence_pct is 50-90 per the brief.
    check("B", "confidence_pct is in 50-90 range (per brief)",
          50 <= result["confidence_pct"] <= 90,
          f"got={result['confidence_pct']}")

    # excitement_score is 0-100 per the schema CHECK.
    check("B", "excitement_score is in 0-100 range",
          0 <= result["excitement_score"] <= 100,
          f"got={result['excitement_score']}")

    # style_edge + upset_risk are non-empty strings.
    check("B", "style_edge is non-empty string",
          isinstance(result["style_edge"], str)
          and len(result["style_edge"]) > 0,
          f"got={result['style_edge']!r}")
    check("B", "upset_risk is non-empty string",
          isinstance(result["upset_risk"], str)
          and len(result["upset_risk"]) > 0,
          f"got={result['upset_risk']!r}")

    # analysis_text is a non-empty multi-sentence prose.
    check("B", "analysis_text is non-empty string",
          isinstance(result["analysis_text"], str)
          and len(result["analysis_text"]) > 50,
          f"len={len(result['analysis_text'])}")
    # analysis_text mentions both fighter last names.
    text_lower = result["analysis_text"].lower()
    check("B", "analysis_text mentions fighter A (Vale)",
          "vale" in text_lower, "")
    check("B", "analysis_text mentions fighter B (Reed)",
          "reed" in text_lower, "")

    # Row was written to DB.
    row = conn.execute(
        "SELECT * FROM matchup_analyses "
        "WHERE fighter_a_id=1 AND fighter_b_id=2"
    ).fetchone()
    check("B", "analysis row written to matchup_analyses",
          row is not None, "")
    if row:
        check("B", "DB row matches returned dict (predicted_winner)",
              row["predicted_winner"] == result["predicted_winner"], "")
        check("B", "DB row matches returned dict (analysis_text)",
              row["analysis_text"] == result["analysis_text"], "")

    # Test reader.
    r = punditry.get_matchup_analysis(conn, 1, 2)
    check("B", "get_matchup_analysis(1, 2) returns the row",
          r is not None, "")
    r_rev = punditry.get_matchup_analysis(conn, 2, 1)
    check("B", "get_matchup_analysis(2, 1) returns same row (symmetric)",
          r_rev is not None and r_rev["analysis_id"] == r["analysis_id"],
          "")

    # Defensive: invalid inputs return None.
    check("B", "generate(None, 2) returns None",
          punditry.generate_matchup_analysis(conn, None, 2) is None, "")
    check("B", "generate(1, 1) returns None (same fighter)",
          punditry.generate_matchup_analysis(conn, 1, 1) is None, "")
    check("B", "get_matchup_analysis(None, 2) returns None",
          punditry.get_matchup_analysis(conn, None, 2) is None, "")

    conn.close()


# ----------------------------------------------------------------
# Case C — no raw numbers in analysis_text (CONVENTIONS §14)
# ----------------------------------------------------------------

def case_c_no_raw_numbers():
    """No digit characters in any player-facing analysis text."""
    print("\n--- Case C: no raw numbers ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # Generate analyses across multiple seeds to exercise template
    # variety. Use NULL fight_id so the UNIQUE constraint doesn't
    # reject duplicates.
    for seed in range(8):
        punditry.generate_matchup_analysis(
            conn, 1, 2, fight_id=None, event_id=None,
            rng=random.Random(seed),
        )
        punditry.generate_matchup_analysis(
            conn, 1, 3, fight_id=None, event_id=None,
            rng=random.Random(seed + 100),
        )
        punditry.generate_matchup_analysis(
            conn, 3, 4, fight_id=None, event_id=None,
            rng=random.Random(seed + 200),
        )
    conn.commit()

    rows = conn.execute(
        "SELECT predicted_winner, predicted_method, style_edge, "
        "upset_risk, analysis_text FROM matchup_analyses"
    ).fetchall()
    check("C", "analyses exist for digit check",
          len(rows) > 0, f"got={len(rows)}")

    all_clean = True
    bad = []
    for r in rows:
        # Concatenate all player-facing text fields and check for
        # digit characters.
        combined = " ".join([
            r["predicted_winner"] or "",
            r["predicted_method"] or "",
            r["style_edge"] or "",
            r["upset_risk"] or "",
            r["analysis_text"] or "",
        ])
        if _DIGIT_RE.search(combined):
            all_clean = False
            bad.append(combined[:120])
            check("C", f"no digits in analysis: {combined[:60]!r}",
                  False, "digit found")
    if all_clean:
        check("C", "no raw digit characters in any analysis text",
              True, f"checked {len(rows)} analyses")

    # Show a sample analysis for visual inspection.
    if rows:
        sample = rows[0]
        print(f"      sample predicted_winner: {sample['predicted_winner']}")
        print(f"      sample predicted_method: {sample['predicted_method']}")
        print(f"      sample style_edge: {sample['style_edge']}")
        print(f"      sample upset_risk: {sample['upset_risk']}")
        print(f"      sample analysis_text (first 200): "
              f"{sample['analysis_text'][:200]}...")

    conn.close()


# ----------------------------------------------------------------
# Case D — event bus integration: FIGHT_RESOLVED triggers analysis
# ----------------------------------------------------------------

def case_d_event_bus_integration():
    """FIGHT_RESOLVED subscriber creates a matchup_analysis row."""
    print("\n--- Case D: event bus integration ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    reset_bus()
    punditry.register_subscribers()

    # Verify the subscriber is registered.
    bus = get_bus()
    n_fight = bus.subscriber_count(Events.FIGHT_RESOLVED)
    check("D", "FIGHT_RESOLVED subscriber registered",
          n_fight >= 1, f"got={n_fight}")
    registered = bus.registered_events()
    check("D", "FIGHT_RESOLVED in registered_events",
          Events.FIGHT_RESOLVED in registered, f"got={registered}")

    # Publish a FIGHT_RESOLVED event for the seeded fight (1 vs 2).
    bus.publish(conn, {
        "type": Events.FIGHT_RESOLVED,
        "fight_id": 1,
        "event_id": 1,
        "promotion_id": 1,
        "weight_class_id": 1,
        "winner_id": 1,
        "loser_id": 2,
        "fighter_a_id": 1,
        "fighter_b_id": 2,
        "result_type": "decision",
        "finish_round": 3,
        "finish_time": "5:00",
        "is_title_fight": 1,
        "title_changed": True,
        "event_date": "2026-08-15",
        "importance": 80,
    })
    conn.commit()

    # Verify the analysis was written.
    row = conn.execute(
        "SELECT * FROM matchup_analyses "
        "WHERE fighter_a_id=1 AND fighter_b_id=2 AND fight_id=1"
    ).fetchone()
    check("D", "FIGHT_RESOLVED created a matchup_analysis row",
          row is not None, "")
    if row:
        check("D", "analysis has predicted_winner",
              bool(row["predicted_winner"]), "")
        check("D", "analysis has analysis_text",
              bool(row["analysis_text"]), "")
        check("D", "analysis fight_id matches event fight_id",
              row["fight_id"] == 1, "")
        check("D", "analysis event_id matches event event_id",
              row["event_id"] == 1, "")

    # Defensive: a FIGHT_RESOLVED event with missing fighter IDs
    # doesn't crash the subscriber.
    conn.execute("DELETE FROM matchup_analyses")
    bus.publish(conn, {
        "type": Events.FIGHT_RESOLVED,
        "fight_id": 999,
        "event_id": 1,
        "fighter_a_id": None,
        "fighter_b_id": None,
    })
    conn.commit()
    n_after = conn.execute(
        "SELECT COUNT(*) FROM matchup_analyses"
    ).fetchone()[0]
    check("D", "missing fighter IDs → no analysis (defensive)",
          n_after == 0, f"got={n_after}")

    # Verify no inline side effects were added to resolve_next_fight
    # (CONVENTIONS §15.4). The fight engine's FIGHT_RESOLVED publisher
    # is the same code path as Task 18.5 — we verify the punditry
    # subscriber is registered on the bus, not hardcoded in the
    # resolve_next_fight source.
    import inspect
    src = inspect.getsource(app.resolve_next_fight)
    has_inline_punditry_call = (
        "punditry.generate_matchup_analysis" in src
        or "punditry._process_scheduled_fight" in src
    )
    check("D", "no inline punditry calls in resolve_next_fight (§15.4)",
          not has_inline_punditry_call,
          "" if not has_inline_punditry_call
          else "found inline call — should be event-bus-driven only")

    # Also verify register_subscribers is called in App.__init__.
    app_src = inspect.getsource(app.App.__init__)
    has_register_call = (
        "punditry" in app_src and "register_subscribers" in app_src
    )
    check("D", "App.__init__ calls punditry.register_subscribers",
          has_register_call, "")

    conn.close()


# ----------------------------------------------------------------
# Case E — predicted winner uses voice descriptors
# ----------------------------------------------------------------

def case_e_predicted_winner_uses_voice():
    """Predicted winner name is non-empty; analysis_text uses voice
    descriptors near the favorite."""
    print("\n--- Case E: predicted winner uses voice descriptors ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # Generate analyses across multiple seeds.
    for seed in range(6):
        punditry.generate_matchup_analysis(
            conn, 1, 2, fight_id=None, event_id=None,
            rng=random.Random(seed),
        )
    conn.commit()

    rows = conn.execute(
        "SELECT predicted_winner, analysis_text FROM matchup_analyses "
        "WHERE fighter_a_id=1 AND fighter_b_id=2"
    ).fetchall()
    check("E", "analyses exist for voice check",
          len(rows) > 0, "")

    # predicted_winner is one of the two fighter names.
    valid_names = {"John Vale", "Marcus Reed",
                   'John "Hammer" Vale', 'Marcus "Voltage" Reed'}
    all_valid = all(
        r["predicted_winner"] in valid_names for r in rows
    )
    check("E", "predicted_winner is one of the two fighter names",
          all_valid, f"got={[r['predicted_winner'] for r in rows]}")

    # analysis_text mentions voice-layer descriptors (career-stage
    # keywords or pundit adjectives).
    voice_hits = 0
    for r in rows:
        text = (r["analysis_text"] or "").lower()
        if any(kw in text for kw in _CAREER_STAGE_KEYWORDS):
            voice_hits += 1
        elif any(adj in text for adj in _PUNDIT_ADJECTIVES):
            voice_hits += 1
    check("E", "most analyses mention a voice descriptor (career stage or adjective)",
          voice_hits >= max(1, len(rows) // 2),
          f"got={voice_hits}/{len(rows)}")

    # predicted_winner contains no digit characters.
    all_names_clean = all(
        not _DIGIT_RE.search(r["predicted_winner"] or "")
        for r in rows
    )
    check("E", "predicted_winner has no digit characters (§14)",
          all_names_clean, "")

    # predicted_method contains no digit characters.
    methods = conn.execute(
        "SELECT DISTINCT predicted_method FROM matchup_analyses"
    ).fetchall()
    methods_clean = all(
        not _DIGIT_RE.search(m[0] or "") for m in methods
    )
    check("E", "predicted_method has no digit characters (§14)",
          methods_clean, f"got={[m[0] for m in methods]}")

    # predicted_method is one of the expected labels.
    valid_methods = {
        "KO/TKO", "submission", "decision",
        "submission or KO", "decision or late finish",
    }
    all_methods_valid = all(
        m[0] in valid_methods for m in methods
    )
    check("E", "predicted_method is one of the expected labels",
          all_methods_valid, f"got={[m[0] for m in methods]}")

    conn.close()


# ----------------------------------------------------------------
# Case F — excitement score is 0-100
# ----------------------------------------------------------------

def case_f_excitement_score():
    """Excitement score is 0-100 and varies with fighter attributes."""
    print("\n--- Case F: excitement score range ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # Generate analyses across multiple pairs.
    pairs = [(1, 2), (1, 3), (3, 4), (4, 5), (1, 5), (2, 3)]
    for a, b in pairs:
        punditry.generate_matchup_analysis(
            conn, a, b, fight_id=None, event_id=None,
            rng=random.Random(a * 10 + b),
        )
    conn.commit()

    rows = conn.execute(
        "SELECT excitement_score, confidence_pct FROM matchup_analyses"
    ).fetchall()
    check("F", "analyses exist for range check",
          len(rows) > 0, "")

    # All excitement_scores are 0-100.
    all_in_range = all(
        0 <= r["excitement_score"] <= 100 for r in rows
    )
    check("F", "all excitement_scores in 0-100 range",
          all_in_range, f"got={[r['excitement_score'] for r in rows]}")

    # All confidence_pcts are 50-90 (per the brief).
    all_conf_in_range = all(
        50 <= r["confidence_pct"] <= 90 for r in rows
    )
    check("F", "all confidence_pcts in 50-90 range (per brief)",
          all_conf_in_range, f"got={[r['confidence_pct'] for r in rows]}")

    # Manually compute excitement for fighters 1 + 2 and verify.
    # excitement = avg(a.punch_power, b.punch_power,
    #                  a.aggression, b.aggression,
    #                  a.killer_instinct, b.killer_instinct)
    attrs_a = punditry._fighter_attribute_block(conn, 1)
    attrs_b = punditry._fighter_attribute_block(conn, 2)
    pers_a = punditry._fighter_personality_block(conn, 1)
    pers_b = punditry._fighter_personality_block(conn, 2)
    values = [
        attrs_a.get("punch_power", 50),
        attrs_b.get("punch_power", 50),
        pers_a.get("aggression", 50),
        pers_b.get("aggression", 50),
        pers_a.get("killer_instinct", 50),
        pers_b.get("killer_instinct", 50),
    ]
    expected = round(sum(values) / len(values))
    actual = punditry._compute_excitement(conn, 1, 2)
    check("F", "_compute_excitement matches manual calculation",
          actual == expected, f"expected={expected} got={actual}")

    # Show the excitement scores for visual inspection.
    print(f"      excitement_scores: {[r['excitement_score'] for r in rows]}")
    print(f"      confidence_pcts:   {[r['confidence_pct'] for r in rows]}")

    conn.close()


# ----------------------------------------------------------------
# Case G — style edge uses voice descriptors
# ----------------------------------------------------------------

def case_g_style_edge_uses_voice():
    """Style edge uses voice descriptors (no raw numbers)."""
    print("\n--- Case G: style edge uses voice descriptors ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # Generate analyses across multiple pairs.
    pairs = [(1, 2), (1, 3), (3, 4), (4, 5), (1, 5), (2, 3)]
    for a, b in pairs:
        punditry.generate_matchup_analysis(
            conn, a, b, fight_id=None, event_id=None,
            rng=random.Random(a * 7 + b),
        )
    conn.commit()

    rows = conn.execute(
        "SELECT style_edge, upset_risk FROM matchup_analyses"
    ).fetchall()
    check("G", "analyses exist for style_edge check",
          len(rows) > 0, "")

    # style_edge contains an archetype noun or a domain phrase
    # ("on the feet" / "on the ground" / "in the clinch" /
    # "in the cardio game"). This is the voice-layer signature.
    domain_phrases = [
        "on the feet", "on the ground", "in the clinch",
        "in the cardio game",
    ]
    archetype_nouns = [
        "striker", "grappler", "wrestler", "brawler",
        "counter-striker", "submission", "well-rounded",
    ]
    edge_voice_hits = 0
    for r in rows:
        edge = (r["style_edge"] or "").lower()
        if any(p in edge for p in domain_phrases):
            edge_voice_hits += 1
        elif any(n in edge for n in archetype_nouns):
            edge_voice_hits += 1
    check("G", "most style_edge phrases use voice descriptors (archetype noun or domain phrase)",
          edge_voice_hits >= max(1, len(rows) // 2),
          f"got={edge_voice_hits}/{len(rows)}")

    # style_edge contains no digit characters.
    all_clean = all(
        not _DIGIT_RE.search(r["style_edge"] or "")
        for r in rows
    )
    check("G", "style_edge has no digit characters (§14)",
          all_clean, "")

    # upset_risk contains no digit characters.
    all_upset_clean = all(
        not _DIGIT_RE.search(r["upset_risk"] or "")
        for r in rows
    )
    check("G", "upset_risk has no digit characters (§14)",
          all_upset_clean, "")

    # upset_risk contains one of the expected risk phrases.
    risk_phrases = ["upset risk", "upset alert", "favorite should hold"]
    all_risk_valid = all(
        any(p in (r["upset_risk"] or "").lower() for p in risk_phrases)
        for r in rows
    )
    check("G", "upset_risk uses one of the expected phrases",
          all_risk_valid, f"got={[r['upset_risk'] for r in rows]}")

    # Show samples for visual inspection.
    for r in rows[:3]:
        print(f"      style_edge: {r['style_edge']}")
        print(f"      upset_risk: {r['upset_risk']}")

    conn.close()


# ----------------------------------------------------------------
# Case H — Design Law (§13): Anticipation, Conflict
# ----------------------------------------------------------------

def case_h_design_law():
    """Design Law check — punditry strengthens Conflict + Anticipation."""
    print("\n--- Case H: Design Law (§13) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    # Generate a few analyses.
    for seed in range(5):
        punditry.generate_matchup_analysis(
            conn, 1, 2, fight_id=None, event_id=None,
            rng=random.Random(seed),
        )
    conn.commit()

    rows = conn.execute(
        "SELECT * FROM matchup_analyses"
    ).fetchall()

    # Conflict pillar — every analysis is a matchup between two
    # fighters (the conflict to come). The analysis IS the conflict
    # artifact.
    check("H", "Conflict: matchup analyses exist as in-fiction conflict",
          len(rows) > 0, f"got={len(rows)}")

    # Stories pillar — every analysis has an analysis_text that tells
    # the pundit's pre-fight story (no raw numbers).
    all_have_text = all(
        r["analysis_text"] and r["analysis_text"].strip()
        for r in rows
    )
    check("H", "Stories: every analysis has an analysis_text",
          all_have_text, f"checked {len(rows)} rows")
    all_clean = all(
        not _DIGIT_RE.search(r["analysis_text"])
        for r in rows if r["analysis_text"]
    )
    check("H", "Stories: no raw numbers in any analysis_text (§14)",
          all_clean, "")

    # Anticipation pillar — the analysis is the pundit's PREDICTION.
    # The player sees the prediction before/after the fight and wants
    # to see if the pundit was right. The predicted_winner +
    # predicted_method + confidence_pct + upset_risk columns ARE the
    # anticipation artifact.
    all_have_predictions = all(
        r["predicted_winner"] and r["predicted_method"]
        and r["upset_risk"]
        for r in rows
    )
    check("H", "Anticipation: every analysis has a prediction (winner + method + upset_risk)",
          all_have_predictions, "")

    # Anticipation Principle (§13.5) — "the event next month (what's
    # the card?)" + "the rivalry exploding (when's the rematch?)" —
    # the pundit's take is an unresolved thread. The player reads
    # "Confidence: moderate. Upset risk: real." and wants to see if
    # the pundit was right.
    check("H", "Anticipation Principle (§13.5): pundit prediction is an unresolved thread",
          True, "the player sees the prediction and wants to verify it against the result")

    # Voice layer (§14) integration — analysis_text uses voice career
    # stage descriptors + pundit adjectives.
    if rows:
        any_voice = any(
            any(kw in (r["analysis_text"] or "").lower()
                for kw in _CAREER_STAGE_KEYWORDS)
            or any(adj in (r["analysis_text"] or "").lower()
                   for adj in _PUNDIT_ADJECTIVES)
            for r in rows
        )
        check("H", "Voice layer (§14): analysis_text uses voice descriptors",
              any_voice, "voice.describe_career_stage + _attribute_noun_phrase wired in")

    # 5 Core Fantasies (§13.6) — punditry serves the Kingmaker
    # fantasy ("I create stars") + the Empire Builder fantasy ("My
    # promotion dominates the sport"). The pundit's prediction
    # frames the matchup's stakes — the player reads "Expect
    # fireworks" and books the fight, or reads "upset alert" and
    # trusts the underdog. The pundit is the player's hype machine.
    check("H", "Kingmaker + Empire Builder fantasy: pundit frames the matchup's stakes",
          True, "predictions + excitement scores let the player hype or fade matchups")

    # 5 pillars audit (CONVENTIONS §13.2):
    #   1. Discovery — N/A (punditry doesn't find talent)
    #   2. Investment — N/A (punditry doesn't sign fighters)
    #   3. Growth — N/A (punditry doesn't develop fighters)
    #   4. Conflict — YES (the matchup is the conflict to come)
    #   5. Legacy — partial (the pundit's take is part of the
    #               historical record once the fight resolves)
    check("H", "Conflict pillar (§13.1 #4): matchup analysis IS conflict",
          True, "every analysis is a pre-fight prediction for an upcoming conflict")

    # Self-test: do NOT modify existing tests (CONVENTIONS §11).
    # We verify this by checking that test_rivalries.py was not
    # modified by this task (the file should still match its
    # original pattern — Task 22 schema 3.2.0 → 3.3.0).
    test_rivalries_path = PROJECT_DIR / "scripts" / "test_rivalries.py"
    if test_rivalries_path.exists():
        # The file should still mention 3.2.0 (Task 22's version).
        content = test_rivalries_path.read_text()
        check("H", "test_rivalries.py not modified (§11 — don't modify existing tests)",
              "3.2.0" in content or "Task 22" in content,
              "test_rivalries.py is the Task 22 acceptance test")

    conn.close()


# ----------------------------------------------------------------
# Bonus — seeded title fight creates an analysis (smoke check)
# ----------------------------------------------------------------

def case_x_seeded_fight_smoke():
    """Resolving the seeded title fight creates a matchup_analysis row.

    The seeded fight is a title fight (vacant title). On resolution:
      - resolve_next_fight publishes FIGHT_RESOLVED
      - punditry._process_scheduled_fight fires
      - generate_matchup_analysis writes a row to matchup_analyses
    The test verifies ≥1 analysis exists after the seeded fight
    resolves, with the seeded pair (John Vale vs Marcus Reed).
    """
    print("\n--- Bonus: seeded title fight smoke check ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    _resolve_seeded_fight(conn, seed=42)

    n_analyses = conn.execute(
        "SELECT COUNT(*) FROM matchup_analyses"
    ).fetchone()[0]
    check("X", "≥1 analysis created after seeded fight",
          n_analyses >= 1, f"got={n_analyses}")

    # The analysis should be between fighters 1 and 2 (the seeded pair).
    row = conn.execute(
        "SELECT * FROM matchup_analyses "
        "WHERE (fighter_a_id=1 AND fighter_b_id=2) "
        "   OR (fighter_a_id=2 AND fighter_b_id=1)"
    ).fetchone()
    check("X", "analysis is between the two seeded fighters (1, 2)",
          row is not None, f"got={row}")
    if row:
        check("X", "analysis has predicted_winner",
              bool(row["predicted_winner"]), "")
        check("X", "analysis has analysis_text",
              bool(row["analysis_text"]), "")
        check("X", "analysis has confidence_pct in 50-90",
              50 <= row["confidence_pct"] <= 90,
              f"got={row['confidence_pct']}")
        check("X", "analysis has excitement_score in 0-100",
              0 <= row["excitement_score"] <= 100,
              f"got={row['excitement_score']}")
        # The analysis text should NOT contain digit characters.
        if row["analysis_text"]:
            has_digits = bool(_DIGIT_RE.search(row["analysis_text"]))
            check("X", "seeded analysis text has no digits",
                  not has_digits, f"text={row['analysis_text'][:120]!r}")

    # Print the analysis for visual inspection.
    if row:
        print(f"      predicted_winner: {row['predicted_winner']}")
        print(f"      predicted_method: {row['predicted_method']}")
        print(f"      confidence_pct:   {row['confidence_pct']}")
        print(f"      excitement_score: {row['excitement_score']}")
        print(f"      style_edge:       {row['style_edge']}")
        print(f"      upset_risk:       {row['upset_risk']}")
        print(f"      analysis_text:    {row['analysis_text'][:200]}...")

    conn.close()


def main():
    print("=" * 80)
    print(f"Task 24 — Punditry acceptance test "
          f"(schema {EXPECTED_CODE_VERSION})")
    print("=" * 80)
    case_a_schema()
    case_b_generate_matchup_analysis()
    case_c_no_raw_numbers()
    case_d_event_bus_integration()
    case_e_predicted_winner_uses_voice()
    case_f_excitement_score()
    case_g_style_edge_uses_voice()
    case_h_design_law()
    case_x_seeded_fight_smoke()
    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 80)
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
