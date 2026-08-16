#!/usr/bin/env python3
"""Acceptance test for Task B2 — Beat Engine Depth.

Tests the B2 additions to the beat-level fight engine (B1 was the
basic beat loop + decision scoring; B2 adds the dramatic depth that
makes fights memorable):

  1. Fatigue system — gas=100 per fight, depletes per beat (phase-
     dependent costs), cardio + fatigue_tolerance slow decay, low
     gas (<30) reduces accuracy 30% and chin vulnerability +20%.
     Between rounds: gas += recovery_rate * 0.3 (capped at 100).
  2. Momentum system — cumulative momentum in a round shifts
     subsequent beat probabilities (initiator_advantage = clamp(
     cum_momentum/200, -0.3, +0.3)). Knockdown beats produce
     momentum_shift = +80, near-finish beats +60, big takedowns +30.
  3. Mid-round finishes — KO/TKO (cumulative damage threshold
     modified by chin/recovery_rate/grit/composure, killer_instinct
     increases finish probability), submission (submission_offense vs
     submission_defense/flexibility/scramble_ability/composure),
     doctor stoppage (cumulative damage > 200 + durability*2,
     checked between rounds), corner stoppage (3+ lost rounds +
     low grit/composure, 20% chance per qualifying round), DQ (low
     discipline + illegal strike, 1% per beat).
  4. Fight importance + pressure modifiers — importance computed
     from card_slot (40%) + is_title_fight (30%) + rivalry (15%, 0
     for now) + avg marketability (15%). In high-importance fights
     (>60), pressure_response (clutch_factor*0.35 + composure*0.25 +
     consistency*0.20 + focus*0.10 + grit*0.10) modifies beat scores:
     >= 70 → +5%, <= 30 → -10%.
  5. Commentary beat selection — after the fight resolves, selects
     3-14 most important beats (knockdowns, near-finishes, finish
     beat, big momentum swings) and writes commentary_segments.
     Beat count depends on importance (quick 3-6, standard 6-10,
     extended 10-14).

Schema changes (per the brief): modify fight_beats.outcome CHECK to
add 'knockdown' and 'near_finish'. Schema version 2.2.0 -> 2.3.0
(MINOR). Migration name: v2_3_0_beat_engine_depth. Per CONVENTIONS
§1.1, modifying a CHECK constraint on an existing table is a MINOR
bump (no breaking change to data shape — existing rows satisfy the
new CHECK because the new values are a superset of the old values).

D1 decision (in build_db.py + app.py worklog comments): the brief
mentioned `fight_rounds.fighter_a/b_gas_remaining` columns "already
exist but aren't populated yet" — they don't actually exist in the
v2.2.0 schema. Added them as REAL NOT NULL DEFAULT 100.0 columns
(per CONVENTIONS §1.1, adding columns to an existing table is a
MINOR bump; the DEFAULT 100.0 keeps existing INSERTs valid — a
fighter starting a round has 100 gas unless they carried over lower
gas from the previous round). resolve_round() writes the per-round
end-of-round gas values to these columns; resolve_next_fight()
ALSO tracks gas in-memory across rounds (gas starts at 100, depletes
per beat per _compute_gas_cost, recovers between rounds per
_recover_gas_between_rounds) and passes it to resolve_round() as
parameters. The fatigue system's effect is observable both via the
per-round gas columns AND via fight outcomes (cardio=90 out-lands
cardio=30 in later rounds), satisfying the brief's acceptance
criterion. NOTE: this breaks test_beat_engine.py case A.10's
hardcoded 18-column count assertion (now 20 columns) — flagged as
D-number D14 in the worklog per CONVENTIONS §11 (do NOT modify
existing tests; the dynamic-column-subset check pattern from
CONVENTIONS §10.4 is the durable replacement).

D2 decision (in app.py worklog comments): the brief's literal KO
threshold formula `100 - chin*0.5 - recovery_rate*0.2 - grit*0.1 -
composure*0.2` is mathematically INVERTED — higher chin → lower
threshold → easier to KO, which is wrong (a high-chin fighter should
be HARDER to KO). Corrected to `chin*0.5 + recovery_rate*0.2 +
grit*0.1 + composure*0.2`. This is a deviation from the brief's
literal text but matches the brief's clear INTENT (high-chin fighters
should be hard to KO).

D3 decision (in app.py worklog comments): the brief's submission
formula `submission_offense - submission_defense*0.5 - flexibility*0.3
- scramble_ability*0.2 + composure*0.1` is ambiguous about whose
`composure` (attacker or defender). Interpreted as the ATTACKER's
composure — a calm attacker is better at finishing submissions.

D4 decision (in app.py worklog comments): the brief was ambiguous
about whether `fighter_a_knockdowns` in fight_rounds means knockdowns
SCORED BY A or SUFFERED BY A. Chose "SCORED BY A" for consistency
with the other fighter_a_* columns (damage DEALT BY A, strikes
LANDED BY A, takedowns SCORED BY A — all "things A DID", not "things
DONE TO A"). This matches the convention used by the existing B1
columns.

Cases:

  A. Schema verification:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read DYNAMICALLY per CONVENTIONS §10).
     - schema_migrations contains a row starting with the dynamic
       prefix `v{version}_` (per CONVENTIONS §10.2).
     - fight_beats.outcome CHECK includes 'knockdown' and 'near_finish'
       (the 2 new B2 outcomes).
     - Inserting a beat with outcome='knockdown' or 'near_finish'
       succeeds (CHECK accepts the new values).
     - Inserting a beat with an invalid outcome still fails (CHECK
       rejects unknown values).
  B. Fatigue system:
     - _compute_gas_cost returns higher costs for higher-intensity
       phases (scramble > ground > clinch/cage > standing).
     - _compute_gas_cost returns lower costs for high-cardio /
       high-fatigue_tolerance fighters (gas depletes slower).
     - _recover_gas_between_rounds adds recovery_rate * 0.3 (capped
       at 100).
     - End-to-end: cardio=90 fighter out-lands cardio=30 fighter
       increasingly in later rounds (gas advantage compounds).
  C. Momentum system:
     - _compute_beat_scores applies the momentum_advantage modifier
       (positive advantage boosts attack, negative boosts defense).
     - Knockdown beats get momentum_shift = +80, near_finish +60,
       big takedowns +30 (when control_time_delta >= 3 — the
       _BIG_TAKEDOWN_MOMENTUM_THRESHOLD; control_time_delta is 1-5
       per _resolve_beat_outcome, so ~60% of landed takedowns
       qualify as "big").
  D. Mid-round KO/TKO:
     - _ko_threshold returns higher values for high-chin fighters
       (hard to KO) and lower for low-chin (easy to KO).
     - _ko_finish_probability scales with killer_instinct.
     - End-to-end: all-90 vs all-30 produces KO/TKO finishes (the
       favorite dominates and finishes).
     - Knockdown beats are recorded with outcome='knockdown' in
       fight_beats.
  E. Submission:
     - _submission_score returns positive for high submission_offense
       vs low defense (submission succeeds).
     - End-to-end: a high-submission_offense fighter produces some
       submission finishes.
     - Submission finishes record a near_finish beat (the tapping
       moment).
  F. Doctor stoppage:
     - _doctor_stoppage_threshold returns 200 + durability*2.
     - End-to-end: a fight where one fighter takes massive damage
       produces a doctor stoppage (between rounds).
  G. Corner stoppage:
     - _check_corner_stoppage returns False for < 3 consecutive
       losses, or for high grit/composure.
     - End-to-end: a durable loser with low grit/composure who loses
       3+ rounds produces some corner stoppages.
  H. DQ:
     - _check_dq returns False for high-discipline fighters, or for
       non-landed strikes.
     - End-to-end: a low-discipline fighter produces some DQs (rare
       — 1% per beat).
  I. Fight importance:
     - _compute_fight_importance returns high values for main event
       + title fight + high marketability.
     - Returns low values for opener + non-title + low marketability.
     - Card slot weights: main_event=100 > co_main=80 > featured_prelim=60
       > prelim=40 > opener=20.
  J. Pressure modifiers:
     - _compute_pressure_response returns the weighted sum of
       clutch_factor*0.35 + composure*0.25 + consistency*0.20 +
       focus*0.10 + grit*0.10.
     - _compute_pressure_modifier returns +5% for response >= 70 in
       high-importance fights, -10% for response <= 30, 0 otherwise.
     - Returns 0 in low-importance fights regardless of response.
  K. Commentary beat selection:
     - _select_commentary_beats returns the right number of beats
       based on importance (3-6 quick, 6-10 standard, 10-14 extended).
     - Knockdown beats are always selected (priority 1000).
     - The finishing beat is always selected (priority 900) when a
       finish occurred.
     - Near-finish beats are selected (priority 800).
     - Big momentum swings (|momentum_shift| > 50) are selected.
  L. End-to-end fight resolution:
     - All-90 beats all-30 >= 80% over 100 sims.
     - All-90 vs all-30 produces some KO/TKO finishes.
     - result_type can be ko_tko / submission / doctor_stoppage /
       corner_stoppage / dq / unanimous_decision / split_decision /
       draw.
     - finish_round is the round where the finish happened (not
       scheduled_rounds).
     - finish_time is a 'M:SS' string within the finishing round.
     - Commentary segments are written for the selected beats.

Run from the project root:
    python3 scripts/test_beat_engine_depth.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` — it does not modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each block of resolve_next_fight
  calls so the test is reproducible. The seed only pins down which
  random draws the beat engine sees, not what it does with them.
"""
import random
import re
import sqlite3
import subprocess
import sys
import os
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)

