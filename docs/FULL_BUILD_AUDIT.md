> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Full Build Forensic Audit

> **Date:** 2026-07-23
> **Schema:** 3.3.0
> **Scope:** Every system audited against Soul document, CONVENTIONS, and player fantasies
> **Verdict:** Several systems are undercooked. This document identifies every gap.

---

## Executive Summary

The build has strong foundations (world seed, fight engine, voice layer, scouting, event bus) but **Stage 4 systems are thin**. The news engine, social media, rivalries, and punditry are architecturally correct (event-bus-driven, voice-layer-compliant) but lack depth, variety, and game-impact wiring. Fighter morale is static — no system changes it. News will grow indefinitely with no pruning. Rivalry heat never decays. Many event types have no subscribers. The player has no filtering controls.

**Recommendation:** Do NOT proceed to Stage 5. Fix the identified gaps in Stage 4 first. The systems need depth, not breadth.

---

## 1. FIGHTER MORALE — CRITICAL GAP

**Status: BROKEN. Fighter morale is NEVER updated by any game system.**

The `fighter_personality.morale` column exists (0-100) but no system writes to it. It's set at seed time and never changes. This breaks the Soul document's "dopamine loop" — wins, losses, injuries, beefs, title changes, and news should all affect morale, which in turn affects fight performance (via the beat engine's morale modifier).

**What should affect morale:**
- Win → +5 to +10 (title win → +15)
- Loss → -5 to -10 (KO loss → -15, losing streak → additional -3 per consecutive)
- Title won → +15
- Title lost → -15
- Injury created → -5 to -10 (severity-scaled)
- Injury recovered → +5
- Rivalry escalation → -3 (stress) or +3 (motivation, depends on personality)
- Social media beef won (opponent apologizes) → +5
- Social media beef lost (forced to apologize) → -5
- Training camp completed → +3
- Training camp injury → -5
- Weight cut miss → -5
- Contract signed/renewed → +3
- Scout report filed (positive) → +2
- Hall of Fame induction (for related fighters) → +1

**Impact:** Morale feeds into the beat engine's fight resolution (the `_load_fighter_stats` function reads morale). A fighter with morale=20 should underperform; morale=90 should get a boost. Currently this has no effect because morale never changes from its seed value.

---

## 2. NEWS ENGINE — UNDERCOOKED

### 2a. News Sources — Only 1 source
The world has a single news source ("System Feed"). The Soul document envisions a living media ecosystem with multiple source types:

**Missing sources:**
- **Tabloid** (sensational, low credibility, high engagement) — "CHAMP CAUGHT IN SCANDAL"
- **Broadsheet** (analytical, high credibility, low sensationalism) — "Tactical breakdown of Vale vs Reed"
- **Social Media Aggregator** (compiles fighter social posts into news) — "Twitter explodes after Vale's callout"
- **Promotion Official** (press releases, announcements) — "Alpha Combat announces July card"
- **Pundit Feed** (opinion pieces from punditry system) — "Why Reed will upset Vale"
- **Regional Insider** (nation-specific, better regional fighter coverage)

Each source should have different `credibility`, `sensationalism`, `bias`, and `reliability` values that affect how they report the same event.

### 2b. Missing News Triggers
The news engine subscribes to FIGHT_RESOLVED, TITLE_CHANGED, and TICK_ADVANCED. But many game events generate NO news:

**Events that should generate news but don't:**
- Injury creation/recovery (currently only "System Feed" hardcoded news, not via news engine)
- Training camp completion (no news at all from the engine)
- Upcoming event announcements (no preview/hype news)
- Other promotion events (what's happening in rival promotions)
- Fighter suspensions (drug tests, bad behavior — doesn't exist yet)
- Agent offers for unknown talents (doesn't exist yet)
- Scouting report generation (no news about scout activity)
- Contract signings/expiries (no news)
- Rivalry formation/escalation (no news)
- Retirement (only via hardcoded "System Feed", not the engine)
- Weight cut results (only "System Feed", not the engine)
- Finance results (only from finance.py, not the news engine)
- Hall of Fame inductions

### 2c. News Pruning — MISSING
There is NO news pruning mechanism. `news_items` will grow indefinitely. After 10 years of sim time with 4000 fighters, this could be millions of rows. Need:
- Configurable retention (e.g., keep last 1000 items per promotion, or last 6 months)
- Archive table for old news (player can search but it doesn't clutter the feed)
- Auto-prune on tick (e.g., delete items older than 365 days with low importance)

### 2d. Player Settings — MISSING
No player settings for:
- News filter by topic (show/hide injuries, social media, finance, etc.)
- News filter by importance (only show "big" news)
- News volume (verbose/normal/summary)

---

## 3. SOCIAL MEDIA — UNDERCOOKED

### 3a. Seeded World Has 0 Social Posts
The world seed doesn't generate any social_posts. The table is empty until the player starts resolving fights. Should have seed-time posts (fighters hyping upcoming fights, trash_talk from existing beefs, brags from recent wins).

### 3b. No Same-Roster Restriction
Social media callouts can happen between fighters in different promotions who would never fight. Should restrict callouts to fighters in the same promotion (or same weight class across promotions for inter-promotion callouts, which should be rare).

### 3c. No Frequency Control
The TICK_ADVANCED subscriber picks up to 5 fighters per tick. With 4000 fighters, this could generate 5 posts per day = 1825 per year. No throttle, no cooldown per fighter. A single high-attention_seeking fighter could post every tick.

### 3d. No Engagement Decay
Social post engagement is set once and never changes. In reality, posts would get more engagement over time (likes, retweets) then fade. Not critical, but the engagement number should be more dynamic.

### 3e. No Player Filtering
No way for the player to filter/hide social posts. With 4000 fighters potentially posting, the feed would be overwhelming.

---

## 4. RIVALRIES — UNDERCOOKED

### 4a. No Heat Decay
Rivalry heat only goes UP (callouts +5, fights +15, title fights +25). It NEVER goes down except via apologies (-10). There's no natural decay over time. A rivalry from 3 years ago should cool down if the fighters haven't interacted. Need:
- Tick-based decay: -1 heat per week of no interaction
- Below heat=20: rivalry becomes `is_active=0` (dormant)
- Apologies should be more impactful: -15 to -20

### 4b. No Same-Roster Restriction
Rivalries can form between fighters in different promotions. Should be restricted to same promotion (or at least same weight class). Cross-promotion rivalries should be extremely rare and special.

### 4c. No Morale/Pressure Effects
Rivalries don't affect fighter morale or fight performance. A high-heat rivalry should:
- Increase both fighters' aggression in the fight (already designed but not wired)
- Decrease composure (pressure of the rivalry)
- Increase fight importance/hype
- Affect morale (stress vs motivation, depends on personality)

### 4d. No Contender/Upstart Beef Generation
Currently beefs only form from social media callouts (3+ posts). Missing:
- #1 contender calling out champion (automatic rivalry)
- Upstart prospect calling out established veteran
- Rematch requests after close decisions
- Bad blood from weight cut misses (designed but rarely triggers)
- Stolen opportunity (fighter loses title shot to someone else)

### 4e. No Seed-Time Rivalries
The seeded world has 0 rivalries. Should seed 50-100 pre-existing rivalries from the historical fight data (fighters who fought each other multiple times, controversial decisions, etc.).

### 4f. No Balance/Throttle
No limit on how many rivalries a single fighter can have. A high-aggression fighter could accumulate dozens, diluting the narrative impact.

---

## 5. PUNDITRY — UNDERCOOKED

### 5a. Only 1 Pundit Voice
The punditry system generates analysis text from templates, but there's only one "voice." Should have multiple pundit personalities:
- The Statistician (data-driven, measured)
- The Hot Take Artist (controversial, sensational)
- The Veteran (experience-based, old-school)
- The Prospect Whisperer (focuses on young fighters)

### 5b. No Pre-Fight Timing
Analysis is generated on FIGHT_RESOLVED (after the fight). Should be generated BEFORE the fight (when it's scheduled) to create anticipation. The analysis should then be compared to the actual result for post-fight "I told you so" / "I was wrong" punditry.

### 5c. No Betting Odds
The brief mentions `betting_odds` table. Not implemented. Odds should be derived from the analysis (confidence_pct → odds ratio) and could be a future economy system.

---

## 6. FINANCE — UNDERCOOKED

### 6a. No Weekly Burn Rate
The brief mentions "per-week burn rate." Not implemented. The player should see "You're burning $50k/week — you need to run an event every 3 weeks to break even."

### 6b. No Forecast
No financial forecast. The player should see "At current burn rate, you'll run out of cash in 14 weeks."

### 6c. No Bankruptcy
No consequence for running out of cash. Should trigger a game-over or bailout scenario.

### 6d. No Fighter Bonuses
Fighters only get base purse. No win bonuses, finish bonuses, or performance bonuses (the contract system has `bonus_structure` but it's never used).

---

## 7. EVENT BUS — UNDERUTILIZED

16 event types defined. Many have NO subscribers:

| Event | Subscribers | Issue |
|---|---|---|
| CAMP_COMPLETED | 0 | No news, no social, no morale update |
| CAMP_INJURY | 0 | No news, no morale update |
| CONTRACT_EXPIRED | 0 | No news, no social |
| EVENT_COMPLETED | 0 | No finance, no news, no social |
| FIGHTER_GENERATED | 0 | No news, no social (new prospect arrives silently) |
| FIGHTER_RETIRED | 0 | No news, no social, no morale impact on rivals |
| FIGHTER_SIGNED | 0 | No news, no social |
| FIGHTER_STATE_CHANGED | 0 | No subscriber uses this |
| FIGHT_CANCELLED | 0 | No news about cancelled fights |
| INJURY_CREATED | 0 | No news engine coverage |
| INJURY_RECOVERED | 0 | No news engine coverage |
| SCOUT_REPORT_GENERATED | 0 | No news about scout activity |
| WEIGHT_CUT_COMPLETED | 0 | No news engine coverage |

**This is the biggest systemic gap.** The event bus was built to decouple systems, but half the events are published with nothing listening.

---

## 8. VOICE LAYER — QUALITY ISSUES

### 8a. News Engine Body Text
The news engine body text has quality issues:
- "holds his own" appears repeatedly (same descriptor variant)
- "round of the third round" is grammatically awkward
- Some descriptors don't flow naturally in prose

### 8b. Descriptor Variety
While the voice layer has 2-3 variants per tier, the news engine and social media reuse the same variants too often. Need more variety or better rng seeding.

### 8c. Context-Dependent Descriptors
The brief for Task 19 mentions context-dependent descriptors (scout report vs commentary vs punditry). Not implemented — all descriptors are context-neutral.

---

## 9. MISSING SYSTEMS (Not Yet Built)

These systems don't exist at all but are needed for a believable world:

### 9a. Fighter Suspensions
No suspension system for drug tests or bad behavior. Should be rare (1-2% chance per fight for drug test, 0.5% for behavior) but create big stories when they happen.

### 9b. Agent Offers / Unknown Talents
No system for agents to offer the player unknown fighters (gamble signings). The scouting system evaluates existing fighters but doesn't generate new "mystery" offers.

### 9c. Fight Camp News
Training camp completions generate "System Feed" news but not via the news engine. No variety, no voice layer integration.

### 9d. Upcoming Event Hype
No pre-event hype generation. Should generate news/social posts in the days leading up to an event (weigh-in predictions, last-minute training updates, staredown photos).

### 9e. Cross-Promotion News
The player should hear about big events in rival promotions (champion changes, big upsets, retirements). Currently only the player's promotion generates news.

---

## 10. DESIGN LAW COMPLIANCE AUDIT

| Pillar | Current State | Gap |
|---|---|---|
| **Discovery** | Scouting works, voice descriptors hide potential | No agent offers, no cross-promotion news about prospects |
| **Investment** | Finance system tracks P&L, camps develop fighters | No burn rate, no forecast, no bankruptcy, no fighter bonuses |
| **Growth** | Effective ceiling growth logic, camp attribute gains | Morale never changes (should affect growth + performance) |
| **Conflict** | Fight engine, rivalries, social media beefs | Rivalries don't affect fights, no suspensions, no decay |
| **Legacy** | Hall of Fame, bios, career histories | No retirement news from engine, no career arc narratives |
| **Anticipation** | Scouting reports, upcoming events | No pre-fight hype, no upcoming event previews, no "what's coming" feed |

---

## 11. RECOMMENDED FIX PRIORITY

### Phase A — Wire What Exists (no new tables, just code)
1. **Morale system** — wire morale updates into all existing event bus subscribers
2. **Rivalry decay** — add tick-based heat decay (-1/week, dormant below 20)
3. **Same-roster restriction** — filter social callouts + rivalries to same promotion
4. **News source variety** — seed 4-5 news sources (tabloid, broadsheet, social aggregator, promotion official, pundit feed)
5. **Event bus gap filling** — subscribe to all 13 unsubscribed event types
6. **News pruning** — auto-prune on tick (keep last 1000 per promotion)
7. **Social frequency throttle** — cooldown per fighter (max 1 post per 7 days)
8. **Rivalry morale/pressure effects** — wire into fight engine (already designed)
9. **Pre-fight punditry timing** — generate analysis when fight is scheduled, not after

### Phase B — Depth (minor schema additions)
10. **Fighter suspensions** — new `suspensions` table (rare events, big stories)
11. **Seed-time rivalries** — generate 50-100 rivalries from historical fight data
12. **Seed-time social posts** — generate initial social posts for active rivalries
13. **Player news settings** — new `player_settings` table (filter by topic/importance)

### Phase C — New Systems (new tables, careful design)
14. **Agent offers** — unknown talent gamble system
15. **Upcoming event hype** — pre-event news/social generation
16. **Cross-promotion news** — news from rival promotions the player hears about
17. **Betting odds** — derived from punditry confidence

---

## 12. CONCLUSION

The architecture is sound (event bus, voice layer, migration system, world seed). The systems are thin. The biggest gap is **fighter morale being static** — it's the connective tissue between all systems. A win should boost morale, which affects the next fight, which generates different news, which affects social media, which affects rivalries.

**Do not proceed to Stage 5 until Phase A fixes are complete.**
