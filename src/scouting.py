"""CAGE EMPIRE Scouting System (Task 18).

Scouts are staff members with role_type='scout'. Their attributes are
stored in the staff.specialty field as JSON:

  {
    "eye_for_talent": 70,        # 0-100, accuracy of potential estimates
    "technical_analysis": 65,     # 0-100, accuracy of attribute estimates
    "character_reading": 60,      # 0-100, accuracy of personality estimates
    "mistake_rate": 15,           # 0-100, chance of a significant misjudgment
    "bias_style": "Striker",      # over-rates this style, under-rates others
    "bias_nationality": "Brazil", # better accuracy for fighters from this nation
    "bias_aggression": 10,        # -20 to +20, over/under-estimates aggressive fighters
    "current_assignment": 42,     # fighter_id currently being scouted (or null)
    "assignment_start_date": "2026-08-01"  # when the current assignment started
  }

ASSIGNMENT LIFECYCLE:
  1. Player (or AI) calls assign_scout(scout_id, target_fighter_id)
  2. The assignment is stored in the scout's specialty JSON
  3. On each tick, _check_scouting_assignments() checks if enough
     time has passed (default 7 days = 7 ticks)
  4. If ready, generate_scouting_report() is called — it loads the
     fighter's TRUE values, applies scout accuracy (Gaussian noise),
     biases (style/nationality/aggression), and mistake rolls, then
     converts everything to descriptors via voice.py (Task 19)
  5. The report is written to scouting_reports + a news item
  6. The scout's assignment is cleared (ready for the next target)

ACCURACY MODEL:
  estimated_value = true_value + gaussian_noise(0, noise_std)
  noise_std = (100 - scout_attribute) / 4
  - A 90-eye scout has ±2.5 noise (very accurate)
  - A 50-eye scout has ±12.5 noise (moderate)
  - A 10-eye scout has ±22.5 noise (wildly inaccurate)

BIASES:
  - bias_style: if the fighter's style matches, +5 to all estimates;
    if opposite (Striker vs Grappler), -5
  - bias_nationality: if the fighter is from the scout's nation,
    noise is halved (familiarity); if unfamiliar, noise is +50%
  - bias_aggression: applied to the aggression estimate directly

MISTAKES (the "real people who make mistakes" directive):
  Each report has a chance (mistake_rate%) of containing a significant
  misjudgment:
    - overestimate_potential: scout sees a flash and projects too high
    - underestimate_potential: scout misses a late bloomer
    - misread_strength_weakness: a strength is reported as a weakness
    - miss_key_trait: a standout attribute is completely missed
    - confidence_mismatch: scout is very confident but very wrong

POTENTIAL ≠ GUARANTEED SUCCESS:
  The scout estimates the fighter's CEILING (potential), but the
  fighter may never reach it. The effective_ceiling growth logic in
  tick_processor._complete_training_camp reduces the actual ceiling
  based on age, health, personality, and diminishing returns. A
  scout might correctly identify a "generational talent ceiling"
  (potential=90), but if the fighter is 32 with health=60 and low
  discipline, their effective ceiling is 90 * 0.80 * 0.70 * 0.40 = 20.
  The player must read the scouting report AND consider the fighter's
  age, health, and personality when deciding whether to invest.
"""
import json
import random
import sqlite3
from datetime import datetime, timedelta


# Default scout attributes when a new scout is created without explicit specs.
DEFAULT_SCOUT_ATTRS = {
    "eye_for_talent": 50,
    "technical_analysis": 50,
    "character_reading": 50,
    "mistake_rate": 20,
    "bias_style": None,
    "bias_nationality": None,
    "bias_aggression": 0,
    "current_assignment": None,
    "assignment_start_date": None,
}

# How many ticks (days) a scout needs to observe a fighter before
# generating a report. 7 days = 1 week of observation.
SCOUTING_DURATION_DAYS = 7

