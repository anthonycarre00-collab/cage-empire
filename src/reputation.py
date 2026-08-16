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
  - EVENT_COMPLETED: Phase F2.3 — 4-tier show-rating deltas:
      overall >= 75 → +3 (great show, was +2)
      overall 60-74 → +1 (good show, NEW tier)
      overall 25-39 → -2 (dud, was -1)
      overall <  25 → -4 (terrible, NEW tier)
      overall 40-59 → no adjustment (average show)
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

import json
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
#
# Phase F2.3 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F2.3) — tightened
# growth/decay tiers. Old: great +2 / dud -1 (only two tiers). New:
# four tiers so a well-run promo can climb (max +36/year at one great
# show/month) and a poorly-run promo can fall fast (max -48/year at
# one terrible show/month). The mid "good" tier (+1) keeps a 60-74
# rated show from being a no-op — it's a small but real lift. The
# new "terrible" tier (-4) makes a 25-or-below disaster hurt enough
# to feel consequential.
PROMO_REP_DELTA_GREAT_SHOW = +3     # show_rating overall >= 75 (was +2)
PROMO_REP_DELTA_GOOD_SHOW = +1      # show_rating overall 60-74 (NEW tier)
PROMO_REP_DELTA_DUD_SHOW = -2       # show_rating overall 25-39 (was -1)
PROMO_REP_DELTA_TERRIBLE_SHOW = -4  # show_rating overall < 25 (NEW tier)
PROMO_REP_DELTA_TITLE_CHANGE = +1   # any title change
PROMO_REP_DELTA_DRUG_SCANDAL = -3   # drug_test_failure suspension
PROMO_REP_DELTA_BANKRUPTCY = -2     # current_cash < 0 after event

# Phase E3.4 — Bankruptcy failure state (per docs/ECON_STAFF_PLAN.md §3.5).
# When current_cash < 0 for 2 CONSECUTIVE monthly ticks:
#   - reputation -15 (was -10 — new owners are unknown, trust is lower)
#   - fan_trust -20 (was -15 — fans are wary of new ownership)
#   - all staff_contracts voided (they leave — new regime, new staff)
#   - top 3 fighters (by salary) request release → set to free agent
#   - 3-5 random fighters leave (uncertainty about new ownership)
#   - news items: "FINANCIAL COLLAPSE: [Promo Name] files for bankruptcy
#     protection" + "A consortium of investors has acquired [Promo]
#     out of receivership. The brand survives; the rebuild begins."
#     (topic='finance', sentiment='negative')
#   - current_cash reset to starting_budget × 0.25 (25% of original —
#     enough to operate but not splurge). For promo 1: $80M × 0.25 = $20M.
#   - is_rebuilding=1, rebuilding_until_date = sim_date + 6 months
#   - PROMOTION_BANKRUPT event fired on the bus
#   - After 6 months: is_rebuilding=0, news: "[Promo] has emerged from
#     receivership. The rebuild is complete."
#
# Fix 2 (v3.23.0 — per docs/DESIGN_REVIEW_E5.md §2): "Promotions don't
# die — they get acquired." A bankrupt promotion is bought by new
# ownership (consortium, wealthy investor, rival promo's parent
# company). The brand survives but with changes.
PROMO_REP_DELTA_BANKRUPTCY_FAILURE = -10  # was -15 — less harsh
PROMO_FAN_TRUST_DELTA_BANKRUPTCY_FAILURE = -15  # was -20 — less harsh
BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED = 3  # was 2 — give promos more time to recover
# NEWS-FINANCE-GYM-LEGACY Issue 7.1 — confirmed at 3 (the brief asked
# for "3+ consecutive months of negative cash flow, was likely 1-2
# months". The pre-fix value was 2; this constant was already raised
# to 3 in the v3.23.0 DESIGN_REVIEW_E5 sweep. The threshold for
# REACHING the CRISIS state (the step before BANKRUPT) is also
# immediate-cash<0 — that stays at 1 month so a sudden catastrophic
# loss still puts the promo on alert, but the BANKRUPT → REBUILDING
# transition now requires 3 full months of sustained insolvency.
BANKRUPTCY_CASH_RESET_FRACTION = 0.50  # was 0.25 — give promos 50% of starting budget (more recovery cash)
BANKRUPTCY_TOP_FIGHTERS_RELEASED = 2  # was 3 — release fewer fighters
BANKRUPTCY_RANDOM_FIGHTERS_RELEASED_MIN = 1  # was 3 — release fewer random fighters
BANKRUPTCY_RANDOM_FIGHTERS_RELEASED_MAX = 3  # was 5 — release fewer random fighters
# Rebuilding period — 6 sim-months after bankruptcy fires. During the
# rebuild, the promo's reputation recovers +1 per monthly tick IF the
# promo ran at least 1 event that month (per the brief's "Reputation
# recovers slowly (+1 per month during rebuild if the promo runs
# events successfully)"). After 6 months, the rebuild is complete.
REBUILDING_PERIOD_MONTHS = 6
REBUILDING_REP_RECOVERY_PER_MONTH = 1

# Bankruptcy warning tracking — stored in player_settings as a JSON
# blob keyed 'bankruptcy_warnings'. Format:
#   {"<promo_id>": <int consecutive_negative_months>}
# Reset to 0 when current_cash >= 0 on a monthly tick. Reaches
# BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED (2) → fires the failure state.
BANKRUPTCY_WARNINGS_SETTING_KEY = "bankruptcy_warnings"

