"""CAGE EMPIRE finance service (Stage 6 — Task 6.0 wrapper).

Pure wrapper module. Re-exports the existing src/finance.py public
API so the future GUI (Task 6.10 Finance screen) can import from the
service layer (`services.finance_svc`) instead of the legacy src/
flat module path.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer `process_event_finances` + weekly cashflow tick to Task 6.10
Finance screen).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of src/finance.py.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Empire Management pillar — finance is the
        economic engine of the player's promotion.
  §14 — Voice Layer: inherited from src/finance.py.
  §15 — Event Bus: N/A — finance operations publish through their
        own subscribers (defined in src/finance.py).

Migration impact: NONE (code-only wrapper).
"""
from finance import *  # re-export everything from src/finance.py
