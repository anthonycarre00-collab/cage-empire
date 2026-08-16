> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# Research: Fight Night Screen

> Task ID: **RESEARCH-FIGHT-NIGHT-ENGINE**
> Scope: read code + docs and report findings. No code written.
> Sources read: `src/services/fight_engine.py` (5 097 lines),
> `src/app_web.py` (8 011 lines), `src/web/js/app.js`, `src/web/js/bridge.js`,
> `src/punditry.py`, `src/services/punditry_svc.py`, `src/show_rating.py`,
> `src/news.py`, `src/rival_ai.py`, `src/tick_processor.py`, `src/build_db.py`,
> `docs/NAV_BUTTONS_AUDIT.md`, `docs/SCREEN_DATA_AUDIT.md`,
> `docs/GUI_PLAN.md`, `docs/UI_REDESIGN_VISUAL_PLAN.md`, `docs/STAGES.md`,
> `docs/CONVENTIONS.md §17.2`, `docs/RESEARCH_WMMA5_MATCHMAKING.md`,
> `docs/RESEARCH_WMMA5_FM_V2.md`.

---

## TL;DR (read this first)

1. **The fight engine already exists and is rich.** `resolve_next_fight` in
   `src/services/fight_engine.py` produces a full beat-by-beat simulation:
   12-28 beats/round × N rounds, with phase transitions (standing → clinch →
   cage → ground_top → ground_bottom → scramble), fatigue (gas 100 → 0 with
   between-round recovery), momentum swings, KO / TKO / submission / DQ /
   doctor-stoppage / corner-stoppage / decision / draw outcomes, weight cuts,
   rivalry pressure modifiers, injuries, rankings (ELO), title changes, news,
   and event lifecycle transitions. The raw substrate for a play-by-play UI is
   fully populated in two tables: `fight_beats` (one row per exchange) and
   `fight_rounds` (one row per round, with aggregates).
