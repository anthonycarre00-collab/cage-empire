# CAGE EMPIRE — Conventions

> **Status:** Authoritative. Violations will be rejected at code review.
> **Last revised:** 2026-07-21 — Task ID 14 (Stage 2 complete, audit pass).

This file defines the rules every agent (human or AI) must follow
when touching the CAGE EMPIRE codebase. It exists because the project
has already lost ~13 tables and dozens of columns to silent schema
drift, and the only way to stop that is to make the rules explicit
and enforce them.

---

## 1. Schema versioning

### 1.1 The version constant

Every `src/build_db.py` file MUST declare a `CODE_SCHEMA_VERSION`
constant at the top:

```python
CODE_SCHEMA_VERSION = "1.2.1"  # MAJOR.MINOR.PATCH
```

Versioning follows semver, adapted for schema:

| Bump type | When to use |
|---|---|
| `PATCH` (1.2.0 → 1.2.1) | Restoring a dropped table, fixing a constraint, adding an index, no new gameplay tables |
| `MINOR` (1.2.1 → 1.3.0) | Adding a new table or new columns to an existing table |
| `MAJOR` (1.3.0 → 2.0.0) | Removing a table, renaming a column, breaking change to existing data shape |

### 1.2 The `schema_meta` table

Every build MUST write a row to `schema_meta` recording the current
version:

```sql
CREATE TABLE IF NOT EXISTS schema_meta (
    schema_name    TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

On rebuild, `INSERT OR REPLACE` the row with `schema_name = 'cage_empire'`
and `schema_version = CODE_SCHEMA_VERSION`.

### 1.3 The `schema_migrations` table

Every version bump MUST add a row to `schema_migrations`:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

The `migration_name` should describe what changed, e.g.
`v1_3_0_add_fight_history_table`. On rebuild, `INSERT OR IGNORE` the
migration name.

### 1.4 The version-check gate (enforced since Task ID 5)

`build_db.py` `main()` MUST check the on-disk `schema_meta.schema_version`
before unlinking the DB file:

- If on-disk version > code version: **abort** with a clear
  `RuntimeError`. This prevents an older script from silently
  clobbering a newer schema.
- If on-disk version < code version: proceed (we are upgrading).
- If on-disk version == code version: proceed (we are rebuilding the
  same version — allowed for dev reset).
- If no `schema_meta` table exists (fresh DB): proceed.

This gate has been enforced since Task ID 5 (v1.3.0). The
`_compare_versions()` helper uses semver comparison (not string
comparison) so `"1.10.0"` correctly sorts after `"1.9.0"`.

---

## 2. CHANGELOG.md

### 2.1 Location

`CHANGELOG.md` lives at the repo root.

### 2.2 Format

Follows [Keep a Changelog](https://keepachangelog.com/) format. Top
of file always has an `[Unreleased]` section. When a version is
released (tagged in git), the `[Unreleased]` section becomes a
versioned section and a new empty `[Unreleased]` is added.

```markdown
## [Unreleased]

### Added
- New feature X.

### Changed
- Y now does Z.

### Fixed
- Bug in W.

## [1.2.1] - 2026-07-21

### Added
- schema_meta + schema_migrations tables (restored from earlier draft).
- ...
```

### 2.3 Rules

- Every task MUST add at least one entry under `[Unreleased]` before
  commit.
- Entries are written in past tense ("Added", not "Add").
- Each entry references the Task ID in parentheses if non-trivial:
  `- Real attribute-based fight resolver (Task ID 3)`.
- When a version is released, move `[Unreleased]` content to a new
  versioned section, bump version in `build_db.py`, tag the commit
  with `vX.Y.Z`.

---

## 3. worklog.md

### 3.1 Location

`worklog.md` lives at the project root on the supervisor's machine
(`/home/z/my-project/worklog.md`). It is NOT committed to the repo —
it is the supervisor's private log of every delegated task.

### 3.2 Format

Every task appends a section starting with `---`:

```markdown
---
Task ID: <id>
Agent: <agent name>
Task: <one-line description>

Work Log:
- Step 1.
- Step 2.

Stage Summary:
- Key results.
- Decisions made.
- Files changed.
- Schema version produced.

