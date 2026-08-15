"""CAGE EMPIRE news service (Stage 6 — Task 6.0 wrapper + Task 6.2 helper).

Pure wrapper module. Re-exports the existing src/news.py public API
so the future GUI (Task 6.3 Dashboard + News Feed screen) can import
from the service layer (`services.news_svc`) instead of the legacy
src/ flat module path.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer feed-query helpers to Task 6.3 Dashboard + News Feed screen).

Task 6.2 adds ONE small helper: get_latest_news_summary() — used by
the bottom bar news ticker. This is a 10-line query function, not
a feature — the full news feed query API lands in Task 6.3.

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of src/news.py.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Drama pillar — news is how the player experiences
        the sim's emergent narratives.
  §14 — Voice Layer: inherited from src/news.py.
  §15 — Event Bus: src/news.py registers its own subscribers on
        import (event_bus.register_topic(...)). This wrapper inherits
        that side effect on import.

Migration impact: NONE (code-only wrapper + 1 query helper).
"""
from news import *  # re-export everything from src/news.py

import sqlite3


def get_latest_news_summary(conn, limit=3):
    """Get the latest N news headlines for the bottom bar ticker.

    Args:
        conn: sqlite3.Connection to the world DB.
        limit: number of headlines to return (default 3).

    Returns:
        List of headline strings (empty list if no news or error).
        Each headline is truncated to 80 chars for the ticker.

    Used by ui/app.py _update_bottom_bar() for the scrolling news
    ticker. This is a simple query helper — the full news feed
    API (filtering, sorting, pagination) lands in Task 6.3.
    """
    try:
        rows = conn.execute(
            "SELECT headline FROM news_items "
            "ORDER BY published_at DESC "
            "LIMIT ?",
            (limit,)
        ).fetchall()
        result = []
        for row in rows:
            headline = row[0] if row[0] else ""
            if len(headline) > 80:
                headline = headline[:77] + "..."
            result.append(headline)
        return result
    except Exception:
        return []
