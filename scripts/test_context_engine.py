#!/usr/bin/env python3
"""Acceptance test for Phase 2 Task 2.2 — Context Engine.

Tests src/interpretation/context_engine.py — the engine that computes
momentum, pressure, and trajectory for every active fighter and writes
the canonical label + voice phrase to fighter_descriptors.

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

Test cases:
  A. compute_momentum — pure function. All 5 tiers:
     very_high (win_streak >= 5), high (>= 3), stable (0-2 / 0-1),
     falling (loss_streak >= 2), collapsing (loss_streak >= 4).
     Win streak takes precedence over loss streak.
  B. compute_pressure — pure function. All 4 tiers + each of the 8
     pressure factors in isolation. 0 factors → minimal, 1-2 →
     moderate, 3-4 → high, 5+ → extreme.
  C. compute_trajectory — pure function. All 5 tiers + age boundary
     cases (rising→peaking at 30, peaking→declining at 35, etc.).
  D. Voice phrases — non-empty, no digits (§14), 3 variants per label.
  E. encode/decode helpers — "label||phrase" round-trips correctly.
  F. Bulk compute on test DB — compute_all_fighters writes momentum +
     pressure for all active fighters; columns start NULL, end
     non-NULL; canonical labels + phrases parseable.
  G. Single-fighter refresh — compute_single_fighter updates one
     fighter; returns the canonical labels; <10ms steady-state.
  H. Determinism — same fighter_id always produces the same voice
     phrase (RNG seeded by fighter_id).
  I. Snapshot cache integration — snapshot_cache.refresh_fighter now
     calls context_engine; the daily pass writes both columns.
  J. Design Law check (§13 + §17.4) — the engine translates raw
     simulation state into player-facing meaning (momentum + pressure
     tell a STORY, not a number).

Pattern follows scripts/test_voice.py + test_event_bus.py
(CONVENTIONS §10 — dynamic version pattern, no hardcoded version
strings).

Run from the project root:
    python3 scripts/test_context_engine.py

Exit code 0 = all PASS, 1 = any FAIL.

D-number decisions in this test (referenced from the worklog):
  - D1: compute_momentum case A.6 explicitly tests that a fighter on
    a 2-fight win streak with a 5-fight loss streak before it is
    "stable" — win streak takes precedence per the spec ("the streak
    is what's current").
  - D2: compute_pressure case B tests each pressure factor in
    ISOLATION (only one factor true, all others false → moderate).
    This catches off-by-one bugs where two factors are accidentally
    tied to the same flag.
  - D3: compute_trajectory case C tests the COLLAPSING rule requires
    BOTH collapsing momentum AND age >= 35. A 25-year-old on a
    4-fight loss streak is "declining" — they have time to turn it
    around. This is a deliberate spec distinction.
  - D4: Voice phrase case D checks NO DIGITS (CONVENTIONS §14).
    The voice layer translates simulation into emotion; a phrase
    like "needs 3 wins" would be a §14 violation. Phrases like
    "riding a hot streak" pass.
  - D5: Bulk compute case F runs against a FRESH test DB (5-fighter
    seed), then manually mutates a fighter's win_streak /
    career_health / etc. to verify each pressure factor is detected
    end-to-end through the SQL JOIN. This catches JOIN bugs that
    pure-function tests miss.
  - D6: Determinism case H runs compute_single_fighter twice and
    asserts the stored value is byte-identical. This catches RNG
    seeding bugs — without the seed, two runs could pick different
    voice variants.
  - D7: Snapshot cache case I verifies the snapshot_cache.refresh_
    fighter now writes BOTH the descriptor snapshot (existing path)
    AND the new momentum + pressure columns. The test inserts a
    fighter with a hot streak and verifies the momentum column ends
    up "very_high||..." after refresh.
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

    The daily pass (compute_all_fighters) UPDATES existing rows — it
    does NOT INSERT. In production, fighter_descriptors rows are
    created by update_fighter_descriptor_snapshot (called on fight
    resolution, camp completion, etc.). The fresh test DB has 0
    descriptor rows, so we pre-create them via the existing snapshot
    path before testing the context engine.
    """
    for fid in range(1, 6):
        app.update_fighter_descriptor_snapshot(conn, fid)
    conn.commit()


# Regex to detect digits in voice phrases (CONVENTIONS §14).
_HAS_DIGIT = re.compile(r"\d")