# Make src/ importable so we can call app.* and read build_db.CODE_SCHEMA_VERSION.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402

# Schema version + migration name prefix (read DYNAMICALLY from
# build_db per CONVENTIONS §10 — do NOT hardcode '2.3.0').
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Fighter IDs assigned by seed_data.py (Alpha Combat's two starters).
# John Vale = 1 (red corner), Marcus Reed = 2 (blue corner).
A_ID = 1
B_ID = 2

# All 25 attribute columns + all 20 personality columns (used to rig
# fights for deterministic test scenarios).
ALL_ATTR_COLS = app._FIGHTER_ATTR_COLUMNS
ALL_PERS_COLS = app._FIGHTER_PERS_COLUMNS

# Probabilistic thresholds (per the brief).
N_SIMS = 100
MIN_WINS_FOR_A = 80   # all-90 must win >= 80 of 100 vs all-30


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True,
        cwd=PROJECT_DIR,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True,
        cwd=PROJECT_DIR,
    )


def get_table_sql(conn, table_name):
    """Return the CREATE TABLE SQL for the given table.

    Used to verify CHECK constraints are present (we look for substrings
    like 'knockdown' and 'near_finish' in the fight_beats SQL).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row[0] if row else ""


def set_all_attrs(conn, fighter_id, value):
    """Set ALL 25 combat attributes + ALL 20 personality fields to `value`.

    Also sets the 3 fighters-table meta columns the B2 engine reads
    (marketability, clutch_factor, consistency) so fight importance +
    pressure response are fully controlled.

    Used by the win-rate + distribution checks. The full-attribute setup
    is required for B2: the per-phase beat scoring uses different
    attribute subsets, and the B2 helpers (_ko_threshold,
    _compute_pressure_response, etc.) read attributes that aren't in
    the phase maps.
    """
    set_clause_attrs = ", ".join(f"{c}={int(value)}" for c in ALL_ATTR_COLS)
    conn.execute(
        f"UPDATE fighter_attributes SET {set_clause_attrs}, "
        f"updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (fighter_id,),
    )
    set_clause_pers = ", ".join(f"{c}={int(value)}" for c in ALL_PERS_COLS)
    conn.execute(
        f"UPDATE fighter_personality SET {set_clause_pers}, "
        f"updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (fighter_id,),
    )
    # v2.3.0 (Task B2): set the 3 fighters-table meta columns the B2
    # engine reads for fight importance + pressure response.
    conn.execute(
        "UPDATE fighters SET marketability=?, clutch_factor=?, consistency=? "
        "WHERE fighter_id=?",
        (int(value), int(value), int(value), fighter_id),
    )


def set_attrs_explicit(conn, fighter_id, attr_dict=None, pers_dict=None,
                       meta_dict=None):
    """Set specific attributes on a fighter (fine-grained control).

    Used by cases that need to rig ONE attribute (e.g., chin=100 for
    the corner-stoppage test) without touching the others. All three
    dicts are optional — pass only the ones you want to set.
    """
    if attr_dict:
        set_clause = ", ".join(f"{k}={int(v)}" for k, v in attr_dict.items())
        conn.execute(
            f"UPDATE fighter_attributes SET {set_clause} "
            f"WHERE fighter_id=?",
            (fighter_id,),
        )
    if pers_dict:
        set_clause = ", ".join(f"{k}={int(v)}" for k, v in pers_dict.items())
        conn.execute(
            f"UPDATE fighter_personality SET {set_clause} "
            f"WHERE fighter_id=?",
            (fighter_id,),
        )
    if meta_dict:
        set_clause = ", ".join(f"{k}={int(v)}" for k, v in meta_dict.items())
        conn.execute(
            f"UPDATE fighters SET {set_clause} WHERE fighter_id=?",
            (fighter_id,),
        )


def reset_fight(conn, fight_id):
    """Clear a fight's result so resolve_next_fight() will pick it again.

    Mirrors the helper in test_beat_engine.py — resets fights winner/
    loser/result_type/finish_*/performance/fan to NULL, clears
    fight_participants.is_winner, deletes fight_beats/fight_rounds/
    fight_history/commentary_segments for the fight.
    """
    conn.execute(
        """
        UPDATE fights
        SET winner_fighter_id=NULL,
            loser_fighter_id=NULL,
            result_type=NULL,
            finish_round=NULL,
            finish_time=NULL,
            performance_rating=NULL,
            fan_reaction_rating=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE fight_id=?
        """,
        (fight_id,),
    )
    conn.execute(
        "UPDATE fight_participants SET is_winner=0 WHERE fight_id=?",
        (fight_id,),
    )
    conn.execute("DELETE FROM fight_beats WHERE fight_id=?", (fight_id,))
    conn.execute("DELETE FROM fight_rounds WHERE fight_id=?", (fight_id,))
    conn.execute("DELETE FROM fight_history WHERE fight_id=?", (fight_id,))
    conn.execute("DELETE FROM commentary_segments WHERE fight_id=?", (fight_id,))
    conn.commit()


def resolve_n_sims(conn, fight_id, n_sims, a_id, b_id):
    """Resolve the same fight n_sims times, tallying results.

    Returns a dict with wins_for_a, wins_for_b, draws, result_types
    (Counter), finish_rounds (list), finish_times (list), and
    knockdowns (total knockdown beats across all sims).
    """
    tallies = {
        "wins_for_a": 0,
        "wins_for_b": 0,
        "draws": 0,
        "result_types": Counter(),
        "finish_rounds": [],
        "finish_times": [],
        "knockdowns": 0,
        "near_finishes": 0,
    }
    for _ in range(n_sims):
        app.resolve_next_fight(conn)
        conn.commit()
        row = conn.execute(
            "SELECT winner_fighter_id, loser_fighter_id, result_type, "
            "finish_round, finish_time FROM fights WHERE fight_id=?",
            (fight_id,),
        ).fetchone()
        winner_id, loser_id, rt, fr, ft = row
        if winner_id == a_id:
            tallies["wins_for_a"] += 1
        elif winner_id == b_id:
            tallies["wins_for_b"] += 1
        else:
            tallies["draws"] += 1
        tallies["result_types"][rt] += 1
        tallies["finish_rounds"].append(fr if fr else 0)
        if ft:
            tallies["finish_times"].append(ft)
        kd = conn.execute(
            "SELECT COUNT(*) FROM fight_beats WHERE fight_id=? "
            "AND outcome='knockdown'",
            (fight_id,),
        ).fetchone()[0]
        nf = conn.execute(
            "SELECT COUNT(*) FROM fight_beats WHERE fight_id=? "
            "AND outcome='near_finish'",
            (fight_id,),
        ).fetchone()[0]
        tallies["knockdowns"] += kd
        tallies["near_finishes"] += nf
        reset_fight(conn, fight_id)
    return tallies


# --------------------------------------------------------------------
# Case A — Schema verification
# --------------------------------------------------------------------

def case_a_schema():
    """Verify schema version, migration, and the fight_beats.outcome CHECK."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # A.1 schema_meta.schema_version matches the dynamic code version.
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        f"A.1 schema_version matches build_db.CODE_SCHEMA_VERSION "
        f"({EXPECTED_CODE_VERSION})",
        sv and sv[0] == EXPECTED_CODE_VERSION,
        f"got={sv[0] if sv else None}, expected={EXPECTED_CODE_VERSION}",
    ))

    # A.2 schema_migrations contains a row with the dynamic prefix.
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    results.append((
        f"A.2 schema_migrations contains a row with prefix "
        f"{EXPECTED_MIGRATION_PREFIX!r}",
        mig is not None,
        f"got={mig[0] if mig else None}",
    ))

    # A.3 fight_beats.outcome CHECK includes 'knockdown' and 'near_finish'.
    beats_sql = get_table_sql(conn, "fight_beats")
    has_knockdown = "knockdown" in beats_sql
    has_near_finish = "near_finish" in beats_sql
    results.append((
        "A.3 fight_beats.outcome CHECK includes 'knockdown'",
        has_knockdown,
        f"knockdown_in_sql={has_knockdown}",
    ))
    results.append((
        "A.3 fight_beats.outcome CHECK includes 'near_finish'",
        has_near_finish,
        f"near_finish_in_sql={has_near_finish}",
    ))

    # A.4 Inserting a beat with outcome='knockdown' succeeds.
    # Use the seeded fight (fight_id=1).
    try:
        conn.execute(
            "INSERT INTO fight_beats (fight_id, round_number, beat_number, "
            "phase, action_type, initiator_fighter_id, target_fighter_id, "
            "outcome, damage_dealt, control_time_delta, momentum_shift) "
            "VALUES (1, 1, 999, 'standing', 'cross', 1, 2, 'knockdown', "
            "30, 0, 80)"
        )
        conn.commit()
        knockdown_insert_ok = True
    except sqlite3.IntegrityError:
        knockdown_insert_ok = False
        conn.rollback()
    results.append((
        "A.4 INSERT outcome='knockdown' succeeds (CHECK accepts the new value)",
        knockdown_insert_ok,
        f"insert_ok={knockdown_insert_ok}",
    ))

    # A.5 Inserting a beat with outcome='near_finish' succeeds.
    try:
        conn.execute(
            "INSERT INTO fight_beats (fight_id, round_number, beat_number, "
            "phase, action_type, initiator_fighter_id, target_fighter_id, "
            "outcome, damage_dealt, control_time_delta, momentum_shift) "
            "VALUES (1, 1, 998, 'ground_top', 'submission_attempt', 1, 2, "
            "'near_finish', 0, 5, 60)"
        )
        conn.commit()
        near_finish_insert_ok = True
    except sqlite3.IntegrityError:
        near_finish_insert_ok = False
        conn.rollback()
    results.append((
        "A.5 INSERT outcome='near_finish' succeeds (CHECK accepts the new value)",
        near_finish_insert_ok,
        f"insert_ok={near_finish_insert_ok}",
    ))

    # A.6 Inserting a beat with an INVALID outcome still fails.
    invalid_outcome_rejected = False
    try:
        conn.execute(
            "INSERT INTO fight_beats (fight_id, round_number, beat_number, "
            "phase, action_type, initiator_fighter_id, target_fighter_id, "
            "outcome, damage_dealt, control_time_delta, momentum_shift) "
            "VALUES (1, 1, 997, 'standing', 'cross', 1, 2, 'bogus_outcome', "
            "0, 0, 0)"
        )
        conn.commit()
    except sqlite3.IntegrityError:
        invalid_outcome_rejected = True
        conn.rollback()
    results.append((
        "A.6 INSERT outcome='bogus_outcome' fails (CHECK rejects unknown values)",
        invalid_outcome_rejected,
        f"rejected={invalid_outcome_rejected}",
    ))

    # A.7 The 5 B1 outcomes are still accepted (backward compat —
    # the CHECK is a SUPERSET of the B1 CHECK, not a replacement).
    # D13: use deterministic beat_numbers (800+i) instead of
    # `900 + hash(outcome) % 90` — the hash-based approach was flaky
    # because (a) Python's hash() is randomized per process for
    # strings, and (b) two outcomes could collide on the same
    # beat_number, hitting the UNIQUE(fight_id,round_number,beat_number)
    # constraint instead of the CHECK constraint. The deterministic
    # approach uses beat_numbers 800-804, which don't collide with
    # the 997-999 range used by A.4-A.6.
    b1_outcomes_ok = True
    for i, outcome in enumerate(("landed", "missed", "blocked", "defended", "reversed")):
        try:
            conn.execute(
                "INSERT INTO fight_beats (fight_id, round_number, beat_number, "
                "phase, action_type, initiator_fighter_id, target_fighter_id, "
                "outcome, damage_dealt, control_time_delta, momentum_shift) "
                "VALUES (1, 1, ?, 'standing', 'jab', 1, 2, ?, 5, 0, 5)",
                (800 + i, outcome),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            b1_outcomes_ok = False
            conn.rollback()
            break
    results.append((
        "A.7 B1 outcomes still accepted (CHECK is a superset, not replacement)",
        b1_outcomes_ok,
        f"all_5_b1_outcomes_ok={b1_outcomes_ok}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case B — Fatigue system
# --------------------------------------------------------------------

def case_b_fatigue():
    """Verify the fatigue system (gas costs, recovery, end-to-end effect)."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # B.1 _compute_gas_cost returns higher costs for higher-intensity
    # phases (scramble > ground > clinch/cage > standing).
    stats = {col: 50 for col in ALL_ATTR_COLS + ALL_PERS_COLS}
    cost_standing = app._compute_gas_cost("standing", stats)
    cost_clinch = app._compute_gas_cost("clinch", stats)
    cost_cage = app._compute_gas_cost("cage", stats)
    cost_ground = app._compute_gas_cost("ground_top", stats)
    cost_scramble = app._compute_gas_cost("scramble", stats)
    results.append((
        "B.1 gas cost ordering: scramble > ground > clinch/cage > standing",
        cost_scramble > cost_ground > cost_clinch == cost_cage > cost_standing,
        f"standing={cost_standing:.2f}, clinch={cost_clinch:.2f}, "
        f"cage={cost_cage:.2f}, ground={cost_ground:.2f}, "
        f"scramble={cost_scramble:.2f}",
    ))

    # B.2 _compute_gas_cost returns LOWER costs for high-cardio /
    # high-fatigue_tolerance fighters (gas depletes slower).
    stats_low_cardio = {col: 50 for col in ALL_ATTR_COLS + ALL_PERS_COLS}
    stats_low_cardio["cardio"] = 30
    stats_low_cardio["fatigue_tolerance"] = 30
    stats_high_cardio = {col: 50 for col in ALL_ATTR_COLS + ALL_PERS_COLS}
    stats_high_cardio["cardio"] = 90
    stats_high_cardio["fatigue_tolerance"] = 90
    cost_low = app._compute_gas_cost("ground_top", stats_low_cardio)
    cost_high = app._compute_gas_cost("ground_top", stats_high_cardio)
    results.append((
        "B.2 high-cardio/high-fatigue_tolerance fighter has lower gas cost",
        cost_high < cost_low,
        f"cost_low_cardio={cost_low:.2f}, cost_high_cardio={cost_high:.2f}",
    ))

    # B.3 _recover_gas_between_rounds adds recovery_rate * 0.3 (capped
    # at 100).
    stats_low_rec = {col: 50 for col in ALL_ATTR_COLS + ALL_PERS_COLS}
    stats_low_rec["recovery_rate"] = 30
    stats_high_rec = {col: 50 for col in ALL_ATTR_COLS + ALL_PERS_COLS}
    stats_high_rec["recovery_rate"] = 90
    # From gas=50, low recovery gains 9 (30*0.3), high gains 27 (90*0.3).
    rec_low = app._recover_gas_between_rounds(50.0, stats_low_rec)
    rec_high = app._recover_gas_between_rounds(50.0, stats_high_rec)
    results.append((
        "B.3 recovery adds recovery_rate * 0.3 (high recovery > low)",
        abs(rec_low - 59.0) < 0.01 and abs(rec_high - 77.0) < 0.01,
        f"rec_low={rec_low:.2f} (expected 59.0), "
        f"rec_high={rec_high:.2f} (expected 77.0)",
    ))

    # B.4 Recovery is capped at 100 (a fighter at gas=95 with high
    # recovery doesn't go above 100).
    rec_capped = app._recover_gas_between_rounds(95.0, stats_high_rec)
    results.append((
        "B.4 recovery is capped at 100 (no 'extra energy' from recovery)",
        rec_capped == 100.0,
        f"rec_from_95={rec_capped:.2f} (expected 100.0)",
    ))

    # B.5 End-to-end: high-cardio fighter out-lands low-cardio fighter
    # increasingly in later rounds. The cardio advantage compounds
    # because the low-cardio fighter's gas depletes faster — by round 5,
    # their gas is much lower, triggering the low-gas accuracy penalty.
    # Setup uses MAX cardio contrast (100 vs 0), MAX fatigue_tolerance
    # contrast (100 vs 0), and ZERO recovery_rate (so gas accumulates
    # across rounds without being topped up). punch_power / kick_power /
    # submission_offense are zeroed on both fighters so the fight can't
    # end in a KO or submission — we need rounds 1 AND 5 to compare
    # strike shares. Both fighters have chin=100 + durability=100 so
    # the doctor-stoppage threshold (200 + 2*durability = 400) is never
    # crossed. set_all_attrs(60) leaves grit=60 + composure=60 on both,
    # which is high enough that corner stoppage (needs grit<40 AND
    # composure<40) doesn't fire; discipline=60 also rules out DQ.
    # Result: every fight goes to decision; rounds 1 AND 5 always
    # exist. By round 5, B's gas drops below the 30 threshold and B's
    # accuracy is reduced 30% — A out-lands B by a wide margin.
    set_all_attrs(conn, A_ID, 60)
    set_all_attrs(conn, B_ID, 60)
    # Max cardio + fatigue_tolerance contrast, zero recovery (gas
    # accumulates across rounds). cardio + recovery_rate live on
    # fighter_attributes; fatigue_tolerance lives on fighter_personality.
    conn.execute(
        "UPDATE fighter_attributes SET cardio=100, recovery_rate=0 "
        "WHERE fighter_id=?",
        (A_ID,),
    )
    conn.execute(
        "UPDATE fighter_attributes SET cardio=0, recovery_rate=0 "
        "WHERE fighter_id=?",
        (B_ID,),
    )
    conn.execute(
        "UPDATE fighter_personality SET fatigue_tolerance=100 "
        "WHERE fighter_id=?",
        (A_ID,),
    )
    conn.execute(
        "UPDATE fighter_personality SET fatigue_tolerance=0 "
        "WHERE fighter_id=?",
        (B_ID,),
    )
    # Zero out the KO/sub pathways so the fight survives to round 5.
    # punch_power=0 + kick_power=0 → per-strike damage = 1 (the engine's
    # min). With chin=100 + recovery_rate=0, the KO threshold is 68 —
    # 68 consecutive landed strikes would be needed to KO either
    # fighter, which is impossible in a 5-round fight.
    # submission_offense=0 → submission score is always negative (the
    # brief's formula reduces submission_offense by submission_defense*0.5
    # + flexibility*0.3 + scramble_ability*0.2), so submissions always
    # fail.
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=0, kick_power=0, "
        "submission_offense=0, chin=100, durability=100 "
        "WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    # Bump scheduled_rounds to 5 to give gas time to deplete below 30.
    conn.execute("UPDATE fights SET scheduled_rounds=5 WHERE fight_id=1")
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    round1_a_share = []
    round5_a_share = []
    for _ in range(50):
        app.resolve_next_fight(conn)
        conn.commit()
        # Get per-round strikes landed. D9: read fighter_a_id from
        # fight_rounds to map strikes to the correct fighter_id —
        # the engine's "fighter A" is determined by `ORDER BY corner`
        # in resolve_next_fight (blue corner first alphabetically, so
        # fighter_id=2 is the engine's "A" in the seeded fight). The
        # test's A_ID=1 (cardio=100) is the engine's "fighter B" —
        # reading fighter_a_strikes_landed directly gives the WRONG
        # fighter's strikes. Mapping via fighter_a_id makes the test
        # robust to corner ordering.
        for rn in range(1, 6):
            row = conn.execute(
                "SELECT fighter_a_id, fighter_b_id, "
                "fighter_a_strikes_landed, fighter_b_strikes_landed "
                "FROM fight_rounds WHERE fight_id=? AND round_number=?",
                (fight_id, rn),
            ).fetchone()
            if row is None:
                # Fight ended before this round (finish). Skip.
                continue
            fa_id, fb_id, a_str, b_str = row
            total = a_str + b_str
            if total > 0:
                # Map to the test's A_ID (cardio=100).
                test_a_str = a_str if fa_id == A_ID else b_str
                share = test_a_str / total
                if rn == 1:
                    round1_a_share.append(share)
                elif rn == 5:
                    round5_a_share.append(share)
        reset_fight(conn, fight_id)
    avg_r1 = sum(round1_a_share) / len(round1_a_share) if round1_a_share else 0
    avg_r5 = sum(round5_a_share) / len(round5_a_share) if round5_a_share else 0
    results.append((
        "B.5 high-cardio out-lands low-cardio increasingly in later rounds "
        "(round 5 share > round 1 share)",
        avg_r5 > avg_r1,
        f"avg_round1_A_share={avg_r1:.3f}, avg_round5_A_share={avg_r5:.3f}",
    ))

    # B.6 Direct verification: fight_rounds.fighter_a/b_gas_remaining
    # columns are populated by resolve_round and A's gas (high cardio +
    # fatigue_tolerance) is HIGHER than B's gas (low cardio + low
    # fatigue_tolerance) at the end of each round. This is the most
    # direct end-to-end test of the fatigue system: it proves gas
    # depletes per-beat per the brief's formula and that the per-fighter
    # difference is observable in the DB.
    set_all_attrs(conn, A_ID, 60)
    set_all_attrs(conn, B_ID, 60)
    conn.execute(
        "UPDATE fighter_attributes SET cardio=100, recovery_rate=0 "
        "WHERE fighter_id=?",
        (A_ID,),
    )
    conn.execute(
        "UPDATE fighter_attributes SET cardio=0, recovery_rate=0 "
        "WHERE fighter_id=?",
        (B_ID,),
    )
    conn.execute(
        "UPDATE fighter_personality SET fatigue_tolerance=100 "
        "WHERE fighter_id=?",
        (A_ID,),
    )
    conn.execute(
        "UPDATE fighter_personality SET fatigue_tolerance=0 "
        "WHERE fighter_id=?",
        (B_ID,),
    )
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=0, kick_power=0, "
        "submission_offense=0, chin=100, durability=100 "
        "WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    conn.commit()
    random.seed(RANDOM_SEED)
    a_gas_higher_count = 0
    gas_depletes_count = 0
    sample_count = 0
    for _ in range(20):
        app.resolve_next_fight(conn)
        conn.commit()
        # D9: read fighter_a_id from fight_rounds to map gas to the
        # correct fighter_id (see B.5 comment for the corner-ordering
        # issue). The test's A_ID=1 (cardio=100) is the engine's
        # "fighter B" in the seeded fight — reading
        # fighter_a_gas_remaining directly gives the WRONG fighter's
        # gas. Mapping via fighter_a_id makes the test robust.
        rows = conn.execute(
            "SELECT round_number, fighter_a_id, "
            "fighter_a_gas_remaining, fighter_b_gas_remaining "
            "FROM fight_rounds WHERE fight_id=? ORDER BY round_number",
            (fight_id,),
        ).fetchall()
        if len(rows) >= 2:
            sample_count += 1
            r1 = rows[0]
            rN = rows[-1]
            # Map engine's A/B gas to test's A/B gas based on fighter_a_id.
            r1_fa_id = r1[1]
            if r1_fa_id == A_ID:
                r1_a_gas, r1_b_gas = r1[2], r1[3]
            else:
                r1_a_gas, r1_b_gas = r1[3], r1[2]
            rN_fa_id = rN[1]
            if rN_fa_id == A_ID:
                rN_a_gas = rN[2]
            else:
                rN_a_gas = rN[3]
            if r1_a_gas is not None and r1_b_gas is not None:
                if r1_a_gas > r1_b_gas:
                    a_gas_higher_count += 1
            if (rN_a_gas is not None and r1_a_gas is not None
                    and rN_a_gas < r1_a_gas):
                gas_depletes_count += 1
        reset_fight(conn, fight_id)
    results.append((
        "B.6 fight_rounds.gas_remaining columns populated; A's gas > B's gas "
        "in round 1 (high-cardio A depletes slower)",
        a_gas_higher_count > sample_count * 0.8,
        f"a_gas_higher_in_round_1={a_gas_higher_count}/{sample_count}",
    ))
    results.append((
        "B.7 A's gas depletes across rounds (last round gas < round 1 gas)",
        gas_depletes_count > sample_count * 0.8,
        f"gas_depleted_across_rounds={gas_depletes_count}/{sample_count}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case C — Momentum system
# --------------------------------------------------------------------

def case_c_momentum():
    """Verify the momentum system (modifier application, shift values)."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # C.1 _compute_beat_scores applies the momentum_advantage modifier
    # (positive advantage boosts attack). Set up a deterministic scenario:
    # same stats, no noise (we can't disable noise, but with 100 samples
    # the average should clearly show the modifier).
    stats = {col: 50 for col in ALL_ATTR_COLS + ALL_PERS_COLS}
    random.seed(RANDOM_SEED)
    attack_no_mom = []
    attack_pos_mom = []
    for _ in range(200):
        a_no, _ = app._compute_beat_scores(
            "standing", stats, stats, momentum_advantage=0.0
        )
        a_pos, _ = app._compute_beat_scores(
            "standing", stats, stats, momentum_advantage=0.3
        )
        attack_no_mom.append(a_no)
        attack_pos_mom.append(a_pos)
    avg_no = sum(attack_no_mom) / len(attack_no_mom)
    avg_pos = sum(attack_pos_mom) / len(attack_pos_mom)
    results.append((
        "C.1 positive momentum_advantage boosts attack score (+30% expected)",
        avg_pos > avg_no * 1.15,  # +30% modifier → ~1.3x, allow noise
        f"avg_no_mom={avg_no:.2f}, avg_pos_mom={avg_pos:.2f} "
        f"(ratio={avg_pos/avg_no:.3f})",
    ))

    # C.2 Negative momentum_advantage reduces attack (the modifier is
    # symmetric — defender's momentum leads to attacker's penalty).
    random.seed(RANDOM_SEED)
    attack_neg_mom = []
    for _ in range(200):
        a_neg, _ = app._compute_beat_scores(
            "standing", stats, stats, momentum_advantage=-0.3
        )
        attack_neg_mom.append(a_neg)
    avg_neg = sum(attack_neg_mom) / len(attack_neg_mom)
    results.append((
        "C.2 negative momentum_advantage reduces attack score (-30% expected)",
        avg_neg < avg_no * 0.85,
        f"avg_no_mom={avg_no:.2f}, avg_neg_mom={avg_neg:.2f} "
        f"(ratio={avg_neg/avg_no:.3f})",
    ))

    # C.3 Knockdown beats get momentum_shift = +80, near_finish +60.
    # End-to-end: an all-90 vs all-30 fight produces knockdown beats,
    # and at least one has momentum_shift = 80.
    set_all_attrs(conn, A_ID, 90)
    set_all_attrs(conn, B_ID, 30)
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    found_kd_80 = False
    found_nf_60 = False
    found_big_takedown_30 = False
    for _ in range(20):
        app.resolve_next_fight(conn)
        conn.commit()
        # Look for KD beats with momentum_shift = 80.
        kd_beats = conn.execute(
            "SELECT momentum_shift FROM fight_beats WHERE fight_id=? "
            "AND outcome='knockdown'",
            (fight_id,),
        ).fetchall()
        for (ms,) in kd_beats:
            if ms == 80:
                found_kd_80 = True
                break
        # Look for near_finish beats with momentum_shift = 60.
        nf_beats = conn.execute(
            "SELECT momentum_shift FROM fight_beats WHERE fight_id=? "
            "AND outcome='near_finish'",
            (fight_id,),
        ).fetchall()
        for (ms,) in nf_beats:
            if ms == 60:
                found_nf_60 = True
                break
        # Look for big takedowns. The engine's _BIG_TAKEDOWN_MOMENTUM_THRESHOLD
        # is 3 — a takedown_attempt that lands with control_time_delta >= 3
        # gets momentum_shift = max(momentum, 30). control_time_delta is
        # randint(1, 5) for non-standing phases, so control >= 3 happens on
        # roughly 60% of landed takedowns in clinch/cage. (Standing-
        # initiated takedowns have control_time_delta = 0 because the
        # standing phase doesn't accrue control time.)
        big_td = conn.execute(
            "SELECT momentum_shift, control_time_delta FROM fight_beats "
            "WHERE fight_id=? AND action_type='takedown_attempt' "
            "AND outcome='landed' AND control_time_delta >= 3",
            (fight_id,),
        ).fetchall()
        for ms, ctrl in big_td:
            if ms >= 30:
                found_big_takedown_30 = True
                break
        reset_fight(conn, fight_id)
    results.append((
        "C.3 knockdown beats have momentum_shift = 80",
        found_kd_80,
        f"found_kd_with_ms_80={found_kd_80}",
    ))
    results.append((
        "C.4 near_finish beats have momentum_shift = 60",
        found_nf_60,
        f"found_nf_with_ms_60={found_nf_60}",
    ))
    # Big takedown (control_time_delta >= 3) is the engine's
    # _BIG_TAKEDOWN_MOMENTUM_THRESHOLD. With control_time = randint(1, 5)
    # for non-standing phases, control >= 3 happens on ~60% of landed
    # clinch/cage takedowns — should be observable in 20 sims of an
    # all-90 vs all-30 fight.
    results.append((
        "C.5 big takedowns (control>=3) have momentum_shift >= 30",
        found_big_takedown_30,
        f"found_big_td_with_ms_30={found_big_takedown_30}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case D — Mid-round KO/TKO
# --------------------------------------------------------------------

def case_d_ko_tko():
    """Verify the KO/TKO finish system."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # D.1 _ko_threshold returns higher values for high-chin fighters
    # (hard to KO) and lower for low-chin (easy to KO).
    stats_high_chin = {"chin": 90, "recovery_rate": 90, "grit": 90, "composure": 90}
    stats_low_chin = {"chin": 30, "recovery_rate": 30, "grit": 30, "composure": 30}
    thresh_high = app._ko_threshold(stats_high_chin)
    thresh_low = app._ko_threshold(stats_low_chin)
    results.append((
        "D.1 KO threshold: high-chin fighter > low-chin fighter (hard to KO)",
        thresh_high > thresh_low,
        f"high_chin={thresh_high:.2f}, low_chin={thresh_low:.2f}",
    ))

    # D.2 _ko_finish_probability scales with killer_instinct.
    prob_low_ki = app._ko_finish_probability({"killer_instinct": 0})
    prob_mid_ki = app._ko_finish_probability({"killer_instinct": 50})
    prob_high_ki = app._ko_finish_probability({"killer_instinct": 100})
    results.append((
        "D.2 KO finish probability scales with killer_instinct (0 < 50 < 100)",
        prob_low_ki < prob_mid_ki < prob_high_ki,
        f"KI=0:{prob_low_ki:.2f}, KI=50:{prob_mid_ki:.2f}, KI=100:{prob_high_ki:.2f}",
    ))

    # D.3 End-to-end: all-90 vs all-30 produces KO/TKO finishes.
    set_all_attrs(conn, A_ID, 90)
    set_all_attrs(conn, B_ID, 30)
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies = resolve_n_sims(conn, fight_id, N_SIMS, A_ID, B_ID)
    ko_count = tallies["result_types"].get("ko_tko", 0)
    results.append((
        f"D.3 all-90 vs all-30 produces KO/TKO finishes (some > 0)",
        ko_count > 0,
        f"ko_tko_count={ko_count}/{N_SIMS}",
    ))

    # D.4 Knockdown beats are recorded with outcome='knockdown'.
    results.append((
        "D.4 knockdown beats recorded (outcome='knockdown')",
        tallies["knockdowns"] > 0,
        f"total_knockdown_beats={tallies['knockdowns']}",
    ))

    # D.5 All-90 wins >= 80% (the favorite dominates).
    wins_a = tallies["wins_for_a"]
    results.append((
        f"D.5 all-90 wins >= {MIN_WINS_FOR_A}/{N_SIMS}",
        wins_a >= MIN_WINS_FOR_A,
        f"wins_for_a={wins_a}/{N_SIMS}",
    ))

    # D.6 KO/TKO fights end mid-round (finish_round <= scheduled_rounds,
    # and at least one finishes before the final round).
    finish_rounds = [r for r in tallies["finish_rounds"] if r > 0]
    sched_rounds = conn.execute(
        "SELECT scheduled_rounds FROM fights WHERE fight_id=?", (fight_id,)
    ).fetchone()[0]
    early_finishes = [r for r in finish_rounds if r < sched_rounds]
    results.append((
        "D.6 KO/TKO fights end before scheduled_rounds (mid-round finish)",
        len(early_finishes) > 0,
        f"early_finishes={len(early_finishes)}/{len(finish_rounds)} "
        f"(scheduled_rounds={sched_rounds})",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case E — Submission
# --------------------------------------------------------------------

def case_e_submission():
    """Verify the submission finish system."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # E.1 _submission_score returns positive for high submission_offense
    # vs low defense (submission should succeed).
    high_off = {"submission_offense": 90, "composure": 90}
    low_def = {"submission_defense": 30, "flexibility": 30, "scramble_ability": 30}
    score_weak_def = app._submission_score(high_off, low_def)
    results.append((
        "E.1 submission score vs weak defense is positive (submission succeeds)",
        score_weak_def > 0,
        f"score_vs_weak_def={score_weak_def:.2f}",
    ))

    # E.2 _submission_score returns negative or near-zero for low
    # submission_offense vs high defense (submission should fail).
    low_off = {"submission_offense": 30, "composure": 30}
    high_def = {"submission_defense": 90, "flexibility": 90, "scramble_ability": 90}
    score_strong_def = app._submission_score(low_off, high_def)
    results.append((
        "E.2 submission score vs strong defense is low/negative (submission fails)",
        score_strong_def < score_weak_def,
        f"score_vs_strong_def={score_strong_def:.2f}",
    ))

    # E.3 End-to-end: a high-submission_offense fighter produces some
    # submission finishes. Setup: A is a submission specialist, B is
    # weak at submission defense.
    set_all_attrs(conn, A_ID, 70)
    set_all_attrs(conn, B_ID, 50)
    # Make A a submission specialist.
    set_attrs_explicit(conn, A_ID, {
        "submission_offense": 95, "takedown_offense": 90, "top_control": 90,
        "bottom_game": 90, "flexibility": 80, "clinch_offense": 80,
    }, {
        "killer_instinct": 80, "composure": 80, "aggression": 70,
    })
    # Make B weak at submission defense.
    set_attrs_explicit(conn, B_ID, {
        "submission_defense": 20, "flexibility": 20, "scramble_ability": 20,
        "takedown_defense": 30, "bottom_game": 30,
        "chin": 90, "durability": 90, "recovery_rate": 90,  # survive to be submitted
    })
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies = resolve_n_sims(conn, fight_id, 50, A_ID, B_ID)
    sub_count = tallies["result_types"].get("submission", 0)
    results.append((
        f"E.3 submission specialist produces submission finishes (> 0 of 50)",
        sub_count > 0,
        f"submission_count={sub_count}/50, all_results={dict(tallies['result_types'])}",
    ))

    # E.4 Submission finishes record a near_finish beat (the tapping moment).
    results.append((
        "E.4 near_finish beats recorded",
        tallies["near_finishes"] > 0,
        f"total_near_finish_beats={tallies['near_finishes']}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case F — Doctor stoppage
# --------------------------------------------------------------------

def case_f_doctor_stoppage():
    """Verify the doctor stoppage system (between rounds)."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # F.1 _doctor_stoppage_threshold returns 200 + durability * 2.
    thresh_low = app._doctor_stoppage_threshold({"durability": 30})
    thresh_high = app._doctor_stoppage_threshold({"durability": 90})
    results.append((
        "F.1 doctor threshold = 200 + durability*2 (high durability > low)",
        abs(thresh_low - 260) < 0.01 and abs(thresh_high - 380) < 0.01,
        f"low_durability={thresh_low:.2f} (expected 260), "
        f"high_durability={thresh_high:.2f} (expected 380)",
    ))

    # F.2 End-to-end: a fight where one fighter takes massive damage
    # produces a doctor stoppage. Setup: A is a volume striker (high
    # cardio, moderate punch_power, low killer_instinct so KOs don't
    # fire), B has high chin (survives KO attempts) + low durability
    # (low doctor threshold) + high grit/composure (no corner stoppage).
    # B's high chin means A's strikes don't cross the KO threshold
    # easily, so the fight goes multiple rounds. A's volume accumulates
    # damage until the doctor threshold (200 + B.durability*2 = 220)
    # is crossed between rounds.
    set_all_attrs(conn, A_ID, 60)
    set_all_attrs(conn, B_ID, 30)
    # A: volume striker (high cardio, moderate power, low killer_instinct).
    set_attrs_explicit(conn, A_ID, {
        "punch_power": 60, "punch_accuracy": 70, "kick_power": 50,
        "kick_accuracy": 60, "cardio": 90, "fight_iq": 70,
        "head_movement": 60, "footwork": 60, "speed_explosiveness": 60,
        "chin": 100, "durability": 100, "recovery_rate": 100,
    }, {
        "aggression": 70, "killer_instinct": 10, "composure": 70,
        "grit": 70, "discipline": 70, "fatigue_tolerance": 70,
    })
    # B: high chin (survive KOs), low durability (low doctor threshold),
    # high grit/composure (avoid corner stoppage).
    set_attrs_explicit(conn, B_ID, {
        "chin": 100, "durability": 10, "recovery_rate": 100,
    }, {
        "grit": 100, "composure": 100, "discipline": 50,
    })
    # Bump scheduled_rounds to 5 to give doctor more chances.
    conn.execute("UPDATE fights SET scheduled_rounds=5 WHERE fight_id=1")
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies = resolve_n_sims(conn, fight_id, 50, A_ID, B_ID)
    doc_count = tallies["result_types"].get("doctor_stoppage", 0)
    results.append((
        f"F.2 doctor stoppage occurs when fighter takes massive damage (> 0 of 50)",
        doc_count > 0,
        f"doctor_stoppage_count={doc_count}/50, "
        f"all_results={dict(tallies['result_types'])}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case G — Corner stoppage
# --------------------------------------------------------------------

def case_g_corner_stoppage():
    """Verify the corner stoppage system (between rounds)."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # G.1 _check_corner_stoppage returns False for < 3 consecutive losses.
    stats_low = {"grit": 10, "composure": 10}
    # Run multiple times to account for the 20% randomness.
    any_true_for_2 = False
    for _ in range(20):
        if app._check_corner_stoppage(2, stats_low):
            any_true_for_2 = True
            break
    results.append((
        "G.1 corner stoppage returns False for 2 consecutive losses (< 3)",
        not any_true_for_2,
        f"any_true_for_2_losses={any_true_for_2}",
    ))

    # G.2 _check_corner_stoppage returns False for high grit/composure
    # even with 3+ consecutive losses.
    stats_high = {"grit": 70, "composure": 70}
    any_true_for_high_grit = False
    for _ in range(20):
        if app._check_corner_stoppage(5, stats_high):
            any_true_for_high_grit = True
            break
    results.append((
        "G.2 corner stoppage returns False for high grit/composure (>= 40)",
        not any_true_for_high_grit,
        f"any_true_for_high_grit={any_true_for_high_grit}",
    ))

    # G.3 End-to-end: a durable loser with low grit/composure who loses
    # 3+ rounds produces some corner stoppages. Setup: A is a wrestler
    # (wins rounds via control, low striking power), B is durable (high
    # chin/durability to survive) but low grit/composure (corner throws
    # in the towel after 3 rounds).
    set_all_attrs(conn, A_ID, 50)
    set_all_attrs(conn, B_ID, 30)
    # A: wrestler (wins rounds via takedowns + control, low striking power).
    set_attrs_explicit(conn, A_ID, {
        "punch_power": 20, "kick_power": 20, "punch_accuracy": 30,
        "takedown_offense": 90, "takedown_defense": 80, "top_control": 90,
        "clinch_offense": 80, "clinch_defense": 80, "cage_wrestling": 90,
        "chin": 70, "recovery_rate": 70, "durability": 80, "strength": 80,
        "cardio": 80, "fight_iq": 80,
    }, {
        "aggression": 70, "composure": 70, "discipline": 80,
        "killer_instinct": 30, "grit": 70, "focus": 70,
    })
    # B: durable but low grit/composure (corner will throw in towel).
    set_attrs_explicit(conn, B_ID, {
        "punch_power": 20, "kick_power": 20, "punch_accuracy": 20,
        "takedown_defense": 20, "chin": 100, "durability": 100,
        "recovery_rate": 100, "bottom_game": 20, "submission_defense": 80,
        "flexibility": 80, "cardio": 80, "fight_iq": 20,
    }, {
        "aggression": 20, "composure": 10, "grit": 10, "discipline": 20,
        "killer_instinct": 10, "focus": 10, "fatigue_tolerance": 80,
    })
    # Bump scheduled_rounds to 5 to give corner more chances.
    conn.execute("UPDATE fights SET scheduled_rounds=5 WHERE fight_id=1")
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies = resolve_n_sims(conn, fight_id, 30, A_ID, B_ID)
    corner_count = tallies["result_types"].get("corner_stoppage", 0)
    results.append((
        f"G.3 corner stoppage occurs for durable low-grit loser (> 0 of 30)",
        corner_count > 0,
        f"corner_stoppage_count={corner_count}/30, "
        f"all_results={dict(tallies['result_types'])}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case H — DQ
# --------------------------------------------------------------------

def case_h_dq():
    """Verify the DQ system (low discipline + illegal strike, rare)."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # H.1 _check_dq returns False for high-discipline fighters.
    stats_high_disc = {"discipline": 50}
    any_true_for_high_disc = False
    for _ in range(50):
        if app._check_dq(stats_high_disc, "cross", "landed"):
            any_true_for_high_disc = True
            break
    results.append((
        "H.1 DQ returns False for discipline >= 20 (high-discipline fighter)",
        not any_true_for_high_disc,
        f"any_true_for_high_disc={any_true_for_high_disc}",
    ))

    # H.2 _check_dq returns False for non-landed strikes (illegal strike
    # requires the strike to land).
    stats_low_disc = {"discipline": 10}
    any_true_for_missed = False
    for _ in range(50):
        if app._check_dq(stats_low_disc, "cross", "missed"):
            any_true_for_missed = True
            break
    results.append((
        "H.2 DQ returns False for non-landed strikes (illegal strike must land)",
        not any_true_for_missed,
        f"any_true_for_missed={any_true_for_missed}",
    ))

    # H.3 _check_dq returns True SOMETIMES for low-discipline fighters
    # who land strikes (1% per beat — should fire in 100+ trials).
    any_true_for_low_disc = False
    for _ in range(500):
        if app._check_dq(stats_low_disc, "cross", "landed"):
            any_true_for_low_disc = True
            break
    results.append((
        "H.3 DQ fires for low-discipline fighter landing strikes (1% per beat)",
        any_true_for_low_disc,
        f"any_true_for_low_disc={any_true_for_low_disc} "
        f"(expected True with 500 trials at 1%)",
    ))

    # H.4 End-to-end: a low-discipline fighter produces some DQs (rare).
    # Setup: A is low-discipline (discipline=10), B is durable.
    set_all_attrs(conn, A_ID, 70)
    set_all_attrs(conn, B_ID, 50)
    set_attrs_explicit(conn, A_ID, {
        "punch_power": 80, "punch_accuracy": 80, "chin": 80,
        "durability": 80, "recovery_rate": 80,
    }, {
        "discipline": 5, "aggression": 90, "composure": 30,  # low discipline + high aggression
        "killer_instinct": 80, "grit": 80,
    })
    # B: durable enough to survive to the DQ.
    set_attrs_explicit(conn, B_ID, {
        "chin": 100, "durability": 100, "recovery_rate": 100,
    }, {
        "grit": 80, "composure": 80,  # avoid corner stoppage
    })
    conn.execute("UPDATE fights SET scheduled_rounds=5 WHERE fight_id=1")
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies = resolve_n_sims(conn, fight_id, 100, A_ID, B_ID)
    dq_count = tallies["result_types"].get("dq", 0)
    # DQ is RARE (1% per beat). With ~20 beats/round * 5 rounds = 100
    # beats per fight, and 100 sims, we expect ~100 DQs in theory —
    # but the discipline check is only on landed STRIKES by the
    # low-discipline fighter, which is fewer. Verify at least 1 DQ
    # occurred in 100 sims.
    results.append((
        f"H.4 DQ occurs for low-discipline fighter (>= 1 of 100)",
        dq_count >= 1,
        f"dq_count={dq_count}/100, all_results={dict(tallies['result_types'])}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case I — Fight importance
# --------------------------------------------------------------------

def case_i_importance():
    """Verify fight importance computation."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # I.1 _compute_fight_importance returns high values for main event
    # + title fight + high marketability.
    high_imp = app._compute_fight_importance("main_event", 1, 90, 90)
    results.append((
        f"I.1 main_event + title + high marketability → high importance (> 70)",
        high_imp > 70,
        f"high_importance={high_imp:.2f}",
    ))

    # I.2 _compute_fight_importance returns low values for opener +
    # non-title + low marketability.
    low_imp = app._compute_fight_importance("opener", 0, 20, 20)
    results.append((
        f"I.2 opener + non-title + low marketability → low importance (< 30)",
        low_imp < 30,
        f"low_importance={low_imp:.2f}",
    ))

    # I.3 Card slot weights: main_event > co_main > featured_prelim >
    # prelim > opener (with title=0 and marketability=50 held constant).
    main_imp = app._compute_fight_importance("main_event", 0, 50, 50)
    co_imp = app._compute_fight_importance("co_main", 0, 50, 50)
    fp_imp = app._compute_fight_importance("featured_prelim", 0, 50, 50)
    prelim_imp = app._compute_fight_importance("prelim", 0, 50, 50)
    opener_imp = app._compute_fight_importance("opener", 0, 50, 50)
    results.append((
        "I.3 card_slot weights: main > co_main > featured_prelim > prelim > opener",
        main_imp > co_imp > fp_imp > prelim_imp > opener_imp,
        f"main={main_imp:.2f}, co_main={co_imp:.2f}, "
        f"featured_prelim={fp_imp:.2f}, prelim={prelim_imp:.2f}, "
        f"opener={opener_imp:.2f}",
    ))

    # I.4 Title fight adds significant importance (same card_slot +
    # marketability, title_fight=1 vs 0).
    title_imp = app._compute_fight_importance("main_event", 1, 50, 50)
    no_title_imp = app._compute_fight_importance("main_event", 0, 50, 50)
    results.append((
        f"I.4 title fight adds importance (title > non-title at same slot)",
        title_imp > no_title_imp,
        f"title={title_imp:.2f}, non_title={no_title_imp:.2f} "
        f"(delta={title_imp - no_title_imp:.2f}, expected ~30)",
    ))

    # I.5 Higher marketability adds importance.
    high_mkt = app._compute_fight_importance("main_event", 0, 90, 90)
    low_mkt = app._compute_fight_importance("main_event", 0, 30, 30)
    results.append((
        f"I.5 higher marketability adds importance (90 > 30)",
        high_mkt > low_mkt,
        f"high_mkt={high_mkt:.2f}, low_mkt={low_mkt:.2f} "
        f"(delta={high_mkt - low_mkt:.2f})",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case J — Pressure modifiers
# --------------------------------------------------------------------

def case_j_pressure():
    """Verify pressure response + modifier computation."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # J.1 _compute_pressure_response returns the weighted sum:
    # clutch_factor*0.35 + composure*0.25 + consistency*0.20 +
    # focus*0.10 + grit*0.10.
    stats_all_90 = {
        "clutch_factor": 90, "composure": 90, "consistency": 90,
        "focus": 90, "grit": 90,
    }
    response_90 = app._compute_pressure_response(stats_all_90)
    results.append((
        f"J.1 pressure_response for all-90 = 90.0 (weighted sum)",
        abs(response_90 - 90.0) < 0.01,
        f"response_90={response_90:.2f} (expected 90.0)",
    ))

    # J.2 _compute_pressure_response returns 30 for all-30.
    stats_all_30 = {
        "clutch_factor": 30, "composure": 30, "consistency": 30,
        "focus": 30, "grit": 30,
    }
    response_30 = app._compute_pressure_response(stats_all_30)
    results.append((
        f"J.2 pressure_response for all-30 = 30.0",
        abs(response_30 - 30.0) < 0.01,
        f"response_30={response_30:.2f} (expected 30.0)",
    ))

    # J.3 _compute_pressure_modifier returns +5% (0.05) for response >= 70
    # in high-importance fights (> 60).
    mod_high = app._compute_pressure_modifier(90, 90)
    results.append((
        f"J.3 modifier for response=90 in high-importance fight = +5%",
        abs(mod_high - 0.05) < 0.001,
        f"mod_high={mod_high:.4f} (expected 0.05)",
    ))

    # J.4 _compute_pressure_modifier returns -10% (-0.10) for response <= 30
    # in high-importance fights.
    mod_low = app._compute_pressure_modifier(90, 30)
    results.append((
        f"J.4 modifier for response=30 in high-importance fight = -10%",
        abs(mod_low - (-0.10)) < 0.001,
        f"mod_low={mod_low:.4f} (expected -0.10)",
    ))

    # J.5 _compute_pressure_modifier returns 0 for mid-range response
    # (30 < response < 70) in high-importance fights.
    mod_mid = app._compute_pressure_modifier(90, 50)
    results.append((
        f"J.5 modifier for response=50 in high-importance fight = 0 (baseline)",
        abs(mod_mid - 0.0) < 0.001,
        f"mod_mid={mod_mid:.4f} (expected 0.0)",
    ))

    # J.6 _compute_pressure_modifier returns 0 in LOW-importance fights
    # regardless of response (no pressure to respond to).
    mod_low_imp_high_resp = app._compute_pressure_modifier(50, 90)
    mod_low_imp_low_resp = app._compute_pressure_modifier(50, 30)
    results.append((
        f"J.6 modifier in low-importance fight = 0 (no pressure to respond to)",
        mod_low_imp_high_resp == 0.0 and mod_low_imp_low_resp == 0.0,
        f"low_imp_high_resp={mod_low_imp_high_resp:.4f}, "
        f"low_imp_low_resp={mod_low_imp_low_resp:.4f}",
    ))

    # J.7 End-to-end: high-clutch fighter in a title fight gets +5% to
    # beat scores; low-clutch gets -10%. Verified indirectly: a high-
    # clutch all-50 fighter wins more often than a low-clutch all-50
    # fighter in a high-importance fight (title main event).
    # Setup 1: both fighters all-50, A has clutch_factor=90.
    set_all_attrs(conn, A_ID, 50)
    set_all_attrs(conn, B_ID, 50)
    set_attrs_explicit(conn, A_ID, meta_dict={
        "clutch_factor": 90, "consistency": 90, "marketability": 50,
    })
    set_attrs_explicit(conn, B_ID, meta_dict={
        "clutch_factor": 50, "consistency": 50, "marketability": 50,
    })
    # Make it a title main event (high importance).
    conn.execute(
        "UPDATE fights SET card_slot='main_event', is_title_fight=1 "
        "WHERE fight_id=1"
    )
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies_high_clutch = resolve_n_sims(conn, fight_id, 50, A_ID, B_ID)
    wins_a_high_clutch = tallies_high_clutch["wins_for_a"]

    # Setup 2: A has clutch_factor=30 (bottler).
    reset_fight(conn, fight_id)
    set_all_attrs(conn, A_ID, 50)
    set_all_attrs(conn, B_ID, 50)
    set_attrs_explicit(conn, A_ID, meta_dict={
        "clutch_factor": 30, "consistency": 30, "marketability": 50,
    })
    set_attrs_explicit(conn, B_ID, meta_dict={
        "clutch_factor": 50, "consistency": 50, "marketability": 50,
    })
    conn.commit()
    random.seed(RANDOM_SEED)
    tallies_low_clutch = resolve_n_sims(conn, fight_id, 50, A_ID, B_ID)
    wins_a_low_clutch = tallies_low_clutch["wins_for_a"]

    results.append((
        f"J.7 high-clutch fighter wins more than low-clutch fighter in "
        f"high-importance fight",
        wins_a_high_clutch > wins_a_low_clutch,
        f"wins_high_clutch={wins_a_high_clutch}/50, "
        f"wins_low_clutch={wins_a_low_clutch}/50",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case K — Commentary beat selection
# --------------------------------------------------------------------

def case_k_commentary():
    """Verify commentary beat selection picks the right beats."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # K.1 _select_commentary_beats returns 3-6 beats for low-importance
    # fights (importance < 40). Use a BALANCED matchup (all-50 vs all-50
    # + high durability) so the fight goes the distance and produces
    # 40+ beats — the selector can pick from a large pool. (An all-90
    # vs all-30 fight ends in round 1 with a fast KO, producing only
    # 3-8 beats total — not enough to test the 3-6 selection range.)
    set_all_attrs(conn, A_ID, 50)
    set_all_attrs(conn, B_ID, 50)
    # Make both durable so the fight goes the distance (3 rounds = 60+ beats).
    conn.execute(
        "UPDATE fighter_attributes SET chin=100, durability=100, "
        "recovery_rate=100 WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    conn.execute(
        "UPDATE fighter_personality SET grit=100, composure=100, "
        "killer_instinct=10 WHERE fighter_id IN (?, ?)",
        (A_ID, B_ID),
    )
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    app.resolve_next_fight(conn)
    conn.commit()
    # Importance for opener + non-title + 50/50 marketability:
    # 20*0.4 + 0*0.3 + 0*0.15 + 50*0.15 = 8 + 7.5 = 15.5 → quick (3-6 beats).
    selected_quick = app._select_commentary_beats(conn, fight_id, importance=17.0)
    n_quick = len(selected_quick)
    results.append((
        f"K.1 low-importance fight → 3-6 beats selected (got {n_quick})",
        3 <= n_quick <= 6,
        f"n_quick={n_quick}",
    ))
    reset_fight(conn, fight_id)

    # K.2 _select_commentary_beats returns 6-10 beats for standard-
    # importance fights (40 <= importance < 70).
    # Run another sim (same balanced setup), select with standard importance.
    random.seed(RANDOM_SEED + 1)
    app.resolve_next_fight(conn)
    conn.commit()
    selected_std = app._select_commentary_beats(conn, fight_id, importance=55.0)
    n_std = len(selected_std)
    results.append((
        f"K.2 standard-importance fight → 6-10 beats selected (got {n_std})",
        6 <= n_std <= 10,
        f"n_std={n_std}",
    ))
    reset_fight(conn, fight_id)

    # K.3 _select_commentary_beats returns 10-14 beats for high-importance
    # fights (importance >= 70).
    random.seed(RANDOM_SEED + 2)
    app.resolve_next_fight(conn)
    conn.commit()
    selected_ext = app._select_commentary_beats(conn, fight_id, importance=85.0)
    n_ext = len(selected_ext)
    results.append((
        f"K.3 high-importance fight → 10-14 beats selected (got {n_ext})",
        10 <= n_ext <= 14,
        f"n_ext={n_ext}",
    ))
    reset_fight(conn, fight_id)

    # K.4 Knockdown beats are always selected (priority 1000).
    # Switch to all-90 vs all-30 to produce knockdowns. D10: with the
    # D6 ko_prob tuning (0.1+KI*0.002, range 0.1-0.3), a single sim
    # has ~73% chance of producing a KO — not deterministic enough
    # for a single-seed test. Loop up to 10 sims until we find one
    # with knockdown beats, then verify the commentary selector picks
    # them. With 73% per sim, P(no KO in 10 sims) ≈ 0.27^10 < 0.002%.
    set_all_attrs(conn, A_ID, 90)
    set_all_attrs(conn, B_ID, 30)
    conn.commit()
    random.seed(RANDOM_SEED + 3)
    kd_beats = []
    for _ in range(10):
        app.resolve_next_fight(conn)
        conn.commit()
        kd_beats = conn.execute(
            "SELECT fight_beat_id FROM fight_beats WHERE fight_id=? "
            "AND outcome='knockdown'",
            (fight_id,),
        ).fetchall()
        if kd_beats:
            break
        reset_fight(conn, fight_id)
    if kd_beats:
        # Use max_beats=2 to force only the top 2 beats — knockdowns
        # should be selected preferentially.
        selected_top2 = app._select_commentary_beats(
            conn, fight_id, importance=85.0, max_beats=2
        )
        selected_ids = {b[0] for b in selected_top2}
        kd_ids = {b[0] for b in kd_beats}
        kd_selected = bool(selected_ids & kd_ids)
    else:
        kd_selected = False
    results.append((
        f"K.4 knockdown beats are selected (priority 1000)",
        kd_selected,
        f"knockdown_beats={len(kd_beats)}, top_2_includes_kd={kd_selected}",
    ))
    reset_fight(conn, fight_id)

    # K.5 The finishing beat is always selected when a finish occurred.
    random.seed(RANDOM_SEED + 4)
    app.resolve_next_fight(conn)
    conn.commit()
    # Get the finishing beat — it's the last beat (highest round/beat
    # for a mid-round finish).
    last_beat = conn.execute(
        "SELECT fight_beat_id, outcome FROM fight_beats WHERE fight_id=? "
        "ORDER BY round_number DESC, beat_number DESC LIMIT 1",
        (fight_id,),
    ).fetchone()
    if last_beat:
        finishing_beat_id = last_beat[0]
        selected_with_finish = app._select_commentary_beats(
            conn, fight_id, importance=85.0,
            finishing_beat_id=finishing_beat_id,
        )
        selected_ids = {b[0] for b in selected_with_finish}
        finish_selected = finishing_beat_id in selected_ids
    else:
        finish_selected = False
    results.append((
        f"K.5 finishing beat is always selected (priority 900)",
        finish_selected,
        f"finishing_beat_id={last_beat[0] if last_beat else None}, "
        f"selected={finish_selected}",
    ))
    reset_fight(conn, fight_id)

    # K.6 End-to-end: commentary_segments are written for the selected
    # beats (segment_type='highlight').
    random.seed(RANDOM_SEED + 5)
    app.resolve_next_fight(conn)
    conn.commit()
    seg_count = conn.execute(
        "SELECT COUNT(*) FROM commentary_segments WHERE fight_id=? "
        "AND segment_type='highlight'",
        (fight_id,),
    ).fetchone()[0]
    results.append((
        f"K.6 commentary_segments written for selected beats (> 0)",
        seg_count > 0,
        f"highlight_segments={seg_count}",
    ))
    reset_fight(conn, fight_id)

    # K.7 Big momentum swings (|momentum_shift| > 50) are selected.
    # Run a sim, find any beats with |momentum_shift| > 50, verify
    # they're in the selected set when max_beats forces tight selection.
    random.seed(RANDOM_SEED + 6)
    app.resolve_next_fight(conn)
    conn.commit()
    big_swing_beats = conn.execute(
        "SELECT fight_beat_id FROM fight_beats WHERE fight_id=? "
        "AND ABS(momentum_shift) > 50",
        (fight_id,),
    ).fetchall()
    if big_swing_beats:
        # Use max_beats=4 to force tight selection — knockdowns (ms=80)
        # and near-finishes (ms=60) qualify as big swings and should
        # be picked preferentially over regular beats.
        selected_tight = app._select_commentary_beats(
            conn, fight_id, importance=85.0, max_beats=4
        )
        selected_ids = {b[0] for b in selected_tight}
        swing_ids = {b[0] for b in big_swing_beats}
        swing_selected = bool(selected_ids & swing_ids)
    else:
        swing_selected = False
    results.append((
        f"K.7 big momentum swings (|ms|>50) are selected",
        swing_selected,
        f"big_swing_beats={len(big_swing_beats)}, "
        f"swing_in_top_4={swing_selected}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Case L — End-to-end fight resolution
# --------------------------------------------------------------------

def case_l_e2e():
    """Verify end-to-end fight resolution produces the expected result types."""
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    results = []

    # L.1 All-90 beats all-30 >= 80% over 100 sims.
    set_all_attrs(conn, A_ID, 90)
    set_all_attrs(conn, B_ID, 30)
    conn.commit()
    random.seed(RANDOM_SEED)
    fight_id = conn.execute(
        "SELECT fight_id FROM fights ORDER BY fight_id LIMIT 1"
    ).fetchone()[0]
    tallies = resolve_n_sims(conn, fight_id, N_SIMS, A_ID, B_ID)
    wins_a = tallies["wins_for_a"]
    results.append((
        f"L.1 all-90 beats all-30 >= {MIN_WINS_FOR_A}/{N_SIMS}",
        wins_a >= MIN_WINS_FOR_A,
        f"wins_for_a={wins_a}/{N_SIMS}",
    ))

    # L.2 All-90 vs all-30 produces some KO/TKO finishes.
    ko_count = tallies["result_types"].get("ko_tko", 0)
    results.append((
        f"L.2 all-90 vs all-30 produces some KO/TKO finishes (> 0)",
        ko_count > 0,
        f"ko_tko_count={ko_count}/{N_SIMS}",
    ))

    # L.3 result_type is one of the 9 valid values (ko_tko, submission,
    # doctor_stoppage, corner_stoppage, dq, unanimous_decision,
    # split_decision, draw, no_contest). v2.7.0 (Task 17): added
    # 'no_contest' for weight-cut-cancelled fights.
    valid_types = {
        "ko_tko", "submission", "doctor_stoppage", "corner_stoppage", "dq",
        "unanimous_decision", "split_decision", "draw", "no_contest",
    }
    observed_types = set(tallies["result_types"].keys())
    all_valid = observed_types.issubset(valid_types)
    results.append((
        f"L.3 all result_type values are valid",
        all_valid,
        f"observed={observed_types}, valid={valid_types}",
    ))

    # L.4 finish_round is the round where the finish happened (not
    # scheduled_rounds) for finishes. v2.7.0: no_contest fights have
    # finish_round=0 (the fight never started), which is valid.
    sched_rounds = conn.execute(
        "SELECT scheduled_rounds FROM fights WHERE fight_id=?", (fight_id,)
    ).fetchone()[0]
    finish_rounds = tallies["finish_rounds"]
    # For finishes, finish_round should be <= scheduled_rounds and > 0.
    # For decisions, finish_round should == scheduled_rounds.
    # For no_contest (weight cut cancellation), finish_round == 0.
    # All finish_rounds should be >= 0.
    all_positive = all(r >= 0 for r in finish_rounds if r is not None)
    all_in_range = all(0 <= r <= sched_rounds for r in finish_rounds if r is not None)
    results.append((
        f"L.4 finish_round is always >= 0 and <= scheduled_rounds (v2.7.0: 0=no_contest)",
        all_positive and all_in_range,
        f"all_positive={all_positive}, all_in_range={all_in_range}, "
        f"scheduled_rounds={sched_rounds}",
    ))

    # L.5 finish_time is a 'M:SS' string within the finishing round.
    # Verify the format with a regex.
    time_pattern = re.compile(r"^\d+:\d{2}$")
    all_valid_times = all(
        time_pattern.match(t) is not None for t in tallies["finish_times"]
    )
    results.append((
        f"L.5 finish_time matches 'M:SS' format",
        all_valid_times,
        f"sample_times={tallies['finish_times'][:5]}",
    ))

    # L.6 result_type can include each of the 5 finish types
    # (ko_tko, submission, doctor_stoppage, corner_stoppage, dq) —
    # verified individually in cases D-H. Here we verify the SET of
    # possible result_types includes at least one finish type.
    finish_types = {"ko_tko", "submission", "doctor_stoppage",
                    "corner_stoppage", "dq"}
    observed_finishes = observed_types & finish_types
    results.append((
        f"L.6 at least one finish type observed in 100 sims "
        f"(ko_tko/sub/doctor/corner/dq)",
        len(observed_finishes) > 0,
        f"observed_finishes={observed_finishes}",
    ))

    conn.close()
    return results


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK B2 BEAT ENGINE DEPTH ACCEPTANCE TEST")
    print(f"Code schema version: {EXPECTED_CODE_VERSION}")
    print(sep)
    print()

    all_results = []
    cases = [
        ("A — schema verification (version, migration, CHECK constraint)",
         case_a_schema),
        ("B — fatigue system (gas costs, recovery, end-to-end)",
         case_b_fatigue),
        ("C — momentum system (modifier, shift values)",
         case_c_momentum),
        ("D — mid-round KO/TKO (threshold, finish probability, end-to-end)",
         case_d_ko_tko),
        ("E — submission (score, end-to-end)",
         case_e_submission),
        ("F — doctor stoppage (threshold, end-to-end)",
         case_f_doctor_stoppage),
        ("G — corner stoppage (check, end-to-end)",
         case_g_corner_stoppage),
        ("H — DQ (check, end-to-end, rare)",
         case_h_dq),
        ("I — fight importance (card_slot, title, marketability)",
         case_i_importance),
        ("J — pressure modifiers (response, +5%/-10%, end-to-end)",
         case_j_pressure),
        ("K — commentary beat selection (priority, count, end-to-end)",
         case_k_commentary),
        ("L — end-to-end fight resolution (wins, finishes, format)",
         case_l_e2e),
    ]

    for case_name, case_fn in cases:
        print("-" * 80)
        print(f"Case {case_name}")
        print("-" * 80)
        try:
            results = case_fn()
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            all_results.append((case_name, "EXCEPTION", [(str(e), False, str(e))]))
            print()
            continue
        all_pass = True
        for desc, passed, detail in results:
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{status}] {desc}")
            if not passed:
                print(f"         {detail}")
        all_results.append((case_name, "PASS" if all_pass else "FAIL", results))
        print()

    # Summary.
    print(sep)
    print("SUMMARY")
    print(sep)
    total_pass = 0
    total_fail = 0
    for case_name, status, results in all_results:
        case_pass = sum(1 for _, p, _ in results if p)
        case_fail = sum(1 for _, p, _ in results if not p)
        total_pass += case_pass
        total_fail += case_fail
        status_str = "PASS" if status == "PASS" else "FAIL"
        print(f"  [{status_str}] {case_name}: {case_pass}/{case_pass + case_fail}")
    print()
    print(f"Total: {total_pass} / {total_pass + total_fail} checks passed "
          f"({total_fail} failed)")
    print(sep)
    if total_fail == 0:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
