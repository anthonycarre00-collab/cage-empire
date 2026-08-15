> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# EXISTING SYSTEMS AUDIT — CAGE EMPIRE

> **Task ID:** EXISTING-SYSTEMS-AUDIT
> **Agent:** DB + Systems Auditor (general-purpose)
> **Date:** 2026-08-19 (sim)
> **Parent docs:** `docs/RIVAL_AI_ARCHITECTURE.md` (proposed build target),
> `docs/CAGE_EMPIRE_SOUL.md`, `docs/CONVENTIONS.md`
> **Constraint:** RESEARCH + AUDIT ONLY — no code changes. All findings
> derived from live DB queries against `data/cage_empire.db` (schema
> v3.13.0, 58 tables, 22 migrations) and source-code inspection of
> 24 service + engine modules.

---

## 0. Executive Summary

**The user's concern is valid and partially confirmed.** The
RIVAL_AI_ARCHITECTURE.md doc proposes 8 "new" systems; **5 of them
already exist as functional infrastructure** (events, matchmaking,
signing, finance event-P&L, staff table) and only need to be **wired
into the rival AI**, not rebuilt. **2 are partially incomplete**
(strategic budget management; staff hiring/firing AI logic). **3 are
genuinely new** (the 4-archetype system; fighter cutting; bidding
wars). The architecture doc itself acknowledges most of this — it
explicitly says "Everything else (events, fights, contracts, staff,
finance_transactions tables) is reused unchanged" (line 45). The risk
of reinventing is **LOW** if the implementation task hews to the
doc's "wire, don't rebuild" intent.

**The staff system specifically is NOT lost** — the user's worry is
understandable but unfounded. The `staff` table has 375 rows, every
promotion already has 7-8 staff (1 GM, 2 scouts, 2-3 commentators,
1 doctor, 1 cutman), and the schema has both `promotion_id` and
`gym_id` columns. What's missing is the **rival-AI logic to manage
staff** (hire/fire), not the staff system itself. There IS a data
hygiene issue: the 300 coaches are orphan (both `promotion_id` AND
`gym_id` are NULL) because `seed_world_phase2.py` was never updated
after the v3.9.0 migration added the `gym_id` column. This is a
one-line backfill, not a rebuild.

**Single most important takeaway:** the implementation task should
be reframed as **"wire the rival AI into existing systems + add 3
genuinely new modules"**, not "build 8 new systems." The
architecture doc's proposed 7-module `src/services/rival_ai/`
package is the right shape — but 4 of those modules are mostly
**wiring + thin decision logic** that CALL existing functions, not
greenfield builds.

---

## Part 1: Full DB Schema Inventory

**DB file:** `data/cage_empire.db`
**Schema version:** 3.13.0 (from `schema_meta`)
**Migrations applied:** 22 (from `schema_migrations`)
**Total tables:** 58 (excluding `sqlite_*` internal tables)

### 1.1 Table inventory (alphabetical, with row counts)

