# Changelog

All notable changes to CAGE EMPIRE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to the schema versioning rules in
`docs/CONVENTIONS.md`.

## [Unreleased]

### Added
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
