> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# Research: Matchmaking + Event Builder Current State

> **Task ID:** RESEARCH-MATCHMAKING-CURRENT-STATE
> **Mode:** RESEARCH ONLY — no code changes.
> **Scope:** Read current matchmaking/event-builder code (frontend + backend), fighter availability logic, calendar/scheduling mechanism, and existing design docs. Map directly to the user's 7 complaints and identify gaps.
> **Cross-refs:**
> - `docs/MASTER_PLAN_MATCHMAKING.md` — the original Phase M4 plan (live-projection design)
> - `docs/RESEARCH_WMMA5_MATCHMAKING.md` — WMMA5 patterns we borrowed
> - `docs/REWARD_REVIEW.md` — reward design
> - `docs/SCREEN_DATA_AUDIT.md` — DB field availability per screen
> - `src/web/js/matchmaking.js` (1 404 lines), `src/web/css/matchmaking.css` (1 327 lines)
> - `src/web/js/event_builder.js` (807 lines), `src/web/js/app.js` (487 lines)
> - `src/services/matchmaking.py` (1 492 lines), `src/services/rival_ai/event_scheduler.py` (471 lines)
> - `src/app_web.py` (6 640 lines) — `get_matchmaking_data`, `book_fight`, `remove_fight`, `reorder_fights`, `get_fight_analysis`, `get_event_preview`, `create_event`

---

## 0. Executive Summary

The matchmaking + event-builder screens **do exist and largely work**, but every one of the user's 7 complaints is real and traceable to specific gaps in the code:

1. **Popularity/rank/titles/rivalries missing in the roster browser** — confirmed. `_fighter_brief` returns `marketability` but the JS never renders it; titles + rivalries are NOT queried at all in the roster path.
2. **Sections are not big/bold/editable** — the layout is a 3-column 300px/1fr/340px grid with each fighter row ~46px tall. It's information-dense, not "BIG and BOLD."
3. **"Easy mode" analysis is shown** — confirmed. `predicted_winner`, `predicted_method`, `confidence_word`, `excitement_phrase`, `upset_risk` are all shown. The Compare modal literally renders a "Predicted Winner" cell with the favourite's name in gold.
4. **Calculations happen LIVE, not after confirm** — confirmed by design (per MASTER_PLAN_MATCHMAKING.md §1.2 — "Live projection debounced 200ms"). There is NO "confirm card" step; each `book_fight` INSERTs to the DB immediately, and the preview re-fetches after every mutation.
5. **No way to choose event date** — confirmed. `event_builder.js` does NOT send `event_date` in the `createEvent` params; backend defaults to `current_date + 14 days`. No calendar UI exists. The "Calendar" nav item in `app.js` line 32 is a PLACEHOLDER (falls through to the "coming soon" branch in `navigate()`).
6. **Fighter availability has gaps** — the eligibility filter `_get_available_fighters_for_card` correctly excludes injured/suspended/recently-fought fighters, BUT neither that function nor `book_fight` checks whether a fighter is already booked on a DIFFERENT scheduled event (only checks THIS event). Also no training-camp conflict check and no last-minute rejection logic.
7. **No last-minute rejection logic exists** — confirmed. Searched the whole `src/` tree: zero references to `short_notice`, `last_minute`, or `willingness` in booking logic.

---

## 1. Matchmaking Screen (`src/web/js/matchmaking.js`)

### 1.1 What info is shown per fighter (roster browser — LEFT column)

`renderRosterList()` (lines 186–251) renders each fighter row. Per fighter, it shows:

| Field shown | Where it comes from (`_fighter_brief` in `app_web.py` lines 3 731–3 813) |
|---|---|
| Portrait (36×36 avatar) | `fighters.portrait_path` |
| `display_name` (name + nickname) | `fighters.first_name + nickname + last_name` |
| `weight_class_name` | `weight_classes.name` |
| `record_str` (W-L-D) | `fighter_career.record_wins/losses/draws` |
| `momentum_short` chip | `fighter_descriptors.momentum_short` (e.g., "rising", "collapsing") |
| `streak_phrase` | derived from `win_streak`/`loss_streak` (e.g., "3-fight win streak") |
| `rank_str` (e.g. "#3") — only if rank ≤ 15 | computed via `COUNT(*) FROM rankings WHERE rating > ?` |

**What is NOT shown (but IS available in `_fighter_brief`):**
- **`marketability`** — returned by `_fighter_brief` (line 3 812) but the JS never renders it. This is the fighter's POPULARITY score.
- **`stage_short`** (career phase) — returned but not rendered.
- **`has_portrait`** — returned, used for lazy-load logic, not displayed.

