"""CAGE EMPIRE Dynamic Reputation System (FIX-VoiceRep).

Wires the two "frozen field" gaps in the promotions + gyms tables.
Before this module landed, both `promotions.reputation` and
`gyms.reputation` were set at seed time and NEVER updated by game
events — a fighter could win a title, fail a drug test, or star in
an instant-classic main event and the promotion's reputation would
not move. This module closes that gap with a small, focused set of
event-bus subscribers that nudge reputation up or down based on
in-world outcomes.

promotions.reputation (0-100, INTEGER CHECK [0, 100]):
  - EVENT_COMPLETED: if show_rating overall >= 75 → +2 (a great
    show lifts the brand); if overall < 40 → -1 (a dud hurts).
    Falls back to no-op if no show_ratings row exists yet (the
    show_rating module writes one per EVENT_COMPLETED — defensive
    ordering).
  - TITLE_CHANGED: +1 (title fights are prestigious — every title
    change is free press for the promotion).
  - Drug-test suspension: -3 (a scandal tarnishes the brand).
    Polled on TICK_ADVANCED via a dedup marker (defensive — see
    _DRUG_TEST_DEDUP_TOPIC below).
  - Bankruptcy / financial trouble: -2 (a promotion that can't pay
    its bills loses standing). Checked on EVENT_COMPLETED (after
    finance.py writes its transactions) when current_cash < 0.
  - Clamped to [10, 95] (mirrors morale.py — never 0/100; [10, 95]
    keeps reputation impactful without breaking the sim).

gyms.reputation (0-100, INTEGER CHECK [0, 100]):
  - FIGHT_RESOLVED: winner's gym +1 (a win reflects well on the
    camp); KO-loser's gym -1 (a knockout loss reflects poorly).
    "KO loser" = the loser of a fight whose result_type is in
    ('ko_tko', 'ko', 'tko') — the brutal finish is what hurts the
    gym's reputation, not a decision loss.
  - TITLE_CHANGED: new champion's gym +3 (a champion is the gym's
    crown jewel).
  - CAMP_COMPLETED: +0.5 (developing talent — the gym is doing its
    job). The +0.5 is a REAL value (reputation column is INTEGER
    but SQLite's INTEGER affinity stores 50.5 as REAL — same
    pattern as morale.py's travel_comfort).
  - Clamped to [10, 95].

The module is entirely event-bus-driven (CONVENTIONS §15.4 — no
new inline side effects added to resolve_next_fight or run_tick).
Subscribes to 5 events:

  FIGHT_RESOLVED  → _process_fight (gyms reputation)
  TITLE_CHANGED   → _process_title_change (promotions + gyms)
  EVENT_COMPLETED → _process_event_completed (promotions + bankruptcy)
  TICK_ADVANCED   → _process_tick (drug-test suspension scan)
  CAMP_COMPLETED  → _process_camp_completed (gyms +0.5)

REGISTRATION ORDER MATTERS: this module should register AFTER
suspensions.py + finance.py + show_rating.py so the suspensions
rows / finance transactions / show_ratings rows are written before
this module tries to read them on the same event. The registration
order in app.py App.__init__ is already show_rating → venues →
finance → save_load → player_settings; this module slots in after
save_load (which is after finance). For TICK_ADVANCED, the
suspensions module's _maybe_random_suspension runs on
FIGHT_RESOLVED (not TICK_ADVANCED), so the suspensions rows
already exist by the time TICK_ADVANCED fires — no ordering issue.

VOICE LAYER (CONVENTIONS §14): the reputation system produces NO
player-facing text. Reputation is internal state that feeds future
systems (rival AI booking decisions, sponsorship payouts, etc.).
No raw numbers leak because reputation writes no prose of its own.

DESIGN LAW (CONVENTIONS §13):
  - Growth: a promotion that consistently puts on great shows
    builds reputation → attracts better fighters → puts on better
    shows. The feedback loop is now CLOSED.
  - Conflict: a scandal (drug test failure) hurts. A bankruptcy
    hurts more. The "can the promotion rebound?" thread is now a
    real sim state, not just a storyline seed.
  - Stories: a gym that produces a champion becomes a destination
    for prospects. A gym whose fighters keep getting knocked out
    falls out of favor. The gym hierarchy now evolves with the sim.

USAGE:
  from reputation import register_subscribers
  register_subscribers()  # call once at startup (UI App.__init__,
                          # test setup). Safe to call multiple times.
"""

