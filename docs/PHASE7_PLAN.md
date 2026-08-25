# Phase 7 Plan — Cleanup + Documentation + Long-Run Validation

**Date:** 2026-08-25
**Status:** PLANNING ONLY — no code changes yet
**Task ID:** PHASE7-CLEANUP-DOCS-SOAKS
**Prerequisites:** Phase 6 complete (commit `c01f6f1`). All 7 HIGH + 5 MEDIUM audit violations resolved. Remaining: 12 borderline §17.4 "Rich Not Thin" issues, 1 stale test failure, stale docs, stale JS comments, long-run soaks.

---

## Background

After Phase 6, the project is in good shape:
- 8/8 invariants PASS
- `app_web` imports OK (76 methods)
- All 24 web screens audited; 7 HIGH + 5 MEDIUM violations resolved
- 2 NEW interpretation engines (`gym_identity_engine`, `promotion_engine`) populate cache tables
- Schema 3.37.0, ENGINE_VERSION 1.10.0
- Economics tuned (Phase 3 + 4) and validated through 30-day soaks (all 10 promos HEALTHY)

What remains is cleanup, documentation, and long-run validation.

---

## Tasks (5 groups)

### Group A — Phase 6.5: Borderline §17.4 "Rich Not Thin" Cleanup (12 violations)

**Goal:** Drop raw 0-100 ints from API JSON payloads where the UI only displays voice phrases. Per §17.4 strict interpretation, only voice phrases should cross the API boundary.

**The 12 violations** (from `docs/PHASE5_SCREEN_AUDIT.md`):

| # | File:line | Issue | Fix |
|---|---|---|---|
| 1 | `app_web.py:2554-2556` | Dashboard returns raw `reputation`/`fan_trust` ints (used for bar widths) | Drop from JSON; JS uses voice phrase for bar width via tier-based mapping (gold=100%, steel=60%, crimson=25%) |
| 2 | `app_web.py:6716` | `_fighter_brief` returns raw `marketability` int (commented "NEVER shown raw") | Drop from JSON |
| 3 | `app_web.py:5475-5505` | Calendar conflict-detection loop O(N×M) iterations | Replace with date→events dict lookup |
| 4 | `app_web.py:12827+` | `get_training_camps_data` reads `training_camps` directly | Audit + decide if `training_camp_descriptors` cache is needed (likely not — training camps are transient, not part of §17 cache taxonomy) |
| 5 | `app_web.py:9602` | Scouting returns raw `scout_confidence` 0-100 (UI shows phrase) | Drop from JSON |
| 6 | `app_web.py:9348` | Staff Market returns raw `skill_level` int alongside `skill_phrase` | Drop from JSON |
| 7 | `app_web.py:13300+` | Finance returns raw `reputation`/`fan_trust`/`overall_rating` ints | Drop from JSON |
| 8 | `app_web.py:6456` | Rivalries returns raw `rivalry_heat` int (B6 fixed JS display, but int is still in JSON) | Drop from JSON |
| 9-10 | `gyms.js:249, 387, 412` | Already addressed by B4, but verify the carve-out comments | No code change — just verify |
| 11 | `app_web.py:6647-6654` | Per-fighter rank computation (partially addressed by B2 batching) | Verify B2 fully addressed; if not, finish |
| 12 | `app_web.py:6673-6677` | Per-fighter simulation_clock lookup (addressed by B2) | Verify B2 fully addressed |

