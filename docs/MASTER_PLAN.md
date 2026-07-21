# CAGE EMPIRE — Master Plan

> **Status:** Living document. Every task this supervisor delegates will
> reference this file. Update it whenever a stage is closed out.
> **Last revised:** 2026-07-21 — Task ID 14 (Stage 2 complete, audit pass).

---

## 1. Where we actually are right now

CAGE EMPIRE is a **working simulation** with a full career lifecycle
loop. Stage 1 (skeleton close-out) and Stage 2 (career systems) are
complete. The game now simulates end-to-end: real attribute-based
fight resolution, event lifecycle, repeatable events, contracts,
rankings, titles, retirement, free agency, and regen.

### Built (v1.9.0, commit `347b339`)

| Layer | State |
|---|---|
| Database | 37 tables (SQLite) |
| Schema versioning | `schema_meta` + `schema_migrations` + version-check gate (Task 5) |
| Fighter attributes | 4 stored (`punch_power`, `cardio`, `fight_iq`, `chin`) — **read by the resolver** but spec calls for 24. **CRITICAL GAP — see §Z.1.** |
| Fighter personality | 3 stored (`aggression`, `composure`, `morale`) — **read by the resolver** but spec calls for 17+. **CRITICAL GAP — see §Z.1.** |
| Tick processor | Advances clock + checks retirements (Task 12) + checks contract expiry (Task 13) |
| Fight resolution | Real probabilistic resolver (Task 3): power score from 4 attrs + Gaussian noise + morale/composure modifiers + margin-based result type |
| Event lifecycle | scheduled → in_progress → completed (Task 7) |
| Repeatable events | Auto-schedules next card ~4 weeks out when event completes (Task 8) |
| Contracts | 4 tables (Task 9): polymorphic base + fighter/staff/broadcast subtypes. 12-month exclusive default. UI Contracts tab. |
| Rankings | ELO-style (Task 10): K=32, zero-sum, auto-update on fight resolution. UI Rankings tab. |
| Titles | 10 columns (Task 11): vacant/held, 5-case resolution logic, vacated on retirement. Seeded main event is a title fight. |
| Retirement | Age + career_health based (Task 12): age ≥45 mandatory, age 40-44 + health <60 optional. Retiring champions vacate titles. |
| Free agency | Contract expiry on tick (Task 13): fighter becomes free agent. UI Free Agents tab with Sign button. |
| Regen | Name pools + style DNA (Task 14): retiring fighter generates replacement with same archetype. 96 seeded names. |
| UI | Tkinter 3-pane: left (fighters with promotion filter), center (events + fights), right (Notebook: News & Commentary / Contracts / Rankings / Free Agents). Top bar: Advance Day, Resolve Fight, Refresh, Filter dropdown, clock. |
| Staff | Table exists and seeded (Nina Cross), **but no dedicated Staff UI tab** — see §Z.5. |
| Rival promotions | Rival Fight League seeded (inert, 3 fighters, no events, no AI) — Task 25 will add AI. |
| Finances | `promotions.current_cash` column only — no P&L, no burn rate. Task 20 will add. |
| Scouting | **none** — Task 18. |
| Injuries / camps / weight cuts | **none** — Tasks 15-17. |
| Social / rivalries / news templates | **none** (enriched hardcoded strings only) — Tasks 21-23. |
| Voice / interpretation layer | **none** — Task 19. |
| Mod tools | **none** — Task 29. |
| Audit trail / changelog | `schema_meta` + `schema_migrations` + `CHANGELOG.md` + `worklog.md` (5,800+ lines) + 12 acceptance tests (500+ sub-checks). |

### The "playable forever" loop (closed in Task 14)

```
contracts → fights → rankings → titles → retirement → regen → free agency → signing → contracts (repeat)
```

This is the lifecycle the user asked for in their very first message.
The roster turns over: old fighters retire, new prospects enter as
free agents, the player signs them, they fight, they win titles, they
age, they retire, and the cycle continues.

