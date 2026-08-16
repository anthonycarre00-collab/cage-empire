# CAGE EMPIRE — Next Level Development Plan (v5 — REVISED)

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Sources:** ChatGPT Post-Review Development Directive + user feedback + UI investigation
**Goal:** Move from "working simulation" to "compelling indie management game"

---

## CRITICAL FINDING: UI Architecture Confusion

### The problem

There are **THREE UI codebases** in the repo:

1. **`src/app.py`** — OLD Tkinter app (`class App(tk.Tk)`). **This is what PLAY.bat launches.** The user sees THIS. It has a basic three-pane layout, a Contracts tab (which the user calls "Deals"), a Rankings tab, and basic buttons. No voice phrases, no interpretation layer, no redesigned screens.

2. **`src/ui/app.py`** — CustomTkinter (CTk) app (`class CageEmpireApp(ctk.CTk)`). This is the REDESIGNED UI with the sidebar, top bar, widgets, voice phrases, etc. **This is NOT being launched.** It has 6 implemented screens (Dashboard, Roster, Fighter Profile, Free Agents, Scouting, Save/Load) + 15 placeholder screens.

3. **`src/app_web.py`** — pywebview web UI. **NOT being launched, NOT needed.** This was an experiment that should be removed.

4. **`src/web/`** — HTML/CSS/JS for the pywebview UI. **NOT needed.** Should be removed.

### What the user actually sees

The OLD Tkinter app (`src/app.py`) with:
- A basic three-pane layout (fighters list / events+fights / news+commentary)
- A "Contracts" tab (the "Deals" screen with errors)
- A Rankings tab
- Buttons: Advance Day, Resolve Fight, Refresh
- NO redesigned screens, NO voice phrases, NO interpretation layer
- NO rivalries screen (the 0-0 issue is in this old app OR in the CTk placeholder)

### What needs to happen

1. **PLAY.bat + run.sh must launch the CTk app** (`src/ui/app.py`), not the old Tkinter app (`src/app.py`)
2. **Remove `src/app_web.py` + `src/web/`** — not needed, not used
3. **The old `src/app.py` must stay** as a module (it re-exports functions used by tests + tick_processor), but should NOT be the entry point
4. **The 15 placeholder screens in the CTk app need to be implemented** — or at minimum, the most important ones

### Which screens to implement first (priority order)

Based on ChatGPT's directive + user feedback + game loop:

