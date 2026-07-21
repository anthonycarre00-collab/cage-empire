# CAGE EMPIRE — Staged Buildout

> **Status:** Living document. Each task gets a brief, an acceptance
> checklist, and a sign-off line in `worklog.md`.
> **Last revised:** 2026-07-21 — Task ID 14 (Stage 2 complete, audit pass).

The stages are **gated**. Stage N+1 does not begin until every task in
Stage N is signed off.

---

## Stage 1 — Close-out (make the skeleton actually simulate) — COMPLETE

All 6 tasks signed off. The skeleton now actually simulates end-to-end.

### Task ID 3 — Real attribute-based fight resolver — DONE ✓

**Status:** Signed off. Commit `7915181`. Schema version unchanged (1.2.1).

**What landed:** Replaced coin-flip `resolve_next_fight()` with a
probabilistic model reading `fighter_attributes` (punch_power, cardio,
fight_iq, chin) and `fighter_personality` (aggression, composure,
morale). Power score = punch_power×0.4 + cardio×0.3 + fight_iq×0.2 +
chin×0.1. Gaussian noise σ≈15. Margin decides result type. Aggression
differential shifts finish round.

**Key decisions:** D1 (deviation from spec on finish-type split), D2
(explicit draw handling), D3 (defensive result_type IS NULL in pick
query), D4 (pure _resolve_outcome function), D5 (random.seed(42) in
test).

**Acceptance test:** `scripts/test_fight_resolver.py` — all-90 fighter
wins 100/100, top result_type at 50/100.

---

### Task ID 4 — fight_history table — DONE ✓

**Status:** Signed off. Commit `1627c87`. Schema version 1.3.0.

**What landed:** New `fight_history` table (14 columns, UNIQUE
fight_id+fighter_id). `resolve_next_fight()` writes 2 rows per fight
(one per fighter, from their perspective). `title_at_stake` populated
(Task 11).

**Acceptance test:** `scripts/test_fight_history.py` — 21 sub-checks.

---

### Task ID 5 — Schema version-check gate — DONE ✓

**Status:** Signed off. Commit `ccc5d24`. Schema version unchanged (1.3.0).

**What landed:** `_parse_version()`, `_compare_versions()`,
`_read_on_disk_schema_version()` helpers. `main()` checks on-disk
version before unlinking. Refuses to clobber newer schema. Semver
comparison correctly handles 1.10.0 > 1.9.0.

**Acceptance test:** `scripts/test_schema_versioning.py` — 7 cases.

---

### Task ID 6 — Promotion filter UI — DONE ✓

**Status:** Signed off. Commit `9e1e924`. Schema version unchanged (1.3.0).

**What landed:** `get_fighters_for_display(conn, promotion_filter)`
helper. Promotion filter Combobox in the top bar. `on_promo_filter_change`
handler. Combobox values refreshed from DB on every `refresh_all()`.

**Acceptance test:** `scripts/test_promotion_filter.py` — 5 cases + 1
SKIP (headless UI).

---

### Task ID 7 — Event lifecycle — DONE ✓

**Status:** Signed off. Commit `93b9910`. Schema version unchanged (1.3.0).

**What landed:** `_update_event_status_after_resolution(conn, event_id)`
helper. scheduled → in_progress (when fights remain) → completed (when
no fights remain). Defensive `WHERE status != 'completed'` clause.

**Acceptance test:** `scripts/test_event_lifecycle.py` — 31 sub-checks.

---

### Task ID 8 — Repeatable event generator — DONE ✓

**Status:** Signed off. Commit `f463a0b`. Schema version unchanged (1.3.0).

**What landed:** `schedule_next_event(conn, promotion_id, from_event_date,
weeks_out=4)` function. `_pick_matchup()` helper. Triggered in
`resolve_next_fight()` when event just completed. New event ~4 weeks
out, same venue/market/weight_class, 1 fight with 2 random participants.

**Acceptance test:** `scripts/test_event_scheduler.py` — 60 sub-checks.

**Manual verification:** 6 cycles produce 7 events with dates
incrementing by 28 days: 2026-08-15 → 09-12 → 10-10 → 11-07 → 12-05
→ 2027-01-02 → 01-30.

---

## Stage 2 — Career systems — COMPLETE

All 6 tasks signed off. The full career lifecycle loop is closed:
contracts → fights → rankings → titles → retirement → regen → free
agency → signing → contracts (repeat forever).

### Task ID 9 — Contracts — DONE ✓

**Status:** Signed off. Commit `7f656f6`. Schema version 1.4.0.

