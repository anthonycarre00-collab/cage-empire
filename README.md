# CAGE EMPIRE

Text-first MMA promotion booking sim. Run a promotion from the bottom up —
sign fighters, scout prospects, book cards, manage staff and finances, and
follow long-running fighter careers through retirement, injury, decline,
death, and regeneration.

> **Current state:** Schema 3.12.0 — 4,450 active fighters, 60 Hall of Fame
> legends, full interpretation layer (momentum, pressure, career phases,
> narrative families, legacy, daily headlines, memory engine), 6 working UI
> screens (Dashboard, Roster, Fighter Profile, Free Agents, Scouting, Save/Load).

## Quick Start — ONE CLICK

### Windows
1. Install Python 3.10+ from https://python.org (check "Add Python to PATH")
2. Download the game from GitHub (Code → Download ZIP, then unzip)
3. **Double-click `PLAY.bat`**

That's it. The first run will:
- Install the required packages automatically (customtkinter, pillow, ttkbootstrap)
- Build the world database (4,450 fighters from your profiles, ~10 seconds)
- Launch the game

### macOS / Linux
1. Install Python 3.10+
2. Open a terminal in the game folder
3. Run: `./run.sh build-world` (first time only, builds the world)
4. Run: `./run.sh run` (launches the game)

## How to Play

1. **Dashboard** — Your home screen. Shows top stories, headlines, your
   promotion status, fighter watch (top prospect, biggest fall), recent news.
2. **Advance Day** — Click the gold "▶ Advance Day" button in the top bar
   to progress the simulation. The world comes alive: fights are resolved,
   fighters retire, news is generated, headlines update.
3. **Roster** — Browse your 1,000+ fighters. Each shows their career phase
   ("rising contender"), momentum ("riding a hot streak"), and narrative
   family ("the wunderkind everyone's talking about") — all as voice phrases,
   not raw numbers.
4. **Fighter Profile** — Click any fighter to see their full profile: bio,
   career stats, recent fights, all 26 attributes and 20 personality traits
   as voice descriptors.
5. **Free Agents** — Browse 550+ unsigned fighters. Click "Sign Selected
   Fighter" to add them to your roster.
6. **Scouting** — Assign scouts to evaluate free agents. Scouting reports
   reveal estimated potential, strengths, and weaknesses.
7. **Save/Load** — Save your game, load a previous save, or delete saves.
   The game auto-saves on exit.

## What Makes CAGE EMPIRE Different

- **No raw numbers.** Every attribute, every rating, every stat is translated
  into a voice phrase. You don't see "Punch Power: 87" — you see
  "fight-ending power in both hands."
- **The player collects stories, not fighters.** The interpretation layer
  generates momentum, pressure, career phases, narrative families, and daily
  headlines from the simulation. Every fighter has a story.
- **4,450 unique fighters.** Each with their own bio, attributes derived from
  their bio keywords, career history, and personality.

## For Developers

### Build modes
```bash
./run.sh run          # Launch the game
./run.sh build-world  # Full world rebuild (4,450 fighters, ~10s)
./run.sh build-dev    # Minimal dev rebuild (5 fighters for testing)
./run.sh migrate      # Apply schema migrations (preserves world data)
./run.sh check        # Forensic DB integrity check (140 checks)
./run.sh test         # Run all 43 acceptance tests
```

### Architecture
- **Simulation layer:** `src/tick_processor.py`, `src/services/fight_engine.py`,
  `src/services/matchmaking.py`, `src/career_arc.py`, etc.
- **Interpretation layer:** `src/interpretation/` — context_engine, career_phase_engine,
  narrative_families, memory_engine, headline_engine, legacy_engine, snapshot_cache
- **Voice layer:** `src/voice.py` — pure functions translating numbers to phrases
- **UI layer:** `src/ui/` — CustomTkinter screens reading from cache tables only (§17)
- **Database:** SQLite, schema 3.12.0, 54+ tables, 21 migrations

```bash
python src/build_db.py          # drop + recreate schema (version 1.2.1)
python src/seed_data.py         # insert minimal seed data
python src/app.py               # open the desktop UI
python src/tick_processor.py    # (optional) advance the sim clock one day
```

## Project layout

