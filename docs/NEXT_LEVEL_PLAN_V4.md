# CAGE EMPIRE — Next Level Development Plan (v4)

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Sources:** ChatGPT Post-Review Development Directive + user feedback + 1-year sim analysis
**Goal:** Move from "working simulation" to "compelling indie management game"

---

## Executive Summary

ChatGPT's directive is excellent and aligns with our direction. The key message: **stop expanding the foundation, start making the existing simulation emotionally meaningful to the player.** We have enough systems. Now we need to surface them, fix the remaining correctness issues, and make the player care.

This plan addresses:
1. User-reported bugs (Deals screen, replay option, rivalries 0-0, finances)
2. ChatGPT's RED priorities (economics, memory resurfacing, long-run performance)
3. UI/UX review (all screens, data sources, attribute colour scheme)
4. Player attachment phase (watchlist, dashboard, interpretation layer)

---

## Part 1: Bug Fixes (user-reported)

### Bug 1: "Deals" screen has errors
**Investigation:** The UI is Tkinter-based (`src/ui/screens/`). The "Deals" screen is likely the "Contracts" tab in `src/app.py` (line 670: "Contracts tab holds a read-only Treeview of the player's contracts"). It may be failing because:
- The contracts table schema changed during HW (fighter_contracts vs contracts)
- The query references columns that don't exist
- The player_settings table doesn't have player_promotion_id set

**Fix:** Audit the Contracts/Deals screen query. Fix the column references. Test with a real player promotion selected.

### Bug 2: Historical fights have "replay" option
**Investigation:** The user says there's a replay option on fight records. I searched the web JS (doesn't exist — the UI is Tkinter). The Tkinter Fighter Profile screen (`src/ui/screens/fighter_profile.py`) shows fight_history. If it shows per-round details or fight_beats data, that's the "replay" the user means.

**Fix:** Audit the Fighter Profile fight history display. Remove any per-round/beat detail view. Show ONLY: result (W/L/D), opponent, result type, event, date. No round-by-round breakdown. No fight_beats data in the UI.

### Bug 3: Rivalries show "series is even" for 0-0 fighters
**Investigation:** Found 8/93 active rivalries with `fights_count=0` and `0-0` record. These are `title_rivalry` type — created when two fighters are in the same title picture but haven't fought yet. The UI shows "series is even" which is misleading for fighters who've never fought.

**Fix:** In the rivalries display, check `fights_count`. If 0, show "These two haven't met yet" instead of "series is even." Only show head-to-head records when `fights_count > 0`.

### Bug 4: Finances — Alpha starts with over $1 billion
**Investigation:** The backfill script processed 431 events for Alpha Combat, generating $1.97B in cumulative revenue. This is unrealistic — no MMA promotion has $2 billion in cash.

**Root cause:** The backfill ran `_process_event_finance` for ALL 1,884 historical events, accumulating decades of event revenue into the current cash balance. But these events happened over many years — the cash should have been spent on operating costs, fighter development, venue upgrades, etc. over those years.

**Fix:** Don't backfill finances into current_cash. Instead:
- Set starting cash to realistic values: Major=$50M, Mid=$10M, Small=$2M (the reseed values)
- The backfilled finance_transactions are still useful as historical records (for economic reconciliation W29)
- But `promotions.current_cash` should NOT include accumulated historical revenue
- Reset current_cash to the reseed values after backfill

---

## Part 2: ChatGPT RED Priorities

### Priority 1: Promotion Economics (§7)

ChatGPT says: "Do NOT solve this by simply injecting more cash or lowering thresholds again. Investigate the actual economic model."

**Investigation plan:**
- Audit the full revenue/expense model in `src/finance.py`
- Check: venue costs vs venue capacity vs ticket prices vs attendance
- Check: fighter purse formula (is it too expensive?)
- Check: broadcast revenue (is it too low for major promos?)
- Check: event frequency (are promos running too many events?)
- Target: Major promos should be profitable with good cards, marginal with average cards. Small promos should break even with careful management.

**Model target:**
- Major: revenue $2-5M/event, expenses $1-3M/event, profit $1-2M/event
- Mid: revenue $500K-1M/event, expenses $300-700K/event, profit $200-300K/event
- Small: revenue $100-300K/event, expenses $80-250K/event, profit $20-50K/event

### Priority 2: Memory Resurfacing in Player Gameplay (§6.2)

ChatGPT says: "Create a player-path test that books a rematch between fighters with known historical memory links."

**Plan:**
- Write `scripts/test_player_path_memory.py`:
  1. Set up player promotion
  2. Find two fighters who have fought before (from fight_history)
  3. Book a fight between them via `app_web.Api.book_fight()`
  4. Verify `generate_fight_preview_memory_news` fires
  5. Verify the news item references their history
  6. Advance to the fight date, resolve the fight
  7. Verify post-fight memory links are updated
- Fix any issues found

### Priority 3: Long-Run Performance (§8)

ChatGPT says: "The game must be tested as a decades-long simulation."

**Plan:**
- Run 5-year, 10-year, 20-year, 30-year soaks
- Track: tick duration, DB size, fighter count, fight count, news, memory, rivalries, promo states
- Look for: O(n²) growth, repeated queries in loops, excessive news generation
- Profile each run with cProfile if performance degrades

---

## Part 3: UI/UX Review

### Screen Audit

ChatGPT says: "Prefer a small number of excellent information surfaces over many mediocre screens."

