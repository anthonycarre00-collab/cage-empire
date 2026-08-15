> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Phase E3: Player Financial Levers

> **Status:** ACTIVE — implementation plan for Phase E3.
> **Source:** `docs/ECON_STAFF_PLAN.md` §3.3 (Player Levers), §3.4 (Balance Targets).
> **Supervisor:** main agent. Dispatching to full-stack-developer subagent.
> **Pre-read:** `docs/MASTER_PLAN.md`, `docs/CONVENTIONS.md` §13-14, `upload/VOICE_ENFORCEMENT.md`, `docs/NAV_BUTTONS_AUDIT.md`.

---

## 0. Scope

Phase E3 implements **5 of the 7 player financial levers** (the other 2 — staff hiring/firing + broadcast deal structure — are Phase E4/E6). Each lever gives the player a real decision with trade-offs.

| # | Lever | Where | Trade-off | Deliverable |
|---|---|---|---|---|
| 3.3.1 | Ticket price ($20-$300) | Event Builder | Higher price = more revenue/head but lower fill rate | E3.1 |
| 3.3.3 | Marketing budget ($0-$500k) | Event Builder | Boosts fill + PPV buys but is a real expense | E3.2 |
| 3.3.5 | Venue choice | Event Builder | Bigger venue = more gate but higher rental + empty-seat risk | E3.3 |
| 3.3.6 | PPV price ($30-$80) | Event Builder (PPV events only) | Higher price = more revenue/buy but fewer buys | E3.4 |
| 3.3.4 | Contract negotiation | Sign Free Agent modal | Replace hardcoded default with negotiation | E3.5 |

**Deferred to Phase E4/E6:**
- 3.3.2 (Broadcast deal structure) — needs Finance screen (Phase E6)
- 3.3.7 (Staff hiring/firing) — needs Staff Market screen (Phase E4)

---

## 1. Deliverables

### E3.1 — Event Builder screen (NEW) with ticket price + venue + marketing + PPV price

This is the biggest deliverable. A new screen `event_builder` that lets the player configure an upcoming event before scheduling it.

**Files to create:**
- `src/web/js/event_builder.js` (NEW)
- `src/web/css/event_builder.css` (NEW)

**Files to modify:**
- `src/web/index.html` — add `<script>` + `<link>` tags
- `src/web/js/app.js` — wire `event_builder` nav to new renderer (currently placeholder)
- `src/web/js/bridge.js` — add new bridge methods
- `src/app_web.py` — add new API methods
- `src/finance.py` — read player-set levers (ticket_price, marketing_spend, ppv_price) from event row
- `src/build_db.py` — migration v3.21.0 adds columns to events table

**Schema migration (v3.21.0):**
Add player-set lever columns to `events`:
```sql
ALTER TABLE events ADD COLUMN ticket_price INTEGER DEFAULT 80;        -- $20-$300
ALTER TABLE events ADD COLUMN marketing_spend INTEGER DEFAULT 0;      -- $0-$500k
ALTER TABLE events ADD COLUMN ppv_price INTEGER DEFAULT 60;           -- $30-$80 (PPV events only)
ALTER TABLE events ADD COLUMN is_ppv INTEGER DEFAULT 0;               -- 1 if PPV event
```

**New API methods:**
- `get_event_builder_data()` — returns: player's promo info, available venues (with capacity + venue_type + rental cost), weight classes, eligible fighters (player's roster, grouped by WC)
- `create_event(params)` — creates a scheduled event with player-set levers, returns event_id
- `get_event_summary(event_id)` — projected revenue/expense breakdown for the configured event (live preview as player adjusts levers)

