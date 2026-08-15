> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Comprehensive Fix Plan (Pre-Screens Polish)

> **Status:** PLANNING ONLY — no code changes yet. Supervisor will delegate.
> **Source:** User feedback doc "before any more screens.txt" — every sentence analyzed.

---

## 0. Issue inventory (every sentence from the user's doc)

| # | Screen | Issue | Root cause |
|---|---|---|---|
| 1 | Empire (Dashboard) | Bidding war alert shows too many — show only 3 random, reduce frame size | No limit on alert display count |
| 2 | Empire (Dashboard) | Echoes: "who you released" but fighter still contracted — rephrase to "since his release" | Echoes engine assumes cut = released, but contract may still be active |
| 3 | Title bar | Shows only "March 2027" — needs the day too | `app.js:241` formats as `month_name + ' ' + year` — missing `current_day` |
| 4 | The Wire | Balance check — too many similar stories or too many on one fighter | Need news diversity audit + dedup + pruning check |
| 5 | Stack a Card | Layout order wrong: should be Name event → Choose date → Pick venue → Set levers | Current order: Build header → Pick venue → Pick date → Set levers |
| 6 | Stack a Card | Venue cards too big, need country/region filter | No country/region filter on venue grid |
| 7 | Stack a Card | "Set Your Levers" needs realistic rename | "Set Your Levers" is gamey — needs voice-compliant name |
| 8 | Stack a Card | No downside to maxing all levers — player makes money regardless | No price elasticity penalty, no fill rate drop for high ticket prices |
| 9 | Stack a Card | Fighter salaries/bonuses too small | _N_EVENTS_PER_YEAR=6 makes per-event purse too low; no FOTN/KO/Sub bonuses |
| 10 | Stack a Card | Need fight of the night + best KO + best submission bonuses per card | No bonus system exists |
| 11 | Matchmaking | No scroll bar — content below screen | `overflow: hidden` on container, inner zones may not scroll |
| 12 | Matchmaking | No minimum fights — can schedule single fight event | No min-fights check based on promo size |
| 13 | Matchmaking | Event rating must weight top 4-5 fights + main/co-main | show_rating.py needs to weight main/co-main more heavily |
| 14 | Fight Night | "Unable to resolve fight" error | resolve_next_fight may fail on player's events — need to debug |
| 15 | Fight Night | Should NOT have direct access to resolve fights — must link to calendar | Fight Night should be "Watch the Show" from Dashboard/Calendar, only on event day |
| 16 | Fight Night | Fights should play in reverse order (prelims first, main event last) | Currently plays in fight_id order, not card_slot order |
| 17 | Fight Resolution | Commentary too small, play/pause buttons too small | CSS sizing issue |
| 18 | Fight Resolution | "Advance Day" header should be disabled during live commentary | No state lock during fight playback |
| 19 | Fight Resolution | "No of beats" shown — hide it | UI shows raw beat count |
| 20 | Fight Resolution | Commentary too samey, no named pundit interjections, no ring announcer | Commentary templates too few, no pundit/announcer system |
| 21 | Fight Resolution | Key highlights all say same thing | Highlight template variety issue |
| 22 | The Archive | Too many events with 0-1 fights — unrealistic | 171 events with 0 fights, 1778 with 1 fight — seed data issue |
| 23 | Rankings | Multiple fighters holding same ranking in same promotion | Duplicate ELO ratings → same rank |
| 24 | Rankings | Champions have bad attributes/profiles | Champions seeded with low attributes (power=36, iq=38 etc.) — they shouldn't be champions |
| 25 | Rankings | Need "contracted to" column + player's promo rankings | No promo column in rankings display |
| 26 | General | User worried we created new systems rather than wiring planned ones | Need audit — verify all systems are wired to plans |
| 27 | General | Run 3-month sim + full world audit | After all fixes, sim forward 90 days + audit everything |

---

## 1. Fix plan (grouped by screen, prioritized)

### Group A: Dashboard + Title Bar (quick fixes)

**A1. Bidding war alert — show 3 random, reduce frame size**
- In `dashboard.js`, slice the alerts to 3 + shuffle
- CSS: reduce padding + border on the bidding war section

**A2. Echoes — rephrase "who you released" to "since his release"**
- In `echoes_engine.py`, change template from `"{name}, who you released in {month}, just..."` to `"Since {his/her} release in {month}, {name} has..."`
- Use gender-aware pronouns (his/her based on fighter.gender)

