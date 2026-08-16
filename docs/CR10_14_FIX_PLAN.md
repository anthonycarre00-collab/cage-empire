> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Fix Plan for 5 Critical DB Audit Issues (CR-10..14)

> **Status:** ACTIVE — fix plan for the 5 critical issues found in
> `docs/DB_REVIEW_AUDIT.md`.
> **Supervisor:** main agent. Five parallel subagents will implement.
> **Source of truth for:** training-camp formula, fight engine balance,
> career-phase pyramid, runtime bugs, bio regeneration.

---

## 0. Summary

| # | Issue | Severity | Subagent | Files |
|---|---|---|---|---|
| CR-10 | Training-camp growth 99.7% broken (effective_ceiling formula) | 🔴 CRITICAL | G | tick_processor.py, build_db.py (re-seed) |
| CR-11 | Fight engine 54% doctor-stoppages (vs 5.7% historical) | 🔴 CRITICAL | H | services/fight_engine.py |
| CR-12 | Career-phase pyramid inverted (75% rising_contender) | 🟠 HIGH | I | interpretation/career_phase_engine.py, snapshot_cache.py |
| CR-13 | 2 runtime bugs (small_reward_12 TypeError + drug_scandal NOT NULL) | 🟠 HIGH | J | news.py, reputation.py |
| CR-14 | Bios contradict DB records (11/14 sampled) | 🟡 MEDIUM | K | scripts/regenerate_fighter_bios.py (NEW) |

---

## 1. CR-10 — Training-camp effective_ceiling fix

### 1.1 Root cause (verified)

`src/tick_processor.py:674`:
```python
effective_ceiling = int(potential * age_factor * health_factor * personality_factor)
```

For a typical fighter (potential=60, age=25, health=100, discipline=50, coachability=50):
- age_factor = 1.0
- health_factor = 1.0
- personality_factor = (50+50)/200 = **0.5**
- effective_ceiling = 60 × 1.0 × 1.0 × 0.5 = **30**

But seeded attributes average **52** (median 52, range 27-93). So effective_ceiling (30) < current_attr (52) → `dim_factor = 0.0` → `gain = 0` → "no gains (attributes already at potential)".

Result: 99.7% of training camps produce zero attribute gains.

### 1.2 Fix approach (TWO-PART)

**Part A — Re-tune the formula (remove personality_factor from ceiling):**

The `personality_factor` should affect the GROWTH RATE, not the CEILING. A low-discipline fighter grows SLOWER but can still reach their potential — they just take longer. Move `personality_factor` into the gain multiplier:

```python
# NEW formula:
effective_ceiling = int(potential * age_factor * health_factor)
# personality_factor now scales the gain, not the ceiling
gain = int(round(base * gym_spec_mult * coach_mult * fatigue_factor * dim_factor * personality_factor))
```

This means:
- A 25yo with potential=60, health=100: ceiling = 60 (can reach potential)
- A 32yo with potential=60, health=70: ceiling = 60 × 0.80 × 0.90 = 43 (age + health limit)
- A 38yo with potential=60, health=50: ceiling = 60 × 0.35 × 0.40 = 8 (deep decline)

**Part B — Re-seed attributes down to give growth room:**

Even with the formula fix, many fighters have attrs already at/near their potential (e.g., avg attr 52, avg potential 62 — only 10 points of headroom). Re-seed all attributes down by ~15 points (clamp at 25 floor) so fighters have realistic growth room:

```sql
UPDATE fighter_attributes
SET punch_power = MAX(25, punch_power - 15),
    cardio = MAX(25, cardio - 15),
    ... -- all 26 attributes
    updated_at = CURRENT_TIMESTAMP;
```

This gives: avg attr 37 (was 52), with avg potential 62 → 25 points of headroom for growth.

**Migration:** Add migration v3.20.0 to `build_db.py` that runs the re-seed SQL.

### 1.3 Downstream wiring

- **Interpretation layer refresh**: after re-seed, the `fighter_descriptors.attribute_descriptors` cache is stale. The migration should trigger a full cache rebuild (or set `snapshot_cache.ENGINE_VERSION` bump to force rebuild on next tick).
- **Attribute trajectory chips (CR-2)**: the trajectory computation in `app_web.py::_compute_attribute_trajectory` uses the same `effective_ceiling` formula — must be updated to match the new formula.
- **Career phase (CR-12)**: with growth now working, fighters will actually progress through career phases over time.

