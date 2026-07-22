# CAGE EMPIRE — World Seed Analysis & Plan

> **Status:** Planning document. No coding until Task 31 execution.
> **Source:** User-provided "world seed suggestions.txt" from external AI advisor.
> **Last revised:** 2026-07-22.

---

## 1. Analysis of the External Advisor's Recommendations

### What the advisor got right

1. **Scale targets are sensible.** The revised recommendation (20 nations, 60 regions, 150 cities, 300 gyms, 4,000 fighters) is realistic for an indie game. The original "25 nations, 400 cities, 500 gyms" was over-scoped — diminishing returns set in fast.

2. **"Fighters are the actual content."** This aligns perfectly with our Soul document: "The player does not collect fighters. The player collects stories." The world data (nations, cities) exists to support the fighters, not the other way around.

3. **Career histories > geography.** The advisor correctly identifies that players remember "Former Lightweight Champion, lost belt to Carlos Mendes, moved to Welterweight, went 1-4 after injury" — not "Born in Springfield 17." This aligns with our Design Law (§13) — stories, not spreadsheets.

4. **Gym identity matters.** "Black River MMA — Wrestlers, Tough sparring, Injury prone" is a story. Our gyms table already has `culture_tone`, `facility_quality`, `medical_support`, `sparring_depth`, `development_focus` — these columns support this vision. The gameworld seed should give gyms distinct personalities.

5. **Fighter generations are the biggest missing system.** After 10 years of sim time, Generation 1 retires, Generation 2 emerges, former champions become coaches, their sons appear. Our regen engine (Task 14) + memory resurfacing (pre-B1 fixes) + regen_lineage table already support this — but only for the retirement→replacement cycle. The advisor's vision of "former champions become coaches" and "their sons appear" needs future work (gym staff from retired fighters, lineage-based name generation).

6. **Memory resurfacing is high ROI.** "Lost title fight 6 years ago, former training partners, shared amateur rivalry, two previous fights, coach left gym — now every fight has context." This aligns with our decision to make memory resurfacing champion-only (pre-B1 fix) and to handle broader memory via the news engine (Task 23) and voice layer (Task 19).

7. **Phase ordering is correct.** Nations → Regions → Cities → Gyms → Fighters → Bios/Rivalries → Memory/Regens. This matches our execution order: the world infrastructure must exist before fighters can be generated into it.

### What needs modification for CAGE EMPIRE

1. **Name pools need to be per-region, not per-nation.** The advisor suggests "200-500 first names per nation." Our current name_pools table has a `region` column (currently NULL for all entries). The seed should populate region-specific names — a Brazilian fighter should have Brazilian names, not generic English ones. This means the name_pools table needs significant expansion (from 96 to ~2,000-3,000 entries, tagged by region/nation).

2. **3,500-4,000 fighters is the right target** but they need:
   - Full 25-attribute blocks (from fighter_gen.py, archetype-biased)
   - Full 20-personality blocks (archetype-biased)
   - Physical attributes (height, reach, stance, handedness)
   - Potential values (10% elite, 30% solid, 60% limited)
   - Career histories (records, title reigns, injuries, rivalries)
   - Rankings (ELO ratings reflecting their career histories)
   - Contracts (active/expired/free agent)
   - Fight histories (past fights with results, beat data for recent ones)

3. **Career histories are the hard part.** Generating 4,000 fighters with attributes is straightforward (fighter_gen.py already does this). Generating believable career histories — records that make sense, title reigns, rivalries, injuries — requires simulating years of fight history. Two approaches:
   - **Simulate forward**: Start with 4,000 rookies, simulate 10 years of fights, let careers develop naturally. Pros: most realistic. Cons: very slow (thousands of fights), may produce uneven results.
   - **Generate backward**: Create 4,000 fighters at various career stages (rookie, prime, declining, veteran), assign them records and histories that make sense for their stage. Pros: fast, controllable. Cons: less organic.
   - **Hybrid**: Generate fighters at career stages, simulate ~500 key fights for title histories/rivalries, leave the rest as "background" records. This is the recommended approach.

