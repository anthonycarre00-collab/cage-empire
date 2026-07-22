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

## Stage 2.5 — Fighter Depth + Engine Rewrite (RESOLVED)

> **Supervisor decisions (2026-07-21):** The 6 open questions from
> `STAGE3_EXPANSION_PLAN.md §8` have been resolved by the supervisor.
> See decisions below.

### Supervisor decisions on the 6 open questions

1. **Combined commit scope (14.5+14.6+14.7):** YES, combined as a
   one-off per user instruction. 68 new columns across 6 tables in one
   commit, tested thoroughly. The `current_date` quirk fix (14.7) rides
   along. Schema version bumps to 2.0.0 (MAJOR — first major version,
   marking the transition from thin skeleton to real simulation depth).

2. **Beat engine complexity:** SPLIT into B1 (tables + basic beat loop +
   decision scoring) and B2 (fatigue + momentum + mid-round finishes +
   commentary beat selection). B1 is the minimum viable engine; B2 adds
   the dramatic depth that makes fights memorable. This keeps each task
   testable and reviewable.

3. **Archetype seed data:** YES, seed 7 style archetypes + 5 personality
   archetypes with bias JSON. Variety in regen is important from the
   start — the Soul document says "the story is the reward," and generic
   50-everything prospects don't generate stories.

4. **Anticipation Feed:** Added as Task 31 (Stage 5). It's a UI feature
   that depends on many systems being in place (injuries, camps, rival
   promotions, title reigns, regen lineage). Too early to build now.

5. **Design Law enforcement:** YES, added to CONVENTIONS.md §13. The
   supervisor will ask "Which of the 5 pillars does this strengthen?
   What stories does it generate?" at every task review.

6. **Execution order:** 14.5+14.6+14.7 → B1 → B2 → 15 → 16 → 17 → 19 → 18.
   The voice layer (19) comes before scouting (18) because scouting
   reports use the voice layer. Injuries (15) come before camps (16)
   because camp injury risk feeds the injury system.

### Revised Stage 2.5 task list

| Task | What | Schema version | Pillars served |
|---|---|---|---|
| **14.5+14.6+14.7** | Expand fighter_attributes (4→25), fighter_personality (3→20), add 14 fighters columns, 6 promotions columns, 8 gyms columns, 2 archetype bias columns. New `src/fighter_gen.py` module. Fix `current_date` quirk. Backfill all existing fighters. Seed 7 style + 5 personality archetypes with bias JSON. | 2.0.0 (MAJOR) | Growth (attributes are the growth substrate), Discovery (archetypes create variety) |
| **B1** | Beat-level fight engine — tables (`fight_beats` + `fight_rounds`), basic beat loop (12-28 beats/round, phase-to-attribute mapping, 6 phases), decision scoring. `resolve_round()` function. | 2.1.0 (MINOR) | Conflict (the fight is the primary conflict), Watch Rise (dramatic moments) |
| **B2** | Beat engine depth — fatigue + momentum + mid-round finishes (KO/sub/doctor/corner/DQ) + commentary beat selection + **fight importance + pressure modifiers** (clutch_factor, composure, consistency affect performance in main events). | 2.2.0 (MINOR) | Conflict (dramatic finishes, pressure stories), Watch Rise (rising to the occasion) |
| **B-regen-update** | Update `generate_fighter()` (Task 14) to use `fighter_gen.py` from 14.5. Regen fighters now get full 25-attribute + 20-personality blocks with archetype bias. | 2.2.0 (same commit as B2) | Discovery (regen prospects feel like real fighters, not generic 50s) |

### Execution order (strict, updated)

```
14.5+14.6+14.7 (combined, schema 2.0.0) ✓ DONE
    ↓
pre-B1-fixes (potential, archetypes, memory, schema 2.0.1) ✓ DONE
    ↓
B1 (beat engine tables + basic loop, schema 2.1.0) ✓ DONE
    ↓
pre-B2-fix (fights.card_slot + is_title_fight + event_cards.is_co_main, schema 2.1.1)
    ↓
B2 (fatigue + momentum + finishes + importance + commentary, schema 2.2.0)
    ↓
B-regen-update (update generate_fighter to use fighter_gen.py, same commit as B2)
    ↓
--- Stage 3a begins ---
15 (injuries, schema 2.3.0)
    ↓
16 (training camps, schema 2.4.0)
    ↓
17 (weight cuts, schema 2.5.0)
    ↓
--- Stage 3b begins ---
19 (voice/interpretation layer, schema 2.6.0)
    ↓
18 (scouting, schema 2.7.0)
```

### Pre-B2 schema fix: fight importance columns

**Pillars served:** Conflict (importance creates pressure stories), Watch Rise
(rising to the occasion / bottling under pressure)