**Estimated effort:** ~1 day (most are 1-line drops; #3 + #4 need investigation)

**Acceptance criteria:**
- [ ] Raw 0-100 ints dropped from JSON payloads (where UI only displays voice phrases)
- [ ] JS UIs still render correctly (verify via node -c + smoke test)
- [ ] 8/8 invariants PASS
- [ ] app_web imports OK

---

### Group B — Stale JS Comment Cleanup

**Goal:** Remove stale JS comments that contradict the post-Phase-6 code behavior.

**Files to fix:**
- `src/web/js/rivalries.js:35-42` — comment claims `rivalry_heat` is "OK to display" but B6 removed the raw int display. Update or remove the comment.
- `src/web/js/gyms.js:41-46` — comment claims camp-state ratings are "OK to display" but B4 changed behavior. Verify + update.
- `src/web/js/scouting.js:43-46` — comment claims `scout_confidence` is "scout's own rating, NOT a fighter attribute" — verify still accurate after Group A drops the raw int.
- `src/web/js/staff_market.js:148` — comment claims `skill_level` is "NEVER displayed raw" — verify still accurate after Group A drops the raw int.

**Estimated effort:** ~0.25 day

---

### Group C — Fix test_pre_b1_fixes.py Cases F+G (real defect)

**Root cause (diagnosed 2026-08-25):**
- `scripts/test_pre_b1_fixes.py` line 137: `SEEDED_CLOCK_DATE = "2026-07-20"` — expects the seeded clock to be 2026-07-20
- `src/build_db.py` actually seeds the clock to TODAY's real date (e.g., 2026-08-25 when run today)
- Test runs `tick_processor.run_tick(conn)` which advances 1 day → 2026-08-26
- Test sets fighter 1's DOB to `1980-07-21` (line 779), making July 21 the birthday
- Retirement check is birthday-only (`src/tick_processor.py:1129` — "DOB month/day == current_date month/day")
- 2026-08-26 is NOT July 21 → retirement never fires → 6 cascading failures in Cases F+G

**Fix:**
1. **In `scripts/test_pre_b1_fixes.py` `build_fresh_db()` (line 161):** after `subprocess.run([sys.executable, str(SRC_DIR / "seed_data.py")])`, explicitly set the simulation_clock to `2026-07-20` so the test is deterministic (independent of when it runs):
   ```python
   # Force deterministic clock — Case F+G depend on tick advancing to
   # 2026-07-21 (fighter's birthday) for retirement to fire. build_db.py
   # seeds the clock to today's real date, which breaks the test when
   # run on any day other than July 20.
   conn = sqlite3.connect(DB_PATH)
   conn.execute("UPDATE simulation_clock SET current_date='2026-07-20', current_day=20, current_week=3, current_month=7, current_year=2026 WHERE clock_id=1")
   conn.commit()
   conn.close()
   ```
2. **Verify the fix:** run `python3 scripts/test_pre_b1_fixes.py` — expect 75/75 PASS (was 69/75).

**Files to modify:**
- `scripts/test_pre_b1_fixes.py` — `build_fresh_db()` function (line 161)

**Estimated effort:** ~0.25 day

**Acceptance criteria:**
- [ ] `python3 scripts/test_pre_b1_fixes.py` returns 75/75 PASS (was 69/75)
- [ ] Test runs deterministically (PASS on any day, not just July 20)
- [ ] 8/8 invariants PASS (the test uses its own DB, not the production one — but verify)

---

### Group D — Update CURRENT_SYSTEM_STATE.md

**Goal:** Reflect Phase 5 + 6 changes in the canonical doc. `docs/CURRENT_SYSTEM_STATE.md` was last updated 2026-08-15 (pre-Phase-3 economics) and doesn't reflect:
- Phase 5 (watchlist, dashboard redesign, attribute phrase fix, visual richness)
- Phase 6 (gym_identity_engine, promotion_engine, 9 audit-finding fixes, ENGINE_VERSION 1.10.0, schema 3.37.0)

**Sections to update:**
1. **Header metadata** — `Last updated:` 2026-08-25; `Schema version:` 3.37.0; add `ENGINE_VERSION:` 1.10.0
2. **§1 What exists — All 22 screens** — note the watchlist feature + dashboard redesign + voice compliance fixes
3. **§2 What works** — add: gym_descriptors (329 rows) + promotion_descriptors (10 rows) populated; watchlist API (3 methods); radar chart uses tier pct not raw attributes
4. **NEW §3.5 — Phase 5 + 6 changes summary** — brief bulleted list of what changed
5. **Test count** — verify `scripts/test_*.py` count + update if changed

**Files to modify:**
- `docs/CURRENT_SYSTEM_STATE.md`

**Estimated effort:** ~0.5 day

---

### Group E — Phase 7 Long-Run Validation (5y/10y/20y soaks)

**Goal:** Per v7 plan Phase 5 (`docs/NEXT_LEVEL_PLAN_V4.md` lines 122-126) — validate economics sustainability over multi-year horizons. Catch regressions that 30-day soaks don't reveal.

**Approach:**
1. **5-year soak first** (1,825 ticks). If PASS, run 10y (3,650 ticks) + 20y (7,300 ticks).
2. Track metrics at every 30-day checkpoint (already done by `scripts/soak_test.py`).
3. Profile bottlenecks — identify any super-linear growth in DB tables or per-tick time.
4. Verify the new engines (`gym_identity_engine`, `promotion_engine`) stay populated through sim cycles (they should fire on the daily interpretation pass).
5. Verify the watchlist feature doesn't break over long runs (player_decisions table growth).

**Files to modify:**
- `docs/PHASE7_SOAK_ANALYSIS.md` (NEW) — analysis report with metrics, charts (text-based), conclusions
- `docs/1YR_SIM_ANALYSIS.md` — update with post-Phase-6 economics numbers (was based on pre-Phase-3 economics)
- `docs/CURRENT_SYSTEM_STATE.md` — add §4.5 "Long-run soak results" pointing to the new analysis

**Estimated effort:** ~2-3 days (mostly waiting for soaks to run + writing analysis)

**Acceptance criteria:**
- [ ] 5-year soak: all 10 promos stay HEALTHY through 1,825 ticks, 0 tick errors
- [ ] 10-year soak: all 10 promos stay HEALTHY through 3,650 ticks
- [ ] 20-year soak: all 10 promos stay HEALTHY through 7,300 ticks (or document which promos went DISTRESSED + why)
- [ ] No super-linear table growth (finance_transactions, news_items, fight_history should be pruned)
- [ ] `gym_descriptors` + `promotion_descriptors` stay populated (1+ rows each) throughout
- [ ] Per-tick time stays <500ms avg (no perf regression)
- [ ] Analysis report produced

---

## Implementation Order

```
Day 1 (parallel):
  Group A — Phase 6.5 (12 borderline raw-int drops) — general-purpose subagent
  Group B — Stale JS comment cleanup — general-purpose subagent (parallel with A; touches different files mostly)
  Group C — Fix test_pre_b1_fixes Cases F+G — general-purpose subagent (touches only test script)

Day 2:
  Group D — Update CURRENT_SYSTEM_STATE.md — general-purpose subagent
  Group E starts — 5-year soak (background, ~30 min runtime)
  
Day 3:
  Group E continues — 10y + 20y soaks (background, ~1-2 hours each)
  Supervisor review + analysis report

Day 4:
  Final verification + commit (hold for user-supplied push token)
  Worklog PHASE7 signoff
```

**Total estimated wall-clock:** ~3-4 days with parallelism

---

## Subagent Delegation Strategy

| Task | Subagent type | Why |
|---|---|---|
| Group A (12 raw-int drops) | general-purpose | Code changes across `app_web.py` (multiple methods) + verification |
| Group B (stale comments) | general-purpose | Small JS changes + verification |
| Group C (test fix) | general-purpose | Small Python change to test script + verification (run test, confirm 75/75) |
| Group D (docs update) | general-purpose | Documentation update — needs to read current code + summarize changes |
| Group E (soaks) | general-purpose | Run soaks + write analysis report |

For Group A: launch as a single subagent that handles all 12 violations sequentially (avoids file conflicts on `app_web.py`).

For Group E: the subagent runs the soaks + writes the analysis report. Supervisor reviews the report + signs off.

---

## What we're NOT doing in Phase 7

- ❌ NO new screens (all 24 implemented)
- ❌ NO new schema/tables (Phase 5 + 6 schemas are stable)
- ❌ NO new dependencies
- ❌ NO fight engine changes
- ❌ NO news system changes
- ❌ NO strict §17.1 LOW violations (would require building new cache tables — large scope, defer to Phase 8 if user requests)
- ❌ NO UI redesign (Phase 5 Dashboard is current state; other screens redesigned only if user reports issues)

---

## Success criteria

- [ ] Group A: 12 borderline raw-int drops applied; voice phrases only in JSON payloads
- [ ] Group B: stale JS comments updated/removed
- [ ] Group C: `test_pre_b1_fixes.py` returns 75/75 PASS (was 69/75)
- [ ] Group D: `CURRENT_SYSTEM_STATE.md` reflects Phase 5 + 6 changes
- [ ] Group E: 5y/10y/20y soaks PASS (all 10 promos HEALTHY, 0 tick errors)
- [ ] Analysis report produced at `docs/PHASE7_SOAK_ANALYSIS.md`
- [ ] 8/8 invariants PASS throughout
- [ ] app_web imports OK throughout
- [ ] Committed (push deferred until user supplies new token)
- [ ] Worklog updated with PHASE7-SIGNOFF entry

---

## Open questions for user (before starting)

None — all groups are well-scoped. Proceed with implementation.
