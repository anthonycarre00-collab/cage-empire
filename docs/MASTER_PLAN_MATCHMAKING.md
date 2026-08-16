> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Master Plan: Matchmaking Heartbeat + World Balance

> **Status:** PLANNING ONLY — no code changes yet. Awaiting user approval.
> **Source:** 3 research agents explored the codebase + WMMA5.
> **Supervisor:** main agent.

---

## 0. Executive Summary

The user identified the **#1 problem**: the Build a Card screen calculates finances without considering show quality — the actual fights on the card. This is the heartbeat of the game. The research confirms the gap is real and deep:

- **Event Builder preview uses a hardcoded `card_draw = 1.2`** — completely disconnected from actual card quality
- **The real card_draw formula exists** in `finance.py` but only fires AFTER the event completes
- **A complete matchup analysis engine exists** in `punditry.py` (predicted winner, style edge, excitement score) — but only fires post-fight, never pre-fight
- **The matchmaking nav item exists** but is a placeholder — no screen built
- **create_event writes the event row but ZERO fights** — the player can't actually build a card

Additionally, 3 world-balance issues were found:
- **Fighter generation uses BASE 50** (not 37) — regen fighters are systematically overpowered
- **Rival AI excludes the player from bidding wars** — no competition for signatures
- **Staff never age, retire, or regen** — the staff world is static

This plan addresses all of these. **No code will be written until the user approves.**

---

## 1. The Matchmaking Heartbeat — Redesign

### 1.1 The problem (confirmed by research)

Current "Build a Card" screen:
1. Pick a venue → ✅ works
2. Set financial levers (ticket price, marketing, PPV) → ✅ works
3. See projected P&L → ❌ uses hardcoded `card_draw=1.2` — completely fake
4. Schedule event → creates event row with ZERO fights

The player can't actually **build a card** — they can only pick a venue + set levers. The projection is disconnected from the actual card quality. The dopamine loop is broken:
- ❌ Book better fights → see projection rise (not possible — no fights to book)
- ❌ Resolve → get verdict (no fights to resolve)

### 1.2 The solution — 3-screen flow (inspired by WMMA5, improved)

**Screen 1: "Build a Card"** (rename to "Stack a Card" — Cage Empire voice)
- Pick a venue (existing, keep)
- Set financial levers (existing, keep)
- **NEW: See live projection that updates as you add fights** (the key change)
- The projection uses the REAL `card_draw_multiplier` formula from finance.py
- Button: "Start Matchmaking" → goes to Screen 2

**Screen 2: "Matchmaking"** (the star — NEW)
- 3-column layout (inspired by WMMA5, improved):
  - **Left column**: Roster list with filters (Available / Top 15 / On Streak / Hometown / By Weight Class). Clicking a fighter selects them as Red Corner.
  - **Center column**: The Card Builder
    - Red Corner vs Blue Corner picker (click fighter from left → fills Red; click from right → fills Blue)
    - "Book This Fight" button → adds to card
    - Card list with drag-drop reordering (main event, co-main, prelims)
    - Each booked fight shows: matchup quality chip (0-100), style matchup phrase, predicted excitement
    - Remove fight button per fight
  - **Right column**: Live Projection Panel
    - Projected Draw (0-100) — card quality score
    - Projected Attendance vs venue capacity
    - Projected PPV buys (if PPV)
    - Revenue / Expenses / Net Profit (color-coded green/yellow/red)
    - Card Health checklist (warnings: "main event weaker than co-main", "no title fight on PPV", "4 of 5 fights are strikers")
    - Voice phrase: "This card will pack the arena" / "Fans will demand refunds" / etc.

- **4 modals** (WMMA5 lacks or does poorly):
  - **Compare modal**: visual radar chart of 25 attributes + voice-layer style matchup analysis ("Reed's boxing vs Vale's wrestling — if Reed can keep it standing, he's got the chin")
  - **Tale of Tape modal**: UFC-broadcast-style graphic with portraits + height/reach/age/record/style/last-5
  - **What's at Stake modal**: ranking implications ("If Reed wins → projected rank #3; if he loses → #11; winner gets title shot")
  - **Fan Pulse modal**: voice-layer reaction mining the memory engine ("Reed hasn't fought since the Vale controversy — fans have been waiting")