**Current screens (Tkinter):**
1. Dashboard — cash, champion, roster, news, next event
2. Roster — fighter list with attributes
3. Fighter Profile — full fighter details
4. Free Agents — unsigned fighters
5. Scouting — assign scouts
6. Save/Load — save game

**Missing screens (referenced in code but may not exist):**
- Rankings
- Titles
- Rivalries
- Calendar/Events
- Matchmaking/Event Builder
- Fight Night
- Finance
- Contracts/Deals
- Staff
- Hall of Fame
- Archive

**Audit each screen for:**
1. What data is shown?
2. Where does it come from? (DB direct, interpretation layer, EventBus)
3. Is it performant? (queries per refresh)
4. Does it use voice phrases or raw numbers?
5. Does it answer "why should I care?"

### Attribute Colour Scheme

**User request:** "Fighter attributes need a standard colour scheme for bad>good>excellent attributes."

**Plan:**
- Define colour bands matching the voice tiers:
  - 0-24: Red (poor/abysmal)
  - 25-39: Orange (limited)
  - 40-59: Yellow (average)
  - 60-74: Light Green (capable)
  - 75-89: Green (strong/elite)
  - 90-100: Gold (elite/special)
- Apply to all attribute displays in Fighter Profile, Roster, Scouting
- Use Tkinter tag colours or CSS if web UI

---

## Part 4: Player Attachment Phase (ChatGPT §11-14)

### Dashboard Redesign (§13)

ChatGPT says: "The dashboard should behave like a sports newsroom and strategic command centre."

**Target hierarchy:**
1. Current date + "Why should I press Advance Day?"
2. Major story of the day (LEGENDARY/MAJOR news)
3. Your promotion status (cash, roster, next event)
4. Your important fighters (watchlist — prospects, champions, fighters on losing streaks)
5. Upcoming fights/events (countdown)
6. Things that changed since last visit (echoes, new signings, injuries, retirements)
7. Threats/problems (rival promo signings, financial warnings, aging champions)
8. Major world stories (title changes, upsets, HoF)

### Player Watchlist (§12)

**Smallest possible mechanism:**
- Add a `player_watchlist` table (fighter_id, added_date, reason)
- OR: use `player_decisions` table (already tracks signings, cuts, scouting — derive watchlist from this)
- Surface on Dashboard: "Your Watched Fighters" section
- Auto-add: fighters the player signed, scouted, or booked
- Auto-surface: when a watched fighter wins/loses/retires/changes gym

### Interpretation Layer Push (§14)

ChatGPT says: "Never expose raw simulation values unless they are intentionally part of a scouting/analysis screen."

**Audit:**
- Find all places where raw numbers are shown in the UI
- Replace with voice phrases where appropriate
- Keep raw numbers ONLY on: Scouting Report (after scout assignment), Fighter Profile attributes (for players who want detail)

---

## Part 5: Implementation Order

### Phase 1: Bug Fixes (1-2 days)
1. Fix Deals/Contracts screen query
2. Remove fight replay/round-by-round from UI
3. Fix rivalries 0-0 display ("haven't met yet")
4. Reset promotion cash to realistic values (undo backfill accumulation)

### Phase 2: Economics + Memory (2-3 days)
5. Audit + tune promotion economics model
6. Write + run player-path memory resurfacing test
7. Fix any memory resurfacing issues found

### Phase 3: UI/UX (3-4 days)
8. Audit all screens (data source, performance, voice vs numbers)
9. Implement attribute colour scheme
10. Redesign Dashboard hierarchy
11. Add player watchlist (minimal)

### Phase 4: Long-Run Validation (2-3 days)
12. Run 5-year soak
13. Run 10-year soak
14. Run 20-year soak
15. Run 30-year soak (sampled)
16. Profile + fix any performance issues

### Phase 5: Polish (1-2 days)
17. Push interpretation layer (raw numbers → voice phrases)
18. Final README + docs update
19. Final sim + analysis

---

## What we're NOT doing (per ChatGPT §24)
- ❌ More attributes
- ❌ More staff types
- ❌ More database tables (unless required)
- ❌ More screens that expose raw data
- ❌ Exact real-world MMA statistical replication
- ❌ Large new subsystems
- ❌ Architecture rewrite
- ❌ Schema changes without explicit approval

---

## ChatGPT Directive Assessment

ChatGPT's directive is **mostly correct** and aligns with our direction. Key points where I disagree or add nuance:

1. **"Stop expanding the foundation"** — AGREE. We have enough systems. Now surface them.
2. **"Do not overfit to real MMA statistics"** — AGREE. KO 23% vs 30% is close enough. The player won't notice.
3. **"Memory resurfacing success = visible recognition, not storage"** — AGREE. We have 4,429 links but 0 resurfacing news in the sim. Need player-path verification.
4. **"Promotion economics — don't just inject cash"** — AGREE. Need to fix the actual revenue/expense model.
5. **"Dashboard = sports newsroom"** — AGREE. Current dashboard is a database homepage.
6. **"Player watchlist — smallest possible mechanism"** — AGREE. Use existing player_decisions data, not a new table.
7. **"Attribute colour scheme"** — User request, not in ChatGPT directive. Adding it.
8. **"Remove fight replay"** — User request. The fight_beats/rounds data exists in DB but shouldn't be shown in UI.

One area where ChatGPT is **too cautious**: it says "no schema changes unless explicitly approved." The rivalries 0-0 fix may need a UI-only change (no schema). The watchlist can use existing tables. So this is fine — we can do everything without schema changes.
