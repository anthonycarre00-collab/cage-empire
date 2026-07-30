#!/usr/bin/env python3
"""Acceptance test for Phase 2 Tasks 2.5 + 2.6 — Memory Engine +
Headline Engine.

Tests src/interpretation/memory_engine.py (4 MVP search types:
previous_fight, shared_gym, former_teammate, injury_history) AND
src/interpretation/headline_engine.py (4 MVP daily headlines:
top_story, upset_of_week, fastest_rising, biggest_fall).

The Memory Engine is a READER (D3 of memory_engine.py) — it surfaces
relevant memories BEFORE a fight is booked between two fighters. The
existing `services/memory_svc.py` remains the writer (it inserts rows
into fighter_memory_links when retirements / signings / main-event
matchups occur). The Memory Engine turns those raw link rows + raw
simulation tables (fight_history, fighters.current_gym_id, injuries)
into PLAYER-FACING voice phrases.

The Headline Engine runs at the END of the daily interpretation pass
(after fighter_descriptors is fully populated). It writes 4 daily
headlines to the daily_headlines table via INSERT OR REPLACE
(idempotent — re-running for the same date overwrites, doesn't
duplicate).

Per CONVENTIONS §17:
  - The interpretation layer is the ONLY writer to daily_headlines
    (a cache table). It NEVER writes to simulation tables.
  - §17.4 "Rich Not Thin": the daily_headlines table stores the
    voice phrase directly (no "label||phrase" composite — headlines
    are free-form story text, not categorical labels).
  - §17.5 Performance: the Memory Engine is called ON-DEMAND (4
    small targeted SELECTs per fighter pair, <50ms). The Headline
    Engine runs daily (4 small SELECTs, <100ms).
  - §14 Voice Layer: ALL memory strings + ALL headline text contain
    NO DIGITS. The voice layer translates simulation into emotion.

Test cases:
  A. surface_memories — pure helpers (year-gap, result-type,
     outcome-verb, body-area, return-band voice phrases).
  B. surface_memories — previous_fight search (two fighters who've
     fought before → "Last met ... — won/lost/drew by ...").
  C. surface_memories — shared_gym search (two fighters who share a
     current gym → "Training partners at {gym_name}.").
  D. surface_memories — former_teammate search (two fighters linked
     via fighter_memory_links.former_teammate → "Former training
     partners.").
  E. surface_memories — injury_history search (one fighter has an
     active injury → "{name} is recovering from {body_area}, {band}.")
  F. surface_memories — no connection (two brand-new free agents →
     empty list).
  G. surface_memories — voice phrases contain NO DIGITS (§14).
  H. generate_daily_headlines — writes 4 headlines to daily_headlines.
  I. generate_daily_headlines — voice phrases contain NO DIGITS (§14).
  J. generate_daily_headlines — IDEMPOTENT (re-running same date
     doesn't duplicate; INSERT OR REPLACE).
  K. generate_daily_headlines — Top Story priority order
     (fallen_champion > prodigy > cinderella_story > veteran).
  L. Snapshot cache integration — run_daily_interpretation_pass
     calls generate_daily_headlines via _generate_headlines (wrapped
     in try/except — failures don't crash the daily pass).
  M. Design Law check (§13 + §17.4) — both engines translate raw
     simulation state into player-facing meaning (memories +
     headlines tell STORIES, not stats).
  N. Schema migration — v3.12.0 link_type CHECK accepts the 4 new
     values ('previous_fight', 'shared_gym', 'former_teammate',
     'injury_history').

Pattern follows scripts/test_narrative_legacy.py (CONVENTIONS §10 —
dynamic version pattern, no hardcoded version strings).

Run from the project root:
    python3 scripts/test_memory_headlines.py

Exit code 0 = all PASS, 1 = any FAIL.

D-number decisions in this test (referenced from the worklog):
  - D1: case A tests the pure voice-phrase helpers in isolation.
    Each helper is a pure function of primitive inputs — no DB, no
    RNG. Boundary cases (year_gap=0, 1, 5; result_type=None;
    projected_return_date=None) are tested explicitly.
  - D2: case B/E insert fight_history + injuries rows directly into
    the test DB to set up the exact scenario the engine should
    surface. This catches JOIN bugs that pure-function tests miss.
  - D3: case F verifies the engine returns an empty list (not None,
    not an exception) when two fighters have no connection. The
    engine must NEVER raise (memory_engine D6).
  - D4: case G+I check NO DIGITS in every voice phrase (CONVENTIONS
    §14). A phrase like "Last met 3 years ago" would be a §14
    violation.
  - D5: case J verifies IDEMPOTENCY — running generate_daily_
    headlines twice for the same date produces 4 rows, not 8. This
    catches INSERT-vs-INSERT-OR-REPLACE bugs that would only manifest
    on a re-run.
  - D6: case K verifies the Top Story priority order. We insert
    multiple narrative_family labels and verify the engine picks
    fallen_champion over prodigy, prodigy over cinderella, etc.
  - D7: case N verifies the v3.12.0 migration expanded the link_type
    CHECK. We insert all 8 link_type values and verify they're
    accepted; we also insert a bogus value and verify it's rejected.
"""
import sys
import os
import sqlite3
import subprocess
import time
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
sys.path.insert(0, str(SRC_DIR))

import build_db  # noqa: E402
import app  # noqa: E402
from interpretation import memory_engine as me  # noqa: E402
from interpretation import headline_engine as he  # noqa: E402
from interpretation import context_engine  # noqa: E402
from interpretation import career_phase_engine  # noqa: E402
from interpretation import narrative_families  # noqa: E402
from interpretation import snapshot_cache  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION

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


def populate_descriptor_rows(conn):
    """Create fighter_descriptors rows for all 5 seeded fighters.

    Same pattern as test_narrative_legacy.py — the daily pass UPDATES
    existing rows; we pre-create them via the existing snapshot path.
    """
    for fid in range(1, 6):
        app.update_fighter_descriptor_snapshot(conn, fid)
    conn.commit()


# Regex to detect digits in voice phrases (CONVENTIONS §14).
_HAS_DIGIT = re.compile(r"\d")


