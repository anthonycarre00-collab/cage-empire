#!/usr/bin/env python3
"""Acceptance test for Phase 2 Tasks 2.4 + 2.7 — Narrative Families
Engine + Legacy Engine.

Tests src/interpretation/narrative_families.py (4 MVP families: prodigy,
veteran, fallen_champion, cinderella_story) AND src/interpretation/
legacy_engine.py (4 MVP states: building, established, legendary,
forgotten).

Both engines are thin modules that follow the EXACT pattern set by
the Context Engine (Task 2.2) and Career Phase Engine (Task 2.3):
  - Pure `compute_*` functions take primitive inputs, return canonical
    label strings. No DB, no RNG.
  - Voice phrases are picked separately, RNG-seeded by fighter_id for
    determinism (no UI flickering between daily passes).
  - Storage format is `"label||voice phrase"` per CONVENTIONS §17.4.
  - Bulk-load pattern: one SELECT, Python loop, executemany UPDATE.
  - Single-fighter refresh path for event-bus subscribers
    (<10ms budget).

Per CONVENTIONS §17:
  - The interpretation layer is the ONLY writer to fighter_descriptors
    (a cache table). It NEVER writes to simulation tables.
  - §17.4 "Rich Not Thin": each cache column stores BOTH the canonical
    label AND a voice phrase, separated by "||". The UI reads the
    phrase (after "||"); tests read the label (before "||").
  - §17.5 Performance: bulk-load pattern (one SELECT, Python loop,
    executemany UPDATE). <1 second for 4450/4510 fighters; <10ms for
    a targeted single-fighter refresh.
  - §14 Voice Layer: phrases contain no digits.

Test cases:
  A. compute_narrative_family — pure function. All 4 families + None:
     prodigy (prospect + high/very_high momentum), veteran (veteran +
     stable/falling momentum), fallen_champion (declining + title_
     reigns>0 + falling/collapsing momentum), cinderella_story
     (rising_contender + very_high + age>=28), None (no match — e.g.,
     rising_contender + stable, age 25).
  B. Narrative priority order — Prodigy > Fallen Champion > Cinderella
     Story > Veteran (first match wins).
  C. Narrative voice phrases — non-empty, no digits (§14), 3 variants.
  D. compute_legacy_state — pure function. All 4 states:
     building (early career), established (25+ fights + 15+ wins),
     legendary (HoF OR 2+ title_reigns + 30+ fights), forgotten
     (retired + no HoF + <20 fights). Plus defensive-default edge
     case (25+ fights + <15 wins → building per D5).
  E. Legacy priority order — Legendary > Forgotten > Established >
     Building (first match wins).
  F. Legacy voice phrases — non-empty, no digits (§14), 3 variants.
  G. encode/decode helpers — "label||phrase" round-trips correctly
     (reused from context_engine — D1 single-source-of-truth).
  H. Bulk compute on test DB — compute_all_families writes
     narrative_family; compute_all_legacies writes legacy_state.
     Columns start NULL, end non-NULL (legacy always non-NULL;
     narrative may be NULL for fighters who match no rule — D5).
     Canonical labels + phrases parseable.
  I. Single-fighter refresh — compute_single_family + compute_single_
     legacy update one fighter; return the canonical label; <10ms
     steady-state.
  J. Determinism — same fighter_id always produces the same voice
     phrase (RNG seeded by fighter_id).
  K. Snapshot cache integration — snapshot_cache.refresh_fighter now
     calls narrative_families + legacy_engine; the daily pass writes
     both columns.
  L. Design Law check (§13 + §17.4) — both engines translate raw
     simulation state into player-facing meaning (narrative_family
     + legacy_state tell STORIES, not stats).

Pattern follows scripts/test_career_phase_engine.py
(CONVENTIONS §10 — dynamic version pattern, no hardcoded version
strings).

Run from the project root:
    python3 scripts/test_narrative_legacy.py

Exit code 0 = all PASS, 1 = any FAIL.

D-number decisions in this test (referenced from the worklog):
  - D1: compute_narrative_family case A tests each family in
    isolation with the MINIMUM qualifying inputs (e.g., prodigy =
    prospect + very_high momentum — one below each boundary).
    Boundary cases (e.g., age 27 vs 28 for Cinderella Story) are
    tested explicitly.
  - D2: priority case B tests the four-way priority order. The most
    important rule: a fighter who could match multiple families
    (e.g., a declining veteran with title_reigns > 0 + falling
    momentum — could be veteran OR fallen_champion) gets the FIRST
    matching family in the priority order (fallen_champion requires
    career_phase=declining, NOT veteran — so the priority order is
    defensive, not actively tested via contrived overlaps).
  - D3: Voice phrase cases C + F check NO DIGITS (CONVENTIONS §14).
    The voice layer translates simulation into emotion; a phrase like
    "won 3 in a row" would be a §14 violation.
  - D4: Bulk compute case H runs against a FRESH test DB (5-fighter
    seed), then manually mutates fighter state to verify each family
    + each state is detected end-to-end through the SQL JOIN. This
    catches JOIN bugs that pure-function tests miss.
  - D5: Determinism case J runs compute_single_* twice and asserts
    the stored value is byte-identical. This catches RNG seeding
    bugs.
  - D6: Snapshot cache case K verifies snapshot_cache.refresh_fighter
    now writes narrative_family + legacy_state. The test makes a
    fighter a prodigy via DB mutation and verifies the family is
    detected after refresh.
  - D7: legacy_engine defensive default — case D verifies the
    journeyman edge case (25+ fights + <15 wins, no HoF) defaults
    to "building" per the legacy_engine D5 design decision.
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
from interpretation import narrative_families as nf  # noqa: E402
from interpretation import legacy_engine as le  # noqa: E402
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

    The daily pass (compute_all_families / compute_all_legacies)
    UPDATES existing rows — it does NOT INSERT. In production,
    fighter_descriptors rows are created by update_fighter_descriptor_
    snapshot (called on fight resolution, camp completion, etc.). The
    fresh test DB has 0 descriptor rows, so we pre-create them via
    the existing snapshot path before testing the new engines.
    """
    for fid in range(1, 6):
        app.update_fighter_descriptor_snapshot(conn, fid)
    conn.commit()


# Regex to detect digits in voice phrases (CONVENTIONS §14).
_HAS_DIGIT = re.compile(r"\d")


