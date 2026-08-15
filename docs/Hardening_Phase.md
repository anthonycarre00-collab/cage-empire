# CAGE EMPIRE — Hardening Phase Plan (v2 — revised after GPT re-read)

> **Status:** PLANNING ONLY — no code changes. Canonical plan for Phase W.
> **Source:** `Cage_Empire_Autonomous_World_Integrity_Plan.md` (GPT directive, 48 sections)
> **Revision:** v2 — corrected after supervisor re-read GPT directive. v1 was wrong about memory/echoes being "compliant" and missed news noise + EventBus severity.

---

## 0. What v1 got wrong (supervisor correction)

GPT is right on all three points. My v1 audit was too shallow:

### Memory resurfacing (W17) — NOT compliant, needs significant work
- **v1 said:** "Well-implemented" ✅
- **Reality:** The memory engine surfaces only **4 types** (previous_fight, shared_gym, former_teammate, injury_history). GPT wants **15 types**: previous fights, rivalries, title fights, former champions, old gyms, former teammates, mentors, successors, controversial losses, injuries, comebacks, promotions, old events, major upsets, career milestones.
- **fighter_memory_links table:** Only 3 link types exist (regional_rival 744, style_echo 29, successor 2). GPT wants former_teammate, shared_gym, mentor, rival, title_history, upset, comeback, etc.
- **The engine is well-architected** (on-demand, targeted, voice-layered) but **starved of data** — only 2 of the 4 search types actually find anything (previous_fight works via fight_history; injury_history works via injuries table). The former_teammate + shared_gym searches return nothing because nobody writes those link types.
- **Fix needed:** Add memory link writers (when a fighter changes gym → write former_teammate link; when a title changes → write title_history link; when an upset happens → write upset link; etc.). Add new surface_memories search types for the missing 11.

### EventBus (W1) — NOT fine, GPT is right
- **v1 said:** EventBus "catches errors" ✅
- **Reality:** The EventBus catches exceptions and prints to stderr (`print(f"WARNING: subscriber '{name}' failed...")`). GPT explicitly says: "A development console warning is insufficient." The errors are **not persisted** — they vanish when the console scrolls. A subscriber can fail silently on every tick and the developer has no way to discover it after the fact.
- **Fix needed:** Create `simulation_tick_health` table. On subscriber failure: persist the error (subscriber name, event name, traceback, sim date) to DB. Mark tick health as DEGRADED. This is W1 and it's a real gap.

### News noise (W19) — NOT addressed in v1
- **v1 said:** "Event-driven narrative ✅" — but missed GPT's point entirely.
- **Reality:** While news IS event-bus-driven (not manufactured spam), GPT's concern is about **volume + quality control**:
  - No story importance tiers (LEGENDARY / MAJOR / SIGNIFICANT / ROUTINE / BACKGROUND)
  - No daily/weekly output cap on news items
  - The `tapping_up_rumor` cap (3/tick) we added is a band-aid, not a proper importance system
  - Social posts have a 5/tick cap ✅ but news has NO cap
  - 1,352 "fight" news items + 734 "injury" items — many are low-value repetitive content
- **Fix needed:** Add `importance` column to news_items. Tag each subscriber's output with an importance tier. Add a daily cap per tier (e.g. max 1 LEGENDARY, 3 MAJOR, 5 SIGNIFICANT, unlimited ROUTINE/BACKGROUND). Suppress items that don't answer at least one of GPT's questions: "Why should I care? What changed? Who caused it? What does it affect? What might happen next? Does it connect to history?"

---

## 1. Critical Gaps (must fix first — everything else depends on these)

### CRITICAL #1: Finance not registered in production (W2)
- `finance.register_subscribers()` exists but may not be called in the production entry point.
- **Impact:** Zero finance transactions from completed events.
- **Fix:** Verify + fix registration.
- **Effort:** S

### CRITICAL #2: `fight_participants` table is EMPTY (W7)
- All historical fights store winner/loser on `fights` table. `fight_participants` has 0 rows.
- **Fix:** Backfill script.
- **Effort:** S

### CRITICAL #3: Economic causality broken (W8)
- `promotions.current_cash` never read by matchmaking, rival AI, or sign_free_agent.
- **Fix:** Wire cash into decisions.
- **Effort:** M

### CRITICAL #4: No formal financial state machine (W9)
- Only ad-hoc `current_cash < 0 → -2 reputation`. No gradient states.
- **Fix:** Add `financial_state` column + state machine.
- **Effort:** M

