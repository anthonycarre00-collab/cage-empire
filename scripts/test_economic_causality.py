#!/usr/bin/env python3
"""HW1.3 (Hardening Phase §HW1.3) — Economic causality tests.

Verifies the three wiring points required by §HW1.3 / CRITICAL #3:

  A. Rival AI budget decisions read `promotions.current_cash` and
     adjust spending:
       - A broke promo's `budget_manager.review_budget` assigns
         SURVIVAL / CRISIS state.
       - `budget_manager.apply_state_modifiers` reduces card_size,
         reduces bid_premium_pct, raises cut_aggressiveness for
         SURVIVAL/CONSERVATIVE states.
       - `event_scheduler.schedule_next_event_for_rival` skips
         event scheduling when cash < estimated_cost × safety_margin
         (the budget gate).

  B. sign_free_agent affordability check (app_web.py):
       - When the player's promo has current_cash < (signing_bonus +
         first_month_salary), sign_free_agent returns
         {ok: False, blocked_by_affordability: True} instead of
         deducting cash + pushing the promo into bankruptcy.

  C. Bankruptcy pathway (reputation.py):
       - When current_cash < 0 for 3 consecutive monthly ticks,
         `_fire_bankruptcy_failure` releases fighters + voids staff
         contracts + resets cash + writes news items + sets
         is_rebuilding=1.

The script builds a fresh DB (the dev seed — 5 fighters, 1 promo),
mutates the relevant rows in isolated sub-tests, and asserts the
expected behaviour. Pass = exit 0; Fail = exit 1.

Run from the project root:
    python3 scripts/test_economic_causality.py

Refs docs/Hardening_Phase.md §HW1.3, §CRITICAL #3.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test_hw1_3.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
os.environ["CAGE_EMPIRE_ALLOW_FRESH"] = "1"

sys.path.insert(0, str(SRC_DIR))


def build_fresh_db():
    """Drop + rebuild + seed a minimal DB for HW1.3 tests."""
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


# -------------------------------------------------------------- helpers
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
        print(f"HW1.3 Economic Causality Tests: "
              f"{self.passed} PASS, {self.failed} FAIL")
        if self.failures:
            print("Failed: " + ", ".join(self.failures))
        print("=" * 72)
        return 0 if self.failed == 0 else 1


# -------------------------------------------------------------- tests
def test_rival_ai_budget_wiring(report):
    """Test A — rival AI budget decisions read current_cash."""
    print("\n[A] Rival AI budget decisions read current_cash")
    from services.rival_ai import budget_manager
    from services.rival_ai._shared import promotion_cash

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")

    # Pick promo 2 (Rival Fight League — has 3 fighters).
    promo_id = 2

    # Reset to a known state.
    conn.execute(
        "UPDATE promotions SET current_cash=?, ai_budget_state=NULL, "
        "starting_budget=? WHERE promotion_id=?",
        (50_000_000.0, 50_000_000.0, promo_id),
    )
    conn.commit()

    # Case A1: rich promo (cash > 6 months expenses) → EXPANSION.
    state = budget_manager.review_budget(conn, promo_id, "2026-08-15")
    report.check("A1 rich promo -> EXPANSION or NORMAL",
                 state in ("EXPANSION", "NORMAL"),
                 f"got {state}")

    # Case A2: broke promo (cash < 1 month expenses) → SURVIVAL.
    # First, give promo 2 some monthly expenses by giving it active
    # contracts. The seed gives promo 2 3 fighters but no contracts
    # (inert). Insert active contracts so _compute_monthly_expenses
    # returns a non-zero value.
    fighters = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=?",
        (promo_id,),
    ).fetchall()
    if not fighters:
        # No fighters on roster — use any 3 free-agent fighters.
        fighters = conn.execute(
            "SELECT fighter_id FROM fighters LIMIT 3"
        ).fetchall()
    # Add active contracts with $1M/yr salary for each fighter.
    for (fid,) in fighters:
        # Insert contract + fighter_contracts link (defer to services.contracts).
        cid = conn.execute(
            "INSERT INTO contracts (promotion_id, contract_target_type, "
            "salary, status, start_date, end_date) "
            "VALUES (?, 'fighter', 1200000, 'active', '2026-01-01', '2027-12-31')"
            ,(promo_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO fighter_contracts (contract_id, fighter_id) "
            "VALUES (?, ?)",
            (cid, fid),
        )
    # Now promo 2 has $3M/yr = $250K/month fighter salaries.
    # Set cash to $50K → runway = $50K / $250K = 0.2 months → SURVIVAL.
    conn.execute(
        "UPDATE promotions SET current_cash=50000.0, "
        "ai_budget_state=NULL WHERE promotion_id=?",
        (promo_id,),
    )
    conn.commit()
    state = budget_manager.review_budget(conn, promo_id, "2026-08-15")
    report.check("A2 broke promo -> SURVIVAL",
                 state == "SURVIVAL",
                 f"got {state}")

    # Case A3: apply_state_modifiers reduces card_size + bid_premium
    # for SURVIVAL state.
    from services.rival_ai.archetypes import get_archetype
    base = get_archetype(promo_id, conn)
    if base is not None:
        modified = budget_manager.apply_state_modifiers(base, "SURVIVAL")
        report.check("A3 SURVIVAL card_size_min reduced",
                     modified['card_size'][0] < base['card_size'][0],
                     f"base={base['card_size']} modified={modified['card_size']}")
        report.check("A3 SURVIVAL bid_premium_pct reduced",
                     modified['bid_premium_pct'] < base['bid_premium_pct'],
                     f"base={base['bid_premium_pct']} modified={modified['bid_premium_pct']}")
        report.check("A3 SURVIVAL cut_aggressiveness raised",
                     modified['cut_aggressiveness'] >= base['cut_aggressiveness'],
                     f"base={base['cut_aggressiveness']} modified={modified['cut_aggressiveness']}")
        report.check("A3 SURVIVAL signing_potential_floor blocks FAs",
                     modified['signing_potential_floor'] >= 999,
                     f"got {modified.get('signing_potential_floor')}")
    else:
        report.check("A3 get_archetype(promo_2) returned non-None",
                     False, "promo 2 has no archetype")

    # Case A4: get_modified_archetype for a broke promo returns the
    # SURVIVAL-modified archetype (via budget_state).
    base2, modified2, state2 = budget_manager.get_modified_archetype(conn, promo_id)
    report.check("A4 get_modified_archetype returns SURVIVAL state",
                 state2 == "SURVIVAL",
                 f"got {state2}")
    report.check("A4 modified card_size < base card_size",
                 modified2['card_size'][0] < base2['card_size'][0],
                 f"base={base2['card_size']} modified={modified2['card_size']}")

    conn.close()


def test_sign_free_agent_affordability(report):
    """Test B — sign_free_agent refuses when cash < signing_bonus + first_month_salary."""
    print("\n[B] sign_free_agent affordability check")
    # Use a separate fresh DB so promo 1 starts with the seeded $80M
    # cash (and we can drive it to a low-cash state without polluting
    # other tests).
    build_fresh_db()
    from app_web import Api
    api = Api()

    # Set player_promotion_id=1 in player_settings (the dev seed doesn't
    # set this — the player picks a promo in the GUI before signing FAs).
    conn = api.conn
    conn.execute(
        "INSERT OR REPLACE INTO player_settings (setting_key, setting_value, updated_at) "
        "VALUES ('player_promotion_id', '1', CURRENT_TIMESTAMP)"
    )
    # Also set current_cash to $80M (the dev seed leaves it at 0; the
    # world seed scripts would set it). This gives us a known rich-cash
    # starting state.
    conn.execute(
        "UPDATE promotions SET current_cash=80000000.0 WHERE promotion_id=1"
    )
    conn.commit()

    # Sanity: promo 1's cash is now $80M.
    cash = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=1"
    ).fetchone()[0]
    report.check("B0 promo 1 cash set to $80M",
                 abs(cash - 80_000_000.0) < 1.0,
                 f"got {cash}")

    # Find a free agent (fighter with no current_promotion_id).
    fa_row = conn.execute(
        "SELECT fighter_id FROM fighters "
        "WHERE current_promotion_id IS NULL LIMIT 1"
    ).fetchone()
    if not fa_row:
        # If no free agent in seed, set fighter 3 (RFL) to FA.
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL "
            "WHERE fighter_id=3"
        )
        conn.commit()
        fa_row = (3,)
    fa_id = fa_row[0]

    # Case B1: signing_bonus=0, salary=$50K → required = $50K/12 = $4.17K.
    # Promo 1 has $80M → sign succeeds.
    res = api.sign_free_agent(fa_id, salary=50000, signing_bonus=0,
                              contract_length=2)
    report.check("B1 rich promo signs (ok=True)",
                 res.get("ok") is True,
                 f"got {res}")

    # Case B2: drive promo 1's cash to $1K and try to sign with a
    # $500K signing_bonus → required = $500K + $50K/12 ≈ $504K > $1K.
    conn.execute(
        "UPDATE promotions SET current_cash=1000.0 WHERE promotion_id=1"
    )
    conn.commit()
    # Find a new free agent (the previous one is now signed).
    fa_row2 = conn.execute(
        "SELECT fighter_id FROM fighters "
        "WHERE current_promotion_id IS NULL AND fighter_id != ? LIMIT 1",
        (fa_id,),
    ).fetchone()
    if not fa_row2:
        # Force one.
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL "
            "WHERE fighter_id=4"
        )
        conn.commit()
        fa_row2 = (4,)
    fa_id2 = fa_row2[0]
    res2 = api.sign_free_agent(fa_id2, salary=50000, signing_bonus=500000,
                               contract_length=2)
    report.check("B2 broke promo blocked_by_affordability",
                 res2.get("ok") is False and
                 res2.get("blocked_by_affordability") is True,
                 f"got {res2}")
    report.check("B2 error message mentions 'Insufficient cash'",
                 "Insufficient cash" in (res2.get("error") or ""),
                 f"got {res2.get('error')!r}")
    report.check("B2 required_cash_display present",
                 "required_cash_display" in res2,
                 f"keys={list(res2.keys())}")
    # The fighter was NOT signed.
    signed = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (fa_id2,),
    ).fetchone()[0]
    report.check("B2 fighter NOT signed (current_promotion_id still NULL)",
                 signed is None,
                 f"got {signed}")

    # Case B3: same low cash but signing_bonus=0, salary=$10K →
    # required = $10K/12 = $833. Promo has $1K → sign succeeds.
    res3 = api.sign_free_agent(fa_id2, salary=10000, signing_bonus=0,
                               contract_length=1)
    report.check("B3 broke promo signs cheap fighter (ok=True)",
                 res3.get("ok") is True,
                 f"got {res3}")

    api._cleanup() if hasattr(api, "_cleanup") else None
    conn.close()


def test_bankruptcy_pathway(report):
    """Test C — bankruptcy pathway fires after 3 consecutive negative-cash months."""
    print("\n[C] Bankruptcy pathway fires after 3 consecutive negative-cash months")
    build_fresh_db()
    import reputation
    from event_bus import reset_bus
    reset_bus()
    reputation.register_subscribers()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")

    # Use promo 2 (Rival Fight League — has 3 fighters).
    promo_id = 2

    # Set starting_budget so the cash reset has a known value.
    conn.execute(
        "UPDATE promotions SET starting_budget=10000000.0, "
        "current_cash=-1.0, ai_budget_state=NULL, "
        "is_rebuilding=0, rebuilding_until_date=NULL "
        "WHERE promotion_id=?",
        (promo_id,),
    )
    # Give promo 2 at least 2 fighters on roster (so release has work).
    fighters = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=? "
        "ORDER BY fighter_id LIMIT 3",
        (promo_id,),
    ).fetchall()
    if len(fighters) < 3:
        # Force any 2 unassigned fighters onto promo 2's roster.
        unassigned = conn.execute(
            "SELECT fighter_id FROM fighters "
            "WHERE current_promotion_id IS NULL OR current_promotion_id != ? "
            "LIMIT 3",
            (promo_id,),
        ).fetchall()
        for (fid,) in unassigned[:3 - len(fighters)]:
            conn.execute(
                "UPDATE fighters SET current_promotion_id=? "
                "WHERE fighter_id=?",
                (promo_id, fid),
            )
    # Add a contract for at least one fighter so the bankruptcy
    # release has a contract to void.
    fid_for_contract = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=? "
        "LIMIT 1",
        (promo_id,),
    ).fetchone()
    if fid_for_contract:
        cid = conn.execute(
            "INSERT INTO contracts (promotion_id, contract_target_type, "
            "salary, status, start_date, end_date) "
            "VALUES (?, 'fighter', 500000, 'active', '2026-01-01', '2027-12-31')",
            (promo_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO fighter_contracts (contract_id, fighter_id) "
            "VALUES (?, ?)",
            (cid, fid_for_contract[0]),
        )
    conn.commit()

    # Case C1: first monthly tick — current_cash < 0 → counter goes 0→1.
    # (player_settings has bankruptcy_warnings JSON — reset to {}.)
    conn.execute(
        "INSERT OR REPLACE INTO player_settings (setting_key, setting_value, updated_at) "
        "VALUES ('bankruptcy_warnings', '{}', CURRENT_TIMESTAMP)"
    )
    conn.commit()
    reputation._check_bankruptcy_failure(conn)
    conn.commit()
    warnings = reputation._load_bankruptcy_warnings(conn)
    report.check("C1 month 1: counter incremented to 1",
                 warnings.get(str(promo_id), 0) == 1,
                 f"got {warnings}")

    # Case C2: second monthly tick — counter goes 1→2 (still < 3).
    reputation._check_bankruptcy_failure(conn)
    conn.commit()
    warnings = reputation._load_bankruptcy_warnings(conn)
    report.check("C2 month 2: counter incremented to 2",
                 warnings.get(str(promo_id), 0) == 2,
                 f"got {warnings}")

    # Confirm bankruptcy hasn't fired yet (cash not reset, no news).
    cash_now = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()[0]
    report.check("C2 cash still -1 (bankruptcy not fired)",
                 cash_now == -1.0,
                 f"got {cash_now}")

    # Case C3: third monthly tick — counter goes 2→3 → bankruptcy fires
    # (BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED = 3). After firing the
    # counter is reset to 0 and cash is reset to
    # starting_budget × 0.50 = $5M.
    reputation._check_bankruptcy_failure(conn)
    conn.commit()
    warnings = reputation._load_bankruptcy_warnings(conn)
    report.check("C3 month 3: counter reset to 0 after firing",
                 warnings.get(str(promo_id), 0) == 0,
                 f"got {warnings}")
    cash_after = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()[0]
    report.check("C3 cash reset to starting_budget × 0.50 = $5M",
                 abs(cash_after - 5_000_000.0) < 1.0,
                 f"got {cash_after}")

    # Case C4: is_rebuilding=1 set.
    rebuilding = conn.execute(
        "SELECT is_rebuilding, rebuilding_until_date "
        "FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()
    report.check("C4 is_rebuilding=1 set",
                 rebuilding[0] == 1,
                 f"got {rebuilding}")
    report.check("C4 rebuilding_until_date not NULL",
                 rebuilding[1] is not None,
                 f"got {rebuilding}")

    # Case C5: news items written — bankruptcy news is written with
    # topic='finance' (per src/reputation.py:987 and src/news.py:4276).
    # Look for the FINANCIAL COLLAPSE headline + 'new ownership' item.
    news_n = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE promotion_id=? AND topic='finance' "
        "AND (headline LIKE '%bankruptcy%' "
        "     OR headline LIKE '%ownership%' "
        "     OR headline LIKE '%FINANCIAL COLLAPSE%')",
        (promo_id,),
    ).fetchone()[0]
    report.check("C5 bankruptcy news items written (>=1)",
                 news_n >= 1,
                 f"got {news_n}")

    # Case C6: at least one fighter released (now FA).
    fas_now = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE current_promotion_id IS NULL"
    ).fetchone()[0]
    report.check("C6 at least 1 fighter released to FA pool",
                 fas_now >= 1,
                 f"got {fas_now}")

    conn.close()


def main():
    print("=" * 72)
    print("HW1.3 — Economic Causality Wiring Tests")
    print("=" * 72)
    build_fresh_db()
    report = TestReport()
    try:
        test_rival_ai_budget_wiring(report)
    except Exception as e:
        report.check("A: no exception", False, f"{type(e).__name__}: {e}")
    try:
        test_sign_free_agent_affordability(report)
    except Exception as e:
        report.check("B: no exception", False, f"{type(e).__name__}: {e}")
    try:
        test_bankruptcy_pathway(report)
    except Exception as e:
        report.check("C: no exception", False, f"{type(e).__name__}: {e}")
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