2. **The web UI cannot trigger fight resolution.** `app.js` registers a
   `fight_resolution` nav item ("Fight Night", 🔥 icon) but its handler falls
   through to a generic placeholder ("Fight Night awaits. The cage is ready.
   The fans are waiting."). The bridge (`bridge.js`) has no
   `resolveNextFight` method, and `app_web.py:Api` has no
   `resolve_next_fight` wrapper. Only the **legacy Tkinter** `src/app.py`
   has an `on_resolve_fight` button wired to `resolve_next_fight(self.conn)`.
   Rival promotions get auto-resolved by the daily tick (`rival_ai.py` lines
   525-546); the **player's promotion is explicitly excluded** from that
   auto-resolution path (`WHERE promotion_id != PLAYER_PROMOTION_ID`). So
   today, the player's booked fights never resolve in the web app at all.
3. **Per-beat commentary exists, but only as 3-14 highlight "segments"
   per fight, not per beat.** `_select_commentary_beats` picks the most
   important beats (knockdowns, near-finishes, the finishing beat, big
   momentum swings) and `_generate_beat_commentary` writes one
   `commentary_segments` row per selected beat using 7 hard-coded templates
   (`_BEAT_COMMENTARY_TEMPLATES` — one line each, e.g. `"{init} drops {target}
   with a heavy shot in round {round}!"`). The remaining 100-200 beats per
   fight have no prose — they have structured data (phase, action_type,
   initiator, target, outcome, damage_dealt, control_time_delta,
   momentum_shift) but no commentary line. Punditry (`src/punditry.py`)
   generates a **single pre-fight analysis paragraph** per fight
   (`matchup_analyses` table) — it is not a per-beat system.
4. **Fights CAN be resolved one at a time** — `resolve_next_fight` picks the
   lowest-`fight_id` unresolved fight. But the rival-AI loop
   (`_resolve_event_card`) drains the whole card in one tick. The web UI
   needs a new "resolve one fight" entry point that lets the player click
   "Play Next Fight" and have the engine write all beats + commentary +
   side effects for that one fight, return the fight_id, and let the UI
   replay the beats at whatever pace the player chooses.
5. **Show rating fires once per event completion** (subscriber for
   `EVENT_COMPLETED`), writes a single `show_ratings` row with 5 axes
   (fan / commercial / excitement / quality / overall) + a voice
   descriptor ("an instant classic that fans will talk about for years").
   This is the natural post-event pay-off moment for a Fight Night recap.

---

## 1. Fight Engine

### 1.1 Entry point
`src/services/fight_engine.py::resolve_next_fight(conn, promotion_id=None) -> int | None`
(line 4 138). Returns the resolved `fight_id`, or `None` if no unresolved
fight was found. The caller commits (`app.py:933` does `self.conn.commit()`
after the call).

The pick-query (lines 4 201-4 209):
```sql
SELECT f.fight_id, f.event_id, f.scheduled_rounds, e.promotion_id,
       f.weight_class_id, e.event_date, f.card_slot, f.is_title_fight
FROM fights f JOIN events e ON e.event_id=f.event_id
WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL
  [AND e.promotion_id = ?]      -- only if promotion_id arg is passed
ORDER BY f.fight_id LIMIT 1
```
So fights resolve in **fight_id order** (the order they were booked). With
`promotion_id=None` (the player's "Resolve Fight" button), it picks the
lowest-id unresolved fight across **all** promotions. With
`promotion_id=X` (the rival-AI path), it only picks from that promotion.

### 1.2 How fights resolve — the beat-by-beat loop
Per fight, `resolve_next_fight` does this in order (lines 4 200-5 059):

1. **Load fighter stats** — 25 attributes + 20 personality + 3 meta columns
   per fighter (`_load_fighter_stats`, line 129).
2. **Run weight cuts** for both fighters (`_run_weight_cut`, line 3 157). If
   either "missed large" (>3 kg over), the fight is cancelled as
   `no_contest` and we return early (lines 4 232-4 333). A "missed medium"
   cut applies a cardio penalty (gas reduced at round 1 start).
3. **Rivalry pressure modifiers** (lines 4 354-4 389) — if the two fighters
   have an active rivalry with heat > 70, both get +5 aggression / -5
   composure; heat > 90 doubles it.
4. **Compute fight importance + pressure modifiers** (lines 4 397-4 404) —
   importance is a computed 0-100 value (card_slot + is_title_fight +
   marketability), never stored. Pressure modifiers only apply in
   high-importance fights (importance > 60).
5. **Beat-level resolution** (lines 4 468-4 598) — calls `resolve_round()`
   once per round, with `gas_a` / `gas_b` / `cum_momentum` carried
   across rounds. After each round, checks for **corner stoppage**
   (3+ consecutive rounds lost + low grit + low composure, 20% chance)
   and **doctor stoppage** (cumulative damage > threshold + 50-point
   differential). Mid-round finishes (KO/sub/DQ) break out of the
   `for round_number` loop early.
6. **Decision scoring** if no finish occurred (`_decide_fight_outcome`,
   line 2 057) — 10-point must across rounds, with knockdowns producing
   10-8 rounds.
7. **Compute performance_rating + fan_reaction_rating** (lines 4 632-4
   661) — clamped 60-95, with bonuses for finishes and upsets.
8. **Side effects** (all inline in `resolve_next_fight`):
   - `UPDATE fights SET winner_fighter_id/loser_fighter_id/result_type/...`
   - `UPDATE fight_participants SET is_winner=...`
   - `UPDATE fighter_career SET record_wins/losses/draws, streaks`
   - `DELETE + INSERT INTO fight_history` (2 rows per fight, one per
     fighter's perspective — `outcome` ∈ {win, loss, draw, nc})
   - `_update_rankings_after_resolution` — ELO update (K=32, zero-sum)
   - `_resolve_title_after_fight` — transfers/vacates belt if title fight
   - `write_news` + `write_commentary` (legacy, in `app.py:124-132`)
   - `_select_commentary_beats` + `_generate_beat_commentary` — writes
     3-14 `commentary_segments` rows (segment_type='highlight') for the
     key moments of the fight
   - `_update_event_status_after_resolution` — transitions event status
     (scheduled → in_progress → completed). Publishes
     `EVENT_COMPLETED` on the event bus when the event completes.
   - `schedule_next_event` — auto-schedules the promotion's next event
     ~4 weeks out if this event just completed.
   - `_check_post_fight_injuries` — rolls injury probability per fighter
     per outcome type (5% base, 30% for KO loser, 15% for sub loser,
     guaranteed for doctor stoppage).
   - `update_fighter_descriptor_snapshot` — refreshes the cached
     `fighter_descriptors` row for both fighters (trigger-based cache
     update — record, ELO, streaks, career_health, title status).
   - `_update_preferred_gameplans` (winner) +
     `_update_bad_matchup_tags` (loser) — Phase A12 inline writes.
   - Publishes `FIGHT_RESOLVED` + `FIGHTER_STATE_CHANGED` (×2) +
     `TITLE_CHANGED` (if applicable) on the event bus.

### 1.3 One-at-a-time vs whole-event
**One at a time is supported** — `resolve_next_fight` picks exactly one
fight per call. The caller decides whether to loop:

- **Legacy Tkinter UI** (`src/app.py:931-939`): single call per button
  press — `on_resolve_fight` calls `resolve_next_fight(self.conn)` once
  and refreshes. So one button click = one fight.
- **Rival AI** (`src/rival_ai.py:353-380`): loops
  `resolve_next_fight(promotion_id=X)` until it returns `None`,
  draining the entire card in one tick. Comment at line 529: *"an MMA
  event is a single-night card, not a week-by-week trickle"*.
- **Web UI**: does not call `resolve_next_fight` at all. This is the gap.

### 1.4 What happens to the player's scheduled fights today?
On `advance_day`, `tick_processor.run_tick` publishes `TICK_ADVANCED`.
Rival AI's daily-phase subscriber (`rival_ai.py` lines 519-546) loops
over `rival_rows` which **explicitly excludes the player's promotion**
(`WHERE promotion_id != PLAYER_PROMOTION_ID`, line 522). So:

- Rival promotion events whose `event_date <= current_date` resolve
  automatically on the tick that crosses the event date.
- **The player's events never auto-resolve** — they sit in `scheduled`
  status forever. The only way to resolve them is the legacy Tkinter
  button. There is no web-UI affordance.

---

## 2. Beat Engine (the play-by-play data)

### 2.1 `fight_beats` schema
Defined in `src/build_db.py:1933-1968`. One row per discrete exchange
within a round.

| Column | Type | Notes |
|---|---|---|
| `fight_beat_id` | INTEGER PK AUTOINCREMENT | |
| `fight_id` | INTEGER NOT NULL FK → fights | ON DELETE CASCADE |
| `round_number` | INTEGER NOT NULL | 1-indexed |
| `beat_number` | INTEGER NOT NULL | 1-indexed within the round |
| `phase` | TEXT NOT NULL CHECK IN ('standing','clinch','cage','ground_top','ground_bottom','scramble') | |
| `action_type` | TEXT NOT NULL | One of `jab`, `cross`, `hook`, `leg_kick`, `head_kick`, `clinch_entry`, `takedown_attempt`, `clinch_knee`, `clinch_elbow`, `cage_push`, `break_clinch`, `cage_knee`, `ground_strike`, `submission_attempt`, `scramble`, `sweep_attempt`, `stand_up` (defined in `PHASE_ACTIONS` constant, fight_engine.py:254) |
| `initiator_fighter_id` | INTEGER NOT NULL FK → fighters | The attacker / aggressor |
| `target_fighter_id` | INTEGER NOT NULL FK → fighters | The defender |
| `outcome` | TEXT NOT NULL CHECK IN ('landed','missed','blocked','defended','reversed','knockdown','near_finish') | |
| `damage_dealt` | INTEGER NOT NULL DEFAULT 0 | For 'landed' strikes; 0 otherwise |
| `control_time_delta` | INTEGER NOT NULL DEFAULT 0 | 1-5 seconds for clinch/cage/ground landed; 0 standing |
| `momentum_shift` | INTEGER NOT NULL DEFAULT 0 | +10 to +30 for landed; +80 for knockdown; +60 for near_finish; -10 to -30 for reversed |
| `created_at` | TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| | | **UNIQUE (fight_id, round_number, beat_number)** |

### 2.2 `fight_rounds` schema
Defined in `src/build_db.py:1970-2002`. One row per round, populated by
a SUM-over-`fight_beats` query so the two tables never drift.

| Column | Type | Notes |
|---|---|---|
| `fight_round_id` | INTEGER PK AUTOINCREMENT | |
| `fight_id`, `round_number` | INTEGER NOT NULL | UNIQUE pair |
| `fighter_a_id`, `fighter_b_id` | INTEGER NOT NULL FK | |
| `fighter_a_damage`, `fighter_b_damage` | INTEGER | damage DEALT BY A/B |
| `fighter_a_control_time`, `fighter_b_control_time` | INTEGER | seconds of control in clinch/cage/ground |
| `fighter_a_knockdowns`, `fighter_b_knockdowns` | INTEGER | knockdowns SCORED BY A/B (D4 convention) |
| `fighter_a_takedowns`, `fighter_b_takedowns` | INTEGER | takedown_attempt + landed count |
| `fighter_a_strikes_landed`, `fighter_b_strikes_landed` | INTEGER | outcome='landed' in standing/clinch/ground phases |
| `fighter_a_gas_remaining`, `fighter_b_gas_remaining` | REAL DEFAULT 100.0 | end-of-round gas (B2 fatigue) |
| `momentum_state` | TEXT | signed cumulative momentum at round end (positive = favors A) |
| `round_winner_fighter_id` | INTEGER FK → fighters | 10-point must winner of the round |
| `created_at` | TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP | |

### 2.3 Beats per round, rounds per fight
- **Beats per round: 12-28**, computed by the pace formula
  (`resolve_round` line 1 627):
  ```
  pace_a = aggression*0.3 + speed_explosiveness*0.3 + cardio*0.2 + discipline*0.2
  pace_b = (same for fighter b)
  beats = max(12, min(28, 15 + round((pace_a + pace_b) / 2 / 10)))
  ```
  So a fast-paced brawler fight hits the 28-beat cap; a slow technical
  fight drops to the 12-beat floor.
- **Rounds per fight: `fights.scheduled_rounds`** (typically 3 for
  non-title, 5 for title fights). Finishes (KO/sub/DQ/doctor/corner)
  stop the loop early — the remaining rounds don't get
  `fight_rounds` rows, and the in-progress round is the last one written.
- **Total beats per fight: 36 (3-round min pace) to 140 (5-round max
  pace), with finishes cutting it short.** The B2 acceptance test
  (`scripts/test_beat_engine.py` case E) verifies ≥12 × sched and
  ≤28 × sched beats per fight.

### 2.4 What data per beat
Every beat has: round_number, beat_number, phase, action_type,
initiator_fighter_id, target_fighter_id, outcome, damage_dealt,
control_time_delta, momentum_shift. Plus the engine tracks (in-memory,
not stored) per-beat: gas_a/gas_b before-and-after, cum_momentum before-
and-after, consecutive_damage_to_a/b (the KO-check tracker), and
knockdowns_a/b (round-level counter). The beat_id is captured so it can
be `UPDATE`d to mark the finishing blow (outcome='knockdown' or
'near_finish') after the fact.

### 2.5 Beat-phase state machine
The engine starts each round in `phase = 'standing'`. The
`_maybe_transition_phase` helper (line 1 499) advances the phase based
on the action + outcome — e.g. a `clinch_entry` that lands transitions
to `clinch`; a `takedown_attempt` that lands transitions to `ground_top`
(initiator on top) or `ground_bottom` (reversed); a `stand_up` lands
returns to `standing`. `scramble` is a transient phase used for one
beat at a time. There is no per-beat "cage position" coordinate stored —
the heatmap visualization called for in GUI_PLAN §7.1 will need to be
derived from `phase` + `initiator_fighter_id` (e.g. "takedown_attempt
landed from standing" → "fight moved to ground_top with A on top").

---

## 3. Commentary System

### 3.1 What exists today (per-beat commentary)
`_select_commentary_beats` + `_generate_beat_commentary` (lines 2 364
and 2 466). After the fight resolves:

1. The engine selects 3-14 of the most "important" beats:
   - **Quick fights** (importance < 40): 3-6 beats
   - **Standard** (40 ≤ importance < 70): 6-10 beats
   - **Extended** (importance ≥ 70): 10-14 beats
2. Selection priority (`beat_priority`, line 2 431):
   - knockdown (priority 1000)
   - finishing_beat (priority 900 — only set if the fight ended in
     KO/sub/DQ)
   - near_finish (priority 800)
   - big_momentum_swing (priority 500 + |momentum|, where |momentum| > 50)
   - everything else: priority = damage_dealt (so the highest-damage
     beat per round gets in)
3. Re-sorted chronologically (round_number, beat_number).
4. For each selected beat, one `commentary_segments` row is written
   with `segment_type='highlight'`, `speaker_staff_id` = first
   commentator staff row, `text` from the template, `importance` ∈
   {95 (knockdown), 85 (near_finish), 75 (big_swing), 60 (other)}.

### 3.2 The 7 templates (`_BEAT_COMMENTARY_TEMPLATES`, line 2 350)
```python
{
    "knockdown":    "{init} drops {target} with a heavy shot in round {round}!",
    "near_finish":  "{init} has {target} hurt in round {round} — the finish is near.",
    "landed":       "{init} lands a clean strike on {target} in round {round}.",
    "reversed":     "{target} reverses {init}'s attempt in round {round} — momentum swing!",
    "defended":     "{target} anticipates and defends {init}'s attack in round {round}.",
    "blocked":      "{target} absorbs {init}'s strike on the guard in round {round}.",
    "missed":       "{init} swings and misses {target} in round {round}.",
}
```
Slots: `{init}` = initiator's full name, `{target}` = target's full name,
`{round}` = round number.

### 3.3 What's missing
- **No per-beat commentary for the ~100-200 non-highlight beats.** A
  live play-by-play UI needs prose for every beat, not just the 3-14
  highlights.
- **No variety in the templates.** 7 fixed lines means after 3-4 fights
  the player sees the same prose repeatedly. CONVENTIONS §14 (Voice
  Layer) requires ≥8 variants per template — the per-beat system needs
  to follow the same voice-variant discipline used elsewhere.
- **No action-type-specific prose.** All "landed" outcomes use the same
  template regardless of whether the action was a `jab`, a `head_kick`,
  a `clinch_knee`, a `takedown_attempt`, or a `ground_strike`. The
  template doesn't tell the player WHAT was thrown.
- **No phase-specific prose.** "Lands a clean strike" reads the same in
  standing, clinch, cage, and ground_top — losing the texture of
  position.
- **No momentum-aware prose.** A `landed` beat with momentum_shift=+30
  (a big swing) reads the same as a `landed` beat with momentum_shift=+5.
- **No commentator personality.** `speaker_staff_id` is set but the
  prose doesn't use `staff.pundit_bias` (the schema column the brief
  said would power "named-pundit interjection generator"). The
  `punditry_svc.py` wrapper comment explicitly defers this: *"defer
  named-pundit interjection generator to Task 6.7 Fight Resolution
  screen, where `staff.pundit_bias` is actually read"*.

### 3.4 Punditry system — what it actually does
`src/punditry.py` (1 343 lines). Public API:
- `generate_matchup_analysis(conn, fighter_a_id, fighter_b_id, fight_id,
  event_id, rng)` — generates ONE pre-fight analysis row in
  `matchup_analyses` table. Predicts winner, method (KO/sub/decision),
  confidence (50-90%), style edge, excitement score (0-100), upset risk,
  and writes a full prose `analysis_text`. Uses voice descriptors (no
  raw numbers per §14).
- Subscribed to `FIGHT_RESOLVED` (`_process_scheduled_fight`, line 1
  297) — generates the analysis retroactively (the brief calls this
  "the analysis describes the pre-fight matchup, written after the fight
  for the news feed").
- `get_matchup_analysis`, `get_recent_analyses`, `get_event_analyses` —
  readers.
- `services/punditry_svc.py` is a 26-line pure wrapper re-exporting
  `punditry.py`.

**Punditry is the PRE-fight prediction, not the live play-by-play.**
The Matchmaking screen (`src/web/js/matchmaking.js`) already uses it
via `get_fight_analysis` / `get_fight_compare` / `get_fight_tale_of_tape`
bridge methods. For Fight Night, punditry output is the **pre-fight
build-up panel** ("here's what the pundits thought going in"), not the
live commentary.

### 3.5 News.py — what it generates for fights
`src/news.py:generate_fight_news` (line 840) — subscribes to
`FIGHT_RESOLVED`. Picks a headline template based on result_type
(`_FIGHT_HEADLINES_KO` / `_SUB` / `_DEC` / `_DOCTOR` / `_OTHER`) and a
body template from `_FIGHT_BODY_TEMPLATES`, fills voice-layer slots
(career_stage, attr_summary, winner_overall). Writes a `news_items`
row. Also: `generate_title_news`, `generate_injury_news`,
`generate_retirement_news`, `generate_event_recap_news` (subscriber for
`EVENT_COMPLETED`). All event-bus-driven, no per-beat content.

### 3.6 Where commentary lives
`commentary_segments` table (`build_db.py:1601-1610`):
```
commentary_segment_id INTEGER PK
event_id              FK → events
fight_id              FK → fights
segment_type          TEXT  -- 'play_by_play' (legacy 1-per-fight) or 'highlight' (per-beat)
speaker_staff_id      FK → staff
text                  TEXT
importance            INTEGER DEFAULT 50
created_at            TEXT
```
Two segment_type values are in use today:
- `'play_by_play'` — written by `app.py:write_commentary`, exactly one
  row per fight (the overall summary line). Importance=70.
- `'highlight'` — written by `_generate_beat_commentary`, 3-14 rows
  per fight (the key moments). Importance 60-95.

### 3.7 Voice phrases
`src/voice.py` (not deeply read for this task) provides the
voice-layer functions: `describe_attribute`, `describe_career_stage`,
`describe_overall`, `describe_potential`. The existing
`_BEAT_COMMENTARY_TEMPLATES` does NOT route through `voice.py` —
it's a flat string format. Per CONVENTIONS §17.2, the Fight Night
screen is **EXEMPT from the snapshot-cache rule** and reads live
`fight_beats` / `fight_rounds` / `commentary_segments` tables and
applies `voice.py` on the fly. So a per-beat commentary system can
either:
- (a) Generate prose at resolution time and store in
  `commentary_segments.text`, OR
- (b) Generate prose on the fly in the UI from the structured beat
  data (phase + action_type + outcome + damage + momentum) using
  voice.py + a richer template system.

(b) is more flexible but loses the persisted narrative; (a) is the
pattern the existing code uses.

---

## 4. Existing UI

### 4.1 Nav state
`src/web/js/app.js` line 44:
```js
{ id: 'fight_resolution', name: 'Fight Night', icon: '🔥' },
```
In the EVENTS nav group, alongside `event_builder` ("Stack a Card"),
`matchmaking` ("Matchmaking"), and `past_events` ("The Archive").

### 4.2 Placeholder phrase
`app.js` line 71:
```js
fight_resolution: { title: 'Fight Night awaits.',
                    body: 'The cage is ready. The fans are waiting.' },
```

### 4.3 `navigate()` handler
`app.js` `navigate(screenId, params)` (line 267) has explicit cases
for: `dashboard`, `schedule`, `roster`, `free_agents`,
`rival_promotions`, `event_builder`, `matchmaking`, `staff_market`,
`fighter_profile`. **There is no `fight_resolution` case.** It falls
through to the generic placeholder renderer (lines 354-372) which
shows the placeholder title + body.

### 4.4 Is there a `fight_resolution.js` file?
**No.** `src/web/js/` contains: `app.js`, `bridge.js`, `dashboard.js`,
`calendar.js`, `roster.js`, `free_agents.js`, `rival_promotions.js`,
`event_builder.js`, `matchmaking.js`, `fighter_profile.js`,
`staff_market.js`. No `fight_resolution.js`, no `fight_night.js`. No
CSS file either.

### 4.5 Bridge gaps
`bridge.js` exposes 30+ methods covering roster, free agents, event
builder, matchmaking, calendar, staff market, rival promotions,
save/load. **There is no `resolveNextFight`, no
`getFightBeats(fightId)`, no `getFightRounds(fightId)`, no
`getFightCommentary(fightId)`, no `getEventCardForResolution(eventId)`.**
The closest existing methods are:
- `getFightTaleOfTape(fightId)` — pre-fight physical/spec comparison
- `getFightStakes(fightId)` — ranking implications + title shot context
- `getFightFanPulse(fightId)` — rivalry context + hometown reaction
- `getFightCompare(fightId)` — 25 attributes for both fighters

All of these are pre-fight analytical data. None surface the per-beat
play-by-play substrate that already exists in `fight_beats` /
`fight_rounds` / `commentary_segments`.

### 4.6 Nav-buttons audit findings
`docs/NAV_BUTTONS_AUDIT.md`:
- §1.1: `fight_resolution` is in the EVENTS nav group (one of 4).
- §2.4 row 11 (Fighter Profile): "Replay fight link (▶ ghost) — On
  each Recent Fights row — ❌ NOT IMPLEMENTED (P1 future) —
  `navigate('fight_resolution', {fight_id})`". So the long-term plan
  is to deep-link from a fighter's recent-fight row into the Fight
  Night screen with a `fight_id` param, replaying that fight's beats.

### 4.7 SCREEN_DATA_AUDIT.md findings
**`fight_resolution` is NOT covered** in SCREEN_DATA_AUDIT.md. The
audit covers Dashboard, Roster, Free Agents, Fighter Profile only
(§1-§4). The "Cross-Screen Findings" (§5) and "Recommendations" (§6)
do not mention Fight Night. This means there is no field inventory
done yet for Fight Night — that work is part of this research task's
output.

---

## 5. Show Rating

### 5.1 When it fires
`src/show_rating.py:_compute_show_ratings` (line 541) is a subscriber
for the `EVENT_COMPLETED` event (line 701: `bus.subscribe(
Events.EVENT_COMPLETED, _compute_show_ratings, ...)`). It fires once
per event — when the event transitions to `completed` status (the last
fight on the card resolves). The `EVENT_COMPLETED` event is published
by `_update_event_status_after_resolution` in `fight_engine.py` (line
2 544+).

### 5.2 What it computes
5 rating axes (each 0-100, CHECK constraint):
- **`fan_rating`** — finishes (KO/sub) vs decisions, fight excitement
  (beats + damage), title fights (+10), rivalry fights (+5).
- **`commercial_rating`** — total fighter marketability, broadcast tier
  (PPV +20, streaming +10, TV +5), attendance from `finance.ticket_sales`.
- **`excitement_rating`** — avg beats per fight, avg damage per fight,
  number of knockdowns, number of near-finishes. Reads from
  `fight_beats` (so the beat engine substrate directly feeds the
  excitement axis).
- **`quality_rating`** — avg fighter attributes, fight IQ, clean
  techniques landed.
- **`overall_rating`** — weighted average: fan 30% + commercial 20% +
  excitement 25% + quality 25%. Phase E5 commentator bonus: +1 per
  10 skill points on the player's active commentators (max +15).

### 5.3 Voice-layer descriptor
`_describe_rating(overall)` (line 131):
- 90+: "an instant classic that fans will talk about for years"
- 75-89: "a highly entertaining show that delivered on expectations"
- 60-74: "a solid night of fights with some memorable moments"
- 40-59: "a decent show that failed to produce many highlights"
- <40: "a lackluster card that left fans wanting more"

### 5.4 What it writes
- `INSERT INTO show_ratings (event_id, promotion_id, fan_rating,
  commercial_rating, excitement_rating, quality_rating,
  overall_rating, rating_description)` — UNIQUE on event_id so it's
  idempotent.
- `_write_show_rating_news` — a `topic='show_rating'` news item with
  the voice descriptor (no raw numbers per §14). Headline + body use
  the descriptor only.

### 5.5 Post-event rating
**Yes — this is exactly the post-event pay-off moment.** When the
Fight Night screen resolves the last fight on the card, the
`EVENT_COMPLETED` event fires, show_rating computes the 5 axes and
writes the descriptor. The Fight Night recap phase can read
`show_ratings` for the event_id and display:
- The descriptor (large, voice phrase)
- The 5 axes as a small radar / bar chart (with raw numbers — show
  ratings are game-state, OK to display per §14)
- The commentator bonus contribution ("your commentary team added +X")

### 5.6 Pre-event projection
**Not built.** `docs/RESEARCH_MATCHMAKING_SHOWRATING.md` flags this as
an opportunity: `commercial_rating` and `quality_rating` are 100%
projectable pre-event (they use known quantities — marketability,
broadcast tier, fighter attributes, fight IQ). `fan_rating` and
`excitement_rating` require the fight to resolve (they read
`fight_beats`). So a pre-event projection can show 2 of 5 axes;
post-event shows all 5.

---

## 6. WMMA5 Comparison

### 6.1 How WMMA5 does fight resolution
The two WMMA5 research docs (`RESEARCH_WMMA5_FM_V2.md`,
`RESEARCH_WMMA5_MATCHMAKING.md`) focus on matchmaking, scheduling, show
rating, and fighter-info display. They do NOT cover the live fight
play-by-play in detail. What they do say:
- §5.11 (WMMA5_MATCHMAKING): "When the player advances to an event,
  commentators give a pre-fight breakdown. Shortcut keys
  (space/backspace/enter/s/b/t) let the player read it at their own
  pace. This builds anticipation — the gap between booking and
  watching is filled with narrative texture."
- The WMMA5 handbook (cited in FM_V2 sources) describes event
  resolution as a single-night play-out of the whole card. From the
  CAGE EMPIRE codebase mirror of this behavior
  (`rival_ai.py:_resolve_event_card`): "an MMA event is a single-night
  card, not a week-by-week trickle."

### 6.2 What's known from the genre
WMMA5 (and its parent game TEW — Total Extreme Wrestling) resolve
fights/matches text-beat-by-text-beat, with the player able to:
- Read each beat as a paragraph of prose.
- Press space to advance, backspace to go back, enter to skip to the
  finish.
- See a commentator panel that interjects ("That's the third body shot
  in 90 seconds").
- See a momentum indicator (who's "winning" the segment).
- At the end, see a rating for the match (commercial + critical) and
  a written recap.

The WMMA5 docs are explicit that this is **text-driven** — there is no
visual cage heatmap, no damage silhouette, no radar chart. CAGE
EMPIRE's GUI_PLAN §7.1 calls out the difference: "WMMA5 uses a flat
text feed for play-by-play; we replace with the 4-zone Fight Night
screen" (UI_REDESIGN_VISUAL_PLAN.md §"Stolen from..." table).

### 6.3 What makes WMMA5's resolution engaging (per the docs)
- **Pre-show commentary** that builds anticipation (the gap between
  booking and watching is filled with narrative).
- **Per-beat prose** — every exchange gets a sentence, not just a
  log line.
- **Named interjections** from the broadcast team ("pundit_bias" in
  our schema, currently unused).
- **The dopamine loop** — booking → pre-show → live fight → result →
  recap → next booking. WMMA5 keeps the player reading by varying the
  prose and surfacing storyline context (rivalries, momentum shifts,
  crowd reactions).

### 6.4 Where WMMA5 falls short (per the docs)
- DATED, spreadsheet-like UI (§6.1) — flat text feed, no visuals.
- No live attendance / buyrate / revenue projection (§6.3) — the
  player books blind.
- Compare button is text-only (§6.4) — no visual radar / tale-of-tape
  graphic.
- Critical rating doesn't explain itself (§6.12).
- Information overload across many screens (§6.14).

CAGE EMPIRE's GUI_PLAN explicitly positions the Fight Night screen as
the answer to all of these: "HBO 24/7 meets a live ESPN broadcast,
narrated by documentary-grade prose, with pundits who argue, memories
that resurface at the perfect moment, and a cage heatmap that shows
you exactly where the fight was won" (GUI_PLAN.md §7.1).

---

## 7. Recommendations for Fight Night Screen

### 7.1 What data to show (per beat)
For each beat (in chronological order, replayed at player-chosen speed):
- **Round number + beat number** — small mono-spaced timestamp
  ("R2 · B7 / 18").
- **Phase indicator** — icon or color chip for standing / clinch / cage /
  ground_top / ground_bottom / scramble. Maps to the heatmap's "where on
  the canvas" axis.
- **Action prose** — needs to be generated. Two options:
  - (a) Pre-generate at fight-resolution time using a richer template
    system (per action_type × phase × outcome × momentum_band) and
    store in `commentary_segments.text` (one row per beat, segment_type
    could be `'beat'` — distinct from `'play_by_play'` and `'highlight'`).
  - (b) Generate on the fly in the UI from the structured beat data
    using `voice.py` (per CONVENTIONS §17.2 the Fight Night screen is
    exempt from the snapshot-cache rule and may read live tables and
    apply voice on the fly).
  - **Recommendation: (a)** — persisted prose is replayable (the
    Fighter Profile "Replay fight" deep-link needs the same data),
    testable, and consistent with the existing pattern. Generate one
    `commentary_segments` row per beat with `segment_type='beat'`,
    plus the existing `'highlight'` rows for the 3-14 key moments
    (the UI can show highlights with a different visual weight).
- **Damage delta** — small bar / chip showing `damage_dealt` (numeric
  is OK — damage is game-state, not voice-gated).
- **Momentum delta** — the signature visual. A momentum ring or bar
  that swings toward A or B as `cum_momentum` shifts. Knockdowns (+
  80) and near_finishes (+60) should produce a visible "lurch."
- **Gas gauges** — both fighters' end-of-round `gas_remaining` from
  `fight_rounds`, updated per-beat (interpolate linearly between round
  start/end for the in-between beats, or just update per-round).

### 7.2 Per-round aggregation view
At the end of each round, show the `fight_rounds` row as a mini-
scorecard:
- Round winner (voice phrase: "Reed takes round 2 on all three cards"
  / "Split round — slight edge to Vale")
- Damage dealt by each fighter (numeric)
- Strikes landed, takedowns, knockdowns, control time (numeric)
- End-of-round gas (numeric or voice phrase: "fresh" / "winded" /
  "running on fumes")
- Cumulative momentum (signed number or bar)

### 7.3 Post-fight recap view
When the fight ends (the engine returns from `resolve_next_fight`):
- **Result card** — winner, result_type (voice phrase: "KO/TKO",
  "submission", "decision (unanimous)", "doctor stoppage"), round,
  finish time. The `_format_fight_news` + `_format_fight_commentary`
  helpers in fight_engine.py already produce these phrases.
- **Performance rating + fan reaction rating** — both numeric 60-95,
  OK to display (game-state).
- **Key moments feed** — the 3-14 `highlight` commentary_segments in
  chronological order, each with the importance-coded visual weight.
- **Fighter stat changes** — win/loss added to record, ELO rating
  delta, streak change, title change indicator (if applicable), new
  injury indicator (if applicable).
- **News item preview** — the `generate_fight_news` headline + body.
- **Punditry matchup_analysis** — the pre-fight prediction vs the
  actual result (the "were the pundits right?" panel).
- **If this was the last fight on the card: show_rating panel** —
  the 5 axes + descriptor + commentator bonus.

### 7.4 How to present play-by-play
Per GUI_PLAN §7.1 + UI_REDESIGN_VISUAL_PLAN §7.7, the screen has a
fixed 4-zone grid (no scroll):
- **Zone A — Cage Heatmap (top-left, 8-col)**: top-down octagon, heat
  accumulates per beat. Derived from `phase` + `initiator_fighter_id`.
  Championship skin overlay when `fights.is_title_fight=1`.
- **Zone B — Damage Silhouettes (top-right, 4-col, 2 stacked)**: head
  / body / legs / arms glow on impact, persists as bruising. Derived
  from `damage_dealt` + `phase` (standing = head/body; leg_kick =
  legs; ground_top = head from above).
- **Zone C — Commentary Feed (bottom-left, 8-col)**: scrollable,
  serif typography (`commentary_fight` font per UI_REDESIGN_VISUAL_PLAN
  §"Type Scale"). Beat timestamp + action prose + pundit interjection
  + memory bubble. Cap visible beats at 200.
- **Zone D — Pundit Panel + Memory Bubble (bottom-right, 4-col)**:
  2-3 named pundits with mood indicator + last interjection summary.
  Memory bubble = resurfaced storyline context (rivalry history,
  previous fight result, career milestone). Memory system:
  `fighter_memory_links` table (Task 6.7 brief calls for +2 columns:
  `context_note`, `last_surfaced_at`).

**Performance budget** (GUI_PLAN §7.1): 60fps on mid-range laptop.
Heatmap redraw = changed zones only. Damage silhouettes = pre-rendered
sprite sheets. Commentary feed = append-only. Pundit interjections =
pre-generated at fight resolution time, stored in `commentary_segments`,
revealed in sequence.

### 7.5 Transport bar (top of screen)
Per UI_REDESIGN_VISUAL_PLAN §"Stolen from ESPN" — the horizontal
scorestrip pattern becomes the Fight Night transport bar: beat counter
+ round clock + speed controls (1x / 2x / 4x / pause / skip to finish
/ exit fight). The "Exit Fight" + "Skip to Finish" controls use
`display_small` (Oswald) typography per UI_REDESIGN_VISUAL_PLAN §10.

### 7.6 Three-phase structure (per GUI_PLAN §7.1)
1. **Pre-Fight Build-Up** (~15-30s at 1x): Tale of Tape
   (`get_fight_tale_of_tape`), Pundit Predictions
   (`matchup_analyses`), Memory Setup (rivalry context from
   `get_fight_fan_pulse`), Storyline Context.
2. **Live Fight** (variable, 2-10min at 1x): the 4 live zones,
   replaying beats from `fight_beats` + `fight_rounds` +
   `commentary_segments`.
3. **Post-Fight Recap** (~20-40s at 1x): Result card, Pundit grades,
   Final heatmap (annotated with decisive moments), Final damage
   silhouettes (with medical suspension indicator if injury created),
   Memory creation, News generation, Storyline hooks.

### 7.7 What makes it a showcase feature
- **The dopamine loop closes here.** The player spent 20 minutes
  matchmaking, building the card, hyping the fight. The Fight Night
  screen is the payoff — the moment the booked matchup becomes a
  story. If the screen is flat (a text log), the loop doesn't close
  and the player loses interest. If the screen is visceral (heatmap
  glowing, momentum swinging, pundits arguing, memories surfacing),
  the player wants to book the next card immediately.
- **Replayability.** Every fight produces 36-140 beats of structured
  data + 3-14 highlight prose lines + 1 news item + 1 matchup analysis
  + (potentially) 1 title change + (potentially) 1 injury + 1 show
  rating (if last fight). The Fighter Profile "Replay fight" deep-link
  (NAV_BUTTONS_AUDIT §2.4 row 11) needs the same Fight Night screen
  in read-only mode. So one screen serves two flows: live resolution
  + historical replay.
- **Voice payoff.** The voice layer (`voice.py`) and the LONG prose
  variant system (UI_REDESIGN_VISUAL_PLAN §"Type Scale") were
  designed for this screen. Every beat needs unique prose — the
  system's 8-variant minimum per template (CONVENTIONS §14) is most
  visible here. The `commentary_fight` serif font (Source Serif Pro
  17px) is the only place pure prose dominates the screen.

### 7.8 Voice considerations
- **No raw attribute numbers in prose.** Per §14, the commentary says
  "Reed lands a heavy left hook" not "Reed's punch_power 78 beat
  Vale's chin 42". The structured `damage_dealt` number is OK to
  display as a chip (game-state), but the prose must be voice-only.
- **8+ variants per template.** The existing 7 templates need to
  expand to 8+ variants each, with variety driven by action_type,
  phase, momentum_band, and (eventually) commentator personality
  (`staff.pundit_bias`).
- **Pundit interjections.** Named-pundit interjection generator was
  explicitly deferred from Task 6.0 to Task 6.7
  (`services/punditry_svc.py` comment). This is the task that builds
  it. The interjection should fire on dramatic beats (knockdown,
  near_finish, big momentum swing) and use the pundit's
  `pundit_bias` JSON to flavor the line.
- **Memory bubble voice.** When a memory surfaces (rivalry history,
  previous fight), the prose is italic serif on a gold-tinted card
  with paper texture (`paper_grain.png`). Reads as "old newspaper
  clipping" — distinct from live commentary.

### 7.9 Reward considerations
- **Performance rating + fan reaction rating** — both visible on the
  result card. The player's matchmaking choices (card_slot, title
  fight, marketability) directly affect these. Higher ratings →
  higher morale boosts for the winner → higher marketability → bigger
  future cards.
- **Show rating descriptor** — the voice phrase ("an instant classic
  that fans will talk about for years") is the dopamine line. The
  player remembers great cards by their descriptor.
- **Title changes** — if `fights.is_title_fight=1` and the belt
  changes hands, the championship skin overlay activates (gold border
  on all 4 zones, belt graphic, "TITLE FIGHT" badge) and the
  post-fight recap shows the title change as a hero moment.
- **Injury / suspension stories** — if the fight produced an injury
  (especially a severe one — ACL tear, concussion), the post-fight
  recap surfaces it. The "9-month comeback" narrative arc is the
  downside risk that balances the upside of a title win.
- **News feed integration** — the `generate_fight_news` item appears
  in The Wire immediately. The player can click through from the
  news item back to the Fight Night replay (the
  `navigate('fight_resolution', {fight_id})` deep-link).
- **Memory creation** — the post-fight recap should write a
  `fighter_memory_links` row for both fighters, so this fight can
  resurface in future Fight Night screens (the "echoes" system per
  `src/interpretation/echoes_engine.py`).

### 7.10 Implementation order (suggested)
1. **Bridge + API methods.** Add to `app_web.py:Api`:
   - `resolve_next_fight(promotion_id=None)` — wraps
     `services.fight_engine.resolve_next_fight`. Returns
     `{ok, fight_id, event_id, was_cancelled}`. The UI polls or
     long-polls for "is there a next fight on my next due event?"
   - `get_fight_night_data(fight_id)` — returns the full play-by-play
     payload: fight metadata + both fighters + all `fight_beats` rows
     (with initiator/target names) + all `fight_rounds` rows + all
     `commentary_segments` rows for this fight + the
     `matchup_analyses` row + the result card data (winner, result_type,
     finish_round, finish_time, performance_rating, fan_reaction_rating)
     + injury rows (if any) + title change flag.
   - `get_event_card_for_resolution(event_id)` — returns the event's
     fights in card_slot order with their resolution status, so the
     UI can show "Fight 1 of 5" and a card-progress bar.
   - `get_event_show_rating(event_id)` — returns the `show_ratings`
     row (None if the event isn't completed yet).
2. **Per-beat commentary system.** Expand `_BEAT_COMMENTARY_TEMPLATES`
   from 7 outcomes to a richer system: `action_type × phase × outcome
   × momentum_band` matrix, each with 8+ voice variants. Generate
   one `commentary_segments` row per beat (segment_type='beat') at
   fight-resolution time. Keep the existing 3-14 highlight rows
   (segment_type='highlight') as the "key moments" feed.
3. **JS module.** New `src/web/js/fight_night.js` + `fight_night.css`.
   Three phases (pre-fight, live, recap). 4-zone grid. Transport bar.
   Memory bubble. Pundit panel. Championship skin overlay.
4. **Nav wiring.** Add `fight_resolution` case to `app.js:navigate()`.
   Support `params.fight_id` for the replay deep-link, and
   `params.event_id` for the live-resolution flow.
5. **Auto-resolution hook for the player's promotion.** Decide
   whether the player's events should auto-resolve on `advance_day`
   (matching rival behavior) or stay manual-only. The current code
   explicitly excludes the player from auto-resolution; the Fight
   Night screen is the manual trigger. Recommendation: keep manual —
   the player wants to *watch* fights, not have them resolve in the
   background. Add a "Fight Tonight?" indicator on the Dashboard
   when `events.event_date <= current_date` AND the event has
   unresolved fights.
6. **Memory system.** Task 6.7 brief calls for +2 columns on
   `fighter_memory_links` (`context_note`, `last_surfaced_at`). The
   echoes engine (`src/interpretation/echoes_engine.py`) needs to
   surface a relevant memory at the start of each Fight Night
   (rivalry history, previous meeting, career milestone).
7. **Pundit interjection generator.** The deferred piece from
   `punditry_svc.py`. Reads `staff.pundit_bias` JSON. Fires on
   knockdown / near_finish / big_momentum_swing beats.

---

## 8. Open Questions (for the supervisor)

1. **Auto-resolve player events on advance_day, or keep manual?**
   Today: manual only (the player clicks "Resolve Fight" in the
   legacy Tkinter UI). Rival promotions auto-resolve. The web UI has
   no button. Recommendation: keep manual + add a Dashboard
   indicator when a fight is "due tonight" so the player knows to
   navigate to Fight Night.
2. **Pre-generate per-beat prose at resolution time (option a) or
   generate on the fly in the UI (option b)?** Recommendation: (a) —
   persisted prose is replayable and consistent with the existing
   `commentary_segments` pattern. Adds ~100-200 rows per fight to
   the table (pruned after 365 days per `REPLAN_RESET.md` §468).
3. **Championship skin overlay — full 4-color palette swap or just
   border + badge?** UI_REDESIGN_VISUAL_PLAN §2.4 recommends the
   4-color overlay (gold leaf heatmap border, champion/challenger
   corner colors, belt graphic, "TITLE FIGHT" badge) — minimal extra
   design work.
4. **Memory bubble — does it surface automatically or only on user
   hover/click?** GUI_PLAN §7.1 implies automatic ("memories that
   resurface at the perfect moment"). The echoes engine needs a
   "should this memory surface now?" check.
5. **Skip-to-Finish control — does it just jump to the recap, or
   does it fast-play through the remaining beats at 10x?**
   Recommendation: jump to recap (the player can always replay
   later). The recap shows the result card + key moments feed, so
   no information is lost.
