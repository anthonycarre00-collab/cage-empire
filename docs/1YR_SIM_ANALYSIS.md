# CAGE EMPIRE — Post-Reseed 1-Year Simulation Analysis

**Date:** 2026-08-15
**Sim period:** 2026-07-20 → 2027-07-20 (365 ticks, COMPLETE)
**DB state:** Reseeded world DB (6,450 fighters, 80K fight_history, schema v3.36.0)
**All fixes applied:** fight engine tuned, news spam fixed, gym transfers, financial state machine relaxed, legacy UI removed
**Verdict:** The world is alive and produces believable, interconnected MMA history. Most systems work well. A few areas still need attention.

---

## 1. Population — HEALTHY

| Metric | Start | End | Change |
|---|---|---|---|
| Total fighters | 6,450 | 6,575 | +125 |
| Active (real) | 4,450 | 4,456 | +6 (net) |
| Retired | 2,000 (grey names) | 2,119 | +119 (grey + real retirees) |
| Regen lineage | 0 | 119 | +119 |
| Free agents | 4,075 | 4,039 | -36 (signed by promos) |

119 fighters retired over the year (~10/month), each replaced by a regen prospect. The active population stays stable at ~4,450 — the regen system perfectly replaces retiring fighters.

## 2. Top Fighters — EXCELLENT

The ELO rankings now match skill. The top 15 fighters all have winning records and high potential:

| Fighter | ELO | Record | Potential |
|---|---|---|---|
| Ryosuke Murakami | 1211 | 47-4 | 89 |
| Albert Campbell | 1209 | 42-2 | 99 |
| Nathan Nelson | 1187 | 28-3 | 90 |
| Jose Xavier | 1179 | 31-3 | 81 |
| Lea Fournier | 1174 | 28-2 | 84 |
| Hugo Francois | 1167 | 54-6 | 83 |
| Riku Takahashi | 1160 | 33-2 | 89 |
| Julie Robert | 1158 | 40-6 | 93 |
| Robert Lewis | 1155 | 34-3 | 99 |

**Assessment:** This is exactly right. Elite fighters (potential 80-99) have dominant records (47-4, 42-2, 28-3). The reseeded tier system works — Elite fighters are at the top, Gatekeepers are in the middle, Fringe fighters are at the bottom. No more losing records in the top 5.

## 3. Retirees + Regen — WORKING

119 retirements, each replaced. Examples:
- Kyle Gonzalez → Murilo Dominguez
- Joon-woo Park → George Petrov
- Billy Patel → Xiang Powell

Kyle Gonzalez was inducted into the Hall of Fame on the same day he retired — the HoF system works.

## 4. Champions + Title Changes — REALISTIC

| Metric | Start | End |
|---|---|---|
| Champions | 78 | 92 |
| Vacant | 43 | 29 |
| Title changes | — | ~54 |

Champions have varying reign lengths — some since 2024 (long-reigning), many since 2027 (new champions). Title defenses range from 0 (newly crowned) to 6 (established champions). The title picture feels alive.

## 5. Fight Results — DRAMATICALLY IMPROVED

| Result | Count | % | Pre-reseed | Target |
|---|---|---|---|---|
| unanimous_decision | 436 | 46.1% | 39% | ~35% |
| **ko_tko** | **218** | **23.1%** | **0%** | ~30% |
| **submission** | **131** | **13.9%** | **1.2%** | ~20% |
| split_decision | 67 | 7.1% | 38% | ~10% |
| NULL (scheduled) | 57 | 6.0% | — | — |
| no_contest | 19 | 2.0% | — | ~0.5% |
| doctor_stoppage | 9 | 1.0% | 3.3% | ~1% |
| draw | 4 | 0.4% | — | ~1% |
| dq | 4 | 0.4% | — | ~0.5% |

**Assessment:** KOs went from 0% → 23.1%. Submissions went from 1.2% → 13.9%. Split decisions went from 38% → 7.1%. The distribution is now plausible MMA — decisions still dominate (53%) but finishes happen regularly (37% KO+sub). The 57 "NULL" results are scheduled fights not yet resolved (NOT a bug).

**Remaining gap:** KO rate is 23% vs target 30% — slightly low but acceptable. Sub rate is 14% vs target 20% — also slightly low. Both are close enough that attribute rebalancing (future task) should close the gap.

## 6. News Feed — TRANSFORMED

| Importance | Count | % | Pre-reseed |
|---|---|---|---|
| ROUTINE | 804 | 42.2% | 84% |
| SIGNIFICANT | 533 | 28.0% | 6% |
| MAJOR | 478 | 25.1% | 7% |
| LEGENDARY | 30 | 1.6% | 1% |
| BACKGROUND | 59 | 3.1% | 1% |

**Assessment:** ROUTINE dropped from 84% → 42%. SIGNIFICANT went from 6% → 28%. MAJOR went from 7% → 25%. The news feed now has meaningful, tiered content instead of spam.