Open questions for the user:
1. ...
```

### 3.3 Rules

- Every task appends, never overwrites.
- Task ID format: `N` for sequential, `N-a` / `N-b` for parallel.
- The supervisor's sign-off line goes at the end of the Stage Summary:
  `Supervisor sign-off: APPROVED` or
  `Supervisor sign-off: REJECTED — reason`.

---

## 4. SCHEMA_DRIFT_AUDIT.md

### 4.1 Location

`docs/SCHEMA_DRIFT_AUDIT.md` lives in the repo.

### 4.2 Rules

- Every schema-change task MUST update this file in the same commit.
- For each table touched, update the relevant row's "Built vX.Y.Z"
  column and the "Status" column.
- At the bottom of the file, update the "Summary counts" table.
- If a table is added, mark its previous status as `MISSING` and new
  status as `OK` (or `THIN` if columns are still missing).
- If a table is removed (should be rare), mark its status as `DROPPED`
  and add a note explaining why.

---

## 5. Task structure (one table-group per task)

### 5.1 The rule

A single task may add at most **one logical group of tables**. A
group is a set of tables that all support the same feature (e.g.
"contracts" = `contracts` + `fighter_contracts` + `staff_contracts`
+ `broadcast_contracts` is one group).

A task may NOT:
- Add contracts AND rankings in the same task.
- Add 60 missing tables in one big-bang commit.
- Add a table without a writer and a reader.

### 5.2 Why

This rule exists because the project already lost 13 tables to the
"write big schema → hit errors → shrink to fix" cycle. One group per
task keeps the blast radius small and makes each task testable.

### 5.3 Every new table must ship with code

A new table is not "done" until at least one of these writes to it
and at least one of these reads from it:

- `src/seed_data.py` (writer)
- `src/tick_processor.py` (writer, on tick)
- `src/app.py` (reader, in the UI)
- A new module under `src/` (reader and/or writer)

A table with no code path is a failure. The supervisor will reject
the task.

---

## 6. Smoke test protocol

Every task MUST be smoke-tested locally before commit. The protocol:

```bash
cd /home/z/my-project/cage_empire

# 1. Rebuild
python3 src/build_db.py
# Expected: "Rebuilt database at .../data/cage_empire.db"

# 2. Seed
python3 src/seed_data.py
# Expected: "Seeded database."

# 3. Tick
python3 src/tick_processor.py
# Expected: "Tick advanced."