**What is NOT queried at all in the matchmaking roster path:**
- **Titles held** — `titles` table is not joined in `_fighter_brief`. The Tale of Tape modal DOES query `champion_of` (line ~1 116–1 127) but only via a separate `get_fight_tale_of_tape` endpoint.
- **Rivalries** — `rivalries` table not queried in roster path. Only the Fan Pulse modal surfaces `rivalry_phrase`.
- **Career health** — `career_health_desc` not queried.
- **Legacy state** — `legacy_state_short` not queried.
- **Personality** — `fighter_personality` table not queried (this is what would drive last-minute rejection).
- **Birth city / region** — only `birth_nation` (used for hometown filter), not birth city.
- **Momentum flame (-5 to +5)** — the WMMA5 "Fighter Heat" concept (per `RESEARCH_WMMA5_MATCHMAKING.md` §5.7) is not implemented.

**Filters available** (`renderRosterFilters` lines 151–184): All, Top 15, On Streak, Hometown, plus one chip per weight class.

### 1.2 Section sizes — are they too small/fiddly?

Looking at `matchmaking.css`:
- Layout: `grid-template-columns: 300px 1fr 340px` (line 29) — left column is **only 300px wide**.
- Fighter row: `padding: 8px 10px`, avatar 36×36 (lines 141–187) — each row is ~46px tall. Compact.
- Filter chip: `font-size: 10px`, `padding: 3px 8px` — tiny.
- Fighter name: `font-size: 13px` (line 195).
- Fighter meta: `font-size: 11px` (line 207).
- Rank chip: `font-size: 10px` (line 217).
- Card-builder section: corners are `min-height: 130px` (line 306); corner portraits are 56×56 (line 332); corner name `font-size: 13px` (line 348); record `font-size: 11px` (line 354).
- Booked-fight card: `padding: 10px 12px`, matchup name `font-size: 13px`, record `font-size: 10px` (lines 455–559).
- Projection column: card-draw score `font-size: 36px` (line 677) — the biggest text on the screen.

**Verdict: yes, the layout is information-dense and small.** The user's complaint that "the section needs to be BIG and BOLD and EDITABLE" is well-founded. The roster rows are mini-table rows, not bold card tiles. The fight cards in the centre column are slim panels (~80–100px tall), not big editorial cards. The 4 action buttons per fight (Compare/Tale of Tape/Stakes/Fan Pulse) are 10px-font chips — very small.

### 1.3 Add/remove/reorder UX

- **Add fight** — click a fighter in the roster → fills next empty corner slot (red first, then blue) → click "Book This Fight" button (gold, full-width). Two clicks + one button press per fight. Same-WC is enforced client-side + server-side.
- **Remove fight** — small ✕ button on the right of each fight card (`data-action="remove"`). Calls `confirm()` browser dialog → `removeFight` API.
- **Reorder** — HTML5 native drag-drop. Each fight card has `draggable="true"` and a `≡` drag-handle (line 368). On drop, the JS optimistically re-orders `state.bookedFights`, calls `bridge.reorderFights(eventId, newOrder)`, then reloads the card (because main event gets 5 rounds, others 3 — backend re-derives this).

**Verdict:** Add/remove/reorder all work, but they're small/fiddly. There's no keyboard arrow shortcut for reordering (the WMMA5 ▲▼ pattern), no auto-scroll during drag, no visual slot highlight (just a `--dragging` opacity class on the dragged card).

### 1.4 Analysis shown — is it "easy mode" or "might" advice?

`renderFightCard` (lines 344–408) shows per booked fight:
- A `ce-mm-quality-chip` with **the matchup_phrase + the numeric score** (e.g. `"strong matchup 73"`). The chip colour encodes the band (gold/green/warning/crimson).
- `analysis.predicted_method` as a chip (e.g. "Decision", "KO").
- `analysis.confidence_word` as a chip with prefix "conf:" (e.g. "conf: high").
- `analysis.style_edge` or `analysis.excitement_phrase` as an italic voice line under the chip row.

