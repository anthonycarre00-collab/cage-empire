import sqlite3
import json
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call _vacate_title_on_retirement and
# generate_fighter from app.py. app.py imports tkinter, but importing
# the module itself does NOT require a display (only tk.Tk() does), so
# this is safe in headless contexts. There is no circular-import risk
# because app.py does NOT import tick_processor.
#
# v2.5.0 (Task 16): also import the camp-focus attribute map and the
# fighter attribute whitelist from app.py — they're maintained there
# (next to the camp writer _create_training_camp and the camp reader
# _get_camp_fatigue_for_event) per the "table ships with code" rule
# (CONVENTIONS §5.3). tick_processor._check_training_camps reads
# _CAMP_FOCUS_ATTRS to know which attributes each camp_focus upgrades
# on completion, and reads _FIGHTER_ATTR_COLUMNS as the SQL-injection
# safety whitelist before string-formatting attribute names into the
# UPDATE statement.
sys.path.insert(0, str(BASE_DIR))
from app import (  # noqa: E402
    _vacate_title_on_retirement,
    generate_fighter,
    _CAMP_FOCUS_ATTRS,
    _FIGHTER_ATTR_COLUMNS,
    fighter_name,
)


# ----------------------------------------------------------------
# Injury recovery checking (Task ID 15).
#
# Fighters get injured (Task 15's _maybe_create_injury in app.py,
# called at the end of resolve_next_fight). Each injury has a
# projected_return_date. On every tick, this helper checks all
# active injuries: if current_date >= projected_return_date, the
# injury is marked as recovered (is_active=0, actual_return_date=
# current_date), the temporary career_health penalty (severity * 2)
# is restored, and a clearance news item is written.
#
# The permanent long_term_damage and any permanent attribute
# reduction are NOT restored — they represent lasting consequences.
# This matches the Soul document's mandate: a torn ACL at age 32
# should haunt the fighter's career even after they're cleared to
# return.
#
# This function runs on every tick (called from run_tick AFTER
# _check_contract_expiry, so the order is: clock advance →
# _check_retirements → _check_contract_expiry → _check_injury_
# recovery → commit). It does NOT commit — the caller commits.
# ----------------------------------------------------------------

def _check_injury_recovery(conn, current_date):
    """Advance recovery on active injuries that have reached their projected return date.

    Rules (Task ID 15):
      - For each injury with is_active=1 AND projected_return_date <=
        current_date:
        (a) Set is_active = 0, actual_return_date = current_date,
            updated_at = CURRENT_TIMESTAMP.
        (b) Restore fighter_career.career_health by severity * 2
            (the temporary penalty that was applied at injury
            creation time). The MIN(100, ...) cap keeps career_health
            within the 0-100 range (the column has no CHECK but values
            >100 would be nonsensical — a fighter at peak health
            before the injury shouldn't end up over 100 after
            recovery).
        (c) Write a clearance news item: "{Fighter} cleared to
            return from {injury_type}" with topic='injury', fighter_id
            set, published_at=current_date.
      - Returns the list of (injury_id, fighter_id) tuples that were
        recovered on this tick.

    The permanent long_term_damage (stored on the injuries row) and
    any permanent attribute reduction (applied to fighter_attributes
    at injury creation) are NOT restored — they represent lasting
    consequences of severe injuries.

    Args:
        conn: sqlite3 connection (caller commits).
        current_date: ISO date string 'YYYY-MM-DD' (the current sim date).

    Returns:
        List of (injury_id, fighter_id) tuples for injuries that were
        recovered on this tick.
    """
    # Fetch active injuries whose projected return date has arrived.
    # We need fighter_id + injury_type + severity for the news item
    # and the career_health restoration.
    rows = conn.execute(
        "SELECT injury_id, fighter_id, injury_type, severity "
        "FROM injuries WHERE is_active = 1 AND projected_return_date <= ?",
        (current_date,),
    ).fetchall()

    if not rows:
        return []

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news, _check_retirements, _check_contract_expiry).
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    recovered = []
    for injury_id, fighter_id, injury_type, severity in rows:
        # (a) Mark the injury as recovered.
        conn.execute(
            "UPDATE injuries SET is_active = 0, actual_return_date = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE injury_id = ?",
            (current_date, injury_id),
        )

        # (b) Restore the temporary career_health penalty (severity * 2).
        # The permanent long_term_damage penalty is NOT restored.
        # MIN(100, ...) keeps career_health at or below the natural max.
        conn.execute(
            "UPDATE fighter_career SET career_health = MIN(100, career_health + ?), "
            "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
            (severity * 2, fighter_id),
        )

        # (c) Write the clearance news item. The fighter's name is
        # fetched fresh (defensive — if the fighter was somehow deleted
        # between injury creation and recovery, the news item still
        # gets written with a placeholder name).
        name_row = conn.execute(
            "SELECT first_name || ' ' || last_name FROM fighters "
            "WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        fighter_name_str = name_row[0] if name_row else f"Fighter {fighter_id}"
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                src_id,
                f"{fighter_name_str} cleared to return from {injury_type}",
                f"{fighter_name_str} has been medically cleared to return "
                f"from {injury_type} and is eligible to compete again.",
                "positive",
                "injury",
                fighter_id,
                current_date,
            ),
        )

        recovered.append((injury_id, fighter_id))

        # v2.8.0 (Task 19): update descriptor snapshot — career_health
        # changed (restored by severity*2). Lazy-import to avoid circular dep.
        from app import update_fighter_descriptor_snapshot
        update_fighter_descriptor_snapshot(conn, fighter_id)

    return recovered


# ----------------------------------------------------------------
# Training camps (Task ID 16).
#
# `_check_training_camps` runs on every tick (called from run_tick
# AFTER _check_injury_recovery so the order is: clock advance →
# _check_retirements → _check_contract_expiry →
# _check_injury_recovery → _check_training_camps → commit).
#
# For each active, uncompleted camp whose [start_date, end_date]
# window contains current_date:
#   - If current_date == end_date: COMPLETE the camp. Pick 2-4
#     attributes from the camp_focus pool, apply +1 to +3 base gain
#     scaled by gym spec / coachability / fatigue factor (capped at
#     fighter_career.potential), write attribute_changes JSON +
#     camp_result_summary + a completion news item, set is_active=0
#     is_completed=1.
#   - Else (start_date < current_date < end_date): PROGRESS the camp.
#     Fatigue +2-5 (reduced by cardio + fatigue_tolerance). Morale
#     ±0-2 (dampened by coachability, biased by gym culture_tone).
#     Injury risk +2-5 (increased by injury_proneness, reduced by
#     gym medical_support). If injury_risk > 80: create a training
#     injury via the Task 15 injuries table (training-injury pool),
#     reduce career_health, mark the camp inactive + completed.
#
# The function does NOT commit — the conn.commit() in run_tick
# covers both the clock UPDATE and any camp side effects (training_
# camps UPDATE, fighter_attributes UPDATE, fighter_career UPDATE,
# injuries INSERT, news_items INSERT). Prints a one-line log per
# tick if any camps progressed or completed.
#
# Reader-of-camp-data rule (CONVENTIONS §5.3): the camp table ships
# with TWO readers — `_get_camp_fatigue_for_event` in app.py (read
# by resolve_next_fight to apply the brief's "Fatigue > 50 = reduced
# starting gas" rule) AND this function (reads the camp to progress
# and complete it). Both readers are required for the table to be
# considered "shipped with code".
# ----------------------------------------------------------------

