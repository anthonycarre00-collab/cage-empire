# CAGE EMPIRE — Schema Drift Audit

> **Status:** Living document. Every schema change must update this
> file. The purpose is to prevent the 37 → 24 table drift that
> already happened twice from happening again.
> **Last revised:** 2026-07-21 — Task ID 2.

This document is a table-by-table comparison of:
- **Designed** — what the v1.6 spec (509-page chat transcript) calls
  for.
- **Built (v1.2.0)** — what exists in commit `986d438`.
- **Built (v1.2.1)** — what exists after Task ID 2 (this commit).
- **Status** — `OK` / `THIN` / `MISSING` / `WRONG` / `DROPPED`.

Legend:
- `OK` — designed and built to spec.
- `THIN` — designed and built, but with fewer columns than spec.
- `MISSING` — designed but not built at all.
- `WRONG` — built but shape does not match design.
- `DROPPED` — existed in an earlier draft and was removed without
  being recorded.

---

## A. Schema meta & versioning

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `schema_meta` | yes | no | yes | `DROPPED` → restored in v1.2.1 |
| `schema_migrations` | yes | no | yes | `DROPPED` → restored in v1.2.1 |

**Notes.** Both tables existed in earlier "reset bundle" drafts and
were dropped during the error → shrink cycle. Restored in Task ID 2
as cheap insurance against further silent drift.

---

## B. Simulation & geography

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `simulation_clock` | yes | yes | yes | `OK` |
| `nations` | yes (rich: language, combat_culture, market_maturity, travel_difficulty, regulatory_profile, talent_pool_strength, fan_style_preference) | yes (thin: name, language) | yes (thin) | `THIN` |
| `regions` | yes (rich: style_preferences, fan_preferences, market_growth) | yes (matches spec) | yes | `OK` |
| `weight_classes` | yes | yes | yes | `OK` |
| `cities` | yes (rich: population, affluence, combat_sports_interest, media_reach, local_bias, venue_capacity_bias) | yes (thin: name, population) | yes (thin) | `THIN` |
| `markets` | yes (rich: market_type, heat_level, fan_taste_profile, ticket_demand, local_star_bonus, touring_penalty) | yes (thin: market_type, heat_level) | yes (thin) | `THIN` |
| `venues` | yes (rich: capacity, prestige, cost, atmosphere, media_suitability, walkout_quality, lighting_quality) | yes (thin: name, capacity) | yes (thin) | `THIN` |

**Notes.** The geography layer is the right shape but missing the
rich attribute columns. Task ID 27 (Stage 5) will fold these in
when venues/markets become load-bearing for show rating and finance.

---

## C. Promotions, gyms, archetypes

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `promotions` | yes (rich: brand_tone, size_tier, starting_budget, current_cash, reputation, fan_trust, broadcast_tier, ownership_type, ai_aggression, ai_spending_style) | yes (thin: name, size_tier, current_cash, reputation, fan_trust) | yes (thin) + 1 extra row (Rival Fight League seeded) | `THIN` |
| `gyms` | yes (rich: reputation, membership_cost, facility_quality, medical_support, sparring_depth, development_focus, culture_tone, weight_cut_support, elite_camp_bonus) | yes (thin: name, location FKs only) | yes (thin) | `THIN` |
| `style_archetypes` | yes (name, description, attribute_bias) | yes (thin: missing attribute_bias) | yes (thin) | `THIN` |
| `personality_archetypes` | yes (name, description, trait_bias) | yes (thin: missing trait_bias) | yes (thin) | `THIN` |

**Notes.** Rival promotion seeded in v1.2.1 per the advisor AI's
recommendation. RFL is inert — no AI behaviour until Task ID 25.

---

## D. Fighters

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `fighters` | yes (rich: identity + injury_proneness, weight_cut_difficulty, consistency, clutch_factor, marketability, fan_friendliness, promo_boost, preferred_gameplans, bad_matchup_tags, is_active, is_retired, is_deceased) | yes (thin: identity + is_active only) | yes (thin) | `THIN` |
| `fighter_attributes` | yes (24 combat stats) | `WRONG` (only 4: punch_power, cardio, fight_iq, chin) | `WRONG` (4) | `WRONG` — critical |
| `fighter_personality` | yes (17 traits + morale + focus + fatigue_tolerance) | `WRONG` (only 3: aggression, composure, morale) | `WRONG` (3) | `WRONG` — critical |
| `fighter_career` | yes (rich: record_*, streaks, current_ranking, title_reigns, title_defenses, legacy_score, market_popularity_local/regional/global, contract_status, career_stage, injury_status, retirement_status, death_flag, peak_rating, career_health, hall_of_fame_flag, legacy_tier) | yes (thin: record_*, streaks, career_health) | yes (thin) | `THIN` |
| `fighter_history` | yes (separate from mutable career counters) | no | no | `MISSING` — added in Task ID 4 |

