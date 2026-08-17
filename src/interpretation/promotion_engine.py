"""Promotion Engine — populates promotion_descriptors cache table.

Per CONVENTIONS §17.1 (Snapshot Rule), Office Mode UI screens must read
from `promotion_descriptors` (the cache table), NOT from the
`promotions` simulation table directly. This engine is the ONLY writer
to `promotion_descriptors`. It runs as part of the daily interpretation
pass (snapshot_cache.run_daily_interpretation_pass →
_interpret_promotions → compute_all_promotion_descriptors) and is
idempotent — INSERT OR REPLACE.

Per CONVENTIONS §14 (Voice Layer — no raw 0-100 numbers in player-
facing UI) + §17.1, the engine derives 3 voice-phrase fields from the
`promotions` table's raw 0-100 reputation + the broadcast_tier /
ownership_type / size_tier categorical fields + the average roster
quality (derived from `fighter_descriptors.overall_desc` joined via
`fighters.current_promotion_id`).

The 3 fields:
  - prestige_desc          voice phrase for reputation tier (6-tier)
  - market_position_desc   voice phrase for broadcast + ownership + size
  - roster_quality_desc    voice phrase for average roster quality tier

Voice phrases follow the same tier system as the helpers in
`src/app_web.py`:
  - `_reputation_phrase(rep)` (app_web.py:210) — 80/60/40/20/0 tiers
  - `_fan_trust_phrase(trust)` (app_web.py:218) — 70/50/30/0 tiers
  - `_size_tier_phrase(size_tier)` (app_web.py:498) — major/mid/small

To keep this module self-contained (testable without booting the web
app — per the task spec recommendation, same pattern Task A1's
gym_identity_engine used), the tier thresholds + label mappings are
COPIED here as constants + helper functions. If `app_web.py` ever
retunes its thresholds, update the constants below in tandem.

Per CONVENTIONS §17.5 (performance): the bulk-load pattern is used —
ONE SELECT fetches all promotions + their roster's overall_desc via
LEFT JOINs (so promos with zero active fighters still get a row with
the "empty" roster phrase). A Python loop derives the 3 voice-phrase
fields per promo (pure CPU, no DB calls). ONE `executemany` writes the
rows via INSERT OR REPLACE. Target: <50ms for 10 promotions (well
under the <1s daily-pass budget).

Per CONVENTIONS §17.3: this module NEVER writes to simulation tables
(`promotions`, `fighters`, etc.). It writes ONLY to
`promotion_descriptors`.
"""


# ============================================================
# PRESTIGE_DESC — reputation tier (6-tier)
# ============================================================
# Per task spec: 6-tier system (90/75/60/40/20/0). Mirrors the band
# logic of `app_web.py:_reputation_phrase` (which uses a 5-tier
# 80/60/40/20/0 system) but expanded to 6 tiers for richer prestige
# phrases per the task spec's exact 6-phrase list.
#
# If `app_web.py:_reputation_phrase` ever retunes its thresholds, the
# constants here should be updated in tandem (per CONVENTIONS §14 +
# §17.1 — voice phrases live in the interpretation layer, not the
# simulation or UI layers).
_PRESTIGE_PHRASES = (
    # (threshold, phrase) — first match wins (highest first).
    (90, "the gold standard of MMA promotions"),
    (75, "an elite promotion with serious pull"),
    (60, "a respected player in the industry"),
    (40, "an established mid-tier promotion"),
    (20, "a scrappy regional player"),
    (0,  "a struggling unknown"),
)


def _prestige_desc(reputation):
    """Voice phrase for the promotion's reputation tier.

    Args:
        reputation: 0-100 int (or None — treated as 0).

    Returns:
        voice phrase string (one of 6 deterministic phrases).
    """
    if reputation is None:
        r = 0
    else:
        try:
            r = int(reputation)
        except (TypeError, ValueError):
            r = 0
    r = max(0, min(100, r))
    for threshold, phrase in _PRESTIGE_PHRASES:
        if r >= threshold:
            return phrase
    return _PRESTIGE_PHRASES[-1][1]  # defensive — r >= 0 always matches