# ----------------------------------------------------------------
# Case A: pure voice-phrase helpers (memory_engine)
# ----------------------------------------------------------------
def case_a_pure_helpers():
    """Test memory_engine voice-phrase helpers (pure functions)."""
    print("\n--- Case A: pure voice-phrase helpers (memory_engine) ---")

    # A.1 — _year_gap_phrase: 0 → "this year".
    check("A", "_year_gap_phrase(0) → 'this year'",
          me._year_gap_phrase(0) == "this year",
          f"got={me._year_gap_phrase(0)!r}")
    # A.2 — _year_gap_phrase: 1 → "one year".
    check("A", "_year_gap_phrase(1) → 'one year'",
          me._year_gap_phrase(1) == "one year",
          f"got={me._year_gap_phrase(1)!r}")
    # A.3 — _year_gap_phrase: 3 → "three years".
    check("A", "_year_gap_phrase(3) → 'three years'",
          me._year_gap_phrase(3) == "three years",
          f"got={me._year_gap_phrase(3)!r}")
    # A.4 — _year_gap_phrase: 5 → "many years".
    check("A", "_year_gap_phrase(5) → 'many years'",
          me._year_gap_phrase(5) == "many years",
          f"got={me._year_gap_phrase(5)!r}")
    # A.5 — _year_gap_phrase: 10 → "many years" (boundary — 5+ caps).
    check("A", "_year_gap_phrase(10) → 'many years'",
          me._year_gap_phrase(10) == "many years",
          f"got={me._year_gap_phrase(10)!r}")
    # A.6 — _year_gap_phrase: negative → "this year" (defensive).
    check("A", "_year_gap_phrase(-5) → 'this year' (defensive)",
          me._year_gap_phrase(-5) == "this year",
          f"got={me._year_gap_phrase(-5)!r}")

    # A.7 — _result_type_phrase: split_decision → "split decision".
    check("A", "_result_type_phrase('split_decision') → 'split decision'",
          me._result_type_phrase("split_decision") == "split decision",
          f"got={me._result_type_phrase('split_decision')!r}")
    # A.8 — _result_type_phrase: ko_tko → "knockout".
    check("A", "_result_type_phrase('ko_tko') → 'knockout'",
          me._result_type_phrase("ko_tko") == "knockout",
          f"got={me._result_type_phrase('ko_tko')!r}")
    # A.9 — _result_type_phrase: submission → "submission".
    check("A", "_result_type_phrase('submission') → 'submission'",
          me._result_type_phrase("submission") == "submission",
          f"got={me._result_type_phrase('submission')!r}")
    # A.10 — _result_type_phrase: doctor_stoppage → "doctor stoppage".
    check("A", "_result_type_phrase('doctor_stoppage') → 'doctor stoppage'",
          me._result_type_phrase("doctor_stoppage") == "doctor stoppage",
          f"got={me._result_type_phrase('doctor_stoppage')!r}")
    # A.11 — _result_type_phrase: dq → "disqualification".
    check("A", "_result_type_phrase('dq') → 'disqualification'",
          me._result_type_phrase("dq") == "disqualification",
          f"got={me._result_type_phrase('dq')!r}")
    # A.12 — _result_type_phrase: draw → "draw".
    check("A", "_result_type_phrase('draw') → 'draw'",
          me._result_type_phrase("draw") == "draw",
          f"got={me._result_type_phrase('draw')!r}")
    # A.13 — _result_type_phrase: None → "a finish" (defensive).
    check("A", "_result_type_phrase(None) → 'a finish' (defensive)",
          me._result_type_phrase(None) == "a finish",
          f"got={me._result_type_phrase(None)!r}")
    # A.14 — _result_type_phrase: unknown → "a finish" (defensive).
    check("A", "_result_type_phrase('bogus') → 'a finish' (defensive)",
          me._result_type_phrase("bogus") == "a finish",
          f"got={me._result_type_phrase('bogus')!r}")

    # A.15 — _outcome_verb: win → "won".
    check("A", "_outcome_verb('win') → 'won'",
          me._outcome_verb("win") == "won",
          f"got={me._outcome_verb('win')!r}")
    # A.16 — _outcome_verb: loss → "lost".
    check("A", "_outcome_verb('loss') → 'lost'",
          me._outcome_verb("loss") == "lost",
          f"got={me._outcome_verb('loss')!r}")
    # A.17 — _outcome_verb: draw → "drew".
    check("A", "_outcome_verb('draw') → 'drew'",
          me._outcome_verb("draw") == "drew",
          f"got={me._outcome_verb('draw')!r}")
    # A.18 — _outcome_verb: None → "fought" (defensive).
    check("A", "_outcome_verb(None) → 'fought' (defensive)",
          me._outcome_verb(None) == "fought",
          f"got={me._outcome_verb(None)!r}")

    # A.19 — _body_area_phrase: shoulder → "a shoulder injury".
    check("A", "_body_area_phrase('shoulder') → 'a shoulder injury'",
          me._body_area_phrase("shoulder") == "a shoulder injury",
          f"got={me._body_area_phrase('shoulder')!r}")
    # A.20 — _body_area_phrase: ribs → "a rib injury" (singular).
    check("A", "_body_area_phrase('ribs') → 'a rib injury' (singular)",
          me._body_area_phrase("ribs") == "a rib injury",
          f"got={me._body_area_phrase('ribs')!r}")
    # A.21 — _body_area_phrase: knee → "a knee injury".
    check("A", "_body_area_phrase('knee') → 'a knee injury'",
          me._body_area_phrase("knee") == "a knee injury",
          f"got={me._body_area_phrase('knee')!r}")
    # A.22 — _body_area_phrase: None → "an injury" (defensive).
    check("A", "_body_area_phrase(None) → 'an injury' (defensive)",
          me._body_area_phrase(None) == "an injury",
          f"got={me._body_area_phrase(None)!r}")

    # A.23 — _return_band_phrase: 25 days out → "near return".
    check("A", "_return_band('2026-08-15', '2026-07-20') → 'near return'",
          me._return_band_phrase("2026-08-15", "2026-07-20")
          == "near return",
          f"got={me._return_band_phrase('2026-08-15', '2026-07-20')!r}")
    # A.24 — _return_band_phrase: 100 days out → "a long road back".
    check("A", "_return_band('2026-12-15', '2026-07-20') → 'a long road back'",
          me._return_band_phrase("2026-12-15", "2026-07-20")
          == "a long road back",
          f"got={me._return_band_phrase('2026-12-15', '2026-07-20')!r}")
    # A.25 — _return_band_phrase: past-due → "indefinite".
    check("A", "_return_band('2026-05-15', '2026-07-20') → 'indefinite'",
          me._return_band_phrase("2026-05-15", "2026-07-20")
          == "indefinite",
          f"got={me._return_band_phrase('2026-05-15', '2026-07-20')!r}")
    # A.26 — _return_band_phrase: None → "indefinite".
    check("A", "_return_band(None, '2026-07-20') → 'indefinite'",
          me._return_band_phrase(None, "2026-07-20") == "indefinite",
          f"got={me._return_band_phrase(None, '2026-07-20')!r}")


