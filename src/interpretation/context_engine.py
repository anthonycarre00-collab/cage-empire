"""CAGE EMPIRE Context Engine (Phase 2 Task 2.2).

Computes momentum, pressure, and trajectory for every active fighter.
Pure functions of DB state — NO RNG, NO text, NO DB writes. The pure
`compute_*` functions return canonical label strings. The bulk-load
helpers (`compute_all_fighters`, `compute_single_fighter`) write the
labels + voice phrases to `fighter_descriptors`.

Per CONVENTIONS §17.4 ("Rich Not Thin"): each cache column stores
BOTH the canonical label AND a voice phrase, separated by `||`:
    "high||riding a hot streak"
The UI reads the voice phrase (after the `||`); the interpretation
engine's rules + tests read the canonical label (before the `||`).

Per CONVENTIONS §17.5: `compute_all_fighters` uses the bulk-load
pattern demonstrated by `career_arc._process_career_arc`:
  1. ONE SELECT (fighters JOIN fighter_career JOIN rankings JOIN
     titles JOIN contracts) — fetch all 4450 active fighters in one
     go. Plus ONE extra SELECT for rank-position computation (per
     weight_class × promotion). Two queries total — NOT N+1.
  2. Python loop — pure CPU, no DB calls inside the loop.
  3. `conn.executemany("UPDATE fighter_descriptors SET ...")` —
     one batched write.
Target: <1 second for 4450 active fighters.

Per CONVENTIONS §17.1: this module writes ONLY to `fighter_descriptors`
(a cache table). It NEVER writes to simulation tables (fighters,
fighter_career, rankings, titles, contracts, etc.).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Use proper rank computation (sort by rating DESC within
      weight_class × promotion) instead of a rating > 1050 heuristic.
      Two SELECTs total — main fighter JOIN + a small rankings-only
      SELECT for the rank map. This is still the bulk-load pattern
      (NOT N+1 — only 2 queries regardless of fighter count).
  D2  Store canonical label AND voice phrase in the same column,
      separated by "||" (per §17.4). Format: "label||voice phrase".
  D3  RNG seeded by fighter_id (`Random(fighter_id * 31 + 17)`) so
      each fighter's voice phrase is DETERMINISTIC. The same fighter
      always gets the same phrase across daily passes — no flickering
      in the UI. The pure compute_* functions NEVER touch RNG.
  D4  Skip inactive OR retired fighters (is_active=0 OR is_retired=1)
      — those rows keep their NULL momentum/pressure. The UI doesn't
      list them on the active roster anyway.
  D5  Filter contracts by `status='active'` when joining. An expired
      contract shouldn't inflate pressure (the fighter is a free
      agent now — captured by the `is_free_agent` factor instead).
  D6  No trajectory column. The v3.10.0 schema only added momentum +
      pressure columns. Trajectory is a derived label that other
      engines (narrative_families, legacy_engine) compute on-demand
      from momentum + age via the pure `compute_trajectory` function
      exposed here. We DON'T store it.
  D7  Bumped snapshot_cache.ENGINE_VERSION to "1.1.0" — the cache
      must rebuild on first run after this code lands (the 6 columns
      start NULL; the daily pass fills them).
  D8  Defensive age handling — if DOB is missing or unparseable,
      default to age 28 (prime). This avoids crashing the daily pass
      on bad data; the descriptor ends up "stable" which is a safe
      fallback.
  D9  Pressure factor for "ranked in top 10": if the fighter has no
      rankings row at all (unranked), they're NOT in the top 10 —
      no pressure factor added. This matches real-world semantics
      (an unranked fighter has no expectations).
"""
import random
import sqlite3
from datetime import datetime


# ============================================================
# CANONICAL LABEL CONSTANTS
# ============================================================
# These are the canonical labels stored BEFORE the "||" separator in
# fighter_descriptors.{momentum, pressure}. Tests read these. UI
# readers parse the voice phrase AFTER "||".