```
CAGE EMPIRE/
├─ run.bat                 # Windows launcher
├─ run.sh                  # macOS / Linux launcher
├─ requirements.txt        # Python deps (MVP = stdlib only)
├─ README.md               # this file
├─ CHANGELOG.md            # versioned change log (see docs/CONVENTIONS.md)
├─ .gitignore
├─ data/
│  ├─ .gitkeep
│  └─ cage_empire.db            # SQLite DB (created on first run, gitignored)
├─ src/
│  ├─ build_db.py          # drops + recreates full schema (v1.2.1)
│  ├─ seed_data.py         # minimal playable seed (2 promotions, 5 fighters)
│  ├─ tick_processor.py    # advances simulation clock
│  └─ app.py               # Tkinter desktop UI
├─ docs/
│  ├─ MASTER_PLAN.md       # current state, target state, revised principle
│  ├─ STAGES.md            # 5 stages, 30 tasks, briefs + acceptance criteria
│  ├─ SCHEMA_DRIFT_AUDIT.md# designed vs built, table by table
│  └─ CONVENTIONS.md       # schema versioning + changelog + worklog rules
├─ mods/
│  └─ .gitkeep             # community / user mod packs
└─ saves/
   └─ .gitkeep             # save-game exports
```

## Documentation

**Read these in order before touching the codebase.** See
`docs/CONVENTIONS.md §8` for the full cross-session handoff protocol.

1. `README.md` (this file) — project overview.
2. `docs/MASTER_PLAN.md` — current state and revised principle.
3. `docs/STAGES.md` — what task we are on, what is next.
4. `docs/CONVENTIONS.md` — the rules (schema versioning, changelog, etc.).
5. `docs/SCHEMA_DRIFT_AUDIT.md` — what tables exist and what is missing.
6. `CHANGELOG.md` — what has changed recently.

## Current build state (v1.2.1)

- **Schema version:** `1.2.1` (recorded in `schema_meta` table).
- **Tables:** 26 (24 from v1.2.0 + `schema_meta` + `schema_migrations`).
- **Seed:** 2 promotions (Alpha Combat, Rival Fight League — RFL inert),
  5 fighters (2 AC, 3 RFL), 1 commentator, 1 event, 1 fight scheduled.
- **UI:** Tkinter three-pane layout — fighters list / events+fights /
  news+commentary. Buttons: Advance Day, Resolve Fight, Refresh.
- **Known limitations:** fight resolution is still a coin flip
  (`random.randint(1, 100) > 50`) — Task ID 3 will fix this. No
  contracts, rankings, titles, injuries, scouting, finances, social,
  rivalries, regen, voice layer, or mod tools yet.

## Design pillars (per v1.6 spec)

1. Realism first, but still fun.
2. Every number should translate into readable meaning (voice / interpretation
   layer — not yet implemented).
3. The world should feel alive through news, social media, rival promotions,
   punditry, and legacy.
4. Highly moddable.
5. Save files must remain long-lived and backward compatible.

## Roadmap (5 stages, 30 tasks)

- **Stage 1 close-out (Tasks 3-8):** real attribute-based fight resolver,
  `fight_history` table, schema version enforcement, second promotion UI,
  event lifecycle, repeatable event generator.
- **Stage 2 career systems (Tasks 9-14):** contracts, rankings, titles,
  retirement, free agency, regen engine.
- **Stage 3 human layer (Tasks 15-19):** injuries, training camps, weight
  cuts, scouting, voice/interpretation layer.
- **Stage 4 media & economy (Tasks 20-24):** finances, social media,
  rivalries, news engine, punditry/matchup analysis.
- **Stage 5 AI & polish (Tasks 25-30):** rival promotion AI, show rating
  engine, deeper venues/markets, CustomTkinter dark theme, mod tools,
  save/load.

See `docs/STAGES.md` for the full brief and acceptance criteria for each
task.

## Why the original "big-bang v1.6 schema dump" plan was killed

The schema went from ~37 tables in an early draft to 24 in the v1.2.0
commit with no flag raised. That is a process failure, not a code
failure. The fix is **schema versioning + a CHANGELOG + an audit
trail**, all of which are dirt cheap to add now and expensive to
retrofit later. A 60-table big-bang dump would have replayed the exact
same failure mode. See `docs/MASTER_PLAN.md §2` for the full rationale.
