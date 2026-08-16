> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Navigation, Buttons & Save/Load Audit

> **Task ID:** NAV-BUTTONS-AUDIT
> **Mode:** RESEARCH ONLY. No code was changed.
> **Date:** 2026-08-02 (sim)
> **Scope:** The 4 rebuilt screens (Dashboard, Roster, Free Agents, Fighter Profile)
>   + the Python API bridge (`src/app_web.py`) + JS navigation layer
>   (`src/web/js/app.js`, `dashboard.js`, `bridge.js`) + save/load
>   (`src/save_load.py`).
> **Sources audited:**
>   - `docs/GUI_PLAN.md` §6 (screen specs), §10.3 (button variants)
>   - `src/app_web.py` (Python `Api` class — 778 lines)
>   - `src/web/js/app.js` (navigation, sidebar, pre-game, Advance Day)
>   - `src/web/js/dashboard.js` (Dashboard renderer + hyperlink wiring)
>   - `src/web/js/bridge.js` (JS↔Python call wrapper)
>   - `src/web/index.html` (shell markup)
>   - `src/services/contracts.py` (`sign_free_agent` only)
>   - `src/save_load.py` (save/load/auto-save)
>   - `src/ui_legacy/state.py` (reference for back-stack design)
>   - `src/ui_legacy/screens/screens/fighter_profile.py` (reference for
>     cut/book/scout UI patterns)

---

## 1. Navigation Map

### 1.1 Sidebar (defined in `src/web/js/app.js` `NAV_GROUPS`)