MOMENTUM_VERY_HIGH = "very_high"
MOMENTUM_HIGH = "high"
MOMENTUM_STABLE = "stable"
MOMENTUM_FALLING = "falling"
MOMENTUM_COLLAPSING = "collapsing"

PRESSURE_MINIMAL = "minimal"
PRESSURE_MODERATE = "moderate"
PRESSURE_HIGH = "high"
PRESSURE_EXTREME = "extreme"

TRAJECTORY_RISING = "rising"
TRAJECTORY_PEAKING = "peaking"
TRAJECTORY_STABLE = "stable"
TRAJECTORY_DECLINING = "declining"
TRAJECTORY_COLLAPSING = "collapsing"


# ============================================================
# VOICE PHRASES (per §17.4 — "Rich Not Thin" principle)
# ============================================================
# Each canonical label maps to 3 voice phrase variants. The phrase is
# what the UI displays; the label is what logic/tests read.
#
# Phrases follow CAGE EMPIRE voice: gritty, journalistic, present-
# tense, no digits (CONVENTIONS §14). The variants add variety so
# two fighters with the same momentum label don't always read
# identically — but the SAME fighter always gets the SAME variant
# (RNG seeded by fighter_id, per D3).

MOMENTUM_PHRASES = {
    "very_high":  [
        "riding a blistering hot streak",
        "on fire and unstoppable right now",
        "the division is on notice",
    ],
    "high":       [
        "riding a hot streak",
        "building serious momentum",
        "trending upward fast",
    ],
    "stable":     [
        "holding steady",
        "form has been consistent",
        "neither hot nor cold right now",
    ],
    "falling":    [
        "sliding in the wrong direction",
        "needs to turn things around",
        "form is dipping",
    ],
    "collapsing": [
        "in freefall",
        "the wheels are coming off",
        "desperately needs a win",
    ],
}

PRESSURE_PHRASES = {
    "minimal":  [
        "no real pressure right now",
        "playing with house money",
        "carefree and loose",
    ],
    "moderate": [
        "some pressure to perform",
        "needs to stay on track",
        "moderate expectations to meet",
    ],
    "high":     [
        "under real pressure",
        "the heat is on",
        "needs a big performance soon",
    ],
    "extreme":  [
        "fighting for their career",
        "do-or-die situation",
        "maximum pressure, back against the wall",
    ],
}

TRAJECTORY_PHRASES = {
    "rising":     [
        "a rising star on the way up",
        "trajectory pointing straight up",
        "the best is yet to come",
    ],
    "peaking":    [
        "at the peak of their powers",
        "in their prime right now",
        "as good as they will ever be",
    ],
    "stable":     [
        "holding their ground",
        "neither rising nor falling",
        "a steady hand",
    ],
    "declining":  [
        "past their best days",
        "the decline has begun",
        "father time is winning",
    ],
    "collapsing": [
        "falling apart fast",
        "the end feels near",
        "a career in rapid decline",
    ],
}


# ============================================================
# CANONICAL LABEL ↔ VOICE PHRASE HELPERS
# ============================================================

def encode(label, phrase):
    """Encode a canonical label + voice phrase into the storage format.

    Per §17.4, the cache column stores "label||voice phrase". The UI
    reads the part AFTER `||`; the logic reads the part BEFORE.
    """
    return f"{label}||{phrase}"


def decode_label(stored_value):
    """Decode the canonical label from a stored "label||phrase" value.

    Returns None if the value is NULL or doesn't contain "||".
    Used by tests + logic that needs the canonical label.
    """
    if not stored_value or "||" not in stored_value:
        return None
    return stored_value.split("||", 1)[0]


def decode_phrase(stored_value):
    """Decode the voice phrase from a stored "label||phrase" value.

    Returns None if the value is NULL or doesn't contain "||".
    Used by UI readers that display the voice phrase.
    """
    if not stored_value or "||" not in stored_value:
        return None
    return stored_value.split("||", 1)[1]


