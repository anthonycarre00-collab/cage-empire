#!/usr/bin/env python3
"""HW1.4 (Hardening Phase §HW1.4) — Financial state machine tests.

Verifies the 7-state lifecycle:
  HEALTHY → PRESSURED → STRUGGLING → CRISIS → BANKRUPT → REBUILDING → RECOVERING → HEALTHY

Per docs/Hardening_Phase.md §HW1.4:
  - HEALTHY → PRESSURED: cash < starting_budget × 0.20 for 2 consecutive months
  - PRESSURED → STRUGGLING: cash < starting_budget × 0.10 for 2 consecutive months
  - STRUGGLING → CRISIS: cash < 0 for 1 month
  - CRISIS → BANKRUPT: cash < 0 for 3 consecutive months (existing bankruptcy)
  - BANKRUPT → REBUILDING: existing bankruptcy recovery (sets financial_state)
  - REBUILDING → RECOVERING: rebuilding period ends (sets financial_state)
  - RECOVERING → HEALTHY: cash > starting_budget × 0.50
  - Each transition writes a voice-compliant news item (topic='finance')
  - Each transition has consequences:
      PRESSURED = -10% marketing spend on next scheduled event
      STRUGGLING = release 1 staff member
      CRISIS = sign_free_agent refuses new signings
      BANKRUPT = full bankruptcy failure (existing)
      REBUILDING = +1 rep/month if event ran (existing)
      RECOVERING = no consequence
      HEALTHY = no consequence

The script builds a fresh DB (dev seed — 5 fighters, 1 promo),
mutates the relevant rows in isolated sub-tests, and asserts the
expected behaviour. Pass = exit 0; Fail = exit 1.

Run from the project root:
    python3 scripts/test_financial_state_machine.py

Refs docs/Hardening_Phase.md §HW1.4, §CRITICAL #4.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test_hw1_4.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
os.environ["CAGE_EMPIRE_ALLOW_FRESH"] = "1"

sys.path.insert(0, str(SRC_DIR))


def build_fresh_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True, capture_output=True,
    )


class TestReport:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  PASS  {name}")
        else:
            self.failed += 1
            self.failures.append(name)
            print(f"  FAIL  {name}  {detail}")

    def summary(self):
        print()
        print("=" * 72)
        print(f"HW1.4 Financial State Machine Tests: "
              f"{self.passed} PASS, {self.failed} FAIL")
        if self.failures:
            print("Failed: " + ", ".join(self.failures))
        print("=" * 72)
        return 0 if self.failed == 0 else 1


# ----------------------------------------------------------- helpers
def _set_promo_state(conn, promo_id, cash, starting_budget,
                     financial_state='HEALTHY', is_rebuilding=0,
                     rebuilding_until_date=None):
    conn.execute(
        "UPDATE promotions SET current_cash=?, starting_budget=?, "
        "financial_state=?, is_rebuilding=?, rebuilding_until_date=?, "
        "ai_budget_state=NULL, updated_at=CURRENT_TIMESTAMP "
        "WHERE promotion_id=?",
        (cash, starting_budget, financial_state, is_rebuilding,
         rebuilding_until_date, promo_id),
    )
    conn.commit()


def _reset_counters(conn):
    """Clear the financial_state_counters + bankruptcy_warnings blobs."""
    conn.execute(
        "INSERT OR REPLACE INTO player_settings "
        "(setting_key, setting_value, updated_at) VALUES "
        "('financial_state_counters', '{}', CURRENT_TIMESTAMP), "
        "('bankruptcy_warnings', '{}', CURRENT_TIMESTAMP)"
    )
    conn.commit()


def _state(conn, promo_id):
    return conn.execute(
        "SELECT financial_state FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()[0]


# ----------------------------------------------------------- tests
def test_migration_added_column(report):
    """Verify the migration added the financial_state column with the
    CHECK constraint + the schema_version is 3.27.0."""
    print("\n[0] Migration + schema checks")
    conn = sqlite3.connect(str(DB_PATH))
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()[0]
    report.check("0a schema_version = 3.27.0",
                 sv == "3.27.0", f"got {sv}")
    mig = conn.execute(
        "SELECT migration_name FROM schema_migrations "
        "WHERE migration_name='v3_27_0_add_financial_state_column'"
    ).fetchone()
    report.check("0b v3.27.0 migration recorded",
                 mig is not None, f"got {mig}")
    # CHECK constraint enforces the 7 allowed values.
    try:
        conn.execute(
            "UPDATE promotions SET financial_state='INVALID' WHERE promotion_id=1"
        )
        report.check("0c CHECK rejects 'INVALID'", False,
                     "no IntegrityError raised")
    except sqlite3.IntegrityError:
        report.check("0c CHECK rejects 'INVALID'", True)
    # Default value is 'HEALTHY' for any promo that didn't match the
    # backfill criteria.
    fs = conn.execute(
        "SELECT financial_state FROM promotions WHERE promotion_id=1"
    ).fetchone()[0]
    report.check("0d default financial_state = 'HEALTHY'",
                 fs == 'HEALTHY', f"got {fs}")
    conn.close()


def test_healthy_to_pressured(report):
    """HEALTHY → PRESSURED: cash < 0.20 × starting_budget for 2 months."""
    print("\n[1] HEALTHY → PRESSURED (2 months below 0.20 × budget)")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()

    # Promo 2 — starting_budget=$10M, so 0.20 × budget = $2M.
    # Set cash to $1.5M (below $2M threshold).
    _set_promo_state(conn, 2, cash=1_500_000.0, starting_budget=10_000_000.0,
                     financial_state='HEALTHY')
    _reset_counters(conn)

    # Month 1: cash < $2M → pressured_months = 1, no transition yet.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("1a month 1: state still HEALTHY (no transition yet)",
                 _state(conn, 2) == 'HEALTHY',
                 f"got {_state(conn, 2)}")
    counters = reputation._load_financial_state_counters(conn)
    report.check("1b month 1: pressured_months = 1",
                 counters.get('2', {}).get('pressured_months') == 1,
                 f"got {counters.get('2')}")

    # Month 2: cash still < $2M → pressured_months = 2 → transition.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("1c month 2: state = PRESSURED",
                 _state(conn, 2) == 'PRESSURED',
                 f"got {_state(conn, 2)}")
    # A news item was written.
    news_n = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id=2 "
        "AND topic='finance' AND headline LIKE '%squeeze%'"
    ).fetchone()[0]
    report.check("1d PRESSURED news item written",
                 news_n >= 1, f"got {news_n}")
    conn.close()


def test_pressured_to_struggling(report):
    """PRESSURED → STRUGGLING: cash < 0.10 × starting_budget for 2 months."""
    print("\n[2] PRESSURED → STRUGGLING (2 months below 0.10 × budget)")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()

    # Promo 2 — starting_budget=$10M, 0.10 × budget = $1M.
    # Set cash to $500K (below $1M threshold).
    _set_promo_state(conn, 2, cash=500_000.0, starting_budget=10_000_000.0,
                     financial_state='PRESSURED')
    _reset_counters(conn)

    # Month 1.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("2a month 1: state still PRESSURED",
                 _state(conn, 2) == 'PRESSURED',
                 f"got {_state(conn, 2)}")

    # Month 2: transition.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("2b month 2: state = STRUGGLING",
                 _state(conn, 2) == 'STRUGGLING',
                 f"got {_state(conn, 2)}")
    # News item written.
    news_n = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id=2 "
        "AND topic='finance' AND headline LIKE '%slashes%'"
    ).fetchone()[0]
    report.check("2c STRUGGLING news item written",
                 news_n >= 1, f"got {news_n}")
    conn.close()


def test_struggling_to_crisis(report):
    """STRUGGLING → CRISIS: cash < 0 for 1 month."""
    print("\n[3] STRUGGLING → CRISIS (cash < 0)")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()

    # Promo 2 — set cash to -$1 (negative).
    _set_promo_state(conn, 2, cash=-1.0, starting_budget=10_000_000.0,
                     financial_state='STRUGGLING')
    _reset_counters(conn)

    # 1 month of negative cash → immediate transition.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("3a state = CRISIS",
                 _state(conn, 2) == 'CRISIS',
                 f"got {_state(conn, 2)}")
    news_n = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id=2 "
        "AND topic='finance' AND headline LIKE '%crisis%'"
    ).fetchone()[0]
    report.check("3b CRISIS news item written",
                 news_n >= 1, f"got {news_n}")
    conn.close()


def test_crisis_blocks_sign_free_agent(report):
    """CRISIS state blocks sign_free_agent in app_web.py."""
    print("\n[4] CRISIS blocks sign_free_agent")
    build_fresh_db()
    from app_web import Api
    api = Api()
    conn = api.conn
    # Set player promo + financial_state='CRISIS'.
    conn.execute(
        "INSERT OR REPLACE INTO player_settings (setting_key, setting_value, updated_at) "
        "VALUES ('player_promotion_id', '1', CURRENT_TIMESTAMP)"
    )
    _set_promo_state(conn, 1, cash=-1.0, starting_budget=80_000_000.0,
                     financial_state='CRISIS')
    # Find a free agent.
    fa_row = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id IS NULL LIMIT 1"
    ).fetchone()
    if not fa_row:
        conn.execute("UPDATE fighters SET current_promotion_id=NULL WHERE fighter_id=3")
        conn.commit()
        fa_row = (3,)
    fa_id = fa_row[0]
    res = api.sign_free_agent(fa_id, salary=50000, signing_bonus=0)
    report.check("4a CRISIS blocks sign_free_agent",
                 res.get("ok") is False and
                 res.get("blocked_by_crisis") is True,
                 f"got {res}")
    report.check("4b error mentions 'CRISIS'",
                 "CRISIS" in (res.get("error") or ""),
                 f"got {res.get('error')!r}")
    conn.close()


def test_pressured_marketing_consequence(report):
    """PRESSURED transition applies -10% marketing to next scheduled event."""
    print("\n[5] PRESSURED consequence: -10% marketing on next event")
    build_fresh_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()
    # Promo 1 — set marketing_spend on its seeded event, then trigger PRESSURED.
    # First update the seeded event's marketing_spend to a known value ($100K).
    # SQLite doesn't support ORDER BY in UPDATE — use a subquery to pick
    # the lowest event_id matching the WHERE clause.
    conn.execute(
        "UPDATE events SET marketing_spend=100000 WHERE event_id = "
        "(SELECT event_id FROM events WHERE promotion_id=1 "
        "AND status='scheduled' ORDER BY event_id ASC LIMIT 1)"
    )
    conn.commit()
    # Set cash below 0.20 × $80M = $16M. Use $10M.
    _set_promo_state(conn, 1, cash=10_000_000.0, starting_budget=80_000_000.0,
                     financial_state='HEALTHY')
    _reset_counters(conn)
    # Month 1.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    # Month 2: transition to PRESSURED → -10% marketing applied.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("5a state = PRESSURED",
                 _state(conn, 1) == 'PRESSURED',
                 f"got {_state(conn, 1)}")
    # The next scheduled event's marketing_spend should be $90K now.
    ms = conn.execute(
        "SELECT marketing_spend FROM events WHERE promotion_id=1 "
        "AND status='scheduled' ORDER BY event_id ASC LIMIT 1"
    ).fetchone()
    ms_val = ms[0] if ms else None
    report.check("5b marketing_spend = 90000 (was 100000 × 0.9)",
                 ms_val == 90000,
                 f"got {ms_val}")
    conn.close()


def test_struggling_staff_release_consequence(report):
    """STRUGGLING transition releases 1 staff member (lowest-skill)."""
    print("\n[6] STRUGGLING consequence: release 1 staff member")
    build_fresh_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()
    # Promo 1 — give it an active staff contract so _release_one_staff has work.
    # First find/create a staff row.
    staff_row = conn.execute(
        "SELECT staff_id FROM staff LIMIT 1"
    ).fetchone()
    if not staff_row:
        # Create a placeholder staff row.
        sid = conn.execute(
            "INSERT INTO staff (first_name, last_name, role_type, skill_level) "
            "VALUES ('Test', 'Coach', 'coach', 50)"
        ).lastrowid
    else:
        sid = staff_row[0]
        # Make sure skill_level is set.
        conn.execute(
            "UPDATE staff SET skill_level=50, promotion_id=1 WHERE staff_id=?",
            (sid,),
        )
    # Insert an active staff contract. staff_contracts.contract_role is
    # NOT NULL — set to 'coach' (any value works for this test).
    cid = conn.execute(
        "INSERT INTO contracts (promotion_id, contract_target_type, "
        "salary, status, start_date, end_date) "
        "VALUES (1, 'staff', 50000, 'active', '2026-01-01', '2027-12-31')"
    ).lastrowid
    conn.execute(
        "INSERT INTO staff_contracts (staff_id, contract_id, contract_role) "
        "VALUES (?, ?, 'coach')",
        (sid, cid),
    )
    conn.commit()
    n_staff_before = conn.execute(
        "SELECT COUNT(*) FROM contracts WHERE promotion_id=1 "
        "AND contract_target_type='staff' AND status='active'"
    ).fetchone()[0]
    report.check("6a setup: promo 1 has >= 1 active staff contract",
                 n_staff_before >= 1, f"got {n_staff_before}")

    # Trigger STRUGGLING: set cash < 0.10 × $80M = $8M, financial_state=PRESSURED.
    _set_promo_state(conn, 1, cash=5_000_000.0, starting_budget=80_000_000.0,
                     financial_state='PRESSURED')
    _reset_counters(conn)
    # Month 1.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    # Month 2: transition to STRUGGLING → release 1 staff.
    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("6b state = STRUGGLING",
                 _state(conn, 1) == 'STRUGGLING',
                 f"got {_state(conn, 1)}")
    n_staff_after = conn.execute(
        "SELECT COUNT(*) FROM contracts WHERE promotion_id=1 "
        "AND contract_target_type='staff' AND status='active'"
    ).fetchone()[0]
    report.check("6c 1 staff contract terminated",
                 n_staff_after == n_staff_before - 1,
                 f"before={n_staff_before} after={n_staff_after}")
    # News item written for the release.
    news_n = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id=1 "
        "AND topic='release' AND headline LIKE '%releases%'"
    ).fetchone()[0]
    report.check("6d 'release' news item written",
                 news_n >= 1, f"got {news_n}")
    conn.close()


def test_crisis_to_bankrupt_sets_rebuilding(report):
    """CRISIS → BANKRUPT → REBUILDING: _fire_bankruptcy_failure sets
    financial_state='REBUILDING'."""
    print("\n[7] CRISIS → BANKRUPT → REBUILDING (3 months below 0)")
    build_fresh_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()

    # Promo 2 — set CRISIS state, cash = -$1, starting_budget=$10M.
    _set_promo_state(conn, 2, cash=-1.0, starting_budget=10_000_000.0,
                     financial_state='CRISIS')
    _reset_counters(conn)
    # Add a fighter + staff contract so the bankruptcy releases have work.
    fighters = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=2 LIMIT 1"
    ).fetchall()
    if not fighters:
        conn.execute("UPDATE fighters SET current_promotion_id=2 WHERE fighter_id=3")
        conn.commit()
    fid = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=2 LIMIT 1"
    ).fetchone()[0]
    cid = conn.execute(
        "INSERT INTO contracts (promotion_id, contract_target_type, salary, "
        "status, start_date, end_date) VALUES "
        "(2, 'fighter', 500000, 'active', '2026-01-01', '2027-12-31')"
    ).lastrowid
    conn.execute(
        "INSERT INTO fighter_contracts (contract_id, fighter_id) VALUES (?, ?)",
        (cid, fid),
    )
    conn.commit()

    # Month 1: counter 0→1, state stays CRISIS.
    reputation._check_financial_state_transitions(conn)
    reputation._check_bankruptcy_failure(conn)
    conn.commit()
    report.check("7a month 1: state = CRISIS",
                 _state(conn, 2) == 'CRISIS',
                 f"got {_state(conn, 2)}")
    # Month 2.
    reputation._check_financial_state_transitions(conn)
    reputation._check_bankruptcy_failure(conn)
    conn.commit()
    report.check("7b month 2: state = CRISIS",
                 _state(conn, 2) == 'CRISIS',
                 f"got {_state(conn, 2)}")
    # Month 3: BANKRUPT fires → REBUILDING.
    reputation._check_financial_state_transitions(conn)
    reputation._check_bankruptcy_failure(conn)
    conn.commit()
    report.check("7c month 3: state = REBUILDING",
                 _state(conn, 2) == 'REBUILDING',
                 f"got {_state(conn, 2)}")
    # Cash was reset to starting_budget × 0.50 = $5M.
    cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=2"
    ).fetchone()[0]
    report.check("7d cash reset to $5M (starting × 0.50)",
                 abs(cash - 5_000_000.0) < 1.0,
                 f"got {cash}")
    # is_rebuilding = 1.
    ir = conn.execute(
        "SELECT is_rebuilding FROM promotions WHERE promotion_id=2"
    ).fetchone()[0]
    report.check("7e is_rebuilding = 1",
                 ir == 1, f"got {ir}")
    conn.close()


def test_recovering_to_healthy(report):
    """RECOVERING → HEALTHY: cash > 0.50 × starting_budget."""
    print("\n[8] RECOVERING → HEALTHY (cash > 0.50 × budget)")
    build_fresh_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()

    # Promo 2 — set RECOVERING state, cash above 0.50 × $10M = $5M.
    _set_promo_state(conn, 2, cash=6_000_000.0, starting_budget=10_000_000.0,
                     financial_state='RECOVERING')
    _reset_counters(conn)

    reputation._check_financial_state_transitions(conn)
    conn.commit()
    report.check("8a state = HEALTHY",
                 _state(conn, 2) == 'HEALTHY',
                 f"got {_state(conn, 2)}")
    news_n = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE promotion_id=2 "
        "AND topic='finance' AND headline LIKE '%health%'"
    ).fetchone()[0]
    report.check("8b HEALTHY news item written",
                 news_n >= 1, f"got {news_n}")
    conn.close()


def main():
    print("=" * 72)
    print("HW1.4 — Financial State Machine Tests")
    print("=" * 72)
    build_fresh_db()
    report = TestReport()
    for fn in (
        test_migration_added_column,
        test_healthy_to_pressured,
        test_pressured_to_struggling,
        test_struggling_to_crisis,
        test_crisis_blocks_sign_free_agent,
        test_pressured_marketing_consequence,
        test_struggling_staff_release_consequence,
        test_crisis_to_bankrupt_sets_rebuilding,
        test_recovering_to_healthy,
    ):
        try:
            print()
            fn(report)
        except Exception as e:
            report.check(f"{fn.__name__}: no exception", False,
                         f"{type(e).__name__}: {e}")
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
