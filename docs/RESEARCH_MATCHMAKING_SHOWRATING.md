> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# Research: Matchmaking + Show Rating + Event Builder

**Task ID:** RESEARCH-MATCHMAKING-SHOWRATING
**Scope:** Read-only audit of every system that touches card-building, show
quality, and pre-event financial projection. No code changes.

---

## TL;DR — The Gap the User Is Complaining About

The **Build a Card** screen (`src/web/js/event_builder.js`) lets the player
pick a **venue** + set **financial levers** (ticket price, marketing spend,
PPV price, PPV toggle) — and it shows a **live P&L preview**. But the preview
has no idea which fights are on the card, because **no fights are booked
through this screen at all**. In `src/app_web.py::get_event_preview`
(line ~2814) the comment is literally:

```python
# Card-quality factor unknown at preview time (no fights
# booked yet) — assume 1.2 (a modest main event + 1
# title fight). Phase E6 will let the player re-preview
# after matchmaking.
card_draw = 1.2
```

So the projected PPV buys, gate, sponsorship, merch, net profit — every
number the player sees — is computed with a **hardcoded `card_draw = 1.2`
multiplier**, regardless of whether the player is booking a superfight card
or a developmental prelim card.

And `create_event` (line 2960) explicitly says:

```python
# Does NOT create any fights (that's the Matchmaking screen's job —
# Phase E3 is finance-only).
```

But **there is no Matchmaking screen**. The `matchmaking` nav item exists in
`src/web/js/app.js` (line 43, icon ⚔) with placeholder text *"Pick two
fighters. See the tale of the tape. Find the right matchup."* — but the
`navigate()` switch (lines 285–328) has no `matchmaking` case, so clicking
it falls through to the generic "coming soon" placeholder (lines 330–348).
There is no `src/web/js/matchmaking.js` file.

Meanwhile the **real** finance engine (`src/finance.py::_compute_broadcast_
revenue`, line 347) — which fires AFTER the event completes — computes a
real `card_draw_multiplier` from:
- main event marketability (0.5 weight)
- co-main marketability (0.2 weight)
- number of title fights (0.3 weight)
- number of rivalry fights with heat ≥ 50 (0.1 weight)

So the **preview** uses a fake `1.2`, but the **actual P&L** uses the real
formula. The preview is disconnected from the very thing the user is
building: the card. This is exactly the gap the user is asking us to close.

---

## 1. Show Rating System

### Location
`src/show_rating.py` (703 lines, well-documented).

### Subscription model
Event-bus driven (CONVENTIONS §15.4). Subscribes to `EVENT_COMPLETED`
(fired by `app._update_event_status_after_resolution` when an event
transitions to `'completed'`). Registered via `register_subscribers()`,
called once at startup.

```python
bus.subscribe(Events.EVENT_COMPLETED, _compute_show_ratings,
              name="show_rating.compute_ratings")
```

UNIQUE(event_id) constraint on `show_ratings` table makes it idempotent.

### What it rates (5 axes, each 0–100)

| Axis | Base | What feeds it |
|---|---|---|
| `fan_rating` | 30 | finishes (KO/sub/doctor/dq) ratio, title fights (+10 each, cap +20), rivalry fights heat>50 (+5 each, cap +15), avg beats/fight (cap +15) |
| `commercial_rating` | 30 | Σ fighter marketability on card (cap +30), broadcast tier bonus (ppv_global +20 / streaming +10 / tv_regional +5), attendance (cap +20) |
| `excitement_rating` | 25 | avg beats/fight (cap +25), avg damage/fight (cap +25), knockdowns × 3 (cap +15), near-finishes × 2 (cap +10) — all from `fight_beats` table |
| `quality_rating` | 25 | avg of all 25 fighter_attributes (cap +40), avg fight_iq (cap +20), clean techniques landed / 5 (cap +15) |
| `overall_rating` | weighted | fan × 0.30 + commercial × 0.20 + excitement × 0.25 + quality × 0.25, PLUS commentator bonus (+1 per 10 skill, cap +15) |

### What data it reads
- `fights` (event_id, result_type, is_title_fight)
- `fight_participants` (fighter_id per fight)
- `fight_beats` (damage_dealt, outcome='knockdown'/'near_finish'/'landed')
- `fighter_attributes` (all 25 attr columns + fight_iq)
- `fighters.marketability`
- `rivalries` (active rivalry with heat > 50)
- `venues.capacity` + `markets.heat_level` (for attendance fallback)
- `finance_transactions` (parses "N tickets × $price" if finance ran first)
- `events` JOIN `promotions` (broadcast_tier, event_date)
- `staff` JOIN `staff_contracts` JOIN `contracts` (commentator bonus, Phase E5)

### When it fires
**Only after event completion** (post-fight). It is fundamentally a
**post-hoc rating** of what happened — the fight_beats, finishes, knockdowns,
damage, attendance are all measured from the resolved fights.

### Can it be used for PRE-event projection?
**Not directly.** Three of the five axes (`fan_rating`, `excitement_rating`,
`quality_rating`) require post-fight data (finishes, beats, damage,
knockdowns) that doesn't exist before the fights happen.

BUT — and this is the key insight — **two of the five axes CAN be projected
pre-event**:

