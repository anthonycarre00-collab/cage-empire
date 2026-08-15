> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Schema Drift Audit

> **Status:** Living document. Every schema change must update this
> file. The purpose is to prevent the 37 → 24 table drift that
> already happened twice from happening again.
> **Last revised:** 2026-07-26 — Task 26 (show rating engine).
> **Current schema version:** 3.6.0 (52 tables, +1 new table this task).

This document is a table-by-table comparison of:
- **Designed** — what the v1.6 spec (509-page chat transcript) calls
  for.
- **Built (v1.2.0)** — what existed in the initial commit `986d438`.
- **Built (v1.9.0)** — what exists now, after Tasks 2-14.
- **Status** — `OK` / `THIN` / `MISSING` / `WRONG` / `DROPPED`.

Legend:
- `OK` — designed and built to spec.
- `THIN` — designed and built, but with fewer columns than spec.
- `MISSING` — designed but not built at all.
- `WRONG` — built but shape does not match design.
- `DROPPED` — existed in an earlier draft and was removed without
  being recorded.
- `CONSOLIDATED` — designed as multiple tables, built as fewer tables
  by design decision (documented in notes).

---

## A. Schema meta & versioning

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `schema_meta` | yes | no | yes | `OK` (restored Task 2, enforced Task 5) |
| `schema_migrations` | yes | no | yes | `OK` (restored Task 2) |

**Notes.** Both tables existed in earlier "reset bundle" drafts and
were dropped during the error → shrink cycle. Restored in Task ID 2.
Task ID 5 added the version-check gate: `build_db.py` refuses to run
if the on-disk schema is newer than the code's known version.

---

## B. Simulation & geography

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `simulation_clock` | yes | yes | yes | `OK` (but has pre-existing `current_date` quirk — see §Z) |
| `nations` | yes (rich: language, combat_culture, market_maturity, travel_difficulty, regulatory_profile, talent_pool_strength, fan_style_preference) | yes (thin: name, language) | yes (thin) | `THIN` — missing ~6 columns |
| `regions` | yes (rich: style_preferences, fan_preferences, market_growth) | yes (matches spec) | yes | `OK` |
| `weight_classes` | yes | yes | yes | `OK` |
| `cities` | yes (rich: population, affluence, combat_sports_interest, media_reach, local_bias, venue_capacity_bias) | yes (thin: name, population) | yes (thin) | `THIN` — missing ~5 columns |
| `markets` | yes (rich: market_type, heat_level, fan_taste_profile, ticket_demand, local_star_bonus, touring_penalty) | yes (thin: market_type, heat_level) | yes (thin) | `THIN` — missing ~4 columns |
| `venues` | yes (rich: capacity, prestige, cost, atmosphere, media_suitability, walkout_quality, lighting_quality) | yes (thin: name, capacity) | yes (thin) | `THIN` — missing ~5 columns |

**Notes.** The geography layer is the right shape but missing the
rich attribute columns. Task ID 27 (Stage 5) will fold these in
when venues/markets become load-bearing for show rating and finance.

---

## C. Promotions, gyms, archetypes

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `promotions` | yes (rich: brand_tone, size_tier, starting_budget, current_cash, reputation, fan_trust, broadcast_tier, ownership_type, ai_aggression, ai_spending_style) | yes (thin: name, size_tier, current_cash, reputation, fan_trust) | yes (all spec columns added in Task 14.6) + 2 rows (AC + RFL) | `OK` — all 6 missing columns added (brand_tone, starting_budget, broadcast_tier, ownership_type, ai_aggression, ai_spending_style). AC seeded with broadcast_tier='regional_tv', ai_aggression=30. RFL with 'local_stream', ai_aggression=60. |
| `gyms` | yes (rich: reputation, membership_cost, facility_quality, medical_support, sparring_depth, development_focus, culture_tone, weight_cut_support, elite_camp_bonus) | yes (thin: name, location FKs only) | yes (all spec columns added in Task 14.6) | `OK` — all 8 missing columns added (reputation, membership_cost, facility_quality, medical_support, sparring_depth, development_focus, culture_tone, weight_cut_support). |
| `style_archetypes` | yes (name, description, attribute_bias) | yes (thin: missing attribute_bias) | yes (attribute_bias added, Task 14.5) + 7 archetypes seeded | `OK` — attribute_bias TEXT (JSON) column added. 7 archetypes seeded with bias JSON (Balanced, Striker, Grappler, Wrestler, Brawler, Counter-Striker, Submission Specialist). |
| `personality_archetypes` | yes (name, description, trait_bias) | yes (thin: missing trait_bias) | yes (trait_bias added, Task 14.5) + 5 archetypes seeded | `OK` — trait_bias TEXT (JSON) column added. 5 archetypes seeded with bias JSON (Calm, Aggressive, Methodical, Showman, Quiet Professional). |