The sidebar has **5 groups × 19 items** (matches GUI_PLAN §4.9 after
the "Settings/Save-Load/Mods → top-bar kebab" move). Fighter Profile
is intentionally NOT in the sidebar (per §10.3 — "Fighter Profile is a
destination, not a starting point").

| Group | Items |
|---|---|
| HOME (3) | dashboard, schedule, news |
| FIGHTERS (4) | roster, free_agents, scouting, hall_of_fame |
| EVENTS (4) | event_builder, matchmaking, fight_resolution, past_events |
| BUSINESS (4) | finance, contracts, rival_promotions, gyms |
| WORLD (4) | rankings, titles, rivalries, records |

Only **dashboard** is implemented (renders via `window.CE.dashboard.loadAndRender`).
The other 18 fall through to the placeholder renderer in `app.js:navigate()`
(lines 256-275), which shows a `ce-placeholder` div with a voice-phrased
title/body from `PLACEHOLDER_PHRASES`. None of the placeholders carry an
action button — they are read-only.

### 1.2 Per-screen navigation

| Screen | Hyperlinks in (sources) | Hyperlinks out (targets) | Nav buttons | Back-nav flow |
|---|---|---|---|---|
| **Dashboard** | Top Story (1, optional), Fighter Watch cards (3), Champions strip (≤8), Recent News list (≤5, optional) | All should resolve to Fighter Profile by `fighter_id` | Advance Day (top bar, wired), Build Card (placeholder, NOT rendered), Matchmaking (placeholder, NOT rendered) | Sidebar item → previous screen (no JS back-stack) |
| **Roster** | Row name (hyperlink, per §6.2) | Fighter Profile | View Profile (Secondary), Weight-class dropdown, Gender dropdown, Stage dropdown, Search box (200ms debounce), Clear Filters (Ghost), Prev/Next pagination | Sidebar → previous; double-click row → Fighter Profile |
| **Free Agents** | Row name (hyperlink) | Fighter Profile | Sign Fighter (Primary, sticky bottom bar), filters (WC/Gender/Stage/Search), pagination | Sidebar → previous; double-click row → Fighter Profile |
| **Fighter Profile** | Opponent names in Recent Fights timeline | Fighter Profile (re-nav with new fighter_id) | Cut Fighter (Danger, if on roster), Offer Extension (Secondary, if contract expiring), Book Next Fight (Secondary), Scout (Primary, if NOT on roster), "Show all 26 attributes" toggle, TabBar (Overview/Attributes/Personality/Career/Fights/News), Back button | Back button → previous screen |

### 1.3 Broken links / missing navigation paths

| # | Issue | Severity | Where |
|---|---|---|---|
| **B1** | **Dashboard fighter-name hyperlinks are dead.** `dashboard.js:render()` lines 419-429 wire click handlers, but the handler only `console.log`s the `fighter_id` — there is no `navigate('fighter_profile', {fighter_id})` call. The "View X →" link in Top Story, the gold name in WatchCards, champion chips, and Recent News headlines are all visually hyperlinks but functionally inert. | **P0 BLOCKER** | `dashboard.js:419-429` |
| **B2** | **No Fighter Profile screen exists.** `app.js:navigate()` has no `fighter_profile` case, and there's no `fighter_profile.js` module in `src/web/js/`. Roster/Free Agents have no destination to navigate to. | **P0 BLOCKER** | `src/web/js/` (file missing) |
| **B3** | **No navigation back-stack.** The legacy CTk app had `GameState._nav_stack` (cap 10, FIFO overflow) in `src/ui_legacy/state.py:92`. The pywebview `app.js` has `state.activeScreen` only — `navigate()` is one-way. Fighter Profile's Back button has no stack to pop. | **P1 HIGH** | `app.js:246-275` |
| **B4** | **`navigate()` takes no parameters.** Signature is `navigate(screenId)` — there's no way to pass `fighter_id` to Fighter Profile or `event_id` to Past Events. Hyperlinks cannot target a specific entity. | **P1 HIGH** | `app.js:246` |
| **B5** | **Roster and Free Agents screens not implemented in JS.** `app.js:navigate()` falls through to the placeholder for both. The bridge methods `getRosterData` / `getFreeAgents` exist but the Python side returns `{placeholder: True, message: "..."}` (`app_web.py:624-649`). No row-click, no double-click, no Sign button, no View Profile button. | **P0 BLOCKER** | `app_web.py:624-649` + missing `roster.js` / `free_agents.js` |
| **B6** | **No Roster↔Free Agents cross-link.** GUI_PLAN §6.2 specifies a "Browse Open Market" CTA in the Roster empty state, and Free Agents' Sign flow should return to Roster. Neither path exists. | P2 MEDIUM | n/a |
| **B7** | **Dashboard "Build Card" and "Matchmaking" buttons not rendered.** §6.1 specifies them in the Next Event card. The Dashboard renderer (`dashboard.js:renderNextEvent`) renders only the event date/name — no buttons. | P1 HIGH | `dashboard.js:225-243` |
| **B8** | **No Breadcrumb component.** §10.3 specifies breadcrumbs ("The Stable / John Vale"). The shell has no breadcrumb host in `index.html`. | P2 MEDIUM | `index.html` |
| **B9** | **Top-bar kebab menu (Save/Settings/Mods) missing.** §4.9 + §10.3 specify a ⚙ ghost button that opens a dropdown. The top bar in `index.html:46-57` has only logo + date + cash + Advance Day button. Save/Load is only reachable programmatically (`bridge.saveGame` / `loadGame`) — there's no UI affordance. | P1 HIGH | `index.html:46-57` |

---

## 2. Action Buttons / Levers per Screen

### 2.1 Dashboard

| Button / Lever | Per §6.1 / §10.3 | Status in rebuild | API method needed |
|---|---|---|---|
| **Advance Day** | Primary (gold), top bar | ✅ WIRED. `app.js:wireAdvanceDay()` (lines 192-211) calls `bridge.advanceDay()` → `api.advance_day()` → `services.clock.advance_day(self.conn)`. Top-bar date + cash refresh via `updateTopBar()`. If activeScreen is dashboard, `dashboard.loadAndRender(promoId)` re-fetches. Button disables during call. | `advance_day` ✅ exists |
| **Build Card** | Primary, in Next Event card | ❌ NOT RENDERED. `renderNextEvent` (dashboard.js:225-243) only shows date + promo name + event name. | `navigate('event_builder')` — needs nav param support |
| **Matchmaking** | Secondary (outline), in Next Event card | ❌ NOT RENDERED. | `navigate('matchmaking')` |
| **Fighter name hyperlinks** (Top Story, Watch Cards, Champions, News) | HyperlinkLabel (gold, gold_bright hover, 1px underline on hover) | ⚠️ RENDERED as `<a class="ce-link" data-fighter-id="...">` but the click handler only `console.log`s (dashboard.js:419-429). | Needs `navigate('fighter_profile', {fighter_id})` (see B4) |
| **Read full story** link on Top Story | HyperlinkLabel | ⚠️ RENDERED as `fighterLink` only if `ts.fighter_name` exists (dashboard.js:152-155). Same dead-click issue. | Same as above |

**Count: 5 distinct action affordances. 1 wired, 4 missing/broken.**

### 2.2 Roster

| Button / Lever | Per §6.2 | Status | API method needed |
|---|---|---|---|
| Row single-click → select | FighterRow, gold left border | ❌ NOT IMPLEMENTED (no `roster.js`) | n/a (JS-only) |
| Row double-click → Fighter Profile | HyperlinkLabel + dblclick | ❌ NOT IMPLEMENTED | `navigate('fighter_profile', {fighter_id})` |
| View Profile button | Secondary, opens Fighter Profile for selected row | ❌ NOT IMPLEMENTED | Same as above |
| Weight-class filter dropdown | UI label, all weight classes | ❌ NOT IMPLEMENTED | `get_roster_data(promo_id, page, {wc, gender, stage, search, sort})` — needs filter params wired |
| Gender filter dropdown | UI label (Men/Women/All) | ❌ NOT IMPLEMENTED | Same |
| Stage filter dropdown | UI label (career_phase buckets) | ❌ NOT IMPLEMENTED | Same |
| Search box | 200ms debounce (already shipped in legacy Phase 4) | ❌ NOT IMPLEMENTED in rebuild | Same |
| Clear Filters button | Ghost (×) | ❌ NOT IMPLEMENTED | JS-only |
| Pagination prev/next | Page numbered, gold current | ❌ NOT IMPLEMENTED | `get_roster_data(promo_id, page, ...)` ✅ accepts page |
| Sort by column header | Click header → sort asc/desc | ❌ NOT IMPLEMENTED | `get_roster_data(..., {sort_col, sort_dir})` |
| Browse Open Market CTA (empty state) | Secondary, navigates to Free Agents | ❌ NOT IMPLEMENTED | `navigate('free_agents')` |
| Weight Class Distribution viz | Horizontal bar chart (data viz requirement) | ❌ NOT IMPLEMENTED | Aggregate `COUNT(*) GROUP BY weight_class_id` — new query in `get_roster_data` |

**Count: 12 distinct action affordances. 0 wired. The Python `get_roster_data` is a STUB returning `{placeholder: True}` (app_web.py:624-632).**

### 2.3 Free Agents

| Button / Lever | Per §6.4 | Status | API method needed |
|---|---|---|---|
| Row single-click → select (updates sign bar) | FighterRow + sticky bottom bar | ❌ NOT IMPLEMENTED | n/a |
| Row double-click → Fighter Profile | HyperlinkLabel + dblclick | ❌ NOT IMPLEMENTED | `navigate('fighter_profile', {fighter_id})` |
| **Sign Fighter button** | Primary, sticky bottom bar | ❌ NOT IMPLEMENTED | **`sign_free_agent(fighter_id, promotion_id, start_date, salary)`** — exists in `services/contracts.py` but NOT exposed on `Api` |
| Estimated cost display | In sticky sign bar | ❌ NOT IMPLEMENTED | Cost formula not defined. Legacy used flat `DEFAULT_SIGNING_SALARY = 50000.0` (free_agents.py:260). §6.4 specifies "based on ceiling, age, momentum, market" — needs new derivation function |
| Ceiling column | Voice phrase ("Elite" / "High" / "Above-Avg" / "Avg" / "Below-Avg" / "Low" / "Unknown"). Unscouted = "????" | ❌ NOT IMPLEMENTED | Reads `fighter_descriptors.legacy_state` or a new `ceiling` field — TBD |
| Scouting report display | Card/Flat below header on Profile, not on Free Agents list | (Defer to Fighter Profile) | `get_scouting_report(fighter_id)` — **MISSING** |
| Sign confirmation ModalDialog | 8px radius, slide-in 150ms | ❌ NOT IMPLEMENTED | JS-only |
| Filters (WC/Gender/Stage/Search) | Same as Roster | ❌ NOT IMPLEMENTED | `get_free_agents(page, filters)` — Python stub returns placeholder |
| Pagination | 20 rows/page | ❌ NOT IMPLEMENTED | `get_free_agents(page, ...)` ✅ accepts page |
| Talent Pool by Ceiling viz | Horizontal bar chart | ❌ NOT IMPLEMENTED | Aggregate query — new |

**Count: 10 distinct action affordances. 0 wired. `sign_free_agent` exists in services but is NOT exposed on the `Api` class — that's the single most critical missing bridge.**

### 2.4 Fighter Profile

| Button / Lever | Per §6.3 | Status | API method needed |
|---|---|---|---|
| **Cut Fighter button** | Danger (crimson), if `current_promotion_id == player_promotion_id` | ❌ NOT IMPLEMENTED | **`cut_fighter(fighter_id)` → releases fighter, sets `current_promotion_id=NULL`, voids active contract** — MISSING (no such function in `src/services/`) |
| **Offer Extension button** | Secondary, if contract `end_date` within 90 days | ❌ NOT IMPLEMENTED | **`offer_extension(fighter_id, new_end_date, new_salary)`** — MISSING |
| **Book Next Fight button** | Secondary, navigates to Matchmaking with fighter_id pre-filled | ❌ NOT IMPLEMENTED | `navigate('matchmaking', {fighter_id})` — needs nav params |
| **Scout button** | Primary, if `current_promotion_id != player_promotion_id` | ❌ NOT IMPLEMENTED | **`send_scout(fighter_id, scout_id?)`** — MISSING |
| Tab navigation | TabBar (6 tabs per §6.3 + Q12 recommended A) | ❌ NOT IMPLEMENTED | JS-only |
| "Show all 26 attributes" toggle | Ghost toggle in Attributes tab | ❌ NOT IMPLEMENTED | JS-only; data already in `fighter_attributes` (joined via `get_fighter_profile`) |
| Opponent name hyperlinks (Recent Fights) | HyperlinkLabel, gold | ❌ NOT IMPLEMENTED | `navigate('fighter_profile', {fighter_id: opponent_id})` |
| Back button | Ghost "← Back" at top | ❌ NOT IMPLEMENTED | Needs nav back-stack (see B3) |
| Replay fight link (▶ ghost) | On each Recent Fights row | ❌ NOT IMPLEMENTED (P1 future) | `navigate('fight_resolution', {fight_id})` |

**Count: 9 distinct action affordances. 0 wired. 4 of them need new Python API methods that don't exist anywhere in `src/`.**

---

## 3. Python API Methods Needed

### 3.1 Existing API methods (`app_web.py:Api`)

| Method | Purpose | Used by | Status |
|---|---|---|---|
| `get_clock()` | Top-bar date | app.js | ✅ Works |
| `get_player_promotion()` | Determine player's promo | app.js init | ✅ Works |
| `select_promotion(id)` | Pre-game screen | app.js pre-game | ✅ Works |
| `get_player_cash()` | Top-bar cash | app.js | ✅ Works |
| `get_promotion_list()` | Pre-game grid | app.js pre-game | ✅ Works |
| `get_dashboard_data(promo_id)` | Dashboard render | dashboard.js | ✅ Works (returns full 8-section payload) |
| `advance_day()` | Top-bar Advance button | app.js | ✅ Works |
| `get_roster_data(promo_id, page, filters)` | Roster render | (no caller yet) | ⚠️ STUB returns placeholder |
| `get_fighter_profile(fighter_id)` | Fighter Profile render | (no caller yet) | ⚠️ STUB returns placeholder |
| `get_free_agents(page, filters)` | Free Agents render | (no caller yet) | ⚠️ STUB returns placeholder |
| `list_saves()` | Save/Load UI | (no caller yet) | ✅ Works |
| `save_game(name)` | Save/Load UI | (no caller yet) | ✅ Works |
| `load_game(name)` | Save/Load UI | (no caller yet) | ⚠️ See §4.3 — doesn't update `Api.conn` |
| `on_close()` | Window close auto-save | app.js (via webview event) | ✅ Works |
| `set_player_name(name)` | Pre-game name input | app.js pre-game | ✅ Works |
| `get_player_name()` | Pre-game name input | app.js pre-game | ✅ Works |

### 3.2 Missing API methods (must be added to `Api` + bridge.js)

| Method | Service-layer backing | Notes |
|---|---|---|
| **`sign_free_agent(fighter_id)`** | ✅ `services.contracts.sign_free_agent` EXISTS (contracts.py:165). Just needs an `Api` wrapper that auto-fills `promotion_id` (from `get_player_promotion`), `start_date` (from `get_clock`), and `salary` (default 50000 or new cost formula). Publishes `Events.FIGHTER_SIGNED` so news/morale/interpretation subscribers fire. | Trivial wrap. |
| **`cut_fighter(fighter_id)`** | ❌ NO service function exists. Must: set `fighters.current_promotion_id=NULL`, mark active contract `status='terminated'`, publish `Events.FIGHTER_CUT` (new event type — needs adding to `event_bus.Events`), write news item ("X released by Y"). | Medium — new service function. |
| **`offer_extension(fighter_id, new_salary)`** | ❌ NO service function exists. Must: query active contract, compute new `end_date` (start_date + 365d), `UPDATE contracts SET end_date=?, salary=? WHERE contract_id=?`, publish news. | Medium. |
| **`book_fight(fighter_a_id, fighter_b_id, event_id?)`** | ❌ NO service function. Matchmaking screen doesn't exist yet. Defer until Matchmaking rebuild. | Deferred. |
| **`send_scout(fighter_id, scout_id=None)`** | ❌ NO service function. Scouting module exists (`src/scouting.py`) but no "assign scout to fighter" entry point. | Large — needs scouting subsystem review. |
| **`get_scouting_report(fighter_id)`** | Partial — `scouting_reports` table exists, legacy `_build_scouting_section` (fighter_profile.py:1264) reads it. Wrap as `Api` method returning `{scout_name, report_date, confidence_phrase, notes}`. | Small — SQL query + voice-phrase decode. |
| **`navigate_to_screen(screen_id, params)`** | n/a — JS-only. Should be a JS function `navigate(screenId, params)` that updates `state.activeScreen`, pushes to a `_navStack`, and routes to the right renderer. The current `navigate(screenId)` is parameter-less (B4). | JS-side fix. |
| **`search_fighters(query, filters)`** | (Optional) Could be folded into `get_roster_data` / `get_free_agents` via the `filters` dict. Legacy uses 200ms debounce + a `LIKE` query on `first_name || ' ' || last_name`. | Fold into existing stubs. |
| **`get_roster_aggregates(promo_id)`** | New — for the Weight Class Distribution viz. Returns `[{wc_name, count}]`. | Small SQL query. |
| **`get_free_agent_aggregates()`** | New — for the Talent Pool by Ceiling viz. Returns `[{ceiling_tier, count}]`. | Small SQL query. |
| **`estimate_signing_cost(fighter_id)`** | New — derives cost from ceiling, age, momentum, market. §6.4 specifies this as the Empire Builder dopamine hook. Legacy used flat 50000. | Medium — needs derivation formula. |

### 3.3 Bridge gaps (`bridge.js`)

The bridge currently exposes 16 methods. Missing wrappers for: `signFreeAgent`, `cutFighter`, `offerExtension`, `bookFight`, `sendScout`, `getScoutingReport`, `estimateSigningCost`, `getRosterAggregates`, `getFreeAgentAggregates`. Trivial to add — follow the existing `callPython` pattern.

---

## 4. Save/Load Verification

### 4.1 Mechanism

`save_load.py` uses `shutil.copy2(DB_PATH, save_db_path)` — a byte-for-byte
file copy. The DB IS the save state (no serialization). This preserves:
- Every table, every row, every column
- `sqlite_sequence` AUTOINCREMENT counters
- WAL journal state (committed via `conn.commit()` before copy)
- `schema_meta` row (schema version 3.15.0)

### 4.2 Live save/load test — PASS

Ran the audit script (see §"RUN THESE TESTS" in the task brief) against
the live world DB at `data/cage_empire.db`. Results:

```
Before save:    date=2026-08-02, day=103
Saved.
After load:     date=2026-08-02, day=103
Match: True

Player settings before: 7 rows
  news_filter_topics: all
  news_filter_min_importance: 0
  news_volume: normal
  auto_save_frequency: 30
  difficulty: normal
  display_descriptors: true
  event_naming_style: mixed
Player settings after: 7 rows  (all 7 match)

Fighter descriptors: 4464 → 4464  ✅
Events:              1981 → 1981  ✅
news_items:          5287
contracts:           1125
fighters:            4464
schema_meta:         cage_empire / 3.15.0 / 2026-08-02 14:38:55
```

**Verdict: PASS.** Sim clock, player_settings (including difficulty + autosave
cadence), fighter_descriptors (the interpretation cache), events, news_items,
contracts, fighters, and schema_meta all survive save/load intact.

### 4.3 What's NOT preserved (caveats)

| Concern | Preserved? | Notes |
|---|---|---|
| Player's promotion selection (`player_settings.player_promotion_id`) | ✅ YES | Lives in the DB, restored by file copy. `Api.get_player_promotion()` reads it on every call. |
| Player name (`player_settings.player_name`) | ✅ YES | Same. |
| Sim clock (date, day, week, year, tick_counter) | ✅ YES | `simulation_clock` row is in the DB. |
| All 17 event-bus subscribers | ⚠️ PARTIAL | Subscribers are **in-memory** (`event_bus.EventBus._subscribers` dict, `event_bus.py:109`). On `load_game`, the DB is restored but `Api.conn` is NOT swapped — `load_game` in `app_web.py:675-687` calls `_load_game(name)` and discards the returned fresh connection. The original `Api.conn` keeps pointing at the same `DB_PATH` file (which has been overwritten in place by `shutil.copy2` inside `load_game`), so subsequent reads DO see the new state. But: (a) any subscriber with in-memory state (e.g., `news._SOURCE_TONE_PREFIX` cache, `morale` last-seen dicts) keeps its pre-load state until those modules are re-imported; (b) the `interpretation` cache subscriber may not re-fire on next tick if its `last_built_date` check thinks the cache is fresh. |
| In-memory subscriber state | ❌ NOT PRESERVED | `news.py` has module-level dicts (`_SOURCE_TONE_PREFIX`, `_FIGHT_HEADLINES_KO`, etc.) — these are constants so OK. But `morale`, `rival_ai`, `career_arc` may carry per-fighter in-memory caches that survive load. After `load_game`, the safest path is to restart the process or call `reset_bus()` + `register_all_subscribers()` again. |
| `Api.conn` reference after `load_game` | ⚠️ FRAGILE | `Api.load_game` calls `_load_game(str(name))` which overwrites `DB_PATH` in place and returns a NEW connection. `Api` discards the new connection and keeps using `self.conn` (which still points at `DB_PATH`). Because SQLite WAL mode re-reads the file header on each transaction, reads work — but `self.conn`'s open transaction state may be stale. Recommended: after `load_game`, JS should re-navigate to Dashboard and trigger a fresh `getDashboardData` call to force a new transaction. |
| Auto-save on close (`exit_save`) | ✅ YES | `Api.on_close()` calls `save_game(self.conn, "exit_save")` before `self.conn.close()`. Wired via `window.events.closing += _on_closing` in `app_web.py:757`. |
| Monthly auto-save (every 30 sim days) | ✅ YES | `save_load.auto_save` subscriber fires on `TICK_ADVANCED` when `current_day % 30 == 0`. Rotates to keep last 3. |

### 4.4 Save/load issues to flag

1. **`Api.load_game` should swap `self.conn`.** Current code:
   ```python
   def load_game(self, name):
       from save_load import load_game as _load_game
       _load_game(str(name))  # ← discards returned connection!
       return {"ok": True, "name": str(name)}
   ```
   The fresh connection is discarded. `self.conn` keeps pointing at the
   overwritten file. Works for reads (SQLite re-reads WAL) but is fragile.
   **Fix needed:** `self.conn.close(); self.conn = _load_game(str(name))`.
   Then re-register subscribers (`reset_bus()` + `register_all_subscribers()`)
   to clear in-memory caches.

2. **No "load confirmation" UI flow.** `bridge.loadGame` is wired but no
   screen calls it. The Save/Load screen (sidebar item removed in §4.9)
   should appear as a ModalDialog from the top-bar kebab (B9).

3. **No "unsaved changes" warning.** If the player makes changes (signs a
   fighter, advances a day) and tries to load a different save, the
   in-flight changes are silently overwritten. Need a confirmation modal.

---

## 5. Performance Considerations

### 5.1 Refresh cadence per screen

| Screen | When to refresh | When NOT to refresh |
|---|---|---|
| **Dashboard** | On navigation; after every `advanceDay` (auto, via `app.js:wireAdvanceDay`); after `loadGame` | On idle — no polling |
| **Roster** | On navigation; after `signFreeAgent` (refresh list — the signed fighter leaves); after `cutFighter` (refresh list — the cut fighter leaves) | On every Advance Day — the roster rarely changes day-to-day. Use the legacy "stale screen" pattern: mark stale on tick, refresh only when player navigates. |
| **Free Agents** | On navigation; after `signFreeAgent` (refresh — signed fighter leaves); after `sendScout` (update ceiling column from "????" to a phrase) | On every Advance Day — same stale-screen pattern. |
| **Fighter Profile** | On navigation ONLY (with `fighter_id` param) | After Advance Day — the player is reading, not editing. Refresh would reset scroll position + active tab. |

### 5.2 Should Dashboard auto-refresh after Advance Day?

**YES — and it already does.** `app.js:wireAdvanceDay()` lines 200-202:
```javascript
if (state.activeScreen === 'dashboard') {
    return window.CE.dashboard.loadAndRender(state.promoId);
}
```
This is correct: only refresh if the player is currently looking at the
Dashboard. If they're on Roster, the Dashboard is marked stale (per the
legacy `GameState._stale_screens` pattern) and refreshed on next navigation.

