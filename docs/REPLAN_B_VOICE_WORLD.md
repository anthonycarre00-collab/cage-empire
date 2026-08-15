> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — REPLAN-B: Voice + World-Aliveness Analysis

> **Task ID:** REPLAN-B
> **Agent:** Voice + World-Aliveness Analysis (general-purpose)
> **Date:** 2026-08-19 (sim) / 2026-08-02 (real)
> **Mode:** RESEARCH + ANALYSIS ONLY. No code changes were made.
> **Audience:** Supervisor (user) + the next planning agent.
> **Live DB queried:** `data/cage_empire.db` (sim_clock: day 31, 2026-08-19)
> **Verdict in one sentence:** Voice failures and the dead world are the
> SAME problem — rival_ai exists in code but was never registered during
> the Aug-1 "unfreeze" run, so 30 sim-days produced 0 scheduled events,
> 0 signings, 0 ranking updates, and the headline_engine has been
> picking the same 3 fighters for 31 consecutive days because there is
> literally nothing else happening to write about.

---

## 0. Executive Summary

The supervisor's two complaints — (1) tabloid voice drift + repetitive
headlines, (2) the world is dead — are not two problems. They are the
upstream and downstream of the same single failure: **the rival-AI
subscriber was never wired into the event bus when the bulk-advance
script ran, so the world never generated the simulation activity the
interpretation layer is designed to translate.**

Concretely, against the live DB:

- **Voice (Claude §5 verification):**
  - Variant coverage: PASSES for `momentum`, `pressure`,
    `career_phase` (8/8 each, except `declining=7` and `very_high=5`
    due to small-N labels). FAILS for `legacy_state` (3 per label) and
    `narrative_family` (2–3 per label) — confirms Claude's audit.
  - Headline repetition: `"The prodigy turns heads again"`,
    `"Hiroki Nakamura is rising fast"`, `"Daniel Gonzalez is sliding
    fast"` — **each shown 31 times across 31 consecutive sim-days
    (2026-07-20 → 2026-08-19)**. Hard fail of §3.
  - Cache freshness: `engine_version='1.6.0'`, `last_built_date=
    '2026-08-19'`, `last_built_fighter_count=4450` — the 8-variant
    `_EXT` phrases ARE in the DB.
  - Tabloid clichés: 11 rows match Claude's §5.4 patterns
    (`%SCANDAL%`=7, `%stunning development%`=2, `%Storm:%`=4) —
    all live in production. The seed `SOURCE_TONE_PREFIX` dict at
    `news.py:120` is the upstream source; the suspension template at
    `news.py:2137` (`"{fighter} {type_phrase} in stunning development"`)
    is the other source.

- **World-aliveness:**
  - **0 scheduled events** across all 10 promotions (1,877 completed,
    0 upcoming, 0 past-due). Every promotion's `latest_event` is
    ≤ 2026-07-28.
  - **0 contract signings** since the world seed (all 312 contracts
    have `start_date='2026-07-20'` — the seed date itself).
  - **0 rankings updates** since 2026-08-01 (`MAX(updated_at)` is
    2026-08-01 23:31:25).
  - **0 title changes** since seed (all 48 active titles still held by
    the same fighter who held them at seed).
  - **0 new rivalries** since 2026-07-29 22:38:13 (all 93 are from the
    world-seed batch).
  - **0 new training camps** since seed (all 50 are pre-seeded with
    `start_date='2026-07-06'`).
  - **0 new suspensions** since 2026-07-15.
  - **0 finance transactions** since 2026-01-01 (pre-seed).
  - **0 fights since 2026-07-28** despite sim clock advancing to
    2026-08-19 (21 sim-days of empty calendar).
  - 82 news_items, 132 social_posts — ALL created in a 15-second
    window on 2026-08-01 23:31:10–25 (real time). None since.

- **Root cause (the smoking gun):**
  `scripts/run_sim_forward.py` (the Aug-1 batch-advance script that
  took the sim from day 1 to day 31) registers 16 modules on the event
  bus, but the list is:
  ```
  ["news", "social", "rivalries", "punditry", "morale",
   "suspensions", "agent_offers", "scouting", "training_svc",
   "injuries_svc", "finance_svc", "rivalries_svc", "retirement_svc",
   "hof_svc", "memory_svc", "contracts"]
  ```
  - **`rival_ai` is NOT in this list.** It is the only module that
    schedules events for non-player promotions. Without it, rival
    promotions sit on their rosters doing nothing.
  - 8 of the 16 listed modules (`training_svc`, `injuries_svc`,
    `finance_svc`, `rivalries_svc`, `retirement_svc`, `hof_svc`,
    `memory_svc`, `contracts`) live in `src/services/`, but the script
    only adds `src/` to `sys.path` — so `__import__("training_svc")`
    fails silently for all 8.
  - Also missing: `career_arc`, `show_rating`, `venues`, `save_load`,
    `player_settings`, `reputation`, `interpretation`, `rival_ai`.

The user's complaint that "the AI has failed completely in building an
'alive' world" is **literally correct**. The rival-AI code is fine; it
was just never plugged in during the bulk-advance.

---

## Part 1: Voice Enforcement Audit (per Claude's §5)

All queries were executed against `data/cage_empire.db` on 2026-08-19.
Outputs pasted verbatim.

### 5.1 — Variant coverage per label

#### 5.1a — momentum

```sql
SELECT SUBSTR(momentum,1,INSTR(momentum,'||')-1) AS label,
       COUNT(DISTINCT momentum) AS distinct_phrases,
       COUNT(*) AS fighters
FROM fighter_descriptors WHERE momentum IS NOT NULL
GROUP BY label ORDER BY fighters DESC;
```

```
label      | distinct_phrases | fighters
-----------+------------------+---------
stable     | 8                | 4377
falling    | 8                | 33
high       | 7                | 20
collapsing | 7                | 14
very_high  | 5                | 7
```

**Assessment vs §3 (≥8):** `stable` ✅ (4377 fighters covered, 8 phrases
— the mass of the roster is fine). `falling` ✅. `high` ❌ (7, 20
fighters). `collapsing` ❌ (7, 14 fighters). `very_high` ❌ (5, 7
fighters — but small N).

**Module verdict:** **PARTIAL PASS** — `stable` (98.3% of roster)
meets the bar; the four minority labels each miss by 1–3 variants.
This is consistent with `MOMENTUM_PHRASES_EXT` in
`context_engine.py:204-260` providing exactly 8 variants for every
label — but the DB shows only 5–7 distinct phrases per minority label
because RNG picked the same variants for the small N. Per-fighter RNG
is seeded by `fighter_id * 31 + 17`, so each fighter deterministically
gets the same phrase across daily passes — with only 7 fighters in
`very_high`, you can have at most 7 distinct phrases observed.

#### 5.1b — pressure

```sql
SELECT SUBSTR(pressure,1,INSTR(pressure,'||')-1) AS label,
       COUNT(DISTINCT pressure) AS distinct_phrases, COUNT(*) AS fighters
FROM fighter_descriptors WHERE pressure IS NOT NULL
GROUP BY label ORDER BY fighters DESC;
```

```
label    | distinct_phrases | fighters
---------+------------------+---------
moderate | 8                | 4138
minimal  | 8                | 200
high     | 8                | 113
```

**Module verdict:** **PASS** — all three labels at 8 variants. Matches
`PRESSURE_PHRASES_EXT` in `context_engine.py:262-299` (8 per label).

#### 5.1c — career_phase

```sql
SELECT SUBSTR(career_phase,1,INSTR(career_phase,'||')-1) AS label,
       COUNT(DISTINCT career_phase) AS distinct_phrases, COUNT(*) AS fighters
FROM fighter_descriptors WHERE career_phase IS NOT NULL
GROUP BY label ORDER BY fighters DESC;
```

```
label            | distinct_phrases | fighters
-----------------+------------------+---------
rising_contender | 8                | 3392
prospect         | 8                | 940
champion         | 8                | 48
declining        | 7                | 26
veteran          | 8                | 24
gatekeeper       | 8                | 21
```

**Module verdict:** **PARTIAL PASS** — 5 of 6 labels at 8. `declining`
sits at 7 (26 fighters, 8-variant bank, deterministic RNG → only 7
distinct picks observed). Minor gap.

#### 5.1d — narrative_family

```sql
SELECT SUBSTR(narrative_family,1,INSTR(narrative_family,'||')-1) AS label,
       COUNT(DISTINCT narrative_family) AS distinct_phrases, COUNT(*) AS fighters
FROM fighter_descriptors WHERE narrative_family IS NOT NULL
GROUP BY label ORDER BY fighters DESC;
```

```
label            | distinct_phrases | fighters
-----------------+------------------+---------
veteran          | 3                | 21
prodigy          | 2                | 7
cinderella_story | 2                | 3
```