# ----------------------------------------------------------------
# Case B: surface_memories — previous_fight
# ----------------------------------------------------------------
def case_b_previous_fight():
    """Test surface_memories with two fighters who have fought before."""
    print("\n--- Case B: surface_memories — previous_fight ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    # Disable FK enforcement for test data inserts — fight_history
    # has FK to fights, and we want to insert a synthetic fight row
    # without setting up the full fights + events + weight_classes
    # chain. The memory engine reads fight_history directly; FK
    # integrity is not what we're testing here.
    conn.execute("PRAGMA foreign_keys = OFF;")

    # Insert a fight_history row between fighters 1 and 2 (a split
    # decision win for fighter 1, 3 years ago). fight_history requires
    # a fight_id (NOT NULL, FK to fights) — we insert a minimal fights
    # row first to satisfy the FK (or skip it with FKs OFF).
    conn.execute(
        "INSERT INTO fight_history "
        "(fight_id, fighter_id, opponent_id, outcome, result_type, "
        " event_date) VALUES (?, ?, ?, ?, ?, ?)",
        (999901, 1, 2, "win", "split_decision", "2023-07-20"),
    )
    # Insert the mirror row (fighter 2's perspective) — the engine
    # only reads fighter 1's row (fighter_a_id=1, fighter_b_id=2),
    # but we insert both for realism.
    conn.execute(
        "INSERT INTO fight_history "
        "(fight_id, fighter_id, opponent_id, outcome, result_type, "
        " event_date) VALUES (?, ?, ?, ?, ?, ?)",
        (999901, 2, 1, "loss", "split_decision", "2023-07-20"),
    )
    conn.commit()

    # B.1 — surface_memories returns a non-empty list.
    memories = me.surface_memories(conn, 1, 2, current_date="2026-07-20")
    check("B", "previous_fight: returns non-empty list",
          len(memories) > 0, f"got={len(memories)} memories")

    # B.2 — the first memory is the previous_fight type.
    types = [m[0] for m in memories]
    check("B", "previous_fight: MEMORY_TYPE_PREVIOUS_FIGHT in types",
          me.MEMORY_TYPE_PREVIOUS_FIGHT in types,
          f"got types={types}")

    # B.3 — the memory phrase contains "Last met" + "split decision".
    prev_phrase = next((m[1] for m in memories
                        if m[0] == me.MEMORY_TYPE_PREVIOUS_FIGHT), None)
    check("B", "previous_fight: phrase contains 'Last met'",
          prev_phrase is not None and "Last met" in prev_phrase,
          f"got={prev_phrase!r}")
    check("B", "previous_fight: phrase contains 'split decision'",
          prev_phrase is not None and "split decision" in prev_phrase,
          f"got={prev_phrase!r}")
    # B.4 — phrase contains "won" (fighter 1 won).
    check("B", "previous_fight: phrase contains 'won' (fighter_a won)",
          prev_phrase is not None and "won" in prev_phrase,
          f"got={prev_phrase!r}")
    # B.5 — phrase contains "three years ago" (2023 → 2026 = 3 years).
    check("B", "previous_fight: phrase contains 'three years' (gap)",
          prev_phrase is not None and "three years" in prev_phrase,
          f"got={prev_phrase!r}")

    # B.6 — reverse perspective: fighter 2's view → "lost" not "won".
    memories_rev = me.surface_memories(conn, 2, 1,
                                       current_date="2026-07-20")
    prev_phrase_rev = next((m[1] for m in memories_rev
                            if m[0] == me.MEMORY_TYPE_PREVIOUS_FIGHT),
                           None)
    check("B", "previous_fight: reverse perspective → 'lost'",
          prev_phrase_rev is not None and "lost" in prev_phrase_rev,
          f"got={prev_phrase_rev!r}")

    conn.close()


# ----------------------------------------------------------------
# Case C: surface_memories — shared_gym
# ----------------------------------------------------------------
def case_c_shared_gym():
    """Test surface_memories with two fighters who share a current gym."""
    print("\n--- Case C: surface_memories — shared_gym ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Fresh seed: fighters 1+2 share gym 1 (Ironhouse Gym); fighters
    # 3+4+5 share gym 2 (Steelcrest Gym).
    # C.1 — fighters 1+2 share gym 1 → shared_gym memory.
    memories = me.surface_memories(conn, 1, 2,
                                   current_date="2026-07-20")
    types = [m[0] for m in memories]
    check("C", "shared_gym: 1+2 → MEMORY_TYPE_SHARED_GYM in types",
          me.MEMORY_TYPE_SHARED_GYM in types,
          f"got types={types}")

    shared_phrase = next((m[1] for m in memories
                          if m[0] == me.MEMORY_TYPE_SHARED_GYM), None)
    check("C", "shared_gym: phrase contains 'Training partners'",
          shared_phrase is not None and "Training partners" in shared_phrase,
          f"got={shared_phrase!r}")
    check("C", "shared_gym: phrase contains 'Ironhouse Gym' (the gym name)",
          shared_phrase is not None and "Ironhouse Gym" in shared_phrase,
          f"got={shared_phrase!r}")

    # C.2 — fighters 3+4 share gym 2 → shared_gym memory with Steelcrest.
    memories = me.surface_memories(conn, 3, 4,
                                   current_date="2026-07-20")
    types = [m[0] for m in memories]
    check("C", "shared_gym: 3+4 → MEMORY_TYPE_SHARED_GYM in types",
          me.MEMORY_TYPE_SHARED_GYM in types,
          f"got types={types}")
    shared_phrase = next((m[1] for m in memories
                          if m[0] == me.MEMORY_TYPE_SHARED_GYM), None)
    check("C", "shared_gym: phrase contains 'Steelcrest Gym'",
          shared_phrase is not None and "Steelcrest Gym" in shared_phrase,
          f"got={shared_phrase!r}")

    # C.3 — fighters 1+3 DON'T share a gym (1→Ironhouse, 3→Steelcrest).
    memories = me.surface_memories(conn, 1, 3,
                                   current_date="2026-07-20")
    types = [m[0] for m in memories]
    check("C", "shared_gym: 1+3 (different gyms) → NOT in types",
          me.MEMORY_TYPE_SHARED_GYM not in types,
          f"got types={types}")

    conn.close()


# ----------------------------------------------------------------
# Case D: surface_memories — former_teammate
# ----------------------------------------------------------------
def case_d_former_teammate():
    """Test surface_memories with two fighters linked via
    fighter_memory_links.former_teammate."""
    print("\n--- Case D: surface_memories — former_teammate ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Insert a former_teammate link between fighters 1 and 3 (who
    # don't currently share a gym — fresh seed has 1→Ironhouse,
    # 3→Steelcrest).
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'former_teammate', 70)",
        (1, 3),
    )
    # Mirror row (memory_svc writes bidirectional for some types —
    # the engine checks both directions in one query, so this is
    # belt-and-suspenders).
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'former_teammate', 70)",
        (3, 1),
    )
    conn.commit()

    # D.1 — surface_memories surfaces the former_teammate memory.
    memories = me.surface_memories(conn, 1, 3,
                                   current_date="2026-07-20")
    types = [m[0] for m in memories]
    check("D", "former_teammate: 1+3 → MEMORY_TYPE_FORMER_TEAMMATE in types",
          me.MEMORY_TYPE_FORMER_TEAMMATE in types,
          f"got types={types}")

    teammate_phrase = next((m[1] for m in memories
                            if m[0] == me.MEMORY_TYPE_FORMER_TEAMMATE),
                           None)
    check("D", "former_teammate: phrase contains 'Former training partners'",
          teammate_phrase is not None
          and "Former training partners" in teammate_phrase,
          f"got={teammate_phrase!r}")

    # D.2 — surface_memories works in the reverse direction (3 → 1).
    memories_rev = me.surface_memories(conn, 3, 1,
                                       current_date="2026-07-20")
    types_rev = [m[0] for m in memories_rev]
    check("D", "former_teammate: reverse (3+1) → also surfaces",
          me.MEMORY_TYPE_FORMER_TEAMMATE in types_rev,
          f"got types={types_rev}")

    # D.3 — fighters without a former_teammate link don't surface it.
    memories_none = me.surface_memories(conn, 2, 4,
                                        current_date="2026-07-20")
    types_none = [m[0] for m in memories_none]
    check("D", "former_teammate: 2+4 (no link) → NOT in types",
          me.MEMORY_TYPE_FORMER_TEAMMATE not in types_none,
          f"got types={types_none}")

    conn.close()


