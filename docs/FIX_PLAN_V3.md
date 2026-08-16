# CAGE EMPIRE — 5 Remaining Issues Fix Plan

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Goal:** Fix the 5 remaining issues from the post-reseed 1-year sim analysis

---

## Issue 1: 9/10 promotions in REBUILDING — event economics broken

### Root cause (CONFIRMED)

The finance system is NOT writing event-related transactions (ticket_sales, fighter_purse, venue_rental, broadcast_revenue). The pre-sim DB has 1,884 completed events but ZERO finance transactions for them (only 20 sponsorship rows from the reseed).

**Why:**
1. **Pre-existing events (1,884):** All status='completed' before the sim. `EVENT_COMPLETED` only fires on the TRANSITION from scheduled→completed. Since these were already completed, the finance subscriber never fires for them.
2. **16 re-set events:** These DID transition to completed during the sim, but `_process_event_finance` produced 0 transactions — likely crashing silently (EventBus catches exceptions but may not log them to tick_health).
3. **~99 new rival AI events:** These should have triggered finance, but we can't verify because the post-sim DB was restored.

**The consequence:** Promotions have NO event revenue (ticket_sales) and NO event expenses (fighter_purse, venue_rental). Their cash only changes via the `reputation.py` financial state machine which directly `UPDATE promotions SET current_cash` without recording transactions. This means:
- Cash goes negative (expenses deducted directly by reputation system)
- No ticket revenue to offset expenses
- Every promo ends up in REBUILDING

### Fix

**Step 1: Backfill finances for pre-existing events**
Write/run `scripts/backfill_finance_transactions.py`:
- For each of the 1,884 completed events that have no `ticket_sales` transaction:
  - Call `_process_event_finance` directly (bypass the EventBus)
  - This computes ticket_sales + broadcast_revenue + fighter_purse + venue_rental
  - Records 4+ finance_transactions rows per event
  - Updates `promotions.current_cash` via `_record_transaction`
- This is a one-time backfill — gives every promo a realistic cash balance based on their event history

**Step 2: Debug the 16 transition events**
- Add verbose error logging to `_process_event_finance` (wrap in try/except with print to stderr)
- Run a controlled test: advance 1 tick with a scheduled event due to complete
- Check stderr for any crash
- Fix whatever is causing the silent failure

**Step 3: Verify finance fires for new rival AI events**
- Run a 30-day sim
- Check that new events (scheduled by rival AI) have finance_transactions rows
- Verify promotions gain ticket revenue + lose cash on purses/venue

**Step 4: Tune the financial state machine**
- With real event finances flowing, the REBUILDING threshold should be less aggressive
- If promos are still going to REBUILDING, raise the threshold further (4+ months of negative cash)
- Ensure the cash injection (already added) fires correctly

---

## Issue 2: Memory resurfacing news = 0 in sim

### Root cause

`generate_fight_preview_memory_news` is called from:
1. `services/matchmaking.schedule_next_event` — when rival AI schedules events
2. `app_web.book_fight` — when the player books a fight

The soak test doesn't simulate player bookings. The rival AI's `schedule_next_event` DOES call it, but the fight-preview news only fires when `surface_memories()` finds history between the two booked fighters. With 4,000 fighters and ~80K fight_history rows, most random matchups DON'T have history (the fighters have never fought before).

The 7 memory_resurfacing news items I saw in the earlier interim sim (day 125) were from the rival AI booking rematches. But in the full 365-day sim, 0 fired — possibly because the pruning cleaned up old fight_history, or because the matchups didn't repeat.

### Fix

**No code change needed.** The system is correctly wired — it just needs the right conditions to fire:
1. Two fighters who have fought before get booked for a rematch → `surface_memories` finds `previous_fights` link → news item written
2. This is a RARE event by design (most fights are first-time matchups)
3. In actual gameplay (player books fights), it will fire more often because the player chooses rematches

**Verification:** Run a controlled test:
- Find two fighters who have fought before (from fight_history)
- Book a fight between them via `app_web.book_fight`
- Verify `generate_fight_preview_memory_news` writes a news item
- This confirms the system works — it just needs the right conditions

---

## Issue 3: KO rate 23% (target 30%)

### Root cause

The fight engine tuning lowered KO thresholds and increased finish probability, but the KO rate is still slightly below target. The remaining gap is likely because:
1. The simplified AI resolver's KO threshold (30 + (chin+dur)*0.3 ≈ 60) is still too high for lower-power fighters (avg power 48 → ~19 dmg/round → 57 total after 3 rounds, just below threshold)
2. The full engine's KO finish probability (0.15 + KI*0.002 ≈ 0.25) means only 25% of threshold crossings result in a KO

### Fix

**Option A: Lower the simplified resolver's KO threshold further**
- Change from `30 + (chin+dur)*0.3` → `20 + (chin+dur)*0.25`
- New typical threshold: 20 + 25 = 45 (reachable in 2-3 rounds)
- Expected KO rate: ~28-32%

**Option B: Increase per-round damage in the simplified resolver**
- Change base damage from 25 → 28
- This makes thresholds easier to cross
- Expected KO rate: ~27-30%