# 4. Verify
python3 -c "
import sqlite3
conn = sqlite3.connect('data/cage_empire.db')
conn.execute('PRAGMA foreign_keys = ON;')
print('Tables:', [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()])
print('Schema version:', conn.execute(\"SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'\").fetchone())
print('Fighters:', conn.execute('SELECT COUNT(*) FROM fighters').fetchone()[0])
print('Events:', conn.execute('SELECT COUNT(*) FROM events').fetchone()[0])
"
```

If any step fails, fix before commit. If the failure is in code the
subagent wrote, the supervisor bounces it back with the error.

---

## 7. Git commit format

### 7.1 Commit message

```
<tag>: <one-line summary>

<body explaining what changed, referencing Task ID and schema version>

<CHANGELOG excerpt>
```

Tags:
- `feat:` — new feature or table
- `fix:` — bug fix
- `docs:` — documentation only
- `chore:` — housekeeping (rename, version bump)
- `refactor:` — code restructure, no behaviour change

Example:
```
feat: real attribute-based fight resolver (Task ID 3)

Replaces the coin-flip resolve_next_fight() with a probabilistic
function that reads fighter_attributes (punch_power, cardio,
fight_iq, chin) and fighter_personality (aggression, composure,
morale). Better fighter wins ~80% of the time over 100 sims.

Schema version: 1.2.1 (no schema change in this task).

CHANGELOG:
- Added: real attribute-based fight resolver (Task ID 3).
```

### 7.2 Branching

For now (single contributor + supervisor), all work goes on `main`.
When the contributor count grows past 1, switch to feature branches
(`feat/task-N-fight-resolver`) with PR review.

---

## 8. Cross-session handoff protocol

When a new AI agent (or a new session of the same agent) starts work
on CAGE EMPIRE, they MUST read these files in this order before
touching anything:

1. `README.md` — project overview.
2. `docs/MASTER_PLAN.md` — current state and revised principle.
3. `docs/STAGES.md` — what task are we on, what's next.
4. `docs/CONVENTIONS.md` (this file) — the rules.
5. `docs/SCHEMA_DRIFT_AUDIT.md` — what tables exist and what's
   missing.
6. `CHANGELOG.md` — what's changed recently.
7. The supervisor's `worklog.md` — full history of every task.

Skipping any of these will cause the agent to miss context and
likely repeat past mistakes. The supervisor's first instruction to
any subagent will be "read these 7 files, then start".

**IMPORTANT for Stage 3+:** Also check `docs/SCHEMA_DRIFT_AUDIT.md §Z`
for known issues and gaps. The §Z section documents critical gaps
(e.g., fighter_attributes still at 4/24 stats) that may block
downstream tasks.

---

## 9. Decision log

Major design decisions get recorded in `docs/MASTER_PLAN.md` §10.
A decision is "major" if it changes the project's direction, kills
a planned task, or introduces a new convention. Examples:

- 2026-07-21 — Original Task 2 (big-bang v1.6 schema dump) killed.
- 2026-07-21 — DB renamed to `cage_empire.db`.
- 2026-07-21 — One table-group per task rule adopted.
- 2026-07-21 (Task 9) — Dynamic-version pattern adopted for tests.
- 2026-07-21 (Task 14) — 10 designed regen tables consolidated into 3.

Minor decisions (which folder a module goes in, which variable name
to use) do not need to be logged.

---

## 10. Dynamic-version pattern for acceptance tests (adopted Task ID 9)

### 10.1 The rule

Every acceptance test MUST read the schema version dynamically from
`build_db.CODE_SCHEMA_VERSION` — do NOT hardcode version strings like
`'1.5.0'` or `'1.9.0'`.

### 10.2 The pattern

```python
import sys
sys.path.insert(0, str(SRC_DIR))
import build_db  # noqa: E402

EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"
```

Then use `EXPECTED_CODE_VERSION` in assertions:
```python
sv = conn.execute(
    "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
).fetchone()
assert sv[0] == EXPECTED_CODE_VERSION
```

And use `EXPECTED_MIGRATION_PREFIX` with a LIKE query for migration
name checks (the description suffix changes per task: `_add_fight_history`,
`_add_contracts`, `_add_rankings`, etc.):
```python
mig = conn.execute(
    "SELECT migration_name FROM schema_migrations "
    "WHERE migration_name LIKE ?",
    (EXPECTED_MIGRATION_PREFIX + "%",),
).fetchone()
assert mig is not None
```

### 10.3 Why

Before this pattern was adopted (Tasks 9-11), every schema version bump
broke 2-3 existing tests that hardcoded the old version string. The
supervisor had to apply fixes in every sign-off. Since adopting the
dynamic pattern (Task 10+), the last 2 tasks (12, 13) needed no
supervisor test fix. The pattern is now self-sustaining.

### 10.4 Table-count assertions

Do NOT hardcode table counts in acceptance tests (e.g.,
`EXPECTED_TABLE_COUNT = 34`). Table counts change on every schema-
adding task. The test's purpose is to verify behavior, not table count.
If a test needs to verify that a specific table exists, use
`SELECT 1 FROM sqlite_master WHERE type='table' AND name=?` instead.

(Task 14 supervisor fix: `test_free_agency.py` had
`EXPECTED_TABLE_COUNT = 34` which broke when Task 14 added 3 tables.
The assertion was removed entirely.)

---

## 11. "Don't modify existing tests" rule with supervisor escalation

### 11.1 The rule

Subagents MUST NOT modify existing acceptance tests. If a version bump
or behavior change breaks an existing test's assertion, the subagent
flags it and the supervisor applies the fix.

### 11.2 The escalation protocol

1. The subagent identifies the broken assertion and its cause (e.g.,
   "test_fight_history.py line 364 asserts title_at_stake=0 but Task 11
   changed it to 1").
2. The subagent documents the issue as a **D-number decision** in its
   worklog entry (e.g., "D6: test_fight_history.py title_at_stake=0
   placeholder assertion is now stale. Flagged for supervisor. NOT
   modified per the brief's rule.").
3. The subagent returns the flag in its return message to the
   supervisor.
4. The supervisor applies the fix during the sign-off verification,
   documenting it in the supervisor verification section of the
   worklog.

### 11.3 D-number decision pattern

Every subagent worklog entry should document its decisions using
D-numbers (D1, D2, D3, ...). D-numbers are referenced in the
supervisor's sign-off (e.g., "D3 APPROVED", "D5 NOTED, not fixed").
This creates a traceable audit trail of every decision made.

### 11.4 History

This pattern was established in Task 9 (first schema version bump that
broke existing tests). It has been used in Tasks 9, 10, 11, 13, and 14.
The most common fix is the dynamic-version pattern (§10). Other fixes
include updating stale assertions (Task 11: title_at_stake [0,0] →
[1,1]) and removing obsolete table-count checks (Task 14).

---

## 12. Test location

Acceptance tests live in `scripts/` (not `tests/` as originally
planned in the STAGES.md cross-cutting work section). This is a minor
convention deviation — the tests are alongside the generation scripts.
The `scripts/` directory contains:
- `test_fight_resolver.py` (Task 3)
- `test_fight_history.py` (Task 4)
- `test_schema_versioning.py` (Task 5)
- `test_promotion_filter.py` (Task 6)
- `test_event_lifecycle.py` (Task 7)
- `test_event_scheduler.py` (Task 8)
- `test_contracts.py` (Task 9)
- `test_rankings.py` (Task 10)
- `test_titles.py` (Task 11)
- `test_retirement.py` (Task 12)
- `test_free_agency.py` (Task 13)
- `test_regen.py` (Task 14)

12 tests, 500+ sub-checks, all passing.
