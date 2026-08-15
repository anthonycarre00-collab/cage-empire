# CAGE EMPIRE — Tier 1-3 Optimization Plan (for 5-10 year completion)

**Date:** 2026-08-15
**Status:** PLANNING — to be implemented by expert agents under supervisor
**Goal:** 365-day soak completion → 5-year → 10-year + 3 missing W-items (W12, W29, W42)

---

## Fight Beats Analysis (user's question)

**Do we need to save every round?** NO.

**fight_beats** (57,281 rows currently, ~17 beats/fight) is the raw beat-by-beat log. It's ONLY read during:
1. Fight resolution (fight_engine.py — the current fight being resolved)
2. Show rating calculation (show_rating.py — immediately after event completes)
3. Morale "exciting fight" check (morale.py:418 — immediately after fight resolves, checks if >10 beats in round 1)
4. Fight Night UI display (app_web.py — while player watches the results)

**After the event completes + show_rating + morale are calculated, fight_beats is NEVER read again.** The permanent fight record is stored in:
- `fights` table (result, method, round, time, performance_rating, fan_reaction_rating)
- `fight_rounds` table (per-round aggregates: damage, strikes, knockdowns, takedowns, gas, momentum)
- `commentary_segments` table (3-14 highlight texts selected for narrative)
- `fight_history` table (fighter-level outcome log)

