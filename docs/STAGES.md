# CAGE EMPIRE — Staged Buildout

> **Status:** Living document. Each task gets a brief, an acceptance
> checklist, and a sign-off line in `worklog.md`.
> **Last revised:** 2026-07-21 — Task ID 2.

The stages are **gated**. Stage N+1 does not begin until every task in
Stage N is signed off.

---

## Stage 1 — Close-out (make the skeleton actually simulate)

The current v1.2.0 skeleton runs end-to-end but does not simulate
anything. This stage closes that gap with the smallest possible set of
high-leverage changes.

### Task ID 3 — Real attribute-based fight resolver

**Brief.** Replace the coin-flip `resolve_next_fight()` in `src/app.py`
with a function that actually reads the 4 stored attributes
(`punch_power`, `cardio`, `fight_iq`, `chin`) plus the 3 personality
fields (`aggression`, `composure`, `morale`) to produce a winner, a
result type, and a finish round. Probabilistic, not deterministic —
the better fighter should win most of the time but not always.

**Scope.** Single function drop-in. No new tables. No new UI. The
existing UI calls `resolve_next_fight(conn)` and that signature stays
the same.

**Approach.**
1. Load both fighters' `fighter_attributes` and `fighter_personality`
   rows.
2. Compute a per-fighter "power score" combining punch_power (×0.4),
   cardio (×0.3), fight_iq (×0.2), chin (×0.1).
3. Compute a "consistency modifier" from composure + morale (high
   composure reduces variance, low morale reduces power).
4. Add Gaussian noise (σ ≈ 15) to each fighter's score.
5. Higher score wins. Margin decides result type:
   - margin > 30 → `ko_tko` (early finish, round 1–2)
   - margin 15–30 → `submission` or `ko_tko` (mid finish, round 2–3)
   - margin 5–15 → `unanimous_decision`
   - margin < 5 → coin flip for `split_decision` or `draw`
6. Aggression differential shifts the finish round (more aggressive
   fighter finishes earlier on average).

**Acceptance checklist.**
- [ ] `resolve_next_fight()` reads from `fighter_attributes` and
      `fighter_personality`.
- [ ] A fighter with all attributes = 90 beats a fighter with all = 30
      at least 80% of the time over 100 simulated resolutions.
- [ ] Result type distribution is reasonable (no single type > 60%).
- [ ] Existing UI still works without changes.
- [ ] Smoke test: build + seed + resolve 5 fights, check `fights` table
      has 5 rows with sensible `result_type` values.
- [ ] `CHANGELOG.md` entry added.
- [ ] Schema version unchanged (still 1.2.1 — no schema work in this
      task).

**Delegation.** full-stack-developer subagent.

---

### Task ID 4 — fight_history table (separate from mutable career counters)

**Brief.** Today a fight's result lives only as an increment to
`record_wins` / `record_losses` on `fighter_career`. Once rankings,
legacy, and stats-based commentary arrive, they need a queryable
per-fight history. Adding the table now is cheap; reconstructing it
later from `record_wins` is impossible.

**Scope.** New table `fight_history`. Populated by `resolve_next_fight()`
on every resolution. Read by a new "Fighter Profile" view (deferred —
just write the table for now, no UI in this task).

**Schema.**
```sql
CREATE TABLE IF NOT EXISTS fight_history (
    fight_history_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id           INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    fighter_id         INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    opponent_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    outcome            TEXT NOT NULL CHECK (outcome IN ('win','loss','draw','nc')),
    result_type        TEXT,            -- ko_tko / submission / decision / etc.
    finish_round       INTEGER,
    finish_time        TEXT,
    score_margin       INTEGER,         -- |power_score_a - power_score_b| at resolution
    event_id           INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    event_date         TEXT,
    weight_class_id    INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,
    title_at_stake     INTEGER NOT NULL DEFAULT 0 CHECK (title_at_stake IN (0,1)),
    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, fighter_id)
);
```

**Acceptance checklist.**
- [ ] `fight_history` table created.
- [ ] `resolve_next_fight()` inserts two rows per fight (one per fighter
      with their perspective).
- [ ] Smoke test: resolve 5 fights → 10 rows in `fight_history`, win/loss
      counts match `fighter_career`.