**Option C: Increase KO finish probability**
- Change `_KO_FINISH_PROB_BASE` from 0.15 → 0.20
- More threshold crossings result in KOs
- Expected KO rate: ~28-32%

**Recommendation:** Option A (lower threshold) — it's the most targeted fix. The threshold is the gate; once crossed, the probability is reasonable.

**Note:** The user said they will rebalance fighter attributes separately. Claude's pyramid distribution (most fighters 46-53, few elite 80+) means most fights are between similarly-skilled fighters → fewer mismatches → fewer KOs. If the user increases the spread (more elite fighters, more fringe fighters), KO rate will naturally increase. The engine tuning should target the THRESHOLD, not the probability.

---

## Issue 4: Sub rate 14% (target 20%)

### Root cause

Same as KO — the submission probability in the simplified resolver is too low. Current: `0.03 per round` (not divided by rounds_div). Over 3 rounds, cumulative sub probability = 1 - (0.97)^3 = 8.7%. Over 5 rounds = 14%. This is close to the observed 14% but below the 20% target.

### Fix

**Increase simplified resolver sub probability from 0.03 → 0.045 per round**
- Over 3 rounds: 1 - (0.955)^3 = 12.8%
- Over 5 rounds: 1 - (0.955)^5 = 20.5%
- Combined (mix of 3 and 5 round fights): ~15-18%
- With the full engine also producing subs, combined rate should hit ~20%

**Also:** Increase the full engine's submission attempt probability slightly. The current formula gives a low attempt rate per beat. Increasing it by 20% would produce more submission attempts → more submission finishes.

---

## Issue 5: Per-event "Fight of the Night" bonuses are ROUTINE

### Root cause

The post-fight bonus news (Fight of the Night, Best KO, Best Submission) fires after every event. With ~115 events/year, that's ~76 bonus news items. These are tagged ROUTINE because they're per-event operational news.

### Fix

**Tag bonus news based on event importance:**
- For title fights / main events: SIGNIFICANT (these are meaningful awards)
- For regular events: ROUTINE (keep as-is — these are operational)
- For end-of-year awards: already LEGENDARY (working correctly)

**Implementation:** In the news code that writes bonus news, check if any fight on the card was a title fight. If yes, tag the bonus news as SIGNIFICANT. If no, keep as ROUTINE.

**Also:** Consider suppressing bonus news for rival AI events (the player doesn't need to know about every regional promo's Fight of the Night). Only write bonus news for:
- The player's promotion's events
- Rival promotion MAIN EVENTS only (not full cards)

This would reduce bonus news from ~76/year to ~20-30/year (more meaningful).

---

## Performance check — no exponential growth

### Tables that grow during sim

| Table | Pre-sim | Post-sim (1yr) | Growth rate | Pruned? | 10yr estimate |
|---|---|---|---|---|---|
| fight_beats | 0 | ~500 (daily pruned) | ~500 (stable) | ✅ Daily | ~500 |
| commentary_segments | 0 | ~13 (365d pruned) | ~13 (stable) | ✅ 365d | ~13 |
| news_items | 0 | 1,904 | ~1,900/yr | ✅ 180d | ~950 (pruned) |
| fighter_memory_links | 0 | 4,429 | ~4,400/yr | ❌ Not pruned | ~44,000 |
| rival_ai_memory | 0 | 676 | ~676/yr | ✅ Weekly decay | ~3,000 (decayed) |
| fight_history | 79,823 | ~80,500 | ~700/yr | ❌ NEVER | ~87,000 |
| simulation_tick_health | 0 | 365 | ~365/yr | ✅ 365d | ~365 |
| training_camps | 138 | ~200 | ~60/yr | ✅ 60d | ~200 |
| injuries | 0 | 89 | ~89/yr | ✅ 180d | ~89 |
| rivalries | 343 | 521 | ~178/yr | ❌ Not pruned | ~2,100 |

### Assessment

**No exponential growth.** All tables grow linearly. The pruned tables stay stable. The un-pruned tables (fighter_memory_links, fight_history, rivalries) grow at manageable rates:
- `fighter_memory_links`: 4,400/year → 44,000 at 10 years. This is fine — the UNIQUE constraint prevents duplicates, and all queries use the covering index.
- `fight_history`: 700/year → 87,000 at 10 years. This is the permanent career record — never pruned. 87K rows is manageable for SQLite.
- `rivalries`: 178/year → 2,100 at 10 years. The decay system keeps active rivalries bounded (~150-200 active at any time).

**No performance concern.** The 365-day sim completed with 337ms avg tick, 1622ms max. No super-linear growth.

---

## Implementation Order

1. **Backfill finances** for 1,884 pre-existing events (Step 1 of Issue 1)
2. **Debug finance subscriber** — find why it crashes silently on the 16 transition events
3. **Tune KO threshold** (Issue 3) — lower simplified resolver threshold
4. **Tune sub probability** (Issue 4) — increase from 0.03 → 0.045
5. **Tag bonus news** by event importance (Issue 5)
6. **Verify memory resurfacing** with controlled test (Issue 2)
7. **Run 365-day sim** with all fixes
8. **Re-analyze** — verify all 5 issues resolved
