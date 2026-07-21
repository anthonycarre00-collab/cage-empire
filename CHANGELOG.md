# Changelog

All notable changes to CAGE EMPIRE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to the schema versioning rules in
`docs/CONVENTIONS.md`.

## [Unreleased]

### Added
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