The Compare modal (`renderCompareModal` lines 926–980) renders:
- The radar chart (5-axis averaged from 25 attributes).
- "Style Edge" voice line.
- A 2×2 prediction grid with cells: **"Predicted Winner"** (gold value = favourite's name), **"Predicted Method"** (e.g. "Decision"), **"Confidence"** (e.g. "high"), **"Excitement"** (e.g. "A measured affair is likely").
- "Upset Risk" voice line (e.g. "upset alert — high risk", "low upset risk — the favorite should hold").

**Verdict: this IS "easy mode."** The engine tells the player:
- WHO will win (Predicted Winner cell with the favourite's name in gold)
- HOW they'll win (Predicted Method)
- How confident the engine is (Confidence: "high"/"moderate"/"low")
- How exciting it will be (Excitement phrase)
- How likely an upset is (Upset Risk phrase)

The only "might" framing is the `style_edge` voice line, which is descriptive (e.g., "Reed's boxing vs Vale's wrestling"). The predictions themselves are definitive, not hedged. The user's directive "should NOT give 'easy mode' analysis — only 'might' advice" requires:
- Removing or softening `predicted_winner`, `predicted_method`, `confidence_word`
- Reframing upset_risk as a "might" rather than a verdict
- Keeping `style_edge` and `excitement_phrase` (these are already voice-friendly)

The matchup_score (numeric 0–100) is ALSO shown next to the phrase in the chip — the design doc says this should NOT happen (`matchmaking.css` lines 16–17: *"Matchup score shown as a colored chip with voice phrase … NOT a bare '73/100'"*) but the JS does it anyway (`bf.matchup_score || 0).toFixed(0)` on line 390 of matchmaking.js).

### 1.5 When do calculations happen?

**Calculations happen LIVE, immediately, after every mutation.** Specifically:
- `reloadCard()` is called after every `bookFight`, `removeFight`, and `reorderFights` (lines 817, 837, 896). It calls `bridge.getMatchmakingData(eventId)` which fetches fresh booked_fights + card_preview.
- `reloadCard()` then calls `schedulePreview()` which debounces 200ms and calls `fetchPreview()` → `bridge.getEventPreview({event_id})`.
- `getEventPreview` (in `app_web.py` line 3 142) computes the **REAL** `card_draw_multiplier` via `_project_card_draw(conn, event_id)` (lines 3 289–3 313). This is the Phase M4 fix — the hardcoded `1.2` was replaced with the real formula when an event_id is provided.
- The projection panel re-renders (right column only) after each preview fetch.

So the live projection is **the design** — `MASTER_PLAN_MATCHMAKING.md` §1.2 explicitly says "Live projection debounced 200ms" and "Projection updates live as you stack the card." The user is now asking to REVERSE this — "calculations should NOT happen until card is confirmed." This contradicts the original plan.

There is **NO "confirm card" step.** Each `book_fight` call INSERTs a `fights` row immediately (line 4 077 of app_web.py). The card is built one fight at a time, persisted to DB as you go. To support a "draft → confirm" flow, the entire booking pipeline would need to be re-architected:
- Either add a `fights.is_draft = 1` column and only count non-draft fights in the card_draw
- Or stage the card entirely in JS state and POST the whole batch on confirm
- Then `confirm_card` would flip `is_draft = 0` (or INSERT all rows)

---

## 2. Event Builder Screen (`src/web/js/event_builder.js`)

### 2.1 Flow

4-section single-screen layout (per `render()` lines 437–492):

1. **🎫 STACK A CARD** — gold section header + promo strip (name + reputation/trust/tier + war chest).
2. **🏟 PICK YOUR VENUE** — capacity filter chips (all/small/mid/large) + venue-card grid + ⚡ Quick Pick button. Each venue card shows icon + name + city/nation flag + capacity + venue_type chip + rent/seat + total rental estimate.
3. **🎚 SET YOUR LEVERS** — three sliders (ticket price $20–$300, marketing $0–$500K, PPV $30–$80) + PPV toggle. Each slider has a gradient track + value bubble + min/max labels.
4. **📊 PROJECTED OUTCOME** — two-column Revenue | Expenses breakdown + a big net-profit banner (colour-coded green/yellow/red) + voice phrase + "your war chest after this card" projection.

Sticky CTA bar at the bottom: "YOUR NEXT CARD · [venue] · Ticket $X · Marketing $Y · PPV $Z · Projected Net $N" + a gold **"Stack This Card"** button.

### 2.2 Confirm step

**There is no "confirm card" step on the Event Builder.** Clicking "Stack This Card" calls `bridge.createEvent(params)` which INSERTs a single row into `events` (status='scheduled') and immediately navigates to the Matchmaking screen (line 655 of event_builder.js: `window.CE.app.navigate('matchmaking', { event_id: result.event_id })`).

The Matchmaking screen then becomes where the player builds the actual fight card — there is no "confirm the whole card" step there either (each `bookFight` is immediately persisted).

### 2.3 Date scheduling

**The player CANNOT choose the event date.** Here's the proof:

- `event_builder.js` lines 642–648 — the params sent to `createEvent` are ONLY: `venue_id`, `ticket_price`, `marketing_spend`, `ppv_price`, `is_ppv`. **No `event_date` is sent.**
- `app_web.py::create_event` lines 3 500–3 508 — the backend reads `params.get("event_date")` and falls back to `current_date + 14 days` if not provided. Since the JS never sends it, every player event is scheduled exactly +14 days from the current sim date.
- The Event Builder UI has **no date picker, no calendar widget, no date input** anywhere. Search the file: zero references to "date" input controls.

**The Rival AI does pick event dates from a window** (`event_scheduler.py::_pick_event_date` line 348 — samples uniformly from `[today + window[0], today + window[1]]` where `window` is the archetype's `event_window_days`), but the PLAYER has no such control — they get a fixed +14 days.

---

## 3. Fighter Availability (`src/services/matchmaking.py`)

### 3.1 Current filters in `_get_available_fighters_for_card` (lines 448–572)

The SQL (lines 493–514) applies these filters:

| Filter | Where in SQL | Status |
|---|---|---|
| Same promotion | `f.current_promotion_id = ?` | ✅ |
| Active | `f.is_active = 1` | ✅ |
| Not retired | `f.is_retired = 0` | ✅ |
| Has a weight class | `f.weight_class_id IS NOT NULL` | ✅ |
| Not currently injured | `f.fighter_id NOT IN (SELECT fighter_id FROM injuries WHERE is_active = 1)` | ✅ |
| Not currently suspended | `f.fighter_id NOT IN (SELECT fighter_id FROM suspensions WHERE is_active = 1)` | ✅ |
| Rest period (21 days default) | Python-side check using `rankings.last_fight_date` vs `before_date` param | ✅ (but see §3.2 caveat) |

**Live DB state** (verified via direct sqlite query):
- 4 493 total fighters; 75 in player promo; 74 active.
- 300 active injuries, 13 active suspensions — these filters DO fire.
- 1 500 training_camps rows exist (across all promotions).
- 414 of 1 034 ranked fighters have NULL `last_fight_date` — these fighters are LENIENTLY included (rest-period check is skipped on parse failure, line 554: `pass  # bad date — be lenient and include the fighter`).

### 3.2 Missing checks (the gaps the user is hitting)

**GAP 1 — Not checking if fighter is booked on ANOTHER scheduled event.**

The eligibility filter only excludes fighters booked on THIS event (in `get_matchmaking_data` lines 3 681–3 688):
```python
booked_ids_row = conn.execute(
    "SELECT DISTINCT fp.fighter_id "
    "FROM fights f "
    "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
    "WHERE f.event_id=?",   # <-- only THIS event
    (eid,),
).fetchall()
```

There is no `JOIN events e ON e.event_id=f.event_id WHERE e.status='scheduled'` to exclude fighters already booked on ANY upcoming event. The `SCREEN_DATA_AUDIT.md` §"Open Issues" line 459 explicitly flagged this gap: *"No 'is_booked' flag. Book Next Fight button needs to know if fighter is already on an upcoming card."*

**Currently the player promo has 0 scheduled events** so the bug doesn't fire today — but the moment the player stacks a second card while the first is still scheduled, they'll be able to double-book fighters across events.

**GAP 2 — `book_fight` does NOT re-validate eligibility.**

Looking at `book_fight` (lines 3 963–4 171), the server-side checks are:
- Both fighters exist + on player's promo ✅
- Both active + not retired ✅
- Same gender ✅
- Same weight class ✅
- Neither already booked on THIS card ✅ (lines 4 040–4 049)
- Event status is 'scheduled' ✅

**Not checked in `book_fight`:**
- ❌ Injuries (a fighter could be injured after the roster loaded and still be bookable)
- ❌ Suspensions (same race condition)
- ❌ Rest period (no check at booking time)
- ❌ Booked on ANOTHER scheduled event
- ❌ Training camp conflicts (e.g., fighter already in a camp for a different fight)
- ❌ Last-minute rejection (no time-between-booking-and-event check)

**GAP 3 — No "training camp" availability check.**

The system creates training camps AFTER booking (in `matchmaking.py` line 1 478 and `event_scheduler.py` line 295), but never CHECKS for camp conflicts BEFORE booking. If a fighter is already in an active training camp for a different event, the booking still succeeds — the new camp is created on top of the old one.

**GAP 4 — No last-minute rejection based on personality.**

Searched the whole `src/` tree: zero references to `short_notice`, `last_minute`, or `willingness` in booking logic. The only `willingness` mention is in `reputation.py:931` and it's about an unrelated narrative phrase. There is no `fighter_personality`-driven check that would cause a fighter to refuse a short-notice booking.

This is a significant missing feature per WMMA5 research (`RESEARCH_WMMA5_MATCHMAKING.md` §1.9 — WMMA5 has dev-journal #152 "Short Notice Search" and dev-journal #160 "Replacement Offers"). Our system has neither.

**GAP 5 — Rest-period check is fragile.**

The 21-day rest period relies on `rankings.last_fight_date` being populated. With 414/1 034 ranked fighters having NULL `last_fight_date`, the check silently passes (line 554) and includes them. If `last_fight_date` is ever stale (e.g., not updated after a fight resolves), fighters who just fought could appear eligible.

### 3.3 What's working

- Injuries are correctly excluded (300 active injuries in DB → all those fighters hidden from roster).
- Suspensions are correctly excluded (13 active suspensions → all hidden).
- Active + non-retired filter works.
- Same-promotion filter works.
- Same-WC enforced both client-side (`onFighterClick` line 782) and server-side (`book_fight` line 4 035).

---

## 4. Backend API (`src/app_web.py`)

### 4.1 What data `get_matchmaking_data` returns per fighter

`_fighter_brief` (lines 3 731–3 813) returns per fighter:

| Field | Source | Shown in JS? |
|---|---|---|
| `fighter_id` | `fighters.fighter_id` | (used for clicks) |
| `name` | `first_name + last_name` | ✅ (in modal fallback) |
| `nickname` | `fighters.nickname` | ❌ NOT shown in roster row |
| `display_name` | `first_name + nickname + last_name` | ✅ (in roster row + corner slot) |
| `weight_class_id` | `fighters.weight_class_id` | (used for same-WC check) |
| `weight_class_name` | `weight_classes.name` | ✅ |
| `gender` | `fighters.gender` | (used for same-gender check) |
| `record_str` | `fighter_career W/L/D` | ✅ |
| `wins`, `losses`, `draws` | `fighter_career` | ❌ (record_str is shown instead) |
| `win_streak`, `loss_streak` | `fighter_career` | ❌ (only used to derive streak_phrase) |
| `stage_short` | `fighter_descriptors.career_phase_short` | ❌ NOT rendered |
| `momentum_short` | `fighter_descriptors.momentum_short` | ✅ (as a chip) |
| `streak_phrase` | derived | ✅ |
| `rank_str` | computed (`#1`–`#15` or `Unranked`) | ✅ (only if ranked) |
| `has_portrait` | `fighters.portrait_path` | (used for lazy-load) |
| `height_cm`, `reach_cm`, `stance` | `fighters` table | ❌ NOT in roster (only Tale of Tape modal) |
| **`marketability`** | `fighters.marketability` | ❌ **NOT rendered** — the comment says "internal — NEVER shown raw" but no voice phrase replaces it |

**Not queried at all** (would need a new SQL JOIN):
- Titles held (`titles` table — only fetched in `get_fight_tale_of_tape`)
- Rivalries (`rivalries` table — only fetched in `get_fight_fan_pulse`)
- Career health (`fighter_descriptors.career_health_desc`)
- Legacy state (`fighter_descriptors.legacy_state_short`)
- Overall descriptor (`fighter_descriptors.overall_desc`)
- Pressure (`fighter_descriptors.pressure_short`)
- Personality (`fighter_personality` table)
- Birth city / region (only `birth_nation` for hometown filter)
- Recent fight form (`fight_history` — only in Tale of Tape modal)
- Camp status / next-scheduled-fight date

### 4.2 Analysis approach — `get_fight_analysis` (lines 4 366–4 474)

Calls punditry.py functions to compute on the fly (no DB write):
- `_compute_predicted_winner` → returns `(favorite_id, underdog_id, gap)`
- `_compute_predicted_method` → "Decision" / "KO" / "Submission" etc.
- `_compute_confidence` → 50–90 integer (definitive)
- `_compute_style_edge` → natural language phrase (good — "might" framed)
- `_compute_excitement` → 0–100 integer
- `_compute_upset_risk` → "high" / "moderate" / "low"

Returns dict with all of these PLUS `_confidence_word` (e.g. "high"), `_excitement_phrase` (e.g. "A measured affair is likely"), `_upset_phrase` (e.g. "upset alert — high risk"). The `predicted_winner` is rendered as the favourite's full name.

**Verdict: this IS easy mode.** The punditry engine definitively predicts the winner, the method, and the confidence. To convert to "might" advice, the punditry functions would need to be re-voiced (e.g., predicted_winner → "either could take it" or "leans [name]"; confidence_word → "could go either way" / "looks like [name]'s fight to lose").

### 4.3 Preview calculation timing — `get_event_preview` (lines 3 142–3 464)

The preview is **fully live**. The JS calls it:
- 200ms after any lever change in Event Builder (`event_builder.js:fetchPreview` line 502)
- 200ms after any book/remove/reorder in Matchmaking (`matchmaking.js:schedulePreview` line 592)

The backend (lines 3 289–3 313) detects whether `event_id` is in params:
- If yes (Matchmaking path) → uses `_project_card_draw(conn, event_id)` to compute the REAL `card_draw_multiplier` from booked fights
- If no (Event Builder pre-event path) → falls back to `card_draw = 1.2` (hardcoded — the original Phase E3 behavior)

The preview then runs the FULL finance formula: fill_rate, gate, broadcast/PPV revenue, sponsorship, merch, concessions, fighter purses (estimated), staff salary, venue rental, marketing, insurance, total revenue, total expenses, net profit, cash_after_event, voice_kind (`safe` / `risky` / `lethal`), voice_phrase. Plus card_draw_score (0–100), card_draw_phrase, card_health_flags.

So the projection is a **complete P&L** — not a "might happen" estimate, but a deterministic computation based on the current state. Per the user's directive ("calculations should NOT happen until card is confirmed"), this whole live-preview design would need to be hidden until the player clicks a "Confirm Card" button.

---

## 5. Calendar / Scheduling

### 5.1 What exists

**The Calendar nav item exists but is a PLACEHOLDER.**
- `app.js` line 32: `{ id: 'schedule', name: 'Calendar', icon: '📅' }` in the HOME nav group.
- `app.js::navigate()` (lines 285–345) has explicit `if` branches for `dashboard`, `roster`, `free_agents`, `rival_promotions`, `event_builder`, `matchmaking`, `staff_market`, `fighter_profile`. There is **NO `if (screenId === 'schedule')` branch** — it falls through to the generic placeholder renderer (lines 347–365).
- The placeholder phrase (line 67): `schedule: { title: 'The calendar is clear.', body: 'Build a card. Give the fans something to remember.' }`.

**There is NO calendar/schedule API method in `app_web.py`.** Searched for `get_calendar`, `get_schedule`, `get_upcoming_events`, `list_events` — zero matches. The closest existing methods are `get_event_builder_data`, `get_matchmaking_data`, `get_event_preview`, `create_event`.

**There is NO calendar widget in `bridge.js`.** Searched for `calendar`, `Schedule`, `getUpcoming` — zero matches.

### 5.2 How event_date is set today

- **Player events**: `create_event` defaults to `current_date + 14 days` (line 3 508 of app_web.py). The player has NO control.
- **Rival AI events**: `event_scheduler.py::_pick_event_date` (line 348) samples uniformly from `[today + window[0], today + window[1]]` where `window` is the archetype's `event_window_days` (per-archetype, e.g., a "regional" archetype might be 7–21 days, a "major" archetype 21–56 days). It also does rival collision avoidance — re-samples up to 3 times if another promo has a scheduled event within ±2 days, with a 15% chance to ignore collision (counter-programming whim).

### 5.3 What's missing

To deliver "choose WHEN to schedule an event":

1. **Calendar UI** — a month-grid calendar showing:
   - All scheduled events (player + rival promos) as date chips
   - Highlighted "available" dates (e.g., weekends, dates outside rival collision window)
   - Click a date → set as event_date
2. **Backend `get_calendar_data` API** — return all scheduled events in a date range, plus sim clock info, plus per-date availability hints (collision warnings).
3. **`create_event` to accept `event_date` from the player** — already supported in the backend (line 3 503), just needs the JS to send it.
4. **Lead-time enforcement** — WMMA5 enforces 1-month minimum lead (2 weeks in the first week of the game) per `RESEARCH_WMMA5_MATCHMAKING.md` §2.1. Our system has no lead-time check.
5. **Multi-event scheduling** — the player should be able to schedule several events at once (WMMA5 allows this). Our system currently has no UI for it.

---

## 6. Key Gaps + Recommendations (mapped to user's 7 complaints)

### 6.1 Mapping complaints → gaps

| # | User complaint | Confirmed? | Root cause |
|---|---|---|---|
| 1 | Can't see fighter popularity, rank, titles, or rivalries when creating matchups | ✅ Confirmed | `_fighter_brief` returns `marketability` but JS doesn't render it. Titles + rivalries not queried at all in roster path. Rank IS shown but only as `#1–#15` (no "Unranked" display). |
| 2 | Section needs to be BIG, BOLD, EDITABLE with add/remove/reorder | ✅ Confirmed | Layout is `300px / 1fr / 340px` grid with 36×36 avatars, 13px fighter names, 10px filter chips, 10px action-button chips. Compact, not bold. |
| 3 | Should NOT give "easy mode" analysis — only "might" advice | ✅ Confirmed | `predicted_winner` (gold cell with favourite's name), `predicted_method`, `confidence_word`, `upset_risk` are all definitive. Only `style_edge` is "might" framed. |
| 4 | Calculations should NOT happen until card is confirmed | ✅ Confirmed (by design) | `MASTER_PLAN_MATCHMAKING.md` explicitly designed live preview. No "confirm card" step exists. Each `book_fight` INSERTs immediately. |
| 5 | No way to choose WHEN to schedule an event (no calendar) | ✅ Confirmed | Calendar nav item is a placeholder. `event_builder.js` never sends `event_date`. `create_event` defaults to +14 days. |
| 6 | Fighter availability may not be working | ⚠️ Partially | Injuries/suspensions filters DO work (300/13 active exclusions). But no check for booked-on-OTHER-event, no camp conflict check, rest-period check is fragile (NULL `last_fight_date` → lenient inclusion). |
| 7 | Last-minute fights should be rejected by many fighters depending on personality | ✅ Confirmed missing | Zero references to `short_notice`, `last_minute`, or `willingness` in booking logic. No `fighter_personality`-driven rejection. |

### 6.2 Priority order for fixing

**P0 — Block the "matchmaking is the heartbeat" loop:**

1. **Fix fighter availability gaps** (#6):
   - Add `JOIN events e ON e.event_id=f.event_id WHERE e.status='scheduled'` to `_get_available_fighters_for_card` so fighters booked on ANY scheduled event are excluded.
   - Re-validate injuries + suspensions + rest period + already-booked in `book_fight` itself (not just the roster query) — closes the race condition.
   - Backfill `rankings.last_fight_date` for the 414 NULL rows + audit the writer that's supposed to update it post-fight.

2. **Surface popularity + titles + rivalries in roster row** (#1):
   - Render `marketability` as a voice phrase ("Mid Regional", "Cult Hero", "Household Name") — same vocabulary as WMMA5.
   - Add `titles_held` chip per fighter (query `titles WHERE current_champion_fighter_id = ? AND is_vacant = 0`).
   - Add `rivalry_count` chip per fighter (query `rivalries WHERE fighter_a_id = ? OR fighter_b_id = ?`).
   - Show `Unranked` (instead of nothing) for fighters with rank_str = "Unranked".

**P1 — Fix the UX of the screen itself:**

3. **Make the card builder BIG and BOLD** (#2):
   - Increase fighter-row height from ~46px to ~72px, avatar from 36px to 56px.
   - Bigger fighter name (16–18px), bigger rank chip.
   - Fight cards in the centre column should be ~140–180px tall (currently ~80–100px) — show portraits + bold names.
   - Action buttons (Compare/Tape/Stakes/Pulse) as icon-buttons with tooltips, not 10px text chips.
   - Add explicit ▲▼ arrow buttons alongside drag-drop for accessibility + speed.

4. **Convert "easy mode" predictions to "might" advice** (#3):
   - Remove the "Predicted Winner" cell from the Compare modal.
   - Reframe `predicted_method` as "Likely Method: Decision or KO" (always include 2 options).
   - Replace `confidence_word` with a "Lean" chip: "leans Red" / "leans Blue" / "toss-up".
   - Replace `upset_risk` with "X-factor" voice line: "Vale's submission game could flip this".
   - KEEP `style_edge` and `excitement_phrase` (already voice-friendly).
   - REMOVE the numeric matchup_score from the chip — show only the phrase (the design doc says this; the JS violates it).

**P2 — Add the missing player controls:**

5. **Build the Calendar screen** (#5):
   - New `get_calendar_data(start_date, end_date)` API returning all scheduled events + sim clock + per-date availability hints.
   - New `src/web/js/calendar.js` rendering a month grid with event chips.
   - Wire the existing "Calendar" nav item (`app.js` line 32) into `navigate()` so it's no longer a placeholder.
   - Add a date picker to `event_builder.js` — when the player clicks "Stack This Card", they first pick a date (or use a default).
   - Pass `event_date` in the `createEvent` params (the backend already accepts it).

6. **Add "confirm card" step** (#4):
   - Either stage fights in JS state and POST on confirm, OR add `fights.is_draft = 1` column + a `confirm_card(event_id)` API.
   - Hide the live projection until confirm — OR keep the live projection but rename it "Draft Preview" and add a separate "Confirmed P&L" after the player commits.
   - **Important design note:** `MASTER_PLAN_MATCHMAKING.md` §1.2 explicitly designed the live projection as the headline feature ("the dopamine loop closer: book better fights → see projection rise"). The user's directive to NOT calculate until confirm reverses this. We should confirm with the user whether they want:
     - (a) Live projection hidden entirely until confirm
     - (b) Live projection shown but framed as "rough estimate" with the "real" numbers only after confirm
     - (c) Live projection shown but the actual fight bookings staged (not persisted) until confirm

**P3 — Add personality-driven last-minute rejection** (#7):

7. **Build a `willingness_to_fight` check** in `book_fight`:
   - Compute days between current sim date and `event.event_date`.
   - If < 14 days ("short notice"), apply a personality-driven rejection:
     - Query `fighter_personality` for both fighters.
     - High-`professionalism` / low-`greed` fighters: high chance to refuse.
     - High-`greed` / desperate fighters (on losing streak, contract year): low chance to refuse.
     - Champions: very high chance to refuse short-notice (they have nothing to gain).
   - On refusal: return `{ok: false, error: "[Fighter Name] won't take this fight on short notice — they need a full training camp."}`.
   - Surface this in the roster UI: dim fighters who would refuse at the current event's lead time.
   - This requires the `fighter_personality` table to be populated (worth verifying — was not in scope of this research).

### 6.3 Quick wins (could ship in a single session)

These are small, isolated changes that immediately improve the UX without architectural rework:

- **Render `marketability` as a voice phrase in the roster row** — 1-line change to `_fighter_brief` (add a `marketability_phrase` derived from the 0–100 score) + 3-line change to `renderRosterList`.
- **Render titles-held chip per fighter** — small SQL JOIN added to `_fighter_brief` + 3-line change to `renderRosterList`.
- **Remove the numeric matchup_score from the chip** — delete `<span class="ce-mm-quality-chip__score">' + (bf.matchup_score || 0).toFixed(0) + '</span>` in `renderFightCard`. The phrase already conveys the band.
- **Hide "Predicted Winner" cell from Compare modal** — delete the pred-cell block in `renderCompareModal`.
- **Add `event_date` to `createEvent` params** — pass `event_date` from `event_builder.js` (even if hardcoded to +14 days for now) so the player-facing API is wired for a future date picker.

### 6.4 Architectural changes (need user approval before building)

- **Confirm-card flow** — requires either a `fights.is_draft` column migration or a complete re-architecture of the booking pipeline (stage in JS, POST batch on confirm).
- **Calendar screen** — new API + new JS module + DB queries to surface all scheduled events in a date range.
- **Personality-driven rejection** — requires `fighter_personality` table to be populated (verification needed) + a new "willingness" computation in `book_fight`.
- **"Might" advice re-voicing** — requires changes to `punditry.py` to soften predictions, OR a translation layer in `app_web.py` that converts definitive punditry output into hedged voice phrases for the matchmaking screen (keeping the definitive version for post-fight analysis).

---

## 7. Cross-References to Existing Design Docs

### 7.1 `docs/MASTER_PLAN_MATCHMAKING.md` — original Phase M4 plan

The plan **explicitly designed the live projection as the headline feature** (§1.2: "Live projection debounced 200ms (per spec: <100ms perceived update)"). The user's new directive "calculations should NOT happen until card is confirmed" **contradicts this plan**. We need user confirmation on which design wins.

The plan also said (§1.5 "No easy mode"): *"The matchup quality chip shows the score but doesn't tell the player WHO to book."* — the chip was supposed to show the score, but the user now wants the OPPOSITE (no score, only voice phrase). The current JS does both (phrase + score), which neither doc nor user wants.

The plan did NOT anticipate:
- The need for a calendar/date picker (assumed +14 days was fine).
- The need for a "confirm card" step (assumed live projection was the loop).
- The need for personality-driven last-minute rejection.
- The need to show popularity/titles/rivalries inline (it mentioned marketability chip in §1.2 roster spec but the implementation dropped it).

### 7.2 `docs/RESEARCH_WMMA5_MATCHMAKING.md` — WMMA5 patterns

Key WMMA5 patterns we borrowed (per §7.1 of that doc):
- 2-column blue/red corner layout ✅ implemented
- Compare button with style analysis ✅ implemented (radar chart + voice line — actually IMPROVED over WMMA5's text-only)
- Fan Feedback / Fan Pulse ✅ implemented as modal
- Side-panel DRAW stars ✅ implemented as matchup_score chip
- 2-rating split (Commercial vs Critical) — partially: card_draw_score is the projectable Commercial axis; Critical is post-event only
- Drag-drop reordering ✅ implemented (WMMA5 only had ▲▼ arrows)

Key WMMA5 patterns we DID NOT borrow (and the user is now asking for):
- **Likely Usage / Name Value text label** (WMMA5 §1.3, dev-journal #146) — we have `marketability` as a raw number but never render it as a text phrase like "Mid Regional".
- **Short Notice Search** (WMMA5 §1.9, dev-journal #152) — not implemented.
- **Replacement Offers** (WMMA5 §1.9, dev-journal #160) — not implemented.
- **Absences button** (WMMA5 §1.9, dev-journal #144) — we have no equivalent. Injured/suspended fighters just disappear from the roster; there's no screen to review who's unavailable.
- **Hype slider** (WMMA5 §5.8) — not implemented.
- **Booking Adviser** (WMMA5 §5.5) — not implemented (opportunities panel for hometown/streaks/debuts/title picture).
- **1-month minimum lead time** (WMMA5 §2.1) — not enforced.

### 7.3 `docs/REWARD_REVIEW.md` — reward design

That doc focuses on Dashboard/Roster/Free Agents/Fighter Profile (the 4 original screens). It does NOT cover Matchmaking. But its principles apply:
- **Ownership** — the matchmaking screen DOES use ownership language ("YOUR NEXT CARD", "YOUR WAR CHEST", "YOUR NET PROFIT").
- **Agency** — the live projection gives the player agency (they see consequence of each booking), but the user's new "no calculations until confirm" directive would REDUCE agency in the moment (player has to commit blind).
- **Discovery** — the roster browser is discovery-rich (filter chips + search), but the missing popularity/titles/rivalries chips reduce at-a-glance readability.

### 7.4 `docs/SCREEN_DATA_AUDIT.md` — DB field availability

That doc was written before matchmaking shipped. Its open issues section (§"Open Issues") flagged:
- Line 235: *"No 'is_on_card' flag … would need a JOIN against `fights` WHERE `event_id IN (SELECT event_id FROM events WHERE status='scheduled')` AND (`winner_fighter_id` IS NULL — i.e. fight not yet resolved)."* — **this is exactly the gap we still have** in `_get_available_fighters_for_card` and `book_fight`.
- Line 459: *"No 'is_booked' flag. Book Next Fight button needs to know if fighter is already on an upcoming card."* — same gap, restated.
- Line 447: *"Book Next Fight … fighter is on player's promo AND not currently in `training_camps` for an upcoming event"* — this requirement was documented but NOT implemented.

So the booking-availability gaps the user is reporting were **documented 4 months ago** but never closed.

---

## 8. Final Summary

The matchmaking + event-builder screens are functional but exhibit every gap the user reported. The fixes range from 1-line tweaks (render marketability phrase, remove numeric score from chip, hide Predicted Winner cell) to architectural reworks (confirm-card flow, calendar screen, personality-driven rejection). The biggest design decision to escalate to the user:

**The user's directive "calculations should NOT happen until card is confirmed" directly contradicts the original `MASTER_PLAN_MATCHMAKING.md` §1.2 design ("Live projection debounced 200ms").** We need explicit confirmation: hide the projection entirely until confirm? Show a "rough estimate" but lock the "real" numbers behind confirm? Or stage fights in JS (not persisted) until confirm?

Without that decision, the P2 work (#6 above) can't be scoped.