# ============================================================
# MARKET_POSITION_DESC — broadcast_tier + ownership_type + size_tier
# ============================================================
# Per task spec: voice phrase derived from broadcast_tier + ownership_
# type. Combine with size_tier for nuance (e.g., "a corporate-backed
# PPV giant" for major vs "a regional streaming operation with a cult
# following" for small).
#
# broadcast_tier values (from PRAGMA table_info(promotions)):
#   'ppv_global', 'ppv_streaming', 'tv_regional', 'streaming',
#   'local_stream', 'none'
#
# ownership_type values: 'private', 'corporate', 'family', 'startup',
#   etc. (production DB has all 'private' as of 2026-08-17; corporate /
#   family / startup branches are included for forward-compat).
#
# size_tier values: 'major', 'mid', 'small' (default 'small').
#
# Mirrors the label logic of `app_web.py:_size_tier_phrase` (which
# maps size_tier → "Major-League Powerhouse" / "Mid-Tier Regional" /
# "Grassroots Operator") — same 3-tier system, but here we use it as
# a nuance modifier on the broadcast phrase rather than a standalone
# label.
def _market_position_desc(broadcast_tier, ownership_type, size_tier):
    """Voice phrase for the promotion's broadcast + ownership + size.

    Args:
        broadcast_tier: one of ppv_global / ppv_streaming / tv_regional
                        / streaming / local_stream / none.
        ownership_type: one of private / corporate / family / startup.
        size_tier:     one of major / mid / small.

    Returns:
        voice phrase string.
    """
    bt = (broadcast_tier or "").lower()
    ot = (ownership_type or "").lower()
    st = (size_tier or "").lower()
    is_ppv = bt in ("ppv_global", "ppv_streaming")
    is_corp = ot == "corporate"

    # PPV tiers — biggest reach + revenue.
    if is_ppv:
        if is_corp:
            if st == "major":
                return "a corporate-backed PPV giant"
            if st == "mid":
                return "a corporate PPV player with serious reach"
            return "a corporate PPV operation punching above its weight"
        # private / family / startup / etc. — independent.
        if st == "major":
            return "an independent PPV powerhouse"
        if st == "mid":
            return "an independent PPV player"
        return "an independent PPV underdog"

    # tv_regional — over-the-air / cable broadcast.
    if bt == "tv_regional":
        if st == "major":
            return "a major regional TV broadcasting presence"
        if st == "mid":
            return "a regional TV broadcasting presence"
        return "a regional TV operation with a cult following"

    # streaming — national/international streaming deal.
    if bt == "streaming":
        if st == "major":
            return "a major streaming-broadcast player"
        if st == "mid":
            return "a mid-tier streaming operation"
        return "a streaming-only operation with a niche audience"

    # local_stream — small streaming-only operation.
    if bt == "local_stream":
        if st == "major":
            return "a major streaming operation with grassroots reach"
        if st == "mid":
            return "a regional streaming operation"
        return "a streaming-only operation with a cult following"

    # none — no broadcast partner.
    if bt == "none" or bt == "":
        return "no broadcast partner — fights live only at the venue"

    # Defensive fallback for unknown broadcast_tier values (forward-
    # compat for future tiers not yet added to the schema).
    if st == "major":
        return "a major independent operation grinding on the regional scene"
    if st == "mid":
        return "an independent mid-tier promotion"
    return "a grassroots operation building its name on the local scene"


# ============================================================
# ROSTER_QUALITY_DESC — average fighter_descriptors.overall_desc tier
# ============================================================
# Per task spec: derive a tier per fighter from `overall_desc` (free-
# form text — checked format), aggregate per promo, then emit the
# "mostly X" phrase. If no tier has ≥50%, emit "mixed".
#
# The actual `overall_desc` format (verified against the production DB
# on 2026-08-17) is a free-form one-sentence summary like:
#   "Hiroki Nakamura 'The Grounded Anchor' is a brawler, with carries
#    real knockout power and above-average inside, currently rising
#    prospect."
#
# The "currently X" suffix encodes the fighter's career-phase label
# (champ / reigning champion / top prospect / contender on the rise /
# journeyman / gatekeeper / sliding veteran / etc.). We use that
# suffix as a quality-tier proxy via substring matching against an
# ordered pattern list (longer / more-specific phrases first to avoid
# prefix collisions).
#
# Tier mapping (per task spec's 5-tier system + a "mixed" bucket):
#   ELITE (5)         champion-tier fighters
#   ABOVE-AVERAGE (4) top prospects + contenders on the rise
#   AVERAGE (3)       mid-tier veterans + roster fillers
#   BELOW-AVERAGE (2) declining vets + raw prospects (unproven)
#   ABYSMAL (1)       (no specific keywords — fallback for unknown)
#
# Phrases per task spec:
#   elite         → "stacked with elite talent from top to bottom"
#   above_average → "a roster brimming with proven talent"
#   average       → "a solid roster of journeyman fighters"
#   below_average → "a roster full of unproven prospects"
#   abysmal       → "a thin roster scraping the bottom of the regional scene"
#   mixed         → "a mixed roster with stars and prospects"
#   empty         → "a roster still taking shape"

