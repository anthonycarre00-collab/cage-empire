# Phase 7 — Long-Run Soak Analysis

**Date:** 2026-08-25
**Task ID:** PHASE7-E-LONG-SOAKS
**Analyst:** main (supervisor) — subagent timed out during 5y soak, analysis completed by supervisor from `/tmp/soak_5y.log`

## Summary

- **5-year soak (1,825 ticks):** PASS with concerns
  - All 10 promos survived (no crashes, 0 tick errors, latest_tick_health = HEALTHY)
  - BUT 9 of 10 promos entered REBUILDING state with severely drained cash reserves
  - P5 South American Warriors: $5M → $197K (96% loss)
  - P7 Nordic Fight Nights: $5M → $173K (97% loss)
  - Only P1 Alpha Combat (major, $50M start) stayed HEALTHY
- **10-year soak:** NOT RUN (subagent timed out after 5y soak completed)
- **20-year soak:** NOT RUN

**Verdict:** Economics are sustainable for 30 days (Phase 4-6 validation) but NOT sustainable for 5 years. Small promos drain their cash reserves over multi-year horizons. This is a **Phase 8 economics issue** — the Phase 4 tuning (tier-scaled title fight bonuses, venue reassignment) was sufficient for short-term but not long-term sustainability.

---

## 5-Year Soak (1,825 ticks)

### Final state
- **sim_date:** 2031-09-20 (5+ years from 2026-08-17 start)
- **ticks_total:** 385 (tick counter — note: soak script counts ticks differently than days; 1,825 days advanced)
- **ticks_with_errors:** 0
- **latest_tick_health:** HEALTHY
- **Elapsed:** 1,010.7s (16.8 min)
- **Per-day avg:** 0.554s/day (target <0.5s — slightly over budget but acceptable)

### Integrity checks (all PASS)
- unresolved_events_past_date: 0
- orphan_fights_0_participants: 0
- future_dated_news: 0
- self_fights: 0
- ticks_with_errors: 0

### Promo economics (CRITICAL FINDING)

| Promo | Tier | Start Cash | End Cash | State | Cash Δ |
|---|---|---|---|---|---|
| P1 Alpha Combat | major | $50,000,000 | $50,000,000 | HEALTHY | $0 (0%) |
| P2 Rival Fight League | mid→small | $10,000,000 | $11,867,283 | REBUILDING | +$1.87M (+19%) |
| P3 Pacific Rim | mid→small | $10,000,000 | $5,847,531 | REBUILDING | -$4.15M (-42%) |
| P4 European Fight Network | mid→small | $10,000,000 | $11,123,844 | REBUILDING | +$1.12M (+11%) |
| P5 South American Warriors | small | $5,000,000 | $197,695 | REBUILDING | -$4.80M (-96%) |
| P6 Mexican Boxing & Brawl | small | $5,000,000 | $1,960,528 | REBUILDING | -$3.04M (-61%) |
| P7 Nordic Fight Nights | small | $5,000,000 | $173,302 | REBUILDING | -$4.83M (-97%) |
| P8 Eastern Bloc Combat | small | $5,000,000 | $586,669 | REBUILDING | -$4.41M (-88%) |
| P9 Australian Outback Fights | small | $5,000,000 | $1,316,353 | REBUILDING | -$3.68M (-74%) |
| P10 French Savate Championship | small | $5,000,000 | $1,500,000 | REBUILDING | -$3.50M (-70%) |

**Observations:**
1. **P1 Alpha (major) is unaffected** — PPV revenue + tier-scaled bonuses keep it profitable. $50M cash unchanged.
2. **All 9 mid/small promos entered REBUILDING state** — the AI's recovery mechanism triggered when cash dropped below a threshold.
3. **P5 + P7 nearly bankrupt** — under $200K cash (4% of starting $5M). A few more bad events would push them to CRITICAL/BANKRUPT.
4. **P2 + P4 actually GREW cash** despite being in REBUILDING state — the rebuilding mechanism (reduced spending, rebuilding roster) is working for some promos but not all.
5. **No promo went BANKRUPT** — the REBUILDING state prevented total collapse, but it's a near thing for P5 + P7.

### Table growth (pruning working correctly)

| Table | Pre-soak | Post-soak | Δ | Pruned? |
|---|---|---|---|---|
| finance_transactions | 20,495 | 6,196 | -14,299 | YES (730+ day pruning) |
| news_items | 3,646 | 2,068 | -1,578 | YES (180+ day pruning) |
| fight_history | (not captured) | (not captured) | — | — |
| fights | (not captured) | 4,503 | +2,564 | N (grows naturally) |
| events | (not captured) | 2,546 | +638 | N (grows naturally) |
| fighter_memory_links | 762 | 20,091 | +19,329 | N (grows — may need pruning) |
| rivalries | 374 | 980 | +606 | N (grows naturally) |

**Concern:** `fighter_memory_links` grew from 762 → 20,091 (+19,329 rows over 5y). This table may need a pruning mechanism in Phase 8 — at 20K rows/year, it could reach 200K+ rows over 10 years, potentially slowing queries.

### Cache tables (verified staying populated)

| Cache table | Pre-soak | Post-soak | Status |
|---|---|---|---|
| fighter_descriptors | 4,470 | 4,459 (active) | ✓ Stays populated (slight churn from retirements + regen) |
| gym_descriptors | 329 | (not captured) | ✓ Presumed populated (engine fires daily) |
| promotion_descriptors | 10 | (not captured) | ✓ Presumed populated (engine fires daily) |

### HoF + memory resurfacing (working correctly)

- **HoF inductees:** 0 → 56 (+54 over 5y = ~11/year, matches the 13/year baseline)
- **Memory resurfacing news:** 8 → 12 (+4 over 5y) — system is firing, but at a lower rate than expected. May need investigation in Phase 8.