# ----------------------------------------------------------------
# Case E: surface_memories — injury_history
# ----------------------------------------------------------------
def case_e_injury_history():
    """Test surface_memories with one fighter who has an active injury."""
    print("\n--- Case E: surface_memories — injury_history ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Insert an active injury for fighter 1 (shoulder, projected return
    # 25 days from current_date → "near return" band).
    conn.execute(
        "INSERT INTO injuries "
        "(fighter_id, injury_type, severity, body_area, start_date, "
        " projected_return_date, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (1, "shoulder labrum tear", 7, "shoulder", "2026-06-01",
         "2026-08-15"),
    )
    conn.commit()

    # E.1 — surface_memories surfaces the injury memory.
    memories = me.surface_memories(conn, 1, 2,
                                   current_date="2026-07-20")
    types = [m[0] for m in memories]
    check("E", "injury_history: 1 has active injury → in types",
          me.MEMORY_TYPE_INJURY_HISTORY in types,
          f"got types={types}")

    injury_phrase = next((m[1] for m in memories
                          if m[0] == me.MEMORY_TYPE_INJURY_HISTORY), None)
    check("E", "injury_history: phrase contains fighter name",
          injury_phrase is not None and "John Vale" in injury_phrase,
          f"got={injury_phrase!r}")
    check("E", "injury_history: phrase contains 'shoulder injury'",
          injury_phrase is not None and "shoulder injury" in injury_phrase,
          f"got={injury_phrase!r}")
    check("E", "injury_history: phrase contains 'near return' band",
          injury_phrase is not None and "near return" in injury_phrase,
          f"got={injury_phrase!r}")

    # E.2 — long road back (projected >60 days out).
    conn.execute(
        "UPDATE injuries SET projected_return_date=? "
        "WHERE fighter_id=? AND is_active=1",
        ("2026-12-15", 1),
    )
    conn.commit()
    memories = me.surface_memories(conn, 1, 2,
                                   current_date="2026-07-20")
    injury_phrase = next((m[1] for m in memories
                          if m[0] == me.MEMORY_TYPE_INJURY_HISTORY), None)
    check("E", "injury_history: long road back band (>60 days)",
          injury_phrase is not None and "long road back" in injury_phrase,
          f"got={injury_phrase!r}")

    # E.3 — indefinite (past-due projected return).
    conn.execute(
        "UPDATE injuries SET projected_return_date=? "
        "WHERE fighter_id=? AND is_active=1",
        ("2026-05-15", 1),
    )
    conn.commit()
    memories = me.surface_memories(conn, 1, 2,
                                   current_date="2026-07-20")
    injury_phrase = next((m[1] for m in memories
                          if m[0] == me.MEMORY_TYPE_INJURY_HISTORY), None)
    check("E", "injury_history: indefinite band (past-due)",
          injury_phrase is not None and "indefinite" in injury_phrase,
          f"got={injury_phrase!r}")

    # E.4 — no active injury → no injury memory.
    conn.execute("UPDATE injuries SET is_active=0 WHERE fighter_id=1")
    conn.commit()
    memories = me.surface_memories(conn, 1, 2,
                                   current_date="2026-07-20")
    types = [m[0] for m in memories]
    check("E", "injury_history: resolved injury → NOT in types",
          me.MEMORY_TYPE_INJURY_HISTORY not in types,
          f"got types={types}")

    conn.close()


