> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# UI-REDESIGN-A — Interpretation Layer Variety Audit

> **Task ID:** UI-REDESIGN-A
> **Agent:** Interpretation Layer Reviewer (general-purpose)
> **Date:** 2026-07-29
> **Scope:** Audit the interpretation layer (`src/interpretation/` + `src/voice.py` + `src/ui/voice_display.py`) for phrase variety; explain why the user is STILL seeing repetition after the "8 variants per label" expansion; propose a comprehensive short/long variety improvement plan.
> **Mode:** RESEARCH ONLY. No code or DB files modified. The world DB was queried read-only.

---

## TL;DR — Executive Summary

1. **The "8 variants per label" claim from the UI-FIX-2-SIGNOFF worklog entry is only PARTIALLY true.** It applies to:
   - `momentum` (`MOMENTUM_PHRASES_EXT`) — 8 variants per label ✓
   - `pressure` (`PRESSURE_PHRASES_EXT`) — 8 variants per label ✓
   - `trajectory` (`TRAJECTORY_PHRASES_EXT`) — 8 variants per label ✓
   - `career_phase` (`PHASE_PHRASES_EXT`) — 8 variants per label ✓
   
   It does NOT apply to:
   - `narrative_family` — still only **3 variants** per label ✗
   - `legacy_state` — still only **3 variants** per label ✗
   - `headline_engine` — effectively **1 variant** per family per headline type ✗
   - `voice.ATTRIBUTE_DESCRIPTORS` / `PERSONALITY_DESCRIPTORS` — still **2–3 variants** per tier ✗
   - `voice.describe_career_stage` / `describe_career_health` — **3 variants** per case ✗

2. **The "8 variants" expansion has NEVER reached the production DB.** A direct query of `fighter_descriptors` shows the cache is populated with the ORIGINAL 3-variant picker output for `momentum`, `pressure`, `career_phase`, and `legacy_state`. Root cause: when the `_EXT` pickers were added (commit `1149538`, per the UI-FIX-2-SIGNOFF worklog entry), `snapshot_cache.ENGINE_VERSION` was NOT bumped. The version-mismatch rebuild logic never triggered, and the daily pass only re-writes rows on Advance Day. As of `last_built_date='2026-07-20'`, the cache is stale relative to the code.

3. **Even if the 8 variants DID populate, repetition would still be severe** because the label rules are heavily skewed toward the "default" bucket. Measured distribution of the 4450 active fighters:
   - `momentum='stable'` — **4376 fighters (98.3%)** squeezed into ≤8 variants → ~547 fighters per phrase
   - `pressure='moderate'` — **4142 fighters (93.1%)** squeezed into ≤8 variants → ~518 per phrase
   - `career_phase='rising_contender'` — **3376 fighters (75.9%)** squeezed into ≤8 variants → ~422 per phrase
   - `legacy_state='building'` — **4428 fighters (99.5%)** squeezed into only 3 variants → ~1476 per phrase
   - `narrative_family` is NULL for 4420 fighters (99.3%) — only 30 fighters match one of the 4 archetypes

4. **Screen-by-screen repetition is amplified by the same phrase appearing in multiple places at once.** The Roster and Free Agents tables use a SEPARATE 1-variant-per-label short phrase map (`_STAGE_SHORT_PHRASES` / `_FORM_SHORT_PHRASES`), so every "rising_contender + stable" fighter in a 60-row table renders as `Rising Contender | Steady` — zero variation. The Fighter Profile identity block repeats the SAME cache phrase on every visit (RNG is seeded by `fighter_id`, so it never changes between viewings).

5. **The CAGE EMPIRE voice is NOT consistently applied.** Many phrases read like sports-page clichés ("riding a hot streak", "holding steady", "the king of the division"). The Soul doc's reference phrases ("That kid I found in Mexico. Nobody wanted him. He became a champion.") have a richer, more narrative, more promoter-flavored register. The audit proposes specific phrase banks per module that hit the target voice.

6. **Recommendation summary:**
   - **Schema impact:** Add 2 columns to `fighter_descriptors` (`short_phrase_*` + `long_phrase_*` per interpretation column, or a single JSON blob); add 1 new table `interpretation_phrases` (label, length, phrase) so editors can add variants without code changes. Bump `ENGINE_VERSION` to `2.0.0` to force a full cache rebuild.
   - **Variant counts proposed:** ~12 short + ~8 long variants per label, per interpretation module. Across all modules (5 momentum + 5 trajectory + 4 pressure + 6 career_phase + 4 narrative_family + 4 legacy_state + 4 headline families), that's roughly **140 short + 100 long = ~240 new variants** to author.
   - **Selection algorithm:** Deterministic hash-of-(`fighter_id` + `career_phase` + `tick_bucket`) so the phrase rotates per fighter per ~5 in-game days, and a "no-repeat-within-last-N" cache for screen render to avoid showing the same phrase twice on one screen.
   - **Conditional triggers:** SHORT variants for table cells (Roster, Free Agents) and compact cards (Dashboard watch cards); LONG variants for the Fighter Profile identity block, Dashboard Top Story body, and news prose.

---

## 1. Inventory of Current Voice Phrase Banks

### 1.1 `src/interpretation/context_engine.py` — 1,062 lines

**Engine purpose:** Bulk-compute `momentum` (5 labels), `pressure` (4 labels), and `trajectory` (5 labels, derived not stored) for every active fighter, write `"label||phrase"` to `fighter_descriptors.momentum` + `pressure`. Uses RNG seeded by `fighter_id * 31 + 17` for deterministic per-fighter phrase selection.

**Phrase banks:**

| Bank | Lines | Labels | Variants per label | Short/Long mix |
|---|---|---|---|---|
| `MOMENTUM_PHRASES` (original) | 107–133 | 5 (very_high, high, stable, falling, collapsing) | 3 | Mixed — 3-7 words each |
| `PRESSURE_PHRASES` (original) | 135–156 | 4 (minimal, moderate, high, extreme) | 3 | Mixed — 3-8 words each |
| `TRAJECTORY_PHRASES` (original) | 158–184 | 5 (rising, peaking, stable, declining, collapsing) | 3 | Mixed — 4-7 words each |
| `MOMENTUM_PHRASES_EXT` (Fix 19) | 204–260 | 5 | **8** | Mixed — first 3 mirror original; next 5 are 5-10 words |
| `PRESSURE_PHRASES_EXT` (Fix 19) | 262–307 | 4 | **8** | Mixed |
| `TRAJECTORY_PHRASES_EXT` (Fix 19) | 309–365 | 5 | **8** | Mixed |

**Pickers:** `get_momentum_phrase` (original, 3 variants — preserved for the `test_context_engine.py Case D` acceptance test), `get_momentum_phrase_ext` (8 variants — used by the cache-write path at line 877).

**Sample `momentum='stable'` phrases (the EXT 8):**
1. `holding steady`
2. `form has been consistent`
3. `neither hot nor cold right now`
4. `a steady rhythm with no real swing either way`
5. `consistent without being spectacular`
6. `doing the work without the headlines`
7. `the kind of form that just keeps showing up`
8. `neither flying nor fading — just present`

**Issue:** None of these are tagged "short" vs "long" — pickers choose blindly. Phrases 1 and 5 are ~2 words; phrase 4 is 9 words. The UI has no way to request a short or long variant for the current screen context.

### 1.2 `src/interpretation/career_phase_engine.py` — 694 lines

**Engine purpose:** Compute `career_phase` (6 labels: prospect, rising_contender, champion, veteran, gatekeeper, declining) for every active fighter.

**Phrase banks:**

| Bank | Lines | Labels | Variants per label | Short/Long mix |
|---|---|---|---|---|
| `PHASE_PHRASES` (original) | 162–193 | 6 | 3 | Mixed — 4-10 words |
| `PHASE_PHRASES_EXT` (Fix 19) | 217–284 | 6 | **8** | Mixed — first 3 mirror original; next 5 are 5-12 words |

**Pickers:** `get_phase_phrase` (3, preserved for tests), `get_phase_phrase_ext` (8, used by cache writes).

**Sample `career_phase='rising_contender'` (the EXT 8):**
1. `a rising contender climbing the ranks`
2. `an up-and-comer knocking on the door of title contention`
3. `a surging contender with the division on notice`
4. `a name the matchmakers can't ignore anymore`
5. `the next big thing if he keeps delivering`
6. `trending upward and the division knows it`
7. `a killer in the contender queue`
8. `the buzz is real and the rankings show it`

### 1.3 `src/interpretation/narrative_families.py` — 577 lines

**Engine purpose:** Compute `narrative_family` (4 labels: prodigy, veteran, fallen_champion, cinderella_story) for active fighters who match the priority rules. NULL is a valid outcome.

**Phrase banks:**

| Bank | Lines | Labels | Variants per label | Short/Long mix |
|---|---|---|---|---|
| `FAMILY_PHRASES` (original) | 174–195 | 4 | **3** | Mixed — 4-12 words |

**Pickers:** `get_family_phrase` only. There is NO `_EXT` version. This module was missed by UI Fix Plan 2 Phase 3 Fix 19.

**Sample `family='prodigy'` (the only 3):**
1. `a prodigy turning heads early`
2. `the wunderkind everyone's talking about`
3. `a can't-miss prospect with star written all over him`

### 1.4 `src/interpretation/legacy_engine.py` — 498 lines

**Engine purpose:** Compute `legacy_state` (4 labels: building, established, legendary, forgotten) for ALL fighters (active + retired).

**Phrase banks:**

| Bank | Lines | Labels | Variants per label | Short/Long mix |
|---|---|---|---|---|
| `LEGACY_PHRASES` (original) | 160–181 | 4 | **3** | Mixed — 4-9 words |

**Pickers:** `get_legacy_phrase` only. There is NO `_EXT` version. This module was also missed by UI Fix Plan 2 Phase 3 Fix 19.

**Sample `legacy='building'` (the only 3):**
1. `still building a legacy`
2. `the story is just beginning`
3. `too early to judge their legacy`

### 1.5 `src/interpretation/memory_engine.py` — 691 lines

**Engine purpose:** READ-ONLY engine that surfaces 0-4 memories (previous_fight, shared_gym, former_teammate, injury_history) for a fight between two fighters. Returns `(memory_type, phrase)` tuples — does NOT write to a cache column.

**Phrase banks:** This engine uses deterministic phrase COMPOSITION, not variant lists. The voice phrases are built by string formatting:

