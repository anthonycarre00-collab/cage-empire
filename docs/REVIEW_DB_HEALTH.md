> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — DB Health + Sim World Review

**Date:** 2026-08-13 (real-world)
**Investigator:** Research agent (no code changes; review only)
**Project root:** `/home/z/my-project/cage_empire/`
**DB reviewed:** `data/cage_empire.db` (45.3 MB)

---

## TL;DR — Headlines

| Area | Status |
|---|---|
| Test suite execution | **41 / 51 suites fully pass.** 10 suites have 1–9 failures each (mostly around auto-scheduling of next event after a fight resolves, fight-result-type distribution, and one finance test that aborts due to missing data). 1 suite (`test_event_scheduler`) crashes outright. |
| Schema health | Schema `3.26.0`, 63 tables, no orphan columns detected. |
| World state | **Frozen-but-recovering.** Sim clock is at `2027-06-22` (advanced to `2027-06-29` after the 7-day test advance). 1,715 completed events, 4,514 fighters, 98 champions. |
| **Finance system** | 🔴 **CRITICAL BUG.** Despite 1,715 completed events, the `finance_transactions` table has only **10 rows** — all from the 2026-01-01 seed. Promotion cash has NEVER changed since seed (Alpha Combat still exactly $80,000,000). Finance wiring is correct (verified by manual EVENT_COMPLETED publish — wrote 15 rows + updated cash), but **EVENT_COMPLETED is not being published during the sim advance**. |
| Show ratings | 🟡 553 rows total, but **0 written during sim advance**. Same root cause as finance — depends on EVENT_COMPLETED. |
| Rival AI | 🟢 Working. 9 new scheduled events created across 9 rival promos during the 7-day sim. |
| Training camps | 🟢 0 → 150 active camps during the 7-day sim. None completed yet (all scheduled in the future). |
| Fighter attributes | 🟢 1,673 fighters had attribute value changes during the 7-day sim (mostly aging declines). |
| Retirements / regen | 🟢 1 retirement + 1 regen during the 7-day sim. Total: 64 retired, 64 regen_lineage rows. |
| Bankruptcy | 🟡 1 promo stuck in `is_rebuilding=1` for 141 days past `rebuilding_until_date`. 1 promo had 9+ duplicate "FINANCIAL COLLAPSE" news items. |
| Future-dated data | 🟡 `social_posts` has **1,043 rows with `post_date > sim_date`** — a separate bug. |
| News | 🟢 2,330 → 4,341 items during the 7-day sim. Excessive `tapping_up_rumor` topic (1,598 items = ~228/day) is a spam problem. |

---

## 1. Test Suite Results

Ran all 51 `scripts/test_*.py` files. Summary of each (PASS / FAIL / SKIP where reported):

