"""CAGE EMPIRE — Canonical marketability helpers (Tier 2 / W38).

GPT's W38 feedback ("one meaning should have one authoritative
calculation") observed that `marketability` was being computed in
3+ places with subtly different signatures:

  1. ``src/suspensions.py::_get_marketability(conn, fighter_id)``
     — reads the cached ``fighters.marketability`` column (the value
     written by ``morale.py`` on each tick). Default 50. Returns int.

  2. ``src/app_web.py::_popularity_tier(marketability)``
     — converts a 0-100 score to a voice label ("Cult Hero" /
     "Rising Star" / "Mid Level" / "Unknown"). Used by the
     Matchmaking V2 corner-slot info (MM1.2 §5).

  3. ``src/services/rival_ai/matchmaker.py::_marketability(fighter_a, fighter_b)``
     — computes a pairwise 0..1 score from the two fighters' rating,
     win_streak, and potential (arch doc §3.2 formula).

This module consolidates all three computations behind a single
canonical API:

  - ``compute_marketability(conn, fighter_id)``  — the cached 0-100 value.
  - ``marketability_tier(value)``                — the voice label.
  - ``pairwise_marketability(conn, fighter_a, fighter_b)`` — the 0..1 score.

The legacy callsites (``_get_marketability``, ``_popularity_tier``,
``_marketability``) are preserved as 1-line delegators so existing
imports + tests continue to work unchanged.

Backward compatibility
----------------------
The 3 canonical functions return the EXACT same values as the legacy
functions they replace — same defaults, same thresholds, same labels.
This is a structural refactor, NOT a behavior change. The
``src/web/js/matchmaking.js`` UI checks ``tier === 'Cult Hero'`` for
the CSS class ``ce-mm-chip-v2--popularity-cult`` — changing the
labels would break that contract, so the tier labels are kept
verbatim.
"""
from __future__ import annotations

from typing import Mapping, Optional, Union


# ---------------------------------------------------------------------------
# 1. Per-fighter marketability (cached column read).
# ---------------------------------------------------------------------------