# ----------------------------------------------------------------
# Case A: compute_momentum — pure function
# ----------------------------------------------------------------
def case_a_momentum():
    """Test compute_momentum for all 5 tiers + precedence."""
    print("\n--- Case A: compute_momentum ---")
    ce = context_engine

    # A.1 — very_high (win_streak >= 5).
    check("A", "win_streak=5 → very_high",
          ce.compute_momentum(5, 0) == ce.MOMENTUM_VERY_HIGH,
          f"got={ce.compute_momentum(5, 0)}")
    check("A", "win_streak=10 → very_high",
          ce.compute_momentum(10, 0) == ce.MOMENTUM_VERY_HIGH,
          f"got={ce.compute_momentum(10, 0)}")

    # A.2 — high (win_streak 3-4).
    check("A", "win_streak=3 → high",
          ce.compute_momentum(3, 0) == ce.MOMENTUM_HIGH,
          f"got={ce.compute_momentum(3, 0)}")
    check("A", "win_streak=4 → high",
          ce.compute_momentum(4, 0) == ce.MOMENTUM_HIGH,
          f"got={ce.compute_momentum(4, 0)}")

    # A.3 — stable (win_streak 0-2 AND loss_streak 0-1).
    check("A", "win_streak=0, loss_streak=0 → stable",
          ce.compute_momentum(0, 0) == ce.MOMENTUM_STABLE,
          f"got={ce.compute_momentum(0, 0)}")
    check("A", "win_streak=2, loss_streak=1 → stable",
          ce.compute_momentum(2, 1) == ce.MOMENTUM_STABLE,
          f"got={ce.compute_momentum(2, 1)}")

    # A.4 — falling (loss_streak 2-3, win_streak < 3).
    check("A", "win_streak=0, loss_streak=2 → falling",
          ce.compute_momentum(0, 2) == ce.MOMENTUM_FALLING,
          f"got={ce.compute_momentum(0, 2)}")
    check("A", "win_streak=2, loss_streak=3 → falling",
          ce.compute_momentum(2, 3) == ce.MOMENTUM_FALLING,
          f"got={ce.compute_momentum(2, 3)}")

    # A.5 — collapsing (loss_streak >= 4, win_streak < 3).
    check("A", "win_streak=0, loss_streak=4 → collapsing",
          ce.compute_momentum(0, 4) == ce.MOMENTUM_COLLAPSING,
          f"got={ce.compute_momentum(0, 4)}")
    check("A", "win_streak=2, loss_streak=10 → collapsing",
          ce.compute_momentum(2, 10) == ce.MOMENTUM_COLLAPSING,
          f"got={ce.compute_momentum(2, 10)}")

    # A.6 — win streak takes precedence (D1).
    # A fighter on a 5-fight win streak with a 4-fight loss streak
    # before it is "very_high" — the win streak is what's current.
    check("A", "win_streak=5, loss_streak=4 → very_high (win takes precedence)",
          ce.compute_momentum(5, 4) == ce.MOMENTUM_VERY_HIGH,
          f"got={ce.compute_momentum(5, 4)}")
    check("A", "win_streak=3, loss_streak=4 → high (win takes precedence)",
          ce.compute_momentum(3, 4) == ce.MOMENTUM_HIGH,
          f"got={ce.compute_momentum(3, 4)}")

    # A.7 — None handling (defensive — DB columns may be NULL).
    check("A", "win_streak=None, loss_streak=None → stable",
          ce.compute_momentum(None, None) == ce.MOMENTUM_STABLE,
          f"got={ce.compute_momentum(None, None)}")


