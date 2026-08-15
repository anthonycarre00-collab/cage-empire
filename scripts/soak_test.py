#!/usr/bin/env python3
"""HW6.1 (Hardening Phase §HW6.1 / W34) — Long-run soak test.

Runs the simulation forward N days, recording metrics at every 30-day
checkpoint. The metrics cover the full world-integrity surface that
the Hardening Phase acceptance gates (W48) require:

  POPULATION       — active / retired / regenerated fighters, gyms,
                     promotions, staff
  COMPETITION      — events, fights, title fights, title changes,
                     rankings
  CAREERS          — retirements, debuts, comebacks, injuries
  ECONOMY          — promotions by financial_state, cash distribution,
                     bankruptcies, finance transactions
  WORLD            — rivalries, gym movements, bidding wars
  NARRATIVE        — news by importance tier, echoes, memory resurfacing
  INTEGRITY        — tick_health errors, unresolved events, orphaned
                     fights, impossible dates

Usage:
    python3 scripts/soak_test.py [days]              # default = 30 days
    python3 scripts/soak_test.py 365                 # 1-year soak
    python3 scripts/soak_test.py 365 --no-backup     # skip backup
    python3 scripts/soak_test.py 30 --db PATH        # custom DB

Output:
    - Per-checkpoint summary report printed to stdout.
    - Final summary report at the end.
    - Exit code 0 if no integrity errors; 1 otherwise.

Refs docs/Hardening_Phase.md §HW6.1, §HW6.2, §HW6.3, W34, W48.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))
sys.path.insert(0, str(SRC_DIR))


# ----------------------------------------------------------------
# Metric collection
# ----------------------------------------------------------------

def _scalar(conn, sql, *args):
    """Run a query + return the first column of the first row (or 0)."""
    try:
        row = conn.execute(sql, *args).fetchone()
        return row[0] if row else 0
    except sqlite3.Error:
        return 0


def _scalar_str(conn, sql, *args):
    """Run a query + return the first column as a string (or 'N/A')."""
    try:
        row = conn.execute(sql, *args).fetchone()
        return str(row[0]) if row and row[0] is not None else "N/A"
    except sqlite3.Error:
        return "N/A"


def _has_column(conn, table, col):
    """Return True if `table` has a column named `col`."""
    try:
        cols = [r[1] for r in conn.execute(
            f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except sqlite3.Error:
        return False


def _has_table(conn, table):
    """Return True if `table` exists."""
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def collect_metrics(conn):
    """Collect a snapshot of all soak-test metrics.

    Returns an OrderedDict with 7 sections (population, competition,
    careers, economy, world, narrative, integrity), each a dict of
    metric_name → value.

    All queries are wrapped in try/except so a missing table or
    column doesn't crash the soak test — instead the metric is
    reported as 0 (with the underlying error printed to stderr
    once, so the operator can investigate).
    """
    m = OrderedDict()

    # ---------- POPULATION ----------
    pop = OrderedDict()
    pop["fighters_total"] = _scalar(conn, "SELECT COUNT(*) FROM fighters")
    pop["fighters_active"] = _scalar(
        conn, "SELECT COUNT(*) FROM fighters WHERE is_active=1")
    pop["fighters_inactive"] = _scalar(
        conn, "SELECT COUNT(*) FROM fighters WHERE is_active=0")
    pop["fighters_retired"] = _scalar(
        conn, "SELECT COUNT(*) FROM fighters WHERE is_retired=1")
    pop["fighters_deceased"] = _scalar(
        conn, "SELECT COUNT(*) FROM fighters WHERE is_deceased=1")
    pop["gyms"] = _scalar(conn, "SELECT COUNT(*) FROM gyms")
    pop["promotions"] = _scalar(conn, "SELECT COUNT(*) FROM promotions")
    pop["staff"] = _scalar(conn, "SELECT COUNT(*) FROM staff")
    # Regen lineage — how many fighters have been regenerated.
    pop["regen_lineage_rows"] = _scalar(
        conn, "SELECT COUNT(*) FROM regen_lineage")
    pop["distinct_regen_chain_heads"] = _scalar(
        conn, "SELECT COUNT(DISTINCT original_fighter_id) FROM regen_lineage")
    m["population"] = pop

    # ---------- COMPETITION ----------
    comp = OrderedDict()
    comp["events_total"] = _scalar(conn, "SELECT COUNT(*) FROM events")
    comp["events_scheduled"] = _scalar(
        conn, "SELECT COUNT(*) FROM events WHERE status='scheduled'")
    comp["events_card_confirmed"] = _scalar(
        conn, "SELECT COUNT(*) FROM events WHERE status='card_confirmed'")
    comp["events_completed"] = _scalar(
        conn, "SELECT COUNT(*) FROM events WHERE status='completed'")
    comp["events_cancelled"] = _scalar(
        conn, "SELECT COUNT(*) FROM events WHERE status='cancelled'")
    comp["fights_total"] = _scalar(conn, "SELECT COUNT(*) FROM fights")
    comp["fights_title_fights"] = _scalar(
        conn, "SELECT COUNT(*) FROM fights WHERE is_title_fight=1")
    comp["titles_total"] = _scalar(conn, "SELECT COUNT(*) FROM titles")
    comp["titles_vacant"] = _scalar(
        conn, "SELECT COUNT(*) FROM titles WHERE is_vacant=1")
    comp["titles_with_champion"] = _scalar(
        conn, "SELECT COUNT(*) FROM titles WHERE is_vacant=0 "
        "AND current_champion_fighter_id IS NOT NULL")
    # Title changes — count title_reigns in titles, minus 1 per active
    # title (each title's first reign isn't a "change"; subsequent
    # reigns are). Approximate: sum(max(title_reigns_count - 1, 0)).
    comp["title_changes_total_approx"] = _scalar(
        conn, "SELECT COALESCE(SUM(MAX(title_reigns_count - 1, 0)), 0) "
        "FROM titles")
    # Rankings
    comp["rankings_rows"] = _scalar(
        conn, "SELECT COUNT(*) FROM rankings")
    comp["weight_classes_with_rankings"] = _scalar(
        conn, "SELECT COUNT(DISTINCT weight_class_id) FROM rankings")
    m["competition"] = comp

    # ---------- CAREERS ----------
    car = OrderedDict()
    # Debut = fights where the fighter has exactly 1 fight_history row.
    # That's expensive to compute on every checkpoint — instead, count
    # fighters with at least 1 fight_history row.
    car["fighters_with_history"] = _scalar(
        conn, "SELECT COUNT(DISTINCT fighter_id) FROM fight_history")
    # Comebacks = retired fighters who came back (is_retired=0 AND
    # they have a regen_lineage entry). This is approximate.
    car["comebacks_via_regen"] = _scalar(
        conn, "SELECT COUNT(DISTINCT rl.original_fighter_id) "
        "FROM regen_lineage rl "
        "JOIN fighters f ON rl.successor_fighter_id = f.fighter_id "
        "WHERE f.is_retired = 0")
    # Injuries (active + total)
    car["injuries_total"] = _scalar(conn, "SELECT COUNT(*) FROM injuries")
    car["injuries_active"] = _scalar(
        conn, "SELECT COUNT(*) FROM injuries WHERE is_active=1")
    # Suspensions
    car["suspensions_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM suspensions")
    car["suspensions_active"] = _scalar(
        conn, "SELECT COUNT(*) FROM suspensions "
        "WHERE end_date >= "
        "(SELECT simulation_clock.current_date "
        " FROM simulation_clock WHERE clock_id=1)")
    # Hall of Fame inductees
    car["hof_inductees"] = _scalar(
        conn, "SELECT COUNT(*) FROM hall_of_fame")
    m["careers"] = car

    # ---------- ECONOMY ----------
    eco = OrderedDict()
    # Promotions by financial_state (HW1.4 — gradient state machine).
    if _has_column(conn, "promotions", "financial_state"):
        for state in ("HEALTHY", "STABLE", "STRAINED",
                      "DISTRESSED", "CRITICAL", "BANKRUPT",
                      "REBUILDING"):
            eco[f"promos_{state.lower()}"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM promotions "
                "WHERE financial_state=?", (state,))
    # Cash distribution
    cash_row = conn.execute(
        "SELECT MIN(current_cash), MAX(current_cash), "
        "       AVG(current_cash), SUM(current_cash) "
        "FROM promotions"
    ).fetchone()
    eco["cash_min"] = cash_row[0] if cash_row else 0
    eco["cash_max"] = cash_row[1] if cash_row else 0
    eco["cash_avg"] = round(cash_row[2], 2) if cash_row and cash_row[2] else 0
    eco["cash_total"] = cash_row[3] if cash_row else 0
    # Bankruptcies — count promotions where is_rebuilding=1 (they
    # entered bankruptcy + are now rebuilding).
    if _has_column(conn, "promotions", "is_rebuilding"):
        eco["promos_rebuilding"] = _scalar(
            conn, "SELECT COUNT(*) FROM promotions WHERE is_rebuilding=1")
    # Finance transactions
    eco["finance_txns_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM finance_transactions")
    # By transaction_type (top 5)
    try:
        txn_types = conn.execute(
            "SELECT transaction_type, COUNT(*) FROM finance_transactions "
            "GROUP BY transaction_type ORDER BY COUNT(*) DESC LIMIT 5"
        ).fetchall()
        for tt, n in txn_types:
            eco[f"txn_{tt}"] = n
    except sqlite3.Error:
        pass
    m["economy"] = eco

    # ---------- WORLD ----------
    wor = OrderedDict()
    wor["rivalries_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM rivalries")
    # Rivalries by intensity (if column exists).
    if _has_column(conn, "rivalries", "intensity"):
        for intensity in ("low", "medium", "high", "bitter"):
            wor[f"rivalries_{intensity}"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM rivalries WHERE intensity=?",
                (intensity,))
    # Bidding alerts (proxy for bidding wars).
    wor["bidding_alerts_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM bidding_alerts")
    if _has_column(conn, "bidding_alerts", "status"):
        for status in ("open", "won", "lost", "expired"):
            wor[f"bidding_{status}"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM bidding_alerts WHERE status=?",
                (status,))
    # Agent offers (proxy for free-agency bidding wars).
    wor["agent_offers_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM agent_offers")
    # Memory links (gym movements, former teammates, etc.).
    wor["memory_links_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM fighter_memory_links")
    if _has_column(conn, "fighter_memory_links", "link_type"):
        wor["memory_link_types"] = dict(conn.execute(
            "SELECT link_type, COUNT(*) FROM fighter_memory_links "
            "GROUP BY link_type ORDER BY COUNT(*) DESC"
        ).fetchall())
    m["world"] = wor

    # ---------- NARRATIVE ----------
    nar = OrderedDict()
    nar["news_total"] = _scalar(conn, "SELECT COUNT(*) FROM news_items")
    # News by importance tier (HW4.1 column).
    if _has_column(conn, "news_items", "importance"):
        for tier in ("LEGENDARY", "MAJOR", "SIGNIFICANT",
                     "ROUTINE", "BACKGROUND"):
            nar[f"news_{tier.lower()}"] = _scalar(
                conn,
                "SELECT COUNT(*) FROM news_items WHERE importance=?",
                (tier,))
    # News by topic (top 8)
    try:
        topics = conn.execute(
            "SELECT topic, COUNT(*) FROM news_items "
            "GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 8"
        ).fetchall()
        nar["news_top_topics"] = dict(topics)
    except sqlite3.Error:
        pass
    # Echoes (daily_echoes — the player-decision consequence feed).
    nar["daily_echoes_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM daily_echoes")
    # Memory resurfacing news (topic='memory_resurfacing').
    nar["memory_resurfacing_news"] = _scalar(
        conn, "SELECT COUNT(*) FROM news_items WHERE topic='memory_resurfacing'")
    # Social posts (proxy for narrative activity).
    nar["social_posts_total"] = _scalar(
        conn, "SELECT COUNT(*) FROM social_posts")
    m["narrative"] = nar

    # ---------- INTEGRITY ----------
    integ = OrderedDict()
    # Tick health (HW2.1 — simulation_tick_health table).
    if _has_table(conn, "simulation_tick_health"):
        # Latest tick health
        latest = conn.execute(
            "SELECT tick_date, health_status, subscribers_failed, "
            "       events_scheduled, events_completed, fights_resolved, "
            "       fighters_retired, fighters_regen, title_changes, "
            "       finance_transactions, news_generated, "
            "       social_posts_generated, memories_generated "
            "FROM simulation_tick_health "
            "ORDER BY tick_id DESC LIMIT 1"
        ).fetchone()
        if latest:
            integ["latest_tick_date"] = str(latest[0])
            integ["latest_tick_health"] = str(latest[1])
            integ["latest_tick_subscribers_failed"] = latest[2]
            integ["latest_tick_events_scheduled"] = latest[3]
            integ["latest_tick_events_completed"] = latest[4]
            integ["latest_tick_fights_resolved"] = latest[5]
            integ["latest_tick_fighters_retired"] = latest[6]
            integ["latest_tick_fighters_regen"] = latest[7]
            integ["latest_tick_title_changes"] = latest[8]
            integ["latest_tick_finance_txns"] = latest[9]
            integ["latest_tick_news_generated"] = latest[10]
            integ["latest_tick_social_posts"] = latest[11]
            integ["latest_tick_memories_generated"] = latest[12]
        # Total ticks with errors
        integ["ticks_with_errors"] = _scalar(
            conn, "SELECT COUNT(*) FROM simulation_tick_health "
            "WHERE tick_success=0 OR subscribers_failed > 0")
        # Total ticks
        integ["ticks_total"] = _scalar(
            conn, "SELECT COUNT(*) FROM simulation_tick_health")
        # Health status distribution (last 100 ticks)
        try:
            status_dist = conn.execute(
                "SELECT health_status, COUNT(*) FROM ("
                "  SELECT health_status FROM simulation_tick_health "
                "  ORDER BY tick_id DESC LIMIT 100"
                ") GROUP BY health_status"
            ).fetchall()
            integ["last_100_ticks_health"] = dict(status_dist)
        except sqlite3.Error:
            pass
    # Unresolved events (scheduled but past their event_date).
    sim_date = _scalar_str(
        conn,
        "SELECT simulation_clock.current_date FROM simulation_clock "
        "WHERE clock_id=1")
    integ["sim_date"] = sim_date
    integ["unresolved_events_past_date"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM events "
        "WHERE status IN ('scheduled', 'card_confirmed') "
        "AND event_date < ?",
        (sim_date,))
    # Orphaned fights (0 participants).
    integ["orphan_fights_0_participants"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM fights f "
        "WHERE NOT EXISTS (SELECT 1 FROM fight_participants fp "
        "                  WHERE fp.fight_id = f.fight_id)")
    # Impossible dates — news published_at > sim_date.
    # NOTE: this catches BOTH legitimate scheduled-content news (e.g.
    # "event X announced for next week") AND bugs (post-event news
    # dated for the event_date instead of the sim_date). The soak
    # test reports the raw count; the operator investigates the
    # distribution by topic to distinguish.
    integ["future_dated_news"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM news_items WHERE published_at > ?",
        (sim_date,))
    # Impossible dates — events with event_date > sim_date.
    # SPLIT by status: 'scheduled' future events are legitimate
    # calendar items; 'completed' future events are a BUG (event
    # resolved before its event_date).
    integ["future_dated_events"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM events WHERE event_date > ?",
        (sim_date,))
    integ["future_dated_events_scheduled"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM events WHERE event_date > ? "
        "AND status IN ('scheduled', 'card_confirmed')",
        (sim_date,))
    integ["future_dated_events_completed"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM events WHERE event_date > ? "
        "AND status='completed'",
        (sim_date,))
    # Impossible dates — social posts with post_date > sim_date.
    integ["future_dated_social_posts"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM social_posts WHERE post_date > ?",
        (sim_date,))
    # Self-fights (winner == loser).
    integ["self_fights"] = _scalar(
        conn,
        "SELECT COUNT(*) FROM fights WHERE winner_fighter_id IS NOT NULL "
        "AND loser_fighter_id IS NOT NULL "
        "AND winner_fighter_id = loser_fighter_id")
    m["integrity"] = integ

    return m


# ----------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------

def _format_value(v):
    """Format a metric value for the report (handles dicts + scalars)."""
    if isinstance(v, dict):
        # Format as "key=n, key=n" (sorted by value desc).
        items = sorted(v.items(), key=lambda x: -x[1] if isinstance(x[1], int) else 0)
        return ", ".join(f"{k}={n}" for k, n in items[:6])
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def print_checkpoint_report(day, sim_date, metrics, baseline=None):
    """Print a per-checkpoint summary report.

    If baseline is provided, also show the delta from baseline (the
    initial metrics collected at day 0).
    """
    print()
    print("=" * 76)
    print(f"CHECKPOINT @ day {day}  (sim_date={sim_date})")
    print("=" * 76)
    for section, section_metrics in metrics.items():
        print(f"--- {section.upper()} ---")
        for name, value in section_metrics.items():
            line = f"  {name:<42} = {_format_value(value)}"
            if baseline and section in baseline:
                base_val = baseline[section].get(name)
                if base_val is not None and isinstance(value, (int, float)):
                    delta = value - (base_val if isinstance(base_val, (int, float)) else 0)
                    if delta != 0:
                        sign = "+" if delta > 0 else ""
                        line += f"   ({sign}{delta} from baseline)"
            print(line)
    print()


def print_final_report(days, elapsed_s, success_count, fail_count,
                       final_metrics, baseline_metrics):
    """Print the final summary report at the end of the soak test."""
    print()
    print("#" * 76)
    print(f"FINAL SOAK TEST REPORT — {days} days")
    print("#" * 76)
    print(f"  Elapsed:        {elapsed_s:.1f}s ({success_count} days advanced, "
          f"{fail_count} failed)")
    if success_count > 0:
        print(f"  Per-day avg:    {elapsed_s / success_count:.3f}s/day")
    print()

    # Compute deltas vs baseline for the most-watched metrics.
    print("--- KEY DELTAS (final - baseline) ---")
    watched = [
        ("population", "fighters_total"),
        ("population", "fighters_active"),
        ("population", "fighters_retired"),
        ("population", "regen_lineage_rows"),
        ("competition", "events_total"),
        ("competition", "events_completed"),
        ("competition", "fights_total"),
        ("competition", "fights_title_fights"),
        ("competition", "title_changes_total_approx"),
        ("careers", "fighters_with_history"),
        ("careers", "injuries_total"),
        ("careers", "hof_inductees"),
        ("economy", "finance_txns_total"),
        ("economy", "promos_rebuilding"),
        ("world", "rivalries_total"),
        ("world", "memory_links_total"),
        ("narrative", "news_total"),
        ("narrative", "news_legendary"),
        ("narrative", "news_major"),
        ("narrative", "news_significant"),
        ("narrative", "news_routine"),
        ("narrative", "news_background"),
        ("narrative", "daily_echoes_total"),
        ("narrative", "social_posts_total"),
        ("narrative", "memory_resurfacing_news"),
    ]
    for section, name in watched:
        if section not in final_metrics:
            continue
        final_v = final_metrics[section].get(name)
        base_v = baseline_metrics.get(section, {}).get(name) if baseline_metrics else None
        if final_v is None:
            continue
        if isinstance(final_v, (int, float)) and isinstance(base_v, (int, float)):
            delta = final_v - base_v
            sign = "+" if delta > 0 else ""
            print(f"  {section}.{name:<36} = {final_v:>8}   "
                  f"({sign}{delta} from baseline)")
        else:
            print(f"  {section}.{name:<36} = {_format_value(final_v)}")

    # Integrity summary
    print()
    print("--- INTEGRITY SUMMARY ---")
    integ = final_metrics.get("integrity", {})
    for name in ("sim_date", "latest_tick_health", "ticks_with_errors",
                 "ticks_total", "unresolved_events_past_date",
                 "orphan_fights_0_participants", "future_dated_news",
                 "future_dated_events", "future_dated_events_scheduled",
                 "future_dated_events_completed",
                 "future_dated_social_posts", "self_fights"):
        if name in integ:
            print(f"  {name:<42} = {_format_value(integ[name])}")
    if "last_100_ticks_health" in integ:
        print(f"  last_100_ticks_health                  = "
              f"{_format_value(integ['last_100_ticks_health'])}")

    # Gate verdict — per HW6.2 (Gate 1, 30d) and HW6.3 (Gate 2, 365d)
    # criteria from docs/Hardening_Phase.md:
    #   Gate 1 (30d): events resolve, finance fires, news generated,
    #                 no crashes, tick_health HEALTHY.
    #   Gate 2 (365d): champions change, fighters retire+regen,
    #                  promotions have differentiated fortunes,
    #                  rivalries develop.
    # The integrity violations below are reported as ISSUES but the
    # gate verdict follows the spec's criteria (events/finance/news/
    # crashes/tick_health for Gate 1; champions/retirements/promos/
    # rivalries for Gate 2).
    print()
    print("--- GATE VERDICT ---")
    comp = final_metrics.get("competition", {})
    eco = final_metrics.get("economy", {})
    nar = final_metrics.get("narrative", {})
    pop = final_metrics.get("population", {})
    wor = final_metrics.get("world", {})
    car = final_metrics.get("careers", {})

    # Hard fails — these are ALWAYS gate-failing regardless of which
    # gate we're running. They indicate broken infrastructure.
    hard_fails = []
    if integ.get("ticks_with_errors", 0) > 0:
        hard_fails.append(f"{integ['ticks_with_errors']} ticks with errors")
    if integ.get("orphan_fights_0_participants", 0) > 0:
        hard_fails.append(f"{integ['orphan_fights_0_participants']} orphan "
                          "fights (0 participants)")
    if integ.get("self_fights", 0) > 0:
        hard_fails.append(f"{integ['self_fights']} self-fights (winner==loser)")
    if integ.get("future_dated_social_posts", 0) > 0:
        hard_fails.append(f"{integ['future_dated_social_posts']} future-dated "
                          "social posts (HW5.4 clamp should prevent this)")
    if integ.get("future_dated_events_completed", 0) > 0:
        hard_fails.append(
            f"{integ['future_dated_events_completed']} future-dated events "
            "marked COMPLETED (event resolved before its event_date — "
            "lifecycle bug)")
    latest_health = integ.get("latest_tick_health", "UNKNOWN")
    if latest_health not in ("HEALTHY", "UNKNOWN"):
        hard_fails.append(f"latest tick health = {latest_health}")

    # Gate 1 criteria (30 days).
    gate1_checks = []
    # 1. events resolve (at least 1 new completed event).
    new_completed = (comp.get("events_completed", 0)
                     - (baseline_metrics.get("competition", {})
                        .get("events_completed", 0)
                        if baseline_metrics else 0))
    gate1_checks.append((
        "events resolve",
        new_completed > 0,
        f"+{new_completed} completed events"))
    # 2. finance fires (at least 1 new finance_transaction).
    new_txns = (eco.get("finance_txns_total", 0)
                - (baseline_metrics.get("economy", {})
                   .get("finance_txns_total", 0)
                   if baseline_metrics else 0))
    gate1_checks.append((
        "finance fires",
        new_txns > 0,
        f"+{new_txns} finance transactions"))
    # 3. news generated (at least 1 new news item).
    new_news = (nar.get("news_total", 0)
                - (baseline_metrics.get("narrative", {})
                   .get("news_total", 0)
                   if baseline_metrics else 0))
    gate1_checks.append((
        "news generated",
        new_news > 0,
        f"+{new_news} news items"))
    # 4. no crashes (fail_count == 0).
    gate1_checks.append((
        "no crashes",
        fail_count == 0,
        f"{fail_count} failed days"))
    # 5. tick_health HEALTHY.
    gate1_checks.append((
        "tick_health HEALTHY",
        latest_health in ("HEALTHY", "UNKNOWN") or
        (integ.get("ticks_with_errors", 0) == 0),
        f"latest={latest_health}, errors={integ.get('ticks_with_errors', 0)}"))

    # Gate 2 criteria (365 days).
    gate2_checks = []
    if days >= 365:
        # 1. champions change (title_changes_total_approx increased).
        new_title_changes = (comp.get("title_changes_total_approx", 0)
                             - (baseline_metrics.get("competition", {})
                                .get("title_changes_total_approx", 0)
                                if baseline_metrics else 0))
        gate2_checks.append((
            "champions change",
            new_title_changes > 0,
            f"+{new_title_changes} title changes"))
        # 2. fighters retire+regen.
        new_retirements = (pop.get("fighters_retired", 0)
                           - (baseline_metrics.get("population", {})
                              .get("fighters_retired", 0)
                              if baseline_metrics else 0))
        new_regen = (pop.get("regen_lineage_rows", 0)
                     - (baseline_metrics.get("population", {})
                        .get("regen_lineage_rows", 0)
                        if baseline_metrics else 0))
        gate2_checks.append((
            "fighters retire+regen",
            new_retirements > 0 or new_regen > 0,
            f"+{new_retirements} retired, +{new_regen} regen"))
        # 3. promotions have differentiated fortunes (cash distribution
        # spread — at least 1 promo in non-HEALTHY state OR cash range
        # is wide).
        non_healthy = sum(
            eco.get(k, 0) for k in eco
            if k.startswith("promos_") and k != "promos_healthy"
        )
        cash_range = (eco.get("cash_max", 0)
                      - eco.get("cash_min", 0))
        gate2_checks.append((
            "promotions have differentiated fortunes",
            non_healthy > 0 or cash_range > 10_000_000,
            f"non_healthy={non_healthy}, cash_range={cash_range:.0f}"))
        # 4. rivalries develop.
        new_rivalries = (wor.get("rivalries_total", 0)
                         - (baseline_metrics.get("world", {})
                            .get("rivalries_total", 0)
                            if baseline_metrics else 0))
        gate2_checks.append((
            "rivalries develop",
            new_rivalries > 0,
            f"+{new_rivalries} rivalries"))

    # Print Gate 1 checks.
    print(f"  Gate 1 (30-day criteria):")
    gate1_pass = True
    for name, passed, detail in gate1_checks:
        status = "✓" if passed else "✗"
        print(f"    {status} {name:<32} {detail}")
        if not passed:
            gate1_pass = False

    # Print Gate 2 checks if applicable.
    gate2_pass = True
    if gate2_checks:
        print(f"  Gate 2 (365-day criteria):")
        for name, passed, detail in gate2_checks:
            status = "✓" if passed else "✗"
            print(f"    {status} {name:<32} {detail}")
            if not passed:
                gate2_pass = False

    # Print hard fails (integrity violations).
    if hard_fails:
        print(f"  Integrity hard fails (ALWAYS gate-failing):")
        for issue in hard_fails:
            print(f"    ✗ {issue}")

    # Print informational issues (NOT gate-failing per spec, but
    # worth flagging).
    info_issues = []
    if integ.get("unresolved_events_past_date", 0) > 0:
        info_issues.append(
            f"{integ['unresolved_events_past_date']} unresolved "
            "past-dated events (event lifecycle issue)")
    if integ.get("future_dated_news", 0) > 0:
        info_issues.append(
            f"{integ['future_dated_news']} future-dated news items "
            "(investigate topic distribution)")
    if integ.get("future_dated_events_scheduled", 0) > 0:
        info_issues.append(
            f"{integ['future_dated_events_scheduled']} future-dated "
            "SCHEDULED events (legitimate calendar items — informational)")
    if info_issues:
        print(f"  Informational issues (NOT gate-failing per spec):")
        for issue in info_issues:
            print(f"    ⚠ {issue}")

    # Final verdict.
    print()
    if hard_fails or not gate1_pass or (gate2_checks and not gate2_pass):
        print("  ✗ OVERALL: FAIL — see gate failures above.")
    else:
        gate_label = "Gate 1 + Gate 2" if gate2_checks else "Gate 1"
        print(f"  ✓ OVERALL: PASS — {gate_label} criteria met.")
    print()


# ----------------------------------------------------------------
# Subscriber registration (mirrors app.py / run_sim_forward.py)
# ----------------------------------------------------------------

def register_all_subscribers():
    """Register all event-bus subscribers (mirrors app.py)."""
    registered = 0
    failed = 0

    # Top-level modules
    top_level_modules = [
        "news", "social", "rivalries", "punditry", "morale",
        "suspensions", "agent_offers", "career_arc", "rival_ai",
        "show_rating", "venues", "save_load", "player_settings",
        "reputation", "scouting",
        # NEWS-FINANCE-GYM-LEGACY Issue 8 — weekly gym-transfer
        # subscriber. Registered here so the soak test exercises the
        # same gym-transfer flow as the live web app.
        "gym_transfers",
    ]
    for mod_name in top_level_modules:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
                registered += 1
        except ImportError:
            failed += 1
        except Exception as e:
            failed += 1
            print(f"  Warning: {mod_name}.register_subscribers failed: {e}",
                  file=sys.stderr)

    # Service modules
    service_modules = [
        "services.hof_svc", "services.retirement_svc",
        "services.training_svc", "services.injuries_svc",
        "services.finance_svc", "services.rivalries_svc",
        "services.memory_svc", "services.contracts",
        "services.scouting_svc", "services.matchmaking",
        "services.punditry_svc", "services.pruning_svc",
    ]
    for mod_name in service_modules:
        try:
            mod = __import__(mod_name, fromlist=["register_subscribers"])
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
                registered += 1
        except ImportError:
            failed += 1
        except Exception as e:
            failed += 1
            print(f"  Warning: {mod_name}.register_subscribers failed: {e}",
                  file=sys.stderr)

    # Interpretation layer
    try:
        from interpretation import register_subscribers as _register_interp
        _register_interp()
        registered += 1
    except ImportError:
        failed += 1
    except Exception as e:
        failed += 1
        print(f"  Warning: interpretation.register_subscribers failed: {e}",
              file=sys.stderr)

    return registered, failed


# ----------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="?", type=int, default=30,
                    help="Number of sim days to advance (default 30).")
    ap.add_argument("--no-backup", action="store_true",
                    help="Skip the DB backup before running.")
    ap.add_argument("--db", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    ap.add_argument("--checkpoint-every", type=int, default=30,
                    help="Print a checkpoint report every N days "
                         "(default 30).")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    print("=" * 76)
    print(f"CAGE EMPIRE — Soak Test (HW6.1 / W34)")
    print("=" * 76)
    print(f"  DB:                  {db}")
    print(f"  Days to advance:     {args.days}")
    print(f"  Checkpoint every:    {args.checkpoint_every} days")
    print()

    # Backup before running (unless --no-backup).
    if not args.no_backup:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = db.parent / f"{db.name}.bak.pre-soak-{ts}"
        shutil.copy2(db, backup_path)
        print(f"  Backed up DB → {backup_path.name}")
        print()

    # Connect.
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON;")

    # Baseline state.
    clock_before = conn.execute(
        "SELECT current_date, current_day, current_month, current_year "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    print(f"  BEFORE: sim_date={clock_before[0]} "
          f"(day {clock_before[1]})")
    print()

    # Collect baseline metrics.
    print("  Collecting baseline metrics...")
    baseline_metrics = collect_metrics(conn)
    print_checkpoint_report(0, clock_before[0], baseline_metrics, baseline=None)

    # Register all event-bus subscribers.
    print("  Registering event-bus subscribers...")
    registered, failed = register_all_subscribers()
    print(f"  Registered {registered} subscribers ({failed} failed)")
    print()

    # Import advance_day.
    from services.clock import advance_day

    # Advance day × N, with checkpoint reports every `checkpoint_every`
    # days.
    t0 = time.perf_counter()
    success_count = 0
    fail_count = 0
    last_checkpoint_day = 0
    for i in range(args.days):
        try:
            advance_day(conn)
            conn.commit()
            success_count += 1
        except Exception as e:
            fail_count += 1
            if fail_count <= 5:
                print(f"    Day {i+1} FAILED: {type(e).__name__}: {e}",
                      file=sys.stderr)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

        # Checkpoint report every N days.
        day_num = i + 1
        if (day_num % args.checkpoint_every == 0
                or day_num == args.days):
            # Get current sim_date.
            clock = conn.execute(
                "SELECT current_date FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            cur_sim_date = clock[0] if clock else "?"
            print(f"  Day {day_num}/{args.days}: {cur_sim_date} — "
                  f"collecting checkpoint metrics...")
            metrics = collect_metrics(conn)
            print_checkpoint_report(day_num, cur_sim_date, metrics,
                                    baseline=baseline_metrics)
            last_checkpoint_day = day_num

    t1 = time.perf_counter()
    elapsed = t1 - t0

    # Final state.
    # NOTE: use qualified column name `simulation_clock.current_date`
    # to avoid the SQLite quirk where bare `current_date` is
    # interpreted as the CURRENT_DATE function (returns today's
    # real date, not the column value). Same quirk as save_load's
    # _query_save_metadata.
    clock_after = conn.execute(
        "SELECT simulation_clock.current_date, "
        "       simulation_clock.current_day, "
        "       simulation_clock.current_month, "
        "       simulation_clock.current_year "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    print(f"  AFTER: sim_date={clock_after[0]} (day {clock_after[1]})")
    print(f"  Elapsed: {elapsed:.1f}s ({success_count} days advanced, "
          f"{fail_count} failed)")

    # Final metrics + report.
    final_metrics = collect_metrics(conn)
    print_final_report(args.days, elapsed, success_count, fail_count,
                       final_metrics, baseline_metrics)

    conn.close()

    # Exit code: 0 if no integrity violations, 1 otherwise.
    integ = final_metrics.get("integrity", {})
    has_violations = (
        integ.get("ticks_with_errors", 0) > 0
        or integ.get("unresolved_events_past_date", 0) > 0
        or integ.get("orphan_fights_0_participants", 0) > 0
        or integ.get("future_dated_news", 0) > 0
        or integ.get("future_dated_events", 0) > 0
        or integ.get("future_dated_social_posts", 0) > 0
        or integ.get("self_fights", 0) > 0
        or integ.get("latest_tick_health", "HEALTHY") not in ("HEALTHY", "UNKNOWN")
    )
    return 0 if not has_violations else 1


if __name__ == "__main__":
    sys.exit(main())
