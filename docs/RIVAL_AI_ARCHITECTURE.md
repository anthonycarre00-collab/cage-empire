# RIVAL AI — Architecture Design

> **Task ID:** RIVAL-AI-DESIGN
> **Status:** PLANNING ONLY — no code changes. This document is the
> build target for the next implementation task.
> **Author:** Rival AI Architecture Designer (general-purpose sub-agent)
> **Date:** 2026-08-19 (sim), staged against the post-2c37f32 world.
> **Parent docs:** `docs/CAGE_EMPIRE_SOUL.md` (5 pillars),
> `docs/REPLAN_B_VOICE_WORLD.md` Part 5 (Alive World spec),
> `docs/CONVENTIONS.md` §13 (Design Law) + §15 (Event Bus).

---

## 0. Executive Summary

The current `src/rival_ai.py` (547 lines) does three things:
schedules events, resolves cards on event night, and signs free
agents at a 10% weekly rate per rival promotion. It uses two
existing knobs (`promotions.ai_aggression` 0–100 and
`promotions.ai_spending_style` ∈ {conservative, balanced,
aggressive}) and reuses the player's `schedule_next_event` +
`resolve_next_fight` + `sign_free_agent` functions.

What it does **not** do: archetype-driven behaviour, staff
hiring/firing, budget management, fighter cutting, bidding wars,
the no-tapping-up soft rule, or any form of intentional
imperfection. The user has halted all coding until these gaps are
specified.

This document specifies a **rule-based + weighted-random** rival
AI organised around **4 promotion archetypes** (Major League,
Regional Power, Grassroots, Rising Star), **6 decision types**
(event scheduling, matchmaking, signing, cutting, staff,
budget), and **6 imperfection mechanisms** (archetype bias,
recency bias, loyalty, matchup mistakes, budget mistakes,
whimsy). Performance target: **< 200ms per rival-AI tick across
all 9 rival promotions combined**, achieved by round-robin
scheduling days and cached roster evaluations.

**Single most important architectural decision:** introduce a
**MINOR schema bump** adding `promotions.ai_archetype` (TEXT) +
`promotions.ai_scheduling_day_of_week` (INTEGER 1–7), and split
the rival-AI work into a **`src/services/rival_ai/` package** of
7 thin modules. Everything else (events, fights, contracts,
staff, finance_transactions tables) is reused unchanged.

---

## 1. Design Philosophy

### 1.1 "The player is part of the universe, not the center of it"

In practice this means four observable things, every one of
which is missing today:

1. **Rival promotions act without player input.** Today the AI
   only schedules an event "if the promotion has no scheduled
   event" and signs a free agent "10% chance per week." That is
   reactive. The new AI **proactively** evaluates roster gaps,
   coaching staff, and budget every week — even when the player
   is idle. The 30-day-without-player-action contract in
   `REPLAN_B_VOICE_WORLD.md §5.3` requires 10–20 rival events
   per sim-month; today the AI produces ~3–4.

2. **The free-agent market is contested.** Today each promo
   picks a random FA independently — no promo ever "loses" a
   signing. The new AI introduces **bidding wars**: when 2+
   promos want the same FA on the same weekly tick, a single
   winner is chosen by an offer-score formula (budget + prestige
   + path-to-title + coach quality + 20% randomness). The
   losers get a news item: *"Pacific Rim lost out on Diego
   Reyes to European Fight Network."*

3. **Rival promotions have their own storylines.** The AI does
   not optimise against the player. Alpha Combat (player) signing
   a star does not trigger a "reaction" from RFL — RFL acts on
   its own schedule. The player notices RFL's moves via the news
   feed, not via prompt-and-counter-prompt duels. (Open Question
   Q2 raises whether this should change.)

4. **The AI's events resolve through the same event-bus as the
   player's.** All 16 event types (`FIGHT_RESOLVED`,
   `TITLE_CHANGED`, `EVENT_COMPLETED`, `FIGHTER_SIGNED`, …) fire
   for rival fights. News engine, social media, morale, punditry,
   and ranking systems all see rival activity. This is already
   true today (because the AI calls the player's
   `resolve_next_fight`); the new architecture preserves it.

### 1.2 "Realistic, not flawless"

The user's exact caveat: *"the AI can never put on flawless
shows/matches/fights it must be more realistically balanced."*

A flawless AI is one that always picks the highest-marketability,
highest-competitiveness matchup; always signs the best-value
free agent; always fires the right coach at the right time. Such
an AI feels robotic and, worse, makes the player feel like the
**only** entity in the world capable of bad decisions. That
breaks the "part of the universe" fantasy.

The new AI is **deliberately imperfect** via 6 mechanisms
(specified in §6). The headline numbers:

- **10–15% of all decisions are "whims"** — the AI picks a
  less-optimal option from the candidate pool just because. This
  is the upper bound; most decision types use 5–10% whimsy, with
  matchmaking pushing higher because it's the most player-visible
  surface.
- **Archetype bias** ensures each promo makes *consistent* errors
  of its own kind (Major League overpays for stars; Grassroots
  hoards cast-offs) rather than random errors. This is the
  Football Manager / OOTP pattern: AI managers are plausible
  characters, not optimisers.
- **Recency bias** ensures a promo's recent event result shifts
  its behaviour for 1–2 sim-weeks (a flop makes them
  conservative; a hit makes them swing for the fences).

The card builder (`_build_main_event` etc. in
`services/matchmaking.py`) currently produces *optimal* main
events (champion vs #1 contender, or #1 vs #2 for a vacant
title). The new architecture introduces a **separate rival
matchmaker** (`services/rival_ai/matchmaker.py`) that wraps that
builder and introduces intentional mismatches 15–25% of the time
(squash matches, stylistic clashes, rematch-too-soon, head-
scratchers). See §3.2.

### 1.3 "Fair challenge by promotion size"

Alpha Combat ($50M cash, 60 fighters, reputation 85, major tier)
must behave **qualitatively differently** from French Savate
Championship ($1.8M cash, 21 fighters, reputation 35, small
tier). Today both use the same `ai_aggression`-based cadence
(2/4/6 weeks). The new AI introduces **4 archetypes** (§2) that
drive every decision axis: cadence, matchmaking style, signing
strategy, staff investment, risk tolerance, and budget
allocation.

The fairness contract is asymmetric and intentional:

- A **Major League** rival should pose a *real* threat to the
  player's prestige — it signs the same calibre of free agent,
  puts on the same calibre of marquee event, and competes for
  the same champions. Losing the bidding war for a 22-year-old
  prodigy to Alpha Combat should sting (the player IS Alpha
  Combat — but RFL also bids).
- A **Grassroots** rival should pose *no threat* to the player's
  prestige but should still feel alive — it books quarterly
  shows in cheap venues, signs cast-offs, and occasionally
  develops a prospect that the player notices and tries to poach
  when the prospect's contract expires.
- The player (Alpha Combat, Major League) is one of 4+ Major
  League / Regional Power promotions. The world is not built
  around the player; the player is a participant.

### 1.4 "Not too complex"

The brief is explicit: *"get the ai logic right but not too
complex."* This rules out:

- Neural nets / learned policies (no training, no inference
  engine, no model weights).
- Behaviour trees with deep nesting (the AI is a stateless
  rule-evaluator, not a goal-oriented planner).
- Per-fighter optimisation (the AI evaluates rosters in
  aggregate, not 60 individual fighter plans per promo).
- Cross-promotion negotiation (no AI-vs-AI diplomacy layer;
  bidding wars are a single-tick resolution, not a multi-tick
  negotiation).

The right paradigm is **rule-based with weighted randomness**,
the same paradigm used by Football Manager's AI managers and
OOTP's AI GMs. Each decision type is a pure function:
`decision(inputs, archetype, rng) -> action`. The rules are
inspectable, debuggable, and tunable via constants at the top of
each module. No decision function should exceed ~80 lines of
logic.

The complexity budget is **~1,800–2,200 lines of new code**
across 7 modules (vs. the current 547-line `rival_ai.py`). Each
module averages ~250–350 lines including docstrings.

---

## 2. Promotion Archetypes

### 2.1 The 4 archetypes

Each promotion is assigned **one** archetype at seed (and
re-evaluated quarterly per §3.7). The archetype drives every
decision axis via the per-axis constants in §2.2.

| Archetype | Description | Event cadence | Matchmaking style | Signing strategy | Staff investment | Risk tolerance | Example promo (current world) |
|---|---|---|---|---|---|---|---|
| **Major League** | Big budget, prestige-focused, marquee events, signs established stars | Bi-weekly (every ~14 sim-days) | Marquee + safe; champion vs #1 contender 70% of main events; rare squash only for prospect development | Sign proven contenders + champions (potential ≥ 70, age ≤ 33); bid aggressively on contested elites | Heavy: 3+ scouts, 2+ commentators, full medical + cutman + GM roster | High — will bid 110–130% of "fair value" in a war | Alpha Combat Federation (player), Rival Fight League |
| **Regional Power** | Medium budget, development-focused, scouts + develops prospects, sells high | Monthly (every ~28 sim-days) | Balanced; co-main is prospect-vs-gatekeeper; main event is contender-vs-contender | Sign rookies + unproven talent (potential ≥ 60, age ≤ 28); rare star signing only when budget allows | Moderate: 2 scouts, 1–2 commentators, 1 doctor, 1 cutman, 1 GM | Medium — bids up to 100% of fair value, walks away above that | Pacific Rim Championship, European Fight Network |
| **Grassroots** | Small budget, survival-focused, short-term deals, cast-offs | Quarterly (every ~84 sim-days) | Safe + showcase; main event is "two veterans coming off losses" or "gatekeeper vs cast-off"; almost never a title fight | Sign released fighters + cheap contracts (potential ≥ 30, age unrestricted); no bidding wars | Minimal: 1 scout, 1 commentator, 1 doctor, 1 cutman, 1 GM | Low — never bids above 80% of fair value; walks away instantly | Mexican Boxing & Brawl, Nordic Fight Nights, Australian Outback Fights, French Savate Championship |
| **Rising Star** | Ambitious, aggressive growth, willing to overspend for a breakthrough; assigned dynamically when a promo's cash jumps > 50% in a quarter | Monthly (every ~28 sim-days) | Risky; books prospect-vs-contender and contender-vs-champion earlier than the ranking justifies; title fights 30% more often than archetype would suggest | Gamble on high-potential prospects (potential ≥ 65, age ≤ 25); bid aggressively on elites when budget allows; overspend tolerated | Heavy investment in development: 3 scouts, elite coach pursuit | Very high — will bid 130–160% of fair value in a war; occasionally busts | Eastern Bloc Combat (cash $4M but ai_aggression 55, size small); South American Warriors (cash $3M, ai_aggression 60, size small) |

### 2.2 Per-axis constants