**Recommendation:** port the `_stale_screens` set from `state.py:106` to
`app.js`. Maintain `state.staleScreens = new Set()`. On `advanceDay`, add
all screens except the active one. On `navigate(screenId)`, if
`staleScreens.has(screenId)`, call the renderer + delete from set.

### 5.3 Fighter name hyperlinks — implementation pattern

**Recommended:** Add a `navigate(screenId, params)` function to `app.js`:

```javascript
function navigate(screenId, params) {
  // Push current screen onto _navStack (if different)
  if (state.activeScreen && state.activeScreen !== screenId) {
    state._navStack.push({
      screen: state.activeScreen,
      params: state.activeParams || {}
    });
    if (state._navStack.length > 10) state._navStack.shift();
  }
  state.activeScreen = screenId;
  state.activeParams = params || {};
  updateSidebarActive();
  // Route to renderer
  if (screenId === 'dashboard') return CE.dashboard.loadAndRender(state.promoId);
  if (screenId === 'fighter_profile') return CE.fighterProfile.loadAndRender(params.fighter_id);
  if (screenId === 'roster') return CE.roster.loadAndRender(state.promoId);
  if (screenId === 'free_agents') return CE.freeAgents.loadAndRender();
  // ...placeholder fallback
}

function goBack() {
  if (!state._navStack.length) return navigate('dashboard');
  var prev = state._navStack.pop();
  return navigate(prev.screen, prev.params);
}
```

