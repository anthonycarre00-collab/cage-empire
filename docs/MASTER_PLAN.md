> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — MASTER PLAN (Working Doc Index)

> **Status:** ACTIVE — this is the canonical planning index as of the
> pre-game bridge fix (commit 4e4a4aa). All future phases reference
> the documents listed below.
> **Maintained by:** Supervisor (main agent)
> **Last updated:** session following "start screen error4" fix.

---

## 0. Purpose of this document

This file is the **single index** that ties together every planning
doc, audit, and architecture note in `docs/`. Each downstream phase
of work MUST cite one or more of the documents listed in §2 as its
source of truth. If a phase requires something not covered by an
existing doc, a new doc is added here FIRST, then the phase is
planned against it.

This document supersedes any informal "next steps" sections at the
bottom of older docs. When in doubt, this file is authoritative.

---

## 1. Current state — what works, what doesn't

### 1.1 Working (verified live)

| Layer | State | Notes |
|---|---|---|
| **pywebview desktop shell** | ✅ Working | Native window, top bar + sidebar + screen container. |
| **Pre-game screen** | ✅ Working (after fix 4e4a4aa) | Bridge now correctly waits for `pywebviewready` event before invoking API methods. |
| **App shell navigation** | ✅ Working | 18-item sidebar, back-stack (cap 10), stale-screen tracking. |
| **Advance Day button** | ✅ Working | Calls Python `advance_day()`, refreshes active screen, marks others stale. |
| **Dashboard screen** | ✅ Working | 8 sections, live DB data, interpretation phrases. |
| **Roster screen** | ✅ Working | 9-column fighter table, filters, sort, pagination (60 fighters). |
| **Free Agents screen** | ✅ Working | 4,082 FAs, ceiling display, sticky sign bar, sign flow. |
| **Fighter Profile screen** | ✅ Working | Header + 6 tabs, collapsable StatBars, fights timeline. |
| **Interpretation layer** | ✅ Working | 8 modules, SHORT (≤25 char) + LONG variants, 224 short phrases, 40 show-rating descriptors, 36+ news templates. |
| **Rival AI** | ✅ Working | 4 archetypes, 7 decision modules, 6 imperfection mechanisms. |
| **Tick processor** | ✅ Working | Targeted interpretation pass (dirty fighters only), per-section dirty flags. 899ms→430ms after re-engineering. |
| **DB pruning service** | ✅ Working | Monthly cleanup of news/headlines/social/injuries. |
| **Save / Load** | ✅ Working | `save_game(name)` + `load_game(name)` + `list_saves()`. |

### 1.2 Known broken / missing (drives the upcoming phases)

| Issue | Severity | Source doc |
|---|---|---|
| **Finance service not registered in `app_web.py`** — promo 1 has 1 finance_transaction row despite 431 events. Rival promos have rows only because `run_sim_forward.py` registers `finance`. | 🔴 Critical | `docs/ECON_STAFF_PLAN.md` §0, §2 |
| **Staff system is dead weight** — 300 coaches have no contracts and no effect on training; 25 commentators have no `broadcast_staff` rows; 24 scouts have never been used (scouting_reports empty). | 🔴 Critical | `docs/ECON_STAFF_PLAN.md` §3 |
| **Player has zero financial levers** — ticket prices auto-computed, broadcast tier fixed, no marketing system, no contract negotiation (sign_free_agent uses hardcoded $50k). | 🔴 Critical | `docs/ECON_STAFF_PLAN.md` §0, §4 |
| **Agency reward is the weakest reward (3/10 on 3 of 4 screens)** — player decisions aren't acknowledged, no "echoes" of past bookings/signings/cuts. | 🟠 High | `docs/REWARD_REVIEW.md` §0, §1 |
| **14 of 18 screens are placeholders** — only Dashboard, Roster, Free Agents, Fighter Profile are wired. | 🟠 High | `docs/SCREEN_DATA_AUDIT.md`, `docs/NAV_BUTTONS_AUDIT.md` |
| **30 of 31 action buttons are wired but many return hardcoded values** — e.g. `sign_free_agent` ignores fighter market value. | 🟡 Medium | `docs/NAV_BUTTONS_AUDIT.md` §3 |

---

## 2. Canonical planning documents

These are the **working docs** for the upcoming phases. Each is the
single source of truth for its domain. New work in that domain MUST
consult the relevant doc before any code is written.

### 2.1 Vision + voice

| Document | Drives | Status |
|---|---|---|
| `docs/CAGE_EMPIRE_SOUL.md` | The 5 player fantasies. Every screen, phrase, and reward must reinforce one of these. | Reference (stable) |
| `docs/VOICE_ENFORCEMENT.md` | Claude's voice directive. Interpretation layer must obey. | Reference (stable) |
| `docs/REWARD_REVIEW.md` | GPT's 5 player rewards applied to each of the 4 built screens + the "every screen has a hook" principle + the "Echoes" data channel proposal. | **Active — drives Phase R** |