def compute_marketability(conn, fighter_id) -> float:
    """Return the fighter's current marketability (0-100).

    This is the single source of truth — reads the cached
    ``fighters.marketability`` column. That column is written by
    ``morale.py`` on each tick (the morale subscriber recomputes
    marketability from recent results + contract value + age curve +
    archetype + rivalry heat). All readers MUST go through this
    function so the value is consistent across the codebase.

    Default 50 if the fighter row is missing or the column is NULL
    (matches the legacy ``_get_marketability`` behavior).

    Args:
        conn: sqlite3.Connection (or compatible).
        fighter_id: the fighter's PK.

    Returns:
        Float in [0, 100]. Returned as float for type stability —
        callers that need int should ``int(...)`` the result.
    """
    row = conn.execute(
        "SELECT marketability FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if row is None:
        return 50.0
    val = row[0]
    if val is None:
        return 50.0
    return float(val)


# ---------------------------------------------------------------------------
# 2. Tier label (voice layer).
# ---------------------------------------------------------------------------

# Tier thresholds — match the legacy ``_popularity_tier`` in app_web.py
# EXACTLY (the JS in src/web/js/matchmaking.js depends on these label
# strings for CSS class assignment — see backward-compat note above).
#
# Threshold summary:
#   >= 80  → "Cult Hero"   (gold chip — the superstars)
#   >= 60  → "Rising Star" (silver chip — emerging names)
#   >= 40  → "Mid Level"   (default — solid roster fighters)
#   <  40  → "Unknown"     (gray chip — prospects + cans)
#   None / unparseable → "Unknown"
def marketability_tier(value) -> str:
    """Convert a 0-100 marketability score to a voice phrase label.

    Returns one of:
      - ``"Cult Hero"``   — marketability >= 80
      - ``"Rising Star"`` — marketability >= 60 (and < 80)
      - ``"Mid Level"``   — marketability >= 40 (and < 60)
      - ``"Unknown"``     — marketability < 40, or None / unparseable

    The labels mirror WMMA5's "Name Value" tiers (per
    docs/MASTER_PLAN_MATCHMAKING_V2.md §MM1.2 #5). Voice-layer: NO
    raw numbers — just the tier label the player reads like a
    marketing band.

    Args:
        value: a 0-100 numeric score (int or float), or None.

    Returns:
        One of the 4 label strings above.
    """
    if value is None:
        return "Unknown"
    try:
        m = int(value)
    except (TypeError, ValueError):
        return "Unknown"
    if m >= 80:
        return "Cult Hero"
    if m >= 60:
        return "Rising Star"
    if m >= 40:
        return "Mid Level"
    return "Unknown"


# ---------------------------------------------------------------------------
# 3. Pairwise marketability (matchup score).
# ---------------------------------------------------------------------------

def _load_fighter_for_pairwise(conn, fighter_id):
    """Fetch the rating + win_streak + potential for a fighter.

    Returns a dict with the 3 fields the pairwise formula needs.
    Defaults match the legacy ``_marketability`` function:
      - rating default 1000.0  (from the ``rankings`` table —
        ``fighters`` has no rating column; the matchmaker's roster
        query joins ``rankings`` to compute ``COALESCE(r.rating,
        1000.0) AS rating`` per services/matchmaking.py:530).
      - win_streak default 0   (from ``fighter_career``)
      - potential default 0    (NOT 50 — the legacy code uses .get
        with default 0 in the comparison ``>= 70``; we preserve that)
    """
    # Mirrors the matchmaking.py:528-548 roster query's column
    # resolution (fighters → fighter_career → rankings). We pick the
    # promotion-matched ranking row to match the roster query's
    # JOIN condition (r.fighter_id = f.fighter_id AND
    # r.weight_class_id = f.weight_class_id AND
    # r.promotion_id = f.current_promotion_id).
    row = conn.execute(
        "SELECT COALESCE(r.rating, 1000.0), "
        "COALESCE(fc.win_streak, 0), "
        "COALESCE(fc.potential, 0) "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id = f.fighter_id "
        "  AND r.weight_class_id = f.weight_class_id "
        "  AND r.promotion_id = f.current_promotion_id "
        "WHERE f.fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if row is None:
        return {
            'rating': 1000.0,
            'win_streak': 0,
            'potential': 0,
        }
    rating = row[0] if row[0] is not None else 1000.0
    return {
        'rating': float(rating),
        'win_streak': int(row[1] or 0),
        'potential': int(row[2] or 0),
    }


def pairwise_marketability(
    conn,
    fighter_a: Union[int, Mapping],
    fighter_b: Union[int, Mapping],
) -> float:
    """Compute the 0..1 marketability score for a fighter pair.

    Per arch doc §3.2 (services/rival_ai/matchmaker.py):

        marketability(A, B) =
            clamp((rating_A + rating_B) / 2 / 1500, 0, 1)
          + 0.20 if either fighter has win_streak >= 3
          + 0.15 if either is a current champion        (SKIPPED —
                  see "Current champion check" note below)
          + 0.10 if both have reputation >= 70           (uses
                  potential as a reputation proxy per legacy code)
          (capped at 1.0)

    The legacy implementation in ``matchmaker._marketability`` accepts
    pre-loaded fighter dicts (the matchmaker already has them in
    memory — a DB round-trip would be wasteful). To preserve that
    performance characteristic, this canonical function accepts
    EITHER fighter IDs (with a non-None ``conn``) OR pre-loaded
    dict-like rows.

    Args:
        conn: sqlite3.Connection. May be None if BOTH fighter_a and
            fighter_b are pre-loaded dicts (the matchmaker's fast
            path).
        fighter_a, fighter_b: either fighter IDs (int) or dict-like
            rows with at minimum the keys ``'rating'`` (default
            1000.0), ``'win_streak'`` (default 0), ``'potential'``
            (default 0).

    Returns:
        Float in [0.0, 1.0].
    """
    # Resolve fighter_a.
    if isinstance(fighter_a, Mapping):
        fa = fighter_a
    else:
        # Treat as an ID — query the DB.
        if conn is None:
            fa = {
                'rating': 1000.0,
                'win_streak': 0,
                'potential': 0,
            }
        else:
            fa = _load_fighter_for_pairwise(conn, fighter_a)

    # Resolve fighter_b.
    if isinstance(fighter_b, Mapping):
        fb = fighter_b
    else:
        if conn is None:
            fb = {
                'rating': 1000.0,
                'win_streak': 0,
                'potential': 0,
            }
        else:
            fb = _load_fighter_for_pairwise(conn, fighter_b)

    # Compute the pairwise score (same formula as the legacy
    # matchmaker._marketability — verbatim).
    rating_a = fa.get('rating', 1000.0) if isinstance(fa, Mapping) else 1000.0
    rating_b = fb.get('rating', 1000.0) if isinstance(fb, Mapping) else 1000.0
    base = ((rating_a + rating_b) / 2.0) / 1500.0
    base = max(0.0, min(1.0, base))
    if (fa.get('win_streak', 0) >= 3
            or fb.get('win_streak', 0) >= 3):
        base += 0.20
    # "Current champion" check would need a titles lookup — skip for
    # performance (the +/- 0.15 is a minor factor; the safe path's
    # _build_main_event handles title fights explicitly).
    if (fa.get('potential', 0) >= 70
            and fb.get('potential', 0) >= 70):
        base += 0.10  # reputation proxy — both have star potential
    return min(1.0, base)


__all__ = [
    "compute_marketability",
    "marketability_tier",
    "pairwise_marketability",
]
