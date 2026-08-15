# CAGE EMPIRE — Fight Engine Tuning + Systems Fix Plan

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes yet
**Goal:** Fix all 8 issues from the 1-year sim analysis. Make the fight engine produce realistic results. Add gym changes. Fix finances. Reduce news spam. Add end-of-year awards.

---

## Issue 1: 0 KOs in 672 fights (CRITICAL)

### Root cause analysis

**Full engine (player fights):** The KO system works like this:
1. Each beat, damage is dealt. Cumulative consecutive damage to a fighter is tracked.
2. When cumulative damage exceeds the fighter's KO threshold (`chin*1.0 + recovery_rate*0.2 + grit*0.1 + composure*0.1`), a KO check fires.
3. The KO check only fires if the current beat is a "power strike" (damage >= 30, `_KO_CHECK_MIN_DAMAGE`).
4. When the check fires, the KO probability is `0.1 + killer_instinct * 0.002` (range 0.1-0.3).

**Problem:** With the OLD attribute data (avg ~54, max ~81), the KO threshold for a typical fighter is:
`50*1.0 + 50*0.2 + 50*0.1 + 50*0.1 = 50 + 10 + 5 + 5 = 70`

But per-beat damage is typically 5-25. So cumulative damage rarely reaches 70 in a single beat sequence (consecutive damage resets when the fighter lands their own strike). The threshold is too high relative to the damage output.

**AI simplified resolver:** The KO threshold is `150 + (chin + durability) * 0.75`. For typical fighters: `150 + (50+50)*0.75 = 225`. Per-round damage is `20 + (power-50)*0.4 ± 10` = typically 15-25. Over 3 rounds = 45-75 total. That's WAY below 225. The threshold is unreachable.

Also, the simplified resolver requires `total_damage > ko_thresh AND winner_ahead_by_30`. With damage of 45-75 vs threshold of 225, this NEVER fires.

### Fix

**Full engine:**
- Lower `_KO_CHECK_MIN_DAMAGE` from 30 → 20 (more strikes can be "finishing blows")
- Lower the KO threshold formula: reduce chin weight from 1.0 → 0.7, so threshold = `chin*0.7 + recovery*0.2 + grit*0.1 + composure*0.1` (typical: 35+10+5+5 = 55, more reachable)
- Increase base KO probability from 0.1 → 0.15 (more KOs when threshold is crossed)
- Increase per-beat damage slightly: the damage formula should produce more 30+ damage strikes