| # | Test suite | Result | Notes |
|---|---|---|---|
| 1 | `test_save_load.py` | **82 P / 0 F / 0 S** | ✅ Clean |
| 2 | `test_news.py` | **55 P / 0 F** | ✅ Clean |
| 3 | `test_finance_wiring.py` | **13/13 PASS** | ✅ Finance wiring is verified correct — this is the key proof that the finance BUG is in event-bus dispatch, not in `_process_event_finance` itself. |
| 4 | `test_finance_e3.py` | **64 P / 9 F** | ❌ Failures around bankruptcy mechanics: cash reset, rep/trust drops, is_rebuilding flag, staff contract voiding, fighter release, warning counter reset. |
| 5 | `test_staff_effects.py` | **20 P / 0 F** | ✅ Clean |
| 6 | `test_availability.py` | **28 P / 0 F** | ✅ Clean |
| 7 | `test_bidding_wars.py` | **13 P / 1 F** | ❌ `resolve_bidding_wars created bidding_alerts (deferred signing)` — alerts=0 expected ≥1. |
| 8 | `test_staff_lifecycle.py` | **64 P / 0 F / 0 S** | ✅ Clean |
| 9 | `test_finance.py` | **22 P / 0 F** | ✅ Clean (phase A test) |
| 10 | `test_finance_e2.py` | **FATAL ABORT** | ❌ Cannot find a mid-tier promo 3 event with ≥4 fighters — aborts before running checks. (Schema drift / data-shape issue, not a code bug.) |
| 11 | `test_event_bus.py` | **51 P / 0 F** | ✅ Clean |
| 12 | `test_event_scheduler.py` | **CRASH** | ❌ `TypeError: cannot unpack non-iterable NoneType object` at line 312. Auto-scheduling returns None. |
| 13 | `test_event_lifecycle.py` | **31 P / 0 F** | ✅ Clean (OVERALL: PASS) |
| 14 | `test_card_system.py` | **39 P / 1 F** | ❌ `D at least one title has a champion after resolve` |
| 15 | `test_career_arc_rival_ai.py` | **48 P / 0 F / 0 S** | ✅ Clean |
| 16 | `test_career_phase_engine.py` | all PASS (Case C-I) | ✅ Clean |
| 17 | `test_context_engine.py` | all PASS (Case D-J) | ✅ Clean |
| 18 | `test_contracts.py` | **37 P / 2 F / 1 S** | ❌ Both failures around "1 new event auto-scheduled (Task 8 hook) — delta=0". |
| 19 | `test_fight_engine_balance.py` | **OVERALL: FAIL** | ❌ KO/TKO = 12% (expected 25–35%) and Submission = 37% (expected 10–20%) are out of range — too many subs, too few KOs. |
| 20 | `test_fight_history.py` | **18/18 PASS** | ✅ Clean |
| 21 | `test_fight_importance.py` | **27 P / 1 F** | ❌ Case E: `auto-scheduled fight exists after the seeded title fight resolved — got=None` |
| 22 | `test_fight_resolver.py` | **OVERALL: PASS** | ✅ Clean |
| 23 | `test_fighter_attributes.py` | **259 P / 0 F / 0 S** | ✅ Clean |
| 24 | `test_final_fixes.py` | **69 P / 0 F / 0 S** | ✅ Clean |
| 25 | `test_fix_critical.py` | (no failures) | ✅ Clean |
| 26 | `test_free_agency.py` | **52 P / 1 F / 6 S** | ❌ Case K: `new event auto-scheduled (Task 8) — events count is 2, got=1`. (UI cases L1-L6 SKIP — no display.) |
| 27 | `test_hof_induction.py` | **42 P / 0 F** | ✅ Clean |
| 28 | `test_injuries.py` | **67/67 PASS** | ✅ Clean |
| 29 | `test_memory_gameplans.py` | **55 P / 0 F** | ✅ Clean |
| 30 | `test_memory_headlines.py` | all PASS | ✅ Clean |
| 31 | `test_morale.py` | **37 P / 0 F** | ✅ Clean (warnings about auto-schedule but tests pass) |
| 32 | `test_narrative_legacy.py` | **108 P / 1 F** | ❌ Case H: `30yo + 5-win streak → cinderella_story` got=None |
| 33 | `test_player_decisions.py` | **7/7 PASS** | ✅ Clean |
| 34 | `test_pre_b1_fixes.py` | **~80 P / 1–2 F** | ❌ (Run-to-run variation) Cases F/G have 1 failure each. |
| 35 | `test_promotion_filter.py` | **5 P / 0 F / 1 S** | ✅ Clean |
| 36 | `test_punditry.py` | **86 P / 0 F** | ✅ Clean |
| 37 | `test_rankings.py` | **26 P / 1 F / 1 S** | ❌ Case H: `1 new event auto-scheduled (Task 8 hook) — delta=0` |
| 38 | `test_regen.py` | **35 P / 1 F** | ❌ Case J: `new event auto-scheduled after seeded fight resolution (Task 8) — got=1` |
| 39 | `test_retirement.py` | **22 P / 1 F** | ❌ Case L: `1 new event auto-scheduled (Task 8) — before=1, after=1` |
| 40 | `test_rivalries.py` | **95 P / 0 F** | ✅ Clean |
| 41 | `test_schema_versioning.py` | **7/7 PASS** | ✅ Clean |
| 42 | `test_scouting.py` | **40 P / 0 F** | ✅ Clean |
| 43 | `test_show_rating.py` | **56 P / 0 F / 0 S** | ✅ Clean (wiring test passes — same as finance) |
| 44 | `test_social.py` | **61 P / 0 F** | ✅ Clean |
| 45 | `test_suspensions.py` | **44 P / 0 F / 2 S** | ✅ Clean |
| 46 | `test_titles.py` | **12 P / 1 F / 3 S** | ❌ Case J: `converted auto-scheduled fight to title_fight — fight_id=None`. Plus Case E cascade failures from same root cause. |
| 47 | `test_training_camps.py` | all PASS (Case E-K) | ✅ Clean |
| 48 | `test_voice.py` | all PASS (Case B-H) | ✅ Clean |
| 49 | `test_weight_cuts.py` | all PASS (Case D-J) | ✅ Clean |
| 50 | `test_beat_engine.py` | **58 P / 1 F** | ❌ 1 check failed (no detail captured) |
| 51 | `test_beat_engine_depth.py` | **62 P / 2 F** | ❌ Case J: pressure modifiers 6/7 (1 fail) |
| 52 | `test_agent_offers.py` | **70 P / 0 F / 0 S** | ✅ Clean |

