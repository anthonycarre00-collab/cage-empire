# CAGE EMPIRE — Fight Engine Analysis + DB Reseed Plan (v2 — revised)

**Date:** 2026-08-15
**Status:** PLANNING ONLY — no code changes
**Goal:** Reseed the default world DB with realistic, believable fighter data + staff. One-off task to create the best possible starting world.

---

## Point-by-point response to ALL user comments

### 1. Keep 4000 fighters — big free agent pool
**AGREED.** We keep all 4000 fighters from Claude's CSV. Roster distribution:
- P1 (Alpha Combat, major): 70 fighters — manageable, fun
- P2-P4 (mid promos): 50 each = 150 total
- P5-P10 (small promos): 30 each = 180 total
- **Free agents: ~3600** — massive scouting pool, filterable by weight class
- Total: 400 signed + 3600 free agents = 4000

The calculated allocations (Claude's 7-tier pyramid, attribute distributions, etc.) are calibrated for 4000 fighters. Reducing to 1000 would break the distribution.

### 2. Unique bios for all 4000 fighters
**Claude's CSV already has 4000 unique bios** (verified: 4000/4000 unique strings, avg 497 chars). They're template-generated but factually grounded in each fighter's actual stats, tier, archetype, record, and top skills. Claude's README is honest: "read enough back to back and you'll recognize the sentence skeletons repeating... Fine for seed data a player won't binge-read start to end."

**Assessment:** Claude's bios are GOOD ENOUGH for the initial seed. They're better than the current bios (which are truncated at 208 chars and factually disconnected from stats). The bios reference each fighter's actual attributes, career tier, mental archetype, and suggested record.

**Plan:** Use Claude's bios directly. For the 72 Elite + 106 Contender fighters (the ones players will actually read), consider hand-touching their bios later as a polish task. But for the initial seed, Claude's bios are sufficient.

### 3. Physicals must NOT change
**AGREED.** The following fields are preserved from the current DB (not overwritten by Claude's CSV):
- `weight_class_id` — current DB assignment (13 weight classes)
- `height_cm` — current DB value
- `birth_nation_id` / `residence_nation_id` — current DB values
- `gender` — current DB value
- `date_of_birth` — current DB value (Claude's CSV has `age` but we don't overwrite DOB)

Claude's CSV has `weight_class` (text) + `height_cm` + `nation` + `gender` — these are provided for REFERENCE and to validate the mapping, but we do NOT overwrite the existing DB values. We only overwrite: attributes, personality, potential, records, bio, nickname.

**Exception:** Claude's CSV does include `nation` and `weight_class` — we use these for VALIDATION (verify the CSV matches the DB). If there's a mismatch, the DB wins (physicals are preserved).

### 4. Nicknames — repeats are TERRIBLE, need fixing
**CONFIRMED PROBLEM.** Both the current DB and Claude's CSV have severe nickname repetition:

| Source | Total | Unique | Repeats | Most repeated |
|---|---|---|---|---|
| Current DB | 2,692 | 810 | 1,882 (70%) | "Scrap" (29×), "Smash" (28×) |
| Claude's CSV | 4,000 | 470 | 3,530 (88%) | "The Finisher" (58×), "Grinder" (57×) |

Claude claims "470 unique nicknames across 4,000 fighters (some repetition is realistic)" — but 88% repetition is NOT realistic. Real MMA has maybe 10-15% nickname repetition.

**Plan:** Generate new nicknames for ALL 4000 fighters using a better system:
- Pull from the fighter's actual top attributes (80+ = elite descriptor)
- Pull from their mental archetype (Bottler = "The Choker", Grinder = "The Engine")
- Pull from their career tier (Elite = champion-tier words, Fringe = underdog words)
- Pull from their fighting style (Wrestler = grappling words, Brawler = power words)
- Use a LARGER word bank (Claude's was too small)
- Ensure <10% repetition across 4000 fighters (target: 3600+ unique nicknames)
- Some repetition is OK for generic nicknames ("The Hammer", "Pitbull") but not 58× for "The Finisher"

This is a **generation task** — we write a script that reads each fighter's attributes/tier/style and produces a unique-ish nickname. No hand-authoring 4000 nicknames.

### 5. Backstory + fight records — grey name opponents
**CONFIRMED: 4000 fighters is NOT a big enough pond for believable 20-fight histories.**

Claude's CSV suggests avg 20 fights per fighter = 80,000 total fights. If all opponents were DB fighters:
- 80,000 fights × 2 fight_history rows = 160,000 rows
- Many would be unrealistic (Fringe fighter vs Elite, mismatched weight classes)
- The DB would be bloated with meaningless matchup data

**Plan: Grey name opponents.** For each fighter's fight_history:
- **~30% of fights** are against other DB fighters (same weight class, similar tier — these create real rivalries + shared history)
- **~70% of fights** are against grey name opponents (not in the DB — just a name + result for record purposes)

**How grey names work (no schema change needed):**
- Grey name opponents are created as `fighters` rows with `is_active=0, is_retired=1`
- They have a name, weight_class_id, and nothing else (no attributes, no personality, no career)
- They exist ONLY so `fight_history.opponent_id` can reference them
- They never appear in roster screens, free agent lists, or matchmaking
- They're filtered out by `WHERE is_active=1 AND is_retired=0` everywhere
- Example: "Marcus Reed beat unknown_local_fighter_42 by KO in round 1 at a regional show in 2023"

**Fight history generation rules:**
- Fighter's win/loss/draw counts match Claude's `suggested_wins/losses/draws`
- Result types weighted by realistic distribution (KO 35%, sub 20%, decision 45%)
- Fight dates spread between the fighter's debut age and current age
- ~30% of DB-vs-DB matchups are against fighters in the same promotion tier
- Title fights (is_title=1) only for Elite/Contender fighters, ~2-3 per career
- Grey name opponents get realistic names from the name pool (same nation as the fighter)

### 6. UI replay options — remove
**CHECKED: 0 references to "replay" found in `src/web/js/`.** The web UI does not have a replay feature. The current fight record display shows:
- Result (W/L/D)
- Opponent name
- Result type (KO, submission, decision)
- Event name + date
- Finish round + time

This is exactly what you want — results only, no replay. The "replay" concept may have existed in the legacy Tkinter UI but is not in the web UI.

**Plan:** No changes needed. Verify after reseed that fight_history display shows only results (not beat-by-beat replay).

### 7. Populate more staff
**CONFIRMED: Staff is understaffed.** Current state:

| Role | Current | Needed | Gap |
|---|---|---|---|
| coach | 300 | 300 (gym-based, OK) | 0 |
| commentator | 25 | 20 (2 per promo) | -5 (oversupplied, fine) |
| scout | 20 | 30 (3 per promo) | +10 needed |
| general_manager | 10 | 10 (1 per promo) | 0 |
| doctor | 10 | 10 (1 per promo) | 0 |
| cutman | 10 | 20 (2 per promo) | +10 needed |
| **matchmaker** | **0** | **10** (1 per promo) | **+10 needed** |

**Plan:** Generate additional staff:
- 10 matchmakers (1 per promotion) — this role is MISSING entirely
- 10 more scouts (total 30, 3 per promo)
- 10 more cutmen (total 20, 2 per promo)
- Keep the 300 coaches (gym-based, not promo-based — correct per W10/W11)
- Total new staff: 30

Staff generation:
- Realistic names from the name pool
- Nation matching the promotion's region
- `skill_level` appropriate to promotion tier (major promos get better staff)
- `salary_ask` + `contract_length_ask` proportional to skill

### 8. Other missing info?

**Identified gaps:**

a) **Gyms need more fighters assigned.** Currently 300 gyms but many fighters have `current_gym_id=NULL`. Claude's CSV has `camp` for 2,350 of 4,000 fighters. Need to map camp names to gym_ids + create new gyms for unmatched camps.

b) **Rankings need regeneration.** Current rankings are at 1000.0 (seed default). After backfilling fight_history, recompute ELO from actual fight results. This gives realistic rankings where Elite fighters are #1-5, Contenders are #6-15, Gatekeepers are #16-30, etc.

c) **Titles need reseeding.** Currently 111 titles, 13 vacant. After regenerating rankings, assign the top-rated fighter in each promotion × weight class as champion. This gives 10 promos × ~13 weight classes = ~130 titles (some may be vacant if a promo doesn't have fighters in that WC).

d) **Rivalries need reseeding.** Currently 93 rivalries. After backfilling fight_history, find fighters who've fought 2+ times + create rivalry rows. Target: ~300-400 rivalries (enough for the world to feel alive but not cluttered).

