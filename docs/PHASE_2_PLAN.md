> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Phase 2 Comprehensive Implementation Plan

> **Status:** PLANNING ONLY — NO CODING. Awaiting supervisor sign-off.
> **Authored:** 2026-07-26. Schema 3.9.0. Commit c023db8.
> **Analysed by:** Supervisor (main) + Plan agent (architectural validation)
>   + Explore agent (independent 2nd opinion / codebase mapping).
> **Spec source:** `/home/z/my-project/upload/cageemprire phase 2 new 267.txt`

---

## 0. Executive Summary

The Phase 2 spec proposes an **Interpretation & Narrative Layer** —
read-only services that translate simulation state into player-facing
meaning, context, and stories. The vision is sound and overdue. The
spec is a **direction document, not a build document** — it doesn't
acknowledge 4 existing assets (`voice.py`, `fighter_descriptors`,
`memory_svc.py`, `news.py`) that the implementation must build on
top of, not alongside.

**Both expert agents agree on the following key findings:**

1. `voice.py` is the **vocabulary layer** (numbers→words) and stays
   where it is. The new interpretation layer calls it, doesn't
   replace it.
2. `career_arc.py` is the **aging system** (attribute growth/decline),
   NOT a phase labeler. The spec's "Career Arc Engine" must be
   renamed to **Career Phase Engine** to avoid a naming collision.
3. `fighter_descriptors` table is **already a snapshot cache** and
   should be **EXTENDED** (add columns), not replaced. 6+ existing
   call sites depend on it.
4. `news.py` is **reactive** (per-event news). The Headline Engine
   (daily aggregation) is genuinely new.
5. `memory_svc.py` is a **writer** only. The Memory Engine (reader
   that surfaces memories before key events) is genuinely new.
6. The UI **barely exists** (1 real screen out of 22). Migration risk
   is near-zero — but the convention must be established BEFORE
   screens are built.
7. "Never modify the database" means "never modify **simulation**
   tables; **cache** tables are fair game." The spec contradicts
   itself here and needs a reconciliation addendum.
8. **~80 content rulesets** (14 narrative families + 12 career phases
   + 10 public narratives + 5 momentum + 4 pressure + 6 legacy +
   8 headlines + 8 gym identity attributes + 10 memory search types)
   is too much for one pass. An **MVP cut** is required.

**The 2nd-opinion agent found 3 critical gaps the Plan agent missed:**

1. **Fight Resolution screen exception** — "UI reads snapshots only"
   does NOT apply to the Fight Resolution screen (Task 6.7). That
   screen reads live `fight_beats` in real-time. Office Mode =
   snapshots; Fight Night Mode = live tables + real-time voice.
2. **60 HoF legends have NO `fighter_descriptors` rows** — need to
   backfill before Phase 2 starts.
3. **450 Group B fighters have NO `fighter_descriptors` rows** —
   need to backfill before Phase 2 starts.

---

## 1. What Already Exists (Don't Rebuild)