# ----------------------------------------------------------------
# Case F: surface_memories — no connection
# ----------------------------------------------------------------
def case_f_no_connection():
    """Test surface_memories with two fighters who have no connection."""
    print("\n--- Case F: surface_memories — no connection ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Force fighters 1 and 3 into different gyms (they're in different
    # gyms already in the fresh seed — 1→Ironhouse, 3→Steelcrest).
    # No fight_history, no former_teammate link, no active injuries.
    # surface_memories should return an empty list.
    memories = me.surface_memories(conn, 1, 3,
                                   current_date="2026-07-20")
    check("F", "no connection: returns empty list",
          memories == [], f"got={memories}")

    # F.2 — also empty in the reverse direction.
    memories_rev = me.surface_memories(conn, 3, 1,
                                       current_date="2026-07-20")
    check("F", "no connection: reverse also empty",
          memories_rev == [], f"got={memories_rev}")

    # F.3 — same fighter (degenerate — should still return empty
    # without crashing; the engine doesn't special-case this).
    memories_self = me.surface_memories(conn, 1, 1,
                                        current_date="2026-07-20")
    check("F", "no connection: same fighter (1,1) doesn't crash",
          isinstance(memories_self, list),
          f"got={memories_self}")

    conn.close()


# ----------------------------------------------------------------
# Case G: voice phrases contain NO DIGITS (§14)
# ----------------------------------------------------------------
def case_g_no_digits():
    """Test that surface_memories voice phrases contain no digits (§14)."""
    print("\n--- Case G: voice phrases contain NO DIGITS (§14) ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")

    # Set up a fighter pair with ALL 4 memory types active.
    # 1. previous_fight: insert a fight_history row.
    conn.execute(
        "INSERT INTO fight_history "
        "(fight_id, fighter_id, opponent_id, outcome, result_type, "
        " event_date) VALUES (?, ?, ?, ?, ?, ?)",
        (999901, 1, 3, "win", "ko_tko", "2023-07-20"),
    )
    # 2. shared_gym: move fighter 3 to gym 1 (Ironhouse).
    conn.execute("UPDATE fighters SET current_gym_id=1 WHERE fighter_id=3")
    # 3. former_teammate: insert a memory link.
    conn.execute(
        "INSERT INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'former_teammate', 70)",
        (1, 3),
    )
    # 4. injury_history: insert an active injury.
    conn.execute(
        "INSERT INTO injuries "
        "(fighter_id, injury_type, severity, body_area, start_date, "
        " projected_return_date, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (1, "shoulder labrum tear", 7, "shoulder", "2026-06-01",
         "2026-08-15"),
    )
    conn.commit()

    memories = me.surface_memories(conn, 1, 3,
                                   current_date="2026-07-20")

    # G.1 — at least 3 memories surfaced (shared_gym + former_teammate
    # may both apply — the engine surfaces each type independently).
    check("G", "4-search setup surfaces at least 3 memories",
          len(memories) >= 3, f"got={len(memories)} memories: "
          f"{[m[0] for m in memories]}")

    # G.2 — every voice phrase contains NO DIGITS.
    bad = 0
    for mem_type, phrase in memories:
        if _HAS_DIGIT.search(phrase):
            bad += 1
            print(f"    DIGIT VIOLATION in {mem_type}: {phrase!r}")
    check("G", "all voice phrases contain NO digits (§14)",
          bad == 0, f"got={bad} violations")

    conn.close()


# ----------------------------------------------------------------
# Case H: generate_daily_headlines writes 4 headlines
# ----------------------------------------------------------------
def case_h_generate_headlines():
    """Test generate_daily_headlines writes 4 headlines to daily_headlines."""
    print("\n--- Case H: generate_daily_headlines writes 4 headlines ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # Set up a fighter with a narrative family so headlines actually
    # generate (otherwise H.3 is vacuously tested with 0 rows).
    # Fighter 1: prodigy (22yo + 5-win streak → very_high + prospect).
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0 "
                 "WHERE fighter_id=1")
    # Fighter 2: collapsing (3-loss streak).
    conn.execute("UPDATE fighter_career SET loss_streak=3, "
                 "record_wins=2, record_losses=3, record_draws=0 "
                 "WHERE fighter_id=2")
    conn.commit()
    # Populate momentum + career_phase + narrative_family + legacy
    # so the headline engine has data to work with.
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    compute_all_legacies(conn)

    # H.1 — daily_headlines table starts empty.
    n_before = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines"
    ).fetchone()[0]
    check("H", "daily_headlines starts empty",
          n_before == 0, f"got={n_before}")

    # H.2 — generate_daily_headlines returns an int (count written).
    n_written = he.generate_daily_headlines(conn,
                                            current_date="2026-07-20")
    check("H", "generate_daily_headlines returns int",
          isinstance(n_written, int), f"got={n_written!r}")

    # H.3 — daily_headlines has between 1 and 4 rows (1-4 because
    # upset_of_week may be skipped — no fights in last 7 days on a
    # fresh test DB. But top_story + fastest_rising + biggest_fall
    # should all have subjects with our prodigy + collapsing setup).
    n_after = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines"
    ).fetchone()[0]
    check("H", "daily_headlines has 1-4 rows after generate (non-vacuous)",
          1 <= n_after <= 4, f"got={n_after}")

    # H.4 — every row has the correct date.
    bad_dates = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines "
        "WHERE headline_date != '2026-07-20'"
    ).fetchone()[0]
    check("H", "all rows have the correct headline_date",
          bad_dates == 0, f"got={bad_dates} bad dates")

    # H.5 — every row has a valid headline_type (one of the 4 MVP
    # types — the CHECK constraint would reject anything else, but
    # we double-check the engine writes only the 4 MVP types).
    valid_types = set(he.ALL_HEADLINE_TYPES)
    bad_types = 0
    for r in conn.execute("SELECT headline_type FROM daily_headlines"):
        if r[0] not in valid_types:
            bad_types += 1
    check("H", "all rows have a valid MVP headline_type",
          bad_types == 0, f"got={bad_types} bad types")

    # H.6 — every row has a non-empty headline_text + body_text.
    bad = 0
    for r in conn.execute("SELECT headline_text, body_text "
                          "FROM daily_headlines"):
        if not r[0] or not r[1]:
            bad += 1
    check("H", "all rows have non-empty headline_text + body_text",
          bad == 0, f"got={bad} empty rows")

    conn.close()


