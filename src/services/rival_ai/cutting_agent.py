"""CAGE EMPIRE Rival AI — Cutting Agent (Task ID RIVAL-AI-P2to4, Phase 3).

Per docs/RIVAL_AI_ARCHITECTURE.md §3.4 — fighter cutting with
cut_risk scoring + protective rules (champion / loyalty / prospect /
title-shot protection) + archetype aggressiveness.

Fires MONTHLY (current_day % 28 == 0) on the TICK_ADVANCED
subscriber in src/rival_ai.py. For each rival promo, evaluates the
roster for cut-eligible fighters, applies the protective rules +
archetype aggressiveness roll, and releases the losers.

CONVENTIONS compliance:
  §5  — No new tables. Reads/writes existing `fighters` + `contracts`
        + `fighter_contracts` + `fighter_career` + `fighter_descriptors`
        + `titles` + `events` + `fights` tables only.
  §13 — Design Law: this is the "Empire Builder" pillar — rival promos
        trim dead weight, develop prospects, build their rosters.
  §14 — Voice Layer: news items use direct prose (no raw numbers).
  §15 — Event Bus: publishes FIGHTER_STATE_CHANGED so the morale +
        descriptor cache refresh for released fighters.
"""

import random as _random
from datetime import datetime, timedelta


# Cut-risk threshold (per arch doc §3.4 step 2).
# A fighter with cut_risk >= CUT_RISK_THRESHOLD is "cut-eligible"
# (subject to protective rules). The loyalty_threshold_bonus can
# raise this to LOYALTY_THRESHOLD_BONUS (75) for 24+ month tenure.
CUT_RISK_THRESHOLD = 65
LOYALTY_THRESHOLD_BONUS = 10  # added to threshold for 24+ month tenure

# Whimsy cut chance (per arch doc §6.6 — "going in a different
# direction" cuts). 10% of cuts are head-scratchers (cut_risk < 50).
WHIMSY_CUT_CHANCE = 0.10

# Recency bias multipliers (per arch doc §3.4 step 3 + §6.2).
HIT_EVENT_CUT_MULTIPLIER = 0.8   # hit → loyalty surge (cut less)
FLOP_EVENT_CUT_MULTIPLIER = 1.2  # flop → panic cuts (cut more)


