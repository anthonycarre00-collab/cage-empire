# Phase 5 Plan — UI/UX Polish for Web UI (v7 Phase 4)

**Date:** 2026-08-17
**Status:** PLANNING ONLY — no code changes yet
**Task ID:** PHASE5-UI-POLISH (next sequential phase after Phase 4 economics)
**Prerequisites:** v7 Phases 1, 2, 3 complete (data bugs, code bugs, economics tuning) + Economics Phase 4 (PPV/bonus/venue deviations fix). All in commits `c7220d7`, `690360b`, `0d8a2dc`.
**Active UI:** pywebview desktop app — `src/app_web.py` (14,898 LOC, 162 API methods) + `src/web/` (24 JS modules, 17,281 LOC; 24 CSS files, 14,544 LOC; index.html 158 LOC).

---

## Background

The v7 plan (`NEXT_LEVEL_PLAN_V4.md` Phase 4, lines 113-121) defines 4 UI/UX polish items for the WEB UI (pywebview desktop app, NOT CTk — the CTk UI redesign work was deleted in commit `c7220d7` and is permanently gone):

| # | v7 Item | Source | Status |
|---|---|---|---|
| 12 | Dashboard redesign per ChatGPT §13 (sports newsroom hierarchy) | v7 plan §Phase 4 line 114 | **Partially done** — dashboard.js already has 8 sections including Gradient Header + Top Story + Promotion Status + Next Event + Fighter Watch + Champions + Recent Results + Recent News. Needs review against ChatGPT §13 hierarchy + visual richness gaps closed. |
| 13 | Player watchlist (minimal, using player_decisions data) | v7 plan §Phase 4 line 116 | **NOT STARTED** — no watchlist functionality exists anywhere in the codebase. player_decisions table is empty (0 rows). Net-new feature. |
| 14 | Screen audit (all 24 screens for voice vs raw numbers, performance, data freshness) | v7 plan §Phase 4 line 118 | **NOT STARTED** — no comprehensive audit done since the v7 plan was written. |
| 15 | Attribute colour scheme verification | v7 plan §Phase 4 line 120 | **Exists, needs verification** — fighter_profile.js lines 75-93 + 562-563 already implement the 3-tier (gold/crimson/steel) scheme. Just need to confirm it renders correctly after the descriptor backfill. |

Plus 1 new item added per user direction (2026-08-17):
| 16 | Visual richness elements (web-native) — gradients, sparklines, trend arrows, momentum rings, form meters | Adapted from deleted CTk Phase 2 Visual Richness Library, re-implemented as web tech | **Not in v7 plan** — user requested 2026-08-17: "if we need some visual richness libraries or whatever add it to the list somewhere" |

---

## Active UI Inventory (verified 2026-08-17)

### 24 web screens (all in `src/web/js/` + `src/web/css/`)

| # | Screen | JS module (LOC) | CSS file (LOC) | API method |
|---|---|---|---|---|
| 1 | Dashboard | `dashboard.js` (740) | `dashboard.css` (649) | `get_dashboard_data(promo_id)` |
| 2 | Roster | `roster.js` (443) | `roster.css` (335) | `get_roster_data(promo_id, page, filters)` |
| 3 | Fighter Profile | `fighter_profile.js` (970) | `fighter_profile.css` (648) | `get_fighter_profile_data(fighter_id)` |
| 4 | Calendar | `calendar.js` (514) | `calendar.css` (612) | `get_calendar_data(month, year)` |
| 5 | Event Builder | `event_builder.js` (1,269) | `event_builder.css` (985) | `get_event_builder_data()` |
| 6 | Fight Night | `fight_night.js` (1,414) | `fight_night.css` (1,371) | `get_fight_night_data(fight_id)` |
| 7 | Matchmaking | `matchmaking.js` (2,179) | `matchmaking.css` (2,348) | `get_matchmaking_data(event_id)` |
| 8 | Rankings | `rankings.js` (396) | `rankings.css` (482) | `get_rankings_data(weight_class_id, gender)` |
| 9 | Titles | `titles.js` (341) | `titles.css` (373) | (via dashboard / fighter_profile) |
| 10 | Rivalries | `rivalries.js` (485) | `rivalries.css` (395) | `get_rivalries_data(page, filters)` |
| 11 | Hall of Fame | `hall_of_fame.js` (341) | `hall_of_fame.css` (293) | `get_hof_data(page, filters)` |
| 12 | Records | `records.js` (250) | `records.css` (352) | (via dashboard / archive) |
| 13 | Archive | `archive.js` (555) | `archive.css` (512) | `get_archive_data(page, filters)` |
| 14 | Free Agents | `free_agents.js` (971) | `free_agents.css` (408) | `get_free_agents(page, filters)` |
| 15 | Agent Offers | `agent_offers.js` (418) | `agent_offers.css` (316) | `get_bidding_alerts()` |
| 16 | Contracts | `contracts.js` (608) | `contracts.css` (495) | (via roster / finance) |
| 17 | Finance | `finance.js` (523) | `finance.css` (648) | (via dashboard + finance_transactions) |
| 18 | Rival Promotions | `rival_promotions.js` (484) | `rival_promotions.css` (189) | `get_rival_promotions()` |
| 19 | Gyms | `gyms.js` (704) | `gyms.css` (471) | (via scouting / fighter_profile) |
| 20 | Scouting | `scouting.js` (731) | `scouting.css` (572) | `get_scouting_data()` + `get_scouting_report(report_id)` |
| 21 | Staff Market | `staff_market.js` (722) | `staff_market.css` (147) | `get_staff_market_data(page, filters)` |
| 22 | Wire (news feed) | `wire.js` (380) | `wire.css` (308) | `get_wire_data(page, filters)` |
| — | Shell + app | `app.js` (1,298) + `bridge.js` (545) | `shell.css` (991) + `theme.css` (197) + `components.css` (289) | (window shell, navigation, save/load modal) |