- `commercial_rating` → 100% projectable. Inputs are: fighter marketability
  (known), broadcast_tier (known), attendance (computable from venue +
  market_heat + marketing_spend). This is essentially the `card_draw_multiplier`
  formula already in `finance.py::_compute_broadcast_revenue`.
- `quality_rating` → mostly projectable. Inputs are: avg fighter attributes
  (known), avg fight_iq (known). The only unknowable part is "clean
  techniques landed" (a fight_beats outcome).

So a **pre-event show quality projection** should be its own thing —
`project_card_quality(card)` — that uses marketability + attributes + title
fights + rivalries + style clashes to give the player a "card strength"
estimate (e.g., "this card is shaping up to be a **highly entertaining
show**"). The post-event `show_rating` then becomes the **actual verdict**
the projection is measured against (closing the dopamine loop).

### Where the data lives
- Table: `show_ratings` (build_db.py:2676). Columns: rating_id, event_id,
  promotion_id, fan/commercial/excitement/quality/overall_rating (each
  CHECK 0-100), rating_description (voice phrase), created_at,
  UNIQUE(event_id).
- Voice descriptors (`_RATING_DESCRIPTIONS` in show_rating.py:122):
  90+ "an instant classic that fans will talk about for years",
  75-89 "a highly entertaining show that delivered on expectations",
  60-74 "a solid night of fights with some memorable moments",
  40-59 "a decent show that failed to produce many highlights",
  <40 "a lackluster card that left fans wanting more".
- News items written with `topic='show_rating'`, sentiment derived from
  the descriptor tier (positive/neutral/negative).

---

## 2. Matchmaking Code

### What exists

**Player-facing auto-matchmaker** — `src/services/matchmaking.py` (1493 lines):
- `schedule_next_event(conn, promotion_id, from_event_date=None, weeks_out=4)`
  is the public entry point. Builds a full card of 5-13 fights based on
  promotion size_tier:
  - **major** → 10-13 fights (main + co-main + 3 featured + 6-8 prelims)
  - **mid**   → 7-9 fights
  - **small** → 5-6 fights
- Card-build helpers (private): `_build_main_event`, `_build_co_main`,
  `_build_featured_prelim`, `_build_prelim`. Each returns a fight dict
  `{weight_class_id, fighter_a, fighter_b, card_slot, is_title_fight,
  scheduled_rounds}`.
- Selection rules:
  - Main event: champion vs #1 contender (title defense) OR #1 vs #2 for
    vacant title OR top-2 rated (non-title). 5 rounds if title fight.
  - Co-main: next-best 2-rated in a different WC for variety.
  - Featured prelims: mid-tier rated.
  - Prelims: prospects (high potential), debuts (0-0), must-win
    (loss_streak ≥ 2).
- Eligibility filters (in `_get_available_fighters_for_card`):
  same-promo, `is_active=1`, `is_retired=0`, has weight_class_id,
  no active injuries, no active suspensions, 21-day rest period.
- Defensive same-gender check (`_same_gender`) layered on top of the
  WC-based gender filter.

**Rival AI matchmaker** — `src/services/rival_ai/matchmaker.py` (568 lines):
Wraps the player-facing builders with archetype-driven imperfection:
- `build_card(conn, promotion_id, event_date, archetype, rng)` — same
  card structure, but each slot goes through `_build_slot_with_bias`:
  - `safe_pct` of the time → use the optimal builder
  - `(1-safe_pct) × 0.6` → "showcase" path (prospect vs can — high
    marketability, low competitiveness)
  - `(1-safe_pct) × 0.4` → "head-scratcher" path (random pair — boring
    stylistic clashes, squashes, rematches-too-soon)
- Main event title-fight enforcement: if `rng.roll < title_pct`, force
  `_build_main_event` (the safe path) so title fights happen at the
  archetype's expected rate.

**Rival AI event scheduler** — `src/services/rival_ai/event_scheduler.py`
(472 lines): `schedule_next_event_for_rival` — picks event_date with rival
collision avoidance (±2 days, 15% chance to ignore), budget gate
(`cash < cost × 1.2` → skip), calls `build_card`, then `_insert_event_and_
card` (shared INSERT helper that the player's `schedule_next_event` also
uses).

### How fights are currently scheduled

**Two paths, both automatic — the player has ZERO direct input:**

1. **Auto-scheduling after event completion** — when the last fight on a
   card resolves, `services/fight_engine.py:4913` calls
   `schedule_next_event(promo_id, from_event_date=event_date, weeks_out=4)`
   automatically. The player never picks opponents; the matchmaker
   picks optimal matchups for them.

2. **Player-created events via "Build a Card"** — `app_web.py::create_event`
   (line 2950) inserts an `events` row with the player's venue + levers,
   but inserts **ZERO fights** (see comment on line 2960: *"Does NOT
   create any fights — that's the Matchmaking screen's job — Phase E3
   is finance-only"*).

   This creates a **dead-end state**: a player-scheduled event with no
   fights. There's no auto-populate step (auto-scheduling only fires on
   event completion, not on event creation). So either:
   - The player must use a non-existent Matchmaking screen to add fights
     to the event, OR
   - The event sits in `status='scheduled'` forever with zero fights,
     and the player can never resolve it.

   (Worth verifying in playtesting — this might be a separate bug.)

### Is there a matchmaking screen?
**NO.** The nav item exists in `src/web/js/app.js:43`:

```js
{ id: 'matchmaking', name: 'Matchmaking', icon: '⚔' },
```

with placeholder phrase (line 70):

```js
matchmaking: { title: 'Pick two fighters.',
               body: 'See the tale of the tape. Find the right matchup.' },
```

But the `navigate()` switch in `app.js` (lines 285-328) has no
`if (screenId === 'matchmaking')` case — so it falls through to the
generic "coming soon" placeholder (lines 330-348). There is no
`src/web/js/matchmaking.js` file. There is no
`get_matchmaking_data`/`book_fight`/`add_fight_to_card` API in the
bridge (`src/web/js/bridge.js`).

### What's missing
- A **matchmaking.js** screen module with the 3-column layout from
  `GUI_PLAN.md` (Red corner | analysis | Blue corner).
- A **bridge API** to: list eligible opponents for a fighter, fetch tale-
  of-tape / matchup analysis for a pair, add a fight to a card slot,
  remove a fight from a card, fetch the current booked card.
- A **server endpoint** to write `fights` + `fight_participants` +
  `event_cards` rows for a player-booked fight.
- A way to **link matchmaking to event_builder** — either merge them
  (Build a Card screen gets a "CARD" section between venue and levers)
  or chain them (Build a Card creates the event shell → Matchmaking
  adds fights → return to Build a Card to see the projected P&L with
  real card_draw).
- A way to **re-fire the live preview** once the card is populated, so
  the player sees the financial impact of each booking decision.

---

## 3. Event Builder Current State

### What the preview calculates (`app_web.py::get_event_preview`, line 2713)

**Inputs** (params dict from JS):
- `venue_id` (player picks)
- `ticket_price` (player slider, $20-$300)
- `marketing_spend` (player slider, $0-$500K)
- `ppv_price` (player slider, $30-$80, PPV only)
- `is_ppv` (player toggle)

**Revenue computed:**
- `attendance = venue_cap × fill_rate`
- `fill_rate = clamp(0.30, 0.98, market_heat/100) + min(0.30, marketing_spend / (cap × $5))`
- `gate = attendance × ticket_price`
- `broadcast_revenue`:
  - If PPV: `ppv_buys = base_buyrate × card_draw × marketing_mult × rep_factor × trust_factor`
    - **`card_draw = 1.2` (HARDCODED — the gap)**
    - `marketing_mult = 1 + min(1.0, spend/250k)`
    - `rep_factor = 0.5 + rep/100`
    - `trust_factor = 0.5 + trust/100`
    - `ppv_revenue = ppv_buys × ppv_price × 0.6` (player split)
  - If non-PPV: flat rights fee by tier (`_FLAT_BROADCAST_RIGHTS`)
- `sponsorship = base_pool × (rep/100) × (trust/100) × 2.0`
- `merch = attendance × (avg_mkt/100) × (0.5 + trust/100) × _MERCH_PER_ATTENDEE_BASE`
  - **`avg_mkt = 55` (HARDCODED — second gap)**
- `concessions = attendance × _CONCESSIONS_PER_ATTENDEE`

**Expenses computed:**
- `fighter_purses = (avg_salary / 12) × 16 × 1.25` (assumes 8 fights × 2 fighters + 25% win bonus)
  - **`n_fights = 8` (HARDCODED — third gap)**
- `staff_salary = sum(active staff_contracts.salary) / 12`
- `venue_rental = venue_cap × cost_per_seat`
- `marketing_expense = marketing_spend`
- `insurance_medical = 5000 + n_fights × 3500`

**Net + voice:**
- `net_profit = total_revenue - total_expenses`
- `cash_after_event = current_cash + net_profit`
- `voice_phrase`: `"Your war chest can absorb this."` (safe, net ≥ 0) /
  `"You're betting the farm on this card."` (risky) /
  `"This could bankrupt you. Are you sure?"` (lethal)

### What's missing (card quality disconnect)

Three hardcoded constants that should be computed from the actual booked
card:

| Constant in `get_event_preview` | Should come from |
|---|---|
| `card_draw = 1.2` (line 2818) | `finance._compute_broadcast_revenue` already computes the real `card_draw_multiplier` from main_event_marketability + co_main_marketability + n_title_fights + n_rivalry_fights_heat_50_plus. Just needs an `event_id` with booked fights. |
| `avg_mkt = 55` (line 2839) | `finance._get_avg_card_marketability(conn, event_id)` already exists (line 487 of finance.py). Returns the avg marketability across all fighters on the card. |
| `n_fights = 8` (line 2851) | `SELECT COUNT(*) FROM fights WHERE event_id=?` — trivial. |

So the fix is structurally simple: **either pass an `event_id` to
`get_event_preview` (if the player has already created the event shell +
booked fights via the matchmaking screen) OR pass a `card_fights` array
from JS that the server uses to compute the multipliers live** (better —
lets the preview update as the player adds/removes fights, before
creating the event row).

### How finances are currently disconnected from show quality

The disconnect is in **three places**:

1. **`get_event_preview` (preview time)** uses hardcoded `card_draw=1.2`,
   `avg_mkt=55`, `n_fights=8`. So the player's preview is blind to card
   quality.
2. **`create_event` (creation time)** writes the events row with player
   levers but no fights. So the event row exists in the DB but has no
   card attached.
3. **`_process_event_finance` (post-event-completion time)** reads the
   real `card_draw_multiplier` from the actual booked fights. So the
   "real" P&L uses the real formula — but the player never saw that
   real P&L in the preview, because the preview used 1.2.

The player has no way to see "if I book Vale vs Reed as the main event,
my PPV buys projection goes from X to Y". They can only see "1.2 ×
everything else".

---

## 4. Fight Card Structure

### Schema (from `src/build_db.py`)

**`fights` table** (line 1494):
```sql
CREATE TABLE fights (
    fight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    weight_class_id INTEGER NOT NULL REFERENCES weight_classes(weight_class_id),
    bout_type TEXT NOT NULL,                              -- DEPRECATED v2.2.0
    card_slot TEXT NOT NULL DEFAULT 'main_event'
        CHECK (card_slot IN ('main_event','co_main',
                             'featured_prelim','prelim','opener')),
    is_title_fight INTEGER NOT NULL DEFAULT 0 CHECK (is_title_fight IN (0,1)),
    round_limit INTEGER NOT NULL DEFAULT 3,
    scheduled_rounds INTEGER NOT NULL DEFAULT 3,
    winner_fighter_id INTEGER REFERENCES fighters(fighter_id),
    loser_fighter_id INTEGER REFERENCES fighters(fighter_id),
    result_type TEXT,                                     -- 'ko_tko','submission',
                                                          -- 'decision','draw','dq', etc.
    finish_round INTEGER,
    finish_time TEXT,
    performance_rating INTEGER,
    fan_reaction_rating INTEGER,
    created_at TEXT, updated_at TEXT
);
```

**`fight_participants` table** (line 1537):
```sql
CREATE TABLE fight_participants (
    fight_participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    fighter_id INTEGER NOT NULL REFERENCES fighters(fighter_id),
    corner TEXT NOT NULL,                                 -- 'red' or 'blue'
    is_winner INTEGER NOT NULL DEFAULT 0 CHECK (is_winner IN (0,1)),
    created_at TEXT,
    UNIQUE (fight_id, fighter_id)
);
```

**`event_cards` table** (line 1547):
```sql
CREATE TABLE event_cards (
    event_card_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    fight_id INTEGER NOT NULL UNIQUE REFERENCES fights(fight_id) ON DELETE CASCADE,
    card_position INTEGER NOT NULL,                       -- 1-based card order
    card_tier TEXT NOT NULL,                              -- 'main_event'/'co_main'/etc
    is_main_event INTEGER NOT NULL DEFAULT 0,
    is_co_main INTEGER NOT NULL DEFAULT 0,
    created_at TEXT, updated_at TEXT
);
```

**`events` table** (line 1471):
```sql
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id, venue_id, market_id,
    event_name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,                             -- 'fight_night' etc
    status TEXT NOT NULL DEFAULT 'scheduled',             -- 'scheduled'/'in_progress'/'completed'/'cancelled'
    -- Phase E3.1 player levers:
    ticket_price INTEGER NOT NULL DEFAULT 80,             -- $20-$300
    marketing_spend INTEGER NOT NULL DEFAULT 0,           -- $0-$500k
    ppv_price INTEGER NOT NULL DEFAULT 60,                -- $30-$80
    is_ppv INTEGER NOT NULL DEFAULT 0 CHECK (is_ppv IN (0,1)),
    created_at, updated_at
);
```

### How fights are added to an event (today)

Only **one path** actually writes `fights` + `fight_participants` +
`event_cards` rows: the `_insert_event_and_card` shared helper, called
from:

1. **`services/matchmaking.schedule_next_event`** (auto-scheduling after
   event completion — player path, lines 1432-1458 of matchmaking.py).
2. **`services.rival_ai.event_scheduler._insert_event_and_card`** (rival
   AI path — extracted from the player path, same INSERT block).
3. **`src/seed_data.py`** (initial seed — creates the very first event
   per promo).

There is **no API endpoint** for a player to add a fight to an existing
event. `create_event` skips fights entirely.

### What data exists per fight
- `weight_class_id` (each fight has its own — events don't have a single WC)
- `card_slot` (the canonical position — main_event / co_main /
  featured_prelim / prelim / opener)
- `is_title_fight` (0/1)
- `bout_type` (DEPRECATED — kept for backward compat, mirrors card_slot)
- `scheduled_rounds` (5 for title fights, 3 otherwise)
- `round_limit` (default 3 — appears unused by engine; scheduled_rounds
  is the operative column)
- `result_type`, `winner_fighter_id`, `loser_fighter_id`,
  `finish_round`, `finish_time` — populated on resolution
- `performance_rating`, `fan_reaction_rating` — populated post-fight
  (currently not heavily used)

Per participant (`fight_participants`):
- `corner` ('red' or 'blue')
- `is_winner` (set on resolution)

Per card slot (`event_cards`):
- `card_position` (1-based ordering on the card)
- `card_tier` (mirrors `fights.card_slot`)
- `is_main_event` / `is_co_main` flags (denormalized for quick queries)

---

## 5. Existing Design Docs

### `docs/GUI_PLAN.md`
- §7.2 (line 778-779) lists both screens with planned layouts:

  | Screen | Purpose | Layout | Data viz |
  |---|---|---|---|
  | Event Builder ("Build a Card") | Schedule event, build card of 5-13 fights | **3-panel split (config / builder / projection)** | **Card-strength meter + buyrate projection sparkline** |
  | Matchmaking | Pick two fighters → tale-of-tape + analysis | **3-column split (Red corner / analysis / Blue corner)** | **Tale-of-tape dual StatBars + win probability bar** |

  → GUI_PLAN already calls for a "builder" panel inside Event Builder
  and a separate Matchmaking screen for pair analysis. The current
  event_builder.js ships only the "config" + "projection" panels;
  "builder" is missing. Matchmaking screen doesn't exist at all.

- §6.1 (line 587-588): Dashboard "Next Event" card should have
  "Build Card" (Primary) + "Matchmaking" (Secondary) buttons — but
  `dashboard.js::renderNextEvent` (line 276) only renders date + promo
  name + event name, **no buttons** (confirmed in
  `NAV_BUTTONS_AUDIT.md` B7: "Dashboard 'Build Card' and 'Matchmaking'
  buttons not rendered").

### `docs/NAV_BUTTONS_AUDIT.md`
- §6.1 (line 80-81): Both buttons are documented as
  "❌ NOT RENDERED. `navigate('event_builder')`" / "`navigate('matchmaking')`".
- §6.4 (line 129): "Book Next Fight button" on Fighter Profile
  → "❌ NOT IMPLEMENTED. `navigate('matchmaking', {fighter_id})` —
  needs nav params".
- §6.7 (line 171): `book_fight(fighter_a_id, fighter_b_id, event_id?)`
  → "❌ NO service function. Matchmaking screen doesn't exist yet.
  Defer until Matchmaking rebuild."

### `docs/SCREEN_DATA_AUDIT.md`
- Line 144: "Matchmaking screen must land before the Dashboard's 'Next
  Event' section is meaningful."
- Line 500: "0 scheduled events for promo 1. Player must use Matchmaking
  screen (not yet built) to schedule first event."

### `docs/ECON_STAFF_PLAN.md`
- §3.1.2 (line 283-297) — defines the **canonical `card_draw_multiplier`
  formula** that `finance.py::_compute_broadcast_revenue` implements:
  ```
  card_draw_multiplier = 1.0
    + 0.5 × (main_event_marketability / 100)
    + 0.2 × (co_main_marketability / 100)
    + 0.3 × (n_title_fights / 2)
    + 0.1 × (n_rivalry_fights_heat_50_plus / 3)
  ```
- §3.4 (line 490): "the player can lose money if they over-spend on
  marketing/venue/fighter salaries relative to **card quality**" —
  explicitly calls out card quality as the lever. But the current
  preview doesn't honor it.

### `docs/PHASE_E3_PLAN.md`
- §1 (line 58): "`get_event_summary(event_id)` — projected revenue/expense
  breakdown for the configured event (live preview as player adjusts
  levers)".
- §1 (line 63): "Step 3: Live preview — projected attendance, gate, PPV
  buys (if PPV), broadcast revenue, sponsorship, merch, concessions,
  fighter purses, staff salary, venue rental, marketing spend,
  insurance, **net profit**. Updates as player adjusts levers."
- The plan never mentions card quality in the preview — Phase E3 was
  scoped to finance-only. The deferral to "Phase E6 will let the player
  re-preview after matchmaking" is documented in code comments.

### `docs/CAGE_EMPIRE_SOUL.md`
- §"Fantasy 3 — Kingmaker": *"I create stars. Systems: promotion,
  matchmaking, hype, rankings, media."* Matchmaking IS the Kingmaker
  pillar — it's the moment the player decides who gets to be a star.
  Right now the player has no agency in this decision.

### `docs/RIVAL_AI_ARCHITECTURE.md`
- §3.2 — defines the **matchup scoring formula** the rival AI uses
  (see §6 below). Same formula could power a player-facing "matchup
  quality" indicator.

---

## 6. Matchmaking Analysis

### Existing matchup-quality / style-compatibility code

**`src/punditry.py`** (1344 lines) — the **punditry engine**, already
shipped. Has a complete matchup analysis pipeline that's currently fired
retroactively on `FIGHT_RESOLVED` but **could be called pre-fight** (the
docstring at line 30-61 explicitly notes this is a deliberate pragmatic
choice — the analysis uses pre-fight data, so it works pre-fight too).

Public API:
- `generate_matchup_analysis(conn, fighter_a_id, fighter_b_id, fight_id=None,
  event_id=None, rng=None)` → returns dict with:
  - `predicted_winner` (fighter name)
  - `predicted_method` ('KO/TKO', 'submission', 'decision', etc.)
  - `confidence_pct` (50-90)
  - `style_edge` (voice phrase: "the striker has the edge on the feet")
  - `excitement_score` (0-100)
  - `upset_risk` (voice phrase: "real upset risk", "low upset risk")
  - `analysis_text` (full prose, voice-layer, no raw numbers per §14)
- `get_matchup_analysis(conn, a_id, b_id, fight_id=None)` — read existing
- `get_recent_analyses(conn, fighter_id, limit=10)` — read recent
- `get_event_analyses(conn, event_id)` — all analyses for one event

Helpers (all reusable as-is):
- `_compute_predicted_winner` (line 738): avg of 5 key attrs
  (punch_power, cardio, fight_iq, chin, takedown_offense) + Gaussian
  noise σ=10 → winner + attribute_gap.
- `_compute_predicted_method` (line 759): based on style archetypes
  (Striker vs Striker → KO/TKO; Wrestler vs anyone → decision; etc.).
- `_compute_confidence` (line 793): attribute_gap → 50-90%.
- `_compute_excitement` (line 807): avg of aggression + punch_power +
  killer_instinct across both fighters → 0-100.
- `_compute_upset_risk` (line 832): underdog's potential + attribute_gap
  → 'high' / 'moderate' / 'low'.
- `_compute_style_edge` (line 853): picks the most lopsided attribute
  matchup + phrases it.

**`src/services/rival_ai/matchmaker.py`** — has its own (separate)
matchup scoring formula:
- `_matchup_score(fighter_a, fighter_b, conn=None)` (line 471):
  ```
  score = 35 × marketability + 30 × competitiveness
        + 20 × storyline + 15 × development_value
  ```
- `_marketability` (line 422): `(avg_rating/1500) + 0.20 if either has
  win_streak ≥ 3 + 0.10 if both have potential ≥ 70`.
- `_competitiveness` (line 447): `1 - abs(rating_A - rating_B)/400`.
- `storyline_score` (in `imperfection.py`, line 336): `0.5 if common
  opponent in last 12mo + 0.3 if active rivalry heat ≥ 40 + 0.2 if
  rematch > 90 days ago`.
- `development_value` (in `imperfection.py`, line 400): `0.5 if one
  is a prospect (potential ≥ 75, age ≤ 26) + 0.3 if the other is a
  gatekeeper (rating 1100-1300, win_pct .40-.70, age ≥ 30)`.

### What can be reused

**For the tale-of-tape / per-pair analysis view (the Matchmaking screen):**
- `punditry.generate_matchup_analysis` — gives the player everything:
  predicted winner, predicted method, confidence, style edge,
  excitement score, upset risk, full prose. Currently fires
  post-fight; can be called pre-fight with `fight_id=None` (the
  UNIQUE constraint allows NULL fight_id).
- `punditry._compute_*` helpers — drop-in for any tale-of-tape UI.
- The `matchup_analyses` table (build_db.py:2479) already has columns
  for everything.

**For the card-strength meter (the Event Builder projection):**
- `finance._compute_broadcast_revenue` already returns the real
  `card_draw_multiplier` (lines 384-390). Just needs to be called with
  a populated event_id (or refactored to accept a `card_fights` array).
- `finance._get_main_event_marketability` / `_get_co_main_marketability`
  / `_count_title_fights` / `_count_rivalry_fights_heat_50_plus` /
  `_get_avg_card_marketability` — all reusable as-is. They read from
  `fights` + `fight_participants` for a given `event_id`.
- `services.rival_ai.matchmaker._matchup_score` — could give a
  per-fight "matchup quality" score (0-100) to display alongside each
  booked fight. Could also sum/average across the card for a card-
  level quality score.

**For eligible-opponent listing (Matchmaking screen's Red/Blue corner pickers):**
- `services.matchmaking._get_available_fighters_for_card` — already
  filters by promo, active, not injured, not suspended, rest period.
  Returns a dict per fighter with rating, record, streaks, potential,
  last_fight_date. Add `marketability` + `style_archetype` to the
  SELECT and you have everything the tale-of-tape needs.

**For booking a fight (the missing service function):**
- `services.rival_ai.event_scheduler._insert_event_and_card` is the
  shared INSERT helper. It takes a pre-built `fights` list and writes
  `events` + `fights` + `fight_participants` + `event_cards` +
  `training_camps` rows. A player-facing `book_fight(event_id, a_id,
  b_id, card_slot)` would call the same INSERT block (minus the events
  INSERT — the event already exists).

---

## 7. Key Findings + Recommendations

### What code exists that can be reused

1. **`finance.py::_compute_broadcast_revenue`** (line 347) — already
   computes the real `card_draw_multiplier` from card-quality signals.
   The preview should call this instead of hardcoding `1.2`.

2. **`finance.py` helpers** — `_get_main_event_marketability`,
   `_get_co_main_marketability`, `_count_title_fights`,
   `_count_rivalry_fights_heat_50_plus`, `_get_avg_card_marketability`.
   All read from the `fights`/`fight_participants` tables for a given
   `event_id`. Reusable as-is.

3. **`punditry.py::generate_matchup_analysis`** (line 1102) — full
   matchup analysis pipeline (predicted winner, method, confidence,
   style edge, excitement, upset risk, prose). Currently fires
   post-fight; safe to call pre-fight with `fight_id=None`.

4. **`services.rival_ai.matchmaker._matchup_score`** (line 471) —
   0-100 matchup quality score (35% marketability + 30% competitiveness
   + 20% storyline + 15% development_value). Could surface as a per-
   fight "matchup quality" chip on the card builder.

5. **`services.matchmaking._get_available_fighters_for_card`** (line 448)
   — eligible-fighter query (promo + active + healthy + rested +
   gender-filtered). Ready to power the Red/Blue corner fighter
   pickers.

6. **`services.rival_ai.event_scheduler._insert_event_and_card`** (line 191)
   — INSERT helper for events + fights + participants + event_cards +
   training_camps. The matchmaking screen's "Book This Fight" button
   should call a thin wrapper around this (minus the events INSERT,
   which `create_event` already did).

7. **`show_rating.py`** (post-event) — already gives the player the
   verdict on their booking decisions. The dopamine loop is:
   **preview projection (pre) → book card → resolve fights → show_rating
   (post)**. The preview should use the same descriptor vocabulary as
   show_rating ("instant classic" / "highly entertaining" / "solid
   night" / "decent show" / "lackluster") so the player can compare
   their projection against the actual verdict.

### What's missing

1. **A matchmaking screen** (`src/web/js/matchmaking.js`) with the
   3-column layout from GUI_PLAN §7.2 (Red corner | analysis | Blue
   corner). Must support:
   - Picking 2 fighters (filtered by eligibility).
   - Showing tale-of-tape (StatBars side-by-side).
   - Showing matchup analysis (predicted winner, method, style edge,
     excitement, upset risk) — call `punditry.generate_matchup_analysis`
     pre-fight.
   - Showing matchup quality score (0-100) — call
     `services.rival_ai.matchmaker._matchup_score`.

2. **A bridge API** for the screen:
   - `get_eligible_opponents(fighter_id, weight_class_id?)` — list.
   - `get_matchup_analysis(fighter_a_id, fighter_b_id)` — call punditry.
   - `add_fight_to_card(event_id, fighter_a_id, fighter_b_id, card_slot,
     is_title_fight, scheduled_rounds)` — write fights + participants
     + event_cards rows.
   - `remove_fight_from_card(fight_id)` — delete the fight (cascades).
   - `get_event_card(event_id)` — list all booked fights with full
     detail (fighter names, records, marketability, matchup scores).

3. **Integration with the Event Builder screen** — either:
   - **Option A (merge)**: Add a "CARD" section to event_builder.js
     between the venue section and the levers section. Show the booked
     fights (initially empty) with a "+ Add Fight" button per slot
     (main event, co-main, featured prelim ×2-3, prelim ×3-8). Each
     click opens a matchmaking modal. The live preview recomputes
     whenever the card changes.
   - **Option B (chain)**: Keep event_builder.js as-is for venue +
     levers. After `create_event`, navigate to the matchmaking screen
     with `event_id` pre-filled. Player books fights there. Then a
     "Back to Preview" button returns to event_builder.js, which now
     shows the real `card_draw_multiplier` in the projection.

   Option A is cleaner UX (single screen, single source of truth) but
   requires a bigger rebuild. Option B is faster to ship (reuses
   existing event_builder.js) but splits the player's mental model
   across two screens. Either is viable — pick based on how much JS
   refactor the team wants to absorb.

4. **A pre-event card-strength projection function** — call it
   `project_card_quality(conn, card_fights)` or
   `project_show_rating(conn, event_id)`. Should return:
   - `projected_commercial_rating` (0-100) — from marketability +
     broadcast_tier + projected attendance.
   - `projected_quality_rating` (0-100) — from avg fighter attributes
     + fight_iq.
   - `projected_card_draw` (1.0-2.5 multiplier) — from the finance
     formula.
   - `voice_descriptor` — using the same 5 bands as show_rating
     ("shaping up to be an instant classic" / "shaping up to be a
     highly entertaining show" / etc.).
   - **Should NOT project fan_rating or excitement_rating** — those
     require post-fight data (finishes, beats, damage). Be honest
     about that: tell the player "the show's quality will be
     determined on fight night — but the card's commercial draw is
     [descriptor]".

### How show_quality should drive the financial preview

The current `get_event_preview` has three hardcoded constants that
should be computed from the card:

| Constant | Should be | How |
|---|---|---|
| `card_draw = 1.2` | real `card_draw_multiplier` | Either (a) call `finance._compute_broadcast_revenue` with a populated `event_id`, or (b) compute it inline from the `card_fights` array passed from JS, using the same formula (0.5 × me_mkt + 0.2 × co_mkt + 0.3 × n_title/2 + 0.1 × n_rivalry/3 + 1.0). |
| `avg_mkt = 55` | real avg marketability | `finance._get_avg_card_marketability(conn, event_id)` — already exists, just call it. |
| `n_fights = 8` | real fight count | `SELECT COUNT(*) FROM fights WHERE event_id=?` |

If the player has booked 0 fights (initial state of the Build a Card
screen), the preview should either:
- Show a clear empty state: *"Book at least one fight to see your
  projected outcome."* (replaces the current fake 1.2 multiplier), OR
- Fall back to `card_draw=1.0` (a baseline non-card) and label it as
  such: *"No fights booked yet — projection assumes a baseline card."*

### What the matchmaking experience should look like (based on existing code + design)

Per `GUI_PLAN.md` §7.2 + `NAV_BUTTONS_AUDIT.md` + the existing
`punditry.py` + `matchmaking.py` infrastructure, the ideal experience:

**Entry points** (per `NAV_BUTTONS_AUDIT.md`):
- Sidebar ⚔ Matchmaking → opens the screen fresh (no preselected fighter).
- Dashboard "Next Event" card "Build Card" / "Matchmaking" buttons
  (currently NOT RENDERED — `dashboard.js::renderNextEvent` line 276
  must add them).
- Fighter Profile "Book Next Fight" button (currently NOT IMPLEMENTED)
  → `navigate('matchmaking', {fighter_id})` — preselects that fighter
  in the Red corner.

**Screen layout** (per `GUI_PLAN.md` §7.2):
- 3-column split: Red corner | analysis | Blue corner.
- Red corner: fighter picker (filtered by eligibility — same promo,
  same WC, active, healthy, rested, same gender). Shows selected
  fighter's name, record, marketability phrase, style archetype,
  career stage, last 5 form.
- Blue corner: same, for the opponent.
- Center analysis column:
  - **Tale of the tape** (dual StatBars per `GUI_PLAN`): top 6
    attributes side-by-side, voice-described (NO raw numbers per §14).
  - **Predicted winner** + **predicted method** (from
    `punditry._compute_predicted_winner` + `_compute_predicted_method`).
  - **Confidence** as a voice phrase ("moderate", "strong") — no
    raw pct per §14.
  - **Style edge**: "the striker has the edge on the feet" (from
    `punditry._compute_style_edge`).
  - **Excitement** descriptor: "Expect fireworks" / "Technical affair"
    (from `punditry._compute_excitement`).
  - **Upset risk**: "real upset risk" / "low upset risk" (from
    `punditry._compute_upset_risk`).
  - **Matchup quality score** (0-100): from
    `services.rival_ai.matchmaker._matchup_score`. Display as a
    progress ring or chip — "🔥 Elite matchup" / "Solid fight" /
    "Passable" / "Mismatch".
  - **Style compatibility hint**: if both fighters are the same
    archetype, warn "Grappler vs Grappler — likely a slow technical
    affair" (the rival AI's "head-scratcher" path intentionally
    produces these — they're BAD for ratings).

**Booking flow**:
1. Player picks fighter A (Red corner).
2. Player picks fighter B (Blue corner). Eligibility filters
   automatically (same WC, same gender).
3. Center column populates with the tale-of-tape + analysis live.
4. Player picks a card slot (main event / co-main / featured prelim /
   prelim) from a dropdown.
5. Player clicks "Book This Fight". Calls `add_fight_to_card(event_id,
   a, b, card_slot, is_title_fight, scheduled_rounds)`.
6. The fight is written to `fights` + `fight_participants` +
   `event_cards`. A training camp is created for both fighters (via
   `_create_training_camp`).
7. The screen shows a toast: "Booked: Vale vs Reed as the main event."
8. Player returns to the Build a Card screen. The live preview now
   uses the real `card_draw_multiplier` and shows updated PPV buys /
   gate / net profit.

**Card-strength meter** (per `GUI_PLAN.md` §7.2):
- A small viz at the top of the Build a Card screen showing the
  card's projected quality on the 5-band scale
  ("instant classic" / "highly entertaining" / "solid night" /
  "decent show" / "lackluster"). Updates as the player adds/removes
  fights. Uses the same voice vocabulary as `show_rating.py` so the
  player can compare projection vs eventual verdict.

**Closing the loop**:
- After the event resolves, `show_rating.py` fires automatically and
  writes the actual rating to `show_ratings` + a `topic='show_rating'`
  news item with the verdict descriptor.
- The player sees the verdict in the news feed + the post-event
  summary. The dopamine loop closes: **projection → booking →
  resolution → verdict**.
- Future enhancement: a "Card Verdict" panel on the past-events
  screen that shows the projected vs actual rating side-by-side
  (with the voice descriptors only — no raw numbers per §14).

---

## Appendix — File Inventory

| File | Lines | Purpose |
|---|---|---|
| `src/show_rating.py` | 703 | Post-event rating engine (5 axes). Event-bus subscriber. |
| `src/services/matchmaking.py` | 1493 | Player-facing auto-matchmaker + card builder + training camps. |
| `src/services/rival_ai/matchmaker.py` | 568 | Rival AI matchmaker with bias injector + matchup score. |
| `src/services/rival_ai/event_scheduler.py` | 472 | Rival AI event scheduler with budget gate + collision avoidance. |
| `src/services/rival_ai/imperfection.py` | 461 | Storyline + development_value helpers + recency bias. |
| `src/punditry.py` | 1344 | Matchup analysis engine (predicted winner, method, style edge, excitement, upset risk). |
| `src/finance.py` | 1071 | Real P&L engine. `_compute_broadcast_revenue` has the real `card_draw_multiplier`. Helpers for main_event_marketability, co_main_marketability, n_title_fights, n_rivalry_fights, avg_card_marketability. |
| `src/app_web.py` | 3959 | Web API. `get_event_builder_data` (2535), `get_event_preview` (2713, has hardcoded `card_draw=1.2`), `create_event` (2950, writes events row only, NO fights). |
| `src/web/js/event_builder.js` | 796 | Event Builder screen. 4 sections (promo strip, venue grid, levers, preview). NO card builder. |
| `src/web/js/app.js` | 465 | Nav + routing. Has `matchmaking` nav item (line 43) but NO `if (screenId === 'matchmaking')` case → falls through to placeholder. |
| `src/web/js/bridge.js` | ~210 | JS↔Python bridge. Has `getEventBuilderData`, `getEventPreview`, `createEvent`. NO matchmaking endpoints. |
| `src/web/js/dashboard.js` | 502 | Dashboard. `renderNextEvent` (line 276) shows date + promo name + event name only — NO card listing, NO Build Card / Matchmaking buttons. |
| `src/build_db.py` | 5543 | Schema. `fights` (1494), `fight_participants` (1537), `event_cards` (1547), `fight_beats` (1890), `show_ratings` (2676), `matchup_analyses` (2479), `events` (1471, with Phase E3.1 player levers). |
| `scripts/test_show_rating.py` | 994 | Acceptance test for the show rating engine. |

---

**End of research. No code changes were made.**
