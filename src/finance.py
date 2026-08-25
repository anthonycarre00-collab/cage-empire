"""CAGE EMPIRE Finance System (Task 20).

Manages promotion finances via the event bus (Task 18.5). Subscribes
to EVENT_COMPLETED (Phase E1.2 — was FIGHT_RESOLVED) to compute
per-event P&L.

REVENUE (Phase E2 — per docs/ECON_STAFF_PLAN.md §3.1):
  - ticket_sales: venue_capacity × fill_rate × avg_ticket_price
  - broadcast_revenue: real PPV model — buyrate × ppv_price ×
    player_split for ppv_global/ppv_streaming; flat rights fee for
    tv_regional/local_stream (§3.1.2)
  - sponsorship: recurring per-event, rep × fan_trust tied (§3.1.3)
  - merchandise: attendance × avg_card_marketability × fan_trust_factor
    × $8 (§3.1.4)
  - concessions: attendance × $15 (§3.1.5)

EXPENSES (Phase E2 — per docs/ECON_STAFF_PLAN.md §3.2):
  - fighter_purse: contracts.salary / 12 pro-rated + win/finish/title/
    main_event bonuses from contracts.bonus_structure (§3.2.1)
  - venue_rental: venue.capacity × cost_per_seat by venue_type tier
    (arena $7, ballroom $5, theater $4, outdoor $3) (§3.2.3)
  - staff_salary: Σ contracts.salary / 12 for active staff_contracts
    (pro-rated monthly to per-event) (§3.2.2)
  - medical_cost: flat per fight + injury treatment costs
  - weight_cut_penalty: per weight_cut_log purse_penalty_pct

VOICE LAYER INTEGRATION:
  Financial descriptors via voice.py:
  - "highly profitable event" / "modest returns" / "hemorrhaging cash"
  - "flush with cash" / "breaking even" / "on the verge of bankruptcy"

USAGE:
  from finance import register_subscribers
  register_subscribers()  # call once at startup

  # The finance system automatically processes events via the bus.
  # No need to call any function directly — it's all event-driven.
"""
import json
import os
import random
import re


# Legacy flat broadcast revenue lookup — RETAINED for reference but
# NO LONGER USED by _process_event_finance as of Phase E2.1. The new
# PPV/broadcast model (per §3.1.2) computes broadcast_rev from
# base_buyrate × card_draw_multiplier × rep/trust factors. See
# _compute_broadcast_revenue below. Kept here so external callers
# (e.g. scripts that haven't been updated) don't break with an
# AttributeError — they'll just get the legacy flat value.
_BROADCAST_REVENUE = {
    "ppv_global":    500000,
    "streaming":     150000,
    "tv_regional":   75000,
    "local_stream":  15000,
}

# Phase E2.1 + Phase 4 (PHASE4-IMPLEMENT) — PPV base buyrates (per
# §3.1.2). The starting point for ppv_buys before card_draw_multiplier ×
# rep/trust factors are applied.
#
# CR-DESIGN (docs/DESIGN_REVIEW_E5.md §4): reduced from 250k/50k to
# 100k/25k — was too high for a new promo. Player builds up to higher
# buyrates via reputation + fan_trust over time, not from day 1.
#
# Phase 4 (PHASE4-IMPLEMENT) — reduced from 100k/25k to 35k/10k because
# the Phase 3 post-fix major promo avg profit was $4.06M/event (target
# $500K-$1M), driven by $4.16M/event broadcast_revenue. At rep=50 /
# trust=50 / card_draw=1.5 / ppv_price=$60 / player_split=0.5:
#   Old: 100k × 1.5 × 1.0 × 1.0 × $60 × 0.5 = $4.5M
#   New:  35k × 1.5 × 1.0 × 1.0 × $60 × 0.5 = $1.575M
# Real UFC numbered events do 200K-1M buys; UFC Fight Night (the bulk
# of major promo cards) does 100K-300K — the new base is the floor of
# that range so even a low-draw card generates realistic PPV revenue.
_PPV_BASE_BUYRATE = {
    "ppv_global":     35000,
    "ppv_streaming":  10000,
}

# Phase E2.1 — PPV price by tier (default — Phase E3 will make this
# player-set via events.ppv_price).
_PPV_PRICE_BY_TIER = {
    "ppv_global":     60,
    "ppv_streaming":  30,
}

# Phase E2.1 — flat broadcast rights fee for non-PPV tiers (per §3.1.2).
# These are the guaranteed per-event fee a promo receives from their
# broadcast partner regardless of card quality (Phase E3 will make
# this negotiable).
#
# DEVIATION FROM SPEC: the ECON_STAFF_PLAN.md §3.1.2 snippet lists
# only tv_regional + local_stream in the flat_rights dict. The
# original Phase-1 finance.py treated 'streaming' as a $150k flat
# tier (between tv_regional and ppv_streaming). I preserve that
# behavior here so promos 2 + 4 (broadcast_tier='streaming') don't
# lose their $150k/event broadcast income — the spec's omission of
# 'streaming' from the flat_rights dict appears to be a typo, not an
# intent to zero out streaming-tier broadcast revenue.
_FLAT_BROADCAST_RIGHTS = {
    "streaming":     150000,
    "tv_regional":   75000,
    "local_stream":  15000,
}

# Phase E2.1 — player_split: 50% of PPV revenue goes to the promo, 50%
# to the broadcast partner. CR-DESIGN: reduced from 60% to 50% —
# broadcast partners take a bigger cut (was too promo-friendly).
_PPV_PLAYER_SPLIT = 0.50

# Phase E2.2 — base sponsor pool per broadcast tier (§3.1.3).
# CR-DESIGN: reduced by 30% across all tiers — was too generous.
_BASE_SPONSOR_POOL = {
    "ppv_global":     350000,
    "ppv_streaming":  140000,
    "streaming":       70000,
    "tv_regional":     35000,
    "local_stream":    17500,
}
_DEFAULT_SPONSOR_POOL = 25000  # fallback for unknown tiers

# Phase E2.4 — concessions revenue per attendee (food/beer/parking avg).
_CONCESSIONS_PER_ATTENDEE = 15

# Phase E2.4 — avg merch spend per attendee (calibrated to $8 per §3.1.4).
_MERCH_PER_ATTENDEE_BASE = 8

# Phase E2.5 — fighter bonus amounts (per §3.2.1).
# Phase P2.5 (docs/COMPREHENSIVE_FIX_PLAN.md §Group B #9-10) — increased
# all bonus amounts + tightened per-event purse pro-rata so fighter
# pay is realistic + main-event / title / finish bonuses are life-
# changing money (Cage Empire voice).
# Base purse pro-rata: salary / 4 (was / 6 — fighters paid more per
# event) × 1.5 multiplier (was × 1.0). Net effect: per-event base
# purse is 2.25× the old formula (6/4 × 1.5).
# Main event bonus: $100k (was $50k).
# Title fight bonus: $250k (was $100k).
# Finish bonus: $25k (was $5k).
# Win bonus default: 100% of base purse (was 75%).
_FINISH_BONUS = 25000        # KO/Sub/Doctor stoppage winner (was $5k)
# Phase 4 (PHASE4-IMPLEMENT) — title fight + main event bonuses scaled
# by promo size_tier. Replaces the flat $250K / $100K constants that
# were applied to ALL promos regardless of tier. A title fight main
# event on a small promo previously cost $700K in bonuses alone ($250K
# × 2 fighters + $100K × 2 fighters), which exceeded the small promo's
# total event revenue ($481K) and forced promos into DISTRESSED.
#
# New tier-based rates (per PHASE4_PLAN.md §Issue 2):
#   - Major: $250K / $100K (unchanged — UFC title fights pay $200K-$500K)
#   - Mid:   $75K  / $30K  (Bellator mid-tier title fights)
#   - Small: $25K  / $10K  (regional title fights pay $5K-$25K)
_TITLE_FIGHT_BONUS_BY_TIER = {
    "major": 250000,
    "mid":    75000,
    "small":  25000,
}
_TITLE_FIGHT_BONUS_DEFAULT = 25000  # fallback for unknown tier

_MAIN_EVENT_BONUS_BY_TIER = {
    "major": 100000,
    "mid":    30000,
    "small":  10000,
}
_MAIN_EVENT_BONUS_DEFAULT = 10000  # fallback for unknown tier

# Legacy constants retained for backward compatibility — any external
# caller importing _TITLE_FIGHT_BONUS or _MAIN_EVENT_BONUS will still
# resolve. The new code paths use the tier-scaled dicts above.
_TITLE_FIGHT_BONUS = 250000  # deprecated — use _TITLE_FIGHT_BONUS_BY_TIER
_MAIN_EVENT_BONUS = 100000   # deprecated — use _MAIN_EVENT_BONUS_BY_TIER
_DEFAULT_WIN_BONUS_PCT = 1.0  # default if contracts.bonus_structure is NULL (was 0.75 — win bonus = 100% of base purse)
# Phase F1.2 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F1.2) — tightened
# from /4 to /3 so fighter purses are ~30-40% of projected revenue (was
# ~9%, way too low — a $200k/yr fighter at /4 × 1.5 = $75k/event on a
# $9M-revenue card = 0.83% of revenue; at /3 × 1.5 = $100k/event = 1.1%
# — still small but the per-event pro-rata + main-event star multiplier
# below combine to push the total purses into the 30-40% target band
# for a typical 5-fight mid-tier card).
_N_EVENTS_PER_YEAR = 3       # pro-rata assumption (was 4 — fighters paid 33% more per event)
# Phase P2.5 — base purse multiplier on top of the per-event pro-rata.
# Compensates for the fact that fighters only fight 2-4 times per year
# IRL but their salary is annualized — the × 1.5 multiplier makes a
# mid-card $200k/yr fighter's per-event base purse $75k (vs $33k at
# the old /6 × 1.0 formula), which is closer to real-world MMA purses.
# NEWS-FINANCE-GYM-LEGACY Issue 7.4 — reduced from 1.5 → 1.2 (~20%
# reduction in fighter_purse per event). Combined with the venue_rental
# reduction above, this brings total event cost down ~20% vs ticket
# revenue, giving small promos (post-Issue-7.3 $5M starting cash) a
# realistic path to solvency.
_BASE_PURSE_MULTIPLIER = 1.2