# HW1.4 — Financial state machine (docs/Hardening_Phase.md §HW1.4).
# 7 states track a promo's financial health lifecycle:
#
#   HEALTHY → PRESSURED → STRUGGLING → CRISIS → BANKRUPT → REBUILDING → RECOVERING → HEALTHY
#
# Transitions (monthly tick):
#   HEALTHY → PRESSURED:  cash < starting_budget × 0.20 for 2 consecutive months
#   PRESSURED → STRUGGLING: cash < starting_budget × 0.10 for 2 consecutive months
#   STRUGGLING → CRISIS:  cash < 0 for 1 month (immediate — no 2-month requirement)
#   CRISIS → BANKRUPT:    cash < 0 for BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED (3) months
#                         (existing _fire_bankruptcy_failure fires here)
#   BANKRUPT → REBUILDING: immediate (handled inside _fire_bankruptcy_failure — sets
#                          financial_state='REBUILDING' alongside is_rebuilding=1)
#   REBUILDING → RECOVERING: existing _check_rebuilding_status clears is_rebuilding
#                            when rebuilding_until_date is reached; this module sets
#                            financial_state='RECOVERING' at the same time.
#   RECOVERING → HEALTHY: cash > starting_budget × 0.50 on a monthly tick
#
# Each forward transition writes a voice-compliant news item (topic='finance').
# Consequences (applied at transition time):
#   PRESSURED:  no immediate consequence beyond the news item (the player
#               must self-correct; the -10% marketing spend consequence
#               is applied as a flag the next event_scheduler reads —
#               the player's NEXT scheduled event has marketing_spend × 0.9).
#   STRUGGLING: release 1 staff member (terminate lowest-skill active
#               staff contract for this promo). Mirrors the bankruptcy
#               release pathway but smaller in scope.
#   CRISIS:     sign_free_agent() in app_web.py refuses new signings
#               when financial_state == 'CRISIS' (HW1.3 — the player
#               must trade their way out of crisis, not sign their way out).
#   BANKRUPT:   handled by _fire_bankruptcy_failure (existing).
#   REBUILDING: +1 reputation/month if the promo ran an event (existing
#               _process_rebuilding_recovery).
#   RECOVERING: no consequence — the promo is on the mend.
#
# Counters persisted via player_settings JSON blob keyed
# 'financial_state_counters':
#   {"<promo_id>": {"pressured_months": <int>, "struggling_months": <int>}}
# Reset to 0 when the cash threshold is no longer met. The CRISIS counter
# is the existing 'bankruptcy_warnings' blob (single int per promo).
FINANCIAL_STATE_THRESHOLDS = {
    "PRESSURED_THRESHOLD":  0.20,   # cash < starting_budget × 0.20
    "STRUGGLING_THRESHOLD": 0.10,   # cash < starting_budget × 0.10
    "RECOVERY_THRESHOLD":   0.50,   # cash > starting_budget × 0.50 → HEALTHY
}
FINANCIAL_STATE_CONSECUTIVE_MONTHS = {
    "PRESSURED":  2,  # 2 months below 0.20 × starting_budget
    "STRUGGLING": 2,  # 2 months below 0.10 × starting_budget
}
FINANCIAL_STATE_COUNTERS_SETTING_KEY = "financial_state_counters"
# Voice-compliant news body templates. Sentiment + topic follow the
# existing pattern (topic='finance', sentiment='negative'/'positive').
_FINANCIAL_STATE_NEWS = {
    "PRESSURED": {
        "headline": "{promo} feeling the financial squeeze",
        "body": (
            "Cash reserves at {promo} have dropped below 20% of the "
            "promotion's starting budget for the second consecutive "
            "month. Marketing spend on the next event will be trimmed "
            "to conserve cash."
        ),
        "sentiment": "negative",
    },
    "STRUGGLING": {
        "headline": "{promo} slashes costs as losses mount",
        "body": (
            "With cash now below 10% of the starting budget for two "
            "months running, {promo} has released a staff member to "
            "stem the bleeding. The promotion is in serious trouble."
        ),
        "sentiment": "negative",
    },
    "CRISIS": {
        "headline": "{promo} enters financial crisis",
        "body": (
            "{promo} is operating at a loss — current_cash has gone "
            "negative. Free agent signings are frozen while the "
            "promotion fights to survive. Three consecutive months "
            "in the red will trigger bankruptcy proceedings."
        ),
        "sentiment": "negative",
    },
    "BANKRUPT": {
        # The bankruptcy news is written by _write_bankruptcy_news
        # (the "FINANCIAL COLLAPSE" headline). We don't write a
        # duplicate here — _fire_bankruptcy_failure owns this state's
        # news. This entry exists only for completeness of the dict.
        "headline": None,
        "body": None,
        "sentiment": "negative",
    },
    "RECOVERING": {
        "headline": "{promo} emerges from receivership",
        "body": (
            "The rebuilding period at {promo} has come to an end. "
            "New ownership has stabilised the brand — the promotion "
            "is now in recovery, climbing back toward solvency."
        ),
        "sentiment": "positive",
    },
    "HEALTHY": {
        "headline": "{promo} returns to financial health",
        "body": (
            "After a difficult stretch, {promo} has rebuilt its cash "
            "reserves past the 50% mark of the starting budget. The "
            "promotion is once again on solid financial footing."
        ),
        "sentiment": "positive",
    },
}

# Gym reputation deltas (per the brief).
GYM_REP_DELTA_WIN = +1              # fighter from this gym wins
GYM_REP_DELTA_KO_LOSS = -1          # fighter from this gym loses by KO
GYM_REP_DELTA_NEW_CHAMP = +3        # fighter from this gym wins a title
GYM_REP_DELTA_CAMP_COMPLETED = 0.5  # the gym is developing talent

