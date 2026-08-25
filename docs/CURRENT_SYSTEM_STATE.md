# CAGE EMPIRE — Current System State

> **Single source of truth** for what exists, what works, and what's
> known to be broken in CAGE EMPIRE as of the Hardening Phase (HW1–HW10 + Tier 1-4).
>
> **Status:** Canonical — supersedes all earlier planning docs.
> **Last updated:** 2026-08-25 (post-Phase 7 cleanup + 5y soak analysis).
> **Schema version:** 3.37.0 (recorded in `schema_meta`).
> **ENGINE_VERSION:** 1.10.0 (forces cache rebuild w/ gym + promotion descriptors).
> **Sim clock:** 2026-08-25 (clean game-start state — restored after 5y soak analysis).
> **See also:** `docs/Hardening_Phase.md` (the canonical hardening plan),
> `docs/GPT_PLAN_AUDIT.md` (W1-W48 compliance audit),
> `docs/PHASE5_SCREEN_AUDIT.md` (Phase 5 audit — 34 violations),
> `docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md` (phrase coverage 94.4% → 100%),
> `docs/PHASE6_PLAN.md` (Phase 6 plan — audit remediation),
> `docs/PHASE7_PLAN.md` (Phase 7 plan — cleanup + long-run soaks),
> `docs/PHASE7_SOAK_ANALYSIS.md` (5y soak results — 9/10 promos REBUILDING).

---

## 1. What exists — All 22 screens

The web UI (`src/web/`) is the active UI. The legacy Tkinter UI
(`src/ui_legacy/`) was removed in the NEWS-FINANCE-GYM-LEGACY
sweep (Issue 9) — the web UI now has full save/load support via
the `save_game` / `load_game` API methods in `src/app_web.py`.
The 22 screens are:

| #  | Screen                  | JS module                        | Backend module                        |
|----|-------------------------|----------------------------------|---------------------------------------|
| 1  | Dashboard               | `src/web/js/dashboard.js`        | `src/app.py` (refresh_all)            |
| 2  | Roster                  | `src/web/js/roster.js`           | `src/app.py` + `src/services/contracts.py` |
| 3  | Fighter Profile         | `src/web/js/fighter_profile.js`  | `src/app.py` + `src/services/scouting.py` |
| 4  | Calendar                | `src/web/js/calendar.js`         | `src/app.py`                          |
| 5  | Event Builder           | `src/web/js/event_builder.js`    | `src/services/matchmaking.py`         |
| 6  | Fight Night             | `src/web/js/fight_night.js`      | `src/services/fight_engine.py`        |
| 7  | Matchmaking             | `src/web/js/matchmaking.js`      | `src/services/matchmaking.py`         |
| 8  | Rankings                | `src/web/js/rankings.js`         | `src/app.py`                          |
| 9  | Titles                  | `src/web/js/titles.js`           | `src/app.py` + `src/services/fight_engine.py` |
| 10 | Rivalries               | `src/web/js/rivalries.js`        | `src/rivalries.py` + `src/services/rivalries_svc.py` |
| 11 | Hall of Fame            | `src/web/js/hall_of_fame.js`     | `src/services/hof_svc.py`             |
| 12 | Records                 | `src/web/js/records.js`          | `src/app.py`                          |
| 13 | Archive                 | `src/web/js/archive.js`          | `src/app.py`                          |
| 14 | Free Agents             | `src/web/js/free_agents.js`      | `src/services/contracts.py`           |
| 15 | Agent Offers            | `src/web/js/agent_offers.js`     | `src/agent_offers.py`                 |
| 16 | Contracts               | `src/web/js/contracts.js`        | `src/services/contracts.py`           |
| 17 | Finance                 | `src/web/js/finance.js`          | `src/finance.py` + `src/services/finance_svc.py` |
| 18 | Rival Promotions        | `src/web/js/rival_promotions.js` | `src/rival_ai.py`                     |
| 19 | Gyms                    | `src/web/js/gyms.js`             | `src/app.py`                          |
| 20 | Scouting                | `src/web/js/scouting.js`         | `src/scouting.py` + `src/services/scouting_svc.py` |
| 21 | Staff Market            | `src/web/js/staff_market.js`     | `src/app.py`                          |
| 22 | Save/Load               | `src/web/js/app.js` (modal)      | `src/app_web.py` (Api.save_game / Api.load_game) + `src/save_load.py` |

The web shell (`src/web/index.html` + `app.js` + `bridge.js` + `wire.js`)
loads all 22 web screens into a tabbed SPA. The Save/Load screen is a
modal triggered from the header — calls `Api.save_game(name)` /
`Api.load_game(name)` which delegate to `save_load.save_game` /
`save_load.load_game` (file-copy + WAL checkpoint + .meta.json sidecar
+ 4-step compatibility check).

### Phase 5 + 6 + 7 changes (post-Hardening)