# Phase F1.2 — star multiplier for main event fighters. A main-event
# fighter's base purse scales with their marketability (1.0 + mkt/100):
#   mkt=0   → ×1.0 (unknown headliner, baseline)
#   mkt=50  → ×1.5 (mid-card name brand)
#   mkt=80  → ×1.8 (established star)
#   mkt=100 → ×2.0 (blockbuster draw)
# This means a main event between two mkt=80 stars costs ~2× a main
# event between two unknowns — the player can't headline every card
# with cheap prospects without paying market rate for a real draw.
_MAIN_EVENT_STAR_MULT_BASE = 1.0
_MAIN_EVENT_STAR_MULT_PER_MKT = 1.0 / 100.0  # +1.0 multiplier at mkt=100

# Phase F1.1 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F1.1) — post-event
# revenue adjustment based on show quality. After show_rating writes
# its row, finance applies a multiplier to PPV + merch revenue (the
# two streams most affected by word-of-mouth). The adjustment is
# written as a SECOND finance_transactions row of type
# 'show_quality_adjustment' rather than mutating the original rows —
# preserves the audit trail + keeps the _process_event_finance logic
# readable. Tiers (per the spec):
#   rating >= 80 → +30% (blockbuster — word of mouth drove extra buys)
#   rating >= 60 → +10% (good show — modest bump)
#   rating >= 40 → ±0%  (average — no adjustment)
#   rating <  40 → -20% (dud — fans demand refunds, bad word of mouth)
# Phase 4 (PHASE4-IMPLEMENT) — tightened show-quality multipliers.
# Phase 3 left GREAT at +30% which added ~$1.3M to a typical major
# promo card (=$886K avg show_quality_adjustment per event). Combined
# with the reduced PPV base_buyrate, +30% would still swing the profit
# band too widely. New values:
#   - GREAT: +15% (was +30%) — blockbuster shows still reward the promo
#     but the windfall is bounded
#   - GOOD:  +5% (was +10%) — modest bump for solid shows
#   - AVG:   ±0% (unchanged)
#   - DUD:   -15% (was -20%) — softer penalty so a single bad show
#     doesn't push a marginal promo into DISTRESSED
_SHOW_QUALITY_MULT_GREAT = 1.15  # rating >= 80
_SHOW_QUALITY_MULT_GOOD = 1.05   # rating 60-79
_SHOW_QUALITY_MULT_AVG = 1.00    # rating 40-59
_SHOW_QUALITY_MULT_DUD = 0.85    # rating < 40
_SHOW_QUALITY_GREAT_THRESHOLD = 80
_SHOW_QUALITY_GOOD_THRESHOLD = 60
_SHOW_QUALITY_DUD_THRESHOLD = 40

# Phase P2.5 — Fight of the Night + Best KO + Best Submission bonuses
# (per docs/COMPREHENSIVE_FIX_PLAN.md §Group B #10). Awarded post-event
# by show_rating._award_card_bonuses (it has the card context +
# fight_beats data needed to pick the winners).
_FOTN_BONUS_TOTAL = 50000    # split between both FOTN fighters ($25k each)
_FOTN_BONUS_PER_FIGHTER = 25000
_BEST_KO_BONUS = 25000
_BEST_SUB_BONUS = 25000

# Phase P2.4 — financial balance tuning (docs/COMPREHENSIVE_FIX_PLAN.md
# §Group B #8). Two elasticity constants + tighter marketing caps make
# maxing all levers unprofitable vs the moderate sweet spot.
# Ticket price elasticity: each $1 above $80 reduces fill rate by
# 0.6/80 = 0.75 percentage points. At $300 ticket the penalty is 1.65
# (165% fill loss) — floored at 0.10 fill by the clamp in
# _compute_fill_rate.
_TICKET_PRICE_PENALTY_FACTOR = 0.6
_TICKET_PRICE_PENALTY_FLOOR = 80  # tickets at/below this have no penalty
# PPV price elasticity: each $1 above $60 reduces PPV buys by 0.4/60
# = 0.67 percentage points. At $80 PPV the penalty is 0.133 (13% buy
# loss). Modest by design — high PPV price still nets more revenue
# than $60, but the marginal gain shrinks so the player can't just
# "set everything to max".
_PPV_PRICE_PENALTY_FACTOR = 0.8  # was 0.4 — strengthened so maxing PPV price hurts
_PPV_PRICE_PENALTY_FLOOR = 60
# Marketing diminishing returns (P2.4):
#   - Fill boost cap: 0.15 (was 0.30) — heavy marketing hits the wall
#     faster on attendance.
#   - PPV multiplier cap: 1.3 (was 2.0) — heavy marketing can no longer
#     double PPV buys; the max boost is +30%.
_MARKETING_FILL_BOOST_CAP = 0.15
_MARKETING_PPV_MULT_CAP = 1.3
_MARKETING_PPV_MULT_DIVISOR = 250000  # spend / $250k → multiplier delta

# Phase 3 (PHASE3-IMPLEMENT) — flat per-event staff salary by promo
# size_tier. Replaces the per-event pro-rata (annual staff salary /
# _N_EVENTS_PER_YEAR) which produced absurd $208K/event staff costs
# on Alpha (10 staff × ~$2.5M total annual salary / 12 events = $208K
# — staff are paid per show, not their full annual salary per show).
# The new flat rate mirrors real-world MMA promo operations: a major
# promo's event-night staff (cutmen, doctors, commentators, security,
# timekeepers, etc.) cost ~$15K all-in; mid promos ~$8K; small
# regional shows ~$3K. The promo's staff_contracts.salary is now
# treated as the annual retainer (paid via a separate monthly tick
# in a future Phase E5), NOT pro-rated per event.
_STAFF_SALARY_PER_EVENT_BY_TIER = {
    "major": 15000,
    "mid":    8000,
    "small":  3000,
}
_DEFAULT_STAFF_SALARY_PER_EVENT = 5000  # fallback for unknown tier

# Phase 3 (PHASE3-IMPLEMENT) — fighter purse multiplier by size_tier.
# Replaces the flat _BASE_PURSE_MULTIPLIER (was 1.2) with a tier-based
# one so major promos pay UFC-level purses (stars $500K+, min $10K)
# while small regional promos pay $500-$2K per fight. The multiplier
# is applied on top of the per-event pro-rata (salary /
# _N_EVENTS_PER_YEAR), so a $200K/yr fighter on a major promo gets
# ($200K / 3) × 3.0 = $200K/event base purse; the same fighter on a
# small promo gets ($200K / 3) × 0.5 = $33K/event — realistic spread.
#
# Phase 8 (PHASE8-A-ECONOMICS) — reduced the small-tier multiplier from
# 0.5 → 0.3 so small promo purses scale better relative to revenue.
# A $15K/yr fighter on a small promo was getting ($15K/3) × 0.5 = $2.5K
# base + $2.5K win + $25K finish = ~$15K/event avg per winner. For a
# 6-fight card that's $90K total purses, which (combined with $14K
# venue + $3K staff + $18K medical) = $125K expenses against ~$220K
# revenue → ~$95K/event profit margin. But the Phase 7 5y soak showed
# small promos at -$95K/event AVG (likely because non-finishing fights
# + title fight bonuses + main event bonuses pulled total purses higher
# than the simple estimate). Reducing the multiplier to 0.3 brings the
# new base purse to $1.5K, avg purse ~$10K, total ~$60K for 6 fights
# — bringing per-event expenses down to ~$95K total and lifting the
# small promo's per-event profit to between -$10K and +$30K (the
# Phase 8 target band).
_PURSE_MULT_BY_TIER = {
    "major": 3.0,
    "mid":   1.5,
    "small": 0.3,
}
_DEFAULT_PURSE_MULT = 1.0  # fallback for unknown tier

# Phase 3 (PHASE3-IMPLEMENT) — default ticket price by size_tier.
# Applied when events.ticket_price is NULL (the player hasn't set the
# lever). Major promos charge $120 (UFC charges $100-$500), mid $60,
# small $35 (regional). Replaces the flat $80 default for all promos.
_DEFAULT_TICKET_PRICE_BY_TIER = {
    "major": 120,
    "mid":    60,
    "small":  35,
}
_DEFAULT_TICKET_PRICE_FALLBACK = 80  # if size_tier unknown

# Phase E2.6 — assumed events per year for staff salary pro-rata
# (mirrors fighter purse pro-rata). Phase E5 will move staff salaries
# to a monthly tick (separate from per-event P&L).

# Phase E2.7 — venue rental cost per seat by venue_type (§3.2.3).
# CR-DESIGN: increased costs — was too cheap. Arena $10, ballroom $7,
# theater $5, outdoor $4.
# NEWS-FINANCE-GYM-LEGACY Issue 7.4 — reduced by ~20% across the board
# to bring venue_rental + fighter_purse ratios back in line with
# ticket revenue (post-Issue-7.3 small-promo cash raise, the
# economics were too tight — small promos were bleeding cash on a
# single bad card). New: arena $8, ballroom $6, theater $4, outdoor $3.
_VENUE_COST_PER_SEAT_BY_TYPE = {
    "arena":    8,
    "ballroom": 6,
    "theater":  4,
    "outdoor":  3,
}
_DEFAULT_VENUE_COST_PER_SEAT = 4  # fallback if venue_type unknown (was 5)

