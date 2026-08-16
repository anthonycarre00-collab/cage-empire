> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Plans vs. Reality Review

> **Status:** READ-ONLY research report. No code was changed.
> **Author:** Research subagent (Explore mode)
> **Method:** Read every `docs/` planning doc + git log (last 100 commits) +
> `src/app_web.py` API surface + `src/web/js/app.js` nav wiring +
> `agent-ctx/` task records + `worklog.md` (last 250 lines) +
> `CHANGELOG.md` (top + bottom).
> **Project root:** `/home/z/my-project/cage_empire/`
> **Latest commit:** `a7e6185` — 2026-08-10 — *"fix: date format (day-of-year→day-of-month) + upcoming cards on dashboard + skip-to-show fix"*
> **Working tree:** clean (nothing uncommitted)

---

## 0. Headline Finding

The project has shipped roughly **70% of what was planned**, but two
significant gaps remain:

1. **The worklog and CHANGELOG are stale.** Both stop mid-July at the
   UI-REDESIGN-P2.5 sign-off (CTk customtkinter dashboard rewrite).
   Everything from the **pywebview migration onward** (Aug 4–10:
   Staff Market, Matchmaking V2, Calendar, Fight Night, The Wire,
   Archive, Rankings, Belts, Rival Promotions, COMPREHENSIVE_FIX_PLAN
   P1–P6, FINANCES_ADVANCEDAY F1–F2, 6 fix-rounds of user feedback) is
   undocumented in the worklog/CHANGELOG. The only audit trail for the
   last 2–3 weeks of work is the git commit messages + the
   `agent-ctx/*.md` task briefs.
2. **Phase E6 (Finance/Books + Contracts/Deals screens) was never
   built**, along with 6 other placeholder screens. The dashboard
   surfaces money + the matchmaking screen previews revenue, but the
   player has no dedicated Finance screen + no Contracts screen —
   the two screens the ECON_STAFF_PLAN explicitly calls for as the
   "Business" payoff of the entire econ track.

The last 4 commits (all Aug 10) are all bug-fixes the user found in
testing. The user is actively testing but the last test round
uncovered date-format corruption, "no way to see events again after
leaving matchmaking", and a future-dated-rows bug that left only 2
fighters eligible for matchmaking.

---

## 1. Timeline (what was built when)

Git-log reconstruction (commit dates are 2026-08-04 through 2026-08-10).
The worklog has NO entries for any of this — last worklog entry is
`UI-REDESIGN-P2.5-SIGNOFF` (line 13530, around late July).

| Date | Phase | Commits | What shipped |
|---|---|---|---|
| 2026-08-04 | E4 + F3 | `7f8d799`, `b35aadf` | Staff Market screen (schema v3.22.0) + Event Builder UX |
| 2026-08-04 | E5 + design | `9397c65`, `e826dbb` | DESIGN_REVIEW_E5 implemented: remove coaches from staff market, add `realization` variable, bankruptcy recovery (new ownership), staff effects wired (doctors/cutmen/GMs/commentators) |
| 2026-08-05 | M1 | `b5f1620` | Fighter gen base 50→37 + realization migration v3.24.0 |
| 2026-08-05 | M2 | `33fb725`, `5c424c2` | Staff aging + retirement |
| 2026-08-05 | M3 | `1fdcd28`, `a611669`, `0e7e057`, `a31d060` | Rival AI bidding wars (player now competes) + fair-value formula includes realization |
| 2026-08-05 | M4 | `ee3ba0c`, `4effe81` | Matchmaking screen (3-column) + event builder integration + `project_card_draw` replaces hardcoded 1.2 |
| 2026-08-05 | M4 test | `bccf1ee`, `fe8d7e4` | 30-day sim-forward aliveness test + punditry fix |
| 2026-08-08 | MM1 | `09823d0`, `6243fbf`, `f3853d9` | Matchmaking V2 full rewrite — BIG two-row layout + 9 fields per corner + "might" advice (no easy-mode predictions) + card-confirm flow + drag-drop |
| 2026-08-08 | MM2 | `0d7f3e8` | Calendar screen (month grid + player + rival events + conflict warnings) |
| 2026-08-08 | MM3+MM4 | `0820f1b`, `76594b7` | Fighter availability fixes + bidding war tone-down + balance sweep + rival AI follows same availability rules |
| 2026-08-08 | Fight Night | `c02c10d`, `c2709a2`, `a053c16` | FN.1 backend per-beat commentary API + FN.2 Fight Night screen (4-zone live play-by-play) + FN.3 nav wiring |
| 2026-08-08 | INFO screens | `9bc8b58`, `17fcc6e`, `1a4a323`, `987ffcb` | The Wire (news) + The Archive + The Rankings + Belts (titles) |
| 2026-08-08 | COMPREHENSIVE_FIX_PLAN | `ddf9a75` | 27-issue plan authored |
| 2026-08-08 | P1 | `5323a6b` | Quick fixes: bidding alert 3 max + echoes rephrase + title bar day + matchmaking scroll |
| 2026-08-08 | P2 | `e1a9234`, `2f98e62` | Stack a Card redesign (name→date→venue→levers) + financial balance (price elasticity, FOTN/KO/Sub bonuses) |
| 2026-08-08 | P3 | `0885f83`, `1da9d4b`, `00053a3` | Fight Night: debug resolve + reverse order + "Watch the Show" gating + commentary improvements + player reward |
| 2026-08-08 | P4 | `9f61346`, `0f172de` | Rankings tiebreaker + champions fix + archive cleanup + show rating weights |
| 2026-08-08 | P6 | `9e78933` | 3-month sim audit (issues flagged — see §3 below) |
| 2026-08-08 | Balance | `ad6a90f` | Rest period 21→90 days, bankruptcy less harsh, champions fixed (again), news variety, memory verified |
| 2026-08-10 | F1 | `bbe2098` | Financial model — show quality drives post-event revenue (±30% on PPV+merch) + purses 30–40% + preview shows RANGE not single number |
| 2026-08-10 | F2 | `600fef9` | Min card size enforcement + Sim Week + Skip to Show + processing overlay + promo growth (great +3 / good +1 / dud -2 / terrible -4) |
| 2026-08-10 | pre-push | `ffc435b` | Clear player_promotion_id for fresh start + fighter snapshot 3s→10s + PPV elasticity strengthened |
| 2026-08-10 | test-feedback | `b8f0878` | Venue default US + quick-pick variety + matchmaking auto-reopen + sim cancel + better bios |
| 2026-08-10 | test-feedback | `815923e` | Cancel button works (1-day-at-a-time sim) + confirmed card layout + force new game |
| 2026-08-10 | cleanup | `3433085` | **CRITICAL FIX** — clean up 28 696 future-dated rows left over from the 3-month sim audit + rest period 90→60 days |
| 2026-08-10 | LATEST | `a7e6185` | Date format fix (was showing "June 353, 2027") + upcoming cards on dashboard + skip-to-show cleanup |