**Simplified AI resolver:**
- Lower KO threshold from `150 + (chin+dur)*0.75` → `60 + (chin+dur)*0.3` (typical: 60+30 = 90, reachable in 3-4 rounds)
- Remove the `+30 damage lead` requirement (too strict — a fighter can get KO'd even in a close fight)
- Increase finish_prob base from 0.02 → 0.04 per round
- Increase submission probability from 0.01 → 0.02 per round

**Target:** KO rate 25-35% (was 0%), submission rate 15-20% (was 1.2%)

---

## Issue 2: 38% split decisions (target 10%)

### Root cause

The 10-point must scoring system awards 10-9 per round. Split decisions happen when judges disagree. The current code likely has too much variance in the scoring, making close rounds go to different fighters.

### Fix

- Reduce the scoring variance. The round winner should be determined by damage dealt (with a small random factor for "octagon control" + "effective aggressiveness"). Currently the variance is too high, making every round a coin flip.
- In the simplified resolver: round winner is `a_id if dmg_a >= dmg_b else b_id`. This is fine — the issue is that with similar power levels, `dmg_a` and `dmg_b` are nearly equal, so the winner flips frequently across rounds. Add a minimum damage differential: if `|dmg_a - dmg_b| < 5`, it's a 10-9 round for the higher damage fighter (not a 10-10 draw, but also reduce the judge split probability).
- In the full engine: reduce the judge variance in the 10-point must scoring. Split decisions should only happen when the round is genuinely close (damage difference < 10).

**Target:** Split decision rate 5-12% (was 38%)

---

## Issue 3: 1.2% submissions (target 20%)

### Root cause

The submission system requires:
1. A fighter to attempt a submission (probability-based per beat)
2. The submission score to exceed the defense score
3. The submission to succeed (probability roll)

With the old attribute data (avg ~50), submission_offense ~51 and submission_defense ~50. The score formula is `attacker.submission_offense - defender.submission_defense * 0.5 - defender.flexibility * 0.3` = `51 - 25 - 15 = 11`. This is too low to trigger a submission finish.

### Fix

**Full engine:**
- Increase submission attempt probability per beat
- Lower the submission success threshold
- Increase the effect of submission_offense on the score

**Simplified AI resolver:**
- Increase `sub_prob` base from 0.01 → 0.03 per round
- Increase the submission_offense scaling from 0.0005 → 0.001

**Target:** Submission rate 15-20% (was 1.2%)

---

## Issue 4: 46 fights with NULL result_type

### Root cause

The simplified AI resolver returns a result dict, but somewhere in the calling code the result_type isn't being written to the fights table. This is a bug in the code path that handles the simplified resolver's return value.

### Fix

- Trace the code path from `_resolve_fight_simplified` → the caller in `resolve_next_fight` → the `UPDATE fights SET result_type=?` statement
- Verify the result_type from the simplified path is properly passed through
- Add a defensive check: if result_type is NULL after resolution, log an error + set it to 'unanimous_decision' as a fallback

---

## Issue 5: ELO rankings don't match skill

### Root cause

This was already fixed by the reseed — the `regenerate_rankings.py` script computes ELO from fight_history (80K rows) with tier-weighted starting values. The pre-sim DB had flat 1000 ELO for everyone. The reseeded DB has proper ELO.

### Fix

Already done. Verify by checking the reseeded rankings.

---

## Issue 6: 84% ROUTINE news

### Root cause

Training news (338 items) and small_reward news (218 items) fire too frequently. The daily cap of 5 ROUTINE items helps but doesn't prevent accumulation across days.

### Fix

- Reduce training news frequency: only fire on camp COMPLETION (not every progression tick). Currently `_check_training_camps` fires news on every camp that progresses, not just completions.
- Reduce small_reward news frequency: increase the threshold for what counts as a "small reward" (currently fires for very minor events).
- Add more SIGNIFICANT news sources:
  - End-of-year awards (Fighter of the Year, Fight of the Year, Knockout of the Year, Submission of the Year, Comeback of the Year)
  - Rival promotion event reports (after each rival event, generate a brief recap: "RFL put on a solid show last night — main event delivered")
  - Pundit analysis (deeper fight breakdowns for title fights: "The numbers say Vale's wrestling was the difference")
  - Divisional rankings changes ("Movement in the Lightweight rankings — 3 fighters climbed this month")
- Add these new news types to the pruning policy (365-day retention).

**Target:** ROUTINE < 60% of total news (was 84%). SIGNIFICANT+ > 25% (was 7.4%).

---

## Issue 7: Most promotions in REBUILDING

### Root cause

The financial state machine transitions to REBUILDING too aggressively. After a few bad events, a promotion drops to REBUILDING and can't recover.

### Fix

- Raise the REBUILDING threshold: only enter REBUILDING after 3+ consecutive months of negative cash flow (was likely 1-2 months)
- Increase the recovery rate: promotions in REBUILDING should recover faster (the "new ownership" narrative should come with a cash injection)
- Lower event costs: venue rental + fighter purses may be too high relative to ticket revenue
- Increase the starting cash for small promotions: $2M → $5M (gives more runway)

---

## Issue 8: No gym changes

### Root cause

There's no gym-transfer flow in the simulation. Fighters are assigned to a gym at seed time and never change.

### Fix — simple implementation

Add a weekly TICK_ADVANCED subscriber `_check_gym_changes` in `src/tick_processor.py` or a new `src/gym_transfers.py`:

1. For each active fighter (weekly tick, ~5% sample = ~220 fighters checked per week):
   - Check if the fighter is on a losing streak (3+ losses) → may want a better gym
   - Check if the fighter's current gym has low facility_quality (< 40) → may want a better gym
   - Check if the fighter is a prospect (age < 25, potential > 70) → may want a better gym to develop
   - Check if the fighter's style doesn't match their gym's specialty → may want a gym that matches their style
2. If any condition is met, roll a small probability (5% per week per eligible fighter):
   - Find a better gym (higher facility_quality, matching style specialty, in the same nation)
   - Update `fighters.current_gym_id`
   - Write a `fighter_memory_links` row of type `old_gyms` (linking fighter to old gym)
   - Write a news item: "[Fighter] has left [Old Gym] to train at [New Gym]"
3. Update the fighter's descriptor snapshot (the gym change affects their training outlook)

This is lightweight — ~10-15 gym changes per year across 4,450 fighters. No schema change needed.

**UI impact:** The Roster + Fighter Profile screens already display `current_gym_id` — they'll automatically show the new gym. No UI changes needed.

**Gym bonus:** The training camp system already reads `gyms.facility_quality` — fighters at better gyms get better training results. The gym change mechanic makes this meaningful (fighters actively seek better gyms).

---

## Issue 9: Legacy Tkinter removal

The user wants the legacy Tkinter UI removed if possible. The web UI (`src/web/`) is the active UI. The Tkinter UI (`src/ui_legacy/`) is only used for the Save/Load screen.

### Fix

- Check if the web UI has a save/load capability (it likely calls `save_game` / `load_game` via `bridge.js`)
- If yes: remove `src/ui_legacy/` entirely
- If no: add save/load to the web UI (call `save_game` / `load_game` from `app_web.Api`), then remove `src/ui_legacy/`

---

## Implementation Plan

### Agent 1: Fight engine tuning (Issues 1-4)
- Adjust KO thresholds (full + simplified engine)
- Adjust submission probabilities
- Fix split decision scoring
- Fix NULL result_type bug
- Test with 1000-fight sample using reseeded DB
- Verify distribution: KO 25-35%, sub 15-20%, decision 40-50%, split 5-12%

### Agent 2: News + finances (Issues 6-7)
- Reduce training + small_reward news frequency
- Add end-of-year awards news (annual tick — January 1)
- Add rival promotion event reports (after each rival event)
- Add pundit analysis for title fights
- Add divisional ranking movement news
- Tune financial state machine thresholds
- Increase small promo starting cash

### Agent 3: Gym changes + legacy removal (Issues 8-9)
- Add gym-transfer flow (weekly subscriber)
- Write old_gyms memory links + news items
- Remove legacy Tkinter UI (verify web save/load works first)

### Supervisor:
- Run full test suite
- Run 1-year sim with reseeded DB
- Analyze results
- Commit (NO force push — use regular push only)
- Update README

---

## Testing approach

1. After fight engine tuning: run `scripts/measure_fight_distribution.py` on 1000 fights
2. After news + finances: run 30-day soak, check news distribution + promo states
3. After gym changes: run 30-day soak, check for gym change news items
4. Full 1-year sim: run `scripts/soak_test.py 365 --no-backup`, then `scripts/analyze_1yr_sim.py`
5. Compare to the previous 1-year analysis (docs/1YR_SIM_ANALYSIS.md)

All tests use the RESEEDED DB (6,450 fighters, 80K fight history, proper ELO rankings).