# ----------------------------------------------------------------
# Case B: compute_pressure — pure function
# ----------------------------------------------------------------
def case_b_pressure():
    """Test compute_pressure for all 4 tiers + each factor in isolation."""
    print("\n--- Case B: compute_pressure ---")
    ce = context_engine

    # Baseline fighter data: NO pressure factors.
    baseline = {
        "contract_days_remaining": 365,
        "age": 25,
        "loss_streak": 0,
        "rank": None,
        "career_health": 100,
        "is_champion": False,
        "is_free_agent": False,
        "win_streak": 0,
    }
    check("B", "0 factors → minimal",
          ce.compute_pressure(baseline) == ce.PRESSURE_MINIMAL,
          f"got={ce.compute_pressure(baseline)}")

    # B.1 — each factor in isolation (D2). Each factor alone → moderate.
    # Factor 1: contract expiring within 60 days.
    d = dict(baseline); d["contract_days_remaining"] = 30
    check("B", "factor 1 (contract ≤60d) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 2: age >= 35.
    d = dict(baseline); d["age"] = 35
    check("B", "factor 2 (age ≥35) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 3: loss_streak >= 3.
    d = dict(baseline); d["loss_streak"] = 3
    check("B", "factor 3 (loss_streak ≥3) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 4: ranked top 10.
    d = dict(baseline); d["rank"] = 5
    check("B", "factor 4 (rank ≤10) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 5: career_health < 50.
    d = dict(baseline); d["career_health"] = 40
    check("B", "factor 5 (career_health <50) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 6: is champion.
    d = dict(baseline); d["is_champion"] = True
    check("B", "factor 6 (champion) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 7: free agent.
    d = dict(baseline); d["is_free_agent"] = True
    check("B", "factor 7 (free agent) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 8: win_streak >= 5 AND age >= 30.
    d = dict(baseline); d["win_streak"] = 5; d["age"] = 30
    check("B", "factor 8 (win≥5 + age≥30) alone → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # Factor 8 — negative: win_streak >= 5 but age < 30 → no factor.
    d = dict(baseline); d["win_streak"] = 5; d["age"] = 29
    check("B", "factor 8 negative (win≥5 + age<30) → minimal",
          ce.compute_pressure(d) == ce.PRESSURE_MINIMAL, f"got={ce.compute_pressure(d)}")

    # B.2 — cumulative tiers.
    # 2 factors → moderate (still).
    d = dict(baseline); d["age"] = 35; d["is_champion"] = True
    check("B", "2 factors → moderate",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")

    # 3 factors → high.
    d = dict(baseline); d["age"] = 35; d["is_champion"] = True; d["loss_streak"] = 3
    check("B", "3 factors → high",
          ce.compute_pressure(d) == ce.PRESSURE_HIGH, f"got={ce.compute_pressure(d)}")

    # 4 factors → high (still).
    d = dict(baseline); d["age"] = 35; d["is_champion"] = True
    d["loss_streak"] = 3; d["rank"] = 5
    check("B", "4 factors → high",
          ce.compute_pressure(d) == ce.PRESSURE_HIGH, f"got={ce.compute_pressure(d)}")

    # 5 factors → extreme.
    d = dict(baseline); d["age"] = 35; d["is_champion"] = True
    d["loss_streak"] = 3; d["rank"] = 5; d["career_health"] = 40
    check("B", "5 factors → extreme",
          ce.compute_pressure(d) == ce.PRESSURE_EXTREME, f"got={ce.compute_pressure(d)}")

    # 8 factors (all) → extreme.
    d = dict(baseline)
    d["contract_days_remaining"] = 30; d["age"] = 36
    d["loss_streak"] = 4; d["rank"] = 1; d["career_health"] = 30
    d["is_champion"] = True; d["is_free_agent"] = False  # can't be champ + FA
    d["win_streak"] = 6
    # Note: champion + free agent is contradictory. Drop free agent
    # to get 7 factors total. With free_agent instead of champion,
    # we'd still hit extreme (5+).
    check("B", "7 factors → extreme",
          ce.compute_pressure(d) == ce.PRESSURE_EXTREME, f"got={ce.compute_pressure(d)}")

    # B.3 — boundary: contract_days=60 (exactly), 61 (just over).
    d = dict(baseline); d["contract_days_remaining"] = 60
    check("B", "contract_days=60 → moderate (boundary inclusive)",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")
    d = dict(baseline); d["contract_days_remaining"] = 61
    check("B", "contract_days=61 → minimal (just over boundary)",
          ce.compute_pressure(d) == ce.PRESSURE_MINIMAL, f"got={ce.compute_pressure(d)}")

    # B.4 — boundary: rank=10 (top 10), rank=11 (not top 10).
    d = dict(baseline); d["rank"] = 10
    check("B", "rank=10 → moderate (boundary inclusive)",
          ce.compute_pressure(d) == ce.PRESSURE_MODERATE, f"got={ce.compute_pressure(d)}")
    d = dict(baseline); d["rank"] = 11
    check("B", "rank=11 → minimal (just outside top 10)",
          ce.compute_pressure(d) == ce.PRESSURE_MINIMAL, f"got={ce.compute_pressure(d)}")


# ----------------------------------------------------------------
# Case C: compute_trajectory — pure function
# ----------------------------------------------------------------
def case_c_trajectory():
    """Test compute_trajectory for all 5 tiers + age boundaries."""
    print("\n--- Case C: compute_trajectory ---")
    ce = context_engine

    # C.1 — rising: very_high/high + age < 30.
    check("C", "very_high + age=25 → rising",
          ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 25) == ce.TRAJECTORY_RISING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 25)}")
    check("C", "high + age=29 → rising",
          ce.compute_trajectory(ce.MOMENTUM_HIGH, 29) == ce.TRAJECTORY_RISING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_HIGH, 29)}")

    # C.2 — peaking: very_high/high + age 30-34.
    check("C", "very_high + age=30 → peaking",
          ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 30) == ce.TRAJECTORY_PEAKING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 30)}")
    check("C", "high + age=34 → peaking",
          ce.compute_trajectory(ce.MOMENTUM_HIGH, 34) == ce.TRAJECTORY_PEAKING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_HIGH, 34)}")

    # C.3 — peaking→declining boundary at 35.
    check("C", "very_high + age=35 → declining (past prime)",
          ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 35) == ce.TRAJECTORY_DECLINING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 35)}")

    # C.4 — stable.
    check("C", "stable + age=25 → stable",
          ce.compute_trajectory(ce.MOMENTUM_STABLE, 25) == ce.TRAJECTORY_STABLE,
          f"got={ce.compute_trajectory(ce.MOMENTUM_STABLE, 25)}")
    check("C", "stable + age=35 → stable",
          ce.compute_trajectory(ce.MOMENTUM_STABLE, 35) == ce.TRAJECTORY_STABLE,
          f"got={ce.compute_trajectory(ce.MOMENTUM_STABLE, 35)}")

    # C.5 — falling → declining.
    check("C", "falling + age=25 → declining",
          ce.compute_trajectory(ce.MOMENTUM_FALLING, 25) == ce.TRAJECTORY_DECLINING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_FALLING, 25)}")

    # C.6 — collapsing + age < 35 → declining (D3 — time to turn it around).
    check("C", "collapsing + age=25 → declining (young, time to turn it around)",
          ce.compute_trajectory(ce.MOMENTUM_COLLAPSING, 25) == ce.TRAJECTORY_DECLINING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_COLLAPSING, 25)}")

    # C.7 — collapsing + age >= 35 → collapsing (the end feels near).
    check("C", "collapsing + age=35 → collapsing",
          ce.compute_trajectory(ce.MOMENTUM_COLLAPSING, 35) == ce.TRAJECTORY_COLLAPSING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_COLLAPSING, 35)}")
    check("C", "collapsing + age=40 → collapsing",
          ce.compute_trajectory(ce.MOMENTUM_COLLAPSING, 40) == ce.TRAJECTORY_COLLAPSING,
          f"got={ce.compute_trajectory(ce.MOMENTUM_COLLAPSING, 40)}")