- **Player Watchlist** (Phase 5 Task 3) — 3 API methods on `app_web.py`:
  `add_to_watchlist`, `remove_from_watchlist`, `get_watchlist`. Piggy-
  backs on the existing `player_decisions` table with cap = 12 watched
  fighters per promo. UI: ★ toggle button on Fighter Profile + Roster
  row + a dedicated "Your Watchlist" section on the Dashboard.
- **Dashboard redesign** (Phase 5 Task 2, commit `3672ebf`) — rebuilt
  per ChatGPT §13 sports-newsroom hierarchy. Adds 5 new sections:
  Watchlist, What Changed (today's events), Threats (low morale /
  financial state / rival heat), Opportunities (title shots, expiring
  contracts), World Stories (rotating news). Plus 7 visual richness
  elements: CSS gradient banner, SVG sparkline (cash history), trend
  arrows (real delta vs yesterday), animated stat bar (CSS transition),
  form-meter W/L blocks (per-fighter recent form), animated momentum
  ring (SVG stroke-dasharray), voice italic phrases throughout.
- **Attribute phrase coverage** (Phase 5 Task 2.5) — `phraseTier()`
  helper in `fighter_profile.js:75-94` had a substring-match bug
  ("explosive" matched "serviceable explosiveness"). Fixed with
  word-boundary regex. Coverage 94.4% → 100% (4 false-positive GOLD +
  21 fall-through-to-STEEL phrases corrected). Audit report:
  `docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md`.
- **Matchmaking radar chart** (Phase 6 Task B1) — was leaking raw
  25-attribute 0-100 ints via `get_fight_compare`. Now uses tier pct
  (gold=100%, steel=60%, crimson=25%) derived from voice phrases.
  Polygon points are tier-based, not raw-attribute-based. Hover shows
  the voice phrase.
- **Gyms + Rival Promotions screens** (Phase 6 Tasks B4 + B8) — were
  reading from the `gyms` / `promotions` simulation tables directly
  and returning raw 0-100 ints. Now JOIN the `gym_descriptors` /
  `promotion_descriptors` cache tables per CONVENTIONS §17.1 + return
  voice phrases. Raw ints are dropped from JSON (Phase 7 Group A).
- **Voice compliance fixes** (Phase 6 Tasks B5 + B6) — Fighter Profile
  `career_health` now displays the voice phrase; Rivalries `rivalry_heat`
  shows the phrase only (raw int kept for bar width per §17.4 carve-out).
- **N+1 query fixes** (Phase 6 Tasks B2, B3, C1, C2) — Matchmaking,
  Event Builder, Roster, Rankings all batched via JOINs. 400+ queries
  per Matchmaking screen load → 1 query.

---

## 2. What works (verified by tests)

The test suite in `scripts/test_*.py` covers 50+ acceptance tests
(most run on a fresh test DB). The canonical end-to-end tests:

- `test_event_lifecycle_e2e.py` — Gate 1: schedule → resolve →
  finance → show rating → rankings → news → memory.
- `test_finance_wiring.py` — Finance fires on completed events.
- `test_save_load.py` (83 checks) — Save/load round-trip + auto-save
  + .meta.json sidecar (HW5.2).
- `test_news.py` (55 checks) — News importance tiers (HW4.1–4.3).
- `test_social.py` (61 checks) — Social posts + HW5.4 date clamp.
- `test_pre_b1_fixes.py` (82 checks, was 69/75) — champion retirement
  + regen + memory-link assertions. Phase 7 Group C fixed the
  deterministic-clock + link_type filter issues → 82/82 PASS.
- `invariant_checker.py` — 8 invariants on the world DB (8/8 PASS
  after HW5.1).

### Systems verified working

- **Event lifecycle**: schedule → card_confirmed → completed →
  finance fires → show rating → rankings → news → memory.
- **Fight engine**: round-by-round resolution, beats, commentary,
  injuries, suspensions, title changes, fight_history writing.
- **Finance**: per-event transactions (purse, bonus, venue rental,
  sponsorship, weight_cut_penalty), gradient financial_state
  machine (HEALTHY → STABLE → STRAINED → DISTRESSED → CRITICAL →
  BANKRUPT → REBUILDING).
- **Career arc**: debuts, retirements (auto + age/injury-driven),
  regen (replacement fighter generation with regen_lineage tracking).
- **Rivalries**: pairwise rivalries seeded from social-media beefs +
  fight outcomes, with intensity gradient.
- **Memory**: fighter_memory_links (regional_rival, style_echo,
  successor, title_history, upset, comeback, milestone), on-demand
  memory resurfacing (HW3). Phase 6 / v3.8.0 added `populate_style_echo`
  feature — fires on every retirement (champion or non-champion) when
  the regen replacement inherits the retiring fighter's archetype.
- **News**: 5-tier importance system (LEGENDARY/MAJOR/SIGNIFICANT/
  ROUTINE/BACKGROUND) with daily caps (HW4.1–4.3).
- **Echoes**: signing_echo, cut_echo, booking_echo, scouting_echo
  (sparse, decision-linked).
