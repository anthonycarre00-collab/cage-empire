> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# Research: Fighter Generation + Rival AI Signing + Staff Lifecycle

**Task ID:** RESEARCH-FIGHTERGEN-RIVALAI-STAFFLIFE
**Agent:** Explore (read-only)
**Scope:** `src/fighter_gen.py`, `src/services/retirement_svc.py`, `src/services/rival_ai/signing_agent.py`, `src/services/rival_ai/archetypes.py`, `src/services/rival_ai/staff_manager.py`, plus `src/tick_processor.py`, `src/seed_data.py`, `scripts/seed_world_phase3.py`, `src/build_db.py` migration `v3_20_0_reseed_fighter_attributes`.
**Method:** Pure read — no edits, no DB writes. Direct DB introspection of `data/cage_empire.db` for live confirmation.

---

## A. Fighter Generation

### Current state

**`src/fighter_gen.py` (579 lines) — the pure generation primitives.**

Four pure-ish functions, deliberately side-effect-free (no DB writes — callers own the INSERT/UPDATE so the same primitives can be reused by seed backfill, regen, and future scouting reports):

1. **`generate_attribute_block(archetype_id, conn)`** → 25-attribute dict.
   - Formula (line 226): `value = clamp(50 + bias.get(col, 0) + random.randint(-8, 8), 0, 100)`
   - **Base value is 50** (NOT 37). The bias dict comes from `style_archetypes.attribute_bias` JSON column (max abs bias = 10, softened ~40-50% from the original ±20).
   - The ±8 noise floor keeps fighters within an archetype distinct.
   - Average produced per attribute ≈ **50** (no bias) to ~55 (with archetype bias).

2. **`generate_personality_block(archetype_id, conn)`** → 20-trait dict.
   - Same formula: `50 + bias + ±8 noise`. Same base-50 starting point.
   - `seed_world_phase3.py` line 486-491 widens this post-generation: scales each value away from 50 by 1.3-2.0× + ±5 noise, clamped [10, 95]. `retirement_svc.generate_fighter` line 444-450 replicates this widening for regen fighters.

3. **`generate_physical_block(weight_class_max_kg, gender)`** → height_cm, reach_cm, stance, handedness.
   - v2.6.3: height is scaled by weight class (47kg→168cm, 120kg→193cm, female −7cm). Gaussian noise std=5.

4. **`generate_potential()`** → int in [25, 90].
   - Distribution (line 537-542):
     - 10% elite (70-90) — "that kid from Mexico"
     - 30% solid (50-69)
     - 60% limited (25-49)
   - Pure function — no I/O.

5. **`generate_nickname(attrs, pers, style_archetype_name, nation_name, rng)`** → str or None.
   - v2.6.3: replaced the old fixed pool of 38 nicknames (each shared by ~43 fighters) with attribute/style/personality/nation-based generation. 40% of fighters get no nickname.

**`src/services/retirement_svc.py:generate_fighter()` (lines 90-634) — the regen path.**

Called by `tick_processor._check_retirements` (line 1312) when a fighter retires, AND by `agent_offers.py` (for `unknown_talent` and `prospect_gamble` offers). Steps:

1. Pick first + last name from `name_pools` (uniqueness-checked against existing fighters).
2. Determine style archetype:
   - 30% chance: inherit retiring fighter's `fight_style_archetype_id` (style DNA continuity)
   - 70% chance: pick a random archetype, weighted by the retiring fighter's nation (Brazilian successor likely a Grappler; Dagestani likely a Wrestler, etc.). `_NATION_OVERRIDES` dict is duplicated inline (lines 246-267) — known duplication documented as decision D7.
