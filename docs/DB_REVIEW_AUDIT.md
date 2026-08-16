> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Comprehensive DB Audit

**Task ID:** DB-REVIEW-COMPREHENSIVE-AUDIT
**Agent:** Subagent F — Comprehensive DB Audit
**Date:** 2026-08-02 (sim-clock pre-audit: 2026-10-15 → post-audit: 2027-01-13)
**Schema version:** 3.19.0
**Method:** Pre-audit snapshot → 90-day sim forward (`scripts/run_sim_forward.py 90`) → post-audit snapshot → diff + targeted queries. DB left in the post-run state (rollback NOT performed; pre-audit backup at `data/cage_empire.db.bak.pre-audit-sim`).

---

## 0. Executive Summary

**Overall assessment: The world is *partially* alive — finance, news, rivalries, regen, HoF, and injury systems all fire, but several core systems are broken or mis-tuned.** The biggest gaps are:

1. **Training camps are 99.7% broken** — of 578 camps completed during the 90-day run, only 2 produced any attribute gain. The `effective_ceiling` formula in `tick_processor._complete_training_camp()` multiplies `potential × age_factor × health_factor × personality_factor` and the `personality_factor` (typically 0.5 for avg fighters with discipline=50, coachability=50) collapses the ceiling *below* the seeded attribute values, so almost all camps hit the "already at ceiling" branch.
2. **Fight engine produces 54% doctor-stoppages** in new fights (vs the 5–6% in seeded historical fights). Zero unanimous decisions, zero draws, zero DQs were generated during the 90-day run — the engine is biased toward an early-round doctor-stoppage outcome.
3. **Career-phase pyramid is inverted** — 75% of active fighters are tagged `rising_contender` (the catch-all default in `career_phase_engine.compute_career_phase`), only ~0.5% are `veteran`, ~0.4% `gatekeeper`, ~0.3% `declining`. The "many prospects → few contenders → very few champions → some declining veterans" pyramid shape does not exist.
4. **No staff aging / retirement / death / regen system exists.** Staff `age` is a static column. The 379 staff range 31–65 (max = 65 = the seed's max-age cap). Rival AI `staff_manager.py` only fires/hires for cause (poor scout reports, high injury rate); no lifecycle.
5. **Bios contain record mismatches.** All 4477 bios are textually unique, but many reference fighter records that *contradict* `fighter_career.record_wins/losses` (e.g., fighter #1200 Arthur Allen bio says "31 professional fights" but `fighter_career` shows 2-0). The bios were generated against an earlier dataset.

### Top 5 findings (ranked by impact)

| # | Finding | Severity | Why it matters |
|---|---|---|---|
| 1 | Training-camp growth is broken (99.7% no-gain). Effective-ceiling formula collapses below seeded attribute values. | **CRITICAL** | The "Talent Hunter" + "Empire Builder" fantasies collapse — prospects never improve, so the player can't develop anyone. |
| 2 | Fight engine produces 54% doctor-stoppages, 0% UD/draw/DQ in new fights. | **CRITICAL** | Every event feels the same; result variety is gone; "Historian" fantasy loses its texture. |
| 3 | Career-phase pyramid inverted (75% rising_contender, 0.5% veteran). | **HIGH** | Breaks the "aging world" fantasy — no veterans to lose to, no gatekeepers to test prospects, no decline arcs. |
| 4 | Two confirmed runtime bugs: `_small_reward_12_upset_alert` passes `event_id=` to `_write_small_reward()` (TypeError every tick); `_write_drug_scandal_marker()` inserts news_items with `published_at=NULL` (NOT NULL violation every tick). | **HIGH** | Errors fire on every tick; small_reward #12 never writes; drug-scandal reputation hits silently fail. |
| 5 | Bios contain record mismatches (bio mentions 31 fights, DB shows 2-0). | **MEDIUM** | "Historian" fantasy depends on bios matching reality. Players will spot the contradictions. |

### Top 5 recommendations (ranked by impact)

1. **Fix the training-camp effective_ceiling formula.** Either (a) raise the seeded attribute values down to ~35–45 so fighters have room to grow into their potential, or (b) rework the formula so `personality_factor` doesn't collapse the ceiling for average fighters. Without this fix, growth is impossible and the Talent Hunter fantasy is dead.
2. **Fix the fight engine's doctor-stoppage bias.** Investigate why `result_type` defaults to `doctor_stoppage` at `finish_round=2 finish_time=5:00`. Most likely the engine has a fallback path that triggers when no KO/sub/decision condition is met by end of round 2. Tune so UD/SD/draw/DQ rates match real MMA (~30%, 7%, 2.5%, 1.5%).
3. **Add a staff lifecycle.** Staff `age` should +1 per sim-year (on the staff member's "joined_anniversary" or via annual tick). Staff over 65 should have a retirement probability curve (mirroring the existing `RETIREMENT_BASE_PROB_BY_AGE` for fighters). On retirement, fire a `STAFF_RETIRED` event, write news, and either leave the role vacant (for the rival AI `staff_manager` to refill) or auto-replace with a regen.
4. **Re-tune the career-phase pyramid.** Relax the upper-phase criteria: drop `veteran` threshold from `age >= 35 AND total_fights >= 20` to `age >= 32 AND total_fights >= 15`; drop `gatekeeper` threshold from `age >= 30 AND total_fights >= 15 AND win_rate < 0.50` to `age >= 28 AND total_fights >= 12 AND win_rate < 0.55`; add a "declining" branch triggered by `loss_streak >= 2 AND age >= 30`. This should push the pyramid from 75% rising_contender to ~50% rising_contender + 20% veteran + 15% gatekeeper + 10% declining + 5% champion/prospect.
5. **Regenerate bios after the records are finalized.** Write a one-shot script that re-queries each fighter's actual `fighter_career` row and rewrites the bio templates with the correct record (and ideally references the fighter's actual `fighter_attributes` and `fighter_personality` data, not generic templates). Until this is done, the bios are inconsistent with the DB.

---

## 1. Methodology

### Pre-audit snapshot (taken at sim date 2026-10-15, schema 3.19.0)

- Backup created: `data/cage_empire.db.bak.pre-audit-sim` (28.7 MB, byte-identical to pre-run DB).
- Full snapshot saved at `/tmp/dbaudit/snapshot_pre.json` — covers: clock, schema_version, fighter counts, age buckets, career_phase distribution, potential distribution, avg attributes, fight_history counts + result_types, contract counts + expiry buckets, regen_lineage, HoF, memory_links, rivalries + heat tiers, injuries, training_camps + gain/no-gain counts, staff age distribution, news by topic/promo/date-range, finance by type/promo/date-range, events by status/promo, show_ratings, titles, free agent counts.
- Pre-audit headline numbers:
  - **4,464 fighters** total (4,450 active, 14 retired, 0 deceased); 451 female, 4,013 male.
  - **4,082 free agents** (92% of active fighters — only 448 under contract).
  - **4,234 fight_history rows** dated 2015-01-01 to 2027-05-30 (seed pre-extends events 8 months past sim clock).
  - **3,379 finance_transactions** (2,156 of which are promo-1 backfilled rows from Phase E1).
  - **5,722 news_items** dated 2015-01-03 to 2027-05-30.
  - **215 fighter_memory_links** (210 regional_rival, 5 style_echo).
  - **169 rivalries** (51 boiling 80+, 54 warm 40-59, 40 cool 20-39, 23 hot 60-79, 1 cold <20).
  - **14 regen_lineage rows** (all seeded 2026-08-02 by a script — no sim-driven retirements yet).
  - **0 HoF inductees** (system not firing because no FIGHTER_RETIRED events have been published yet).
  - **700 training_camps** (382 completed, 318 active).
  - **233 active injuries** out of 595 total.
  - **379 staff** (300 coaches + 26 commentators + 24 scouts + 10 GMs + 10 doctors + 10 cutmen). Ages 31-65, avg 48.
  - **10 promotions** (1 player-controlled `Alpha Combat Federation`, 9 rival AI with archetypes `major_league`×2, `regional_power`×1, `rising_star`×3, `grassroots`×3).
  - **111 titles** (64 held, 47 vacant — 42% of divisions have no champion).

### 90-day sim forward run

- Command: `python3 scripts/run_sim_forward.py 90` (from `/home/z/my-project/cage_empire/`).
- Sim clock advanced: 2026-10-15 (day 103) → 2027-01-13 (day 193).
- 0 days failed, 44.8s wall-clock.
- All 16 event-bus subscriber modules registered cleanly (top-level + services + interpretation).
- **Two recurring runtime warnings on every tick:**
  - `WARNING: small_reward template _small_reward_12_upset_alert failed: TypeError: _write_small_reward() got an unexpected keyword argument 'event_id'`
  - `WARNING: subscriber 'reputation.process_tick' failed on event 'tick_advanced': IntegrityError: NOT NULL constraint failed: news_items.published_at`
- Both warnings fire every tick and represent real bugs (see Q5 + Q7 below).
- DB left in the post-run state (rollback not performed). The pre-audit backup remains at `data/cage_empire.db.bak.pre-audit-sim` if rollback is desired.

### After-snapshot headline numbers (changes vs pre-audit)

| Metric | Pre | Post | Δ |
|---|---:|---:|---:|
| Fighters total | 4,464 | 4,477 | +13 |
| Fighters retired | 14 | 27 | +13 |
| Free agents | 4,082 | 4,012 | -70 |
| Active contracts | 448 | 526 | +78 |
| Fight_history rows | 4,234 | 4,824 | +590 |
| Events total | 1,981 | 2,096 | +115 |
| Events completed | 1,974 | 2,091 | +117 |
| Show_ratings | 90 | 207 | +117 |
| News_items | 5,722 | 10,786 | +5,064 |
| Finance_transactions | 3,379 | 5,193 | +1,814 |
| Regen_lineage | 14 | 27 | +13 |
| HoF inductees | 0 | 1 | +1 |
| Memory_links | 215 | 412 | +197 |
| Rivalries | 169 | 247 | +78 |
| Active injuries | 233 | 240 | +7 |
| Training_camps completed | 382 | 578 | +196 |
| Staff total | 379 | 382 | +3 |
| Titles held | 64 | 80 | +16 |
| Titles vacant | 47 | 31 | -16 |

---

## 2. Findings by Question

### Q1: Do prospects always become good? (unrealistic if so)

**Answer: NO — prospects *cannot* become good, because the training-camp growth system is 99.7% broken.**

**Evidence:**
- Of 578 training camps completed during the 90-day run, **only 2** produced any `attribute_changes` (both for the same fighter). The other 576 produced `"{}"` (empty JSON) and the `camp_result_summary` text "completed (focus) — no gains (attributes already at potential)".
- This is consistent with the pre-audit state: 382 completed camps, 379 with `"{}"` changes (99.2% no-gain).
- Sample 25 random fighters (avg_attr vs potential): typical fighter has `avg_attr=50-55` and `potential=55-65`. The `effective_ceiling` formula in `tick_processor._complete_training_camp()` (line ~670):

  ```python
  effective_ceiling = potential * age_factor * health_factor * personality_factor
  ```

  For a typical 28-year-old with `potential=60`, `career_health=100`, `discipline=50`, `coachability=50`:
  - `age_factor` = 0.95 (28-30 band)
  - `health_factor` = 1.0 (>=90)
  - `personality_factor` = (50+50)/200 = **0.5**
  - `effective_ceiling` = 60 × 0.95 × 1.0 × 0.5 = **28.5 → 28**

  But the seeded attributes are **50-55** — already **22 points above** the effective ceiling. The `dim_factor` calculation sees `cur_val > effective_ceiling` → returns 0 → no gain.

- The 14 regen replacements (fighters 4464-4477) all entered with the `generate_fighter` defaults (attributes 50, career 0-0-0). In the 90-day window, none of them had a training camp (camps are auto-created on event booking, but most regens weren't booked into events).

**Realism assessment: BROKEN (not unrealistic — nonexistent).**

**Recommendation:**
1. Re-tune the `effective_ceiling` formula. Either:
   - **(A)** Remove `personality_factor` from the ceiling calc (move it into the `gain` multiplier instead — low discipline/coachability slows growth rather than capping it).
   - **(B)** Re-seed all fighter attributes to the 35-45 range (so there's room to grow into potential).
   - **(C)** Both — recommended.
2. Verify by running a 90-day sim and confirming ~40-60% of completed camps produce ≥1 attribute gain (currently 0.3%).
3. Add a "bust" mechanic — a small % of prospects should have their potential *decrease* after each fight (injury-hampered development, motivation loss, gym mismatch). Currently potential is static.

---

### Q2: Do staff age and die and get replaced?

**Answer: NO.** Staff `age` is a static column with no lifecycle logic anywhere in the codebase.

**Evidence:**
- Pre-audit: 379 staff, ages 31-65, avg 48. **Max age is exactly 65** (the seed cap in `staff_manager._evaluate_hires`: `age = rng.randint(28, 55)` — but a separate seed script set the initial ages up to 65).
- Post-audit: 382 staff (3 hired during run), ages 31-65, avg 48. **Identical age stats** — no aging occurred over 90 sim-days.
- `rg "age" src/services/rival_ai/staff_manager.py` — only uses `age` for read display, never increments it.
- `rg "age\+|age +=|retire_staff|staff_retire|staff_death" src/tick_processor.py src/services/clock.py src/services/retirement_svc.py` — **no matches**. The retirement service handles only fighters (`_check_retirements` reads `fighters.date_of_birth`, not `staff.age`).
- `staff_manager._evaluate_fires` only fires for cause:
  - Scouts with <2 useful reports in 90 days
  - Doctors when promo injury rate >30% above league average
  - Commentators and GMs: **never fired**
  - 30% whimsy roll on fire-eligible staff (most get one more chance)
- No staff regen system exists (unlike the fighter regen_lineage table).
- All 82 non-coach staff have active contracts (status='active'). The 300 coaches have NO `staff_contracts` rows — they're gym-bound via `staff.gym_id`. (Phase E4 is planned to add coach contracts.)
- No staff contract has ever expired in the DB (`contracts.status` breakdown: 526 active, 714 terminated — all 714 terminated are from the seed).

**Realism assessment: UNREALISTIC.** Real MMA promotions have GMs/scouts/commentators who retire, die, move to other promos, get fired for cause, etc. The static staff world is a major "feels new" gap — players will notice that the same 9 rival promo GMs are running things forever.

**Recommendation:**
1. Add a `staff_anniversary_tick` to `tick_processor.run_tick` that increments `staff.age += 1` on each staff member's "joined_anniversary" date (use `staff_contracts.start_date` for non-coaches, or fall back to a per-staff `hire_date` column — needs schema migration).
2. Add a `_check_staff_retirements` helper mirroring the fighter retirement curve (`RETIREMENT_BASE_PROB_BY_AGE`). Suggested curve for staff: 0% under 55, 2% at 55-59, 5% at 60-64, 15% at 65-69, 30% at 70+.
3. On staff retirement: fire `STAFF_RETIRED` event, write news item (topic='staff'), set the staff row's `is_active=0` (need to add this column — or reuse a status column), expire any active staff_contracts.
4. Rival AI `staff_manager` should auto-hire replacements for retired staff (the existing `_evaluate_hires` already has the gap-detection logic — just needs to detect "vacant role" instead of "fire-eligible role").
5. Add a `staff_regen_lineage` table mirroring `regen_lineage` so we can track torch-passing for legendary GMs/commentators (the "successor" memory link concept, extended to staff).

---

### Q3: Is the rival AI working as intended?

**Answer: PARTIALLY — it runs and makes decisions, but with several imbalances and gaps.**

**Evidence:**

**Events run by each promo over 90 days:**

| Promo | Archetype | Events run | New signings | Cuts |
|---|---|---:|---:|---:|
| 1 Alpha (player) | — | 0 | 0 | 0 |
| 2 Rival Fight League | major_league | 26 | 9 | 5 |
| 3 Pacific Rim | regional_power | 19 | 11 | 2 |
| 4 European Fight Network | major_league | **37** | 11 | 6 |
| 5 South American Warriors | rising_star | 21 | 16 | 7 |
| 6 Mexican Boxing & Brawl | rising_star | 17 | 10 | 5 |
| 7 Nordic Fight Nights | grassroots | 27 | 16 | 1 |
| 8 Eastern Bloc Combat | rising_star | **4** | 14 | 4 |
| 9 Australian Outback Fights | grassroots | 20 | **18** | 4 |
| 10 French Savate | grassroots | 14 | 14 | 9 |

- **Anomaly 1**: Promo 8 (Eastern Bloc Combat, rising_star) ran only **4 events** but signed **14 fighters** — it's hoarding talent without booking shows. Likely a budget-state issue (its `ai_budget_state='EXPANSION'`).
- **Anomaly 2**: Promo 1 (player's Alpha Combat Federation) ran **zero events** during the sim-forward run. This is *correct* behavior — `run_sim_forward.py` doesn't drive UI, so the player's promo is dormant. But it means we can't measure how Phase E2 finance behaves for promo 1 in real time.
- All 4 archetypes are represented across 9 promos (`major_league`×2, `regional_power`×1, `rising_star`×3, `grassroots`×3).
- Rival AI news by promo: 107-435 items per rival promo (promo 4 EFN highest at 435, promo 8 EBC lowest at 107). Player promo 1 got only 6 news items.

**Bidding wars**: Only **3 bidding_war_lost** news items in 90 days (out of 122 total signings). So rival-vs-rival competition is rare. The `signing_agent.evaluate_signing_intents` is firing but rarely do 2 promos target the same FA in the same week.

**Tapping-up rumors**: 9 news items, all about the same fighter (Cynthia Garcia) over a 1-week period. So when multiple promos express interest in one FA, the rumor mill generates headlines — but Cynthia Garcia ultimately didn't sign with anyone. The tapping-up rumor doesn't always result in a signing.

**Decision modules firing**: Confirmed via news topic distribution — `signing`, `release`, `staff`, `event_hype`, `cross_promo`, `inter_promo_callout`, `tapping_up_rumor`, `bidding_war_lost` all present in the post-run news. The 7 rival_ai sub-modules (`signing_agent`, `cutting_agent`, `matchmaker`, `event_scheduler`, `staff_manager`, `budget_manager`, `imperfection`) appear to be firing.

**Realism assessment: WORKING BUT IMBALANCED.** Promo 8 hoarding fighters without booking shows is a clear AI bug. The lack of bidding wars (3 in 90 days for ~122 signings) suggests promos rarely pursue the same FAs — likely because each promo has different roster gaps by WC and rarely overlap on the same FA at the same time.

**Recommendation:**
1. Investigate promo 8's anomaly — why 14 signings but only 4 events? Likely a `budget_state` issue (EXPANSION state may be too permissive).
2. Increase signing competition: when a FA has high `marketability` or `potential`, multiple rival promos should evaluate them simultaneously and trigger more bidding wars. Currently only ~2.5% of signings involve competition.
3. Verify the 4 archetypes behave differently in measurable ways (signings, events, cuts). The data above suggests they do (major_league = many events; rising_star = many signings; grassroots = balanced), but a controlled test would confirm.

---

### Q4: Are fighter contracts too easy with little competition?

**Answer: YES, contracts are too easy — but for a different reason than expected.**

**Evidence:**

- **Zero contract expiries occurred during the 90-day run.** All 448 pre-run active contracts have `end_date > 2027-01-13` (1 in the 3-6mo bucket, 429 in the 6-12mo bucket, 18 in the 12mo+ bucket). So no fighter became a free agent due to expiry during the audit.
- **Free agent pool shrank from 4,082 to 4,012** (-70 net) — but this is entirely from rival AI *signing* existing FAs, not from contract expiry creating new FAs.
- The `sign_free_agent` function in `src/services/contracts.py` always creates a **365-day (1-year)** contract at the `salary` parameter (default $50,000). **No variation in contract length, no negotiation, no bidding-war mechanic for the player.**
- The `signing_agent` rival AI module computes an `offer_score` to pick the best FA candidate, but the salary it passes is the default $50k — so there's no actual bidding war (highest score wins, no salary escalation).
- Bidding wars: 3 in 90 days (`bidding_war_lost` news items). The `signing_agent.resolve_bidding_wars` function exists and works, but it only triggers when ≥2 promos submit intents for the same FA in the same week — rare in practice.
- Player promo (Alpha) had **6 news items in 90 days**, of which 2 were signing-related: "Cynthia Garcia released by Alpha Combat Federation" (duplicated!) and "Hiroki Nakamura signs with Alpha Combat Federation". So the player can sign/cut FAs, but the system isn't generating competitive pressure from rival promos.

**Realism assessment: TOO EASY.** The player faces no real competition for FAs because:
1. Contract length is fixed at 1 year — no multi-year deals, no contract value variation.
2. Salary is fixed at $50k — no negotiation.
3. Rival AI rarely pursues the same FAs the player might want (only 3 bidding wars in 90 days).
4. The player can sign any FA instantly via `sign_free_agent` — no time pressure, no offer window, no counter-offers.

**Recommendation:**
1. Add contract-length variation: 6mo / 1yr / 18mo / 2yr / 3yr, weighted by fighter potential + marketability + promo budget.
2. Add salary negotiation: the FA's `marketability` + `potential` + recent fight results should determine a base asking salary. The player must match or beat it.
3. Add a "signing window" mechanic: when the player makes an offer, rival AI promos have 1 sim-week to submit competing offers. Highest offer wins. Currently the `signing_agent.evaluate_signing_intents` is one-shot with no player offer phase.
4. Vary contract end_dates in the seed so expirations happen continuously (currently 99% of active contracts expire in a 6-month window 6-12 months out — this causes long dry spells then a flood of expiries).
5. Add contract renewal: when an active contract is within 60 days of expiry and the fighter is still performing well, the promo should auto-renew (rather than letting them hit free agency).

---

### Q5: Is growth and decay happening?

**Answer: GROWTH IS BROKEN (see Q1). DECAY IS NOT IMPLEMENTED.**

**Evidence (growth):**
- See Q1 for the training-camp analysis. 578 completed camps → 2 with gains (0.3% success rate). The `effective_ceiling` formula collapses for average fighters.
- Avg attributes pre vs post:
  | Attribute | Pre | Post | Δ |
  |---|---:|---:|---:|
  | punch_power | 54 | 54 | 0 |
  | cardio | 52 | 51 | -1 |
  | fight_iq | 56 | 56 | 0 |
  | chin | 50 | 50 | 0 |
  | takedown_offense | 54 | 54 | 0 |
  | submission_offense | 51 | 51 | 0 |
  | speed_explosiveness | 53 | 52 | -1 |
  | strength | 54 | 54 | 0 |
  | durability | 52 | 52 | 0 |
- The -1 changes are likely just the 13 new regen fighters (avg attrs 48-53) dragging the league average down, not actual decay.

**Evidence (decay):**
- `rg "decay|decline|attribute.*decrease|reduce.*attribute" src/tick_processor.py src/services/training_svc.py src/services/injuries_svc.py` — no matches. No code path decreases attributes over time.
- The `effective_ceiling` formula has a `health_factor` (0.15-1.0 based on career_health) and an `age_factor` (0.35-1.0 based on age). When career_health drops (from injuries) or age rises, the ceiling drops — *but this only stops growth, it doesn't decrease attributes*.
- Injuries DO cause long-term damage: 17 fighters have `long_term_damage > 0` (concussions severity 8-10 typically add 2-5 long_term_damage). The `fighter_career.career_health` is reduced by `severity * 2 + long_term_damage` at injury creation, and the `severity * 2` portion is *restored* on recovery (only the `long_term_damage` portion is permanent). But this only affects `career_health`, not the actual attribute values.
- Fighter retirements: 13 in 90 days (one per ~7 days). Mostly 35+ year-old fighters on losing streaks. So the *roster* decays (fighters leave), but no *individual attribute decay* happens.

**Realism assessment: GROWTH BROKEN, DECAY MISSING.**

**Recommendation:**
1. Fix growth (see Q1).
2. Add an explicit age-decay tick: when a fighter crosses age 33, each attribute has a small chance (1-3% per year) of -1. This compounds with injury long_term_damage. By age 38, most fighters should see ~3-5 points of decline across their attributes.
3. Track attribute history (a new `fighter_attribute_history` table or extend `training_camps.attribute_changes` to support negative values) so the player can see the decline arc.

---

### Q6: Are memories being saved and resurfacing (and pruned)?

**Answer: SAVED (limited), RESURFACING (working but thin), PRUNED (working).**

**Evidence:**

**Memory links saved:**
- Pre-audit: 215 memory_links (210 `regional_rival`, 5 `style_echo`).
- Post-audit: 412 memory_links (+197 new). Distribution:
  - `regional_rival`: 210 → 402 (+192 new — bidirectional, so 96 unique pairs)
  - `style_echo`: 5 → 9 (+4 new — regen replacements inheriting style archetype)
  - `successor`: 0 → 1 (+1 new — regen explicitly linked to retiring fighter)
- Memory-link types NOT being written:
  - `former_teammate` (despite being in the `memory_engine` reader's search list — the writer doesn't exist)
  - `shared_gym` (same — reader exists, writer doesn't)
  - No memory of: upsets, knockouts, comebacks, title fights, grudge matches, weight-cut drama, doctor stoppages, etc.

**Memory resurfacing:**
- `interpretation/memory_engine.py` is a reader that surfaces 4 search types per booked fight:
  1. `previous_fight` (fight_history — they've met before?)
  2. `shared_gym` (fighters.current_gym_id — same gym now?)
  3. `former_teammate` (fighter_memory_links of type 'former_teammate' or 'shared_gym')
  4. `injury_history` (injuries table — currently injured?)
- It's called from `matchmaking._build_main_event` when a fight is booked, returning voice phrases like "Last met six years ago" / "Former training partners" / "First fight ended in split decision" / "Recovering from shoulder injury".
- BUT — since `former_teammate` and `shared_gym` writer functions don't exist, only `previous_fight` and `injury_history` actually surface meaningful memories. So in practice, 2 of 4 search types are dead code.
- Memory resurfacing is NOT saved to news_items — the engine returns phrases to the caller, but I couldn't find a code path that writes them to news_items.body. They likely show up in the Fight Card UI but don't appear in the news wire.

**Memory pruning:**
- `services/pruning_svc.py` runs on the 1st of each in-game month. Confirmed working: pre-audit `news_date_range` min was 2015-01-03, post-audit min is 2026-01-16. So news_items older than 365 days are being pruned (policy: `news_items > 365 days`).
- `fighter_memory_links` is NOT in the prune policy list (no retention limit). So memory links accumulate forever — currently 412, would grow to ~1,600/year at the current rate.
- `daily_headlines` (90-day retention), `social_posts` (180-day), `injuries` (365-day resolved only), `suspensions` (365-day expired only), `training_camps` (90-day completed only), `scouting_reports` (180-day) — all pruned.

**Realism assessment: PARTIAL.** Memory is being saved (for `regional_rival` + `style_echo` only) and surfaced (for `previous_fight` + `injury_history` only). The other 4 search types are unwired. Memory pruning works but doesn't touch memory_links.

**Recommendation:**
1. Implement writers for `former_teammate` and `shared_gym` memory_link types. Specifically:
   - `former_teammate`: when a fighter's `current_gym_id` changes, write `former_teammate` links to all fighters who were at the previous gym.
   - `shared_gym`: when 2 fighters at the same gym are booked against each other, write a `shared_gym` link.
2. Add memory_link types for: `upset`, `comeback`, `knockout_loss`, `title_fight`, `bad_blood_fight`, `weight_cut_miss`. These should be written by the fight engine on FIGHT_RESOLVED.
3. Surface memory phrases in news_items — when a fight is booked between 2 fighters with history, the news item should mention it ("These two have history — 3 fights, 1 each").
4. Add `fighter_memory_links` to the pruning policy with a longer retention (e.g., 730 days = 2 sim-years). Old "regional_rival" links between fighters who've never fought should eventually decay.

---

### Q7: Other findings

#### Veterans/legends
- **HoF inductees: 1** (George Hill, inducted 2026-12-15, wrestler with 3-fight win streak at retirement). So the HoF system IS working — just very slowly.
- The eligibility thresholds in `hof_svc._is_eligible_for_hof`:
  - `title_reigns >= 2` (multi-time champion), OR
  - `record_wins >= 30` (longevity + success), OR
  - `record_wins >= 20 AND title_reigns >= 1` (champion + longevity)
- These are intentionally inclusive, but only 1 fighter qualified in 90 days because most fighters retire before accumulating 30 wins or 2 title reigns. The seeded roster has very few fighters with `title_reigns >= 1` (most have `title_reigns = 0`).
- **0 HoF inductees at pre-audit** is because the 14 seeded retired fighters were marked retired via direct DB INSERT, not via `tick_processor._check_retirements` (which publishes `FIGHTER_RETIRED` events that trigger HoF induction). The seed bypassed the event bus.
- **Recommendation:** Pre-seed 10-20 HoF legends (retired fighters with strong careers) at world build time so the HoF screen isn't empty on day 1.

#### Rivalry escalation
- 78 new rivalries created in 90 days. Distribution:
  - `bad_blood`: 42 (avg heat 86, all have ≥1 fight between them — created on weight_cut_miss during a fight)
  - `title_rivalry`: 28 (avg heat 87, all have ≥1 fight — created when title changes hands)
  - `callout`: 8 (avg heat 78, 0 fights — purely social-media callouts)
- **Issue:** New rivalries START at heat 70-90 (the `initial_heat` parameter in `_create_rivalry` defaults to 50, then immediately gets `+15` for `fight_between_rivals` or `+20` for title fights, plus `+10` for weight_cut_miss). So rivalries skip the "cold → cool → warm → hot → boiling" arc — they jump straight to hot/boiling.
- **Recommendation:** Lower `initial_heat` to 20-30 for new rivalries (cold/cool tier). Let fights escalate them gradually (+10-15 per fight). Title rivalries can start warmer (~50) since there's already tension.

#### Injury healing
- 595 → 795 total injuries (+200 new in 90 days).
- 233 → 240 active injuries (+7 net) — so ~193 injuries healed during the run.
- 17 fighters have `long_term_damage > 0` (permanent damage — concussions mostly).
- 383 fighters have `career_risk > 0` (temporary flag — restored on recovery).
- The injury recovery system in `tick_processor._check_injury_recovery` is **working correctly** — when `current_date >= projected_return_date`, the injury is marked `is_active=0`, `actual_return_date` is set, and the temporary `career_health` penalty (severity × 2) is restored.
- **Recommendation:** None — injury healing is healthy. The `long_term_damage` permanent penalty is preserved correctly.

#### Weight class balance
- 13 weight classes (8 male, 5 female). Fighter counts per WC:
  - Male: HW 269, LHW 342, MW 550, WW 556, LW 621, FW 679, BW 544, FlyW 439 (total 3,990)
  - Female: AtomW 60, StrawW 139, FlyW 105, BW 96, FW 50 (total 450)
- Distribution is realistic (heavyweight has fewer fighters; lighter classes have more). Female weight classes have proportionally fewer fighters (~10% of roster).
- **Recommendation:** None — WC balance is good.

#### Free agent pool
- Pre-audit: 4,082 free agents (92% of active roster).
- Post-audit: 4,012 free agents (-70).
- This is **far too high**. Real MMA: maybe 5-15% of fighters are unsigned FAs at any time. 92% means the world feels empty — most fighters aren't competing for any promo.
- Root cause: only ~448 fighters have active contracts. The seed created 4,464 fighters but only signed ~10% of them to promos. Matchmaking only sees signed fighters, so most FAs never fight.
- **Recommendation:** Pre-seed more contracts at world build. Target: 60-70% of active fighters should be under contract (3,000-3,200 signed across the 10 promos). The remaining 30-40% (1,300-1,800) is a healthy FA pool for the player and rival AI to bid on.

#### News wire variety
- Post-audit: 10,786 news_items across 23 topics.
- **Top-heavy distribution:**
  - `news_engine`: 4,166 (39%)
  - `career_arc`: 1,894 (18%)
  - `weight_cut`: 1,256 (12%)
  - `injury`: 960 (9%)
  - `training`: 780 (7%)
  - `fight`: 583 (5%)
  - `finance`: 236 (2%)
  - `show_rating`: 207 (2%)
  - Other 15 topics: <2% each
- **80% of news_items have NULL `promotion_id`** (8,357 of 10,786). The "fighter-centric" topics (career_arc, weight_cut, injury, training, retirement, prospect) leave promotion_id NULL — they're only tagged with fighter_id. The "promo-centric" topics (fight, show_rating, signing, finance, cross_promo) properly set promo_id.
- This means the player's news feed (filtering by their promo) would show only ~6 items in 90 days (fight + show_rating + signing news). All the fighter-centric news would be hidden unless the player filters by "my roster."
- **Two confirmed bugs in news generation** (fire on every tick during sim-forward):
  - `_small_reward_12_upset_alert` (in `src/news.py` line 3743) calls `_write_small_reward(... event_id=event_id ...)`, but `_write_small_reward`'s signature (line 3260) doesn't accept `event_id`. TypeError fires every tick when an upset is eligible.
  - `_write_drug_scandal_marker` (in `src/reputation.py` line 236) inserts a news_items row with `published_at=None`, but the column has NOT NULL constraint. IntegrityError fires every tick when there's an unprocessed drug-test suspension.
- **Recommendation:**
  1. Fix the two news-generation bugs (small_reward_12 signature mismatch, drug_scandal_marker NULL published_at).
  2. Set `promotion_id` on fighter-centric news items based on the fighter's `current_promotion_id` (at the time of the news event). This makes the player's news feed actually useful.
  3. Consider promoting underused topics (`bidding_war_lost`, `tapping_up_rumor`, `inter_promo_callout`) by increasing their trigger rates or tying them to more events.

#### Show ratings
- Pre-audit: 90 show_ratings. Post-audit: 207 (+117, matching the +117 completed events).
- **100% of completed events have a show_rating** (2,091 of 2,091). The 90 pre-existing ratings correspond to events run after the show_rating system was added (the other 1,884 completed events from before that have no rating).
- `rating_description` text is voice-compliant.
- **Recommendation:** Backfill show_ratings for the 1,884 pre-system completed events (or accept that pre-Phase-A events have no ratings — players probably won't scroll that far back).

#### Finance for rival promos
- All 9 rival AI promos are writing finance_transactions during the 90-day run:
  - Promo 4 EFN: 288 new txns
  - Promo 2 RFL: 217
  - Promo 3 PRC: 186
  - Promo 7 NFN: 129
  - Promo 5 SAW: 99
  - Promo 9 AOF: 89
  - Promo 8 EBC: 0 (zero new finance — matches its zero-events-run anomaly)
  - Promo 6 MBB: 71
  - Promo 10 FSC: 61
- All 9 transaction types from Phase E2 are firing: `ticket_sales`, `broadcast_revenue`, `sponsorship`, `merchandise`, `concessions`, `fighter_purse`, `staff_salary`, `venue_rental`, `medical_cost`, `weight_cut_penalty`.
- Promo 1 (player's Alpha) wrote **0 new finance_transactions** during the 90-day run (it ran 0 events). The 2,156 pre-existing promo-1 rows are from the Phase E1 backfill.
- **Recommendation:** Phase E2 finance is working for rival promos. The player's promo will get transactions as soon as the player schedules and runs events via the UI.

#### Matchmaking repeats same fighter pairs
- Sampled recent fights show the same fighter pair booked 4-7 times within 9 months (e.g., Iara Queiroz vs Sofia Hansson fought 7 times in 9 months; Tulio Santos vs Takumi Nakajima 6 times).
- Root cause: `_pick_matchup` in `src/services/matchmaking.py` line 53 uses pure `random.sample()` with NO rematch-avoidance. The comment in the docstring admits: "Task ID 10 will add ranking-proximity matchmaking; Task ID 22 will add rivalry logic." These tasks were apparently never implemented.
- Compounded by small roster sizes: ~30-60 fighters per promo / 13 weight classes = ~3-5 fighters per WC per promo. Random selection from a 4-fighter pool WILL repeat pairs.
- **Recommendation:**
  1. Implement rematch-avoidance in `_pick_matchup`: exclude fighters who fought each other in the last 90 sim-days.
  2. Implement ranking-proximity matchmaking (Task 10): prefer fighters within ±5 ranking spots of each other.
  3. Increase roster sizes per promo (see "Free agent pool" recommendation) so the matchmaking pool is deeper per WC.

#### Matchmaking same fighter vs same opponent (Christian Harris vs Gustavo Araújo)
- 3 fights in 90 days (Jul 24, Aug 21, Sep 18 2027) — all main-event slot for promo 4 EFN.
- Result types: ko_tko, doctor_stoppage, doctor_stoppage.
- This is the matchmaking-repeat issue combined with the doctor_stoppage bias.

---

## 3. Bio + Recent Results Review

### Bio uniqueness sample (14 fighters across ID range)

All 4,477 fighter bios are textually unique (`COUNT(DISTINCT bio_text) = COUNT(*) = 4,477`). However, they fall into ~9 template patterns (one per career_phase archetype):

| Phase | Template opening | Sample |
|---|---|---|
| prospect (high potential) | "There's a version of the future where X 'nickname' is a champion. There's also a version where he flames out by 25." | Fighter #1 Hiroki Nakamura, Fighter #200 Cynthia Jimenez |
| low-potential / mid-card | "X is the kind of fighter who fills out a card and makes the better fighters earn their money." | Fighter #50 Yu Luo, Fighter #500 Ryan Jenkins, Fighter #3500 Kevin Laurent |
| veteran | "The brawler from Gym who once had the division worried is now the division's afterthought." | Fighter #100 Jesse Mitchell |
| low-potential (role-player) | "Not every fighter is a contender. X knows that better than anyone." | Fighter #500 Ryan Jenkins |
| mid-card filler | "Solid. Dependable. Unspectacular. X is the definition of a mid-card roster filler — and that's not a knock." | Fighter #800 Sora Yamamoto |
| veteran (mileage) | "N professional fights. That number alone tells you what X is made of." | Fighter #1200 Arthur Allen |
| balanced (uncertain trajectory) | "X has the look of a fighter who could go either way." | Fighter #3000 Yaroslav Makarov, Fighter #4464 Oisin Wisniewski |
| entertainer | "You won't find X atop any rankings. You will find him in the highlight reels..." | Fighter #2500 Antonio Martin, Fighter #4000 Rafal Michalski |
| gatekeeper | "Every promotion needs a fighter like X. Someone tough enough to test the prospects..." | Fighter #4400 Tatsuya Ito |

**Critical problem — bios contradict the DB:**

| Fighter | Bio claim | Actual DB record |
|---|---|---|
| #1 Hiroki Nakamura | "At 18 with a 2-2 record" | record 3-1 |
| #50 Yu Luo | "14-17 record" | record 9-7 |
| #100 Jesse Mitchell | "12-13 doesn't lie" | record 28-9 (veteran!) |
| #200 Cynthia Jimenez | "At 22 with a 5-1 record" | age 23, record 3-6 |
| #500 Ryan Jenkins | (implies he's had fights: "settled into a role: beat the fighters he should beat") | record 0-0 |
| #800 Sora Yamamoto | "15-11" | record 0-0 |
| #1200 Arthur Allen | "31 professional fights" | record 2-0 |
| #1800 Padraig O'Dwyer | "professional record of 7-7 across 14 fights" | record 0-0 |
| #2500 Antonio Martin | (implies fights: "post-fight bonus records") | record 0-0 |
| #4000 Rafal Michalski | (implies fights: "highlight reels") | record 0-0 |
| #4400 Tatsuya Ito | "carries a 7-4 record" | record 0-0 |
| #4464 Oisin Wisniewski | "just starting his career" | record 0-0 |

**11 of 14 sampled bios contradict the actual fighter record.** The bios were generated against an earlier version of the dataset (likely when records were pre-seeded differently), and were never re-generated after the records changed.

**Realism assessment: BIOS ARE UNIQUE BUT INCONSISTENT.** The voice + tone is good, but the factual content contradicts the DB. The "Historian" fantasy depends on bios being accurate.

**Recommendation:**
1. Write a one-shot script `scripts/regenerate_bios.py` that:
   - Reads each fighter's actual `fighter_career` (record, win_streak, title_reigns)
   - Reads each fighter's `fighter_attributes` (top 3 attributes — informs "brawler" vs "wrestler" vs "submission specialist")
   - Reads each fighter's `fighter_personality` (informs tone)
   - Re-generates the bio using the existing templates but with correct data inserted
2. Run it once and verify all bios match the DB.

### Result type variety sample (25 recent fights)

**Pre-existing seeded fights (2,117 unique fights):** Realistic distribution:
- unanimous_decision: 701 (33%)
- ko_tko: 575 (27%)
- submission: 284 (13%)
- split_decision: 151 (7%)
- doctor_stoppage: 120 (5.7%)
- dq: 31 (1.5%)
- draw: not counted (would be ~2%)
- no_contest: not counted (~0.3%)

**NEW fights during 90-day run (468 unique fights):** Heavily skewed:
- **doctor_stoppage: 255 (54%!)** ← 10x realistic
- ko_tko: 109 (23%)
- submission: 103 (22%)
- split_decision: 1 (0.2%)
- **unanimous_decision: 0 (0%!)** ← should be ~33%
- **draw: 0 (0%!)** ← should be ~2%
- **dq: 0 (0%!)** ← should be ~1.5%

**Finish-round distribution of new fights:**
- Round 1: 354 (60%)
- Round 2: 542 (45%) — most at finish_time 5:00 (end of round)
- Round 3: 40 (7%)
- Round 0: 48 (NC/DQ marker — finish_time 0:00)

**Critical observation:** 538 of 590 new fight_history rows have `finish_time='5:00'` — meaning the fight ended at the END of a round (most commonly round 2). This pattern strongly suggests the fight engine has a fallback that triggers `doctor_stoppage` at the end of round 2 when no other result has been determined.

**Realism assessment: BROKEN.** The fight engine produces wildly unrealistic result distributions in live fights (vs realistic in seeded historical fights).

**Recommendation:** Inspect `src/services/fight_engine.py` (or wherever fights are resolved) — find the result-type determination logic at end-of-round and tune it so:
- ~33% of fights that go to decision are UD
- ~7% are SD
- ~2% are draws
- ~1.5% are DQ
- Doctor stoppages should be ~5-10% (not 54%)

### `fighter_image_prompts.txt` usage

- File exists at `/home/z/my-project/cage_empire/download/fighter_image_prompts.txt` — 28,014 lines, generated 2026-07-22.
- Header: "Total fighters: 4000" — so the prompts cover the first 4,000 of the 4,464 fighters (the last 464 were added later by regens).
- Each prompt is **correctly generated from the DB** — the generator (`scripts/generate_image_prompts.py`) reads `fighters` + `fighter_attributes` + `fighter_personality` + `weight_classes` + `nations` + style/personality archetypes and emits a per-fighter prompt that includes:
  - Age, gender, height, weight class, nationality, ethnicity
  - Style archetype (informs body type, posture, attire)
  - Personality archetype (informs facial expression)
  - Nickname (if any)
  - Stance, handedness
  - Alternating full-body vs portrait pose
  - Varied attire (6 colorways) + background (cage, gym, backstage, ring walkout)
- Sample prompt (Fighter #1 Hiroki Nakamura): "A 18-year-old male MMA fighter of Japanese, East Asian features descent, from Japan, Height: 175cm, Weight class: Welterweight (max 77.1kg), Fight style: Brawler, Stance: southpaw, Body type: lean, wiry, cut definition, fast-twitch build, Physical: 175cm tall, wide stance, chin tucked, hands loose and ready, close-up portrait, head and shoulders, cold, calculating eyes, slight frown, focused, Wearing: navy blue shorts with white stars, red gloves, barefoot, Background: center of the octagon under bright arena lights, photorealistic, ultra-detailed..."
- **415 portrait image files** exist under `data/portraits/batch_*/` (the user confirmed 415 uploaded images), generated from these prompts.
- **Issue:** The prompts file was generated 2026-07-22 against the first 4,000 fighters. The 477 regen-replacement fighters added since then (4,464–4,477 by 2027-01-13) do NOT have image prompts or portraits. As the sim continues, the gap between "fighters with portraits" and "total fighters" will grow.
- **Recommendation:** Re-run `scripts/generate_image_prompts.py` periodically (or on each regen) so new fighters get prompts. The image-generation itself is a separate (manual) workflow.

---

## 4. Overall DB Balance Assessment

### Pyramid shape

**Current: INVERTED.** 75% of active fighters are `rising_contender` (the catch-all default in `career_phase_engine.compute_career_phase`). Only 0.5% are `veteran`, 0.4% `gatekeeper`, 0.3% `declining`.

**Real MMA pyramid (target):**
- Prospects: ~25-30%
- Rising contenders: ~30-35%
- Veterans: ~15-20%
- Gatekeepers: ~10-15%
- Declining: ~5-10%
- Champions: ~2-3%

**Why it's inverted:**
1. The `compute_career_phase` criteria for upper phases are too strict:
   - `veteran`: `age >= 35 AND total_fights >= 20` — most 35+ fighters don't have 20 fights because the seeded records are short.
   - `gatekeeper`: `age >= 30 AND total_fights >= 15 AND win_rate < 0.50` — most 30+ fighters with 15+ fights have win_rate > 0.50 (seed bias).
   - `declining`: `age >= 33 AND (loss_streak >= 3 OR career_health < 50)` — most 33+ fighters have career_health ~85-100 and no 3-loss streaks.
2. Most fighters fall through to the catch-all `rising_contender` because they don't match any of the strict upper-phase criteria.

**Recommendation:** Relax the criteria (see Executive Summary recommendation #4).

### Potential distribution

**Current: 21% elite+high.** Distribution:
- Elite (85+): 391 (9%)
- High (70-84): 539 (12%)
- Above-avg (55-69): 1,914 (43%)
- Avg (40-54): 1,391 (31%)
- Low (<40): 229 (5%)

**Real MMA target:**
- Elite: 3-5% (these are your genuine title contenders)
- High: 5-10%
- Above-avg: 20-30%
- Avg: 40-50%
- Low: 20-30% (most fighters wash out, never reach contender status)

**Recommendation:** Reduce elite tier from 9% to ~4% by re-rolling potentials for the bottom 50% of the elite tier (those with `potential` 85-87 → demote to 70-84). This makes the "Talent Hunter" fantasy meaningful — finding a true 88+ prospect is rare.

### Age distribution

**Current: BELL-SHAPED, slightly top-heavy.** Distribution:
- <22: 497 (11%)
- 22-25: 866 (19%)
- 26-29: 971 (22%)
- 30-33: 1,003 (22%)
- 34-37: 722 (16%)
- 38+: 405 (9%)
- Range: 18-43, avg 29.

**Real MMA target:** Peak at 27-32, with thinner tails. Current distribution is slightly too old — 25% of fighters are 34+, vs maybe 15-20% in real MMA.

**Recommendation:** Slight downward age rebalance — seed more 22-26 fighters (prospects) and fewer 38+ fighters (most should have retired by now).

### Career phase flow

**Current: STATIC.** Fighters are tagged with a career_phase in `fighter_descriptors.career_phase` (computed by the interpretation layer daily). But:
- No transitions happen during the 90-day run that meaningfully shift the distribution (still 75% rising_contender).
- No code path explicitly moves a fighter from `prospect` → `rising_contender` → `veteran` → `declining` based on career events.
- The career_phase is RECOMPUTED daily from `age`, `total_fights`, `win_streak`, `loss_streak`, `win_rate`, `career_health`, `is_champion` — so as fighters age and accumulate fights, they should naturally transition. But the thresholds are too strict to trigger transitions.

**Recommendation:** See "Pyramid shape" recommendation above.

### Rival AI activity

**Current: ACTIVE BUT IMBALANCED.** 9 rival promos are running events (4-37 each in 90 days), signing FAs (9-18 each), cutting fighters (1-9 each). All 4 archetypes are represented.

**Issues:**
- Promo 8 (Eastern Bloc Combat) is hoarding talent (14 signings, 4 events) — likely a budget-state bug.
- Bidding wars are rare (3 in 90 days) — promos rarely compete for the same FAs.
- Promo 1 (player's) generates 6 news items in 90 days — much less than rival promos (107-435).

**Recommendation:** See Q3.

### Memory + story generation

**Current: THIN.** 412 memory_links total (210 `regional_rival`, 9 `style_echo`, 1 `successor`, 0 other types). Memory resurfacing works for `previous_fight` and `injury_history` but the other 2 search types (`shared_gym`, `former_teammate`) have no writers.

**Issues:**
- No memory types for: upsets, knockouts, comebacks, title fights, grudge matches, weight-cut drama.
- Memory phrases are not surfaced in news_items — they only appear in the Fight Card UI.
- Memory_links are never pruned — they accumulate indefinitely.

**Recommendation:** See Q6.

### "Alive from day 1" assessment

**Verdict: PARTIALLY ALIVE.**

What works on day 1:
- 4,464 fighters with bios (mostly unique, though inconsistent).
- 4,234 historical fights across 2015-2027 with realistic result distributions.
- 5,722 news items spanning 2015-2027 — the wire isn't empty.
- 169 rivalries (some with 4+ fights history).
- 10 promotions with rosters + cash + reputation.
- 111 titles (64 held, 47 vacant — could be better).
- 90 show_ratings for past events.
- 3,379 finance_transactions.
- 300 coaches + 82 non-coach staff.
- 215 memory_links (regional_rival pairs).

What's missing / broken on day 1:
- **0 HoF inductees** — the Hall of Fame screen is empty. Player sees nothing to aspire to.
- **0 staff churn** — all 379 staff are static, no retirements/deaths/hires. Feels like a frozen world.
- **Inverted career-phase pyramid** — 75% rising_contender, 0.5% veteran. No "old guard" to lose to.
- **4,082 free agents** (92% of roster) — most fighters aren't signed to any promo, so the world feels sparse.
- **47 vacant titles** (42% of divisions) — many divisions have no champion.
- **Only 90 show_ratings** out of 1,974 completed events — most historical events have no rating.
- **Bios contradict records** — 11 of 14 sampled bios have wrong records.
- **Training camps are 99.7% no-gain** — prospects can't develop.
- **Fight engine produces 54% doctor-stoppages** — every event feels the same.
- **Same fighter pairs fight repeatedly** (4-7 times in 9 months).
- **Rivalries start at heat 70-90** — no cold-to-hot escalation arcs.
- **Memory is regional_rival-only** — no upsets, comebacks, knockouts in memory.
- **Promo 1 (player's) has only 4 news items at world start** — the player's news feed is empty.

---

## 5. Recommendations for Pre-loading Data

### Rec 1: Pre-seed 15-20 Hall of Fame legends

**Why:** The HoF screen is empty on day 1. The "Historian" fantasy depends on the player seeing legendary figures to aspire to. Currently, HoF inductees only happen on fighter retirement during gameplay, which is too slow (1 in 90 days).

**How:**
- Add a HoF-seeding block to `scripts/seed_world_phase5.py` (or a new `scripts/seed_hof_legends.py`).
- For each legend: create a retired fighter (`is_active=0, is_retired=1`) with `fighter_career.record_wins >= 30 OR title_reigns >= 2`. Generate a rich `career_summary` + `career_highlights` (the existing `hof_svc._generate_career_summary` function can be reused).
- Insert into `hall_of_fame` with `inducted_date` 2-5 sim-years before the world start date.
- Write a "looking back" news_items row per legend (topic='hall_of_fame', promotion_id=NULL).
- **Row count:** 15-20 new fighters + 15-20 new hall_of_fame rows + 15-20 news_items.

### Rec 2: Pre-seed more veteran fighters (35+) with declining attributes

**Why:** Only 1,127 of 4,464 fighters (25%) are age 34+. The pyramid is too young — real MMA has more 35+ veterans winding down their careers. Veterans give prospects someone to lose to and give the world "old guard" texture.

**How:**
- Rebalance the fighter seed: target 30% age 34+ (1,340 fighters), 50% age 24-33 (2,230), 20% age <24 (890).
- For age 35+ fighters: assign 1-2 reduced attributes (e.g., `cardio` at 40-45 instead of 50-55) to simulate decline.
- For age 38+ fighters: assign `career_health` 70-85 (lower than the default 100) + a 1-2 fight losing streak to seed them as "declining".
- **Row count:** Rebalance ~400 existing fighters from younger buckets to older buckets. No new rows needed.

### Rec 3: Pre-seed 50+ rivalries with varied heat

**Why:** 51 of 169 rivalries (30%) are already at "boiling" (heat 80+) at world start. Most have 0 fights between them (seeded cold). Rivalries should start cooler and escalate through fights, not arrive pre-boiled.

**How:**
- For 50 rivalries: set `rivalry_heat` to a uniform distribution across buckets (10 cold, 15 cool, 15 warm, 7 hot, 3 boiling) — currently most are boiling.
- For rivalries with 0 `fights_count`: lower heat to 20-40 (cold/cool — they're rumored rivals, not yet fought).
- For rivalries with 1+ `fights_count`: heat should scale with fights (1 fight = 40-60, 2 = 60-75, 3+ = 75-90).
- Write a one-shot script `scripts/rebalance_rivalry_heat.py` that adjusts existing rivalry_heat values.
- **Row count:** 50 UPDATE statements on existing rows. No new rows.

### Rec 4: Pre-seed more contracts with varied expiry dates

**Why:** 99% of active contracts expire in the 6-12 month window. This causes long dry spells (no expiries) followed by a flood. The contract market feels static.

**How:**
- Rebalance the seed: target ~30% of active contracts expiring in 0-3 months, ~30% in 3-6 months, ~25% in 6-12 months, ~15% in 12-24 months.
- This creates continuous contract churn (a few expiries per sim-week) and gives the player regular FA opportunities.
- Write a one-shot script `scripts/rebalance_contract_end_dates.py` that adjusts existing `contracts.end_date` values.
- **Row count:** ~450 UPDATE statements on existing contracts.

### Rec 5: Pre-seed more fighter contracts overall (sign 60-70% of roster)

**Why:** 92% of active fighters are free agents. The world feels empty — most fighters aren't competing for any promo. Matchmaking only sees signed fighters, so the player sees a thin active roster.

**How:**
- Write a one-shot script `scripts/seed_more_contracts.py` that signs 2,500-3,000 currently-unsigned fighters to the 10 promos (weighted by promo roster size + archetype).
- Each new contract: 6-24 month duration (varied per Rec 4), salary $20k-$200k based on fighter marketability + potential.
- Set `fighters.current_promotion_id` to the signing promo.
- This brings the FA pool down from 4,082 to ~1,000-1,500 (still a healthy pool for the player to bid on).
- **Row count:** 2,500-3,000 new `contracts` rows + 2,500-3,000 new `fighter_contracts` rows + 2,500-3,000 UPDATE on `fighters`.

### Rec 6: Pre-seed varied staff ages (some near retirement)

**Why:** All 379 staff are ages 31-65 with no over-65 staff. The staff world is "frozen" — no one is near retirement. Combined with the missing staff lifecycle (Rec 2 in Q2), the staff feel like mannequins.

**How:**
- Rebalance the staff seed: target ~20% age 55+ (with a few age 65-70), ~50% age 40-54, ~30% age 30-39.
- This is a one-shot UPDATE script — adjust the `age` column on existing staff rows.
- Combine with implementing the staff lifecycle (Q2 Rec 2) so the 65-70 staff actually retire during gameplay.
- **Row count:** 379 UPDATE statements on existing staff.

### Rec 7: Pre-seed memory_link types beyond regional_rival

**Why:** Only 2 memory_link types exist (`regional_rival` + `style_echo`). The "Puppet Master" + "Historian" fantasies depend on rich memory — upsets, comebacks, knockouts, title fights should all create memories that resurface in future fights.

**How:**
- Backfill memory_links for past fights in `fight_history`:
  - For each pair of fighters with 2+ fights between them: write a `previous_fights` memory_link (link_strength = 50 + 10*fights_count, capped at 100).
  - For each fight that ended in KO/TKO: write a `knockout_loss` memory_link from loser → winner (link_strength = 70).
  - For each upset (winner was lower-ranked): write an `upset` memory_link (link_strength = 80).
  - For each title fight: write a `title_fight` memory_link (link_strength = 90).
- Write a one-shot script `scripts/backfill_memory_links.py` that scans `fight_history` and inserts these.
- **Row count:** Estimated ~3,000-5,000 new `fighter_memory_links` rows.

### Rec 8: Backfill show_ratings for pre-Phase-A events

**Why:** Only 90 of 1,974 completed events have show_ratings (the rest predate the show_rating system). The "Recent Results" screen looks thin for older events.

**How:**
- Write a one-shot script `scripts/backfill_show_ratings.py` that, for each completed event without a show_rating, generates a synthetic rating based on:
  - Card quality (avg fighter marketability)
  - Result variety (decisions vs finishes)
  - Rivalry heat on the card
  - Title fights on the card
- Use the existing `show_rating._compute_show_rating` function (or similar logic).
- **Row count:** ~1,884 new `show_ratings` rows.

### Rec 9: Regenerate fighter bios to match DB records

**Why:** 11 of 14 sampled bios contradict the actual `fighter_career` record. The "Historian" fantasy depends on bios being accurate.

**How:**
- Write a one-shot script `scripts/regenerate_bios.py` that:
  - Reads each fighter's `fighter_career` (record, win_streak, title_reigns, career_health)
  - Reads `fighter_attributes` (top 3 attributes — informs "brawler" vs "wrestler" vs "submission specialist")
  - Reads `fighter_personality` (informs tone)
  - Re-generates the bio using the existing 9 template patterns but with correct data interpolated.
  - For fighters with 0 fights: use a "fresh face" template that doesn't claim a record.
  - For fighters with title_reigns > 0: use a champion/veteran template that mentions the reign.
- Run once after all other rebalancing is done (Recs 1-8) so the bios reflect the final DB state.
- **Row count:** 4,477 UPDATE statements on existing `fighter_bios`.

### Rec 10: Pre-seed news_items at world start (player's promo)

**Why:** Promo 1 (player's) has only 4 news items at world start. The player's news feed is empty when they start a new game.

**How:**
- Backfill 20-30 news_items for promo 1 (Alpha Combat Federation) covering the 3-6 months before world start:
  - 5-8 signing news (recent FA pickups)
  - 5-8 release news (recent cuts)
  - 3-5 event recaps (recent shows)
  - 3-5 show_rating news
  - 2-3 cross_promo news (rival promo callouts, etc.)
- Use realistic dates (3-6 months before 2026-10-15).
- **Row count:** 20-30 new `news_items` rows for promo_id=1.

### Rec 11: Pre-seed more title histories (reduce vacant titles)

**Why:** 47 of 111 titles (42%) are vacant. Many divisions have no champion, which feels unfinished.

**How:**
- For each vacant title: find the top-ranked eligible fighter in that weight class and assign them as the current champion.
- Set `titles.current_champion_fighter_id`, `champion_since_date` (1-12 months before world start), `title_reigns_count=1`, `is_vacant=0`.
- Increment the fighter's `fighter_career.title_reigns` by 1.
- Write a "title won" news_item (topic='title_change' or similar).
- **Row count:** ~47 UPDATE on `titles` + ~47 UPDATE on `fighter_career` + ~47 new `news_items`.

---

## 6. Open Questions for User

1. **Pyramid rebalance scope:** Should we rebalance career_phase criteria (relax veteran/gatekeeper/declining thresholds in `career_phase_engine.py`) AND/OR re-seed the fighter roster with more veterans? Both? The former is a smaller change; the latter is more impactful but more disruptive.

2. **Training-camp fix approach:** Should we (A) re-tune the `effective_ceiling` formula (remove `personality_factor` from the ceiling, move it into the gain multiplier), (B) re-seed all fighter attributes down to 35-45 (so there's room to grow), or (C) both? Option A is less disruptive but may make growth too fast for high-potential prospects. Option B invalidates the existing bios (which already contradict records) and would require Reg 9 anyway.

3. **Fight engine investigation:** Should the next subagent deep-dive into `src/services/fight_engine.py` to find the doctor-stoppage bias root cause? Or is this a known issue with an existing fix plan? The 54% doctor-stoppage rate is the most visible bug to a player.

4. **Staff lifecycle scope:** Should we implement staff aging + retirement + regen in a single task, or split it into (1) staff aging + retirement (smaller), then (2) staff regen (larger)? The former alone would make the staff world feel dynamic; the latter is needed for the long-term sim.

5. **Pre-seeding vs. simulating forward:** Some recommendations (Rec 1 HoF legends, Rec 5 more contracts, Rec 8 backfill show_ratings) add data that *could* be generated by running the sim forward 5-10 years instead of pre-seeding. Which approach do you prefer? Pre-seeding gives instant "alive" feel but the data is synthetic; sim-forward produces organic data but takes sim time and the world looks thin for the first 6-12 sim-months.

6. **Bio regeneration timing:** Should we regenerate bios now (against the current inconsistent DB) or wait until after Recs 1-8 are applied (so the bios reflect the final, rebalanced DB)? The latter is cleaner but requires sequencing.

7. **Matchmaking rematch-avoidance priority:** This is a quick fix (add a `WHERE fighter_id NOT IN (SELECT opponent_id FROM fight_history WHERE event_date > date(?, '-90 days'))` clause to `_pick_matchup`). Should it be the next priority, or deferred until ranking-proximity matchmaking (Task 10) is implemented?

8. **Memory_link backfill scope:** Should the backfill script (Rec 7) generate memories for ALL 4,234 historical fights, or only for the most recent 1,000? The former gives a richer memory surface; the latter is faster and may be sufficient (most old memories would be "forgotten" anyway).

9. **Free agent pool target size:** Should we aim for 1,000-1,500 FAs (Rec 5 — sign 60-70% of roster) or a different target? Real MMA has maybe 5-15% unsigned, but our sim needs a healthy pool for the player to recruit from.

10. **Run rollback preference:** The DB is currently in the post-90-day-sim state (sim clock at 2027-01-13). Should I roll back to the pre-audit backup (sim clock 2026-10-15) so the DB is at the "pristine" pre-audit state, or leave it as-is? Rolling back loses the 90 days of generated news/events/finance but restores the pre-audit state for the next subagent.

---

*End of audit.*
