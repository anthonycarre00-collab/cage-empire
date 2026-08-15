#!/usr/bin/env python3
"""Phase M2 — Staff Lifecycle test suite.

Per docs/MASTER_PLAN_MATCHMAKING.md §2.3 + docs/RESEARCH_FIGHTERGEN_
RIVALAI_STAFFLIFE.md §C.

Verifies the 4 staff lifecycle deliverables:
  M2.1 — Staff aging on annual tick (Jan 1: all staff.age += 1)
  M2.2 — Staff retirement probability curve
         (65-69: 10%, 70-74: 25%, 75+: 50%, under 65: 0%)
  M2.3 — Staff regen (replacement + staff_regen_lineage table)
  M2.4 — Staff contract expiry (extend _check_contract_expiry)

Uses a SEPARATE test DB (data/cage_empire_m2_test.db) so the world
DB is untouched. Each test rebuilds + seeds + injects test staff at
specific ages + advances the clock to the relevant boundary dates.

Usage:
    python3 scripts/test_staff_lifecycle.py

Exit code 0 = all PASS, 1 = any FAIL.
"""
import os
import sys
import sqlite3
import subprocess
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_m2_test.db"
SAVES_DIR = PROJECT_DIR / "data" / "saves"

# Use a separate test DB so the world DB is never touched.
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
os.environ["CAGE_EMPIRE_ALLOW_FRESH"] = "1"
sys.path.insert(0, str(SRC_DIR))

from tick_processor import (
    run_tick,
    _check_staff_annual_lifecycle,
    _check_contract_expiry,
)
from event_bus import get_bus, reset_bus, Events


# ============================================================
# Test runner
# ============================================================

