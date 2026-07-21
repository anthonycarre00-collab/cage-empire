# CAGE EMPIRE

Text-first MMA promotion booking sim. Run a promotion from the bottom up —
sign fighters, scout prospects, book cards, manage staff and finances, and
follow long-running fighter careers through retirement, injury, decline,
death, and regeneration.

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
1. Rebuild the SQLite database (`data/mma_booking_sim_v1_2.db`)
2. Seed a minimal playable world (2 fighters, 1 event, 1 fight)
3. Launch the Tkinter desktop app

## Run order (manual, if you skip the launcher)

```bash
python src/build_db.py          # drop + recreate schema
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
├─ .gitignore
├─ data/
│  ├─ .gitkeep
│  └─ mma_booking_sim_v1_2.db   # SQLite DB (created on first run, gitignored)
├─ src/
│  ├─ build_db.py          # drops + recreates full schema (v1.2)
│  ├─ seed_data.py         # minimal playable seed
│  ├─ tick_processor.py    # advances simulation clock
│  └─ app.py               # Tkinter desktop UI
├─ docs/
│  └─ .gitkeep             # drop the v1.6 design doc markdown here
├─ mods/
│  └─ .gitkeep             # community / user mod packs
└─ saves/
   └─ .gitkeep             # save-game exports
```

## Current build state (v1.2 minimal)

- **Schema**: 25 tables — simulation_clock, nations, regions, weight_classes,
  cities, markets, venues, promotions, gyms, style_archetypes,
  personality_archetypes, fighters, fighter_attributes (4 stats),
  fighter_personality (3 traits), fighter_career, staff, broadcast_staff,
  events, fights, fight_participants, event_cards, news_sources, news_items,
  commentary_segments.
- **Seed**: 1 promotion (Alpha Combat), 2 fighters (John "Hammer" Vale,
  Marcus "Voltage" Reed), 1 commentator (Nina Cross), 1 event, 1 fight
  scheduled as main event.
- **UI**: Tkinter three-pane layout — fighters list / events+fights / news+
  commentary. Buttons: Advance Day, Resolve Fight, Refresh.

## Design pillars (per v1.6 spec)

1. Realism first, but still fun.
2. Every number should translate into readable meaning (voice / interpretation
   layer — not yet implemented).
3. The world should feel alive through news, social media, rival promotions,
   punditry, and legacy.
4. Highly moddable.
5. Save files must remain long-lived and backward compatible.

## Roadmap

- **v1.2 (current)**: minimal schema, basic Tkinter UI, random fight resolver.
- **v1.3 (next)**: extend schema to v1.6 spec — expand `fighter_attributes`
  (24 stats) and `fighter_personality` (17 traits), add `betting_odds`,
  `matchup_analysis`, `pundit_segments`, `training_camps`, `regen_lineage`,
  `fighter_memory_links`, name pools, voice descriptors, hall of fame.
- **v1.4**: real round-by-round fight engine driven by combat attributes.
- **v1.5**: voice/interpretation layer, show rating engine, scouting system,
  finance screen, rival promotion AI.
- **v1.6**: regen engine + memory resurfacing, CustomTkinter dark theme,
  mod tools skeleton.