- **Save/load**: file-copy + WAL checkpoint + .meta.json sidecar
  (HW5.2) + 4-step compatibility check (HW5.3).
- **Tick health**: every tick recorded in `simulation_tick_health`
  with subscriber success/failure counts, side-effect counts, error
  JSON (HW2.1).
- **Player Watchlist API** (Phase 5): `add_to_watchlist`,
  `remove_from_watchlist`, `get_watchlist` on `app_web.py`. Cap = 12
  watched fighters per promo. Piggybacks on `player_decisions` table
  with relaxed CHECK constraint (schema 3.37.0).
- **Descriptor cache engines** (Phase 6):
  - `gym_descriptors` populated by `src/interpretation/gym_identity_engine.py`
    (329 rows after Phase 6 commit `0c4c0ed`; was 0). Fields:
    identity_label, known_for, produces, weakness, development_rating_desc.
  - `promotion_descriptors` populated by `src/interpretation/promotion_engine.py`
    (10 rows; was 0). Fields: prestige_desc, market_position_desc,
    roster_quality_desc.
  - Both fire on the daily interpretation pass (post-tick commit).
  - 5-year soak analysis confirmed they stay populated throughout.
- **Matchmaking radar chart** (Phase 6 Task B1): polygon points now
  derived from tier pct (gold=100%, steel=60%, crimson=25%) — no raw
  attribute ints cross the API boundary. Hover shows voice phrase.
- **Voice compliance** (Phase 6 + 7): 7 HIGH + 5 MEDIUM audit
  violations resolved; 13 borderline §17.4 raw-int drops in Phase 7
  Group A (Dashboard, Fighter Brief, Calendar, Training Camps,
  Scouting, Staff Market, Finance, Rivalries JSON).

---

## 3. What is partially implemented

- **Rival AI event scheduler** — schedules events but has a bug
  where events dated months in the future (e.g., 2027-12) are
  marked 'completed' immediately (soak test surfaced this in HW6.3;
  see §5 Known Limitations).
- **Memory resurfacing** — engine architecture is good (4 search
  types, on-demand, voice-layered) but only 4 types return results.
  GPT wants 15 types; HW3 added 11 new link types + 6 new search
  types but the surface_memories caller isn't fully wired into the
  narrative layer yet (only `memory_resurfacing` news items fire,
  and the soak test showed 0 of these generated in 180 days).
- **Echoes** — only signing_echo + cut_echo fire reliably in normal
  play. booking_echo + scouting_echo only fire after the player
  actually books a fight or assigns a scout (verified by HW3.4).
- **Daily headlines** — `daily_headlines` table exists + is
  populated by the daily interpretation pass, but the soak test
  showed 0 echoes generated (no player decisions → no echoes).
- **Hall of Fame** — HoF inductees exist (2–3 in the world DB) but
  the induction criteria are conservative; long sims produce few
  inductees.
- **Staff market** — UI exists, staff table exists, but staff
  lifecycle is shallow (no death/retirement regen loop).
- **Bidding wars** — `bidding_alerts` table exists but the soak
  test showed 0 alerts (the system is wired but rarely triggers).

---

## 3.5. Phase 5-7 Changes (2026-08-16 to 2026-08-25)

### Phase 5 — UI/UX Polish (commit `3672ebf`)

- **Dashboard redesign** per ChatGPT §13 sports-newsroom hierarchy:
  - 5 new sections: Watchlist, What Changed, Threats, Opportunities,
    World Stories.
  - 7 visual richness elements: CSS gradient banner, SVG sparkline
    (cash history), trend arrows (real delta vs yesterday), animated
    stat bar (CSS transition), form-meter W/L blocks, animated momentum
    ring (SVG stroke-dasharray), voice italic phrases throughout.
- **Player Watchlist feature** (Task 3) — 3 API methods
  (`add_to_watchlist`, `remove_from_watchlist`, `get_watchlist`) + ★ UI
  on Fighter Profile + Roster row + Dashboard "Your Watchlist" section.
  Cap = 12 per promo. Piggybacks on `player_decisions` table.
- **Attribute phrase coverage** 94.4% → 100% (Task 2.5): word-boundary
  regex fix in `phraseTier()` (`fighter_profile.js:75-94`). 4
  false-positive GOLD + 21 fall-through-to-STEEL phrases corrected.
- **Schema 3.36.0 → 3.37.0**: relaxed `player_decisions.decision_type`
  CHECK constraint to allow `watch` / `unwatch` decision types.
- **2 audit reports**: `docs/PHASE5_SCREEN_AUDIT.md` (34 violations
  found — 7 HIGH, 18 MEDIUM, 9 LOW) + `docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md`
  (full DB-wide phrase coverage analysis).

### Phase 6 — Audit Findings Remediation (commits `0c4c0ed` + `c01f6f1`)