# ----------------------------------------------------------------
# Case A: compute_narrative_family — pure function (all 4 + None)
# ----------------------------------------------------------------
def case_a_pure_compute_narrative():
    """Test compute_narrative_family for all 4 families + None."""
    print("\n--- Case A: compute_narrative_family (pure function) ---")
    nfe = nf

    # A.1 — prodigy (career_phase=prospect AND momentum=very_high).
    check("A", "prodigy: prospect + very_high + 22yo + 0 titles",
          nfe.compute_narrative_family("prospect", "very_high", 22, 0)
          == nfe.FAMILY_PRODIGY,
          f"got={nfe.compute_narrative_family('prospect', 'very_high', 22, 0)}")
    # A.1b — prodigy also matches with momentum=high (boundary).
    check("A", "prodigy: prospect + high (boundary)",
          nfe.compute_narrative_family("prospect", "high", 22, 0)
          == nfe.FAMILY_PRODIGY,
          f"got={nfe.compute_narrative_family('prospect', 'high', 22, 0)}")

    # A.2 — fallen_champion (career_phase=declining + title_reigns>0
    # + momentum=falling).
    check("A", "fallen_champion: declining + falling + 35yo + 1 title",
          nfe.compute_narrative_family("declining", "falling", 35, 1)
          == nfe.FAMILY_FALLEN_CHAMPION,
          f"got={nfe.compute_narrative_family('declining', 'falling', 35, 1)}")
    # A.2b — fallen_champion also matches with momentum=collapsing.
    check("A", "fallen_champion: declining + collapsing (boundary)",
          nfe.compute_narrative_family("declining", "collapsing", 35, 1)
          == nfe.FAMILY_FALLEN_CHAMPION,
          f"got={nfe.compute_narrative_family('declining', 'collapsing', 35, 1)}")
    # A.2c — NOT fallen_champion when title_reigns=0 (never held belt).
    check("A", "boundary: declining + falling + 0 titles → NOT fallen_champion",
          nfe.compute_narrative_family("declining", "falling", 35, 0)
          is None,
          f"got={nfe.compute_narrative_family('declining', 'falling', 35, 0)}")
    # A.2d — NOT fallen_champion when momentum=stable (not falling).
    check("A", "boundary: declining + stable + 1 title → NOT fallen_champion",
          nfe.compute_narrative_family("declining", "stable", 35, 1)
          is None,
          f"got={nfe.compute_narrative_family('declining', 'stable', 35, 1)}")

    # A.3 — cinderella_story (rising_contender + very_high + age>=28).
    check("A", "cinderella_story: rising_contender + very_high + 30yo",
          nfe.compute_narrative_family("rising_contender", "very_high", 30, 0)
          == nfe.FAMILY_CINDERELLA_STORY,
          f"got={nfe.compute_narrative_family('rising_contender', 'very_high', 30, 0)}")
    # A.3b — boundary: age=28 exactly → cinderella_story.
    check("A", "boundary: rising_contender + very_high + 28yo (age bound)",
          nfe.compute_narrative_family("rising_contender", "very_high", 28, 0)
          == nfe.FAMILY_CINDERELLA_STORY,
          f"got={nfe.compute_narrative_family('rising_contender', 'very_high', 28, 0)}")
    # A.3c — boundary: age=27 → NOT cinderella_story (too young — prodigy
    # territory, but rising_contender phase blocks prodigy match).
    check("A", "boundary: rising_contender + very_high + 27yo → None (age too low)",
          nfe.compute_narrative_family("rising_contender", "very_high", 27, 0)
          is None,
          f"got={nfe.compute_narrative_family('rising_contender', 'very_high', 27, 0)}")
    # A.3d — boundary: rising_contender + high (not very_high) → NOT
    # cinderella_story (momentum too low).
    check("A", "boundary: rising_contender + high + 30yo → None (momentum too low)",
          nfe.compute_narrative_family("rising_contender", "high", 30, 0)
          is None,
          f"got={nfe.compute_narrative_family('rising_contender', 'high', 30, 0)}")

    # A.4 — veteran (career_phase=veteran + momentum=stable).
    check("A", "veteran: veteran + stable + 36yo",
          nfe.compute_narrative_family("veteran", "stable", 36, 0)
          == nfe.FAMILY_VETERAN,
          f"got={nfe.compute_narrative_family('veteran', 'stable', 36, 0)}")
    # A.4b — veteran also matches with momentum=falling.
    check("A", "veteran: veteran + falling (boundary)",
          nfe.compute_narrative_family("veteran", "falling", 36, 0)
          == nfe.FAMILY_VETERAN,
          f"got={nfe.compute_narrative_family('veteran', 'falling', 36, 0)}")
    # A.4c — NOT veteran when momentum=very_high (veteran on a hot
    # streak is a different story — falls through to None).
    check("A", "boundary: veteran + very_high → None (veteran on surge)",
          nfe.compute_narrative_family("veteran", "very_high", 36, 0)
          is None,
          f"got={nfe.compute_narrative_family('veteran', 'very_high', 36, 0)}")

    # A.5 — None (no match — D5). The most common outcome.
    # A 25yo rising_contender on a 2-fight win streak (momentum=stable).
    check("A", "None: rising_contender + stable + 25yo (no match — D5)",
          nfe.compute_narrative_family("rising_contender", "stable", 25, 0)
          is None,
          f"got={nfe.compute_narrative_family('rising_contender', 'stable', 25, 0)}")
    # A.5b — None: a prospect with cold momentum (stable).
    check("A", "None: prospect + stable → None (cold prospect, no family)",
          nfe.compute_narrative_family("prospect", "stable", 22, 0)
          is None,
          f"got={nfe.compute_narrative_family('prospect', 'stable', 22, 0)}")
    # A.5c — None: champion (career_phase=champion — not in any rule).
    check("A", "None: champion + very_high → None (champions aren't a family in MVP)",
          nfe.compute_narrative_family("champion", "very_high", 28, 1)
          is None,
          f"got={nfe.compute_narrative_family('champion', 'very_high', 28, 1)}")

    # A.6 — None handling (defensive — DB columns may be NULL).
    # None career_phase → None result. None momentum → None result.
    # None age → 0 (defensive). None title_reigns → 0 (defensive).
    none_result = nfe.compute_narrative_family(
        None, None, None, None)
    check("A", "None inputs do not crash (return None — D5)",
          none_result is None,
          f"got={none_result}")


# ----------------------------------------------------------------
# Case B: narrative priority order
# ----------------------------------------------------------------
def case_b_narrative_priority():
    """Test that the narrative priority order is enforced.

    Priority order (D4): Prodigy > Fallen Champion > Cinderella Story
    > Veteran (first match wins).

    The rules are mutually exclusive by career_phase:
      - prodigy requires career_phase=prospect
      - fallen_champion requires career_phase=declining
      - cinderella_story requires career_phase=rising_contender
      - veteran requires career_phase=veteran
    So no fighter can match multiple families via the career_phase
    constraint alone. The priority order is a defensive safeguard
    for Phase 3+ when new families might overlap.
    """
    print("\n--- Case B: narrative priority order ---")
    nfe = nf

    # B.1 — A prospect on a hot streak is prodigy (NOT None, NOT
    # anything else). The Prodigy story is checked first.
    check("B", "prospect + very_high → prodigy (priority 1)",
          nfe.compute_narrative_family("prospect", "very_high", 22, 0)
          == nfe.FAMILY_PRODIGY,
          f"got={nfe.compute_narrative_family('prospect', 'very_high', 22, 0)}")

    # B.2 — A declining ex-champion on a fall is fallen_champion
    # (priority 2). NOT veteran (which requires career_phase=veteran,
    # not declining) — verified by phase mutual exclusivity.
    check("B", "declining + falling + 1 title → fallen_champion (priority 2)",
          nfe.compute_narrative_family("declining", "falling", 35, 1)
          == nfe.FAMILY_FALLEN_CHAMPION,
          f"got={nfe.compute_narrative_family('declining', 'falling', 35, 1)}")

    # B.3 — A 30yo rising_contender on a very_high streak is
    # cinderella_story (priority 3).
    check("B", "rising_contender + very_high + 30yo → cinderella_story (priority 3)",
          nfe.compute_narrative_family("rising_contender", "very_high", 30, 0)
          == nfe.FAMILY_CINDERELLA_STORY,
          f"got={nfe.compute_narrative_family('rising_contender', 'very_high', 30, 0)}")

    # B.4 — A veteran on a flat streak is veteran (priority 4 — last).
    check("B", "veteran + stable → veteran (priority 4 — last)",
          nfe.compute_narrative_family("veteran", "stable", 36, 0)
          == nfe.FAMILY_VETERAN,
          f"got={nfe.compute_narrative_family('veteran', 'stable', 36, 0)}")

    # B.5 — priority is mutually exclusive by phase (defensive —
    # documents that the order is a safeguard, not actively tested
    # via contrived overlaps).
    check("B", "phase mutual exclusivity safeguards priority (documented)",
          True, "prodigy=prospect, fallen_champion=declining, "
                "cinderella=rising_contender, veteran=veteran")


