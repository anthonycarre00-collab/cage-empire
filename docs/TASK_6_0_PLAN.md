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

| Module | Functions moved from `app.py` | Lines (approx) |
|---|---|---|
| `services/clock.py` | `get_clock`, `advance_day`, `advance_week`, internal helpers | ~150 |
| `services/fight_engine.py` | `resolve_next_fight`, `resolve_round`, `_resolve_outcome`, beat engine, decision scoring, all fight-related internal helpers, `_select_commentary_beats` + constants | ~2200 |
| `services/matchmaking.py` | `schedule_next_event`, `_pick_matchup`, `_build_card`, `_auto_schedule_next_event_for_promotion`, fight importance calc | ~500 |
| `services/contracts.py` | `sign_fighter`, `renew_contract`, `_expire_contracts`, contract helpers (some already in `src/agent_offers.py` — coordinate) | ~300 |
| `services/scouting_svc.py` | Wraps existing `src/scouting.py`; adds report staleness logic from `app.py` | ~150 |
| `services/finance_svc.py` | Wraps existing `src/finance.py`; adds `process_event_finances`, weekly cashflow tick | ~200 |
| `services/news_svc.py` | Wraps existing `src/news.py`; adds feed querying for UI (filter, sort, paginate) | ~100 |
| `services/rivalries_svc.py` | Wraps existing `src/rivalries.py`; adds heat decay tick, confrontation triggers | ~150 |
| `services/training_svc.py` | Wraps existing `src/tick_processor._check_training_camps`; adds camp query helpers for UI | ~200 |
| `services/injuries_svc.py` | Wraps existing `src/tick_processor._check_injuries`; adds injury query helpers | ~100 |
| `services/retirement_svc.py` | Wraps existing `src/tick_processor._check_retirements`; adds HoF induction | ~150 |
| `services/punditry_svc.py` | Wraps existing `src/punditry.py`; adds named-pundit interjection generator for Fight Resolution screen (uses new `staff.pundit_bias` column) | ~250 (new code) |
| `services/memory_svc.py` | Wraps `fighter_memory_links` reads + writes; adds memory candidate queueing for Fight Resolution screen, prunes stale links | ~200 (new code) |

**Total moved:** ~4650 lines out of `app.py`. After refactor,
`app.py` shrinks from 7700 lines to ~3050 lines (the tkinter UI
class + a few misc helpers), and those 3050 lines are DELETED in
Task 6.2 when the new CTk shell lands. So Task 6.0 leaves
`app.py` as a stub — a 30-line launcher.

### 1.2 What stays in `app.py` after Task 6.0

```python
"""CAGE EMPIRE — application launcher.

After Task 6.0, this file is a 30-line launcher. All game logic
lives in src/services/. The tkinter UI (App class) was REMOVED
in Task 6.2 when the new CustomTkinter shell landed.

To run the game:
    python src/app.py
"""
import sys
from pathlib import Path
from ui.app import CageEmpireApp  # landed in Task 6.2

def main():
    app = CageEmpireApp()
    app.mainloop()

if __name__ == "__main__":
    main()
```

**During Task 6.0** (before Task 6.2 lands), `app.py` keeps the
old tkinter `App` class intact so the game still runs. The
services are extracted but the UI still calls them. The 3050
remaining lines are the old UI — they get deleted in Task 6.2.

### 1.3 What does NOT move in Task 6.0

- `src/build_db.py` — unchanged (schema only).
- `src/seed_data.py` — unchanged (minimal seed).
- `src/tick_processor.py` — unchanged in Task 6.0. Its
  functions (`_check_retirements`, `_check_training_camps`,
  `_check_injuries`) get *wrapped* by the new service modules
  but the wrappers delegate to the existing functions. A later
  task (6.0.5, optional) may inline them.
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

