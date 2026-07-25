"""CAGE EMPIRE news service (Stage 6 — Task 6.0 wrapper).

Pure wrapper module. Re-exports the existing src/news.py public API
so the future GUI (Task 6.3 Dashboard + News Feed screen) can import
from the service layer (`services.news_svc`) instead of the legacy
src/ flat module path.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer feed-query helpers to Task 6.3 Dashboard + News Feed screen).

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

Migration impact: NONE (code-only wrapper).
"""
from news import *  # re-export everything from src/news.py