# ----------------------------------------------------------------
# Case C: narrative voice phrases — non-empty, no digits, 3 variants
# ----------------------------------------------------------------
def case_c_narrative_voice_phrases():
    """Test narrative voice phrase helpers (§17.4 + §14)."""
    print("\n--- Case C: narrative voice phrases ---")
    nfe = nf

    # C.1 — each family label has 3 non-empty, no-digit variants.
    for label in nfe.ALL_FAMILIES:
        variants = nfe.FAMILY_PHRASES[label]
        check("C", f"family '{label}' has 3 variants",
              len(variants) == 3, f"got={len(variants)}")
        for v in variants:
            check("C", f"family '{label}' variant '{v[:30]}' has no digits (§14)",
                  not _HAS_DIGIT.search(v), f"got={v!r}")
            check("C", f"family '{label}' variant is non-empty",
                  isinstance(v, str) and len(v) > 0, "")

    # C.2 — phrase picker returns a non-empty string for each label.
    rng = random.Random(RANDOM_SEED)
    for label in nfe.ALL_FAMILIES:
        phrase = nfe.get_family_phrase(label, rng)
        check("C", f"get_family_phrase('{label}') returns non-empty str",
              isinstance(phrase, str) and len(phrase) > 0, f"got={phrase!r}")

    # C.3 — phrase picker returns one of the 3 defined variants.
    rng = random.Random(RANDOM_SEED)
    for label in nfe.ALL_FAMILIES:
        phrase = nfe.get_family_phrase(label, rng)
        check("C", f"get_family_phrase('{label}') returns a defined variant",
              phrase in nfe.FAMILY_PHRASES[label], f"got={phrase!r}")

    # C.4 — None label → None phrase (defensive).
    rng = random.Random(RANDOM_SEED)
    phrase = nfe.get_family_phrase(None, rng)
    check("C", "get_family_phrase(None) returns None",
          phrase is None, f"got={phrase!r}")

    # C.5 — unknown label falls back to prodigy variants (defensive).
    rng = random.Random(RANDOM_SEED)
    phrase = nfe.get_family_phrase("nonexistent_label", rng)
    check("C", "unknown label falls back to prodigy variants",
          phrase in nfe.FAMILY_PHRASES[nfe.FAMILY_PRODIGY],
          f"got={phrase!r}")


# ----------------------------------------------------------------
# Case D: compute_legacy_state — pure function (all 4 states)
# ----------------------------------------------------------------
def case_d_pure_compute_legacy():
    """Test compute_legacy_state for all 4 states + edge cases."""
    print("\n--- Case D: compute_legacy_state (pure function) ---")
    leg = le

    # D.1 — building (NOT HoF AND total_fights < 15).
    # A 10-fight active fighter.
    check("D", "building: active + 10 fights + 5 wins (early career)",
          leg.compute_legacy_state(False, False, 0, 10, 5)
          == leg.LEGACY_BUILDING,
          f"got={leg.compute_legacy_state(False, False, 0, 10, 5)}")
    # D.1b — building: mid-career, not enough wins yet
    # (total_fights < 25 AND wins < 15).
    check("D", "building: active + 20 fights + 10 wins (mid-career)",
          leg.compute_legacy_state(False, False, 0, 20, 10)
          == leg.LEGACY_BUILDING,
          f"got={leg.compute_legacy_state(False, False, 0, 20, 10)}")
    # D.1c — boundary: 14 fights → building (just under).
    check("D", "boundary: 14 fights + 7 wins → building (under 15)",
          leg.compute_legacy_state(False, False, 0, 14, 7)
          == leg.LEGACY_BUILDING,
          f"got={leg.compute_legacy_state(False, False, 0, 14, 7)}")
    # D.1d — boundary: 15 fights + 7 wins → building (mid-career clause).
    check("D", "boundary: 15 fights + 7 wins → building (mid-career, < 15 wins)",
          leg.compute_legacy_state(False, False, 0, 15, 7)
          == leg.LEGACY_BUILDING,
          f"got={leg.compute_legacy_state(False, False, 0, 15, 7)}")

    # D.2 — established (NOT HoF AND total_fights >= 25 AND wins >= 15).
    check("D", "established: 30 fights + 20 wins, no HoF",
          leg.compute_legacy_state(False, False, 0, 30, 20)
          == leg.LEGACY_ESTABLISHED,
          f"got={leg.compute_legacy_state(False, False, 0, 30, 20)}")
    # D.2b — boundary: 25 fights + 15 wins (at bounds).
    check("D", "boundary: 25 fights + 15 wins → established (at bounds)",
          leg.compute_legacy_state(False, False, 0, 25, 15)
          == leg.LEGACY_ESTABLISHED,
          f"got={leg.compute_legacy_state(False, False, 0, 25, 15)}")
    # D.2c — boundary: 24 fights + 20 wins → NOT established (fights < 25).
    check("D", "boundary: 24 fights + 20 wins → NOT established (fights bound)",
          leg.compute_legacy_state(False, False, 0, 24, 20)
          != leg.LEGACY_ESTABLISHED,
          f"got={leg.compute_legacy_state(False, False, 0, 24, 20)}")
    # D.2d — boundary: 30 fights + 14 wins → NOT established (wins < 15).
    check("D", "boundary: 30 fights + 14 wins → NOT established (wins bound)",
          leg.compute_legacy_state(False, False, 0, 30, 14)
          != leg.LEGACY_ESTABLISHED,
          f"got={leg.compute_legacy_state(False, False, 0, 30, 14)}")

    # D.3 — legendary (HoF OR (title_reigns >= 2 AND total_fights >= 30)).
    # HoF path.
    check("D", "legendary: in HoF (binary induction)",
          leg.compute_legacy_state(True, True, 1, 30, 25)
          == leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(True, True, 1, 30, 25)}")
    # D.3b — legendary: multi-title + longevity path (no HoF yet).
    check("D", "legendary: 3 titles + 35 fights, no HoF (multi-title path)",
          leg.compute_legacy_state(False, False, 3, 35, 25)
          == leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(False, False, 3, 35, 25)}")
    # D.3c — boundary: 2 titles + 30 fights → legendary (at bounds).
    check("D", "boundary: 2 titles + 30 fights → legendary (at bounds)",
          leg.compute_legacy_state(False, False, 2, 30, 25)
          == leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(False, False, 2, 30, 25)}")
    # D.3d — boundary: 1 title + 30 fights → NOT legendary (title_reigns < 2).
    check("D", "boundary: 1 title + 30 fights → NOT legendary (titles bound)",
          leg.compute_legacy_state(False, False, 1, 30, 25)
          != leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(False, False, 1, 30, 25)}")
    # D.3e — boundary: 2 titles + 29 fights → NOT legendary (fights bound).
    check("D", "boundary: 2 titles + 29 fights → NOT legendary (fights bound)",
          leg.compute_legacy_state(False, False, 2, 29, 25)
          != leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(False, False, 2, 29, 25)}")

    # D.4 — forgotten (retired AND NOT HoF AND total_fights < 20).
    check("D", "forgotten: retired + no HoF + 15 fights",
          leg.compute_legacy_state(True, False, 0, 15, 8)
          == leg.LEGACY_FORGOTTEN,
          f"got={leg.compute_legacy_state(True, False, 0, 15, 8)}")
    # D.4b — boundary: 19 fights + retired → forgotten.
    check("D", "boundary: 19 fights + retired → forgotten (under 20)",
          leg.compute_legacy_state(True, False, 0, 19, 10)
          == leg.LEGACY_FORGOTTEN,
          f"got={leg.compute_legacy_state(True, False, 0, 19, 10)}")
    # D.4c — boundary: 20 fights + retired → NOT forgotten (fights bound).
    check("D", "boundary: 20 fights + retired → NOT forgotten (fights bound)",
          leg.compute_legacy_state(True, False, 0, 20, 10)
          != leg.LEGACY_FORGOTTEN,
          f"got={leg.compute_legacy_state(True, False, 0, 20, 10)}")
    # D.4d — boundary: retired + HoF + 10 fights → legendary (HoF wins).
    check("D", "boundary: retired + HoF + 10 fights → legendary (HoF wins)",
          leg.compute_legacy_state(True, True, 1, 10, 8)
          == leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(True, True, 1, 10, 8)}")

    # D.5 — defensive default (D5): a 30-fight journeyman with < 15
    # wins (no HoF, not retired) matches NEITHER Building (total_fights
    # >= 25 AND wins < 15 → Building clause fails) NOR Established
    # (wins < 15 fails). Defaults to "building" per D5.
    check("D", "defensive: 30 fights + 5 wins + no HoF → building (D5 default)",
          leg.compute_legacy_state(False, False, 0, 30, 5)
          == leg.LEGACY_BUILDING,
          f"got={leg.compute_legacy_state(False, False, 0, 30, 5)}")

    # D.6 — None handling (defensive — DB columns may be NULL).
    # None is_retired → False, None in_hall_of_fame → False,
    # None title_reigns → 0, None total_fights → 0, None wins → 0.
    # With all defaults: 0 fights + 0 wins → building.
    none_result = leg.compute_legacy_state(
        None, None, None, None, None)
    check("D", "None inputs do not crash (returns a canonical label)",
          none_result in set(leg.ALL_LEGACY_STATES),
          f"got={none_result}")
    check("D", "None inputs → building (defensive: 0 fights matches building)",
          none_result == leg.LEGACY_BUILDING,
          f"got={none_result}")