The progression is: pywebview migration (July) → ECON/STAFF fixes
(E1–E5, July–Aug) → Matchmaking plan M1–M4 (Aug 4–5) → Matchmaking
V2 plan MM1–MM4 (Aug 8) → Fight Night (Aug 8) → Info screens batch
(Aug 8) → COMPREHENSIVE_FIX_PLAN P1–P6 (Aug 8) → FINANCES_ADVANCEDAY
F1–F2 (Aug 10) → 4 rounds of user-feedback fixes (Aug 10).

---

## 2. Phase Status — planned vs. implemented

### 2.1 `docs/MASTER_PLAN.md` (canonical roadmap)

| Phase | Plan summary | Status | Evidence |
|---|---|---|---|
| **Phase 0** | Pre-game bridge fix (`Cannot read properties of undefined`) | ✅ DONE | commit `4e4a4aa` |
| **Phase R** | Echoes data channel + `player_decisions` log + Ownership language | ✅ DONE | `src/interpretation/echoes_engine.py` (748 lines) + `src/player_decisions.py` (444 lines) + backfill wired into `app_web.py:1862-1878`. Echoes rephrase "since his release" landed in P1 (`5323a6b`). |
| **Phase E1** | Fix finance wiring (register `finance.register_subscribers()`) | ✅ DONE | `src/app_web.py:78-127` `register_all_subscribers()` includes `"finance"` in the registration_modules list (line 96). Comment cites "Phase E1.1 (docs/ECON_STAFF_PLAN.md §0 + §1.5 bug #1)". |
| **Phase E2** | Real PPV/broadcast revenue model (replace flat lookup) | ✅ DONE | commits `97531c8`–`881a6dc` (Aug 4). Verified in `src/finance.py` (1 360 lines). |
| **Phase E3** | Player financial levers (ticket slider, marketing, PPV toggle, venue picker, contract negotiation) | ✅ DONE | commits `b88af5a`, `254da35`, `7e644cc`, `f2455be`, `f6a08d8` (Aug 3–4). Event Builder screen (`event_builder.js`, 1 269 lines) + Sign Free Agent contract sliders. |
| **Phase E4** | Staff Market screen (hire/fire/assign flows) | ✅ DONE | commit `7f8d799` (Aug 4). Schema v3.22.0. `staff_market.js` (721 lines) + `get_staff_market_data` in `app_web.py:8041`. |
| **Phase E5** | Wire staff effects (doctors/cutmen/GMs/commentators — NOT coaches) | ✅ DONE | commit `e826dbb` (Aug 4). Verified in code: `finance.py:1084-1131` (GM savings), `services/injuries_svc.py:48` `get_doctor_recovery_bonus`, `services/fight_engine.py:1204-1251` `_get_cutman_stoppage_bonus`, `show_rating.py` commentator bonus. |
| **Phase E6** | Finance ("The Books") + Contracts ("Deals") screens | ❌ **NOT STARTED** | No `finance.js` / `contracts.js` files exist. `get_finance_data` / `get_contracts_data` methods NOT in `app_web.py`. Both screens are still using the `PLACEHOLDER_PHRASES` fallback in `app.js:713-720`. The Books nav item (`app.js:47`) → placeholder. Deals nav item (`app.js:48`) → placeholder. |
| **Phase S** | Replace remaining 14 placeholder screens | 🟡 **PARTIAL — 7 of 14 done** | See §2.2 below. |

### 2.2 Phase S — placeholder screens breakdown

`src/web/js/app.js:29-59` defines 19 nav items across 5 groups. Of
those, **14 are wired** (have a JS module + an API method) and **7 are
still placeholders** using the `PLACEHOLDER_PHRASES` fallback
(`app.js:703-721`):

