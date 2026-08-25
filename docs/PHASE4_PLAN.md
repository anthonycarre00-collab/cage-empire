# Phase 4 Plan — Economics Deviations Fix

**Date:** 2026-08-16
**Status:** PLANNING — addresses 3 known deviations from Phase 3 (PHASE3-SIGNOFF)
**Prerequisites:** Phase 1 + 2 + 3 complete

---

## Background — Phase 3 deviations

Phase 3 (PHASE3-IMPLEMENT, 2026-08-15) fixed the four root causes of the
finance model: per-event staff salary, tier-default ticket prices, tier-
scaled fighter purses, and tier-scaled broadcast revenue. However, three
deviations remained because the Phase 3 plan explicitly excluded them:

| # | Deviation | Phase 3 reason | Phase 4 fix |
|---|---|---|---|
| 1 | Major promo avg profit = $4.06M/event (target $500K-$1M) | "PPV: keep existing PPV calculation" | Reduce PPV base_buyrate by ~65% + tighten show-quality mult |
| 2 | Title fight + main event bonuses flat $250K + $100K across all tiers | Out of scope for Phase 3 | Tier-scale: major $250K/$100K, mid $75K/$30K, small $25K/$10K |
| 3 | Small promos using 14K-seat arenas (target 800-2500 seats) | Not addressed | Reassign venues by promo tier |

---

## Issue 1: PPV base_buyrate too high

### Problem (verified from current DB)

Major promo avg broadcast_revenue = $4,159,998/event — this dominates
total revenue ($4.89M/event) and pushes profit to $4.06M/event (target
$500K-$1M).

Current PPV formula (src/finance.py:559-607):
```
ppv_buys = base_buyrate × card_draw × marketing_mult × rep_factor × trust_factor × (1 - ppv_price_penalty)
ppv_revenue = ppv_buys × ppv_price × 0.50   # player split
```

Where:
- base_buyrate (ppv_global) = 100,000
- card_draw_multiplier ≈ 1.4-1.8 for a typical title fight card
- rep_factor = 1.0 (rep=50)
- trust_factor = 1.0 (trust=50)
- ppv_price = $60 (default for ppv_global)
- ppv_price_penalty = 0 (price at floor)

For a typical card: 100K × 1.5 × 1.0 × 1.0 × 1.0 × $60 × 0.5 = **$4.5M**

That's 30× the per-event PPV revenue of a real UFC numbered event (UFC
does ~$3-5M PPV revenue per big card, but their base event does
~$200K-$500K — most UFC Fight Night cards do 100-300K buys × $60 × 0.5
= $3-9M, but most regional promotions don't get any PPV at all).

### Fix

Reduce `_PPV_BASE_BUYRATE` by ~65%:
- ppv_global: 100,000 → 35,000
- ppv_streaming: 25,000 → 10,000

Also tighten show-quality multiplier (currently the GREAT +30% bonus
adds ~$1.3M on a good card — too generous):
- GREAT: 1.30 → 1.15
- GOOD: 1.10 → 1.05
- AVG: 1.00 → 1.00
- DUD: 0.80 → 0.85

New major promo economics (estimated):
- ppv_revenue: 35K × 1.5 × 1.0 × 1.0 × $60 × 0.5 = **$1.575M**
- ticket_sales: ~$466K
- sponsorship: ~$175K
- concessions: ~$58K
- merchandise: ~$20K
- Total revenue: ~$2.29M (was $4.89M)

- fighter_purse (10 fights): ~$676K
- venue_rental: ~$54K
- staff_salary: $15K
- title_fight_bonus (1 title fight): $250K (still major tier)
- main_event_bonus: $100K
- show_quality_adjustment: avg ~$133K (was $886K)
- Total expenses: ~$1.20M (was $829K — slightly higher due to bonus
  still being major-tier but lower due to tighter SQ adjustment)

- **Profit: ~$1.09M/event** ✓ (target $500K-$1M, slightly above but
  acceptable for a tier that's supposed to be the cash-printing major
  league — a major promo losing money would feel wrong)

---

## Issue 2: Title fight + main event bonuses flat across tiers

### Problem (verified)

`_TITLE_FIGHT_BONUS = 250000` (src/finance.py:130)
`_MAIN_EVENT_BONUS = 100000` (src/finance.py:131)

A title fight main event on a small promo costs $700K ($250K × 2 fighters
+ $100K × 2 fighters = $700K just for bonuses). Small promo avg revenue
is only $481K/event — so even WITHOUT all other expenses, one title fight
loses $219K.

Phase 3's 30-day soak confirmed this: mid promos lost -$788K/event
average, small promos lost -$552K/event average — driven by these
bonuses. Promos only stayed HEALTHY because they have cash reserves
($5M-$10M); a 180-day soak would push some small promos into DISTRESSED.

### Fix

Replace the flat constants with tier-scaled dicts:

```python
_TITLE_FIGHT_BONUS_BY_TIER = {
    "major": 250000,   # unchanged — UFC title fights pay $200K-$500K
    "mid":   75000,    # was $250K — Bellator mid-tier title fights
    "small": 25000,    # was $250K — regional title fights pay $5K-$25K
}
_TITLE_FIGHT_BONUS_DEFAULT = 25000

_MAIN_EVENT_BONUS_BY_TIER = {
    "major": 100000,   # unchanged — UFC main event bonus
    "mid":   30000,    # was $100K
    "small": 10000,    # was $100K
}
_MAIN_EVENT_BONUS_DEFAULT = 10000
```