### 1.4 Acceptance criteria
- [ ] Training camps produce attribute gains for ≥80% of completed camps (was 0.3%)
- [ ] A 20-year-old prospect with potential=70 reaches ~60+ in their key attributes within 2 sim-years
- [ ] A 32-year-old veteran shows minimal growth (ceiling age-bounded)
- [ ] A 38-year-old shows attribute decline (ceiling below current)
- [ ] `effective_ceiling` formula no longer includes `personality_factor`
- [ ] Attribute trajectory chips (CR-2) reflect the new formula
- [ ] `fighter_descriptors.attribute_descriptors` cache rebuilds after re-seed

---

## 2. CR-11 — Fight engine doctor-stoppage fix

### 2.1 Root cause (verified)

`src/services/fight_engine.py:4410-4445`. The doctor_stoppage check fires when:
```python
total_a_damage > doctor_b_threshold  # threshold = 200 + durability*2 = ~300 for durability=50
AND total_a_damage > total_b_damage + 50  # one-sided beating
```

The threshold (300) is too low relative to the damage output per round. By end of round 2, cumulative damage often exceeds 300 for one fighter, triggering doctor_stoppage at finish_time="5:00".

Result: 54% of new fights end via doctor_stoppage at 5:00 of round 2. Zero UD/SD/draw/DQ generated.

### 2.2 Fix approach

**Tune the constants:**

```python
# Current (too aggressive):
_DOCTOR_STOPPAGE_BASE = 200
_DOCTOR_STOPPAGE_DURABILITY_SCALE = 2  # threshold = 200 + dur*2 = 300 for dur=50
_DOCTOR_STOPPAGE_DIFFERENTIAL = 50

# NEW (more conservative — doctor stoppage should be rare, ~5-8% of fights):
_DOCTOR_STOPPAGE_BASE = 400          # was 200 — higher base threshold
_DOCTOR_STOPPAGE_DURABILITY_SCALE = 3  # was 2 — durability matters more
_DOCTOR_STOPPAGE_DIFFERENTIAL = 100  # was 50 — must be MORE one-sided
```

New threshold for durability=50: 400 + 50*3 = 550. For durability=90: 400 + 90*3 = 670.

This makes doctor stoppages rare (only in genuinely one-sided beatings where one fighter has taken 550+ cumulative damage AND the differential is 100+).

**Also: verify the decision-scoring path fires when no finish occurs.**

The audit found zero UD/SD/draw. After raising the doctor threshold, more fights should reach the judges. Verify the decision-scoring code (around line 1941-2011) actually runs when no finish_info is set. If it doesn't, investigate why.

### 2.3 Target result-type distribution

Per real MMA statistics:
- KO/TKO: ~30%
- Submission: ~15%
- Unanimous decision: ~33%
- Split decision: ~7%
- Doctor stoppage: ~5-8%
- Draw: ~2.5%
- DQ: ~1.5%

After the fix, run 100 sim-fights and verify the distribution is within ±10% of these targets.

### 2.4 Downstream wiring

- **News engine**: `_format_fight_news` (line 2021) already handles all result types — no change needed.
- **Show rating**: `show_rating.py` reads result types — no change needed.
- **Finance (purse bonuses)**: Phase E2's `fighter_purse` pays finish_bonus for KO/Sub — no change needed, but more decisions means fewer finish bonuses (correct behavior).
- **Fight history**: the `result_type` column already accepts all types — no schema change.

### 2.5 Acceptance criteria
- [ ] Doctor stoppages drop from 54% to ~5-8% of new fights
- [ ] Unanimous decisions appear (~30-35%)
- [ ] Split decisions appear (~5-10%)
- [ ] Draws appear (~2-3%)
- [ ] DQs appear (~1-2%)
- [ ] KO/TKO rate stays ~25-35%
- [ ] Submission rate stays ~10-20%
- [ ] Run 100 sim-fights, verify distribution within ±10% of targets

---

## 3. CR-12 — Career-phase pyramid rebalance

### 3.1 Root cause (verified)

`src/interpretation/career_phase_engine.py` D4 priority order:
```python
1. champion        — is_champion
2. declining       — age >= 33 AND (loss_streak >= 3 OR career_health < 50)
3. prospect        — age < 24 AND total_fights < 10
4. veteran         — age >= 35 AND total_fights >= 20
5. gatekeeper      — age >= 30 AND total_fights >= 15 AND win_rate < 0.50
6. rising_contender — default
```