- [ ] `CHANGELOG.md` entry added.
- [ ] Schema version bumped to `1.3.0`.

**Delegation.** full-stack-developer subagent (same one as Task 3 if
sequential, since they touch the same function).

---

### Task ID 5 — schema_meta / schema_migrations enforcement

**Brief.** Task 2 restores the two tables. This task makes them
enforced: `build_db.py` refuses to run if the on-disk schema is newer
than the code expects. Prevents an older script silently clobbering a
newer schema.

**Scope.** Modify `build_db.py` `main()` to check `schema_meta` before
rebuilding. Add a `CODE_SCHEMA_VERSION` constant. If
`schema_meta.schema_version > CODE_SCHEMA_VERSION`, abort with a clear
error message. If `<`, proceed (we are upgrading). If `=`, proceed (we
are rebuilding the same version, which is allowed for dev reset).

**Acceptance checklist.**
- [ ] `CODE_SCHEMA_VERSION = "1.3.0"` constant at top of `build_db.py`.
- [ ] `main()` checks `schema_meta` before unlinking the DB file.
- [ ] If on-disk version is newer than code version, abort with
      `RuntimeError` and clear message.
- [ ] Smoke test: set on-disk version to `9.9.9`, run `build_db.py`,
      confirm it refuses.
- [ ] `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 6 — Second promotion seed + UI multi-promotion awareness

**Brief.** Task 2 seeds a second promotion (`Rival Fight League`) as
inert data. This task makes the UI aware that multiple promotions
exist: the Fighters tree gets a "Promotion" column (already present)
and a filter dropdown. No AI behaviour yet — RFL just sits there with
no roster.

**Scope.** UI changes in `src/app.py`. No schema changes. Seed gets
the second promotion's roster (3 generic fighters) so the filter
actually shows something.

**Acceptance checklist.**
- [ ] Promotion filter dropdown in the UI top bar.
- [ ] Filtering by `Alpha Combat` shows only AC fighters.
- [ ] Filtering by `Rival Fight League` shows only RFL fighters.
- [ ] Filtering by `All` shows all fighters.
- [ ] Smoke test: launch app, switch filters, confirm counts.
- [ ] `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 7 — Event lifecycle (scheduled → in_progress → completed)

**Brief.** Today `events.status` is set to `'scheduled'` on creation
and never changes. This task adds proper transitions: when the first
fight on the card resolves, status → `'in_progress'`; when the last
fight resolves, status → `'completed'` and `event_date` is locked.

**Scope.** Modify `resolve_next_fight()` to update event status. No
schema changes (status column already exists).

**Acceptance checklist.**
- [ ] After resolving the only fight on the seeded event, event status
      is `'completed'`.
- [ ] After resolving the first of N fights, event status is
      `'in_progress'`.
- [ ] Smoke test: seed, resolve the one fight, query events table,
      confirm status.
- [ ] `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 8 — Repeatable event generator

**Brief.** Today after the one seeded fight resolves, the world is
dead — nothing schedules the next card. This breaks "played forever"
on the very first playthrough. This task adds a function
`schedule_next_event(conn, promotion_id)` that picks a date ~4 weeks
out, picks the venue, and creates a card with 1 main event (auto-
matched from the roster by ranking proximity, falling back to random
if no rankings yet).

**Scope.** New function in `src/app.py` (or a new `src/booking.py`
module if the subagent prefers — supervisor's call). Called from
`on_resolve_fight()` after the last fight on the current card resolves.
No schema changes.

**Acceptance checklist.**
- [ ] After resolving the only seeded fight, a new event is auto-
      scheduled 4 weeks later.
- [ ] The new event has at least 1 fight with 2 participants.
- [ ] No infinite loop — only one new event per resolution.
- [ ] Smoke test: resolve the seeded fight, confirm a new event
      appears in the events tree.
- [ ] `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

## Stage 2 — Career systems

Gated on Stage 1 sign-off. Each task adds one table-group with at
least one writer and one reader.

### Task ID 9 — Contracts

**Brief.** Add `contracts`, `fighter_contracts`, `staff_contracts`,
`broadcast_contracts` tables. Seed each fighter with a default
12-month contract. Add a Contracts tab to the UI showing the player's
promotion's active contracts. No negotiation flow yet — just the
data shape and a read-only view.