### Designed (per the v1.6 spec, 509-page chat transcript)

| Layer | Target | Gap |
|---|---|---|
| Database | ~60 logical tables | 37 built, ~23 remaining (see SCHEMA_DRIFT_AUDIT.md) |
| Fighter attributes | 24 combat stats | **4 built (CRITICAL)** — blocks Tasks 16, 18, 19, 24 |
| Fighter personality | 17+ traits | **3 built (CRITICAL)** — same blocker |
| fight_rounds | Per-round stats | **MISSING** — blocks Tasks 23, 24, 26 |
| Tick | day / week / event / season | Day only (advance + retirements + contract expiry) |
| Fight resolution | Attribute-driven, round-by-round, commentary beats | Attribute-driven ✓, round-by-round ✗ (no fight_rounds table), commentary beats ✗ (hardcoded strings) |
| Finances | Full P&L, burn rate, forecasts | `current_cash` column only |
| Scouting | Scout reports as objects | **none** |
| Injuries / camps / weight cuts | Severity, recovery, camp morale/fatigue | **none** |
| Social / rivalries | Posts, replies, beefs, fan reactions | **none** |
| Voice / interpretation layer | Numeric stats → readable descriptors | **none** |
| Mod tools | Editors, CSV+JSON+portrait import | **none** |

---

## 2. Why we are not doing the original Task 2 (big-bang v1.6 schema dump)

The original plan was: delegate one task to a subagent that adds all ~60
missing tables in a single pass. **That plan is killed.** Reasons:

1. **It already failed twice.** The schema went 37 → 24 tables between two
   earlier "reset bundles" with no flag raised.
2. **It is untestable.** One broken FK in a 60-table dump is hard to find.
3. **It produces dead tables.** Tables with no code path rot silently.
4. **It blocks the real priority.** The fight engine is the spine of
   every downstream system.

**This decision has been validated.** Tasks 3-14 delivered 13 new tables
across 12 focused, testable commits. Each table shipped with a writer
and a reader. No silent drift occurred. The incremental approach works.

---

## 3. Revised principle — incremental, tested, versioned

Every task from here on must satisfy these rules. Subagents that violate
them will have their work rejected.

1. **One table-group per task.** A task may add at most one logical group
   of tables.
2. **Every new table must have a writer and a reader in the same task.**
3. **Every schema change bumps `schema_meta.schema_version`** and adds
   a row to `schema_migrations`.
4. **Every task gets a `CHANGELOG.md` entry** under `[Unreleased]`.
5. **Every task is smoke-tested locally** before commit.
6. **Every task appends to `worklog.md`** with the Task ID, schema
   version, and decisions made.
7. **No task removes a table or column without an explicit migration.**
8. **NEW (Task 9+): Every new acceptance test MUST use
   `build_db.CODE_SCHEMA_VERSION` dynamically** — do NOT hardcode the
   version string. This prevents test breakage on version bumps.
9. **NEW (Task 9+): The "don't modify existing tests" rule has an
   escalation protocol.** If a version bump or behavior change breaks
   an existing test's hardcoded assertion, the subagent flags it (D-number
   in the worklog) and the supervisor applies the fix. This has happened
   in Tasks 9, 10, 11, 13, and 14.

---

## 4. The schema drift problem — and how we closed it

Between two earlier "reset bundle" drafts and the v1.2.0 commit, the
schema lost 13+ tables and dozens of fields without anyone flagging it.

**Closed in Task ID 2:**
- Restored `schema_meta` and `schema_migrations` tables.
- Added `CHANGELOG.md` at the repo root.
- Wrote `docs/SCHEMA_DRIFT_AUDIT.md`.
- Wrote `docs/CONVENTIONS.md`.
- Wrote `docs/STAGES.md`.

**Closed in Task ID 5:**
- `build_db.py` refuses to run if on-disk schema is newer than code.
- Semver comparison (`_compare_versions`) correctly handles 1.10.0 > 1.9.0.