- **Group A — Cache engine foundations**:
  - NEW file `src/interpretation/gym_identity_engine.py` — populates
    `gym_descriptors` cache (0 → 329 rows). Fields: identity_label,
    known_for, produces, weakness, development_rating_desc.
  - NEW file `src/interpretation/promotion_engine.py` — populates
    `promotion_descriptors` cache (0 → 10 rows). Fields: prestige_desc,
    market_position_desc, roster_quality_desc.
  - `ENGINE_VERSION` bumped 1.9.0 → 1.10.0 (forces cache rebuild).
- **Group B+C — 9 audit-finding fixes** (7 HIGH + 5 MEDIUM resolved):
  - **B1**: Matchmaking radar chart raw 25 attributes → tier pct +
    voice phrases (per `phraseTier()`).
  - **B2**: Matchmaking N+1 query → batched JOIN (400+ queries → 1).
  - **B3**: Event Builder N+1 → JOIN `fighter_career`.
  - **B4**: Gyms screen reads from `gym_descriptors` cache (not `gyms`
    simulation table); voice phrases replace raw 0-100 ints.
  - **B5**: Fighter Profile `career_health` → voice phrase (raw int
    kept for bar width per §17.4 carve-out).
  - **B6**: Rivalries `rivalry_heat` → phrase only in UI (raw int
    kept for bar width).
  - **B8**: Rival Promotions reads from `promotion_descriptors` cache.
  - **C1**: Roster per-row subqueries → LEFT JOIN + GROUP BY.
  - **C2**: Rankings per-row subquery → LEFT JOIN MAX(fight_history_id).

### Phase 7 — Cleanup + Documentation + Long-Run Validation

- **Group A — Phase 6.5**: 12 borderline §17.4 raw-int drops from JSON
  payloads (Dashboard rep/ft, Fighter Brief marketability, Calendar
  perf, Training Camps, Scouting scout_confidence, Staff Market
  skill_level, Finance rep/ft/rating, Rivalries heat, gyms.js carve-out
  comments verified, B2 batching verified).
- **Group B**: 4 stale JS comment updates (rivalries.js, gyms.js,
  scouting.js, staff_market.js) reflecting post-Phase-6 behavior.
- **Group C**: Fixed `test_pre_b1_fixes.py` Cases F+G (82/82 PASS, was
  69/75). Root causes: (1) build_db.py seeds clock to 2026-01-01 not
  the test's expected 2026-07-20; (2) Phase 6 `populate_style_echo`
  feature inserts an additional `fighter_memory_links` row with
  `link_type='style_echo'` that the test counted as unexpected. Fix
  is test-side only (clock override + `link_type='successor'` filter).
- **Group D**: This documentation update.
- **Group E — 5-year soak analysis** (`docs/PHASE7_SOAK_ANALYSIS.md`):
  - All 10 promos survived 5 years (1,825 ticks, 0 tick errors, HEALTHY).
  - BUT 9/10 promos entered REBUILDING state with severely drained
    cash (P5 → $197K, P7 → $173K, both ~96-97% loss). Only P1 Alpha
    Combat ($50M start, major promo) stayed HEALTHY.
  - Cache tables (`fighter_descriptors`, `gym_descriptors`,
    `promotion_descriptors`) stay populated throughout.
  - `fighter_memory_links` grew 762 → 20,091 (+19,329 over 5y = ~3,866/y)
    — no pruning mechanism (Phase 8 candidate).
  - HoF: 0 → 56 inductees (~11/year, matches baseline).
  - Memory resurfacing: only 4 fires over 5y (lower than expected —
    Phase 8 investigation).
  - Performance: 0.554s/day avg (11% over <0.5s budget, but stable
    throughout, no super-linear growth).
  - **10y/20y soaks deferred** until Phase 8 economics fix.

---

## 4. Known limitations

> **Phase 7 update**: `test_pre_b1_fixes.py` now PASSES (82/82, was 69/75
> — fixed in Group C). 13 MEDIUM/LOW borderline §17.4 raw-int issues
> RESOLVED in Phase 7 Group A (raw ints dropped from JSON payloads).
> The 5-year soak surfaced 3 new issues (items 7-9 below — all Phase 8
> candidates).

1. **Event lifecycle bug (HIGH PRIORITY)**: the rival AI event
   scheduler creates events dated months in the future (e.g., 2027)
   and the lifecycle marks them 'completed' immediately. The soak
   test (HW6.3) surfaced this as 146 future-dated events marked
   COMPLETED after 180 sim days. This is OUT OF SCOPE for HW5/6/7
   (HW6 runs the tests; bug fixes are for a future pass) but is
   documented here as the next thing to fix.

2. **Per-tick cost growth**: the sim slows down super-linearly past
   day ~180 of a long run. The 30-day soak takes 11s (0.37s/tick);
   the 180-day soak takes 122s (0.68s/tick avg, 3.0s/tick at the
   end). The 365-day soak exceeded the 10-minute tool timeout at
   day ~180. Likely causes: DB bloat (news_items, training_camps,
   fight_beats tables grow significantly) + some O(n²) queries in
   the per-tick path.

