> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Economic + Financial + Staff Audit & Plan

**Task ID:** ECON-STAFF-AUDIT
**Date:** 2026-10-30 (sim date)
**Author:** Sub-agent audit pass
**Status:** RESEARCH + PLANNING ONLY — no code changes proposed in this doc, only direction for future phases.

**Scope:** Audit the existing economic/financial model and the staff system, identify what is weak / broken / underutilised, and produce a phased plan to make finances realistic + balanced + player-influenced (with gate receipts + PPV/broadcast as the main income) and to make staff a real, signable, useful, costly layer of the simulation.

---

## 0. Executive Summary (TL;DR)

The financial model exists but is **not wired into the active GUI app** (`src/app.py` and `src/app_web.py` both omit `finance.register_subscribers()` from their registration list). That single bug is why promo 1 (the player's promo) has exactly **one** finance_transaction row — the $80M opening-balance "sponsorship" seed entry on 2026-01-01. Every event the player has run from the GUI has produced zero finance rows. AI rival promos (2-10) have transactions only because `scripts/run_sim_forward.py` auto-registers `finance` when it runs sim-forward batches.

The staff system has **379 staff** seeded but most of them have **no gameplay effect**:
- 300 coaches — gym-bound, no `staff_contracts` row, **completely missing from the salary model** (finance.py's `WHERE promotion_id=?` filter excludes them). Training camps have `gym_id` but no `coach_id` — coaches affect nothing.
- 25 commentators — seeded, but `broadcast_staff` table has **0 rows** and `pundit_bias` column is NULL on every staff row. Punditry system can't actually use them.
- 24 scouts — **only staff with a real effect** (scouting.py uses `eye_for_talent` + `mistake_rate`). But `scouting_reports` has 0 rows — no scouting has ever been done in this save.
- 10 doctors / 10 cutmen / 10 GMs — pure salary drains, zero gameplay effect.
- Player has **no UI** to hire, fire, view, or assign staff. Only the rival AI can hire/fire (quarterly, via `services/rival_ai/staff_manager.py`).

Player has **zero direct financial levers** today: ticket prices auto-computed, broadcast tier fixed at seed, no marketing system, no venue selection, no contract negotiation (sign_free_agent uses a hardcoded $50k default).

The plan below proposes **6 phases** over an estimated **14-20 dev-days**:
1. Fix the finance wiring bug + backfill promo 1's missing transactions.
2. Replace the flat broadcast_tier lookup with proper PPV/broadcast revenue (gate + buyrate × price).
3. Add player financial levers (ticket pricing slider, marketing spend, broadcast negotiation, venue picker in Event Builder).
4. Build the Staff Market screen (free-agent pool for staff, hire/fire flows).
5. Wire staff effects into the simulation (coaches → camp quality → attribute dev; doctors/cutmen → injury recovery; GM → cost reduction; commentators → show_rating).
6. Build Finance ("The Books") + Contracts ("Deals") screens.

---

## 1. Current Financial Model Audit

### 1.1 What income sources exist?

Per `src/finance.py::_process_event_finance` (lines 74-220), the system computes 3 revenue streams per event:

| Type | Formula | Reality Check |
|---|---|---|
| `ticket_sales` | `venue_cap × fill_rate × avg_ticket_price` where `fill_rate = clamp(market_heat/100, 0.30, 0.98)` and `avg_ticket_price = 50 + (market_heat × 2)` ($50-$240) | OK in principle. No player lever on price or fill. |
| `broadcast_revenue` | Flat lookup by `promotions.broadcast_tier`: `ppv_global=$500k`, `streaming=$150k`, `tv_regional=$75k`, `local_stream=$15k` | **No buyrate calculation, no per-event variance, no negotiation.** |
| `merchandise` | `Σ fighter.marketability × $100` for every fighter on the card | Linear + simplistic. No fan_trust factor, no sponsor cut. |
| `sponsorship` | **One seed row only** ($80M for promo 1 on 2026-01-01, smaller for others). No recurring sponsorship income exists. | The CHECK constraint allows `'sponsorship'` as a transaction_type, but `finance.py` never writes one. |

**Missing income sources:**
- ❌ PPV buyrate × PPV price (the headline revenue source the user called out)
- ❌ Recurring sponsorships (banner ads, kit sponsors, title sponsors) tied to promotion reputation
- ❌ Concessions / parking / VIP / hospitality (per-attendance revenue)
- ❌ Broadcast deal negotiation (flat fee vs PPV split vs rights fee)
- ❌ Marketing-driven revenue boosts

### 1.2 What expenses exist?

Per `finance.py::_process_event_finance` (lines 161-220):

| Type | Formula | Reality Check |
|---|---|---|
| `fighter_purse` | `contracts.salary` per fighter on the card (negative). Winner bonus NOT paid — just the salary. Schema allows `'bonus_payment'` + `'signing_bonus'` types but `finance.py` never writes them. | Missing win bonuses, finishing bonuses, signing bonuses. |
| `venue_rental` | `venue_cap × $5/seat` (negative) | Flat per-seat. No venue-type variance (arena vs ballroom vs outdoor). |
| `staff_salary` | `n_staff × $2000` per event (negative). Query: `SELECT COUNT(*) FROM staff WHERE promotion_id=?` | **Two bugs:** (a) misses all 300 coaches (they use `gym_id` not `promotion_id`); (b) $2000/event × 8 staff = $16k/event is wildly underpriced vs the $40k-$80k/yr contracts.salary values — should be ~$5k-$10k per staff per event if events run monthly. |
| `medical_cost` | `n_fights × $1500` (negative) | Flat per-fight. No injury-treatment variance. |
| `weight_cut_penalty` | `salary × penalty_pct / 100` per `weight_cut_log` row (negative) | OK — already wired. |

**Missing expenses:**
- ❌ Marketing spend (no schema, no code)
- ❌ Insurance (per-event liability + per-fighter medical coverage)
- ❌ Travel/accommodation for fighters + staff (relevant for away shows)
- ❌ Tax (would add realism but optional)
- ❌ Signing bonuses for new fighter contracts

### 1.3 How is revenue calculated from a show?

Currently the chain is:
1. `schedule_next_event` (in `app.py`) creates an event with `venue_id` + `market_id`.
2. Player or AI resolves fights via `resolve_next_fight` → publishes `FIGHT_RESOLVED` on the event bus.
3. When the last fight resolves, `app._update_event_status_after_resolution` sets `events.status='completed'` + publishes `EVENT_COMPLETED`.
4. `finance._process_event_finance` is supposed to fire on `FIGHT_RESOLVED`, but it actually checks `events.status=='completed'` and skips otherwise. So it only processes once the event is complete.
5. **It then writes 7-9 finance_transactions rows** (ticket_sales, broadcast_revenue, merchandise, fighter_purse×N, venue_rental, staff_salary, medical_cost, weight_cut_penalty×N).
6. Each row updates `promotions.current_cash`.

**The `show_rating.py` engine** computes fan/commercial/excitement/quality/overall ratings on `EVENT_COMPLETED` and feeds the commercial_rating axis from `attendance` + `marketability` + `broadcast_tier`. But `show_rating.py::_get_attendance` has a defensive fallback that computes attendance on-the-fly **because it can't trust finance to have run yet** (line 336-381). That fallback is the symptom of the wiring bug.

### 1.4 What levers does the player currently have?

**Direct financial levers — NONE.** The player cannot:
- ❌ Set ticket prices (auto = `50 + market_heat × 2`)
- ❌ Choose PPV price or broadcast model (broadcast_tier is set at promotion seed, never changes)
- ❌ Negotiate or sign broadcast deals (no UI, no schema for negotiation beyond the vestigial `broadcast_contracts` table which has 0 rows)
- ❌ Invest in marketing (no system exists)
- ❌ Choose venue size / pick a venue (events are auto-assigned venues by `schedule_next_event`)
- ❌ Renegotiate fighter contracts (`sign_free_agent` uses hardcoded $50k default; no renew/extension flow)
- ❌ Set signing bonuses or win bonuses

**Indirect levers (the player's only current financial influence):**
- ✅ Book good cards → high `show_rating.fan_rating` → market_heat rises (via `venues.py::_adjust_market_heat`) → next event's `fill_rate` + `avg_ticket_price` rise.
- ✅ Sign high-marketability fighters → boosts `merchandise` revenue + `commercial_rating`.
- ✅ Sign free agents at the default $50k (no negotiation, but at least the player picks who).

This is far too thin. The "main income from great shows" loop the user described does technically exist (show quality → market heat → ticket revenue), but it has **no per-event player decisions** and **no failure mode** (the player cannot lose money by over-spending because they cannot spend).

### 1.5 What's broken / weak?

**Critical bugs:**

1. **`finance.register_subscribers()` is never called from the GUI app.**
   - `src/app.py:330-587` registers 17 subscriber modules but `finance` is not in the list.
   - `src/app_web.py:86-91` lists 14 modules (`registration_modules`) and `finance` is not among them.
   - `src/ui_legacy/app.py:198-299` also omits finance.
   - **Effect:** Every event the player runs from any GUI produces zero finance_transactions. Promo 1 has 431 completed events in the DB but only 1 finance_transactions row (the seed opening balance).
   - Only `scripts/run_sim_forward.py` (lines 97-98) auto-registers finance, which is why AI rival promos have transactions.
   - `src/services/finance_svc.py` is a pure re-export wrapper with a comment that explicitly punts: "defer `process_event_finances` + weekly cashflow tick to Task 6.10 Finance screen." So this is a known gap.

2. **`finance._process_event_finance` subscribes to the wrong event.**
   - It subscribes to `FIGHT_RESOLVED` (line 288) but its first action is to bail unless `events.status=='completed'` (line 90). That's a fragile pattern — it should subscribe to `EVENT_COMPLETED` directly, like `show_rating.py` does (and like `finance.py`'s own module docstring suggests: "Subscribe to FIGHT_RESOLVED. When an event completes..." — the parenthetical reveals the real intent).
   - Risk: if subscription order is wrong, finance fires before the event status flips to 'completed' and skips. Or it never fires at all if the status flip happens via a different code path.

3. **Staff salary query misses all 300 coaches.**
   - `finance.py:182-185`: `SELECT COUNT(*) FROM staff WHERE promotion_id=?`
   - Coaches use `gym_id` (not `promotion_id`) per the v3.9.0 Phase 1.5 Fix C6 backfill. So they're never counted.
   - **Effect:** Even when finance does fire, it under-counts staff by ~97% (300 coaches vs 8 promo-bound staff for promo 1).

4. **Staff salary $2000/event flat doesn't match `contracts.salary`.**
   - `finance.py:44`: `_STAFF_SALARY_PER_EVENT = 2000`
   - But seeded staff contracts show: GM $80k/yr, doctor $60k/yr, commentator $50k/yr, scout $45k/yr, cutman $40k/yr.
   - A promo with 8 staff averages ~$54k/yr/staff = ~$4.5k/month. If events run monthly, $2000/event × 8 = $16k/event is roughly 1/2 the true monthly burn. (And that's *before* counting the 300 missing coaches.) The number is also decoupled from the actual `contracts.salary` value, so renegotiating a contract wouldn't change the expense.

5. **Sponsorship income is one-shot, not recurring.**
   - Schema allows `transaction_type='sponsorship'` but `finance.py` never writes one. Only the seed (one row per promo, on 2026-01-01, as the opening balance) ever inserts one.
   - **Effect:** Promotions have no recurring sponsorship revenue tied to reputation, despite the schema anticipating it.

6. **`broadcast_contracts` + `broadcast_staff` tables are vestigial (0 rows).**
   - `broadcast_contracts` schema: `(contract_id, staff_id, network_name)`. The `staff_id` is required, suggesting the original design was "a broadcaster is a staff member with a contract."
   - `broadcast_staff` schema: `(staff_id, on_air_role)`. Also 0 rows.
   - 25 commentators exist in `staff` (role_type='commentator') but **none** appear in `broadcast_staff`, and their `pundit_bias` column is NULL.
   - **Effect:** The entire "commentator/pundit as staff" design is dead code. Punditry system has no named pundits to draw from.

7. **Fighter purse doesn't pay win/finish bonuses.**
   - `finance.py:163-173` pays `contracts.salary` to every fighter on the card, win or lose. The `bonus_structure` column on `contracts` exists but is never read.
   - Schema allows `'bonus_payment'` and `'signing_bonus'` transaction types but nothing writes them.

8. **Merchandise ignores `fan_trust`.**
   - `finance.py:154`: `merch_revenue = total_marketability × 100`. Linear in marketability, ignores fan_trust entirely. A promo with fan_trust=20 sells the same merch as one with fan_trust=80 if marketability is equal.

9. **No marketing / marketing_spend system at all.**
   - No schema, no code, no UI. The rival AI's `archetypes.py` mentions `"marketing": 0.10` in budget allocations (lines 120-171) but no actual marketing spend is ever recorded.

10. **No weekly/monthly cash burn — only per-event P&L.**
    - Staff salaries, gym leases, insurance, etc. are real-world monthly costs. The sim has a `TICK_ADVANCED` event (fired daily by `tick_processor`) but `finance.py` doesn't subscribe to it. So staff only "cost" money on event day, not between events. A promo that runs 0 events in a month pays 0 staff cost.

---

## 2. Current Staff System Audit

### 2.1 What staff roles exist?

Per the live DB (`SELECT role_type, COUNT(*) FROM staff GROUP BY role_type`):

| Role | Count | Bound To | Salary (avg) | Has staff_contract? | Gameplay effect? |
|---|---|---|---|---|---|
| `coach` | **300** | `gym_id` (not promotion_id) | None (no contract) | ❌ No | ❌ **None** — `training_camps` has `gym_id` but no `coach_id` column; `services/training_svc.py:progress_camps()` never references coaches. |
| `commentator` | 25 | `promotion_id` | $50,000/yr | ✅ Yes | ❌ **None** — `broadcast_staff` table has 0 rows, `pundit_bias` is NULL on every row. Punditry system can't use them. |
| `scout` | 24 | `promotion_id` | $45,000/yr | ✅ Yes | ✅ **Yes** — `scouting.py` reads `eye_for_talent` + `mistake_rate` from the JSON `specialty` column. But `scouting_reports` has 0 rows — no scouting has ever happened in this save. |
| `general_manager` | 10 | `promotion_id` | $80,000/yr | ✅ Yes | ❌ **None** — pure salary drain. |
| `doctor` | 10 | `promotion_id` | $60,000/yr | ✅ Yes | ❌ **None** — no effect on injury recovery, no event medical_cost discount. |
| `cutman` | 10 | `promotion_id` | $40,000/yr | ✅ Yes | ❌ **None** — no effect on cut/stoppage outcomes. |
| **TOTAL** | **379** | | | | Only **1 of 6 roles** (scouts) has any effect, and that effect has never been exercised. |

The user's "completely underutilised" assessment is correct — 6 staff types seeded, 5 of them do nothing.

### 2.2 What do they DO?

**Coaches (300):**
- Schema: `staff.gym_id` links coach → gym.
- Intended effect (per `build_db.py:1384-1393` comment): "the upcoming training-camps UI screen displays the coach alongside the fighter's gym."
- Actual effect: **none**. `training_camps` table has no `coach_id` column. `services/training_svc.py:progress_camps()` updates `attribute_changes` based on `camp_focus` + `camp_duration_days` + `camp_morale` but never references any coach.
- The "Phase 1.5 Fix C6" backfill (per the comment) only populated `gym_id` — it didn't wire any coach effect.

**Scouts (24):**
- Schema: `staff.specialty` JSON column carries `{eye_for_talent, technical_analysis, character_reading, mistake_rate, bias_style, bias_nationality, bias_aggression, current_assignment, assignment_start_date}`.
- Actual effect: `scouting.py:generate_scouting_report()` reads `eye_for_talent` to weight potential estimates, `mistake_rate` to roll for misjudgments. Real, working code.
- But: `scouting_reports` table has **0 rows**. No scout has been assigned (player has no UI to assign them; AI doesn't call `scouting_svc.assign_scout`). The `current_assignment` JSON field is `null` on every scout.
- So scouts have the only coded effect, but it has never fired in this save.

**Commentators (25):**
- Schema: `staff.role_type='commentator'`, `specialty='play_by_play'` (or similar). `pundit_bias` column exists for JSON bias data.
- Intended effect (per `build_db.py:1395-1405`): "stores a broadcast pundit's per-attribute bias so the Fight Resolution screen can render named-pundit interjections that favour strikers / grapplers / veterans / prospects / nations / gyms."
- Actual effect: `pundit_bias` is NULL on all 25 commentators. `broadcast_staff` table (the link table) has 0 rows. Punditry system has no named pundits to draw from.

**Doctors (10) + Cutmen (10):**
- Schema: `staff.specialty='sports_medicine'` (doctor) or `'cuts_and_swelling'` (cutman).
- Intended effect: presumably injury recovery + cut/stoppage outcomes. No code reads these.
- Actual effect: **none**. The `services/rival_ai/staff_manager.py:_evaluate_fires()` uses injury rate as a fire-trigger for medical staff (so they can be fired for poor performance), but there's no positive effect of having them. A promo with 0 doctors has the same injury outcomes as one with 5.

**General Managers (10):**
- Schema: `staff.specialty='operations'`.
- Actual effect: **none**. Pure salary line item.

### 2.3 How are they hired / fired?

**AI rival promos** (fully implemented in `services/rival_ai/staff_manager.py`):
- Fires quarterly (every 84 sim days) via `rival_ai.py`'s TICK_ADVANCED dispatch.
- Fire evaluation per role:
  - Scout: <2 useful reports in 90 days AND tenure ≥180 days → fire-eligible.
  - Commentator: never fired ("voice of the brand").
  - Doctor/Cutman: promo injury rate >30% above league avg → fire-eligible (recency bias).
  - GM: never fired.
  - 30% whimsy roll on fire-eligible staff ("most get one more quarter").
  - Loyalty protection: tenure ≥365 days → grace period.
- Hire evaluation: compares staff counts to archetype.staff_target; checks budget (cash ≥ 2× monthly staff commitment); hires 1/role/quarter max.
- Writes news items (topic='staff', sentiment positive for hires, neutral for fires).

**Player (promo 1):**
- ❌ **No staff screen at all.** Cannot view, hire, fire, or assign any staff.
- The 8 staff seeded onto promo 1 (3 commentators, 1 cutman, 1 doctor, 1 GM, 2 scouts) are fixed forever in this save unless the AI fires them (it doesn't — only AI promos are evaluated).
- No "Staff Market" or "Staff Free Agents" screen exists. `src/web/js/` has dashboard.js, fighter_profile.js, free_agents.js, roster.js, bridge.js, app.js — no staff.js.

### 2.4 What do they cost?

Per live DB query (`SELECT sc.contract_role, AVG(c.salary) FROM staff_contracts sc JOIN contracts c ON c.contract_id=sc.contract_id GROUP BY sc.contract_role`):

| Role | Avg Annual Salary | Per-Event Cost (if monthly events) |
|---|---|---|
| general_manager | $80,000 | ~$6,667 |
| doctor | $60,000 | ~$5,000 |
| commentator | $50,000 | ~$4,167 |
| scout | $45,000 | ~$3,750 |
| cutman | $40,000 | ~$3,333 |
| coach | **$0** (no contract) | $0 — never paid |

But `finance.py:_STAFF_SALARY_PER_EVENT = 2000` pays **$2,000 flat per staff member per event regardless of role or contract**. So:
- A promo with 8 staff (avg $54k/yr) should burn ~$36k/event if monthly — finance pays $16k/event.
- A promo with 0 staff pays $0 — but coaches (300 of them, none with contracts) are never paid by anyone.
- The disconnect means contract salary is fiction — finance.py never reads it.

### 2.5 What's broken / underutilised?

1. **Player has zero staff management UI.** No screen, no hire flow, no fire flow, no assign flow.
2. **300 coaches are orphaned** — no contract, no salary, no effect on training.
3. **Commentators/pundits are dead code** — `broadcast_staff` empty, `pundit_bias` NULL everywhere.
4. **Doctors/cutmen/GMs have no effect** — pure salary drains the player can't even adjust.
5. **Scouts have working code but 0 scouting_reports** — player can't assign them.
6. **No staff market / free agent pool for staff** — only the rival AI's `_hire_staff()` creates new staff (random name + flat salary). Player can't browse candidates.
7. **No staff development** — skill levels are static. No experience accrual, no attribute improvement, no aging effects.
8. **No contract negotiation** — salaries are flat per role (`STAFF_SALARY_BY_ROLE` dict in `staff_manager.py:32-38`). A 28-year-old rookie GM costs the same as a 50-year-old Hall-of-Fame GM.
9. **Coaches have no `staff_contracts` row** — they're outside the contract system entirely. The schema supports it (the table exists) but no seed populates it.
10. **Staff firing has no morale consequence** — the comment says "may affect morale if done ruthlessly" in the user's brief, but no current code penalises the player for firing staff.

---

## 3. Proposed Financial Model

Goal: a realistic, balanced model where the **main income is gate receipts + PPV/broadcast money** (per the user's directive), secondary income comes from sponsorships/merch/concessions tied to reputation & fan_trust, and the player has **meaningful levers** that create real trade-offs.

### 3.1 Revenue Model

#### 3.1.1 Gate Receipts (PRIMARY — ~40-60% of revenue for most promos)

```
attendance = venue.capacity × fill_rate
gate_receipts = attendance × ticket_price

where:
  fill_rate = clamp(
    0.30                                   # floor — even a cold market sells 30%
    + (market_heat / 100) × 0.50           # heat drives up to 80% baseline
    + (promo.reputation / 100) × 0.10      # promo brand adds 10pp
    + marketing_boost                      # player marketing spend (see 3.3.3)
    - price_elasticity_penalty             # higher prices → lower fill (see 3.3.1)
    , 0.10, 0.99)
  
  ticket_price = player-set, with a default of (50 + market_heat × 2)
```

Player lever: **ticket price slider** in the Event Builder. Higher price = more revenue per head but lower fill rate (price elasticity). The optimal price depends on market heat + card quality + opponent draw.

#### 3.1.2 PPV / Broadcast Revenue (PRIMARY — ~20-50% of revenue, depending on tier)

Replace the flat `_BROADCAST_REVENUE` lookup with a real PPV model:

```
For PPV events:
  ppv_buys = base_buyrate × card_draw_multiplier × marketing_multiplier
  
  where:
    base_buyrate = promo_reputation_factor × fan_trust_factor × broadcast_partner_reach
      (ppv_global: 250k base; streaming: 50k base; etc.)
    
    card_draw_multiplier = 1.0
      + 0.5 × (main_event_marketability / 100)        # main event drives buys
      + 0.2 × (co_main_marketability / 100)           # co-main adds
      + 0.3 × (n_title_fights / 2)                    # title fights boost
      + 0.1 × (n_rivalry_fights_heat_50_plus / 3)     # beefs sell
  
  ppv_revenue = ppv_buys × ppv_price × player_split
    (player_split = 50% default; negotiable up to 70% with bigger partners
     in exchange for smaller base rights fee)

For non-PPV events (flat broadcast rights):
  broadcast_revenue = rights_fee_per_event × broadcast_partner_tier
    (negotiated in 3.3.2; ranges from $15k local to $500k global)
```

Player lever: **PPV price** (slider, $30-$80 typical range) and **broadcast deal structure** (flat fee vs PPV split — see 3.3.2).

#### 3.1.3 Sponsorship (SECONDARY — ~5-15% of revenue)

Recurring, reputation-tied, written quarterly or per-event:

```
sponsorship_revenue_per_event = base_sponsor_pool × promo_multiplier

where:
  base_sponsor_pool = $25k (local) ... $500k (ppv_global) — tier-dependent
  
  promo_multiplier = (promo.reputation / 100) × (promo.fan_trust / 100) × 2.0
    # A promo with rep=80, trust=70 → 1.12× base
    # A promo with rep=30, trust=20 → 0.12× base (sponsors flee)
```

Player lever: **none directly** — sponsorship is a passive consequence of reputation + fan_trust. But the player *indirectly* drives it by putting on great shows (raises rep) and treating fans well (raises trust).

Implementation: write a `sponsorship` finance_transactions row on every event (replacing the current one-shot opening-balance pattern).

#### 3.1.4 Merchandise (SECONDARY — ~2-8% of revenue)

Fix the current linear formula:

```
merch_revenue = attendance × (avg_fighter_marketability / 100) × fan_trust_factor × $8

where:
  fan_trust_factor = 0.5 + (promo.fan_trust / 100)   # trust=100 → 1.5×, trust=20 → 0.7×
  $8 = avg per-attendee merch spend (calibrated)
```

Captures: more attendees = more merch, hotter fighters = more merch, but **fan trust gates it** (fans don't buy merch from a promo they don't trust).

#### 3.1.5 Concessions / Parking / VIP (SECONDARY — ~5-10% of revenue)

New income type, simple per-attendee calculation:

```
concessions_revenue = attendance × $15 (food/beer/parking avg)
  + vip_tickets × vip_price (if venue has VIP suites — schema addition needed)
```

This is a small but realistic line item that scales with attendance (so big-venue shows earn noticeably more than small-venue ones).

### 3.2 Expense Model

#### 3.2.1 Fighter Salaries (PRIMARY expense — ~30-50% of revenue)

Replace the current "pay salary to everyone" with a real purse structure:

```
per fighter on card:
  base_purse = contracts.salary / n_events_per_year    # pro-rated
  win_bonus = base_purse × win_bonus_pct (contracts.bonus_structure JSON, default 50%)
  finish_bonus = $5k flat if winner by KO/Sub/Doctor stoppage
  title_fight_bonus = $25k flat if is_title_fight=1
  main_event_bonus = $10k flat if card_slot='main_event'
  
  total_purse = base_purse + (win_bonus if winner else 0) + (finish_bonus if winner_by_finish)
                + (title_fight_bonus if is_title_fight) + (main_event_bonus if main_event)
```

Reads the existing `contracts.bonus_structure` JSON column (currently unused).

Player lever: **contract negotiation** (see 3.3.4) — the player sets salary + win_bonus_pct + signing_bonus when signing/renewing.

#### 3.2.2 Staff Salaries (MONTHLY expense, not per-event)

Fix the current $2k/event flat by switching to a monthly tick:

```
For each active staff_contracts row:
  monthly_salary = contracts.salary / 12
  → written as a 'staff_salary' finance_transactions row on every monthly TICK_ADVANCED
    (current_day % 30 == 0)
```

**Critical fix:** count coaches too. Either (a) give coaches `staff_contracts` rows (preferred — coaches should be hirable/fireable too, see §4) or (b) handle coaches via a separate gym-lease expense line (the gym pays the coach, the promo pays the gym a lease). Option (a) is simpler and aligns with the user's "sign staff" directive.

Player lever: **staff hiring/firing** (see §4) directly controls this expense.

#### 3.2.3 Venue Rental (per-event, tiered)

Replace flat $5/seat with venue-type tiers:

```
venue_cost = venue.capacity × cost_per_seat_by_venue_type

  arena (cap 15k+):    $7/seat   # big production, security, staff
  ballroom (5-15k):    $5/seat
  theater (2-5k):      $4/seat
  outdoor (<2k):       $3/seat
```

Requires adding a `venue_type` column to `venues` (currently only has capacity + name). The cost-per-seat tiers can be a constants dict in `finance.py` keyed on `venue_type`.

Player lever: **venue selection in Event Builder** (see 3.3.5) — bigger venue = more gate potential but higher fixed cost. Risk/reward trade-off.

#### 3.2.4 Marketing Spend (NEW — player-controlled)

```
marketing_spend_per_event = player-set amount ($0 to $500k typical)

Effects (computed in fill_rate + buyrate formulas above):
  marketing_boost_to_fill = marketing_spend / (attendance × $5)   # $5 per attendee = +100% fill boost cap
  marketing_multiplier_to_buys = 1 + (marketing_spend / $250k)    # $250k = 2× buyrate boost cap
```

Diminishing returns implicit (each additional dollar adds less because of the cap structure).

Player lever: **marketing budget slider** in Event Builder or Finance screen. Higher spend = more attendance + more PPV buys, but it's a real expense.

#### 3.2.5 Insurance + Medical (per-event)

```
insurance_cost = $5k flat (event liability) + $2k per fight (medical coverage)
medical_cost = $1.5k per fight (current) + injury_treatment_costs
  where injury_treatment_costs = SUM(injury.severity × $500) for new injuries this event
```

Doctor staff could discount this (see §4.3.3).

#### 3.2.6 Travel/Accommodation (per-event, optional)

For "away" shows (event market_id != promo's home region):

```
travel_cost = n_fighters_on_card × $1.5k + n_staff × $1k
```

Requires adding a `home_region_id` to promotions (or using the existing `region_id`). Optional realism layer — can defer to Phase 7+.

### 3.3 Player Levers (Summary)

| # | Lever | Where Set | Trade-off |
|---|---|---|---|
| 3.3.1 | Ticket price ($20-$300) | Event Builder | Higher price = more revenue/head but lower fill rate (price elasticity). |
| 3.3.2 | Broadcast deal structure (flat fee vs PPV split) | Finance screen → Broadcast tab | Flat fee = guaranteed income but no upside; PPV split = high ceiling but card-quality dependent. |
| 3.3.3 | Marketing budget ($0-$500k/event) | Event Builder or Finance screen | Boosts fill + buys but is a real expense. Diminishing returns. |
| 3.3.4 | Fighter contract terms (salary, win bonus, signing bonus, length) | Contracts screen | Higher salary = better fighter retention but bigger expense; signing bonus = upfront cash hit. |
| 3.3.5 | Venue choice | Event Builder | Bigger venue = more gate potential but higher rental + risk of empty seats (looks bad, hurts market heat). |
| 3.3.6 | PPV price ($30-$80) | Event Builder (PPV events only) | Higher price = more revenue/buy but fewer buys (elasticity). |
| 3.3.7 | Staff hiring/firing | Staff screen | More/better staff = better fighter dev + show quality, but bigger monthly burn. |

These are the seven levers the player can pull. None of them exist today.

### 3.4 Balance Targets

For a mid-tier promo (rep=60, trust=60, regional TV, 8k seat venue, market_heat=60):
- **Gate:** 8k × 0.70 fill × $80 avg = $448k
- **Broadcast (flat regional TV):** $75k
- **Sponsorship:** $100k × 0.72 multiplier = $72k
- **Merch:** 5.6k attendees × 0.6 mkt × 1.1 trust × $8 = $29.6k
- **Concessions:** 5.6k × $15 = $84k
- **Total revenue:** ~$708k

- **Fighter purses (8 fights, avg $4k base + 50% win bonus):** ~$48k
- **Staff salaries (8 staff × $4.5k/event pro-rata):** ~$36k
- **Venue rental (8k × $5):** $40k
- **Marketing (mid-pack):** $50k
- **Insurance + medical:** $5k + 8 × $3.5k = $33k
- **Total expenses:** ~$207k

- **Net profit per event:** ~$500k (a healthy regional show)

For a top-tier PPV promo (rep=90, trust=80, PPV global, 18k seat arena, market_heat=85):
- **Gate:** 18k × 0.92 fill × $200 = $3.3M
- **PPV (250k base buys × 1.8 card_draw × 1.4 marketing × $60 × 60% split):** ~$22.7M
- **Sponsorship:** $500k × 1.44 = $720k
- **Merch:** 16.5k × 0.75 × 1.3 × $8 = $129k
- **Concessions:** 16.5k × $15 = $248k
- **Total revenue:** ~$27.1M

- **Fighter purses (12 fights, avg $25k base + 100% win bonus + main event bonus + title bonuses):** ~$700k
- **Staff salaries (15 staff × $5k/event):** $75k
- **Venue rental (18k × $7):** $126k
- **Marketing (heavy):** $250k
- **Insurance + medical:** $5k + 12 × $3.5k = $47k
- **Total expenses:** ~$1.2M

- **Net profit per event:** ~$25.9M (a blockbuster PPV)

These numbers feel right — PPV is the lion's share for top promos, gate is the workhorse for regional promos, and the player can lose money if they over-spend on marketing/venue/fighter salaries relative to card quality.

### 3.5 Bankruptcy / Failure State

Currently the `reputation.py` module has a "bankruptcy check" (per the app.py:556-568 comment), but without finance firing for the player, it can never trigger.

Proposed: when `promotions.current_cash < 0` for 2 consecutive monthly ticks:
- Fire a `PROMOTION_BANKRUPT` event.
- Effects: reputation -10, fan_trust -15, all staff contracts voided (they leave), top 3 fighters request release.
- Player must recover via austerity (cut marketing, fire staff, run cheaper shows) or accept game-over.

This is the failure mode that makes the financial levers meaningful.

---

## 4. Proposed Staff System

### 4.1 Roles + Effects (rewired)

| Role | Bound To | Salary Range | Effect (NEW) |
|---|---|---|---|
| **Coach** | `gym_id` + new `coach_id` on `training_camps` | $30k-$150k/yr based on skill | Boosts `attribute_changes` magnitude in `progress_camps()`. A 90-skill coach → 1.5× attribute gain; a 30-skill coach → 0.7×. Also reduces `camp_injury_risk` by (skill/200). |
| **Scout** | `promotion_id` (assigned to a target fighter) | $30k-$80k/yr based on `eye_for_talent` | Already wired via `scouting.py`. Player UI to assign scouts to targets (see §5.3). |
| **Commentator** | `promotion_id` + `broadcast_staff` link | $30k-$80k/yr | Boosts `show_rating.commercial_rating` by +1 per 10 skill points (max +10). Populates `pundit_bias` JSON for the punditry system (named interjections during fight resolution). |
| **Doctor** | `promotion_id` | $40k-$100k/yr | Reduces `medical_cost` per fight by (skill/200) × $1500. Reduces injury recovery time by (skill/100) × 10% for the promo's injured fighters. |
| **Cutman** | `promotion_id` | $25k-$60k/yr | Reduces `doctor_stoppage` outcomes by (skill/300). Small boost to `show_rating.fan_rating` (better corner work = fewer bloody messes). |
| **General Manager** | `promotion_id` | $50k-$200k/yr | Reduces all expenses by (skill/1000) × total_expense (max 10% cost reduction). Boosts contract negotiation success rate (player gets better terms when renewing). |

### 4.2 Staff Attributes (per staff member)

Add a `skill_level` column (0-100) to `staff` table. Currently the only "skill" data lives in:
- `scout.specialty` JSON (`eye_for_talent`, `technical_analysis`, `character_reading`)
- `pundit_bias` JSON (NULL everywhere)

Proposed unified model:
```
staff.skill_level: 0-100 integer (overall competence)
staff.specialty: keep as JSON for role-specific attributes
  - scout: {eye_for_talent, technical_analysis, character_reading, mistake_rate, ...}
  - coach: {striking_focus, grappling_focus, cardio_focus, development_bonus}
  - commentator: {charisma, mma_knowledge, bias_style, bias_nationality}
  - doctor: {sports_medicine, recovery_speed, diagnostic_accuracy}
  - cutman: {hemostasis_speed, swelling_reduction}
  - general_manager: {negotiation, operations, scouting_network}
```

### 4.3 Hiring / Firing

#### 4.3.1 Staff Market Screen

A new screen (`Staff Market` / `Free Agent Staff`) that mirrors the existing Free Agents screen for fighters:
- Lists all `staff` rows where `promotion_id IS NULL` (and not retired/terminated).
- Filterable by role_type + skill_level + salary_ask.
- Each row shows: name, age, role, skill_level (as a voice-tier descriptor — "world-class" / "established" / "promising" / "unproven"), salary_ask, contract_length_ask.
- Click → "Make Offer" → modal with salary + signing_bonus + contract_length inputs → "Submit Offer" → if `salary ≥ salary_ask × 0.9` and `signing_bonus ≥ 0`, offer accepted.

#### 4.3.2 Hiring Pool Generation

New `staff_market` table (or use `staff` with `promotion_id IS NULL`):
- Seed 5-15 free-agent staff per role on world init.
- Regen: when a staff member is fired or retires, replace them in the market with a similar-tier new staff (mirroring the fighter regen system).
- Quality distribution: 5% elite (skill 80+), 20% established (60-79), 50% mid (40-59), 25% unproven (20-39).

#### 4.3.3 Firing Flow

From the Staff screen (Roster view):
- Select staff → "Release" button → confirmation modal → on confirm:
  - UPDATE `staff.promotion_id = NULL`
  - UPDATE `contracts.status = 'terminated'`
  - If terminated mid-contract: pay 50% of remaining salary as severance (one-time `staff_salary` finance_transactions row, negative).
  - **Morale consequence:** if player fires >2 staff in 30 days, remaining staff get a morale penalty (new `staff_morale` column or repurpose an existing mechanism). Fighter morale also dips if their favorite coach/corner is fired.

#### 4.3.4 Contract Renewal

When `contracts.end_date` approaches (within 60 days):
- Auto-fire a news item: "<staff> contract expiring soon."
- Player can offer a renewal via the Contracts screen.
- If the staff's skill has improved since signing, their salary_ask rises.
- If no renewal by `end_date`, staff becomes a free agent (back into the Staff Market pool).

### 4.4 Staff Development

Add slow skill growth over time:

```
On monthly TICK_ADVANCED (current_day % 30 == 0):
  For each active staff:
    skill_gain = rng.random() < 0.20 ? +1 : 0   # 20% chance per month, +1 skill
    if skill_gain:
      UPDATE staff SET skill_level = MIN(100, skill_level + 1)
    
    # Age-based decline (over 50)
    if staff.age > 50:
      skill_decline = rng.random() < 0.10 ? -1 : 0
      if skill_decline:
        UPDATE staff SET skill_level = MAX(20, skill_level - 1)
```

Slow enough to feel realistic (a 28-year-old coach can go from skill 50 to skill 80 over a 5-year career), but the player sees progression.

### 4.5 Assignment UIs

#### 4.5.1 Coach Assignment

In the Fighter Profile screen (or new Training Camps screen):
- Each fighter's gym shows the assigned coach.
- Player can reassign coaches between gyms (drag-and-drop or dropdown).
- A coach assigned to a fighter's gym boosts that fighter's camp quality.
- Limit: 1 coach per gym (or N fighters per coach — configurable).

#### 4.5.2 Scout Assignment

In the Scouting screen:
- Each scout has a "current_assignment" (already in the JSON specialty).
- Player clicks "Assign Scout" → picks a target fighter from Free Agents or rival rosters.
- After `n` sim days (per `scouting.py:_check_scouting_assignments`), a scouting_report is generated.
- Player can recall a scout early (lose partial progress).

#### 4.5.3 Doctor / Cutman / GM / Commentator

These are passive — they apply their effects automatically while under contract. No assignment UI needed.

---

## 5. Screens Needed

### 5.1 Finance Screen ("The Books")

**Purpose:** the player's financial dashboard. Replaces the current dashboard's tiny cash-line sparkline.

**Tabs:**
1. **Overview** — current cash, monthly burn rate, last-event P&L summary, projected next-event P&L, bankruptcy warning if cash < 2× monthly burn.
2. **Transactions** — paginated `finance_transactions` log with type filter (ticket_sales, broadcast_revenue, sponsorship, etc.) and date range.
3. **Broadcast Deals** — current deal summary + available deals to negotiate (see 5.2).
4. **Ticket Pricing** — default ticket price per venue_type + per-event override (see 5.5).
5. **Marketing Budget** — default monthly marketing allocation + per-event override.

**Data sources:** `finance_transactions`, `promotions`, `broadcast_contracts` (new), `events` (for upcoming P&L projection).

### 5.2 Broadcast Deals Sub-screen

**Purpose:** negotiate + sign broadcast deals.

**Layout:**
- Current deal card (if any): partner name, deal type (flat fee / PPV split / hybrid), per-event rights fee, PPV split %, deal expiry date.
- Available deals list: 3-5 partner offers, each with type + terms + tier requirements (e.g., "ESPN+ requires rep ≥ 70 for PPV split deal").
- "Negotiate" button on each: opens a modal with sliders for rights_fee vs split % (inverse trade-off), contract length, exclusivity flag.
- "Sign Deal" button → writes to `broadcast_contracts` table + news item.

**New schema:** extend `broadcast_contracts` to include `deal_type`, `rights_fee_per_event`, `ppv_split_pct`, `start_date`, `end_date`, `exclusivity_flag`. Drop the `staff_id` requirement (it was a vestigial design choice — broadcasters aren't staff).

### 5.3 Staff Screen ("The Team")

**Purpose:** view + manage the player's staff.

**Tabs:**
1. **Roster** — all staff under contract. Columns: name, role, skill (descriptor), age, salary, contract end, assignment (if applicable). Actions: Release (fire), Renew Contract, Assign (role-dependent).
2. **Staff Market** — free-agent staff for hire (mirrors Free Agents screen for fighters). Filter by role + skill tier. Action: Make Offer.
3. **Coaches** — special view: coaches grouped by gym. Drag-and-drop reassignment. Shows which fighters train at each gym.
4. **Scouts** — special view: scout assignments + target fighters + report ETA. Action: Assign to Target.

**Data sources:** `staff`, `staff_contracts`, `contracts`, `gyms` (for coach view), `scouting_reports` (for scout view).

### 5.4 Contracts Screen ("Deals")

**Purpose:** unified view of all contracts — fighter + staff.

**Tabs:**
1. **Fighter Contracts** — all signed fighters with their contract terms. Columns: fighter name, salary, win_bonus_pct (from `bonus_structure` JSON), contract end, status. Filter: expiring soon (≤60 days). Actions: Renew (opens negotiation modal), Release (voids contract, may pay severance), Trade (future).
2. **Staff Contracts** — all staff contracts. Same column structure. Same Renew/Release actions.
3. **Negotiations** — pending offers (outbound to free agents, inbound from fighters seeking renewal). Action: Accept / Reject / Counter.

**Data sources:** `contracts`, `fighter_contracts`, `staff_contracts`, `bonus_structure` JSON.

### 5.5 Event Builder — Financial Tab (extends existing Event Builder)

**Purpose:** per-event financial decisions made at scheduling time.

**Fields:**
- Venue picker (dropdown of available venues, sorted by capacity). Shows capacity + venue_type + rental cost preview.
- Ticket price slider ($20-$300). Shows projected fill rate + projected gate.
- Marketing budget slider ($0-$500k). Shows projected attendance boost + PPV buy boost.
- PPV toggle (if promo has PPV-capable broadcast deal). If on: PPV price slider ($30-$80) + projected buys.
- Projected P&L summary at the bottom: revenue (gate + broadcast + sponsor + merch + concessions) minus expenses (purses + staff + venue + marketing + insurance). Green if projected profit, red if loss.

**Data sources:** `venues`, `promotions`, `finance.py` (for projection formulas), `broadcast_contracts` (for PPV eligibility).

### 5.6 Screen Summary

| # | Screen | New? | Priority |
|---|---|---|---|
| 5.1 | Finance ("The Books") | ✅ New | Phase 6 |
| 5.2 | Broadcast Deals (sub-screen of Finance) | ✅ New | Phase 3 |
| 5.3 | Staff ("The Team") | ✅ New | Phase 4 |
| 5.4 | Contracts ("Deals") | ✅ New | Phase 6 |
| 5.5 | Event Builder — Financial tab | Extends existing | Phase 3 |

**Total: 5 screens (4 new + 1 extension).**

---

## 6. Implementation Phases

### Phase 1: Fix the broken finance system (1-2 days)

**Goal:** make `finance.py` actually fire when the player runs events from the GUI.

**Changes:**
1. **Code:** Add `from finance import register_subscribers as _register_finance; _register_finance()` to `src/app.py` (in the registration block, after `show_rating` per the existing comment about registration order — finance must run before reputation so the bankruptcy check can read the latest cash).
2. **Code:** Add `"finance"` to `src/app_web.py:registration_modules` list (line 86-91). Position: between `"show_rating"` and `"venues"` to preserve order.
3. **Code:** Add the same registration to `src/ui_legacy/app.py` (line 198-299).
4. **Code:** Change `finance.py:register_subscribers()` (line 281-289) to subscribe to `EVENT_COMPLETED` instead of `FIGHT_RESOLVED`. Remove the `if status != 'completed': return` early-exit guard at line 90-91 (no longer needed).
5. **Migration:** Backfill promo 1's missing finance_transactions for the 35 events in 2026 that were resolved without finance firing. New script `scripts/backfill_promo1_finance.py` that iterates promo 1's completed events since 2026-01-01 and calls `_process_event_finance` on each (the existing idempotency guard at line 94-100 will skip any that already have rows).

**Effort:** 1-2 dev-days.
**Dependencies:** None.
**Risk:** Low. The finance.py code already works for AI promos; we're just wiring it into the GUI app.

### Phase 2: Add revenue calculation from shows (gate + PPV + broadcast) (2-3 days)

**Goal:** replace the flat `_BROADCAST_REVENUE` lookup with a real PPV/broadcast model + fix the staff salary bug + add sponsorship/concessions.

**Changes:**
1. **Schema:** Add `venue_type` column to `venues` (migration `_migrate_v3_X_0_add_venue_type`). Backfill existing venues by capacity tier.
2. **Schema:** Add `broadcast_contracts` columns: `deal_type` ('flat_fee' | 'ppv_split' | 'hybrid'), `rights_fee_per_event` REAL, `ppv_split_pct` REAL (0-1), `start_date` TEXT, `end_date` TEXT, `exclusivity_flag` INTEGER. Make `staff_id` nullable (drop the NOTNULL).
3. **Code:** Rewrite `finance.py::_process_event_finance` revenue section:
   - Replace flat broadcast revenue with PPV buyrate calculation (per §3.1.2).
   - Add `sponsorship` row (per §3.1.3).
   - Replace merchandise formula with fan_trust-weighted version (per §3.1.4).
   - Add `concessions` row (per §3.1.5).
4. **Code:** Rewrite `finance.py::_process_event_finance` expense section:
   - Fix staff salary query: `SELECT COUNT(*) FROM staff s LEFT JOIN staff_contracts sc ON sc.staff_id=s.staff_id LEFT JOIN contracts c ON c.contract_id=sc.contract_id WHERE (s.promotion_id=? OR s.gym_id IN (SELECT gym_id FROM gyms WHERE city_id IN (SELECT city_id FROM cities WHERE region_id=(SELECT region_id FROM promotions WHERE promotion_id=?)))) AND c.status='active'` — or simpler, just sum `contracts.salary / 12` for all active staff_contracts where `c.promotion_id=?`.
   - Replace flat `_STAFF_SALARY_PER_EVENT` with monthly pro-rata: `salary / 12` per staff (assuming 1 event/month; if 2 events/month, split it).
   - Replace flat venue rental with venue_type-tiered cost.
   - Add insurance cost line.
   - Add win/finish/title/main_event bonuses to fighter purse calculation (read `contracts.bonus_structure` JSON).
5. **Code:** Subscribe `finance.py` to `TICK_ADVANCED` for monthly staff salary burn (when `current_day % 30 == 0`). This ensures promos pay staff even in months with 0 events.
6. **Tests:** Extend `scripts/test_finance.py` to cover the new revenue/expense formulas + the monthly tick.

**Effort:** 2-3 dev-days.
**Dependencies:** Phase 1 (finance must be wired first).
**Risk:** Medium. Schema change requires migration; revenue formula tuning needs balance testing.

### Phase 3: Add player financial levers (3-4 days)

**Goal:** give the player the 7 levers from §3.3.

**Changes:**
1. **Schema:** Add `ticket_price_override` REAL to `events` (nullable; defaults to the auto-computed value if NULL). Add `marketing_budget` REAL to `events` (nullable; defaults to 0). Add `ppv_price` REAL to `events` (nullable; only set for PPV events).
2. **Schema:** Add `default_ticket_price` REAL + `default_marketing_budget` REAL to `promotions` (player-set defaults, applied to new events unless overridden).
3. **Code:** Update `finance.py` to read `events.ticket_price_override` instead of computing `50 + market_heat × 2`. Apply price-elasticity penalty to fill_rate.
4. **Code:** Update `finance.py` to read `events.marketing_budget` and apply the marketing_boost to fill_rate + buyrate.
5. **Code:** Build broadcast deal negotiation logic in a new `src/services/broadcast_svc.py`:
   - `get_available_deals(promotion_id)` — returns 3-5 partner offers based on promo reputation + size_tier.
   - `negotiate_deal(promotion_id, partner_name, deal_type, rights_fee, ppv_split, length)` — returns success/failure based on partner willingness.
   - `sign_deal(...)` — writes to `broadcast_contracts` + sets `promotions.broadcast_tier` appropriately.
6. **Code:** Update `sign_free_agent` in `services/contracts.py` to accept `win_bonus_pct` + `signing_bonus` + `contract_length_days` parameters (currently just `salary`).
7. **Code:** Add `renew_contract(contract_id, new_salary, new_length, new_bonus_structure)` to `services/contracts.py`.
8. **UI:** Build the Broadcast Deals sub-screen (5.2) — initially in the web UI (`src/web/js/finance.js` + new HTML template) since that's the active UI per the migration plan.
9. **UI:** Add Financial tab to the Event Builder (5.5) — venue picker, ticket price slider, marketing slider, PPV toggle, projected P&L summary.

**Effort:** 3-4 dev-days.
**Dependencies:** Phase 2 (revenue formulas must exist before player can tune them).
**Risk:** Medium. UI work is the bulk; backend negotiation logic is straightforward.

### Phase 4: Build staff hiring/firing system (2-3 days)

**Goal:** make staff a real, signable, fireable layer.

**Changes:**
1. **Schema:** Add `skill_level` INTEGER (0-100) to `staff` (migration `_migrate_v3_X_0_add_staff_skill_level`). Backfill: random 20-80 for existing staff, weighted by role.
2. **Schema:** Add `salary_ask` REAL + `contract_length_ask` INTEGER to `staff` (used by free-agent staff in the market).
3. **Schema:** Give coaches `staff_contracts` rows (backfill — create a contract per coach at $30k-$80k based on inferred skill).
4. **Code:** Build `src/services/staff_svc.py`:
   - `get_staff_market(role_filter=None, skill_min=0)` — returns free-agent staff.
   - `make_offer(staff_id, promotion_id, salary, signing_bonus, length)` — accepts if `salary ≥ salary_ask × 0.9`; writes `staff_contracts` + `contracts` rows + `staff.promotion_id` + `signing_bonus` finance_transactions row.
   - `release_staff(staff_id, promotion_id)` — terminates contract, pays 50% severance if mid-contract.
   - `renew_staff_contract(staff_id, new_salary, new_length)`.
5. **Code:** Add staff regen to `tick_processor.py` (or new subscriber): when staff retire/quit, replace them in the market with a similar-tier new staff.
6. **UI:** Build the Staff screen (5.3) — Roster + Staff Market tabs in the web UI (`src/web/js/staff.js` + new HTML template). Mirror the Free Agents screen structure.

**Effort:** 2-3 dev-days.
**Dependencies:** None strictly (can be built in parallel with Phase 3).
**Risk:** Low. Mostly CRUD + a new screen.

### Phase 5: Wire staff effects to simulation (3-4 days)

**Goal:** make staff matter — coaches boost training, doctors reduce injuries, GMs cut costs, commentators boost ratings.

**Changes:**
1. **Schema:** Add `coach_id` INTEGER to `training_camps` (nullable; references `staff.staff_id` where `role_type='coach'`).
2. **Code:** Update `services/training_svc.py:progress_camps()`:
   - Read `training_camps.coach_id` (if set).
   - Read `staff.skill_level` for that coach.
   - Scale `attribute_changes` by `(0.5 + skill_level / 100)` — a 100-skill coach → 1.5× gains; a 0-skill coach → 0.5×.
   - Reduce `camp_injury_risk` by `(skill_level / 200)`.
3. **Code:** Update `finance.py` to apply doctor/cutman/GM effects:
   - Doctor: reduce `medical_cost` by `(doctor.skill_level / 200) × base_medical_cost`.
   - GM: reduce total expenses by `(gm.skill_level / 1000) × total_expenses` (max 10%).
4. **Code:** Update injury recovery (in `tick_processor.py:_check_injuries` or `services/injuries_svc.py`):
   - Reduce `injury.projected_return_date` by `(doctor.skill_level / 100) × 10%` if the promo has an active doctor.
5. **Code:** Update `show_rating.py:_compute_commercial_rating`:
   - Add commentator bonus: `+1 per 10 commentator skill_level` (max +10) for the promo's active commentators.
6. **Code:** Populate `pundit_bias` JSON for active commentators (in `staff_svc.py:make_offer` or via a backfill script). Wire `punditry.py` to read from `staff.pundit_bias` for active commentators (currently reads from nowhere — `broadcast_staff` is empty).
7. **Code:** Add staff skill development on monthly TICK_ADVANCED (per §4.4).
8. **Tests:** New `scripts/test_staff_effects.py` covering each role's effect.

**Effort:** 3-4 dev-days.
**Dependencies:** Phase 4 (staff system must exist before wiring effects). Phase 2 (finance.py must be the right place to apply doctor/GM effects).
**Risk:** Medium. Tuning the effect magnitudes will need playtesting.

### Phase 6: Build Finance + Contracts screens (2-3 days)

**Goal:** full UI for the financial + contract management layer.

**Changes:**
1. **UI:** Build the Finance screen (5.1) — Overview / Transactions / Broadcast Deals / Ticket Pricing / Marketing Budget tabs. New `src/web/js/finance.js` + HTML template + `src/web/css/finance.css`.
2. **UI:** Build the Contracts screen (5.4) — Fighter Contracts / Staff Contracts / Negotiations tabs. New `src/web/js/contracts.js` + HTML template.
3. **UI:** Add navigation buttons for Finance + Staff + Contracts to the main shell (extend `src/web/js/app.js` + `src/web/index.html`).
4. **Code:** Add `src/services/finance_svc.py` real implementations (currently it's a pure re-export wrapper):
   - `get_cash_summary(promotion_id)` — current cash, monthly burn, last-event P&L.
   - `get_transactions(promotion_id, limit=50, type_filter=None)` — paginated transaction log.
   - `project_event_pnl(event_id)` — projected P&L for an upcoming event (uses the formulas from finance.py without writing rows).
5. **Code:** Add bankruptcy logic to `reputation.py` (or new `src/services/bankruptcy_svc.py`):
   - On monthly TICK_ADVANCED: if `promotions.current_cash < 0` for 2 consecutive months, fire `PROMOTION_BANKRUPT` event.
   - Effects: reputation -10, fan_trust -15, all staff contracts voided, top 3 fighters request release.

**Effort:** 2-3 dev-days.
**Dependencies:** Phases 2 + 3 + 4 (the screens surface data those phases produce).
**Risk:** Low. Mostly UI work; backend already built in earlier phases.

### Phase Summary

| Phase | Goal | Effort | Deps |
|---|---|---|---|
| 1 | Fix finance wiring + backfill promo 1 | 1-2 days | None |
| 2 | Real revenue (gate + PPV + sponsor) + fix staff salary bug + monthly tick | 2-3 days | Phase 1 |
| 3 | Player financial levers (ticket price, marketing, broadcast negotiation, contract terms, venue picker) | 3-4 days | Phase 2 |
| 4 | Staff Market + hire/fire system + Staff screen | 2-3 days | None (parallel with 3) |
| 5 | Wire staff effects (coaches → training, doctors → injuries, GM → costs, commentators → ratings) | 3-4 days | Phases 2 + 4 |
| 6 | Finance + Contracts screens + bankruptcy logic | 2-3 days | Phases 2 + 3 + 4 |
| **Total** | | **13-19 dev-days** | |

### Recommended Sequencing

```
Week 1:  Phase 1 (1-2d) → Phase 2 (2-3d)              [fix + revenue model]
Week 2:  Phase 4 (2-3d, parallel) + Phase 3 (3-4d)    [staff system + player levers]
Week 3:  Phase 5 (3-4d) → Phase 6 (2-3d)              [wire effects + UI]
```

Total: ~3 dev-weeks for the complete economic + staff overhaul. Can ship Phase 1 + 2 as a "finance finally works" milestone first (end of week 1), then Phase 3 + 4 as a "player agency" milestone (end of week 2), then Phase 5 + 6 as a "polish + screens" milestone (end of week 3).

---

## 7. Risks + Open Questions

1. **Balance risk.** The PPV buyrate formula (§3.1.2) has many multipliers. Will need playtesting to ensure top-tier promos don't print money infinitely and regional promos don't go bankrupt instantly. Mitigation: ship with conservative defaults, add a `finance_balance_modifiers` JSON column on `promotions` for easy tuning.

2. **Coach linkage complexity.** Coaches are gym-bound but fighters train at gyms. Adding `coach_id` to `training_camps` is straightforward, but the UI for "assign coach to gym" + "fighter trains at gym X" + "coach Y is at gym X" has multiple hops. May need a dedicated Training Camps screen (deferred to Phase 7+).

3. **Sponsorship realism.** Real MMA sponsorships are per-fighter (Reebok/UFK deals) + per-promotion (banner ads). The proposed model is promo-level only. Per-fighter sponsorships would need a `fighter_sponsorships` table — deferred.

4. **Broadcast partner naming.** The proposed `broadcast_contracts.network_name` is free-text. Should we seed a fixed list of partners (ESPN+, DAZN, UFC Fight Pass, etc.)? Yes — add a `broadcast_partners` reference table in Phase 3.

5. **AI rival adaptation.** The rival AI's `budget_manager.py` + `staff_manager.py` already exist and work. They'll need updating to use the new revenue/expense formulas (currently they read the existing `finance_transactions` for burn-rate calculation). Phase 2's formula changes will ripple through the rival AI's budget state evaluation.

6. **Voice layer compliance (CONVENTIONS §14).** All new player-facing text (finance news, staff hire/fire news, broadcast deal announcements) must use voice descriptors, not raw numbers. The existing `_write_finance_news` in `finance.py` (line 226) sets the pattern — extend it for the new transaction types.

---

## 8. References

- `src/finance.py` — current finance system (290 lines)
- `src/services/finance_svc.py` — wrapper (25 lines, pure re-export)
- `src/show_rating.py` — show rating engine (640 lines, feeds commercial_rating)
- `src/venues.py` — market heat drift (235 lines)
- `src/build_db.py` — schema (lines 1375-1408 for staff, 1609-1623 for staff_contracts + broadcast_contracts, 2233-2248 for finance_transactions)
- `src/services/rival_ai/staff_manager.py` — AI staff hire/fire (476 lines)
- `src/services/rival_ai/budget_manager.py` — AI budget state
- `src/services/contracts.py` — fighter contract signing (327 lines)
- `src/scouting.py` — scout effect (only working staff effect)
- `src/app.py:330-587` — subscriber registration block (missing finance)
- `src/app_web.py:86-91` — registration_modules list (missing finance)
- `docs/TASK_6_0_PLAN.md` — explicitly defers finance to Task 6.10
- `docs/CONVENTIONS.md` — §13 Design Law, §14 Voice Layer, §15 Event Bus
- `docs/RIVAL_AI_ARCHITECTURE.md` — §3.5 staff manager design