**Validated through Tasks 3-14:**
- No silent drift occurred across 12 tasks and 7 schema version bumps.
- The dynamic-version pattern (adopted Task 9+) means tests no longer
  break on version bumps — the last 2 tasks (12, 13) needed no
  supervisor test fix.

---

## 5. Stage breakdown (high-level — see `STAGES.md` for detail)

| Stage | Theme | Tasks | Status |
|---|---|---|---|
| **1 close-out** | Make the skeleton actually simulate | 3 – 8 | **COMPLETE** (all 6 tasks signed off) |
| **2** | Career systems | 9 – 14 | **COMPLETE** (all 6 tasks signed off) |
| **3** | Human layer | 15 – 19 | **NOT STARTED** — briefs need expansion (see §8) |
| **4** | Media & economy | 20 – 24 | **NOT STARTED** — briefs need expansion |
| **5** | AI & polish | 25 – 30 | **NOT STARTED** — briefs need expansion |

Each stage is gated: the next stage does not start until every task in
the previous stage is signed off in `worklog.md`.

---

## 6. What landed in Stage 1 (Tasks 3-8)

| Task | What it delivered | Schema version | Commit |
|---|---|---|---|
| 3 | Real attribute-based fight resolver (no more coin flip) | 1.2.1 (no change) | `7915181` |
| 4 | `fight_history` table (per-fighter per-fight, separate from mutable counters) | 1.3.0 | `1627c87` |
| 5 | Schema version-check gate (refuses to clobber newer schema) | 1.3.0 (no change) | `ccc5d24` |
| 6 | Promotion filter dropdown in UI (multi-promotion awareness) | 1.3.0 (no change) | `9e1e924` |
| 7 | Event lifecycle (scheduled → in_progress → completed) | 1.3.0 (no change) | `93b9910` |
| 8 | Repeatable event generator (auto-schedule next card ~4 weeks out) | 1.3.0 (no change) | `f463a0b` |

**Stage 1 result:** The skeleton actually simulates. Click "Resolve
Fight" repeatedly and the world keeps going: events complete, new
events auto-schedule, career counters accumulate, fight history is
recorded. 6 acceptance tests, 155+ sub-checks.

---

## 7. What landed in Stage 2 (Tasks 9-14)

| Task | What it delivered | Schema version | Commit |
|---|---|---|---|
| 9 | Contracts (4 tables, seed, UI Contracts tab) | 1.4.0 | `7f656f6` |
| 10 | Rankings (ELO, auto-update, UI Rankings tab) | 1.5.0 | `9caa315` |
| 11 | Titles (champion per weight class, 5-case resolution, vacated on retirement) | 1.6.0 | `9f34c8a` |
| 12 | Retirement (age + health-based, vacates titles, news items) | 1.7.0 | `24ef7bd` |
| 13 | Free agency (contract expiry, sign free agents, UI Free Agents tab) | 1.8.0 | `51ca8f7` |
| 14 | Regen (name pools, style DNA, replacement on retirement) | 1.9.0 | `347b339` |

**Stage 2 result:** The full career lifecycle loop is closed:
contracts → fights → rankings → titles → retirement → regen → free
agency → signing → contracts (repeat forever). 6 acceptance tests,
350+ sub-checks.

---

## 8. New tasks identified during audit (before Stage 3) — RESOLVED

The audit (see `SCHEMA_DRIFT_AUDIT.md §Z`) identified gaps that must
be addressed before or during Stage 3. The 6 open questions from
`STAGE3_EXPANSION_PLAN.md §8` have been resolved by the supervisor
(see `STAGES.md` Stage 2.5 for the full decisions).

### Resolved decisions

1. **Task 14.5+14.6+14.7 combined** — YES, one commit, schema 2.0.0
   (MAJOR). 68 new columns across 6 tables + `current_date` quirk fix
   + `src/fighter_gen.py` module + 12 archetype seeds.
