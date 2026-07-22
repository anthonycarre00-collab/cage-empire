# Changelog

All notable changes to CAGE EMPIRE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to the schema versioning rules in
`docs/CONVENTIONS.md`.

## [Unreleased]

### Added
- `fighter_career.potential` column (INTEGER NOT NULL DEFAULT 50 CHECK
  (potential BETWEEN 0 AND 100)) — the fighter's growth ceiling (Task
  pre-B1-fixes, schema 2.0.1 MINOR). Training camps (Task 16, future)
  will push attributes toward this ceiling with diminishing returns as
  they approach it. Without this column, every fighter has unlimited
  growth potential and the Talent Hunter fantasy
  (CAGE_EMPIRE_SOUL.md Fantasy 1) collapses — a journeyman could
  theoretically train every attribute to 100. The DEFAULT 50 keeps
  existing rows valid; new fighters get potential from
  `fighter_gen.generate_potential()` (10% elite 70-90, 30% solid 50-69,
  60% limited 25-49). Scarcity makes elite prospects exciting to find.
- `fighter_career.title_reigns` column (INTEGER NOT NULL DEFAULT 0 CHECK
  (title_reigns >= 0)) — counts how many title reigns this fighter has
  had (Task pre-B1-fixes, schema 2.0.1 MINOR). Incremented by
  `_resolve_title_after_fight()` in app.py every time the fighter wins
  a title (vacant title claimed OR reigning champion dethroned). It is
  the clean, reliable signal the retirement path uses to decide whether
  to create a `fighter_memory_links` "successor" row — only fighters
  who held a title get the "reminiscent of former champion {name}"
  treatment. Reserving memory resurfacing for champions makes the
  comparison meaningful.
- `fighter_gen.generate_potential()` function (Task pre-B1-fixes) —
  returns an int in [25, 90] using the rare-elite distribution: 10%
  elite (70-90), 30% solid (50-69), 60% limited (25-49). Pure function
  — no I/O, no side effects. Called by `app.generate_fighter()` to set
  the new fighter's `potential` column at creation time.
- Champion-successor memory resurfacing (Task pre-B1-fixes) — when a
  fighter with `fighter_career.title_reigns > 0` retires, the
  retirement path now (1) creates a `fighter_memory_links` row with
  `link_type='successor'` linking the new replacement fighter to the
  retiring champion, with `link_strength=min(50 + 10*reigns, 100)`,
  and (2) writes a 'legacy'-topic news item with the headline "New
  prospect {name} emerges on the scene — fight fans are already drawing
  comparisons to former champion {retiring_name}." This is the
  memory-resurfacing payoff: the world remembers who the retiring
  champion was and draws the comparison to the new prospect. Non-
  champion retirements get neither the memory link nor the extra news
  — only the standard "new prospect emerges" news from
  `generate_fighter`. This keeps the memory resurfacing rare and
  meaningful (a "stamp of greatness"), not noise.

### Changed
- All 12 archetype biases softened ~40-50% (Task pre-B1-fixes). The
  maximum absolute bias dropped from 20 to 10. Modern MMA fighters at
  the highest level are well-rounded; archetypes should be tendencies,
  not extremes. A Brawler should hit a bit harder and take a better
  shot, but not be helpless on the feet or gas after 1 round. The 7
  style archetypes and 5 personality archetypes all use the softened
  values per the brief. The existing `test_fighter_attributes.py` case
  D statistical checks (Brawler > Counter-Striker on punch_power/chin,
  CS > Brawler on footwork/fight_iq, with a >5 margin) STILL pass with
  the softened biases (margins of 10, 8, 16, 13 — all comfortably >5).
- `app.generate_fighter()` now sets `potential` on the new fighter via
  `fighter_gen.generate_potential()` (Task pre-B1-fixes). Previously
  the fighter_career INSERT used the schema DEFAULT 50; now it
  explicitly INSERTs the generated value. All other fighter_career
  columns (record, streaks, career_health, title_reigns) still use
  their schema DEFAULTs (0-0-0, 100, 0) — sensible for a fresh
  prospect.
