# Phase 6 Plan — Audit Findings Remediation + Descriptor Engines

**Date:** 2026-08-17
**Status:** PLANNING ONLY — no code changes yet
**Task ID:** PHASE6-AUDIT-REMEDIATION
**Prerequisites:** Phase 5 UI/UX Polish complete (commit `3672ebf`). All invariants PASS, all 24 web screens audited.
**Active UI:** pywebview desktop app — `src/app_web.py` (~15,500 LOC, 76 public API methods) + `src/web/` (24 JS modules, 24 CSS files, index.html).

---

## Background

The Phase 5 Screen Audit (read-only, report at `docs/PHASE5_SCREEN_AUDIT.md`) found **34 violations** across the 24 web screens:
- **7 HIGH** — raw attribute/rating exposure + N+1 query patterns + cache table bypass
- **18 MEDIUM** — suboptimal patterns (raw ints in JSON-but-not-displayed, correlated subqueries)
- **9 LOW** — strict-letter §17.1 violations for identity/record fields where no cache table exists

Phase 6 addresses the 7 HIGH + the top 5 MEDIUM (12 total). The remaining 13 MEDIUM/LOW are borderline §17.4 "Rich Not Thin" issues — they'd need a separate, more philosophical discussion about whether raw ints should cross the API boundary even if not displayed.

Phase 6 also addresses a gap discovered during audit planning: the `gym_descriptors` and `promotion_descriptors` cache tables exist in the schema but are EMPTY (0 rows) because the sub-engines that populate them (`gym_identity_engine.py`, `promotion_engine.py`) were never built. They're skeleton no-ops in `snapshot_cache.py:804-829`. This means Fix #4 (gyms screen) and Fix #10 (rival promotions screen) can't just "switch to reading the cache" — they need the cache to be populated first.

---

## Tasks (12 items, grouped by dependency)

### Group A — Cache Engine Foundations (must ship before Group B fixes #4 + #10)

#### Task A1 — Build `gym_identity_engine.py` (NEW file)
**Audit driver:** Fix #4 (gyms screen HIGH violation)
**Current state:** `src/interpretation/snapshot_cache.py:804-814` calls `compute_all_gym_descriptors` from `interpretation.gym_identity_engine`, but that module doesn't exist. `gym_descriptors` table is empty (0 rows). Schema:
```
gym_descriptors(
  gym_id INTEGER PRIMARY KEY,
  identity_label TEXT,           -- e.g., "The Striking Lab"
  known_for TEXT,                -- voice phrase, e.g., "produces elite strikers"
  produces TEXT,                 -- voice phrase for fighter archetype output
  weakness TEXT,                 -- voice phrase for what the gym lacks
  development_rating_desc TEXT,  -- voice phrase for facility_quality (gold/steel/crimson tier)
  snapshot_version INTEGER,
  updated_at TEXT
)
```
**Scope:** Build the engine that populates this table. Voice phrases derived from:
- `gyms.reputation` (0-100) → reputation tier phrase (use existing `_reputation_phrase` helper pattern from `app_web.py:210`)
- `gyms.facility_quality` (0-100) → quality phrase (use existing `_gym_quality_phrase` at `app_web.py:429`)
- `gyms.medical_support`, `sparring_depth`, `development_focus`, `weight_cut_support` (each 0-100) → tier phrases
- `gyms.specialty` (TEXT, e.g., "striking", "grappling") → `produces` phrase
- Aggregate these into `identity_label` + `known_for` + `weakness` + `development_rating_desc`

**Files:**
- NEW: `src/interpretation/gym_identity_engine.py`
- Modified: `src/interpretation/snapshot_cache.py` — remove the `try/except ImportError` skeleton at line 811-813, call directly
- Modified: `src/interpretation/snapshot_cache.py` — bump `ENGINE_VERSION` from `"1.9.0"` to `"1.10.0"` so the cache rebuilds with the new gym descriptors

**Estimated complexity:** M (1 day)