# The training-injury pool — distinct from the fight-injury pool in
# app.py because training injuries have a different character (overuse,
# sparring accidents, weight-cut complications) than in-fight injuries
# (concussions from KO, joint damage from submissions, doctor-
# stoppage facial damage). Picked at random when injury_risk > 80.
# Each entry is (injury_type, body_area, sev_min, sev_max). Severity
# is rolled in [sev_min, sev_max] then adjusted by durability (see
# the same -2..+2 adjustment that _maybe_create_injury uses).
_TRAINING_INJURY_POOL = (
    ("torn ACL",            "knee",     7, 10),  # catastrophic — 3-5 month layoff
    ("hamstring strain",    "hip",      3,  6),  # 4-9 weeks (hip flexor/hamstring)
    ("shoulder labrum tear","shoulder", 6,  9),  # 2-4 months
    ("rib sprain",          "ribs",     2,  5),  # 2-6 weeks
    ("training concussion", "head",     4,  7),  # 6-10 weeks (extra cautious)
    ("wrist sprain",        "wrist",    2,  4),  # 2-5 weeks
    ("ankle sprain",        "ankle",    2,  4),  # 2-5 weeks
)


def _check_training_camps(conn, current_date):
    """Progress and complete active training camps on a tick.

    Args:
        conn: sqlite3 connection (caller commits — same pattern as
            _check_injury_recovery, _check_retirements,
            _check_contract_expiry).
        current_date: ISO date string 'YYYY-MM-DD' (the current sim
            date after this tick's clock advance).

    Returns:
        List of (training_camp_id, fighter_id, action) tuples for
        camps that progressed or completed on this tick. action is
        one of 'progressed', 'completed', 'injured' (a training
        injury was created and the camp was force-completed).
    """
    # Fetch active, uncompleted camps whose window contains today.
    # Order by training_camp_id for deterministic processing.
    rows = conn.execute(
        "SELECT training_camp_id, fighter_id, gym_id, event_id, "
        "fight_id, start_date, end_date, camp_focus, camp_morale, "
        "camp_fatigue, camp_injury_risk "
        "FROM training_camps "
        "WHERE is_active = 1 AND is_completed = 0 "
        "AND start_date <= ? AND end_date >= ? "
        "ORDER BY training_camp_id",
        (current_date, current_date),
    ).fetchall()

    if not rows:
        return []

    # Get or create the "System Feed" news source — same pattern as
    # every other tick-side helper that writes news items.
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    results = []
    for (camp_id, fighter_id, gym_id, event_id, fight_id,
         start_date, end_date, camp_focus, morale, fatigue,
         injury_risk) in rows:
        # Load the fighter's stats once per camp — pulled fresh each
        # tick (the fighter's cardio / fatigue_tolerance / etc. may
        # have changed since the camp started; pull the current
        # values for accurate progression).
        stats_row = conn.execute(
            "SELECT fa.cardio, fa.recovery_rate, fa.durability, "
            "fp.fatigue_tolerance, fp.coachability, fp.discipline, "
            "fc.potential, fc.career_health, "
            "f.injury_proneness "
            "FROM fighters f "
            "JOIN fighter_attributes fa ON fa.fighter_id = f.fighter_id "
            "JOIN fighter_personality fp ON fp.fighter_id = f.fighter_id "
            "JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
            "WHERE f.fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        if stats_row is None:
            # Defensive — the fighter was deleted between camp
            # creation and progression. Mark the camp inactive so we
            # don't keep retrying.
            conn.execute(
                "UPDATE training_camps SET is_active = 0, "
                "camp_result_summary = 'fighter not found', "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE training_camp_id = ?",
                (camp_id,),
            )
            results.append((camp_id, fighter_id, "skipped"))
            continue
        (cardio, recovery_rate, durability, fatigue_tol,
         coachability, discipline, potential, career_health,
         injury_proneness) = stats_row

        # Load the gym's spec columns — defensive against NULL gym_id
        # (shouldn't happen since _create_training_camp skips fighters
        # with NULL gym_id, but the FK is ON DELETE SET NULL so a
        # gym could be deleted out from under an active camp).
        gym_row = (conn.execute(
            "SELECT facility_quality, medical_support, "
            "sparring_depth, development_focus, culture_tone "
            "FROM gyms WHERE gym_id = ?",
            (gym_id,),
        ).fetchone() if gym_id is not None else None)
        if gym_row is None:
            # Gym was deleted — fall back to neutral spec values.
            facility_quality, medical_support, sparring_depth = 50, 50, 50
            development_focus, culture_tone = 50, "balanced"
        else:
            (facility_quality, medical_support, sparring_depth,
             development_focus, culture_tone) = gym_row

        # ---- Branch: completion vs progression ----
        if current_date == end_date:
            action = _complete_training_camp(
                conn, camp_id, fighter_id, camp_focus, fatigue, morale,
                cardio, fatigue_tol, coachability, discipline,
                potential, facility_quality, development_focus,
                culture_tone, src_id, current_date,
            )
            results.append((camp_id, fighter_id, action))
        else:
            action = _progress_training_camp(
                conn, camp_id, fighter_id, fatigue, morale, injury_risk,
                cardio, fatigue_tol, coachability, injury_proneness,
                medical_support, culture_tone, durability,
                recovery_rate, event_id, fight_id, src_id, current_date,
            )
            results.append((camp_id, fighter_id, action))

    return results


def _progress_training_camp(conn, camp_id, fighter_id, fatigue, morale,
                            injury_risk, cardio, fatigue_tol, coachability,
                            injury_proneness, medical_support,
                            culture_tone, durability, recovery_rate,
                            event_id, fight_id, src_id, current_date):
    """Progress an in-window camp by one tick: accrue fatigue, fluctuate
    morale, accumulate injury risk, maybe spawn a training injury.

    Returns the action string: 'progressed' or 'injured' (if a training
    injury was created and the camp force-completed).
    """
    # Fatigue: +2-5 per tick. Reduced by cardio (50 = no reduction,
    # 100 = -2) and fatigue_tolerance (50 = no reduction, 100 = -2).
    # A cardio monster with elite fatigue tolerance might gain only
    # +0-1 fatigue per tick; a cardio-deficient fighter with low
    # tolerance can hit 100 fatigue inside a 14-day camp.
    fatigue_gain = random.randint(2, 5)
    fatigue_gain -= max(0, int((cardio - 50) / 25))      # 0..2 reduction
    fatigue_gain -= max(0, int((fatigue_tol - 50) / 25)) # 0..2 reduction
    new_fatigue = min(100, fatigue + max(0, fatigue_gain))

    # Morale: ±0-2 per tick. Dampened by coachability (high coachability
    # = stable morale; low = volatile). Biased by gym culture_tone:
    #   disciplined → +1 bias (structured camp, clear expectations)
    #   loose       → -1 bias (chaotic camp, lots of distractions)
    #   predator    → +1 bias (high-intensity, us-vs-them mentality)
    #   balanced    → 0 bias (neutral)
    morale_delta = random.randint(-2, 2)
    # Dampen the delta by coachability (50 = no dampening, 100 = halved).
    morale_delta = int(morale_delta * (1 - max(0, coachability - 50) / 100))
    culture_bias = {
        "disciplined": 1,
        "loose": -1,
        "predator": 1,
        "balanced": 0,
    }.get(culture_tone, 0)
    new_morale = max(0, min(100, morale + morale_delta + culture_bias))

    # Injury risk: +2-5 per tick. Increased by injury_proneness (50 =
    # no change, 100 = +2), reduced by gym medical_support (50 = no
    # reduction, 100 = -2). A fighter with high injury_proneness at a
    # gym with weak medical support can hit 80 risk inside a 14-day
    # camp; the same fighter at an elite gym stays under 50.
    risk_gain = random.randint(2, 5)
    risk_gain += max(0, int((injury_proneness - 50) / 25))  # 0..2 increase
    risk_gain -= max(0, int((medical_support - 50) / 25))   # 0..2 reduction
    new_risk = min(100, injury_risk + max(0, risk_gain))

    # If risk crosses 80, spawn a training injury and force-complete
    # the camp (the fighter can't continue training). This is the
    # "training-camp injury" story — the prospect tears his ACL two
    # weeks out from his debut, the title challenger suffers a
    # concussion in sparring, etc.
    if new_risk > 80:
        # Pick a training injury from the pool.
        injury_type, body_area, sev_min, sev_max = random.choice(
            _TRAINING_INJURY_POOL
        )
        # Severity in [sev_min, sev_max], adjusted by durability
        # (-2 at dur=100, +2 at dur=0). Same adjustment as
        # _maybe_create_injury in app.py.
        severity = random.randint(sev_min, sev_max)
        severity += int((50 - durability) / 25)  # -2..+2
        severity = max(1, min(10, severity))
        # Recovery timeline: severity * 14 days, minus a small
        # recovery_rate bonus (same formula as fight injuries).
        from datetime import datetime as _dt, timedelta as _td
        start_dt = _dt.strptime(current_date, "%Y-%m-%d")
        days_out = max(7, severity * 14 - int(recovery_rate * 0.1))
        projected_return = (start_dt + _td(days=days_out)).strftime("%Y-%m-%d")
        # 30% chance of long-term damage on severity 8+ (matches
        # _maybe_create_injury's rule).
        long_term = 0
        if severity >= 8 and random.random() < 0.30:
            long_term = random.randint(2, 5)
        # Insert the injuries row. injury_source = 'training' (the
        # column doesn't exist in the schema yet — Task 15 used a
        # body_area CHECK constraint that allows any string, so the
        # news body will clarify "suffered in training camp").
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, body_area, "
            "severity, start_date, projected_return_date, "
            "long_term_damage, is_active, fight_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (fighter_id, injury_type, body_area, severity,
             current_date, projected_return, long_term, fight_id, event_id),
        )
        # Reduce career_health by severity * 2 (temporary — restored
        # on recovery) + long_term (permanent). Same rule as fight
        # injuries.
        health_penalty = severity * 2 + long_term
        conn.execute(
            "UPDATE fighter_career SET career_health = MAX(0, "
            "career_health - ?), updated_at = CURRENT_TIMESTAMP "
            "WHERE fighter_id = ?",
            (health_penalty, fighter_id),
        )
        # Write the training-injury news item.
        name_row = conn.execute(
            "SELECT first_name || ' ' || last_name FROM fighters "
            "WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        fighter_name_str = (name_row[0] if name_row
                            else f"Fighter {fighter_id}")
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, fight_id, event_id, "
            "published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"{fighter_name_str} suffers {injury_type} in training",
             f"{fighter_name_str} suffered a {injury_type} (severity "
             f"{severity}/10) during training camp and is projected "
             f"to return on {projected_return}. The camp has been "
             f"suspended.",
             "negative", "injury", fighter_id, fight_id, event_id,
             current_date),
        )
        # Force-complete the camp as 'injured' (no attribute gains).
        conn.execute(
            "UPDATE training_camps SET camp_fatigue = ?, camp_morale = ?, "
            "camp_injury_risk = ?, is_active = 0, is_completed = 1, "
            "camp_result_summary = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE training_camp_id = ?",
            (new_fatigue, new_morale, new_risk,
             f"suspended due to training injury: {injury_type} "
             f"(severity {severity}/10)",
             camp_id),
        )
        # v2.8.0 (Task 19): update descriptor snapshot — career_health
        # reduced by the training injury. Lazy-import to avoid circular dep.
        from app import update_fighter_descriptor_snapshot
        update_fighter_descriptor_snapshot(conn, fighter_id)
        # Phase A (Task A1): publish CAMP_INJURY event so the morale
        # system can apply its -5 morale penalty for training setbacks
        # (CONVENTIONS §15.4 — event-bus-driven, no inline morale
        # write here). The event carries the fighter_id + injury_type
        # + severity so future subscribers (news engine, social media)
        # can react to training injuries too.
        try:
            from event_bus import get_bus, Events
            bus = get_bus()
            bus.publish(conn, {
                'type': Events.CAMP_INJURY,
                'training_camp_id': camp_id,
                'fighter_id': fighter_id,
                'injury_type': injury_type,
                'severity': severity,
                'event_id': event_id,
                'fight_id': fight_id,
                'current_date': current_date,
            })
        except ImportError:
            pass  # event_bus not available (defensive)
        return "injured"

    # Normal progression — update the camp's tracking columns and
    # leave is_active=1, is_completed=0.
    conn.execute(
        "UPDATE training_camps SET camp_fatigue = ?, camp_morale = ?, "
        "camp_injury_risk = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE training_camp_id = ?",
        (new_fatigue, new_morale, new_risk, camp_id),
    )
    return "progressed"