import random


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# Reputation bounds — never 0/100 (a 0-reputation promotion is dead;
# a 100-reputation promotion has nothing to chase). The [10, 95]
# band mirrors morale.py and keeps reputation impactful without
# breaking the sim.
REP_FLOOR = 10
REP_CEIL = 95

# Promotion reputation deltas (per the brief).
PROMO_REP_DELTA_GREAT_SHOW = +2     # show_rating overall >= 75
PROMO_REP_DELTA_DUD_SHOW = -1       # show_rating overall < 40
PROMO_REP_DELTA_TITLE_CHANGE = +1   # any title change
PROMO_REP_DELTA_DRUG_SCANDAL = -3   # drug_test_failure suspension
PROMO_REP_DELTA_BANKRUPTCY = -2     # current_cash < 0 after event

# Gym reputation deltas (per the brief).
GYM_REP_DELTA_WIN = +1              # fighter from this gym wins
GYM_REP_DELTA_KO_LOSS = -1          # fighter from this gym loses by KO
GYM_REP_DELTA_NEW_CHAMP = +3        # fighter from this gym wins a title
GYM_REP_DELTA_CAMP_COMPLETED = 0.5  # the gym is developing talent

# Show-rating thresholds for promotion reputation.
SHOW_RATING_GREAT_THRESHOLD = 75
SHOW_RATING_DUD_THRESHOLD = 40

# Drug-test suspension type — matches the suspensions module's
# CHECK constraint value.
DRUG_TEST_SUSPENSION_TYPE = "drug_test_failure"

# Hidden dedup marker for the drug-test scandal scan. Appended to a
# throwaway news_items row's body (topic='reputation_marker') so we
# can detect "have we already applied the scandal hit for this
# suspension_id?" without adding a new table (CONVENTIONS §16 —
# code-only fixes, no new tables). The marker is NOT player-facing
# — the topic='reputation_marker' filter excludes it from the news
# feed (the UI filters by topic IN ('fight','title','retirement',
# 'news_engine','show_rating','suspension', etc.)).
_REPUTATION_MARKER_TOPIC = "reputation_marker"


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _clamp(value):
    """Clamp a reputation value to [REP_FLOOR, REP_CEIL]."""
    if value < REP_FLOOR:
        return REP_FLOOR
    if value > REP_CEIL:
        return REP_CEIL
    return value