**Acceptance criteria:**
- [ ] `gym_identity_engine.py` exists with `compute_all_gym_descriptors(conn, current_date)` function
- [ ] After running the interpretation pass, `gym_descriptors` table has 1 row per gym (300+ gyms)
- [ ] Each row has all 6 voice phrase fields populated (no NULLs)
- [ ] Voice phrases use the existing tier system (gold/steel/crimson mapping)
- [ ] 8/8 invariants PASS
- [ ] `app_web.py` imports OK

---

#### Task A2 — Build `promotion_engine.py` (NEW file)
**Audit driver:** Fix #10 (rival promotions MEDIUM violation)
**Current state:** `src/interpretation/snapshot_cache.py:817-829` calls `compute_all_promotion_descriptors` from `interpretation.promotion_engine`, but that module doesn't exist. `promotion_descriptors` table is empty (0 rows). Schema:
```
promotion_descriptors(
  promotion_id INTEGER PRIMARY KEY,
  prestige_desc TEXT,             -- voice phrase for reputation
  market_position_desc TEXT,     -- voice phrase for ownership + broadcast tier
  roster_quality_desc TEXT,      -- voice phrase for average roster quality
  snapshot_version INTEGER,
  updated_at TEXT
)
```
**Scope:** Build the engine that populates this table. Voice phrases derived from:
- `promotions.reputation` (0-100) → `prestige_desc` (use existing `_reputation_phrase` pattern)
- `promotions.fan_trust` (0-100) → trust phrase (use existing `_fan_trust_phrase` at `app_web.py:218`)
- `promotions.broadcast_tier` (TEXT) + `ownership_type` (TEXT) → `market_position_desc`
- Average `fighter_descriptors.overall_desc` tier across the promo's roster → `roster_quality_desc`

**Files:**
- NEW: `src/interpretation/promotion_engine.py`
- Modified: `src/interpretation/snapshot_cache.py` — remove the `try/except ImportError` skeleton at line 825-828
- Modified: `src/interpretation/snapshot_cache.py` — bump `ENGINE_VERSION` (already bumped in A1, but ensure both engines fire on cache rebuild)

**Estimated complexity:** M (1 day)

**Acceptance criteria:**
- [ ] `promotion_engine.py` exists with `compute_all_promotion_descriptors(conn, current_date)` function
- [ ] After running the interpretation pass, `promotion_descriptors` table has 10 rows (one per promo)
- [ ] Each row has all 4 voice phrase fields populated (no NULLs)
- [ ] 8/8 invariants PASS
- [ ] `app_web.py` imports OK

---

### Group B — Voice Compliance Fixes (HIGH priority, after Group A for #4 + #10)

#### Task B1 — Fix #1: Matchmaking radar chart leaks raw 25 attributes
**Audit citation:** `matchmaking.js:1678-1742` (`renderRadarChart`) + `app_web.py:8117-8118` (`get_fight_compare`)
**Problem:** `get_fight_compare` returns `red_attributes` + `blue_attributes` dicts of all 25 raw 0-100 attribute values. The JS averages them into 5-axis polygon coordinates. Player sees relative attribute magnitudes as polygon shapes — clear §14 violation.
**Fix:** Route through `fighter_descriptors.attribute_descriptors` (JSON of 26 voice phrases). Use `phraseTier()` (the helper fixed in Phase 5 Task 2.5, `fighter_profile.js:75-101`) to convert each phrase to a tier pct (gold=100%, steel=60%, crimson=25%). Polygon points become tier-based, not raw-attribute-based.
**Files:**
- Modified: `src/app_web.py` `get_fight_compare` method (line ~8117) — replace `red_attributes`/`blue_attributes` dicts of raw ints with `red_attribute_phrases`/`blue_attribute_phrases` dicts of voice phrases + `red_attribute_tiers`/`blue_attribute_tiers` dicts of tier pct values
- Modified: `src/web/js/matchmaking.js` `renderRadarChart` (lines 1678-1742) — use the tier pct values for polygon points, optionally show phrase on hover
**Estimated complexity:** M (0.5 day)
**Acceptance criteria:**
- [ ] `get_fight_compare` response no longer contains raw 0-100 attribute ints
- [ ] `matchmaking.js` radar chart still renders (using tier pct values)
- [ ] Hovering over a radar axis shows the voice phrase (not a raw number)
- [ ] 8/8 invariants PASS, app_web imports OK

