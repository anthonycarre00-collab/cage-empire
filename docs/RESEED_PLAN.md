# CAGE EMPIRE — Fight Engine Analysis + DB Reseed Plan

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Goal:** Analyze fight engine + current DB data, evaluate Claude's reseed CSV, produce a unified plan

---

## Part 1: Fight Engine Analysis

### Current state
- **File:** `src/services/fight_engine.py` (4,953 lines)
- **Key functions:** `resolve_next_fight()` (line 3994), `resolve_round()` (line 1438), `_resolve_fight_simplified()` (added Tier 4 for AI vs AI)
- **Attribute references:** 222 references to fighter attributes throughout the engine
- **Two paths:** Full beat-by-beat resolution (player fights) + simplified resolution (AI vs AI fights, added Tier 4)

### Fight result distribution (current DB, 1,799 resolved fights)

| Result | Count | % | Target (UFC) | Gap |
|---|---|---|---|---|
| unanimous_decision | 701 | 39.0% | ~35% | +4pp (close) |
| ko_tko | 542 | 30.1% | ~35% | -5pp (slightly low) |
| submission | 263 | 14.6% | ~20% | -5pp (low) |
| split_decision | 151 | 8.4% | ~10% | -2pp (close) |
| doctor_stoppage | 59 | 3.3% | ~1% | +2pp (improved from 17%!) |
| draw | 52 | 2.9% | ~1% | +2pp |
| dq | 31 | 1.7% | ~0.5% | +1pp |

**Assessment:** The distribution is **plausible** — much better than the 17% doctor stoppage rate we measured earlier (the Tier 4 AI fight simplification helped by not generating per-beat damage that triggers doctor stoppages). KO rate is slightly low (30% vs 35%), sub rate is low (15% vs 20%), decision rate is slightly high (47% vs 45%). These gaps are **attribute-driven, not engine-driven** — the engine logic is sound, but the fighter attributes don't produce enough finishes.

### Fight engine findings

1. **The engine is structurally strong** — beat-by-beat resolution with momentum, fatigue, damage accumulation, finish thresholds, 10-point must scoring. The architecture matches GPT's W12 spec.

2. **The simplified AI resolver works** — produces ko_tko/submission/unanimous_decision/split_decision/draw with same result types as full engine. Doesn't produce doctor_stoppage/corner_stoppage/dq (requires per-beat tracking). Minor distribution shift for AI fights only — player path unchanged.

3. **The calibration gap is attribute-driven** — with the current near-Gaussian attribute distribution (avg ~54, no real tail), most fights are between evenly-matched fighters, producing more decisions and fewer finishes. Claude's pyramid distribution (most fighters 46-53, few elite at 80+) would create more mismatch fights → more finishes.

4. **No engine changes needed for reseed** — the engine reads attributes from `fighter_attributes` table. If we reseed with Claude's data, the engine will automatically produce different (likely better) distributions.

5. **Mental attributes ARE wired** — the engine reads `composure`, `focus`, `grit`, `clutch_factor` etc. for pressure modifiers in high-importance fights. Claude's `mental_archetype` (Bottler/Grinder/Winner) would affect outcomes IF we store `mental_score` and the engine reads it. Currently the engine reads individual personality traits, not a composite `mental_score`.

---

## Part 2: Current DB Data Analysis

### Critical problems confirmed

| Problem | Current state | Claude's fix | Impact |
|---|---|---|---|
| **94.8% of fighters have 0 fights** | 4,215 of 4,450 active fighters have 0 career fights | CSV provides `suggested_wins/losses/draws` for all 4,000 fighters (avg 20 fights each) | Fighters have no career history — no debuts, no records, no context |
| **Potential distribution is Gaussian** | 658 elite (80+), bell-shaped | 246 elite (80+), right-skewed pyramid | Too many elite fighters → no sense of scarcity |
| **Old fighters have HIGHER potential** | 40+ avg potential 65.5, under-30 avg 60.8 (backwards!) | 35+ with elite potential: 28 (all legitimately great veterans) | Defies MMA logic — old fighters should be declining |
| **No career tiers** | All fighters treated equally | 7 tiers: Elite (72), Contender (106), Prospect (218), Gatekeeper (2278), Unproven (569), DecliningVet (557), Fringe (200) | No narrative differentiation |
| **No mental archetype** | Personality traits exist but don't drive outcomes | 5 archetypes: Winner-clutch (91), Bottler (71), Grinder (696), Fragile (734), Steady (2408) | "Talented but chokes" stories impossible |
| **No overall_current** | Only `potential` exists (ceiling, not realized ability) | `overall_current` = day-one snapshot accounting for tier + mental | Can't distinguish "prospect with 50 current / 80 potential" from "gatekeeper with 50 current / 53 potential" |
| **Roster sizes tiny** | P1 has 60 fighters, P5-P10 have 18-21 each | P1 has 450, P2-P4 have ~350, P5-P9 have ~500 | Promotions can't book events (not enough fighters) |
| **Bios are generic** | Template-generated, truncated at 208 chars | Richer combinatorial, factually grounded in stats | Reading 40 in a row shows seams, but better than current |

