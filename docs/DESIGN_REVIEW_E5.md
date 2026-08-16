> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Design Review: Coaches, Bankruptcy, Attribute Realism, Financial Balance

> **Status:** ACTIVE — design review for 5 user points before Phase E5.
> **Supervisor:** main agent.

---

## 0. User directives

1. **Remove coaches from staff list** — promotions don't coach fighters; fighters choose gyms (personality-driven). Coaches belong to gyms, not promos.
2. **Bankruptcy recovery** — promotions that go bankrupt should "come back to life" under new owners/shareholders, not permanently die.
3. **Attribute gains realistic** — over time/age/career, with variables (personality profiles) determining whether any fighter hits their potential ceiling. Not every fighter should reach peak.
4. **Finances balanced** — not too finicky, not too easy, not too hard. MMA shows and fighters are the star; finances are flavour.

---

## 1. Coaches — remove from staff market, reassign to gym system

### Current state
- 300 coaches in DB: 200 free-agent (just freed for Staff Market), 100 gym-bound.
- Staff Market screen (Phase E4) shows 200 free-agent coaches as hireable.
- `tick_processor._complete_training_camp` has a `coach_mult` variable but it's hardcoded to 1.0 (no coach effect wired).

### Design decision
**Coaches are NOT promo staff.** In real MMA, fighters choose which gym to train at — the gym has coaches, not the promotion. The promo's role is to sign fighters, book fights, and run shows. Coaches are part of the gym ecosystem.

### Changes
1. **Remove coaches from Staff Market** — filter them out of `get_staff_market_data`. The Staff Market only shows scouts, doctors, cutmen, GMs, commentators (5 roles, not 6).
2. **Reassign the 200 free-agent coaches back to gyms** — they were orphaned; give them `gym_id` again (random gym assignment). They're part of the gym ecosystem, not hireable by promos.
3. **Gym quality affects training** — the gym's `facility_quality` + `development_focus` already scale attribute gains via `gym_spec_mult`. The coach at the gym should contribute to this — a gym with a world-class coach has higher effective `development_focus`.
4. **Fighter chooses gym** — this is a personality-driven decision (future phase: fighter AI picks gym based on style fit + personality + gym reputation). For now, fighters stay at their current gym; the player can't hire/fire coaches.

### Implementation
- `src/app_web.py::get_staff_market_data` — add `WHERE role_type != 'coach'` filter.
- `data/cage_empire.db` — reassign 200 free-agent coaches to random gyms (UPDATE staff SET gym_id = random gym WHERE promotion_id IS NULL AND role_type='coach').
- `src/web/js/staff_market.js` — remove "Coach" from the role filter dropdown.
- `docs/` — update staff system docs to reflect coaches are gym-bound, not promo staff.

---

## 2. Bankruptcy recovery — "new ownership" mechanism

### Current state
- Bankruptcy fires when `current_cash < 0` for 2 consecutive monthly ticks.
- Effects: rep -10, trust -15, staff contracts voided, top 3 fighters released, cash reset to $1M.
- No narrative recovery mechanism — just a cash injection.

### Design decision
**Promotions don't die — they get acquired.** A bankrupt promotion is bought by new ownership (consortium, wealthy investor, rival promo's parent company). The brand survives but with changes.

### Changes
1. **Bankruptcy event fires** — same as now (cash < 0 for 2 months).
2. **"New Ownership" news item** — voice-compliant narrative:
   - "FINANCIAL COLLAPSE: [Promo Name] files for bankruptcy protection. New ownership group takes control."
   - "A consortium of investors has acquired [Promo Name] out of receivership. The brand survives; the rebuild begins."
3. **Recovery effects** (instead of just $1M cash reset):
   - Cash reset to `starting_budget × 0.25` (25% of original — enough to operate but not splurge). For promo 1: $80M × 0.25 = $20M recovery fund.
   - Reputation -15 (was -10 — new owners are unknown, trust is lower).
   - Fan trust -20 (was -15 — fans are wary of new ownership).
   - All staff contracts voided (they leave — new regime, new staff).
   - Top 3 fighters (by salary) request release → become free agents.
   - 3-5 random fighters leave (uncertainty about new ownership).
   - Brand name stays the same (the IP has value).
   - A "rebuilding" flag is set for 6 months (news items reference the rebuild).
