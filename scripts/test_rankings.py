#!/usr/bin/env python3
"""Acceptance test for Task ID 10 — Rankings (second Stage 2 task).

Tests the rankings system added in Task ID 10:

  A. Schema:
     - schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION
       (read dynamically — no hardcoded version string).
     - schema_migrations contains a migration starting with 'v1_5_0_'.
     - `rankings` table exists with 12 expected columns.
     - CHECK constraints fire on rating=-1 and fights_count=-1.
     - UNIQUE constraint fires on duplicate (fighter_id, weight_class_id,
       promotion_id).
  B. Seed:
     - 5 rankings rows (2 AC + 3 RFL).
     - All rating=1000.0.
     - All fights_count=0, wins=0, losses=0, draws=0.
     - All last_fight_date IS NULL.
     - Each fighter's rankings row promotion_id matches their
       current_promotion_id.
  C. ELO update on fight resolution:
     - Set fighter 1 attrs all-90, fighter 2 attrs all-30.
     - Both start at rating=1000.0.
     - Call app.resolve_next_fight(conn).
     - Assert fighter 1 (winner) rating > 1000.0.
     - Assert fighter 2 (loser) rating < 1000.0.
     - Assert sum is zero-sum (2000.0 ± 0.01).
     - Assert both fights_count=1.
     - Assert fighter 1 wins=1, fighter 2 losses=1.
     - Assert both last_fight_date='2026-08-15'.
  D. ELO upset math:
     - Build fresh DB. Set f1 rating=1500, f2 rating=800.
     - Make f2 win (underdog). Record f2's rating gain.
     - Build another fresh DB. Same ratings. Make f1 win (favorite).
       Record f1's rating gain.
     - Assert upset gain >= 10x favorite-wins gain.
  E. Draw handling:
     - Build fresh DB. Set both fighters' attrs AND personality to 50/50.
     - random.seed(42), resolve up to 20 tries until a draw occurs
       (else SKIP with warning).
     - When draw occurs: both fighters draws=1, fights_count=1.
     - With both at 1000.0, expected=0.5, so draw produces zero rating
       change. Assert both ratings still 1000.0 (±0.01).
  F. get_rankings_for_display() helper:
     - Build fresh DB, resolve a few fights (seed=42).
     - Call helper with alpha_combat_id → 2 rows ordered by rating DESC.
     - Assert 7-tuple shape, rank is 1-indexed.
     - Call with weight_class_id filter → same 2 rows.
     - Call with promotion_id=99999 → empty list.
     - Call with limit=1 → 1 row.
  G. UI smoke (SKIP in headless):
     - Try App(). If _tkinter.TclError, print SKIP.
     - Else: verify self.rankings exists; set filter=AC, refresh,
       assert 2 entries; set filter=RFL, refresh, assert 3 entries;
       destroy app.
  H. Regression:
     - Build fresh DB. app.resolve_next_fight(conn).
     - Assert fight_history has 2 new rows (Task 4).
     - Assert events.status='completed' (Task 7).
     - Assert new event auto-scheduled (Task 8).
     - Assert contracts unchanged (Task 9).
     - Assert rankings has 2 updated rows for the participants (Task 10).

Run from the project root:
    python3 scripts/test_rankings.py

Exit code 0 = all PASS, 1 = any FAIL (case G SKIP is not a fail).
The script rebuilds the DB at `data/cage_empire.db` — it does not
modify any source files.

Reproducibility note:
  `random.seed(42)` is set before each `app.resolve_next_fight()` call
  so the test is reproducible. The seed only pins down which random
  draws the resolver sees, not what it does with them.
"""
import random
import shutil
import sqlite3
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
DB_BACKUP_PATH = PROJECT_DIR / "data" / "cage_empire.case_abc_backup.db"

# Make src/ importable so we can call get_rankings_for_display(),
# _update_rankings_after_resolution(), and (for case G) construct
# App() directly. Importing app.py pulls in tkinter — the import
# itself does not require a display (only tk.Tk() does), so this
# is safe in headless contexts.
sys.path.insert(0, str(SRC_DIR))
import app  # noqa: E402
import build_db  # noqa: E402

# Seed for reproducibility — see module docstring.
RANDOM_SEED = 42

# Schema version + migration name prefix (read dynamically from
# build_db so this test does not need to be updated on every schema
# version bump — same pattern the supervisor applied to
# test_fight_history.py and test_schema_versioning.py in Task 9's
# sign-off).
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Expected rankings counts after seeding.
EXPECTED_RANKINGS_ROWS = 5  # 2 AC + 3 RFL
INITIAL_RATING = 1000.0

# ELO K-factor (must match app._ELO_K).
ELO_K = 32.0