Problems:
- `veteran` requires age ≥ 35 AND fights ≥ 20 — too strict (few fighters have 20+ fights in this sim)
- `gatekeeper` requires age ≥ 30 AND fights ≥ 15 AND win_rate < 0.50 — too strict
- `declining` requires age ≥ 33 AND (loss_streak ≥ 3 OR health < 50) — narrow
- `prospect` requires age < 24 — too narrow (24-26 year olds with <10 fights are still prospects)
- Everything else falls to `rising_contender` (the catch-all)

Result: 75% rising_contender, 0.5% veteran, 0.4% gatekeeper, 0.3% declining.

### 3.2 Fix approach — relax thresholds

```python
# NEW priority order (first match wins):
1. champion        — is_champion (unchanged)
2. declining       — age >= 32 AND (loss_streak >= 2 OR career_health < 60)
                    # was: age >= 33 AND (loss_streak >= 3 OR health < 50)
                    # lowered age + lowered loss_streak + raised health threshold
3. prospect        — age < 26 AND total_fights < 12
                    # was: age < 24 AND total_fights < 10
                    # raised age cutoff + fight count
4. veteran         — age >= 32 AND total_fights >= 12
                    # was: age >= 35 AND total_fights >= 20
                    # lowered both thresholds
5. gatekeeper      — age >= 28 AND total_fights >= 10 AND win_rate < 0.55
                    # was: age >= 30 AND total_fights >= 15 AND win_rate < 0.50
                    # lowered age + fights, raised win_rate cutoff
6. rising_contender — default (still the catch-all, but now a smaller share)
```

Expected distribution after fix:
- champion: ~2-3%
- declining: ~8-12%
- prospect: ~10-15%
- veteran: ~15-20%
- gatekeeper: ~12-18%
- rising_contender: ~40-50% (down from 75%)

This gives a realistic pyramid: many prospects → many rising contenders → some veterans/gatekeepers → few champions → some declining.

### 3.3 Downstream wiring

- **Interpretation layer refresh**: after threshold change, `fighter_descriptors.career_phase` cache is stale. Bump `snapshot_cache.ENGINE_VERSION` to force rebuild.
- **Dashboard fighter_watch**: uses `career_phase` for the watch cards — no code change, just better data.
- **Roster screen**: the "WHERE THEY ARE" column uses `career_phase_short` — no code change.
- **News engine**: `news.py` reads `career_phase` for some templates — no code change.
- **Small rewards (CR-13)**: templates like `_small_reward_04_champion_decline` check career_phase — will fire more accurately now.

### 3.4 Acceptance criteria
- [ ] Career phase distribution: ~40-50% rising_contender (down from 75%)
- [ ] Veterans: ~15-20% (up from 0.5%)
- [ ] Gatekeepers: ~12-18% (up from 0.4%)
- [ ] Declining: ~8-12% (up from 0.3%)
- [ ] Prospects: ~10-15% (up from ~3%)
- [ ] Champions: ~2-3% (unchanged)
- [ ] `fighter_descriptors.career_phase` cache rebuilds after threshold change
- [ ] No fighter has NULL career_phase (all active fighters bucketed)

---

## 4. CR-13 — Runtime bug fixes

### 4.1 Bug A: `_small_reward_12_upset_alert` TypeError

**Root cause:** `src/news.py:3754` calls:
```python
_write_small_reward(conn, 12, fight_id, headline, body,
                    fighter_id=wid, event_id=event_id,
                    published_at=sim_date, sentiment="positive")
```

But `_write_small_reward` signature (line 3260):
```python
def _write_small_reward(conn, template_id, key, headline, body,
                        fighter_id=None, promo_id=None,
                        published_at=None, sentiment="neutral"):
```

It does NOT accept `event_id=` as a kwarg. → `TypeError: _write_small_reward() got an unexpected keyword argument 'event_id'` on every tick.

**Fix:** Add `event_id=None` parameter to `_write_small_reward` + pass it through to `_write_news_item`:

```python
def _write_small_reward(conn, template_id, key, headline, body,
                        fighter_id=None, promo_id=None, event_id=None,
                        published_at=None, sentiment="neutral"):
    # ... existing code ...
    _write_news_item(
        conn, headline, full_body, sentiment=sentiment,
        fighter_id=fighter_id, promotion_id=promo_id, event_id=event_id,
        published_at=published_at, topic=SMALL_REWARD_TOPIC,
    )
```

Verify `_write_news_item` accepts `event_id` (check its signature). If not, add it there too.

### 4.2 Bug B: `_write_drug_scandal_marker` NOT NULL violation

**Root cause:** `src/reputation.py:235`:
```python
conn.execute(
    "INSERT INTO news_items (news_source_id, headline, body, "
    "sentiment, topic, fighter_id, promotion_id, published_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    (src_id, "[reputation marker]", marker, "neutral",
     _REPUTATION_MARKER_TOPIC, None, promotion_id, None),  # ← published_at=None!
)
```

`published_at` column has `NOT NULL DEFAULT CURRENT_TIMESTAMP`. Passing explicit `None` overrides the default → NOT NULL violation.

ALSO: `news_source_id` is NOT NULL. If `src_id` is None (System Feed source missing), that's a second NOT NULL violation.

**Fix:**

```python
def _write_drug_scandal_marker(conn, suspension_id, promotion_id):
    if suspension_id is None:
        return
    marker = f"[suspension_id={suspension_id}:drug_scandal]"
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    src_id = src_row[0] if src_row else None
    if src_id is None:
        # System Feed source doesn't exist — create it defensively
        conn.execute(
            "INSERT OR IGNORE INTO news_sources (name, source_type) "
            "VALUES ('System Feed', 'system')"
        )
        src_row = conn.execute(
            "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
        ).fetchone()
        src_id = src_row[0] if src_row else None
        if src_id is None:
            return  # can't write without a source — bail gracefully
    # CR-13 fix: omit published_at from INSERT so the DEFAULT CURRENT_TIMESTAMP applies
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, promotion_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, "[reputation marker]", marker, "neutral",
         _REPUTATION_MARKER_TOPIC, None, promotion_id),
    )
```

Key change: omit `published_at` from the INSERT column list entirely, so SQLite applies the DEFAULT.

### 4.3 Downstream wiring

- **Small reward #12**: after fix, upset alerts will actually fire on upsets. Verify the trigger query (fights in last 7 days with rating gap ≥ 15) finds real upsets.
- **Drug scandal**: after fix, reputation hits for drug scandals will be recorded + deduped correctly. Verify `_has_drug_scandal_marker` finds the marker.
- **News wire**: both fixes reduce error spam in the console (warnings every tick).

### 4.4 Acceptance criteria
- [ ] No TypeError on `_small_reward_12_upset_alert` (run sim forward 7+ days, verify no warning)
- [ ] No NOT NULL violation on `_write_drug_scandal_marker` (verify no warning in console)
- [ ] Small reward #12 actually fires when an upset occurs (verify news item written)
- [ ] Drug scandal marker is written + deduped correctly
- [ ] No regressions in other small_reward templates or reputation processing

---

## 5. CR-14 — Bio regeneration

### 5.1 Root cause (verified)

`fighter_bios` table has 4464 bios. All textually unique. But 11 of 14 sampled bios mention records that contradict `fighter_career` (e.g., bio says "31 professional fights" but DB shows 2-0).

Bios were generated against an earlier dataset (before `fighter_career` was finalized). They reference records, fight counts, win streaks, etc. that no longer match.

### 5.2 Fix approach

Create `scripts/regenerate_fighter_bios.py` that:

1. For each fighter, queries their ACTUAL data:
   - `fighter_career`: record_wins, record_losses, record_draws, win_streak, loss_streak, career_health, title_reigns
   - `fighters`: age, gender, weight_class, nationality, stance, nickname
   - `fighter_attributes`: key attributes (top 3 by value)
   - `fighter_personality`: personality archetype
   - `style_archetypes`: style name
   - `fight_history`: total fights, recent result types
   - `titles`: current champion status
   - `gyms`: current gym name

2. Generates a new bio using voice-compliant templates that REFERENCE the actual data:
   - Opening: fighter name + nickname + age + weight class + nationality
   - Record line: "X-Y-D record" (from fighter_career, NOT invented)
   - Style line: "Known for [style]" (from style_archetype)
   - Personality line: "[Personality] type" (from personality_archetype)
   - Trajectory line: based on career_phase + momentum (from fighter_descriptors)
   - Title line: if champion, "Current [WC] champion"; if former, "X-time title holder"
   - Gym line: "Trains at [gym]"
   - Closing: voice phrase from interpretation layer