4. **Rebuilding period** — for 6 sim-months after bankruptcy:
   - News items reference the rebuild: "[Promo Name] continues its rebuild under new ownership."
   - Reputation recovers slowly (+1 per month during rebuild if the promo runs events successfully).
   - After 6 months, the "rebuilding" flag clears.

### Implementation
- `src/reputation.py::_check_bankruptcy_failure` — update the recovery logic.
- `src/reputation.py` — add `_REBUILDING_PERIOD_MONTHS = 6` constant.
- `src/news.py` — add "new ownership" + "rebuilding" news templates.
- `data/cage_empire.db` — add `is_rebuilding` column to promotions (INTEGER, default 0) + `rebuilding_until_date` (TEXT).

---

## 3. Attribute gain realism — "realization" variable

### Current state
- `effective_ceiling = potential × age_factor × health_factor`
- `personality_factor = (discipline + coachability) / 200` scales the GAIN RATE, not the ceiling.
- Every fighter CAN reach their effective_ceiling if they train enough.
- This is unrealistic — some prospects bust, some exceed expectations.

### Design decision
**Not every fighter hits their potential.** A "realization factor" determines how close a fighter gets to their theoretical potential. This is set at fighter creation (personality-driven) and represents the fighter's ability to translate potential into actual skill.

### Changes
1. **New `realization` column** on `fighter_career` (REAL 0.0-1.0, default 0.7).
   - Represents the % of potential the fighter will actually reach.
   - 0.7 = reaches 70% of potential (a "bust" if potential was 85 → ceiling becomes 60).
   - 1.0 = reaches 100% of potential (a "realizer" — rare).
   - 0.5 = reaches 50% (a major bust).
2. **Realization is set at fighter creation** based on personality:
   - Base: 0.7 (most fighters reach 70% of potential)
   - +0.1 if discipline ≥ 70 (hard workers realize more)
   - +0.1 if coachability ≥ 70 (coachable fighters realize more)
   - +0.05 if professionalism ≥ 70 (dedicated pros realize more)
   - -0.1 if ego ≥ 70 (big egos bust more)
   - -0.1 if risk_taking ≥ 80 (reckless fighters bust more)
   - -0.05 if attention_seeking ≥ 70 (distraction)
   - Clamp to [0.4, 1.0] — no one realizes less than 40% or more than 100%
3. **Effective ceiling formula update**:
   ```python
   effective_ceiling = int(potential * age_factor * health_factor * realization)
   ```
   - A fighter with potential=85, realization=0.7, age=25, health=100: ceiling = 85 × 1.0 × 1.0 × 0.7 = 59 (not 85)
   - A fighter with potential=85, realization=1.0, age=25, health=100: ceiling = 85 (the full potential — rare)
   - A fighter with potential=85, realization=0.5, age=25, health=100: ceiling = 42 (a bust)
4. **Realization is hidden** — the player can't see it directly. They infer it from:
   - Training camp results (a fighter with low realization stops growing early)
   - Career trajectory (a "bust" prospect plateaus while a "realizer" keeps climbing)
   - Scouting reports (future: scouts estimate realization with noise)

### Implementation
- `src/build_db.py` — migration v3.23.0 adds `realization` column to fighter_career. Backfill based on personality.
- `src/tick_processor.py` — update effective_ceiling formula to include realization.
- `src/app_web.py::_compute_attribute_trajectory` — update to match.

---

## 4. Financial balance — tune down PPV, tune up expenses

### Current state
- Promo 1 (ppv_global) nets $23M per event (revenue $23.4M, expenses $270k).
- Starting cash $80M → after 1 event $103M.
- This is too easy — the player gets rich fast with no pressure.

### Design decision
**Finances are flavour, not the star.** The player should feel economic pressure but not be overwhelmed. Target: a well-run promo nets $1-5M per event (not $23M). A poorly-run promo can lose money. Bankruptcy is a real threat if you over-spend.

### Changes
1. **PPV buys — reduce base buyrate**:
   - `ppv_global` base: 250k → 100k (was too high for a new promo)
   - `ppv_streaming` base: 50k → 25k
   - The player builds up to higher buyrates via reputation + fan_trust over time, not from day 1.
2. **PPV split — reduce player share**:
   - Default: 60% → 50% (broadcast partners take a bigger cut)
3. **Fighter purses — increase**:
   - Base purse: salary/12 → salary/6 (fighters paid twice as much per event — more realistic)
   - Main event bonus: $10k → $50k
   - Title fight bonus: $25k → $100k
   - Win bonus: 50% → 75% of base purse