**Acceptance checklist.**
- [ ] 4 tables created with proper FKs.
- [ ] Seed creates 1 contract per seeded fighter (12 months, default
      salary).
- [ ] Contracts tab in UI lists all active contracts for the player's
      promotion.
- [ ] Smoke test passes.
- [ ] Schema version `1.4.0`. `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 10 — Rankings

**Brief.** Add `rankings` table (one row per fighter per weight class
per promotion). Auto-update on fight resolution: winner moves up,
loser moves down, simple ELO-style. Add a Rankings tab.

**Acceptance checklist.**
- [ ] `rankings` table created.
- [ ] After resolving a fight, both fighters' rank updates.
- [ ] Rankings tab in UI shows top 10 per weight class for the player's
      promotion.
- [ ] Schema version `1.5.0`. `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 11 — Titles

**Brief.** Add `titles` table (one row per belt per promotion per
weight class). Title fights are flagged on `fights` (already have
`bout_type` — use `'title_fight'`). Winner becomes champion. Add a
Titles panel to the Fighter Profile view (deferred — just write the
table and the writer for now).

**Acceptance checklist.**
- [ ] `titles` table created.
- [ ] Seed creates 1 vacant title per weight class per promotion.
- [ ] Resolving a `title_fight` bout_type transfers the title.
- [ ] Schema version `1.6.0`. `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 12 — Retirement logic

**Brief.** Fighters age. When a fighter crosses age 40 with a
declining `career_health`, they retire (set `is_retired = 1` — note
this column exists in the spec but is missing from the v1.2.0 build;
Task 12 must add it as a migration). Retirement triggers a news item.

**Acceptance checklist.**
- [ ] `fighters.is_retired` column added (migration).
- [ ] Tick processor checks for retirement-eligible fighters and
      retires them.
- [ ] Retiring fighter generates a news item.
- [ ] Schema version `1.7.0`. `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 13 — Free agency + signings

**Brief.** When a fighter's contract expires, they become a free
agent. Player can sign free agents from a new Free Agents tab. No
negotiation yet — just "click to sign at default salary".

**Acceptance checklist.**
- [ ] Contract expiry on tick → `contract_status = 'expired'`,
      `current_promotion_id = NULL`.
