> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Matchmaking V2 + Calendar + Balance Sweep

> **Status:** ACTIVE — comprehensive fix plan based on user feedback + research.
> **Supervisor:** main agent.

---

## 0. User complaints (from latest testing)

1. **"Easy mode" analysis** — Compare modal shows definitive "Predicted Winner" + raw numeric matchup score. User wants "might" advice only.
2. **Calculations happen too early** — live projection fires on every fight add/remove. User wants calculations to NOT happen until card is confirmed.
3. **Can't see fighter info** — popularity, rank, titles, rivalries not shown when creating matchups.
4. **Section too small/fiddly** — needs to be BIG and BOLD and EDITABLE with add/remove/reorder.
5. **No calendar** — can't choose WHEN to schedule events. This "fucks up everything else."
6. **Fighter availability broken** — may not check injuries/suspensions/booked/camps correctly.
7. **Last-minute fights** — should be rejected by many fighters depending on personality (need training camps).
8. **Bidding war news too frequent** — needs toning down.
9. **Fighters showing as "left promotion" but still contracted** — contradictory news state.

---

## 1. Matchmaking Screen V2 — BIG and BOLD

### 1.1 Layout redesign

**Current:** 3-column grid (300px / 1fr / 340px), 46px fighter rows, tiny action buttons.

**NEW: Two-row layout:**
- **Top row (60% height) = MATCHUP ZONE** — Red Corner | VS strip | Blue Corner, each ~45% width. This is the decision zone — it should dominate the screen. Large portraits (120×120), 18px names, dense info chips.
- **Bottom row (40% height) = CARD LIST (left 60%) + PROJECTION (right 40%)** — the card list shows booked fights with drag-drop reorder, the projection shows financial estimate (ONLY after card is confirmed, not during build).

### 1.2 Fighter info display (9 fields in corner slot)

Per WMMA5 research, every signal the player needs should be visible IN the corner slot, not buried in modals:

1. **Portrait** — large (120×120px)
2. **Name + nickname** — display font, 18px
3. **Rank chip** — `#7 LW` (gold if champion, silver if top-5)
4. **Title chip** — `🥇 LW Champion` or `—` (visible AT ALL TIMES)
5. **Popularity tier label** — voice phrase from marketability ("Cult Hero" / "Mid Level Regional" / "Household Name")
6. **Momentum flame** — colored arrow ▲/▼ + streak number
7. **Record + WC + age + style** — single dense line: `18-4-0 · LW · 28y · Striker`
8. **Rivalry indicator** — if the two selected fighters have a rivalry (heat ≥ 50), show `⚔ RIVALRY` chip on the VS strip
9. **Recent form** — last 5 fights as W/L/D chips (green/red/grey)

### 1.3 Roster browser — denser info

Each fighter row shows: name, portrait (40×40), WC, record, momentum phrase, rank, title chip, popularity tier, availability status. Configurable columns (FM-style).

### 1.4 "Might" advice (NOT "easy mode")

Per user directive: **NO definitive predictions.** Replace:
- "Predicted Winner: [Name]" → "This one might favor [Name]'s style, but [Opponent] has the tools to make it interesting."
- "Predicted Method: Decision" → "Could go either way — [Red] has the power to end it, [Blue] has the cardio to grind it out."
- "Confidence: High" → REMOVE entirely. No confidence indicators.
- "Upset Risk: Low" → REMOVE entirely.
- Raw numeric matchup score (e.g., "73") → REMOVE the number. Keep only the voice phrase chip ("elite matchup" / "solid fight" / "tune-up" / "mismatch") — and even that is framed as "early read" not definitive.

### 1.5 Card confirmation flow (NEW)

**Current:** Each `book_fight` call INSERTs to DB immediately. Live projection fires on every change.

**NEW:**
1. Player builds the card in the matchmaking screen (add/remove/reorder)
2. Fights are staged in JS memory (NOT written to DB yet)
3. Projection is HIDDEN during build — show "Confirm card to see projected revenue"
4. Player clicks "CONFIRM CARD" button
5. ONLY THEN: fights are written to DB + projection is calculated + event is finalized
6. After confirmation, the card is locked (can still be edited but requires "Re-open card" which removes the event from scheduled)

### 1.6 Add/remove/reorder — BIG and EDITABLE

- Each booked fight is a LARGE card (not a tiny row) — 80px+ tall, with both fighters' names + portraits + matchup chip + remove button (✕, large, 24px)
- Drag-drop reordering with visible drag handle (⠿ icon, 24px)
- Reorder changes card_slot: first fight = Main Event, second = Co-Main, rest = Prelims
- Card slot labels are BIG and BOLD ("MAIN EVENT" / "CO-MAIN" / "PRELIM 1")

---

