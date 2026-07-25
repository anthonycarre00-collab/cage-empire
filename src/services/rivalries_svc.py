"""CAGE EMPIRE rivalries service (Stage 6 — Task 6.0 wrapper).

Pure wrapper module. Re-exports the existing src/rivalries.py public
API so the future GUI (Task 6.9 Rivalries screen) can import from
the service layer (`services.rivalries_svc`) instead of the legacy
src/ flat module path.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer heat decay tick + confrontation triggers to Task 6.9 Rivalries
screen).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of src/rivalries.py.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Drama pillar — rivalries are the recurring
        storylines that keep the sim feeling alive.
  §14 — Voice Layer: inherited from src/rivalries.py.
  §15 — Event Bus: src/rivalries.py registers its own subscribers
        (FIGHT_RESOLVED → maybe_escalate_rivalry). This wrapper
        inherits that side effect on import.

Migration impact: NONE (code-only wrapper).
"""
from rivalries import *  # re-export everything from src/rivalries.py