**Module verdict:** **HARD FAIL** — every label has ≤3 variants.
`narrative_families.py:174-195` (`FAMILY_PHRASES`) defines exactly 3
variants per family. There is NO `_EXT` bank for narrative families
(compare: `context_engine` has `MOMENTUM_PHRASES_EXT`,
`PRESSURE_PHRASES_EXT`, `TRAJECTORY_PHRASES_EXT`; `career_phase_engine`
has `PHASE_PHRASES_EXT`; `legacy_engine` and `narrative_families` have
none). Claude's audit §1.4 flagged this for `legacy_engine` — the
identical gap exists for `narrative_families`.

**Also:** `fallen_champion` does NOT appear in the output at all —
**zero fighters** currently match the `fallen_champion` rule
(`career_phase=declining` AND `title_reigns>0` AND `momentum in
falling/collapsing`). The top_story priority order in
`headline_engine._generate_top_story` (lines 253–258) ranks
`fallen_champion` first — but since no fighter qualifies, the
headline always falls through to `prodigy`. This is why "The prodigy
turns heads again" has run 31 days straight (see §5.2).

#### 5.1e — legacy_state

```sql
SELECT SUBSTR(legacy_state,1,INSTR(legacy_state,'||')-1) AS label,
       COUNT(DISTINCT legacy_state) AS distinct_phrases, COUNT(*) AS fighters
FROM fighter_descriptors WHERE legacy_state IS NOT NULL
GROUP BY label ORDER BY fighters DESC;
```

```
label       | distinct_phrases | fighters
------------+------------------+---------
building    | 3                | 4427
established | 3                | 21
forgotten   | 2                | 2
legendary   | 1                | 1
```

**Module verdict:** **HARD FAIL** — confirms Claude's §3 table:
"`legacy_engine` `building` (99% of roster) — 3 — ❌ flagged in audit
§1.4, never implemented." `legacy_engine.py:160-181` (`LEGACY_PHRASES`)
defines exactly 3 variants per label. No `_EXT` bank exists. This is
the same gap Claude flagged; it has not been touched.