Then `dashboard.js:419-429` becomes:
```javascript
host.querySelectorAll('[data-fighter-id]').forEach(function (el) {
  el.addEventListener('click', function (evt) {
    evt.preventDefault();
    var fid = el.getAttribute('data-fighter-id');
    if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
  });
});
```

### 5.4 Should the back button use a navigation stack?

**YES — and the legacy code already proved the design.** `ui_legacy/state.py:92`
had `self._nav_stack = []` with cap 10, FIFO overflow, and `go_back()` that
pops + navigates without re-pushing. The pywebview rebuild should port this
verbatim (in JS). The Fighter Profile Back button should:
1. If `_navStack` non-empty: pop + navigate to (screen, params).
2. If empty: fall back to `navigate('dashboard')` (safer default than
   `roster` — the player may have arrived from Free Agents or News).

### 5.5 Top 3 performance recommendations

1. **Port the stale-screen set from `ui_legacy/state.py:106` to `app.js`.**
   On `advanceDay`, mark every screen except the active one as stale.
   On `navigate(screenId)`, if stale, refresh + clear flag. This skips
   re-rendering 3-5 invisible screens per Advance Day, saving ~120 widget
   rebuilds × ~5ms each = ~600ms per tick. Critical for the "Advance Day
   should feel instant" dopamine requirement.