**Critical (player can't play without these):**
1. **Fight Night** — watch fights resolve (the core dopamine loop)
2. **Build a Card / Event Builder** — book fights (player agency)
3. **The Wire (news)** — see what's happening (the "why press Advance Day" screen)
4. **The Books (finance)** — manage cash (economic decisions)

**Important (player wants these soon):**
5. **Bad Blood (rivalries)** — see rivalries (fix the 0-0 display)
6. **Deals (contracts)** — manage fighter contracts
7. **The Rankings** — see who's where
8. **Belts (titles)** — see champions
9. **Calendar** — see upcoming events
10. **The Archive** — see past events

**Nice to have:**
11. **The Competition (rival promos)** — watch AI promos
12. **Training Camps (gyms)** — see gym transfers
13. **Hall of Fame** — see legends
14. **The Record Book** — see records
15. **Settings + Mods** — utility

---

## Part 1: Critical Fixes (user-reported bugs)

### Bug 1: "Deals" screen has errors
**Root cause:** The user is seeing the OLD Tkinter app's Contracts tab. The query likely references columns that changed during HW. The CTk app's Deals screen is a placeholder ("coming soon").

**Fix:** Implement the Deals/Contracts screen in the CTk app. Show active contracts with fighter name, type, salary, start/end date, status. Read from `contracts` + `fighter_contracts` tables.

### Bug 2: Historical fights have "replay" option
**Root cause:** The OLD Tkinter app may show fight_beats or round-by-round data. The CTk app's Fighter Profile shows fight_history (W/L, opponent, result type, event, date) — no replay.

**Fix:** Ensure the CTk app's Fighter Profile shows ONLY: result, opponent, result type, event name, date. NO fight_beats, NO round-by-round, NO replay. The fight_beats/rounds data stays in the DB for the engine but is never shown in the UI.

### Bug 3: Rivalries show "series is even" for 0-0
**Root cause:** 8/93 active rivalries have `fights_count=0`. The rivalry was created (title_rivalry type) but the fighters haven't fought yet. The display says "series is even" which is misleading.

**Fix:** When implementing the Rivalries screen in CTk, check `fights_count`. If 0, show "These two haven't met yet" or "Rivalry brewing — no fights yet." Only show head-to-head records when `fights_count > 0`.

### Bug 4: Finances — Alpha has $1B+
**Root cause:** The backfill script accumulated decades of event revenue into `current_cash`. This is unrealistic.

**Fix:** Reset `current_cash` to realistic starting values after backfill:
- Major: $50M
- Mid: $10M
- Small: $5M
The backfilled finance_transactions remain as historical records but don't inflate current cash.

---

## Part 2: ChatGPT RED Priorities

### Priority 1: Fix the launcher (CRITICAL — nothing else matters if the player can't see the game)

**Fix:** 
- Update `PLAY.bat` to launch `python src/ui/app.py` (or `python -m ui.app`)
- Update `run.sh` to launch `python src/ui/app.py`
- Keep `src/app.py` as a module (re-exports) but remove its `if __name__ == "__main__"` block or point it to `ui.app.main()`
- Remove `src/app_web.py` + `src/web/` (not needed)

### Priority 2: Promotion Economics (§7)

**Investigation:**
- Audit the full revenue/expense model in `src/finance.py`
- Check: venue costs vs capacity vs ticket prices vs attendance
- Check: fighter purse formula
- Check: broadcast revenue by tier
- Target: Major profitable with good cards, small promos break even

### Priority 3: Memory Resurfacing in Player Gameplay (§6.2)

**Plan:**
- Write a player-path test that books a rematch between fighters with history
- Verify `generate_fight_preview_memory_news` fires
- Verify the player sees the memory connection in the news feed

### Priority 4: Long-Run Performance (§8)

**Plan:**
- Run 5-year, 10-year, 20-year soaks
- Track all metrics
- Profile + fix bottlenecks

---

## Part 3: UI/UX Screen Implementation

### Screen Implementation Plan

Each screen should:
1. Read from the interpretation layer (fighter_descriptors, daily_headlines) where possible
2. Read from DB directly for raw data (events, fights, contracts)
3. Use voice phrases, not raw numbers (except Scouting Report + Fighter Profile attributes)
4. Be performant (single query per refresh, no N+1)

**Screen specs:**

#### Fight Night (fight_resolution)
- Shows the current event's fights in card order
- Player clicks "Resolve Next Fight" → fight resolves → result shown
- Result: winner, loser, result type, finish round, finish time
- NO beat-by-beat replay, NO round-by-round detail
- Performance rating shown as voice phrase ("spectacular finish", "grinding decision")
- After all fights: event summary (show rating, attendance, revenue)

#### Build a Card (event_builder)
- Shows available fighters (player's roster, by weight class)
- Player selects two fighters → matchup analysis (punditry)
- Player assigns card slot (main event, co-main, prelim)
- Confirm card → event scheduled
- Uses matchmaking service for availability checking

#### The Wire (news)
- Scrollable feed of news items, filtered by importance
- LEGENDARY/MAJOR at top, ROUTINE at bottom
- Each item: headline, body, topic chip, date, fighter/promotion link
- Click fighter name → navigate to Fighter Profile
- Filter by topic (signing, fight, injury, retirement, etc.)

#### The Books (finance)
- Current cash (big number)
- Recent transactions (last 20)
- Revenue vs expenses chart (sparkline)
- Ticket price lever + marketing spend lever
- Upcoming event projected revenue/expense

#### Bad Blood (rivalries)
- List of active rivalries, sorted by heat
- Each: Fighter A vs Fighter B, rivalry type, heat bar, head-to-head record
- If fights_count=0: "Rivalry brewing — no fights yet"
- Click → rivalry detail (fight history between the two)

#### Deals (contracts)
- List of active contracts for player's promotion
- Each: fighter name, type, salary, start/end, status
- Expiring soon filter (next 30 days)
- Release button (with confirmation)

---

## Part 4: Attribute Colour Scheme

Define colour bands matching voice tiers:
- 0-24: Red (#DC143C) — poor/abysmal
- 25-39: Orange (#FF8C00) — limited
- 40-59: Yellow (#DAA520) — average
- 60-74: Light Green (#7CFC00) — capable
- 75-89: Green (#00CD00) — strong
- 90-100: Gold (#FFD700) — elite

Apply to:
- Fighter Profile attribute bars
- Roster attribute columns (if shown)
- Scouting report attribute display

Implementation: CTk widgets use `fg_color` parameter. The `attribute_bar.py` widget already exists in `src/ui/widgets/components/` — add colour mapping.

---

## Part 5: Implementation Order

### Phase 1: Fix the launcher + cleanup (1 day)
1. Update PLAY.bat + run.sh to launch `src/ui/app.py`
2. Remove `src/app_web.py` + `src/web/`
3. Reset promotion cash to realistic values
4. Test: game launches with CTk UI

### Phase 2: Implement critical screens (3-4 days)
5. Fight Night (fight_resolution)
6. Build a Card (event_builder)
7. The Wire (news)
8. The Books (finance)
9. Deals (contracts) — fix the errors

### Phase 3: Implement important screens (2-3 days)
10. Bad Blood (rivalries) — fix 0-0 display
11. The Rankings
12. Belts (titles)
13. Calendar
14. The Archive

### Phase 4: Economics + memory (2-3 days)
15. Audit + tune promotion economics
16. Player-path memory resurfacing test
17. Fix any memory issues

### Phase 5: Polish (2-3 days)
18. Attribute colour scheme
19. Dashboard redesign (newsroom hierarchy)
20. Player watchlist (minimal)
21. Long-run validation (5/10/20-year soaks)
22. Final README + docs

---

## What we're NOT doing
- ❌ NO web UI (pywebview + src/web/ removed)
- ❌ NO new schema/tables
- ❌ NO new attributes
- ❌ NO architecture rewrite
- ❌ NO exact MMA statistical replication
- ❌ NO fight replay/round-by-round in UI
- ❌ NO raw numbers where voice phrases exist

## ChatGPT Directive Assessment

ChatGPT's directive is **excellent and correct**. The key insight: "The project has crossed from 'build the simulation foundation' into 'make the existing simulation emotionally meaningful to the player.'" This is exactly right. We have the machinery — now we need to surface it through a proper UI.

The biggest gap ChatGPT didn't know about: **the player isn't seeing the redesigned UI.** The launcher points to the old Tkinter app. Fixing this is Priority #1 — nothing else matters if the player can't see the game.
