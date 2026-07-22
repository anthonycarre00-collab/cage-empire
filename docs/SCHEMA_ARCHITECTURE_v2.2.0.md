# CAGE EMPIRE — Schema & Architecture Reference (v2.2.0)

> **Status:** Living document. Updated on every schema change.
> **Current version:** 2.2.0 (38 tables, 389 columns, 16 acceptance tests, 970+ sub-checks)
> **Last revised:** 2026-07-21 — pre-B2-fix (fight importance columns)

This document is the complete reference for every table, column, module,
function, and data flow in the CAGE EMPIRE build. It is the single source
of truth for "what exists right now."

---

## 1. Architecture Overview

### Source modules

| Module | Purpose | Lines (approx) |
|---|---|---|
| `src/build_db.py` | Schema definition + version gate + DB rebuild | ~700 |
| `src/seed_data.py` | Minimal playable world seed (5 fighters, 2 promotions, 1 event, 1 title fight) | ~700 |
| `src/tick_processor.py` | Clock advance + retirement checks + contract expiry checks | ~560 |
| `src/app.py` | Fight engine (beat-level) + all side effects + UI (Tkinter) + display helpers + fighter generation | ~2800 |
| `src/fighter_gen.py` | Fighter generation functions (attributes, personality, physical, potential) | ~400 |

### Data flow

```
Player clicks "Advance Day"
    → tick_processor.run_tick()
        → advance simulation_clock by 1 day
        → _check_retirements(conn, current_date)
            → retire eligible fighters (age ≥45 OR age ≥40 AND career_health <60)
            → vacate titles for retiring champions (_vacate_title_on_retirement)
            → generate replacement fighter (generate_fighter from app.py)
            → create regen_lineage row
            → create fighter_memory_links row (champions only)
            → write retirement + prospect news items
        → _check_contract_expiry(conn, current_date)
            → expire contracts past end_date
            → set current_promotion_id=NULL for non-retired fighters (free agents)
            → write free-agency news items

Player clicks "Resolve Fight"
    → app.resolve_next_fight(conn)
        → pick next unresolved fight (winner IS NULL AND result_type IS NULL)
        → load both fighters' 25 attributes + 20 personality fields
        → for each round 1..scheduled_rounds:
            → resolve_round()
                → compute beat count (12-28, based on pace formula)
                → for each beat:
                    → determine initiator (alternating / aggression-weighted)
                    → determine action_type (based on current phase)
                    → compute attack score (phase-specific attrs + noise)
                    → compute defense score (phase-specific attrs + noise)
                    → determine outcome (landed/missed/blocked/defended/reversed)
                    → compute damage, control_time, momentum_shift
                    → check phase transitions (takedown → ground, etc.)
                    → INSERT into fight_beats
                → populate fight_rounds as SUM aggregates over fight_beats
                → determine round winner (10-point must)
        → _decide_fight_outcome() — unanimous_decision / split_decision / draw
        → UPDATE fights SET winner, loser, result_type, finish_round, finish_time
        → UPDATE fight_participants SET is_winner
        → UPDATE fighter_career (record_wins/losses/draws, streaks)
        → INSERT fight_history (2 rows, one per fighter, title_at_stake from is_title_fight)
        → _update_rankings_after_resolution() (ELO K=32, zero-sum)
        → _resolve_title_after_fight() (if is_title_fight=1: transfer/vacate belt)
        → _format_fight_news() + write_news()
        → _format_fight_commentary() + write_commentary()
        → _update_event_status_after_resolution() (scheduled→in_progress→completed)
        → if event just completed: schedule_next_event() (auto-schedule ~4 weeks out)
```

### UI structure (Tkinter)

```
App (tk.Tk) — 1280x760 window
├── Top bar
│   ├── "Advance Day" button → on_advance_day()
│   ├── "Resolve Fight" button → on_resolve_fight()
│   ├── "Refresh" button → refresh_all()
│   ├── "Filter:" label + Combobox (All Promotions / Alpha Combat / Rival Fight League)
│   └── Clock label (date | day | week | month | year | ticks)
├── Left pane — Fighters Treeview
│   └── Columns: name, weight_class, promotion, record (W-L-D)
├── Center pane
│   ├── Events Treeview (date, name, status)
│   └── Fights Treeview (id, matchup, weight_class, result)
└── Right pane — ttk.Notebook (4 tabs)
    ├── "News & Commentary" tab
    │   ├── News Listbox (last 10 headlines)
    │   └── Commentary Listbox (last 10 commentary lines)
    ├── "Contracts" tab
    │   └── Treeview: contractor, type, start, end, salary, exclusive, status
    ├── "Rankings" tab
    │   └── Treeview: rank, fighter, weight_class, rating, fights, record, last_fight
    └── "Free Agents" tab
        ├── "Sign Selected" button → on_sign_free_agent()
        └── Treeview: name, weight_class, record, age (fighter_id as iid)
```

### Acceptance test suite (16 tests, 970+ sub-checks)