# Show-rating thresholds for promotion reputation.
#
# Phase F2.3 — split the old single DUD threshold (40) into TWO tiers:
#   SHOW_RATING_GOOD_THRESHOLD (60): >= this and < GREAT → +1 (good show)
#   SHOW_RATING_DUD_THRESHOLD (40): >= this and < GOOD → no adjustment
#   SHOW_RATING_TERRIBLE_THRESHOLD (25): < this → -4 (terrible)
#   Between DUD and TERRIBLE (25-39) → -2 (dud — was the old -1)
#
# The [10, 95] clamp on reputation (REP_FLOOR / REP_CEIL below)
# means a promo at 95 can't grow past 95 even with consecutive great
# shows, and a promo at 10 can't decay past 10 even with consecutive
# terrible shows. This keeps reputation impactful without breaking
# the sim (per the original brief).
SHOW_RATING_GREAT_THRESHOLD = 75
SHOW_RATING_GOOD_THRESHOLD = 60
SHOW_RATING_DUD_THRESHOLD = 40
SHOW_RATING_TERRIBLE_THRESHOLD = 25

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

    CR-13 fix: omit ``published_at`` from the INSERT so the column's
    ``DEFAULT CURRENT_TIMESTAMP`` applies (was passing ``None`` which
    overrode the default → NOT NULL violation every tick). Also
    defensively ensure the System Feed source exists before inserting
    (mirrors the pattern in tick_processor.py / career_arc.py / etc.).
    """
    if suspension_id is None:
        return
    marker = f"[suspension_id={suspension_id}:drug_scandal]"
    # Defensively ensure System Feed source exists (INSERT OR IGNORE —
    # matches the codebase convention; news_sources has no source_type
    # column, only name + 6 credibility/etc. metrics).
    conn.execute(
        "INSERT OR IGNORE INTO news_sources (name, credibility, "
        "sensationalism, bias, regional_reach, reliability, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("System Feed", 70, 40, 50, 60, 80, 80),
    )
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    src_id = src_row[0] if src_row else None
    if src_id is None:
        # Still no source — bail gracefully rather than crash
        return
    # CR-13 fix: omit published_at from INSERT — let DEFAULT
    # CURRENT_TIMESTAMP apply (was passing None which overrode the
    # default → NOT NULL violation every tick).
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, promotion_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, "[reputation marker]", marker, "neutral",
         _REPUTATION_MARKER_TOPIC, None, promotion_id),
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
      1. Show rating: Phase F2.3 — 4-tier growth/decay.
         - show_ratings.overall_rating >= 75 → +3 (great show)
         - 60 <= overall < 75 → +1 (good show)
         - 25 <= overall < 40 → -2 (dud)
         - overall < 25 → -4 (terrible)
         - 40 <= overall < 60 → no adjustment (average show)
         (Defensive — no-op if no show_ratings row exists yet. The
         show_rating module writes one per EVENT_COMPLETED; if it
         hasn't run yet, we skip this effect rather than guess.)
      2. Bankruptcy: if promotion.current_cash < 0 after the
         event's finances are processed → -2. (finance.py writes
         its transactions on EVENT_COMPLETED; we check after.)
    """
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    if not event_id or not promo_id:
        return

    # ---- 1. Show rating effect ----
    # Phase F2.3 — 4-tier growth/decay (was 2-tier great/dud). The
    # tiers (per docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F2.3):
    #   rating >= 75 → +3 (great show — was +2)
    #   rating 60-74 → +1 (good show — NEW tier)
    #   rating 25-39 → -2 (dud — was -1)
    #   rating <  25 → -4 (terrible — NEW tier)
    #   rating 40-59 → no adjustment (average show — neither helps nor hurts)
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
        elif overall >= SHOW_RATING_GOOD_THRESHOLD:
            _adjust_promotion_rep(
                conn, promo_id, PROMO_REP_DELTA_GOOD_SHOW,
            )
        elif overall < SHOW_RATING_TERRIBLE_THRESHOLD:
            _adjust_promotion_rep(
                conn, promo_id, PROMO_REP_DELTA_TERRIBLE_SHOW,
            )
        elif overall < SHOW_RATING_DUD_THRESHOLD:
            _adjust_promotion_rep(
                conn, promo_id, PROMO_REP_DELTA_DUD_SHOW,
            )
        # else: 25 <= overall < 40 covered by the < DUD branch above;
        # 40 <= overall < 60 → no adjustment (average show).

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
    """TICK_ADVANCED subscriber — scan for new drug-test suspensions +
    Phase E3.4 bankruptcy failure state check.

    Two effects:

    1. Drug-test scandal scan (Phase E1):
       The suspensions module writes suspensions rows on FIGHT_RESOLVED
       (via _maybe_random_suspension). There's no specific event bus
       event for "drug-test suspension created" — we poll on
       TICK_ADVANCED for new drug_test_failure suspensions that haven't
       been processed yet (dedup via a hidden news_items marker).

       For each new drug-test suspension:
         - Apply -3 to the suspended fighter's current_promotion_id.
         - Write the dedup marker so we don't apply the hit twice.

    2. Bankruptcy failure state (Phase E3.4):
       On monthly ticks (current_day % 30 == 0), check each promo's
       current_cash. If negative, increment that promo's
       consecutive_negative_months counter (stored in player_settings
       as a JSON blob). When the counter reaches
       BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED (2), fire the failure
       state: -10 reputation, -15 fan_trust, void staff contracts,
       release top 3 fighters, write a voice-compliant news item,
       reset current_cash to $1M, fire PROMOTION_BANKRUPT event.

       Per docs/ECON_STAFF_PLAN.md §3.5. This is the failure mode
       that makes the player's financial levers (Phase E3.1-E3.3)
       meaningful — without it, the player can over-spend with no
       consequence beyond the small -2 per-event bankruptcy hit.
    """
    # ---- 1. Drug-test scandal scan (Phase E1) ----
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

    # ---- 2. Bankruptcy failure state check (Phase E3.4 + Fix 2) ----
    # Only fires on monthly ticks. The tick_processor advances
    # current_day by 1 each day; current_day % 30 == 0 catches day
    # 30, 60, 90, ... (i.e., end-of-month boundary). Defensive: if
    # the event payload doesn't include current_day, we read it
    # from the simulation_clock table directly.
    current_day = event.get("current_day") if event else None
    if current_day is None:
        # Read from the DB if the event payload didn't include it.
        clock_row = conn.execute(
            "SELECT current_day FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        current_day = clock_row[0] if clock_row else None
    if current_day is None or current_day % 30 != 0:
        return  # not a monthly tick — skip the bankruptcy scan

    # ---- 2a. HW1.4 — Financial state machine (runs BEFORE the
    # bankruptcy check so the HEALTHY → PRESSURED → STRUGGLING → CRISIS
    # progression is reflected before _check_bankruptcy_failure reads
    # the counter and decides whether to fire BANKRUPT).
    _check_financial_state_transitions(conn)

    _check_bankruptcy_failure(conn)

    # ---- 3. Rebuilding period check (Fix 2 — v3.23.0) ----
    # On the same monthly tick, check each rebuilding promo: if the
    # rebuilding_until_date has been reached, clear is_rebuilding +
    # write the 'rebuild complete' news item. Also apply +1 reputation
    # recovery to rebuilding promos that ran >= 1 event this month
    # (per docs/DESIGN_REVIEW_E5.md §2 step 4). Both helpers are
    # defensive — they no-op if no promos are currently rebuilding.
    clock_date_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    current_date_str = clock_date_row[0] if clock_date_row else None
    if current_date_str:
        _process_rebuilding_recovery(conn, current_date_str)
        _check_rebuilding_status(conn, current_date_str)


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
# Phase E3.4 — Bankruptcy failure state helpers
# ----------------------------------------------------------------

def _load_bankruptcy_warnings(conn):
    """Load the bankruptcy_warnings JSON blob from player_settings.

    Returns a dict mapping promo_id (as str key) → consecutive
    negative months (int). Empty dict if the setting doesn't exist
    or is malformed.
    """
    row = conn.execute(
        "SELECT setting_value FROM player_settings WHERE setting_key=?",
        (BANKRUPTCY_WARNINGS_SETTING_KEY,),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        d = json.loads(row[0])
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save_bankruptcy_warnings(conn, warnings):
    """Persist the bankruptcy_warnings dict back to player_settings."""
    conn.execute(
        "INSERT OR REPLACE INTO player_settings (setting_key, setting_value) "
        "VALUES (?, ?)",
        (BANKRUPTCY_WARNINGS_SETTING_KEY, json.dumps(warnings)),
    )


def _adjust_promotion_fan_trust(conn, promotion_id, delta):
    """Adjust a promotion's fan_trust by delta, clamped to [0, 100].

    Defensive — silently no-ops if the promotion doesn't exist.
    fan_trust has a CHECK [0, 100] constraint per the schema.
    """
    if not promotion_id or delta == 0:
        return
    row = conn.execute(
        "SELECT fan_trust FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if not row:
        return
    current = row[0] if row[0] is not None else 50
    new_val = max(0, min(100, current + delta))
    conn.execute(
        "UPDATE promotions SET fan_trust=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE promotion_id=?",
        (new_val, promotion_id),
    )


def _release_top_fighters(conn, promotion_id, n=3):
    """Release the top N fighters (by salary) from a promotion.

    Sets current_promotion_id = NULL (making them free agents) and
    terminates their active contracts. Per docs/ECON_STAFF_PLAN.md
    §3.5: "top 3 fighters (by salary) request release" — they see
    the sinking ship and ask out.

    Returns the list of released fighter_ids (for the news item /
    event payload).
    """
    # Find the top N fighters by active-contract salary on this promo.
    top_rows = conn.execute(
        "SELECT fc.fighter_id, c.salary, f.first_name, f.last_name "
        "FROM fighter_contracts fc "
        "JOIN contracts c ON c.contract_id=fc.contract_id "
        "JOIN fighters f ON f.fighter_id=fc.fighter_id "
        "WHERE c.promotion_id=? AND c.status='active' "
        "  AND f.current_promotion_id=? AND f.is_active=1 "
        "ORDER BY c.salary DESC LIMIT ?",
        (promotion_id, promotion_id, n),
    ).fetchall()
    released = []
    for fid, _salary, _fn, _ln in top_rows:
        # Set fighter to free agent
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (fid,),
        )
        # Terminate the active contract(s)
        conn.execute(
            "UPDATE contracts SET status='terminated', "
            "updated_at=CURRENT_TIMESTAMP "
            "WHERE contract_id IN ("
            "  SELECT fc.contract_id FROM fighter_contracts fc "
            "  WHERE fc.fighter_id=?"
            ") AND status='active'",
            (fid,),
        )
        released.append(fid)
    return released


def _release_random_fighters(conn, promotion_id, already_released, n_min=3,
                              n_max=5):
    """Release N random fighters from a promotion (excluding those
    already released via _release_top_fighters).

    Per docs/DESIGN_REVIEW_E5.md §2 step 3: "3-5 random fighters leave
    (uncertainty about new ownership)". These are mid-tier fighters who
    aren't the top earners (already released) but get jittery about the
    new regime and ask out anyway.

    Sets current_promotion_id = NULL + terminates active contracts
    (same pattern as _release_top_fighters). Returns the list of
    released fighter_ids (excluding the already_released set).
    """
    # Build the exclusion placeholder list for the SQL query.
    excluded = set(already_released or [])
    # Pick a random count in [n_min, n_max]. Seeded by promotion_id so
    # the count is deterministic per-bankruptcy-event for testability.
    rng = random.Random(promotion_id * 17 + 31)
    n = rng.randint(n_min, n_max)
    # Fetch eligible fighters (active, on this promo, not in excluded).
    # We use is_active=1 to skip retired/inactive fighters.
    placeholders = ()
    exclude_clause = ""
    if excluded:
        placeholders = tuple(excluded)
        exclude_clause = (
            " AND f.fighter_id NOT IN (" + ",".join("?" * len(excluded)) + ")"
        )
    eligible_rows = conn.execute(
        "SELECT f.fighter_id FROM fighters f "
        "WHERE f.current_promotion_id=? AND f.is_active=1 "
        + exclude_clause,
        (promotion_id,) + placeholders,
    ).fetchall()
    if not eligible_rows:
        return []
    # Sample min(n, len(eligible)) fighter_ids.
    eligible_ids = [r[0] for r in eligible_rows]
    actual_n = min(n, len(eligible_ids))
    chosen = rng.sample(eligible_ids, actual_n)
    released = []
    for fid in chosen:
        conn.execute(
            "UPDATE fighters SET current_promotion_id=NULL, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (fid,),
        )
        conn.execute(
            "UPDATE contracts SET status='terminated', "
            "updated_at=CURRENT_TIMESTAMP "
            "WHERE contract_id IN ("
            "  SELECT fc.contract_id FROM fighter_contracts fc "
            "  WHERE fc.fighter_id=?"
            ") AND status='active'",
            (fid,),
        )
        released.append(fid)
    return released


def _set_rebuilding_flag(conn, promotion_id, sim_date):
    """Mark a promotion as 'rebuilding' for REBUILDING_PERIOD_MONTHS
    (6) sim-months from sim_date.

    Per docs/DESIGN_REVIEW_E5.md §2 step 3:
      - is_rebuilding = 1
      - rebuilding_until_date = sim_date + 6 months

    The +6 months is computed via a simple month + 6 with year rollover
    (no external deps). The rebuilding period ends on the first monthly
    tick where current_date >= rebuilding_until_date.
    """
    if not sim_date:
        # Defensive — read from the simulation_clock if not provided.
        clock_row = conn.execute(
            "SELECT current_date FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        sim_date = clock_row[0] if clock_row else None
    if not sim_date:
        return  # nothing we can do without a date
    # Compute sim_date + 6 months (year rollover if month > 12).
    # Format: 'YYYY-MM-DD'. We preserve the day-of-month (clamped to
    # 28 to avoid invalid dates like 'YYYY-02-30').
    try:
        y_str, m_str, d_str = sim_date.split("-")
        y, m, d = int(y_str), int(m_str), int(d_str)
    except (ValueError, AttributeError):
        # Defensive — bail gracefully if the date isn't ISO format.
        return
    new_m = m + REBUILDING_PERIOD_MONTHS
    new_y = y
    while new_m > 12:
        new_m -= 12
        new_y += 1
    # Clamp day to 28 (no month has fewer than 28 days).
    new_d = min(d, 28)
    until_date = f"{new_y:04d}-{new_m:02d}-{new_d:02d}"
    conn.execute(
        "UPDATE promotions SET is_rebuilding=1, rebuilding_until_date=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
        (until_date, promotion_id),
    )


def _check_rebuilding_status(conn, current_date):
    """Monthly-tick helper: check each rebuilding promo for completion.

    For each promo with is_rebuilding=1 AND rebuilding_until_date <=
    current_date:
      - Set is_rebuilding=0, rebuilding_until_date=NULL.
      - Write a 'rebuild complete' news item (voice-compliant) via
        news.generate_rebuild_complete_news.

    Per docs/DESIGN_REVIEW_E5.md §2 step 4: "After 6 months:
    is_rebuilding=0, news: '[Promo] has emerged from receivership.
    The rebuild is complete.'"

    Defensive: if rebuilding_until_date is NULL but is_rebuilding=1
    (corrupt state — shouldn't happen, but the schema allows it),
    we clear the flag without writing the news item.
    """
    rows = conn.execute(
        "SELECT promotion_id, name, rebuilding_until_date "
        "FROM promotions WHERE is_rebuilding=1"
    ).fetchall()
    for promo_id, promo_name, until_date in rows:
        if not until_date:
            # Defensive — clear the flag without news.
            conn.execute(
                "UPDATE promotions SET is_rebuilding=0, "
                "rebuilding_until_date=NULL, "
                "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
                (promo_id,),
            )
            continue
        if until_date <= current_date:
            # Rebuilding period complete.
            conn.execute(
                "UPDATE promotions SET is_rebuilding=0, "
                "rebuilding_until_date=NULL, "
                "financial_state='RECOVERING', "
                "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
                (promo_id,),
            )
            # NEWS-FINANCE-GYM-LEGACY Issue 7.2 — clear the cash-
            # injection flag so a future bankruptcy on this promo is
            # eligible for the "new ownership" injection again.
            try:
                _clear_rebuilding_injection_flag(conn, promo_id)
            except Exception as e:
                print(f"[reputation._check_rebuilding_status] WARN: "
                      f"clear injection flag failed for promo "
                      f"{promo_id}: {e}", flush=True)
            try:
                from news import generate_rebuild_complete_news
                generate_rebuild_complete_news(
                    conn, promo_id, promo_name, sim_date=current_date,
                )
            except Exception as e:
                # Defensive — news failure shouldn't break the flow.
                print(f"[reputation._check_rebuilding_status] WARN: "
                      f"rebuild complete news write failed: {e}",
                      flush=True)


def _process_rebuilding_recovery(conn, current_date):
    """Monthly-tick helper: apply +1 reputation to rebuilding promos
    that ran >= 1 event this month.

    Per docs/DESIGN_REVIEW_E5.md §2 step 4: "Reputation recovers
    slowly (+1 per month during rebuild if the promo runs events
    successfully)."

    "This month" = the 30-day window ending at current_date. A promo
    ran an event if it has a completed event with event_date in
    [current_date - 30 days, current_date].

    Defensive: only applies to promos with is_rebuilding=1. The rep
    gain is small (+1) and clamped to REP_CEIL by _adjust_promotion_
    rep. A "rebuild continues" news item is also written.

    NEWS-FINANCE-GYM-LEGACY Issue 7.2 — also calls
    _process_rebuilding_cash_injection to apply the one-time "new
    ownership" cash injection 3 months into the rebuilding period.
    """
    # Compute the 30-day window start (ISO date string).
    try:
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(current_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=30)
        start_str = start_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return  # defensive — bail on bad date

    rows = conn.execute(
        "SELECT promotion_id, name FROM promotions WHERE is_rebuilding=1"
    ).fetchall()
    for promo_id, promo_name in rows:
        # Check if the promo ran >= 1 completed event in the last 30
        # days. event_date is TEXT (ISO 'YYYY-MM-DD') so a string
        # comparison works (lexicographic == chronological for ISO
        # dates).
        ran_event = conn.execute(
            "SELECT 1 FROM events "
            "WHERE promotion_id=? AND status='completed' "
            "  AND event_date >= ? AND event_date <= ? "
            "LIMIT 1",
            (promo_id, start_str, current_date),
        ).fetchone()
        if not ran_event:
            continue  # no events this month — no rep gain, no news
        _adjust_promotion_rep(
            conn, promo_id, REBUILDING_REP_RECOVERY_PER_MONTH,
        )
        try:
            from news import generate_rebuild_continues_news
            generate_rebuild_continues_news(
                conn, promo_id, promo_name, sim_date=current_date,
            )
        except Exception as e:
            # Defensive — news failure shouldn't break the recovery flow.
            print(f"[reputation._process_rebuilding_recovery] WARN: "
                  f"rebuild continues news write failed: {e}",
                  flush=True)

    # NEWS-FINANCE-GYM-LEGACY Issue 7.2 — apply the one-time "new
    # ownership" cash injection 3 months into the rebuilding period.
    # Called once per monthly tick AFTER the per-promo reputation
    # loop so the cash injection doesn't gate the rep gain.
    try:
        _process_rebuilding_cash_injection(conn, current_date)
    except Exception as e:
        print(f"[reputation._process_rebuilding_recovery] WARN: "
              f"cash injection failed: {e}", flush=True)


# ----------------------------------------------------------------
# NEWS-FINANCE-GYM-LEGACY Issue 7.2 — Rebuilding cash injection.
#
# Per the brief: "When a promotion is in REBUILDING, give them a
# cash injection after 3 months (the 'new ownership' narrative):
# +$2M for small, +$5M for mid, +$10M for major."
#
# A bankrupt promo gets current_cash reset to 50% of starting_budget
# at bankruptcy time. 3 months later, "new ownership" injects fresh
# capital to keep the recovery viable. This is applied ONCE per
# bankruptcy event (tracked via the rebuilding_cash_injections
# player_settings JSON blob).
# ----------------------------------------------------------------

# Cash injection amount by promo size_tier.
REBUILDING_CASH_INJECTION_BY_TIER = {
    "major": 10_000_000,
    "mid":    5_000_000,
    "small":  2_000_000,
}
# Months into the rebuilding period before the injection fires.
# The rebuilding period itself is 6 months (REBUILDING_PERIOD_MONTHS).
# At month 3 (halfway), new ownership injects capital.
REBUILDING_CASH_INJECTION_MONTH = 3
REBUILDING_INJECTIONS_SETTING_KEY = "rebuilding_cash_injections"


def _load_rebuilding_injections(conn):
    """Return the dict of promo_id (as str) → injection_applied_flag.

    A promo's entry is set to 1 once the cash injection fires. Cleared
    when the rebuilding period completes (so a future bankruptcy on
    the same promo is eligible again).
    """
    row = conn.execute(
        "SELECT setting_value FROM player_settings WHERE setting_key=?",
        (REBUILDING_INJECTIONS_SETTING_KEY,),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        d = json.loads(row[0])
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save_rebuilding_injections(conn, injections):
    """Persist the rebuilding_cash_injections dict back to player_settings."""
    conn.execute(
        "INSERT OR REPLACE INTO player_settings (setting_key, setting_value) "
        "VALUES (?, ?)",
        (REBUILDING_INJECTIONS_SETTING_KEY, json.dumps(injections)),
    )


def _process_rebuilding_cash_injection(conn, current_date):
    """Apply the one-time "new ownership" cash injection to rebuilding
    promos that are >= 3 months into their rebuilding period.

    For each promo with is_rebuilding=1:
      1. Compute months_since_bankruptcy by subtracting
         (REBUILDING_PERIOD_MONTHS) from rebuilding_until_date and
         diffing against current_date.
      2. If months_since_bankruptcy >= 3 AND the promo hasn't already
         received the injection (tracked in player_settings):
           - Read size_tier, look up the injection amount.
           - UPDATE promotions.current_cash += amount.
           - Record a finance_transactions row of type 'sponsorship'
             (the closest existing transaction_type for an inflow)
             with description "New ownership capital injection".
           - Mark the injection applied in player_settings.
           - Write a 'finance' news item announcing the injection.

    Defensive — every step is wrapped so a failure on one promo
    doesn't block the others. The injection is applied at most once
    per bankruptcy event; when the rebuilding period ends (handled
    by _check_rebuilding_status), the entry is cleared so a future
    bankruptcy on the same promo is eligible again.
    """
    try:
        from datetime import datetime
        current_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return  # bad date — bail

    rows = conn.execute(
        "SELECT promotion_id, name, size_tier, current_cash, "
        "rebuilding_until_date "
        "FROM promotions WHERE is_rebuilding=1"
    ).fetchall()
    if not rows:
        return
    injections = _load_rebuilding_injections(conn)
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    src_id = src_row[0] if src_row else None
    if src_id is None:
        try:
            src_id = conn.execute(
                "INSERT INTO news_sources (name, credibility, "
                "sensationalism, bias, regional_reach, reliability, "
                "frequency) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("System Feed", 70, 40, 50, 60, 80, 80),
            ).lastrowid
        except Exception:
            src_id = None

    for promo_id, promo_name, size_tier, current_cash, until_date in rows:
        if not until_date:
            continue
        # Compute months_since_bankruptcy. The bankruptcy fired at
        # (until_date - REBUILDING_PERIOD_MONTHS) months. We use a
        # simple month-arithmetic helper (no external deps).
        try:
            uy, um, ud = (int(x) for x in until_date.split("-"))
        except (ValueError, AttributeError):
            continue
        # Bankruptcy month = um - REBUILDING_PERIOD_MONTHS (with year
        # rollover).
        bank_m = um - REBUILDING_PERIOD_MONTHS
        bank_y = uy
        while bank_m <= 0:
            bank_m += 12
            bank_y -= 1
        # Months since bankruptcy = (current_year - bank_year) * 12 +
        # (current_month - bank_month). Defensive — clamp to >= 0.
        cy, cm = current_dt.year, current_dt.month
        months_since = (cy - bank_y) * 12 + (cm - bank_m)
        if months_since < REBUILDING_CASH_INJECTION_MONTH:
            continue  # not yet at month 3
        key = str(promo_id)
        if injections.get(key, 0) == 1:
            continue  # already injected — skip
        amount = REBUILDING_CASH_INJECTION_BY_TIER.get(
            size_tier, REBUILDING_CASH_INJECTION_BY_TIER["small"],
        )
        new_cash = (current_cash or 0) + amount
        try:
            conn.execute(
                "UPDATE promotions SET current_cash=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
                (new_cash, promo_id),
            )
        except Exception as e:
            print(f"[reputation._process_rebuilding_cash_injection] "
                  f"WARN: cash UPDATE failed for promo {promo_id}: "
                  f"{e}", flush=True)
            continue
        # Record the inflow as a finance_transactions row (use
        # 'sponsorship' type — closest existing inflow type).
        try:
            conn.execute(
                "INSERT INTO finance_transactions (promotion_id, "
                "transaction_type, amount, description, "
                "transaction_date) VALUES (?, 'sponsorship', ?, "
                "'New ownership capital injection', ?)",
                (promo_id, amount, current_date),
            )
        except Exception as e:
            print(f"[reputation._process_rebuilding_cash_injection] "
                  f"WARN: finance_transactions INSERT failed for "
                  f"promo {promo_id}: {e}", flush=True)
        # Write a 'finance' news item announcing the injection.
        if src_id is not None:
            try:
                # Format amount as $XM / $XK for voice compliance.
                if amount >= 1_000_000:
                    amount_str = f"${amount / 1_000_000:.0f} million"
                else:
                    amount_str = f"${amount / 1_000:.0f}K"
                headline = (f"New ownership injects capital into "
                            f"{promo_name}")
                body = (
                    f"The new ownership group behind {promo_name} "
                    f"has injected {amount_str} in fresh capital — "
                    f"a show of faith three months into the rebuild. "
                    f"The promotion's recovery now has the runway "
                    f"to plan a return card."
                )
                conn.execute(
                    "INSERT INTO news_items (news_source_id, headline, "
                    "body, sentiment, topic, promotion_id, "
                    "published_at, importance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (src_id, headline, body, "positive", "finance",
                     promo_id, current_date, "MAJOR"),
                )
            except Exception as e:
                print(f"[reputation._process_rebuilding_cash_injection] "
                      f"WARN: news INSERT failed for promo {promo_id}: "
                      f"{e}", flush=True)
        # Mark the injection applied.
        injections[key] = 1
    _save_rebuilding_injections(conn, injections)


def _clear_rebuilding_injection_flag(conn, promotion_id):
    """Clear the cash-injection flag for a promo whose rebuilding
    period just completed (so a future bankruptcy is eligible again).

    Called by _check_rebuilding_status when is_rebuilding flips to 0.
    """
    injections = _load_rebuilding_injections(conn)
    key = str(promotion_id)
    if key in injections:
        del injections[key]
        _save_rebuilding_injections(conn, injections)


def _void_staff_contracts(conn, promotion_id):
    """Void all active staff_contracts for a promotion.

    Sets status='terminated' on every active contract tied to a
    staff_contracts row for this promo. Per docs/ECON_STAFF_PLAN.md
    §3.5: "all staff contracts voided" — staff leave a bankrupt
    promotion.

    Returns the count of voided contracts.
    """
    cur = conn.execute(
        "UPDATE contracts SET status='terminated', "
        "updated_at=CURRENT_TIMESTAMP "
        "WHERE contract_id IN ("
        "  SELECT sc.contract_id FROM staff_contracts sc "
        "  WHERE sc.staff_id IN ("
        "    SELECT staff_id FROM staff WHERE role_type IS NOT NULL"
        "  )"
        ") AND promotion_id=? AND status='active'",
        (promotion_id,),
    )
    return cur.rowcount or 0


def _write_bankruptcy_news(conn, promotion_id, promo_name):
    """Write the bankruptcy news item (voice-compliant).

    Per docs/PHASE_E3_PLAN.md §1.E3.4 + VOICE_ENFORCEMENT.md:
      - 'FINANCIAL COLLAPSE: [Promo Name] files for bankruptcy
        protection' (factual, no tabloid clichés)
      - topic='finance', sentiment='negative'

    Fix 2 (v3.23.0 — per docs/DESIGN_REVIEW_E5.md §2): now writes
    TWO news items, the second via news.generate_new_ownership_news:
      - Item 1: 'FINANCIAL COLLAPSE: [Promo] files for bankruptcy
        protection' (factual).
      - Item 2: 'New ownership group takes control of [Promo]' —
        the "consortium of investors" narrative (business-page
        register, NOT tabloid).

    VOICE COMPLIANCE: 'FINANCIAL COLLAPSE' is OK (factual). The
    explicitly-forbidden alternatives are tabloid-style:
      'SHOCKING: [Promo] goes BUST!' — NOT OK
      'BLOCKBUSTER: [Promo] BANKRUPT!' — NOT OK
    'A consortium of investors' is the right register — business-
    page, not gossip column.
    """
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if src_row is None:
        # Defensive — create the System Feed source if missing.
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]
    # Read the current sim date for the news timestamp.
    clock_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = clock_row[0] if clock_row else None
    headline = f"FINANCIAL COLLAPSE: {promo_name} files for bankruptcy protection"
    body = (
        f"{promo_name} has filed for bankruptcy protection after "
        f"sustaining heavy losses. The promotion's top fighters have "
        f"requested release, staff contracts have been voided, and "
        f"the brand has taken a severe reputation hit. Recovery will "
        f"require deep austerity — cheaper shows, leaner payroll, "
        f"and a willingness to rebuild from the bottom."
    )
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "negative", "finance",
         promotion_id, sim_date),
    )
    # Fix 2 — item #2 of the 2-item narrative: the "new ownership"
    # article. Voice-compliant per VOICE_ENFORCEMENT.md — business-page
    # register, factual, no tabloid clichés.
    try:
        from news import generate_new_ownership_news
        generate_new_ownership_news(
            conn, promotion_id, promo_name, sim_date=sim_date,
        )
    except Exception as e:
        # Defensive — news failure shouldn't break the bankruptcy flow.
        print(f"[reputation._write_bankruptcy_news] WARN: new ownership "
              f"news write failed: {e}", flush=True)


