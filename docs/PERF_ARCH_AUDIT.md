> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Tick Processor + Screen Refresh Architecture Audit

**Task ID:** PERF-ARCH-AUDIT
**Date:** 2026-08-02
**Scope:** `src/tick_processor.py`, `src/ui/state.py`, `src/ui/app.py`, `src/ui/perf.py`, and the four primary screens (`dashboard.py`, `roster.py`, `fighter_profile.py`, `free_agents.py`).
**Mode:** Research + analysis only. No code changes.

---

## 0. Executive Summary

The CAGE EMPIRE UI does too much work on every Advance Day click and on every navigation. The current "refresh everything that's visible, mark the rest stale" heuristic is good as a baseline, but:

1. The **Dashboard** does **30 separate SQL queries** and fully destroys + rebuilds ~80 widgets every refresh — even when nothing visible changed.
2. The **Roster** and **Free Agents** screens do **full table rebuilds of every row** even when one fighter signed or one record ticked over.
3. The **tick pipeline** itself is dominated by the **post-commit interpretation pass** (`run_daily_interpretation_pass`) which recomputes all 4 sub-engines for all 4 450 active fighters on every single tick — **~333 ms / tick (73 % of total tick time)** — even when only a handful of fighters actually changed.
4. Many tick subscribers (`morale.process_tick`, `rivalries.check_social_beefs`, `social.check_social_activity`) poll the entire active roster every tick, even though most of their logic is gated to fire weekly.

The **single biggest waste**: every Advance Day click recomputes every fighter's momentum / pressure / career_phase / narrative_family / legacy_state from scratch, even though most of those attributes only meaningfully change when a fighter fights, signs, retires, or recovers from an injury. That's ~333 ms of wasted CPU per click + ~40 ms of downstream refresh work that wouldn't be needed if only the affected fighters were re-interpreted.

**Measured performance:**

| Metric | Measured |
|---|---|
| `tick_processor.run_tick` total (median, daily tick) | **455 ms** |
| `tick_processor.run_tick` total (monthly tick, lots of camps complete) | **1 880 ms** |
| `run_daily_interpretation_pass` (the 4 sub-engines, all 4 450 fighters) | **333 ms** |
| `bus.publish(TICK_ADVANCED)` across all 19 subscribers | **57 ms** |
| `_check_retirements` (one SELECT over all 4 464 active fighters) | **26 ms** |
| `_check_training_camps` (processes ~38-122 camps per tick) | **2 ms typical, ~50 ms monthly** |
| `DashboardScreen._refresh` (30 queries + ~80 widget rebuilds) | **380 ms** |
| `RosterScreen._refresh` (4 queries + ~120 row widget rebuilds) | **485 ms** |
| `FreeAgentsScreen._refresh` (4 queries + ~120 row widget rebuilds) | **475 ms** |
| `FighterProfileScreen._refresh` (7 queries + ~40 widget rebuilds) | **110 ms** |
| `refresh_all` lazy (active=Dashboard) | **400 ms** |
| `refresh_all` lazy (active=Roster) — refreshes Dashboard + Roster | **945 ms** |
| `refresh_all` force=True (theme toggle / Load) — all 5 screens | **1 570 ms** |

**Total experienced Advance Day latency** (active=Dashboard, the most common case): **~455 ms tick + ~400 ms Dashboard refresh + ~10 ms top/bottom bar update ≈ 865 ms** before the user sees a responsive UI again. With the active screen on Roster that jumps to **~1.4 s**.

---

## 1. Tick Processor Audit

### 1.1 Pipeline shape

`run_tick(conn, tick_type, steps)` (defined at `src/tick_processor.py:1558`) runs the following sequence per step:

1. **Clock advance** — `UPDATE simulation_clock` (1 SQL, ~0 ms).
2. **`_check_retirements(conn, dt)`** — birthday-gated retirement check.
3. **`_check_contract_expiry(conn, dt)`** — expire contracts past `end_date`.
4. **`_check_injury_recovery(conn, dt)`** — mark recovered injuries.
5. **`_check_training_camps(conn, dt)`** — progress / complete all active camps.
6. **`_check_scouting_assignments(conn, dt)`** — resolve ready scout assignments.
7. **`bus.publish(TICK_ADVANCED)`** — dispatches to **19 registered subscribers**.
8. **`conn.commit()`** — single transaction covering everything above.
9. **`run_daily_interpretation_pass(conn)`** — POST-COMMIT step (per CONVENTIONS §17.5). NOT a TICK_ADVANCED subscriber. Recomputes all 4 interpretation sub-engines + writes daily headlines. Commits its own transaction.

### 1.2 Direct (inline) helpers — measured per-tick cost