```
User clicks "Advance Day" (UI button)
  ↓
ui/screens/dashboard.py calls services.clock.advance_day(conn)
  ↓
services.clock.advance_day:
  1. Updates simulation_clock row (current_date += 1 day, etc.)
  2. Calls services.retirement_svc.check_retirements(conn)
  3. Calls services.training_svc.progress_camps(conn)
  4. Calls services.injuries_svc.progress_injuries(conn)
  5. Calls services.contracts.expire_contracts(conn)
  6. Calls services.rivalries_svc.apply_heat_decay(conn)
  7. Calls services.finance_svc.process_daily_cashflow(conn)
  8. Publishes Events.TICK_ADVANCED on the event bus
  ↓
Event bus synchronously calls all subscribers:
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
Event bus returns. advance_day returns. UI gets control back.
  ↓
UI calls ui/state.py:refresh_all() (the game-state layer — see §3)
  ↓
All visible screens re-query their data and re-render.
```

**Contract for every service function called from advance_day:**
- Takes `conn` (sqlite3.Connection) as first arg.
- Mutates DB state inside the same transaction.
- Does NOT publish events itself — the orchestrator
  (`advance_day`) publishes one TICK_ADVANCED at the end. This
  preserves §15.4 ("no new inline side effects in run_tick").
- Returns either None (fire-and-forget) or a list of dicts
  (structured result for logging/testing).

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

- `services/memory_svc.py` skeleton with:
  - `queue_candidates(conn, fight_id)` → dict
  - `get_relevant_memory(conn, fight_id, beat_data)` → memory dict or None
  - `mark_surfaced(conn, memory_link_id, fight_id)` (writes to a new `memory_resurface_log` table — deferred to Task 6.7 schema bump)
  - `prune_stale_links(conn)` → int (called weekly)
  - `populate_style_echo(conn, fighter_id)` (new — called by tick_processor on regen)
  - `populate_gym_heir(conn, fighter_id)` (new — called when a fighter joins a gym)
  - `populate_regional_rival(conn, fighter_a_id, fighter_b_id)` (new — called by matchmaking when both fighters share a region)

The actual *calls* to populate_* happen in the relevant existing
functions (tick_processor, matchmaking), NOT in memory_svc
itself. memory_svc just exposes the logic. This preserves
§15.4 (no new inline side effects — the calls are in existing
code paths, just calling a new service function).

---

## 4. Subagent brief (per CONVENTIONS §8 + §11)

When the supervisor signs off, the following brief is handed to
a dedicated `general-purpose` subagent.

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
   private log) — last 200 lines.

3. Run the smoke test (CONVENTIONS §6):
   ```bash
   cd /home/z/my-project/cage_empire
   python3 src/build_db.py
   python3 src/seed_data.py
   python3 src/tick_processor.py
   ```

4. Run all 38 acceptance tests. ALL must pass before starting.
   If any fail, STOP and report to supervisor.

### 4.2 Task ID

`6.0` (sequential, no parallel sub-tasks).

### 4.3 Scope (EXACTLY this, nothing more)

Move the functions listed in §1.1 from `src/app.py` into the 13
new `src/services/*.py` modules. Add backwards-compatibility
re-exports in `src/app.py` so existing tests still import from
`app` and work.

DO NOT:
- Change any function's behaviour.
- Rename any function.
- Change any function signature (except adding `conn` as first
  arg where it was previously closed-over — and only if
  necessary).
- Modify any acceptance test (CONVENTIONS §11.1 — flag stale
  assertions as D-numbers, do not fix them).
- Add new features.
- Touch `src/voice.py`, `src/event_bus.py`, `src/build_db.py`,
  `src/seed_data.py`, `src/tick_processor.py` (you may *wrap*
  tick_processor functions from a service module, but do not
  modify tick_processor itself).
- Touch any of the 16 existing `src/*.py` modules (you may
  import from them).

DO:
- Create `src/services/__init__.py` (empty).
- Create the 13 service modules listed in §1.1.
- Move functions verbatim (copy-paste, preserve docstrings).
- Update imports across the codebase (use grep to find every
  call site).
- Add re-exports in `src/app.py`:
  ```python
  # Backwards compatibility — re-export moved functions so
  # existing tests (scripts/test_*.py) keep working.
  from services.clock import get_clock, advance_day, advance_week
  from services.fight_engine import resolve_next_fight, ...
  # ... etc for all 13 modules
  ```
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
5. ✅ `src/app.py` is reduced from 7700 lines to ~3050 lines
   (the tkinter UI + launcher). The 13 service modules exist
   under `src/services/` with the functions listed in §1.1.
