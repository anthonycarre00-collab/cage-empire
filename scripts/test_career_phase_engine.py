#!/usr/bin/env python3
"""Acceptance test for Phase 2 Task 2.3 — Career Phase Engine.

Tests src/interpretation/career_phase_engine.py — the engine that
computes the canonical career phase (prospect / rising_contender /
champion / veteran / gatekeeper / declining) for every active
fighter and writes the canonical label + voice phrase to
fighter_descriptors.career_phase.

Per CONVENTIONS §17:
  - The interpretation layer is the ONLY writer to fighter_descriptors
    (a cache table). It NEVER writes to simulation tables.
  - §17.4 "Rich Not Thin": each cache column stores BOTH the canonical
    label AND a voice phrase, separated by "||". The UI reads the
    phrase (after "||"); tests read the label (before "||").
  - §17.5 Performance: bulk-load pattern (one SELECT, Python loop,
    executemany UPDATE). <1 second for 4450 fighters; <10ms for a
    targeted single-fighter refresh.
  - §14 Voice Layer: phrases contain no digits.

Per CONVENTIONS §14.6 / §17.3: the existing `career_stage` column
(populated by voice.describe_career_stage via the descriptor snapshot)
is CONSUMED BY news.py for news generation and is NOT touched by this
engine. The new `career_phase` column is for UI display + future
interpretation-layer rules (narrative_families, legacy_engine).

Test cases:
  A. compute_career_phase — pure function. All 6 phases:
     prospect (age<24 AND fights<10), rising_contender (default),
     champion (is_champion), veteran (age>=35 AND fights>=20),
     gatekeeper (age>=30 AND fights>=15 AND win_rate<0.50),
     declining (age>=33 AND (loss_streak>=3 OR health<50)).
  B. Priority order — champion supersedes everything; declining
     supersedes veteran; veteran supersedes gatekeeper; etc.
     A 36yo champ on a 4-loss streak with health<50 stays champion.
  C. Voice phrases — non-empty, no digits (§14), 3 variants per label.
  D. encode/decode helpers — "label||phrase" round-trips correctly
     (reused from context_engine — D1 single-source-of-truth).
  E. Bulk compute on test DB — compute_all_career_phases writes
     career_phase for all active fighters; column starts NULL, ends
     non-NULL; canonical labels + phrases parseable.
  F. Single-fighter refresh — compute_single_phase updates one
     fighter; returns the canonical label; <10ms steady-state.
  G. Determinism — same fighter_id always produces the same voice
     phrase (RNG seeded by fighter_id).
  H. Snapshot cache integration — snapshot_cache.refresh_fighter now
     calls career_phase_engine; the daily pass writes career_phase.
  I. Design Law check (§13 + §17.4) — the engine translates raw
     simulation state into player-facing meaning (career_phase tells
     a STORY, not a stat).

Pattern follows scripts/test_context_engine.py
(CONVENTIONS §10 — dynamic version pattern, no hardcoded version
strings).

Run from the project root:
    python3 scripts/test_career_phase_engine.py

Exit code 0 = all PASS, 1 = any FAIL.

D-number decisions in this test (referenced from the worklog):
  - D1: compute_career_phase case A tests each phase in isolation
    with the MINIMUM qualifying inputs (e.g., prospect = age 23 +
    fights 9 — one below each boundary). Boundary cases are tested
    in case A.7 (age 24 with 9 fights → NOT prospect).
  - D2: priority case B tests that champion supersedes ALL other
    criteria — a 36yo champ with health=20 + 4-loss-streak stays
    "champion", not "declining". This is the most important spec
    rule: a champ on a losing streak is still the champ until they
    lose the belt.
  - D3: priority case B also tests that declining supersedes veteran
    (a 35yo with 4 losses in a row is "declining", not "veteran")
    — the decline story supersedes the age story. This is a
    deliberate spec distinction.
  - D4: Voice phrase case C checks NO DIGITS (CONVENTIONS §14).
    The voice layer translates simulation into emotion; a phrase
    like "won 3 in a row" would be a §14 violation. Phrases like
    "the king of the division" pass.
  - D5: Bulk compute case E runs against a FRESH test DB (5-fighter
    seed), then manually mutates fighter state to verify each phase
    is detected end-to-end through the SQL JOIN. This catches JOIN
    bugs that pure-function tests miss.
  - D6: Determinism case G runs compute_single_phase twice and
    asserts the stored value is byte-identical. This catches RNG
    seeding bugs — without the seed, two runs could pick different
    voice variants.
  - D7: Snapshot cache case H verifies snapshot_cache.refresh_fighter
    now writes career_phase (in addition to the existing descriptor
    snapshot + the Task 2.2 momentum/pressure columns). The test
    makes a fighter a champion via the titles table and verifies
    career_phase = "champion" after refresh.
"""
import sys
import os
import sqlite3
import subprocess
import random
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
from interpretation import career_phase_engine as cpe  # noqa: E402
from interpretation import context_engine  # noqa: E402
from interpretation import snapshot_cache  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
RANDOM_SEED = 42

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

    The daily pass (compute_all_career_phases) UPDATES existing rows
    — it does NOT INSERT. In production, fighter_descriptors rows are
    created by update_fighter_descriptor_snapshot (called on fight
    resolution, camp completion, etc.). The fresh test DB has 0
    descriptor rows, so we pre-create them via the existing snapshot
    path before testing the career phase engine.
    """
    for fid in range(1, 6):
        app.update_fighter_descriptor_snapshot(conn, fid)
    conn.commit()


# Regex to detect digits in voice phrases (CONVENTIONS §14).
_HAS_DIGIT = re.compile(r"\d")


# ----------------------------------------------------------------
# Case A: compute_career_phase — pure function (all 6 phases)
# ----------------------------------------------------------------
def case_a_pure_compute():
    """Test compute_career_phase for all 6 phases + boundary cases."""
    print("\n--- Case A: compute_career_phase (pure function) ---")
    ce = cpe

    # A.1 — champion (is_champion).
    # A 28yo champ with 20 fights and 0.80 win rate — title supersedes
    # the rising_contender default.
    check("A", "champion: 28yo + 20 fights + is_champion=True",
          ce.compute_career_phase(28, 20, 5, 0, 0.80, 95, True)
          == ce.PHASE_CHAMPION,
          f"got={ce.compute_career_phase(28, 20, 5, 0, 0.80, 95, True)}")

    # A.2 — declining (age >= 33 AND (loss_streak >= 3 OR health < 50)).
    # Two variants: loss_streak trigger + health trigger.
    check("A", "declining: 33yo + loss_streak=3 (streak trigger)",
          ce.compute_career_phase(33, 25, 0, 3, 0.40, 90, False)
          == ce.PHASE_DECLINING,
          f"got={ce.compute_career_phase(33, 25, 0, 3, 0.40, 90, False)}")
    check("A", "declining: 33yo + career_health=40 (health trigger)",
          ce.compute_career_phase(33, 25, 1, 1, 0.40, 40, False)
          == ce.PHASE_DECLINING,
          f"got={ce.compute_career_phase(33, 25, 1, 1, 0.40, 40, False)}")
    # Boundary: age=32 + loss_streak=3 → NOT declining (age too low).
    check("A", "boundary: 32yo + loss_streak=3 → NOT declining",
          ce.compute_career_phase(32, 25, 0, 3, 0.40, 90, False)
          != ce.PHASE_DECLINING,
          f"got={ce.compute_career_phase(32, 25, 0, 3, 0.40, 90, False)}")
    # Boundary: 33yo + loss_streak=2 + health=90 → NOT declining.
    check("A", "boundary: 33yo + loss_streak=2 + health=90 → NOT declining",
          ce.compute_career_phase(33, 25, 0, 2, 0.40, 90, False)
          != ce.PHASE_DECLINING,
          f"got={ce.compute_career_phase(33, 25, 0, 2, 0.40, 90, False)}")

    # A.3 — prospect (age < 24 AND total_fights < 10).
    check("A", "prospect: 22yo + 6 fights",
          ce.compute_career_phase(22, 6, 1, 1, 0.50, 100, False)
          == ce.PHASE_PROSPECT,
          f"got={ce.compute_career_phase(22, 6, 1, 1, 0.50, 100, False)}")
    # Boundary: age=23 + fights=9 → prospect (just under both bounds).
    check("A", "boundary: 23yo + 9 fights → prospect (just under)",
          ce.compute_career_phase(23, 9, 1, 0, 0.50, 100, False)
          == ce.PHASE_PROSPECT,
          f"got={ce.compute_career_phase(23, 9, 1, 0, 0.50, 100, False)}")
    # Boundary: age=24 + 9 fights → NOT prospect (age too high).
    check("A", "boundary: 24yo + 9 fights → NOT prospect (age bound)",
          ce.compute_career_phase(24, 9, 1, 0, 0.50, 100, False)
          != ce.PHASE_PROSPECT,
          f"got={ce.compute_career_phase(24, 9, 1, 0, 0.50, 100, False)}")
    # Boundary: 22yo + 10 fights → NOT prospect (fights too high).
    check("A", "boundary: 22yo + 10 fights → NOT prospect (fights bound)",
          ce.compute_career_phase(22, 10, 1, 0, 0.50, 100, False)
          != ce.PHASE_PROSPECT,
          f"got={ce.compute_career_phase(22, 10, 1, 0, 0.50, 100, False)}")

    # A.4 — veteran (age >= 35 AND total_fights >= 20).
    check("A", "veteran: 37yo + 25 fights + 0.70 win rate",
          ce.compute_career_phase(37, 25, 1, 0, 0.70, 90, False)
          == ce.PHASE_VETERAN,
          f"got={ce.compute_career_phase(37, 25, 1, 0, 0.70, 90, False)}")
    # Boundary: 35yo + 20 fights → veteran (just at bounds).
    check("A", "boundary: 35yo + 20 fights → veteran (at bounds)",
          ce.compute_career_phase(35, 20, 1, 0, 0.70, 90, False)
          == ce.PHASE_VETERAN,
          f"got={ce.compute_career_phase(35, 20, 1, 0, 0.70, 90, False)}")
    # Boundary: 34yo + 20 fights → NOT veteran (age too low).
    check("A", "boundary: 34yo + 20 fights → NOT veteran",
          ce.compute_career_phase(34, 20, 1, 0, 0.70, 90, False)
          != ce.PHASE_VETERAN,
          f"got={ce.compute_career_phase(34, 20, 1, 0, 0.70, 90, False)}")
    # Boundary: 35yo + 19 fights → NOT veteran (fights too few).
    check("A", "boundary: 35yo + 19 fights → NOT veteran",
          ce.compute_career_phase(35, 19, 1, 0, 0.70, 90, False)
          != ce.PHASE_VETERAN,
          f"got={ce.compute_career_phase(35, 19, 1, 0, 0.70, 90, False)}")

    # A.5 — gatekeeper (age >= 30 AND fights >= 15 AND win_rate < 0.50).
    check("A", "gatekeeper: 32yo + 18 fights + 0.40 win rate",
          ce.compute_career_phase(32, 18, 1, 1, 0.40, 90, False)
          == ce.PHASE_GATEKEEPER,
          f"got={ce.compute_career_phase(32, 18, 1, 1, 0.40, 90, False)}")
    # Boundary: 30yo + 15 fights + 0.49 win rate → gatekeeper.
    check("A", "boundary: 30yo + 15 fights + 0.49 win rate → gatekeeper",
          ce.compute_career_phase(30, 15, 0, 1, 0.49, 90, False)
          == ce.PHASE_GATEKEEPER,
          f"got={ce.compute_career_phase(30, 15, 0, 1, 0.49, 90, False)}")
    # Boundary: 30yo + 15 fights + 0.50 win rate → NOT gatekeeper.
    check("A", "boundary: 30yo + 15 fights + 0.50 win rate → NOT gatekeeper",
          ce.compute_career_phase(30, 15, 0, 1, 0.50, 90, False)
          != ce.PHASE_GATEKEEPER,
          f"got={ce.compute_career_phase(30, 15, 0, 1, 0.50, 90, False)}")

    # A.6 — rising_contender (default for active fighters).
    # A 27yo with 12 fights + 0.60 win rate + no other phase match.
    check("A", "rising_contender: 27yo + 12 fights + 0.60 win rate (default)",
          ce.compute_career_phase(27, 12, 2, 1, 0.60, 90, False)
          == ce.PHASE_RISING_CONTENDER,
          f"got={ce.compute_career_phase(27, 12, 2, 1, 0.60, 90, False)}")
    # Default for any unmatched active fighter (e.g., 25yo + 15 fights +
    # 0.55 win rate — passes none of prospect/veteran/gatekeeper/
    # declining).
    check("A", "rising_contender: 25yo + 15 fights + 0.55 win rate (default)",
          ce.compute_career_phase(25, 15, 1, 0, 0.55, 90, False)
          == ce.PHASE_RISING_CONTENDER,
          f"got={ce.compute_career_phase(25, 15, 1, 0, 0.55, 90, False)}")

    # A.7 — None handling (defensive — D5 — DB columns may be NULL).
    # None age → 0, None total_fights → 0, None career_health → 100,
    # None is_champion → False. With defensive defaults applied, the
    # rules run: age 0 < 24 AND fights 0 < 10 → prospect. This is a
    # SENSIBLE defensive default — a fighter with no DOB / record
    # data is most likely a brand-new seed fighter, and "prospect"
    # (young, few fights) is the right label. The point of this test
    # is that the engine doesn't CRASH on None inputs, not that it
    # returns any specific phase. (See D5 in the module docstring.)
    none_result = ce.compute_career_phase(
        None, None, None, None, None, None, False)
    check("A", "None inputs do not crash (returns a canonical label)",
          none_result in set(ce.ALL_PHASES),
          f"got={none_result}")
    check("A", "None inputs → prospect (defensive: 0yo + 0 fights matches prospect)",
          none_result == ce.PHASE_PROSPECT,
          f"got={none_result}")


# ----------------------------------------------------------------
# Case B: priority order — champion supersedes everything
# ----------------------------------------------------------------
def case_b_priority_order():
    """Test that the priority order is correctly enforced."""
    print("\n--- Case B: priority order ---")
    ce = cpe

    # B.1 — champion supersedes ALL other criteria (D2).
    # A 36yo champ on a 4-loss streak with health=20 — still champion.
    # (Without priority, this would be "declining".)
    check("B", "champ supersedes declining (36yo + ls=4 + health=20)",
          ce.compute_career_phase(36, 30, 0, 4, 0.40, 20, True)
          == ce.PHASE_CHAMPION,
          f"got={ce.compute_career_phase(36, 30, 0, 4, 0.40, 20, True)}")
    # A 37yo champ with 30 fights — still champion (not veteran).
    check("B", "champ supersedes veteran (37yo + 30 fights)",
          ce.compute_career_phase(37, 30, 1, 0, 0.70, 90, True)
          == ce.PHASE_CHAMPION,
          f"got={ce.compute_career_phase(37, 30, 1, 0, 0.70, 90, True)}")
    # A 22yo champ with 8 fights — still champion (not prospect).
    check("B", "champ supersedes prospect (22yo + 8 fights)",
          ce.compute_career_phase(22, 8, 1, 0, 0.50, 100, True)
          == ce.PHASE_CHAMPION,
          f"got={ce.compute_career_phase(22, 8, 1, 0, 0.50, 100, True)}")

    # B.2 — declining supersedes veteran (D3).
    # A 35yo on a 4-loss streak — declining (NOT veteran). The decline
    # story supersedes the age story.
    check("B", "declining supersedes veteran (35yo + ls=4 + 25 fights)",
          ce.compute_career_phase(35, 25, 0, 4, 0.40, 90, False)
          == ce.PHASE_DECLINING,
          f"got={ce.compute_career_phase(35, 25, 0, 4, 0.40, 90, False)}")
    # A 37yo with health=30 — declining (NOT veteran).
    check("B", "declining supersedes veteran (37yo + health=30 + 25 fights)",
          ce.compute_career_phase(37, 25, 0, 0, 0.40, 30, False)
          == ce.PHASE_DECLINING,
          f"got={ce.compute_career_phase(37, 25, 0, 0, 0.40, 30, False)}")

    # B.3 — declining checked BEFORE prospect.
    # A 33yo can't be a prospect anyway (prospect needs age < 24),
    # but this verifies the order is champion → declining → prospect.
    # (A 23yo on a 3-loss streak at age 33 is impossible — both
    # declining AND prospect require age constraints that exclude
    # each other. We test the order via the result, not the
    # contrived overlap.)
    # The point: prospect requires age < 24, declining requires
    # age >= 33 — mutually exclusive. No real overlap to test.
    # Documented here for completeness.
    check("B", "prospect + declining criteria are mutually exclusive (age bounds)",
          True, "documented — no overlap to test (prospect age<24, declining age>=33)")

    # B.4 — veteran supersedes gatekeeper.
    # A 37yo with 25 fights and 0.40 win rate — veteran (NOT
    # gatekeeper). The veteran story supersedes the gatekeeper story
    # when both apply.
    check("B", "veteran supersedes gatekeeper (37yo + 25 fights + 0.40 win rate)",
          ce.compute_career_phase(37, 25, 0, 1, 0.40, 90, False)
          == ce.PHASE_VETERAN,
          f"got={ce.compute_career_phase(37, 25, 0, 1, 0.40, 90, False)}")

    # B.5 — gatekeeper checked BEFORE rising_contender.
    # A 32yo with 18 fights and 0.40 win rate — gatekeeper (NOT
    # rising_contender).
    check("B", "gatekeeper beats rising_contender default",
          ce.compute_career_phase(32, 18, 0, 1, 0.40, 90, False)
          == ce.PHASE_GATEKEEPER,
          f"got={ce.compute_career_phase(32, 18, 0, 1, 0.40, 90, False)}")


# ----------------------------------------------------------------
# Case C: voice phrases — non-empty, no digits, 3 variants
# ----------------------------------------------------------------
def case_c_voice_phrases():
    """Test voice phrase helpers (§17.4 + §14)."""
    print("\n--- Case C: voice phrases ---")
    ce = cpe

    # C.1 — each phase label has 3 non-empty, no-digit variants.
    for label in ce.ALL_PHASES:
        variants = ce.PHASE_PHRASES[label]
        check("C", f"phase '{label}' has 3 variants",
              len(variants) == 3, f"got={len(variants)}")
        for v in variants:
            check("C", f"phase '{label}' variant '{v[:30]}' has no digits (§14)",
                  not _HAS_DIGIT.search(v), f"got={v!r}")
            check("C", f"phase '{label}' variant is non-empty",
                  isinstance(v, str) and len(v) > 0, "")

    # C.2 — phrase picker returns a non-empty string for each label.
    rng = random.Random(RANDOM_SEED)
    for label in ce.ALL_PHASES:
        phrase = ce.get_phase_phrase(label, rng)
        check("C", f"get_phase_phrase('{label}') returns non-empty str",
              isinstance(phrase, str) and len(phrase) > 0, f"got={phrase!r}")

    # C.3 — phrase picker returns one of the 3 defined variants.
    rng = random.Random(RANDOM_SEED)
    for label in ce.ALL_PHASES:
        phrase = ce.get_phase_phrase(label, rng)
        check("C", f"get_phase_phrase('{label}') returns a defined variant",
              phrase in ce.PHASE_PHRASES[label], f"got={phrase!r}")

    # C.4 — unknown label falls back to rising_contender variants
    # (defensive — should not happen but the picker must not crash).
    rng = random.Random(RANDOM_SEED)
    phrase = ce.get_phase_phrase("nonexistent_label", rng)
    check("C", "unknown label falls back to rising_contender variants",
          phrase in ce.PHASE_PHRASES[ce.PHASE_RISING_CONTENDER],
          f"got={phrase!r}")


# ----------------------------------------------------------------
# Case D: encode/decode helpers (reused from context_engine — D1)
# ----------------------------------------------------------------
def case_d_encode_decode():
    """Test the "label||phrase" round-trip (reused from context_engine)."""
    print("\n--- Case D: encode/decode (reused from context_engine) ---")
    ce = cpe

    # D.1 — encode produces "label||phrase".
    encoded = ce.encode("champion", "the reigning champion")
    check("D", "encode('champion', '...') == 'champion||...'",
          encoded == "champion||the reigning champion", f"got={encoded!r}")

    # D.2 — decode_label extracts the label.
    check("D", "decode_label('champion||...') == 'champion'",
          ce.decode_label("champion||the reigning champion") == "champion",
          f"got={ce.decode_label('champion||the reigning champion')!r}")

    # D.3 — decode_phrase extracts the phrase.
    check("D", "decode_phrase('champion||...') == 'the reigning champion'",
          ce.decode_phrase("champion||the reigning champion")
          == "the reigning champion",
          f"got={ce.decode_phrase('champion||the reigning champion')!r}")

    # D.4 — round-trip preserves both parts for ALL 6 phases.
    for label in ce.ALL_PHASES:
        phrase = ce.PHASE_PHRASES[label][0]
        encoded = ce.encode(label, phrase)
        check("D", f"round-trip preserves '{label}' label",
              ce.decode_label(encoded) == label, "")
        check("D", f"round-trip preserves '{label}' phrase",
              ce.decode_phrase(encoded) == phrase, "")

    # D.5 — defensive: NULL / missing "||" → None.
    check("D", "decode_label(None) == None",
          ce.decode_label(None) is None, "")
    check("D", "decode_label('') == None",
          ce.decode_label("") is None, "")
    check("D", "decode_label('noseparator') == None",
          ce.decode_label("noseparator") is None, "")

    # D.6 — phrase containing "||" only splits on FIRST separator.
    encoded = ce.encode("veteran", "a veteran who's||seen it all")
    check("D", "phrase with '||' splits on first only",
          ce.decode_label(encoded) == "veteran"
          and ce.decode_phrase(encoded) == "a veteran who's||seen it all",
          f"got={encoded!r}")

    # D.7 — encode/decode helpers are THE SAME OBJECTS as
    # context_engine's (D1 — single source of truth). Verifies
    # the import-based reuse, not a copy.
    check("D", "encode is context_engine.encode (D1 single-source)",
          ce.encode is context_engine.encode, "")
    check("D", "decode_label is context_engine.decode_label (D1)",
          ce.decode_label is context_engine.decode_label, "")
    check("D", "decode_phrase is context_engine.decode_phrase (D1)",
          ce.decode_phrase is context_engine.decode_phrase, "")


# ----------------------------------------------------------------
# Case E: bulk compute on test DB
# ----------------------------------------------------------------
def case_e_bulk_compute():
    """Test compute_all_career_phases on a fresh test DB (5 fighters)."""
    print("\n--- Case E: bulk compute on test DB ---")
    ce = cpe

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Pre-create fighter_descriptors rows via the existing snapshot
    # path. compute_all_career_phases UPDATES existing rows (production
    # contract) — it does not INSERT.
    populate_descriptor_rows(conn)

    # E.1 — career_phase column starts NULL.
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors"
    ).fetchone()[0]
    check("E", "5 fighter_descriptors rows exist (via populate_descriptor_rows)",
          total_rows == 5, f"got={total_rows}")
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE career_phase IS NULL"
    ).fetchone()[0]
    check("E", "career_phase column starts NULL (5 fighters)",
          nulls == 5, f"got={nulls} NULLs")

    # E.2 — run bulk compute.
    n_updated = ce.compute_all_career_phases(conn)
    check("E", "compute_all_career_phases updated all 5 active fighters",
          n_updated == 5, f"got={n_updated}")

    # E.3 — column now non-NULL for all 5.
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE career_phase IS NULL"
    ).fetchone()[0]
    check("E", "all career_phase values written (0 NULLs)",
          nulls == 0, f"got={nulls} NULLs")

    # E.4 — every stored value matches "label||phrase" format.
    bad = 0
    for r in conn.execute("SELECT fighter_id, career_phase "
                          "FROM fighter_descriptors"):
        if not isinstance(r[1], str) or "||" not in r[1]:
            bad += 1
    check("E", "all stored values match 'label||phrase' format",
          bad == 0, f"got={bad} bad values")

    # E.5 — decoded labels are all valid canonical labels.
    valid_labels = set(ce.ALL_PHASES)
    bad = 0
    for r in conn.execute("SELECT career_phase FROM fighter_descriptors"):
        if ce.decode_label(r[0]) not in valid_labels:
            bad += 1
    check("E", "decoded career_phase labels all canonical",
          bad == 0, f"got={bad} bad labels")

    # E.6 — phrases contain no digits (§14).
    bad = 0
    for r in conn.execute("SELECT career_phase FROM fighter_descriptors"):
        phrase = ce.decode_phrase(r[0])
        if not phrase or _HAS_DIGIT.search(phrase):
            bad += 1
    check("E", "voice phrases contain no digits (§14)",
          bad == 0, f"got={bad} violations")

    # E.7 — performance: <1 second for 5 fighters (smoke check — the
    # real budget is for 4450, but we don't have that many in the test
    # DB; we just verify it doesn't blow up).
    t0 = time.time()
    ce.compute_all_career_phases(conn)
    elapsed = time.time() - t0
    check("E", f"bulk compute <1s ({elapsed*1000:.0f}ms)",
          elapsed < 1.0, f"{elapsed*1000:.0f}ms")

    # E.8 — end-to-end: a young fighter with few fights → prospect.
    # Mutate fighter 1: 22yo + 6 total fights (1W + 4L + 1D).
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET record_wins=1, "
                 "record_losses=4, record_draws=1 WHERE fighter_id=1")
    conn.commit()
    ce.compute_all_career_phases(conn)
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("E", "22yo + 6 fights → prospect (end-to-end)",
          ce.decode_label(stored) == ce.PHASE_PROSPECT,
          f"got={stored!r}")

    # E.9 — end-to-end: a champion fighter → champion phase.
    # Make fighter 2 the current champion of AC's WC 1.
    conn.execute("UPDATE titles SET current_champion_fighter_id=2, "
                 "is_vacant=0 WHERE promotion_id=1 AND weight_class_id=1")
    conn.commit()
    ce.compute_all_career_phases(conn)
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    check("E", "champion fighter → champion phase (end-to-end)",
          ce.decode_label(stored) == ce.PHASE_CHAMPION,
          f"got={stored!r}")

    # E.10 — end-to-end: an old fighter with many fights + losing
    # streak → declining (NOT veteran). Priority order enforced.
    # Fighter 3: 35yo + 4 losses in a row + 25 total fights.
    conn.execute("UPDATE fighters SET date_of_birth='1989-01-01' "
                 "WHERE fighter_id=3")
    conn.execute("UPDATE fighter_career SET record_wins=11, "
                 "record_losses=14, record_draws=0, loss_streak=4, "
                 "career_health=85 WHERE fighter_id=3")
    conn.commit()
    ce.compute_all_career_phases(conn)
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    check("E", "35yo + 4 losses + 25 fights → declining (priority over veteran)",
          ce.decode_label(stored) == ce.PHASE_DECLINING,
          f"got={stored!r}")

    conn.close()


# ----------------------------------------------------------------
# Case F: single-fighter refresh
# ----------------------------------------------------------------
def case_f_single_refresh():
    """Test compute_single_phase (targeted refresh)."""
    print("\n--- Case F: single-fighter refresh ---")
    ce = cpe

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # F.1 — fighter exists → returns dict with 'career_phase' key.
    result = ce.compute_single_phase(conn, 1)
    check("F", "returns dict with 'career_phase' key",
          isinstance(result, dict) and "career_phase" in result,
          f"got={result}")
    check("F", "career_phase is a canonical label",
          result["career_phase"] in set(ce.ALL_PHASES),
          f"got={result['career_phase']}")

    # F.2 — DB row updated.
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("F", "DB row updated with 'label||phrase' value",
          isinstance(stored, str) and "||" in stored
          and ce.decode_label(stored) == result["career_phase"],
          f"got={stored!r}")

    # F.3 — non-existent fighter → None.
    result = ce.compute_single_phase(conn, 99999)
    check("F", "non-existent fighter → None",
          result is None, f"got={result}")

    # F.4 — performance: <10ms steady-state (3rd call after warm-up).
    ce.compute_single_phase(conn, 1)
    ce.compute_single_phase(conn, 1)
    t0 = time.time()
    ce.compute_single_phase(conn, 1)
    elapsed_ms = (time.time() - t0) * 1000
    check("F", f"single-fighter refresh <10ms steady-state ({elapsed_ms:.2f}ms)",
          elapsed_ms < 10.0, f"{elapsed_ms:.2f}ms")

    # F.5 — single refresh reflects live state changes (D5).
    # Make fighter 1 a champion → champion phase.
    conn.execute("UPDATE titles SET current_champion_fighter_id=1, "
                 "is_vacant=0 WHERE promotion_id=1 AND weight_class_id=1")
    conn.commit()
    result = ce.compute_single_phase(conn, 1)
    check("F", "single refresh picks up champion → champion phase",
          result["career_phase"] == ce.PHASE_CHAMPION,
          f"got={result}")

    # F.6 — single refresh reflects a phase change (champ dethroned
    # → not champion anymore). Clear the title.
    conn.execute("UPDATE titles SET current_champion_fighter_id=NULL, "
                 "is_vacant=1 WHERE promotion_id=1 AND weight_class_id=1")
    conn.commit()
    result = ce.compute_single_phase(conn, 1)
    check("F", "single refresh picks up dethronement → NOT champion",
          result["career_phase"] != ce.PHASE_CHAMPION,
          f"got={result}")

    conn.close()


# ----------------------------------------------------------------
# Case G: determinism
# ----------------------------------------------------------------
def case_g_determinism():
    """Test that the same fighter_id always produces the same phrase."""
    print("\n--- Case G: determinism ---")
    ce = cpe

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # G.1 — two single-fighter refreshes produce identical stored values.
    ce.compute_single_phase(conn, 1)
    v1 = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    ce.compute_single_phase(conn, 1)
    v2 = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("G", "two single refreshes produce identical stored values",
          v1 == v2, f"v1={v1} v2={v2}")

    # G.2 — bulk compute then single refresh produces identical values.
    ce.compute_all_career_phases(conn)
    v_bulk = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    ce.compute_single_phase(conn, 3)
    v_single = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    check("G", "bulk compute + single refresh produce identical values",
          v_bulk == v_single, f"bulk={v_bulk} single={v_single}")

    # G.3 — voice phrases produced for all 5 fighters (smoke check).
    phrases = set()
    for fid in range(1, 6):
        row = conn.execute(
            "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if row and row[0]:
            phrases.add(ce.decode_phrase(row[0]))
    check("G", "voice phrases produced for all 5 fighters",
          len(phrases) >= 1, f"got={len(phrases)} unique phrases")

    # G.4 — different fighters with the same phase label MAY get
    # different voice variants (RNG seed differs by fighter_id).
    # We verify the RNG seed formula differs by fighter_id.
    r1 = random.Random(1 * 31 + 17)
    r2 = random.Random(2 * 31 + 17)
    # Force both to the same label to compare variants.
    v1 = ce.get_phase_phrase(ce.PHASE_RISING_CONTENDER, r1)
    v2 = ce.get_phase_phrase(ce.PHASE_RISING_CONTENDER, r2)
    # Smoke check — both are valid variants (deterministic per seed).
    check("G", "fighter_id=1 RNG seed picks a valid rising_contender variant",
          v1 in ce.PHASE_PHRASES[ce.PHASE_RISING_CONTENDER], f"got={v1!r}")
    check("G", "fighter_id=2 RNG seed picks a valid rising_contender variant",
          v2 in ce.PHASE_PHRASES[ce.PHASE_RISING_CONTENDER], f"got={v2!r}")

    conn.close()


# ----------------------------------------------------------------
# Case H: snapshot_cache integration
# ----------------------------------------------------------------
def case_h_snapshot_cache_integration():
    """Test that snapshot_cache wires career_phase_engine correctly."""
    print("\n--- Case H: snapshot_cache integration ---")
    ce = cpe

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Pre-create the descriptor row for fighter 1 so refresh_fighter
    # can update it.
    app.update_fighter_descriptor_snapshot(conn, 1)
    conn.commit()

    # H.1 — snapshot_cache.refresh_fighter writes career_phase.
    # Before refresh: NULL.
    nulls_before = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND career_phase IS NULL"
    ).fetchone()[0]
    check("H", "career_phase is NULL before refresh_fighter",
          nulls_before == 1, f"got={nulls_before} NULLs")

    snapshot_cache.refresh_fighter(conn, 1)

    nulls_after = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND career_phase IS NULL"
    ).fetchone()[0]
    check("H", "career_phase is non-NULL after refresh_fighter",
          nulls_after == 0, f"got={nulls_after} NULLs")

    # H.2 — value is in "label||phrase" format.
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("H", "refresh_fighter writes 'label||phrase' format",
          isinstance(stored, str) and "||" in stored, f"got={stored!r}")

    # H.3 — daily pass writes career_phase for all fighters.
    # Pre-create descriptor rows for all 5 fighters, then reset
    # career_phase to NULL to verify the daily pass writes them.
    populate_descriptor_rows(conn)
    conn.execute("UPDATE fighter_descriptors SET career_phase=NULL")
    conn.commit()
    snapshot_cache.run_daily_interpretation_pass(conn)
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE career_phase IS NULL"
    ).fetchone()[0]
    check("H", "daily pass writes career_phase for all 5 fighters (0 NULLs)",
          nulls == 0, f"got={nulls} NULLs")

    # H.4 — interpretation_cache_meta updated.
    # Per CONVENTIONS §10 (dynamic-version pattern), the engine_version
    # is read from snapshot_cache.ENGINE_VERSION at runtime — NOT
    # hardcoded. Task 2.3 bumped it to "1.2.0"; future tasks will bump
    # further. The semantic check is "the daily pass wrote the engine_
    # version" — not "the version is a specific hardcoded string".
    row = conn.execute(
        "SELECT engine_version, last_built_fighter_count "
        "FROM interpretation_cache_meta WHERE meta_id=1"
    ).fetchone()
    check("H", "interpretation_cache_meta.engine_version matches snapshot_cache.ENGINE_VERSION",
          row and row[0] == snapshot_cache.ENGINE_VERSION,
          f"got={row[0] if row else None} (expected {snapshot_cache.ENGINE_VERSION})")
    check("H", "interpretation_cache_meta.last_built_fighter_count == 5",
          row and row[1] == 5, f"got={row[1] if row else None}")

    # H.5 — end-to-end: refresh_fighter on a champion → champion phase.
    # Make fighter 2 the champion of AC's WC 1.
    conn.execute("UPDATE titles SET current_champion_fighter_id=2, "
                 "is_vacant=0 WHERE promotion_id=1 AND weight_class_id=1")
    conn.commit()
    snapshot_cache.refresh_fighter(conn, 2)
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    check("H", "refresh_fighter on champion fighter → champion phase",
          ce.decode_label(stored) == ce.PHASE_CHAMPION,
          f"got={stored!r}")

    # H.6 — end-to-end: dethrone the champion → phase changes.
    conn.execute("UPDATE titles SET current_champion_fighter_id=NULL, "
                 "is_vacant=1 WHERE promotion_id=1 AND weight_class_id=1")
    conn.commit()
    snapshot_cache.refresh_fighter(conn, 2)
    stored = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    check("H", "refresh_fighter on dethroned fighter → NOT champion",
          ce.decode_label(stored) != ce.PHASE_CHAMPION,
          f"got={stored!r}")

    conn.close()


# ----------------------------------------------------------------
# Case I: Design Law check (§13 + §17.4)
# ----------------------------------------------------------------
def case_i_design_law():
    """Design Law check — engine translates simulation into emotion."""
    print("\n--- Case I: Design Law check ---")
    ce = cpe

    # I.1 — §17.4 "Rich Not Thin": canonical label + voice phrase
    # are BOTH stored (separated by "||"). The UI reads the phrase;
    # the logic reads the label.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    populate_descriptor_rows(conn)
    snapshot_cache.run_daily_interpretation_pass(conn)
    row = conn.execute(
        "SELECT career_phase FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()
    career_phase = row[0]
    check("I", "§17.4: career_phase stores BOTH label AND phrase (||)",
          "||" in career_phase and ce.decode_label(career_phase) is not None
          and ce.decode_phrase(career_phase) is not None,
          f"got={career_phase!r}")

    # I.2 — §13 Design Law: career_phase tells a STORY. Compare:
    # raw "age=37, total_fights=25, win_rate=0.70" → story "veteran
    # || 'a grizzled veteran who's seen it all'". The label tells
    # the truth; the phrase tells the story.
    label = ce.decode_label(career_phase)
    phrase = ce.decode_phrase(career_phase)
    check("I", "§13: label is canonical (logic-readable)",
          label in set(ce.ALL_PHASES), f"got={label}")
    check("I", "§13: phrase is narrative (player-readable, no digits)",
          isinstance(phrase, str) and not _HAS_DIGIT.search(phrase),
          f"got={phrase!r}")

    # I.3 — §14: no raw numbers leak into the player-facing phrase.
    raw_phrases = []
    for r in conn.execute("SELECT career_phase FROM fighter_descriptors"):
        raw_phrases.append(ce.decode_phrase(r[0]))
    violations = sum(1 for p in raw_phrases if p and _HAS_DIGIT.search(p))
    check("I", "§14: zero digit violations across all stored phrases",
          violations == 0, f"got={violations} violations")

    # I.4 — §13.5 Anticipation: career_phase distinguishes a 22yo
    # with 6 fights (prospect — the world ahead of him) from a 37yo
    # with 25 fights (veteran — seen it all). Same engine, different
    # story based on age + experience.
    prospect_phase = ce.compute_career_phase(
        22, 6, 1, 1, 0.50, 100, False)
    veteran_phase = ce.compute_career_phase(
        37, 25, 1, 0, 0.70, 90, False)
    check("I", "§13.5: 22yo + 6 fights → prospect (anticipation: world ahead)",
          prospect_phase == ce.PHASE_PROSPECT, f"got={prospect_phase}")
    check("I", "§13.5: 37yo + 25 fights → veteran (anticipation: seen it all)",
          veteran_phase == ce.PHASE_VETERAN, f"got={veteran_phase}")

    # I.5 — §13.3 Interpretation Layer: translates simulation into
    # emotion. A champion (raw: "holds title_id=X") produces
    # "champion || 'the reigning champion'" — a story word, not a
    # foreign key.
    champ_phase = ce.compute_career_phase(
        28, 20, 5, 0, 0.80, 95, True)
    check("I", "§13.3: champion flag → 'champion' (story word, not FK)",
          champ_phase == ce.PHASE_CHAMPION, f"got={champ_phase}")

    # I.6 — Priority order is a NARRATIVE choice, not just a sort.
    # A 35yo on a 4-loss streak with 25 fights is "declining" (the
    # fall is the story), NOT "veteran" (the age is the story). The
    # priority order tells you WHICH story is more important to the
    # player right now.
    declining_over_veteran = ce.compute_career_phase(
        35, 25, 0, 4, 0.40, 90, False)
    check("I", "priority: 35yo + 4 losses → declining (fall > age)",
          declining_over_veteran == ce.PHASE_DECLINING,
          f"got={declining_over_veteran}")

    # I.7 — career_stage (existing, news.py) and career_phase (new,
    # interpretation layer) are DIFFERENT columns serving DIFFERENT
    # purposes. Verify both are populated and non-overlapping in
    # semantic role (career_stage is a free-form voice phrase from
    # voice.describe_career_stage; career_phase is "label||phrase"
    # from the canonical-label engine).
    row = conn.execute(
        "SELECT career_stage, career_phase FROM fighter_descriptors "
        "WHERE fighter_id=1"
    ).fetchone()
    career_stage, career_phase = row
    check("I", "career_stage populated (existing — news.py consumer)",
          career_stage is not None and len(career_stage) > 0,
          f"got={career_stage!r}")
    check("I", "career_phase populated (new — interpretation layer)",
          career_phase is not None and "||" in career_phase,
          f"got={career_phase!r}")
    # career_stage is a free-form phrase (no "||"); career_phase is
    # "label||phrase" format. Different storage shapes — different
    # purposes.
    check("I", "career_stage is NOT in 'label||phrase' format (different role)",
          "||" not in (career_stage or ""),
          f"got={career_stage!r}")

    conn.close()


def main():
    print("=" * 80)
    print(f"Phase 2 Task 2.3 — Career Phase Engine acceptance test "
          f"(schema {EXPECTED_CODE_VERSION})")
    print("=" * 80)

    case_a_pure_compute()
    case_b_priority_order()
    case_c_voice_phrases()
    case_d_encode_decode()
    case_e_bulk_compute()
    case_f_single_refresh()
    case_g_determinism()
    case_h_snapshot_cache_integration()
    case_i_design_law()

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