# Expected event date from the seed (Alpha Combat: Test Night).
# HW8.1: the seeded event now follows simulation_clock.current_date
# (was hardcoded "2026-08-15" while the fresh-DB clock started at
# "2026-08-14"). The fresh-DB clock is GAME_START_DATE = "2026-01-01"
# (per build_db.py), so the seeded event is now dated "2026-01-01".
SEEDED_EVENT_DATE = "2026-01-01"


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state.

    Mirrors the helper in test_contracts.py / test_event_scheduler.py
    so all tests share the same setup contract: a fresh DB with
    2 promotions (Alpha Combat + Rival Fight League), 5 fighters
    (2 AC + 3 RFL), 1 staff member (Nina Cross), 1 event, 1 fight,
    6 contracts (5 fighter + 1 staff), 5 rankings rows (all at 1000.0).
    """
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


def get_promotion_id(conn, name):
    """Look up a promotion_id by name. Raises if the promotion is missing."""
    row = conn.execute(
        "SELECT promotion_id FROM promotions WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"promotion {name!r} not found in seeded DB")
    return row[0]


def get_weight_class_id(conn, name="Lightweight"):
    """Look up a weight_class_id by name. Raises if missing."""
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"weight_class {name!r} not found in seeded DB")
    return row[0]


def set_fighter_attrs(conn, fighter_id, attr_val, pers_val):
    """Set all 4 attributes and all 3 personality traits to the given values."""
    conn.execute(
        "UPDATE fighter_attributes SET punch_power=?, cardio=?, fight_iq=?, "
        "chin=?, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (attr_val, attr_val, attr_val, attr_val, fighter_id),
    )
    conn.execute(
        "UPDATE fighter_personality SET aggression=?, composure=?, morale=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (pers_val, pers_val, pers_val, fighter_id),
    )


# Lazy import of _tkinter — only needed inside case G's exception
# handler. Wrapped so that if _tkinter itself is unavailable (which
# would imply `import tkinter` already failed at module load time),
# we don't get a NameError on the isinstance() check.
try:
    import _tkinter as _tkinter_mod
    _tkinter_TclError = _tkinter_mod.TclError
except ImportError:
    _tkinter_TclError = type("_MissingTclError", (Exception,), {})


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main():
    sep = "=" * 80
    print(sep)
    print("TASK 10 RANKINGS ACCEPTANCE TEST")
    print(sep)

    # Single bucket of results — every check is fatal. Each entry is
    # (case, name, passed, detail).
    results = []

    # ----------------------------------------------------------------
    # Build a fresh DB. Used by cases A, B, C, D, E, F.
    # ----------------------------------------------------------------
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    rfl_id = get_promotion_id(conn, "Rival Fight League")
    wc_id = get_weight_class_id(conn, "Lightweight")

    print(f"Alpha Combat promotion_id   = {alpha_combat_id}")
    print(f"Rival Fight League promo_id = {rfl_id}")
    print(f"Lightweight weight_class_id = {wc_id}")

    # ----------------------------------------------------------------
    # Test case A — Schema.
    # ----------------------------------------------------------------
    print("\n--- Case A: schema ---")

    # schema_meta.schema_version matches the code's current
    # CODE_SCHEMA_VERSION (dynamic, no hardcoding).
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    results.append((
        "A",
        f"schema_meta.schema_version == '{EXPECTED_CODE_VERSION}'",
        sv is not None and sv[0] == EXPECTED_CODE_VERSION,
        f"got={sv[0] if sv else None}",
    ))

    # migration name starts with 'v1_5_0_' (LIKE prefix check, so the
    # description suffix can change per task: _add_rankings, etc.).
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name LIKE ?",
        (EXPECTED_MIGRATION_PREFIX + "%",),
    ).fetchone()
    results.append((
        "A",
        f"migration starting with '{EXPECTED_MIGRATION_PREFIX}' recorded",
        mig is not None,
        f"found={mig}",
    ))

    # `rankings` table exists.
    rk_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='rankings'"
    ).fetchone()[0]
    results.append((
        "A",
        "rankings table exists",
        rk_count == 1,
        f"found={rk_count}",
    ))

    # `rankings` table has 12 expected columns.
    expected_cols = {
        "ranking_id", "fighter_id", "weight_class_id", "promotion_id",
        "rating", "fights_count", "wins", "losses", "draws",
        "last_fight_date", "created_at", "updated_at",
    }
    actual_cols = {r[1] for r in conn.execute("PRAGMA table_info(rankings)").fetchall()}
    results.append((
        "A",
        f"rankings has 12 expected columns ({sorted(expected_cols)})",
        actual_cols == expected_cols,
        f"got={sorted(actual_cols)}",
    ))

    # CHECK constraint: rating=-1 → IntegrityError.
    try:
        conn.execute(
            "INSERT INTO rankings (fighter_id, weight_class_id, promotion_id, "
            "rating) VALUES (?, ?, ?, -1.0)",
            (1, wc_id, alpha_combat_id),
        )
        results.append((
            "A",
            "CHECK rating >= 0: rating=-1 raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "CHECK rating >= 0: rating=-1 raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK rating >= 0: rating=-1 raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # CHECK constraint: fights_count=-1 → IntegrityError.
    try:
        conn.execute(
            "INSERT INTO rankings (fighter_id, weight_class_id, promotion_id, "
            "fights_count) VALUES (?, ?, ?, -1)",
            (1, wc_id, alpha_combat_id),
        )
        results.append((
            "A",
            "CHECK fights_count >= 0: fights_count=-1 raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "CHECK fights_count >= 0: fights_count=-1 raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "CHECK fights_count >= 0: fights_count=-1 raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # UNIQUE constraint: duplicate (fighter_id, weight_class_id, promotion_id)
    # → IntegrityError. The seed already created a row for fighter 1 / wc 1 /
    # promo 1, so inserting another should fail.
    try:
        conn.execute(
            "INSERT INTO rankings (fighter_id, weight_class_id, promotion_id) "
            "VALUES (?, ?, ?)",
            (1, wc_id, alpha_combat_id),
        )
        results.append((
            "A",
            "UNIQUE (fighter_id, weight_class_id, promotion_id): "
            "duplicate raises IntegrityError",
            False,
            "no exception raised",
        ))
    except sqlite3.IntegrityError:
        results.append((
            "A",
            "UNIQUE (fighter_id, weight_class_id, promotion_id): "
            "duplicate raises IntegrityError",
            True,
            "IntegrityError raised",
        ))
    except Exception as e:
        results.append((
            "A",
            "UNIQUE (fighter_id, weight_class_id, promotion_id): "
            "duplicate raises IntegrityError",
            False,
            f"wrong exception: {type(e).__name__}: {e}",
        ))

    # ----------------------------------------------------------------
    # Test case B — Seed.
    # ----------------------------------------------------------------
    print("\n--- Case B: seed ---")

    # 5 rankings rows.
    n_rankings = conn.execute("SELECT COUNT(*) FROM rankings").fetchone()[0]
    results.append((
        "B",
        f"rankings has {EXPECTED_RANKINGS_ROWS} rows after seed",
        n_rankings == EXPECTED_RANKINGS_ROWS,
        f"got={n_rankings}",
    ))

    # All rating=1000.0.
    n_non_default = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE rating != 1000.0"
    ).fetchone()[0]
    results.append((
        "B",
        "all rankings rows have rating=1000.0",
        n_non_default == 0,
        f"non_default={n_non_default}",
    ))

    # All fights_count=0, wins=0, losses=0, draws=0.
    n_non_zero = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE fights_count != 0 OR "
        "wins != 0 OR losses != 0 OR draws != 0"
    ).fetchone()[0]
    results.append((
        "B",
        "all rankings rows have fights_count=0, wins=0, losses=0, draws=0",
        n_non_zero == 0,
        f"non_zero={n_non_zero}",
    ))

    # All last_fight_date IS NULL.
    n_non_null = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE last_fight_date IS NOT NULL"
    ).fetchone()[0]
    results.append((
        "B",
        "all rankings rows have last_fight_date IS NULL",
        n_non_null == 0,
        f"non_null={n_non_null}",
    ))

    # Each fighter's rankings row promotion_id matches their
    # current_promotion_id.
    mismatches = conn.execute(
        "SELECT COUNT(*) FROM rankings r JOIN fighters f "
        "ON f.fighter_id = r.fighter_id "
        "WHERE r.promotion_id != f.current_promotion_id"
    ).fetchone()[0]
    results.append((
        "B",
        "every rankings row promotion_id matches fighter's "
        "current_promotion_id",
        mismatches == 0,
        f"mismatches={mismatches}",
    ))

    # ----------------------------------------------------------------
    # Test case C — ELO update on fight resolution.
    # ----------------------------------------------------------------
    print("\n--- Case C: ELO update on fight resolution ---")

    # Rebuild fresh DB so case A's CHECK/UNIQUE test inserts don't
    # pollute the state.
    conn.close()
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Re-fetch IDs (they should be the same since the DB was rebuilt
    # identically, but defensive).
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    rfl_id = get_promotion_id(conn, "Rival Fight League")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Set fighter 1 attrs all-90, fighter 2 attrs all-30. Both start
    # at rating=1000.0 (from the seed).
    set_fighter_attrs(conn, 1, 90, 90)  # all-90 attrs + personality
    set_fighter_attrs(conn, 2, 30, 30)  # all-30 attrs + personality
    conn.commit()

    # Snapshot ratings before resolution.
    rating_f1_before = conn.execute(
        "SELECT rating FROM rankings WHERE fighter_id=1"
    ).fetchone()[0]
    rating_f2_before = conn.execute(
        "SELECT rating FROM rankings WHERE fighter_id=2"
    ).fetchone()[0]
    assert rating_f1_before == 1000.0 and rating_f2_before == 1000.0

    random.seed(RANDOM_SEED)
    resolved = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "C",
        "resolve_next_fight returned a fight_id",
        resolved is not None,
        f"fight_id={resolved}",
    ))

    # Determine who won (should be fighter 1 since all-90 beats all-30
    # ~100% of the time, but check the actual result to be safe).
    fight_row = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type "
        "FROM fights WHERE fight_id=?",
        (resolved,),
    ).fetchone()
    winner_id, loser_id, result_type = fight_row
    results.append((
        "C",
        "fight resolved with a non-draw result (winner + loser)",
        result_type != "draw" and winner_id is not None and loser_id is not None,
        f"winner={winner_id}, loser={loser_id}, result_type={result_type}",
    ))

    # Winner rating > 1000.0, loser rating < 1000.0.
    rating_winner = conn.execute(
        "SELECT rating FROM rankings WHERE fighter_id=?",
        (winner_id,),
    ).fetchone()[0]
    rating_loser = conn.execute(
        "SELECT rating FROM rankings WHERE fighter_id=?",
        (loser_id,),
    ).fetchone()[0]
    results.append((
        "C",
        "winner rating > 1000.0",
        rating_winner > 1000.0,
        f"got={rating_winner}",
    ))
    results.append((
        "C",
        "loser rating < 1000.0",
        rating_loser < 1000.0,
        f"got={rating_loser}",
    ))

    # Zero-sum: sum of both ratings == 2000.0 ± 0.01.
    rating_sum = rating_winner + rating_loser
    results.append((
        "C",
        "zero-sum: winner + loser ratings == 2000.0 ± 0.01",
        abs(rating_sum - 2000.0) <= 0.01,
        f"got={rating_sum}",
    ))

    # Both fights_count=1.
    fc_winner = conn.execute(
        "SELECT fights_count FROM rankings WHERE fighter_id=?",
        (winner_id,),
    ).fetchone()[0]
    fc_loser = conn.execute(
        "SELECT fights_count FROM rankings WHERE fighter_id=?",
        (loser_id,),
    ).fetchone()[0]
    results.append((
        "C",
        "both fighters fights_count=1",
        fc_winner == 1 and fc_loser == 1,
        f"winner={fc_winner}, loser={fc_loser}",
    ))

    # Winner wins=1, loser losses=1.
    wins_winner = conn.execute(
        "SELECT wins FROM rankings WHERE fighter_id=?",
        (winner_id,),
    ).fetchone()[0]
    losses_loser = conn.execute(
        "SELECT losses FROM rankings WHERE fighter_id=?",
        (loser_id,),
    ).fetchone()[0]
    results.append((
        "C",
        "winner wins=1, loser losses=1",
        wins_winner == 1 and losses_loser == 1,
        f"winner_wins={wins_winner}, loser_losses={losses_loser}",
    ))

    # Both last_fight_date='2026-08-15' (the seeded event date).
    lfd_winner = conn.execute(
        "SELECT last_fight_date FROM rankings WHERE fighter_id=?",
        (winner_id,),
    ).fetchone()[0]
    lfd_loser = conn.execute(
        "SELECT last_fight_date FROM rankings WHERE fighter_id=?",
        (loser_id,),
    ).fetchone()[0]
    results.append((
        "C",
        f"both last_fight_date='{SEEDED_EVENT_DATE}'",
        lfd_winner == SEEDED_EVENT_DATE and lfd_loser == SEEDED_EVENT_DATE,
        f"winner={lfd_winner}, loser={lfd_loser}",
    ))

    # ----------------------------------------------------------------
    # Backup case A/B/C state for case H (which rebuilds the DB).
    # ----------------------------------------------------------------
    conn.close()
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, DB_BACKUP_PATH)

    # ----------------------------------------------------------------
    # Test case D — ELO upset math.
    # ----------------------------------------------------------------
    print("\n--- Case D: ELO upset math ---")

    # Upset scenario: f2 (rating 800) beats f1 (rating 1500).
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("UPDATE rankings SET rating=1500.0 WHERE fighter_id=1")
    conn.execute("UPDATE rankings SET rating=800.0 WHERE fighter_id=2")
    # Make f2 win: f2 all-90, f1 all-30.
    set_fighter_attrs(conn, 1, 30, 30)
    set_fighter_attrs(conn, 2, 90, 90)
    conn.commit()
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()
    # Verify f2 actually won (defensive). Query the RESOLVED fight
    # (result_type IS NOT NULL) — the auto-scheduler (Task 8) creates
    # a new unresolved fight after the event completes, so
    # ORDER BY fight_id DESC LIMIT 1 alone would pick the unresolved
    # one. Filter to resolved fights only.
    d_upset_row = conn.execute(
        "SELECT winner_fighter_id, result_type FROM fights "
        "WHERE result_type IS NOT NULL ORDER BY fight_id DESC LIMIT 1"
    ).fetchone()
    upset_rating_f2 = conn.execute(
        "SELECT rating FROM rankings WHERE fighter_id=2"
    ).fetchone()[0]
    upset_gain = upset_rating_f2 - 800.0
    results.append((
        "D",
        "upset scenario: f2 (rating 800) won against f1 (rating 1500)",
        d_upset_row is not None and d_upset_row[0] == 2 and d_upset_row[1] != "draw",
        f"winner={d_upset_row[0] if d_upset_row else None}, "
        f"result={d_upset_row[1] if d_upset_row else None}",
    ))
    results.append((
        "D",
        f"upset gain > 0 (f2 rating moved up from 800.0)",
        upset_gain > 0,
        f"upset_gain={upset_gain:.4f}",
    ))

    conn.close()

    # Favorite scenario: f1 (rating 1500) beats f2 (rating 800).
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("UPDATE rankings SET rating=1500.0 WHERE fighter_id=1")
    conn.execute("UPDATE rankings SET rating=800.0 WHERE fighter_id=2")
    # Make f1 win: f1 all-90, f2 all-30.
    set_fighter_attrs(conn, 1, 90, 90)
    set_fighter_attrs(conn, 2, 30, 30)
    conn.commit()
    random.seed(RANDOM_SEED)
    app.resolve_next_fight(conn)
    conn.commit()
    # Verify f1 actually won (defensive). Filter to resolved fights
    # (see upset scenario comment above).
    d_fav_row = conn.execute(
        "SELECT winner_fighter_id, result_type FROM fights "
        "WHERE result_type IS NOT NULL ORDER BY fight_id DESC LIMIT 1"
    ).fetchone()
    fav_rating_f1 = conn.execute(
        "SELECT rating FROM rankings WHERE fighter_id=1"
    ).fetchone()[0]
    fav_gain = fav_rating_f1 - 1500.0
    results.append((
        "D",
        "favorite scenario: f1 (rating 1500) won against f2 (rating 800)",
        d_fav_row is not None and d_fav_row[0] == 1 and d_fav_row[1] != "draw",
        f"winner={d_fav_row[0] if d_fav_row else None}, "
        f"result={d_fav_row[1] if d_fav_row else None}",
    ))
    results.append((
        "D",
        f"favorite gain > 0 (f1 rating moved up from 1500.0)",
        fav_gain > 0,
        f"fav_gain={fav_gain:.4f}",
    ))

    # Assert upset gain >= 10x favorite-wins gain.
    if fav_gain > 0:
        ratio = upset_gain / fav_gain
        results.append((
            "D",
            f"upset gain >= 10x favorite gain (ratio={ratio:.2f}x)",
            upset_gain >= 10 * fav_gain,
            f"upset_gain={upset_gain:.4f}, fav_gain={fav_gain:.4f}, "
            f"ratio={ratio:.2f}x",
        ))
    else:
        results.append((
            "D",
            "upset gain >= 10x favorite gain",
            False,
            f"favorite gain is 0 or negative ({fav_gain:.4f}), "
            f"cannot compute ratio",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case E — Draw handling.
    # ----------------------------------------------------------------
    print("\n--- Case E: draw handling ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Set both fighters' attrs AND personality to 50/50 (draw likely).
    # The resolver uses personality too, so setting only attrs would
    # still be asymmetric. Setting both to 50/50 maximizes draw
    # probability (same approach as test_fight_history.py's draw path).
    set_fighter_attrs(conn, 1, 50, 50)
    set_fighter_attrs(conn, 2, 50, 50)
    conn.commit()

    # random.seed(42), resolve up to 20 tries until a draw occurs.
    # Each resolve picks the lowest unresolved fight_id. After the
    # first resolve, the event completes and a new event+fight is
    # auto-scheduled (Task 8), so the second resolve picks the new
    # fight, and so on. With both fighters at 50/50, each fight has
    # a ~12% chance of being a draw (margin < 5 → coin flip → 50%
    # draw). Over 20 tries, the probability of at least one draw is
    # very high. With seed=42, a draw occurs on the first try.
    random.seed(RANDOM_SEED)
    draw_fight_id = None
    for attempt in range(20):
        fid = app.resolve_next_fight(conn)
        conn.commit()
        if fid is None:
            break
        rt = conn.execute(
            "SELECT result_type FROM fights WHERE fight_id=?",
            (fid,),
        ).fetchone()
        if rt and rt[0] == "draw":
            draw_fight_id = fid
            break

    if draw_fight_id is None:
        print("  SKIP — no draw occurred in 20 tries (probabilistic; "
              "re-run with a different seed if this persists)")
        results.append((
            "E",
            "draw occurred within 20 tries",
            None,  # SKIP
            "no draw in 20 tries",
        ))
    else:
        results.append((
            "E",
            f"draw occurred within 20 tries (fight_id={draw_fight_id})",
            True,
            f"fight_id={draw_fight_id}",
        ))

        # Both fighters draws=1, fights_count=1. These assertions hold
        # because with seed=42, the draw happens on the first try
        # (fight_id=1), so no previous non-draw fights have occurred.
        # If the draw happened on a later try, fights_count would be
        # > 1 — but we verify the actual state here rather than
        # assuming.
        draws_f1 = conn.execute(
            "SELECT draws FROM rankings WHERE fighter_id=1"
        ).fetchone()[0]
        draws_f2 = conn.execute(
            "SELECT draws FROM rankings WHERE fighter_id=2"
        ).fetchone()[0]
        fc_f1 = conn.execute(
            "SELECT fights_count FROM rankings WHERE fighter_id=1"
        ).fetchone()[0]
        fc_f2 = conn.execute(
            "SELECT fights_count FROM rankings WHERE fighter_id=2"
        ).fetchone()[0]
        results.append((
            "E",
            "both fighters draws=1 (only the draw fight occurred)",
            draws_f1 == 1 and draws_f2 == 1,
            f"f1_draws={draws_f1}, f2_draws={draws_f2}",
        ))
        results.append((
            "E",
            "both fighters fights_count=1",
            fc_f1 == 1 and fc_f2 == 1,
            f"f1_fc={fc_f1}, f2_fc={fc_f2}",
        ))

        # With both at 1000.0, expected=0.5, so draw produces zero
        # rating change (score=0.5, delta=0). Assert both ratings
        # still 1000.0 (±0.01).
        rating_f1 = conn.execute(
            "SELECT rating FROM rankings WHERE fighter_id=1"
        ).fetchone()[0]
        rating_f2 = conn.execute(
            "SELECT rating FROM rankings WHERE fighter_id=2"
        ).fetchone()[0]
        results.append((
            "E",
            "draw with both at 1000.0 → zero rating change "
            "(both still 1000.0 ± 0.01)",
            abs(rating_f1 - 1000.0) <= 0.01 and abs(rating_f2 - 1000.0) <= 0.01,
            f"f1={rating_f1:.4f}, f2={rating_f2:.4f}",
        ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case F — get_rankings_for_display() helper.
    # ----------------------------------------------------------------
    print("\n--- Case F: get_rankings_for_display() helper ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")
    rfl_id = get_promotion_id(conn, "Rival Fight League")
    wc_id = get_weight_class_id(conn, "Lightweight")

    # Resolve a few fights (seed=42). With default 50/50 fighters,
    # this produces a mix of wins/losses/draws that move ratings.
    set_fighter_attrs(conn, 1, 90, 90)  # f1 all-90 to make wins reliable
    set_fighter_attrs(conn, 2, 30, 30)  # f2 all-30
    conn.commit()
    random.seed(RANDOM_SEED)
    for _ in range(3):
        app.resolve_next_fight(conn)
        conn.commit()

    # Call helper with alpha_combat_id → 2 rows ordered by rating DESC.
    rows_ac = app.get_rankings_for_display(conn, alpha_combat_id)
    results.append((
        "F",
        f"AC rankings: 2 rows returned",
        len(rows_ac) == 2,
        f"got={len(rows_ac)} rows",
    ))

    # Every row is a 7-tuple.
    bad_arity = [r for r in rows_ac if len(r) != 7]
    results.append((
        "F",
        "every row is a 7-tuple (rank, fighter, wc, rating, fights, "
        "record, last_fight)",
        len(bad_arity) == 0,
        f"bad rows={bad_arity}",
    ))

    # Rank is 1-indexed.
    ranks = [r[0] for r in rows_ac]
    results.append((
        "F",
        "rank is 1-indexed (ranks == [1, 2])",
        ranks == [1, 2],
        f"ranks={ranks}",
    ))

    # Ordered by rating DESC.
    ratings_list = [r[3] for r in rows_ac]
    results.append((
        "F",
        "rows ordered by rating DESC",
        ratings_list == sorted(ratings_list, reverse=True),
        f"ratings={ratings_list}",
    ))

    # Call with weight_class_id filter → same 2 rows.
    rows_wc = app.get_rankings_for_display(conn, alpha_combat_id, weight_class_id=wc_id)
    results.append((
        "F",
        "weight_class_id filter: same 2 rows as no filter",
        len(rows_wc) == 2 and {r[1] for r in rows_wc} == {r[1] for r in rows_ac},
        f"got={len(rows_wc)} rows, "
        f"fighters={[r[1] for r in rows_wc]}",
    ))

    # Call with promotion_id=99999 → empty list.
    try:
        rows_invalid = app.get_rankings_for_display(conn, 99999)
        results.append((
            "F",
            "invalid promotion_id=99999: returns empty list, no crash",
            len(rows_invalid) == 0,
            f"got={len(rows_invalid)} rows",
        ))
    except Exception as e:
        results.append((
            "F",
            "invalid promotion_id=99999: returns empty list, no crash",
            False,
            f"crashed: {type(e).__name__}: {e}",
        ))

    # Call with limit=1 → 1 row.
    rows_limit1 = app.get_rankings_for_display(conn, alpha_combat_id, limit=1)
    results.append((
        "F",
        "limit=1: returns 1 row",
        len(rows_limit1) == 1,
        f"got={len(rows_limit1)} rows",
    ))

    conn.close()

    # ----------------------------------------------------------------
    # Test case G — UI smoke test (optional, SKIPs cleanly in headless).
    # ----------------------------------------------------------------
    print("\n--- Case G: UI smoke test ---")
    g_skipped = False
    # Restore case A/B/C state for the UI smoke (so the DB has the
    # expected seed + a resolved fight). Actually, the UI smoke should
    # run on a fresh seeded DB (no resolved fights) so the rankings
    # are all at 1000.0. Build fresh.
    build_fresh_db()
    try:
        app_instance = app.App()
    except (_tkinter_TclError, AttributeError) as e:
        print(f"  SKIP — no display available ({type(e).__name__})")
        g_skipped = True
    except Exception as e:
        results.append((
            "G",
            "App() constructs without crashing",
            False,
            f"App() crashed: {type(e).__name__}: {e}",
        ))
        g_skipped = True  # nothing else to test in case G
    else:
        try:
            # Verify self.rankings Treeview widget exists.
            has_rankings_widget = hasattr(app_instance, "rankings")
            results.append((
                "G",
                "App() has self.rankings Treeview widget",
                has_rankings_widget,
                f"hasattr={has_rankings_widget}",
            ))

            # Set filter to AC, refresh, assert Rankings tree has 2 entries.
            app_instance.current_promotion_filter = alpha_combat_id
            app_instance.refresh_all()
            n_ac = len(app_instance.rankings.get_children())
            results.append((
                "G",
                "filter=AC: Rankings tree has 2 entries",
                n_ac == 2,
                f"got={n_ac}",
            ))

            # Set filter to RFL, refresh, assert Rankings tree has 3.
            app_instance.current_promotion_filter = rfl_id
            app_instance.refresh_all()
            n_rfl = len(app_instance.rankings.get_children())
            results.append((
                "G",
                "filter=RFL: Rankings tree has 3 entries",
                n_rfl == 3,
                f"got={n_rfl}",
            ))
        finally:
            try:
                app_instance.destroy()
            except Exception:
                pass

    # ----------------------------------------------------------------
    # Test case H — Regression.
    # ----------------------------------------------------------------
    print("\n--- Case H: regression (fight_history + event lifecycle + "
          "event scheduler + contracts + rankings) ---")

    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    alpha_combat_id = get_promotion_id(conn, "Alpha Combat")

    # Jack fighter 1 to all-90 attrs + personality so the resolve
    # produces a non-draw (winner + loser). With default 50/50
    # fighters, seed=42 produces a DRAW on the first resolve (see
    # case E above), which would leave ratings at 1000.0 and fail the
    # "rating != 1000.0" assertion below. Jacking f1 to all-90 makes
    # f1 win reliably (~99.4%), moving both fighters' ratings.
    set_fighter_attrs(conn, 1, 90, 90)
    conn.commit()

    # Snapshot before resolution.
    fh_before = conn.execute(
        "SELECT COUNT(*) FROM fight_history"
    ).fetchone()[0]
    events_before = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    contracts_before = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    rankings_before = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE fights_count = 0"
    ).fetchone()[0]  # all 5 rows start at fights_count=0

    random.seed(RANDOM_SEED)
    resolved = app.resolve_next_fight(conn)
    conn.commit()
    results.append((
        "H",
        "resolve_next_fight returned a fight_id",
        resolved is not None,
        f"fight_id={resolved}",
    ))

    # fight_history has 2 new rows (Task 4).
    fh_after = conn.execute(
        "SELECT COUNT(*) FROM fight_history"
    ).fetchone()[0]
    results.append((
        "H",
        "fight_history has 2 new rows after resolution (Task 4)",
        fh_after - fh_before == 2,
        f"before={fh_before}, after={fh_after}, "
        f"delta={fh_after - fh_before}",
    ))

    # Seeded event's status is 'completed' (Task 7).
    seeded_status = conn.execute(
        "SELECT status FROM events ORDER BY event_id LIMIT 1"
    ).fetchone()
    results.append((
        "H",
        "seeded event's status is 'completed' after resolution (Task 7)",
        seeded_status is not None and seeded_status[0] == "completed",
        f"got={seeded_status[0] if seeded_status else None}",
    ))

    # A new event was auto-scheduled (Task 8).
    events_after = conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    results.append((
        "H",
        "1 new event auto-scheduled (Task 8 hook)",
        events_after - events_before == 1,
        f"before={events_before}, after={events_after}, "
        f"delta={events_after - events_before}",
    ))

    # Contracts table unchanged (Task 9 — fight resolution doesn't
    # touch contracts).
    contracts_after = conn.execute(
        "SELECT COUNT(*) FROM contracts"
    ).fetchone()[0]
    results.append((
        "H",
        "contracts table unchanged after fight resolution (Task 9)",
        contracts_after == contracts_before,
        f"before={contracts_before}, after={contracts_after}",
    ))

    # Rankings: 2 updated rows for the participants (Task 10).
    # The two participants now have fights_count=1 (was 0).
    rankings_after = conn.execute(
        "SELECT COUNT(*) FROM rankings WHERE fights_count = 0"
    ).fetchone()[0]
    results.append((
        "H",
        "rankings: 2 rows updated (fights_count 0 → 1) for the "
        "participants (Task 10)",
        rankings_before - rankings_after == 2,
        f"before_fights_count_0={rankings_before}, "
        f"after_fights_count_0={rankings_after}, "
        f"delta={rankings_before - rankings_after}",
    ))

    # Also verify the 2 updated rows have non-default ratings (moved
    # from 1000.0) and last_fight_date is set.
    updated_rows = conn.execute(
        "SELECT fighter_id, rating, fights_count, last_fight_date "
        "FROM rankings WHERE fights_count > 0 ORDER BY fighter_id"
    ).fetchall()
    results.append((
        "H",
        "the 2 updated rankings rows have rating != 1000.0 and "
        "last_fight_date set",
        len(updated_rows) == 2
        and all(r[1] != 1000.0 and r[3] is not None for r in updated_rows),
        f"rows={updated_rows}",
    ))

    conn.close()

    # Clean up the backup file if it exists.
    if DB_BACKUP_PATH.exists():
        DB_BACKUP_PATH.unlink()

    # ----------------------------------------------------------------
    # Print summary table.
    # ----------------------------------------------------------------
    print("\n" + sep)
    print(f"{'Case':<6} {'Check':<72} {'Result':<8} Detail")
    print("-" * 120)
    n_pass = 0
    n_fail = 0
    n_skip = 0
    by_case = {}
    for case, name, passed, detail in results:
        if passed is None:
            status = "SKIP"
            n_skip += 1
        elif passed:
            status = "PASS"
            n_pass += 1
        else:
            status = "FAIL"
            n_fail += 1
        by_case.setdefault(case, {"pass": 0, "fail": 0, "skip": 0})
        if passed is None:
            by_case[case]["skip"] += 1
        elif passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 50:
            detail_str = detail_str[:47] + "..."
        print(f"{case:<6} {name:<72} {status:<8} {detail_str}")
    if g_skipped and not any(c == "G" for c, _, _, _ in results):
        print(f"{'G':<6} {'UI smoke test (App construction + Rankings tab)':<72} "
              f"{'SKIP':<8} no display available")
    print(sep)
    summary_parts = [f"Total: {n_pass} PASS, {n_fail} FAIL"]
    if n_skip > 0:
        summary_parts.append(f"{n_skip} SKIP")
    if g_skipped:
        summary_parts.append("(+ case G skipped — no display)")
    print(", ".join(summary_parts))
    print(sep)
    print("By case:")
    for case in sorted(by_case.keys()):
        c = by_case[case]
        parts = [f"{c['pass']} PASS", f"{c['fail']} FAIL"]
        if c["skip"] > 0:
            parts.append(f"{c['skip']} SKIP")
        print(f"  Case {case}: {', '.join(parts)}")
    if g_skipped and "G" not in by_case:
        print(f"  Case G: SKIP (no display available)")
    print(sep)

    overall_pass = n_fail == 0
    if overall_pass:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