**Notes.** `fighter_attributes` and `fighter_personality` are the
most critical gap — the v1.6 spec calls for 24 combat stats and 17
personality traits, the v1.2.0 build only has 4 and 3. **Task ID 3
will extend these to spec** in the same commit that ships the real
fight resolver, because the resolver needs the full attribute set to
work properly.

---

## E. Staff & broadcast

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `staff` | yes (rich: name, age, nationality, role_type, specialty, skill_level, reputation, loyalty, salary, contract_start/end, fatigue, retirement_status, death_flag, promotion_id) | yes (thin: name, age, role_type, specialty, promotion_id) | yes (thin) | `THIN` |
| `broadcast_staff` | yes (rich: staff_id, on_air_role, mic_skill, analysis_skill, chemistry_rating, bias, credibility, knowledge_depth, commentary_style, catchphrase_level) | yes (thin: staff_id, on_air_role) | yes (thin) | `THIN` |

**Notes.** UI does not show staff at all yet, even though the table
is seeded. Task ID 6 will add a Staff tab as a side-effect of the
multi-promotion UI work.

---

## F. Contracts (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `contracts` | yes | no | no | `MISSING` — Task ID 9 |
| `fighter_contracts` | yes | no | no | `MISSING` — Task ID 9 |
| `staff_contracts` | yes | no | no | `MISSING` — Task ID 9 |
| `broadcast_contracts` | yes | no | no | `MISSING` — Task ID 9 |

**Notes.** Today fighters are tied to promotions only by a
`current_promotion_id` FK on the fighters table — no terms, no
expiry, no free agency. This is the single biggest career-system
gap.

---

## G. Events & fights

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `events` | yes (rich: + prestige, glamour_score) | yes (thin: missing prestige, glamour_score) | yes (thin) | `THIN` |
| `fights` | yes | yes | yes | `OK` |
| `fight_participants` | yes (rich: + official_result, score_total) | yes (thin: missing these) | yes (thin) | `THIN` |
| `event_cards` | yes (rich: + is_co_main, notes) | yes (thin: missing these) | yes (thin) | `THIN` |
| `fight_rounds` | yes (round_number, fighter_a/b_damage, control_time, knockdowns, takedowns, strikes_landed, momentum_state, round_winner_fighter_id) | no | no | `MISSING` — Task ID 3 or 4 |

**Notes.** `fight_rounds` is needed by the real fight resolver to
produce round-by-round output. Will likely be added in Task ID 3
or 4 alongside the resolver work.

---

## H. Career & medical

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `injuries` | yes (fighter_id, event_id, injury_type, severity, body_area, start_date, projected_return_date, actual_return_date, long_term_damage, career_risk) | no | no | `MISSING` — Task ID 15 |
| `training_camps` | yes (fighter_id, gym_id, event_id, dates, camp_focus, camp_morale, camp_fatigue, camp_injury_risk, camp_weight_cut_pressure, camp_result_summary) | no | no | `MISSING` — Task ID 16 |

---

## I. Scouting & analysis (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `scouting_reports` | yes | no | no | `MISSING` — Task ID 18 |
| `betting_odds` | yes | no | no | `MISSING` — Task ID 24 |
| `matchup_analysis` | yes | no | no | `MISSING` — Task ID 24 |

---

## J. News & commentary

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `news_sources` | yes (rich: credibility, sensationalism, bias, regional_reach, reliability, frequency) | yes (matches spec) | yes | `OK` |
| `news_items` | yes (rich: + region_id) | yes (thin: missing region_id) | yes (thin) | `THIN` |
| `commentary_segments` | yes | yes | yes | `OK` |
| `pundit_segments` | yes | no | no | `MISSING` — Task ID 24 |

---

## K. Rankings & titles (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `rankings` | yes | no | no | `MISSING` — Task ID 10 |
| `titles` | yes | no | no | `MISSING` — Task ID 11 |

---

## L. Social & rivalries (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `social_posts` | yes | no | no | `MISSING` — Task ID 21 |
| `social_accounts` | yes | no | no | `MISSING` — Task ID 21 |
| `rivalries` | yes | no | no | `MISSING` — Task ID 22 |