def get_momentum_phrase(momentum, rng=None):
    """Pick a voice phrase for the momentum label (per §17.4).

    Args:
        momentum: canonical momentum label.
        rng: optional random.Random for deterministic selection. If
            None, uses the global random (NOT deterministic — caller
            should pass an rng seeded by fighter_id for stable
            phrases across daily passes).

    Returns:
        A voice phrase string. Falls back to the "stable" variants
        if the label is unrecognized (defensive — should not happen).
    """
    if rng is None:
        rng = random
    variants = MOMENTUM_PHRASES.get(momentum, MOMENTUM_PHRASES[MOMENTUM_STABLE])
    return rng.choice(variants)


def get_pressure_phrase(pressure, rng=None):
    """Pick a voice phrase for the pressure label (per §17.4)."""
    if rng is None:
        rng = random
    variants = PRESSURE_PHRASES.get(pressure, PRESSURE_PHRASES[PRESSURE_MODERATE])
    return rng.choice(variants)


def get_trajectory_phrase(trajectory, rng=None):
    """Pick a voice phrase for the trajectory label (per §17.4).

    Trajectory isn't stored in a column (D6) — this helper is for
    engines (narrative_families, legacy_engine) that surface trajectory
    phrases inline in their own output.
    """
    if rng is None:
        rng = random
    variants = TRAJECTORY_PHRASES.get(trajectory, TRAJECTORY_PHRASES[TRAJECTORY_STABLE])
    return rng.choice(variants)


# ============================================================
# COMPUTE FUNCTIONS — pure, no DB, no RNG
# ============================================================
# These are the canonical label computers. They take primitive inputs
# (ints, bools) and return canonical label strings. No DB access, no
# RNG. The DB-write helpers (compute_all_fighters,
# compute_single_fighter) call these after loading the inputs.

def compute_momentum(win_streak, loss_streak):
    """Compute momentum from current win/loss streaks.

    Tiers (per spec §12):
      very_high   — win_streak >= 5
      high        — win_streak >= 3 (and < 5)
      collapsing  — loss_streak >= 4 (and win_streak < 3)
      falling     — loss_streak >= 2 (and win_streak < 3, loss_streak < 4)
      stable      — win_streak 0-2 AND loss_streak 0-1

    Win streak takes precedence over loss streak (a fighter on a
    5-fight win streak who happens to have a 2-fight loss streak
    before that is still "very_high" — the streak is what's current).

    Args:
        win_streak: int (>= 0). Current consecutive wins.
        loss_streak: int (>= 0). Current consecutive losses.

    Returns:
        Canonical momentum label string.
    """
    win_streak = win_streak or 0
    loss_streak = loss_streak or 0
    if win_streak >= 5:
        return MOMENTUM_VERY_HIGH
    if win_streak >= 3:
        return MOMENTUM_HIGH
    if loss_streak >= 4:
        return MOMENTUM_COLLAPSING
    if loss_streak >= 2:
        return MOMENTUM_FALLING
    return MOMENTUM_STABLE