### 2.2 Architecture + audit

| Document | Drives | Status |
|---|---|---|
| `docs/PERF_ARCH_AUDIT.md` | Performance architecture (tick processor, dirty flags, interpretation pass). | Reference (stable) |
| `docs/RIVAL_AI_ARCHITECTURE.md` | Rival AI archetypes, decision modules, imperfection mechanisms. | Reference (stable) |
| `docs/UI_MIGRATION_PYWEBVIEW.md` | CustomTkinter → pywebview migration notes. | Reference (historical) |
| `docs/SCREEN_DATA_AUDIT.md` | Per-screen DB field + interpretation-layer inventory. | **Active — drives every screen build** |
| `docs/NAV_BUTTONS_AUDIT.md` | Per-screen nav, hyperlinks, action buttons, save/load. | **Active — drives every screen build** |

### 2.3 Economics + staff (the upcoming focus)

| Document | Drives | Status |
|---|---|---|
| `docs/ECON_STAFF_PLAN.md` | Financial model audit + 7 player levers + 5 new screens + 6-phase plan. | **Active — drives Phases E1–E6** |

---

## 3. Phase roadmap (working plan)

The phases below are the **canonical working plan**. Each phase cites
its source doc. Phases are not strictly sequential — a phase can be
paused to do another, but each phase's scope is fixed by its source
doc.

### Phase 0 — Pre-game bridge fix ✅ DONE (commit 4e4a4aa)

**Source:** (this doc, §1.2)
**Scope:** Fix the `Cannot read properties of undefined (reading 'apply')` error on the pre-game screen.
**Root cause:** `bridge.js` resolved `waitForApi()` the instant `window.pywebview.api` was truthy, but pywebview 6.x initializes `api` as `{}` and populates methods later via `_createApi()` + the `pywebviewready` event.
**Fix:** `waitForApi()` now waits for `pywebviewready` (preferred) + polls until `api.get_clock` is callable (fallback). `callPython()` defensively checks `typeof fn === 'function'` before `.apply()`.
**Done:** user can now launch the app and the pre-game screen will load promotions correctly.

### Phase R — Reward layer (Echoes + Ownership language) 🟡 NEXT

**Source:** `docs/REWARD_REVIEW.md`
**Scope (proposed):**
- Build the **`player_decisions` log table** — every player action (sign, cut, book, scout, hire staff) writes a row with `{decision_type, target_fighter_id, target_promo_id, decision_date, context_json}`.
- Build the **Echoes generator** — on Advance Day, pick 2-3 past decisions whose consequences are now visible (e.g. "Three months ago you cut Marcus Reyes. He just won the Pacific Rim title.").
- Surface Echoes on the Dashboard as a new section (between Fighter Watch and News Wire).
- Apply Ownership language across all 4 built screens ("Your Champion", "Record Under You", "Stable Pulse").
- Add small-reward generators on Advance Day (15 examples in §5 of REWARD_REVIEW.md).
**Estimated effort:** 4–5 dev-days.
**Why before econ:** The reward layer is screen-level + interpretation-layer work. It can be done in parallel with the econ wiring (Phase E1) without conflict. Doing it first also gives the player something to DO while econ is being fixed.

### Phase E1 — Fix finance wiring 🟡 PARALLEL-WITH-R

**Source:** `docs/ECON_STAFF_PLAN.md` §2
**Scope:**
- Add `finance.register_subscribers()` to `app_web.py::register_all_subscribers()`.
- Backfill promo 1's missing finance_transactions for the 431 events that have already happened (one-time script).
- Verify: after fix, every `advance_day` from the GUI writes ≥1 finance row per owned event.
**Estimated effort:** 1 dev-day.
**Why critical:** Without this, the entire Finance screen (Phase E6) would show $80M and never move. This is a 1-day fix that unblocks the entire econ track.

### Phase E2 — Real PPV/broadcast revenue model

**Source:** `docs/ECON_STAFF_PLAN.md` §3
**Scope:**
- Replace flat `broadcast_tier` lookup with: `gate = venue_cap × fill_rate × avg_ticket_price` + `ppv_revenue = buyrate × ppv_price × households` + `broadcast_rights = tier × fixed_fee`.
- Buyrate scales with card quality (main event star power + co-main + title fight bonus).
- Per-event variance: main event star power, fan_trust modifier, market_heat modifier.
- Sponsorship: recurring sponsor slots (banner, kit, title) tied to reputation tier.
**Estimated effort:** 3–4 dev-days.
**Depends on:** E1.

### Phase E3 — Player financial levers

**Source:** `docs/ECON_STAFF_PLAN.md` §4
**Scope:**
- Ticket pricing slider (low/standard/premium/VIP) → affects fill_rate inversely.
- Marketing spend slider ($0–$500k/event) → boosts market_heat (with diminishing returns).
- Broadcast negotiation (accept/reject PPV partner offers per event).
- Venue picker in Event Builder (small/mid/large/stadium → different caps + rental costs).
- Contract negotiation for `sign_free_agent` — replace hardcoded $50k with fighter market value × signing bonus % × contract length.
**Estimated effort:** 4–5 dev-days.
**Depends on:** E2.