4. **Progressive seeding is the right call.** The user correctly noted that "seeding our game world/db can be progressive tasks but once fully populated its a job we can tick off as game will load db not seed scripts." This means:
   - The seed scripts create the initial world.
   - The game loads the pre-built DB (no re-seeding on every startup).
   - Future updates to the world (new nations, gyms, etc.) are done via separate migration scripts, not by re-running the seed.

5. **Promotion ecosystem.** The advisor doesn't mention promotions, but our game needs them:
   - 1 major promotion (player's starting promotion, or takeover target)
   - 3-5 mid-tier promotions (rivals, talent pipelines)
   - 5-10 small regional promotions (talent sources, minor shows)
   - Each promotion needs: roster (15-200 fighters depending on size), venues, broadcast deals, champions, rankings.

### What's missing from the advisor's plan

1. **Promotions.** The advisor focuses on geography + fighters but doesn't mention the promotion ecosystem. CAGE EMPIRE is a promotion management game — the world needs multiple promotions of varying sizes competing for talent.

2. **Weight classes.** The advisor doesn't mention weight class distribution. 4,000 fighters need to be distributed across weight classes (Heavyweight down to Strawweight) in realistic proportions (more at middle weights, fewer at extremes).

3. **Historical events.** The advisor mentions career histories but not past events. The world should have a history of past cards — "Alpha Combat 47: Vale vs Reed" — with results, attendance, ratings. This is what makes the world feel like it existed before the player arrived.

4. **Staff.** The advisor doesn't mention staff (coaches, commentators, scouts). The world needs staff at every gym and promotion.

5. **Hall of Fame / retired legends.** The advisor mentions "former champions" but doesn't explicitly call for a hall of fame with retired legends. Our legacy system (future Task) should include ~50-100 retired fighters in the hall of fame, with career summaries.

---

## 2. Revised World Seed Plan (Task 31)

### Scale targets (confirmed)

| Entity | Count | Notes |
|---|---|---|
| Nations | 20 | Real-world-inspired (USA, Brazil, Japan, Russia, UK, Mexico, etc.) |
| Regions | 60 | MMA hotbeds (North America, Latin America, Europe, Asia, Oceania, Africa) |
| Cities | 150 | Weighted toward MMA hotbeds (Las Vegas, Rio, Tokyo, London, Mexico City, etc.) |
| Gyms | 300 | 15-20 elite, 80 national, 100 regional, 105 local. Each with distinct identity. |
| Promotions | 8-12 | 1 major, 3-5 mid, 4-6 small. Each with roster, venues, champions. |
| Weight classes | 8-12 | Heavyweight through Strawweight (men's + women's) |
| Fighters | 3,500-4,000 | Distributed across weight classes and promotions. Full attribute/personality/potential blocks. |
| Staff | 200-300 | Coaches, commentators, scouts, doctors, cutmen. At every gym and promotion. |
| Name pool entries | ~2,500-3,000 | Region-specific first/last names + nicknames. |
| Retired legends | 50-100 | Hall of fame with career summaries. |
| Historical events | 500-1,000 | Past cards with results (not full beat data — just results). |
| Historical fights | 5,000-8,000 | Past fight results (winner, loser, result_type, round, date). |
| Rivalries | 50-100 | Pre-existing rivalries between fighters. |
| Titles | 60-120 | One per weight class per promotion. Most held, some vacant. |

### Phased approach (progressive seeding)

**Phase 1: World Infrastructure** (can be done now, doesn't need all systems)
- Nations (20): real-world-inspired with language, combat culture hints
- Regions (60): grouped under nations, with style preferences
- Cities (150): with population, MMA interest level
- Markets (150): one per city, with heat level
- Venues (200-300): multiple per major city, with capacity and prestige
- Weight classes (8-12): standard MMA weight classes
- Name pools (2,500-3,000): region-specific names

**Phase 2: Gyms & Promotions**
- Gyms (300): with distinct identities (facility_quality, medical_support, sparring_depth, development_focus, culture_tone, weight_cut_support). 15-20 elite gyms with strong specializations. Each gym has a nation/region.
- Promotions (8-12): with size_tier, broadcast_tier, budget, reputation, ai_aggression, ai_spending_style. 1 major (player's), 3-5 mid, 4-6 small.
- Staff (200-300): coaches at gyms, commentators/scouts at promotions. With skill levels.

**Phase 3: Fighter Generation**
- 3,500-4,000 fighters generated via fighter_gen.py
- Distributed across weight classes (more at middle weights)
- Distributed across promotions (major=200-400, mid=80-150, small=20-50, free agents=200-400)
- Each fighter gets: full 25 attrs + 20 personality + physical + potential + archetype
- Career stage assigned: prospect (18-22, few fights), developing (23-27, building record), prime (28-32, peak), declining (33-37, past peak), veteran (38+, winding down)
- Records generated to match career stage (prospect 2-5 fights, prime 15-25 fights, veteran 30+ fights)

**Phase 4: Career Histories**
- Generate past fights (5,000-8,000) with results (no beat data — just winner/loser/result_type/round/date)
- Populate fight_history table
- Generate title histories (60-120 titles, most held, with reigns and defenses)
- Generate rankings (ELO ratings reflecting career histories)
- Generate contracts (active/expired/free agent based on career stage)
- Generate injuries (some fighters recovering, some with long-term damage)
- Generate rivalries (50-100 pre-existing)

**Phase 5: Narrative Layer**
- Bios for top 200 fighters (the "featured" fighters with richer stories)
- Gym histories (how the gym was founded, notable fighters produced)
- Retired legends (50-100) in hall of fame with career summaries
- Memory links (successor links for recently retired champions)
- News items covering past milestones (title wins, upsets, retirements)

### Implementation approach

Each phase is a **separate seed script** that can be run independently:
- `scripts/seed_world_phase1.py` — nations, regions, cities, markets, venues, weight classes, name pools
- `scripts/seed_world_phase2.py` — gyms, promotions, staff
- `scripts/seed_world_phase3.py` — fighters
- `scripts/seed_world_phase4.py` — career histories, fights, titles, rankings, contracts, injuries, rivalries
- `scripts/seed_world_phase5.py` — bios, gym histories, retired legends, memory links, news

Once all 5 phases are run, the DB is fully populated and the game loads it directly. No re-seeding on startup.

### Key design decisions

1. **Real-world-inspired, not real-world.** Nations are named after real countries (for believability) but fighters, gyms, and promotions are fictional (for legal safety and creative freedom).

2. **Career histories are generated, not simulated.** Simulating 10 years of fights for 4,000 fighters would take hours and produce uneven results. Instead, we generate fighters at career stages and assign them records that make sense. A 32-year-old prime fighter has 18-22 fights with a 75% win rate. A 38-year-old veteran has 35+ fights with a declining win rate in recent years.

3. **Historical fights have results but no beat data.** Past fights store winner/loser/result_type/round/date in fight_history but NOT in fight_beats (which would be millions of rows). Only fights that happen during gameplay get full beat-level data.

4. **Top 200 fighters get "featured" treatment.** These are the fighters the player will encounter most — champions, top contenders, top prospects. They get richer bios, more detailed career histories, and pre-existing rivalries. The other 3,800 fighters are "deep but procedurally believable" — they have records and attributes but less narrative depth.

5. **Progressive: each phase can be run independently.** If the player wants a smaller world, they can stop after Phase 3 (no career histories). If they want the full experience, they run all 5 phases. This also means we can ship Phase 1-3 early and add Phase 4-5 later.

---

## 3. Integration with Existing Systems

### What already exists and can be reused

| System | Task | Status | Reuse for world seed |
|---|---|---|---|
| `fighter_gen.py` | 14.5 | ✅ | Generate 4,000 fighters with archetype-biased attrs |
| `generate_potential()` | pre-B1 | ✅ | 10% elite, 30% solid, 60% limited |
| Name pools (96 entries) | Task 14 | ✅ | Expand to 2,500-3,000 with region tags |
| Style archetypes (7) | 14.5 | ✅ | Assign to fighters |
| Personality archetypes (5) | 14.5 | ✅ | Assign to fighters |
| Weight classes (1) | Task 2 | ✅ | Expand to 8-12 |
| Gyms (2) | Task 2 | ✅ | Expand to 300 with distinct identities |
| Promotions (2) | Task 2 | ✅ | Expand to 8-12 |
| Contracts system | Task 9 | ✅ | Generate active/expired contracts |
| Rankings (ELO) | Task 10 | ✅ | Generate ratings reflecting career histories |
| Titles | Task 11 | ✅ | Generate 60-120 titles, most held |
| Injuries | Task 15 | ✅ | Some fighters recovering, some with long-term damage |
| Regen lineage | Task 14 | ✅ | For retired legends → successors |
| Memory links | pre-B1 | ✅ | Champion successor links |

### What needs to be built

| System | Task | When |
|---|---|---|
| World seed scripts (5 phases) | Task 31 | Stage 5 (after all systems in place) |
| Career history generator | Task 31 | Part of Phase 4 |
| Bio generator | Task 31 / Task 19 | Phase 5 (uses voice layer) |
| Rivalry generator | Task 31 / Task 22 | Phase 4 (uses rivalries table from Task 22) |
| Hall of fame system | Task 31 | Phase 5 |

### Dependencies

Task 31 (gameworld seed) depends on:
- All Stage 3 tasks complete (injuries ✓, camps, weight cuts, scouting, voice layer)
- All Stage 4 tasks complete (finances, social media, rivalries, news engine, punditry)
- All Stage 5 tasks complete (rival promotion AI, show rating, venue depth, theme, mod tools, save/load)

This is why Task 31 is positioned at the end of Stage 5 — it needs every table and system to be available so it can populate the full living history.

---

## 4. Decision: Progressive Seeding vs. Single Script

The user noted: "seeding our game world/db can be progressive tasks but once fully populated its a job we can tick off as game will load db not seed scripts."

**Decision:** Progressive seeding with 5 separate phase scripts. Once all 5 phases are run and the DB is verified, the world seed is "done" — the game loads the DB directly. Future world updates (new nations, new gyms, balance tweaks) are done via migration scripts, not by re-running the seed.

This means:
- `src/seed_data.py` remains the minimal playable world (5 fighters, 2 promotions, 1 event) — used for development and testing.
- `scripts/seed_world_phase1.py` through `scripts/seed_world_phase5.py` are the full world seed — run once to populate the DB, then never again.
- The game ships with a pre-built `data/cage_empire.db` containing the full world. The player never runs seed scripts.

---

## 5. Summary

The external advisor's recommendations are sound and align with our Soul document and Design Law. The key takeaways:

1. **Scale:** 20 nations, 60 regions, 150 cities, 300 gyms, 4,000 fighters. Enough to feel enormous, not so much it's unmanageable.

2. **Priority:** Fighters are the content. World data exists to support them. Career histories and gym identities matter more than geography.

3. **Phasing:** 5 progressive phases (infrastructure → gyms/promotions → fighters → career histories → narrative layer). Each can be run independently.

4. **Career histories are generated, not simulated.** Fighters are created at career stages with records that make sense. Only 500-1,000 key fights get full results; the rest are "background."

5. **Top 200 fighters get featured treatment.** Richer bios, more detailed histories, pre-existing rivalries. The other 3,800 are "deep but procedurally believable."

6. **Once seeded, the DB is the world.** The game loads it directly. No re-seeding on startup. Future updates via migration scripts.

This document should be referenced when Task 31 (gameworld seed) is implemented in Stage 5.
