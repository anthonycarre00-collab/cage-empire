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
CODE_SCHEMA_VERSION = "2.5.0"


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
    name TEXT NOT NULL UNIQUE,
    style_preferences TEXT,
    fan_preferences TEXT,
    market_growth INTEGER NOT NULL DEFAULT 50 CHECK (market_growth BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS weight_classes (
    weight_class_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    min_weight_kg REAL,
    max_weight_kg REAL,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
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
    UNIQUE (name_type, name_value)
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
"""

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- version-check gate (Task ID 5) ---------------------------
    # See docs/CONVENTIONS.md §1.4. Prevents an older build_db.py
    # from silently clobbering a newer schema. This is the gate that
    # closes the 37 -> 24 table drift that already happened twice.
    # The check happens BEFORE the DB_PATH.unlink() call so that
    # refusing does not destroy the on-disk schema.
    on_disk = _read_on_disk_schema_version(DB_PATH)
    if on_disk is not None:
        cmp = _compare_versions(on_disk, CODE_SCHEMA_VERSION)
        if cmp > 0:
            raise RuntimeError(
                f"Refusing to rebuild: on-disk schema version {on_disk} is newer "
                f"than code version {CODE_SCHEMA_VERSION}. This would silently "
                f"destroy schema work. Either:\n"
                f"  (a) upgrade build_db.py to support the newer schema, or\n"
                f"  (b) delete {DB_PATH} manually if you really want to start fresh."
            )
        elif cmp < 0:
            print(f"Upgrading schema: {on_disk} -> {CODE_SCHEMA_VERSION} (rebuilding).")
        else:
            print(f"Rebuilding same schema version {CODE_SCHEMA_VERSION}.")
    # ---- end version-check gate -----------------------------------

    if DB_PATH.exists():
        DB_PATH.unlink()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL)
        # Record the schema version + migration (see docs/CONVENTIONS.md §1).
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (schema_name, schema_version) VALUES (?, ?)",
            ("cage_empire", CODE_SCHEMA_VERSION),
        )
        # Record ALL migrations that this build_db.py knows about —
        # one INSERT per migration. Per CONVENTIONS §1.4, the
        # schema_migrations table is the complete history of named
        # migrations applied to this DB; if a migration is dropped
        # from this list, a future reader can't tell whether the
        # migration was applied (the data is still there, but the
        # audit row is missing). Keep this list in version order.
        for migration_name in (
            "v2_2_0_add_fighter_depth",
            "v2_3_0_add_beat_engine_depth",
            "v2_4_0_add_injuries",
            "v2_5_0_add_training_camps",
        ):
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (?)",
                (migration_name,),
            )
        conn.execute("INSERT INTO simulation_clock (clock_id, current_date, current_day, current_week, current_month, current_year) VALUES (1, '2026-07-20', 1, 1, 7, 2026)")
        conn.commit()
    print(f"Rebuilt database at {DB_PATH}")
    print(f"Schema version: {CODE_SCHEMA_VERSION}")

if __name__ == "__main__":
    main()