def _check_bankruptcy_failure(conn):
    """Phase E3.4 — check all promotions for the bankruptcy failure state.

    Called on monthly ticks (current_day % 30 == 0) by _process_tick.

    For each promotion:
      - If current_cash < 0: increment its consecutive_negative_months
        counter. If the counter reaches
        BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED (2), fire the failure
        state:
            - reputation -10
            - fan_trust -15
            - all staff_contracts voided (status='terminated')
            - top 3 fighters (by salary) released → free agents
            - news item written (voice-compliant)
            - current_cash reset to $1M (so the player can recover)
            - PROMOTION_BANKRUPT event fired on the bus
            - counter reset to 0
      - If current_cash >= 0: reset its counter to 0 (one good month
        clears the warning).

    The counter persists across ticks via player_settings (JSON blob
    keyed 'bankruptcy_warnings'). This survives app restarts and is
    idempotent under re-runs of the same tick.
    """
    warnings = _load_bankruptcy_warnings(conn)
    promos = conn.execute(
        "SELECT promotion_id, name, current_cash, reputation, fan_trust "
        "FROM promotions"
    ).fetchall()
    for promo_id, promo_name, current_cash, _rep, _trust in promos:
        if current_cash is None:
            continue
        key = str(promo_id)
        if current_cash < 0:
            warnings[key] = warnings.get(key, 0) + 1
            if warnings[key] >= BANKRUPTCY_CONSECUTIVE_MONTHS_REQUIRED:
                # ---- FIRE THE FAILURE STATE ----
                _fire_bankruptcy_failure(conn, promo_id, promo_name)
                warnings[key] = 0  # reset after firing
        else:
            warnings[key] = 0  # good month — clear the warning
    _save_bankruptcy_warnings(conn, warnings)