6. ✅ `git diff --stat` shows: app.py shrinks by ~4650 lines,
   services/ grows by ~4650 lines, no other files change
   except docs/ + worklog.md.
7. ✅ No function signature changes (verified by `grep` for
   each public function name across `scripts/test_*.py` — all
   call sites still work).
8. ✅ Worklog entry appended per CONVENTIONS §3 with D-numbers
   for every decision.
9. ✅ Commit message follows CONVENTIONS §7.1 format with
   `refactor:` tag.

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
from app import resolve_next_fight, advance_day, sign_fighter
```

After Task 6.0, `resolve_next_fight` lives in
`services/fight_engine.py`. To keep tests working without
modification (per CONVENTIONS §11.1 — "Subagents MUST NOT
modify existing acceptance tests"), `src/app.py` re-exports
every moved function:

```python
# src/app.py (after Task 6.0)

# Backwards compatibility re-exports.
# These exist SOLELY so existing acceptance tests
# (scripts/test_*.py) that do `from app import X` or
# `import app; app.X()` keep working without modification.
# New code should import from services/ directly.
from services.clock import (
    get_clock, advance_day, advance_week,
)
from services.fight_engine import (
    resolve_next_fight, resolve_event,
    _select_commentary_beats,  # exported because tests use it
    # ... all other fight_engine functions used by tests
)
from services.matchmaking import (
    schedule_next_event, _pick_matchup, _build_card,
)
# ... etc for all 13 modules

# Then the remaining tkinter App class + main() launcher
# (deleted in Task 6.2)
class App(tk.Tk):
    ...

if __name__ == "__main__":
    App().mainloop()
```

The subagent MUST run `grep -rEn "from app import|import app" scripts/` to find every test's import, and ensure every imported name is in the re-export block.

---

## 7. Open questions for the supervisor (Task 6.0 specific)

1. **Tick processor wrappers:** The new
   `services/training_svc.py`, `services/injuries_svc.py`, and
   `services/retirement_svc.py` modules *wrap*
   `src/tick_processor.py` functions. The wrappers add UI
   query helpers (e.g., `get_active_camps_for_fighter(fighter_id)`)
   but the actual tick logic stays in `tick_processor.py`.
   Approve this "wrapper" approach, or do you want the
   tick_processor functions moved into the services (deeper
   refactor, higher risk)?

2. **memory_svc population calls:** §3.5 adds 3 new
   `populate_*` functions to be called from
   `tick_processor._check_retirements` (for `style_echo`) and
   `services/matchmaking.schedule_next_event` (for
   `regional_rival`). These are NEW inline calls in existing
   functions. Per §15.4, "no new inline side effects" applies
   to `resolve_next_fight` and `run_tick` — but
   `_check_retirements` and `schedule_next_event` are NOT
   those. Approve these specific inline calls, or require them
   to go through the event bus (publishing a new
   `FIGHTER_GENERATED` event that memory_svc subscribes to)?

3. **memory_svc pruning policy:** §3.4 proposes pruning
   `successor` links where the legend has been in HoF >10 sim
   years. Approve this policy, or want a different threshold
   (5 years? 20 years? never prune)?

4. **Subagent type:** I propose using the `general-purpose`
   subagent for Task 6.0 (it has all tools, can run tests, can
   write code, can read all docs). Approve, or want a different
   agent type?

---

## 8. Sign-off

Once the supervisor answers Q1–Q8 from the chat reply (the
"answer these questions only" set) + Q1–Q4 from this doc's §7,
the supervisor (this agent) will:

1. Update `docs/STAGES.md` to add Task 6.0 to Stage 6.
2. Update `docs/MASTER_PLAN.md §10` decision log with the
   answers.
3. Hand the brief (§4) to the subagent.
4. Monitor the subagent's work.
5. Run the acceptance criteria (§4.5) on return.
6. Sign off (APPROVED) or bounce (REJECTED — reason).
7. Push to GitHub (this time, for real — `git push` after every
   commit, verified by `git fetch` + `git rev-parse`).