### Existing theme + components
- `theme.css` (197 lines) — already has the 4-tier bg system (`--bg-base` `#0a0c10`, `--bg-surface` `#15181f`, `--bg-card` `#1c2028`, `--bg-card-elevated` `#252a33`), brand accents (crimson `#d63a3f`, gold `#e0a957`, gold-bright `#f5c878`), tints for hover, font tokens (Oswald for display, Inter for body, JetBrains Mono for numerics, Source Serif Pro for commentary).
- `components.css` (289 lines) — has shared component classes (`.ce-card`, `.ce-chip`, `.ce-stat-bar`, `.ce-accent-bar`, `.ce-sec-header`, etc.) used across all 24 screens.
- Fonts: Oswald-Bold, Inter (4 weights), JetBrains Mono, Source Serif Pro (4 weights) — all bundled locally in `src/web/assets/fonts/` (works offline).

### Dashboard current state (verified)
`dashboard.js` (740 lines) already has 8 sections:
1. Welcome + Logo
2. Gradient Header ("THE EMPIRE") — uses CSS gradient
3. Top Story (gold-bordered card)
4. Promotion Status (5 stat tiles)
5. Next Event
6. Fighter Watch (3 cards: momentum ring + form meter)
7. Champions (3-col grid)
8. Recent Results (4-col grid) + Recent News (vertical list)

It uses `MOMENTUM_RING` (5 tiers with color + pct fill), `ratingTier()` (rating→phrase+color), `formatCash()` with Billion branch. Data via `window.CE.bridge.getDashboardData(promo_id)` → `Api.get_dashboard_data(promo_id)` (line 2293 of app_web.py, ~450 lines of query logic).

### What's NOT on the Dashboard yet (visual richness gaps)
Comparing to the deleted CTk Phase 2.5 Dashboard spec (`UI_REDESIGN_VISUAL_PLAN.md` §6.1):
- ❌ No SVG sparkline for 7-day cash history (CTk had it via PIL)
- ❌ No trend arrows (▲▼●) with signed delta on stat tiles
- ❌ No CSS-animated stat bar fill (CTk had 400ms ease-out)
- ❌ No form meter with W/L blocks for last 5 fights (CTk had gold/crimson blocks)
- ❌ No CSS gradient banner at top (the "Gradient Header" exists but may just be a flat color — need to verify)
- ❌ Fighter Watch cards don't show FormMeter (only MomentumRing)
- ❌ No voice italic phrase under each fighter name on watch cards

### Watchlist state
- `player_decisions` table is EMPTY (0 rows). Schema has `decision_type`, `target_fighter_id`, `target_staff_id`, `target_event_id`, `target_promo_id`, `decision_date`, `context_json`.
- No `watch` decision_type exists yet — we'll need to add it (schema is TEXT, no CHECK constraint, so no migration needed).
- No `Api.add_to_watchlist` / `Api.remove_from_watchlist` / `Api.get_watchlist` methods exist.
- No JS-side watchlist UI exists.
- The player_promotion setting exists (`player_settings.setting_key='player_promotion_id'`) — watchlist will be scoped to the player's promotion.

