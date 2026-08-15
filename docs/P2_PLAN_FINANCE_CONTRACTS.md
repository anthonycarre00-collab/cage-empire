> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# P2 Plan: Finance (The Books) + Contracts (Deals) Screens

> **Status:** ACTIVE — implementation plan for P2.
> **Source:** `docs/COMPREHENSIVE_REVIEW.md` P2 + `docs/ECON_STAFF_PLAN.md` §7

---

## 0. Scope

2 new screens — the Empire Builder fantasy's payoff screens.

| Screen | Nav ID | Data Available | Effort |
|---|---|---|---|
| The Books (Finance) | `finance` | finance_transactions (23 rows), promotions cash/rep/trust | Medium |
| Deals (Contracts) | `contracts` | 624 active contracts (1431 fighter + 102 staff) | Medium |

---

## 1. The Books (Finance) — `finance` nav

**API:** `get_finance_data(page, filters)` — returns:
- Promo summary: current_cash, starting_budget, reputation, fan_trust, monthly_burn_rate
- Recent transactions (paginated 20/page, filterable by type)
- Cash flow breakdown by type (last 30 days): revenue vs expenses
- Salary breakdown: total fighter salaries, total staff salaries, per-event cost
- Last event P&L (if any completed events with finance data)

**UI:**
- Section header: "THE BOOKS" (gold accent) + subtitle showing current cash
- **Summary strip**: 4 stat tiles — Current Cash, Monthly Burn, Reputation (voice phrase), Fan Trust (voice phrase)
- **Cash Flow section**: two-column — Revenue (ticket_sales, broadcast_revenue, sponsorship, merchandise, concessions) vs Expenses (fighter_purse, staff_salary, venue_rental, marketing, medical_cost, bonus_payment). Last 30 days. Color-coded green/red.
- **Recent Transactions** table: date, type (chip), description, amount (green positive / red negative). Paginated. Filterable by type.
- **Last Event P&L** card (if available): event name, date, revenue breakdown, expense breakdown, net profit, show rating (voice phrase)
- Empty state: "The books are open. Run your first show to see the numbers move."

## 2. Deals (Contracts) — `contracts` nav

**API:** `get_contracts_data(page, filters)` — returns:
- Fighter contracts (paginated, filterable by expiry status)
- Staff contracts
- Expiring soon (end_date within 60 days)

**UI:**
- Section header: "DEALS" (gold accent) + subtitle "X active contracts"
- **Filter bar**: All / Expiring Soon (≤60 days) / Fighters / Staff
- **Fighter Contracts** table: fighter name (clickable → Fighter Profile), salary, start_date, end_date, days_until_expiry (color-coded: red ≤30 days, yellow ≤60 days, green >60 days), bonus_structure (voice phrase: "75% win bonus"), status chip
- **Staff Contracts** table: staff name, role, skill (voice phrase), salary, end_date, days_until_expiry
- **Expiring Soon** alert banner (if any ≤30 days): "X contracts expire within 30 days. Time to talk extensions."
- Click contract → expand to show full details (buyout clause, exclusivity, etc.)
- Empty state: "No deals on the table. Sign some fighters or staff."

## 3. Implementation

Pattern: `staff_market.js` / `rankings.js` (IIFE, bridge methods, CSS, nav wiring).

Files to create:
- `src/web/js/finance.js` + `src/web/css/finance.css`
- `src/web/js/contracts.js` + `src/web/css/contracts.css`

Files to modify:
- `src/web/index.html` — add 4 script/link tags
- `src/web/js/app.js` — wire 2 nav items
- `src/web/js/bridge.js` — add bridge methods
- `src/app_web.py` — add 2 API methods

## 4. Voice + design rules
- No raw reputation/trust numbers in headers — voice phrases
- Salary amounts OK as dollar figures (they're contracts, not hidden attributes)
- Days-until-expiry OK as a number (it's a countdown, not a rating)
- Gold accents, dark bg, section headers with accent bars
- Green for revenue/positive, red for expenses/negative
- Empty states with voice-appropriate phrases