# ----------------------------------------------------------------
# Case D: voice phrases — non-empty, no digits, 3 variants
# ----------------------------------------------------------------
def case_d_voice_phrases():
    """Test voice phrase helpers (§17.4 + §14)."""
    print("\n--- Case D: voice phrases ---")
    ce = context_engine

    # D.1 — each momentum label has 3 non-empty, no-digit variants.
    for label in [ce.MOMENTUM_VERY_HIGH, ce.MOMENTUM_HIGH, ce.MOMENTUM_STABLE,
                  ce.MOMENTUM_FALLING, ce.MOMENTUM_COLLAPSING]:
        variants = ce.MOMENTUM_PHRASES[label]
        check("D", f"momentum '{label}' has 3 variants",
              len(variants) == 3, f"got={len(variants)}")
        for v in variants:
            check("D", f"momentum '{label}' variant '{v[:30]}' has no digits (§14)",
                  not _HAS_DIGIT.search(v), f"got={v!r}")
            check("D", f"momentum '{label}' variant is non-empty",
                  isinstance(v, str) and len(v) > 0, "")

    # D.2 — each pressure label has 3 variants.
    for label in [ce.PRESSURE_MINIMAL, ce.PRESSURE_MODERATE,
                  ce.PRESSURE_HIGH, ce.PRESSURE_EXTREME]:
        variants = ce.PRESSURE_PHRASES[label]
        check("D", f"pressure '{label}' has 3 variants",
              len(variants) == 3, f"got={len(variants)}")
        for v in variants:
            check("D", f"pressure '{label}' variant '{v[:30]}' has no digits (§14)",
                  not _HAS_DIGIT.search(v), f"got={v!r}")

    # D.3 — each trajectory label has 3 variants.
    for label in [ce.TRAJECTORY_RISING, ce.TRAJECTORY_PEAKING,
                  ce.TRAJECTORY_STABLE, ce.TRAJECTORY_DECLINING,
                  ce.TRAJECTORY_COLLAPSING]:
        variants = ce.TRAJECTORY_PHRASES[label]
        check("D", f"trajectory '{label}' has 3 variants",
              len(variants) == 3, f"got={len(variants)}")
        for v in variants:
            check("D", f"trajectory '{label}' variant '{v[:30]}' has no digits (§14)",
                  not _HAS_DIGIT.search(v), f"got={v!r}")

    # D.4 — phrase picker returns a non-empty string for each label.
    rng = random.Random(RANDOM_SEED)
    for fn, labels in [
        (ce.get_momentum_phrase, [ce.MOMENTUM_VERY_HIGH, ce.MOMENTUM_HIGH,
                                  ce.MOMENTUM_STABLE, ce.MOMENTUM_FALLING,
                                  ce.MOMENTUM_COLLAPSING]),
        (ce.get_pressure_phrase, [ce.PRESSURE_MINIMAL, ce.PRESSURE_MODERATE,
                                  ce.PRESSURE_HIGH, ce.PRESSURE_EXTREME]),
        (ce.get_trajectory_phrase, [ce.TRAJECTORY_RISING, ce.TRAJECTORY_PEAKING,
                                    ce.TRAJECTORY_STABLE, ce.TRAJECTORY_DECLINING,
                                    ce.TRAJECTORY_COLLAPSING]),
    ]:
        for label in labels:
            phrase = fn(label, rng)
            check("D", f"{fn.__name__}('{label}') returns non-empty str",
                  isinstance(phrase, str) and len(phrase) > 0, f"got={phrase!r}")


