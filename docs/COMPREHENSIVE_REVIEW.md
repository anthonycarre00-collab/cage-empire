> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Comprehensive Review (August 2026)

> **Date:** August 13, 2026
> **Latest commit:** `a7e6185` (Aug 10, 2026)
> **Schema:** v3.26.0 (37 migrations, 63 tables)
> **Codebase:** ~10,978 lines backend (app_web.py) + ~12,444 lines frontend (16 JS files) + ~6,900 lines interpretation layer + 51 test files
> **Reviewers:** Supervisor (main agent) + 4 research subagents

---

## 0. Executive Summary

CAGE EMPIRE has built a **deeper, more story-rich simulation than WMMA5** — but WMMA5 ships more of its simulation to the player. The work that remains is mostly **wiring, not new systems**.

**Scorecard:**
- **12 of 19 sidebar screens wired** (63%)
- **7 placeholder screens remain** (37%)
- **5 of 5 core fantasies have at least partial implementation** — but 4 of 5 have placeholder screens blocking the player from reaching rich backends
- **Critical bug:** Finance system is broken in production (EVENT_COMPLETED not firing during sim advance → zero new finance rows, zero show ratings, zero injuries from fights)
- **Backend richness:** 56 API methods, 6 interpretation engines, 7-axis rival AI, memory resurfacing, echoes, career arcs, realization variable, bankruptcy recovery, staff effects
- **Frontend polish:** Matchmaking V2 (3-column, might advice, confirm flow), Fight Night (4-zone live play-by-play), Calendar, Staff Market, 4 info screens

---

## 1. What Works (wired + functional)

| Screen | Status | Key Features |
|---|---|---|
| **The Empire** (Dashboard) | ✅ Full | Echoes, bidding alerts, upcoming cards, fighter watch, champions, recent results, news |
| **Calendar** | ✅ Full | Month grid, player + rival events, conflict warnings, date picker |
| **The Wire** (News) | ✅ Full | Topic filters, search, 16 filter groups, sentiment |
| **The Stable** (Roster) | ✅ Full | 9-column table, filters (WC/gender/stage), sort, pagination, promo logo |
| **Open Market** (Free Agents) | ✅ Full | Ceiling display, negotiation panel (salary/bonus/length/win_bonus), acceptance indicator |
| **Stack a Card** (Event Builder) | ✅ Full | Name → date → venue → business end, quick pick, financial levers with elasticity |
| **Matchmaking** | ✅ Full V2 | 3-column layout, 9 fighter info fields, might advice, card confirm flow, drag-drop, 4 modals |
| **Fight Night** | ✅ Full | 4-zone live play-by-play, pre-fight build-up, post-fight recap, speed controls, cancel |
| **The Archive** (Past Events) | ✅ Full | Event list with card results, show ratings, replay button |
| **Staff Market** | ✅ Full | 5 roles (no coaches), hire modal with negotiation, skill voice phrases |
| **The Competition** (Rival Promos) | ✅ Full | 9 rival promo cards, view rival rosters (read-only) |
| **The Rankings** | ✅ Full | Top 15 per WC, contracted-to column, promo toggle, champion strip |
| **Belts** (Titles) | ✅ Full | All titles across promos, champion portraits, reign phrases |
| **Fighter Profile** | ✅ Full | 6 tabs, 26 attribute StatBars with trajectory chips, fights timeline, your history |
| **Calendar** | ✅ Full | Month grid, conflict warnings |

## 2. What's Missing (placeholders)

| Screen | Nav ID | Backend Status | Effort |
|---|---|---|---|
| **Scouting** | `scouting` | ✅ `scouting.py` + `scouting_svc.py` exist, `scouting_reports` table empty | Low — wire existing backend to UI |
| **Legends** (HoF) | `hall_of_fame` | ✅ `hof_svc.py` exists, 2 HoF members in DB | Low — wire existing backend |
| **The Books** (Finance) | `finance` | ❌ No `get_finance_data` API method | Medium — build API + UI |
| **Deals** (Contracts) | `contracts` | ❌ No `get_contracts_data` API method | Medium — build API + UI |
| **Training Camps** (Gyms) | `gyms` | ✅ `training_svc.py` exists, `training_camps` table has data | Low — wire existing backend |
| **Bad Blood** (Rivalries) | `rivalries` | ✅ `rivalries.py` (1,052 lines), 390 rivalries in DB | Low — wire existing backend |
| **The Record Book** | `records` | ❌ No backend | Medium — build from scratch |

