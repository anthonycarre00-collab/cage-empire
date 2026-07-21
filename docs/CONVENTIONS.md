# CAGE EMPIRE — Conventions

> **Status:** Authoritative. Violations will be rejected at code review.
> **Last revised:** 2026-07-21 — Task ID 2.

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

### 1.4 The version-check gate (Task ID 5 will enforce this)

`build_db.py` `main()` MUST check the on-disk `schema_meta.schema_version`
before unlinking the DB file:

- If on-disk version > code version: **abort** with a clear
  `RuntimeError`. This prevents an older script from silently
  clobbering a newer schema.
- If on-disk version < code version: proceed (we are upgrading).
- If on-disk version == code version: proceed (we are rebuilding the
  same version — allowed for dev reset).
- If no `schema_meta` table exists (fresh DB): proceed.

This gate is not enforced in v1.2.1 (the table is restored but not
checked). Task ID 5 closes that gap.

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

---

## 9. Decision log

Major design decisions get recorded in `docs/MASTER_PLAN.md` § 7.
A decision is "major" if it changes the project's direction, kills
a planned task, or introduces a new convention. Examples:

- 2026-07-21 — Original Task 2 (big-bang v1.6 schema dump) killed.
- 2026-07-21 — DB renamed to `cage_empire.db`.
- 2026-07-21 — One table-group per task rule adopted.

Minor decisions (which folder a module goes in, which variable name
to use) do not need to be logged.
