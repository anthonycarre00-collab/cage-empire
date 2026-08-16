> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Fix Plan: Finances + Min Fights + Advance Day + Growth

> **Status:** PLANNING ONLY. No code until plan is clear.
> **Source:** User feedback + code audit.

---

## 0. Issues (every sentence from user's message)

1. **Financial predictions are way off** — projections don't interwork properly with actual results
2. **Too easy to make money** — show QUALITY/RATINGS must play a major part
3. **Projections can't know show rating until after it happens** — pre-event preview should be a ROUGH estimate, not a precise prediction. Post-event should show the REAL numbers.
4. **No minimum card size enforced** — player can schedule 1-fight events (confirm_card HAS the check but it may not be wired to the UI properly, OR the player can bypass confirm_card)
5. **Promotions can't grow or grow/decay too quick** — reputation deltas may be too small (great show = +2) or too large (bankruptcy = -10)
6. **Advance Day needs more options** — "Sim a Full Week" + "Skip to Next Show" (runs daily ticks in background)
7. **During sim processing, snapshot a random fighter profile every minute** — visual feedback while processing

---

## 1. Financial Model Fix

### Current problem
- `card_draw = 1.2` is STILL hardcoded in `get_event_preview` (the preview doesn't use the real card_draw formula even though we built `_project_card_draw`)
- The preview shows $8M net profit for a single moderate event — way too much
- Show quality/rating is NOT factored into the preview (can't be — it hasn't happened yet)
- Fighter purses are $824k but revenue is $9.2M — the ratio is wrong (real MMA: purses are 30-50% of revenue)

### Fix approach

**A. Pre-event preview = ROUGH ESTIMATE only (not precise)**
- The preview should say "Projected revenue: roughly $X-Y range" not "Net profit: $8,085,751"
- Use voice phrases: "This card should bring in decent money" / "You're betting big on this one" / "Tight margins — one injury could sink this"
- Show a RANGE (min-max), not a single number. The range accounts for show quality variance.
- The range should be wide: "Revenue could be anywhere from $2M to $8M depending on how the fights go"

**B. Post-event = REAL numbers**
- After the event resolves, show the ACTUAL revenue/expenses/net
- This is where show rating matters: a great show (finishes, upsets, excitement) boosts revenue retroactively (PPV buys were higher because fans talked about it, merch sold more, etc.)
- A terrible show (boring decisions, injuries, no-name card) earns LESS than projected

**C. Fighter purses must be 30-50% of revenue**
- Currently purses = $824k on $9.2M revenue = 9% (way too low)
- Fix: increase purse formula so purses are ~30-40% of projected revenue
- This means: higher ticket prices → higher revenue → higher purses (proportional)
- Star fighters (high marketability) should command higher purses

**D. Show quality drives post-event revenue adjustment**
- After event resolves, compute show_rating (already exists)
- Apply a post-event revenue multiplier based on show rating:
  - Rating ≥ 80: +30% bonus to PPV buys + merch (retroactive — "word of mouth drove extra buys")
  - Rating 60-79: +10% bonus
  - Rating 40-59: no adjustment
  - Rating < 40: -20% penalty (fans demand refunds, bad word of mouth)
- Write the adjusted numbers as the ACTUAL finance_transactions
- The news item should reflect this: "Blockbuster card! Extra PPV buys driven by word of mouth." or "Lackluster show — refunds demanded."

### Implementation

**`src/finance.py` — `_process_event_finance`:**
1. Compute base revenue (gate, broadcast, sponsorship, merch, concessions) — same as now
2. Compute expenses (purses, staff, venue, marketing, insurance) — same as now
3. After fights resolve + show_rating computed, apply show_quality_multiplier to PPV + merch:
   ```python
   show_rating = _get_show_rating(conn, event_id)
   if show_rating and show_rating >= 80:
       quality_mult = 1.30  # +30% bonus
   elif show_rating and show_rating >= 60:
       quality_mult = 1.10
   elif show_rating and show_rating < 40:
       quality_mult = 0.80  # -20% penalty
   else:
       quality_mult = 1.0
   # Apply to PPV + merch (retroactive adjustment)
   ppv_revenue = int(ppv_revenue * quality_mult)
   merch_revenue = int(merch_revenue * quality_mult)
   ```
4. Increase fighter purses: change `_N_EVENTS_PER_YEAR` from 4 to 3 (fighters paid even more per event) OR add a `star_multiplier` for main event fighters

**`src/app_web.py` — `get_event_preview`:**
1. Replace the precise single-number projection with a RANGE:
   ```python
   base_revenue = compute_revenue(...)
   # Show quality is unknown pre-event — assume 50 (average) ± 30 (variance)
   low_quality = 20  # worst case
   high_quality = 80  # best case
   low_revenue = base_revenue * 0.7  # -30% if show is terrible
   high_revenue = base_revenue * 1.3  # +30% if show is great
   return {
       "revenue_range_low": low_revenue,
       "revenue_range_high": high_revenue,
       "revenue_range_phrase": "roughly $2M to $8M depending on how the fights go",
       "expenses": expenses,  # expenses are known precisely
       "net_range_low": low_revenue - expenses,
       "net_range_high": high_revenue - expenses,
       "voice_phrase": "This card should bring in decent money — but the fights need to deliver.",
   }
   ```
2. Remove the precise single-number projection (was misleading)
3. Show the range with a voice phrase

**`src/web/js/event_builder.js` + `matchmaking.js`:**
- Update the preview panel to show the RANGE, not a single number
- Voice phrase: "Projected: roughly $2M-$8M revenue depending on show quality"
- After the event resolves, the Archive shows the ACTUAL numbers

---

## 2. Minimum Card Size Enforcement

### Current state
`confirm_card` in `app_web.py` HAS the min fights check (major=5, mid=4, small=3). But:
- The player might be bypassing `confirm_card` (creating events directly without confirming)
- OR the matchmaking UI doesn't enforce it before showing the CONFIRM button

### Fix
1. In `matchmaking.js`, check the min fights before enabling the CONFIRM CARD button:
   ```js
   var minFights = state.promo.size_tier === 'major' ? 5 : 
                   state.promo.size_tier === 'mid' ? 4 : 3;
   var canConfirm = state.stagedFights.length >= minFights;
   ```
2. Show the requirement: "Major promotion needs at least 5 fights (you have 3)"
3. In `confirm_card`, the backend check already exists — verify it fires correctly

---

## 3. Advance Day Options

### Current state
Only a single "Advance Day" button that advances 1 day at a time.

### Fix
Add 3 buttons to the top bar:
1. **▶ Advance Day** (existing — advances 1 day)
2. **⏩ Sim Week** (advances 7 days — runs 7 daily ticks in background)
3. **⏭ Skip to Show** (advances to the next scheduled event date — runs N daily ticks)

**Behavior:**
- When clicked, disable all 3 buttons + show a processing overlay: "Processing sim..."
- Run the ticks in a loop (Python side — `advance_day` called N times)
- Every ~60 ticks (or every sim-week), snapshot a random fighter profile + display it in the overlay
- When done, re-enable buttons + refresh the screen

**`src/app_web.py`:**
- Add `advance_days(n)` method — runs `run_tick` N times in a single API call
- Add `advance_to_next_event()` method — finds the next scheduled event date, computes days to advance, runs that many ticks

**`src/web/js/app.js`:**
- Add the 3 buttons to the top bar
- On click: disable buttons → show overlay → call bridge → on complete: hide overlay + refresh

**Processing overlay:**
- Full-screen semi-transparent overlay
- "Processing simulation..." text
- A rotating fighter profile card (random fighter, updated every few seconds)
- Progress indicator: "Day 3 of 7..." or "Advancing to March 15..."

---

## 4. Promotion Growth/Decay

### Current state
- Great show (rating ≥ 75): rep +2
- Dud show (rating < 40): rep -1
- Title change: rep +1
- Drug scandal: rep -3
- Bankruptcy (per event): rep -2
- Bankruptcy failure: rep -10

### Problem
- +2 per great show is too slow — a promo running 1 event/month with all great shows gains +24 rep/year → from 50 to 74 in one year (reasonable but slow)
- -1 per dud show is too lenient — a promo running bad shows loses only -12 rep/year
- The user is worried promos can't grow OR grow/decay too quick

### Fix
- Great show: rep +3 (was +2)
- Good show (rating 60-74): rep +1 (NEW tier)
- Dud show: rep -2 (was -1)
- Terrible show (rating < 25): rep -4 (NEW tier)
- This makes growth possible (3/month = +36/year max) but decay is real (-4/month = -48/year max)
- A well-run promo can grow from 50 to 80+ in 1-2 years
- A poorly-run promo can drop from 80 to 40 in 1 year

---

## 5. Implementation plan

### Phase F1: Financial model fix (finances + preview + show quality)
- `src/finance.py` — show quality multiplier on post-event PPV + merch, increase purses
- `src/app_web.py` — get_event_preview returns RANGE not single number, voice phrase
- `src/web/js/event_builder.js` + `matchmaking.js` — show range + voice phrase in preview panel

### Phase F2: Min card size + advance day + growth
- `src/web/js/matchmaking.js` — enforce min fights before CONFIRM button
- `src/app_web.py` — add `advance_days(n)` + `advance_to_next_event()` API methods
- `src/web/js/app.js` — add Sim Week + Skip to Show buttons + processing overlay
- `src/reputation.py` — adjust rep deltas (great +3, good +1, dud -2, terrible -4)

---

## 6. Acceptance criteria

- [ ] Pre-event preview shows a RANGE ("roughly $2M-$8M") not a precise number
- [ ] Post-event actuals reflect show quality (great show = +30% PPV, bad show = -20%)
- [ ] Fighter purses are 30-40% of revenue (not 9%)
- [ ] It's NOT too easy to make money — a bad card with no stars can lose money
- [ ] Min card size enforced in the matchmaking UI (CONFIRM button disabled if too few fights)
- [ ] "Sim Week" button advances 7 days with processing overlay
- [ ] "Skip to Show" button advances to next event date
- [ ] Processing overlay shows random fighter profiles during sim
- [ ] Promotion reputation grows with great shows (+3) and decays with bad shows (-2 to -4)
- [ ] All tests pass