| Group | Nav ID | Wired? | Renderer |
|---|---|---|---|
| HOME | dashboard | ✅ | `dashboard.js` (739 lines) |
| HOME | schedule (Calendar) | ✅ | `calendar.js` (514 lines) — built MM2 |
| HOME | news (The Wire) | ✅ | `wire.js` (380 lines) — INFO-SCREENS-BATCH-1 |
| FIGHTERS | roster (The Stable) | ✅ | `roster.js` (443 lines) |
| FIGHTERS | free_agents (Open Market) | ✅ | `free_agents.js` (970 lines) |
| FIGHTERS | scouting | ❌ | placeholder ("The scouts are waiting") |
| FIGHTERS | hall_of_fame (Legends) | ❌ | placeholder ("Legends never die") |
| EVENTS | event_builder (Stack a Card) | ✅ | `event_builder.js` (1 269 lines) |
| EVENTS | matchmaking | ✅ | `matchmaking.js` (1 963 lines) — MM1 V2 rewrite |
| EVENTS | past_events (The Archive) | ✅ | `archive.js` (555 lines) — INFO-SCREENS-BATCH-1 |
| EVENTS | fight_resolution (Fight Night) | ✅ | `fight_night.js` (1 410 lines) — FIGHT-NIGHT-SHOWCASE |
| BUSINESS | finance (The Books) | ❌ | placeholder ("The books are open") — Phase E6 gap |
| BUSINESS | contracts (Deals) | ❌ | placeholder ("No deals on the table") — Phase E6 gap |
| BUSINESS | staff_market | ✅ | `staff_market.js` (721 lines) — Phase E4 |
| BUSINESS | rival_promotions (The Competition) | ✅ | `rival_promotions.js` (484 lines) — CR-9 |
| BUSINESS | gyms (Training Camps) | ❌ | placeholder ("Training camps are ready") |
| WORLD | rankings | ✅ | `rankings.js` (396 lines) — INFO-SCREENS-BATCH-1 |
| WORLD | titles (Belts) | ✅ | `titles.js` (341 lines) — INFO-SCREENS-BATCH-1 |
| WORLD | rivalries (Bad Blood) | ❌ | placeholder ("No bad blood brewing") |
| WORLD | records (The Record Book) | ❌ | placeholder ("The record book is open") |

**14 wired + 7 placeholders = 21 nav items** (one extra is
`fighter_profile` which is a destination, not a sidebar item — accessed
via fighter name hyperlinks).

**The 7 still-placeholder screens are:**
1. **Scouting** — planned in `docs/SCREEN_DATA_AUDIT.md` + ECON_STAFF_PLAN
2. **Legends / Hall of Fame** — `hof_svc.py` exists (writes HoF rows),
   but no UI screen reads them
3. **The Books (Finance)** — Phase E6 gap. The entire econ track's
   payoff screen is missing
4. **Deals (Contracts)** — Phase E6 gap. Contract negotiation lives in
   `sign_free_agent` (E3) but no browse/manage screen exists
5. **Training Camps (Gyms)** — backend (`src/services/training_svc.py`
   exists) but no UI
6. **Bad Blood (Rivalries)** — backend (`src/rivalries.py`,
   `services/rivalries_svc.py` exist) but no UI
7. **The Record Book (Records)** — no obvious backend; would need a
   new query layer

### 2.3 `docs/MASTER_PLAN_MATCHMAKING.md` (M1–M5)

| Phase | Plan | Status |
|---|---|---|
| **M1** | Fighter gen fix (base 50→37) + realization migration | ✅ DONE — commit `b5f1620`, migration v3.24.0 |
| **M2** | Staff lifecycle (aging + retirement + regen + contract expiry) | ✅ DONE — commits `33fb725`, `5c424c2`, `f9de5ab` |
| **M3** | Rival AI bidding wars (player competes) + fair-value w/ realization | ✅ DONE — commits `1fdcd28`, `a611669`, `0e7e057`, `a31d060` |
| **M4** | Matchmaking screen (3-column) + `project_card_draw` replaces hardcoded 1.2 | ✅ DONE — commits `ee3ba0c`, `4effe81` |
| **M5** | Polish + balance (card health checklist, suggested matchups, voice phrases, balance tuning) | 🟡 PARTIAL — superseded by MM1 V2 rewrite before M5 could ship. Most of MM1's deliverables overlap M5. |

### 2.4 `docs/MASTER_PLAN_MATCHMAKING_V2.md` (MM1–MM4)

| Phase | Plan | Status |
|---|---|---|
| **MM1** | Matchmaking V2 — BIG two-row layout + 9 fields + might advice + confirm flow + drag-drop | ✅ DONE — commits `09823d0`, `6243fbf`, `f3853d9`. Verified `matchmaking.js` is 1 963 lines, `confirm_card` API exists at `app_web.py:4536`, `_compute_might_analysis` removes `predicted_winner`/`confidence_pct`/`upset_risk`. |
| **MM2** | Calendar screen + date picker + conflict warnings | ✅ DONE — commit `0d7f3e8`, `calendar.js` (514 lines) |
| **MM3** | Fighter availability fixes (cross-event booking, training camp requirement, last-minute rejection, re-validation at book_fight time) | 🟡 PARTIAL — commit `0820f1b` "fighter availability fixes + bidding war tone-down + balance sweep". Cross-event + re-validation confirmed. Training-camp requirement + personality-based last-minute rejection: not explicitly verified, the commit message doesn't list them. **Flagged for follow-up.** |
| **MM4** | Balance sweep (bidding war news frequency, "left promotion but still contracted" bug, news consistency audit) | 🟡 PARTIAL — bidding war tone-down confirmed. "Left promotion but still contracted" bug: not explicitly mentioned in any commit message. **Flagged for follow-up.** |