3. Pick a random personality archetype (uniform).
4. Compute DOB: 18-26 years old (young prospect).
5. Pick a random weight class.
6. Inherit `birth_city_id` + `birth_nation_id` from the retiring fighter (region-aware regen, v2.6.1).
7. 50% chance: assign a gym in the retiring fighter's nation. 50%: gym NULL (v2.6.2 — some prospects train independently).
8. Randomized meta-columns: `injury_proneness`, `weight_cut_difficulty`, `consistency`, `clutch_factor`, `marketability`, `fan_friendliness`, `promo_boost` (was all-50).
9. INSERT into `fighters` as a free agent (current_promotion_id=NULL, is_active=1, is_retired=0).
10. Generate `attrs = fighter_gen.generate_attribute_block(style_archetype_id, conn)` → INSERT into `fighter_attributes` (all 25 columns explicitly).
11. Generate `pers = fighter_gen.generate_personality_block(pers_archetype_id, conn)` → widen via 1.3-2.0× scaling → INSERT into `fighter_personality`.
12. Generate nickname via `fighter_gen.generate_nickname(...)` → UPDATE the fighter row (was NULL at INSERT because attrs/pers weren't available yet).
13. **Set `potential` via `fighter_gen.generate_potential()`** → INSERT into `fighter_career (fighter_id, potential) VALUES (?, ?)` (line 520-523). All other fighter_career columns (record, streaks, career_health=100, title_reigns=0) use schema defaults.
14. NO rankings row (requires a promotion_id — created lazily on first signed fight).
15. Write a "new prospect emerges" news item (topic='prospect').
16. Generate a bio (`fighter_bios` table) — tone is always `'unproven_prospect'`, does NOT reveal potential.
17. Publish `FIGHTER_GENERATED` event on the bus (Phase A5).
18. Return the new `fighter_id`.

The caller (`tick_processor._check_retirements`) then:
- INSERTs a row into `regen_lineage` linking retiring_fighter_id → replacement_fighter_id.
- If the retiring fighter was a champion (`title_reigns > 0`), creates a `fighter_memory_links` row of type `'successor'` with link_strength = `min(50 + 10*reigns, 100)`. Writes a "fight fans are already drawing comparisons to former champion {name}" news item (topic='legacy').
- Also writes `style_echo` memory link if archetype was inherited.

**`regen_lineage` table** (39 rows currently) columns: `regen_lineage_id`, `retiring_fighter_id`, `replacement_fighter_id`, `style_dna_archetype_id`, `regen_date`, `created_at`.

### Attribute baseline: old (~50) or new (~37)?

**`fighter_gen._generate_block` uses BASE 50 — NOT the new ~37.**

The re-seed migration `v3_20_0_reseed_fighter_attributes` (build_db.py line 4741-4800) ran ONE-SHOT UPDATE on existing rows:

```sql
UPDATE fighter_attributes SET
  punch_power = MAX(25, punch_power - 15),
  cardio = MAX(25, cardio - 15),
  ... (all 26 attribute columns) ...
WHERE fighter_id IN (SELECT fighter_id FROM fighters WHERE is_active=1);
```

This dropped the world average from ~52 to ~37 (clamp at 25 catches ~3% of high-end attrs). **But the generation code (`fighter_gen._generate_block`) was never updated** — it still uses `50 + bias + noise`.

**Live DB confirmation:**
| Group | Avg punch_power | Avg cardio | Avg fight_iq | Avg chin | n |
|---|---:|---:|---:|---:|---:|
| All active fighters (post-reseed) | 39.3 | 36.6 | 41.8 | 35.1 | 4,450 |
| Regen replacements (fighter_id ≥ 4451) | 41.7 | 38.3 | 40.1 | 39.6 | 39 |

The 39 regen replacements happen to be only ~2-3 points above the world avg because **the v3.20.0 re-seed migration was applied on 2026-08-02 21:31:08, AND many of those 39 regens were generated BEFORE that timestamp** (regen_lineage dates range 2026-07-23 to 2027-02-19). So those regen fighters got the -15 re-seed applied retroactively.

**Any regen fighter generated AFTER the v3.20.0 migration will use the unscaled `50 + bias + noise` formula → avg ~50**, which is ~13 attribute points above the world average of ~37. This is the imbalance the user is flagging.

### Does it set `realization`?

**NO.** `generate_fighter` does NOT set `realization`.

The `fighter_career` INSERT (line 520-523) is:
```python
conn.execute(
    "INSERT INTO fighter_career (fighter_id, potential) VALUES (?, ?)",
    (fid, potential),
)
```

Only `fighter_id` and `potential` are specified. `realization` falls back to the column DEFAULT (0.7). The 4,489 existing fighter_career rows have varied values (0.50-0.82) — these were backfilled by a script that is **NOT in the codebase**. Grep for `realization` across all `.py` files finds only `tick_processor.py` (READ only) and `docs/DESIGN_REVIEW_E5.md` (the spec).

**Schema gap:** the `realization` column was added via `ALTER TABLE fighter_career ADD COLUMN realization REAL DEFAULT 0.7` — visible in `sqlite_master.sql` as `, realization REAL DEFAULT 0.7)` appended after the closing paren (SQLite's pattern for ALTER ADD). **There is NO migration function in `MIGRATIONS` list (build_db.py lines 5196-5243) that adds this column.** A fresh `--fresh` build will NOT have the column — only the live DB has it (because someone ran the ALTER manually).

### Does it set `potential`?

**YES, correctly.** `fighter_gen.generate_potential()` returns an int in [25, 90] using the rare-elite distribution (10% elite 70-90, 30% solid 50-69, 60% limited 25-49). The `generate_fighter` INSERT explicitly sets it (line 519-523).

**Live DB confirmation:**
- All fighter_career rows: avg potential=60.5, min=25, max=92, n=4,489 (the 92 max is from a seed-world script that may have used a slightly different range pre-distribution-fix).
- Regen replacements: avg=50.9, min=26, max=84, n=39 (the lower avg is the regen distribution functioning as designed — fewer elite prospects).

### Regen system summary

| Trigger | Caller | Effect |
|---|---|---|
| Fighter retires (birthday + probability roll) | `tick_processor._check_retirements` line 1312 | Calls `generate_fighter(style_dna_source_id=fighter_id)` → INSERTs new free agent + `regen_lineage` row + (if champion) `fighter_memory_links.successor` row + legacy news |
| Player accepts an `unknown_talent` or `prospect_gamble` agent offer | `agent_offers.resolve_offer` | Calls `generate_fighter(style_dna_source_id=None)` → no regen_lineage row (not a retirement regen) |

**`retirement_svc.check_retirements(conn)`** (line 803-821) is a thin wrapper that reads `simulation_clock.current_date` and delegates to `tick_processor._check_retirements`. The orchestration order in `run_tick` (line 1649-1696) is: clock advance → `_check_retirements` → `_check_contract_expiry` → `_check_injury_recovery` → commit.

### Gaps

1. **🚨 Attribute baseline mismatch (CRITICAL).** `fighter_gen._generate_block` uses base 50 + ±8 noise + ±10 bias → avg ~50. The world is at avg ~37 (after the v3.20.0 re-seed). Regen fighters come in ~13 attribute points above the world average — they are systematically OVERPOWERED. Fix: change the base from 50 to ~37 in `_generate_block` (line 226: `out[col] = _clamp(50 + bias_value + noise, 0, 100)` → `_clamp(37 + bias_value + noise, 0, 100)`). Should also be applied to `seed_world_phase3.py` and the seed_data backfill path so a fresh `--fresh` build is consistent without needing the v3.20.0 re-seed migration.

2. **🚨 `realization` is NEVER set by `generate_fighter` (CRITICAL).** The INSERT (line 520-523) only specifies `fighter_id` and `potential`. New regen fighters get the column DEFAULT (0.7) — a flat, non-personality-driven value. The 4,489 existing fighters have varied values (0.50-0.82) from a backfill script that is NOT in the codebase. Fix: add a `generate_realization(personality_block)` function to `fighter_gen.py` (per `docs/DESIGN_REVIEW_E5.md` §3: based on discipline + coachability + professionalism, penalized by ego + risk_taking + attention_seeking), and add it to the `generate_fighter` INSERT.

3. **🚨 `realization` column migration is MISSING from `MIGRATIONS` list (CRITICAL).** A fresh `--fresh` build will not have the column. The migration name needs to be added to `MIGRATIONS` (build_db.py line 5196+) with a function that does `ALTER TABLE fighter_career ADD COLUMN realization REAL DEFAULT 0.7` (idempotent via `_has_column`). Should also be added to the `fighter_career` CREATE TABLE schema (line 1375-1406).

4. **`fighter_gen` does NOT scale attributes UP toward potential for veteran regens.** `seed_world_phase3.py` lines 502-511 applies growth scaling for prime/declining/veteran stages (80-95% of potential reached for prime, 55-75% for developing). Regen fighters always enter as 18-26yo prospects, so they correctly skip this — but it means regen fighters don't simulate the "older free agent past their prime" use case. `agent_offers.py`'s `washout_veteran` offer type picks an existing FA, so this isn't broken, just incomplete.

5. **`_NATION_OVERRIDES` dict is duplicated** in `retirement_svc.generate_fighter` (lines 246-267) and the Phase 3 seed scripts. If the overrides change, both must be updated. Documented as decision D7 — should be extracted to a shared module.

---

## B. Rival AI Signing

### Current state

**`src/services/rival_ai/signing_agent.py` (737 lines) — Phase 2 of the rival AI.**

Wraps `services.contracts.sign_free_agent` with a multi-promo intent-collection layer. The flow (per `RIVAL_AI_ARCHITECTURE.md §3.3 + §5.3`):

1. **`evaluate_signing_intents(conn, promotion_ids, current_date, rng)`** — called WEEKLY by `src/rival_ai.py` line 603. For each rival promo:
   - Fetch the (state-modified, recency-modified) archetype via `budget_manager.get_modified_archetype`.
   - If budget_state is `SURVIVAL` or `CRISIS` → no signings.
   - `_identify_roster_gaps` → set of weight_class_ids with gaps:
     - Critical gap: 0 fighters in a WC where the promo holds a title.
     - Depth gap: < 4 fighters in any WC the promo operates in.
     - Prospect gap (Rising Star only): no fighter with potential ≥ 70 under age 26 in any WC.
   - If no gaps: 8-12% whimsy chance (per archetype) to sign anyway — picks any WC the promo already operates in.
   - `_search_fa_pool` — filters the cached FA pool by archetype's `signing_potential_floor`, `signing_age_max`, and the gap_wcs. Pool is cached per tick (one query, filtered in Python per promo).
   - For each candidate, compute `_offer_score` (0..1):
     ```
     offer_score = (0.30 * reputation/100
                  + 0.20 * log10(cash+1)/8
                  + 0.15 * path_to_title
                  + 0.15 * staff_quality
                  + 0.10 * (1 - age/40)
                  + 0.10 * potential/100
                 ) * (1 + ±10% randomness)
                 + re_signing_bonus (if previously on roster)
     ```
     - `path_to_title`: 1.0 if candidate would be #1 contender, 0.5 if top-5, 0.2 otherwise.
     - `staff_quality`: count of promo-bound non-coach staff / 8 (max quality).
   - Pick the highest-offer_score candidate. Return intent dict.

2. **`resolve_bidding_wars(conn, intents, current_date, rng)`** — groups intents by `fighter_id`:
   - **Uncontested (1 promo wants the FA):** sign at `base_salary` = `potential × $1K + rating × $50` (the "fair value" formula).
   - **Contested (2+ promos want the same FA):** highest offer_score wins. Salary = `base_salary × min(2.0, 1.0 + bid_premium_pct × num_losers × 0.5)` (capped at 200% of fair value). Losers each get a `bidding_war_lost` news item (topic='bidding_war_lost', sentiment='negative').

3. **`evaluate_contract_expiry_interest(conn, current_date, rng)`** — soft rule, writes `tapping_up_rumor` news items for fighters whose contract expires within 30 days. Rate-limited to 1 rumor per (promo, fighter) per 30 days. 10% whimsy: eligible candidates sometimes don't get a rumor. 5% whimsy: ineligible candidates sometimes get a rumor anyway (tabloid fabrication).

4. **OLD fallback path** (`src/rival_ai.py` line 616-657): the original 10%-per-week-per-promo signing loop with `ai_spending_style` potential thresholds. KEPT for tests + as a fallback when the new signing_agent finds no roster gaps. Caps at roster_size < 50 (MAX_ROSTER_SIZE).

**`src/services/rival_ai/archetypes.py` — the 4 archetypes.**

Per `RIVAL_AI_ARCHITECTURE.md §2`. Frozen via `MappingProxyType`. Assignment rules in `_determine_archetype` (line 209-252):
- `size_tier == 'major' + cash ≥ $10M` → `major_league`
- `size_tier == 'major'` (cash-strapped) → `major_league` if rep ≥ 70 else `regional_power`
- `size_tier == 'mid' + cash ≥ $15M + rep ≥ 60` → `major_league` (only RFL qualifies)
- `size_tier == 'mid'` (other) → `regional_power`
- `size_tier == 'small' + ai_aggression ≥ 55 + cash ≥ $3M` → `rising_star`
- `size_tier == 'small'` (other) → `grassroots`

**Per-archetype signing knobs:**

| Knob | major_league | regional_power | grassroots | rising_star |
|---|---|---|---|---|
| `signing_potential_floor` | 70 | 60 | 30 | 65 |
| `signing_age_max` | 33 | 28 | None (no cap — signs 38yo cast-offs) | 25 |
| `bid_premium_pct` | +0.30 (130% of fair value) | 0.00 (walks above fair value) | -0.20 (bids 80%, walks instantly above) | +0.60 (160% — overspend tolerated) |
| `event_cadence_days` | 14 (bi-weekly) | 28 (monthly) | 84 (quarterly) | 28 (monthly) |
| `cut_aggressiveness` | 0.40 | 0.30 | 0.50 | 0.35 |
| `whimsy_pct` | 0.05 | 0.08 | 0.10 | 0.12 |

**Fit consideration: does it exist?** YES — the archetype's `signing_potential_floor` + `signing_age_max` enforce fit:
- `major_league` only signs potential ≥ 70, age ≤ 33 (established stars).
- `regional_power` signs potential ≥ 60, age ≤ 28 (developing prospects).
- `grassroots` signs potential ≥ 30, ANY age (journeymen + cast-offs — explicitly signs the "scrub" the major_league wouldn't touch).
- `rising_star` signs potential ≥ 65, age ≤ 25 (young high-ceiling prospects — the "breakthrough signing").

**Does it sign journeymen + prospects, or only stars?** BOTH — depending on the archetype:
- `grassroots` is explicitly designed for journeymen/cast-offs (potential floor 30, no age cap, bids 80% of fair value).
- `rising_star` is explicitly for prospects (potential floor 65, age ≤ 25).
- `regional_power` is for developing prospects (potential floor 60, age ≤ 28).
- `major_league` is for established stars (potential floor 70, age ≤ 33).

**Bidding wars: do they happen?** YES — among AI promos. If two rival promos both have a roster gap at the same weight class and both find the same FA in the cached pool, they each generate an intent for that fighter. `resolve_bidding_wars` then resolves the contest: highest offer_score wins, salary is bid up by `bid_premium_pct × losers × 0.5` (capped at 200%). Each loser gets a `bidding_war_lost` news item.

**Is there a "player vs AI" bidding war?** **NO.** The signing_agent runs over `promotion_ids` filtered to exclude the player (line 601 in `rival_ai.py` excludes promo_id=1 from the list — confirmed in `archetypes.py:PLAYER_PROMOTION_ID = 1`). When the player tries to sign a free agent via the UI, they call `sign_free_agent` directly — the AI's weekly evaluation runs separately and could snipe the FA before the player notices, but there's no explicit counter-offer mechanic between the player and AI.

**Signing frequency:** WEEKLY — `evaluate_signing_intents` runs on every tick where `current_day % 7 == 0`. Each rival promo (9 promos total: promos 2-10) evaluates once per week. Most weeks produce 0-2 intents across all promos (most promos have no gap or no eligible FA in their gap WCs). The OLD fallback path adds 10% chance per week per promo as a backstop.

### Gaps

1. **🚨 NO player-vs-AI bidding wars (CRITICAL).** The user explicitly flagged: "if the player isn't competing for signatures of fighters with other promotions (various levels) it's pointless and easy." Currently the AI's `evaluate_signing_intents` excludes the player's promo (promo_id=1). The player signs FAs via direct `sign_free_agent` calls from the UI. There is NO mechanism for:
   - AI to detect that the player is interested in the same FA (no "player made an offer" event).
   - The player to be notified that an AI is interested in an FA they're considering (no `tapping_up_rumor`-style news for FAs the player has scouted).
   - The player to counter-offer when an AI bids up an FA.
   - The player to lose an FA to an AI (the AI just signs FAs from the pool — if the player hasn't signed them yet, the AI can grab them, but there's no head-to-head auction).

2. **NO "interest signal" between AI promos and the player.** The `tapping_up_rumor` system (line 602-714) writes rumors about fighters whose CONTRACTS are expiring — these are signed fighters, not FAs. There's no equivalent "AI is rumored to be interested in this FA" system that would let the player know an FA is contested before they make an offer.

3. **`base_salary` (fair value) formula ignores realization.** Line 464-470: `fair_value = potential × $1K + rating × $50`. With the new `realization` column, a fighter with potential=85 but realization=0.5 has an effective ceiling of 42 (a bust). The fair-value formula treats them the same as a realization=1.0 fighter. Fix: include realization in the fair-value calc, e.g. `potential × realization × $1K + rating × $50`.

4. **The OLD 10%-chance fallback path (rival_ai.py line 616-657) bypasses the archetype fit logic.** It uses `ai_spending_style` potential thresholds (different from archetype's `signing_potential_floor`). This means a `grassroots` promo could occasionally sign a potential-80 star via the fallback path, breaking the "fit" architecture. Should be removed or guarded once the new signing_agent is confirmed stable.

5. **No "depth chart" consideration.** `_identify_roster_gaps` checks fighter COUNT per WC (< 4 = depth gap), but doesn't consider the WC's strength — a promo with 4 journeymen in a WC has no "depth gap" but is still weak. Should add a "talent gap" check (e.g., no fighter in the WC's top-10 ranking → contender gap, even if depth is OK). Actually, `_identify_roster_gaps` already has a "contender gap" check at line 234 — but it's commented as "Per arch doc §3.3 step 1" and the code at line 234 only checks `< 2 fighters in the WC's top-10 ranking` — let me re-check... Actually looking at the code, the "contender gap" is mentioned in the docstring (line 234) but the implementation (lines 240-280) only checks the "critical gap" (title WC with 0 fighters), "depth gap" (< 4 fighters per WC), and "prospect gap" (Rising Star only, no potential ≥ 70 under 26). The "contender gap" check is NOT implemented.

6. **Whimsy is the only noise source.** The ±10% randomness in `_offer_score` (line 397) is the only variation. A promo with a much higher offer_score will almost always win, even if a rival promo is a marginally better fit. Could add a "fighter preference" factor (some fighters prefer to sign with their home-region promo, or with a promo that has a coach from their style archetype).

---

## C. Staff Lifecycle

### Current state

**`src/services/rival_ai/staff_manager.py` (476 lines) — Phase 3 of the rival AI.**

Per `RIVAL_AI_ARCHITECTURE.md §3.5`. Runs QUARTERLY (every 84 sim-days, on `current_day % 84 == 0`) via `src/rival_ai.py` line 672-673 → `_run_quarterly_phase` line 710-731.

**`evaluate_staff_changes(conn, promotion_id, archetype, current_date, rng)`** does TWO things per rival promo:

1. **Fire evaluation** (`_evaluate_fires`, line 122-212):
   - Fetches all promo-bound non-coach staff (scout, commentator, doctor, cutman, general_manager).
   - Per role:
     - **Commentator / general_manager:** NEVER fired (voice of the brand / can't fire yourself).
     - **Scout:** fire-eligible if `< 2 useful reports (potential ≥ 60) in 90 days AND tenure ≥ 180 days`. (Currently always returns 0 — no AI scout has been assigned to scout, per the docstring at line 261-274. So scouts are never actually fire-eligible in practice.)
     - **Doctor / cutman:** fire-eligible if promo's injury rate > 30% above league average in last 90 days (recency bias).
   - Loyalty protection: tenure ≥ 365 days → +1 quarter grace period (approximated by checking 180-day performance window).
   - 30% whimsy roll on fire-eligible staff (most get "one more quarter to turn it around").
   - On fire: UPDATE `staff.promotion_id = NULL`, UPDATE `contracts.status = 'terminated'`, write a `staff` news item (sentiment='neutral').

2. **Hire evaluation** (`_evaluate_hires`, line 215-258):
   - No hires in SURVIVAL/CRISIS budget state.
   - Compare current staff counts per role to `archetype.staff_target` (e.g., major_league wants 3 scouts, 3 commentators, 1 doctor, 1 cutman, 1 GM).
   - Budget check: `cash >= 2 × monthly_staff_commitment`.
   - Hire 1 staff per role per quarter (gradual buildup, not filling the whole gap in one tick).
   - `_hire_staff` (line 354-433):
     - Random name from `name_pools` (first_male + last_name).
     - Random age 28-55.
     - Role-appropriate `specialty` (matches seed values).
     - Salary per `STAFF_SALARY_BY_ROLE` (GM=$80K, doctor=$60K, commentator=$50K, scout=$45K, cutman=$40K).
     - 1-year contract (365 days).
     - INSERT into `staff` + `contracts` + `staff_contracts`.
     - Write a `staff` news item (sentiment='positive').

### Aging: does it happen?

**NO.** Staff `age` is set ONCE at hire/seed and NEVER updated.

Grep for `staff.age`, `UPDATE staff SET age`, `staff_age`, `staff_retir`, `staff_died`, `staff_regener` across all `.py` files: **no matches**.

The `staff_manager._evaluate_hires` only uses `age` for the new-hire random range (28-55) at line 375. The `_evaluate_fires` function reads `s.age` (line 130) but never uses it in any decision logic.

**Live DB confirmation:**
- 382 staff, ages 31-65, avg 48.7. Max age is exactly 65 (the seed cap — separate seed script set initial ages up to 65).
- Pre-audit (per `docs/DB_REVIEW_AUDIT.md` Q2): 379 staff, ages 31-65, avg 48.
- Post-audit: 382 staff (3 hired during run), ages 31-65, avg 48. **Identical age stats — no aging occurred over 90 sim-days.**
- By role: coach (300, age 35-65, avg 49.6), commentator (26, age 31-55, avg 42.5), cutman (10, age 32-53, avg 43.9), doctor (10, age 35-58, avg 47.7), general_manager (10, age 40-59, avg 49.1), scout (26, age 32-60, avg 46.8).

### Retirement: does it happen?

**NO.** There is no `_check_staff_retirements` function anywhere. The retirement service (`src/services/retirement_svc.py`) handles ONLY fighters — grep for `staff` in that file returns NO matches. The fighter retirement path reads `fighters.date_of_birth` and computes retirement probability via `_compute_retirement_probability` (tick_processor.py line 948) — there is no equivalent for staff.

### Death: does it happen?

**NO.** No code anywhere creates a "staff died" event or sets `staff.is_deceased = 1` (the column doesn't even exist on staff). The fighters table has an `is_deceased` column (per the seed_data backfill docstring at line 428: "is_deceased (0)") but no equivalent exists for staff.

### Regen: does it happen?

**NO.** There is no `staff_regen_lineage` table (only `regen_lineage` for fighters, 39 rows). When a staff member is fired or their contract expires, no replacement is generated — the `_evaluate_hires` function hires ONE staff per role per quarter IF the count is below `staff_target`, so over time the roster refills, but there's no torch-passing narrative ("legendary GM's successor takes over") like there is for champion fighters.

### Contract expiry: what happens?

**NOTHING.** Contracts with `end_date < current_date` and `status='active'` are NOT automatically expired by any tick logic. The staff_manager only FIRES staff (sets status='terminated') for cause — it never EXPIRES contracts. Per `docs/DB_REVIEW_AUDIT.md` Q2: "All 82 non-coach staff have active contracts (status='active'). The 300 coaches have NO `staff_contracts` rows — they're gym-bound via `staff.gym_id`. No staff contract has ever expired in the DB (`contracts.status` breakdown: 526 active, 714 terminated — all 714 terminated are from the seed)."

The `_check_contract_expiry` function in `tick_processor.py` (mentioned at line 1459, 1475, 1665) only handles FIGHTER contracts (`fighter_contracts` table), not `staff_contracts`.

### What `staff_manager` DOES NOT do (summary)

| Lifecycle event | Implemented? | Where it would live |
|---|---|---|
| Staff age increment (annual) | ❌ NO | New `staff_anniversary_tick` in `tick_processor.run_tick` |
| Staff retirement (probability by age) | ❌ NO | New `_check_staff_retirements` mirroring `_check_retirements` |
| Staff death (rare event) | ❌ NO | (Optional — real-world, but probably skip) |
| Staff regen (replacement on retirement) | ❌ NO | New `staff_regen_lineage` table + `generate_staff()` primitive |
| Staff contract expiry | ❌ NO | Extend `_check_contract_expiry` to handle `staff_contracts` |
| Staff re-signing (renew expiring contracts) | ❌ NO | New `_evaluate_resigns` in `staff_manager` |
| Staff moving between promos (FA cycle) | ❌ NO | New `_staff_free_agency` tick |

### Gaps

1. **🚨 Staff NEVER age (CRITICAL).** The `age` column is set once at hire and never updated. A 28yo scout hired in 2026 will still be 28 in 2050. Fix: add a `staff_anniversary_tick` to `tick_processor.run_tick` that increments `staff.age += 1` on each staff member's "joined_anniversary" date (use `staff_contracts.start_date` for non-coaches, or add a `hire_date` column to `staff` for coaches).

2. **🚨 Staff NEVER retire (CRITICAL).** A 65yo GM will keep running the promo forever. Fix: add `_check_staff_retirements` mirroring the fighter retirement curve. Suggested curve (per `docs/DB_REVIEW_AUDIT.md` Q2 rec 2): 0% under 55, 2% at 55-59, 5% at 60-64, 15% at 65-69, 30% at 70+. On retirement: fire `STAFF_RETIRED` event, write news item (topic='staff'), set the staff row's `is_active=0` (need to add this column — or reuse `contracts.status='expired'`), expire any active `staff_contracts`.

3. **🚨 Staff contracts NEVER expire (CRITICAL).** A staff contract with `end_date = 2027-01-01` and `status='active'` is still active in 2030. Fix: extend `tick_processor._check_contract_expiry` to also handle `staff_contracts` — when `end_date < current_date` AND `status='active'`, set `status='expired'` and either renew (if the promo wants to keep them) or release (set `staff.promotion_id=NULL`, making them a free-agent staff).

4. **🚨 NO staff regen system (CRITICAL).** When a legendary GM or commentator retires, there's no torch-passing narrative. Fix: create a `staff_regen_lineage` table (mirroring `regen_lineage` for fighters), and a `generate_staff(role_type, successor_of_staff_id)` primitive that creates a replacement with a new name but a `fighter_memory_links`-style "successor" link. This is especially important for commentators (the "voice of the brand") and GMs (the "face of the promo") — the user-facing narrative depends on these roles having continuity.

5. **NO staff free-agency cycle.** When a staff contract expires, the staff should become a free agent (other promos can sign them). Currently they just stay on the promo forever. Fix: extend the existing `_evaluate_hires` to also consider free-agent staff (staff with `promotion_id=NULL` AND active skill level), not just generate fresh staff.

6. **Scout fire-eligibility is broken in practice.** `_scout_performance` (line 261-274) reads the `scouting_reports` table, but no AI scout has ever been assigned to scout (the rival AI doesn't call `scouting_svc`). So `useful_reports` always returns 0, which means ALL scouts with tenure ≥ 180 days are technically fire-eligible — but the 30% whimsy roll saves most of them. Still, this means scout tenure is purely whimsy-driven, not performance-driven. Fix: either have the rival AI call `scouting_svc.assign_scout` weekly, OR remove the scout fire-eligibility check until the AI scouting feature is built.

7. **Coach staff are entirely outside the rival AI's lifecycle.** The 300 coaches are gym-bound (managed by `staff.gym_id`, not `staff.promotion_id`). They're never hired/fired by `staff_manager`. Coaches have NO `staff_contracts` rows. A separate coach-lifecycle system is needed (gym-bound, not promo-bound).

8. **`specialty` field for new hires is a hardcoded JSON/string.** Line 378-384: `'scout'` gets a hardcoded JSON specialty string with `eye_for_talent: 50` etc. — every new scout has identical 50/50 scouting stats. Should randomize these (e.g., 30-70 range) so scouts vary in quality, which would make the (currently broken) scout fire-eligibility meaningful.

---

## Key Findings + Recommendations

### Top 3 findings per area

**A. Fighter Generation:**
1. `fighter_gen._generate_block` uses base 50, NOT 37 — regen fighters come in ~13 attribute points above the post-reseed world average.
2. `generate_fighter` does NOT set `realization` — new regen fighters get the column DEFAULT (0.7), losing the personality-driven variation the user added.
3. The `realization` column was added via an uncommitted `ALTER TABLE` — there's NO migration function in `MIGRATIONS`, so a fresh `--fresh` build will not have the column.

**B. Rival AI Signing:**
1. The signing_agent has a sophisticated multi-promo intent + bidding-war system AMONG AI PROMOS — but the PLAYER is excluded. There is NO player-vs-AI bidding war.
2. Fit is well-modeled via 4 archetypes — `grassroots` explicitly signs journeymen (potential ≥ 30, no age cap), `rising_star` explicitly signs prospects (potential ≥ 65, age ≤ 25), `major_league` signs stars (potential ≥ 70, age ≤ 33).
3. The `base_salary` (fair value) formula ignores `realization` — a "bust" (potential=85, realization=0.5, effective ceiling=42) is priced the same as a "realizer" (potential=85, realization=1.0, effective ceiling=85).

**C. Staff Lifecycle:**
1. Staff NEVER age — the `age` column is set once at hire and never updated.
2. Staff NEVER retire and NEVER die — there is no `_check_staff_retirements` function. The 65yo GMs and commentators run their promos forever.
3. Staff contracts NEVER expire — `end_date` is set but never checked. The `_check_contract_expiry` function in `tick_processor.py` only handles `fighter_contracts`, not `staff_contracts`.

### Biggest gap per area

**A. Fighter Generation:** The base-50 attribute formula in `fighter_gen._generate_block` (line 226) MUST be lowered to ~37 to match the post-reseed world. Without this, every new regen fighter is systematically overpowered.

**B. Rival AI Signing:** The player must be inserted into the bidding-war system — currently `evaluate_signing_intents` excludes the player's promo (promo_id=1), and the player signs FAs via direct `sign_free_agent` calls with no AI competition. Without this, the user is right: "if the player isn't competing for signatures of fighters with other promotions, it's pointless and easy."

**C. Staff Lifecycle:** A complete staff lifecycle system needs to be built — aging (annual `staff.age += 1`), retirement (probability-based by age, mirroring fighter retirement), contract expiry (extend `_check_contract_expiry` to `staff_contracts`), and regen (new `staff_regen_lineage` table + `generate_staff()` primitive). The existing `staff_manager` only handles hire/fire for cause — it doesn't simulate the natural lifecycle.

### Can existing code be extended or does it need rewriting?

**A. Fighter Generation — EXTEND.** The fix is small and surgical:
- Change the base value in `_generate_block` line 226 from `50` to `37` (or extract as a module-level constant `ATTR_BASELINE = 37`).
- Add a `generate_realization(personality_block)` function to `fighter_gen.py`.
- Update `generate_fighter` line 520-523 to include `realization` in the INSERT.
- Add a migration `v3_24_0_add_realization_column` to `MIGRATIONS` that does the `ALTER TABLE` + backfills existing rows.
- Update `seed_world_phase3.py` line 464 to use the new baseline.
- No rewrite needed — the existing primitives are well-designed and reusable.

**B. Rival AI Signing — EXTEND (mostly).** The architecture is sound, but adding player-vs-AI bidding wars requires new event flows:
- The signing_agent's `evaluate_signing_intents` can be extended to include the player's promo (when the player has flagged interest in an FA via a new "scout/watch" UI action).
- A new `PLAYER_OFFER_MADE` event on the bus, subscribed to by the signing_agent, could trigger AI counter-offers.
- The `resolve_bidding_wars` function already handles multi-promo contests — it would just need to include the player as one of the "promos" with the player's offer_score computed from the player's reputation, cash, staff, etc.
- The `_offer_score` formula and `base_salary` fair-value formula need to include `realization` (small change to `_fair_value` line 464-470 and the talent factor in `_offer_score` line 387).
- The OLD 10%-chance fallback path (rival_ai.py line 616-657) should be removed once the new system is confirmed stable — it bypasses the archetype fit logic.

**C. Staff Lifecycle — BUILD (mostly new).** The existing `staff_manager` only handles hire/fire for cause. The lifecycle pieces need to be built:
- New `staff_anniversary_tick` function in `tick_processor.py` (small — `UPDATE staff SET age = age + 1 WHERE ...`).
- New `_check_staff_retirements` function in `retirement_svc.py` (medium — mirrors `_check_retirements` for fighters, reads `staff.age`, applies probability curve, fires `STAFF_RETIRED` event).
- Extend `_check_contract_expiry` in `tick_processor.py` to also handle `staff_contracts` (small — same pattern as fighter contracts).
- New `generate_staff(role_type, successor_of_staff_id)` primitive (medium — mirrors `generate_fighter` but simpler: no attributes, just name + age + role + specialty).
- New `staff_regen_lineage` table (small schema addition — mirrors `regen_lineage`).
- The existing `staff_manager._evaluate_hires` can be EXTENDED to consider free-agent staff (instead of always generating fresh staff) — this would close the FA cycle.
- No rewrite of `staff_manager` itself needed — it just needs to be one of several staff-related tick functions, alongside the new aging/retirement/expiry/regen functions.
