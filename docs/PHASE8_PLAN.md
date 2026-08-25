# Phase 8 Plan — Economics Sustainability + Memory Links Pruning + Memory Resurfacing Fix

**Date:** 2026-08-25
**Status:** PLANNING ONLY — no code changes yet
**Task ID:** PHASE8-ECON-MEMORY
**Prerequisites:** Phase 7 complete (commit `6de2a97`). 5-year soak revealed 3 issues requiring fixes before 10y/20y soaks.

---

## Background

The Phase 7 5-year soak (`docs/PHASE7_SOAK_ANALYSIS.md`) revealed 3 issues:

1. **[HIGH] Small promo economics not sustainable** — 9/10 promos entered REBUILDING state with severely drained cash. P5 South American Warriors: $5M → $197K (96% loss). P7 Nordic Fight Nights: $5M → $173K (97% loss).

2. **[MEDIUM] `fighter_memory_links` table grows unbounded** — 762 → 20,091 rows over 5y (+19,329). No pruning mechanism. At ~3,866/year, a 20y soak would reach ~77K rows.

3. **[LOW but user-flagged] Memory resurfacing rate too low** — only 4 fires over 5y when 30-day soaks showed 3-4 fires per 30 days (projected ~180-240 over 5y). The system is firing at ~2% of expected rate.

---

## Root Cause Analysis

### Issue 1 — Small promo economics

**Phase 4 tuning was sufficient for 30 days but not 5 years.** The 30-day soak showed small promos at -$95K/event avg. Over 5 years (~64 events per small promo):
- Cumulative loss: -$95K × 64 = -$6.1M per small promo
- Starting cash: $5M
- Ending cash: $5M - $6.1M = -$1.1M (bankrupt)

The REBUILDING state (AI cuts spending when cash drops below ~$2M) prevents bankruptcy but doesn't reverse the underlying per-event loss. Some promos (P2, P4) recovered because REBUILDING cut spending enough to flip them profitable; others (P5, P7) didn't recover because their per-event loss was too large.

**Root cause:** Small promo per-event expenses exceed per-event revenue even after Phase 4 tuning. The Phase 4 fix reduced title fight bonuses from $250K to $25K (small tier), but fighter purses + venue rental + staff salary + other expenses still exceed ticket + broadcast + concessions revenue.

### Issue 2 — `fighter_memory_links` no pruning

The `src/services/pruning_svc.py` `_PRUNE_POLICY` tuple (line 91) lists 8 tables that get pruned monthly:
- news_items (180 days)
- daily_headlines (60 days)
- social_posts (90 days)
- injuries (180 days, is_active=0)
- suspensions (180 days, is_active=0)
- training_camps (60 days, is_completed=1)
- scouting_reports (90 days)
- fight_beats (daily, special case)

**`fighter_memory_links` is NOT in the policy.** It was added in Phase 2 Task 2.5 (Memory Engine) but never added to the prune policy. Each retirement creates a `successor` link + each `populate_style_echo` creates a `style_echo` link — both accumulate forever.

**Memory links are valuable for narrative** ("this fighter is the successor to a former champion") — so we shouldn't prune them too aggressively. The right policy: prune links where BOTH fighters are retired (the link is no longer relevant to active gameplay).

### Issue 3 — Memory resurfacing low rate

**Investigation found 3 contributing factors:**

1. **SIGNIFICANT daily cap is 5/day, shared across ALL SIGNIFICANT news types** (`src/news.py:891-897`). Memory resurfacing competes with: fight results, injuries, suspensions, career arcs, cross-promo, comebacks (8+ other SIGNIFICANT news types per `src/news.py:827-832`). When a fight is booked, the date often already has 5 SIGNIFICANT items queued (from fight resolutions earlier that day), so memory resurfacing is suppressed.

