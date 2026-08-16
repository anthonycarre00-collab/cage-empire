> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# P5+P6 Plan: Polish, Balance, Bug Fixes, WMMA5 Features

> **Status:** ACTIVE — final polish phase before review against COMPREHENSIVE_REVIEW.md
> **Source:** `docs/COMPREHENSIVE_REVIEW.md` P5 + P6 + known bugs

---

## 0. Current state

- **20 sidebar screens wired** ✅ (zero placeholders)
- **Fight result types:** Actually reasonable now — UD 38.9%, KO/TKO 30.1%, Sub 14.7%, SD 8.4%, Doctor 3.4%, Draw 2.9%, DQ 1.7%. The earlier imbalance was from the future-dated data that was cleaned up. **BUG #5 is already fixed.**
- **Finance:** Still broken — 25 finance_transactions for 1,715 completed events. The sim clock was reset but no new events have resolved since. Need to verify finance fires when events resolve.
- **BUG #2:** Promo 7 stuck in rebuild (is_rebuilding=1, rebuilding_until_date=2027-02-08 but sim date is 2026-08-13 — future date artifact).
- **BUG #6:** 1,773 tapping_up_rumor news items — spam.
- **Rival AI card thickness:** avg 1.0-1.1 fights/event — way too thin (should be 5-8). Root cause: the rival AI events were created with 1 fight each (seed data), and new events scheduled by the rival AI may not be building full cards.

---

## 1. Bug fixes (P6)

### BUG #1: Finance not firing (verify + fix if needed)
- The sim clock was reset to 2026-08-13 + future-dated events were deleted. The rival AI should now schedule new events with correct dates. When those events resolve, EVENT_COMPLETED should fire → finance writes rows.
- Need to verify: run a 14-day sim, check if any events complete + finance rows are written.
- If still broken: trace the event resolution chain (rival_ai → resolve_next_fight → _update_event_status_after_resolution → publish EVENT_COMPLETED → finance subscriber fires).

### BUG #2: Promo 7 stuck in rebuild
- `is_rebuilding=1`, `rebuilding_until_date=2027-02-08` (future date artifact).
- Fix: clear `is_rebuilding=0` + `rebuilding_until_date=NULL` for any promo where `rebuilding_until_date > sim_date`.

### BUG #3: Duplicate bankruptcy news
- 9 duplicate "FINANCIAL COLLAPSE" items for Promo 2.
- Fix: add dedup check in the bankruptcy news writer (check if a news item with the same headline + promo_id exists in the last 30 days before writing).

### BUG #4: Social posts future-dated
- Already cleaned up 3,017 in the last fix. Check if any remain.

### BUG #6: tapping_up_rumor spam
- 1,773 items — way too many.
- Fix: throttle the tapping_up_rumor news generation (max 1 per week per promo, or reduce the trigger probability).

### Rival AI card thickness
- avg 1.0-1.1 fights/event — the rival AI's `build_card` function targets 5-13 fights but may not be finding enough eligible fighters (rest period + injuries).
- Fix: verify the rival AI is calling `build_card` with the correct archetype card_size. Check if the 60-day rest period is too restrictive (combined with injuries, may leave too few eligible fighters).
- May need to reduce rest period to 45 days OR ensure the rival AI schedules events far enough apart that fighters have recovered.

---

## 2. WMMA5-style features (P5)

### P5.1: Booking Adviser (on Matchmaking screen)
- Surface opportunities: "Hometown fighter available", "#1 contender fight available", "Debuting fighter available", "Rivalry heat building"
- NOT auto-booking — just surfacing info the player might miss
- Add a "Suggested Matchups" panel to the Matchmaking screen (right column or below the card list)

### P5.2: Save/Load UI affordance
- Add a visible "Save Game" button to the top bar
- Add a "Load Game" option in the pre-game screen
- The API methods exist (`save_game`, `load_game`, `list_saves`) — just need UI

### P5.3: Commentary variety
- Expand per-beat commentary templates from ~7 to 12+ per (action_type, outcome)
- Add more named pundit interjections
- Add more crowd reaction variety

---

## 3. Implementation order

### Phase A: Bug fixes (supervisor direct — surgical)
1. Fix BUG #2 (promo 7 rebuild)
2. Fix BUG #6 (tapping_up_rumor spam)
3. Clean up any remaining future-dated data
4. Verify finance fires on event resolution (run 14-day sim)
5. Fix rival AI card thickness if needed

### Phase B: WMMA5 features (subagent)
1. Booking Adviser panel on Matchmaking
2. Save/Load UI buttons
3. Commentary variety expansion

### Phase C: Final review against COMPREHENSIVE_REVIEW.md
- Verify all acceptance criteria met
- Update the review doc with final status
