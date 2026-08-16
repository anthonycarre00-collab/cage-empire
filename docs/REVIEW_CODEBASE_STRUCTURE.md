> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Codebase Structure Review

**Reviewer:** Explore agent (read-only)
**Scope:** Screen inventory, backend API, frontend files, service layer, interpretation layer, DB tables, test suite.
**DB schema version at time of review:** `3.26.0` (37 migrations applied; latest: `v3_26_0_add_show_quality_adjustment_txn_type`, applied 2026-08-10).
**DB:** `data/cage_empire.db` (SQLite, WAL mode). Total tables: **62**.

This document is the foundation for the comprehensive review. Every fact below was verified by reading the actual code (not inferred from docs).

---

## 1. Screen Inventory

### NAV_GROUPS (from `src/web/js/app.js` lines 29-59)

5 sidebar groups, **19 nav items** total + 2 non-sidebar screens reached via navigation (`fighter_profile`, `fight_resolution`).

| # | Nav ID | Display name | Group | Status | Handler |
|---|--------|--------------|-------|--------|---------|
| 1 | `dashboard` | The Empire 🏛 | HOME | **WIRED** | `window.CE.dashboard` (`dashboard.js`) |
| 2 | `schedule` | Calendar 📅 | HOME | **WIRED** | `window.CE.calendar` (`calendar.js`) — Phase MM2 |
| 3 | `news` | The Wire 📰 | HOME | **WIRED** | `window.CE.wire` (`wire.js`) |
| 4 | `roster` | The Stable 🥊 | FIGHTERS | **WIRED** | `window.CE.roster` (`roster.js`) |
| 5 | `free_agents` | Open Market 🏪 | FIGHTERS | **WIRED** | `window.CE.freeAgents` (`free_agents.js`) |
| 6 | `scouting` | Scouting 🔍 | FIGHTERS | **PLACEHOLDER** | falls through to `PLACEHOLDER_PHRASES` |
| 7 | `hall_of_fame` | Legends 🏆 | FIGHTERS | **PLACEHOLDER** | falls through |
| 8 | `event_builder` | Stack a Card 🎫 | EVENTS | **WIRED** | `window.CE.eventBuilder` (`event_builder.js`) |
| 9 | `matchmaking` | Matchmaking ⚔ | EVENTS | **WIRED** | `window.CE.matchmaking` (`matchmaking.js`) |
| 10 | `past_events` | The Archive 📦 | EVENTS | **WIRED** | `window.CE.archive` (`archive.js`) |
| 11 | `finance` | The Books 💰 | BUSINESS | **PLACEHOLDER** | falls through |
| 12 | `contracts` | Deals ✍ | BUSINESS | **PLACEHOLDER** | falls through |
| 13 | `staff_market` | Staff Market 👔 | BUSINESS | **WIRED** | `window.CE.staffMarket` (`staff_market.js`) |
| 14 | `rival_promotions` | The Competition ⚔ | BUSINESS | **WIRED** | `window.CE.rivalPromotions` (`rival_promotions.js`) |
| 15 | `gyms` | Training Camps 🏋 | BUSINESS | **PLACEHOLDER** | falls through |
| 16 | `rankings` | The Rankings 📊 | WORLD | **WIRED** | `window.CE.rankings` (`rankings.js`) |
| 17 | `titles` | Belts 🥇 | WORLD | **WIRED** | `window.CE.titles` (`titles.js`) |
| 18 | `rivalries` | Bad Blood 💢 | WORLD | **PLACEHOLDER** | falls through |
| 19 | `records` | The Record Book 📖 | WORLD | **PLACEHOLDER** | falls through |
| — | `fighter_profile` | (no sidebar entry) | — | **WIRED** | `window.CE.fighterProfile` — reached via hyperlinks |
| — | `fight_resolution` | (no sidebar entry) | — | **WIRED** | `window.CE.fightNight` — reached via Dashboard |

### Summary

- **14 wired screens** (12 sidebar + 2 non-sidebar).
- **7 placeholder sidebar items** (~37% of sidebar): `scouting`, `hall_of_fame`, `finance`, `contracts`, `gyms`, `rivalries`, `records`.

### Placeholder phrases (from `PLACEHOLDER_PHRASES` in `app.js`)

Each placeholder screen shows a voice-styled "coming soon" message (no real content). Phrases exist for all 7 placeholders + 3 wired screens that fall through if their JS module is missing. The placeholder phrases confirm the *planned* vision for each unwired screen:

- `scouting`: "The scouts are waiting. Send them out. Find the next great one before anyone else does."
- `hall_of_fame` (Legends): "Legends never die. The fighters who shaped the sport. Their stories live here."
- `finance` (The Books): "The books are open. Every dollar in, every dollar out. Run a tight ship."
- `contracts` (Deals): "No deals on the table. When fighters need new contracts, they will appear here."
- `gyms` (Training Camps): "Training camps are ready. Send your fighters to develop."
- `rivalries` (Bad Blood): "Rivalries develop over time."
- `records` (The Record Book): "All-time leaders. The names that echo through the sport."

### App shell flow (from `app.js` `init()`)

1. App launches → `bridge.ready()` waits for `pywebviewready` event (timing fix documented in `bridge.js`).
2. `getPlayerPromotion()` → if a promo is selected in `player_settings`, skip pre-game.
3. Otherwise show pre-game screen → fetch `getPromotionList()` → render promo cards.
4. Player clicks a card → `selectPromotion()` + optional `setPlayerName()` → build sidebar + navigate to `dashboard`.

Top-bar actions wired in `app.js`:
- **Advance Day** button → `advanceDay()` (single tick).
- **Sim Week** button (Phase F2.2) → loops `advanceDays(1)` × 7 with a processing overlay that cycles random fighter profile snapshots every 10s + a Cancel button.
- **Skip to Show** button (Phase F2.2) → `advanceToNextShow()` (one call, full skip).
- Both use a full-screen `#ce-processing-overlay` with progress text + a random fighter bio card.

Back navigation: 10-entry FIFO stack (`state._navStack`) with `navigateBack()`.

---

## 2. Backend API Inventory

Source: `src/app_web.py` (10,978 lines). Single class `Api` (line 1759) exposed to JS via pywebview.

**Total public methods: 56** (methods not starting with `_`).