### 2.5 `docs/COMPREHENSIVE_FIX_PLAN.md` (27 issues, P1–P6)

| Phase | Plan | Status |
|---|---|---|
| **P1** | Quick fixes: bidding alert 3 max + echoes rephrase + title bar day + matchmaking scroll | ✅ DONE — commit `5323a6b` |
| **P2** | Stack a Card redesign + financial balance (price elasticity, PPV elasticity, FOTN/KO/Sub bonuses, fighter salaries) | ✅ DONE — commits `e1a9234`, `2f98e62` |
| **P3** | Fight Night: debug resolve + reverse order + "Watch the Show" gating + commentary improvements + player reward | ✅ DONE — commits `0885f83`, `1da9d4b`, `00053a3` |
| **P4** | Rankings + champions fix + archive cleanup + show rating weights | ✅ DONE — commits `9f61346`, `0f172de` |
| **P5** | News diversity audit + pruning check + show-rating-to-news wiring | 🟡 PARTIAL — show rating → news wired (`0f172de`). News variety improved via INTERP-EXPAND-V2 (already in CHANGELOG). However the P6 audit found "51× 'event highly profitable' duplicates" — finance-news variety still thin. **Flagged for follow-up.** |
| **P6** | 3-month sim + full world audit | ✅ DONE — commit `9e78933`. Audit ran, 7 issues flagged (see §3.1). |

### 2.6 `docs/FIX_PLAN_FINANCES_ADVANCEDAY.md` (F1–F2)

| Phase | Plan | Status |
|---|---|---|
| **F1** | Show quality drives post-event revenue (±30% on PPV+merch) + fighter purses 30–40% + preview shows RANGE | ✅ DONE — commit `bbe2098`. `agent-ctx/F1-F2-FINANCES-ADVANCEDAY-GROWTH.md` confirms all 9 acceptance criteria met. **Deviation noted (D6):** the 30–40% purse target is only fully achievable on mid-tier cards; PPV-tier cards land at 10–15% (per real-world UFC economics) — supervisor accepted this as realistic. |
| **F2** | Min card size + Sim Week + Skip to Show + processing overlay + promo growth/decay 4-tier | ✅ DONE — commit `600fef9`. |

### 2.7 `docs/DESIGN_REVIEW_E5.md` (5 design points)

| # | Plan | Status |
|---|---|---|
| 1 | Remove coaches from staff market (coaches are gym-bound, not promo staff) | ✅ DONE — commit `9397c65` |
| 2 | Bankruptcy recovery = "new ownership" mechanism + rebuilding period | ✅ DONE — commit `e826dbb`. (Note: later commit `ad6a90f` "bankruptcy less harsh" suggests tuning was needed post-ship.) |
| 3 | Realization variable (personality-driven, hidden, scales effective_ceiling) | ✅ DONE — commits `9397c65`, `b5f1620`. Migration v3.23.0 + 3.24.0. |
| 4 | Financial balance tuning (PPV buys down, purses up, expenses up) | ✅ DONE — commits `2f98e62`, `e1a9234`. Further tuned in `ad6a90f` (Aug 8) + `bbe2098` (Aug 10, F1). |
| 5 | Phase E5 — staff effects (doctors, cutmen, GMs, commentators — NOT coaches) | ✅ DONE — commit `e826dbb` |

### 2.8 `docs/CR1_4_PLAN.md` (CR-1..4 — User Feedback Round 1)

| # | Plan | Status |
|---|---|---|
| CR-1 | Replace "your promotion" with actual promo name (dashboard + fighter_profile) | ✅ DONE — verified `dashboard.js` + `fighter_profile.js` use `promo_name` |
| CR-2 | Attribute progress/decay trajectory chips (5 states green→red) | ✅ DONE — verified `_compute_attribute_trajectory` in `app_web.py`. Re-tuned in CR-10 (`1aa25b5`). |
| CR-3 | Gender separation (WC dropdown optgroups + correct pronouns) | ✅ DONE — verified |
| CR-4 | Open Market filters/sort/search (scouting-safe ceiling sort) | ✅ DONE — verified `free_agents.js` (970 lines) |

### 2.9 `docs/CR5_9_PLAN.md` (CR-5..9 — User Feedback Round 2)

| # | Plan | Status |
|---|---|---|
| CR-5 | Dashboard "Who's Making Moves" — filter to player's promo | ✅ DONE |
| CR-6 | Dashboard "Cards You've Run" — limit to 3 + filter to player's promo | ✅ DONE |
| CR-7 | Roster promo logo + weight distribution gender toggle (default male) | ✅ DONE |
| CR-8 | Fighter Profile Career tab "BELTS HE'S WON FOR YOU" → "BELTS WON" | ✅ DONE |
| CR-9 | NEW: "The Competition" screen (rival promos list + view rival roster) | ✅ DONE — `rival_promotions.js` (484 lines) + `get_rival_promotions` + `get_rival_roster` in `app_web.py:2905, 2953` |

