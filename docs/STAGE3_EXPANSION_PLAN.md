# CAGE EMPIRE — Stage 2.5/3 Expansion Plan

> **Status:** Planning document. No coding until user approves.
> **Last revised:** 2026-07-21 — post-audit, post-Soul-document integration.
> **Inputs:** ATTRIBUTE_AND_ENGINE_EXPANSION_BRIEF.md (external AI spec),
> Cage Empire Soul.txt (design philosophy / prime directive).

---

## PART 1: ANALYSIS OF THE ATTRIBUTE SPEC

### What fits

The external AI's attribute spec is excellent. It's better than our
original v1.6 spec in several ways:

**Improvements over our spec:**
1. **`punch_accuracy` / `kick_accuracy`** (separate) vs our `accuracy`
   (single). The split is correct — punch accuracy and kick accuracy
   are different skills. A Muay Thai specialist may have elite kick
   accuracy but average punch accuracy.
2. **`speed_explosiveness`** vs our `punch_speed` / `kick_speed`. The
   external spec correctly identifies that speed is a general athletic
   trait, not per-strike-type. Explosiveness affects takedown speed,
   scramble speed, and striking speed — one attribute, not two.
3. **`strength`** (new, not in our spec). Critical for clinch control,
   takedown power, top control retention. Our spec was missing this.
4. **`durability`** (body/cuts/joints) vs our `chin` (head-only). The
   split is correct — chin is head-trauma resistance, durability is
   everything else (cuts, joint damage, body wear). A fighter can have
   a granite chin but fragile skin (cuts easily).
5. **`flexibility`** (new). Needed for submission escapes, kick range,
   guard retention. Our spec was missing this.
6. **`scramble_ability`** (new). The ability to transition — getting
   back to feet, reversing position, winning chaotic exchanges. This
   is a real MMA skill that our spec didn't capture.
