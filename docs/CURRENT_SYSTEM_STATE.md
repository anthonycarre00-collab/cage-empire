# CAGE EMPIRE — Current System State

> **Single source of truth** for what exists, what works, and what's
> known to be broken in CAGE EMPIRE as of the Hardening Phase (HW1–HW10 + Tier 1-4).
>
> **Status:** Canonical — supersedes all earlier planning docs.
> **Last updated:** 2026-08-15 (HW1-HW10 + Tier 1-4 perf optimizations).
> **Schema version:** 3.36.0 (recorded in `schema_meta`).
> **Sim clock:** 2026-08-27 (day 239 of 2026).
> **See also:** `docs/Hardening_Phase.md` (the canonical hardening plan),
> `docs/GPT_PLAN_AUDIT.md` (W1-W48 compliance audit).

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
  memory resurfacing (HW3).
- **News**: 5-tier importance system (LEGENDARY/MAJOR/SIGNIFICANT/
  ROUTINE/BACKGROUND) with daily caps (HW4.1–4.3).
- **Echoes**: signing_echo, cut_echo, booking_echo, scouting_echo
  (sparse, decision-linked).
- **Save/load**: file-copy + WAL checkpoint + .meta.json sidecar
  (HW5.2) + 4-step compatibility check (HW5.3).
- **Tick health**: every tick recorded in `simulation_tick_health`
  with subscriber success/failure counts, side-effect counts, error
  JSON (HW2.1).

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

## 4. Known limitations

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

6. **Future-dated news items**: the soak test showed 640–2036
   future-dated news items generated DURING the run (depending on
   duration). These are mostly post-event news dated for the
   event_date (which is in the future because of bug #1) rather
   than for the sim_date. Fixing #1 will fix this.

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
- **Schema version**: 3.30.0 (recorded in `schema_meta`). The code's `build_db.CODE_SCHEMA_VERSION` is also 3.30.0. Older saves (3.x) are loadable; saves from a NEWER version are refused.

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

- **Code**: `build_db.CODE_SCHEMA_VERSION = "3.30.0"`
- **Live DB**: `schema_meta.schema_version = "3.30.0"` (after HW5 normalize ran `build_db.py --migrate` from 3.29.0 → 3.30.0).
- **Migrations applied**: 33 (v2.2.0 → v3.30.0), recorded in `schema_migrations` table.
- **Latest migration**: `v3_30_0_add_news_items_importance` (HW4.1 — added `news_items.importance` column with 5-tier CHECK constraint + backfill by topic).

### Schema surface (top tables by row count, post-HW5)

| Table                    | Rows    | Notes |
|--------------------------|---------|-------|
| `fight_beats`            | 53,669  | Per-fight beat-by-beat log |
| `commentary_segments`    | 32,889  | Per-fight commentary |
| `fight_participants`     | 6,426   | HW1.2 + HW5.1 backfilled (every fight has 2) |
| `fighters`               | 4,518   | Active + retired |
| `fight_history`          | 3,608   | Per-fighter outcome log |
| `fights`                 | 3,213   | All resolved + scheduled |
| `news_items`             | 2,407   | With importance tier (HW4.1) |
| `fighter_memory_links`   | 2,091   | HW3 memory expansion |
| `events`                 | 1,714   | Scheduled + completed |
| `finance_transactions`   | 25→1227 | HW1.1 wired finance; grows ~30/mo |
| `rivalries`              | 390     | Pairwise fighter rivalries |
| `simulation_tick_health` | 0       | HW2.1 — grows by 1 per tick |

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

- **`docs/Hardening_Phase.md`** — the canonical hardening plan (HW1–HW10).
- **`docs/GPT_PLAN_AUDIT.md`** — W1-W48 compliance audit + Gate 1-5 status.
- **`docs/DECISION_CHAINS.md`** — 10 formal decision→consequence chains.
- **`docs/fight_distribution_report.md`** — W12 fight calibration data.
- **`docs/OPTIMIZATION_PLAN_TIER1_3.md`** — perf optimization plan.
- **`scripts/invariant_checker.py`** — 8 world-DB invariants (run after any DB change).
- **`scripts/soak_test.py`** — long-run soak test (30d/365d/5yr).
- **`scripts/measure_fight_distribution.py`** — fight result distribution.
- **`scripts/economic_reconciliation.py`** — finance audit.
- **`src/save_load.py`** — save/load + .meta.json + compatibility check.
- **`src/build_db.py`** — schema + migrations (CODE_SCHEMA_VERSION = "3.36.0").

### Next steps

1. **Fight engine calibration** (W12) — doctor stoppage rate is 17% (target 1%). User will rebalance fighter attributes separately.
2. **Economic reconciliation** (W29) — 9/10 promotions have cash discrepancies. Fix: route all cash changes through finance_transactions.
3. **10-year soak** (Gate 5) — per-tick cost is stable, just needs ~36min timeout.
4. **Build a web-native save/load screen** to replace the legacy Tkinter one.
5. **Gym ecosystem** — 300 gyms exist but gym identity isn't historically meaningful yet.