- `app._resolve_title_after_fight()` now increments
  `fighter_career.title_reigns` for the new champion when a title is
  won (vacant title claimed OR reigning champion dethroned). A
  successful title defense (champion wins) does NOT increment the
  counter — it's a HISTORICAL reign counter, not a current-reign flag.
  The title-level `titles.title_reigns_count` is unchanged (it tracks
  the title's history across all champions, not per-fighter).
- Schema version bumped 2.0.0 → 2.0.1 (MINOR — adding 2 new columns to
  an existing table). Migration name
  `v2_0_1_potential_memory_archetype_fix`. The version-check gate
  (Task ID 5) refuses to clobber a newer on-disk schema — old scripts
  running against a 2.0.1 DB will abort with a clear RuntimeError.

### Fixed
- None in this task. (No bugs fixed — purely additive + the
  design-fix softening of archetype biases.)

### Known issues (flagged for supervisor)
- `test_fighter_attributes.py` case A.3 (exact migration name check
  for `v2_0_0_fighter_schema_expansion`) — STALE after the v2.0.1 bump.
  The dynamic-prefix check (A.2) still passes; only the exact-name
  check fails because the new migration is
  `v2_0_1_potential_memory_archetype_fix`. Flagged as D1 in the
  worklog; NOT modified per CONVENTIONS §11.
- `test_fighter_attributes.py` case B.7 (6 exact-value assertions on
  Brawler bias) — STALE after bias softening. The new Brawler bias is
  `{"punch_power": 10, "chin": 8, "durability": 5, "footwork": -8,
  "fight_iq": -5, "cardio": -3}` (was punch_power=20, chin=15,
  durability=10, footwork=-15, fight_iq=-10, cardio=-5). Flagged as
  D2; NOT modified per CONVENTIONS §11.
- `test_fighter_attributes.py` case B.8 (6 exact-value assertions on
  Counter-Striker bias) — STALE after bias softening. The new CS bias
  is `{"punch_accuracy": 8, "head_movement": 8, "footwork": 8,
  "fight_iq": 8, "aggression": -5, "takedown_offense": -5}` (was
  punch_accuracy=15, head_movement=15, footwork=15, fight_iq=15,
  aggression=-10, takedown_offense=-10). Flagged as D3; NOT modified
  per CONVENTIONS §11.
- Net effect: `test_fighter_attributes.py` goes from 260/260 to
  247/260 (13 stale assertions). The new acceptance test
  `scripts/test_pre_b1_fixes.py` covers the same ground (case B
  verifies the new bias values exactly; case A verifies the new
  migration name exactly) so the supervisor can update
  `test_fighter_attributes.py`'s stale constants during sign-off
  without losing coverage.

## [2.0.0] - 2026-07-21

### Added
- 68 new columns across 6 existing tables + 2 archetype tables in the
  largest single schema expansion since the project started (Task ID
  14.5+14.6+14.7, schema 2.0.0 MAJOR). This is the depth-of-sim
  expansion the v1.6 spec called for and the audit (SCHEMA_DRIFT_AUDIT
  §Z.1, §Z.3, §Z.4) flagged as the most critical gap remaining — it
  unblocks Tasks 15 (injuries), 16 (training camps), 17 (weight cuts),
  18 (scouting), 19 (voice layer), 24 (matchup analysis), 25 (rival
  promotion AI), and 26 (show rating). No new tables, no columns
  removed — purely additive. The MAJOR bump marks the transition from
  thin skeleton (4 attributes, 3 personality traits, coin-flip-
  equivalent resolver) to real simulation depth.
- `fighter_attributes` expanded 4 → 25 columns (Task ID 14.5). The
  existing 4 (punch_power, cardio, fight_iq, chin) are preserved with
  their values and WITHOUT retroactive CHECK constraints (avoids
  breaking existing tests that UPDATE these with arbitrary values).
  21 new columns added with `INTEGER NOT NULL DEFAULT 50 CHECK (col
  BETWEEN 0 AND 100)`, grouped per STAGES.md §14.5:
  * Striking: punch_accuracy, kick_power, kick_accuracy, head_movement
  * Range: footwork, clinch_striking, clinch_offense, clinch_defense
  * Grappling: takedown_offense, takedown_defense, top_control,
    bottom_game, submission_offense, submission_defense,
    scramble_ability, cage_wrestling
  * Physical: recovery_rate, speed_explosiveness, strength, durability,
    flexibility
  * Mental: adaptability
- `fighter_personality` expanded 3 → 20 fields (Task ID 14.5). The
  existing 3 (aggression, composure, morale) are preserved. 17 new
  fields with the same `INTEGER NOT NULL DEFAULT 50 CHECK (col
  BETWEEN 0 AND 100)` pattern, grouped per STAGES.md §14.5:
  * Temperament: risk_taking, killer_instinct, grit, discipline,
    patience
  * Career: ambition, loyalty, charisma, attention_seeking,
    coachability, professionalism
  * Resilience: ego, resilience, sportsmanship, travel_comfort
  * Dynamic: focus, fatigue_tolerance
- 14 new columns on `fighters` (Task ID 14.6): height_cm, reach_cm,
  stance (CHECK IN orthodox/southpaw/switch), handedness (CHECK IN
  right/left/ambidextrous), injury_proneness, weight_cut_difficulty,
  consistency, clutch_factor, marketability, fan_friendliness (all
  CHECK 0-100 DEFAULT 50), promo_boost (CHECK -100..100 DEFAULT 0),
  preferred_gameplans (TEXT, JSON array, nullable), bad_matchup_tags
  (TEXT, JSON array, nullable), is_deceased (CHECK IN 0,1 DEFAULT 0).
  Closes SCHEMA_DRIFT_AUDIT §Z.3.
- 6 new columns on `promotions` (Task ID 14.6): brand_tone,
  starting_budget, broadcast_tier, ownership_type, ai_aggression
  (CHECK 0-100 DEFAULT 50), ai_spending_style. Closes
  SCHEMA_DRIFT_AUDIT §Z.4 — unblocks Task 25 (rival promotion AI).
  Seed values: AC gets broadcast_tier='regional_tv',
  starting_budget=500000, ai_aggression=30 (player-controlled, low
  AI); RFL gets broadcast_tier='local_stream', starting_budget=200000,
  ai_aggression=60 (more aggressive AI for the future rival).
- 8 new columns on `gyms` (Task ID 14.6): reputation, membership_cost,
  facility_quality, medical_support, sparring_depth, development_focus
  (all CHECK 0-100 DEFAULT 50 except membership_cost REAL DEFAULT 0),
  culture_tone (TEXT DEFAULT 'balanced'), weight_cut_support (CHECK
  0-100 DEFAULT 50). Unblocks Task 16 (training camps) and Task 17
  (weight cuts). Seed values for both Ironhouse Gym and Steelcrest
  Gym: facility_quality=60, medical_support=50, sparring_depth=55,
  development_focus=60 (per the brief).
- `attribute_bias` TEXT column on `style_archetypes` (Task ID 14.5)
  holding a JSON dict mapping attribute names to +/- integer bias
  values. Nullable (NULL = no bias, equivalent to {}). Consumed by
  `fighter_gen.generate_attribute_block(archetype_id, conn)`.
- `trait_bias` TEXT column on `personality_archetypes` (Task ID 14.5)
  — symmetric to `style_archetypes.attribute_bias` but for the
  personality block. Consumed by
  `fighter_gen.generate_personality_block(archetype_id, conn)`.
- 7 style archetypes seeded with bias JSON (Task ID 14.5): Balanced
  (existing, bias added), Striker, Grappler, Wrestler, Brawler,
  Counter-Striker, Submission Specialist (6 new). Bias values per
  STAGES.md §14.5 — e.g. Brawler: {"punch_power": 20, "chin": 15,
  "durability": 10, "footwork": -15, "fight_iq": -10, "cardio": -5}.
  These biases give regen prospects a style identity from day one —
  a Brawler replacement for a retiring Brawler feels like a Brawler,
  not a generic 50/50 prospect. The new acceptance test
  `test_fighter_attributes.py` case D verifies the bias system works
  by asserting that 100 Brawlers average higher on punch_power/chin
  and lower on footwork/fight_iq than 100 Counter-Strikers.
- 5 personality archetypes seeded with bias JSON (Task ID 14.5): Calm
  (existing, bias added), Aggressive, Methodical, Showman, Quiet
  Professional (4 new). Bias values per STAGES.md §14.5 — e.g.
  Aggressive: {"aggression": 20, "killer_instinct": 15, "patience":
  -15, "discipline": -5}.
- New module `src/fighter_gen.py` (Task ID 14.5) with three pure-ish
  generation functions used by both the seed backfill and
  `app.generate_fighter()`:
  * `generate_attribute_block(archetype_id=None, conn=None) -> dict` —
    generates a 25-key dict of attribute values via
    `clamp(50 + bias.get(col, 0) + random.randint(-8, 8), 0, 100)`.
    The +/-8 noise floor keeps fighters within an archetype distinct
    (no two Brawlers identical) while the bias gives the archetype
    its identity.
  * `generate_personality_block(archetype_id=None, conn=None) -> dict`
    — symmetric to generate_attribute_block but for the 20 personality
    fields.
  * `generate_physical_block() -> dict` — generates height_cm (normal
    distribution around 178, bounded to [165, 195]), reach_cm
    (height + random.randint(-5, 10)), stance (80/15/5
    orthodox/southpaw/switch), handedness (85/10/5
    right/left/ambidextrous).
- `scripts/test_fighter_attributes.py` — new acceptance test (Task ID
  14.5+14.6+14.7). 6 test cases (A-F) covering: schema (column counts
  + CHECK constraints + version + migration name), archetype seed
  (7 style + 5 personality with parseable bias JSON), fighter_gen
  function shapes (25/20/4 keys, values in [0,100], bias applied
  correctly), backfill (5 existing fighters with no NULLs, existing
  4+3 values PRESERVED), archetype bias statistical effect (100
  Brawlers vs 100 Counter-Strikers — brawler averages higher on
  punch_power/chin, lower on footwork/fight_iq, mean difference > 5
  points), and `current_date` quirk fix (tick advances by exactly 1
  day from the seeded date, not jumping to today's real date). Uses
  `build_db.CODE_SCHEMA_VERSION` dynamically per CONVENTIONS §10
  (does NOT hardcode '2.0.0').

### Changed
- `app.generate_fighter()` (Task 14 regen function) updated to use
  `fighter_gen.py` instead of INSERT with all-50 defaults (Task ID
  14.5). Regen prospects now arrive with archetype-biased attributes
  (25 columns), personality (20 columns), and physical stats
  (height/reach/stance/handedness). Previously: regen fighters were
  generic 50/50 stubs — visually identical, no style identity. Now: a
  Brawler replacement for a retiring Brawler actually hits hard and
  has a chin. This is the design-law fix: regen now serves the
  Discovery pillar (Fantasy 1: Talent Hunter) — players can spot
  "this kid hits hard" from day one. The 25 attribute columns and 20
  personality columns are INSERTed explicitly via dynamically-built
  SQL (from `fighter_gen.ATTRIBUTE_NAMES` / `PERSONALITY_NAMES`) so
  future column additions don't require touching this code.
  D4-update decision: the Task 14 worklog's D4 ("new fighter enters
  with default attrs all 50") is superseded by this change. The
  existing acceptance test `test_regen.py` case C (lines 556-580)
  asserts all-50 defaults — that assertion is now stale and flagged
  for supervisor fix per CONVENTIONS §11 (NOT modified by this task).
- `app.get_clock()` and `app.schedule_next_event()` updated to
  qualify `current_date` as `simulation_clock.current_date` (Task ID
  14.7). Closes the pre-existing SQLite quirk flagged in
  SCHEMA_DRIFT_AUDIT §Z.6 where bare `current_date` resolved to
  SQLite's built-in date FUNCTION (today's wall-clock date) instead
  of the simulation_clock.current_date COLUMN. This caused the sim
  clock to jump from the seeded 2026-07-20 to today+1 on the first
  tick after a fresh build. The fix was deferred through Tasks 12,
  13, and 14 (each flagged it as "out of scope"); the MAJOR bump in
  this task is the right place to land it. The existing
  `get_free_agents_for_display()` helper already qualified the
  column (added in Task 13) — this change brings the rest of the
  codebase in line with that pattern.
- `tick_processor.run_tick()` updated to qualify `current_date` (and
  the other clock columns, for consistency) as
  `simulation_clock.current_date` etc. (Task ID 14.7). Same fix as
  `app.get_clock()` above. Closes the second occurrence of the
  §Z.6 quirk. After this fix, `python3 src/tick_processor.py` on a
  freshly-built DB advances the clock from 2026-07-20 to 2026-07-21
  (exactly 1 day), not from 2026-07-20 to today+1.
- `seed_data.py` `_seed_archetypes()` helper added (Task ID 14.5) —
  seeds 7 style + 5 personality archetypes with bias JSON. Uses
  INSERT OR IGNORE + UPDATE so existing archetype rows (Balanced,
  Calm) are preserved at their original autoincrement IDs (1 and 1)
  — important because the 5 existing seeded fighters reference
  style_id=1 and pers_id=1.
- `seed_data.py` `_backfill_fighter_v2()` helper added (Task ID 14.5)
  — backfills a single existing fighter with the 21 new attribute
  columns, 17 new personality columns, and 4 physical columns, while
  PRESERVING the existing 4 attribute values (punch_power, cardio,
  fight_iq, chin) and 3 personality values (aggression, composure,
  morale). The existing values are read from the DB and override the
  generated dict's keys before UPDATE, so the backfill is correct
  even if a future change seeds non-default values for the existing
  4. The meta columns on the fighters table (injury_proneness,
  marketability, etc.) are left at their schema DEFAULT 50/0/NULL
  per the brief.
- `seed_data.py` promotions seeder updated (Task ID 14.6) to set
  `starting_budget`, `broadcast_tier`, and `ai_aggression` for both
  promotions per the brief: AC gets regional_tv/500000/30, RFL gets
  local_stream/200000/60. The other 3 new promotion columns
  (brand_tone, ownership_type, ai_spending_style) use schema
  defaults.
- `seed_data.py` gyms seeder updated (Task ID 14.6) to set
  `facility_quality=60`, `medical_support=50`, `sparring_depth=55`,
  `development_focus=60` for both Ironhouse Gym and Steelcrest Gym.
  The other 4 new gym columns (reputation, membership_cost,
  culture_tone, weight_cut_support) use schema defaults.
- `seed_data.py` seed summary print expanded (Task ID 14.5+14.6) to
  include the new archetype count (7 style + 5 personality), the
  promotion AI-tuning values, the gym facility values, and the
  backfill summary.
- `build_db.py` `CODE_SCHEMA_VERSION` bumped 1.9.0 → 2.0.0 (MAJOR —
  first major version, Task ID 14.5+14.6+14.7). Per CONVENTIONS §1.1,
  MAJOR bumps are for "removing a table, renaming a column, breaking
  change to existing data shape." This bump is unusual: no tables are
  removed, no columns renamed, no data shape broken. The MAJOR bump
  is for the depth-of-sim significance (4 attrs → 25 attrs is a
  paradigm shift, not an incremental step) and to mark the
  transition from thin skeleton to real simulation. Documented in
  the worklog D1 decision.
- `build_db.py` migration name updated from
  `v1_9_0_add_regen` → `v2_0_0_fighter_schema_expansion` (Task ID
  14.5+14.6+14.7) to reflect the combined nature of this task.

### Fixed
- Pre-existing `current_date` SQLite quirk (SCHEMA_DRIFT_AUDIT §Z.6,
  flagged in Tasks 12, 13, 14 worklogs as D5 / "out of scope").
  Bare `current_date` in SELECT statements resolved to SQLite's
  built-in date FUNCTION (today's wall-clock date) instead of the
  `simulation_clock.current_date` COLUMN, causing the sim clock to
  jump unpredictably on the first tick after a fresh build. Fixed
  by qualifying the column as `simulation_clock.current_date` in
  `app.get_clock()`, `app.schedule_next_event()`, and
  `tick_processor.run_tick()`. The `get_free_agents_for_display()`
  helper was already qualified (Task 13). All existing tests passed
  despite the quirk because none asserted specific clock values
  (they used `tick_counter` or explicit `current_date` parameter
  passing instead). Verified by the new acceptance test
  `test_fighter_attributes.py` case F: tick advances by exactly 1
  day from the seeded 2026-07-20 to 2026-07-21, NOT to today+1.

## [1.9.0] - 2026-07-21

### Added
- Name pools + regen lineage + memory links tables (Task ID 14).
  Three new tables ship in this task:
  * `name_pools` — first_male / first_female / last / nickname
    entries drawn from by `generate_fighter()` when a fighter retires.
    UNIQUE (name_type, name_value) so re-seeding is idempotent.
  * `regen_lineage` — one row per (retiring_fighter_id,
    replacement_fighter_id) pair, recording the style_dna_archetype_id
    inherited and the regen_date. Foundation for future memory-
    resurfacing features (style echoes, gym heirs, regional rivals,
    successors) in Stage 3+. UNIQUE (retiring_fighter_id,
    replacement_fighter_id).
  * `fighter_memory_links` — created but NOT populated in this task.
    The table exists so future memory-resurfacing tasks can write to
    it without needing a schema change. CHECK constraint on link_type
    (style_echo / gym_heir / regional_rival / successor) and
    link_strength (0-100, default 50). UNIQUE (fighter_id,
    linked_fighter_id, link_type).
  Note on `used_names`: the spec calls for a separate `used_names`
  table to prevent duplicate fighter names. We chose to check
  uniqueness against the existing `fighters` table (first_name +
  last_name combination) in `generate_fighter()` instead. This is
  simpler, avoids a redundant table, and stays correct when fighters
  are deleted (their names become available again). Documented in
  the `name_pools` schema comment in `build_db.py`.
- `generate_fighter(conn, style_dna_source_id=None, current_date=None,
  gender='male')` module-scope function in `app.py` (Task ID 14) —
  the core regen function. Called by `tick_processor._check_retirements`
  for each retiring fighter (see "Changed" below). Generates a new
  fighter from the name pools with the same
  `fight_style_archetype_id` (style DNA) as the retiring fighter. The
  new fighter: has a unique (first, last) name checked against the
  `fighters` table; has a nickname (50% chance); has a random DOB
  making them 18-26 years old; has default attributes (all 50),
  personality (all 50), career (0-0-0, career_health=100); enters as
  a FREE AGENT (`current_promotion_id=NULL`, `is_active=1`,
  `is_retired=0`); does NOT get a rankings row at generation time
  (the `rankings` table requires a `promotion_id`; the row is created
  defensively by `_update_rankings_after_resolution` when the fighter
  is signed and fights their first bout — see decision D2 in the
  function's section comment); does NOT get a contract (the player
  or AI signs them via Task 13's `sign_free_agent`); triggers a
  "new prospect" news item (`topic='prospect'`,
  `published_at=current_date`) so the player sees them arrive in the
  Free Agents tab. Returns the new `fighter_id` (int) on success,
  `None` on failure (name pool exhausted — all (first, last)
  combinations already used). Style DNA inheritance: if
  `style_dna_source_id` is provided, the new fighter inherits that
  fighter's `fight_style_archetype_id`; if None, picks a random
  archetype. The `gender` parameter ('male' or 'female', default
  'male') determines which first-name pool to draw from. Design
  decisions D1-D5 documented in the function's section comment
  (D1: no used_names table; D2: no rankings row at gen time;
  D3: no memory resurfacing yet; D4: default attrs/personality/career;
  D5: DOB computed by subtracting age_years * 365 days + random
  offset within the year — approximate, doesn't account for leap
  years, but close enough for sim purposes).
- `_seed_name_pools(conn)` helper in `seed_data.py` (Task ID 14) —
  seeds the `name_pools` table with 25 male first names (Aaron..Zane),
  25 female first names (Aria..Zoe), 26 last names (Adams..Zhang), and
  20 nicknames (The Hammer..Vortex). Total: 96 name pool entries.
  Uses `INSERT OR IGNORE` so re-seeding is idempotent. Module-level
  constants `MALE_FIRST_COUNT=25`, `FEMALE_FIRST_COUNT=25`,
  `LAST_COUNT=26`, `NICKNAME_COUNT=20` expose the counts to the
  seed summary print without duplicating the lists.
- Regen on retirement: retiring fighters generate a replacement
  (Task ID 14). `tick_processor._check_retirements()` now calls
  `generate_fighter(conn, style_dna_source_id=fighter_id,
  current_date=current_date)` for each retiring fighter, after the
  retirement UPDATE + title vacation + retirement news item. If the
  replacement is successfully generated, a `regen_lineage` row is
  inserted linking the retiring fighter to the replacement (with the
  retiring fighter's `fight_style_archetype_id` as
  `style_dna_archetype_id`). The replacement enters as a free agent —
  they appear in Task 13's Free Agents tab and can be signed by any
  promotion. The replacement is logged via a one-line print in
  `run_tick` ("Generated N replacement fighter(s) on YYYY-MM-DD: [...]"),
  mirroring the retirement log pattern. The retirement path now
  fetches `f.fight_style_archetype_id` in the SELECT so it can pass
  it to the regen_lineage INSERT (it was previously not fetched).
  No new commit — the existing `conn.commit()` in `run_tick` covers
  the regen side effects (fighter INSERT, attributes/personality/
  career INSERTs, news_items INSERT, regen_lineage INSERT).
- New prospect news items (Task ID 14) — written by
  `generate_fighter()` when a replacement fighter is generated.
  Headline: `"New prospect <first> <last>[ "<nickname>"] emerges on
  the scene"`. Body: a brief announcement that the new talent has
  arrived as a free agent. `topic='prospect'` (so the future news
  engine in Task 23 can filter prospect-arrival news), `fighter_id`
  set, `published_at=current_date` (the sim date the regen happened
  on, NOT `CURRENT_TIMESTAMP` which is wall-clock time). Falls back
  to today's date string if `current_date` is None (e.g., when
  `generate_fighter` is called directly without a date — see case K
  of `test_regen.py`).
- Acceptance test `scripts/test_regen.py` (Task ID 14) — tests
  schema (version, migration name prefix, 3 new tables exist, total
  table count == 37, name_pools CHECK constraint, regen_lineage
  UNIQUE constraint, fighter_memory_links CHECK constraint),
  name pool seed (all 4 name_types populated, >= 20 per type, total
  == 96), `generate_fighter()` basic (returns valid fighter_id,
  free agent status, unique name, style DNA inherited, default
  attrs/personality/career, age 18-26, prospect news item written),
  `generate_fighter()` without style DNA source (random archetype
  picked), name uniqueness (10 calls produce 10 unique names, no
  collision with seeded fighters), name pool exhaustion (shrunk pool
  → second call returns None with warning), regen on retirement
  (5 → 6 fighters, regen_lineage row created, style DNA inherited,
  free agent, appears in `get_free_agents_for_display`, prospect
  news), multiple regens on one tick (3 retirements → 8 fighters,
  3 regen_lineage rows, 3 prospect news), female gender (gender
  == 'female', first name from first_female pool), regression
  (Tasks 3-13 side effects still work — fight_history +2, title
  transferred, event completed, new event scheduled, no retirements
  on a normal tick, no regens on contract expiry — regen = retirement
  only), and `generate_fighter()` callable directly (no args beyond
  conn, returns valid fighter_id, free agent). 11 cases A-K.
  Uses `build_db.CODE_SCHEMA_VERSION` dynamically (no hardcoded
  version string — same pattern as `test_retirement.py`,
  `test_free_agency.py`, `test_rankings.py`, `test_contracts.py`,
  `test_titles.py`, `test_schema_versioning.py`,
  `test_fight_history.py`). Uses `random.seed(42)` for reproducibility
  where relevant. Prints PASS/FAIL summary. Exit 0 = all PASS,
  1 = any FAIL.
- Contract expiry logic (Task ID 13) — when a fighter's contract
  `end_date` passes the current sim date, the contract transitions to
  `'expired'` and the fighter becomes a free agent
  (`current_promotion_id = NULL`). This is the talent-circulation
  foundation for Task 25 (rival promotion AI — RFL signs free agents),
  Task 14 (regen — new generated fighters enter as free agents), and
  the "playable forever" loop (without free agency, the roster is
  static). Uses the existing `contracts`, `fighter_contracts`, and
  `fighters` tables — no new tables, no new columns. The version bump
  (1.7.0 -> 1.8.0, MINOR) documents that the free-agency behavior was
  added in this version; per CONVENTIONS.md the MINOR/MAJOR/PATCH
  categories don't cleanly fit a "significant new behavior, no schema
  change" task, so MINOR was chosen as the closest match (see worklog
  decision D2 for the rationale).
- `_check_contract_expiry(conn, current_date)` function in
  `tick_processor.py` (Task ID 13) — runs on every tick (called from
  `run_tick()` AFTER `_check_retirements()` so a retired-and-contract-
  expiring fighter is handled correctly). For each contract with
  `status='active'` AND `end_date < current_date`: sets
  `contracts.status='expired'`; for fighter contracts whose fighter is
  NOT already retired, sets the fighter's `current_promotion_id=NULL`
  (free agent) and `is_active=1`, writes a free-agency news item
  (`topic='signing'`, `fighter_id` set, `published_at=current_date`).
  Staff/broadcast contracts also expire but don't set
  `current_promotion_id` (staff don't have that column) and don't get
  a news item. The `is_retired` check is critical: a retired fighter
  whose contract also expired on this tick was retired FIRST by
  `_check_retirements` (which runs before this function in `run_tick`);
  setting `current_promotion_id=NULL` on a retired fighter would be
  misleading (they're not a free agent, they're retired). Returns the
  list of `(contract_id, fighter_id_or_None)` tuples that expired
  (`fighter_id` is `None` for staff/broadcast contracts and for fighter
  contracts whose fighter is already retired). The function does NOT
  commit — the caller (`run_tick`) commits.
- `sign_free_agent(conn, fighter_id, promotion_id, start_date,
  salary=50000.0)` module-scope function in `app.py` (Task ID 13) —
  signs a free agent to a promotion with a new 12-month exclusive
  contract. Verifies the fighter is currently a free agent
  (`current_promotion_id IS NULL`) and active (`is_active=1`,
  `is_retired=0`); refuses retired fighters ("they can't sign") and
  already-signed fighters ("they're not free agents"). Creates one
  row in `contracts` (`contract_target_type='fighter'`,
  `status='active'`, `exclusive_flag=1`, `start_date=start_date`,
  `end_date=start_date+365 days`, `salary=salary`) and one in
  `fighter_contracts` (`contract_type='standard'`), sets the fighter's
  `current_promotion_id`, writes a signing news item
  (`"<fighter> signs with <promotion>"`, `topic='signing'`,
  `fighter_id` set, `promotion_id` set, `published_at=start_date`),
  and returns the new `contract_id` (None on failure). No negotiation
  flow yet — that's a future task; the player signs at the default
  salary.
- `get_free_agents_for_display(conn)` helper in `app.py` (Task ID 13)
  — returns a list of `(fighter_id, fighter_name, weight_class_name,
  record_str, age_int)` tuples for every fighter who is currently a
  free agent (`current_promotion_id IS NULL` AND `is_active=1` AND
  `is_retired=0`). The `fighter_id` is included (as the first element)
  so the Treeview can use it as the item iid, which lets the Sign
  button read the fighter_id directly from `tree.selection()[0]`
  instead of doing a fragile name lookup. The age is computed from
  `date_of_birth` and the current sim date — read using the QUALIFIED
  column reference `simulation_clock.current_date` (not bare
  `current_date`) to avoid the pre-existing D5 SQLite quirk where bare
  `current_date` resolves to the built-in date function. The
  pre-existing `get_clock()` function (line 17) is left unchanged —
  fixing it is out of scope for this task and is flagged for a future
  housekeeping task.
- Free Agents tab in the UI (Task ID 13) — fourth tab in the right-
  pane `ttk.Notebook` (after "News & Commentary", "Contracts",
  "Rankings"). Shows a read-only Treeview of all free agents with
  columns: name, weight class, record, age. The Treeview item iid is
  the fighter_id (so the Sign button can read it directly from the
  selection). A "Sign Selected" button above the Treeview calls
  `on_sign_free_agent()` which calls `sign_free_agent()` with the
  player's current promotion filter (or the first promotion if "All
  Promotions" is selected). The Free Agents tab does NOT respect the
  promotion filter — free agents are not bound to any promotion, so
  they're available to sign with ANY promotion. The UI always shows
  all free agents regardless of the `current_promotion_filter`
  dropdown. This is intentional and documented (case I of
  `test_free_agency.py`).
- Free agency news items (Task ID 13) — written by
  `_check_contract_expiry` when a fighter's contract expires. Headline:
  `"<fighter> becomes a free agent"`. Body: a brief announcement that
  the fighter's contract has expired and they are available to sign
  with any promotion. `topic='signing'` (so future UI filters can
  group signing-related news together — both free-agency + actual
  signings), `fighter_id` set, `published_at=current_date` (the sim
  date the expiry happened on, NOT `CURRENT_TIMESTAMP` which is wall-
  clock time).
- Signing news items (Task ID 13) — written by `sign_free_agent` when
  a free agent is signed to a promotion. Headline: `"<fighter> signs
  with <promotion>"`. Body: a brief announcement. `topic='signing'`,
  `fighter_id` set, `promotion_id` set, `published_at=start_date`.
  Sentiment is `'positive'` (signings are good news for the signing
  promotion).
- Acceptance test `scripts/test_free_agency.py` (Task ID 13) — tests
  schema (version, migration name prefix, no new tables, seeded
  contracts all `'active'` with `end_date='2027-07-20'`), contract
  expiry on tick (one fighter contract expires -> status='expired',
  fighter becomes free agent, free-agency news item written), multiple
  contracts expire on one tick (all 5 fighter contracts -> all 5
  expired, all 5 free agents, 5 news items), staff contract expiry
  (Nina Cross's contract expires -> status='expired', NO fighter
  update, NO free-agency news item), `sign_free_agent()` function
  (signs free agent to RFL -> new contract with correct fields, new
  fighter_contracts row, fighter's current_promotion_id updated,
  signing news item written), `sign_free_agent()` rejects non-free-
  agents (already-signed fighter -> returns None, no changes),
  `sign_free_agent()` rejects retired fighters (retired fighter ->
  returns None, no new contract), `get_free_agents_for_display()`
  helper (empty at seed, 1 row after setting one fighter's
  current_promotion_id=NULL, 2 rows after setting a second,
  inactive/retired fighters excluded), Free Agents tab does NOT
  respect the promotion filter (documented; verified via the helper
  signature), retired fighter's contract expiry doesn't make them a
  free agent (the `is_retired` check in `_check_contract_expiry`
  skips the `current_promotion_id=NULL` update), regression (Tasks
  3-12 side effects still work, no spurious contract expirations or
  retirements on a normal tick), and UI smoke (optional, SKIPs in
  headless). 12 cases A-L. Uses `build_db.CODE_SCHEMA_VERSION`
  dynamically (no hardcoded version string — same pattern as
  `test_retirement.py`, `test_rankings.py`, `test_contracts.py`,
  `test_titles.py`, `test_schema_versioning.py`,
  `test_fight_history.py`). Uses `random.seed(42)` for
  reproducibility where relevant. Prints PASS/FAIL summary. Exit 0 =
  all PASS, 1 = any FAIL.
- `is_retired` column on `fighters` table (Task ID 12) — INTEGER NOT
  NULL DEFAULT 0 CHECK (is_retired IN (0,1)). Distinguishes "retired"
  (is_retired=1) from "inactive for another reason" (injury in Task
  15, suspension in a future task). When a fighter retires, both
  is_active and is_retired are set: is_active=0 (excludes them from
  _pick_matchup's `is_active = 1` filter, so they won't be picked for
  new matchups), is_retired=1 (marks the reason). The column lives
  right after `is_active` in the table definition. Foundation for
  Task 14 (regen — retiring fighters trigger replacement fighter
  generation) and the "playable forever" loop (without retirement,
  the roster never turns over).
- `_check_retirements(conn, current_date)` function in
  `tick_processor.py` (Task ID 12) — runs on every tick (called from
  `run_tick()` after the clock advance). Retirement rules: a fighter
  is eligible if (age >= 45) OR (age >= 40 AND career_health < 60).
  Age 45 is mandatory retirement (no one fights past 45 in this sim,
  regardless of health). Age 40-44 is conditional on declining health
  (a healthy 40-year-old can keep fighting; a worn-down one should
  hang it up). The boundary is `< 60` (career_health=60 does NOT
  retire). For each eligible fighter: sets is_active=0, is_retired=1,
  calls `_vacate_title_on_retirement`, writes a retirement news item
  (topic='retirement', fighter_id set, published_at=current_date).
  Returns the list of retired fighter_ids (empty list if none). The
  function does NOT commit — the caller (run_tick) commits.
- `_vacate_title_on_retirement(conn, fighter_id, current_date)`
  helper in `app.py` (Task ID 12) — vacates any title held by a
  retiring fighter. Sets current_champion_fighter_id=NULL,
  champion_since_date=NULL, is_vacant=1. `title_reigns_count` and
  `title_defenses_count` are PRESERVED (historical counters that
  survive across reigns for legacy/Hall-of-Fame work). Writes a
  vacation news item per title (topic='retirement', promotion_id
  set, fighter_id set, published_at=current_date). Returns the list
  of vacated title_ids (empty list if the fighter held no titles).
  Lives in app.py next to `_resolve_title_after_fight` so all title-
  mutation logic is in one place. tick_processor imports it via
  `from app import _vacate_title_on_retirement` (no circular import
  — app.py does not import tick_processor).
- Retirement news items (Task ID 12) — written by
  `_check_retirements` when a fighter retires. Headline:
  "<fighter> announces retirement at age <age>". Body: a brief
  retirement announcement. topic='retirement', fighter_id set,
  published_at=current_date (the sim date the retirement happened
  on, NOT CURRENT_TIMESTAMP which is wall-clock time).
- Title vacation news items (Task ID 12) — written by
  `_vacate_title_on_retirement` when a retiring fighter was a
  champion. Headline: "<fighter> vacates the <promotion>
  <weight_class> title". Body: announces the retirement + vacation
  + that a new champion will be crowned at the next title fight.
  topic='retirement', fighter_id set, promotion_id set,
  published_at=current_date.
- Acceptance test `scripts/test_retirement.py` (Task ID 12) — tests
  schema (is_retired column, DEFAULT 0, CHECK IN (0,1), all seeded
  fighters is_retired=0), age computation (age 46 retires, age 36
  doesn't), age 40-44 with declining career_health (age 41 +
  career_health=50 retires, age 41 + career_health=70 doesn't),
  career_health=60 boundary (does NOT retire), career_health=59
  boundary (retires), mandatory age 45 (retires even with
  career_health=100), title vacation on champion retirement
  (is_vacant=1, current_champion_fighter_id=NULL, reigns/defenses
  preserved), retirement news item (topic='retirement', headline
  contains name + 'retirement', fighter_id matches), title vacation
  news item (headline contains 'vacates' + title name), retired
  fighter excluded from new matchups (schedule_next_event returns
  None when only 1 active fighter remains), multiple retirements on
  one tick, no retirements when none eligible, regression
  (fight_history + rankings + titles + event lifecycle + scheduler
  still work), and `_check_retirements` callable directly with no
  eligible fighters. 13 cases A-M. Uses
  build_db.CODE_SCHEMA_VERSION dynamically (no hardcoded version
  string — same pattern as test_rankings.py, test_contracts.py,
  test_titles.py). Uses random.seed(42) for reproducibility where
  relevant. Prints PASS/FAIL summary. Exit 0 = all PASS, 1 = any
  FAIL.
- `titles` table (Task ID 11) — one row per belt per promotion per
  weight class. Tracks the current champion, when they won it
  (`champion_since_date`), how many reigns they've had
  (`title_reigns_count`), how many defenses they've made
  (`title_defenses_count`), and whether the title is vacant
  (`is_vacant`). UNIQUE constraint on (promotion_id, weight_class_id)
  enforces one belt per weight class per promotion. CHECK constraints
  enforce `is_vacant IN (0,1)`, `title_reigns_count >= 0`,
  `title_defenses_count >= 0`. `current_champion_fighter_id` is
  nullable (NULL = vacant). Foundation for Task 8's
  `schedule_next_event()` (future: champion vs #1 contender), Task 14
  (regen — retiring champions vacate the title), and Task 22
  (rivalries — title fight rivalries are the most heated).
- `_resolve_title_after_fight()` private helper in `app.py`
  (Task ID 11) — transfers or vacates the title after a title fight
  resolution. Called unconditionally by `resolve_next_fight()` but
  returns None early if the fight is not a title fight (defensive —
  the caller doesn't need to check `bout_type`). Handles all five
  cases: vacant + non-draw (winner becomes champion), vacant + draw
  (stays vacant), held + champion wins (defense incremented), held +
  contender wins (title changes hands, defenses reset), held + draw
  (champion retains, no defense counted). Returns the `title_id` if a
  title change occurred, else None. The caller uses the non-None
  return to enrich the news/commentary with a "(TITLE CHANGE!)"
  suffix.
- `_seed_vacant_title()` helper in `seed_data.py` (Task ID 11) —
  creates a vacant title for a (promotion, weight_class) pair. Uses
  `INSERT OR IGNORE` so the seed is idempotent. Called from the seed
  for both AC Lightweight and RFL Lightweight.
- Acceptance test `scripts/test_titles.py` (Task ID 11) — tests
  schema (CHECK + UNIQUE constraints), seed (2 vacant titles, seeded
  main event is a title_fight), vacant-title + non-draw transfer
  (winner becomes champion, reigns=1, defenses=0, fight_history
  title_at_stake=1), held-title + champion-wins defense
  (defenses=1, reigns still 1), held-title + contender-wins upset
  (title changes hands, reigns=2, defenses=0, champion_since_date
  updated), held-title + draw (champion retains, no defense),
  vacant-title + draw (stays vacant), non-title fight (no title
  change, fight_history title_at_stake=0), `_resolve_title_after_fight()`
  defensive cases (non-existent fight_id, non-title bout_type,
  non-existent promotion_id), and regression (fight_history +
  rankings + event lifecycle + event scheduler + contracts all still
  work together; AC Lightweight title has a champion after resolving
  the seeded title fight). UI smoke test SKIPs cleanly in headless.
- `rankings` table (Task ID 10) — one row per fighter per weight class
  per promotion, with an ELO-style rating (default 1000.0), cumulative
  fights_count / wins / losses / draws, and last_fight_date. UNIQUE
  constraint on (fighter_id, weight_class_id, promotion_id) ensures
  one row per fighter per WC per promotion. CHECK constraints enforce
  non-negative rating / fights_count / wins / losses / draws.
  Foundation for Task ID 11 (titles — champion vs #1 contender),
  Task ID 14 (regen — new fighters enter at the bottom at 1000.0),
  and Task ID 22 (rivalries — ranking proximity boosts heat).
- `_update_rankings_after_resolution()` private helper in `app.py`
  (Task ID 10) — updates both fighters' ELO ratings after a fight
  resolution. K-factor fixed at 32.0 (not dependent on fights_count).
  Zero-sum: the winner's gain is exactly the loser's loss (within
  floating-point precision). Draw handling: both fighters get
  score=0.5, which produces zero rating change when both start at
  the same rating. Defensive: creates the rankings row on the fly if
  the seed missed it, and is a no-op if either fighter doesn't exist.
- `get_rankings_for_display(conn, promotion_id, weight_class_id=None,
  limit=10)` module-scope helper in `app.py` (Task ID 10) — extracted
  for testability, same pattern as `get_fighters_for_display()` from
  Task 6 and `get_contracts_for_display()` from Task 9. Returns a
  list of 7-tuples (rank, fighter_name, weight_class_name,
  rating_rounded_1dp, fights_count, 'W-L-D' string,
  last_fight_date_or_'N/A'), ordered by rating DESC, fights_count DESC.
  Handles invalid promotion_id (returns empty list, no crash).
- Rankings tab in the UI (Task ID 10) — third tab in the right-pane
  ttk.Notebook (after "News & Commentary" and "Contracts"). Shows
  the top 10 fighters by ELO rating for the selected promotion. When
  the promotion filter is "All Promotions", falls back to the first
  promotion's rankings (cross-promotion combined rankings are not
  meaningful under per-promotion ELO). Respects the promotion filter
  from Task 6.
- `_seed_initial_ranking()` helper in `seed_data.py` (Task ID 10) —
  creates an initial rankings row at rating=1000.0 for each fighter.
  Uses INSERT OR IGNORE so the seed is idempotent. Called from both
  fighter creation loops (AC and RFL) after the contract INSERT.
- Acceptance test `scripts/test_rankings.py` (Task ID 10) — tests
  schema (CHECK + UNIQUE constraints), seed (5 rows at 1000.0 with
  correct defaults), ELO update on fight resolution (zero-sum,
  correct direction, fights_count, last_fight_date), ELO upset math
  (underdog gain >= 10x favorite gain), draw handling (zero rating
  change), `get_rankings_for_display()` helper (7-tuple shape,
  1-indexed rank, weight_class filter, invalid promotion, limit),
  UI smoke test (skips in headless), and regression (fight_history +
  event lifecycle + event scheduler + contracts + rankings all still
  work together).
- Contracts group (Task ID 9) — 4 new tables: `contracts` (polymorphic
  base with contract_target_type CHECK constraint), `fighter_contracts`,
  `staff_contracts`, `broadcast_contracts` (subtype tables with UNIQUE
  contract_id FKs). Each fighter is now tied to their promotion via a
  real contract row with start_date, end_date, salary, exclusive_flag,
  and status — not just a `current_promotion_id` FK. Foundation for
  Task 13 (free agency + signings) and Task 25 (rival promotion AI
  poaching).
- `_seed_default_fighter_contract()` and `_seed_default_staff_contract()`
  helpers in `seed_data.py` (Task ID 9) — create a default 12-month
  exclusive contract for each fighter and staff member. Salary
  defaults to 50000.0; contract_type defaults to 'standard'.
- Contracts tab in the UI (Task ID 9) — adds a ttk.Notebook to the
  right pane with two tabs: "News & Commentary" (existing widgets
  moved) and "Contracts" (new Treeview showing contractor name, type,
  start/end dates, salary, exclusive flag, status). Respects the
  promotion filter from Task 6.
- `get_contracts_for_display(conn, promotion_id=None)` helper in
  `app.py` (Task ID 9) — extracted for testability, same pattern as
  `get_fighters_for_display()` from Task 6. Joins contracts to
  fighter_contracts/fighters and staff_contracts/broadcast_contracts/
  staff via LEFT JOINs with COALESCE for the contractor name.
- Acceptance test `scripts/test_contracts.py` (Task ID 9) — tests
  schema (CHECK constraints), seed (5 fighter + 1 staff contract with
  correct defaults), helper (filter by promotion, invalid promotion),
  UI smoke test (skips in headless), and regression (fight_history +
  event lifecycle + event scheduler still work).
- Repeatable event generator (Task ID 8) — `resolve_next_fight()`
  now auto-schedules a new event ~4 weeks out when an event just
  transitions to 'completed'. The new event reuses the same promotion,
  venue, market, and weight class as the just-completed event, with
  at least 1 fight between 2 randomly-picked active fighters from the
  promotion's roster. This is the last task in Stage 1 close-out —
  after it, the skeleton actually simulates end-to-end (real resolver
  + event lifecycle + repeatable events) and we can move to Stage 2
  (career systems).
- `schedule_next_event(conn, promotion_id, from_event_date=None,
  weeks_out=4)` function in `app.py` (Task ID 8) — module-scope,
  callable directly for testing or for "schedule now" UI actions.
  Returns the new event_id on success, or None with a printed warning
  if scheduling fails (e.g., not enough available fighters).
- `_pick_matchup(conn, promotion_id, weight_class_id,
  exclude_fighter_ids=())` private helper in `app.py` (Task ID 8) —
  picks 2 distinct active fighters from the promotion's roster in the
  given weight class, excluding any fighters in `exclude_fighter_ids`.
  Random selection for now; Task 10 will add ranking proximity, Task
  22 will add rivalry logic.
- Acceptance test `scripts/test_event_scheduler.py` (Task ID 8) —
  tests single-fight scheduling trigger, multi-fight trigger-only-on-
  last-fight, no-infinite-loop, 3-cycle loop continuation,
  not-enough-fighters edge case, direct callability, and fight_history
  regression.
- Event lifecycle transitions (Task ID 7) — `resolve_next_fight()` now
  updates the parent event's status: `scheduled` → `in_progress` when
  the first fight on the card resolves, `in_progress` → `completed`
  when the last unresolved fight resolves. An event with only 1 fight
  goes `scheduled` → `completed` in one step. Previously events stayed
  `'scheduled'` forever, which made the Events tree meaningless and
  blocked Task ID 8 (repeatable event generator).
- `_update_event_status_after_resolution(conn, event_id)` helper in
  `app.py` (Task ID 7) — counts unresolved fights remaining on the
  event and transitions the status accordingly. Defensive against
  already-completed events and non-existent event_ids.
- Acceptance test `scripts/test_event_lifecycle.py` (Task ID 7) —
  tests single-fight, multi-fight, already-completed, and non-existent
  event_id cases. Also verifies fight_history regression.
- Promotion filter dropdown in the UI (Task ID 6) — adds a "Filter:"
  combobox to the top bar that lets the player focus the Fighters
  tree on one promotion. Defaults to "All Promotions". Wires the
  multi-promotion data shape (landed in Task ID 2 as inert Rival
  Fight League seed) into the UI.
- `get_fighters_for_display(conn, promotion_filter)` helper in
  `app.py` (Task ID 6) — extracted from the inline query in
  `refresh_all()` so the filter logic is testable without a Tkinter
  display.
- Acceptance test `scripts/test_promotion_filter.py` (Task ID 6) —
  tests the filter helper with all promotions, single promotion,
  invalid promotion, and free agent (NULL promotion) cases. Optional
  UI smoke test that skips cleanly in headless environments.
- Schema version-check gate (Task ID 5) — `build_db.py` `main()` now
  checks `schema_meta.schema_version` before unlinking the DB file and
  refuses to run if the on-disk version is newer than the code's known
  version. Closes the schema-drift prevention loop set up in Task ID 2.
  See `docs/CONVENTIONS.md §1.4`.
- `_parse_version` and `_compare_versions` helpers in `build_db.py`
  (Task ID 5) — semver comparison so `"1.10.0"` correctly sorts after
  `"1.9.0"`.
- Acceptance test `scripts/test_schema_versioning.py` (Task ID 5) —
  tests fresh DB, same-version rebuild, upgrade, refuse-newer, no-
  schema_meta, corrupt DB, and unit tests for the version comparison
  helpers.
- `fight_history` table (Task ID 4) — separate per-fighter history table
  distinct from the mutable `fighter_career` counters. Populated by
  `resolve_next_fight()` with 2 rows per fight (one per fighter, from
  their perspective). Schema version bumped 1.2.1 → 1.3.0.
- Acceptance test `scripts/test_fight_history.py` (Task ID 4) — builds
  a fresh DB, resolves 5 fights, asserts `fight_history` row count and
  win/loss/draw correspondence with `fighter_career`.
- Real attribute-based fight resolver (Task ID 3) — replaces coin flip
  with probabilistic model reading `fighter_attributes` +
  `fighter_personality`.
- Acceptance test `scripts/test_fight_resolver.py` (Task ID 3) — builds
  a fresh DB, jacks one fighter to all-90 stats and another to all-30,
  resolves the fight 100 times, asserts the all-90 fighter wins >= 80
  and no single `result_type` accounts for > 60 / 100.
- `docs/MASTER_PLAN.md` — revised incremental build plan, gap
  analysis, and the rationale for killing the original big-bang
  v1.6 schema dump (Task ID 2).
- `docs/STAGES.md` — 5-stage, 30-task buildout with briefs and
  acceptance checklists for each task (Task ID 2).
- `docs/SCHEMA_DRIFT_AUDIT.md` — table-by-table comparison of the
  designed v1.6 spec vs. the built v1.2.0 vs. v1.2.1 (Task ID 2).
- `docs/CONVENTIONS.md` — schema versioning rules, CHANGELOG format,
  worklog format, smoke test protocol, cross-session handoff
  protocol (Task ID 2).
- `CHANGELOG.md` at repo root (Task ID 2).
- `schema_meta` table — restored from earlier draft, dropped during
  the error→shrink cycle. Records the current schema version
  (Task ID 2).
- `schema_migrations` table — restored from earlier draft. Records
  each migration applied (Task ID 2).
- Second promotion `Rival Fight League` seeded as inert data. No AI
  behaviour yet — wiring the data shape for multi-promotion now is
  cheap; retrofitting it later is expensive (per advisor's analysis)
  (Task ID 2).

### Changed
- Schema version bumped 1.8.0 → 1.9.0 (Task ID 14) — sixth MINOR bump
  in Stage 2 (after Task ID 9's 1.3.0 → 1.4.0, Task ID 10's 1.4.0 →
  1.5.0, Task ID 11's 1.5.0 → 1.6.0, Task ID 12's 1.6.0 → 1.7.0,
  Task ID 13's 1.7.0 → 1.8.0). Adds three new tables (`name_pools`,
  `regen_lineage`, `fighter_memory_links`) — the regen engine
  group. This closes the Stage 2 lifecycle loop: contracts → fights →
  rankings → titles → retirement → regen → free agency → signing →
  contracts (repeat forever). Total tables: 34 → 37.
- `build_db.py` migration name updated from `v1_8_0_add_free_agency`
  to `v1_9_0_add_regen` (Task ID 14). Note: build_db.py records only
  the latest migration name on each rebuild (it drops + recreates the
  DB file before recording), so the schema_migrations table contains
  only the current task's migration after a rebuild — this is a known
  quirk of the build_db.py design and is unchanged by Task 14.
- `_check_retirements()` now generates a replacement fighter for each
  retirement (Task ID 14). The retirement path now: (1) sets
  is_active=0/is_retired=1, (2) vacates any held titles via
  `_vacate_title_on_retirement`, (3) writes the retirement news item,
  (4) calls `generate_fighter(conn, style_dna_source_id=fighter_id,
  current_date=current_date)` to create a replacement with the same
  style DNA, (5) inserts a `regen_lineage` row linking the retiring
  fighter to the replacement. The replacement enters as a free agent
  (Task 13's Free Agents tab) — no signing logic here, the player or
  AI signs them. The retirement path now also fetches
  `f.fight_style_archetype_id` in the SELECT (was not fetched before)
  so it can be passed to the regen_lineage INSERT. The function does
  NOT commit — the existing `conn.commit()` in `run_tick` covers all
  the regen side effects. Prints a one-line log per tick if any
  replacements were generated ("Generated N replacement fighter(s) on
  YYYY-MM-DD: [...]"), mirroring the retirement log pattern.
- Seed now populates name pools (Task ID 14). `_seed_name_pools(conn)`
  inserts 25 male first names, 25 female first names, 26 last names,
  and 20 nicknames (96 total). Uses `INSERT OR IGNORE` so re-seeding
  is idempotent. Seed summary printout updated to include the name
  pool count: `Name pool: 96 names (25 male first, 25 female first,
  26 last, 20 nicknames)`.
- Schema version bumped 1.7.0 → 1.8.0 (Task ID 13) — fifth MINOR bump
  in Stage 2 (after Task ID 9's 1.3.0 → 1.4.0, Task ID 10's 1.4.0 →
  1.5.0, Task ID 11's 1.5.0 → 1.6.0, Task ID 12's 1.6.0 → 1.7.0).
  This task adds no new tables and no new columns — the schema itself
  is unchanged from 1.7.0. The MINOR bump documents that significant
  new gameplay behavior (contract expiry, free agency, click-to-sign)
  was added in this version. Per CONVENTIONS.md §1.1 the MINOR
  category is "Adding a new table or new columns to an existing
  table" and PATCH is "Restoring a dropped table, fixing a
  constraint, adding an index, no new gameplay tables" — neither
  category cleanly fits a "significant new behavior, no schema
  change" task. MINOR was chosen as the closest match (the supervisor
  can downgrade to PATCH if they disagree — see worklog decision D2).
- `build_db.py` migration name updated from `v1_7_0_add_retirement` to
  `v1_8_0_add_free_agency` (Task ID 13). Note: build_db.py records
  only the latest migration name on each rebuild (it drops + recreates
  the DB file before recording), so the schema_migrations table
  contains only the current task's migration after a rebuild — this
  is a known quirk of the build_db.py design and is unchanged by Task
  13.
- `tick_processor.run_tick()` now checks for contract expiry AFTER
  retirements (Task ID 13). The new order inside the for loop is:
  clock UPDATE → `_check_retirements(conn, new_date_str)` →
  `_check_contract_expiry(conn, new_date_str)` → `conn.commit()`. The
  expiry check uses the NEW sim date (so a contract that expires on
  this tick's new date is caught today, not yesterday). The expiry
  runs AFTER retirements so a retired-and-contract-expiring fighter
  is handled correctly: `_check_retirements` sets `is_retired=1`
  first, then `_check_contract_expiry` sees `is_retired=1` and skips
  the `current_promotion_id=NULL` update (they're retired, not a free
  agent). If any contracts expired, a one-line log message is printed
  ("Expired N contract(s) on YYYY-MM-DD: [...]"), mirroring the
  pattern in `_check_retirements`'s retirement log. The commit covers
  the clock UPDATE + retirement side effects + contract-expiry side
  effects.
- Schema version bumped 1.6.0 → 1.7.0 (Task ID 12) — fourth MINOR bump
  in Stage 2 (after Task ID 9's 1.3.0 → 1.4.0, Task ID 10's 1.4.0 →
  1.5.0, Task ID 11's 1.5.0 → 1.6.0). Adds the `is_retired` column to
  the existing `fighters` table (no new tables — the column addition
  is the whole schema change).
- `build_db.py` migration name updated from `v1_6_0_add_titles` to
  `v1_7_0_add_retirement` (Task ID 12). Note: build_db.py records only
  the latest migration name on each rebuild (it drops + recreates the
  DB file before recording), so the schema_migrations table contains
  only the current task's migration after a rebuild — this is a known
  quirk of the build_db.py design and is unchanged by Task 12.
- `tick_processor.run_tick()` now checks for retirements after
  advancing the clock (Task ID 12). The new order inside the for loop
  is: clock UPDATE → `_check_retirements(conn, new_date_str)` →
  conn.commit(). The retirement check uses the NEW sim date (so a
  fighter who turns 40 on this tick's new date becomes eligible today,
  not yesterday). If any fighters were retired, a one-line log message
  is printed ("Retired N fighter(s) on YYYY-MM-DD: [...]"), mirroring
  the pattern in `resolve_next_fight`'s auto-schedule warning. The
  commit covers both the clock UPDATE and any retirement side effects
  (fighters UPDATE, titles UPDATE, news_items INSERTs).
- `_pick_matchup()` in `app.py` already filters on `is_active = 1`
  (since Task ID 8), so retired fighters (is_active=0) are
  automatically excluded from new matchups (Task ID 12). No change to
  `_pick_matchup` itself was needed — the is_active=0 set by
  `_check_retirements` is what makes the exclusion work. The
  acceptance test (case I) verifies this end-to-end: when a fighter
  retires and `schedule_next_event` is called, it returns None if
  fewer than 2 active fighters remain in the promotion.
- Schema version bumped 1.5.0 → 1.6.0 (Task ID 11) — third MINOR bump
  in Stage 2 (after Task ID 9's 1.3.0 → 1.4.0 and Task ID 10's
  1.4.0 → 1.5.0). Adds the `titles` table.
- `build_db.py` migration name updated to `v1_6_0_add_titles`.
- `seed_data.py` now creates 2 vacant titles (AC Lightweight + RFL
  Lightweight) and marks the seeded main event as
  `bout_type='title_fight'` so the title-transfer logic is exercised
  end-to-end on the first resolve. Seed summary printout updated to
  include the titles count.
- `resolve_next_fight()` in `app.py` now resolves titles after the
  rankings ELO update (Task ID 10) and before `write_news` /
  `write_commentary` (so the news can mention the title change). The
  `write_news` and `write_commentary` calls were moved to AFTER the
  rankings + title resolution to make this ordering possible. News
  headline is enriched with a "(TITLE CHANGE!)" suffix and commentary
  with " Title changes hands!" when a title change occurred (new
  champion crowned from vacant OR title changed hands). Docstring's
  side-effects list updated to include the new titles line and
  reflect the `title_at_stake` population on the fight_history line.
- `fight_history` INSERTs in `resolve_next_fight()` now populate
  `title_at_stake` based on `fights.bout_type` (1 if 'title_fight',
  0 otherwise). Previously hardcoded to 0 (placeholder since Task ID 4).
- Schema version bumped 1.4.0 → 1.5.0 (Task ID 10) — second MINOR bump
  in Stage 2 (after Task ID 9's 1.3.0 → 1.4.0). Adds the `rankings`
  table.
- `build_db.py` migration name updated to `v1_5_0_add_rankings`.
- `seed_data.py` now creates an initial rankings row (rating=1000.0)
  for every fighter. Seed summary printout updated to include the
  rankings count.
- `resolve_next_fight()` in `app.py` now updates both fighters' ELO
  ratings after writing `fight_history` rows (Task ID 4) and before
  the event status transition (Task ID 7). The update is zero-sum.
  For draws, both fighters get score=0.5, which produces zero rating
  change when both start at the same rating. Docstring's side-effects
  list updated to include the new rankings line.
- Schema version bumped 1.3.0 → 1.4.0 (Task ID 9) — first MINOR bump
  since Task ID 4 (1.2.1 → 1.3.0). First schema change in Stage 2.
- `build_db.py` migration name updated to `v1_4_0_add_contracts`.
- `seed_data.py` now creates default contracts for every fighter and
  the seeded commentator. Seed summary printout updated to include
  contract count.
- Schema version: `1.2.1` → `1.3.0`. First MINOR bump since the
  versioning system was restored in Task ID 2. Adds the `fight_history`
  table (Task ID 4).
- DB filename: `mma_booking_sim_v1_2.db` → `cage_empire.db`. Applied
  across all four `src/*.py` files. Branding consistency; cleanest
  moment is during the schema-versioning restoration (Task ID 2).
- Schema version: `1.2.0` → `1.2.1`. First versioned schema change
  since the project's initial commit (Task ID 2).
- `README.md` updated with new DB filename and links to the new
  `docs/` files (Task ID 2).

### Fixed
- Schema drift problem: `schema_meta` + `schema_migrations` now
  exist, so future schema changes must bump the version. The 37 → 24
  table silent drift that already happened twice can no longer
  recur unnoticed (Task ID 2).

## [1.2.0] - 2026-07-21

### Added
- Initial CAGE EMPIRE scaffold (commit `986d438`).
- 25-table SQLite schema (`src/build_db.py`): simulation_clock,
  nations, regions, weight_classes, cities, markets, venues,
  promotions, gyms, style_archetypes, personality_archetypes,
  fighters, fighter_attributes (4 stats), fighter_personality
  (3 traits), fighter_career, staff, broadcast_staff, events,
  fights, fight_participants, event_cards, news_sources,
  news_items, commentary_segments.
- Minimal seed (`src/seed_data.py`): 1 promotion (Alpha Combat),
  2 fighters (John "Hammer" Vale, Marcus "Voltage" Reed), 1
  commentator (Nina Cross), 1 event (Alpha Combat: Test Night,
  2026-08-15), 1 fight scheduled as main event.
- Tick processor (`src/tick_processor.py`) advancing the simulation
  clock by one day per call.
- Tkinter 3-pane desktop UI (`src/app.py`): fighters list / events
  + fights / news + commentary. Buttons: Advance Day, Resolve
  Fight, Refresh.
- Windows launcher (`run.bat`) and macOS/Linux launcher (`run.sh`).
- `.gitignore` excluding `data/*.db`, `__pycache__/`, `.venv/`, IDE
  files.
- `README.md`, `requirements.txt`, `data/.gitkeep`, `docs/.gitkeep`,
  `mods/.gitkeep`, `saves/.gitkeep`.

### Known limitations (v1.2.0)
- Fight resolution is a coin flip (`random.randint(1, 100) > 50`).
  The 4 stored fighter attributes are not read.
- No rival promotions (single promotion only).
- No contracts, rankings, titles, injuries, training camps,
  scouting, finances, social media, rivalries, regen, voice layer,
  or mod tools.
- Event status never transitions out of `'scheduled'`.
- After the one seeded fight resolves, no new events are scheduled.
- Schema has no version marker (this is fixed in v1.2.1).