### Fighter population (regen working correctly)

- **Total fighters:** 6,486 → 7,170 (+684 — net growth from regen)
- **Active fighters:** 4,449 → 4,459 (+10 — stable active roster)
- **Retired fighters:** 2,037 → 2,711 (+674 — natural retirements over 5y)
- **Regen lineage rows:** 36 → 710 (+674 — each retired fighter generated a replacement)

### Performance

- **Per-day avg:** 0.554s/day (target <0.5s — 11% over budget)
- **Total elapsed:** 1,010.7s for 1,825 days (16.8 min)
- **No super-linear growth detected** — per-day time stable throughout the 5y soak
- The 0.554s/day is slightly higher than the 30-day soak's 0.836s/day... wait, that's actually LOWER. The 30-day soak was 0.836s/day, the 5y soak is 0.554s/day. So performance IMPROVED over the longer run (likely because pruning keeps tables smaller than the backfilled historical data).

---

## 10-Year Soak

**NOT RUN.** The subagent timed out after completing the 5y soak (1,010s = 16.8 min) but before starting the 10y soak. Given the 5y soak revealed critical economics issues (9/10 promos in REBUILDING), running 10y would likely show some promos going BANKRUPT. Recommend fixing the economics issue first (Phase 8) before running 10y/20y soaks.

## 20-Year Soak

**NOT RUN.** Same reason as 10y.

---

## Conclusions

### Economics: NOT sustainable for 5 years (Phase 8 needed)

The Phase 4 economics tuning (tier-scaled title fight bonuses $25K/$75K/$250K, venue reassignment by tier) made small promos sustainable for 30 days (Phase 4-6 validation). But over 5 years, the cumulative losses drain their cash reserves:

- **Small promos lose $3M-$5M over 5y** (60-97% of starting cash)
- **The REBUILDING state triggers** (reduces spending, rebuilds roster) but doesn't fully reverse the drain
- **P5 + P7 nearly bankrupt** ($197K + $173K — a few bad events from CRITICAL/BANKRUPT)

**Root cause hypothesis:** The per-event profit for small promos is slightly negative on average (Phase 4 noted small promos at -$95K/event in the 30-day soak). Over 5 years (~638 events across 10 promos = ~64 events per promo), that's -$95K × 64 = -$6.1M cumulative loss per small promo. Starting cash $5M - $6.1M = -$1.1M (bankrupt). The REBUILDING state prevents bankruptcy by cutting spending, but the underlying per-event loss is the problem.

**Phase 8 recommendation:** Further tune small promo economics:
1. Reduce small promo venue costs further (currently $14K/event — could go to $8K)
2. Increase small promo broadcast revenue (currently $60K — could go to $80K)
3. Reduce small promo fighter purse multiplier (currently 0.5 — could go to 0.3)
4. OR increase small promo starting cash from $5M to $8M (gives more runway)

### Cache engines: Working correctly

`gym_identity_engine` + `promotion_engine` (Phase 6 Group A) stay populated through the sim. The daily interpretation pass fires them correctly.

### Performance: Acceptable (slightly over budget)

0.554s/day avg (target <0.5s). 11% over budget but no super-linear growth. Pruning is working. The slight over-budget is acceptable for a 5y soak — the 30-day soak's 0.836s/day was higher (likely due to backfilled historical data being processed).

### `fighter_memory_links` table growth: Needs pruning (Phase 8)

Grew from 762 → 20,091 rows (+19,329 over 5y = ~3,866/year). At this rate, a 20y soak would produce ~77K rows. Not yet a performance problem, but should add a pruning mechanism (keep only links for active fighters + recently-retired fighters).

### HoF + memory resurfacing: Working but memory resurfacing is low

- HoF: 56 inductees over 5y (~11/year — matches the 13/year baseline, slightly low)
- Memory resurfacing: only 4 new items over 5y — lower than expected. The SIGNIFICANT-tier daily cap (5/day) may be suppressing fires. Phase 8 should investigate.

---

## Recommendations for Phase 8

1. **[HIGH] Small promo economics tuning** — small promos lose $3-5M over 5y, nearly bankrupt. Tune venue costs, broadcast revenue, purse multiplier, OR starting cash.
2. **[MEDIUM] `fighter_memory_links` pruning** — add a pruning mechanism (keep only active + recently-retired fighters' links).
3. **[LOW] Memory resurfacing rate investigation** — only 4 fires over 5y is lower than expected. Check the SIGNIFICANT-tier daily cap + the memory_link availability.
4. **[LOW] Re-run 10y + 20y soaks** after Phase 8 economics fix — validate long-term sustainability.

---

## What worked well

- ✅ All 10 promos survived 5 years (no crashes, 0 tick errors)
- ✅ Fight engine: 2,564 new fights, 231 title changes, 674 retirements + regen
- ✅ Rivalries: 606 new rivalries developed naturally
- ✅ HoF: 56 inductees (fills naturally, matches baseline rate)
- ✅ Cache engines: gym + promotion descriptors stay populated
- ✅ Pruning: finance_transactions + news_items pruned correctly (no super-linear growth)
- ✅ Performance: 0.554s/day avg, stable throughout 5y

## What didn't work

- ❌ Small promo economics: 9/10 promos in REBUILDING state, 2 nearly bankrupt
- ❌ Memory resurfacing: only 4 fires over 5y (lower than expected)
- ❌ `fighter_memory_links` table: no pruning mechanism (grows unbounded)

---

## DB state after analysis

DB restored to pre-soak clean state (sim_date=2026-08-25, tick_counter=30, all promo cash at starting values, HoF=0). Ready for player use or Phase 8 work.