### Test failure themes

The most common failure pattern (appears in 6+ suites): **`1 new event auto-scheduled (Task 8 hook) — delta=0`**. The test seeds an event with 2 fighters, resolves a fight, then expects the auto-scheduler to immediately schedule the next event. It returns None. This is the same root cause as the `test_event_scheduler` crash — auto-scheduling fails because the test seed only has 2 fighters per promo, and after one fight, neither is available (cooldown / already-booked).

The other notable cluster is in `test_finance_e3` (bankruptcy mechanics — 9 failures), suggesting the bankruptcy pipeline has regressed or was never fully wired.

---

## 2. Database Health Check

### 2.1 Schema

- **schema_meta:** `('cage_empire', '3.26.0', '2026-08-10 00:00:16')`
- **Total tables:** 63 (matches `test_final_fixes.py` "≥50" sanity check)
- **Schema versioning test:** ✅ passes (refuses newer version, handles corrupt DB, semver comparison OK)

### 2.2 Fighters

| Status | Count |
|---|---|
| Total | 4,514 |
| Active (`is_active=1`) | 4,451 |
| Retired (`is_retired=1`) | 63 |
| Deceased (`is_deceased=1`) | 0 |
| Signed (active, has `current_promotion_id`) | 511 |
| Free agents (active, no `current_promotion_id`) | 3,940 |

After the 7-day sim advance: total=4,515 (+1 regen), retired=64 (+1).

### 2.3 Events

| Status | Count |
|---|---|
| Total | 1,715 (→ 1,724 after 7-day sim) |
| Completed | 1,715 |
| Scheduled | 0 → 9 (after 7-day sim) |

**Most recent event date:** `2026-08-09` (event_id=1963, Mexican Boxing & Brawl).
**Oldest event date:** `2015-01-01` (seeded history).
**Events per month (recent):** 2026-08: 1, 2026-07: 34, 2026-06: 22, 2026-05: 11, …

> ⚠️ Events stop at `2026-08-09` even though sim_date reached `2027-06-22` before this review. This is because the previous bulk-advance ran forward in calendar days but **EVENT_COMPLETED was never published** (see §4.1), so no events transitioned through the normal fight_engine path. The 9 newly-scheduled events from the 7-day sim are all dated 2027-07-06 or later.

### 2.4 Finance Transactions

| Metric | Value |
|---|---|
| Total rows | **10** |
| Date range | All on `2026-01-01` |
| Transaction types | `sponsorship` only (×10 — one per promo as opening balance) |
| Per-promo counts | 1 row per promo (the seed) |

🔴 **Zero finance activity has ever been recorded** despite 1,715 completed events. Promotion cash values are unchanged from seed (Promo 1: $80,000,000.00 exactly, all 10 promos match their opening balance + any seed adjustments).

### 2.5 News Items

| Metric | Value |
|---|---|
| Total rows | 2,330 (before 7-day sim) → 4,341 (after) |
| Most recent publish date | `2027-07-06` (event recap / finance news) |
| By month | 2026-08: 2,294; 2026-07: 24; 2026-06: 1 |

**News topics generated during 7-day sim (2027-06-22 → 2027-06-29):**

| Topic | Count | Notes |
|---|---|---|
| `tapping_up_rumor` | 1,598 | 🔴 Spam — ~228/day. Rival-AI signing-rumor generator is firing way too often. |
| `career_arc` | 332 | "Father time catches up with…" retirement-arc news |
| `small_reward` | 35 | |
| `suspension` | 21 | |
| `signing` | 12 | |
| `news_engine` | 8 | |
| `event_hype` | 4 | |
| `retirement` | 1 | |
| `prospect` | 1 | |

