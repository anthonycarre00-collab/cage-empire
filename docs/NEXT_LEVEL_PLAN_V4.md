# CAGE EMPIRE — Next Level Development Plan (v7 — FULLY CORRECTED)

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Sources:** ChatGPT Post-Review Development Directive + thorough UI audit + user feedback + verified DB state

---

## CORRECTION: The UI IS working correctly

### What I got wrong (twice)

1. **First time:** I said the launcher was broken (PLAY.bat launches old Tkinter). **WRONG.** `src/app.py`'s `__main__` block delegates to `app_web.main()` — the pywebview desktop app IS what the player sees.
2. **Second time:** The subagent I hired said the same thing. **ALSO WRONG** — it didn't read the `__main__` block.

### The verified truth

- **PLAY.bat** runs `python src/app.py` → `src/app.py __main__` calls `from app_web import main as _web_main; _web_main()` → **pywebview desktop app launches with all 24 screens.**
- The user IS seeing the pywebview UI. The old Tkinter `class App(tk.Tk)` in `src/app.py` is dead code — it never runs.
- **ALL 24 web screens are fully implemented** (17,260 lines of JS, 162 API methods in `app_web.py`).
- **The launcher is NOT broken.** I wasted time on a non-issue.

### What IS actually broken (verified against DB)

The audit found **5 DATA bugs** (not code bugs) that affect what the player sees:

| # | Bug | Root cause | Verified |
|---|---|---|---|
| 1 | **fight_beats, fight_rounds, commentary_segments ALL EMPTY** (0 rows each, despite 1,747 resolved fights) | The beat engine exists but isn't wired into `resolve_next_fight` for the pre-seeded fights. New sim fights DO write beats (for player fights) but the pre-seeded 1,747 fights have none. | ✅ Confirmed: 0 rows in all 3 tables |
| 2 | **news_items only has `topic='finance'`** (1,884 rows, ALL finance) | The backfill script (`backfill_finance_transactions.py`) wrote finance news for every event. No other news was generated for the pre-seeded events. | ✅ Confirmed: 1,884 rows, all topic='finance' |
| 3 | **rivalries counter drift** — 86/343 rivalries show "0-0" despite fights_count>0 | `fights_count` gets incremented but `fighter_a_wins/fighter_b_wins/draws` aren't reconciled when fights resolve. | ✅ Confirmed: 86 rivalries with fights_count>0 but 0-0 |
| 4 | **show_ratings EMPTY** (0 rows) | Show ratings only fire during sim, not for pre-seeded events. | ✅ Confirmed: 0 rows |
| 5 | **hall_of_fame EMPTY** (0 rows) | HoF only fires on retirement during sim, not for pre-seeded fighters. | ✅ Confirmed: 0 rows |

Plus 3 **code bugs** in the web UI:

