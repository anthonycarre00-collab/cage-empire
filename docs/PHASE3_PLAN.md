# Phase 3 Plan — Economics Tuning + HoF Fix + Memory Verification

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes yet
**Prerequisites:** Phase 1 + 2 complete (data bugs fixed, Tkinter removed, code bugs fixed)

---

## Issue 1: Hall of Fame — 289 inductees (should be ~0-20)

### Problem
The HoF backfill inducted 287 ACTIVE fighters + 2 grey-name fighters. Hall of Fame should ONLY contain RETIRED fighters who had notable careers. At pre-sim state (sim_date=2026-07-20, tick=0), no real fighters have retired yet — the HoF should be EMPTY or contain only a small number of pre-seed historical legends.

### Fix
- DELETE all 289 HoF inductees
- The HoF system fires DURING the sim when fighters retire (verified in 1-year sim: 13 inductees)
- Starting the game with an empty HoF is correct — the player builds the history

### Alternative (if empty HoF feels wrong)
- Induct 10-20 "historical legends" from the grey-name fighters (is_retired=1) who have notable records
- These are fighters who "retired before the game started"
- Criteria: retired + record_wins >= 25 (gives ~5-10 inductees from the 19 grey-name fighters with career data)

**Recommendation:** Start EMPTY. The HoF fills naturally during play. 13 inductees/year is realistic.

---

## Issue 2: Promotion Cash — P6 anomaly

### Problem
P6 (Mexican Boxing & Brawl) has $5,006,782 instead of $5,000,000. The $6,782 is sim residue from the 1-tick test.

### Fix
- Reset P6 to exactly $5,000,000
- All other promos are correct (Major=$50M, Mid=$10M, Small=$5M)

---

## Issue 3: Finance Model — fundamentally unbalanced

### Problem (verified from backfilled data)

The finance model produces absurd profits:

| Promo tier | Avg revenue/event | Avg expenses/event | Avg profit/event | Assessment |
|---|---|---|---|---|
| Major (Alpha) | $5,097K | $338K | $4,759K | WAY too profitable |
| Mid (RFL) | $837K | $310K | $527K | Too profitable |
| Small (Nordic) | $439K | $290K | $149K | Reasonable |

### Root causes (5 issues)

**1. Staff salary: $208,333 per event — ABSURD**
- The code divides annual staff salary by number of events
- Alpha has 411 events → $208K per event (10 staff × $2.5M total annual / 12 months... but divided wrong)
- Should be: ~$5K-$15K per event (staff get paid per show, not annual salary per event)
- Fix: Cap staff_salary at $5K-$20K per event based on promo tier

**2. Ticket price: $80 flat for ALL promos**
- Major promos charge $80-$300 (UFC charges $100-$500)
- Mid promos charge $40-$80
- Small/regional promos charge $20-$50
- Fix: Default ticket_price varies by size_tier (major=120, mid=60, small=35)

**3. Fighter purses: $4K-$65K per fight — too low for major, too high for small**
- Major: UFC minimum is $10K, stars earn $500K+ (current: $4K-$65K)
- Mid: Should be $5K-$30K
- Small: Regional fighters get $500-$2K (current: $4K — too high for small promos)
- Fix: Scale purse multiplier by size_tier (major=3x, mid=1.5x, small=0.5x)

**4. Broadcast revenue: $150K flat for 'streaming' — too high for small**
- Major (PPV): $500K-$5M (PPV buys × $60)
- Mid (streaming): $20K-$100K
- Small (no broadcast): $0
- Fix: Scale broadcast_revenue by broadcast_tier (regional_tv=$50K-$200K, local_stream=$10K-$50K, none=$0)

**5. Venue rental: $8/seat — reasonable but should vary**
- Arena: $8/seat (OK)
- Ballroom: $6/seat (OK)
- Theater: $4/seat (OK)
- Outdoor: $3/seat (OK)
- No change needed

### Target economics (after fix)

| Tier | Revenue/event | Expenses/event | Profit/event | Assessment |
|---|---|---|---|---|
| Major | $1.5M-$3M | $1M-$2M | $500K-$1M | Profitable with good cards, marginal with bad |
| Mid | $300K-$600K | $200K-$400K | $100K-$200K | Sustainable |
| Small | $50K-$150K | $40K-$120K | $10K-$30K | Break even, occasional loss |

### Implementation

In `src/finance.py`:

1. **Staff salary:** Find the staff_salary calculation. Replace the per-event division with a flat rate:
   - Major: $15K per event
   - Mid: $8K per event
   - Small: $3K per event

2. **Ticket price:** In `_process_event_finance`, set default ticket_price based on size_tier:
   - Major: 120 (was 80)
   - Mid: 60 (was 80)
   - Small: 35 (was 80)
   - Player can still override via the finance screen lever

3. **Fighter purse:** In the purse calculation, multiply by size_tier factor:
   - Major: 3x (was 1x)
   - Mid: 1.5x (was 1x)
   - Small: 0.5x (was 1x)

4. **Broadcast revenue:** In `_compute_broadcast_revenue`, scale by broadcast_tier:
   - `regional_tv`: $100K-$300K (was $150K flat)
   - `local_stream`: $10K-$50K (was $150K flat)
   - `none`: $0 (was $150K flat)

5. **After code changes:** Re-run `scripts/backfill_finance_transactions.py` to recompute all historical finances with the new model. Then reset cash to realistic values.

---

## Issue 4: Memory resurfacing verification

### Plan
Write `scripts/test_player_path_memory.py`:
1. Set up player promotion (promo 1)
2. Find two fighters who have fought before (from fight_history where both fighter_id and opponent_id are active fighters)
3. Book a fight between them via `app_web.Api.book_fight()`
4. Verify `generate_fight_preview_memory_news` fires (check for memory_resurfacing news item)
5. Verify the news item references their history (headline contains "History looms" or "Past meets present")
6. Advance to the fight date, resolve the fight
7. Verify post-fight memory links are updated (previous_fights, etc.)

If it doesn't fire, trace why:
- Is `surface_memories` returning empty? (check what links exist between the fighters)
- Is the daily cap suppressing it? (check SIGNIFICANT cap = 5/day)
- Is the function being called at all? (check matchmaking.schedule_next_event + app_web.book_fight)

---

## Implementation Order

1. **Delete HoF inductees** (1 minute — DELETE FROM hall_of_fame)
2. **Reset P6 cash** (1 minute — UPDATE promotions SET current_cash=5000000 WHERE promotion_id=6)
3. **Tune finance model** (2-3 hours — modify 4 calculations in src/finance.py)
4. **Re-backfill finances** (run backfill script with new model)
5. **Reset cash again** (after re-backfill, reset to realistic values)
6. **Write + run memory test** (1 hour)
7. **Run 30-day soak** — verify economics work
8. **Run 365-day soak** — verify long-term sustainability
9. **Commit + push**

---

## What we're NOT doing
- ❌ NO new tables/schema
- ❌ NO new screens
- ❌ NO architecture changes
- ❌ NO fight engine changes (KO/sub rates are close enough per ChatGPT)