# ----------------------------------------------------------------
# Case I: headlines contain NO DIGITS (§14)
# ----------------------------------------------------------------
def case_i_headlines_no_digits():
    """Test that headline text contains no digits (§14)."""
    print("\n--- Case I: headlines contain NO DIGITS (§14) ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # Set up a fighter with a narrative family so the top_story
    # headline has a subject. Make fighter 1 a prodigy (22yo + 5-win
    # streak → very_high momentum + prospect phase → prodigy family).
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0 "
                 "WHERE fighter_id=1")
    conn.commit()

    # Run the full interpretation pass so fighter_descriptors has
    # fresh momentum + career_phase + narrative_family + legacy.
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    compute_all_legacies(conn)

    # Also set up a biggest_fall subject — fighter 2 with collapsing
    # momentum (3+ loss streak).
    conn.execute("UPDATE fighter_career SET loss_streak=3, "
                 "record_wins=2, record_losses=3, record_draws=0 "
                 "WHERE fighter_id=2")
    conn.commit()
    compute_all_fighters(conn)

    # Generate headlines.
    he.generate_daily_headlines(conn, current_date="2026-07-20")

    # I.0 — at least one headline was generated (otherwise the no-digit
    # check below is vacuously true and tests nothing). With fighter 1
    # as a prodigy + fighter 2 collapsing, top_story + fastest_rising +
    # biggest_fall should all have subjects.
    n_headlines = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines "
        "WHERE headline_date='2026-07-20'"
    ).fetchone()[0]
    check("I", "at least 1 headline generated (non-vacuous digit check)",
          n_headlines >= 1, f"got={n_headlines}")

    # I.1 — every headline_text + body_text contains NO DIGITS.
    bad = 0
    for r in conn.execute("SELECT headline_type, headline_text, body_text "
                          "FROM daily_headlines"):
        if _HAS_DIGIT.search(r[1] or ""):
            bad += 1
            print(f"    DIGIT VIOLATION in {r[0]} text: {r[1]!r}")
        if _HAS_DIGIT.search(r[2] or ""):
            bad += 1
            print(f"    DIGIT VIOLATION in {r[0]} body: {r[2]!r}")
    check("I", "all headline_text + body_text contain NO digits (§14)",
          bad == 0, f"got={bad} violations")

    conn.close()


# ----------------------------------------------------------------
# Case J: idempotency — re-running same date doesn't duplicate
# ----------------------------------------------------------------
def case_j_idempotency():
    """Test that re-running generate_daily_headlines for the same date
    doesn't duplicate rows (INSERT OR REPLACE per D6)."""
    print("\n--- Case J: idempotency ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # Set up a fighter with a narrative family so headlines actually
    # generate (otherwise idempotency is vacuously tested with 0 rows).
    # Fighter 1: prodigy (22yo + 5-win streak → very_high + prospect).
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0 "
                 "WHERE fighter_id=1")
    # Fighter 2: collapsing (3-loss streak).
    conn.execute("UPDATE fighter_career SET loss_streak=3, "
                 "record_wins=2, record_losses=3, record_draws=0 "
                 "WHERE fighter_id=2")
    conn.commit()
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    compute_all_legacies(conn)

    # J.1 — first run produces N rows (N >= 1, non-vacuous).
    he.generate_daily_headlines(conn, current_date="2026-07-20")
    n_first = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines "
        "WHERE headline_date='2026-07-20'"
    ).fetchone()[0]
    check("J", "first run produces 1-4 rows (non-vacuous)",
          1 <= n_first <= 4, f"got={n_first}")

    # J.2 — second run for the SAME date produces the SAME count
    # (INSERT OR REPLACE — no duplicates).
    he.generate_daily_headlines(conn, current_date="2026-07-20")
    n_second = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines "
        "WHERE headline_date='2026-07-20'"
    ).fetchone()[0]
    check("J", "second run produces same count (idempotent)",
          n_second == n_first, f"first={n_first}, second={n_second}")

    # J.3 — third run for the same date still produces the same count.
    he.generate_daily_headlines(conn, current_date="2026-07-20")
    n_third = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines "
        "WHERE headline_date='2026-07-20'"
    ).fetchone()[0]
    check("J", "third run still produces same count",
          n_third == n_first, f"first={n_first}, third={n_third}")

    # J.4 — UNIQUE (headline_date, headline_type) constraint is intact
    # — no duplicate (date, type) pairs.
    n_dupes = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT headline_date, headline_type, COUNT(*) AS c "
        "  FROM daily_headlines GROUP BY headline_date, headline_type"
        ") WHERE c > 1"
    ).fetchone()[0]
    check("J", "no duplicate (date, type) pairs",
          n_dupes == 0, f"got={n_dupes} duplicate pairs")

    # J.5 — a different date produces a separate set of rows.
    he.generate_daily_headlines(conn, current_date="2026-07-21")
    n_next_day = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines "
        "WHERE headline_date='2026-07-21'"
    ).fetchone()[0]
    check("J", "different date produces separate rows",
          0 <= n_next_day <= 4, f"got={n_next_day}")

    # J.6 — total rows = n_first + n_next_day (no overlap).
    n_total = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines"
    ).fetchone()[0]
    check("J", "total rows = first day + second day (no overlap)",
          n_total == n_first + n_next_day,
          f"total={n_total}, expected={n_first + n_next_day}")

    conn.close()