### CRITICAL #5: EventBus errors not persisted (W1) — REVISED
- Subscriber failures print to stderr but are NOT persisted to DB. Silent failures can let half the simulation stop functioning with no trace.
- **Fix:** Create `simulation_tick_health` table. Persist subscriber errors. Mark tick health DEGRADED.
- **Effort:** M

### CRITICAL #6: Memory system starved of data (W17) — REVISED
- Engine architecture is good (4 search types, on-demand, voice-layered) but only 2 types return results. Only 3 link types in fighter_memory_links (regional_rival, style_echo, successor). GPT wants 15 memory types.
- **Fix:** Add memory link writers (gym changes, title changes, upsets, comebacks, milestones). Add new surface_memories search types. Backfill historical links.
- **Effort:** L

### CRITICAL #7: News has no importance tiers or volume control (W19) — REVISED
- No importance column. No daily cap. Low-value repetitive content drowns out meaningful stories.
- **Fix:** Add importance column. Tag subscribers. Add daily caps per tier. Suppress items that don't answer "why should I care?"
- **Effort:** M

---

## 2. Implementation Phases (revised)

### Phase HW1: Fix the Causal Chain (3-4 days)
- HW1.1: Fix finance registration (CRITICAL #1)
- HW1.2: Backfill fight_participants (CRITICAL #2)
- HW1.3: Wire economic causality (CRITICAL #3)
- HW1.4: Build financial state machine (CRITICAL #4)
- HW1.5: End-to-end event lifecycle test (W2)
- HW1.6: Add cancelled/postponed event statuses (W3)
- HW1.7: Clean up orphaned events (0 fights marked completed)

### Phase HW2: EventBus + Observability (2 days) — REVISED
- HW2.1: Create `simulation_tick_health` table (W1) — persist subscriber errors to DB, not just stderr
- HW2.2: Simulation Time Law audit (W4) — replace datetime.now()/date.today()/CURRENT_DATE in gameplay code
- HW2.3: Formal GAME_START_DATE constant (W5)
- HW2.4: World Health Status (W27) — HEALTHY/DEGRADED/BROKEN from tick health + event resolution rate
- HW2.5: Invariant Checker (W28) — extend forensic_db_check.py with 8 missing invariants

### Phase HW3: Memory + Echoes Expansion (3 days) — REVISED (was "Data Integrity + Save")
- HW3.1: Add memory link writers — when a fighter changes gym → former_teammate link; when title changes → title_history link; when upset happens → upset link; when fighter comes back from retirement → comeback link; when fighter reaches milestone (10 wins, 5 KO streak, etc.) → milestone link
- HW3.2: Add new surface_memories search types — title_fight_history, former_champion, controversial_loss, major_upset, career_milestone, comeback
- HW3.3: Backfill historical memory links from fight_history + titles + events
- HW3.4: Echoes quality audit (W16) — ensure sparse, relevant, personal, linked to actual decisions. Currently only signing_echo + cut_echo fire. Verify booking_echo + scouting_echo work.
- HW3.5: Memory resurfacing relevance (W17) — surface only when contextually relevant (e.g. rematch → surface old fight; title fight → surface former champion history)

### Phase HW4: News Noise Control + Narrative Quality (2 days) — REVISED
- HW4.1: Add `importance` column to news_items (W19) — tiers: LEGENDARY / MAJOR / SIGNIFICANT / ROUTINE / BACKGROUND
- HW4.2: Tag each news subscriber with a default importance tier
- HW4.3: Add daily caps per tier (1 LEGENDARY, 3 MAJOR, 5 SIGNIFICANT, unlimited ROUTINE/BACKGROUND)
- HW4.4: Suppress items that don't answer at least one GPT question ("Why should I care? What changed? Who caused it?")
- HW4.5: Player decision → consequence chain (W15) — verify logging, define chains
- HW4.6: Narrative quality rule (W37) — CAUSE → CHANGE → MEANING in interpretation phrases

### Phase HW5: Data Integrity + Save Hardening (2 days)
- HW5.1: Historical data normalisation (W7) — validate every fight has 2 participants, valid event, valid result
- HW5.2: Save system hardening (W25) — WAL checkpoint, world-integrity metadata
- HW5.3: Save compatibility (W26) — schema version check + PRAGMA integrity_check before load
- HW5.4: Social media date integrity (W18) — enforce post_date <= sim_date in writer

### Phase HW6: Long-Run Soak Tests (2-3 days)
- HW6.1: Build scripts/soak_test.py (30d/365d/1825d/3650d)
- HW6.2: Gate 1 — 30 days
- HW6.3: Gate 2 — 365 days
- HW6.4: Gate 3 — 5 years
- HW6.5: "What happened while I was gone?" test (W34)
- HW6.6: Historical continuity test (W33)
- HW6.7: Player agency test (W35)

### Phase HW7: Documentation (1 day)
- HW7.1: Create docs/CURRENT_SYSTEM_STATE.md (W44)
- HW7.2: Mark obsolete planning docs
- HW7.3: Update COMPREHENSIVE_REVIEW.md

---

## 3. Items genuinely compliant (no work needed) — REVISED

| W-item | Status | Note |
|---|---|---|
| W10 (coaches not in promo payroll) | ✅ Clean | GPT explicitly agrees this is correct |
| W20 (event-driven narrative) | ✅ News IS event-bus-driven | But needs importance tiers (W19) |
| W23 (staff audit — coaches excluded) | ✅ Clean | Same as W10 |
| W43 (don't rebuild architecture) | ✅ Compliant | Hardening, not rewriting |
| W45 (single source of truth) | ✅ Will be CURRENT_SYSTEM_STATE.md | |

### Items REMOVED from "compliant" list (v1 was wrong):
| W-item | v1 said | v2 reality |
|---|---|---|
| W17 (memory resurfacing) | "Well-implemented" ❌ | Engine good, data starved. Only 3 link types, 4 search types. GPT wants 15 types. Needs L effort. |
| W1 (EventBus) | "Catches errors" ❌ | Catches but doesn't persist. GPT says "warning is insufficient." Needs M effort. |
| W19 (news noise) | Not mentioned ❌ | No importance tiers, no daily cap. GPT says "3 meaningful stories > 300 interchangeable." Needs M effort. |

---

## 4. Other small but important items GPT raised (not missed this time)

| Item | GPT section | Status |
|---|---|---|
| Echoes should be sparse, not generic daily trivia | W16 | Need to verify — currently 672 daily_echoes (406 signing + 266 cut). Are they sparse enough? |
| Echoes should link to actual player decisions | W16 | Need to verify — does the echoes engine read from player_decisions table? |
| Narrative should prefer CAUSE → CHANGE → MEANING | W37 | Audit interpretation phrases — do they connect world fact + player agency + consequence? |
| Interpretation duplication — one meaning, one calculation | W38 | Check if multiple systems independently compute momentum, career_phase, marketability |
| Rival AI should react to its own previous results | W21 | Currently schedules + resolves but doesn't adjust based on financial outcome |
| Rival promotions should remember past interactions | W22 | No memory of bidding wars lost, fighters signed, title histories |
| Performance — measure before optimising | W39 | Profile tick duration, identify bottlenecks |
| DB index audit | W40 | Check indexes on recurring queries |
| Clean test DB vs long-run sandbox DB | W41 | Need separate environments |
| Test data vs game data provenance | W42 | Record world_version, seed_version |

---

## 5. Acceptance Gates (from W48)

- **Gate 1:** One complete event works end-to-end (schedule → resolve → finance → show rating → rankings → news → memory → next event)
- **Gate 2:** World coherent for 30 days (no silent failures, finance fires, events resolve)
- **Gate 3:** One year of meaningful autonomous evolution (champions change, fighters retire+regen, promotions have differentiated fortunes, rivalries develop, memories resurface)
- **Gate 4:** Five years of coherence (careers, promotions, economics, history — a fighter from year 1 can be traced through their full career)

---

## 6. What this plan does NOT do

- ❌ NO new gameplay features
- ❌ NO redesigned fight engine
- ❌ NO replaced SQLite/EventBus/save system architecture
- ❌ NO new screens
- ❌ NO WMMA5-style features (Hype, Inducements, etc.)
- ❌ NO purge of existing future-dated test data (valid if internally consistent)
- ❌ NO promotion coach payroll (coaches belong to gym ecosystem)

---

## 7. Revised effort estimate

| Phase | Days |
|---|---|
| HW1: Causal chain | 3-4 |
| HW2: EventBus + observability | 2 |
| HW3: Memory + echoes expansion | 3 |
| HW4: News noise + narrative quality | 2 |
| HW5: Data integrity + save | 2 |
| HW6: Long-run soak tests | 2-3 |
| HW7: Documentation | 1 |
| **Total** | **15-19 days** |

(v1 estimated 8-12 days — was too optimistic because it missed the memory expansion, EventBus persistence, and news noise control work.)
