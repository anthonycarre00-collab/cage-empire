# Phase 9 Plan — Pruning Loosening + Economics Fine-Tuning + Memory Resurfacing Optimization

**Date:** 2026-08-26
**Status:** PLANNING — execute immediately after writing
**Task ID:** PHASE9-PRUNE-ECON-PERF
**Prerequisites:** Phase 8 complete + 5-year soak validated (commit `19621be`)

---

## Background

Phase 8 5-year soak (`docs/PHASE8_SOAK_ANALYSIS.md`) validated the core fixes but identified 3 issues for Phase 9:

1. **[HIGH] `fighter_memory_links` pruning not effective** — grew 445 → 19,976 (+19,531) over 5y despite the Phase 8 pruning policy. Root cause: the "both fighters retired" condition is too strict. Most `successor` links connect a retired champion (`linked_fighter_id`) to their ACTIVE replacement (`fighter_id`), so the "both retired" condition is rarely met.

2. **[MEDIUM] P5 + P9 small promos nearly bankrupt** — P5 South American Warriors: $8M → $0.4M (-95%), P9 Australian Outback Fights: $8M → $0.2M (-98%). Both survived (REBUILDING/PRESSURED states prevented bankruptcy) but are on the edge. Further tuning needed for comfortable sustainability.

3. **[LOW] Memory resurfacing performance overhead** — per-tick time went from 0.55s/day (Phase 7) to ~1.0s/day (Phase 8) due to the new daily `generate_upcoming_fight_memory_news` pass. The pass queries upcoming fights + calls `surface_memories` per fight. Can be optimized.

---

## Tasks (3 groups)

### Group A — Loosen `fighter_memory_links` pruning [HIGH]

**Current:** `src/services/pruning_svc.py:213-217`:
```python
("fighter_memory_links", "created_at", 365,
 "linked_fighter_id IN (SELECT fighter_id FROM fighters WHERE is_retired=1) "
 "AND fighter_id IN (SELECT fighter_id FROM fighters WHERE is_retired=1)"),
```

**Problem:** The "both fighters retired" condition is too strict. Most `successor` links connect a retired champion (`linked_fighter_id`) to their ACTIVE replacement (`fighter_id`). The active replacement may fight for years, keeping the link alive even though the retired champion's narrative is long forgotten.

**Fix:** Loosen to "linked_fighter_id retired + 365 days" (regardless of `fighter_id` status). This prunes old successor links once the retired champion has been gone for a year. The active replacement's other links (style_echo, etc.) are kept because they may still surface.

**Also:** Add a separate, more aggressive prune for `style_echo` links (90 days, regardless of retirement status). `style_echo` links are created on every retirement (via `populate_style_echo` in `src/services/memory_svc.py`) + are less narratively valuable than `successor` links — they just record "this replacement fighter inherited the retiring fighter's archetype." After 90 days, the narrative value is gone.

**Implementation:**
1. Modify the existing `fighter_memory_links` entry in `_PRUNE_POLICY` to use the loosened condition (linked_fighter_id retired only).
2. Add a SECOND entry for `style_echo` links specifically (90 days, no retirement condition).

**Files:** `src/services/pruning_svc.py` only.

---

### Group B — Further tune P5 + P9 economics [MEDIUM]

**Problem:** P5 + P9 nearly bankrupt after 5 years (-95% / -98%). The Phase 8 economics helped most promos but these 2 are still on the edge.

**Fix:** 2 targeted adjustments:

1. **Increase small promo starting cash $8M → $10M** — gives 25% more runway. This is the simplest + most impactful fix. The 5y soak showed P5 + P9 lost ~$7.6M + $7.8M respectively over 5 years. With $10M start, they'd end at ~$2.4M + $2.2M (still PRESSURED but not bankrupt).

2. **Reduce small promo venue cost multiplier 0.4x → 0.3x** — further reduces the per-event venue expense. A 3,489-seat theater at $4/seat × 0.3 = $4,187/event (was $5,580 at 0.4x, was $13,956 at 1.0x pre-Phase 8). Saves ~$1,400/event × 64 events = ~$90K over 5 years. Modest but helps.

**Files:** `src/finance.py` (`_VENUE_COST_MULT_BY_TIER`), `scripts/phase8_apply_economics.py` (starting cash $8M → $10M), `scripts/reset_promotion_cash.py` + `scripts/phase4_rebackfill_and_reset.py` + `scripts/set_promotion_finances.py` (starting cash references).