**Screen 3: "Fight Night"** (future — not this phase)
- Live play-by-play (the other showcase feature the user mentioned — not built yet)

### 1.3 The key technical change

**Replace the hardcoded `card_draw = 1.2`** in `app_web.py::get_event_preview` with a real `project_card_draw(fights, event_meta)` function that:
- Uses the existing `card_draw_multiplier` formula from `finance.py::_compute_broadcast_revenue`
- Reads the actual fights booked on the card (main event marketability, co-main, title fights, rivalry heat)
- Updates live as the player adds/removes/reorders fights

This single change closes the gap between preview (fake number) and actual P&L (real formula).

### 1.4 Existing code to reuse (NOT reinvent)

Per the research, these already exist:
- `finance.py::_compute_broadcast_revenue` — the real card_draw formula
- `finance.py` helpers — `_get_main_event_marketability`, `_get_co_main_marketability`, `_count_title_fights`, `_count_rivalry_fights_heat_50_plus`, `_get_avg_card_marketability`
- `punditry.py::generate_matchup_analysis` — full tale-of-tape + predicted winner + style edge + excitement score. Currently fires post-fight but is safe to call pre-fight.
- `services.rival_ai.matchmaker._matchup_score` — 0-100 matchup quality score (35% marketability + 30% competitiveness + 20% storyline + 15% development_value)
- `services.matchmaking._get_available_fighters_for_card` — eligible-fighter query
- `services.rival_ai.event_scheduler._insert_event_and_card` — INSERT helper for fights + fight_participants + event_cards
- `show_rating.py` voice vocabulary — "instant classic" / "highly entertaining" / "solid night" / "decent show" / "lackluster"

### 1.5 "No easy mode" (per user directive)

The user explicitly said: "no easy mode such as guaranteeing good matchups."

