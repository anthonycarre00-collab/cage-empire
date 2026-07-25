"""CAGE EMPIRE scouting service (Stage 6 — Task 6.0 wrapper).

Pure wrapper module. Re-exports the existing src/scouting.py public
API so the future GUI (Task 6.5 Scouting screen) can import from the
service layer (`services.scouting_svc`) instead of the legacy src/
flat module path.

NO new code in Task 6.0 (per docs/TASK_6_0_PLAN.md §1.1, Fix #4 —
defer staleness query helpers to Task 6.5 Scouting screen).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it inherits the table footprint of src/scouting.py.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass.
  §13 — Design Law: Talent Hunter pillar — scouting is how the
        player discovers new talent.
  §14 — Voice Layer: inherited from src/scouting.py.
  §15 — Event Bus: N/A — scouting queries don't publish events.

Migration impact: NONE (code-only wrapper).
"""
from scouting import *  # re-export everything from src/scouting.py