# (tier_label, keyword) — checked in order; first match wins.
# Longer/more-specific phrases listed before shorter ones to avoid
# prefix collisions (e.g., "contender on the rise" before any bare
# "contender" pattern — though we have none, the ordering is still
# defensive). "veteran on a roll" listed before other "veteran"
# phrases since it's the only above-average veteran label. The
# below-average veteran phrases ("sliding veteran", "grizzled
# veteran") are checked BEFORE the average veteran phrases so the
# "veteran" substring doesn't accidentally match an AVERAGE pattern
# first.
_ROSTER_TIER_PATTERNS = (
    # ELITE — champion-tier phrases (highest priority).
    ("elite",          "reigning titleholder"),
    ("elite",          "reigning champion"),
    ("elite",          "current titleholder"),
    ("elite",          "multi-time champ"),
    ("elite",          "champ"),
    # ABOVE-AVERAGE — top prospects + contenders on the rise.
    ("above_average",  "contender on the rise"),
    ("above_average",  "resurgent contender"),
    ("above_average",  "blue-chip prospect"),
    ("above_average",  "top prospect"),
    ("above_average",  "veteran on a roll"),
    # BELOW-AVERAGE — declining vets + raw prospects (checked before
    # AVERAGE so the "veteran" / "prospect" substring in those phrases
    # doesn't accidentally match an AVERAGE pattern first).
    ("below_average",  "sliding veteran"),
    ("below_average",  "grizzled veteran"),
    ("below_average",  "fallen contender"),
    ("below_average",  "gatekeeper"),
    ("below_average",  "young gun"),
    ("below_average",  "rising prospect"),
    ("below_average",  "developing prospect"),
    # AVERAGE — mid-tier veterans + roster fillers.
    ("average",        "former contender"),
    ("average",        "battle-tested veteran"),
    ("average",        "mid-card veteran"),
    ("average",        "wily veteran"),
    ("average",        "veteran fighter"),
    ("average",        "up-and-comer"),
    ("average",        "late bloomer"),
    ("average",        "seasoned competitor"),
    ("average",        "experienced hand"),
    ("average",        "active competitor"),
    ("average",        "promotion fighter"),
    ("average",        "roster fighter"),
    ("average",        "journeyman"),
)

_ROSTER_TIER_PHRASES = {
    "elite":         "stacked with elite talent from top to bottom",
    "above_average": "a roster brimming with proven talent",
    "average":       "a solid roster of journeyman fighters",
    "below_average": "a roster full of unproven prospects",
    "abysmal":       "a thin roster scraping the bottom of the regional scene",
    "mixed":         "a mixed roster with stars and prospects",
    "empty":         "a roster still taking shape",
}


def _fighter_tier(overall_desc):
    """Extract a tier label from a fighter's overall_desc text.

    Performs substring matching against the ordered pattern list.
    Returns the tier_label of the first matching pattern, or None
    if no pattern matches (fighter excluded from aggregation).

    Args:
        overall_desc: free-form one-sentence summary string (or None).

    Returns:
        one of "elite" / "above_average" / "average" / "below_average"
        / "abysmal", or None if no pattern matches.
    """
    if not overall_desc:
        return None
    # Substring match — patterns are ordered most-specific first
    # to avoid prefix collisions (e.g., "contender on the rise"
    # before "former contender"; both contain "contender" but
    # neither contains the other as a substring, so order is
    # defensive only).
    for tier_label, keyword in _ROSTER_TIER_PATTERNS:
        if keyword in overall_desc:
            return tier_label
    return None