### Phase E4 — Staff Market screen + hire/fire flows

**Source:** `docs/ECON_STAFF_PLAN.md` §5
**Scope:**
- New `Staff Market` screen (free-agent pool of coaches, scouts, doctors, cutmen, GMs, commentators).
- Hire flow: select staff → see salary demand → confirm → writes `staff_contracts` row + decrements promo cash.
- Fire flow: terminate contract → pay severance (50% of remaining) → frees roster spot.
- Assign flow: assign coach to gym, assign scout to region, assign doctor/cutman to active roster.
**Estimated effort:** 3–4 dev-days.
**Depends on:** E1 (so salaries actually hit finance).

### Phase E5 — Wire staff effects into simulation

**Source:** `docs/ECON_STAFF_PLAN.md` §6
**Scope:**
- Coaches: training camp quality → attribute development rate. Camp with no coach = -50% dev rate. Camp with elite coach = +25% dev rate + unlocks specialisation tracks.
- Scouts: scouting_reports actually populated. Scout quality determines report accuracy + reveal depth.
- Doctors: injury recovery time reduced by doctor skill (top doctor = -40% recovery time).
- Cutmen: cut/stoppage probability reduced on fight night.
- GMs: overhead cost reduction (better GM = lower day-to-day operating cost).
- Commentators: show_rating bonus on events they work (top commentator = +5% show_rating).
**Estimated effort:** 5–6 dev-days.
**Depends on:** E4.

### Phase E6 — Finance ("The Books") + Contracts ("Deals") screens

**Source:** `docs/ECON_STAFF_PLAN.md` §7, `docs/SCREEN_DATA_AUDIT.md`
**Scope:**
- Finance screen: 4 sections (cash flow statement, last event P&L, salary breakdown, projected next-month outlook).
- Contracts screen: list of all fighter contracts (expiry, salary, status) + staff contracts + negotiations queue.
- Both screens follow the Dashboard visual pattern (color-coded section headers, voice phrases, no raw numbers where a phrase exists).
**Estimated effort:** 4–5 dev-days.
**Depends on:** E2, E3, E4.

### Phase S — Remaining 14 screens (placeholder replacement)

**Source:** `docs/SCREEN_DATA_AUDIT.md`, `docs/NAV_BUTTONS_AUDIT.md`
**Scope:** Replace placeholder screens with full implementations:
- HOME: Calendar (Schedule), The Wire (News).
- FIGHTERS: Scouting, Legends (Hall of Fame).
- EVENTS: Build a Card (Event Builder), Matchmaking, Fight Night (Fight Resolution), The Archive (Past Events).
- BUSINESS: The Books (Finance), Deals (Contracts), The Competition (Rival Promotions), Training Camps (Gyms).
- WORLD: The Rankings, Belts (Titles), Bad Blood (Rivalries), The Record Book (Records).
**Estimated effort:** 12–18 dev-days (screen-by-screen, parallelisable in batches of 3–4).
**Depends on:** Phase R (for reward hooks), Phase E1 (for any finance-related screen), E4 (for Staff Market).

---

## 4. Working rules for future phases

1. **Always cite the source doc.** Every phase's first commit message MUST name the doc(s) it implements.
2. **No code without a doc.** If a phase needs something not in any existing doc, write the doc first, add it to §2 of this file, then start coding.
3. **One fix per commit when feasible.** Bridge timing bugs, finance wiring, reward hooks — each is its own commit so bisects stay clean.
4. **Interpretation layer is the voice.** Every number that has a phrase in `fighter_descriptors` or `daily_headlines` MUST be displayed as the phrase, not the number. New screens must follow this rule.
5. **Player decisions are logged.** Once Phase R ships, every player action writes a `player_decisions` row. New actions added in later phases MUST also log.
6. **Test before sign-off.** Each phase ends with: (a) VLM screenshot review, (b) `python -m pytest scripts/test_*.py` green, (c) user-facing summary in `worklog.md`.

---

## 5. What the user should do next

1. **Test the pre-game fix.** Run `PLAY.bat` (Windows) or `./run.sh` (Mac/Linux). Pre-game should now load 10 promotion cards. Pick one → Dashboard should render.
2. **Read the two key planning docs:**
   - `docs/REWARD_REVIEW.md` — the reward layer plan (Phase R).
   - `docs/ECON_STAFF_PLAN.md` — the econ + staff plan (Phases E1–E6).
3. **Approve or amend the phase order.** The default order is R → E1 (parallel) → E2 → E3 → E4 → E5 → E6 → S. If the user wants a different order (e.g. finance first because they want to feel the money pressure), say so before work starts.
4. **After approval, work begins on Phase R + E1 in parallel.** Both are scoped in their source docs.