| Spec section | Existing system | Status | Action |
|---|---|---|---|
| §2 Interpretation Engine | `voice.py` (905 lines, 7 public functions) | EXISTS — vocabulary layer (numbers→words). The interpretation engine is a HIGHER layer that calls voice.py. | Keep as-is. New layer imports from it. |
| §3 Context Engine | `career_arc.py` (attribute aging); `voice.describe_career_stage()` (phrase-based) | PARTIALLY EXISTS — career_arc handles growth/decline mechanics. `describe_career_stage` produces phrases ("top prospect", "grizzled veteran") but not canonical labels. | New module. career_arc stays untouched. |
| §4 Narrative Families | (none) | DOES NOT EXIST | 100% new. |
| §5 Memory Engine | `memory_svc.py` (101 lines, 2 writer functions); `news.generate_memory_resurfacing_news` (fires on TITLE_CHANGED only) | PARTIALLY EXISTS — memory_svc is a WRITER. The news function is a partial READER (title fights only). `fighter_memory_links` table has 96 rows + 4 link types. | New reader module. Extend link_type CHECK with ~6 new values. |
| §6 Snapshot Cache | `fighter_descriptors` table (8 cols, 4000 rows) | EXISTS — this IS the fighter snapshot cache. Spec doesn't acknowledge it. | EXTEND with 6 new columns. Add 4 sibling cache tables (gym/promo/division/headlines). |
| §7 Entity Summaries | `voice.describe_overall()` (fighter summary); `hof_svc._generate_career_summary()` (retired fighter summary) | PARTIALLY EXISTS — fighter summary exists. Gym/promo/division summaries do not. | Add gym.summary(), promotion.summary(), division.summary(). |
| §8 Headline Engine | `news.py` (3245 lines, 21 event subscribers, reactive) | PARTIALLY EXISTS — news.py is reactive (per-event). `generate_event_hype_news` is weekly/proactive but doesn't do top-N aggregation. | New module. Separate from news.py. |
| §9 Gym Identity | `gyms` table (8 INT cols: reputation, facility_quality, medical_support, etc.) | DATA EXISTS — but no interpretation layer turns INTs into identity ("Known For: Elite wrestlers"). | New interpretation module over existing data. |
| §10 Career Arc Engine | `career_arc.py` (NAMING COLLISION — this is the aging system); `voice.describe_career_stage()` | COLLISION — career_arc.py is NOT a phase labeler. `describe_career_stage` is close but phrase-based, not canonical-label-based. | Rename to Career Phase Engine. Add new `career_phase` column (don't overwrite existing `career_stage`). |
| §11 Public Narrative | (none) | DOES NOT EXIST | 100% new. |
| §12 Momentum | (none — win/loss streaks exist in fighter_career but no derived label) | DOES NOT EXIST | 100% new (thin — 5 thresholds, ~30 lines). |
| §13 Pressure | (none — contract, ranking, popularity, losses all exist separately) | DOES NOT EXIST | 100% new (thin — 4 thresholds + formula, ~50 lines). |
| §14 Legacy | `hof_svc.py` (binary: in HoF or not); `fighter_bios.bio_tone` (static seeded label) | PARTIALLY EXISTS — hof_svc is the induction event. bio_tone is static. | New living, re-derived label. Distinct from hof_svc. |
| §15 UI Rule | (none — UI reads DB directly) | DOES NOT EXIST | New convention (CONVENTIONS.md §17). |
| §16 Performance | `career_arc._process_career_arc()` (shows the correct bulk-load pattern) | PATTERN EXISTS — career_arc already does bulk-load + Python loop + batch UPDATE. | Follow the same pattern for the interpretation pass. |

---

## 2. Architecture

### 2.1 Directory structure

```
src/
├── voice.py                    ← EXISTS (vocabulary layer, DO NOT MOVE)
├── career_arc.py               ← EXISTS (aging system, DO NOT TOUCH)
├── news.py                     ← EXISTS (reactive news engine, DO NOT TOUCH)
├── services/
│   ├── memory_svc.py           ← EXISTS (memory writer, DO NOT TOUCH)
│   ├── hof_svc.py              ← EXISTS (HoF induction, DO NOT TOUCH)
│   └── ...
├── interpretation/             ← NEW PACKAGE (Phase 2)
│   ├── __init__.py             ← register_subscribers() aggregator
│   ├── interpretation_engine.py ← orchestrator (daily pass)
│   ├── context_engine.py       ← momentum, pressure, trajectory
│   ├── career_phase_engine.py  ← canonical career phase labels (NOT "career_arc")
│   ├── narrative_families.py   ← story archetypes (The Prodigy, etc.)
│   ├── memory_engine.py        ← reader: surface memories before key events
│   ├── headline_engine.py      ← daily headline aggregation
│   ├── gym_identity_engine.py  ← gym personality narratives
│   ├── legacy_engine.py        ← living legacy labels
│   └── snapshot_cache.py       ← orchestrator: writes to cache tables
├── ui/
│   ├── app.py                  ← EXISTS (CTk shell, registers interpretation subscribers)
│   ├── state.py                ← EXISTS (GameState)
│   ├── theme.py                ← EXISTS
│   └── screens/                ← Phase 3+ (screens read snapshots ONLY)
└── build_db.py                 ← EXTEND with cache tables + migrations
```

### 2.2 Layering (the key insight from both agents)

```
Layer 0: voice.py           — numbers → words ("elite", "iron chin")
                              EXISTS. Pure functions. No DB. No state.

Layer 1: context_engine.py  — state → derived labels ("high" momentum)
                              NEW. Pure functions of DB state. No RNG.
                              Returns canonical enum strings.

Layer 2: interpretation_engine.py — labels + state → meaning ("Career Crisis")
                              NEW. Orchestrator. Reads DB, calls Layer 0+1,
                              produces narrative sentences. Uses RNG for
                              phrase variety (seeded by fighter_id).

Layer 3: narrative_families.py — meaning → story archetype ("The Prodigy")
                              NEW. Rules-based matcher. One family per
                              fighter (or None). Voice variants.

Layer 4: snapshot_cache.py  — all of the above → cached DB rows
                              NEW. Writes to fighter_descriptors (extended)
                              + gym_descriptors + promotion_descriptors +
                              division_descriptors + daily_headlines.
                              UI reads from HERE ONLY (Office Mode).
```

### 2.3 The "UI reads snapshots only" rule — with the Fight Resolution exception

**Office Mode screens** (Dashboard, Roster, Fighter Profile, Rankings, News, Finance, etc.):
- MUST read from `*_descriptors` and `daily_headlines` tables only.
- MUST NOT read from `fighters`, `fighter_attributes`, `fighter_career`, `contracts`, `events`, `fights`, `rankings`, `titles` directly.
- This is codified as CONVENTIONS.md §17 (new).

**Fight Night Mode screens** (Fight Resolution — Task 6.7):
- MUST read from live simulation tables (`fight_beats`, `fight_rounds`, `commentary_segments`) in real-time.
- MUST apply `voice.py` in real-time for beat commentary.
- The daily snapshot cache is STALE during a live fight — the fight is happening NOW.
- This exception is documented in CONVENTIONS.md §17.1.

**Save/Load interaction:**
- Cache tables are in the DB → they save/load automatically with the world DB.
- No special handling needed. Loading a save restores the cache as-is.
- If the interpretation engine is upgraded (new narrative family added), a `interpretation_cache_meta` table tracks the engine version. On version mismatch, the next daily pass rebuilds all caches.

---

## 3. Schema Impact

### 3.1 Extend `fighter_descriptors` (v3.10.0, MINOR)

6 new nullable TEXT columns:
```sql
ALTER TABLE fighter_descriptors ADD COLUMN momentum TEXT;
    -- 'very_high' | 'high' | 'stable' | 'falling' | 'collapsing'
ALTER TABLE fighter_descriptors ADD COLUMN pressure TEXT;
    -- 'minimal' | 'moderate' | 'high' | 'extreme'
ALTER TABLE fighter_descriptors ADD COLUMN career_phase TEXT;
    -- 'prospect' | 'rising_contender' | 'title_challenger' | 'champion' |
    -- 'dominant_champion' | 'veteran' | 'gatekeeper' | 'journeyman' |
    -- 'comeback' | 'declining' | 'retirement_tour'
ALTER TABLE fighter_descriptors ADD COLUMN narrative_family TEXT;
    -- 'prodigy' | 'veteran' | 'fallen_champion' | 'cinderella_story' | ... or NULL
ALTER TABLE fighter_descriptors ADD COLUMN public_narrative TEXT;
    -- 'future_champion' | 'needs_one_more_win' | 'career_in_freefall' | ... or NULL
ALTER TABLE fighter_descriptors ADD COLUMN legacy_state TEXT;
    -- 'building' | 'established' | 'legendary' | 'forgotten' | ... 
```

**IMPORTANT:** The existing `career_stage` column stays — it's used by `news.py` for news generation. The new `career_phase` column is for UI display. They serve different purposes.

### 3.2 New cache tables (v3.11.0, MINOR)

4 new narrow cache tables:
- `gym_descriptors` (PK = gym_id, ~7 TEXT columns for identity/known_for/produces/weakness)
- `promotion_descriptors` (PK = promotion_id, ~5 TEXT columns)
- `division_descriptors` (PK = promotion_id + weight_class_id, ~5 TEXT columns)
- `daily_headlines` (PK = headline_date + headline_type, 8 headline types per day)

Plus: `interpretation_cache_meta` (1 row, tracks engine_version + last_built_date for cache invalidation).

### 3.3 Extend `fighter_memory_links.link_type` CHECK (v3.12.0, MINOR)

Current CHECK allows 4 values. Add ~6 more for the Memory Engine:
`'previous_fight'`, `'shared_gym'`, `'former_teammate'`, `'contract_dispute'`, `'injury_history'`, `'weight_class_change'`.

This requires a table rebuild per CONVENTIONS §16.6 (CHECK constraint changes can't use ALTER).

**Total: 3 MINOR schema bumps (v3.10.0, v3.11.0, v3.12.0). All idempotent migrations. No MAJOR bumps. No simulation-table changes.**

---

## 4. MVP Cut

The full spec has ~80 content rulesets. The MVP delivers ~40% of the content volume with ~80% of the player-perceived value:

| System | Full spec | MVP | Deferred |
|---|---|---|---|
| Career Phases | 11 | 6 (Prospect, Rising Contender, Champion, Veteran, Gatekeeper, Declining) | 5 (Title Challenger, Dominant Champion, Journeyman, Comeback, Retirement Tour) |
| Narrative Families | 14 | 4 (The Prodigy, The Veteran, The Fallen Champion, The Cinderella Story) | 10 |
| Public Narratives | 10 | 4 (Future Champion, Needs One More Win, Career in Freefall, Crowd Favourite) | 6 |
| Momentum | 5 | 5 (all — it's thin) | 0 |
| Pressure | 4 | 4 (all — it's thin) | 0 |
| Legacy | 6 | 4 (Building, Established, Legendary, Forgotten) | 2 (Controversial, Cult Hero) |
| Headlines | 8 | 4 (Top Story, Upset of the Week, Fastest Rising, Biggest Fall) | 4 |
| Gym Identity | 8 attributes | Defer entirely (data exists, low marginal value) | All |
| Memory link types | 10 | 4 (previous_fight, shared_gym, former_teammate, injury_history) | 6 |

**Deferred items ship as Phase 2.1, 2.2, etc.** The MVP is a complete, playable interpretation layer — not a half-built skeleton.

---

## 5. Corrected Implementation Order

The spec's order (§17) puts Snapshot Cache first. The Plan agent corrected to Context Engine first. The 2nd-opinion agent corrected BACK to Snapshot Cache first (context needs somewhere to write).

**Supervisor's ruling: The 2nd-opinion agent is right.** Cache must come before context. Context computed without a cache is discarded on every UI view — defeating the spec's "one interpretation pass per day" requirement.

### Phase 2.0 — Foundation (3 tasks, no code logic)

**Task 2.0a: CONVENTIONS.md §17 (UI Snapshot Rule) + §14.6 (cache-table clarification)**
- Docs-only. No code. 30 minutes.
- Establishes: UI reads snapshots ONLY (Office Mode). Fight Night Mode reads live tables. Interpretation layer is the ONLY writer to `*_descriptors`.
- This is the highest-leverage 30 minutes in the entire plan.

**Task 2.0b: Reconciliation addendum to the spec**
- Docs-only. 30 minutes.
- Maps each spec section to the existing asset it extends.
- Renames "Career Arc Engine" → "Career Phase Engine" everywhere.
- Clarifies "never modify the database" = "never modify simulation tables."
- Documents the Fight Resolution exception.

**Task 2.0c: Schema migration + backfill (v3.10.0)**
- Extend `fighter_descriptors` with 6 new columns.
- Backfill missing snapshots for 60 HoF legends + 450 Group B fighters.
- Create `interpretation_cache_meta` table.
- ~half-day.

### Phase 2.1 — Snapshot Cache + Context Engine (2 tasks)

**Task 2.1: Snapshot Cache (`snapshot_cache.py`) + new cache tables (v3.11.0)**
- Create `gym_descriptors`, `promotion_descriptors`, `division_descriptors`, `daily_headlines` tables.
- Create `snapshot_cache.py` — the orchestrator that calls sub-engines and writes to cache tables.
- Wire the daily pass as a **post-commit step in `run_tick`** (NOT a TICK_ADVANCED subscriber — avoids event-bus ordering hazards).
- The orchestrator is a skeleton — sub-engines can be stubs initially.
- ~500 lines + migration. 1-2 days.

**Task 2.2: Context Engine (`context_engine.py`)**
- `compute_momentum(conn, fighter_id)` → 'very_high' | 'high' | 'stable' | 'falling' | 'collapsing'
- `compute_pressure(conn, fighter_id)` → 'minimal' | 'moderate' | 'high' | 'extreme'
- `compute_trajectory(conn, fighter_id)` → 'rising' | 'peaking' | 'stable' | 'declining' | 'collapsing'
- Pure functions of DB state. No RNG. No text. Returns canonical labels.
- Bulk-load pattern (one SELECT, loop in Python, executemany UPDATE).
- Subscribes to FIGHT_RESOLVED, FIGHTER_RETIRED, TITLE_CHANGED, CONTRACT_EXPIRED for targeted single-fighter refresh.
- ~600 lines. 1-2 days.

### Phase 2.2 — Career Phase + Narrative (2 tasks)

**Task 2.3: Career Phase Engine (`career_phase_engine.py`)**
- 6 MVP phases (Prospect, Rising Contender, Champion, Veteran, Gatekeeper, Declining).
- Thin layer over `voice.describe_career_stage()` — promotes phrases to canonical labels.
- Writes to `fighter_descriptors.career_phase` (new column, NOT `career_stage`).
- ~300 lines. 1 day.

**Task 2.4: Narrative Families (`narrative_families.py`)**
- 4 MVP families (The Prodigy, The Veteran, The Fallen Champion, The Cinderella Story).
- Rules-based matcher. One family per fighter (or None).
- Voice variants for each family (3-5 phrases, RNG-seeded by fighter_id).
- Depends on Phase 2.2 (needs momentum/phase as inputs).
- ~400 lines code + ~400 lines voice strings. 2 days.

### Phase 2.3 — Memory + Headlines (2 tasks)

**Task 2.5: Memory Engine (`memory_engine.py`) + link_type CHECK expansion (v3.12.0)**
- `surface_memories(conn, fighter_a_id, fighter_b_id)` → list of memory strings.
- 4 MVP memory search types: previous_fight, shared_gym, former_teammate, injury_history.
- Extend `fighter_memory_links.link_type` CHECK with new values (table rebuild).
- Reader only — `memory_svc.py` remains the writer.
- Wire into matchmaking to surface memories on fight booking.
- This is the **highest story-density-per-line-of-code** system — "Last met six years ago" makes every fight feel meaningful.
- ~500 lines + migration. 2 days.

**Task 2.6: Headline Engine (`headline_engine.py`)**
- 4 MVP daily headlines: Top Story, Upset of the Week, Fastest Rising, Biggest Fall.
- Runs at end of daily pass. Writes to `daily_headlines` table.
- Voice-layered (uses `voice.py` for all text, no raw numbers).
- Check `punditry_svc.py` first to avoid duplication.
- ~400 lines. 1-2 days.

### Phase 2.4 — Legacy (1 task, can parallelize)

**Task 2.7: Legacy Engine (`legacy_engine.py`)**
- 4 MVP legacy states: Building, Established, Legendary, Forgotten.
- Applies to active AND retired fighters.
- Distinct from `hof_svc.py` (which is the binary induction event).
- Writes to `fighter_descriptors.legacy_state`.
- ~300 lines. 1 day.

### Phase 2.5 — Gym Identity (1 task, lowest priority)

**Task 2.8: Gym Identity Engine (`gym_identity_engine.py`)**
- Turn 8 gym INT columns + roster into a personality narrative.
- "Known For: Elite wrestlers. Produces: Grinding pressure fighters. Weakness: High injury rate."
- Mostly voice work over existing data.
- Writes to `gym_descriptors` table.
- ~300 lines. 1 day.

---

## 6. Wiring Map — Every Integration Point

### 6.1 Tick Processor Integration

```
tick_processor.run_tick(conn):
  1. Advance clock
  2. _check_retirements → publishes FIGHTER_RETIRED
  3. _check_contract_expiry → publishes CONTRACT_EXPIRED
  4. _check_injury_recovery
  5. _check_training_camps → publishes CAMP_COMPLETED
  6. bus.publish(TICK_ADVANCED) ← all 15+ subscribers run
  7. conn.commit()
  8. _run_daily_interpretation_pass(conn) ← NEW (Phase 2.1)
     ↑ runs AFTER commit, sees all committed writes
     ↑ writes to *_descriptors + daily_headlines in a separate transaction
     ↑ can be skipped on bulk-tick (run_tick(steps=N)) and run once at end
```

### 6.2 Event Bus Integration

The interpretation layer subscribes to 4 events for **targeted single-fighter refresh** (fast, ~5ms per fighter):
- `FIGHT_RESOLVED` → refresh the two fighters who fought
- `FIGHTER_RETIRED` → refresh the retiring fighter + compute legacy
- `TITLE_CHANGED` → refresh the new champion + the dethroned champion
- `CONTRACT_EXPIRED` → refresh the fighter whose contract expired

The **full daily pass** (all 4450 fighters) runs as a post-commit step in `run_tick`, NOT as a subscriber. This avoids event-bus ordering hazards.

### 6.3 CTk App Integration

```python
# src/ui/app.py — CageEmpireApp.__init__
# After the existing 15 register_subscribers calls:

try:
    from interpretation import register_subscribers as _register_interpretation
    _register_interpretation()  # registers 4 event-bus subscribers
except ImportError:
    pass
```

The `interpretation/__init__.py` exposes a single `register_subscribers()` that registers all 4 event subscribers (FIGHT_RESOLVED, FIGHTER_RETIRED, TITLE_CHANGED, CONTRACT_EXPIRED).

### 6.4 UI Integration (Phase 3+ — screens not built yet)

When screens are built (Phase 3 / Stage 6.3+), they read from cache tables:

```python
# CORRECT — reads from snapshot cache
conn.execute("SELECT career_phase, momentum, pressure, narrative_family,
              public_narrative, legacy_state, overall_desc
              FROM fighter_descriptors WHERE fighter_id=?", (fid,))

# WRONG — reads from simulation tables (CONVENTIONS §17 violation)
conn.execute("SELECT punch_power, cardio, fight_iq FROM fighter_attributes
              WHERE fighter_id=?", (fid,))
```

**Exception:** Fight Resolution screen (Task 6.7) reads from `fight_beats` directly:
```python
# CORRECT for Fight Night Mode — reads live simulation tables
conn.execute("SELECT * FROM fight_beats WHERE fight_id=? ORDER BY round_number, beat_number", (fight_id,))
# Then applies voice.py in real-time for commentary
```

### 6.5 Save/Load Integration

- Cache tables are in the DB → they save/load automatically with `save_game()` / `load_game()`.
- No special handling needed.
- `interpretation_cache_meta` table tracks engine version. On version mismatch (e.g., after a code update that changes narrative family rules), the next daily pass rebuilds all caches.

### 6.6 Voice.py Integration

The interpretation layer calls `voice.py` for ALL text production:
- `voice.describe_attribute(name, value)` → "elite", "iron chin"
- `voice.describe_career_stage(age, wins, losses, draws)` → "top prospect"
- `voice.describe_overall(fighter_data)` → full sentence summary
- `voice.describe_potential(potential)` → "high-end potential"

The interpretation layer ADDS higher-level meaning on top:
- `context_engine.compute_momentum()` → "high" (canonical label)
- `interpretation_engine.format_momentum_phrase("high", rng)` → "riding a hot streak — four in a row, the division is on notice" (voice variant)

**The test:** at the end of Phase 2, open a fighter profile. If you see `Momentum: High`, the layer is a spreadsheet. If you see `Momentum: riding a hot streak`, the layer is CAGE EMPIRE.

---

## 7. Performance Budget

| Operation | Frequency | Naive cost | Batched cost | Budget |
|---|---|---|---|---|
| Daily interpretation pass (all 4450 fighters) | 1/day | ~22s | ~0.5s | <1s |
| Targeted single-fighter refresh | Per event | ~50ms | ~5ms | <10ms |
| Memory resurfacing (one fight booking) | Per booking | ~200ms | ~50ms | <100ms |
| Daily headlines (4 types) | 1/day | ~400ms | ~100ms | <200ms |
| Snapshot backfill (60 legends + 450 Group B) | One-time | N/A | ~2s | <5s |

**The daily pass must use the bulk-load pattern from `career_arc._process_career_arc()`:**
1. One `SELECT ... FROM fighters JOIN fighter_career JOIN fighter_personality WHERE is_active=1` → fetch all 4450 rows.
2. Loop in Python, compute labels (pure CPU, no DB).
3. `executemany("UPDATE fighter_descriptors SET ...")` → batch write.

This is the ONLY way to hit <1 second.

---

## 8. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Naming collision (career_arc.py vs Career Arc Engine) | CRITICAL but cheap to fix | Rename to Career Phase Engine in the reconciliation addendum. 5 minutes. |
| Performance (22-second ticks if naive) | HIGH | Follow career_arc.py bulk-load pattern. Budget <1s. |
| Fight Resolution exception not documented | HIGH (architectural) | Document in CONVENTIONS §17.1 before any code. |
| 60 HoF legends + 450 Group B fighters missing snapshots | MEDIUM | Backfill as Task 2.0c (one-time script, <5s). |
| ~80 rulesets too much for one pass | MEDIUM | MVP cut to ~40% (§4). Deferred items ship as Phase 2.1, 2.2. |
| Event-bus ordering hazard | MEDIUM | Daily pass runs post-commit, NOT as a subscriber. Targeted refresh subscribes LAST. |
| Determinism (RNG in voice.py) | LOW | Snapshot cache IS the solution (RNG seeded by fighter_id, cached in DB). |
| UI migration | LOW (UI barely exists) | Convention established BEFORE screens built. Zero migration cost. |

---

## 9. The "Uniqueness" Concern

The user said: "We are in danger of losing the uniqueness of this game."

**What makes CAGE EMPIRE unique:**
1. §14 — no raw numbers in the UI (every attribute → phrase via voice.py)
2. The player collects stories, not fighters (5 narrative fantasies)
3. Anticipation is the dopamine loop ("I wonder what happens next")

**How Phase 2 reinforces this:**
- Narrative Families, Memory Engine, Headline Engine all generate stories
- The "UI reads snapshots only" rule structurally prevents sliding back to "show the user the raw numbers"
- The interpretation layer translates `won 5 in a row` into `The Prodigy — five fight win streak, ready for Top-10 opponent`

**What we must NOT lose:**
1. Letting raw numbers leak into the UI "just this once" — the rule must be absolute
2. Building the interpretation layer as "translation" instead of "narrative" — every label needs voice variants, every summary needs RNG-based phrasing
3. Letting the simulation grow during Phase 2 — the spec's §1 freeze is correct and must be enforced at code review

**The deepest risk:** If Phase 2 ships as a thin labels-only layer ("momentum: high"), the subsequent UI tasks will build screens around those labels and the game will feel like a labeled spreadsheet. If Phase 2 ships as a voice-driven layer ("riding a hot streak — four in a row, the division is on notice"), the UI tasks will build screens around sentences and the game will feel like a magazine.

**The interpretation layer must be RICH, not thin.** A dumb UI fed by a thin interpretation layer produces a dumb game. A dumb UI fed by a rich interpretation layer produces CAGE EMPIRE.

---

## 10. Estimated Effort

| Task | Lines (code) | Lines (voice) | Effort |
|---|---|---|---|
| 2.0a CONVENTIONS §17 | 0 (docs) | 0 | 30 min |
| 2.0b Reconciliation addendum | 0 (docs) | 0 | 30 min |
| 2.0c Schema migration + backfill | ~100 | 0 | half-day |
| 2.1 Snapshot Cache | ~500 | 0 | 1-2 days |
| 2.2 Context Engine | ~600 | 0 | 1-2 days |
| 2.3 Career Phase Engine | ~300 | ~200 | 1 day |
| 2.4 Narrative Families (4 MVP) | ~400 | ~400 | 2 days |
| 2.5 Memory Engine + link_type | ~500 | 0 | 2 days |
| 2.6 Headline Engine (4 MVP) | ~400 | ~200 | 1-2 days |
| 2.7 Legacy Engine (4 MVP) | ~300 | ~100 | 1 day |
| 2.8 Gym Identity Engine | ~300 | ~200 | 1 day |
| **Total** | **~3400** | **~1100** | **~2-3 weeks** |

**This is a Stage, not a Phase.** The spec frames it as "Phase 2" — that framing is correct. The implicit framing that it's one or two tasks is wrong by an order of magnitude.

---

## 11. Open Questions for the Supervisor

1. **MVP cut:** Approve the MVP cut (§4) — 6 career phases, 4 narrative families, 4 public narratives, 5 momentum, 4 pressure, 4 legacy, 4 headlines, 4 memory types? Or do you want the full spec in one pass?

2. **Implementation order:** Approve the corrected order (§5) — Snapshot Cache → Context Engine → Career Phase → Narrative Families → Memory → Headlines → Legacy → Gym Identity? Or do you prefer a different order?

3. **Gym Identity:** Defer entirely to Phase 2.1 (data exists, low marginal value)? Or include in the MVP?

4. **The "rich not thin" principle:** Approve the requirement that every derived label has a voice variant (e.g., momentum="high" → "riding a hot streak")? This doubles the voice string count but is the difference between CAGE EMPIRE and a labeled spreadsheet.

5. **Simulation freeze:** Confirm that NO simulation systems will be added during Phase 2. The interpretation layer is read-only (except for cache tables). If an edge case requires a sim change, it's deferred to Phase 3.

6. **CONVENTIONS.md §17:** Approve adding the UI Snapshot Rule as a new convention BEFORE any Phase 2 code? This is the highest-leverage 30 minutes in the plan.

---

## 12. Sign-off

Once the supervisor answers the 6 open questions, the implementation plan is ready for delegation. Each task (2.0a through 2.8) is delegated to a `full-stack-developer` subagent per CONVENTIONS §8 + §11, with the supervisor reviewing + signing off before any git push.

**No coding begins until the supervisor approves this plan.**