**Plus 1 dark system:** `agent_offers.py` (893 lines — the Talent Hunter's mystery-box gamble where agents offer you unknown fighters) exists but has NO Api wrapper, NO bridge method, NO UI.

---

## 3. Critical Bugs (must fix before building new screens)

### BUG #1: Finance system broken in production (CRITICAL)
- **Symptom:** Only 10 finance_transactions rows in the DB (all from 2026-01-01 seed). Zero new rows from 1,715 completed events.
- **Root cause:** `EVENT_COMPLETED` is not being published when events transition to 'completed' during sim advance. The event bus subscriber for finance never fires.
- **Impact:** No revenue/expenses tracked, no show ratings computed, no injuries from fights, no finance news. The entire economic loop is broken.
- **Also broken:** `show_ratings` table has rows only from manual test fires, not from sim. Injury generation from fights is not happening (0 active injuries).

### BUG #2: Promo 7 stuck in bankruptcy rebuild (MEDIUM)
- **Symptom:** `is_rebuilding=1` for 141 days past `rebuilding_until_date`.
- **Impact:** The rebuild-clearing logic in `reputation.py` isn't firing.

### BUG #3: Duplicate bankruptcy news (LOW)
- **Symptom:** 9 duplicate "FINANCIAL COLLAPSE" news items for Promo 2.
- **Impact:** News spam.

### BUG #4: Social posts future-dated (LOW)
- **Symptom:** 1,043 `social_posts` with `post_date > sim_date`.
- **Impact:** Same root cause as the future-dated-rows bug that was cleaned up — `run_sim_forward.py` writes future data.

### BUG #5: Fight result type imbalance (MEDIUM)
- **Symptom:** KO/TKO = 12% (should be 25-35%), Submission = 37% (should be 10-20%).
- **Impact:** Fights end too often by submission, not enough KOs. Less exciting.

### BUG #6: `tapping_up_rumor` news spam (LOW)
- **Symptom:** 1,598 items in 7 days (~228/day).
- **Impact:** News wire flooded with tapping-up rumors.

---

## 4. CAGE EMPIRE vs WMMA5

### Where CAGE EMPIRE is BETTER

| Feature | Why we're better |
|---|---|
| **Live P&L projection during card building** | WMMA5 books blind — no revenue/expense preview. CE shows a range with voice phrases. |
| **Visual matchup tools** | CE has radar chart Compare, Tale of Tape, What's at Stake, Fan Pulse modals. WMMA5 is text-only. |
| **Calendar integration** | CE has month grid with rival events + conflict warnings. WMMA5 has separate calendar. |
| **"Might" advice** | CE gives no definitive predictions. WMMA5 shows predicted winner. |
| **4-zone Fight Night** | CE has cage heatmap, damage silhouettes, commentary feed, pundit panel. WMMA5 is flat text. |
| **Interpretation layer** | 6 engines (context, career_phase, narrative, memory, headline, legacy) + echoes. WMMA5 has none. |
| **Memory resurfacing** | "Met earlier this year — won by submission." WMMA5 doesn't surface history. |
| **Rival AI depth** | 7-axis decision system, 4 archetypes, 6 imperfection mechanisms, player-facing bidding wars. |
| **Realization variable** | Not every fighter hits their potential — personality-driven. WMMA5 has no equivalent. |
| **Player financial levers** | Ticket price, marketing, PPV price with elasticity. WMMA5 has none. |
| **Bankruptcy recovery** | "New ownership" narrative with rebuilding period. WMMA5 just resets cash. |
| **Staff effects** | Doctors (recovery), Cutmen (stoppage), GMs (cost), Commentators (show rating). |

### Where WMMA5 is still BETTER

| Feature | Why they're better |
|---|---|
| **Finance screen** | WMMA5 has a full finance dashboard. CE has none (placeholder). |
| **Scouting screen** | WMMA5 has scouting with uncertain reports. CE has backend but no UI. |
| **HoF / Legends** | WMMA5 has a rich HoF. CE has 2 members + no screen. |
| **Record Book** | WMMA5 has all-time records. CE has nothing. |
| **Rivalries screen** | WMMA5 shows rivalry history + heat. CE has 390 rivalries but no screen. |
| **Hype slider** | WMMA5 lets you hype fights for risk/reward. CE doesn't have this. |
| **Booking Adviser** | WMMA5 surfaces opportunities (hometown fighter, #1 contender). CE doesn't. |
| **Inducements** | WMMA5 has per-fight personality-driven extra-cost demands. CE doesn't. |
| **Replacement Offers** | WMMA5 has fighters self-offering to step in on short notice. CE doesn't. |
| **Event Disruption** | WMMA5 penalizes late card changes. CE doesn't. |
| **Commentary variety** | WMMA5 has richer prose. CE has 7 fixed templates per beat type. |
| **Save/Load UI** | WMMA5 has visible save slots. CE has API but no UI affordance. |
| **Agent Offers** | WMMA5 has agents offering unknown fighters. CE has 893 lines of code but no UI. |

---

## 5. Phase Status (plans vs reality)

| Phase | Plan | Status |
|---|---|---|
| Phase 0 | Bridge fix | ✅ Done |
| Phase R | Reward layer (Echoes, player_decisions) | ✅ Done |
| Phase E1 | Finance wiring | ✅ Done (but broken in production — BUG #1) |
| Phase E2 | PPV/broadcast model | ✅ Done |
| Phase E3 | Player financial levers | ✅ Done |
| Phase E4 | Staff Market screen | ✅ Done |
| Phase E5 | Staff effects | ✅ Done |
| **Phase E6** | **Finance + Contracts screens** | **❌ NOT STARTED** |
| CR-1..4 | Promo name, trajectory, gender, filters | ✅ Done |
| CR-5..9 | Dashboard fixes, roster logo, Competition screen | ✅ Done |
| CR-10..14 | Training camp fix, fight engine, career phase, bugs, bios | ✅ Done |
| M1..M4 | Fighter gen, staff lifecycle, rival AI bidding, matchmaking | ✅ Done |
| MM1..MM4 | Matchmaking V2, calendar, availability, balance | ✅ Done (MM3/MM4 partial) |
| P1..P6 | Quick fixes, financial balance, Fight Night, rankings, audit | ✅ Done (some issues remain) |
| F1..F2 | Financial model + advance day | ✅ Done |

---

## 6. Recommended Next Steps (priority order)

### P0: Fix critical finance bug (1-2 days)
- **BUG #1:** `EVENT_COMPLETED` not firing during sim advance. This is the #1 blocker — without it, the entire economic loop is broken. No revenue, no show ratings, no injuries, no finance news.
- Also fix: BUG #2 (promo 7 stuck in rebuild), BUG #6 (tapping_up_rumor spam)

### P1: Wire the 4 missing core-fantasy screens (3-4 days)
These screens have full backends but no UI:
1. **Scouting** — `scouting.py` + `scouting_svc.py` exist. Wire to UI. (Talent Hunter fantasy)
2. **Bad Blood** (Rivalries) — `rivalries.py` (1,052 lines), 390 rivalries in DB. Wire to UI. (Puppet Master fantasy)
3. **Legends** (HoF) — `hof_svc.py` exists, 2 members. Wire to UI. (Historian fantasy)
4. **Training Camps** (Gyms) — `training_svc.py` exists, training_camps table has data. Wire to UI. (Growth fantasy)

### P2: Build Finance + Contracts screens (Phase E6) (4-5 days)
- **The Books** (Finance) — cash flow, P&L, salary breakdown, projected outlook
- **Deals** (Contracts) — fighter + staff contracts, expiry, negotiation queue
- These are the Empire Builder fantasy's payoff screens

### P3: Expose agent_offers to UI (2 days)
- `agent_offers.py` (893 lines) — the Talent Hunter's mystery-box gamble
- Agents offer you unknown fighters — you decide whether to sign based on limited info
- Highest dopamine-per-line-of-code: the backend is done, just needs UI

### P4: Build Record Book screen (2 days)
- All-time records (most wins, most KOs, longest reign, etc.)
- No backend exists — build from scratch
- Historian fantasy payoff

### P5: Add WMMA5-style matchmaking features (3-4 days)
- Hype slider (risk/reward for promoting fights)
- Booking Adviser (surface opportunities, not auto-book)
- Inducements (personality-driven extra-cost demands)
- Replacement Offers (fighters self-offer on short notice)

### P6: Polish + balance (ongoing)
- Commentary variety (more templates per beat type)
- Fight result type imbalance (KO/TKO too low, submission too high)
- Rival AI card thickness (avg 2.5 fights, should be 5-8)
- Save/Load UI affordance (visible save slots)
- News variety (still some repetitive headlines)

---

## 7. The One-Sentence Verdict

**CAGE EMPIRE has built a deeper, more story-rich simulation than WMMA5 — but WMMA5 ships more of its simulation to the player. Wire the 7 placeholder screens + fix the finance bug + expose agent_offers, and CAGE EMPIRE becomes the better game across the board. The work that remains is mostly wiring, not new systems.**