**Brief.** Add `card_slot` and `is_title_fight` columns to `fights` to
separate card position from title-fight status (currently `bout_type` does
both, which is a design smell — a fight can be a main event AND a title
fight). Add `is_co_main` to `event_cards` (was in the spec but missing).
Update code to use the new columns. Backfill existing fights.

**Schema changes:**
- `fights.card_slot` TEXT NOT NULL DEFAULT 'main_event' CHECK (card_slot IN ('main_event', 'co_main', 'featured_prelim', 'prelim', 'opener'))
- `fights.is_title_fight` INTEGER NOT NULL DEFAULT 0 CHECK (is_title_fight IN (0,1))
- `event_cards.is_co_main` INTEGER NOT NULL DEFAULT 0 CHECK (is_co_main IN (0,1))

**Code changes:**
- `_resolve_title_after_fight()`: check `fights.is_title_fight=1` instead of `bout_type='title_fight'`
- `fight_history.title_at_stake`: check `fights.is_title_fight` instead of `bout_type`
- `schedule_next_event()`: set `card_slot='main_event'`, `is_title_fight=0` for auto-scheduled fights
- Seed: set `card_slot='main_event'`, `is_title_fight=1` for the seeded title fight
- `bout_type` column stays for backward compatibility but is deprecated

**Card size limits by promotion size (for future booking UI, NOT implemented now):**
- small: 4-6 fights, mid: 5-8 fights, major: 6-12 fights

**Acceptance checklist:**
- [ ] `fights.card_slot` column added with CHECK constraint
- [ ] `fights.is_title_fight` column added with CHECK constraint
- [ ] `event_cards.is_co_main` column added with CHECK constraint
- [ ] Schema version 2.1.1 (PATCH — adding columns to existing tables for a fix)
- [ ] Migration name `v2_1_1_fight_importance_columns`
- [ ] `_resolve_title_after_fight()` checks `is_title_fight=1` (not `bout_type='title_fight'`)
- [ ] `fight_history.title_at_stake` checks `is_title_fight` (not `bout_type`)
- [ ] `schedule_next_event()` sets `card_slot='main_event'`, `is_title_fight=0`
- [ ] Seeded title fight has `card_slot='main_event'`, `is_title_fight=1`
- [ ] All existing tests pass

### Detailed task brief: 14.5+14.6+14.7 — Fighter Schema Expansion

**Pillars served:** Growth (attributes are the substrate fighters grow
on), Discovery (archetype bias makes regen fighters feel distinct)

**Brief.** Migrate `fighter_attributes` from 4 to 25 columns and
`fighter_personality` from 3 to 20 fields. Add archetype bias columns
to `style_archetypes` and `personality_archetypes`. Add 14 missing
columns to `fighters`, 6 to `promotions`, 8 to `gyms`. Fix the
pre-existing `current_date` SQLite quirk. New module `src/fighter_gen.py`
with generation functions reusable by the backfill and Task 14's
`generate_fighter()`. Seed 7 style archetypes + 5 personality archetypes
with bias JSON. Backfill all 5 existing fighters with the new columns.
Schema version bumped to 2.0.0 (MAJOR — first major version).

**Scope.** Schema migration on 6 existing tables + 2 archetype tables.
No brand-new tables. New module `src/fighter_gen.py`. Fix in `app.py`
and `tick_processor.py` (column qualification).

**Schema — fighter_attributes (4 → 25 columns):**

Add 21 new columns, all `INTEGER NOT NULL DEFAULT 50 CHECK (col BETWEEN 0 AND 100)`:

| Group | New columns |
|---|---|
| Striking | punch_accuracy, kick_power, kick_accuracy, head_movement |
| Range | footwork, clinch_striking, clinch_offense, clinch_defense |
| Grappling | takedown_offense, takedown_defense, top_control, bottom_game, submission_offense, submission_defense, scramble_ability, cage_wrestling |
| Physical | recovery_rate, speed_explosiveness, strength, durability, flexibility |
| Mental | adaptability |

Keep existing (values preserved): punch_power, cardio, fight_iq, chin

**Schema — fighter_personality (3 → 20 fields):**

Add 17 new fields, all `INTEGER NOT NULL DEFAULT 50 CHECK (col BETWEEN 0 AND 100)`:

| Group | New fields |
|---|---|
| Temperament | risk_taking, killer_instinct, grit, discipline, patience |
| Career | ambition, loyalty, charisma, attention_seeking, coachability, professionalism |
| Resilience | ego, resilience, sportsmanship, travel_comfort |
| Dynamic | focus, fatigue_tolerance |

Keep existing (values preserved): aggression, composure, morale

**Schema — fighters (+14 columns):**

