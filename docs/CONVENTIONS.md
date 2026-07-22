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

### 1.5 Dual-mode build (added Task 16.6)

Since v2.6.0, `build_db.py` supports two modes: `--fresh` (drop +
rebuild, default) and `--migrate` (apply pending migrations to the
existing DB, preserve data). The version-check gate in §1.4 applies
only to `--fresh`. The `--migrate` path has no such gate — it can
migrate a same-version or older DB. See §16 for the full migration
workflow.

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
2. `docs/CAGE_EMPIRE_SOUL.md` — **prime directive**. The project's
   purpose. Read this FIRST — it defines what "success" means.
3. `docs/MASTER_PLAN.md` — current state and revised principle.
4. `docs/STAGES.md` — what task are we on, what's next.
5. `docs/CONVENTIONS.md` (this file) — the rules.
6. `docs/SCHEMA_DRIFT_AUDIT.md` — what tables exist and what's
   missing.
7. `CHANGELOG.md` — what's changed recently.
8. The supervisor's `worklog.md` — full history of every task.

Skipping any of these will cause the agent to miss context and
likely repeat past mistakes. The supervisor's first instruction to
any subagent will be "read these 8 files, then start".

**IMPORTANT for Stage 3+:** Also check `docs/SCHEMA_DRIFT_AUDIT.md §Z`
for known issues and gaps. The §Z section documents critical gaps
(e.g., fighter_attributes still at 4/25 stats) that may block
downstream tasks.

**IMPORTANT for ALL tasks:** Every task must be evaluated against
the CAGE EMPIRE Design Law (§13). The supervisor will ask: "Which
of the 5 pillars does this strengthen? What stories does it generate?"

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

---

## 13. CAGE EMPIRE Design Law (Prime Directive)

> **Source:** `docs/CAGE_EMPIRE_SOUL.md` — the project's north star.

### 13.1 The Law

> The player does not collect fighters. The player collects stories.
>
> Every major system must contribute to:
> 1. **Discovery** — finding talent, uncovering hidden potential
> 2. **Investment** — signing, training, developing fighters
> 3. **Growth** — fighters improving, careers progressing
> 4. **Conflict** — fights, rivalries, title battles
> 5. **Legacy** — hall of fame, records, memories, history
>
> If a feature does not strengthen one of those five pillars, it is
> probably not worth building.

### 13.2 Enforcement

At every task review, the supervisor MUST ask:

1. **Which of the 5 pillars does this task strengthen?** If the answer
   is "none" or "unclear," the task should be reconsidered.
2. **What stories does this system generate?** If the answer is "none"
   or "just numbers moving," the system needs a narrative layer.
3. **Does this create anticipation?** The player should always have
   something coming — a prospect developing, a champion aging, a
   rivalry building. Systems that don't create anticipation are
   support systems, not core systems.

### 13.3 The Interpretation Layer

The voice/interpretation layer (Task 19) is not a technical utility —
it is the **machinery that translates simulation into emotion**. Its
true purpose:

- Raw: `Age 37, Losses 4, Durability down 12%`
- Meaning: `His best years may be behind him.`

Every system that produces data the player sees must eventually route
through the interpretation layer. Raw numbers are for debugging; the
player sees meaning.

### 13.4 Success Metric

**Do not measure success by number of systems built.**

**Measure success by number of stories generated.**

A good outcome: "36-year-old former champion returns after 4 years
away, upsets undefeated prospect, triggers a comeback storyline.
Player remembers forever."

A bad outcome: "New ranking algorithm added. Player doesn't care."

### 13.5 Anticipation Principle

