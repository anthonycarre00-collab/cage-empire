from pathlib import Path
import sqlite3
import os

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
# DB_PATH can be overridden via CAGE_EMPIRE_DB_PATH env var or --db-path
# argument. Default: data/cage_empire.db (the world DB).
# Tests use data/cage_empire_test.db to avoid destroying the world DB.
_DEFAULT_DB_PATH = DATA_DIR / "cage_empire.db"
DB_PATH = Path(os.environ.get("CAGE_EMPIRE_DB_PATH", str(_DEFAULT_DB_PATH)))

# Schema version — see docs/CONVENTIONS.md for the versioning rules.
# Bump this on every schema change. Format: MAJOR.MINOR.PATCH.
#
# v2.5.0 (Task 16 — Training camps) — MINOR bump. Adds the new
# `training_camps` table (one row per fighter per scheduled fight —
# the camp they attend at their gym in the ~2 weeks leading up to the
# event). Per CONVENTIONS §1.1, adding a new table is a MINOR bump.
# Per CONVENTIONS §5 (one table-group per task), this task adds ONLY
# the `training_camps` table — it is a single logical group (career &
# development) that builds on Task 14.6's gym specialization columns
# (facility_quality, medical_support, sparring_depth, development_
# focus, culture_tone, weight_cut_support) and Task 15's injuries
# table (camp injury risk feeds into Task 15's injury system). Per
# CONVENTIONS §5.3, the table ships with both a writer
# (schedule_next_event in app.py creates camps when a new event is
# scheduled; _check_training_camps in tick_processor.py progresses
# and completes them) and a reader (resolve_next_fight in app.py
# reads the camp's fatigue to apply a starting-gas penalty).
#
# Schema changes in this task (per the Task 16 brief):
#   1. New `training_camps` table — 19 columns. The brief's parenthetical
#      lists 19 column names ("training_camp_id PK, fighter_id FK, gym_id
#      FK, event_id FK, fight_id FK, start_date, end_date,
#      camp_duration_days, camp_focus CHECK IN ..., camp_morale 0-100
#      DEFAULT 50, camp_fatigue 0-100 DEFAULT 0, camp_injury_risk 0-100
#      DEFAULT 0, camp_weight_cut_pressure 0-100 DEFAULT 0,
#      attribute_changes TEXT, camp_result_summary TEXT, is_active 0/1
#      DEFAULT 1, is_completed 0/1 DEFAULT 0, created_at, updated_at")
#      but the brief's prose header says "20 columns". Implemented the
#      19 enumerated columns (the list is the authoritative spec — the
#      "20" in the prose is an off-by-one typo, same pattern as Task
#      14.5's "21 vs 22 new attribute columns" decision D1). See
#      worklog decision D2 for the full explanation. The CHECK
#      constraints enforce camp_morale, camp_fatigue, camp_injury_risk,
#      camp_weight_cut_pressure all 0-100; is_active / is_completed
#      0/1; camp_focus restricted to the 8 enumerated values (striking,
#      grappling, wrestling, conditioning, submission, clinch, general,
#      weight_cut). FKs: fighter_id NOT NULL ON DELETE CASCADE, gym_id
#      / event_id / fight_id ON DELETE SET NULL (preserve camp history
#      when a gym/event/fight is deleted — the camp record survives
#      with NULL FK).
#
# Code changes in app.py (Task 16):
#   - New `_create_training_camp()` helper called from
#     schedule_next_event() AFTER the event, fight, participants, and
#     event_cards rows are INSERTed. For each of the 2 booked fighters,
#     creates one training_camps row with start_date = event_date - 14
#     days, end_date = event_date, camp_duration_days = 14, camp_focus
#     derived from the fighter's fight_style_archetype_id (style
#     archetype name → camp_focus via _ARCHETYPE_NAME_TO_CAMP_FOCUS
#     map; default 'general'). The camp's gym_id is the fighter's
#     current_gym_id — if NULL, the camp is skipped (with a printed
#     warning) since free agents without a gym can't run a camp.
#   - New `_get_camp_fatigue_for_event()` reader called from
#     resolve_next_fight() to apply the brief's "Fatigue > 50 = reduced
#     starting gas" rule. Reads the most recent training_camps row for
#     the (fighter_id, event_id) pair; if camp_fatigue > 50, the
#     fighter's starting gas is reduced by (camp_fatigue - 50), floored
#     at 50. This is the reader required by CONVENTIONS §5.3.
#   - New `_CAMP_FOCUS_ATTRS` mapping camp_focus → attribute pool (used
#     by tick_processor._complete_training_camp to pick which
#     attributes the camp upgrades — striking → punch_power/accuracy/
#     kick_power/accuracy/head_movement, etc.).
#   - New `_ARCHETYPE_NAME_TO_CAMP_FOCUS` mapping archetype name →
#     camp_focus (Striker → striking, Grappler → grappling, Wrestler
#     → wrestling, Submission Specialist → submission, Brawler/
#     Counter-Striker → striking, Balanced → general; default
#     'general' for unknown archetypes).
#
# Code changes in tick_processor.py (Task 16):
#   - New `_check_training_camps()` helper called from run_tick() AFTER
#     _check_injury_recovery. For each active, uncompleted camp whose
#     [start_date, end_date] window contains current_date:
#       * If current_date == end_date: complete the camp. Pick 2-4
#         attributes from the camp_focus pool (count = 2 + int((coach_
#         ability + development_focus) / 100), clamped to [2, 4]).
#         Apply +1 to +3 base gain to each chosen attribute, scaled
#         by gym spec multiplier (0.5-1.5 from facility_quality +
#         development_focus), coachability multiplier (0.5-1.5), and
#         fatigue factor (0.5-1.0 from fatigue_tolerance vs camp_
#         fatigue). Capped at fighter_career.potential. Write the
#         attribute_changes JSON + camp_result_summary + a completion
#         news item ("{Fighter} completes training camp"). Set
#         is_active=0, is_completed=1.
#       * Else (start_date < current_date < end_date): progress the
#         camp. Accrue fatigue +2-5 per tick (modified by cardio +
#         fatigue_tolerance, both reducing). Fluctuate morale by ±0-2
#         (modified by coachability dampening + culture_tone bias —
#         disciplined = +morale, loose = -morale, predator = +morale,
#         balanced = neutral). Accumulate injury_risk +2-5 per tick
#         (modified by injury_proneness increasing + medical_support
#         reducing). If injury_risk > 80: create an injury via the
#         Task 15 injuries table (training-injury pool: torn ACL,
#         hamstring strain, shoulder labrum tear, rib sprain, training
#         concussion, wrist/ankle sprain), reduce career_health by
#         severity*2, write injury news, and mark the camp as inactive
#         + completed (the fighter is injured and can't continue).
#   - EXTENDED: run_tick — calls _check_training_camps AFTER
#     _check_injury_recovery (order: clock advance → _check_retirements
#     → _check_contract_expiry → _check_injury_recovery →
#     _check_training_camps → commit). Prints one-line logs per tick
#     if any camps completed or any camp injuries occurred.
#
# News items written (Task 16):
#   - Camp completion: "{Fighter} completes training camp" with
#     topic='training', fighter_id set, body summarizing the attribute
#     changes ("Training camp (striking): punch_power +2, head_movement
#     +1"). This is the narrative layer the Soul document demands — the
#     player sees "John Vale's striking camp paid off — his punch power
#     is up 2 points" instead of a raw UPDATE query.
#   - Camp injury: "{Fighter} suffers {injury_type} in training" with
#     topic='injury', fighter_id set. Same news shape as Task 15's
#     fight injuries — the player can't tell from the headline whether
#     the injury happened in camp or in the fight, which is realistic
#     (both are "the fighter is hurt" stories).
#
# Migration name: v2_5_0_add_training_camps.
#
# v2.6.0 (Task 16.5 — World seed prep) — MINOR bump. Adds two new
# tables (`fighter_bios`, `hall_of_fame`) and two new columns to
# existing tables (`regions.nation_id`, `weight_classes.gender` +
# `weight_classes.display_order`). These are required for the world
# seed (Task 31): the bios table holds long-form prose for the top
# ~200 featured fighters; the hall_of_fame table holds retired
# legends; `regions.nation_id` is a long-standing bug (regions had
# no link to nations — only cities did); `weight_classes.gender` is
# required so men's and women's weight classes can coexist (the
# real-world UFC has both).
#
# Schema changes:
#   1. `regions.nation_id` — FK to nations(nation_id) ON DELETE SET
#      NULL. Bug fix: the table had no nation link before, despite
#      `cities.nation_id` existing. The seed Phase 1 populates this.
#   2. `weight_classes.gender` — TEXT NOT NULL DEFAULT 'male' CHECK
#      IN ('male','female'). Default 'male' preserves backward
#      compatibility with the existing seeded weight class (which
#      was implicitly male).
#   3. `weight_classes.display_order` — INTEGER NOT NULL DEFAULT 0.
#      Used by the UI to display weight classes in a sensible order
#      (Heavyweight first, Strawweight last) instead of by ID.
#   4. `fighter_bios` — new table. PK = fighter_id (one bio per
#      fighter). bio_text NOT NULL. bio_tone CHECK restricted to 12
#      enumerated tone values used by the voice layer (Task 19).
#   5. `hall_of_fame` — new table. PK = fighter_id. inducted_date
#      NOT NULL. career_summary NOT NULL. career_highlights TEXT
#      (nullable — some legends have only a summary).
#
# Per CONVENTIONS §1.1, adding new tables + new columns = MINOR.
# Per CONVENTIONS §5 (one table-group per task), this task adds
# the "world seed prep" group — bios + hall_of_fame + the two
# column fixes are all in service of the upcoming world seed.
#
# Migration name: v2_6_0_world_seed_prep.
#
# v2.7.0 (Task 17 — Weight cuts) — MINOR bump. Adds the new
# `weight_cut_log` table (one row per fighter per fight recording the
# weight cut result: made_weight, weight_missed_kg, cut_outcome,
# cardio_penalty, purse_penalty_pct). Per CONVENTIONS §1.1, adding a
# new table is a MINOR bump. Per CONVENTIONS §5 (one table-group per
# task), this task adds ONLY the `weight_cut_log` table — it is a
# single logical group (fight preparation) that builds on the existing
# `fighters.weight_cut_difficulty` column (Task 14.5) and the existing
# `training_camps.camp_weight_cut_pressure` column (Task 16).
#
# Schema changes in this task:
#   1. New `weight_cut_log` table — 14 columns. One row per fighter
#      per scheduled fight, recording the cut outcome. The
#      `cut_outcome` CHECK constrains to the 5 enumerated values
#      ('made_weight', 'missed_small', 'missed_medium', 'missed_large',
#      'cancelled'). FKs: fighter_id NOT NULL ON DELETE CASCADE,
#      fight_id / event_id ON DELETE SET NULL (preserve cut history
#      when a fight/event is deleted).
#
# Code changes in app.py (Task 17):
#   - New `_run_weight_cut()` helper called from resolve_next_fight()
#     BEFORE the fight resolves. For each of the 2 fighters, rolls
#     against the miss probability (derived from weight_cut_difficulty
#     + age + camp_weight_cut_pressure). If the fighter misses, picks
#     a cut_outcome based on how badly they missed (small/medium/large).
#   - New `_apply_weight_cut_penalty()` helper that applies the cardio
#     penalty to the fighter's starting gas (for missed_small and
#     missed_medium — the fight proceeds at catch-weight with reduced
#     cardio). For missed_large, the fight is CANCELLED (returns early
#     from resolve_next_fight with no fight resolution).
#   - New `_record_weight_cut_log()` helper that writes the
#     weight_cut_log row + a news item ("{Fighter} misses weight by
#     X kg" or "{Fighter} makes weight").
#
# Code changes in tick_processor.py (Task 17):
#   - The training camp progression (_progress_training_camp) now
#     accrues camp_weight_cut_pressure for camps with camp_focus=
#     'weight_cut' (reserved in Task 16). This pressure feeds into
#     _run_weight_cut's miss probability.
#
# Migration name: v2_7_0_add_weight_cut_log.
#
# v2.8.0 (Task 19 — Voice / Interpretation Layer) — MINOR bump. Adds
# the new `fighter_descriptors` snapshot table. This is the caching
# layer for the interpretation layer (src/voice.py). Per CONVENTIONS
# §14, no raw numbers appear in the player-facing UI — everything
# passes through voice.py which translates 0-100 values into
# descriptor strings. The fighter_descriptors table caches the
# computed descriptors per fighter as JSON, updated on trigger
# events (camp completion, fight resolution, injury, title change)
# — NOT on every UI view.
#
# Schema changes:
#   1. New `fighter_descriptors` table — 8 columns. PK = fighter_id
#      (one snapshot per fighter). attribute_descriptors JSON (25
#      key-value pairs). personality_descriptors JSON (20 pairs).
#      career_stage TEXT. career_health_desc TEXT. overall_desc TEXT.
#      snapshot_version INTEGER (incremented on each update).
#      updated_at TEXT.
#
# Migration name: v2_8_0_add_fighter_descriptors.
#
# v2.4.0 (Task 15 — Injuries + medical recovery) — MINOR bump. Adds
# the new `injuries` table (one row per injury a fighter suffers).
# Per CONVENTIONS §1.1, adding a new table is a MINOR bump. Per
# CONVENTIONS §5 (one table-group per task), this task adds ONLY the
# `injuries` table — it is a single logical group (career & medical)
# even though the SCHEMA_DRIFT_AUDIT.md §H list also includes
# `training_camps` (deferred to Task 16). The injuries table ships
# with both a writer (resolve_next_fight in app.py, _check_injury_
# recovery in tick_processor.py) and a reader (_pick_matchup in
# app.py, plus the upcoming UI tab) per CONVENTIONS §5.3.
#
# Schema changes in this task (per the Task 15 brief):
#   1. New `injuries` table — 15 columns. The CHECK constraints
#      enforce severity 1-10, long_term_damage 0-100, career_risk
#      0-100, is_active 0/1, and body_area restricted to the 18
#      anatomical regions enumerated in the brief (head, face, jaw,
#      nose, eye, neck, shoulder, arm, elbow, wrist, hand, ribs,
#      back, hip, knee, ankle, foot, general). The schema sketch in
#      STAGES.md had `body_area TEXT NOT NULL` without a CHECK; the
#      brief's expanded Injury types by body area section enumerates
#      the 18 allowed values, so the CHECK is added to enforce them
#      (the brief's expanded section is the authoritative spec).
#      ON DELETE CASCADE on fighter_id keeps the table clean when a
#      fighter is deleted; ON DELETE SET NULL on event_id and
#      fight_id preserves the injury record (with NULL event/fight
#      FK) when an event or fight is deleted, so a fighter's injury
#      history survives event/fight cleanup.
#
# Code changes in app.py (Task 15):
#   - New `_maybe_create_injury()` helper called at the END of
#     resolve_next_fight() AFTER all existing side effects
#     (fight_history, rankings, titles, event lifecycle,
#     schedule_next_event, news, commentary, commentary beat
#     selection). For each fighter in the resolved fight, computes
#     cumulative damage_taken from fight_beats, then rolls against
#     injury probability:
#       * doctor_stoppage: guaranteed injury on the loser (the
#         reason the doctor stopped it).
#       * ko_tko: 30% chance of head injury (concussion) on the
#         loser, severity scaled by damage in the finishing beat.
#       * submission: 15% chance of joint injury (knee/elbow/
#         shoulder/ankle) on the loser.
#       * decision / draw / corner_stoppage / dq: 5% base + damage-
#         scaled chance, applied to BOTH fighters.
#     injury_proneness (fighters column) modifies the probability
#     (0.5x at proneness=0, 1.5x at proneness=100). durability
#     (fighter_attributes column) reduces severity (high durability
#     = less severe). projected_return_date = start_date + severity
#     * 14 days, reduced by recovery_rate * 0.1 per day. Severity
#     8+ injuries have a 30% chance of permanent attribute reduction
#     (-2 to -5 on a body-area-relevant attribute) which is stored
#     as long_term_damage on the injuries row AND applied to
#     fighter_attributes + fighter_career.career_health. Each
#     active injury reduces career_health by severity * 2 while
#     active (restored on recovery).
#   - `_pick_matchup()` now filters out fighters with active
#     injuries (`AND fighter_id NOT IN (SELECT fighter_id FROM
#     injuries WHERE is_active = 1)`) — injured fighters can't be
#     booked. This is the reader required by CONVENTIONS §5.3.
#
# Code changes in tick_processor.py (Task 15):
#   - New `_check_injury_recovery()` helper called from run_tick()
#     after _check_contract_expiry. For each active injury where
#     `current_date >= projected_return_date`: sets
#     actual_return_date = current_date, is_active = 0, restores
#     career_health by severity * 2 (the temporary penalty lifted),
#     and writes a clearance news item ("{Fighter} cleared to
#     return from {injury_type}"). The permanent long_term_damage
#     and any permanent attribute reduction are NOT restored (they
#     represent lasting consequences — the Soul document's "the
#     story is the reward" mandate: a torn ACL at age 32 should
#     haunt the fighter's career).
#
# News items written (Task 15):
#   - Injury creation: "{Fighter} suffers {injury_type}" with
#     topic='injury', fighter_id set, projected return in the body.
#   - Recovery clearance: "{Fighter} cleared to return from
#     {injury_type}" with topic='injury', fighter_id set. These
#     are the narrative layer the Soul document demands — the
#     player remembers "the prospect who tore his ACL in his title
#     shot and came back 9 months later" because the news engine
#     surfaced both moments.
#
# Migration name: v2_4_0_add_injuries.
#
# v2.3.0 (Task B2 — Beat Engine Depth) — MINOR bump. Modifies the
# fight_beats.outcome CHECK constraint to add two new outcome values
# ('knockdown' and 'near_finish') that the B2 engine uses to mark the
# finishing exchange of a mid-round KO/TKO and the "rocked but
# survived" near-finish moments. B1's outcome CHECK allowed only
# ('landed','missed','blocked','defended','reversed') — purely
# per-beat exchange outcomes. B2 adds dramatic depth:
#   - 'knockdown' marks the beat that ends a fight by KO/TKO (the
#     finishing blow) AND high-momentum knockdown moments that didn't
#     end the fight (a fighter got dropped but survived). These carry
#     momentum_shift = +80 per the B2 brief.
#   - 'near_finish' marks the beat where a defender was "rocked"
#     (cumulative damage in the current beat sequence crossed their
#     KO threshold, but the KO roll failed) OR where a submission
#     attempt landed (defender tapped — finish) OR where a submission
#     attempt almost succeeded. These carry momentum_shift = +60.
#
# Schema changes in this task (per the B2 brief):
#   1. `fight_beats.outcome` CHECK constraint: add 'knockdown' and
#      'near_finish' to the allowed outcome values (superset of B1's
#      5 values — no breaking change to existing rows). Per CONVENTIONS
#      §1.1, modifying a CHECK constraint on an existing table is a
#      MINOR bump (existing rows still satisfy the new CHECK because
#      the new values are a superset).
#   2. `fight_rounds.fighter_a_gas_remaining` and
#      `fight_rounds.fighter_b_gas_remaining` REAL NOT NULL DEFAULT
#      100.0 columns: per the B2 brief ("Store in
#      fight_rounds.fighter_a/b_gas_remaining"). resolve_round() now
#      writes the per-round gas values to these columns (per-fighter,
#      tracked in-memory across rounds by resolve_next_fight()).
#      Adding columns to an existing table is a MINOR bump per
#      CONVENTIONS §1.1. The DEFAULT 100.0 keeps existing INSERTs
#      valid (a fighter starting a round has 100 gas unless they
#      carried over lower gas from the previous round). This breaks
#      test_beat_engine case A.10's hardcoded 17-column count
#      assertion (D-number decision D1 — flagged per CONVENTIONS §11
#      for the supervisor to relax to a column-subset check; the new
#      test_beat_engine_depth.py uses a column-subset check that
#      survives future column additions).
#
# No new tables. No columns removed. Migration name:
# v2_3_0_beat_engine_depth.
#
# Code changes in app.py (Task B2):
#   - Added fatigue system: gas=100 per fight, depletes per beat
#     (phase-dependent costs), cardio + fatigue_tolerance slow decay,
#     low gas (<30) reduces accuracy 30% and chin vulnerability +20%.
#     Recovery between rounds: gas += recovery_rate * 0.3 (capped 100).
#   - Added momentum system: cumulative momentum in a round shifts
#     subsequent beat probabilities (initiator_advantage = clamp(
#     cum_momentum/200, -0.3, +0.3)). Knockdown beats produce
#     momentum_shift = +80, near_finish beats produce +60, big
#     takedowns produce +30. Produces "smells blood" sequences
#     instead of memoryless coin flips.
#   - Added mid-round finishes: KO/TKO (cumulative damage threshold
#     modified by chin/recovery_rate/grit/composure, killer_instinct
#     increases finish probability), submission (submission_offense vs
#     submission_defense/flexibility/scramble_ability/composure),
#     doctor stoppage (cumulative damage > 200 + durability*2,
#     checked between rounds), corner stoppage (3+ lost rounds +
#     low grit/composure, 20% chance), DQ (low discipline + illegal
#     strike, 1% per beat).
#   - Added fight importance + pressure modifiers: importance computed
#     from card_slot (40%) + is_title_fight (30%) + rivalry heat (15%,
#     0 for now) + avg marketability (15%). In high-importance fights
#     (>60), pressure_response (clutch_factor*0.35 + composure*0.25 +
#     consistency*0.20 + focus*0.10 + grit*0.10) modifies beat scores:
#     >= 70 → +5%, <= 30 → -10%.
#   - Added commentary beat selection: after the fight resolves,
#     selects 3-14 most important beats (knockdowns, near-finishes,
#     finish, big momentum swings) and writes commentary_segments.
#     Beat count depends on fight importance (quick 3-6, standard
#     6-10, extended 10-14).
#
# v2.2.0 (Task pre-B2-fix) — MINOR bump. Adds three new columns to two
# existing tables to separate "card position" from "title-fight status"
# ahead of Task B2 (engine depth — fatigue + momentum + finishes +
# commentary). The pre-existing `fights.bout_type` column was doing
# double duty (card position AND title-fight flag) — a fight can be a
# main event AND a title fight, but a single TEXT column cannot express
# both. The fix splits the concept:
#   1. `fights.card_slot` — TEXT NOT NULL DEFAULT 'main_event' CHECK
#      (card_slot IN ('main_event','co_main','featured_prelim','prelim',
#      'opener')). Pure card-position column. Future Task B2 + booking
#      UI will read this to compute fight importance.
#   2. `fights.is_title_fight` — INTEGER NOT NULL DEFAULT 0 CHECK
#      (is_title_fight IN (0,1)). Pure title-fight flag. Code now checks
#      `is_title_fight=1` instead of the deprecated `bout_type='title_fight'`
#      comparison. The `bout_type` column is kept for backward
#      compatibility (deprecated — do not write new code that reads it).
#   3. `event_cards.is_co_main` — INTEGER NOT NULL DEFAULT 0 CHECK
#      (is_co_main IN (0,1)). Was in the v1.6 spec but missing from
#      the original build. Symmetric to the existing `is_main_event`
#      column. Future booking UI will set this for the second-biggest
#      fight on the card.
#
# Code changes in app.py:
#   - `_resolve_title_after_fight()` now checks `fights.is_title_fight=1`
#     instead of `fights.bout_type='title_fight'`.
#   - `resolve_next_fight()` computes `fight_history.title_at_stake`
#     from `fights.is_title_fight` instead of `fights.bout_type`.
#   - `schedule_next_event()` INSERT now sets `card_slot='main_event',
#     is_title_fight=0` on auto-scheduled fights (alongside the
#     deprecated `bout_type='main_event'`).
# Seed change in seed_data.py:
#   - The seeded title-fight INSERT now sets `card_slot='main_event',
#     is_title_fight=1` (alongside the deprecated `bout_type='title_fight'`).
#
# Per CONVENTIONS §1.1 this is a MINOR bump (adding new columns to
# existing tables — purely additive, no breaking change to data shape).
# The `bout_type` column is NOT removed (that would be a MAJOR bump and
# would require a backfill migration). Future tasks should treat
# `bout_type` as deprecated and read `card_slot` + `is_title_fight`
# instead. Migration name: v2_2_0_fight_importance_columns.
#
# v2.1.0 (Task B1) — MINOR bump. First beat-level fight engine release.
# Adds two new tables that the rewritten `resolve_next_fight()` in
# app.py populates as it simulates each round:
#   1. `fight_beats` — one row per discrete exchange within a round
#      (12-28 beats per round, pace-driven). Each beat records the
#      phase (standing / clinch / cage / ground_top / ground_bottom /
#      scramble), the action type, the initiator + target fighter IDs,
#      the outcome (landed / missed / blocked / defended / reversed),
#      the damage dealt, the control time delta, and the momentum shift.
#      This is the raw substrate that future Task B2 (fatigue +
#      momentum + finishes) and Task 23 (commentary beat selection)
#      build on. Per CONVENTIONS §14, the beat engine stores RAW
#      numbers — the interpretation layer (Task 19) is what eventually
#      translates them into prose.
#   2. `fight_rounds` — one row per round, holding the per-round
#      aggregates computed from that round's fight_beats rows (damage,
#      control time, knockdowns, takedowns, strikes landed, momentum
#      state, round winner). Knockdowns are always 0 in B1 (no
#      mid-round finishes — that's B2). The aggregate is populated by
#      a SUM-over-fight_beats query so the two tables never drift.
#
# The pure `_resolve_outcome()` function from Task 3 is REPLACED by
# `resolve_round()` in app.py. The new resolver generates beats,
# writes them to fight_beats, then writes the per-round aggregate to
# fight_rounds. After all scheduled rounds complete, decision scoring
# (10-point must, unanimous / split / draw) picks the fight winner.
# B1 does NOT have mid-round finishes — every fight goes to decision.
# B2 will add fatigue, momentum, KO/submission/doctor/corner/DQ.
#
# All existing side effects of resolve_next_fight() are PRESERVED
# (fight_history, rankings, titles, event lifecycle, schedule_next_event,
# news, commentary). Only the resolution mechanism changes. The
# `fights` table's winner_fighter_id / loser_fighter_id / result_type /
# finish_round / finish_time / performance_rating / fan_reaction_rating
# columns are populated exactly as before — just with decision-flavored
# values (result_type in {'unanimous_decision', 'split_decision',
# 'draw'}, finish_round = scheduled_rounds, finish_time = '5:00').
#
# v2.0.1 (Task pre-B1-fixes) — MINOR bump. Two new columns added to
# `fighter_career` (`potential` and `title_reigns`), neither of which
# removes or renames existing data — purely additive. The two new
# columns unblock three design fixes the supervisor flagged before
# the beat-level fight engine (Task B1) can begin:
#   1. `potential` (INTEGER NOT NULL DEFAULT 50 CHECK 0-100) is the
#      fighter's growth ceiling. Without it, every fighter has
#      unlimited growth potential and the Talent Hunter fantasy
#      (CAGE_EMPIRE_SOUL.md Fantasy 1) collapses — a journeyman could
#      theoretically train every attribute to 100. With `potential`,
#      training camps (Task 16, future) will push attributes toward
#      this ceiling with diminishing returns as they approach it.
#      Scarcity makes elite prospects exciting to find.
#   2. `title_reigns` (INTEGER NOT NULL DEFAULT 0 CHECK >= 0) counts
#      how many title reigns this fighter has had. It is incremented
#      by `_resolve_title_after_fight()` in app.py every time the
#      fighter wins a title (vacant title claimed OR reigning champion
#      dethroned). It is the clean, reliable signal the retirement
#      path uses to decide whether to create a `fighter_memory_links`
#      "successor" row — only fighters who held a title get the
#      "reminiscent of former champion {name}" treatment. Reserving
#      memory resurfacing for champions makes the comparison
#      meaningful: "reminiscent of former champion John Vale" means
#      something because Vale was a champion.
#
# Archetype biases in `seed_data.py` are also softened ~40-50% in the
# same task (max absolute bias drops from 20 to 10). Modern MMA
# fighters at the highest level are well-rounded; archetypes should
# be tendencies, not extremes. The bias softening is a data change
# only (no schema change to `style_archetypes` or
# `personality_archetypes` — the `attribute_bias` / `trait_bias`
# columns stay TEXT JSON).
#
# v2.0.0 (Task 14.5+14.6+14.7) — MAJOR bump. First major version,
# marking the transition from the thin skeleton (4 attributes, 3
# personality traits, coin-flip-equivalent resolver) to real
# simulation depth (25 attributes, 20 personality traits, full
# physical + meta columns on fighters, AI-tuning columns on
# promotions, training-camp-relevant columns on gyms, archetype
# bias JSON for variety in regen). 68 new columns across 6 existing
# tables + 2 archetype tables, plus a new module src/fighter_gen.py,
# plus the long-flagged current_date SQLite quirk fix (§Z.6). No new
# tables, no columns removed — this is purely an additive expansion
# (the MAJOR bump is for the depth-of-sim significance, not for any
# breaking change to existing data shape).
#
# v3.13.0 (Phase 4 — Performance: add 12 indexes on hot query columns)
# — MINOR bump. Per CONVENTIONS §1.1 MINOR is for additive changes;
# per §16.4, indexes are CREATE INDEX IF NOT EXISTS (idempotent —
# safe to re-run, no-op if already present). No data is moved, no
# schema is altered — only B-tree indexes are added to speed up
# existing queries. The migration is fast (< 100ms on a 4450-row
# fighters table) + runs in a single transaction (caller commits).
#
# v3.14.0 (Task RIVAL-AI-P1 — Rival AI Phase 1 Foundation) — MINOR
# bump. Per CONVENTIONS §1.1 MINOR is for additive changes; per §16.4,
# the migration is idempotent (_has_column guards every ALTER). Adds
# 3 new columns to `promotions` for the rival AI archetype system
# (per docs/RIVAL_AI_ARCHITECTURE.md §7.2):
#   - ai_archetype              TEXT     (nullable — NULL means
#                                        "not yet assigned". Assigned
#                                        on the first rival AI tick
#                                        by services.rival_ai.
#                                        archetypes.assign_all_archetypes.
#                                        One of: 'major_league' /
#                                        'regional_power' /
#                                        'grassroots' / 'rising_star'.)
#   - ai_scheduling_day_of_week INTEGER  (nullable — 1-7 Mon-Sun.
#                                        Assigned on first tick;
#                                        spreads rival promos across
#                                        the week per arch doc §4.2.)
#   - ai_budget_state           TEXT     (nullable — default 'NORMAL'.
#                                        One of: SURVIVAL /
#                                        CONSERVATIVE / NORMAL /
#                                        EXPANSION / CRISIS. Set to
#                                        'NORMAL' on first tick;
#                                        Phase 3's budget_manager
#                                        adjusts monthly.)
#
# The migration ALSO performs 2 one-time data backfills (per the
# RIVAL-AI-P1 task brief + EXISTING_SYSTEMS_AUDIT.md Parts 3+5):
#   1. Coach-gym backfill: assigns each of the 300 orphan coaches
#      (staff rows with role_type='coach' AND gym_id IS NULL AND
#      promotion_id IS NULL — a seed-script gap from v3.9.0) to a
#      gym. Round-robin assignment: each coach gets the next gym_id
#      in sequence. This is the "one-line backfill" the audit
#      identifies as the fix for the orphan coach problem.
#   2. staff_contracts backfill: creates a staff_contracts row (+
#      parent contracts row) for each of the 75 promo-bound staff
#      (staff rows with promotion_id IS NOT NULL). The polymorphic
#      contracts pattern supports target_type='staff' but the seed
#      script never wrote the rows — staff_contracts had 0 rows
#      despite 375 staff existing. Each backfilled contract is a
#      1-year deal (start_date='2026-07-20', end_date='2027-07-20')
#      with role-based salary.
#
# Both backfills print their counts so the operator can verify:
#   "  Backfilled 300 orphan coaches to gyms"
#   "  Backfilled 75 staff_contracts rows"
#
# On --fresh builds, the SCHEMA_SQL already includes the 3 new
# columns (added to the promotions CREATE TABLE below). The
# migration function is NOT called on --fresh (per CONVENTIONS
# §16.4) but the migration_name IS recorded in schema_migrations
# for audit-trail consistency. The backfills are skipped on --fresh
# (the fresh-build path seeds its own data; the backfills only
# apply to the existing world DB).
# v3.36.0 (TIER3-MISSING / W12+W29+W42+memory) — MINOR bump.
#
# Two migrations under one version bump (mirrors the v3.25.0 pattern
# of two migrations under one version):
#
#   1. _migrate_v3_36_0_add_provenance_metadata — adds 2 nullable TEXT
#      columns to schema_meta:
#        - world_version  — set on each save (e.g. "sim_2026-08-27_tick14")
#        - seed_version   — set on fresh DB build (e.g. "world_seed_v1")
#      For existing DBs (the --migrate path), the migration sets
#      seed_version='world_seed_v1' retroactively (every existing DB
#      was built from world_seed_v1).
#      Per docs/OPTIMIZATION_PLAN_TIER1_3.md §T3.3 (W42 — Provenance
#      metadata). The columns are nullable so old save files that
#      predate the migration can still be loaded (the columns will
#      just be NULL until the next save).
#
#   2. _migrate_v3_36_0_expand_memory_link_types_tier3 — expands
#      fighter_memory_links.link_type CHECK with 8 new values:
#        'previous_fights', 'former_teammates', 'old_gyms',
#        'former_champions', 'controversial_losses', 'injuries',
#        'promotions', 'old_events'
#      Per docs/OPTIMIZATION_PLAN_TIER1_3.md §T3.4 (W17 — 8 missing
#      memory link types). The new CHECK is a SUPERSET of the old
#      one (12 existing + 8 new = 20 total allowed link_types), so
#      every existing row is preserved verbatim by the table-rebuild
#      pattern (CONVENTIONS §16.6).
#
# Both migrations are idempotent (CREATE/ALTER guards + table-rebuild
# sentinel check). On --fresh builds, SCHEMA_SQL already includes
# both changes; the migration functions are no-ops (per CONVENTIONS
# §16.4) but the migration_names are still recorded in
# schema_migrations for audit-trail consistency.
CODE_SCHEMA_VERSION = "3.36.0"


# HW2.3 (docs/Hardening_Phase.md §HW2.3 / W5) — the formal sim-start
# date constant. New games initialize simulation_clock.current_date
# from this value (NOT from today's real date). Existing worlds keep
# whatever clock they have; only the --fresh seed path uses this.
#
# The literal "2026-01-01" matches the brief. The seed in _build_fresh
# reads this constant (so a future change to the start date only needs
# to update one line). seed_data.py + the staff_contract backfill also
# import this constant so contract start_dates stay consistent with
# the sim clock (contracts used to default to 2026-07-20; now they
# default to GAME_START_DATE).
GAME_START_DATE = "2026-01-01"


# v3.29.0 (HW2.1 — EventBus error persistence per docs/Hardening_Phase.md
# §HW2.1 / CRITICAL #5) — MINOR bump. Per CONVENTIONS §1.1 MINOR is for
# additive changes; this task adds ONE new table (simulation_tick_health)
# and the formal GAME_START_DATE constant (above). No existing columns
# are touched.
#
# simulation_tick_health stores ONE ROW PER TICK summarizing what
# happened during that tick: how long it took, how many event-bus
# subscribers were invoked, how many failed, a JSON blob of the errors
# (subscriber name + event type + traceback + sim date), and aggregate
# counts of side effects (events scheduled/completed, fights resolved,
# fighters retired/regen, injuries created/recovered, contracts changed,
# title changes, ranking changes, finance transactions, news/social/
# memory items generated).
#
# The migration _migrate_v3_29_0_add_simulation_tick_health is
# idempotent (uses _has_table guard). On --fresh builds, SCHEMA_SQL
# already includes the table (the migration function is not called,
# but the migration_name is still recorded in schema_migrations per
# §16.4).
#
# tick_success values:
#   1  = HEALTHY  (all subscribers succeeded, no errors)
#   0  = DEGRADED (>= 1 subscriber failed but the tick completed)
#   -1 = BROKEN   (tick itself crashed — set by run_tick's try/except
#                  wrapper if it catches an exception before writing
#                  the summary row)
#
# Read by:
#   - compute_world_health(conn) in app_web.py (HW2.4) — overall world
#     health status (HEALTHY/DEGRADED/BROKEN) based on recent ticks.
#   - get_world_health() API method (HW2.4) — exposes the same to JS.
#
# Written by:
#   - tick_processor.run_tick (HW2.1) — one row per tick at tick end.
#   - EventBus.publish (HW2.1) — on a subscriber failure, the error is
#     accumulated in the bus's in-memory tick_errors list (which
#     run_tick then reads + persists as the errors_json column).


# v3.28.0 (HW3 — Memory + Echoes Expansion per docs/Hardening_Phase.md
# §HW3.1 / CRITICAL #6) — MINOR bump. Per CONVENTIONS §1.1 MINOR is for
# additive changes; per §16.6, expanding a CHECK constraint requires a
# table rebuild (SQLite has no ALTER TABLE ADD CHECK).
#
# 4 new link_type values added to the fighter_memory_links.link_type
# CHECK enum:
#   'title_history' — the two fighters contested a title against each
#                     other (one dethroned the other, or they fought
#                     for a vacant belt). Written by memory_svc when
#                     TITLE_CHANGED fires; read by memory_engine's
#                     _search_title_fight_history.
#   'upset'         — the lower-rated fighter beat the higher-rated
#                     fighter (rankings.rating gap >= 15 at fight
#                     time). Written by memory_svc when FIGHT_RESOLVED
#                     fires + the rating-gap test passes; read by
#                     memory_engine's _search_major_upset.
#   'comeback'      — one of the fighters returned from a long layoff
#                     (>= 365 days without a fight) or from retirement.
#                     Written by memory_svc when FIGHTER_SIGNED fires
#                     for a previously-retired fighter; read by
#                     memory_engine (surfaced via the existing
#                     previous_fight / shared_gym searches — no
#                     dedicated _search_comeback because the comeback
#                     story is told from one fighter's perspective
#                     against their NEXT opponent, not a pairwise link).
#   'milestone'     — one fighter reached a career milestone against
#                     the other (10th win, 20th win, 5-KO streak,
#                     10th title defense). Written by memory_svc when
#                     FIGHT_RESOLVED fires + the milestone test passes;
#                     read by memory_engine's _search_career_milestone.
#
# The migration _migrate_v3_28_0_expand_memory_link_types_again rebuilds
# the table (rename → recreate with new CHECK → copy → drop old) per
# CONVENTIONS §16.6. The existing 775 rows (regional_rival 744 +
# style_echo 29 + successor 2) are preserved verbatim — the new CHECK
# is a SUPERSET of the old one, so every existing row still satisfies
# it.
#
# Pre-HW3, link_type CHECK was (8 values, v3.12.0):
#   ('style_echo', 'gym_heir', 'regional_rival', 'successor',
#    'previous_fight', 'shared_gym', 'former_teammate', 'injury_history')
# Post-HW3, link_type CHECK is (12 values):
#   ('style_echo', 'gym_heir', 'regional_rival', 'successor',
#    'previous_fight', 'shared_gym', 'former_teammate', 'injury_history',
#    'title_history', 'upset', 'comeback', 'milestone')


# v3.12.0 (Phase 2 — Task 2.5-memory-engine: expand fighter_memory_links.
# link_type CHECK with 4 new values) — MINOR bump. Per CONVENTIONS §1.1
# MINOR is for additive changes; per §16.6, expanding a CHECK constraint
# requires a table rebuild (SQLite has no ALTER TABLE ADD CHECK).
#
# 4 new link_type values added to the CHECK enum:
#   'previous_fight'   — the two fighters have fought before (written by
#                        memory_svc when a fight between them resolves;
#                        read by memory_engine.surface_memories when
#                        surfacing fight history before a booked rematch).
#   'shared_gym'       — the two fighters currently train at the same
#                        gym (written by memory_svc; read by the Memory
#                        Engine for the "former training partners" voice
#                        phrase).
#   'former_teammate'  — the two fighters trained at the same gym at
#                        overlapping times in the past (written by
#                        memory_svc; read by the Memory Engine).
#   'injury_history'   — the linked fighter appears in this fighter's
#                        injury narrative (e.g., the cause of a recent
#                        layoff). Written by memory_svc; read by the
#                        Memory Engine for the "recovering from injury"
#                        voice phrase.
#
# The migration _migrate_v3_12_0_expand_memory_link_types rebuilds the
# table (rename → recreate with new CHECK → copy → drop old) per
# CONVENTIONS §16.6. The existing 96 rows (all 'style_echo') are
# preserved verbatim — the new CHECK is a SUPERSET of the old one, so
# every existing row still satisfies it.
#
# Memory Engine (Task 2.5) + Headline Engine (Task 2.6) ship in the
# same task batch (Task ID 2.5-2.6-memory-headlines). The Headline
# Engine writes to the existing daily_headlines table (added in
# v3.11.0) — no schema change required for headlines.
#
# Pre-Task 2.5, link_type CHECK was:
#   ('style_echo', 'gym_heir', 'regional_rival', 'successor')
# Post-Task 2.5, link_type CHECK is:
#   ('style_echo', 'gym_heir', 'regional_rival', 'successor',
#    'previous_fight', 'shared_gym', 'former_teammate', 'injury_history')


# v3.11.0 (Phase 2 — Task 2.1-snapshot-cache: add 4 new cache tables for
# the Snapshot Cache orchestrator) — MINOR bump. Per CONVENTIONS §1.1,
# adding new tables qualifies as MINOR. Per §5 (one table-group per
# task), this task adds ONLY the Phase 2 Interpretation Layer's 4 cache
# tables that store daily-refreshed summaries of gyms, promotions,
# divisions, and daily headlines. The orchestrator (snapshot_cache.py)
# is the ONLY writer per CONVENTIONS §17.3; Office Mode UI is the
# intended reader.
#
# 4 new tables:
#   gym_descriptors         — PK = gym_id. ~5 TEXT columns describing
#                             the gym's identity (identity_label,
#                             known_for, produces, weakness,
#                             development_rating_desc). Written by
#                             Task 2.8 (gym_identity_engine).
#   promotion_descriptors   — PK = promotion_id. 3 TEXT columns
#                             (prestige_desc, market_position_desc,
#                             roster_quality_desc).
#   division_descriptors    — PK = (promotion_id, weight_class_id) via
#                             UNIQUE constraint + AUTOINCREMENT surrogate.
#                             2 TEXT columns (depth_desc,
#                             competitiveness_desc).
#   daily_headlines         — PK = (headline_date, headline_type) via
#                             UNIQUE. 8 headline types per day
#                             (top_story, upset_of_week,
#                             fastest_rising, biggest_fall,
#                             contract_drama, gym_of_month,
#                             veteran_watch, prospect_watch). Written
#                             by Task 2.6 (headline_engine).
#
# All 4 tables have a snapshot_version INTEGER (DEFAULT 1) + an
# updated_at TEXT (DEFAULT CURRENT_TIMESTAMP) — mirrors the
# fighter_descriptors cache pattern (Task 19) for cache busting.
#
# The migration function _migrate_v3_11_0_add_cache_tables is
# idempotent (uses _has_table guards before each CREATE TABLE). On
# --fresh builds, the SCHEMA_SQL already includes the 4 new tables
# (the migration function is not called, but the migration_name is
# still recorded in schema_migrations per §16.4).
#
# Default settings seeded by the migration: (none — schema-only change.
# The daily interpretation pass in snapshot_cache.py populates the
# tables on the first run_tick after registration.)


# v3.10.0 (Phase 2 — Task 2.0c-schema-backfill: extend fighter_descriptors
# with 6 interpretation columns + add interpretation_cache_meta table) —
# MINOR bump. Per CONVENTIONS §1.1, adding columns to an existing table
# AND adding a new table both qualify as MINOR. Per §5, this task adds
# a single logical group: the Phase 2 Interpretation Layer's fighter-
# facing snapshot columns + the cache-engine version meta table.
#
# 6 new columns on fighter_descriptors (all nullable TEXT — the Phase 2
# Context Engine, Career Phase Engine, Narrative Families, and Legacy
# Engine will populate them in subsequent tasks 2.2/2.3/2.4/2.7):
#   momentum         — 'very_high'|'high'|'stable'|'falling'|'collapsing'
#   pressure         — 'minimal'|'moderate'|'high'|'extreme'
#   career_phase     — 'prospect'|'rising_contender'|'title_challenger'|
#                      'champion'|'dominant_champion'|'veteran'|
#                      'gatekeeper'|'journeyman'|'comeback'|'declining'|
#                      'retirement_tour'
#   narrative_family — 'prodigy'|'veteran'|'fallen_champion'|
#                      'cinderella_story'|... or NULL
#   public_narrative — 'future_champion'|'needs_one_more_win'|
#                      'career_in_freefall'|... or NULL
#   legacy_state     — 'building'|'established'|'legendary'|'forgotten'|...
#
# IMPORTANT: the existing career_stage column stays (it's used by
# news.py for news generation; the new career_phase is for UI display
# per CONVENTIONS §17). They serve different purposes.
#
# 1 new table: interpretation_cache_meta (singleton row, tracks the
# interpretation engine version + last_built_date so the daily pass
# can invalidate + rebuild caches when the engine's logic changes).
#
# The migration function _migrate_v3_10_0_extend_fighter_descriptors is
# idempotent (uses _has_column / _has_table guards before ALTER / CREATE).
# On --fresh builds, the SCHEMA_SQL already includes the new columns +
# the new table. The backfill script (scripts/backfill_missing_snapshots.py)
# creates descriptor snapshots for the 60 HoF legends + 450 Group B
# fighters that were added in Phase 1.5 without descriptor rows.
#
# Default settings seeded by the migration: (none — schema-only change.
# The 6 new columns default to NULL on existing rows; subsequent Phase
# 2 tasks populate them via the daily interpretation pass.)


# v3.9.0 (Phase 1.5 — Task 1.5C-seed-data Fix C6: add staff.gym_id
# column for coach-gym linkage) — MINOR bump. Per CONVENTIONS §1.1,
# adding a column to an existing table is a MINOR bump. Per §5 (one
# table-group per task), this task adds ONLY the staff.gym_id column —
# a single logical group (coach-gym linkage so each staff coach can be
# affiliated with a gym, independent of staff_contracts which is empty).
# The migration function _migrate_v3_9_0_add_staff_gym_id is idempotent
# (uses _has_column guard before ALTER TABLE). On --fresh builds, the
# SCHEMA_SQL already includes the column. The seed script
# (scripts/group_c_seed.py) back-fills the gym_id for each existing
# coach (match by nation_id if possible, else random gym). Future coach
# generation in seed scripts should also set staff.gym_id.
#
# Default settings seeded by the migration: (none — schema-only change.)


# v3.8.0 (Stage 6 prep — D-GUI-4 Fight Resolution screen) — MINOR bump.
# Adds `staff.pundit_bias` JSON column. The 5 broadcast_staff (1 per
# promotion) get a populated bias JSON when the seed scripts generate
# them; non-broadcast staff (scouts, refs, etc.) have NULL bias. See
# _migrate_v3_8_0_add_staff_pundit_bias below.
#
# v3.7.0 (Stage 5 — Task Stage5-Final: Player settings) — MINOR bump.
# Adds the new `player_settings` table. Per CONVENTIONS §1.1, adding a
# new table is a MINOR bump. Per §5 (one table-group per task), this
# task adds ONLY the `player_settings` table — it is a single logical
# group (player preferences for the UI / sim — news feed filtering,
# auto-save cadence, difficulty, voice descriptors toggle). The
# player_settings table is a simple key-value store: one row per
# setting (PRIMARY KEY setting_key), with a TEXT setting_value + a
# timestamp. The migration seeds 6 default settings on first apply
# (idempotent via INSERT OR IGNORE). The src/player_settings.py module
# is the reader/writer (get_setting, set_setting, get_all_settings).
# This task also ships code-only changes that fix 6 stale personality
# fields (grit, ambition, loyalty, resilience, travel_comfort,
# fatigue_tolerance) in src/morale.py + src/career_arc.py — those are
# NOT schema changes (the columns already exist from v2.0.0); they're
# system extensions. And it ships the src/mods.py skeleton (Task 29 —
# code-only, no schema).
#
# Default settings seeded by the migration:
#   news_filter_topics          = 'all'
#   news_filter_min_importance  = '0'
#   news_volume                 = 'normal'
#   auto_save_frequency         = '30'
#   difficulty                  = 'normal'
#   display_descriptors         = 'true'
#
# Migration name: v3_7_0_add_player_settings.
#
# v3.6.0 (Stage 5 — Task 26 Show rating engine) — MINOR bump. Adds
# the new `show_ratings` table. Per CONVENTIONS §1.1, adding a new
# table is a MINOR bump. Per §5 (one table-group per task), this task
# adds ONLY the `show_ratings` table — it is a single logical group
# (Stories + Investment pillars of the Design Law §13) that captures
# the post-event fan / commercial / excitement / quality / overall
# ratings. Computed by src/show_rating.py (event-bus subscriber on
# EVENT_COMPLETED) — entirely event-bus-driven per CONVENTIONS §15.4
# (no inline side effects added to resolve_next_fight). The
# rating_description column stores a voice-layer descriptor (e.g.
# "an instant classic that fans will talk about for years") — NO raw
# rating numbers appear in player-facing text per CONVENTIONS §14.
#
# See docs/STAGES.md Task ID 26 for the brief and acceptance checklist.
# See docs/CONVENTIONS.md §14 (voice layer) + §15.4 (event bus).

# v3.5.0 (Phase C — Agent offers) — MINOR bump. Adds the new
# `agent_offers` table. Per CONVENTIONS §1.1, adding a new table is
# a MINOR bump. Per §5 (one table-group per task), this task adds
# ONLY the `agent_offers` table — it is a single logical group
# (Discovery pillar of the Design Law §13) that captures the agent's
# "mystery box" offer to the player: a vague description of an
# unknown talent (or washout veteran / style specialist / released
# contender / gamble prospect) with an asking price. The player sees
# only voice descriptors (career stage + style adjectives from
# voice.py) — NEVER raw attributes, potential, or career state per
# CONVENTIONS §14. The offer expires after 14 days; the player can
# sign (resolve_offer with accept=True) or reject.
#
# The src/agent_offers.py module writes offers (event-bus subscriber
# on TICK_ADVANCED — 10% chance per week, generates an offer for the
# player's promotion) and the resolve_offer helper signs the fighter
# (sets current_promotion_id + deducts asking_price from the
# promotion's current_cash). The news engine is NOT invoked on offer
# creation (the player sees the offer in the UI directly — no
# narrative needed for a "your agent calls you" moment). The expiry
# is silent too (the offer just disappears from the player's UI).
#
# Schema changes in this task:
#   1. New `agent_offers` table — 12 columns. One row per offer.
#      promotion_id + fighter_id are NOT NULL (every offer is for one
#      fighter to one promotion). offer_type is CHECK-constrained to
#      5 enumerated values ('unknown_talent', 'washout_veteran',
#      'style_specialist', 'contender_release', 'prospect_gamble').
#      is_resolved is 0/1 with resolution CHECK-constrained to
#      'signed' / 'rejected' / 'expired' (NULL only while unresolved).
#      asking_price is REAL (currency) — the price the player pays to
#      sign. expires_date is the offer's expiry date (offer_date +
#      14 days). fighter_description is the voice-layer-driven
#      "mystery box" text (NO raw numbers per §14).
#
# Code changes:
#   - New `src/agent_offers.py` — entirely event-bus-driven
#     (CONVENTIONS §15.4). Subscribes to TICK_ADVANCED (weekly —
#     _maybe_generate_offer with 10% chance per week +
#     _check_expired_offers that expires offers past expires_date).
#     resolve_offer is called directly by the UI (not a subscriber).
#   - Reader function: get_active_offers(conn, promotion_id) returns
#     the player's pending offers (UI tab will display them).
#
# Migration name: v3_5_0_add_agent_offers.
#
# v3.4.0 (Phase B — Suspensions + Seed-Time Rivalries/Social) — MINOR bump.


# v3.3.0 (Task 24 — Punditry / matchup analysis) — MINOR bump. Adds the
# new `matchup_analyses` table. Per CONVENTIONS §1.1, adding a new table
# is a MINOR bump. Per §5 (one table-group per task), this task adds
# ONLY the `matchup_analyses` table — it is a single logical group
# (Conflict + Anticipation pillars of the Design Law §13) that captures
# the pundit's pre-fight prediction for a fighter pair: predicted
# winner + method, confidence, style edge, excitement score, upset
# risk, and a full prose analysis_text (voice-layer-driven per §14 —
# NO raw attribute values, NO digit characters anywhere in the text).
#
# The brief mentioned 3 tables (pundit_segments + matchup_analysis +
# betting_odds), but per CONVENTIONS §5 (one table-group per task),
# this task adds ONLY `matchup_analyses`. The other two tables
# (pundit_segments for in-fight pundit commentary, betting_odds for
# the sportsbook line) are reserved for a follow-up task — the
# analysis_text column already carries the pundit's voice; a future
# task can add pundit_segments for round-by-round commentary and
# betting_odds for the implied probability line.
#
# Schema changes in this task:
#   1. New `matchup_analyses` table — 13 columns. One row per
#      (fighter_a_id, fighter_b_id, fight_id) triple (UNIQUE). The
#      analysis is generated retroactively after a fight resolves
#      (the FIGHT_RESOLVED subscriber writes the analysis as the
#      pundit's pre-fight prediction — the analysis describes the
#      pre-fight matchup, written after the fight for the news feed
#      so the player sees "here's what the pundits thought going
#      in"). predicted_winner + predicted_method are TEXT (fighter
#      full name + method label, NO raw numbers). confidence_pct +
#      excitement_score are 0-100 (CHECK BETWEEN 0 AND 100). style_edge
#      + upset_risk are TEXT (voice-layer-driven, NO raw numbers).
#      analysis_text is the full prose analysis (voice-layer-driven,
#      NO raw numbers per §14).
#
# Code changes:
#   - New `src/punditry.py` — entirely event-bus-driven (CONVENTIONS
#     §15.4). Subscribes to FIGHT_RESOLVED (_process_scheduled_fight).
#     The subscriber generates a matchup analysis as the pundit's pre-
#     fight prediction (using the pre-fight state — the analysis is
#     written retroactively after the fight resolves so it appears in
#     the news feed). Writes voice-layer-driven analysis_text
#     (CONVENTIONS §14 — no raw numbers in any text).
#   - Reader function: get_matchup_analysis(conn, fighter_a_id,
#     fighter_b_id, fight_id) returns the analysis row for a fight
#     (or None). Used by a future UI tab to surface pundit takes.
#
# Migration name: v3_3_0_add_matchup_analyses.
#
# v3.2.0 (Task 22 — Rivalries) — MINOR bump. Adds the new `rivalries`
# table (one row per pairwise rivalry between two fighters). Per
# CONVENTIONS §1.1, adding a new table is a MINOR bump. Per §5 (one
# table-group per task), this task adds ONLY the `rivalries` table —
# it is a single logical group (Conflict pillar of the Design Law §13)
# that builds on Task 21's `social_posts.is_beef_escalation` column
# (callouts + trash_talk between fighters seed rivalries) and the
# existing `fighters` + `fights` + `titles` tables.
#
# Schema changes in this task:
#   1. New `rivalries` table — 16 columns. One row per pairwise
#      rivalry between two fighters. The `rivalry_type` CHECK
#      constrains to 7 enumerated values ('callout', 'bad_blood',
#      'title_rivalry', 'rematch_hungry', 'style_clash',
#      'disrespect', 'stolen_opportunity'). `rivalry_heat` 0-100
#      drives fight-hype + aggression/composure modifiers.
#      `is_active` 0/1 marks whether the rivalry is still simmering
#      (inactive after both retire, or after a long quiet period).
#      UNIQUE (fighter_a_id, fighter_b_id) — one rivalry per pair
#      (fighter_a_id is always the lower fighter_id for canonical
#      ordering). FKs: both fighter columns NOT NULL ON DELETE
#      CASCADE.
#
# Code changes:
#   - New `src/rivalries.py` — entirely event-bus-driven (CONVENTIONS
#     §15.4). Subscribes to TICK_ADVANCED (_check_social_beefs),
#     FIGHT_RESOLVED (_process_fight_rivalry), and TITLE_CHANGED
#     (_process_title_rivalry). Writes voice-layer-driven origin
#     descriptions (CONVENTIONS §14 — no raw numbers in any text).
#   - Reader functions: get_rivalry(conn, a_id, b_id) returns the row
#     for a fighter pair (or None); get_active_rivalries(conn,
#     fighter_id) returns all active rivalries involving that fighter.
#     The fight engine (resolve_next_fight in app.py) is NOT modified
#     per the brief — the readers are provided for a future task to
#     consume.
#
# Rivalry heat escalation:
#   - Each callout/trash_talk social post between rivals: +5 heat
#   - Each fight between rivals: +15 heat
#   - Title fight between rivals: +25 heat
#   - Weight cut miss against a rival: +10 heat
#   - Apology social post: -10 heat
#   - Heat caps at 100 (CHECK constraint + code clamp)
#
# Migration name: v3_2_0_add_rivalries.
#
# v3.1.0 (Task 21 — Social media + beefs) — MINOR bump. Adds the new
# `social_posts` table. See the long comment block above the table
# definition for full details.


def _parse_version(v):
    """Parse a semver string 'MAJOR.MINOR.PATCH' into a tuple of ints.

    Each dotted component is parsed by extracting its leading digit
    prefix as an int. This means '1.0.0-beta' parses as (1, 0, 0) —
    the prerelease suffix '-beta' on the PATCH component is silently
    dropped. This is a deliberate simplification: in practice, schema
    versions are always plain MAJOR.MINOR.PATCH (no prereleases), and
    the brief explicitly allows 'pad and compare ints' handling for
    the '1.0.0-beta' edge case (see docs/STAGES.md Task ID 5 case 7,
    option A). Trade-off: '1.0.0-beta' compares equal to '1.0.0'.
    """
    nums = []
    for part in v.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        nums.append(int(digits) if digits else 0)
    return tuple(nums)


def _compare_versions(a, b):
    """Return -1 if a < b, 0 if a == b, +1 if a > b. Semver comparison.

    Splits on '.', compares each component as an int. Pads shorter
    tuples with zeros (so '1.3' == '1.3.0'). Correctly handles
    '1.10.0' > '1.9.0' (string comparison would get this wrong, which
    is the whole reason this helper exists).
    """
    ta, tb = _parse_version(a), _parse_version(b)
    # Pad to equal length (in case one has more components than the other).
    n = max(len(ta), len(tb))
    ta += (0,) * (n - len(ta))
    tb += (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def _read_on_disk_schema_version(db_path):
    """Return the on-disk schema_version string, or None if it cannot be read.

    Returns None when:
      - the DB file does not exist, or
      - the DB has no schema_meta table (prints a warning), or
      - schema_meta exists but has no row for schema_name='cage_empire'
        (prints a warning), or
      - the DB file is corrupt / unreadable (silent — treated as no
        version, allows rebuild).

    Uses mode=ro URI to open the DB read-only, which avoids creating
    WAL/journal files just for the version check and works cleanly on
    Windows where file locking is stricter. See docs/CONVENTIONS.md
    §1.4 (Task ID 5).
    """
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            )
            if cur.fetchone() is None:
                print(f"Warning: no schema_meta table in {db_path} — "
                      f"proceeding with rebuild (treating as pre-versioning DB).")
                return None
            row = conn.execute(
                "SELECT schema_version FROM schema_meta WHERE schema_name=?",
                ("cage_empire",),
            ).fetchone()
            if row is None:
                print(f"Warning: schema_meta exists but no row for "
                      f"schema_name='cage_empire' — proceeding with rebuild.")
                return None
            return row[0]
    except sqlite3.DatabaseError:
        # Corrupt or unreadable DB — treat as no version, allow rebuild.
        return None


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------
-- Schema meta & versioning (restored in v1.2.1, see
-- docs/CONVENTIONS.md §1 for the rules).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    schema_name    TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    -- v3.36.0 (TIER3-MISSING §T3.3 / W42) — provenance metadata.
    -- Both columns are nullable so old save files that predate the
    -- migration can still be loaded (the columns will be NULL until
    -- the next save writes them).
    --   world_version — set on each save (e.g. "sim_2026-08-27_tick14")
    --   seed_version  — set on fresh DB build (e.g. "world_seed_v1")
    world_version  TEXT,
    seed_version   TEXT,
    created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS simulation_clock (
    clock_id INTEGER PRIMARY KEY CHECK (clock_id = 1),
    current_date TEXT NOT NULL,
    current_day INTEGER NOT NULL,
    current_week INTEGER NOT NULL,
    current_month INTEGER NOT NULL,
    current_year INTEGER NOT NULL,
    current_tick_type TEXT NOT NULL DEFAULT 'day',
    tick_counter INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS nations (
    nation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    language TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS regions (
    region_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    name TEXT NOT NULL UNIQUE,
    style_preferences TEXT,
    fan_preferences TEXT,
    market_growth INTEGER NOT NULL DEFAULT 50 CHECK (market_growth BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS weight_classes (
    weight_class_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT 'male' CHECK (gender IN ('male', 'female')),
    min_weight_kg REAL,
    max_weight_kg REAL,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (name, gender)
);

CREATE TABLE IF NOT EXISTS cities (
    city_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    population INTEGER,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (nation_id, name)
);

CREATE TABLE IF NOT EXISTS markets (
    market_id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL UNIQUE REFERENCES cities(city_id) ON DELETE CASCADE,
    market_type TEXT NOT NULL DEFAULT 'standard',
    heat_level INTEGER NOT NULL DEFAULT 50 CHECK (heat_level BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    -- v3.18.0 (Phase E2.7 — tiered venue rental per §3.2.3). Drives
    -- the cost_per_seat_by_venue_type tiered lookup in finance.py.
    -- 4 values: arena (cap 15k+), ballroom (5-15k), theater (2-5k),
    -- outdoor (<2k). NOT NULL with DEFAULT 'ballroom' so existing
    -- INSERTs that don't set venue_type get the mid-tier value
    -- (matches the spec's "Default existing venues to 'ballroom'").
    venue_type TEXT NOT NULL DEFAULT 'ballroom'
        CHECK (venue_type IN ('arena', 'ballroom', 'theater', 'outdoor')),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS promotions (
    promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    size_tier TEXT NOT NULL DEFAULT 'small',
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    current_cash REAL NOT NULL DEFAULT 0,
    reputation INTEGER NOT NULL DEFAULT 50 CHECK (reputation BETWEEN 0 AND 100),
    fan_trust INTEGER NOT NULL DEFAULT 50 CHECK (fan_trust BETWEEN 0 AND 100),
    -- 6 new columns added v2.0.0 (Task 14.6). These were flagged as
    -- THIN in SCHEMA_DRIFT_AUDIT.md §Z.4 and are needed by:
    --   - Task 25 (rival promotion AI) — ai_aggression + ai_spending_style
    --   - Task 20 (finances) + Task 26 (show rating) — broadcast_tier
    --   - Task 23 (news engine) — brand_tone for promotion voice
    -- brand_tone + broadcast_tier + ownership_type + ai_spending_style
    -- are TEXT with no CHECK constraint (allowed values are open-ended
    -- for future expansion); ai_aggression has a CHECK (0-100) like the
    -- other 0-100 promotion columns above.
    brand_tone TEXT NOT NULL DEFAULT 'standard',
    starting_budget REAL NOT NULL DEFAULT 0,
    broadcast_tier TEXT NOT NULL DEFAULT 'local_stream',
    ownership_type TEXT NOT NULL DEFAULT 'startup',
    ai_aggression INTEGER NOT NULL DEFAULT 50 CHECK (ai_aggression BETWEEN 0 AND 100),
    ai_spending_style TEXT NOT NULL DEFAULT 'balanced',
    -- v3.14.0 (Task RIVAL-AI-P1 — Rival AI Phase 1 Foundation): 3 new
    -- columns for the rival AI archetype system per docs/RIVAL_AI_
    -- ARCHITECTURE.md §7.2. All nullable so the migration can add
    -- them without backfilling at migration time — the rival AI's
    -- first TICK_ADVANCED subscriber call assigns the archetype +
    -- scheduling day + initial budget state (see services/rival_ai/
    -- archetypes.py assign_all_archetypes).
    --   ai_archetype              — 'major_league' / 'regional_power' /
    --                               'grassroots' / 'rising_star' (NULL =
    --                               not yet assigned).
    --   ai_scheduling_day_of_week — 1-7 Mon-Sun (NULL = not yet
    --                               assigned). Spreads rival promos
    --                               across the week per arch doc §4.2.
    --   ai_budget_state           — 'SURVIVAL' / 'CONSERVATIVE' /
    --                               'NORMAL' / 'EXPANSION' / 'CRISIS'
    --                               (NULL = not yet assigned; first
    --                               tick sets 'NORMAL'). Phase 3's
    --                               budget_manager adjusts monthly.
    ai_archetype TEXT,
    ai_scheduling_day_of_week INTEGER,
    ai_budget_state TEXT,
    -- v3.23.0 (Fix 2 — Bankruptcy Recovery per docs/DESIGN_REVIEW_E5.md
    -- §2). Two new columns tracking the "new ownership" rebuilding
    -- period that follows a bankruptcy failure state. When
    -- is_rebuilding=1, the promo is under new ownership and slowly
    -- recovering reputation month-by-month while it runs events.
    --   is_rebuilding          INTEGER (0 or 1; default 0). Set to 1
    --                          by _fire_bankruptcy_failure when the
    --                          bankruptcy failure state fires, cleared
    --                          by _check_rebuilding_status when the
    --                          6-month rebuilding period ends.
    --   rebuilding_until_date  TEXT (ISO 'YYYY-MM-DD'). The sim date
    --                          6 months after the bankruptcy firing —
    --                          the rebuild is complete on/after this
    --                          date.
    is_rebuilding INTEGER NOT NULL DEFAULT 0 CHECK (is_rebuilding IN (0, 1)),
    rebuilding_until_date TEXT,
    -- v3.27.0 (HW1.4 — Financial State Machine per docs/Hardening_
    -- Phase.md §HW1.4). The 7-state lifecycle column. Default
    -- 'HEALTHY'. CHECK enforces the 7 allowed values:
    --   HEALTHY    → cash comfortable (>= starting_budget × 0.20)
    --   PRESSURED  → cash < 0.20 × starting_budget for 2 months
    --   STRUGGLING → cash < 0.10 × starting_budget for 2 months
    --   CRISIS     → cash < 0 for 1 month
    --   BANKRUPT   → cash < 0 for 3 consecutive months (transient —
    --                immediately transitions to REBUILDING via
    --                _fire_bankruptcy_failure)
    --   REBUILDING → 6-month post-bankruptcy recovery (is_rebuilding=1)
    --   RECOVERING → rebuilding period complete, cash climbing back
    --                toward starting_budget × 0.50
    -- The state machine is implemented in src/reputation.py
    -- (_check_financial_state_transitions), called monthly on
    -- TICK_ADVANCED. Each transition writes a voice-compliant news
    -- item + applies a consequence (PRESSURED = -10% marketing spend
    -- on next event; STRUGGLING = release 1 staff; CRISIS = block FA
    -- signings; etc.).
    financial_state TEXT NOT NULL DEFAULT 'HEALTHY'
        CHECK (financial_state IN (
            'HEALTHY', 'PRESSURED', 'STRUGGLING', 'CRISIS',
            'BANKRUPT', 'REBUILDING', 'RECOVERING'
        )),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS gyms (
    gym_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    city_id INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    -- 8 new columns added v2.0.0 (Task 14.6). Flagged THIN in
    -- SCHEMA_DRIFT_AUDIT.md §C — needed by Task 16 (training camps)
    -- and Task 17 (weight cuts). All 5 INTEGER columns have CHECK
    -- (0-100) like the other 0-100 gym-relevant columns. culture_tone
    -- is open-ended TEXT (future values: 'disciplined', 'loose',
    -- 'predator', etc.). membership_cost is REAL (currency, in
    -- dollars) — Task 20 finances will use it.
    reputation INTEGER NOT NULL DEFAULT 50 CHECK (reputation BETWEEN 0 AND 100),
    membership_cost REAL NOT NULL DEFAULT 0,
    facility_quality INTEGER NOT NULL DEFAULT 50 CHECK (facility_quality BETWEEN 0 AND 100),
    medical_support INTEGER NOT NULL DEFAULT 50 CHECK (medical_support BETWEEN 0 AND 100),
    sparring_depth INTEGER NOT NULL DEFAULT 50 CHECK (sparring_depth BETWEEN 0 AND 100),
    development_focus INTEGER NOT NULL DEFAULT 50 CHECK (development_focus BETWEEN 0 AND 100),
    culture_tone TEXT NOT NULL DEFAULT 'balanced',
    weight_cut_support INTEGER NOT NULL DEFAULT 50 CHECK (weight_cut_support BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS style_archetypes (
    style_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    -- attribute_bias (added v2.0.0, Task 14.5) holds a JSON dict
    -- mapping attribute names to +/- integer bias values, e.g.
    -- {"punch_power": 15, "takedown_defense": -10}. Used by
    -- fighter_gen.generate_attribute_block(archetype_id, conn) when
    -- generating new fighters (regen) or backfilling existing ones.
    -- Nullable — old code that doesn't set it gets NULL, which
    -- fighter_gen treats as "no bias" (equivalent to {}).
    -- See docs/STAGES.md §14.5 for the 7 seeded bias values.
    attribute_bias TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS personality_archetypes (
    personality_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    -- trait_bias (added v2.0.0, Task 14.5) — symmetric to
    -- style_archetypes.attribute_bias but for personality fields.
    -- Used by fighter_gen.generate_personality_block(archetype_id, conn).
    trait_bias TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighters (
    fighter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    nickname TEXT,
    gender TEXT NOT NULL DEFAULT 'unknown',
    date_of_birth TEXT NOT NULL,
    birth_city_id INTEGER REFERENCES cities(city_id) ON DELETE SET NULL,
    birth_nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    residence_city_id INTEGER REFERENCES cities(city_id) ON DELETE SET NULL,
    residence_nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    weight_class_id INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,
    current_gym_id INTEGER REFERENCES gyms(gym_id) ON DELETE SET NULL,
    current_promotion_id INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    fight_style_archetype_id INTEGER REFERENCES style_archetypes(style_archetype_id) ON DELETE SET NULL,
    personality_archetype_id INTEGER REFERENCES personality_archetypes(personality_archetype_id) ON DELETE SET NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    is_retired INTEGER NOT NULL DEFAULT 0 CHECK (is_retired IN (0,1)),
    -- 14 new columns added v2.0.0 (Task 14.6). Flagged THIN in
    -- SCHEMA_DRIFT_AUDIT.md §Z.3. Needed by:
    --   - Task 15 (injuries) — injury_proneness
    --   - Task 17 (weight cuts) — weight_cut_difficulty
    --   - Task 19 (voice layer) — height_cm, reach_cm, stance,
    --     handedness, marketability, fan_friendliness
    --   - Task 20 (finances) + Task 26 (show rating) — marketability,
    --     fan_friendliness, promo_boost
    --   - Death/career-end system — is_deceased
    --   - Task 24 (matchup analysis) — preferred_gameplans,
    --     bad_matchup_tags (JSON arrays)
    -- height_cm and reach_cm are nullable INTEGER (no CHECK) — a
    -- future regen or import path might not have these. stance and
    -- handedness have CHECK constraints matching the brief. The 6
    -- 0-100 INTEGER columns follow the same pattern as the existing
    -- is_active/is_retired CHECK columns. promo_boost is the only
    -- column that allows -100..100 (it's a delta, not a 0-100 score).
    -- preferred_gameplans and bad_matchup_tags are TEXT (JSON arrays);
    -- NULL is allowed and means "no preference" / "no known bad
    -- matchups" respectively.
    height_cm INTEGER,
    reach_cm INTEGER,
    stance TEXT CHECK (stance IN ('orthodox','southpaw','switch')),
    handedness TEXT CHECK (handedness IN ('right','left','ambidextrous')),
    injury_proneness INTEGER NOT NULL DEFAULT 50 CHECK (injury_proneness BETWEEN 0 AND 100),
    weight_cut_difficulty INTEGER NOT NULL DEFAULT 50 CHECK (weight_cut_difficulty BETWEEN 0 AND 100),
    consistency INTEGER NOT NULL DEFAULT 50 CHECK (consistency BETWEEN 0 AND 100),
    clutch_factor INTEGER NOT NULL DEFAULT 50 CHECK (clutch_factor BETWEEN 0 AND 100),
    marketability INTEGER NOT NULL DEFAULT 50 CHECK (marketability BETWEEN 0 AND 100),
    fan_friendliness INTEGER NOT NULL DEFAULT 50 CHECK (fan_friendliness BETWEEN 0 AND 100),
    promo_boost INTEGER NOT NULL DEFAULT 0 CHECK (promo_boost BETWEEN -100 AND 100),
    preferred_gameplans TEXT,
    bad_matchup_tags TEXT,
    is_deceased INTEGER NOT NULL DEFAULT 0 CHECK (is_deceased IN (0,1)),
    -- v3.19.0 (DB-REVIEW-IMAGE-ASSIGNMENT): relative path to the
    -- fighter's portrait image, e.g.
    -- 'portraits/batch_001-020/batch_001-020/0001_HirokiNakamura_Mist.webp'
    -- (relative to the data/ directory). NULL for fighters without a
    -- custom portrait (the UI renders an initial-letter placeholder).
    -- Per user directive: image never changes once assigned — regens
    -- get a fresh fighter_id (see regen_lineage), so the cached base64
    -- payload stays valid for the lifetime of the fighter_id.
    portrait_path TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_attributes (
    fighter_attribute_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    -- Existing 4 attributes (preserved across the v2.0.0 migration —
    -- their values are NOT touched by the backfill). No CHECK
    -- constraint is added retroactively, to avoid breaking existing
    -- tests that UPDATE these columns with arbitrary values like
    -- 90/30/50 (test_fight_resolver, test_fight_history, etc.).
    punch_power INTEGER NOT NULL DEFAULT 50,
    cardio INTEGER NOT NULL DEFAULT 50,
    fight_iq INTEGER NOT NULL DEFAULT 50,
    chin INTEGER NOT NULL DEFAULT 50,
    -- 21+ new attributes added v2.0.0 (Task 14.5). All CHECK (0-100)
    -- per the brief — these are NEW columns so adding CHECK constraints
    -- is safe (no existing data to violate). The fighter_gen module
    -- generates values via clamp(50 + bias + noise), so they will
    -- always satisfy the CHECK. The 5 groups per STAGES.md §14.5:
    --   Striking:  punch_accuracy, kick_power, kick_accuracy, head_movement
    --   Range:     footwork, clinch_striking, clinch_offense, clinch_defense
    --   Grappling: takedown_offense, takedown_defense, top_control,
    --              bottom_game, submission_offense, submission_defense,
    --              scramble_ability, cage_wrestling
    --   Physical:  recovery_rate, speed_explosiveness, strength,
    --              durability, flexibility
    --   Mental:    adaptability
    -- Note: the brief says "21 new columns" but the column-name list
    -- contains 22 names (4+4+8+5+1=22). Implemented all 22 from the
    -- list — the column-name list is the authoritative spec. The
    -- "21" in the brief's prose is an off-by-one typo. See worklog
    -- decision D1 for the full explanation.
    punch_accuracy INTEGER NOT NULL DEFAULT 50 CHECK (punch_accuracy BETWEEN 0 AND 100),
    kick_power INTEGER NOT NULL DEFAULT 50 CHECK (kick_power BETWEEN 0 AND 100),
    kick_accuracy INTEGER NOT NULL DEFAULT 50 CHECK (kick_accuracy BETWEEN 0 AND 100),
    head_movement INTEGER NOT NULL DEFAULT 50 CHECK (head_movement BETWEEN 0 AND 100),
    footwork INTEGER NOT NULL DEFAULT 50 CHECK (footwork BETWEEN 0 AND 100),
    clinch_striking INTEGER NOT NULL DEFAULT 50 CHECK (clinch_striking BETWEEN 0 AND 100),
    clinch_offense INTEGER NOT NULL DEFAULT 50 CHECK (clinch_offense BETWEEN 0 AND 100),
    clinch_defense INTEGER NOT NULL DEFAULT 50 CHECK (clinch_defense BETWEEN 0 AND 100),
    takedown_offense INTEGER NOT NULL DEFAULT 50 CHECK (takedown_offense BETWEEN 0 AND 100),
    takedown_defense INTEGER NOT NULL DEFAULT 50 CHECK (takedown_defense BETWEEN 0 AND 100),
    top_control INTEGER NOT NULL DEFAULT 50 CHECK (top_control BETWEEN 0 AND 100),
    bottom_game INTEGER NOT NULL DEFAULT 50 CHECK (bottom_game BETWEEN 0 AND 100),
    submission_offense INTEGER NOT NULL DEFAULT 50 CHECK (submission_offense BETWEEN 0 AND 100),
    submission_defense INTEGER NOT NULL DEFAULT 50 CHECK (submission_defense BETWEEN 0 AND 100),
    scramble_ability INTEGER NOT NULL DEFAULT 50 CHECK (scramble_ability BETWEEN 0 AND 100),
    cage_wrestling INTEGER NOT NULL DEFAULT 50 CHECK (cage_wrestling BETWEEN 0 AND 100),
    recovery_rate INTEGER NOT NULL DEFAULT 50 CHECK (recovery_rate BETWEEN 0 AND 100),
    speed_explosiveness INTEGER NOT NULL DEFAULT 50 CHECK (speed_explosiveness BETWEEN 0 AND 100),
    strength INTEGER NOT NULL DEFAULT 50 CHECK (strength BETWEEN 0 AND 100),
    durability INTEGER NOT NULL DEFAULT 50 CHECK (durability BETWEEN 0 AND 100),
    flexibility INTEGER NOT NULL DEFAULT 50 CHECK (flexibility BETWEEN 0 AND 100),
    adaptability INTEGER NOT NULL DEFAULT 50 CHECK (adaptability BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_personality (
    fighter_personality_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    -- Existing 3 personality fields (preserved across the v2.0.0
    -- migration — their values are NOT touched by the backfill). No
    -- CHECK constraint added retroactively, to avoid breaking existing
    -- tests that UPDATE these columns (test_fight_resolver, etc.).
    aggression INTEGER NOT NULL DEFAULT 50,
    composure INTEGER NOT NULL DEFAULT 50,
    morale INTEGER NOT NULL DEFAULT 50,
    -- 17 new personality fields added v2.0.0 (Task 14.5). All CHECK
    -- (0-100). The 4 groups per STAGES.md §14.5:
    --   Temperament: risk_taking, killer_instinct, grit, discipline, patience
    --   Career:      ambition, loyalty, charisma, attention_seeking,
    --                coachability, professionalism
    --   Resilience:  ego, resilience, sportsmanship, travel_comfort
    --   Dynamic:     focus, fatigue_tolerance
    risk_taking INTEGER NOT NULL DEFAULT 50 CHECK (risk_taking BETWEEN 0 AND 100),
    killer_instinct INTEGER NOT NULL DEFAULT 50 CHECK (killer_instinct BETWEEN 0 AND 100),
    grit INTEGER NOT NULL DEFAULT 50 CHECK (grit BETWEEN 0 AND 100),
    discipline INTEGER NOT NULL DEFAULT 50 CHECK (discipline BETWEEN 0 AND 100),
    patience INTEGER NOT NULL DEFAULT 50 CHECK (patience BETWEEN 0 AND 100),
    ambition INTEGER NOT NULL DEFAULT 50 CHECK (ambition BETWEEN 0 AND 100),
    loyalty INTEGER NOT NULL DEFAULT 50 CHECK (loyalty BETWEEN 0 AND 100),
    charisma INTEGER NOT NULL DEFAULT 50 CHECK (charisma BETWEEN 0 AND 100),
    attention_seeking INTEGER NOT NULL DEFAULT 50 CHECK (attention_seeking BETWEEN 0 AND 100),
    coachability INTEGER NOT NULL DEFAULT 50 CHECK (coachability BETWEEN 0 AND 100),
    professionalism INTEGER NOT NULL DEFAULT 50 CHECK (professionalism BETWEEN 0 AND 100),
    ego INTEGER NOT NULL DEFAULT 50 CHECK (ego BETWEEN 0 AND 100),
    resilience INTEGER NOT NULL DEFAULT 50 CHECK (resilience BETWEEN 0 AND 100),
    sportsmanship INTEGER NOT NULL DEFAULT 50 CHECK (sportsmanship BETWEEN 0 AND 100),
    travel_comfort INTEGER NOT NULL DEFAULT 50 CHECK (travel_comfort BETWEEN 0 AND 100),
    focus INTEGER NOT NULL DEFAULT 50 CHECK (focus BETWEEN 0 AND 100),
    fatigue_tolerance INTEGER NOT NULL DEFAULT 50 CHECK (fatigue_tolerance BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fighter_career (
    fighter_career_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id INTEGER NOT NULL UNIQUE REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    record_wins INTEGER NOT NULL DEFAULT 0,
    record_losses INTEGER NOT NULL DEFAULT 0,
    record_draws INTEGER NOT NULL DEFAULT 0,
    win_streak INTEGER NOT NULL DEFAULT 0,
    loss_streak INTEGER NOT NULL DEFAULT 0,
    career_health INTEGER NOT NULL DEFAULT 100,
    -- v2.0.1 (Task pre-B1-fixes): `potential` is the fighter's growth
    -- ceiling. Training camps (Task 16, future) will push attributes
    -- toward this ceiling with diminishing returns as they approach
    -- it. Without this column, every fighter has unlimited growth
    -- potential and the Talent Hunter fantasy (CAGE_EMPIRE_SOUL.md
    -- Fantasy 1) collapses — a journeyman could theoretically train
    -- every attribute to 100. The DEFAULT 50 keeps existing rows
    -- valid; new fighters get potential from
    -- fighter_gen.generate_potential() (10% elite 70-90, 30% solid
    -- 50-69, 60% limited 25-49).
    potential INTEGER NOT NULL DEFAULT 50 CHECK (potential BETWEEN 0 AND 100),
    -- v2.0.1 (Task pre-B1-fixes): `title_reigns` counts how many
    -- title reigns this fighter has had. Incremented by
    -- _resolve_title_after_fight() in app.py every time the fighter
    -- wins a title (vacant title claimed OR reigning champion
    -- dethroned). The retirement path reads this to decide whether
    -- to create a fighter_memory_links 'successor' row — only
    -- fighters who held a title get the "reminiscent of former
    -- champion {name}" treatment.
    title_reigns INTEGER NOT NULL DEFAULT 0 CHECK (title_reigns >= 0),
    -- CR-M1 (docs/MASTER_PLAN_MATCHMAKING.md §2.1): `realization` is a
    -- 0.4-1.0 multiplier on effective_ceiling. Represents how close a
    -- fighter gets to their theoretical potential. Set at fighter
    -- creation from personality — NOT every fighter hits their peak.
    -- A "bust" (realization=0.5) with potential=85 has ceiling=42.
    realization REAL NOT NULL DEFAULT 0.7 CHECK (realization BETWEEN 0.4 AND 1.0),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS staff (
    staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    age INTEGER NOT NULL,
    nation_id INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    role_type TEXT NOT NULL,
    specialty TEXT,
    promotion_id INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    -- v3.9.0 (Phase 1.5 Fix C6): staff.gym_id is the coach-gym linkage.
    -- For role_type='coach' rows, this points to the gym where the
    -- coach is resident. NULL for non-coach staff (broadcast, scouts,
    -- refs, cutmen, doctors, GMs) — those are promotion-affiliated
    -- via promotion_id, not gym-affiliated. The seed script
    -- (scripts/group_c_seed.py) back-fills gym_id for existing
    -- coaches (match by nation_id). Per CONVENTIONS §5.3, the writer
    -- is scripts/group_c_seed.py + future coach-generation seed
    -- scripts; the reader is the upcoming training-camps UI screen
    -- (which displays the coach alongside the fighter's gym).
    gym_id INTEGER REFERENCES gyms(gym_id) ON DELETE SET NULL,
    -- v3.8.0 (Stage 6 prep — D-GUI-4): pundit_bias JSON stores a
    -- broadcast pundit's per-attribute bias so the Fight Resolution
    -- screen can render named-pundit interjections that favour
    -- strikers / grapplers / veterans / prospects / nations / gyms.
    -- NULL for non-broadcast staff (scouts, refs, etc.). The JSON
    -- schema is documented in src/punditry.py. NO CHECK constraint
    -- because SQLite CHECK can't validate JSON shape. Per
    -- CONVENTIONS §5.3, the writer is src/punditry.py (writes bias
    -- when generating matchup_analyses) and the reader is the
    -- upcoming ui/screens/event_resolution.py screen.
    pundit_bias TEXT,
    -- v3.22.0 (Phase E4 — Staff Market, per docs/ECON_STAFF_PLAN.md
    -- §4.2 + §4.3 + task brief). Three new columns drive the Staff
    -- Market screen (free-agent pool of coaches / scouts / doctors
    -- / cutmen / GMs / commentators):
    --   skill_level          INTEGER 0-100 (overall competence).
    --     Displayed via voice phrase ('world-class' / 'established'
    --     / 'promising' / 'unproven') — NEVER the raw int.
    --   salary_ask           REAL — the salary the staff expects in
    --     $/yr. Drives the negotiation threshold (offer must clear
    --     salary_ask × 0.9).
    --   contract_length_ask  INTEGER — desired contract length in
    --     years (1-5). Drives the default contract_length slider.
    -- Defaults: skill_level=50 ('promising'), salary_ask=50000,
    -- contract_length_ask=2. Existing staff backfilled by the
    -- migration function (_migrate_v3_22_0_add_staff_market_columns)
    -- using a role + skill-tier salary table (see §4.1 of the plan).
    skill_level INTEGER NOT NULL DEFAULT 50
        CHECK (skill_level BETWEEN 0 AND 100),
    salary_ask REAL NOT NULL DEFAULT 50000.0,
    contract_length_ask INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS broadcast_staff (
    broadcast_staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL UNIQUE REFERENCES staff(staff_id) ON DELETE CASCADE,
    on_air_role TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    venue_id INTEGER NOT NULL REFERENCES venues(venue_id) ON DELETE RESTRICT,
    market_id INTEGER NOT NULL REFERENCES markets(market_id) ON DELETE RESTRICT,
    event_name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    -- v3.21.0 (Phase E3.1 — Player Financial Levers per docs/PHASE_E3_PLAN.md
    -- §1.E3.1 + docs/ECON_STAFF_PLAN.md §3.3). 4 player-set lever columns
    -- that drive the finance model (Phase E3.2 reads them in
    -- finance._process_event_finance). Defaults preserve backward
    -- compatibility for existing events (pre-E3 events use defaults:
    -- ticket_price=80, marketing_spend=0, ppv_price=60, is_ppv=0).
    ticket_price INTEGER NOT NULL DEFAULT 80,        -- $20-$300
    marketing_spend INTEGER NOT NULL DEFAULT 0,      -- $0-$500k
    ppv_price INTEGER NOT NULL DEFAULT 60,           -- $30-$80 (PPV events only)
    is_ppv INTEGER NOT NULL DEFAULT 0 CHECK (is_ppv IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fights (
    fight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    weight_class_id INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE RESTRICT,
    -- `bout_type` is DEPRECATED as of v2.2.0 (Task pre-B2-fix). It was
    -- doing double duty (card position AND title-fight flag) which a
    -- single TEXT column cannot express — a fight can be a main event
    -- AND a title fight. The two new columns below split the concept:
    --   - `card_slot` — pure card position (main_event/co_main/
    --     featured_prelim/prelim/opener).
    --   - `is_title_fight` — pure title-fight flag (0/1).
    -- `bout_type` is kept for backward compatibility (no MAJOR bump,
    -- no backfill migration) but new code MUST read card_slot +
    -- is_title_fight instead. The existing seed still sets
    -- bout_type='title_fight' for the seeded title fight and
    -- bout_type='main_event' for auto-scheduled fights — these values
    -- are now redundant with is_title_fight but are kept so any
    -- external reader that still checks bout_type keeps working.
    bout_type TEXT NOT NULL,
    -- 2 new columns added v2.2.0 (Task pre-B2-fix). Both have CHECK
    -- constraints (safe — these are NEW columns so no existing data
    -- can violate them). `card_slot` defaults to 'main_event' so
    -- existing INSERTs that don't specify a card_slot get the most
    -- common value; `is_title_fight` defaults to 0 so existing
    -- INSERTs that don't specify it get the safer non-title-fight
    -- value. The seed (seed_data.py) and schedule_next_event (app.py)
    -- explicitly set both columns on every INSERT so the defaults are
    -- only a safety net for ad-hoc / external INSERTs.
    card_slot TEXT NOT NULL DEFAULT 'main_event' CHECK (card_slot IN ('main_event','co_main','featured_prelim','prelim','opener')),
    is_title_fight INTEGER NOT NULL DEFAULT 0 CHECK (is_title_fight IN (0,1)),
    round_limit INTEGER NOT NULL DEFAULT 3,
    scheduled_rounds INTEGER NOT NULL DEFAULT 3,
    winner_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    loser_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    result_type TEXT,
    finish_round INTEGER,
    finish_time TEXT,
    performance_rating INTEGER,
    fan_reaction_rating INTEGER,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS fight_participants (
    fight_participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE RESTRICT,
    corner TEXT NOT NULL,
    is_winner INTEGER NOT NULL DEFAULT 0 CHECK (is_winner IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, fighter_id)
);

CREATE TABLE IF NOT EXISTS event_cards (
    event_card_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    fight_id INTEGER NOT NULL UNIQUE REFERENCES fights(fight_id) ON DELETE CASCADE,
    card_position INTEGER NOT NULL,
    card_tier TEXT NOT NULL,
    is_main_event INTEGER NOT NULL DEFAULT 0 CHECK (is_main_event IN (0,1)),
    -- 1 new column added v2.2.0 (Task pre-B2-fix). Symmetric to the
    -- existing `is_main_event` column. Was in the v1.6 spec but
    -- missing from the original build (flagged THIN in
    -- SCHEMA_DRIFT_AUDIT.md §G). The DEFAULT 0 keeps existing rows
    -- valid; the seed and schedule_next_event both explicitly set
    -- is_co_main=0 (the seeded and auto-scheduled main events are
    -- main events, not co-mains). Future booking UI (Task B2+ will
    -- read this to identify the second-biggest fight on the card).
    is_co_main INTEGER NOT NULL DEFAULT 0 CHECK (is_co_main IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS news_sources (
    news_source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    credibility INTEGER NOT NULL DEFAULT 50,
    sensationalism INTEGER NOT NULL DEFAULT 50,
    bias INTEGER NOT NULL DEFAULT 50,
    regional_reach INTEGER NOT NULL DEFAULT 50,
    reliability INTEGER NOT NULL DEFAULT 50,
    frequency INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS news_items (
    news_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_source_id INTEGER NOT NULL REFERENCES news_sources(news_source_id) ON DELETE RESTRICT,
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    sentiment TEXT NOT NULL DEFAULT 'neutral',
    topic TEXT NOT NULL,
    event_id INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    promotion_id INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    published_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    -- HW4.1 (docs/Hardening_Phase.md §HW4.1 / W19) — importance tier.
    -- 5 tiers: LEGENDARY (title change, HoF, career-ending injury),
    -- MAJOR (signing, retirement, major upset, rivalry escalation),
    -- SIGNIFICANT (fight result, injury, suspension, comeback),
    -- ROUTINE (training camp, finance, weight cut, event hype),
    -- BACKGROUND (tapping_up_rumor, social media, generic). Daily
    -- caps per tier enforced in news._write_news_item (HW4.3): 1
    -- LEGENDARY / 3 MAJOR / 5 SIGNIFICANT / 10 ROUTINE / 5 BACKGROUND.
    importance TEXT NOT NULL DEFAULT 'ROUTINE'
        CHECK (importance IN ('LEGENDARY','MAJOR','SIGNIFICANT',
                              'ROUTINE','BACKGROUND')),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS commentary_segments (
    commentary_segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
    fight_id INTEGER REFERENCES fights(fight_id) ON DELETE CASCADE,
    segment_type TEXT NOT NULL,
    speaker_staff_id INTEGER REFERENCES staff(staff_id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- fight_history (added in v1.3.0, Task ID 4).
-- Per-fighter, per-fight history row — separate from the mutable
-- `fighter_career` counters. Two rows are written per resolved fight
-- (one per fighter, from their perspective). Required by upcoming
-- rankings, legacy, and stats-based commentary work (Tasks 10, 11,
-- 14, 19, 23) — reconstructing it later from `record_wins` would be
-- impossible. See docs/STAGES.md Task ID 4 for the brief.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fight_history (
    fight_history_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id           INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    fighter_id         INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    opponent_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    outcome            TEXT NOT NULL CHECK (outcome IN ('win','loss','draw','nc')),
    result_type        TEXT,
    finish_round       INTEGER,
    finish_time        TEXT,
    score_margin       INTEGER,
    event_id           INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    event_date         TEXT,
    weight_class_id    INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,
    title_at_stake     INTEGER NOT NULL DEFAULT 0 CHECK (title_at_stake IN (0,1)),
    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, fighter_id)
);

-- ----------------------------------------------------------------
-- Contracts (added in v1.4.0, Task ID 9).
-- 4 tables: contracts (polymorphic base) + fighter_contracts +
-- staff_contracts + broadcast_contracts (subtype tables). The base
-- table holds the common fields (promotion_id, dates, salary,
-- exclusivity, status); the subtype tables hold the FK to the
-- contracted entity (fighter / staff / broadcast_staff).
-- Polymorphic-association pattern: contracts.contract_target_type
-- is 'fighter' / 'staff' / 'broadcast', and the corresponding
-- subtype table has the FK. This avoids a single nullable FK column
-- on the base table (which would have no FK constraint).
-- See docs/SCHEMA_DRIFT_AUDIT.md §F and docs/STAGES.md Task ID 9.
-- Foundation for Task ID 13 (free agency + signings) and Task ID 25
-- (rival promotion AI poaching).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contracts (
    contract_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_target_type TEXT NOT NULL CHECK (contract_target_type IN ('fighter', 'staff', 'broadcast')),
    promotion_id         INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    start_date           TEXT NOT NULL,
    end_date             TEXT NOT NULL,
    salary               REAL NOT NULL DEFAULT 0 CHECK (salary >= 0),
    bonus_structure      TEXT,
    buyout_clause        REAL,
    exclusive_flag       INTEGER NOT NULL DEFAULT 1 CHECK (exclusive_flag IN (0, 1)),
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'terminated', 'renegotiating')),
    created_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS fighter_contracts (
    fighter_contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         INTEGER NOT NULL UNIQUE REFERENCES contracts(contract_id) ON DELETE CASCADE,
    fighter_id          INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    contract_type       TEXT NOT NULL DEFAULT 'standard' CHECK (contract_type IN ('standard', 'champion', 'prospect', 'veteran')),
    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS staff_contracts (
    staff_contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id       INTEGER NOT NULL UNIQUE REFERENCES contracts(contract_id) ON DELETE CASCADE,
    staff_id          INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    contract_role     TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS broadcast_contracts (
    broadcast_contract_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id           INTEGER NOT NULL UNIQUE REFERENCES contracts(contract_id) ON DELETE CASCADE,
    staff_id              INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    network_name          TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- Rankings (added in v1.5.0, Task ID 10).
-- One row per fighter per weight class per promotion. Auto-updated
-- on fight resolution by `_update_rankings_after_resolution()` in
-- app.py using a simple ELO-style rating system (K=32, zero-sum).
-- Foundation for Task ID 11 (titles — champion vs #1 contender),
-- Task ID 14 (regen — new fighters enter at the bottom at rating
-- 1000.0), and Task ID 22 (rivalries — ranking proximity boosts
-- heat). The `rankings` UNIQUE (fighter_id, weight_class_id,
-- promotion_id) constraint ensures one row per fighter per WC per
-- promotion; the same fighter fighting in two promotions gets two
-- ranking rows (cross-promotional ranking is out of scope until
-- Task 25+). See docs/SCHEMA_DRIFT_AUDIT.md §K and
-- docs/STAGES.md Task ID 10.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rankings (
    ranking_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    weight_class_id INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE CASCADE,
    promotion_id    INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    rating          REAL NOT NULL DEFAULT 1000.0 CHECK (rating >= 0),
    fights_count    INTEGER NOT NULL DEFAULT 0 CHECK (fights_count >= 0),
    wins            INTEGER NOT NULL DEFAULT 0 CHECK (wins >= 0),
    losses          INTEGER NOT NULL DEFAULT 0 CHECK (losses >= 0),
    draws           INTEGER NOT NULL DEFAULT 0 CHECK (draws >= 0),
    last_fight_date TEXT,
    created_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_id, weight_class_id, promotion_id)
);

-- ----------------------------------------------------------------
-- Titles (added in v1.6.0, Task ID 11).
-- One row per belt per promotion per weight class. Tracks the
-- current champion, when they won it, how many defenses they've
-- made, and whether the title is vacant. Foundation for Task 8's
-- schedule_next_event() (future: champion vs #1 contender), Task
-- 14 (regen - retiring champions vacate), Task 22 (rivalries -
-- title fight rivalries are the most heated).
--
-- A title is "vacant" when current_champion_fighter_id IS NULL.
-- The seed creates all titles as vacant. The first title fight
-- transfers the belt to the winner. Subsequent title fights are
-- the champion defending against a contender. If a champion
-- retires (Task 12) or leaves (Task 13), the title is vacated.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS titles (
    title_id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id                 INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    weight_class_id              INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE CASCADE,
    current_champion_fighter_id  INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    champion_since_date          TEXT,
    title_reigns_count           INTEGER NOT NULL DEFAULT 0 CHECK (title_reigns_count >= 0),
    title_defenses_count         INTEGER NOT NULL DEFAULT 0 CHECK (title_defenses_count >= 0),
    is_vacant                    INTEGER NOT NULL DEFAULT 1 CHECK (is_vacant IN (0, 1)),
    created_at                   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at                   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (promotion_id, weight_class_id)
);

-- ----------------------------------------------------------------
-- Name pools + regen lineage (added in v1.9.0, Task ID 14).
-- When a fighter retires, a replacement is generated from the name
-- pools with a similar style DNA. The new fighter enters as a free
-- agent (current_promotion_id=NULL, is_active=1, is_retired=0) and
-- appears in Task 13's Free Agents tab, ready to be signed by any
-- promotion. regen_lineage tracks which retiring fighter spawned
-- which replacement (for future memory-resurfacing features in
-- Stage 3+). fighter_memory_links exists in this task but is NOT
-- populated — memory resurfacing (style echoes, gym heirs, regional
-- rivals, successors) is a future enhancement that will write to
-- this table without needing a schema change.
--
-- Note on `used_names`: the spec calls for a separate `used_names`
-- table to prevent duplicate fighter names. We chose to check
-- uniqueness against the existing `fighters` table (first_name +
-- last_name combination) instead. This is simpler, avoids a
-- redundant table, and stays correct when fighters are deleted
-- (their names become available again, which matches the design
-- intent — the world doesn't keep a permanent name registry). The
-- generate_fighter() function in app.py implements this check.
-- See docs/SCHEMA_DRIFT_AUDIT.md §M and docs/STAGES.md Task ID 14.
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS name_pools (
    name_pool_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name_type       TEXT NOT NULL CHECK (name_type IN ('first_male', 'first_female', 'last', 'nickname')),
    name_value      TEXT NOT NULL,
    region          TEXT,
    created_at      TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (name_type, name_value, region)
);

CREATE TABLE IF NOT EXISTS regen_lineage (
    regen_lineage_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    retiring_fighter_id    INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    replacement_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    style_dna_archetype_id INTEGER REFERENCES style_archetypes(style_archetype_id) ON DELETE SET NULL,
    regen_date             TEXT NOT NULL,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (retiring_fighter_id, replacement_fighter_id)
);

CREATE TABLE IF NOT EXISTS fighter_memory_links (
    memory_link_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    -- v3.36.0 (TIER3-MISSING §T3.4 / W17) — expanded CHECK with 8 new
    -- link types: 'previous_fights', 'former_teammates', 'old_gyms',
    -- 'former_champions', 'controversial_losses', 'injuries',
    -- 'promotions', 'old_events'. Total 20 allowed values.
    --   - The 12 existing values (style_echo, gym_heir, regional_rival,
    --     successor, previous_fight, shared_gym, former_teammate,
    --     injury_history, title_history, upset, comeback, milestone)
    --     are preserved verbatim (the new CHECK is a SUPERSET).
    --   - The 8 new values are distinct from existing singular-form
    --     variants (previous_fight vs previous_fights, former_teammate
    --     vs former_teammates, injury_history vs injuries) — they
    --     capture related-but-distinct memory categories per the
    --     T3.4 brief.
    link_type         TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history', 'title_history', 'upset', 'comeback', 'milestone', 'previous_fights', 'former_teammates', 'old_gyms', 'former_champions', 'controversial_losses', 'injuries', 'promotions', 'old_events')),
    link_strength     INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_id, linked_fighter_id, link_type)
);

-- ----------------------------------------------------------------
-- staff_regen_lineage (added v3.25.0, Phase M2.3 — docs/MASTER_PLAN_
-- MATCHMAKING.md §2.3 Staff lifecycle — regen).
--
-- Mirrors regen_lineage (for fighters) but for STAFF. When a staff
-- member retires (Phase M2.2 annual tick on Jan 1), the retirement
-- service generates a replacement staff member with a similar skill
-- range + same role_type. This table tracks which retiring staff
-- spawned which replacement, so future torch-passing narrative
-- features (e.g., "the legendary GM's successor takes over" news
-- items, "in the lineage of {retiring_commentator}" personality
-- traits) can read the link without needing a schema change.
--
-- One row per (retiring_staff_id, replacement_staff_id) pair —
-- the UNIQUE constraint enforces this. replacement_staff_id can
-- be NULL briefly during the replacement generation (defensive —
-- if generation fails midway, the lineage row still records that
-- a retirement happened, just without a successor).
--
-- Per CONVENTIONS §5.3, the writer is src/services/retirement_svc.
-- generate_staff_replacement (Phase M2.3) and the reader is the
-- future torch-passing news engine (Phase M3+, not built yet).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staff_regen_lineage (
    regen_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    retiring_staff_id      INTEGER REFERENCES staff(staff_id) ON DELETE SET NULL,
    replacement_staff_id   INTEGER REFERENCES staff(staff_id) ON DELETE SET NULL,
    role_type              TEXT NOT NULL,
    regen_date             TEXT NOT NULL,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (retiring_staff_id, replacement_staff_id)
);
CREATE INDEX IF NOT EXISTS idx_staff_regen_lineage_retiring
    ON staff_regen_lineage(retiring_staff_id);
CREATE INDEX IF NOT EXISTS idx_staff_regen_lineage_replacement
    ON staff_regen_lineage(replacement_staff_id);

-- fighter_bios (added v2.6.0, Task 16.5 — World seed prep).
-- Long-form prose bios for fighters. The world seed Phase 5 writes
-- these for the top ~200 "featured" fighters (champions, top
-- contenders, top prospects, notable veterans). Other fighters have
-- no bio row — the UI will show "no bio available" or generate a
-- short procedural descriptor via the voice layer (Task 19).
--
-- One row per fighter (PK = fighter_id). The bio_text is a 2-4
-- sentence prose bio written by the seed; bio_tone is a hint for
-- the voice layer (e.g. 'hype_prospect', 'grizzled_veteran',
-- 'champion_reign', 'fallen_contender', 'journeyman', 'cult_hero').
CREATE TABLE IF NOT EXISTS fighter_bios (
    fighter_id  INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    bio_text    TEXT NOT NULL,
    bio_tone    TEXT NOT NULL DEFAULT 'neutral'
                CHECK (bio_tone IN ('neutral', 'unproven_prospect',
                                    'grizzled_veteran', 'champion_reign',
                                    'fallen_contender', 'journeyman',
                                    'cult_hero', 'mid_carder',
                                    'late_bloomer', 'enforcer')),
    created_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- hall_of_fame (added v2.6.0, Task 16.5 — World seed prep).
-- Retired legends who have been inducted into the CAGE EMPIRE Hall
-- of Fame. The world seed Phase 5 inserts ~50-100 retired fighters
-- here with career summaries + highlights. A future UI tab (Hall of
-- Fame) will display this. The inducted_date is the in-fiction
-- ceremony date; career_highlights is a multi-line string of bullet
-- points ("3-time Lightweight Champion", "10 title defenses",
-- "Submission of the Year 2021").
CREATE TABLE IF NOT EXISTS hall_of_fame (
    fighter_id          INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    inducted_date       TEXT NOT NULL,
    career_summary      TEXT NOT NULL,
    career_highlights   TEXT,
    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- Beat-level fight engine (added in v2.1.0, Task B1).
--
-- Two tables that the rewritten `resolve_next_fight()` in app.py
-- populates as it simulates each round beat-by-beat. The pure
-- `_resolve_outcome()` function from Task 3 is REPLACED by
-- `resolve_round()` — the new resolver generates beats, writes them
-- to `fight_beats`, then writes the per-round aggregate to
-- `fight_rounds` via a SUM-over-fight_beats query (so the two tables
-- can never drift). After all scheduled rounds complete, decision
-- scoring (10-point must, unanimous / split / draw) picks the fight
-- winner. B1 does NOT have mid-round finishes — every fight goes to
-- decision. B2 will add fatigue, momentum, KO/submission/doctor/
-- corner/DQ.
--
-- `fight_beats` is the raw substrate that future Task B2 (fatigue +
-- momentum + finishes + commentary beat selection) and Task 23
-- (commentary beat selection) build on. Per CONVENTIONS §14, the
-- beat engine stores RAW numbers — the interpretation layer (Task
-- 19) is what eventually translates them into prose. Until Task 19
-- lands, the beat engine also produces hardcoded commentary text via
-- the existing _format_fight_commentary() function.
--
-- `fight_rounds` is the per-round aggregate that future Task 23
-- (commentary beats — "round 2 was all Vale, he landed 15
-- significant strikes"), Task 24 (punditry — round-by-round
-- analysis), and Task 26 (show rating — round-by-round drama is a
-- key input) will read from. The aggregate columns are computed
-- sums over the round's `fight_beats` rows; the
-- `round_winner_fighter_id` is set by the engine after each round
-- using the 10-point must scoring rule.
--
-- All existing side effects of `resolve_next_fight()` are PRESERVED
-- (fight_history, rankings, titles, event lifecycle,
-- schedule_next_event, news, commentary). Only the resolution
-- mechanism changes — the `fights` table's winner_fighter_id /
-- loser_fighter_id / result_type / finish_round / finish_time /
-- performance_rating / fan_reaction_rating columns are populated
-- exactly as before, just with decision-flavored values
-- (result_type in {'unanimous_decision', 'split_decision', 'draw'},
-- finish_round = scheduled_rounds, finish_time = '5:00').
--
-- See docs/STAGES.md Stage 2.5 "Detailed task brief: B1" for the
-- full brief and acceptance checklist. See
-- docs/STAGE3_EXPANSION_PLAN.md Part 2 for the engine mechanics
-- spec (beat count formula, phase-to-attribute mapping, phase
-- transitions, decision scoring).
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fight_beats (
    fight_beat_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id               INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    round_number           INTEGER NOT NULL,
    beat_number            INTEGER NOT NULL,
    phase                  TEXT NOT NULL CHECK (phase IN
                             ('standing','clinch','cage','ground_top','ground_bottom','scramble')),
    action_type            TEXT NOT NULL,
    initiator_fighter_id   INTEGER NOT NULL REFERENCES fighters(fighter_id),
    target_fighter_id      INTEGER NOT NULL REFERENCES fighters(fighter_id),
    -- v2.3.0 (Task B2): added 'knockdown' and 'near_finish' to the
    -- outcome CHECK. The 5 B1 outcomes ('landed','missed','blocked',
    -- 'defended','reversed') describe per-beat exchange outcomes. The
    -- 2 new B2 outcomes mark dramatic moments:
    --   - 'knockdown': the beat that ends a fight by KO/TKO (finishing
    --     blow) OR a moment where the defender was dropped but
    --     survived (high-momentum knockdown). Carries
    --     momentum_shift = +80 per the B2 brief.
    --   - 'near_finish': the defender was "rocked" (cumulative damage
    --     in the current beat sequence crossed their KO threshold, but
    --     the KO roll failed — they survived) OR a submission_attempt
    --     landed (defender tapped — finish) OR a submission attempt
    --     almost succeeded. Carries momentum_shift = +60.
    -- Modifying a CHECK constraint on an existing table is a MINOR
    -- bump per CONVENTIONS §1.1 (no breaking change to data shape —
    -- existing rows satisfy the new CHECK because the new values are
    -- a superset of the old values).
    outcome                TEXT NOT NULL CHECK (outcome IN
                             ('landed','missed','blocked','defended','reversed',
                              'knockdown','near_finish')),
    damage_dealt           INTEGER NOT NULL DEFAULT 0,
    control_time_delta     INTEGER NOT NULL DEFAULT 0,
    momentum_shift         INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, round_number, beat_number)
);

CREATE TABLE IF NOT EXISTS fight_rounds (
    fight_round_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id                    INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    round_number                INTEGER NOT NULL CHECK (round_number > 0),
    fighter_a_id                INTEGER NOT NULL REFERENCES fighters(fighter_id),
    fighter_b_id                INTEGER NOT NULL REFERENCES fighters(fighter_id),
    fighter_a_damage            INTEGER NOT NULL DEFAULT 0,
    fighter_b_damage            INTEGER NOT NULL DEFAULT 0,
    fighter_a_control_time      INTEGER NOT NULL DEFAULT 0,
    fighter_b_control_time      INTEGER NOT NULL DEFAULT 0,
    fighter_a_knockdowns        INTEGER NOT NULL DEFAULT 0,
    fighter_b_knockdowns        INTEGER NOT NULL DEFAULT 0,
    fighter_a_takedowns         INTEGER NOT NULL DEFAULT 0,
    fighter_b_takedowns         INTEGER NOT NULL DEFAULT 0,
    fighter_a_strikes_landed    INTEGER NOT NULL DEFAULT 0,
    fighter_b_strikes_landed    INTEGER NOT NULL DEFAULT 0,
    -- v2.3.0 (Task B2): per-fighter gas remaining at the end of the
    -- round. The fatigue system tracks gas in-memory across rounds in
    -- resolve_next_fight() (gas starts at 100, depletes per beat per
    -- _compute_gas_cost, recovers between rounds per
    -- _recover_gas_between_rounds). resolve_round() writes the end-of-
    -- round gas values to these columns so future systems (training
    -- camps analyzing cardio endurance, commentary mentioning "he
    -- looked gassed by round 3", punditry on conditioning) can read
    -- them. DEFAULT 100.0 keeps existing INSERTs valid; the engine
    -- always writes the actual end-of-round value.
    fighter_a_gas_remaining     REAL NOT NULL DEFAULT 100.0,
    fighter_b_gas_remaining     REAL NOT NULL DEFAULT 100.0,
    momentum_state              TEXT,
    round_winner_fighter_id     INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    created_at                  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, round_number)
);

-- ----------------------------------------------------------------
-- Injuries + medical recovery (added in v2.4.0, Task ID 15).
--
-- One row per injury a fighter suffers. Injuries are created by
-- `_maybe_create_injury()` in app.py at the end of
-- resolve_next_fight() (after all other side effects — fight_history,
-- rankings, titles, event lifecycle, schedule_next_event, news,
-- commentary). Recovery is advanced by `_check_injury_recovery()` in
-- tick_processor.py on every tick.
--
-- Injury creation rules (per the Task 15 brief):
--   - doctor_stoppage: guaranteed injury on the loser (the reason
--     the doctor stopped it).
--   - ko_tko: 30% chance of head injury (concussion) on the loser,
--     severity scaled by damage in the finishing beat.
--   - submission: 15% chance of joint injury (knee / elbow /
--     shoulder / ankle) on the loser.
--   - decision / draw / corner_stoppage / dq: 5% base + damage-
--     scaled chance, applied to BOTH fighters.
-- `injury_proneness` (fighters column) modifies the probability;
-- `durability` (fighter_attributes column) reduces severity.
--
-- Recovery:
--   - projected_return_date = start_date + severity * 14 days,
--     reduced by recovery_rate * 0.1 per day.
--   - Tick processor advances recovery: if current_date >=
--     projected_return_date, set actual_return_date = current_date,
--     is_active = 0.
--   - long_term_damage: severity 8+ injuries have 30% chance of
--     permanent attribute reduction (-2 to -5 on a body-area-
--     relevant attribute). Reduces fighter_career.career_health by
--     the same amount (permanent — NOT restored on recovery).
--   - career_health reduction while active: each active injury
--     reduces career_health by severity * 2 (temporary — restored
--     on recovery).
--
-- Booking restriction:
--   - `_pick_matchup()` in app.py filters out fighters with active
--     injuries (`AND fighter_id NOT IN (SELECT fighter_id FROM
--     injuries WHERE is_active = 1)`) — injured fighters can't be
--     booked.
--
-- News:
--   - On injury creation: "{Fighter} suffers {injury_type} —
--     projected return {date}" (topic='injury').
--   - On recovery clearance: "{Fighter} cleared to return from
--     {injury_type}" (topic='injury').
--
-- See docs/STAGES.md Task ID 15 for the brief and acceptance
-- checklist. See docs/SCHEMA_DRIFT_AUDIT.md §H (injuries was the
-- MISSING row this task upgrades to OK).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS injuries (
    injury_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id             INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    event_id               INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id               INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    injury_type            TEXT NOT NULL,
    severity               INTEGER NOT NULL DEFAULT 5 CHECK (severity BETWEEN 1 AND 10),
    body_area              TEXT NOT NULL CHECK (body_area IN ('head','face','jaw','nose','eye','neck','shoulder','arm','elbow','wrist','hand','ribs','back','hip','knee','ankle','foot','general')),
    start_date             TEXT NOT NULL,
    projected_return_date  TEXT NOT NULL,
    actual_return_date     TEXT,
    long_term_damage       INTEGER NOT NULL DEFAULT 0 CHECK (long_term_damage BETWEEN 0 AND 100),
    career_risk            INTEGER NOT NULL DEFAULT 0 CHECK (career_risk BETWEEN 0 AND 100),
    is_active              INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- training_camps (added v2.5.0, Task 16 — Training camps).
--
-- One row per fighter per scheduled fight. When schedule_next_event()
-- in app.py auto-schedules a new event, it creates one training_camps
-- row for each of the 2 booked fighters, with start_date = event_date
-- - 14 days and end_date = event_date (a ~2-week camp leading up to
-- the fight). The camp_focus is derived from the fighter's
-- fight_style_archetype_id (Striker → striking, Grappler → grappling,
-- Wrestler → wrestling, Submission Specialist → submission, Brawler
-- and Counter-Striker → striking, Balanced → general; default
-- 'general' for unknown archetypes — see _ARCHETYPE_NAME_TO_CAMP_FOCUS
-- in app.py).
--
-- The tick processor (_check_training_camps in tick_processor.py)
-- progresses each active, uncompleted camp on every tick within the
-- camp's [start_date, end_date] window:
--   - Fatigue accrues +2-5 per tick (reduced by cardio +
--     fatigue_tolerance).
--   - Morale fluctuates ±0-2 per tick (dampened by coachability,
--     biased by the gym's culture_tone: disciplined → +morale,
--     loose → -morale, predator → +morale, balanced → neutral).
--   - Injury risk accumulates +2-5 per tick (increased by
--     injury_proneness, reduced by the gym's medical_support).
--   - If injury_risk > 80: a training injury is created via the
--     Task 15 injuries table (training-injury pool: torn ACL,
--     hamstring strain, shoulder labrum tear, rib sprain, training
--     concussion, wrist/ankle sprain). The camp is marked inactive
--     and completed (the fighter is injured and can't continue
--     training).
--   - If current_date == end_date: the camp completes. Pick 2-4
--     attributes from the camp_focus pool (count = 2 + int((coach_
--     ability + development_focus) / 100), clamped [2,4]). Apply
--     +1 to +3 base gain to each, scaled by:
--       * gym spec multiplier (0.5-1.5 from facility_quality +
--         development_focus — the brief's "Gym spec +50%/-50%" rule)
--       * coachability multiplier (0.5-1.5)
--       * fatigue factor (0.5-1.0 — high fatigue + low fatigue_
--         tolerance reduces gains)
--     Capped at fighter_career.potential. The attribute_changes
--     column records the gains as a JSON dict (e.g. {"punch_power":
--     2, "head_movement": 1}). A completion news item is written:
--     "{Fighter} completes training camp" with topic='training'.
--
-- resolve_next_fight in app.py reads the camp's camp_fatigue column
-- to apply the brief's "Fatigue > 50 = reduced starting gas" rule:
-- starting gas = 100 - max(0, camp_fatigue - 50), floored at 50.
-- This is the reader required by CONVENTIONS §5.3.
--
-- 19 columns (the brief's prose says "20" but the parenthetical
-- list enumerates 19 — see worklog decision D2). The 4 0-100
-- INTEGER columns have CHECK constraints; is_active / is_completed
-- are 0/1 CHECK; camp_focus is restricted to the 8 enumerated
-- values. FKs: fighter_id NOT NULL ON DELETE CASCADE (clean up
-- when a fighter is deleted); gym_id / event_id / fight_id ON
-- DELETE SET NULL (preserve camp history when a gym/event/fight
-- is deleted — the camp record survives with NULL FK).
--
-- See docs/STAGES.md Task ID 16 for the brief. See SCHEMA_DRIFT_
-- AUDIT.md §H (training_camps was the MISSING row this task
-- upgrades to OK — deferred update per the brief's "No docs"
-- rule; the supervisor applies the audit update at sign-off).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS training_camps (
    training_camp_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id                 INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    gym_id                     INTEGER REFERENCES gyms(gym_id) ON DELETE SET NULL,
    event_id                   INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id                   INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    start_date                 TEXT NOT NULL,
    end_date                   TEXT NOT NULL,
    camp_duration_days         INTEGER NOT NULL DEFAULT 14 CHECK (camp_duration_days >= 0),
    camp_focus                 TEXT NOT NULL DEFAULT 'general' CHECK (camp_focus IN ('striking','grappling','wrestling','conditioning','submission','clinch','general','weight_cut')),
    camp_morale                INTEGER NOT NULL DEFAULT 50 CHECK (camp_morale BETWEEN 0 AND 100),
    camp_fatigue               INTEGER NOT NULL DEFAULT 0 CHECK (camp_fatigue BETWEEN 0 AND 100),
    camp_injury_risk           INTEGER NOT NULL DEFAULT 0 CHECK (camp_injury_risk BETWEEN 0 AND 100),
    camp_weight_cut_pressure   INTEGER NOT NULL DEFAULT 0 CHECK (camp_weight_cut_pressure BETWEEN 0 AND 100),
    attribute_changes          TEXT,
    camp_result_summary        TEXT,
    is_active                  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_completed               INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    created_at                 TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at                 TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- weight_cut_log (added v2.7.0, Task 17 — Weight cuts).
--
-- One row per fighter per scheduled fight, recording the weight cut
-- outcome. Created by _run_weight_cut() in app.py, called from
-- resolve_next_fight() BEFORE the fight resolves. The cut_outcome
-- determines what happens:
--   'made_weight'    — fighter made weight, no penalty, fight proceeds
--   'missed_small'   — missed by < 1kg, fight proceeds at catch-weight,
--                      offender forfeits 20% of purse to opponent
--   'missed_medium'  — missed by 1-3kg, fight proceeds at catch-weight,
--                      offender forfeits 30% of purse + starts with
--                      reduced cardio (gas penalty)
--   'missed_large'   — missed by > 3kg, fight CANCELLED (opponent gets
--                      50% purse, offender gets nothing, fight_history
--                      records a 'no_contest' result_type)
--   'cancelled'      — the fight was cancelled before the cut (e.g.,
--                      opponent's camp produced an injury). The fighter
--                      didn't attempt the cut.
--
-- The miss probability is derived from:
--   - fighters.weight_cut_difficulty (0-100, per-fighter static)
--   - fighter age (older = harder cut, +1% per year over 30)
--   - training_camps.camp_weight_cut_pressure (0-100, from weight_cut
--     focused camps)
--   - gym weight_cut_support (reduces miss probability)
--
-- The cardio_penalty is applied to the fighter's starting gas in
-- resolve_next_fight (gas starts at 100 - cardio_penalty, floored at
-- 50). This is the "hard cut cost the fighter his gas" story.
--
-- 14 columns. FKs: fighter_id NOT NULL ON DELETE CASCADE; fight_id /
-- event_id ON DELETE SET NULL (preserve cut history when a fight/event
-- is deleted). See docs/STAGES.md Task ID 17 for the brief.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weight_cut_log (
    weight_cut_log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id             INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    fight_id               INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    event_id               INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    weight_class_id        INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,
    cut_date               TEXT NOT NULL,
    target_weight_kg       REAL NOT NULL,
    actual_weight_kg       REAL,
    weight_missed_kg       REAL NOT NULL DEFAULT 0.0,
    cut_outcome            TEXT NOT NULL DEFAULT 'made_weight'
                           CHECK (cut_outcome IN ('made_weight', 'missed_small',
                                                  'missed_medium', 'missed_large',
                                                  'cancelled')),
    cardio_penalty         INTEGER NOT NULL DEFAULT 0 CHECK (cardio_penalty BETWEEN 0 AND 50),
    purse_penalty_pct      INTEGER NOT NULL DEFAULT 0 CHECK (purse_penalty_pct BETWEEN 0 AND 100),
    is_title_fight         INTEGER NOT NULL DEFAULT 0 CHECK (is_title_fight IN (0, 1)),
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- fighter_descriptors (added v2.8.0, Task 19 — Voice/Interpretation
-- Layer snapshot cache).
--
-- One row per fighter (PK = fighter_id). Stores the computed
-- descriptor strings as JSON, updated on trigger events (camp
-- completion, fight resolution, injury, title change) — NOT on
-- every UI view. The UI reads from this table for fast display;
-- the src/voice.py module computes the descriptors when a trigger
-- fires.
--
-- Columns:
--   attribute_descriptors: JSON dict {attr_name: descriptor_str}
--   personality_descriptors: JSON dict {trait_name: descriptor_str}
--   career_stage: short phrase ("reigning champion", "top prospect")
--   career_health_desc: short phrase ("in peak condition", "battered")
--   overall_desc: one-sentence summary
--   potential_desc: NULL (hidden — set by scouting system Task 18)
--   snapshot_version: incremented on each update (for cache busting)
--   updated_at: timestamp of last update
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fighter_descriptors (
    fighter_id              INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    attribute_descriptors   TEXT NOT NULL DEFAULT '{}',
    personality_descriptors TEXT NOT NULL DEFAULT '{}',
    career_stage            TEXT,
    career_health_desc      TEXT,
    overall_desc            TEXT,
    potential_desc          TEXT,
    -- Phase 2 Interpretation Layer columns (added v3.10.0, Task 2.0c).
    -- All nullable TEXT — populated by the daily interpretation pass
    -- (Tasks 2.2/2.3/2.4/2.7) and refreshed on FIGHT_RESOLVED /
    -- FIGHTER_RETIRED / TITLE_CHANGED / CONTRACT_EXPIRED events.
    -- Per CONVENTIONS §17: these are CACHE columns — the interpretation
    -- layer is the ONLY writer. Office Mode UI reads them directly.
    momentum                TEXT,
    pressure                TEXT,
    career_phase            TEXT,
    narrative_family        TEXT,
    public_narrative        TEXT,
    legacy_state            TEXT,
    -- INTERP-EXPAND-V2 (Claude VOICE_ENFORCEMENT §3): SHORT variants
    -- of the 4 interpretation columns above. Each stores the SAME
    -- canonical label (before "||") + a SHORT voice phrase (≤25 chars)
    -- for display contexts with limited width (Fighter Watch Cards,
    -- Roster rows, table chips). The LONG column above still carries
    -- the full phrase for Fighter Profile (full width). The daily
    -- interpretation pass writes BOTH columns from the same RNG seed
    -- so the same fighter's short + long pair is deterministic.
    momentum_short          TEXT,
    pressure_short          TEXT,
    career_phase_short      TEXT,
    narrative_family_short  TEXT,
    legacy_state_short      TEXT,
    snapshot_version        INTEGER NOT NULL DEFAULT 1,
    updated_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- scouting_reports (added v2.9.0, Task 18 — Scouting system).
--
-- One row per scouting report. A scout (staff member with role_type=
-- 'scout') is assigned to evaluate a target fighter. After N ticks of
-- observation, a report is generated with estimated attributes,
-- potential, strengths, weaknesses — all expressed as DESCRIPTORS
-- (via voice.py), NOT raw numbers.
--
-- The report's accuracy depends on the scout's attributes:
--   - eye_for_talent: how accurately they estimate potential
--   - technical_analysis: how accurately they estimate attributes
--   - character_reading: how accurately they estimate personality
--   - mistake_rate: chance of a significant misjudgment
--   - bias_style: over/under-rates certain styles
--   - bias_nationality: better accuracy for familiar nations
--
-- Reports become STALE when the fighter trains, fights, or ages
-- significantly. Stale reports show a warning but remain readable.
--
-- Per CONVENTIONS §14: all estimates use voice.py descriptors, NOT
-- raw numbers. The player sees "high ceiling, above-average power,
-- questionable chin" — not "potential=72, punch_power=78, chin=35."
--
-- Per the user directive: "potential should never equal guaranteed
-- success." The scout estimates the fighter's CEILING, but the
-- fighter may never reach it (see the effective_ceiling growth logic
-- in tick_processor._complete_training_camp — age, health,
-- personality, and diminishing returns all reduce the actual ceiling
-- below the theoretical potential).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scouting_reports (
    scouting_report_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_id                INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    target_fighter_id       INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    promotion_id            INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    report_date             TEXT NOT NULL,
    estimated_potential     TEXT,
    estimated_ceiling       TEXT,
    estimated_floor         TEXT,
    estimated_strengths     TEXT,
    estimated_weaknesses    TEXT,
    marketability_assessment TEXT,
    injury_risk_assessment  TEXT,
    contract_cost_estimate  INTEGER,
    scout_confidence        INTEGER NOT NULL DEFAULT 50 CHECK (scout_confidence BETWEEN 0 AND 100),
    is_stale                INTEGER NOT NULL DEFAULT 0 CHECK (is_stale IN (0, 1)),
    report_text             TEXT NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- finance_transactions (added v3.0.0, Task 20 — Finance system).
--
-- One row per financial transaction (revenue or expense). Created by
-- src/finance.py (event bus subscriber) when events complete or
-- weekly expenses accrue. Each transaction has a type (ticket_sales,
-- broadcast_revenue, fighter_purse, venue_rental, staff_salary,
-- medical_cost, signing_bonus, weight_cut_penalty), an amount
-- (positive=revenue, negative=expense), and references the event/
-- fighter/promotion it relates to.
--
-- The promotions.current_cash column is updated on each transaction.
-- Per-event P&L = sum of transactions for that event_id.
-- Weekly burn rate = sum of negative transactions in the last 7 days.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS finance_transactions (
    transaction_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id            INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    event_id                INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fighter_id              INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    transaction_type        TEXT NOT NULL CHECK (transaction_type IN (
        'ticket_sales', 'broadcast_revenue', 'merchandise',
        'fighter_purse', 'venue_rental', 'staff_salary',
        'medical_cost', 'signing_bonus', 'weight_cut_penalty',
        'sponsorship', 'bonus_payment', 'concessions',
        'marketing', 'show_quality_adjustment'
    )),
    amount                  REAL NOT NULL,
    description             TEXT,
    transaction_date        TEXT NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- social_posts (added v3.1.0, Task 21 — Social media + beefs).
--
-- One row per fighter social media post. Created by src/social.py
-- (event bus subscriber) in response to FIGHT_RESOLVED, TITLE_CHANGED,
-- and TICK_ADVANCED events. Posts are entirely voice-layer-driven —
-- no raw attribute numbers, ratings, or stats appear in post_text
-- (CONVENTIONS §14).
--
-- Personality influence on post generation (handled in src/social.py):
--   attention_seeking → frequency of posts (high trait → more posts)
--   aggression        → mix of post types (high → more trash_talk/callout)
--   charisma          → engagement score (high → more likes/comments)
--   ego               → more brags / challenges
--   composure         → fewer excuse posts, more measured tone
--   sportsmanship     → more apologies, fewer trash_talks
--
-- Beef escalation: when fighter A has previously callout'd or trash-
-- talked fighter B, any new callout/trash_talk/excuse between them is
-- flagged is_beef_escalation=1. Task 22 (rivalries) will mine this
-- column to seed rivalries.
--
-- 9 post types (CHECK constraint):
--   callout            — calling out a specific fighter for a fight
--   trash_talk         — insulting a specific fighter
--   hype               — building up an upcoming fight or training camp
--   apology            — apologizing for poor behavior or performance
--   announcement       — generic announcement (could be retirement,
--                        signing, etc.)
--   brag               — bragging about a recent win or achievement
--   excuse             — explaining away a loss
--   retirement_hint    — hinting at retirement (often the precursor
--                        to FIGHTER_RETIRED events)
--   challenge          — challenging the current champion
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS social_posts (
    post_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id       INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    post_type        TEXT NOT NULL CHECK (post_type IN (
        'callout', 'trash_talk', 'hype', 'apology', 'announcement',
        'brag', 'excuse', 'retirement_hint', 'challenge'
    )),
    target_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    post_text        TEXT NOT NULL,
    post_date        TEXT NOT NULL,
    engagement       INTEGER NOT NULL DEFAULT 0 CHECK (engagement >= 0),
    is_beef_escalation INTEGER NOT NULL DEFAULT 0 CHECK (is_beef_escalation IN (0, 1)),
    created_at       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- rivalries (added v3.2.0, Task 22 — Rivalries).
--
-- One row per pairwise rivalry between two fighters. Created by
-- src/rivalries.py (event-bus subscribers) in response to TICK_ADVANCED
-- (social beefs accumulation), FIGHT_RESOLVED (close decisions, weight
-- cut misses, fights between existing rivals), and TITLE_CHANGED (title
-- changes hands between two fighters → title_rivalry).
--
-- Rivalry heat escalation (handled in src/rivalries.py):
--   Each callout/trash_talk social post between rivals: +5 heat
--   Each fight between rivals: +15 heat
--   Title fight between rivals: +25 heat
--   Weight cut miss against a rival: +10 heat
--   Apology social post: -10 heat
--   Heat caps at 100 (CHECK + code clamp)
--
-- 7 rivalry types (CHECK constraint):
--   callout             — built from accumulated callouts/trash_talk
--                         posts between two fighters (3+ posts)
--   bad_blood           — built from a non-fight incident (weight cut
--                         miss against a rival, etc.)
--   title_rivalry       — built when a title changes hands between
--                         two fighters (champion vs former champion)
--   rematch_hungry      — built after a close/controversial decision
--                         that demands a rematch
--   style_clash         — reserved for when two fighters with strongly
--                         opposing style archetypes meet (future task
--                         may seed this from matchmaking)
--   disrespect          — built from post-fight unsportsmanlike
--                         behavior (trash_talk after a loss)
--   stolen_opportunity  — reserved for when a contender loses a
--                         promised title shot (future task may seed
--                         this from rankings + title-shot promises)
--
-- fighter_a_id is always the LOWER fighter_id (canonical ordering),
-- so the UNIQUE (fighter_a_id, fighter_b_id) constraint prevents
-- duplicate rivalries regardless of who initiated. The
-- fighter_a_wins / fighter_b_wins / draws columns track head-to-head
-- fight results between the two (updated by _process_fight_rivalry).
--
-- origin_description holds a voice-layer-driven description of how
-- the rivalry started (CONVENTIONS §14 — no raw numbers). Example:
--   "A bad blood rivalry between John Vale (reigning champion) and
--    Marcus Reed (top prospect). The rivalry started with callouts
--    on social media."
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rivalries (
    rivalry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_a_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    fighter_b_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    rivalry_heat      INTEGER NOT NULL DEFAULT 50 CHECK (rivalry_heat BETWEEN 0 AND 100),
    rivalry_type      TEXT NOT NULL CHECK (rivalry_type IN (
        'callout', 'bad_blood', 'title_rivalry', 'rematch_hungry',
        'style_clash', 'disrespect', 'stolen_opportunity'
    )),
    origin_event      TEXT,
    origin_description TEXT,
    fights_count      INTEGER NOT NULL DEFAULT 0,
    fighter_a_wins    INTEGER NOT NULL DEFAULT 0,
    fighter_b_wins    INTEGER NOT NULL DEFAULT 0,
    draws             INTEGER NOT NULL DEFAULT 0,
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_escalation_date TEXT,
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_a_id, fighter_b_id)
);

-- ----------------------------------------------------------------
-- matchup_analyses (added v3.3.0, Task 24 — Punditry / matchup
-- analysis). One row per (fighter_a_id, fighter_b_id, fight_id)
-- triple (UNIQUE — the pundit's pre-fight prediction for a single
-- scheduled fight). Generated retroactively by src/punditry.py
-- (event-bus subscriber for FIGHT_RESOLVED — the analysis describes
-- the pre-fight matchup, written after the fight so it appears in
-- the news feed as "here's what the pundits thought going in").
--
-- The analysis is the pundit's take on the matchup:
--   predicted_winner     — fighter full name (TEXT, NO raw numbers)
--   predicted_method     — "KO/TKO" / "submission" / "decision" /
--                          "KO or submission" (TEXT, method label)
--   confidence_pct       — 0-100 INTEGER (the only numeric column
--                          the player sees — see D2 in the worklog;
--                          represents pundit confidence, NOT a
--                          fighter attribute value, so §14 doesn't
--                          forbid it. CHECK BETWEEN 0 AND 100.)
--   style_edge           — voice-layer-driven phrase (e.g.,
--                          "the striker has the edge on the feet")
--                          — NO raw attribute numbers per §14.
--   excitement_score     — 0-100 INTEGER (CHECK BETWEEN 0 AND 100).
--                          Same §14 carve-out as confidence_pct —
--                          the pundit's excitement rating, not a
--                          fighter attribute.
--   upset_risk           — voice-layer-driven phrase (e.g.,
--                          "real upset risk" / "the favorite should
--                          hold" / "upset alert") — NO raw numbers.
--   analysis_text        — full prose analysis (voice-layer-driven,
--                          NO raw numbers per §14). The pundit's
--                          pre-fight breakdown using voice.
--                          describe_career_stage + voice.
--                          describe_attribute descriptors.
--
-- fighter_a_id + fighter_b_id are NOT NULL (every analysis involves
-- two fighters). fight_id is nullable (a future UI might let the
-- player request a pundit analysis for a hypothetical matchup; for
-- now, every analysis is tied to a real fight via FIGHT_RESOLVED).
-- event_id is nullable + denormalized for convenience (the news
-- feed can filter analyses by event without a JOIN).
--
-- UNIQUE (fighter_a_id, fighter_b_id, fight_id) — the pundit only
-- writes one analysis per scheduled fight. If the same pair rematches
-- in a later fight (different fight_id), a new analysis row is
-- written (so the player sees the pundit's evolving take).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matchup_analyses (
    analysis_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_a_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    fighter_b_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    fight_id            INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    event_id            INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    predicted_winner    TEXT,
    predicted_method    TEXT,
    confidence_pct      INTEGER NOT NULL DEFAULT 50 CHECK (confidence_pct BETWEEN 0 AND 100),
    style_edge          TEXT,
    excitement_score    INTEGER NOT NULL DEFAULT 50 CHECK (excitement_score BETWEEN 0 AND 100),
    upset_risk          TEXT,
    analysis_text       TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_a_id, fighter_b_id, fight_id)
);

-- ----------------------------------------------------------------
-- suspensions (added v3.4.0, Phase B — Fighter suspensions).
--
-- One row per fighter suspension (drug test failure, behavioral
-- incident, repeated missed weight, post-fight brawl, social media
-- violation). Suspensions are RARE per the brief (1% drug test +
-- 0.5% behavior chance per fight) but generate BIG stories when
-- they happen — a champion failing a drug test is a generational
-- event. Per docs/FULL_BUILD_AUDIT.md §9a.
--
-- Suspension lifecycle:
--   1. _maybe_random_suspension (FIGHT_RESOLVED subscriber in
--      src/suspensions.py) rolls the dice on each resolved fight.
--      1% drug test failure, 0.5% behavior (higher for high-
--      aggression + low-discipline fighters). On trigger:
--      - drug_test_failure: 6-12 month suspension, morale -20,
--        marketability -15.
--      - behavior: 3-6 month suspension, morale -10.
--      Inserts a suspensions row with is_active=1, start_date =
--      event_date, end_date = start_date + duration_days.
--   2. check_suspension_recovery (TICK_ADVANCED subscriber in
--      src/suspensions.py) scans for active suspensions whose
--      end_date has passed. Sets is_active=0 and writes a clearance
--      news item (the fighter returns).
--   3. app._pick_matchup excludes fighters with is_active=1 (the
--      matchup SQL adds `AND fighter_id NOT IN (SELECT fighter_id
--      FROM suspensions WHERE is_active = 1)` alongside the
--      existing injury exclusion). A suspended fighter cannot be
--      booked until cleared.
--
-- 5 suspension_type values (CHECK constraint):
--   drug_test_failure       — failed a USADA / commission drug test
--                             (PEDs, diuretics, banned substances)
--   behavior                — behavioral incident (altercation with
--                             officials, refused media, etc.)
--   missed_weight_repeat   — repeat weight-cut miss (commission
--                             intervention — future Phase C task
--                             may wire this from weight cut log)
--   post_fight_brawl       — brawl after a fight (the infamous
--                             post-fight melee scenario)
--   social_media_violation  — social media post crossed the line
--                             (commission / promotion suspends)
--
-- duration_days is a stored INTEGER column (NOT shown to the player
-- per §14 — the news text uses word-form phrases like "six months"
-- or "the rest of the year", never the raw day count). It exists
-- only so check_suspension_recovery can compute end_date arithmetic
-- (end_date < current_date) without recomputing duration every tick.
--
-- description is a short admin note (NOT player-facing). Player-
-- facing narrative comes from the news items written by the news
-- engine subscriber (topic='suspension') with voice-layer-driven
-- headlines + body text.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suspensions (
    suspension_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    suspension_type   TEXT NOT NULL CHECK (suspension_type IN (
        'drug_test_failure', 'behavior', 'missed_weight_repeat',
        'post_fight_brawl', 'social_media_violation'
    )),
    start_date        TEXT NOT NULL,
    end_date          TEXT NOT NULL,
    duration_days     INTEGER NOT NULL CHECK (duration_days > 0),
    description       TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- agent_offers (added v3.5.0, Phase C — Agent offers / unknown
-- talent gamble system).
--
-- One row per agent offer — the agent calls the player with a
-- "mystery box" fighter: a vague description (voice descriptors
-- only, NO raw attributes per §14) with an asking price. The player
-- can sign (resolve_offer with accept=True → current_promotion_id
-- set + asking_price deducted from current_cash) or reject. Offers
-- expire after 14 days if unresolved (is_resolved=0, resolution=
-- 'expired').
--
-- The agent_offers table is the single table-group this task adds
-- (CONVENTIONS §5 — one table-group per task). Per the brief, this
-- is the "Talent Hunter" fantasy (CAGE_EMPIRE_SOUL.md Fantasy 1)
-- — finding greatness before anyone else. The description is
-- deliberately vague enough that the player doesn't know if they're
-- getting a future champion or a bust. This is a gamble, not a
-- guaranteed signing.
--
-- 5 offer_type values (CHECK constraint):
--   unknown_talent       — a brand-new fighter generated for the
--                          offer (the agent found someone off the
--                          radar). Description emphasizes "unknown"
--                          + nation + style archetype only.
--   washout_veteran      — an existing free agent who's a veteran
--                          past their prime. Description uses
--                          voice.describe_career_stage to hint at
--                          the stage without revealing age precisely.
--   style_specialist     — an existing free agent whose style
--                          archetype fills a gap in the roster.
--                          Description uses style adjective + voice
--                          descriptors for top attributes.
--   contender_release   — an existing free agent recently released
--                          by another promotion (was a contender).
--                          Description uses career_stage to hint
--                          at "former contender" without revealing
--                          the precise record.
--   prospect_gamble      — a brand-new fighter generated for the
--                          offer, but framed as a "high-risk,
--                          high-reward" prospect gamble. The
--                          potential is HIDDEN per §14 — the
--                          description is deliberately ambiguous
--                          ("might have something" / "raw talent").
--
-- asking_price is REAL (currency) — the price the player pays to
-- sign. The promotion's current_cash is deducted on resolve_offer
-- (the schema doesn't enforce this — the application code does).
-- fighter_description is the voice-layer-driven text the player
-- sees in the UI. NEVER contains raw numbers (potential, attributes,
-- age as int, record wins/losses) per CONVENTIONS §14.
--
-- is_resolved is 0/1 (CHECK). resolution is 'signed' / 'rejected' /
-- 'expired' (CHECK, NULL only while unresolved). resolution_date is
-- the date the player (or expiry) resolved the offer. expires_date
-- is offer_date + 14 days — past this date, the offer auto-expires.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_offers (
    offer_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id       INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    fighter_id         INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    offer_date         TEXT NOT NULL,
    offer_type         TEXT NOT NULL CHECK (offer_type IN (
        'unknown_talent', 'washout_veteran', 'style_specialist',
        'contender_release', 'prospect_gamble'
    )),
    asking_price       REAL NOT NULL,
    fighter_description TEXT NOT NULL,
    is_resolved        INTEGER NOT NULL DEFAULT 0 CHECK (is_resolved IN (0, 1)),
    resolution         TEXT CHECK (resolution IN ('signed', 'rejected', 'expired')),
    resolution_date    TEXT,
    expires_date       TEXT NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- show_ratings (added v3.6.0, Stage 5 — Task 26 Show rating engine).
--
-- One row per COMPLETED event (UNIQUE event_id — exactly one rating
-- per show). Computed by src/show_rating.py (event-bus subscriber
-- on EVENT_COMPLETED) — entirely event-bus-driven per CONVENTIONS
-- §15.4 (no inline side effects added to resolve_next_fight).
--
-- 5 rating axes (each 0-100, CHECK BETWEEN 0 AND 100):
--   fan_rating        — how much fans enjoyed the show (finishes,
--                       excitement, title fights, rivalries).
--   commercial_rating — how well the show did commercially
--                       (marketability, broadcast tier, attendance).
--   excitement_rating — how action-packed the show was (beats,
--                       damage, knockdowns, near-finishes).
--   quality_rating    — how technically skilled the fights were
--                       (avg fighter attributes, fight_iq, clean
--                       techniques landed).
--   overall_rating    — weighted average (fan 30%, commercial 20%,
--                       excitement 25%, quality 25%).
--
-- rating_description is a voice-layer descriptor (NO raw numbers
-- per CONVENTIONS §14):
--   90+ "an instant classic that fans will talk about for years"
--   75-89 "a highly entertaining show that delivered on expectations"
--   60-74 "a solid night of fights with some memorable moments"
--   40-59 "a decent show that failed to produce many highlights"
--   <40   "a lackluster card that left fans wanting more"
--
-- The src/venues.py module (Task 27) reads fan_rating from this
-- table to adjust market heat after each event (high fan rating →
-- +2 heat, poor events → -1 heat).
--
-- See docs/STAGES.md Task ID 26 for the brief.
-- See docs/CONVENTIONS.md §14 (voice layer) + §15.4 (event bus).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS show_ratings (
    rating_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    promotion_id        INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    fan_rating          INTEGER NOT NULL DEFAULT 50 CHECK (fan_rating BETWEEN 0 AND 100),
    commercial_rating   INTEGER NOT NULL DEFAULT 50 CHECK (commercial_rating BETWEEN 0 AND 100),
    excitement_rating   INTEGER NOT NULL DEFAULT 50 CHECK (excitement_rating BETWEEN 0 AND 100),
    quality_rating      INTEGER NOT NULL DEFAULT 50 CHECK (quality_rating BETWEEN 0 AND 100),
    overall_rating      INTEGER NOT NULL DEFAULT 50 CHECK (overall_rating BETWEEN 0 AND 100),
    rating_description  TEXT,
    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (event_id)
);

-- ----------------------------------------------------------------
-- player_settings (added v3.7.0, Stage 5 — Task Stage5-Final).
--
-- Simple key-value store for player preferences. One row per setting
-- (PRIMARY KEY setting_key). setting_value is TEXT — callers parse
-- (int, bool, comma-separated list, etc.) per the setting's contract.
-- updated_at is auto-stamped on every write.
--
-- 6 default settings seeded by _migrate_v3_7_0_add_player_settings:
--   news_filter_topics          = 'all'       (comma-separated topics
--                                              or 'all' to show all)
--   news_filter_min_importance  = '0'         (0=show all, 1=only
--                                              important, 2=only major)
--   news_volume                 = 'normal'    (verbose/normal/summary)
--   auto_save_frequency         = '30'        (days between auto-saves)
--   difficulty                  = 'normal'    (easy/normal/hard —
--                                              affects starting cash,
--                                              AI aggression, injury
--                                              rates)
--   display_descriptors         = 'true'      (show voice descriptors
--                                              instead of raw numbers —
--                                              should always be true
--                                              per CONVENTIONS §14)
--
-- The src/player_settings.py module is the reader/writer:
--   get_setting(conn, key, default=None) — reader
--   set_setting(conn, key, value)        — writer (upsert)
--   get_all_settings(conn)               — returns dict of all settings
--
-- The module is NOT event-bus-driven — settings are read by other
-- systems (news feed filter, auto-save cadence, etc.) at their own
-- cadence. register_subscribers is provided as a no-op for parity
-- with the other system modules (called from App.__init__ alongside
-- the 12 other register_subscribers calls).
--
-- See docs/STAGES.md Task Stage5-Final for the brief.
-- See docs/CONVENTIONS.md §5 (one table-group per task), §14 (voice
-- layer — display_descriptors='false' would violate §14, but the
-- setting exists for debugging / future accessibility modes).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_settings (
    setting_key        TEXT PRIMARY KEY,
    setting_value      TEXT NOT NULL,
    updated_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- interpretation_cache_meta (added v3.10.0, Phase 2 Task 2.0c —
-- Interpretation Layer cache version tracking).
--
-- Singleton row (CHECK meta_id = 1) that records the interpretation
-- engine version + last daily-pass metadata. When the engine's logic
-- changes (e.g., a new narrative family is added, the momentum
-- thresholds are retuned), engine_version is bumped — the daily pass
-- detects the mismatch and rebuilds all descriptor caches from
-- scratch on the next run.
--
-- This is the cache-invalidation handshake between code and data:
--   - Writer: the daily interpretation pass (snapshot_cache.py, Task 2.1)
--     updates last_built_date + last_built_fighter_count after each run.
--   - Reader: the same daily pass compares engine_version on disk to
--     its in-code constant; on mismatch, it forces a full rebuild.
--
-- Per CONVENTIONS §17.3, this is a CACHE table — the interpretation
-- layer is the ONLY writer. Office Mode UI never reads it directly
-- (it reads fighter_descriptors / gym_descriptors / etc. instead).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interpretation_cache_meta (
    meta_id                  INTEGER PRIMARY KEY DEFAULT 1,
    engine_version           TEXT NOT NULL DEFAULT '1.0.0',
    last_built_date          TEXT,
    last_built_fighter_count INTEGER DEFAULT 0,
    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    CHECK (meta_id = 1)  -- singleton row
);

-- ----------------------------------------------------------------
-- gym_descriptors (added v3.11.0, Phase 2 Task 2.1 — Snapshot Cache
-- gym-level identity narrative).
--
-- One row per gym (PK = gym_id). Stores a player-facing identity
-- narrative for the gym, computed by Task 2.8 (gym_identity_engine)
-- from the gym's 8 INT columns (wrestling_bias, striking_bias,
-- conditioning_bias, etc.) plus its active roster. The daily
-- interpretation pass in snapshot_cache.py refreshes this row; the
-- refresh_fighter single-fighter path does NOT touch it (gym identity
-- is a daily-pass concern, not a per-fight concern).
--
-- Columns:
--   identity_label:           short phrase ("The Wrestler Factory")
--   known_for:                one-sentence description of gym's strength
--   produces:                 fighter type the gym tends to develop
--                             ("grinding pressure fighters")
--   weakness:                 gym's characteristic blind spot
--                             ("high injury rate")
--   development_rating_desc:  voice phrase for the development_rating INT
--                             ("elite developer of talent")
--   snapshot_version:         incremented on each refresh (cache busting)
--   updated_at:               timestamp of last refresh
--
-- Per CONVENTIONS §17.3, this is a CACHE table — the interpretation
-- layer is the ONLY writer. Office Mode UI reads it directly.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gym_descriptors (
    gym_id                   INTEGER PRIMARY KEY REFERENCES gyms(gym_id) ON DELETE CASCADE,
    identity_label           TEXT,
    known_for                TEXT,
    produces                 TEXT,
    weakness                 TEXT,
    development_rating_desc  TEXT,
    snapshot_version         INTEGER NOT NULL DEFAULT 1,
    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- promotion_descriptors (added v3.11.0, Phase 2 Task 2.1 — Snapshot
-- Cache promotion-level summary).
--
-- One row per promotion (PK = promotion_id). Stores a player-facing
-- summary of the promotion's current state (prestige, market position,
-- roster quality) computed by the daily interpretation pass from the
-- promotions table + roster aggregate queries.
--
-- Columns:
--   prestige_desc:          voice phrase for the prestige INT
--                           ("global superpower" / "regional player")
--   market_position_desc:   voice phrase describing market standing
--   roster_quality_desc:    voice phrase for the roster's overall strength
--   snapshot_version:       incremented on each refresh (cache busting)
--   updated_at:             timestamp of last refresh
--
-- Per CONVENTIONS §17.3, this is a CACHE table — the interpretation
-- layer is the ONLY writer. Office Mode UI reads it directly.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS promotion_descriptors (
    promotion_id             INTEGER PRIMARY KEY REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    prestige_desc            TEXT,
    market_position_desc     TEXT,
    roster_quality_desc      TEXT,
    snapshot_version         INTEGER NOT NULL DEFAULT 1,
    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- ----------------------------------------------------------------
-- division_descriptors (added v3.11.0, Phase 2 Task 2.1 — Snapshot
-- Cache division (promotion × weight class) summary).
--
-- One row per (promotion, weight_class) pair — UNIQUE constraint
-- enforces the composite key, with an AUTOINCREMENT surrogate PK
-- (division_id) for reference simplicity. Stores a player-facing
-- summary of each division's depth + competitiveness, computed by
-- the daily interpretation pass from rankings + roster queries.
--
-- Columns:
--   division_id:            surrogate AUTOINCREMENT PK
--   promotion_id:           FK to promotions
--   weight_class_id:        FK to weight_classes
--   depth_desc:             voice phrase for division depth
--                           ("shallow — only 8 ranked fighters")
--   competitiveness_desc:   voice phrase for parity at the top
--                           ("wide open — 5 fighters within 10 rating points")
--   snapshot_version:       incremented on each refresh (cache busting)
--   updated_at:             timestamp of last refresh
--
-- Per CONVENTIONS §17.3, this is a CACHE table — the interpretation
-- layer is the ONLY writer. Office Mode UI reads it directly.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS division_descriptors (
    division_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id             INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    weight_class_id          INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE CASCADE,
    depth_desc               TEXT,
    competitiveness_desc     TEXT,
    snapshot_version         INTEGER NOT NULL DEFAULT 1,
    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (promotion_id, weight_class_id)
);

-- ----------------------------------------------------------------
-- daily_headlines (added v3.11.0, Phase 2 Task 2.1 — Snapshot Cache
-- daily news headlines).
--
-- One row per (headline_date, headline_type) pair — UNIQUE constraint
-- enforces the composite key, with an AUTOINCREMENT surrogate PK
-- (headline_id). At most 8 headlines per day (one per CHECK'd
-- headline_type). Written by Task 2.6 (headline_engine) at the end of
-- the daily interpretation pass; headlines older than a configurable
-- retention window are pruned by the same pass.
--
-- Columns:
--   headline_id:    surrogate AUTOINCREMENT PK
--   headline_date:  simulation date the headline applies to (TEXT YYYY-MM-DD)
--   headline_type:  one of 8 enumerated values (CHECK'd)
--   headline_text:  player-facing headline (voice-rendered, no raw numbers)
--   body_text:      optional 1-3 sentence body (voice-rendered)
--   fighter_id:     optional FK — the fighter the headline is about
--                   (NULL for "gym_of_month" or general headlines)
--   snapshot_version: incremented on each rewrite (cache busting)
--   created_at:     timestamp this headline row was inserted/refreshed
--
-- Per CONVENTIONS §17.3, this is a CACHE table — the interpretation
-- layer is the ONLY writer. Office Mode UI reads it directly.
-- Per §17.4 ("Rich Not Thin"): headline_text + body_text MUST be
-- voice phrases (no raw numbers). The CHECK constraint enumerates
-- the 8 headline types so a typo can't insert an unrecognized type.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_headlines (
    headline_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline_date            TEXT NOT NULL,
    headline_type            TEXT NOT NULL CHECK (headline_type IN (
        'top_story', 'upset_of_week', 'fastest_rising', 'biggest_fall',
        'contract_drama', 'gym_of_month', 'veteran_watch', 'prospect_watch'
    )),
    headline_text            TEXT NOT NULL,
    body_text                TEXT,
    fighter_id               INTEGER REFERENCES fighters(fighter_id),
    snapshot_version         INTEGER NOT NULL DEFAULT 1,
    created_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (headline_date, headline_type)
);

-- ----------------------------------------------------------------
-- player_decisions (added v3.16.0, Phase R — Reward Layer §6 Principle 4).
-- Append-only log of every player action whose consequence should
-- "echo" back later. The Dashboard's "ECHOES" section + the Fighter
-- Profile's "Your History with [Fighter]" section both read from
-- this table (per docs/REWARD_REVIEW.md §1.5 + §6 + the Phase R
-- brief). Without this log, the Agency reward stays at 3/10 forever.
--
-- Schema is intentionally narrow + index-friendly: every column the
-- Echoes engine reads in its 4 templates (sign / cut / book / scout)
-- is either on this table or joinable in <5ms with the existing
-- idx_player_decisions_* indexes below.
--
-- decision_type values (CHECK'd): the canonical set of player
-- actions. New actions added in later phases MUST extend this CHECK
-- (don't bypass it with a free-form TEXT). The 9 initial values
-- cover everything the player can do as of Phase R: sign, cut, book,
-- scout, hire_staff, fire_staff, assign_staff, set_ticket_price,
-- set_marketing, negotiate_contract.
--
-- All *_id columns are nullable (a 'set_ticket_price' decision has
-- no fighter_id; an 'hire_staff' decision has no fighter_id but has
-- a staff_id). The context_json TEXT column captures arbitrary
-- per-decision context (signing cost, opponent, offer terms) so the
-- Echoes engine can quote specifics ("signed for $120K") without
-- re-querying finance_transactions.
--
-- decision_date is the sim date (YYYY-MM-DD), not wall-clock —
-- echoes should reference the player's in-game timeline.
--
-- The 3 indexes cover the 3 read patterns:
--   idx_player_decisions_type  → "give me all 'sign' decisions"
--   idx_player_decisions_date  → "give me decisions from the last 120 days"
--   idx_player_decisions_fighter → "give me everything I did to fighter X"
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_decisions (
    decision_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_type      TEXT NOT NULL CHECK (decision_type IN (
        'sign', 'cut', 'book', 'scout',
        'hire_staff', 'fire_staff', 'assign_staff',
        'set_ticket_price', 'set_marketing', 'negotiate_contract'
    )),
    target_fighter_id  INTEGER,        -- nullable (NULL for staff decisions)
    target_staff_id    INTEGER,        -- nullable
    target_event_id    INTEGER,        -- nullable (for 'book' decisions)
    target_promo_id    INTEGER,        -- nullable (cross-promo context)
    decision_date      TEXT NOT NULL,  -- sim date (YYYY-MM-DD)
    context_json       TEXT,           -- arbitrary context (signing cost, opponent, etc.)
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_player_decisions_type
    ON player_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_player_decisions_date
    ON player_decisions(decision_date);
CREATE INDEX IF NOT EXISTS idx_player_decisions_fighter
    ON player_decisions(target_fighter_id);

-- ----------------------------------------------------------------
-- daily_echoes (added v3.16.0, Phase R — Reward Layer §1.5 + §6).
-- Cache table for the daily-generated "echo" phrases surfaced on
-- the Dashboard. Same pattern as daily_headlines: written by the
-- interpretation layer (src/interpretation/echoes_engine.py) on
-- every Advance Day, read by app_web.get_dashboard_data in one
-- query. UNIQUE (echo_date, echo_slot) so re-running for the same
-- date overwrites instead of duplicating (idempotent — matches
-- daily_headlines behavior).
--
-- echo_slot is an integer 1-3 (the Dashboard shows up to 3 echoes
-- per day, in slot order). Each row carries:
--   phrase        — the ≤120-char voice phrase ("Since you signed X in May, he's won 4 straight.")
--   decision_id   — link back to the player_decisions row it echoes from
--   target_fighter_id — for hyperlink rendering (NULL = no fighter link)
--   link_to_screen — 'fighter_profile' | 'past_events' (which screen to navigate to)
--
-- Per CONVENTIONS §17.3, this is a CACHE table — only echoes_engine
-- writes to it. The Dashboard reads it directly (no join needed
-- beyond the fighter name lookup for the hyperlink label).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_echoes (
    echo_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    echo_date          TEXT NOT NULL,
    echo_slot          INTEGER NOT NULL CHECK (echo_slot BETWEEN 1 AND 5),
    echo_type          TEXT NOT NULL CHECK (echo_type IN (
        'signing_echo', 'cut_echo', 'booking_echo', 'scouting_echo'
    )),
    phrase             TEXT NOT NULL,
    decision_id        INTEGER,        -- link back to player_decisions (nullable for safety)
    target_fighter_id  INTEGER,        -- for hyperlink rendering (nullable)
    link_to_screen     TEXT,           -- 'fighter_profile' | 'past_events' | NULL
    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (echo_date, echo_slot)
);
CREATE INDEX IF NOT EXISTS idx_daily_echoes_date
    ON daily_echoes(echo_date DESC);

-- ----------------------------------------------------------------
-- bidding_alerts (added v3.25.0, Phase M3.2 — docs/MASTER_PLAN_
-- MATCHMAKING.md §2.2 Rival AI signing — include player in bidding
-- wars).
--
-- Persistent store for "rival AI is pursuing this free agent" alerts
-- surfaced on the Dashboard. When a rival AI decides to pursue a FA
-- (signing_agent.resolve_bidding_wars produces a winning intent), the
-- signing is DEFERRED by decision_window_days (default 3) so the
-- player has a window to counter-offer via app_web.counter_offer.
--
-- Lifecycle:
--   1. signing_agent.resolve_bidding_wars INSERTs a row with
--      status='pending' + fires Events.SIGNING_INTENT on the bus.
--      The rival AI's signing is NOT executed yet.
--   2. The player can call app_web.counter_offer(fighter_id, salary,
--      signing_bonus). counter_offer looks up the pending alert,
--      computes both offer_scores (rival AI's stored score + the
--      player's score from the unified formula), the fighter chooses
--      the higher score (with ±5% randomness for drama), and the
--      winner signs via sign_free_agent. The alert is marked
--      'won_by_player' or 'won_by_rival' depending on the outcome.
--   3. If the player doesn't respond before expiry_date, the daily
--      tick (_check_bidding_alerts_expiry in signing_agent) signs
--      the fighter with the rival AI's intent + marks the alert
--      'won_by_rival' + writes a "you lost [Fighter] to [Rival]"
--      news item (if the player has a selected promo).
--   4. If the fighter is no longer a free agent when the daily tick
--      tries to sign (e.g., the player signed them directly via
--      sign_free_agent — which is BLOCKED when a pending alert
--      exists, but defensive), the alert is marked 'lost_race'.
--
-- Voice compliance (CONVENTIONS §14): no raw potential / realization
-- numbers appear in the UI text — the dashboard renders salary in
-- $K/M format + uses voice phrases for promo archetype fit.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bidding_alerts (
    alert_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id            INTEGER NOT NULL REFERENCES fighters(fighter_id)
                              ON DELETE CASCADE,
    rival_promo_id        INTEGER NOT NULL REFERENCES promotions(promotion_id)
                              ON DELETE CASCADE,
    -- The rival AI's pre-computed offer (frozen at intent time so the
    -- counter_offer comparison uses the same numbers).
    offered_salary        REAL NOT NULL,        -- $/yr
    offered_bonus         REAL NOT NULL DEFAULT 0,  -- $ upfront
    offer_score           REAL NOT NULL,        -- 0..1 (rival AI's score)
    -- The decision window: player has this many sim-days to respond.
    intent_date           TEXT NOT NULL,        -- sim date 'YYYY-MM-DD'
    expiry_date           TEXT NOT NULL,        -- intent_date + window
    decision_window_days  INTEGER NOT NULL DEFAULT 3
                              CHECK (decision_window_days BETWEEN 1 AND 14),
    -- Status lifecycle:
    --   pending         → alert active, awaiting player response
    --   won_by_player   → player counter-offered + won the bidding war
    --   won_by_rival    → rival AI signed (window expired OR player
    --                     counter-offered but lost)
    --   lost_race       → fighter no longer FA when expiry tick ran
    --                     (e.g., signed by another promo directly)
    status                TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN (
                                  'pending', 'won_by_player',
                                  'won_by_rival', 'lost_race'
                              )),
    -- Captured at resolution time for the "you lost X to Y" news item.
    player_offer_salary   REAL,                 -- NULL until player counters
    player_offer_bonus    REAL,
    player_offer_score    REAL,
    resolved_date         TEXT,
    created_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_bidding_alerts_fighter
    ON bidding_alerts(fighter_id);
CREATE INDEX IF NOT EXISTS idx_bidding_alerts_status
    ON bidding_alerts(status, expiry_date);
CREATE INDEX IF NOT EXISTS idx_bidding_alerts_rival
    ON bidding_alerts(rival_promo_id);

-- ----------------------------------------------------------------
-- rival_ai_memory (added v3.34.0, HW10-W21W22 — rival AI memory).
--
-- The rival AI used to be STATELESS PER TICK — each rival promo
-- scheduled events, signed free agents, and resolved fights without
-- remembering its own past results, bidding wars lost, fighters
-- signed/released, or title histories. GPT's W21 feedback: "Rival
-- AI should react to its own previous results." GPT's W22 feedback:
-- "Rival promotions should remember past interactions."
--
-- This table gives every rival promo a memory log. Each row is one
-- memory of a specific type (event_result, signing_won, title_loss,
-- etc.). Subscribers on the event bus write memories when something
-- happens; the rival AI's decision functions READ memories to shape
-- future decisions ("we just had a flop event, don't book another
-- one too soon", "we lost a bidding war last week, be more
-- aggressive on the next target", "this fighter lost us a title,
-- consider releasing them").
--
-- Lifecycle:
--   1. EVENT_COMPLETED → 'event_result' memory with attendance/profit.
--   2. FIGHTER_SIGNED  → 'signing_won' memory for the signing promo.
--      (signing_missed is written when a bidding-war loser would have
--      wanted the fighter; rivalry_fuelled is written on bankruptcies.)
--   3. SIGNING_INTENT expiry (rival AI lost a bidding war) →
--      'bidding_war_lost' memory for the rival promo.
--   4. TITLE_CHANGED  → 'title_win' memory if the promo gains a
--      champion; 'title_loss' memory if the promo's champion was
--      dethroned.
--   5. PROMOTION_BANKRUPT → 'rivalry_fuelled' memory for every other
--      rival promo (the bankruptcy is an opportunity for competitors).
--   6. Weekly TICK_ADVANCED subscriber decays salience by -1. When
--      salience hits 0, the memory row is DELETED (forgotten) — old
--      memories should not bloat the table.
--
-- Readers:
--   - event_scheduler: scans recent 'event_result' memories; if the
--     last event was a flop (low attendance/profit), suppress
--     scheduling for one cycle (don't book another show too soon
--     after a flop).
--   - signing_agent: scans recent 'bidding_war_lost' memories; if
--     the promo recently lost a bidding war, raise the offer_score
--     (don't lose the next one).
--   - cutting_agent: scans 'title_loss' memories; if a fighter was
--     involved in a recent title loss, raise their cut_risk (they've
--     peaked).
--
-- Salience semantics:
--   - 0..100, default 50 (a "neutral" memory — recorded but not
--     especially influential).
--   - Writers tune the initial salience: 'title_win'=80, 'title_loss'
--     =70, 'bidding_war_lost'=60, 'event_result'=50 (default),
--     'signing_won'=40, 'rivalry_fuelled'=50.
--   - The weekly decay (-1) means a memory at salience=50 is
--     "forgotten" in ~50 weeks (~1 sim year). High-salience memories
--     (title wins/losses) persist longer.
--   - Salience=0 → DELETE (not kept). This keeps the table from
--     growing unboundedly.
--
-- Index design:
--   - idx_rival_ai_memory_promo_type_date: covers the "what does
--     this promo remember about X recently?" lookup used by readers.
--   - idx_rival_ai_memory_promo_salience: covers the "what does
--     this promo remember most strongly?" lookup (future use).
--
-- Voice compliance (CONVENTIONS §14): the context_json is internal
-- state, never rendered in the UI directly. The rival AI's memory
-- influences its decisions, which manifest as news items / events /
-- signings — already voice-layer-compliant.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rival_ai_memory (
    memory_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id         INTEGER NOT NULL REFERENCES promotions(promotion_id)
                             ON DELETE CASCADE,
    memory_type          TEXT NOT NULL
                             CHECK (memory_type IN (
                                 'event_result', 'signing_missed',
                                 'signing_won', 'title_loss', 'title_win',
                                 'bidding_war_lost', 'bidding_war_won',
                                 'fighter_released', 'rivalry_fuelled'
                             )),
    target_fighter_id    INTEGER REFERENCES fighters(fighter_id)
                             ON DELETE SET NULL,
    target_promotion_id  INTEGER REFERENCES promotions(promotion_id)
                             ON DELETE SET NULL,
    memory_date          TEXT NOT NULL,        -- sim date 'YYYY-MM-DD'
    context_json         TEXT,                 -- arbitrary JSON
    salience             INTEGER NOT NULL DEFAULT 50
                             CHECK (salience BETWEEN 0 AND 100),
    created_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_rival_ai_memory_promo_type_date
    ON rival_ai_memory (promotion_id, memory_type, memory_date DESC);
CREATE INDEX IF NOT EXISTS idx_rival_ai_memory_promo_salience
    ON rival_ai_memory (promotion_id, salience DESC);

-- ============================================================
-- Phase 4 — Performance indexes (v3.13.0).
-- These are duplicated here (in SCHEMA_SQL) so fresh --fresh builds
-- get them from the start. The _migrate_v3_13_0_add_performance_indexes
-- migration applies them to existing DBs (CREATE INDEX IF NOT EXISTS
-- is idempotent, so re-running the migration on a DB that already has
-- the indexes from SCHEMA_SQL is a no-op).
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_fighters_promo_active
    ON fighters (current_promotion_id, is_active, is_retired);
CREATE INDEX IF NOT EXISTS idx_fighters_weight_class
    ON fighters (weight_class_id);
CREATE INDEX IF NOT EXISTS idx_fighters_gender
    ON fighters (gender);
CREATE INDEX IF NOT EXISTS idx_fight_history_fighter
    ON fight_history (fighter_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_fight_history_opponent
    ON fight_history (opponent_id);
CREATE INDEX IF NOT EXISTS idx_news_items_published
    ON news_items (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_headlines_date_type
    ON daily_headlines (headline_date DESC, headline_type);
CREATE INDEX IF NOT EXISTS idx_titles_champion
    ON titles (current_champion_fighter_id);
CREATE INDEX IF NOT EXISTS idx_rankings_fighter
    ON rankings (fighter_id);
CREATE INDEX IF NOT EXISTS idx_injuries_fighter_active
    ON injuries (fighter_id, is_active);
CREATE INDEX IF NOT EXISTS idx_suspensions_fighter_active
    ON suspensions (fighter_id, is_active);
CREATE INDEX IF NOT EXISTS idx_scouting_reports_target
    ON scouting_reports (target_fighter_id);
-- HW8.2 — per-tick perf indexes (added after HW6.3 soak test
-- surfaced super-linear cost growth from full-table scans on
-- training_camps + fight_beats). See _migrate_v3_31_0_add_perf_indexes.
CREATE INDEX IF NOT EXISTS idx_training_camps_active_window
    ON training_camps (is_active, is_completed, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_training_camps_fighter
    ON training_camps (fighter_id, is_completed, end_date);
CREATE INDEX IF NOT EXISTS idx_fight_beats_fight
    ON fight_beats (fight_id, round_number);
-- TIER2-5YEAR §T2.3 — additional perf indexes for 5-year soak.
-- See _migrate_v3_35_0_add_perf_indexes_2.
CREATE INDEX IF NOT EXISTS idx_news_items_importance_date
    ON news_items (importance, published_at);
CREATE INDEX IF NOT EXISTS idx_commentary_segments_fight
    ON commentary_segments (fight_id);
CREATE INDEX IF NOT EXISTS idx_training_camps_completed_end
    ON training_camps (is_completed, end_date);

-- ============================================================
-- HW2.1 — simulation_tick_health (v3.29.0).
-- One row per tick. Records tick duration, EventBus subscriber
-- success/failure counts, a JSON blob of subscriber errors
-- (with traceback + sim date), and aggregate counts of the
-- tick's side effects (events/fights/fighters/injuries/contracts
-- /titles/rankings/finance/news/social/memory).
--
-- tick_success:
--   1  = HEALTHY  (no subscriber failures)
--   0  = DEGRADED (>= 1 subscriber failure, tick completed)
--   -1 = BROKEN   (tick itself crashed — set by run_tick's
--                  try/except wrapper before the summary row
--                  is written)
--
-- Read by compute_world_health() (HW2.4) + get_world_health()
-- API method (HW2.4). Written by tick_processor.run_tick (HW2.1).
-- ============================================================
CREATE TABLE IF NOT EXISTS simulation_tick_health (
    tick_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_date              TEXT NOT NULL,
    tick_duration_ms       INTEGER NOT NULL DEFAULT 0,
    tick_success           INTEGER NOT NULL DEFAULT 1
                               CHECK (tick_success IN (-1, 0, 1)),
    health_status          TEXT NOT NULL DEFAULT 'HEALTHY'
                               CHECK (health_status IN
                                      ('HEALTHY', 'DEGRADED', 'BROKEN')),
    subscribers_invoked    INTEGER NOT NULL DEFAULT 0,
    subscribers_succeeded  INTEGER NOT NULL DEFAULT 0,
    subscribers_failed     INTEGER NOT NULL DEFAULT 0,
    errors_json            TEXT,
    events_scheduled       INTEGER NOT NULL DEFAULT 0,
    events_completed       INTEGER NOT NULL DEFAULT 0,
    fights_resolved        INTEGER NOT NULL DEFAULT 0,
    fighters_retired       INTEGER NOT NULL DEFAULT 0,
    fighters_regen         INTEGER NOT NULL DEFAULT 0,
    injuries_created       INTEGER NOT NULL DEFAULT 0,
    injuries_recovered     INTEGER NOT NULL DEFAULT 0,
    contracts_changed      INTEGER NOT NULL DEFAULT 0,
    title_changes          INTEGER NOT NULL DEFAULT 0,
    ranking_changes        INTEGER NOT NULL DEFAULT 0,
    finance_transactions   INTEGER NOT NULL DEFAULT 0,
    news_generated         INTEGER NOT NULL DEFAULT 0,
    social_posts_generated INTEGER NOT NULL DEFAULT 0,
    memories_generated     INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_tick_health_date
    ON simulation_tick_health (tick_date DESC);
CREATE INDEX IF NOT EXISTS idx_tick_health_status
    ON simulation_tick_health (tick_success, tick_date DESC);

-- HW8.3 — global daily news cap trigger (catches ALL writes,
-- including direct INSERTs that bypass news._write_news_item).
-- HW10.1 — importance-aware: LEGENDARY + MAJOR items bypass the cap
-- (player never misses title changes, HoF, major signings, retirements).
-- See _migrate_v3_33_0_news_cap_importance_aware.
DROP TRIGGER IF EXISTS trg_news_items_global_daily_cap;
CREATE TRIGGER trg_news_items_global_daily_cap
BEFORE INSERT ON news_items
WHEN (
    SELECT COUNT(*) FROM news_items
    WHERE date(COALESCE(published_at, CURRENT_TIMESTAMP))
        = date(COALESCE(NEW.published_at, CURRENT_TIMESTAMP))
) >= 30
AND COALESCE(NEW.importance, 'ROUTINE') NOT IN ('LEGENDARY', 'MAJOR')
BEGIN
    SELECT RAISE(IGNORE);
END;
"""

def _has_column(conn, table, column):
    """Return True if `column` exists on `table` (defensive idempotency check)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _has_table(conn, table):
    """Return True if `table` exists in sqlite_master."""
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _has_check_constraint(conn, table, fragment):
    """Return True if `table` has a CHECK constraint whose SQL contains
    `fragment` (case-insensitive). Used to test idempotency of CHECK-
    adding migrations (SQLite has no ALTER TABLE ADD CHECK, so CHECKs
    can only be added via table rebuild — rare and explicit).
    """
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if sql is None or sql[0] is None:
        return False
    return fragment.lower() in sql[0].lower()


# ----------------------------------------------------------------
# Migration functions.
#
# Each migration is idempotent — it checks the current schema state
# (via _has_column / _has_table / _has_check_constraint) before
# applying its change. This is REQUIRED because:
#   1. The migration runner records the migration name in
#      schema_migrations AFTER it runs. If a migration crashes mid-
#      way, the next run re-executes it — the partial work must be
#      safe to re-apply.
#   2. The --fresh path also calls every migration after
#      executescript(SCHEMA_SQL), to keep the migration functions
#      exercised. CREATE TABLE IF NOT EXISTS + _has_column guards
#      make this safe (the migrations are no-ops on a fresh build).
#
# Each migration function takes a sqlite3.Connection (caller commits)
# and returns nothing. Errors raise sqlite3.Error (caller aborts).
# ----------------------------------------------------------------

def _migrate_v2_2_0_add_fighter_depth(conn):
    """Task 14.5+14.6+14.7 — fighter schema expansion.

    Adds 21 attribute columns, 17 personality columns, 4 physical
    columns to fighters; creates fighter_attributes (25 attrs),
    fighter_personality (20 traits), fighter_career (potential,
    career_health, title_reigns), fight_rounds, style_archetypes,
    personality_archetypes, regen_lineage, fighter_memory_links.

    This migration is a no-op on a fresh --fresh build (the
    SCHEMA_SQL already includes all these tables/columns). It exists
    to upgrade a v2.1.0 DB to v2.2.0 without data loss.
    """
    # Fighter physical columns
    for col, decl in [
        ("height_cm", "INTEGER"),
        ("reach_cm", "INTEGER"),
        ("stance", "TEXT DEFAULT 'Orthodox'"),
        ("handedness", "TEXT DEFAULT 'Orthodox'"),
        ("injury_proneness", "INTEGER NOT NULL DEFAULT 50"),
        ("weight_cut_difficulty", "INTEGER NOT NULL DEFAULT 50"),
        ("consistency", "INTEGER NOT NULL DEFAULT 50"),
        ("clutch_factor", "INTEGER NOT NULL DEFAULT 50"),
        ("marketability", "INTEGER NOT NULL DEFAULT 50"),
        ("fan_friendliness", "INTEGER NOT NULL DEFAULT 50"),
        ("promo_boost", "INTEGER NOT NULL DEFAULT 50"),
        ("preferred_gameplans", "TEXT"),
        ("bad_matchup_tags", "TEXT"),
        ("is_deceased", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if not _has_column(conn, "fighters", col):
            conn.execute(f"ALTER TABLE fighters ADD COLUMN {col} {decl}")

    # fighter_attributes table
    if not _has_table(conn, "fighter_attributes"):
        # Build the CREATE TABLE statement inline (matches SCHEMA_SQL)
        attr_cols = [
            "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
            "head_movement", "footwork", "clinch_striking", "clinch_offense",
            "clinch_defense", "takedown_offense", "takedown_defense",
            "top_control", "bottom_game", "submission_offense",
            "submission_defense", "scramble_ability", "cage_wrestling",
            "recovery_rate", "speed_explosiveness", "strength",
            "durability", "flexibility", "adaptability", "cardio",
            "fight_iq", "chin",
        ]
        col_decls = ",\n    ".join(
            f"{c} INTEGER NOT NULL DEFAULT 50 CHECK ({c} BETWEEN 0 AND 100)"
            for c in attr_cols
        )
        conn.execute(
            f"CREATE TABLE fighter_attributes (\n"
            f"    fighter_attribute_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            f"    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            f"    {col_decls},\n"
            f"    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            f"    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            f"    UNIQUE (fighter_id)\n"
            f")"
        )

    # fighter_personality table
    if not _has_table(conn, "fighter_personality"):
        pers_cols = [
            "aggression", "composure", "morale", "risk_taking",
            "killer_instinct", "grit", "discipline", "patience",
            "ambition", "loyalty", "charisma", "attention_seeking",
            "coachability", "professionalism", "ego", "resilience",
            "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance",
        ]
        col_decls = ",\n    ".join(
            f"{c} INTEGER NOT NULL DEFAULT 50 CHECK ({c} BETWEEN 0 AND 100)"
            for c in pers_cols
        )
        conn.execute(
            f"CREATE TABLE fighter_personality (\n"
            f"    fighter_personality_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            f"    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            f"    {col_decls},\n"
            f"    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            f"    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            f"    UNIQUE (fighter_id)\n"
            f")"
        )

    # fighter_career table
    if not _has_table(conn, "fighter_career"):
        conn.execute(
            "CREATE TABLE fighter_career (\n"
            "    fighter_career_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    record_wins INTEGER NOT NULL DEFAULT 0,\n"
            "    record_losses INTEGER NOT NULL DEFAULT 0,\n"
            "    record_draws INTEGER NOT NULL DEFAULT 0,\n"
            "    win_streak INTEGER NOT NULL DEFAULT 0,\n"
            "    loss_streak INTEGER NOT NULL DEFAULT 0,\n"
            "    career_health INTEGER NOT NULL DEFAULT 100 CHECK (career_health BETWEEN 0 AND 100),\n"
            "    potential INTEGER NOT NULL DEFAULT 50 CHECK (potential BETWEEN 0 AND 100),\n"
            "    title_reigns INTEGER NOT NULL DEFAULT 0,\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_id)\n"
            ")"
        )

    # fight_rounds table
    if not _has_table(conn, "fight_rounds"):
        conn.execute(
            "CREATE TABLE fight_rounds (\n"
            "    fight_round_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fight_id INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,\n"
            "    round_number INTEGER NOT NULL,\n"
            "    fighter_a_gas_remaining REAL,\n"
            "    fighter_b_gas_remaining REAL,\n"
            "    momentum_end REAL,\n"
            "    a_score INTEGER NOT NULL DEFAULT 0,\n"
            "    b_score INTEGER NOT NULL DEFAULT 0,\n"
            "    finish_beat_id INTEGER,\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fight_id, round_number)\n"
            ")"
        )

    # style_archetypes table
    if not _has_table(conn, "style_archetypes"):
        conn.execute(
            "CREATE TABLE style_archetypes (\n"
            "    style_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    name TEXT NOT NULL UNIQUE,\n"
            "    description TEXT,\n"
            "    bias_json TEXT NOT NULL DEFAULT '{}',\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )

    # personality_archetypes table
    if not _has_table(conn, "personality_archetypes"):
        conn.execute(
            "CREATE TABLE personality_archetypes (\n"
            "    personality_archetype_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    name TEXT NOT NULL UNIQUE,\n"
            "    description TEXT,\n"
            "    bias_json TEXT NOT NULL DEFAULT '{}',\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )

    # regen_lineage table
    if not _has_table(conn, "regen_lineage"):
        conn.execute(
            "CREATE TABLE regen_lineage (\n"
            "    regen_lineage_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    retiring_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    replacement_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    style_dna_archetype_id INTEGER REFERENCES style_archetypes(style_archetype_id) ON DELETE SET NULL,\n"
            "    regen_date TEXT NOT NULL,\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (retiring_fighter_id, replacement_fighter_id)\n"
            ")"
        )

    # fighter_memory_links table
    if not _has_table(conn, "fighter_memory_links"):
        conn.execute(
            "CREATE TABLE fighter_memory_links (\n"
            "    memory_link_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    link_type TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history')),\n"
            "    link_strength INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_id, linked_fighter_id, link_type)\n"
            ")"
        )


def _migrate_v2_3_0_add_beat_engine_depth(conn):
    """Task B2 — beat engine depth. Modifies fight_beats.outcome CHECK
    (adds 'knockdown' and 'near_finish'). SQLite cannot ALTER a CHECK
    constraint — requires a table rebuild. On a fresh --fresh build
    the SCHEMA_SQL already has the new CHECK; on a migration from
    v2.2.0, we rebuild the table.

    Also adds fatigue/momentum/finish columns to fight_rounds if
    missing (those columns were added in v2.2.0's SCHEMA_SQL but
    some early v2.2.0 DBs may predate them).
    """
    # fight_rounds fatigue/momentum/finish columns
    for col, decl in [
        ("fighter_a_gas_remaining", "REAL"),
        ("fighter_b_gas_remaining", "REAL"),
        ("momentum_end", "REAL"),
        ("finish_beat_id", "INTEGER"),
    ]:
        if not _has_column(conn, "fight_rounds", col):
            conn.execute(f"ALTER TABLE fight_rounds ADD COLUMN {col} {decl}")

    # fight_beats.outcome CHECK expansion — only rebuild if the
    # existing CHECK doesn't include 'knockdown'.
    if not _has_check_constraint(conn, "fight_beats", "knockdown"):
        # Defensive: only attempt the rebuild if fight_beats exists.
        if _has_table(conn, "fight_beats"):
            # SQLite table-rebuild pattern: rename, create new, copy,
            # drop old. We accept the data-loss risk because this
            # migration runs once per DB and any v2.2.0 DB has at
            # most a handful of test fight_beats rows.
            conn.executescript("""
                ALTER TABLE fight_beats RENAME TO fight_beats_old;
            """)
            # The new fight_beats table is created by SCHEMA_SQL on
            # --fresh, or by this migration on --migrate. The CREATE
            # statement must match SCHEMA_SQL exactly.
            conn.executescript("""
                CREATE TABLE fight_beats (
                    fight_beat_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    fight_id         INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
                    round_number     INTEGER NOT NULL,
                    beat_number      INTEGER NOT NULL,
                    phase            TEXT NOT NULL CHECK (phase IN ('standing','clinch','cage','ground_top','ground_bottom','scramble')),
                    initiator_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
                    target_fighter_id   INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
                    outcome          TEXT NOT NULL CHECK (outcome IN ('strike_landed','strike_missed','strike_blocked','takedown_attempted','takedown_landed','takedown_defended','submission_attempted','submission_landed','submission_defended','clinch_engaged','clinch_break','position_improved','position_lost','knockdown','near_finish','no_change')),
                    damage_dealt     INTEGER NOT NULL DEFAULT 0,
                    gas_cost_initiator INTEGER NOT NULL DEFAULT 0,
                    gas_cost_target  INTEGER NOT NULL DEFAULT 0,
                    momentum_delta   REAL NOT NULL DEFAULT 0,
                    commentary       TEXT,
                    created_at       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                );
                INSERT INTO fight_beats (fight_beat_id, fight_id, round_number, beat_number, phase, initiator_fighter_id, target_fighter_id, outcome, damage_dealt, gas_cost_initiator, gas_cost_target, momentum_delta, commentary, created_at)
                SELECT fight_beat_id, fight_id, round_number, beat_number, phase, initiator_fighter_id, target_fighter_id,
                       CASE WHEN outcome IN ('strike_landed','strike_missed','strike_blocked','takedown_attempted','takedown_landed','takedown_defended','submission_attempted','submission_landed','submission_defended','clinch_engaged','clinch_break','position_improved','position_lost','knockdown','near_finish','no_change')
                            THEN outcome ELSE 'no_change' END,
                       damage_dealt, gas_cost_initiator, gas_cost_target, momentum_delta, commentary, created_at
                FROM fight_beats_old;
                DROP TABLE fight_beats_old;
            """)


def _migrate_v2_4_0_add_injuries(conn):
    """Task 15 — injuries table."""
    if not _has_table(conn, "injuries"):
        conn.execute(
            "CREATE TABLE injuries (\n"
            "    injury_id              INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id             INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    injury_type            TEXT NOT NULL,\n"
            "    body_area              TEXT NOT NULL CHECK (body_area IN ('head','face','jaw','nose','eye','neck','shoulder','arm','elbow','wrist','hand','ribs','back','hip','knee','ankle','foot','general')),\n"
            "    severity               INTEGER NOT NULL DEFAULT 5 CHECK (severity BETWEEN 1 AND 10),\n"
            "    start_date             TEXT NOT NULL,\n"
            "    projected_return_date  TEXT,\n"
            "    actual_return_date     TEXT,\n"
            "    long_term_damage       INTEGER NOT NULL DEFAULT 0 CHECK (long_term_damage BETWEEN 0 AND 100),\n"
            "    career_risk            INTEGER NOT NULL DEFAULT 0 CHECK (career_risk BETWEEN 0 AND 100),\n"
            "    is_active              INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),\n"
            "    fight_id               INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,\n"
            "    event_id               INTEGER REFERENCES events(event_id) ON DELETE SET NULL,\n"
            "    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    updated_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v2_5_0_add_training_camps(conn):
    """Task 16 — training camps table."""
    if not _has_table(conn, "training_camps"):
        conn.execute(
            "CREATE TABLE training_camps (\n"
            "    training_camp_id           INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id                 INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    gym_id                     INTEGER REFERENCES gyms(gym_id) ON DELETE SET NULL,\n"
            "    event_id                   INTEGER REFERENCES events(event_id) ON DELETE SET NULL,\n"
            "    fight_id                   INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,\n"
            "    start_date                 TEXT NOT NULL,\n"
            "    end_date                   TEXT NOT NULL,\n"
            "    camp_duration_days         INTEGER NOT NULL DEFAULT 14 CHECK (camp_duration_days >= 0),\n"
            "    camp_focus                 TEXT NOT NULL DEFAULT 'general' CHECK (camp_focus IN ('striking','grappling','wrestling','conditioning','submission','clinch','general','weight_cut')),\n"
            "    camp_morale                INTEGER NOT NULL DEFAULT 50 CHECK (camp_morale BETWEEN 0 AND 100),\n"
            "    camp_fatigue               INTEGER NOT NULL DEFAULT 0 CHECK (camp_fatigue BETWEEN 0 AND 100),\n"
            "    camp_injury_risk           INTEGER NOT NULL DEFAULT 0 CHECK (camp_injury_risk BETWEEN 0 AND 100),\n"
            "    camp_weight_cut_pressure   INTEGER NOT NULL DEFAULT 0 CHECK (camp_weight_cut_pressure BETWEEN 0 AND 100),\n"
            "    attribute_changes          TEXT,\n"
            "    camp_result_summary        TEXT,\n"
            "    is_active                  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),\n"
            "    is_completed               INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),\n"
            "    created_at                 TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    updated_at                 TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v2_6_0_world_seed_prep(conn):
    """Task 16.5 — world seed prep. Adds regions.nation_id,
    weight_classes.gender + display_order, fighter_bios, hall_of_fame.
    """
    # regions.nation_id
    if not _has_column(conn, "regions", "nation_id"):
        conn.execute(
            "ALTER TABLE regions ADD COLUMN nation_id INTEGER "
            "REFERENCES nations(nation_id) ON DELETE SET NULL"
        )

    # weight_classes.gender
    if not _has_column(conn, "weight_classes", "gender"):
        conn.execute(
            "ALTER TABLE weight_classes ADD COLUMN gender TEXT "
            "NOT NULL DEFAULT 'male' CHECK (gender IN ('male', 'female'))"
        )

    # weight_classes.display_order
    if not _has_column(conn, "weight_classes", "display_order"):
        conn.execute(
            "ALTER TABLE weight_classes ADD COLUMN display_order "
            "INTEGER NOT NULL DEFAULT 0"
        )

    # fighter_bios table
    if not _has_table(conn, "fighter_bios"):
        conn.execute(
            "CREATE TABLE fighter_bios (\n"
            "    fighter_id  INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    bio_text    TEXT NOT NULL,\n"
            "    bio_tone    TEXT NOT NULL DEFAULT 'neutral'\n"
            "                CHECK (bio_tone IN ('neutral', 'unproven_prospect',\n"
            "                                    'grizzled_veteran', 'champion_reign',\n"
            "                                    'fallen_contender', 'journeyman',\n"
            "                                    'cult_hero', 'mid_carder',\n"
            "                                    'late_bloomer', 'enforcer')),\n"
            "    created_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    updated_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )

    # hall_of_fame table
    if not _has_table(conn, "hall_of_fame"):
        conn.execute(
            "CREATE TABLE hall_of_fame (\n"
            "    fighter_id          INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    inducted_date       TEXT NOT NULL,\n"
            "    career_summary      TEXT NOT NULL,\n"
            "    career_highlights   TEXT,\n"
            "    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v2_7_0_add_weight_cut_log(conn):
    """Task 17 — weight cuts. Adds the weight_cut_log table."""
    if not _has_table(conn, "weight_cut_log"):
        conn.execute(
            "CREATE TABLE weight_cut_log (\n"
            "    weight_cut_log_id      INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id             INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    fight_id               INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,\n"
            "    event_id               INTEGER REFERENCES events(event_id) ON DELETE SET NULL,\n"
            "    weight_class_id        INTEGER REFERENCES weight_classes(weight_class_id) ON DELETE SET NULL,\n"
            "    cut_date               TEXT NOT NULL,\n"
            "    target_weight_kg       REAL NOT NULL,\n"
            "    actual_weight_kg       REAL,\n"
            "    weight_missed_kg       REAL NOT NULL DEFAULT 0.0,\n"
            "    cut_outcome            TEXT NOT NULL DEFAULT 'made_weight'\n"
            "                           CHECK (cut_outcome IN ('made_weight', 'missed_small',\n"
            "                                                  'missed_medium', 'missed_large',\n"
            "                                                  'cancelled')),\n"
            "    cardio_penalty         INTEGER NOT NULL DEFAULT 0 CHECK (cardio_penalty BETWEEN 0 AND 50),\n"
            "    purse_penalty_pct      INTEGER NOT NULL DEFAULT 0 CHECK (purse_penalty_pct BETWEEN 0 AND 100),\n"
            "    is_title_fight         INTEGER NOT NULL DEFAULT 0 CHECK (is_title_fight IN (0, 1)),\n"
            "    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


# The ordered registry of migrations. Each entry is
# (migration_name, version_introduced, function). The runner applies
# them in order, skipping any already recorded in schema_migrations.
# To add a new migration: define _migrate_v2_X_0_your_name(conn),
# append it to this list, and bump CODE_SCHEMA_VERSION.
def _migrate_v2_8_0_add_fighter_descriptors(conn):
    """Task 19 — Voice/Interpretation Layer snapshot cache."""
    if not _has_table(conn, "fighter_descriptors"):
        conn.execute(
            "CREATE TABLE fighter_descriptors (\n"
            "    fighter_id              INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    attribute_descriptors   TEXT NOT NULL DEFAULT '{}',\n"
            "    personality_descriptors TEXT NOT NULL DEFAULT '{}',\n"
            "    career_stage            TEXT,\n"
            "    career_health_desc      TEXT,\n"
            "    overall_desc            TEXT,\n"
            "    potential_desc          TEXT,\n"
            "    snapshot_version        INTEGER NOT NULL DEFAULT 1,\n"
            "    updated_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


# The ordered registry of migrations. Each entry is
# (migration_name, version_introduced, function). The runner applies
# them in order, skipping any already recorded in schema_migrations.
# To add a new migration: define _migrate_v2_X_0_your_name(conn),
# append it to this list, and bump CODE_SCHEMA_VERSION.
def _migrate_v2_9_0_add_scouting_reports(conn):
    """Task 18 — Scouting system. Adds the scouting_reports table."""
    if not _has_table(conn, "scouting_reports"):
        conn.execute(
            "CREATE TABLE scouting_reports (\n"
            "    scouting_report_id      INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    scout_id                INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,\n"
            "    target_fighter_id       INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    promotion_id            INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,\n"
            "    report_date             TEXT NOT NULL,\n"
            "    estimated_potential     TEXT,\n"
            "    estimated_ceiling       TEXT,\n"
            "    estimated_floor         TEXT,\n"
            "    estimated_strengths     TEXT,\n"
            "    estimated_weaknesses    TEXT,\n"
            "    marketability_assessment TEXT,\n"
            "    injury_risk_assessment  TEXT,\n"
            "    contract_cost_estimate  INTEGER,\n"
            "    scout_confidence        INTEGER NOT NULL DEFAULT 50 CHECK (scout_confidence BETWEEN 0 AND 100),\n"
            "    is_stale                INTEGER NOT NULL DEFAULT 0 CHECK (is_stale IN (0, 1)),\n"
            "    report_text             TEXT NOT NULL,\n"
            "    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    updated_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v3_0_0_add_finance_transactions(conn):
    """Task 20 — Finance system. Adds the finance_transactions table."""
    if not _has_table(conn, "finance_transactions"):
        conn.execute(
            "CREATE TABLE finance_transactions (\n"
            "    transaction_id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    promotion_id            INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,\n"
            "    event_id                INTEGER REFERENCES events(event_id) ON DELETE SET NULL,\n"
            "    fighter_id              INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,\n"
            "    transaction_type        TEXT NOT NULL CHECK (transaction_type IN (\n"
            "        'ticket_sales', 'broadcast_revenue', 'merchandise',\n"
            "        'fighter_purse', 'venue_rental', 'staff_salary',\n"
            "        'medical_cost', 'signing_bonus', 'weight_cut_penalty',\n"
            "        'sponsorship', 'bonus_payment'\n"
            "    )),\n"
            "    amount                  REAL NOT NULL,\n"
            "    description             TEXT,\n"
            "    transaction_date        TEXT NOT NULL,\n"
            "    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v3_1_0_add_social_posts(conn):
    """Task 21 — Social media + beefs. Adds the social_posts table.

    Migration name: v3_1_0_add_social_posts. Idempotent — checks for
    the table's existence before creating.
    """
    if not _has_table(conn, "social_posts"):
        conn.execute(
            "CREATE TABLE social_posts (\n"
            "    post_id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id       INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    post_type        TEXT NOT NULL CHECK (post_type IN (\n"
            "        'callout', 'trash_talk', 'hype', 'apology', 'announcement',\n"
            "        'brag', 'excuse', 'retirement_hint', 'challenge'\n"
            "    )),\n"
            "    target_fighter_id INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,\n"
            "    post_text        TEXT NOT NULL,\n"
            "    post_date        TEXT NOT NULL,\n"
            "    engagement       INTEGER NOT NULL DEFAULT 0 CHECK (engagement >= 0),\n"
            "    is_beef_escalation INTEGER NOT NULL DEFAULT 0 CHECK (is_beef_escalation IN (0, 1)),\n"
            "    created_at       TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v3_2_0_add_rivalries(conn):
    """Task 22 — Rivalries. Adds the rivalries table.

    Migration name: v3_2_0_add_rivalries. Idempotent — checks for the
    table's existence before creating.
    """
    if not _has_table(conn, "rivalries"):
        conn.execute(
            "CREATE TABLE rivalries (\n"
            "    rivalry_id        INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_a_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    fighter_b_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    rivalry_heat      INTEGER NOT NULL DEFAULT 50 CHECK (rivalry_heat BETWEEN 0 AND 100),\n"
            "    rivalry_type      TEXT NOT NULL CHECK (rivalry_type IN (\n"
            "        'callout', 'bad_blood', 'title_rivalry', 'rematch_hungry',\n"
            "        'style_clash', 'disrespect', 'stolen_opportunity'\n"
            "    )),\n"
            "    origin_event      TEXT,\n"
            "    origin_description TEXT,\n"
            "    fights_count      INTEGER NOT NULL DEFAULT 0,\n"
            "    fighter_a_wins    INTEGER NOT NULL DEFAULT 0,\n"
            "    fighter_b_wins    INTEGER NOT NULL DEFAULT 0,\n"
            "    draws             INTEGER NOT NULL DEFAULT 0,\n"
            "    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),\n"
            "    last_escalation_date TEXT,\n"
            "    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    updated_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_a_id, fighter_b_id)\n"
            ")"
        )


def _migrate_v3_3_0_add_matchup_analyses(conn):
    """Task 24 — Punditry / matchup analysis. Adds the matchup_analyses table.

    Migration name: v3_3_0_add_matchup_analyses. Idempotent — checks
    for the table's existence before creating.
    """
    if not _has_table(conn, "matchup_analyses"):
        conn.execute(
            "CREATE TABLE matchup_analyses (\n"
            "    analysis_id         INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_a_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    fighter_b_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    fight_id            INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,\n"
            "    event_id            INTEGER REFERENCES events(event_id) ON DELETE SET NULL,\n"
            "    predicted_winner    TEXT,\n"
            "    predicted_method    TEXT,\n"
            "    confidence_pct      INTEGER NOT NULL DEFAULT 50 CHECK (confidence_pct BETWEEN 0 AND 100),\n"
            "    style_edge          TEXT,\n"
            "    excitement_score    INTEGER NOT NULL DEFAULT 50 CHECK (excitement_score BETWEEN 0 AND 100),\n"
            "    upset_risk          TEXT,\n"
            "    analysis_text       TEXT NOT NULL,\n"
            "    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_a_id, fighter_b_id, fight_id)\n"
            ")"
        )


def _migrate_v3_4_0_add_suspensions(conn):
    """Phase B (Task B1+B2) — Fighter suspensions. Adds the suspensions table.

    Migration name: v3_4_0_add_suspensions. Idempotent — checks for
    the table's existence before creating. Per docs/FULL_BUILD_AUDIT.md
    §9a + CONVENTIONS §5 (one table-group per task — `suspensions` is
    the single group this task adds). The src/suspensions.py module
    writes (event-bus subscribers) + app._pick_matchup reads (excludes
    fighters with active suspensions) — every new table ships with
    both a writer and a reader per §5.3.
    """
    if not _has_table(conn, "suspensions"):
        conn.execute(
            "CREATE TABLE suspensions (\n"
            "    suspension_id     INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    suspension_type   TEXT NOT NULL CHECK (suspension_type IN (\n"
            "        'drug_test_failure', 'behavior', 'missed_weight_repeat',\n"
            "        'post_fight_brawl', 'social_media_violation'\n"
            "    )),\n"
            "    start_date        TEXT NOT NULL,\n"
            "    end_date          TEXT NOT NULL,\n"
            "    duration_days     INTEGER NOT NULL CHECK (duration_days > 0),\n"
            "    description       TEXT,\n"
            "    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),\n"
            "    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v3_5_0_add_agent_offers(conn):
    """Phase C — Agent offers / unknown talent gamble system.

    Adds the agent_offers table. Per docs/FULL_BUILD_AUDIT.md §9b +
    CONVENTIONS §5 (one table-group per task — `agent_offers` is the
    single group this task adds). The src/agent_offers.py module writes
    (event-bus subscribers on TICK_ADVANCED: _maybe_generate_offer
    weekly 10% chance + _check_expired_offers expiry scan) + the
    resolve_offer helper signs the fighter (sets current_promotion_id
    + deducts asking_price from current_cash) + the reader
    get_active_offers for the UI — every new table ships with both a
    writer and a reader per §5.3.

    Migration name: v3_5_0_add_agent_offers. Idempotent — checks for
    the table's existence before creating.
    """
    if not _has_table(conn, "agent_offers"):
        conn.execute(
            "CREATE TABLE agent_offers (\n"
            "    offer_id           INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    promotion_id       INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,\n"
            "    fighter_id         INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    offer_date         TEXT NOT NULL,\n"
            "    offer_type         TEXT NOT NULL CHECK (offer_type IN (\n"
            "        'unknown_talent', 'washout_veteran', 'style_specialist',\n"
            "        'contender_release', 'prospect_gamble'\n"
            "    )),\n"
            "    asking_price       REAL NOT NULL,\n"
            "    fighter_description TEXT NOT NULL,\n"
            "    is_resolved        INTEGER NOT NULL DEFAULT 0 CHECK (is_resolved IN (0, 1)),\n"
            "    resolution         TEXT CHECK (resolution IN ('signed', 'rejected', 'expired')),\n"
            "    resolution_date    TEXT,\n"
            "    expires_date       TEXT NOT NULL,\n"
            "    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )


def _migrate_v3_6_0_add_show_ratings(conn):
    """Stage 5 — Task 26 Show rating engine.

    Adds the show_ratings table. Per CONVENTIONS §5 (one table-group
    per task — `show_ratings` is the single group this task adds).
    The src/show_rating.py module writes ratings (event-bus subscriber
    on EVENT_COMPLETED — computes fan/commercial/excitement/quality/
    overall ratings after each event completes) and writes a
    topic='show_rating' news item with the voice-layer descriptor
    (rating_description column — NO raw numbers per CONVENTIONS §14).
    The src/venues.py module (Task 27) reads fan_rating to adjust
    market heat after each event. No reader is wired into the UI in
    this task — a future task will add a post-event summary panel
    that reads show_ratings. Per §5.3, every new table must ship with
    a writer (src/show_rating.py) AND a reader (src/venues.py reads
    fan_rating; future UI panel reads all 5 ratings).

    Migration name: v3_6_0_add_show_ratings. Idempotent — checks for
    the table's existence before creating.
    """
    if not _has_table(conn, "show_ratings"):
        conn.execute(
            "CREATE TABLE show_ratings (\n"
            "    rating_id           INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    event_id            INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,\n"
            "    promotion_id        INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,\n"
            "    fan_rating          INTEGER NOT NULL DEFAULT 50 CHECK (fan_rating BETWEEN 0 AND 100),\n"
            "    commercial_rating   INTEGER NOT NULL DEFAULT 50 CHECK (commercial_rating BETWEEN 0 AND 100),\n"
            "    excitement_rating   INTEGER NOT NULL DEFAULT 50 CHECK (excitement_rating BETWEEN 0 AND 100),\n"
            "    quality_rating      INTEGER NOT NULL DEFAULT 50 CHECK (quality_rating BETWEEN 0 AND 100),\n"
            "    overall_rating      INTEGER NOT NULL DEFAULT 50 CHECK (overall_rating BETWEEN 0 AND 100),\n"
            "    rating_description  TEXT,\n"
            "    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (event_id)\n"
            ")"
        )


def _migrate_v3_7_0_add_player_settings(conn):
    """Stage 5 — Task Stage5-Final: Player settings table.

    Adds the player_settings table — a simple key-value store for
    player preferences (news feed filtering, auto-save cadence,
    difficulty, voice descriptors toggle). Per CONVENTIONS §5 (one
    table-group per task — `player_settings` is the single group this
    task adds). The src/player_settings.py module is the reader/
    writer (get_setting, set_setting, get_all_settings). The module
    is NOT event-bus-driven — settings are read by other systems at
    their own cadence. Per §5.3, every new table must ship with a
    writer (src/player_settings.py) AND a reader (src/player_settings.
    py — same module, dual role; future UI panel will also read it).

    Migration name: v3_7_0_add_player_settings. Idempotent — checks
    for the table's existence before creating. Seeds 6 default
    settings on first apply (idempotent via INSERT OR IGNORE — a
    re-run preserves any user-modified values). FIX-Critical (Issue 5)
    added a 7th default setting: event_naming_style='mixed' (the
    event-name format toggle).
    """
    if not _has_table(conn, "player_settings"):
        conn.execute(
            "CREATE TABLE player_settings (\n"
            "    setting_key        TEXT PRIMARY KEY,\n"
            "    setting_value      TEXT NOT NULL,\n"
            "    updated_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )
    # Seed default settings (idempotent — preserves user-modified values).
    # FIX-Critical (Issue 5): added event_naming_style = 'mixed' for the
    # event-name format toggle ('numbered' / 'themed' / 'mixed').
    defaults = [
        ("news_filter_topics",         "all"),
        ("news_filter_min_importance", "0"),
        ("news_volume",                "normal"),
        ("auto_save_frequency",        "30"),
        ("difficulty",                 "normal"),
        ("display_descriptors",        "true"),
        ("event_naming_style",         "mixed"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO player_settings "
        "(setting_key, setting_value) VALUES (?, ?)",
        defaults,
    )


def _migrate_v3_8_0_add_staff_pundit_bias(conn):
    """Stage 6 prep — D-GUI-4 (Fight Resolution screen): add
    `staff.pundit_bias` JSON column.

    The Fight Resolution screen (planned in docs/GUI_PLAN.md §4) will
    render named-pundit interjections during beat-by-beat playback.
    Each broadcast pundit (staff row where role_type='broadcast' and
    exists in broadcast_staff) has per-attribute biases that shape
    their commentary voice: favour strikers vs grapplers, veterans vs
    prospects, specific nations, specific gyms, etc.

    The JSON schema is documented in src/punditry.py and looks like:
        {
          "style":          "striker" | "grappler" | "balanced",
          "age":            "veteran" | "prospect" | "neutral",
          "nation_ids":     [12, 47],          # favoured nations
          "gym_ids":        [3, 8],            # favoured gyms
          "aggression":     "high" | "low",    # commentary intensity
          "skepticism":     0.0-1.0,           # how often they disagree
          "catchphrases":   ["..."]            # voice texture (future)
        }

    Per CONVENTIONS §5, this is a single-group column add (one column
    on one existing table). Per §1.1, adding a column is a MINOR
    bump (3.7.0 → 3.8.0). Per §5.3, the writer is src/punditry.py
    (writes bias when generating matchup_analyses if the staff row
    doesn't yet have one — lazy initialization) and the reader is
    the upcoming ui/screens/event_resolution.py screen.

    Migration name: v3_8_0_add_staff_pundit_bias. Idempotent — uses
    _has_column guard before ALTER TABLE. On --fresh builds, the
    SCHEMA_SQL already includes the column (the migration function
    is not called, but the migration_name is still recorded in
    schema_migrations per §16.4).
    """
    if not _has_column(conn, "staff", "pundit_bias"):
        conn.execute(
            "ALTER TABLE staff ADD COLUMN pundit_bias TEXT"
        )


def _migrate_v3_9_0_add_staff_gym_id(conn):
    """Phase 1.5 — Task 1.5C-seed-data Fix C6: add staff.gym_id
    column for coach-gym linkage.

    Prior to v3.9.0, the staff table had no gym linkage. Coaches
    (role_type='coach') existed as standalone rows with no
    affiliation to a specific gym. staff_contracts is empty (and
    even when populated, links staff to promotions, not gyms). The
    training-camps system (Task 16) writes training_camps rows that
    reference fighter_id + gym_id; linking the camp's coach to the
    gym requires this staff.gym_id column.

    Per CONVENTIONS §5, this is a single-group column add (one
    column on one existing table — staff.gym_id). Per §1.1, adding
    a column is a MINOR bump (3.8.0 → 3.9.0). Per §5.3, the writer
    is scripts/group_c_seed.py (Phase 1.5 — back-fills gym_id for
    existing coaches) + future coach-generation seed scripts; the
    reader is the upcoming training-camps UI screen (which displays
    the coach alongside the fighter's gym when viewing a camp).

    The column is INTEGER, nullable (NULL for non-coach staff),
    FK to gyms.gym_id with ON DELETE SET NULL (deleting a gym
    NULLs the staff.gym_id rather than cascading — preserves the
    coach row, just leaves it unaffiliated).

    Migration name: v3_9_0_add_staff_gym_id. Idempotent — uses
    _has_column guard before ALTER TABLE. On --fresh builds, the
    SCHEMA_SQL already includes the column (the migration function
    is not called, but the migration_name is still recorded in
    schema_migrations per §16.4).
    """
    if not _has_column(conn, "staff", "gym_id"):
        conn.execute(
            "ALTER TABLE staff ADD COLUMN gym_id INTEGER "
            "REFERENCES gyms(gym_id) ON DELETE SET NULL"
        )


def _migrate_v3_10_0_extend_fighter_descriptors(conn):
    """Phase 2 Task 2.0c-schema-backfill — extend fighter_descriptors with
    6 interpretation columns + create interpretation_cache_meta table.

    Per docs/PHASE_2_PLAN.md §3.1 + §5, this is the foundational schema
    bump for the Phase 2 Interpretation Layer. The 6 new columns are
    nullable TEXT (NULL on existing rows; populated by subsequent
    Phase 2 tasks 2.2/2.3/2.4/2.7 via the daily interpretation pass).

    Columns added to fighter_descriptors:
      momentum         — 'very_high'|'high'|'stable'|'falling'|'collapsing'
      pressure         — 'minimal'|'moderate'|'high'|'extreme'
      career_phase     — 11 canonical labels (see SCHEMA_SQL comment)
      narrative_family — 'prodigy'|'veteran'|'fallen_champion'|... or NULL
      public_narrative — 'future_champion'|'needs_one_more_win'|... or NULL
      legacy_state     — 'building'|'established'|'legendary'|'forgotten'

    IMPORTANT: the existing `career_stage` column is NOT touched — it
    stays where it is (used by news.py). The new `career_phase` column
    is for UI display per CONVENTIONS §17. They serve different
    purposes (see PHASE_2_PLAN.md §3.1 footnote).

    Also creates the `interpretation_cache_meta` singleton table —
    tracks the interpretation engine_version + last_built_date so the
    daily pass can invalidate + rebuild caches when the engine's logic
    changes (CONVENTIONS §17.3 lists it as a CACHE table).

    Per CONVENTIONS §5, this is a single-group schema change (the
    Phase 2 Interpretation Layer's cache columns + its meta table).
    Per §1.1, adding columns + adding a table both qualify as MINOR
    (3.9.0 → 3.10.0). Per §16.4, the migration is idempotent — uses
    _has_column / _has_table guards before ALTER / CREATE.

    Migration name: v3_10_0_extend_fighter_descriptors. On --fresh
    builds, the SCHEMA_SQL already includes the 6 new columns + the
    new table (the migration function is not called, but the
    migration_name is still recorded in schema_migrations per §16.4).
    """
    # 6 new columns on fighter_descriptors (nullable TEXT, no DEFAULT)
    for col in ["momentum", "pressure", "career_phase",
                "narrative_family", "public_narrative", "legacy_state"]:
        if not _has_column(conn, "fighter_descriptors", col):
            conn.execute(
                f"ALTER TABLE fighter_descriptors ADD COLUMN {col} TEXT"
            )

    # Singleton meta table for the interpretation engine version.
    if not _has_table(conn, "interpretation_cache_meta"):
        conn.execute(
            "CREATE TABLE interpretation_cache_meta (\n"
            "    meta_id                  INTEGER PRIMARY KEY DEFAULT 1,\n"
            "    engine_version           TEXT NOT NULL DEFAULT '1.0.0',\n"
            "    last_built_date          TEXT,\n"
            "    last_built_fighter_count INTEGER DEFAULT 0,\n"
            "    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    CHECK (meta_id = 1)\n"
            ")"
        )


def _migrate_v3_11_0_add_cache_tables(conn):
    """Phase 2 Task 2.1-snapshot-cache — add 4 new cache tables for the
    Snapshot Cache orchestrator.

    Per docs/PHASE_2_PLAN.md §3.2 + §5, this is the schema bump that
    ships alongside snapshot_cache.py. The 4 new tables store daily-
    refreshed summaries of gyms, promotions, divisions, and daily
    headlines — the player-facing projection per CONVENTIONS §17.

    Tables created:
      gym_descriptors         — PK = gym_id, FK cascade to gyms.
                                5 TEXT columns (identity_label, known_for,
                                produces, weakness, development_rating_desc).
                                Written by Task 2.8 (gym_identity_engine).
      promotion_descriptors   — PK = promotion_id, FK cascade.
                                3 TEXT columns (prestige_desc,
                                market_position_desc, roster_quality_desc).
      division_descriptors    — Surrogate PK (division_id AUTOINCREMENT),
                                UNIQUE (promotion_id, weight_class_id).
                                2 TEXT columns (depth_desc,
                                competitiveness_desc).
      daily_headlines         — Surrogate PK (headline_id AUTOINCREMENT),
                                UNIQUE (headline_date, headline_type),
                                CHECK'd headline_type enum (8 values).
                                Written by Task 2.6 (headline_engine).

    Per CONVENTIONS §5, this is a single-group schema change (the
    Phase 2 Snapshot Cache's 4 narrow cache tables). Per §1.1, adding
    4 new tables is a MINOR bump (3.10.0 → 3.11.0). Per §16.4, the
    migration is idempotent — uses _has_table guards before each CREATE
    TABLE.

    Per CONVENTIONS §17.3, all 4 tables are CACHE tables — the
    interpretation layer (src/interpretation/snapshot_cache.py) is the
    ONLY writer. Simulation tables are NEVER written to.

    Migration name: v3_11_0_add_cache_tables. On --fresh builds, the
    SCHEMA_SQL already includes the 4 new tables (the migration
    function is not called, but the migration_name is still recorded
    in schema_migrations per §16.4).
    """
    if not _has_table(conn, "gym_descriptors"):
        conn.execute(
            "CREATE TABLE gym_descriptors (\n"
            "    gym_id                   INTEGER PRIMARY KEY REFERENCES gyms(gym_id) ON DELETE CASCADE,\n"
            "    identity_label           TEXT,\n"
            "    known_for                TEXT,\n"
            "    produces                 TEXT,\n"
            "    weakness                 TEXT,\n"
            "    development_rating_desc  TEXT,\n"
            "    snapshot_version         INTEGER NOT NULL DEFAULT 1,\n"
            "    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )

    if not _has_table(conn, "promotion_descriptors"):
        conn.execute(
            "CREATE TABLE promotion_descriptors (\n"
            "    promotion_id             INTEGER PRIMARY KEY REFERENCES promotions(promotion_id) ON DELETE CASCADE,\n"
            "    prestige_desc            TEXT,\n"
            "    market_position_desc     TEXT,\n"
            "    roster_quality_desc      TEXT,\n"
            "    snapshot_version         INTEGER NOT NULL DEFAULT 1,\n"
            "    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )

    if not _has_table(conn, "division_descriptors"):
        conn.execute(
            "CREATE TABLE division_descriptors (\n"
            "    division_id              INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    promotion_id             INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,\n"
            "    weight_class_id          INTEGER NOT NULL REFERENCES weight_classes(weight_class_id) ON DELETE CASCADE,\n"
            "    depth_desc               TEXT,\n"
            "    competitiveness_desc     TEXT,\n"
            "    snapshot_version         INTEGER NOT NULL DEFAULT 1,\n"
            "    updated_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (promotion_id, weight_class_id)\n"
            ")"
        )

    if not _has_table(conn, "daily_headlines"):
        conn.execute(
            "CREATE TABLE daily_headlines (\n"
            "    headline_id              INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    headline_date            TEXT NOT NULL,\n"
            "    headline_type            TEXT NOT NULL CHECK (headline_type IN (\n"
            "        'top_story', 'upset_of_week', 'fastest_rising', 'biggest_fall',\n"
            "        'contract_drama', 'gym_of_month', 'veteran_watch', 'prospect_watch'\n"
            "    )),\n"
            "    headline_text            TEXT NOT NULL,\n"
            "    body_text                TEXT,\n"
            "    fighter_id               INTEGER REFERENCES fighters(fighter_id),\n"
            "    snapshot_version         INTEGER NOT NULL DEFAULT 1,\n"
            "    created_at               TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (headline_date, headline_type)\n"
            ")"
        )


def _migrate_v3_12_0_expand_memory_link_types(conn):
    """Phase 2 Task 2.5 — expand `fighter_memory_links.link_type` CHECK
    with 4 new values: 'previous_fight', 'shared_gym', 'former_teammate',
    'injury_history'.

    Per CONVENTIONS §16.6, SQLite cannot ALTER a CHECK constraint in
    place — the only way to expand a column's CHECK enum is a TABLE
    REBUILD: rename the old table, create the new table with the
    updated CHECK, copy data over, drop the old table. The existing
    data (96 'style_echo' rows in the seeded world DB) is preserved
    verbatim — the new CHECK is a SUPERSET of the old one, so every
    existing row still satisfies it.

    Idempotent (per CONVENTIONS §16.4): the migration runner records
    its migration_name in schema_migrations AFTER it runs. If the
    migration crashes mid-way, the next run re-executes it — the
    partial work must be safe to re-apply. The `_has_check_constraint`
    guard detects whether the new CHECK is already in place and skips
    the rebuild (so a re-run after a successful migration is a no-op).

    The new CHECK enum (8 values total):
      'style_echo', 'gym_heir', 'regional_rival', 'successor'  (existing)
      'previous_fight', 'shared_gym', 'former_teammate',
      'injury_history'                                            (new)

    Migration name: v3_12_0_expand_memory_link_types. On --fresh builds,
    the SCHEMA_SQL already includes the new CHECK (the migration
    function is not called, but the migration_name is still recorded
    in schema_migrations per §16.4 — same idempotency pattern as every
    other migration).
    """
    # Idempotency guard: if the existing table's CHECK already includes
    # 'previous_fight' (a sentinel from the new enum), the migration has
    # already been applied — no-op.
    if _has_check_constraint(conn, "fighter_memory_links",
                             "previous_fight"):
        return

    # Defensive: only attempt the rebuild if fighter_memory_links exists.
    # On a fresh --fresh build, the SCHEMA_SQL already creates the table
    # with the new CHECK (and the idempotency guard above would have
    # returned), so we only get here on a --migrate path from a v3.11.0
    # DB.
    if not _has_table(conn, "fighter_memory_links"):
        # Defensive — create the table with the new CHECK (matches
        # SCHEMA_SQL exactly). Should never happen on the migrate path
        # (every v3.x DB has this table), but the migration must not
        # crash on edge cases.
        conn.execute(
            "CREATE TABLE fighter_memory_links (\n"
            "    memory_link_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    link_type TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history')),\n"
            "    link_strength INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_id, linked_fighter_id, link_type)\n"
            ")"
        )
        return

    # SQLite table-rebuild pattern (CONVENTIONS §16.6):
    #   1. Rename the old table.
    #   2. Create the new table with the updated CHECK (matches
    #      SCHEMA_SQL exactly).
    #   3. Copy all rows verbatim from the old table — the new CHECK
    #      is a SUPERSET of the old one, so every existing row is
    #      still valid (no row transformation needed).
    #   4. Drop the old table.
    # We accept the brief window where the table is renamed (the
    # migration runs in a single transaction — caller commits).
    conn.executescript("""
        ALTER TABLE fighter_memory_links RENAME TO fighter_memory_links_old;
    """)
    conn.executescript("""
        CREATE TABLE fighter_memory_links (
            memory_link_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
            linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
            link_type         TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history')),
            link_strength     INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),
            created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE (fighter_id, linked_fighter_id, link_type)
        );
        INSERT INTO fighter_memory_links
            (memory_link_id, fighter_id, linked_fighter_id, link_type,
             link_strength, created_at)
        SELECT memory_link_id, fighter_id, linked_fighter_id, link_type,
               link_strength, created_at
        FROM fighter_memory_links_old;
        DROP TABLE fighter_memory_links_old;
    """)


def _migrate_v3_13_0_add_performance_indexes(conn):
    """Phase 4 — Performance: add 12 indexes on hot query columns.

    Per CONVENTIONS §16.4, this migration is IDEMPOTENT — every
    statement uses `CREATE INDEX IF NOT EXISTS` so re-running it
    is a no-op. No data is moved, no schema is altered — only
    B-tree indexes are added to speed up existing queries.

    Indexes added (with the query that benefits):

      1. idx_fighters_promo_active
         ON fighters (current_promotion_id, is_active, is_retired)
         — Roster query (WHERE current_promotion_id=? AND is_active=1)
         — Free Agents query (WHERE current_promotion_id IS NULL
            AND is_active=1 AND is_retired=0)
         — Matchmaking query (WHERE current_promotion_id=? AND
            is_active=1 AND is_retired=0)

      2. idx_fighters_weight_class — Roster weight-class filter
      3. idx_fighters_gender — Roster gender filter
      4. idx_fight_history_fighter (fighter_id, event_date DESC)
         — Fighter Profile recent fights
      5. idx_fight_history_opponent — reverse lookups
      6. idx_news_items_published — Dashboard recent news
      7. idx_daily_headlines_date_type — Fighter Watch
      8. idx_titles_champion — Fighter Profile champion check
      9. idx_rankings_fighter — ranking lookups
     10. idx_injuries_fighter_active — matchmaking injury check
     11. idx_suspensions_fighter_active — matchmaking suspension check
     12. idx_scouting_reports_target — Fighter Profile scouting section

    The composite (current_promotion_id, is_active, is_retired) index
    is the most impactful — every Roster / Free Agents / Matchmaking
    query filters on this combination. SQLite uses the LEFTMOST prefix
    of a composite index, so this single index also serves queries
    that filter on just current_promotion_id.
    """
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_fighters_promo_active
            ON fighters (current_promotion_id, is_active, is_retired);
        CREATE INDEX IF NOT EXISTS idx_fighters_weight_class
            ON fighters (weight_class_id);
        CREATE INDEX IF NOT EXISTS idx_fighters_gender
            ON fighters (gender);
        CREATE INDEX IF NOT EXISTS idx_fight_history_fighter
            ON fight_history (fighter_id, event_date DESC);
        CREATE INDEX IF NOT EXISTS idx_fight_history_opponent
            ON fight_history (opponent_id);
        CREATE INDEX IF NOT EXISTS idx_news_items_published
            ON news_items (published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_daily_headlines_date_type
            ON daily_headlines (headline_date DESC, headline_type);
        CREATE INDEX IF NOT EXISTS idx_titles_champion
            ON titles (current_champion_fighter_id);
        CREATE INDEX IF NOT EXISTS idx_rankings_fighter
            ON rankings (fighter_id);
        CREATE INDEX IF NOT EXISTS idx_injuries_fighter_active
            ON injuries (fighter_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_suspensions_fighter_active
            ON suspensions (fighter_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_scouting_reports_target
            ON scouting_reports (target_fighter_id);
    """)


def _migrate_v3_14_0_add_rival_ai_columns(conn):
    """Task RIVAL-AI-P1 — Rival AI Phase 1 Foundation.

    Adds 3 columns to `promotions` for the rival AI archetype system
    (per docs/RIVAL_AI_ARCHITECTURE.md §7.2) AND performs 2 one-time
    data backfills (per the RIVAL-AI-P1 task brief +
    EXISTING_SYSTEMS_AUDIT.md Parts 3+5):

      1. SCHEMA: ai_archetype (TEXT), ai_scheduling_day_of_week
         (INTEGER), ai_budget_state (TEXT) on `promotions`. All
         nullable — NULL means "not yet assigned". The rival AI's
         first TICK_ADVANCED subscriber call (see
         services/rival_ai/archetypes.py assign_all_archetypes)
         populates them. Per CONVENTIONS §16.4, every ALTER is
         guarded by _has_column so the migration is idempotent.

      2. COACH-GYM BACKFILL: assigns each of the 300 orphan coaches
         (staff.role_type='coach' AND staff.gym_id IS NULL AND
         staff.promotion_id IS NULL) to a gym. The audit found all
         300 coaches were orphan — both gym_id AND promotion_id NULL
         — because scripts/seed_world_phase2.py was never updated
         after v3.9.0 added the gym_id column. Round-robin
         assignment: each coach gets the next gym_id (1 coach per
         gym, matching the original seed intent of "1 head coach per
         gym"). Prints the count of backfilled coaches.

      3. STAFF_CONTRACTS BACKFILL: creates a staff_contracts row (+
         parent contracts row with target_type='staff') for each of
         the 75 promo-bound staff (staff.promotion_id IS NOT NULL).
         The polymorphic contracts pattern supports target_type='staff'
         but the seed script never wrote the rows — staff_contracts
         had 0 rows despite 375 staff existing. Each backfilled
         contract is a 1-year deal (start_date='2026-07-20',
         end_date='2027-07-20') with role-based salary:
            general_manager: $80,000  (most senior)
            doctor:          $60,000  (specialist)
            commentator:     $50,000  (matches seed_data.py default)
            scout:           $45,000
            cutman:          $40,000
         Coaches (role_type='coach') are NOT backfilled here — they
         are gym-bound (per arch doc §3.5 + §Q5), not promo-bound.
         Prints the count of created staff_contracts rows.

    Idempotency:
      - The 3 ALTER TABLE statements are guarded by _has_column so
        re-running the migration on an already-migrated DB is a no-op.
      - The coach-gym backfill uses a WHERE clause that filters to
        only orphan coaches (gym_id IS NULL AND promotion_id IS NULL
        AND role_type='coach') — re-running on a backfilled DB finds
        0 rows + is a no-op.
      - The staff_contracts backfill uses a NOT EXISTS subquery to
        skip staff who already have a contract — re-running on a
        backfilled DB finds 0 eligible staff + is a no-op.

    Performance:
      - Schema changes: < 50ms (3 ALTER TABLE statements).
      - Coach-gym backfill: < 100ms (1 SELECT + 1 UPDATE on 300 rows).
      - staff_contracts backfill: < 200ms (1 SELECT + 75 INSERTs into
        contracts + 75 INSERTs into staff_contracts).
      - Total: < 500ms on the live world DB.
    """
    # ---- 1. Schema changes (idempotent via _has_column guard) ------
    if not _has_column(conn, "promotions", "ai_archetype"):
        conn.execute("ALTER TABLE promotions ADD COLUMN ai_archetype TEXT")
    if not _has_column(conn, "promotions", "ai_scheduling_day_of_week"):
        conn.execute(
            "ALTER TABLE promotions ADD COLUMN ai_scheduling_day_of_week INTEGER"
        )
    if not _has_column(conn, "promotions", "ai_budget_state"):
        conn.execute("ALTER TABLE promotions ADD COLUMN ai_budget_state TEXT")

    # ---- 2. Coach-gym backfill ------------------------------------
    # The audit found 300 coaches with gym_id IS NULL AND promotion_id
    # IS NULL — orphan staff because the seed script wasn't updated
    # after v3.9.0 added the gym_id column. Assign each to a gym
    # (round-robin: 1 coach per gym, matching the original seed
    # intent of "1 head coach per gym" in seed_world_phase2.py).
    #
    # The assignment is nation-aware where possible — if a coach has
    # a nation_id, prefer assigning them to a gym in the same nation
    # (preserves regional identity). Falls back to round-robin by
    # gym_id for coaches with NULL nation_id.
    orphan_coaches = conn.execute(
        "SELECT staff_id, nation_id FROM staff "
        "WHERE role_type='coach' AND gym_id IS NULL AND promotion_id IS NULL "
        "ORDER BY staff_id ASC"
    ).fetchall()
    coaches_backfilled = 0
    if orphan_coaches:
        # Build a per-nation list of gym_ids for nation-aware assignment.
        # Coaches with NULL nation_id fall through to the global pool.
        gyms_by_nation = {}
        all_gym_ids = []
        for gym_id, nation_id in conn.execute(
            "SELECT gym_id, nation_id FROM gyms ORDER BY gym_id ASC"
        ).fetchall():
            all_gym_ids.append(gym_id)
            if nation_id is not None:
                gyms_by_nation.setdefault(nation_id, []).append(gym_id)
        # Round-robin index per nation (so we don't always assign
        # the first gym in each nation to multiple coaches).
        nation_rr_index = {}
        global_rr_index = 0
        for staff_id, nation_id in orphan_coaches:
            if nation_id is not None and nation_id in gyms_by_nation:
                # Nation-aware assignment — cycle through this nation's gyms.
                gyms = gyms_by_nation[nation_id]
                idx = nation_rr_index.get(nation_id, 0) % len(gyms)
                gym_id = gyms[idx]
                nation_rr_index[nation_id] = idx + 1
            elif all_gym_ids:
                # Global round-robin fallback.
                gym_id = all_gym_ids[global_rr_index % len(all_gym_ids)]
                global_rr_index += 1
            else:
                # No gyms exist — skip (shouldn't happen on a seeded DB).
                continue
            conn.execute(
                "UPDATE staff SET gym_id=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE staff_id=?",
                (gym_id, staff_id),
            )
            coaches_backfilled += 1
        print(f"  Backfilled {coaches_backfilled} orphan coaches to gyms "
              f"(v3.14.0 coach-gym linkage fix)")

    # ---- 3. staff_contracts backfill ------------------------------
    # Create a staff_contracts row (+ parent contracts row with
    # target_type='staff') for each promo-bound staff member who
    # doesn't already have one. Coaches are excluded (gym-bound, not
    # promo-bound — handled by the coach-gym backfill above).
    #
    # Salary model (role-based, matches the brief's "salary based on
    # role" + the seed_data.py default of $50K for commentators):
    #   general_manager: $80,000  (most senior, sets strategy)
    #   doctor:          $60,000  (specialist, medical degree)
    #   commentator:     $50,000  (matches seed_data.py default)
    #   scout:           $45,000
    #   cutman:          $40,000
    #
    # The 1-year contract window (GAME_START_DATE → +365 days) matches
    # the seeded simulation start date (simulation_clock seeds
    # current_date=GAME_START_DATE per HW2.3). Phase 3's staff_manager
    # will renew / renegotiate these contracts going forward.
    # HW2.3: derive from GAME_START_DATE constant instead of hardcoding
    # 2026-07-20.
    STAFF_SALARY_BY_ROLE = {
        "general_manager": 80000.0,
        "doctor":          60000.0,
        "commentator":     50000.0,
        "scout":           45000.0,
        "cutman":          40000.0,
    }
    from datetime import datetime as _dt, timedelta as _td
    _cs = _dt.strptime(GAME_START_DATE, "%Y-%m-%d")
    CONTRACT_START = GAME_START_DATE
    CONTRACT_END = (_cs + _td(days=365)).strftime("%Y-%m-%d")

    # Find promo-bound staff who don't yet have a staff_contracts row.
    # NOT EXISTS subquery makes this idempotent — re-running finds 0
    # eligible staff on a backfilled DB.
    eligible_staff = conn.execute(
        "SELECT s.staff_id, s.role_type, s.promotion_id "
        "FROM staff s "
        "WHERE s.promotion_id IS NOT NULL "
        "AND s.role_type != 'coach' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM staff_contracts sc "
        "  JOIN contracts c ON c.contract_id=sc.contract_id "
        "  WHERE sc.staff_id=s.staff_id AND c.status='active'"
        ") "
        "ORDER BY s.staff_id ASC"
    ).fetchall()
    contracts_created = 0
    for staff_id, role_type, promotion_id in eligible_staff:
        salary = STAFF_SALARY_BY_ROLE.get(role_type, 50000.0)
        cur = conn.execute(
            "INSERT INTO contracts "
            "(contract_target_type, promotion_id, start_date, end_date, "
            " salary, exclusive_flag, status) "
            "VALUES ('staff', ?, ?, ?, ?, 1, 'active')",
            (promotion_id, CONTRACT_START, CONTRACT_END, salary),
        )
        contract_id = cur.lastrowid
        conn.execute(
            "INSERT INTO staff_contracts (contract_id, staff_id, contract_role) "
            "VALUES (?, ?, ?)",
            (contract_id, staff_id, role_type),
        )
        contracts_created += 1
    if contracts_created:
        print(f"  Backfilled {contracts_created} staff_contracts rows "
              f"(v3.14.0 staff salary tracking fix)")


def _migrate_v3_15_0_add_fighter_descriptor_short_columns(conn):
    """INTERP-EXPAND-V2 (Claude VOICE_ENFORCEMENT §3) — add 5 SHORT
    variant columns to `fighter_descriptors` so the UI can pick a
    ≤25-char phrase for narrow display contexts (Fighter Watch Cards,
    Roster rows, table chips) instead of clipping the 35-65 char LONG
    phrase.

    Columns added (all nullable TEXT, no DEFAULT — populated by the
    daily interpretation pass via the new SHORT phrase pickers in
    context_engine / career_phase_engine / legacy_engine /
    narrative_families):
      momentum_short          — "label||short voice phrase"
      pressure_short          — "label||short voice phrase"
      career_phase_short      — "label||short voice phrase"
      narrative_family_short  — "label||short voice phrase" (NULL when
                                the fighter matches no family — same
                                D5 NULL behavior as narrative_family)
      legacy_state_short      — "label||short voice phrase"

    Per CONVENTIONS §1.1, adding columns to an existing table
    qualifies as MINOR (3.14.0 → 3.15.0). Per §16.4, every ALTER is
    guarded by _has_column so the migration is idempotent.

    The INTERP-EXPAND-V2 task ALSO bumps snapshot_cache.ENGINE_VERSION
    from "1.7.0" → "1.8.0" — that bump lives in snapshot_cache.py
    (separate constant). The engine_version bump forces a full cache
    rebuild on the next daily pass so the new SHORT columns get
    populated across all 4450 active fighters (and 60 retired
    legends) in one go.

    Performance:
      - 5 ALTER TABLE statements, each guarded by _has_column.
        SQLite's ALTER TABLE ADD COLUMN is O(1) metadata-only for
        nullable columns with no DEFAULT — total <50ms even on the
        4500-row fighter_descriptors table.
      - No data backfill here — the daily interpretation pass
        populates the columns on the next tick after the migration
        lands (forced by the engine_version bump).
    """
    # 5 new SHORT-variant columns on fighter_descriptors (nullable
    # TEXT, no DEFAULT). Each stores "label||short voice phrase".
    # Idempotent via _has_column guard.
    for col in ["momentum_short", "pressure_short",
                "career_phase_short", "narrative_family_short",
                "legacy_state_short"]:
        if not _has_column(conn, "fighter_descriptors", col):
            conn.execute(
                f"ALTER TABLE fighter_descriptors ADD COLUMN {col} TEXT"
            )


def _migrate_v3_16_0_add_player_decisions_and_echoes(conn):
    """PHASE-R (Reward Layer §1.5 + §6 Principle 4) — add 2 new tables:
    `player_decisions` (append-only log of player actions) and
    `daily_echoes` (cache of 2-3 daily-generated "echo" phrases).

    Per docs/REWARD_REVIEW.md §1.5 + §6 + Phase R brief: the Agency
    reward is the weakest of GPT's 5 player rewards (3/10 on 3 of 4
    screens). The fix is to log every player action that should
    "echo" later (sign / cut / book / scout / staff moves), then
    surface 2-3 of those echoes per Advance Day on the Dashboard +
    a per-fighter "Your History with [Fighter]" section on the
    Fighter Profile.

    Tables created (both idempotent via _has_table guard):
      player_decisions — PK decision_id AUTOINCREMENT, decision_type
        TEXT NOT NULL CHECK (10 values: sign/cut/book/scout +
        6 staff/econ actions), 4 nullable target_*_id FK-free
        INTEGER columns (fighter / staff / event / promo — left
        un-FK'd intentionally so historical log rows survive a
        fighter/staff deletion), decision_date TEXT NOT NULL (sim
        date YYYY-MM-DD), context_json TEXT (arbitrary per-decision
        context), created_at TIMESTAMP.
        3 indexes: idx_player_decisions_type, idx_player_decisions_date,
        idx_player_decisions_fighter. (No index on target_staff_id —
        staff-decision queries are rare and the type index covers
        them via filter.)
      daily_echoes — PK echo_id AUTOINCREMENT, echo_date TEXT NOT
        NULL, echo_slot INTEGER NOT NULL CHECK (1..5), echo_type
        TEXT NOT NULL CHECK (4 values: signing/cut/booking/scouting
        echo), phrase TEXT NOT NULL, decision_id INTEGER (link back
        to player_decisions), target_fighter_id INTEGER (for
        hyperlink), link_to_screen TEXT, created_at TIMESTAMP.
        UNIQUE (echo_date, echo_slot) → idempotent INSERT OR REPLACE
        (matches daily_headlines behavior). 1 index on echo_date DESC.

    Per CONVENTIONS §1.1, adding 2 new narrow tables is MINOR
    (3.15.0 → 3.16.0). Per §16.4, the migration is idempotent — uses
    _has_table guards before each CREATE TABLE + CREATE INDEX IF NOT
    EXISTS so re-running on a DB that already has the tables is a
    no-op.

    Per CONVENTIONS §17.3, daily_echoes is a CACHE table — only
    echoes_engine.py writes to it. player_decisions is a PLAYER_LOG
    table — only player_decisions.log_decision() writes to it
    (called from app_web.py::sign_free_agent / cut_fighter /
    select_promotion / etc.). The simulation layer NEVER writes to
    either table.

    Migration name: v3_16_0_add_player_decisions_and_echoes. On
    --fresh builds, SCHEMA_SQL already includes both tables (the
    migration function is not called, but the migration_name is
    still recorded in schema_migrations per §16.4).
    """
    if not _has_table(conn, "player_decisions"):
        conn.execute(
            "CREATE TABLE player_decisions (\n"
            "    decision_id        INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    decision_type      TEXT NOT NULL CHECK (decision_type IN (\n"
            "        'sign', 'cut', 'book', 'scout',\n"
            "        'hire_staff', 'fire_staff', 'assign_staff',\n"
            "        'set_ticket_price', 'set_marketing', 'negotiate_contract'\n"
            "    )),\n"
            "    target_fighter_id  INTEGER,\n"
            "    target_staff_id    INTEGER,\n"
            "    target_event_id    INTEGER,\n"
            "    target_promo_id    INTEGER,\n"
            "    decision_date      TEXT NOT NULL,\n"
            "    context_json       TEXT,\n"
            "    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n"
            ")"
        )
        # Indexes (CREATE INDEX IF NOT EXISTS is idempotent — safe to
        # run even if the table pre-existed from a prior partial run).
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_decisions_type "
            "ON player_decisions(decision_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_decisions_date "
            "ON player_decisions(decision_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_decisions_fighter "
            "ON player_decisions(target_fighter_id)"
        )

    if not _has_table(conn, "daily_echoes"):
        conn.execute(
            "CREATE TABLE daily_echoes (\n"
            "    echo_id            INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    echo_date          TEXT NOT NULL,\n"
            "    echo_slot          INTEGER NOT NULL CHECK (echo_slot BETWEEN 1 AND 5),\n"
            "    echo_type          TEXT NOT NULL CHECK (echo_type IN (\n"
            "        'signing_echo', 'cut_echo', 'booking_echo', 'scouting_echo'\n"
            "    )),\n"
            "    phrase             TEXT NOT NULL,\n"
            "    decision_id        INTEGER,\n"
            "    target_fighter_id  INTEGER,\n"
            "    link_to_screen     TEXT,\n"
            "    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (echo_date, echo_slot)\n"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_echoes_date "
            "ON daily_echoes(echo_date DESC)"
        )


def _migrate_v3_17_0_add_concessions_txn_type(conn):
    """Phase E2.4 — add 'concessions' to the finance_transactions
    transaction_type CHECK constraint (per docs/ECON_STAFF_PLAN.md
    §3.1.5).

    Per CONVENTIONS §16.6, SQLite cannot ALTER a CHECK constraint in
    place — the only way to expand a column's CHECK enum is a TABLE
    REBUILD: rename the old table, create the new table with the
    updated CHECK, copy data over, drop the old table. The existing
    data (2155+ rows in promo 1's backfilled finance_transactions
    from Phase E1) is preserved verbatim — the new CHECK is a
    SUPERSET of the old one, so every existing row still satisfies it.

    Idempotent (per CONVENTIONS §16.4): the migration runner records
    its migration_name in schema_migrations AFTER it runs. If the
    migration crashes mid-way, the next run re-executes it — the
    partial work must be safe to re-apply. The `_has_check_constraint`
    guard detects whether the new CHECK is already in place and skips
    the rebuild (so a re-run after a successful migration is a no-op).

    The new CHECK enum (12 values total — was 11 before E2.4):
      'ticket_sales', 'broadcast_revenue', 'merchandise',
      'fighter_purse', 'venue_rental', 'staff_salary',
      'medical_cost', 'signing_bonus', 'weight_cut_penalty',
      'sponsorship', 'bonus_payment'                   (existing)
      'concessions'                                     (new — Phase E2.4)

    Migration name: v3_17_0_add_concessions_txn_type. On --fresh
    builds, the SCHEMA_SQL already includes 'concessions' in the
    CHECK (the migration function is not called, but the migration_
    name is still recorded in schema_migrations per §16.4 — same
    idempotency pattern as every other migration).
    """
    # Idempotency guard: if the existing table's CHECK already includes
    # 'concessions', the migration has already been applied — no-op.
    if _has_check_constraint(conn, "finance_transactions", "concessions"):
        return

    # Defensive: only attempt the rebuild if finance_transactions exists.
    # On a fresh --fresh build, the SCHEMA_SQL already creates the table
    # with the new CHECK (and the idempotency guard above would have
    # returned), so we only get here on a --migrate path from a v3.16.0
    # DB.
    if not _has_table(conn, "finance_transactions"):
        # Defensive — create the table with the new CHECK (matches
        # SCHEMA_SQL exactly). Should never happen on the migrate path
        # (every v3.x DB has this table since v3.0.0), but the
        # migration must not crash on edge cases.
        conn.execute(
            "CREATE TABLE finance_transactions (\n"
            "    transaction_id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    promotion_id            INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,\n"
            "    event_id                INTEGER REFERENCES events(event_id) ON DELETE SET NULL,\n"
            "    fighter_id              INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,\n"
            "    transaction_type        TEXT NOT NULL CHECK (transaction_type IN (\n"
            "        'ticket_sales', 'broadcast_revenue', 'merchandise',\n"
            "        'fighter_purse', 'venue_rental', 'staff_salary',\n"
            "        'medical_cost', 'signing_bonus', 'weight_cut_penalty',\n"
            "        'sponsorship', 'bonus_payment', 'concessions'\n"
            "    )),\n"
            "    amount                  REAL NOT NULL,\n"
            "    description             TEXT,\n"
            "    transaction_date        TEXT NOT NULL,\n"
            "    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
            ")"
        )
        return

    # SQLite table-rebuild pattern (CONVENTIONS §16.6):
    #   1. Rename the old table.
    #   2. Create the new table with the updated CHECK (matches
    #      SCHEMA_SQL exactly).
    #   3. Copy all rows verbatim from the old table — the new CHECK
    #      is a SUPERSET of the old one, so every existing row is
    #      still valid (no row transformation needed).
    #   4. Drop the old table.
    # We accept the brief window where the table is renamed (the
    # migration runs in a single transaction — caller commits).
    conn.executescript("""
        ALTER TABLE finance_transactions RENAME TO finance_transactions_old;
    """)
    conn.executescript("""
        CREATE TABLE finance_transactions (
            transaction_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            promotion_id            INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
            event_id                INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
            fighter_id              INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
            transaction_type        TEXT NOT NULL CHECK (transaction_type IN (
                'ticket_sales', 'broadcast_revenue', 'merchandise',
                'fighter_purse', 'venue_rental', 'staff_salary',
                'medical_cost', 'signing_bonus', 'weight_cut_penalty',
                'sponsorship', 'bonus_payment', 'concessions'
            )),
            amount                  REAL NOT NULL,
            description             TEXT,
            transaction_date        TEXT NOT NULL,
            created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        );
        INSERT INTO finance_transactions
            (transaction_id, promotion_id, event_id, fighter_id,
             transaction_type, amount, description, transaction_date,
             created_at)
        SELECT transaction_id, promotion_id, event_id, fighter_id,
               transaction_type, amount, description, transaction_date,
               created_at
        FROM finance_transactions_old;
        DROP TABLE finance_transactions_old;
    """)


def _migrate_v3_18_0_add_venue_type(conn):
    """Phase E2.7 — add `venue_type` column to `venues` table (per
    docs/ECON_STAFF_PLAN.md §3.2.3).

    Drives the tiered venue_rental cost_per_seat_by_venue_type lookup
    in finance.py. 4 values:
      - 'arena'    (capacity >= 15000) — $7/seat
      - 'ballroom' (5000-14999)        — $5/seat
      - 'theater'  (2000-4999)         — $4/seat
      - 'outdoor'  (<2000)             — $3/seat

    Per CONVENTIONS §1.1, adding a NOT NULL column with a DEFAULT to
    an existing table qualifies as MINOR (3.17.0 → 3.18.0). Per §16.4,
    the ALTER is guarded by _has_column so the migration is idempotent
    (re-runs are a no-op).

    Backfill strategy (per spec): default all existing venues to
    'ballroom' (mid-tier), then UPDATE by capacity tier:
      - capacity >= 15000 → 'arena'
      - 5000-14999        → 'ballroom' (already default — no UPDATE needed)
      - 2000-4999         → 'theater'
      - <2000             → 'outdoor'

    The ALTER TABLE ADD COLUMN with NOT NULL DEFAULT 'ballroom' is
    SQLite O(1) metadata-only for the column addition (SQLite fills
    the default for existing rows on read, no row rewrite). The 3
    UPDATE statements are O(N) — fast on the ~270-row venues table
    (<5ms).

    Migration name: v3_18_0_add_venue_type. On --fresh builds, the
    SCHEMA_SQL already includes the venue_type column with CHECK
    constraint (the migration function is not called, but the
    migration_name is still recorded in schema_migrations per §16.4).
    """
    # Idempotency guard: if venue_type column already exists, no-op.
    if _has_column(conn, "venues", "venue_type"):
        return

    # Add the column with NOT NULL DEFAULT 'ballroom'. SQLite allows
    # ADD COLUMN NOT NULL DEFAULT <constant> without a table rebuild
    # (the default fills existing rows on read).
    conn.execute(
        "ALTER TABLE venues ADD COLUMN venue_type TEXT NOT NULL "
        "DEFAULT 'ballroom' "
        "CHECK (venue_type IN ('arena', 'ballroom', 'theater', 'outdoor'))"
    )

    # Backfill by capacity tier. 'ballroom' is already the default so
    # only 3 UPDATE statements are needed.
    conn.execute(
        "UPDATE venues SET venue_type='arena' "
        "WHERE capacity >= 15000"
    )
    conn.execute(
        "UPDATE venues SET venue_type='theater' "
        "WHERE capacity >= 2000 AND capacity < 5000"
    )
    conn.execute(
        "UPDATE venues SET venue_type='outdoor' "
        "WHERE capacity < 2000"
    )


def _migrate_v3_19_0_add_fighter_portrait_path(conn):
    """DB-REVIEW-IMAGE-ASSIGNMENT (per task spec) — add `portrait_path`
    TEXT column to the `fighters` table.

    Per the user directive: 415 fighter portrait images (512x512 .webp)
    were uploaded under data/portraits/batch_XXX_YYY/batch_XXX_YYY/.
    Filenames follow the pattern
    ``NNNN_FirstNameLastName[_Nickname].webp`` where ``NNNN`` is the
    fighter_id (zero-padded 4 digits, range 0001-0496).

    This column stores the relative path (relative to ``data/``) for
    fighters with custom portraits, e.g.
    ``portraits/batch_001-020/batch_001-020/0001_HirokiNakamura_Mist.webp``.
    NULL for the 4049 fighters without custom portraits (they're
    generated fighters; future batches may add portraits for them).

    Per CONVENTIONS §1.1, adding a nullable column to an existing table
    qualifies as MINOR (3.18.0 → 3.19.0). Per §16.4, the ALTER is
    guarded by _has_column so the migration is idempotent (re-runs are
    a no-op).

    Per user directive: the image never changes once assigned — regens
    work differently (they get a fresh fighter_id via regen_lineage),
    so the path stored here is stable for the lifetime of the
    fighter_id. The UI caches the base64-encoded image in-memory after
    first load.

    The ALTER TABLE ADD COLUMN with no DEFAULT is SQLite O(1)
    metadata-only (existing rows get NULL — exactly the desired
    behavior for the 4049 fighters without portraits).

    Migration name: v3_19_0_add_fighter_portrait_path. On --fresh
    builds, the SCHEMA_SQL already includes the portrait_path column
    (the migration function is not called, but the migration_name is
    still recorded in schema_migrations per §16.4).
    """
    # Idempotency guard: if portrait_path column already exists, no-op.
    if _has_column(conn, "fighters", "portrait_path"):
        return

    conn.execute("ALTER TABLE fighters ADD COLUMN portrait_path TEXT")


def _migrate_v3_20_0_reseed_fighter_attributes(conn):
    """CR-10 (per docs/CR10_14_FIX_PLAN.md §1.2) — re-seed all 26
    fighter_attributes columns down by 15 points, clamped at a floor
    of 25, for every active fighter.

    Per CONVENTIONS §1.1, a data-only UPDATE (no schema change) is a
    MINOR bump (3.19.0 → 3.20.0). The schema is unchanged — the
    fighter_attributes table already has all 26 columns. This
    migration only adjusts the seeded VALUES.

    WHY: the DB audit (docs/DB_REVIEW_AUDIT.md finding #1) found that
    seeded attributes average 52 across all 26 columns, but average
    fighter_career.potential is only 62 — leaving just 10 points of
    headroom. Combined with the effective_ceiling formula bug (now
    fixed in tick_processor.py G.1), the ceiling collapsed to ~30 for
    typical fighters → 99.7% of training camps produced zero gains.

    Even WITH the G.1 formula fix (personality_factor moved from
    ceiling to gain multiplier), 10 points of headroom is too thin:
    fighters plateau within 1-2 camps, then the dim_factor shrinks
    gains to nothing. Lowering all attributes by 15 (clamped at 25
    so we never push a fighter below the original floor) gives:

      - Old avg attr: 52 (median 52, range 27-93)
      - New avg attr: 37 (clamp at 25 catches ~3% of high-end attrs)
      - Avg potential: 62
      - New headroom: 25 points (was 10) → ~8-12 camps of growth room

    The 25 floor preserves fighter identity — a fighter seeded with
    chin=30 stays at chin=25 (5-point drop, not 15), and a fighter
    seeded with chin=80 drops to chin=65 (full 15-point drop).

    Idempotent per CONVENTIONS §16.4: the migration runner records
    its migration_name (v3_20_0_reseed_fighter_attributes) in
    schema_migrations AFTER it runs. Re-running _run_migrations on
    a DB that already has this row will skip the migration entirely
    (the for-loop in _run_migrations checks `if name in applied:
    continue`). The migration function itself has no internal guard
    because there is no schema marker to check — the only "idempotent
    re-run" path is via schema_migrations (the standard pattern for
    data-only migrations in this codebase).

    The WHERE clause scopes the UPDATE to active fighters only
    (is_active=1) — retired legends / HoF inductees keep their
    historical attributes (preserves "in their prime" snapshots
    for the Hall of Fame screen).

    Migration name: v3_20_0_reseed_fighter_attributes. On --fresh
    builds, the migration function is NOT called (per CONVENTIONS
    §16.4) but the migration_name IS recorded in schema_migrations
    for audit-trail consistency. The fresh-build path uses
    seed_world_phase*.py to seed attributes at the NEW lower baseline
    (avg ~37) — no re-seed needed.

    Downstream: snapshot_cache.ENGINE_VERSION is bumped (1.8.0 →
    1.9.0) to force a full fighter_descriptors cache rebuild on the
    next daily interpretation pass. The attribute_descriptors column
    in fighter_descriptors is stale after the re-seed (it references
    the old, higher attribute values). The cache rebuild regenerates
    every fighter's descriptors from the freshly-lowered attributes.
    """
    conn.execute("""
UPDATE fighter_attributes SET
    punch_power = MAX(25, punch_power - 15),
    cardio = MAX(25, cardio - 15),
    fight_iq = MAX(25, fight_iq - 15),
    chin = MAX(25, chin - 15),
    punch_accuracy = MAX(25, punch_accuracy - 15),
    kick_power = MAX(25, kick_power - 15),
    kick_accuracy = MAX(25, kick_accuracy - 15),
    head_movement = MAX(25, head_movement - 15),
    footwork = MAX(25, footwork - 15),
    clinch_striking = MAX(25, clinch_striking - 15),
    clinch_offense = MAX(25, clinch_offense - 15),
    clinch_defense = MAX(25, clinch_defense - 15),
    takedown_offense = MAX(25, takedown_offense - 15),
    takedown_defense = MAX(25, takedown_defense - 15),
    top_control = MAX(25, top_control - 15),
    bottom_game = MAX(25, bottom_game - 15),
    submission_offense = MAX(25, submission_offense - 15),
    submission_defense = MAX(25, submission_defense - 15),
    scramble_ability = MAX(25, scramble_ability - 15),
    cage_wrestling = MAX(25, cage_wrestling - 15),
    recovery_rate = MAX(25, recovery_rate - 15),
    speed_explosiveness = MAX(25, speed_explosiveness - 15),
    strength = MAX(25, strength - 15),
    durability = MAX(25, durability - 15),
    flexibility = MAX(25, flexibility - 15),
    adaptability = MAX(25, adaptability - 15),
    updated_at = CURRENT_TIMESTAMP
WHERE fighter_id IN (SELECT fighter_id FROM fighters WHERE is_active=1);
""")


def _migrate_v3_21_0_add_player_levers(conn):
    """Phase E3.1 — add player-set financial lever columns to the
    `events` table (per docs/PHASE_E3_PLAN.md §1.E3.1 + docs/ECON_STAFF_PLAN.md §3.3).

    4 new columns:
      - ticket_price    INTEGER NOT NULL DEFAULT 80   ($20-$300, default 80)
      - marketing_spend INTEGER NOT NULL DEFAULT 0    ($0-$500k, default 0)
      - ppv_price       INTEGER NOT NULL DEFAULT 60   ($30-$80, default 60)
      - is_ppv          INTEGER NOT NULL DEFAULT 0 CHECK (0,1)

    Per CONVENTIONS §1.1, adding NOT NULL DEFAULT columns to an existing
    table qualifies as MINOR (3.20.0 → 3.21.0). Per §16.4, each ALTER is
    guarded by _has_column so the migration is idempotent (re-runs are a
    no-op). SQLite ALTER TABLE ADD COLUMN with NOT NULL DEFAULT <const>
    is metadata-only — no row rewrite.

    Backward compat: existing events (all 20000+ completed events in
    the world DB) get the defaults — ticket_price=80, marketing_spend=0,
    ppv_price=60, is_ppv=0. Phase E3.2's _process_event_finance reads
    these levers; pre-E3 events behave identically to Phase E2 because
    the defaults match Phase E2's hard-coded values.

    ALSO: expand the finance_transactions CHECK constraint to add
    'marketing' as a new transaction_type (used by Phase E3.2 to write
    the marketing_spend expense row). Uses the same SQLite table-rebuild
    pattern as v3.17.0 (CONVENTIONS §16.6 — CHECK constraints can only
    be expanded via rename + recreate + copy + drop).
    """
    # ---- Step 1: add the 4 lever columns to events ----
    # Track whether we added the is_ppv column THIS run — if so, we
    # need to backfill is_ppv=1 for events on PPV-tier promos (so
    # pre-E3 events on ppv_global/ppv_streaming promos retain their
    # Phase E2 PPV revenue behavior). Without this backfill, the
    # column default of 0 would cause finance._process_event_finance
    # to skip the PPV formula for these events on the next re-process,
    # breaking test_finance_wiring + test_finance_e2's broadcast_
    # revenue assertion on promo 1 (ppv_global) events.
    added_is_ppv_column = False
    for col, decl in [
        ("ticket_price",    "INTEGER NOT NULL DEFAULT 80"),
        ("marketing_spend", "INTEGER NOT NULL DEFAULT 0"),
        ("ppv_price",       "INTEGER NOT NULL DEFAULT 60"),
    ]:
        if not _has_column(conn, "events", col):
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {decl}")

    # is_ppv has a CHECK constraint (0,1) — added separately because the
    # ADD COLUMN with CHECK needs a different declaration.
    if not _has_column(conn, "events", "is_ppv"):
        conn.execute(
            "ALTER TABLE events ADD COLUMN is_ppv INTEGER NOT NULL "
            "DEFAULT 0 CHECK (is_ppv IN (0,1))"
        )
        added_is_ppv_column = True

    # Backfill is_ppv=1 for events on PPV-tier promos (ppv_global,
    # ppv_streaming). This preserves Phase E2 behavior: a ppv_global
    # promo's pre-E3 events were processed with the PPV formula, so
    # setting is_ppv=1 keeps them on the PPV path. Events on tv_
    # regional / streaming / local_stream keep is_ppv=0 (the column
    # default) — they were always on the flat-rights path.
    #
    # Only runs on the migration that ADDED the is_ppv column. A re-run
    # of this migration is a no-op (the column already exists, so
    # added_is_ppv_column stays False, so the backfill doesn't fire
    # again — preserves any player changes to is_ppv on their events).
    if added_is_ppv_column:
        conn.execute(
            "UPDATE events SET is_ppv=1 "
            "WHERE promotion_id IN ("
            "  SELECT promotion_id FROM promotions "
            "  WHERE broadcast_tier IN ('ppv_global', 'ppv_streaming')"
            ")"
        )

    # ---- Step 2: add 'marketing' to the finance_transactions CHECK ----
    # Idempotency guard: if the CHECK already includes 'marketing', skip.
    if not _has_check_constraint(conn, "finance_transactions", "marketing"):
        # Only attempt the rebuild if finance_transactions exists.
        if _has_table(conn, "finance_transactions"):
            conn.executescript("""
                ALTER TABLE finance_transactions RENAME TO finance_transactions_old_v3_21;
            """)
            conn.executescript("""
                CREATE TABLE finance_transactions (
                    transaction_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    promotion_id            INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
                    event_id                INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
                    fighter_id              INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
                    transaction_type        TEXT NOT NULL CHECK (transaction_type IN (
                        'ticket_sales', 'broadcast_revenue', 'merchandise',
                        'fighter_purse', 'venue_rental', 'staff_salary',
                        'medical_cost', 'signing_bonus', 'weight_cut_penalty',
                        'sponsorship', 'bonus_payment', 'concessions',
                        'marketing'
                    )),
                    amount                  REAL NOT NULL,
                    description             TEXT,
                    transaction_date        TEXT NOT NULL,
                    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                );
                INSERT INTO finance_transactions
                    (transaction_id, promotion_id, event_id, fighter_id,
                     transaction_type, amount, description, transaction_date,
                     created_at)
                SELECT transaction_id, promotion_id, event_id, fighter_id,
                       transaction_type, amount, description, transaction_date,
                       created_at
                FROM finance_transactions_old_v3_21;
                DROP TABLE finance_transactions_old_v3_21;
            """)


def _migrate_v3_22_0_add_staff_market_columns(conn):
    """Phase E4 — Staff Market screen (per docs/ECON_STAFF_PLAN.md
    §4.2 + §4.3 + task brief).

    Three new columns on the `staff` table:
      - skill_level          INTEGER 0-100 (overall competence).
        Displayed via voice phrase ('world-class' / 'established' /
        'promising' / 'unproven') — NEVER the raw int.
      - salary_ask           REAL — annual salary expectation in $.
        Drives the negotiation threshold (offer must clear salary_ask
        × 0.9 for the staff to accept).
      - contract_length_ask  INTEGER — desired contract length in years
        (1-5). Drives the default contract_length slider.

    Per CONVENTIONS §1.1, adding NOT NULL DEFAULT columns to an
    existing table qualifies as MINOR (3.21.0 → 3.22.0). Per §16.4,
    each ALTER is guarded by _has_column so the migration is
    idempotent. SQLite ALTER TABLE ADD COLUMN with NOT NULL DEFAULT
    <const> is metadata-only — no row rewrite.

    Backfill strategy:
      1. skill_level — for scouts, read eye_for_talent from the
         specialty JSON (already populated by the seed). For all
         other roles, use a deterministic pseudo-random in 30-80
         (seeded by staff_id so the backfill is reproducible). The
         seed prevents skill levels from changing on every migration
         re-run.
      2. salary_ask — based on role + skill_level per the table in
         docs/ECON_STAFF_PLAN.md §4.1 + the task brief:
           GM:           $50k-200k
           Doctor:       $40k-100k
           Commentator:  $30k-80k
           Scout:        $30k-80k
           Cutman:       $25k-60k
           Coach:        $30k-150k
         Computed as (min + (skill_level / 100) × (max - min)) so a
         100-skill GM asks $200k, a 0-skill GM asks $50k. Round to
         nearest $1k for clean display.
      3. contract_length_ask — fixed at 2 years (the spec's default).
         Could be randomized later but the spec doesn't ask for it.

    Free-agent pool creation:
      Per the task brief, set staff.promotion_id = NULL for ~200 staff
      to populate the Staff Market's free-agent pool. The current
      world DB has 82 promo-bound staff (commentators/cutmen/doctors/
      GMs/scouts) and 300 coaches with promotion_id IS NULL already
      (gym-affiliated, not promo-affiliated).

      To create the market, we pick ~200 of the 300 orphan coaches
      (deterministic — first 200 by staff_id) and NULL their gym_id
      too (so they're truly free agents, not gym-bound). This leaves
      ~100 coaches as gym residents (preserves the training-camp
      ecosystem for Phase E5). The promo-bound non-coach staff stay
      assigned to their promos (the rival AI's staff_manager already
      manages those).

      NOTE: we DO NOT touch the staff_contracts rows for these 200
      coaches — coaches don't have staff_contracts (per the audit in
      docs/ECON_STAFF_PLAN.md §2.2). Their salary model is the new
      salary_ask column, not the contracts table. When the player
      hires one, hire_staff creates the staff_contracts row.

    Backward compat: existing staff without these columns get the
    defaults (skill_level=50 'promising', salary_ask=$50K,
    contract_length_ask=2). The backfill runs only on the migration
    that ADDED the columns — re-runs are a no-op (the columns exist,
    _has_column returns True, the ALTER is skipped, and the backfill
    is guarded by a skill_level IS NULL check — but since we set
    NOT NULL DEFAULT 50, that check never matches. Instead we use a
    schema_migrations marker row to detect re-runs of the backfill,
    which is simpler + matches the v3.14.0 pattern).

    Migration name: v3_22_0_add_staff_market_columns. On --fresh
    builds, the SCHEMA_SQL already includes the 3 new columns (the
    migration function is not called, but the migration_name is
    still recorded in schema_migrations per §16.4).
    """
    import json as _json
    import random as _random

    # ---- Step 1: add the 3 columns ----
    if not _has_column(conn, "staff", "skill_level"):
        conn.execute(
            "ALTER TABLE staff ADD COLUMN skill_level INTEGER NOT NULL "
            "DEFAULT 50 CHECK (skill_level BETWEEN 0 AND 100)"
        )
    if not _has_column(conn, "staff", "salary_ask"):
        conn.execute(
            "ALTER TABLE staff ADD COLUMN salary_ask REAL NOT NULL "
            "DEFAULT 50000.0"
        )
    if not _has_column(conn, "staff", "contract_length_ask"):
        conn.execute(
            "ALTER TABLE staff ADD COLUMN contract_length_ask INTEGER "
            "NOT NULL DEFAULT 2"
        )

    # ---- Step 2: backfill skill_level + salary_ask ----
    # The default (skill_level=50) was applied to every existing row
    # by the ADD COLUMN. We overwrite it for every staff row with a
    # real value (scout eye_for_talent from JSON, otherwise a
    # deterministic pseudo-random in 30-80).
    #
    # Idempotency: a schema_migrations marker row prevents re-runs of
    # the backfill (so a re-migrate doesn't re-randomize skill levels).
    # This matches the v3.14.0 pattern (staff_contracts backfill used
    # the same marker-row guard).
    marker_row = conn.execute(
        "SELECT 1 FROM schema_migrations "
        "WHERE migration_name='v3_22_0_backfill_done'"
    ).fetchone()
    if marker_row:
        # Backfill already applied — skip (only the column ADDs run,
        # which are themselves no-ops via _has_column).
        return

    # Salary bands per role (min, max) — task brief + ECON_STAFF_PLAN §4.1.
    SALARY_BAND = {
        "general_manager": (50_000, 200_000),
        "doctor":          (40_000, 100_000),
        "commentator":     (30_000, 80_000),
        "scout":           (30_000, 80_000),
        "cutman":          (25_000, 60_000),
        "coach":           (30_000, 150_000),
    }

    rows = conn.execute(
        "SELECT staff_id, role_type, specialty FROM staff"
    ).fetchall()
    rng = _random.Random(20260720)  # deterministic seed — reproducible
    n_skill_set = 0
    n_salary_set = 0
    for staff_id, role_type, specialty_json in rows:
        # --- skill_level ---
        skill = None
        if role_type == "scout" and specialty_json:
            # Scouts already have eye_for_talent in their specialty JSON.
            try:
                spec = _json.loads(specialty_json)
                eye = spec.get("eye_for_talent")
                if isinstance(eye, (int, float)) and 0 <= eye <= 100:
                    skill = int(eye)
            except Exception:
                pass
        if skill is None:
            # Deterministic per-staff pseudo-random in 30-80.
            # Seeded by staff_id so re-runs produce the same value.
            staff_rng = _random.Random(staff_id * 31 + 17)
            skill = staff_rng.randint(30, 80)

        # --- salary_ask ---
        lo, hi = SALARY_BAND.get(role_type or "", (30_000, 80_000))
        # Linear interpolation: 0-skill → lo, 100-skill → hi.
        salary_ask = lo + (skill / 100.0) * (hi - lo)
        # Round to nearest $1k for clean display.
        salary_ask = round(salary_ask / 1000.0) * 1000.0

        conn.execute(
            "UPDATE staff SET skill_level=?, salary_ask=? "
            "WHERE staff_id=?",
            (skill, salary_ask, staff_id),
        )
        n_skill_set += 1
        n_salary_set += 1

    # ---- Step 3: free-agent pool (~200 orphan coaches → market) ----
    # Per the task brief: "Set staff.promotion_id = NULL for ~200 staff
    # (creating the free-agent pool) — keep the rest assigned to their
    # current promos."
    #
    # The world DB has 300 coaches with promotion_id IS NULL already
    # (gym-affiliated only). To make them true free agents (hirable
    # by the player), we also NULL their gym_id (so they're not bound
    # to any gym). The first 200 by staff_id become market candidates
    # (deterministic — same set on every fresh world build).
    #
    # The 82 promo-bound staff (commentators/cutmen/doctors/GMs/scouts)
    # STAY assigned to their promos — the rival AI's staff_manager
    # manages those, and the player shouldn't be able to poach them
    # out from under the AI.
    orphan_coaches = conn.execute(
        "SELECT staff_id FROM staff "
        "WHERE role_type='coach' "
        "  AND promotion_id IS NULL "
        "  AND gym_id IS NOT NULL "
        "ORDER BY staff_id "
        "LIMIT 200"
    ).fetchall()
    n_freed = 0
    for (staff_id,) in orphan_coaches:
        conn.execute(
            "UPDATE staff SET gym_id=NULL WHERE staff_id=?",
            (staff_id,),
        )
        n_freed += 1

    # Mark the backfill as done so a re-migrate doesn't re-randomize.
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (migration_name) "
        "VALUES ('v3_22_0_backfill_done')"
    )

    print(f"  Backfilled skill_level + salary_ask for {n_skill_set} "
          f"staff rows.")
    print(f"  Free-agent pool: freed {n_freed} orphan coaches "
          f"(gym_id → NULL).")


def _migrate_v3_23_0_add_bankruptcy_rebuild_columns(conn):
    """Fix 2 — Bankruptcy recovery ("new ownership" mechanism) per
    docs/DESIGN_REVIEW_E5.md §2.

    Adds 2 columns to `promotions` for the rebuilding period that
    follows a bankruptcy failure state:
      - is_rebuilding          INTEGER NOT NULL DEFAULT 0
                               CHECK (is_rebuilding IN (0, 1))
      - rebuilding_until_date  TEXT (ISO 'YYYY-MM-DD', nullable)

    Per CONVENTIONS §1.1, adding NOT NULL DEFAULT columns to an
    existing table qualifies as MINOR (3.22.0 → 3.23.0). Per §16.4,
    each ALTER is guarded by _has_column so the migration is
    idempotent. SQLite ALTER TABLE ADD COLUMN with NOT NULL DEFAULT
    <const> is metadata-only — no row rewrite.

    No backfill is needed — every existing promo starts with
    is_rebuilding=0 (the column DEFAULT), and rebuilding_until_date
    is NULL (no promo is currently rebuilding). The columns are
    populated by src/reputation.py::_fire_bankruptcy_failure when
    the bankruptcy failure state fires, and cleared by
    src/reputation.py::_check_rebuilding_status when the 6-month
    rebuilding period ends.

    Migration name: v3_23_0_add_bankruptcy_rebuild_columns. On
    --fresh builds, the SCHEMA_SQL already includes the 2 new
    columns (the migration function is not called, but the
    migration_name is still recorded in schema_migrations per §16.4).
    """
    if not _has_column(conn, "promotions", "is_rebuilding"):
        conn.execute(
            "ALTER TABLE promotions ADD COLUMN is_rebuilding INTEGER "
            "NOT NULL DEFAULT 0 CHECK (is_rebuilding IN (0, 1))"
        )
    if not _has_column(conn, "promotions", "rebuilding_until_date"):
        conn.execute(
            "ALTER TABLE promotions ADD COLUMN rebuilding_until_date TEXT"
        )


def _migrate_v3_24_0_add_realization_column(conn):
    """CR-M1 (docs/MASTER_PLAN_MATCHMAKING.md §2.1): add `realization`
    column to fighter_career.

    realization is a 0.4-1.0 multiplier on effective_ceiling that
    represents how close a fighter gets to their theoretical potential.
    Set at fighter creation from personality — NOT every fighter hits
    their peak.

    This migration was missing from the original MIGRATIONS list (the
    column was added via an uncommitted ALTER TABLE script). A fresh
    --fresh build would NOT have had the column. This migration fixes
    that + backfills existing fighters based on personality (same
    formula as fighter_gen.generate_realization).

    Migration name: v3_24_0_add_realization_column. Idempotent via
    _has_column guard.
    """
    if not _has_column(conn, "fighter_career", "realization"):
        conn.execute(
            "ALTER TABLE fighter_career ADD COLUMN realization REAL DEFAULT 0.7"
        )
        # Backfill existing fighters based on personality
        import random
        random.seed(42)
        rows = conn.execute("""
            SELECT fc.fighter_id, fp.discipline, fp.coachability,
                   fp.professionalism, fp.ego, fp.risk_taking,
                   fp.attention_seeking
            FROM fighter_career fc
            LEFT JOIN fighter_personality fp ON fp.fighter_id = fc.fighter_id
        """).fetchall()
        for fid, discipline, coachability, professionalism, ego, risk_taking, attention_seeking in rows:
            realization = 0.7
            if discipline and discipline >= 70: realization += 0.10
            if coachability and coachability >= 70: realization += 0.10
            if professionalism and professionalism >= 70: realization += 0.05
            if ego and ego >= 70: realization -= 0.10
            if risk_taking and risk_taking >= 80: realization -= 0.10
            if attention_seeking and attention_seeking >= 70: realization -= 0.05
            realization += random.uniform(-0.05, 0.05)
            realization = max(0.4, min(1.0, realization))
            conn.execute(
                "UPDATE fighter_career SET realization=? WHERE fighter_id=?",
                (realization, fid),
            )


def _migrate_v3_25_0_add_bidding_alerts(conn):
    """Phase M3.2 (docs/MASTER_PLAN_MATCHMAKING.md §2.2): add the
    `bidding_alerts` table for player-vs-AI bidding wars.

    bidding_alerts persists "rival AI is pursuing this free agent"
    alerts so the player can counter-offer within a decision window
    (default 3 sim-days). The rival AI's signing is deferred by the
    window; if the player counter-offers, the fighter chooses between
    the two offers based on a unified formula (reputation + salary +
    bonus + size_tier fit + realization-weighted potential).

    See SCHEMA_SQL above for full table + index DDL + lifecycle docs.

    Migration name: v3_25_0_add_bidding_alerts. Idempotent via
    _has_table guard (CREATE TABLE IF NOT EXISTS is also idempotent
    but _has_table short-circuits the no-op case for clarity).
    """
    if not _has_table(conn, "bidding_alerts"):
        conn.execute("""
            CREATE TABLE bidding_alerts (
                alert_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fighter_id            INTEGER NOT NULL REFERENCES fighters(fighter_id)
                                          ON DELETE CASCADE,
                rival_promo_id        INTEGER NOT NULL REFERENCES promotions(promotion_id)
                                          ON DELETE CASCADE,
                offered_salary        REAL NOT NULL,
                offered_bonus         REAL NOT NULL DEFAULT 0,
                offer_score           REAL NOT NULL,
                intent_date           TEXT NOT NULL,
                expiry_date           TEXT NOT NULL,
                decision_window_days  INTEGER NOT NULL DEFAULT 3
                                          CHECK (decision_window_days BETWEEN 1 AND 14),
                status                TEXT NOT NULL DEFAULT 'pending'
                                          CHECK (status IN (
                                              'pending', 'won_by_player',
                                              'won_by_rival', 'lost_race'
                                          )),
                player_offer_salary   REAL,
                player_offer_bonus    REAL,
                player_offer_score    REAL,
                resolved_date         TEXT,
                created_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
        """)
        conn.execute(
            "CREATE INDEX idx_bidding_alerts_fighter "
            "ON bidding_alerts(fighter_id)"
        )
        conn.execute(
            "CREATE INDEX idx_bidding_alerts_status "
            "ON bidding_alerts(status, expiry_date)"
        )
        conn.execute(
            "CREATE INDEX idx_bidding_alerts_rival "
            "ON bidding_alerts(rival_promo_id)"
        )


def _migrate_v3_25_0_add_staff_regen_lineage(conn):
    """Phase M2.3 (docs/MASTER_PLAN_MATCHMAKING.md §2.3): add the
    `staff_regen_lineage` table.

    Mirrors `regen_lineage` (for fighters) but for STAFF. When a staff
    member retires (Phase M2.2 annual tick on Jan 1), the retirement
    service generates a replacement staff member with a similar skill
    range + same role_type. This table tracks which retiring staff
    spawned which replacement, so future torch-passing narrative
    features (e.g., "the legendary GM's successor takes over" news
    items) can read the link without needing a schema change.

    Schema is intentionally minimal — just (retiring_staff_id,
    replacement_staff_id, role_type, regen_date). The full staff
    profile (name, age, skill_level, specialty) lives on the `staff`
    table; this lineage table just links two staff rows.

    Migration name: v3_25_0_add_staff_regen_lineage. Idempotent via
    _has_table guard. NOTE: shares the v3.25.0 version slot with
    v3_25_0_add_bidding_alerts (M3.2 work) — both run on the same
    migration pass; both are recorded in schema_migrations so a
    re-run is a no-op for both.
    """
    if not _has_table(conn, "staff_regen_lineage"):
        conn.execute("""
            CREATE TABLE staff_regen_lineage (
                regen_id               INTEGER PRIMARY KEY AUTOINCREMENT,
                retiring_staff_id      INTEGER REFERENCES staff(staff_id)
                                          ON DELETE SET NULL,
                replacement_staff_id   INTEGER REFERENCES staff(staff_id)
                                          ON DELETE SET NULL,
                role_type              TEXT NOT NULL,
                regen_date             TEXT NOT NULL,
                created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE (retiring_staff_id, replacement_staff_id)
            )
        """)
        conn.execute(
            "CREATE INDEX idx_staff_regen_lineage_retiring "
            "ON staff_regen_lineage(retiring_staff_id)"
        )
        conn.execute(
            "CREATE INDEX idx_staff_regen_lineage_replacement "
            "ON staff_regen_lineage(replacement_staff_id)"
        )


def _migrate_v3_26_0_add_show_quality_adjustment_txn_type(conn):
    """Phase F1.1 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F1.1) — add
    'show_quality_adjustment' to the finance_transactions transaction_type
    CHECK constraint.

    Background: prior to Phase F1, post-event finance was a single-shot
    computation that ignored show quality. A blockbuster show (rating 85+)
    earned the same PPV + merch revenue as a dud (rating 25). This made
    finances too easy — the player could stack a boring card with two
    marketable stars and still book the same PPV revenue as a Fight of
    the Year candidate.

    Phase F1.1 fixes this by adding a SECOND finance_transactions row
    AFTER show_rating.compute_ratings has written its row. The row is:
      type:        'show_quality_adjustment'
      amount:      (quality_mult - 1.0) * (original_ppv + original_merch)
                   where quality_mult is 1.30 (rating >= 80), 1.10 (60-79),
                   1.0 (40-59), or 0.80 (< 40). For the +30% case the
                   amount is positive (extra revenue); for the -20% case
                   it's negative (refunds / lost word-of-mouth buys).
      description: "show quality adjustment (rating=82, +30% PPV+merch)"

    Per CONVENTIONS §16.6, SQLite cannot ALTER a CHECK constraint in
    place — the only way to expand the enum is a table rebuild
    (rename → recreate → copy → drop). Idempotent via _has_check_constraint
    guard so re-runs are a no-op.

    The new CHECK enum (14 values total — was 13 before F1.1):
      'ticket_sales', 'broadcast_revenue', 'merchandise',
      'fighter_purse', 'venue_rental', 'staff_salary',
      'medical_cost', 'signing_bonus', 'weight_cut_penalty',
      'sponsorship', 'bonus_payment', 'concessions', 'marketing',
      'show_quality_adjustment'   (new — Phase F1.1)

    Migration name: v3_26_0_add_show_quality_adjustment_txn_type. On
    --fresh builds, SCHEMA_SQL already includes the new CHECK value
    (the migration function is not called, but the migration_name is
    still recorded in schema_migrations per §16.4 — same idempotency
    pattern as every other migration).
    """
    # Idempotency guard: if the existing table's CHECK already includes
    # 'show_quality_adjustment', the migration has already been applied.
    if _has_check_constraint(conn, "finance_transactions",
                             "show_quality_adjustment"):
        return

    # Defensive: only attempt the rebuild if finance_transactions exists.
    if not _has_table(conn, "finance_transactions"):
        return

    # SQLite table-rebuild pattern (CONVENTIONS §16.6). The new CHECK
    # is a SUPERSET of the old one, so every existing row is still
    # valid (no row transformation needed).
    conn.executescript("""
        ALTER TABLE finance_transactions RENAME TO finance_transactions_old_v3_26;
    """)
    conn.executescript("""
        CREATE TABLE finance_transactions (
            transaction_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            promotion_id            INTEGER NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
            event_id                INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
            fighter_id              INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
            transaction_type        TEXT NOT NULL CHECK (transaction_type IN (
                'ticket_sales', 'broadcast_revenue', 'merchandise',
                'fighter_purse', 'venue_rental', 'staff_salary',
                'medical_cost', 'signing_bonus', 'weight_cut_penalty',
                'sponsorship', 'bonus_payment', 'concessions',
                'marketing', 'show_quality_adjustment'
            )),
            amount                  REAL NOT NULL,
            description             TEXT,
            transaction_date        TEXT NOT NULL,
            created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        );
        INSERT INTO finance_transactions
            (transaction_id, promotion_id, event_id, fighter_id,
             transaction_type, amount, description, transaction_date,
             created_at)
        SELECT transaction_id, promotion_id, event_id, fighter_id,
               transaction_type, amount, description, transaction_date,
               created_at
        FROM finance_transactions_old_v3_26;
        DROP TABLE finance_transactions_old_v3_26;
    """)


def _migrate_v3_27_0_add_financial_state_column(conn):
    """HW1.4 (docs/Hardening_Phase.md §HW1.4 / CRITICAL #4) — add the
    `financial_state` column to `promotions`.

    The 7-state financial lifecycle:
      HEALTHY    → cash comfortable (>= starting_budget × 0.20)
      PRESSURED  → cash < 0.20 × starting_budget for 2 months
      STRUGGLING → cash < 0.10 × starting_budget for 2 months
      CRISIS     → cash < 0 for 1 month
      BANKRUPT   → cash < 0 for 3 consecutive months (transient —
                   immediately transitions to REBUILDING via
                   _fire_bankruptcy_failure)
      REBUILDING → 6-month post-bankruptcy recovery (is_rebuilding=1)
      RECOVERING → rebuilding period complete, cash climbing back
                   toward starting_budget × 0.50

    The state machine is implemented in src/reputation.py
    (_check_financial_state_transitions), called monthly on
    TICK_ADVANCED. Each transition writes a voice-compliant news item
    + applies a consequence (PRESSURED = -10% marketing spend on
    next event; STRUGGLING = release 1 staff; CRISIS = block FA
    signings; etc.).

    Per CONVENTIONS §1.1, adding a NOT NULL DEFAULT column with a
    CHECK constraint to an existing table qualifies as MINOR
    (3.26.0 → 3.27.0). SQLite ALTER TABLE ADD COLUMN with NOT NULL
    DEFAULT + CHECK is supported (verified — see worklog HW1.4 entry
    for the SQLite version test). The ALTER is metadata-only — no
    row rewrite (the DEFAULT 'HEALTHY' is a compile-time constant).

    Backfill (per-promo, derived from existing state):
      - is_rebuilding=1 → 'REBUILDING' (covers promos in the 6-month
        post-bankruptcy recovery window)
      - current_cash < 0 → 'CRISIS' (covers promos in the 3-month
        bankruptcy-trigger window; they may already have a partial
        bankruptcy_warnings counter)
      - otherwise → 'HEALTHY' (the DEFAULT — most promos start here)

    Migration name: v3_27_0_add_financial_state_column. Idempotent via
    _has_column guard. On --fresh builds, SCHEMA_SQL already includes
    the new column (the migration function is not called, but the
    migration_name is still recorded in schema_migrations per §16.4).
    """
    if not _has_column(conn, "promotions", "financial_state"):
        conn.execute(
            "ALTER TABLE promotions ADD COLUMN financial_state TEXT "
            "NOT NULL DEFAULT 'HEALTHY' CHECK (financial_state IN ("
            "'HEALTHY', 'PRESSURED', 'STRUGGLING', 'CRISIS', "
            "'BANKRUPT', 'REBUILDING', 'RECOVERING'))"
        )
        # Backfill existing promos based on is_rebuilding + current_cash.
        # REBUILDING takes precedence (a rebuilding promo is by
        # definition in the post-bankruptcy recovery window).
        conn.execute(
            "UPDATE promotions SET financial_state='REBUILDING' "
            "WHERE is_rebuilding=1"
        )
        # CRISIS — promos with negative cash but not yet bankrupt
        # (the bankruptcy failure state hasn't fired yet, or the
        # promo is in the 3-month lead-up).
        conn.execute(
            "UPDATE promotions SET financial_state='CRISIS' "
            "WHERE current_cash < 0 AND is_rebuilding=0"
        )


def _migrate_v3_28_0_expand_memory_link_types_with_hw3_values(conn):
    """HW3 (docs/Hardening_Phase.md §HW3.1 / CRITICAL #6) — expand
    `fighter_memory_links.link_type` CHECK with 4 new values:
    'title_history', 'upset', 'comeback', 'milestone'.

    Per CONVENTIONS §16.6, SQLite cannot ALTER a CHECK constraint in
    place — the only way to expand a column's CHECK enum is a TABLE
    REBUILD: rename the old table, create the new table with the
    updated CHECK, copy data over, drop the old table. The existing
    data (775 rows: regional_rival 744 + style_echo 29 + successor 2
    in the seeded world DB) is preserved verbatim — the new CHECK is
    a SUPERSET of the old one, so every existing row still satisfies
    it.

    Idempotent (per CONVENTIONS §16.4): the migration runner records
    its migration_name in schema_migrations AFTER it runs. If the
    migration crashes mid-way, the next run re-executes it — the
    partial work must be safe to re-apply. The `_has_check_constraint`
    guard detects whether the new CHECK is already in place and skips
    the rebuild (so a re-run after a successful migration is a no-op).
    The sentinel used is 'title_history' (a sentinel from the new
    enum that didn't exist before).

    The new CHECK enum (12 values total):
      'style_echo', 'gym_heir', 'regional_rival', 'successor'      (existing v1)
      'previous_fight', 'shared_gym', 'former_teammate',           (v3.12.0)
      'injury_history'                                              (v3.12.0)
      'title_history', 'upset', 'comeback', 'milestone'            (v3.28.0 — NEW)

    Migration name: v3_28_0_expand_memory_link_types_with_hw3_values.
    On --fresh builds, SCHEMA_SQL already includes the new CHECK (the
    migration function is not called, but the migration_name is still
    recorded in schema_migrations per §16.4 — same idempotency pattern
    as every other migration).
    """
    # Idempotency guard: if the existing table's CHECK already includes
    # 'title_history' (a sentinel from the new enum), the migration has
    # already been applied — no-op.
    if _has_check_constraint(conn, "fighter_memory_links",
                             "title_history"):
        return

    # Defensive: only attempt the rebuild if fighter_memory_links exists.
    # On a fresh --fresh build, the SCHEMA_SQL already creates the table
    # with the new CHECK (and the idempotency guard above would have
    # returned), so we only get here on a --migrate path from a v3.27.0
    # DB.
    if not _has_table(conn, "fighter_memory_links"):
        # Defensive — create the table with the new CHECK (matches
        # SCHEMA_SQL exactly). Should never happen on the migrate path
        # (every v3.x DB has this table), but the migration must not
        # crash on edge cases.
        conn.execute(
            "CREATE TABLE fighter_memory_links (\n"
            "    memory_link_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    link_type TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history', 'title_history', 'upset', 'comeback', 'milestone')),\n"
            "    link_strength INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_id, linked_fighter_id, link_type)\n"
            ")"
        )
        return

    # SQLite table-rebuild pattern (CONVENTIONS §16.6):
    #   1. Rename the old table.
    #   2. Create the new table with the updated CHECK (matches
    #      SCHEMA_SQL exactly).
    #   3. Copy all rows verbatim from the old table — the new CHECK
    #      is a SUPERSET of the old one, so every existing row is
    #      still valid (no row transformation needed).
    #   4. Drop the old table.
    # We accept the brief window where the table is renamed (the
    # migration runs in a single transaction — caller commits).
    conn.executescript("""
        ALTER TABLE fighter_memory_links RENAME TO fighter_memory_links_old_v3_28;
    """)
    conn.executescript("""
        CREATE TABLE fighter_memory_links (
            memory_link_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
            linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
            link_type         TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history', 'title_history', 'upset', 'comeback', 'milestone')),
            link_strength     INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),
            created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE (fighter_id, linked_fighter_id, link_type)
        );
        INSERT INTO fighter_memory_links
            (memory_link_id, fighter_id, linked_fighter_id, link_type,
             link_strength, created_at)
        SELECT memory_link_id, fighter_id, linked_fighter_id, link_type,
               link_strength, created_at
        FROM fighter_memory_links_old_v3_28;
        DROP TABLE fighter_memory_links_old_v3_28;
    """)


def _migrate_v3_29_0_add_simulation_tick_health(conn):
    """HW2.1 (docs/Hardening_Phase.md §HW2.1 / CRITICAL #5) — add the
    `simulation_tick_health` table.

    One row per tick summarizing: tick duration, EventBus subscriber
    success/failure counts, JSON blob of subscriber errors (with
    traceback + sim date), and aggregate counts of the tick's side
    effects (events/fights/fighters/injuries/contracts/titles/rankings
    /finance/news/social/memory).

    Idempotent: the _has_table guard skips the CREATE if the table
    already exists (re-running the migration on a DB that already has
    the table from SCHEMA_SQL is a no-op). On --fresh builds, SCHEMA_SQL
    already creates the table — the migration function is not called,
    but the migration_name is still recorded in schema_migrations per
    §16.4.
    """
    if _has_table(conn, "simulation_tick_health"):
        return
    conn.execute("""
CREATE TABLE simulation_tick_health (
    tick_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_date              TEXT NOT NULL,
    tick_duration_ms       INTEGER NOT NULL DEFAULT 0,
    tick_success           INTEGER NOT NULL DEFAULT 1
                               CHECK (tick_success IN (-1, 0, 1)),
    health_status          TEXT NOT NULL DEFAULT 'HEALTHY'
                               CHECK (health_status IN
                                      ('HEALTHY', 'DEGRADED', 'BROKEN')),
    subscribers_invoked    INTEGER NOT NULL DEFAULT 0,
    subscribers_succeeded  INTEGER NOT NULL DEFAULT 0,
    subscribers_failed     INTEGER NOT NULL DEFAULT 0,
    errors_json            TEXT,
    events_scheduled       INTEGER NOT NULL DEFAULT 0,
    events_completed       INTEGER NOT NULL DEFAULT 0,
    fights_resolved        INTEGER NOT NULL DEFAULT 0,
    fighters_retired       INTEGER NOT NULL DEFAULT 0,
    fighters_regen         INTEGER NOT NULL DEFAULT 0,
    injuries_created       INTEGER NOT NULL DEFAULT 0,
    injuries_recovered     INTEGER NOT NULL DEFAULT 0,
    contracts_changed      INTEGER NOT NULL DEFAULT 0,
    title_changes          INTEGER NOT NULL DEFAULT 0,
    ranking_changes        INTEGER NOT NULL DEFAULT 0,
    finance_transactions   INTEGER NOT NULL DEFAULT 0,
    news_generated         INTEGER NOT NULL DEFAULT 0,
    social_posts_generated INTEGER NOT NULL DEFAULT 0,
    memories_generated     INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tick_health_date "
        "ON simulation_tick_health (tick_date DESC);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tick_health_status "
        "ON simulation_tick_health (tick_success, tick_date DESC);"
    )


def _migrate_v3_30_0_add_news_items_importance(conn):
    """HW4.1 (docs/Hardening_Phase.md §HW4.1 / W19) — add the
    `importance` column to news_items.

    5 tiers (CHECK'd):
      LEGENDARY  — title change (championship), Hall of Fame
                   induction, career-ending injury
      MAJOR      — signing, retirement, major upset, rivalry
                   escalation
      SIGNIFICANT— fight result, injury, suspension, comeback
      ROUTINE    — training camp, finance, weight cut, event hype
      BACKGROUND — tapping_up_rumor, social media, generic

    Per CONVENTIONS §1.1, adding a NOT NULL DEFAULT column with a
    CHECK constraint to an existing table qualifies as MINOR
    (3.29.0 → 3.30.0). SQLite ALTER TABLE ADD COLUMN with NOT NULL
    DEFAULT + CHECK is supported (same pattern as v3.27.0
    financial_state — verified to work on the SQLite version we
    ship). The ALTER is metadata-only — no row rewrite (the DEFAULT
    'ROUTINE' is a compile-time constant).

    Backfill (HW4.2): existing news_items get a tier derived from
    their topic. Title-fight + retirement + Hall-of-Fame topics →
    LEGENDARY/MAJOR (kept as-is by the A6 pruner, so they're
    already long-lived). Most existing rows get ROUTINE (the
    default — the world DB has 1352 'fight' + 734 'injury' rows
    that are SIGNIFICANT, but for backfill we just stamp them all
    ROUTINE and let future news get the right tier via the writer's
    importance parameter — see news._write_news_item).

    Actually, to make the existing world DB immediately useful for
    the daily-cap check (HW4.3), we backfill existing rows with a
    best-effort topic → importance mapping so historical rows
    aren't all ROUTINE. Title / awards → LEGENDARY; signing /
    retirement / release / inter_promo_callout → MAJOR; fight /
    injury / suspension / career_arc / cross_promo → SIGNIFICANT;
    finance / event_hype / weight_cut / training / show_rating /
    prospect / reputation_marker / small_reward → ROUTINE;
    tapping_up_rumor / news_engine / memory_resurfacing / staff →
    BACKGROUND.

    Migration name: v3_30_0_add_news_items_importance. Idempotent
    via _has_column guard. On --fresh builds, SCHEMA_SQL already
    includes the new column (the migration function is not called,
    but the migration_name is still recorded in schema_migrations
    per §16.4).
    """
    if not _has_column(conn, "news_items", "importance"):
        conn.execute(
            "ALTER TABLE news_items ADD COLUMN importance TEXT "
            "NOT NULL DEFAULT 'ROUTINE' CHECK (importance IN ("
            "'LEGENDARY', 'MAJOR', 'SIGNIFICANT', 'ROUTINE', "
            "'BACKGROUND'))"
        )
    # HW4.2 backfill — stamp existing rows with a best-effort tier
    # derived from their topic. Only UPDATEs rows where importance
    # is still the default 'ROUTINE' (so re-runs are no-ops once
    # the backfill has applied). This makes the daily-cap check
    # (HW4.3) immediately useful on the existing world DB.
    _IMPORTANCE_BACKFILL = [
        ("LEGENDARY", ("title", "awards")),
        ("MAJOR", ("signing", "retirement", "release",
                   "inter_promo_callout")),
        ("SIGNIFICANT", ("fight", "injury", "suspension",
                         "career_arc", "cross_promo")),
        ("BACKGROUND", ("tapping_up_rumor", "news_engine",
                        "memory_resurfacing", "staff")),
        # ROUTINE topics: finance, event_hype, weight_cut, training,
        # show_rating, prospect, reputation_marker, small_reward —
        # these are the DEFAULT so no UPDATE needed.
    ]
    for tier, topics in _IMPORTANCE_BACKFILL:
        placeholders = ",".join("?" for _ in topics)
        conn.execute(
            f"UPDATE news_items SET importance=? "
            f"WHERE importance='ROUTINE' AND topic IN ({placeholders})",
            (tier, *topics),
        )
    # Index for the daily-cap lookup (HW4.3): the cap check queries
    # COUNT(*) FROM news_items WHERE published_at = ? AND importance = ?.
    # A composite index on (published_at, importance) makes this O(1).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_items_date_importance "
        "ON news_items (published_at, importance);"
    )


def _migrate_v3_31_0_add_perf_indexes(conn):
    """HW8.2 — Add performance indexes on training_camps + fight_beats.

    The HW6.3 soak test surfaced super-linear per-tick cost growth:
    0.37s/tick at day 30 → 3.0s/tick at day 180. Root cause: the
    training_camps + fight_beats tables had NO indexes (only the
    autoindex on their primary keys), so every per-tick query scanned
    the full table. As the tables grew (training_camps to ~9000 rows
    over 180 days, fight_beats to ~80K rows), the scans dominated
    tick cost.

    This migration adds 4 indexes:
      1. idx_training_camps_active_window — covers the daily tick's
         _check_training_camps query: WHERE is_active=1 AND
         is_completed=0 AND start_date<=? AND end_date>=?.
      2. idx_training_camps_fighter — covers per-fighter camp lookups
         (used by matchmaking's camp_status check + the dashboard's
         camp history).
      3. idx_fight_beats_fight — covers per-fight beat lookups (used
         by show_rating + fight_engine's per-fight aggregation).
      4. idx_fight_beats_round — covers per-round beat lookups
         (used by fight_engine's round aggregation).

    The indexes are CREATE IF NOT EXISTS so they're idempotent. The
    migration also runs ANALYZE on the 2 tables so the query planner
    picks up the new indexes immediately.
    """
    # training_camps — daily tick window + per-fighter lookups.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_camps_active_window "
        "ON training_camps (is_active, is_completed, start_date, end_date);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_camps_fighter "
        "ON training_camps (fighter_id, is_completed, end_date);"
    )
    # fight_beats — per-fight + per-round lookups.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fight_beats_fight "
        "ON fight_beats (fight_id, round_number);"
    )
    # Refresh the query planner's stats so the new indexes are picked
    # up immediately (without ANALYZE, SQLite might keep using the
    # autoindex until the next ANALYZE pass).
    try:
        conn.execute("ANALYZE training_camps;")
        conn.execute("ANALYZE fight_beats;")
    except sqlite3.OperationalError:
        # ANALYZE can fail on a brand-new empty table (no stats to
        # gather). Safe to ignore — the indexes are still created.
        pass


def _migrate_v3_32_0_add_news_global_daily_cap_trigger(conn):
    """HW8.3 — Add a SQLite trigger that enforces a global daily cap
    on news_items writes (catches ALL writes, including direct
    INSERTs that bypass news._write_news_item).

    The HW6.3 soak test showed news_items bloating from 2400 → 10581
    rows in 180 days (+7399 ROUTINE, ~41/day). The HW4.3 soft caps in
    _IMPORTANCE_DAILY_CAPS only applied to items that went through
    _write_news_item — but 30+ direct INSERT INTO news_items callsites
    bypass that function, so the soft caps didn't catch them.

    This migration adds a BEFORE INSERT trigger that counts existing
    news_items for the same published_at date (using date() to
    normalize both sides) + silently drops the INSERT (RAISE IGNORE)
    if the count is at or above the cap.

    The cap is set to 30/day (= LEGENDARY 1 + MAJOR 3 + SIGNIFICANT 5
    + ROUTINE 5 + BACKGROUND 5 + 11 spare for direct-INSERT bypass
    paths). The cap is intentionally loose — it's a HARD ceiling to
    prevent runaway bloat, NOT a throttle on legitimate news. The
    soft caps in _write_news_item remain the primary throttle.

    Trigger details:
      - Name: trg_news_items_global_daily_cap
      - Fires: BEFORE INSERT ON news_items
      - Condition: COUNT(*) for same date(published_at) >= 30
      - Action: RAISE(IGNORE) — silently drop the INSERT
      - Date normalization: date(COALESCE(NEW.published_at,
        CURRENT_TIMESTAMP)) so NULL + timestamp formats all match

    Side effects:
      - INSERT statements that hit the cap return 0 rows affected
        (the caller's lastrowid will be None). All current callers
        either ignore the return value or handle None defensively.
      - The trigger is per-row, so multi-row INSERTs are evaluated
        per-row (each row gets its own cap check). This is correct
        behavior — the cap is a per-day total, not a per-statement
        total.
      - The trigger is idempotent (DROP TRIGGER IF EXISTS before
        CREATE TRIGGER) so re-running the migration is safe.
    """
    # Drop existing trigger (defensive — idempotent re-runs).
    conn.execute("DROP TRIGGER IF EXISTS trg_news_items_global_daily_cap;")
    # Create the trigger. The WHEN clause uses a correlated subquery
    # to count existing items for the same date. The COALESCE handles
    # NULL published_at (falls back to CURRENT_TIMESTAMP). The date()
    # function normalizes both 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM:SS'
    # formats to 'YYYY-MM-DD' so they compare correctly.
    #
    # HW10.1 (news cap audit): the trigger is now IMPORTANCE-AWARE —
    # LEGENDARY + MAJOR items are NEVER suppressed, even if the daily
    # cap is hit. This prevents the player from missing title changes,
    # Hall of Fame inductions, major signings, or retirements just
    # because the day was busy. The cap still applies to SIGNIFICANT +
    # ROUTINE + BACKGROUND (the high-volume tiers that cause feed
    # bloat). Per the user's audit concern: "is there a chance the
    # player might miss important news with a cap?" — now they can't.
    conn.execute(
        """
        CREATE TRIGGER trg_news_items_global_daily_cap
        BEFORE INSERT ON news_items
        WHEN (
            SELECT COUNT(*) FROM news_items
            WHERE date(COALESCE(published_at, CURRENT_TIMESTAMP))
                = date(COALESCE(NEW.published_at, CURRENT_TIMESTAMP))
        ) >= 30
        AND COALESCE(NEW.importance, 'ROUTINE') NOT IN ('LEGENDARY', 'MAJOR')
        BEGIN
            SELECT RAISE(IGNORE);
        END;
        """
    )


def _migrate_v3_33_0_news_cap_importance_aware(conn):
    """HW10.1 — Make the news cap trigger importance-aware.

    The HW8.3 trigger suppressed ALL news items beyond 30/day. The
    user's audit concern: "is there a chance the player might miss
    important news with a cap?" — YES, on busy days (events +
    signings + injuries stacking up), LEGENDARY/MAJOR items could
    be suppressed.

    This migration drops + recreates the trigger with an importance-
    aware WHEN clause: LEGENDARY + MAJOR items bypass the cap
    entirely. SIGNIFICANT + ROUTINE + BACKGROUND are still capped
    (they're the high-volume tiers that cause feed bloat).

    The cap is still 30/day for the capped tiers — same as HW8.3.
    Only the importance filter is new.

    Idempotent: DROP TRIGGER IF EXISTS before CREATE TRIGGER.
    """
    conn.execute("DROP TRIGGER IF EXISTS trg_news_items_global_daily_cap;")
    conn.execute(
        """
        CREATE TRIGGER trg_news_items_global_daily_cap
        BEFORE INSERT ON news_items
        WHEN (
            SELECT COUNT(*) FROM news_items
            WHERE date(COALESCE(published_at, CURRENT_TIMESTAMP))
                = date(COALESCE(NEW.published_at, CURRENT_TIMESTAMP))
        ) >= 30
        AND COALESCE(NEW.importance, 'ROUTINE') NOT IN ('LEGENDARY', 'MAJOR')
        BEGIN
            SELECT RAISE(IGNORE);
        END;
        """
    )


def _migrate_v3_34_0_add_rival_ai_memory(conn):
    """HW10-W21W22 — Add the rival_ai_memory table + 2 supporting indexes.

    The rival AI used to be STATELESS PER TICK — every rival promo
    scheduled events, signed free agents, and resolved fights without
    remembering its own past results, bidding wars lost, fighters
    signed/released, or title histories. GPT's W21 feedback: "Rival
    AI should react to its own previous results." GPT's W22 feedback:
    "Rival promotions should remember past interactions."

    This migration adds the rival_ai_memory table:
      - promotion_id: the rival promo that owns the memory.
      - memory_type: one of 9 enums (event_result, signing_won,
        title_loss, title_win, bidding_war_lost, bidding_war_won,
        fighter_released, rivalry_fuelled, signing_missed).
      - target_fighter_id / target_promotion_id: the entity involved.
      - memory_date: sim date 'YYYY-MM-DD'.
      - context_json: arbitrary JSON (e.g. for event_result:
        {event_id, wins, losses, attendance, profit}).
      - salience: 0..100 (default 50), decays -1/week; row is DELETED
        when salience hits 0 (forgotten).

    Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT
    EXISTS, so re-running the migration on a DB that already has the
    table is a no-op. On a fresh --fresh build, SCHEMA_SQL already
    includes the table + indexes (the migration function is NOT
    called on --fresh per CONVENTIONS §16.4, but the migration_name
    IS recorded in schema_migrations for audit-trail consistency).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rival_ai_memory (
            memory_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            promotion_id         INTEGER NOT NULL REFERENCES promotions(promotion_id)
                                     ON DELETE CASCADE,
            memory_type          TEXT NOT NULL
                                     CHECK (memory_type IN (
                                         'event_result', 'signing_missed',
                                         'signing_won', 'title_loss', 'title_win',
                                         'bidding_war_lost', 'bidding_war_won',
                                         'fighter_released', 'rivalry_fuelled'
                                     )),
            target_fighter_id    INTEGER REFERENCES fighters(fighter_id)
                                     ON DELETE SET NULL,
            target_promotion_id  INTEGER REFERENCES promotions(promotion_id)
                                     ON DELETE SET NULL,
            memory_date          TEXT NOT NULL,
            context_json         TEXT,
            salience             INTEGER NOT NULL DEFAULT 50
                                     CHECK (salience BETWEEN 0 AND 100),
            created_at           TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rival_ai_memory_promo_type_date "
        "ON rival_ai_memory (promotion_id, memory_type, memory_date DESC);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rival_ai_memory_promo_salience "
        "ON rival_ai_memory (promotion_id, salience DESC);"
    )


def _migrate_v3_35_0_add_perf_indexes_2(conn):
    """TIER2-5YEAR §T2.3 — Add 3 additional performance indexes for
    5-year soak completion.

    The Tier 1 optimizations (v3.31.0 perf indexes + the daily
    fight_beats prune + the conditional weekly interpretation rebuild)
    brought the 365-day soak from "times out at day 310/365 in 9min"
    down to "complete in 1.86min" with a stable ~0.31s/day per-tick
    cost. Extrapolating linearly to 5 years (1825 days) gives ~9.4min,
    which is within the 15min budget — but the Tier 1 worklog noted
    that a few specific query patterns were still doing index scans
    instead of index seeks, and those would scale linearly with table
    growth over 5 years.

    This migration adds 3 indexes targeting the slowest-growing
    query patterns:

      1. ``idx_news_items_importance_date ON news_items (importance,
         published_at)`` — for the cap check query that filters by
         importance tier first (e.g. "show me the LEGENDARY items
         from the last 90 days, oldest first" — the news engine's
         importance-aware pruning pass). The existing
         ``idx_news_items_date_importance`` from v3.30.0 has the
         columns in the OPPOSITE order (published_at, importance),
         which serves the per-day cap check but NOT the per-importance
         historical lookup. Both indexes coexist (SQLite uses the one
         whose leading column matches the WHERE clause).

      2. ``idx_commentary_segments_fight ON commentary_segments
         (fight_id)`` — for fight highlight lookups. The Fight Night
         UI + the post-fight news engine both look up a fight's
         commentary segments by fight_id. Without an index, this is
         a full-table scan that grows linearly with fight count
         (~3-14 segments per fight, ~30K fights after 5 years →
         ~150K-420K rows scanned per lookup).

      3. ``idx_training_camps_completed_end ON training_camps
         (is_completed, end_date)`` — for pruning queries. The
         pruning service's monthly pass deletes completed camps
         older than 60 days. The existing
         ``idx_training_camps_active_window`` covers (is_active,
         is_completed, start_date, end_date) — useful for the daily
         "find active camps whose window contains today" lookup,
         but the leading column is_active=1 doesn't match the
         pruning query's WHERE (is_completed=1 AND end_date < ?).
         The new index has is_completed as the leading column,
         matching the pruning query.

    All 3 indexes use CREATE INDEX IF NOT EXISTS so they're
    idempotent — re-running the migration on a DB that already has
    them is a no-op. On a fresh --fresh build, SCHEMA_SQL already
    includes the indexes (the migration function is NOT called on
    --fresh per CONVENTIONS §16.4, but the migration_name IS
    recorded in schema_migrations for audit-trail consistency).

    The migration also runs ANALYZE on the 3 tables so the query
    planner picks up the new indexes immediately (without ANALYZE,
    SQLite might keep using an older index until the next ANALYZE
    pass).
    """
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_items_importance_date "
        "ON news_items (importance, published_at);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_commentary_segments_fight "
        "ON commentary_segments (fight_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_camps_completed_end "
        "ON training_camps (is_completed, end_date);"
    )
    # Refresh the query planner's stats so the new indexes are picked
    # up immediately (mirrors the v3.31.0 migration's ANALYZE step).
    try:
        conn.execute("ANALYZE news_items;")
        conn.execute("ANALYZE commentary_segments;")
        conn.execute("ANALYZE training_camps;")
    except sqlite3.OperationalError:
        # ANALYZE can fail on a brand-new empty table (no stats to
        # gather). Safe to ignore — the indexes are still created.
        pass


def _migrate_v3_36_0_add_provenance_metadata(conn):
    """TIER3-MISSING §T3.3 (W42) — Add provenance metadata columns to
    `schema_meta`.

    Adds 2 nullable TEXT columns:
      - ``world_version`` — set on each save (e.g. "sim_2026-08-27_tick14")
        by save_load.save_game before the DB file copy. NULL until the
        first save after this migration.
      - ``seed_version``  — set on fresh DB build (e.g. "world_seed_v1")
        by build_db._build_fresh. For existing DBs (the --migrate path),
        this migration backfills seed_version='world_seed_v1'
        retroactively (every existing DB was built from world_seed_v1).

    Both columns are nullable so old save files that predate the
    migration can still be loaded — the columns will be NULL until
    the next save writes them. save_load.load_game does NOT refuse a
    save with NULL provenance columns; it just leaves them NULL until
    the next save_game call updates them.

    Idempotent (per CONVENTIONS §16.4): the migration runner records
    its migration_name in schema_migrations AFTER it runs. If the
    migration crashes mid-way, the next run re-executes it. The
    `_has_column` guard on each ALTER TABLE makes re-runs safe — the
    ALTER is skipped if the column already exists. The UPDATE that
    backfills seed_version uses WHERE seed_version IS NULL so it's a
    no-op on a DB that already has the backfill.

    On --fresh builds, SCHEMA_SQL already includes the new columns
    (the migration function is not called, but the migration_name is
    still recorded in schema_migrations per §16.4 — same idempotency
    pattern as every other migration). The _build_fresh path then
    sets seed_version='world_seed_v1' explicitly.

    Migration name: v3_36_0_add_provenance_metadata.
    """
    # 1. Add world_version TEXT column (idempotent — _has_column guard).
    if not _has_column(conn, "schema_meta", "world_version"):
        conn.execute(
            "ALTER TABLE schema_meta ADD COLUMN world_version TEXT"
        )
    # 2. Add seed_version TEXT column (idempotent).
    if not _has_column(conn, "schema_meta", "seed_version"):
        conn.execute(
            "ALTER TABLE schema_meta ADD COLUMN seed_version TEXT"
        )
    # 3. Backfill seed_version='world_seed_v1' for existing DBs
    #    (every existing DB was built from world_seed_v1 per the
    #    brief). The WHERE seed_version IS NULL clause makes this
    #    idempotent — a re-run skips rows that already have a value.
    #    If the DB is missing the schema_meta row entirely (a fresh
    #    build before _build_fresh inserts the row), this UPDATE is a
    #    no-op (0 rows affected).
    try:
        conn.execute(
            "UPDATE schema_meta SET seed_version='world_seed_v1' "
            "WHERE seed_version IS NULL"
        )
    except sqlite3.OperationalError:
        # Defensive — the UPDATE can fail if schema_meta is missing
        # (shouldn't happen because _migrate_existing creates it
        # before calling _run_migrations, but defensive never hurts).
        pass


def _migrate_v3_36_0_expand_memory_link_types_tier3(conn):
    """TIER3-MISSING §T3.4 (W17) — Expand
    `fighter_memory_links.link_type` CHECK with 8 new values.

    Per CONVENTIONS §16.6, SQLite cannot ALTER a CHECK constraint in
    place — the only way to expand a column's CHECK enum is a TABLE
    REBUILD: rename the old table, create the new table with the
    updated CHECK, copy data over, drop the old table. The existing
    data (the 12 link_type values allowed by the v3.28.0 migration:
    style_echo, gym_heir, regional_rival, successor, previous_fight,
    shared_gym, former_teammate, injury_history, title_history,
    upset, comeback, milestone) is preserved verbatim — the new CHECK
    is a SUPERSET of the old one, so every existing row still
    satisfies it.

    Idempotent (per CONVENTIONS §16.4): the migration runner records
    its migration_name in schema_migrations AFTER it runs. The
    `_has_check_constraint` guard detects whether the new CHECK is
    already in place and skips the rebuild (so a re-run after a
    successful migration is a no-op). The sentinel used is
    'previous_fights' (a sentinel from the new enum that didn't exist
    before).

    The new CHECK enum (20 values total — 12 existing + 8 new):
      'style_echo', 'gym_heir', 'regional_rival', 'successor'      (v1)
      'previous_fight', 'shared_gym', 'former_teammate',           (v3.12.0)
      'injury_history'                                              (v3.12.0)
      'title_history', 'upset', 'comeback', 'milestone'            (v3.28.0)
      'previous_fights', 'former_teammates', 'old_gyms',           (v3.36.0 — NEW)
      'former_champions', 'controversial_losses', 'injuries',      (v3.36.0 — NEW)
      'promotions', 'old_events'                                   (v3.36.0 — NEW)

    The 8 new values are distinct from existing singular-form variants
    (previous_fight vs previous_fights, former_teammate vs
    former_teammates, injury_history vs injuries) — they capture
    related-but-distinct memory categories per the T3.4 brief. The
    brief specifies plural forms + new categories (old_gyms,
    former_champions, controversial_losses, promotions, old_events)
    that don't overlap with the existing 12.

    Migration name: v3_36_0_expand_memory_link_types_tier3. On
    --fresh builds, SCHEMA_SQL already includes the new CHECK (the
    migration function is not called, but the migration_name is
    still recorded in schema_migrations per §16.4 — same idempotency
    pattern as every other migration).
    """
    # Idempotency guard: if the existing table's CHECK already
    # includes 'previous_fights' (a sentinel from the new enum), the
    # migration has already been applied — no-op.
    if _has_check_constraint(conn, "fighter_memory_links",
                             "previous_fights"):
        return

    # Defensive: only attempt the rebuild if fighter_memory_links
    # exists. On a fresh --fresh build, SCHEMA_SQL already creates
    # the table with the new CHECK (and the idempotency guard above
    # would have returned), so we only get here on a --migrate path
    # from a v3.35.0 DB.
    if not _has_table(conn, "fighter_memory_links"):
        # Defensive — create the table with the new CHECK (matches
        # SCHEMA_SQL exactly). Should never happen on the migrate
        # path (every v3.x DB has this table), but the migration
        # must not crash on edge cases.
        conn.execute(
            "CREATE TABLE fighter_memory_links (\n"
            "    memory_link_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,\n"
            "    link_type TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history', 'title_history', 'upset', 'comeback', 'milestone', 'previous_fights', 'former_teammates', 'old_gyms', 'former_champions', 'controversial_losses', 'injuries', 'promotions', 'old_events')),\n"
            "    link_strength INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),\n"
            "    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),\n"
            "    UNIQUE (fighter_id, linked_fighter_id, link_type)\n"
            ")"
        )
        return

    # SQLite table-rebuild pattern (CONVENTIONS §16.6):
    #   1. Rename the old table.
    #   2. Create the new table with the updated CHECK (matches
    #      SCHEMA_SQL exactly).
    #   3. Copy all rows verbatim from the old table — the new CHECK
    #      is a SUPERSET of the old one, so every existing row is
    #      still valid (no row transformation needed).
    #   4. Drop the old table.
    # We accept the brief window where the table is renamed (the
    # migration runs in a single transaction — caller commits).
    conn.executescript("""
        ALTER TABLE fighter_memory_links RENAME TO fighter_memory_links_old_v3_36;
    """)
    conn.executescript("""
        CREATE TABLE fighter_memory_links (
            memory_link_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            fighter_id        INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
            linked_fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
            link_type         TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor', 'previous_fight', 'shared_gym', 'former_teammate', 'injury_history', 'title_history', 'upset', 'comeback', 'milestone', 'previous_fights', 'former_teammates', 'old_gyms', 'former_champions', 'controversial_losses', 'injuries', 'promotions', 'old_events')),
            link_strength     INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),
            created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE (fighter_id, linked_fighter_id, link_type)
        );
        INSERT INTO fighter_memory_links
            (memory_link_id, fighter_id, linked_fighter_id, link_type,
             link_strength, created_at)
        SELECT memory_link_id, fighter_id, linked_fighter_id, link_type,
               link_strength, created_at
        FROM fighter_memory_links_old_v3_36;
        DROP TABLE fighter_memory_links_old_v3_36;
    """)


MIGRATIONS = [
    ("v2_2_0_add_fighter_depth",   "2.2.0", _migrate_v2_2_0_add_fighter_depth),
    ("v2_3_0_add_beat_engine_depth","2.3.0", _migrate_v2_3_0_add_beat_engine_depth),
    ("v2_4_0_add_injuries",        "2.4.0", _migrate_v2_4_0_add_injuries),
    ("v2_5_0_add_training_camps",  "2.5.0", _migrate_v2_5_0_add_training_camps),
    ("v2_6_0_world_seed_prep",     "2.6.0", _migrate_v2_6_0_world_seed_prep),
    ("v2_7_0_add_weight_cut_log",  "2.7.0", _migrate_v2_7_0_add_weight_cut_log),
    ("v2_8_0_add_fighter_descriptors","2.8.0", _migrate_v2_8_0_add_fighter_descriptors),
    ("v2_9_0_add_scouting_reports","2.9.0", _migrate_v2_9_0_add_scouting_reports),
    ("v3_0_0_add_finance_transactions","3.0.0", _migrate_v3_0_0_add_finance_transactions),
    ("v3_1_0_add_social_posts",    "3.1.0", _migrate_v3_1_0_add_social_posts),
    ("v3_2_0_add_rivalries",       "3.2.0", _migrate_v3_2_0_add_rivalries),
    ("v3_3_0_add_matchup_analyses","3.3.0", _migrate_v3_3_0_add_matchup_analyses),
    ("v3_4_0_add_suspensions",     "3.4.0", _migrate_v3_4_0_add_suspensions),
    ("v3_5_0_add_agent_offers",    "3.5.0", _migrate_v3_5_0_add_agent_offers),
    ("v3_6_0_add_show_ratings",    "3.6.0", _migrate_v3_6_0_add_show_ratings),
    ("v3_7_0_add_player_settings", "3.7.0", _migrate_v3_7_0_add_player_settings),
    ("v3_8_0_add_staff_pundit_bias", "3.8.0", _migrate_v3_8_0_add_staff_pundit_bias),
    ("v3_9_0_add_staff_gym_id",      "3.9.0", _migrate_v3_9_0_add_staff_gym_id),
    ("v3_10_0_extend_fighter_descriptors", "3.10.0",
        _migrate_v3_10_0_extend_fighter_descriptors),
    ("v3_11_0_add_cache_tables", "3.11.0",
        _migrate_v3_11_0_add_cache_tables),
    ("v3_12_0_expand_memory_link_types", "3.12.0",
        _migrate_v3_12_0_expand_memory_link_types),
    ("v3_13_0_add_performance_indexes", "3.13.0",
        _migrate_v3_13_0_add_performance_indexes),
    ("v3_14_0_add_rival_ai_columns", "3.14.0",
        _migrate_v3_14_0_add_rival_ai_columns),
    ("v3_15_0_add_fighter_descriptor_short_columns", "3.15.0",
        _migrate_v3_15_0_add_fighter_descriptor_short_columns),
    ("v3_16_0_add_player_decisions_and_echoes", "3.16.0",
        _migrate_v3_16_0_add_player_decisions_and_echoes),
    ("v3_17_0_add_concessions_txn_type", "3.17.0",
        _migrate_v3_17_0_add_concessions_txn_type),
    ("v3_18_0_add_venue_type", "3.18.0",
        _migrate_v3_18_0_add_venue_type),
    ("v3_19_0_add_fighter_portrait_path", "3.19.0",
        _migrate_v3_19_0_add_fighter_portrait_path),
    ("v3_20_0_reseed_fighter_attributes", "3.20.0",
        _migrate_v3_20_0_reseed_fighter_attributes),
    ("v3_21_0_add_player_levers", "3.21.0",
        _migrate_v3_21_0_add_player_levers),
    ("v3_22_0_add_staff_market_columns", "3.22.0",
        _migrate_v3_22_0_add_staff_market_columns),
    ("v3_23_0_add_bankruptcy_rebuild_columns", "3.23.0",
        _migrate_v3_23_0_add_bankruptcy_rebuild_columns),
    ("v3_24_0_add_realization_column", "3.24.0",
        _migrate_v3_24_0_add_realization_column),
    ("v3_25_0_add_bidding_alerts", "3.25.0",
        _migrate_v3_25_0_add_bidding_alerts),
    ("v3_25_0_add_staff_regen_lineage", "3.25.0",
        _migrate_v3_25_0_add_staff_regen_lineage),
    ("v3_26_0_add_show_quality_adjustment_txn_type", "3.26.0",
        _migrate_v3_26_0_add_show_quality_adjustment_txn_type),
    ("v3_27_0_add_financial_state_column", "3.27.0",
        _migrate_v3_27_0_add_financial_state_column),
    ("v3_28_0_expand_memory_link_types_with_hw3_values", "3.28.0",
        _migrate_v3_28_0_expand_memory_link_types_with_hw3_values),
    ("v3_29_0_add_simulation_tick_health", "3.29.0",
        _migrate_v3_29_0_add_simulation_tick_health),
    ("v3_30_0_add_news_items_importance", "3.30.0",
        _migrate_v3_30_0_add_news_items_importance),
    ("v3_31_0_add_perf_indexes", "3.31.0",
        _migrate_v3_31_0_add_perf_indexes),
    ("v3_32_0_add_news_global_daily_cap_trigger", "3.32.0",
        _migrate_v3_32_0_add_news_global_daily_cap_trigger),
    ("v3_33_0_news_cap_importance_aware", "3.33.0",
        _migrate_v3_33_0_news_cap_importance_aware),
    ("v3_34_0_add_rival_ai_memory", "3.34.0",
        _migrate_v3_34_0_add_rival_ai_memory),
    ("v3_35_0_add_perf_indexes_2", "3.35.0",
        _migrate_v3_35_0_add_perf_indexes_2),
    ("v3_36_0_add_provenance_metadata", "3.36.0",
        _migrate_v3_36_0_add_provenance_metadata),
    ("v3_36_0_expand_memory_link_types_tier3", "3.36.0",
        _migrate_v3_36_0_expand_memory_link_types_tier3),
]


def _applied_migrations(conn):
    """Return the set of migration_name strings already recorded in
    schema_migrations for the given DB connection.
    """
    rows = conn.execute(
        "SELECT migration_name FROM schema_migrations"
    ).fetchall()
    return {r[0] for r in rows}


def _run_migrations(conn, target_version=None):
    """Apply all migrations not yet recorded in schema_migrations.

    Idempotent: a migration whose name is already in the table is
    skipped. After all migrations run, schema_meta.schema_version is
    updated to CODE_SCHEMA_VERSION (or target_version if provided).

    Args:
        conn: sqlite3.Connection (caller commits).
        target_version: optional — the version to set in schema_meta
            after migrations run. Defaults to CODE_SCHEMA_VERSION.
    """
    if target_version is None:
        target_version = CODE_SCHEMA_VERSION
    applied = _applied_migrations(conn)
    n_run = 0
    for name, version, fn in MIGRATIONS:
        if name in applied:
            continue
        print(f"  Applying migration: {name}")
        fn(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (?)",
            (name,),
        )
        n_run += 1
    if n_run == 0:
        print("  No new migrations to apply.")
    # Update schema_meta to the current code version. Use UPSERT
    # (ON CONFLICT DO UPDATE) instead of INSERT OR REPLACE so the
    # world_version + seed_version provenance columns (added v3.36.0)
    # are PRESERVED on a re-run. INSERT OR REPLACE would delete the
    # existing row and insert a fresh one with NULL provenance —
    # that would silently wipe the seed_version set by _build_fresh
    # or the world_version set by save_load.save_game.
    conn.execute(
        "INSERT INTO schema_meta (schema_name, schema_version) "
        "VALUES (?, ?) "
        "ON CONFLICT(schema_name) DO UPDATE SET "
        "schema_version=excluded.schema_version",
        ("cage_empire", target_version),
    )
    return n_run


def _build_fresh(conn):
    """Drop+rebuild path: executescript(SCHEMA_SQL) + record all
    migrations + insert the simulation_clock seed row.
    """
    conn.executescript(SCHEMA_SQL)
    # Record ALL migrations (the fresh build's SCHEMA_SQL includes
    # every table/column, so every migration is "applied" by
    # definition — we record them all to keep the audit trail
    # consistent with --migrate path).
    for name, _version, _fn in MIGRATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (?)",
            (name,),
        )
    # Seed the simulation clock (only on fresh — preserve on migrate).
    # HW2.3: use the formal GAME_START_DATE constant (default "2026-01-01")
    # instead of a hardcoded date — new games start from this sim date,
    # NOT from today's real date. Existing worlds keep their clock (the
    # --migrate path doesn't touch simulation_clock).
    from datetime import datetime as _dt
    _start_dt = _dt.strptime(GAME_START_DATE, "%Y-%m-%d")
    conn.execute(
        "INSERT OR IGNORE INTO simulation_clock "
        "(clock_id, current_date, current_day, current_week, current_month, current_year) "
        "VALUES (1, ?, 1, 1, ?, ?)",
        (GAME_START_DATE, _start_dt.month, _start_dt.year)
    )
    # Phase A (A4) — seed the 5 news sources. INSERT OR IGNORE so
    # this is idempotent (a re-run with the sources already present
    # is a no-op). The existing 'System Feed' source is created on
    # demand by app.write_news / _check_retirements / etc. — we
    # seed it here so the fresh DB has all 5 sources from the start
    # (otherwise the first news publish creates 'System Feed' before
    # 'CAGE Wire' exists, which is fine but messier). Frequency
    # drives the weighted-random source selection in news.py's
    # _get_random_news_source.
    conn.executemany(
        "INSERT OR IGNORE INTO news_sources "
        "(name, credibility, sensationalism, bias, regional_reach, "
        "reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            # Official inline news (app.write_news, retirement, etc.).
            # Neutral credibility, low sensationalism, official voice.
            ("System Feed", 70, 40, 50, 60, 80, 80),
            # The news engine's default rich-template source. Tabloid
            # flair — punches up headlines, lower credibility.
            ("CAGE Wire", 75, 60, 50, 70, 80, 90),
            # A4 — 4 new sources for variety. Each has a distinct
            # voice: tabloid (sensational), broadsheet (analytical),
            # aggregator (social-driven), opinion (pundit-driven).
            ("The Cage Wire", 30, 80, 60, 50, 50, 70),
            ("MMA Analytica", 90, 20, 30, 80, 95, 50),
            ("Social Sphere", 50, 60, 50, 70, 60, 60),
            ("The Pundit's Desk", 60, 50, 40, 60, 70, 40),
        ],
    )
    # v3.7.0 (Stage5-Final) — seed the 6 default player_settings.
    # Same INSERT OR IGNORE pattern as the news_sources seeding above
    # (idempotent — preserves any user-modified values on a re-run).
    # The migration function _migrate_v3_7_0_add_player_settings also
    # seeds these defaults (for the --migrate path on an existing
    # world DB); mirroring here ensures the fresh-build path has the
    # defaults from the very first run (the migration functions are
    # NOT called on the --fresh path per CONVENTIONS §16.4 — only
    # recorded in schema_migrations).
    conn.executemany(
        "INSERT OR IGNORE INTO player_settings "
        "(setting_key, setting_value) VALUES (?, ?)",
        [
            ("news_filter_topics",         "all"),
            ("news_filter_min_importance", "0"),
            ("news_volume",                "normal"),
            ("auto_save_frequency",        "30"),
            ("difficulty",                 "normal"),
            ("display_descriptors",        "true"),
            # FIX-Critical (Issue 5): event name format toggle.
            ("event_naming_style",         "mixed"),
        ],
    )
    conn.execute(
        # v3.36.0 (TIER3-MISSING §T3.3) — set seed_version on fresh
        # builds. UPSERT preserves the world_version column if a row
        # already exists (shouldn't happen on --fresh, but defensive).
        "INSERT INTO schema_meta (schema_name, schema_version, seed_version) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(schema_name) DO UPDATE SET "
        "schema_version=excluded.schema_version, "
        "seed_version=COALESCE(schema_meta.seed_version, excluded.seed_version)",
        ("cage_empire", CODE_SCHEMA_VERSION, "world_seed_v1"),
    )


def _migrate_existing(conn):
    """Migration path: run all un-applied migrations on the existing DB.
    Does NOT drop or recreate any table — preserves all data.
    """
    # Ensure schema_migrations table exists (very old DBs may predate it).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (\n"
        "    migration_name TEXT PRIMARY KEY,\n"
        "    applied_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
        ")"
    )
    # Ensure schema_meta exists too. v3.36.0 added the world_version
    # + seed_version provenance columns; the migration function
    # _migrate_v3_36_0_add_provenance_metadata handles adding them
    # to an existing schema_meta via ALTER TABLE. This CREATE TABLE
    # IF NOT EXISTS only fires for an old DB that predates
    # schema_meta entirely — it creates the table with the new
    # columns inline (matches SCHEMA_SQL) so the migration is a
    # no-op (the _has_column guard skips the ALTER).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (\n"
        "    schema_name    TEXT PRIMARY KEY,\n"
        "    schema_version TEXT NOT NULL,\n"
        "    world_version  TEXT,\n"
        "    seed_version   TEXT,\n"
        "    created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)\n"
        ")"
    )
    _run_migrations(conn)


def main(argv=None):
    """Entry point. Supports two modes:

      python src/build_db.py              # default = --fresh
      python src/build_db.py --fresh      # drop + rebuild (tests, dev)
      python src/build_db.py --migrate    # apply migrations to existing DB

    --fresh refuses to run if the on-disk schema is NEWER than
    CODE_SCHEMA_VERSION (the Task 5 version-check gate). --migrate
    has no such gate — it can migrate a same-version or older DB.
    --migrate on a non-existent DB falls back to --fresh (so first
    run after fresh clone just works).
    """
    import argparse
    parser = argparse.ArgumentParser(
        description="Build or migrate the CAGE EMPIRE database."
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Drop + rebuild the DB from SCHEMA_SQL (default). Destroys all data.",
    )
    parser.add_argument(
        "--migrate", action="store_true",
        help="Apply pending migrations to the existing DB. Preserves all data.",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Path to the DB file (overrides CAGE_EMPIRE_DB_PATH env var "
             "and the default data/cage_empire.db).",
    )
    args = parser.parse_args(argv)

    # Override DB_PATH if --db-path is specified
    global DB_PATH
    if args.db_path:
        DB_PATH = Path(args.db_path)

    # Default mode: --fresh. If both flags, --fresh wins (defensive).
    if args.migrate and not args.fresh:
        mode = "migrate"
    else:
        mode = "fresh"

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- version-check gate (only for --fresh) -----------------
    # See docs/CONVENTIONS.md §1.4 + §16. Prevents an older
    # build_db.py from silently clobbering a newer schema.
    on_disk = _read_on_disk_schema_version(DB_PATH)
    if mode == "fresh":
        if on_disk is not None:
            cmp = _compare_versions(on_disk, CODE_SCHEMA_VERSION)
            if cmp > 0:
                raise RuntimeError(
                    f"Refusing to --fresh: on-disk schema version {on_disk} is newer "
                    f"than code version {CODE_SCHEMA_VERSION}. This would silently "
                    f"destroy schema work. Either:\n"
                    f"  (a) upgrade build_db.py to support the newer schema, or\n"
                    f"  (b) use --migrate to apply pending migrations instead, or\n"
                    f"  (c) delete {DB_PATH} manually if you really want to start fresh."
                )
            elif cmp < 0:
                print(f"Rebuilding schema: {on_disk} -> {CODE_SCHEMA_VERSION}.")
            else:
                print(f"Rebuilding same schema version {CODE_SCHEMA_VERSION}.")

        # ---- WORLD DB PROTECTION GUARD (Phase 1.5) -------------
        # Prevents --fresh from destroying the world DB (4000+
        # fighters, 80000+ fight_history rows, 60 HoF legends).
        # The world DB is the FOUNDATION of the game — re-seeding
        # takes 10 seconds but destroys any save-game progress and
        # any fighter development the player has done.
        #
        # Tests that need a fresh DB must set CAGE_EMPIRE_ALLOW_FRESH=1
        # in their environment. run.sh test mode sets this automatically.
        # Individual test runs: CAGE_EMPIRE_ALLOW_FRESH=1 python3 scripts/test_foo.py
        #
        # The threshold is 100 fighters — a minimal seed has 5, the
        # world has 4000+. This catches accidental --fresh on the
        # world DB while allowing test DBs (which start empty).
        import os
        if DB_PATH.exists() and not os.environ.get("CAGE_EMPIRE_ALLOW_FRESH"):
            try:
                _guard_conn = sqlite3.connect(DB_PATH)
                _guard_fighters = _guard_conn.execute(
                    "SELECT COUNT(*) FROM fighters"
                ).fetchone()[0]
                _guard_conn.close()
            except Exception:
                _guard_fighters = 0
            if _guard_fighters > 100:
                raise RuntimeError(
                    f"REFUSING to --fresh: {DB_PATH} has {_guard_fighters} "
                    f"fighters — this is the WORLD DB, not a test DB.\n"
                    f"--fresh would DESTROY the world (4000+ fighters, "
                    f"80000+ fight history rows, 60 HoF legends, all "
                    f"player progress).\n\n"
                    f"To rebuild the world intentionally: ./run.sh build-world\n"
                    f"To run tests (which need fresh DBs): ./run.sh test\n"
                    f"  (run.sh test sets CAGE_EMPIRE_ALLOW_FRESH=1 automatically)\n"
                    f"To override manually: CAGE_EMPIRE_ALLOW_FRESH=1 python3 src/build_db.py --fresh\n\n"
                    f"To apply schema changes WITHOUT destroying data: "
                    f"python3 src/build_db.py --migrate"
                )
        # ---- END WORLD DB PROTECTION GUARD ----------------------

        if DB_PATH.exists():
            DB_PATH.unlink()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            _build_fresh(conn)
            conn.commit()
        print(f"Rebuilt database at {DB_PATH}")
        print(f"Schema version: {CODE_SCHEMA_VERSION}")
    else:  # mode == "migrate"
        if not DB_PATH.exists():
            # First-run fallback: no DB exists, do a fresh build.
            print(f"No DB at {DB_PATH} — falling back to --fresh.")
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                _build_fresh(conn)
                conn.commit()
            print(f"Rebuilt database at {DB_PATH}")
            print(f"Schema version: {CODE_SCHEMA_VERSION}")
            return
        if on_disk is None:
            print(f"Existing DB at {DB_PATH} has no schema_meta — "
                  f"initializing as v{CODE_SCHEMA_VERSION}.")
        else:
            cmp = _compare_versions(on_disk, CODE_SCHEMA_VERSION)
            if cmp > 0:
                print(f"WARNING: on-disk schema {on_disk} is NEWER than "
                      f"code {CODE_SCHEMA_VERSION}. No migrations will run "
                      f"(upgrade build_db.py to support the newer schema).")
                return
            elif cmp == 0:
                print(f"DB already at {CODE_SCHEMA_VERSION} — checking for "
                      f"any unrecorded migrations.")
            else:
                print(f"Migrating schema: {on_disk} -> {CODE_SCHEMA_VERSION}.")
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            _migrate_existing(conn)
            conn.commit()
        print(f"Migrated database at {DB_PATH}")
        print(f"Schema version: {CODE_SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
