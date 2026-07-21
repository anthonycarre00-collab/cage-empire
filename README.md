# CAGE EMPIRE

Text-first MMA promotion booking sim. Run a promotion from the bottom up —
sign fighters, scout prospects, book cards, manage staff and finances, and
follow long-running fighter careers through retirement, injury, decline,
death, and regeneration.

> **Current state:** v1.2.1 — working skeleton. See `docs/MASTER_PLAN.md`
> for the gap between current state and the v1.6 spec target.

## Quick start

### Windows
```bat
run.bat
```

### macOS / Linux
```bash
chmod +x run.sh
./run.sh
```

This will:
1. Rebuild the SQLite database (`data/cage_empire.db`)
2. Seed a minimal playable world (2 promotions, 5 fighters, 1 event, 1 fight)
3. Launch the Tkinter desktop app

## Run order (manual, if you skip the launcher)

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