**Notes.** Rival promotion seeded in v1.2.1 (Task 2). RFL is inert —
no AI behaviour until Task ID 25. The `promotions` table is missing
`ai_aggression` and `ai_spending_style` columns that Task 25 needs —
these must be added as a migration before or during Task 25.

---

## D. Fighters

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `fighters` | yes (rich: identity + height_cm, reach_cm, stance, handedness, injury_proneness, weight_cut_difficulty, consistency, clutch_factor, marketability, fan_friendliness, promo_boost, preferred_gameplans, bad_matchup_tags, is_active, is_retired, is_deceased) | yes (thin: identity + is_active only) | yes (all spec columns added in Task 14.5+14.6) | `OK` — all 14 missing columns added (height_cm, reach_cm, stance, handedness, injury_proneness, weight_cut_difficulty, consistency, clutch_factor, marketability, fan_friendliness, promo_boost, preferred_gameplans, bad_matchup_tags, is_deceased) |
| `fighter_attributes` | yes (25 combat stats) | `WRONG` (only 4: punch_power, cardio, fight_iq, chin) | `OK` (25 columns, Task 14.5) | `OK` — expanded from 4 to 25 columns in Task 14.5+14.6+14.7. Existing 4 values preserved. 21 new columns added with CHECK (0-100). |
| `fighter_personality` | yes (20 fields: 17 static + 3 dynamic) | `WRONG` (only 3: aggression, composure, morale) | `OK` (20 fields, Task 14.5) | `OK` — expanded from 3 to 20 fields in Task 14.5+14.6+14.7. Existing 3 values preserved. 17 new fields added with CHECK (0-100). |
| `fighter_career` | yes (rich: record_*, streaks, current_ranking, title_reigns, title_defenses, legacy_score, market_popularity_local/regional/global, contract_status, career_stage, injury_status, retirement_status, death_flag, peak_rating, career_health, hall_of_fame_flag, legacy_tier) | yes (thin: record_*, streaks, career_health) | yes (thin) | `THIN` — missing ~14 columns |
| `fight_history` | yes (separate from mutable career counters) | no | yes (Task 4) | `OK` — added in Task 4, 14 columns, title_at_stake populated (Task 11) |

**Notes.** `fighter_attributes` and `fighter_personality` are the
**most critical gap remaining**. The v1.6 spec calls for 24 combat
stats and 17+ personality traits; the v1.9.0 build only has 4 and 3.
The fight resolver (Task 3) works with just these 4+3, but every
downstream system (training camps, scouting, voice layer, matchup
analysis, show rating) needs the full attribute set. **A new task
(Task ID 14.5) is needed to extend these to spec.** See §Z for
details.

---

## E. Staff & broadcast

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `staff` | yes (rich: name, age, nationality, role_type, specialty, skill_level, reputation, loyalty, salary, contract_start/end, fatigue, retirement_status, death_flag, promotion_id) | yes (thin: name, age, role_type, specialty, promotion_id, **pundit_bias** added v3.8.0) | yes (thin) | `THIN` — missing ~8 columns (pundit_bias added v3.8.0 for D-GUI-4 Fight Resolution screen) |
| `broadcast_staff` | yes (rich: staff_id, on_air_role, mic_skill, analysis_skill, chemistry_rating, bias, credibility, knowledge_depth, commentary_style, catchphrase_level) | yes (thin: staff_id, on_air_role) | yes (thin) | `THIN` — missing ~8 columns |