def _complete_training_camp(conn, camp_id, fighter_id, camp_focus,
                            fatigue, morale, cardio, fatigue_tol,
                            coachability, discipline, potential,
                            facility_quality, development_focus,
                            culture_tone, src_id, current_date):
    """Complete a camp: pick attributes to upgrade, apply scaled gains,
    write attribute_changes JSON + summary + news item, mark complete.

    Returns the action string: 'completed'.
    """
    # The attribute pool for this camp_focus. Imported from app.py
    # (the source of truth for "which attributes does each camp_focus
    # upgrade" — see _CAMP_FOCUS_ATTRS).
    attr_pool = _CAMP_FOCUS_ATTRS.get(camp_focus, _CAMP_FOCUS_ATTRS["general"])

    # Number of attributes to upgrade: 2 + (coach_ability +
    # development_focus) / 100, clamped to [2, 4]. The brief's
    # "coach_ability" is the gym's coach-quality proxy — we use the
    # fighter's own coachability (their ability to absorb coaching)
    # combined with the gym's development_focus (how good the gym is
    # at developing talent).
    n_attrs = 2 + int((coachability + development_focus) / 100)
    n_attrs = max(2, min(4, n_attrs))

    # Pick n_attrs distinct attributes from the pool (random.sample
    # without replacement — no attribute gets upgraded twice in one
    # camp).
    n_attrs = min(n_attrs, len(attr_pool))
    chosen_attrs = random.sample(attr_pool, n_attrs)

    # Multipliers:
    #   gym_spec_mult: 0.5-1.5 from (facility_quality + development_
    #     focus) / 200 + 0.5. A bare-bones gym (50/50) = 1.0; an
    #     elite gym (100/100) = 1.5; a shoebox gym (0/0) = 0.5.
    #   coach_mult: 0.5-1.5 from coachability / 100. A coachable
    #     fighter (100) gets +50% gains; an uncoachable one (0) gets
    #     -50%.
    #   fatigue_factor: 0.5-1.0 from 1 - (camp_fatigue - fatigue_
    #     tolerance) / 100. A fighter with low fatigue (0) and
    #     decent tolerance (50+) gets full 1.0 gains. A fighter who
    #     is gassed (100 fatigue) with low tolerance (0) gets 0.5
    #     gains — they're too tired to absorb the work.
    gym_spec_mult = 0.5 + (facility_quality + development_focus) / 200.0
    coach_mult = 0.5 + coachability / 100.0
    fatigue_factor = 1.0 - max(0, fatigue - fatigue_tol) / 100.0 * 0.5
    fatigue_factor = max(0.5, min(1.0, fatigue_factor))

    # v2.9.0 (Task 18): EFFECTIVE CEILING — potential is NOT guaranteed
    # success. Most fighters never reach their true potential because:
    #   - Age: fighters past prime (28+) grow slower; past 32, almost
    #     no growth; past 36, decline.
    #   - Injury history: career_health < 80 reduces growth; < 50 =
    #     almost no growth.
    #   - Personality: low discipline/coachability reduces the ceiling.
    #   - Diminishing returns: as attributes approach potential, growth
    #     rate decreases (the last 10 points are 2x harder than the
    #     first 10).
    #
    # effective_ceiling = potential * age_factor * health_factor *
    #   personality_factor
    #
    # A 20-year-old with potential=90, perfect health, high discipline
    # (90) + coachability (90): ceiling = 90 * 1.0 * 1.0 * 0.9 = 81.
    # Can reach ~81, NOT 90.
    #
    # A 32-year-old with potential=90, health=70, avg discipline (50):
    # ceiling = 90 * 0.85 * 0.90 * 0.5 = 34. Already past their growth
    # window — they're declining, not growing.
    #
    # This ensures "potential ≠ guaranteed success" per the user's
    # directive. Scouting reports (Task 18) estimate potential, but
    # the player must also consider age, health, personality, and gym
    # quality when deciding whether to invest in a prospect.

    # Load fighter age + career_health for the effective ceiling calc.
    f_meta = conn.execute(
        "SELECT f.date_of_birth, fc.career_health "
        "FROM fighters f JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    fighter_age = 25  # default if DOB missing
    career_health = 100  # default
    if f_meta:
        dob_str, ch = f_meta
        if dob_str:
            try:
                fighter_age = 2026 - int(dob_str[:4])
            except (ValueError, TypeError):
                pass
        career_health = ch if ch is not None else 100

    # Age factor: 1.0 at 18-27, declining after
    if fighter_age <= 27:
        age_factor = 1.0
    elif fighter_age <= 30:
        age_factor = 0.95
    elif fighter_age <= 33:
        age_factor = 0.80
    elif fighter_age <= 36:
        age_factor = 0.60
    else:
        age_factor = 0.35  # veterans barely grow

    # Health factor: 1.0 at 90+, declining
    if career_health >= 90:
        health_factor = 1.0
    elif career_health >= 70:
        health_factor = 0.90
    elif career_health >= 50:
        health_factor = 0.70
    elif career_health >= 30:
        health_factor = 0.40
    else:
        health_factor = 0.15  # broken down fighters can't grow

    # Personality factor: average of discipline + coachability / 200
    # Range: 0.0 (both at 0) to 1.0 (both at 100). Most fighters ~0.5.
    personality_factor = (discipline + coachability) / 200.0

    effective_ceiling = int(potential * age_factor * health_factor * personality_factor)
    # Floor at 10 — even the most degraded fighter can maintain some baseline
    effective_ceiling = max(10, effective_ceiling)

    attribute_changes = {}
    for attr_name in chosen_attrs:
        # Defensive — never string-format an unknown attribute name
        # into the UPDATE statement (CONVENTIONS §6 — SQL safety).
        if attr_name not in _FIGHTER_ATTR_COLUMNS:
            continue
        cur_val = conn.execute(
            f"SELECT {attr_name} FROM fighter_attributes WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()[0]

        # v2.9.0: Diminishing returns — as cur_val approaches
        # effective_ceiling, growth rate halves. The last 10 points
        # are 2x harder than the first 10. This makes plateauing
        # natural — fighters don't linearly grind to their ceiling.
        if effective_ceiling > cur_val:
            progress = (cur_val - 40) / max(1, effective_ceiling - 40)
            progress = max(0.0, min(1.0, progress))
            dim_factor = 1.0 - progress * 0.5  # 1.0 at base, 0.5 at ceiling
        else:
            dim_factor = 0.0  # already at or above ceiling — no growth

        # Base gain +1 to +3.
        base = random.randint(1, 3)
        # Final gain = round(base * gym_mult * coach_mult * fatigue_
        # factor * dim_factor), min 0 (if dim_factor=0, no gain —
        # fighter has plateaued). If dim_factor > 0, min 1.
        gain = int(round(base * gym_spec_mult * coach_mult
                         * fatigue_factor * dim_factor))
        if dim_factor > 0:
            gain = max(1, gain)
        else:
            gain = 0

        # Cap at effective_ceiling (NOT potential — potential is the
        # theoretical max, effective_ceiling is what this fighter can
        # actually reach given age/health/personality).
        new_val = min(effective_ceiling, cur_val + gain)
        actual_gain = new_val - cur_val
        if actual_gain > 0:
            conn.execute(
                f"UPDATE fighter_attributes SET {attr_name} = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
                (new_val, fighter_id),
            )
            attribute_changes[attr_name] = actual_gain

    # Build the camp_result_summary — a one-line human-readable
    # summary the future UI will display. The Interpretation Layer
    # (Task 19) will translate this into a player-facing string; for
    # now we write the raw data (CONVENTIONS §14 allows raw data in
    # the DB, only the UI must use the interpretation layer).
    if attribute_changes:
        gains_str = ", ".join(f"+{v} {k.replace('_', ' ')}"
                              for k, v in attribute_changes.items())
        summary = f"completed ({camp_focus} focus): {gains_str}"
    else:
        summary = (f"completed ({camp_focus} focus) — no gains "
                   f"(attributes already at potential)")

    conn.execute(
        "UPDATE training_camps SET is_active = 0, is_completed = 1, "
        "attribute_changes = ?, camp_result_summary = ?, "
        "camp_fatigue = ?, camp_morale = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE training_camp_id = ?",
        (json.dumps(attribute_changes), summary, fatigue, morale, camp_id),
    )

    # Completion news item — topic='training' (the news_items.topic
    # column is TEXT with no CHECK, so any string is accepted).
    name_row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters "
        "WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    fighter_name_str = (name_row[0] if name_row
                        else f"Fighter {fighter_id}")
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id,
         f"{fighter_name_str} completes training camp",
         f"{fighter_name_str} has completed a {camp_focus}-focused "
         f"training camp. {summary}.",
         "positive", "training", fighter_id, current_date),
    )

    # v2.8.0 (Task 19): update descriptor snapshot — attributes changed.
    # Lazy-import app to avoid circular dependency (app imports nothing
    # from tick_processor, but tick_processor already imports from app).
    from app import update_fighter_descriptor_snapshot
    update_fighter_descriptor_snapshot(conn, fighter_id)

    # v2.9.0 (Task 18): mark scouting reports stale — fighter changed.
    from scouting import mark_stale_reports
    mark_stale_reports(conn, fighter_id)

    # Phase A (Task A1): publish CAMP_COMPLETED event so the morale
    # system can apply its +3 morale bump for training going well
    # (CONVENTIONS §15.4 — event-bus-driven, no inline morale write
    # here). The event carries the fighter_id + attribute_changes +
    # camp_focus so future subscribers (news engine, social media)
    # can react to camp completions too.
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.CAMP_COMPLETED,
            'training_camp_id': camp_id,
            'fighter_id': fighter_id,
            'camp_focus': camp_focus,
            'attribute_changes': attribute_changes,
            'event_id': None,  # camps aren't tied to a specific event
            'fight_id': None,  # camps aren't tied to a specific fight
            'current_date': current_date,
        })
    except ImportError:
        pass  # event_bus not available (defensive)

    return "completed"