7. **`recovery_rate`** vs our `recovery`. Same concept, better name.
8. **`clinch_striking`** vs our `clinch_offense` / `clinch_defense`.
   The external spec correctly collapses clinch striking into one
   attribute (you don't strike offensively and defensively in the
   clinch differently — you either land knees/elbows or you don't).
   However, we should keep `clinch_offense` / `clinch_defense` for
   the grappling aspects of the clinch (takedown entries, throws).

**Personality improvements:**
1. **`patience`** (new). Independent of aggression — patient pressure
   vs wild pressure are different fighters. Excellent addition.
2. **`killer_instinct`** vs our `finish_instinct` (attribute). Better
   as a personality trait — it's about mentality, not technique.
3. **`grit`** vs our `resilience` (personality) + `toughness`
   (attribute). The external spec correctly separates in-fight grit
   (personality) from physical durability (attribute).
4. **`charisma`** (new). Drives marketability and promo skill. Critical
   for the Kingmaker fantasy (Soul document Fantasy 3).
5. **`travel_comfort`** (new). Ties to nations.travel_difficulty.
   Creates regional advantages — fighting in your home region vs
   traveling abroad. Supports the Puppet Master fantasy (Soul
   document Fantasy 5 — gym ecosystems, regional dynamics).
6. **`risk_taking`** vs our `risk_tolerance` (attribute). Better as a
   personality trait — it's about willingness, not capability.
7. **`sportsmanship`** vs our `respectfulness`. Same concept, better
   name — covers post-fight conduct, rivalry de-escalation.

### What doesn't fit (modifications needed)

1. **Missing from external spec but in ours:**
   - **`cage_wrestling`** — pressing opponents against the cage,
     wall-walking. This is a distinct MMA skill (vs mat wrestling).
     **Keep it.** Add it to the Grappling group.
   - **`ringcraft`** — using the cage/octagon strategically (cutting
     off angles, avoiding being backed into corners). Overlaps with
     `footwork` but is more tactical. **Fold into `fight_iq`** —
     ringcraft is an expression of fight IQ, not a separate physical
     attribute. This simplifies without losing meaning.
   - **`damage_output`** — how much damage each landed strike does.
     Overlaps with `punch_power` / `kick_power`. **Drop it** — power
     already captures this. Adding damage_output double-counts.
   - **`finish_instinct`** (attribute) — moved to personality as
     `killer_instinct` per the external spec. **Correct.**

2. **External spec has `clinch_striking`** — we should ADD this as a
   new column alongside `clinch_offense` / `clinch_defense` (which
   cover the grappling aspects of the clinch). The external spec
   doesn't have `clinch_offense` / `clinch_defense` at all — they
   seem to have collapsed all clinch work into `clinch_striking`.
   **Keep both:** `clinch_striking` for strikes in the clinch,
   `clinch_offense` / `clinch_defense` for takedown entries/throws
   from the clinch.

3. **External spec has `punch_accuracy` / `kick_accuracy`** but our
   original spec also had `defense` (general). The external spec
   replaces `defense` with `head_movement`. **Keep `head_movement`
   but also keep a general `defense`** — head movement is one form
   of defense, but blocking, parrying, and footwork-based evasion
   are also defense. Actually, re-reading: `footwork` covers distance
   evasion, `head_movement` covers head evasion. Blocking/parrying is
   fight_iq-related (knowing when to cover up). **Drop `defense`** —
   it's too generic and is already covered by `head_movement` +
   `footwork` + `fight_iq`.

### Final merged attribute list (25 columns)

| Group | Column | Source | What it governs |
|---|---|---|---|
| Striking | `punch_power` | existing | KO probability on clean punches |
| Striking | `punch_accuracy` | external spec | landed-vs-thrown ratio on punches |
| Striking | `kick_power` | external spec | KO/damage probability on clean kicks |
| Striking | `kick_accuracy` | external spec | landed-vs-thrown ratio on kicks |
| Striking | `head_movement` | external spec | evasion — reduces opponent's landed-strike rate |
| Range | `footwork` | external spec | ring generalship, distance/angle control |
| Range | `clinch_striking` | external spec | knees/elbows/dirty boxing in the clinch |
| Range | `clinch_offense` | our spec | takedown entries/throws from the clinch |
| Range | `clinch_defense` | our spec | stuffing clinch takedown entries |
| Grappling | `takedown_offense` | both | landing takedowns |
| Grappling | `takedown_defense` | both | stuffing takedowns (sprawl) |
| Grappling | `top_control` | both | maintaining dominant position once on top |
| Grappling | `bottom_game` | both | offense/sweeps from the bottom (guard play) |
| Grappling | `submission_offense` | both | threatening/finishing submissions |
| Grappling | `submission_defense` | both | escaping/defending submission attempts |
| Grappling | `scramble_ability` | external spec | transitions — getting up, reversing |
| Grappling | `cage_wrestling` | our spec | pressing opponents against the cage, wall-walking |
| Physical | `cardio` | existing | gas tank — output decay across rounds |
| Physical | `chin` | existing | head-trauma resistance, KO/rock resistance |
| Physical | `recovery_rate` | external spec | between-round recovery, bounce-back after being hurt |
| Physical | `speed_explosiveness` | external spec | reflexes, burst athleticism, reaction time |
| Physical | `strength` | external spec | clinch/top-control retention, takedown power |
| Physical | `durability` | external spec | resistance to cuts/joint damage/cumulative body wear |
| Physical | `flexibility` | external spec | submission escapes, kick range/height, guard retention |
| Mental | `fight_iq` | existing | gameplan execution, in-fight problem-solving, ringcraft |
| Mental | `adaptability` | both | capability to switch approach mid-fight |

**Total: 25 columns** (4 existing + 21 new). One more than the
external spec's 24 because we kept `clinch_offense`, `clinch_defense`,
and `cage_wrestling` which the external spec didn't have.

### Final merged personality list (20 fields)

| Group | Column | Source | What it governs |
|---|---|---|---|
| Temperament | `aggression` | existing | forward pressure, initiation rate |
| Temperament | `composure` | existing | poise under pressure, resistance to panic |
| Temperament | `risk_taking` | external | willingness to attempt high-risk/high-reward techniques |
| Temperament | `killer_instinct` | external | urgency/effectiveness finishing a hurt opponent |
| Temperament | `grit` | external | fighting through adversity rather than folding |
| Temperament | `discipline` | both | sticking to the gameplan under fatigue/adversity |
| Temperament | `patience` | external | willingness to wait for openings vs forcing |
| Career | `ambition` | both | drive to seek ranked opponents/title shots |
| Career | `loyalty` | both | attachment to gym/promotion — free agency, poaching |
| Career | `charisma` | external | promo skill, fan connection — feeds marketability |
| Career | `attention_seeking` | external | trash talk / social media driver |
| Career | `coachability` | both | receptiveness to staff coaching — camp gains |
| Career | `professionalism` | both | weight-cut discipline, avoiding off-field incidents |
| Resilience | `ego` | both | willingness to take "beneath them" fights |
| Resilience | `resilience` | both | mental bounce-back after a loss |
| Resilience | `sportsmanship` | external | post-fight conduct — rivalry de-escalation |
| Resilience | `travel_comfort` | external | performance impact fighting far from home |
| Dynamic | `morale` | existing | short/medium-term emotional state |
| Dynamic | `focus` | external | current mental sharpness heading into camp/fight |
| Dynamic | `fatigue_tolerance` | external | resistance to cumulative wear across camp/career |

**Total: 20 fields** (3 existing + 17 new). Matches the external spec.

---

## PART 2: ANALYSIS OF THE ENGINE SPEC

### What fits

The beat-level round simulation is a **massive upgrade** over our
current single-resolution model. Key strengths:

1. **Phase-to-attribute mapping.** Each phase (standing, clinch,
   ground_top, ground_bottom, scramble) uses only the relevant
   attributes. This is how real MMA works — a striker's takedown
   defense doesn't matter when they're on their back. This makes
   the 25 attributes meaningful instead of just being a combined
   power score.

2. **Fatigue system.** Gas as a depleting resource across beats and
   rounds, with cardio/recovery_rate/fatigue_tolerance all playing
   distinct roles. This creates the late-round dramatic shifts that
   make fights exciting (the "he's gassing!" moment).

3. **Momentum system.** Large swings (knockdowns, near-finishes)
   shift subsequent beat probabilities. This produces believable
   "smells blood" sequences instead of memoryless coin flips. This
   is critical for the **dopamine loop** — the player needs to see
   dramatic momentum shifts, not just a result.

4. **Mid-round finishes.** A fight can end at beat 7 of round 2,
   not just at "round 2, 5:00". This creates the "oh my god it's
   over" moment that makes fight highlights memorable.

5. **`fight_beats` table.** Every exchange is recorded. This is the
   raw material for the commentary engine (Task 23), the punditry
   system (Task 24), and the show rating engine (Task 26). Without
   beat-level data, commentary is generic ("X defeated Y"). With it,
   commentary is specific ("Vale landed a devastating right hand at
   2:34 of round 2 that staggered Reed against the cage").

### What needs modification

1. **Beat count formula.** The spec proposes
   `beats = clamp(15 + round((pace_a + pace_b) / 2 / 10), 12, 28)`.
   This is reasonable but the pace formula
   `pace = aggression*0.4 + speed_explosiveness*0.4 - fatigue_penalty*0.2`
   should also factor in `cardio` (a tired fighter slows down) and
   `discipline` (a disciplined fighter maintains output). Revised:
   `pace = aggression*0.3 + speed_explosiveness*0.3 + cardio*0.2 + discipline*0.2`

2. **Phase transitions need a "cage" phase.** The spec has
   `standing`, `clinch`, `ground_top`, `ground_bottom`, `scramble`.
   MMA also has a "cage" phase — fighters pressed against the cage
   wall, which is distinct from open clinch. This is where
   `cage_wrestling` matters. **Add `cage` as a 6th phase.**
   Updated phase mapping:
   - `cage` → cage_wrestling, clinch_offense, clinch_defense, strength,
     takedown_offense, takedown_defense

3. **Submission logic needs `flexibility`.** The spec says submission
   defense uses `submission_defense + scramble_ability + composure`.
   It should also use `flexibility` (physical attribute for physically
   escaping submissions) — flexibility is a physical trait that
   directly affects submission escapes.

4. **KO logic needs `durability`.** The spec says KO threshold is
   modified by `chin`, `recovery_rate`, and `killer_instinct`. It
   should also factor in `durability` for body-shot KOs (liver kicks,
   body punches) — `chin` is head-only.

5. **Fight outcome types.** Our current resolver produces
   `ko_tko`, `submission`, `unanimous_decision`, `split_decision`,
   `draw`. The beat engine should also produce:
   - `doctor_stoppage` — cumulative damage triggers a doctor stoppage
     (uses `durability` and accumulated `damage_dealt`)
   - `corner_stoppage` — a fighter's corner throws in the towel
     (uses `grit` and `composure` — a fighter who keeps getting beat
     but won't quit may have their corner stop it)
   - `dq` — disqualification (rare, driven by `discipline` — low
     discipline fighters may throw illegal strikes)

### Impact on existing systems

The beat-level engine changes the shape of `resolve_next_fight()`.
Currently it:
1. Picks the next unresolved fight
2. Runs `_resolve_outcome()` (pure function, no DB writes)
3. Writes the result (fights, fight_participants, fighter_career,
   fight_history, rankings, titles, events, news, commentary)
4. Schedules the next event if the event just completed

The new engine:
1. Picks the next unresolved fight
2. Runs `resolve_round()` once per scheduled round
3. Each `resolve_round()` generates 12-28 beats, writes them to
   `fight_beats`
4. After each round, checks for mid-round finish (KO/submission/
   doctor/corner). If finished, stops.
5. If all rounds complete without finish, goes to decision
6. Aggregates `fight_rounds` from `fight_beats`
7. Writes the result (same side effects as current, but with
   enriched commentary from the beat data)

**The `_resolve_outcome()` pure function is replaced.** The new
resolver is not a pure function — it writes beats to the DB as it
goes. This changes the test pattern: `test_fight_resolver.py` can no
longer call `_resolve_outcome()` directly. Instead, it calls
`resolve_next_fight()` and inspects the `fight_beats` table.

**`fight_history.score_margin`** needs redefinition. Currently it's
`abs_margin` from the power-score differential. With the beat engine,
it should be the total damage differential (sum of `damage_dealt`
across all beats for winner vs loser).

---

## PART 3: THE SOUL DOCUMENT — INTEGRATION

### The 5 Core Fantasies mapped to our stage plan

| Fantasy | Player desire | Systems that serve it | Stage |
|---|---|---|---|
| **1. Talent Hunter** | "I find greatness before anyone else" | Scouting (Task 18), hidden potential, uncertain reports, regional networks, regen (Task 14 ✓) | Stage 3 |
| **2. Empire Builder** | "My promotion dominates the sport" | Finances (Task 20), prestige, market expansion, TV deals, champions (Task 11 ✓), rival promotion AI (Task 25) | Stage 4-5 |
| **3. Kingmaker** | "I create stars" | Matchmaking (Task 8 ✓), hype, rankings (Task 10 ✓), media (Task 21), promotion | Stage 4 |
| **4. Historian** | "The world remembers what I built" | Hall of fame, records, memories, historical comparisons, legacy, regen lineage (Task 14 ✓) | Stage 5+ |
| **5. Puppet Master** | "The sport evolves because of my decisions" | Rivalries (Task 22), gym ecosystems, promotion ecosystems, career arcs | Stage 4-5 |

### The dopamine loop mapped to game systems

```
Discover    → Scouting (Task 18), regen prospects (Task 14 ✓), free agents (Task 13 ✓)
    ↓
Invest      → Contracts (Task 9 ✓), signing free agents (Task 13 ✓), training camps (Task 16)
    ↓
Develop     → Training camps (Task 16), coaching staff, gym selection
    ↓
Promote     → Matchmaking (Task 8 ✓), title fights (Task 11 ✓), social media (Task 21), hype
    ↓
Watch Rise  → Fight engine (Task 3 ✓ → Task B rewrite), rankings (Task 10 ✓), commentary
    ↓
Create Legacy → Titles (Task 11 ✓), hall of fame, records, regen lineage (Task 14 ✓)
    ↓
Shape History → Rivalries (Task 22), gym ecosystems, promotion AI (Task 25), career arcs
    ↓
Repeat
```

### The Design Law

> **CAGE EMPIRE DESIGN LAW**
>
> The player does not collect fighters. The player collects stories.
>
> Every major system must contribute to:
> 1. Discovery
> 2. Investment
> 3. Growth
> 4. Conflict
> 5. Legacy
>
> If a feature does not strengthen one of those five pillars, it is
> probably not worth building.

This law must be added to `CONVENTIONS.md` and enforced at task
review time. The supervisor should ask of every task: "Which of the
5 pillars does this strengthen? How does it generate stories?"

### The Interpretation Layer's true purpose

The Soul document reframes the voice/interpretation layer (Task 19)
from "a technical translation layer" to "the machinery that translates
simulation into emotion." This changes the priority — the voice layer
is not a Stage 3 nice-to-have, it's the **connective tissue between
the simulation and the player's experience**.

Raw: `Age 37, Losses 4, Durability down 12%`
Meaning: `His best years may be behind him.`

The voice layer must be built early enough that every subsequent
system (scouting reports, news, commentary, punditry, hall of fame)
can use it. **Move Task 19 to the front of Stage 3**, before scouting
and training camps.

### Anticipation as the real dopamine

The Soul document's key insight: "Players should constantly have
something coming." The game must always have unresolved threads:
- The prospect just signed (when will they fight?)
- The champion nearing retirement (who takes over?)
- The rivalry exploding (when's the rematch?)
- The gym producing talent (who's next?)
- The event next month (what's the card?)

This means the **tick processor** is not just a calendar — it's an
**anticicipation engine**. Every tick should surface unresolved
threads to the player. A future task should add an "Anticipation
Feed" to the UI that shows what's developing, what's coming, and
what's unresolved.

---

## PART 4: REVISED STAGE 3 SPLIT

Based on the analysis above, Stage 3 is split into 3 sub-stages:

### Stage 3a — Fighter Depth (attribute expansion + engine rewrite)

This is the foundation. Everything else in Stage 3 depends on the
full attribute set and the beat-level engine.

| Task | What | Schema version | Dependencies |
|---|---|---|---|
| **14.5** | Expand fighter_attributes (4→25) + fighter_personality (3→20) + archetype bias columns. Backfill existing fighters. New module `src/fighter_gen.py`. | 1.10.0 | None (but must land before 14.7) |
| **14.6** | Add ~14 missing `fighters` columns (height, reach, stance, injury_proneness, weight_cut_difficulty, marketability, etc.) + missing `promotions` columns (ai_aggression, ai_spending_style, broadcast_tier, brand_tone) + missing `gyms` columns (facility_quality, medical_support, sparring_depth, etc.). Combined with 14.5 as a one-off per user instruction. | 1.10.0 (same commit) | 14.5 |
| **14.7** | Fix `current_date` SQLite quirk. Qualify column in `app.py` and `tick_processor.py`. | 1.10.0 (same commit, no version bump) | None |
| **B** | Beat-level fight engine rewrite. New `fight_beats` + `fight_rounds` tables. `resolve_round()` function. Phase-to-attribute mapping. Fatigue system. Momentum system. Mid-round finishes. `fight_history.score_margin` redefined. | 1.11.0 | 14.5 (needs full 25-attribute set) |
| **14.5-regen-update** | Update `generate_fighter()` (Task 14) to use `fighter_gen.py` from Task 14.5. Regen fighters now get full 25-attribute + 20-personality blocks with archetype bias. | 1.11.0 (same commit) | 14.5 + B |

### Stage 3b — Fighter Welfare (injuries, camps, weight cuts)

These systems make the fighter's body a resource that the player
manages — creating investment and growth stories.

| Task | What | Schema version | Dependencies |
|---|---|---|---|
| **15** | Injuries + medical recovery. `injuries` table. Fight resolution (beat engine) creates injuries based on damage accumulation. Tick advances recovery. Injured fighters can't be booked. `career_health` declines from injuries. | 1.12.0 | 14.6 (needs `injury_proneness`), B (needs beat-level damage data) |
| **16** | Training camps. `training_camps` table. Pre-fight camp at gym. Camp modifies attributes slightly (+/- 1-3 points) based on gym specialization and camp focus. Camp fatigue affects fight performance. Camp injury risk feeds Task 15. | 1.13.0 | 14.5 (needs full 25-attribute set to modify), 14.6 (needs gym columns), 15 (camp injury risk) |
| **17** | Weight cuts. `weight_cut_difficulty` column (from 14.6). Pre-fight weight cut. High difficulty + low professionalism = chance of missing weight → catch-weight or cancelled. Cut affects fight performance (lower cardio/stamina). | 1.14.0 | 14.6 (needs `weight_cut_difficulty` + `professionalism`) |

### Stage 3c — Presentation Layer (voice, scouting)

These systems translate the simulation into stories — the Soul
document's core directive.

| Task | What | Schema version | Dependencies |
|---|---|---|---|
| **19** | Voice / interpretation layer. New module `src/voice.py`. `describe_attribute()`, `describe_fighter()`, `describe_fight_beat()`, `describe_career_arc()`. Deterministic. Banded descriptors. Multi-attribute compound descriptions. Feeds into all text-generation systems. | 1.15.0 | 14.5 (needs full 25-attribute set to describe) |
| **18** | Scouting system. `scouting_reports` table. Scout staff role. Assign scout to target → after N ticks, report generated with estimated strengths/weaknesses/ceiling/floor/marketability/injury risk. Report accuracy depends on scout skill + budget + region familiarity. Uses voice layer for report text. | 1.16.0 | 14.5 (needs full attribute set), 19 (uses voice layer for report text) |

---

## PART 5: COLLAPSABLE DETAIL FOR EACH TASK

### Task 14.5+14.6+14.7 — Fighter Schema Expansion (combined one-off)

**Pillars served:** Growth (attributes are the growth substrate),
Discovery (scouting needs attributes to discover)

**Schema changes:**

<details>
<summary>fighter_attributes: 4 → 25 columns (click to expand)</summary>

Add 21 new columns, all `INTEGER NOT NULL DEFAULT 50 CHECK (col BETWEEN 0 AND 100)`:
- punch_accuracy, kick_power, kick_accuracy, head_movement
- footwork, clinch_striking, clinch_offense, clinch_defense
- takedown_offense, takedown_defense, top_control, bottom_game
- submission_offense, submission_defense, scramble_ability, cage_wrestling
- recovery_rate, speed_explosiveness, strength, durability, flexibility
- adaptability

Keep existing: punch_power, cardio, fight_iq, chin (values preserved)
</details>

<details>
<summary>fighter_personality: 3 → 20 fields (click to expand)</summary>

Add 17 new fields, all `INTEGER NOT NULL DEFAULT 50 CHECK (col BETWEEN 0 AND 100)`:
- risk_taking, killer_instinct, grit, discipline, patience
- ambition, loyalty, charisma, attention_seeking, coachability, professionalism
- ego, resilience, sportsmanship, travel_comfort
- focus, fatigue_tolerance

Keep existing: aggression, composure, morale (values preserved)
</details>

<details>
<summary>fighters: add ~14 columns (click to expand)</summary>

- height_cm INTEGER
- reach_cm INTEGER
- stance TEXT (CHECK IN ('orthodox','southpaw','switch'))
- handedness TEXT (CHECK IN ('right','left','ambidextrous'))
- injury_proneness INTEGER DEFAULT 50 CHECK (0-100)
- weight_cut_difficulty INTEGER DEFAULT 50 CHECK (0-100)
- consistency INTEGER DEFAULT 50 CHECK (0-100)
- clutch_factor INTEGER DEFAULT 50 CHECK (0-100)
- marketability INTEGER DEFAULT 50 CHECK (0-100)
- fan_friendliness INTEGER DEFAULT 50 CHECK (0-100)
- promo_boost INTEGER DEFAULT 0 CHECK (-100 to 100)
- preferred_gameplans TEXT (JSON)
- bad_matchup_tags TEXT (JSON)
- is_deceased INTEGER DEFAULT 0 CHECK IN (0,1)
</details>

<details>
<summary>promotions: add 6 columns (click to expand)</summary>

- brand_tone TEXT DEFAULT 'standard'
- starting_budget REAL DEFAULT 0
- broadcast_tier TEXT DEFAULT 'local_stream'
- ownership_type TEXT DEFAULT 'startup'
- ai_aggression INTEGER DEFAULT 50 CHECK (0-100)
- ai_spending_style TEXT DEFAULT 'balanced'
</details>

<details>
<summary>gyms: add 8 columns (click to expand)</summary>

- reputation INTEGER DEFAULT 50 CHECK (0-100)
- membership_cost REAL DEFAULT 0
- facility_quality INTEGER DEFAULT 50 CHECK (0-100)
- medical_support INTEGER DEFAULT 50 CHECK (0-100)
- sparring_depth INTEGER DEFAULT 50 CHECK (0-100)
- development_focus INTEGER DEFAULT 50 CHECK (0-100)
- culture_tone TEXT DEFAULT 'balanced'
- weight_cut_support INTEGER DEFAULT 50 CHECK (0-100)
</details>

<details>
<summary>style_archetypes + personality_archetypes: add bias columns (click to expand)</summary>

- style_archetypes.attribute_bias TEXT (JSON, e.g. {"punch_power": 15, "chin": 10})
- personality_archetypes.trait_bias TEXT (JSON, e.g. {"aggression": 20, "patience": -10})
</details>

<details>
<summary>src/fighter_gen.py: new module (click to expand)</summary>

```python
def generate_attribute_block(archetype_id=None) -> dict:
    """Generate a full 25-attribute block, optionally biased by archetype."""
    # Base 50 + archetype bias + noise(-8, 8), clamped 0-100

def generate_personality_block(archetype_id=None) -> dict:
    """Generate a full 20-personality block, optionally biased by archetype."""
    # Base 50 + archetype bias + noise(-8, 8), clamped 0-100

def generate_physical_block() -> dict:
    """Generate height, reach, stance, handedness."""
    # Height: 165-195cm (normal distribution around 178)
    # Reach: height ± 5-10cm
    # Stance: 80% orthodox, 15% southpaw, 5% switch
    # Handedness: 85% right, 10% left, 5% ambidextrous
```

Used by:
- Backfill script (this task — fills new columns for existing fighters)
- `generate_fighter()` in app.py (Task 14 — regen fighters get full blocks)
</details>

<details>
<summary>current_date quirk fix (14.7 — click to expand)</summary>

In `app.py` `get_clock()` (line 17):
```python
# Was: SELECT current_date, current_day, ...
# Now: SELECT simulation_clock.current_date, simulation_clock.current_day, ...
```

In `tick_processor.py` `run_tick()` and `_check_retirements()`:
```python
# Was: SELECT current_date, ...
# Now: SELECT simulation_clock.current_date, ...
```

Also tighten `test_retirement.py` case L's loosened assertion back to
asserting the specific clock date (now that the quirk is fixed).
</details>

**Acceptance test:** `scripts/test_fighter_attributes.py`
- Assert all 25 attribute columns exist with CHECK constraints
- Assert all 20 personality fields exist with CHECK constraints
- Assert existing 4+3 values preserved after migration
- Assert all new columns populated (no NULLs)
- Assert archetype bias works: generate 100 "brawler" archetype fighters
  vs 100 "technician" archetype fighters, verify brawler averages higher
  on punch_power/chin, lower on footwork/cardio
- Assert `fighter_gen.py` functions are importable and return correct shapes
- Assert `generate_fighter()` (Task 14 regen) now uses `fighter_gen.py`
- Assert `current_date` quirk is fixed (tick advances by exactly 1 day)
- Regression: all 12 existing tests still pass

---

### Task B — Beat-Level Fight Engine

**Pillars served:** Conflict (the fight is the primary conflict),
Watch Rise (the engine produces the dramatic moments players remember)

<details>
<summary>Schema: fight_beats + fight_rounds (click to expand)</summary>

```sql
CREATE TABLE IF NOT EXISTS fight_beats (
    fight_beat_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id               INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    round_number           INTEGER NOT NULL,
    beat_number            INTEGER NOT NULL,
    phase                  TEXT NOT NULL CHECK (phase IN
                             ('standing','clinch','cage','ground_top','ground_bottom','scramble')),
    action_type            TEXT NOT NULL,
    initiator_fighter_id   INTEGER NOT NULL REFERENCES fighters(fighter_id),
    target_fighter_id      INTEGER NOT NULL REFERENCES fighters(fighter_id),
    outcome                TEXT NOT NULL CHECK (outcome IN
                             ('landed','missed','blocked','defended','reversed','knockdown','near_finish')),
    damage_dealt           INTEGER NOT NULL DEFAULT 0,
    control_time_delta     INTEGER NOT NULL DEFAULT 0,
    momentum_shift         INTEGER NOT NULL DEFAULT 0,
    gas_cost_initiator     INTEGER NOT NULL DEFAULT 0,
    gas_cost_target        INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, round_number, beat_number)
);

CREATE TABLE IF NOT EXISTS fight_rounds (
    fight_round_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id                    INTEGER NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
    round_number                INTEGER NOT NULL CHECK (round_number > 0),
    fighter_a_id                INTEGER NOT NULL REFERENCES fighters(fighter_id),
    fighter_b_id                INTEGER NOT NULL REFERENCES fighters(fighter_id),
    fighter_a_damage            INTEGER NOT NULL DEFAULT 0,
    fighter_b_damage            INTEGER NOT NULL DEFAULT 0,
    fighter_a_control_time      INTEGER NOT NULL DEFAULT 0,
    fighter_b_control_time      INTEGER NOT NULL DEFAULT 0,
    fighter_a_knockdowns        INTEGER NOT NULL DEFAULT 0,
    fighter_b_knockdowns        INTEGER NOT NULL DEFAULT 0,
    fighter_a_takedowns         INTEGER NOT NULL DEFAULT 0,
    fighter_b_takedowns         INTEGER NOT NULL DEFAULT 0,
    fighter_a_strikes_landed    INTEGER NOT NULL DEFAULT 0,
    fighter_b_strikes_landed    INTEGER NOT NULL DEFAULT 0,
    fighter_a_gas_remaining     INTEGER NOT NULL DEFAULT 100,
    fighter_b_gas_remaining     INTEGER NOT NULL DEFAULT 100,
    momentum_state              TEXT,
    round_winner_fighter_id     INTEGER REFERENCES fighters(fighter_id) ON DELETE SET NULL,
    created_at                  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (fight_id, round_number)
);
```
</details>

<details>
<summary>Engine mechanics (click to expand)</summary>

**Beat count per round:**
```python
pace_a = aggression*0.3 + speed_explosiveness*0.3 + cardio*0.2 + discipline*0.2
pace_b = (same for fighter b)
beats = clamp(15 + round((pace_a + pace_b) / 2 / 10), 12, 28)
```

**Phase-to-attribute mapping (6 phases):**

| Phase | Initiator attributes | Defender attributes |
|---|---|---|
| `standing` | punch_power, punch_accuracy, kick_power, kick_accuracy, fight_iq, speed_explosiveness | head_movement, footwork, chin, fight_iq |
| `clinch` | clinch_striking, takedown_offense, strength | clinch_defense, takedown_defense, strength |
| `cage` | cage_wrestling, clinch_offense, takedown_offense, strength | cage_wrestling, clinch_defense, takedown_defense, strength |
| `ground_top` | top_control, submission_offense, strength, ground striking (punch_power*0.5) | bottom_game, submission_defense, flexibility, scramble_ability |
| `ground_bottom` | bottom_game, submission_offense, flexibility, scramble_ability | top_control, submission_defense, strength, scramble_ability |
| `scramble` | scramble_ability, speed_explosiveness, strength, cardio | scramble_ability, speed_explosiveness, strength, cardio |

**Fatigue system:**
- Each fighter starts each fight with gas=100.
- Each beat costs gas: standing=1, clinch=2, cage=2, ground=3, scramble=4.
- `fatigue_tolerance` slows decay: `gas_cost = base_cost * (1 - fatigue_tolerance/200)`.
- `cardio` affects how fast gas depletes: `gas_cost *= (1.5 - cardio/100)`.
- Low gas (<30) reduces accuracy by 30%, increases chin vulnerability by 20%.
- Between rounds: `gas += recovery_rate * 0.3` (capped at 100).

**Momentum system:**
- `momentum_shift` per beat: -100 to +100, signed toward initiator.
- A knockdown beat: momentum_shift = +80.
- A near_finish beat: momentum_shift = +60.
- A big takedown: momentum_shift = +30.
- Cumulative momentum in a round shifts subsequent beat probabilities:
  `initiator_advantage = clamp(cumulative_momentum / 200, -0.3, +0.3)`.
  This means a fighter with +100 cumulative momentum gets +0.5 to
  their beat-win probability — enough to produce "smells blood"
  sequences without being deterministic.

**Finish logic:**
- **KO/TKO**: cumulative damage in the current beat sequence crosses
  `threshold = 100 - chin*0.5 - recovery_rate*0.2 - grit*0.1 - composure*0.2`.
  If crossed, the defender is KO'd. `killer_instinct` on the attacker
  increases the chance the finish happens before the defender recovers.
- **Submission**: a `submission_attempt` beat with sufficient
  `control_time_delta` crosses
  `threshold = submission_offense - submission_defense*0.5 - flexibility*0.3 - scramble_ability*0.2 + composure*0.1`.
  If crossed, the defender taps.
- **Doctor stoppage**: cumulative `damage_dealt` across ALL rounds
  crosses `threshold = 200 + durability*2`. The ringside doctor stops
  the fight between rounds.
- **Corner stoppage**: if a fighter loses 3+ consecutive rounds AND
  their `grit` < 40 AND `composure` < 40, their corner may throw in
  the towel (20% chance per qualifying round).
- **DQ**: if a fighter has `discipline` < 20 AND lands a strike in
  an illegal zone (1% chance per beat for low-discipline fighters),
  they're disqualified.

**Decision scoring:**
- Each round, the fighter with higher `damage_dealt + strikes_landed*0.5
  + takedowns*2 + knockdowns*10 + control_time*0.1` wins the round.
- If the margin is < 5, it's a 10-9 round for the winner.
- If the margin is > 20 OR there's a knockdown, it's a 10-8 round.
- Two knockdowns in a round: 10-7.
- Sum across rounds. If all 3 judges agree: unanimous decision.
  If 2/3 agree: split decision. If tied: draw.
</details>

<details>
<summary>Commentary beat selection (click to expand)</summary>

After the fight resolves, select the 3-14 most important beats for
the commentary highlights (per the v1.6 spec's commentary modes:
Quick=3-6, Standard=6-10, Extended=10-14). Selection priority:
1. Knockdown beats (highest priority)
2. Near-finish beats
3. Finish beat (always included)
4. Big momentum swings (|momentum_shift| > 50)
5. Round-winning sequences (last 3 beats of a round the winner dominated)
6. Style clash moments (e.g., a striker stuffing a takedown)

Each selected beat gets a commentary line generated from the beat
data + the voice layer (Task 19). Example:
- Beat: phase=standing, action=right_hand, outcome=knockdown, damage=80
- Commentary: "Vale lands a DEVASTATING right hand! Reed is out cold!"
</details>

**Acceptance test:** `scripts/test_beat_engine.py`
- Assert 12-28 beats per round
- Assert phase transitions work (takedown → ground, scramble → standing)
- Assert fatigue accumulates (cardio=90 out-lands cardio=30 in later rounds)
- Assert momentum creates clustered outcomes (knockdown raises finish probability)
- Assert mid-round finishes work (KO/submission/doctor/corner/DQ)
- Assert `fight_rounds` aggregates match `SUM` over `fight_beats`
- Assert all-90 beats all-30 ≥80% over 100 sims
- Assert no single result type >60%
- Assert commentary beat selection picks the right beats
- Regression: all existing tests updated for new resolver shape

---

### Task 15 — Injuries + Medical Recovery

**Pillars served:** Investment (fighter health is an investment the
player manages), Conflict (injuries create adversity stories)

<details>
<summary>Schema + mechanics (click to expand)</summary>

```sql
CREATE TABLE IF NOT EXISTS injuries (
    injury_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id             INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    event_id               INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id               INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    injury_type            TEXT NOT NULL,
    severity               INTEGER NOT NULL DEFAULT 5 CHECK (severity BETWEEN 1 AND 10),
    body_area              TEXT NOT NULL CHECK (body_area IN
                             ('head','face','jaw','nose','eye','neck','shoulder','arm',
                              'elbow','wrist','hand','ribs','back','hip','knee','ankle','foot','general')),
    start_date             TEXT NOT NULL,
    projected_return_date  TEXT NOT NULL,
    actual_return_date     TEXT,
    long_term_damage       INTEGER NOT NULL DEFAULT 0 CHECK (long_term_damage BETWEEN 0 AND 100),
    career_risk            INTEGER NOT NULL DEFAULT 0 CHECK (career_risk BETWEEN 0 AND 100),
    is_active              INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at             TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

**Injury creation on fight resolution:**
- After the fight resolves, check the `fight_beats` for damage patterns.
- Base injury probability: 5% per fight (non-finish) + severity scaled by
  cumulative `damage_dealt` to the fighter.
- `injury_proneness` (fighters column from Task 14.6) modifies: high
  proneness = more likely to get injured.
- `durability` (attribute) reduces severity: high durability = less
  severe injuries when they do occur.
- KO/TKO finishes: 30% chance of head injury (concussion), severity
  scaled by `damage_dealt` in the finishing sequence.
- Submission finishes: 15% chance of joint injury (the submitted joint).
- Doctor stoppage: guaranteed injury (that's why the doctor stopped it).

**Injury types by body area:**
- Head: concussion (severity 5-10), cuts (1-3)
- Face: laceration (2-5), broken nose (3-5), orbital fracture (5-8)
- Knee: ACL tear (7-10), meniscus (4-7), MCL sprain (3-6)
- Ribs: bruised (2-4), fractured (5-7)
- Hand: broken (4-6)
- General: muscle tear (3-6), fatigue syndrome (2-4)

**Recovery:**
- `projected_return_date = start_date + severity * 14 days` (base).
- `durability` and `recovery_rate` (attribute) speed recovery: reduce
  projected days by `recovery_rate * 0.1` per day.
- Tick processor checks active injuries: if `current_date >= projected_return_date`,
  set `actual_return_date = current_date`, `is_active = 0`.
- `long_term_damage`: severity 8+ injuries have a 30% chance of
  permanent attribute reduction (-2 to -5 on the relevant attribute).
  This is the "wear and tear" that eventually drives retirement.

**`career_health` interaction:**
- Each active injury reduces `fighter_career.career_health` by
  `severity * 2` while active.
- `long_term_damage` permanently reduces `career_health` by the same amount.
- This feeds back into Task 12's retirement logic (career_health < 60
  at age 40+ = retirement).

**Booking restriction:**
- `_pick_matchup()` filters: `AND fighter_id NOT IN (SELECT fighter_id
  FROM injuries WHERE is_active = 1)`.
</details>

---

### Task 16 — Training Camps

**Pillars served:** Growth (camps are how fighters develop),
Investment (the player invests in camps to develop fighters)

<details>
<summary>Schema + mechanics (click to expand)</summary>

```sql
CREATE TABLE IF NOT EXISTS training_camps (
    training_camp_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id                INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    gym_id                    INTEGER NOT NULL REFERENCES gyms(gym_id) ON DELETE RESTRICT,
    event_id                  INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    fight_id                  INTEGER REFERENCES fights(fight_id) ON DELETE SET NULL,
    start_date                TEXT NOT NULL,
    end_date                  TEXT NOT NULL,
    camp_duration_days        INTEGER NOT NULL,
    camp_focus                TEXT NOT NULL CHECK (camp_focus IN
                                 ('striking','grappling','wrestling','conditioning',
                                  'submission','clinch','general','weight_cut')),
    camp_morale               INTEGER NOT NULL DEFAULT 50 CHECK (0-100),
    camp_fatigue              INTEGER NOT NULL DEFAULT 0 CHECK (0-100),
    camp_injury_risk          INTEGER NOT NULL DEFAULT 0 CHECK (0-100),
    camp_weight_cut_pressure  INTEGER NOT NULL DEFAULT 0 CHECK (0-100),
    attribute_changes         TEXT,  -- JSON: {"punch_power": +2, "cardio": +1, ...}
    camp_result_summary       TEXT,
    created_at                TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at                TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

**Camp flow:**
1. When `schedule_next_event()` creates a new event, auto-create a
   training camp for each participant (2 weeks before the event date).
2. Camp focus is determined by the fighter's style archetype and the
   opponent's weaknesses (if known via scouting — Task 18).
3. During the camp (on each tick between camp start and event date):
   - `camp_fatigue` increases by 2-5 per tick (modified by `cardio`
     and `fatigue_tolerance`).
   - `camp_morale` fluctuates based on `coachability` and the gym's
     `culture_tone`.
   - `camp_injury_risk` accumulates (modified by `injury_proneness`
     and the gym's `medical_support`). If it crosses a threshold,
     a camp injury fires (feeds Task 15's injury system).
4. At camp end (event date):
   - `attribute_changes` computed: for the camp's focus area, +1-3
     points on 2-4 relevant attributes. Magnitude scaled by the gym's
     `facility_quality` + `development_focus` and the fighter's
     `coachability` + `fatigue_tolerance`.
   - Changes applied to `fighter_attributes` (permanent, but small).
   - `camp_fatigue` carried into the fight: if >50, reduces the
     fighter's starting `gas` in the beat engine by `camp_fatigue`.
   - `camp_result_summary` generated via the voice layer (Task 19):
     "Vale spent 2 weeks at Ironhouse Gym focusing on striking.
     His coach reports improved punch accuracy (+2) and head movement (+1)."

**Gym specialization:**
- Each gym has a specialization (stored as a JSON column or inferred
  from the highest `attribute_bias` in its archetype).
- Camps at a specialized gym give +50% attribute gains in that
  specialization but -50% in other areas.
- The player can suggest a gym change for a fighter (the fighter's
  `loyalty` affects whether they accept).
</details>

---

### Task 17 — Weight Cuts

**Pillars served:** Conflict (weight cut drama is a pre-fight conflict),
Investment (managing weight cuts is an investment decision)

<details>
<summary>Schema + mechanics (click to expand)</summary>

No new tables. Uses `fighters.weight_cut_difficulty` (from Task 14.6)
and `fighter_personality.professionalism` and `fighter_personality.discipline`.

**Weight cut flow (on fight day, before resolution):**
1. Each fighter cuts weight. Base cut success probability:
   `success = 100 - weight_cut_difficulty*0.5 - (age - 30)*2 + professionalism*0.3 + discipline*0.2`
2. If `success < 50`, the fighter misses weight.
3. Missing weight consequences:
   - The fight becomes catch-weight (no weight class restriction).
   - The fighter who missed weight loses 20% of their purse (Task 20 finances).
   - The fighter who missed weight starts the fight with -15 gas
     (they're depleted from the bad cut).
   - 10% chance the fight is cancelled entirely (if the miss is > 5 lbs).
4. Weight cut drama news item: "Vale misses weight by 3 pounds!
   Reed's camp is furious."
5. Repeated misses affect `professionalism` (-2 per miss) and
   `fan_friendliness` (-3 per miss).

**Weight class changes:**
- A fighter can move up or down a weight class between fights.
- Moving up: `weight_cut_difficulty` decreases by 10 (easier cut).
- Moving down: `weight_cut_difficulty` increases by 15 (harder cut).
- Moving down twice in a row: +25 (cumulative stress).
</details>

---

### Task 19 — Voice / Interpretation Layer

**Pillars served:** ALL 5 — the voice layer is the connective tissue
that translates simulation into stories.

<details>
<summary>Module structure + descriptors (click to expand)</summary>

New module: `src/voice.py`

```python
def describe_attribute(name, value, context="default") -> str:
    """Convert a numeric attribute to a readable descriptor.
    
    Examples:
        describe_attribute("cardio", 91) -> "elite gas tank"
        describe_attribute("chin", 38) -> "fragile under pressure"
        describe_attribute("punch_power", 75, "scouting") -> "above-average power"
        describe_attribute("punch_power", 75, "commentary") -> "heavy hands"
    """

def describe_fighter(fighter_id, conn, context="profile") -> str:
    """Generate a fighter profile blurb from their attributes + personality.
    
    Example: "A patient pressure fighter with elite cardio and heavy hands.
    His suspect chin is a concern against elite strikers."
    """

def describe_fight_beat(beat_data, conn) -> str:
    """Generate a commentary line from a single fight beat.
    
    Example: beat_data = {phase: "standing", action: "right_hand", 
                          outcome: "knockdown", damage: 80, initiator: "Vale"}
    Returns: "Vale lands a DEVASTATING right hand! Reed is out cold!"
    """

def describe_career_arc(fighter_id, conn) -> str:
    """Generate a career arc summary for hall of fame / legacy purposes.
    
    Example: "A late-blooming prospect who rose from obscurity to claim
    the Lightweight title at age 31. Defended it 4 times before a
    knee injury derailed his career. Retired at 37 with a 24-3 record."
    """

def describe_injury(injury_data, conn) -> str:
    """Generate an injury report.
    
    Example: "Moderate ACL tear, projected 8 weeks recovery. May affect
    takedown defense upon return."
    """
```

**Descriptor bands (0-100 scale):**

| Range | Label (default) | Label (scouting) | Label (commentary) |
|---|---|---|---|
| 90-100 | elite | elite | world-class |
| 75-89 | above-average | strong | impressive |
| 60-74 | solid | capable | respectable |
| 40-59 | average | average | serviceable |
| 25-39 | below-average | suspect | lacking |
| 10-24 | poor | liability | woeful |
| 0-9 | abysmal | critical weakness | non-existent |

**Attribute-specific descriptors (examples):**

| Attribute | High (85+) | Low (35-) |
|---|---|---|
| punch_power | "heavy hands" / "one-punch knockout power" | "pillow-fisted" / "lacks stopping power" |
| cardio | "elite gas tank" / "endless energy" | "gasses early" / "questionable stamina" |
| chin | "granite chin" / "takes a shot like a tree" | "glass chin" / "fragile under pressure" |
| submission_offense | "submission sniper" / "dangerous grappler" | "no submission threat" |
| fight_iq | "cerebral" / "tactical genius" | "wild" / "no gameplan" |
| speed_explosiveness | "explosive athlete" / "lightning-fast" | "plodding" / "slow twitch" |

**Multi-attribute compound descriptors:**
- High aggression + low patience + high punch_power = "reckless brawler"
- High fight_iq + high patience + high footwork = "methodical technician"
- High cardio + high grit + low punch_power = "volume pressure fighter"
- High submission_offense + high flexibility + high patience = "submission specialist"
- High takedown_offense + high top_control + low submission_offense = "wrestle-boxer"
- High chin + high punch_power + low footwork = "brawler with an iron jaw"

**Context determines tone:**
- `scouting`: measured, analytical ("above-average power")
- `commentary`: excited, immediate ("HE LANDS A BOMB!")
- `news`: neutral, journalistic ("known for his knockout power")
- `hall_of_fame`: reverent, narrative ("legendary chin")
</details>

---

### Task 18 — Scouting System

**Pillars served:** Discovery (Fantasy 1 — "I find greatness before
anyone else"), Investment (scouting reports inform signing decisions)

<details>
<summary>Schema + mechanics (click to expand)</summary>

```sql
CREATE TABLE IF NOT EXISTS scouting_reports (
    scouting_report_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_id              INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE RESTRICT,
    target_fighter_id     INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    promotion_id          INTEGER REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    report_type           TEXT NOT NULL CHECK (report_type IN
                             ('initial','follow_up','rival_check','title_readiness')),
    report_date           TEXT NOT NULL,
    estimated_attributes  TEXT,  -- JSON: {"punch_power": 75, "cardio": 82, ...}
    estimated_personality TEXT,  -- JSON
    strength_summary      TEXT,
    weakness_summary      TEXT,
    ceiling               TEXT,   -- "title contender" / "gatekeeper" / "prospect" / "journeyman"
    floor                 TEXT,   -- "club fighter" / "amateur" / "can"
    marketability         INTEGER CHECK (0-100),
    injury_risk           INTEGER CHECK (0-100),
    contract_cost_estimate REAL,
    development_outlook   TEXT,
    loyalty_risk          INTEGER CHECK (0-100),
    summary_verdict       TEXT,
    confidence_level      INTEGER NOT NULL DEFAULT 50 CHECK (0-100),
    is_stale              INTEGER NOT NULL DEFAULT 0 CHECK (0-1),
    created_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at            TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

**Scout mechanics:**
1. The player hires a Scout (new staff role_type). Scout has
   `skill_level` (0-100) and `specialty` (region or weight class).
2. The player assigns the scout to a target fighter (free agent or
   rival promotion fighter).
3. On each tick, the scout accumulates "scouting progress" toward the
   report. Progress rate = `scout.skill_level * 0.5 + budget_factor`.
4. When progress reaches 100, the report is generated:
   - `estimated_attributes`: for each of the 25 attributes, generate
     an estimate = `true_value + gauss(0, (100 - scout.skill_level) * 0.3)`.
     A skill-90 scout estimates within ±3; a skill-50 scout estimates
     within ±15.
   - `strength_summary` / `weakness_summary`: top 3 attributes above
     70 / below 40, described via the voice layer (Task 19).
   - `ceiling` / `floor`: based on age, current attributes, and
     archetype potential.
   - `marketability`: estimate of the fighter's star power (uses
     `charisma` + `attention_seeking` + fighting style).
   - `injury_risk`: based on `injury_proneness` + age + fighting style
     (brawlers get hurt more).
   - `contract_cost_estimate`: based on attributes + age + current
     contract salary (if known).
   - `summary_verdict`: one-line summary via voice layer.
   - `confidence_level`: scout.skill_level * 0.5 + random(0, 50).
5. Reports become stale: after 30 days, `is_stale = 1`. Stale reports
   have wider error bars. The player can request a follow-up report.

**Scout skill growth:**
- Successful reports (where the estimate was close to true value)
   increase `scout.skill_level` by 1-2.
- Reports on fighters in the scout's `specialty` region/weight class
  are 20% more accurate and 30% faster.

**UI:**
- Scouting tab in the right-pane notebook (5th tab).
- Shows: assigned scouts, current targets, progress bars, completed
  reports (clickable to view full report).
- "Assign Scout" button: select a free scout + a target fighter →
  starts the scouting process.
</details>

---

## PART 6: WHAT ELSE NEEDS UPDATING

### Regen engine (Task 14) update

`generate_fighter()` must be updated to use `fighter_gen.py`:
```python
# Old (Task 14):
conn.execute("INSERT INTO fighter_attributes (fighter_id) VALUES (?)", (fid,))
# All attributes default to 50.

# New (after Task 14.5):
from fighter_gen import generate_attribute_block, generate_personality_block
attrs = generate_attribute_block(style_archetype_id)
pers = generate_personality_block(personality_archetype_id)
conn.execute("INSERT INTO fighter_attributes (fighter_id, punch_power, punch_accuracy, ...) VALUES (?, ?, ?, ...)",
             (fid, attrs['punch_power'], attrs['punch_accuracy'], ...))
```

This means regen fighters are no longer generic 50-everything prospects —
they inherit the retiring fighter's style archetype bias, making them
feel like a spiritual successor (supporting the Soul document's
"his son is fighting" memory).

### Seed data update

The existing 5 seeded fighters need backfill:
- John Vale, Marcus Reed (AC): backfill 21 new attribute columns +
  17 new personality columns using the "Balanced" archetype bias.
- Dario Knox, Eli Storm, Cole Briggs (RFL): same.
- Also backfill the 14 new `fighters` columns (height, reach, stance,
  etc.) for all 5 fighters.

The 2 existing archetypes ("Balanced" style, "Calm" personality) need
`attribute_bias` / `trait_bias` JSON columns populated:
- "Balanced" style: `{"punch_power": 5, "cardio": 5, "fight_iq": 5}`
  (slightly above average everywhere, no weakness).
- "Calm" personality: `{"composure": 15, "aggression": -10, "patience": 10}`.

Additional archetypes should be seeded to make the regen engine
produce variety:
- Style archetypes: "Striker", "Grappler", "Wrestler", "All-Rounder",
  "Brawler", "Counter-Striker", "Submission Specialist"
- Personality archetypes: "Aggressive", "Methodical", "Showman",
  "Quiet Professional", "Wildcard"

### Fight resolver rewrite impact

The beat-level engine replaces `_resolve_outcome()` (pure function)
with `resolve_round()` (writes to DB). This means:
- `test_fight_resolver.py` must be rewritten to inspect `fight_beats`
  instead of calling `_resolve_outcome()` directly.
- `test_fight_history.py`'s score_margin assertion must change (now
  computed from beat damage, not power-score differential).
- All tests that call `resolve_next_fight()` still work (the function
  signature is unchanged), but the internal mechanics are completely
  different.

### Commentary enrichment

The beat engine produces rich data for commentary. The current
`_format_fight_news()` and `_format_fight_commentary()` functions
(hardcoded strings) should be replaced with voice-layer-generated
text that references specific beats:
- Old: "John Vale KO's Marcus Reed in round 1"
- New: "John Vale puts Marcus Reed away with a devastating right hand
  at 2:34 of round 1"

This naturally feeds into Task 23 (news engine) and Task 24
(punditry), but the basic enrichment should happen in the engine
rewrite (Task B) so the data is available.

---

## PART 7: REVISED STAGE SUMMARY

| Stage | Tasks | Theme | Pillars served |
|---|---|---|---|
| **2.5** | 14.5+14.6+14.7, B | Fighter depth + engine rewrite | Growth, Conflict |
| **3a** | 15, 16, 17 | Fighter welfare (injuries, camps, weight cuts) | Investment, Growth, Conflict |
| **3b** | 19, 18 | Presentation (voice layer, scouting) | Discovery, all 5 |
| **4** | 20, 21, 22, 23, 24 | Media & economy | Empire Builder, Kingmaker, Puppet Master |
| **5** | 25, 26, 27, 28, 29, 30 | AI & polish | Empire Builder, Historian |

**Execution order within Stage 2.5:**
1. Task 14.5+14.6+14.7 (combined, one commit) — schema expansion + quirk fix
2. Task B — beat-level engine rewrite (depends on 14.5's full attribute set)
3. Task 14.5-regen-update — update `generate_fighter()` to use `fighter_gen.py`

**Execution order within Stage 3a:**
4. Task 15 (injuries) — depends on 14.6 + B
5. Task 16 (training camps) — depends on 14.5 + 14.6 + 15
6. Task 17 (weight cuts) — depends on 14.6

**Execution order within Stage 3b:**
7. Task 19 (voice layer) — depends on 14.5
8. Task 18 (scouting) — depends on 14.5 + 19

**Then Stage 4 (media & economy):**
9. Task 20 (finances) — depends on 14.6 (marketability)
10. Task 21 (social media) — depends on 14.5 (attention_seeking, charisma)
11. Task 22 (rivalries) — depends on 21
12. Task 23 (news engine) — depends on 19 + B (beat data for commentary)
13. Task 24 (punditry) — depends on 14.5 + B + 19

**Then Stage 5 (AI & polish):**
14-19. Tasks 25-30 as planned.

---

## PART 8: OPEN QUESTIONS FOR THE USER

1. **Task 14.5+14.6 combined commit.** You said "yes but only as a one-off
   and test thoroughly." The combined commit adds 21 attribute columns +
   17 personality columns + 14 fighter columns + 6 promotion columns +
   8 gym columns + 2 archetype bias columns = **68 new columns across 6
   tables**, plus the `fighter_gen.py` module, plus the `current_date`
   quirk fix. This is the largest single schema change since the project
   started. Are you comfortable with this scope, or should I split it
   into 14.5 (attributes+personality+archetypes) and 14.6 (fighters+
   promotions+gyms) as separate commits?

2. **Beat engine complexity.** The beat-level engine is significantly
   more complex than the current resolver. The `resolve_round()`
   function will be 200-300 lines of phase-transition logic, fatigue
   tracking, momentum accumulation, and finish checks. Are you
   comfortable with this complexity in a single task, or should I
   split it into "B1: fight_beats + fight_rounds tables + basic beat
   loop" and "B2: fatigue + momentum + mid-round finishes" as
   separate tasks?

3. **Archetype seed data.** The regen engine needs variety in
   archetypes to produce interesting fighters. I propose seeding 7
   style archetypes and 5 personality archetypes (listed in Part 6).
   Should I also seed archetype bias JSON for each, or let the first
   few regen fighters use the "Balanced" archetype until we tune the
   biases?

4. **The Soul document's "Anticipation Feed."** This is a UI feature
   that shows the player what's developing, what's coming, and what's
   unresolved. It's not in the current 30-task plan. Should I add it
   as a new task (e.g., Task 19.5 or Task 31), or fold it into an
   existing task (e.g., the UI work in Task 28 CustomTkinter)?

5. **The Design Law enforcement.** I propose adding the CAGE EMPIRE
   DESIGN LAW to `CONVENTIONS.md` and asking "which of the 5 pillars
   does this strengthen?" at every task review. Do you agree with this
   enforcement mechanism, or do you prefer a softer approach?

6. **Stage 3 split.** I've proposed splitting Stage 3 into 3a (fighter
   welfare) and 3b (presentation). The key insight from the Soul
   document is that the voice layer (Task 19) should come BEFORE
   scouting (Task 18) because scouting reports use the voice layer.
   But the voice layer needs the full attribute set (Task 14.5) to
   describe. So the order is: 14.5 → B → 15/16/17 → 19 → 18. Does
   this ordering work for you?