### 2.10 `docs/CR10_14_FIX_PLAN.md` (CR-10..14 — 5 critical DB audit fixes)

| # | Plan | Status |
|---|---|---|
| CR-10 | Training-camp effective_ceiling fix (remove personality_factor from ceiling, move to gain multiplier; re-seed attrs down 15) | ✅ DONE — commits `9edbb75`, `1aa25b5`, `db118d5`, `f6aa461`. Migration v3.20.0. |
| CR-11 | Fight engine doctor-stoppage fix (raise thresholds, cut rate from 54% to ~5-8%) | ✅ DONE — commits `4e1dc30`, `567e66b`. New constants: BASE 200→400, SCALE 2→3, DIFF 50→100. |
| CR-12 | Career-phase pyramid rebalance (relax thresholds) | ✅ DONE — commits `32c8c2b`, `afc2166`. |
| CR-13 | Runtime bugs: `_small_reward_12` TypeError + `_write_drug_scandal_marker` NOT NULL | ✅ DONE — commits `14a9eb5`, `57df1df`. |
| CR-14 | Bio regeneration (regenerate all 4 464 bios to match DB records) | ✅ DONE — commits `1cc1e38`, `0d9f454`, `efb8993`. `scripts/regenerate_fighter_bios.py` + `verify_bios.py` created. |

### 2.11 Other planning docs (audit / reference)