- The matchup quality chip shows the score but doesn't tell the player WHO to book
- The "Suggested Matchups" panel surfaces opportunities (hometown fighter, #1-contender fight, debuting fighter) but doesn't auto-book — the player still makes every decision
- Bad bookings are allowed — the player CAN book a terrible main event, and the projection will show the consequence (low draw, low revenue, fans demand refunds)
- The Booking Adviser (WMMA5-inspired) surfaces opportunities but never replaces player judgement

---

## 2. World Balance Fixes

### 2.1 Fighter generation (EXTEND — small surgical fix)

**Problem:** `fighter_gen._generate_block` uses BASE 50, not 37. After the v3.20.0 re-seed dropped the world avg to ~37, regen fighters come in ~13 points above the world average → systematically overpowered.

**Fix:**
1. Change `fighter_gen._generate_block` line 226: base `50` → `37` (matches re-seeded world)
2. Add `generate_realization()` function — same personality-based formula as the backfill
3. Update `generate_fighter` to set `realization` in the fighter_career INSERT
4. Add the `realization` column migration to `build_db.py` MIGRATIONS list (currently missing — a fresh build won't have the column)

### 2.2 Rival AI signing — include the player in bidding wars (EXTEND)

**Problem:** The signing_agent has a sophisticated multi-promo bidding-war system AMONG AI promos — but the PLAYER is excluded (promo_id=1 filtered out). No player-vs-AI bidding wars exist.

**Fix:**
1. Remove the `promo_id=1` exclusion from `rival_ai.evaluate_signing_intents` — the player's promo is now a valid bidding participant
2. When a rival AI decides to pursue a free agent, fire a `SIGNING_INTENT` event on the bus
3. The player sees a "Bidding War Alert" on the Dashboard: "Rival Fight League is pursuing [Fighter Name]. You have 3 days to make a counter-offer."
4. If the player offers within the window, the fighter chooses based on: promo reputation + salary + signing bonus + promo size_tier fit
5. If the player doesn't respond, the rival AI signs the fighter

**Also:** Update `base_salary` (fair value) formula to include `realization` — a "bust" (potential=85, realization=0.5, ceiling=42) should be priced lower than a "realizer" (potential=85, realization=1.0, ceiling=85).

### 2.3 Staff lifecycle — aging, retirement, regen (BUILD — mostly new)

**Problem:** Staff never age, never retire, never die, contracts never expire. The staff world is static.

**Fix:**
1. **Staff aging** — on annual tick (once per sim-year), increment all staff.age by 1
2. **Staff retirement** — on annual tick, staff over 65 have a retirement probability curve (mirroring fighter retirement):
   - Age 65-69: 10% chance/year
   - Age 70-74: 25% chance/year
   - Age 75+: 50% chance/year
   - On retirement: fire `STAFF_RETIRED` event, void contract, write news item, generate replacement
3. **Staff regen** — when a staff retires, generate a replacement (similar role + skill range, new name, age 30-45). This keeps the staff market populated.
4. **Contract expiry** — extend `_check_contract_expiry` in tick_processor.py to handle staff_contracts. When a staff contract expires:
   - If the promo wants to renew (rival AI decision): renew at adjusted salary
   - If not renewed: staff becomes a free agent (goes into Staff Market)
5. **Staff death** — very rare (1% chance/year for staff over 70). On death: fire `STAFF_DIED` event, void contract, write news item, generate replacement.

---

## 3. Implementation Phases (NO CODE YET — awaiting approval)

### Phase M1 — Fighter gen fix + realization migration (1 day)
- Fix `fighter_gen._generate_block` base 50→37
- Add `generate_realization()` + wire into `generate_fighter`
- Add realization column migration to build_db.py MIGRATIONS list
- Test: generate 10 new fighters, verify attributes ~37 + realization 0.4-1.0

### Phase M2 — Staff lifecycle (2 days)
- Staff aging (annual tick)
- Staff retirement (probability curve + STAFF_RETIRED event)
- Staff regen (generate replacement)
- Contract expiry for staff_contracts
- Test: run sim forward 1 year, verify staff age + retire + regen

### Phase M3 — Rival AI bidding wars (2 days)
- Remove player exclusion from signing intents
- Add SIGNING_INTENT event + Dashboard alert
- Player counter-offer flow
- Include realization in fair-value formula
- Test: run sim forward, verify bidding wars happen + player can compete

### Phase M4 — Matchmaking screen (3-4 days — the big one)
- Build `matchmaking.js` (3-column layout: roster + card builder + live projection)
- Build `project_card_draw()` function (replaces hardcoded 1.2)
- Wire punditry.py pre-fight (matchup analysis + excitement score)
- Wire matchmaker._matchup_score (quality chip per fight)
- Build 4 modals (Compare, Tale of Tape, What's at Stake, Fan Pulse)
- Rename "Build a Card" → "Stack a Card" (Cage Empire voice)
- Integrate: Stack a Card → Start Matchmaking → Matchmaking screen → Schedule card
- Test: book a card, verify projection updates with each fight, verify projection matches post-event P&L

### Phase M5 — Polish + balance (1 day)
- Card health checklist (warnings)
- Suggested Matchups panel (opportunities, not auto-booking)
- Voice phrases for card quality
- Balance tuning (verify mid-tier + top-tier projections feel right)
- Test: full flow from venue pick → card build → schedule → advance day → resolve → verify P&L matches projection

**Total: ~9-10 dev-days.** No code written until user approves.

---

## 4. What the user should decide

1. **Approve the 3-screen flow?** (Stack a Card → Matchmaking → Fight Night [future])
2. **Approve the "no easy mode" design?** (matchup quality shown but no auto-booking, bad bookings allowed)
3. **Approve the 4 modals?** (Compare, Tale of Tape, What's at Stake, Fan Pulse)
4. **Approve the phase order?** (M1 fighter gen → M2 staff lifecycle → M3 bidding wars → M4 matchmaking → M5 polish)
5. **Any priorities to reorder?** (e.g., do matchmaking first since it's the heartbeat?)

---

## 5. Research docs (already written)

- `docs/RESEARCH_MATCHMAKING_SHOWRATING.md` — existing matchmaking + show_rating + event builder code analysis
- `docs/RESEARCH_FIGHTERGEN_RIVALAI_STAFFLIFE.md` — fighter generation + rival AI + staff lifecycle analysis
- `docs/RESEARCH_WMMA5_MATCHMAKING.md` — WMMA5 matchmaking approach + what to learn + what to improve

All 3 are available for the user to read if they want more detail before approving.