def _roster_quality_desc(overall_descs):
    """Voice phrase for the average roster quality tier.

    Args:
        overall_descs: list of overall_desc strings for the promo's
                       active (non-retired) roster.

    Returns:
        voice phrase string.
    """
    if not overall_descs:
        return _ROSTER_TIER_PHRASES["empty"]

    # Count tiers per fighter. Fighters with no matching pattern are
    # excluded from the aggregation (defensive — their overall_desc
    # format may have shifted; we don't want to misclassify them).
    tier_counts = {}
    matched = 0
    for od in overall_descs:
        tier = _fighter_tier(od)
        if tier is None:
            continue
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        matched += 1

    if matched == 0:
        # No fighters had a recognizable tier — fall back to the
        # "empty" phrase (defensive — should not happen in production
        # but keeps the engine crash-safe).
        return _ROSTER_TIER_PHRASES["empty"]

    # "Mostly X" = a single tier has ≥50% of the matched fighters.
    # Otherwise "mixed".
    dominant_tier = None
    dominant_count = 0
    for tier, count in tier_counts.items():
        if count > dominant_count:
            dominant_count = count
            dominant_tier = tier

    if dominant_tier is None:
        return _ROSTER_TIER_PHRASES["mixed"]

    if dominant_count * 2 >= matched:
        # ≥50% — dominant tier wins.
        return _ROSTER_TIER_PHRASES.get(
            dominant_tier, _ROSTER_TIER_PHRASES["mixed"]
        )

    # No dominant tier — mixed.
    return _ROSTER_TIER_PHRASES["mixed"]


# ============================================================
# SNAPSHOT_VERSION + UPDATED_AT convention
# ============================================================
# Per task spec: read interpretation_cache_meta.engine_version (currently
# "1.10.0" after the snapshot_cache.ENGINE_VERSION bump in Task A1)
# and store as integer.
#
# Convention (matches gym_descriptors.snapshot_version from Task A1 +
# fighter_descriptors.snapshot_version): the cache table's
# snapshot_version is an INCREMENTING COUNTER —
# `COALESCE((SELECT snapshot_version + 1 ...), 1)` — that ticks on
# every refresh. We follow the same pattern via SQL rather than
# reading engine_version into Python. This keeps the snapshot_version
# meaningful as a "how many times has this promo been re-interpreted"
# counter — consistent with fighter_descriptors + gym_descriptors.
#
# Reading interpretation_cache_meta.engine_version into a separate
# Python variable is NOT needed because the SQL COALESCE pattern
# handles the increment + initial-value cases atomically. The
# engine_version mismatch check (snapshot_cache._should_full_rebuild)
# already triggers a full cache rebuild when ENGINE_VERSION bumps
# (1.9.0 → 1.10.0 in Task A1), which is the actual cache-invalidation
# signal — snapshot_version is just a per-row monotonic counter, not
# a version stamp.
#
# updated_at uses the SQL CURRENT_TIMESTAMP function (not a Python
# datetime) so the timestamp is consistent with the rest of the
# interpretation layer's writes (matches gym_identity_engine +
# context_engine conventions).


