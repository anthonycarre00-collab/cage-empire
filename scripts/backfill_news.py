#!/usr/bin/env python3
"""CLEANUP-AND-FIX Bug 5: Backfill news_items with varied topics.

The audit found news_items has 1884 rows, ALL with topic='finance'
(from a prior backfill). This script:

  1. DELETEs existing finance-only news items.
  2. For each completed event with at least one resolved fight:
       - 1 fight-result news item per fight (importance=SIGNIFICANT)
       - 1 event recap news item per event (importance=ROUTINE)
  3. 1 signing news per fighter contract (importance=MAJOR) —
     from contracts joined to fighter_contracts.
  4. 1 retirement news per retired fighter (importance=MAJOR) —
     from fighters where is_retired=1.
  5. 1 title-change news per title with title_reigns_count > 1
     (importance=LEGENDARY) — from titles table.

All news items use the 'System Feed' news_source (created if absent).
All have proper topic tags: 'fight_result', 'event_recap',
'fighter_signing', 'retirement', 'title_change'.

NOT idempotent — re-running will produce duplicate non-finance news
items. (The DELETE in step 1 only targets finance topic, so re-runs
will leave step 2-5 outputs intact.) Run once.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"


def _get_or_create_system_feed(conn) -> int:
    row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO news_sources (name, credibility, sensationalism, "
        "bias, regional_reach, reliability, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("System Feed", 70, 40, 50, 60, 80, 80),
    )
    return cur.lastrowid


def _fighter_name(conn, fighter_id) -> str:
    if not fighter_id:
        return "Unknown Fighter"
    row = conn.execute(
        "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return f"Fighter #{fighter_id}"
    return f"{row[0] or ''} {row[1] or ''}".strip()


def _promo_name(conn, promo_id) -> str:
    if not promo_id:
        return "the promotion"
    row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()
    return row[0] if row else "the promotion"


def _method_phrase(result_type: str) -> str:
    rt = (result_type or "").lower()
    return {
        "ko_tko": "by KO/TKO",
        "submission": "by submission",
        "doctor_stoppage": "by doctor stoppage",
        "dq": "by disqualification",
        "unanimous_decision": "by unanimous decision",
        "split_decision": "by split decision",
        "majority_decision": "by majority decision",
        "draw": "ended in a draw",
    }.get(rt, "by decision")


def _delete_finance_news(conn) -> int:
    cur = conn.execute("DELETE FROM news_items WHERE topic='finance'")
    return cur.rowcount or 0


def _write_fight_result_news(conn, src_id) -> int:
    """1 news item per resolved fight."""
    fights = conn.execute(
        "SELECT f.fight_id, f.event_id, f.winner_fighter_id, "
        "       f.loser_fighter_id, f.result_type, f.finish_round, "
        "       f.performance_rating, e.event_date, e.promotion_id "
        "FROM fights f "
        "JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NOT NULL"
    ).fetchall()
    n = 0
    for (fid, eid, winner, loser, rt, rnd, perf, edate, pid) in fights:
        wname = _fighter_name(conn, winner)
        lname = _fighter_name(conn, loser)
        method = _method_phrase(rt)
        headline = f"{wname} defeats {lname} {method}"
        body = (
            f"{wname} defeated {lname} {method}"
            + (f" in round {rnd}" if rnd and rt != "draw" else "")
            + (f". Performance rating: {perf}." if perf else ".")
        )
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, event_id, fight_id, fighter_id, "
            "promotion_id, published_at, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, "neutral", "fight_result",
             eid, fid, winner, pid, edate, "SIGNIFICANT"),
        )
        n += 1
    return n


def _write_event_recap_news(conn, src_id) -> int:
    """1 recap per completed event."""
    events = conn.execute(
        "SELECT e.event_id, e.event_name, e.event_date, e.promotion_id, "
        "       (SELECT COUNT(*) FROM fights f "
        "        WHERE f.event_id=e.event_id "
        "          AND f.winner_fighter_id IS NOT NULL) AS n_fights, "
        "       (SELECT COUNT(*) FROM fights f "
        "        WHERE f.event_id=e.event_id "
        "          AND f.result_type IN ('ko_tko','submission',"
        "              'doctor_stoppage','dq')) AS n_finishes "
        "FROM events e "
        "WHERE e.status='completed'"
    ).fetchall()
    n = 0
    for (eid, ename, edate, pid, n_fights, n_finishes) in events:
        if n_fights == 0:
            continue
        promo = _promo_name(conn, pid)
        headline = f"{promo}: {ename} recap — {n_fights} bouts, {n_finishes} finishes"
        body = (
            f"{promo} wrapped up {ename} on {edate} with {n_fights} "
            f"bouts on the card, including {n_finishes} finishes. "
            f"A solid night of action for the promotion."
        )
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, event_id, promotion_id, published_at, "
            "importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, "neutral", "event_recap",
             eid, pid, edate, "ROUTINE"),
        )
        n += 1
    return n


def _write_signing_news(conn, src_id) -> int:
    """1 signing news per fighter contract."""
    signings = conn.execute(
        "SELECT fc.fighter_id, fc.contract_id, c.promotion_id, "
        "       c.start_date, c.salary, c.status "
        "FROM fighter_contracts fc "
        "JOIN contracts c ON c.contract_id=fc.contract_id "
        "WHERE c.contract_target_type='fighter'"
    ).fetchall()
    n = 0
    for (fighter_id, contract_id, pid, start_date, salary, status) in signings:
        fname = _fighter_name(conn, fighter_id)
        promo = _promo_name(conn, pid)
        headline = f"{promo} signs {fname}"
        body = (
            f"{promo} has signed {fname} to a "
            f"{'active' if status == 'active' else status} contract "
            f"effective {start_date}."
            + (f" Reported salary: ${salary:,.0f}." if salary else "")
        )
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, promotion_id, published_at, "
            "importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, "positive", "fighter_signing",
             fighter_id, pid, start_date, "MAJOR"),
        )
        n += 1
    return n


def _write_retirement_news(conn, src_id) -> int:
    """1 retirement news per retired fighter."""
    retired = conn.execute(
        "SELECT fighter_id, first_name, last_name, nickname "
        "FROM fighters WHERE is_retired=1"
    ).fetchall()
    n = 0
    # NOTE: "current_date" must be quoted — without quotes SQLite
    # treats it as the CURRENT_DATE keyword and returns today's real
    # date, not the column value.
    sim_date_row = conn.execute(
        'SELECT "current_date" FROM simulation_clock LIMIT 1'
    ).fetchone()
    sim_date = sim_date_row[0] if sim_date_row else "2026-07-20"
    for (fid, first, last, nick) in retired:
        name = f"{first or ''} {last or ''}".strip()
        if nick:
            name = f'"{nick}" {name}'
        headline = f"{name} announces retirement"
        body = (
            f"After a long career in the cage, {name} has officially "
            f"retired from active competition. The veteran fighter "
            f"hangs up the gloves, closing a chapter on a memorable run."
        )
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, "neutral", "retirement",
             fid, sim_date, "MAJOR"),
        )
        n += 1
    return n


def _write_title_change_news(conn, src_id) -> int:
    """1 title-change news per title with title_reigns_count > 1."""
    titles = conn.execute(
        "SELECT t.title_id, t.promotion_id, t.weight_class_id, "
        "       t.current_champion_fighter_id, "
        "       t.title_reigns_count, t.title_defenses_count "
        "FROM titles t "
        "WHERE t.title_reigns_count > 1"
    ).fetchall()
    # NOTE: "current_date" must be quoted — without quotes SQLite
    # treats it as the CURRENT_DATE keyword.
    sim_date_row = conn.execute(
        'SELECT "current_date" FROM simulation_clock LIMIT 1'
    ).fetchone()
    sim_date = sim_date_row[0] if sim_date_row else "2026-07-20"
    n = 0
    for (tid, pid, wid, champ, reigns, defenses) in titles:
        champ_name = _fighter_name(conn, champ)
        promo = _promo_name(conn, pid)
        wc_row = conn.execute(
            "SELECT name FROM weight_classes WHERE weight_class_id=?",
            (wid,),
        ).fetchone()
        wc_name = wc_row[0] if wc_row else "Unknown Weight Class"
        headline = f"{promo} {wc_name} title changes hands"
        body = (
            f"The {promo} {wc_name} championship has changed hands, "
            f"with current champion {champ_name} now in their "
            f"{reigns}-th reign. The belt has been contested "
            f"{defenses} times in title defenses."
        )
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, promotion_id, published_at, "
            "importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id, headline, body, "positive", "title_change",
             champ, pid, sim_date, "LEGENDARY"),
        )
        n += 1
    return n


def backfill(conn: sqlite3.Connection) -> dict:
    src_id = _get_or_create_system_feed(conn)
    deleted = _delete_finance_news(conn)
    fight_n = _write_fight_result_news(conn, src_id)
    recap_n = _write_event_recap_news(conn, src_id)
    sign_n = _write_signing_news(conn, src_id)
    retire_n = _write_retirement_news(conn, src_id)
    title_n = _write_title_change_news(conn, src_id)
    conn.commit()
    return {
        "deleted_finance": deleted,
        "fight_result": fight_n,
        "event_recap": recap_n,
        "fighter_signing": sign_n,
        "retirement": retire_n,
        "title_change": title_n,
    }


def main():
    db_path = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(DB_PATH)))
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    try:
        result = backfill(conn)
    finally:
        conn.close()

    print("news_items backfill complete:")
    print(f"  deleted finance-only news: {result['deleted_finance']}")
    print(f"  fight_result news items:   {result['fight_result']}")
    print(f"  event_recap news items:    {result['event_recap']}")
    print(f"  fighter_signing news:      {result['fighter_signing']}")
    print(f"  retirement news:           {result['retirement']}")
    print(f"  title_change news:         {result['title_change']}")
    total_new = sum(v for k, v in result.items()
                    if k != "deleted_finance")
    print(f"  total new news items:      {total_new}")


if __name__ == "__main__":
    main()
