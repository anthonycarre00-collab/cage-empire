# CAGE EMPIRE — 1-Year Simulation Analysis

**Date:** 2026-08-15
**Sim period:** 2026-07-20 → 2027-07-20 (365 ticks)
**DB state:** Pre-reseed world DB (4,450 fighters, schema v3.36.0)
**Verdict:** The world is alive. Most systems work well. A few issues need attention.

---

## 1. Population — GOOD

The world breathes. Fighters retire and are replaced by regenerated prospects.

| Metric | Start | End | Change |
|---|---|---|---|
| Total fighters | 4,450 | 4,515 | +65 |
| Active | 4,450 | 4,453 | +3 (net) |
| Retired | 0 | 62 | +62 |
| Regen lineage | 0 | 62 | +62 |
| Free agents | 4,138 | 4,061 | -77 (signed by promos) |

62 fighters retired over the year (~5/month), each replaced by a regen prospect. The free agent pool shrank slightly as rival AI signed fighters. This is healthy churn.

## 2. Top Fighters — CONCERNING

The ELO rankings after 1 year show some problems:

| Fighter | ELO | Record | Potential | Reigns |
|---|---|---|---|---|
| Steven Chavez | 1199 | 29-11 | 89 | 0 |
| Tulio Gonçalves | 1162 | 12-15 | 78 | 1 |
| Ryan Kim | 1147 | 6-8 | 50 | 0 |
| Paul Lee | 1136 | 11-13 | 57 | 0 |

**Issues:**
- Ryan Kim is #3 with a **losing record (6-8)** and **below-average potential (50)**. This makes no sense — a 6-8 fighter shouldn't be top 3.
- Paul Lee is #4 with an 11-13 record and potential 57. Also a losing record in the top 5.
- Tulio Gonçalves is #2 at 12-15 — another losing record.

**Root cause:** The ELO system awards +32 per win and -32 per loss, but the starting ELO is 1000 for everyone. A fighter who beats high-rated opponents gains more than they should. The issue is that the INITIAL ELO was seeded at 1000 flat for all 4000 fighters — it should have been seeded based on their record/tier (Elite starts at 1150, Fringe at 850, etc.).

**Fix needed:** Reseed ELO based on career tier + win rate, not flat 1000. This is part of the reseed plan (Step 5: regenerate rankings).

## 3. Retirees + Regen — GOOD

62 fighters retired, each replaced by a new prospect. Examples:
- Kyle Gonzalez → Joseph Moraes
- Joon-woo Park → Kyle Ortega
- Sara Long → Louis Prieto

The regen system works correctly — retired fighters get `is_retired=1`, replacement fighters get new IDs, and `regen_lineage` tracks the connection.

## 4. Champions + Title Changes — GOOD

| Metric | Start | End |
|---|---|---|
| Champions | 48 | 69 |
| Vacant titles | 63 | 42 |
| Title changes | — | +54 |

54 title changes in 1 year is realistic (~4.5/month). More champions were crowned than vacated, which makes sense — many titles started vacant and got filled. Champions have varying reign lengths — some since 2024 (long-reigning), many since 2027 (new champions).

## 5. News Feed — GOOD BUT NEEDS TUNING

1,691 news items generated over the year (~4.6/day). Distribution:

| Importance | Count | % |
|---|---|---|
| ROUTINE | 1,429 | 84.4% |
| MAJOR | 120 | 7.1% |
| SIGNIFICANT | 106 | 6.3% |
| BACKGROUND | 19 | 1.1% |
| LEGENDARY | 17 | 1.0% |

**Issues:**
- ROUTINE dominates at 84.4% — the daily cap of 5 ROUTINE items is working, but training news (338 items) and small_reward news (218 items) are too frequent. These are low-value items that clutter the feed.
- Only 7 memory_resurfacing news items fired — the fight-preview memory system works but fires rarely (only when booked fighters have history).
- Headlines read well: "SHOCK: Gonzalez hangs them up", "New prospect Joseph Moraes emerges", "Pedro Alvarez cleared to return from broken hand"

## 6. Memory Resurfacing — WORKING

| Metric | Start | End |
|---|---|---|
| Memory links | 0 | 1,754 |
| Memory resurfacing news | 0 | 7 |

13 different memory link types were created during the sim. The top types:
- controversial_losses (420) — from split decisions
- previous_fights (310) — from repeat matchups
- regional_rival (304) — from same-region pairings
- promotions (248) — from signings

The 7 memory_resurfacing news items are low because they only fire when a fight is BOOKED between fighters with history. With the reseeded fight_history (79K rows), this should fire much more frequently.

## 7. Rivalries — EXCELLENT

| Metric | Start | End |
|---|---|---|
| Rivalries | 93 | 254 (+161) |
| Active | — | 138 |

4 rivalry types developed naturally:
- bad_blood (126) — from split decisions, DQs, weight cut misses
- title_rivalry (76) — from title fight matchups
- rematch_hungry (39) — from 1-1 records
- callout (13) — from social media callouts

Top rivalries have high heat (93-97) with 2-10 fights between the pair. The decay system works — 116 rivalries went dormant (is_active=0) as heat dropped below 20.

## 8. Promotions + Finances — MIXED