**What landed:** 4 tables (contracts polymorphic base +
fighter_contracts + staff_contracts + broadcast_contracts). Seed
creates 5 fighter contracts + 1 staff contract (12-month, 50000
salary, exclusive, active). UI Contracts tab. `get_contracts_for_display()`
helper.

**Acceptance test:** `scripts/test_contracts.py` — 39 sub-checks + 1
SKIP.

---

### Task ID 10 — Rankings — DONE ✓

**Status:** Signed off. Commit `9caa315`. Schema version 1.5.0.

**What landed:** `rankings` table (ELO-style, 12 columns, UNIQUE
fighter+weight_class+promotion). `_update_rankings_after_resolution()`
(K=32, zero-sum, expected score formula). UI Rankings tab.
`get_rankings_for_display()` helper. All fighters seeded at 1000.0.

**Acceptance test:** `scripts/test_rankings.py` — 43 sub-checks + 1
SKIP.

---

### Task ID 11 — Titles — DONE ✓

**Status:** Signed off. Commit `9f34c8a`. Schema version 1.6.0.

**What landed:** `titles` table (10 columns, UNIQUE
promotion+weight_class). `_resolve_title_after_fight()` (5 cases:
vacant+win, vacant+draw, held+champ-wins, held+contender-wins,
held+draw). Seeded main event is now `bout_type='title_fight'`.
`fight_history.title_at_stake` populated. News/commentary enriched
with "(TITLE CHANGE!)" suffix.

**Acceptance test:** `scripts/test_titles.py` — 55 sub-checks + 1
SKIP.

---

### Task ID 12 — Retirement — DONE ✓

**Status:** Signed off. Commit `24ef7bd`. Schema version 1.7.0.

**What landed:** `is_retired` column on fighters.
`_check_retirements()` in tick_processor.py (age ≥45 mandatory,
age 40-44 + career_health <60 optional). `_vacate_title_on_retirement()`
in app.py. Retirement + title vacation news items.

**Acceptance test:** `scripts/test_retirement.py` — 44 sub-checks.

---

### Task ID 13 — Free agency — DONE ✓

**Status:** Signed off. Commit `51ca8f7`. Schema version 1.8.0.

**What landed:** `_check_contract_expiry()` in tick_processor.py
(expires contracts past end_date, sets current_promotion_id=NULL for
non-retired fighters). `sign_free_agent()` in app.py (creates 12-month
exclusive contract). `get_free_agents_for_display()` helper. UI Free
Agents tab with Sign button. Free agency + signing news items.

**Acceptance test:** `scripts/test_free_agency.py` — 54 sub-checks +
6 SKIP.

---

### Task ID 14 — Regen engine — DONE ✓

**Status:** Signed off. Commit `347b339`. Schema version 1.9.0.

**What landed:** 3 tables (name_pools, regen_lineage,
fighter_memory_links). 96 seeded names (25 male firsts, 25 female
firsts, 26 lasts, 20 nicknames). `generate_fighter()` in app.py
(unique name from pools, inherits style DNA, 18-26 years old, enters
as free agent). `_check_retirements()` calls `generate_fighter()` for
each retiring fighter. Regen lineage tracked. New prospect news items.

**Acceptance test:** `scripts/test_regen.py` — 69 sub-checks.

---

## Stage 2.5 — Audit gap-fill (NEW — identified during post-Stage-2 audit)

These tasks were identified during the audit pass (see
`SCHEMA_DRIFT_AUDIT.md §Z` and `MASTER_PLAN.md §8`). They must be
completed before Stage 3 because they block downstream tasks.

### Task ID 14.5 — Extend fighter_attributes + fighter_personality to spec

**Status:** NOT STARTED. **Priority: CRITICAL.**

**Why.** The v1.6 spec calls for 24 combat stats and 17+ personality
traits. The v1.9.0 build has 4 and 3. This blocks Tasks 16 (training
camps), 18 (scouting), 19 (voice layer), and 24 (matchup analysis).

**Brief.** TBD — needs full expansion before delegation. Key points:
- Add 20 columns to `fighter_attributes`: punch_speed, kick_power,
  kick_speed, accuracy, defense, footwork, head_movement,
  clinch_offense, clinch_defense, takedown_offense, takedown_defense,
  top_control, bottom_game, submission_offense, submission_defense,
  toughness, recovery, adaptability, pace, cage_wrestling, ringcraft,
  damage_output, finish_instinct, risk_tolerance.
