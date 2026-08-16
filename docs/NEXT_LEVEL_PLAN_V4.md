# CAGE EMPIRE — Next Level Development Plan (v6 — CORRECTED)

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Sources:** ChatGPT Post-Review Development Directive + user feedback + thorough UI investigation

---

## CRITICAL CORRECTION

### What I got wrong

I was confused about the UI architecture. Here's the ACTUAL situation:

**The project DID move away from Tkinter.** The migration from CustomTkinter to pywebview was **approved and completed** (per `docs/UI_MIGRATION_PYWEBVIEW.md`). The current UI is:

- **`src/app_web.py`** — 14,896-line pywebview desktop application with 162 API methods
- **`src/web/`** — 24 FULLY IMPLEMENTED JavaScript screens (17,260 lines total)
- **pywebview creates a NATIVE DESKTOP WINDOW** — it's NOT a web app. The user sees a native Windows window with HTML/CSS/JS rendering inside it.

**ALL 24 screens are implemented:**
1. Dashboard (739 lines), 2. Roster (443), 3. Fighter Profile (969), 4. Free Agents (970), 5. Scouting (731), 6. Calendar (514), 7. Event Builder (1,269), 8. Fight Night (1,410), 9. Matchmaking (2,178), 10. The Wire/news (380), 11. Rankings (396), 12. Titles (341), 13. Rivalries (475), 14. Hall of Fame (341), 15. Records (250), 16. Archive (555), 17. Finance (523), 18. Contracts (608), 19. Rival Promotions (484), 20. Gyms (704), 21. Agent Offers (417), 22. Staff Market (721), 23. Save/Load (in app.js), 24. Promotion Select (in app.js)

**The ONLY problem: PLAY.bat launches the WRONG file.**

`PLAY.bat` runs `python src/app.py` (the OLD Tkinter app). It should run `python src/app_web.py` (the pywebview desktop app).

The old Tkinter `src/app.py` still exists because it re-exports functions used by tests + tick_processor. But it should NOT be the entry point.

### What the user is actually seeing

The OLD Tkinter app with:
- Basic three-pane layout
- A "Contracts" tab (the "Deals" screen with errors — wrong query for the reseeded DB)
- A Rankings tab
- Basic buttons (Advance Day, Resolve Fight, Refresh)
- NO redesigned screens, NO voice phrases, NO interpretation layer

When the user says "we moved away from Tkinter" — they're right. The code was migrated. But the launcher was never updated.

---

## The user's reported bugs — CORRECTED analysis

### Bug 1: "Deals" screen has errors
**Location:** The OLD Tkinter app's Contracts tab (`src/app.py` line 670+).
**Why:** The query references old schema columns. The reseed changed the data.
**Fix:** Update PLAY.bat to launch `src/app_web.py`. The web UI's Contracts screen (608 lines, fully implemented) handles this correctly via the API.

### Bug 2: Historical fights have "replay" option
**Location:** The web UI's Fight Night screen (`src/web/js/fight_night.js`).
**What I found:** Fight Night has TWO modes:
- `live` mode: resolves a fight in real-time, showing beats one by one
- `replay` mode: reads existing fight_beats from the DB and replays them beat-by-beat

The replay mode IS a feature of the web UI. When a player clicks on a resolved fight, it enters `replay` mode and shows the beat-by-beat animation. The user wants this REMOVED — no replay, just results.

**Fix:** In `fight_night.js`, remove the `replay` mode. When a fight is already resolved, show ONLY the result (winner, loser, method, round, time) — no beat-by-beat animation. The `live` mode (for currently-resolving fights) can stay — that's the player watching their event in real-time.

### Bug 3: Rivalries show "series is even" for 0-0
**Location:** The web UI's Rivalries screen (`src/web/js/rivalries.js`).
**What I found:** The screen displays `riv.head_to_head` which is a string like "6-2-0". For rivalries with `fights_count=0`, this shows "0-0-0" which looks like "series is even."

**Fix:** In `rivalries.js`, check `riv.fights_count`. If 0, display "Haven't met yet" instead of the head-to-head record. If >0, show the actual record.

### Bug 4: Finances — Alpha has $1B+
**Root cause:** The backfill script accumulated decades of event revenue into `current_cash`.
**Fix:** Reset `current_cash` to realistic values after backfill (Major=$50M, Mid=$10M, Small=$5M). The finance_transactions remain as historical records.

---

## Revised Plan

### Phase 1: Fix the launcher + cleanup (1 hour)
1. Update `PLAY.bat`: `src\app.py` → `src\app_web.py`
2. Update `run.sh`: `src/app.py` → `src/app_web.py`
3. Add `pywebview` to requirements.txt + PLAY.bat pip install line
4. Reset promotion cash to realistic values
5. Test: game launches with the pywebview desktop UI

### Phase 2: Fix user-reported bugs (1-2 days)
6. Remove `replay` mode from Fight Night (show results only for resolved fights)
7. Fix Rivalries 0-0 display ("Haven't met yet")
8. Fix any errors in the Contracts/Deals screen (verify the API method works)
9. Remove fight_beats + fight_rounds writes for AI vs AI fights (already done — verify)
10. Consider removing fight_beats + fight_rounds writes for PLAYER fights too (user said no replay needed)

### Phase 3: Economics + memory (2-3 days)
11. Audit + tune promotion economics (venue costs, purses, ticket revenue)
12. Write player-path memory resurfacing test
13. Fix any memory issues

### Phase 4: UI/UX polish (3-4 days)
14. Implement attribute colour scheme (CSS in web UI — easy)
15. Audit all 24 screens for data source + performance + voice vs numbers
16. Dashboard redesign (newsroom hierarchy per ChatGPT §13)
17. Add player watchlist (minimal — use existing player_decisions data)

### Phase 5: Long-run validation (2-3 days)
18. Run 5-year, 10-year, 20-year soaks
19. Profile + fix bottlenecks
20. Final analysis + docs

---

## ChatGPT Directive Assessment (CORRECTED)

ChatGPT's directive is **excellent and correct**. Key points:

1. **"Stop expanding the foundation"** — AGREE. We have 24 screens, 162 API methods, 80K fight history, 15 memory types, rival AI with memory. Enough systems. Surface them.
2. **"Do not overfit to real MMA statistics"** — AGREE. KO 28.6% is close enough.
3. **"Memory resurfacing success = visible recognition"** — AGREE. Need player-path test.
4. **"Promotion economics — don't just inject cash"** — AGREE. Fix the model.
5. **"Dashboard = sports newsroom"** — AGREE. The web Dashboard (739 lines) needs redesign.
6. **"Player watchlist — smallest possible mechanism"** — AGREE.
7. **"Remove fight replay"** — User request. The web Fight Night has replay mode — remove it.
8. **"Attribute colour scheme"** — User request. Easy in CSS.

The biggest issue ChatGPT didn't know about: **the launcher points to the wrong file.** The player has never seen the actual game UI. Fixing this is Priority #1.
