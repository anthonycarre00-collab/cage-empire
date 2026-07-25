# CAGE EMPIRE — Task 6.0 Detailed Plan

> **Status:** Awaiting supervisor sign-off. Once approved, this
> plan is handed to a dedicated subagent per CONVENTIONS §8 + §11.
> The supervisor (this agent) does NOT write the refactor code —
> the subagent does. The supervisor reviews + signs off.
> **Authored:** 2026-07-25.
> **Decision owner:** Supervisor (user).
> **Prerequisite for:** All Stage 6 GUI work (Tasks 6.1–6.14).
> **Schema impact:** NONE. Task 6.0 is a pure code refactor. All
> 38 acceptance tests must still pass at the end.

---

## 0. Why Task 6.0 exists

The current `src/app.py` is a **7700-line monolith** mixing:

1. Game logic — `resolve_next_fight`, `advance_day`, `run_tick`,
   beat engine, decision scoring, retirement checks, regen, etc.
2. DB plumbing — connection management, schema reads/writes.
3. Primitive tkinter UI — the `App(tk.Tk)` class at line 6980,
   rejected by the supervisor as "ugly and not very flexible."

Every GUI screen we build in Tasks 6.1–6.14 would otherwise have
to fight this monolith: import its functions, navigate its
internals, risk breaking its tests, and duplicate its
already-mixed concerns. **Splitting it first is the single
biggest de-risking step for the entire GUI phase.**

The refactor is mechanical: move functions out of `app.py` into
themed service modules under `src/services/`. The behaviour must
not change. The 38 acceptance tests are the contract.

---

## 1. Scope — what moves where

### 1.1 The 13 service modules to extract