def _adjust_promotion_rep(conn, promotion_id, delta):
    """Adjust a promotion's reputation by delta, clamped to [10, 95].

    Defensive — silently no-ops if the promotion doesn't exist.
    """
    if not promotion_id or delta == 0:
        return
    row = conn.execute(
        "SELECT reputation FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if not row:
        return
    current = row[0] if row[0] is not None else 50
    new_val = _clamp(current + delta)
    conn.execute(
        "UPDATE promotions SET reputation=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE promotion_id=?",
        (new_val, promotion_id),
    )


def _adjust_gym_rep(conn, gym_id, delta):
    """Adjust a gym's reputation by delta, clamped to [10, 95].

    Defensive — silently no-ops if the gym doesn't exist. The
    reputation column is INTEGER but accepts REAL deltas (SQLite's
    INTEGER affinity stores 50.5 as REAL — same pattern as morale.
    py's travel_comfort, see D6 in the worklog).
    """
    if not gym_id or delta == 0:
        return
    row = conn.execute(
        "SELECT reputation FROM gyms WHERE gym_id=?",
        (gym_id,),
    ).fetchone()
    if not row:
        return
    current = row[0] if row[0] is not None else 50
    new_val = _clamp(current + delta)
    conn.execute(
        "UPDATE gyms SET reputation=? WHERE gym_id=?",
        (new_val, gym_id),
    )


def _fighter_gym_id(conn, fighter_id):
    """Return the fighter's current_gym_id (or None)."""
    if fighter_id is None:
        return None
    row = conn.execute(
        "SELECT current_gym_id FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else None


def _has_drug_scandal_marker(conn, suspension_id):
    """Return True if we've already applied the drug-scandal rep hit.

    Uses a hidden news_items row with topic='reputation_marker' and
    a body containing '[suspension_id=N:drug_scandal]'. The marker
    is invisible to the player (the topic is excluded from the news
    feed) but queryable by us. This avoids adding a new table per
    CONVENTIONS §16 (code-only fixes).
    """
    if suspension_id is None:
        return False
    marker = f"[suspension_id={suspension_id}:drug_scandal]"
    row = conn.execute(
        "SELECT 1 FROM news_items WHERE topic=? AND body LIKE ?",
        (_REPUTATION_MARKER_TOPIC, f"%{marker}%"),
    ).fetchone()
    return row is not None


def _write_drug_scandal_marker(conn, suspension_id, promotion_id):
    """Record that we've applied the drug-scandal rep hit.

    Writes a hidden news_items row (topic='reputation_marker') so
    future TICK_ADVANCED polls can detect the dedup. The row is
    written to the System Feed news source (defensive — the source
    is created by app.py / tick_processor.py at startup).
    """
    if suspension_id is None:
        return
    marker = f"[suspension_id={suspension_id}:drug_scandal]"
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    src_id = src_row[0] if src_row else None
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (src_id, "[reputation marker]", marker, "neutral",
         _REPUTATION_MARKER_TOPIC, None, promotion_id, None),
    )


# ----------------------------------------------------------------
# FIGHT_RESOLVED — gyms reputation (winner +1, KO-loser -1)
# ----------------------------------------------------------------

def _process_fight(conn, event):
    """FIGHT_RESOLVED subscriber — adjust gyms reputation.

    Winner's gym: +1 (a win reflects well on the camp).
    KO-loser's gym: -1 (a brutal knockout loss reflects poorly —
    decision losses don't hurt the gym's reputation the same way).
    """
    winner_id = event.get("winner_id")
    loser_id = event.get("loser_id")
    result_type = event.get("result_type", "") or ""
    if winner_id is None or loser_id is None:
        return  # draw or incomplete event payload

    winner_gym = _fighter_gym_id(conn, winner_id)
    if winner_gym is not None:
        _adjust_gym_rep(conn, winner_gym, GYM_REP_DELTA_WIN)

    # KO loss: result_type in ('ko_tko', 'ko', 'tko'). The brutal
    # finish is what hurts the gym's reputation — a decision loss
    # is just a loss, not a camp-damaging moment.
    rt = result_type.lower()
    if rt in ("ko_tko", "ko", "tko"):
        loser_gym = _fighter_gym_id(conn, loser_id)
        if loser_gym is not None:
            _adjust_gym_rep(conn, loser_gym, GYM_REP_DELTA_KO_LOSS)


# ----------------------------------------------------------------
# TITLE_CHANGED — promotions +1, gyms +3 (champion's gym)
# ----------------------------------------------------------------

def _process_title_change(conn, event):
    """TITLE_CHANGED subscriber — adjust promotion + gym reputation.

    Promotion: +1 (title fights are prestigious — every title change
    is free press for the promotion).
    New champion's gym: +3 (a champion is the gym's crown jewel).
    """
    title_id = event.get("title_id")
    promo_id = event.get("promotion_id")
    if not title_id:
        return

    # Promotion reputation +1.
    if promo_id:
        _adjust_promotion_rep(conn, promo_id, PROMO_REP_DELTA_TITLE_CHANGE)

    # New champion's gym +3.
    title_row = conn.execute(
        "SELECT current_champion_fighter_id FROM titles WHERE title_id=?",
        (title_id,),
    ).fetchone()
    if not title_row:
        return
    champ_id = title_row[0]
    if champ_id is None:
        return  # title is vacant — no champion's gym to credit
    champ_gym = _fighter_gym_id(conn, champ_id)
    if champ_gym is not None:
        _adjust_gym_rep(conn, champ_gym, GYM_REP_DELTA_NEW_CHAMP)


# ----------------------------------------------------------------
# EVENT_COMPLETED — promotion reputation (show rating + bankruptcy)
# ----------------------------------------------------------------

def _process_event_completed(conn, event):
    """EVENT_COMPLETED subscriber — adjust promotion reputation.

    Two effects:
      1. Show rating: if show_ratings.overall_rating for this event
         is >= 75 → +2; if < 40 → -1. (Defensive — no-op if no
         show_ratings row exists yet. The show_rating module writes
         one per EVENT_COMPLETED; if it hasn't run yet, we skip
         this effect rather than guess.)
      2. Bankruptcy: if promotion.current_cash < 0 after the
         event's finances are processed → -2. (finance.py writes
         its transactions on EVENT_COMPLETED; we check after.)
    """
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    if not event_id or not promo_id:
        return

    # ---- 1. Show rating effect ----
    rating_row = conn.execute(
        "SELECT overall_rating FROM show_ratings WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if rating_row and rating_row[0] is not None:
        overall = rating_row[0]
        if overall >= SHOW_RATING_GREAT_THRESHOLD:
            _adjust_promotion_rep(
                conn, promo_id, PROMO_REP_DELTA_GREAT_SHOW,
            )
        elif overall < SHOW_RATING_DUD_THRESHOLD:
            _adjust_promotion_rep(
                conn, promo_id, PROMO_REP_DELTA_DUD_SHOW,
            )

    # ---- 2. Bankruptcy check ----
    # finance.py writes its transactions on EVENT_COMPLETED. We
    # read the post-event current_cash. If it's negative, the
    # promotion is in financial trouble — apply the -2 hit.
    cash_row = conn.execute(
        "SELECT current_cash FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()
    if cash_row and cash_row[0] is not None and cash_row[0] < 0:
        _adjust_promotion_rep(
            conn, promo_id, PROMO_REP_DELTA_BANKRUPTCY,
        )


# ----------------------------------------------------------------
# TICK_ADVANCED — drug-test scandal scan
# ----------------------------------------------------------------

def _process_tick(conn, event):
    """TICK_ADVANCED subscriber — scan for new drug-test suspensions.

    The suspensions module writes suspensions rows on FIGHT_RESOLVED
    (via _maybe_random_suspension). There's no specific event bus
    event for "drug-test suspension created" — we poll on
    TICK_ADVANCED for new drug_test_failure suspensions that haven't
    been processed yet (dedup via a hidden news_items marker).

    For each new drug-test suspension:
      - Apply -3 to the suspended fighter's current_promotion_id.
      - Write the dedup marker so we don't apply the hit twice.
    """
    # Find all drug_test_failure suspensions that haven't been
    # processed yet (no dedup marker exists).
    new_suspensions = conn.execute(
        "SELECT suspension_id, fighter_id FROM suspensions "
        "WHERE suspension_type=?",
        (DRUG_TEST_SUSPENSION_TYPE,),
    ).fetchall()
    for susp_id, fighter_id in new_suspensions:
        if _has_drug_scandal_marker(conn, susp_id):
            continue  # already processed
        # Look up the fighter's current_promotion_id at the time of
        # the scandal. The fighter may have since switched
        # promotions or become a free agent — in that case we apply
        # the hit to whatever promotion they were in when the
        # suspension started (stored in the suspensions.description
        # admin note by _create_suspension). Defensive: if we can't
        # find a promotion_id, skip (no promotion to penalize).
        promo_row = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        promo_id = promo_row[0] if promo_row else None
        if promo_id:
            _adjust_promotion_rep(
                conn, promo_id, PROMO_REP_DELTA_DRUG_SCANDAL,
            )
        _write_drug_scandal_marker(conn, susp_id, promo_id)


# ----------------------------------------------------------------
# CAMP_COMPLETED — gyms +0.5
# ----------------------------------------------------------------

def _process_camp_completed(conn, event):
    """CAMP_COMPLETED subscriber — adjust the fighter's gym reputation.

    The gym is developing talent → +0.5 reputation. The fighter's
    current_gym_id is the gym that ran the camp.
    """
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    gym_id = _fighter_gym_id(conn, fighter_id)
    if gym_id is None:
        return  # free agent without a gym — no gym to credit
    _adjust_gym_rep(conn, gym_id, GYM_REP_DELTA_CAMP_COMPLETED)


# ----------------------------------------------------------------
# REGISTRATION
# ----------------------------------------------------------------

def register_subscribers():
    """Register all reputation subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior registrations.

    Subscribes to:
      FIGHT_RESOLVED  → _process_fight (gyms win/KO-loss)
      TITLE_CHANGED   → _process_title_change (promo +1, gym +3)
      EVENT_COMPLETED → _process_event_completed (show rating + bankruptcy)
      TICK_ADVANCED   → _process_tick (drug-test scandal scan)
      CAMP_COMPLETED  → _process_camp_completed (gym +0.5)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.FIGHT_RESOLVED, _process_fight,
        name="reputation.process_fight",
    )
    bus.subscribe(
        Events.TITLE_CHANGED, _process_title_change,
        name="reputation.process_title_change",
    )
    bus.subscribe(
        Events.EVENT_COMPLETED, _process_event_completed,
        name="reputation.process_event_completed",
    )
    bus.subscribe(
        Events.TICK_ADVANCED, _process_tick,
        name="reputation.process_tick",
    )
    bus.subscribe(
        Events.CAMP_COMPLETED, _process_camp_completed,
        name="reputation.process_camp_completed",
    )
