> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Phase A Fix Plan (Post-Audit)

> **Date:** 2026-07-23
> **Schema:** 3.3.0 (no change needed for Phase A — all fixes are code-only)
> **Scope:** Wire existing pipes, fill event bus gaps, make stale fields dynamic

---

## STALE FIELD AUDIT RESULTS

### Fighter personality fields that are NEVER updated by game events:

| Field | Read by fight engine? | Updated by? | Impact |
|---|---|---|---|
| **morale** | ✓ (in _FIGHTER_PERS_COLUMNS) | NOTHING | CRITICAL — should swing with wins/losses/injuries/beefs |
| **aggression** | ✓ | NOTHING | Should shift with rivalry heat, personality development |
| **composure** | ✓ | NOTHING | Should drop under rivalry pressure, recover with experience |
| **discipline** | ✓ | NOTHING | Should improve with age/experience, drop with suspensions |
| **coachability** | ✓ | NOTHING | Should improve with camp attendance |
| **focus** | ✓ | NOTHING | Should drop with distractions (beefs, media), recover with camp |
| **ego** | ✓ | NOTHING | Should grow with wins/titles, shrink with losses |
| **confidence** (not a column — but morale serves this role) | — | — | — |
| grit | ✓ | NOTHING | Should be tested + potentially grow through adversity |
| resilience | ✓ | NOTHING | Should grow through injury comebacks |
| patience | ✓ | NOTHING | Could shift with age |
| ambition | ✓ | NOTHING | Could drop after achieving title |
| charisma | ✓ | NOTHING | Could grow with media exposure |
| attention_seeking | ✓ | NOTHING | Static is OK (personality trait) |
| professionalism | ✓ | NOTHING | Could drop with suspensions, grow with experience |
| sportsmanship | ✓ | NOTHING | Could shift based on rivalry behavior |
| loyalty | ✓ | NOTHING | Could shift based on contract/gym changes |
| risk_taking | ✓ | NOTHING | Could shift with age (older = less risk) |
| killer_instinct | ✓ | NOTHING | Static is OK (personality trait) |
| fatigue_tolerance | ✓ | NOTHING | Could degrade with age/injuries |
| travel_comfort | ✓ | NOTHING | Static is OK (personality trait) |

### Fighter meta-fields that are NEVER updated:

| Field | Current State | Should be updated by? |
|---|---|---|
| **marketability** | Static since seed | Should grow with wins/titles/media exposure, shrink with losses/suspensions |
| **fan_friendliness** | Static since seed | Should grow with exciting fights, shrink with boring ones |
| **consistency** | Static since seed | Should improve with experience (fights fought) |
| **clutch_factor** | Static since seed | Should be tested + grow through high-pressure fights |
| **promo_boost** | Static since seed | Should grow with social media engagement |
| **injury_proneness** | Static since seed | Should increase with age + injury history |
| **weight_cut_difficulty** | Static since seed | Should increase with age |
| **preferred_gameplans** | NULL for all | Should be populated based on style archetype + fight history |
| **bad_matchup_tags** | NULL for all | Should be populated based on fight history (losses to certain styles) |

### Memory resurfacing gaps:

| Check | Status |
|---|---|
| `fighter_memory_links` table exists | ✓ |
| Populated for retiring champions | ✓ (regen function) |
| Used by any game system | ⚠️ NOT USED — no system reads fighter_memory_links |
| Memory resurfacing in news engine | ⚠️ MISSING — no "fighter X reminds fans of legend Y" stories |
| Memory resurfacing in scouting | ⚠️ MISSING — no "this prospect fights like retired legend Z" comparisons |
| Memory resurfacing in commentary | ⚠️ MISSING — no "like his predecessor, fighter X..." references |

### Interpretation layer gaps:

| Check | Status |
|---|---|
| voice.py has descriptors for all 25 attrs | ✓ |
| voice.py has descriptors for all 20 personality | ✓ |
| voice.py has descriptors for potential | ✓ |
| voice.py has descriptors for career stage | ✓ |
| voice.py has descriptors for career health | ✓ |
| voice.py has context-dependent descriptors | ⚠️ MISSING — all descriptors are context-neutral |
| voice.py has multi-attribute compound descriptors | ⚠️ MISSING — only single-attribute |
| fighter_descriptors snapshot updated on triggers | ✓ |
| fighter_descriptors snapshot covers all 4000 fighters | ✓ |