# ----------------------------------------------------------------
# Retirement checking (Task ID 12, extended in Task ID 14).
#
# Fighters age. When a fighter crosses age 40 with declining
# career_health, they retire. Age 45 is mandatory retirement
# (regardless of health). Retiring champions vacate their titles
# (delegated to app._vacate_title_on_retirement). A news item is
# written per retirement.
#
# Task ID 14 added the regen hook: each retirement also generates a
# replacement fighter (via app.generate_fighter) with the same
# fight_style_archetype_id (style DNA). The new fighter enters as a
# free agent and a regen_lineage row is recorded linking the retiring
# fighter to the replacement (for future memory-resurfacing features).
#
# This function runs on every tick (called from run_tick after the
# clock advance). It does NOT commit — the caller commits. This
# matches the existing pattern in app.py where every helper leaves
# the commit to the outermost caller.
#
# Foundation for:
#   - Task 14 (regen) — retiring fighters trigger generate_fighter.
#   - Task 11 (titles) — retiring champions vacate the belt (handled
#     by _vacate_title_on_retirement in app.py).
#   - The "playable forever" loop — without retirement + regen, the
#     roster shrinks permanently and eventually empties.
# ----------------------------------------------------------------

def _check_retirements(conn, current_date):
    """Check all active fighters for retirement eligibility and retire them.

    Retirement rules (Task ID 12):
      - A fighter is retirement-eligible if:
        (a) age >= 40 (computed from date_of_birth and current_date), AND
        (b) career_health < 60 (declining health — a healthy 40-year-old
            can keep fighting, but a worn-down one should hang it up).
      - OR age >= 45 (mandatory retirement — no one fights past 45 in
        this sim, regardless of health).
      - When a fighter retires:
        (a) Set fighters.is_active = 0, fighters.is_retired = 1,
            fighters.updated_at = CURRENT_TIMESTAMP.
        (b) Vacate any title they hold (call
            _vacate_title_on_retirement from app.py).
        (c) Write a news item announcing the retirement.
        (d) Task ID 14: generate a replacement fighter via
            app.generate_fighter (inherits the retiring fighter's
            fight_style_archetype_id as style DNA; enters as a free
            agent) and record a regen_lineage row linking the retiring
            fighter to the replacement.
      - Returns the list of retired fighter_ids (for logging/testing).

    Args:
        conn: sqlite3 connection (caller commits).
        current_date: ISO date string 'YYYY-MM-DD' (the current sim date).

    Returns:
        List of fighter_ids that were retired on this tick.
    """
    try:
        current_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        # Defensive: if current_date is somehow malformed, skip the
        # retirement check entirely (return empty list). The clock
        # advance in run_tick will still commit; the next tick will
        # try again.
        return []

    # Fetch all active, non-retired fighters with their DOB + career
    # health. LEFT JOIN fighter_career so a fighter without a career
    # row (defensive — shouldn't happen with the seed) is treated as
    # career_health=100 (healthy, won't retire on the health rule).
    # We also pull fight_style_archetype_id so we can pass it to the
    # regen_lineage INSERT below (Task ID 14 — the new replacement
    # fighter inherits the retiring fighter's style DNA).
    rows = conn.execute(
        "SELECT f.fighter_id, f.first_name, f.last_name, f.date_of_birth, "
        "f.fight_style_archetype_id, "
        "COALESCE(fc.career_health, 100) AS career_health "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 AND f.is_retired = 0"
    ).fetchall()

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news). The seeded DB already has this source.
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    retired = []
    for fighter_id, first_name, last_name, dob, style_archetype_id, career_health in rows:
        # Compute age: years between dob and current_date, adjusted
        # down by 1 if the birthday hasn't happened yet this year.
        # Comparing (month, day) tuples handles leap-year babies
        # correctly (Feb 29 vs Feb 28 in non-leap years).
        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
        except (ValueError, TypeError):
            # Defensive: skip fighters with malformed DOB. (Shouldn't
            # happen with the seed, but a future regen engine or mod
            # tool could produce one.)
            continue
        age = current_dt.year - dob_dt.year
        if (current_dt.month, current_dt.day) < (dob_dt.month, dob_dt.day):
            age -= 1

        # Eligibility: age >= 45 (mandatory) OR (age >= 40 AND
        # career_health < 60). The brief specifies `< 60` for the
        # health threshold — a fighter with career_health exactly 60
        # does NOT retire (boundary case tested in test_retirement.py
        # case D).
        eligible = (age >= 45) or (age >= 40 and career_health < 60)
        if not eligible:
            continue

        # Retire the fighter. is_active=0 means _pick_matchup (Task 8)
        # and any future "available fighters" queries will skip them.
        # is_retired=1 distinguishes "retired" from "inactive for
        # another reason" (e.g., injury in Task 15, suspension in a
        # future task). Both flags are set together here.
        conn.execute(
            "UPDATE fighters SET is_active = 0, is_retired = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
            (fighter_id,),
        )

        # Vacate any title the retiring fighter holds. Returns the
        # list of vacated title_ids (empty list if they held none).
        # The helper writes its own news item per vacation, so we
        # don't write a duplicate one here.
        _vacate_title_on_retirement(conn, fighter_id, current_date)

        # Write the retirement news item. topic='retirement' so the
        # future news engine (Task 23) can filter retirement-themed
        # items. fighter_id is set so future UIs can filter "this
        # fighter's news". promotion_id is left NULL (the news is
        # about the fighter, not a specific promotion — a fighter can
        # retire from one promotion and sign with another in Task 13).
        full_name = f"{first_name} {last_name}"
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                src_id,
                f"{full_name} announces retirement at age {age}",
                f"After a long career, {full_name} has announced retirement "
                f"from professional MMA competition at age {age}.",
                "neutral",
                "retirement",
                fighter_id,
                current_date,
            ),
        )

        # ----------------------------------------------------------------
        # Regen engine (Task ID 14). When a fighter retires, generate
        # a replacement fighter from the name pools with the same
        # fight_style_archetype_id (style DNA). The new fighter enters
        # as a free agent (current_promotion_id=NULL, is_active=1,
        # is_retired=0) so they appear in Task 13's Free Agents tab
        # and can be signed by any promotion. Record the regen_lineage
        # row linking the retiring fighter to the replacement (for
        # future memory-resurfacing features in Stage 3+).
        #
        # The replacement fighter's fighter_id is appended to the
        # `retired` list returned by this function (alongside the
        # retiring fighter's fighter_id) so the caller can log both.
        # We don't append to `retired` here — that list is "fighters
        # retired on this tick", and the replacement isn't retired.
        # The replacement_id is logged via a separate print in
        # run_tick (see below).
        #
        # v2.0.1 (Task pre-B1-fixes): champion-successor memory
        # resurfacing. After generating the replacement, check whether
        # the retiring fighter was ever a champion (fighter_career.
        # title_reigns > 0). If YES:
        #   - Create a fighter_memory_links row with link_type=
        #     'successor' linking the new fighter to the retiring
        #     champion. link_strength is based on title_reigns (more
        #     reigns = stronger link): min(50 + 10*reigns, 100).
        #   - Write a "comparisons to former champion {name}" news
        #     item with topic='legacy' (separate from the standard
        #     'prospect' news generate_fighter already wrote). This
        #     is the memory-resurfacing payoff: the world remembers
        #     who the retiring champion was and draws the comparison
        #     to the new prospect.
        # If NO (non-champion retirement): no memory link, no extra
        # news. The standard "new prospect emerges" news from
        # generate_fighter is enough — keeps the world alive without
        # cheapening the memory-resurfacing feature.
        # ----------------------------------------------------------------
        replacement_id = generate_fighter(
            conn,
            style_dna_source_id=fighter_id,  # inherit retiring fighter's style archetype
            current_date=current_date,
        )
        if replacement_id is not None:
            # Record the regen lineage. style_dna_archetype_id is the
            # retiring fighter's archetype (already fetched above) —
            # the replacement inherits it via generate_fighter.
            # INSERT OR IGNORE protects against the (theoretically
            # impossible) case of duplicate (retiring, replacement)
            # pairs — the UNIQUE constraint on regen_lineage enforces
            # this. regen_date is the sim date the retirement happened
            # on (NOT CURRENT_TIMESTAMP which is wall-clock time).
            conn.execute(
                "INSERT OR IGNORE INTO regen_lineage (retiring_fighter_id, "
                "replacement_fighter_id, style_dna_archetype_id, regen_date) "
                "VALUES (?, ?, ?, ?)",
                (fighter_id, replacement_id, style_archetype_id, current_date),
            )

            # v2.0.1 (Task pre-B1-fixes): champion-successor memory
            # resurfacing. Check whether the retiring fighter was
            # ever a champion. The fighter_career.title_reigns column
            # is the cleanest, most reliable signal — it's incremented
            # by _resolve_title_after_fight() in app.py every time
            # the fighter wins a title (vacant title claimed OR
            # reigning champion dethroned). COALESCE(..., 0) is
            # defensive: a fighter without a career row (shouldn't
            # happen with the seed) is treated as non-champion.
            reigns_row = conn.execute(
                "SELECT COALESCE(fc.title_reigns, 0) "
                "FROM fighter_career fc "
                "WHERE fc.fighter_id = ?",
                (fighter_id,),
            ).fetchone()
            retiring_reigns = reigns_row[0] if reigns_row else 0

            if retiring_reigns > 0:
                # The retiring fighter was a champion. Create the
                # fighter_memory_links 'successor' row linking the
                # new prospect to the retiring champion. link_strength
                # is based on title_reigns: 1 reign = 60, 2 = 70,
                # 3 = 80, 4 = 90, 5+ = 100 (capped). More reigns =
                # stronger link (a 5-reign champion's successor is a
                # MUCH bigger deal than a 1-reign champion's
                # successor). INSERT OR IGNORE protects against the
                # UNIQUE (fighter_id, linked_fighter_id, link_type)
                # constraint — duplicate successor links (theoretically
                # impossible since regen_lineage also has UNIQUE on
                # retiring+replacement pairs) are silently skipped.
                link_strength = min(50 + 10 * retiring_reigns, 100)
                conn.execute(
                    "INSERT OR IGNORE INTO fighter_memory_links "
                    "(fighter_id, linked_fighter_id, link_type, "
                    "link_strength) VALUES (?, ?, 'successor', ?)",
                    (replacement_id, fighter_id, link_strength),
                )

                # Write the champion-successor comparison news item.
                # topic='legacy' so future UI filters can group
                # memory-resurfacing news together (separate from
                # 'prospect' news the standard generate_fighter
                # already wrote, and from 'retirement' news the
                # retirement announcement already wrote). The
                # headline follows the brief's exact wording: "New
                # prospect {name} emerges on the scene — fight fans
                # are already drawing comparisons to former champion
                # {retiring_fighter_name}." fighter_id is set to the
                # NEW fighter (the prospect) so future UIs can filter
                # "this prospect's news". published_at=current_date.
                replacement_name_row = conn.execute(
                    "SELECT first_name || ' ' || last_name "
                    "FROM fighters WHERE fighter_id = ?",
                    (replacement_id,),
                ).fetchone()
                replacement_name = (
                    replacement_name_row[0]
                    if replacement_name_row
                    else f"Fighter {replacement_id}"
                )
                conn.execute(
                    "INSERT INTO news_items (news_source_id, headline, "
                    "body, sentiment, topic, fighter_id, published_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        src_id,
                        f"New prospect {replacement_name} emerges on "
                        f"the scene — fight fans are already drawing "
                        f"comparisons to former champion {full_name}",
                        f"A new talent, {replacement_name}, has arrived "
                        f"as a free agent. Fans and pundits are already "
                        f"drawing comparisons to former champion "
                        f"{full_name}, who retired with "
                        f"{retiring_reigns} title reign(s) to their "
                        f"name. Only time will tell whether the "
                        f"comparisons hold up.",
                        "positive",
                        "legacy",
                        replacement_id,
                        current_date,
                    ),
                )
            # Non-champion retirement: no memory link, no extra news.
            # The standard "new prospect emerges" news from
            # generate_fighter is the only prospect news — keeps the
            # world alive without cheapening the memory-resurfacing
            # feature.

        retired.append(fighter_id)

    return retired