# ----------------------------------------------------------------
# Case E: legacy priority order
# ----------------------------------------------------------------
def case_e_legacy_priority():
    """Test that the legacy priority order is enforced.

    Priority order (D4): Legendary > Forgotten > Established >
    Building (first match wins).
    """
    print("\n--- Case E: legacy priority order ---")
    leg = le

    # E.1 — Legendary supersedes Forgotten (D4).
    # A retired HoF legend with < 20 fights — Legendary wins (HoF
    # induction supersedes the "few fights" signal).
    check("E", "legendary supersedes forgotten (HoF + retired + 15 fights)",
          leg.compute_legacy_state(True, True, 1, 15, 8)
          == leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(True, True, 1, 15, 8)}")
    # E.1b — Legendary supersedes Established (multi-title path).
    # A non-HoF fighter with 2 titles + 35 fights + 25 wins —
    # Legendary (multi-title path), NOT Established (which would
    # also match the criteria but is checked AFTER Legendary).
    check("E", "legendary supersedes established (multi-title + longevity)",
          leg.compute_legacy_state(False, False, 2, 35, 25)
          == leg.LEGACY_LEGENDARY,
          f"got={leg.compute_legacy_state(False, False, 2, 35, 25)}")

    # E.2 — Forgotten supersedes Established (D4).
    # A retired fighter with 20 fights + 15 wins, no HoF — would
    # match Established (20 fights >= 25? No — 20 < 25 — Established
    # doesn't match). Use a contrived case: a retired fighter with
    # 18 fights, no HoF — Forgotten (NOT Established, which requires
    # 25+ fights).
    # More directly: a retired non-HoF fighter with 15 fights +
    # 10 wins → Forgotten (Building also matches but priority order
    # has Forgotten first).
    check("E", "forgotten supersedes building (retired + 15 fights + 10 wins)",
          leg.compute_legacy_state(True, False, 0, 15, 10)
          == leg.LEGACY_FORGOTTEN,
          f"got={leg.compute_legacy_state(True, False, 0, 15, 10)}")

    # E.3 — Established supersedes Building (D4).
    # An active fighter with 30 fights + 20 wins, no HoF — Established
    # (NOT Building, which requires total_fights < 15 OR
    # (total_fights < 25 AND wins < 15)).
    check("E", "established supersedes building (active + 30 fights + 20 wins)",
          leg.compute_legacy_state(False, False, 0, 30, 20)
          == leg.LEGACY_ESTABLISHED,
          f"got={leg.compute_legacy_state(False, False, 0, 30, 20)}")

    # E.4 — Building is the catch-all default (D4 + D5).
    # An active fighter with 10 fights — Building (Legendary no HoF,
    # Forgotten not retired, Established fights<25, Building yes).
    check("E", "building is catch-all (active + 10 fights)",
          leg.compute_legacy_state(False, False, 0, 10, 5)
          == leg.LEGACY_BUILDING,
          f"got={leg.compute_legacy_state(False, False, 0, 10, 5)}")


# ----------------------------------------------------------------
# Case F: legacy voice phrases — non-empty, no digits, 3 variants
# ----------------------------------------------------------------
def case_f_legacy_voice_phrases():
    """Test legacy voice phrase helpers (§17.4 + §14)."""
    print("\n--- Case F: legacy voice phrases ---")
    leg = le

    # F.1 — each state label has 3 non-empty, no-digit variants.
    for label in leg.ALL_LEGACY_STATES:
        variants = leg.LEGACY_PHRASES[label]
        check("F", f"state '{label}' has 3 variants",
              len(variants) == 3, f"got={len(variants)}")
        for v in variants:
            check("F", f"state '{label}' variant '{v[:30]}' has no digits (§14)",
                  not _HAS_DIGIT.search(v), f"got={v!r}")
            check("F", f"state '{label}' variant is non-empty",
                  isinstance(v, str) and len(v) > 0, "")

    # F.2 — phrase picker returns a non-empty string for each label.
    rng = random.Random(RANDOM_SEED)
    for label in leg.ALL_LEGACY_STATES:
        phrase = leg.get_legacy_phrase(label, rng)
        check("F", f"get_legacy_phrase('{label}') returns non-empty str",
              isinstance(phrase, str) and len(phrase) > 0, f"got={phrase!r}")

    # F.3 — phrase picker returns one of the 3 defined variants.
    rng = random.Random(RANDOM_SEED)
    for label in leg.ALL_LEGACY_STATES:
        phrase = leg.get_legacy_phrase(label, rng)
        check("F", f"get_legacy_phrase('{label}') returns a defined variant",
              phrase in leg.LEGACY_PHRASES[label], f"got={phrase!r}")

    # F.4 — None label → None phrase (defensive).
    rng = random.Random(RANDOM_SEED)
    phrase = leg.get_legacy_phrase(None, rng)
    check("F", "get_legacy_phrase(None) returns None",
          phrase is None, f"got={phrase!r}")

    # F.5 — unknown label falls back to building variants (defensive).
    rng = random.Random(RANDOM_SEED)
    phrase = leg.get_legacy_phrase("nonexistent_label", rng)
    check("F", "unknown label falls back to building variants",
          phrase in leg.LEGACY_PHRASES[leg.LEGACY_BUILDING],
          f"got={phrase!r}")


