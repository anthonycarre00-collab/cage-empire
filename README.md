# CAGE EMPIRE

A text-based MMA promotion management simulation. Build your promotion from the ground up — sign fighters, scout prospects, book cards, manage finances, and follow long-running fighter careers through retirement, injury, decline, and regeneration. The world evolves autonomously whether you're playing or not.

> **Current state:** Schema 3.36.0 — 4,000 reseeded fighters (7-tier pyramid from Elite to Fringe), 2,000 grey-name historical opponents, 80,000 fight history rows, 78 champions across 10 promotions, 343 rivalries, full interpretation layer, autonomous rival AI with memory, roster caps, 5-year soak test completes in 7.5 minutes.

---

## What is this game?

CAGE EMPIRE is a management sim where you run an MMA promotion. You're not a fighter — you're the matchmaker, the GM, the person who decides who fights whom, who gets signed, who gets cut, and how much to charge for tickets. The fighters are the stars. Your job is to build a promotion that puts on great shows and makes money.

The world doesn't wait for you. While you're managing your roster, nine rival promotions run by AI are scheduling their own events, signing free agents, developing prospects, and competing for the same talent pool. They remember past results — if you outbid them for a fighter, they'll remember. If their champion loses, they remember that too.

Every fighter has a career arc. They start as prospects with raw potential, develop through training camps, peak in their late 20s, and decline as they age. They retire and are replaced by regenerated prospects who carry the lineage of retired legends. A fighter you sign at 18 could be a champion by 23 — or could flame out and become a gatekeeper. The simulation decides, based on their attributes, personality, and the opportunities you give them.

---

## Quick Start

### Windows
1. Install Python 3.10+ from https://python.org (check "Add Python to PATH")
2. Download the game from GitHub (Code → Download ZIP, then unzip)
3. **Double-click `PLAY.bat`**

### macOS / Linux
1. Install Python 3.10+
2. Open a terminal in the game folder
3. Run: `./run.sh build-world` (first time only)
4. Run: `./run.sh run` (launches the game)

### Manual
```bash
pip install -r requirements.txt
python src/build_db.py --fresh     # build the world DB (~10s)
python src/seed_data.py            # seed minimal playable data
python src/app_web.py              # launch the web UI
```

---

## How to Play

1. **Dashboard** — Your home screen. Shows top stories, headlines, your promotion's cash balance, fighter watch cards, recent news, and echoes of your past decisions.
2. **Advance Day** — The core action. Click "Advance Day" to progress the simulation by one day. Rival promotions schedule events, fights resolve, fighters retire and regenerate, news is generated, and the world evolves.
3. **Roster** — Browse your signed fighters. Each shows their career phase ("rising contender"), momentum ("riding a hot streak"), and narrative family ("the wunderkind everyone's talking about") — all as voice phrases, not raw numbers.
4. **Fighter Profile** — Click any fighter for their full bio, career stats, fight history, 26 attributes, 20 personality traits, and scouting reports.
5. **Event Builder** — Build fight cards. Choose matchups, set card slots (main event, co-main, prelims), confirm the card.
6. **Fight Night** — When your event's date arrives, watch fights resolve one by one with beat-by-beat commentary.
7. **Free Agents** — Browse ~3,600 unsigned fighters. Filter by weight class. Sign them to your roster (subject to roster caps).
8. **Scouting** — Assign scouts to evaluate fighters. Reports reveal potential, strengths, and weaknesses.
9. **Finance** — Set ticket prices and marketing spend. Watch your cash flow. Go bankrupt and you'll enter REBUILDING mode.
10. **Rival Promotions** — Watch AI promotions schedule events, sign fighters, and compete. They remember past interactions.

### Continue Button
The game auto-saves every 30 sim days. Your world persists across sessions. Click "Continue" to load your most recent save.

---

## What Makes This Different

### Voice-First Design
You never see "Punch Power: 87." You see "fight-ending power in both hands." Every attribute, rating, and stat is translated into a voice phrase by the interpretation layer. Fighters have momentum, pressure, career phases, narrative families, and legacy states — all described in words, not numbers.

### Autonomous World
Rival AI promotions schedule events, resolve fights, sign free agents, bid against you, remember past results, go bankrupt, and rebuild. The world runs on its own — you're just one promotion in a living ecosystem.