| Test | Task | Sub-checks | What it verifies |
|---|---|---|---|
| test_schema_versioning | 5 | 7 | Version gate: refuse newer, allow upgrade, same-version rebuild, no schema_meta, corrupt DB, semver comparison |
| test_fight_resolver | 3 | 100 sims | All-90 beats all-30 ≥80%, B1 exemption for unanimous_decision |
| test_fight_history | 4 | 18 | 2 rows per fight, win/loss/draw outcomes, title_at_stake, career counter match |
| test_promotion_filter | 6 | 5+1SKIP | Filter by promotion, invalid promo, free agent display |
| test_event_lifecycle | 7 | 31 | scheduled→in_progress→completed, defensive clause, multi-fight |
| test_event_scheduler | 8 | 60 | Auto-schedule next event, no infinite loop, 3+ cycle dates |
| test_contracts | 9 | 39+1SKIP | 4 contract tables, seed defaults, polymorphic JOIN, UI smoke |
| test_rankings | 10 | 43+1SKIP | ELO zero-sum, upset math, draw handling, display helper |
| test_titles | 11 | 55 | 5-case title resolution, vacation on retirement, title_reigns counter |
| test_retirement | 12 | 44 | Age rules, title vacation, news, matchup exclusion, multi-retirement |
| test_free_agency | 13 | 54+6SKIP | Contract expiry, sign_free_agent, free agents tab, retired-fighter edge |
| test_regen | 14 | 68 | Name uniqueness, style DNA, regen on retirement, lineage, prospect news |
| test_fighter_attributes | 14.5 | 259 | 25 attrs, 20 personality, archetype bias, backfill, current_date fix |
| test_pre_b1_fixes | pre-B1 | 85 | Potential distribution, softened biases, champion memory links |
| test_beat_engine | B1 | 59 | Beat count, 6 phases, transitions, aggregates, decision scoring, side effects |
| test_fight_importance | pre-B2 | 32 | card_slot, is_title_fight, is_co_main, code checks is_title_fight |

---

## 2. Complete Schema (38 tables, 389 columns)

### 2.1 Schema Meta & Versioning (2 tables)

#### schema_meta (3 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| schema_name | TEXT | PK | Always 'cage_empire' |
| schema_version | TEXT | NOT NULL | Current schema version (e.g. '2.2.0') |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | When this row was written |

#### schema_migrations (2 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| migration_name | TEXT | PK | e.g. 'v2_2_0_fight_importance_columns' |
| applied_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | When this migration was applied |

### 2.2 Simulation & Geography (7 tables)

#### simulation_clock (9 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| clock_id | INTEGER | PK CHECK (=1) | Singleton row |
| current_date | TEXT | NOT NULL | ISO date 'YYYY-MM-DD' (sim date, NOT real date) |
| current_day | INTEGER | NOT NULL | Day counter (1, 2, 3, ...) |
| current_week | INTEGER | NOT NULL | Week counter (derived from day) |
| current_month | INTEGER | NOT NULL | Month (1-12) |
| current_year | INTEGER | NOT NULL | Year (e.g. 2026) |
| current_tick_type | TEXT | NOT NULL DEFAULT 'day' | 'day' (only type currently) |
| tick_counter | INTEGER | NOT NULL DEFAULT 0 | Total ticks since start |
| updated_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | Last update timestamp |

#### nations (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| nation_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'Northland' |
| language | TEXT | | e.g. 'English' |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Note:** THIN — spec calls for combat_culture, market_maturity, travel_difficulty, regulatory_profile, talent_pool_strength, fan_style_preference. These will be added in Task 27.

#### regions (7 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| region_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'East Coast' |
| style_preferences | TEXT | | e.g. 'boxing, pressure' |
| fan_preferences | TEXT | | e.g. 'rivalries' |
| market_growth | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Market growth potential |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

#### weight_classes (6 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| weight_class_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'Lightweight' |
| min_weight_kg | REAL | | e.g. 65.8 |
| max_weight_kg | REAL | | e.g. 70.3 |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

#### cities (7 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| city_id | INTEGER | PK AUTOINCREMENT | |
| nation_id | INTEGER | FK → nations | |
| region_id | INTEGER | FK → regions | |
| name | TEXT | NOT NULL | e.g. 'Metro City' |
| population | INTEGER | | e.g. 2500000 |
| created_at / updated_at | TEXT | | Timestamps |

**Note:** THIN — spec calls for affluence, combat_sports_interest, media_reach, local_bias, venue_capacity_bias. Task 27.

#### markets (6 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| market_id | INTEGER | PK AUTOINCREMENT | |
| city_id | INTEGER | NOT NULL UNIQUE FK → cities | One market per city |
| market_type | TEXT | NOT NULL DEFAULT 'standard' | e.g. 'major' |
| heat_level | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Market interest level |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for fan_taste_profile, ticket_demand, local_star_bonus, touring_penalty. Task 27.

#### venues (6 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| venue_id | INTEGER | PK AUTOINCREMENT | |
| city_id | INTEGER | NOT NULL FK → cities | |
| name | TEXT | NOT NULL | e.g. 'Metro Arena' |
| capacity | INTEGER | NOT NULL CHECK (>0) | e.g. 18000 |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for prestige, cost, atmosphere, media_suitability, walkout_quality, lighting_quality. Task 27.

### 2.3 Promotions, Gyms, Archetypes (4 tables)

#### promotions (16 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| promotion_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'Alpha Combat' |
| size_tier | TEXT | NOT NULL DEFAULT 'small' | 'small'/'mid'/'major' |
| nation_id | INTEGER | FK → nations | |
| region_id | INTEGER | FK → regions | |
| current_cash | REAL | NOT NULL DEFAULT 0 | Available funds |
| reputation | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Promotion prestige |
| fan_trust | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Fan confidence in promotion |
| brand_tone | TEXT | NOT NULL DEFAULT 'standard' | Brand identity |
| starting_budget | REAL | NOT NULL DEFAULT 0 | Initial budget |
| broadcast_tier | TEXT | NOT NULL DEFAULT 'local_stream' | 'local_stream'/'regional_tv'/'national_tv'/'ppv' |
| ownership_type | TEXT | NOT NULL DEFAULT 'startup' | 'startup'/'takeover'/'corporate' |
| ai_aggression | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | AI aggressiveness for rival promotions (Task 25) |
| ai_spending_style | TEXT | NOT NULL DEFAULT 'balanced' | 'conservative'/'balanced'/'aggressive' |
| created_at / updated_at | TEXT | | |

