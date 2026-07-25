# CAGE EMPIRE — Phase 1 Detailed Plan (Foundation Fixes)

> **Status:** Awaiting supervisor sign-off. Once approved, each fix is
> delegated to a dedicated `full-stack-developer` subagent per
> CONVENTIONS §8 + §11. The supervisor reviews + signs off before any
> git push.
> **Authored:** 2026-07-25.
> **Prerequisite for:** Phase 2 (voice + personality) and all screen
> work (Tasks 6.3-6.14).
> **Schema impact:** NONE for fixes 1.1, 1.2, 1.3. Fix 1.4 (HoF
> induction) is code-only — the `hall_of_fame` table already exists,
> we're just adding a writer.

---

## 0. Why Phase 1 exists

The deep audits (save/load, long-term world health, voice/memory/
rivalries/personality/5-fantasies) found 4 critical foundation gaps
that would make any screen built on top feel hollow:

1. **Supervisor's 4000 original bios were discarded** — replaced with
   6 template-generated variants that recycle the supervisor's
   phrasings but substitute different stats. The `fighter_bios` table
   has 4000 rows, but NONE are the supervisor's originals.
2. **Save/load is not wired up** — the new CTk App never calls
   `register_subscribers()` for any of the 13 event-bus-driven
   systems, and `services.clock.advance_day` doesn't actually call
   `tick_processor.run_tick`. So no simulation runs, no events fire,
   no auto-save triggers, and there's no Save/Load screen.
3. **No Save/Load screen** — the sidebar entry is a placeholder.
   The player has no UI to save or load.
4. **Hall of Fame is closed** — only the 60 seeded legends ever
   appear. No code inducts fighters who retire during gameplay.
   After 50 sim years of developing champions, none of the player's
   fighters will be in the HoF. The Historian fantasy collapses.

Phase 1 fixes all 4. **No screen work begins until Phase 1 is
complete, verified, and pushed.**

---

## Fix 1.1 — Save supervisor's 4000 original bios

### Problem

`scripts/seed_world_phase3_from_profiles.py` loads
`data/parsed_fighters.json` (which contains the supervisor's 4000
original bios) but uses the bio **only as input** to
`assign_attributes_from_bios.py` for attribute inference. It never
writes to `fighter_bios`. Then `scripts/seed_world_phase5.py`
generates **template bios** that recycle the supervisor's phrasings
but substitute different stats.

Result: `fighter_bios` has 4000 rows, but none are the supervisor's
originals. Example for fighter #1:
- **Supervisor original**: "At 18 with a 2-2 record, the brawler
  from Valor Athletic..."
- **DB bio**: "At 17 with a 4-2 record, the brawler from Anvil Mixed
  Martial Arts... the career crossroads every young fighter hits..."

Same opening hook, different fighter.

### Fix

1. In `scripts/seed_world_phase3_from_profiles.py`, after the
   `INSERT INTO fighters` (around line 270), add:
   ```python
   # Save the supervisor's original bio (from parsed_fighters.json)
   # to fighter_bios. This is the FOUNDATION bio — seed_world_phase5.py
   # will skip fighters that already have a bio.
   bio_text = fighter.get("bio", "")
   if bio_text:
       # Derive bio_tone from the fighter's career state
       # (champion/prospect/veteran/etc.) — reuse the existing
       # _pick_bio_tone logic from seed_world_phase5.py
       bio_tone = _derive_bio_tone_from_fighter(wins, losses, age, potential)
       conn.execute(
           "INSERT OR REPLACE INTO fighter_bios "
           "(fighter_id, bio_text, bio_tone) VALUES (?, ?, ?)",
           (new_fighter_id, bio_text, bio_tone),
       )
   ```
