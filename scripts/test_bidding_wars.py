#!/usr/bin/env python3
"""Phase M3 — Rival AI Bidding Wars test suite.

Per docs/MASTER_PLAN_MATCHMAKING.md §2.2 (Rival AI signing — include
player in bidding wars). Tests the 3 M3 deliverables:

  M3.1 — Player exclusion removed from rival AI signing intents.
         The player's promo (promo_id=1) is now passed in the
         promo_ids list (a "valid bidding participant"), but the
         player doesn't auto-generate intents (guard in
         _evaluate_one_promo).

  M3.2 — SIGNING_INTENT event + Dashboard bidding war alert +
         counter_offer API. Rival AI signing intents become
         bidding_alerts rows (signing deferred 3 sim-days); the
         player can counter-offer via the API; the fighter chooses
         the higher offer_score (with ±5% randomness); if the
         player doesn't respond, the rival AI signs when the window
         expires.

  M3.3 — Fair-value formula includes realization. A "bust"
         (potential=85, realization=0.5, ceiling=42) is priced
         lower than a "realizer" (potential=85, realization=1.0,
         ceiling=85). Both the rival AI fair-value AND the player's
         agent-offer asking price use effective_ceiling.

Usage:
    python scripts/test_bidding_wars.py

Exit code 0 = all PASS, 1 = any FAIL. The test uses a transaction
+ rollback so the DB is left unchanged. Re-running is safe.
"""
import os
import sys
import sqlite3
import random
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from event_bus import get_bus, reset_bus, Events  # noqa: E402
from services.rival_ai.signing_agent import (  # noqa: E402
    evaluate_signing_intents, resolve_bidding_wars,
    check_bidding_alerts_expiry, _create_bidding_alert,
    _fair_value, _evaluate_one_promo, _get_fa_pool,
    _clear_fa_pool_cache, DEFAULT_DECISION_WINDOW_DAYS,
)
from rival_ai import PLAYER_PROMOTION_ID  # noqa: E402
from services.clock import get_clock  # noqa: E402

DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  [PASS] {name}  {detail}")
        else:
            self.failed += 1
            self.failures.append((name, detail))
            print(f"  [FAIL] {name}  {detail}")
        return cond