- Add 14+ columns to `fighter_personality`: discipline, volatility,
  ego, loyalty, ambition, professionalism, trash_talk,
  media_friendliness, resilience, confidence, heart, respectfulness,
  temper, attention_seeking, coachability, focus, fatigue_tolerance.
- Update `_power_score()` and `_resolve_outcome()` to use the full
  attribute set (the current 4-attribute formula must be expanded to
  a 24-attribute formula — this is a significant rebalancing effort).
- Update seed defaults (all new columns default to 50).
- Schema version bump.
- New acceptance test verifying the resolver still works with the
  expanded attributes (all-90 beats all-30 ≥80% of the time).

### Task ID 14.6 — Add missing fighters table columns

**Status:** NOT STARTED. **Priority: HIGH.**

**Why.** The `fighters` table is missing ~14 spec columns needed for
Tasks 15, 17, 20, 26.

**Brief.** TBD — needs full expansion. Columns to add: height_cm,
reach_cm, stance, handedness, injury_proneness, weight_cut_difficulty,
consistency, clutch_factor, marketability, fan_friendliness,
promo_boost, preferred_gameplans (JSON), bad_matchup_tags (JSON),
is_deceased. Should be done alongside Task 14.5 (both touch the
fighter schema).

### Task ID 14.7 — Fix pre-existing `current_date` SQLite quirk

**Status:** NOT STARTED. **Priority: MEDIUM.**

**Why.** Bare `current_date` in SELECTs resolves to SQLite's built-in
date function instead of the `simulation_clock.current_date` column.
Causes the clock to jump unpredictably on the first tick after a fresh
build. Flagged in Tasks 12, 13, 14 but never fixed.

