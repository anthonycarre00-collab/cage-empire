> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# REVIEW — P1 Screen Backends (Scouting / Rivalries / HoF / Gyms)

> Research notes for wiring 4 placeholder screens to their existing backends.
> Each screen has a complete simulation backend but **no API methods in
> `src/app_web.py`** and **no screen renderer in `src/web/js/`**. The nav
> items exist in `src/web/js/app.js` (`NAV_GROUPS`) but fall through to the
> placeholder renderer (`PLACEHOLDER_PHRASES`).
>
> Scope: research only. No code written. DB queried at
> `data/cage_empire.db` to confirm row counts + data shape.

---

## TL;DR — what's there and what's missing

| Screen (nav_id)        | Backend module                     | Table(s)                       | Rows in DB | Existing API methods in `app_web.py`                                     |
| ---------------------- | ---------------------------------- | ------------------------------ | ---------- | ------------------------------------------------------------------------ |
| **scouting**           | `src/scouting.py` (752 LOC)        | `scouting_reports`             | **0**      | NONE — only inline embedding in `get_fighter_profile_data`               |
| **rivalries**          | `src/rivalries.py` (1053 LOC)      | `rivalries`                    | **390**    | NONE for screen — only `get_rivalry_partners(fighter_id)` (matchmaking)  |
| **hall_of_fame**       | `src/services/hof_svc.py` (602 LOC)| `hall_of_fame`                 | **2**      | NONE — only news-topic filter `legacy` groups `hall_of_fame` news items  |
| **gyms** (training)    | `src/services/training_svc.py` + `src/tick_processor.py` (~840 LOC) | `training_camps`, `gyms` | 138 camps / 300 gyms | NONE — only `_compute_attribute_trajectory` (private helper for fighter profile) |

All 4 screens need:
1. A `get_<screen>_data(...)` API method on the `Api` class in `src/app_web.py`
2. A bridge wrapper in `src/web/js/bridge.js` (`callPython('get_<screen>_data', [...])`)
3. A screen renderer module in `src/web/js/<screen>.js` (`window.CE.<screen>.loadAndRender()`)
4. A navigate() branch in `src/web/js/app.js` (matching the pattern used by `wire.js` / `archive.js` / `titles.js`)
5. A CSS file in `src/web/css/<screen>.css`
6. `<script>` + `<link>` tags added to `src/web/index.html`

The service wrappers (`scouting_svc.py`, `rivalries_svc.py`, `hof_svc.py`, `training_svc.py`) all exist as Task 6.0 thin re-export wrappers — they are NOT used by `app_web.py` today, but are available for the UI to import from the `services.*` namespace.

---

## 1. Scouting (nav_id: `scouting`)

### 1.1 Backend files + functions

**Primary module: `src/scouting.py` (752 lines)**

Constants:
- `DEFAULT_SCOUT_ATTRS` — default scout attribute set (eye_for_talent=50, technical_analysis=50, character_reading=50, mistake_rate=20, plus bias fields and assignment tracking).
- `SCOUTING_DURATION_DAYS = 7` — ticks (sim days) a scout must observe a fighter before producing a report.
- `_STYLE_OPPOSITES` — Striker↔Grappler etc., used for bias math.

