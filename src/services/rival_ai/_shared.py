"""CAGE EMPIRE Rival AI — shared utilities (Task ID RIVAL-AI-P1, Phase 1).

Shared helpers used by multiple `services/rival_ai/` submodules:
    - DB connection helpers (current_date, roster_size, etc.)
    - A per-(promotion_id, date) roster cache (Phase 2+ will use this;
      Phase 1 ships only the helpers + a no-op cache)
    - News-item writer (Phase 2+ will use this for bidding-war-lost
      news items, etc.; Phase 1 ships the helper but no callers)

Phase 1 ships ONLY the helper functions + a placeholder roster cache.
The cache invalidation hooks (FIGHT_RESOLVED, FIGHTER_SIGNED,
INJURY_CREATED, INJURY_RECOVERED) will be wired in Phase 2 when the
matchmaker starts querying rosters.

CONVENTIONS compliance:
  §5  — No new tables. Reads existing fighters / promotions /
        simulation_clock tables.
  §14 — Voice Layer: the news-item writer is a thin wrapper around
        the existing news engine INSERT pattern. Phase 2+ callers
        must supply voice-layer-formatted text (no raw numbers).
  §15 — Event Bus: N/A — these are pure helpers, not subscribers.
"""


# ----------------------------------------------------------------
# DB helpers — small wrappers around common SELECTs that the
# Phase 2-4 modules will need. Centralizing them here keeps the
# decision modules thin (each decision function should be ~80 lines
# of logic, not 80 lines of logic + 40 lines of boilerplate SELECTs).
# ----------------------------------------------------------------

def current_sim_date(conn):
    """Return the current sim date string ('YYYY-MM-DD') from
    simulation_clock, or None if the clock isn't initialized.
    """
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else None


def current_sim_day(conn):
    """Return simulation_clock.current_day (int >= 1), or 0 if unset."""
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else 0


