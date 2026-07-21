# Changelog

All notable changes to CAGE EMPIRE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to the schema versioning rules in
`docs/CONVENTIONS.md`.

## [Unreleased]

### Added
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
