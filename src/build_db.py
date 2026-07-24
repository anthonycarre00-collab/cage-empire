from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "cage_empire.db"

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
CODE_SCHEMA_VERSION = "3.7.0"


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
    link_type         TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor')),
    link_strength     INTEGER NOT NULL DEFAULT 50 CHECK (link_strength BETWEEN 0 AND 100),
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_id, linked_fighter_id, link_type)
);

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
        'sponsorship', 'bonus_payment'
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
            "    link_type TEXT NOT NULL CHECK (link_type IN ('style_echo', 'gym_heir', 'regional_rival', 'successor')),\n"
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
    re-run preserves any user-modified values).
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
    defaults = [
        ("news_filter_topics",         "all"),
        ("news_filter_min_importance", "0"),
        ("news_volume",                "normal"),
        ("auto_save_frequency",        "30"),
        ("difficulty",                 "normal"),
        ("display_descriptors",        "true"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO player_settings "
        "(setting_key, setting_value) VALUES (?, ?)",
        defaults,
    )


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
    # Update schema_meta to the current code version.
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (schema_name, schema_version) VALUES (?, ?)",
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
    conn.execute(
        "INSERT OR IGNORE INTO simulation_clock "
        "(clock_id, current_date, current_day, current_week, current_month, current_year) "
        "VALUES (1, '2026-07-20', 1, 1, 7, 2026)"
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
        ],
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (schema_name, schema_version) "
        "VALUES (?, ?)",
        ("cage_empire", CODE_SCHEMA_VERSION),
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
    # Ensure schema_meta exists too.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (\n"
        "    schema_name    TEXT PRIMARY KEY,\n"
        "    schema_version TEXT NOT NULL,\n"
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
    args = parser.parse_args(argv)

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