# ----------------------------------------------------------------
# Contract expiry (Task ID 13).
#
# When a fighter's contract end_date passes the current sim date,
# the contract transitions to 'expired' and the fighter becomes a
# free agent (current_promotion_id = NULL). This is the talent-
# circulation foundation for:
#   - Task 25 (rival promotion AI) — RFL signs free agents.
#   - Task 14 (regen) — new generated fighters enter as free agents.
#   - The "playable forever" loop — without free agency the roster
#     is static.
#
# Rules:
#   - For each contract with status='active' AND end_date < current_date:
#     (a) Set contracts.status = 'expired', contracts.updated_at =
#         CURRENT_TIMESTAMP.
#     (b) If the contract is a fighter contract
#         (contract_target_type='fighter' AND the linked fighter is
#         NOT retired), set the fighter's current_promotion_id = NULL
#         and is_active = 1 (they're still active, just unsigned). The
#         is_retired check is important: a retired fighter whose
#         contract also expired on this tick was retired FIRST by
#         _check_retirements (which runs before this function in
#         run_tick). Setting current_promotion_id = NULL on a retired
#         fighter would be misleading — they're not a free agent,
#         they're retired. So we skip that update for retired fighters.
#     (c) For fighter contracts (non-retired), write a news item:
#         "<fighter> becomes a free agent".
#   - Staff / broadcast contracts also expire (status -> 'expired')
#     but they don't have a current_promotion_id column on the
#     fighters table — they're in the `staff` table — so no fighter
#     update happens, and no news item is written for them (the
#     player-facing UI doesn't surface staff contract expiry).
#   - Returns the list of (contract_id, fighter_id_or_None) tuples
#     that expired (fighter_id is None for staff/broadcast contracts,
#     or for fighter contracts whose fighter is already retired).
#
# This function runs on every tick (called from run_tick AFTER
# _check_retirements, so a retired-and-contract-expiring fighter is
# handled correctly). It does NOT commit — the caller commits.
# ----------------------------------------------------------------

