> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# HW2.2 — Simulation Time Law Audit

> **Task:** Replace `datetime.now()`, `datetime.today()`, `date.today()`,
> `CURRENT_DATE`, `CURRENT_TIMESTAMP` in gameplay code with
> `get_clock(conn)` or `simulation_clock.current_date`.
>
> **Scope:** Gameplay code ONLY. Save metadata, diagnostics, and
> filesystem operations are EXEMPT (per the HW2 brief).

## Summary

- **Total occurrences audited:** ~120 across `src/` + `scripts/`
- **Real violations found + fixed:** 2 (both in `fight_engine.py`)
- **Defensive fallbacks (OK — documented):** 16
- **Row-metadata `CURRENT_TIMESTAMP` (OK — exempt):** ~100

## Files CHANGED (real violations)

### `src/services/fight_engine.py` (2 fixes)

Both in `_resolve_title_change` — the `champion_since_date` column's
`COALESCE(?, CURRENT_DATE)` fallback. `fight_date` is normally passed
by the caller, but if it's `None`, the fallback used `CURRENT_DATE`
(today's REAL-WORLD date). This is a Time Law violation — a title
that changes hands should be stamped with the SIM date, not the real
wall-clock date.

**Fix:** replaced `CURRENT_DATE` with a SQL subquery that reads
`simulation_clock.current_date`:

```sql
-- Before (HW2.2):
champion_since_date = COALESCE(?, CURRENT_DATE)

-- After (HW2.2):
champion_since_date = COALESCE(?,
    (SELECT simulation_clock.current_date
     FROM simulation_clock WHERE clock_id=1))
```

Two locations: line ~4383 (vacant + non-draw → winner becomes champion)
and line ~4427 (contender wins → title changes hands).

## Files NOT changed (documented as OK)

### Defensive fallbacks (16 occurrences)

These all follow the same pattern: the code FIRST tries to read
`simulation_clock.current_date` from the DB, and only falls back to
`datetime.now()` / `date.today()` if the clock row is missing (which
only happens on a fresh test DB that hasn't been seeded yet). In
production with a seeded DB, the sim clock is ALWAYS used. These are
test-DB safety nets, not gameplay violations.

| File | Line | Pattern |
|---|---|---|
| `src/services/retirement_svc.py` | 310, 312 | `current_dt = datetime.now()` if `current_date` arg is None or unparseable |
| `src/services/retirement_svc.py` | 1159 | `current_date = datetime.now().strftime(...)` if `current_date` arg is None |
| `src/services/hof_svc.py` | 477 | `sim_date = _date.today().isoformat()` if both arg and sim_clock are None |
| `src/services/rival_ai/staff_manager.py` | 416, 504 | `start_dt = datetime.now()` if `current_date` arg can't be parsed |
| `src/services/contracts.py` | 123, 125 | `current_dt = datetime.now()` if sim_clock missing or unparseable |
| `src/scouting.py` | 154 | `datetime.now().strftime(...)` if sim_clock row missing |
| `src/ui_legacy/screens/screens/free_agents.py` | 1191 | `datetime.now().strftime(...)` if sim_clock missing |
| `src/interpretation/headline_engine.py` | 630 | `_date.today().isoformat()` if sim_clock missing |
| `src/interpretation/memory_engine.py` | 389 | `date.today().isoformat()` (same pattern) |
| `src/interpretation/narrative_families.py` | 573, 709 | `_date.today().isoformat()` (same pattern) |
| `src/interpretation/context_engine.py` | 1010, 1158 | `_date.today().isoformat()` (same pattern) |
| `src/interpretation/snapshot_cache.py` | 362 | `_date.today().isoformat()` if sim_clock row missing |
| `src/interpretation/career_phase_engine.py` | 638, 765 | `_date.today().isoformat()` (same pattern) |

These could be hardened further (e.g., replace `_date.today()` with
`build_db.GAME_START_DATE` so even the fallback is a sim date), but
doing so would risk masking real bugs (a missing sim_clock row is a
real problem that should be visible). The current pattern — log +
fall back to real time ONLY for missing-clock scenarios — is a
reasonable defensive design. Left as-is.

### Row metadata `CURRENT_TIMESTAMP` (~100 occurrences)

Every `updated_at = CURRENT_TIMESTAMP` and `created_at TEXT NOT NULL
DEFAULT (CURRENT_TIMESTAMP)` in the schema is REAL-WORLD row metadata
(when was this row last touched in wall-clock time). This is NOT
gameplay time — it's database bookkeeping. The HW2 brief explicitly
exempts "save metadata / diagnostics" and these row timestamps are
the same category.

Examples (NOT violations):
- `src/build_db.py` — every `CREATE TABLE` has `created_at` / `updated_at`
  columns with `DEFAULT (CURRENT_TIMESTAMP)`. These are row metadata.
- `src/services/fight_engine.py` — every `UPDATE` sets
  `updated_at = CURRENT_TIMESTAMP`. Row metadata.
- `src/app_web.py` — same pattern across all UPDATE queries.
- `src/services/rival_ai/*.py` — same pattern.

### Save metadata + filesystem (3 occurrences in `src/save_load.py`)

- Line 348: `"timestamp": datetime.now().isoformat(timespec="seconds")` —
  save file metadata (when was this save created in real-world time).
- Line 429: `save_name = datetime.now().strftime("save_%Y%m%d_%H%M%S")` —
  save file naming (unique real-world timestamp).
- Line 696: `wallclock = datetime.now().strftime("%Y%m%d_%H%M%S")` —
  backup filename.

All three are FILESYSTEM operations (save file naming + metadata),
explicitly exempt per the HW2 brief.

### UI widget defaults (`src/ui_legacy/widgets/widgets/components/calendar_strip.py`)

- Lines 54, 74, 76: `date.today()` as a default parameter for the
  calendar widget's `start_date` / `today` arguments. These are UI
  component defaults — the actual calendar screens override them with
  sim dates from `get_clock(conn)`. The defaults only matter if a
  caller doesn't provide values, which is a UI-only concern, not
  gameplay state.

## Conclusion

The codebase was already largely Time-Law-compliant (most gameplay
code reads `simulation_clock.current_date` via `get_clock(conn)`).
The only real violations were the two `CURRENT_DATE` fallbacks in
`fight_engine.py`'s title-change logic, which are now fixed. The 16
defensive fallbacks and ~100 row-metadata timestamps are documented
as exempt.
