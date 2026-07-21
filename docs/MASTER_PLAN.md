# CAGE EMPIRE — Master Plan

> **Status:** Living document. Every task this supervisor delegates will
> reference this file. Update it whenever a stage is closed out.
> **Last revised:** 2026-07-21 — Task ID 2 (planning + housekeeping).

---

## 1. Where we actually are right now

CAGE EMPIRE is a **working skeleton**, not an early version of the designed
game. That is intentional and correct — getting a thin end-to-end slice
running before adding depth is the right call. But it is worth being
clear-eyed about what exists vs. what was designed.

### Built (v1.2.0, commit `986d438`)

| Layer | State |
|---|---|
| Database | 24 user tables (SQLite) |
| Schema versioning | **none** (this is a problem — see §4) |
| Fighter attributes | 4 stored (`punch_power`, `cardio`, `fight_iq`, `chin`) — **not read by any code** |
| Fighter personality | 3 stored (`aggression`, `composure`, `morale`) — **not read by any code** |
| Tick processor | Calendar advance only — no simulation effects |
| Fight resolution | `random.randint(1, 100) > 50` coin flip |
| Event lifecycle | `status = 'scheduled'` forever — nothing transitions it |
| Repeatable events | **none** — after the one seeded fight resolves, the world is dead |
| UI | Tkinter 3-pane (fighters / events+fights / news+commentary), 3 buttons |
| Staff | Table exists and seeded, **but UI never shows them** |
| Rival promotions | **none** — single promotion only |
| Finances | `promotions.current_cash` column only — no P&L, no burn rate |
| Scouting | **none** |
| Contracts | **none** (only `current_promotion_id` FK on fighter) |
| Rankings / titles | **none** |
| Injuries / camps / weight cuts | **none** |
| Social / rivalries / news templates | **none** (2 hardcoded string templates only) |
| Regen / lineage / memory | **none** |
| Voice / interpretation layer | **none** |
| Mod tools / name pools | **none** |
| Audit trail / changelog | **none** |

### Designed (per the v1.6 spec, 509-page chat transcript)

| Layer | Target |
|---|---|
| Database | 83+ tables (see `SCHEMA_DRIFT_AUDIT.md`) |
| Fighter attributes | 24 combat stats + 17 personality traits |
| Tick | day / week / event / season — each runs different systems |
| Fight resolution | Attribute-driven, probabilistic, round-by-round, with commentary beats |
| Event lifecycle | scheduled → in_progress → completed → archived |
| Repeatable events | Auto-scheduling of next card |
| Rival promotions | Multiple, AI-driven, competing for talent |
| Finances | Full P&L, burn rate, forecasts, budget allocation |
| Scouting | Scout reports as objects, quality driven by scout skill + budget |
| Contracts | Length, exclusivity, pay, bonuses, clauses, renewals |
| Rankings / titles | Belt hierarchy, contenders, interim, lineal |
| Injuries / camps / weight cuts | Severity, recovery timelines, camp morale/fatigue |
| Social / rivalries | Posts, replies, beefs, fan reactions |
| Regen / lineage / memory | Style DNA, region templates, memory resurfacing |
| Voice / interpretation layer | Numeric stats → readable descriptors everywhere |
| Mod tools | Fighter / promotion / venue / contract / commentary editors, CSV+JSON+portrait import |
| Audit trail / changelog | `schema_meta` + `schema_migrations` + `CHANGELOG.md` |

The gap between these two columns is what the rest of this plan closes.

---

## 2. Why we are not doing the original Task 2 (big-bang v1.6 schema dump)

The original plan was: delegate one task to a subagent that adds all ~60
missing tables in a single pass. **That plan is killed.** Reasons:

1. **It already failed twice.** The schema went 37 → 24 tables between two
   earlier "reset bundles" with no flag raised. The pattern was: write a
   big schema → hit errors → shrink to make errors go away → lose design
   work → repeat. A 60-table dump would replay this exact failure mode.

2. **It is untestable.** If 60 tables land in one commit and one of them
   has a broken FK or a check constraint that conflicts with the seed,
   finding which one is hard. With one table-group per commit, the blast
   radius is small.

3. **It produces dead tables.** Tables that exist but are not read or
   written by any code are worse than missing tables — they create the
   illusion of progress and rot silently. Every table should land with
   at least one writer and one reader.

4. **It blocks the real priority.** The fight engine is the spine of
   every downstream system. Camps, scouting, personality, finances,
   legacy — all feed into fight resolution. Adding 60 tables before
   fixing the coin-flip resolver means rebuilding the plumbing a second
   time the moment real resolution shows up.

---

## 3. Revised principle — incremental, tested, versioned

Every task from here on must satisfy these rules. Subagents that violate
them will have their work rejected.