| # | Table | Cols | Rows | Purpose | Rival-AI / automation writes? |
|---|---|---:|---:|---|---|
| 1 | `agent_offers` | 12 | **0** | Mystery-box talent offers from agents to the player (Phase C). Schema + writer (`src/agent_offers.py`) exist; **0 rows = designed but never fired** | Player-only — rival AI does NOT call `agent_offers.py` |
| 2 | `broadcast_contracts` | 5 | **0** | Polymorphic contract subtype linking a `staff` commentator to a broadcast network. Schema exists; **0 rows = unused** | None |
| 3 | `broadcast_staff` | 5 | **0** | Marks a `staff` member as on-air talent with an `on_air_role`. Schema exists; **0 rows = unused** (commentators are just `staff.role_type='commentator'`) | None |
| 4 | `cities` | 7 | 114 | Geographic city reference | None (seed only) |
| 5 | `commentary_segments` | 8 | 65 | In-fight commentary text fragments | Written by `services/fight_engine._select_commentary_beats` — fires for rival fights too (via shared `resolve_next_fight`) |
| 6 | `contracts` | 12 | 986 | Polymorphic contract base. `contract_target_type ∈ {'fighter','staff','broadcast'}`. 317 active + 669 terminated. **ALL 986 rows are `target_type='fighter'` — ZERO staff or broadcast contracts exist** | Rival AI calls `sign_free_agent()` which writes fighter contracts |
| 7 | `daily_headlines` | 8 | 112 | Voice-layer daily news headlines cache | Written by `interpretation/headline_engine` (post-commit daily pass) |
| 8 | `division_descriptors` | 7 | **0** | Per-weight-division narrative cache | **0 rows — interpretation engine stub not yet populating** |
| 9 | `event_cards` | 9 | 63 | Mapping fights → card slots (main_event, co_main, featured_prelim, prelim) on an event | Written by `schedule_next_event` (called by rival AI) |
| 10 | `events` | 10 | 1894 | Promotion events (1886 completed, 8 scheduled). Recent rival-AI scheduling: 8 events for 8 rival promos on 2026-08-23/2026-09-06 | Written by `schedule_next_event` (called by rival AI) |
| 11 | `fight_beats` | 13 | 232 | Per-beat fight resolution trace | Written by `services/fight_engine` — fires for rival fights too |
| 12 | `fight_history` | 14 | 3614 | Per-fighter fight log (one row per fighter per fight, so 2 rows per fight) | Written by `resolve_next_fight` — fires for rival fights too |
| 13 | `fight_participants` | 6 | 126 | Links fighters to fights with corner + winner flag | Written by `schedule_next_event` + `resolve_next_fight` |
| 14 | `fight_rounds` | 20 | 13 | Per-round fight summary (rare — only some fights have round-level data) | Written by `resolve_next_fight` |
| 15 | `fighter_attributes` | 30 | 4458 | Per-fighter 28-attribute block (punch_power, cardio, chin, etc.) | Written by `career_arc.py` (monthly drift), training camp completion, injuries |
| 16 | `fighter_bios` | 5 | 4458 | Free-form bio text per fighter | Seed only |
| 17 | `fighter_career` | 12 | 4458 | Career stats (record_wins/losses/draws, win_streak, career_health, potential, title_reigns) | Written by `resolve_next_fight`, `_check_retirements`, training camps |
| 18 | `fighter_contracts` | 5 | 986 | Polymorphic contract subtype linking contract → fighter | Written by `sign_free_agent` (called by rival AI) |
| 19 | `fighter_descriptors` | 15 | 4458 | Per-fighter voice-layer descriptor cache (momentum, pressure, career_phase, narrative_family, etc.) | Written by `interpretation/snapshot_cache.run_daily_interpretation_pass` + `refresh_fighter` |
| 20 | `fighter_memory_links` | 6 | 42 | Links between fighters (style echoes, gym heirs, successors) — Task 14 design | Mostly seed + regen |
| 21 | `fighter_personality` | 24 | 4458 | Personality traits (aggression, composure, discipline, etc.) + `morale` column | Written by `morale.py` (FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED subscribers) |
| 22 | `fighters` | 33 | 4458 | Master fighter table. Includes `current_promotion_id`, `current_gym_id`, `marketability`, `is_active`, `is_retired` | Written by `sign_free_agent`, `_check_retirements`, `generate_fighter` (regen) |
| 23 | `fights` | 17 | 1862 | Per-fight row (event_id, weight_class_id, card_slot, is_title_fight, winner, result_type, etc.) | Written by `schedule_next_event` + `resolve_next_fight` |
| 24 | `finance_transactions` | 9 | 41 | Per-event revenue + expense ledger. 9 sponsorship rows (seed) + 32 event-P&L rows (all for promo_id=6 Mexican Boxing) | Written by `finance.py._process_event_finance` subscriber — fires on EVENT_COMPLETED for ALL promos, but most rival events pre-date v3.0.0 finance system |
| 25 | `gym_descriptors` | 8 | **0** | Per-gym narrative cache | **0 rows — interpretation engine stub not yet populating** |
| 26 | `gyms` | 15 | 300 | Gym master table (reputation, membership_cost, facility_quality, medical_support, sparring_depth, etc.) | Reputation written by `reputation.py` (FIGHT_RESOLVED, TITLE_CHANGED, CAMP_COMPLETED) |
| 27 | `hall_of_fame` | 5 | **0** | HoF inductees. Schema + `services/hof_svc.py` exist; **0 rows = no fighter has been inducted via gameplay yet** | Written by `services/hof_svc.py` subscriber on FIGHTER_RETIRED — but only eligible fighters (title_reigns ≥ 2 OR wins ≥ 30 OR wins≥20+title) get inducted |
| 28 | `injuries` | 15 | 397 | Active + historical injuries (severity, body_area, projected_return_date, long_term_damage, career_risk) | Written by `_maybe_create_injury` (in fight_engine) + training camps. Rival fights produce injuries too |
| 29 | `interpretation_cache_meta` | 5 | 1 | Single-row cache metadata (engine_version, last_build_date, fighter_count) | Written by `snapshot_cache.run_daily_interpretation_pass` |
| 30 | `markets` | 6 | 114 | Market master (city_id, market_type, heat_level 0-100) | Heat written by `venues.py` (EVENT_COMPLETED + monthly TICK_ADVANCED) |
| 31 | `matchup_analyses` | 13 | 8 | Pundit pre-fight predictions (predicted_winner, predicted_method, confidence_pct, style_edge, etc.) | Written by `punditry.py` subscriber on FIGHT_RESOLVED — fires for rival fights too (8 rows = small sample) |
| 32 | `name_pools` | 5 | 3726 | First/last/nickname pools for regen engine | Seed only |
| 33 | `nations` | 5 | 20 | Nation reference | Seed only |
| 34 | `news_items` | 12 | 524 | All news items (topic, sentiment, headline, body, links to fighter/promo/event/fight) | Written by `news.py` (subscriber) + many direct INSERTs |
| 35 | `news_sources` | 10 | 6 | News outlet reference (credibility, sensationalism, bias, etc.) | Seed only |
| 36 | `personality_archetypes` | 5 | 5 | 5 personality archetype templates | Seed only |
| 37 | `player_settings` | 3 | 7 | 7 player preferences (news filter, difficulty, etc.) | UI / settings module |
| 38 | `promotion_descriptors` | 6 | **0** | Per-promotion narrative cache | **0 rows — interpretation engine stub not yet populating** |
| 39 | `promotions` | 16 | 10 | 10 promotions. Has `ai_aggression` + `ai_spending_style` columns (existing). **Missing:** `ai_archetype`, `ai_scheduling_day_of_week`, `ai_budget_state` (proposed by arch doc) | Cash written by `finance.py`; reputation by `reputation.py` |
| 40 | `rankings` | 12 | 678 | ELO rankings (one row per fighter per WC per promo). 678 rows across 10 promos × 13 WCs | Written by `_update_rankings_after_resolution` (fires for rival fights too) |
| 41 | `regen_lineage` | 6 | 8 | Replacement fighter lineage (retiring_fighter_id → replacement_fighter_id) | Written by `_check_retirements` via `generate_fighter` |
| 42 | `regions` | 8 | 54 | Geographic region reference | Seed only |
| 43 | `rivalries` | 15 | 97 | Pairwise fighter rivalries (97 rows: 25 bad_blood, 40 rematch_hungry, 32 title_rivalry). Heat 0-100, is_active flag | Written by `rivalries.py` subscribers (FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED) — fires for rival fights too |
| 44 | `schema_meta` | 3 | 1 | Single-row schema version tracker | Migration framework |
| 45 | `schema_migrations` | 2 | 22 | 22 applied migrations log | Migration framework |
| 46 | `scouting_reports` | 18 | **0** | Per-scout report on a target fighter. Schema + `src/scouting.py` writer exist; **0 rows = no scout has ever been assigned** | Player-only — `assign_scout()` is UI-driven; rival AI does NOT call it |
| 47 | `show_ratings` | 10 | 2 | Per-event 5-axis ratings (fan/commercial/excitement/quality/overall). Only 2 rows = recent Mexican Boxing events only | Written by `show_rating.py` subscriber on EVENT_COMPLETED — fires for ALL promos, but only 2 events have completed since v3.6.0 |
| 48 | `simulation_clock` | 9 | 1 | Single-row sim clock (current_date='2026-08-19', current_day=31, current_week=5, current_month=8, current_year=2026) | Written by `run_tick` |
| 49 | `social_posts` | 9 | 157 | Fighter social media posts (9 types: callout, trash_talk, hype, apology, etc.) | Written by `social.py` subscribers — fires for rival fights too |
| 50 | `staff` | 12 | 375 | **STAFF TABLE — 375 rows, 6 role types.** See Part 3 deep dive | Written by `seed_world_phase2.py` (seed only) — **rival AI does NOT write** |
| 51 | `staff_contracts` | 5 | **0** | Polymorphic contract subtype for staff. Schema + `_seed_default_staff_contract()` function exist; **0 rows = unused** | None — function exists but never called on live DB |
| 52 | `style_archetypes` | 5 | 7 | 7 fighter style archetypes (Balanced, Striker, Grappler, Wrestler, Brawler, Counter-Striker, Submission Specialist) | Seed only |
| 53 | `suspensions` | 9 | 4 | Fighter suspensions (drug_test_failure, behavior). 4 rows = rare but functional | Written by `suspensions.py` subscribers (FIGHT_RESOLVED + TICK_ADVANCED) — fires for rival fights too |
| 54 | `titles` | 10 | 111 | Per-promo per-WC titles. 111 total: 48 held, 63 vacant. Current champions tracked | Written by `_resolve_title_after_fight` (fires for rival fights too) |
| 55 | `training_camps` | 19 | 176 | Per-fighter per-fight training camps (camp_focus, fatigue, morale, injury_risk, attribute_changes). 116 active + 60 completed | Written by `_create_training_camp` (in matchmaking, called by rival AI's `schedule_next_event`) + progressed by `tick_processor._check_training_camps` |
| 56 | `venues` | 6 | 276 | Venue master (city_id, name, capacity) | Seed only (no writer beyond seed) |
| 57 | `weight_classes` | 8 | 13 | 13 weight classes (gender-specific) | Seed only |
| 58 | `weight_cut_log` | 14 | 16 | Per-fight weight cut records (target_weight, actual_weight, cut_outcome, cardio_penalty, purse_penalty_pct) | Written by `_run_weight_cut` (in fight_engine) — fires for rival fights too |

### 1.2 Key observations from the schema inventory

1. **The `promotions` table does NOT have the 3 columns the arch doc
   proposes** (`ai_archetype`, `ai_scheduling_day_of_week`,
   `ai_budget_state`). These are genuinely MISSING and would require
   a v3.14.0 migration. The existing `ai_aggression` (0-100) and
   `ai_spending_style` ('conservative'/'balanced'/'aggressive')
   columns ARE present and used by the current `rival_ai.py`.

2. **5 tables are EMPTY (0 rows) despite having full schemas +
   writers**: `agent_offers`, `broadcast_contracts`, `broadcast_staff`,
   `hall_of_fame`, `scouting_reports`, `staff_contracts`, plus 3
   descriptor cache tables (`gym_descriptors`,
   `promotion_descriptors`, `division_descriptors`). These are
   **designed-but-unused systems**, not missing systems.

3. **The `contracts` table CHECK constraint allows
   `contract_target_type ∈ {'fighter','staff','broadcast'}`**, but
   only `'fighter'` contracts exist (986 rows). The infrastructure
   for staff + broadcast contracts EXISTS in schema — it's just never
   written to. The arch doc's proposal to track staff salaries via
   `staff_contracts` could be wired into the existing polymorphic
   pattern without a schema change.

4. **Rival AI activity is visible across the schema**: 8 scheduled
   events for 8 rival promos on 2026-08-23/2026-09-06; recent
   contracts (id=977-986) show rival signings; rankings + titles +
   rivalries + social_posts + news_items all have rows for non-player
   promotions. The existing rival AI IS functional — it's just
   simplistic (10% weekly signing chance, random matchmaking).

---

## Part 2: Existing Code Inventory

For each of the 17 modules listed in the task brief, here's what
exists and whether the rival AI already hooks into it:

### 2.1 Module-by-module audit

| # | Module | Lines | Purpose | Rival AI hooks into it? |
|---|---|---:|---|---|
| 1 | `src/rival_ai.py` | 547 | Current rival AI: subscribes to TICK_ADVANCED, daily event-resolution + weekly scheduling + 10% weekly FA signing. Uses `ai_aggression` (cadence) + `ai_spending_style` (potential floor). | **IS the rival AI** — arch doc proposes refactoring into `src/services/rival_ai/` package |
| 2 | `src/services/matchmaking.py` | 1493 | `schedule_next_event()` + `_build_main_event` / `_build_co_main` / `_build_featured_prelim` / `_build_prelim` + `_get_available_fighters_for_card` + `_create_training_camp` + camp focus maps. Card-size by tier (major 10-13, mid 7-9, small 5-6). | **YES** — `rival_ai.py` line 441 calls `schedule_next_event(conn, promotion_id=promo_id, weeks_out=weeks_out)` |
| 3 | `src/services/contracts.py` | 327 | `sign_free_agent()` (signs FA + creates contract + writes news + publishes FIGHTER_SIGNED) + `get_contracts_for_display` + `get_free_agents_for_display`. Refuses retired / already-signed fighters. | **YES** — `rival_ai.py` line 508 calls `sign_free_agent_fn(conn, fighter_id, promotion_id, start_date)` |
| 4 | `src/services/finance_svc.py` | 24 | Thin wrapper re-exporting `src/finance.py`. | Inherited from finance.py |
| 5 | `src/finance.py` | 290 | Subscribes to FIGHT_RESOLVED → `_process_event_finance`. Per-event P&L: ticket_sales (capacity × fill_rate × price), broadcast_revenue (by tier), merchandise (fighter marketability), fighter_purse (-salary), venue_rental, staff_salary (-$2K × staff_count), medical_cost (-$1.5K × fights), weight_cut_penalty. Updates `promotions.current_cash`. | **YES (passive)** — fires automatically on EVENT_COMPLETED for rival fights. **DOES NOT** do strategic budget management (no SURVIVAL/CONSERVATIVE/NORMAL/EXPANSION state machine, no monthly review, no crisis handling). |
| 6 | `src/services/training_svc.py` | 47 | Thin wrapper delegating to `tick_processor._check_training_camps`. | Inherited — camps progress for rival fighters automatically |
| 7 | `src/services/scouting_svc.py` | 22 | Thin wrapper re-exporting `src/scouting.py`. | **NO** — `assign_scout()` is UI-driven; rival AI never calls it. The 20 scouts across 10 promos are seeded but never produce reports. |
| 8 | `src/scouting.py` | 752 | Full scouting engine: `assign_scout()` (sets `current_assignment` in scout's specialty JSON), `_check_scouting_assignments()` (tick subscriber — generates report after 7 days), `generate_scouting_report()` (applies accuracy model + biases + mistake rolls, writes to `scouting_reports`), `mark_stale_reports()`. Rich specialty JSON schema: eye_for_talent, technical_analysis, character_reading, mistake_rate, bias_style, bias_nationality, bias_aggression, current_assignment, assignment_start_date. | **NO** — see above. **0 rows in `scouting_reports`** confirms no scout has ever been assigned. |
| 9 | `src/services/rivalries_svc.py` | 25 | Thin wrapper re-exporting `src/rivalries.py`. | Inherited |
| 10 | `src/rivalries.py` | 1053 | Full rivalries engine: 7 rivalry types (callout, bad_blood, title_rivalry, rematch_hungry, style_clash, disrespect, stolen_opportunity). Heat escalation (+5 callout, +15 fight, +25 title fight, +10 weight-cut miss, -15 apology). Weekly heat decay. Same-roster restriction (cross-promo only 5% chance). Subscribes to FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED. | **YES (passive)** — fires automatically on rival fight events. 97 rivalry rows across all 10 promos. |
| 11 | `src/services/hof_svc.py` | 602 | HoF induction: subscribes to FIGHTER_RETIRED, evaluates eligibility (title_reigns≥2 OR wins≥30 OR wins≥20+title), inducts with voice-layer career_summary + career_highlights. | **YES (passive)** — fires automatically when any fighter retires, including rival-promo fighters. **0 rows** because no eligible fighter has retired since v3.x wiring. |
| 12 | `src/services/retirement_svc.py` | 822 | `generate_fighter()` (regen replacement) + `_vacate_title_on_retirement()` + `check_retirements()` wrapper. | **YES (passive)** — fires for rival fighters via `_check_retirements` in tick_processor. 8 regen_lineage rows confirm regen has fired 8 times. |
| 13 | `src/services/injuries_svc.py` | 48 | Thin wrapper delegating to `tick_processor._check_injury_recovery`. | Inherited — injuries recover for rival fighters too |
| 14 | `src/career_arc.py` | 569 | Monthly fighter attribute drift: growth (age 18-27, capped at effective_ceiling), prime (28-29, no change), decline (30+, accelerating per attribute). Subscribes to TICK_ADVANCED (monthly tick). | **YES (passive)** — fires for all active fighters including rival-promo fighters. 300 news items with topic='career_arc' confirm it's running. |
| 15 | `src/reputation.py` | 469 | Dynamic reputation: `promotions.reputation` (EVENT_COMPLETED show_rating ±, TITLE_CHANGED +1, drug-test -3, bankruptcy -2) + `gyms.reputation` (FIGHT_RESOLVED winner +1 / KO-loser -1, TITLE_CHANGED +3, CAMP_COMPLETED +0.5). Subscribes to 5 events. | **YES (passive)** — fires for rival events automatically. |
| 16 | `src/morale.py` | 1661 | Fighter morale + dynamic meta-fields: `fighter_personality.morale` (FIGHT_RESOLVED winner/loser swings, TITLE_CHANGED ±15, weekly drift, CAMP_COMPLETED +3, CAMP_INJURY -5) + 7 fighters.* dynamic fields (marketability, fan_friendliness, etc.). | **YES (passive)** — fires for rival fights automatically. |
| 17 | `src/show_rating.py` | 640 | Per-event 5-axis ratings (fan, commercial, excitement, quality, overall) + voice descriptor. Subscribes to EVENT_COMPLETED. | **YES (passive)** — fires for rival events automatically. Only 2 rows because only 2 events have completed since v3.6.0 wiring. |
| 18 | `src/venues.py` | 234 | Market heat dynamics: EVENT_COMPLETED (±heat based on fan_rating), monthly drift (hot markets cool toward 70, cold warm toward 40). | **YES (passive)** — fires for rival events automatically. |
| 19 | `src/agent_offers.py` | 881 | Mystery-box talent offers: 5 offer types (unknown_talent, washout_veteran, style_specialist, contender_release, prospect_gamble). 10% weekly chance per PLAYER promo. 14-day expiry. Voice-layer descriptions only. `resolve_offer()` for Accept/Reject. | **NO** — explicitly player-only. The `agent_offers` table has `promotion_id` so it COULD be extended to rival AI, but the current code is hardcoded to the player. **0 rows** because the player hasn't been offered anything yet (10% × weekly tick hasn't fired). |
| 20 | `src/punditry.py` | 1344 | Pre-fight matchup analysis (predicted_winner, predicted_method, confidence_pct, style_edge, excitement_score, upset_risk). Subscribes to FIGHT_RESOLVED. | **YES (passive)** — fires for rival fights automatically. 8 rows confirms it's running. |
| 21 | `src/suspensions.py` | 465 | Drug-test (1% per fight) + behavior (0.5% per fight, higher for aggressive/low-discipline fighters) suspensions. Morale + marketability penalties. | **YES (passive)** — fires for rival fights automatically. 4 rows confirms it's running. |
| 22 | `src/tick_processor.py` | 1699 | The tick orchestrator: `_check_injury_recovery`, `_check_training_camps` (progress + complete), `_check_retirements`, `_check_contract_expiry`, `run_tick()` (advances clock, runs all checks, publishes TICK_ADVANCED, runs daily interpretation pass post-commit). | Inherited — the rival AI subscribes to TICK_ADVANCED published by `run_tick`. |
| 23 | `src/news.py` | 3245 | News engine: subscribes to many events, generates voice-layer news items. | **YES (passive)** — fires for all events including rival. 524 news items confirm broad activity. |
| 24 | `src/social.py` | 1226 | Fighter social media posts: 9 post types, personality-driven frequency + content. | **YES (passive)** — fires for rival fights. 157 posts confirm. |
| 25 | `src/voice.py` | 904 | Voice layer: career stage descriptors, attribute descriptors, overall descriptors, personality descriptors. Foundation for all player-facing text. | Inherited — used by all the above |
| 26 | `src/event_bus.py` | 210 | In-memory pub/sub. 16 event types (FIGHT_RESOLVED, FIGHT_CANCELLED, TITLE_CHANGED, EVENT_COMPLETED, FIGHTER_RETIRED, FIGHTER_SIGNED, FIGHTER_GENERATED, CONTRACT_EXPIRED, CAMP_COMPLETED, CAMP_INJURY, INJURY_CREATED, INJURY_RECOVERED, WEIGHT_CUT_COMPLETED, SCOUT_REPORT_GENERATED, FIGHTER_STATE_CHANGED, TICK_ADVANCED). | Inherited |
| 27 | `src/interpretation/snapshot_cache.py` | 430 | Daily interpretation pass + single-fighter refresh. Writes to `fighter_descriptors`, `gym_descriptors`, `promotion_descriptors`, `division_descriptors`, `daily_headlines`. | Inherited — runs post-commit on every tick. **The "performance caching" the arch doc proposes already exists** (just not for the specific "rival AI roster cache" the arch doc wants to add). |

### 2.2 Summary of the 8 "new" systems in the arch doc

| Proposed "new" system | Does it exist? | Where? | What's missing? |
|---|---|---|---|
| **Staff hiring/firing** | **Schema + seeded data exist; AI logic does NOT** | `staff` table (375 rows, 6 role types), `staff_contracts` table (0 rows), `staff.promotion_id` column, `staff.gym_id` column. Every promo has 7-8 staff. `_seed_default_staff_contract()` function exists but never run on live DB. | **Missing:** rival-AI logic to UPDATE `staff.promotion_id=NULL` (fire) or INSERT new `staff` rows (hire). Also: 300 coaches are orphan (`gym_id IS NULL`) — need backfill. |
| **Budget management** | **Event-P&L exists; strategic budget does NOT** | `finance_transactions` table (41 rows), `src/finance.py` (event revenue + expenses), `promotions.current_cash` column. | **Missing:** monthly budget review, SURVIVAL/CONSERVATIVE/NORMAL/EXPANSION state machine, `promotions.ai_budget_state` column, crisis handling, ownership-change escape hatch. |
| **Fighter signing with bidding wars** | **Signing exists; bidding wars do NOT** | `sign_free_agent()` in `services/contracts.py` (327 lines). Called by rival AI at 10% weekly chance per promo. | **Missing:** multi-promo offer collection, offer_score formula, winner selection, bid_premium_pct, loser news items. |
| **Fighter cutting** | **Does NOT exist** | (Nothing — fighters only leave via contract expiry) | **Genuinely new.** Need: cut_risk scoring, protective rules (champion / loyalty / prospect / title-shot protection), archetype aggressiveness, news items. |
| **Event scheduling** | **EXISTS, fully functional** | `schedule_next_event()` in `services/matchmaking.py` (lines 1142-1493). Called by rival AI weekly. | **Missing (arch doc proposals):** `promotions.ai_scheduling_day_of_week` column for round-robin distribution; archetype-based cadence (currently only `ai_aggression`); budget gate; rival collision avoidance. |
| **Matchmaking** | **EXISTS, fully functional** | `_build_main_event` (champ vs #1, vacant #1 vs #2, fallback top-2), `_build_co_main`, `_build_featured_prelim`, `_build_prelim`. All in `services/matchmaking.py`. | **Missing (arch doc proposals):** biased matchup scoring (marketability + competitiveness + storyline + development_value), imperfection injector (head-scratcher path), separate `services/rival_ai/matchmaker.py` wrapper. |
| **Archetype system** | **Does NOT exist (as proposed)** | (Nothing — the 7 `style_archetypes` are FIGHTER styles, not promotion archetypes) | **Genuinely new.** Need: `promotions.ai_archetype` column, `ARCHETYPES` dict, `assign_archetype()` function, quarterly re-eval. |
| **Performance caching** | **EXISTS** | `interpretation/snapshot_cache.py` (daily pass + single-fighter refresh). Already used by 4 event-bus subscribers. `interpretation_cache_meta` table tracks engine version. | **Missing (arch doc proposal):** per-(promotion_id, date) roster cache for `_get_available_fighters_for_card`. The existing snapshot cache is per-fighter, not per-roster. |

---

## Part 3: The "Staff" System Deep Dive

The user specifically called out staff. Here's the full picture.

### 3.1 Staff table schema

```sql
CREATE TABLE staff (
    staff_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    age           INTEGER NOT NULL,
    nation_id     INTEGER REFERENCES nations(nation_id),
    role_type     TEXT NOT NULL,           -- 'coach','commentator','scout','general_manager','doctor','cutman'
    specialty     TEXT,                    -- JSON for scouts; literal for others ('head_coach:bjj','play_by_play','operations','sports_medicine','cuts_and_swelling')
    promotion_id  INTEGER REFERENCES promotions(promotion_id),  -- set for promo-bound staff
    gym_id        INTEGER REFERENCES gyms(gym_id),              -- added v3.9.0, intended for coaches
    pundit_bias   TEXT,                    -- JSON for broadcast pundits (added v3.8.0)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

### 3.2 Live DB staff inventory

| Role | Count | Promotion-bound? | Gym-bound? | Specialty |
|---|---:|---|---|---|
| `coach` | 300 | **NO** (all NULL) | **NO** (all NULL — orphan!) | `'head_coach:striking'`, `'head_coach:wrestling'`, `'head_coach:bjj'`, `'head_coach:judo'`, `'head_coach:mma'` |
| `commentator` | 25 | YES (2-3 per promo) | N/A | `'play_by_play'` |
| `scout` | 20 | YES (2 per promo) | N/A | **Rich JSON**: `{eye_for_talent, technical_analysis, character_reading, mistake_rate, bias_style, bias_nationality, bias_aggression, current_assignment, assignment_start_date}` |
| `general_manager` | 10 | YES (1 per promo) | N/A | `'operations'` |
| `doctor` | 10 | YES (1 per promo) | N/A | `'sports_medicine'` |
| `cutman` | 10 | YES (1 per promo) | N/A | `'cuts_and_swelling'` |
| **TOTAL** | **375** | 75 promo-bound + 300 orphan coaches | 0 gym-bound | |

### 3.3 Per-promotion staff breakdown (sample — Alpha Combat Federation)

| Promotion | GM | Commentator | Scout | Doctor | Cutman | Total |
|---|---:|---:|---:|---:|---:|---:|
| Alpha Combat Federation | 1 | 3 | 2 | 1 | 1 | 8 |
| Rival Fight League | 1 | 3 | 2 | 1 | 1 | 8 |
| Pacific Rim Championship | 1 | 3 | 2 | 1 | 1 | 8 |
| European Fight Network | 1 | 2 | 2 | 1 | 1 | 7 |
| South American Warriors | 1 | 2 | 2 | 1 | 1 | 7 |
| Mexican Boxing & Brawl | 1 | 2 | 2 | 1 | 1 | 7 |
| Nordic Fight Nights | 1 | 3 | 2 | 1 | 1 | 8 |
| Eastern Bloc Combat | 1 | 3 | 2 | 1 | 1 | 8 |
| Australian Outback Fights | 1 | 2 | 2 | 1 | 1 | 7 |
| French Savate Championship | 1 | 2 | 2 | 1 | 1 | 7 |

**This is EXACTLY the staff_target the arch doc proposes** for the
4 archetypes (§2.2): `{scout: 2-3, commentator: 2-3, doctor: 1,
cutman: 1, general_manager: 1}`. The seed already produces the
target. The arch doc's "staff_manager" module would manage
**deviations from this baseline** (hire 3rd scout for a Major
League, fire a scout for a Grassroots).

### 3.4 The coach orphan problem

The arch doc (§3.5) claims: *"the live DB has 300 coaches, all
linked to `gym_id` (not `promotion_id`)."* **This is FALSE.** The
live DB has 300 coaches with BOTH `gym_id IS NULL` AND
`promotion_id IS NULL`. They are orphan staff.

**Root cause:** `scripts/seed_world_phase2.py` (line 364-375)
contains this stale comment:

```python
# Coaches don't have a promotion_id (they're at a gym, not a promotion)
# The staff table has promotion_id but for coaches we leave it NULL.
# The gym link isn't in the staff table — we'll need to add it via
# a separate concept. For now, store gym_id in specialty field as
# a hint (e.g. "head_coach:bjj:gym_id=42"). Actually, the staff
# table doesn't have a gym_id column — we'll just note the gym
# in the specialty.
```

This comment was written BEFORE migration `v3_9_0_add_staff_gym_id`
added the `gym_id` column (build_db.py line 658). The seed script
was never updated to populate `gym_id` after the migration landed.
The result: 300 coaches exist as STAFF ROWS but are not linked to
any gym or promotion.

**Note:** Fighters DO have `current_gym_id` set (4456/4458 fighters
have it). So fighters are linked to gyms, but coaches are NOT linked
to gyms. This is the "lost" connection the user may have sensed.

**Fix:** A one-line backfill migration (match coaches to gyms by
nation_id or sequentially) would resolve this. The arch doc's
Open Question Q5 asks whether to extend rival AI to manage coaches
— the answer should be YES, but ONLY after the backfill.

### 3.5 The staff_contracts gap

The polymorphic `contracts` pattern supports `target_type='staff'`
(the CHECK constraint allows it). The `_seed_default_staff_contract()`
function in `src/seed_data.py` (line 73) creates a 12-month staff
contract with $50K salary. But:

- The function is only called for COMMENTATORS (line 685) in
  `seed_data.py` — and even then, only in a code path that
  apparently wasn't run on the live DB (staff_contracts has 0 rows).
- The live DB was populated by `scripts/seed_world_phase2.py`, which
  INSERTs staff rows directly into `staff` without creating
  `staff_contracts` rows.
- The `finance.py._process_event_finance` function estimates staff
  salaries as `$2K × staff_count` per event (line 186-189) — it
  does NOT read `staff_contracts.salary`. So the absence of
  staff_contracts rows is not breaking finance; it just means staff
  salaries are not individually tracked.

**The arch doc's claim that "staff don't have explicit salary rows
in the current schema; this is an approximation" (§3.6) is
inaccurate.** The schema SUPPORTS staff salaries via the polymorphic
`contracts` + `staff_contracts` tables. The CODE just doesn't write
them. Wiring this up is a one-time backfill + a small change to
`finance.py` to read `staff_contracts.salary` instead of using the
flat $2K estimate.

### 3.6 Staff system status — does it support hiring / firing?

| Capability | Status |
|---|---|
| Hire (assign staff to a promotion) | **Schema supports** — `INSERT INTO staff (..., promotion_id=X, ...)` or `UPDATE staff SET promotion_id=X WHERE staff_id=Y`. The seed already does this. **No rival-AI code calls it.** |
| Fire (remove staff from a promotion) | **Schema supports** — `UPDATE staff SET promotion_id=NULL WHERE staff_id=Y`. **No code calls it.** |
| Staff performance tracking | **PARTIAL** — scouts have `current_assignment` + `assignment_start_date` in their specialty JSON (tracks who they're scouting + since when). Commentators have no performance metric. Doctors/cutmen/GMs have no performance metric. The `scouting_reports` table (0 rows) would be the data source for scout performance. |
| Staff roles (coach, scout, commentator, doctor, cutman, GM) | **YES** — 6 role types, all populated. Matches the arch doc's 5 managed roles + coaches. |
| Staff salaries (in staff_contracts) | **Schema supports; data is missing.** `staff_contracts` has 0 rows. Salaries are estimated as $2K/event in `finance.py`. |

**Bottom line:** the staff system is 70% built. The schema, role
taxonomy, and seeded data are all in place. What's missing is
**(a) rival-AI management logic** (hire/fire decisions) and
**(b) data hygiene** (backfill 300 coaches' gym_id; optionally
backfill staff_contracts for salary tracking). Neither requires
a schema change.

---

## Part 4: The "Already Designed" Gap Analysis

For each arch doc proposal, classified by status:

### 4.1 Already exists + fully functional — DON'T REBUILD, just wire

| Proposal | Existing system | Action |
|---|---|---|
| Event scheduling (§3.1) | `schedule_next_event()` in `services/matchmaking.py` — already called by rival AI weekly | Add: archetype-based cadence, `ai_scheduling_day_of_week` round-robin, budget gate, rival collision avoidance. Wrap, don't rebuild. |
| Matchmaking card builder (§3.2) | `_build_main_event`, `_build_co_main`, `_build_featured_prelim`, `_build_prelim` — all in `services/matchmaking.py` | Add: separate `services/rival_ai/matchmaker.py` wrapper that injects bias + imperfection. The existing functions stay unchanged. |
| Free agent signing (§3.3 step 5) | `sign_free_agent()` in `services/contracts.py` — already called by rival AI | Add: bidding war resolution layer that COLLECTS intents then CALLS `sign_free_agent` for the winner. The function itself stays unchanged. |
| Hard "no tapping up" rule (§5.1) | Already enforced — `sign_free_agent()` refuses already-signed fighters (line 211-214); SQL filter in `_maybe_sign_free_agent` (line 498) is `WHERE current_promotion_id IS NULL` | No action — already compliant. |
| Event bus publication of rival fight events | `resolve_next_fight()` publishes FIGHT_RESOLVED + EVENT_COMPLETED for all fights including rival — news, social, morale, punditry, finance, reputation, show_rating, venues, rivalries all fire | No action — already wired. |
| Training camps for rival fights | `_create_training_camp()` called by `schedule_next_event` for every booked fighter — fires for rival AI events too (176 camps, 116 active) | No action. |
| Rankings + titles updates | `_update_rankings_after_resolution` + `_resolve_title_after_fight` fire for all fights | No action. |
| Fighter regen on retirement | `generate_fighter()` produces a replacement when a rival fighter retires (8 regen_lineage rows confirm) | No action. |

### 4.2 Already exists but incomplete — EXTEND, don't rebuild

| Proposal | Existing system | Gap to fill |
|---|---|---|
| Staff hiring/firing (§3.5) | `staff` table + `promotion_id` column + 75 seeded promo-bound staff | Add: rival-AI logic in `services/rival_ai/staff_manager.py` that calls `UPDATE staff SET promotion_id=NULL` (fire) or `INSERT INTO staff (...)` (hire). Backfill 300 coaches' `gym_id`. Optionally wire `staff_contracts` for salary tracking. |
| Budget management (§3.6) | `finance.py._process_event_finance` records per-event P&L + updates `promotions.current_cash` | Add: `services/rival_ai/budget_manager.py` with monthly review + SURVIVAL/CONSERVATIVE/NORMAL/EXPANSION state machine + `promotions.ai_budget_state` column (new migration) + crisis handling. The event-P&L layer stays unchanged. |
| Matchmaking imperfection (§3.2 + §6.4) | Existing card builder produces optimal matchups | Add: biased matchup scoring function + imperfection injector (head-scratcher path) in `services/rival_ai/matchmaker.py`. The existing optimal builder stays as the "safe path" fallback. |
| Performance caching (§4.4) | `interpretation/snapshot_cache.py` runs daily pass + single-fighter refresh | Add: per-(promotion_id, date) roster cache for `_get_available_fighters_for_card`. Invalidation hooks on FIGHT_RESOLVED / FIGHTER_SIGNED / INJURY_CREATED / INJURY_RECOVERED. The existing snapshot cache stays unchanged. |
| Staff salary tracking | `staff_contracts` table + `_seed_default_staff_contract()` function exist but unused | Backfill: create `staff_contracts` rows for the 75 promo-bound staff (one-time migration). Update `finance.py` to read `staff_contracts.salary` instead of the flat $2K estimate. |

### 4.3 Already exists but unused — WIRE IT UP, don't rebuild

| Proposal | Existing system | Wiring needed |
|---|---|---|
| Scouting for rival AI | `scouting.py.assign_scout()` + `generate_scouting_report()` + `scouting_reports` table (0 rows) + 20 seeded scouts with rich specialty JSON | The arch doc does NOT propose wiring rival AI to scouting. But: the infrastructure is there if a future task wants AI scouts to produce reports. The arch doc's `staff_manager.py` DOES propose counting scout reports as a performance metric — that would automatically start populating `scouting_reports` IF the rival AI also calls `assign_scout()`. **Recommendation: extend arch doc to wire this.** |
| Agent offers for rival AI | `agent_offers.py` + `agent_offers` table (0 rows) + 5 offer types + `resolve_offer()` UI hook | The arch doc does NOT propose wiring rival AI to agent_offers. The table is player-only by design. **Recommendation: leave as player-only.** |
| Hall of Fame | `services/hof_svc.py` + `hall_of_fame` table (0 rows) + eligibility logic | Already wired passively — fires on FIGHTER_RETIRED for any fighter. **0 rows because no eligible fighter has retired since v3.x wiring.** Will populate naturally as the sim progresses. |
| Broadcast contracts | `broadcast_contracts` table (0 rows) + `broadcast_staff` table (0 rows) | Schema exists for tracking broadcast-network deals for commentators. Currently unused. The arch doc does not propose wiring this. **Recommendation: defer.** |
| `staff_contracts` polymorphic pattern | Schema + `_seed_default_staff_contract()` function exist | See §4.2 above — backfill + finance.py update. |

### 4.4 Truly new — MUST BUILD

| Proposal | Status | Build target |
|---|---|---|
| 4-archetype system (Major League, Regional Power, Grassroots, Rising Star) | **Genuinely new.** No existing concept of promotion archetypes (the 7 `style_archetypes` are FIGHTER styles, different concept). | `services/rival_ai/archetypes.py` + `promotions.ai_archetype` column (new migration v3.14.0) + `assign_archetype()` + quarterly re-eval. |
| `promotions.ai_scheduling_day_of_week` column | **Genuinely new.** No existing concept of per-promo scheduling day. | New migration v3.14.0 + backfill (assign days 1-7 round-robin across 9 rival promos). |
| `promotions.ai_budget_state` column | **Genuinely new.** No existing budget-state tracking. | New migration v3.14.0 + backfill (all promos start at 'normal'). |
| `PROMOTION_RECLASSIFIED` event bus type | **Genuinely new.** 16 existing event types do not include this. | Add to `event_bus.Events` class (one-line addition). |
| Fighter cutting (§3.4) | **Genuinely new.** No code cuts fighters from rosters (only contract expiry removes them). | `services/rival_ai/cutting_agent.py` with cut_risk scoring + protective rules + archetype aggressiveness + news items. |
| Bidding wars (§3.3 step 4 + §5.3) | **Genuinely new.** Current AI picks an independent random FA per promo — no multi-promo competition. | `services/rival_ai/signing_agent.py` with offer_score formula + winner selection + bid_premium_pct + loser news items. |
| Tapping-up rumors (§5.2) | **Genuinely new.** No contract-expiry interest system exists. | Add to `signing_agent.py` — query fighters with `end_date <= +30 days`, compute interest_score, write rumor news items. |
| Recency bias (§6.2) | **Genuinely new.** No show-rating-driven behavior modifier exists. | Add to `services/rival_ai/imperfection.py` — read `show_ratings` after events, apply archetype constant modifiers for 14 sim-days. |
| Whimsy layer (§6.6) | **Genuinely new.** No random non-optimal decision path exists. | Add to `services/rival_ai/imperfection.py` — `rng.random() < whimsy_pct` gate at start of each decision function. |

---

## Part 5: Revised Implementation Recommendation

Based on the audit, the implementation task should be reframed.

### 5.1 What we DON'T need to build (already exists + functional)

The rival AI just needs to CALL these existing systems:

1. **Event scheduling** — `schedule_next_event()` already works for
   rival promos. The arch doc's `event_scheduler.py` should be a
   thin wrapper that picks the event_date + calls the existing
   function (not a re-implementation).
2. **Matchmaking card builder** — `_build_main_event` etc. already
   produce cards. The arch doc's `matchmaker.py` should wrap these
   with a bias injector (not replace them).
3. **Free agent signing** — `sign_free_agent()` already works. The
   arch doc's `signing_agent.py` should collect intents + resolve
   bidding wars + call `sign_free_agent` for the winner.
4. **Event bus publication** — all 16 event types fire for rival
   fights already. The arch doc's `PROMOTION_RECLASSIFIED` is the
   only new event type needed.
5. **News engine + social + morale + punditry + rivalries + finance
   + reputation + show_rating + venues + suspensions + career_arc
   + HoF + retirement + regen + injury recovery + training camps
   + contract expiry** — all 17 of these systems fire for rival
   activity via the existing event bus. **No wiring needed.**

### 5.2 What we DO need to build (truly new)

This is a MUCH shorter list than the arch doc's 8-system proposal:

1. **`services/rival_ai/archetypes.py`** — the 4-archetype dict +
   `assign_archetype()` + `assign_scheduling_day()` + quarterly
   re-eval. ~150 lines.
2. **`services/rival_ai/cutting_agent.py`** — cut_risk scoring +
   protective rules + archetype aggressiveness + news items. ~250
   lines.
3. **`services/rival_ai/budget_manager.py`** — monthly review +
   SURVIVAL/CONSERVATIVE/NORMAL/EXPANSION/CRISIS state machine +
   crisis handling. ~300 lines. (The event-P&L layer is reused
   unchanged.)
4. **Bidding war resolution** (inside `signing_agent.py`) —
   offer_score formula + winner selection + bid_premium_pct + loser
   news items. ~150 lines. (Calls existing `sign_free_agent`.)
5. **Tapping-up rumor path** (inside `signing_agent.py`) —
   contract-expiry interest + rumor news items. ~80 lines.
6. **Imperfection module** (`services/rival_ai/imperfection.py`) —
   recency bias + whimsy + loyalty helpers. ~200 lines.
7. **Schema bump v3.14.0** — 3 new columns on `promotions`
   (`ai_archetype`, `ai_scheduling_day_of_week`, `ai_budget_state`)
   + 1 new event type (`PROMOTION_RECLASSIFIED`).
8. **Rival AI matchmaker wrapper** (`services/rival_ai/matchmaker.py`)
   — biased matchup scoring + imperfection injector. ~300 lines.
   (Calls existing `_build_main_event` etc. for the "safe path".)
9. **Rival AI event scheduler wrapper**
   (`services/rival_ai/event_scheduler.py`) — archetype-based
   cadence + budget gate + rival collision avoidance. ~200 lines.
   (Calls existing `schedule_next_event` for the actual insert.)

**Total truly new code: ~1,630 lines across 7 modules.** This
matches the arch doc's estimate of "~1,800-2,200 lines" (§1.4) —
the doc was accurate about volume.

### 5.3 What we need to WIRE (exists but not connected to rival AI)

1. **Staff hiring/firing** — `staff` table + `promotion_id` column
   exist. The rival AI's `staff_manager.py` calls
   `UPDATE staff SET promotion_id=NULL` (fire) or
   `INSERT INTO staff (...)` (hire). No new table, no schema change.
2. **`_insert_event_and_card` helper extraction** — the arch doc
   proposes extracting this from `schedule_next_event` (lines
   ~1300-1490 of `services/matchmaking.py`) into a shared helper
   that both the player's `schedule_next_event` and the rival AI's
   `event_scheduler.py` can call. This is a refactor, not a rebuild.
3. **Roster cache** — the arch doc proposes a per-(promotion_id,
   date) cache for `_get_available_fighters_for_card`. This sits
   alongside the existing `interpretation/snapshot_cache.py` (which
   is per-fighter). The cache invalidates on FIGHT_RESOLVED /
   FIGHTER_SIGNED / INJURY_CREATED / INJURY_RECOVERED.
4. **`promotions.ai_budget_state` reads** — once the column exists,
   the rival AI's `event_scheduler.py`, `signing_agent.py`,
   `cutting_agent.py`, `staff_manager.py` all read it to apply
   state-driven modifiers.

### 5.4 What we need to EXTEND (exists but incomplete)

1. **Staff salary tracking** — backfill `staff_contracts` for the
   75 promo-bound staff (one-time migration). Update `finance.py`
   to read `staff_contracts.salary` instead of the flat $2K
   estimate. ~30 lines of code change.
2. **Coach-gym linkage** — backfill the 300 coaches' `gym_id`
   (one-time migration). Match by nation_id or sequentially. ~20
   lines of migration code.
3. **`schedule_next_event` extraction** — pull the INSERT logic
   into `_insert_event_and_card` so the rival AI's
   `event_scheduler.py` can call it directly without going through
   the player-facing `schedule_next_event` wrapper. ~80 lines of
   refactor (no behaviour change).
4. **Show-rating reads for recency bias** — the rival AI's
   `imperfection.py` reads `show_ratings` after events to apply
   archetype constant modifiers. The `show_ratings` table + the
   `show_rating.py` subscriber already exist; this is just a new
   reader.

---

## Part 6: The "Reinventing" Risk Assessment

The arch doc is, on the whole, **careful about not reinventing**.
Its §0 executive summary explicitly states: *"Everything else
(events, fights, contracts, staff, finance_transactions tables) is
reused unchanged."* The risks below are places where the doc's
claims are INACCURATE, which could lead an implementation agent
astray.

### 6.1 Risk matrix

| Arch doc claim | Reality | Risk of reinventing | Mitigation |
|---|---|---|---|
| "the live DB has 300 coaches, all linked to `gym_id` (not `promotion_id`)" (§3.5) | **FALSE.** All 300 coaches have BOTH `gym_id IS NULL` AND `promotion_id IS NULL` — they're orphan staff. | An implementer might build a "new" coach-gym linkage system instead of just backfilling the existing column. | Reframe: "300 coaches exist as staff rows; their `gym_id` column (added v3.9.0) needs backfill." |
| "AI never touches the staff table" (Appendix A) | **Technically true** (rival_ai.py doesn't write to `staff`), but misleading. The staff table is FULLY POPULATED (375 rows, every promo has 7-8 staff). The arch doc's `staff_manager.py` would be the FIRST writer — but it's adding logic, not building the system. | An implementer might think they need to design the staff system from scratch. | Reframe: "The staff system EXISTS; the rival AI's `staff_manager.py` adds hire/fire LOGIC to the existing system." |
| "staff don't have explicit salary rows in the current schema; this is an approximation" (§3.6) | **INACCURATE.** The schema SUPPORTS staff salaries via the polymorphic `contracts` + `staff_contracts` tables. The CODE just doesn't write them. | An implementer might add a new `staff_salaries` table instead of using the existing `staff_contracts` pattern. | Reframe: "The `staff_contracts` polymorphic pattern exists but is unused (0 rows). Backfill it for salary tracking." |
| "No budget management" (Appendix A) | **PARTIALLY TRUE.** Event-P&L management EXISTS (`finance.py`). Strategic budget management (state machine, crisis) does NOT. | An implementer might rebuild the event-P&L layer instead of extending it. | Reframe: "Event-P&L exists; strategic budget management is genuinely new." |
| "Signings are random within a potential floor. No budget management." (Appendix A) | **Accurate for the strategic layer.** The signing mechanism (`sign_free_agent`) works; the strategy (bidding wars, offer_score) does not. | Low risk — the arch doc correctly identifies `sign_free_agent` as reusable. | None needed. |
| "The AI uses the player's optimal card builder — produces *flawless* main events" (Appendix A) | **Accurate.** `_build_main_event` does pick champ vs #1 / vacant #1 vs #2 / fallback top-2 — optimal by design. | Low risk — the arch doc correctly proposes a wrapper, not a replacement. | None needed. |
| "10% free-agent-signing chance per week per rival promotion" (Appendix A) | **Accurate.** `rival_ai.py` line 166: `FREE_AGENT_SIGN_CHANCE = 0.10`. | Low risk. | None needed. |
| Proposed `services/rival_ai/` package (§7.1) | **Right shape.** The 7-module package is appropriate for the 6 decision types + imperfection. | Low risk — the doc explicitly says "extract decision logic" not "rebuild". | None needed. |
| Proposed `_insert_event_and_card` helper extraction (§3.1 step 5) | **Right approach.** Pulling the INSERT logic out of `schedule_next_event` is a clean refactor. | Low risk. | None needed. |
| Proposed `promotions.ai_archetype` + `ai_scheduling_day_of_week` + `ai_budget_state` columns (§7.2) | **Genuinely missing.** These 3 columns don't exist. | Low risk — the doc correctly identifies them as new. | None needed. |
| Proposed `PROMOTION_RECLASSIFIED` event type (§7.3) | **Genuinely missing.** 16 existing event types; this would be #17. | Low risk. | None needed. |

### 6.2 What would happen if we built "new" systems alongside existing ones?

| Reinventing risk | Consequence if it happened |
|---|---|
| Building a new `staff_salaries` table instead of using `staff_contracts` | Data inconsistency: two salary sources. `finance.py` already uses `staff_contracts` (via the polymorphic `contracts` JOIN in `get_contracts_for_display`). A parallel table would break that JOIN. |
| Building a new `rival_events` table instead of using `events` | Catastrophic — the entire event bus + 17 subscriber systems would not fire for rival events. The "living world" effect would be lost. |
| Building a new `rival_fights` table instead of using `fights` | Same as above — `fight_history`, `rankings`, `titles`, `rivalries`, `matchup_analyses`, `commentary_segments`, `fight_beats`, `fight_rounds`, `fight_participants`, `event_cards` all JOIN to `fights`. A parallel table would orphan all of these. |
| Building a new `ai_budget` table instead of using `promotions.current_cash` + `finance_transactions` | Double-counting: the existing `finance.py` already updates `promotions.current_cash` on every event. A parallel budget table would diverge. |
| Building a new `rival_signings` log instead of using `contracts` + `fighter_contracts` | The existing `sign_free_agent` writes to `contracts` + `fighter_contracts` + publishes `FIGHTER_SIGNED`. A parallel log would miss the event bus publication. |
| Building a new matchmaker instead of wrapping `_build_main_event` | The existing builder has 4 specialized functions (main / co-main / featured_prelim / prelim) with same-gender checks, rest-day enforcement, injury/suspension exclusion. Re-implementing these would risk regressions. |

### 6.3 Where the arch doc is RIGHT about reuse

The arch doc explicitly says (and the audit confirms):

- ✅ "Everything else (events, fights, contracts, staff,
  finance_transactions tables) is reused unchanged." (§0)
- ✅ "Both call the same shared `_insert_event_and_card` helper for
  DB writes — no duplication of the INSERT logic." (§3.2)
- ✅ "Call `sign_free_agent(conn, fighter_id, promotion_id,
  start_date, salary=bid_salary)` (existing function in
  `services/contracts.py`)." (§3.3 step 5)
- ✅ "Call the rival matchmaker (§3.2) which returns a list of 5-13
  fight dicts. The matchmaker reuses the card-slot structure from
  the player's matchmaking code." (§3.1 step 4)
- ✅ "Call `_create_training_camp` per booked fighter (existing
  function in `services/matchmaking.py`)." (§3.1 step 5)
- ✅ "The AI uses the SAME schedule_next_event + resolve_next_fight
  + sign_free_agent functions the player uses." (rival_ai.py
  docstring)

The audit confirms all of these. The arch doc is **not** proposing
to reinvent — it's proposing to wrap + extend. The user's concern
is valid as a RISK to guard against, but the doc itself is sound.

---

## Part 7: Worklog

```
---
Task ID: EXISTING-SYSTEMS-AUDIT
Agent: DB + Systems Auditor (general-purpose)
Task: Audit existing DB schema + codebase to prevent reinventing
      systems. Compare RIVAL_AI_ARCHITECTURE.md proposals against
      what already exists.

Work Log:
- 58 tables audited (full schema + row counts + column inventory)
- 27 source modules audited (rival_ai, matchmaking, contracts,
  finance, training_svc, scouting_svc, rivalries_svc, hof_svc,
  retirement_svc, injuries_svc, agent_offers, career_arc,
  reputation, morale, show_rating, venues, punditry, suspensions,
  tick_processor, news, social, voice, event_bus, snapshot_cache,
  build_db, seed_data, seed_world_phase2)
- 5 systems that already exist + are wired to rival AI passively
  (event bus fires for rival fights → news, social, morale,
  punditry, rivalries, finance event-P&L, reputation, show_rating,
  venues, suspensions, career_arc, HoF, retirement, regen,
  injuries, training camps, contract expiry, rankings, titles)
- 3 systems that already exist + are actively called by rival AI
  (schedule_next_event, sign_free_agent, resolve_next_fight via
  the daily single-night resolution loop)
- 3 systems that exist but are unused (agent_offers, scouting
  reports, hall_of_fame — all 0 rows)
- 3 systems that are genuinely new (4-archetype system, fighter
  cutting, bidding wars)
- 5 reinventing risks identified (most are documentation
  inaccuracies in the arch doc, not design flaws)

Stage Summary:
- Audit doc: /home/z/my-project/cage_empire/docs/EXISTING_SYSTEMS_AUDIT.md
- Top 3 "already exists, don't rebuild" findings:
  1. Event scheduling + matchmaking card builder + free agent
     signing — all 3 are functional and already called by rival
     AI. Wrap, don't rebuild.
  2. Event bus + 17 subscriber systems (news, social, morale,
     punditry, rivalries, finance event-P&L, reputation,
     show_rating, venues, suspensions, career_arc, HoF,
     retirement, regen, injuries, training camps, contract
     expiry) — all fire for rival fights automatically.
  3. Staff table + role taxonomy + 75 seeded promo-bound staff —
     the system exists; only the rival-AI management logic is
     missing.
- Top 3 "truly new, must build" findings:
  1. The 4-archetype system (Major League, Regional Power,
     Grassroots, Rising Star) — genuinely new concept, requires
     `promotions.ai_archetype` column + ARCHETYPES dict +
     assign_archetype() + quarterly re-eval.
  2. Fighter cutting — no code currently cuts fighters from
     rosters (only contract expiry removes them). Requires
     cut_risk scoring + protective rules + archetype
     aggressiveness.
  3. Bidding wars — current AI picks an independent random FA per
     promo. Requires multi-promo offer collection + offer_score
     formula + winner selection + bid_premium_pct + loser news.
- Revised implementation recommendation:
  - WIRE: 4 systems (staff hire/fire, _insert_event_and_card
    helper extraction, roster cache, ai_budget_state reads)
  - EXTEND: 4 systems (staff salary tracking, coach-gym backfill,
    schedule_next_event extraction, show-rating reads for
    recency bias)
  - BUILD: 9 genuinely-new items (archetypes module, cutting
    agent, budget manager, bidding war resolution, tapping-up
    rumors, imperfection module, schema bump v3.14.0, rival
    matchmaker wrapper, rival event scheduler wrapper)
  - Total truly-new code: ~1,630 lines across 7 modules (matches
    arch doc's ~1,800-2,200 line estimate)
- The single most important thing the supervisor should know
  before proceeding: **The arch doc is sound — it correctly
  identifies what to reuse vs. what to build. The user's concern
  about "reinventing" is a valid RISK to guard against, but the
  doc itself does not propose reinventing. The 3 documentation
  inaccuracies (coach-gym linkage, staff_contracts existence,
  budget management framing) should be corrected in the arch
  doc before implementation begins, so the implementer doesn't
  accidentally rebuild existing infrastructure.**
---
```

## Appendix A — Live DB Snapshots (for reference)

### A.1 Promotions table (full dump)

```
id  name                                tier    cash          rep  aggr  spend         bcast          own
1   Alpha Combat Federation             major   $50,000,000   85   30    balanced      ppv_global     private
2   Rival Fight League                  mid     $15,000,000   65   50    aggressive    streaming      private
3   Pacific Rim Championship            mid     $12,000,000   60   45    balanced      tv_regional    private
4   European Fight Network              mid     $10,000,000   62   40    conservative  streaming      private
5   South American Warriors             small   $3,000,000    45   60    aggressive    local_stream   private
6   Mexican Boxing & Brawl              small   $6,644,140    46   65    aggressive    local_stream   private
7   Nordic Fight Nights                 small   $2,500,000    42   35    conservative  local_stream   private
8   Eastern Bloc Combat                 small   $4,000,000    48   55    aggressive    tv_regional    private
9   Australian Outback Fights           small   $2,000,000    38   50    balanced      local_stream   private
10  French Savate Championship          small   $1,800,000    35   30    conservative  local_stream   private
```

### A.2 Recent rival-AI scheduled events (proof the existing system works)

```
id    promo                             event_date  status      fights
1959  Rival Fight League                2026-08-23  scheduled   9
1960  Pacific Rim Championship          2026-08-23  scheduled   9
1961  European Fight Network            2026-08-23  scheduled   9
1962  South American Warriors           2026-08-23  scheduled   6
1964  Nordic Fight Nights               2026-08-23  scheduled   6
1965  Eastern Bloc Combat               2026-08-23  scheduled   5
1966  Australian Outback Fights         2026-08-23  scheduled   5
1967  French Savate Championship        2026-09-06  scheduled   6
```

### A.3 Recent rival-AI signings (proof `sign_free_agent` is being called)

```
contract_id  promotion                       start_date  end_date    salary
977          French Savate Championship       2026-07-20  2027-07-20  $15,000
978          French Savate Championship       2026-07-20  2027-07-20  $15,000
979          French Savate Championship       2026-07-20  2027-07-20  $15,000
980          French Savate Championship       2026-07-20  2027-07-20  $15,000
981          French Savate Championship       2026-07-20  2027-07-20  $15,000
982          Rival Fight League               2026-07-26  2027-07-26  $50,000
983          Australian Outback Fights       2026-07-26  2027-07-26  $50,000
984          South American Warriors         2026-08-09  2027-08-09  $50,000
985          Rival Fight League               2026-08-16  2027-08-16  $50,000
986          French Savate Championship       2026-08-16  2027-08-16  $50,000
```

### A.4 Schema migrations applied (22 total)

```
v2_2_0_add_fighter_depth             v3_0_0_add_finance_transactions
v2_3_0_add_beat_engine_depth         v3_1_0_add_social_posts
v2_4_0_add_injuries                  v3_2_0_add_rivalries
v2_5_0_add_training_camps            v3_3_0_add_matchup_analyses
v2_6_0_world_seed_prep               v3_4_0_add_suspensions
v2_7_0_add_weight_cut_log            v3_5_0_add_agent_offers
v2_8_0_add_fighter_descriptors       v3_6_0_add_show_ratings
v2_9_0_add_scouting_reports          v3_7_0_add_player_settings
                                     v3_8_0_add_staff_pundit_bias
                                     v3_9_0_add_staff_gym_id
                                     v3_10_0_extend_fighter_descriptors
                                     v3_11_0_add_cache_tables
                                     v3_12_0_expand_memory_link_types
                                     v3_13_0_add_performance_indexes
```

### A.5 Event bus types (16 existing — `PROMOTION_RECLASSIFIED` would be #17)

```
FIGHT_RESOLVED          FIGHTER_RETIRED         CONTRACT_EXPIRED
FIGHT_CANCELLED         FIGHTER_SIGNED          CAMP_COMPLETED
TITLE_CHANGED           FIGHTER_GENERATED       CAMP_INJURY
EVENT_COMPLETED                                 INJURY_CREATED
                                                INJURY_RECOVERED
                                                WEIGHT_CUT_COMPLETED
                                                SCOUT_REPORT_GENERATED
                                                FIGHTER_STATE_CHANGED
                                                TICK_ADVANCED
```

---

## End of Document

**Next action for the supervisor:**
1. Approve the 3-column schema bump (`promotions.ai_archetype` +
   `ai_scheduling_day_of_week` + `ai_budget_state`) as migration
   v3.14.0.
2. Approve the `PROMOTION_RECLASSIFIED` event type addition.
3. Correct the 3 documentation inaccuracies in
   `RIVAL_AI_ARCHITECTURE.md` (§3.5 coach-gym linkage, §3.6
   staff_contracts existence, Appendix A "AI never touches the
   staff table" framing).
4. Approve a one-time backfill migration for the 300 orphan
   coaches' `gym_id` column.
5. Greenlight the implementation task against the arch doc, with
   the explicit constraint: **wire + extend + build only what's
   listed in Part 5 above; do not rebuild existing infrastructure.**

**Audit complete.**