def _fire_bankruptcy_failure(conn, promotion_id, promo_name):
    """Phase E3.4 + Fix 2 — execute the bankruptcy failure state.

    Per docs/ECON_STAFF_PLAN.md §3.5 + docs/DESIGN_REVIEW_E5.md §2:
      - reputation -15 (was -10 — new owners are unknown, trust lower)
      - fan_trust -20 (was -15 — fans are wary of new ownership)
      - all staff_contracts voided (they leave — new regime, new staff)
      - top 3 fighters (by salary) released → free agents
      - 3-5 random fighters leave (uncertainty about new ownership)
      - 2 news items written (FINANCIAL COLLAPSE + new ownership)
      - current_cash reset to starting_budget × 0.25 (25% of original
        — enough to operate but not splurge). For promo 1: $80M ×
        0.25 = $20M recovery fund.
      - is_rebuilding=1, rebuilding_until_date = sim_date + 6 months
      - PROMOTION_BANKRUPT event fired on the bus

    Voice rule (per VOICE_ENFORCEMENT.md):
      News headline #1: 'FINANCIAL COLLAPSE: [Promo] files for
      bankruptcy protection' — factual, no tabloid clichés.
      News headline #2: 'New ownership group takes control of [Promo]'
      — business-page register, "consortium of investors" tone.
    """
    # 1. Reputation -15 (clamped to [10, 95] by _adjust_promotion_rep).
    _adjust_promotion_rep(
        conn, promotion_id, PROMO_REP_DELTA_BANKRUPTCY_FAILURE,
    )
    # 2. Fan trust -20 (clamped to [0, 100]).
    _adjust_promotion_fan_trust(
        conn, promotion_id, PROMO_FAN_TRUST_DELTA_BANKRUPTCY_FAILURE,
    )
    # 3. Void all staff contracts (staff leave the sinking ship).
    n_staff_voided = _void_staff_contracts(conn, promotion_id)
    # 4. Release the top 3 fighters by salary (they request out).
    released_top = _release_top_fighters(
        conn, promotion_id, n=BANKRUPTCY_TOP_FIGHTERS_RELEASED,
    )
    # 5. Release 3-5 random fighters (uncertainty about new ownership).
    released_random = _release_random_fighters(
        conn, promotion_id, already_released=released_top,
        n_min=BANKRUPTCY_RANDOM_FIGHTERS_RELEASED_MIN,
        n_max=BANKRUPTCY_RANDOM_FIGHTERS_RELEASED_MAX,
    )
    released_fighters = released_top + released_random
    # 6. Write the 2 voice-compliant news items (collapse + new ownership).
    _write_bankruptcy_news(conn, promotion_id, promo_name)
    # 7. Reset current_cash to starting_budget × 0.25 (recovery fund).
    # Read starting_budget from the promotions row (defensive — if
    # NULL, fall back to $1M which is the old recovery seed amount).
    budget_row = conn.execute(
        "SELECT starting_budget FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    starting_budget = budget_row[0] if budget_row else None
    if starting_budget and starting_budget > 0:
        cash_reset = starting_budget * BANKRUPTCY_CASH_RESET_FRACTION
    else:
        # Defensive fallback — old $1M seed. Shouldn't happen on a
        # properly-seeded promo but guards against corruption.
        cash_reset = 1_000_000
    # Read the current sim_date for the rebuilding flag + event payload.
    clock_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = clock_row[0] if clock_row else None
    conn.execute(
        "UPDATE promotions SET current_cash=?, "
        "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
        (cash_reset, promotion_id),
    )
    # 8. Set is_rebuilding=1 + rebuilding_until_date = sim_date + 6 months.
    _set_rebuilding_flag(conn, promotion_id, sim_date)
    # 8a. HW1.4 — set financial_state='REBUILDING' (the state machine's
    # post-bankruptcy recovery state). The state machine in
    # _check_financial_state_transitions will eventually transition
    # REBUILDING → RECOVERING when _check_rebuilding_status clears
    # is_rebuilding (after 6 months).
    conn.execute(
        "UPDATE promotions SET financial_state='REBUILDING', "
        "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
        (promotion_id,),
    )
    # 9. Fire PROMOTION_BANKRUPT on the event bus.
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.PROMOTION_BANKRUPT,
            'promotion_id': promotion_id,
            'promo_name': promo_name,
            'released_fighter_ids': released_fighters,
            'staff_contracts_voided': n_staff_voided,
            'is_rebuilding': 1,
            'cash_reset': cash_reset,
        })
    except Exception as e:
        # Defensive — bus publish failure shouldn't break the bankruptcy flow.
        print(f"[reputation._fire_bankruptcy_failure] WARN: bus "
              f"publish failed: {e}", flush=True)