height_cm INTEGER, reach_cm INTEGER, stance TEXT CHECK IN ('orthodox','southpaw','switch'), handedness TEXT CHECK IN ('right','left','ambidextrous'), injury_proneness INTEGER DEFAULT 50 CHECK (0-100), weight_cut_difficulty INTEGER DEFAULT 50 CHECK (0-100), consistency INTEGER DEFAULT 50 CHECK (0-100), clutch_factor INTEGER DEFAULT 50 CHECK (0-100), marketability INTEGER DEFAULT 50 CHECK (0-100), fan_friendliness INTEGER DEFAULT 50 CHECK (0-100), promo_boost INTEGER DEFAULT 0 CHECK (-100 to 100), preferred_gameplans TEXT (JSON), bad_matchup_tags TEXT (JSON), is_deceased INTEGER DEFAULT 0 CHECK IN (0,1)

**Schema — promotions (+6 columns):**

brand_tone TEXT DEFAULT 'standard', starting_budget REAL DEFAULT 0, broadcast_tier TEXT DEFAULT 'local_stream', ownership_type TEXT DEFAULT 'startup', ai_aggression INTEGER DEFAULT 50 CHECK (0-100), ai_spending_style TEXT DEFAULT 'balanced'

**Schema — gyms (+8 columns):**

reputation INTEGER DEFAULT 50 CHECK (0-100), membership_cost REAL DEFAULT 0, facility_quality INTEGER DEFAULT 50 CHECK (0-100), medical_support INTEGER DEFAULT 50 CHECK (0-100), sparring_depth INTEGER DEFAULT 50 CHECK (0-100), development_focus INTEGER DEFAULT 50 CHECK (0-100), culture_tone TEXT DEFAULT 'balanced', weight_cut_support INTEGER DEFAULT 50 CHECK (0-100)

**Schema — style_archetypes + personality_archetypes (+1 column each):**

attribute_bias TEXT (JSON), trait_bias TEXT (JSON)

**Seed archetypes (7 style + 5 personality):**

Style archetypes with bias JSON:
1. Balanced (existing, add bias: {"punch_power": 5, "cardio": 5, "fight_iq": 5})
2. Striker ({"punch_power": 15, "kick_power": 15, "punch_accuracy": 10, "head_movement": 10, "takedown_defense": -10, "submission_offense": -10})
3. Grappler ({"takedown_offense": 15, "top_control": 15, "submission_offense": 15, "punch_power": -5, "kick_power": -5, "head_movement": -5})
4. Wrestler ({"takedown_offense": 20, "top_control": 15, "cage_wrestling": 15, "strength": 10, "submission_offense": -10, "kick_power": -10})
5. Brawler ({"punch_power": 20, "chin": 15, "durability": 10, "footwork": -15, "fight_iq": -10, "cardio": -5})
6. Counter-Striker ({"punch_accuracy": 15, "head_movement": 15, "footwork": 15, "fight_iq": 15, "aggression": -10, "takedown_offense": -10})
7. Submission Specialist ({"submission_offense": 20, "bottom_game": 15, "flexibility": 15, "punch_power": -10, "chin": -5})

Personality archetypes with bias JSON:
1. Calm (existing, add bias: {"composure": 15, "aggression": -10, "patience": 10})
2. Aggressive ({"aggression": 20, "killer_instinct": 15, "patience": -15, "discipline": -5})
3. Methodical ({"discipline": 15, "patience": 20, "fight_iq": 10, "risk_taking": -10})
4. Showman ({"charisma": 20, "attention_seeking": 20, "ego": 10, "sportsmanship": -10})
5. Quiet Professional ({"coachability": 15, "professionalism": 15, "discipline": 10, "attention_seeking": -15})

**`src/fighter_gen.py` module:**

```python
def generate_attribute_block(archetype_id=None) -> dict:
    """Generate 25-attribute block, optionally biased by archetype.
    value = clamp(50 + bias.get(col, 0) + random_noise(-8, 8), 0, 100)"""

def generate_personality_block(archetype_id=None) -> dict:
    """Generate 20-personality block, optionally biased by archetype.
    value = clamp(50 + bias.get(col, 0) + random_noise(-8, 8), 0, 100)"""

def generate_physical_block() -> dict:
    """Generate height, reach, stance, handedness.
    Height: 165-195cm (normal around 178)
    Reach: height ± 5-10cm
    Stance: 80% orthodox, 15% southpaw, 5% switch
    Handedness: 85% right, 10% left, 5% ambidextrous"""
```

**`current_date` quirk fix (14.7):**

In `app.py` `get_clock()` and `tick_processor.py` `_check_retirements()`
and `_check_contract_expiry()` and `run_tick()`: qualify all bare
`current_date` references as `simulation_clock.current_date`.

**Backfill approach:**
1. Existing 4 attribute values (punch_power, cardio, fight_iq, chin) are
   PRESERVED — do not overwrite.