# Style opposites for bias calculation.
_STYLE_OPPOSITES = {
    "Striker": "Grappler",
    "Grappler": "Striker",
    "Wrestler": "Striker",
    "Brawler": "Counter-Striker",
    "Counter-Striker": "Brawler",
    "Submission Specialist": "Striker",
    "Balanced": None,  # no opposite
}


def _load_scout_attrs(conn, scout_id):
    """Load a scout's attributes from the staff.specialty JSON field.

    Returns a dict with the DEFAULT_SCOUT_ATTRS keys, overlaid with
    whatever is stored in the specialty field. If the specialty is
    not valid JSON or doesn't contain scout keys, defaults are used.
    """
    row = conn.execute(
        "SELECT specialty FROM staff WHERE staff_id=? AND role_type='scout'",
        (scout_id,),
    ).fetchone()
    if row is None or not row[0]:
        return dict(DEFAULT_SCOUT_ATTRS)
    try:
        stored = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return dict(DEFAULT_SCOUT_ATTRS)
    attrs = dict(DEFAULT_SCOUT_ATTRS)
    attrs.update(stored)
    return attrs


def _save_scout_attrs(conn, scout_id, attrs):
    """Save a scout's attributes to the staff.specialty JSON field."""
    conn.execute(
        "UPDATE staff SET specialty=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE staff_id=?",
        (json.dumps(attrs), scout_id),
    )


def assign_scout(conn, scout_id, target_fighter_id, promotion_id=None):
    """Assign a scout to evaluate a target fighter.

    Stores the assignment in the scout's specialty JSON. The report
    will be generated after SCOUTING_DURATION_DAYS ticks (processed
    by _check_scouting_assignments on each tick).

    Args:
        conn: sqlite3 connection (caller commits).
        scout_id: the staff_id of the scout.
        target_fighter_id: the fighter to evaluate.
        promotion_id: the promotion commissioning the report (optional).

    Returns:
        True if the assignment was made, False if the scout is already
        assigned or doesn't exist.
    """
    attrs = _load_scout_attrs(conn, scout_id)
    if attrs.get("current_assignment") is not None:
        return False  # scout is already assigned
    # Get current sim date
    date_row = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock"
    ).fetchone()
    current_date = date_row[0] if date_row else datetime.now().strftime("%Y-%m-%d")
    attrs["current_assignment"] = target_fighter_id
    attrs["assignment_start_date"] = current_date
    attrs["assignment_promotion_id"] = promotion_id
    _save_scout_attrs(conn, scout_id, attrs)
    return True


def _check_scouting_assignments(conn, current_date):
    """Check all scouts for ready assignments and generate reports.

    Called by run_tick() on every tick. For each scout with an active
    assignment (current_assignment is not None), checks if
    SCOUTING_DURATION_DAYS have passed since assignment_start_date.
    If yes, generates the scouting report and clears the assignment.

    Returns a list of (scout_id, target_fighter_id) tuples for reports
    generated on this tick.
    """
    scouts = conn.execute(
        "SELECT staff_id FROM staff WHERE role_type='scout'"
    ).fetchall()
    completed = []
    for (scout_id,) in scouts:
        attrs = _load_scout_attrs(conn, scout_id)
        target_id = attrs.get("current_assignment")
        start_date = attrs.get("assignment_start_date")
        if target_id is None or start_date is None:
            continue
        # Check if enough days have passed
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            current_dt = datetime.strptime(current_date, "%Y-%m-%d")
            days_elapsed = (current_dt - start_dt).days
        except (ValueError, TypeError):
            continue
        if days_elapsed >= SCOUTING_DURATION_DAYS:
            promo_id = attrs.get("assignment_promotion_id")
            generate_scouting_report(conn, scout_id, target_id, promo_id, current_date)
            # Clear the assignment
            attrs["current_assignment"] = None
            attrs["assignment_start_date"] = None
            attrs["assignment_promotion_id"] = None
            _save_scout_attrs(conn, scout_id, attrs)
            completed.append((scout_id, target_id))
    return completed