3. Writes the new bio to `fighter_bios.bio_text` (UPDATE, not INSERT — preserve bio_id).

4. Sets `bio_tone` based on the fighter's career_phase (e.g., "hopeful" for prospects, "determined" for rising_contenders, "weathered" for veterans, "reflective" for declining).

5. Idempotent: re-running regenerates the same bios (deterministic templates, seeded by fighter_id).

### 5.3 Template structure

```python
def _generate_bio(fighter_data):
    """Generate a voice-compliant bio from actual fighter data."""
    name = f"{fighter_data['first_name']} {fighter_data['last_name']}"
    nick = fighter_data['nickname']
    age = fighter_data['age']
    wc = fighter_data['weight_class_name']
    nat = fighter_data['nationality_name']
    stance = fighter_data['stance']
    record = f"{fighter_data['wins']}-{fighter_data['losses']}"
    if fighter_data['draws'] > 0:
        record += f"-{fighter_data['draws']}"
    style = fighter_data['style_name']
    personality = fighter_data['personality_name']
    career_phase = fighter_data['career_phase']
    gym = fighter_data['gym_name']
    is_champion = fighter_data['is_champion']
    title_reigns = fighter_data['title_reigns']

    # Opening line
    bio = f"{name}"
    if nick:
        bio += f" '{nick}'"
    bio += f" is a {age}-year-old {wc} from {nat}."

    # Record line (ACTUAL, not invented)
    bio += f" {record} record"
    if fighter_data['win_streak'] >= 3:
        bio += f", on a {fighter_data['win_streak']}-fight win streak"
    elif fighter_data['loss_streak'] >= 3:
        bio += f", riding a {fighter_data['loss_streak']}-fight skid"
    bio += "."

    # Style + personality
    bio += f" Known as a {style} fighter, {personality} by nature."

    # Career phase line (voice phrase)
    phase_phrase = fighter_data['career_phase_phrase']  # from interpretation layer
    bio += f" {phase_phrase}."

    # Title line
    if is_champion:
        bio += f" Current {wc} champion."
    elif title_reigns > 0:
        bio += f" Former {title_reigns}-time title holder."

    # Gym line
    if gym:
        bio += f" Trains at {gym}."

    return bio
```

### 5.4 Downstream wiring

- **Fighter Profile UI**: reads `fighter_bios.bio_text` — no code change, just better data.
- **Interpretation layer**: `attribute_descriptors` already references fighter data — no change.
- **Scouting reports**: may reference bios — verify no hardcoded bio assumptions.

### 5.5 Acceptance criteria
- [ ] All 4464 fighters have regenerated bios
- [ ] Bios reference ACTUAL records (verify: bio says "X-Y" matches `fighter_career.record_wins-losses`)
- [ ] Bios reference ACTUAL style + personality (from archetype tables)
- [ ] Bios reference ACTUAL gym + nationality
- [ ] Bios are voice-compliant (no tabloid clichés, no ALL CAPS, ≤300 chars where possible)
- [ ] Bios are unique (no two fighters have identical bios — different name/record/style/gym)
- [ ] Sample 20 bios, verify all match DB records (was 11/14 mismatched)
- [ ] `bio_tone` set based on career_phase

---

## 6. Subagent assignments + parallelization

### Subagent G — CR-10: Training-camp formula + re-seed (CRITICAL)
**Task ID:** CR-G-TRAINING-CAMP
**Files owned:** `src/tick_processor.py`, `src/build_db.py` (migration v3.20.0 + re-seed SQL), `src/app_web.py` (update `_compute_attribute_trajectory` to match new formula), `src/interpretation/snapshot_cache.py` (bump ENGINE_VERSION).
**Scope:**
- Re-tune `effective_ceiling` formula (remove personality_factor from ceiling, move to gain multiplier)
- Migration v3.20.0: re-seed all fighter_attributes down by 15 (clamp at 25)
- Update `_compute_attribute_trajectory` in app_web.py to use new formula
- Bump snapshot_cache.ENGINE_VERSION to force descriptor cache rebuild