Functions (public + internal):
| Function | Purpose |
| --- | --- |
| `_load_scout_attrs(conn, scout_id)` | Read scout's specialty JSON (`staff.specialty` column) |
| `_save_scout_attrs(conn, scout_id, attrs)` | Write it back |
| **`assign_scout(conn, scout_id, target_fighter_id, promotion_id=None)`** | **Player-callable**: assigns a scout to a target fighter. Returns `True` if assigned, `False` if scout is already busy. Stores `current_assignment` + `assignment_start_date` in `staff.specialty` JSON. |
| `_check_scouting_assignments(conn, current_date)` | Tick-side: scans all scouts, fires `generate_scouting_report` after 7 days, clears assignment |
| `_build_style_echo(conn, target_fighter_id, target_style_name, rng=None)` | A11b — appends "STYLE ECHO" line if target is a regen replacement (recalls a retired legend's style) |
| **`generate_scouting_report(conn, scout_id, target_fighter_id, promotion_id, current_date)`** | **CORE**: produces the full report — applies Gaussian noise (noise_std = (100 - scout_attribute) / 4), biases (style / nationality / aggression), mistake rolls (5 mistake types), voice-layer descriptors via `voice.py`, inserts the `scouting_reports` row, writes a `news_items` row, publishes `SCOUT_REPORT_GENERATED` event |
| `mark_stale_reports(conn, fighter_id)` | Marks a fighter's existing reports `is_stale=1` (called on camp completion, fight resolution, injury) |

**Wrapper: `src/services/scouting_svc.py` (23 lines)**
```python
from scouting import *  # re-export everything
```
Pure re-export. No new code. Available for `app_web.py` to import from the `services.*` namespace if desired.

**Scout attributes (stored in `staff.specialty` JSON):**
```json
{
  "eye_for_talent": 70,            // 0-100, accuracy of potential estimates
  "technical_analysis": 65,         // 0-100, accuracy of attribute estimates
  "character_reading": 60,          // 0-100, accuracy of personality estimates
  "mistake_rate": 15,               // 0-100, chance of a significant misjudgment
  "bias_style": "Striker",          // over-rates this style, under-rates opposites
  "bias_nationality": "Brazil",     // better accuracy for fighters from this nation
  "bias_aggression": 10,            // -20 to +20, over/under-estimates aggressive fighters
  "current_assignment": 42,         // fighter_id currently being scouted (or null)
  "assignment_start_date": "2026-08-01",
  "assignment_promotion_id": 1
}
```

### 1.2 Table schema — `scouting_reports`

```sql
CREATE TABLE scouting_reports (
    scouting_report_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_id                INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    target_fighter_id       INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    promotion_id            INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    report_date             TEXT NOT NULL,
    estimated_potential     TEXT,                  -- voice-layer descriptor ("generational talent ceiling")
    estimated_ceiling       TEXT,                  -- "REALISTIC CEILING" — age/health-adjusted descriptor
    estimated_floor         TEXT,                  -- floor descriptor
    estimated_strengths     TEXT,                  -- JSON array of voice descriptors
    estimated_weaknesses    TEXT,                  -- JSON array of voice descriptors
    marketability_assessment TEXT,                 -- "strong commercial appeal" / "decent marketability" / "limited commercial appeal"
    injury_risk_assessment  TEXT,                  -- "significant injury concern" / "moderate injury risk" / "durable, low injury risk"
    contract_cost_estimate  INTEGER,               -- dollar amount (raw number — OK per §14 carve-out, contract cost is a dollar value not an attribute)
    scout_confidence        INTEGER NOT NULL DEFAULT 50 CHECK (scout_confidence BETWEEN 0 AND 100),
    is_stale                INTEGER NOT NULL DEFAULT 0 CHECK (is_stale IN (0, 1)),
    report_text             TEXT NOT NULL,         -- the full multi-line prose report
    created_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at              TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

Note: all the "estimated_*" columns store **voice-layer descriptors** (per CONVENTIONS §14 — no raw attribute numbers in player-facing text). The full prose report is in `report_text` and follows this template:
```
SCOUTING REPORT: {fighter_name}
Scout: {scout_name}
Date: {current_date}

CEILING: {pot_desc}
REALISTIC CEILING: {ceiling_desc} (accounting for age, health, and work ethic)
FLOOR: {floor_desc}

STRENGTHS: {strengths[0]}, {strengths[1]}, ...
WEAKNESSES: {weaknesses[0]}, ...

MARKETABILITY: {market_desc}
INJURY RISK: {injury_desc}
ESTIMATED CONTRACT COST: ${contract_est:,}
SCOUT CONFIDENCE: {scout_confidence}%

[STYLE ECHO: This prospect's style recalls retired fighter {legend_name} ...]   (only if target is a regen replacement)
```

### 1.3 Existing data — `scouting_reports` table

```
scouting_reports = 0 rows
```

**No reports exist in the live DB.** This means:
- No scout has ever been assigned via `assign_scout()` yet (the UI doesn't exist to drive it).
- Tick-driven report generation has fired zero times.
- `_check_scouting_assignments` runs on every `advance_day` (via `run_tick`), but with no `current_assignment` set in any scout's `staff.specialty`, there's nothing to do.
- `get_fighter_profile_data` reads `scouting_reports` to embed a "Scouting report" section on non-player fighters — currently always returns `scouting_report: None`.

There are **26 scouts** in the DB (7 free agents, 19 signed to rival promotions). Their attribute distribution:
- `eye_for_talent`:       avg 58.6, range 36–84
- `technical_analysis`:   avg 58.7, range 38–83
- `character_reading`:    avg 56.3, range 35–85
- `mistake_rate`:         avg 18.5, range 6–31
- Currently assigned to a fighter: **0/26**.

So once a player hires a scout and assigns them, the system will produce reports within 7 sim days.

### 1.4 How the player assigns scouts to fighters

**API method to build:**
```
assign_scout(scout_id, target_fighter_id) -> {ok, scout_id, target_fighter_id, eta_date}
```
- Wraps `scouting.assign_scout(conn, scout_id, target_fighter_id, promotion_id=player_promo)`.
- Returns the projected completion date (`assignment_start_date + 7 sim days`) so the UI can show "Report ETA: 2026-08-22".
- Must enforce: scout belongs to player's promotion; target is a non-roster fighter (or any active fighter?); scout is not currently assigned.
- Caller commits (use the `self.conn` + `self.conn.commit()` pattern from `hire_staff`).

**Read methods to build:**
- `get_scouting_data(filters)` — main screen payload (see §1.5 below).
- `get_scout_roster(promo_id)` — list scouts on player's promo with their specialty JSON parsed into human-readable fields. Already partly overlaps with `get_staff_market_data` (which returns scout rows for the staff market). For the player's signed scouts, a dedicated reader is cleaner.

### 1.5 Existing API methods vs. what's missing

**Exists:**
- `get_fighter_profile_data(fighter_id)` — embeds the latest scouting report for the fighter (if not on player's roster). Used by the Fighter Profile screen's "Scouting Report" card. Lines 3522-3543 in `app_web.py`.
- Staff hire flow (`get_staff_market_data` + `hire_staff`) — already supports hiring scouts (they're staff with `role_type='scout'`).

**Missing (need to build):**
- `get_scouting_data(filters)` — for the Scouting screen. Should return:
  ```json
  {
    "player_scouts": [
      {
        "staff_id": 307, "name": "Matthew Ward",
        "skill_level": 75, "salary_ask": 68000,
        "eye_for_talent": 75, "technical_analysis": 55, "character_reading": 50,
        "mistake_rate": 11, "bias_style": "Counter-Striker",
        "bias_nationality": "Nigeria", "bias_aggression": -11,
        "current_assignment": null | {
          "fighter_id": 42, "fighter_name": "...",
          "start_date": "2026-08-01", "eta_date": "2026-08-08",
          "days_remaining": 4
        }
      }, ...
    ],
    "recent_reports": [
      {
        "scouting_report_id": 12,
        "target_fighter_id": 42, "target_name": "John Vale",
        "target_promotion_id": 3, "target_promotion_name": "...",
        "scout_name": "Matthew Ward",
        "report_date": "2026-08-08",
        "estimated_potential": "high ceiling",       // voice desc
        "estimated_ceiling": "solid rotational contender",
        "estimated_floor": "career preliminary carder",
        "estimated_strengths": ["heavy hands", "solid chin"],
        "estimated_weaknesses": ["limited footwork"],
        "marketability_assessment": "decent marketability",
        "injury_risk_assessment": "moderate injury risk",
        "contract_cost_estimate": 75000,
        "scout_confidence": 67,                       // 0-100 int — only number OK per §14
        "is_stale": 0,
        "report_text": "..."                          // full prose
      }, ...
    ],
    "free_agent_scouts_count": 7
  }
  ```
- `assign_scout(scout_id, target_fighter_id)` — see §1.4.
- (Optional) `cancel_scout_assignment(scout_id)` — clears `current_assignment` mid-observation. Not strictly required but nice for UX.

### 1.6 What the UI should show

Per the existing data + the `report_text` template:

**Section A — My Scouts (signed to player's promo):**
- A table/grid of scouts with: name, skill_level, eye/tech/char reading (3 small bars or chips), mistake_rate as a "Reliability" chip, bias tags ("Style: Striker", "Nat: Brazil", "Agg: +10"), current assignment status (Idle / "Scouting John Vale — ETA 2026-08-08 (4d)").
- Click a scout → opens "Assign Scout" modal: pick a target fighter (free agents + rival-promo fighters — same filter set as Rival Roster / Free Agents screens).
- "Cancel Assignment" button on an assigned scout.

**Section B — Recent Reports (last 20, paginated):**
- A card list. Each card shows:
  - Target fighter name + portrait + their promotion badge
  - Voice-layer ceiling phrase ("high ceiling")
  - Top 1-2 strengths as chips
  - Scout name + confidence chip (Low/Med/High — derived from `_scout_confidence_phrase`)
  - Stale badge if `is_stale=1` ("Stale — fighter has changed since report")
- Click a card → modal with the full `report_text` (multi-line prose) + all 8 estimated fields as labeled rows.

**Section C — Free Agent Scouts:**
- Count + a CTA "Browse Free Agent Scouts" that navigates to Staff Market pre-filtered to role=scout. (Don't duplicate the staff market UI here.)

**Note on CONVENTIONS §14 (voice layer):** All `estimated_*` columns are already voice descriptors. The only raw numbers in the table are `contract_cost_estimate` (a dollar value — OK) and `scout_confidence` (0-100, OK per the existing `punditry` carve-out — it's the scout's own confidence rating, not a fighter attribute). Do NOT compute or display any other raw integers (potential, attribute values).

---

## 2. Bad Blood / Rivalries (nav_id: `rivalries`)

### 2.1 Backend files + functions

**Primary module: `src/rivalries.py` (1053 lines)**

Entirely event-bus-driven. Subscribes to `TICK_ADVANCED`, `FIGHT_RESOLVED`, `TITLE_CHANGED`. No inline writes to `resolve_next_fight` or `run_tick`.

Constants:
- `_MIN_BEEF_POSTS_FOR_RIVALRY = 3` — a callout pair needs 3+ social posts to graduate into a tracked rivalry.
- Heat deltas: `_HEAT_CALLOUT_POST=+5`, `_HEAT_FIGHT_BETWEEN_RIVALS=+15`, `_HEAT_TITLE_FIGHT_BETWEEN_RIVALS=+25`, `_HEAT_WEIGHT_CUT_MISS=+10`, `_HEAT_APOLOGY_POST=-15`.
- `_MAX_HEAT=100`, `_MIN_HEAT=0` (CHECK constraint on table clamps).
- `_HEAT_WEEKLY_DECAY=-1` (every 7 sim days).
- `_HEAT_DORMANCY_THRESHOLD=20` (below → `is_active=0`).
- `_CROSS_PROMO_CALLOUT_CHANCE=0.05` (5% gate for inter-promotion callouts — same weight class required).
- `_CLOSE_DECISION_MARGIN=2` (decision by ≤2 points → `rematch_hungry`).
- `VALID_RIVALRY_TYPES = ("callout", "bad_blood", "title_rivalry", "rematch_hungry", "style_clash", "disrespect", "stolen_opportunity")`.

Functions:
| Function | Purpose |
| --- | --- |
| `_fighter_full_name(conn, fighter_id)` | "John Vale" or 'John "Hammer" Vale' |
| `_fighter_age(conn, fighter_id, current_date=None)` | Age from DOB |
| `_fighter_career_stage(conn, fighter_id, ...)` | voice.describe_career_stage wrapper |
| `_canonical_pair(a_id, b_id)` | Returns (lower_id, higher_id) — table UNIQUE constraint relies on this |
| **`get_rivalry(conn, fighter_a_id, fighter_b_id)`** | Reader — returns the row for a pair (any order), or None |
| **`get_active_rivalries(conn, fighter_id)`** | Reader — all active rivalries involving a fighter, sorted by heat DESC |
| **`get_rivalry_heat(conn, fighter_a_id, fighter_b_id)`** | Reader — heat (0-100) or 0. Convenience for the fight engine. |
| `_clamp_heat(value)` | Bounds to [0,100] |
| `_build_origin_description(conn, a, b, type, narrative, ...)` | Voice-layered description ("A bad blood rivalry between X (reigning champion) and Y (top prospect). The rivalry started with...") |
| `_create_rivalry(conn, a, b, type, origin_event, narrative, initial_heat=50, ...)` | INSERT a new row |
| `_escalate_rivalry(conn, a, b, heat_delta, current_date, increment_fights, winner_id, is_draw)` | UPDATE heat + optionally fights_count / a_wins / b_wins / draws; re-activates dormant rows if heat rises above threshold |
| `_check_social_beefs(conn, event)` | `TICK_ADVANCED` subscriber — scans `social_posts` for callouts/apologies, escalates existing rivalries, spawns new `callout` rivalries for 3+ post pairs (cross-promo gate) |
| `_cross_promo_callout_allowed(conn, a_id, b_id, rng)` | A3 gate |
| `_is_weekly_tick(conn)` | True if `current_day % 7 == 0` |
| `_decay_rivalry_heat(conn, event)` | `TICK_ADVANCED` weekly subscriber — `-1` heat, dormancy below 20 |
| `_process_fight_rivalry(conn, event)` | `FIGHT_RESOLVED` subscriber — updates existing rivalry with fight result + heat, OR creates `bad_blood` (weight cut miss) / `rematch_hungry` (close decision) |
| `_process_title_rivalry(conn, event)` | `TITLE_CHANGED` subscriber — creates/upgrades `title_rivalry` on dethroning |
| `_today_from_clock(conn)` | Helper |
| **`register_subscribers()`** | Registers all 4 subscribers on the event bus. Called from `app_web.register_all_subscribers()` line 94. |

**Wrapper: `src/services/rivalries_svc.py` (25 lines)**
```python
from rivalries import *  # re-export everything
```
Pure re-export. No new code.

### 2.2 Table schema — `rivalries`

```sql
CREATE TABLE rivalries (
    rivalry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_a_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    fighter_b_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    rivalry_heat      INTEGER NOT NULL DEFAULT 50 CHECK (rivalry_heat BETWEEN 0 AND 100),
    rivalry_type      TEXT NOT NULL CHECK (rivalry_type IN (
        'callout', 'bad_blood', 'title_rivalry', 'rematch_hungry',
        'style_clash', 'disrespect', 'stolen_opportunity'
    )),
    origin_event      TEXT,                    -- e.g. 'social_media' / 'fight:42:weight_cut_miss' / 'title_change:7'
    origin_description TEXT,                   -- voice-layer prose ("A bad blood rivalry between...")
    fights_count      INTEGER NOT NULL DEFAULT 0,
    fighter_a_wins    INTEGER NOT NULL DEFAULT 0,
    fighter_b_wins    INTEGER NOT NULL DEFAULT 0,
    draws             INTEGER NOT NULL DEFAULT 0,
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_escalation_date TEXT,
    created_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at        TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fighter_a_id, fighter_b_id)
);
```

Note: `fighter_a_id` is ALWAYS the lower ID (canonical pair ordering). UI must compute "the other fighter" via `a_id + b_id - focus_fighter_id`.

### 2.3 Existing data

```
rivalries_total     = 390
rivalries_active    = 286
rivalries_dormant   = 104
```

**By type:**
| type             | count | avg_heat |
| ---------------- | ----- | -------- |
| bad_blood        | 183   | 56.8     |
| title_rivalry    | 134   | 57.4     |
| rematch_hungry   | 40    | 21.2     |
| callout          | 33    | 58.9     |

**By heat band:**
| band                | count |
| ------------------- | ----- |
| 0-19 (cold/dormant) | 104   |
| 20-39 (simmering)   | 42    |
| 40-59 (warm)        | 56    |
| 60-79 (hot)         | 96    |
| 80-100 (boiling)    | 92    |

**Sample top-heat rivalries** (heat=100):
- **Stepan Pavlov vs Leonardo Lima** — title_rivalry, 8 fights (6-2-0)
- **Alexander Ross vs Robert Bennett** — bad_blood, 6 fights (6-0-0)
- **Elena Petrov vs Rosa Muñoz** — bad_blood, 12 fights (8-4-0)
- **Aoi Watanabe vs Wilma Bengtsson** — bad_blood, 2 fights (2-0-0)
- **Jakob Klein vs Gustavo Araújo** — callout, 0 fights (0-0-0) — pure social-media beef, hasn't fought yet

**Missing types** in current data: `style_clash`, `disrespect`, `stolen_opportunity` (defined in CHECK but no row creator currently writes them — only callout/bad_blood/title_rivalry/rematch_hungry are produced by existing subscribers).

### 2.4 Existing API methods vs. what's missing

**Exists:**
- `get_rivalry_partners(fighter_id)` — returns fighters with active heat ≥ 50 against the given fighter. Used by Matchmaking V2 to show ⚔ chips next to eligible opponents. Returns `{partner_ids: [{fighter_id, heat, type, label}]}`. Lines 5536-5585.
- `_rivalry_heat(conn, a, b)` (private) — used by matchmaking + fight-night to render the rivalry chip on the VS strip.
- `_rivalry_type_label(rtype, heat, n_fights, a_wins, b_wins, draws)` (private) — produces voice labels like "Bitter Blood · 1-1" / "Title Rivalry · 0-0" / "Simmering Callout".

**Missing (need to build):**
- `get_rivalries_data(filters)` — main screen payload. Should return:
  ```json
  {
    "active_count": 286,
    "dormant_count": 104,
    "by_type": [{"type": "bad_blood", "label": "Bad Blood", "count": 183, "avg_heat": 57}, ...],
    "by_heat_band": [{"band": "80-100", "label": "Boiling", "count": 92}, ...],
    "rivalries": [
      {
        "rivalry_id": 97,
        "fighter_a": {"id": 218, "name": "Stepan Pavlov", "nickname": "The Slam", "stage": "top prospect"},
        "fighter_b": {"id": 152, "name": "Leonardo Lima", "nickname": "The Brutal Shield", "stage": "current titleholder"},
        "rivalry_heat": 100,            // 0-100 int — OK to show per §14 (it's a heat rating, not an attribute)
        "rivalry_type": "title_rivalry",
        "type_label": "Title Rivalry",
        "fights_count": 8,
        "fighter_a_wins": 6, "fighter_b_wins": 2, "draws": 0,
        "head_to_head": "6-2-0",
        "origin_description": "A title rivalry between ...",
        "last_escalation_date": "2026-09-14",
        "is_active": 1,
        "created_at": "..."
      }, ...
    ],
    "page": 1, "per_page": 20, "total": 390, "total_pages": 20,
    "filters": {"type": "all", "heat_band": "all", "search": "", "scope": "all"}
  }
  ```
- Filters to support:
  - `type` — one of the 7 VALID_RIVALRY_TYPES or "all"
  - `heat_band` — "boiling" (80-100), "hot" (60-79), "warm" (40-59), "simmering" (20-39), "cold" (0-19), "all"
  - `scope` — "all" (every rivalry), "player_promo" (only rivalries where at least one fighter is on the player's promo), "involves_my_roster" (at least one fighter is on player's roster)
  - `search` — substring match on fighter names

### 2.5 What the UI should show

**Section A — Summary strip (top):**
- 4 stat tiles: Active (286), Dormant (104), Boiling (92 — heat 80+), Title Rivalries (134)
- A small heat-band bar chart (5 segments showing the distribution)

**Section B — Filter bar:**
- Type dropdown (All / Bad Blood / Title Rivalry / Rematch Hungry / Callout / Style Clash / Disrespect / Stolen Opportunity)
- Heat band dropdown
- Scope dropdown (All rivalries / My roster / My promotion)
- Search input (fighter name)

**Section C — Rivalry cards (paginated 20/page):**
- Each card shows both fighters (portrait + name + nickname + career-stage chip), the rivalry type label as a colored badge (red for bad_blood, gold for title_rivalry, etc.), the heat as a horizontal meter (0-100), the head-to-head record ("6-2-0"), origin_description as the card body, last_escalation_date as a "Last escalated: 2026-09-14" footer.
- Sort by heat DESC by default (the existing `get_active_rivalries` reader uses this order).
- Click a card → modal with full origin_description + fight history (pull from `fight_history` where both fighter IDs match).

**Section D — Dormant tab:**
- Same card layout but for `is_active=0` rows. Show "Went dormant on {updated_at}" instead of last_escalation_date.

**Note on CONVENTIONS §14:** `rivalry_heat` (0-100 int) is OK to display — it's a relationship rating, not a fighter attribute. The `origin_description` is already voice-layered (uses `voice.describe_career_stage` for fighter stages). Do NOT display raw fighter ages, win_streaks, or attribute values on the cards.

---

## 3. Legends / Hall of Fame (nav_id: `hall_of_fame`)

### 3.1 Backend files + functions

**Primary module: `src/services/hof_svc.py` (602 lines)**

Event-bus subscriber on `FIGHTER_RETIRED`. When a fighter retires (published by `tick_processor._check_retirements`), evaluates HoF eligibility and inducts if eligible.

Constants / eligibility:
```python
# A retired fighter is eligible for HoF induction if ANY of:
#   - title_reigns >= 2           (multi-time champion)
#   - record_wins  >= 30          (longevity + success)
#   - record_wins  >= 20 AND title_reigns >= 1   (champion + longevity)
```

Functions:
| Function | Purpose |
| --- | --- |
| `_is_eligible_for_hof(conn, fighter_id)` | Returns True/False based on the criteria above |
| `_fighter_age(conn, fighter_id, current_date=None)` | Age from DOB |
| `_generate_career_summary(conn, fighter_id, rng=None)` | Uses `voice.describe_overall` to produce a 1-2 sentence summary. NO raw numbers per §14 (no raw age, no raw attribute values, no raw streak counts). Example: *"John Vale 'Hammer' is a striker, with fight-ending power in both hands and excellent chin, currently grizzled veteran."* |
| `_generate_career_highlights(conn, fighter_id)` | Bullet list of career stats (OK per §14 — career stats are NOT attribute values). Includes title reigns, title defenses, record, notable streaks, career-stage descriptor. |
| **`induce_fighter_into_hof(conn, event)`** | **Subscriber** — checks idempotency, checks eligibility, generates summary + highlights, INSERTs `hall_of_fame` row, writes a `news_items` row with `topic='hall_of_fame'` |
| **`register_subscribers()`** | Registers on `Events.FIGHTER_RETIRED`. Called from `app_web.py:111` (separate from `register_all_subscribers`, but called at the same startup point). |

### 3.2 Table schema — `hall_of_fame`

```sql
CREATE TABLE hall_of_fame (
    fighter_id          INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    inducted_date       TEXT NOT NULL,
    career_summary      TEXT NOT NULL,           -- voice-layer, digit-free per §14
    career_highlights   TEXT,                    -- bullet list (career stats OK per §14)
    created_at          TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

This is the smallest table of the 4. Just 4 columns of data. The `fighter_id` IS the primary key (one row per inductee, idempotent). To get display data, JOIN to `fighters`, `fighter_career`, `style_archetypes` for name/style/record/etc.

### 3.3 Existing data — 2 inductees

```
hall_of_fame = 2 rows
```

**Inductee 1: George Hill (fighter_id=218)**
- Inducted: 2026-12-15
- Record: 9-3-0, Title reigns: 3
- Career summary (excerpt): *"George Hill is a wrestler, with excellent takedowns and excellent top control, riding a three-fight win streak, currently..."*
- Career highlights:
  - • 3-time champion
  - • 9-3 career record
  - • Retired as late bloomer

**Inductee 2: Daisuke Endo "The Baseball Bat" (fighter_id=244)**
- Inducted: 2027-03-13
- Record: 11-16-0, Title reigns: 2
- Career summary (excerpt): *"Daisuke Endo 'The Baseball Bat' is a striker, with won't shock anyone with his hands and serviceable defense, on a four-..."*
- Career highlights:
  - • 2-time champion
  - • 11-16 career record
  - • Retired as fallen contender

Note: the seeded world (`scripts/seed_world_phase5.py`) was supposed to seed 60 HoF legends on initial build, but only 2 are present. This is either because (a) the seed never ran, (b) the seed ran but only 2 fighters met the criteria, or (c) the seed ran and was subsequently pruned. The `hof_svc` docstring mentions "the 60 seeded legends would be the only inductees forever" — implying the seeding was intended. **Worth flagging to the team**: the HoF is very sparse. Both existing inductees were inducted DURING gameplay (retired after the seed was created), not from the seed.

### 3.4 How fighters are inducted into HoF

**Automatic on retirement.** The flow is:
1. `tick_processor._check_retirements` decides a fighter retires (probability-based, on their birthday).
2. The function publishes `Events.FIGHTER_RETIRED` on the event bus with `{fighter_id, current_date}`.
3. `hof_svc.induce_fighter_into_hof(conn, event)` runs as a subscriber:
   - Checks if already in `hall_of_fame` (idempotent skip).
   - Checks eligibility (the 3 criteria above).
   - If eligible, calls `_generate_career_summary` (voice-layered) and `_generate_career_highlights` (bullet list with career stats).
   - INSERTs into `hall_of_fame`.
   - Writes a `news_items` row with `topic='hall_of_fame'`, sentiment='positive'.

There is **no player decision** in this flow — the player cannot manually induct or veto. Induction is purely based on the eligibility criteria. If a player develops a champion for 5 sim years and the fighter retires with title_reigns=2 or wins≥30 or (wins≥20 + reigns≥1), they're inducted automatically.

The player's only indirect influence is via the "develop champions" gameplay loop — sign good prospects, book them into title fights, win, repeat.

### 3.5 Existing API methods vs. what's missing

**Exists:**
- `get_wire_data(filters)` — supports `topic='legacy'` filter, which maps to news items with `topic IN ('legacy', 'hall_of_fame')`. So HoF induction news items already surface on The Wire.
- Nothing else.

**Missing (need to build):**
- `get_hof_data(filters)` — main screen payload. Should return:
  ```json
  {
    "total_inductees": 2,
    "inductees": [
      {
        "fighter_id": 218,
        "name": "George Hill",
        "nickname": null,
        "style_archetype": "Wrestler",
        "inducted_date": "2026-12-15",
        "inducted_date_display": "Dec 15, 2026",
        "career_summary": "George Hill is a wrestler, with excellent takedowns and excellent top control, riding a three-fight win streak, currently grizzled veteran.",
        "career_highlights": "• 3-time champion\n• 9-3 career record\n• Retired as late bloomer",
        "highlights_parsed": ["3-time champion", "9-3 career record", "Retired as late bloomer"],
        "record_wins": 9, "record_losses": 3, "record_draws": 0,
        "title_reigns": 3,
        "has_portrait": true,
        "portrait_uri": "data:image/png;base64,..."
      }, ...
    ],
    "page": 1, "per_page": 20, "total": 2, "total_pages": 1,
    "filters": {"search": "", "sort": "inducted_date_desc"}
  }
  ```
- Filters: `search` (name substring), `sort` (inducted_date_desc / inducted_date_asc / title_reigns_desc / wins_desc).
- (Optional) `get_hof_inductee_detail(fighter_id)` — full detail page including fight history, title reigns, biggest wins. Could just reuse `get_fighter_profile_data` with a "HoF mode" flag.

### 3.6 What the UI should show

**Section A — Header strip:**
- Total inductees count ("2 Legends Enshrined")
- Maybe a "next eligible candidate" hint (a soon-to-retire veteran with title_reigns=1 and wins≥18). Optional — could be a nice touch.

**Section B — Inductee grid (cards):**
- Each card: large portrait, name (with nickname), style archetype badge, "Inducted {month year}" date, the career_summary as a quote-styled paragraph, the career_highlights as a bullet list.
- Cards sorted by `inducted_date DESC` (most recent first).
- Click a card → modal or dedicated page showing:
  - Full career_summary
  - All highlights
  - Fight history (pull from `fight_history` — wins/losses/draws, opponents, results)
  - Title reign timeline
  - Link back to their Fighter Profile screen

**Section C — Empty state:**
- Per `PLACEHOLDER_PHRASES.hall_of_fame` in `app.js`: *"Legends never die. The fighters who shaped the sport. Their stories live here."*
- If total_inductees is 0 (after a fresh seed?), show this empty-state phrasing + a hint "Develop champions. The Hall of Fame grows as your fighters retire as legends."

**Note on CONVENTIONS §14:** Career stats (wins/losses/reigns/defenses/streaks) are OK to display in highlights — the brief's clarification explicitly carves these out. The career_summary is already voice-layered (digit-free). Do NOT display raw attribute values, raw age, or raw potential — only career stats.

---

## 4. Training Camps / Gyms (nav_id: `gyms`)

### 4.1 Backend files + functions

**Wrapper: `src/services/training_svc.py` (46 lines)**
```python
def progress_camps(conn):
    """Thin wrapper that delegates to tick_processor._check_training_camps."""
    from tick_processor import _check_training_camps
    row = conn.execute("SELECT current_date FROM simulation_clock WHERE clock_id=1").fetchone()
    current_date = row[0] if row else None
    if current_date is None:
        return
    return _check_training_camps(conn, current_date)
```
Just one function — a thin wrapper. The real logic lives in `tick_processor.py`.

**Primary logic: `src/tick_processor.py`**

Functions:
| Function | Purpose |
| --- | --- |
| **`_check_training_camps(conn, current_date)`** | Tick-side: fetches all active+uncompleted camps whose `[start_date, end_date]` window contains `current_date`. For each: branch to `_complete_training_camp` (if `current_date == end_date`) or `_progress_training_camp` (otherwise). Returns list of `(camp_id, fighter_id, action)` tuples. |
| `_progress_training_camp(conn, ...)` | Per-tick progression: fatigue +2-5 (reduced by cardio + fatigue_tolerance), morale ±0-2 (dampened by coachability, biased by gym `culture_tone`), injury_risk +2-5 (increased by `injury_proneness`, reduced by gym `medical_support`). If `injury_risk > 80`, spawn a training injury from `_TRAINING_INJURY_POOL`, force-complete the camp as 'injured'. |
| **`_complete_training_camp(conn, ...)`** | Picks 2-4 attributes from the camp_focus pool (random.sample), applies +1 to +3 base gain scaled by `gym_spec_mult * coach_mult * fatigue_factor * dim_factor * personality_factor`, caps at `effective_ceiling = potential * age_factor * health_factor * realization`. Writes `attribute_changes` JSON + `camp_result_summary` + a completion news item + publishes `CAMP_COMPLETED` event. Marks `is_active=0, is_completed=1`. |

**Camp creation: `src/services/matchmaking.py`**
| Function | Purpose |
| --- | --- |
| `_pick_camp_focus_for_archetype(conn, style_archetype_id)` | Maps style archetype → camp_focus ("Striker"→"striking", "Grappler"→"grappling", etc.) |
| **`_create_training_camp(conn, fighter_id, gym_id, event_id, fight_id, event_date, style_archetype_id)`** | Creates a training_camps row when a fight is scheduled. start_date = event_date - 14 days, end_date = event_date. |
| `_get_camp_fatigue_for_event(conn, fighter_id, event_id)` | Reader — used by `resolve_next_fight` to apply the "Fatigue > 50 = reduced starting gas" rule. |

**Constants:**
- `_CAMP_LEAD_DAYS = 14` (camp duration is 2 sim weeks).
- `_CAMP_FOCUS_ATTRS` (in `matchmaking.py:217`) — maps each `camp_focus` to its attribute pool:
  ```python
  "striking":     ["punch_power", "punch_accuracy", "kick_power",
                   "kick_accuracy", "head_movement"]
  "grappling":    ["takedown_offense", "takedown_defense", "top_control",
                   "submission_offense", "submission_defense"]
  "wrestling":    ["takedown_offense", "top_control", "cage_wrestling", "strength"]
  "conditioning": ["cardio", "recovery_rate", "durability"]
  "submission":   ["submission_offense", "submission_defense",
                   "bottom_game", "flexibility"]
  "clinch":       ["clinch_striking", "clinch_offense", "clinch_defense",
                   "cage_wrestling"]
  "general":      ["punch_power", "cardio", "fight_iq", "chin",
                   "footwork", "strength"]
  "weight_cut":   ["cardio", "recovery_rate"]
  ```
- `_ARCHETYPE_NAME_TO_CAMP_FOCUS` (in `matchmaking.py:175`):
  ```python
  "Balanced": "general", "Striker": "striking", "Grappler": "grappling",
  "Wrestler": "wrestling", "Brawler": "striking",
  "Counter-Striker": "striking", "Submission Specialist": "submission"
  ```
- `_TRAINING_INJURY_POOL` — 7 injury types (torn ACL, hamstring strain, shoulder labrum tear, rib sprain, training concussion, wrist sprain, ankle sprain).

**Important:** Camps are NOT created by player action. They're created automatically when `schedule_next_event` books a fighter onto an event. The fighter's `current_gym_id` is recorded on the camp at creation time. The player has no direct "send to camp" action today — camps happen because fights are scheduled.

### 4.2 Table schemas

**`gyms` table (15 columns):**
```sql
CREATE TABLE gyms (
    gym_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE,
    city_id            INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    nation_id          INTEGER REFERENCES nations(nation_id) ON DELETE SET NULL,
    region_id          INTEGER REFERENCES regions(region_id) ON DELETE SET NULL,
    reputation         INTEGER NOT NULL DEFAULT 50 CHECK (reputation BETWEEN 0 AND 100),
    membership_cost    REAL NOT NULL DEFAULT 0,
    facility_quality   INTEGER NOT NULL DEFAULT 50 CHECK (facility_quality BETWEEN 0 AND 100),
    medical_support    INTEGER NOT NULL DEFAULT 50 CHECK (medical_support BETWEEN 0 AND 100),
    sparring_depth     INTEGER NOT NULL DEFAULT 50 CHECK (sparring_depth BETWEEN 0 AND 100),
    development_focus  INTEGER NOT NULL DEFAULT 50 CHECK (development_focus BETWEEN 0 AND 100),
    culture_tone       TEXT NOT NULL DEFAULT 'balanced',   -- 'disciplined' | 'loose' | 'predator' | 'balanced'
    weight_cut_support INTEGER NOT NULL DEFAULT 50 CHECK (weight_cut_support BETWEEN 0 AND 100),
    created_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at         TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

**`training_camps` table (17 columns):**
```sql
CREATE TABLE training_camps (
    training_camp_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id                 INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    gym_id                     INTEGER REFERENCES gyms(gym_id) ON DELETE SET NULL,
    event_id                   INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id                   INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    start_date                 TEXT NOT NULL,
    end_date                   TEXT NOT NULL,
    camp_duration_days         INTEGER NOT NULL DEFAULT 14 CHECK (camp_duration_days >= 0),
    camp_focus                 TEXT NOT NULL DEFAULT 'general'
                               CHECK (camp_focus IN ('striking','grappling','wrestling','conditioning','submission','clinch','general','weight_cut')),
    camp_morale                INTEGER NOT NULL DEFAULT 50 CHECK (camp_morale BETWEEN 0 AND 100),
    camp_fatigue               INTEGER NOT NULL DEFAULT 0 CHECK (camp_fatigue BETWEEN 0 AND 100),
    camp_injury_risk           INTEGER NOT NULL DEFAULT 0 CHECK (camp_injury_risk BETWEEN 0 AND 100),
    camp_weight_cut_pressure   INTEGER NOT NULL DEFAULT 0 CHECK (camp_weight_cut_pressure BETWEEN 0 AND 100),
    attribute_changes          TEXT,                  -- JSON dict {attr_name: gain} on completion
    camp_result_summary        TEXT,                  -- "completed (striking focus): +2 punch power, +1 kick power"
    is_active                  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_completed               INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    created_at                 TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at                 TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

### 4.3 Existing data

```
gyms                    = 300 rows
training_camps_total    = 138 rows
training_camps_active   = 138 rows
training_camps_completed= 0 rows
```

**Gyms by culture_tone:**
| tone         | count | avg_rep | avg_facility | avg_med | avg_spar | avg_dev | avg_wc_support | avg_cost |
| ------------ | ----- | ------- | ------------ | ------- | -------- | ------- | -------------- | -------- |
| predator     | 82    | 55.2    | 58.2         | 57.4    | 62.8     | 61.6    | 50.1           | $83      |
| loose        | 81    | 54.3    | 57.9         | 56.0    | 61.2     | 62.7    | 46.7           | $79      |
| disciplined  | 77    | 59.6    | 61.6         | 57.4    | 63.5     | 64.1    | 47.3           | $86      |
| balanced     | 60    | 56.5    | 57.1         | 58.3    | 60.4     | 61.1    | 48.4           | $74      |

**Top gyms by reputation:**
- #73 Dragon Training Center (Beijing, China) — rep=96, predator, $227/mo
- #20 Apex Performance (Makhachkala, Dagestan) — rep=95, balanced, $56/mo
- #52 Midtown Fight Club (Gothenburg, Sweden) — rep=95, disciplined, $53/mo
- #60 Alpha Academy (Indianapolis, USA) — rep=95, predator, $25/mo
- #61 Asahi Dojo (Lagos, Nigeria) — rep=95, predator, $266/mo

**Gyms by fighter headcount (top 10):**
| Fighters | Gym |
| -------- | --- |
| 67       | Apex Performance |
| 51       | Granite Training Camp |
| 45       | Honor Fight Team |
| 45       | Spartan Gym & Spa |
| 44       | Forge Conditioning |
| 43       | Fight Grappling |
| 43       | Peak Athletic |
| 43       | Crown Lab |
| 43       | Rising Gym & Spa |
| 42       | Combat Gym & Spa |

**Training camps by camp_focus:**
| focus        | count | avg_fatigue | avg_morale | avg_injury_risk |
| ------------ | ----- | ----------- | ---------- | --------------- |
| striking     | 57    | 2.7         | 50.6       | 2.6             |
| general      | 34    | 0.8         | 50.2       | 0.5             |
| wrestling    | 19    | 8.9         | 51.4       | 8.1             |
| grappling    | 16    | 5.4         | 50.9       | 4.9             |
| submission   | 12    | 6.3         | 50.3       | 6.1             |

(No conditioning/clinch/weight_cut camps yet — these camp_focus values are valid but the archetype mapping doesn't produce them currently. `weight_cut` camps are reserved for Task 17, which hasn't been wired to scheduling.)

**Sample recent camps (5 most recent by start_date):**
- Camp #3041: Sean Taylor at Ronin Boxing — 2026-10-04 to 2026-10-18, focus=general, fatigue=0, morale=50, risk=0, active=1
- Camp #3042: Cristiano Cardim at Sunset Athletic — same window, focus=submission
- Camp #3043: Donald Lopez at Fusion Training Camp — same window, focus=general
- Camp #3044: David Carter at Coastal Gym & Spa — same window, focus=general
- Camp #3045: Igor Stepanov at Northside Martial Arts — same window, focus=striking

**No camps have completed yet** (`is_completed=0` for all 138 rows). This means:
- Either the sim hasn't advanced past any camp's end_date, OR
- Camps get reset/recreated on each event scheduling, OR
- The seeded camps are all freshly created and the player hasn't advanced many days.

Looking at the data: the most recent camps are dated 2026-10-04 to 2026-10-18 — and there are 138 active camps. This strongly suggests the world was seeded with all upcoming-event camps pre-created, but the player hasn't advanced the clock enough to complete any. The completion logic IS coded and IS called by `_check_training_camps` on every tick — it just hasn't fired yet in this save.

### 4.4 What a training camp does

When a fighter is scheduled to fight on event E (date D), `schedule_next_event` calls `_create_training_camp`:
1. Camp row created: `start_date = D - 14 days`, `end_date = D`, `camp_focus` = mapped from fighter's `style_archetype_id`.
2. On each tick where `start_date ≤ current_date ≤ end_date`:
   - If `current_date < end_date`: `_progress_training_camp` runs. Fatigue accrues (+2-5/tick, reduced by cardio + fatigue_tolerance). Morale fluctuates (±0-2, biased by gym `culture_tone`: disciplined/predator=+1, loose=-1, balanced=0). Injury risk accrues (+2-5/tick, increased by injury_proneness, reduced by gym medical_support). If risk > 80, a training injury is spawned (one of 7 types from `_TRAINING_INJURY_POOL`), career_health drops, the camp is force-completed as 'injured'.
3. On `current_date == end_date`: `_complete_training_camp` runs.
   - Pick 2-4 attributes from the camp_focus pool (n_attrs = 2 + (coachability + gym.development_focus) / 100, clamped [2,4]).
   - For each attribute, compute gain = `base(1-3) * gym_spec_mult * coach_mult * fatigue_factor * dim_factor * personality_factor`.
     - `gym_spec_mult` = 0.5 + (facility_quality + development_focus) / 200  → range 0.5-1.5
     - `coach_mult` = 0.5 + coachability / 100  → range 0.5-1.5
     - `fatigue_factor` = 1.0 - max(0, (fatigue - fatigue_tolerance) / 100) * 0.5  → range 0.5-1.0
     - `dim_factor` = diminishing returns as attr approaches `effective_ceiling`
     - `personality_factor` = (discipline + coachability) / 200  → range 0.0-1.0
   - Cap at `effective_ceiling = potential * age_factor * health_factor * realization` (NOT raw potential — accounts for age, health, and a per-fighter "realization" multiplier so not every prospect reaches their ceiling).
   - Write `attribute_changes` JSON (`{attr_name: gain}`) and `camp_result_summary` ("completed (striking focus): +2 punch power, +1 kick power").
   - Write a news item ("{fighter} completes training camp").
   - Mark `is_active=0, is_completed=1`.
   - Call `mark_stale_reports(fighter_id)` — scouting reports for this fighter are now stale.
   - Publish `CAMP_COMPLETED` event.

### 4.5 Existing API methods vs. what's missing

**Exists:**
- `_compute_attribute_trajectory(conn, fighter_id, sim_date)` (private, lines 659-...) — reads `training_camps.attribute_changes` for last 90 days to compute per-attribute trajectory chips ("surging/growing/stable/declining/decaying"). Used by the Fighter Profile Attributes tab. Not exposed as a public API method directly, but the data flows through `get_fighter_profile_data`.
- That's it. No gym data is exposed via any API method today.

**Missing (need to build):**
- `get_gyms_data(filters)` — main screen payload. Should return:
  ```json
  {
    "total_gyms": 300,
    "by_culture_tone": [
      {"tone": "predator", "label": "Predator", "count": 82, "avg_rep": 55},
      ...
    ],
    "gyms": [
      {
        "gym_id": 73,
        "name": "Dragon Training Center",
        "city": "Beijing", "nation": "China",
        "reputation": 96,
        "facility_quality": 90,    // 0-100 — OK to show as a gym rating
        "medical_support": 85,
        "sparring_depth": 94,
        "development_focus": 90,
        "weight_cut_support": 50,
        "culture_tone": "predator",
        "culture_tone_label": "Predator",
        "membership_cost": 226.81,
        "fighter_count": 28,           // fighters currently training here
        "active_camps_count": 3        // currently running camps
      }, ...
    ],
    "page": 1, "per_page": 20, "total": 300, "total_pages": 15,
    "filters": {"culture_tone": "all", "sort": "reputation_desc", "search": "", "scope": "all"}
  }
  ```
- `get_training_camps_data(filters)` — camps list (a tab on the same screen, or a sub-screen). Should return:
  ```json
  {
    "total_camps": 138,
    "active_camps": 138,
    "completed_camps": 0,
    "by_focus": [
      {"focus": "striking", "label": "Striking", "count": 57, "avg_fatigue": 2.7},
      ...
    ],
    "camps": [
      {
        "training_camp_id": 3041,
        "fighter": {"id": 240, "name": "Sean Taylor", "portrait_uri": "..."},
        "gym": {"id": 145, "name": "Ronin Boxing"},
        "event": {"id": 2579, "name": "Round 47", "date": "2026-10-18"},
        "start_date": "2026-10-04",
        "end_date": "2026-10-18",
        "days_remaining": 5,
        "camp_focus": "general",
        "camp_focus_label": "General",
        "camp_morale": 50,        // 0-100
        "camp_fatigue": 0,        // 0-100
        "camp_injury_risk": 0,    // 0-100
        "is_active": 1,
        "is_completed": 0,
        "attribute_changes": null,    // null until completed
        "camp_result_summary": null
      }, ...
    ],
    "page": 1, "per_page": 20, "total": 138, "total_pages": 7,
    "filters": {"focus": "all", "status": "active", "scope": "player_promo", "search": ""}
  }
  ```
- Filters for camps: `focus` (camp_focus), `status` (active/completed/injured/all), `scope` (player_promo / all / gym_id=X), `search` (fighter name).
- (Optional) `get_gym_detail(gym_id)` — full gym detail page with: gym stats, current fighters training there, current camps running, historical camp results (last 20 completed camps at this gym).

### 4.6 What the UI should show

The screen is named "Training Camps" in the nav (icon 🏋). Two logical sub-views:

**Section A — Gyms browse (default tab):**
- Summary strip: total gyms (300), avg reputation, gym culture distribution (4 chips with counts).
- Filter bar: culture_tone dropdown, sort dropdown (Reputation / Fighter count / Facility quality / Development focus), search input (gym name), scope (All / My region / My nation).
- Gym cards (20 per page): name, city+nation, reputation badge, 5 small bars for facility_quality/medical_support/sparring_depth/development_focus/weight_cut_support, culture_tone badge (color-coded: disciplined=blue, loose=yellow, predator=red, balanced=gray), membership_cost as "$X/mo", fighter_count + active_camps_count as small chips.
- Click a card → modal/page with the gym's current roster + active camps.

**Section B — Active Training Camps (second tab):**
- Summary strip: active camps (138), completed camps (0), avg fatigue, avg injury risk.
- Filter bar: camp_focus dropdown, scope dropdown (My roster / All / By gym), search (fighter name).
- Camp cards (20 per page): fighter portrait + name + promotion badge, gym name, focus badge (color-coded by focus — striking=red, grappling=blue, etc.), 3 progress meters (fatigue / morale / injury_risk), "Ends in {days_remaining} days" countdown, the linked event name + date.
- Click a card → modal with full camp detail (start/end dates, gym stats, fighter's relevant attributes for the focus, projected gains — note: actual gains only known on completion).
- Completed camps (when they exist): show the `camp_result_summary` + attribute_changes as chips ("+2 Punch Power", "+1 Kick Power").

**Section C — Completed Camps history (third tab, optional):**
- Same card layout but for `is_completed=1` rows. Show `camp_result_summary` prominently.
- Sortable by completion date, total gains, fighter name.
- Currently 0 rows in the DB, so this tab will show an empty state initially.

**Note on CONVENTIONS §14:** Gym stats (reputation, facility_quality, medical_support, sparring_depth, development_focus, weight_cut_support — all 0-100) are OK to display — they're gym ratings, not fighter attributes. Camp stats (fatigue, morale, injury_risk — 0-100) are OK — they're camp-state ratings. The `attribute_changes` JSON contains raw attribute gains (+2 punch_power) — these are deltas, not absolute values, and the existing Fighter Profile screen already displays similar trajectory chips via `_compute_attribute_trajectory`. **Verify with the team** whether displaying raw attribute deltas on the camps screen is acceptable or if they need voice descriptors ("gained noticeable power" instead of "+2 punch_power").

---

## 5. Cross-cutting notes

### 5.1 Bridge + screen wiring pattern

Every new screen needs 4 touchpoints:

**`src/web/js/bridge.js`** — add 4 wrappers (one per screen):
```javascript
getScoutingData: function (filters) { return callPython('get_scouting_data', [filters || {}]); },
assignScout: function (scoutId, targetFighterId) { return callPython('assign_scout', [Number(scoutId), Number(targetFighterId)]); },
getRivalriesData: function (page, filters) { return callPython('get_rivalries_data', [Number(page || 1), filters || {}]); },
getHofData: function (page, filters) { return callPython('get_hof_data', [Number(page || 1), filters || {}]); },
getGymsData: function (page, filters) { return callPython('get_gyms_data', [Number(page || 1), filters || {}]); },
getTrainingCampsData: function (page, filters) { return callPython('get_training_camps_data', [Number(page || 1), filters || {}]); },
```

**`src/web/js/app.js`** — add a navigate() branch per screen (lines 595-720). Pattern matches `wire.js` / `archive.js`:
```javascript
if (screenId === 'scouting' && window.CE.scouting) {
  window.CE.scouting.loadAndRender().catch(function () {});
  return;
}
if (screenId === 'rivalries' && window.CE.rivalries) {
  window.CE.rivalries.loadAndRender().catch(function () {});
  return;
}
if (screenId === 'hall_of_fame' && window.CE.hof) {
  window.CE.hof.loadAndRender().catch(function () {});
  return;
}
if (screenId === 'gyms' && window.CE.gyms) {
  window.CE.gyms.loadAndRender().catch(function () {});
  return;
}
```
Also add corresponding branches in `navigateBack()` (lines 728-810).

**`src/web/js/<screen>.js`** — new file per screen. Pattern: an IIFE exposing `window.CE.<screen> = { loadAndRender: loadAndRender, ... };`. See `src/web/js/staff_market.js` (733 lines) as the most recent exemplar.

**`src/web/index.html`** — add `<script src="js/<screen>.js"></script>` and `<link rel="stylesheet" href="css/<screen>.css">` tags.

**`src/web/css/<screen>.css`** — new file per screen.

### 5.2 API method placement in `app_web.py`

Add new `get_<screen>_data(...)` methods on the `Api` class. Recommended placement (matching existing screen ordering):
- `get_scouting_data` — after `get_staff_market_data` (line 8041), since scouts are staff.
- `get_rivalries_data` — after `get_rivalry_partners` (line 5536), since they share the rivalries table.
- `get_hof_data` — after `get_archive_data` (line 8768), since both are "history/legacy" screens.
- `get_gyms_data` + `get_training_camps_data` — after `get_titles_data` (line 10705), at the end of the screen-data methods.

Each method should follow the `get_wire_data` pattern (lines 8535-8770): try/except wrapper, filter parsing, paginated COUNT+SELECT, response dict with `items/page/per_page/total/total_pages/filters`.

### 5.3 CONVENTIONS §14 compliance — quick reference

For all 4 screens, the following are OK to display as raw integers:
- `scout_confidence` (0-100) — scout's own rating, not a fighter attribute
- `rivalry_heat` (0-100) — relationship rating
- `contract_cost_estimate` (dollar value)
- `camp_morale`, `camp_fatigue`, `camp_injury_risk` (0-100) — camp-state ratings
- All `gyms.*` 0-100 columns — gym ratings
- Career stats: `record_wins`, `record_losses`, `record_draws`, `title_reigns`, `fights_count`, `fighter_a_wins`, `fighter_b_wins`, `draws` — career stats are explicitly carved out per §14
- Dates: `report_date`, `inducted_date`, `start_date`, `end_date`, `last_escalation_date`

The following must NOT be displayed as raw integers (use voice descriptors — already in the DB):
- `estimated_potential`, `estimated_ceiling`, `estimated_floor` — voice descriptors in DB
- `estimated_strengths`, `estimated_weaknesses` — voice descriptors in DB
- `marketability_assessment`, `injury_risk_assessment` — voice descriptors in DB
- `career_summary` — voice-layered in DB
- Fighter ages, attribute values, potential, win_streak — use voice.describe_career_stage / voice.describe_attribute

The `attribute_changes` JSON in `training_camps.attribute_changes` contains raw deltas like `{"punch_power": 2}`. The existing Fighter Profile screen displays these as trajectory chips via `_compute_attribute_trajectory`. **Decision needed from the team**: either display the deltas directly on the camps screen (matching the fighter-profile precedent) or convert to voice descriptors ("noticeable power gain").

### 5.4 Performance notes

All 4 tables are small enough that no special indexing is needed for the initial implementation:
- `scouting_reports`: 0 rows (will grow slowly — ~1 row per scout assignment, max ~26 active scouts)
- `rivalries`: 390 rows (grows ~10-30/sim year as new callout/bad_blood/title rivalries spawn)
- `hall_of_fame`: 2 rows (grows ~1-5/sim year as fighters retire)
- `training_camps`: 138 active rows (churns — ~10-30 created per event schedule, ~10-30 completed per tick where end_date matches)
- `gyms`: 300 rows (static seed)

The existing queries in `app_web.py` (`get_wire_data`, `get_archive_data`) use pagination with `LIMIT ? OFFSET ?` and a separate `COUNT(*)` query — this pattern works fine for these table sizes.

For the rivalries screen specifically, the JOIN to `fighters` (twice, for fighter_a and fighter_b) and the LEFT JOIN to `fighter_career` (for career-stage computation) could become slow if rivalries grows past ~10k rows. For now, no optimization needed — but worth noting that `get_active_rivalries(fighter_id)` already has a `WHERE is_active=1` filter that the screen should reuse.

### 5.5 Open questions for the team

1. **Scouting scope** — should the player be able to scout ANY active fighter (free agents + all rival promos), or only free agents + fighters on promos the player has scouted before? The `get_fighter_profile_data` embed only shows scouting reports for "not player's fighter" — suggesting the design intent is "anyone not on your roster".

2. **HoF seeding** — the docstring says "the 60 seeded legends would be the only inductees forever" but only 2 rows exist. Was the seed never run? Should we backfill? (Out of scope for the UI wiring, but worth flagging.)

3. **Training camps scope** — should the gyms screen show ALL 300 gyms (global gym ecosystem) or only the player's promotion's "home region" gyms? The `get_staff_market_data` already filters to free-agent staff, so there's precedent for both "global" and "scoped" views. Recommend: default to "all gyms" with a scope filter.

4. **Camp creation agency** — currently camps are auto-created when a fight is scheduled. Should the player have a "send to camp" action independent of fight scheduling (e.g., to develop a prospect without booking them)? The current backend does NOT support this — it would require a new `_create_training_camp` call path. Out of scope for the UI wiring, but worth noting if the screen design assumes player-initiated camps.

5. **Rivalries scope** — should the rivalries screen default to "all rivalries" (390 rows, mostly NPC-vs-NPC) or "involves my roster" (much smaller, more relevant to the player)? Recommend: default to "involves my roster" with a toggle to "all".

6. **Style Echo** — the `_build_style_echo` function adds a "STYLE ECHO" line to scouting reports when the target is a regen replacement (a fighter who inherited a retired legend's style DNA). This is a powerful narrative feature. Confirm the Scouting screen UI renders this line distinctly (e.g., italicized, with a "MEMORY" or "ECHO" badge) rather than burying it in the report body.

---

## Appendix A — File line counts for reference

| File | Lines | Role |
| --- | --- | --- |
| `src/scouting.py` | 752 | Scouting system (scout attrs, assignment, report generation) |
| `src/services/scouting_svc.py` | 23 | Thin wrapper (re-export) |
| `src/rivalries.py` | 1053 | Rivalries system (heat, decay, escalation, event subscribers) |
| `src/services/rivalries_svc.py` | 25 | Thin wrapper (re-export) |
| `src/services/hof_svc.py` | 602 | HoF induction subscriber + summary/highlights generation |
| `src/services/training_svc.py` | 46 | Thin wrapper (`progress_camps` → `_check_training_camps`) |
| `src/tick_processor.py` | 1947 (training_camps code: lines 200-840) | Camp progression + completion logic |
| `src/services/matchmaking.py` | 1629 (camp creation: lines 175-373) | Camp focus mapping + `_create_training_camp` |
| `src/app_web.py` | 10978 | Existing API surface (NONE of the 4 screen methods exist) |

## Appendix B — Existing API methods on `Api` class (reference)

The full list of public API methods currently exposed (39 total):
```
get_clock, get_player_promotion, select_promotion, set_player_name,
get_player_name, get_player_cash, get_promotion_list, get_dashboard_data,
advance_day, advance_days, advance_to_next_event, get_random_fighter_id,
get_roster_data, get_free_agents, get_rival_promotions, get_rival_roster,
get_fighter_profile, get_fighter_decision_history, get_fighter_profile_data,
get_event_builder_data, get_event_preview, confirm_card, reopen_card,
create_event, get_calendar_data, get_date_conflicts, get_matchmaking_data,
get_rivalry_partners, book_fight, remove_fight, reorder_fights,
get_fight_analysis, get_fight_tale_of_tape, get_fight_stakes,
get_fight_fan_pulse, get_fight_compare, estimate_signing_cost,
sign_free_agent, get_bidding_alerts, counter_offer, cut_fighter,
get_staff_market_data, estimate_staff_hire_cost, hire_staff,
get_wire_data, get_archive_data, get_event_card, resolve_next_fight,
get_fight_night_data, get_event_fights, get_rankings_data, get_titles_data,
list_saves, save_game, load_game, on_close
```

**None of the 4 new screen methods exist.** The wiring work is greenfield.

---

End of review. Next actions: hand off to a full-stack developer to implement the 4 API methods + 4 screen renderers + bridge wrappers + nav branches per §5.1.