# ============================================================
# PUBLIC API
# ============================================================
def compute_all_promotion_descriptors(conn, current_date=None):
    """Populate `promotion_descriptors` for all promotions.

    Per CONVENTIONS §17.5 (performance): uses the bulk-load pattern —
    ONE SELECT fetches all promotions + their roster's overall_desc
    via LEFT JOINs (so promos with zero active fighters still get a
    row with the "empty" roster phrase). A Python loop derives the 3
    voice-phrase fields per promo (pure CPU, no DB calls). ONE
    `executemany` writes the rows via INSERT OR REPLACE (idempotent —
    safe to re-run on the same date or across daily passes).

    Per CONVENTIONS §17.1: this is the ONLY writer to
    promotion_descriptors. It writes ONLY to promotion_descriptors —
    never to `promotions` (simulation table) or any other table.

    Per CONVENTIONS §17.3: the engine is idempotent. Re-running for
    the same date overwrites the existing rows (INSERT OR REPLACE).
    Re-running across daily passes is the normal usage pattern (the
    daily interpretation pass calls this once per tick).

    Args:
        conn:         sqlite3.Connection.
        current_date: ISO date string (unused — promotion descriptors
                      don't depend on the sim date. Kept for API
                      symmetry with the other interpretation sub-
                      engines which DO take current_date:
                      context_engine, career_phase_engine, etc. The
                      signature is fixed by snapshot_cache._
                      _interpret_promotions which calls this with
                      (conn, current_date).).

    Returns:
        int — number of promotion_descriptors rows written.
    """
    # ----------------------------------------------------------------
    # 1. ONE SELECT — fetch all promotions + their roster's overall_
    #    desc. LEFT JOIN fighters + fighter_descriptors so promos
    #    with zero active fighters still appear (with overall_desc
    #    = NULL). The fighters table has ~4450 active rows total —
    #    this JOIN produces ~415 rows (10 promos × ~42 fighters each
    #    on average; promos with no roster contribute ONE row with
    #    overall_desc = NULL, which the Python loop ignores). The
    #    result is grouped by promotion_id in Python (step 2).
    # ----------------------------------------------------------------
    rows = conn.execute(
        """
        SELECT p.promotion_id, p.reputation, p.broadcast_tier,
               p.ownership_type, p.size_tier,
               fd.overall_desc
        FROM promotions p
        LEFT JOIN fighters f
            ON f.current_promotion_id = p.promotion_id
            AND f.is_retired = 0
        LEFT JOIN fighter_descriptors fd
            ON fd.fighter_id = f.fighter_id
        ORDER BY p.promotion_id
        """
    ).fetchall()

    if not rows:
        # No promotions in DB — nothing to do (defensive; should
        # never happen in a real game but keeps the engine crash-
        # safe on a fresh/test DB).
        return 0

    # ----------------------------------------------------------------
    # 2. Python loop — group rows by promotion_id, derive the 3
    #    voice-phrase fields per promo. Pure CPU — no DB calls.
    #
    #    The SELECT returns ONE row per (promotion, fighter) pair —
    #    promos with multiple fighters appear multiple times with
    #    the same promo-level columns + different overall_desc. We
    #    group them here into a single per-promo record.
    #
    #    promo_order preserves the SELECT's ORDER BY promotion_id
    #    so the executemany writes rows in deterministic order
    #    (idempotent across re-runs — same input → same output).
    # ----------------------------------------------------------------
    promo_rows = {}   # {promotion_id: {rep, broadcast, ownership, size, [overall_descs]}}
    promo_order = []  # preserve promotion_id order for deterministic output

    for r in rows:
        (promotion_id, reputation, broadcast_tier, ownership_type,
         size_tier, overall_desc) = r

        if promotion_id not in promo_rows:
            promo_rows[promotion_id] = {
                "reputation":      reputation,
                "broadcast_tier":  broadcast_tier,
                "ownership_type":  ownership_type,
                "size_tier":        size_tier,
                "overall_descs":   [],
            }
            promo_order.append(promotion_id)

        if overall_desc:
            promo_rows[promotion_id]["overall_descs"].append(overall_desc)

    # Derive the 3 voice-phrase fields per promo.
    rows_to_write = []
    for promotion_id in promo_order:
        info = promo_rows[promotion_id]
        prestige = _prestige_desc(info["reputation"])
        market_position = _market_position_desc(
            info["broadcast_tier"],
            info["ownership_type"],
            info["size_tier"],
        )
        roster_quality = _roster_quality_desc(info["overall_descs"])

        rows_to_write.append((
            promotion_id,
            prestige,
            market_position,
            roster_quality,
        ))

    # ----------------------------------------------------------------
    # 3. ONE executemany — INSERT OR REPLACE into promotion_descriptors.
    #    snapshot_version follows the gym_descriptors convention
    #    (from Task A1): COALESCE((SELECT snapshot_version + 1 ...), 1)
    #    so it ticks on every refresh (1 on first write, 2/3/... on
    #    subsequent). updated_at uses the SQL CURRENT_TIMESTAMP
    #    function (not a Python datetime) so the timestamp is
    #    consistent with the rest of the interpretation layer's
    #    writes.
    # ----------------------------------------------------------------
    conn.executemany(
        """
        INSERT OR REPLACE INTO promotion_descriptors
            (promotion_id, prestige_desc, market_position_desc,
             roster_quality_desc, snapshot_version, updated_at)
        VALUES (?, ?, ?, ?,
                COALESCE((SELECT snapshot_version + 1
                          FROM promotion_descriptors
                          WHERE promotion_id = ?), 1),
                CURRENT_TIMESTAMP)
        """,
        # Bind 4 fields + promotion_id twice (once for the INSERT
        # VALUES, once for the COALESCE subquery's WHERE clause).
        [(pid, prest, mpos, rqual, pid)
         for (pid, prest, mpos, rqual) in rows_to_write],
    )
    conn.commit()

    return len(rows_to_write)