Plus module-level private helpers (`_decode_phrase`, `_format_cash`, `_rating_tier`, `_nation_iso3`, `_venue_icon`, etc.) and `register_all_subscribers()` at line 78.

### 2.1 Clock + Player Settings (7 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_clock` | `()` | Returns current sim date/day/week/month/year as dict with `month_name`. |
| `get_player_promotion` | `()` | Returns the player's selected `promotion_id` (int) or 0 if unselected, from `player_settings`. |
| `select_promotion` | `(promo_id)` | Persists the player's promo selection. |
| `set_player_name` | `(name)` | Persists the player's manager name. |
| `get_player_name` | `()` | Returns the player's manager name (or empty string). |
| `get_player_cash` | `()` | Returns `{cash, cash_display, is_negative}` for the player's promo. |
| `get_promotion_list` | `()` | Returns all promotions for the pre-game selection screen. |

### 2.2 Dashboard + Time Advancement (5 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_dashboard_data` | `(promo_id)` | Returns the full 8-section Dashboard payload (top story, status, next event, watch, champions, recent results, news). |
| `advance_day` | `()` | Advances the sim by one day via `services.clock.advance_day`. |
| `advance_days` | `(n)` | Phase F2.2 — advances the sim by N days in one call (used by Sim Week). |
| `advance_to_next_event` | `()` | Phase F2.2 — advances to the player's next scheduled event (Skip to Show). |
| `get_random_fighter_id` | `()` | Phase F2.2 — returns a random fighter_id from the player's roster (processing overlay). |

### 2.3 Roster + Free Agents (3 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_roster_data` | `(promo_id, page=1, filters=None)` | Returns paginated roster for the player's promo with WC/gender/stage/search filters. |
| `get_free_agents` | `(page=1, filters=None)` | Returns paginated free-agent pool with WC/ceiling/search filters. |
| `get_fighter_portrait_b64` | `(fighter_id)` | Returns base64-encoded portrait for a fighter (DB-REVIEW-IMAGE-ASSIGNMENT E.4). |

### 2.4 Fighter Profile (4 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_fighter_profile` | `(fighter_id)` | Backward-compat wrapper → delegates to `get_fighter_profile_data`. |
| `get_fighter_profile_data` | `(fighter_id)` | Returns the full Fighter Profile payload (header, identity strip, attributes, personality, career stats, fight history, news, bio, decision history). |
| `get_fighter_decision_history` | `(fighter_id)` | Returns player's decision history for a fighter (Phase R reward layer). |
| `get_random_fighter_id` | `()` | (also listed above — used by overlay). |

### 2.5 Rival Promotions (2 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_rival_promotions` | `()` | Returns list of rival promos (excludes the player's) — CR-9. |
| `get_rival_roster` | `(promo_id, page=1, filters=None)` | Read-only roster view of a rival promo (no potential/ceiling/scouting info exposed). |

### 2.6 Free Agency Actions (5 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `estimate_signing_cost` | `(fighter_id)` | Returns estimated signing cost (derived from potential + age + form). |
| `sign_free_agent` | `(fighter_id, salary=None, signing_bonus=0, contract_length=2, win_bonus_pct=0.5)` | Signs a free agent with player-set terms (Phase E3.3 negotiation). |
| `get_bidding_alerts` | `()` | Returns active SIGNING_INTENT alerts for the player to counter (Phase M3.2). |
| `counter_offer` | `(fighter_id, salary, signing_bonus=0, contract_length=2, win_bonus_pct=0.5)` | Player's counter-offer against a rival AI's SIGNING_INTENT. |
| `cut_fighter` | `(fighter_id)` | Releases a fighter from the player's promo. |

### 2.7 Event Builder (5 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_event_builder_data` | `()` | Returns venues + weight classes + financial levers for the Stack a Card screen. |
| `get_event_preview` | `(params)` | Returns projected revenue/expense breakdown for a candidate event WITHOUT creating it. |
| `confirm_card` | `(event_id, fights)` | Writes a staged card to DB in one transaction + computes projection (locks event). |
| `reopen_card` | `(event_id)` | Re-opens a confirmed card so the player can edit (removes all fights, resets status). |
| `create_event` | `(params)` | Creates a scheduled event with player-set financial levers. |

### 2.8 Calendar (2 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_calendar_data` | `(month=None, year=None)` | Returns a month-grid of days with player + rival events + conflict warnings. |
| `get_date_conflicts` | `(event_date)` | Returns conflict warnings for a single date (event_builder date picker). |