### Attribute color scheme state
- `fighter_profile.js` lines 75-93: `attributeTier(phrase)` maps elite phrases → 'gold', weak phrases → 'crimson', default → 'steel'.
- `fighter_profile.js` lines 562-563: tier→pct mapping (gold=100%, steel=60%, crimson=25%) for stat bar fill width.
- Need to verify: (a) the elite/weak phrase lists are complete, (b) the scheme renders correctly on a real fighter (gold bar fully filled, crimson bar 25% filled, steel bar 60% filled), (c) all 26 attributes use the scheme consistently.

---

## Implementation Plan

### Order (informed by dependencies)

**Task 1 — Screen Audit** (read-only, ~1 day, Explore subagent)
→ produces findings that inform Tasks 2-4
**Task 2 — Dashboard Redesign + Visual Richness** (~2 days, general-purpose subagent, 2 subagents in parallel)
→ biggest piece, depends on Task 1 findings
**Task 3 — Player Watchlist** (~1 day, general-purpose subagent, parallel with Task 2)
→ independent of Task 2 (uses player_decisions, doesn't touch Dashboard JS structure)
**Task 4 — Attribute Colour Verification** (~0.5 day, Explore subagent)
→ independent, can run in parallel with Tasks 2-3

Total estimated wall-clock: **~2.5 days** with parallelism (vs 4-5 days sequential).

---

### Task 1 — Screen Audit (Explore subagent, read-only)

**Scope:** Read all 24 web screens (JS + CSS) + their corresponding API methods in `app_web.py`. Produce a structured audit report.

**Audit dimensions (per v7 plan §Phase 4 line 118):**
1. **Voice vs raw numbers** — flag every place where a raw attribute number, potential rating, or internal rating is shown directly instead of routed through the interpretation layer (CONVENTIONS §14 violation). Check both JS rendering AND app_web.py query responses.
2. **Performance** — flag queries without LIMIT/OFFSET pagination, N+1 query patterns, missing indexes (check `data/cage_empire.db` `PRAGMA index_list`), JS render loops that could jank on 100+ row result sets.
3. **Data freshness** — flag any screen that reads from simulation tables (fighters, fights, events, contracts) directly instead of the cache tables (fighter_descriptors, gym_descriptors, promotion_descriptors, division_descriptors, daily_headlines) per CONVENTIONS §17.1.

**Deliverable:** `docs/PHASE5_SCREEN_AUDIT.md` with:
- One section per screen (24 sections)
- Each section lists: voice violations (with line numbers), performance issues (with line numbers), data freshness violations (with line numbers)
- Summary table at end: top 10 highest-impact issues, recommended fix order
- NO code changes — audit only

**Acceptance criteria:**
- [ ] All 24 screens covered
- [ ] Each violation has a file:line citation
- [ ] Summary identifies the top 10 issues by impact
- [ ] No false positives (every flagged violation is a real violation)

---

### Task 2 — Dashboard Redesign + Visual Richness (general-purpose subagent)

**Scope:** Close the visual richness gaps on the Dashboard + reorganize sections per ChatGPT §13 sports newsroom hierarchy. NO new screens, NO schema changes, NO new API methods (use existing `get_dashboard_data` response).

**ChatGPT §13 sports newsroom hierarchy** (the target structure):
1. **Today's Story** — the single most important thing happening RIGHT NOW (next event's main event, or a major news item if no event scheduled)
2. **Promotion Status** — cash (with sparkline), reputation, fan trust, roster count, champions count
3. **Important Fighters** — 3 watch cards (hottest streak, coldest streak, top prospect)
4. **Upcoming** — next 1-3 scheduled events
5. **What Changed** — recent transactions / signings / injuries (last 7 days)
6. **Threats** — financial warnings, injured champions, expiring contracts
7. **Opportunities** — title fight opportunities, free agent targets, rivalry heat
8. **World Stories** — top 3-5 news items from other promotions

The current Dashboard has 8 sections but they're in a different order + miss "What Changed", "Threats", "Opportunities", "World Stories" as distinct sections. The redesign will:
- Reorder existing sections to match §13 hierarchy
- Add 4 new sections (What Changed, Threats, Opportunities, World Stories) — pulling from existing `get_dashboard_data` response fields (no new API methods needed; the response already returns news_items, finance_transactions, rival_promotions, etc.)
- Close visual richness gaps (see below)