- [ ] Free Agents tab lists all fighters with no current promotion.
- [ ] Click to sign creates a new 12-month contract.
- [ ] Schema version `1.8.0`. `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

### Task ID 14 — Regen engine (first cut)

**Brief.** When a fighter retires, generate a replacement fighter from
a name pool with a similar style DNA. No memory resurfacing yet —
just keep the roster count stable.

**Scope.** Add `name_pools` (first_male, first_female, last, nickname)
+ `regen_lineage` + `fighter_memory_links` tables. Add a
`generate_fighter(conn, style_dna_source_id=None)` function. Called
from the retirement path.

**Acceptance checklist.**
- [ ] 3 tables created with seed name data.
- [ ] Retiring a fighter triggers `generate_fighter()`.
- [ ] New fighter has unique name (checked against `used_names`).
- [ ] New fighter has the same `fight_style_archetype_id` as the
      retiring fighter (style DNA).
- [ ] Schema version `1.9.0`. `CHANGELOG.md` entry added.

**Delegation.** full-stack-developer subagent.

---

## Stage 3 — Human layer

Gated on Stage 2 sign-off.

### Task ID 15 — Injuries + medical recovery

**Brief.** Add `injuries` table. Fight resolution has a chance to
create an injury (severity 1–10, body area, projected return date).
Tick processor advances recovery. Injured fighters can't be booked.

### Task ID 16 — Training camps

**Brief.** Add `training_camps` table. Before an event, fighters
attend a camp at their gym. Camp modifies `fighter_attributes`
slightly (+/- 1–3 points) based on gym specialization and camp focus.

### Task ID 17 — Weight cuts

**Brief.** Add `weight_cut_difficulty` column to `fighters` (migration).
Before a fight, fighters cut weight. High `weight_cut_difficulty` +
high `aggression` = chance of missing weight → fight becomes catch-
weight or cancelled.

### Task ID 18 — Scouting system

**Brief.** Add `scouting_reports` table. New "Scout" staff role.
Scout can be assigned a target fighter; after N ticks, a scouting
report is generated with estimated strengths, weaknesses, ceiling,
floor, marketability, injury risk, contract cost.

### Task ID 19 — Voice / interpretation layer

**Brief.** New module `src/voice.py`. Function `describe_attribute(name,
value, context)` returns a string like `"elite gas tank"` for cardio=91.
Used everywhere stats appear: fighter profile blurbs, scout reports,
news, commentary, punditry. Deterministic — same input always produces
same output.

---

## Stage 4 — Media & economy

Gated on Stage 3 sign-off.

### Task ID 20 — Finance system + screen

**Brief.** Add `finances` table (per-event P&L, per-week burn rate).
Add Finance tab to UI: current cash, burn rate, last event P&L,
forecast. Revenue from ticket sales + broadcast; expenses from
purses + venue + staff salaries + medical.

### Task ID 21 — Social media + beefs

**Brief.** Add `social_posts` + `social_accounts` tables. Fighters
post on a schedule based on `attention_seeking` and `trash_talk`.
Beefs escalate from callouts → insults → apology videos, driven by
personality and recent fight results.

### Task ID 22 — Rivalries

**Brief.** Add `rivalries` table. Built from callouts, bad decisions,
missed weights, close fights, stolen opportunities. Affects fight hype
and fighter performance (higher `aggression` + lower `composure` in
rivalry fights).

### Task ID 23 — News engine (template-based)

**Brief.** New module `src/news.py`. Function `generate_news(event_type,
context)` picks a template and fills slots using the voice layer.
Replaces the current hardcoded "X defeats Y" strings with varied,
context-aware headlines and bodies.

### Task ID 24 — Punditry / matchup analysis

**Brief.** Add `pundit_segments` + `matchup_analysis` + `betting_odds`
tables. When two fighters are paired, generate a matchup analysis
with predicted winner, method, main-event score, prelim score, style
edge, excitement score, upset risk. Pundits comment on the analysis.

---

## Stage 5 — AI & polish

Gated on Stage 4 sign-off.

### Task ID 25 — Rival promotion AI

**Brief.** RFL (and any other rival promotion) runs its own booking
loop: signs free agents, books cards, develops talent. Driven by
`ai_aggression` + `ai_spending_style` columns on `promotions` (need
migration to add these — they exist in spec but missing from v1.2.0).

### Task ID 26 — Show rating engine

**Brief.** Compute fan rating + commercial rating + business impact +
momentum impact per event, using the v1.6 spec's input list. Display
in the post-event summary panel.

### Task ID 27 — Venues / markets deeper simulation

**Brief.** Add the missing columns to `venues`, `markets`, `cities`,
`nations`, `regions` per the spec (prestige, cost, atmosphere,
affluence, combat_sports_interest, etc.). Wire them into show rating
and finance calculations.

### Task ID 28 — CustomTkinter dark theme

**Brief.** Replace the stock ttk widgets with CustomTkinter. Apply the
spec's palette: charcoal background, blood-red + electric-teal/gold
accents, amber warning, green success. Inter / Segoe UI fonts.

### Task ID 29 — Mod tools skeleton

**Brief.** New `src/mods.py` module. Fighter / promotion / venue /
contract editors. CSV + JSON import/export. Portrait pack folder
support. Full database backup/restore.

### Task ID 30 — Save / load + backup / restore

**Brief.** Save game state to `saves/<save_name>.db`. Load on startup.
Auto-backup every N ticks to `data/backups/`. Backup rotation (keep
last 5).

---

## Cross-cutting work

These run in parallel with the stages above, not gated:

- **Documentation.** Every task updates `CHANGELOG.md` and
  `worklog.md`. Every schema change updates `SCHEMA_DRIFT_AUDIT.md`.
- **Testing.** A `tests/` folder lands with Task 3 (the fight resolver
  needs unit tests for the probabilistic outcomes). Subsequent tasks
  add tests as they go.
- **Performance.** Not a focus until Stage 5. Premature optimization
  will be rejected.
- **Modding readiness.** Tables are designed with moddability in mind
  (every "template" table is JSON-friendly), but the actual mod UI is
  Task 29.