### Player Agency + Echoes
Every decision you make is logged and can resurface later:
- "Since you signed Ramirez in May, she's won four straight."
- "You released Vale six months ago — he just signed with your rival."
- "The prospect you scouted last year just won a title."

The world remembers what you did and reminds you of the consequences.

### Historical Persistence
The world remembers its own history through 15 memory link types — previous fights, rivalries, title fights, former champions, controversial losses, comebacks, milestones. When two fighters with history are booked for a rematch, the news engine surfaces that history: "History looms over Vale vs Reed."

### Career Arcs
Fighters grow (ages 18-27), peak (28-29), and decline (30+). They retire and are replaced by regenerated prospects who carry the lineage of retired legends. The Hall of Fame preserves the greatest careers.

### Realistic Fighter Population
4,000 fighters across 7 career tiers — from Elite (72 fighters, champion-level) to Fringe (200 fighters, below replacement level). The distribution is a pyramid, not a bell curve. Most fighters are gatekeepers. A few are stars. That's how MMA works.

---

## Roster Caps

Promotions can't hoard talent indefinitely:

| Promotion tier | Max roster |
|---|---|
| Major | 100 |
| Mid | 80 |
| Small | 50 |

When you're at cap, you'll see: "Your roster is full (70/100). Release a fighter to make room." Rival AI respects the same caps.

---

## Performance

| Soak test | Time | Status |
|---|---|---|
| 30-day | 6.2s (0.21s/day) | ✅ PASS |
| 365-day | 94.9s (1.6min) | ✅ COMPLETE |
| 5-year | 7.5min (0.22s/day) | ✅ COMPLETE |

The simulation runs 365 days in under 2 minutes. Five years in under 8 minutes. Per-tick cost stays stable — no super-linear growth.

---

## For Developers

### Build + Test
```bash
./run.sh run                    # Launch the game
./run.sh build-world            # Full world rebuild
./run.sh migrate                # Apply schema migrations
python scripts/invariant_checker.py          # 8 world-DB invariants
python scripts/soak_test.py 30               # 30-day soak test
python scripts/soak_test.py 365 --no-backup  # 365-day soak (~2min)
python scripts/soak_test.py 1825 --no-backup # 5-year soak (~7.5min)
python scripts/measure_fight_distribution.py # Fight result calibration
python scripts/economic_reconciliation.py    # Finance audit
```

### Architecture
```
SIMULATION (tick_processor, fight_engine, matchmaking, career_arc, rival_ai)
    ↓ EventBus (22 event types, 16+ subscribers, error-persisted to DB)
INTERPRETATION (context_engine, career_phase, memory, echoes, headlines, legacy)
    ↓ SNAPSHOT/CACHE (fighter_descriptors, daily_headlines)
UI (web — 22 JS modules via bridge.js API)
```

### Database
- **SQLite**, schema 3.36.0, 63+ tables, 48 migrations
- **4,000 fighters** (7-tier pyramid) + 2,000 grey-name historical opponents
- **80,000 fight history rows** (avg 20 fights per fighter)
- **Provenance:** world_version + seed_version in schema_meta
- **Save:** file-copy + WAL checkpoint + .meta.json sidecar + 4-step compatibility check

### Key Docs
1. `docs/CURRENT_SYSTEM_STATE.md` — single source of truth
2. `docs/GPT_PLAN_AUDIT.md` — W1-W48 compliance audit
3. `docs/Hardening_Phase.md` — HW1-HW10 hardening plan
4. `docs/1YR_SIM_ANALYSIS.md` — 1-year sim analysis + findings
5. `docs/RESEED_PLAN.md` — DB reseed methodology
6. `docs/DECISION_CHAINS.md` — 10 decision→consequence chains

---

## Known Limitations

- **Fight engine calibration:** KO rate is too low (0% in 1-year sim), split decisions too high (38% vs target 10%). The reseeded fighter data should improve this, but the fight engine thresholds may also need tuning.
- **Financial state machine:** Most promotions end up in REBUILDING after 1 year — thresholds may be too aggressive.
- **Gym changes:** Fighters never switch gyms during the sim. The gym-transfer flow doesn't exist yet.

---

## License

Private project. All rights reserved.