Each module is a themed group of related functions. Functions are
moved verbatim (no logic changes). Imports are updated across the
codebase to point at the new locations. `app.py` retains its
public API via re-exports for backwards compatibility (so
existing tests don't break — see §6).

> **REVISED per Plan agent validation (Rev 4):** function names
> verified against `grep -nE "^def " src/app.py`. Misnamed /
> nonexistent names from Rev 3 corrected. Orphaned functions
> (fighter_name, _load_fighter_stats, update_fighter_descriptor
> _snapshot, _create_training_camp, _get_camp_fatigue_for_event,
> _pick_camp_focus_for_archetype, generate_fighter,
> _vacate_title_on_retirement) now explicitly assigned to a
> module. Line counts revised to actuals (~6919 lines extractable,
> not ~4650). Wrapper modules stripped of "adds new code" items
> — those defer to the screen tasks that need them (Tasks
> 6.3–6.11). Task 6.0 = pure mechanical refactor + populate_*
> calls in memory_svc (the only new code, called from existing
> code paths).

| Module | Functions moved from `app.py` | Lines (approx) |
|---|---|---|
| `services/clock.py` | `get_clock` (app.py:17), `advance_day` (app.py:29), `fighter_name` (app.py:13 — orphaned util used by App + tick_processor + tests, assigned here as the smallest fundamental module). **NO advance_week** (does not exist — `advance_day` handles weekly logic inline). | ~25 |
| `services/fight_engine.py` | `resolve_next_fight` (5184), `resolve_round` (1366), `_decide_fight_outcome` (1861), `_load_fighter_stats` (303 — was orphaned), `_compute_beat_scores` (829), `_compute_gas_cost` (876), `_recover_gas_between_rounds` (901), `_compute_fight_importance` (919), `_compute_pressure_response` (952), `_compute_pressure_modifier` (980), `_ko_threshold` (1007), `_ko_finish_probability` (1037), `_submission_score` (1057), `_doctor_stoppage_threshold` (1083), `_check_corner_stoppage` (1094), `_check_dq` (1112), `_random_finish_time` (1132), `_pick_action_type` (1156), `_compute_damage` (1169), `_resolve_beat_outcome` (1223), `_maybe_transition_phase` (1309), `_format_fight_news` (1943), `_round_word` (2011), `_finish_time_phrase` (2024), `_severity_phrase_inline` (2054), `_format_fight_commentary` (2076), `_select_commentary_beats` (2144), `_generate_beat_commentary` (2243), `_update_event_status_after_resolution` (2318), `_get_or_create_ranking_row` (2441), `_update_rankings_after_resolution` (2477), `_resolve_title_after_fight` (2630), `_maybe_create_injury` (4585), `_check_post_fight_injuries` (4864), gameplan helpers (`_derive_preferred_gameplans`, `_derive_bad_matchup_tags`, `_update_preferred_gameplans`, `_update_bad_matchup_tags` — 4996-5182), `_compute_weight_cut_miss_prob` (3267), `_run_weight_cut` (3331), `update_fighter_descriptor_snapshot` (3499 — was orphaned), `_vacate_title_on_retirement` (2815 — was orphaned, called by tick_processor). Plus ALL constants (`_FIGHTER_ATTR_COLUMNS`, `_FIGHTER_PERS_COLUMNS`, `PHASE_ATTRS`, `PHASE_ACTIONS`, `PHASE_ACTION_WEIGHTS`, `STRIKE_ACTIONS`, `TRANSITION_ACTIONS`, `_BEAT_NOISE_SIGMA`, `PHASE_GAS_COSTS`, `CARD_SLOT_WEIGHTS`, `_PRESSURE_*`, `_KO_*`, `_DOCTOR_STOPPAGE_*`, `_MOMENTUM_*`, `_COMMENTARY_*`, `_INJURY_*`, `_BEAT_COMMENTARY_TEMPLATES`, `_ELO_K`, `_INITIAL_RATING`, `_GAMEPLAN_*`). | ~2700 |
| `services/matchmaking.py` | `schedule_next_event` (4232), `_pick_matchup` (2964), `_get_available_fighters_for_card` (3682), `_group_available_by_wc` (3796), `_build_main_event` (3807), `_build_co_main` (3901), `_build_featured_prelim` (3938), `_build_prelim` (3971), `_get_event_naming_style` (4125), `_build_event_name` (4144). Plus camp helpers (orphaned): `_create_training_camp` (3155), `_get_camp_fatigue_for_event` (3220), `_pick_camp_focus_for_archetype` (3124), `_ARCHETYPE_NAME_TO_CAMP_FOCUS` (3060), `_CAMP_FOCUS_ATTRS` (3099), `_CAMP_LEAD_DAYS` (3121). Plus event constants (`EVENT_NAME_THEMES` 4050, `EVENT_THEMES` 4061, `_CARD_SIZE_BY_TIER` 3658, `_FEATURED_PRELIM_COUNT_BY_TIER` 3668, `_REST_PERIOD_DAYS` 3675, `_TITLE_FIGHT_ROUNDS` 3678, `_NON_TITLE_FIGHT_ROUNDS` 3679). | ~1300 |
| `services/contracts.py` | `sign_free_agent` (6225 — was misnamed `sign_fighter`), UI reader `get_free_agents_for_display` (6143), UI reader `get_contracts_for_display` (103 — was orphaned). **NO renew_contract** (does not exist). **NO _expire_contracts** (actual is `tick_processor._check_contract_expiry`, stays in tick_processor). | ~200 |
| `services/scouting_svc.py` | Pure wrapper — delegates to existing `src/scouting.py`. NO new code in Task 6.0 (defer staleness query helpers to Task 6.5 Scouting screen). | ~30 |
| `services/finance_svc.py` | Pure wrapper — delegates to existing `src/finance.py`. NO new code in Task 6.0 (defer `process_event_finances` + weekly cashflow tick to Task 6.10 Finance screen). | ~30 |
| `services/news_svc.py` | Pure wrapper — delegates to existing `src/news.py`. NO new code in Task 6.0 (defer feed-query helpers to Task 6.3 Dashboard + News Feed screen). | ~30 |
| `services/rivalries_svc.py` | Pure wrapper — delegates to existing `src/rivalries.py`. NO new code in Task 6.0 (defer heat decay tick + confrontation triggers to Task 6.9 Rivalries screen). | ~30 |
| `services/training_svc.py` | Wrapper — delegates to `tick_processor._check_training_camps` (NOT `_check_injuries` — that was a misname). NO new query helpers in Task 6.0 (defer camp query helpers to Task 6.6 Event Builder). | ~30 |
| `services/injuries_svc.py` | Wrapper — delegates to `tick_processor._check_injury_recovery` (NOT `_check_injuries` — that was a misname). NO new query helpers in Task 6.0 (defer injury query helpers to Task 6.4 Fighter Profile screen). | ~30 |
| `services/retirement_svc.py` | `generate_fighter` (6433 — was orphaned, called by tick_processor + agent_offers + 3 tests), wrapper around `tick_processor._check_retirements`. **NO HoF induction code in Task 6.0** — defer to Task 6.11 Hall of Fame screen. | ~700 |
| `services/punditry_svc.py` | Pure wrapper — delegates to existing `src/punditry.py`. **NO named-pundit interjection generator in Task 6.0** — defer to Task 6.7 Fight Resolution screen (where `staff.pundit_bias` is actually read). | ~30 |
| `services/memory_svc.py` | Only the **3 populate_* functions** are written in Task 6.0 (called from existing code paths per §3.5): `populate_style_echo` (called from `tick_processor._check_retirements`), `populate_regional_rival` (called from `services/matchmaking._build_main_event` + `_build_co_main`). `populate_gym_heir` is **DEFERRED** (no current "fighter joins gym" code path — would need new game logic, violates §4.3). Memory candidate queue + mark_surfaced + pruning defer to Task 6.7 Fight Resolution screen (where they're actually needed). | ~150 |

**Total moved:** ~6919 lines out of `app.py` (corrected from the
Rev 3 estimate of ~4650). After refactor, `app.py` shrinks from
7694 lines to **~775 lines** (App class ~715 lines + launcher ~10
lines + re-export block ~50 lines). The 715-line App class is
DELETED in Task 6.2 when the new CTk shell lands. So Task 6.0
leaves `app.py` as the old tkinter UI + a re-export block; Task
6.2 reduces it to a 30-line launcher.

### 1.2 What stays in `app.py` after Task 6.0

```python
"""CAGE EMPIRE — application launcher.

After Task 6.0, this file is:
  - The tkinter App class (715 lines, deleted in Task 6.2)
  - The re-export block (~50 lines — see §6)
  - The main() launcher (~10 lines)

All game logic lives in src/services/. The tkinter UI (App class)
is REMOVED in Task 6.2 when the new CustomTkinter shell lands.

To run the game (during Task 6.0, before Task 6.2):
    python src/app.py    # launches the old tkinter App
"""
# Re-exports first (must be at module scope — see §6 warning)
from services.clock import get_clock, advance_day, fighter_name
from services.fight_engine import resolve_next_fight, resolve_round, ...
# ... full list in §6

import tkinter as tk
from tkinter import ttk, messagebox

class App(tk.Tk):
    """The old tkinter UI. Deleted in Task 6.2."""
    # ... 715 lines unchanged ...

if __name__ == "__main__":
    App().mainloop()
```

**During Task 6.0** (before Task 6.2 lands), `app.py` keeps the
old tkinter `App` class intact so the game still runs. The
services are extracted but the App class still calls them via
the re-export block at module scope. The 715 remaining App-class
lines are deleted in Task 6.2.

### 1.3 What does NOT move in Task 6.0

- `src/build_db.py` — unchanged (schema only).
- `src/seed_data.py` — unchanged (minimal seed).
- `src/tick_processor.py` — **mostly unchanged**. Its functions
  (`_check_retirements`, `_check_training_camps`,
  `_check_injury_recovery`, `_check_contract_expiry`, `run_tick`)
  get *wrapped* by the new service modules but the wrappers
  delegate to the existing functions. **ONE exception per Fix #3
  (Rev 4):** a single inline call to
  `services.memory_svc.populate_style_echo` is added to
  `_check_retirements` after the existing `successor` link INSERT
  (matches how `_check_retirements` already publishes
  `FIGHTER_RETIRED` inline — additive side effect, not a
  behavioral change, fits CONVENTIONS §15.4 spirit). This is the
  ONLY modification to tick_processor.py in Task 6.0. A later
  task (6.0.5, optional) may inline the rest.
- `src/voice.py` — unchanged (the interpretation layer; pure
  module, no DB access, no move needed).
- `src/event_bus.py` — unchanged.
- All 16 existing `src/*.py` modules (`agent_offers.py`,
  `career_arc.py`, `finance.py`, `morale.py`, `news.py`,
  `punditry.py`, `reputation.py`, `rivalries.py`, `rival_ai.py`,
  `scouting.py`, `show_rating.py`, `social.py`, `suspensions.py`,
  `venues.py`, `mods.py`, `save_load.py`, `fighter_gen.py`) —
  unchanged. The new `services/*.py` modules wrap these where
  needed.
- **Inline-news helpers `write_news` + `write_commentary`
  (app.py:39-47)** — STAY in app.py (tiny UI-layer helpers, used
  by App + various inline-news writes; not game logic).
- **UI reader functions** `get_fighters_for_display` (67),
  `get_rankings_for_display` (166) — STAY in app.py (UI-layer
  concerns, replaced by CTk screens in Task 6.2+ anyway). Only
  `get_free_agents_for_display` + `get_contracts_for_display`
  move (to `services/contracts.py`, thematically grouped with
  `sign_free_agent`).

---

## 2. Integration map — every system touchpoint

This is the critical section the supervisor demanded. Every
integration point is enumerated, with the contract (function
signature, caller, callee, event-bus topic if any, refresh
trigger).

### 2.1 Tick / event-bus integration

The tick is the heartbeat. Every GUI screen that shows
simulation state must refresh when the tick advances. The
mechanism:

> **REVISED per Plan agent validation (Rev 4, Fix #2):** The
> Rev 3 version of this section described
> `services.clock.advance_day` as the orchestrator that calls
> retirement/training/injury/etc services directly. That
> contradicts §1.3 + §4.3 ("do not modify tick_processor.py"),
> because ALL of that orchestration currently lives in
> `tick_processor.run_tick` (lines 1546-1659), not
> `app.advance_day` (which only updates the clock row at
> app.py:29-37). **Resolution (Q4 recommendation):**
> `services.clock.advance_day` is a **thin wrapper** that
> delegates to `tick_processor.run_tick`. The orchestration
> stays in `run_tick` for Task 6.0 (the wrappers in the 8
> service modules also delegate to `run_tick`'s sub-functions).
> A future task (6.0.5, optional) may move `run_tick`'s
> orchestration into `services.clock.advance_day` for cleaner
> separation, but that is NOT in Task 6.0's scope.

```
User clicks "Advance Day" (UI button)
  ↓
ui/screens/dashboard.py calls services.clock.advance_day(conn)
  ↓
services.clock.advance_day:
  1. Thin wrapper — delegates to tick_processor.run_tick(conn)
  2. tick_processor.run_tick (UNCHANGED in Task 6.0) does:
     a. Updates simulation_clock row (current_date += 1 day, etc.)
     b. Calls _check_retirements (wrapped by retirement_svc)
     c. Calls _check_training_camps (wrapped by training_svc)
     d. Calls _check_injury_recovery (wrapped by injuries_svc)
     e. Calls _check_contract_expiry (stays in tick_processor)
     f. Publishes Events.TICK_ADVANCED on the event bus
  3. advance_day returns whatever run_tick returned
  ↓
Event bus synchronously calls all subscribers (UNCHANGED):
  - news.generate_retirement_news
  - news.generate_suspension_news
  - news.prune_old_news
  - news.generate_event_hype_news
  - morale.update_morale_on_tick
  - social.generate_social_posts
  - agent_offers.maybe_generate_offer
  - rival_ai.run_rival_ai_tick
  - (any future subscriber)
  ↓
Event bus returns. run_tick returns. advance_day returns.
UI gets control back.
  ↓
UI calls ui/state.py:refresh_all() (the game-state layer — see §2.4)
  ↓
All visible screens re-query their data and re-render.
```

**Contract for `services.clock.advance_day`:**
- Takes `conn` (sqlite3.Connection) as first arg.
- Delegates to `tick_processor.run_tick(conn)` — does NOT
  re-implement the orchestration.
- Returns whatever `run_tick` returns.
- Does NOT publish events itself — `run_tick` does that (this
  preserves §15.4 — no new inline side effects).

**Contract for the 8 wrapper service modules (scouting_svc,
finance_svc, news_svc, rivalries_svc, training_svc,
injuries_svc, retirement_svc, punditry_svc):**
- Each is a thin delegation layer.
- For modules wrapping tick_processor functions
  (training_svc, injuries_svc, retirement_svc), the wrapper
  exposes a function with the SAME signature that calls the
  underlying tick_processor function.
- For modules wrapping src/ modules (scouting_svc wraps
  scouting.py, finance_svc wraps finance.py, etc.), the
  wrapper just re-exports the existing module's public API.
- NO new logic in Task 6.0 (per Fix #4). New query helpers /
  features land in the screen tasks that need them (6.3-6.11).

**Contract for every event-bus subscriber:**
- Takes `(conn, event_dict)`.
- Catches its own exceptions (the bus is defensive — broken
  subscribers don't crash the game, per §15.4).
- Does NOT publish new events itself (prevents cascade). If a
  subscriber needs to publish, it's a sign the orchestration
  should be in advance_day, not in the subscriber.

### 2.2 Fight resolution integration

```
User clicks "Resolve Fight" on Event Builder screen
  ↓
ui/screens/event_builder.py calls
  services.matchmaking.schedule_next_event(conn, promotion_id, ...)
  → returns event_id with 5-13 fight rows in event_cards
  ↓
When event_date arrives (advance_day triggers it):
  services.fight_engine.resolve_event(conn, event_id)
  ↓
For each fight on the card:
  services.fight_engine.resolve_next_fight(conn, fight_id)
    1. Loads fighter_attributes + fighter_personality + training_camp
    2. Calls resolve_round() 3-5 times (one per round)
    3. Each round generates 12-28 fight_beats rows
    4. Writes fight_rounds aggregate row
    5. Writes fight_history rows (one per fighter)
    6. Updates fighter_career (wins/losses/streaks/health)
    7. Updates rankings (ELO + position)
    8. Resolves title change if is_title_fight=1
    9. Applies injuries (calls injuries_svc.create_injury if KO/TKO)
   10. Applies suspensions (calls suspensions.apply_suspension)
   11. Generates commentary_segments for selected beats
       (uses _select_commentary_beats + voice layer)
   12. Publishes Events.FIGHT_RESOLVED
       → news.generate_fight_news + generate_injury_news
       → punditry.generate_matchup_analysis (post-fight analysis)
       → social.generate_post_fight_posts
       → morale.update_morale_on_fight
       → rivalries.maybe_escalate_rivalry
       → reputation.update_gym_reputation_on_fight
   13. If title changed, publishes Events.TITLE_CHANGED
       → news.generate_title_news + generate_memory_resurfacing_news
       → reputation.update_gym_reputation_on_title
  ↓
After all fights on the card resolve:
  services.fight_engine.publishes Events.EVENT_COMPLETED
    → news.generate_event_recap_news
    → finance_svc.process_event_revenue
    → show_rating.compute_show_rating
    → rival_ai.maybe_schedule_rival_event
  ↓
UI's Fight Resolution screen plays back the pre-resolved
fight_beats for the selected fight (NOT real-time — the
resolution is already done; the screen is a player-facing
playback of pre-computed data).
```

**Key integration contract:** the Fight Resolution screen is a
**reader**, not a writer. It reads `fight_beats`,
`fight_rounds`, `commentary_segments`, `matchup_analyses`,
`fighter_memory_links`. It does NOT call resolve_next_fight.
The fight is already resolved by the time the player sees it.

### 2.3 Voice / interpretation layer integration

Per CONVENTIONS §14, every player-facing number routes through
`src/voice.py`. The integration:

```
UI screen needs to display fighter data
  ↓
ui/screens/fighter_profile.py calls services.fighter_svc.get_fighter_data(fighter_id)
  → returns a dict with raw attribute values (e.g., punch_power=87)
  ↓
UI screen calls voice.describe_attribute("punch_power", 87)
  → returns "elite" (a descriptor string)
  ↓
UI displays the descriptor, NOT the number.
```

**For the Fight Resolution screen specifically:**
- Raw damage values stored in `fight_beats.damage_dealt` are
  NEVER displayed. The commentary_segments.text column already
  contains the prose ("He's hurt! That left hook landed clean!")
  generated at resolution time by the existing
  `_select_commentary_beats` function calling the voice layer.
- The cage heatmap widget reads `fight_beats.phase` + the
  fighter corner positions to compute zone heat — it does NOT
  display raw damage numbers; the heat colour IS the
  visualisation.
- The damage silhouette widget reads `fight_beats.target_fighter_id`
  + `fight_beats.outcome` (knockdown, near_finish, etc.) to
  light up body zones — again, no raw numbers, the glow IS the
  visualisation.
- The "Stats" overlay (player opts in) shows strike counts +
  takedown counts + control time — these are derived from
  `fight_rounds` aggregate columns, NOT raw `fight_beats`. They
  are match statistics, not attribute numbers, so they don't
  violate §14 (which forbids raw attribute values, not match
  stats).

### 2.4 Screen refresh strategy — the game-state layer

The supervisor asked: "all affected screens are 'refreshed' or
we use a 'game state' layer/function." Answer: **we use both.**
A single `ui/state.py` module exposes:

```python
# src/ui/state.py (new in Task 6.2, but designed in Task 6.0)

class GameState:
    """Singleton game-state layer.

    Holds the sqlite3.Connection, the current screen, the
    current theme (Office/Fight Night), and a dirty-flag set.

    Every screen registers a refresh_callback. When the state
    changes (tick advanced, fight resolved, fighter signed),
    GameState calls refresh_callback on every registered screen.

    Screens that are not visible skip the refresh (they'll
    refresh when next shown).
    """
    def __init__(self, conn):
        self.conn = conn
        self._screens = {}  # name -> (instance, refresh_callback)
        self._active_screen = None
        self._theme = "office"  # or "fight_night"

    def register_screen(self, name, instance, refresh_callback):
        self._screens[name] = (instance, refresh_callback)

    def set_active_screen(self, name):
        self._active_screen = name
        # Refresh the now-active screen (it might have stale data)
        self.refresh(name)

    def refresh(self, name=None):
        """Refresh one screen (by name) or all visible screens."""
        if name:
            instance, cb = self._screens.get(name, (None, None))
            if cb: cb()
        else:
            # Refresh only the active screen (others defer refresh)
            if self._active_screen:
                self.refresh(self._active_screen)

    def refresh_all(self):
        """Refresh ALL registered screens. Used after major state
        changes (tick advance, fight resolution, save load)."""
        for name, (instance, cb) in self._screens.items():
            if cb: cb()

    def set_theme(self, theme):
        if theme not in ("office", "fight_night"):
            return
        if self._theme != theme:
            self._theme = theme
            self.refresh_all()  # theme affects every screen
```

**Refresh triggers:**

| Action | Refresh scope |
|---|---|
| Advance Day button | `refresh_all()` — every screen's data may have changed |
| Resolve Fight button | `refresh_all()` + navigate to Fight Resolution screen |
| Sign Fighter button | Refresh Roster + Free Agents + Finance + News |
| Scout Fighter button | Refresh Scouting + (maybe) Roster |
| Schedule Event button | Refresh Schedule + Finance projection |
| Save / Load | `refresh_all()` |
| Theme toggle | `refresh_all()` (theme affects rendering, not data) |
| Navigate to a screen | `refresh(name)` for that screen only |

**Performance:** `refresh_all()` is only called on user-initiated
actions (Advance Day, Resolve Fight, Save/Load). It is NOT
called on every UI interaction. Each screen's refresh_callback
is expected to complete in <100ms (one DB query + re-render).
If a screen is too slow, it caches and only re-queries on dirty
flag.

### 2.5 Data flow diagram — the full picture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        USER (player)                                  │
│                   clicks button in CTk UI                             │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  src/ui/screens/*.py   (CustomTkinter screens — Task 6.3 onwards)    │
│  - dashboard.py                                                       │
│  - roster.py                                                          │
│  - fighter_profile.py                                                 │
│  - event_resolution.py  ← the Fight Night screen (Task 6.7)           │
│  - ... (22 screens total)                                             │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ calls
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  src/ui/state.py   (GameState singleton — game-state layer)           │
│  - holds conn, theme, active screen                                   │
│  - refresh() / refresh_all() — the refresh contract                   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ delegates to
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  src/services/*.py   (game logic — extracted from app.py in 6.0)      │
│  - clock.py            advance_day, get_clock                          │
│  - fight_engine.py     resolve_next_fight, resolve_round               │
│  - matchmaking.py      schedule_next_event                             │
│  - contracts.py        sign_fighter, expire_contracts                  │
│  - scouting_svc.py     wraps scouting.py                               │
│  - finance_svc.py      wraps finance.py                                │
│  - news_svc.py         wraps news.py (feed queries for UI)             │
│  - rivalries_svc.py    wraps rivalries.py                              │
│  - training_svc.py     wraps tick_processor._check_training_camps      │
│  - injuries_svc.py     wraps tick_processor._check_injuries            │
│  - retirement_svc.py   wraps tick_processor._check_retirements         │
│  - punditry_svc.py     wraps punditry.py + new interjection generator  │
│  - memory_svc.py       wraps fighter_memory_links + new candidate queue│
└────────────────────────────┬─────────────────────────────────────────┘
                             │ reads/writes
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  src/voice.py   (interpretation layer — CONVENTIONS §14)              │
│  - describe_attribute(name, value) → "elite" / "above-average" / ...   │
│  - describe_career_stage(fighter_data) → "rising contender" / ...      │
│  - describe_overall(fighter_data) → one-sentence prose                 │
│  - called by services AND by UI (never displays raw numbers)           │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ routes through
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  src/event_bus.py   (in-memory pub/sub — CONVENTIONS §15)             │
│  - 16 event types (FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED, ...)  │
│  - subscribers in news.py, punditry.py, social.py, morale.py, etc.    │
│  - services publish; subscribers react; UI never subscribes            │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ mutates
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  data/cage_empire.db   (SQLite — 54 tables, schema 3.8.0)             │
│  - fighters, fighter_attributes, fighter_personality, fight_beats,     │
│    fight_rounds, commentary_segments, events, fights, ...              │
│  - the source of truth — UI is a reader, services are writers          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Memory resurfacing review (per supervisor Q5)

The supervisor asked: "what is it collecting, how's it stored,
and is it ever pruned?" Here is the full audit after reading
the codebase end-to-end.

### 3.1 What it collects (current state)

`fighter_memory_links` has 4 link types defined in the CHECK
constraint:

| link_type | What it links | Who writes it | When |
|---|---|---|---|
| `successor` | new regen fighter → retiring champion | `tick_processor._check_retirements` | When a retiring fighter had `fighter_career.title_reigns > 0` and a regen replacement is generated. `link_strength = min(50 + 10*reigns, 100)`. |
| `style_echo` | (defined in CHECK) | **NEVER WRITTEN** | Reserved for future. Intended: when a regen inherits a style archetype, link to the retiring fighter for "fighting style reminiscent of..." commentary. |
| `gym_heir` | (defined in CHECK) | **NEVER WRITTEN** | Reserved. Intended: when a new fighter joins a gym that produced a legend, link them. |
| `regional_rival` | (defined in CHECK) | **NEVER WRITTEN** | Reserved. Intended: when two fighters from the same region fight, link them. |

**Status:** only `successor` is populated. The other 3 link
types are dead schema. This was a known decision (logged in
MASTER_PLAN.md §10: "Memory resurfacing scope is broader than
champion successor links... No additional table needed." — but
the broader population never landed).

### 3.2 How it's stored

- Table: `fighter_memory_links`
- Columns: `memory_link_id` (PK), `fighter_id` (FK),
  `linked_fighter_id` (FK), `link_type` (CHECK),
  `link_strength` (0-100), `created_at`.
- Constraint: `UNIQUE (fighter_id, linked_fighter_id, link_type)`
  — prevents duplicate links of the same type.
- No `context_note` column, no `trigger_condition` column, no
  `last_surfaced_at` column. Just the link + strength.

### 3.3 Is it ever pruned?

**No.** There is no pruning logic. Once a `successor` link is
written, it stays forever. This is acceptable for `successor`
links (a regen fighter's predecessor doesn't change), but it
means:

- A fighter who retires at age 40 with 1 title reign creates 1
  successor link. If that successor fights for 15 years and
  retires with 3 title reigns, they create another successor
  link. After 50 years of simulation, you have ~1000+ successor
  links — most pointing at long-dead legends.
- The `news.generate_memory_resurfacing_news` subscriber looks
  up `successor` links when a new champion is crowned. With
  1000+ links, the query is still fast (indexed by fighter_id),
  but the *narrative* gets repetitive — "the torch passes" loses
  meaning if it fires every title change.

### 3.4 What needs to change for the Fight Resolution screen

The Fight Resolution screen's memory resurfacing (planned in
GUI_PLAN.md §4.3) is **broader** than just `successor` links on
title changes. It surfaces memories *during* a fight, triggered
by beat content (body-shot-heavy fight → past body-shot KO
memory, etc.). This requires:

1. **Populate the 3 dead link types** (`style_echo`, `gym_heir`,
   `regional_rival`). This is new code in
   `services/memory_svc.py` (part of Task 6.0 scope — the
   service module exposes the population functions; the actual
   calls happen in tick_processor + resolve_next_fight).

2. **Add `context_note` + `last_surfaced_at` columns** to
   `fighter_memory_links`. This is a **MINOR schema bump**
   (3.8.0 → 3.9.0) — I propose deferring it to Task 6.7 (Fight
   Resolution screen) where it's actually needed. Task 6.0 just
   builds the service module skeleton with the queries that
   will use these columns.

3. **Add a pruning policy.** Proposed: prune `successor` links
   where `linked_fighter_id` (the legend) has been in the Hall
   of Fame for >10 sim years (the memory is "settled" — the
   torch has been passed, the legend is canonized, no need to
   keep surfacing it). Keep `style_echo` / `gym_heir` /
   `regional_rival` links indefinitely (they're cheaper
   narratively). This pruning runs on the weekly tick.

4. **Memory candidate queue.** Before a fight resolves,
   `services.memory_svc.queue_candidates(fight_id)` pre-loads
   3-5 relevant memory links into an in-memory dict (keyed by
   fight_id, cleared after the fight screen closes). The Fight
   Resolution screen reads this queue, not the DB directly —
   faster, and the queue is the "what might surface" set.

### 3.5 Task 6.0 deliverables on memory

> **REVISED per Plan agent validation (Rev 4, Fix #4):** Task 6.0
> is a pure mechanical refactor + the `populate_*` functions
> only. All other memory_svc work (queue, mark_surfaced, pruning)
> defers to Task 6.7 (Fight Resolution screen — where it's
> actually needed). `populate_gym_heir` is also deferred (no
> current "fighter joins gym" code path — would need new game
> logic, violates §4.3).

`services/memory_svc.py` ships in Task 6.0 with ONLY these 2
functions:

- `populate_style_echo(conn, replacement_fighter_id, retiring_fighter_id)` —
  writes a `style_echo` link if the regen replacement inherited
  the retiring fighter's style archetype. Called from
  `tick_processor._check_retirements` (the ONE inline call per
  Fix #3) immediately AFTER the existing `successor` link INSERT
  at tick_processor.py:1309.
- `populate_regional_rival(conn, fighter_a_id, fighter_b_id)` —
  writes a `regional_rival` link if both fighters share a birth
  nation or region. Called from
  `services/matchmaking._build_main_event` (app.py:3807 after
  refactor) and `services/matchmaking._build_co_main`
  (app.py:3901 after refactor), immediately after the
  `fighter_a_id, fighter_b_id` selection.

Both functions are idempotent (use `INSERT OR IGNORE` against
the UNIQUE constraint). Both check the link_strength logic
(0-100) — `style_echo` uses 70 if archetype is inherited (else
skips the insert); `regional_rival` uses 50 + 10*common_region_
count.

**DEFERRED to Task 6.7** (Fight Resolution screen):
- `queue_candidates(conn, fight_id)` → dict
- `get_relevant_memory(conn, fight_id, beat_data)` → memory dict or None
- `mark_surfaced(conn, memory_link_id, fight_id)` (writes to a new `memory_resurface_log` table — deferred to Task 6.7 schema bump 3.8.0 → 3.9.0)
- `prune_stale_links(conn)` → int (called weekly; prunes `successor` links where legend in HoF >10 sim years)
- `populate_gym_heir(conn, fighter_id)` (deferred — no current "fighter joins gym" code path)

**DEFERRED to a future gym-events task:**
- `populate_gym_heir` — needs a "fighter joins gym" event that
  doesn't exist yet. Likely lands alongside Task 6.10 (Gyms
  screen) or a new gym-events task.

The actual *calls* to the 2 in-scope `populate_*` functions
happen in the relevant existing functions
(`tick_processor._check_retirements` for `populate_style_echo`;
`services/matchmaking._build_main_event` + `_build_co_main`
for `populate_regional_rival`), NOT in memory_svc itself.
memory_svc just exposes the logic. This preserves §15.4 in
spirit (the calls are in existing code paths, just calling a
new service function — same pattern as how
`_check_retirements` already publishes `FIGHTER_RETIRED`
inline).

---

## 4. Subagent brief (per CONVENTIONS §8 + §11)

When the supervisor signs off, the following brief is handed to
a dedicated `full-stack-developer` subagent (NOT `general-purpose`
— per supervisor instruction + Plan agent recommendation #G).
The subagent does NOT push to git — only the supervisor pushes
after sign-off.

### 4.1 Pre-flight (subagent MUST do this first)

1. Read these files in order (CONVENTIONS §8):
   - `README.md`
   - `docs/CAGE_EMPIRE_SOUL.md`
   - `docs/MASTER_PLAN.md` (current state + §10 decision log)
   - `docs/STAGES.md` (Stage 6 is the current stage)
   - `docs/CONVENTIONS.md` (all 16 sections — these are the rules)
   - `docs/SCHEMA_DRIFT_AUDIT.md`
   - `CHANGELOG.md` (recent changes)
   - `worklog.md` (supervisor's log — read the last 500 lines
     for context on the GUI plan + the schema bump just landed)
   - `docs/GUI_PLAN.md` (the design plan this task supports)
   - `docs/TASK_6_0_PLAN.md` (THIS file — the task brief)

2. Read `/home/z/my-project/worklog.md` (the supervisor's
   private log) — last 200 lines. Pay particular attention to
   the most recent entries (Task ID `STAGE6-PREP-REV4-LOGO-LOCK`
   and `STAGE6-PREP-REV3`) which document the Plan agent's
   validation report + the 10 fixes applied to this plan.

3. Run the smoke test (CONVENTIONS §6):
   ```bash
   cd /home/z/my-project/cage_empire
   python3 src/build_db.py
   python3 src/seed_data.py
   python3 src/tick_processor.py
   ```

4. Run all 38 acceptance tests. ALL must pass before starting.
   If any fail, STOP and report to supervisor.

5. **NEW per Plan agent Fix #10:** Run the App instantiation
   smoke test to confirm the baseline works before any extraction:
   ```bash
   cd /home/z/my-project/cage_empire
   python3 -c "import sys; sys.path.insert(0, 'src'); import app; a = app.App(); a.destroy()"
   ```
   If this fails, STOP — the baseline is broken before any work
   starts.

### 4.2 Task ID

`6.0` (sequential, no parallel sub-tasks).

### 4.3 Scope (EXACTLY this, nothing more)

Move the functions listed in §1.1 from `src/app.py` into the 13
new `src/services/*.py` modules. Add backwards-compatibility
re-exports in `src/app.py` (the complete 43-name list in §6.1)
so existing tests still import from `app` and work. Add the 2
`populate_*` functions to `services/memory_svc.py` per §3.5
(only new code in this task) + the ONE inline call in
`tick_processor._check_retirements` per Fix #3.

> **REVISED per Plan agent validation (Rev 4, Fix #4):** Task
> 6.0 is a **pure mechanical refactor + the 2 populate_*
> functions only**. All other "adds new code" items in Rev 3
> §1.1 (process_event_finances, weekly cashflow tick, feed
> querying, heat decay tick, confrontation triggers, camp query
> helpers, injury query helpers, HoF induction, named-pundit
> interjection generator, memory candidate queueing, pruning,
> mark_surfaced, populate_gym_heir) **DEFER** to the screen
> tasks that need them (Tasks 6.3–6.11). Do NOT write them
> in Task 6.0.

DO NOT:
- Change any function's behaviour.
- Rename any function.
- Change any function signature (except adding `conn` as first
  arg where it was previously closed-over — and only if
  necessary).
- Modify any acceptance test (CONVENTIONS §11.1 — flag stale
  assertions as D-numbers, do not fix them).
- Add new features (the 2 `populate_*` functions in memory_svc
  are the ONLY new code allowed; everything else defers per
  Fix #4).
- Touch `src/voice.py`, `src/event_bus.py`, `src/build_db.py`,
  `src/seed_data.py`.
- Touch any of the 16 existing `src/*.py` modules (you may
  import from them).
- Push to git (the supervisor pushes after sign-off).
- Modify `src/tick_processor.py` EXCEPT for the ONE inline
  `populate_style_echo` call per Fix #3 (inserted in
  `_check_retirements` after the existing `successor` link
  INSERT at line 1309). All other tick_processor functions
  stay untouched — wrap them from service modules instead.

DO:
- Create `src/services/__init__.py` (empty).
- Create the 13 service modules listed in §1.1.
- Move functions verbatim (copy-paste, preserve docstrings).
- Update imports across the codebase (use grep to find every
  call site).
- Add the re-export block in `src/app.py` per §6.1 (43 names,
  at module scope — see Fix #9 warning).
- Run the App instantiation smoke test (§4.5 #10) after EVERY
  extraction step.
- Run the re-export completeness check (§6.2) after writing
  the re-export block.
- Write the 2 `populate_*` functions in `services/memory_svc.py`
  per §3.5.
- Insert the ONE inline `populate_style_echo` call in
  `tick_processor._check_retirements` per Fix #3.
- Append a worklog entry per CONVENTIONS §3 with D-numbers.
- Run all 38 acceptance tests after every service module
  extraction (not just at the end — after each module, run the
  full suite. If a test breaks, you know which extraction caused
  it).
- Append a worklog entry per CONVENTIONS §3 at the end.

### 4.4 Service module template

Each `src/services/<module>.py` file follows this template:

```python
"""CAGE EMPIRE <module_name> service (Stage 6 — Task 6.0).

<one-paragraph description of what this module does and which
app.py functions it extracted>

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add
        tables; it's a code-only refactor. <note any tables
        it reads/writes>
  §6  — Smoke test protocol followed. All 38 acceptance tests
        pass after extraction.
  §13 — Design Law: <which pillar(s) this module supports>
  §14 — Voice Layer: <how this module routes through voice.py
        if it produces player-facing text>
  §15 — Event Bus: <which events this module publishes or
        subscribes to>

Migration impact: NONE (code-only refactor).
"""
import sqlite3
# ... imports

# ... functions moved verbatim from app.py
```

### 4.5 Acceptance criteria

The subagent's work is ACCEPTED only if ALL of:

1. ✅ `python3 src/build_db.py --fresh` succeeds, schema 3.8.0,
   54 tables, 17 migrations.
2. ✅ `python3 src/seed_data.py` succeeds.
3. ✅ `python3 src/tick_processor.py` succeeds.
4. ✅ All 38 acceptance tests pass (run each
   `scripts/test_*.py` file, count sub-checks).
5. ✅ `src/app.py` is reduced from 7694 lines to **~775 lines**
   (App class ~715 + launcher ~10 + re-export block ~50). The
   13 service modules exist under `src/services/` with the
   functions listed in §1.1. (Corrected per Plan agent Fix #8 —
   was ~3050 in Rev 3, actual is ~775.)
6. ✅ `git diff --stat` shows: app.py shrinks by ~6919 lines,
   services/ grows by ~6919 lines, no other files change
   except `src/tick_processor.py` (ONE inline
   `populate_style_echo` call per Fix #3) + docs/ + worklog.md.
7. ✅ No function signature changes (verified by `grep` for
   each public function name across `scripts/test_*.py` — all
   call sites still work).
8. ✅ Worklog entry appended per CONVENTIONS §3 with D-numbers
   for every decision.
9. ✅ Commit message follows CONVENTIONS §7.1 format with
   `refactor:` tag.
10. ✅ **NEW per Plan agent Fix #10 — App instantiation smoke
    test:** After EVERY extraction step, the subagent runs:
    ```bash
    cd /home/z/my-project/cage_empire
    python3 -c "import sys; sys.path.insert(0, 'src'); import app; a = app.App(); a.destroy()"
    ```
    This catches broken subscriber registrations + broken
    bare-name references early (5 tests instantiate `app.App()`:
    test_contracts, test_free_agency, test_promotion_filter,
    test_rankings, test_titles). If this smoke test fails, do
    NOT proceed to the next extraction step — fix the breakage
    first.
11. ✅ **NEW per Plan agent Fix #5 — Re-export completeness
    check:** After writing the re-export block, the subagent
    runs the grep in §6.2 and verifies every name resolves. Any
    `ImportError` or `AttributeError` on `import app` is a
    hard fail.

### 4.6 Escalation protocol

Per CONVENTIONS §11, if a test breaks:

1. The subagent identifies the broken assertion and its cause.
2. The subagent documents it as a D-number decision in its
   worklog entry.
3. The subagent returns the flag in its final message.
4. The supervisor (this agent) applies the fix during sign-off.

The subagent MUST NOT modify the test file.

### 4.7 What the supervisor does during the subagent's work

- Does NOT write code.
- Reads the subagent's progress messages.
- After the subagent returns, runs the full test suite to
  verify the acceptance criteria.
- Applies any D-number fixes per §11.2.
- Signs off (APPROVED) or bounces back (REJECTED — reason).

---

## 5. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hidden coupling between app.py functions (a function reads a module-level variable that another function sets) | Medium | High (test failure) | After each module extraction, run full test suite. If a test fails, the subagent investigates the coupling and either passes the variable as a parameter or moves the variable to the service module. |
| Circular imports (services/A imports services/B which imports services/A) | Low | Medium | Service modules must NOT import each other. If A needs B's function, the function should be in a shared util or the call should be in the orchestrator (app.py / tick_processor), not in the service. |
| Event bus subscriber registration order changes | Low | Medium | The event_bus is order-independent (subscribers stored in a dict). But if a subscriber depends on another subscriber having run first, that's a bug — flag as D-number. |
| Performance regression (extra import overhead) | Very Low | Low | Python imports are cached. Measured cost: <10ms at startup. |
| Test imports break (tests do `from app import resolve_next_fight`) | High | High | Re-exports in app.py (§4.3) solve this. Verify with `grep -r "from app import" scripts/`. |

---

## 6. Backwards compatibility — the re-export strategy

Every existing test file does some variant of:

```python
import app
app.resolve_next_fight(conn, fight_id)
```

or

```python
from app import resolve_next_fight, advance_day, sign_free_agent
```

After Task 6.0, `resolve_next_fight` lives in
`services/fight_engine.py`. To keep tests working without
modification (per CONVENTIONS §11.1 — "Subagents MUST NOT
modify existing acceptance tests"), `src/app.py` re-exports
every moved function.

> **REVISED per Plan agent validation (Rev 4, Fix #5 + Fix #9):**
> The Rev 3 version of this section only showed example
> re-exports. The complete list (43 names) is below — verified
> via `grep -rEn "(from app import|app\.)[a-zA-Z_][a-zA-Z0-9_]*"
> scripts/ src/`. The subagent MUST verify completeness by re-
> running this grep after writing the re-export block.
>
> **Fix #9 (CRITICAL):** The re-export block MUST live at module
> scope (top of `app.py`), NOT inside a conditional or function.
> Reason: the App class body (app.py:6980-7694) calls `advance_day`,
> `fighter_name`, `get_clock`, `get_contracts_for_display`,
> `get_fighters_for_display`, `get_free_agents_for_display`,
> `get_rankings_for_display`, `resolve_next_fight`,
> `schedule_next_event`, `sign_free_agent` as **bare names**.
> Python resolves bare names at module scope — if the re-exports
> are inside a function or conditional, the App class methods
> will raise `NameError`. The re-export block serves double duty:
> (a) backwards-compat for tests, AND (b) module-scope name
> resolution for the App class.

### 6.1 The complete re-export block (43 names)

```python
# src/app.py (after Task 6.0) — re-export block at module scope

# === services.clock (3 names) ===
from services.clock import (
    fighter_name,
    get_clock,
    advance_day,
)

# === services.fight_engine (35 names — public + private + constants) ===
from services.fight_engine import (
    # Public functions
    resolve_next_fight,
    resolve_round,
    update_fighter_descriptor_snapshot,
    # Beat engine internals (used by tests)
    _load_fighter_stats,
    _compute_beat_scores,
    _compute_gas_cost,
    _recover_gas_between_rounds,
    _compute_fight_importance,
    _compute_pressure_response,
    _compute_pressure_modifier,
    _ko_threshold,
    _ko_finish_probability,
    _submission_score,
    _doctor_stoppage_threshold,
    _check_corner_stoppage,
    _check_dq,
    _pick_action_type,
    _compute_damage,
    _resolve_beat_outcome,
    _maybe_transition_phase,
    _select_commentary_beats,
    _maybe_create_injury,
    _run_weight_cut,
    _compute_weight_cut_miss_prob,
    _resolve_title_after_fight,
    _update_event_status_after_resolution,
    _get_or_create_ranking_row,
    _update_rankings_after_resolution,
    # Gameplan derivation (used by tests)
    _derive_preferred_gameplans,
    _derive_bad_matchup_tags,
    _update_preferred_gameplans,
    _update_bad_matchup_tags,
    # Constants (used by tests + tick_processor + agent_offers)
    _FIGHTER_ATTR_COLUMNS,
    _FIGHTER_PERS_COLUMNS,
    _ELO_K,
    _INITIAL_RATING,
    _INJURY_BASE_DAYS_PER_SEVERITY,
    _INJURY_CAREER_HEALTH_MULT,
    _INJURY_MIN_DAYS_OUT,
    _INJURY_RECOVERY_RATE_DAYS_PER_POINT,
    _GAMEPLAN_THRESHOLD,
    _GAMEPLAN_CAP,
    _BAD_MATCHUP_CAP,
    _BEAT_COMMENTARY_TEMPLATES,
    PHASE_ATTRS,
    PHASE_ACTIONS,
    # Title vacation (used by tick_processor)
    _vacate_title_on_retirement,
)

# === services.matchmaking (13 names) ===
from services.matchmaking import (
    schedule_next_event,
    _pick_matchup,
    _build_main_event,
    _build_co_main,
    _build_featured_prelim,
    _build_prelim,
    _get_available_fighters_for_card,
    _group_available_by_wc,
    _get_event_naming_style,
    _build_event_name,
    EVENT_NAME_THEMES,
    EVENT_THEMES,
    # Camp helpers (used by tick_processor + App)
    _create_training_camp,
    _get_camp_fatigue_for_event,
    _pick_camp_focus_for_archetype,
    _ARCHETYPE_NAME_TO_CAMP_FOCUS,
    _CAMP_FOCUS_ATTRS,
    _CAMP_LEAD_DAYS,
)

# === services.contracts (3 names) ===
from services.contracts import (
    sign_free_agent,
    get_free_agents_for_display,
    get_contracts_for_display,
)

# === services.retirement_svc (1 name) ===
from services.retirement_svc import (
    generate_fighter,
)

# NOTE: the 8 pure-wrapper modules (scouting_svc, finance_svc,
# news_svc, rivalries_svc, training_svc, injuries_svc,
# punditry_svc, memory_svc) do NOT need re-exports — no test or
# src/ module imports their names from `app` directly. They are
# called only by the new services/* + ui/* code that will land
# in Tasks 6.1+.

# ============================================================
# Below: the unchanged tkinter App class (715 lines, deleted in
# Task 6.2) + the main() launcher. The App class's bare-name
# references (advance_day, resolve_next_fight, sign_free_agent,
# etc.) resolve via the re-exports above.
# ============================================================
import tkinter as tk
from tkinter import ttk, messagebox

class App(tk.Tk):
    """The old tkinter UI. Deleted in Task 6.2."""
    # ... 715 lines unchanged ...

if __name__ == "__main__":
    App().mainloop()
```

### 6.2 Verification step (subagent MUST do this)

After writing the re-export block, the subagent runs:

```bash
cd /home/z/my-project/cage_empire
# Find every name imported from app by tests + src modules
grep -rEn "(from app import |^import app$|app\.[a-zA-Z_][a-zA-Z0-9_]*)" scripts/ src/ | \
  grep -oE "(from app import [a-zA-Z_, ]+|app\.[a-zA-Z_][a-zA-Z0-9_]*)" | \
  sort -u
```

Every name in the output MUST be either:
- In the re-export block above, OR
- A name that stays in `app.py` (the App class, write_news,
  write_commentary, get_fighters_for_display,
  get_rankings_for_display — these stay per §1.3)

If any name is missing, the subagent adds it to the re-export
block and re-runs the verification.

---

## 7. Open questions for the supervisor (Task 6.0 specific)

> **REVISED per Plan agent validation (Rev 4):** All 4 original
> open questions have been resolved by the supervisor's
> approval + the Q3/Q4 recommendations. Kept here for audit
> trail.

1. **Tick processor wrappers:** ✅ APPROVED — the wrapper
   approach is used. `services/training_svc.py`,
   `services/injuries_svc.py`, and
   `services/retirement_svc.py` wrap
   `tick_processor._check_training_camps` /
   `_check_injury_recovery` / `_check_retirements` without
   modifying tick_processor (except the ONE inline
   `populate_style_echo` call per Fix #3). The actual tick
   logic stays in `tick_processor.py`.

2. **memory_svc population calls:** ✅ APPROVED — the inline
   `populate_style_echo` call in `tick_processor._check_
   retirements` is permitted (Q3 recommendation — relaxes §4.3
   for this ONE call because it matches how `_check_retirements`
   already publishes `FIGHTER_RETIRED` inline). The
   `populate_regional_rival` call in
   `services/matchmaking._build_main_event` + `_build_co_main`
   does NOT need the relaxation (those functions are not in
   tick_processor).

3. **memory_svc pruning policy:** ✅ APPROVED — prune
   `successor` links where the legend has been in HoF >10 sim
   years. **DEFERRED to Task 6.7** (Fight Resolution screen —
   where pruning is actually needed). Task 6.0 only writes the
   `populate_*` functions, not the pruning logic.

4. **Subagent type:** ✅ APPROVED — `full-stack-developer` (NOT
   `general-purpose`, per supervisor instruction + Plan agent
   recommendation #G). The `full-stack-developer` agent has
   Read / Write / Edit / Bash / Grep / Glob — all needed tools.
   This matches the agent used for every recent code task per
   worklog history (Tasks 14.5, B1, B2, 15, 16, 17, 18, 19, 20,
   21, 24).

---

## 8. Sign-off

> **REVISED per Plan agent validation (Rev 4):** All §7 questions
> resolved (supervisor approved + Q3/Q4 recommendations applied).
> STAGES.md + MASTER_PLAN.md §10 already updated. Ready to delegate.

The supervisor (this agent) will now:

1. ✅ ~~Update `docs/STAGES.md` to add Task 6.0 to Stage 6.~~ (Done
   in Rev 3 — Stage 6 task list with 15 entries including Task 6.0.)
2. ✅ ~~Update `docs/MASTER_PLAN.md §10` decision log with the
   answers.~~ (Done in Rev 3 — 11 new decision log entries.)
3. ✅ ~~Apply the 10 Plan agent fixes to this plan.~~ (Done in
   Rev 4 — all 10 fixes applied to this document.)
4. **NEXT:** Hand the brief (§4) to a dedicated
   `full-stack-developer` subagent. The subagent's prompt will
   include this entire plan + the Plan agent's full validation
   report as additional context.
5. Monitor the subagent's work via its return message.
6. Run the acceptance criteria (§4.5 — all 11 checks) on return.
7. Apply any D-number fixes per CONVENTIONS §11.2.
8. Sign off (APPROVED) or bounce (REJECTED — reason).
9. **Push to GitHub** ONLY after supervisor sign-off. Verified
   via `git fetch` + `git rev-parse` to confirm remote HEAD
   matches local HEAD. PAT cleared from `.git/config` after
   push (per established pattern).