**Summary table (per Claude's §3 bar of ≥8):**

| Module                | Labels meeting ≥8 | Labels failing | Status |
|---|---|---|---|
| context_engine (momentum)  | 1/5 (stable) + 1/5 (falling) | very_high, high, collapsing | PARTIAL PASS (98.3% of roster covered) |
| context_engine (pressure)  | 3/3 | none | PASS |
| career_phase_engine        | 5/6 | declining (7) | PARTIAL PASS |
| narrative_families         | 0/4 | all (3 each) | FAIL — no _EXT bank |
| legacy_engine              | 0/4 | all (3 each) | FAIL — no _EXT bank, identical to gap Claude flagged |

### 5.2 — Headline repetition across days

```sql
SELECT headline_text, COUNT(*) AS times_shown,
       MIN(headline_date) AS first_seen, MAX(headline_date) AS last_seen
FROM daily_headlines GROUP BY headline_text
ORDER BY times_shown DESC LIMIT 15;
```

```
headline_text                           | times_shown | first_seen | last_seen
----------------------------------------+-------------+------------+----------
The prodigy turns heads again           | 31          | 2026-07-20 | 2026-08-19
Hiroki Nakamura is rising fast          | 31          | 2026-07-20 | 2026-08-19
Daniel Gonzalez is sliding fast         | 31          | 2026-07-20 | 2026-08-19
Samuel Hall stuns Steven Chavez         | 7           | 2026-07-22 | 2026-07-28
Alexander Russell stuns Charles Russell | 2           | 2026-07-29 | 2026-07-30
Jack Taylor stuns Silvio Guerra         | 1           | 2026-07-20 | 2026-07-20
Gregory Mendoza stuns Austin Rodriguez  | 1           | 2026-07-31 | 2026-07-31
Dmitry Komarov stuns Dmitry Ivanov      | 1           | 2026-07-21 | 2026-07-21
```

**Totals:** 105 daily_headlines rows, 8 distinct texts, 31 distinct
dates (2026-07-20 → 2026-08-19), sim_clock advanced 31 days.

**Per-type breakdown:**

```
headline_type     | rows | distinct_texts | distinct_dates
------------------+------+----------------+---------------
top_story         |  31  |  1             |  31
fastest_rising    |  31  |  1             |  31
biggest_fall      |  31  |  1             |  31
upset_of_week     |  12  |  5             |  12
```

**Module verdict:** **HARD FAIL** of §3's "Same literal headline for
the same subject on 2+ consecutive sim-days, when other qualifying
subjects exist: 0 (forbidden)."

Three headlines have run **31 consecutive sim-days**. Claude's
threshold is 2 days. This is 15× over the threshold.

**Why this is happening (root cause, from `headline_engine.py`):**

1. `_generate_top_story` (line 222) selects fighters by priority:
   `fallen_champion > prodigy > cinderella_story > veteran`. With
   `fallen_champion` having 0 qualifiers (see §5.1d above), the winner
   is always whichever `prodigy` has the lowest `fighter_id`. There are
   only 7 prodigies. The same one wins every day.

2. `_generate_fastest_rising` (line 408) uses the fallback chain
   `very_high+prospect → high+prospect → very_high`. Each query uses
   `ORDER BY fd.fighter_id ASC LIMIT 1` (line 509). There are 7
   `very_high` fighters; the same `fighter_id` wins daily. Output:
   `"Hiroki Nakamura is rising fast"` 31 days running.

3. `_generate_biggest_fall` (line 445) iterates `collapsing → falling`
   with the same `ORDER BY fighter_id ASC LIMIT 1`. 14 collapsing
   fighters; lowest `fighter_id` wins every day. Output:
   `"Daniel Gonzalez is sliding fast"` 31 days running.

4. Each family in `headline_engine.py` has exactly **ONE** template
   (e.g. line 287–293 for prodigy, line 432–437 for fastest_rising,
   line 458–464 for biggest_fall). Claude's §3 bar is ≥8 templates per
   `(headline_type, narrative_family)` pair. We have 1. Combined with
   the deterministic fighter pick, you get the same string for 31 days.

5. `_generate_upset_of_week` (line 319) varies because it queries
   `fight_history` for the last 7 days. With no fights since
   2026-07-28, **the last 12 upset_of_week headlines come from a
   shrinking pool of 7-day-old fights**. As the last fights age out of
   the 7-day window, this headline will start skipping days entirely
   (already happening: only 12 of 31 days have an upset row).

### 5.3 — Cache freshness

```sql
SELECT * FROM interpretation_cache_meta;
```

```
meta_id | engine_version | last_built_date | last_built_fighter_count | updated_at
--------+----------------+-----------------+--------------------------+--------------------
1       | 1.6.0          | 2026-08-19      | 4450                     | 2026-08-01 23:31:25
```

**Module verdict:** **PASS** for `engine_version` (`1.6.0` matches
`snapshot_cache.ENGINE_VERSION` and the live DB). `last_built_date`
reflects the sim clock (`2026-08-19`). `updated_at` reflects real
wall-clock (`2026-08-01 23:31:25`) — confirming the last daily pass
ran during the Aug-1 batch-advance script, and no further ticks have
fired since (otherwise `updated_at` would be more recent).

**Note:** the apparent contradiction between `last_built_date=
2026-08-19` and `updated_at=2026-08-01` is the smoking-gun for "the
sim was advanced 30 sim-days in a single real-time batch on Aug-1."
The cache was rebuilt at the end of each tick, so the final
`last_built_date` written was the final sim date. But the real-time
`updated_at` shows no writes since. This is consistent with the
world-aliveness findings in Part 2.

### 5.4 — Tabloid-cliché sweep

```sql
SELECT headline FROM news_items
WHERE headline LIKE '%SCANDAL%' OR headline LIKE '%stunning development%'
   OR headline LIKE '%Storm:%';
```

```
headline
------------------------------------------------------------------------
Social Storm: Murphy caught by commission testing in stunning development
Scandal rocks the division — Ortiz hit with behavior ban
SCANDAL: Flores fails drug test in stunning development
SCANDAL: Saito returns to active duty
SCANDAL: Cox returns to active duty
Social Storm: Sanders returns to active duty
SCANDAL: Legrand back from injury
SCANDAL: Vidal returns to active duty
Social Storm: Martinez back from injury
Social Storm: Martins returns to active duty
SCANDAL: Murray cleared to return
```

**Pattern counts (broader sweep):**

```
%SCANDAL%              → 7
%stunning development% → 2
%Storm:%               → 4
%SHOCK:%               → 0
%BOMBSHELL:%           → 3
%EXCLUSIVE:%           → 4
%BREAKING:%            → 0
```

**Module verdict:** **HARD FAIL**. 11 rows match Claude's specific
§5.4 patterns. Total tabloid-style prefixes in production:
SCANDAL(7) + Storm:(4) + BOMBSHELL:(3) + EXCLUSIVE:(4) = 18 rows
(some overlap, e.g. "Social Storm: Murphy caught by commission testing
in stunning development" hits both `Storm:` and `stunning development`).

Worse, 2 of these rows are clearance/cleared-to-return news items
("SCANDAL: Saito returns to active duty", "SCANDAL: Murray cleared to
return"). The tabloid `SCANDAL:` prefix is being applied to
**clearance** news (which should read as positive comebacks), not
just creation news. That's because `_apply_source_tone`
(`news.py:385-409`) unconditionally prepends the source's tone prefix
whenever the source is "The Cage Wire" — it doesn't know whether the
underlying story is scandalous or not.

**Two upstream sources of the tabloid pattern (both confirmed in code):**

1. **`_SOURCE_TONE_PREFIX` (`news.py:120-131`)** — `"The Cage Wire"`
   has `("SHOCK", "SCANDAL", "BOMBSHELL", "EXCLUSIVE", "CONTROVERSY")`
   as prefixes; `"Social Sphere"` has `(..., "Social Storm")`.
   `_apply_source_tone` (line 408) renders them as
   `f"{prefix.upper()}: {headline}"` — so any Cage Wire source
   produces `SCANDAL: ...`, `BOMBSHELL: ...`, etc. regardless of the
   underlying story.

2. **`_SUSPENSION_CREATE_HEADLINES` (`news.py:2131-2138`)** — the
   6th template is `"{fighter} {type_phrase} in stunning development"`.
   This is the literal source of the "stunning development" pattern
   Claude flagged.

### Part 1 summary

| Check | Module | Result | Threshold | Status |
|---|---|---|---|---|
| §5.1a momentum variants | context_engine | 8/8/5/7/7/8 | ≥8 per label | PARTIAL — `stable` (98% of roster) PASS; minority labels FAIL |
| §5.1b pressure variants | context_engine | 8/8/8 | ≥8 per label | PASS |
| §5.1c career_phase variants | career_phase_engine | 8/8/8/7/8/8 | ≥8 per label | PARTIAL — `declining` at 7 |
| §5.1d narrative_family variants | narrative_families | 3/2/2/0 labels | ≥8 per label | FAIL — no `_EXT` bank, max 3 |
| §5.1e legacy_state variants | legacy_engine | 3/3/2/1 | ≥8 per label | FAIL — no `_EXT` bank, max 3 |
| §5.2 headline repetition | headline_engine | 3 headlines × 31 days | 0 consecutive | FAIL — 15× over threshold |
| §5.3 cache freshness | snapshot_cache | engine_version 1.6.0 | matches code constant | PASS |
| §5.4 tabloid clichés | news.py | 11 rows match patterns | 0 rows | FAIL |

---

## Part 2: The "World Not Alive" Diagnosis (Issue 4)

### 2.1 What the world should be doing (per the user's brief)

The user's exact words: *"the player controlling the promotion is
expected to book events which is partly why no events appear but the
rival promotions should also be booking events/signing fighters etc or
our AI has failed completely in building an 'alive' world which should
be alive regardless of whether the player is influencing things."*

The implied contract: on every Advance Day, the world (as a system)
should evolve independently of the player. Specifically, rival
promotions should autonomously:

1. Schedule events (book fights, build cards, pick dates/venues)
2. Resolve scheduled events on their event_date (full-card resolution)
3. Sign free agents (react to roster gaps, weight-class needs)
4. Cut underperformers (release fighters on bad streaks)
5. Develop talent (assign training camps before scheduled fights)
6. Create/escalate/de-escalate rivalries
7. Book title fights (when #1 contender is clear)
8. Generate cross-promotion news (a title change in RFL should reach
   the player's news feed)
9. Update rankings (fighters move up/down based on results)

### 2.2 What the rival AI currently does (code-level audit)

`src/rival_ai.py` (547 lines) — the dedicated rival-AI module. Its
design is sound:

- Subscribes to `Events.TICK_ADVANCED` via `register_subscribers()`
  (line 529).
- On every tick: checks each rival promotion for scheduled events
  whose `event_date <= current_date` AND have unresolved fights, then
  resolves ALL fights on that event in one tick (single-night card
  resolution — `_resolve_event_card`, line 308).
- On weekly ticks (`current_day % 7 == 0`): for each rival promotion,
  if no scheduled event exists, calls `schedule_next_event()` with
  `weeks_out` derived from `ai_aggression` (low=6wk, med=4wk,
  high=2wk). 10% chance per week of signing a free agent, filtered by
  `ai_spending_style` (conservative/balanced/aggressive).
- Uses the SAME `schedule_next_event` / `resolve_next_fight` /
  `sign_free_agent` functions the player uses, so all event-bus
  subscribers (news, social, morale, finance, punditry) fire for rival
  fights too.
- NEVER touches `promotion_id=1` (the player's promotion).

**Verdict on code design:** the rival AI module is well-built. It
schedules, signs, and resolves. It does NOT cut underperformers, does
NOT create rivalries, does NOT book title fights explicitly (title
fights happen implicitly via `schedule_next_event` when a champion +
#1 contender are available). It does NOT do training-camp assignment
(camps are auto-created by `schedule_next_event` for each booked
fight — see `matchmaking.py:1142+`).

### 2.3 What the rival AI is ACTUALLY doing in the live DB

**Nothing.** Here's the proof.

#### Q1 — events per promotion

```sql
SELECT p.promotion_id, p.name, p.ai_aggression, p.ai_spending_style,
       COUNT(e.event_id) as events,
       SUM(CASE WHEN e.status='scheduled' THEN 1 ELSE 0 END) as scheduled,
       SUM(CASE WHEN e.status='completed' THEN 1 ELSE 0 END) as completed,
       SUM(CASE WHEN e.status='cancelled' THEN 1 ELSE 0 END) as cancelled,
       MIN(e.event_date) as earliest_event, MAX(e.event_date) as latest_event
FROM promotions p LEFT JOIN events e ON e.promotion_id = p.promotion_id
GROUP BY p.promotion_id ORDER BY events DESC;
```

```
promotion_id | name                       | ai_agg | style        | events | sched | compl | canc | earliest   | latest
-------------+----------------------------+--------+--------------+--------+-------+-------+------+------------+------------
1            | Alpha Combat Federation    | 30     | balanced     | 431    | 0     | 431   | 0    | 2015-01-03 | 2026-07-24
2            | Rival Fight League         | 50     | aggressive   | 345    | 0     | 345   | 0    | 2015-01-05 | 2026-07-28
3            | Pacific Rim Championship   | 45     | balanced     | 323    | 0     | 323   | 0    | 2015-01-20 | 2026-07-22
4            | European Fight Network     | 40     | conservative | 278    | 0     | 278   | 0    | 2015-01-10 | 2026-07-25
9            | Australian Outback Fights  | 50     | balanced     | 123    | 0     | 123   | 0    | 2015-01-13 | 2026-07-12
8            | Eastern Bloc Combat        | 55     | aggressive   | 112    | 0     | 112   | 0    | 2015-02-21 | 2026-07-22
6            | Mexican Boxing & Brawl     | 65     | aggressive   | 97     | 0     | 97    | 0    | 2015-01-01 | 2026-07-18
10           | French Savate Championship | 30     | conservative | 75     | 0     | 75    | 0    | 2015-03-05 | 2026-05-05
7            | Nordic Fight Nights        | 35     | conservative | 67     | 0     | 67    | 0    | 2015-03-19 | 2026-07-11
5            | South American Warriors    | 60     | aggressive   | 33     | 0     | 33    | 0    | 2017-01-27 | 2026-07-22
```

**Reading:**
- **0 scheduled events across ALL 10 promotions** (player included).
- The latest `event_date` for any promotion is 2026-07-28 (RFL).
- The sim clock is at 2026-08-19. **21 sim-days of empty calendar.**
- French Savate's latest event is 2026-05-05 (3+ sim-months silent).

#### Q2 — fighters per promotion

```sql
SELECT p.promotion_id, p.name, COUNT(f.fighter_id) as fighters,
       SUM(CASE WHEN f.is_active=1 AND f.is_retired=0 THEN 1 ELSE 0 END) as active
FROM promotions p LEFT JOIN fighters f ON f.current_promotion_id = p.promotion_id
GROUP BY p.promotion_id ORDER BY fighters DESC;
```

```
promotion_id | name                       | fighters | active
-------------+----------------------------+----------+-------
1            | Alpha Combat Federation    | 60       | 60
2            | Rival Fight League         | 46       | 46
3            | Pacific Rim Championship   | 45       | 45
4            | European Fight Network     | 44       | 44
5            | South American Warriors    | 21       | 21
9            | Australian Outback Fights  | 20       | 20
10           | French Savate Championship | 20       | 20
6            | Mexican Boxing & Brawl     | 19       | 19
7            | Nordic Fight Nights        | 19       | 19
8            | Eastern Bloc Combat        | 18       | 18
```

**Reading:** 312 active fighters across 10 promotions, 4,138 free
agents. Roster sizes are healthy. **But:** no fighter has been signed
or cut since seed (see Q3 below) — these are the seeded rosters, frozen.

#### Q3 — free agents + recent roster movement

```sql
SELECT COUNT(*) as total_fa,
       SUM(CASE WHEN f.updated_at > '2026-07-20' THEN 1 ELSE 0 END) as updated_since_seed,
       SUM(CASE WHEN f.updated_at > '2026-08-01' THEN 1 ELSE 0 END) as updated_since_aug1
FROM fighters f WHERE f.current_promotion_id IS NULL AND f.is_active = 1;
```

```
total_fa | updated_since_seed | updated_since_aug1
---------+--------------------+-------------------
4138     | 4138               | 173
```

**Reading:** All 4,138 free agents have been touched since seed, but
only 173 since Aug-1. The "since seed" count reflects the bulk
attribute-assignment script that ran during world-seed (assigning
fighter_attributes); it does NOT indicate signing activity.

**Contracts (the real signal):**

```
new contracts since seed: 312   range: 2026-07-20 → 2026-07-20
contracts with created_at > 2026-07-20: 981   range: 2025-07-22 → 2026-07-20
```

**Reading:** all 312 active contracts have `start_date='2026-07-20'`
(the seed date). The 981 with `created_at > 2026-07-20` is bulk
re-creation during seed (their `start_date`s are retroactive to
pre-seed dates). **Zero contracts created since seed for any new
signing.** Per-promotion breakdown confirms this — every promotion's
"new contracts since seed" exactly matches its seeded roster size.

#### Q4 — rivalries

```sql
SELECT COUNT(*) as total_rivalries,
       SUM(CASE WHEN rivalry_heat >= 50 THEN 1 ELSE 0 END) as high_heat,
       SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active_rivalries,
       MIN(created_at), MAX(created_at)
FROM rivalries;
```

```
total_rivalries | high_heat | active_rivalries | MIN(created_at)     | MAX(created_at)
----------------+-----------+------------------+---------------------+--------------------
93              | 93        | 93               | 2026-07-29 22:38:13 | 2026-07-29 22:38:13
```

**By type:**

```
rematch_hungry   → 40
title_rivalry    → 30
bad_blood        → 23
```

**Reading:** 93 rivalries exist, ALL created in a single 1-second
window during world-seed on 2026-07-29 22:38:13. **Zero rivalries
created or escalated since.** The `rivalries.py` module has a
`register_subscribers()` that DOES listen for `FIGHT_RESOLVED` to
create/escalate rivalries — and it WAS registered by
`run_sim_forward.py` (it's in the list at index 2) — but with no
fights since 2026-07-28, no new rivalries can be created.

#### Q5 — training camps

```sql
SELECT COUNT(*) as total_camps,
       SUM(CASE WHEN is_completed=1 THEN 1 ELSE 0 END) as completed,
       SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active,
       MIN(start_date), MAX(start_date)
FROM training_camps;
```

```
total_camps | completed | active | MIN(start_date) | MAX(start_date)
------------+-----------+--------+-----------------+----------------
50          | 50        | 0      | 2026-07-06      | 2026-07-06
```

**Reading:** 50 camps, all completed, all started 2026-07-06 (pre-
seed). **Zero camps active, zero created since seed.** This is the
expected downstream consequence of zero new events being scheduled —
`_create_training_camp` is called by `schedule_next_event` per booked
fight, so no events = no camps.

#### Q6 — suspensions, titles, fights, rankings, social

```
suspensions: 4 total (4 active), range 2026-07-15 → 2026-07-15 (pre-seed)
titles:      111 total, 48 currently held, 0 changed since seed
fight_history: 3598 total (range 2015-01-01 → 2026-07-28)
              72 fights since seed (2026-07-20), 0 since 2026-08-01
rankings:    669 rows, 669 distinct fighters, 0 updated since 2026-08-01
social_posts: 132 total, all created 2026-08-01 23:31:10–25
```

**Reading:** zero sim-side activity since 2026-07-28 (fights),
2026-08-01 (news/social/rankings/descriptors).

#### Q7 — scheduled (upcoming) events detail

```sql
SELECT e.event_id, p.name, e.event_name, e.event_date, e.status, e.event_type
FROM events e JOIN promotions p ON p.promotion_id = e.promotion_id
WHERE e.status = 'scheduled'
ORDER BY e.event_date ASC;
```

```
(no rows)
```

**Zero upcoming events. Zero past-due unresolved events. The events
table is completely idle.**

#### Q8 — latest dated activity in each table

```
events                       max(event_date)       = 2026-07-28
fight_history                max(event_date)       = 2026-07-28
news_items                   max(created_at)       = 2026-08-01 23:31:25
daily_headlines              max(headline_date)    = 2026-08-19
social_posts                 max(created_at)       = 2026-08-01 23:31:25
finance_transactions         max(transaction_date) = 2026-01-01
training_camps               max(start_date)       = 2026-07-06
contracts                    max(start_date)       = 2026-07-20
suspensions                  max(start_date)       = 2026-07-15
rivalries                    max(created_at)       = 2026-07-29 22:38:13
fighter_descriptors          max(updated_at)       = 2026-08-01 23:31:25
interpretation_cache_meta    max(last_built_date)  = 2026-08-19
```

**Reading:** every "activity" column either:
- stopped at the world-seed date (events/fights/camps/suspensions/
  rivalries/contracts/titles), OR
- was last written during the Aug-1 batch-advance script
  (news/social/descriptors), OR
- reflects the sim-clock-driven last-built date (daily_headlines,
  cache_meta).

### 2.4 The autonomous-behavior report card

| # | Behavior | Should rival promos do this? | Do they currently? | If not, why? | What's needed? |
|---|---|---|---|---|---|
| 1 | Event scheduling (book fights, build cards) | YES — autonomous weekly | **NO** | `rival_ai.py` was never registered on the bus during the Aug-1 bulk-advance; no TICK_ADVANCED listener exists for rival scheduling | Register `rival_ai.register_subscribers()` in the startup path AND in any bulk-advance script. Verify by checking `events.status='scheduled'` count > 0 after a weekly tick. |
| 2 | Event resolution (full-card on event_date) | YES — single-night | **NO** (no scheduled events to resolve) | Downstream of #1 — nothing scheduled, nothing to resolve | Fix #1; the resolve loop already exists in `_resolve_event_card` |
| 3 | Free agent signing | YES — weekly, 10%/promo, filtered by spending style | **NO** | Same as #1 — `rival_ai` not registered | Fix #1; the signing logic in `_maybe_sign_free_agent` is correct |
| 4 | Cutting underperformers | YES — release fighters on bad streaks | **NO** | **NOT IMPLEMENTED** — `rival_ai.py` has no cut logic. A rival promo with 50 fighters + 10 on losing streaks will never trim. | Add `_maybe_cut_underperformer(promo_id, rng)` to `rival_ai.py`. Trigger: weekly tick, 5%/promo chance, cut 1 fighter with momentum='collapsing' OR career_phase='declining' + age >= 36. Release sets `current_promotion_id=NULL`, ends contract. |
| 5 | Training camp assignment | YES — auto-created by `schedule_next_event` per booked fight | **NO** (no events scheduled) | Downstream of #1 | Fix #1 — camps flow automatically from `schedule_next_event` → `_create_training_camp` |
| 6 | Rivalry creation/escalation | YES — on `FIGHT_RESOLVED` (rematch_hungry, bad_blood, title_rivalry) | **NO** (no fights since 2026-07-28) | `rivalries.py` IS registered correctly, but needs fights to trigger | Fix #1 — fights feed rivalries automatically |
| 7 | Title fight booking | YES — implicit via `schedule_next_event._build_main_event` when champion + #1 contender available | **NO** (no events scheduled) | Downstream of #1 | Fix #1 — title fights book automatically when the main-event builder finds a champion + #1 contender |
| 8 | News generation (rival promos) | YES — `news.py` subscribers fire on `FIGHT_RESOLVED`, `TITLE_CHANGED`, `EVENT_COMPLETED` for any promotion | **NO new news since 2026-08-01** | `news.py` IS registered correctly, but no triggering events fire | Fix #1 — fight/title/event events auto-generate news via existing subscribers |
| 9 | Ranking changes | YES — rankings should update after every fight | **0 updates since 2026-08-01** | No `rankings` writer appears to subscribe to `FIGHT_RESOLVED`. The `rankings` table is populated by `world_phase2` seeding + (apparently) nothing else. **GAP:** there's no rankings-recalculation subscriber. | Add a `rankings.recalculate_after_fight(conn, event)` subscriber on `FIGHT_RESOLVED` that adjusts `rating` for the winner (+) and loser (-) based on result_type + opponent rating. Also a weekly top-N re-sort. |
| 10 | Cross-promotion news | YES — `news.generate_cross_promo_title_news` + `news.generate_cross_promo_fight_news` (line 3238, 3242) | **NO** (no rival title changes/fights to trigger) | Subscribers ARE registered. Need fights to fire. | Fix #1 — cross-promo news flows from rival fights |

### 2.5 What `tick_processor.run_tick` actually does

Per `tick_processor.py:1558-1690`, on every `run_tick(conn)`:

1. Advance `simulation_clock` by 1 day.
2. `_check_retirements(conn, current_date)` — birthday-gated,
   probability-based. Publishes `FIGHTER_RETIRED` + generates a
   regen replacement.
3. `_check_contract_expiry(conn, current_date)` — for contracts whose
   `end_date <= current_date`, set `current_promotion_id=NULL`,
   publish `CONTRACT_EXPIRED`.
4. `_check_injury_recovery(conn, current_date)` — for injuries whose
   `projected_return_date <= current_date`, clear `is_active=0`,
   publish `INJURY_RECOVERED`.
5. `_check_training_camps(conn, current_date)` — progress or complete
   active camps based on `[start_date, end_date]` window. Publishes
   `CAMP_COMPLETED` or `CAMP_INJURY`.
6. `_check_scouting_assignments(conn, current_date)` — generate
   reports for ready assignments.
7. Publish `TICK_ADVANCED` on the event bus.
8. `conn.commit()`.
9. **Post-commit:** `run_daily_interpretation_pass(conn)` — runs the
   interpretation engines (context, career_phase, narrative_families,
   legacy, headline) and writes to `fighter_descriptors` +
   `daily_headlines`.

**Subscribers that SHOULD fire on `TICK_ADVANCED`** (the bus dispatch
happens at step 7, before commit):

- `rival_ai._process_rival_promotions` — daily event resolution + weekly
  scheduling/signing **← THIS IS THE MISSING ONE**
- `news.generate_retirement_news` — polls for unwritten retirement news
- `news.generate_suspension_news` — polls for unwritten suspension news
- `news.prune_old_news` — weekly prune
- `news.generate_event_hype_news` — weekly hype for upcoming events
- `morale.*` subscribers — morale drift
- `agent_offers.*` — weekly offer generation
- Plus 13+ other subscribers across modules

The list of registered subscribers depends on which modules called
`register_subscribers()` at startup. The startup path differs between
the UI (`src/ui/app.py:228+` — registers ~25 modules) and the
bulk-advance script (`scripts/run_sim_forward.py:77-82` — registers
only 8 modules correctly; 8 are misnamed and silently fail).

---

## Part 3: The Interconnection — Why Voice Failures and a Dead World Are the Same Problem

The user's two complaints are not parallel problems. They are
upstream/downstream of a single root cause: **the simulation is not
running any meaningful events, so the interpretation layer has nothing
to interpret.**

### 3.1 The causal chain

```
rival_ai not registered
        ↓
no rival promotion schedules events
        ↓
no scheduled events exist anywhere (player too hasn't booked any)
        ↓
no event_date <= current_date triggers fire
        ↓
no fights get resolved
        ↓
no FIGHT_RESOLVED events on the bus
        ↓
news.py has nothing to write about (82 news items all from Aug-1 batch)
social.py has nothing to post about (132 posts all from Aug-1 batch)
rivalries.py can't create/escalate (no FIGHT_RESOLVED trigger)
rankings table frozen (no subscriber even if there were fights)
        ↓
no fighter's momentum/pressure/career_phase changes
        ↓
fighter_descriptors table is static (max updated_at = 2026-08-01)
        ↓
headline_engine._generate_top_story queries fighter_descriptors
        ↓
the same fighter_id (lowest in priority rank) wins daily
        ↓
the same single template per family is rendered
        ↓
"The prodigy turns heads again" — 31 days running
"Hiroki Nakamura is rising fast" — 31 days running
"Daniel Gonzalez is sliding fast" — 31 days running
```

### 3.2 The voice layer can't translate simulation into emotion
       IF THERE IS NO SIMULATION HAPPENING

This is the Soul doc's core thesis (§"Anticipation Is the Real
Dopamine"): "Something is always coming. Something is always
developing. Something is always unresolved. That's what keeps people
clicking Advance Day for another 500 hours."

The interpretation layer's purpose (Soul §"The Interpretation Layer's
Real Purpose") is: "Translate simulation into emotion. Raw: `Age 37,
Losses 4, Durability down 12%`. Meaning: `His best years may be
behind him.`"

But translation requires a source text. Right now there is no source
text. The "simulation" is a frozen screenshot. No fighter is fighting,
no champion is falling, no prospect is rising, no rivalry is brewing,
no signing is happening. The interpretation layer is asked to
translate an empty page.

That's why the same 3 headlines recur: the headline_engine queries the
SAME static fighter_descriptors table every day, finds the SAME
"most-extreme" fighter (lowest fighter_id in the priority rank), and
applies the SAME single template. The algorithm is deterministic; the
input hasn't changed; so the output is identical.

### 3.3 The tabloid-cliché problem is a SEPARATE failure mode

The tabloid clichés in `news.py` (`SCANDAL:`, `stunning development`,
`Social Storm:`) are NOT caused by the dead world. They're caused by:

1. `_SOURCE_TONE_PREFIX` (`news.py:120`) — a hardcoded dict that
   unconditionally prepends scandalous prefixes to ANY headline
   published by "The Cage Wire" or "Social Sphere" sources,
   regardless of whether the underlying story is scandalous. This
   applies to clearance news ("SCANDAL: Murray cleared to return" —
   not a scandal, a comeback), injury news, signing news, etc.

2. `_SUSPENSION_CREATE_HEADLINES` (`news.py:2137`) — the literal
   template `"{fighter} {type_phrase} in stunning development"` is
   stock clickbait phrasing.

These would be voice failures EVEN IF the world were alive. They are
a separate axis of drift — the news engine has slipped into a
tabloid register that nobody sanctioned in the Soul doc.

So: tabloid-cliché purge is a P0 voice fix; headline-engine subject
selection is a P0 voice fix; but BOTH are downstream of the world-
aliveness fix. Without the world running, even a perfect voice layer
would have nothing varied to say.

### 3.4 The 8-variant bank gap is a separate failure mode

The `legacy_engine` and `narrative_families` modules have only 3
variants per label. This is also NOT caused by the dead world — it's
an unfinished implementation. The `context_engine` and
`career_phase_engine` got `_EXT` banks; the other two didn't. Claude's
audit flagged this; nobody followed through.

Even if the world were alive and the headline engine rotated subjects,
the `legacy_state` and `narrative_family` columns would still show
only 3 distinct phrases per label across thousands of fighters. This
is a content-completeness gap, independent of the simulation state.

---

## Part 4: Revised Priority Order

Claude's `VOICE_ENFORCEMENT.md` §6 has 6 priorities. The user's
issue 4 ("world must be alive") is the upstream of all of them.
Revised order, with the world-aliveness fixes promoted to P0:

| Priority | Change | Effort | Impact | Dependency |
|---|---|---|---|---|
| **P0-a** | Fix `scripts/run_sim_forward.py`'s module list — add `rival_ai`, `career_arc`, `show_rating`, `venues`, `save_load`, `player_settings`, `reputation`, `interpretation`, and use `from services import X` for the 8 service modules (`training_svc`, `injuries_svc`, `finance_svc`, `rivalries_svc`, `retirement_svc`, `hof_svc`, `memory_svc`, `contracts`) | S (1–2 hrs) | **CRITICAL** — unblocks all downstream world activity. Without this, no other fix produces visible results. | None |
| **P0-b** | Verify `rival_ai.register_subscribers()` is called in the LIVE UI startup path (`src/ui/app.py:228+`) — code-grep confirms it IS called, but verify no exception is silently swallowed | S (30 min) | Critical — confirms the UI itself wires rival_ai correctly (so when the user clicks Advance Day, the world evolves) | None |
| **P0-c** | Run `advance_day(conn)` for ~14 sim-days with the corrected subscriber list and verify: ≥5 scheduled events exist, ≥1 rival fight resolved, ≥1 free agent signed by a rival, ≥1 new rivalry created | S (30 min) | Verifies P0-a/b worked; provides evidence for §5 re-run | P0-a, P0-b |
| **P0-d** | Purge tabloid-cliché templates from `news.py`: (1) remove `SCANDAL/SHOCK/BOMBSHELL/EXCLUSIVE/CONTROVERSY` from `_SOURCE_TONE_PREFIX["The Cage Wire"]` (or replace with neutral wire-service prefixes); (2) remove `Social Storm` from `Social Sphere` prefixes; (3) delete the `"{fighter} {type_phrase} in stunning development"` template from `_SUSPENSION_CREATE_HEADLINES` | S (1 hr) | Eliminates the 11 live cliché rows. Also eliminates future drift — the prefixes apply to ANY news from those sources, not just suspensions | None |
| **P0-e** | Fix `headline_engine` subject selection: (1) replace `ORDER BY fighter_id ASC LIMIT 1` with a deterministic hash of `(date, headline_type)` over the top-N candidates (≥5) so the subject rotates daily; (2) expand each family from 1 template to ≥8 templates (per Claude's §3 bar) | M (3–4 hrs) | Eliminates the 31-day-repetition failure. Top Story, Fastest Rising, Biggest Fall each rotate subjects + templates daily | None (independent of P0-a/b/c — but full benefit requires the world to be alive so the candidate pool changes) |
| **P0-f** | Add `_EXT`-style 8-variant banks to `legacy_engine` (`LEGACY_PHRASES_EXT`) and `narrative_families` (`FAMILY_PHRASES_EXT`). Bump `ENGINE_VERSION` to `1.7.0`. Re-run daily pass to rebuild cache | M (2–3 hrs) | Closes the smallest remaining gap from Claude's audit. Brings legacy_state + narrative_family to the §3 bar | None |
| **P0-g** | Add a rankings-recalculation subscriber on `FIGHT_RESOLVED` — `rankings.recalculate_after_fight(conn, event)`. Adjust winner rating (+/- based on result_type + opponent rating delta), weekly top-N re-sort | M (3–4 hrs) | Closes the "rankings frozen" gap. Required for the "Champions change hands, prospects rise + fall" aliveness requirement | P0-a/b/c |
| **P0-h** | Add rival-AI fighter cutting: `_maybe_cut_underperformer` in `rival_ai.py`. Weekly, 5%/promo chance, cut 1 fighter on a bad streak or aging veteran | S (1–2 hrs) | Closes one of the autonomous-behavior gaps (row 4 in §2.4). Adds visible roster movement | P0-a/b/c |
| **P1** | SHORT/LONG column split — per `UI_REDESIGN_INTERPRETATION_AUDIT.md` §6.2. Add `*_short` + `*_long` columns to `fighter_descriptors`; per-screen picker | L (8–10 hrs) | Stops Roster/Free Agents from showing identical text per row | P0-f |
| **P2** | Move phrase banks to `interpretation_phrases` DB table — content-editable without redeploys | L (1–2 days) | Operational improvement; not a voice-quality fix | P0-f |

### 4.1 Rationale for the re-ordering

Claude's order: P0 tabloid purge → P0 headline engine → P0 legacy
_EXT → P1 investigate events gap → P1 SHORT/LONG split → P2 phrase
table.

My order promotes the "investigate events gap" (Claude's P1) to
**P0-a/b/c**, because:

1. The user's exact words make world-aliveness a co-equal priority
   with voice enforcement.
2. Without the world running, even a perfect voice layer produces
   nothing varied (the candidate pool is static; the same fighter
   wins daily no matter how the templates rotate).
3. The fix is small (1–2 hrs to fix `run_sim_forward.py`'s module
   list + verify UI path) and the payoff is enormous (rival
   promotions start booking events, the news feed fills with
   variety, rankings move, rivalries brew).

The tabloid purge (P0-d), headline-engine fix (P0-e), and
legacy_EXT expansion (P0-f) are kept at P0 — they're independent
voice fixes that would be needed even if the world were alive. They
can proceed in parallel with P0-a/b/c.

P0-g (rankings) and P0-h (cuts) are added — they're autonomous-
behaviors that the user implicitly expects ("signing fighters etc")
and that the rival AI doesn't currently do.

---

## Part 5: The "Alive World" Specification

This becomes the build target for the world-AI work. Every item is
verifiable by direct DB query.

### 5.1 Per-tick activity contract

On every `advance_day(conn)` call (the user clicks "Advance Day"):

| # | Behavior | Frequency | Target count | Verification query |
|---|---|---|---|---|
| 1 | Each rival promotion (9 of them) evaluates: do I have a scheduled event? | every tick | n/a (guard clause) | `SELECT promotion_id, COUNT(*) FROM events WHERE status='scheduled' GROUP BY promotion_id` |
| 2 | Each rival promotion with no scheduled event has a chance to schedule one | weekly tick (current_day % 7 == 0) | avg 0.5–1 new scheduled events per rival per week (depends on ai_aggression) | `SELECT COUNT(*) FROM events WHERE status='scheduled' AND created_at > ?` |
| 3 | Each scheduled event whose `event_date <= current_date` resolves ALL its fights in one tick | every tick | 100% of due events resolve on their event_date | `SELECT COUNT(*) FROM events WHERE status='scheduled' AND event_date < current_date` (should be 0 — none past due) |
| 4 | Each rival promotion has a 10% chance to sign a free agent (if roster < 50) | weekly tick | ~0.8 signings per sim-week across all rivals | `SELECT COUNT(*) FROM contracts WHERE start_date >= ? AND promotion_id != 1` |
| 5 | Each rival promotion has a 5% chance to cut an underperformer | weekly tick | ~0.4 cuts per sim-week | `SELECT COUNT(*) FROM fighters WHERE current_promotion_id IS NULL AND updated_at >= ?` (cut fighters re-enter FA pool) |
| 6 | Rivalries create/escalate on `FIGHT_RESOLVED` | event-driven | ~1–3 per sim-week | `SELECT COUNT(*) FROM rivalries WHERE created_at >= ?` |
| 7 | Training camps auto-create per booked fight | event-driven (via `schedule_next_event`) | 5–13 per event scheduled | `SELECT COUNT(*) FROM training_camps WHERE created_at >= ?` |
| 8 | Training camps progress/complete on tick | every tick | 100% of camps in window | `SELECT COUNT(*) FROM training_camps WHERE is_completed=1 AND end_date >= ?` |
| 9 | News items generate across all promotions | event-driven | 5–15 per sim-week across all promotions | `SELECT COUNT(*) FROM news_items WHERE created_at >= ?` |
| 10 | Rankings update after every fight | event-driven | 2 rows per fight (winner + loser) | `SELECT COUNT(*) FROM rankings WHERE updated_at >= ?` |
| 11 | Daily headlines regenerate from fresh `fighter_descriptors` | daily (post-commit) | 4 headlines per day, ≥3 distinct texts per headline_type per week | `SELECT headline_type, COUNT(DISTINCT headline_text) FROM daily_headlines WHERE headline_date >= date('now', '-7 days') GROUP BY 1` |
| 12 | Cross-promo news fires on rival title changes + rival big upsets | event-driven | 1–3 per sim-month | `SELECT COUNT(*) FROM news_items WHERE topic='inter_promo_callout' AND created_at >= ?` |

### 5.2 Player-visible activity contract

The player should SEE the world's activity via:

1. **News Feed** — shows rival promotion events + signings + title
   changes. Never empty for more than 1–2 sim-days. Verification:
   `SELECT COUNT(*) FROM news_items WHERE created_at >= date('now',
   '-3 days')` ≥ 3.

2. **Dashboard "Recent Results"** — shows completed events from ALL
   promotions (not just the player's). Verification: a query for
   recent completed events returns ≥3 rows from ≥2 distinct
   promotions in the last 7 sim-days.

3. **Rival Promotions screen** — shows each rival's: next scheduled
   event (date + main event), recent results, roster count, recent
   signings/cuts. Verification: `SELECT p.name, e.event_date,
   e.event_name FROM promotions p LEFT JOIN events e ON
   e.promotion_id=p.promotion_id AND e.status='scheduled' WHERE
   p.promotion_id != 1` returns ≥3 rows with non-NULL event_date.

4. **Fighter Watch cards** — show fighters whose momentum changed
   due to rival-promo fights (not just the player's). Verification:
   `SELECT fighter_id, momentum FROM fighter_descriptors WHERE
   updated_at >= date('now', '-7 days')` returns ≥20 rows of which
   ≥50% belong to fighters on rival promotions.

5. **Next Event card** — shows the player's next scheduled event
   with countdown. If the player hasn't booked one, shows "no
   upcoming event" + a one-tap CTA. (This is the only place the
   player is responsible for booking — everything else is autonomous.)

### 5.3 "30 days without player action" contract

If the player advances 30 sim-days without booking a single event:

- **10–20 events happen across all rival promotions** (9 rivals ×
  avg 1.5 events/month = ~14). Verification: `SELECT COUNT(*) FROM
  events WHERE status='completed' AND event_date >= date('now',
  '-30 days') AND promotion_id != 1` ≥ 10.
- **Champions change hands** — at least 1–2 title changes per
  sim-month. Verification: `SELECT COUNT(*) FROM titles WHERE
  champion_since_date >= date('now', '-30 days')` ≥ 1.
- **Prospects rise + fall** — ≥10 fighters change momentum band
  (e.g., stable → high, falling → collapsing). Verification:
  `SELECT COUNT(DISTINCT fighter_id) FROM fighter_descriptors WHERE
  updated_at >= date('now', '-30 days')` ≥ 50.
- **Rivalries brew + explode** — ≥3 new rivalries, ≥1 with heat ≥80.
  Verification: `SELECT COUNT(*) FROM rivalries WHERE created_at >=
  date('now', '-30 days')` ≥ 3.
- **News feed is never empty** — ≥30 news items per sim-month
  across all promotions. Verification: `SELECT COUNT(*) FROM
  news_items WHERE created_at >= date('now', '-30 days')` ≥ 30.
- **Daily headlines rotate** — ≥3 distinct texts per headline_type
  per week. Verification: §5.2 query (no headline text shown >3
  consecutive days).

### 5.4 What an "alive world" feels like

The player clicks Advance Day. They see:

- RFL just booked a card for next month — main event: their
  featherweight champ vs the #1 contender.
- Pacific Rim signed a free agent the player was scouting — a 22yo
  prospect with potential 78.
- European Fight Network cut a 38yo veteran on a 4-loss streak.
- A bad-blood rivalry in Eastern Bloc Combat escalated from heat 40
  to heat 75 after a controversial decision.
- The weekly headlines rotate: "The prodigy turns heads again" on
  Monday, "A new contender emerges from RFL" on Wednesday, "Veteran
  cuts spark retirement rumors" on Friday.
- The player's Roster screen shows 3 of their fighters with changed
  momentum (one rose, one fell) — not because of the player's
  booking, but because the simulation moved.

This is the contract the Soul doc commits to. None of it currently
happens.

---

## Part 6: Implementation Approach (high-level, no code)

### 6.1 P0-a — Fix `run_sim_forward.py`'s module list

**Problem:** The script's `register_modules` list at line 77–82 is
missing `rival_ai` and uses top-level names for 8 modules that live
in `src/services/`. The `__import__("training_svc")` calls fail
silently due to the `except ImportError: pass` clause.

**Approach:**
1. Replace the list with the canonical startup registration sequence
   (mirror what `src/ui/app.py:228+` does).
2. For service modules, either:
   - Add `src/services/` to `sys.path`, OR
   - Use `__import__("services.training_svc", fromlist=["training_svc"])`.
3. Add `rival_ai`, `career_arc`, `show_rating`, `venues`, `save_load`,
   `player_settings`, `reputation`, `interpretation` to the list.
4. Replace the silent `except ImportError: pass` with a logged warning
   so missing modules are visible.
5. After running, verify by querying: `SELECT COUNT(*) FROM events
   WHERE status='scheduled'` ≥ 1 after 7 sim-days.

**Files touched:** `scripts/run_sim_forward.py` only.

### 6.2 P0-b — Verify UI startup path

**Problem:** `src/ui/app.py:238` does call
`from rival_ai import register_subscribers as _register_rival_ai;
_register_rival_ai()` — but it's wrapped in `try/except ImportError:
pass`. If `rival_ai.py` exists but throws on import (e.g., due to a
circular import or missing dependency), the failure is silent.

**Approach:**
1. Verify by running: `python3 -c "from src.rival_ai import
   register_subscribers; register_subscribers()"` and check no
   exception is raised.
2. Add a startup log line in `src/ui/app.py` confirming each
   subscriber module was registered (replace the silent `except
   ImportError: pass` with `except ImportError as e: print(f"WARN:
   {mod} not registered: {e}")`).
3. Confirm by inspecting the bus's subscriber list after App init:
   `from event_bus import get_bus; print(len(get_bus()._subs.get(
   'TICK_ADVANCED', [])))` should be ≥10.

**Files touched:** `src/ui/app.py` (logging only — no behavior
change).

### 6.3 P0-c — Verify world wakes up

**Approach:**
1. After P0-a, run: `python3 scripts/run_sim_forward.py 14`
2. Run the diagnostic queries from Part 2 (Q1, Q3, Q4, Q5, Q7) and
   confirm:
   - `SELECT COUNT(*) FROM events WHERE status='scheduled'` ≥ 3
   - `SELECT COUNT(*) FROM contracts WHERE start_date > '2026-08-19'`
     ≥ 1
   - `SELECT COUNT(*) FROM rivalries WHERE created_at > '2026-08-19'`
     ≥ 1
   - `SELECT COUNT(*) FROM news_items WHERE created_at >
     '2026-08-19'` ≥ 5
3. If any of these return 0, debug the relevant subscriber.

**Files touched:** None (verification only).

### 6.4 P0-d — Tabloid-cliché purge in `news.py`

**Three changes:**

1. **`_SOURCE_TONE_PREFIX` (line 120)** — replace the scandalous
   prefix tuples with neutral wire-service prefixes OR remove the
   prefix mechanism entirely for "The Cage Wire" / "Social Sphere"
   (set to `None`, matching "System Feed" + "CAGE Wire"). The Soul
   doc's reference phrases ("That kid I found in Mexico. Nobody
   wanted him. He became a champion.") are NOT tabloid — they're
   promoter-flavored. Tabloid prefixes are an uninvited register.

   Suggested replacement (preserving source differentiation without
   tabloid register):
   - "The Cage Wire" → `None` (neutral wire service)
   - "Social Sphere" → `("Buzzing", "Trending", "Going Viral")`
     (drop `"Feeds Lit"`, `"Social Storm"` — the latter is what
     produces the `Storm:` pattern)
   - "MMA Analytica" → keep as-is (analytical prefixes are fine)
   - "The Pundit's Desk" → keep as-is

2. **`_SUSPENSION_CREATE_HEADLINES` (line 2131)** — delete the 6th
   template `"{fighter} {type_phrase} in stunning development"`.
   Replace with a voice-appropriate alternative, e.g.:
   - `"{fighter} {type_phrase} — the commission came down hard"`
   - `"The suspension lands on {fighter}"`
   - `"{fighter} faces the music after {type_phrase}"`

3. **Apply `_apply_source_tone` selectively** — currently every
   news item gets the source's tone prefix. Consider applying it
   ONLY to items where the source's tone is appropriate (e.g., skip
   the prefix for clearance/return news, which should read as
   comebacks not scandals).

**Files touched:** `src/news.py` only.

**Verification:** Re-run §5.4 query — should return 0 rows.

### 6.5 P0-e — Headline engine subject selection + template expansion

**Problem (root cause from code):**
- `_generate_top_story` (line 222): queries all fighters with a
  non-NULL `narrative_family`, picks the one with the lowest
  `(priority_rank, fighter_id)`. Same fighter wins daily.
- `_generate_fastest_rising` (line 408) and `_generate_biggest_fall`
  (line 445): `ORDER BY fd.fighter_id ASC LIMIT 1` in
  `_find_fighter_by_labels` (line 509). Same fighter wins daily.
- Each family has exactly 1 template (e.g., line 287–293 for prodigy).

**Approach:**

1. **Subject rotation** — replace the deterministic-lowest-fighter_id
   pick with a deterministic daily rotation over the top-N candidates.

   For `_generate_top_story`:
   - Fetch ALL fighters matching the priority-1 family (e.g., all
     prodigies). If 0, fall through to priority-2, etc.
   - Compute a daily index: `idx = hash((current_date, headline_type))
     % len(candidates)`. Sort candidates by `fighter_id` for
     deterministic order, then pick `candidates[idx]`.
   - Same fighter can be picked again after exhausting the rotation —
     but only after every other candidate has been picked once.

   For `_generate_fastest_rising` and `_generate_biggest_fall`:
   - Same approach: fetch all qualifiers, pick by daily-hash index.

2. **Template expansion** — for each family in
   `_generate_top_story`, expand from 1 template to ≥8. Follow the
   voice reference phrases in `VOICE_ENFORCEMENT.md` §1.

   Example for `prodigy` (currently 1 template: "The prodigy turns
   heads again"). Add 7 more:
   - `"The wunderkind keeps proving the hype is real"`
   - `"Another night, another statement from the division's brightest
     young talent"`
   - `"The prospect era is over — the prodigy has arrived"`
   - `"He's not a prospect anymore. He's the future, and the future
     is now"`
   - `"Scouts whisper his name. Opponents dread it. The prodigy
     rolls on"`
   - `"The kind of start that careers are built on"`
   - `"The division's next superstar is making his case, week by
     week"`

   Same pattern for `veteran`, `cinderella_story`, `fallen_champion`
   (note: `fallen_champion` currently has 0 qualifiers — fix the
   label rule OR lower the threshold, so this family activates).

3. **For `_generate_fastest_rising` / `_generate_biggest_fall`** —
   expand from 1 template each to ≥8. Currently the template is
   hardcoded with `{name}`. Add 7 more variants per type.

**Files touched:** `src/interpretation/headline_engine.py` only.

**Verification:** Re-run §5.2 query — no headline should appear on
more than 3 consecutive days.

### 6.6 P0-f — Legacy + narrative_families `_EXT` banks

**Problem:** `legacy_engine.LEGACY_PHRASES` (line 160) and
`narrative_families.FAMILY_PHRASES` (line 174) have 3 variants per
label. The other interpretation engines (`context_engine`,
`career_phase_engine`) have `_EXT` banks with 8 variants.

**Approach:**
1. Add `LEGACY_PHRASES_EXT` to `legacy_engine.py` — 8 variants per
   label (5 new per label, following the context_engine pattern).
2. Add `FAMILY_PHRASES_EXT` to `narrative_families.py` — 8 variants
   per family (5 new per family).
3. Add `get_legacy_phrase_ext` / `get_family_phrase_ext` pickers that
   draw from the `_EXT` banks (mirror `get_momentum_phrase_ext` in
   `context_engine.py:447-463`).
4. Update `compute_all_legacies` and `compute_all_families` to use
   the `_EXT` pickers in the cache-write path (same pattern as
   `context_engine`).
5. Bump `snapshot_cache.ENGINE_VERSION` from `'1.6.0'` to `'1.7.0'`.
6. The next `advance_day` call will trigger the cache rebuild (the
   version mismatch triggers `run_daily_interpretation_pass` to
   rebuild `fighter_descriptors`).

**Files touched:** `src/interpretation/legacy_engine.py`,
`src/interpretation/narrative_families.py`,
`src/interpretation/snapshot_cache.py` (ENGINE_VERSION bump).

**Verification:** Re-run §5.1d and §5.1e queries — every label
should show ≥8 distinct phrases.

### 6.7 P0-g — Rankings recalculation subscriber

**Problem:** The `rankings` table has 669 rows, 0 updated since
2026-08-01. There is no subscriber that recalculates ratings after a
fight.

**Approach:**
1. Add `rankings.recalculate_after_fight(conn, event)` — subscribes
   to `FIGHT_RESOLVED`.
2. On each fight: adjust winner's `rating` (+small delta based on
   opponent rating + result_type — e.g., +5 for decision, +10 for
   KO/sub over a higher-rated opponent), loser's `rating` (-delta).
3. Add `rankings.weekly_resort(conn, event)` — subscribes to
   `TICK_ADVANCED` on weekly ticks. Re-sorts fighters within each
   weight class by `rating` DESC, updates `rank` column.
4. Optional: add a "rankings movement" news item when a fighter
   moves up ≥3 spots in a week (e.g., "Hiroki Nakamura surges into
   the top 5").

**Files touched:** `src/rankings.py` (new module or extend existing)
+ `src/ui/app.py` / `scripts/run_sim_forward.py` (register).

**Verification:** After 7 sim-days with fights,
`SELECT COUNT(*) FROM rankings WHERE updated_at >= date('now',
'-7 days')` ≥ 10.

### 6.8 P0-h — Rival-AI fighter cutting

**Problem:** `rival_ai.py` has signing logic but no cutting logic.
A rival promotion's roster can only grow (capped at 50), never trim.

**Approach:**
1. Add `_maybe_cut_underperformer(conn, promotion_id, rng)` to
   `rival_ai.py`.
2. Trigger: weekly tick, 5% chance per rival promotion.
3. Criteria: pick a fighter on the roster with `momentum` in
   (`collapsing`, `falling`) OR (`career_phase` = `declining` AND
   `age` >= 36). Lowest `fighter_id` wins (deterministic).
4. Action: set `fighters.current_promotion_id = NULL`, end the
   contract (set `contracts.end_date = current_date`,
   `contracts.status = 'terminated'`).
5. Publish `FIGHTER_CUT` event (new event type — add to
   `event_bus.Events`).
6. Add `news.generate_fighter_cut_news` subscriber — writes a
   voice-appropriate news item ("Pacific Rim parts ways with the
   veteran", "RFL cuts ties with the struggling contender").

**Files touched:** `src/rival_ai.py` (add `_maybe_cut_underperformer`),
`src/event_bus.py` (add `FIGHTER_CUT` event), `src/news.py` (add
`generate_fighter_cut_news` subscriber), `src/ui/app.py` (register).

**Verification:** After 30 sim-days, `SELECT COUNT(*) FROM fighters
WHERE current_promotion_id IS NULL AND updated_at >= date('now',
'-30 days')` ≥ 5 (new cuts beyond the existing free agent pool).

---

## Part 7: The Single Most Important Next Action

**Fix `scripts/run_sim_forward.py`'s module list (P0-a).**

It is the smallest fix (1–2 hours), it is the upstream of every other
world-aliveness issue, and without it, no other fix produces visible
results. Specifically:

- Add `"rival_ai"` to the `register_modules` list (this is the
  critical missing entry).
- Add `"career_arc"`, `"show_rating"`, `"venues"`, `"save_load"`,
  `"player_settings"`, `"reputation"`, `"interpretation"`.
- For the 8 service modules (`training_svc`, `injuries_svc`,
  `finance_svc`, `rivalries_svc`, `retirement_svc`, `hof_svc`,
  `memory_svc`, `contracts`), fix the import path — either add
  `src/services/` to `sys.path` or use
  `__import__("services.training_svc", fromlist=["training_svc"])`.
- Replace the silent `except ImportError: pass` with a logged
  warning so future drift is visible.

After this fix, run `python3 scripts/run_sim_forward.py 14` and
verify the diagnostic queries in §2 return non-zero counts. The
world will start producing events, fights, signings, news,
rankings movement, and (downstream) varied headlines.

This single fix unlocks the entire "alive world" contract. Every
other P0 item (tabloid purge, headline engine, legacy _EXT,
rankings, cuts) can proceed in parallel — but they all assume the
world is running. Without P0-a, they're polishing a screenshot of
an empty room.

---

## Appendix A — Files Read in Full

1. `/home/z/my-project/upload/VOICE_ENFORCEMENT.md` (188 lines)
2. `/home/z/my-project/cage_empire/docs/REPLAN_GAP_ANALYSIS.md` (668 lines)
3. `/home/z/my-project/cage_empire/docs/REPLAN_RESET.md` (427 lines)
4. `/home/z/my-project/cage_empire/docs/CAGE_EMPIRE_SOUL.md` (149 lines)
5. `/home/z/my-project/cage_empire/src/interpretation/headline_engine.py` (570 lines)
6. `/home/z/my-project/cage_empire/src/interpretation/legacy_engine.py` (498 lines)
7. `/home/z/my-project/cage_empire/src/rival_ai.py` (547 lines)
8. `/home/z/my-project/cage_empire/src/services/matchmaking.py` (1,492 lines, key sections)
9. `/home/z/my-project/cage_empire/src/tick_processor.py` (1,698 lines, key sections)
10. `/home/z/my-project/cage_empire/src/services/clock.py` (64 lines)
11. `/home/z/my-project/cage_empire/src/news.py` (3,245 lines, key sections)
12. `/home/z/my-project/cage_empire/src/interpretation/__init__.py` (219 lines)
13. `/home/z/my-project/cage_empire/src/interpretation/context_engine.py` (key sections)
14. `/home/z/my-project/cage_empire/src/interpretation/narrative_families.py` (key sections)
15. `/home/z/my-project/cage_empire/scripts/run_sim_forward.py` (178 lines)
16. `/home/z/my-project/cage_empire/src/app.py` (key sections)
17. `/home/z/my-project/cage_empire/src/ui/app.py` (key sections)

## Appendix B — SQL Queries Executed

All queries were executed against `data/cage_empire.db` (sim_clock:
day 31, current_date 2026-08-19). Outputs pasted verbatim in Part 1
and Part 2.

- §5.1a–e: variant coverage per label (momentum, pressure,
  career_phase, narrative_family, legacy_state)
- §5.2: headline repetition across days (top 15 + per-type breakdown)
- §5.3: interpretation_cache_meta (full row)
- §5.4: tabloid-cliché sweep + broader pattern counts
- Q1: events per promotion (with status counts + date range)
- Q2: fighters per promotion
- Q3: free agents + recent changes + contracts by promotion
- Q4: rivalries state + by type
- Q5: training camps state
- Q6: suspensions state
- Q7: scheduled (upcoming) events detail (returned 0 rows)
- Q8: recent completed events
- Q9: latest dated activity in each major table
- Plus schema introspection for: rivalries, training_camps, events,
  promotions, titles, contracts

## Appendix C — Brutal Honest Assessment

The user is correct: "our AI has failed completely in building an
'alive' world." The code is mostly fine — `rival_ai.py` is well-
designed, `schedule_next_event` is robust, the event bus is properly
wired. The failure is operational: the bulk-advance script that was
supposed to "unfreeze the world" on Aug-1 didn't register the rival
AI subscriber (or 8 of the 16 service subscribers it claimed to
register). The script ran 30 sim-days of empty ticks. The world
stayed dead.

The voice failures are real but secondary. The 31-day headline
repetition, the 11 tabloid-cliché rows, the 3-variant legacy bank —
all of these would still need fixing even if the world were alive.
But they would be fixing a TRANSLATION problem (the interpretation
layer mistranslating rich simulation into thin prose), not a
CONTENT-ABSENCE problem (the interpretation layer translating
nothing into the same nothing, daily).

Fix the world first. Then the voice fixes have something to bite
into. The Soul doc's core thesis — "anticipation is the real
dopamine" — requires something to be anticipated. Right now, there
is nothing on the calendar, nothing brewing, nothing developing,
nothing unresolved. The dopamine loop is broken at the source.

---

*End of REPLAN-B analysis. Awaits supervisor sign-off before any
coding begins.*