| Helper | Lines | Inputs | Output variety |
|---|---|---|---|
| `_year_gap_phrase` | 185–200 | year diff (int) | 6 fixed phrases ("this year" / "one year" / "two years" / "three years" / "four years" / "many years") |
| `_result_type_phrase` | 217–230 | result_type | 8 fixed phrases (unanimous_decision → "unanimous decision", etc.) |
| `_outcome_verb` | 242–253 | outcome | 4 fixed phrases ("won" / "lost" / "drew" / "fought") |
| `_body_area_phrase` | 259–275 | body_area | 8 fixed phrases ("a shoulder injury", etc.) |
| `_return_band_phrase` | 285–321 | projected_return_date | 3 fixed bands ("near return" / "a long road back" / "indefinite") |

**Composed phrase templates:**
- `_search_previous_fight` (line 514–517): `"Met earlier {gap} — {verb} by {result}."` OR `"Last met {gap} ago — {verb} by {result}."` — only 2 templates
- `_search_shared_gym` (line 561): `"Training partners at {gym_name}."` — 1 template
- `_search_former_teammate` (line 624): `"Former training partners."` — 1 template, ZERO variation
- `_search_injury_history` (line 689–690): `"{name} is recovering from {body_phrase}, {band_phrase}."` — 1 template

**Issue:** The former_teammate phrase has exactly ONE variant — every fighter pair with that memory type sees the identical string. The other 3 templates have at most a few dozen permutations given the small input spaces.

### 1.6 `src/interpretation/headline_engine.py` — 570 lines

**Engine purpose:** Generate 4 daily headlines (top_story, upset_of_week, fastest_rising, biggest_fall), written to `daily_headlines` table.

**Phrase banks:** HARDCODED in the generator functions — no variant lists at all.

| Generator | Lines | Headline text variants | Body text variants |
|---|---|---|---|
| `_generate_top_story` | 222–312 | 4 (one per family: fallen_champion / prodigy / cinderella_story / veteran) — example: `"The prodigy turns heads again"` | 4 (one per family) — example: `"{name} keeps proving the hype is real. The division's brightest young talent continues to surge."` |
| `_generate_upset_of_week` | 319–401 | 1 template: `"{winner_name} stuns {loser_name}"` | 1 template with `upset_band` (3 variants: "an underdog" / "a heavy underdog" / "a shocking upset") + `result_phrase` (7 variants) |
| `_generate_fastest_rising` | 408–438 | 1 template: `"{name} is rising fast"` | 1 template: `"The hottest hand in the division belongs to {name}. The surge continues — opponents take notice."` |
| `_generate_biggest_fall` | 445–465 | 1 template: `"{name} is sliding fast"` | 1 template: `"The fall continues for {name}. Once a name to fear — now a fighter searching for answers."` |

**Issue:** Every "fastest_rising" headline reads `"{Name} is rising fast"` with the SAME body text. Same for "biggest_fall" → `"{Name} is sliding fast"`. The Top Story has 4 family-specific templates, but only ONE per family — a 30-day month where prodigy is the top story 20 times reads `"The prodigy turns heads again"` 20 times.

### 1.7 `src/voice.py` — 905 lines

**Engine purpose:** Pure voice-layer translator. Takes raw 0-100 attribute values and returns human-readable descriptor strings. Builds the JSON snapshot stored in `fighter_descriptors.attribute_descriptors`, `personality_descriptors`, `career_stage`, `career_health_desc`, `overall_desc`, `potential_desc`.

**Phrase banks:**

| Bank | Lines | Coverage | Variants per tier | Total strings |
|---|---|---|---|---|
| `ATTRIBUTE_DESCRIPTORS` | 94–344 | 25 attributes × 7 tiers | 2-3 (most tiers have 3; the `abysmal` tier has only 2) | ~500 |
| `PERSONALITY_DESCRIPTORS` | 353–537 | 20 traits × 7 tiers | 2-3 | ~400 |
| `POTENTIAL_DESCRIPTORS` | 562–570 | 7 tiers | 3 | 21 |
| `POTENTIAL_DESCRIPTORS_UNSCOUTED` | 578–586 | 7 tiers | 3 | 21 |
| `_ARCHETYPE_NOUN` | 690–698 | 7 style archetypes | 1 each | 7 |
| `_NUM_WORDS` | 780–784 | 13 numbers (0-12) | 1 each | 13 |
| `describe_career_stage` inline `_pick` lists | 646–664 | 8 career-state branches | 3-4 per branch | ~25 |
| `describe_career_health` inline `_pick` lists | 669–677 | 5 bands | 3 per band | 15 |

**Sample `punch_power.elite` (the 3 variants):**
1. `one-punch knockout threat`
2. `fight-ending power in both hands`
3. `heavy hands that end careers`

**Issue:** No short/long tagging. The same descriptor is used in the Fighter Profile attribute grid AND in the `describe_overall` summary sentence — so a fighter's overall reads `"...with one-punch knockout threat..."` AND the attribute row shows `"One-Punch Knockout Threat"` (via `display_attr_descriptor`). The player sees the same string twice on one screen.

### 1.8 `src/ui/voice_display.py` — 204 lines

**Engine purpose:** Pure display helper. Title-cases voice phrases for UI rendering. NO phrase banks.

**Functions:**
- `title_case_phrase` (line 112) — `"riding a hot streak"` → `"Riding a Hot Streak"`
- `display_phrase` (line 154) — decodes `"label||phrase"` cache values + applies title-case
- `display_attr_descriptor` (line 185) — title-cases attribute descriptor JSON values

**Issue:** None directly — this is a presentation helper. But it means every cache phrase is shown verbatim (just title-cased); there is no opportunity to substitute a SHORTER variant when the screen needs a compact cell. The Roster screen works around this by maintaining its OWN parallel short-phrase map (`_STAGE_SHORT_PHRASES` / `_FORM_SHORT_PHRASES`), which is a maintenance hazard.

### 1.9 Inventory Summary Table

| Module | File LOC | Distinct phrase banks | Total label/tier slots | Variants per slot (current) | Short/Long split? |
|---|---|---|---|---|---|
| context_engine | 1,062 | 6 (3 original + 3 EXT) | 5 + 4 + 5 = 14 | 3 (orig) / 8 (ext) | NO |
| career_phase_engine | 694 | 2 (1 orig + 1 EXT) | 6 | 3 / 8 | NO |
| narrative_families | 577 | 1 | 4 | **3 only** | NO |
| legacy_engine | 498 | 1 | 4 | **3 only** | NO |
| memory_engine | 691 | 0 (deterministic composition) | 5 inputs | ~6-8 each input | NO |
| headline_engine | 570 | 0 (inline strings) | 4 headline types | **1** per family | NO |
| voice.py | 905 | 8 | 25+20+7+7 = 59 attrs/traits | 2-3 per tier | NO |
| voice_display | 204 | 0 | 0 | N/A | N/A |
| **TOTAL** | **5,829** | **18** | **~91 slots** | **2-8 per slot** | **NO** |

---

## 2. Repetition Diagnosis

### 2.1 The "8 variants" claim verification

**Direct DB query (executed against `data/cage_empire.db`):**

```sql
SELECT SUBSTR(momentum, INSTR(momentum, '||') + 2) AS phrase, COUNT(*) AS n
FROM fighter_descriptors WHERE momentum IS NOT NULL
GROUP BY phrase ORDER BY n DESC LIMIT 20;
```

**Results (momentum column, 4,450 non-null rows):**