# ----------------------------------------------------------------
# HW1.4 — Financial state machine (docs/Hardening_Phase.md §HW1.4)
# ----------------------------------------------------------------

def _load_financial_state_counters(conn):
    """Load the financial_state_counters JSON blob from player_settings.

    Returns a dict mapping promo_id (as str key) →
    {"pressured_months": <int>, "struggling_months": <int>}.
    Empty dict if the setting doesn't exist or is malformed.
    """
    row = conn.execute(
        "SELECT setting_value FROM player_settings WHERE setting_key=?",
        (FINANCIAL_STATE_COUNTERS_SETTING_KEY,),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        d = json.loads(row[0])
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save_financial_state_counters(conn, counters):
    """Persist the financial_state_counters dict back to player_settings."""
    conn.execute(
        "INSERT OR REPLACE INTO player_settings "
        "(setting_key, setting_value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (FINANCIAL_STATE_COUNTERS_SETTING_KEY, json.dumps(counters)),
    )


def _get_financial_state(conn, promotion_id):
    """Return the promo's current financial_state string.

    Defaults to 'HEALTHY' if the column is NULL (defensive — shouldn't
    happen post-v3.27.0 migration, but the column is NOT NULL DEFAULT
    'HEALTHY' so NULL is only possible if a future migration inserts
    a promo without setting the column).
    """
    row = conn.execute(
        "SELECT financial_state FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if not row or not row[0]:
        return 'HEALTHY'
    return row[0]


def _write_financial_state_news(conn, promotion_id, promo_name, new_state,
                                 sim_date=None):
    """Write the voice-compliant news item for a financial state transition.

    Looks up the news template in _FINANCIAL_STATE_NEWS. If the template's
    headline is None (e.g. BANKRUPT — news is owned by
    _write_bankruptcy_news), this is a no-op.

    Voice compliance (per CONVENTIONS §14 + VOICE_ENFORCEMENT.md):
      - topic='finance' (matches existing finance news)
      - sentiment='negative'/'positive' per the template
      - business-page register, no tabloid clichés
      - {promo} substituted with the promo's display name
    """
    template = _FINANCIAL_STATE_NEWS.get(new_state)
    if not template or not template.get("headline"):
        return  # no news for this state (e.g. BANKRUPT is owned elsewhere)
    if sim_date is None:
        clock_row = conn.execute(
            "SELECT current_date FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        sim_date = clock_row[0] if clock_row else None
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
    headline = template["headline"].format(promo=promo_name)
    body = template["body"].format(promo=promo_name)
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, template["sentiment"], "finance",
         promotion_id, sim_date),
    )


def _release_one_staff(conn, promotion_id):
    """HW1.4 STRUGGLING consequence — release the lowest-skill active
    staff contract for this promo.

    Per docs/Hardening_Phase.md §HW1.4: 'STRUGGLING = release 1 staff'.
    Terminates the active staff contract with the lowest skill_level
    (the most expendable). Sets contract.status='terminated' + writes
    a 'release' topic news item with the staff member's name.

    Defensive: no-op if the promo has no active staff contracts.
    """
    # Find the lowest-skill active staff contract.
    row = conn.execute(
        "SELECT sc.staff_contract_id, sc.staff_id, c.contract_id, "
        "s.first_name || ' ' || s.last_name AS staff_name, "
        "s.skill_level "
        "FROM staff_contracts sc "
        "JOIN contracts c ON c.contract_id=sc.contract_id "
        "JOIN staff s ON s.staff_id=sc.staff_id "
        "WHERE c.promotion_id=? AND c.status='active' "
        "ORDER BY s.skill_level ASC, sc.staff_contract_id ASC LIMIT 1",
        (promotion_id,),
    ).fetchone()
    if not row:
        return  # no staff to release
    _sc_id, staff_id, contract_id, staff_name, _skill = row
    conn.execute(
        "UPDATE contracts SET status='terminated', "
        "updated_at=CURRENT_TIMESTAMP WHERE contract_id=?",
        (contract_id,),
    )
    # Detach the staff from the promo (set staff.promotion_id=NULL).
    conn.execute(
        "UPDATE staff SET promotion_id=NULL, "
        "updated_at=CURRENT_TIMESTAMP WHERE staff_id=?",
        (staff_id,),
    )
    # Write a voice-compliant 'release' news item.
    clock_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = clock_row[0] if clock_row else None
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    src_id = src_row[0] if src_row else None
    if src_id is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    promo_name_row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    promo_name = promo_name_row[0] if promo_name_row else f"Promo {promotion_id}"
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id,
         f"{promo_name} releases {staff_name} amid cost cuts",
         f"{staff_name} has been released by {promo_name} as the "
         f"promotion trims its payroll during a financial struggle.",
         "negative", "release", promotion_id, sim_date),
    )


