# CAGE EMPIRE — Potential vs Current Ability

> **Purpose:** Clear explanation of how fighter potential and current
> ability work in the game, where they're stored, and how they relate.
> Addresses the user's question: "where is potential and current ability
> stored or is it calculated?"

---

## Quick Summary

| Concept | Where Stored | Scale | Visible to Player? |
|---|---|---|---|
| **Potential** | `fighter_career.potential` | 0-100 | NO (hidden until scouted — Task 18) |
| **Current Ability** | NOT stored as a single number | — | Reflected through attributes + ELO |
| **Attributes** (25) | `fighter_attributes` table | 0-100 each | YES (raw numbers in DB; UI shows descriptors via Task 19) |
| **ELO Rating** | `rankings.rating` | ~900-1400 | YES (ranking position) |

---

## 1. Potential (the Ceiling)

**Stored in:** `fighter_career.potential` (INTEGER, 0-100)

**What it is:** The fighter's growth ceiling. Attributes cannot exceed
this value through training camps or any other growth mechanism. A
fighter with potential=75 can never have any attribute above 75, no
matter how many camps they do.

**Distribution (set at fighter creation, never changes):**
- **10% elite (70-90):** Future champions, superstars. Rare and exciting to find.
- **30% solid (50-69):** Can become contenders with development.
- **60% limited (25-49):** Journeymen who plateau early. Most of the roster.

**Why it's hidden:** Per CONVENTIONS §14, the player doesn't see raw
numbers in the UI. Potential is revealed through:
1. **Scouting reports** (Task 18, future) — a scout estimates potential
   with Gaussian noise around the true value.
2. **Watching the fighter fight** — as they age, their attributes grow
   toward their potential, and the player can infer the ceiling.
3. **Training camp results** (Task 16) — when a camp completes, the
   attribute_changes JSON shows which attributes grew. If a fighter's
   attributes stop growing, they've hit their potential.

**Key design rule:** An 18-year-old elite prospect and an 18-year-old
limited prospect have IDENTICAL attributes (~50 each). You CANNOT tell
them apart by looking at stats. This is the scouting challenge — the
Talent Hunter fantasy depends on it.

---

## 2. Current Ability (NOT a Single Number)

**Current ability is NOT stored as a single value.** It's reflected
through two systems:

### 2a. Attributes (25 values, 0-100 each)

**Stored in:** `fighter_attributes` table

**What they are:** The fighter's current skill level across 25
dimensions:
- **Striking (5):** punch_power, punch_accuracy, kick_power, kick_accuracy, head_movement
- **Range (3):** footwork, clinch_striking, clinch_offense, clinch_defense
- **Grappling (7):** takedown_offense, takedown_defense, top_control, bottom_game, submission_offense, submission_defense, scramble_ability
- **Physical (6):** cage_wrestling, recovery_rate, speed_explosiveness, strength, durability, flexibility
- **Mental (4):** adaptability, cardio, fight_iq, chin

**How they grow:** Training camps (Task 16) upgrade 2-4 attributes by
+1 to +3 each, capped at the fighter's `potential`. The growth is:
- Scaled by gym spec (facility_quality + development_focus → 0.5-1.5x)
- Scaled by coachability (0.5-1.5x)
- Scaled by fatigue tolerance vs camp fatigue (0.5-1.0x)

**How they relate to potential:** Attributes start at ~50 (archetype-
biased) for young fighters. As they age and train, attributes grow
toward potential. By prime (28-32), attributes strongly correlate with
potential. By then the fighter has a fight record the player can read.

### 2b. ELO Rating (ranking score)

**Stored in:** `rankings.rating` (REAL, ~900-1400)

**What it is:** The fighter's competitive ranking score, computed from
fight results using ELO (K=32, zero-sum). A fighter who wins gains
points; the loser loses the same amount. The magnitude depends on the
rating difference (upsets are worth more).

**Scale:**
- **1000:** Average (starting point for all fighters)
- **1050-1100:** Solid roster fighter
- **1100-1200:** Contender
- **1200-1300:** Champion / elite
- **1300+:** All-time great

**Why our "highest rated" fighters seem "low":** ELO is on a 1000-1400
scale, NOT a 0-100 scale. A rating of 1277 (our top fighter) means
"elite champion" — it's NOT comparable to a 0-100 attribute value.
The ELO scale is intentionally compressed because:
1. It makes upsets meaningful (a 1050 beating a 1200 is a big swing)
2. It produces realistic ranking gaps (the #1 vs #10 gap is ~100
   points, not 50)
3. It's the standard ELO scale used in chess, competitive gaming, etc.

---

## 3. How Potential and Current Ability Interact

```
Age 18 (prospect):
  potential = 85 (elite, hidden)
  attributes = ~50 each (archetype-biased, can't tell elite from limited)
  ELO = 1000 (just started, no fights)

Age 25 (developing):
  potential = 85 (unchanged)
  attributes = ~55-60 each (growing via camps, 55-75% of potential reached)
  ELO = ~1050-1100 (winning some, losing some)

Age 30 (prime):
  potential = 85 (unchanged)
  attributes = ~68-80 each (80-95% of potential reached — now visible)
  ELO = ~1150-1250 (proven contender/champion)

Age 38 (veteran):
  potential = 85 (unchanged, but now mostly reached)
  attributes = ~68-81 (plateaued near potential, may decline from age)
  ELO = ~1100-1200 (past peak, still competitive)
```

**The scouting arc:**
- At 18, you CAN'T tell if a prospect is elite or limited — attributes
  are ~50 for everyone. You have to scout (Task 18) or wait.
- At 25, attributes start diverging — an elite prospect is pulling
  ahead of a limited one, but the gap is still small.
- At 30, the gap is obvious — elite fighters have 70+ attributes,
  limited fighters are stuck at 50. By now they have 15+ fights on
  their record.
- At 38, the career arc is clear — you can read the fighter's ceiling
  from their attributes AND their record.

---

## 4. Why This Design Works

1. **Scouting matters.** If you could read potential from attributes
   at age 18, the Talent Hunter fantasy collapses. The hidden-potential
   + similar-young-attributes design forces the player to invest in
   scouting (Task 18) or take risks on unknown prospects.

2. **Career arcs are visible.** By prime (28-32), attributes correlate
   with potential — but by then the fighter has a track record. The
   player isn't "cheated" — they can read a veteran's ceiling from
   both their attributes AND their record.

3. **Training camps have meaning.** Camps push attributes toward
   potential. A limited-potential fighter (30) physically cannot
   become a 90-punch-power killer no matter how many camps they do.
   This makes camp investment decisions meaningful.

4. **ELO is separate from attributes.** A fighter can have great
   attributes but a mediocre ELO (underperformer) or mediocre
   attributes but a great ELO (overachiever). This produces realistic
   "eye test vs record" debates.

---

## 5. What the Player Sees (per CONVENTIONS §14)

The player does NOT see raw numbers in the UI. Everything passes
through the Interpretation Layer (Task 19, future):

| Raw Value | Player Sees |
|---|---|
| potential = 85 | (hidden — only revealed via scouting report) |
| punch_power = 78 | "devastous knockout power" |
| ELO = 1245 | "#3 ranked in the division" |
| career_health = 64 | "battling injuries, declining" |
| win_streak = 5 | "on a 5-fight win streak" |

For now (pre-Task 19), the DB stores raw numbers and the UI shows them
directly. Task 19 will retrofit the interpretation layer across all
systems.