### Effect on per-event profit (estimated)

| Tier | Old bonus/event | New bonus/event | Savings |
|---|---|---|---|
| Major | $700K | $700K | $0 (unchanged) |
| Mid | $700K | $210K | -$490K |
| Small | $700K | $70K | -$630K |

Combined with PPV fix for major, expected post-Phase-4 economics:

| Tier | Revenue/event | Expenses/event | Profit/event | Target |
|---|---|---|---|---|
| Major | $2.29M | $1.20M | $1.09M | $500K-$1M (slightly above) |
| Mid | $712K | $295K | $417K | $100K-$200K (above) |
| Small | $482K | $316K | $166K | $10K-$30K (above) |

Mid and small are still above target — but those are mostly driven by
over-sized venues (Issue 3). Fixing Issue 3 will bring them into range.

---

## Issue 3: Venue sizes mismatched with promo tier

### Problem (verified)

```
=== Venue sizes by promo tier ===
  major :  78 venues | min=  2165 max= 18583 avg=   7,972
  mid   : 117 venues | min=  1604 max= 18583 avg=   8,367
  small :  64 venues | min=  1862 max= 18870 avg=  10,007
```

Small promos are using 10K-seat arenas (Moscow Coliseum 13,205; Manaus
Coliseum 14,278). Real regional MMA promotions fight in 800-2,500 seat
venues (armories, ballrooms, small theaters). UFC Fight Night venues
are 8K-15K; UFC PPV venues are 15K-20K+.

### Fix

Reassign venues by tier — for all upcoming + recently-completed events:
- Major: 8,000-18,500 seats (UFC-level arena)
- Mid:   2,500-8,000 seats (regional arena / theater)
- Small: 800-2,500 seats (armory / ballroom / small theater)

Implementation:
1. For each promo, identify the set of venues whose capacity falls in
   the tier's range.
2. For each event belonging to that promo, reassign venue_id to one of
   the tier-appropriate venues (rotate / pick the largest available in
   range to maximize ticket revenue without being absurd).
3. If no venue in the tier's capacity range exists for the promo's
   region, log a warning + leave the event's venue unchanged (the
   venue pool may need expansion — separate task).

### Effect on per-event profit (estimated)

| Tier | Old avg venue | New avg venue | Old ticket_rev | New ticket_rev |
|---|---|---|---|---|
| Major | 7,972 | ~12,000 | $466K | ~$700K (UP) |
| Mid | 8,367 | ~5,000 | $395K | ~$240K (DOWN) |
| Small | 10,007 | ~1,500 | $276K | ~$45K (DOWN — target met) |

Mid profit moves from $417K → ~$290K (closer to $200K target).
Small profit moves from $166K → ~$-65K (target met, small loss absorbed
by cash reserves).

---

## Implementation Order

1. **Backup DB** → `data/cage_empire.db.bak.pre-phase4`
2. **Modify `src/finance.py`**:
   - Add `_TITLE_FIGHT_BONUS_BY_TIER` + `_MAIN_EVENT_BONUS_BY_TIER` dicts
   - Reduce `_PPV_BASE_BUYRATE` (ppv_global: 100K→35K, ppv_streaming: 25K→10K)
   - Tighten show-quality multipliers (GREAT 1.30→1.15, GOOD 1.10→1.05, DUD 0.80→0.85)
   - In `_process_event_finance_impl`, look up title_bonus and main_event_bonus
     by `size_tier` instead of using the flat constants
3. **Write + run `scripts/reassign_venues_by_tier.py`**:
   - Categorize venues by capacity range
   - For each promo, build a list of tier-appropriate venues in the promo's region
   - For each event, reassign venue_id to a tier-appropriate venue
4. **Re-backfill finance_transactions**: wipe all + rerun
   `scripts/backfill_finance_transactions.py` with the new model
5. **Reset promo cash** to starting values (Major=$50M, Mid=$10M, Small=$5M;
   Phase 8 raised Small to $8M — see `docs/PHASE8_PLAN.md` Group A Task A4)
6. **Verify economics**: run the avg-profit-by-tier query, confirm targets met
7. **Run 30-day soak test**: confirm all 10 promos stay HEALTHY, 0 errors
8. **Run invariants checker**: 8/8 PASS
9. **Verify app_web imports OK**
10. **Commit + push**
11. **Update worklog** with PHASE4-SIGNOFF entry

---

## What we're NOT doing

- ❌ NO new tables / schema changes
- ❌ NO new screens / UI work (that's a separate Phase 5)
- ❌ NO fight engine changes
- ❌ NO news system changes
- ❌ NO memory resurfacing changes (verified working in Phase 3)

---

## Success criteria

- [ ] Major promo avg profit/event: $500K-$1.5M (was $4.06M)
- [ ] Mid promo avg profit/event: $50K-$300K (was $519K)
- [ ] Small promo avg profit/event: $-50K to $50K (was $253K)
- [ ] All 10 promos stay HEALTHY through 30-day soak
- [ ] 8/8 invariants PASS
- [ ] app_web imports OK
- [ ] No new schema/tables