e) **Style archetypes need mapping.** Claude's CSV has `style` (Brawler, Wrestler, Striker, etc.) but DB uses `fight_style_archetype_id` (FK). Need to map style name → archetype_id. DB has 7 archetypes; verify Claude's styles match.

f) **Personality archetypes need mapping.** Claude's CSV has `personality_tag` (Calm, Aggressive, etc.) but DB uses `personality_archetype_id` (FK). DB has 5 archetypes; verify Claude's tags match.

g) **`date_of_birth` calculation.** Claude's CSV has `age` (integer). Need to compute DOB from `GAME_START_DATE` (2026-01-01) minus age years, with a random month/day for birthday spread. Do NOT overwrite existing DOB — only set for fighters missing one.

h) **Finance transactions.** Current DB has only 10. After reseed, each promotion should start with a realistic cash balance based on their tier:
  - Major (P1): $50M
  - Mid (P2-P4): $10M each
  - Small (P5-P10): $2M each
  Write opening-balance finance_transactions rows.

---

## Revised Plan (v2)

### Approach: Incremental reseed, no schema changes, 4000 fighters

**Zero new columns. Zero migrations.** The reseed only updates existing columns with better data.

### Step 1: Backup + prepare
- Backup: `cp data/cage_empire.db data/cage_empire.db.bak.pre-reseed`
- Copy Claude's CSV to `data/fighter_seed_rebuild.csv`
- No migration needed (schema stays at v3.36.0)