**Visual richness elements to add (web-native, NO new dependencies):**

| Element | Tech | Where it goes | Source concept |
|---|---|---|---|
| CSS gradient banner | `linear-gradient(135deg, var(--gold), var(--bg-card))` on `.ce-gradient-header` | Top of Dashboard (replace flat color) | CTk GradientHeader |
| SVG sparkline | Inline `<svg>` with `<polyline>` for 7-day cash history | Cash stat tile | CTk Sparkline (PIL) |
| Trend arrow + delta | ▲▼● unicode + signed delta in mono font | All 5 stat tiles (cash, rep, trust, roster, champions) | CTk TrendIndicator |
| CSS-animated stat bar fill | `transition: width 400ms ease-out` on `.ce-stat-bar-fill` | Career health bar (already exists, just add transition) | CTk AttributeBar animation |
| Form meter W/L blocks | Flexbox row of 5 16×16 `<div>` blocks, gold for W, crimson for L, steel for D | Fighter Watch cards (3 cards × 5 blocks) | CTk FormMeter |
| CSS-animated momentum ring | `<svg><circle>` with `stroke-dasharray` + `transition: stroke-dashoffset 600ms ease` | Fighter Watch cards (already has the ring, verify animation) | CTk MomentumRing |
| Voice italic phrase | `<div class="descriptor-small">` with the voice phrase from fighter_descriptors | Under each Fighter Watch card name | CTk voice compliance |

**Implementation constraints:**
- All visual richness must use vanilla JS + CSS + inline SVG. NO new dependencies (no Chart.js, no D3, no React). The pywebview environment runs whatever Chromium ships with the system, so stick to features supported in Chrome 90+.
- All new CSS goes in `dashboard.css` (extend the existing 649-line file, don't create new files).
- All new JS goes in `dashboard.js` (extend the existing 740-line file).
- The `get_dashboard_data` API response may need 1-2 new fields added (e.g., `cash_history` array, `yesterday_cash` for trend delta). These go in `app_web.py` `get_dashboard_data()` method (line 2293, ~450 lines) — extend, don't rewrite.
- NO breaking changes to existing response fields (other screens may consume them).
- Voice compliance (CONVENTIONS §14): NO raw attribute numbers anywhere. All fighter data must come from `fighter_descriptors` and display as italic voice phrases.

**Deliverable:**
- Modified `src/web/js/dashboard.js` (rewritten rendering layer, preserve all data queries + `_refresh` callback)
- Modified `src/web/css/dashboard.css` (extended with new component classes)
- Modified `src/app_web.py` `get_dashboard_data()` method (added 1-2 new response fields only)
- NO new files, NO new schema, NO new dependencies

**Acceptance criteria:**
- [ ] Dashboard sections reordered to match ChatGPT §13 hierarchy
- [ ] 4 new sections added (What Changed, Threats, Opportunities, World Stories) using existing API response data
- [ ] SVG sparkline renders on Cash stat tile with 7-day history
- [ ] Trend arrows (▲▼●) + signed delta on all 5 stat tiles
- [ ] CSS gradient banner at top (not flat color)
- [ ] Form meter (5 W/L blocks) on each Fighter Watch card
- [ ] Voice italic phrase under each Fighter Watch card name
- [ ] Career health stat bar has 400ms ease-out transition on width change
- [ ] Momentum ring has 600ms ease transition on stroke-dashoffset
- [ ] 8/8 invariants PASS
- [ ] `app_web.py` imports OK
- [ ] Dashboard renders without JS errors on promo_id=1 (live DB)
- [ ] Dashboard renders without JS errors on empty DB (all sections show EmptyState gracefully)

---

### Task 3 — Player Watchlist (general-purpose subagent)

**Scope:** Net-new feature. Player can mark fighters as "watched" from the Fighter Profile screen + Roster screen. Watched fighters appear in a new "Watchlist" section on the Dashboard. Watchlist is scoped to the player's promotion (only fighters on the player's promo can be watched).

**Schema:** Use existing `player_decisions` table — no new table, no migration. Add 2 new decision_types:
- `'watch'` — fighter added to watchlist. `target_fighter_id` set, `context_json` = `{"reason": "manual"|"auto-title-threat"|"auto-expiring-contract", "added_at": "2026-08-17"}`.
- `'unwatch'` — fighter removed from watchlist. `target_fighter_id` set, `context_json` = `{"reason": "manual"|"auto-promotion"|"auto-retired"}`.