2. Existing 3 personality values (aggression, composure, morale) are
   PRESERVED.
3. New columns filled using `generate_attribute_block()` /
   `generate_personality_block()` with the fighter's existing archetype_id.
4. New fighters columns (height, reach, stance, etc.) filled using
   `generate_physical_block()` + sensible defaults for meta columns
   (injury_proneness=50, marketability=50, etc.).
5. New promotions columns: AC gets broadcast_tier='regional_tv',
   starting_budget=500000, ai_aggression=30 (player-controlled, low AI).
   RFL gets broadcast_tier='local_stream', starting_budget=200000,
   ai_aggression=60 (more aggressive AI for future Task 25).
6. New gyms columns: sensible defaults (facility_quality=60,
   medical_support=50, sparring_depth=55, development_focus=60).

**Acceptance checklist:**
- [ ] `fighter_attributes` has all 25 columns with CHECK (0-100)
- [ ] `fighter_personality` has all 20 fields with CHECK (0-100)
- [ ] Existing 4+3 values preserved after migration
- [ ] `fighters` has 14 new columns with correct types/defaults
- [ ] `promotions` has 6 new columns with correct types/defaults
- [ ] `gyms` has 8 new columns with correct types/defaults
- [ ] `style_archetypes.attribute_bias` and `personality_archetypes.trait_bias` columns added (TEXT, JSON)
- [ ] 7 style archetypes + 5 personality archetypes seeded with bias JSON
- [ ] `src/fighter_gen.py` exists with 3 generation functions, importable
- [ ] All 5 existing fighters backfilled (no NULLs in new columns)
- [ ] `current_date` quirk fixed (tick advances by exactly 1 day, not jumping to today's real date)
- [ ] `generate_fighter()` (Task 14 regen) updated to use `fighter_gen.py`
- [ ] Schema version bumped to 2.0.0 (MAJOR)
- [ ] Migration name is `v2_0_0_fighter_schema_expansion`
- [ ] SCHEMA_DRIFT_AUDIT.md updated (fighter_attributes: WRONG → OK, fighter_personality: WRONG → OK, fighters: THIN → OK, promotions: THIN → OK, gyms: THIN → OK)
- [ ] CHANGELOG.md entry
- [ ] New acceptance test `scripts/test_fighter_attributes.py`:
  - All 25 attribute columns exist with CHECK constraints
  - All 20 personality fields exist with CHECK constraints
  - Existing 4+3 values preserved
  - All new columns populated (no NULLs)
  - Archetype bias works: 100 "Brawler" fighters vs 100 "Counter-Striker" fighters — brawler averages higher on punch_power/chin, lower on footwork/fight_iq
  - `fighter_gen.py` functions return correct shapes (25 keys, 20 keys)
  - `generate_fighter()` uses `fighter_gen.py` (regen fighters get archetype-biased attributes, not all-50s)
  - `current_date` quirk fixed (tick advances by exactly 1 day)
- [ ] **No regression**: all 12 existing tests pass (with dynamic-version pattern handling the 2.0.0 bump)

**Delegation.** full-stack-developer subagent. This is the largest
single schema change since the project started. Thorough testing is
critical.

---

### Detailed task brief: B1 — Beat-Level Fight Engine (Basic)

**Pillars served:** Conflict (the fight is the primary conflict),
Watch Rise (dramatic moments players remember)

**Brief.** Replace the current single-resolution `resolve_next_fight()`
with a beat-level round simulation. A "beat" is one discrete exchange
within a round. Target 12-28 beats per round, density driven by the
fighters' pace attributes. Each beat's outcome is computed from the
attributes relevant to its current phase (standing, clinch, cage,
ground_top, ground_bottom, scramble). `fight_rounds` aggregate columns
become computed sums over that round's `fight_beats` rows.

**Scope.** New tables `fight_beats` + `fight_rounds`. New function
`resolve_round()` called by `resolve_next_fight()` once per round.
The `_resolve_outcome()` pure function from Task 3 is replaced.

**Dependencies.** Task 14.5 (needs full 25-attribute set).

**Schema — fight_beats + fight_rounds:** See STAGE3_EXPANSION_PLAN.md Part 2 for full schema.

**Mechanics:** See STAGE3_EXPANSION_PLAN.md Part 2 for:
- Beat count formula
- Phase-to-attribute mapping (6 phases)
- Phase transitions (takedown → ground, scramble → standing)
- Decision scoring (10-point must system, round-by-round)

**Acceptance checklist:**
- [ ] `fight_beats` table created
- [ ] `fight_rounds` table created
- [ ] `resolve_round()` generates 12-28 beats per round
- [ ] Phase transitions work (takedown → ground, scramble → standing)
- [ ] `fight_rounds` aggregates match SUM over `fight_beats`
- [ ] Decision scoring works (10-point must, unanimous/split/draw)
- [ ] All-90 beats all-30 ≥80% over 100 sims
- [ ] No single result type >60%
- [ ] Schema version 2.1.0
- [ ] `test_fight_resolver.py` updated for new engine shape
- [ ] All existing tests pass

**Delegation.** full-stack-developer subagent. After 14.5+14.6+14.7 lands.

---

### Detailed task brief: B2 — Beat Engine Depth (fatigue, momentum, finishes, importance)

**Pillars served:** Conflict (dramatic finishes, pressure responses), Watch Rise
(the "oh my god it's over" moment, the "he rose to the occasion" story)

**Brief.** Add fatigue system (gas depletes across beats/rounds), momentum
system (clustered outcomes from knockdowns/near-finishes), mid-round finishes
(KO/submission/doctor/corner/DQ), commentary beat selection (3-14 highlight
beats), and **fight importance + pressure modifiers** (fighters with high
clutch_factor rise to the occasion in main events; fighters with low
clutch_factor bottle under pressure).

**Dependencies.** Task B1 (needs the basic beat loop), pre-B2 schema fix
(needs `fights.card_slot` + `fights.is_title_fight` columns).

**Fight importance system (NEW — added during pre-B2 planning):**

Fight importance is a computed value (0-100), not stored:
- Card slot weight (40%): main_event=100, co_main=80, featured_prelim=60, prelim=40, opener=20
- Title at stake (30%): yes=100, no=0
- Rivalry heat (15%): from rivalries table (Task 22, future — 0 for now)
- Fighter popularity (15%): avg marketability of both fighters

Pressure response per fighter (computed, not stored):
`pressure_response = clutch_factor*0.35 + composure*0.25 + consistency*0.20 + focus*0.10 + grit*0.10`

In high-importance fights (importance > 60):
- pressure_response >= 70: "Rises to the occasion" — +5% to beat attack/defense scores
- pressure_response <= 30: "Bottler" — -10% to beat attack/defense scores
- 30 < pressure_response < 70: no modifier (baseline)

This creates the stories the Soul document demands:
- "Unknown prospect upsets the champion in the main event — he rose to the occasion."
- "Veteran chokes in the title fight — crumbled under the spotlight."
- "Journeyman performs consistently whether it's the opener or the main event."

**Acceptance checklist:**
- [ ] Fatigue: cardio=90 out-lands cardio=30 increasingly in later rounds
- [ ] Momentum: knockdown raises finish probability for subsequent beats
- [ ] Mid-round KO/TKO works (cumulative damage threshold)
- [ ] Mid-round submission works (submission_offense vs defense + flexibility + composure)
- [ ] Doctor stoppage works (cumulative damage + durability)
- [ ] Corner stoppage works (3+ lost rounds + low grit/composure)
- [ ] DQ works (low discipline + illegal strike, rare)
- [ ] Commentary beat selection picks the right beats (knockdowns, near-finishes, finish, big momentum swings)
- [ ] Fight importance computed from card_slot + is_title_fight + marketability
- [ ] Pressure modifiers: high clutch_factor fighter gets bonus in main events
- [ ] Pressure modifiers: low clutch_factor fighter gets penalty in main events
- [ ] Schema version 2.2.0
- [ ] All existing tests pass

**Delegation.** full-stack-developer subagent. After B1 + pre-B2 fix lands.

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

### Task ID 16 — Training camps — **DONE** (commit pending)

**Status:** Schema v2.4.0 → v2.5.0 (MINOR). 1 new table (`training_camps`,
19 columns). Migration `v2_5_0_add_training_camps`. 85 sub-checks
across 11 cases in `scripts/test_training_camps.py`.

**Implementation:**
- `_create_training_camp()` in app.py — called by schedule_next_event
  for each of the 2 booked fighters. Camp window: start_date =
  event_date - 14, end_date = event_date, camp_duration_days = 14.
  camp_focus derived from the fighter's style archetype via
  `_ARCHETYPE_NAME_TO_CAMP_FOCUS` (7 archetype → camp_focus mappings;
  default 'general').
- `_check_training_camps()` in tick_processor.py — runs every tick
  AFTER _check_injury_recovery. For each active, uncompleted camp
  whose [start_date, end_date] window contains current_date:
  * Progression (current_date < end_date): fatigue +2-5 (reduced
    by cardio + fatigue_tolerance), morale ±0-2 (dampened by
    coachability, biased by gym culture_tone), injury_risk +2-5
    (increased by injury_proneness, reduced by gym medical_support).
    If injury_risk > 80: spawn a training injury from
    `_TRAINING_INJURY_POOL` (7 entries — torn ACL, hamstring strain,
    shoulder labrum tear, rib sprain, training concussion, wrist /
    ankle sprain), reduce career_health, write "suffers X in
    training" news item, force-complete the camp as 'injured'.
  * Completion (current_date == end_date): pick 2-4 attributes from
    the camp_focus pool, apply +1 to +3 base gain scaled by gym_spec_
    mult (0.5-1.5 from facility_quality + development_focus),
    coach_mult (0.5-1.5 from coachability), fatigue_factor (0.5-1.0
    from fatigue_tolerance vs camp_fatigue). Capped at fighter_career.
    potential. Write attribute_changes JSON + camp_result_summary +
    completion news item.
- `_get_camp_fatigue_for_event()` reader in app.py — called by
  resolve_next_fight to apply the "Fatigue > 50 = reduced starting
  gas" rule. Starting gas = 100 - max(0, camp_fatigue - 50), floored
  at 50.

**Answers to the brief's open questions:**
- Camp starts 14 days before the event (`_CAMP_LEAD_DAYS = 14`).
- Camp focus = derived from style archetype (Striker → striking,
  Grappler → grappling, Wrestler → wrestling, Submission Specialist
  → submission, Brawler/Counter-Striker → striking, Balanced →
  general; default 'general').
- Camp fatigue > 50 reduces starting gas in resolve_next_fight,
  floored at 50.
- Camp injury risk > 80 spawns a training injury via the Task 15
  injuries table (training-injury pool distinct from the fight-injury
  pool). Career_health is reduced; the camp is force-completed.
- UI camp reports deferred to a future task (the camp_result_summary
  column stores the raw data; Task 19's interpretation layer will
  translate it for the UI per CONVENTIONS §14).

**Decisions logged in worklog:**
- D1: 19 columns (brief's parenthetical list) vs "20" (brief's prose
  header) — implemented the 19 enumerated (the list is authoritative,
  the prose "20" is an off-by-one typo).
- D2: Training-injury pool uses body_area values from the injuries
  CHECK constraint's enumerated set (the brief's "leg" was changed
  to "hip" — "leg" is not in the CHECK).

