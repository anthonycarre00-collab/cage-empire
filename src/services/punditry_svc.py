"""CAGE EMPIRE punditry service (Stage 6 — Task 6.0 wrapper).

Pure wrapper module. Re-exports the existing src/punditry.py public
API so the future GUI (Task 6.7 Fight Resolution screen — where
`staff.pundit_bias` is actually read) can import from the service
layer (`services.punditry_svc`) instead of the legacy src/ flat
module path.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer named-pundit interjection generator to Task 6.7 Fight
Resolution screen, where `staff.pundit_bias` is actually read).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of src/punditry.py.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Drama pillar — punditry is the broadcast voice
        that frames fights for the audience.
  §14 — Voice Layer: inherited from src/punditry.py.
  §15 — Event Bus: src/punditry.py registers its own subscribers
        (FIGHT_RESOLVED → generate_matchup_analysis). This wrapper
        inherits that side effect on import.

Migration impact: NONE (code-only wrapper).
"""
from punditry import *  # re-export everything from src/punditry.py
