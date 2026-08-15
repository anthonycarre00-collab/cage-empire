"""CAGE EMPIRE Rival AI — Promotion Archetypes (Task ID RIVAL-AI-P1, Phase 1).

The 4-archetype system specified in docs/RIVAL_AI_ARCHITECTURE.md §2.
Each rival promotion is assigned ONE archetype at first AI tick (and
re-evaluated quarterly per §3.7 — re-eval is Phase 4, not Phase 1).
The archetype drives every decision axis via the per-axis constants
in `ARCHETYPES` below.

The 4 archetypes:
    major_league     — Big budget, prestige-focused, marquee events,
                       signs established stars. Bi-weekly cadence.
                       Example: Rival Fight League (mid-tier + $15M
                       cash + rep 65 — qualifies as Major League per
                       §2.4 mapping; mid-tier with major-tier cash).

    regional_power   — Medium budget, development-focused, scouts +
                       develops prospects, sells high. Monthly cadence.
                       Example: Pacific Rim Championship, European
                       Fight Network.

    grassroots       — Small budget, survival-focused, short-term
                       deals, cast-offs. Quarterly cadence.
                       Example: Nordic Fight Nights, Australian
                       Outback Fights, French Savate Championship.

    rising_star      — Ambitious, aggressive growth, willing to
                       overspend for a breakthrough. Monthly cadence
                       with risky matchmaking. Assigned dynamically
                       when a small promo has cash >= $3M AND
                       ai_aggression >= 55.
                       Example: Mexican Boxing & Brawl, Eastern Bloc
                       Combat, South American Warriors.

ARCHETYPE ASSIGNMENT RULES (per §2.3 + §2.4 mapping table):
    - size_tier == 'major' + cash >= $10M           → major_league
    - size_tier == 'major' (cash-strapped)           → major_league if rep >= 70 else regional_power
    - size_tier == 'mid' + cash >= $15M + rep >= 60  → major_league
                                                       (RFL qualifies; Pacific Rim/EFN
                                                       fall through to regional_power)
    - size_tier == 'mid' (other)                     → regional_power
    - size_tier == 'small' + ai_aggression >= 55
                       + cash >= $3M                 → rising_star
    - size_tier == 'small' (other)                   → grassroots
    - default                                         → grassroots (defensive)

The mid-tier "major_league" threshold (cash >= $15M + rep >= 60)
matches the §2.4 mapping table exactly: only RFL ($15M, rep 65)
qualifies, while Pacific Rim ($12M, rep 60) and European Fight
Network ($10M, rep 62) fall through to regional_power. This
produces the mix the architecture doc specifies:
    2 major_league  (Alpha Combat [player], RFL)
    2 regional_power (Pacific Rim, European Fight Network)
    3 rising_star   (Mexican Boxing & Brawl, Eastern Bloc, South American Warriors)
    3 grassroots    (Nordic, Australian, French Savate)

PER-AXIS CONSTANTS (per §2.2 of the arch doc). Each archetype is a
frozen dict — frozen so callers can't accidentally mutate the shared
constant. The keys are the decision-axis knobs that Phase 2-4 modules
will read:
    event_cadence_days         — bi-weekly/monthly/quarterly
    event_window_days          — (min, max) day offset for event_date
    card_size                  — (min, max) fights per card
    main_event_title_pct       — 0..1 fraction of main events that are title fights
    matchmaking_safe_pct       — 0..1 fraction of "optimal" matchups
    signing_potential_floor    — minimum potential for FA signing
    signing_age_max            — maximum age for FA signing (None = no cap)
    bid_premium_pct            — ±fraction above/below fair value in bidding wars
    staff_target               — dict of role → target headcount
    budget_allocation          — dict of category → fraction of cash
    cut_aggressiveness         — 0..1 chance to cut an eligible fighter per month
    whimsy_pct                 — 0..1 fraction of "whim" decisions

These constants are READ by Phase 2-4 modules; Phase 1 only writes
them + assigns the archetype. Phase 2's event_scheduler.py will read
`event_cadence_days` + `event_window_days` + `card_size`, etc.

CONVENTIONS compliance:
  §5  — No new tables. The archetype is stored in the existing
        `promotions.ai_archetype` column (added by the v3.14.0
        migration). The scheduling day is stored in
        `promotions.ai_scheduling_day_of_week`.
  §14 — Voice Layer: archetypes are internal — the player doesn't
        see "Major League" in the UI (per arch doc §Q6 default
        assumption). The player infers a promo's behaviour from
        its actions.
  §15 — Event Bus: N/A — `assign_all_archetypes` is called directly
        from `src/rival_ai.py`'s TICK_ADVANCED subscriber on the
        first tick. Phase 4 will add `PROMOTION_RECLASSIFIED` event
        publication on quarterly re-eval.
  §16 — Migration: the v3.14.0 migration calls `assign_all_archetypes`
        is NOT done at migration time — instead, the migration leaves
        `ai_archetype` NULL and the first TICK_ADVANCED subscriber
        call assigns them. This keeps the migration idempotent + the
        archetype assignment testable in isolation.
"""