**A3. Title bar — add day**
- In `app.js:241`, change from `month_name + ' ' + year` to `month_name + ' ' + current_day + ', ' + year`

### Group B: Stack a Card redesign

**B1. Layout reorder: Name event → Choose date → Pick venue → Set levers**
- Reorder sections in `event_builder.js`
- Add event name input (default: "[Promo Name] [Number]" auto-incrementing)

**B2. Venue cards smaller + country/region filter**
- Reduce venue card size in CSS
- Add country dropdown + region dropdown (join venues → cities → nations)
- Check if reputation gains by nation/region are wired (if not, flag for future)

**B3. Rename "Set Your Levers"**
- Rename to "PRICE YOUR SHOW" or "THE BUSINESS END" (Cage Empire voice)

**B4. Financial balance — add downside to maxing levers**
- **Price elasticity**: higher ticket price → lower fill rate (currently fill_rate barely drops)
  - Current: `fill_rate = clamp(0.30 + (market_heat/100)*0.50 + (rep/100)*0.10 + marketing_boost - price_elasticity_penalty, 0.10, 0.99)`
  - Fix: make `price_elasticity_penalty` much stronger — `(ticket_price - 80) / 80 * 0.5` (ticket at $300 → -137% fill → floored at 0.10)
- **PPV price elasticity**: higher PPV price → fewer buys
  - Add: `ppv_price_penalty = (ppv_price - 60) / 60 * 0.3` applied to ppv_buys
- **Marketing diminishing returns**: already has caps but make them tighter

**B5. Fighter salaries + bonuses increase**
- Increase `_N_EVENTS_PER_YEAR` from 6 to 4 (fighters paid even more per event)
- OR: increase base purse formula (salary × 2 per event)
- Add Fight of the Night bonus ($50k split between both fighters)
- Add Best KO bonus ($25k to the fighter)
- Add Best Submission bonus ($25k to the fighter)
- These are computed post-event (after all fights resolve) + written as finance_transactions

### Group C: Matchmaking fixes

**C1. Add scroll bar**
- Fix CSS: `overflow: hidden` → `overflow-y: auto` on the main container

**C2. Minimum fights per card based on promo size**
- Major promo: min 5 fights
- Mid promo: min 4 fights
- Small promo: min 3 fights
- Block "CONFIRM CARD" if fewer than minimum

**C3. Show rating weights main/co-main more heavily**
- In `show_rating.py`, weight main_event × 2.0, co_main × 1.5, featured × 1.0, prelim × 0.5
- Make rating less generous overall (lower the overall_rating by 10-15%)
- Wire show rating into news ("Blockbuster card!" / "Terrible show" etc.)

### Group D: Fight Night redesign

**D1. Debug "unable to resolve fight"**
- The `resolve_next_fight` API may fail because the player's events have no fights (create_event writes 0 fights, matchmaking stages in JS but confirm_card may not be wired correctly)
- Debug: verify `confirm_card` actually writes fights to DB

**D2. Remove direct resolve access — link to calendar**
- Remove the "Fight Night" nav item's direct resolve capability
- Fight Night becomes "Watch the Show" — only accessible from:
  - Dashboard "Your Next Card" → "Watch the Show" button (only enabled on event day)
  - Calendar → click event on today's date → "Watch the Show"
- Fights can ONLY be resolved on the event's scheduled date (advance day to event day first)

**D3. Reverse fight order (prelims first, main event last)**
- Sort fights by card_slot: main_event LAST, prelims FIRST
- Player can skip any fight → go directly to result

**D4. Commentary improvements**
- Make commentary text larger (18px → 22px)
- Make play/pause/skip buttons larger (larger touch targets)
- Hide "no of beats" counter
- Disable "Advance Day" button during live commentary
- Add more commentary template variety (8+ per action_type × outcome)
- Add named pundit interjections (if promo has commentators on staff)
- Add ring announcer intro ("In the red corner, weighing in at...")
- Add crowd reactions ("The crowd erupts!" / "Silence falls over the arena")

**D5. Key highlights variety**
- Expand highlight template system — each highlight type needs 8+ variants
- Use fighter names + specific actions in templates

### Group E: Archive cleanup