#### gyms (15 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| gym_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'Ironhouse Gym' |
| city_id | INTEGER | NOT NULL FK → cities | |
| nation_id | INTEGER | FK → nations | |
| region_id | INTEGER | FK → regions | |
| reputation | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Gym prestige |
| membership_cost | REAL | NOT NULL DEFAULT 0 | Cost to train here |
| facility_quality | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Training facility quality |
| medical_support | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Medical/recovery support |
| sparring_depth | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Quality/variety of sparring partners |
| development_focus | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Coaching development quality |
| culture_tone | TEXT | NOT NULL DEFAULT 'balanced' | Gym culture |
| weight_cut_support | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Weight cut facilities (Task 17) |
| created_at / updated_at | TEXT | | |

#### style_archetypes (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| style_archetype_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'Brawler', 'Striker', 'Grappler' |
| description | TEXT | NOT NULL | Human-readable description |
| attribute_bias | TEXT | | JSON: {"punch_power": 10, "chin": 8, ...} — shifts attribute generation |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Seeded archetypes (7):** Balanced, Striker, Grappler, Wrestler, Brawler, Counter-Striker, Submission Specialist

#### personality_archetypes (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| personality_archetype_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'Calm', 'Aggressive' |
| description | TEXT | NOT NULL | |
| trait_bias | TEXT | | JSON: {"aggression": 10, "patience": -8, ...} |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Seeded archetypes (5):** Calm, Aggressive, Methodical, Showman, Quiet Professional

### 2.4 Fighters (5 tables)

#### fighters (33 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fighter_id | INTEGER | PK AUTOINCREMENT | |
| first_name | TEXT | NOT NULL | |
| last_name | TEXT | NOT NULL | |
| nickname | TEXT | | e.g. 'Hammer' |
| gender | TEXT | NOT NULL DEFAULT 'unknown' | 'male'/'female' |
| date_of_birth | TEXT | NOT NULL | ISO date 'YYYY-MM-DD' |
| birth_city_id | INTEGER | FK → cities | |
| birth_nation_id | INTEGER | FK → nations | |
| residence_city_id | INTEGER | FK → cities | |
| residence_nation_id | INTEGER | FK → nations | |
| weight_class_id | INTEGER | FK → weight_classes | |
| current_gym_id | INTEGER | FK → gyms | |
| current_promotion_id | INTEGER | FK → promotions | NULL = free agent |
| fight_style_archetype_id | INTEGER | FK → style_archetypes | Style DNA for regen |
| personality_archetype_id | INTEGER | FK → personality_archetypes | |
| is_active | INTEGER | NOT NULL DEFAULT 1 CHECK (0,1) | 0 = inactive (injured, etc.) |
| is_retired | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | 1 = retired |
| height_cm | INTEGER | | Physical height (165-195 typical) |
| reach_cm | INTEGER | | Wingspan (height ± 5-10cm) |
| stance | TEXT | CHECK IN ('orthodox','southpaw','switch') | Fighting stance |
| handedness | TEXT | CHECK IN ('right','left','ambidextrous') | Dominant hand |
| injury_proneness | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Likelihood of injury in fights (Task 15) |
| weight_cut_difficulty | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Difficulty of making weight (Task 17) |
| consistency | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Performs at expected level vs fluctuates |
| clutch_factor | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Rises to occasion in big fights / bottler |
| marketability | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Star power / fan appeal |
| fan_friendliness | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | How much fans like them |
| promo_boost | INTEGER | NOT NULL DEFAULT 0 CHECK (-100 to 100) | Temporary popularity boost |
| preferred_gameplans | TEXT | | JSON: gameplan tags |
| bad_matchup_tags | TEXT | | JSON: matchup weakness tags |
| is_deceased | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | Death flag (hardcore sim) |
| created_at / updated_at | TEXT | | |

#### fighter_attributes (30 columns = 25 attributes + id + fighter_id + 2 timestamps)

**Striking (5):**
| Column | Intended use |
|---|---|
| punch_power | KO probability on clean punches |
| punch_accuracy | Landed-vs-thrown ratio on punches |
| kick_power | KO/damage probability on clean kicks |
| kick_accuracy | Landed-vs-thrown ratio on kicks |
| head_movement | Evasion — reduces opponent's landed-strike rate |

**Range (4):**
| Column | Intended use |
|---|---|
| footwork | Ring generalship, distance/angle control |
| clinch_striking | Knees/elbows/dirty boxing in the clinch |
| clinch_offense | Takedown entries/throws from the clinch |
| clinch_defense | Stuffing clinch takedown entries |

**Grappling (8):**
| Column | Intended use |
|---|---|
| takedown_offense | Landing takedowns |
| takedown_defense | Stuffing takedowns (sprawl) |
| top_control | Maintaining dominant position on top |
| bottom_game | Offense/sweeps from the bottom (guard play) |
| submission_offense | Threatening/finishing submissions |
| submission_defense | Escaping/defending submission attempts |
| scramble_ability | Transitions — getting up, reversing |
| cage_wrestling | Pressing opponents against the cage, wall-walking |