# ----------------------------------------------------------------
# The 4 archetype definitions (per arch doc §2.2).
#
# Frozen via MappingProxyType so a buggy Phase 2 module can't mutate
# the shared constant. Each value is a plain dict literal matching
# the spec in §2.2 of the architecture doc.
# ----------------------------------------------------------------

from types import MappingProxyType


_ARCHETYPE_MAJOR_LEAGUE = {
    "event_cadence_days":      14,            # bi-weekly
    "event_window_days":       (14, 35),      # pick event_date in [today+14, today+35]
    "card_size":               (10, 13),      # major-tier card
    "main_event_title_pct":    0.70,          # 70% of main events are title fights
    "matchmaking_safe_pct":    0.75,          # 75% safe, 20% showcase, 5% head-scratcher
    "signing_potential_floor": 70,
    "signing_age_max":         33,
    "bid_premium_pct":         0.30,          # will bid up to 130% of fair value
    "staff_target":            {"scout": 3, "commentator": 3, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.55, "staff": 0.10,
                                "venue": 0.20, "marketing": 0.10, "reserve": 0.05},
    "cut_aggressiveness":      0.40,          # 40% chance to cut an eligible underperformer per month
    "whimsy_pct":              0.05,          # 5% of decisions are whims
}

_ARCHETYPE_REGIONAL_POWER = {
    "event_cadence_days":      28,
    "event_window_days":       (21, 45),
    "card_size":               (7, 9),
    "main_event_title_pct":    0.50,
    "matchmaking_safe_pct":    0.65,          # 65% safe, 25% showcase, 10% head-scratcher
    "signing_potential_floor": 60,
    "signing_age_max":         28,
    "bid_premium_pct":         0.00,          # bids fair value, walks away above
    "staff_target":            {"scout": 2, "commentator": 2, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.50, "staff": 0.12,
                                "venue": 0.18, "marketing": 0.10, "reserve": 0.10},
    "cut_aggressiveness":      0.30,
    "whimsy_pct":              0.08,
}

_ARCHETYPE_GRASSROOTS = {
    "event_cadence_days":      84,
    "event_window_days":       (45, 75),
    "card_size":               (5, 6),
    "main_event_title_pct":    0.20,
    "matchmaking_safe_pct":    0.85,          # 85% safe, 10% showcase, 5% head-scratcher
    "signing_potential_floor": 30,
    "signing_age_max":         None,          # no age cap — will sign 38yo cast-offs
    "bid_premium_pct":         -0.20,         # bids 80% of fair value, walks instantly above
    "staff_target":            {"scout": 1, "commentator": 1, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.45, "staff": 0.08,
                                "venue": 0.25, "marketing": 0.05, "reserve": 0.17},
    "cut_aggressiveness":      0.50,
    "whimsy_pct":              0.10,
}

_ARCHETYPE_RISING_STAR = {
    "event_cadence_days":      28,
    "event_window_days":       (14, 35),
    "card_size":               (7, 9),
    "main_event_title_pct":    0.65,          # books title fights earlier than ranking justifies
    "matchmaking_safe_pct":    0.50,          # 50% safe, 30% showcase, 20% head-scratcher (aggressive)
    "signing_potential_floor": 65,
    "signing_age_max":         25,
    "bid_premium_pct":         0.60,          # will bid 160% of fair value (overspend tolerated)
    "staff_target":            {"scout": 3, "commentator": 2, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.60, "staff": 0.15,
                                "venue": 0.15, "marketing": 0.08, "reserve": 0.02},
    "cut_aggressiveness":      0.35,
    "whimsy_pct":              0.12,
}


# The public ARCHETYPES dict — frozen views of the 4 archetype dicts.
# Callers should treat these as read-only constants.
ARCHETYPES = MappingProxyType({
    "major_league":    MappingProxyType(_ARCHETYPE_MAJOR_LEAGUE),
    "regional_power":  MappingProxyType(_ARCHETYPE_REGIONAL_POWER),
    "grassroots":      MappingProxyType(_ARCHETYPE_GRASSROOTS),
    "rising_star":     MappingProxyType(_ARCHETYPE_RISING_STAR),
})


# Friendly display names (for the "[rival_ai] Assigned archetypes:"
# print on first run). Maps the internal snake_case key to the
# Title Case display name used in the arch doc.
ARCHETYPE_DISPLAY_NAMES = MappingProxyType({
    "major_league":   "Major League",
    "regional_power": "Regional Power",
    "grassroots":     "Grassroots",
    "rising_star":    "Rising Star",
})