def compute_pressure(fighter_data):
    """Compute pressure from multiple factors.

    Per spec §13, pressure is derived from:
      contract, ranking, recent losses, expectations, age, etc.

    Eight factors (each adds 1):
      1. Contract expiring within 60 days.
      2. Age >= 35 (veteran pressure — father time).
      3. Loss streak >= 3 (sliding — needs a win urgently).
      4. Ranked in top 10 of their division (expectations).
      5. Career health < 50 (body is failing).
      6. Is champion (title pressure — everyone wants the belt).
      7. Free agent (no contract — career survival pressure).
      8. Win streak >= 5 but age >= 30 (window closing pressure).

    Tier mapping:
      0 factors  → minimal
      1-2        → moderate
      3-4        → high
      5+         → extreme

    Args:
        fighter_data: dict with keys (see D-number comments in the
            module docstring for default handling):
              contract_days_remaining (int or None)
              age (int)
              loss_streak (int)
              rank (int or None — None = unranked)
              career_health (int)
              is_champion (bool)
              is_free_agent (bool)
              win_streak (int)

    Returns:
        Canonical pressure label string.
    """
    factors = 0

    # 1. Contract expiring within 60 days.
    cdr = fighter_data.get("contract_days_remaining")
    if cdr is not None and cdr <= 60:
        factors += 1

    # 2. Age >= 35 (veteran pressure).
    age = fighter_data.get("age", 0) or 0
    if age >= 35:
        factors += 1

    # 3. Loss streak >= 3 (sliding).
    if (fighter_data.get("loss_streak", 0) or 0) >= 3:
        factors += 1

    # 4. Ranked in top 10 (expectations).
    rank = fighter_data.get("rank")
    if rank is not None and rank <= 10:
        factors += 1

    # 5. Career health < 50 (body failing).
    if (fighter_data.get("career_health", 100) or 100) < 50:
        factors += 1

    # 6. Is champion (title pressure).
    if fighter_data.get("is_champion", False):
        factors += 1

    # 7. Free agent (no active contract — career survival).
    if fighter_data.get("is_free_agent", False):
        factors += 1

    # 8. Win streak >= 5 but age >= 30 (window closing).
    if (fighter_data.get("win_streak", 0) or 0) >= 5 and age >= 30:
        factors += 1

    if factors >= 5:
        return PRESSURE_EXTREME
    if factors >= 3:
        return PRESSURE_HIGH
    if factors >= 1:
        return PRESSURE_MODERATE
    return PRESSURE_MINIMAL


def compute_trajectory(momentum, age):
    """Compute trajectory from momentum + age.

    Per spec §3 (Context Engine examples):
      rising     — momentum (very_high, high) AND age < 30
      peaking    — momentum (very_high, high) AND age 30-34
      stable     — momentum = stable
      declining  — momentum (falling, collapsing) OR age >= 35
      collapsing — momentum = collapsing AND age >= 35

    Note: the collapsing trajectory is the most specific — it
    requires BOTH collapsing momentum AND age >= 35. A 25-year-old
    on a 4-fight loss streak is "declining" (not collapsing) — they
    have time to turn it around.

    Trajectory isn't stored in a column (D6) — it's a derived label
    that other engines compute on-demand from momentum + age. We
    expose this pure function so they don't reimplement the logic.

    Args:
        momentum: canonical momentum label (e.g. "very_high").
        age: int.

    Returns:
        Canonical trajectory label string.
    """
    age = age or 0
    if momentum in (MOMENTUM_VERY_HIGH, MOMENTUM_HIGH):
        if age < 30:
            return TRAJECTORY_RISING
        if age <= 34:
            return TRAJECTORY_PEAKING
        return TRAJECTORY_DECLINING  # hot streak but past prime
    if momentum == MOMENTUM_COLLAPSING and age >= 35:
        return TRAJECTORY_COLLAPSING
    if momentum == MOMENTUM_STABLE:
        return TRAJECTORY_STABLE
    # falling, collapsing (age < 35), or unrecognized momentum
    return TRAJECTORY_DECLINING


# ============================================================
# HELPERS — age + rank-position computation
# ============================================================