Query pattern: `SELECT * FROM player_decisions WHERE decision_type='watch' AND target_fighter_id NOT IN (SELECT target_fighter_id FROM player_decisions WHERE decision_type='unwatch' AND decision_date > watch.decision_date)`. This gives the "currently watched" set without schema changes.

**API methods (add to `app_web.py`):**
- `Api.add_to_watchlist(fighter_id, reason='manual')` — INSERT a 'watch' row
- `Api.remove_from_watchlist(fighter_id, reason='manual')` — INSERT an 'unwatch' row
- `Api.get_watchlist(promo_id)` — SELECT currently-watched fighters for the given promo's fighters, join fighter_descriptors for voice phrases

**UI:**
- **Fighter Profile** (`fighter_profile.js`): add a "★ Watch" / "★ Unwatch" button in the header next to the fighter name. Star icon fills gold when watched.
- **Roster** (`roster.js`): add a star icon column. Click toggles watch state.
- **Dashboard** (`dashboard.js`): if `Api.get_watchlist()` returns ≥1 fighter, show a "Watchlist" section between "Important Fighters" and "Upcoming" with up to 6 watch cards (reuse the Fighter Watch card layout — MomentumRing + FormMeter + voice phrase + portrait).

**Implementation constraints:**
- NO new tables. NO migrations. The `player_decisions` schema already supports this (decision_type is TEXT, no CHECK constraint).
- All new API methods go in `app_web.py` (extend, don't rewrite).
- All new JS goes in the existing files (`fighter_profile.js`, `roster.js`, `dashboard.js`).
- All new CSS goes in the existing files (`fighter_profile.css`, `roster.css`, `dashboard.css`).
- Watchlist is read-only on the Dashboard (no add/remove from Dashboard — only from Fighter Profile + Roster).
- Watchlist capped at 12 fighters per promotion (return only top 12 by watch decision_date DESC).
- Voice compliance: watched fighter cards show voice phrases (momentum, recent form), not raw attribute numbers.

**Deliverable:**
- Modified `src/app_web.py` (3 new API methods)
- Modified `src/web/js/fighter_profile.js` (★ Watch button in header)
- Modified `src/web/js/roster.js` (★ column in table)
- Modified `src/web/js/dashboard.js` (new Watchlist section, conditional render)
- Modified `src/web/css/fighter_profile.css` + `roster.css` + `dashboard.css` (star button styles, watch card styles)

**Acceptance criteria:**
- [ ] `Api.add_to_watchlist(5)` inserts a 'watch' row in player_decisions
- [ ] `Api.remove_from_watchlist(5)` inserts an 'unwatch' row, which overrides the prior 'watch'
- [ ] `Api.get_watchlist(1)` returns currently-watched fighters (excludes unwatched)
- [ ] Fighter Profile screen shows ★ Watch button; clicking it toggles to ★ Unwatch (gold-filled star)
- [ ] Roster screen shows ★ column; clicking toggles watch state for that fighter
- [ ] Dashboard shows Watchlist section when ≥1 fighter is watched; hides section when 0 watched
- [ ] Watchlist section shows up to 6 fighter watch cards with voice phrases (not raw numbers)
- [ ] 8/8 invariants PASS
- [ ] `app_web.py` imports OK
- [ ] Watchlist is scoped to player's promotion (can't watch fighters on other promos)

---

### Task 4 — Attribute Colour Verification (Explore subagent, read-only)

**Scope:** Verify the existing 3-tier attribute colour scheme (gold/crimson/steel) in `fighter_profile.js` renders correctly on real fighters after the descriptor backfill (v7 Phase 1, commit `c7220d7`).

**Audit dimensions:**
1. **Phrase list completeness** — `attributeTier(phrase)` (lines 75-93 of fighter_profile.js) has an `eliteWords` list (gold) and a `weakWords` list (crimson). Verify these lists cover ALL phrases actually used in `fighter_descriptors.attribute_*` columns. Sample 100 fighters from the DB, pull their attribute descriptors, check that every phrase maps to a tier (no `steel` fallback for phrases that should be gold/crimson).
2. **Render correctness** — open fighter_profile.js on 5 sample fighters (1 elite, 1 above-avg, 1 avg, 1 below-avg, 1 weak) and verify:
   - Elite attributes show gold bar at 100% width + gold-colored label
   - Above-avg attributes show steel bar at 60% width
   - Avg attributes show steel bar at 60% width
   - Below-avg attributes show steel bar at 60% width
   - Weak attributes show crimson bar at 25% width + crimson-colored label