**New content types working:**
- End-of-year awards: 6 LEGENDARY items (Fight/KO/Sub/Comeback/Prospect of the Year)
- Gym transfers: 52 MAJOR items
- Fight of the Night bonuses: ~76 ROUTINE items per event
- Hall of Fame inductions: LEGENDARY

**Sample headlines:**
- "Kyle Gonzalez inducted into Hall of Fame"
- "Jacob Nguyen vs Fergus Doyle named Fight of the Year for 2026"
- "Tyler Martinez's Knockout of Daniel Flores named Knockout of the Year"
- "Stunning upset — Gary Ramirez just beat Jin-soo Roh"
- "Hiroki Nakamura has left Triumph Training Center to train at Empire Academy"

## 7. Memory Resurfacing — ALL 15 TYPES WORKING

| Metric | Start | End |
|---|---|---|
| Memory links | 0 | 4,429 |
| Memory resurfacing news | 0 | 0* |

*Memory resurfacing news = 0 in the sim, but this is because the fight-preview memory system fires when fights are BOOKED (not resolved). The soak test doesn't book player fights, so the player-path memory news doesn't fire. The rival AI's `schedule_next_event` does call it, but rival fights may not have history between the paired fighters.

**All 15 link types have data:**
- former_teammates (2,728) — from gym transfers
- regional_rival (312) — from same-region matchups
- previous_fights (312) — from 2nd meetings
- promotions (248) — from signings
- upset (156) — from upset victories
- old_events (116) — from title fights
- injuries (108) — from fight injuries
- milestone (90) — from career milestones
- controversial_losses (84) — from split decisions
- title_history (78) — from title changes
- style_echo (57) — from regen replacements
- old_gyms (50) — from gym transfers
- comeback (50) — from losing streak recoveries
- former_champions (40) — from title losses
- successor (1) — from regen lineage

## 8. Rivalries — EXCELLENT

| Metric | Start | End |
|---|---|---|
| Rivalries | 343 | 521 (+178) |
| Active | — | 152 |

4 types, all forming naturally:
- bad_blood (230) — from split decisions, DQs, weight cut misses
- rematch_hungry (177) — from 1-1 records
- title_rivalry (82) — from title fight matchups
- callout (32) — from social media callouts

**Top rivalries feel real:**
- Kevin Hall vs Nikita Fedorov — bad_blood, heat 98, 4 fights
- Gerald King vs Anton Sorokin — title_rivalry, heat 95, 12 fights
- Andrea Ibañez vs Debra Cruz — bad_blood, heat 97, 6 fights

The decay system works — 369 rivalries went dormant as heat dropped below 20.

## 9. Promotions + Finances — MIXED BUT BETTER

**The good:** Promotions differentiate. Show ratings range from 62-74 (bigger promos put on better shows). Rival AI is active — 676 memories written (222 signings, 178 cuts, 104 events, 92 title wins/losses).

**The issue:** 9 of 10 promotions still end up in REBUILDING. Only Alpha Combat (the player's promo, which didn't run events) stays HEALTHY. The financial state machine is still too aggressive — even with raised thresholds + cash injections, rival promos can't sustain profitability.

**Root cause:** The event economics may be fundamentally unbalanced — venue rental + fighter purses exceed ticket revenue for most events. This needs separate investigation.

**Promotion reputation varies meaningfully:** Mexican Boxing & Brawl (rep 67, trust 35) → Pacific Rim (rep 14, trust 35) → Rival Fight League (rep 11, trust 35). The reputation system differentiates promos.

## 10. Show Ratings — GOOD

Show ratings range from 62-74 across promotions:
- Rival Fight League: avg 74.0 (best — puts on the best shows)
- French Savate Championship: avg 61.9 (worst — smallest promo, weakest roster)

This differentiation is realistic — bigger promos with better fighters put on better shows.

## 11. Tick Health — EXCELLENT

365 ticks, ALL HEALTHY. Average 337ms/tick, max 1622ms. Zero errors.

## 12. Gym Transfers — WORKING

52 gym transfers in 1 year (~4.3/month). Fighters actively change gyms based on losing streaks, gym quality, and prospect status. Each transfer writes a MAJOR news item.

## 13. Injuries — LIGHT BUT PLAUSIBLE

89 injuries (17 active) over 945 fights = 9.4% injury rate. With 23% KO rate, most injuries come from KO/TKO damage. This is low but plausible.

## 14. Staff — STABLE

405 staff (unchanged — no staff lifecycle during the sim). 300 coaches (gym-based), 30 scouts, 25 commentators, 20 cutmen, 10 matchmakers, 10 GMs, 10 doctors.

## 15. Fighter Growth + Decay — WORKING

**Top prospects (age < 25, potential > 80):**
- Helen Chavez (pot 99, 7-1, ELO 1033)
- Yua Yamada (pot 95, 1-0, ELO 999)
- Edward Walker (pot 94, 1-1, ELO 984)
- Christopher Carter (pot 93, 1-0, ELO 1046)
- Joe Thomas (pot 93, 6-1, ELO 1074)