| Doc | Purpose | Used? |
|---|---|---|
| `docs/REWARD_REVIEW.md` | GPT's 5 player rewards applied per screen + Echoes channel proposal | ✅ Drove Phase R — implemented |
| `docs/ECON_STAFF_PLAN.md` | Financial + staff audit, 7 player levers, 5 new screens, 6-phase plan | ✅ Drove E1–E5 (E6 NOT done) |
| `docs/SCREEN_DATA_AUDIT.md` | Per-screen DB field + interpretation inventory | ✅ Drove every screen build |
| `docs/NAV_BUTTONS_AUDIT.md` | Per-screen nav/hyperlinks/action buttons | ✅ Drove every screen build |
| `docs/CAGE_EMPIRE_SOUL.md` | The 5 core fantasies (prime directive) | ✅ Reference — cited in every phase's commit messages |
| `docs/CONVENTIONS.md` §13-14 | Design Law (5 pillars) + Interpretation Layer (no raw numbers) | ✅ Enforced — interpretation layer routes through `voice.py` + descriptors |
| `docs/DB_REVIEW_AUDIT.md` | 90-day sim audit found 5 critical issues | ✅ Drove CR-10..14 |
| `docs/REPLAN_RESET.md` + `docs/REPLAN_GAP_ANALYSIS.md` | Earlier reset planning (frozen world diagnosis) | ✅ Drove the sim-forward + cache rebuild fixes (these landed before the worklog's last entry) |
| `docs/RESEARCH_FIGHT_NIGHT.md` | Fight Night research | ✅ Drove FIGHT-NIGHT-SHOWCASE |
| `docs/RESEARCH_MATCHMAKING_*.md` (3 files) | Matchmaking research | ✅ Drove MASTER_PLAN_MATCHMAKING + V2 |
| `docs/RESEARCH_FIGHTERGEN_RIVALAI_STAFFLIFE.md` | Fighter gen + rival AI + staff lifecycle research | ✅ Drove M1–M3 |
| `docs/RESEARCH_WMMA5_MATCHMAKING.md` + `docs/RESEARCH_WMMA5_FM_V2.md` | WMMA5 comparison | ✅ Referenced |
| `docs/POTENTIAL_VS_ABILITY.md` | Design doc on realization | ✅ Drove CR-10 + realization variable |
| `docs/PERF_ARCH_AUDIT.md`, `docs/SCHEMA_ARCHITECTURE_v2.2.0.md`, `docs/SCHEMA_DRIFT_AUDIT.md`, `docs/STAGE3_EXPANSION_PLAN.md`, `docs/STAGE3_FORENSIC_ANALYSIS.md`, `docs/EXISTING_SYSTEMS_AUDIT.md`, `docs/FULL_BUILD_AUDIT.md` | Older audits/plans | 📚 Historical — predates the current Phase R/E/S/M era |

---

## 3. Known Issues — unfixed bugs + flagged follow-ups

### 3.1 Issues flagged in the 3-month sim audit (commit `9e78933`, Aug 8)

The supervisor ran a 90-day sim-forward + world audit and explicitly
flagged these 7 issues for follow-up:

| # | Issue | Severity | Current state |
|---|---|---|---|
| 1 | Champions still have bad attributes (power=30-44, iq=25-43) — `fix_champions` script didn't take on these specific titleholders | 🟠 HIGH | NOT FIXED — no commit between Aug 8 (audit) and Aug 10 (latest) addresses this. `9f61346` (champions fix) was BEFORE the audit, so the audit caught residual bad champions. **Still open.** |
| 2 | Some fighters fighting 20-23 times in 90 days (2.5/week) — rest period may be too short or not enforced | 🟠 HIGH | PARTIALLY FIXED — rest period was changed 21→90 (commit `ad6a90f` Aug 8), then 90→60 (commit `3433085` Aug 10). 60 days = ~6 fights/year max. But the audit's complaint was 20-23 fights in 90 days, which means 60-day rest wouldn't fully prevent it. **Verify.** |
| 3 | Avg fights per event = 2.5 (should be 5-8) — rival AI cards too thin | 🟠 HIGH | PARTIALLY FIXED — F2 (`600fef9` Aug 10) added min card size enforcement for the PLAYER. Rival AI cards: not explicitly fixed. The min-card-size check is in `confirm_card`, which only the player calls. **Still open for rival AI.** |
| 4 | Duplicate news headlines (51× "event highly profitable") — news templates too repetitive for finance events | 🟡 MEDIUM | NOT FIXED — INTERP-EXPAND-V2 expanded fight-news + show-rating-news variety (already in CHANGELOG), but finance-event news templates (e.g. "event highly profitable") were NOT expanded. **Still open.** |
| 5 | Staff avg age unchanged (48.7) — annual tick (Jan 1) hasn't crossed | 🟡 LOW | PARTIALLY FIXED — M2 (`33fb725`, `5c424c2` Aug 5) wired staff aging on annual tick. The audit ran before enough sim-time had crossed Jan 1. **Verify after a sim-year crosses.** |
| 6 | Promo 7 (Nordic) nearly broke (47k) + promo 10 (French) 97k — heading toward bankruptcy | ✅ N/A | Flagged as "correct behavior" — bankruptcy is intended. Bankruptcy recovery ("new ownership") wired in E5. |
| 7 | Promo 1 (player) cash unchanged at 0M — player hasn't run events | ✅ N/A | Flagged as "expected — this is sim-forward, not player-driven". |

### 3.2 Issues from the future-dated-rows cleanup (commit `3433085`, Aug 10)

The 3-month sim audit (`9e78933`) wrote future-dated rows (fight_history,
injuries, events, news, finance_transactions, training_camps — 28 696
rows total). The DB was then reset to the pre-sim backup while the
future-dated rows remained. This caused:

- All 50 fighters had `last_fight_date` in 2027 (future) → rest period
  check thought they fought recently → ineligible
- 38 injuries had `start_date` in 2027 (future) → "active" injuries for
  fighters who hadn't actually fought yet
- Result: only 2 fighters eligible for matchmaking

This was CLEANED UP in `3433085` (deletes 28 696 rows + recomputes
fighter records from remaining fight_history). However, **the root
cause was never fixed** — any future sim-forward that doesn't rollback
its data will re-introduce the same bug. **Flagged for follow-up:**
the `run_sim_forward.py` script needs to either (a) rollback on
completion, or (b) be marked as "destructive — backup first".

### 3.3 Issues fixed in the last 4 commits (Aug 10) — user found these in testing

These came from the user testing rounds AFTER the F1/F2 ship:

1. **`ffc435b`** — pre-push fix: clear `player_promotion_id` for fresh
   game start (kept being stale from previous test sessions)
2. **`b8f0878`** — 5 test-feedback fixes:
   - Venue filter defaults to United States (was index 0 = "All")
   - Quick-pick venue excludes already-selected + random from top 5
     (was always the same venue)
   - Matchmaking auto-reopens roster after adding a fight (user
     couldn't figure out they needed to pick new fighters for the
     second fight — "button greyed out")
   - Sim cancel button added + Skip-to-Show no-event handling
   - Better fighter bios on processing screen
3. **`815923e`** — cancel button works (1-day-at-a-time sim loop instead
   of a single 7-day synchronous call) + confirmed card layout fix +
   force new game
4. **`a7e6185`** — date format fix (was showing "June 353, 2027" because
   `current_day` is day-of-YEAR not day-of-month) + upcoming cards on
   dashboard (user: "no way to see events again once you leave
   matchmaking") + skip-to-show cleanup

### 3.4 Phase MM3/MM4 partial completion

Per `docs/MASTER_PLAN_MATCHMAKING_V2.md` §3-4:

| Planned | Done? |
|---|---|
| Cross-event booking check (can't double-book a fighter within ±7 days) | 🟡 not explicitly verified — `0820f1b` commit message says "fighter availability fixes" generically |
| Training camp requirement (fighters need camp, shown as warning if < 21 days out) | ❌ not mentioned in any commit |
| Last-minute rejection based on personality (< 14 days out, high professionalism rejects) | ❌ not mentioned in any commit |
| Re-validation at book_fight time | 🟡 not explicitly verified |
| Bidding war news frequency tone-down (max 1/7 days, potential ≥ 60 only) | ✅ done — `0820f1b` |
| "Left promotion but still contracted" bug fix | ❌ not mentioned in any commit — **still open** |

### 3.5 Phase E6 — never started

The Finance ("The Books") and Contracts ("Deals") screens were the
explicit payoff of the entire ECON_STAFF track. They were never built.
The player can:

- ✅ See the cash + reputation + fan trust on the Dashboard (top bar
  + 5 StatTiles)
- ✅ See a RANGE projection for upcoming events (Stack a Card /
  Matchmaking preview)
- ✅ Tweak financial levers (ticket price, marketing, PPV) in the
  Event Builder
- ✅ Negotiate fighter contracts in the Sign Free Agent modal
- ❌ Browse all finance transactions over time
- ❌ See a P&L breakdown per event (post-event actuals vs projection)
- ❌ See a salary breakdown across the roster
- ❌ See projected next-month outlook
- ❌ Browse all fighter/staff contracts + expiry
- ❌ See a negotiations queue

### 3.6 Stale documentation

- `worklog.md` (at `/home/z/my-project/worklog.md`, NOT in
  `cage_empire/`) — last entry is `UI-REDESIGN-P2.5-SIGNOFF` from
  late July. The entire pywebview migration + 7 phases of work since
  then are missing.
- `CHANGELOG.md` (at `cage_empire/CHANGELOG.md`) — top "Unreleased"
  section's most recent entry is `INTERP-EXPAND-V2` from late July.
  None of the August work (E4, E5, M1-M5, MM1-MM4, Fight Night, Info
  screens, P1-P6, F1-F2, CR fixes) is in the CHANGELOG.
- The git commit messages + `agent-ctx/*.md` task briefs are the only
  audit trail for August work.

---

## 4. User's Last Complaints (still-broken last test round)

The latest 4 commits (all Aug 10) are all user-feedback fixes. Reading
the commit messages tells us what the user complained about in their
most recent test session:

### 4.1 From commit `a7e6185` (latest, Aug 10 02:39)

1. **Date format was corrupt** — top bar showed "June 353, 2027"
   because `current_day` is the day-of-YEAR (1-365), not day-of-month.
   Fixed by extracting day-of-month from the `current_date` string.
2. **"No way to see events again once you leave matchmaking"** —
   player would book a card, navigate away, and have no UI path back
   to view/edit it. Fixed by adding `upcoming_events` to the dashboard
   payload + a new `renderUpcomingCards()` section on the Dashboard
   that lists all the player's scheduled events with date / name /
   CONFIRMED-or-DRAFT chip / fight count. Click → Matchmaking with
   that `event_id`.
3. **Next event on dashboard could show a rival promo's event** —
   `next_event` query wasn't filtering by player's promo. Fixed.
4. **Skip to Show cleanup** — handles no-events gracefully.

### 4.2 From commit `815923e` (Aug 10 01:31)

1. **Cancel button didn't actually cancel** — `advance_days(7)` was a
   single synchronous Python call that couldn't be interrupted. The
   Cancel button set a flag but the flag was never checked. Fixed by
   switching to a 1-day-at-a-time loop that checks the cancel flag
   between ticks.
2. **Confirmed card layout** — visual issue with how a confirmed card
   was displayed after `confirm_card` was called.
3. **Force new game** — `player_promotion_id` kept persisting across
   test sessions, causing the app to skip the pre-game screen.

### 4.3 From commit `b8f0878` (Aug 10 01:10)

1. **Venue filter defaulted to "All"** — user wanted US venues first.
   Fixed: default to United States.
2. **Quick-pick venue always picked the same venue** — fixed by
   excluding the already-selected venue + random from top 5.
3. **Matchmaking button greyed out** — user couldn't figure out they
   needed to pick new fighters for the second fight. Fixed by
   auto-reopening the roster browser + clearing corners + showing a
   toast "Staged: X vs Y. Pick your next matchup!"
4. **Cancel button + no-event handling on Skip to Show** — added.
5. **Bios on the processing screen were too sparse** — added country
   of origin + bio excerpt.

### 4.4 From commit `ffc435b` (Aug 10 00:55)

1. **`player_promotion_id` was stale** — cleared for fresh game start.
2. **Fighter snapshot cycle was too fast** — 3s → 10s.
3. **PPV elasticity needed strengthening** — tuned.

### 4.5 Pattern observation

Every one of the last 4 commits is reactive — the user tested, found
a bug or UX gap, and the supervisor fixed it. There is no proactive
planning round happening. The user is essentially doing QA, and the
supervisor is in pure bug-fix mode. The deeper issues (Phase E6
missing, MM3/MM4 partial, news variety, champions still bad, rival AI
cards too thin, future-dated-rows root cause) are NOT being addressed
because the supervisor is chasing user-reported symptoms.

---

## 5. Summary — what to do next

### Immediate (highest-leverage)

1. **Build Phase E6 — The Books + Deals screens.** This is the single
   biggest planned-but-missing feature. The entire econ track (E1-E5)
   was built to feed these screens, and they don't exist. Estimated
   4-5 dev-days per the MASTER_PLAN.
2. **Fix the "champions still have bad attributes" residual issue**
   flagged in the P6 audit. The `9f61346` "champions fix" commit
   didn't catch all bad champions.
3. **Fix rival AI card thickness** — the F2 min-card-size check only
   fires for the player. Rival AI events still average 2.5 fights
   (target 5-8). Wire the min-card-size check into
   `services/rival_ai/event_scheduler.py`.
4. **Expand finance-news templates** — the "event highly profitable"
   headline repeats 51× per the P6 audit. Need 8+ variants like the
   fight-news banks already have.
5. **Resume the worklog + CHANGELOG.** Both stopped in late July. The
   August work (E4, E5, M1-M5, MM1-MM4, Fight Night, P1-P6, F1-F2,
   CR-10..14) is undocumented except in git commit messages.

### Medium-term (planned-but-deferred)

6. **Build the remaining 5 placeholder screens** — Scouting, Legends
   (HoF), Training Camps (Gyms), Bad Blood (Rivalries), Records. Each
   has a backend already (except Records which needs new queries).
7. **Finish MM3** — training camp requirement + personality-based
   last-minute rejection. These were in the MM3 plan but not
   explicitly shipped.
8. **Fix the "left promotion but still contracted" bug** flagged in
   MM4 §4.2. Never mentioned in any commit.
9. **Fix the `run_sim_forward.py` root cause** so future sim audits
   don't leave 28 696 future-dated rows in the DB (commit `3433085`
   cleaned them up but didn't prevent recurrence).

### Lower-priority

10. Verify staff aging fires correctly once a sim-year crosses Jan 1
    (P6 audit issue #5 — possibly already resolved by M2 but
    unverified).
11. Verify cross-event booking check (MM3 §3.1) is actually wired
    into `book_fight` (the `0820f1b` commit message is generic).

---

## Appendix A — File counts (rough scale of system)

| Layer | Lines | Notes |
|---|---|---|
| `src/app_web.py` | 10 979 | API surface — 30+ `get_*_data` methods, 100+ endpoints |
| `src/finance.py` | 1 360 | Real PPV/broadcast model + purses + show-quality adjustment |
| `src/services/fight_engine.py` | ~5 100 | Beat-by-beat fight resolver + per-beat commentary |
| `src/services/rival_ai/` (8 files) | ~4 200 | 4 archetypes, 7 decision modules, 6 imperfection mechanisms |
| `src/interpretation/` (8 files) | ~6 300 | Snapshot cache + 5 phrase engines (momentum, pressure, trajectory, phase, legacy, family) |
| `src/web/js/` (16 files) | ~11 000 | 14 wired screens + bridge + app shell |
| `src/web/css/` (16 files) | — | One CSS file per screen + theme + components |
| `scripts/` (60+ files) | — | Tests, seed data, audit scripts |
| `docs/` (40+ files) | — | All planning docs referenced above |

## Appendix B — Verifying the "Phase E6 never started" claim

To confirm Phase E6 (Finance/Books + Contracts/Deals screens) was
never built:

```
$ ls src/web/js/finance.js src/web/js/contracts.js
ls: cannot access 'src/web/js/finance.js': No such file or directory
ls: cannot access 'src/web/js/contracts.js': No such file or directory

$ grep -n "def get_finance_data\|def get_contracts_data" src/app_web.py
(no matches)

$ git log --oneline -- src/web/js/finance.js src/web/js/contracts.js
(empty — no commits ever touched these files)
```

Both nav items (`finance` → "The Books", `contracts` → "Deals") are
defined in `app.js:47-48` and fall through to the
`PLACEHOLDER_PHRASES` fallback at `app.js:713-720`, rendering the
generic "The books are open" / "No deals on the table" empty state.

## Appendix C — Recent commit hashes referenced

| Hash | Date | Phase |
|---|---|---|
| `a7e6185` | 2026-08-10 | LATEST — date format + upcoming cards + skip-to-show |
| `3433085` | 2026-08-10 | 28 696 future-dated rows cleanup + rest 90→60 |
| `815923e` | 2026-08-10 | Cancel button works + confirmed card layout + force new game |
| `b8f0878` | 2026-08-10 | Venue default US + quick pick variety + matchmaking auto-reopen + sim cancel + better bios |
| `ffc435b` | 2026-08-10 | Pre-push: clear player_promotion_id + snapshot 3s→10s + PPV elasticity |
| `600fef9` | 2026-08-10 | F2: min card size + Sim Week + Skip to Show + overlay + promo growth |
| `bbe2098` | 2026-08-10 | F1: financial model — show quality drives post-event revenue + purses + preview range |
| `9e78933` | 2026-08-08 | P6: 3-month sim audit — 7 issues flagged |
| `ddf9a75` | 2026-08-08 | COMPREHENSIVE_FIX_PLAN doc authored (27 issues) |
| `5323a6b` | 2026-08-08 | P1: quick fixes (bidding alert 3 max, echoes rephrase, title bar day, matchmaking scroll) |
| `e1a9234` | 2026-08-08 | P2: Stack a Card redesign + financial balance |
| `c02c10d`–`a053c16` | 2026-08-08 | Fight Night FN.1–FN.3 |
| `6243fbf` | 2026-08-08 | MM1.1–1.5 frontend rewrite |
| `0d7f3e8` | 2026-08-08 | MM2 calendar screen |
| `0820f1b` | 2026-08-08 | MM3+MM4 fighter availability + bidding tone-down + balance sweep |
| `9bc8b58`–`987ffcb` | 2026-08-08 | INFO-SCREENS-BATCH-1 (Wire, Archive, Rankings, Belts) |
| `e826dbb` | 2026-08-04 | E5: bankruptcy recovery + staff effects |
| `7f8d799` | 2026-08-04 | E4: Staff Market screen |
| `b5f1620` | 2026-08-05 | M1: fighter gen base 50→37 + realization |
| `f9de5ab` | 2026-08-05 | M2+M3: staff lifecycle + rival AI bidding wars |
| `ee3ba0c`–`4effe81` | 2026-08-05 | M4: matchmaking screen + event builder integration |
| `1cc1e38`–`efb8993` | 2026-08-02 | CR-14: bio regeneration |
| `4e1dc30`–`567e66b` | 2026-08-02 | CR-11: fight engine doctor-stoppage fix |
| `9edbb75`–`f6aa461` | 2026-08-02 | CR-10: training-camp effective_ceiling fix |
| `081972c` | 2026-08-02 | DB review: schema v3.19.0 + portraits |

---

*End of review. No code was changed by this research pass.*