### Task ID 17 — Weight cuts — **DONE** (commit `pending`)

**Status:** Schema v2.6.0 → v2.7.0 (MINOR). 1 new table (`weight_cut_log`,
14 columns). Migration `v2_7_0_add_weight_cut_log`. 41 sub-checks
across 10 cases in `scripts/test_weight_cuts.py`.

**Implementation:**
- `_run_weight_cut()` in app.py — called by `resolve_next_fight`
  BEFORE the fight resolves. For each of the 2 fighters, rolls against
  the miss probability (derived from `weight_cut_difficulty` + age +
  `camp_weight_cut_pressure` − gym `weight_cut_support`).
- 5 cut outcomes:
  * `made_weight` — no penalty, fight proceeds normally
  * `missed_small` (< 1kg) — 20% purse forfeiture, no cardio penalty
  * `missed_medium` (1-3kg) — 30% purse forfeiture, 15 cardio penalty
  * `missed_large` (> 3kg) — fight CANCELLED (no_contest, opponent
    gets 50% purse)
  * `cancelled` — fight cancelled before the cut (reserved for future)
- Miss distribution: 50% small, 35% medium, 15% large.
- Cardio penalty applied to starting gas (`gas = 100 - cardio_penalty`,
  floored at 50).
- News items written for every cut result (topic='weight_cut').