Each archetype is a frozen dict in
`services/rival_ai/archetypes.py`. Below is the spec; the
implementation will be a single `ARCHETYPES` dict literal.

```python
ARCHETYPES = {
  "major_league": {
    "event_cadence_days":      14,         # bi-weekly
    "event_window_days":       (14, 35),   # pick event_date in [today+14, today+35]
    "card_size":               (10, 13),   # major-tier card (matches _CARD_SIZE_BY_TIER)
    "main_event_title_pct":    0.70,       # 70% of main events are title fights
    "matchmaking_safe_pct":    0.75,       # 75% safe, 20% showcase, 5% head-scratcher
    "signing_potential_floor": 70,
    "signing_age_max":         33,
    "bid_premium_pct":         0.30,       # will bid up to 130% of fair value
    "staff_target":            {"scout": 3, "commentator": 3, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.55, "staff": 0.10,
                                "venue": 0.20, "marketing": 0.10, "reserve": 0.05},
    "cut_aggressiveness":      0.40,       # 40% chance to cut an eligible underperformer per month
    "whimsy_pct":              0.05,       # 5% of decisions are whims
  },
  "regional_power": {
    "event_cadence_days":      28,
    "event_window_days":       (21, 45),
    "card_size":               (7, 9),
    "main_event_title_pct":    0.50,
    "matchmaking_safe_pct":    0.65,       # 65% safe, 25% showcase, 10% head-scratcher
    "signing_potential_floor": 60,
    "signing_age_max":         28,
    "bid_premium_pct":         0.00,       # bids fair value, walks away above
    "staff_target":            {"scout": 2, "commentator": 2, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.50, "staff": 0.12,
                                "venue": 0.18, "marketing": 0.10, "reserve": 0.10},
    "cut_aggressiveness":      0.30,
    "whimsy_pct":              0.08,
  },
  "grassroots": {
    "event_cadence_days":      84,
    "event_window_days":       (45, 75),
    "card_size":               (5, 6),
    "main_event_title_pct":    0.20,
    "matchmaking_safe_pct":    0.85,       # 85% safe, 10% showcase, 5% head-scratcher
    "signing_potential_floor": 30,
    "signing_age_max":         None,       # no age cap — will sign 38yo cast-offs
    "bid_premium_pct":         -0.20,      # bids 80% of fair value, walks instantly above
    "staff_target":            {"scout": 1, "commentator": 1, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.45, "staff": 0.08,
                                "venue": 0.25, "marketing": 0.05, "reserve": 0.17},
    "cut_aggressiveness":      0.50,
    "whimsy_pct":              0.10,
  },
  "rising_star": {
    "event_cadence_days":      28,
    "event_window_days":       (14, 35),
    "card_size":               (7, 9),
    "main_event_title_pct":    0.65,       # books title fights earlier than ranking justifies
    "matchmaking_safe_pct":    0.50,       # 50% safe, 30% showcase, 20% head-scratcher (aggressive)
    "signing_potential_floor": 65,
    "signing_age_max":         25,
    "bid_premium_pct":         0.60,       # will bid 160% of fair value (overspend tolerated)
    "staff_target":            {"scout": 3, "commentator": 2, "doctor": 1,
                                "cutman": 1, "general_manager": 1},
    "budget_allocation":       {"fighter_salaries": 0.60, "staff": 0.15,
                                "venue": 0.15, "marketing": 0.08, "reserve": 0.02},
    "cut_aggressiveness":      0.35,
    "whimsy_pct":              0.12,
  },
}
```

### 2.3 Archetype assignment at seed

A promotion's archetype is derived from (a) `size_tier`, (b)
`current_cash`, (c) `reputation`, (d) `ai_aggression`. The
assignment function:

```
def assign_archetype(promo):
    if size_tier == 'major' and cash >= 10_000_000:
        return 'major_league'
    if size_tier == 'major' or (size_tier == 'mid' and cash >= 8_000_000):
        # major-tier cash but not the biggest, OR mid with major-tier cash
        return 'major_league' if reputation >= 70 else 'regional_power'
    if size_tier == 'mid':
        return 'regional_power'
    if size_tier == 'small':
        # Rising Star: small but aggressive + cash >= $3M
        if ai_aggression >= 55 and cash >= 3_000_000:
            return 'rising_star'
        return 'grassroots'
    return 'grassroots'  # defensive default
```

**Re-evaluation (§3.7):** every 84 sim-days (a quarter), each
promo re-runs `assign_archetype`. If the result differs from the
current `ai_archetype` column, the column is updated and a news
item is written: *"French Savate Championship has been elevated
to Regional Power status after a strong quarter."* This makes
the world feel dynamic — a Grassroots promo that wins a bidding
war for a star and grows can graduate to Regional Power.

### 2.4 Mapping the current 9 rival promotions

Applying §2.3 to the live DB as of 2026-08-19:

| Promo | size_tier | cash | reputation | ai_aggression | Assigned archetype |
|---|---|---|---|---|---|
| Alpha Combat (player) | major | $50M | 85 | 30 | major_league |
| Rival Fight League | mid | $15M | 65 | 50 | major_league (mid + cash ≥ $10M + rep ≥ 60 — qualifies via §2.3 line 4) |
| Pacific Rim Championship | mid | $12M | 60 | 45 | regional_power (mid + rep < 70) |
| European Fight Network | mid | $10M | 62 | 40 | regional_power (mid + rep < 70) |
| Mexican Boxing & Brawl | small | $6.6M | 46 | 65 | rising_star (small + aggression ≥ 55 + cash ≥ $3M) |
| Eastern Bloc Combat | small | $4M | 48 | 55 | rising_star |
| South American Warriors | small | $3M | 45 | 60 | rising_star |
| Nordic Fight Nights | small | $2.5M | 42 | 35 | grassroots (small + aggression < 55) |
| Australian Outback Fights | small | $2M | 38 | 50 | grassroots |
| French Savate Championship | small | $1.8M | 35 | 30 | grassroots |

That gives a healthy mix: 2 major_league, 2 regional_power, 3
rising_star, 3 grassroots across the 10 promotions (player
included). No archetype dominates; each will produce visible
different behaviour in the news feed.

---

## 3. The Decision Engine

The rival AI runs **6 decision types**, each specified below
with: when it runs, inputs, logic, outputs, and the
imperfection mechanisms that apply.

### 3.1 Event Scheduling

**When:** On the promo's `ai_scheduling_day_of_week` (1–7), if
the promo has no scheduled event AND at least
`archetype.event_cadence_days` have passed since the promo's
last completed event. The "scheduling day of week" column
spreads work across the week — only 1–2 promos run their full
decision engine per daily tick (see §4).

**Inputs:**
- `promotions.ai_archetype` → archetype dict
- `promotions.current_cash` (must be > estimated event cost; see
  §3.6 for the cost estimate)
- Roster availability (from `_get_available_fighters_for_card`
  in `services/matchmaking.py` — reused, not re-implemented)
- Upcoming title fights (already-scheduled title fights should
  not stack — the AI waits for the current one to resolve)