3. **Consistency** — verify ALL 26 attributes use the same `attributeTier()` function (no attribute has a custom color path that bypasses the scheme).
4. **Edge cases** — verify NULL/empty descriptors render as steel (not as a missing bar or empty space).

**Deliverable:** `docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md` with:
- Phrase coverage table (every phrase in DB → its tier)
- Render verification screenshots (or text descriptions of the rendered output for 5 sample fighters)
- List of missing phrases (if any) that should be added to `eliteWords` or `weakWords`
- Consistency check results

**Acceptance criteria:**
- [ ] All phrases in fighter_descriptors map to a tier (no unexpected `steel` fallbacks for phrases that should be gold/crimson)
- [ ] 5 sample fighters verified to render correctly
- [ ] All 26 attributes use `attributeTier()` consistently
- [ ] NULL/empty descriptors handled gracefully
- [ ] If gaps found, list them with recommended additions to `eliteWords`/`weakWords` (NO code changes in this task — code changes go in a follow-up if needed)

---

## Implementation Order (with parallelism)

```
Day 1 (morning):
  Task 1 — Screen Audit (Explore subagent, read-only)
  Task 4 — Attribute Colour Verification (Explore subagent, read-only)
  [both run in parallel — no dependencies between them]

Day 1 (afternoon, after Task 1 returns):
  Task 2 — Dashboard Redesign + Visual Richness (general-purpose subagent)
  Task 3 — Player Watchlist (general-purpose subagent)
  [both run in parallel — Task 3 doesn't touch Dashboard JS structure]

Day 2:
  Supervisor reviews Tasks 2 + 3 outputs
  Run invariant_checker
  Run app_web import test
  Run soak_test.py 7 (1-week soak to catch regressions)
  Commit + push
  Update worklog with PHASE5-UI-POLISH-SIGNOFF
```

---

## Subagent Delegation Strategy

| Task | Subagent type | Why |
|---|---|---|
| 1 (Screen Audit) | Explore | Read-only survey, no code changes, needs thorough file reading across 24 screens + app_web.py |
| 2 (Dashboard Redesign) | general-purpose | Code changes to dashboard.js + dashboard.css + app_web.py (1-2 new response fields). Needs to understand existing rendering layer + extend it. |
| 3 (Player Watchlist) | general-purpose | Code changes to 3 JS files + 3 CSS files + 3 new API methods in app_web.py. Net-new feature but well-scoped. |
| 4 (Attribute Colour Verification) | Explore | Read-only verification, needs to sample DB + read JS + render visual check (via text descriptions of expected output). |

For Tasks 2 + 3, the supervisor (me) will:
1. Pass each subagent a self-contained spec (this plan + the relevant audit findings from Task 1)
2. Tell them to read `/home/z/my-project/worklog.md` first (especially the last ~100 lines for context)
3. Tell them their Task ID (e.g., `PHASE5-T2-DASHBOARD`)
4. Tell them to append their work record to `/home/z/my-project/worklog.md` using the standard template
5. Review their output: verify invariants PASS, app_web imports OK, no regressions
6. Commit + push on their behalf (subagents don't have git access in this setup)

---

## What we're NOT doing

- ❌ NO new screens (all 24 are implemented)
- ❌ NO new schema/tables (player_decisions already supports watchlist)
- ❌ NO new dependencies (no Chart.js, no D3, no React — vanilla JS + CSS + SVG only)
- ❌ NO fight engine changes
- ❌ NO news system changes
- ❌ NO memory resurfacing changes (verified working in Phase 3)
- ❌ NO restoration of deleted CTk UI (per user direction 2026-08-17)
- ❌ NO long-run soaks in this phase (that's v7 Phase 5 — separate task)

---

## Success criteria

- [ ] Screen audit complete (Task 1) — `docs/PHASE5_SCREEN_AUDIT.md` produced
- [ ] Dashboard redesigned per ChatGPT §13 hierarchy + visual richness gaps closed (Task 2)
- [ ] Player watchlist functional end-to-end (Task 3)
- [ ] Attribute colour scheme verified (Task 4) — `docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md` produced
- [ ] 8/8 invariants PASS
- [ ] `app_web.py` imports OK
- [ ] 7-day soak test: all 10 promos stay HEALTHY, 0 tick errors
- [ ] No new schema/tables/dependencies
- [ ] Committed + pushed
- [ ] Worklog updated with PHASE5-UI-POLISH-SIGNOFF entry