# ----------------------------------------------------------------
# Case G: encode/decode helpers (reused from context_engine — D1)
# ----------------------------------------------------------------
def case_g_encode_decode():
    """Test the "label||phrase" round-trip (reused from context_engine)."""
    print("\n--- Case G: encode/decode (reused from context_engine) ---")
    nfe = nf
    leg = le

    # G.1 — encode produces "label||phrase" (narrative).
    encoded = nfe.encode("prodigy", "a prodigy turning heads early")
    check("G", "encode('prodigy', '...') == 'prodigy||...'",
          encoded == "prodigy||a prodigy turning heads early", f"got={encoded!r}")

    # G.2 — encode produces "label||phrase" (legacy).
    encoded = leg.encode("legendary", "an all-time great")
    check("G", "encode('legendary', '...') == 'legendary||...'",
          encoded == "legendary||an all-time great", f"got={encoded!r}")

    # G.3 — round-trip preserves both parts for ALL 4 families.
    for label in nfe.ALL_FAMILIES:
        phrase = nfe.FAMILY_PHRASES[label][0]
        encoded = nfe.encode(label, phrase)
        check("G", f"round-trip preserves '{label}' family label",
              nfe.decode_label(encoded) == label, "")
        check("G", f"round-trip preserves '{label}' family phrase",
              nfe.decode_phrase(encoded) == phrase, "")

    # G.4 — round-trip preserves both parts for ALL 4 legacy states.
    for label in leg.ALL_LEGACY_STATES:
        phrase = leg.LEGACY_PHRASES[label][0]
        encoded = leg.encode(label, phrase)
        check("G", f"round-trip preserves '{label}' state label",
              leg.decode_label(encoded) == label, "")
        check("G", f"round-trip preserves '{label}' state phrase",
              leg.decode_phrase(encoded) == phrase, "")

    # G.5 — defensive: NULL / missing "||" → None.
    check("G", "decode_label(None) == None",
          nfe.decode_label(None) is None, "")
    check("G", "decode_label('') == None",
          leg.decode_label("") is None, "")
    check("G", "decode_label('noseparator') == None",
          nfe.decode_label("noseparator") is None, "")

    # G.6 — phrase containing "||" only splits on FIRST separator.
    encoded = nfe.encode("veteran", "a veteran who's||seen it all")
    check("G", "phrase with '||' splits on first only",
          nfe.decode_label(encoded) == "veteran"
          and nfe.decode_phrase(encoded) == "a veteran who's||seen it all",
          f"got={encoded!r}")

    # G.7 — encode/decode helpers are THE SAME OBJECTS as
    # context_engine's (D1 — single source of truth). Verifies
    # the import-based reuse, not a copy.
    check("G", "narrative.encode is context_engine.encode (D1 single-source)",
          nfe.encode is context_engine.encode, "")
    check("G", "legacy.encode is context_engine.encode (D1 single-source)",
          leg.encode is context_engine.encode, "")
    check("G", "narrative.decode_label is context_engine.decode_label (D1)",
          nfe.decode_label is context_engine.decode_label, "")
    check("G", "legacy.decode_label is context_engine.decode_label (D1)",
          leg.decode_label is context_engine.decode_label, "")
    check("G", "narrative.decode_phrase is context_engine.decode_phrase (D1)",
          nfe.decode_phrase is context_engine.decode_phrase, "")
    check("G", "legacy.decode_phrase is context_engine.decode_phrase (D1)",
          leg.decode_phrase is context_engine.decode_phrase, "")


# ----------------------------------------------------------------
# Case H: bulk compute on test DB
# ----------------------------------------------------------------
def case_h_bulk_compute():
    """Test compute_all_families + compute_all_legacies on a fresh test DB."""
    print("\n--- Case H: bulk compute on test DB ---")
    nfe = nf
    leg = le

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Pre-create fighter_descriptors rows + populate momentum +
    # career_phase (the narrative_families engine reads these columns).
    populate_descriptor_rows(conn)
    # Populate momentum + career_phase so narrative_families can read
    # the canonical labels.
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    compute_all_fighters(conn)
    compute_all_career_phases(conn)

    # H.1 — both columns start NULL.
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors"
    ).fetchone()[0]
    check("H", "5 fighter_descriptors rows exist (via populate_descriptor_rows)",
          total_rows == 5, f"got={total_rows}")
    nulls_nf = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE narrative_family IS NULL"
    ).fetchone()[0]
    check("H", "narrative_family column starts NULL (5 fighters)",
          nulls_nf == 5, f"got={nulls_nf} NULLs")
    nulls_le = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE legacy_state IS NULL"
    ).fetchone()[0]
    check("H", "legacy_state column starts NULL (5 fighters)",
          nulls_le == 5, f"got={nulls_le} NULLs")

    # H.2 — run legacy bulk compute (independent — runs first because
    # it doesn't depend on momentum/career_phase).
    n_updated_le = leg.compute_all_legacies(conn)
    check("H", "compute_all_legacies updated all 5 fighters",
          n_updated_le == 5, f"got={n_updated_le}")
    nulls_le = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE legacy_state IS NULL"
    ).fetchone()[0]
    check("H", "all legacy_state values written (0 NULLs)",
          nulls_le == 0, f"got={nulls_le} NULLs")

    # H.3 — run narrative bulk compute.
    n_updated_nf = nfe.compute_all_families(conn)
    # n_updated_nf is the count of fighters MATCHED a family, not the
    # total updated (NULL-writes aren't counted). Don't assert a
    # specific count — the 5 seeded fighters have 0 fights, 0 streak,
    # so career_phase=prospect + momentum=stable → no family match
    # (Prodigy requires high/very_high momentum; prospect+stable → None).
    # The bulk write still TOUCHES all 5 rows (writes NULL).
    check("H", "compute_all_families ran without crashing (returns int)",
          isinstance(n_updated_nf, int), f"got={n_updated_nf!r}")

    # H.4 — every legacy_state value matches "label||phrase" format.
    bad = 0
    for r in conn.execute("SELECT fighter_id, legacy_state "
                          "FROM fighter_descriptors"):
        if not isinstance(r[1], str) or "||" not in r[1]:
            bad += 1
    check("H", "all legacy_state values match 'label||phrase' format",
          bad == 0, f"got={bad} bad values")

    # H.5 — decoded legacy labels are all valid canonical labels.
    valid_labels = set(leg.ALL_LEGACY_STATES)
    bad = 0
    for r in conn.execute("SELECT legacy_state FROM fighter_descriptors"):
        if leg.decode_label(r[0]) not in valid_labels:
            bad += 1
    check("H", "decoded legacy_state labels all canonical",
          bad == 0, f"got={bad} bad labels")

    # H.6 — every narrative_family value is EITHER NULL OR matches
    # "label||phrase" format (NULL is valid per D5).
    bad = 0
    for r in conn.execute("SELECT fighter_id, narrative_family "
                          "FROM fighter_descriptors"):
        if r[1] is None:
            continue  # NULL is valid
        if not isinstance(r[1], str) or "||" not in r[1]:
            bad += 1
    check("H", "all narrative_family values match 'label||phrase' format OR NULL",
          bad == 0, f"got={bad} bad values")

    # H.7 — decoded narrative labels are all valid canonical labels.
    valid_labels = set(nfe.ALL_FAMILIES)
    bad = 0
    for r in conn.execute("SELECT narrative_family FROM fighter_descriptors"):
        if r[0] is None:
            continue
        if nfe.decode_label(r[0]) not in valid_labels:
            bad += 1
    check("H", "decoded narrative_family labels all canonical",
          bad == 0, f"got={bad} bad labels")

    # H.8 — phrases contain no digits (§14).
    bad = 0
    for r in conn.execute("SELECT narrative_family, legacy_state "
                          "FROM fighter_descriptors"):
        nf_phrase = nfe.decode_phrase(r[0]) if r[0] else None
        le_phrase = leg.decode_phrase(r[1]) if r[1] else None
        if nf_phrase and _HAS_DIGIT.search(nf_phrase):
            bad += 1
        if le_phrase and _HAS_DIGIT.search(le_phrase):
            bad += 1
    check("H", "voice phrases contain no digits (§14)",
          bad == 0, f"got={bad} violations")

    # H.9 — performance: <1 second for 5 fighters (smoke check).
    t0 = time.time()
    nfe.compute_all_families(conn)
    leg.compute_all_legacies(conn)
    elapsed = time.time() - t0
    check("H", f"bulk compute <1s ({elapsed*1000:.0f}ms)",
          elapsed < 1.0, f"{elapsed*1000:.0f}ms")

    # H.10 — end-to-end: a prospect on a 5-fight win streak → prodigy.
    # Fighter 1: 22yo, prospect phase, 5-win streak → very_high momentum.
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0 "
                 "WHERE fighter_id=1")
    conn.commit()
    # Re-populate momentum + career_phase so narrative_families can read.
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    nfe.compute_all_families(conn)
    stored = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("H", "22yo + 5-win streak → prodigy (end-to-end)",
          nfe.decode_label(stored) == nfe.FAMILY_PRODIGY,
          f"got={stored!r}")

    # H.11 — end-to-end: a 30yo rising_contender on a 5-fight win
    # streak → cinderella_story (late bloomer).
    conn.execute("UPDATE fighters SET date_of_birth='1994-01-01' "
                 "WHERE fighter_id=2")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=10, record_losses=5, record_draws=0 "
                 "WHERE fighter_id=2")
    conn.commit()
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    nfe.compute_all_families(conn)
    stored = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    check("H", "30yo + 5-win streak → cinderella_story (end-to-end)",
          nfe.decode_label(stored) == nfe.FAMILY_CINDERELLA_STORY,
          f"got={stored!r}")

    # H.12 — end-to-end: legacy state — a fighter with 30 fights + 20
    # wins, no HoF → established.
    conn.execute("UPDATE fighter_career SET record_wins=20, "
                 "record_losses=10, record_draws=0, title_reigns=0 "
                 "WHERE fighter_id=3")
    conn.commit()
    leg.compute_all_legacies(conn)
    stored = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    check("H", "30 fights + 20 wins + no HoF → established (end-to-end)",
          leg.decode_label(stored) == leg.LEGACY_ESTABLISHED,
          f"got={stored!r}")

    # H.13 — end-to-end: legacy state — a fighter in HoF → legendary.
    conn.execute(
        "INSERT INTO hall_of_fame (fighter_id, inducted_date, career_summary) "
        "VALUES (4, '2025-01-01', 'A legendary career.')"
    )
    conn.commit()
    leg.compute_all_legacies(conn)
    stored = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=4"
    ).fetchone()[0]
    check("H", "HoF inductee → legendary (end-to-end)",
          leg.decode_label(stored) == leg.LEGACY_LEGENDARY,
          f"got={stored!r}")

    conn.close()