**Plan:** Delete fight_beats for completed events after a 1-day delay (keeps the current event's beats for the Fight Night screen). This is a pruning operation, not a schema change. No replay feature exists or is planned — the user explicitly confirmed "theres no reason we should have any replay options that save every round ever."

**5-year impact:** fight_beats would grow from 57K → 286K rows without pruning. With pruning, it stays at ~0-500 rows (current event only). Saves ~27MB DB growth + eliminates the fastest-growing table.

---

## Tier 1 — 365-day completion (close the last 55 days)

### T1.1: Tune pruning thresholds (src/services/pruning_svc.py)
- news_items: 365 days → 180 days
- daily_headlines: 90 days → 60 days
- social_posts: 180 days → 90 days
- training_camps: 90 days → 60 days (completed only)
- injuries: 365 days → 180 days (resolved only)
- **NEW: fight_beats pruning** — delete fight_beats for fights whose event status='completed' AND event_date < sim_date - 1 day. Add to pruning_svc monthly tick + also run daily (lightweight — just deletes yesterday's beats).

### T1.2: Make weekly full-rebuild conditional (src/interpretation/snapshot_cache.py)
- `_should_full_rebuild` currently returns True every 7 days (current_day % 7 == 0), rebuilding ALL 4452 fighters.
- Change: only rebuild fighters whose attributes changed since the last full rebuild. Use a `fighters_dirty_for_rebuild` set that's populated by the HW9.1 tier-crossing check in career_arc.
- The weekly full-rebuild becomes a "dirty-fighter rebuild" — typically 200-500 fighters instead of 4452.
- Keep the engine_version mismatch check (full rebuild on logic change).
- **Expected savings:** ~300ms per weekly tick (7-day cycle).

### T1.3: Run 365-day soak with optimizations
- Use `--no-backup` flag (avoid WAL issues).
- Set 15-minute timeout (was 9min, need ~3 more min for the last 55 days).
- Verify: 0 future-dated COMPLETED events, tick HEALTHY, all Gate 3 metrics pass.

---

## Tier 2 — 5-year completion

### T2.1: Archive/delete old fight_beats (daily pruning)
- Already covered in T1.1 — fight_beats pruning runs daily.
- After 5 years, fight_beats stays at ~500 rows (current event only).
- No separate archive table needed — the data is genuinely disposable.

### T2.2: Consolidate marketability (W38)
- Currently computed in 3+ places:
  - `src/suspensions.py:151` — `_get_marketability(conn, fighter_id)`
  - `src/app_web.py:1087` — `_popularity_tier(marketability)`
  - `src/services/rival_ai/matchmaker.py:491` — `_marketability(fighter_a, fighter_b)`
- Create one canonical `src/interpretation/marketability.py` with `compute_marketability(conn, fighter_id)`.
- Update all 3 callsites to use the canonical function.
- **Expected savings:** ~20-30ms per tick (removes duplicate queries + computation).

### T2.3: Additional indexes
- `news_items (importance, published_at)` — for the cap check query.
- `fight_beats (fight_id)` — already exists (idx_fight_beats_fight from HW8.2).
- `commentary_segments (fight_id)` — for fight highlight lookups.
- `training_camps (is_completed, end_date)` — for pruning queries.

### T2.4: Run 5-year soak
- 1825 days. Estimated time: ~15-25 minutes with T1+T2 optimizations.
- Verify Gate 4 criteria: careers, promotions, economics, history coherent.

---

## Tier 3 — 10-year completion + 3 missing W-items

### T3.1: Implement 8 missing memory link types (W17)
Currently have 7/15 types. Missing:
1. `previous_fights` — write when two fighters have fought before (from fight_history)
2. `former_teammates` — write when a fighter changes gym (link to old gym mates)
3. `old_gyms` — write when a fighter changes gym (link to old gym)
4. `former_champions` — write when a title changes hands (link ex-champion to title)
5. `controversial_losses` — write on split_decision / disputed stoppage
6. `injuries` — write when a fighter is injured (link to the injury)
7. `promotions` — write when a fighter changes promotion (link to old promo)
8. `old_events` — write for milestone events (title fights, main events)

Add writers at the appropriate event-bus subscribers. Add search types to `surface_memories`. Backfill historical links from fight_history + titles.

### T3.2: W12 — Fight engine calibration (MEASURE ONLY, don't tune yet)
- Run 1000-fight simulation sample.
- Measure: KO%, sub%, decision%, draw%, DQ%, doctor stoppage%.
- Compare to real-world MMA distributions.
- **NOTE: The user will rebalance fighter attribute allocations separately. Do NOT tune the fight engine constants now — just measure + document.**
- Current distribution: UD 34%, KO/TKO 29%, Sub 23%, Doc Stop 20%, Split 6%, Draw 2%, DQ 1%, NC 2%.
- Real-world UFC: KO/TKO ~35%, Sub ~20%, Decision ~45%. Our KO is low, sub is high, decision is low.

### T3.3: W29 — Economic reconciliation script
- Write `scripts/economic_reconciliation.py`.
- For each promotion, for each month: `opening_cash + SUM(revenue) - SUM(expenses) = closing_cash`.
- Flag promotions where the reconciliation fails.
- Run on the world DB + report.

### T3.4: W42 — Provenance metadata
- Add `world_version TEXT` and `seed_version TEXT` columns to `schema_meta` (migration v3.35.0).
- Set `seed_version` on fresh DB build (e.g., "world_seed_v1").
- Set `world_version` on each save (e.g., "sim_2026-08-27_tick14").
- This lets us distinguish seed history from simulated history in long runs.

### T3.5: Run 10-year soak
- 3650 days. Estimated time: ~30-60 minutes with all optimizations.
- Verify Gate 5: world remains alive + historically reconstructible.
- Run `test_historical_continuity.py` on the result.

---

## Implementation Order + Delegation Plan

### Agent 1 (Tier 1): 365-day completion
- T1.1: Tune pruning thresholds + add fight_beats daily pruning
- T1.2: Make weekly full-rebuild conditional
- Verify: 30-day soak still PASS, 365-day soak COMPLETES
- **Files:** `src/services/pruning_svc.py`, `src/interpretation/snapshot_cache.py`, `src/career_arc.py` (dirty-set export)

### Agent 2 (Tier 2): 5-year completion
- T2.2: Consolidate marketability
- T2.3: Additional indexes
- Verify: 5-year soak completes
- **Files:** `src/interpretation/marketability.py` (NEW), `src/suspensions.py`, `src/app_web.py`, `src/services/rival_ai/matchmaker.py`, `src/build_db.py` (indexes)

### Agent 3 (Tier 3): 10-year + missing items
- T3.1: 8 missing memory link types
- T3.2: W12 fight calibration measurement (NO tuning)
- T3.3: W29 economic reconciliation
- T3.4: W42 provenance metadata
- Verify: test_rival_ai_memory still passes, new tests pass
- **Files:** `src/interpretation/memory_engine.py`, `src/news.py`, `src/rival_ai.py`, `scripts/economic_reconciliation.py` (NEW), `src/build_db.py` (migration)

### Supervisor (after all agents):
- Run full test suite
- Run 365-day, 5-year, 10-year soaks
- Commit + push
- Write final audit update

---

## What we're NOT doing (user instruction)
- ❌ Fight engine constant tuning (W12) — user will rebalance fighter attributes separately
- ❌ New features
- ❌ Architecture changes
- ❌ UI changes