| Helper | What it does | DB writes | Measured cost | Could it run less often? |
|---|---|---|---|---|
| `_check_retirements` | Loads ALL active fighters (one SELECT), filters to today's birthdays in Python (~1/365 of roster). On hit: `fighters` UPDATE + `titles` UPDATE + 2× `news_items` INSERT + `regen_lineage` INSERT + `generate_fighter()` (slow). | `fighters`, `titles`, `news_items`, `regen_lineage` | **26 ms** (mostly the SELECT over 4 464 rows) | **Yes.** Birthday check is fine per-tick, but the bulk SELECT can be pre-filtered to "fighters whose DOB month/day matches today" via a `WHERE strftime('%m-%d', date_of_birth) = strftime('%m-%d', ?)` clause — drops 4 464 rows → ~12 rows. Saves ~25 ms / tick. |
| `_check_contract_expiry` | One SELECT on `contracts` filtered by `status='active' AND end_date < current_date`. Indexed; empty result on most ticks. | `contracts`, `fighters`, `news_items` (only when something expires) | **0.2 ms** | No. Needs to fire every tick — cheap enough. |
| `_check_injury_recovery` | One SELECT on `injuries` filtered by `is_active=1 AND projected_return_date <= current_date`. | `injuries`, `fighter_career`, `news_items` (only on recovery) | **0.1 ms** | No. Cheap + correct. |
| `_check_training_camps` | One SELECT on `training_camps` filtered by window containing today. For each camp (typically 38-144 active): 1 stats-row SELECT + 1 gym-row SELECT + 1 camp UPDATE. Per-completion adds: ~25 attribute UPDATEs + news INSERT + descriptor snapshot refresh. | `training_camps`, `fighter_attributes`, `fighter_career`, `injuries`, `news_items`, `fighter_descriptors` | **2 ms typical, ~50 ms on monthly tick when 38 camps complete** | Could split progression from completion. Progression (`+2-5 fatigue`) is a small per-camp UPDATE — fine every tick. Completion (which applies attribute gains + descriptor snapshot refresh) only fires when `current_date == end_date` — already gated. No change needed. |
| `_check_scouting_assignments` | One SELECT on `scouting_assignments`. Cheap; 0 rows in the seeded DB. | `scouting_reports` (only when assignments complete) | **0.2 ms** | No. |
| `run_daily_interpretation_pass` | POST-COMMIT. Calls `compute_all_fighters` (Context Engine) + `compute_all_career_phases` + `compute_all_families` + `compute_all_legacies` + `generate_daily_headlines`. Each iterates over all 4 450 active fighters. | `fighter_descriptors`, `gym_descriptors`, `division_descriptors`, `daily_headlines`, `interpretation_cache_meta` | **333 ms** | **YES — biggest win.** See §4. Only fighters whose underlying state changed (fought, signed, retired, recovered from injury, changed camps) need re-interpretation. The 4 event-bus subscribers in `interpretation/__init__.py` already call `refresh_fighter(fighter_id)` per-event for `FIGHT_RESOLVED` / `FIGHTER_RETIRED` / `TITLE_CHANGED` / `CONTRACT_EXPIRED`. The full daily pass could be downgraded to a **weekly re-baseline** (catch up anything the event-driven path missed) instead of an every-tick full rebuild. |

### 1.3 TICK_ADVANCED subscribers (19 registered)

The bus dispatches these synchronously inside `bus.publish()` (line 1 664 of `tick_processor.py`). All see the same `event = {type, current_date, tick_type}` dict. **None** receive `current_day` (a known papercut — see `save_load.auto_save` comment at line 614).

Per-subscriber median timing, ranked by cost (measured across 3 ticks, see §0 for methodology):