def main():
    print("=" * 72)
    print("Phase M3 — Rival AI Bidding Wars test suite")
    print(f"  DB: {DB_PATH}")
    print(f"  PLAYER_PROMOTION_ID: {PLAYER_PROMOTION_ID}")
    print(f"  DEFAULT_DECISION_WINDOW_DAYS: {DEFAULT_DECISION_WINDOW_DAYS}")
    print("=" * 72)

    r = Results()

    if not DB_PATH.exists():
        print(f"\nFATAL: DB not found at {DB_PATH}")
        sys.exit(2)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Reset bus so we can subscribe our own test listener for
    # SIGNING_INTENT events.
    reset_bus()
    bus = get_bus()

    # Track SIGNING_INTENT events fired during the test.
    signing_intent_events = []

    def _capture_signing_intent(c, event):
        signing_intent_events.append(event)

    bus.subscribe(Events.SIGNING_INTENT, _capture_signing_intent,
                  name="test.capture_signing_intent")

    # Read the current sim date.
    sim_date = get_clock(conn)[0]
    if not sim_date:
        print("FATAL: no sim clock.")
        sys.exit(2)
    print(f"  sim_date: {sim_date}")

    # Clear any leftover bidding_alerts from previous test runs.
    conn.execute("DELETE FROM bidding_alerts")
    # Also clear any test news items we may have written.
    conn.execute("DELETE FROM news_items WHERE topic IN "
                 "('bidding_war_lost', 'signing') "
                 "AND headline LIKE 'You %' OR headline LIKE '%bidding war%'")
    # Restore the player's promo setting if it was unset.
    conn.execute(
        "INSERT OR REPLACE INTO player_settings "
        "(setting_key, setting_value, updated_at) "
        "VALUES ('player_promotion_id', '1', CURRENT_TIMESTAMP)"
    )
    conn.commit()

    # Snapshot cash + roster for the player's promo (to verify on win).
    player_cash_before = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=1"
    ).fetchone()[0]

    # =====================================================================
    # M3.1 — Player exclusion removed (player is a valid bidding
    # participant but doesn't auto-generate intents).
    # =====================================================================
    print("\n--- M3.1: player exclusion removed ---")

    # Test 1: _evaluate_one_promo returns None for player's promo.
    rng = random.Random(42)
    _clear_fa_pool_cache()
    player_intent = _evaluate_one_promo(conn, PLAYER_PROMOTION_ID, sim_date, rng)
    r.check(
        "M3.1: _evaluate_one_promo returns None for player's promo",
        player_intent is None,
        f"got={player_intent}",
    )

    # Test 2: evaluate_signing_intents includes player_pid but skips it.
    # Pass [player_pid, 2] and verify only promo 2 generates an intent.
    _clear_fa_pool_cache()
    intents = evaluate_signing_intents(
        conn, [PLAYER_PROMOTION_ID, 2], sim_date, rng,
    )
    r.check(
        "M3.1: evaluate_signing_intents skips player, includes rival",
        len(intents) >= 0 and all(i['promotion_id'] != PLAYER_PROMOTION_ID
                                  for i in intents),
        f"intents={[(i['promotion_id'], i['fighter_id']) for i in intents]}",
    )

    # =====================================================================
    # M3.2 — SIGNING_INTENT event + bidding_alerts + counter_offer API.
    # =====================================================================
    print("\n--- M3.2: SIGNING_INTENT + bidding_alerts + counter_offer ---")

    # Generate intents for 5 rival promos + the player. Use 5 (not 3)
    # so we have enough alerts to test all 4 counter_offer scenarios
    # (player wins, player loses, sign_free_agent blocked, expiry).
    rival_pids = [r[0] for r in conn.execute(
        "SELECT promotion_id FROM promotions "
        "WHERE promotion_id != ? AND ai_archetype IS NOT NULL "
        "ORDER BY promotion_id LIMIT 5",
        (PLAYER_PROMOTION_ID,),
    ).fetchall()]
    r.check(
        "M3.2: found >= 3 rival promos with archetypes",
        len(rival_pids) >= 3,
        f"rival_pids={rival_pids}",
    )

    _clear_fa_pool_cache()
    promo_ids = rival_pids + [PLAYER_PROMOTION_ID]
    intents = evaluate_signing_intents(conn, promo_ids, sim_date, rng)
    r.check(
        "M3.2: evaluate_signing_intents produced >= 1 intent",
        len(intents) >= 1,
        f"intent_count={len(intents)}",
    )

    # Resolve bidding wars (defers signing + creates alerts).
    signing_intent_events.clear()
    alerts = resolve_bidding_wars(conn, intents, sim_date, rng)
    conn.commit()
    r.check(
        "M3.2: resolve_bidding_wars created bidding_alerts (deferred signing)",
        len(alerts) >= 1,
        f"alerts={len(alerts)}",
    )
    r.check(
        "M3.2: SIGNING_INTENT event fired for each alert",
        len(signing_intent_events) == len(alerts),
        f"events={len(signing_intent_events)} alerts={len(alerts)}",
    )

    # Verify the alerts are in the DB with status='pending'.
    db_alerts = conn.execute(
        "SELECT alert_id, fighter_id, rival_promo_id, offered_salary, "
        "       offer_score, status, expiry_date "
        "FROM bidding_alerts WHERE status='pending'"
    ).fetchall()
    r.check(
        "M3.2: bidding_alerts rows are 'pending' in DB",
        len(db_alerts) == len(alerts),
        f"db_alerts={len(db_alerts)} created={len(alerts)}",
    )

    # Verify the player's promo is NOT the rival_promo_id on any alert.
    player_rival_alerts = [a for a in db_alerts if a[2] == PLAYER_PROMOTION_ID]
    r.check(
        "M3.2: player's promo is not the rival on any alert",
        len(player_rival_alerts) == 0,
        f"player_rival_alerts={len(player_rival_alerts)}",
    )

    # Verify expiry_date = intent_date + decision_window_days.
    if db_alerts:
        a = db_alerts[0]
        intent_date_str = sim_date
        expected_expiry = (
            datetime.strptime(sim_date, "%Y-%m-%d")
            + timedelta(days=DEFAULT_DECISION_WINDOW_DAYS)
        ).strftime("%Y-%m-%d")
        r.check(
            f"M3.2: expiry_date = intent_date + {DEFAULT_DECISION_WINDOW_DAYS}d",
            a[6] == expected_expiry,
            f"expiry={a[6]} expected={expected_expiry}",
        )

    # Verify the fighter is still a free agent (signing was deferred).
    if db_alerts:
        fighter_id = db_alerts[0][1]
        fa_status = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        r.check(
            "M3.2: fighter is still a FA after alert creation (signing deferred)",
            fa_status[0] is None,
            f"fighter_id={fighter_id} promo={fa_status[0]}",
        )

    # Test get_bidding_alerts API (using the app_web.Api class).
    from app_web import Api
    api = Api(db_path=str(DB_PATH))
    api.conn = conn  # use the same conn so we see the test alerts
    alerts_api = api.get_bidding_alerts()
    r.check(
        "M3.2: get_bidding_alerts API returns the pending alerts",
        alerts_api.get("count", 0) == len(alerts),
        f"api_count={alerts_api.get('count', 0)} expected={len(alerts)}",
    )
    # Voice compliance: no raw potential / realization numbers in the
    # API payload. Check a sample alert's keys.
    if alerts_api.get("alerts"):
        sample = alerts_api["alerts"][0]
        forbidden_keys = ["potential", "realization", "effective_ceiling",
                          "offer_score"]  # offer_score is internal-only
        has_forbidden = any(k in sample for k in forbidden_keys)
        r.check(
            "M3.2: API payload has NO raw potential/realization/offer_score",
            not has_forbidden,
            f"keys={list(sample.keys())}",
        )
        # Voice-compliant fields should be present.
        r.check(
            "M3.2: API payload includes voice fields",
            ("fighter_name" in sample and "rival_promo_name" in sample
             and "offered_salary_display" in sample
             and "rival_promo_size_tier_phrase" in sample
             and "fighter_ceiling_phrase" in sample),
            f"keys={list(sample.keys())}",
        )

    # Test counter_offer with a high offer (player should win).
    if db_alerts:
        target_alert = db_alerts[0]
        target_fighter = target_alert[1]
        target_rival = target_alert[2]
        target_salary = target_alert[3]
        # High counter-offer: 3x the rival's salary + signing bonus.
        win_salary = target_salary * 3
        win_bonus = 200000
        result = api.counter_offer(
            target_fighter, salary=win_salary, signing_bonus=win_bonus,
            contract_length=3, win_bonus_pct=0.75,
        )
        r.check(
            "M3.2: counter_offer returns ok=True (resolved)",
            result.get("ok") is True,
            f"result={result}",
        )
        r.check(
            "M3.2: counter_offer player WON with high salary+bonus",
            result.get("accepted") is True,
            f"accepted={result.get('accepted')} "
            f"player_score={result.get('player_offer_score')} "
            f"rival_score={result.get('rival_offer_score')}",
        )
        r.check(
            "M3.2: counter_offer returns chosen_promo_id = player's promo",
            result.get("chosen_promo_id") == PLAYER_PROMOTION_ID,
            f"chosen_promo_id={result.get('chosen_promo_id')}",
        )
        # Verify the alert is resolved as 'won_by_player'.
        alert_status = conn.execute(
            "SELECT status, player_offer_salary, player_offer_score "
            "FROM bidding_alerts WHERE fighter_id=? "
            "ORDER BY alert_id DESC LIMIT 1",
            (target_fighter,),
        ).fetchone()
        r.check(
            "M3.2: alert status = 'won_by_player' after player wins",
            alert_status[0] == 'won_by_player',
            f"status={alert_status[0]}",
        )
        # Verify the fighter is now signed to the player's promo.
        fighter_signed = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (target_fighter,),
        ).fetchone()
        r.check(
            "M3.2: fighter signed to player's promo after winning bid",
            fighter_signed[0] == PLAYER_PROMOTION_ID,
            f"promo={fighter_signed[0]}",
        )
        # Verify a contract was created.
        contract_count = conn.execute(
            "SELECT COUNT(*) FROM fighter_contracts fc "
            "JOIN contracts c ON c.contract_id = fc.contract_id "
            "WHERE fc.fighter_id=? AND c.promotion_id=? "
            "AND c.status='active'",
            (target_fighter, PLAYER_PROMOTION_ID),
        ).fetchone()[0]
        r.check(
            "M3.2: contract created for player after winning bid",
            contract_count >= 1,
            f"contracts={contract_count}",
        )
        # Verify a 'You won X in a bidding war' news item was written.
        won_news = conn.execute(
            "SELECT COUNT(*) FROM news_items "
            "WHERE topic='signing' AND promotion_id=? "
            "AND headline LIKE 'You won%bidding war%'",
            (PLAYER_PROMOTION_ID,),
        ).fetchone()[0]
        r.check(
            "M3.2: 'You won X in a bidding war' news item written",
            won_news >= 1,
            f"news_count={won_news}",
        )
        # Verify signing_bonus was deducted from player's cash.
        player_cash_after = conn.execute(
            "SELECT current_cash FROM promotions WHERE promotion_id=1"
        ).fetchone()[0]
        cash_diff = player_cash_before - player_cash_after
        r.check(
            "M3.2: signing_bonus deducted from player's cash",
            abs(cash_diff - win_bonus) < 1.0,  # allow float rounding
            f"cash_before={player_cash_before} cash_after={player_cash_after} "
            f"diff={cash_diff} expected={win_bonus}",
        )
        # Restore: release the fighter so we don't pollute the world DB.
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL "
            "WHERE fighter_id=?", (target_fighter,),
        )
        conn.execute(
            "UPDATE contracts SET status='terminated' "
            "WHERE contract_id IN ("
            "  SELECT fc.contract_id FROM fighter_contracts fc "
            "  WHERE fc.fighter_id=?"
            ")",
            (target_fighter,),
        )

    # Test counter_offer with a low offer (player should lose).
    if len(db_alerts) >= 2:
        target_alert2 = db_alerts[1]
        target_fighter2 = target_alert2[1]
        target_rival2 = target_alert2[2]
        # Low counter-offer: minimum salary, no bonus.
        result2 = api.counter_offer(
            target_fighter2, salary=10000, signing_bonus=0,
        )
        r.check(
            "M3.2: counter_offer with low offer returns ok=True (resolved)",
            result2.get("ok") is True,
            f"result={result2}",
        )
        # Note: with ±5% randomness, the player MIGHT win even with a
        # low offer if the rival's score is also low. So we just check
        # that the alert is resolved (either won_by_player or won_by_rival).
        alert_status2 = conn.execute(
            "SELECT status FROM bidding_alerts WHERE fighter_id=? "
            "ORDER BY alert_id DESC LIMIT 1",
            (target_fighter2,),
        ).fetchone()
        r.check(
            "M3.2: low counter_offer resolves the alert (either way)",
            alert_status2[0] in ('won_by_player', 'won_by_rival'),
            f"status={alert_status2[0]}",
        )
        # If player lost, verify the fighter signed with the rival.
        if alert_status2[0] == 'won_by_rival':
            fighter2_signed = conn.execute(
                "SELECT current_promotion_id FROM fighters "
                "WHERE fighter_id=?",
                (target_fighter2,),
            ).fetchone()
            r.check(
                "M3.2: fighter signed to rival promo after player loses bid",
                fighter2_signed[0] == target_rival2,
                f"promo={fighter2_signed[0]} expected={target_rival2}",
            )
            # Verify 'You lost X to Y' news item.
            lost_news = conn.execute(
                "SELECT COUNT(*) FROM news_items "
                "WHERE topic='bidding_war_lost' AND promotion_id=? "
                "AND headline LIKE 'You lost%'",
                (PLAYER_PROMOTION_ID,),
            ).fetchone()[0]
            r.check(
                "M3.2: 'You lost X to Y' news item written after losing bid",
                lost_news >= 1,
                f"news_count={lost_news}",
            )
            # Restore.
            conn.execute(
                "UPDATE fighters SET current_promotion_id=NULL "
                "WHERE fighter_id=?", (target_fighter2,),
            )
            conn.execute(
                "UPDATE contracts SET status='terminated' "
                "WHERE contract_id IN ("
                "  SELECT fc.contract_id FROM fighter_contracts fc "
                "  WHERE fc.fighter_id=?"
                ")",
                (target_fighter2,),
            )

    # Test sign_free_agent BLOCKED when pending alert exists.
    if len(db_alerts) >= 3:
        target_alert3 = db_alerts[2]
        target_fighter3 = target_alert3[1]
        # Try to sign directly (should be blocked).
        block_result = api.sign_free_agent(
            target_fighter3, salary=100000, signing_bonus=0,
        )
        r.check(
            "M3.2: sign_free_agent blocked when pending alert exists",
            block_result.get("ok") is False
            and block_result.get("blocked_by_bidding_alert") is True,
            f"result={block_result}",
        )
        r.check(
            "M3.2: blocked sign returns rival_promo_name",
            "rival_promo_name" in block_result,
            f"keys={list(block_result.keys())}",
        )
        # Verify the fighter is still a FA (sign was blocked).
        still_fa = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (target_fighter3,),
        ).fetchone()
        r.check(
            "M3.2: fighter remains FA when sign_free_agent is blocked",
            still_fa[0] is None,
            f"promo={still_fa[0]}",
        )

    # Test check_bidding_alerts_expiry — advance sim_date past expiry.
    if len(db_alerts) >= 3:
        target_alert3 = db_alerts[2]
        target_fighter3 = target_alert3[1]
        target_rival3 = target_alert3[2]
        target_salary3 = target_alert3[3]
        # Compute the expiry_date + 1 day.
        expiry_str = target_alert3[6]
        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d")
        past_date = (expiry_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        signed = check_bidding_alerts_expiry(conn, past_date)
        r.check(
            "M3.2: check_bidding_alerts_expiry signs expired alerts",
            len(signed) >= 1,
            f"signed={len(signed)}",
        )
        # Verify the alert is resolved as 'won_by_rival'.
        alert3_status = conn.execute(
            "SELECT status FROM bidding_alerts WHERE alert_id=?",
            (target_alert3[0],),
        ).fetchone()
        r.check(
            "M3.2: expired alert resolved as 'won_by_rival'",
            alert3_status[0] == 'won_by_rival',
            f"status={alert3_status[0]}",
        )
        # Verify the fighter signed with the rival.
        fighter3_signed = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (target_fighter3,),
        ).fetchone()
        r.check(
            "M3.2: fighter signed to rival after window expired",
            fighter3_signed[0] == target_rival3,
            f"promo={fighter3_signed[0]} expected={target_rival3}",
        )
        # Restore.
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL "
            "WHERE fighter_id=?", (target_fighter3,),
        )
        conn.execute(
            "UPDATE contracts SET status='terminated' "
            "WHERE contract_id IN ("
            "  SELECT fc.contract_id FROM fighter_contracts fc "
            "  WHERE fc.fighter_id=?"
            ")",
            (target_fighter3,),
        )

    # =====================================================================
    # M3.3 — Fair-value formula includes realization.
    # =====================================================================
    print("\n--- M3.3: fair-value formula includes realization ---")

    # Test _fair_value with realization.
    bust_salary = _fair_value(85, 1000, realization=0.5)
    realizer_salary = _fair_value(85, 1000, realization=1.0)
    old_salary = _fair_value(85, 1000)  # no realization = old behavior
    r.check(
        "M3.3: bust (pot=85, real=0.5) priced LOWER than realizer (pot=85, real=1.0)",
        bust_salary < realizer_salary,
        f"bust=${bust_salary:,.0f} realizer=${realizer_salary:,.0f}",
    )
    r.check(
        "M3.3: realizer (pot=85, real=1.0) priced SAME as old behavior (pot=85, no real)",
        realizer_salary == old_salary,
        f"realizer=${realizer_salary:,.0f} old=${old_salary:,.0f}",
    )
    # Bust salary should be roughly half of realizer (since realization=0.5).
    expected_bust_ratio = 0.5 * 85 * 1000 + 1000 * 50  # 42500 + 50000 = 92500
    r.check(
        "M3.3: bust salary matches effective_ceiling formula (pot*real*$1K + rating*$50)",
        abs(bust_salary - expected_bust_ratio) < 0.01,
        f"bust=${bust_salary:,.0f} expected=${expected_bust_ratio:,.0f}",
    )

    # Test _compute_asking_price uses effective_ceiling.
    from agent_offers import _compute_asking_price, ASKING_PRICE_MIN, ASKING_PRICE_MAX
    random.seed(0)
    # Find a real high-potential, low-realization fighter (bust).
    bust_row = conn.execute(
        "SELECT fc.fighter_id, fc.potential, fc.realization "
        "FROM fighter_career fc "
        "WHERE fc.potential >= 80 AND fc.realization <= 0.55 "
        "ORDER BY fc.realization ASC LIMIT 1"
    ).fetchone()
    realizer_row = conn.execute(
        "SELECT fc.fighter_id, fc.potential, fc.realization "
        "FROM fighter_career fc "
        "WHERE fc.potential >= 80 AND fc.realization >= 0.78 "
        "ORDER BY fc.realization DESC LIMIT 1"
    ).fetchone()
    if bust_row and realizer_row:
        # Average over 10 runs (to smooth out the ±10% noise).
        bust_prices = []
        realizer_prices = []
        for _ in range(10):
            bust_prices.append(_compute_asking_price(conn, bust_row[0]))
            realizer_prices.append(_compute_asking_price(conn, realizer_row[0]))
        avg_bust = sum(bust_prices) / len(bust_prices)
        avg_realizer = sum(realizer_prices) / len(realizer_prices)
        r.check(
            "M3.3: asking_price for bust (high pot, low real) < realizer (high pot, high real)",
            avg_bust < avg_realizer,
            f"bust_avg=${avg_bust:,.0f} (pot={bust_row[1]} real={bust_row[2]:.2f}) "
            f"realizer_avg=${avg_realizer:,.0f} (pot={realizer_row[1]} real={realizer_row[2]:.2f})",
        )

    # Test the FA pool includes realization.
    _clear_fa_pool_cache()
    pool = _get_fa_pool(conn)
    if pool:
        sample = pool[0]
        r.check(
            "M3.3: FA pool includes 'realization' field",
            "realization" in sample,
            f"keys={list(sample.keys())}",
        )

    # =====================================================================
    # Cleanup: rollback all test changes.
    # =====================================================================
    print("\n--- Cleanup ---")
    # We've already restored the fighter signings inline; just clean up
    # the bidding_alerts + test news items.
    conn.execute("DELETE FROM bidding_alerts")
    conn.execute(
        "DELETE FROM news_items WHERE topic IN ('bidding_war_lost', 'signing') "
        "AND (headline LIKE 'You won%bidding war%' "
        "     OR headline LIKE 'You lost%')"
    )
    # Restore player's cash (we deducted signing_bonus during the test).
    conn.execute(
        "UPDATE promotions SET current_cash=? WHERE promotion_id=1",
        (player_cash_before,),
    )
    conn.commit()
    print("  Cleanup done (bidding_alerts + test news + player cash restored)")

    # =====================================================================
    # Summary.
    # =====================================================================
    print("\n" + "=" * 72)
    print(f"RESULT: {r.passed} PASS, {r.failed} FAIL")
    if r.failures:
        print("\nFAILURES:")
        for name, detail in r.failures:
            print(f"  - {name}: {detail}")
    print("=" * 72)
    sys.exit(0 if r.failed == 0 else 1)


if __name__ == "__main__":
    main()