---

## PHASE A FIX PLAN (code-only, no schema changes)

### A1. Fighter Morale System (CRITICAL)
**File:** new `src/morale.py`
**What:** Subscribe to FIGHT_RESOLVED, TITLE_CHANGED, INJURY_CREATED, INJURY_RECOVERED, CAMP_COMPLETED, TICK_ADVANCED. Update `fighter_personality.morale` based on events:
- Win → +5 (title win → +15)
- Loss → -5 (KO loss → -10, losing streak → additional -3 per consecutive)
- Title won → +15; Title lost → -15
- Injury → -5 to -10 (severity-scaled)
- Injury recovered → +5
- Camp completed → +3
- Camp injury → -5
- Weight cut miss → -5
- Rivalry escalation → ±3 (depends on personality)
- Apology forced → -5
- Contract signed → +3

Clamp to [10, 95] (never 0 = broken, never 100 = complacent).

### A2. Rivalry Heat Decay
**File:** modify `src/rivalries.py`
**What:** On TICK_ADVANCED, decay all active rivalries by -1 heat per week. Below heat=20, set is_active=0 (dormant). Apologies increase to -15.

### A3. Same-Roster Restrictions
**File:** modify `src/social.py`, `src/rivalries.py`
**What:** Callouts and rivalries restricted to fighters in the same promotion. Cross-promotion callouts only for same weight class, 5% chance, generates extra hype.

### A4. News Source Variety
**File:** modify `src/build_db.py` (seed), `src/news.py`
**What:** Seed 5 news sources:
- System Feed (existing — neutral, official)
- The Cage Wire (tabloid — high sensationalism, low credibility)
- MMA Analytica (broadsheet — high credibility, analytical)
- Social Sphere (aggregates social posts into news items)
- The Pundit's Desk (opinion pieces from punditry system)

### A5. Fill Unsubscribed Event Types
**File:** modify `src/news.py`, `src/social.py`, `src/rivalries.py`, `src/morale.py`
**What:** Subscribe to all 13 unsubscribed events:
- CAMP_COMPLETED → news (camp report), morale (+3)
- CAMP_INJURY → news (training injury), morale (-5)
- CONTRACT_EXPIRED → news (fighter becomes free agent)
- EVENT_COMPLETED → news (event recap)
- FIGHTER_GENERATED → news (new prospect emerges)
- FIGHTER_RETIRED → news (career retrospective), social (tributes from rivals)
- FIGHTER_SIGNED → news (signing announcement), social (welcome trash talk)
- FIGHTER_STATE_CHANGED → descriptor snapshot update
- FIGHT_CANCELLED → news (cancellation report)
- INJURY_CREATED → news (injury report via engine, not hardcoded)
- INJURY_RECOVERED → news (clearance report via engine)
- SCOUT_REPORT_GENERATED → news (scout activity)
- WEIGHT_CUT_COMPLETED → news (weigh-in results via engine)

### A6. News Pruning
**File:** modify `src/news.py` or new `src/maintenance.py`
**What:** On TICK_ADVANCED (weekly), prune news_items older than 365 days with low importance. Keep all title change news indefinitely. Configurable retention.

### A7. Social Frequency Throttle
**File:** modify `src/social.py`
**What:** Cooldown per fighter: max 1 post per 7 days. Track last post date in the social_posts table (already has post_date). Query before generating.

### A8. Rivalry Morale/Pressure Effects
**File:** modify `src/app.py` (fight engine)
**What:** When loading fighter stats for a fight, check for active rivalry. If heat > 70: +aggression, -composure modifiers. This is a READER of the rivalries table (CONVENTIONS §5.3).

### A9. Pre-Fight Punditry Timing
**File:** modify `src/punditry.py`
**What:** Generate analysis when a fight is scheduled (on schedule_next_event), not after resolution. The analysis exists BEFORE the fight, creating anticipation. Post-fight, generate a "result vs prediction" comparison.