2. **Add a fighter-query cache in `bridge.js`.** Fighter Profile reads are
   keyed by `fighter_id` and rarely change within a session. Cache the
   last 20 profiles in `window.CE._profileCache`. On `navigate('fighter_profile', {fighter_id})`, check cache first; fetch only on miss or
   after `advanceDay` (which should clear the cache). Saves ~50ms per
   Profile navigation.

3. **Debounce Roster/Free Agents search at 200ms (already the legacy
   standard).** Wire `input` event → `clearTimeout(timer); timer = setTimeout(fetch, 200)`.
   Cancel inflight fetches if a new keystroke arrives (track a
   `_searchSeq` counter, ignore stale responses). The legacy Phase 4
   debounce is documented in `GUI_PLAN.md` §6.2 — port the same pattern.

---

## 6. Summary Table — Per-Screen Action Inventory

| Screen | Hyperlinks | Nav buttons | Action buttons | New API methods needed |
|---|---|---|---|---|
| Dashboard | 4 sources (Top Story, Watch ×3, Champions ×≤8, News ×≤5) → Fighter Profile | 2 (Build Card, Matchmaking) — both missing | 1 (Advance Day) ✅ | 0 new (uses existing `advance_day`) |
| Roster | 1 (row name) → Fighter Profile | 1 (View Profile) | 7 (WC/Gender/Stage filters, Search, Clear, Pagination, Sort) | 0 new (extend `get_roster_data` to accept filters + return aggregates) |
| Free Agents | 1 (row name) → Fighter Profile | 0 | 4 (Sign, Filters, Pagination, Sign Modal) | 2 new (`sign_free_agent` Api wrap, `estimate_signing_cost`) |
| Fighter Profile | 1 (opponent names in Recent Fights) → Fighter Profile | 1 (Back) | 5 (Cut, Offer Extension, Book Next Fight, Scout, Show-all-26 toggle) + 6 tabs | 4 new (`cut_fighter`, `offer_extension`, `book_fight`, `send_scout`, `get_scouting_report`) |