#### Task B2 — Fix #2: Matchmaking N+1 query
**Audit citation:** `app_web.py:5820-5832` (`get_matchmaking_data`) + `app_web.py:6607-6632` (`_fighter_brief`)
**Problem:** For each eligible fighter (100+ on a major promo), `get_matchmaking_data` calls `self._fighter_brief(conn, fid)` which runs 4+ subqueries per fighter (rank, clock, recent_form, title_chip). On a 100-fighter roster this is 400+ queries per Matchmaking screen load.
**Fix:** Batch into a single JOIN query. Use a window function for rank computation. Fetch the simulation_clock once (it's constant per request). Cache recent_form via a single `fight_history` JOIN with `GROUP BY fighter_id`.
**Files:**
- Modified: `src/app_web.py` `get_matchmaking_data` (line ~5676) — rewrite the per-fighter loop into a single batched query
- Modified: `src/app_web.py` `_fighter_brief` (line ~6607) — keep for backward compat (other callers may use it) but mark deprecated
**Estimated complexity:** M (1 day)
**Acceptance criteria:**
- [ ] `get_matchmaking_data` runs 1 query (with JOINs) instead of N+1
- [ ] Matchmaking screen load time on 100-fighter roster drops from ~2-3s to <300ms (measure via timing)
- [ ] Same response shape returned (no breaking changes to JS)
- [ ] 8/8 invariants PASS

#### Task B3 — Fix #3: Event Builder N+1 query
**Audit citation:** `app_web.py:4332-4339` (`get_event_builder_data`)
**Problem:** Inside the per-fighter loop, a subquery `SELECT SUM(...) FROM fight_history WHERE fighter_id=?` computes the W/L/D record per fighter. Should JOIN `fighter_career` (which already has `record_wins/losses/draws` columns).
**Fix:** Replace the per-fighter subquery with a LEFT JOIN to `fighter_career` on `fighter_id`. The columns are already there.
**Files:**
- Modified: `src/app_web.py` `get_event_builder_data` (line ~4163) — rewrite the eligible-fighters query to JOIN `fighter_career`
**Estimated complexity:** S (0.5 day)
**Acceptance criteria:**
- [ ] `get_event_builder_data` no longer has a per-fighter subquery for record
- [ ] Response shape unchanged
- [ ] 8/8 invariants PASS

#### Task B4 — Fix #4: Gyms screen reads simulation table + shows raw 0-100 ratings
**Audit citation:** `app_web.py:12752-12757` (`get_gyms_data`) + `gyms.js:387,412`
**Problem:** `get_gyms_data` reads `gyms` simulation table directly + returns 6 raw 0-100 gym ratings (`reputation`, `facility_quality`, `medical_support`, `sparring_depth`, `development_focus`, `weight_cut_support`), all displayed as numeric values + bar fills. The `gym_descriptors` cache table exists per §17.3 but is unused — and empty (Task A1 fills it).
**Fix:** After Task A1 ships, switch `get_gyms_data` to JOIN `gym_descriptors`. Return voice phrases instead of raw ints. Use raw ints ONLY for bar fill widths (per the §17.4 "Rich Not Thin" carve-out for visualization widths).
**Files:**
- Modified: `src/app_web.py` `get_gyms_data` (line ~12758) — JOIN `gym_descriptors`, return voice phrases + bar widths
- Modified: `src/web/js/gyms.js` `renderStatBar` (line 387) + `renderMeter` (line 249) + reputation display (line 412) — display voice phrase, use raw int only for bar width
**Estimated complexity:** M (0.5 day)
**Depends on:** Task A1
**Acceptance criteria:**
- [ ] `get_gyms_data` reads from `gym_descriptors` (cache table) per §17.1
- [ ] Raw 0-100 ints NOT displayed in JS — only voice phrases
- [ ] Raw ints may still be in JSON for bar-width purposes (per §17.4 carve-out)
- [ ] 8/8 invariants PASS

#### Task B5 — Fix #5: Fighter Profile shows raw career_health int
**Audit citation:** `fighter_profile.js:306` + `app_web.py:3808`
**Problem:** `fighter_profile.js:306` displays raw `career_health` 0-100 int in the Career Health stat tile, despite `career_health_desc` voice phrase existing (fetched at `app_web.py:3745`).
**Fix:** Display the `career_health_desc` voice phrase. Use the raw int ONLY for the bar fill width (the existing stat bar at line 307).
**Files:**
- Modified: `src/web/js/fighter_profile.js` line 306 — replace `cs.career_health` display with `cs.career_health_desc` voice phrase
**Estimated complexity:** S (0.25 day)
**Acceptance criteria:**
- [ ] `fighter_profile.js:306` shows voice phrase, not raw int
- [ ] Bar fill still uses raw int for width (per §17.4 carve-out)
- [ ] 8/8 invariants PASS

#### Task B6 — Fix #6: Rivalries shows raw rivalry_heat int
**Audit citation:** `rivalries.js:238` + `app_web.py:6456`
**Problem:** `rivalries.js:238` displays raw `rivalry_heat` int alongside the voice `heat_phrase`. Player sees both.
**Fix:** Drop the raw int display. Keep the bar visual + phrase.
**Files:**
- Modified: `src/web/js/rivalries.js` line 238 — remove the raw int display
**Estimated complexity:** S (0.25 day)
**Acceptance criteria:**
- [ ] `rivalries.js:238` shows phrase only, no raw int
- [ ] Bar fill still uses raw int for width
- [ ] 8/8 invariants PASS

#### Task B7 — Fix #7: Gyms screen shows raw 0-100 ints for gym reputation + 5 stat bars
**Audit citation:** `gyms.js:387,412`
**Problem:** Same as Fix #4 — covered by Task B4. (Audit listed it twice from different citation angles.)
**Fix:** Merged into Task B4.
**Estimated complexity:** — (covered by B4)

#### Task B8 — Fix #10: Rival Promotions reads simulation table + returns raw ints
**Audit citation:** `app_web.py:3257-3266` + `app_web.py:3269-3278` (`get_rival_promotions`)
**Problem:** `get_rival_promotions` reads `promotions` simulation table directly + returns raw `reputation`/`fan_trust`/`current_cash` ints alongside voice phrases.
**Fix:** After Task A2 ships, JOIN `promotion_descriptors`. Return voice phrases. Use raw ints ONLY for bar widths.
**Files:**
- Modified: `src/app_web.py` `get_rival_promotions` (line ~3244) — JOIN `promotion_descriptors`
**Estimated complexity:** S (0.25 day)
**Depends on:** Task A2
**Acceptance criteria:**
- [ ] `get_rival_promotions` reads from `promotion_descriptors` cache (per §17.1)
- [ ] Raw 0-100 ints NOT displayed in JS — only voice phrases
- [ ] 8/8 invariants PASS

---

### Group C — Performance Fixes (MEDIUM priority, independent)

#### Task C1 — Fix #8: Roster correlated subqueries
**Audit citation:** `app_web.py:2886-2887` (`get_roster_data`)
**Problem:** Two correlated subqueries per row for `injury_count` + `susp_count`. With 20 rows/page = 40 subqueries.
**Fix:** LEFT JOIN to `injuries` + `suspensions` with `GROUP BY fighter_id` to compute counts in a single query.
**Files:**
- Modified: `src/app_web.py` `get_roster_data` (line ~2774) — rewrite the per-fighter subqueries as JOINs
**Estimated complexity:** S (0.5 day)
**Acceptance criteria:**
- [ ] `get_roster_data` no longer has per-row subqueries for injury/suspension counts
- [ ] Same response shape
- [ ] 8/8 invariants PASS

#### Task C2 — Fix #9: Rankings correlated subquery
**Audit citation:** `app_web.py:12352-12353` (`get_rankings_data`)
**Problem:** Correlated subquery per row for `last_outcome`. 15 rows = 15 subqueries.
**Fix:** LEFT JOIN to a `fight_history` subquery aliased with `MAX(fight_history_id)`.
**Files:**
- Modified: `src/app_web.py` `get_rankings_data` (line ~12184) — rewrite the last_outcome subquery as a JOIN
**Estimated complexity:** S (0.25 day)
**Acceptance criteria:**
- [ ] `get_rankings_data` no longer has per-row subquery for last_outcome
- [ ] Same response shape
- [ ] 8/8 invariants PASS

---

## Implementation Order (with dependencies)

```
Day 1 (parallel):
  Task A1 — gym_identity_engine.py (NEW file)
  Task A2 — promotion_engine.py (NEW file)
  [both run in parallel — independent modules]
  [both touch snapshot_cache.py but at different lines — A1 at :804, A2 at :817]

Day 2 (parallel after Group A):
  Task B1 — Matchmaking radar chart fix (depends on nothing new — phraseTier already exists from Phase 5)
  Task B2 — Matchmaking N+1 query fix (independent of B1)
  Task B3 — Event Builder N+1 query fix (independent)
  Task B4 — Gyms screen voice fix (depends on A1)
  Task B5 — Fighter Profile career_health fix (independent)
  Task B6 — Rivalries heat_phrase fix (independent)
  Task B8 — Rival Promotions voice fix (depends on A2)

Day 3 (parallel, can start any time):
  Task C1 — Roster correlated subqueries fix (independent)
  Task C2 — Rankings correlated subquery fix (independent)

Day 4:
  Supervisor review + verification + commit + push + worklog signoff
```

**Total estimated wall-clock:** ~3 days with full parallelism (vs ~6-7 days sequential).

---

## Subagent Delegation Strategy

| Task | Subagent type | Why |
|---|---|---|
| A1 (gym_identity_engine) | general-purpose | New module + voice phrase derivation logic. Needs to understand existing tier helpers (`_reputation_phrase`, `_gym_quality_phrase`) + the `gym_descriptors` schema. |
| A2 (promotion_engine) | general-purpose | Same pattern as A1 — new module + voice phrases from existing helpers. |
| B1 (radar chart fix) | general-purpose | Code changes to `app_web.py` (1 method) + `matchmaking.js` (1 function). Needs to understand the `phraseTier` pattern from Phase 5 Task 2.5. |
| B2 (matchmaking N+1) | general-purpose | Pure SQL optimization. Rewrite per-fighter loop as batched JOIN. |
| B3 (event builder N+1) | general-purpose | Pure SQL optimization. Replace subquery with JOIN. |
| B4 (gyms voice fix) | general-purpose | Depends on A1. Code changes to `app_web.py` + `gyms.js`. |
| B5 (career_health) | general-purpose | 1-line JS change. Trivial. |
| B6 (rivalries heat) | general-purpose | 1-line JS change. Trivial. |
| B8 (rival promos voice) | general-purpose | Depends on A2. 1-method change in `app_web.py`. |
| C1 (roster subqueries) | general-purpose | Pure SQL optimization. |
| C2 (rankings subquery) | general-purpose | Pure SQL optimization. |

For parallelism: launch A1 + A2 first (Day 1). Then launch B1+B3+B5+B6+C1+C2 in parallel on Day 2 (6 subagents — none touch overlapping files except `app_web.py` which is multi-method). Launch B4 (after A1 ships) + B8 (after A2 ships) + B2 on Day 2 afternoon.

**File conflict risk:** Tasks B1, B2, B3, B4, B5, B6, B8, C1, C2 all modify `src/app_web.py`. If launched in parallel they'll conflict. Safer strategy: **serialize the app_web.py changes** — run them sequentially OR carefully partition by method (each task touches a different method, but they all live in the same file).

**Revised parallelism:**
- Day 1: A1 + A2 in parallel (different files, no conflict)
- Day 2 morning: B5 + B6 + C2 in parallel (B5 + B6 touch JS files only, C2 touches app_web.py but a different method from B1-B4)
- Day 2 afternoon: B1 + B2 + B3 + B4 + B8 + C1 sequentially (all touch app_web.py — must serialize)
- Day 3: supervisor review + commit + push

Or simpler: launch each task with explicit instructions about which exact line range to modify, and have the supervisor merge them sequentially.

---

## What we're NOT doing in Phase 6

- ❌ NO new screens (all 24 implemented)
- ❌ NO new schema/tables (gym_descriptors + promotion_descriptors already exist; just need to be populated)
- ❌ NO new dependencies (vanilla Python + SQL)
- ❌ NO fight engine changes
- ❌ NO news system changes
- ❌ NO long-run soaks (Phase 7 territory)
- ❌ NO 13 MEDIUM/LOW "Rich Not Thin" borderline issues (raw ints in JSON-but-not-displayed — separate philosophical discussion)
- ❌ NO UI redesign (Phase 5 already did the Dashboard; other screens will be redesigned in later phases if user requests)

---

## Success criteria

- [ ] Task A1: `gym_identity_engine.py` built + `gym_descriptors` table populated (300+ rows)
- [ ] Task A2: `promotion_engine.py` built + `promotion_descriptors` table populated (10 rows)
- [ ] Task B1: Matchmaking radar chart no longer shows raw attributes
- [ ] Task B2: Matchmaking screen load time drops from ~2-3s to <300ms
- [ ] Task B3: Event Builder no longer has per-fighter record subquery
- [ ] Task B4: Gyms screen reads from `gym_descriptors` cache, shows voice phrases
- [ ] Task B5: Fighter Profile Career Health shows voice phrase, not raw int
- [ ] Task B6: Rivalries heat shows phrase only, not raw int
- [ ] Task B8: Rival Promotions reads from `promotion_descriptors` cache
- [ ] Task C1: Roster query no longer has per-row subqueries
- [ ] Task C2: Rankings query no longer has per-row subquery
- [ ] All 7 HIGH audit violations resolved
- [ ] Top 5 MEDIUM audit violations resolved (B5, B6, B4-partial, C1, C2)
- [ ] 8/8 invariants PASS throughout
- [ ] app_web imports OK throughout
- [ ] ENGINE_VERSION bumped from 1.9.0 → 1.10.0 (forces cache rebuild with new gym + promotion descriptors)
- [ ] 7-day soak test: all 10 promos stay HEALTHY, 0 tick errors
- [ ] Committed + pushed
- [ ] Worklog updated with PHASE6-AUDIT-REMEDIATION-SIGNOFF entry

---

## Open questions for user (before starting Phase 6)

1. **Borderline §17.4 "Rich Not Thin" issues (13 MEDIUM/LOW)** — these are cases where the API returns raw 0-100 ints alongside voice phrases, but the JS only displays the phrase. Per §17.4 the canonical label "should be the only thing crossing the API boundary." Strict interpretation says we should drop the raw ints from the JSON. Loose interpretation says it's fine because nothing displays them. **Recommendation:** Drop them — defensive + cleaner. But this affects 13 places and could break other consumers (e.g., the radar chart fix in B1 will need a tier-based replacement). Confirm direction before scoping a "Phase 6.5 Rich-Not-Thin cleanup."

2. **`ENGINE_VERSION` bump strategy** — bumping from 1.9.0 → 1.10.0 forces a full cache rebuild (4,470 fighter_descriptors + 300+ gym_descriptors + 10 promotion_descriptors). This takes ~30-60 seconds on first load after the upgrade. **Recommendation:** Ship the bump, accept the one-time cost. Player won't see it again unless we bump again.

3. **Performance budget for B2 (Matchmaking N+1)** — the audit cited "2-3s" as the current load time on 100-fighter rosters. After the fix, target is <300ms. But we haven't measured actual current performance. **Recommendation:** Measure before + after with a timing script, document the improvement in the worklog.

4. **Task ordering within Day 2** — given the `app_web.py` file conflict risk, do you prefer (a) serialize all 6 app_web.py-touching tasks (slower but safer), or (b) partition by method + use MultiEdit-style atomic edits (faster but requires careful supervisor review)?