**Answers to the brief's open questions:**
- Weight cut difficulty: per-fighter static value
  (`fighters.weight_cut_difficulty`, 0-100, added in Task 14.5).
  Modified by age (+1% per year over 30, max +15%) and
  `camp_weight_cut_pressure` (0-20%).
- Missing weight: three outcomes based on how badly they miss (small/
  medium/large). Large miss → fight cancelled.
- Cut affects performance: missed_medium applies a 15-point cardio
  penalty to starting gas.

**Design Law (§13):** Conflict (pre-fight tension), Investment
(manage weight cut difficulty), Anticipation ("will he make weight?"),
Stories ("champion missed weight, stripped, interim title fight set").

### Task ID 18 — Scouting system — **DONE** (commit `pending`)

**Status:** Schema v2.8.0 → v2.9.0 (MINOR). 1 new table
(`scouting_reports`, 18 columns). Migration `v2_9_0_add_scouting_reports`.
40 sub-checks across 12 cases in `scripts/test_scouting.py`.

**Also fixed:** Growth logic in `_complete_training_camp` — potential
is no longer guaranteed success. Added `effective_ceiling` that's below
potential based on age, health, personality, and diminishing returns.
Most fighters never reach their true potential.

**Implementation:**
- `src/scouting.py` — the scouting engine with:
  * Scout attributes stored in `staff.specialty` JSON: `eye_for_talent`,
    `technical_analysis`, `character_reading`, `mistake_rate`,
    `bias_style`, `bias_nationality`, `bias_aggression`
  * `assign_scout()` — stores assignment in scout's specialty JSON
  * `_check_scouting_assignments()` — called on tick, generates reports
    after 7 days of observation
  * `generate_scouting_report()` — the core function:
    1. Loads fighter's TRUE values
    2. Applies Gaussian noise based on scout accuracy
       (noise_std = (100 - attribute) / 4)
    3. Applies biases (style +5/-5, nationality noise mult, aggression)
    4. Rolls for mistakes (5 types: overestimate, underestimate,
       misread strength/weakness, miss key trait, confidence mismatch)
    5. Converts to descriptors via `voice.py` (Task 19)
    6. Writes `scouting_reports` row + news item
  * `mark_stale_reports()` — marks reports stale when fighter changes