**Notes.** UI does not show staff at all yet, even though the table
is seeded (Nina Cross, commentator). Task ID 2's worklog mentioned
"Task ID 6 will add a Staff tab" but Task 6's brief explicitly scoped
it out. **A new task (Task ID 6.5) is needed for a Staff tab.** The
Contracts tab (Task 9) does show staff contracts, but there's no
dedicated staff management view.

---

## F. Contracts

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `contracts` | yes | no | yes (Task 9) | `OK` — polymorphic base, 12 columns, CHECK constraints |
| `fighter_contracts` | yes | no | yes (Task 9) | `OK` — UNIQUE contract_id FK |
| `staff_contracts` | yes | no | yes (Task 9) | `OK` — UNIQUE contract_id FK |
| `broadcast_contracts` | yes | no | yes (Task 9) | `OK` — UNIQUE contract_id FK, 0 rows seeded |

**Notes.** All 4 tables added in Task 9. Contract expiry logic added
in Task 13 (`_check_contract_expiry` in tick_processor.py). Signing
logic added in Task 13 (`sign_free_agent` in app.py). UI Contracts
tab added in Task 9.

---

## G. Events & fights

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `events` | yes (rich: + prestige, glamour_score) | yes (thin: missing prestige, glamour_score) | yes (thin) | `THIN` — missing ~2 columns. Event lifecycle (scheduled → in_progress → completed) added Task 7. |
| `fights` | yes | yes | yes (+card_slot +is_title_fight in v2.2.0) | `OK` — bout_type now includes 'title_fight' (Task 11) |
| `fight_participants` | yes (rich: + official_result, score_total) | yes (thin: missing these) | yes (thin) | `THIN` — missing 2 columns |
| `event_cards` | yes (rich: + is_co_main, notes) | yes (thin: missing these) | yes (+is_co_main in v2.2.0, still missing notes) | `THIN` — missing 1 column (notes) |
| `fight_rounds` | yes (round_number, fighter_a/b_damage, control_time, knockdowns, takedowns, strikes_landed, momentum_state, round_winner_fighter_id) | no | no | `MISSING` — **still missing**. The audit originally said "Task ID 3 or 4" would add it. Neither did. The resolver produces a finish_round but doesn't store per-round stats. Needed for Task 23 (commentary beats), Task 24 (punditry), Task 26 (show rating). **A new task is needed.** |

**Notes.** `fight_rounds` is the most significant missing table in
this group. The fight resolver (Task 3) produces round-level outcomes
(finish_round 1-3) but discards the per-round detail. Adding this
table later would require re-running the resolver or accepting that
historical fights have no round data.

---

## H. Career & medical

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `injuries` | yes (fighter_id, event_id, injury_type, severity, body_area, start_date, projected_return_date, actual_return_date, long_term_damage, career_risk) | no | yes (v2.4.0) | `OK` — Task 15 |
| `training_camps` | yes (fighter_id, gym_id, event_id, dates, camp_focus, camp_morale, camp_fatigue, camp_injury_risk, camp_weight_cut_pressure, camp_result_summary) | no | yes (v2.5.0) | `OK` — Task 16 |
| `weight_cut_log` | yes (fighter_id, fight_id, event_id, weight_class_id, cut_date, target_weight_kg, actual_weight_kg, weight_missed_kg, cut_outcome, cardio_penalty, purse_penalty_pct, is_title_fight) | no | yes (v2.7.0) | `OK` — Task 17 |
| `fighter_descriptors` | yes (fighter_id, attribute_descriptors, personality_descriptors, career_stage, career_health_desc, overall_desc, potential_desc, snapshot_version) | no | yes (v2.8.0) | `OK` — Task 19 |
| `scouting_reports` | yes (scout_id, target_fighter_id, promotion_id, report_date, estimated_potential, estimated_ceiling, estimated_floor, estimated_strengths, estimated_weaknesses, marketability_assessment, injury_risk_assessment, contract_cost_estimate, scout_confidence, is_stale, report_text) | no | yes (v2.9.0) | `OK` — Task 18 |
| `suspensions` | yes (fighter_id, suspension_type, start_date, end_date, duration_days, is_active) | no | yes (Phase B / v3.4.0) | `OK` — Phase B (B1+B2) added 9-column suspensions table (5 suspension_type values via CHECK, duration_days > 0 CHECK, is_active 0/1 CHECK, fighter_id FK NOT NULL ON DELETE CASCADE). Written by src/suspensions.py event-bus subscribers (FIGHT_RESOLVED → _maybe_random_suspension with 1% drug_test + 0.5% behavior chance; TICK_ADVANCED → check_suspension_recovery clears expired suspensions). Read by app._pick_matchup (SQL NOT IN excludes suspended fighters from booking, parallel to the injury exclusion). Player-facing narrative written by news.generate_suspension_news polling subscriber (topic='suspension'). NO raw duration day counts in news text per §14 — uses word-form phrases ("an extended ban", "a multi-month suspension"). Per docs/FULL_BUILD_AUDIT.md §9a. |