# Phase 8 (PHASE8-A-ECONOMICS) — tier-scaled venue cost multiplier.
# A 3,489-seat theater at $4/seat = $13,956/event, which is ~6% of a
# small promo's typical $220K revenue — too high for regional shows.
# Real-world regional MMA venues rent for ~$2K-$5K flat (high-school
# gyms, community centers, ballrooms), while UFC-scale arenas run
# $50K-$200K. The tier multiplier scales the per-seat cost so:
#   - Major promos: 1.0x (unchanged — $8 arena, $6 ballroom, etc.)
#   - Mid promos:   0.7x ($5.60 arena, $4.20 ballroom, $2.80 theater)
#   - Small promos: 0.4x ($3.20 arena, $2.40 ballroom, $1.60 theater,
#                   $1.20 outdoor). A 3,489-seat theater at $1.60 =
#                   $5,582 — closer to real-world regional venue rent.
_VENUE_COST_MULT_BY_TIER = {
    "major": 1.0,
    "mid":   0.7,
    "small": 0.4,
}
_VENUE_COST_MULT_DEFAULT = 1.0

# Legacy flat per-seat venue cost (kept for backward compat with any
# caller that imports it — Phase E2.7 switches to the tiered dict).
_VENUE_COST_PER_SEAT = 5.0

# Staff salary per staff member per event — DEPRECATED as of Phase
# E2.6. Kept for backward compat with any external caller (none in
# this codebase as of E2). The new model reads contracts.salary / 12.
_STAFF_SALARY_PER_EVENT = 2000

# Medical cost per fight
# CR-DESIGN: increased from $1.5k to $3k — medical costs were too low.
_MEDICAL_COST_PER_FIGHT = 3000

# Phase E2.1 — rivalry heat threshold for PPV buyrate boost (per
# §3.1.2 "n_rivalry_fights_heat_50_plus"). Matches show_rating.py's
# _RIVALRY_HEAT_THRESHOLD = 50 (which uses strict >; we use >= to
# match the spec's "50 plus" wording — heat=50 counts as hot).
_RIVALRY_HEAT_THRESHOLD = 50

# Result types that count as "finishes" for the fighter finish bonus
# (Phase E2.5). Mirrors show_rating._count_finishes' set.
_FINISH_RESULT_TYPES = frozenset({
    'ko_tko', 'ko', 'tko', 'submission',
    'doctor_stoppage', 'corner_stoppage', 'dq',
})

# Fill rate: what % of seats are sold. Based on market heat.
# heat 30 → 40% fill, heat 95 → 95% fill
# Phase P2.4 (docs/COMPREHENSIVE_FIX_PLAN.md §Group B #8) — full
# rewrite. The old formula was a flat market_heat lookup with a small
# marketing boost + NO price elasticity, so maxing the ticket-price
# lever to $300 still filled the arena. The new formula:
#
#   price_penalty = max(0, (ticket_price - 80) / 80) * 0.6
#   marketing_boost = min(0.15, marketing_spend / (cap × $5))
#   fill_rate = clamp(0.30 + (heat/100)*0.50 + (rep/100)*0.10
#                     + marketing_boost - price_penalty, 0.10, 0.99)
#
# Effects at the extremes (heat=50, rep=85, cap=18000):
#   - $80 ticket, $0 mkt:   0.30 + 0.25 + 0.085 + 0 - 0     = 0.635 (63.5%)
#   - $150 ticket, $50k mkt: 0.30 + 0.25 + 0.085 + 0.15 - 0.525 = 0.26 (26%)
#   - $300 ticket, $500k mkt: floored at 0.10 (penalty 1.65 >> boost 0.15)
#
# Backward compat: when ticket_price isn't passed (legacy callers that
# only compute base_fill), the price_penalty is 0 and the formula
# collapses to the old market_heat-driven fill (with the new +rep term
# and the tighter 0.15 marketing cap).
def _compute_fill_rate(market_heat, marketing_spend=0, venue_capacity=0,
                       ticket_price=None, promo_reputation=50):
    """Compute the fill rate (0-1) for a market.

    Phase P2.4 — full rewrite per docs/COMPREHENSIVE_FIX_PLAN.md
    §Group B #8. The fill rate now responds to:
      - market_heat (50% weight) — the dominant driver
      - promo reputation (10% weight) — a high-rep promo draws better
      - marketing_spend (capped at +15% fill) — diminishing returns
      - ticket_price (penalty above $80, floored at 0.10 fill) — price
        elasticity so maxing the lever empties the arena

    Args:
        market_heat: 0-100 market heat level.
        marketing_spend: player-set marketing budget. Default 0.
        venue_capacity: venue capacity (scales the marketing boost —
            $50k matters more for a 2k theater than an 18k arena).
            Default 0 = no boost.
        ticket_price: player-set ticket price. Default None = no
            price penalty (legacy callers / pre-event preview before
            the player has touched the lever).
        promo_reputation: 0-100 promo reputation. Default 50.

    Returns:
        Fill rate in [0.10, 0.99].
    """
    heat = max(0, min(100, market_heat or 50))
    rep = max(0, min(100, promo_reputation or 50))
    # Marketing boost — tighter 0.15 cap (was 0.30 per P2.4).
    marketing_boost = 0.0
    if marketing_spend > 0 and venue_capacity > 0:
        marketing_boost = min(_MARKETING_FILL_BOOST_CAP,
                              marketing_spend /
                              max(1, venue_capacity * 5))
    # Price elasticity — penalty scales linearly above $80.
    price_penalty = 0.0
    if ticket_price is not None and ticket_price > _TICKET_PRICE_PENALTY_FLOOR:
        price_penalty = (
            (ticket_price - _TICKET_PRICE_PENALTY_FLOOR) /
            _TICKET_PRICE_PENALTY_FLOOR
        ) * _TICKET_PRICE_PENALTY_FACTOR
    fill = (0.30 +
            (heat / 100.0) * 0.50 +
            (rep / 100.0) * 0.10 +
            marketing_boost -
            price_penalty)
    return max(0.10, min(0.99, fill))


def _record_transaction(conn, promotion_id, event_id, fighter_id,
                        txn_type, amount, description, txn_date):
    """Write a finance_transactions row + update promotion cash."""
    conn.execute(
        "INSERT INTO finance_transactions (promotion_id, event_id, "
        "fighter_id, transaction_type, amount, description, "
        "transaction_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (promotion_id, event_id, fighter_id, txn_type, amount,
         description, txn_date),
    )
    # Update promotion cash (positive = revenue, negative = expense)
    conn.execute(
        "UPDATE promotions SET current_cash = current_cash + ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE promotion_id = ?",
        (amount, promotion_id),
    )


# ============================================================
# Phase E2.1 — PPV/broadcast revenue helpers (per §3.1.2)
# ============================================================
# These helpers read card-quality signals (main event marketability,
# co-main marketability, title fights, hot rivalries) and feed them
# into the card_draw_multiplier. They mirror patterns from
# show_rating.py but are deliberately self-contained here so finance
# doesn't depend on show_rating's import order.
# ============================================================