- `scouting_reports` table — 18 columns. Stores estimated potential,
  ceiling, floor, strengths, weaknesses as DESCRIPTORS (not raw numbers).
  `scout_confidence` (0-100), `is_stale` (0/1), `report_text` (full
  prose report).
- Tick integration: `_check_scouting_assignments` wired into `run_tick()`
  after `_check_training_camps`.
- Report staleness: `mark_stale_reports()` called on camp completion,
  fight resolution, and injury events.
- Seed Phase 2: 2 scouts per promotion (20 total) with randomized
  scout attributes (eye_for_talent 35-85, mistake_rate 5-35, random
  style/nationality biases).
- Growth logic fix: `effective_ceiling = potential * age_factor *
  health_factor * personality_factor`. Age factor: 1.0 at 18-27,
  declining to 0.35 at 37+. Health factor: 1.0 at 90+, declining to
  0.15 below 30. Personality factor: (discipline + coachability) / 200.
  Diminishing returns: growth rate halves as attributes approach
  effective_ceiling. Most fighters plateau well below their potential.

**Answers to the brief's open questions:**
- Accuracy: based on scout's eye_for_talent (potential), technical_
  analysis (attributes), character_reading (personality). Gaussian
  noise with std = (100 - attribute) / 4. A 90-eye scout has ±2.5
  noise; a 50-eye scout has ±12.5.
- Estimates use descriptors (voice.py), NOT raw numbers. Player sees
  "high ceiling, above-average power" — not "potential=72."
- Hidden traits: all 25 attributes + 20 personality traits are
  estimated with noise. Consistency, clutch_factor, etc. are
  estimated like any other attribute.
- Staleness: reports marked stale on camp completion, fight resolution,
  injury. Stale reports show a warning but remain readable.
- UI: player calls `assign_scout(scout_id, target_fighter_id)` — future
  UI tab will display this.

**Potential ≠ guaranteed success:**
- The scout estimates the fighter's CEILING (potential), but the
  fighter may never reach it. The effective_ceiling growth logic
  reduces the actual ceiling based on age, health, personality, and
  diminishing returns.
- A 20-year-old with potential=90, perfect health, high discipline:
  effective_ceiling = 90 * 1.0 * 1.0 * 0.9 = 81. Can reach ~81.
- A 32-year-old with potential=90, health=70, avg discipline:
  effective_ceiling = 90 * 0.80 * 0.90 * 0.5 = 32. Already declining.
- Most fighters never hit their true potential — only young, healthy,
  disciplined fighters in good gyms get close.

**Design Law (§13):** Discovery (scouting reveals identity without raw
numbers), Investment (player assigns scouts to evaluate prospects),
Stories (scouts make mistakes — "bust" and "steal" narratives).

### Task ID 19 — Voice / interpretation layer — **DONE** (commit `pending`)

**Status:** Schema v2.7.0 → v2.8.0 (MINOR). 1 new table
(`fighter_descriptors`, 9 columns). Migration
`v2_8_0_add_fighter_descriptors`. 92 sub-checks across 8 cases in
`scripts/test_voice.py`.