**Grand total:** 7 hyperlink sources, 4 nav buttons, 17 action buttons
across the 4 screens. **1 of 17 action buttons is currently wired
(Advance Day).** **6 new Python API methods are needed** (cut_fighter,
offer_extension, book_fight, send_scout, get_scouting_report,
estimate_signing_cost — plus the trivial `sign_free_agent` Api wrap
around the existing service function).

---

## 7. Decision Points for the Supervisor

1. **Navigation back-stack:** port the legacy `state._nav_stack` design
   verbatim, or build a fuller browser-history-style stack with forward
   button? **[RECOMMENDED: port verbatim]** — simpler, proven, matches
   the §10.3 Breadcrumb spec.

2. **Sign cost formula:** flat 50000 (legacy default) vs. derived from
   ceiling/age/momentum/market (§6.4 spec). Derived is more engaging
   but needs ~50 lines of formula code + balance testing. **[RECOMMENDED:
   ship flat 50000 in Phase 1, derive in Phase 2 once ceiling column
   exists.]**

3. **Cut Fighter event:** should it publish a new `Events.FIGHTER_CUT`
   event, or reuse `Events.FIGHTER_SIGNED` with a `direction='out'`
   flag? **[RECOMMENDED: new event type]** — cleaner subscriber logic,
   mor/interpretation/news can branch on event type.

4. **Save/Load UI:** ModalDialog from top-bar kebab (§4.9 spec) vs.
   dedicated screen in sidebar. **[RECOMMENDED: ModalDialog]** — matches
   the spec, removes a sidebar item, and the load flow doesn't need
   screen real estate.

5. **`Api.load_game` conn swap:** should `Api` close + swap `self.conn`
   on load, or rely on SQLite WAL re-read? **[RECOMMENDED: close + swap]**
   — eliminates the stale-transaction fragility, costs 5 lines of code.