**Event Builder UI:**
- **Step 1: Choose venue** — grid of venue cards (name, city, capacity, venue_type, rental cost). Filterable by capacity range.
- **Step 2: Set levers** — sliders/inputs for ticket_price ($20-$300), marketing_spend ($0-$500k), ppv_price ($30-$80, only if PPV event), is_ppv toggle.
- **Step 3: Live preview** — projected attendance, gate, PPV buys (if PPV), broadcast revenue, sponsorship, merch, concessions, fighter purses, staff salary, venue rental, marketing spend, insurance, **net profit**. Updates as player adjusts levers.
- **Step 4: Schedule event** — button to create the event. Writes to `events` table with player-set levers. Event appears on Dashboard "Your Next Card" + Calendar.

**Voice/design:**
- Section headers: "BUILD A CARD" (gold accent), "PICK YOUR VENUE", "SET YOUR LEVERS", "PROJECTED OUTCOME"
- Live preview uses voice phrases where possible (e.g., "Your war chest can absorb this" vs "You're betting the farm on this card" based on net profit vs current cash)
- No raw potential/ceiling numbers exposed
- Empty state: "No venues available in your region. Try expanding your market reach."

### E3.2 — Finance.py reads player-set levers

**File:** `src/finance.py` — `_process_event_finance` function.

Currently the finance model uses defaults (ticket_price = 50 + market_heat×2, marketing_multiplier = 1.0, ppv_price = 60 or 30). Update to read from the event row:

```python
# Read player-set levers from the event row
event_row = conn.execute(
    "SELECT ticket_price, marketing_spend, ppv_price, is_ppv "
    "FROM events WHERE event_id=?", (event_id,)
).fetchone()
ticket_price = event_row[0] if event_row and event_row[0] else (50 + market_heat * 2)
marketing_spend = event_row[1] if event_row and event_row[1] else 0
ppv_price = event_row[2] if event_row and event_row[2] else 60
is_ppv = bool(event_row[3]) if event_row else False
```

Then update the formulas:
- **fill_rate** — add `marketing_boost = marketing_spend / (attendance × $5)` (cap at +100%)
- **ppv_buys** — use `ppv_price` from event row, add `marketing_multiplier = 1 + (marketing_spend / $250k)` (cap at 2×)
- **ticket_revenue** — use `ticket_price` from event row (was auto-computed)
- **marketing_spend** — write as a `marketing` finance_transactions row (negative)

### E3.3 — Sign Free Agent contract negotiation (E3.5)

**File:** `src/web/js/free_agents.js` — sign modal.

Currently the sign modal shows "WHAT HE'LL COST YOU: $X" + "Make Him Yours" button. The cost is a single number from `estimate_signing_cost`. Replace with a negotiation panel:

- **Salary slider** ($10k-$500k/yr) — default to `estimate_signing_cost` value
- **Signing bonus slider** ($0-$1M) — default $0
- **Contract length slider** (1-5 years) — default 2 years
- **Win bonus % slider** (0-100%) — default 50%
- **Live acceptance indicator** — fighter "accepts" if total_value ≥ estimate × 0.9. Shows "He'll sign" (green) or "He's not interested" (red) based on the offer vs his expectation.
- **"Make Him Yours" button** — disabled if offer below acceptance threshold.

**Backend changes (`app_web.py`):**
- `sign_free_agent(fighter_id, salary, signing_bonus, contract_length, win_bonus_pct)` — update signature to accept negotiation params. Write the contract with the player-set terms. Deduct signing_bonus from promo cash immediately (finance_transactions row).

### E3.4 — Bankruptcy / failure state

**File:** `src/reputation.py` — add bankruptcy check.

Per ECON_STAFF_PLAN §3.5: when `promotions.current_cash < 0` for 2 consecutive monthly ticks:
- Fire a `PROMOTION_BANKRUPT` event
- Effects: reputation -10, fan_trust -15, all staff contracts voided, top 3 fighters request release
- News item: "FINANCIAL COLLAPSE: [Promo Name] files for bankruptcy protection"

This is the failure mode that makes the financial levers meaningful. Without it, the player can over-spend with no consequence.

### E3.5 — Tests + balance verification

**File:** `scripts/test_finance_e3.py` (NEW).