### Data that would be LOST on reseed (if we wipe + rebuild)

| Table | Rows | Impact |
|---|---|---|
| events | 1,884 | All historical events gone |
| fights | 1,799 | All fight results gone |
| fight_history | 3,598 | All career records gone (but CSV has suggested records) |
| titles | 111 | All title history gone (need to reseed) |
| rivalries | 93 | All rivalries gone (need to reseed) |
| rankings | 669 | Rankings gone (can regenerate from new records) |
| injuries | 390 | Active injuries gone (acceptable — fresh start) |
| training_camps | 50 | Active camps gone (acceptable) |
| finance_transactions | 10 | Finance history gone (acceptable — fresh start) |

**Assessment:** The data loss is **acceptable** — most of the historical data is from pre-hardening-phase testing and doesn't reflect coherent world state. The CSV's `suggested_wins/losses` gives every fighter a career history, which is better than the current 94.8% with 0 fights.

---

## Part 3: Claude's CSV Evaluation

### What's good
1. **7-tier career classification** — pyramid distribution (57% Gatekeeper, 1.8% Elite) matches real-world MMA
2. **Mental archetype system** — Bottler (71), Grinder (696), Winner (91) create "talented but chokes" stories
3. **Suggested records** — avg 20 fights per fighter, with realistic variance
4. **Attribute shape preserved** — each fighter's original style-driven shape kept (Wrestler still has higher takedown offense)
5. **All 26 skills + 20 personality traits** — perfect column mapping to existing DB tables
6. **New bios** — factually grounded in stats, 4000 unique strings
7. **Promotion tier assignment** — pyramid (450/1050/2500) matches real-world MMA

### What's questionable
1. **Promotion IDs are placeholders (P1-P9)** — need mapping to actual DB promotion IDs (1-10). Claude says "swap in your actual promotion IDs" — we have 10 promos but Claude designed for 9. P10 (French Savate) would need fighters too.
2. **Weight class names may not match** — CSV uses "Welterweight", "Lightweight" etc. Need to verify these match DB `weight_classes.name` exactly.
3. **No style_archetype_id** — CSV has `style` (Brawler, Wrestler, etc.) but DB uses `fight_style_archetype_id` (FK to `style_archetypes` table). Need to map style name → archetype ID.
4. **No personality_archetype_id** — CSV has `personality_tag` (Calm, Aggressive, etc.) but DB uses `personality_archetype_id` (FK). Need to map tag → archetype ID.
5. **`mental_score` is compressed** — Claude warns: range 48.5-66.6, std 3.2. The categorical `mental_archetype` carries the narrative weight, not the raw number.
6. **No height_cm in CSV mapping** — wait, CSV has `height_cm` but does the DB `fighters` table have it? Yes, `height_cm` EXISTS in fighters table.
7. **`camp` column** — CSV has gym/camp names. Need to map to `gyms` table (300 gyms exist). Claude says 2,350 pulled from original bio, rest filled from same pool.

### What's missing
1. **No `date_of_birth`** — CSV has `age` but DB needs `date_of_birth` (YYYY-MM-DD). Need to compute from age + sim_date.
2. **No `nation_id` / `city_id`** — CSV has `nation` (text) but DB uses FKs to `nations` table. Need to map nation name → nation_id.
3. **No `weight_class_id`** — CSV has `weight_class` (text) but DB uses FK. Need to map WC name → weight_class_id.
4. **No gender-specific weight class handling** — DB has separate male/female WCs (e.g., Flyweight exists for both). CSV's `weight_class` + `gender` → need to find the right `weight_class_id`.

---

## Part 4: The Plan

### Approach: **Incremental reseed, not wipe-and-rebuild**

We do NOT wipe the DB and rebuild from scratch. Instead:
1. Add new columns (migration v3.37.0)
2. Update existing 4,000 fighters (fighter_id 1-4000) with Claude's data
3. Keep the extra 450 fighters (IDs 4001-4450) as regen-generated prospects
4. Regenerate rankings, titles, rivalries from the new records
5. Backfill fight_history from suggested records