**Implementation:**
- `src/voice.py` — pure module (no DB, no I/O, no side effects) with:
  * `ATTRIBUTE_DESCRIPTORS` — 25 attributes × 7 tiers × 2-3 variants
    = ~500 descriptor strings ("one-punch knockout threat", "iron
    chin", "fades in deep waters")
  * `PERSONALITY_DESCRIPTORS` — 20 traits × 7 tiers × 2-3 variants
    = ~400 descriptor strings ("comes forward like a freight train",
    "ice in his veins", "no killer instinct")
  * `POTENTIAL_DESCRIPTORS` — 7 tiers ("generational talent ceiling",
    "high ceiling", "limited potential")
  * `describe_attribute(attr_name, value, rng)` → str
  * `describe_personality(trait_name, value, rng)` → str
  * `describe_potential(potential, scouted, rng)` → str or None
  * `describe_career_stage(age, record, is_champion, streaks, rng)` → str
  * `describe_career_health(health, rng)` → str
  * `describe_overall(fighter_data, rng)` → one-sentence summary
  * `build_descriptor_snapshot(attrs, pers, fighter_data, rng)` → dict
- `fighter_descriptors` snapshot table — caches computed descriptors
  as JSON per fighter. Updated on trigger events (NOT every UI view):
  * Training camp completion (attributes change)
  * Fight resolution (record, ELO, streaks, title status change)
  * Injury creation (career_health drops)
  * Injury recovery (career_health restores)
- `update_fighter_descriptor_snapshot(conn, fighter_id)` in app.py —
  reads attrs/pers/career from DB, calls voice.build_descriptor_
  snapshot(), writes to fighter_descriptors table. Uses a per-fighter
  deterministic RNG (seed=fighter_id) so descriptors are stable
  across calls (no flickering).
- Trigger wiring:
  * `resolve_next_fight` — calls update for both fighters after all
    side effects complete
  * `_complete_training_camp` in tick_processor.py — calls update
    after attribute gains applied
  * `_check_injury_recovery` in tick_processor.py — calls update
    after career_health restored
  * `_progress_training_camp` training-injury path — calls update
    after career_health reduced

**Answers to the brief's open questions:**
- Descriptor bands: 7 tiers per CONVENTIONS §14.3 — 90-100 elite,
  75-89 strong, 60-74 capable, 40-59 average, 25-39 limited, 10-24
  poor, 0-9 abysmal.
- Multi-attribute descriptors: `describe_overall()` combines career
  stage + top 2-3 attributes into one sentence. Future tasks (news
  engine, punditry) can build more complex multi-attribute phrases
  on top of the single-attribute descriptors.
- Context-dependent descriptors: not yet. The current descriptors
  are context-neutral. Future tasks can add context variants (scout
  report vs commentary vs punditry) by extending the descriptor dicts.
- News engine integration: Task 23 will import voice.py and use
  describe_attribute/describe_career_stage to narrate events instead
  of raw numbers.

**Performance architecture:**
- voice.py is pure — no DB, no I/O. Fast (dict lookup + random.choice).
- fighter_descriptors table caches the computed descriptors as JSON.
  The UI reads one row per fighter (SELECT * FROM fighter_descriptors
  WHERE fighter_id=?). No recomputation on every view.
- Snapshots are updated on trigger events only (camp, fight, injury).
  A fighter profile view never triggers recomputation.
- snapshot_version increments on each update — useful for cache
  busting + tracking how many times the fighter's story changed.

**Design Law (§13):** Discovery (descriptors reveal identity without
raw numbers), Investment (camp completion updates descriptors —
growth visible), Growth (tier changes when attributes cross band
boundaries), Conflict (injury changes career_health_desc), Legacy
(snapshots preserve the fighter's story over time), Stories
("one-punch knockout threat", "iron chin", "fades in deep waters").

**No raw numbers in UI (§14):** verified — 92 test sub-checks confirm
no attribute descriptor contains digit characters. Potential is None
when not scouted (hidden until Task 18).



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

### Task ID 18.5 — Event bus refactor

**Brief (needs expansion).** Refactor `resolve_next_fight()` and
`_check_retirements()` from monolithic functions with hardcoded side
effects into event-publishing functions. Each system subscribes to the
events it cares about (FightResolved, TitleChanged, FighterRetired,
ContractExpired, etc.). This decouples systems and makes adding new
side effects (social media, rivalries, punditry, show rating) a matter
of adding a subscriber, not editing the monolith.

**Dependencies:** All Stage 3 tasks complete (injuries, camps, weight
cuts, scouting, voice layer all in place — enough systems to justify
the refactor).

**Pillars served:** All (the event bus is infrastructure that supports
every system).

### Task ID 31 — Gameworld seed: living history

**Brief (needs expansion).** Generate a believable gameworld with years
of simulated history. Not just a starting state — a world that feels
like it has existed for years:
- 100+ fighters across multiple promotions with full career histories
  (records, title reigns, injuries, rivalries)
- 5+ promotions of varying sizes (small regional, mid-tier national,
  major established)
- Historical events (past cards with results, not just future scheduled)
- Pre-existing rivalries and beefs
- Retired legends in the hall of fame
- Rankings that reflect career histories
- News items covering past milestones
- Gym ecosystems with developed talent pipelines

**Dependencies:** All systems in place (Stage 5, after Task 30). The
seed needs every table to be available so it can populate the full
living history.

**Pillars served:** All 5 — the living history seed is what makes the
world feel alive from the first click. Without it, the player starts in
an empty room. With it, the player inherits a world with stories
already in motion — champions to dethrone, legends to remember,
rivalries to continue.

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