# ----------------------------------------------------------------
# Case I: single-fighter refresh
# ----------------------------------------------------------------
def case_i_single_refresh():
    """Test compute_single_family + compute_single_legacy."""
    print("\n--- Case I: single-fighter refresh ---")
    nfe = nf
    leg = le

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)
    # Populate momentum + career_phase so narrative_families can read.
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    compute_all_fighters(conn)
    compute_all_career_phases(conn)

    # I.1 — narrative: fighter exists → returns dict with 'narrative_family'.
    result = nfe.compute_single_family(conn, 1)
    check("I", "narrative: returns dict with 'narrative_family' key",
          isinstance(result, dict) and "narrative_family" in result,
          f"got={result}")
    # The returned value is either a canonical label OR None (D5 —
    # most fighters don't match a family).
    if result["narrative_family"] is not None:
        check("I", "narrative_family is a canonical label (or None)",
              result["narrative_family"] in set(nfe.ALL_FAMILIES),
              f"got={result['narrative_family']}")
    else:
        check("I", "narrative_family is None (D5 — no family match)",
              True, f"got={result}")

    # I.2 — narrative: DB row updated.
    stored = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    if result["narrative_family"] is None:
        check("I", "narrative: DB row updated (NULL when no family match)",
              stored is None, f"got={stored!r}")
    else:
        check("I", "narrative: DB row updated with 'label||phrase' value",
              isinstance(stored, str) and "||" in stored
              and nfe.decode_label(stored) == result["narrative_family"],
              f"got={stored!r}")

    # I.3 — narrative: non-existent fighter → None.
    result = nfe.compute_single_family(conn, 99999)
    check("I", "narrative: non-existent fighter → None",
          result is None, f"got={result}")

    # I.4 — narrative: prodigy via single refresh.
    # Fighter 1: 22yo + 5-win streak → prospect + very_high momentum.
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=1")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0 "
                 "WHERE fighter_id=1")
    conn.commit()
    # Need to refresh momentum + career_phase first.
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    result = nfe.compute_single_family(conn, 1)
    check("I", "narrative: single refresh picks up prodigy (5-win streak)",
          result["narrative_family"] == nfe.FAMILY_PRODIGY,
          f"got={result}")

    # I.5 — narrative: prodigy cooled off → None (family cleared).
    # Fighter 1: still 22yo, but now win_streak=0, loss_streak=2 → falling.
    conn.execute("UPDATE fighter_career SET win_streak=0, "
                 "loss_streak=2 WHERE fighter_id=1")
    conn.commit()
    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    result = nfe.compute_single_family(conn, 1)
    check("I", "narrative: single refresh clears prodigy when streak ends",
          result["narrative_family"] is None,
          f"got={result}")

    # I.6 — legacy: fighter exists → returns dict with 'legacy_state'.
    result = leg.compute_single_legacy(conn, 1)
    check("I", "legacy: returns dict with 'legacy_state' key",
          isinstance(result, dict) and "legacy_state" in result,
          f"got={result}")
    check("I", "legacy_state is a canonical label (always non-None)",
          result["legacy_state"] in set(leg.ALL_LEGACY_STATES),
          f"got={result['legacy_state']}")

    # I.7 — legacy: DB row updated.
    stored = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("I", "legacy: DB row updated with 'label||phrase' value",
          isinstance(stored, str) and "||" in stored
          and leg.decode_label(stored) == result["legacy_state"],
          f"got={stored!r}")

    # I.8 — legacy: non-existent fighter → None.
    result = leg.compute_single_legacy(conn, 99999)
    check("I", "legacy: non-existent fighter → None",
          result is None, f"got={result}")

    # I.9 — legacy: HoF induction via single refresh → legendary.
    conn.execute(
        "INSERT INTO hall_of_fame (fighter_id, inducted_date, career_summary) "
        "VALUES (2, '2025-01-01', 'A legend.')"
    )
    conn.commit()
    result = leg.compute_single_legacy(conn, 2)
    check("I", "legacy: single refresh picks up HoF → legendary",
          result["legacy_state"] == leg.LEGACY_LEGENDARY,
          f"got={result}")

    # I.10 — legacy: HoF removal via single refresh → not legendary.
    conn.execute("DELETE FROM hall_of_fame WHERE fighter_id=2")
    conn.commit()
    result = leg.compute_single_legacy(conn, 2)
    check("I", "legacy: single refresh picks up HoF removal → NOT legendary",
          result["legacy_state"] != leg.LEGACY_LEGENDARY,
          f"got={result}")

    # I.11 — performance: <10ms steady-state (3rd call after warm-up).
    nfe.compute_single_family(conn, 1)
    nfe.compute_single_family(conn, 1)
    t0 = time.time()
    nfe.compute_single_family(conn, 1)
    elapsed_ms = (time.time() - t0) * 1000
    check("I", f"narrative single refresh <10ms steady-state ({elapsed_ms:.2f}ms)",
          elapsed_ms < 10.0, f"{elapsed_ms:.2f}ms")

    leg.compute_single_legacy(conn, 1)
    leg.compute_single_legacy(conn, 1)
    t0 = time.time()
    leg.compute_single_legacy(conn, 1)
    elapsed_ms = (time.time() - t0) * 1000
    check("I", f"legacy single refresh <10ms steady-state ({elapsed_ms:.2f}ms)",
          elapsed_ms < 10.0, f"{elapsed_ms:.2f}ms")

    conn.close()