2. **Beat engine split** — B1 (basic beat loop + decision scoring,
   schema 2.1.0) and B2 (fatigue + momentum + finishes + commentary,
   schema 2.2.0).
3. **Archetype seed data** — 7 style + 5 personality archetypes with
   bias JSON, seeded in Task 14.5.
4. **Anticipation Feed** — Task 31 (Stage 5), depends on many systems.
5. **Design Law enforcement** — Added to CONVENTIONS.md §13. Enforced
   at every task review.
6. **Execution order** — 14.5+14.6+14.7 → B1 → B2 → 15 → 16 → 17 →
   19 → 18.

### Stage 2.5 task list (resolved)

| Task | What | Schema | Pillars |
|---|---|---|---|
| 14.5+14.6+14.7 | Fighter schema expansion (68 columns, fighter_gen.py, quirk fix, archetype seeds) | 2.0.0 | Growth, Discovery |
| B1 | Beat-level engine (tables + basic loop + decision scoring) | 2.1.0 | Conflict, Watch Rise |
| B2 | Engine depth (fatigue + momentum + finishes + commentary) | 2.2.0 | Conflict, Watch Rise |
| B-regen-update | Update generate_fighter to use fighter_gen.py | 2.2.0 | Discovery |

### Stage 3a — Fighter Welfare (after Stage 2.5)

| Task | What | Schema | Pillars |
|---|---|---|---|
| 15 | Injuries + medical recovery | 2.3.0 | Investment, Conflict |
| 16 | Training camps | 2.4.0 | Growth, Investment |
| 17 | Weight cuts | 2.5.0 | Conflict, Investment |

### Stage 3b — Presentation (after Stage 3a)

| Task | What | Schema | Pillars |
|---|---|---|---|
| 19 | Voice / interpretation layer | 2.6.0 | ALL 5 (translates simulation into emotion) |
| 18 | Scouting system | 2.7.0 | Discovery (Fantasy 1: Talent Hunter) |

---

## 9. Stage 3-5 briefs need expansion

The user correctly identified that Stages 3-5 are "thinly designed and
planned." The current briefs in `STAGES.md` for Tasks 15-30 are 2-3
line summaries. Before any coding begins on Stage 3, each task brief
must be expanded to include:
- Detailed schema (column names, types, constraints, FKs)
- Approach (algorithm, formulas, hook points)
- Acceptance checklist (testable criteria)
- Dependencies (which prior tasks must be complete)
- Scope boundaries (what NOT to do)

**This expansion is the next planning step.** No coding until the
expanded briefs are reviewed and approved.

---