- `simulation_clock.current_date` (to pick the event_date)
- Rival event dates (avoid direct competition — see "rival
  collision" below)

**Logic:**
1. **Guard clause.** If the promo already has a `scheduled`
   event, return. If the last completed event was < cadence_days
   ago, return.
2. **Budget gate.** Estimate event cost:
   - Fighter payouts ≈ `monthly_commitment / 4` (one week of
     salaries)
   - Venue cost ≈ archetype-determined (major: $200K, mid:
     $80K, small: $25K)
   - Staff payouts ≈ archetype staff_target × $5K
   - Total estimated cost must be ≤ `current_cash *
   budget_allocation.reserve` (typically 2–17% of cash depending
   on archetype)
   - If cash < estimated cost × 1.2 (safety margin), skip this
     week. The promo is in "survival mode" — see §3.6.
3. **Pick event_date.** Sample uniformly from
   `[today + event_window_days[0], today + event_window_days[1]]`.
   Apply **rival collision avoidance**: if any other promo has a
   scheduled event within ±2 days of the sampled date, re-sample
   (max 3 attempts; if all fail, take the last sample — direct
   competition is allowed but discouraged).
4. **Build the card.** Call the rival matchmaker (§3.2) which
   returns a list of 5–13 fight dicts. The matchmaker reuses the
   card-slot structure (`main_event`, `co_main`,
   `featured_prelim`, `prelim`) from the player's matchmaking
   code but applies its own biased fighter selection.
5. **Insert.** Call a new shared helper
   `_insert_event_and_card(conn, promo_id, event_date, fights,
   event_name)` (extracted from `schedule_next_event` lines
   ~1300–1490 of `services/matchmaking.py`). This helper:
   - INSERTs the `events` row (status='scheduled', venue from
     archetype budget)
   - INSERTs each `fights` + `fight_participants` row
   - INSERTs the `event_cards` slot-mapping row per fight
   - Calls `_create_training_camp` per booked fighter (existing
     function in `services/matchmaking.py`)
6. **News item.** Write a "scheduling announcement" news item
   with the main event. (The existing `schedule_next_event`
   writes this; the new helper preserves the behaviour.)

**Output:** 1 new `events` row + 5–13 new `fights` rows + 5–13
`event_cards` rows + 10–26 `training_camps` rows + 1 news
item. All inserts in a single transaction (caller commits).

**Imperfection mechanisms applied:**
- **Archetype bias:** Major League picks the highest-reputation
  available main-event pair; Grassroots picks the cheapest two
  veterans coming off losses (the "salary dump" main event).
- **Whimsy:** 5–12% of the time (per archetype), the AI schedules
  an event one week earlier or later than the optimal date.
- **Rival collision:** Sometimes ignored (15% chance the AI
  books head-to-head against a rival — a "counter-programming"
  whim).

### 3.2 Matchmaking (within an event)

**When:** Inside §3.1 step 4 (event scheduling). Not a separate
tick — matchmaking is part of card-building.

**Inputs:**
- Available-fighters pool (from
  `_get_available_fighters_for_card`, filtered by the event's
  `before_date`).
- `fighters.weight_class_id` + `fighters.gender` (defensive
  same-gender check — preserved from the existing code).
- `rankings.rating` (ELO) for competitiveness scoring.
- `fighter_career.win_streak` / `loss_streak` (momentum).
- `fighter_career.potential` (for prospect-development scoring).
- `style_archetypes.name` (for stylistic-clash scoring).
- Recent fight history (avoid immediate rematches — fighters
  who fought each other in the last 90 days cannot be re-paired
  unless no alternative exists).

**Logic — the matchup scoring function:**

For each candidate pair (A, B) in the same weight class + same
gender, compute a 0–100 score:

```
score = (
   35 * marketability(A, B)        # fan interest
 + 30 * competitiveness(A, B)      # how close the ratings are
 + 20 * storyline(A, B)            # rivalry? common opponent? rematch?
 + 15 * development_value(A, B)    # is a prospect being tested?
)

marketability(A, B) =
    clamp((rating_A + rating_B) / 2 / 1500, 0, 1)
  + 0.20 if either fighter has win_streak >= 3
  + 0.15 if either is a current champion
  + 0.10 if both have reputation >= 70

competitiveness(A, B) =
    1 - abs(rating_A - rating_B) / 400   # 1 if equal, 0 if 400+ apart

storyline(A, B) =
    0.5 if they share a common opponent in the last 12 months
  + 0.3 if they have an active rivalry row (heat >= 40)
  + 0.2 if it's a rematch of a fight >90 days ago
  (capped at 1.0)

development_value(A, B) =
    0.5 if one fighter has potential >= 75 AND age <= 26
  + 0.3 if the other fighter is a "gatekeeper" (rating 1100–1300,
         record .500–.700, age 30+)
  + 0.2 if it's the prospect's first main-card slot
  (capped at 1.0)
```

**Realistic imperfection — the bias injector:**

The matchmaker does NOT pick the highest-scored pair. It picks
from the top-N candidates (N=5 for main event, N=8 for
co-main, N=all for prelims) using a weighted random where the
weights depend on the archetype's `matchmaking_safe_pct`:

- `safe_pct` of the time: pick the highest-scored pair (the
  "right" matchup).
- `(100 - safe_pct) * 0.6` of the time: pick a "showcase"
  matchup — a high-marketability but low-competitiveness pair
  (the prospect-vs-can fight).
- `(100 - safe_pct) * 0.4` of the time: pick a "head-scratcher"
  — a random pair from the top-N that ignores score (the
  stylistic clash, the rematch-too-soon, the ranking-inversion).

**Card assembly:**
1. **Main event:** Apply the bias injector with N=5. If
   archetype.main_event_title_pct >= the roll, REQUIRE a title
   fight (champion vs #1 contender). If no title fight is
   possible (champion injured / no eligible contender), fall
   back to non-title main event.
2. **Co-main:** Apply the bias injector with N=8, exclude_wc =
   main event's weight class (for variety).
3. **Featured prelims (1–3 depending on tier):** Apply the bias
   injector with N=all, prefer prospects (potential ≥ 70).
4. **Prelims (fill to card_size):** Use the existing
   `_build_prelim` logic from `services/matchmaking.py` (which
   already prioritises debuts and must-win fighters). This is
   the "prospect development" slot — leave it alone.

**Output:** List of fight dicts
`[{weight_class_id, fighter_a, fighter_b, card_slot,
is_title_fight, scheduled_rounds}, …]`. Handed to §3.1 step 5
for insertion.

**Imperfection mechanisms applied:**
- **Archetype bias:** Grassroots' safe_pct=0.85 means 15% of
  its matchups are non-optimal (mostly safe showcases). Rising
  Star's safe_pct=0.50 means 50% of its matchups are non-
  optimal (aggressive swings).
- **Matchup mistakes:** The head-scratcher path explicitly
  books "boring" stylistic clashes (grappler vs grappler) and
  squashes (top contender vs rookie) — by ignoring score.
- **Whimsy:** 5–12% whimsy overlay on top of the archetype
  safe_pct.

**Why a separate matchmaker module (not reusing the player's)?**
The player's `_build_main_event` etc. produce *optimal*
matchups (champion vs #1, #1 vs #2 for vacant, highest-rated
fallback). The rival AI needs to *intentionally* produce non-
optimal matchups 15–50% of the time. Adding a `rival_bias`
parameter to the player's functions would couple the player's
matchmaking to the AI's whimsy — a future tuning of the AI
would risk regressing the player's experience. The separate
`services/rival_ai/matchmaker.py` keeps the two concerns
isolated. Both call the same shared `_insert_event_and_card`
helper for DB writes — no duplication of the INSERT logic.

### 3.3 Fighter Signing (free agency)

**When:** Weekly tick (current_day % 7 == 0), during the
promo's `ai_scheduling_day_of_week`. One signing *evaluation*
per promo per week; actual signing happens only if the
evaluation produces a target.

**Inputs:**
- `promotions.ai_archetype` → signing_potential_floor,
  signing_age_max, bid_premium_pct
- Roster gaps (see logic below)
- Free-agent pool (from `fighters` WHERE
  `current_promotion_id IS NULL AND is_active=1 AND
  is_retired=0` — joined to `fighter_career` for potential +
  age + record, joined to `rankings` for rating)
- `promotions.current_cash` (must be > estimated contract cost)
- `promotions.reputation` (used in offer_score)
- Staff quality (number of scouts on the promo — more scouts =
  better offer_score, represents "better talent evaluation")

**Logic:**

1. **Identify roster gaps.** For each weight class the promo
   has a title in:
   - If the promo has < 2 fighters in that WC's top-10 ranking,
     that's a "contender gap."
   - If the promo has < 4 fighters total in that WC, that's a
     "depth gap."
   - If the promo has 0 fighters in a WC where it has a title,
     that's a "critical gap" (the title is undefendable).
   - For Rising Star archetype: if the promo has 0 fighters
     with potential ≥ 70 under age 26 in any WC, that's a
     "prospect gap."

2. **Search free agents matching the need.** Filter the FA pool
   by:
   - `potential >= archetype.signing_potential_floor`
   - `age <= archetype.signing_age_max` (if not None)
   - `weight_class_id IN (gap_weight_classes)` — only sign
     fighters at WCs where there's a gap (avoids roster bloat
     at strong WCs)
   - Already not under negotiation this tick (see bidding war
     resolution below)

3. **Evaluate offer_score for each candidate:**
   ```
   offer_score = (
       0.30 * (promotion.reputation / 100)         # prestige
     + 0.20 * (log10(promotion.current_cash + 1) / 8)  # budget
     + 0.15 * path_to_title(candidate, promotion)  # 0.0–1.0
     + 0.15 * staff_quality(promotion)             # 0.0–1.0
     + 0.10 * (1 - candidate.age / 40)             # youth bonus
     + 0.10 * (candidate.potential / 100)          # talent
   ) * (1 + rng.uniform(-0.10, 0.10))              # 20% randomness band
   ```
   `path_to_title` returns 1.0 if the candidate would
   immediately become the #1 contender at their WC in the
   promo, 0.5 if they'd be top-5, 0.2 otherwise. This is the
   "smaller promo with clearer path" factor — a Grassroots
   promo can occasionally outbid a Major League for a young
   prospect because the prospect sees a faster title shot.

4. **Bidding war resolution.** Before any signing happens, the
   signing_agent collects all promos' intended signings for
   this tick. For each FA who is wanted by 2+ promos:
   - The promo with the highest `offer_score` wins.
   - The losing promos get a news item: *"{Promo} lost out on
     {Fighter} to {Winner}."* (topic='bidding_war_lost')
   - The winning promo pays a **bid premium**: the contract
     salary is inflated by `winner.bid_premium_pct ×
     number_of_losing_bidders × 0.5`. So a Major League
     outbidding 2 losers pays +30% salary; a Rising Star
     outbidding 1 loser pays +30% salary; a Grassroots that
     somehow wins (rare — only when the FA's offer_score tilts
     on path_to_title) pays -10% (their bid_premium_pct is
     negative).
   - **Hard cap:** no promo can bid above 200% of the FA's
     "fair value" salary (fair value = potential × $1,000 +
     rating × $50). If the bid premium pushes above 200%, the
     promo walks away and the next-highest offer_score wins.

5. **Sign.** Call `sign_free_agent(conn, fighter_id,
   promotion_id, start_date, salary=bid_salary)` (existing
   function in `services/contracts.py`). This publishes
   `FIGHTER_SIGNED` on the event bus — the news engine +
   morale system fire automatically.

**RULE — no tapping up:** Step 2 filters on
`current_promotion_id IS NULL`. The signing_agent NEVER queries
fighters with a non-null `current_promotion_id`. This is
enforced at the SQL level (WHERE clause), not at the application
level — there is no code path that can bypass it. See §5 for
the soft-rule layer (contract-expiry interest).

**Output:** 0–1 `sign_free_agent` calls per promo per week
(most weeks: 0; some weeks: 1; rarely: 2 if the promo has 2
critical gaps). Plus 0–3 bidding-war-lost news items per
contest FA.

**Imperfection mechanisms applied:**
- **Archetype bias:** Major League overpays for stars
  (bid_premium_pct=+30%). Grassroots never bids above fair
  value (bid_premium_pct=-20%, walks instantly).
- **Budget mistakes:** Occasionally (5% whimsy) a Rising Star
  overspends into budget trouble — the bid_premium_pct=+60%
  pushes them into the next month's "cash < 1 month expenses"
  state, forcing §3.6 cost-cutting. This is realistic —
  promotions occasionally bust.
- **Loyalty:** If a FA was previously on the promo's roster
  (cut or contract expired), the promo gets a +0.10
  offer_score bonus ("we know the kid, he's one of ours").
- **Whimsy:** 8–12% of the time, the AI signs a FA who doesn't
  fill any roster gap — just because they had a high potential
  and the promo had cash. This is the "we couldn't let him slip
  by" signing.

### 3.4 Fighter Cutting

**When:** Monthly tick (current_day % 28 == 0). One cut
*evaluation* per promo per month.

**Inputs:**
- Roster (all active fighters on the promo)
- Per-fighter: `fighter_career.record_wins/losses`,
  `win_streak/loss_streak`, `career_health`, `potential`, age
- Per-fighter contract: `salary`, `end_date`
- `fighter_descriptors.momentum` (if available — used for the
  "fan favorite" check)

**Logic:**

1. **Score each fighter for cut risk** (0–100):
   ```
   cut_risk = (
       0.30 * loss_streak_factor      # 0 if loss_streak=0, 100 if >=4
     + 0.25 * age_factor              # 0 if age<=28, 100 if age>=38
     + 0.20 * salary_factor           # 0 if salary < $20K, 100 if > $200K
     + 0.15 * health_factor           # 0 if career_health>=80, 100 if <=40
     + 0.10 * anti_fan_favorite       # 100 if NOT a fan favorite, 0 if fan favorite
   )
   ```
   - `loss_streak_factor` = min(100, loss_streak × 25)
   - `age_factor` = clamp((age - 28) × 10, 0, 100)
   - `salary_factor` = clamp((salary - 20000) / 1800, 0, 100)
   - `health_factor` = clamp((80 - career_health) × 1.67, 0, 100)
   - `anti_fan_favorite` = 0 if the fighter has momentum ≥ 70 OR
     record_wins ≥ 15 OR is a current champion; else 100

2. **Apply the cut threshold.** A fighter is "cut-eligible" if
   `cut_risk >= 65` AND none of these **protective rules**
   apply:
   - **Champion protection:** current champions are never cut
     (they're assets).
   - **Loyalty protection:** a fighter who has been on the
     promo's roster ≥ 24 months gets +10 to the cut_risk
     threshold (i.e., cut_risk must be ≥ 75). This is the
     "he's been with us since the beginning" rule.
   - **Prospect protection:** a fighter age ≤ 26 with potential
     ≥ 70 is never cut (development asset).
   - **Title-shot protection:** a fighter scheduled for a title
     fight in the next 60 days is never cut.

3. **Apply archetype aggressiveness.** For each cut-eligible
   fighter, roll `rng.random() < archetype.cut_aggressiveness`
   to decide whether to actually cut. A Major League
   (cut_aggressiveness=0.40) cuts 40% of eligible fighters per
   month; a Grassroots (0.50) cuts half; a Regional Power (0.30)
   is more patient.

4. **Cut.** For each fighter selected for cutting:
   - `UPDATE fighters SET current_promotion_id = NULL,
     updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?`
   - `UPDATE contracts SET status = 'terminated',
     updated_at = CURRENT_TIMESTAMP WHERE contract_id = ? AND
     contract_target_type = 'fighter'` (find via
     `fighter_contracts`)
   - Write a news item: *"{Fighter} released by {Promo}."*
     (topic='release')
   - Publish `FIGHTER_STATE_CHANGED` on the event bus (so
     morale system + descriptor cache update).

**Output:** 0–3 fighter cuts per promo per month. The fighter
re-enters the FA pool (where they may be picked up by another
promo via §3.3 — often a Grassroots promo signs the cast-off,
per archetype strategy).

**Imperfection mechanisms applied:**
- **Loyalty:** the loyalty protection rule keeps veterans past
  their prime. The 24-month threshold means a Major League
  promo keeps its declining 36-year-old fan favorite because
  he's been there 3 years.
- **Recency bias:** if the promo's last event was a flop (show
  rating < 50), `cut_aggressiveness` is multiplied by 1.2 for
  the next month (panic cuts). If the last event was a hit
  (rating > 75), multiplied by 0.8 (loyalty surge).
- **Whimsy:** 10% of cuts are "head-scratcher" cuts — a fighter
  with cut_risk < 50 gets cut anyway. This is the "we're going
  in a different direction" move. Rare, but visible.

### 3.5 Staff Hiring/Firing

**When:** Quarterly tick (current_day % 84 == 0). One staff
*evaluation* per promo per quarter.

**Inputs:**
- Current staff (from `staff` WHERE `promotion_id = ?`)
- Per-staff: `role_type`, `age`, `specialty`
- For scouts: their recent discovery rate (count of
  `scout_reports` they've produced in the last 90 days where
  the scouted fighter had potential ≥ 60)
- For commentators: their tenure (long-tenured commentators
  are "voices of the brand" — protected)
- `promotions.current_cash` (must support the new hire's
  salary)
- `promotions.ai_archetype` → staff_target

**Note on coaches:** the live DB has 300 coaches, all linked to
`gym_id` (not `promotion_id`). Coaches are gym-bound staff, not
promo-bound. The rival AI's staff management handles only
promotion-bound staff: `scout`, `commentator`, `doctor`,
`cutman`, `general_manager`. See Open Question Q6 for whether
the AI should also manage gym-level coaches (a separate system).

**Logic:**

1. **Fire evaluation.** For each current staff member:
   - **Scout:** if the scout has produced < 2 useful reports
     (potential ≥ 60) in the last 90 days AND has been on
     staff ≥ 180 days → fire-eligible.
   - **Commentator:** never fired (protected — "voice of the
     brand"). Even if old. (Realism: real promotions don't
     fire their lead commentator unless forced.)
   - **Doctor / cutman:** if the promo's injury rate over the
     last quarter was > 30% above the league average →
     fire-eligible (the medical staff takes the fall). This is
     recency bias in action.
   - **General_manager:** never fired (protected — firing the
     GM is "firing yourself" for an AI promo).
   - Apply a 30% whimsy roll: even if fire-eligible, only 30%
     of fire-eligible staff are actually fired per quarter (the
     rest get "one more quarter to turn it around").
   - **Loyalty protection:** a staff member who has been on the
     promo ≥ 365 days gets a +1 quarter grace period before
     firing.
2. **Hire evaluation.** Compare current staff counts to
   `archetype.staff_target`. For each role where current <
   target:
   - Check budget: can the promo afford the hire? Estimated
     staff salary ≈ $5K–$15K per month depending on role. If
     `current_cash < 2 × monthly staff commitment`, skip the
     hire (survival mode — §3.6).
   - For scouts: only hire if the promo also has fighter
     development needs (i.e., the promo signs prospects per
     §3.3 — Major League and Rising Star always need scouts;
     Grassroots rarely does).
   - Generate a new staff row (random name from a name pool,
     random age 28–55, appropriate role_type + specialty).
     This mirrors the existing seed logic in `seed_world_phase2`.
3. **News items.** Hiring and firing both write news items
   (topic='staff'). Hiring is positive sentiment; firing is
   neutral.

**Output:** 0–2 staff changes per promo per quarter. Most
quarters: 0. Occasional quarters: 1 (a fired scout or a hired
scout). Rare quarters: 2 (a fire + a hire for the same role).

**Imperfection mechanisms applied:**
- **Loyalty:** long-tenured scouts get grace periods.
  Commentators are unfireable.
- **Recency bias:** a bad injury quarter gets the doctor/cutman
  fired (often unfairly — injuries are mostly fighter-driven,
  not staff-driven).
- **Whimsy:** 10% of hires are "name hires" — a scout with a
  famous last name (a placeholder for "we hired So-and-so's
  brother"). Cosmetic, but adds flavour.

### 3.6 Budget Management

**When:** Monthly tick (current_day % 28 == 0). One budget
*review* per promo per month.

**Inputs:**
- `promotions.current_cash`
- Monthly expenses:
  - Fighter salaries: `SELECT SUM(salary) FROM contracts WHERE
    promotion_id=? AND status='active' AND
    contract_target_type='fighter'`
  - Staff salaries: estimated `$5K × staff_count` per month
    (staff don't have explicit salary rows in the current
    schema; this is an approximation)
  - Venue costs: tracked via `finance_transactions` (events
    INSERT a row when scheduled)
- Monthly income (projected):
  - Event revenue (last 3 events' average revenue ×
    expected_events_this_month based on cadence)
  - Broadcast deals (read from `broadcast_contracts` if
    present)

**Logic — the 3-state budget machine:**

1. **Compute `cash_runway_months`** =
   `current_cash / max(1, monthly_expenses)`.
2. **State assignment:**
   - `cash_runway_months < 1.0` → **SURVIVAL** state
   - `1.0 ≤ cash_runway_months < 3.0` → **CONSERVATIVE** state
   - `3.0 ≤ cash_runway_months < 6.0` → **NORMAL** state (the
     default; archetype behaviour runs unmodified)
   - `cash_runway_months ≥ 6.0` → **EXPANSION** state
3. **State-driven behaviour modifiers:**

   | State | Event scheduling | Signing | Staff | Cut |
   |---|---|---|---|---|
   | SURVIVAL | Skip next 2 events (or move to cheapest venue); reduce card_size by 2 | No signings (signing_potential_floor set to ∞) | No hires; fire highest-paid scout if > 1 | cut_aggressiveness × 1.5 |
   | CONSERVATIVE | Cheapest venue; card_size reduced by 1 | Only fill critical gaps (no depth gaps); bid_premium_pct × 0.5 | No hires | cut_aggressiveness × 1.2 |
   | NORMAL | Archetype default | Archetype default | Archetype default | Archetype default |
   | EXPANSION | Standard venue; card_size + 1 if roster allows | Allow depth-gap signings; bid_premium_pct × 1.2 | Hire to staff_target if below | cut_aggressiveness × 0.8 |

4. **Bankruptcy protection (Open Question Q5):** if a promo
   enters SURVIVAL state for 2 consecutive months AND
   `current_cash < monthly_expenses × 0.5`, the promo enters
   **CRISIS** state. In CRISIS:
   - All signings halted.
   - Top-3 highest-salary fighters put on the cut list
     immediately (no cut_risk scoring — pure salary dump).
   - All staff except 1 scout + 1 GM put on the cut list.
   - Next event cancelled (status → 'cancelled').
   - A news item: *"{Promo} in financial crisis — major cuts
     expected."*
   - If after another month the promo is still in CRISIS, the
     promo is "sold" (a cosmetic news event) and gets a
     $2M–$5M cash injection from a new "owner" (the
     `ownership_type` column updates). This avoids true
     bankruptcy but produces a visible storyline. (See Open
     Question Q5 — supervisor may want a harsher rule.)

5. **Budget allocation enforcement.** When the promo schedules
   an event, the budget_manager pre-computes the allocation
   per `archetype.budget_allocation`. If the planned event cost
   exceeds the `venue + marketing` allocation, the event is
   downscoped (smaller venue, less marketing) rather than
   cancelled.

**Output:** A `budget_state` value (SURVIVAL / CONSERVATIVE /
NORMAL / EXPANSION / CRISIS) stored in a new column
`promotions.ai_budget_state` (TEXT, included in the MINOR
schema bump — §7.2). Read by §3.1, §3.3, §3.4, §3.5 to apply
their state-driven modifiers.

**Imperfection mechanisms applied:**
- **Budget mistakes:** the Rising Star archetype in EXPANSION
  state can overspend into SURVIVAL within 2 months (the
  bid_premium_pct=+60% + EXPANSION multiplier compounds). This
  is realistic — promotions occasionally bust.
- **Recency bias:** a hit event (show rating > 75) shifts the
  state up by 1 tier for the next month (NORMAL → EXPANSION).
  A flop (rating < 40) shifts it down by 1 (NORMAL →
  CONSERVATIVE). This is the "irrational exuberance" / "panic"
  cycle.
- **Whimsy:** 5% of monthly reviews ignore the computed state
  and pick a random adjacent state. (Mostly cosmetic — produces
  occasional weird moves.)

### 3.7 Archetype Re-evaluation

**When:** Quarterly tick (current_day % 84 == 0), before §3.5
runs.

**Logic:** Re-run `assign_archetype(promo)` (§2.3) using the
promo's current `size_tier`, `current_cash`, `reputation`, and
`ai_aggression`. If the result differs from
`promotions.ai_archetype`:
1. UPDATE the column.
2. Write a news item:
   - Upgrade: *"{Promo} has been elevated to {New Archetype}
     status after a strong quarter."*
   - Downgrade: *"{Promo} has been reclassified as {New
     Archetype} after a difficult quarter."*
3. Publish a `PROMOTION_RECLASSIFIED` event on the event bus
   (a new event type — minor extension to `event_bus.Events`;
   the news engine subscribes).

**Output:** 0–1 archetype changes per promo per quarter. Most
quarters: 0. The visible changes are rare and meaningful — a
Grassroots that develops a star and grows into a Regional Power
is a multi-year storyline.

---

## 4. Performance Architecture

### 4.1 The cadence map

The rival AI must not do everything every tick. The work is
spread across the sim calendar:

| Decision | Cadence | Ticks per sim-week | Cost per call (target) | Notes |
|---|---|---|---|---|
| Event resolution (fight night) | Daily | 0–9 (only when an event is due) | ~10ms per event | Already implemented — single-night resolution drains all fights on the event in one tick. |
| Event scheduling + matchmaking | Per-promo scheduling day (1–7) | ~1.3 promos/day × 7 days = ~9 promos/week | ~15ms per promo | Round-robin: each promo has its own scheduling day. Only 1–2 promos run their full decision engine per daily tick. |
| Fighter signing evaluation | Weekly tick (current_day % 7 == 0) | 9 promos × 1 evaluation | ~8ms per promo | Cheaper than scheduling because it's a single SQL filter + offer_score computation. |
| Fighter cutting | Monthly (current_day % 28 == 0) | 9 promos × 1 evaluation | ~12ms per promo | Roster scan + cut_risk scoring. |
| Staff hiring/firing | Quarterly (current_day % 84 == 0) | 9 promos × 1 evaluation | ~6ms per promo | Small staff counts → fast. |
| Budget review | Monthly (current_day % 28 == 0) | 9 promos × 1 evaluation | ~4ms per promo | Single SUM query + state lookup. |
| Archetype re-eval | Quarterly (current_day % 84 == 0) | 9 promos × 1 evaluation | ~1ms per promo | Pure function. |

**Per-tick cost budget:**
- Daily tick with no event resolution: ~0ms (the AI does
  nothing — only the daily event-resolution check fires, which
  is a single SELECT per promo).
- Daily tick with 1 event resolution: ~10ms.
- Weekly tick (current_day % 7 == 0): 1–2 promos run their full
  decision engine (~30ms) + 9 promos run signing evaluation
  (~70ms) = **~100ms total**.
- Monthly tick (current_day % 28 == 0): weekly cost + cutting
  (~110ms) + budget review (~36ms) = **~250ms total**.
- Quarterly tick (current_day % 84 == 0): monthly cost + staff
  (~54ms) + archetype re-eval (~9ms) = **~315ms total**.

The 200ms target is for **typical daily/weekly ticks**. Monthly
and quarterly ticks are allowed to exceed 200ms (they're rare —
4× per sim-month, 1× per sim-quarter — and the user clicks
Advance Day, not Advance Month). The brief's "< 200ms per
rival-AI tick" is interpreted as "the typical daily/weekly
tick" since those are what the user feels.

### 4.2 Round-robin scheduling days

Each promo is assigned a `ai_scheduling_day_of_week` (1–7) at
seed. Distribution goal: spread the 9 rival promos roughly
evenly across the 7 days (1–2 promos per day). Sample
assignment for the current world:

| Day of week | Promos |
|---|---|
| 1 (Mon) | Rival Fight League |
| 2 (Tue) | Pacific Rim Championship |
| 3 (Wed) | European Fight Network, Mexican Boxing & Brawl |
| 4 (Thu) | South American Warriors |
| 5 (Fri) | Eastern Bloc Combat, Nordic Fight Nights |
| 6 (Sat) | Australian Outback Fights |
| 7 (Sun) | French Savate Championship |

On a daily tick, the rival AI:
1. Runs event resolution for ALL promos (cheap SELECT per
   promo — required for fight-night correctness).
2. Runs the full decision engine (§3.1 + §3.2) ONLY for promos
   whose `ai_scheduling_day_of_week == current_day % 7 + 1`.
3. If it's a weekly tick, runs signing evaluation for ALL
   promos (this is the contested-FA resolution — must see all
   promos' intents together).
4. If it's a monthly tick, runs cutting + budget for ALL promos.
5. If it's a quarterly tick, runs staff + archetype re-eval for
   ALL promos.

### 4.3 Batched DB operations

The current `_maybe_sign_free_agent` does 1 SELECT + 1
`sign_free_agent` call (which itself does ~6 INSERTs). For 9
promos, that's 9 × 7 = 63 round-trips. The new
`signing_agent` does:
- 1 SELECT to fetch all FAs matching the *loose* filter
  (potential ≥ the lowest archetype floor across all promos).
- Per-promo filtering in Python (cheap — the FA pool is
  ~4,000 rows; in-memory filtering is sub-millisecond).
- Bidding war resolution in Python (collects all promos'
  intended signings, resolves conflicts, then issues the
  winning `sign_free_agent` calls).
- The actual `sign_free_agent` calls remain 1-per-signing
  (they publish events that other systems subscribe to —
  can't be batched into a single executemany without
  reworking the event bus contract).

For event scheduling, the `_insert_event_and_card` helper uses
`executemany` for the `fights` + `event_cards` + `training_
camps` inserts (5–13 rows each in a single round-trip).

### 4.4 Cached roster evaluations

The most expensive per-tick query today is
`_get_available_fighters_for_card` (a 4-way LEFT JOIN over the
promo's roster + injuries + suspensions + rankings + career).
For 9 promos, that's 9 × ~5ms = 45ms per weekly tick.

The new architecture caches the result of
`_get_available_fighters_for_card` per (promotion_id, date)
in a module-level dict, invalidated when any of these events
fire:
- `FIGHT_RESOLVED` (a fighter's last_fight_date changed →
  rest-eligibility changed)
- `FIGHTER_SIGNED` (roster changed)
- `INJURY_CREATED` / `INJURY_RECOVERED` (eligibility changed)
- `WEIGHT_CUT_COMPLETED` (rarely — usually doesn't change
  eligibility)

The cache is keyed on `(promotion_id, ref_date_str)`. TTL: 1
tick (cleared at the start of each new tick). On a weekly tick
where 9 promos each call the function once, the cache turns a
9-query operation into a 0-query operation (the cache is
populated by the first promo's call, then reused by subsequent
promos — wait, that's wrong, each promo has its own roster).

Correct caching: the cache is keyed on `(promotion_id,
ref_date_str)`. Within a single tick, each promo calls the
function 1–2 times (once for scheduling, possibly once for
matchmaking). The cache saves the 2nd call. Modest win (~5ms
per tick). The bigger win is across ticks: if the tick didn't
fire any invalidating events, the cache is reused on the next
tick — saves 45ms per non-event tick.

### 4.5 Lazy imports + stateless modules

Each `services/rival_ai/*.py` module is **stateless** — no
module-level mutable state, no singletons. All state lives in
the DB or in the function arguments. This makes the modules
trivially testable (no setup/teardown of module state) and
safe to call concurrently (though CAGE EMPIRE is single-
threaded).

Lazy imports: `services/rival_ai/__init__.py` lazy-imports the
submodules on first use (matching the existing `rival_ai.py`
pattern of lazy-importing `app` to avoid circular dependencies).
The `register_subscribers` function in the new `rival_ai.py`
shim imports each submodule's `register_*` function and
subscribes it.

### 4.6 Target: < 200ms per rival-AI tick

| Tick type | Estimated cost | Within 200ms? |
|---|---|---|
| Daily, no events | ~5ms (9 cheap SELECTs) | ✅ |
| Daily, 1 fight night | ~15ms | ✅ |
| Daily, 3 fight nights | ~35ms | ✅ |
| Weekly (no scheduling day) | ~80ms (9 signing evals) | ✅ |
| Weekly (1 scheduling day) | ~110ms | ✅ |
| Weekly (2 scheduling days) | ~140ms | ✅ |
| Monthly | ~250ms | ⚠️ (rare tick) |
| Quarterly | ~315ms | ⚠️ (very rare tick) |

The monthly/quarterly overage is acceptable because those
ticks are rare (4× and 1× per sim-month respectively) and the
user perceives them as "end-of-month processing" — a brief
pause is fine. If profiling shows the monthly tick exceeding
300ms in practice, the cut_evaluation can be split across 2
ticks (cut half the promos on day 28, the other half on day
29 — but this requires extending the cadence map, defer to
profiling).

---

## 5. The "No Tapping Up" Rule

### 5.1 Hard rule (already enforced)

The AI NEVER makes an offer to a fighter who has
`current_promotion_id IS NOT NULL`. This is enforced at the SQL
level in §3.3 step 2:

```sql
SELECT f.fighter_id
FROM fighters f
JOIN fighter_career fc ON fc.fighter_id = f.fighter_id
WHERE f.current_promotion_id IS NULL          -- ← THE RULE
  AND f.is_active = 1
  AND f.is_retired = 0
  AND fc.potential >= ?
  AND f.weight_class_id IN (...)
```

There is no application-level code path that can bypass this —
the WHERE clause is in every signing query. Even if a future
bug tried to call `sign_free_agent` with a contracted fighter's
ID, the existing `sign_free_agent` function (in
`services/contracts.py` lines 199–217) refuses with a printed
warning ("already signed to promotion_id=X") and returns None.
The rule is double-enforced: SQL filter + application guard.

### 5.2 Soft rule — contract-expiry interest

When a fighter's contract is within 30 days of expiry, rival
promotions can express "interest" (a news item only — no
actual signing attempt). This produces the storyline: *"Rumored
interest from Pacific Rim Championship in John Vale"* without
violating the hard rule.

**Implementation:**
- On the weekly signing-evaluation tick, in addition to
  querying the FA pool (§3.3), the signing_agent queries
  fighters whose contract `end_date` is within 30 days:
  ```sql
  SELECT f.fighter_id, f.first_name || ' ' || f.last_name,
         c.promotion_id AS current_promo, c.end_date
  FROM fighters f
  JOIN fighter_contracts fc ON fc.fighter_id = f.fighter_id
  JOIN contracts c ON c.contract_id = fc.contract_id
  WHERE c.status = 'active'
    AND c.end_date <= date(simulation_clock.current_date, '+30 days')
    AND c.promotion_id != ?   -- not the evaluating promo
    AND f.is_active = 1
    AND f.is_retired = 0
  ```
- For each such fighter, the evaluating promo computes an
  `interest_score` (a simplified version of `offer_score`
  from §3.3 — same formula, but weighted toward "would this
  fighter fill a roster gap").
- If `interest_score >= 0.6`, write a "rumored interest" news
  item:
  - Headline: *"Rumored interest from {Promo} in {Fighter}"*
  - Body: *"{Promo} is rumored to be interested in signing
    {Fighter} when his contract with {CurrentPromo} expires
    on {end_date}."*
  - Topic: `'tapping_up_rumor'`
  - Sentiment: `'neutral'`
- **Rate limit:** max 1 rumored-interest news item per
  (promo, fighter) pair per 30 days. This prevents the same
  rumor from repeating weekly.
- **Whimsy:** 10% of eligible interest-score candidates don't
  get a rumor (the promo keeps its interest quiet). 5% of
  ineligible candidates (interest_score < 0.6) get a rumor
  anyway (a journalist fabricates a story — tabloid realism).

When the contract actually expires (handled by the existing
`_check_contract_expiry` in `tick_processor.py`), the fighter
becomes a FA and §3.3 takes over. If the rumored promo wins the
bidding war, the storyline pays off; if not, the rumor was
just noise (realistic — not all rumors pan out).

### 5.3 Bidding wars (multi-promo FA competition)

Already specified in §3.3 step 4. Summary of the rule:

1. **Detection.** The signing_agent collects all promos'
   intended signings for the weekly tick before any
   `sign_free_agent` calls are made. For each FA wanted by 2+
   promos, a bidding war is triggered.
2. **Resolution.** The promo with the highest `offer_score`
   wins. `offer_score` formula (from §3.3):
   - 30% reputation + 20% budget + 15% path_to_title + 15%
     staff_quality + 10% youth + 10% talent, with ±10%
     randomness.
   - The 20% randomness band is what allows upsets: a
     Grassroots promo with a great path_to_title can occasionally
     beat a Major League for a young prospect, but only when
     the Major League's randomness roll is low AND the
     Grassroots' roll is high.
3. **Premium.** The winner pays a salary premium proportional
   to `archetype.bid_premium_pct × number_of_losers × 0.5`,
   capped at 200% of fair value.
4. **Loser news.** Each losing promo gets a news item:
   - Headline: *"{Promo} lost out on {Fighter} to {Winner}"*
   - Body: *"{Fighter} has signed with {Winner} despite
     interest from {Promo}."*
   - Topic: `'bidding_war_lost'`
   - Sentiment: `'negative'` (mild — the promo's fans are
     disappointed)

This is the single most important "alive world" mechanism in
the new AI. Today, no promo ever "loses" a signing — each
picks an independent random FA. With bidding wars, the player
will see: *"Rival Fight League lost out on Diego Reyes to
European Fight Network"* and feel the world is contested.

### 5.4 What the AI NEVER does

- ❌ Never makes an offer to a contracted fighter (hard SQL rule).
- ❌ Never trades fighters with another promo (no trade system
  exists; the AI does not invent one).
- ❌ Never negotiates a contract buyout with another promo
  (no buyout system; the AI waits for contract expiry).
- ❌ Never makes a "verbal agreement" before contract expiry
  that bypasses the bidding war (the soft rule is news-only).
- ❌ Never signs a retired fighter (`sign_free_agent` already
  refuses — `is_retired=1` guard).
- ❌ Never signs an inactive fighter (`is_active=0` guard).

---

## 6. Realistic Imperfection (the "not flawless" requirement)

The user's caveat: *"the AI can never put on flawless
shows/matches/fights it must be more realistically balanced."*

Six imperfection mechanisms, each specified as a tunable
constant in `services/rival_ai/imperfection.py`:

### 6.1 Archetype bias

Each archetype makes **consistent** errors of its own kind.
This is the Football Manager / OOTP pattern: AI managers are
plausible characters with exploitable weaknesses.

- **Major League** overpays for established stars
  (`bid_premium_pct=+30%`) and underinvests in scouting
  relative to development (signs stars, doesn't develop
  prospects → roster ages → eventually declines).
- **Regional Power** is too patient with prospects
  (`cut_aggressiveness=0.30`) → roster bloats with
  "almost-but-not-quite" fighters.
- **Grassroots** hoards cast-offs (`signing_age_max=None`,
  `signing_potential_floor=30`) → roster fills with old
  losing-record fighters → low show quality → low revenue →
  stays Grassroots forever (a realistic trap).
- **Rising Star** overspends on gambles (`bid_premium_pct=+60%`,
  `matchmaking_safe_pct=0.50`) → frequent budget crises →
  sometimes graduates to Regional Power, sometimes collapses
  back to Grassroots.

These biases are **persistent** (archetype doesn't change week-
to-week) and **predictable** (a player who scouts RFL will
learn that RFL always bids aggressively on elites). This is
what makes the AI feel like a character, not a calculator.

### 6.2 Recency bias

A promo's recent event result shifts its behaviour for 1–2
sim-weeks. Implemented as a modifier applied to the archetype
constants:

- After a **hit event** (show rating > 75, computed by the
  existing `show_rating` module):
  - `bid_premium_pct` × 1.2 (more aggressive bidding)
  - `matchmaking_safe_pct` - 0.10 (riskier matchmaking)
  - `cut_aggressiveness` × 0.8 (loyalty surge — keep the squad)
  - Budget state shifted UP one tier (NORMAL → EXPANSION) for
    the next month
- After a **flop event** (show rating < 40):
  - `bid_premium_pct` × 0.5 (gun-shy)
  - `matchmaking_safe_pct` + 0.10 (conservative matchmaking)
  - `cut_aggressiveness` × 1.2 (panic cuts)
  - Budget state shifted DOWN one tier (NORMAL → CONSERVATIVE)
    for the next month

The modifier decays after 14 sim-days (the promo "forgets" the
event). Multiple events in the window compound the modifier
(2 hits in 14 days = 2× the upshift, capped at +50% above
archetype baseline).

This is the "irrational exuberance" / "panic" cycle that real
promotions go through. It's the most observable imperfection —
the player will notice that RFL got hot after a big event and
is suddenly bidding on everyone.

### 6.3 Loyalty

Three loyalty rules:

1. **Veteran loyalty.** A fighter who has been on the promo's
   roster ≥ 24 months gets +10 to the cut_risk threshold (§3.4
   — they must hit cut_risk ≥ 75 instead of 65). This is the
   "he's been with us since the beginning" rule.
2. **Coach loyalty.** Long-tenured scouts get a +1 quarter
   grace period before firing (§3.5). Commentators are
   unfireable.
3. **Re-signing loyalty.** When evaluating a FA who was
   previously on the promo's roster, the promo gets +0.10 to
   `offer_score` (§3.3). This is the "welcome back, kid" rule
   — a promo is more likely to re-sign a fighter they
   previously cut than to sign a stranger of equivalent value.

These rules produce storylines: the 38-year-old veteran who
should have been cut 2 years ago but keeps getting one more
fight; the scout who hasn't found a prospect in 3 years but is
"family"; the prodigy who left for a bigger promo, flopped, and
came home.

### 6.4 Matchup mistakes

The matchmaker's `head-scratcher` path (§3.2) explicitly books
*bad* matchups 5–20% of the time (per archetype
`matchmaking_safe_pct`). The mistake types:

- **Boring stylistic clash:** grappler vs grappler, wrestler vs
  wrestler. The matchmaker's scoring function would normally
  penalise these (low marketability), but the head-scratcher
  path ignores score.
- **Squash:** top contender vs rookie. The matchmaker would
  normally require a prospect-development angle; the head-
  scratcher pairs them anyway.
- **Rematch too soon:** two fighters who fought < 90 days ago
  get re-paired. Normally the matchmaker excludes these via
  the recent-fight-history filter; the head-scratcher bypasses
  the filter.
- **Ranking inversion:** the #5 contender vs the #15 contender
  when #5 vs #6 was available. The matchmaker picks the worse
  matchup purely from whimsy.

These are NOT bugs — they're features. Real promotions book
head-scratchers all the time (the UFC's "money fight" era is
canonical example). The player will see RFL book a grappler-vs-
grappler main event and think "why would they book that?" —
which is exactly the reaction a real MMA fan has watching real
promotions.

### 6.5 Budget mistakes

Two budget mistake mechanisms:

1. **Bidding war escalation.** The bid_premium_pct stack
   (§3.3 step 4 + §3.6 EXPANSION multiplier + §6.2 recency
   bias) can compound to push a Rising Star into paying 180%
   of fair value for a FA. This is the "we couldn't let him
   slip by" mistake — and it's realistic (the UFC's UFC 200
   concussion of paying Brock Lesnar $2.5M is canonical).
2. **Crisis mismanagement.** A promo in SURVIVAL state
   (§3.6) sometimes (15% whimsy) makes a "panic signing" — a
   cheap veteran cast-off who doesn't fill a roster gap, just
   because the GM feels they need to "do something." This
   wastes salary budget and prolongs the crisis.

These mistakes are how promos go bankrupt (or near-bankrupt)
in real life. The Crisis state + ownership-change escape hatch
(§3.6 step 4) ensures the AI never truly dies — it just
suffers, recovers, and the player sees the storyline.

### 6.6 Randomness (whimsy)

10–15% of all decisions are "whims" — the AI picks a less-
optimal option just because. Each decision type has its own
whimsy budget:

| Decision | Whimsy % | Whim behaviour |
|---|---|---|
| Event scheduling | 5–12% (per archetype) | Schedules on a non-optimal date; ignores rival collision; books a smaller card than roster allows. |
| Matchmaking | 15–25% (per archetype) | Head-scratcher path (§6.4). |
| Signing | 8–12% | Signs a FA who doesn't fill a gap ("couldn't let him slip by"). |
| Cutting | 10% | Cuts a fighter with cut_risk < 50 ("going in a different direction"). |
| Staff | 10% | Hires a "name hire" (cosmetic). Fires a staff member who was performing OK. |
| Budget | 5% | Picks a random adjacent state. |

The whimsy is implemented as a `rng.random() < whimsy_pct`
check at the start of each decision function. If the roll
succeeds, the function picks from a "whim pool" (a small set
of pre-defined non-optimal actions) instead of running its
normal logic.

This is the **anti-robot** mechanism. Without it, the AI would
always make the same decisions in the same situations; with
it, the AI occasionally does something the player can't
predict. Predictability + occasional surprise = plausibility.

---

## 7. Implementation Approach

### 7.1 File structure

Keep `src/rival_ai.py` as the entry point (event-bus
subscriber). Extract decision logic into a new
`src/services/rival_ai/` package:

```
src/
├── rival_ai.py                          # entry point — subscribes to TICK_ADVANCED,
│                                        #   dispatches to the right submodule per tick type.
│                                        #   ~120 lines (down from 547).
└── services/
    └── rival_ai/
        ├── __init__.py                  # lazy-imports the submodules.
        ├── archetypes.py                # ARCHETYPES dict + assign_archetype().
        ├── event_scheduler.py           # §3.1 — picks event_date, calls matchmaker, inserts.
        ├── matchmaker.py                # §3.2 — biased matchup scoring + card assembly.
        ├── signing_agent.py             # §3.3 — roster gap detection, bidding war resolution.
        ├── cutting_agent.py             # §3.4 — cut_risk scoring + protective rules.
        ├── staff_manager.py             # §3.5 — fire/hire scouts, commentators, doctors, etc.
        ├── budget_manager.py            # §3.6 — 3-state budget machine + crisis handling.
        ├── imperfection.py              # §6 — whimsy + recency bias + loyalty helpers.
        └── _shared.py                   # _insert_event_and_card (extracted from
                                         #   services/matchmaking.py schedule_next_event),
                                         #   roster cache, offer_score formula,
                                         #   news-item writer.
```

**Why a package, not a single file?** The current `rival_ai.py`
is 547 lines and does 3 things. The new AI does 6 things, each
with its own decision logic, imperfection mechanisms, and
testing surface. A single file would be ~2,000 lines —
unreadable. The package lets each module be ~250–350 lines
(readable, testable in isolation). The entry point
(`src/rival_ai.py`) shrinks to ~120 lines of dispatch logic.

### 7.2 Schema bump (MINOR)

Per CONVENTIONS §1.1, adding columns to an existing table is a
MINOR bump (e.g., 1.x.y → 1.(x+1).y). Three new columns on
`promotions`:

```sql
ALTER TABLE promotions ADD COLUMN ai_archetype TEXT DEFAULT 'grassroots';
ALTER TABLE promotions ADD COLUMN ai_scheduling_day_of_week INTEGER DEFAULT 1;
ALTER TABLE promotions ADD COLUMN ai_budget_state TEXT DEFAULT 'normal';
```

**Migration function** (added to `src/build_db.py`'s migration
registry, mirroring the existing pattern at CONVENTIONS §16.3):

```python
def _migrate_v1_x_y_to_v1_x_plus_1_y(conn):
    """Add ai_archetype, ai_scheduling_day_of_week, ai_budget_state columns."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(promotions)")}
    if 'ai_archetype' not in cols:
        conn.execute("ALTER TABLE promotions ADD COLUMN ai_archetype TEXT DEFAULT 'grassroots'")
    if 'ai_scheduling_day_of_week' not in cols:
        conn.execute("ALTER TABLE promotions ADD COLUMN ai_scheduling_day_of_week INTEGER DEFAULT 1")
    if 'ai_budget_state' not in cols:
        conn.execute("ALTER TABLE promotions ADD COLUMN ai_budget_state TEXT DEFAULT 'normal'")
    # Backfill: assign archetype + scheduling day for existing promos.
    from services.rival_ai.archetypes import assign_archetype, assign_scheduling_day
    for row in conn.execute("SELECT promotion_id, size_tier, current_cash, reputation, ai_aggression FROM promotions"):
        promo_id, size_tier, cash, rep, aggr = row
        archetype = assign_archetype(size_tier, cash, rep, aggr)
        day = assign_scheduling_day(promo_id)
        conn.execute("UPDATE promotions SET ai_archetype=?, ai_scheduling_day_of_week=?, ai_budget_state='normal' WHERE promotion_id=?", (archetype, day, promo_id))
```

**Why these 3 columns (and not more)?**

- `ai_archetype`: must be persisted (queried by every decision
  module). Could be derived from `(size_tier, current_cash,
  reputation, ai_aggression)` on every query, but persisting
  it makes the quarterly re-evaluation explicit + debuggable
  (the player can SEE that RFL is "major_league" via a future
  UI inspector).
- `ai_scheduling_day_of_week`: must be persisted (queried
  every daily tick). Could be derived from
  `promotion_id % 7`, but persisting it lets the seed
  distribute promos evenly across days 1–7 (a mod function
  would cluster them).
- `ai_budget_state`: must be persisted (queried by §3.1, §3.3,
  §3.4, §3.5). Could be recomputed every query, but
  persisting it makes the state transitions visible + lets
  the news engine write "Promo enters financial crisis" items
  on state change.

No other schema changes. All decision logic reads/writes
existing tables (`events`, `fights`, `fight_participants`,
`event_cards`, `training_camps`, `fighters`, `contracts`,
`fighter_contracts`, `staff`, `finance_transactions`,
`news_items`, `news_sources`).

### 7.3 Event bus — one new event type

Add `PROMOTION_RECLASSIFIED` to `event_bus.Events` (currently
16 event types — this is #17). Published by §3.7 when a promo's
archetype changes. Subscribed by:

- News engine — writes the "elevated to X status" / "reclassified
  as Y" news items.
- (Future) UI — to refresh the rival promotions screen if it's
  open.

No other event-bus changes. The rival AI continues to subscribe
to `TICK_ADVANCED` (existing) and publish no other events of
its own (it relies on the existing `FIGHT_RESOLVED`,
`FIGHTER_SIGNED`, `EVENT_COMPLETED`, `TITLE_CHANGED`,
`FIGHTER_STATE_CHANGED` events published by the functions it
calls).

### 7.4 Testing strategy

For each decision type, **one acceptance test** specifying
inputs → expected output. These become the build-target
acceptance tests for the implementation task.

| Test ID | Decision | Setup | Expected |
|---|---|---|---|
| T-RIVAL-01 | Archetype assignment | size=major, cash=$50M, rep=85, aggr=30 | `assign_archetype()` returns `'major_league'` |
| T-RIVAL-02 | Archetype assignment | size=small, cash=$2M, rep=38, aggr=50 | returns `'grassroots'` |
| T-RIVAL-03 | Archetype assignment | size=small, cash=$4M, rep=48, aggr=55 | returns `'rising_star'` |
| T-RIVAL-04 | Event scheduling | Major League promo with 60-fighter roster, no scheduled event, $50M cash | 1 new `events` row, 10–13 new `fights`, status='scheduled', event_date in [today+14, today+35] |
| T-RIVAL-05 | Event scheduling | Grassroots promo with $1.8M cash, monthly_commit=$525K, runway=3.4 months | State=NORMAL, event scheduled with card_size 5–6, cheap venue |
| T-RIVAL-06 | Event scheduling | Same Grassroots promo but cash=$200K (runway=0.4 months) | State=SURVIVAL, no event scheduled this week |
| T-RIVAL-07 | Matchmaker | Major League, 60 fighters, main_event_title_pct=0.70 | Over 100 simulated events, ≥65% have a title-fight main event (within ±5% tolerance for randomness) |
| T-RIVAL-08 | Matchmaker | Rising Star, safe_pct=0.50 | Over 100 simulated events, ≥40% of main events are non-optimal (showcase or head-scratcher) |
| T-RIVAL-09 | Matchmaker | Any archetype | Over 100 events, zero mixed-gender fights (defensive same-gender check preserved) |
| T-RIVAL-10 | Signing — no tapping up | FA pool contains 1 fighter with `current_promotion_id IS NOT NULL` (corrupt test data) | The signing_agent's SQL filter excludes them; they are never signed |
| T-RIVAL-11 | Signing — bidding war | 2 promos (Major League + Rising Star) both want FA X on the same tick | Major League wins 70–80% of the time over 100 trials (offer_score formula favors reputation + budget); Rising Star wins 20–30% (randomness + path_to_title) |
| T-RIVAL-12 | Signing — bidding war news | Same setup as T-RIVAL-11 | Loser promo gets a `bidding_war_lost` news item mentioning the winner |
| T-RIVAL-13 | Cutting | Fighter with loss_streak=4, age=37, salary=$200K, career_health=40, not a fan favorite, not a champion, tenure=12 months | cut_risk ≥ 65 → cut-eligible; with cut_aggressiveness=0.40, cut fires ~40% of the time over 100 trials |
| T-RIVAL-14 | Cutting — champion protection | Same fighter but is_current_champion=1 | Not cut (champion protection rule) |
| T-RIVAL-15 | Cutting — loyalty protection | Same fighter but tenure=30 months | cut_risk threshold raised to 75; not cut (or cut less often) |
| T-RIVAL-16 | Staff — fire scout | Scout with 0 useful reports in 90 days, tenure=200 days | Fire-eligible; 30% chance to actually fire per quarter |
| T-RIVAL-17 | Staff — commentator protection | Commentator with tenure=10 years | Never fired |
| T-RIVAL-18 | Budget — state machine | Promo with cash=$50K, monthly_expenses=$200K | State=SURVIVAL; next 2 events skipped; no signings; cut_aggressiveness×1.5 |
| T-RIVAL-19 | Budget — crisis | Promo in SURVIVAL for 2 months + cash < expenses×0.5 | State=CRISIS; top-3 salaries put on cut list; staff trimmed; news item written |
| T-RIVAL-20 | Performance — weekly tick | 9 rival promos, weekly tick, no events due | Total rival-AI time < 200ms (measured via `time.perf_counter()` around the subscriber) |
| T-RIVAL-21 | Performance — monthly tick | 9 rival promos, monthly tick | Total rival-AI time < 350ms |
| T-RIVAL-22 | Soft rule — tapping-up rumor | Fighter with contract end_date in +25 days, eval promo has interest_score=0.7 | 1 `tapping_up_rumor` news item written; same promo+fighter pair does not produce another rumor within 30 days |

These 22 tests are the acceptance bar. The implementation task
is complete when all 22 pass.

### 7.5 Implementation phasing

The implementation task should be split into 4 sub-tasks
(each ~1 day of work), in dependency order:

1. **Phase 1 — Foundation.** Schema bump (§7.2). `archetypes.py`
   + `_shared.py` (extracted helpers). Backfill existing
   promos. Tests T-RIVAL-01, 02, 03.
2. **Phase 2 — Core decisions.** `event_scheduler.py` +
   `matchmaker.py` + `signing_agent.py`. Tests T-RIVAL-04, 05,
   06, 07, 08, 09, 10, 11, 12. This is the bulk of the player-
   visible behaviour.
3. **Phase 3 — Management.** `cutting_agent.py` +
   `staff_manager.py` + `budget_manager.py`. Tests T-RIVAL-13,
   14, 15, 16, 17, 18, 19.
4. **Phase 4 — Imperfection + soft rules + perf.**
   `imperfection.py` (recency bias, loyalty, whimsy).
   Tapping-up rumor path. Performance tuning. Tests T-RIVAL-20,
   21, 22.

Total estimated effort: **4–6 days** of focused implementation
+ testing.

---

## 8. Open Questions for the Supervisor

These are decisions where the supervisor's input is needed
before implementation can proceed. Each is tagged with the
default assumption the architecture makes if the supervisor
doesn't weigh in.

### Q1. Should the AI ever make cross-promotion Superfight offers?

**Default assumption:** No. Cross-promotion superfights are out
of scope for v1. The AI books only intra-promotion events.
(Superfights would require a new `superfight_offers` table, a
negotiation protocol, and a broadcast-revenue-sharing model —
too complex for "not too complex.")

**Question:** Does the supervisor want a future Superfight
system (e.g., Alpha Combat champ vs RFL champ) on the roadmap?
If yes, the `events` table may need a `is_cross_promotion`
flag now to avoid a future MAJOR bump.

### Q2. Should the AI adapt to the player's actions?

**Default assumption:** No. The AI does not monitor the
player's signings, event quality, or roster moves. The AI acts
on its own schedule (its `ai_scheduling_day_of_week`). The
player's actions affect the AI only through shared resources
(the FA pool — if the player signs a FA, the AI can't also sign
them; the news feed — the player sees the AI's moves).

**Question:** Does the supervisor want a "rival reaction"
layer (e.g., if the player signs a star, RFL bids 10% harder
on the next FA out of "we can't fall behind" pressure)? This
would make the world feel more responsive to the player but
also more gameable (the player could trick RFL into
overbidding). The brief says "the user/player lives within the
bigger universe as part of it world does not revolve around
them" — which argues for NO adaptation. Confirm.

### Q3. How aggressive should bidding wars be?

**Default assumption:** The 20% randomness band in
`offer_score` (§3.3) produces upsets ~20% of the time (the
lower-offer promo wins). The bid_premium_pct cap is 200% of
fair value.

**Question:** Is 20% randomness too much (feels arbitrary) or
too little (feels deterministic)? Should the cap be 150%
(conservative) or 300% (allows blockbuster overpays)? The
default is a middle ground.

### Q4. Should AI promotions ever go bankrupt?

**Default assumption:** No. The CRISIS state (§3.6 step 4)
triggers an "ownership change" cash injection after 3 months,
avoiding true bankruptcy. This keeps the world stable (no
promo ever disappears) at the cost of realism (real promotions
do go bankrupt).

**Question:** Does the supervisor want a "promo dies" path
where a Grassroots promo in CRISIS for 6+ months is removed
from the sim (roster becomes FA, titles vacated, news item
announces closure)? This would be a powerful storyline but
reduces the world's stability. If yes, specify: how many
promos must always exist (minimum 8? 10?), and does a new
promo get seeded to replace the dead one?

### Q5. Should the AI manage gym-level coaches?

**CORRECTION (per EXISTING_SYSTEMS_AUDIT):** The prior claim that
"the live DB has 300 coaches, all `gym_id`-only" is **FALSE**. The
audit found that all 300 coaches are **ORPHAN** — both `gym_id` AND
`promotion_id` are NULL — because `seed_world_phase2.py` was never
updated after v3.9.0 added the `gym_id` column. This is a seed-script
gap, not a schema gap. The fix is a one-line backfill assigning each
coach to a gym.

**Updated assumption:** The AI manages only promotion-bound staff
(scout, commentator, doctor, cutman, general_manager). Coaches are
gym-bound (the `staff` table has a `gym_id` column from v3.9.0) but
the seed script never linked them. Once the coach-gym backfill is done,
coaches are managed by the gym system, not the rival AI.

**Question remains:** Does the supervisor want the rival AI to also
hire/fire coaches at the gym level? This would require either
(a) adding a `promotion_id` column to coaches (linking them to
a promo in addition to / instead of a gym), or (b) the AI
deciding which gym each of its fighters trains at (effectively
firing the gym's coach by withdrawing fighters). Option (a) is
a MINOR schema bump; option (b) is a more invasive change to
the gym system. The brief asks for "staff hiring/firing logic"
— confirm whether gym coaches are in scope.

### Q6. How visible should the archetype system be to the player?

**Default assumption:** The `ai_archetype` column is internal
— the player doesn't see "Major League" / "Regional Power" /
etc. in the UI. The player infers a promo's behaviour from its
actions (RFL bids aggressively on stars → "they must be a big
promo").

**Question:** Does the supervisor want a UI inspector showing
each rival promo's archetype + budget state + scheduling day?
This would help the player strategize ("RFL is in SURVIVAL
state — I can outbid them for anyone right now") but also
makes the AI feel less like a character and more like a
spreadsheet. The brief's "not too complex" suggests leaving
it invisible; confirm.

### Q7. Should the AI produce show-rating-relevant cards (high
main-event marketability → higher show rating)?

**Default assumption:** Yes, indirectly. The matchmaker's
`marketability` score (§3.2) favors high-reputation, high-
momentum, champion-included main events — which the existing
`show_rating` module rewards. The AI doesn't *directly*
optimise for show rating, but its matchmaking naturally
produces decent-rated cards. This is the "plausible not
optimal" sweet spot.

**Question:** Does the supervisor want the AI to *explicitly*
target a show-rating threshold (e.g., Major League always
aims for ≥70)? This would make the AI's shows more consistent
but less varied. The default (indirect optimisation via
marketability scoring) produces more variance — some RFL
shows are blockbusters, some are flops. Confirm which.

### Q8. Should the news items for rival AI events use the voice
layer?

**Default assumption:** Yes, where the voice layer is already
invoked. The rival AI reuses `sign_free_agent`,
`schedule_next_event` (via the extracted
`_insert_event_and_card`), and writes news items via the
existing pattern (direct INSERT with `topic` + `sentiment`).
The news engine's existing subscribers (which use voice
descriptors) fire automatically on `FIGHTER_SIGNED`,
`FIGHT_RESOLVED`, etc. — so rival news already routes through
voice. The new news items (`bidding_war_lost`,
`tapping_up_rumor`, `staff` hire/fire, `promo reclassified`)
should follow CONVENTIONS §14 (no raw numbers in player-facing
text — use descriptors like "highly-rated prospect" instead
of "potential 78").

**Question:** Does the supervisor want the new news items
to use the full voice layer (descriptors + narrative family
templates) from day one, or is direct INSERT with simple
templates acceptable for v1 with voice-layer retrofit later?
The latter is faster to ship; the former is more correct per
CONVENTIONS §14.5.

---

## Appendix A — Current `rival_ai.py` Gap Analysis

For reference, here is what `src/rival_ai.py` (547 lines) does
today vs. what the user wants:

| User requirement | Current state | Gap |
|---|---|---|
| "sufficiently sophisticated to pose a fair challenge depending on size of promotion" | `ai_aggression` (0–100) controls only scheduling cadence (2/4/6 weeks). No archetype differentiation. | **Major gap.** The 4-archetype system (§2) drives every decision axis. |
| "rival promotion including staff hiring/firing logic" | **CORRECTION (per EXISTING_SYSTEMS_AUDIT):** The `staff` table EXISTS with 375 rows + 75 promo-bound staff. The `staff_contracts` table EXISTS in schema (0 rows — needs backfill). The rival AI does NOT currently call any hire/fire functions, but the infrastructure is there. | **Partial gap.** §3.5 specifies fire/hire logic that CALLS existing staff + staff_contracts tables. The AI needs to be wired to use them, not rebuild them. |
| "recruitment and budget logic" | 10% weekly chance to sign a FA, filtered by `ai_spending_style` potential floor. No budget management. | **Major gap.** §3.3 (signing with roster gaps + bidding wars) + §3.6 (3-state budget machine). |
| "rules logic of not 'tapping up' contracted fighters" | Hard rule enforced (SQL filter on `current_promotion_id IS NULL`). | **Already compliant** at the hard-rule level. §5.2 adds the soft-rule (contract-expiry interest rumors). |
| "depending on all relevant factors from show quality to finance to signing better/higher profile fighters, or searching for rookies or unproven" | Signings are random within a potential floor. No show-quality or finance factors. | **Major gap.** §3.3 (offer_score formula considers budget, prestige, path_to_title, staff quality) + §6.2 (recency bias from show rating). |
| "the user/player lives within the bigger universe as part of it world does not revolve around them" | AI acts independently of player (good). But AI doesn't act *enough* — only schedules when no event exists, signs 1 FA per 10 weeks per promo. | **Partial gap.** §3.1 (proactive scheduling on a per-promo cadence) + §3.3 (bidding wars where promos compete with each other, not just the player). |
| "rivals should be trying to put on good events/great matchmaking same as the player is with his promotion" | AI uses the player's `schedule_next_event` which has intelligent card-building. | **Already compliant** — but §3.2 introduces the separate rival matchmaker with intentional imperfection, because the existing card builder is *too* optimal. |
| "the AI can never put on flawless shows/matches/fights it must be more realistically balanced" | AI uses the player's optimal card builder — produces *flawless* main events (champ vs #1, #1 vs #2). | **Major gap.** §6 specifies 6 imperfection mechanisms. |
| "get the ai logic right but not too complex" | Current AI is *too simple* (3 functions, random matchmaking). | The new architecture is rule-based with weighted randomness — no neural net, no behaviour tree. ~2,000 lines across 7 modules. |

**Bottom line:** The current AI is functional (events resolve,
signings happen) but is **neither sophisticated nor imperfect**.
The new architecture adds the sophistication (archetypes,
bidding wars, budget states, staff management) AND the
imperfection (6 mechanisms) in a maintainable rule-based
package.

---

## Appendix B — Traceability Matrix

Every design decision in this document traces to one of the
user's caveats. If a decision can't be traced, it shouldn't be
in the doc.

| User caveat | Where addressed |
|---|---|
| "fair challenge depending on size of promotion" | §1.3, §2 (archetypes scale by size/budget/prestige), §3.6 (budget states scale behaviour by cash) |
| "staff hiring/firing logic" | §3.5 (staff_manager.py), §7.1 (staff_manager.py module) |
| "recruitment and budget logic" | §3.3 (signing_agent.py), §3.6 (budget_manager.py) |
| "rules logic of not 'tapping up' contracted fighters" | §5.1 (hard SQL rule), §5.2 (soft rule for contract-expiry rumors) |
| "depending on all relevant factors from show quality to finance to signing better/higher profile fighters, or searching for rookies or unproven" | §3.3 (offer_score considers budget, prestige, path_to_title, staff, youth, talent), §6.2 (recency bias from show rating) |
| "battling it out to sign them" | §3.3 step 4 (bidding war resolution), §5.3 (bidding war detail) |
| "the user/player lives within the bigger universe as part of it world does not revolve around them" | §1.1 (4 observable behaviours), §4.2 (round-robin scheduling days — AI acts on its own schedule, not synced to player) |
| "rivals should be trying to put on good events/great matchmaking same as the player is with his promotion" | §3.1 (event scheduling), §3.2 (matchmaking with marketability + competitiveness + storyline + development scoring) |
| "the AI can never put on flawless shows/matches/fights it must be more realistically balanced" | §6 (6 imperfection mechanisms), §3.2 (head-scratcher path), §3.4 (whimsy cuts), §3.6 (budget mistakes) |
| "get the ai logic right but not too complex" | §1.4 (rule-based + weighted randomness, no neural net, ~2,000 lines / 7 modules), §7.1 (file structure), §7.5 (4-phase implementation) |

---

## End of Document

**Next action:** Supervisor review of §8 (8 open questions) +
§7.2 (schema bump approval) + §7.5 (phasing approval). Once
approved, the implementation task can be opened against this
architecture doc as the build target.