### Step 2: Generate better nicknames
Write `scripts/generate_nicknames.py`:
- Read each fighter's top 3 attributes, career tier, mental archetype, style
- Use a LARGE word bank (adjective + noun combinatorial, 50+ adjectives × 50+ nouns = 2500+ combinations)
- Ensure <10% repetition across 4000 fighters
- Some fighters get no nickname (realistic — not every fighter has one)
- Output: nickname for each fighter_id

### Step 3: Load Claude's CSV + update fighters
Write `scripts/reseed_fighters_from_csv.py`:
- Read the CSV (4000 rows)
- For each fighter (fighter_id 1-4000):
  - **DO NOT OVERWRITE:** `weight_class_id`, `height_cm`, `birth_nation_id`, `residence_nation_id`, `gender`, `date_of_birth`, `first_name`, `last_name` (physicals preserved)
  - **OVERWRITE:** `nickname` (from Step 2), `fight_style_archetype_id` (mapped from CSV `style`), `personality_archetype_id` (mapped from CSV `personality_tag`), `current_promotion_id` (from CSV `promotion_id` mapped to DB IDs), `current_gym_id` (from CSV `camp` mapped to gym_ids)
  - **OVERWRITE in fighter_attributes:** all 26 skill columns (from CSV)
  - **OVERWRITE in fighter_personality:** all 20 personality columns (from CSV, strip `personality_` prefix)
  - **OVERWRITE in fighter_career:** `potential` (from CSV), `record_wins/losses/draws` (from CSV `suggested_wins/losses/draws`), `win_streak`/`loss_streak` (computed from record), `career_health` (100 for active, lower for DecliningVet)
  - **OVERWRITE in fighter_bios:** `bio_text` (from CSV `bio`)
  - **DO NOT STORE:** `career_tier`, `mental_archetype`, `mental_score`, `overall_current` (seed-time tools only)

### Step 4: Generate grey name opponents
Write `scripts/generate_grey_name_fighters.py`:
- Generate ~2000 grey name fighters (enough for 70% of 80,000 fights)
- Each gets: fighter_id (4001+), first_name, last_name, weight_class_id, is_active=0, is_retired=1, date_of_birth (random, age 25-45)
- Names from the existing name pool, matched to the fighter's nation
- No attributes, no personality, no career, no bio — they exist for record purposes only

### Step 5: Backfill fight_history
Write `scripts/backfill_fight_history.py`:
- For each of the 4000 real fighters with `suggested_total_fights > 0`:
  - Generate `suggested_wins` + `suggested_losses` + `suggested_draws` fight_history rows
  - ~30% of opponents are DB fighters (same weight class, similar tier)
  - ~70% of opponents are grey name fighters (random from same weight class)
  - Result types weighted: KO 35%, sub 20%, decision 40%, draw 3%, DQ 1%, NC 1%
  - Fight dates spread between fighter's debut age and current age
  - Title fights (~2-3 per Elite/Contender career) marked with `title_at_stake=1`