# Player promotion — the AI never assigns an archetype to the player's
# promo (Alpha Combat, promotion_id=1). The player controls their own
# strategy; the archetype column stays NULL for the player's promo.
# Mirrors `PLAYER_PROMOTION_ID` in src/rival_ai.py.
PLAYER_PROMOTION_ID = 1


# ----------------------------------------------------------------
# Assignment logic
# ----------------------------------------------------------------

def _determine_archetype(size_tier, current_cash, reputation, ai_aggression):
    """Pure function: derive the archetype key from promo attributes.

    Implements the rules in §2.3 + the §2.4 mapping table. See the
    module docstring for the exact threshold breakdown.

    Args:
        size_tier:    promotions.size_tier ('major' / 'mid' / 'small').
        current_cash: promotions.current_cash (REAL, may be None).
        reputation:   promotions.reputation (0-100, may be None).
        ai_aggression: promotions.ai_aggression (0-100, may be None).

    Returns:
        One of 'major_league' / 'regional_power' / 'grassroots' /
        'rising_star'. Defaults to 'grassroots' for unknown size_tier
        or missing attributes (defensive — the seed guarantees all 4
        columns are populated, but defensive coding is cheaper than
        a crash).
    """
    # Defensive coercion — None / NaN / negative cash all collapse to 0.
    cash = float(current_cash) if current_cash is not None else 0.0
    rep = int(reputation) if reputation is not None else 0
    aggr = int(ai_aggression) if ai_aggression is not None else 0

    # Major tier: well-funded → major_league
    if size_tier == 'major' and cash >= 10_000_000:
        return 'major_league'
    # Major tier cash-strapped → major_league if high reputation else regional_power
    if size_tier == 'major':
        return 'major_league' if rep >= 70 else 'regional_power'
    # Mid tier: well-funded (≥ $15M) + reputation ≥ 60 → major_league
    # (matches §2.4 mapping: RFL qualifies; Pacific Rim/EFN are regional_power)
    if size_tier == 'mid':
        if cash >= 15_000_000 and rep >= 60:
            return 'major_league'
        return 'regional_power'
    # Small tier: aggressive + cash >= $3M → rising_star
    if size_tier == 'small':
        if aggr >= 55 and cash >= 3_000_000:
            return 'rising_star'
        return 'grassroots'
    # Defensive default for unknown size_tier (shouldn't happen —
    # the seed guarantees 'major'/'mid'/'small').
    return 'grassroots'


def _determine_scheduling_day(promotion_id):
    """Return the day-of-week (1-7, Mon-Sun) for a rival promotion.

    Round-robin assignment: rival promos have promotion_id 2..10 (9
    promos). Day = ((promotion_id - 2) % 7) + 1, which spreads them
    across 7 days as 2/2/1/1/1/1/1 — within the §4.2 goal of "1-2
    promos per day". Sample:
        promo 2  → day 1 (Mon)
        promo 3  → day 2 (Tue)
        promo 4  → day 3 (Wed)
        promo 5  → day 4 (Thu)
        promo 6  → day 5 (Fri)
        promo 7  → day 6 (Sat)
        promo 8  → day 7 (Sun)
        promo 9  → day 1 (Mon)
        promo 10 → day 2 (Tue)

    Args:
        promotion_id: the rival promotion's promotion_id (int >= 2).

    Returns:
        Integer 1-7. For promotion_id < 2 (shouldn't happen for rival
        promos) returns 1 (defensive).
    """
    if promotion_id is None or promotion_id < 2:
        return 1
    return ((promotion_id - 2) % 7) + 1