---

## I. Scouting & analysis

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `scouting_reports` | yes | no | no | `MISSING` — Task ID 18 (Stage 3) |
| `betting_odds` | yes | no | no | `MISSING` — reserved for a follow-up to Task ID 24 (Stage 4). Task 24 added `matchup_analyses` only (one table-group per CONVENTIONS §5). |
| `matchup_analyses` | yes | no | yes (Task 24) | `OK` — v3.3.0 added 13-column matchup_analyses table (predicted_winner + predicted_method + confidence_pct 0-100 + style_edge + excitement_score 0-100 + upset_risk + analysis_text NOT NULL). UNIQUE (fighter_a_id, fighter_b_id, fight_id). Written by src/punditry.py event-bus subscriber (FIGHT_RESOLVED). NO raw numbers in any text field per §14 (confidence_pct + excitement_score are stored as INTEGER for sorting, but the analysis_text uses word forms). |

---

## J. News & commentary

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `news_sources` | yes (rich: credibility, sensationalism, bias, regional_reach, reliability, frequency) | yes (matches spec) | yes | `OK` |
| `news_items` | yes (rich: + region_id) | yes (thin: missing region_id) | yes (thin) | `THIN` — missing region_id column. News items now written by: fight resolution (Task 3), title changes (Task 11), retirement (Task 12), title vacation (Task 12), contract expiry (Task 13), free agent signing (Task 13), new prospect (Task 14). |
| `commentary_segments` | yes | yes | yes | `OK` — enriched with title-change suffix (Task 11) |
| `pundit_segments` | yes | no | no | `MISSING` — reserved for a follow-up to Task ID 24 (Stage 4). Task 24 added `matchup_analyses` only (one table-group per CONVENTIONS §5); the analysis_text column carries the pundit's voice. A future task can add pundit_segments for round-by-round in-fight commentary. |
| `show_ratings` | yes (event_id, promotion_id, fan_rating, commercial_rating, excitement_rating, quality_rating, overall_rating, rating_description) | no | yes (Task 26 / v3.6.0) | `OK` — v3.6.0 added 10-column show_ratings table (5 rating axes 0-100 CHECK, rating_description TEXT voice descriptor, UNIQUE event_id). Written by src/show_rating.py event-bus subscriber (EVENT_COMPLETED → _compute_show_ratings computes fan/commercial/excitement/quality/overall ratings + writes a topic='show_rating' news item). Read by src/venues.py (Task 27 — reads fan_rating to adjust market heat). NO raw rating numbers in player-facing text per §14 — rating_description uses voice descriptors ("an instant classic", "a lackluster card", etc.). Per docs/STAGES.md Task ID 26. |

---

## K. Rankings & titles

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `rankings` | yes | no | yes (Task 10) | `OK` — ELO-style, 12 columns, auto-update on fight resolution, UI tab |
| `titles` | yes | no | yes (Task 11) | `OK` — 10 columns, 5-case resolution logic, vacated on retirement (Task 12) |