3. **Save/Load screen**: only the legacy Tkinter `save_load.py`
  screen exists. The web shell doesn't have a native save/load
  screen — players using the web UI have to call `save_game` /
  `load_game` programmatically.

4. **Auto-save cadence**: fires every 30 sim days (monthly). The
   cadence is correct but the player has no UI to see when the next
   auto-save will fire or to manually trigger one outside the
   "Advance Day" loop.

5. **Schema version drift**: the live DB was at 3.29.0 before HW5;
   the HW5 normalize script ran `build_db.py --migrate` to bring it
   to 3.30.0 (HW4.1 importance column). The HW5.3 compatibility
   check now refuses to load saves with mismatched MAJOR versions.
   **Current state (post-Phase 7)**: schema is 3.37.0 (Phase 5
   relaxed the `player_decisions.decision_type` CHECK for watch/
   unwatch decisions). `ENGINE_VERSION` is 1.10.0 (Phase 6 forces
   cache rebuild with new gym + promotion descriptors).

6. **Future-dated news items**: the soak test showed 640–2036
   future-dated news items generated DURING the run (depending on
   duration). These are mostly post-event news dated for the
   event_date (which is in the future because of bug #1) rather
   than for the sim_date. Fixing #1 will fix this.

7. **Small promo economics not sustainable for 5+ years (Phase 8
   candidate)**: 5-year soak analysis showed 9/10 promos entered
   REBUILDING state. Small promos ($5M starting cash) lost $3-5M
   over 5 years (60-97% drain). P5 → $197K + P7 → $173K nearly
   bankrupt. Only P1 Alpha Combat (major, $50M start) stayed
   HEALTHY. The Phase 4 economics tuning (tier-scaled title fight
   bonuses, venue reassignment) was sufficient for 30-day soaks
   but not multi-year. **Phase 8 recommendation**: reduce small
   promo venue costs, increase broadcast revenue, reduce purse
   multiplier, OR increase small promo starting cash. See
   `docs/PHASE7_SOAK_ANALYSIS.md` §"Root cause hypothesis".

8. **`fighter_memory_links` table grows unbounded (Phase 8
   candidate)**: no pruning mechanism. 5-year soak showed growth
   from 762 → 20,091 rows (+19,329 over 5y = ~3,866/year). At this
   rate, a 20y soak would produce ~77K rows. Not yet a performance
   problem, but a pruning mechanism (keep only active + recently-
   retired fighters' links) is recommended before long soaks.

9. **Memory resurfacing rate lower than expected (Phase 8
   investigation)**: 5-year soak produced only 4 memory-resurfacing
   news items (lower than expected). The engine architecture is good
   (15 link types, 9 search types) but only `memory_resurfacing`
   news items fire, and the SIGNIFICANT-tier daily cap (5/day) may
   be suppressing fires. Phase 8 should investigate whether the
   cap should be relaxed for memory-tier items.

10. **10y/20y soaks deferred**: not run because the 5y soak revealed
    critical economics issues (item #7). Recommend re-running after
    Phase 8 economics fix to validate long-term sustainability.

---

## 5. Current event subscriptions

The event bus (`src/event_bus.py`) defines 22 event types. The
following modules register subscribers (mirrored in `scripts/
run_sim_forward.py` + `scripts/soak_test.py` for headless runs):

| Event                  | Published by                              | Subscribed by                                   |
|------------------------|-------------------------------------------|-------------------------------------------------|
| `TICK_ADVANCED`        | `services.clock.advance_day`              | news, social, rivalries, punditry, morale, suspensions, agent_offers, career_arc, rival_ai, show_rating, venues, save_load (auto-save), reputation, scouting, services.{hof, retirement, training, injuries, finance, rivalries, memory, contracts, scouting, matchmaking, punditry, pruning}, interpretation |
| `FIGHT_RESOLVED`       | `services.fight_engine.resolve_next_fight`| news, social, rivalries, punditry, services.{injuries, finance, rivalries, memory, hof}, career_arc |
| `FIGHT_CANCELLED`      | `services.matchmaking`                    | news, services.{finance, rivalries}             |
| `EVENT_COMPLETED`      | `services.matchmaking`                    | news, services.finance, show_rating             |
| `TITLE_CHANGED`        | `services.fight_engine`                   | news, social, services.{rivalries, memory}, career_arc, reputation |
| `FIGHTER_RETIRED`      | `services.retirement_svc`                 | news, services.hof, career_arc, reputation      |
| `FIGHTER_SIGNED`       | `services.contracts`                      | news, rivalries                                 |
| `FIGHTER_GENERATED`    | `services.retirement_svc`                 | (none currently — future hook)                  |
| `FIGHTER_STATE_CHANGED`| (various)                                 | (none currently — future hook)                  |
| `INJURY_CREATED`       | `services.injuries_svc`                   | news, services.memory                           |
| `INJURY_RECOVERED`     | `services.injuries_svc`                   | news                                            |
| `CONTRACT_EXPIRED`     | `services.contracts`                      | news, services.contracts                        |
| `SIGNING_INTENT`       | `services.contracts`                      | agent_offers                                    |
| `PROMOTION_BANKRUPT`   | `services.finance_svc`                    | news, rival_ai                                  |
| `SCOUT_REPORT_GENERATED`| `services.scouting_svc`                  | news                                            |
| `CAMP_COMPLETED`       | `services.training_svc`                   | news                                            |
| `CAMP_INJURY`          | `services.training_svc`                   | news, services.injuries                         |
| `WEIGHT_CUT_COMPLETED` | `services.matchmaking`                    | news                                            |
| `STAFF_CONTRACT_EXPIRING`| `services.contracts`                    | (none currently — future hook)                  |
| `STAFF_CONTRACT_EXPIRED`| `services.contracts`                     | news                                            |
| `STAFF_RETIRED`        | (various)                                 | (none currently — future hook)                  |
| `STAFF_DIED`           | (various)                                 | (none currently — future hook)                  |

Total: ~16 modules register subscribers on the global bus.

---

## 6. Current simulation lifecycle

The sim is tick-driven. Each "tick" = 1 in-game day.

1. **`services.clock.advance_day(conn)`** — called by `tick_processor.run_tick` (or directly by tests).
2. **Clock update** — `simulation_clock.current_date`, `current_day`, `current_week`, `current_month`, `current_year` are advanced by 1 day.
3. **Daily sim body** (`tick_processor._run_one_tick_body`) — runs:
   - Injuries recovery (`services.injuries_svc`)
   - Training camp progression (`services.training_svc`)
   - Contract expiry checks (`services.contracts`)
   - Rival AI event scheduling + matchmaking (`src/rival_ai.py` + `src/services/matchmaking.py`)
   - Event resolution (events whose `event_date <= sim_date` are resolved via `services.fight_engine.resolve_next_fight`)
   - Fighter retirement + regen (`services.retirement_svc`)
   - Weight cuts (`services.matchmaking`)
   - Scouting (`services.scouting_svc`)
4. **`conn.commit()`** — the sim transaction commits.
5. **`bus.publish(TICK_ADVANCED)`** — fires all TICK_ADVANCED subscribers (the 16 modules above). HW2.1 wraps each subscriber in try/except so a failing subscriber is recorded in `simulation_tick_health` but doesn't crash the tick.
6. **`simulation_tick_health` row written** — records the tick's health (HEALTHY/DEGRADED/BROKEN), subscriber counts, side-effect counts, error JSON.
7. **Daily interpretation pass** (POST-COMMIT) — `interpretation.snapshot_cache` rebuilds `fighter_descriptors`, `gym_descriptors`, `promotion_descriptors`, `daily_headlines` cache tables. This is a POST-COMMIT step (CONVENTIONS §17.5) — it sees all committed writes.

The tick is **idempotent within a day** — calling `run_tick(conn, "day", 1)` twice on the same day advances the clock by 2 days. The player triggers ticks via the "Advance Day" button in the web UI (or `tick_processor.main()` from CLI).

---

## 7. Current save architecture

- **Storage**: the DB IS the save state. No serialization — `shutil.copy2` byte-for-byte copy of `data/cage_empire.db` to `data/saves/{name}.db`.
- **WAL checkpoint** (HW5.2): `PRAGMA wal_checkpoint(TRUNCATE)` is run BEFORE the copy. TRUNCATE is a superset of the spec's FULL — checkpoints everything AND zeroes the -wal file.
- **Metadata sidecar** (HW5.2): every save writes TWO JSON files:
  - `{name}.json` — legacy compat (basic fields: save_name, timestamp, sim_date, promotion_name, current_cash, fighter_count, event_count, schema_version).
  - `{name}.meta.json` — canonical HW5.2 world-integrity metadata (all of the legacy fields PLUS simulation_date, active_fighter_count, fight_count, title_count, champion_count, rivalry_count, finance_transaction_count, memory_count, last_tick_date, world_health_status).
- **Auto-save**: registered on `TICK_ADVANCED`. Fires every 30 sim days. Filename: `autosave_{sim_date}_{wallclock}.db`. Rotating — keeps only the last 3 auto-saves (by mtime). Silent (no news item, no print).
- **Compatibility check** (HW5.3): `load_game` runs 4 checks BEFORE replacing the active DB:
  1. `schema_meta` table exists + has `schema_version`.
  2. Schema version compatible (MAJOR matches code AND save version ≤ code version).
  3. `PRAGMA integrity_check` returns 'ok'.
  4. `simulation_clock` exists + has a valid `current_date`.
  
  If any check fails, raises `SaveIncompatibleError` WITHOUT modifying the active DB.
- **Schema version**: 3.37.0 (recorded in `schema_meta`). The code's `build_db.CODE_SCHEMA_VERSION` is also 3.37.0. Older saves (3.x) are loadable; saves from a NEWER version are refused. Phase 5 (schema 3.37.0) relaxed the `player_decisions.decision_type` CHECK constraint to allow `watch` / `unwatch` decision types for the Watchlist feature.

### Save file layout

```
data/saves/
├── my_save.db              # byte-for-byte copy of cage_empire.db
├── my_save.json            # legacy metadata (compat with list_saves)
├── my_save.meta.json       # HW5.2 world-integrity metadata
├── autosave_2026-09-26_20260813_221307.db
├── autosave_2026-09-26_20260813_221307.json
├── autosave_2026-09-26_20260813_221307.meta.json
└── ... (rotating — last 3 kept)
```

---

## 8. Current schema version

- **Code**: `build_db.CODE_SCHEMA_VERSION = "3.37.0"`
- **Live DB**: `schema_meta.schema_version = "3.37.0"` (Phase 5 migration `v3_37_0_relax_player_decisions_watchlist_check` from 3.36.0).
- **ENGINE_VERSION**: `1.10.0` (Phase 6 bump from 1.9.0 — forces cache rebuild with new `gym_descriptors` + `promotion_descriptors` rows).
- **Migrations applied**: 36 (v2.2.0 → v3.37.0), recorded in `schema_migrations` table.
- **Latest migrations**:
  - `v3_30_0_add_news_items_importance` (HW4.1 — 5-tier CHECK + topic backfill).
  - `v3_36_0_*` (Tier 1-4 — pruning thresholds, fight_beats daily prune, morale weekly refresh).
  - `v3_37_0_relax_player_decisions_watchlist_check` (Phase 5 — relaxed CHECK constraint for `watch` / `unwatch` decision types).

### Schema surface (top tables by row count)

| Table                    | Rows (post-Phase 7) | Notes |
|--------------------------|---------|-------|
| `fight_beats`            | 53,669 (HW5 baseline; daily-pruned) | Per-fight beat-by-beat log |
| `commentary_segments`    | 32,889  | Per-fight commentary |
| `fighter_memory_links`   | ~762 (pre-soak) → grows ~3,866/yr | HW3 memory expansion; Phase 6 `populate_style_echo` adds style_echo rows on every retirement; **no pruning mechanism (Phase 8 candidate)** |
| `fighters`               | 4,518   | Active + retired |
| `fight_history`          | 3,608   | Per-fighter outcome log |
| `fights`                 | 3,213   | All resolved + scheduled |
| `news_items`             | 2,407 (pruned) | With importance tier (HW4.1); 180+ day pruning |
| `events`                 | 1,714   | Scheduled + completed |
| `finance_transactions`   | ~1,227 (pruned) | HW1.1 wired finance; 730+ day pruning |
| `rivalries`              | 390     | Pairwise fighter rivalries |
| `fighter_descriptors`    | 4,459   | Phase 6 cache (active fighters); churn from retirements + regen |
| `gym_descriptors`        | **329** | **Phase 6 NEW** — populated by `gym_identity_engine.py` (was 0) |
| `promotion_descriptors`  | **10**  | **Phase 6 NEW** — populated by `promotion_engine.py` (was 0) |
| `simulation_tick_health` | grows 1/tick | HW2.1 — per-tick health log |

(63 tables total — see `data/cage_empire.db` for the full schema.)

---

## 9. Hardening phase status (HW1–HW10 + Tier 1-4)

| Phase | Status | Notes |
|-------|--------|-------|
| HW1: Causal chain | ✅ DONE | Finance wired, fight_participants backfilled, financial state machine built. |
| HW2: EventBus + observability | ✅ DONE | simulation_tick_health table, Time Law audit, GAME_START_DATE constant, World Health Status, invariant_checker (8/8 PASS). |
| HW3: Memory + echoes expansion | ✅ DONE | 15 memory link types, 9 search types, historical backfill, echoes quality audit. |
| HW4: News noise + narrative quality | ✅ DONE | importance column (5 tiers), daily caps, GPT-question suppression, importance-aware trigger. |
| HW5: Data integrity + save | ✅ DONE | Backfilled fight_participants, WAL checkpoint + .meta.json sidecar, 4-step compatibility check, social date clamp. |
| HW6: Long-run soak tests | ✅ DONE | 30-day PASS, 365-day COMPLETE (1.6min), 5-year COMPLETE (7.5min). |
| HW7: Documentation | ✅ DONE | This document + obsolete-doc headers. |
| HW8: Event-lifecycle fix + perf | ✅ DONE | event_date<=sim_date filter, perf indexes, news cap trigger. |
| HW9: Career arc optimization | ✅ DONE | Bulk-load + batch UPDATE + tier-crossing + strptime elimination. |
| HW10: Rival AI memory + tests | ✅ DONE | rival_ai_memory table, decision chains, narrative quality, historical continuity, player agency. |
| Tier 1: 365-day completion | ✅ DONE | Pruning thresholds + fight_beats daily prune + conditional weekly rebuild. |
| Tier 2: 5-year foundation | ✅ DONE | Marketability consolidated + 3 new indexes + orphan cleanup. |
| Tier 3: Missing W-items | ✅ DONE | W12 measured, W29 reconciliation script, W42 provenance, 8 new memory types. |
| Tier 4: 5-year completion | ✅ DONE | Morale weekly refresh optimized + 7 tables pruned + AI fight simplification. |

### Acceptance gates (W48)

| Gate | Criteria | Status |
|------|----------|--------|
| Gate 1 (1 event) | Complete event end-to-end | ✅ PASS |
| Gate 2 (30 days) | World coherent for 30 days | ✅ PASS (6.2s, 0.21s/day) |
| Gate 3 (1 year) | Meaningful autonomous evolution | ✅ COMPLETE (94.9s, 1.6min) |
| Gate 4 (5 years) | Careers, promotions, economics, history coherent | ✅ COMPLETE (7.5min, 0.22s/day stable) |
| Gate 5 (10 years) | World alive + historically reconstructible | ⏸ Stable per-tick, needs ~36min timeout |

---

## 10. Where to look next

### Canonical planning + audit docs

- **`docs/Hardening_Phase.md`** — the canonical hardening plan (HW1–HW10).
- **`docs/GPT_PLAN_AUDIT.md`** — W1-W48 compliance audit + Gate 1-5 status.
- **`docs/PHASE5_SCREEN_AUDIT.md`** — Phase 5 audit (34 violations: 7 HIGH, 18 MEDIUM, 9 LOW). 12 of 18 MEDIUM + 9 LOW resolved in Phase 7 Group A.
- **`docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md`** — attribute phrase coverage analysis (94.4% → 100% after Task 2.5 fix).
- **`docs/PHASE6_PLAN.md`** — Phase 6 plan (audit remediation + descriptor engines).
- **`docs/PHASE7_PLAN.md`** — Phase 7 plan (cleanup + long-run soaks).
- **`docs/PHASE7_SOAK_ANALYSIS.md`** — 5y soak results (9/10 promos REBUILDING, economics Phase 8 candidate).
- **`docs/DECISION_CHAINS.md`** — 10 formal decision→consequence chains.
- **`docs/fight_distribution_report.md`** — W12 fight calibration data.
- **`docs/OPTIMIZATION_PLAN_TIER1_3.md`** — perf optimization plan.

### Canonical scripts

- **`scripts/invariant_checker.py`** — 8 world-DB invariants (run after any DB change).
- **`scripts/soak_test.py`** — long-run soak test (30d/365d/5yr).
- **`scripts/measure_fight_distribution.py`** — fight result distribution.
- **`scripts/economic_reconciliation.py`** — finance audit.
- **`scripts/test_pre_b1_fixes.py`** — champion retirement + regen + memory-link tests (82/82 PASS post-Phase 7 Group C).
- **`scripts/test_gym_identity_engine.py`** — Phase 6 cache engine tests.
- **`scripts/test_promotion_engine.py`** — Phase 6 cache engine tests.

### Canonical source files

- **`src/save_load.py`** — save/load + .meta.json + compatibility check.
- **`src/build_db.py`** — schema + migrations (CODE_SCHEMA_VERSION = "3.37.0").
- **`src/interpretation/gym_identity_engine.py`** — Phase 6 NEW — populates `gym_descriptors`.
- **`src/interpretation/promotion_engine.py`** — Phase 6 NEW — populates `promotion_descriptors`.
- **`src/interpretation/snapshot_cache.py`** — orchestrates the daily interpretation pass; `ENGINE_VERSION = 1.10.0`.
- **`src/app_web.py`** — 76 public API methods including the Watchlist API (3 methods added in Phase 5).

### Next steps (Phase 8 candidates)

1. **Small promo economics tuning (HIGH PRIORITY)** — 5-year soak showed 9/10 promos in REBUILDING state. Reduce small promo venue costs, increase broadcast revenue, reduce purse multiplier, OR increase starting cash. See `docs/PHASE7_SOAK_ANALYSIS.md` §"Root cause hypothesis".
2. **`fighter_memory_links` pruning mechanism** — table grows unbounded (~3,866 rows/year). Add pruning (keep only active + recently-retired fighters' links).
3. **Memory resurfacing rate investigation** — only 4 fires over 5y. Check SIGNIFICANT-tier daily cap + memory_link availability.
4. **Re-run 10y + 20y soaks** after Phase 8 economics fix — validate long-term sustainability.
5. **Event lifecycle bug (limitation #1)** — future-dated events marked 'completed' immediately. Out of scope for HW5/6/7; first thing to fix in Phase 8.
6. **Fight engine calibration** (W12) — doctor stoppage rate is 17% (target 1%). User will rebalance fighter attributes separately.
7. **Economic reconciliation** (W29) — 9/10 promotions have cash discrepancies. Fix: route all cash changes through finance_transactions.
8. **Build a web-native save/load screen** to replace the legacy Tkinter one.
9. **Gym ecosystem** — 300 gyms exist; `gym_identity_engine` now populates descriptors, but historical narratives still need development.