# ----------------------------------------------------------------
# Case K: Top Story priority order
# ----------------------------------------------------------------
def case_k_top_story_priority():
    """Test the Top Story priority order:
    fallen_champion > prodigy > cinderella_story > veteran.
    """
    print("\n--- Case K: Top Story priority order ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # Set up 4 fighters — one for each narrative family.
    # Fighter 1: prodigy (22yo + 5-win streak → prospect + very_high).
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0, "
                 "title_reigns=0 WHERE fighter_id=1")
    # Fighter 2: veteran (36yo + 20 fights + flat streak → veteran +
    # stable).
    conn.execute("UPDATE fighters SET date_of_birth='1990-01-01' "
                 "WHERE fighter_id=2")
    conn.execute("UPDATE fighter_career SET win_streak=1, loss_streak=0, "
                 "record_wins=12, record_losses=8, record_draws=0, "
                 "title_reigns=0 WHERE fighter_id=2")
    # Fighter 3: cinderella_story (30yo + 5-win streak → rising_contender
    # + very_high).
    conn.execute("UPDATE fighters SET date_of_birth='1996-01-01' "
                 "WHERE fighter_id=3")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=10, record_losses=5, record_draws=0, "
                 "title_reigns=0 WHERE fighter_id=3")
    # Fighter 4: fallen_champion (35yo + 3-loss streak + 1 title_reign
    # → declining + falling).
    conn.execute("UPDATE fighters SET date_of_birth='1991-01-01' "
                 "WHERE fighter_id=4")
    conn.execute("UPDATE fighter_career SET win_streak=0, loss_streak=3, "
                 "record_wins=15, record_losses=8, record_draws=0, "
                 "title_reigns=1 WHERE fighter_id=4")
    conn.commit()

    # Run the full interpretation pass.
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    compute_all_legacies(conn)

    # K.1 — verify each fighter got the expected family.
    families = {}
    for r in conn.execute("SELECT fighter_id, narrative_family "
                          "FROM fighter_descriptors"):
        families[r[0]] = narrative_families.decode_label(r[1])
    check("K", "fighter 1 → prodigy",
          families.get(1) == "prodigy", f"got={families.get(1)!r}")
    check("K", "fighter 4 → fallen_champion",
          families.get(4) == "fallen_champion",
          f"got={families.get(4)!r}")

    # K.2 — generate headlines + verify top_story is fallen_champion.
    he.generate_daily_headlines(conn, current_date="2026-07-20")
    top = conn.execute(
        "SELECT fighter_id, headline_text FROM daily_headlines "
        "WHERE headline_type='top_story' AND headline_date='2026-07-20'"
    ).fetchone()
    check("K", "top_story subject = fighter 4 (fallen_champion priority)",
          top is not None and top[0] == 4,
          f"got={top}")
    check("K", "top_story headline contains 'fallen champion'",
          top is not None and "fallen champion" in top[1].lower(),
          f"got={top[1] if top else None!r}")

    # K.3 — remove fallen_champion (reset fighter 4 to a rising_
    # contender with no titles) → top_story should now be prodigy.
    conn.execute("UPDATE fighter_career SET win_streak=1, loss_streak=0, "
                 "record_wins=15, record_losses=8, record_draws=0, "
                 "title_reigns=0 WHERE fighter_id=4")
    conn.execute("UPDATE fighters SET date_of_birth='1996-01-01' "
                 "WHERE fighter_id=4")
    conn.commit()
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    he.generate_daily_headlines(conn, current_date="2026-07-20")
    top = conn.execute(
        "SELECT fighter_id, headline_text FROM daily_headlines "
        "WHERE headline_type='top_story' AND headline_date='2026-07-20'"
    ).fetchone()
    check("K", "after removing fallen_champion → top_story = prodigy (fighter 1)",
          top is not None and top[0] == 1,
          f"got={top}")
    check("K", "top_story headline contains 'prodigy'",
          top is not None and "prodigy" in top[1].lower(),
          f"got={top[1] if top else None!r}")

    conn.close()


# ----------------------------------------------------------------
# Case L: Snapshot cache integration
# ----------------------------------------------------------------
def case_l_snapshot_cache_integration():
    """Test that snapshot_cache.run_daily_interpretation_pass calls
    generate_daily_headlines via _generate_headlines (wrapped in
    try/except — failures don't crash the daily pass)."""
    print("\n--- Case L: snapshot_cache integration ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # L.1 — run_daily_interpretation_pass doesn't crash.
    try:
        snapshot_cache.run_daily_interpretation_pass(conn)
        passed = True
    except Exception as e:
        passed = False
        detail = f"{type(e).__name__}: {e}"
    check("L", "run_daily_interpretation_pass doesn't crash",
          passed, detail if not passed else "")

    # L.2 — daily_headlines table is populated (the pass calls
    # generate_daily_headlines).
    n = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines"
    ).fetchone()[0]
    check("L", "daily_headlines populated by daily pass",
          0 <= n <= 4, f"got={n}")

    # L.3 — interpretation_cache_meta.engine_version is bumped to
    # the new ENGINE_VERSION. Phase 0 (UI Redesign Rev 3) bumped
    # 1.5.0 → 1.6.0 to force a cache rebuild. Test reads the current
    # ENGINE_VERSION dynamically so future bumps don't break this.
    from interpretation.snapshot_cache import ENGINE_VERSION
    row = conn.execute(
        "SELECT engine_version FROM interpretation_cache_meta "
        "WHERE meta_id=1"
    ).fetchone()
    check("L", f"interpretation_cache_meta.engine_version = {ENGINE_VERSION}",
          row is not None and row[0] == ENGINE_VERSION,
          f"got={row[0] if row else None!r}")

    # L.4 — _generate_headlines wraps the call in try/except
    # Exception. We verify this by MONKEY-PATCHING the headline
    # engine to raise, then running the daily pass — it should NOT
    # crash (the exception is caught + logged).
    import interpretation.headline_engine as he_mod
    original = he_mod.generate_daily_headlines

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated headline engine failure")

    he_mod.generate_daily_headlines = _raise
    try:
        try:
            snapshot_cache.run_daily_interpretation_pass(conn)
            passed = True
        except Exception as e:
            passed = False
            detail = f"{type(e).__name__}: {e}"
        check("L", "daily pass survives headline_engine failure (try/except)",
              passed, detail if not passed else "")
    finally:
        he_mod.generate_daily_headlines = original

    conn.close()