| # | Subscriber | What it does | Cost (median ms) | Frequency gate | DB writes | Could it run less often? |
|---|---|---|---|---|---|---|
| 1 | `morale.process_tick` | WEEKLY: drift all fighters' morale toward 50 (loops over 4 450 fighters, per-fighter `_days_since_last_fight` sub-query), applies ring rust, win-streak bonus, injury recovery +5; calls `_weekly_snapshot_refresh` which calls `_refresh_snapshot` for every active fighter. DAILY: birthday aging. | **22 ms** | Weekly gate via `_is_weekly_tick` for the heavy loop; birthday check runs daily. | `fighter_personality`, `fighter_descriptors` | **Yes** — the weekly drift loop's per-fighter `_days_since_last_fight` sub-query is N+1 (4 450 sub-queries). One JOIN would drop it to a single SELECT. The `_weekly_snapshot_refresh` then calls `_refresh_snapshot` 4 450 times — should be batched. |
| 2 | `rivalries.check_social_beefs` | Loops over ALL active rivalries (~169 rows), per-rivalry runs 2 COUNT queries on `social_posts`. Then a second pass scans ALL callout/trash_talk posts for new candidate pairs. | **22 ms** | No gate — runs every tick | `rivalries` (UPDATE heat, INSERT new) | **Yes** — should be WEEKLY (rivalry heat changes slowly). Or at minimum, gate the "discover new rivalries" full-scan pass to weekly and only escalate existing rivalries daily. |
| 3 | `rival_ai.process_rival_promotions` | DAILY: for each rival promo (~9), check for events due for resolution + resolve the full card (this calls `resolve_next_fight` which is expensive). WEEKLY: schedule next event + 10 % signing roll. | **5 ms** (daily phase only; can spike to 200+ ms when a rival card resolves) | Daily for resolve, weekly for schedule/sign | `events`, `fights`, `fight_history`, `fighters`, `news_items`, `titles`, `rankings`, `contracts` | **No** — daily resolution is correct (an event's fights must resolve on its scheduled date). The spike when a card resolves is unavoidable but bounded. |
| 4 | `news.generate_suspension_news` | Polls `suspensions` for active + cleared rows without news items. Per-row, runs `_has_suspension_news` LIKE check. | **3.7 ms** | No gate | `news_items` | **Yes** — should be WEEKLY (only 8 suspensions in the seeded DB; polling every day is wasteful). Or migrate to event-driven: `suspensions` already has FIGHT_RESOLVED subscribers that create the row, those subscribers could publish a `SUSPENSION_CREATED` event and the news engine could write the item immediately. |
| 5 | `social.check_social_activity` | Samples up to `_MAX_TICK_POSTS` fighters weighted by `attention_seeking`. Pre-loads `MAX(post_date)` per fighter in one query, then iterates. | **1.9 ms** | No gate | `social_posts` | No — daily post volume is the point. The cooldown filter (7-day) keeps the per-fighter frequency sane. |
| 6 | `reputation.process_tick` | Polls `suspensions` for `drug_test_failure` rows without a dedup marker. | **1 ms** | No gate | `news_items` (dedup marker), `promotions` (rep -3) | **Yes** — same as #4, this is a polling scan for an event that already has a row in `suspensions`. Should be event-driven. (Note: this subscriber raised `NOT NULL constraint failed: news_items.published_at` during my test runs — there's an existing bug where the dedup marker INSERT omits `published_at`. Worth fixing.) |
| 7 | `news.generate_retirement_news` | Polls `news_items` for `topic='retirement'` rows published today; for each, writes a richer voice-driven news item. | **0.03 ms** | No gate | `news_items` | No-op most ticks (no retirements). Cheap. |
| 8 | `morale.process_monthly_gym_spec_drift` | Monthly gym spec evolution. | **0.02 ms** | Monthly gate (`current_day % 28 == 0`) | `gyms` | Already gated. Fine. |
| 9 | `suspensions.check_suspension_recovery` | Clears suspensions whose `end_date` passed. | **0.02 ms** | No gate | `suspensions` | No — daily is correct (suspensions end on specific dates). |
| 10 | `agent_offers.check_expired_offers` | DELETE agent offers past their `expires_date`. | **0.02 ms** | No gate | `agent_offers` | No — daily is correct. |
| 11 | `news.prune_old_news` | DELETE news older than 365 days (except title/retirement/HoF). | **0.01 ms** | Weekly gate | `news_items` | Already gated. Fine. |
| 12 | `agent_offers.maybe_generate_offer` | 10 % weekly roll to generate a new agent offer. | **0.01 ms** | Weekly gate | `agent_offers` | Already gated. Fine. |
| 13 | `save_load.auto_save` | Saves the game every 30 sim days + prunes old autosaves. | **0.01 ms** daily; **~50-100 ms** when save fires | Monthly gate (`current_day % 30 == 0`) | Disk write (new save file) | Already gated. Fine. |
| 14 | `rivalries.decay_rivalry_heat` | WEEKLY: decay all rivalry heat by -5. | **0 ms** daily; ~0.3 ms weekly | Weekly gate | `rivalries` | Already gated. Fine. |
| 15 | `pruning_svc.on_tick_advanced` | Monthly prune of news_items, daily_headlines, social_posts, injuries, suspensions, training_camps, scouting_reports. | **0 ms** daily; ~25 ms monthly | Monthly gate (1st of month) | Multiple tables (DELETE) | Already gated. Fine. |
| 16 | `career_arc.process_career_arc` | Monthly: natural growth + decline per fighter. | **0 ms** daily; ~50-150 ms monthly | Monthly gate (`current_day % 28 == 0`) | `fighter_attributes`, `fighter_career`, `fighter_descriptors` | Already gated. Fine. |
| 17 | `news.generate_event_hype_news` | WEEKLY: write 0-2 hype news items per scheduled event in the next 7 days. | **0 ms** daily; ~3.5 ms weekly | Weekly gate | `news_items` | Already gated. Fine. |
| 18 | `venues.drift_market_heat` | Monthly: drift venue market heat. | **0 ms** daily | Monthly gate | `venues` | Already gated. Fine. |
| 19 | `morale.process_monthly_promotion_tier` | Monthly: recompute AI promotion size_tier. | **0 ms** daily | Monthly gate | `promotions` | Already gated. Fine. |

**Downstream refresh trigger:** None of these subscribers directly call `GameState.refresh_all()`. The refresh is triggered by the UI layer (`CageEmpireApp._on_advance_day` at `src/ui/app.py:1118`) AFTER `advance_day()` returns. The subscriber side is fire-and-forget.

### 1.4 Tick-processor findings

- **18 of 19 TICK_ADVANCED subscribers are correctly gated** (daily / weekly / monthly). The exceptions:
  - `rivalries.check_social_beefs` runs every tick but the comment claims weekly intent — should be gated.
  - `news.generate_suspension_news` polls every tick for an event that's only created on FIGHT_RESOLVED — should be event-driven.
  - `reputation.process_tick` same issue + has a latent NOT NULL constraint bug.
- The big-ticket items are NOT in the subscribers — they're in:
  1. `run_daily_interpretation_pass` (333 ms — 73 % of total tick time, called post-commit, NOT a subscriber).
  2. `_check_retirements` (26 ms — bulk SELECT over 4 464 fighters).
  3. The 3 expensive subscribers above (~30 ms combined).

---

## 2. Screen Refresh Audit

All 4 screens use the same pattern: `_refresh()` destroys every dynamic widget from the previous render (`_destroy_widgets(widget_list)` calls `w.destroy()` on each), then re-queries all needed data, then rebuilds every widget from scratch. There is **no diffing** — even unchanged data triggers a full destroy+rebuild cycle.

### 2.1 DashboardScreen (`src/ui/screens/dashboard.py:810`)

**Refresh strategy:** 9 sub-refresh methods, each in its own try/except. Each sub-method:
1. Calls `self._destroy_widgets(self._<section>_widgets)` — destroys ALL prior widgets.
2. Runs SQL queries.
3. Constructs new CTk widgets (`GradientCard`, `StatTile`, `DataChip`, `NewsCard`, `HyperlinkLabel`, `EmptyState`, `Button`, etc.).
4. Appends each new widget to `self._<section>_widgets` for the next destroy cycle.

**DB queries per refresh (measured):** **30 queries** total — distributed across the 9 sub-methods:

| Sub-method | Queries | Median ms | Notes |
|---|---|---|---|
| `_refresh_subtitle` | 2 | 0.1 | Clock + promo name. |
| `_refresh_welcome` | 4 | 4.4 | Clock + 3 stat rows (next event, recent results count, top streak). |
| `_refresh_top_story` | 1-2 | **18.7** | `daily_headlines` query (sub-ms) + optional fighter WC query. Most cost is `GradientCard` + chips + `HyperlinkLabel` widget construction. |
| `_refresh_promotion_status` | 5 | **58.8** | Promo row + roster COUNT + champion COUNT + 7-day cash history (correlated subquery) + yesterday's cash + WC COUNT. Builds 5 `StatTile`s + 2 `DataChip`s + Sparkline. |
| `_refresh_next_event` | 1-3 | 9.1 | Next scheduled event (or last completed fallback) + main-event fighter JOIN. Builds a `Card` with date/name/matchup/chips/buttons. |
| `_refresh_champions` | 2 | **72.8** | Champions JOIN + sim_date. Builds up to 8 champion chips, each with WC label + name HyperlinkLabel + reign DataChip + defense count DataChip + reign-number DataChip. **Most expensive section per widget built.** |
| `_refresh_fighter_watch` | ~10 | **125.0** ⚠️ | `daily_headlines` query + `_find_hottest_streak_fighter` (queries `fighter_descriptors` with `SUBSTR(...)` filter — 4.9 ms!) + 3× `_lookup_fighter_watch_data` (fighter JOIN) + 3× `_query_last_5_fights` (5-row history) + sim_date. Builds **3 GradientCards**, each with eyebrow + PortraitFrame + name HyperlinkLabel + MomentumRing + voice phrase + FormMeter + chips. |
| `_refresh_recent_results` | 2 | 36.3 | Last 5 completed events JOIN show_ratings + batch main-event matchups (single IN(...) query — was 5 correlated subqueries, fixed in UI-PHASE-3). Builds 5 cards. |
| `_refresh_news` | 1 | **59.6** | 5 news rows. Builds 5 `NewsCard`s with chips + body + footer. |
| **Total** | **30** | **380 ms** | |

**Top 3 most expensive sections:**
1. `_refresh_fighter_watch` — **125 ms** (33 % of refresh). Three `GradientCard`s with portrait frames + momentum rings + form meters. The `SUBSTR(...)` filter on `fighter_descriptors.momentum` is a full table scan (4.9 ms) repeated for "very_high" and "high" labels.
2. `_refresh_champions` — **73 ms** (19 %). 8 champion rows × ~5 widgets each = ~40 widgets.
3. `_refresh_promotion_status` — **59 ms** (16 %). 5 StatTiles, each is a multi-widget composite (label + value + trend arrow + sparkline canvas).

**Could it be smarter?** **Yes — significantly.** Of these 9 sections:
- `_refresh_subtitle` (clock + promo name): changes only on Advance Day or Save/Load. Never changes on intra-screen navigation.
- `_refresh_top_story`: changes only on Advance Day (the daily headlines are recomputed by the interpretation pass). Never changes on intra-screen navigation.
- `_refresh_champions`: changes only on `TITLE_CHANGED` event (new champion crowned / title vacated). Rare.
- `_refresh_fighter_watch`: changes only on Advance Day (the headlines + descriptors are recomputed).
- `_refresh_news`: changes on Advance Day + on any event that writes news (FIGHT_RESOLVED, FIGHTER_RETIRED, FIGHTER_SIGNED, etc.).
- `_refresh_promotion_status`: cash changes on every finance transaction; roster count changes on FIGHTER_SIGNED / contract expiry; champions count changes on TITLE_CHANGED.
- `_refresh_next_event`: changes when an event is scheduled, completed, or when the date rolls over.
- `_refresh_recent_results`: changes only when an event is completed.
- `_refresh_welcome`: aggregates data from multiple sources; effectively changes on Advance Day.

On a pure **intra-screen navigation** (player is on Roster, clicks back to Dashboard) — **at most 2 sections need refresh** (`_refresh_next_event` if event state could have changed, `_refresh_news` if a fight just resolved). The other 7 sections have data identical to the last Dashboard render. Currently all 9 sections rebuild unconditionally — that's ~340 ms of unnecessary widget work per navigation.

### 2.2 RosterScreen (`src/ui/screens/roster.py:1343`)

**Refresh strategy:**
1. Read sim date (1 query).
2. `_refresh_weight_class_dropdown` — 1 query for distinct WC rows in player's roster (filtered by gender if active).
3. `_query_roster` — 1 large JOIN query (fighters + WC + nation + gym + descriptors + career).
4. `_refresh_subtitle` — 1 query (promo name) + `_refresh_promo_logo` (loads PNG via PIL).
5. `_render_table_new` — calls `FighterTable.set_rows(rows)` which destroys + rebuilds all visible row widgets.
6. `_refresh_pagination` — no queries, just label configures.

**DB queries per refresh:** **4**

**Refresh cost:** **485 ms** median.

**Where the time goes:** The roster query itself is **0.2 ms** (indexed, see `EXPLAIN` in `profile_screens.py`). The 485 ms is **entirely widget work** in `FighterTable.set_rows`:
- Destroys all previous row widgets.
- For each fighter in the current page (typically 25-50): builds a `FighterRow` widget (a `CTkFrame` containing ~8 sub-widgets: rank, name, WC chip, age, nation abbrev, form meter, record, gym).
- Plus the header row + sorting hooks.

**Could it be smarter?** Yes:
- The sim date only changes on Advance Day — could be cached at the session level.
- The WC dropdown only changes when a fighter is signed/cut — could be event-driven (`FIGHTER_SIGNED`, `CONTRACT_EXPIRED`, `FIGHTER_RETIRED`).
- The roster data only changes on Advance Day, FIGHTER_SIGNED, FIGHTER_RETIRED, or contract expiry. On pure navigation, the data is identical to the last render.
- `FighterTable.set_rows` could diff old vs new and only update the rows whose data changed (e.g., a fighter whose `momentum` changed would only need its FormMeter + momentum chip updated, not the whole row destroyed + rebuilt).

### 2.3 FighterProfileScreen (`src/ui/screens/fighter_profile.py:1302`)

**Refresh strategy:** `_refresh()` calls `_destroy_dynamic_widgets()` (destroys ALL widgets across 8 sections), then runs `_query_fighter` (one big JOIN), then renders 8 sections:
1. `_refresh_header` — name, subtitle, champion badge, gym icon, portrait.
2. `_refresh_identity` — age, WC, nation, gym, promotion chips.
3. `_refresh_bio` — bio text.
4. `_refresh_career` — record + streaks + reigns + champion check (1 query for `titles`).
5. `_refresh_recent_fights` — last 5 fights (1 query).
6. `_refresh_attribute_profile` (own fighter only) — 26 attributes ranked, displayed as voice descriptors. Reads `attribute_descriptors` JSON.
7. `_refresh_personality` (own fighter only) — personality grid.
8. `_refresh_scouting` (other-promo fighter only) — scouting report (1 query on `scouting_reports`).

**DB queries per refresh:** **7** (own fighter) / **7** (other-promo fighter, swapping attribute/personality section for scouting).

**Refresh cost:** **110 ms** median (cache miss == cache hit — the portrait cache helps but the rest of the work is identical).

**Where the time goes:**
- `_refresh_attribute_profile` builds a 26-row attribute grid (each row = label + AttributeBar widget + voice phrase label) — ~80 widgets.
- `_refresh_recent_fights` builds 5 fight row cards.
- `_refresh_header` builds the portrait + name + subtitle + champion badge.

**Could it be smarter?** Yes:
- The profile only changes for a given `fighter_id` on: Advance Day, FIGHT_RESOLVED (for that fighter), CAMP_COMPLETED (for that fighter), INJURY_RECOVERED (for that fighter), TITLE_CHANGED (for that fighter), or when the player explicitly toggles "Show Full Stats". On navigation back to a profile the player just left, nothing has changed — could skip refresh entirely.
- The attribute_descriptors JSON is decoded + ranked every refresh — could be cached per fighter_id + invalidated on FIGHT_RESOLVED / CAMP_COMPLETED.
- `_refresh_attribute_profile`'s 26-row grid could update in-place (just `configure(text=...)` the labels + `set_value(...)` the bars) instead of destroy + rebuild.

### 2.4 FreeAgentsScreen (`src/ui/screens/free_agents.py:1351`)

**Refresh strategy:** Mirrors Roster exactly — sim date + WC dropdown + free-agent query + table rebuild + pagination.

**DB queries per refresh:** **4**

**Refresh cost:** **475 ms** median. Same widget-rebuild bottleneck as Roster.

**Could it be smarter?** Same recommendations as Roster:
- Free agent pool only changes on FIGHTER_SIGNED, FIGHTER_RETIRED, contract expiry, or Advance Day (career arc / aging). On pure navigation, no change.
- `_query_free_agents` is **13.7 ms** (slower than roster's 0.2 ms because the `current_promotion_id IS NULL` filter has no index — see `EXPLAIN` showing `idx_fighters_promo_active` is used but the IS NULL branch scans).

---

## 3. The "Refresh Everything" Problem

### 3.1 What `refresh_all` currently does

`GameState.refresh_all(force=False)` (`src/ui/state.py:271`) is the lazy-mode refresh called by `_on_advance_day`. Current behavior:

1. Always refresh **Dashboard** first (the "always-on" screen).
2. Refresh the **active screen** if it isn't the Dashboard.
3. Mark every other registered screen as "stale" (informational — `set_active_screen` calls `refresh(name)` on next navigation anyway).

This is **already much better** than the original "refresh every screen every Advance Day" pattern. The Phase 4 perf utility (`scripts/perf/test_perf.py:test_lazy_refresh_skips_invisible_screens`) confirms it skips invisible screens.

### 3.2 Where it still wastes work

#### A. Dashboard refresh when the player is on the Roster screen

When the player clicks Advance Day while on Roster:
- `refresh_all` refreshes Dashboard (380 ms) **even though the player can't see it**.
- Then refreshes Roster (485 ms).
- Total: **~945 ms** of UI freeze.

The Dashboard refresh is justified IF the player is likely to navigate back to it soon — the data will be fresh and the navigation will be instant. But:
- 9 of the 9 Dashboard sections rebuild unconditionally. If the player advances the day, then advances again, the second advance could safely skip 7 of the 9 sections (champions rarely change, fighter_watch data is identical until the next interpretation pass, recent_results only changes if an event completed, etc.).
- The fix is **per-section dirty flags** on the Dashboard itself (not just on screens).

#### B. Roster refresh when the player navigates to Fighter Profile

When the player double-clicks a row on the Roster → `_navigate("fighter_profile")` is called → `state.set_active_screen("fighter_profile")` triggers `FighterProfileScreen._refresh()`.

The Roster itself is NOT refreshed on this navigation (correct — `_navigate` calls `set_active_screen` which calls `refresh(name)` only for the NEW active screen). 

But when the player hits Back from Fighter Profile → `go_back()` calls `state.refresh("roster")` → Roster rebuilds all 25-50 row widgets. **Even though the roster data didn't change** (the player just looked at a fighter, didn't sign anyone).

The fix: `go_back` should only refresh if the screen's data actually changed. The screen could set its own `_dirty` flag when an action it cares about fires (e.g., Roster's `_dirty = True` on FIGHTER_SIGNED).