def _check_contract_expiry(conn, current_date):
    """Expire contracts past their end_date and set fighters as free agents.

    Rules (Task ID 13):
      - For each contract with status='active' AND end_date < current_date:
        (a) Set contracts.status = 'expired', contracts.updated_at =
            CURRENT_TIMESTAMP.
        (b) If the contract is a fighter contract
            (contract_target_type='fighter') AND the linked fighter is
            NOT already retired, set the fighter's current_promotion_id
            = NULL (they become a free agent). Also set is_active = 1
            (they're still active, just unsigned — defensive in case
            they were marked inactive for some other reason). Retired
            fighters are skipped: they're not free agents, they're
            retired.
        (c) For fighter contracts whose fighter is not retired, write a
            news item: "<fighter> becomes a free agent". topic='signing'
            (so future UI filters can group signing-related news
            together), fighter_id set, published_at=current_date.
      - Staff/broadcast contracts (contract_target_type='staff' or
        'broadcast') also expire but don't set current_promotion_id
        (staff don't have that column) and don't get a news item.
      - Returns the list of (contract_id, fighter_id_or_None) tuples
        that expired. fighter_id is None for staff/broadcast contracts
        and for fighter contracts whose fighter is already retired.

    Args:
        conn: sqlite3 connection (caller commits).
        current_date: ISO date string 'YYYY-MM-DD' (the current sim date).

    Returns:
        List of (contract_id, fighter_id) tuples for contracts that
        expired on this tick. fighter_id is None for staff/broadcast
        contracts and for fighter contracts whose fighter is already
        retired.
    """
    # Fetch active contracts past their end_date. LEFT JOIN
    # fighter_contracts to pick up the fighter_id (NULL for staff/
    # broadcast contracts). LEFT JOIN fighters to get the name +
    # is_retired flag (we only want to set current_promotion_id=NULL
    # for non-retired fighters).
    rows = conn.execute(
        "SELECT c.contract_id, c.contract_target_type, "
        "fc.fighter_id, f.first_name, f.last_name, f.is_retired "
        "FROM contracts c "
        "LEFT JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "LEFT JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE c.status = 'active' AND c.end_date < ?",
        (current_date,),
    ).fetchall()

    if not rows:
        return []

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news and _check_retirements). The seeded DB already
    # has this source.
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    expired = []
    for contract_id, target_type, fighter_id, first_name, last_name, is_retired in rows:
        # (a) Mark the contract as expired.
        conn.execute(
            "UPDATE contracts SET status = 'expired', "
            "updated_at = CURRENT_TIMESTAMP WHERE contract_id = ?",
            (contract_id,),
        )

        # (b) For fighter contracts whose fighter is NOT retired, set
        # current_promotion_id = NULL (free agent). is_retired check
        # is critical: a retired fighter whose contract also expired
        # on this tick was retired FIRST by _check_retirements (which
        # runs before this function in run_tick). Setting
        # current_promotion_id = NULL on a retired fighter would be
        # misleading — they're not a free agent, they're retired.
        if target_type == 'fighter' and fighter_id is not None and is_retired != 1:
            conn.execute(
                "UPDATE fighters SET current_promotion_id = NULL, "
                "is_active = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE fighter_id = ?",
                (fighter_id,),
            )
            # (c) Write the free-agency news item.
            full_name = f"{first_name} {last_name}"
            conn.execute(
                "INSERT INTO news_items (news_source_id, headline, body, "
                "sentiment, topic, fighter_id, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    src_id,
                    f"{full_name} becomes a free agent",
                    f"{full_name}'s contract has expired and they are now "
                    f"a free agent, available to sign with any promotion.",
                    "neutral",
                    "signing",
                    fighter_id,
                    current_date,
                ),
            )
            expired.append((contract_id, fighter_id))
        else:
            # Staff/broadcast contract, OR fighter contract for an
            # already-retired fighter. No fighter update, no news item.
            expired.append((contract_id, None))

    return expired