2. Extract `_pick_bio_tone` from `seed_world_phase5.py` into a shared
   helper (or duplicate the logic — it's small).
3. In `scripts/seed_world_phase5.py`, change the bio-generation loop
   (lines ~380-446) to **skip fighters that already have a bio**:
   ```python
   # Only generate a bio for fighters that don't have one
   # (regen replacements, etc.). The supervisor's 4000 original
   # bios were saved in seed_world_phase3_from_profiles.py.
   existing_bio = conn.execute(
       "SELECT bio_text FROM fighter_bios WHERE fighter_id=?",
       (fighter_id,),
   ).fetchone()
   if existing_bio and existing_bio[0]:
       continue  # already has a bio — skip
   # ... else generate template bio (existing logic)
   ```

### Verification

After `./run.sh build-world`:
```bash
python3 -c "
import json, sqlite3
fighters = json.load(open('data/parsed_fighters.json'))
conn = sqlite3.connect('data/cage_empire.db')
# Check fighter 1's DB bio matches the supervisor's original
original = fighters[0]['bio']
db = conn.execute('SELECT bio_text FROM fighter_bios WHERE fighter_id=1').fetchone()[0]
assert original == db, f'MISMATCH:\noriginal={original[:100]}\ndb={db[:100]}'
print('Fighter 1 bio: MATCH')
# Check 10 random fighters
import random
for fid in random.sample(range(1, 4001), 10):
    original = next(f['bio'] for f in fighters if f['fighter_id'] == fid)
    db = conn.execute('SELECT bio_text FROM fighter_bios WHERE fighter_id=?', (fid,)).fetchone()[0]
    assert original == db, f'Fighter {fid} MISMATCH'
print('10 random fighters: all MATCH')
"
```

### Acceptance criteria

- ✅ `fighter_bios` has 4000 rows after `./run.sh build-world`
- ✅ Fighter 1's DB bio EXACTLY matches `parsed_fighters.json[0]['bio']`
- ✅ 10 random fighters' DB bios match their `parsed_fighters.json` bios
- ✅ `seed_world_phase5.py` skips fighters that already have a bio
- ✅ All 38 acceptance tests still pass
- ✅ Forensic DB check still passes (139/140, 0 critical)

---

## Fix 1.2 — Wire up CTk App + make advance_day call run_tick

### Problem

The new CTk App (`src/ui/app.py:CageEmpireApp`) never calls
`register_subscribers()` for any of the 13 event-bus-driven systems.
And `services.clock.advance_day` doesn't actually call
`tick_processor.run_tick` — it only updates the clock row. So:

- No simulation runs on "Advance Day" (retirements, injuries, camps,
  scouting, rival-AI, contract expiry — all silent)
- `TICK_ADVANCED` is never published
- Auto-save never triggers (it's a TICK_ADVANCED subscriber)
- News engine never generates tick-driven news

### Fix

#### 1.2a — Register all 13 subscribers in CageEmpireApp.__init__

Copy the lazy-import + try/except block from `src/app.py:328-574`
into `src/ui/app.py:CageEmpireApp.__init__` (after the GameState
init, before `_build_top_bar`). The 13 modules:

1. `news.register_subscribers` (FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED, etc.)
2. `social.register_subscribers`
3. `rivalries.register_subscribers`
4. `punditry.register_subscribers`
5. `morale.register_subscribers`
6. `suspensions.register_subscribers`
7. `agent_offers.register_subscribers`
8. `career_arc.register_subscribers`
9. `rival_ai.register_subscribers`
10. `show_rating.register_subscribers`
11. `venues.register_subscribers`
12. `save_load.register_subscribers`
13. `player_settings.register_subscribers`
14. `reputation.register_subscribers`

(That's 14 — the audit said 13, but there are 14. All must be registered.)

Each registration uses the pattern:
```python
try:
    from news import register_subscribers as _register_news
    _register_news()
except Exception as e:
    print(f"Warning: news.register_subscribers failed: {e}", flush=True)
```

#### 1.2b — Make services.clock.advance_day call tick_processor.run_tick

Current `src/services/clock.py:advance_day` (lines 45-53) only updates
the clock row. It must delegate to `tick_processor.run_tick(conn)`:

```python
def advance_day(conn):
    """Advance the simulation by one day.

    Thin wrapper that delegates to tick_processor.run_tick(conn).
    run_tick handles:
      - Updating simulation_clock (current_date += 1 day, etc.)
      - _check_retirements (birthday-gated, probability-based)
      - _check_training_camps (progress + complete)
      - _check_injury_recovery (clear is_active when recovered)
      - _check_contract_expiry (free agents)
      - Publishing Events.TICK_ADVANCED on the event bus
      - conn.commit()

    Per CONVENTIONS §15.4, the orchestration stays in run_tick —
    advance_day is just a thin wrapper so the UI has a single
    function to call.
    """
    from tick_processor import run_tick
    run_tick(conn)
```

### Verification

After the fix:
```bash
# 1. Fresh build + world seed
./run.sh build-world

# 2. Launch app in headless mode (can't actually launch CTk in
#    headless, but we can verify the wiring via a script)
python3 -c "
import sys; sys.path.insert(0, 'src')
from event_bus import get_bus, Events
bus = get_bus()
# Verify subscribers are registered (would be 0 if not wired)
print(f'TICK_ADVANCED subscribers: {len(bus._subscribers.get(Events.TICK_ADVANCED, []))}')
print(f'FIGHT_RESOLVED subscribers: {len(bus._subscribers.get(Events.FIGHT_RESOLVED, []))}')
print(f'FIGHTER_RETIRED subscribers: {len(bus._subscribers.get(Events.FIGHTER_RETIRED, []))}')
# Should be > 0 for each
"

# 3. Verify advance_day actually runs the simulation
python3 -c "
import sys, sqlite3; sys.path.insert(0, 'src')
from services.clock import advance_day, get_clock
conn = sqlite3.connect('data/cage_empire.db')
before = get_clock(conn)
print(f'Before: day={before[1]}')
advance_day(conn)
after = get_clock(conn)
print(f'After:  day={after[1]}')
assert after[1] == before[1] + 1, 'Day did not advance!'
print('advance_day correctly advanced the clock')
"
```

### Acceptance criteria

- ✅ All 14 `register_subscribers` calls execute without error on app startup
- ✅ `TICK_ADVANCED` has > 0 subscribers after app init
- ✅ `FIGHT_RESOLVED` has > 0 subscribers after app init
- ✅ `services.clock.advance_day(conn)` advances the clock by 1 day
- ✅ `services.clock.advance_day(conn)` publishes TICK_ADVANCED (verify via a test subscriber)
- ✅ All 38 acceptance tests still pass
- ✅ Forensic DB check still passes

---

## Fix 1.3 — Build Save/Load screen (Task 6.12 pulled forward)

### Problem

The sidebar has a "Save / Load" entry, but it's a placeholder. The
player has no UI to save or load. The `save_load` module exists and
works (`save_game`, `load_game`, `list_saves`, `delete_save`,
`auto_save`) but is unreachable from the UI.

### Fix

Create `src/ui/screens/save_load.py` — a CTk screen with:

#### Layout
```
┌──────────────────────────────────────────────────────────┐
│  SAVE / LOAD                                             │
├──────────────────────────────────────────────────────────┤
│  [Save Current Game]                                     │
│  Save name: [________________] [Save]                    │
│                                                          │
│  ── Saved Games ─────────────────────────────────────── │
│  ┌────────────────────────────────────────────────────┐ │
│  │ ★ Autosave — 2026-08-15          [Load] [Delete]  │ │
│  │   Alpha Combat · $12.4M · 4000 fighters           │ │
│  ├────────────────────────────────────────────────────┤ │
│  │   My Save — 2026-08-10           [Load] [Delete]  │ │
│  │   Alpha Combat · $8.2M · 3950 fighters            │ │
│  ├────────────────────────────────────────────────────┤ │
│  │   Pre-Experiment — 2026-07-30   [Load] [Delete]   │ │
│  │   Alpha Combat · $5.1M · 3900 fighters            │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  [Refresh] [Back to Dashboard]                           │
└──────────────────────────────────────────────────────────┘
```

#### Functions
- `SaveLoadScreen(ctk.CTkFrame)` — the screen widget
- `_build_save_section()` — name input + Save button
- `_build_saves_list()` — scrollable list of saved games (from `list_saves()`)
- `_on_save()` — calls `save_load.save_game(conn, name)`, refreshes list
- `_on_load(save_name)` — confirms with user, calls `save_load.load_game(save_name)`,
  reconnects the app's conn, refreshes all screens via `GameState.refresh_all()`
- `_on_delete(save_name)` — confirms with user, calls `save_load.delete_save(save_name)`,
  refreshes list
- `_refresh()` — re-queries `list_saves()` and re-renders the list
  (registered with GameState as the screen's refresh callback)

#### Integration
- Register the screen with GameState in `CageEmpireApp.__init__`
- Wire the "save_load" nav button to navigate to this screen
- On `_on_load`, the app must close the current conn, call `load_game`
  (which overwrites the DB file), open a new conn, update
  `GameState.conn`, and call `refresh_all()`
- On app quit (`CageEmpireApp.destroy`), auto-save as "exit_save"
  so accidental closes don't lose progress

### Verification

After the fix:
```bash
# 1. Launch app (requires display — supervisor tests manually)
./run.sh run

# 2. Click Save/Load in sidebar → screen renders
# 3. Type "test_save" → click Save → save appears in list
# 4. Verify file exists: data/saves/test_save.db + .json
# 5. Click Delete → save disappears from list + file deleted
# 6. Click Load on an existing save → app reconnects, screens refresh
```

### Acceptance criteria

- ✅ Save/Load screen renders when nav button clicked
- ✅ Save creates `data/saves/{name}.db` + `.json` metadata
- ✅ Save list shows all saves sorted by date DESC
- ✅ Load closes conn, overwrites DB, opens new conn, refreshes all screens
- ✅ Delete removes the save file + metadata
- ✅ App quit auto-saves as "exit_save"
- ✅ All 38 acceptance tests still pass
- ✅ Forensic DB check still passes

---

## Fix 1.4 — Build Hall of Fame induction system

### Problem

`hall_of_fame` table has 60 rows — all seeded at world build. No code
inducts fighters who retire during gameplay. The Soul document's
Historian fantasy ("The world remembers what I built") collapses for
any champion the player develops.

### Fix

Create `src/services/hof_svc.py` — a Hall of Fame induction service
that subscribes to `FIGHTER_RETIRED` and inducts qualifying fighters.

#### Eligibility criteria (per the audit recommendation)

A retired fighter is eligible for HoF induction if ANY of:
- `title_reigns >= 2` (multi-time champion)
- `title_defenses >= 5` (long-reigning champion) — note: need to
  verify the `title_defenses_count` column on `titles` table
- `record_wins >= 30` (longevity + success)
- `record_wins >= 20 AND title_reigns >= 1` (champion with longevity)

#### Implementation

```python
# src/services/hof_svc.py

"""CAGE EMPIRE Hall of Fame induction service (Phase 1 — Fix 1.4).

Subscribes to FIGHTER_RETIRED. When a fighter retires, evaluates
them against HoF eligibility criteria. If eligible, inducts them
into hall_of_fame with a generated career_summary + career_highlights,
and writes an induction news item.

This is the Historian fantasy's foundation (CAGE_EMPIRE_SOUL.md
Fantasy 4 — "The world remembers what I built"). Without this,
every champion the player develops is forgotten on retirement.

CONVENTIONS compliance:
  §13 — Design Law: Legacy pillar — HoF induction is how the world
        remembers what the player built.
  §14 — Voice Layer: career_summary + career_highlights use voice
        descriptors (no raw numbers). Inductee's potential,
        title_reigns, etc. are described, not numbered.
  §15 — Event Bus: subscribes to FIGHTER_RETIRED. No new inline
        side effects in tick_processor.
"""
import sqlite3
from event_bus import get_bus, Events


def _is_eligible_for_hof(conn, fighter_id):
    """Check if a retired fighter meets HoF eligibility criteria.

    Criteria (ANY of):
      - title_reigns >= 2 (multi-time champion)
      - record_wins >= 30 (longevity + success)
      - record_wins >= 20 AND title_reigns >= 1 (champion + longevity)
    """
    row = conn.execute(
        "SELECT fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.title_reigns "
        "FROM fighter_career fc WHERE fc.fighter_id = ?",
        (fighter_id,)
    ).fetchone()
    if not row:
        return False
    wins, losses, draws, title_reigns = row
    if title_reigns is None:
        title_reigns = 0

    if title_reigns >= 2:
        return True
    if wins >= 30:
        return True
    if wins >= 20 and title_reigns >= 1:
        return True
    return False


def _generate_career_summary(conn, fighter_id):
    """Generate a voice-layered career summary for the HoF inductee.

    Uses voice.describe_career_stage + describe_overall to produce
    a 1-2 sentence summary. NO raw numbers (CONVENTIONS §14).
    """
    # TODO: implement using voice.py
    # For now, return a placeholder that will be replaced
    pass


def _generate_career_highlights(conn, fighter_id):
    """Generate a bullet-list of career highlights for the inductee.

    Includes: title reigns, title defenses, notable wins, records.
    Formatted as a multi-line string with bullet points.
    """
    # TODO: implement
    pass


def induce_fighter_into_hof(conn, event):
    """Subscriber for FIGHTER_RETIRED — induce qualifying fighters
    into the Hall of Fame.

    Args:
        conn: sqlite3.Connection
        event: dict with 'fighter_id' (the retiring fighter)
    """
    fighter_id = event.get("fighter_id")
    if not fighter_id:
        return

    # Check if already inducted (defensive — idempotent)
    existing = conn.execute(
        "SELECT 1 FROM hall_of_fame WHERE fighter_id = ?",
        (fighter_id,)
    ).fetchone()
    if existing:
        return  # already inducted

    # Check eligibility
    if not _is_eligible_for_hof(conn, fighter_id):
        return  # not eligible — silent skip

    # Generate summary + highlights
    career_summary = _generate_career_summary(conn, fighter_id)
    career_highlights = _generate_career_highlights(conn, fighter_id)

    # Get current sim date for induction date
    sim_date = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]

    # Induct
    conn.execute(
        "INSERT INTO hall_of_fame "
        "(fighter_id, inducted_date, career_summary, career_highlights) "
        "VALUES (?, ?, ?, ?)",
        (fighter_id, sim_date, career_summary, career_highlights)
    )

    # Write induction news item
    # TODO: use news.write_news_item with topic='hall_of_fame'
    # The news should use voice descriptors + the inductee's career
    # summary. Example: "John Vale inducted into Hall of Fame —
    # a multi-time champion who defended his belt with elite
    # knockout power and an iron chin."


def register_subscribers():
    """Register HoF induction subscriber on FIGHTER_RETIRED."""
    bus = get_bus()
    bus.subscribe(
        Events.FIGHTER_RETIRED, induce_fighter_into_hof,
        name="hof_svc.induce_fighter_into_hof"
    )
```

#### Integration

1. Register `hof_svc.register_subscribers()` in `CageEmpireApp.__init__`
   (alongside the other 14 from Fix 1.2 — this is #15)
2. Also register it in the OLD `App.__init__` in `src/app.py` for
   backwards-compat with tests that instantiate `app.App()`

#### Verification

After the fix:
```bash
# 1. Find a fighter with title_reigns >= 2
python3 -c "
import sqlite3
conn = sqlite3.connect('data/cage_empire.db')
row = conn.execute('SELECT fighter_id, first_name, last_name FROM fighters f JOIN fighter_career fc ON f.fighter_id=fc.fighter_id WHERE fc.title_reigns >= 2 AND f.is_active=1 LIMIT 1').fetchone()
print(f'Test fighter: {row[1]} {row[2]} (id={row[0]})')
"

# 2. Manually retire them (set is_retired=1, is_active=0)
# 3. Publish FIGHTER_RETIRED
# 4. Verify they appear in hall_of_fame with summary + highlights
# 5. Verify a news item was written with topic='hall_of_fame'
```

### Acceptance criteria

- ✅ `hof_svc.register_subscribers()` runs without error on app startup
- ✅ `FIGHTER_RETIRED` event triggers `induce_fighter_into_hof`
- ✅ Eligible fighters (title_reigns>=2 OR wins>=30 OR wins>=20+title_reigns>=1) get inducted
- ✅ Ineligible fighters are silently skipped
- ✅ Already-inducted fighters are not re-inducted (idempotent)
- ✅ `career_summary` uses voice descriptors (no raw numbers — §14)
- ✅ `career_highlights` formatted as bullet list
- ✅ Induction news item written with topic='hall_of_fame'
- ✅ All 38 acceptance tests still pass
- ✅ Forensic DB check still passes

---

## Delegation strategy

Each fix is delegated to a `full-stack-developer` subagent per
CONVENTIONS §8 + §11. The supervisor (this agent):

1. **Writes the detailed brief** (this document + the specific fix section)
2. **Delegates to subagent** with the brief + CONVENTIONS §8 pre-flight
   reading list
3. **Monitors** the subagent's return message
4. **Verifies** the acceptance criteria independently (doesn't trust
   subagent output)
5. **Applies D-number fixes** per CONVENTIONS §11.2 if tests break
6. **Signs off** (APPROVED) or bounces (REJECTED — reason)
7. **Pushes to git** only after sign-off (never the subagent)

### Execution order (sequential, not parallel — each fix builds on the prior)

1. **Fix 1.1** (bios) — independent, can run first
2. **Fix 1.2** (CTk wiring) — depends on 1.1 (the world must have bios
   for the wired-up app to display them)
3. **Fix 1.4** (HoF induction) — depends on 1.2 (must be registered
   alongside the other 14 subscribers)
4. **Fix 1.3** (Save/Load screen) — depends on 1.2 (the screen calls
   `save_load` functions which must be wired up)

So: **1.1 → 1.2 → 1.4 → 1.3**.

### Subagent brief template

Each subagent receives:
1. The relevant section of this plan (§1, §2, §3, or §4)
2. The CONVENTIONS §8 pre-flight reading list
3. The acceptance criteria for their fix
4. The CRITICAL RULES (no test modification, no signature changes,
   no git push, run all 38 tests after the fix, append worklog entry
   per §3)
5. The return format (A. summary, B. files changed, C. D-numbers,
   D. acceptance criteria verification, E. worklog entry)

---

## Risk mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Fix 1.1 breaks the world seed | Low | High (world rebuild fails) | Test `./run.sh build-world` end-to-end after the fix |
| Fix 1.2 breaks existing tests | Medium | High (tests instantiate App which now registers 15 subscribers) | Run all 38 tests after the fix; flag any breakage as D-number |
| Fix 1.3 can't be tested headlessly | High | Medium (CTk requires a display) | Subagent writes the screen; supervisor tests manually if display available, else verifies code review + import test |
| Fix 1.4 voice descriptors contain digits | Medium | Medium (§14 violation) | Run `test_voice.py` after the fix; verify no digits in career_summary |
| World DB destroyed during testing | High (happened twice before) | Critical | NEVER run `build_db.py --fresh` during subagent testing. Subagents use `--migrate` or test against a copy. Supervisor restores world from `./run.sh build-world` if needed. |

---

## Sign-off

Once all 4 fixes are complete + verified:

1. ✅ All 38 acceptance tests pass
2. ✅ Forensic DB check passes (139/140, 0 critical)
3. ✅ World DB has 4000 fighters + 4000 SUPERVISOR BIOS (not templates)
4. ✅ CTk App registers all 15 subscribers on startup
5. ✅ `advance_day` actually runs the simulation
6. ✅ Save/Load screen renders + saves + loads + deletes
7. ✅ HoF induction fires on FIGHTER_RETIRED for eligible fighters
8. ✅ Worklog entries appended for each fix (4 entries)
9. ✅ CHANGELOG + STAGES + MASTER_PLAN updated
10. ✅ Pushed to git (single commit or 4 commits — supervisor's choice)

**Only then does Phase 2 (voice + personality) begin.**