**Brief.** Qualify the column as `simulation_clock.current_date` in
`app.py` `get_clock()` (line 17) and `tick_processor.py` `run_tick()`
(line 337). Small, low-risk fix. No schema change. No new acceptance
test needed (existing tests should still pass; tighten
test_retirement.py case L's loosened assertion if the fix works).

### Task ID 14.8 — Add `fight_rounds` table

**Status:** NOT STARTED. **Priority: MEDIUM.**

**Why.** The resolver produces a `finish_round` but doesn't store
per-round stats. Needed for Tasks 23 (commentary beats), 24
(punditry), 26 (show rating).

**Brief.** TBD — needs full expansion. Add `fight_rounds` table
(round_number, fighter_a/b_damage, control_time, knockdowns,
takedowns, strikes_landed, momentum_state, round_winner_fighter_id).
Update `resolve_next_fight()` to populate it. Schema version bump.

### Task ID 6.5 — Staff UI tab

**Status:** NOT STARTED. **Priority: LOW.**

**Why.** The `staff` and `broadcast_staff` tables exist and are seeded
but the UI has no dedicated staff management view.

**Brief.** TBD — needs full expansion. Add a Staff tab showing all
staff with their roles, skills, contracts. Read-only for now (like
the Contracts tab). No hire/fire yet.

---

## Stage 3 — Human layer

**Status:** NOT STARTED. **Briefs need expansion before any coding.**

The current briefs below are 2-3 line summaries from the original
planning pass. They must be expanded to full briefs (detailed schema,
approach, acceptance checklist, dependencies, scope boundaries) before
any Stage 3 work begins. See `MASTER_PLAN.md §9`.

**Dependency note:** Tasks 15-19 depend on Task 14.5 (attribute
extension) and Task 14.6 (fighter columns). Task 14.5 is CRITICAL —
training camps can't modify attributes that don't exist, scouting
can't report on attributes that don't exist, the voice layer can't
describe attributes that don't exist.

### Task ID 15 — Injuries + medical recovery

**Brief (needs expansion).** Add `injuries` table. Fight resolution
has a chance to create an injury (severity 1–10, body area, projected
return date). Tick processor advances recovery. Injured fighters can't
be booked.

**Dependencies:** Task 14.6 (needs `injury_proneness` column on
fighters).

**Schema sketch:**
```sql
CREATE TABLE IF NOT EXISTS injuries (
    injury_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id             INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    event_id               INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id               INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    injury_type            TEXT NOT NULL,
    severity               INTEGER NOT NULL DEFAULT 5 CHECK (severity BETWEEN 1 AND 10),
    body_area              TEXT NOT NULL,
    start_date             TEXT NOT NULL,
    projected_return_date  TEXT NOT NULL,
    actual_return_date     TEXT,
    long_term_damage       INTEGER NOT NULL DEFAULT 0 CHECK (long_term_damage BETWEEN 0 AND 100),
    career_risk            INTEGER NOT NULL DEFAULT 0 CHECK (career_risk BETWEEN 0 AND 100),
    is_active              INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

**Questions to resolve before coding:**
- How does injury probability interact with the fight resolver?
  (Based on result_type? score_margin? The loser's `chin`/`toughness`
  — but those attributes don't exist yet without Task 14.5.)
- How does injury affect `fighter_career.career_health`?
- Should `_pick_matchup` filter on `injuries.is_active = 0` or on a
  separate `fighter_career.injury_status` column?
- What injury types exist? (Concussion, broken bone, torn ACL, etc.)
- How does `long_term_damage` accumulate and affect retirement?

### Task ID 16 — Training camps

**Brief (needs expansion).** Add `training_camps` table. Before an
event, fighters attend a camp at their gym. Camp modifies
`fighter_attributes` slightly (+/- 1–3 points) based on gym
specialization and camp focus.

**Dependencies:** Task 14.5 (needs full 24-attribute set to modify),
Task 14.6 (needs gym specialization columns — currently the `gyms`
table is thin).

**Questions to resolve:**
- How long before an event does the camp start? (2 weeks? 4 weeks?)
- How does camp focus interact with the fighter's style archetype?
- Does camp fatigue affect fight performance?
- Does camp injury risk feed into Task 15's injury system?
- Should the UI show camp reports?

### Task ID 17 — Weight cuts

**Brief (needs expansion).** Add `weight_cut_difficulty` column to
`fighters` (migration). Before a fight, fighters cut weight. High
`weight_cut_difficulty` + high `aggression` = chance of missing weight
→ fight becomes catch-weight or cancelled.

**Dependencies:** Task 14.6 (needs `weight_cut_difficulty` column).

**Questions to resolve:**
- How is weight cut difficulty determined? (Per-fighter static value?
  Affected by age? Affected by weight class changes?)
- What happens when a fighter misses weight? (Catch-weight? Fight
  cancelled? Opponent gets a percentage of purse?)
- Does the cut affect fight performance? (Lower cardio/stamina for
  the fighter who had a harder cut?)

### Task ID 18 — Scouting system

**Brief (needs expansion).** Add `scouting_reports` table. New "Scout"
staff role. Scout can be assigned a target fighter; after N ticks, a
scouting report is generated with estimated strengths, weaknesses,
ceiling, floor, marketability, injury risk, contract cost.

**Dependencies:** Task 14.5 (needs full 24-attribute set to report on),
Task 14.6 (needs `marketability` column).

**Questions to resolve:**
- How accurate is the scout's estimate? (Based on scout skill_level?
  Affected by scout's region familiarity? Budget?)
- How does the scout's estimate differ from the fighter's actual
  attributes? (Gaussian noise around the true value? Banded
  estimates like "elite" / "above average" / "average"?)
- Can scouts discover hidden traits (consistency, clutch_factor)?
- How does scouting quality degrade over time? (Report is a snapshot
  that becomes stale as the fighter develops.)
- UI: how does the player assign scouts and view reports?

### Task ID 19 — Voice / interpretation layer

**Brief (needs expansion).** New module `src/voice.py`. Function
`describe_attribute(name, value, context)` returns a string like
`"elite gas tank"` for cardio=91. Used everywhere stats appear:
fighter profile blurbs, scout reports, news, commentary, punditry.
Deterministic — same input always produces same output.

**Dependencies:** Task 14.5 (needs full 24-attribute set to describe).

**Questions to resolve:**
- What are the descriptor bands? (90-100 = "elite", 75-89 = "above
  average", 60-74 = "solid", 40-59 = "average", 25-39 = "below
  average", 10-24 = "poor", 0-9 = "abysmal"?)
- How do multi-attribute descriptors work? (e.g., "reckless but
  dangerous" for high aggression + low discipline + high punch_power)
- Should the voice layer support context-dependent descriptors?
  (e.g., "elite gas tank" in a scout report vs "cardio for days" in
  commentary)
- How does the voice layer feed into the news engine (Task 23)?

---

## Stage 4 — Media & economy

**Status:** NOT STARTED. **Briefs need expansion.**

### Task ID 20 — Finance system + screen

**Brief (needs expansion).** Add `finances` table (per-event P&L,
per-week burn rate). Add Finance tab to UI: current cash, burn rate,
last event P&L, forecast. Revenue from ticket sales + broadcast;
expenses from purses + venue + staff salaries + medical.

**Dependencies:** Task 14.6 (needs `marketability` column for fighter
purse calculation).

### Task ID 21 — Social media + beefs

**Brief (needs expansion).** Add `social_posts` + `social_accounts`
tables. Fighters post on a schedule based on `attention_seeking` and
`trash_talk`. Beefs escalate from callouts → insults → apology videos,
driven by personality and recent fight results.

**Dependencies:** Task 14.5 (needs `trash_talk`, `attention_seeking`,
`media_friendliness` personality traits).

### Task ID 22 — Rivalries

**Brief (needs expansion).** Add `rivalries` table. Built from callouts,
bad decisions, missed weights, close fights, stolen opportunities.
Affects fight hype and fighter performance (higher `aggression` +
lower `composure` in rivalry fights).

**Dependencies:** Task 14.5 (needs `aggression`, `composure` — already
exist), Task 21 (social media callouts feed rivalries).

### Task ID 23 — News engine (template-based)

**Brief (needs expansion).** New module `src/news.py`. Function
`generate_news(event_type, context)` picks a template and fills slots
using the voice layer. Replaces the current hardcoded "X defeats Y"
strings with varied, context-aware headlines and bodies.

**Dependencies:** Task 19 (voice layer), Task 14.8 (fight_rounds for
round-level commentary).

### Task ID 24 — Punditry / matchup analysis

**Brief (needs expansion).** Add `pundit_segments` + `matchup_analysis`
+ `betting_odds` tables. When two fighters are paired, generate a
matchup analysis with predicted winner, method, main-event score,
prelim score, style edge, excitement score, upset risk. Pundits
comment on the analysis.

**Dependencies:** Task 14.5 (needs full 24-attribute set for style
edge analysis), Task 14.8 (fight_rounds for round-by-round punditry),
Task 19 (voice layer for pundit commentary).

---

## Stage 5 — AI & polish

**Status:** NOT STARTED. **Briefs need expansion.**

### Task ID 25 — Rival promotion AI

**Brief (needs expansion).** RFL (and any other rival promotion) runs
its own booking loop: signs free agents, books cards, develops talent.
Driven by `ai_aggression` + `ai_spending_style` columns on `promotions`
(need migration to add these — they exist in spec but missing from
v1.9.0).

**Dependencies:** Migration to add `ai_aggression`, `ai_spending_style`,
`brand_tone`, `broadcast_tier`, `ownership_type` to `promotions` table.

### Task ID 26 — Show rating engine

**Brief (needs expansion).** Compute fan rating + commercial rating +
business impact + momentum impact per event, using the v1.6 spec's
input list. Display in the post-event summary panel.

**Dependencies:** Task 14.8 (fight_rounds for round-by-round drama),
Task 20 (finances for commercial rating).

### Task ID 27 — Venues / markets deeper simulation

**Brief (needs expansion).** Add the missing columns to `venues`,
`markets`, `cities`, `nations`, `regions` per the spec (prestige, cost,
atmosphere, affluence, combat_sports_interest, etc.). Wire them into
show rating and finance calculations.

### Task ID 28 — CustomTkinter dark theme

**Brief (needs expansion).** Replace the stock ttk widgets with
CustomTkinter. Apply the spec's palette: charcoal background,
blood-red + electric-teal/gold accents, amber warning, green success.
Inter / Segoe UI fonts.

### Task ID 29 — Mod tools skeleton

**Brief (needs expansion).** New `src/mods.py` module. Fighter /
promotion / venue / contract editors. CSV + JSON import/export.
Portrait pack folder support. Full database backup/restore.

### Task ID 30 — Save / load + backup / restore

**Brief (needs expansion).** Save game state to `saves/<save_name>.db`.
Load on startup. Auto-backup every N ticks to `data/backups/`. Backup
rotation (keep last 5).

---

## Cross-cutting work

These run in parallel with the stages above, not gated:

- **Documentation.** Every task updates `CHANGELOG.md` and
  `worklog.md`. Every schema change updates `SCHEMA_DRIFT_AUDIT.md`.
- **Testing.** 12 acceptance tests live in `scripts/` (not `tests/`
  as originally planned — minor convention deviation, see
  `SCHEMA_DRIFT_AUDIT.md §Z.8`). 500+ sub-checks, all passing.
- **Performance.** Not a focus until Stage 5. Premature optimization
  will be rejected.
- **Modding readiness.** Tables are designed with moddability in mind
  (every "template" table is JSON-friendly), but the actual mod UI is
  Task 29.
- **Pre-existing bug fixes.** The `current_date` SQLite quirk (§Z.6)
  and stale comments in `test_fight_history.py` (§Z.7) should be
  fixed as housekeeping tasks before Stage 3.