- Total: ~80,000 fight_history rows (2 per fight × 40,000 fights)

### Step 6: Regenerate rankings
Write `scripts/regenerate_rankings.py`:
- For each weight_class × promotion:
  - Compute ELO from fight_history (win=+32, loss=-32, draw=0, adjusted by opponent rating)
  - Write to `rankings` table
  - Sort by rating for ranking order

### Step 7: Reseed titles
Write `scripts/reseed_titles.py`:
- For each promotion × weight_class where the promo has ≥2 fighters:
  - Find the top-rated fighter (from regenerated rankings)
  - Assign as current champion
  - Write to `titles` table
- Promotions with <2 fighters in a weight class: title remains vacant

### Step 8: Reseed rivalries
Write `scripts/reseed_rivalries.py`:
- Find all fighter pairs who've fought 2+ times (from backfilled fight_history)
- Create rivalry rows:
  - `bad_blood` for pairs with a split decision or DQ
  - `title_rivalry` for pairs who fought for a title
  - `rematch_hungry` for pairs with a 1-1 record
  - `callout` for pairs where one called out the other (rare, ~5%)
- Target: ~300-400 rivalries

### Step 9: Populate more staff
Write `scripts/populate_staff.py`:
- Generate 10 matchmakers (1 per promo, MISSING role)
- Generate 10 more scouts (total 30)
- Generate 10 more cutmen (total 20)
- Each gets: name, nation (matching promo region), role_type, skill_level, salary_ask, contract_length_ask, promotion_id
- Assign to promotions (1 matchmaker per promo, 3 scouts per promo, 2 cutmen per promo)

### Step 10: Set promotion finances
Write `scripts/set_promotion_finances.py`:
- Set `current_cash` by tier:
  - Major (P1): $50,000,000
  - Mid (P2-P4): $10,000,000 each
  - Small (P5-P10): $2,000,000 each
- Write opening-balance `finance_transactions` rows (type='opening_balance')
- Set `financial_state='HEALTHY'` for all promos

### Step 11: Add roster caps (code change, not schema)
In `src/services/contracts.py` or `src/app_web.py`:
- Add constant: `ROSTER_CAPS = {'major': 100, 'mid': 80, 'small': 50}`
- Add check in `sign_free_agent`: refuse if at cap
- Add check in `rival_ai` signing logic: don't sign if at cap
- Add check in `cutting_agent`: consider cutting if over cap

### Step 12: Verify
1. `python3 scripts/invariant_checker.py` — 8/8 PASS
2. `python3 scripts/measure_fight_distribution.py` — check distribution with new data
3. `python3 scripts/soak_test.py 30` — verify world is coherent
4. Spot-check: read 10 fighter bios, verify they match their stats
5. Spot-check: read 10 fight_history rows, verify they're believable
6. Check nickname uniqueness: <10% repetition
7. Check roster sizes: P1 ≤70, P2-P4 ≤50, P5-P10 ≤30
8. Check grey names: is_active=0, is_retired=1, not in roster/free agent lists

---

## What we're NOT doing
- ❌ NO new columns (career_tier, mental_archetype, mental_score, overall_current are seed-time tools, not stored)
- ❌ NO schema migration (stays at v3.36.0)
- ❌ NO fight engine changes (the reseeded data will naturally produce better distributions)
- ❌ NO physicals changes (weight class, height, nation, gender preserved)
- ❌ NO wiping the DB (incremental update of existing columns)
- ❌ NO UI replay feature (doesn't exist in web UI)

## What we ARE doing
- ✅ Reseed 4000 fighters with Claude's attribute/personality/potential/record data
- ✅ Generate unique nicknames (better than Claude's 88% repetition)
- ✅ Generate grey name opponents for believable fight histories
- ✅ Backfill 80,000 fight_history rows (30% DB vs DB, 70% DB vs grey)
- ✅ Regenerate rankings, titles, rivalries from new data
- ✅ Populate 30 more staff (matchmakers + scouts + cutmen)
- ✅ Set realistic promotion finances
- ✅ Add roster caps (major=100, mid=80, small=50) — code constant, no schema change
- ✅ Preserve all physicals (weight class, height, nation, gender, DOB)