| # | Bug | Location | Fix |
|---|---|---|---|
| 6 | **$1B+ cash displays as "$1968.3M"** | `_format_cash()` in `app_web.py` + 7 JS `formatCash()` helpers — no Billion branch | Add `if abs(cash) >= 1e9: return f"${cash/1e9:.2f}B"` |
| 7 | **Fight Night replay mode** reads fight_beats (which are empty) | `fight_night.js` has `state.mode='replay'` with beat-by-beat animation | Remove replay mode (~80 LOC) OR fix beat engine to populate data |
| 8 | **31% of fighters missing descriptors** | `fighter_descriptors` has 4,450 rows but DB has 6,450 fighters (2,000 grey-name fighters don't need them, but some real fighters may be missing) | Run `refresh_fighter` for all active fighters |

### User-reported bugs — CORRECTED analysis

1. **"Deals" screen errors** — The web Contracts screen (`contracts.js` → `get_contracts_data`) works correctly (verified: returns 60 active fighter contracts + 11 staff contracts). The user may have seen errors from the finance news spam (1,884 finance news items) or from the $1B cash display. **Need to verify by actually running the screen.**

2. **"Replay" option** — CONFIRMED. `fight_night.js` has a `replay` mode with beat-by-beat animation. When the user clicks on a resolved fight, it enters replay mode and tries to read fight_beats (which are empty, so it skips to recap). The "↻ Replay" button is visible in the recap. User wants this REMOVED.

3. **"Rivalries series is even" for 0-0** — CONFIRMED. 86 rivalries show "0-0" despite having `fights_count>0`. The win/loss/draw counters aren't reconciled. The display shows "0-0" which looks like "series is even."

4. **"$1B+ cash"** — CONFIRMED. Alpha Combat has $1,968,269,335. The backfill accumulated decades of event revenue. Displays as "$1968.3M" because `_format_cash()` has no Billion branch.

---

## ChatGPT Directive — Re-assessed with correct understanding

Now that I understand the UI IS working, ChatGPT's directive makes more sense:

1. **"Stop expanding the foundation"** — AGREE. 24 screens, 162 API methods, all implemented. The foundation is built. Now make it meaningful.

2. **"Fix world-simulation correctness issues"** — AGREE. The 5 data bugs (empty fight_beats, finance-only news, rivalry counter drift, empty show_ratings, empty HoF) are correctness issues that break immersion.

3. **"Fix promotion economics"** — AGREE. $1B+ cash is unrealistic. Need to reset to realistic values.

4. **"Memory resurfacing in player gameplay"** — AGREE. Need to verify it fires when the player books fights.

5. **"Dashboard = sports newsroom"** — AGREE. But the dashboard is already 739 lines of JS. It needs redesign, not implementation.

6. **"Attribute colour scheme"** — ALREADY EXISTS. The audit found that `fighter_profile.js` already has a 3-tier colour scheme (gold for elite, crimson for weak, steel for default). The user may not have noticed because 31% of fighters are missing descriptors.

7. **"Remove fight replay"** — User request. The replay mode in `fight_night.js` should be removed. Show results only for resolved fights.

8. **"Do not overfit to MMA statistics"** — AGREE. KO 28.6% is close enough.

---

## Corrected Plan (v7)

### Phase 1: Fix DATA bugs (1-2 days)

These are the highest priority because they break immersion:

1. **Reconcile rivalry counters** — write a script that recomputes `fighter_a_wins`, `fighter_b_wins`, `draws`, `fights_count` from `fight_history` for every rivalry. This fixes the "0-0" display.

2. **Reset promotion cash** — set `current_cash` to realistic values:
   - Major: $50M, Mid: $10M, Small: $5M
   - Keep the finance_transactions as historical records
   - This fixes the "$1968.3M" display

3. **Backfill show_ratings** — write a script that computes show ratings for the 1,884 pre-seeded events (based on fight results, card quality, attendance). This fixes the Archive "unrated" display.

4. **Backfill hall_of_fame** — write a script that inducts eligible retired fighters based on career criteria (title reigns, win records, milestones). This fixes the HoF empty state.

5. **Backfill non-finance news** — write a script that generates fight result news, signing news, retirement news, etc. for the pre-seeded events. This fixes the Wire showing only finance news.

6. **Backfill fighter_descriptors** — run `refresh_fighter` for all active fighters missing descriptors. This fixes the 31% missing attribute/personality displays.

### Phase 2: Fix CODE bugs (1 day)

7. **Add Billion branch to `_format_cash()`** — one line in `app_web.py` + one line in each of 7 JS files.

8. **Remove fight replay mode** — remove `state.mode='replay'`, the replay button, and the beat-by-beat animation from `fight_night.js`. When a fight is already resolved, show ONLY the result (winner, loser, method, round, time, performance rating). ~80 LOC removal.

9. **Fix rivalries 0-0 display** — in `rivalries.js`, when `fights_count=0` OR (`fights_count>0` AND all win/draw counters are 0), show "Haven't met yet" instead of "0-0".

### Phase 3: Economics + memory (2-3 days)

10. **Audit + tune promotion economics** — investigate venue costs, purses, ticket revenue, broadcast revenue. Target: Major profitable with good cards, small promos break even.

11. **Player-path memory resurfacing test** — book a rematch between fighters with history, verify `generate_fight_preview_memory_news` fires, verify the player sees it in the Wire.

### Phase 4: UI/UX polish (3-4 days)

12. **Dashboard redesign** — restructure the dashboard per ChatGPT §13 (sports newsroom hierarchy: today's story → promotion status → important fighters → upcoming → what changed → threats → opportunities → world stories).

13. **Player watchlist** — minimal implementation using existing `player_decisions` data. Surface watched fighters on the dashboard.

14. **Screen audit** — review all 24 screens for voice vs raw numbers, performance, data freshness. The audit found voice compliance is GOOD but some screens may need tweaking.

15. **Attribute colour scheme verification** — the 3-tier scheme (gold/crimson/steel) already exists. Verify it renders correctly after the descriptor backfill.

### Phase 5: Long-run validation (2-3 days)

16. **Run 5-year, 10-year, 20-year soaks** — track all metrics, profile bottlenecks.
17. **Final analysis + docs** — update README, CURRENT_SYSTEM_STATE, 1YR_SIM_ANALYSIS.

---

## What we're NOT doing
- ❌ NO launcher fix (it's NOT broken — app.py delegates to app_web.py)
- ❌ NO web UI removal (it IS the UI — pywebview desktop app)
- ❌ NO new screens (all 24 are implemented)
- ❌ NO new schema/tables
- ❌ NO architecture rewrite
- ❌ NO fight replay (removing it, not building it)

## Performance notes

The audit found NO performance concerns in the web UI:
- All list screens use LIMIT/OFFSET pagination (20/page)
- No unbounded queries
- Minor N+1 patterns (matchmaking rank subquery, rivalry fighter stage) are acceptable for N<20
- All queries reference existing columns (no schema mismatches)

The sim performance is stable:
- 365-day sim completes in ~7 minutes (337ms avg tick)
- No super-linear growth
- All pruned tables stay bounded