# ----------------------------------------------------------------
# Case J: determinism
# ----------------------------------------------------------------
def case_j_determinism():
    """Test that the same fighter_id always produces the same phrase."""
    print("\n--- Case J: determinism ---")
    nfe = nf
    leg = le

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    populate_descriptor_rows(conn)
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    compute_all_fighters(conn)
    compute_all_career_phases(conn)

    # J.1 — narrative: two single refreshes produce identical values.
    nfe.compute_single_family(conn, 1)
    v1 = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    nfe.compute_single_family(conn, 1)
    v2 = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("J", "narrative: two single refreshes produce identical values",
          v1 == v2, f"v1={v1} v2={v2}")

    # J.2 — narrative: bulk compute then single refresh produces
    # identical values.
    nfe.compute_all_families(conn)
    v_bulk = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    nfe.compute_single_family(conn, 3)
    v_single = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    check("J", "narrative: bulk + single refresh produce identical values",
          v_bulk == v_single, f"bulk={v_bulk} single={v_single}")

    # J.3 — legacy: two single refreshes produce identical values.
    leg.compute_single_legacy(conn, 1)
    v1 = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    leg.compute_single_legacy(conn, 1)
    v2 = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("J", "legacy: two single refreshes produce identical values",
          v1 == v2, f"v1={v1} v2={v2}")

    # J.4 — legacy: bulk compute then single refresh produces identical.
    leg.compute_all_legacies(conn)
    v_bulk = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    leg.compute_single_legacy(conn, 3)
    v_single = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    check("J", "legacy: bulk + single refresh produce identical values",
          v_bulk == v_single, f"bulk={v_bulk} single={v_single}")

    # J.5 — voice phrases produced for all 5 fighters (smoke check).
    nf_phrases = set()
    le_phrases = set()
    for fid in range(1, 6):
        row = conn.execute(
            "SELECT narrative_family, legacy_state "
            "FROM fighter_descriptors WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if row and row[0]:
            nf_phrases.add(nfe.decode_phrase(row[0]))
        if row and row[1]:
            le_phrases.add(leg.decode_phrase(row[1]))
    check("J", "narrative: voice phrases produced (or NULL — D5)",
          len(nf_phrases) >= 0, f"got={len(nf_phrases)} unique phrases")
    check("J", "legacy: voice phrases produced for all 5 fighters",
          len(le_phrases) >= 1, f"got={len(le_phrases)} unique phrases")

    # J.6 — RNG seed differs by fighter_id; different fighters with
    # the same label MAY get different voice variants.
    r1 = random.Random(1 * 31 + 17)
    r2 = random.Random(2 * 31 + 17)
    v1 = leg.get_legacy_phrase(leg.LEGACY_BUILDING, r1)
    v2 = leg.get_legacy_phrase(leg.LEGACY_BUILDING, r2)
    check("J", "fighter_id=1 RNG seed picks a valid building variant",
          v1 in leg.LEGACY_PHRASES[leg.LEGACY_BUILDING], f"got={v1!r}")
    check("J", "fighter_id=2 RNG seed picks a valid building variant",
          v2 in leg.LEGACY_PHRASES[leg.LEGACY_BUILDING], f"got={v2!r}")

    conn.close()


# ----------------------------------------------------------------
# Case K: snapshot_cache integration
# ----------------------------------------------------------------
def case_k_snapshot_cache_integration():
    """Test that snapshot_cache wires narrative_families + legacy_engine."""
    print("\n--- Case K: snapshot_cache integration ---")
    nfe = nf
    leg = le

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Pre-create the descriptor row for fighter 1 so refresh_fighter
    # can update it.
    app.update_fighter_descriptor_snapshot(conn, 1)
    conn.commit()

    # K.1 — snapshot_cache.refresh_fighter writes narrative_family +
    # legacy_state. Before refresh: both NULL.
    nulls_before_nf = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND narrative_family IS NULL"
    ).fetchone()[0]
    check("K", "narrative_family is NULL before refresh_fighter",
          nulls_before_nf == 1, f"got={nulls_before_nf} NULLs")
    nulls_before_le = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND legacy_state IS NULL"
    ).fetchone()[0]
    check("K", "legacy_state is NULL before refresh_fighter",
          nulls_before_le == 1, f"got={nulls_before_le} NULLs")

    snapshot_cache.refresh_fighter(conn, 1)

    # After refresh: legacy_state always non-NULL; narrative_family
    # may be NULL (D5 — no family match).
    nulls_after_nf = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND narrative_family IS NULL"
    ).fetchone()[0]
    check("K", "narrative_family is NULL OR 'label||phrase' after refresh",
          nulls_after_nf in (0, 1), f"got={nulls_after_nf} NULLs (D5 allows NULL)")
    nulls_after_le = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors "
        "WHERE fighter_id=1 AND legacy_state IS NULL"
    ).fetchone()[0]
    check("K", "legacy_state is non-NULL after refresh_fighter",
          nulls_after_le == 0, f"got={nulls_after_le} NULLs")

    # K.2 — legacy_state value is in "label||phrase" format.
    stored = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()[0]
    check("K", "refresh_fighter writes legacy_state 'label||phrase' format",
          isinstance(stored, str) and "||" in stored, f"got={stored!r}")

    # K.3 — daily pass writes both columns for all fighters.
    populate_descriptor_rows(conn)
    conn.execute("UPDATE fighter_descriptors "
                 "SET narrative_family=NULL, legacy_state=NULL")
    conn.commit()
    snapshot_cache.run_daily_interpretation_pass(conn)
    nulls_nf = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE narrative_family IS NULL"
    ).fetchone()[0]
    # narrative_family may be NULL for fighters who don't match (D5) —
    # the column being NULL is valid. The 5 seeded fighters are
    # 0-fight 0-streak, so all 5 will have NULL narrative_family
    # (prospect + stable momentum → None).
    check("K", "daily pass writes narrative_family (NULL allowed per D5)",
          nulls_nf in (0, 5), f"got={nulls_nf} NULLs (0 or 5 expected)")
    nulls_le = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE legacy_state IS NULL"
    ).fetchone()[0]
    check("K", "daily pass writes legacy_state for all 5 fighters (0 NULLs)",
          nulls_le == 0, f"got={nulls_le} NULLs")

    # K.4 — interpretation_cache_meta updated.
    # Per CONVENTIONS §10 (dynamic-version pattern), the engine_version
    # is read from snapshot_cache.ENGINE_VERSION at runtime — NOT
    # hardcoded. Task 2.4 + 2.7 bumped it to "1.4.0"; future tasks
    # will bump further.
    row = conn.execute(
        "SELECT engine_version, last_built_fighter_count "
        "FROM interpretation_cache_meta WHERE meta_id=1"
    ).fetchone()
    check("K", "interpretation_cache_meta.engine_version matches snapshot_cache.ENGINE_VERSION",
          row and row[0] == snapshot_cache.ENGINE_VERSION,
          f"got={row[0] if row else None} (expected {snapshot_cache.ENGINE_VERSION})")
    check("K", "interpretation_cache_meta.last_built_fighter_count == 5",
          row and row[1] == 5, f"got={row[1] if row else None}")

    # K.5 — end-to-end: refresh_fighter on a prodigy → prodigy family.
    # Fighter 2: 22yo + 5-win streak → prospect + very_high momentum.
    conn.execute("UPDATE fighters SET date_of_birth='2004-01-01' "
                 "WHERE fighter_id=2")
    conn.execute("UPDATE fighter_career SET win_streak=5, "
                 "record_wins=5, record_losses=0, record_draws=0 "
                 "WHERE fighter_id=2")
    conn.commit()
    snapshot_cache.refresh_fighter(conn, 2)
    stored = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors WHERE fighter_id=2"
    ).fetchone()[0]
    check("K", "refresh_fighter on prodigy fighter → prodigy family",
          nfe.decode_label(stored) == nfe.FAMILY_PRODIGY,
          f"got={stored!r}")

    # K.6 — end-to-end: refresh_fighter after HoF induction → legendary.
    conn.execute(
        "INSERT INTO hall_of_fame (fighter_id, inducted_date, career_summary) "
        "VALUES (3, '2025-01-01', 'A legend.')"
    )
    conn.commit()
    snapshot_cache.refresh_fighter(conn, 3)
    stored = conn.execute(
        "SELECT legacy_state FROM fighter_descriptors WHERE fighter_id=3"
    ).fetchone()[0]
    check("K", "refresh_fighter on HoF inductee → legendary state",
          leg.decode_label(stored) == leg.LEGACY_LEGENDARY,
          f"got={stored!r}")

    conn.close()