Players should constantly have unresolved threads:
- The prospect just signed (when will they fight?)
- The champion nearing retirement (who takes over?)
- The rivalry exploding (when's the rematch?)
- The gym producing talent (who's next?)
- The event next month (what's the card?)

**Something is always coming. Something is always developing.
Something is always unresolved.** That's what keeps people clicking
Advance Day for another 500 hours.

### 13.6 The 5 Core Fantasies

Every system should serve at least one of these player fantasies:

| Fantasy | Player desire | Example systems |
|---|---|---|
| **Talent Hunter** | "I find greatness before anyone else" | Scouting, regen, hidden potential |
| **Empire Builder** | "My promotion dominates the sport" | Finances, prestige, TV deals, champions |
| **Kingmaker** | "I create stars" | Matchmaking, hype, rankings, media |
| **Historian** | "The world remembers what I built" | Hall of fame, records, legacy, lineage |
| **Puppet Master** | "The sport evolves because of my decisions" | Rivalries, gym ecosystems, promotion AI |

### 13.7 Required Reading

Every agent (human or AI) working on CAGE EMPIRE MUST read
`docs/CAGE_EMPIRE_SOUL.md` before starting any task. The Soul document
is the prime directive. The CONVENTIONS.md rules are the mechanics;
the Soul document is the purpose.

---

## 14. Interpretation Layer — Core Directive

### 14.1 The Rule

**No raw attribute values, potential numbers, or internal ratings
appear in the player-facing UI.** All numbers pass through the
interpretation layer (`src/voice.py`, Task 19) and are displayed as
human-readable descriptors.

Raw: `potential=72, punch_power=58, chin=62`
Player sees: `Solid prospect with above-average power and a respectable chin.`

### 14.2 Why

The Soul document states: "Translate simulation into emotion." Raw
numbers are for debugging; the player sees meaning. This is what makes
CAGE EMPIRE unique — the player experiences stories, not spreadsheets.

### 14.3 Threshold-Based Descriptors

The interpretation layer uses **banded descriptors** that only update
when a fighter's attribute crosses a band boundary:
- 90-100 = "elite", 75-89 = "above-average", 60-74 = "solid",
  40-59 = "average", 25-39 = "below-average", 10-24 = "poor",
  0-9 = "abysmal"

A fighter whose cardio drops from 76 to 74 sees their descriptor change
from "above-average" to "solid". A drop from 76 to 75 does NOT change
the descriptor. This prevents descriptor flickering and makes
descriptions stable until a meaningful threshold is crossed.

### 14.4 Architecture Requirement

Every system that produces text the player sees MUST route through the
interpretation layer. This includes:
- Fighter profile blurbs
- Scouting reports (Task 18)
- News items (Task 23)
- Commentary (Task B2)
- Punditry (Task 24)
- Hall of fame / legacy descriptions (Task 31)
- Event summaries / show ratings (Task 26)

Systems that produce raw data (the fight engine, the tick processor,
the contract system) do NOT call the interpretation layer directly —
they store raw numbers in the DB. The interpretation layer is called
by the UI and the text-generation systems when they need to display
or narrate the data.

### 14.5 Implementation Timing

The interpretation layer (Task 19) is built in Stage 3b, after the
full 25-attribute set (Task 14.5) is available. Systems built before
Task 19 (the beat engine, injuries, camps, weight cuts) store raw
numbers and produce hardcoded text. When Task 19 lands, these systems
are retrofitted to route through it. After Task 19, all new systems
MUST use the interpretation layer from day one.

---

## 15. Event Bus (implemented Task 18.5)

### 15.1 Architecture

`src/event_bus.py` provides a lightweight in-memory pub/sub system.
Game actions (resolve_next_fight, run_tick) publish events; game
systems subscribe to the events they care about. The bus is
synchronous, in-memory, and defensive (subscriber errors are caught).

### 15.2 Event Types

16 event types defined in `Events`:
- FIGHT_RESOLVED, FIGHT_CANCELLED, TITLE_CHANGED, EVENT_COMPLETED
- FIGHTER_RETIRED, FIGHTER_SIGNED, FIGHTER_GENERATED
- CONTRACT_EXPIRED
- CAMP_COMPLETED, CAMP_INJURY
- INJURY_CREATED, INJURY_RECOVERED
- WEIGHT_CUT_COMPLETED
- SCOUT_REPORT_GENERATED
- FIGHTER_STATE_CHANGED
- TICK_ADVANCED

### 15.3 Usage

```python
from event_bus import get_bus, Events

bus = get_bus()
bus.subscribe(Events.FIGHT_RESOLVED, my_system.handle_fight)
# ... later, when a fight resolves:
# resolve_next_fight publishes FIGHT_RESOLVED automatically
# my_system.handle_fight is called with (conn, event_dict)
```

### 15.4 Design Rules

- **No DB table** — events are transient. The DB stores results.
- **Synchronous** — CAGE EMPIRE is single-threaded.
- **Additive** — existing inline side effects remain. The event bus
  is for NEW subscribers (Stage 4+), not a replacement.
- **Defensive** — broken subscribers don't crash the game.
- **Stage 4+ systems MUST use the event bus** — no new inline side
  effects in resolve_next_fight or run_tick. All new systems subscribe
  to events instead.

---

## 16. Database Build & Migration Workflow

### 16.1 The Dual-Mode Pattern

`src/build_db.py` supports two modes:

| Mode | Command | Effect |
|---|---|---|
| Fresh | `python src/build_db.py --fresh` (or default, no flag) | Drops the DB file and rebuilds from `SCHEMA_SQL`. Destroys all data. |
| Migrate | `python src/build_db.py --migrate` | Applies pending migrations to the existing DB. Preserves all data. |

**Default mode is `--fresh`.** This is what tests use (they rebuild a 5-fighter toy DB on every test run). **The seeded world DB uses `--migrate` exclusively** — once the world is seeded, we never drop it.

### 16.2 When to Use Which

- **Tests** → `--fresh` (or no flag). Tests rebuild from scratch on every run. The 19 acceptance tests in `scripts/test_*.py` all use `--fresh`.
- **Development** → `--fresh`. When iterating on schema, drop + rebuild is faster than writing a migration.
- **Seeded world DB** → `--migrate`. Once `scripts/seed_world_phase1.py` through `phase5.py` have been run, the DB is the world. Future schema changes (Tasks 17-30) ship a migration function and the player/updater runs `python src/build_db.py --migrate` to apply it. **Never run `--fresh` on a seeded DB** — it destroys 4000 fighters and 30000+ fight_history rows.

### 16.3 The Migration Registry

Every schema change since v2.2.0 has a migration function in `build_db.py`:

```python
def _migrate_v2_X_0_your_name(conn):
    """Task ID — short description. Idempotent."""
    if not _has_column(conn, "table", "col"):
        conn.execute("ALTER TABLE table ADD COLUMN col TYPE ...")
    if not _has_table(conn, "new_table"):
        conn.execute("CREATE TABLE new_table (...)")
```

These functions are registered in the `MIGRATIONS` list at the bottom of `build_db.py`:

```python
MIGRATIONS = [
    ("v2_2_0_add_fighter_depth",    "2.2.0", _migrate_v2_2_0_add_fighter_depth),
    ("v2_3_0_add_beat_engine_depth","2.3.0", _migrate_v2_3_0_add_beat_engine_depth),
    # ... append new migrations here ...
]
```

The migration runner (`_run_migrations`) iterates `MIGRATIONS` in order. For each entry, it checks if the migration_name is already in `schema_migrations`. If yes, skip. If no, run the function + record the name.

### 16.4 Idempotency Rule (CRITICAL)

**Every migration function MUST be idempotent.** It MUST check the current schema state (`_has_column`, `_has_table`, `_has_check_constraint`) before applying its change. This is REQUIRED because:

1. **Crash safety:** if a migration crashes mid-way (e.g., power loss, bug), the next `--migrate` run re-executes it. Partial work must be safe to re-apply.
2. **Fresh-build consistency:** the `--fresh` path also records every migration name in `schema_migrations` (because `SCHEMA_SQL` already includes every table/column). The migration functions are NOT called on `--fresh`, but they could be — the idempotency guards make this safe.
3. **Order independence:** if a future migration depends on an earlier one having run, the `MIGRATIONS` list order guarantees it. The idempotency guards handle the case where the earlier migration was a no-op (e.g., the column was already added by `SCHEMA_SQL`).

### 16.5 Adding a New Migration (Workflow)

When a task adds or changes schema:

1. **Update `SCHEMA_SQL`** in `build_db.py`. The fresh-build path uses this. New tables/columns go here as `CREATE TABLE IF NOT EXISTS` / the column appears in the table definition.
2. **Write a migration function** `_migrate_v2_X_0_your_name(conn)`. Use `ALTER TABLE` for new columns, `CREATE TABLE IF NOT EXISTS` for new tables. Guard every change with `_has_column` / `_has_table`.
3. **Append to `MIGRATIONS`** with the new version string + function reference.
4. **Bump `CODE_SCHEMA_VERSION`** per §1.1 rules (PATCH/MINOR/MAJOR).
5. **Update the migration name in the function's docstring** (`Migration name: v2_X_0_your_name`).
6. **Test both paths:** `python src/build_db.py` (fresh) and `python src/build_db.py --migrate` (migrate an older DB).
7. **Run the acceptance tests** to verify nothing broke.

### 16.6 SQLite ALTER TABLE Limitations

SQLite's `ALTER TABLE` supports only:
- `ADD COLUMN` (with restrictions — can't add NOT NULL without DEFAULT, can't add CHECK that references existing rows)
- `RENAME TABLE`
- `RENAME COLUMN` (SQLite 3.25+)
- `DROP COLUMN` (SQLite 3.35+)

SQLite does NOT support:
- Adding a CHECK constraint to an existing column (requires table rebuild)
- Modifying a column's type (requires table rebuild)
- Adding a FOREIGN KEY to an existing column (requires table rebuild)
- Removing a column's NOT NULL (requires table rebuild)

**Table rebuild pattern** (rare — only when a CHECK or type changes):

```python
conn.executescript("""
    ALTER TABLE old_table RENAME TO old_table_backup;
    -- CREATE the new table with the updated schema
    CREATE TABLE old_table (...);
    -- COPY data from backup, transforming as needed
    INSERT INTO old_table (cols) SELECT cols FROM old_table_backup;
    DROP TABLE old_table_backup;
""")
```

The migration function `_migrate_v2_3_0_add_beat_engine_depth` in `build_db.py` shows this pattern in use (rebuilding `fight_beats` to expand the `outcome` CHECK constraint).

### 16.7 Version-Check Gate (Task 5, preserved)

The `--fresh` path refuses to run if the on-disk schema is NEWER than `CODE_SCHEMA_VERSION` (the Task 5 gate). This prevents an older `build_db.py` from silently clobbering a newer schema.

The `--migrate` path has no such gate — it can migrate a same-version or older DB. If the on-disk version is NEWER than code, `--migrate` prints a warning and does nothing (the upgrade direction is "code leads, DB follows").

### 16.8 The Seed Layer

`src/seed_data.py` is the **minimal playable seed** — 5 fighters, 2 gyms, 2 promotions, 1 weight class, 1 event. Used by tests and dev. Run AFTER `--fresh`:

```
python src/build_db.py        # fresh build (default)
python src/seed_data.py       # minimal seed
```

`scripts/seed_world_phase1.py` through `phase5.py` are the **full world seed** — 20 nations, 60 regions, 150 cities, 300 gyms, 8-12 promotions, 4000 fighters, career histories, bios, hall of fame. Run once on a fresh DB:

```
python src/build_db.py                            # fresh build
python scripts/seed_world_phase1.py               # nations/regions/cities/venues/WCs/names
python scripts/seed_world_phase2.py               # gyms/promotions/staff
python scripts/seed_world_phase3.py               # fighters (4000)
python scripts/seed_world_phase4.py               # career histories/fights/titles/rankings/contracts/injuries
python scripts/seed_world_phase5.py               # bios/gym histories/legends/memory/news
```

After all 5 phases run, the DB at `data/cage_empire.db` IS the world. The game loads it directly. The player never runs seed scripts.

Future code changes (Tasks 17-30) ship migrations:

```
git pull
python src/build_db.py --migrate                  # apply new migrations, preserve world data
```

### 16.9 Backups

Before running `--migrate` on the production world DB, **always back up**:

```
cp data/cage_empire.db data/cage_empire.db.backup-$(date +%Y%m%d)
python src/build_db.py --migrate
```

If the migration fails or produces unexpected results, restore from backup. The migration runner does NOT auto-backup — this is the operator's responsibility.