### A10. Dynamic Meta-Fields
**File:** new `src/dynamic_fields.py` or integrate into `src/morale.py`
**What:** On FIGHT_RESOLVED + TICK_ADVANCED, update:
- marketability: +2 per win, +5 per title win, -1 per loss, -5 per suspension
- fan_friendliness: +1 per exciting fight (KO/Sub), -1 per boring decision
- consistency: +0.5 per fight (capped at 90)
- clutch_factor: tested in title fights (+2 if win, -2 if loss)
- injury_proneness: +1 per year over 30, +2 per serious injury
- weight_cut_difficulty: +1 per year over 32
- promo_boost: +1 per social post with high engagement

### A11. Memory Resurfacing Wiring
**File:** modify `src/news.py`, `src/scouting.py`
**What:**
- News engine: when a new champion is crowned, check fighter_memory_links for the retiring champion's successor. Generate "X carries the torch of Y" news.
- Scouting: when a scout evaluates a prospect, check regen_lineage for style echoes. Include "reminds us of retired legend Y" in the report.

### A12. Preferred Gameplans + Bad Matchup Tags Population
**File:** modify `src/app.py` (after fight resolution)
**What:** After each fight, populate preferred_gameplans based on the fighter's winning attributes. After losses to specific styles, populate bad_matchup_tags.

---

## UI DESIGN CONSIDERATIONS (NOTED FOR FUTURE)

The UI is a massive design task that needs its own planning phase. Key considerations:

### Screens needed:
1. **Dashboard** — overview of promotion status (cash, upcoming event, top news, active rivalries)
2. **Fighter roster** — filterable/sortable list with descriptor-based profiles
3. **Fighter detail** — full profile with bio, attributes (descriptors), personality (descriptors), career history, fight history, social posts, rivalry status, scouting reports, descriptor snapshot
4. **Event management** — upcoming events, fight card builder, weigh-in results
5. **Scouting** — scout assignment, report viewer
6. **Finance** — P&L per event, burn rate, forecast, transaction log
7. **News feed** — filterable by topic/source/importance, with pruning
8. **Social media feed** — fighter posts, beefs, callouts
9. **Rivalries** — active rivalries, heat meter, fight history between rivals
10. **Hall of Fame** — retired legends, career summaries
11. **Staff management** — coaches, scouts, commentators
12. **Rankings** — per weight class, per promotion
13. **Titles** — current champions, title history
14. **Settings** — news filters, difficulty options, display preferences

### Design principles:
- **No raw numbers** (CONVENTIONS §14) — everything through voice.py
- **Card-based layout** for fighters, events, news
- **Breadcrumb navigation** — always know where you are
- **Loading screens** for world generation / DB operations
- **Dark theme** (Task 28 — CustomTkinter)
- **Responsive** — works on different screen sizes
- **Icons + textures** — MMA-themed visual identity
- **Fight animation** — beat-by-beat fight visualization (future)
- **Subscreens/modals** for detailed views without losing context

### Data to show/hide:
- **Show:** descriptors, career stage, bio, record, streak, title status, rivalry heat, morale descriptor, injury status descriptor
- **Hide:** raw attribute numbers, raw potential, raw ELO, internal IDs
- **Conditional:** scouting reports show estimated descriptors (not true values), fighter attributes show descriptors (not raw 0-100)

---

## IMPLEMENTATION ORDER

1. A1 (morale) — the connective tissue, highest priority
2. A10 (dynamic meta-fields) — closely related to morale
3. A5 (fill event bus gaps) — makes all events meaningful
4. A2 (rivalry decay) — simple, high impact
5. A3 (same-roster restrictions) — simple, prevents absurd callouts
6. A7 (social throttle) — simple, prevents spam
7. A4 (news sources) — variety
8. A6 (news pruning) — DB hygiene
9. A8 (rivalry fight effects) — wires rivalries into the engine
10. A9 (pre-fight punditry) — anticipation
11. A11 (memory resurfacing) — legacy stories
12. A12 (gameplans/matchup tags) — depth

Each fix is code-only (no schema changes). Can be done in 2-3 commits.