2. **`surface_memories` returns empty for most fighter pairs** — the first search (`_search_previous_fight`) only finds matches if the two fighters have fought before. Most bookings are between fighters who have never met, so this returns None. The other 8 searches (shared_gym, former_teammate, injury_history, title_fight_history, former_champion, controversial_loss, major_upset, career_milestone) also return None for most pairs.

3. **Memory resurfacing only fires at fight booking time** (`src/app_web.py:8344` + `src/services/matchmaking.py:1633`). It does NOT fire on:
   - Daily tick (no scheduled "memory resurfacing" pass)
   - Event completion
   - Fighter retirement
   - Title change (the `generate_memory_resurfacing_news` function exists at `src/news.py:1503` but only fires on TITLE_CHANGED events per `src/news.py:5451`)

**The fix should:**
- Give memory resurfacing its OWN daily cap (separate from the shared SIGNIFICANT cap) so it doesn't compete with fight results
- Add a daily memory resurfacing pass that surfaces memories for upcoming scheduled fights (not just at booking time)
- Loosen the cap to 2/day (down from competing for 5/day with 8+ other types)

---

## Tasks (4 groups)

### Group A — Small Promo Economics Tuning [HIGH]

**Goal:** Make small promos sustainable for 5+ years. Target: small promo avg profit per event between -$10K and +$30K (currently -$95K).

**Approach:** Don't change the underlying model (Phase 4 tuning was correct in principle). Instead, adjust the specific levers that are draining small promo cash:

#### Task A1 — Reduce small promo venue rental cost
**Current:** `src/finance.py` `_VENUE_COST_PER_SEAT_BY_TYPE` — arena $7, ballroom $5, theater $4, outdoor $3. Small promos use 1.5K-5K seat venues (avg 3,489 after Phase 4 reassignment).
**Problem:** A 3,489-seat theater at $4/seat = $13,956/event. That's 6% of a small promo's typical $220K revenue — too high for regional shows.
**Fix:** Add a tier-scaled venue cost multiplier:
- Major: 1.0x (unchanged — $7/seat arena, $5 ballroom, etc.)
- Mid: 0.7x ($4.90 arena, $3.50 ballroom, etc.)
- Small: 0.4x ($2.80 arena, $2.00 ballroom, $1.60 theater, $1.20 outdoor)

**Files:** `src/finance.py` — `_VENUE_COST_PER_SEAT_BY_TIER` new dict + apply in `_process_event_finance_impl` venue rental calculation.

#### Task A2 — Increase small promo broadcast revenue floor
**Current:** `src/finance.py` `_compute_broadcast_revenue` non-PPV path — local_stream: $10K-$50K (rep-scaled). Small promos get ~$60K avg.
**Problem:** $60K is too low for sustainability. Real regional streaming deals pay $30K-$100K guaranteed.
**Fix:** Raise the local_stream floor from $10K to $25K, ceiling from $50K to $80K. Also raise tv_regional/streaming floor from $100K to $120K for mid-tier promos.

**Files:** `src/finance.py` `_compute_broadcast_revenue` non-PPV path.

#### Task A3 — Reduce small promo fighter purse multiplier further
**Current:** `src/finance.py` `_PURSE_MULT_BY_TIER` — major 3.0, mid 1.5, small 0.5.
**Problem:** Small promo fighters get ($15K/yr salary / 3 events) × 0.5 = $2.5K/event base purse. With win bonus (100%) + finish bonus ($25K), avg purse = ~$15K. For a 6-fight card, that's $90K total purses.
**Fix:** Reduce small promo multiplier from 0.5 to 0.3. New base purse: ($15K/3) × 0.3 = $1.5K/event. Avg purse with bonuses: ~$10K. For 6 fights: $60K total.

**Files:** `src/finance.py` `_PURSE_MULT_BY_TIER`.