---

## L. Social & rivalries

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `social_posts` | yes | no | yes (Task 21) | `OK` — v3.1.0 added 9-column social_posts table (9 post types via CHECK, engagement + is_beef_escalation columns). Written by src/social.py event-bus subscribers (FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED). NO raw numbers in post_text per §14. |
| `social_accounts` | yes | no | no | `MISSING` — Task 21 chose to skip the separate accounts table. Fighter identity on the `fighters` table is sufficient; the player isn't managing account credentials. If a future task adds account-level state (followers count, verified status, suspended flag), this table can be added then. |
| `rivalries` | yes | no | yes (Task 22) | `OK` — v3.2.0 added 16-column rivalries table (7 rivalry types via CHECK, rivalry_heat 0-100, head-to-head fight counts, is_active flag, voice-layer-driven origin_description). Written by src/rivalries.py event-bus subscribers (FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED). Feeds from social_posts callouts/trash_talks + weight_cut_log misses + close decisions + title changes. NO raw numbers in any description per §14. |

---

## M. Regen & name pools

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `name_first_male` | yes | no | no | `CONSOLIDATED` → merged into `name_pools` (Task 14) |
| `name_first_female` | yes | no | no | `CONSOLIDATED` → merged into `name_pools` (Task 14) |
| `name_last` | yes | no | no | `CONSOLIDATED` → merged into `name_pools` (Task 14) |
| `nickname_pool` | yes | no | no | `CONSOLIDATED` → merged into `name_pools` (Task 14) |
| `region_pool` | yes | no | no | `MISSING` — not implemented. Regions use the existing `regions` table. |
| `regen_templates` | yes | no | no | `MISSING` — not implemented. Style DNA is inherited directly via `fight_style_archetype_id`. |
| `fighter_lineage` | yes | no | yes (as `regen_lineage`) | `CONSOLIDATED` → renamed to `regen_lineage` (Task 14) |
| `fighter_generation_history` | yes | no | no | `MISSING` — not implemented. `regen_lineage` tracks retiring→replacement links, which is sufficient for now. |
| `used_names` | yes | no | no | `MISSING` — by design. Name uniqueness checked against the `fighters` table directly (simpler, avoids redundant table). |
| `fighter_memory_links` | yes | no | yes (Task 14) | `OK` — table exists but NOT populated (memory resurfacing is a future enhancement) |

**Design deviation notes.** Task 14 consolidated the 10 designed
regen tables into 3:
- `name_pools` (one table with a `name_type` column: first_male,
  first_female, last, nickname — replaces 4 separate tables)
- `regen_lineage` (tracks retiring→replacement links — replaces
  `fighter_lineage` + `fighter_generation_history`)
- `fighter_memory_links` (kept as designed, but not populated)

This simplification was a deliberate decision (documented in Task 14's
worklog D1): fewer tables, same functionality, easier to maintain.
The `used_names` table was dropped in favor of checking uniqueness
against the `fighters` table directly.

---

## N. Voice & templates

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `voice_descriptors` | yes | no | no | `MISSING` — Task ID 19 (Stage 3) |
| `commentary_templates` | yes | no | no | `MISSING` — Task ID 23 (Stage 4) |
| `news_templates` | yes | no | no | `MISSING` — Task ID 23 (Stage 4) |
| `bio_templates` | yes | no | no | `MISSING` — Task ID 19 (Stage 3) |

---

## O. Legacy & history

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `fighter_history` | yes | no | yes (Task 4, as `fight_history`) | `OK` — renamed to `fight_history` (more descriptive) |
| `staff_history` | yes | no | no | `MISSING` |
| `company_history` | yes | no | no | `MISSING` |
| `hall_of_fame` | yes | no | no | `MISSING` |
| `legacy_records` | yes | no | no | `MISSING` |

---

## P. Portraits & art

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `portrait_assets` | yes | no | no | `MISSING` — Task ID 29 (Stage 5) |
| `portrait_templates` | yes | no | no | `MISSING` — Task ID 29 (Stage 5) |