def assign_archetype(promotion_id, conn):
    """Assign + persist the archetype for a single promotion.

    Reads the promotion's (size_tier, current_cash, reputation,
    ai_aggression), derives the archetype via `_determine_archetype`,
    and UPDATEs `promotions.ai_archetype` +
    `promotions.ai_scheduling_day_of_week` +
    `promotions.ai_budget_state='NORMAL'` (the default starting state;
    Phase 3's budget_manager will adjust it).

    Idempotent: safe to call on a promo that already has an archetype
    (re-evaluates and overwrites — Phase 4's quarterly re-eval will
    use this). The caller commits.

    Args:
        promotion_id: the promotion to assign (int).
        conn:         sqlite3.Connection (caller commits).

    Returns:
        The archetype key string ('major_league' / 'regional_power' /
        'grassroots' / 'rising_star'). Returns None if the promo
        doesn't exist.
    """
    row = conn.execute(
        "SELECT size_tier, current_cash, reputation, ai_aggression "
        "FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if row is None:
        return None
    size_tier, current_cash, reputation, ai_aggression = row
    archetype = _determine_archetype(size_tier, current_cash, reputation, ai_aggression)
    scheduling_day = _determine_scheduling_day(promotion_id)
    conn.execute(
        "UPDATE promotions "
        "SET ai_archetype=?, ai_scheduling_day_of_week=?, "
        "    ai_budget_state=COALESCE(ai_budget_state, 'NORMAL'), "
        "    updated_at=CURRENT_TIMESTAMP "
        "WHERE promotion_id=?",
        (archetype, scheduling_day, promotion_id),
    )
    return archetype


def get_archetype(promotion_id, conn):
    """Return the archetype dict for a promotion.

    Reads `promotions.ai_archetype`. If NULL (not yet assigned),
    calls `assign_archetype` to assign one on the fly, then returns
    the corresponding dict from `ARCHETYPES`.

    Args:
        promotion_id: the promotion to look up (int).
        conn:         sqlite3.Connection (caller commits if assignment
                      is triggered).

    Returns:
        The frozen archetype dict (one of the 4 in `ARCHETYPES`), or
        None if the promotion doesn't exist. The dict is read-only
        (MappingProxyType) — callers must not attempt to mutate it.
    """
    row = conn.execute(
        "SELECT ai_archetype FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if row is None:
        return None
    archetype_key = row[0]
    if archetype_key is None:
        # Not yet assigned — assign on the fly. This is the
        # "lazy assignment" path for the rare case where a promo is
        # created mid-game (future seed scripts, regen, etc.) and
        # hasn't been picked up by assign_all_archetypes yet.
        archetype_key = assign_archetype(promotion_id, conn)
        if archetype_key is None:
            return None
    return ARCHETYPES.get(archetype_key)


def assign_all_archetypes(conn):
    """Assign archetypes to ALL rival promotions (skips the player's).

    Iterates every promotion with promotion_id != PLAYER_PROMOTION_ID
    whose ai_archetype IS NULL, calls `assign_archetype` for each, and
    prints a one-line summary of the assignments:

        [rival_ai] Assigned archetypes: RFL=Major League, Pacific Rim=Regional Power, ...

    Idempotent: promos that already have ai_archetype set are skipped
    (Phase 4's quarterly re-eval will use `assign_archetype` directly
    to force re-evaluation; this function is the first-run backfill).

    Args:
        conn: sqlite3.Connection (caller commits).

    Returns:
        Dict mapping promotion_id (int) → archetype_key (str) for
        every promo that was assigned on this call. Empty dict if
        all rival promos already had archetypes.
    """
    rows = conn.execute(
        "SELECT promotion_id, name FROM promotions "
        "WHERE promotion_id != ? AND ai_archetype IS NULL "
        "ORDER BY promotion_id ASC",
        (PLAYER_PROMOTION_ID,),
    ).fetchall()

    assignments = {}
    for promo_id, name in rows:
        archetype_key = assign_archetype(promo_id, conn)
        if archetype_key is not None:
            assignments[promo_id] = (name, archetype_key)

    if assignments:
        # Build the friendly "[rival_ai] Assigned archetypes: ..." print.
        # Uses ARCHETYPE_DISPLAY_NAMES so the output reads "Major League"
        # instead of "major_league". Short promo names (drop "Federation"
        # / "Championship" suffixes where present, to keep the line tidy).
        parts = []
        for promo_id, (name, archetype_key) in assignments.items():
            short = _short_promo_name(name)
            display = ARCHETYPE_DISPLAY_NAMES.get(archetype_key, archetype_key)
            parts.append(f"{short}={display}")
        print("[rival_ai] Assigned archetypes: " + ", ".join(parts))

    return {pid: key for pid, (_, key) in assignments.items()}


def _short_promo_name(name):
    """Return a shortened promotion name for the print line.

    Drops common suffixes ("Federation", "Championship", "Fight
    League") so the print fits on one line. Special-case: "Rival
    Fight League" → "RFL" (the brief's expected abbreviation).
    Falls back to the full name if no suffix matches.

        "Alpha Combat Federation"     → "Alpha Combat"
        "Pacific Rim Championship"    → "Pacific Rim"
        "Rival Fight League"          → "RFL"  (special case)
        "Mexican Boxing & Brawl"      → "Mexican Boxing & Brawl" (no suffix)

    This is presentation-only — the DB stores the full name.
    """
    if not name:
        return "?"
    # Special case: "Rival Fight League" → "RFL" (brief's expected
    # abbreviation, matches the league's common initialism).
    if name == "Rival Fight League":
        return "RFL"
    for suffix in (" Fight League", " Federation", " Championship",
                   " Combat", " Fights", " Nights"):
        if name.endswith(suffix) and len(name) > len(suffix) + 3:
            return name[:-len(suffix)]
    return name