#### Task A4 — Increase small promo starting cash
**Current:** Major $50M, Mid $10M, Small $5M.
**Problem:** $5M is too thin for 5+ year sustainability. Even with A1-A3 fixes, small promos need a buffer for bad months.
**Fix:** Increase small promo starting cash from $5M to $8M. This gives ~60% more runway.

**Files:** `src/finance.py` (or wherever the starting cash is set — check `src/build_db.py` for the seed value + the reset script `scripts/phase4_apply_all.py`).

#### Task A5 — Re-backfill finance_transactions + reset cash
After A1-A4 code changes, wipe all finance_transactions + re-backfill with new model + reset cash to new starting values (Small=$8M).

**Files:** `scripts/phase4_rebackfill_and_reset.py` (extend with new starting values) OR new `scripts/phase8_apply_economics.py`.

**Acceptance criteria:**
- [ ] Small promo avg profit/event between -$10K and +$30K (was -$95K)
- [ ] All 10 promos stay HEALTHY through 30-day soak (no REBUILDING)
- [ ] 8/8 invariants PASS
- [ ] app_web imports OK

---

### Group B — `fighter_memory_links` Pruning [MEDIUM]

**Goal:** Add a pruning mechanism for `fighter_memory_links` to prevent unbounded growth. Target: keep table under 10K rows over 20y runs (was projected 77K).

**Approach:** Prune links where BOTH fighters are retired (the link is no longer relevant to active gameplay). Active fighters' links are always kept (they may surface in future memory resurfacing).

#### Task B1 — Add `fighter_memory_links` to prune policy
**Current:** `_PRUNE_POLICY` in `src/services/pruning_svc.py:91` has 8 tables. `fighter_memory_links` is not included.
**Problem:** Table grows unbounded (762 → 20,091 over 5y).
**Fix:** Add a new entry to `_PRUNE_POLICY`:
```python
("fighter_memory_links", "created_at", 365,
 """linked_fighter_id IN (SELECT fighter_id FROM fighters WHERE is_retired=1)
    AND fighter_id IN (SELECT fighter_id FROM fighters WHERE is_retired=1)"""),
```

This prunes links older than 365 days where BOTH the fighter_id and linked_fighter_id are retired. Keeps active fighters' links regardless of age.

**Files:** `src/services/pruning_svc.py` `_PRUNE_POLICY`.

#### Task B2 — Add `created_at` column if missing
Check if `fighter_memory_links` has a `created_at` column. If not, add it via migration (schema 3.37.0 → 3.38.0).

**Files:** `src/build_db.py` migration function + `data/cage_empire.db` schema.