---

## M. Regen & name pools (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `name_first_male` | yes | no | no | `MISSING` — Task ID 14 |
| `name_first_female` | yes | no | no | `MISSING` — Task ID 14 |
| `name_last` | yes | no | no | `MISSING` — Task ID 14 |
| `nickname_pool` | yes | no | no | `MISSING` — Task ID 14 |
| `region_pool` | yes | no | no | `MISSING` — Task ID 14 |
| `regen_templates` | yes | no | no | `MISSING` — Task ID 14 |
| `fighter_lineage` | yes | no | no | `MISSING` — Task ID 14 |
| `fighter_generation_history` | yes | no | no | `MISSING` — Task ID 14 |
| `used_names` | yes | no | no | `MISSING` — Task ID 14 |
| `fighter_memory_links` | yes | no | no | `MISSING` — Task ID 14 |

---

## N. Voice & templates (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `voice_descriptors` | yes | no | no | `MISSING` — Task ID 19 |
| `commentary_templates` | yes | no | no | `MISSING` — Task ID 23 |
| `news_templates` | yes | no | no | `MISSING` — Task ID 23 |
| `bio_templates` | yes | no | no | `MISSING` — Task ID 19 |

---

## O. Legacy & history (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `fighter_history` | yes (separate from mutable career counters — advisor's point #3) | no | no | `MISSING` — Task ID 4 |
| `staff_history` | yes | no | no | `MISSING` |
| `company_history` | yes | no | no | `MISSING` |
| `hall_of_fame` | yes | no | no | `MISSING` |
| `legacy_records` | yes | no | no | `MISSING` |

---

## P. Portraits & art (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `portrait_assets` | yes | no | no | `MISSING` — Task ID 29 |
| `portrait_templates` | yes | no | no | `MISSING` — Task ID 29 |

---

## Q. Finances (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `finances` | yes (per-event P&L, weekly burn rate, forecast) | no (only `promotions.current_cash` column) | no | `MISSING` — Task ID 20 |

---

## R. Modding (entire group MISSING)

| Table | Designed | Built v1.2.0 | Built v1.2.1 | Status |
|---|---|---|---|---|
| `mod_metadata` | yes | no | no | `MISSING` — Task ID 29 |

---

## Summary counts

| Category | Designed | Built v1.2.0 | Built v1.2.1 | Gap |
|---|---|---|---|---|
| Schema meta | 2 | 0 | 2 | 0 |
| Geography | 7 | 7 (thin) | 7 (thin) | 0 tables, ~20 columns thin |
| Promotions/gyms/archetypes | 4 | 4 (thin) | 4 (thin) | 0 tables, ~15 columns thin |
| Fighters | 5 | 4 (`fighter_history` missing, `attributes`/`personality` wrong) | 4 | 1 table + 20 attribute columns + 14 personality columns |
| Staff & broadcast | 2 | 2 (thin) | 2 (thin) | 0 tables, ~15 columns thin |
| Contracts | 4 | 0 | 0 | 4 tables |
| Events & fights | 5 | 4 (`fight_rounds` missing) | 4 | 1 table |
| Career & medical | 2 | 0 | 0 | 2 tables |
| Scouting & analysis | 3 | 0 | 0 | 3 tables |
| News & commentary | 4 | 3 (`pundit_segments` missing) | 3 | 1 table |
| Rankings & titles | 2 | 0 | 0 | 2 tables |
| Social & rivalries | 3 | 0 | 0 | 3 tables |
| Regen & name pools | 10 | 0 | 0 | 10 tables |
| Voice & templates | 4 | 0 | 0 | 4 tables |
| Legacy & history | 5 | 0 | 0 | 5 tables |
| Portraits & art | 2 | 0 | 0 | 2 tables |
| Finances | 1 | 0 | 0 | 1 table |
| Modding | 1 | 0 | 0 | 1 table |
| **TOTAL TABLES** | **~60** | **24** | **26** | **~34 tables** |
| **TOTAL THIN COLUMNS** | — | — | — | **~70 columns** |

**Headline numbers.**
- Designed: ~60 tables (the "83+" figure in the advisor's analysis
  counts every FK and lookup table separately; the logical table
  count is ~60).
- Built v1.2.0: 24 tables.
- Built v1.2.1: 26 tables (restored `schema_meta` + `schema_migrations`).
- Gap: ~34 tables and ~70 thin columns.

This audit is the source of truth for what work remains. Every
schema-change task must update this file in the same commit.