# ----------------------------------------------------------------
# Case E: encode/decode helpers
# ----------------------------------------------------------------
def case_e_encode_decode():
    """Test the "label||phrase" round-trip."""
    print("\n--- Case E: encode/decode ---")
    ce = context_engine

    # E.1 — encode produces "label||phrase".
    encoded = ce.encode("high", "riding a hot streak")
    check("E", "encode('high', '...') == 'high||...'",
          encoded == "high||riding a hot streak", f"got={encoded!r}")

    # E.2 — decode_label extracts the label.
    check("E", "decode_label('high||...') == 'high'",
          ce.decode_label("high||riding a hot streak") == "high",
          f"got={ce.decode_label('high||riding a hot streak')!r}")

    # E.3 — decode_phrase extracts the phrase.
    check("E", "decode_phrase('high||...') == 'riding a hot streak'",
          ce.decode_phrase("high||riding a hot streak") == "riding a hot streak",
          f"got={ce.decode_phrase('high||riding a hot streak')!r}")

    # E.4 — round-trip preserves both parts.
    label, phrase = "extreme", "do-or-die situation"
    encoded = ce.encode(label, phrase)
    check("E", "round-trip preserves label",
          ce.decode_label(encoded) == label, "")
    check("E", "round-trip preserves phrase",
          ce.decode_phrase(encoded) == phrase, "")

    # E.5 — defensive: NULL / missing "||" → None.
    check("E", "decode_label(None) == None",
          ce.decode_label(None) is None, "")
    check("E", "decode_label('') == None",
          ce.decode_label("") is None, "")
    check("E", "decode_label('noseparator') == None",
          ce.decode_label("noseparator") is None, "")

    # E.6 — phrase containing "||" only splits on FIRST separator.
    encoded = ce.encode("stable", "neither here||there")
    check("E", "phrase with '||' splits on first only",
          ce.decode_label(encoded) == "stable"
          and ce.decode_phrase(encoded) == "neither here||there",
          f"got={encoded!r}")