def roster_size(conn, promotion_id):
    """Return the number of active, non-retired fighters on the
    promotion's roster. Mirrors `_roster_size` in src/rival_ai.py.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM fighters "
        "WHERE current_promotion_id=? AND is_active=1 AND is_retired=0",
        (promotion_id,),
    ).fetchone()
    return row[0] if row else 0


def promotion_cash(conn, promotion_id):
    """Return promotions.current_cash (REAL), or 0.0 if missing."""
    row = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


# ----------------------------------------------------------------
# Roster cache (Phase 2 placeholder).
#
# Per arch doc §4.4, the rival AI should cache the result of
# `_get_available_fighters_for_card` per (promotion_id, ref_date_str)
# to avoid re-querying the 4-way JOIN on every weekly tick.
#
# Phase 1 ships the cache structure + invalidate_all() but does NOT
# wire it into any decision function (Phase 2's matchmaker will be
# the first caller). The cache is module-level (not a singleton) —
# per arch doc §4.5, the modules are stateless, but the cache is
# explicitly a TTL cache (cleared at the start of each new tick),
# not "mutable state" in the design-law sense.
# ----------------------------------------------------------------

_ROSTER_CACHE = {}


def cache_key(promotion_id, ref_date_str):
    """Return the cache key for (promotion_id, ref_date_str)."""
    return (int(promotion_id), str(ref_date_str))


def roster_cache_get(promotion_id, ref_date_str):
    """Return the cached roster for (promotion_id, ref_date_str),
    or None if not cached. Phase 2 callers should call this BEFORE
    the expensive SELECT; on miss, run the SELECT + call
    `roster_cache_put`.
    """
    return _ROSTER_CACHE.get(cache_key(promotion_id, ref_date_str))


def roster_cache_put(promotion_id, ref_date_str, roster_rows):
    """Store `roster_rows` (list of dict-like rows) in the cache
    under (promotion_id, ref_date_str). Phase 2 will call this after
    the SELECT.
    """
    _ROSTER_CACHE[cache_key(promotion_id, ref_date_str)] = roster_rows


def roster_cache_invalidate(promotion_id=None):
    """Invalidate cache entries.

    If `promotion_id` is None, clears ALL entries (call this at the
    start of each new tick — the TTL is 1 tick per arch doc §4.4).
    If `promotion_id` is given, clears only entries for that promo
    (call this on FIGHTER_SIGNED / INJURY_CREATED / etc. for that
    promo's roster).
    """
    if promotion_id is None:
        _ROSTER_CACHE.clear()
        return
    pid = int(promotion_id)
    # Iterate keys() to a list to avoid mutating-during-iteration.
    for key in list(_ROSTER_CACHE.keys()):
        if key[0] == pid:
            del _ROSTER_CACHE[key]


# ----------------------------------------------------------------
# News-item writer (Phase 2+ helper).
#
# Phase 1 ships the writer but no callers. Phase 2's signing_agent
# will use this for bidding-war-lost + tapping-up-rumor news items;
# Phase 3's cutting_agent + staff_manager will use it for release +
# staff hire/fire news items; Phase 4's imperfection will use it for
# archetype-reclassification news items.
#
# Mirrors the existing news INSERT pattern (direct INSERT into
# news_items with the 'System Feed' source — the news engine's
# subscribers handle the voice-layer routing on FIGHTER_SIGNED etc.
# but the rival AI's bespoke news items go in directly per arch doc
# §Q8 default assumption).
# ----------------------------------------------------------------

def write_news_item(conn, headline, body, topic, sentiment='neutral',
                    promotion_id=None, fighter_id=None, event_id=None,
                    fight_id=None, published_at=None, importance=None,
                    news_source_id=None):
    """Insert a news_items row + return its news_item_id.

    Phase 2+ helper. The news engine's subscribers will pick this up
    via the daily interpretation pass; for immediate UI visibility the
    published_at is set to the current sim date (or `published_at` if
    supplied). Defaults match the existing pattern in app.write_news
    + news.py.

    Args:
        conn: sqlite3.Connection (caller commits).
        headline: short headline (≤ 120 chars recommended).
        body: full body text. Voice-layer formatted — NO raw numbers
            (potential 78, salary $50K, age 27) per CONVENTIONS §14.
        topic: news topic key (e.g. 'bidding_war_lost',
            'tapping_up_rumor', 'release', 'staff', 'reclassified').
        sentiment: 'positive' / 'neutral' / 'negative'.
        promotion_id, fighter_id, event_id, fight_id: optional FKs.
        published_at: optional sim date string ('YYYY-MM-DD').
            Defaults to current sim date.
        importance: optional importance tier name (one of
            NEWS_IMPORTANCE_LEGENDARY / MAJOR / SIGNIFICANT /
            ROUTINE / BACKGROUND). If None, the tier is derived from
            the `topic` via news._importance_for_topic (the canonical
            topic→tier mapper). NOTE: this used to be a numeric 0-100
            value which was silently ignored (the INSERT omitted the
            importance column, so all writes defaulted to 'ROUTINE'
            via the schema column default — contributing to ROUTINE
            spam). NEWS-SPAM-MEMORY-CHECK changed it to a tier-name
            string and routed the write through
            news._write_news_item so the daily cap + GPT-question
            downgrade apply uniformly.
        news_source_id: optional news_sources.news_source_id. Defaults
            to the 'System Feed' source (id resolved at INSERT time).

    Returns:
        The new news_item_id (int), or None if the write was
        suppressed by the daily cap (HW4.3) or a fatal error.
    """
    if published_at is None:
        published_at = current_sim_date(conn)

    # NEWS-SPAM-MEMORY-CHECK — route through news._write_news_item so
    # the importance tier is tagged (derived from `topic` via the
    # canonical mapper, or from the `importance` arg if the caller
    # passed an explicit tier name). The previous direct INSERT
    # omitted the importance column entirely, defaulting everything
    # to ROUTINE — including 'release' (should be MAJOR) and
    # 'tapping_up_rumor' (should be BACKGROUND).
    try:
        from news import _write_news_item as _news_write
        return _news_write(
            conn, headline, body, sentiment=sentiment,
            event_id=event_id, fight_id=fight_id, fighter_id=fighter_id,
            promotion_id=promotion_id, published_at=published_at,
            source_id=news_source_id, topic=topic, importance=importance,
        )
    except ImportError:
        # Fallback — direct INSERT (preserves old behavior if the
        # news module isn't importable for any reason). Defensive —
        # shouldn't happen since news.py is a core module.
        if news_source_id is None:
            row = conn.execute(
                "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO news_sources "
                    "(name, credibility, sensationalism, bias, regional_reach, "
                    "reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("System Feed", 70, 40, 50, 60, 80, 80),
                )
                news_source_id = cur.lastrowid
            else:
                news_source_id = row[0]
        # Resolve importance tier (defensive — if it's not a valid
        # tier name, fall back to 'ROUTINE').
        valid_tiers = ("LEGENDARY", "MAJOR", "SIGNIFICANT",
                       "ROUTINE", "BACKGROUND")
        tier = importance if importance in valid_tiers else "ROUTINE"
        cur = conn.execute(
            "INSERT INTO news_items "
            "(news_source_id, headline, body, sentiment, topic, "
            " event_id, fight_id, fighter_id, promotion_id, published_at, "
            " importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (news_source_id, headline, body, sentiment, topic,
             event_id, fight_id, fighter_id, promotion_id, published_at,
             tier),
        )
        return cur.lastrowid