def evaluate_cuts(conn, promotion_id, archetype=None, current_date=None, rng=None):
    """Evaluate the roster for cut-eligible fighters + apply the
    archetype aggressiveness roll.

    Per arch doc §3.4:
      1. For each active fighter on the promo's roster:
         a. Compute cut_risk (0-100).
         b. Apply protective rules (champion / loyalty / prospect /
            title-shot protection).
         c. If cut_risk >= threshold AND no protection applies:
            cut-eligible. Roll rng.random() < archetype.cut_aggressiveness
            to decide whether to actually cut.
      2. For each fighter selected for cutting:
         - UPDATE fighters SET current_promotion_id=NULL.
         - UPDATE contracts SET status='terminated'.
         - Write a 'release' news item.
         - Publish FIGHTER_STATE_CHANGED on the event bus.
      3. Recency bias: if the promo's last event was a flop (rating <
         40), multiply cut_aggressiveness by 1.2 (panic cuts). If hit
         (rating > 75), multiply by 0.8 (loyalty surge).
      4. Whimsy: 10% of cuts are "head-scratcher" cuts — a fighter
         with cut_risk < 50 gets cut anyway.

    Args:
        conn: sqlite3.Connection (caller commits).
        promotion_id: the rival promo evaluating cuts.
        archetype: optional pre-fetched archetype dict.
        current_date: sim date string. Defaults to current sim date.
        rng: optional random.Random instance.

    Returns:
        List of (fighter_id, fighter_name) tuples that were cut.
    """
    rng = rng or _random.Random()
    if current_date is None:
        from services.rival_ai._shared import current_sim_date
        current_date = current_sim_date(conn)
    if not current_date:
        return []

    # Resolve the (state-modified, recency-modified) archetype.
    if archetype is None:
        from services.rival_ai.budget_manager import get_modified_archetype
        _, archetype, budget_state = get_modified_archetype(conn, promotion_id)
        if archetype is None:
            return []
    else:
        from services.rival_ai.budget_manager import get_budget_state
        budget_state = get_budget_state(conn, promotion_id)
    # CRISIS: cut more aggressively (the budget_manager already
    # triggered top-3 salary cuts via _handle_crisis; we still run
    # the normal cut evaluation for additional trim).
    cut_aggr = archetype.get('cut_aggressiveness', 0.30)

    # Fetch all active fighters on the promo's roster with the data
    # we need to compute cut_risk. Batched in a single query (1 round-
    # trip per promo per month — perf-budget-friendly).
    rows = conn.execute(
        "SELECT f.fighter_id, f.first_name || ' ' || f.last_name, "
        "f.date_of_birth, f.weight_class_id, "
        "COALESCE(fc.record_wins, 0), COALESCE(fc.record_losses, 0), "
        "COALESCE(fc.win_streak, 0), COALESCE(fc.loss_streak, 0), "
        "COALESCE(fc.career_health, 100), COALESCE(fc.potential, 50), "
        "COALESCE(fd.momentum, 'unknown'), "
        "c.contract_id, c.salary, c.start_date "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
        "LEFT JOIN fighter_contracts fct ON fct.fighter_id = f.fighter_id "
        "LEFT JOIN contracts c ON c.contract_id = fct.contract_id "
        "AND c.status='active' AND c.promotion_id = f.current_promotion_id "
        "WHERE f.current_promotion_id = ? "
        "AND f.is_active = 1 AND f.is_retired = 0",
        (promotion_id,),
    ).fetchall()

    if not rows:
        return []

    # Fetch champion IDs for this promo (used in champion protection).
    champion_ids = set()
    for (champ_id,) in conn.execute(
        "SELECT current_champion_fighter_id FROM titles "
        "WHERE promotion_id=? AND current_champion_fighter_id IS NOT NULL",
        (promotion_id,),
    ).fetchall():
        champion_ids.add(champ_id)

    # Fetch fighter_ids scheduled for a title fight in the next 60 days
    # (title-shot protection). We check events scheduled in the next
    # 60 days with is_title_fight=1.
    title_shot_ids = set()
    title_shot_rows = conn.execute(
        "SELECT DISTINCT fp.fighter_id FROM fights f "
        "JOIN events e ON e.event_id = f.event_id "
        "JOIN fight_participants fp ON fp.fight_id = f.fight_id "
        "WHERE e.promotion_id = ? AND e.status = 'scheduled' "
        "AND e.event_date <= date(?, '+60 days') "
        "AND f.is_title_fight = 1",
        (promotion_id, current_date),
    ).fetchall()
    for (fid,) in title_shot_rows:
        title_shot_ids.add(fid)

    cut_fighters = []
    for row in rows:
        (fid, fname, dob, wc_id, wins, losses, win_streak, loss_streak,
         career_health, potential, momentum, contract_id, salary,
         contract_start) = row

        # Compute cut_risk.
        age = _age_from_dob(dob, current_date)
        fighter_dict = {
            'fighter_id': fid,
            'age': age,
            'win_streak': win_streak,
            'loss_streak': loss_streak,
            'career_health': career_health,
            'potential': potential,
            'record_wins': wins,
            'momentum': momentum,
        }
        contract_dict = {
            'salary': salary or 0.0,
            'start_date': contract_start,
        }
        cut_risk = _cut_risk_score(fighter_dict, contract_dict)

        # W21/W22 — rival AI memory read: if this fighter recently
        # lost a title for the promo (within the last 180 sim days),
        # bump cut_risk by +20 ("they've peaked — cut them while
        # they still have trade value"). Defensive — reader failures
        # are swallowed + cut_risk is the unmodified score.
        try:
            from services.rival_ai.memory import fighter_has_recent_title_loss
            if fighter_has_recent_title_loss(
                conn, promotion_id, fid, lookback_days=180,
            ):
                cut_risk = min(100.0, cut_risk + 20.0)
        except ImportError:
            pass  # services.rival_ai.memory not available — proceed
        except Exception:
            pass  # defensive — memory read failure MUST NOT block cutting

        # Apply protective rules.
        is_champion = fid in champion_ids
        is_prospect = (age <= 26 and potential >= 70)
        has_title_shot = fid in title_shot_ids
        # Loyalty protection: tenure >= 24 months → threshold +10.
        loyalty_bonus = _loyalty_threshold_bonus(
            conn, fid, promotion_id, contract_start, current_date,
        )
        threshold = CUT_RISK_THRESHOLD + loyalty_bonus

        cut_eligible = (cut_risk >= threshold
                        and not is_champion
                        and not is_prospect
                        and not has_title_shot)

        # Apply the archetype aggressiveness roll.
        if cut_eligible:
            if rng.random() < cut_aggr:
                cut_fighters.append((fid, fname, contract_id))
        else:
            # Whimsy cut: 10% chance to cut a fighter with cut_risk < 50
            # ("going in a different direction"). The whimsy only fires
            # for fighters with cut_risk >= 30 (don't cut productive
            # roster members on a whim).
            if cut_risk < 50 and cut_risk >= 30 and not is_champion:
                from services.rival_ai.imperfection import maybe_whim
                if maybe_whim(archetype, 'cutting', rng):
                    cut_fighters.append((fid, fname, contract_id))

    # Execute the cuts.
    for (fid, fname, contract_id) in cut_fighters:
        _cut_fighter(conn, fid, contract_id, promotion_id, fname, current_date)

    return [(fid, fname) for (fid, fname, _) in cut_fighters]