---

## Q. Finances

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `finances` | yes (per-event P&L, weekly burn rate, forecast) | no (only `promotions.current_cash` column) | no (still only `current_cash`) | `CONSOLIDATED` → built as `finance_transactions` (Task 20, v3.0.0). One row per transaction (revenue/expense) with type, amount, event_id, fighter_id. Per-event P&L = SUM(amount) WHERE event_id=X. Weekly burn rate = SUM(amount) WHERE transaction_date >= date('now','-7 days') AND amount < 0. |
| `finance_transactions` | yes | no | yes (Task 20, v3.0.0) | `OK` — 9 columns, 11 transaction types via CHECK constraint. Written by src/finance.py event-bus subscriber (FIGHT_RESOLVED). |

---

## R. Modding

| Table | Designed | Built v1.2.0 | Built v1.9.0 | Status |
|---|---|---|---|---|
| `mod_metadata` | yes | no | no | `MISSING` — Task ID 29 (Stage 5) |

---

## Z. Known issues & gaps (not table-specific)

### Z.1 fighter_attributes and fighter_personality still at 4/3 stats (CRITICAL)

The v1.6 spec calls for 24 combat attributes and 17+ personality
traits. The v1.9.0 build still has only 4 (`punch_power`, `cardio`,
`fight_iq`, `chin`) and 3 (`aggression`, `composure`, `morale`).

The fight resolver (Task 3) works with just these 4+3, but every
downstream system needs the full set:
- Task 16 (training camps) needs to modify attributes like
  `takedown_offense`, `submission_defense`, `footwork` — can't
  modify columns that don't exist.
- Task 18 (scouting) needs to report on `accuracy`, `clinch_offense`,
  `cage_wrestling` — can't report on columns that don't exist.
- Task 19 (voice layer) needs to describe `ringcraft`,
  `finish_instinct`, `risk_tolerance` — can't describe columns that
  don't exist.
- Task 24 (matchup analysis) needs `head_movement`,
  `submission_offense`, `top_control` for style-edge analysis.

**A new task (Task ID 14.5) is needed** to extend `fighter_attributes`
from 4 to 24 columns and `fighter_personality` from 3 to 17+ columns.
This is a schema migration (MINOR bump to 1.9.1 or 1.10.0). The
resolver's `_power_score()` function and `_resolve_outcome()` must be
updated to use the full attribute set. The seed must populate the new
columns with default values (50).

### Z.2 fight_rounds table still missing