def _get_main_event_marketability(conn, event_id):
    """Return the max marketability (0-100) of the main event fighters.

    Looks for a fight on the card with card_slot='main_event'. If
    found, returns MAX(fighter.marketability) across the participants
    of that fight. If no main_event fight exists (e.g. promo 1's seed
    uses card_slot='prelim' for all fights), falls back to the highest
    marketability across ALL fighters on the card — so the buyrate
    formula still gets a non-zero signal from the card's biggest draw.
    Returns 0 if the event has no fights at all.
    """
    me_row = conn.execute(
        "SELECT f.fight_id FROM fights f "
        "WHERE f.event_id=? AND f.card_slot='main_event' "
        "LIMIT 1",
        (event_id,),
    ).fetchone()
    if me_row:
        fight_id = me_row[0]
        row = conn.execute(
            "SELECT MAX(fi.marketability) FROM fight_participants fp "
            "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
            "WHERE fp.fight_id=?",
            (fight_id,),
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
    # Fallback: max marketability across all fighters on the card.
    row = conn.execute(
        "SELECT MAX(fi.marketability) FROM fight_participants fp "
        "JOIN fights f ON f.fight_id=fp.fight_id "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _get_co_main_marketability(conn, event_id):
    """Return the max marketability (0-100) of the co-main event fighters.

    Falls back to the SECOND-highest card-wide marketability if no
    card_slot='co_main' fight exists (so it doesn't double-count the
    main event's star). Returns 0 if the card has <2 fights.
    """
    cm_row = conn.execute(
        "SELECT f.fight_id FROM fights f "
        "WHERE f.event_id=? AND f.card_slot='co_main' "
        "LIMIT 1",
        (event_id,),
    ).fetchone()
    if cm_row:
        fight_id = cm_row[0]
        row = conn.execute(
            "SELECT MAX(fi.marketability) FROM fight_participants fp "
            "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
            "WHERE fp.fight_id=?",
            (fight_id,),
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
    # Fallback: 2nd-highest marketability on the card (so the formula
    # doesn't double-count the main event's star).
    row = conn.execute(
        "SELECT fi.marketability FROM fight_participants fp "
        "JOIN fights f ON f.fight_id=fp.fight_id "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "WHERE f.event_id=? "
        "ORDER BY fi.marketability DESC LIMIT 2",
        (event_id,),
    ).fetchall()
    if len(row) >= 2:
        return int(row[1][0] or 0)
    return 0


def _count_title_fights(conn, event_id):
    """Return the number of title fights on the card."""
    row = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=? AND is_title_fight=1",
        (event_id,),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _count_rivalry_fights_heat_50_plus(conn, event_id):
    """Count fights on the card where the two participants have an
    active rivalry with heat >= 50 (per §3.1.2 "n_rivalry_fights_heat_
    50_plus"). Mirrors show_rating._count_rivalry_fights but uses >=
    instead of strict > (spec says "50 plus" — heat=50 counts as hot).
    """
    fights = conn.execute(
        "SELECT fp_a.fighter_id AS a, fp_b.fighter_id AS b "
        "FROM fights f "
        "JOIN fight_participants fp_a ON fp_a.fight_id=f.fight_id "
           "AND fp_a.corner='red' "
        "JOIN fight_participants fp_b ON fp_b.fight_id=f.fight_id "
        "   AND fp_b.corner='blue' "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchall()
    n = 0
    for a, b in fights:
        if a is None or b is None:
            continue
        row = conn.execute(
            "SELECT rivalry_heat FROM rivalries "
            "WHERE is_active=1 AND "
            "((fighter_a_id=? AND fighter_b_id=?) OR "
            " (fighter_a_id=? AND fighter_b_id=?))",
            (a, b, b, a),
        ).fetchone()
        if row and row[0] is not None and row[0] >= _RIVALRY_HEAT_THRESHOLD:
            n += 1
    return n


def _compute_broadcast_revenue(conn, event_id, broadcast_tier,
                               promo_reputation, promo_fan_trust,
                               marketing_spend=0, ppv_price=None,
                               is_ppv=True):
    """Phase E2.1 + E3.2 + P2.4 — real PPV/broadcast revenue model
    (§3.1.2 + §3.3 + docs/COMPREHENSIVE_FIX_PLAN.md §Group B #8).

    For PPV tiers (ppv_global, ppv_streaming) when is_ppv=True:
        ppv_price_penalty = max(0, (ppv_price - 60) / 60) * 0.8   (strengthened)
        marketing_multiplier = 1.0 + min(1.3, spend / 250k)       (P2.4 cap)
        ppv_buys = int(base_buyrate × card_draw × marketing_mult ×
                       rep_factor × trust_factor × (1 - ppv_price_penalty))
        ppv_revenue = ppv_buys × ppv_price × player_split
        broadcast_revenue = ppv_revenue

    For non-PPV tiers (tv_regional, local_stream) OR when is_ppv=False
    on a PPV-tier promo (the player chose to run a non-PPV show):
        broadcast_revenue = flat_rights (tier-dependent)

    Phase P2.4 changes (per docs/COMPREHENSIVE_FIX_PLAN.md §Group B #8):
      - PPV price elasticity: high ppv_price reduces buys. At $80 PPV
        the penalty is 0.267 (27% buy loss) — strong enough that maxing
        PPV price nets LESS revenue than $60-70 (the sweet spot).
      - Marketing multiplier cap tightened: 1.3 (was 2.0). Heavy
        marketing can no longer double PPV buys — the max boost is
        +30% instead of +100%.

    Backward compat: when called with marketing_spend=0, ppv_price=None,
    is_ppv=True (the pre-E3 default), behaves identically to Phase E2
    (ppv_price defaults to tier-default which is at/below the $60 floor
    so no penalty; marketing_mult = 1.0).
    """
    # If the promo's tier supports PPV AND the player chose is_ppv=1
    # for this event, use the PPV formula.
    if is_ppv and broadcast_tier in _PPV_BASE_BUYRATE:
        base_buyrate = _PPV_BASE_BUYRATE[broadcast_tier]
        me_mkt = _get_main_event_marketability(conn, event_id)
        co_mkt = _get_co_main_marketability(conn, event_id)
        n_title = _count_title_fights(conn, event_id)
        n_rivalry = _count_rivalry_fights_heat_50_plus(conn, event_id)

        card_draw_multiplier = (
            1.0
            + 0.5 * (me_mkt / 100.0)
            + 0.2 * (co_mkt / 100.0)
            + 0.3 * (n_title / 2.0)
            + 0.1 * (n_rivalry / 3.0)
        )
        # Phase P2.4 — marketing_multiplier capped at 1.3 total (was 2.0).
        # The cap is on the TOTAL multiplier (1 + delta), so the delta
        # caps at 0.3 (= 1.3 - 1.0). Heavy marketing can no longer
        # double PPV buys — the max boost is +30% instead of +100%.
        # spend / $250k still drives the curve, but the delta cap is
        # the binding constraint for any marketing_spend ≥ $75k
        # ($75k / $250k = 0.3 — the cap is reached).
        marketing_multiplier = 1.0 + min(
            _MARKETING_PPV_MULT_CAP - 1.0,
            (marketing_spend or 0) / _MARKETING_PPV_MULT_DIVISOR,
        )
        rep_factor = 0.5 + (promo_reputation / 100.0)  # rep=0→0.5, rep=100→1.5
        trust_factor = 0.5 + (promo_fan_trust / 100.0)

        # Phase P2.4 — PPV price elasticity. Higher ppv_price → fewer
        # buys. Penalty is 0 at ppv_price ≤ $60 (the floor), scales
        # linearly above. At $80 PPV the penalty is 0.133 (13% buys
        # lost) — modest by design (high PPV price still nets more
        # revenue than $60, but the marginal gain shrinks).
        if ppv_price is None or ppv_price <= 0:
            ppv_price = _PPV_PRICE_BY_TIER.get(broadcast_tier, 30)
        ppv_price_penalty = 0.0
        if ppv_price > _PPV_PRICE_PENALTY_FLOOR:
            ppv_price_penalty = (
                (ppv_price - _PPV_PRICE_PENALTY_FLOOR) /
                _PPV_PRICE_PENALTY_FLOOR
            ) * _PPV_PRICE_PENALTY_FACTOR

        ppv_buys = int(
            base_buyrate * card_draw_multiplier *
            marketing_multiplier * rep_factor * trust_factor *
            (1.0 - ppv_price_penalty)
        )
        ppv_revenue = int(ppv_buys * ppv_price * _PPV_PLAYER_SPLIT)
        return ppv_revenue

    # Non-PPV path (either tier is non-PPV OR player chose is_ppv=0):
    # Phase 3 (PHASE3-IMPLEMENT) — scale the flat broadcast rights fee
    # by reputation + fan_trust so a high-rep mid promo earns more from
    # its regional TV deal than a low-rep one. The old model returned a
    # flat $150K for 'streaming', $75K for 'tv_regional', $15K for
    # 'local_stream' regardless of rep — which overpaid low-rep promos
    # and underpaid high-rep ones. New ranges (per PHASE3_PLAN.md §3d):
    #   - tv_regional / streaming: $120K-$300K (rep + fan_trust scaled)
    #   - local_stream:             $25K-$80K   (rep scaled)
    #   - none / unknown:          $0          (no broadcast partner)
    # 'streaming' is treated like 'tv_regional' (regional TV level) —
    # both are mid-tier broadcast deals where the partner pays a rights
    # fee that scales with the promo's brand power. The PPV tiers
    # (ppv_global, ppv_streaming) are handled by the early return above.
    #
    # Phase 8 (PHASE8-A-ECONOMICS) — raised the local_stream floor from
    # $10K → $25K + ceiling from $50K → $80K so small promos get ~$60K
    # avg instead of ~$30K (matches real-world regional streaming deals:
    # UFC Fight Pass prelims pay $30K-$100K guaranteed). Also raised
    # the tv_regional/streaming floor from $100K → $120K so mid promos
    # aren't squeezed by negative per-event profit. Ceilings unchanged.
    rep = max(0, min(100, promo_reputation or 50))
    trust = max(0, min(100, promo_fan_trust or 50))
    if broadcast_tier in ("tv_regional", "streaming"):
        # Rep + fan_trust both contribute. Linear interpolation from
        # $120K floor (rep=0, trust=0) to $300K cap (rep=100, trust=100):
        #   rep=0,   trust=0   → $120K
        #   rep=50,  trust=50  → $210K
        #   rep=100, trust=100 → $300K
        # Capped at $300K (defensive — if rep+trust somehow exceeds 200
        # due to direct-DB edits, we don't pay out more than the spec).
        # Phase 8 — floor raised from $100K to $120K to keep mid promos
        # profitable per-event (was ~$200K avg, now ~$210K).
        factor = 1.2 + (rep + trust) / 100.0
        return int(min(300000, 100000 * factor))
    if broadcast_tier == "local_stream":
        # Rep-only scaling (local stream deals are smaller and only
        # care about the promo's name recognition, not fan trust).
        # Linear interpolation: $25K floor at rep=0 → $80K at rep=100.
        #   rep=0   → $25K  (was $10K)
        #   rep=25  → $38.75K
        #   rep=50  → $52.5K (was $30K)
        #   rep=75  → $66.25K
        #   rep=100 → $80K   (was $50K cap)
        # Phase 8 — both floor + ceiling raised to give small promos
        # (broadcast_tier='local_stream') realistic revenue.
        return int(25000 + (rep / 100.0) * 55000)
    # 'none' or unknown tier — no broadcast partner, $0 revenue.
    return 0


def _compute_sponsorship_revenue(broadcast_tier,
                                 promo_reputation, promo_fan_trust):
    """Phase E2.2 — recurring sponsorship income (§3.1.3).

    Per-event sponsorship revenue, scaled by promo reputation × fan
    trust. Replaces the one-shot opening-balance sponsorship seed
    pattern — now every event generates a recurring sponsorship row.

        base_sponsor_pool = tier-dependent ($25k local ... $500k ppv_global)
        promo_multiplier  = (rep / 100) × (trust / 100) × 2.0
                            # rep=80, trust=70 → 1.12x base
                            # rep=30, trust=20 → 0.12x base (sponsors flee)
        sponsorship_revenue = int(base_sponsor_pool × promo_multiplier)

    Returns 0 if the promo has 0 reputation (sponsors won't touch a
    promo with no brand power).
    """
    base_pool = _BASE_SPONSOR_POOL.get(broadcast_tier, _DEFAULT_SPONSOR_POOL)
    promo_multiplier = (
        (promo_reputation / 100.0) *
        (promo_fan_trust / 100.0) *
        2.0
    )
    return int(base_pool * promo_multiplier)


def _get_event_attendance(conn, event_id, venue_cap=None, market_heat=None):
    """Phase E2.3/E2.4 — return the ticketed attendance for an event.

    Two paths (mirrors show_rating._get_attendance):
      1. If a ticket_sales finance_transactions row exists for this
         event (which we just wrote earlier in _process_event_finance
         for new events, or which was backfilled for historical
         events), parse the description "N tickets × $price".
      2. Fallback: compute on-the-fly using the finance formula
         (venue_cap × fill_rate, where fill_rate is clamped 0.30-0.98).

    The fallback is needed for callers that compute attendance BEFORE
    finance writes the ticket_sales row (e.g. test_finance_e2.py
    inspecting an event that hasn't been processed yet).

    Args can be pre-fetched venue_cap + market_heat to avoid a
    redundant query when the caller already has them (e.g.
    _process_event_finance).
    """
    row = conn.execute(
        "SELECT description FROM finance_transactions "
        "WHERE event_id=? AND transaction_type='ticket_sales'",
        (event_id,),
    ).fetchone()
    if row and row[0]:
        try:
            n_str = row[0].split(" tickets")[0].strip()
            return int(n_str)
        except (ValueError, IndexError):
            pass  # fall through

    if venue_cap is None or market_heat is None:
        ev = conn.execute(
            "SELECT v.capacity, m.heat_level "
            "FROM events e "
            "LEFT JOIN venues v ON v.venue_id=e.venue_id "
            "LEFT JOIN markets m ON m.market_id=e.market_id "
            "WHERE e.event_id=?",
            (event_id,),
        ).fetchone()
        if not ev:
            return 0
        venue_cap = ev[0] or 5000
        market_heat = ev[1] if ev[1] is not None else 50
    fill_rate = _compute_fill_rate(market_heat)
    return int(venue_cap * fill_rate)


def _get_avg_card_marketability(conn, event_id):
    """Phase E2.3 — average marketability (0-100) across all fighters
    on the card. Used by the merchandise formula (§3.1.4). Returns 0
    if the card has no fighters.
    """
    row = conn.execute(
        "SELECT AVG(fi.marketability) FROM fight_participants fp "
        "JOIN fights f ON f.fight_id=fp.fight_id "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchone()
    if not row or row[0] is None:
        return 0
    return int(row[0])


def _parse_win_bonus_pct(bonus_structure):
    """Phase E2.5 — parse the win_bonus percentage from a fighter's
    contracts.bonus_structure column (§3.2.1).

    Supports 2 formats (defensive — the column is TEXT with no schema
    enforcement, so future migrations + Phase E3's contract negotiation
    UI might use either):

      1. JSON dict (future-proof for Phase E3 contract negotiation UI):
         '{"win_bonus_pct": 0.5}' or '{"win_bonus": 50}' (0-1 or 0-100).

      2. Seeded string format (the only format in the current DB):
         'win_bonus=50%, finish_bonus=25%, performance_bonus=10%'
         — extracts the win_bonus=N% substring.

    Returns a float (0.0 - 2.0 — capped at 2.0 to allow 200% win
    bonuses for elite contracts). Default 0.5 if NULL or unparseable
    (per spec §3.2.1 default).
    """
    if not bonus_structure:
        return _DEFAULT_WIN_BONUS_PCT
    # Try JSON first (Phase E3 contract UI will write JSON).
    try:
        d = json.loads(bonus_structure)
        if isinstance(d, dict):
            for k in ('win_bonus_pct', 'win_bonus'):
                if k in d:
                    val = float(d[k])
                    # Accept either pct form (0.5) or fraction (50).
                    return val if val <= 1.0 else val / 100.0
    except (ValueError, TypeError):
        pass
    # Try seeded string format: 'win_bonus=50%, ...'
    m = re.search(r'win_bonus\s*=\s*(\d+(?:\.\d+)?)\s*%',
                  bonus_structure)
    if m:
        return float(m.group(1)) / 100.0
    return _DEFAULT_WIN_BONUS_PCT


def _get_venue_type(conn, venue_id):
    """Phase E2.7 — return the venue_type for a venue_id (per §3.2.3).

    The venue_type column was added to the venues table by migration
    v3_18_0_add_venue_type (see src/build_db.py). 4 values:
      - 'arena'    (capacity >= 15000) — $7/seat
      - 'ballroom' (5000-14999)        — $5/seat
      - 'theater'  (2000-4999)         — $4/seat
      - 'outdoor'  (<2000)             — $3/seat

    Returns None if the venue doesn't exist or the venue_type column
    is somehow missing (defensive — shouldn't happen post-migration).
    The caller falls back to _DEFAULT_VENUE_COST_PER_SEAT ($5) in
    that case.
    """
    if not venue_id:
        return None
    row = conn.execute(
        "SELECT venue_type FROM venues WHERE venue_id=?",
        (venue_id,),
    ).fetchone()
    if not row or row[0] is None:
        return None
    return row[0]


def _process_event_finance(conn, event):
    """Process finances when an event completes (FIX-V3-ALL5 #1a wrapper).

    Thin wrapper around `_process_event_finance_impl` that catches any
    unexpected exception and prints the full traceback to stderr. This
    is a defensive guard added to diagnose the silent-crash symptom
    reported in FIX-V3-ALL5: pre-existing events had ZERO
    finance_transactions rows, and 16 events that transitioned during
    the sim also produced 0 rows — likely a crash inside the impl
    that was silently swallowed by the event bus. With this wrapper,
    the traceback will at least be visible on stderr.

    The wrapper does NOT re-raise — finance is one of several
    EVENT_COMPLETED subscribers, and a crash here shouldn't prevent
    show_rating / reputation / news from running on the same event.
    The bus's own try/except would also catch it, but bus-side
    catch is generic (logs at WARNING level only); printing the
    full traceback here gives a richer error for debugging.

    Args:
        conn: sqlite3.Connection (caller commits; wrapper does not
            commit either — impl writes are visible to the caller's
            transaction).
        event: dict with keys 'event_id', 'promotion_id', and
            optionally 'event_date' / 'type'.
    """
    import sys
    import traceback
    try:
        _process_event_finance_impl(conn, event)
    except Exception:
        # Print full traceback to stderr so silent crashes become
        # visible. Do NOT re-raise — see docstring above.
        try:
            sys.stderr.write(
                f"[finance._process_event_finance] CRASH on "
                f"event={event!r}\n"
            )
            sys.stderr.flush()
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
        except Exception:
            # Last-resort: if even the error logging crashes, swallow
            # (matches the defensive pattern in _compute_show_ratings).
            pass


def _process_event_finance_impl(conn, event):
    """Process finances when an event completes.

    Computes all revenue + expenses for the event and records them
    as finance_transactions rows. Called as an event bus subscriber
    for EVENT_COMPLETED (Phase E1.2 — was FIGHT_RESOLVED, switched
    per docs/ECON_STAFF_PLAN.md §1.5 bug #2).
    """
    event_id = event.get('event_id')
    promo_id = event.get('promotion_id')
    if not event_id or not promo_id:
        return

    # Defensive status check (kept from the FIGHT_RESOLVED era).
    # Phase E1.2: the subscription was switched from FIGHT_RESOLVED
    # to EVENT_COMPLETED (see register_subscribers below). EVENT_COMPLETED
    # is only published by fight_engine._update_event_status_after_
    # resolution on the transition INTO 'completed' (fight_engine.py
    # lines 2489-2498), so when this function fires via the bus the
    # status is guaranteed 'completed'. The check below is therefore
    # redundant in the bus path but is kept as a defensive guard for
    # direct-call paths (e.g. scripts/backfill_finance_transactions.py
    # calls this function directly with an event dict — the guard
    # ensures we still only process truly-completed events). Per
    # docs/ECON_STAFF_PLAN.md §1.5 bug #2 the original FIGHT_RESOLVED
    # subscription was "fragile" because it required this status check
    # to filter out the per-fight fires that happen before the final
    # fight resolves. EVENT_COMPLETED eliminates that fragility.
    status = conn.execute(
        "SELECT status FROM events WHERE event_id=?", (event_id,)
    ).fetchone()
    if not status or status[0] != 'completed':
        return  # not done yet — wait for the last fight

    # Check if we already processed finances for this event
    existing = conn.execute(
        "SELECT 1 FROM finance_transactions WHERE event_id=? "
        "AND transaction_type='ticket_sales'",
        (event_id,)
    ).fetchone()
    if existing:
        return  # already processed

    # Get event details — Phase E3.2 also fetches the player-set
    # lever columns (ticket_price, marketing_spend, ppv_price, is_ppv).
    # These columns are NULL/missing on pre-v3.21.0 DBs (defensive
    # COALESCE handles that — the column-default 80/0/60/0 is applied
    # at the migration level via ALTER TABLE ADD COLUMN DEFAULT, so
    # existing rows already have the defaults; this defensive fallback
    # only matters if a future code path INSERTs an event without
    # setting the levers).
    #
    # Phase 3 (PHASE3-IMPLEMENT) — also fetch p.size_tier (used by
    # the new tier-based defaults: ticket_price, staff_salary, fighter
    # purse multiplier). ticket_price is fetched RAW (e.ticket_price,
    # NOT COALESCE'd) so we can detect NULL and substitute the tier-
    # based default in Python below (COALESCE can't pick a tier-
    # dependent default inline).
    event_row = conn.execute(
        "SELECT e.event_date, e.venue_id, e.market_id, "
        "v.capacity, m.heat_level, p.broadcast_tier, p.name, "
        "p.reputation, p.fan_trust, p.size_tier, "
        "e.ticket_price, "
        "COALESCE(e.marketing_spend, 0), "
        "COALESCE(e.ppv_price, 60), "
        "COALESCE(e.is_ppv, 0) "
        "FROM events e "
        "LEFT JOIN venues v ON v.venue_id=e.venue_id "
        "LEFT JOIN markets m ON m.market_id=e.market_id "
        "JOIN promotions p ON p.promotion_id=e.promotion_id "
        "WHERE e.event_id=?",
        (event_id,),
    ).fetchone()
    if not event_row:
        return

    event_date, venue_id, market_id, venue_cap, market_heat, \
        broadcast_tier, promo_name, promo_reputation, promo_fan_trust, \
        size_tier, ticket_price_raw, marketing_spend, ppv_price, is_ppv = event_row

    venue_cap = venue_cap or 5000
    market_heat = market_heat or 50
    # Phase E2 — clamp rep/trust to [0, 100] defensively (schema has
    # CHECK constraints but defensive clamping protects against any
    # future drift / direct-INSERT path).
    promo_reputation = max(0, min(100, promo_reputation or 50))
    promo_fan_trust = max(0, min(100, promo_fan_trust or 50))
    # Phase 3 (PHASE3-IMPLEMENT) — resolve ticket_price. If the player
    # set the lever (NOT NULL AND != 80), use it. If NULL OR == 80
    # (the legacy schema default that represents "no player value yet"
    # — applied to all pre-existing events via ALTER TABLE ADD COLUMN
    # DEFAULT 80), fall back to the tier-based default (Major=120,
    # Mid=60, Small=35). This replaces the flat COALESCE(e.ticket_price,
    # 80) so all promos no longer charge the same $80 default — major
    # promos get UFC-level prices ($120), small regional promos get
    # $35 (matches real-world regional MMA ticket pricing).
    #
    # Treating 80 as "unset" is consistent with the original migration
    # intent: when the ticket_price column was added (v3.21.0), all
    # existing events got 80 (the schema default), and new events
    # inserted without an explicit ticket_price also get 80. So 80
    # means "system default — apply tier-based override". If the player
    # deliberately sets ticket_price=80, they get 80 (the rare case
    # where they want a major promo to charge $80 — the explicit
    # intent overrides the tier default).
    _TICKET_PRICE_LEGACY_DEFAULT = 80
    if ticket_price_raw is None or ticket_price_raw == _TICKET_PRICE_LEGACY_DEFAULT:
        ticket_price = _DEFAULT_TICKET_PRICE_BY_TIER.get(
            size_tier, _DEFAULT_TICKET_PRICE_FALLBACK,
        )
    else:
        ticket_price = int(ticket_price_raw)
    # Phase E3.2 — clamp the player-set levers to their documented
    # ranges (defensive against bad INSERT paths).
    ticket_price = max(20, min(300, int(ticket_price or 80)))
    marketing_spend = max(0, min(500000, int(marketing_spend or 0)))
    ppv_price = max(30, min(80, int(ppv_price or 60)))
    is_ppv = 1 if is_ppv else 0
    # Phase P2.4 — fill_rate now takes marketing_spend + venue_capacity
    # + ticket_price (price elasticity) + promo_reputation (small draw
    # boost for high-rep promos). The old call (E3.2) only passed
    # market_heat + marketing + cap, so ticket price had zero effect on
    # attendance. Now maxing ticket_price to $300 floors fill at 0.10
    # — the arena is almost empty.
    fill_rate = _compute_fill_rate(market_heat,
                                   marketing_spend=marketing_spend,
                                   venue_capacity=venue_cap,
                                   ticket_price=ticket_price,
                                   promo_reputation=promo_reputation)

    # ---- REVENUE ----
    # 1. Ticket sales — Phase E3.2 uses the player-set ticket_price
    #    (was: auto-computed as 50 + market_heat*2). Pre-E3 events
    #    have ticket_price=80 (the migration default) so the per-head
    #    revenue changes from a market-heat-tied value to a flat $80,
    #    which is closer to real-world pricing + makes the player's
    #    lever decision meaningful.
    tickets_sold = int(venue_cap * fill_rate)
    ticket_revenue = tickets_sold * ticket_price
    _record_transaction(conn, promo_id, event_id, None,
                        'ticket_sales', ticket_revenue,
                        f"{tickets_sold} tickets × ${ticket_price}",
                        event_date)

    # 2. Broadcast revenue (Phase E2.1 + E3.2 — real PPV model per
    #    §3.1.2 + player-set marketing/ppv_price/is_ppv per §3.3).
    #    If is_ppv=0 on a PPV-tier promo, skip PPV entirely and use
    #    the flat broadcast rights fee (the player chose a non-PPV
    #    Fight Night on a PPV-capable promo).
    broadcast_rev = _compute_broadcast_revenue(
        conn, event_id, broadcast_tier,
        promo_reputation, promo_fan_trust,
        marketing_spend=marketing_spend,
        ppv_price=ppv_price,
        is_ppv=bool(is_ppv),
    )
    _record_transaction(conn, promo_id, event_id, None,
                        'broadcast_revenue', broadcast_rev,
                        f"broadcast ({broadcast_tier}"
                        f"{', PPV' if is_ppv else ', flat'})",
                        event_date)

    # 2b. Sponsorship (Phase E2.2 — recurring, reputation-tied per §3.1.3)
    # Replaces the one-shot opening-balance seed pattern. Every event
    # now generates a sponsorship row scaled by rep × fan_trust.
    sponsorship_rev = _compute_sponsorship_revenue(
        broadcast_tier, promo_reputation, promo_fan_trust,
    )
    if sponsorship_rev > 0:
        _record_transaction(conn, promo_id, event_id, None,
                            'sponsorship', sponsorship_rev,
                            f"sponsorship ({broadcast_tier})",
                            event_date)

    # 3. Merchandise (Phase E2.3 — attendance × marketability ×
    #    fan_trust × $8 per §3.1.4. Replaces the old linear formula
    #    (Σ fighter.marketability × $100) which ignored attendance
    #    AND fan_trust entirely.)
    attendance = _get_event_attendance(
        conn, event_id, venue_cap=venue_cap, market_heat=market_heat,
    )
    avg_card_mkt = _get_avg_card_marketability(conn, event_id)
    fan_trust_factor = 0.5 + (promo_fan_trust / 100.0)  # 100→1.5x, 20→0.7x
    merch_revenue = int(
        attendance * (avg_card_mkt / 100.0) * fan_trust_factor *
        _MERCH_PER_ATTENDEE_BASE
    )
    if merch_revenue > 0:
        _record_transaction(conn, promo_id, event_id, None,
                            'merchandise', merch_revenue,
                            f"merch ({attendance} attendees, "
                            f"avg mkt {avg_card_mkt})",
                            event_date)

    # 3b. Concessions (Phase E2.4 — attendance × $15 per §3.1.5)
    # New income type — food/beer/parking avg per attendee. Scales
    # with attendance so big-venue shows earn noticeably more than
    # small-venue ones. Simple flat calculation per spec; Phase E3
    # may add VIP / hospitality tiers later.
    concessions_revenue = int(attendance * _CONCESSIONS_PER_ATTENDEE)
    if concessions_revenue > 0:
        _record_transaction(conn, promo_id, event_id, None,
                            'concessions', concessions_revenue,
                            f"concessions ({attendance} attendees)",
                            event_date)

    # Cache fights list for the fighter-purse loop below — fetches one
    # row per (fighter, fight) on the card with the contract + fight
    # metadata needed to compute base + win + finish + title + main_
    # event bonuses (Phase E2.5). Was previously just a fighter_id
    # list used twice for merch; now a single richer query replaces
    # both the merch query (E2.3 uses _get_avg_card_marketability
    # helper instead) and the old fighter_purse loop.
    #
    # Phase F1.2 — also fetches fi.marketability so the main-event
    # star multiplier can scale the base purse for headliners. Other
    # card slots don't get the multiplier (only main event pays
    # market-rate; prelim fighters stay on the per-event pro-rata).
    fighter_fight_rows = conn.execute(
        "SELECT DISTINCT fp.fighter_id, fp.fight_id, "
        "f.card_slot, f.is_title_fight, f.result_type, "
        "f.winner_fighter_id, c.salary, c.bonus_structure, "
        "COALESCE(fi.marketability, 0) AS mkt "
        "FROM fight_participants fp "
        "JOIN fights f ON f.fight_id=fp.fight_id "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "LEFT JOIN fighter_contracts fc ON fc.fighter_id=fp.fighter_id "
        "LEFT JOIN contracts c ON c.contract_id=fc.contract_id "
        "   AND c.status='active' "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchall()

    # ---- EXPENSES ----
    # 4. Fighter purses (Phase E2.5 — base + win + finish + title +
    #    main_event bonuses per §3.2.1. Replaces the old "pay salary
    #    to everyone" model which ignored winner/finish/title/main_
    #    event status AND paid the FULL annual salary per event
    #    instead of pro-rating it.)
    for (fid, fight_id, card_slot, is_title, result_type,
         winner_id, salary, bonus_structure, mkt) in fighter_fight_rows:
        # Defensive defaults — fighters without an active contract
        # get a $10k nominal salary (matches the legacy fallback).
        salary = salary if salary else 10000
        # Phase P2.5 — base purse pro-rata × 1.5 multiplier (was × 1.0).
        # Phase F1.2 — _N_EVENTS_PER_YEAR tightened from 4 to 3.
        # Phase 3 (PHASE3-IMPLEMENT) — replace the flat
        # _BASE_PURSE_MULTIPLIER with a tier-based one so major promos
        # pay UFC-level purses (multiplier 3.0) while small regional
        # promos pay $500-$2K per fight (multiplier 0.5). Mid promos
        # stay at 1.5 (the old default). The lookup falls back to
        # _DEFAULT_PURSE_MULT (1.0) if size_tier is somehow unknown.
        purse_mult = _PURSE_MULT_BY_TIER.get(
            size_tier, _DEFAULT_PURSE_MULT,
        )
        base_purse = (salary / _N_EVENTS_PER_YEAR) * purse_mult
        is_winner = (winner_id is not None and fid == winner_id)
        is_finish = (result_type or '').lower() in _FINISH_RESULT_TYPES
        is_title_fight = bool(is_title)
        is_main_event = (card_slot == 'main_event')
        # Phase F1.2 — star multiplier for main event fighters. A
        # headliner's base purse scales with their marketability:
        #   mkt=0 → ×1.0, mkt=50 → ×1.5, mkt=80 → ×1.8, mkt=100 → ×2.0
        # This is applied to the base purse BEFORE the win bonus is
        # computed (so win_bonus_pct scales the boosted base, which
        # is realistic — a star's win bonus is also star-sized).
        if is_main_event:
            star_mult = _MAIN_EVENT_STAR_MULT_BASE + (
                _MAIN_EVENT_STAR_MULT_PER_MKT * max(0, min(100, int(mkt or 0)))
            )
            base_purse = base_purse * star_mult
        win_bonus_pct = _parse_win_bonus_pct(bonus_structure)

        win_bonus = base_purse * win_bonus_pct if is_winner else 0
        finish_bonus = _FINISH_BONUS if (is_winner and is_finish) else 0
        # Phase 4 (PHASE4-IMPLEMENT) — tier-scaled title fight + main
        # event bonuses. Was flat $250K / $100K across all promos which
        # made title fights unsustainable for small/mid promos. The
        # size_tier is fetched in the event_row query above (Phase 3).
        if is_title_fight:
            title_bonus = _TITLE_FIGHT_BONUS_BY_TIER.get(
                size_tier, _TITLE_FIGHT_BONUS_DEFAULT,
            )
        else:
            title_bonus = 0
        if is_main_event:
            main_event_bonus = _MAIN_EVENT_BONUS_BY_TIER.get(
                size_tier, _MAIN_EVENT_BONUS_DEFAULT,
            )
        else:
            main_event_bonus = 0
        total_purse = int(
            base_purse + win_bonus + finish_bonus +
            title_bonus + main_event_bonus
        )
        if total_purse > 0:
            # Description lists each bonus component for debugging —
            # e.g. "purse (base $4166, win $2083, finish $5000,
            # title $25000, ME $10000)" so a player reading the
            # transaction log can see WHY a fighter's purse was big.
            # Phase F1.2 — for main event, also note the star
            # multiplier so the player can verify "yes, my mkt=85
            # headliner is being paid 1.85× their pro-rata base".
            base_label = f"base ${int(base_purse)}"
            if is_main_event:
                base_label += f" (×{star_mult:.2f} star, mkt {int(mkt or 0)})"
            parts = [base_label]
            if win_bonus:
                parts.append(f"win ${int(win_bonus)}")
            if finish_bonus:
                parts.append(f"finish ${finish_bonus}")
            if title_bonus:
                parts.append(f"title ${title_bonus}")
            if main_event_bonus:
                parts.append(f"ME ${main_event_bonus}")
            _record_transaction(conn, promo_id, event_id, fid,
                                'fighter_purse', -total_purse,
                                f"purse ({', '.join(parts)})",
                                event_date)

    # 5. Venue rental (Phase E2.7 — tiered by venue_type per §3.2.3.
    #    Replaces the flat _VENUE_COST_PER_SEAT = $5 lookup with a
    #    4-tier model: arena $7, ballroom $5, theater $4, outdoor $3.
    #    Falls back to $5 if venue_type is unknown/missing.
    #    Phase 8 (PHASE8-A-ECONOMICS) — additionally multiplies the
    #    per-seat cost by a tier multiplier (major 1.0x, mid 0.7x,
    #    small 0.4x) so small regional promos pay ~$2K-$5K venue rental
    #    instead of $14K, matching real-world regional venue rent.)
    venue_type = _get_venue_type(conn, venue_id)
    cost_per_seat = _VENUE_COST_PER_SEAT_BY_TYPE.get(
        venue_type, _DEFAULT_VENUE_COST_PER_SEAT,
    )
    venue_mult = _VENUE_COST_MULT_BY_TIER.get(
        size_tier, _VENUE_COST_MULT_DEFAULT,
    )
    venue_cost = venue_cap * cost_per_seat * venue_mult
    _record_transaction(conn, promo_id, event_id, None,
                        'venue_rental', -venue_cost,
                        f"venue rental ({venue_cap} seats × "
                        f"${cost_per_seat}/seat × {venue_mult} tier_mult, "
                        f"{venue_type or 'unknown'})",
                        event_date)

    # 6. Staff salaries (Phase 3 / PHASE3-IMPLEMENT — flat per-event
    #    rate by size_tier. Replaces the per-event pro-rata (sum of
    #    contracts.salary / _N_EVENTS_PER_YEAR for active staff) which
    #    produced absurd $208K/event staff costs on Alpha (10 staff ×
    #    ~$2.5M total annual salary / 12 events = $208K — staff are
    #    paid per show, not their full annual salary per show).
    #
    #    New model: a flat fee per event based on promo tier:
    #      - Major: $15,000/event (cutmen, doctors, commentators,
    #        security, timekeepers, etc. for a UFC-scale production)
    #      - Mid:    $8,000/event
    #      - Small:  $3,000/event (regional show skeleton crew)
    #
    #    The promo's staff_contracts.salary is now treated as the
    #    annual retainer (will be paid via a separate monthly tick
    #    in Phase E5), NOT pro-rated per event. We still query
    #    staff_contracts to get n_staff for the description label so
    #    the finance log shows "12 staff" (transparency), but the
    #    amount is the flat tier rate.
    staff_rows = conn.execute(
        "SELECT sc.staff_id, c.salary, s.role_type "
        "FROM staff_contracts sc "
        "JOIN contracts c ON c.contract_id=sc.contract_id "
        "JOIN staff s ON s.staff_id=sc.staff_id "
        "WHERE c.promotion_id=? AND c.status='active'",
        (promo_id,),
    ).fetchall()
    n_staff = len(staff_rows)
    # Phase 3 (PHASE3-IMPLEMENT) — flat per-event rate by tier.
    staff_cost = _STAFF_SALARY_PER_EVENT_BY_TIER.get(
        size_tier, _DEFAULT_STAFF_SALARY_PER_EVENT,
    )
    if staff_cost > 0:
        _record_transaction(conn, promo_id, event_id, None,
                            'staff_salary', -staff_cost,
                            f"staff salaries ({n_staff} staff, "
                            f"tier={size_tier or 'unknown'}, "
                            f"${staff_cost:,} flat per-event)",
                            event_date)

    # 7. Medical costs (per fight)
    n_fights = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=?",
        (event_id,),
    ).fetchone()[0]
    medical_cost = n_fights * _MEDICAL_COST_PER_FIGHT
    _record_transaction(conn, promo_id, event_id, None,
                        'medical_cost', -medical_cost,
                        f"medical ({n_fights} fights)", event_date)

    # 8. Weight cut penalties (if any fights were cancelled or catch-weight)
    wc_rows = conn.execute(
        "SELECT fighter_id, purse_penalty_pct FROM weight_cut_log "
        "WHERE event_id=? AND purse_penalty_pct > 0",
        (event_id,),
    ).fetchall()
    for fid, penalty_pct in wc_rows:
        contract_row = conn.execute(
            "SELECT c.salary FROM contracts c "
            "JOIN fighter_contracts fc ON fc.contract_id=c.contract_id "
            "WHERE fc.fighter_id=? AND c.status='active'",
            (fid,),
        ).fetchone()
        salary = contract_row[0] if contract_row else 10000
        penalty_amount = int(salary * penalty_pct / 100)
        if penalty_amount > 0:
            _record_transaction(conn, promo_id, event_id, fid,
                                'weight_cut_penalty', -penalty_amount,
                                f"weight cut penalty ({penalty_pct}%)",
                                event_date)

    # 9. Marketing spend (Phase E3.2 — player-set, written as a
    #    'marketing' finance_transactions row, negative). The player's
    #    marketing_spend lever is the upfront cost of boosting fill
    #    rate + PPV buys. Always written when marketing_spend > 0 (so
    #    the player sees the cost in the finance log even if the event
    #    didn't generate the boost they hoped for — they overpaid).
    # Phase P2.4 — description uses the tighter 0.15 fill cap + 1.3 PPV
    # multiplier cap (was 0.30 / 2.0).
    if marketing_spend > 0:
        _record_transaction(
            conn, promo_id, event_id, None,
            'marketing', -marketing_spend,
            f"marketing ({marketing_spend} spend, "
            f"+{int(min(_MARKETING_FILL_BOOST_CAP, marketing_spend / max(1, venue_cap * 5)) * 100)}% fill"
            f"{(' +' + str(int(min(_MARKETING_PPV_MULT_CAP, marketing_spend / _MARKETING_PPV_MULT_DIVISOR) * 100)) + '% PPV') if is_ppv else ''})",
            event_date,
        )

    # 10. Phase E5 — General Manager cost reduction. The promo's active
    #     GMs (role_type='general_manager' with active staff_contracts)
    #     reduce total expenses by (gm.skill_level / 1000) × total_expense,
    #     capped at 10% with a 100-skill GM. Per docs/DESIGN_REVIEW_E5.md
    #     §5: "Write a gm_savings note in the finance summary (NOT a
    #     separate transaction — just reduces the total)."
    #
    #     Implementation: query the SUM of negative finance_transactions
    #     for this event (the total expenses just written in steps 4-9),
    #     compute the GM bonus, and CREDIT promotions.current_cash by
    #     the savings amount (no finance_transactions row written — the
    #     brief explicitly forbids a separate transaction). The savings
    #     is logged via DEBUG_FINANCE + the news item's body gets a
    #     "gm_savings=$X" note appended.
    gm_row = conn.execute(
        "SELECT COALESCE(SUM(s.skill_level), 0) "
        "FROM staff s "
        "JOIN staff_contracts sc ON sc.staff_id=s.staff_id "
        "JOIN contracts c ON c.contract_id=sc.contract_id "
        "WHERE s.role_type='general_manager' "
        "  AND s.promotion_id=? "
        "  AND c.status='active'",
        (promo_id,),
    ).fetchone()
    gm_skill_total = gm_row[0] if gm_row and gm_row[0] is not None else 0
    gm_savings = 0
    if gm_skill_total > 0:
        # Total expenses = absolute value of SUM of negative txns.
        expense_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
            "WHERE event_id=? AND amount < 0",
            (event_id,),
        ).fetchone()
        total_expenses = abs(expense_row[0]) if expense_row else 0
        if total_expenses > 0:
            # Per the brief: (gm_skill / 1000) × total_expense, max 10%.
            # With a single 100-skill GM: 100/1000 = 0.10 = 10% savings.
            # Multiple GMs stack linearly up to the cap.
            gm_fraction = min(0.10, gm_skill_total / 1000.0)
            gm_savings = int(total_expenses * gm_fraction)
            if gm_savings > 0:
                # Credit the promo's current_cash directly (NO
                # finance_transactions row per the brief). The
                # DEBUG_FINANCE log below surfaces the savings for
                # debugging.
                conn.execute(
                    "UPDATE promotions SET current_cash = current_cash + ?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
                    (gm_savings, promo_id),
                )

    # ---- 11. Show quality adjustment (Phase F1.1) ----
    # After all base revenue + expense rows are written AND the GM
    # savings has been applied, check whether show_rating has written
    # a row for this event yet. The event bus fires EVENT_COMPLETED
    # subscribers in registration order; show_rating.register_subscribers
    # is called BEFORE finance.register_subscribers in
    # app_web.register_all_subscribers (registration_modules list:
    # [..., "show_rating", "finance", ...]). So by the time
    # _process_event_finance runs, show_ratings has its row.
    #
    # The adjustment is a SECOND finance_transactions row (type =
    # 'show_quality_adjustment') rather than mutating the original
    # broadcast_revenue / merchandise rows — preserves the audit trail
    # so a player reading the finance log can see "PPV $X, merch $Y,
    # show quality adjustment +$Z" instead of just the inflated PPV.
    #
    # Tiers (per docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F1.1):
    #   rating >= 80 → +30% (blockbuster — word of mouth drove extra buys)
    #   rating >= 60 → +10% (good show — modest bump)
    #   rating >= 40 → ±0%  (average — no adjustment)
    #   rating <  40 → -20% (dud — fans demand refunds)
    #
    # The multiplier applies to PPV + merch revenue (the two streams
    # most affected by word-of-mouth). Gate, sponsorship, and
    # concessions are ticketed-attendance-driven, not viewership-
    # driven, so they don't get the quality bump.
    show_quality_row = conn.execute(
        "SELECT overall_rating FROM show_ratings WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if show_quality_row and show_quality_row[0] is not None:
        show_rating = int(show_quality_row[0])
        if show_rating >= _SHOW_QUALITY_GREAT_THRESHOLD:
            quality_mult = _SHOW_QUALITY_MULT_GREAT
            verdict_phrase = "blockbuster — word of mouth drove extra buys"
        elif show_rating >= _SHOW_QUALITY_GOOD_THRESHOLD:
            quality_mult = _SHOW_QUALITY_MULT_GOOD
            verdict_phrase = "good show — modest bump"
        elif show_rating >= _SHOW_QUALITY_DUD_THRESHOLD:
            quality_mult = _SHOW_QUALITY_MULT_AVG
            verdict_phrase = "average — no adjustment"
        else:
            quality_mult = _SHOW_QUALITY_MULT_DUD
            verdict_phrase = "dud — fans demand refunds, bad word of mouth"

        # Only write a row if the multiplier is non-trivial (skip the
        # ±0% case so the finance log doesn't get a "no adjustment"
        # row per average show — keeps the log clean).
        if quality_mult != 1.0:
            # Compute the BASE ppv + merch revenue from the rows just
            # written (handles both PPV-tier events where broadcast_
            # revenue IS the PPV revenue, and non-PPV events where
            # broadcast_revenue is a flat rights fee — we only adjust
            # the PPV component + merch in either case to keep the
            # semantics "word of mouth affected viewership-driven
            # revenue").
            ppv_base_row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
                "WHERE event_id=? AND transaction_type='broadcast_revenue' "
                "AND description LIKE '%PPV%'",
                (event_id,),
            ).fetchone()
            ppv_base = int(ppv_base_row[0] or 0) if ppv_base_row else 0
            merch_base_row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM finance_transactions "
                "WHERE event_id=? AND transaction_type='merchandise'",
                (event_id,),
            ).fetchone()
            merch_base = int(merch_base_row[0] or 0) if merch_base_row else 0

            adjustment_amount = int(
                (quality_mult - 1.0) * (ppv_base + merch_base)
            )
            if adjustment_amount != 0:
                pct_label = int(round((quality_mult - 1.0) * 100))
                sign = "+" if pct_label >= 0 else ""
                _record_transaction(
                    conn, promo_id, event_id, None,
                    'show_quality_adjustment', adjustment_amount,
                    f"show quality (rating={show_rating}, "
                    f"{sign}{pct_label}% PPV+merch — {verdict_phrase})",
                    event_date,
                )

    # Write a finance news item via voice descriptors
    _write_finance_news(conn, promo_id, event_id, event_date)

    # Phase E5 — surface GM savings in the debug log if active.
    if gm_savings > 0 and os.environ.get('DEBUG_FINANCE'):
        try:
            print(f"[finance] GM savings for promo={promo_id} "
                  f"event={event_id}: ${gm_savings:,} "
                  f"(gm_skill_total={gm_skill_total}, "
                  f"fraction={min(0.10, gm_skill_total / 1000.0):.1%})",
                  flush=True)
        except Exception:
            pass

    # Phase E1.5 — debug hook. Only emits if the DEBUG_FINANCE env var
    # is set, so production log volume is unaffected. Lets you verify
    # the GUI path writes finance rows without rummaging in the DB:
    #
    #   DEBUG_FINANCE=1 python src/app_web.py
    #
    # Then click Advance Day / Resolve Fight; you'll see one log line
    # per event-completion. Placed AFTER _write_finance_news (which
    # already computes the net P&L) so we can report the actual net
    # impact rather than a projected guess.
    if os.environ.get('DEBUG_FINANCE'):
        try:
            net_row = conn.execute(
                "SELECT SUM(amount) FROM finance_transactions "
                "WHERE event_id=?",
                (event_id,),
            ).fetchone()
            net = net_row[0] if net_row and net_row[0] is not None else 0
            print(f"[finance] processing event_id={event_id} "
                  f"promo_id={promo_id} net=${net:,.2f}", flush=True)
        except Exception:
            # Defensive — debug print must never break the finance flow.
            pass


def _write_finance_news(conn, promo_id, event_id, event_date):
    """Write a news item about the event's financial performance."""
    # Compute P&L
    pnl_row = conn.execute(
        "SELECT SUM(amount) FROM finance_transactions WHERE event_id=?",
        (event_id,),
    ).fetchone()
    pnl = pnl_row[0] if pnl_row and pnl_row[0] else 0

    # Voice descriptor for the P&L — CR-BALANCE: expanded from 5
    # fixed phrases to 8+ variants per tier to prevent repetitive
    # headlines ("event highly profitable" × 51 in 90-day audit).
    import random as _rng
    if pnl > 200000:
        desc = _rng.choice([
            "highly profitable",
            "a financial success",
            "a blockbuster at the box office",
            "a money-making night",
        ])
        sentiment = "positive"
    elif pnl > 50000:
        desc = _rng.choice([
            "modestly profitable",
            "a steady earner",
            "solid but unspectacular",
            "in the black",
        ])
        sentiment = "positive"
    elif pnl > 0:
        desc = _rng.choice([
            "barely broke even",
            "a thin-margin night",
            "scraped by financially",
        ])
        sentiment = "neutral"
    elif pnl > -100000:
        desc = _rng.choice([
            "operated at a loss",
            "a rough night for the books",
            "bled money",
        ])
        sentiment = "negative"
    else:
        desc = _rng.choice([
            "hemorrhaging cash",
            "a financial disaster",
            "a night to forget on the balance sheet",
        ])
        sentiment = "negative"

    promo_name = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?", (promo_id,)
    ).fetchone()[0]

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
        "sentiment, topic, event_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id,
         f"{promo_name} event {desc}",
         f"The latest {promo_name} event was {desc}, with a net "
         f"{'profit' if pnl > 0 else 'loss'} for the promotion.",
         sentiment, "finance", event_id, event_date),
    )


def register_subscribers():
    """Register finance system subscribers on the event bus.

    Call once at startup (after event_bus is available).

    Phase E1.2 (docs/ECON_STAFF_PLAN.md §1.5 bug #2) — subscription
    switched from FIGHT_RESOLVED to EVENT_COMPLETED. EVENT_COMPLETED
    is published exactly once per event by fight_engine._
    update_event_status_after_resolution on the transition to
    'completed' (fight_engine.py:2489-2498), which is the semantic
    intent ("when an event completes"). This matches the pattern
    already used by show_rating.py:638 + reputation.py:458.

    Trade-off: if any future code path sets events.status='completed'
    WITHOUT publishing EVENT_COMPLETED, finance would not fire. Today
    the only such path is _update_event_status_after_resolution,
    which also publishes EVENT_COMPLETED, so the switch is safe. The
    defensive status check at the top of _process_event_finance is
    kept as a belt-and-braces guard for direct-call paths.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(Events.EVENT_COMPLETED, _process_event_finance,
                  name="finance.process_event")