### Subagent H — CR-11: Fight engine doctor-stoppage fix (CRITICAL)
**Task ID:** CR-H-FIGHT-ENGINE
**Files owned:** `src/services/fight_engine.py` (constants only — 3 lines changed).
**Scope:**
- Raise `_DOCTOR_STOPPAGE_BASE` from 200 → 400
- Raise `_DOCTOR_STOPPAGE_DURABILITY_SCALE` from 2 → 3
- Raise `_DOCTOR_STOPPAGE_DIFFERENTIAL` from 50 → 100
- Verify decision-scoring path fires when no finish occurs
- Run 100 sim-fights, verify result-type distribution within ±10% of targets

### Subagent I — CR-12: Career-phase pyramid rebalance (HIGH)
**Task ID:** CR-I-CAREER-PHASE
**Files owned:** `src/interpretation/career_phase_engine.py` (threshold relaxation), `src/interpretation/snapshot_cache.py` (bump ENGINE_VERSION).
**Scope:**
- Relax thresholds for veteran, gatekeeper, declining, prospect per §3.2
- Bump ENGINE_VERSION to force cache rebuild
- Verify distribution: ~40-50% rising_contender, ~15-20% veteran, etc.

### Subagent J — CR-13: Runtime bug fixes (HIGH)
**Task ID:** CR-J-RUNTIME-BUGS
**Files owned:** `src/news.py` (fix `_write_small_reward` signature + `_small_reward_12_upset_alert` call), `src/reputation.py` (fix `_write_drug_scandal_marker` INSERT).
**Scope:**
- Add `event_id=None` param to `_write_small_reward` + pass to `_write_news_item`
- Fix `_write_drug_scandal_marker`: omit `published_at` from INSERT (use DEFAULT), ensure System Feed source exists
- Verify no TypeErrors or NOT NULL violations on 7+ day sim run

### Subagent K — CR-14: Bio regeneration (MEDIUM)
**Task ID:** CR-K-BIO-REGEN
**Files owned:** `scripts/regenerate_fighter_bios.py` (NEW), `scripts/verify_bios.py` (NEW).
**Scope:**
- Create `regenerate_fighter_bios.py` that reads actual fighter data + generates voice-compliant bios
- Run it to regenerate all 4464 bios
- Create `verify_bios.py` to confirm bios match DB records
- Sample 20 bios, verify 100% match (was 11/14 mismatched)

### Why all 5 can run in parallel
- G touches tick_processor + build_db + app_web + snapshot_cache
- H touches fight_engine (different file)
- I touches career_phase_engine + snapshot_cache (snapshot_cache is shared — coordinate via ENGINE_VERSION bump: G bumps to 1.x.0, I bumps to 1.y.0)
- J touches news.py + reputation.py (different files)
- K creates new scripts (no file conflicts)

**snapshot_cache coordination:** G and I both need to bump ENGINE_VERSION. G should bump to force attribute_descriptors rebuild; I should bump to force career_phase rebuild. Either can go first — the second bump just triggers another rebuild. To avoid conflict, G bumps ENGINE_VERSION first (attribute re-seed is more impactful), I uses the same bumped version.

Actually, simpler: snapshot_cache.py has ONE ENGINE_VERSION constant. Whoever commits first bumps it; the second subagent sees the new version + doesn't need to bump again. The supervisor resolves any merge conflict.

---

## 7. Out of scope (defer)

- Pre-loading additional data (HoF legends, veteran fighters, rivalries) — separate phase after fixes verified
- Staff lifecycle (aging, retirement, regen) — Phase E5
- Memory link backfill — separate phase
- Matchmaking rematch-avoidance — separate phase
- Phase E3 (player financial levers) — next phase after all 5 fixes verified

---

## 8. After all 5 fixes ship

Run a full integration test:
1. Run sim forward 90 days.
2. Verify:
   - Training camps produce gains for ≥80% of fighters
   - Fight result types distributed realistically (~30% KO, ~15% sub, ~33% UD, etc.)
   - Career phase pyramid is balanced (~40-50% rising_contender, ~15-20% veteran, etc.)
   - No TypeErrors or NOT NULL violations in console
   - Bios match DB records (sample 20, 100% match)
3. Run all existing tests: save/load, news, finance wiring, finance E2, schema versioning.
4. Push to GitHub.

Then proceed to Phase E3 (player financial levers) per `docs/MASTER_PLAN.md`.