**The good:** Promotions differentiate. Cash ranges from $-400K (Mexican Boxing & Brawl, REBUILDING) to $50M (Alpha Combat, HEALTHY). 8 of 10 promotions entered REBUILDING state — they ran events that lost money.

**The concerning:**
- Alpha Combat (P1, the player's promo) still has $50M cash and only 1 finance transaction — it didn't run any events! The player didn't play. This is expected (no player input during the sim).
- Rival Fight League dropped from mid to small size_tier — promotions can demote.
- Pacific Rim Championship went from mid to small — same.
- Most promotions are in REBUILDING — this may be too aggressive. The financial state machine may be too quick to declare REBUILDING.

**Fix needed:** The financial state machine thresholds may need tuning — promotions shouldn't all end up in REBUILDING after 1 year of normal operations.

## 9. Fight Results — PROBLEMATIC

672 fights resolved this year. Result distribution:

| Result | Count | % | Target |
|---|---|---|---|
| unanimous_decision | 332 | 49.4% | ~35% |
| split_decision | 257 | 38.2% | ~10% |
| submission | 8 | 1.2% | ~20% |
| no_contest | 29 | 4.3% | ~0.5% |
| unknown | 46 | 6.8% | 0% |

**Major problems:**
1. **Split decisions are 38%** (target 10%) — way too many. The fight engine's scoring is too close too often.
2. **Submissions are 1.2%** (target 20%) — almost none. The submission finish threshold is too high.
3. **KO/TKO is 0%** — not a single KO! This is a critical bug. The KO finish threshold is not being triggered.
4. **46 "unknown" results** — fights with NULL result_type. These are bugs (fights that resolved but didn't record a result).
5. **Doctor stoppage is 0%** — the improved AI simplified resolution doesn't produce doctor stoppages (expected), but even the full engine isn't producing them.

**Root cause:** This is the pre-reseed DB with the old (bad) attribute data. The reseeded data (Claude's pyramid distribution) should produce more mismatches → more finishes. But the fight engine thresholds also need investigation — 0 KOs is unacceptable.

## 10. Show Ratings — GOOD

Show ratings range from 45-72 across promotions, with the bigger promos (RFL, EFN, PRC) averaging 63-67 and smaller promos averaging 55-59. This differentiation is realistic — bigger promos put on better shows.

## 11. Tick Health — EXCELLENT

365 ticks, ALL HEALTHY. Average tick duration 152ms, max 978ms. Zero errors. The EventBus is firing cleanly, all subscribers succeed.

## 12. Rival AI — WORKING WELL

701 rival AI memories written across 6 types:
- signing_won (201) — AI signed fighters
- fighter_released (160) — AI cut fighters
- event_result (108) — AI ran events
- rivalry_fuelled (88) — AI developed rivalries
- title_win (72) / title_loss (72) — AI champions won/lost

The rival AI is actively managing its promotions — signing, cutting, scheduling, and reacting to results.

## 13. Gym Movements — NOT WORKING

0 gym change memory links. Fighters do not change gyms during the sim. The `former_teammates` and `old_gyms` memory writers exist but are never called because there's no gym-transfer flow in the simulation.

**Fix needed:** Add a gym-change mechanic — fighters should occasionally switch gyms (especially after losses, or when seeking better training). This is a feature gap, not a bug.

## 14. Injuries — LIGHT

Only 38 injuries (8 active) over 672 fights = 5.6% injury rate. This is low but plausible — most injuries come from KO/TKO damage, and with 0 KOs, fewer injuries is expected.

## 15. Staff — LOST THE NEW STAFF

Staff count went from 375 to 381 (only +6, expected +30 from the reseed). The matchmaker role (10 added in reseed) is missing — this is because the pre-reseed DB was used for this sim, not the reseeded DB.

---

## Summary: What Works + What Doesn't

### Working well ✅
- Retirement + regen lifecycle (62 retired, 62 replaced)
- Title changes (54 in 1 year, realistic)
- Rivalries forming + decaying (161 new, 138 active, 116 dormant)
- News feed quality (1,691 items, good headline variety)
- Memory link creation (1,754 links across 13 types)
- Rival AI behavior (701 memories, active signing/cutting/scheduling)
- Tick health (365/365 HEALTHY, 0 errors, 152ms avg)
- Show ratings (differentiated by promotion tier)
- Promotion financial differentiation (cash range $-400K to $50M)

### Needs attention ⚠️
- **0 KOs in 672 fights** — critical fight engine issue
- **38% split decisions** (target 10%) — scoring too close
- **1.2% submissions** (target 20%) — finish threshold too high
- **46 fights with NULL result** — bug in fight resolution
- **ELO rankings don't match skill** — losing records in top 5 (flat 1000 start)
- **ROUTINE news 84%** — training + small_reward too frequent
- **Most promotions in REBUILDING** — financial state machine too aggressive
- **No gym changes** — fighters never switch gyms

### Expected to improve with reseed ✅
- ELO rankings (reseed computes from fight_history, tier-weighted)
- Fight results (Claude's pyramid attributes → more mismatches → more finishes)
- Memory resurfacing (79K fight_history rows → more history to surface)
- News quality (more meaningful events → better stories)