1. **One table-group per task.** A task may add at most one logical group
   of tables (e.g. "contracts" = `contracts` + `fighter_contracts` +
   `staff_contracts` + `broadcast_contracts` counts as one group). It may
   not add contracts AND rankings AND titles in the same task.

2. **Every new table must have a writer and a reader in the same task.**
   Either the seed, the tick processor, the app UI, or a new module must
   read from and write to the table. A table with no code path is a
   failure.

3. **Every schema change bumps `schema_meta.schema_version`** and adds
   a row to `schema_migrations`. See `CONVENTIONS.md`.

4. **Every task gets a `CHANGELOG.md` entry** under `[Unreleased]`
   describing what was added / changed / fixed. See `CONVENTIONS.md`.

5. **Every task is smoke-tested locally** before commit. The smoke test
   must include: `python src/build_db.py`, `python src/seed_data.py`,
   `python src/tick_processor.py`, and a manual UI launch check.

6. **Every task appends to `worklog.md`** with the Task ID, the schema
   version it produced, and any decisions made.

7. **No task removes a table or column without an explicit migration.**
   While we are pre-MVP and full rebuilds are acceptable, the version
   must still bump and the CHANGELOG must still record the removal.

---

## 4. The schema drift problem — and how we are closing it

Between two earlier "reset bundle" drafts and the v1.2.0 commit, the
schema lost 13+ tables and dozens of fields without anyone flagging it.
That is the failure mode this plan exists to prevent.

**Closed in Task ID 2 (this task):**
- Restored `schema_meta` and `schema_migrations` tables.
- Added `CHANGELOG.md` at the repo root.
- Wrote `docs/SCHEMA_DRIFT_AUDIT.md` documenting every designed-but-missing
  table and every built-but-thin table.
- Wrote `docs/CONVENTIONS.md` with the schema versioning rules.
- Wrote `docs/STAGES.md` with the 30-task staged buildout.

**Open (closed by Task 5):**
- Make `build_db.py` refuse to run if `schema_meta.schema_version` is
  newer than the code's known version (prevents an older script from
  silently clobbering a newer schema).

---

## 5. Stage breakdown (high-level — see `STAGES.md` for detail)

| Stage | Theme | Tasks | Goal |
|---|---|---|---|
| **1 close-out** | Make the skeleton actually simulate | 3 – 8 | Real fight resolver, repeatable events, fight history, schema versioning, second promotion, event lifecycle |
| **2** | Career systems | 9 – 14 | Contracts, rankings, titles, retirement, free agency, regen |
| **3** | Human layer | 15 – 19 | Injuries, training camps, weight cuts, scouting, voice/interpretation layer |
| **4** | Media & economy | 20 – 24 | Finances, social media, rivalries, news engine, punditry/matchup analysis |
| **5** | AI & polish | 25 – 30 | Rival promotion AI, show rating engine, venues/markets deeper sim, CustomTkinter dark theme, mod tools skeleton, save/load |

Each stage is gated: the next stage does not start until every task in
the previous stage is signed off in `worklog.md`.

---

## 6. What the next commit (Task ID 2) actually contains

This is a **planning + housekeeping** commit, not a feature commit. It
contains no new gameplay. It contains:

- `docs/MASTER_PLAN.md` (this file)
- `docs/STAGES.md`
- `docs/SCHEMA_DRIFT_AUDIT.md`
- `docs/CONVENTIONS.md`
- `CHANGELOG.md` (root)
- `schema_meta` + `schema_migrations` tables restored in `build_db.py`
- DB filename rename: `mma_booking_sim_v1_2.db` → `cage_empire.db`
- Second promotion `Rival Fight League` seeded (inert — no AI yet)
- `README.md` updated with new DB filename + links to docs/
- Schema version bumped: `1.2.0` → `1.2.1`

The next commit (Task ID 3) will be the real attribute-based fight
resolver — the highest-leverage single piece of work, per the advisor's
analysis and per our own §2 reasoning above.

---

## 7. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-21 | Repo stays private | User request |
| 2026-07-21 | DB renamed to `cage_empire.db` | Branding consistency; cleanest moment is during the schema-versioning restoration |
| 2026-07-21 | Original Task 2 (big-bang v1.6 schema dump) killed | Would replay the 37→24 drift failure mode; untestable; produces dead tables; blocks the real priority |
| 2026-07-21 | `schema_meta` + `schema_migrations` restored before any new tables | Cheap insurance; the schema has already drifted twice without anyone flagging it |
| 2026-07-21 | One table-group per task enforced as a hard rule | Makes each task testable; small blast radius; forces every table to ship with a reader+writer |
| 2026-07-21 | Stages are gated — next stage does not start until previous is signed off | Prevents half-built systems stacking up on top of each other |