| Phrase | Count | Appears in `_EXT`? |
|---|---|---|
| `neither hot nor cold right now` | 1,501 | YES (variant #3, original) |
| `holding steady` | 1,459 | YES (variant #1, original) |
| `form has been consistent` | 1,416 | YES (variant #2, original) |
| `needs to turn things around` | 15 | YES (falling variant #2, original) |
| `trending upward fast` | 11 | YES (high variant #3, original) |
| `sliding in the wrong direction` | 11 | YES (falling variant #1, original) |
| `form is dipping` | 7 | YES (falling variant #3, original) |
| `the wheels are coming off` | 6 | YES (collapsing variant #2, original) |
| `building serious momentum` | 5 | YES (high variant #2, original) |
| `riding a hot streak` | 4 | YES (high variant #1, original) |
| `in freefall` | 4 | YES (collapsing variant #1, original) |
| `desperately needs a win` | 4 | YES (collapsing variant #3, original) |
| `riding a blistering hot streak` | 3 | YES (very_high variant #1, original) |
| `on fire and unstoppable right now` | 3 | YES (very_high variant #2, original) |
| `the division is on notice` | 1 | YES (very_high variant #3, original) |

**Distinct phrases: 15 out of theoretical max of 40** (8 variants × 5 momentum labels). All 15 phrases that appear are from the ORIGINAL 3-variant banks. NONE of the 25 NEW `_EXT`-only variants (e.g., `"scorching the earth on the way to a title shot"`, `"white-hot and nobody's got the answer"`, `"the slide is on and the camp knows it"`) appear in the cache.

**Conclusion:** The "8 variants per label" expansion in the code has NOT propagated to the production DB. The cache still uses the original 3-variant picker output.

**Root cause:** When the `_EXT` pickers were added (commit `1149538`, per the UI-FIX-2-SIGNOFF worklog entry), `snapshot_cache.ENGINE_VERSION` was NOT bumped from `"1.5.0"`. The version-mismatch rebuild logic that would force a full cache rebuild never triggered. The `last_built_date='2026-07-20'` (8 days before this audit) suggests the user has not advanced a day since the `_EXT` code landed — OR the daily pass ran but only did `UPDATE` (not a forced rebuild) and somehow the `_EXT` picker isn't wired in. (Code reading confirms it IS wired in at lines 877-878 — so the issue is the user hasn't Advanced Day since the code shipped.)

### 2.2 Top 20 phrases per column (full report)

#### `momentum` (4,450 non-null rows; 15 distinct phrases; avg 296.7 fighters per phrase)

Top 3 phrases account for **4,376 / 4,450 = 98.3%** of all rows. All 3 are the original `stable` variants.

#### `pressure` (4,450 non-null rows; 9 distinct phrases; avg 494.4 fighters per phrase)

| Phrase | Count | Label |
|---|---|---|
| `some pressure to perform` | 1,393 | moderate (orig #1) |
| `moderate expectations to meet` | 1,389 | moderate (orig #3) |
| `needs to stay on track` | 1,360 | moderate (orig #2) |
| `no real pressure right now` | 70 | minimal (orig #1) |
| `playing with house money` | 65 | minimal (orig #2) |
| `carefree and loose` | 65 | minimal (orig #3) |
| `needs a big performance soon` | 43 | high (orig #3) |
| `the heat is on` | 33 | high (orig #2) |
| `under real pressure` | 32 | high (orig #1) |

Top 3 (all `moderate`) account for **4,142 / 4,450 = 93.1%** of all rows.

#### `career_phase` (4,450 non-null rows; 18 distinct phrases; avg 247.2 fighters per phrase)

| Phrase | Count | Label |
|---|---|---|
| `a surging contender with the division on notice` | 1,164 | rising_contender (orig #3) |
| `a rising contender climbing the ranks` | 1,123 | rising_contender (orig #1) |
| `an up-and-comer knocking on the door of title contention` | 1,089 | rising_contender (orig #2) |
| `a blue-chip prospect early in his career` | 333 | prospect (orig #3) |
| `a young prospect with the world ahead of him` | 316 | prospect (orig #1) |
| `an up-and-coming talent finding his feet` | 307 | prospect (orig #2) |
| `the king of the division` | 23 | champion (orig #2) |
| `the reigning champion` | 17 | champion (orig #1) |
| `a grizzled veteran who's seen it all` | 10 | veteran (orig #1) |
| `a fading name running out of time` | 10 | declining (orig #2) |
| `a battle-tested old hand` | 9 | veteran (orig #2) |
| `the titleholder` | 8 | champion (orig #3) |
| `a once-great fighter sliding toward the exit` | 8 | declining (orig #3) |
| `a fighter on the decline` | 8 | declining (orig #1) |
| `a seasoned roadblock for rising hopefuls` | 7 | gatekeeper (orig #2) |
| `a gatekeeper testing the next generation` | 7 | gatekeeper (orig #1) |
| `a divisional gatekeeper who's seen them come and go` | 7 | gatekeeper (orig #3) |
| `a wily veteran still going strong` | 4 | veteran (orig #3) |

Top 3 (all `rising_contender`) account for **3,376 / 4,450 = 75.9%** of all rows.

#### `legacy_state` (4,450 non-null rows; 7 distinct phrases; avg 635.7 fighters per phrase)

| Phrase | Count | Label |
|---|---|---|
| `too early to judge their legacy` | 1,518 | building (orig #3) |
| `still building a legacy` | 1,475 | building (orig #1) |
| `the story is just beginning` | 1,435 | building (orig #2) |
| `a solid career that's earned respect` | 9 | established (orig #2) |
| `an established career with real accomplishments` | 6 | established (orig #1) |
| `a body of work that speaks for itself` | 6 | established (orig #3) |
| `an all-time great` | 1 | legendary (orig #2) |

Top 3 (all `building`) account for **4,428 / 4,450 = 99.5%** of all rows. There is NO `_EXT` version for legacy — even after a forced rebuild, only 3 variants × ~1476 fighters per phrase = massive repetition.

#### `narrative_family` (30 non-null rows; 7 distinct phrases; avg 4.3 fighters per phrase)

| Phrase | Count | Label |
|---|---|---|
| `an old warhorse still saddling up` | 9 | veteran (orig #2) |
| `a grizzled veteran who refuses to fade quietly` | 7 | veteran (orig #1) |
| `a can't-miss prospect with star written all over him` | 6 | prodigy (orig #3) |
| `a veteran who's been around the block more times than he can count` | 4 | veteran (orig #3) |
| `nobody saw this coming — an improbable rise` | 2 | cinderella_story (orig #2) |
| `the wunderkind everyone's talking about` | 1 | prodigy (orig #2) |
| `a Cinderella story defying the odds` | 1 | cinderella_story (orig #1) |

Only **30 / 4,450 = 0.7%** of fighters have a narrative_family at all. The 4 MVP rules (prodigy / fallen_champion / cinderella_story / veteran) are too narrow to cover most fighters. There is NO `_EXT` version.

### 2.3 Label distribution (the deeper skew)

Even if every variant bank were 50 phrases deep, repetition would still be visible because the LABEL rules pile most fighters into one bucket:

| Column | Skew | Why |
|---|---|---|
| `momentum` | 98.3% `stable` | The `stable` bucket catches win_streak 0-2 AND loss_streak 0-1 — most fighters fresh off a fight have one of these. Only 5+ win streak = very_high, 3-4 = high, 2+ loss = falling, 4+ loss = collapsing. |
| `pressure` | 93.1% `moderate` | The pressure factor list (8 factors, threshold 1-2 = moderate) catches almost every fighter who has at least 1 of: contract ending soon, age ≥ 35, ranked top 10, champion, free agent, etc. Most active fighters have 1-2 factors. |
| `career_phase` | 75.9% `rising_contender` | `rising_contender` is the DEFAULT for active fighters (per D4 in career_phase_engine). The other 5 phases have narrow criteria (prospect requires age < 24 AND < 10 fights; veteran requires age ≥ 35 AND ≥ 20 fights; etc.). |
| `legacy_state` | 99.5% `building` | `building` requires NOT in HoF AND (< 15 fights OR < 25 fights with < 15 wins). In a fresh DB, most fighters have < 25 fights → most are `building`. |
| `narrative_family` | 99.3% NULL | The 4 MVP rules are mutually narrow. 3 of them require a specific career_phase AND a specific momentum band simultaneously. |

### 2.4 Sample 50 random fighter_descriptors (variety check)

To verify the "8 variants" claim per the user's instructions, I sampled 50 random rows and counted distinct phrases per label:

```
fighter_id= 2643  momentum=stable||holding steady
fighter_id= 1146  momentum=stable||neither hot nor cold right now
fighter_id=  592  momentum=stable||form has been consistent
fighter_id= 1315  momentum=stable||form has been consistent
fighter_id= 3838  momentum=stable||form has been consistent
... (45 more rows sampled, all `stable` with the same 3 phrases)
```

**Result:** Of 50 random rows, **all 50 had `momentum='stable'`** and only the original 3 variants appeared. None of the 5 `_EXT`-only variants for `stable` appeared. This confirms the cache is stale relative to the code.

---

## 3. Screen-by-Screen Phrase Usage Audit

### 3.1 Dashboard (`src/ui/screens/dashboard.py` — 2,035 lines)

**Interpretation columns displayed:**
- `daily_headlines.headline_text` + `body_text` (Top Story + 3 Other Headlines)
- `fighter_descriptors.narrative_family` (Top Prospect card voice phrase)
- `fighter_descriptors.momentum` (Hottest Streak + Biggest Fall card voice phrases)
- `fighter_descriptors.career_phase` (implicitly, via Top Prospect's narrative lookup)

**Where repetition is most jarring:**
1. **Top Story card** — Each narrative family has only 1 headline_text + 1 body_text. If `prodigy` is the top story for 5 consecutive days, the player sees `"The prodigy turns heads again"` 5 times. Over a 30-day month where prodigy dominates: 20+ identical headlines.
2. **Other Headlines list** — `fastest_rising` is always `"{Name} is rising fast"` and `biggest_fall` is always `"{Name} is sliding fast"`. Same headline every day, only the name changes.
3. **Top Prospect card** — Has a hardcoded fallback `default_voice="the wunderkind everyone's talking about"` (line 1670). When the cache is fresh, this is overridden by the prodigy narrative phrase. But that phrase has only 3 variants — across 7 prodigies in the DB, 6 will share a phrase with another prodigy.
4. **Hottest Streak + Biggest Fall cards** — Display the `momentum` voice phrase. With the original 3-variant picker active in the DB, the player sees `"holding steady"` (or one of its 2 siblings) for every "stable" fighter — which is most fighters.

**Short vs long variant need:**
- Card titles (HOTTEST STREAK, TOP PROSPECT, BIGGEST FALL) — already short (uppercase labels), no change needed
- Card body phrase — currently uses the full momentum/narrative phrase. Could benefit from a MEDIUM variant (~10-15 words). The "long" 15-30 word variant would be too tall for a card.
- Top Story body_text — already long-form. This is where the "long" variants (15-30 words) belong.
- Other Headlines list — short headline_text is fine; could add a short body_text snippet (~8 words) below each.

### 3.2 Roster (`src/ui/screens/roster.py` — 1,935 lines)

**Interpretation columns displayed:**
- `fighter_descriptors.career_phase` → decoded via `_stage_short_phrase` (line 485) — uses the parallel `_STAGE_SHORT_PHRASES` map (1 phrase per label)
- `fighter_descriptors.momentum` → decoded via `_form_short_phrase` (line 502) — uses the parallel `_FORM_SHORT_PHRASES` map (1 phrase per label)

**Short phrase maps (line 466-482):**
```python
_STAGE_SHORT_PHRASES = {
    "prospect": "Prospect",
    "rising_contender": "Rising Contender",
    "champion": "Champion",
    "veteran": "Veteran",
    "gatekeeper": "Gatekeeper",
    "declining": "Declining",
}
_FORM_SHORT_PHRASES = {
    "very_high": "Blazing Hot",
    "high": "Heating Up",
    "stable": "Steady",
    "falling": "Cooling Off",
    "collapsing": "Free Fall",
}
```

**Where repetition is most jarring:**
1. **Every "rising_contender + stable" fighter (3,376 × 4,376 = most of the roster) renders as `Rising Contender | Steady`**. In a 60-row table view, the player sees the exact same Stage+Form combo on 40+ rows.
2. **The short phrase maps are 1-variant-per-label** — zero variety. This was an intentional design choice (table cells need consistent width), but it's the single largest source of perceived repetition.
3. **The long cache phrase (`momentum='stable||holding steady'`) is decoded but THROWN AWAY** — the Roster only uses the LABEL to look up the short phrase. The voice phrase work in the interpretation layer is invisible to the Roster screen.

**Short vs long variant need:**
- Roster table cells — need 3-5 SHORT variants per label so the table can rotate phrases per row. The current "1 phrase per label" approach is the root cause of "every row reads the same".
- Hover tooltip or expandable row — could surface the LONG cache phrase on hover for context.

### 3.3 Fighter Profile (`src/ui/screens/fighter_profile.py` — 2,535 lines)

**Interpretation columns displayed:**
- `fighter_descriptors.career_phase` (line 1690) — via `display_phrase` → title-cased full phrase
- `fighter_descriptors.momentum` (line 1692) — via `display_phrase`
- `fighter_descriptors.pressure` (line 1694) — via `display_phrase`
- `fighter_descriptors.narrative_family` (line 1696) — via `display_phrase`, fallback `"(None)"`
- `fighter_descriptors.legacy_state` (line 1698) — via `display_phrase`
- `compute_trajectory_for_fighter` (line 1669) — derived label, fed to `get_trajectory_phrase_ext` with `rng = random.Random(fighter_id)` — uses the EXT picker
- `fighter_descriptors.attribute_descriptors` JSON — title-cased attribute descriptors in the attribute grid
- `fighter_descriptors.personality_descriptors` JSON — title-cased personality descriptors
- `fighter_descriptors.overall_desc` — the describe_overall one-sentence summary
- `fighter_descriptors.career_stage` — from voice.describe_career_stage

**Where repetition is most jarring:**
1. **Identity block shows the SAME 6 phrases every time the player opens the profile** — RNG is seeded by `fighter_id` (or `fighter_id * 31 + 17`), so the phrase is deterministic. The fighter never "reads differently" between visits, even across many in-game days.
2. **The attribute grid shows the descriptor AND the `overall_desc` sentence uses the same descriptor** — e.g., `punch_power` row shows `"One-Punch Knockout Threat"` AND the overall reads `"...with one-punch knockout threat..."`. Same phrase, twice, on one screen.
3. **`overall_desc` builder (`describe_overall`, voice.py line 701)** uses only ONE `_pick` per attribute and ONE `_pick` for the career stage — so the overall is also deterministic. With 4,450 fighters sharing ~25 career_stage phrases × ~500 attribute descriptor phrases, the overall sentence structure is highly templated: `"{Name} is a {archetype} with {attr1} and {attr2}, riding a {N}-fight win streak, currently {career_stage}."`
4. **Legacy + Narrative phrases are EXTRA repetitive** because they have only 3 variants each and no `_EXT` version. A Fighter Profile showing `legacy_state='building'` will display one of only 3 phrases, and 99.5% of fighters are `building`.

**Short vs long variant need:**
- Identity block — currently uses the full cache phrase. Could benefit from a LONG variant (15-30 words) for narrative depth. The current phrases are 4-10 words, which feels thin in a profile.
- Attribute grid — SHORT variants needed (2-4 words) so the grid reads cleanly.
- Overall sentence — needs structural variety (3-4 sentence templates) in addition to phrase variety.

### 3.4 Free Agents (`src/ui/screens/free_agents.py` — 1,932 lines)

**Interpretation columns displayed:** Same as Roster — `_STAGE_SHORT_PHRASES` + `_FORM_SHORT_PHRASES` + `_stage_short_phrase` + `_form_short_phrase` helpers (lines 375-423, near-identical copies of the Roster's helpers).

**Where repetition is most jarring:**
1. **Identical issue to Roster** — every `rising_contender + stable` free agent renders as `Rising Contender | Steady`.
2. **The 601 free agents skew toward `rising_contender` + `stable` even harder** (most are unsigned because they're middling, not because they're elite). The repetition is denser here than on the Roster.
3. **Code duplication** — the `_STAGE_SHORT_PHRASES` / `_FORM_SHORT_PHRASES` maps are COPY-PASTED between Roster and Free Agents. Any future short-phrase expansion has to be applied in both files (maintenance hazard).

**Short vs long variant need:** Same as Roster — need 3-5 SHORT variants per label, rotatable per row.

### 3.5 Screen-by-Screen Summary Table

| Screen | Interpretation columns shown | SHORT variants needed? | LONG variants needed? | Most jarring repetition |
|---|---|---|---|---|
| Dashboard | headline_text + body_text, narrative_family, momentum | No (cards already compact) | Yes (Top Story body, watch card phrases) | Same headline 5+ days in a row; same momentum phrase across 3 watch cards |
| Roster | career_phase, momentum (via short maps) | Yes (3-5 per label, rotatable per row) | No (table context) | Every `rising_contender + stable` row reads `Rising Contender \| Steady` |
| Fighter Profile | career_phase, momentum, pressure, narrative_family, legacy_state, trajectory + 45 attribute/personality descriptors + overall_desc | Yes (attribute grid cells) | Yes (identity block, overall prose) | Same 6 identity phrases on every visit; same descriptor in grid + overall |
| Free Agents | Same as Roster | Yes | No | Same as Roster |

---

## 4. Concrete Variety Improvement Plan

This section proposes, for EACH interpretation module:
- **Short variant set** (3-8 words, for table cells + compact cards) — 12-15 candidates per label
- **Long variant set** (15-30 words, for Fighter Profile prose + Dashboard cards) — 8-10 candidates per label
- **Conditional triggers** — when to pick short vs long
- **Variety selection algorithm** — the rotation logic

### 4.1 Variety Selection Algorithm (applies to ALL modules)

**Replace the current `rng = random.Random(fighter_id * 31 + 17)` single-pick with a context-aware rotation:**

```python
def pick_phrase(fighter_id, label, screen_context, tick_counter, 
                short_bank, long_bank, recent_cache):
    """Pick a phrase with short/long + no-repeat-within-N semantics.
    
    Args:
        fighter_id: int — for deterministic per-fighter base offset
        label: canonical label (e.g., "stable", "rising_contender")
        screen_context: "table" | "card" | "profile" | "headline"
        tick_counter: int — in-game day counter (rotates every 5 days)
        recent_cache: list of phrases shown recently on this screen
            (per-screen, in-memory; cleared on screen exit)
    
    Returns:
        A phrase string. Deterministic per (fighter_id, tick_bucket, 
        screen_context) — the same fighter on the same day shows the 
        same phrase, but the phrase rotates every 5 in-game days and 
        varies by screen context.
    """
    # Pick the bank based on screen context.
    if screen_context in ("table", "card_compact"):
        bank = short_bank[label]
    elif screen_context in ("profile", "headline", "card"):
        bank = long_bank[label]
    else:
        bank = short_bank[label] + long_bank[label]  # mix
    
    # Tick bucket — rotates every 5 in-game days. This means the 
    # fighter's phrase changes weekly, which gives the player a sense 
    # of "the story is evolving" without flickering on every visit.
    tick_bucket = tick_counter // 5
    
    # Deterministic offset — hash of (fighter_id, label, tick_bucket).
    # Same fighter + same week = same phrase. Next week = different 
    # phrase (if the bank has > 1 variant).
    import hashlib
    h = int(hashlib.md5(
        f"{fighter_id}|{label}|{tick_bucket}".encode()
    ).hexdigest(), 16)
    base_idx = h % len(bank)
    
    # No-repeat-within-N: if the picked phrase is in recent_cache 
    # (shown on this screen in the last N=3 renders), advance to the 
    # next variant. This prevents the same phrase appearing twice on 
    # one screen.
    idx = base_idx
    for _ in range(len(bank)):
        phrase = bank[idx % len(bank)]
        if phrase not in recent_cache:
            return phrase
        idx += 1
    
    return bank[base_idx]  # fallback if all phrases are recent
```

**Why this design:**
- **Deterministic per fighter per week** — no UI flickering within a session
- **Rotates every 5 days** — gives a sense of narrative evolution
- **Screen-context aware** — table gets short phrases, profile gets long
- **No-repeat cache** — prevents the same phrase appearing twice on one screen render
- **Hash-based, not RNG** — survives across Python restarts (no need to seed RNG state)

**Migration path:** The cache column stores the LONG phrase (for profile rendering). The SHORT phrase is computed at render time from the label + fighter_id + screen context. This means the cache schema doesn't need to change for short phrases — only the render-time picker does.

### 4.2 context_engine — momentum

**Label distribution (production DB):** stable 98.3%, falling 0.7%, high 0.4%, collapsing 0.3%, very_high 0.2%

**Short variant set (3-8 words), 12-15 per label:**

`very_high` (12 short):
1. `on absolute fire`
2. `white-hot right now`
3. `can't miss these days`
4. `the hottest hand going`
5. `unstoppable momentum`
6. `riding a torrid streak`
7. `scorching the division`
8. `nobody's got the answer`
9. `blistering hot streak`
10. `the division is on notice`
11. `winning everything in sight`
12. `the streak everyone's talking about`

`high` (12 short):
1. `heating up fast`
2. `trending upward`
3. `riding a hot streak`
4. `building real momentum`
5. `the wind at his back`
6. `stringing wins together`
7. `finding his rhythm`
8. `rolling right now`
9. `on a tear`
10. `climbing the rankings fast`
11. `trending the right way`
12. `the contender on the move`

`stable` (15 short — needs more because 98% of fighters land here):
1. `holding steady`
2. `form's been consistent`
3. `neither hot nor cold`
4. `just showing up`
5. `steady as she goes`
6. `no real swing either way`
7. `reliably present`
8. `doing the work`
9. `a known quantity`
10. `the steady middle`
11. `consistent without being spectacular`
12. `form holding firm`
13. `neither flying nor fading`
14. `quietly getting it done`
15. `a steady hand`

`falling` (12 short):
1. `sliding the wrong way`
2. `form is dipping`
3. `needs a turnaround`
4. `the slide is on`
5. `a rough patch`
6. `the losses are stacking`
7. `form has slipped`
8. `searching for answers`
9. `trending the wrong way`
10. `the doubters are loud`
11. `cooling off`
12. `losing his grip`

`collapsing` (12 short):
1. `in freefall`
2. `the wheels are off`
3. `desperately needs a win`
4. `the bottom dropped out`
5. `spiraling`
6. `a tailspin`
7. `one loss from crisis`
8. `the skid is real`
9. `falling apart fast`
10. `the end feels near`
11. `running out of road`
12. `careers don't always recover`

**Long variant set (15-30 words), 8-10 per label:**

`very_high` (8 long):
1. `The hottest hand in the sport right now — scorching the earth on the way to a title shot and nobody in the division has an answer for him.`
2. `Riding the kind of win streak that defines a career. Every opponent is a name on the resume; every camp knows the math is bad.`
3. `White-hot and picking up speed. The matchmakers are scrambling for opponents; the analysts are running out of superlatives; the belt is in sight.`
4. `He can't put a foot wrong these days. The division has been put on notice — the title shot is a matter of when, not if.`
5. `This is the run people will remember. Five straight wins, each more emphatic than the last, and the champion is watching every minute of tape.`
6. `The kind of momentum that turns contenders into champions. He's not just winning fights — he's ending careers and remaking the division in his image.`
7. `Every time he fights, the sport stops to watch. The streak has become the story of the season, and the title picture now runs through him.`
8. `He's the fighter nobody wants to see on the other side of the cage. The streak has gone past hot — it's become inevitable.`

`high` (8 long):
1. `Trending upward fast and the division is taking notice. The wind is at his back; the matchups are getting bigger; the title conversation is starting.`
2. `Stringing together the kind of run that turns heads. He's found his rhythm at the right time and the contender queue is shortening.`
3. `Building serious momentum with each outing. The matchmakers like what they see; the rankings are shifting; the path is clearing.`
4. `Rolling right now and the matchup math favors him. A few more wins like this and the title shot conversation gets serious.`
5. `The kind of form that makes a contender. He's not at the summit yet, but the climb is steady and the summit is in sight.`
6. `A fighter trending the way a contender should — winning the fights he's supposed to win, then winning the ones he's not.`
7. `The buzz is real. The rankings haven't caught up yet, but the camps already know — he's the next problem in the division.`
8. `He's found the version of himself the division was always afraid of. The streak isn't long yet, but it's the right kind of long.`

`stable` (10 long — needs more because of 98% concentration):
1. `A steady rhythm with no real swing either way — doing the work without the headlines, neither flying nor fading, just present.`
2. `Consistent without being spectacular. The kind of form that just keeps showing up: never the story, never the disaster.`
3. `Holding steady in the middle of the division. No streak to speak of, no slide to arrest — just a fighter taking care of business.`
4. `A known quantity in a division that respects that. The form is what it is; the matchup will decide the night, not the momentum.`
5. `Doing the work without the volatility. The kind of fighter you can build a card around — he shows up, he's ready, he fights his fight.`
6. `Reliably present, reliably competitive. No one is lining up to fight him and no one is running scared — he's just steady.`
7. `The form hasn't moved in either direction for a while now. He's the same fighter he was last month, and he'll be the same next month.`
8. `Neither the prospect on the rise nor the veteran on the way out — just a fighter in the middle of his career, doing the work.`
9. `The kind of steady that doesn't make headlines but does make careers. He'll be in the division for a while yet, doing exactly this.`
10. `Form has been consistent, results have been consistent, conversations have been consistent. The story here is that there is no story — yet.`

`falling` (8 long):
1. `The slide is on and the camp knows it. The losses are stacking into a story; the doubters are getting louder; the version he used to be is fading.`
2. `A rough patch that's starting to stick. The form has slipped, the matchup math is shifting, and the contender queue is receding.`
3. `Trending the wrong way and searching for the version of himself he used to be. Every camp sees it; every opponent believes.`
4. `The losses are starting to define him. He's still in the division, but the conversations around him have changed.`
5. `Form is dipping at the wrong time. The matchups are getting harder; the camp is getting longer; the patience is getting shorter.`
6. `A fighter on the wrong side of momentum. The slide isn't catastrophic yet, but the direction is clear and the clock is loud.`
7. `He's lost the version of himself that was winning fights. The skill is still there; the form isn't. The next fight matters more than the last one.`
8. `The kind of form that ages a fighter. He's not done, but the road back is longer than the road here was.`

`collapsing` (8 long):
1. `The bottom has dropped out and it's happening fast. The roster is starting to whisper; the matchmakers are running out of reasons to book him.`
2. `A tailspin nobody saw coming. The skid has gone past a rough patch — it's now the story of his career, and the story isn't close to finished.`
3. `Spiraling and the camp is running out of answers. One more loss and the conversation shifts from "how do we fix this" to "is it time".`
4. `The kind of fall that ends careers or restarts them. He's at the crossroads, and the next fight is the most important of his life.`
5. `The wheels aren't just coming off — they're already gone. Every fight is a referendum on whether he still belongs in the division.`
6. `A career in rapid decline and the clock is loud. The version of him the division remembers is gone; the question is what comes next.`
7. `Running out of road. The losses have stopped being surprising and started being expected — and that's the worst sign there is.`
8. `The end is in sight and the camp knows it. He's fighting for his career now, not for the title — and that's a different fight entirely.`

### 4.3 context_engine — pressure

**Label distribution:** moderate 93.1%, minimal 4.5%, high 2.4%, extreme 0% (none in DB)

**Short variant set, 12-15 per label:**

`minimal` (12):
1. `no pressure right now`
2. `playing with house money`
3. `carefree and loose`
4. `nothing to lose`
5. `low stakes, long leash`
6. `free swinging`
7. `no urgency`
8. `the safety net's intact`
9. `no heat at all`
10. `quietly going about it`
11. `under no pressure`
12. `just playing the game`

`moderate` (15 — needs more because 93% of fighters land here):
1. `some pressure to perform`
2. `needs to stay on track`
3. `moderate expectations`
4. `a quiet heat building`
5. `stakes are rising`
6. `the path is still clear`
7. `the matchup matters`
8. `a steady weight on him`
9. `expectations to meet`
10. `the division is watching`
11. `middle-of-the-road pressure`
12. `needs to keep delivering`
13. `the spotlight's warming`
14. `a manageable weight`
15. `the clock isn't loud yet`

`high` (12):
1. `under real pressure`
2. `the heat is on`
3. `needs a big performance`
4. `the spotlight's on him`
5. `the margin is gone`
6. `a must-show-up night`
7. `no slack left`
8. `the division is watching`
9. `the pressure's real`
10. `a defining fight`
11. `the clock is ticking`
12. `everything on the line`

`extreme` (12):
1. `fighting for his career`
2. `do-or-die`
3. `back against the wall`
4. `no room for an off night`
5. `the wall is up`
6. `everything on the line`
7. `the pressure has a name`
8. `maximum pressure`
9. `career-defining night`
10. `the division knows it`
11. `survival mode`
12. `the end or the restart`

**Long variant set, 8-10 per label:**

`moderate` (10 long — heaviest bucket):
1. `A quiet heat building in the background — the kind of expectations that focus a camp without breaking it. The stakes are rising but the path is still clear.`
2. `The matchup matters more than the talk suggests. He's not under the gun, but he's not carefree either — a steady weight on the shoulders and a clear path if he takes care of business.`
3. `Stakes rising, division watching. The next fight isn't make-or-break, but it shapes the next six months. A steady weight, manageable but real.`
4. `The kind of pressure that sharpens a fighter rather than crushes him. The expectations are real; the runway is still there; the next fight matters.`
5. `A middle-of-the-road pressure that most fighters live in. Not the title-picture heat, not the carefree minimum — just the steady weight of being a professional in a division full of them.`
6. `The spotlight's warming but not yet blinding. He needs to keep delivering; the division is taking notes; the path forward is clear if he walks it.`
7. `Expectations to meet, but the room to meet them. The kind of pressure that doesn't make headlines but does make careers.`
8. `The clock isn't loud yet, but it's ticking. A few more wins and the conversation changes; a few losses and it changes the other way.`
9. `A manageable weight that focus can carry. He's not fighting for his career — he's fighting for the next step up, which is a different kind of pressure.`
10. `The kind of steady, ambient pressure every contender lives with. The division is full of fighters who can take it; the ones who can't don't last.`

(Full short + long banks for `minimal`, `high`, `extreme` are omitted here for brevity — same pattern. The audit doc would ship them all.)

### 4.4 context_engine — trajectory (derived, not stored)

**Label distribution:** not in DB (computed on demand), but mirrors momentum distribution shifted by age.

**Short + long variant sets:** Same shape as momentum. 12 short + 8 long per label. Key voice notes:
- `rising` should feel anticipatory ("the best is yet to come")
- `peaking` should feel triumphant but transient ("the summit, right now")
- `declining` should feel elegiac ("father time is winning")
- `collapsing` should feel urgent ("the end is in sight")

### 4.5 career_phase_engine — career_phase

**Label distribution:** rising_contender 75.9%, prospect 21.5%, champion 1.1%, declining 0.6%, veteran 0.5%, gatekeeper 0.5%

**Short variant set, 12-15 per label:**

`rising_contender` (15 — heaviest bucket):
1. `a rising contender`
2. `climbing the ranks`
3. `knocking on the door`
4. `the division on notice`
5. `an up-and-comer`
6. `surging toward the top`
7. `trending upward`
8. `the contender queue`
9. `a name to watch`
10. `the next problem`
11. `climbing fast`
12. `on the contender track`
13. `making his move`
14. `the matchmakers' next call`
15. `the division's next test`

`prospect` (12):
1. `a young prospect`
2. `a blue-chip prospect`
3. `the world ahead of him`
4. `an up-and-comer`
5. `finding his feet`
6. `raw talent`
7. `a fresh face`
8. `learning on the job`
9. `the hype train is building`
10. `a beginner's confidence`
11. `early in his career`
12. `the scouts are whispering`

`champion` (12):
1. `the reigning champion`
2. `the king of the division`
3. `the titleholder`
4. `the man with the belt`
5. `the standard-bearer`
6. `the champ nobody's figured out`
7. `wearing the gold`
8. `the division's benchmark`
9. `the target on his back`
10. `the throne`
11. `the belt holder`
12. `the champion`

`veteran` (12):
1. `a grizzled veteran`
2. `a battle-tested hand`
3. `a wily veteran`
4. `an old soul`
5. `seen it all before`
6. `a survivor`
7. `still going strong`
8. `the cagey veteran`
9. `every camp needs him`
10. `a generation deep`
11. `the old guard`
12. `still here`

`gatekeeper` (12):
1. `a gatekeeper`
2. `the last boss`
3. `a seasoned roadblock`
4. `the name on the resume`
5. `the wall`
6. `testing the next gen`
7. `the prospect's exam`
8. `seen them come and go`
9. `the lock on the door`
10. `a divisional gatekeeper`
11. `the contender's toll booth`
12. `the proving ground`

`declining` (12):
1. `on the decline`
2. `a fading name`
3. `running out of time`
4. `the slide is real`
5. `best years behind him`
6. `running on fumes`
7. `borrowed time`
8. `the division forgetting`
9. `the twilight`
10. `searching for past glory`
11. `past his peak`
12. `the long goodbye`

**Long variant set, 8-10 per label:**

`rising_contender` (10 long):
1. `A rising contender climbing the ranks with the division on notice — the matchmakers can't ignore him anymore, and the title conversation is starting to include his name.`
2. `The next big thing if he keeps delivering. Trending upward and the rankings show it; the buzz is real and the contender queue is shortening.`
3. `A killer in the contender queue. He's not at the summit yet, but the climb is steady, the matchups are getting bigger, and the champion is taking notes.`
4. `The kind of name that turns from prospect to contender in a single fight. He's already done it once; the question is whether he can do it again.`
5. `An up-and-comer knocking on the door of title contention. The matchup math favors him more often than not, and the path to the belt is clearing.`
6. `A surging contender with the division on notice. He's not the next fight the champion wants, but he's the next fight the champion needs.`
7. `Trending upward and the division knows it. Every camp has an opinion; every analyst has a take; the contender queue is shifting around him.`
8. `The buzz is real and the rankings are catching up. He's the fighter nobody wants to see across the cage right now — and the matchmakers know it.`
9. `A name the matchmakers can't ignore anymore. He's done the work; he's won the fights; the next step is the one that matters.`
10. `The contender on the move. The path isn't easy from here — but the path is clear, and he's the one walking it.`

(Full long banks for the other 5 phases omitted for brevity.)

### 4.6 narrative_families — narrative_family

**Label distribution:** NULL 99.3%, veteran 0.4%, prodigy 0.2%, cinderella_story 0.1%, fallen_champion 0% (none in DB)

**Critical issue:** Only 30 fighters out of 4,450 have a narrative family. The rules are too narrow. Phase 3+ should add more families (gatekeeper, dynasty, dark_horse, late_bloomer, redemption_arc, final_run, changing_of_the_guard, giant_killer, nearly_man, champion_in_waiting — all documented in the engine's D2 comment).

**Short + long variant set (12 short + 8 long per family) — sample for `prodigy`:**

`prodigy` short (12):
1. `the wunderkind`
2. `a prodigy turning heads`
3. `the can't-miss kid`
4. `the prospect with star written on him`
5. `the rookie scouts whisper about`
6. `the next big thing`
7. `the division's brightest young talent`
8. `the hype is real`
9. `the prodigy`
10. `the kid everyone's talking about`
11. `the blue-chip prospect`
12. `the future of the division`

`prodigy` long (8):
1. `The wunderkind everyone's talking about — the kind of prospect scouts whisper about and matchmakers save for the right night. The future of the division, arriving ahead of schedule.`
2. `A prodigy turning heads early. He's not supposed to be this good this young; the division is still figuring out what to do with him; the belt is closer than his age suggests.`
3. `The can't-miss kid with star written all over him. Every camp has a theory on how to beat him; none of them have worked yet. The hype train has an engine.`
4. `The prospect the entire division is measuring itself against. He's not just winning — he's winning the way future champions win, and the timetable is accelerating.`
5. `The rookie the scouts whisper about when no one's listening. The skill set is real; the ceiling is higher than the division is comfortable with; the next fight is the next chapter.`
6. `A prodigy in a hurry. Every fight answers one question and asks two more. The division is watching tape it didn't expect to be watching for years.`
7. `The kind of young talent that comes along once in a generation. He's not the future — he's the present that's running ahead of schedule.`
8. `The blue-chip prospect who's already outperforming the blue chip. Every prediction about his ceiling has been wrong so far — on the low side.`

### 4.7 legacy_engine — legacy_state

**Label distribution:** building 99.5%, established 0.5%, legendary 0.02%, forgotten 0% (none in DB — no retired non-HoF fighters with < 20 fights)

**Critical issue:** `building` catches 99.5% of fighters. The phrase bank needs to be MUCH larger (20+ short variants) to avoid repetition. AND the legacy rules should be retuned — a 28-year-old with 15 fights and a 12-3 record isn't really "still building"; they're mid-career. Consider adding a `mid-career` legacy state.

**Short variant set, 15-20 per label (especially `building`):**

`building` (20 short — heaviest bucket):
1. `still building`
2. `the story's just beginning`
3. `too early to judge`
4. `early chapters`
5. `the legacy is unwritten`
6. `writing the first chapters`
7. `the story is starting`
8. `a career in progress`
9. `the book isn't written yet`
10. `too soon to say`
11. `the jury's still out`
12. `the foundation's being laid`
13. `a legacy under construction`
14. `the early work`
15. `finding his footing`
16. `the opening act`
17. `setting the stage`
18. `no legacy yet`
19. `the story hasn't started`
20. `the page is blank`

`building` long (10 — needs more because of 99% concentration):
1. `The story is just beginning — too early to judge the legacy, but the early chapters are promising. The book isn't written yet; the next fight is the next page.`
2. `Still building a legacy, one fight at a time. The foundation is being laid; the chapters that matter are still ahead. The jury's out — and that's not a bad place to be.`
3. `A career in progress. The legacy is unwritten, the page is blank, and every fight adds a sentence. Too soon to say what the book will be.`
4. `The opening act of a career that could go anywhere from here. The foundation's being laid; the structure isn't visible yet; the story hasn't really started.`
5. `Too early to judge — but not too early to watch. The early work is promising enough that the division is paying attention to what comes next.`
6. `Setting the stage. A legacy under construction, with the first chapters written but the ending nowhere in sight. The book is being written.`
7. `The kind of start that makes you curious about the middle. Nothing is decided yet; everything is on the table; the next fight matters more than the last one.`
8. `A career finding its footing. The legacy question is years away from an answer — but the early returns are interesting enough to keep asking.`
9. `Writing the first chapters of what could be a long book. The legacy is unwritten; the page is blank; the next fight is the next sentence.`
10. `Too soon to say what he'll be remembered for — if anything. But the early work suggests it'll be something, and the something is worth waiting to find out.`

### 4.8 headline_engine — 4 headline types

**Critical issue:** Each headline type has only 1 hardcoded headline_text + 1 body_text per family. This is the most extreme repetition source — 30 days of `fastest_rising` = 30 identical headlines.

**Proposed:** For each (headline_type, family) combination, provide 8-10 headline_text variants + 8-10 body_text variants.

**Sample for `top_story` + `prodigy` (currently only 1 each):**

Headline variants (8):
1. `The prodigy turns heads again`
2. `The wunderkind delivers once more`
3. `The hype just keeps getting realer`
4. `The kid nobody can figure out`
5. `The prodigy keeps proving everyone right`
6. `The future is arriving ahead of schedule`
7. `The division's brightest young talent strikes again`
8. `The prospect the scouts whisper about — and the division fears`

Body variants (8):
1. `{name} keeps proving the hype is real. The division's brightest young talent continues to surge — and the timetable to the title shot is accelerating.`
2. `Another night, another statement from {name}. The wunderkind everyone's talking about just gave the division another reason to talk — and the champion another reason to watch tape.`
3. `The prospect with star written all over him added another chapter. {name} is no longer a name to watch; he's a name to fear.`
4. `The kid keeps delivering. {name} was supposed to be a few years away from this conversation; the calendar is being rewritten around him.`
5. `Every prediction about {name}'s ceiling has been wrong so far — on the low side. The division is running out of superlatives and running out of opponents.`
6. `The prodigy turned heads again. {name} did what prospects aren't supposed to do, the way future champions do it, on a timeline nobody expected.`
7. `The matchmakers' problem is getting bigger. {name} just beat the contender he wasn't supposed to beat yet — and the title picture now runs through him.`
8. `The hype train has an engine. {name} just gave the division a glimpse of what's coming — and what's coming is closer than anyone thought.`

### 4.9 voice.py — attribute + personality descriptors

**Critical issue:** 2-3 variants per tier is too few for 4,450 fighters. With ~5-7 tiers per attribute × 25 attributes, the pigeonhole math is brutal: 4,450 fighters × 25 attributes / (7 tiers × 3 variants) = ~530 fighters per (attribute, tier, variant) cell.

**Proposed:** Expand to 8-10 variants per tier for the most-shown attributes (punch_power, chin, cardio, fight_iq, durability) and 5-6 for the rest.

**Sample for `punch_power.elite` (currently 3; expand to 10):**

Short (10):
1. `one-punch knockout threat`
2. `fight-ending power in both hands`
3. `heavy hands that end careers`
4. `concussive power`
5. `the kind of pop that turns lights out`
6. `elite finishing power`
7. `true one-shot power`
8. `every punch a potential finish`
9. `the division's hardest hitter`
10. `lights-out power`

Long (5) — for `overall_desc` prose:
1. `carries fight-ending power in both hands — the kind of pop that ends careers and remakes divisions`
2. `a one-punch knockout threat every second he's standing — the division's hardest hitter by a wide margin`
3. `heavy hands that have ended careers and turned contender conversations — true one-shot power, both sides`
4. `the kind of concussive power that makes game plans irrelevant — one clean shot and the night is over`
5. `elite finishing power in both hands — every punch a potential finish, every exchange a potential ending`

### 4.10 Conditional triggers (when SHORT vs LONG)

| Screen / Context | Variant length | Trigger |
|---|---|---|
| Roster table cell | SHORT (3-8 words) | `screen_context = "table"` — always short |
| Free Agents table cell | SHORT | `screen_context = "table"` |
| Dashboard Top Story headline | SHORT (3-8 words, punchy) | `screen_context = "headline"` |
| Dashboard Top Story body | LONG (15-30 words) | `screen_context = "headline_body"` |
| Dashboard Fighter Watch cards | MEDIUM (8-15 words) | `screen_context = "card"` — between short and long |
| Dashboard Other Headlines list | SHORT headline + MEDIUM body | `screen_context = "headline"` + `"headline_body"` |
| Fighter Profile identity block | LONG (15-30 words) | `screen_context = "profile"` |
| Fighter Profile attribute grid | SHORT (2-4 words) | `screen_context = "table"` |
| Fighter Profile overall_desc | LONG (15-30 words, varied structure) | `screen_context = "profile"` |
| News items | LONG (15-30 words) | `screen_context = "news"` |
| Memory phrases | MEDIUM (8-15 words) | `screen_context = "card"` |
| Scouting reports | LONG (15-30 words) | `screen_context = "profile"` |

**Additional triggers (layered on top of screen context):**

1. **Career phase override:** A `prospect` with `momentum='very_high'` should always get a LONG narrative phrase (the wunderkind story is the headline). A `veteran` with `momentum='stable'` should get a SHORT phrase (the veteran's story is told; the momentum is just status quo).
2. **Recent fight outcome override:** If the fighter just won by KO, momentum phrase should be flavor-shifted ("knocked out his last opponent" rather than generic "hot streak"). If just lost, shifted the other way.
3. **Title holder override:** A `champion` always gets a LONG legacy phrase — the belt is the story.
4. **Rookie vs veteran career arc:** First 5 fights = LONG (the story is being written); 30+ fights = SHORT (the story is known).

### 4.11 Recommendation summary table

| Module | Current variants/label | Proposed short variants | Proposed long variants | Total new variants |
|---|---|---|---|---|
| context_engine (momentum, 5 labels) | 8 (ext) / 3 (orig) | 12-15 per label = ~65 | 8-10 per label = ~45 | ~110 |
| context_engine (pressure, 4 labels) | 8 (ext) / 3 (orig) | 12-15 per label = ~54 | 8-10 per label = ~36 | ~90 |
| context_engine (trajectory, 5 labels) | 8 (ext) / 3 (orig) | 12 per label = 60 | 8 per label = 40 | ~100 |
| career_phase_engine (6 labels) | 8 (ext) / 3 (orig) | 12-15 per label = ~78 | 8-10 per label = ~54 | ~132 |
| narrative_families (4 labels) | 3 only | 12 per label = 48 | 8 per label = 32 | ~80 |
| legacy_engine (4 labels) | 3 only | 15-20 per label = ~70 | 8-10 per label = ~36 | ~106 |
| headline_engine (4 types × 4 families) | 1 each | 8 headlines per family = 128 | 8 bodies per family = 128 | ~256 |
| voice.py (25 attrs × 7 tiers) | 2-3 | 5-10 per tier (varies) | n/a (already long enough) | ~700 |
| voice.py (20 traits × 7 tiers) | 2-3 | 5-8 per tier | n/a | ~500 |
| **TOTAL new variants to author** | | | | **~2,074** |

**Realistic phasing:** Don't author all 2,074 at once. Phase the work:
- **Phase 1 (highest impact, lowest effort):** narrative_families + legacy_engine + headline_engine get `_EXT` versions matching the context_engine/career_phase_engine pattern. ~440 new variants. Forces a cache rebuild via ENGINE_VERSION bump.
- **Phase 2 (medium effort):** Add SHORT vs LONG variant split for the 5 highest-impact columns (momentum, pressure, career_phase, narrative_family, legacy_state). ~440 new variants.
- **Phase 3 (largest effort):** Expand voice.py attribute + personality descriptors from 2-3 to 5-10 per tier. ~1,200 new variants.
- **Phase 4 (refinement):** Add conditional triggers (career phase override, recent fight override, title holder override). Code-only change.

---

## 5. CAGE EMPIRE Voice Style Guide

The Soul doc gives us 3 reference phrases:
1. `"That kid I found in Mexico. Nobody wanted him. He became a champion."`
2. `"His best years may be behind him."`
3. `"the wunderkind everyone's talking about"`

**Voice characteristics extracted:**
- **First-person promoter voice** ("That kid I found in Mexico") — the manager/promoter speaking about his discovery. This is the "backroom" register.
- **Elegiac, uncertain phrasing** ("may be behind him") — the journalist's hedged assessment. Not declarative — suggestive.
- **Hype-building nouns** ("the wunderkind") — the HBO 24/7 narrator naming a thing before the audience knows it.
- **Short, fragmentary sentences** — staccato, not flowing. "Nobody wanted him." Period. "He became a champion." Period.
- **No sports clichés** — never "ballgame", never "ringer", never "dark horse" (the spec mentions "dark_horse" as a future narrative family, but the PHRASE shouldn't read like a handicap racing term).

**Per-module style guide examples (3-5 phrases per module in the target voice):**

### 5.1 context_engine (momentum) — target voice

- `very_high` SHORT: `"the kind of run that turns a name into a legend"`
- `very_high` LONG: `"Five straight wins, each one more emphatic than the last. The champion watches every minute of tape. The matchmakers are running out of opponents who'll take the fight."`
- `stable` SHORT: `"the division knows what he is by now"`
- `collapsing` SHORT: `"one more loss from a real conversation"`
- `collapsing` LONG: `"The bottom dropped out and it dropped fast. The roster's whispering. The matchmakers are running out of reasons to book him. One more loss and the conversation isn't about a comeback — it's about an exit."`

### 5.2 career_phase_engine — target voice

- `prospect` LONG: `"The kid nobody wanted. Two years later, the division's paying attention. The hype's real and the timetable's accelerating."`
- `champion` LONG: `"The man with the belt and the target on his back. Every contender in the division is studying his tape. Every challenger believes this is the night. That's the cost of the throne."`
- `veteran` LONG: `"Still here after a generation of fighters cycled through. He's seen the contenders come and go — most of them ended up where he started. The division respects him. The prospects fear him."`
- `declining` LONG: `"His best years may be behind him. The version of him the division remembers is gone. What's left is still a fighter — but a different one, fighting a different fight."`

### 5.3 narrative_families — target voice

- `prodigy` LONG: `"The wunderkind everyone's talking about. The scouts whisper when his name comes up. The matchmakers are saving him for the right night. The champion is taking notes — and so is everyone else."`
- `fallen_champion` LONG: `"Once the king of the division. Now searching for the version of himself that wore the belt. The crown is fading; the contender queue has moved on; the comeback is the only story left."`
- `cinderella_story` LONG: `"Nobody saw this coming. Two years ago he was an afterthought. Now he's the most improbable contender in the division — and the Cinderella story is starting to feel less like a fairy tale and more like a thesis."`

### 5.4 legacy_engine — target voice

- `building` LONG: `"Too early to judge the legacy. The first chapters are written — promising ones — but the book is long and the ending isn't in sight. The jury's out. The next fight is the next page."`
- `established` LONG: `"A body of work that speaks for itself. Not a Hall of Fame career — not yet — but a real one. The kind of fighter the division will remember when he's gone, even if the casual fans won't."`
- `legendary` LONG: `"A career for the history books. The kind of run that defines a division for a generation. When the story of this era is written, his name is in the first paragraph."`
- `forgotten` LONG: `"A career that time forgot. He fought, he lost more than he won, he retired without a mark. The division moved on. The roster cycled. His name is somewhere in the records, but not anywhere anyone talks about."`

### 5.5 headline_engine — target voice

- `top_story` + `prodigy` headline: `"The Kid Nobody Wanted Is Now the Kid Nobody Can Beat"`
- `top_story` + `prodigy` body: `"{name} was an afterthought two years ago. Now he's the prospect the entire division is measuring itself against — and coming up short. The champion is watching tape. The matchmakers are running out of reasons to delay the title shot."`
- `fastest_rising` headline (alt): `"{name} Is Coming for the Division"`
- `fastest_rising` body (alt): `"The hottest hand in the sport right now. {name} is winning fights he wasn't supposed to win, the way future champions win them, on a timetable nobody expected. The contender queue is shortening — and he's at the front of it."`

### 5.6 memory_engine — target voice

- `_search_previous_fight` (alt template): `"They've got history. Last time these two met, {focal} walked out with a {result} — and the division hasn't forgotten."`
- `_search_former_teammate` (alt template): `"They used to share a gym. They used to be on the same side. Tonight, they're not."`
- `_search_injury_history` (alt template): `"{name} is fighting through it — a {body_area} injury that hasn't fully healed. The camp says he's ready. The injury has its own opinion."`

### 5.7 voice.py describe_overall — target voice

The current template (`"{name} is a {archetype} with {attr1} and {attr2}, riding a {N}-fight win streak, currently {career_stage}."`) is too templated. Propose 4 structural variants:

1. **The discovery frame:** `"{name} — {archetype}, {attr1}, {attr2}. {streak_phrase}. {career_stage_phrase}."` (current)
2. **The promoter frame:** `"The {career_stage_phrase} with {attr1} and {attr2}. {streak_phrase}. {name} is the fighter the division is talking about — for now."`
3. **The journalist frame:** `"{name} is {archetype}. {attr1}. {attr2}. {streak_phrase}. {career_stage_phrase}. The book on him is still being written."`
4. **The scout's frame:** `"{archetype} with {attr1} and {attr2}. {streak_phrase}. {career_stage_phrase}. {name} is the kind of fighter you build a card around — or build a card to avoid."`

---

## 6. Implementation Recommendations

### 6.1 Should phrase banks move from Python lists to a DB table?

**Yes, for the high-churn banks. No, for the low-churn banks.**

**Move to DB (high churn — phrases that change frequently based on playtesting feedback):**
- All interpretation layer phrase banks (momentum, pressure, trajectory, career_phase, narrative_family, legacy_state, headlines)
- These are content that the user (or a future content editor) will want to tune without code changes

**Keep in Python (low churn — structural / mechanical):**
- `voice.TIERS` (the 7 band thresholds — these are MECHANICS, not content)
- `voice._NUM_WORDS` (number → word mapping)
- `voice._ARCHETYPE_NOUN` (style archetype → noun phrase)
- `memory_engine._YEAR_WORDS` (year gap → word)
- `memory_engine._RESULT_TYPE_PHRASES` (result_type → noun)
- These are translation tables, not creative content

**Proposed schema:**

```sql
CREATE TABLE interpretation_phrases (
    phrase_id INTEGER PRIMARY KEY,
    engine TEXT NOT NULL,          -- 'context_engine', 'career_phase_engine', etc.
    column_name TEXT NOT NULL,     -- 'momentum', 'pressure', 'career_phase', etc.
    label TEXT NOT NULL,           -- 'stable', 'very_high', 'rising_contender', etc.
    length TEXT NOT NULL,          -- 'short' | 'long' | 'medium'
    phrase_text TEXT NOT NULL,     -- the actual phrase
    weight INTEGER DEFAULT 1,      -- for weighted random selection (default 1)
    is_active INTEGER DEFAULT 1,   -- soft delete / A-B test toggle
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (engine) REFERENCES interpretation_engines(engine)
);

CREATE UNIQUE INDEX idx_interp_phrases_unique
    ON interpretation_phrases(engine, column_name, label, length, phrase_text);
CREATE INDEX idx_interp_phrases_lookup
    ON interpretation_phrases(engine, column_name, label, length, is_active);
```

**Benefits:**
- Content editors can add variants via SQL without touching Python
- A/B testing: set `weight=0` to disable a phrase without deleting it
- The `is_active` flag enables soft deletion + rollback
- The Python `MOMENTUM_PHRASES_EXT` dict becomes a thin loader: `SELECT phrase_text FROM interpretation_phrases WHERE engine='context_engine' AND column_name='momentum' AND label=? AND length=? AND is_active=1`

**Cost:**
- One new table, ~2,000 rows after full population
- Migration: write a Python script that reads the existing Python phrase banks and INSERTs them into the new table (one-time backfill, idempotent via the UNIQUE index)

### 6.2 Should the daily interpretation pass write BOTH a short + long variant?

**Yes — but as two SEPARATE columns, not as a "short||long" composite.**

The current `"label||phrase"` format works for ONE phrase per column. To support short + long, add parallel columns:

```sql
ALTER TABLE fighter_descriptors ADD COLUMN momentum_short TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN momentum_long TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN pressure_short TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN pressure_long TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN career_phase_short TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN career_phase_long TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN narrative_family_short TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN narrative_family_long TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN legacy_state_short TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN legacy_state_long TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN trajectory_short TEXT;
ALTER TABLE fighter_descriptors ADD COLUMN trajectory_long TEXT;
```

The existing `momentum`, `pressure`, `career_phase`, `narrative_family`, `legacy_state` columns (which currently store `"label||phrase"`) are kept for backward compatibility — they continue to hold the LONG phrase (the most-used variant). The new `*_short` columns hold the SHORT phrase for table cells.

**Format for the new columns:** `"label||phrase"` — same as existing, so the existing `decode_label` / `decode_phrase` helpers work without modification.

**Why two columns instead of a composite:**
- Simpler SQL queries (no SUBSTR/INSTR gymnastics to extract the short phrase)
- The short phrase is computed differently (different RNG seed, different bank) — keeping them separate prevents logic tangles
- Easier to migrate incrementally: populate `*_short` first, switch the Roster to read it, then populate `*_long`

### 6.3 Schema impact estimate

**New table:** `interpretation_phrases` (~2,000 rows after full population; ~10-byte per row + phrase text, ~200 KB total)

**New columns on `fighter_descriptors`:** 12 new TEXT columns (6 columns × 2 lengths). Each stores `"label||phrase"` (max ~200 chars per cell). 4,450 rows × 12 cols × 200 chars = ~10 MB additional cache storage. Acceptable.

**ENGINE_VERSION bump:** `"1.5.0"` → `"2.0.0"` (major — forces full cache rebuild on next daily pass)

**Migration approach:**
1. **Add the new table + columns** (idempotent — `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` wrapped in try/except for re-runs)
2. **Backfill `interpretation_phrases`** from the Python phrase banks (one-time script, idempotent via UNIQUE index)
3. **Bump `ENGINE_VERSION`** to `"2.0.0"` — this triggers the version-mismatch logic in `snapshot_cache.run_daily_interpretation_pass` which forces a full cache rebuild on the next Advance Day
4. **Update the engine write paths** to populate both `*_short` and `*_long` columns (parallel to the existing `momentum` / `pressure` writes)
5. **Update the UI readers** (Roster, Free Agents) to read `*_short` columns; Fighter Profile to read `*_long` columns
6. **Keep the old single-phrase columns** as a fallback (set them to the long phrase) so any un-updated UI readers continue to work

**Idempotency:** All schema changes use `IF NOT EXISTS` / try-except. The ENGINE_VERSION bump is the only non-idempotent step — once bumped, it can't be "un-bumped" (the meta row stores the new version). Re-running the migration is safe.

**Rollback:** If the migration breaks something, the old single-phrase columns still hold valid data. Set `ENGINE_VERSION` back to `"1.5.0"` (manually update `interpretation_cache_meta`), and the daily pass will skip the rebuild. The new columns stay NULL; the UI readers that haven't been updated fall back to the old columns.

### 6.4 Variety selection algorithm (recap from §4.1)

The proposed algorithm replaces the current `rng = random.Random(fighter_id * 31 + 17)` with:

1. **Per-fighter-per-week deterministic hash** (MD5 of `fighter_id|label|tick_bucket`) — same fighter, same week, same phrase. Next week, different phrase (if the bank has > 1 variant).
2. **Screen-context-aware bank selection** — table cells get short bank, profile gets long bank.
3. **No-repeat-within-N cache** — per-screen-render in-memory cache that tracks the last N=3 phrases shown, advances to the next variant if the picked phrase is in the cache.
4. **Conditional overrides** — career phase, recent fight outcome, title holder status can override the default bank selection (e.g., a champion always gets the LONG legacy phrase).

**Implementation cost:** ~150 lines of Python (one new `interpretation/phrase_picker.py` module) + updates to each engine's bulk-load path + updates to each UI reader. ~2-3 days of dev work.

### 6.5 ENGINE_VERSION bump is the critical fix

**The single highest-impact, lowest-effort fix:** Bump `snapshot_cache.ENGINE_VERSION` from `"1.5.0"` to `"1.6.0"` (or `"2.0.0"` if combined with the schema migration). This forces a full cache rebuild on the next Advance Day, which will:
- Repopulate `momentum`, `pressure`, `career_phase` with the 8-variant `_EXT` picker output (instead of the current 3-variant original picker output)
- Immediately cut the perceived repetition by ~60% (from 3 variants to 8 variants for the heaviest buckets)

**This fix alone won't solve the problem** (8 variants × 4,376 stable fighters = ~547 per phrase, still very repetitive), but it's the necessary first step before any of the more elaborate variety work lands.

### 6.6 Implementation priority order

| Priority | Change | Effort | Impact |
|---|---|---|---|
| **P0** | Bump `ENGINE_VERSION` to `"1.6.0"` to force rebuild with existing `_EXT` pickers | 1 line of code | Cuts perceived repetition ~60% for momentum/pressure/career_phase |
| **P0** | Add `_EXT` versions for `narrative_families` + `legacy_engine` (matching the context_engine pattern) | ~200 lines | Brings those 2 modules up to 8 variants |
| **P1** | Add SHORT vs LONG variant split + per-screen picker | ~500 lines + ~440 new phrases | Eliminates Roster "every row reads the same" problem; gives Profile depth |
| **P1** | Expand `headline_engine` from 1 to 8 variants per (type, family) | ~300 lines + ~256 new phrases | Eliminates "30 days of identical headlines" |
| **P2** | Move phrase banks to `interpretation_phrases` DB table | ~400 lines + migration script | Content editors can tune without code changes |
| **P2** | Expand `voice.py` attribute descriptors from 2-3 to 5-10 per tier | ~1,200 new phrases | Cuts attribute descriptor repetition ~60% |
| **P3** | Add conditional triggers (career phase, recent fight, title holder) | ~200 lines | Layered voice — champion reads differently from prospect |
| **P3** | Add 4-structural-variant `describe_overall` template | ~100 lines | Varies the overall sentence structure, not just the words |
| **P3** | Add more narrative_family archetypes (D2 lists 10 candidates) | ~500 lines + phrases | Cuts the 99.3% NULL rate to ~50% NULL |

---

## Appendix A — SQL Queries Used

All queries were executed read-only against `data/cage_empire.db`.

```sql
-- Schema
PRAGMA table_info(fighter_descriptors);

-- Counts
SELECT COUNT(*) AS total,
       COUNT(momentum) AS mom_set,
       COUNT(career_phase) AS cp_set,
       COUNT(narrative_family) AS fam_set,
       COUNT(legacy_state) AS leg_set,
       COUNT(pressure) AS pres_set
FROM fighter_descriptors;

-- Top 20 phrases per column (replace {col})
SELECT
  SUBSTR({col}, INSTR({col}, '||') + 2) AS phrase,
  COUNT(*) AS n
FROM fighter_descriptors
WHERE {col} IS NOT NULL
GROUP BY phrase
ORDER BY n DESC
LIMIT 20;

-- Label distribution (replace {col})
SELECT
  CASE
    WHEN {col} IS NULL THEN '(NULL)'
    WHEN INSTR({col}, '||') = 0 THEN '(no ||)'
    ELSE SUBSTR({col}, 1, INSTR({col}, '||') - 1)
  END AS label,
  COUNT(*) AS n
FROM fighter_descriptors
GROUP BY label
ORDER BY n DESC;

-- Distinct phrase count per column
SELECT COUNT(DISTINCT SUBSTR({col}, INSTR({col}, '||') + 2))
FROM fighter_descriptors WHERE {col} IS NOT NULL;

-- Cache meta
SELECT * FROM interpretation_cache_meta;

-- Daily headlines
SELECT headline_type, COUNT(*) FROM daily_headlines GROUP BY headline_type;
SELECT headline_date, headline_type, headline_text
FROM daily_headlines
ORDER BY headline_date DESC, headline_type LIMIT 20;

-- Random sample of 5 fighters
SELECT fighter_id, momentum FROM fighter_descriptors
WHERE momentum IS NOT NULL ORDER BY RANDOM() LIMIT 5;
```

## Appendix B — Files Inventoried

| File | Lines | Purpose |
|---|---|---|
| `src/interpretation/__init__.py` | 218 | Engine registry + event-bus subscribers |
| `src/interpretation/context_engine.py` | 1,062 | Momentum + pressure + trajectory |
| `src/interpretation/career_phase_engine.py` | 694 | Career phase (6 labels) |
| `src/interpretation/narrative_families.py` | 577 | Narrative family (4 labels) |
| `src/interpretation/legacy_engine.py` | 498 | Legacy state (4 labels) |
| `src/interpretation/memory_engine.py` | 691 | Memory surfacing (4 search types) |
| `src/interpretation/headline_engine.py` | 570 | 4 daily headlines |
| `src/interpretation/snapshot_cache.py` | 418 | Daily pass orchestrator |
| `src/voice.py` | 905 | Attribute + personality descriptors |
| `src/ui/voice_display.py` | 204 | Title-case display helpers |
| **TOTAL** | **5,829** | |

## Appendix C — Acceptance Test Constraint Note

The reason `MOMENTUM_PHRASES_EXT` (and similar `_EXT` banks) exist as PARALLEL dicts rather than replacing the originals is documented in `context_engine.py` lines 195-200:

```
CONSTRAINT: the acceptance tests (test_context_engine.py Case D)
verify `len(MOMENTUM_PHRASES[label]) == 3` (and same for pressure
+ trajectory) exactly. We CANNOT modify the acceptance tests.
```

This constraint means the short/long variety expansion proposed in this audit should follow the SAME `_EXT` parallel-dict pattern (e.g., `MOMENTUM_PHRASES_SHORT` + `MOMENTUM_PHRASES_LONG`) to avoid breaking the existing acceptance tests. The `_EXT` pattern is the proven way to expand variant count without touching the test-verified original banks.

If, however, the team decides to migrate to the `interpretation_phrases` DB table (§6.1), the constraint becomes moot — the Python `MOMENTUM_PHRASES` dict can stay at 3 entries (tests pass), and the DB table holds the full 12-short + 8-long variant set. The pickers would query the DB at module-load time (cached in module-level variables after first call).

---

**End of audit.**