def _cut_risk_score(fighter_row, contract_row):
    """Compute the 0-100 cut_risk for a single fighter.

    Per arch doc §3.4 step 1:
        cut_risk = 0.30 * loss_streak_factor
                 + 0.25 * age_factor
                 + 0.20 * salary_factor
                 + 0.15 * health_factor
                 + 0.10 * anti_fan_favorite

    Args:
        fighter_row: dict-like (age, win_streak, loss_streak,
            career_health, potential, record_wins, momentum).
        contract_row: dict-like (salary, start_date).

    Returns:
        Float 0..100.
    """
    loss_streak = fighter_row.get('loss_streak', 0)
    loss_streak_factor = min(100, loss_streak * 25)

    age = fighter_row.get('age', 28)
    age_factor = max(0, min(100, (age - 28) * 10))

    salary = float(contract_row.get('salary', 0) or 0)
    salary_factor = max(0, min(100, (salary - 20000) / 1800))

    career_health = fighter_row.get('career_health', 100)
    health_factor = max(0, min(100, (80 - career_health) * 1.67))

    # anti_fan_favorite: 0 if the fighter is a fan favorite
    # (momentum >= 70 OR wins >= 15 OR is current champion — but we
    # check champion separately in evaluate_cuts).
    momentum_str = str(fighter_row.get('momentum', 'unknown')).lower()
    wins = fighter_row.get('record_wins', 0)
    is_fan_favorite = (
        any(w in momentum_str for w in ('surging', 'hot', 'rising', 'elite'))
        or wins >= 15
    )
    anti_fan_favorite = 0 if is_fan_favorite else 100

    cut_risk = (
        0.30 * loss_streak_factor
        + 0.25 * age_factor
        + 0.20 * salary_factor
        + 0.15 * health_factor
        + 0.10 * anti_fan_favorite
    )
    return max(0.0, min(100.0, cut_risk))


def _age_from_dob(dob, current_date):
    """Return age computed from date_of_birth + current_date."""
    if not dob or not current_date:
        return 28
    try:
        dob_dt = datetime.strptime(dob, "%Y-%m-%d")
        cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
        age = cur_dt.year - dob_dt.year
        if (cur_dt.month, cur_dt.day) < (dob_dt.month, dob_dt.day):
            age -= 1
        return age
    except (ValueError, TypeError):
        return 28


def _loyalty_threshold_bonus(conn, fighter_id, promotion_id,
                              contract_start, current_date):
    """Return the +threshold bonus for veteran loyalty.

    Per arch doc §6.3 rule 1: a fighter who has been on the promo's
    roster ≥ 24 months gets +10 to the cut_risk threshold.

    Uses the contract's start_date (passed in) to compute tenure,
    avoiding a redundant DB query (the calling code already fetched
    the contract row).
    """
    if not contract_start or not current_date:
        return 0
    try:
        start_dt = datetime.strptime(contract_start, "%Y-%m-%d")
        cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    tenure_months = (cur_dt.year - start_dt.year) * 12 + (cur_dt.month - start_dt.month)
    if tenure_months >= 24:
        return LOYALTY_THRESHOLD_BONUS
    return 0


def _cut_fighter(conn, fighter_id, contract_id, promotion_id,
                 fighter_name, current_date):
    """Release a fighter — UPDATE fighters + contracts + write news +
    publish FIGHTER_STATE_CHANGED.

    Per arch doc §3.4 step 4:
      - UPDATE fighters SET current_promotion_id=NULL.
      - UPDATE contracts SET status='terminated'.
      - Write a 'release' news item.
      - Publish FIGHTER_STATE_CHANGED on the event bus.
      - W21/W22: write a 'fighter_released' rival_ai_memory row so
        future signing decisions can read it ("we let this one go
        last year — maybe re-sign them now that they're back on the
        market"). Defensive — the memory write is wrapped in
        try/except so a failure can't roll back the cut.
    """
    # 1. UPDATE fighters — remove from roster.
    conn.execute(
        "UPDATE fighters SET current_promotion_id=NULL, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (fighter_id,),
    )
    # 2. UPDATE contracts — terminate.
    if contract_id is not None:
        conn.execute(
            "UPDATE contracts SET status='terminated', "
            "updated_at=CURRENT_TIMESTAMP WHERE contract_id=?",
            (contract_id,),
        )
    # 3. Write the release news item.
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"
    from services.rival_ai._shared import write_news_item
    write_news_item(
        conn,
        headline=f"{fighter_name} released by {promo_name}",
        body=(f"{fighter_name} has been released by {promo_name}. "
              f"The fighter is now a free agent."),
        topic='release',
        sentiment='neutral',
        promotion_id=promotion_id,
        fighter_id=fighter_id,
        published_at=current_date,
    )
    # 4. Publish FIGHTER_STATE_CHANGED (so morale + descriptor cache
    # refresh). Matches the pattern in retirement_svc.
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.FIGHTER_STATE_CHANGED,
            'fighter_id': fighter_id,
            'promotion_id': promotion_id,
            'change': 'released',
            'current_date': current_date,
        })
    except (ImportError, Exception):
        pass  # defensive — event bus failure shouldn't crash the cut
    # 5. W21/W22 — write a 'fighter_released' memory row. Low
    # salience (40) — the fighter is gone, this is mostly a record
    # for future re-signing decisions.
    try:
        from services.rival_ai.memory import record_fighter_released
        record_fighter_released(
            conn, promotion_id, fighter_id, current_date,
        )
    except ImportError:
        pass  # services.rival_ai.memory not available — skip silently
    except Exception:
        pass  # defensive — memory write failure MUST NOT roll back the cut