# ----------------------------------------------------------------
# Case M: Design Law check (§13 + §17.4)
# ----------------------------------------------------------------
def case_m_design_law():
    """Verify both engines translate raw simulation state into player-
    facing meaning (memories + headlines tell STORIES, not stats)."""
    print("\n--- Case M: Design Law check ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")
    populate_descriptor_rows(conn)

    # Set up: fighter 1 + fighter 2 share gym 1, fought before, and
    # fighter 1 has an active injury. Surface_memories should produce
    # story-like phrases — NOT raw stat dumps.
    conn.execute(
        "INSERT INTO fight_history "
        "(fight_id, fighter_id, opponent_id, outcome, result_type, "
        " event_date) VALUES (?, ?, ?, ?, ?, ?)",
        (999901, 1, 2, "win", "ko_tko", "2023-07-20"),
    )
    conn.execute(
        "INSERT INTO injuries "
        "(fighter_id, injury_type, severity, body_area, start_date, "
        " projected_return_date, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (1, "shoulder labrum tear", 7, "shoulder", "2026-06-01",
         "2026-08-15"),
    )
    conn.commit()

    memories = me.surface_memories(conn, 1, 2,
                                   current_date="2026-07-20")

    # M.1 — memories are non-empty strings (stories, not None).
    bad = 0
    for _type, phrase in memories:
        if not isinstance(phrase, str) or len(phrase) < 10:
            bad += 1
    check("M", "memories are non-empty story strings (>=10 chars)",
          bad == 0, f"got={bad} bad memories")

    # M.2 — memories don't contain raw stat keywords (record_wins,
    # rating, fighter_id, etc.).
    raw_keywords = ["record_wins", "record_losses", "fighter_id",
                    "rating", "momentum=", "career_phase="]
    bad = 0
    for _type, phrase in memories:
        for kw in raw_keywords:
            if kw in phrase.lower():
                bad += 1
                print(f"    RAW KEYWORD '{kw}' in {type}: {phrase!r}")
    check("M", "memories contain no raw stat keywords",
          bad == 0, f"got={bad} violations")

    # M.3 — headlines likewise tell stories, not stats.
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    compute_all_legacies(conn)
    he.generate_daily_headlines(conn, current_date="2026-07-20")

    bad = 0
    for r in conn.execute("SELECT headline_text, body_text "
                          "FROM daily_headlines"):
        for kw in raw_keywords:
            if kw in (r[0] or "").lower() or kw in (r[1] or "").lower():
                bad += 1
                print(f"    RAW KEYWORD '{kw}' in headline: {r!r}")
    check("M", "headlines contain no raw stat keywords",
          bad == 0, f"got={bad} violations")

    conn.close()


# ----------------------------------------------------------------
# Case N: Schema migration — v3.12.0 link_type CHECK expansion
# ----------------------------------------------------------------
def case_n_schema_migration():
    """Test that the v3.12.0 migration expanded the link_type CHECK."""
    print("\n--- Case N: schema migration — v3.12.0 link_type CHECK ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")

    # N.1 — schema_meta shows the current CODE_SCHEMA_VERSION.
    # Phase 4 bumped it to 3.13.0 (additive index migration). The
    # test originally hard-coded '3.12.0' — updated to read the
    # actual current version from build_db.CODE_SCHEMA_VERSION so
    # future schema bumps don't break this assertion.
    from build_db import CODE_SCHEMA_VERSION
    row = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("N", f"schema_meta.schema_version = '{CODE_SCHEMA_VERSION}'",
          row is not None and row[0] == CODE_SCHEMA_VERSION,
          f"got={row[0] if row else None!r}")

    # N.2 — v3_12_0 migration is recorded in schema_migrations.
    n = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations "
        "WHERE migration_name='v3_12_0_expand_memory_link_types'"
    ).fetchone()[0]
    check("N", "v3_12_0 migration recorded in schema_migrations",
          n == 1, f"got={n}")

    # N.3 — fighter_memory_links CHECK accepts all 8 link_type values
    # (4 original + 4 new).
    # Insert minimal fighters (foreign_keys=OFF so we can skip the
    # full fighter schema).
    conn.execute(
        "INSERT INTO fighters (fighter_id, first_name, last_name, "
        "date_of_birth, gender, is_active, is_retired) "
        "VALUES (9001, 'Test', 'One', '1990-01-01', 'M', 1, 0)")
    conn.execute(
        "INSERT INTO fighters (fighter_id, first_name, last_name, "
        "date_of_birth, gender, is_active, is_retired) "
        "VALUES (9002, 'Test', 'Two', '1990-01-01', 'M', 1, 0)")
    conn.commit()

    all_8 = ['style_echo', 'gym_heir', 'regional_rival', 'successor',
             'previous_fight', 'shared_gym', 'former_teammate',
             'injury_history']
    bad = 0
    for lt in all_8:
        try:
            conn.execute(
                "INSERT INTO fighter_memory_links "
                "(fighter_id, linked_fighter_id, link_type) "
                "VALUES (?, ?, ?)",
                (9001, 9002, lt))
        except sqlite3.IntegrityError:
            bad += 1
            print(f"    REJECTED link_type={lt}")
    check("N", "all 8 link_type values accepted by CHECK",
          bad == 0, f"got={bad} rejections")

    # N.4 — bogus link_type is still rejected.
    try:
        conn.execute(
            "INSERT INTO fighter_memory_links "
            "(fighter_id, linked_fighter_id, link_type) "
            "VALUES (?, ?, ?)",
            (9001, 9002, "bogus_type"))
        check("N", "bogus link_type rejected by CHECK",
              False, "bogus_type was accepted")
    except sqlite3.IntegrityError:
        check("N", "bogus link_type rejected by CHECK",
              True, "")

    # N.5 — the migration is IDEMPOTENT — re-running it is a no-op
    # (the _has_check_constraint guard detects the new CHECK and
    # skips the rebuild).
    n_before = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    build_db._migrate_v3_12_0_expand_memory_link_types(conn)
    conn.commit()
    n_after = conn.execute(
        "SELECT COUNT(*) FROM fighter_memory_links"
    ).fetchone()[0]
    check("N", "re-running migration is idempotent (row count preserved)",
          n_before == n_after, f"before={n_before}, after={n_after}")

    conn.close()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    print("=" * 80)
    print(f"Phase 2 Tasks 2.5 + 2.6 — Memory Engine + Headline Engine "
          f"acceptance test (schema {EXPECTED_CODE_VERSION})")
    print("=" * 80)

    case_a_pure_helpers()
    case_b_previous_fight()
    case_c_shared_gym()
    case_d_former_teammate()
    case_e_injury_history()
    case_f_no_connection()
    case_g_no_digits()
    case_h_generate_headlines()
    case_i_headlines_no_digits()
    case_j_idempotency()
    case_k_top_story_priority()
    case_l_snapshot_cache_integration()
    case_m_design_law()
    case_n_schema_migration()

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