### 2.9 Matchmaking (10 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_matchmaking_data` | `(event_id)` | Returns event info + eligible fighters + booked fights with matchup scores + punditry. |
| `get_rivalry_partners` | `(fighter_id)` | Returns fighters with an active rivalry (heat ≥ 50) with the given fighter. |
| `book_fight` | `(event_id, red_fighter_id, blue_fighter_id, card_slot=None)` | Creates a fight row + participants + event_cards + persists punditry analysis. |
| `remove_fight` | `(fight_id)` | Deletes a fight from the card (cascade removes participants + event_cards). |
| `reorder_fights` | `(event_id, fight_order)` | Updates `card_slot` + `card_position` for all fights on the card. |
| `get_fight_analysis` | `(red_fighter_id, blue_fighter_id)` | Pre-fight analysis for a fighter pair without booking (Compare modal preview). |
| `get_fight_tale_of_tape` | `(fight_id)` | Tale-of-tape data (height/reach/age/record/style/last-5 + champion status). |
| `get_fight_stakes` | `(fight_id)` | Ranking implications + title shot context (What's at Stake modal). |
| `get_fight_fan_pulse` | `(fight_id)` | Rivalry context + hometown reaction + voice-layer fan pulse verdict. |
| `get_fight_compare` | `(fight_id)` | 25 attributes for both fighters + punditry analysis (Compare modal radar chart). |

### 2.10 Staff Market (3 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_staff_market_data` | `(page=1, filters=None)` | Returns paginated free-agent staff (Coach/Scout/Doctor/Cutman/GM/Commentator). |
| `estimate_staff_hire_cost` | `(staff_id)` | Returns hire cost estimate (salary + signing bonus display). |
| `hire_staff` | `(staff_id, salary=None, signing_bonus=0, contract_length=2)` | Hires a free-agent staff member to the player's promo. |

### 2.11 News/Archive/Rankings/Titles (5 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `get_wire_data` | `(page=1, filters=None)` | Returns paginated news items with topic + sentiment filters + search. |
| `get_archive_data` | `(page=1, filters=None)` | Returns 10 past events with main-event result + rating voice phrase + net profit. |
| `get_event_card` | `(event_id)` | Returns the full fight list for one event (Archive expand). |
| `get_rankings_data` | `(weight_class_id=None, gender=None, promo_filter=None)` | Returns top-15 ranked fighters for a weight class + the player's promo. |
| `get_titles_data` | `()` | Returns all titles across all promos, grouped by promo with champion info. |

### 2.12 Fight Night (3 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `resolve_next_fight` | `(event_id=None)` | Resolves the next unresolved fight on the player's scheduled event. |
| `get_fight_night_data` | `(fight_id=None)` | Returns the full play-by-play payload (beats + commentary + result card); null → preview mode. |
| `get_event_fights` | `(event_id)` | Returns all fights on an event with their resolution status (Fight X of Y transport bar). |

### 2.13 Save/Load + System (4 methods)

| Method | Signature | One-sentence purpose |
|--------|-----------|----------------------|
| `list_saves` | `()` | Returns a list of available save-game names. |
| `save_game` | `(name)` | Saves the current game state under `name`. |
| `load_game` | `(name)` | Loads a saved game state in-place on the conn. |
| `on_close` | `()` | Auto-saves `exit_save` before the window closes (defensive). |

### API method count by area

| Area | Count |
|------|-------|
| Clock + Player Settings | 7 |
| Dashboard + Time | 5 |
| Roster + Free Agents | 3 |
| Fighter Profile | 4 (incl. shared `get_random_fighter_id`) |
| Rival Promotions | 2 |
| Free Agency Actions | 5 |
| Event Builder | 5 |
| Calendar | 2 |
| Matchmaking | 10 |
| Staff Market | 3 |
| News/Archive/Rankings/Titles | 5 |
| Fight Night | 3 |
| Save/Load + System | 4 |
| **TOTAL** | **56** (one overlap: `get_random_fighter_id` counted in 2) |

### API surface observations

- All methods are wrapped in try/except + return `None` / `{ok: false, error: ...}` on failure (defensive).
- Fighter data is read from `fighter_descriptors` (cache) per CONVENTIONS §17 — no raw attribute integers leak to the UI.
- `register_all_subscribers()` is called in `Api.__init__` (line 1788) so every API instance has all event-bus subscribers wired (retirements, injuries, scouting, rival AI, news, auto-save, interpretation refresh).
- Connection: `check_same_thread=False` + WAL mode + 5s busy timeout — pywebview calls API methods from different threads.

---

## 3. Frontend File Inventory

### 3.1 JS files (`src/web/js/`)

**16 files, 12,444 total lines.** Loaded in this order (from `src/web/index.html`):

| # | File | Lines | Implements |
|---|------|-------|------------|
| 1 | `bridge.js` | 417 | JS↔Python bridge — wraps every `window.pywebview.api.method_name(...)` call in a Promise with timeout + error reporting. Waits for `pywebviewready` event (timing fix). |
| 2 | `dashboard.js` | 739 | The Empire dashboard — 8 sections: welcome, gradient header, top story, promo status (5 tiles), next event, fighter watch (3 cards), champions grid, recent results, recent news. |
| 3 | `roster.js` | 443 | The Stable — 9-column ledger table of player's roster with WC/gender/stage/search filters, 20/page, sortable. Row click = select, double-click = Fighter Profile. |
| 4 | `free_agents.js` | 970 | Open Market — 8-column ledger of free agents with sticky sign bar at bottom. Ceiling display: voice phrase if scouted, else "????". Supports bidding-alert flow via `loadAndRenderWithBiddingAlert`. |
| 5 | `fighter_profile.js` | 969 | Fighter Profile — 6-tab dossier (Overview/Attributes/Personality/Career/Fights/News) with 256px portrait, identity strip, action buttons (Cut/Book Next Fight/Scout). |
| 6 | `rival_promotions.js` | 484 | The Competition — two views: grid of rival promo cards (default) + read-only roster view when a promo is selected. |
| 7 | `event_builder.js` | 1269 | Stack a Card — 6 sections: header, name your event, pick your date (with conflict warnings), pick your venue (filterable), the business end (sliders: ticket/marketing/ppv/is_ppv), review + create. |
| 8 | `staff_market.js` | 721 | Staff Market — 7-column ledger of free-agent staff with sticky hire bar. Filters by role/skill tier/search. Never displays raw `skill_level`. |
| 9 | `matchmaking.js` | 1963 | Matchmaking V2 (the Heartbeat) — two-row layout: top = matchup zone (Red/VS/Blue), bottom = drag-drop card list + status panel. Full card-confirmation flow (MM1.4). |
| 10 | `calendar.js` | 514 | The Calendar — month-grid showing player events (gold) + rival events (red) + today (blue) + past dates (greyed) + min-lead-time blocked (diagonal stripes) + conflict icons. Click date → detail panel → schedule event. |
| 11 | `wire.js` | 380 | The Wire — paginated filterable news feed (16k+ items, 24 DB topics collapsed to 16 UI groups). 20/page. |
| 12 | `archive.js` | 555 | The Archive — past events list with filters (date-from/to, search, min-rating). Click event → expand to full card with winner highlight. 10/page. |
| 13 | `rankings.js` | 396 | The Rankings — top-15 by weight class. Champion strip + rankings table with rank-change symbols, momentum phrases, title chips. |
| 14 | `titles.js` | 341 | Belts — every title across every promo, grouped by promo. Player's promo block has gold border. Each title = card with champion portrait + reign voice phrase OR "VACANT" state. |
| 15 | `fight_night.js` | 1410 | Fight Night — live play-by-play. 3-phase state machine per fight: PRE-FIGHT (5s timer, tale of tape, punditry), LIVE (4-zone grid: commentary feed/status/tracker/key moments with 1x/2x/4x/Pause/Skip), RECAP (result card + stat changes + show rating panel). |
| 16 | `app.js` | 873 | App shell — pre-game, navigation, sidebar build, top-bar (clock/cash), Advance Day + Sim Week + Skip to Show with processing overlay, back-stack navigation, toast helper. |

### 3.2 CSS files (`src/web/css/`)

**17 files, 10,345 total lines.** Loaded in this order (after `theme.css` + `shell.css` + `components.css`):

| # | File | Lines | Styles |
|---|------|-------|--------|
| 1 | `theme.css` | 197 | Global theme variables — colors, fonts, spacing, radii, shadows, voice-tier colors. |
| 2 | `shell.css` | 733 | App shell layout — sidebar, top bar, pre-game, processing overlay, toast, error banner. |
| 3 | `components.css` | 289 | Shared UI components — chips, buttons, cards, stat tiles, momentum rings, form meters. |
| 4 | `dashboard.css` | 649 | Dashboard layout + sections. |
| 5 | `roster.css` | 335 | Roster ledger table. |
| 6 | `free_agents.css` | 408 | Free Agents ledger + sticky sign bar. |
| 7 | `fighter_profile.css` | 648 | Fighter Profile 6-tab layout + identity strip + portrait. |
| 8 | `rival_promotions.css` | 189 | Rival promo cards + read-only roster. |
| 9 | `event_builder.css` | 985 | Stack a Card sections + sliders + venue grid. |
| 10 | `staff_market.css` | 147 | Staff Market ledger + sticky hire bar. |
| 11 | `matchmaking.css` | 2107 | Matchmaking V2 — biggest CSS file. Matchup zone + drag-drop cards + modals (Tale of Tape, Stakes, Fan Pulse, Compare). |
| 12 | `calendar.css` | 612 | Calendar month-grid + date cells + conflict icons. |
| 13 | `wire.css` | 308 | The Wire news list + topic chips + sentiment dots. |
| 14 | `archive.css` | 512 | The Archive event list + expandable card. |
| 15 | `rankings.css` | 482 | Rankings table + champion strip + rank-change arrows. |
| 16 | `titles.css` | 373 | Belts grid + reign voice phrases. |
| 17 | `fight_night.css` | 1371 | Fight Night 4-zone grid + play-by-play feed + result card. |

---

## 4. Service Layer Inventory

### 4.1 `src/services/` (16 files)

| File | Lines | One-sentence purpose |
|------|-------|----------------------|
| `__init__.py` | 0 | Empty package init. |
| `clock.py` | 63 | Smallest module — sim clock reader + fighter name lookup. |
| `contracts.py` | 326 | Contract display + `sign_free_agent` logic (extracted from old `app.py`). |
| `fight_engine.py` | 6337 | Beat-level fight resolution (largest service file) — fatigue, momentum, finishes, commentary, doctor stoppage. |
| `finance_svc.py` | 24 | Thin wrapper — re-exports `src/finance.py` public API. |
| `hof_svc.py` | 601 | Hall of Fame induction — subscribes to `FIGHTER_RETIRED`, evaluates eligibility, writes `hall_of_fame` row + induction news item. |
| `injuries_svc.py` | 114 | Injury recovery tick + `get_doctor_recovery_bonus` (Phase E5 — sum of doctor `skill_level / 200` capped at 15% with 3 top doctors). |
| `matchmaking.py` | 1628 | Event scheduling + card building (5-13 fights by promo size tier) + training-camp orchestration. |
| `memory_svc.py` | 100 | Writer for `fighter_memory_links` — `populate_style_echo`, `populate_former_teammate_link`, etc. (Task 6.0 ships only the 2 populate functions). |
| `news_svc.py` | 63 | Thin wrapper — re-exports `src/news.py` + adds `get_latest_news_summary` (10-line query for bottom-bar ticker). |
| `pruning_svc.py` | 268 | Monthly `TICK_ADVANCED` subscriber — prunes 7 high-churn tables (news_items >365d, daily_headlines >90d, social_posts >180d, injuries/suspensions >365d, training_camps >90d, scouting_reports >365d). |
| `punditry_svc.py` | 26 | Thin wrapper — re-exports `src/punditry.py` public API. |
| `retirement_svc.py` | 1278 | `generate_fighter` regen engine (550-line function) + `_vacate_title_on_retirement` + `check_retirements` wrapper. |
| `rivalries_svc.py` | 25 | Thin wrapper — re-exports `src/rivalries.py` public API. |
| `scouting_svc.py` | 22 | Thin wrapper — re-exports `src/scouting.py` public API. |
| `training_svc.py` | 46 | Thin wrapper — delegates to `tick_processor._check_training_camps`. |

### 4.2 `src/services/rival_ai/` (10 files)

The rival promotion AI — 7 thin modules each owning one decision axis + shared helpers. Per `docs/RIVAL_AI_ARCHITECTURE.md`:

| File | Lines | One-sentence purpose |
|------|-------|----------------------|
| `__init__.py` | 117 | Package init + tick dispatcher. |
| `_shared.py` | 205 | Shared DB helpers (current_date, roster_size) + news-item writer + per-(promo, date) roster cache placeholder. |
| `archetypes.py` | 437 | The 4-archetype system (Major League / Regional Power / Grassroots / Rising Star) + per-axis constants. |
| `event_scheduler.py` | 471 | Phase 2 — picks event_date + cadence for rival promos + delegates to matchmaker. |
| `matchmaker.py` | 636 | Phase 2 — biased matchup scoring + card assembly (15-50% non-optimal matchups for "realistic, not flawless" AI). |
| `signing_agent.py` | 1081 | Phase 2 — roster-gap detection + bidding wars + contract-expiry interest rumors. Never queries fighters with `current_promotion_id IS NOT NULL` (no-tapping-up rule). |
| `cutting_agent.py` | 352 | Phase 3 — fighter cutting with `cut_risk` scoring + protective rules (champion/loyalty/prospect/title-shot protection). |
| `staff_manager.py` | 588 | Phase 3 — quarterly hire/fire for promotion-bound staff (scouts/commentators/doctors/cutmen/GMs). Coaches are gym-bound, excluded. |
| `budget_manager.py` | 485 | Phase 3 — 5-state budget machine (SURVIVAL/CONSERVATIVE/NORMAL/EXPANSION/CRISIS) + crisis handling. Monthly tick. |
| `imperfection.py` | 460 | Phase 4 — 6 imperfection mechanisms (archetype bias, recency bias, loyalty, whim, fatigue-mistakes, personality-driven errors). Pure functions. |

---

## 5. Interpretation Layer Inventory

### `src/interpretation/` (9 files)

The interpretation layer translates raw simulation state into player-facing meaning, context, and stories. **NEVER modifies simulation tables — only writes to `*_descriptors` cache tables.** Per CONVENTIONS §17, the Office Mode UI reads from `*_descriptors` ONLY.

| File | Lines | One-sentence purpose |
|------|-------|----------------------|
| `__init__.py` | 351 | Package init + `register_subscribers` — wires 4 event-bus subscribers that trigger targeted single-fighter refreshes. |
| `snapshot_cache.py` | 687 | Orchestrator — `run_daily_interpretation_pass(conn)` (post-commit step in `run_tick`) + `refresh_fighter(conn, fighter_id)` (targeted <10ms refresh). |
| `context_engine.py` | 1298 | Task 2.2 — computes momentum, pressure, trajectory for every active fighter. Bulk-load pattern: 2 SELECTs for 4450 fighters (NOT N+1). |
| `career_phase_engine.py` | 841 | Task 2.3 — 6 canonical career phases (prospect / rising_contender / champion / veteran / gatekeeper / declining). |
| `narrative_families.py` | 797 | Task 2.4 — 4 narrative families (prodigy / veteran / fallen_champion / cinderella_story) layered ABOVE career_phase. |
| `memory_engine.py` | 690 | Task 2.5 — READER that surfaces memories before fights (4 MVP search types: previous_fight, shared_gym, former_teammate, injury_history). |
| `headline_engine.py` | 1267 | Task 2.6 — generates 4 MVP daily headlines (top_story, upset_of_week, fastest_rising, biggest_fall). |
| `legacy_engine.py` | 708 | Task 2.7 — 4 legacy states (building / established / legendary / forgotten) for active AND retired fighters. |
| `echoes_engine.py` | 748 | Phase R — surfaces 2-3 consequences of the player's past bookings/signings/cuts on every Advance Day. 4 templates (SIGNING_ECHO, CUT_ECHO, BOOKING_ECHO, DECISION_ECHO). |

### Storage convention (CONVENTIONS §17.4)

Each cache column stores `label||voice phrase`:
- The UI reads the voice phrase (after `||`).
- The interpretation engine's rules + tests read the canonical label (before `||`).

Example: `fighter_descriptors.career_phase = "prospect||a young prospect with the world ahead of him"`.

---

## 6. Database Tables

### Total tables: **62**

### 6.1 Table groups

#### Core simulation (10 tables)
- `simulation_clock` (1 row) — single-row sim clock.
- `fighters` (4,514 rows) — fighter master records.
- `fighter_attributes` (4,514) — 26 attributes per fighter.
- `fighter_personality` (4,514) — 20 personality traits per fighter.
- `fighter_career` (4,514) — career stats (record, streaks, etc.).
- `fighter_bios` (4,514) — long-form bio text per fighter.
- `fighter_descriptors` (4,513) — interpretation cache (`context`, `career_phase`, `narrative_family`, `legacy_state`, etc.).
- `events` (1,714) — scheduled + completed events.
- `fights` (3,235) — fight records.
- `fight_history` (3,608) — denormalized fight results.

#### Fight engine (5 tables)
- `fight_beats` (53,669) — per-beat play-by-play data (the B1/B2 beat engine).
- `fight_rounds` (2,930) — per-round summary data.
- `fight_participants` (2,872) — Red/Blue corner fighter IDs per fight.
- `commentary_segments` (32,889) — punditry commentary tied to beats.
- `matchup_analyses` (1,361) — pre-fight pundit predictions per fighter pair.

#### Economy + contracts (5 tables)
- `finance_transactions` (10 rows) — ledger of all cash movements.
- `contracts` (1,498) — contract templates (salary, length, etc.).
- `fighter_contracts` (1,396) — active fighter contracts.
- `staff_contracts` (102) — active staff contracts.
- `broadcast_contracts` (0 rows — empty) — broadcast deals (schema exists, no data).

#### Player + decisions (4 tables)
- `player_settings` (8 rows) — key-value store (`player_promotion_id`, `player_name`, `schema_version`, etc.).
- `player_decisions` (216) — Phase R reward layer: logs every signing/cut/booking with `context_json`.
- `daily_headlines` (435) — interpretation cache: 4 daily headlines per day.
- `daily_echoes` (672) — interpretation cache: 2-3 player-decision echoes per day.

#### Roster + talent + world (10 tables)
- `promotions` (10) — 10 promotions in the world.
- `weight_classes` (13) — 13 weight classes (men's + women's).
- `rankings` (1,069) — divisional rankings (top-15 per WC × promo).
- `titles` (111) — championship titles (vacant + held).
- `gyms` (300) — training camps.
- `staff` (382) — coaches, scouts, doctors, cutmen, GMs, commentators.
- `scouting_reports` (**0 rows — empty**) — scouting system exists but no reports generated.
- `training_camps` (**0 rows — empty**) — training camp system exists but no active camps.
- `regen_lineage` (63) — links retired fighters to their regen replacements.
- `staff_regen_lineage` (0) — same for staff.

#### World geography (5 tables)
- `nations`, `regions`, `cities`, `venues` (276), `markets`.

#### Narrative + voice (5 tables)
- `news_items` (2,319) — news feed entries (24 topics).
- `news_sources` (6) — news outlets (ESPN, MMA Junkie, etc.).
- `social_posts` — fighter social media posts.
- `rivalries` (390) — pairwise fighter rivalries with heat scores.
- `fighter_memory_links` (763) — memory links (style_echo, former_teammate, etc.).

#### Descriptor cache (4 tables)
- `fighter_descriptors` (4,513) — main per-fighter interpretation cache.
- `division_descriptors` (**0 rows**).
- `gym_descriptors` (**0 rows**).
- `promotion_descriptors` (**0 rows**).

#### Show rating + lifecycle (4 tables)
- `show_ratings` (552) — per-event fan/commercial/excitement/quality/overall ratings.
- `injuries` (395) — active + resolved injuries.
- `suspensions` (24) — active + expired suspensions.
- `hall_of_fame` (**2 rows** — surprisingly low; docstring says 60 seeded legends).

#### Reference data (3 tables)
- `name_pools` — first/last name pools by nationality.
- `style_archetypes` — fighting style definitions.
- `personality_archetypes` — personality type definitions.

#### Bookkeeping (5 tables)
- `agent_offers` (5) — Phase C agent offers (player can lure rival fighters).
- `bidding_alerts` (40) — Phase M3.2 active bidding-war alerts.
- `weight_cut_log` — weight cut history per fight.
- `event_cards` (1,420) — slot/position per fight on a card.
- `broadcast_staff` — staff assigned to broadcast roles.

#### Schema + meta (3 tables)
- `schema_meta` (1 row): `('cage_empire', '3.26.0', '2026-08-10 00:00:16')`.
- `schema_migrations` (37 rows): migration history, latest = `v3_26_0_add_show_quality_adjustment_txn_type`.
- `interpretation_cache_meta` (1 row): interpretation pass metadata.

### 6.2 Notable DB observations

1. **Empty `scouting_reports` table** — but Scouting screen is a **placeholder**. Service layer exists (`scouting_svc.py` wrapper + `src/scouting.py`), DB schema exists, but no reports are being generated and no UI consumes them.
2. **Empty `training_camps` table** — but Training Camps (gyms) screen is a **placeholder**. Service layer exists (`training_svc.py` wrapper), schema exists, but no active camps.
3. **Empty descriptor caches** (`division_descriptors`, `gym_descriptors`, `promotion_descriptors`) — interpretation layer writes only to `fighter_descriptors` currently. The other 3 caches are stubbed schema for future interpretation engines.
4. **`hall_of_fame` has only 2 rows** — but `hof_svc.py` docstring claims 60 seeded legends. Likely the seeded legends are in a different table (perhaps `fighters` with `is_retired=1` + a flag) OR the docstring is out-of-date. Worth investigating.
5. **`broadcast_contracts` is empty** — Phase E2 finance model references it (broadcast revenue), but no data is populated. May be a Phase E2/E3 deferred feature.
6. **`finance_transactions` has only 10 rows** — surprisingly low for 1,714 events. Finance processing may not be running on every event (worth checking `finance.register_subscribers`).
7. **`staff_regen_lineage` is empty** — but `regen_lineage` (for fighters) has 63 rows. Staff regen may not be running.

---

## 7. Test Suite Inventory

### `scripts/test_*.py` — **51 test files**

Organized by area:

### 7.1 Fight Engine (6 tests)

| Test file | Tests |
|-----------|-------|
| `test_beat_engine.py` | Task B1 — basic beat-level fight engine (schema, scoring, decision). |
| `test_beat_engine_depth.py` | Task B2 — fatigue system, momentum shifts, finishes, commentary. |
| `test_fight_resolver.py` | Task 3 — attribute-based fight resolver (jacks fighter A to 90s + B to 50s, verifies A wins). |
| `test_fight_engine_balance.py` | CR-11 — runs 100 sim-fights, verifies result-type distribution falls in target ranges (doctor_stoppage fix). |
| `test_fight_importance.py` | pre-B2-fix — separates `bout_type` (card position) from `is_title_fight` (was double-duty TEXT column). |
| `test_fight_history.py` | Task 4 — `fight_history` table + record updates after a fight. |

### 7.2 Matchmaking + Cards (3 tests)

| Test file | Tests |
|-----------|-------|
| `test_card_system.py` | FIX-CardSystem — rewrite of `schedule_next_event` to build FULL fight cards (5-13 fights by size tier) instead of 1-fight-per-event. |
| `test_availability.py` | Phase MM3 — fighter availability (MM3.1 cross-event booking ±7 days, MM3.2 training camp requirement `ready/needs_camp/short_notice`). |
| `test_bidding_wars.py` | Phase M3 — rival AI bidding wars: player promo (id=1) included in signing intents. |

### 7.3 Economy + Finance (6 tests)

| Test file | Tests |
|-----------|-------|
| `test_finance.py` | Task 20 — finance system schema 3.0.0 (`finance_transactions` + `_record_transaction` + `_process_event_finance` + event bus integration). |
| `test_finance_e2.py` | Phase E2 — real PPV/broadcast revenue model balance (picks mid-tier + top-tier completed events). |
| `test_finance_e3.py` | Phase E3 — player financial levers (event builder + sliders + 5 deliverables E3.1-E3.5). |
| `test_finance_wiring.py` | Phase E1 — finance wiring smoke test (`finance.register_subscribers` callable, subscribes `_process_event_finance` to `EVENT_COMPLETED`). |
| `test_contracts.py` | Task 9 — contracts system (schema 1.4.0 + `v1_4_0_add_contracts` migration). |
| `test_free_agency.py` | Task 13 — free agency + signings. |

### 7.4 Career + Lifecycle (6 tests)

| Test file | Tests |
|-----------|-------|
| `test_regen.py` | Task 14 — regen engine (retirements create replacement fighters via `generate_fighter`). |
| `test_retirement.py` | Task 12 — retirement logic. |
| `test_career_arc_rival_ai.py` | Stage 5 — natural career arc (attribute growth 18-27, decline 30+) + rival promotion AI. |
| `test_career_phase_engine.py` | Phase 2 Task 2.3 — career phase engine (6 phases: prospect → declining). |
| `test_morale.py` | Phase A — morale (winner up, loser down; title boost; KO loss bigger drop). |
| `test_hof_induction.py` | Phase 1 Fix 1.4 — `hof_svc.py` subscriber on `FIGHTER_RETIRED` inducts qualifying fighters (title_reigns ≥ 2). |

### 7.5 Health + Training (4 tests)

| Test file | Tests |
|-----------|-------|
| `test_injuries.py` | Task 15 — injuries + medical recovery (schema 2.4.0). |
| `test_training_camps.py` | Task 16 — training camps (schema 2.5.0). |
| `test_weight_cuts.py` | Task 17 — weight cuts (schema 2.7.0, 14-column `weight_cut_log`). |
| `test_suspensions.py` | Phase B — suspensions (schema 3.4.0) + seed-time rivalries + seed-time social posts. |

### 7.6 Interpretation Layer (4 tests)

| Test file | Tests |
|-----------|-------|
| `test_context_engine.py` | Phase 2 Task 2.2 — momentum/pressure/trajectory for every active fighter. |
| `test_memory_headlines.py` | Phase 2 Tasks 2.5 + 2.6 — memory engine (4 MVP search types) + headline engine (4 MVP daily headlines). |
| `test_narrative_legacy.py` | Phase 2 Tasks 2.4 + 2.7 — narrative families (4) + legacy states (4). |
| `test_voice.py` | Task 19 — voice/interpretation layer (schema 2.8.0, `describe_attribute` for 25 attrs × 7 tiers). |

### 7.7 Staff + Scouting (3 tests)

| Test file | Tests |
|-----------|-------|
| `test_staff_effects.py` | Phase E5 — wired staff effects (doctors, cutmen, GMs, commentators) + stacking + no-staff baseline + coaches excluded. |
| `test_staff_lifecycle.py` | Phase M2 — staff aging on annual tick (Jan 1: all `staff.age += 1`). |
| `test_scouting.py` | Task 18 — scouting system (schema 2.9.0, scout attributes from specialty JSON). |

### 7.8 Rival AI (1 test)

| Test file | Tests |
|-----------|-------|
| `test_event_scheduler.py` | Task 8 — repeatable event generator (single-fight event triggers scheduling). |

### 7.9 News + Social + Punditry (3 tests)

| Test file | Tests |
|-----------|-------|
| `test_news.py` | Task 23 — event-bus-driven news engine (subscribes `FIGHT_RESOLVED`, `TITLE_CHANGED`, `TICK_ADVANCED`). |
| `test_social.py` | Task 21 — social media + beefs (schema 3.1.0, personality-driven posts). |
| `test_punditry.py` | Task 24 — punditry / matchup analysis (schema 3.2.0 → 3.3.0, writes `matchup_analyses`). |

### 7.10 Schema + Foundation (4 tests)

| Test file | Tests |
|-----------|-------|
| `test_schema_versioning.py` | Task 5 — schema version-check gate in `build_db.py` (7 cases: fresh DB, same-version rebuild, version mismatch). |
| `test_event_lifecycle.py` | Task 7 — event lifecycle transitions (single-fight event goes `scheduled → completed`). |
| `test_event_bus.py` | Task 18.5 — event bus (subscribe, publish, subscriber_count, error handling, Events.* constants). |
| `test_fighter_attributes.py` | Task 14.5+14.6+14.7 — fighter schema expansion (largest single schema change since project start). |

### 7.11 Rankings + Titles + Rivalries + Promotion (4 tests)

| Test file | Tests |
|-----------|-------|
| `test_rankings.py` | Task 10 — rankings system. |
| `test_titles.py` | Task 11 — titles system. |
| `test_rivalries.py` | Task 22 — rivalries (pairwise from social media beefs, close decisions, weight cut misses, dethronings). |
| `test_promotion_filter.py` | Task 6 — promotion filter dropdown (multi-promotion awareness). |

### 7.12 Show Rating + Agent Offers (2 tests)

| Test file | Tests |
|-----------|-------|
| `test_show_rating.py` | Stage 5 — show rating engine + venues/markets deeper simulation. |
| `test_agent_offers.py` | Phase C — agent offers + event hype + cross-promotion news + betting odds (schema 3.4.0 → 3.5.0). |

### 7.13 Reward Layer + Memory (2 tests)

| Test file | Tests |
|-----------|-------|
| `test_player_decisions.py` | Phase R — `player_decisions` `log_decision` helper (writes row, rejects invalid decision_type). |
| `test_memory_gameplans.py` | Phase A — memory resurfacing wiring (A11) + dynamic `preferred_gameplans` / `bad_matchup_tags` population (A12). |

### 7.14 Final + Critical (3 tests)

| Test file | Tests |
|-----------|-------|
| `test_final_fixes.py` | Stage5-Final — 6 stale personality fields + `player_settings` table (3.6.0 → 3.7.0) + auto-save. |
| `test_fix_critical.py` | FIX-Critical — 5 issues: rival AI resolves ALL fights on event_date (not 1 per weekly tick), retirement, gym growth, event name variety, remaining static fields. |
| `test_pre_b1_fixes.py` | pre-B1-fixes — 3 design fixes flagged before beat-level fight engine (Task B1) could begin. |

### 7.15 Test coverage observations

- **51 test files** cover nearly every stage of the project's evolution (Tasks 3-24, Phases A/B/C/E1-E5/M2-M4/MM3/R, Stage 5, Phase 1 Fix 1.4, Phase 2 Tasks 2.2-2.7).
- Tests are acceptance-style: each rebuilds a fresh DB + verifies a specific deliverable end-to-end.
- **No screen/UI tests** — all tests are backend (Python). No JS tests, no e2e tests for the wired screens.
- **No tests for the placeholder screens** (scouting, hall_of_fame, finance, contracts, gyms, rivalries, records) — confirming they are not yet built.
- `scripts/perf/` contains 3 perf tests (`test_perf.py`, `profile_screens.py`, `profile_refresh.py`) — not counted above.

---

## 8. Cross-Cutting Observations

### 8.1 What's wired vs. placeholder (full picture)

**WIRED (14 screens):** Dashboard, Calendar, The Wire, The Stable (Roster), Open Market (Free Agents), Stack a Card (Event Builder), Matchmaking, The Archive, Staff Market, The Competition (Rival Promotions), The Rankings, Belts, Fighter Profile, Fight Night.

**PLACEHOLDER (7 sidebar items):** Scouting, Legends (HoF), The Books (Finance), Deals (Contracts), Training Camps (Gyms), Bad Blood (Rivalries), The Record Book (Records).

### 8.2 Service-layer stubs vs. real engines

Many services exist as **thin wrappers re-exporting legacy `src/*.py` modules**:
- `finance_svc.py` → re-exports `src/finance.py`
- `news_svc.py` → re-exports `src/news.py`
- `punditry_svc.py` → re-exports `src/punditry.py`
- `rivalries_svc.py` → re-exports `src/rivalries.py`
- `scouting_svc.py` → re-exports `src/scouting.py`

The wrappers exist for "future GUI tasks" (6.3-6.10 per the docstrings) — most of those tasks are now done, but the wrappers remain thin (no extra logic added). The legacy `src/*.py` modules are where the real logic lives.

### 8.3 Code size hotspots

| File | Lines | Why |
|------|-------|-----|
| `src/services/fight_engine.py` | 6,337 | Beat-level fight resolution (largest file in the codebase). |
| `src/web/js/matchmaking.js` | 1,963 | Matchmaking V2 — biggest JS module. |
| `src/services/matchmaking.py` | 1,628 | Card building + training camp orchestration. |
| `src/web/js/fight_night.js` | 1,410 | 3-phase state machine + 4-zone grid. |
| `src/services/retirement_svc.py` | 1,278 | `generate_fighter` regen (550-line function alone). |
| `src/interpretation/headline_engine.py` | 1,267 | 4 daily headline types + many voice templates. |
| `src/web/js/event_builder.js` | 1,269 | 6-section screen + slider live preview. |
| `src/services/rival_ai/signing_agent.py` | 1,081 | Bidding wars + roster-gap detection. |
| `src/web/js/free_agents.js` | 970 | Bidding-alert flow + negotiation. |
| `src/web/js/fighter_profile.js` | 969 | 6-tab dossier. |
| `src/web/css/matchmaking.css` | 2,107 | Biggest CSS file. |

### 8.4 Architecture layering (per CONVENTIONS §13-§17)

```
┌──────────────────────────────────────────────────────────┐
│ UI Layer (src/web/js/*.js + src/web/css/*.css)            │
│  - 14 wired screens, 7 placeholders                       │
│  - Reads ONLY from *_descriptors cache (CONVENTIONS §17) │
│  - Fight Night is the exception (reads live fight_beats) │
└─────────────────────┬────────────────────────────────────┘
                      │ bridge.js (pywebview API wrapper)
┌─────────────────────▼────────────────────────────────────┐
│ API Layer (src/app_web.py — class Api, 56 methods)       │
│  - Defensive: try/except + JSON-serializable returns     │
│  - WAL mode + check_same_thread=False for pywebview      │
└─────────────────────┬────────────────────────────────────┘
                      │ direct SQLite calls
┌─────────────────────▼────────────────────────────────────┐
│ Service Layer (src/services/*)                           │
│  - Fight engine, matchmaking, contracts, retirement,     │
│    HoF, injuries, training, pruning, memory writer,      │
│    rival AI (7-axis decision system)                     │
└─────────────────────┬────────────────────────────────────┘
                      │ event bus (src/event_bus.py)
┌─────────────────────▼────────────────────────────────────┐
│ Interpretation Layer (src/interpretation/*)              │
│  - Pure compute → writes label||phrase to *_descriptors  │
│  - Daily pass (post-commit) + targeted single-fighter    │
│    refreshes via 4 event-bus subscribers                 │
└─────────────────────┬────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────┐
│ Database (data/cage_empire.db — 62 tables, schema 3.26.0)│
│  - 4,514 fighters, 1,714 events, 3,235 fights, 53,669    │
│    beats, 32,889 commentary segments                     │
│  - 7 empty tables (scouting_reports, training_camps,     │
│    division/gym/promotion_descriptors, broadcast_contracts│
│    staff_regen_lineage)                                  │
└──────────────────────────────────────────────────────────┘
```

### 8.5 Next-action recommendations for the comprehensive review

Based on this structural audit, the comprehensive review should investigate:

1. **Why are `scouting_reports` and `training_camps` empty?** Scouting and Training Camps screens are placeholders, but the service layer + schema exist. Is the seed not running? Is the tick not generating them?
2. **Why is `hall_of_fame` only 2 rows** when `hof_svc.py` docstring claims 60 seeded legends? Check `scripts/seed_world_phase5.py` and `scripts/backfill_legends.py`.
3. **Why is `finance_transactions` only 10 rows** for 1,714 events? Is `finance.register_subscribers` actually wired? Is `_process_event_finance` actually firing on `EVENT_COMPLETED`?
4. **Why are `division_descriptors`, `gym_descriptors`, `promotion_descriptors` empty?** These are interpretation caches that should be populated by the daily pass.
5. **Service-layer wrappers are still thin** — `finance_svc`, `news_svc`, `punditry_svc`, `rivalries_svc`, `scouting_svc` are 22-63 line re-export wrappers. The real logic lives in `src/finance.py`, `src/news.py`, etc. Is this intentional or migration debt?
6. **7 placeholder screens** represent unbuilt features: Scouting, Legends (HoF), Finance, Contracts, Training Camps (Gyms), Rivalries, Records. The interpretation layer + services exist for some of these (rivalries_svc, hof_svc, scouting_svc, finance_svc) — but no UI consumes them.
7. **No JS/e2e tests** — all 51 test files are backend Python. Frontend has no test coverage. A regression in `bridge.js` or any screen renderer would only be caught manually.
8. **`fight_engine.py` is 6,337 lines** — single largest file. Worth splitting for maintainability (beat scoring, fatigue, finishes, commentary, doctor stoppage could be separate modules).
9. **`matchmaking.js` + `matchmaking.css` = 4,070 lines** — biggest UI surface. The card-confirmation flow (MM1.4) + 4 modals (Tale of Tape, Stakes, Fan Pulse, Compare) add up.
10. **Schema version is 3.26.0** with 37 migrations — schema is mature, no major schema changes implied by the placeholder screens (they all have backing tables already).

---

## Appendix A: File counts (for context)

- Python source files (`src/`): ~50 files (excluding legacy UI, assets, portraits).
- JS source files (`src/web/js/`): 16 files, 12,444 lines.
- CSS source files (`src/web/css/`): 17 files, 10,345 lines.
- Test files (`scripts/test_*.py`): 51 files.
- Docs (`docs/`): 47 markdown files (planning, research, audits, fix plans).
- Agent context (`agent-ctx/`): 22 markdown files (task briefs from prior agents).
- DB migrations applied: 37.
- DB tables: 62.
- DB rows (key tables): 4,514 fighters, 1,714 events, 3,235 fights, 53,669 fight beats, 32,889 commentary segments, 2,319 news items, 390 rivalries, 763 memory links, 216 player decisions, 435 daily headlines, 672 daily echoes.

This document is the structural foundation. The comprehensive review should layer findings about *correctness*, *completeness*, *performance*, and *player experience* on top of this map.