def _apply_financial_state_consequence(conn, promotion_id, new_state,
                                        promo_name, sim_date):
    """Apply the consequence for entering `new_state`.

    Per docs/Hardening_Phase.md §HW1.4:
      PRESSURED:  -10% marketing spend on next scheduled event
                  (UPDATE events SET marketing_spend = marketing_spend * 0.9
                   WHERE promotion_id=? AND status='scheduled' ORDER BY
                   event_date LIMIT 1).
      STRUGGLING: release 1 staff member (lowest-skill active contract).
      CRISIS:     no immediate consequence beyond the news item (the
                  sign_free_agent block in app_web.py reads
                  financial_state='CRISIS' at signing time).
      BANKRUPT:   handled by _fire_bankruptcy_failure (existing).
      REBUILDING: handled by _process_rebuilding_recovery (existing).
      RECOVERING: no consequence.
      HEALTHY:    no consequence.
    """
    if new_state == "PRESSURED":
        # -10% marketing spend on the next scheduled event.
        next_event = conn.execute(
            "SELECT event_id FROM events WHERE promotion_id=? "
            "AND status='scheduled' ORDER BY event_date ASC LIMIT 1",
            (promotion_id,),
        ).fetchone()
        if next_event:
            eid = next_event[0]
            conn.execute(
                "UPDATE events SET marketing_spend = "
                "CAST(marketing_spend * 0.9 AS INTEGER), "
                "updated_at=CURRENT_TIMESTAMP WHERE event_id=?",
                (eid,),
            )
    elif new_state == "STRUGGLING":
        _release_one_staff(conn, promotion_id)
    # CRISIS / BANKRUPT / REBUILDING / RECOVERING / HEALTHY: no immediate
    # consequence here (CRISIS's sign_free_agent block lives in app_web.py;
    # BANKRUPT/REBUILDING are handled by existing functions;
    # RECOVERING/HEALTHY are positive states with no consequence).