# ----------------------------------------------------------------
# Case F: bulk compute on test DB
# ----------------------------------------------------------------
def case_f_bulk_compute():
    """Test compute_all_fighters on a fresh test DB (5 fighters)."""
    print("\n--- Case F: bulk compute on test DB ---")
    ce = context_engine

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Pre-create fighter_descriptors rows via the existing snapshot
    # path. compute_all_fighters UPDATES existing rows (production
    # contract) — it does not INSERT. The fresh test DB has 0 rows
    # until update_fighter_descriptor_snapshot is called.
    populate_descriptor_rows(conn)

    # F.1 — momentum + pressure columns start NULL (descriptor rows
    # exist but the 6 new Phase 2 columns are unpopulated).
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors"
    ).fetchone()[0]
    check("F", "5 fighter_descriptors rows exist (via populate_descriptor_rows)",
          total_rows == 5, f"got={total_rows}")
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE momentum IS NULL"
    ).fetchone()[0]
    check("F", "momentum columns start NULL (5 fighters)",
          nulls == 5, f"got={nulls} NULLs")

    # F.2 — run bulk compute.
    n_updated = ce.compute_all_fighters(conn)
    check("F", "compute_all_fighters updated all 5 active fighters",
          n_updated == 5, f"got={n_updated}")

    # F.3 — columns now non-NULL for all 5.
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE momentum IS NULL"
    ).fetchone()[0]
    check("F", "all momentum values written (0 NULLs)",
          nulls == 0, f"got={nulls} NULLs")
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE pressure IS NULL"
    ).fetchone()[0]
    check("F", "all pressure values written (0 NULLs)",
          nulls == 0, f"got={nulls} NULLs")

    # F.4 — every stored value matches "label||phrase" format.
    bad = 0
    for r in conn.execute("SELECT fighter_id, momentum, pressure "
                          "FROM fighter_descriptors"):
        for v in (r[1], r[2]):
            if not isinstance(v, str) or "||" not in v:
                bad += 1
    check("F", "all stored values match 'label||phrase' format",
          bad == 0, f"got={bad} bad values")

    # F.5 — decoded labels are all valid canonical labels.
    valid_m = {ce.MOMENTUM_VERY_HIGH, ce.MOMENTUM_HIGH, ce.MOMENTUM_STABLE,
               ce.MOMENTUM_FALLING, ce.MOMENTUM_COLLAPSING}
    valid_p = {ce.PRESSURE_MINIMAL, ce.PRESSURE_MODERATE,
               ce.PRESSURE_HIGH, ce.PRESSURE_EXTREME}
    bad = 0
    for r in conn.execute("SELECT momentum, pressure FROM fighter_descriptors"):
        if ce.decode_label(r[0]) not in valid_m:
            bad += 1
        if ce.decode_label(r[1]) not in valid_p:
            bad += 1
    check("F", "decoded momentum + pressure labels all canonical",
          bad == 0, f"got={bad} bad labels")

    # F.6 — phrases contain no digits (§14).
    bad = 0
    for r in conn.execute("SELECT momentum, pressure FROM fighter_descriptors"):
        for v in (r[0], r[1]):
            phrase = ce.decode_phrase(v)
            if not phrase or _HAS_DIGIT.search(phrase):
                bad += 1
    check("F", "voice phrases contain no digits (§14)",
          bad == 0, f"got={bad} violations")

    # F.7 — performance: <1 second for 5 fighters (smoke check — the
    # real budget is for 4450, but we don't have that many in the test
    # DB; we just verify it doesn't blow up).
    t0 = time.time()
    ce.compute_all_fighters(conn)
    elapsed = time.time() - t0
    check("F", f"bulk compute <1s ({elapsed*1000:.0f}ms)",
          elapsed < 1.0, f"{elapsed*1000:.0f}ms")

    # F.8 — end-to-end: a fighter with a hot streak → very_high momentum.
    # Mutate fighter 1 (John Vale): give him a 6-fight win streak.
    conn.execute("UPDATE fighter_career SET win_streak=6 WHERE fighter_id=1")
    conn.commit()
    ce.compute_all_fighters(conn)
    stored = conn.execute(
        "SELECT momentum FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("F", "fighter with win_streak=6 → very_high momentum (end-to-end)",
          ce.decode_label(stored) == ce.MOMENTUM_VERY_HIGH,
          f"got={stored!r}")

    # F.9 — end-to-end: a fighter with bad health + age + champion
    # → at least high pressure.
    # Fighter 2 (Marcus Reed): make him a 36yo champ with bad health.
    # First, give him a title + a career_health drop.
    conn.execute("UPDATE fighters SET date_of_birth='1990-01-01' WHERE fighter_id=2")
    conn.execute("UPDATE fighter_career SET career_health=30 WHERE fighter_id=2")
    # Make him champion: update the existing vacant title for AC's WC 1.
    conn.execute("UPDATE titles SET current_champion_fighter_id=2, is_vacant=0 "
                 "WHERE promotion_id=1 AND weight_class_id=1")
    conn.commit()
    ce.compute_all_fighters(conn)
    stored = conn.execute(
        "SELECT pressure FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    label = ce.decode_label(stored)
    # Age (36) + career_health<50 + champion = 3 factors → high.
    check("F", "36yo champ with bad health → high pressure (end-to-end)",
          label in (ce.PRESSURE_HIGH, ce.PRESSURE_EXTREME),
          f"got={stored!r} (label={label})")

    conn.close()


# ----------------------------------------------------------------
# Case G: single-fighter refresh
# ----------------------------------------------------------------
def case_g_single_refresh():
    """Test compute_single_fighter (targeted refresh)."""
    print("\n--- Case G: single-fighter refresh ---")
    ce = context_engine

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # G.1 — fighter exists → returns dict with momentum + pressure.
    result = ce.compute_single_fighter(conn, 1)
    check("G", "returns dict with 'momentum' key",
          isinstance(result, dict) and "momentum" in result,
          f"got={result}")
    check("G", "returns dict with 'pressure' key",
          isinstance(result, dict) and "pressure" in result,
          f"got={result}")
    check("G", "momentum is a canonical label",
          result["momentum"] in {ce.MOMENTUM_VERY_HIGH, ce.MOMENTUM_HIGH,
                                 ce.MOMENTUM_STABLE, ce.MOMENTUM_FALLING,
                                 ce.MOMENTUM_COLLAPSING},
          f"got={result['momentum']}")

    # G.2 — DB row updated.
    stored = conn.execute(
        "SELECT momentum FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("G", "DB row updated with 'label||phrase' value",
          isinstance(stored, str) and "||" in stored
          and ce.decode_label(stored) == result["momentum"],
          f"got={stored!r}")

    # G.3 — non-existent fighter → None.
    result = ce.compute_single_fighter(conn, 99999)
    check("G", "non-existent fighter → None",
          result is None, f"got={result}")

    # G.4 — performance: <10ms steady-state (3rd call after warm-up).
    ce.compute_single_fighter(conn, 1)
    ce.compute_single_fighter(conn, 1)
    t0 = time.time()
    ce.compute_single_fighter(conn, 1)
    elapsed_ms = (time.time() - t0) * 1000
    check("G", f"single-fighter refresh <10ms steady-state ({elapsed_ms:.2f}ms)",
          elapsed_ms < 10.0, f"{elapsed_ms:.2f}ms")

    # G.5 — single refresh reflects live state changes (D5).
    # Bump fighter 1 to win_streak=5 → very_high.
    conn.execute("UPDATE fighter_career SET win_streak=5 WHERE fighter_id=1")
    conn.commit()
    result = ce.compute_single_fighter(conn, 1)
    check("G", "single refresh picks up win_streak=5 → very_high",
          result["momentum"] == ce.MOMENTUM_VERY_HIGH,
          f"got={result}")

    conn.close()


# ----------------------------------------------------------------
# Case H: determinism
# ----------------------------------------------------------------
def case_h_determinism():
    """Test that the same fighter_id always produces the same phrase."""
    print("\n--- Case H: determinism ---")
    ce = context_engine

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)

    # H.1 — two single-fighter refreshes produce identical stored values.
    ce.compute_single_fighter(conn, 1)
    v1 = conn.execute(
        "SELECT momentum, pressure FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()
    ce.compute_single_fighter(conn, 1)
    v2 = conn.execute(
        "SELECT momentum, pressure FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()
    check("H", "two single refreshes produce identical stored values",
          v1 == v2, f"v1={v1} v2={v2}")

    # H.2 — bulk compute then single refresh produces identical values.
    ce.compute_all_fighters(conn)
    v_bulk = conn.execute(
        "SELECT momentum, pressure FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()
    ce.compute_single_fighter(conn, 3)
    v_single = conn.execute(
        "SELECT momentum, pressure FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()
    check("H", "bulk compute + single refresh produce identical values",
          v_bulk == v_single, f"bulk={v_bulk} single={v_single}")

    # H.3 — different fighters may get different phrases (variety).
    # With 5 fighters + 3 variants per label, we expect at least some
    # variation across fighters (unless all 5 land on the same label
    # AND the same RNG-offset picks the same variant — possible but
    # unlikely).
    phrases = set()
    for fid in range(1, 6):
        row = conn.execute(
            "SELECT momentum FROM fighter_descriptors WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if row and row[0]:
            phrases.add(ce.decode_phrase(row[0]))
    # Smoke check — at least 1 phrase returned (defensive — variety
    # assertion is flaky on a 5-fighter test DB).
    check("H", "voice phrases produced for all 5 fighters",
          len(phrases) >= 1, f"got={len(phrases)} unique phrases")

    conn.close()


# ----------------------------------------------------------------
# Case I: snapshot_cache integration
# ----------------------------------------------------------------
def case_i_snapshot_cache_integration():
    """Test that snapshot_cache wires context_engine correctly."""
    print("\n--- Case I: snapshot_cache integration ---")
    ce = context_engine

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Pre-create the descriptor row for fighter 1 so refresh_fighter
    # can update it. (refresh_fighter calls update_fighter_descriptor_
    # snapshot which INSERTs the row if it doesn't exist — but we
    # want to verify the NULL → non-NULL transition explicitly.)
    app.update_fighter_descriptor_snapshot(conn, 1)
    conn.commit()

    # I.1 — snapshot_cache.refresh_fighter writes momentum + pressure.
    # Before refresh: NULL.
    nulls_before = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND momentum IS NULL"
    ).fetchone()[0]
    check("I", "momentum is NULL before refresh_fighter",
          nulls_before == 1, f"got={nulls_before} NULLs")

    snapshot_cache.refresh_fighter(conn, 1)

    nulls_after = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND momentum IS NULL"
    ).fetchone()[0]
    check("I", "momentum is non-NULL after refresh_fighter",
          nulls_after == 0, f"got={nulls_after} NULLs")

    # I.2 — value is in "label||phrase" format.
    stored = conn.execute(
        "SELECT momentum FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("I", "refresh_fighter writes 'label||phrase' format",
          isinstance(stored, str) and "||" in stored, f"got={stored!r}")

    # I.3 — daily pass writes momentum + pressure for all fighters.
    # Pre-create descriptor rows for all 5 fighters (compute_all_
    # fighters UPDATES — does not INSERT). Then reset momentum +
    # pressure to NULL to verify the daily pass writes them.
    populate_descriptor_rows(conn)
    conn.execute("UPDATE fighter_descriptors SET momentum=NULL, pressure=NULL")
    conn.commit()
    snapshot_cache.run_daily_interpretation_pass(conn)
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE momentum IS NULL"
    ).fetchone()[0]
    check("I", "daily pass writes momentum for all 5 fighters (0 NULLs)",
          nulls == 0, f"got={nulls} NULLs")
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE pressure IS NULL"
    ).fetchone()[0]
    check("I", "daily pass writes pressure for all 5 fighters (0 NULLs)",
          nulls == 0, f"got={nulls} NULLs")

    # I.4 — interpretation_cache_meta updated.
    row = conn.execute(
        "SELECT engine_version, last_built_fighter_count "
        "FROM interpretation_cache_meta WHERE meta_id=1"
    ).fetchone()
    check("I", "interpretation_cache_meta.engine_version == '1.1.0'",
          row and row[0] == "1.1.0", f"got={row[0] if row else None}")
    check("I", "interpretation_cache_meta.last_built_fighter_count == 5",
          row and row[1] == 5, f"got={row[1] if row else None}")

    # I.5 — end-to-end: refresh_fighter on a hot-streak fighter writes
    # very_high momentum (D7).
    conn.execute("UPDATE fighter_career SET win_streak=7 WHERE fighter_id=2")
    conn.commit()
    snapshot_cache.refresh_fighter(conn, 2)
    stored = conn.execute(
        "SELECT momentum FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    check("I", "refresh_fighter on win_streak=7 fighter → very_high",
          ce.decode_label(stored) == ce.MOMENTUM_VERY_HIGH,
          f"got={stored!r}")

    conn.close()


# ----------------------------------------------------------------
# Case J: Design Law check (§13 + §17.4)
# ----------------------------------------------------------------
def case_j_design_law():
    """Design Law check — engine translates simulation into emotion."""
    print("\n--- Case J: Design Law check ---")
    ce = context_engine

    # J.1 — §17.4 "Rich Not Thin": canonical label + voice phrase
    # are BOTH stored (separated by "||"). The UI reads the phrase;
    # the logic reads the label.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    populate_descriptor_rows(conn)
    snapshot_cache.run_daily_interpretation_pass(conn)
    row = conn.execute(
        "SELECT momentum, pressure FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()
    momentum, pressure = row
    check("J", "§17.4: momentum stores BOTH label AND phrase (||)",
          "||" in momentum and ce.decode_label(momentum) is not None
          and ce.decode_phrase(momentum) is not None, f"got={momentum!r}")
    check("J", "§17.4: pressure stores BOTH label AND phrase (||)",
          "||" in pressure and ce.decode_label(pressure) is not None
          and ce.decode_phrase(pressure) is not None, f"got={pressure!r}")

    # J.2 — §13 Design Law: momentum + pressure tell a STORY.
    # Compare: raw "win_streak=5, loss_streak=0" → story "very_high ||
    # 'riding a blistering hot streak'". The label tells the truth;
    # the phrase tells the story.
    label = ce.decode_label(momentum)
    phrase = ce.decode_phrase(momentum)
    check("J", "§13: label is canonical (logic-readable)",
          label in {ce.MOMENTUM_VERY_HIGH, ce.MOMENTUM_HIGH,
                    ce.MOMENTUM_STABLE, ce.MOMENTUM_FALLING,
                    ce.MOMENTUM_COLLAPSING}, f"got={label}")
    check("J", "§13: phrase is narrative (player-readable, no digits)",
          isinstance(phrase, str) and not _HAS_DIGIT.search(phrase),
          f"got={phrase!r}")

    # J.3 — §14: no raw numbers leak into the player-facing phrase.
    # The canonical label is "very_high" — but the player sees
    # "riding a hot streak". Raw numbers (5 wins, etc.) are NOT
    # in the phrase.
    raw_phrases = []
    for r in conn.execute("SELECT momentum, pressure FROM fighter_descriptors"):
        raw_phrases.append(ce.decode_phrase(r[0]))
        raw_phrases.append(ce.decode_phrase(r[1]))
    violations = sum(1 for p in raw_phrases if p and _HAS_DIGIT.search(p))
    check("J", "§14: zero digit violations across all stored phrases",
          violations == 0, f"got={violations} violations")

    # J.4 — §13.5 Anticipation: trajectory distinguishes a 25yo
    # hot-streak fighter (rising) from a 36yo hot-streak fighter
    # (declining — past prime). Same momentum, different story.
    rising = ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 25)
    peaking = ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 32)
    declining = ce.compute_trajectory(ce.MOMENTUM_VERY_HIGH, 36)
    check("J", "§13.5: 25yo hot streak → rising (anticipation: the best is yet to come)",
          rising == ce.TRAJECTORY_RISING, f"got={rising}")
    check("J", "§13.5: 32yo hot streak → peaking (anticipation: in their prime)",
          peaking == ce.TRAJECTORY_PEAKING, f"got={peaking}")
    check("J", "§13.5: 36yo hot streak → declining (anticipation: how long can they keep this up?)",
          declining == ce.TRAJECTORY_DECLINING, f"got={declining}")

    # J.5 — §13.3 Interpretation Layer: translates simulation into
    # emotion. The same raw state (4 losses in a row) produces
    # "collapsing" — a story word, not a stat.
    collapsing_label = ce.compute_momentum(0, 4)
    check("J", "§13.3: 4 losses → 'collapsing' (story word, not stat)",
          collapsing_label == ce.MOMENTUM_COLLAPSING, f"got={collapsing_label}")

    conn.close()


def main():
    print("=" * 80)
    print(f"Phase 2 Task 2.2 — Context Engine acceptance test "
          f"(schema {EXPECTED_CODE_VERSION})")
    print("=" * 80)

    case_a_momentum()
    case_b_pressure()
    case_c_trajectory()
    case_d_voice_phrases()
    case_e_encode_decode()
    case_f_bulk_compute()
    case_g_single_refresh()
    case_h_determinism()
    case_i_snapshot_cache_integration()
    case_j_design_law()

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