---

### Group C — Optimize memory resurfacing performance [LOW]

**Current:** `generate_upcoming_fight_memory_news` in `src/news.py:1830` runs every tick. It:
1. Queries upcoming fights (JOIN fights + events + fight_participants, GROUP BY) — 1 query
2. For each upcoming fight, calls `generate_fight_preview_memory_news` which calls `surface_memories` (11 searches × multiple queries each) — N queries per fight
3. Short-circuits at 2 writes/day (the daily cap)

**Problem:** Even with the short-circuit, the function still calls `surface_memories` for each upcoming fight until it finds 2 with memories. On a typical day there may be 5-10 upcoming fights in the 7-day window, + most have no memories → 5-10 × 11 searches = 55-110 queries per tick just for this pass.

**Fix:** Add an early-exit pre-check: before calling `surface_memories` for a fight, do a SINGLE fast query to check if ANY `fighter_memory_links` row exists between the two fighters. If not, skip the full `surface_memories` call (saves 11 queries). This is a ~10x speedup for fights with no history (the common case).

**Implementation:**
1. In `generate_upcoming_fight_memory_news`, before the `generate_fight_preview_memory_news` call, add a fast pre-check:
   ```python
   # Fast pre-check: skip if no memory_links exist between the two
   # fighters (the common case — most fighter pairs have no history).
   # Saves 11 surface_memories queries per skipped fight.
   has_link = conn.execute(
       "SELECT 1 FROM fighter_memory_links "
       "WHERE (fighter_id=? AND linked_fighter_id=?) "
       "   OR (fighter_id=? AND linked_fighter_id=?) "
       "LIMIT 1",
       (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
   ).fetchone()
   if not has_link:
       continue  # no memory_links → surface_memories would return empty
   ```
2. Also pre-check `fight_history` (for the `previous_fight` search type):
   ```python
   has_history = conn.execute(
       "SELECT 1 FROM fight_history "
       "WHERE (fighter_id=? AND opponent_id=?) "
       "   OR (fighter_id=? AND opponent_id=?) "
       "LIMIT 1",
       (fighter_a_id, fighter_b_id, fighter_b_id, fighter_a_id),
   ).fetchone()
   if not has_link and not has_history:
       continue  # no links + no history → only the weak searches
                # (same_weight_class, ranked_proximity) would match.
                # Skip — those are low-value for fight previews.
   ```
   This is more aggressive — skips fights where the only matches would be the weak "same weight class" / "ranked proximity" searches. Fight previews with no real history aren't worth surfacing.

**Files:** `src/news.py` only (`generate_upcoming_fight_memory_news` function).

---

### Group D — Run 10y soak to validate [LOW]

After Groups A-C, run a 10-year soak to confirm:
1. `fighter_memory_links` table stays bounded (was 19,976 after 5y; target <15K after 10y with loosened pruning)
2. P5 + P9 stay sustainable (target: end cash >$1M, no BANKRUPT)
3. Memory resurfacing still fires at a good rate (target: 400+ fires over 10y)
4. Per-tick time improves (target: <0.8s/day, was 1.0s/day)

**Files:** `docs/PHASE9_SOAK_ANALYSIS.md` (NEW) — analysis report.

---

## Implementation Order

```
Group A (pruning) — 1 file, ~10 min
Group B (economics) — 4 files, ~15 min + re-backfill
Group C (perf) — 1 file, ~10 min
  [Groups A+B+C can be done sequentially by the supervisor — small changes]
Group D (10y soak) — ~50 min runtime, run in chunks
```

Total estimated: ~2 hours.

---

## Success criteria

- [ ] Group A: `fighter_memory_links` pruning loosened (linked_fighter_id retired only) + `style_echo` aggressive prune (90 days)
- [ ] Group B: Small promo starting cash $8M → $10M, venue cost 0.4x → 0.3x
- [ ] Group C: Memory resurfacing pre-check added (skip fights with no links/history)
- [ ] Group D: 10y soak — all 10 promos survive, 0 bankruptcies, memory_links <15K, mem_resurf 400+ fires
- [ ] 8/8 invariants PASS throughout
- [ ] app_web imports OK throughout
- [ ] Committed + pushed
- [ ] Worklog updated with PHASE9-SIGNOFF