The resolver produces a `finish_round` (1-3) but doesn't store
per-round stats (damage, strikes, takedowns, knockdowns, control
time, momentum). This table is needed for:
- Commentary beats (Task 23 — "round 2 was all Vale, he landed 15
  significant strikes")
- Punditry (Task 24 — round-by-round analysis)
- Show rating (Task 26 — round-by-round drama is a key input)
- Fighter profile depth (future — career stats per round)

**A new task is needed** to add `fight_rounds` and wire the resolver
to populate it. This should probably happen before or during Task 23
(commentary engine), since commentary needs round-level data to be
believable.

### Z.3 fighters table missing ~14 spec columns

Missing: `height_cm`, `reach_cm`, `stance`, `handedness`,
`injury_proneness`, `weight_cut_difficulty`, `consistency`,
`clutch_factor`, `marketability`, `fan_friendliness`, `promo_boost`,
`preferred_gameplans`, `bad_matchup_tags`, `is_deceased`.

- `injury_proneness` is needed for Task 15 (injuries).
- `weight_cut_difficulty` is needed for Task 17 (weight cuts).
- `is_deceased` is needed for the death flag (spec mentions death as
  a career outcome, though it's optional).
- Physical attributes (`height_cm`, `reach_cm`, `stance`,
  `handedness`) are needed for fighter profiles and matchup analysis.
- Marketability attributes are needed for Task 20 (finances) and
  Task 26 (show rating).

**These should be added** in a migration task, possibly alongside
Z.1 (attribute extension) since both touch the fighter schema.

### Z.4 promotions table missing AI columns

Missing: `ai_aggression`, `ai_spending_style`, `brand_tone`,
`starting_budget`, `broadcast_tier`, `ownership_type`.

- `ai_aggression` and `ai_spending_style` are needed for Task 25
  (rival promotion AI).
- `broadcast_tier` is needed for Task 20 (finances) and Task 26
  (show rating).
- `brand_tone` is needed for Task 23 (news engine — promotion voice).

**These should be added** in a migration task before or during
Task 25.

### Z.5 No Staff UI tab

Task 2's worklog mentioned "Task ID 6 will add a Staff tab" but
Task 6's brief explicitly scoped it out. The `staff` and
`broadcast_staff` tables exist and are seeded (Nina Cross), but the
UI has no dedicated staff management view. The Contracts tab (Task 9)
shows staff contracts, but there's no way to hire/fire staff, view
their skills, or assign them to roles.

**A new task (Task ID 6.5) is needed** for a Staff tab.

### Z.6 Pre-existing `current_date` SQLite quirk (D5)

**Flagged in Tasks 12, 13, 14 but never fixed.** In `app.py`
`get_clock()` (line 17) and `tick_processor.py` `run_tick()` (line 337),
bare `current_date` in SELECTs resolves to SQLite's built-in date
function (today's real date) instead of the `simulation_clock.current_date`
column. This means the clock can jump unpredictably on the first tick
after a fresh build.

All existing tests pass despite this quirk because none assert
specific clock values (tests use `tick_counter` instead). The
retirement, contract expiry, and regen logic are robust because they
use the passed `current_date` parameter, not a bare SELECT.

**Fix:** qualify the column as `simulation_clock.current_date` in
both `app.py` and `tick_processor.py`. This is a small, low-risk
fix that should be done as a housekeeping task.

### Z.7 Stale comments in test_fight_history.py (D6)

The docstring and code comments in `test_fight_history.py` still
mention "placeholder for Task 11" and `'1.3.0'`, but the actual
assertion was updated to `[1, 1]` in Task 11's supervisor sign-off.
The test passes 21/21. **Clean up the stale comments** in a future
housekeeping task.

### Z.8 No `tests/` folder — tests live in `scripts/`

The STAGES.md cross-cutting work section says "A `tests/` folder
lands with Task 3". In practice, tests were placed in `scripts/`
alongside the generation scripts, not in a separate `tests/` folder.
This is a minor convention deviation. The tests are:
`scripts/test_fight_resolver.py`, `scripts/test_fight_history.py`,
`scripts/test_schema_versioning.py`, `scripts/test_promotion_filter.py`,
`scripts/test_event_lifecycle.py`, `scripts/test_event_scheduler.py`,
`scripts/test_contracts.py`, `scripts/test_rankings.py`,
`scripts/test_titles.py`, `scripts/test_retirement.py`,
`scripts/test_free_agency.py`, `scripts/test_regen.py`.

12 acceptance tests, 500+ sub-checks, all passing.

---

## Summary counts

| Category | Designed | Built v1.2.0 | Built v1.9.0 | Gap |
|---|---|---|---|---|
| Schema meta | 2 | 0 | 2 | 0 |
| Geography | 7 | 7 (thin) | 7 (thin) | 0 tables, ~20 columns thin |
| Promotions/gyms/archetypes | 4 | 4 (thin) | 4 (thin) | 0 tables, ~16 columns thin |
| Fighters | 5 | 4 | 5 (fight_history added) | 0 tables, but fighter_attributes WRONG (4/24), fighter_personality WRONG (3/17), fighters THIN (missing ~14 columns) |
| Staff & broadcast | 2 | 2 (thin) | 2 (thin) | 0 tables, ~17 columns thin, no UI tab |
| Contracts | 4 | 0 | 4 | 0 |
| Events & fights | 5 | 4 | 4 | 1 table (fight_rounds still missing) |
| Career & medical | 2 | 0 | 6 (injuries Task 15, training_camps Task 16, weight_cut_log Task 17, fighter_descriptors Task 19, scouting_reports Task 18, suspensions Phase B) | 0 tables |
| Scouting & analysis | 3 | 0 | 1 (matchup_analyses Task 24) | 2 tables (scouting_reports → Task 18, betting_odds → follow-up) |
| News & commentary | 4 | 3 | 4 (show_ratings Task 26) | 1 table (pundit_segments, follow-up to Task 24) |
| Rankings & titles | 2 | 0 | 2 | 0 |
| Social & rivalries | 3 | 0 | 2 (social_posts Task 21, rivalries Task 22) | 1 table (social_accounts deliberately skipped) |
| Regen & name pools | 10 | 0 | 3 (consolidated) | 0 tables (7 consolidated/dropped by design — see §M) |
| Voice & templates | 4 | 0 | 0 | 4 tables (Task 19, 23) |
| Legacy & history | 5 | 0 | 1 (fight_history) | 4 tables |
| Portraits & art | 2 | 0 | 0 | 2 tables (Task 29) |
| Finances | 1 | 0 | 0 | 1 table (Task 20) |
| Modding | 1 | 0 | 0 | 1 table (Task 29) |
| **TOTAL TABLES** | **~60** | **24** | **52** (51 user + 1 sqlite_sequence) | **~9 tables** (down from ~34 because 7 regen tables were consolidated into 3; social_accounts deliberately skipped; remaining gaps are Stage 4+ pundit_segments, betting_odds, fighter_bios variants, hall_of_fame polish, etc.) |
| **TOTAL THIN COLUMNS** | — | — | — | **~67 columns** (geography 20 + promotions/gyms 16 + fighters 14 + staff 17) |
| **WRONG (critical)** | — | — | — | **fighter_attributes (4/24) + fighter_personality (3/17)** — 34 columns missing |

**Headline numbers.**
- Designed: ~60 logical tables (the "83+" figure in the advisor's
  analysis counts every FK and lookup table separately; the logical
  table count is ~60).
- Built v1.2.0: 24 tables.
- Built v1.9.0: 37 tables (+13 from Tasks 2-14).
- Built v3.2.0 (Task 22): 48 tables (47 user + 1 sqlite_sequence).
  +11 from Tasks 15-22: injuries (15), training_camps (16),
  fighter_bios + hall_of_fame (16.5), weight_cut_log (17),
  fighter_descriptors (19), scouting_reports (18),
  finance_transactions (20), social_posts (21), rivalries (22).
- Built v3.3.0 (Task 24): 49 tables (48 user + 1 sqlite_sequence).
  +1 from Task 24: matchup_analyses (punditry / matchup analysis).
- Built v3.4.0 (Phase B — B1+B2): 50 tables (49 user + 1 sqlite_sequence).
  +1 from Phase B: suspensions (fighter drug test / behavior bans).
- Built v3.5.0 (Phase C — agent offers): 51 tables (50 user + 1 sqlite_sequence).
  +1 from Phase C: agent_offers (unknown talent / gamble signing system).
- Built v3.6.0 (Stage 5 — Task 26 show rating): 52 tables (51 user + 1 sqlite_sequence).
  +1 from Task 26: show_ratings (per-event fan / commercial / excitement /
  quality / overall ratings + voice-layer rating_description).
- 34 acceptance tests, 2200+ sub-checks, all passing.

**Most critical gaps (priority order):**
1. **fighter_attributes + fighter_personality extension** (Z.1) —
   blocks Tasks 16, 18, 19, 24. Should be the first task in Stage 3.
2. **fight_rounds table** (Z.2) — blocks Tasks 23, 24, 26. Should
   be added before or during Task 23.
3. **fighters table column extension** (Z.3) — blocks Tasks 15, 17,
   20, 26. Should be added alongside Z.1.
4. **promotions table AI columns** (Z.4) — blocks Task 25. Should
   be added before or during Task 25.
5. **Staff UI tab** (Z.5) — quality of life. Can be done anytime.
6. **`current_date` quirk fix** (Z.6) — pre-existing bug. Should be
   fixed as a housekeeping task before Stage 3.