#### Task B3 — Verify pruning doesn't break memory resurfacing
After pruning, verify `surface_memories` still works correctly — it should only fail to find links for pruned (both-retired) pairs, which is correct behavior (we don't surface memories for retired vs retired pairs).

**Files:** No code changes — verification only.

**Acceptance criteria:**
- [ ] `fighter_memory_links` added to `_PRUNE_POLICY`
- [ ] `created_at` column exists (migration if needed)
- [ ] Pruning test: simulate 2 retired fighters with a link, run prune, verify link is removed
- [ ] Active fighters' links NOT pruned
- [ ] 8/8 invariants PASS

---

### Group C — Memory Resurfacing Rate Fix [LOW but user-flagged]

**Goal:** Increase memory resurfacing fire rate from 4/5y to projected 50+/5y. The system has 20K memory_links but only surfaces 4 — that's a 0.02% utilization rate.

**Approach:** 3 fixes addressing the 3 root causes:

#### Task C1 — Give memory resurfacing its own daily cap
**Current:** `src/news.py:891-897` — SIGNIFICANT cap is 5/day, shared across all SIGNIFICANT news types. Memory resurfacing competes with 8+ other types.
**Problem:** When memory resurfacing fires at fight booking time, the date often already has 5 SIGNIFICANT items queued (fight results, injuries, etc.), so memory resurfacing is suppressed.
**Fix:** Add a separate daily cap for `memory_resurfacing` topic. New logic in `_write_news_item`:
- If topic == 'memory_resurfacing', check the memory_resurfacing-specific cap (2/day) INSTEAD of the SIGNIFICANT cap.
- Other SIGNIFICANT topics still use the shared 5/day cap.

**Files:** `src/news.py` `_write_news_item` + new `_MEMORY_RESURFACING_DAILY_CAP = 2` constant.

#### Task C2 — Add daily memory resurfacing pass for upcoming fights
**Current:** Memory resurfacing only fires at fight booking time (`book_fight` + `schedule_next_event`). It does NOT fire on daily tick.
**Problem:** For fights booked days/weeks in advance, the memory resurfacing news is published on booking day — but the player may not see it because the news feed moves on. By fight day, the memory is forgotten.
**Fix:** Add a daily pass that surfaces memories for fights scheduled in the next 7 days. This gives the player a "fight coming up — here's the backstory" reminder.
- New function `generate_upcoming_fight_memory_news(conn, event)` in `src/news.py`
- Subscribes to `TICK_ADVANCED` event
- Finds fights scheduled in the next 7 days where the two fighters have a memory_link
- Writes a memory_resurfacing news item for each (subject to the C1 daily cap)

**Files:** `src/news.py` new function + subscriber registration.

#### Task C3 — Loosen `surface_memories` to find more matches
**Current:** `surface_memories` returns the FIRST matching memory per search type. If `previous_fight` returns None, it tries `shared_gym`, etc.
**Problem:** Most fighter pairs have no previous fight + no shared gym + no former teammate link — so all 9 searches return None.
**Fix:** Add 2 new search types that find more matches:
- `same_weight_class` — are they in the same weight class? (common — most fighters share a WC with ~200 others)
- `ranked_proximity` — are they within 5 ranks of each other? (creates "two top-10 fighters meet" narrative)

These are weaker memories but still worth surfacing for fight previews.

**Files:** `src/interpretation/memory_engine.py` — 2 new search functions + add to `surface_memories` loop.

**Acceptance criteria:**
- [ ] Memory resurfacing fires at least 20 times over a 30-day soak (was 3-4)
- [ ] Memory resurfacing fires at least 100 times over a 5-year soak (was 4)
- [ ] C1: memory_resurfacing has its own 2/day cap, separate from SIGNIFICANT 5/day
- [ ] C2: daily pass surfaces memories for upcoming fights
- [ ] C3: 2 new search types find matches for ~30% of fighter pairs (was <5%)
- [ ] 8/8 invariants PASS

---

### Group D — Re-run 10y + 20y Soaks [LOW]

**Goal:** After Groups A-C, re-run the 10y + 20y soaks to validate long-term sustainability.

**Approach:**
1. Run 10y soak (3,650 ticks). If PASS (all 10 promos HEALTHY, 0 tick errors), run 20y.
2. Run 20y soak (7,300 ticks).
3. Track: promo cash trajectory, table growth (especially fighter_memory_links after B pruning), cache tables, HoF, memory resurfacing rate (after C fix).
4. Update `docs/PHASE7_SOAK_ANALYSIS.md` with 10y + 20y results (or create `docs/PHASE8_SOAK_ANALYSIS.md`).

**Files:** `docs/PHASE8_SOAK_ANALYSIS.md` (NEW) — analysis report.

**Acceptance criteria:**
- [ ] 10y soak: all 10 promos HEALTHY through 3,650 ticks, 0 tick errors
- [ ] 20y soak: all 10 promos HEALTHY through 7,300 ticks (or document which went REBUILDING + why)
- [ ] `fighter_memory_links` stays under 10K rows (was projected 77K without pruning)
- [ ] Memory resurfacing fires at least 200 times over 20y (was 4)
- [ ] Analysis report produced

---

## Implementation Order

```
Day 1 (parallel):
  Group A — Small promo economics (general-purpose subagent)
    A1: venue cost multiplier
    A2: broadcast revenue floor
    A3: purse multiplier
    A4: starting cash
    A5: re-backfill + reset
  Group B — Memory links pruning (general-purpose subagent)
    B1: add to prune policy
    B2: created_at column (if needed)
    B3: verify pruning

Day 2 (parallel):
  Group C — Memory resurfacing fix (general-purpose subagent)
    C1: own daily cap
    C2: daily pass for upcoming fights
    C3: 2 new search types

Day 3:
  30-day soak test (verify Groups A-C work)
  If PASS, start 10y soak (background, ~50 min)

Day 4:
  10y soak results analysis
  If PASS, start 20y soak (background, ~100 min)

Day 5:
  20y soak results analysis
  Update docs/PHASE8_SOAK_ANALYSIS.md
  Final verification + commit + push
  Worklog PHASE8 signoff
```

**Total estimated wall-clock:** ~5 days with parallelism + soak runtimes.

---

## Subagent Delegation Strategy

| Task | Subagent type | Why |
|---|---|---|
| Group A (economics) | general-purpose | Code changes to `src/finance.py` + `scripts/phase8_apply_economics.py` (new backfill script). Needs to understand the existing finance model + extend it carefully. |
| Group B (pruning) | general-purpose | Code change to `src/services/pruning_svc.py` + possible migration. Small but needs care. |
| Group C (memory resurfacing) | general-purpose | Code changes to `src/news.py` + `src/interpretation/memory_engine.py`. Needs to understand the memory engine + news system. |
| Group D (soaks) | general-purpose | Run soaks + write analysis report. Supervisor reviews. |

**File conflict risk:**
- Group A touches `src/finance.py` + new script + `data/cage_empire.db`
- Group B touches `src/services/pruning_svc.py` + `src/build_db.py` (migration) + `data/cage_empire.db`
- Group C touches `src/news.py` + `src/interpretation/memory_engine.py`

Groups A + B both touch `data/cage_empire.db` (A resets cash, B adds migration). Run A first (resets cash), then B (adds migration). Or combine into one task if needed.

Groups A + C don't overlap. Run in parallel.

**Recommended parallelism:**
- Day 1: Group A (serial — economics changes need to be applied in order) + Group C (parallel — different files)
- Day 2: Group B (after A, since B's migration needs to run on A's reset DB)
- Day 3-5: Group D soaks (after A+B+C complete)

---

## What we're NOT doing in Phase 8

- ❌ NO new screens (all 24 implemented)
- ❌ NO new schema/tables (only adding `created_at` column to existing `fighter_memory_links` if missing)
- ❌ NO new dependencies
- ❌ NO fight engine changes
- ❌ NO UI redesign
- ❌ NO strict §17.1 LOW violations (deferred — large scope)

---

## Success criteria

- [ ] Group A: Small promo avg profit/event between -$10K and +$30K (was -$95K)
- [ ] Group A: All 10 promos stay HEALTHY through 30-day soak
- [ ] Group B: `fighter_memory_links` pruning added (both-retired + 365 days)
- [ ] Group B: Table stays under 10K rows over 20y soak (was projected 77K)
- [ ] Group C: Memory resurfacing fires 20+ times over 30-day soak (was 3-4)
- [ ] Group C: Memory resurfacing fires 100+ times over 5y soak (was 4)
- [ ] Group D: 10y soak PASS (all 10 promos HEALTHY, 0 tick errors)
- [ ] Group D: 20y soak PASS (or document which promos went REBUILDING + why)
- [ ] 8/8 invariants PASS throughout
- [ ] app_web imports OK throughout
- [ ] Analysis report at `docs/PHASE8_SOAK_ANALYSIS.md`
- [ ] Committed + pushed
- [ ] Worklog updated with PHASE8-SIGNOFF entry

---

## Open questions for user

None — all groups are well-scoped. Proceed with implementation.