**E1. Remove/cleanup events with 0-1 fights**
- Delete the 171 events with 0 fights (they're seed artifacts, not real events)
- For the 1778 events with 1 fight: these are legacy seed data — keep them but flag as "exhibition" or merge into multi-fight cards
- Future: ensure rival AI never creates events with < 3 fights

### Group F: Rankings + Champions fix

**F1. Fix duplicate rankings**
- The `rankings` table has no `rank` column — rank is derived from `rating` (ELO)
- Multiple fighters with the same ELO rating get the same rank
- Fix: add a tiebreaker (fighter_id ASC) so no two fighters share a rank

**F2. Fix champions with bad attributes**
- Champions were seeded randomly — some have power=36, iq=38 (below average)
- Fix: re-seed champions — pick the highest-rated fighter per WC per promo as champion
- OR: boost champion attributes to be above-average (they're champions for a reason)

**F3. Rankings — add "contracted to" column + player's promo**
- In the rankings table, add a column showing which promo the fighter is contracted to
- Add a toggle: "My Promotion" vs "All Promotions"

### Group G: Wire balance

**G1. News diversity audit**
- Check for duplicate headlines (same headline text appearing too many times)
- Check for fighter over-representation (one fighter getting too many news items)
- Verify pruning service is running (old news culled, important items retained)

---

## 2. Implementation order

### Phase P1: Quick fixes (Dashboard + Title bar + Matchmaking scroll) — 1 subagent
- A1: Bidding war alert (3 random, smaller frame)
- A2: Echoes rephrase ("since his release")
- A3: Title bar day
- C1: Matchmaking scroll

### Phase P2: Stack a Card redesign + financial balance — 1 subagent
- B1: Layout reorder (name → date → venue → levers)
- B2: Venue cards smaller + country/region filter
- B3: Rename "Set Your Levers"
- B4: Financial balance (price elasticity, PPV elasticity, no downside to maxing)
- B5: Fighter salaries + FOTN/KO/Sub bonuses

### Phase P3: Fight Night redesign — 1 subagent
- D1: Debug resolve error
- D2: Remove direct resolve → "Watch the Show" from Dashboard/Calendar on event day
- D3: Reverse fight order (prelims first, main last)
- D4: Commentary improvements (larger text, hide beats, disable advance day, more variety, pundits, announcer, crowd)
- D5: Key highlights variety

### Phase P4: Rankings + Champions + Archive — 1 subagent
- E1: Archive cleanup (remove 0-fight events)
- F1: Fix duplicate rankings (tiebreaker)
- F2: Fix champions (re-seed highest-rated as champions)
- F3: Rankings "contracted to" column + promo toggle
- C3: Show rating weights + news wiring

### Phase P5: Wire balance + news audit — 1 subagent
- G1: News diversity audit + pruning check
- C3 (continued): Show rating → news ("Blockbuster card" / "Terrible show")

### Phase P6: 3-month sim + full world audit — supervisor
- Run sim forward 90 days
- Full audit: champions, promo growth/decay, fighter attribute growth/decay, staff movement, finances, rivalries, personalities, news variety, prospects, retirements, cash, events, performance

---

## 3. Acceptance criteria

- [ ] Bidding war alert shows max 3, smaller frame
- [ ] Echoes say "since his/her release" not "who you released"
- [ ] Title bar shows "March 15, 2027" not just "March 2027"
- [ ] Stack a Card order: Name → Date → Venue → Levers
- [ ] Venue cards smaller + country/region filter
- [ ] "Set Your Levers" renamed to voice-compliant phrase
- [ ] Maxing all levers has a real downside (fill rate drops, PPV buys drop)
- [ ] Fighter salaries more realistic
- [ ] Fight of the Night + Best KO + Best Sub bonuses per card
- [ ] Matchmaking screen has scroll
- [ ] Minimum fights per card (major=5, mid=4, small=3)
- [ ] Show rating weights main/co-main more heavily
- [ ] Fight Night: "unable to resolve" debugged
- [ ] Fight Night: no direct resolve — "Watch the Show" from Dashboard/Calendar on event day
- [ ] Fight Night: fights play in reverse order (prelims first, main last)
- [ ] Commentary larger text + larger buttons
- [ ] "No of beats" hidden
- [ ] "Advance Day" disabled during live commentary
- [ ] Commentary has more variety + named pundits + ring announcer + crowd reactions
- [ ] Key highlights have variety
- [ ] Archive: 0-fight events removed
- [ ] Rankings: no duplicate ranks
- [ ] Champions: have above-average attributes
- [ ] Rankings: "contracted to" column + promo toggle
- [ ] News: no excessive duplicates or over-representation
- [ ] 3-month sim + full world audit complete