## 2. Calendar Screen (NEW)

### 2.1 Calendar view

Month-grid calendar showing:
- **Player's scheduled events** (gold border + promo logo)
- **Rival promotions' scheduled events** (red border + rival promo logo)
- **Today's date** highlighted
- **Min-lead-time boundary** — dates < 14 days out are greyed out
- **Click any eligible date** → navigates to Stack a Card with that date pre-filled

### 2.2 Conflict warnings

When the player picks a date:
- If a rival promo has an event within ±2 days → "Rival Fight League is running 'RFL 47' on Sat — counter-programming will split the gate."
- If the player's own promo has an event within 7 days → "You're already running 'CE 12' on Fri — short turnaround."

### 2.3 Date picker on Stack a Card

Add a date input to the event builder. Default to `sim_date + 30 days`. Validate ≥ 14 days out. Pass to `create_event`.

---

## 3. Fighter Availability Fixes

### 3.1 Cross-event booking check

Currently `_get_available_fighters_for_card` only checks if a fighter is booked on THIS event. Need to also check if they're booked on ANY scheduled event within ±7 days of this event's date.

### 3.2 Training camp requirement

Fighters need a training camp before a fight. If the event is < 21 days away and the fighter doesn't have a completed camp in the last 30 days, they're "needs camp" — available but with a warning. If < 14 days, many fighters will REJECT based on personality (see 3.3).

### 3.3 Last-minute rejection (personality-based)

When a fight is booked on short notice (< 14 days):
- Check fighter personality: `risk_taking`, `ambition`, `professionalism`, `patience`
- High professionalism + low risk_taking → REJECTS short-notice fights ("I need a proper camp")
- Low professionalism + high risk_taking → ACCEPTS short-notice fights ("I'll fight anyone, anytime")
- The rejection is a news item: "[Fighter Name] has turned down a short-notice bout against [Opponent] at [Event], citing the need for a proper training camp."

### 3.4 Re-validation at book_fight time

`book_fight` must re-check availability at the moment of booking (not just when the roster was loaded). Prevents race conditions.

---

## 4. Balance Sweep

### 4.1 Bidding war news frequency

Current: too many bidding war alerts. Tone down:
- Rival AI only fires SIGNING_INTENT for fighters with potential ≥ 60 (not every FA)
- Max 1 bidding war alert per 7 sim-days (cooldown)
- The alert only fires if the rival AI's offer is competitive (not a lowball the player will easily beat)

### 4.2 "Left promotion but still contracted" bug

Fighters showing as "left promotion" in news but still contracted. This is likely a news item firing from contract expiry but the contract status not being updated correctly. Need to audit:
- `_check_contract_expiry` — does it correctly set contracts.status = 'expired'?
- Does the news item fire BEFORE or AFTER the contract status update?
- Are there race conditions between retirement_svc and contract_expiry?

---

## 5. Implementation phases

### Phase MM1 — Matchmaking V2 (3-4 days)
- Layout redesign (two-row, BIG corners)
- Fighter info display (9 fields in corner slot)
- Roster browser denser info
- "Might" advice (remove definitive predictions)
- Card confirmation flow (stage in JS, write to DB on confirm)
- Add/remove/reorder with large drag-drop cards

### Phase MM2 — Calendar (2 days)
- Calendar screen (month grid, player + rival events)
- Date picker on Stack a Card
- Conflict warnings
- Nav wiring

### Phase MM3 — Fighter availability (1-2 days)
- Cross-event booking check
- Training camp requirement
- Last-minute rejection (personality-based)
- Re-validation at book_fight time

### Phase MM4 — Balance sweep (1 day)
- Bidding war news frequency tone-down
- "Left promotion but still contracted" bug fix
- General news consistency audit

**Total: ~7-9 dev-days.**

---

## 6. Acceptance criteria

- [ ] Matchmaking screen is BIG and BOLD — corner slots dominate the screen
- [ ] Fighter info (rank, title, popularity, momentum, rivalry, form) visible in corner slot
- [ ] NO definitive predictions — only "might" advice
- [ ] Card confirmation flow — fights staged in JS, written to DB on confirm
- [ ] Projection hidden during build, shown after confirm
- [ ] Add/remove/reorder with large drag-drop cards
- [ ] Calendar screen with player + rival events
- [ ] Date picker on Stack a Card
- [ ] Conflict warnings (±2 days rival, 7-day own-event)
- [ ] Cross-event booking check (can't double-book a fighter)
- [ ] Training camp requirement (fighters need camp, shown as warning)
- [ ] Last-minute rejection based on personality
- [ ] Bidding war news toned down (max 1/7 days, potential ≥ 60 only)
- [ ] "Left promotion but still contracted" bug fixed
- [ ] All existing tests pass