### Step 1: Schema migration (v3.37.0)

Add 4 new columns to `fighter_career`:
```sql
ALTER TABLE fighter_career ADD COLUMN career_tier TEXT;
ALTER TABLE fighter_career ADD COLUMN mental_archetype TEXT;
ALTER TABLE fighter_career ADD COLUMN mental_score REAL;
ALTER TABLE fighter_career ADD COLUMN overall_current INTEGER;
```

Add `backstory_depth` + `narrative_hook` to `fighter_bios`:
```sql
ALTER TABLE fighter_bios ADD COLUMN backstory_depth TEXT;
ALTER TABLE fighter_bios ADD COLUMN narrative_hook TEXT;
```

Bump `CODE_SCHEMA_VERSION` to "3.37.0".

### Step 2: Load CSV + map to DB

Write `scripts/reseed_fighters_from_csv.py`:

1. **Read the CSV** (4,000 rows)
2. **Map columns:**
   - `fighter_id` → direct match (1-4000)
   - `name` → split into `first_name` + `last_name`
   - `nickname` → `fighters.nickname`
   - `age` → compute `date_of_birth` from `GAME_START_DATE` (2026-01-01) minus age years, random month/day
   - `gender` → `fighters.gender`
   - `nation` → map to `nations.nation_id` (lookup by name)
   - `weight_class` + `gender` → map to `weight_classes.weight_class_id` (lookup by name + gender)
   - `camp` → map to `gyms.gym_id` (lookup by name, create if missing)
   - `style` → map to `style_archetypes.style_archetype_id` (lookup by name)
   - `stance` → `fighters.stance`
   - `handedness` → `fighters.handedness`
   - `personality_tag` → map to `personality_archetypes.personality_archetype_id`
   - `promotion_id` (P1-P9) → map to actual DB promotion IDs (see mapping below)
   - 26 skill columns → `fighter_attributes` (direct column match)
   - 20 personality columns → `fighter_personality` (strip `personality_` prefix)
   - `overall_current` → `fighter_career.overall_current` (NEW column)
   - `potential` → `fighter_career.potential`
   - `mental_score` → `fighter_career.mental_score` (NEW)
   - `mental_archetype` → `fighter_career.mental_archetype` (NEW)
   - `career_tier` → `fighter_career.career_tier` (NEW)
   - `suggested_wins/losses/draws` → `fighter_career.record_wins/losses/draws`
   - `bio` → `fighter_bios.bio_text`
   - `backstory_depth` → `fighter_bios.backstory_depth` (NEW)
   - `narrative_hook` → `fighter_bios.narrative_hook` (NEW)
   - `height_cm` → `fighters.height_cm`
   - `ref_*` columns → IGNORE (reference only)

3. **Promotion mapping (P1-P9 → DB IDs 1-10):**
   - P1 (Tier1 Large) → promo 1 (Alpha Combat Federation, major) — 450 fighters
   - P2 (Tier2 Mid) → promo 2 (Rival Fight League, mid) — ~350
   - P3 (Tier2 Mid) → promo 3 (Pacific Rim Championship, mid) — ~350
   - P4 (Tier2 Mid) → promo 4 (European Fight Network, mid) — ~350
   - P5 (Tier3 Regional) → promo 5 (South American Warriors, small) — ~500
   - P6 (Tier3 Regional) → promo 6 (Mexican Boxing & Brawl, small) — ~500
   - P7 (Tier3 Regional) → promo 7 (Nordic Fight Nights, small) — ~500
   - P8 (Tier3 Regional) → promo 8 (Eastern Bloc Combat, small) — ~500
   - P9 (Tier3 Regional) → promo 9 (Australian Outback Fights, small) — ~500
   - P10 (French Savate, small) → assign remaining fighters proportionally

### Step 3: Backfill career history

Write `scripts/backfill_fight_history_from_csv.py`:

For each fighter with `suggested_total_fights > 0`:
1. Generate `suggested_wins` + `suggested_losses` + `suggested_draws` fight_history rows
2. Assign random opponents from the same weight class + promotion tier
3. Assign random dates (between fighter's debut age and current age)
4. Assign random result types weighted by the fight distribution targets
5. Write to `fight_history` table

This gives every fighter a career history that matches their suggested record.

### Step 4: Regenerate rankings

Write `scripts/regenerate_rankings.py`:

For each weight class × promotion:
1. Compute ELO rating from fight_history (win = +32, loss = -32, draw = 0, adjusted by opponent rating)
2. Write to `rankings` table
3. Sort by rating to produce ranking order

### Step 5: Reseed titles

Write `scripts/reseed_titles.py`:

For each promotion × weight class:
1. Find the top-rated fighter (from regenerated rankings)
2. Assign them as current champion
3. Write to `titles` table with `current_champion_fighter_id` + `champion_since_date`

### Step 6: Reseed rivalries

Write `scripts/reseed_rivalries.py`:

For each promotion:
1. Find fighters who have fought each other 2+ times (from backfilled fight_history)
2. Create rivalry rows with appropriate `rivalry_type` (bad_blood for split decisions, title_rivalry for title fights, rematch_hungry for 1-1 records)
3. Write to `rivalries` table

### Step 7: Update fight engine to read `overall_current` + `mental_archetype`

In `src/services/fight_engine.py`:
1. The engine already reads individual personality traits for pressure modifiers
2. Add: read `fighter_career.overall_current` as the baseline ability (instead of computing from attributes)
3. Add: read `fighter_career.mental_archetype` for outcome modifiers:
   - Bottler: -5% finish probability in high-importance fights (title fights, main events)
   - Grinder: +5% upset probability (wins more than attributes suggest)
   - Winner-clutch: +5% finish probability in high-importance fights
   - Fragile: -5% win probability when behind on the scorecards
   - Steady: no modifier

### Step 8: Verify + calibrate

1. Run `python3 scripts/measure_fight_distribution.py` on a 100-fight sample with the new data
2. Compare distribution to targets (KO 35%, sub 20%, decision 45%)
3. If still off, adjust the fight engine's finish thresholds (but NOT the fighter attributes — Claude's data is the source of truth)
4. Run `python3 scripts/soak_test.py 30` to verify the world is coherent
5. Run `python3 scripts/invariant_checker.py` to verify 8/8 PASS

---

## Part 5: Risk Assessment + Mitigation

### Risks

1. **Fighter ID mismatch** — CSV has fighter_id 1-4000, DB has 1-4450. The extra 450 (regen replacements) won't be in the CSV. **Mitigation:** Leave fighters 4001-4450 untouched (they're regen-generated, keep their existing data). Only update fighters 1-4000.

2. **Weight class name mismatch** — CSV may use slightly different names than DB. **Mitigation:** Write a name-normalization function (lowercase, strip spaces) for lookup.

3. **Nation name mismatch** — CSV has "Japan", DB might have "Japanese" or a different format. **Mitigation:** Fuzzy match or create missing nations.

4. **Gym/camp name mismatch** — CSV has 2,350+ camp names, DB has 300 gyms. **Mitigation:** Map CSV camp names to existing gyms by name. Create new gyms for unmatched camps (up to ~2000 new gyms).

5. **Fight history backfill creates impossible matchups** — random opponents might be from different weight classes or promotions. **Mitigation:** Constrain opponent selection to same weight class + same promotion tier band.

6. **Fight engine calibration shifts** — new attribute distribution will produce different fight outcomes. **Mitigation:** Measure first (W12), then calibrate engine thresholds if needed. Do NOT change fighter attributes — Claude's data is the source of truth.

### What we're NOT doing
- ❌ Wiping the DB (incremental update, not rebuild)
- ❌ Changing the fight engine architecture (just adding `overall_current` + `mental_archetype` reads)
- ❌ Tuning fighter attributes after reseed (Claude's data is the source of truth)
- ❌ Changing the schema beyond 6 new columns
- ❌ Touching the 450 regen-generated fighters (IDs 4001-4450)

### Backup plan
- Backup the DB before reseed: `cp data/cage_empire.db data/cage_empire.db.bak.pre-reseed`
- The reseed script is idempotent — can be re-run safely
- If anything breaks, restore from backup

---

## Part 6: Implementation Order

1. **Migration v3.37.0** — add 6 new columns
2. **`scripts/reseed_fighters_from_csv.py`** — load CSV, update 4000 fighters
3. **`scripts/backfill_fight_history_from_csv.py`** — generate career history from suggested records
4. **`scripts/regenerate_rankings.py`** — compute ELO from fight_history
5. **`scripts/reseed_titles.py`** — assign champions from rankings
6. **`scripts/reseed_rivalries.py`** — create rivalries from fight_history
7. **Fight engine update** — read `overall_current` + `mental_archetype`
8. **Verify** — measure fight distribution, run soak test, run invariants
9. **Commit + push**

Each step is independently testable + reversible. If any step fails, the DB is still in a usable state from the previous step.