def run_tick(conn, tick_type="day", steps=1):
    for _ in range(steps):
        # v2.0.0 (Task 14.7): qualify current_date (and the other
        # clock columns, for consistency) as simulation_clock.current_date
        # etc. to avoid the pre-existing SQLite quirk (§Z.6 in
        # SCHEMA_DRIFT_AUDIT.md) where bare `current_date` resolves to
        # SQLite's built-in date FUNCTION (today's wall-clock date)
        # instead of the simulation_clock.current_date COLUMN. This
        # caused the sim clock to jump from the seeded 2026-07-20 to
        # today+1 on the first tick. The new acceptance test
        # test_fighter_attributes.py case F verifies the tick now
        # advances by exactly 1 day from the seeded date.
        row = conn.execute("SELECT simulation_clock.current_date, simulation_clock.current_day, simulation_clock.current_week, simulation_clock.current_month, simulation_clock.current_year FROM simulation_clock WHERE clock_id=1").fetchone()
        dt = datetime.strptime(row[0], "%Y-%m-%d") + timedelta(days=1)
        day = row[1] + 1
        week = ((day - 1) // 7) + 1
        conn.execute(
            "UPDATE simulation_clock SET current_date=?, current_day=?, current_week=?, current_month=?, current_year=?, current_tick_type=?, tick_counter=tick_counter+1, updated_at=CURRENT_TIMESTAMP WHERE clock_id=1",
            (dt.strftime("%Y-%m-%d"), day, week, dt.month, dt.year, tick_type),
        )
        # Task ID 12: check for retirements on every tick. Runs AFTER
        # the clock advance so the retirement check uses the NEW sim
        # date (a fighter who turns 40 on this tick's new date becomes
        # eligible today, not yesterday). The function does NOT commit
        # — the conn.commit() below covers both the clock UPDATE and
        # any retirement side effects (fighters UPDATE, titles UPDATE,
        # news_items INSERTs). Task ID 14: each retirement also triggers
        # generate_fighter() which adds a replacement fighter + writes
        # the new-prospect news item + records the regen_lineage row.
        # Prints a one-line log per tick if any fighters were retired,
        # mirroring the pattern in resolve_next_fight's auto-schedule
        # warning.
        retired = _check_retirements(conn, dt.strftime("%Y-%m-%d"))
        if retired:
            print(f"  Retired {len(retired)} fighter(s) on "
                  f"{dt.strftime('%Y-%m-%d')}: {retired}")
            # Task ID 14: log regens alongside retirements. Each retired
            # fighter spawned a replacement — query regen_lineage to
            # find the replacement_ids.
            regens = conn.execute(
                "SELECT retiring_fighter_id, replacement_fighter_id "
                "FROM regen_lineage WHERE regen_date = ?",
                (dt.strftime("%Y-%m-%d"),),
            ).fetchall()
            if regens:
                print(f"  Generated {len(regens)} replacement fighter(s) on "
                      f"{dt.strftime('%Y-%m-%d')}: {regens}")
        # Task ID 13: check for contract expiry on every tick. Runs
        # AFTER _check_retirements so a retired-and-contract-expiring
        # fighter is handled correctly: _check_retirements sets
        # is_retired=1 first, then _check_contract_expiry sees
        # is_retired=1 and skips the current_promotion_id=NULL update
        # (they're retired, not a free agent). The function does NOT
        # commit — the conn.commit() below covers both the clock
        # UPDATE and any contract-expiry side effects (contracts
        # UPDATE, fighters UPDATE, news_items INSERTs). Prints a one-
        # line log per tick if any contracts expired.
        expired = _check_contract_expiry(conn, dt.strftime("%Y-%m-%d"))
        if expired:
            print(f"  Expired {len(expired)} contract(s) on "
                  f"{dt.strftime('%Y-%m-%d')}: {expired}")
        # Task ID 15: check for injury recovery on every tick. Runs
        # AFTER _check_contract_expiry so the order is: clock advance →
        # _check_retirements → _check_contract_expiry →
        # _check_injury_recovery → commit. For each active injury whose
        # projected_return_date <= current_date: sets is_active=0,
        # actual_return_date=current_date, restores career_health by
        # severity*2 (the temporary penalty), and writes a clearance
        # news item. The function does NOT commit — the conn.commit()
        # below covers both the clock UPDATE and any injury-recovery
        # side effects (injuries UPDATE, fighter_career UPDATE,
        # news_items INSERTs). Prints a one-line log per tick if any
        # injuries were recovered.
        recovered = _check_injury_recovery(conn, dt.strftime("%Y-%m-%d"))
        if recovered:
            print(f"  Recovered {len(recovered)} injur(ies) on "
                  f"{dt.strftime('%Y-%m-%d')}: {recovered}")
        # v2.5.0 (Task 16): progress and complete active training camps
        # on every tick. Runs AFTER _check_injury_recovery so the order
        # is: clock advance → _check_retirements → _check_contract_
        # expiry → _check_injury_recovery → _check_training_camps →
        # commit. For each active, uncompleted camp whose [start_date,
        # end_date] window contains current_date: progress the camp
        # (accrue fatigue, fluctuate morale, accumulate injury risk,
        # maybe spawn a training injury) or complete it (apply
        # attribute gains, write news item). The function does NOT
        # commit — the conn.commit() below covers both the clock
        # UPDATE and any camp side effects.
        camps = _check_training_camps(conn, dt.strftime("%Y-%m-%d"))
        if camps:
            print(f"  Processed {len(camps)} training camp(s) on "
                  f"{dt.strftime('%Y-%m-%d')}: {camps}")
        # v2.9.0 (Task 18): process scouting assignments. Checks all
        # scouts for ready assignments (7+ days elapsed) and generates
        # reports. Lazy-import to avoid circular dependency.
        from scouting import _check_scouting_assignments
        scouting_done = _check_scouting_assignments(conn, dt.strftime("%Y-%m-%d"))
        if scouting_done:
            print(f"  Generated {len(scouting_done)} scouting report(s) on "
                  f"{dt.strftime('%Y-%m-%d')}: {scouting_done}")
        # v2.9.1 (Task 18.5): publish TICK_ADVANCED event. Stage 4+
        # systems that need to react to time passing (e.g., social
        # media posts, rivalry cooldowns, finances) will subscribe.
        try:
            from event_bus import get_bus, Events
            bus = get_bus()
            bus.publish(conn, {
                'type': Events.TICK_ADVANCED,
                'current_date': dt.strftime("%Y-%m-%d"),
                'tick_type': tick_type,
            })
        except ImportError:
            pass
        conn.commit()

def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        run_tick(conn, "day", 1)
    print("Tick advanced.")

if __name__ == "__main__":
    main()