class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []
        self.skipped = 0

    def check(self, case, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  [PASS] {case}  {name:<70}  {detail}")
        else:
            self.failed += 1
            self.failures.append((case, name, detail))
            print(f"  [FAIL] {case}  {name:<70}  {detail}")
        return cond

    def skip(self, case, name, reason=""):
        self.skipped += 1
        print(f"  [SKIP] {case}  {name:<70}  {reason}")
        return False


# ============================================================
# DB setup helpers
# ============================================================

def build_fresh_db():
    """Drop + rebuild + seed the test DB with minimal seed_data."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True, cwd=PROJECT_DIR,
        env={**os.environ, "CAGE_EMPIRE_ALLOW_FRESH": "1"},
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True, cwd=PROJECT_DIR,
    )


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def set_sim_date(conn, iso_date):
    """Force the simulation_clock.current_date to a specific value.

    Also recomputes current_day/current_week/current_month/current_year
    so they stay consistent (the tick_processor.run_tick reads
    simulation_clock.current_day for the day counter, etc.).
    """
    from datetime import datetime
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    # Compute current_day as the day-of-year (1-indexed) — close
    # enough for the test; the lifecycle hook only checks month/day,
    # not the day counter.
    day_of_year = dt.timetuple().tm_yday
    week = ((day_of_year - 1) // 7) + 1
    conn.execute(
        "UPDATE simulation_clock SET current_date=?, current_day=?, "
        "current_week=?, current_month=?, current_year=? WHERE clock_id=1",
        (iso_date, day_of_year, week, dt.month, dt.year),
    )
    conn.commit()


def get_sim_date(conn):
    """Read simulation_clock.current_date (qualified to avoid the
    SQLite CURRENT_DATE function collision).
    """
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else None


def inject_staff(conn, first, last, age, role_type='commentator',
                 promotion_id=None, skill_level=50, specialty=None,
                 gym_id=None):
    """Insert a test staff row at a specific age. Returns staff_id.

    Used to set up retirement-curve tests (inject staff at ages 64,
    65, 70, 75, etc. then advance to Jan 1 and verify the retirement
    rolls fire in the right bands).
    """
    if specialty is None:
        specialty_by_role = {
            'scout': '{"eye_for_talent": 50, "technical_analysis": 50}',
            'commentator': 'play_by_play',
            'doctor': 'sports_medicine',
            'cutman': 'cuts_and_swelling',
            'general_manager': 'operations',
        }
        specialty = specialty_by_role.get(role_type, 'general')
    cur = conn.execute(
        "INSERT INTO staff (first_name, last_name, age, role_type, "
        "specialty, promotion_id, gym_id, skill_level) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (first, last, age, role_type, specialty, promotion_id,
         gym_id, skill_level),
    )
    conn.commit()
    return cur.lastrowid


def inject_staff_contract(conn, staff_id, promotion_id, role_type,
                          start_date='2026-01-01', end_date='2027-12-31',
                          salary=50000.0):
    """Insert a staff_contracts + contracts row for a test staff."""
    contract_id = conn.execute(
        "INSERT INTO contracts (contract_target_type, promotion_id, "
        "start_date, end_date, salary, exclusive_flag, status) "
        "VALUES ('staff', ?, ?, ?, ?, 1, 'active')",
        (promotion_id, start_date, end_date, salary),
    ).lastrowid
    conn.execute(
        "INSERT INTO staff_contracts (contract_id, staff_id, contract_role) "
        "VALUES (?, ?, ?)",
        (contract_id, staff_id, role_type),
    )
    conn.commit()
    return contract_id


# ============================================================
# M2.1 — Staff aging on annual tick
# ============================================================

def test_m2_1_staff_aging(r):
    """M2.1: Staff aging fires on Jan 1, ages all staff +1."""
    case = "M2.1"
    print(f"\n{'=' * 72}")
    print(f"  {case} — Staff aging on annual tick")
    print(f"{'=' * 72}")

    build_fresh_db()
    conn = get_conn()

    # Inject test staff at various ages (one of each role + various
    # age bands so we can reuse the setup for retirement tests later).
    inject_staff(conn, "Al", "Able", 64, 'commentator', promotion_id=1)
    inject_staff(conn, "Bo", "Baker", 68, 'doctor', promotion_id=1)
    inject_staff(conn, "Cy", "Carr", 72, 'cutman', promotion_id=1)
    inject_staff(conn, "Di", "Dover", 78, 'general_manager', promotion_id=1)
    inject_staff(conn, "Ed", "Evan", 30, 'scout', promotion_id=1)

    # Confirm setup
    rows = conn.execute(
        "SELECT first_name, last_name, age FROM staff ORDER BY age"
    ).fetchall()
    print(f"  SETUP — staff ages (sorted): {rows}")

    # Test 1: Non-Jan-1 date — staff_annual_lifecycle is a no-op.
    set_sim_date(conn, "2026-12-31")
    result = _check_staff_annual_lifecycle(conn, "2026-12-31")
    r.check(case, "non-Jan-1 date returns aged_count=0",
            result['aged_count'] == 0,
            f"got={result['aged_count']}")
    ages_after_noop = conn.execute(
        "SELECT first_name, age FROM staff WHERE first_name='Al'"
    ).fetchone()
    r.check(case, "non-Jan-1 date does NOT age staff",
            ages_after_noop[1] == 64,
            f"got={ages_after_noop[1]} (expected 64)")

    # Test 2: Jan 1 — all staff age +1.
    # Capture the staff count BEFORE the lifecycle runs (the aging
    # UPDATE's rowcount reflects the pre-retirement count; after the
    # lifecycle, retirements + regen replacements will have changed
    # the total).
    pre_lifecycle_count = conn.execute(
        "SELECT COUNT(*) FROM staff"
    ).fetchone()[0]
    set_sim_date(conn, "2027-01-01")
    result = _check_staff_annual_lifecycle(conn, "2027-01-01")
    r.check(case, "Jan-1 returns aged_count=total staff count",
            result['aged_count'] == pre_lifecycle_count,
            f"got={result['aged_count']} expected={pre_lifecycle_count}")

    ages_after = dict(conn.execute(
        "SELECT first_name, age FROM staff"
    ).fetchall())
    expected = {"Al": 65, "Bo": 69, "Cy": 73, "Di": 79, "Ed": 31, "Nina": 42}
    for name, exp_age in expected.items():
        if name in ages_after:
            r.check(case, f"{name} aged +1 to {exp_age}",
                    ages_after[name] == exp_age,
                    f"got={ages_after[name]} expected={exp_age}")

    # Test 3: Jan 2 of the same year — no further aging (annual =
    # once per year, not once per day-in-January).
    set_sim_date(conn, "2027-01-02")
    result = _check_staff_annual_lifecycle(conn, "2027-01-02")
    r.check(case, "Jan-2 does NOT re-age (annual = once per year)",
            result['aged_count'] == 0,
            f"got={result['aged_count']}")

    # Test 4: Jan 1 of the NEXT year — staff age again (+1).
    pre_count_y2 = conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
    set_sim_date(conn, "2028-01-01")
    result = _check_staff_annual_lifecycle(conn, "2028-01-01")
    r.check(case, "Jan-1 of next year ages staff again",
            result['aged_count'] == pre_count_y2,
            f"got={result['aged_count']}")
    ages_after_2 = dict(conn.execute(
        "SELECT first_name, age FROM staff"
    ).fetchall())
    r.check(case, "Al aged from 65 to 66 over the next year",
            ages_after_2.get("Al") == 66,
            f"got={ages_after_2.get('Al')} expected=66")

    # Test 5: Integration — run_tick advances from Dec 31 to Jan 1
    # and the aging fires (proves wiring in run_tick).
    build_fresh_db()
    conn = get_conn()
    inject_staff(conn, "Fa", "Finn", 50, 'commentator', promotion_id=1)
    set_sim_date(conn, "2026-12-31")
    pre_age = conn.execute(
        "SELECT age FROM staff WHERE first_name='Fa'"
    ).fetchone()[0]
    run_tick(conn, "day", 1)
    conn.commit()
    post_sim = get_sim_date(conn)
    post_age = conn.execute(
        "SELECT age FROM staff WHERE first_name='Fa'"
    ).fetchone()[0]
    r.check(case, "run_tick Dec-31->Jan-1 advances sim_date",
            post_sim == "2027-01-01",
            f"got={post_sim}")
    r.check(case, "run_tick Jan-1 ages staff (wiring verified)",
            post_age == pre_age + 1,
            f"pre={pre_age} post={post_age}")

    conn.close()


# ============================================================
# M2.2 — Staff retirement probability curve + STAFF_RETIRED event
# ============================================================

def test_m2_2_staff_retirement(r):
    """M2.2: Staff retirement curve + event + contract void + news."""
    case = "M2.2"
    print(f"\n{'=' * 72}")
    print(f"  {case} — Staff retirement (probability curve + STAFF_RETIRED)")
    print(f"{'=' * 72}")

    # Import the pure probability function for unit-level testing.
    from services.retirement_svc import (
        _staff_retirement_prob,
        STAFF_RETIREMENT_PROB_BY_AGE_BAND,
        check_staff_retirements,
    )

    # ---- Unit tests of the probability curve (pure function) -------
    r.check(case, "prob(age=30) == 0.0 (under 65 — never retire)",
            _staff_retirement_prob(30) == 0.0,
            f"got={_staff_retirement_prob(30)}")
    r.check(case, "prob(age=64) == 0.0 (still under 65)",
            _staff_retirement_prob(64) == 0.0,
            f"got={_staff_retirement_prob(64)}")
    r.check(case, "prob(age=65) == 0.10 (65-69 band)",
            abs(_staff_retirement_prob(65) - 0.10) < 1e-9,
            f"got={_staff_retirement_prob(65)}")
    r.check(case, "prob(age=69) == 0.10 (still 65-69 band)",
            abs(_staff_retirement_prob(69) - 0.10) < 1e-9,
            f"got={_staff_retirement_prob(69)}")
    r.check(case, "prob(age=70) == 0.25 (70-74 band)",
            abs(_staff_retirement_prob(70) - 0.25) < 1e-9,
            f"got={_staff_retirement_prob(70)}")
    r.check(case, "prob(age=74) == 0.25 (still 70-74 band)",
            abs(_staff_retirement_prob(74) - 0.25) < 1e-9,
            f"got={_staff_retirement_prob(74)}")
    r.check(case, "prob(age=75) == 0.50 (75+ band)",
            abs(_staff_retirement_prob(75) - 0.50) < 1e-9,
            f"got={_staff_retirement_prob(75)}")
    r.check(case, "prob(age=90) == 0.50 (still 75+ band)",
            abs(_staff_retirement_prob(90) - 0.50) < 1e-9,
            f"got={_staff_retirement_prob(90)}")

    r.check(case, "STAFF_RETIREMENT_PROB_BY_AGE_BAND has 4 bands",
            len(STAFF_RETIREMENT_PROB_BY_AGE_BAND) == 4,
            f"got={list(STAFF_RETIREMENT_PROB_BY_AGE_BAND.keys())}")

    # ---- Integration test: retirements fire on the annual tick -----
    build_fresh_db()
    conn = get_conn()
    # Inject staff at various ages (all of which have been aged to
    # the post-aging value via the lifecycle).
    # We inject staff AGED at the target value (so we don't need to
    # wait for aging) — the lifecycle's check_staff_retirements reads
    # staff.age directly.
    staff_ids = {
        'under65': inject_staff(conn, "Uly", "Under", 50,
                                'commentator', promotion_id=1),
        'at65':    inject_staff(conn, "Sia", "Sixfy", 65,
                                'doctor', promotion_id=1),
        'at70':    inject_staff(conn, "Sev", "Seventy", 70,
                                'cutman', promotion_id=1),
        'at75':    inject_staff(conn, "Sev", "Five", 75,
                                'general_manager', promotion_id=1),
    }
    # Give each staff a contract so we can verify voiding.
    for key, sid in staff_ids.items():
        role = {
            'under65': 'commentator', 'at65': 'doctor',
            'at70': 'cutman', 'at75': 'general_manager',
        }[key]
        inject_staff_contract(conn, sid, promotion_id=1, role_type=role,
                              start_date='2026-01-01',
                              end_date='2027-12-31')

    # Verify setup.
    contracts_before = conn.execute(
        "SELECT COUNT(*) FROM contracts c JOIN staff_contracts sc "
        "ON sc.contract_id=c.contract_id WHERE c.status='active' "
        "AND sc.staff_id IN ({})".format(
            ",".join(str(s) for s in staff_ids.values())
        )
    ).fetchone()[0]
    r.check(case, "setup: 4 staff + 4 active contracts",
            contracts_before == 4,
            f"got={contracts_before}")

    # Stub RNG to force deterministic retirement outcomes:
    #   under65 (prob=0.0):  roll=0.99 → never retire
    #   at65   (prob=0.10): roll=0.05 → retire (0.05 < 0.10)
    #   at70   (prob=0.25): roll=0.05 → retire (0.05 < 0.25)
    #   at75   (prob=0.50): roll=0.99 → NOT retire (0.99 >= 0.50)
    # We patch random.Random in retirement_svc via monkey-patch.
    import services.retirement_svc as rsvc

    class _FakeRandom:
        """Yields a fixed sequence of values for deterministic tests.

        For `random()` (used by retirement_svc.check_staff_retirements
        for the dice roll), returns the next value in the fixed
        sequence — so retirement outcomes are deterministic.

        For all other RNG methods (choice, randint, uniform — used by
        the news subscriber generate_staff_retired_news to pick a
        headline/body variant), delegates to a real random.Random
        instance. This is fine because the news VARIETY isn't what
        we're testing — we just need it to not crash.
        """
        def __init__(self, values):
            self._values = list(values)
            self._idx = 0
            self._real = random.Random()

        def random(self):
            v = self._values[self._idx % len(self._values)]
            self._idx += 1
            return v

        def choice(self, seq):
            return self._real.choice(seq)

        def randint(self, a, b):
            return self._real.randint(a, b)

        def uniform(self, a, b):
            return self._real.uniform(a, b)

    # The order of staff rows is age ASC by default in SQLite without
    # an explicit ORDER BY, but the SQL is "WHERE age >= 65" with no
    # ORDER BY — so the order depends on the rowid (insertion order).
    # We injected at65, at70, at75 in that order, so the rowid order
    # is at65 → at70 → at75 (under65 is filtered out by age >= 65).
    # Roll values: [at65_roll, at70_roll, at75_roll]
    #
    # IMPORTANT: capture the REAL random.Random class BEFORE patching.
    # The _FakeRandom.__init__ uses random.Random() to seed its
    # internal delegate RNG; if we patched random.Random first, that
    # call would recurse infinitely through our own lambda.
    _RealRandom = random.Random

    class _FakeRandomWithDelegate(_FakeRandom):
        def __init__(self, values):
            self._values = list(values)
            self._idx = 0
            self._real = _RealRandom()

    rsvc.random.Random = lambda: _FakeRandomWithDelegate([0.05, 0.05, 0.99])
    try:
        retired = check_staff_retirements(conn, "2027-01-01")
    finally:
        rsvc.random.Random = _RealRandom

    r.check(case, "under-65 staff NOT in retirement candidate list",
            staff_ids['under65'] not in retired,
            f"retired={retired}")
    r.check(case, "age-65 staff retired (roll 0.05 < 0.10)",
            staff_ids['at65'] in retired,
            f"retired={retired}")
    r.check(case, "age-70 staff retired (roll 0.05 < 0.25)",
            staff_ids['at70'] in retired,
            f"retired={retired}")
    r.check(case, "age-75 staff NOT retired (roll 0.99 >= 0.50)",
            staff_ids['at75'] not in retired,
            f"retired={retired}")

    # Verify contract voiding — the 2 retired staff should have
    # status='terminated' contracts; the 2 non-retired should still
    # be 'active'.
    retired_contracts = conn.execute(
        "SELECT COUNT(*) FROM contracts c JOIN staff_contracts sc "
        "ON sc.contract_id=c.contract_id WHERE c.status='terminated' "
        "AND sc.staff_id IN (?, ?)",
        (staff_ids['at65'], staff_ids['at70']),
    ).fetchone()[0]
    r.check(case, "retired staff contracts voided (status='terminated')",
            retired_contracts == 2,
            f"got={retired_contracts} expected=2")
    active_contracts = conn.execute(
        "SELECT COUNT(*) FROM contracts c JOIN staff_contracts sc "
        "ON sc.contract_id=c.contract_id WHERE c.status='active' "
        "AND sc.staff_id IN (?, ?)",
        (staff_ids['under65'], staff_ids['at75']),
    ).fetchone()[0]
    r.check(case, "non-retired staff contracts still active",
            active_contracts == 2,
            f"got={active_contracts} expected=2")

    # Verify promotion_id was cleared on retired staff.
    promo_cleared = conn.execute(
        "SELECT COUNT(*) FROM staff WHERE promotion_id IS NULL "
        "AND staff_id IN (?, ?)",
        (staff_ids['at65'], staff_ids['at70']),
    ).fetchone()[0]
    r.check(case, "retired staff promotion_id=NULL (they leave)",
            promo_cleared == 2,
            f"got={promo_cleared} expected=2")

    # Verify news items were written for the retirements.
    # Per retired staff: 1 inline retirement news + 1 event-driven
    # retirement news (from generate_staff_retired_news subscriber) +
    # 1 regen news (from generate_staff_replacement, M2.3) = 3 items.
    # 2 retired staff × 3 items = 6 total staff-topic news items.
    news_count = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='staff' "
        "AND published_at='2027-01-01'"
    ).fetchone()[0]
    r.check(case, "retirement news items written (inline + event-driven + regen)",
            news_count == 6,
            f"got={news_count} expected=6 (2 staff × 3 items)")

    # ---- Event-bus wiring test ------------------------------------
    # Reset the bus + register only the news subscriber; verify it
    # fires on STAFF_RETIRED.
    reset_bus()
    import news
    news.register_subscribers()
    bus = get_bus()
    r.check(case, "STAFF_RETIRED subscriber registered",
            bus.subscriber_count(Events.STAFF_RETIRED) >= 1,
            f"got={bus.subscriber_count(Events.STAFF_RETIRED)}")

    # Publish a synthetic event + verify the news item was written.
    pre_count = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='staff'"
    ).fetchone()[0]
    bus.publish(conn, {
        'type': Events.STAFF_RETIRED,
        'staff_id': staff_ids['at75'],
        'role_type': 'general_manager',
        'promotion_id': 1,
        'current_date': '2027-01-01',
        'event_date': '2027-01-01',
    })
    conn.commit()
    post_count = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='staff'"
    ).fetchone()[0]
    r.check(case, "STAFF_RETIRED event fires generate_staff_retired_news",
            post_count == pre_count + 1,
            f"pre={pre_count} post={post_count}")

    # ---- Voice-compliance spot check (no raw numbers) -------------
    # Pull a staff retirement news item + verify the body doesn't
    # contain raw skill_level digits in the 0-100 range. (We can't
    # easily check "all digits" because the date contains digits —
    # we check the body text specifically.)
    row = conn.execute(
        "SELECT headline, body FROM news_items "
        "WHERE topic='staff' ORDER BY news_item_id DESC LIMIT 1"
    ).fetchone()
    if row:
        headline, body = row
        # The body should contain a voice phrase for skill.
        voice_phrases = ['world-class', 'established',
                         'promising', 'unproven']
        has_voice = any(p in body.lower() for p in voice_phrases)
        r.check(case, "news body uses voice phrase (no raw skill digit)",
                has_voice,
                f"body={body[:80]}...")
        # The body should NOT contain "rated 50" / "rated 75" etc.
        # (raw skill_level digit phrases).
        no_raw_skill = "rated 5" not in body and "rated 6" not in body \
            and "rated 7" not in body and "rated 8" not in body \
            and "rated 9" not in body
        r.check(case, "news body has NO raw skill_level digit",
                no_raw_skill,
                f"body={body[:80]}...")

    conn.close()


# ============================================================
# M2.3 — Staff regen (generate replacement + staff_regen_lineage)
# ============================================================

def test_m2_3_staff_regen(r):
    """M2.3: Replacement staff generated on retirement + lineage row."""
    case = "M2.3"
    print(f"\n{'=' * 72}")
    print(f"  {case} — Staff regen (replacement + staff_regen_lineage)")
    print(f"{'=' * 72}")

    from services.retirement_svc import (
        generate_staff_replacement,
        STAFF_REGEN_AGE_MIN, STAFF_REGEN_AGE_MAX,
        STAFF_REGEN_SKILL_DELTA, STAFF_REGEN_SKILL_MIN,
        STAFF_REGEN_SKILL_MAX,
    )

    # ---- Unit tests of the regen constants -------------------------
    r.check(case, "STAFF_REGEN_AGE_MIN == 30 (prime working years)",
            STAFF_REGEN_AGE_MIN == 30,
            f"got={STAFF_REGEN_AGE_MIN}")
    r.check(case, "STAFF_REGEN_AGE_MAX == 45",
            STAFF_REGEN_AGE_MAX == 45,
            f"got={STAFF_REGEN_AGE_MAX}")
    r.check(case, "STAFF_REGEN_SKILL_DELTA == 15 (±15 of retiring)",
            STAFF_REGEN_SKILL_DELTA == 15,
            f"got={STAFF_REGEN_SKILL_DELTA}")
    r.check(case, "STAFF_REGEN_SKILL_MIN == 10 (never below 'unproven')",
            STAFF_REGEN_SKILL_MIN == 10,
            f"got={STAFF_REGEN_SKILL_MIN}")
    r.check(case, "STAFF_REGEN_SKILL_MAX == 95 (never world-class fresh)",
            STAFF_REGEN_SKILL_MAX == 95,
            f"got={STAFF_REGEN_SKILL_MAX}")

    # ---- Integration test: regen on retirement --------------------
    build_fresh_db()
    conn = get_conn()
    retiring_id = inject_staff(conn, "Old", "Veteran", 70,
                                'general_manager', promotion_id=1,
                                skill_level=80)
    inject_staff_contract(conn, retiring_id, promotion_id=1,
                          role_type='general_manager',
                          start_date='2026-01-01',
                          end_date='2027-12-31')
    r.check(case, "setup: retiring GM injected (skill=80)",
            conn.execute(
                "SELECT skill_level FROM staff WHERE staff_id=?",
                (retiring_id,)
            ).fetchone()[0] == 80,
            f"retiring_id={retiring_id}")

    new_staff_id = generate_staff_replacement(
        conn,
        retiring_staff_id=retiring_id,
        role_type='general_manager',
        retiring_skill_level=80,
        retiring_promotion_id=1,
        current_date='2027-01-01',
    )
    conn.commit()
    r.check(case, "generate_staff_replacement returns a new staff_id",
            new_staff_id is not None and new_staff_id > 0,
            f"got={new_staff_id}")

    row = conn.execute(
        "SELECT first_name, last_name, age, role_type, "
        "specialty, promotion_id, gym_id, skill_level "
        "FROM staff WHERE staff_id=?",
        (new_staff_id,),
    ).fetchone()
    if row:
        fname, lname, age, role_type, specialty, promo_id, gym_id, skill = row
        r.check(case, "replacement role_type matches retiring (general_manager)",
                role_type == 'general_manager',
                f"got={role_type}")
        r.check(case, "replacement age in [30, 45]",
                STAFF_REGEN_AGE_MIN <= age <= STAFF_REGEN_AGE_MAX,
                f"got={age}")
        r.check(case, "replacement skill_level within ±15 of retiring (80)",
                65 <= skill <= 95,
                f"got={skill} (expected 65-95)")
        r.check(case, "replacement promotion_id=NULL (free agent)",
                promo_id is None,
                f"got={promo_id}")
        r.check(case, "replacement gym_id=NULL",
                gym_id is None,
                f"got={gym_id}")
        r.check(case, "replacement has a NEW name (not 'Old Veteran')",
                f"{fname} {lname}" != "Old Veteran",
                f"got={fname} {lname}")
    else:
        r.check(case, "replacement staff row exists", False,
                f"no row for staff_id={new_staff_id}")

    lineage = conn.execute(
        "SELECT retiring_staff_id, replacement_staff_id, role_type, "
        "regen_date FROM staff_regen_lineage "
        "WHERE retiring_staff_id=?",
        (retiring_id,),
    ).fetchone()
    r.check(case, "staff_regen_lineage row recorded",
            lineage is not None,
            f"got={lineage}")
    if lineage:
        r.check(case, "lineage role_type matches (general_manager)",
                lineage[2] == 'general_manager',
                f"got={lineage[2]}")
        r.check(case, "lineage replacement_staff_id matches new staff_id",
                lineage[1] == new_staff_id,
                f"got={lineage[1]} expected={new_staff_id}")
        r.check(case, "lineage regen_date == '2027-01-01'",
                lineage[3] == '2027-01-01',
                f"got={lineage[3]}")

    news_count = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='staff' "
        "AND headline LIKE '%enters the staff market%'"
    ).fetchone()[0]
    r.check(case, "regen news item written ('enters the staff market')",
            news_count >= 1,
            f"got={news_count}")

    # ---- Skill clamping test (retiring skill near edges) ---------
    bounds_ok = True
    for trial in range(20):
        sid = generate_staff_replacement(
            conn,
            retiring_staff_id=retiring_id,  # lineage UNIQUE skips dup
            role_type='doctor',
            retiring_skill_level=98,
            current_date='2027-01-01',
        )
        if sid is None:
            continue
        skill = conn.execute(
            "SELECT skill_level FROM staff WHERE staff_id=?", (sid,)
        ).fetchone()[0]
        if skill > STAFF_REGEN_SKILL_MAX:
            bounds_ok = False
            break
    r.check(case, "skill_level clamped to MAX=95 (high retiring skill)",
            bounds_ok,
            f"20 trials, all <= {STAFF_REGEN_SKILL_MAX}")

    bounds_ok_low = True
    for trial in range(20):
        sid = generate_staff_replacement(
            conn,
            retiring_staff_id=retiring_id,
            role_type='cutman',
            retiring_skill_level=5,
            current_date='2027-01-01',
        )
        if sid is None:
            continue
        skill = conn.execute(
            "SELECT skill_level FROM staff WHERE staff_id=?", (sid,)
        ).fetchone()[0]
        if skill < STAFF_REGEN_SKILL_MIN:
            bounds_ok_low = False
            break
    r.check(case, "skill_level clamped to MIN=10 (low retiring skill)",
            bounds_ok_low,
            f"20 trials, all >= {STAFF_REGEN_SKILL_MIN}")

    # ---- End-to-end: retirement triggers regen via annual tick ----
    build_fresh_db()
    conn = get_conn()
    old_gm = inject_staff(conn, "Grumpy", "Oldman", 70,
                          'general_manager', promotion_id=1,
                          skill_level=70)
    inject_staff_contract(conn, old_gm, promotion_id=1,
                          role_type='general_manager',
                          start_date='2026-01-01',
                          end_date='2027-12-31')
    import services.retirement_svc as rsvc
    _RealRandom = random.Random

    class _ForceRetireRandom:
        def __init__(self):
            self._real = _RealRandom()
        def random(self):
            return 0.01
        def choice(self, seq):
            return self._real.choice(seq)
        def randint(self, a, b):
            return self._real.randint(a, b)
        def uniform(self, a, b):
            return self._real.uniform(a, b)

    rsvc.random.Random = _ForceRetireRandom
    try:
        set_sim_date(conn, "2027-01-01")
        result = _check_staff_annual_lifecycle(conn, "2027-01-01")
    finally:
        rsvc.random.Random = _RealRandom
    conn.commit()

    r.check(case, "annual tick retired the 70yo GM",
            old_gm in result.get('retired', []),
            f"retired={result.get('retired')}")
    lineage = conn.execute(
        "SELECT replacement_staff_id FROM staff_regen_lineage "
        "WHERE retiring_staff_id=?", (old_gm,)
    ).fetchone()
    r.check(case, "annual tick triggered regen (lineage row written)",
            lineage is not None and lineage[0] is not None,
            f"lineage={lineage}")
    if lineage and lineage[0]:
        rep_row = conn.execute(
            "SELECT role_type, promotion_id, skill_level FROM staff "
            "WHERE staff_id=?", (lineage[0],)
        ).fetchone()
        if rep_row:
            r.check(case, "replacement is a free-agent GM (role_type match)",
                    rep_row[0] == 'general_manager' and rep_row[1] is None,
                    f"got role={rep_row[0]} promo={rep_row[1]}")
            r.check(case, "replacement skill in [55, 85] (±15 of 70)",
                    55 <= rep_row[2] <= 85,
                    f"got={rep_row[2]}")

    # ---- Staff_manager hook test (free-agent FA cycle) -----------
    from services.rival_ai.staff_manager import _try_hire_free_agent_staff
    if lineage and lineage[0]:
        fa_count_before = conn.execute(
            "SELECT COUNT(*) FROM staff WHERE promotion_id IS NULL "
            "AND role_type='general_manager'"
        ).fetchone()[0]
        r.check(case, "free-agent GM exists before rival AI hire attempt",
                fa_count_before >= 1,
                f"got={fa_count_before}")
        rng = random.Random()
        hired_id = _try_hire_free_agent_staff(
            conn, 2, 'general_manager', '2027-01-15', rng,
        )
        conn.commit()
        r.check(case, "_try_hire_free_agent_staff returns a staff_id",
                hired_id is not None,
                f"got={hired_id}")
        if hired_id:
            new_promo = conn.execute(
                "SELECT promotion_id FROM staff WHERE staff_id=?",
                (hired_id,)
            ).fetchone()[0]
            r.check(case, "FA staff assigned to promo 2 after hire",
                    new_promo == 2,
                    f"got={new_promo}")
            contract_count = conn.execute(
                "SELECT COUNT(*) FROM staff_contracts sc "
                "JOIN contracts c ON c.contract_id=sc.contract_id "
                "WHERE sc.staff_id=? AND c.status='active'",
                (hired_id,)
            ).fetchone()[0]
            r.check(case, "active staff_contract created for hired FA",
                    contract_count == 1,
                    f"got={contract_count}")

    conn.close()


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 72)
    print("Phase M2 — Staff Lifecycle test suite")
    print(f"  Test DB: {DB_PATH}")
    print(f"  (separate from world DB at data/cage_empire.db)")
    print("=" * 72)

    r = Results()

    # Reset the event bus so subscribers from prior test runs don't
    # leak into this one.
    reset_bus()

    # Register news subscribers (so news events fired by the
    # lifecycle are picked up — verifies event bus wiring).
    try:
        import news  # noqa: F401
        news.register_subscribers()
    except Exception:
        pass

    test_m2_1_staff_aging(r)
    test_m2_2_staff_retirement(r)
    test_m2_3_staff_regen(r)

    print()
    print("=" * 72)
    print(f"RESULT: {r.passed} PASS, {r.failed} FAIL, {r.skipped} SKIP")
    print("=" * 72)
    if r.failed > 0:
        print("\nFailures:")
        for case, name, detail in r.failures:
            print(f"  {case}  {name}  {detail}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