Tests:
1. Event Builder creates an event with player-set levers → event row has correct ticket_price/marketing_spend/ppv_price
2. Finance processes the event → reads player-set levers (not defaults)
3. Higher ticket_price → higher revenue but lower fill_rate
4. Higher marketing_spend → higher fill + PPV buys but higher expense
5. Sign free agent with negotiated terms → contract has correct salary/bonus/length
6. Bankruptcy fires when cash < 0 for 2 months
7. Balance: mid-tier event nets ~$500k, top-tier PPV nets ~$25M (per §3.4 targets)

---

## 2. Voice + Design Rules (per VOICE_ENFORCEMENT.md + CONVENTIONS §14)

- **No raw potential/ceiling numbers** in the Event Builder preview. PPV buys shown as a number is OK (it's a projection, not a hidden attribute). Fighter marketability is shown as a voice phrase if available.
- **No tabloid clichés** in news items. Bankruptcy news: "FINANCIAL COLLAPSE: [Promo] files for bankruptcy protection" — not "SHOCKING: [Promo] goes BUST!"
- **Empty states** use voice-appropriate phrases: "No venues available in your region. Try expanding your market reach." not "No data found."
- **Ownership language**: "YOUR NEXT CARD", "YOUR WAR CHEST", "YOUR STABLE"
- **Live preview voice phrases**: net profit shown as both a number AND a voice phrase:
  - Net > $0: "Your war chest can absorb this."
  - Net < 0 but cash > |net|: "You're betting the farm on this card."
  - Net < 0 and cash < |net|: "This could bankrupt you. Are you sure?"

---

## 3. Navigation + Button Audit (per NAV_BUTTONS_AUDIT.md)

- `event_builder` nav item already exists in sidebar (app.js:42) — currently a placeholder. Wire it to the new renderer.
- Dashboard "Your Next Card" section should have a "Build Card" button that navigates to `event_builder` (per NAV_BUTTONS_AUDIT §2 — currently NOT RENDERED).
- Sign Free Agent modal updated with negotiation panel (replaces single-button "Make Him Yours").
- All new buttons must have clear disabled states + voice-appropriate labels.

---

## 4. Reward + Fantasy Alignment (per CAGE_EMPIRE_SOUL.md)

- **Empire Builder fantasy**: player controls finances → "My promotion dominates the sport." ✅
- **Kingmaker fantasy**: Event Builder lets player choose venue + levers → "I create stars." ✅
- **Agency reward** (per REWARD_REVIEW.md): player decisions (ticket price, marketing, venue) have visible consequences (net profit preview, bankruptcy risk). ✅
- **Progression reward**: live preview shows how levers affect outcome → player learns the economic model. ✅

---

## 5. Acceptance Criteria

- [ ] Event Builder screen renders with venue picker + lever sliders + live preview
- [ ] Creating an event writes player-set levers to events table
- [ ] Finance.py reads player-set levers (not defaults) when processing the event
- [ ] Higher ticket_price → higher revenue/head but lower fill_rate (verified)
- [ ] Higher marketing_spend → higher fill + PPV buys + higher expense (verified)
- [ ] Sign Free Agent modal has negotiation panel (salary/bonus/length/win_bonus)
- [ ] Fighter accepts if offer ≥ estimate × 0.9, rejects otherwise
- [ ] Signing bonus deducted from promo cash immediately
- [ ] Bankruptcy fires when cash < 0 for 2 consecutive months
- [ ] Bankruptcy news item written (voice-compliant, no tabloid)
- [ ] Balance: mid-tier event nets ~$500k, top-tier PPV nets ~$25M
- [ ] All tests pass (save/load, news, finance E1+E2+E3)
- [ ] No raw potential/ceiling numbers exposed in UI

---

## 6. Out of scope (Phase E4+)

- Staff Market screen (Phase E4)
- Broadcast deal negotiation UI (Phase E6 — Finance screen)
- Finance screen UI (Phase E6)
- Contracts screen UI (Phase E6)
- Coach effects on training (Phase E5)
- Doctor/cutman/GM effects (Phase E5)