4. **Staff salary — increase**:
   - Per-event pro-rating: salary/12 → salary/8 (staff paid more per event)
5. **Venue rental — increase**:
   - Cost per seat: arena $7→$10, ballroom $5→$7, theater $4→$5, outdoor $3→$4
6. **Insurance + medical — increase**:
   - Per-fight medical: $1.5k → $3k
   - Event liability: $5k → $10k
7. **Marketing — make it more impactful but more expensive**:
   - Marketing boost to fill: cap 30% → 20% (diminishing returns hit harder)
   - Marketing multiplier to buys: cap 2× → 1.5×
8. **Sponsorship — reduce**:
   - Base sponsor pool: reduce by 30% across all tiers

### Target balance after tuning
- **Mid-tier promo** (rep=60, trust=60, regional TV, 8k venue, $80 ticket, $50k marketing):
  - Revenue: ~$500k (gate $448k + broadcast $75k + sponsor $50k + merch $30k + concessions $84k)
  - Expenses: ~$300k (purses $150k + staff $50k + venue $56k + marketing $50k + insurance $34k)
  - Net: ~$200k (was $500k — tighter but still profitable)
- **Top-tier PPV promo** (rep=90, trust=80, PPV global, 18k arena, $200 ticket, $250k marketing, $60 PPV):
  - Revenue: ~$8M (gate $3.3M + PPV $4M + sponsor $500k + merch $130k + concessions $248k)
  - Expenses: ~$2M (purses $1.2M + staff $150k + venue $180k + marketing $250k + insurance $46k)
  - Net: ~$6M (was $23M — still very profitable but not absurd)

### Implementation
- `src/finance.py` — tune the constants + formulas.
- `src/app_web.py::get_event_preview` — mirror the tuned formulas.
- `scripts/test_finance_e3.py` — update balance targets.
- Run sim-forward 90 days, verify promo 1 doesn't explode to $500M.

---

## 5. Phase E5 — Wire staff effects (NO coaches)

### Scope (updated — coaches removed)
- **Scouts** → scouting report accuracy (already wired in scouting.py, needs player UI to assign scouts to targets — future phase)
- **Doctors** → injury recovery time reduction (skill/200 × 10% reduction)
- **Cutmen** → cut/stoppage probability reduction (skill/300 reduction)
- **GMs** → overhead cost reduction (skill/1000 × total_expense, max 10%) + better contract negotiation success
- **Commentators** → show_rating bonus (+1 per 10 skill points, max +10)

### NOT in scope
- Coaches (removed from promo staff — gym ecosystem only)
- Training camp quality (gym facility_quality + development_focus already handle this)

### Implementation
- `src/finance.py` — GM cost reduction in _process_event_finance.
- `src/services/injuries_svc.py` — doctor recovery time reduction.
- `src/services/fight_engine.py` — cutman stoppage reduction.
- `src/show_rating.py` — commentator bonus.
- `scripts/test_staff_effects.py` (NEW) — verify each staff effect fires correctly.

---

## 6. Implementation order

1. **Fix 1: Remove coaches from staff market** — DB update + filter + UI. 1 commit.
2. **Fix 2: Bankruptcy recovery** — new ownership mechanism + rebuilding period. 1 commit.
3. **Fix 3: Realization variable** — schema migration + formula update + backfill. 1 commit.
4. **Fix 4: Financial balance tuning** — tune constants + formulas. 1 commit.
5. **Phase E5: Staff effects** — doctors, cutmen, GMs, commentators. 1-2 commits.
6. **Tests + verification + push.**

---

## 7. Acceptance criteria

- [ ] Coaches removed from Staff Market (filter + UI)
- [ ] 200 free-agent coaches reassigned to gyms
- [ ] Bankruptcy recovery = "new ownership" narrative + 25% starting_budget cash + rebuilding period
- [ ] Realization column added to fighter_career, backfilled from personality
- [ ] effective_ceiling formula includes realization
- [ ] Not every fighter hits potential (sample: 20 fighters, verify ~30% have realization < 0.7)
- [ ] Financial balance: mid-tier nets ~$200-500k, top-tier PPV nets ~$5-8M (not $23M)
- [ ] Staff effects wired: doctors, cutmen, GMs, commentators (NOT coaches)
- [ ] All tests pass
- [ ] No regressions