def _compute_age(dob_str, current_date_str):
    """Compute a fighter's age as of current_date.

    Mirrors career_arc._compute_age. Returns 28 (prime) as a
    defensive default for missing/invalid DOB (D8) — keeps the
    daily pass from crashing on bad data.
    """
    if not dob_str or not current_date_str:
        return 28
    try:
        dob = datetime.strptime(dob_str[:10], "%Y-%m-%d")
        cur = datetime.strptime(current_date_str[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return 28
    age = cur.year - dob.year
    if (cur.month, cur.day) < (dob.month, dob.day):
        age -= 1
    return age


def _compute_contract_days_remaining(contract_end_str, current_date_str):
    """Days remaining on a fighter's active contract.

    Returns None if no end_date or unparseable. Negative values are
    kept — they indicate the contract has technically expired (the
    `status='active'` filter in the SELECT should prevent this, but
    we keep the value for safety).
    """
    if not contract_end_str or not current_date_str:
        return None
    try:
        end_dt = datetime.strptime(contract_end_str[:10], "%Y-%m-%d")
        cur_dt = datetime.strptime(current_date_str[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return (end_dt - cur_dt).days


def _build_rank_map(conn):
    """Build a {(promotion_id, weight_class_id): {fighter_id: rank}} map.

    Per D1: rather than guessing rank from a rating threshold, we
    compute the actual rank position by sorting fighters within each
    (promotion_id, weight_class_id) by rating DESC. The #1 fighter
    in each division gets rank=1, etc.

    Returns:
        dict[(promotion_id, weight_class_id)][fighter_id] = rank_int
        (1-indexed). Fighters without a rankings row are absent from
        the inner dict — callers should default to None (unranked).

    This is ONE SELECT (rankings only) — the bulk-load pattern is
    preserved (2 queries total: this + the main fighter JOIN).
    """
    rows = conn.execute(
        "SELECT fighter_id, weight_class_id, promotion_id, rating "
        "FROM rankings"
    ).fetchall()

    # Group by (promotion_id, weight_class_id).
    groups = {}
    for fighter_id, wc_id, promo_id, rating in rows:
        key = (promo_id, wc_id)
        groups.setdefault(key, []).append((rating or 0.0, fighter_id))

    # Sort each group by rating DESC, assign rank 1..N.
    rank_map = {}
    for key, lst in groups.items():
        lst.sort(key=lambda t: (-t[0], t[1]))  # rating DESC, id ASC tiebreak
        rank_map[key] = {fid: (i + 1) for i, (_, fid) in enumerate(lst)}
    return rank_map


def _build_champion_set(conn):
    """Build a set of fighter_ids who currently hold a non-vacant title.

    Used for the pressure factor "is_champion" — far cheaper than a
    per-fighter subquery in the main SELECT (which would create a
    fan-out via the LEFT JOIN to titles).
    """
    rows = conn.execute(
        "SELECT current_champion_fighter_id FROM titles "
        "WHERE is_vacant = 0 AND current_champion_fighter_id IS NOT NULL"
    ).fetchall()
    return {row[0] for row in rows}


# ============================================================
# BULK COMPUTE + WRITE (called by snapshot_cache.run_daily_pass)
# ============================================================

def compute_all_fighters(conn, current_date=None):
    """Bulk-compute momentum + pressure for all active fighters.

    Uses the bulk-load pattern from career_arc._process_career_arc
    (CONVENTIONS §17.5):
      1. ONE main SELECT (fighters JOIN fighter_career LEFT JOIN
         rankings LEFT JOIN contracts) — fetch all 4450 active
         fighters in one go. Plus ONE extra SELECT for the rank map
         + ONE for the champion set (both small, neither is N+1).
      2. Python loop — pure CPU, no DB calls inside the loop.
      3. conn.executemany("UPDATE fighter_descriptors SET momentum=?, pressure=?") —
         one batched write.

    Per §17.4: each column is written as "label||voice phrase".
    Per D3: the voice phrase is RNG-seeded by fighter_id so it's
    deterministic across daily passes (no UI flickering).

    MUST complete in <1 second for 4450 active fighters (CONVENTIONS
    §17.5).

    Args:
        conn: sqlite3.Connection.
        current_date: optional ISO date string. If None, read from
            simulation_clock (the normal case — caller is the daily
            interpretation pass).

    Returns:
        int — number of fighter_descriptors rows updated (should
        equal the active fighter count).
    """
    # 1. Resolve current_date from simulation_clock if not provided.
    if current_date is None:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        if row is None:
            from datetime import date as _date
            current_date = _date.today().isoformat()
        else:
            current_date = row[0]

    # 2. Bulk-load all active (non-retired) fighters + their career
    #    stats + ranking row + active contract.
    #
    #    Filter contracts by status='active' (D5) — expired contracts
    #    shouldn't inflate pressure (the fighter is now a free agent,
    #    captured by the is_free_agent factor instead).
    #
    #    We do NOT join titles here — a LEFT JOIN to titles would
    #    fan out one row per title held (rare, but possible if a
    #    fighter holds two belts). We compute the champion set
    #    separately (D1 — champion set as a Python set lookup).
    rows = conn.execute(
        """
        SELECT
            f.fighter_id,
            f.date_of_birth,
            f.current_promotion_id,
            fc.win_streak,
            fc.loss_streak,
            fc.career_health,
            r.rating,
            r.weight_class_id,
            r.promotion_id,
            c.end_date
        FROM fighters f
        JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        LEFT JOIN rankings r ON r.fighter_id = f.fighter_id
        LEFT JOIN fighter_contracts fct ON fct.fighter_id = f.fighter_id
        LEFT JOIN contracts c ON c.contract_id = fct.contract_id
                              AND c.status = 'active'
        WHERE f.is_active = 1 AND f.is_retired = 0
        """
    ).fetchall()

    # 3. Build the rank map + champion set ONCE (not per-fighter).
    rank_map = _build_rank_map(conn)
    champion_set = _build_champion_set(conn)

    # 4. Python loop — compute labels + voice phrases.
    updates = []
    for (fighter_id, dob, current_promotion_id, win_streak, loss_streak,
         career_health, rating, wc_id, rank_promo_id, contract_end) in rows:

        # Compute age (defensive default 28 — D8).
        age = _compute_age(dob, current_date)

        # Compute contract days remaining (None if no active contract).
        contract_days = _compute_contract_days_remaining(contract_end, current_date)

        # Compute rank position via the rank_map (None if unranked).
        rank = None
        if rank_promo_id is not None and wc_id is not None:
            rank = rank_map.get((rank_promo_id, wc_id), {}).get(fighter_id)

        # The fighter is a free agent if they have no current promotion
        # (D5: dropped contracts leave current_promotion_id NULL when
        # the contract expires — the tick processor's contract-expiry
        # path clears it).
        is_free_agent = current_promotion_id is None
        is_champion = fighter_id in champion_set

        fighter_data = {
            "contract_days_remaining": contract_days,
            "age": age,
            "loss_streak": loss_streak,
            "rank": rank,
            "career_health": career_health,
            "is_champion": is_champion,
            "is_free_agent": is_free_agent,
            "win_streak": win_streak,
        }

        momentum = compute_momentum(win_streak, loss_streak)
        pressure = compute_pressure(fighter_data)

        # Deterministic RNG per fighter (D3) — same fighter always
        # gets the same voice phrase across daily passes.
        rng = random.Random(fighter_id * 31 + 17)
        momentum_phrase = get_momentum_phrase(momentum, rng)
        pressure_phrase = get_pressure_phrase(pressure, rng)

        updates.append((
            encode(momentum, momentum_phrase),
            encode(pressure, pressure_phrase),
            fighter_id,
        ))

    # 5. Batch UPDATE (one executemany — CONVENTIONS §17.5).
    if updates:
        conn.executemany(
            "UPDATE fighter_descriptors SET momentum=?, pressure=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            updates,
        )
        conn.commit()

    return len(updates)


def compute_single_fighter(conn, fighter_id, current_date=None):
    """Compute momentum + pressure for a single fighter (targeted refresh).

    Called by event-bus subscribers on FIGHT_RESOLVED, FIGHTER_RETIRED,
    TITLE_CHANGED, CONTRACT_EXPIRED (via snapshot_cache.refresh_fighter)
    so the UI shows the up-to-date descriptor immediately, without
    waiting for the next daily pass.

    MUST complete in <10ms (CONVENTIONS §17.5). Uses TARGETED queries
    (not _build_rank_map / _build_champion_set — those load ALL rows
    and would push this above the 10ms budget on a 4500-fighter DB).
    The rank is computed via a single COUNT subquery against rankings;
    the champion check is a single EXISTS subquery against titles.

    Args:
        conn: sqlite3.Connection.
        fighter_id: int.
        current_date: optional ISO date string.

    Returns:
        dict with keys 'momentum' and 'pressure' (canonical labels),
        or None if the fighter doesn't exist.
    """
    if current_date is None:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        current_date = row[0] if row else None
    if not current_date:
        from datetime import date as _date
        current_date = _date.today().isoformat()

    row = conn.execute(
        """
        SELECT
            f.fighter_id,
            f.date_of_birth,
            f.current_promotion_id,
            fc.win_streak,
            fc.loss_streak,
            fc.career_health,
            r.rating,
            r.weight_class_id,
            r.promotion_id,
            c.end_date
        FROM fighters f
        JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
        LEFT JOIN rankings r ON r.fighter_id = f.fighter_id
        LEFT JOIN fighter_contracts fct ON fct.fighter_id = f.fighter_id
        LEFT JOIN contracts c ON c.contract_id = fct.contract_id
                              AND c.status = 'active'
        WHERE f.fighter_id = ?
        """,
        (fighter_id,),
    ).fetchone()

    if not row:
        return None

    (fid, dob, current_promotion_id, win_streak, loss_streak,
     career_health, rating, wc_id, rank_promo_id, contract_end) = row

    age = _compute_age(dob, current_date)
    contract_days = _compute_contract_days_remaining(contract_end, current_date)

    # Compute rank via a targeted COUNT subquery — fighters in the
    # same (promotion_id, weight_class_id) with a strictly higher
    # rating. rank = (#fighters ahead) + 1. None if unranked.
    rank = None
    if rank_promo_id is not None and wc_id is not None and rating is not None:
        ahead = conn.execute(
            "SELECT COUNT(*) FROM rankings "
            "WHERE promotion_id=? AND weight_class_id=? AND rating > ?",
            (rank_promo_id, wc_id, rating),
        ).fetchone()[0]
        rank = ahead + 1

    # Champion check via EXISTS — far cheaper than loading all titles.
    is_champion = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM titles WHERE "
        "current_champion_fighter_id=? AND is_vacant=0)",
        (fid,),
    ).fetchone()[0] == 1

    fighter_data = {
        "contract_days_remaining": contract_days,
        "age": age,
        "loss_streak": loss_streak,
        "rank": rank,
        "career_health": career_health,
        "is_champion": is_champion,
        "is_free_agent": current_promotion_id is None,
        "win_streak": win_streak,
    }

    momentum = compute_momentum(win_streak, loss_streak)
    pressure = compute_pressure(fighter_data)

    rng = random.Random(fighter_id * 31 + 17)
    momentum_phrase = get_momentum_phrase(momentum, rng)
    pressure_phrase = get_pressure_phrase(pressure, rng)

    conn.execute(
        "UPDATE fighter_descriptors SET momentum=?, pressure=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        (encode(momentum, momentum_phrase),
         encode(pressure, pressure_phrase),
         fighter_id),
    )
    conn.commit()

    return {"momentum": momentum, "pressure": pressure}


# ============================================================
# Convenience: compute trajectory for a stored momentum + age.
# Used by narrative_families / legacy_engine (D6).
# ============================================================

def compute_trajectory_for_fighter(conn, fighter_id, current_date=None):
    """Compute trajectory on-demand for a single fighter.

    Per D6, trajectory isn't stored in a column. Engines that need
    it (narrative_families, legacy_engine) call this helper. It
    reads the fighter's stored momentum label + age and applies
    compute_trajectory.

    Args:
        conn: sqlite3.Connection.
        fighter_id: int.
        current_date: optional ISO date string.

    Returns:
        Canonical trajectory label string, or None if the fighter
        doesn't exist / has no stored momentum yet.
    """
    if current_date is None:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        current_date = row[0] if row else None

    row = conn.execute(
        """
        SELECT fd.momentum, f.date_of_birth
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        WHERE fd.fighter_id = ?
        """,
        (fighter_id,),
    ).fetchone()
    if not row:
        return None
    stored_momentum, dob = row
    momentum = decode_label(stored_momentum)
    if momentum is None:
        return None
    age = _compute_age(dob, current_date)
    return compute_trajectory(momentum, age)