def _check_financial_state_transitions(conn):
    """HW1.4 — monthly tick: advance each promo's financial_state.

    Per docs/Hardening_Phase.md §HW1.4. Runs BEFORE
    _check_bankruptcy_failure so the state machine reflects the
    HEALTHY → PRESSURED → STRUGGLING → CRISIS progression before the
    existing bankruptcy pathway fires (which handles CRISIS → BANKRUPT
    via _fire_bankruptcy_failure).

    For each promo (excluding BANKRUPT and REBUILDING — those are
    owned by _fire_bankruptcy_failure / _check_rebuilding_status
    respectively):
      1. Compute cash thresholds based on starting_budget (defensive
         fallback to $1M if starting_budget is NULL/0).
      2. Update the pressured_months + struggling_months counters
         based on whether cash is below each threshold this month.
      3. Apply state transitions:
         - HEALTHY → PRESSURED  if pressured_months >= 2
         - HEALTHY → CRISIS     if cash < 0 (immediate skip)
         - PRESSURED → STRUGGLING if struggling_months >= 2
         - PRESSURED → CRISIS   if cash < 0 (immediate skip)
         - PRESSURED → HEALTHY  if cash >= 0.20 × starting_budget
         - STRUGGLING → CRISIS  if cash < 0
         - STRUGGLING → PRESSURED if cash >= 0.10 × starting_budget
         - CRISIS → STRUGGLING  if cash >= 0 (recovery)
         - RECOVERING → HEALTHY if cash > 0.50 × starting_budget
      4. For each transition:
         - UPDATE promotions.financial_state
         - Write the voice-compliant news item (_write_financial_state_news)
         - Apply the consequence (_apply_financial_state_consequence)

    Counters persist via player_settings (JSON blob keyed
    'financial_state_counters'). The CRISIS counter is the existing
    'bankruptcy_warnings' blob — left untouched here; the existing
    _check_bankruptcy_failure owns it.
    """
    counters = _load_financial_state_counters(conn)
    promos = conn.execute(
        "SELECT promotion_id, name, current_cash, starting_budget, "
        "financial_state FROM promotions"
    ).fetchall()
    clock_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    sim_date = clock_row[0] if clock_row else None
    for promo_id, promo_name, current_cash, starting_budget, \
            financial_state in promos:
        if current_cash is None or financial_state is None:
            continue
        # BANKRUPT + REBUILDING states are owned by other functions —
        # skip them here so we don't fight _fire_bankruptcy_failure /
        # _check_rebuilding_status.
        if financial_state in ("BANKRUPT", "REBUILDING"):
            continue
        # Defensive — if starting_budget is NULL or 0, use $1M as a
        # fallback (so the thresholds are still meaningful).
        budget = starting_budget if starting_budget and starting_budget > 0 \
            else 1_000_000.0
        pressured_threshold = budget * FINANCIAL_STATE_THRESHOLDS["PRESSURED_THRESHOLD"]
        struggling_threshold = budget * FINANCIAL_STATE_THRESHOLDS["STRUGGLING_THRESHOLD"]
        recovery_threshold = budget * FINANCIAL_STATE_THRESHOLDS["RECOVERY_THRESHOLD"]

        # Update counters (only for non-CRISIS states — the CRISIS
        # counter is owned by _check_bankruptcy_failure).
        key = str(promo_id)
        entry = counters.get(key, {})
        if "pressured_months" not in entry:
            entry["pressured_months"] = 0
        if "struggling_months" not in entry:
            entry["struggling_months"] = 0
        # Update counters based on current cash.
        if current_cash < pressured_threshold:
            entry["pressured_months"] = entry["pressured_months"] + 1
        else:
            entry["pressured_months"] = 0
        if current_cash < struggling_threshold:
            entry["struggling_months"] = entry["struggling_months"] + 1
        else:
            entry["struggling_months"] = 0
        counters[key] = entry

        # Determine the new state.
        new_state = financial_state
        if financial_state == "HEALTHY":
            # HEALTHY → CRISIS if cash < 0 (immediate skip — bypasses
            # PRESSURED/STRUGGLING).
            if current_cash < 0:
                new_state = "CRISIS"
            # HEALTHY → PRESSURED if pressured_months >= 2.
            elif entry["pressured_months"] >= \
                    FINANCIAL_STATE_CONSECUTIVE_MONTHS["PRESSURED"]:
                new_state = "PRESSURED"
        elif financial_state == "PRESSURED":
            # PRESSURED → CRISIS if cash < 0.
            if current_cash < 0:
                new_state = "CRISIS"
            # PRESSURED → STRUGGLING if struggling_months >= 2.
            elif entry["struggling_months"] >= \
                    FINANCIAL_STATE_CONSECUTIVE_MONTHS["STRUGGLING"]:
                new_state = "STRUGGLING"
            # PRESSURED → HEALTHY if cash recovered above the
            # pressured_threshold.
            elif current_cash >= pressured_threshold:
                new_state = "HEALTHY"
                entry["pressured_months"] = 0
                entry["struggling_months"] = 0
        elif financial_state == "STRUGGLING":
            # STRUGGLING → CRISIS if cash < 0.
            if current_cash < 0:
                new_state = "CRISIS"
            # STRUGGLING → PRESSURED if cash recovered above the
            # struggling_threshold (but not yet above pressured_threshold).
            elif current_cash >= struggling_threshold:
                new_state = "PRESSURED"
                entry["struggling_months"] = 0
        elif financial_state == "CRISIS":
            # CRISIS → STRUGGLING if cash >= 0 (recovery — but stay
            # below 0.10 × budget which is the STRUGGLING threshold;
            # otherwise we'd bounce straight back to HEALTHY, which
            # is too generous). If cash also exceeds 0.10 × budget,
            # we transition CRISIS → STRUGGLING → PRESSURED over the
            # next 2 months (the natural recovery path).
            if current_cash >= 0:
                new_state = "STRUGGLING"
        elif financial_state == "RECOVERING":
            # RECOVERING → HEALTHY if cash > 0.50 × budget.
            if current_cash > recovery_threshold:
                new_state = "HEALTHY"
                entry["pressured_months"] = 0
                entry["struggling_months"] = 0

        # Apply the transition if the state changed.
        if new_state != financial_state:
            conn.execute(
                "UPDATE promotions SET financial_state=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
                (new_state, promo_id),
            )
            _write_financial_state_news(
                conn, promo_id, promo_name, new_state, sim_date=sim_date,
            )
            _apply_financial_state_consequence(
                conn, promo_id, new_state, promo_name, sim_date,
            )
    _save_financial_state_counters(conn, counters)


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