**Physical (6):**
| Column | Intended use |
|---|---|
| cardio | Gas tank — output decay across rounds |
| chin | Head-trauma resistance, KO/rock resistance |
| recovery_rate | Between-round recovery, bounce-back after being hurt |
| speed_explosiveness | Reflexes, burst athleticism, reaction time |
| strength | Clinch/top-control retention, takedown power |
| durability | Resistance to cuts/joint damage/cumulative body wear (body, NOT head — that's chin) |
| flexibility | Submission escapes, kick range/height, guard retention |

**Mental (2):**
| Column | Intended use |
|---|---|
| fight_iq | Gameplan execution, in-fight problem-solving, ringcraft |
| adaptability | Capability to switch approach mid-fight when plan A stalls |

All attributes: INTEGER NOT NULL DEFAULT 50, newer ones have CHECK (0-100).
Original 4 (punch_power, cardio, fight_iq, chin) lack CHECK constraint (legacy).

#### fighter_personality (24 columns = 20 fields + id + fighter_id + 2 timestamps)

**Temperament (7 static):**
| Column | Intended use |
|---|---|
| aggression | Forward pressure, initiation rate |
| composure | Poise under pressure, resistance to panic when hurt |
| risk_taking | Willingness to attempt high-risk/high-reward techniques |
| killer_instinct | Urgency/effectiveness finishing a hurt opponent |
| grit | Fighting through adversity rather than folding |
| discipline | Sticking to the gameplan under fatigue/adversity |
| patience | Willingness to wait for openings vs forcing exchanges |

**Career (6 static):**
| Column | Intended use |
|---|---|
| ambition | Drive to seek ranked opponents/title shots |
| loyalty | Attachment to gym/promotion — affects free agency, poaching |
| charisma | Promo skill, fan connection — feeds marketability |
| attention_seeking | Trash talk / social media driver (Task 21) |
| coachability | Receptiveness to staff coaching — affects camp gains (Task 16) |
| professionalism | Weight-cut discipline, avoiding off-field incidents |

**Resilience (4 static):**
| Column | Intended use |
|---|---|
| ego | Willingness to take "beneath them" fights, respect for opponents |
| resilience | Mental bounce-back after a loss, post-loss dip magnitude/duration |
| sportsmanship | Post-fight conduct — de-escalates or escalates rivalries |
| travel_comfort | Performance impact fighting far from home region |

**Dynamic (3 — change over time):**
| Column | Intended use |
|---|---|
| morale | Short/medium-term emotional state — recent results, camp quality |
| focus | Current mental sharpness heading into camp/fight |
| fatigue_tolerance | Resistance to cumulative wear across camp/career (distinct from in-fight cardio) |

All personality fields: INTEGER NOT NULL DEFAULT 50, newer ones have CHECK (0-100).
Original 3 (aggression, composure, morale) lack CHECK constraint (legacy).

#### fighter_career (12 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fighter_career_id | INTEGER | PK AUTOINCREMENT | |
| fighter_id | INTEGER | NOT NULL UNIQUE FK → fighters | |
| record_wins | INTEGER | NOT NULL DEFAULT 0 | Career wins |
| record_losses | INTEGER | NOT NULL DEFAULT 0 | Career losses |
| record_draws | INTEGER | NOT NULL DEFAULT 0 | Career draws |
| win_streak | INTEGER | NOT NULL DEFAULT 0 | Current win streak |
| loss_streak | INTEGER | NOT NULL DEFAULT 0 | Current loss streak |
| career_health | INTEGER | NOT NULL DEFAULT 100 | Overall health (declines from injuries, affects retirement) |
| potential | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | Growth ceiling — training camps push attributes toward this |
| title_reigns | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | How many title reigns this fighter has had (for memory resurfacing) |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for current_ranking, title_defenses, legacy_score, market_popularity_local/regional/global, contract_status, career_stage, injury_status, retirement_status, death_flag, peak_rating, hall_of_fame_flag, legacy_tier. These will be added in future tasks.

#### fight_history (14 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fight_history_id | INTEGER | PK AUTOINCREMENT | |
| fight_id | INTEGER | NOT NULL FK → fights | |
| fighter_id | INTEGER | NOT NULL FK → fighters | This fighter's perspective |
| opponent_id | INTEGER | NOT NULL FK → fighters | Who they fought |
| outcome | TEXT | NOT NULL CHECK IN ('win','loss','draw','nc') | From this fighter's perspective |
| result_type | TEXT | | 'unanimous_decision', 'split_decision', 'draw', (future: 'ko_tko', 'submission', etc.) |
| finish_round | INTEGER | | Round the fight ended (scheduled_rounds for decisions) |
| finish_time | TEXT | | '5:00' for decisions, 'M:SS' for finishes (B2) |
| score_margin | INTEGER | | Abs damage differential (how dominant was the winner) |
| event_id | INTEGER | FK → events | |
| event_date | TEXT | | Date of the event |
| weight_class_id | INTEGER | FK → weight_classes | |
| title_at_stake | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | 1 if is_title_fight was 1 for this fight |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE (fight_id, fighter_id) | | | One row per fighter per fight |

### 2.5 Staff & Broadcast (2 tables)

#### staff (10 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| staff_id | INTEGER | PK AUTOINCREMENT | |
| first_name / last_name | TEXT | NOT NULL | |
| age | INTEGER | NOT NULL | |
| nation_id | INTEGER | FK → nations | |
| role_type | TEXT | NOT NULL | 'commentator', 'scout' (future), 'coach' (future), etc. |
| specialty | TEXT | | e.g. 'analysis' |
| promotion_id | INTEGER | FK → promotions | |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for skill_level, reputation, loyalty, salary, contract_start/end, fatigue, retirement_status, death_flag. Task 6.5 (Staff UI tab) and future tasks.

#### broadcast_staff (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| broadcast_staff_id | INTEGER | PK AUTOINCREMENT | |
| staff_id | INTEGER | NOT NULL UNIQUE FK → staff | One-to-one with staff |
| on_air_role | TEXT | NOT NULL | e.g. 'play_by_play' |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for mic_skill, analysis_skill, chemistry_rating, bias, credibility, knowledge_depth, commentary_style, catchphrase_level. Task 24.

### 2.6 Contracts (4 tables)

#### contracts (12 columns) — polymorphic base
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| contract_id | INTEGER | PK AUTOINCREMENT | |
| contract_target_type | TEXT | NOT NULL CHECK IN ('fighter','staff','broadcast') | Polymorphic discriminator |
| promotion_id | INTEGER | NOT NULL FK → promotions | Who holds the contract |
| start_date | TEXT | NOT NULL | ISO date |
| end_date | TEXT | NOT NULL | ISO date (start + 365 days for default) |
| salary | REAL | NOT NULL DEFAULT 0 CHECK (≥0) | Base salary |
| bonus_structure | TEXT | | Future: JSON for win/finish/title bonuses |
| buyout_clause | REAL | | Future: buyout amount for rival promotion poaching |
| exclusive_flag | INTEGER | NOT NULL DEFAULT 1 CHECK (0,1) | 1 = can't fight for other promotions |
| status | TEXT | NOT NULL DEFAULT 'active' CHECK IN ('active','expired','terminated','renegotiating') | |
| created_at / updated_at | TEXT | | |
| CHECK (end_date >= start_date) | | | |

#### fighter_contracts (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fighter_contract_id | INTEGER | PK AUTOINCREMENT | |
| contract_id | INTEGER | NOT NULL UNIQUE FK → contracts | One-to-one with base |
| fighter_id | INTEGER | NOT NULL FK → fighters | |
| contract_type | TEXT | NOT NULL DEFAULT 'standard' CHECK IN ('standard','champion','prospect','veteran') | |
| created_at | TEXT | | |

#### staff_contracts (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| staff_contract_id | INTEGER | PK AUTOINCREMENT | |
| contract_id | INTEGER | NOT NULL UNIQUE FK → contracts | |
| staff_id | INTEGER | NOT NULL FK → staff | |
| contract_role | TEXT | NOT NULL | e.g. 'commentator' |
| created_at | TEXT | | |

#### broadcast_contracts (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| broadcast_contract_id | INTEGER | PK AUTOINCREMENT | |
| contract_id | INTEGER | NOT NULL UNIQUE FK → contracts | |
| staff_id | INTEGER | NOT NULL FK → staff | |
| network_name | TEXT | NOT NULL | |
| created_at | TEXT | | |

### 2.7 Events & Fights (6 tables)

#### events (10 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| event_id | INTEGER | PK AUTOINCREMENT | |
| promotion_id | INTEGER | NOT NULL FK → promotions | |
| venue_id | INTEGER | NOT NULL FK → venues | |
| market_id | INTEGER | NOT NULL FK → markets | |
| event_name | TEXT | NOT NULL | e.g. 'Alpha Combat: Test Night' |
| event_date | TEXT | NOT NULL | ISO date |
| event_type | TEXT | NOT NULL | e.g. 'fight_night' |
| status | TEXT | NOT NULL DEFAULT 'scheduled' | 'scheduled'→'in_progress'→'completed' |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for prestige, glamour_score. Task 26.

#### fights (17 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fight_id | INTEGER | PK AUTOINCREMENT | |
| event_id | INTEGER | NOT NULL FK → events | |
| weight_class_id | INTEGER | NOT NULL FK → weight_classes | |
| bout_type | TEXT | NOT NULL | DEPRECATED — use card_slot + is_title_fight |
| card_slot | TEXT | NOT NULL DEFAULT 'main_event' CHECK IN ('main_event','co_main','featured_prelim','prelim','opener') | Card position |
| is_title_fight | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | Whether a title is at stake |
| round_limit | INTEGER | NOT NULL DEFAULT 3 | Max rounds allowed |
| scheduled_rounds | INTEGER | NOT NULL DEFAULT 3 | Scheduled rounds (3 for non-title, 5 for title — future) |
| winner_fighter_id | INTEGER | FK → fighters | NULL until resolved |
| loser_fighter_id | INTEGER | FK → fighters | NULL until resolved |
| result_type | TEXT | | 'unanimous_decision'/'split_decision'/'draw' (B2 adds ko_tko/submission/etc.) |
| finish_round | INTEGER | | Round the fight ended |
| finish_time | TEXT | | '5:00' for decisions |
| performance_rating | INTEGER | | 60-95, based on dominance |
| fan_reaction_rating | INTEGER | | 60-95, based on excitement |
| created_at / updated_at | TEXT | | |

#### fight_participants (6 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fight_participant_id | INTEGER | PK AUTOINCREMENT | |
| fight_id | INTEGER | NOT NULL FK → fights | |
| fighter_id | INTEGER | NOT NULL FK → fighters | |
| corner | TEXT | NOT NULL | 'red' or 'blue' |
| is_winner | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | Set on resolution |
| created_at | TEXT | | |
| UNIQUE (fight_id, fighter_id) | | | |

#### event_cards (9 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| event_card_id | INTEGER | PK AUTOINCREMENT | |
| event_id | INTEGER | NOT NULL FK → events | |
| fight_id | INTEGER | NOT NULL UNIQUE FK → fights | |
| card_position | INTEGER | NOT NULL | Ordering on the card (1 = first) |
| card_tier | TEXT | NOT NULL | e.g. 'main_event' |
| is_main_event | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | |
| is_co_main | INTEGER | NOT NULL DEFAULT 0 CHECK (0,1) | |
| created_at / updated_at | TEXT | | |

**Note:** THIN — spec calls for `notes` column. Low priority.

#### fight_beats (13 columns) — NEW in v2.1.0 (Task B1)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fight_beat_id | INTEGER | PK AUTOINCREMENT | |
| fight_id | INTEGER | NOT NULL FK → fights | |
| round_number | INTEGER | NOT NULL | 1, 2, 3, ... |
| beat_number | INTEGER | NOT NULL | 1, 2, 3, ... within the round |
| phase | TEXT | NOT NULL CHECK IN ('standing','clinch','cage','ground_top','ground_bottom','scramble') | Current fight phase |
| action_type | TEXT | NOT NULL | 'jab','cross','hook','leg_kick','takedown_attempt','submission_attempt','clinch_knee','ground_strike','sweep_attempt', etc. |
| initiator_fighter_id | INTEGER | NOT NULL FK → fighters | Who initiated the exchange |
| target_fighter_id | INTEGER | NOT NULL FK → fighters | Who was targeted |
| outcome | TEXT | NOT NULL CHECK IN ('landed','missed','blocked','defended','reversed') | Result of the exchange |
| damage_dealt | INTEGER | NOT NULL DEFAULT 0 | Damage points dealt by initiator |
| control_time_delta | INTEGER | NOT NULL DEFAULT 0 | Seconds of control time gained |
| momentum_shift | INTEGER | NOT NULL DEFAULT 0 | -100 to +100, signed toward initiator |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE (fight_id, round_number, beat_number) | | | |

#### fight_rounds (18 columns) — NEW in v2.1.0 (Task B1)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| fight_round_id | INTEGER | PK AUTOINCREMENT | |
| fight_id | INTEGER | NOT NULL FK → fights | |
| round_number | INTEGER | NOT NULL CHECK (>0) | 1, 2, 3, ... |
| fighter_a_id | INTEGER | NOT NULL FK → fighters | Red corner |
| fighter_b_id | INTEGER | NOT NULL FK → fighters | Blue corner |
| fighter_a_damage | INTEGER | NOT NULL DEFAULT 0 | SUM of damage dealt TO fighter_b |
| fighter_b_damage | INTEGER | NOT NULL DEFAULT 0 | SUM of damage dealt TO fighter_a |
| fighter_a_control_time | INTEGER | NOT NULL DEFAULT 0 | Total control seconds |
| fighter_b_control_time | INTEGER | NOT NULL DEFAULT 0 | |
| fighter_a_knockdowns | INTEGER | NOT NULL DEFAULT 0 | Always 0 in B1 (no finishes) |
| fighter_b_knockdowns | INTEGER | NOT NULL DEFAULT 0 | |
| fighter_a_takedowns | INTEGER | NOT NULL DEFAULT 0 | COUNT of landed takedown_attempt beats |
| fighter_b_takedowns | INTEGER | NOT NULL DEFAULT 0 | |
| fighter_a_strikes_landed | INTEGER | NOT NULL DEFAULT 0 | COUNT of landed strike beats |
| fighter_b_strikes_landed | INTEGER | NOT NULL DEFAULT 0 | |
| momentum_state | TEXT | | Current momentum leader |
| round_winner_fighter_id | INTEGER | FK → fighters | Who won this round (10-9) |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE (fight_id, round_number) | | | |

### 2.8 Rankings & Titles (2 tables)

#### rankings (12 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| ranking_id | INTEGER | PK AUTOINCREMENT | |
| fighter_id | INTEGER | NOT NULL FK → fighters | |
| weight_class_id | INTEGER | NOT NULL FK → weight_classes | |
| promotion_id | INTEGER | NOT NULL FK → promotions | Per-promotion rankings |
| rating | REAL | NOT NULL DEFAULT 1000.0 CHECK (≥0) | ELO rating (K=32, zero-sum) |
| fights_count | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | Total ranked fights |
| wins | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | |
| losses | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | |
| draws | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | |
| last_fight_date | TEXT | | ISO date of last ranked fight |
| created_at / updated_at | TEXT | | |
| UNIQUE (fighter_id, weight_class_id, promotion_id) | | | One row per fighter per WC per promotion |

#### titles (10 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| title_id | INTEGER | PK AUTOINCREMENT | |
| promotion_id | INTEGER | NOT NULL FK → promotions | |
| weight_class_id | INTEGER | NOT NULL FK → weight_classes | |
| current_champion_fighter_id | INTEGER | FK → fighters | NULL = vacant |
| champion_since_date | TEXT | | When current reign started |
| title_reigns_count | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | Total reigns (historical) |
| title_defenses_count | INTEGER | NOT NULL DEFAULT 0 CHECK (≥0) | Current reign's defenses |
| is_vacant | INTEGER | NOT NULL DEFAULT 1 CHECK (0,1) | 1 = no champion |
| created_at / updated_at | TEXT | | |
| UNIQUE (promotion_id, weight_class_id) | | | One belt per WC per promotion |

### 2.9 Regen & Name Pools (3 tables)

#### name_pools (5 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| name_pool_id | INTEGER | PK AUTOINCREMENT | |
| name_type | TEXT | NOT NULL CHECK IN ('first_male','first_female','last','nickname') | |
| name_value | TEXT | NOT NULL | The actual name |
| region | TEXT | | Future: region-specific names |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE (name_type, name_value) | | | No duplicate names per type |

**Seeded:** 25 male firsts, 25 female firsts, 26 lasts, 20 nicknames = 96 total

#### regen_lineage (6 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| regen_lineage_id | INTEGER | PK AUTOINCREMENT | |
| retiring_fighter_id | INTEGER | NOT NULL FK → fighters | Who retired |
| replacement_fighter_id | INTEGER | NOT NULL FK → fighters | Who was generated as replacement |
| style_dna_archetype_id | INTEGER | FK → style_archetypes | Style inherited from retiring fighter |
| regen_date | TEXT | NOT NULL | When the replacement was generated |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE (retiring_fighter_id, replacement_fighter_id) | | | |

#### fighter_memory_links (6 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| memory_link_id | INTEGER | PK AUTOINCREMENT | |
| fighter_id | INTEGER | NOT NULL FK → fighters | The new fighter (successor) |
| linked_fighter_id | INTEGER | NOT NULL FK → fighters | The retired champion |
| link_type | TEXT | NOT NULL CHECK IN ('style_echo','gym_heir','regional_rival','successor') | |
| link_strength | INTEGER | NOT NULL DEFAULT 50 CHECK (0-100) | min(50+10*title_reigns, 100) |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE (fighter_id, linked_fighter_id, link_type) | | | |

**Note:** Only populated for retiring champions (title_reigns > 0).

### 2.10 News & Commentary (3 tables)

#### news_sources (10 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| news_source_id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | NOT NULL UNIQUE | e.g. 'System Feed' |
| credibility | INTEGER | NOT NULL DEFAULT 50 | |
| sensationalism | INTEGER | NOT NULL DEFAULT 50 | |
| bias | INTEGER | NOT NULL DEFAULT 50 | |
| regional_reach | INTEGER | NOT NULL DEFAULT 50 | |
| reliability | INTEGER | NOT NULL DEFAULT 50 | |
| frequency | INTEGER | NOT NULL DEFAULT 50 | |
| created_at / updated_at | TEXT | | |

#### news_items (12 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| news_item_id | INTEGER | PK AUTOINCREMENT | |
| news_source_id | INTEGER | NOT NULL FK → news_sources | |
| headline | TEXT | NOT NULL | |
| body | TEXT | NOT NULL | |
| sentiment | TEXT | NOT NULL DEFAULT 'neutral' | 'neutral'/'positive'/'negative' |
| topic | TEXT | NOT NULL | 'fight'/'retirement'/'signing'/'prospect'/'legacy' |
| event_id | INTEGER | FK → events | |
| fight_id | INTEGER | FK → fights | |
| fighter_id | INTEGER | FK → fighters | |
| promotion_id | INTEGER | FK → promotions | |
| published_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Note:** THIN — spec calls for region_id. Low priority.

#### commentary_segments (8 columns)
| Column | Type | Constraints | Intended use |
|---|---|---|---|
| commentary_segment_id | INTEGER | PK AUTOINCREMENT | |
| event_id | INTEGER | FK → events | |
| fight_id | INTEGER | FK → fights | |
| segment_type | TEXT | NOT NULL | 'play_by_play' |
| speaker_staff_id | INTEGER | FK → staff | Commentator |
| text | TEXT | NOT NULL | Commentary line |
| importance | INTEGER | NOT NULL DEFAULT 50 | For highlight selection |
| created_at | TEXT | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

## 3. Module Function Inventory

### src/build_db.py
- `main()` — drops + rebuilds DB, checks version gate, writes schema_meta + schema_migrations
- `_parse_version(v)` — semver string → tuple of ints
- `_compare_versions(a, b)` — semver comparison (-1/0/+1)
- `_read_on_disk_schema_version(db_path)` — reads version from existing DB (read-only)

### src/fighter_gen.py
- `generate_attribute_block(archetype_id, conn)` → dict with 25 keys (50 + bias + noise, clamped 0-100)
- `generate_personality_block(archetype_id, conn)` → dict with 20 keys
- `generate_physical_block()` → dict with height_cm, reach_cm, stance, handedness
- `generate_potential()` → int (10% elite 70-90, 30% solid 50-69, 60% limited 25-49)
- Constants: `ATTRIBUTE_NAMES` (25), `PERSONALITY_NAMES` (20), `POTENTIAL_DISTRIBUTION`

### src/seed_data.py
- `main()` — seeds the minimal playable world
- `_seed_default_fighter_contract(conn, fighter_id, promotion_id, start_date)` — 12-month exclusive, 50000 salary
- `_seed_default_staff_contract(conn, staff_id, promotion_id, role, start_date)` — same pattern for staff
- `_seed_initial_ranking(conn, fighter_id, weight_class_id, promotion_id)` — rating=1000.0
- `_seed_vacant_title(conn, promotion_id, weight_class_id)` — is_vacant=1
- `_seed_name_pools(conn)` — 96 names across 4 types
- `_seed_archetypes(conn)` — 7 style + 5 personality archetypes with bias JSON
- `_backfill_fighter_v2(conn, fighter_id, style_archetype_id, pers_archetype_id)` — fills new columns for existing fighters
- `_backfill_potential_title_reigns(conn)` — sets potential for existing fighters

### src/tick_processor.py
- `run_tick(conn, tick_type, steps)` — advances clock, runs retirement + contract expiry checks
- `_check_retirements(conn, current_date)` — retires eligible fighters, generates replacements, creates memory links for champions
- `_check_contract_expiry(conn, current_date)` — expires contracts, creates free agents
- `main()` — CLI entry point (runs 1 tick)

### src/app.py — Core engine functions
- `resolve_next_fight(conn)` → fight_id or None — the main entry point. Calls resolve_round() per round, then all side effects.
- `resolve_round(conn, fight_id, round_number, fighter_a_id, fighter_b_id, stats_a, stats_b)` — generates 12-28 beats, writes to fight_beats, populates fight_rounds
- `_pick_action_type(phase, init_stats)` — picks action based on phase
- `_compute_beat_scores(phase, init_stats, target_stats)` — attack vs defense score
- `_compute_damage(phase, action_type, init_stats)` — damage calculation
- `_resolve_beat_outcome(phase, action_type, attack_score, defense_score, ...)` — determines outcome (landed/missed/blocked/defended/reversed)
- `_maybe_transition_phase(phase, action_type, outcome, ...)` — phase transitions
- `_decide_fight_outcome(rounds, fighter_a_id, fighter_b_id, scheduled_rounds)` — 10-point must decision scoring
- `_load_fighter_stats(conn, fighter_id)` — loads all 25 attrs + 20 personality into a dict

### src/app.py — Side effect functions (called by resolve_next_fight)
- `_update_event_status_after_resolution(conn, event_id)` — scheduled→in_progress→completed
- `_get_or_create_ranking_row(conn, fighter_id, weight_class_id, promotion_id)` — defensive INSERT OR IGNORE
- `_update_rankings_after_resolution(conn, winner_id, loser_id, ...)` — ELO K=32 zero-sum
- `_resolve_title_after_fight(conn, fight_id, event_id, winner_id, loser_id, ...)` — 5-case title resolution
- `_vacate_title_on_retirement(conn, fighter_id, current_date)` — vacates title + writes news
- `write_news(conn, headline, body, ...)` — inserts news_items row
- `write_commentary(conn, event_id, fight_id, text)` — inserts commentary_segments row
- `_format_fight_news(winner_name, loser_name, result_type, finish_round)` — generates headline + body
- `_format_fight_commentary(winner_name, loser_name, result_type, finish_round)` — generates commentary line

### src/app.py — Scheduling & generation
- `_pick_matchup(conn, promotion_id, weight_class_id, exclude_fighter_ids)` → (fighter_a_id, fighter_b_id) or None
- `schedule_next_event(conn, promotion_id, from_event_date, weeks_out)` → new event_id or None
- `generate_fighter(conn, style_dna_source_id, current_date, gender)` → new fighter_id or None — uses fighter_gen.py

### src/app.py — Display helpers (used by UI + tests)
- `get_fighters_for_display(conn, promotion_filter)` → list of 4-tuples
- `get_contracts_for_display(conn, promotion_id)` → list of 7-tuples
- `get_rankings_for_display(conn, promotion_id, weight_class_id, limit)` → list of 7-tuples
- `get_free_agents_for_display(conn)` → list of 5-tuples

### src/app.py — Free agency
- `sign_free_agent(conn, fighter_id, promotion_id, start_date, salary)` → contract_id or None

### src/app.py — Utility
- `fighter_name(conn, fighter_id)` → "First Last"
- `get_clock(conn)` → (date, day, week, month, year, tick_counter)
- `advance_day(conn)` — advances clock by 1 day

### src/app.py — UI class
- `App(tk.Tk)` — main window with 3-pane layout + 4-tab notebook
  - `build_ui()` — constructs all widgets
  - `refresh_all()` — reloads all data from DB into widgets
  - `on_advance_day()` / `on_resolve_fight()` / `on_sign_free_agent()` / `on_promo_filter_change()` — event handlers

---

## 4. Seeded World Data (v2.2.0)

| Entity | Count | Details |
|---|---|---|
| Nations | 1 | Northland (English) |
| Regions | 1 | East Coast (boxing, pressure; rivalries) |
| Weight classes | 1 | Lightweight (65.8-70.3 kg) |
| Cities | 1 | Metro City (pop 2,500,000) |
| Markets | 1 | Metro City (major) |
| Venues | 1 | Metro Arena (cap 18,000) |
| Promotions | 2 | Alpha Combat (major, regional_tv, ai_aggression=30), Rival Fight League (mid, local_stream, ai_aggression=60) |
| Gyms | 2 | Ironhouse Gym (AC), Steelcrest Gym (RFL) |
| Style archetypes | 7 | Balanced, Striker, Grappler, Wrestler, Brawler, Counter-Striker, Submission Specialist |
| Personality archetypes | 5 | Calm, Aggressive, Methodical, Showman, Quiet Professional |
| Fighters | 5 | John Vale (AC), Marcus Reed (AC), Dario Knox (RFL), Eli Storm (RFL), Cole Briggs (RFL) |
| Staff | 1 | Nina Cross (commentator, AC) |
| Contracts | 6 | 5 fighter + 1 staff (12-month, 50000 salary, exclusive, active) |
| Rankings | 5 | All at 1000.0 rating |
| Titles | 2 | AC Lightweight (vacant), RFL Lightweight (vacant) |
| Events | 1 | Alpha Combat: Test Night (2026-08-15, scheduled) |
| Fights | 1 | Title fight (main_event, is_title_fight=1, 3 rounds) |
| Name pools | 96 | 25 male first, 25 female first, 26 last, 20 nicknames |
| Potential | 5 | John Vale=72, Marcus Reed=71, RFL fighters 47-53 |
| Clock | 1 | 2026-07-20, day 1, week 1, tick 0 |

---

## 5. Version History

| Version | Task | Migration name | Key changes |
|---|---|---|---|
| 1.2.0 | Initial | — | 24 tables, coin-flip resolver |
| 1.2.1 | Task 2 | v1_2_1_initial | schema_meta + schema_migrations restored, DB renamed to cage_empire.db, RFL seeded |
| 1.3.0 | Task 4 | v1_3_0_add_fight_history | fight_history table |
| 1.4.0 | Task 9 | v1_4_0_add_contracts | contracts group (4 tables) |
| 1.5.0 | Task 10 | v1_5_0_add_rankings | rankings table (ELO) |
| 1.6.0 | Task 11 | v1_6_0_add_titles | titles table |
| 1.7.0 | Task 12 | v1_7_0_add_retirement | is_retired column on fighters |
| 1.8.0 | Task 13 | v1_8_0_add_free_agency | Contract expiry + free agency (no schema change, behavior only) |
| 1.9.0 | Task 14 | v1_9_0_add_regen | name_pools + regen_lineage + fighter_memory_links |
| 2.0.0 | 14.5+14.6+14.7 | v2_0_0_fighter_schema_expansion | 69 new columns (25 attrs, 20 personality, 14 fighters, 6 promotions, 8 gyms, 2 archetype bias) + current_date fix |
| 2.0.1 | pre-B1-fixes | v2_0_1_potential_memory_archetype_fix | potential + title_reigns columns, softened archetype biases, champion-only memory links |
| 2.1.0 | B1 | v2_1_0_add_beat_engine | fight_beats + fight_rounds tables, beat-level round simulation |
| 2.2.0 | pre-B2-fix | v2_2_0_fight_importance_columns | fights.card_slot + fights.is_title_fight + event_cards.is_co_main |