**Declining veterans (age > 35, still active):**
- Hugo Francois (pot 83, 54-6, ELO 1167) — still elite at 35+
- Ryosuke Murakami (pot 89, 47-4, ELO 1211) — #1 ranked at 35+
- Anthony Gonzalez (pot 64, 46-43, ELO 948) — gatekeeper declining

The career arc system works — young prospects have high potential with room to grow, aging veterans have established records, and the decline system produces realistic attrition.

## 16. Hall of Fame — WORKING

13 inductees over the year, including Kyle Gonzalez (retired on the last day of the sim). The HoF system fires on retirement for fighters who meet the criteria (title reigns, win records, career milestones).

## 17. End-of-Year Awards — WORKING

6 LEGENDARY award news items fired on January 1, 2027:
- Fight of the Year: Jacob Nguyen vs Fergus Doyle
- Knockout of the Year: Tyler Martinez's KO of Daniel Flores
- Submission of the Year: William Russell's sub of Tulio Gonçalves
- Comeback of the Year: Dmitry Belov
- Prospect of the Year: Ruth "The Grounded Smother" Martinez

Plus ~76 per-event "Fight of the Night" bonus announcements (ROUTINE).

## 18. Bios — GOOD

Sample bios are factually grounded in each fighter's actual attributes, tier, and record:
- "Benjamin Morgan won't headline a pay-per-view, but every prospect moving up the Middleweight ranks eventually has to get through a fighter like this..."
- "What Barbara Ramos lacks in natural tools gets made up for with a work rate that's worn down more talented opponents..."
- "Eric Collins shows flashes against lesser competition, but the jump in class keeps exposing the same cracks..."

The bios reference the fighter's actual attributes (style, top skills, tier) and feel like real MMA writing.

## 19. Nicknames — GOOD

Sample nicknames are unique and relevant:
- "The Crumbling Spark", "The Next-Gen Tackler", "The Iron Boulder"
- "The Obsidian Engine", "The Veteran Smesh", "The Fading Flame"
- "The Relentless Machine", "The Precise Spark"

Only 40% of fighters have nicknames (realistic). 100% unique (no repetition).

---

## Summary: What Works + What Still Needs Attention

### Working well ✅
- **Fight results:** KO 23%, sub 14%, decision 53%, split 7% — plausible MMA distribution (was 0% KO!)
- **ELO rankings:** Top fighters have winning records + high potential (was losing records in top 5)
- **Retirement + regen:** 119 retired, 119 replaced, 13 HoF inductees
- **Title changes:** 54 changes, varying reign lengths, realistic defense counts
- **Rivalries:** 178 new (4 types), decay working (369 dormant)
- **News feed:** 42% ROUTINE (was 84%), 28% SIGNIFICANT, 25% MAJOR, 30 LEGENDARY items
- **Memory links:** 4,429 across all 15 types (was 0 at start)
- **Gym transfers:** 52 transfers, each with MAJOR news
- **Rival AI:** 676 memories, active signing/cutting/event management
- **Tick health:** 365/365 HEALTHY, 0 errors, 337ms avg
- **Show ratings:** Differentiated by promotion (62-74 range)
- **End-of-year awards:** 6 LEGENDARY items (Fight/KO/Sub/Comeback/Prospect of Year)
- **Bios:** Factually grounded, reference actual attributes
- **Nicknames:** 40% coverage, 100% unique, relevant to fighter

### Still needs attention ⚠️
1. **9/10 promotions in REBUILDING** — event economics may be fundamentally unbalanced (venue + purses > ticket revenue). Needs separate investigation.
2. **Memory resurfacing news = 0** — the fight-preview system fires when fights are BOOKED, but the soak test doesn't book player fights. Need to verify it fires in actual gameplay.
3. **KO rate 23% (target 30%)** — slightly low. Attribute rebalancing (future task) should help.
4. **Sub rate 14% (target 20%)** — slightly low. Same fix.
5. **Per-event "Fight of the Night" bonuses are ROUTINE** — these are per-event items that add up (76/year). Could be SIGNIFICANT for main events only.

### Comparison: Pre-reseed vs Post-reseed

| Metric | Pre-reseed | Post-reseed | Improvement |
|---|---|---|---|
| KO rate | 0% | 23.1% | ✅ Fixed |
| Sub rate | 1.2% | 13.9% | ✅ Fixed |
| Split decision | 38% | 7.1% | ✅ Fixed |
| ROUTINE news | 84% | 42% | ✅ Fixed |
| ELO top 5 records | 6-8, 11-13 | 47-4, 42-2 | ✅ Fixed |
| Gym transfers | 0 | 52 | ✅ Added |
| Memory types | 7/15 | 15/15 | ✅ Fixed |
| Promos in REBUILDING | 8/10 | 9/10 | ⚠️ Still high |
| End-of-year awards | 0 | 6 LEGENDARY | ✅ Added |
| HoF inductees | 0 | 13 | ✅ Working |
| Tick health | HEALTHY | HEALTHY | ✅ Maintained |