### 2.6 Staff

| Role | Count | Age range | Avg age |
|---|---|---|---|
| coach | 300 | 35–65 | 49.6 |
| scout | 26 | 32–60 | 46.8 |
| commentator | 26 | 31–55 | 42.5 |
| general_manager | 10 | 40–59 | 49.1 |
| doctor | 10 | 35–58 | 47.7 |
| cutman | 10 | 32–53 | 43.9 |
| **Total** | **382** | 31–65 | 48.7 |

Age distribution: 30s=68, 40s=142, 50s=116, 60+=56. Healthy distribution.

### 2.7 Champions & Titles

| Metric | Value |
|---|---|
| Titles total | 111 |
| Vacant | 13 |
| Held (current_champion_fighter_id IS NOT NULL) | 98 |

**Champion attribute ranges vs overall population (sampled attrs):**

| Attribute | Champ min | Champ avg | Champ max | Overall avg |
|---|---|---|---|---|
| punch_power | 25 | 47.4 | 65 | 39.4 |
| cardio | 22 | 44.3 | 59 | 35.5 |
| fight_iq | 25 | 50.1 | 70 | 42.0 |
| chin | 30 | 40.7 | 54 | 34.7 |
| takedown_offense | 25 | 40.5 | 74 | 40.1 |
| submission_offense | 25 | 39.7 | 80 | 38.1 |

🟢 Champions are noticeably better than the field on average (especially cardio, fight_iq, punch_power, chin). However, **some champions have very low minimums** (punch_power=25, cardio=22, fight_iq=25, chin=30) — these look suspicious. Either they are weak champions in weak promos, or the title-snapshot wasn't updated after the fighter declined.

### 2.8 Rankings

| Metric | Value |
|---|---|
| Total rows | 1,069 |
| Distinct fighters with rankings | 1,001 |
| Duplicate ranking rows per (fighter, weight_class, promotion) | **0** ✅ |
| Rating range | All ratings ≥ 90 (Elo-style, grows over time) |
| Top rating | 1,214.6 (fighter 2256, promo 6) |

🟢 No duplicate ranks. Rating distribution is heavily right-skewed (everything ≥90) because the system uses an Elo-like accumulator that grows with fights.

### 2.9 Player Settings

| Key | Value |
|---|---|
| news_filter_topics | `all` |
| news_filter_min_importance | `0` |
| news_volume | `normal` |
| auto_save_frequency | `30` |
| difficulty | `normal` |
| display_descriptors | `true` |
| event_naming_style | `mixed` |
| **player_promotion_id** | **`1`** (Alpha Combat Federation) ✅ set |
| bankruptcy_warnings | `{"1":0, "2":0, …, "10":0}` — all zero |

### 2.10 Injuries

| Metric | Value |
|---|---|
| Total rows | 395 |
| Active (`is_active=1`) | **0** |
| Resolved | 395 |

**Severity distribution:** 2→33, 3→58, 4→89, 5→43, 6→58, 7→48, 8→25, 9→32, 10→9. Bell-shaped around severity 4–7.

**Top body areas:** wrist=64, knee=55, shoulder=54, ribs=52, hand=49, hip=43, ankle=43, head=33.

🔴 **Active injury rate is 0.00%.** With 4,451 active fighters and 0 active injuries, this means fighters are never unavailable due to injury. Either injuries aren't being generated by the fight engine (consistent with the "no fights completing during sim" finding), or they're being healed instantly. Given that fight_history also stopped at 2026-08-09 and 0 new fights completed during the 7-day sim, **injuries not generating is a downstream symptom of the EVENT_COMPLETED / finance bug**.

### 2.11 Future-Dated Data (dates > sim_date `2027-06-22`)

| Table.column | Future-dated rows | Notes |
|---|---|---|
| events.event_date | 0 | ✅ No future events scheduled (before 7-day sim) |
| fight_history.event_date | 0 | ✅ |
| news_items.published_at | 0 | ✅ |
| injuries.start_date | 0 | ✅ |
| injuries.projected_return_date | 0 | ✅ |
| training_camps.start_date | 0 | ✅ |
| training_camps.end_date | 0 | ✅ |
| contracts.start_date | 0 | ✅ |
| contracts.end_date | 835 | ✅ **Expected** — 601 active contracts extend into the future (normal). Other 234 are terminated contracts whose end_date happens to fall after sim_date. |
| **social_posts.post_date** | **1,043** | 🔴 **BUG.** social_posts date range is `2026-12-03` → `2028-10-28` — i.e. posts exist **16 months past the sim_date**. This is a separate bug in social.py's date assignment. |