## 10. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-21 | Repo stays private | User request |
| 2026-07-21 | DB renamed to `cage_empire.db` | Branding consistency |
| 2026-07-21 | Original Task 2 (big-bang v1.6 schema dump) killed | Would replay the 37→24 drift failure mode |
| 2026-07-21 | `schema_meta` + `schema_migrations` restored before any new tables | Cheap insurance against silent drift |
| 2026-07-21 | One table-group per task enforced as a hard rule | Makes each task testable; small blast radius |
| 2026-07-21 | Stages are gated | Prevents half-built systems stacking up |
| 2026-07-21 (Task 3) | Fight resolver deviates from spec's literal "margin > 30 → ko_tko" — at any finish margin both KO and submission are possible, weighted by winner's punch_power vs fight_iq | Required to pass the no-single-type-60% assertion in the symmetric all-90-vs-all-30 matchup |
| 2026-07-21 (Task 3) | Explicit draw handling added (was a bug in the original spec — draws would have corrupted career counters) | Bug fix |
| 2026-07-21 (Task 4) | Defensive `DELETE FROM fight_history WHERE fight_id=?` before INSERTs | Makes resolver idempotent for re-resolution (required by test_fight_resolver.py's 100x re-resolve pattern) |
| 2026-07-21 (Task 9) | Dynamic-version pattern adopted for tests | Tests read `build_db.CODE_SCHEMA_VERSION` instead of hardcoding version strings. Prevents test breakage on version bumps. Applied to test_fight_history, test_schema_versioning, test_contracts, test_rankings, test_titles, test_retirement, test_free_agency, test_regen. |
| 2026-07-21 (Task 9) | "Don't modify existing tests" rule with supervisor escalation protocol | Subagents flag stale assertions (D-number in worklog) instead of modifying tests. Supervisor applies the fix. Happened in Tasks 9, 10, 11, 13, 14. |
| 2026-07-21 (Task 11) | `write_news`/`write_commentary` reordered to after rankings + title resolution | News can now mention title changes. Required reorder because the original code had write_news BEFORE rankings update. |
| 2026-07-21 (Task 12) | Retirement runs BEFORE contract expiry on tick | Retired fighters' contracts expire but they don't become free agents (they're retired, not unsigned) |
| 2026-07-21 (Task 13) | Free Agents tab does NOT respect promotion filter | Free agents have no promotion — scoping would always return empty |
| 2026-07-21 (Task 13) | `fighter_id` stored as Treeview item iid | Clean lookup for the Sign button — no fragile name matching |
| 2026-07-21 (Task 14) | 10 designed regen tables consolidated into 3 | `name_pools` (one table with name_type column) replaces 4 separate tables. `regen_lineage` replaces `fighter_lineage` + `fighter_generation_history`. `used_names` dropped (check against fighters table instead). Simpler, same functionality. |
| 2026-07-21 (Task 14) | `fighter_memory_links` created but NOT populated | Memory resurfacing is a future enhancement. Table exists so future tasks can populate without schema change. |
| 2026-07-21 (audit) | Tasks 14.5, 14.6, 14.7, 14.8, 6.5 identified as new tasks | Audit of Stages 1-2 revealed critical gaps: fighter_attributes/personality still at 4/3 (not 24/17), fight_rounds still missing, fighters table missing ~14 columns, pre-existing current_date quirk, no Staff UI tab |
| 2026-07-21 (audit) | Stage 3-5 briefs need expansion before coding | Current briefs are 2-3 line summaries. Must expand to full briefs (schema, approach, acceptance checklist, dependencies, scope) before any Stage 3 work begins. |
| 2026-07-21 (Soul) | CAGE EMPIRE SOUL adopted as prime directive | "The player collects stories, not fighters." Design Law added to CONVENTIONS.md §13. 5 pillars: Discovery, Investment, Growth, Conflict, Legacy. Every task reviewed against these pillars. |
| 2026-07-21 (Soul) | Voice/interpretation layer reframed | Not a technical utility — it is "the machinery that translates simulation into emotion." Moved to front of Stage 3b (before scouting). |
| 2026-07-21 (supervisor) | Task 14.5+14.6+14.7 combined as one-off | 68 new columns across 6 tables in one commit. Schema 2.0.0 (MAJOR — first major version). Thorough testing required. |
| 2026-07-21 (supervisor) | Beat engine split into B1 + B2 | B1: tables + basic beat loop + decision scoring (2.1.0). B2: fatigue + momentum + finishes + commentary (2.2.0). Keeps each task testable. |
| 2026-07-21 (supervisor) | 7 style + 5 personality archetypes seeded with bias JSON | Variety in regen from the start. Generic 50-everything prospects don't generate stories. |
| 2026-07-21 (supervisor) | Anticipation Feed added as Task 31 (Stage 5) | UI feature showing "what's coming." Depends on many systems. Too early now. |
| 2026-07-21 (supervisor) | Execution order: 14.5 → B1 → B2 → 15 → 16 → 17 → 19 → 18 | Voice layer (19) before scouting (18) because scouting reports use the voice layer. Injuries (15) before camps (16) because camp injury risk feeds injury system. |
| 2026-07-21 (supervisor) | Schema version jumps to 2.0.0 for fighter expansion | MAJOR bump marks the transition from thin skeleton (4 attributes, coin-flip resolver) to real simulation depth (25 attributes, beat-level engine). |