def generate_scouting_report(conn, scout_id, target_fighter_id,
                             promotion_id, current_date):
    """Generate a scouting report for a fighter.

    This is the CORE function of the scouting system. It:
    1. Loads the fighter's TRUE attributes, personality, potential
    2. Loads the scout's attributes from specialty JSON
    3. Applies Gaussian noise based on scout accuracy
    4. Applies scout biases (style, nationality, aggression)
    5. Rolls for mistakes (overestimate, underestimate, misread, etc.)
    6. Converts estimated values to descriptors via voice.py (Task 19)
    7. Writes the scouting_reports row + a news item

    Per CONVENTIONS §14: all estimates use voice.py descriptors, NOT
    raw numbers. The player sees "high ceiling, above-average power"
    — not "potential=72, punch_power=78."

    Args:
        conn: sqlite3 connection (caller commits).
        scout_id: the staff_id of the scout.
        target_fighter_id: the fighter being scouted.
        promotion_id: the promotion commissioning the report.
        current_date: the sim date (for the report_date field).
    """
    import voice  # lazy import — voice.py is in src/

    # ---- 1. Load the fighter's TRUE values ----
    f_row = conn.execute(
        "SELECT f.first_name, f.last_name, f.nickname, f.date_of_birth, "
        "f.fight_style_archetype_id, f.birth_nation_id, "
        "f.marketability, f.injury_proneness, "
        "sa.name AS style_archetype_name, n.name AS nation_name, "
        "fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.career_health, fc.potential, "
        "fc.title_reigns "
        "FROM fighters f "
        "LEFT JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
        "LEFT JOIN nations n ON n.nation_id=f.birth_nation_id "
        "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "WHERE f.fighter_id=?",
        (target_fighter_id,),
    ).fetchone()
    if f_row is None:
        return  # fighter doesn't exist
    (first, last, nick, dob, sa_id, birth_nation_id, market, inj_pron,
     sa_name, nation_name, wins, losses, draws, ws, ls, health, true_potential,
     reigns) = f_row

    # Load true attributes
    attr_row = conn.execute(
        "SELECT * FROM fighter_attributes WHERE fighter_id=?",
        (target_fighter_id,),
    ).fetchone()
    if attr_row is None:
        return
    attr_cols = [d[0] for d in conn.execute(
        "SELECT * FROM fighter_attributes WHERE fighter_id=?", (target_fighter_id,)
    ).description]
    true_attrs = {col: val for col, val in zip(attr_cols, attr_row)
                  if col not in ("fighter_attribute_id", "fighter_id", "created_at", "updated_at")
                  and val is not None}

    # Load true personality
    pers_row = conn.execute(
        "SELECT * FROM fighter_personality WHERE fighter_id=?",
        (target_fighter_id,),
    ).fetchone()
    if pers_row is None:
        return
    pers_cols = [d[0] for d in conn.execute(
        "SELECT * FROM fighter_personality WHERE fighter_id=?", (target_fighter_id,)
    ).description]
    true_pers = {col: val for col, val in zip(pers_cols, pers_row)
                 if col not in ("fighter_personality_id", "fighter_id", "created_at", "updated_at")
                 and val is not None}

    # ---- 2. Load the scout's attributes ----
    scout_attrs = _load_scout_attrs(conn, scout_id)
    eye = scout_attrs.get("eye_for_talent", 50)
    tech = scout_attrs.get("technical_analysis", 50)
    char_read = scout_attrs.get("character_reading", 50)
    mistake_rate = scout_attrs.get("mistake_rate", 20)
    bias_style = scout_attrs.get("bias_style")
    bias_nat = scout_attrs.get("bias_nationality")
    bias_agg = scout_attrs.get("bias_aggression", 0)

    # Scout name for the report
    scout_row = conn.execute(
        "SELECT first_name, last_name FROM staff WHERE staff_id=?",
        (scout_id,),
    ).fetchone()
    scout_name = f"{scout_row[0]} {scout_row[1]}" if scout_row else "Unknown Scout"

    # ---- 3. Apply Gaussian noise based on scout accuracy ----
    # noise_std = (100 - attribute) / 4
    # A 90-eye scout: ±2.5 noise. A 50-eye scout: ±12.5. A 10-eye: ±22.5.
    pot_noise_std = (100 - eye) / 4.0
    attr_noise_std = (100 - tech) / 4.0
    pers_noise_std = (100 - char_read) / 4.0

    # Nationality familiarity: if the fighter is from the scout's
    # familiar nation, noise is halved. If unfamiliar, +50%.
    nat_mult = 1.0
    if bias_nat and nation_name:
        if bias_nat == nation_name:
            nat_mult = 0.5  # familiar — more accurate
        else:
            nat_mult = 1.5  # unfamiliar — less accurate

    pot_noise_std *= nat_mult
    attr_noise_std *= nat_mult
    pers_noise_std *= nat_mult

    # Estimate potential with noise
    est_potential = true_potential + random.gauss(0, pot_noise_std)
    est_potential = max(1, min(100, int(round(est_potential))))

    # Estimate attributes with noise
    est_attrs = {}
    for attr_name, true_val in true_attrs.items():
        est_val = true_val + random.gauss(0, attr_noise_std)
        est_attrs[attr_name] = max(1, min(100, int(round(est_val))))

    # Estimate personality with noise
    est_pers = {}
    for trait_name, true_val in true_pers.items():
        est_val = true_val + random.gauss(0, pers_noise_std)
        est_pers[trait_name] = max(1, min(100, int(round(est_val))))

    # ---- 4. Apply scout biases ----
    # Style bias: if the fighter's style matches the scout's preference,
    # +5 to all estimates. If opposite, -5.
    if bias_style and sa_name:
        if bias_style == sa_name:
            for k in est_attrs:
                est_attrs[k] = min(100, est_attrs[k] + 5)
        elif _STYLE_OPPOSITES.get(bias_style) == sa_name:
            for k in est_attrs:
                est_attrs[k] = max(1, est_attrs[k] - 5)

    # Aggression bias: applied directly to the aggression estimate
    if "aggression" in est_pers:
        est_pers["aggression"] = max(1, min(100, est_pers["aggression"] + bias_agg))

    # ---- 5. Roll for mistakes ----
    # Each report has mistake_rate% chance of containing a significant
    # misjudgment. If triggered, pick a mistake type and apply it.
    mistake_type = None
    if random.random() * 100 < mistake_rate:
        mistake_type = random.choice([
            "overestimate_potential",
            "underestimate_potential",
            "misread_strength_weakness",
            "miss_key_trait",
            "confidence_mismatch",
        ])
        if mistake_type == "overestimate_potential":
            est_potential = min(100, est_potential + random.randint(10, 25))
        elif mistake_type == "underestimate_potential":
            est_potential = max(1, est_potential - random.randint(10, 25))
        elif mistake_type == "misread_strength_weakness":
            # Swap the highest and lowest estimated attributes
            if est_attrs:
                sorted_attrs = sorted(est_attrs.items(), key=lambda x: x[1])
                lowest_name, lowest_val = sorted_attrs[0]
                highest_name, highest_val = sorted_attrs[-1]
                est_attrs[lowest_name] = highest_val
                est_attrs[highest_name] = lowest_val
        elif mistake_type == "miss_key_trait":
            # Set the highest estimated attribute to average (50)
            if est_attrs:
                highest_name = max(est_attrs, key=est_attrs.get)
                est_attrs[highest_name] = 50
        elif mistake_type == "confidence_mismatch":
            # The scout is very confident but very wrong — double the
            # noise on all estimates (applied retroactively)
            for k in est_attrs:
                est_attrs[k] = max(1, min(100, est_attrs[k] + random.randint(-20, 20)))
            est_potential = max(1, min(100, est_potential + random.randint(-20, 20)))

    # ---- 6. Convert to descriptors via voice.py ----
    # Use a deterministic rng seeded by (scout_id * 1000 + target_fighter_id)
    # so the same scout evaluating the same fighter gets the same variants
    # (stable report). Different scouts get different variants.
    rng = random.Random(scout_id * 1000 + target_fighter_id)

    # Potential descriptor (scouted=True — the scout IS revealing it)
    pot_desc = voice.describe_potential(est_potential, scouted=True, rng=rng)

    # Estimated ceiling: this is the scout's estimate of what the
    # fighter can ACTUALLY reach (accounting for age/health/personality).
    # We compute a rough effective ceiling the same way the growth
    # logic does, but using ESTIMATED values.
    fighter_age = 25
    if dob:
        try:
            fighter_age = 2026 - int(dob[:4])
        except (ValueError, TypeError):
            pass
    if fighter_age <= 27:
        age_factor = 1.0
    elif fighter_age <= 30:
        age_factor = 0.95
    elif fighter_age <= 33:
        age_factor = 0.80
    elif fighter_age <= 36:
        age_factor = 0.60
    else:
        age_factor = 0.35
    est_health = health or 100
    if est_health >= 90:
        health_factor = 1.0
    elif est_health >= 70:
        health_factor = 0.90
    elif est_health >= 50:
        health_factor = 0.70
    elif est_health >= 30:
        health_factor = 0.40
    else:
        health_factor = 0.15
    est_discipline = est_pers.get("discipline", 50)
    est_coachability = est_pers.get("coachability", 50)
    personality_factor = (est_discipline + est_coachability) / 200.0
    est_effective_ceiling = int(est_potential * age_factor * health_factor * personality_factor)
    est_effective_ceiling = max(10, est_effective_ceiling)

    ceiling_desc = voice.describe_potential(est_effective_ceiling, scouted=True, rng=rng)
    floor_desc = voice.describe_potential(
        max(10, int(est_effective_ceiling * 0.5)), scouted=True, rng=rng
    )

    # Strengths: top 3 estimated attributes
    sorted_est = sorted(est_attrs.items(), key=lambda x: x[1], reverse=True)
    strengths = []
    for attr_name, val in sorted_est[:3]:
        if val >= 60:  # only report as a strength if above average
            desc = voice.describe_attribute(attr_name, val, rng)
            strengths.append(desc)
    # Weaknesses: bottom 3 estimated attributes
    weaknesses = []
    for attr_name, val in sorted_est[-3:]:
        if val <= 40:  # only report as a weakness if below average
            desc = voice.describe_attribute(attr_name, val, rng)
            weaknesses.append(desc)

    # Marketability + injury risk assessments
    est_market = (market or 50) + random.gauss(0, attr_noise_std)
    est_market = max(1, min(100, int(round(est_market))))
    market_desc = voice.describe_attribute("fight_iq", est_market, rng)  # reuse tier system
    # Actually use a simple descriptor for marketability
    if est_market >= 75:
        market_desc = "strong commercial appeal"
    elif est_market >= 50:
        market_desc = "decent marketability"
    else:
        market_desc = "limited commercial appeal"

    est_inj = (inj_pron or 50) + random.gauss(0, attr_noise_std)
    est_inj = max(1, min(100, int(round(est_inj))))
    if est_inj >= 70:
        injury_desc = "significant injury concern"
    elif est_inj >= 40:
        injury_desc = "moderate injury risk"
    else:
        injury_desc = "durable, low injury risk"

    # Contract cost estimate (based on record + potential)
    total_fights = (wins or 0) + (losses or 0) + (draws or 0)
    contract_est = max(5000, int((est_potential * 1000) + (total_fights * 500)))

    # Scout confidence: higher for better scouts, lower if mistake occurred
    base_confidence = (eye + tech + char_read) / 3
    if mistake_type == "confidence_mismatch":
        # Confidence mismatch: scout is VERY confident despite being wrong
        scout_confidence = min(100, int(base_confidence + 20))
    elif mistake_type:
        scout_confidence = max(20, int(base_confidence - 15))
    else:
        scout_confidence = int(base_confidence)

    # ---- 7. Build the prose report ----
    fighter_name = f"{first} {last}"
    if nick:
        fighter_name += f" '{nick}'"

    report_lines = [
        f"SCOUTING REPORT: {fighter_name}",
        f"Scout: {scout_name}",
        f"Date: {current_date}",
        "",
        f"CEILING: {pot_desc}",
        f"REALISTIC CEILING: {ceiling_desc} (accounting for age, health, and work ethic)",
        f"FLOOR: {floor_desc}",
        "",
    ]
    if strengths:
        report_lines.append(f"STRENGTHS: {', '.join(strengths)}")
    else:
        report_lines.append("STRENGTHS: No standout attributes identified")
    if weaknesses:
        report_lines.append(f"WEAKNESSES: {', '.join(weaknesses)}")
    else:
        report_lines.append("WEAKNESSES: No significant weaknesses identified")
    report_lines.extend([
        "",
        f"MARKETABILITY: {market_desc}",
        f"INJURY RISK: {injury_desc}",
        f"ESTIMATED CONTRACT COST: ${contract_est:,}",
        f"SCOUT CONFIDENCE: {scout_confidence}%",
    ])
    report_text = "\n".join(report_lines)

    # ---- 8. Write to scouting_reports ----
    conn.execute(
        "INSERT INTO scouting_reports (scout_id, target_fighter_id, "
        "promotion_id, report_date, estimated_potential, estimated_ceiling, "
        "estimated_floor, estimated_strengths, estimated_weaknesses, "
        "marketability_assessment, injury_risk_assessment, "
        "contract_cost_estimate, scout_confidence, is_stale, report_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (scout_id, target_fighter_id, promotion_id, current_date,
         pot_desc, ceiling_desc, floor_desc,
         json.dumps(strengths) if strengths else None,
         json.dumps(weaknesses) if weaknesses else None,
         market_desc, injury_desc, contract_est, scout_confidence,
         report_text),
    )

    # ---- 9. Write a news item ----
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
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
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id,
         f"Scouting report filed on {fighter_name}",
         f"{scout_name} has filed a scouting report on {fighter_name}. "
         f"The report estimates a {pot_desc} with {ceiling_desc} realistic ceiling. "
         f"Confidence: {scout_confidence}%.",
         "neutral", "scouting", target_fighter_id, current_date),
    )

    # Phase A5 — publish SCOUT_REPORT_GENERATED on the event bus.
    # The news engine subscribes to write a richer scouting news item
    # (the inline item above has raw confidence %; the event-driven
    # item uses voice descriptors per §14). Lazy import to avoid any
    # circular dependency.
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.SCOUT_REPORT_GENERATED,
            'fighter_id': target_fighter_id,
            'scout_id': scout_id,
            'promotion_id': promotion_id,
            'current_date': current_date,
            'event_date': current_date,
        })
    except ImportError:
        pass


def mark_stale_reports(conn, fighter_id):
    """Mark all scouting reports for a fighter as stale.

    Called when a fighter's state meaningfully changes (camp completion,
    fight resolution, injury, etc.). Stale reports show a warning in
    the UI but remain readable.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter whose reports to mark stale.
    """
    conn.execute(
        "UPDATE scouting_reports SET is_stale=1, updated_at=CURRENT_TIMESTAMP "
        "WHERE target_fighter_id=? AND is_stale=0",
        (fighter_id,),
    )