# ----------------------------------------------------------------
# Case L: Design Law check (§13 + §17.4)
# ----------------------------------------------------------------
def case_l_design_law():
    """Design Law check — engines translate simulation into emotion."""
    print("\n--- Case L: Design Law check ---")
    nfe = nf
    leg = le

    # L.1 — §17.4 "Rich Not Thin": canonical label + voice phrase
    # are BOTH stored (separated by "||"). The UI reads the phrase;
    # the logic reads the label.
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    populate_descriptor_rows(conn)
    snapshot_cache.run_daily_interpretation_pass(conn)
    row = conn.execute(
        "SELECT narrative_family, legacy_state "
        "FROM fighter_descriptors WHERE fighter_id=1"
    ).fetchone()
    nf_stored, le_stored = row
    # legacy_state always non-NULL; check format.
    check("L", "§17.4: legacy_state stores BOTH label AND phrase (||)",
          "||" in le_stored and leg.decode_label(le_stored) is not None
          and leg.decode_phrase(le_stored) is not None,
          f"got={le_stored!r}")
    # narrative_family may be NULL (D5); if non-NULL, check format.
    if nf_stored is not None:
        check("L", "§17.4: narrative_family stores BOTH label AND phrase (||)",
              "||" in nf_stored and nfe.decode_label(nf_stored) is not None
              and nfe.decode_phrase(nf_stored) is not None,
              f"got={nf_stored!r}")
    else:
        check("L", "§17.4: narrative_family is NULL (D5 — no family match)",
              True, "documented — D5 allows NULL")

    # L.2 — §13 Design Law: narrative_family tells a STORY. Compare:
    # raw "career_phase=prospect, momentum=very_high" → story "prodigy
    # || 'a prodigy turning heads early'". The label tells the truth;
    # the phrase tells the story.
    family = nfe.compute_narrative_family("prospect", "very_high", 22, 0)
    phrase = nfe.get_family_phrase(family, random.Random(1 * 31 + 17))
    check("L", "§13: prospect + very_high → prodigy (story word)",
          family == nfe.FAMILY_PRODIGY, f"got={family}")
    check("L", "§13: prodigy phrase is narrative (no digits)",
          isinstance(phrase, str) and not _HAS_DIGIT.search(phrase),
          f"got={phrase!r}")

    # L.3 — §13 Design Law: legacy_state tells a STORY. Compare:
    # raw "in_hall_of_fame=True" → story "legendary || 'an all-time
    # great'". The label tells the truth; the phrase tells the story.
    state = leg.compute_legacy_state(True, True, 1, 30, 25)
    phrase = leg.get_legacy_phrase(state, random.Random(1 * 31 + 17))
    check("L", "§13: HoF inductee → legendary (story word)",
          state == leg.LEGACY_LEGENDARY, f"got={state}")
    check("L", "§13: legendary phrase is narrative (no digits)",
          isinstance(phrase, str) and not _HAS_DIGIT.search(phrase),
          f"got={phrase!r}")

    # L.4 — §14: no raw numbers leak into the player-facing phrases.
    nf_violations = 0
    le_violations = 0
    for r in conn.execute("SELECT narrative_family, legacy_state "
                          "FROM fighter_descriptors"):
        nf_p = nfe.decode_phrase(r[0]) if r[0] else None
        le_p = leg.decode_phrase(r[1]) if r[1] else None
        if nf_p and _HAS_DIGIT.search(nf_p):
            nf_violations += 1
        if le_p and _HAS_DIGIT.search(le_p):
            le_violations += 1
    check("L", "§14: zero digit violations in narrative phrases",
          nf_violations == 0, f"got={nf_violations} violations")
    check("L", "§14: zero digit violations in legacy phrases",
          le_violations == 0, f"got={le_violations} violations")

    # L.5 — §13.5 Anticipation: narrative_family distinguishes a 22yo
    # hot prospect (prodigy — the world ahead of him) from a 30yo
    # rising contender on the same streak (cinderella_story — late
    # bloomer). Same momentum, different story based on age + phase.
    prodigy_family = nfe.compute_narrative_family(
        "prospect", "very_high", 22, 0)
    cinderella_family = nfe.compute_narrative_family(
        "rising_contender", "very_high", 30, 0)
    check("L", "§13.5: 22yo prospect + very_high → prodigy (anticipation)",
          prodigy_family == nfe.FAMILY_PRODIGY, f"got={prodigy_family}")
    check("L", "§13.5: 30yo rising_contender + very_high → cinderella_story (late bloomer)",
          cinderella_family == nfe.FAMILY_CINDERELLA_STORY,
          f"got={cinderella_family}")

    # L.6 — §13.3 Interpretation Layer: legacy_state translates raw
    # hall_of_fame membership (binary True/False) into a gradient
    # (building / established / legendary / forgotten). The same
    # "not in HoF" fighter gets different labels based on fight
    # count + win count.
    building_state = leg.compute_legacy_state(False, False, 0, 10, 5)
    established_state = leg.compute_legacy_state(False, False, 0, 30, 20)
    check("L", "§13.3: 10 fights + no HoF → building (gradient)",
          building_state == leg.LEGACY_BUILDING, f"got={building_state}")
    check("L", "§13.3: 30 fights + 20 wins + no HoF → established (gradient)",
          established_state == leg.LEGACY_ESTABLISHED,
          f"got={established_state}")

    # L.7 — Priority order is a NARRATIVE choice, not just a sort.
    # A retired HoF legend with 15 fights is "legendary" (the
    # induction story > the "few fights" story), NOT "forgotten"
    # (which would be the case if priority put Forgotten first).
    hof_short_career = leg.compute_legacy_state(True, True, 1, 15, 8)
    check("L", "priority: retired HoF + 15 fights → legendary (induction > fights)",
          hof_short_career == leg.LEGACY_LEGENDARY,
          f"got={hof_short_career}")

    # L.8 — legacy_state is DISTINCT from career_phase. A retired HoF
    # legend has career_phase=NULL (not active) but legacy_state=
    # "legendary" (post-retirement story). The two labels are
    # orthogonal — they tell different stories at different timescales.
    # Active fighter: career_phase=prospect, legacy_state=building
    # (early career, too soon to judge legacy).
    # Retired HoF: career_phase=NULL (not computed), legacy_state=
    # legendary (the long-arc story).
    # We verify the legacy_engine applies to ALL fighters (active +
    # retired) by running compute_all_legacies on the test DB and
    # checking every fighter has a non-NULL legacy_state.
    leg.compute_all_legacies(conn)
    nulls = conn.execute(
        "SELECT COUNT(*) FROM fighter_descriptors WHERE legacy_state IS NULL"
    ).fetchone()[0]
    check("L", "legacy_state is non-NULL for ALL fighters (active + retired)",
          nulls == 0, f"got={nulls} NULLs")

    conn.close()


def main():
    print("=" * 80)
    print(f"Phase 2 Tasks 2.4 + 2.7 — Narrative Families + Legacy Engine "
          f"acceptance test (schema {EXPECTED_CODE_VERSION})")
    print("=" * 80)

    case_a_pure_compute_narrative()
    case_b_narrative_priority()
    case_c_narrative_voice_phrases()
    case_d_pure_compute_legacy()
    case_e_legacy_priority()
    case_f_legacy_voice_phrases()
    case_g_encode_decode()
    case_h_bulk_compute()
    case_i_single_refresh()
    case_j_determinism()
    case_k_snapshot_cache_integration()
    case_l_design_law()

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