#### C. Fields that change rarely but get re-queried every refresh

The following queries run on EVERY Dashboard refresh even though their results change rarely:

| Query | Section | When does the result actually change? |
|---|---|---|
| `SELECT COUNT(*) FROM weight_classes WHERE is_active=1` | `_refresh_promotion_status` (Tile 5: "X of 8 belts") | Never (the WC count is fixed by the seed). |
| `SELECT name FROM promotions WHERE promotion_id=?` | `_refresh_subtitle` + `_refresh_promotion_status` + Roster `_refresh_subtitle` + Free Agents `_refresh_subtitle` | Never (promo name doesn't change). |
| `SELECT current_month, current_year FROM simulation_clock` | `_refresh_subtitle` + `_refresh_welcome` | Only on Advance Day. |
| `SELECT * FROM weight_classes WHERE ... ORDER BY display_order` | Roster + Free Agents WC dropdown | Only when a fighter is signed/cut (changes which WCs are "present" in the roster). |
| `SELECT * FROM nations` (implicit via JOIN) | Roster + Free Agents row rendering | Never (nation list is fixed by the seed). |
| `SELECT * FROM gyms` (implicit via JOIN) | Roster + Free Agents row rendering | Only when a gym is added/removed (rare). |
| Champions JOIN (`titles` ⋈ `weight_classes` ⋈ `fighters`) | `_refresh_champions` | Only on `TITLE_CHANGED`. |
| `daily_headlines` query | `_refresh_top_story` + `_refresh_fighter_watch` | Only on Advance Day (the daily interpretation pass writes them). |

**Recommendation:** Cache these at the session level (in `GameState` or a dedicated `SessionCache` class). Invalidate via specific events: `clear_wc_cache()` on fighter signed/cut, `clear_promo_cache()` on promotion name change (never), `clear_champions_cache()` on `TITLE_CHANGED`, `clear_headlines_cache()` on Advance Day.

### 3.3 The dashboard "always refresh first" choice

`state.refresh_all()` refreshes Dashboard before the active screen. This is correct for the "player is on Roster, clicks Advance Day, will probably navigate back to Dashboard soon" case. But:

- If the player is actively working on the Roster (advancing days, signing free agents), the Dashboard refresh is wasted work for every Advance Day click.
- If the player is on the Dashboard itself, this is fine — only the Dashboard refreshes.

**Recommendation:** Refresh the **active screen first** (so the user sees their current screen update immediately), then refresh Dashboard in the background (via `widget.after(0, ...)` so it doesn't block the event loop). This trades ~400 ms of freeze for instant-active-screen feedback.

---

## 4. Recommended Architecture

### 4.1 Dirty-flag system on Dashboard sections

Add a `_dirty_sections: set[str]` to `DashboardScreen`. Each section's refresh method checks if its name is in the dirty set; if not, skip. Sections get marked dirty by:

| Section | Marked dirty on |
|---|---|
| `_refresh_subtitle` | Advance Day, Save/Load, theme toggle |
| `_refresh_welcome` | Advance Day, Save/Load, theme toggle |
| `_refresh_top_story` | Advance Day (headlines recomputed), Save/Load, theme toggle |
| `_refresh_promotion_status` | Advance Day, FIGHTER_SIGNED, TITLE_CHANGED, finance events, Save/Load, theme toggle |
| `_refresh_next_event` | Advance Day, event scheduled, event completed, Save/Load, theme toggle |
| `_refresh_champions` | TITLE_CHANGED, FIGHTER_RETIRED, Save/Load, theme toggle |
| `_refresh_fighter_watch` | Advance Day, Save/Load, theme toggle |
| `_refresh_recent_results` | EVENT_COMPLETED, Save/Load, theme toggle |
| `_refresh_news` | Advance Day, FIGHT_RESOLVED, FIGHTER_RETIRED, FIGHTER_SIGNED, TITLE_CHANGED, Save/Load, theme toggle |

Implementation: `GameState` exposes a `mark_dirty(screen_name, section_name=None)` method. Screens subscribe to specific events via the event bus and call `mark_dirty` on themselves when relevant events fire. The Dashboard's `_refresh` then only runs the dirty sections.

Expected impact: On intra-screen navigation (player returns to Dashboard from Roster), **0 sections are dirty → 0 ms refresh** (vs. current 380 ms).

### 4.2 Event-driven updates for non-Dashboard screens

| Screen | Subscribe to | Action |
|---|---|---|
| Roster | `FIGHTER_SIGNED`, `FIGHTER_RETIRED`, `CONTRACT_EXPIRED`, Advance Day | Mark `_dirty = True` (skip refresh on next navigation if not dirty). |
| Free Agents | `FIGHTER_SIGNED`, `CONTRACT_EXPIRED`, `FIGHTER_RETIRED`, Advance Day | Same. |
| Fighter Profile | `FIGHT_RESOLVED` (for the displayed fighter_id), `CAMP_COMPLETED` (for the displayed fighter_id), `INJURY_RECOVERED` (for the displayed fighter_id), `TITLE_CHANGED` (for the displayed fighter_id), Advance Day | Same. If the fighter retired, navigate back automatically. |
| Scouting | `SCOUT_REPORT_GENERATED`, Advance Day | Same. |

Implementation: Each screen registers a bus subscriber in its `__init__` that sets `self._dirty = True`. The `_refresh` method short-circuits if `not self._dirty and not force`. `set_active_screen` always calls `refresh(name)` for the new active screen — if `_dirty` is False, the refresh is a no-op (just `pack` the existing widgets, which already happened in `_navigate`).

**Important caveat:** The event bus is currently per-connection (not per-session). Subscribers registered in screen `__init__` would persist across screen destruction. Screens should either:
- Register once at app startup (in `CageEmpireApp.__init__`) with a weak reference to the screen instance, or
- Use `GameState.mark_dirty(screen_name)` instead of subscribing directly — AppState owns the dirty flags, screens just check them.

The second approach is cleaner — `GameState` already has `_stale_screens` (Phase 4); we extend it to `_stale_sections` per-screen.

### 4.3 Session-level cached queries

Add a `SessionCache` class (or extend `ui/perf.py`'s `query_cache`):

```python
# ui/perf.py — extend with session-scoped caches
_SESSION_CACHE = {
    "weight_classes": None,           # never changes after seed
    "weight_classes_active_count": None,
    "nations": None,                  # never changes
    "gyms": None,                     # changes rarely
    "promotions": None,               # changes rarely
    "player_promotion": None,         # cached on first access
    "sim_clock": None,                # invalidated on Advance Day
}

def session_get(key, builder):
    if _SESSION_CACHE[key] is None:
        _SESSION_CACHE[key] = builder()
    return _SESSION_CACHE[key]

def invalidate_session(key=None):
    if key is None:
        for k in _SESSION_CACHE:
            _SESSION_CACHE[k] = None
    else:
        _SESSION_CACHE[key] = None
```

Call `invalidate_session("sim_clock")` from `_on_advance_day`. Call `invalidate_session()` (all) from Save/Load.

Expected impact: Saves 4-6 queries per Dashboard refresh + 2 queries per Roster/Free Agents refresh. Marginal time savings (~1-2 ms total) but reduces DB round-trips + simplifies the screen code (no defensive try/except around trivial lookups).

### 4.4 Diff-based widget updates (the big win for Roster/Free Agents/Fighter Profile)

`FighterTable.set_rows(rows)` currently:
1. Destroys all existing row widgets.
2. Creates new row widgets for every fighter in `rows`.

Proposed:
1. Keep a dict `{fighter_id: FighterRow}` of existing rows.
2. For each new row in `rows`:
   - If `fighter_id` in existing rows → call `row.update(new_data)` which only `configure()`s the labels whose values changed.
   - If `fighter_id` not in existing rows → create a new `FighterRow` + insert at the correct position.
3. Remove rows whose `fighter_id` is no longer in `rows`.

`FighterRow.update(new_data)` would diff `new_data` against `self._current_data` and only call `configure(text=...)` on labels whose text changed. For unchanged data → 0 widget work.

Expected impact: When the player returns to a Roster they just left (no data change), refresh drops from **485 ms → ~5 ms** (just the diffing loop, no widget work). When ONE fighter's momentum changes (Advance Day), only that row's FormMeter + momentum chip update — ~10 ms instead of 485 ms.

### 4.5 Targeted interpretation pass (the biggest tick-processor win)

The post-commit `run_daily_interpretation_pass` currently recomputes all 4 sub-engines for all 4 450 active fighters on every tick (333 ms).

Proposed:
1. The 4 event-bus subscribers in `interpretation/__init__.py` already call `refresh_fighter(fighter_id)` per-event. **These are the targeted refreshes.**
2. Replace the every-tick full rebuild with:
   - A **weekly re-baseline** (run the full pass on `current_day % 7 == 0`) — catches anything the event-driven path missed.
   - On non-weekly ticks: a **targeted refresh** of only the fighters who fought today, retired today, signed today, or recovered from an injury today. The tick processor already knows these IDs (return values from `_check_retirements`, `_check_contract_expiry`, `_check_injury_recovery`, `_check_training_camps`).
3. `daily_headlines` regeneration should still run every tick (it's cheap — ~5-10 ms — and the player expects fresh headlines on Advance Day).

Expected impact: Tick time drops from **455 ms → ~120 ms** on daily ticks (saves ~333 ms). Weekly ticks remain ~455 ms (full re-baseline). Monthly ticks remain ~1 880 ms (career arc + training camp completions).

### 4.6 Pre-filter `_check_retirements` SELECT

Change the SELECT to filter by birthday in SQL:

```sql
SELECT f.fighter_id, ... FROM fighters f
LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
WHERE f.is_active = 1 AND f.is_retired = 0
  AND strftime('%m-%d', f.date_of_birth) = strftime('%m-%d', ?)
```

Expected impact: Drops the SELECT from 4 464 rows → ~12 rows. Saves ~25 ms / tick.

### 4.7 Index `current_promotion_id IS NULL` for Free Agents query

The Free Agents query (`current_promotion_id IS NULL AND is_active=1`) is 13.7 ms vs. the Roster query's 0.2 ms. The `idx_fighters_promo_active` index handles the `= ?` case but not the `IS NULL` case.

Add a partial index:

```sql
CREATE INDEX idx_fighters_free_agents
ON fighters(weight_class_id)
WHERE current_promotion_id IS NULL AND is_active = 1;
```

Expected impact: Free Agents query drops from **13.7 ms → <1 ms**. Saves ~13 ms per Free Agents refresh.

---

## 5. Performance Budget

### 5.1 Current measured performance

| Metric | Measured | Target | Gap |
|---|---|---|---|
| `run_tick` (daily) | **455 ms** | 150 ms | -305 ms |
| `run_tick` (monthly) | **1 880 ms** | 600 ms | -1 280 ms |
| `run_daily_interpretation_pass` | **333 ms** | 50 ms (targeted refresh) / 150 ms (weekly full) | -283 ms |
| `bus.publish(TICK_ADVANCED)` | **57 ms** | 30 ms | -27 ms |
| `_check_retirements` | **26 ms** | 2 ms | -24 ms |
| `DashboardScreen._refresh` (full) | **380 ms** | 100 ms | -280 ms |
| `DashboardScreen._refresh` (no-op, no dirty sections) | 380 ms (currently same as full) | <5 ms | -375 ms |
| `RosterScreen._refresh` (full) | **485 ms** | 150 ms | -335 ms |
| `RosterScreen._refresh` (no-op, no changes) | 485 ms (currently same as full) | <10 ms | -475 ms |
| `FreeAgentsScreen._refresh` (full) | **475 ms** | 150 ms | -325 ms |
| `FighterProfileScreen._refresh` (full) | **110 ms** | 50 ms | -60 ms |
| `refresh_all` lazy (active=Dashboard) | **400 ms** | 100 ms | -300 ms |
| `refresh_all` lazy (active=Roster) | **945 ms** | 200 ms | -745 ms |
| `refresh_all` force=True (all 5 screens) | **1 570 ms** | 400 ms | -1 170 ms |
| **Total experienced Advance Day latency** (active=Dashboard) | **~865 ms** | 250 ms | -615 ms |
| **Total experienced Advance Day latency** (active=Roster) | **~1 400 ms** | 350 ms | -1 050 ms |

### 5.2 The single biggest performance issue

**`run_daily_interpretation_pass` recomputes every fighter's momentum / pressure / career_phase / narrative_family / legacy_state from scratch on every tick — 333 ms / tick — even though most fighters' state didn't change.**

This is 73 % of total tick time. It's the single biggest lever. Fixing it (§4.5) drops the total experienced Advance Day latency by ~333 ms immediately.

### 5.3 The second-biggest performance issue

**`DashboardScreen._refresh_fighter_watch` runs 125 ms of widget work on every refresh, even though the watch data only changes on Advance Day.**

The three GradientCards (Top Prospect, Hottest Streak, Biggest Fall) are torn down and rebuilt from scratch — each is ~40 widgets (eyebrow + PortraitFrame + name HyperlinkLabel + MomentumRing + voice phrase + FormMeter + chips). On intra-screen navigation, this is pure waste.

### 5.4 Estimated improvement if all fixes applied

| Fix | Estimated ms saved per Advance Day click |
|---|---|
| §4.5 Targeted interpretation pass (skip full rebuild on non-weekly ticks) | **~280 ms** (333 → ~50 ms) |
| §4.6 Pre-filter `_check_retirements` SELECT by birthday | **~24 ms** |
| §4.1 Dashboard per-section dirty flags (intra-screen navigation case) | **~380 ms** (Dashboard refresh becomes no-op when no sections are dirty) |
| §4.4 Diff-based widget updates on Roster (intra-screen navigation case) | **~475 ms** (Roster refresh becomes ~10 ms) |
| §4.4 Diff-based widget updates on Free Agents | **~465 ms** |
| §4.4 Diff-based widget updates on Fighter Profile | **~60 ms** (110 → ~50 ms) |
| §4.7 Free Agents query index | **~13 ms** per Free Agents refresh |
| §4.3 Session-level cached queries | **~5-10 ms** per refresh (small but cumulative) |
| §3.3 Refresh active screen first, Dashboard in background | **~380 ms** of perceived latency (active screen updates immediately, Dashboard catches up) |

**Aggregate estimated improvement on Advance Day click (active=Dashboard, the common case):**
- Current: ~865 ms
- After §4.5 + §4.6: ~560 ms (tick side)
- After §4.1 (Dashboard dirty flags, Advance Day marks all sections dirty so still full refresh — but next navigation is free): ~560 ms (no improvement on the Advance Day click itself, but the next navigation back to Dashboard drops from 380 ms → ~5 ms)
- After §4.4 (Dashboard widget diffing): ~200 ms (Dashboard refresh drops from 380 → ~30 ms — only changed sections rebuild, and they diff instead of destroy+rebuild)
- **Total estimated Advance Day latency after all fixes: ~250 ms** (vs. current ~865 ms — **3.5× faster**).

**Aggregate estimated improvement on intra-screen navigation (player returns to a screen they just left):**
- Current: 380-485 ms (full destroy+rebuild)
- After §4.1 + §4.4: ~5-10 ms (no dirty sections → no-op refresh)
- **~50× faster** for the common "browse a few fighters" pattern.

---

## 6. Implementation Order (Recommended)

1. **§4.5** — Targeted interpretation pass. Biggest single win (~280 ms / tick). Requires changing `tick_processor.run_tick` to skip the full pass on non-weekly ticks + pass the affected fighter IDs from the inline helpers to a new `_targeted_interpretation_refresh(conn, fighter_ids)` function.
2. **§4.6** — Pre-filter `_check_retirements` SELECT. Trivial change, ~24 ms / tick saved.
3. **§4.1** — Dashboard per-section dirty flags. Medium effort (extend `GameState` with `_stale_sections: dict[screen_name, set[section_name]]`, add `mark_dirty` calls from event-bus subscribers, update Dashboard `_refresh` to skip non-dirty sections).
4. **§4.4** — Diff-based widget updates. Largest effort (rewrite `FighterTable.set_rows` + `FighterRow` to support `update(new_data)`; rewrite Dashboard section refreshes to call `configure(text=...)` on existing widgets instead of destroy+rebuild).
5. **§4.7** — Free Agents partial index. Trivial migration.
6. **§4.3** — Session-level cached queries. Low priority — small savings, but cleans up the screen code.
7. **§3.3** — Refresh active screen first. Small change to `state.refresh_all` ordering + use `widget.after(0, ...)` for the Dashboard refresh.

---

## 7. Appendix — Measurement Methodology

All measurements taken on the production-seeded DB at `data/cage_empire.db` (4 464 fighters, 4 234 fight_history rows, 5 287 news_items, 100 daily_headlines, 111 titles, 700 training_camps, 595 injuries, 8 suspensions).

### 7.1 Tick timing

Script: `/tmp/time_advance_day.py` (preserved in this audit's session, not committed).
- Registers all 19 TICK_ADVANCED subscribers via each module's `register_subscribers()`.
- Wraps `bus.publish` to time per-subscriber dispatch.
- Runs `tick_processor.run_tick(conn, "day", 1)` 3 times, reports median + per-subscriber median.
- DB was restored from backup before each run to keep measurements comparable.

### 7.2 Tick-piece timing

Script: `/tmp/time_tick_pieces.py`.
- Monkey-patches each inline helper (`_check_retirements`, `_check_contract_expiry`, `_check_injury_recovery`, `_check_training_camps`, `_check_scouting_assignments`) + `run_daily_interpretation_pass` + `bus.publish(TICK_ADVANCED)` with timing wrappers.
- Runs 5 ticks, reports per-piece median.

### 7.3 Screen refresh timing

Script: `scripts/perf/profile_refresh.py` (existing).
- Opens DB read-only via `?mode=ro`.
- Instantiates each screen under a hidden `ctk.CTk()` root.
- Calls `_refresh()` 5 times, reports median.

### 7.4 Dashboard section timing

Script: `/tmp/time_dashboard_sections2.py`.
- Calls each `_refresh_*` method directly with the appropriate signature.
- 5 iterations per section, median reported.

### 7.5 DB query counting

Script: `/tmp/count_queries.py`.
- Wraps `sqlite3.Connection.execute` with a counter via a `CountingConn` proxy.
- Calls each screen's `_refresh()` once, reports the count.

### 7.6 EXPLAIN plans

Existing script `scripts/perf/profile_screens.py` reports `EXPLAIN QUERY PLAN` for each hot query. Key findings:
- `idx_fighters_promo_active` covers the Roster query (0.2 ms) but not the Free Agents IS NULL case (13.7 ms).
- `daily_headlines` uses `idx_daily_headlines_date_type` (full scan, but only 100 rows — 0.1 ms).
- `news_items` uses `idx_news_items_published` (0.0 ms for LIMIT 20).
- `_find_hottest_streak_fighter`'s `SUBSTR(fd.momentum, 1, INSTR(...))` filter forces a full scan of `fighter_descriptors` (4.9 ms) — this is the only "slow" query on the Dashboard side. Could be fixed by adding a `momentum_label` column to `fighter_descriptors` (the label is already stored as the prefix of `momentum` before `||`).

### 7.7 Known measurement caveat

The test machine is missing the project fonts (Inter, JetBrains Mono, Source Serif Pro, Oswald) — Tk falls back to `Sans` / `Mono`. This may inflate widget construction time slightly (fallback font metrics differ). On the production machine with fonts installed, widget construction may be marginally faster — but the relative ordering of expensive vs. cheap sections will be identical.