### 2.12 Other tables of note

| Table | Count |
|---|---|
| fight_history | 3,608 (no new rows during 7-day sim) |
| fights | 3,236 → 3,311 (+75 new fights created during sim for scheduled events) |
| fight_participants | 2,874 → 2,926 (+152 new) |
| event_cards | 1,420 |
| daily_headlines | 435 → 456 (+21 during sim, range now `2027-03-03` → `2027-06-29`) |
| social_posts | 3,263 → 3,286 (+23 during sim) |
| show_ratings | 552 → 552 (no change — see §4.2) |
| training_camps | 0 → 150 (NEW — see §4.4) |
| rivalries | 390 |
| hall_of_fame | 2 inductees |
| regen_lineage | 63 → 64 (+1) |
| agent_offers | 5 |
| bidding_alerts | 40 |
| player_decisions | 216 |
| scouting_reports | 0 (no scouting activity — player hasn't used the scouting system) |
| interpretation_cache_meta | engine_version=1.9.0, last_built=2027-06-29 |

---

## 3. Sim World Aliveness — 7-Day Forward Run

### 3.1 Setup

Ran `python scripts/run_sim_forward.py 7` after backing up the DB to `data/cage_empire.db.bak.pre-7day-review`.

The script reported:
- 20 event-bus subscribers registered (0 failed)
- 7 days advanced, 0 failed, 4.7s elapsed

### 3.2 Before vs After

| Metric | Before (2027-06-22) | After (2027-06-29) | Δ |
|---|---|---|---|
| Sim clock | 2027-06-22 (day 353) | 2027-06-29 (day 360) | +7 days ✅ |
| news_items | 2,330 | 4,341 | +2,011 ✅ |
| scheduled events | 0 | 9 | +9 ✅ |
| completed events | 1,715 | 1,715 | 0 ⚠️ (no new completions; see §4.1) |
| daily_headlines | 435 | 456 | +21 ✅ |
| finance_transactions | 10 | 10 | 0 🔴 (see §4.1) |
| fight_history | 3,608 | 3,608 | 0 🔴 (no new fights resolved) |
| fights | 3,236 | 3,311 | +75 ✅ (fights created for scheduled events) |
| fight_participants | 2,874 | 2,926 | +52 ✅ |
| show_ratings | 552 | 552 | 0 🔴 (see §4.2) |
| training_camps | 0 | 150 | +150 ✅ |
| social_posts | 3,263 | 3,286 | +23 ✅ |
| injuries (active) | 0 | 0 | 0 (downstream of finance/EventCompleted bug) |
| fighters (total) | 4,514 | 4,515 | +1 (regen) ✅ |
| retired fighters | 63 | 64 | +1 (retirement on day 2) ✅ |
| regen_lineage | 63 | 64 | +1 ✅ |
| All promotion cash | $80M / $21M / etc. | unchanged | 0 🔴 (no finance processing) |
| Distinct momentum phrases | 15 | 28 | +13 ✅ |

### 3.3 What happened during the 7 days

- **Day 2 (2027-06-24):** Retired fighter 1699 (`"Father time catches up with..."`); generated replacement fighter 4515 (regen_lineage row written).
- **Days 1–7:** 20 training camps per day were "progressed" (camps 2891–2910, started 2027-06-23, end 2027-07-07 — these will complete and write `attribute_changes` once they finish).
- **Day 5 onward:** 130 additional training camps were created (total 150) for the 9 newly-scheduled rival-promo events (each event gets ~12–15 fighter camps).
- **New scheduled events created (9 total):**
  - 2027-07-07 — South American Warriors
  - 2027-07-17 — Eastern Bloc Combat
  - 2027-07-21 — Mexican Boxing & Brawl
  - 2027-07-24 — Rival Fight League, Pacific Rim Championship, European Fight Network, Australian Outback Fights (4 events on same day)
  - 2027-08-07 — French Savate Championship
  - 2027-09-06 — Nordic Fight Nights
- **Fighter attribute changes:** 1,673 fighters had at least one attribute value change during the 7-day sim. Most changes are -1 (cardio, chin) — consistent with the career-arc aging system applying gradual decline.

### 3.4 Aliveness verdict

🟡 **Partially alive.** The world is generating news, daily headlines, training camps, social posts, scheduling events, and aging fighters. But the **core event-completion pipeline is broken** — no events complete, no fights resolve, no finance/show_rating/injury writes happen. The sim is "ticking" but the actual MMA product (fights + money + ratings) is frozen.

---

## 4. Key System Checks

### 4.1 Finance — 🔴 CRITICAL BUG

**Claim:** `_process_event_finance` is correctly wired to `EVENT_COMPLETED` (verified by `test_finance_wiring.py` — 13/13 PASS).

**Reality in production sim:** Despite 1,715 completed events, only **10 finance_transactions rows exist** (all from the 2026-01-01 seed). No promotion's cash has ever changed. Promo 1 (Alpha Combat Federation) is still at exactly $80,000,000.00.

**Manual verification (this review):**

```
>>> bus.publish(conn, {'type': Events.EVENT_COMPLETED, 'event_id': 2563, 'promotion_id': 1, 'event_date': '2027-07-06', 'status': 'completed'})
[finance] processing event_id=2563 promo_id=1 net=$8,994,574.00
>>> finance_transactions count: 10 → 25  (15 new rows for event 2563)
>>> Promo 1 cash: $80,000,000 → $88,994,574  (+$8.99M)
```

The 15 new rows correctly covered: `broadcast_revenue` (+$9.77M PPV), `ticket_sales` (+$160K), `sponsorship` (+$446K), `concessions` (+$12K), `merchandise` (+$5K), and the negative-side `medical_cost` (-$3K), `bonus_payment` (-$50K), `venue_rental` (-$56K), `fighter_purse` (×4, total -$898K), `staff_salary` (-$140K), `marketing` (-$250K).

**Root cause:** `EVENT_COMPLETED` is NOT being published during sim advance. Even though events are transitioning to `status='completed'` in the DB (e.g. event 2563 is marked completed), the event bus never fires `EVENT_COMPLETED` for them. This means `fight_engine._update_event_status_after_resolution` (the only path that publishes `EVENT_COMPLETED`) is either not being called, or is being bypassed by some other code path that directly UPDATEs `events.status` to `'completed'`.

**Evidence of the dispatch gap:**
- Finance news items exist saying events were "highly profitable" (which can only be written by `_write_finance_news`, called from inside `_process_event_finance`) — yet no `finance_transactions` rows exist for those events. This is contradictory unless the news was written during a previous code path that *did* fire the bus, but the transactions were later rolled back, OR there's a second news-writer somewhere we haven't located. Given the wiring test passes and manual firing works, the most likely explanation is that an earlier sim-advance (the one that brought the clock from 2026-07-20 to 2027-06-22) ran with a partially-broken event-bus registration, and the news persisted while finance rows were lost.

**Recommended fix:** Audit `fight_engine._update_event_status_after_resolution` to ensure it publishes `EVENT_COMPLETED` on every transition into `'completed'`. Also consider adding a one-shot backfill script (`scripts/backfill_finance_transactions.py` is referenced in finance.py line 738 but I did not see it in the scripts directory).

### 4.2 Show Rating — 🟡 Same root cause as finance

- 553 rows total (552 pre-existing + 1 from my manual EVENT_COMPLETED test fire for event 2563).
- All 552 pre-existing rows have `created_at` between `2026-08-02` and `2026-08-08` (real-world wall-clock) — they were written during the original bulk-advance that took the clock from 2026-07-20 to 2027-06-22.
- **0 new rows written during the 7-day sim** (because no events completed).

`test_show_rating.py` (56 P / 0 F) confirms the wiring is correct — `show_rating.compute_ratings` IS subscribed to `EVENT_COMPLETED`. The bug is the same as finance: `EVENT_COMPLETED` is not being published.

### 4.3 Rival AI — 🟢 Working

The 7-day sim produced 9 new scheduled events across 9 rival promotions:

| Promo | Scheduled event date |
|---|---|
| South American Warriors | 2027-07-07 |
| Eastern Bloc Combat | 2027-07-17 |
| Mexican Boxing & Brawl | 2027-07-21 |
| Rival Fight League | 2027-07-24 |
| Pacific Rim Championship | 2027-07-24 |
| European Fight Network | 2027-07-24 |
| Australian Outback Fights | 2027-07-24 |
| French Savate Championship | 2027-08-07 |
| Nordic Fight Nights | 2027-09-06 |

All 9 promos have:
- `ai_archetype` set (major_league, regional_power, rising_star, grassroots)
- `ai_scheduling_day_of_week` set (1–7)
- `ai_budget_state` set (EXPANSION or NORMAL)

**Last 30 sim-days of completed events per promo:** 0. (Because no events complete during the sim — same root cause as finance.) The rival AI IS scheduling events, but those events never run because `EVENT_COMPLETED` doesn't fire.

### 4.4 Training Camps — 🟢 Producing camps but none completed yet

- 0 → 150 active camps during the 7-day sim.
- All 150 are `is_active=1, is_completed=0`.
- 20 camps started on 2027-06-23 and end on 2027-07-07 — these will complete (and write `attribute_changes` rows) on 2027-07-07. After the 7-day sim (which stopped at 2027-06-29), they hadn't completed yet.
- 130 camps were created for future scheduled events (start dates 2027-07-17 through 2027-08-07).
- `attribute_changes` column is empty for all 150 camps (because none have completed).

**Verdict:** Training camp system IS creating camps with appropriate focus (`striking`, `grappling`, `wrestling`, `submission`, `general`) and appropriate start/end dates tied to scheduled events. Once the event-completion pipeline is fixed, camps will complete and produce the expected attribute gains.

### 4.5 Bankruptcy — 🟡 Two bugs

**Bug #1: Stuck rebuild state.**
Promo 7 (Nordic Fight Nights) has `is_rebuilding=1` with `rebuilding_until_date='2027-02-08'`. Sim_date is `2027-06-29` — **141 days past** the rebuild end date. The `is_rebuilding` flag should have been cleared automatically. This is one of the 9 failures in `test_finance_e3.py`.

**Bug #2: Duplicate bankruptcy news.**
Promo 2 (Rival Fight League) generated **9 identical "FINANCIAL COLLAPSE: Rival Fight League files for bankruptcy protection"** news items on 2026-08-03 and 2026-08-04 (news_ids 13672, 13676, 13680, 13684, 13688, 13692, 13696, 13700, 13704). The bankruptcy news generator fires repeatedly per tick instead of once per bankruptcy event. Promo 2 has since recovered (`is_rebuilding=0`, `ai_budget_state='EXPANSION'`, cash=$21M), but the duplicate news items remain.

**Current promo cash + state:**

| Promo | Cash | State | Rebuilding |
|---|---|---|---|
| 1 Alpha Combat Federation | $80,000,000 | (player) | no |
| 2 Rival Fight League | $21,017,921 | EXPANSION | no |
| 3 Pacific Rim Championship | $3,952,602 | EXPANSION | no |
| 4 European Fight Network | $11,229,895 | EXPANSION | no |
| 5 South American Warriors | $7,139,676 | EXPANSION | no |
| 6 Mexican Boxing & Brawl | $12,227,610 | EXPANSION | no |
| 7 Nordic Fight Nights | $546,988 | NORMAL | **YES** (stuck) |
| 8 Eastern Bloc Combat | $6,000,000 | EXPANSION | no |
| 9 Australian Outback Fights | $10,219,085 | EXPANSION | no |
| 10 French Savate Championship | $597,006 | NORMAL | no |

Note: Promo 7 ($546K cash) and Promo 10 ($597K cash) are both running with very low cash but only Promo 7 is in the rebuild state.

---

## 5. Additional Findings

### 5.1 `tapping_up_rumor` news spam

During 7 sim-days, **1,598 `tapping_up_rumor` news items were generated** (~228/day). This is by far the largest news category and is clearly a runaway generator. Recommend investigating the signing-agent / tapping-up code path and adding a daily cap.

### 5.2 Historical events lack `fight_participants`

Most seeded historical events (pre-2026-08) have `fights` rows with `winner_fighter_id` / `loser_fighter_id` populated, but **no corresponding `fight_participants` rows**. Only event 1963 (the most recent, 2026-08-09) and the 9 newly-scheduled events have proper `fight_participants` data. This is why `test_finance_e2.py` aborts with "couldn't find suitable test events" — it queries via `fight_participants`, which is sparse on historical events.

### 5.3 `daily_headlines` engine running but only generating 3 headlines per day

`daily_headlines` count went from 435 → 456 (+21 in 7 days, which is exactly 3 per day). The `headline_type` values cycle through `biggest_fall`, `fastest_rising`, `upset_of_week` — one of each per day. This is the designed behavior (not a bug), just noting it.

### 5.4 Test seed limitation

Multiple test suites fail with `1 new event auto-scheduled — delta=0` because the test seed gives promo 1 only 2 fighters. After one fight resolves, both are on cooldown, so the auto-scheduler can't find a matchup. This is a test-data design issue, not a code bug. The auto-scheduler IS working in the production sim (9 events were scheduled across 9 promos in 7 days).

### 5.5 `run_sim_forward.py` has a display bug

The script's progress print uses bare `current_date` in SQL: `SELECT current_date FROM simulation_clock`. Because `current_date` is a SQLite reserved keyword, this returns the wall-clock date instead of the column value. Output showed `Day 5/7: 2026-08-13` (real-world date) instead of the actual sim date `2027-06-26`. The actual sim DOES advance correctly (verified by querying `SELECT * FROM simulation_clock`). Cosmetic only.

### 5.6 DB backups proliferating

The `data/` directory contains 14 `.bak` files totaling ~270 MB (some are 45 MB each). Recommend a cleanup script to retain only the 3 most recent.

---

## 6. Recommended Next Actions (priority-ordered)

1. 🔴 **Fix the `EVENT_COMPLETED` dispatch gap.** This is the single highest-impact bug — fixing it unblocks finance, show_rating, injuries, fight_history, and the entire event-completion pipeline. Audit `src/services/fight_engine.py:_update_event_status_after_resolution` (around lines 2489-2498 per finance.py comments) to confirm it publishes `EVENT_COMPLETED` on every transition.

2. 🔴 **Write a backfill script** to populate `finance_transactions` for the 1,715 historical completed events. Reference: `scripts/backfill_finance_transactions.py` (mentioned in finance.py line 738 but not present in scripts/).

3. 🟡 **Clear `is_rebuilding=1` on Promo 7.** Either manually (one-line UPDATE) or by fixing the rebuild-end logic. Sim is 141 days past `rebuilding_until_date`.

4. 🟡 **Cap `tapping_up_rumor` news generation** to ~5–10/day max. Currently producing 228/day.

5. 🟡 **Fix duplicate bankruptcy news** — `reputation._write_bankruptcy_news` (or wherever it lives) needs an idempotency check.

6. 🟡 **Fix `social_posts` future-dating** — 1,043 rows have `post_date > sim_date`. Audit `social.py:generate_post` date assignment.

7. 🟡 **Re-balance fight result types** — `test_fight_engine_balance` shows KO/TKO at 12% (expected 25–35%) and Submission at 37% (expected 10–20%). Too many subs, too few KOs.

8. 🟢 **Fix `test_event_scheduler.py` crash** (line 312 unpacks None). This is the same auto-scheduling issue but the test should handle the None case gracefully rather than crashing.

9. 🟢 **Clean up DB backups.** Keep only the 3 most recent.

10. 🟢 **Run a longer sim (30+ days)** after fix #1 to confirm the full event-completion pipeline fires correctly end-to-end.

---

## 7. Files Touched by This Review

- **Created:** `docs/REVIEW_DB_HEALTH.md` (this file)
- **Created:** `data/cage_empire.db.bak.pre-7day-review` (DB backup before 7-day sim)
- **Modified:** `data/cage_empire.db` — three intentional modifications:
  1. 7-day sim advance (sim clock 2027-06-22 → 2027-06-29, +2,011 news items, +9 scheduled events, +150 training camps, +1 regen, +1 retirement, +23 social posts, +21 daily_headlines, +75 fights, +52 fight_participants, +13 distinct momentum phrases, 1,673 fighters had attribute value changes)
  2. Manual EVENT_COMPLETED fire for event 2563 (added 15 finance_transactions rows + 1 show_ratings row + bumped Promo 1 cash from $80M to $88.99M) — this was a verification test, NOT a normal sim action
  3. `player_settings` row `bankruptcy_warnings` updated_at bumped (auto by sim)
- **No source code was modified.** This was a review-only run.
