> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE vs WMMA5 — Feature Comparison & Gap Review

> **Task ID:** REVIEW-WMMA5-COMPARISON
> **Mode:** RESEARCH ONLY — no code changed.
> **Scope:** Compare CAGE EMPIRE (Python + SQLite + pywebview) against
> *World of Mixed Martial Arts 5* (Grey Dog Software, 2018, Adam Ryland)
> feature-by-feature. Identify where we are better, where we are worse,
> and what is still missing. Be honest — the user values honesty over
> flattery.
> **Sources read:**
> - `docs/CAGE_EMPIRE_SOUL.md` — 5 core fantasies, "stories not fighters" law
> - `docs/RESEARCH_WMMA5_MATCHMAKING.md` (999 lines) — WMMA5 matchmaking deep-dive
> - `docs/RESEARCH_WMMA5_FM_V2.md` (762 lines) — WMMA5 + Football Manager V2
> - `docs/RESEARCH_FIGHT_NIGHT.md` (844 lines) — fight engine audit
> - `docs/RESEARCH_MATCHMAKING_CURRENT_STATE.md` (500 lines) — current state analysis
> - `docs/RESEARCH_MATCHMAKING_SHOWRATING.md` (851 lines) — show-rating research
> - `docs/NAV_BUTTONS_AUDIT.md` (415 lines) — nav wiring audit
> - `src/web/js/app.js` — NAV_GROUPS + navigate() switch
> - `src/web/js/*.js` — 15 screen modules (1 964-line matchmaking, 1 410-line fight_night, 1 269-line event_builder, etc.)
> - `src/app_web.py` (10 978 lines) — Api class, 50+ methods
> - `src/services/*.py` — finance, fight_engine, hof_svc, scouting_svc, contracts, matchmaking, etc.
> - `src/interpretation/*.py` (6 engines, ~5.8K lines total)
> - `src/news.py` (4 551 lines), `src/rivalries.py` (1 052), `src/social.py` (1 226),
>   `src/morale.py` (1 660), `src/career_arc.py` (568), `src/reputation.py` (1 179),
>   `src/agent_offers.py` (893), `src/player_decisions.py` (444)

---

## 0. TL;DR — The Honest Verdict

CAGE EMPIRE is **a deeper simulation than WMMA5 in many places** —
fight engine, fighter development, scouting, narrative engine, memory
surfacing, social media, morale, reputation, rivalries. The backend
machinery is genuinely richer.

But CAGE EMPIRE is **a less complete game than WMMA5 today** because
the backend riches aren't all wired to the UI. **7 of 19 sidebar
screens are still placeholders.** Four of the five core fantasies
defined in `CAGE_EMPIRE_SOUL.md` have at least one major screen
unwired. The matchmaking loop is fully built out (the "Kingmaker"
fantasy is well served); the other four fantasies are partially
dark.

In short: **we built a bigger engine than WMMA5, but WMMA5 ships
more of its engine to the player.** The work that remains is mostly
wiring, not new systems.

---

## 1. What we already know about WMMA5

Summarized from the five existing RESEARCH_*.md docs.

### 1.1 WMMA5's design philosophy

- 2-rating model: **Commercial Rating** (card-on-paper draw) vs
  **Critical Rating** (how exciting it actually was). Two distinct
  strategies: promoter vs purist.
- "Name Value" ≠ "Rankings" — popularity is a separate axis from
  skill. A #1-ranked fighter with low popularity is a *story to
  develop*, not a bug.
- Main event dominates the Commercial Rating; co-main is secondary;
  prelims have **zero** impact.
- Booking is the player's job — the AI never auto-books for the
  player. Reddit: *"Matchmaking is the most enjoyable aspect of the
  game, why let an AI do it."*

### 1.2 WMMA5's matchmaking UX

- Two-column "blue corner vs red corner" layout, full-window.
- Per fighter in the corner slot: portrait, name, record, rank,
  **Name Value** (text label like "Cult Hero"), style archetype,
  weight class, Likely Usage phrase, **Momentum / Fighter Heat**
  (flame icons, dev-journal #77), inducements icons, personality.
- **Compare button** — generates natural-language style matchup
  analysis ("striker vs grappler, X's wrestling matches Y's, he
  should win if…"). **Text-only — no radar chart, no tale-of-tape
  graphic.** This is WMMA5's biggest UX weakness.
- **Fan Feedback button** — one-line voice reaction ("fans think
  this is a worthy main event").
- **Side-panel DRAW stars** per booked fight (0–5).
- **Hype slider** per fight (None / Small / Medium / Large) — risk/
  reward popularity lever.
- **Inducements icons** per fight — 4 categories: training-time,
  opponent-specific, difficulty, weight-class. Personality-driven.
- **Booking Adviser** — tabs surfacing opportunities (hometown
  fighters, debuts, #1-contender fights, win streaks).
- ▲▼ arrow reordering, no drag-drop.

### 1.3 WMMA5's scheduling

- 1-month minimum lead (2 weeks in the first game week).
- No limit on simultaneously-scheduled shows.
- Trade-off: longer lead = injury risk + camp cost, but lets you
  grab shared fighters + build heat.
- Separate calendar screen (not integrated into matchmaking).
- Rival events visible on the same calendar.
- Cancelling close to the date costs money + Stability.

### 1.4 WMMA5's fighter availability

- **Absences button** — single list of every unavailable fighter +
  reason (dev-journal #144).
- Injured/suspended fighters filtered automatically.
- Already-booked fighters don't appear in the picker for the event's
  date range.
- **Replacement Offers** (dev-journal #160) — when a booked fighter
  withdraws, eligible fighters **privately email** self-offering to
  step in. They won't turn down the fight if accepted within 7 days.
- **Short Notice Search** (dev-journal #152) — filter for fighters
  willing to take a short-notice booking.
- **Event Disruption** — up to −15% Commercial Rating for severely
  disrupted shows; main-event injuries hurt most.

### 1.5 WMMA5's AI

- AI rival promotions book their own cards, sign their own fighters,
  run their own title pictures.
- **Combatative AI** (dev-journal #50) — rivals out-bid you for free
  agents, try to poach your exclusive fighters, grab shared fighters.
- **Booking Adviser** is **opportunity-surfacing, not auto-booking.**

### 1.6 WMMA5's fight night

- Per-beat text prose (paragraph per exchange) with shortcut keys.
- Commentators interject ("That's the third body shot in 90
  seconds").
- Pre-show commentary builds anticipation.
- **No visual cage heatmap, no damage silhouette, no radar chart.**
  Text-driven only.
- Post-match: Commercial Rating + Critical Rating + written recap.

### 1.7 WMMA5's weaknesses (per research docs)

- DATED spreadsheet-like UI (2018 Windows desktop app).
- No live attendance / buyrate / revenue projection during booking
  — **the player books blind.**
- Compare button text-only (no visual radar/tale-of-tape).
- No "ranking implications" prediction ("if #7 wins → #3").
- Prelims have zero impact on the rating.
- No drag-drop reordering.
- No smart matchup suggestions.
- No card coherence feedback.
- Ticket pricing automatic, no player control.
- No pre-event "card quality score."
- Critical Rating doesn't explain itself post-event.
- Information overload — too many separate screens.
- Card-placement advice is one-dimensional (per-fighter, not
  per-matchup).

---

## 2. CAGE EMPIRE's Soul — the prime directive

Per `docs/CAGE_EMPIRE_SOUL.md`, every system must serve one of the
**5 Core Fantasies**:

| # | Fantasy | Player feels | Systems |
|---|---|---|---|
| 1 | **Talent Hunter** | "I find greatness before anyone else." | scouting, hidden potential, uncertain reports, regional networks, regen prospects, agent offers |
| 2 | **Empire Builder** | "My promotion dominates the sport." | prestige, finances, market expansion, TV deals, champions |
| 3 | **Kingmaker** | "I create stars." | promotion, matchmaking, hype, rankings, media |
| 4 | **Historian** | "The world remembers what I built." | hall of fame, records, memories, historical comparisons, legacy |
| 5 | **Puppet Master** | "The sport evolves because of my decisions." | rivalries, gym ecosystems, promotion ecosystems, career arcs |

**The Design Law:**
> The player does not collect fighters. The player collects stories.
> Every major system must contribute to: Discovery, Investment,
> Growth, Conflict, or Legacy.

**The Real Dopamine Loop:**
> Discover → Invest → Develop → Promote → Watch Rise → Create Legacy
> → Shape History → Repeat. The addiction comes from "I wonder what
> happens next."

**The Interpretation Layer's real purpose:**
> Translate simulation into emotion.
> Raw: `Age 37, Losses 4, Durability down 12%`
> Meaning: `His best years may be behind him.`

This is the lens for the comparison. WMMA5's design is "simulate MMA
booking." CAGE EMPIRE's design is "generate stories the player
remembers." Where we serve the Soul better, we win — even if WMMA5
ships more screens.

---

## 3. Feature-by-Feature Comparison

Legend: **CE = CAGE EMPIRE. WMMA5 = World of Mixed Martial Arts 5.**

### 3.1 Matchmaking (card building, fighter info, matchup quality)

| Aspect | WMMA5 | CAGE EMPIRE (current) | Who's better? |
|---|---|---|---|
| Corner layout | 2-col blue/red, full-window | 2-row layout: Matchup Zone (top, Red\|VS\|Blue) + Card List/Status Panel (bottom). Per `matchmaking.js` header comment. | **CE** — bigger corner slots, 9-field density per corner |
| Fighter info in corner slot | portrait, name, record, rank, Name Value label, style, WC, Likely Usage, momentum flame, inducements, personality | portrait (120×120), name+nickname (18px), rank chip (gold/silver/steel), title chip, popularity tier label (Cult Hero / Rising Star / Mid Level / Unknown), momentum indicator (▲▼→ + streak), record+WC+age+style dense line, rivalry chip, recent form (last 5 W/L/D chips) | **CE** — denser + visual (WMMA5's is text-only) |
| Compare analysis | Natural-language paragraph, text-only | Radar chart (5-axis averaged from 25 attributes) + 3 "might" voice phrases (style_matchup_phrase, early_read_phrase, excitement_phrase) + matchup_phrase chip (voice tier only — no raw 73/100 score). **No Predicted Winner / Method / Confidence / Upset Risk cells.** | **CE** — visual + voice, deliberately "might" not "easy mode" |
| Tale of the tape | Not really (text-only) | UFC-style modal: portraits + height/reach/age/record/style/last-5 | **CE** |
| "What's at Stake" (ranking implications) | NO | Yes — `get_fight_stakes(fight_id)` returns projected rank moves + title-shot context | **CE** |
| Fan Feedback / Fan Pulse | One-line voice reaction | Modal: rivalry context + hometown reaction + memory surfacing | **CE** |
| DRAW stars per fight | 0–5★ side-panel stars | matchup_phrase chip with voice tier only (no raw number) | **CE** (preserves the magic — no raw score leaks) |
| Reorder | ▲▼ arrow buttons | HTML5 drag-drop + arrow fallback | **CE** |
| Card zones | Main event / Co-main / Main card / Prelims | Same zones, with slot labels MAIN EVENT / CO-MAIN / PRELIM 1 / PRELIM 2 / … | **Tie** |
| Confirm-card flow | No — each `Add Match` immediately persists | Staged in JS (`state.stagedFights`), `confirmCard` writes all fights in one transaction, projection locked behind confirm. Re-open Card to wipe + go back to build mode. | **CE** — supports "build draft → see projection → commit" loop |
| Live projection | **NO — player books blind** | Live projection after confirm: gate, PPV buys, revenue, costs, net profit, voice phrase ("safe"/"risky"/"lethal"), card-draw score, card_health_flags. `_project_card_draw` (app_web.py:1444) feeds real card_draw_multiplier into preview. | **CE — headline advantage** |
| Calendar integration | Separate calendar screen | Calendar screen (`calendar.js`, 515 lines) integrated — click date → schedule event on that date. Conflict warnings ("Counter-programming risk", "Short turnaround"). Min-lead-time (14-day) blocked dates with diagonal stripes. | **CE** |
| Hype slider per fight | Yes (None/Small/Medium/Large) | **NOT IMPLEMENTED** | **WMMA5** |
| Booking Adviser tabs | Yes (Hometown / Win streaks / Debuts / Title picture) | **NOT IMPLEMENTED** — only "Hometown" exists as a roster filter chip | **WMMA5** |
| Smart matchup suggestions | NO | **NOT IMPLEMENTED** | **Tie** (both miss this) |
| Card coherence feedback | NO | `card_health_flags` returned by preview (main event strength, title fight present, stylistic diversity, weight-class spread, card length) — but **not yet surfaced prominently in the UI** | **CE** (slightly — engine exists) |
| Inducements | Yes — 4 categories, personality-driven, visible icons | **NOT IMPLEMENTED** | **WMMA5** |
| Quick Move Fight (between events) | Yes (dev-journal #22) | **NOT IMPLEMENTED** | **WMMA5** |
| Replacement Offers | Yes — fighters privately self-offer when booked fighter withdraws | **NOT IMPLEMENTED** | **WMMA5** |
| Event Disruption penalty | Yes — up to −15% Commercial Rating | **NOT IMPLEMENTED** | **WMMA5** |
| Absences panel | Yes (dev-journal #144) | **NOT IMPLEMENTED** as a screen — injured/suspended fighters just disappear from the roster | **WMMA5** |
| Personality-driven short-notice rejection | Implicit via Inducements + Replacement Offers | **IMPLEMENTED (MM3.3)** — `_short_notice_willingness` (app_web.py:1396) computes willingness from risk_taking / ambition / professionalism / patience. If willingness < 30, fight rejected with news item "{fname} turns down short-notice bout." | **CE** (more explicit) |
| Cross-event double-booking check | Implicit (already-booked fighters don't appear) | **IMPLEMENTED (MM3.1)** — `_get_available_fighters_for_card` excludes fighters booked on ANY scheduled event within ±7 days | **CE** |
| Training camp status | Implicit (1-month minimum lead implies camp) | **IMPLEMENTED (MM3.2)** — each eligible fighter gets `camp_status` field: `ready` / `needs_camp` / `short_notice` | **CE** |
| 1-month minimum lead time | Yes (2 weeks in first game week) | 14-day minimum lead (more lenient for faster early-game pace) | **Tie** (different design choice, both valid) |

**Matchmaking verdict:** CAGE EMPIRE is **substantively better than
WMMA5** on the core booking loop — live projection, visual compare,
"might" advice, calendar integration, confirm-card flow, drag-drop,
9-field corner density, and the explicit personality-driven
rejection. WMMA5 still wins on Hype slider, Booking Adviser,
Inducements, Quick Move Fight, Replacement Offers, Event Disruption,
and Absences panel — 7 secondary systems that add texture but aren't
core to the booking decision.

---

### 3.2 Fight Engine (beats, commentary, live play-by-play)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Beat-by-beat simulation | Yes (text prose) | 12–28 beats/round × N rounds, phase transitions (standing → clinch → cage → ground_top → ground_bottom → scramble), fatigue (gas 100→0 + between-round recovery), momentum swings. `fight_engine.py` is **6 337 lines.** | **CE** (much deeper sim) |
| Outcomes | KO / TKO / sub / decision / draw / DQ | KO / TKO / sub / DQ / **doctor-stoppage** / **corner-stoppage** / decision / draw / **no-contest** (weight-cut miss) | **CE** |
| Weight cuts | Simulated (dev-journals #93–98) | Yes — `_run_weight_cut`, "missed large" cancels fight as no_contest, "missed medium" applies cardio penalty | **Tie** |
| Rivalry pressure modifiers | Implicit (Heat feeds side-panel) | Explicit — heat > 70 → +5 aggression / −5 composure; heat > 90 doubles it | **CE** |
| Decision scoring | 10-point must | 10-point must with 10-8 rounds for knockdowns | **Tie** |
| Side effects | Career record, title, news | Record, ELO (K=32 zero-sum), title, news, **fighter_descriptor snapshot refresh**, **preferred gameplan update** (winner), **bad_matchup_tags** (loser), injuries (5% base / 30% KO loser / 15% sub loser / guaranteed doctor-stoppage), `FIGHT_RESOLVED` + `FIGHTER_STATE_CHANGED` + `TITLE_CHANGED` event-bus publishes | **CE** |
| Per-fight data persisted | Not detailed in research | `fight_beats` (1 row/exchange, 13 cols) + `fight_rounds` (1 row/round, 13 cols) + `commentary_segments` (highlight + play_by_play) | **CE** (richer substrate) |
| Live play-by-play UI | Per-beat text feed, shortcut keys (space/backspace/enter/s/b/t) | `fight_night.js` (1 410 lines) — 3-phase state machine: PRE-FIGHT (tale of tape + punditry "might" + rivalry/memory, 5s timer) → LIVE (4-zone fixed grid: Commentary Feed / Fight Status / Fight Tracker / Key Moments, speed 1x/2x/4x/Pause/Skip-to-Finish) → RECAP (result card + stat changes + news + key moments + show-rating panel) | **CE** — visual 4-zone layout vs WMMA5's flat text feed |
| Cage heatmap / damage silhouette | NO | **Planned** (GUI_PLAN §7.1) — phase + initiator_fighter_id can derive position. Not yet rendered as a visual heatmap. | **CE** (planned; not yet rendered) |
| Pre-show commentary | Yes — shortcut keys to read at pace | PRE-FIGHT phase includes punditry "might" analysis + rivalry/memory context | **CE** |
| Per-beat commentary variety | Variable prose per beat | 7 fixed templates today (`_BEAT_COMMENTARY_TEMPLATES`); per CONVENTIONS §14 needs ≥8 variants per template. **The 100–200 non-highlight beats per fight have no prose** — only structured data. The fight_night.js generates on-the-fly from structured data. | **WMMA5** (more varied prose per beat) — **CE gap** |
| Commentator personality | Generic | `staff.pundit_bias` schema column exists but **not yet read** by the commentary generator (`punditry_svc.py` wrapper comment explicitly defers) | **WMMA5** (uses its broadcast-team system) — **CE gap** |
| Replay fights | n/a | `navigate('fight_resolution', {fight_id})` — replay mode reads existing beats from DB | **CE** |

**Fight engine verdict:** CAGE EMPIRE has a **far richer simulation
substrate** (6 337-line engine, 3 outcome types WMMA5 lacks, ELO
rankings, gameplan learning, explicit rivalry modifiers, 3 fully-
normalized beat/round/commentary tables). The 4-zone Fight Night UI
beats WMMA5's flat text feed. **But** WMMA5 still beats us on
per-beat commentary variety (we have 7 templates, they have varied
prose per beat) and named-commentator personality (we have the
schema column but don't read it). These are real, fixable gaps.

---

### 3.3 Finance (revenue, expenses, player levers)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Revenue model | Attendance (region-driven) + broadcast revenue + sponsorship + merch | ticket_sales (capacity × fill × price) + broadcast_revenue (real PPV model: buyrate × price × split, or flat rights fee) + sponsorship + merchandise + concessions | **CE** (more granular) |
| Player ticket-price lever | **NO — automatic, no player control** (handbook: "Ticket pricing is handled automatically and cannot be impacted by the player.") | Yes — `$20–$300` slider on Stack a Card screen | **CE — clear advantage** |
| Player marketing lever | Implicit via Marketing level | Yes — `$0–$500K` slider | **CE** |
| Player PPV-price lever | NO | Yes — `$30–$80` slider + PPV toggle | **CE** |
| Venue selection | Region-based (no specific venue picker) | Explicit venue picker: capacity / rental cost / venue_type (arena/ballroom/theater/outdoor) | **CE — clear advantage** |
| Live P&L preview | **NO — player books blind** | Yes — `get_event_preview` returns full P&L: fill_rate, gate, broadcast/PPV revenue, sponsorship, merch, concessions, fighter purses (estimated), staff salary, venue rental, marketing, insurance, total revenue, total expenses, net profit, cash_after_event, voice_kind, voice_phrase. Plus card_draw_score, card_draw_phrase, card_health_flags. | **CE — headline advantage** |
| Finance screen (UI) | Yes — full finance screen | **PLACEHOLDER** — "The Books" nav item falls through to placeholder. Only `get_player_cash()` (top-bar cash) is wired. No `get_finance_data` API method. No `finance.js` screen module. | **WMMA5** — **CE gap (Empire Builder fantasy underserved)** |
| Finance transactions log | n/a | `finance_transactions` table — 9 columns, 11 transaction types (ticket_sales, broadcast_revenue, merchandise, fighter_purse, venue_rental, staff_salary, medical_cost, signing_bonus, weight_cut_penalty, sponsorship, bonus_payment). One row per transaction. | **CE** (richer ledger — but not yet surfaced in UI) |
| Bankruptcy / rebuild model | Implicit (stability hit) | Explicit — `generate_new_ownership_news`, `generate_rebuild_continues_news`, `generate_rebuild_complete_news` (news.py:4247+) | **CE** |
| Cross-promotion financial pressure | Implicit | Rival AI has `budget_manager.py` (485 lines) + `signing_agent.py` (1 081 lines) — bids against the player for free agents | **CE** |

**Finance verdict:** CAGE EMPIRE has **a deeper, more player-controllable
finance model** than WMMA5 — explicit venue picker, three player
levers (ticket / marketing / PPV), live P&L preview, granular
transaction ledger, bankruptcy/rebuild narrative. But WMMA5 still
beats us because we **don't have a Finance screen** — the player
can't browse transaction history, see expense breakdowns over time,
or review their promotion's financial trajectory. The "Empire
Builder" fantasy has all its backend machinery in place and zero UI
to expose it.

---

### 3.4 Fighter Development (attributes, training camps, realization)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Attribute system | 25 attributes (Standing, Ground, Wrestling, Muay Thai, Mental, General sub-trees) | 25 attributes + 20 personality traits + 3 meta columns. Fight engine's `_load_fighter_stats` loads 48 per fighter. | **Tie** (similar depth) |
| Training camps | Yes (implicit — 1-month minimum lead implies camp) | Explicit `training_camps` table. `tick_processor._check_training_camps` runs camps. `services/training_svc.py` wraps it. Camp completion publishes `TRAINING_CAMP_COMPLETED`. | **CE** |
| Potential ≠ success | Implicit | Explicit — `effective_ceiling = potential × age_factor × health_factor × personality_factor`. Most fighters plateau well below their potential. Only young, healthy, disciplined fighters in good gyms get close. | **CE** (explicit realism) |
| Natural career arc | Implicit | Explicit `career_arc.py` (568 lines) — monthly tick. Growth (18–27): random physical maturation + technical learning. Prime (28–29): no natural change. Decline (30+): age-graded decay accelerating with each threshold (cardio -1/mo after 32, speed after 34, chin after 35, durability after 36, recovery after 33, flexibility after 35). Some age gracefully, some fall off a cliff. | **CE — clear advantage (the "father time catches up" stories)** |
| Morale | n/a | `morale.py` (1 660 lines) — fighter_personality.morale (0–100, clamped [10,95]) + 7 dynamic meta-fields (marketability, fan_friendliness, consistency, clutch_factor, promo_boost, injury_proneness, weight_cut_difficulty). Subscribes to FIGHT_RESOLVED / TITLE_CHANGED / TICK_ADVANCED / CAMP_COMPLETED / CAMP_INJURY / FIGHT_CANCELLED. Weekly drift toward 50, ring rust, win-streak bonus, birthday-based aging of injury_proneness. | **CE** (WMMA5 doesn't have a dynamic morale model this rich) |
| Fighter development UI | Yes (Training Teams screen) | **PLACEHOLDER** — "Training Camps" nav item falls through to placeholder. No `get_gyms_data` API. No `gyms.js` screen module. | **WMMA5** — **CE gap** |
| Scouting (potential realization) | Scouts affect what you can see about true attributes (dev-journals #83–85) | `scouting.py` (752 lines) — Gaussian-noise accuracy model (`noise_std = (100 - scout_attribute) / 4`), 3 bias types (style / nationality / aggression), 5 mistake types (overestimate_potential / underestimate_potential / misread_strength_weakness / miss_key_trait / confidence_mismatch). Reports write descriptors only (voice layer). Staleness tracked. | **CE** (deeper model) |
| Scouting UI | Yes (Scout button + Scouting Costs screen) | **PLACEHOLDER** — "Scouting" nav item falls through to placeholder. No `get_scouting_data` API. No `scouting.js` screen module. Fighter Profile has a Scout action button. | **WMMA5** — **CE gap (Talent Hunter fantasy underserved)** |
| Agent offers (mystery box) | NO | `agent_offers.py` (893 lines) — agent periodically calls with vague description + asking price. 5 offer types: unknown_talent / washout_veteran / style_specialist / contender_release / prospect_gamble. 10% chance per weekly tick (~5 offers/year). 14-day expiry. Voice descriptors ONLY — no raw attributes. | **CE — unique feature, but NOT wired to UI** (`agent_offers.get_active_offers` + `resolve_offer` exist but no `Api` wrapper, no `bridge.js` method, no UI screen) |
| Regens (new talent) | n/a | `tick_processor._check_retirements` generates successor fighter on retirement. `memory_svc.populate_style_echo` writes link if regen inherits retiring fighter's style archetype ("torch-passing" stories). | **CE** |

**Fighter development verdict:** CAGE EMPIRE has **a substantially
deeper fighter development backend** — explicit training camps,
effective_ceiling formula, natural career arcs, dynamic morale +
7 meta-fields, scouting with biases + mistakes, agent offers (mystery
box), regens with torch-passing memory links. **But** WMMA5 ships a
Training Teams screen and a Scouting screen. We ship neither.
Talent Hunter is one of the 5 core fantasies and **its primary UI is
a placeholder**.

---

### 3.5 Scouting (hidden potential, uncertain reports)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Scout accuracy | Affects what you can see | Gaussian noise: `noise_std = (100 - scout_attribute) / 4`. 90-eye scout ±2.5; 50-eye ±12.5; 10-eye ±22.5 | **CE** (explicit, tunable) |
| Scout biases | Implicit | 3 explicit types: style (+5/-5 to estimates), nationality (0.5x noise for familiar, 1.5x for unfamiliar), aggression (direct modifier) | **CE** |
| Scout mistakes | n/a | 5 explicit types with `mistake_rate%` chance: overestimate_potential / underestimate_potential / misread_strength_weakness / miss_key_trait / confidence_mismatch. **"Real people who make mistakes" directive.** | **CE — clear advantage** |
| Report content | Visible in fighter profile | `scouting_reports` table — 18 columns. Estimated potential, ceiling, floor, strengths, weaknesses as DESCRIPTORS (via voice.py). scout_confidence (0-100), is_stale, report_text (full prose). | **CE** |
| Staleness | n/a | Reports marked stale on camp completion, fight resolution, injury events. `mark_stale_reports()` callable. | **CE** |
| Scout as staff role | Yes | Yes — `staff.specialty` JSON stores eye_for_talent, technical_analysis, character_reading, mistake_rate, bias_*. Seed Phase 2: 2 scouts per promotion (20 total). | **Tie** |
| Scouting UI | Yes (Scout button + Costs screen) | **PLACEHOLDER** — "Scouting" nav item is a placeholder. No API, no JS screen, no bridge method. Fighter Profile has a Scout action button (but the player can't browse their scouting assignments or reports). | **WMMA5** — **CE gap** |

**Scouting verdict:** CAGE EMPIRE has **a vastly deeper scouting
model** (accuracy math, biases, 5 mistake types, staleness tracking).
But the scouting **screen is a placeholder**, which means the
player can't actually use any of this depth through a dedicated UI.
The Talent Hunter fantasy — "I find greatness before anyone else" —
is the most underserved of the 5 fantasies today.

---

### 3.6 Rival AI (promotion competition, bidding wars)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| AI books own cards | Yes | Yes — `rival_ai/event_scheduler.py` (471 lines) picks dates from archetype windows + rival collision avoidance + 15% counter-programming whim | **Tie** |
| AI signs own fighters | Yes | Yes — `rival_ai/signing_agent.py` (1 081 lines) bids for free agents, evaluates desirability, computes offer score | **Tie** |
| Combatative AI (out-bid player) | Yes (dev-journal #50) | Yes — `bidding_alerts` API surfaces when a rival is bidding on a fighter the player is pursuing. `counter_offer` API lets the player respond. Bidding wars are first-class. | **CE** (more explicit, player-facing) |
| AI roster management | Yes (implicit) | Yes — `rival_ai/cutting_agent.py` (352 lines) releases underperformers | **CE** (explicit) |
| AI staff management | n/a | Yes — `rival_ai/staff_manager.py` (588 lines) | **CE** |
| AI budgets | Implicit | Explicit `budget_manager.py` (485 lines) | **CE** |
| AI imperfection (personality-driven mistakes) | Implicit | Explicit `imperfection.py` (460 lines) — AI makes personality-driven mistakes (the "real people who make mistakes" directive extended to rival GMs) | **CE** |
| AI archetypes | Implicit | Explicit `archetypes.py` (437 lines) — different rival promotions play differently (regional / major / developmental archetypes with distinct event windows, signing behavior, budget discipline) | **CE** |
| AI matchmaker | Yes | `rival_ai/matchmaker.py` (636 lines) — books fights for rival cards | **Tie** |
| Rival AI UI | Yes (promotion screen) | `rival_promotions.js` (484 lines) — list of rivals, browse rival rosters, see bidding alerts | **CE** |

**Rival AI verdict:** CAGE EMPIRE **substantially outclasses WMMA5
here.** Explicit archetypes, imperfection, budget management, staff
management, cutting agent, signing agent — and the bidding-war
mechanic is **player-facing** (`bidding_alerts` + `counter_offer`),
which WMMA5 does not surface as directly. This is one of our
strongest advantages.

---

### 3.7 Staff System (hiring, effects, lifecycle)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Staff roles | Commentators, scouts, trainers, drug testing agencies | Coaches, scouts, doctors, cutmen, GMs, commentators (6 roles) | **Tie** (similar coverage) |
| Staff attributes | Implicit | `staff.specialty` JSON with role-specific fields (scout: eye_for_talent, technical_analysis, character_reading, mistake_rate, biases) | **CE** (more granular) |
| Staff lifecycle | Static | `rival_ai/staff_manager.py` (588 lines) — AI hires staff. Staff retire (`generate_staff_retired_news`), generate news, affect promotion quality | **CE** |
| Staff effects on broadcast | Yes (poor announcing = popularity penalty) | Yes — show_rating applies commentator bonus: +1 per 10 skill points on player's active commentators (max +15) | **CE** |
| Staff effects on scouting | Yes | Yes — scout accuracy model | **CE** (deeper) |
| Staff effects on training | Yes (trainers affect development) | Implicit (training camp logic in tick_processor) | **WMMA5** (more explicit) |
| Staff market UI | Yes | `staff_market.js` (721 lines) — 7-column table, role/skill filters, hire flow with salary + signing_bonus + contract_length sliders, live acceptance indicator | **CE** |
| Staff hire cost estimation | Implicit | Yes — `estimate_staff_hire_cost(staff_id)` API | **CE** |

**Staff verdict:** **CE is roughly even or slightly ahead.** Staff
market UI exists and is wired. The staff lifecycle (retirements,
rival AI hiring) is more developed than WMMA5's static model.
Weak spot: trainer effects on fighter development are less explicit
than WMMA5's.

---

### 3.8 News / Media (variety, voice, memory resurfacing)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| News topics | Fight results, title changes, injuries, retirements, signings, scouting, suspensions, weight cuts, hype, event recaps | All of WMMA5's + **memory resurfacing** ("Last met six years ago", "Former training partners"), **cross-promo news** (title fights, upsets across promotions), **15 small-reward templates** (prospect spotted, veteran comeback, gym producing talent, champion decline, title picture crowded, etc.), **bankruptcy/rebuild** narrative, **career arc decline** news ("father time catches up with {name}") | **CE — substantially deeper** |
| News engine size | n/a | `news.py` is **4 551 lines.** 48 headline templates across 6 result-type subgroups + 15 small-reward templates + suspension + cross-promo + bankruptcy + camp + memory + event hype. | **CE** |
| Voice layer | Generic text | Explicit `voice.py` (CONVENTIONS §14) — `ATTRIBUTE_DESCRIPTORS` (25 attrs × 7 tiers × 2-3 variants = ~500 strings), `PERSONALITY_DESCRIPTORS` (20 traits × 7 tiers = ~400 strings). NO raw attribute values, potential numbers, age-as-int, or streak counts in any player-facing text. | **CE — clear advantage** |
| News source tone | n/a | `_SOURCE_TONE_PREFIX` — different news sources have different tones (tabloid / serious / regional) | **CE** |
| Memory resurfacing | n/a | `interpretation/memory_engine.py` (690 lines) — surfaces 0-4 memories per fight: previous_fight, shared_gym, former_teammate, injury_history. Voice phrases: "Last met three years ago", "Split decision", "near return", "long road back", "indefinite" | **CE — unique feature** |
| Social media | n/a | `social.py` (1 226 lines) — fighter-driven posts with personality-driven voice. Callouts, trash-talk, brags, challenges, apologies. Beefs build into rivalries. 7-day cooldown per fighter. Cross-promo callouts (5% chance, same-WC only). | **CE — unique feature** |
| Echoes (player decisions resurface) | n/a | `interpretation/echoes_engine.py` (748 lines) — 4 echo types: SIGNING_ECHO ("Since you signed [Fighter] in [Month], he's won [N] straight"), CUT_ECHO, BOOKING_ECHO, SCOUTING_ECHO. Surfaces 2-3 per Advance Day. | **CE — unique feature** |
| News UI | Yes (mail/news screen) | `wire.js` (380 lines) — "The Wire" screen with filters, pagination. | **CE** (wired) |
| News variety discipline | n/a | Per CHANGELOG, template banks expanded to ≥8 variants per topic (48 total news templates + 40 show-rating descriptors + 224 SHORT voice phrases for narrow UI contexts) | **CE** |

**News/media verdict:** CAGE EMPIRE **crushes WMMA5 here.** 4 551-
line news engine vs WMMA5's generic text. Memory resurfacing,
social media, echoes (player-decision callbacks), 15 small-reward
templates, cross-promo news, voice-layer discipline — none of this
exists in WMMA5. This is the single biggest area of CE superiority
and the direct expression of the Soul doc's "the player collects
stories" law.

---

### 3.9 Calendar / Scheduling (date selection, rival events)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Calendar UI | Yes (separate screen) | `calendar.js` (515 lines) — month grid with player events (gold) + rival events (red) + today (blue) + past (greyed) + min-lead blocked (diagonal stripes) + conflict warning icons (⚠). Click date → detail panel + "Schedule Event on [Date]" → navigate to Stack a Card with event_date pre-filled. | **CE** (better integrated with matchmaking) |
| Date picker on event creation | Yes (date picker popup) | Yes — Calendar screen click → pre-fills event_builder | **Tie** |
| Rival events visible | Yes | Yes | **Tie** |
| Conflict warnings | NO | Yes — "Counter-programming risk" / "Short turnaround" / "Clear date" voice phrases. `get_date_conflicts(event_date)` API. | **CE** |
| Min-lead enforcement | Yes (1 month) | Yes (14 days — more lenient) | **Tie** (design choice) |
| Multi-event scheduling | Yes | Yes | **Tie** |
| Skip-to-show | n/a | Yes — `wireSkipToShow()` in app.js calls `advance_to_next_event` API + processing overlay with cancel button | **CE** |
| Sim-week | n/a | Yes — `wireSimWeek()` advances 7 days one-at-a-time with cancel + processing overlay + random fighter snapshot cycle | **CE** |

**Calendar verdict:** **CE is better than WMMA5.** Conflict
warnings, integrated click-to-schedule, sim-week and skip-to-show
controls with processing overlay. WMMA5's calendar is a separate
browse screen; ours is integrated into the booking flow.

---

### 3.10 Rankings + Titles

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Rankings model | Implicit (skill-based) | ELO (K=32, zero-sum) — `_update_rankings_after_resolution` in fight_engine. Stored in `rankings` table. | **CE** (transparent) |
| Rankings UI | Yes (with hover tooltips) | `rankings.js` (396 lines) — filterable by WC, gender, promo | **CE** (wired) |
| Titles model | Yes | Yes — `_resolve_title_after_fight` transfers/vacates belt. Title reigns tracked in `career_highlights`. | **Tie** |
| Titles UI | Yes (Titles button per fighter) | `titles.js` (341 lines) — "Belts" screen showing all champions + reigns | **CE** (wired) |
| Title implications in matchmaking | NO | Yes — "What's at Stake" modal: ranking implications + title-shot context | **CE** |
| Rankings ≠ Popularity distinction | Yes (handbook explicit; designer clarified in forum) | Yes — `rankings` table (skill) is separate from `fighters.marketability` (popularity). Both surfaced on matchmaking corner slots with distinct chips. | **Tie** |
| Cross-promo titles | n/a | `generate_cross_promo_title_news` — news when a champion moves promos / wins another promo's title | **CE** (unique) |

**Rankings + titles verdict:** **CE is roughly even or slightly
ahead.** ELO is more transparent than WMMA5's implicit model. The
"What's at Stake" modal is something WMMA5 lacks. Both screens are
wired.

---

### 3.11 Hall of Fame / Legacy

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| HoF induction | Yes | `hof_svc.py` (601 lines) — subscribes to `FIGHTER_RETIRED`, evaluates against eligibility (title_reigns ≥ 2 OR record_wins ≥ 30 OR wins ≥ 20 + title_reigns ≥ 1), inducts with `career_summary` + `career_highlights`, writes induction news. Idempotent. 60 seeded legends. | **CE** (deeper model) |
| Legacy state (gradient) | n/a | `interpretation/legacy_engine.py` (708 lines) — 4 MVP labels: building / established / legendary / forgotten. "Not a HoF score. A living interpretation." Distinct from career_phase. | **CE — unique feature** |
| Career phase | n/a | `interpretation/career_phase_engine.py` (841 lines) — current "where are they now" snapshot | **CE — unique feature** |
| Narrative families | n/a | `interpretation/narrative_families.py` (797 lines) — categorizes fighters into narrative archetypes | **CE — unique feature** |
| HoF UI | Yes (HoF screen) | **PLACEHOLDER** — "Legends" nav item falls through to placeholder. No `get_hof_data` API. No `hof.js` screen module. | **WMMA5** — **CE gap (Historian fantasy underserved)** |
| Record book UI | Yes | **PLACEHOLDER** — "The Record Book" nav item falls through to placeholder. No `get_records_data` API. No `records.js` screen module. | **WMMA5** — **CE gap (Historian fantasy underserved)** |
| Snapshot cache | n/a | `interpretation/snapshot_cache.py` (687 lines) + `fighter_descriptors` table — caches all interpretation outputs per fighter, refreshed on events. Short + long phrase variants. | **CE** (unique infra) |

**HoF/legacy verdict:** CAGE EMPIRE has **a substantially deeper
legacy backend** (HoF service with eligibility logic, 4-state
legacy engine, career phase engine, narrative families, snapshot
cache). But **two of the Historian fantasy's three screens are
placeholders.** The third (Archive) is wired. This means the player
can't currently browse their retired legends or the all-time record
book — the long-arc memory payoff that the Soul doc says is the
whole point of the game.

---

### 3.12 Save / Load

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| Save mechanism | Binary save file | `save_load.py` uses `shutil.copy2(DB_PATH, save_db_path)` — byte-for-byte file copy. The DB IS the save state. | **Tie** (different mechanisms, both work) |
| Preserves everything | Yes | Yes — every table, every row, every column, `sqlite_sequence` AUTOINCREMENT counters, WAL journal state, `schema_meta` row (v3.15.0). Live test passed: date, day, player_settings (7 rows), fighter_descriptors (4 464), events (1 981), news_items (5 287), contracts (1 125), fighters (4 464), schema_meta all survive intact. | **CE** (verified by test) |
| In-memory subscriber state | n/a | **NOT PRESERVED** — event-bus subscribers carry per-fighter in-memory caches (morale, rival_ai, career_arc). After `load_game`, safest path is to restart the process or call `reset_bus()` + `register_all_subscribers()` again. | **WMMA5** (less subscriber state to leak) — **CE gap** |
| `Api.conn` reference after `load_game` | n/a | **FRAGILE** — `Api.load_game` calls `_load_game` which overwrites `DB_PATH` in place and returns a NEW connection, but `Api` discards the new connection and keeps using `self.conn`. SQLite WAL re-reads the file header on each transaction so reads work, but the open transaction state may be stale. | **WMMA5** — **CE gap** |
| Save UI | Yes | `list_saves` / `save_game` / `load_game` API methods exist. Bridge methods exist. **No top-bar kebab menu UI affordance** per NAV_BUTTONS_AUDIT.md B9 — save/load is only reachable programmatically. | **WMMA5** — **CE gap** |
| Auto-save | n/a | `on_close` API method — auto-saves on window close. `auto_save_frequency` player setting (default 30 days). | **CE** (has auto-save; WMMA5 lacks) |

**Save/load verdict:** The byte-copy mechanism works and is
verified. But **the in-memory subscriber state isn't preserved on
load**, the `Api.conn` reference is fragile, and **there's no
save/load UI affordance in the top bar**. WMMA5 ships a working
save/load menu. CE's auto-save is a point in our favor.

---

### 3.13 UI / UX (layout, voice, interpretation layer)

| Aspect | WMMA5 | CAGE EMPIRE | Who's better? |
|---|---|---|---|
| UI toolkit | 2000s-era Windows desktop (tables, dropdowns, grey panels) | HTML/CSS/JS in pywebview — cards, gradients, portraits, venue icons, custom fonts (Source Serif Pro, Inter, Oswald, JetBrains Mono) | **CE — clear advantage** |
| Voice layer | Generic text | Explicit `voice.py` + CONVENTIONS §14 + VOICE_ENFORCEMENT.md. 8 voice-variant pickers, 40 show-rating descriptors, 48 news headline templates, 224 SHORT voice phrases for narrow UI contexts. NO raw attribute values anywhere. | **CE — clear advantage** |
| Interpretation layer | n/a | 6 interpretation engines (~5.8K lines): context_engine (1 298), headline_engine (1 267), career_phase_engine (841), echoes_engine (748), narrative_families (797), legacy_engine (708), memory_engine (690), snapshot_cache (687). Translates simulation → emotion. | **CE — unique infra** |
| Player decisions log | n/a | `player_decisions.py` (444 lines) — append-only log of every player action (sign / cut / book / scout / staff / finance levers / contracts). Surfaces via Echoes engine + Fighter Profile "Your History with [Fighter]" section. | **CE — unique feature** |
| Pre-game screen | n/a (just menu) | Yes — promotion-select grid with logos, cash, size/broadcast tier chips + player name input | **CE** |
| Top bar | n/a | Date + cash + Advance Day + Sim Week + Skip to Show buttons | **CE** |
| Sidebar nav | Yes | 5 groups × 19 items, voice-phrased names ("The Empire", "The Stable", "Open Market", "Stack a Card", "Bad Blood", "The Record Book") | **CE** (more thematic) |
| Back-stack | Yes | Yes — `_navStack` (cap 10, FIFO overflow) in app.js + `navigateBack()` | **Tie** |
| Dashboard | n/a | `dashboard.js` (739 lines) — 8 sections: Welcome/Logo, Gradient Header, Top Story, Promotion Status (5 stat tiles), Next Event, Fighter Watch (3 cards with momentum ring + form meter), Champions (3-col grid), Recent Results (4-col), Recent News | **CE** |
| Breadcrumb component | n/a | **MISSING** per NAV_BUTTONS_AUDIT.md B8 — no breadcrumb host in `index.html` | **WMMA5** (less polished but more consistent) — **CE gap** |
| Top-bar kebab (Save/Settings/Mods) | Yes (menu) | **MISSING** per NAV_BUTTONS_AUDIT.md B9 — only logo + date + cash + Advance Day button | **WMMA5** — **CE gap** |
| Hyperlinks between screens | Yes | Partial — fighter name hyperlinks in Dashboard are dead-click (NAV_BUTTONS_AUDIT.md B1) — though fighter_profile.js exists and is wired via `navigate('fighter_profile', {fighter_id})`. The Dashboard wiring needs verification post-audit. | **WMMA5** (more consistent) — **CE gap (status uncertain)** |

**UI/UX verdict:** CAGE EMPIRE has **a more modern, voice-driven,
thematic UI** than WMMA5 — pywebview + custom fonts + 6-engine
interpretation layer + player_decisions echo system. WMMA5 is a
2018 spreadsheet app. **But** CE has 3 known UI gaps: no breadcrumb
component, no top-bar kebab (save/settings/mods menu), and
dashboard fighter hyperlinks were dead-click per the NAV_BUTTONS
AUDIT (status post-audit unknown — fighter_profile.js does exist
and is wired).

---

## 4. Where CAGE EMPIRE is BETTER than WMMA5

In rough priority order (most-impactful first):

1. **Live P&L projection during card building.** WMMA5's single
   biggest UX gap. We have a full P&L preview (gate / PPV / sponsor /
   merch / concessions / purses / staff / venue / marketing / net)
   that updates after the player confirms the card. WMMA5 has nothing
   — the player books blind.
2. **Visual Compare modal with radar chart + voice phrases.** WMMA5's
   Compare is text-only. Ours is a 5-axis radar chart + 3 "might"
   voice phrases + matchup_phrase chip. Plus a separate Tale-of-Tape
   modal (UFC-style graphic) + What's-at-Stake modal (ranking
   implications) + Fan Pulse modal (rivalry/hometown/memory context).
3. **Calendar integration with conflict warnings.** WMMA5's calendar
   is a separate browse screen. Ours is integrated: click any
   eligible date → schedule event → conflict warnings
   ("Counter-programming risk" / "Short turnaround"). Plus Sim Week
   + Skip to Show controls with processing overlay.
4. **"Might" advice, not "easy mode".** WMMA5 deliberately refuses
   to predict a winner. We follow that principle (no Predicted
   Winner / Method / Confidence / Upset Risk cells) but **add**
   conditional voice phrases ("Reed's boxing vs Vale's wrestling —
   if Reed can keep it standing…"). The player gets more context
   without spoiling the result.
5. **9-field corner slot density.** WMMA5's corner shows ~10 fields
   as text. Ours shows portrait + name+nickname + rank chip +
   title chip + popularity tier label + momentum indicator + dense
   record+WC+age+style line + rivalry chip + recent-form chips.
   Visual, not text-dump.
6. **Confirm-card flow (staged fights, projection locked behind
   confirm).** WMMA5 persists each fight immediately on Add. We
   stage in JS, commit in one transaction. The player can build a
   draft, see the projection, then commit. Re-open Card to wipe.
7. **Personality-driven short-notice rejection (MM3.3).** WMMA5 has
   Inducements (a cost lever). We have **explicit willingness
   math** (risk_taking / ambition / professionalism / patience) and
   a fighter can flat-out refuse with a news item ("{fname} turns
   down short-notice bout"). More narrative, less transactional.
8. **Cross-event double-booking check (MM3.1).** WMMA5 filters
   already-booked fighters implicitly. We explicitly exclude
   fighters booked on ANY scheduled event within ±7 days.
9. **Training camp status field (MM3.2).** Each eligible fighter
   gets `ready` / `needs_camp` / `short_notice` — visible warning
   chip. WMMA5's camp model is implicit.
10. **Fight engine depth.** 6 337-line engine. 3 outcome types
    WMMA5 lacks (doctor-stoppage, corner-stoppage, no-contest).
    Explicit rivalry pressure modifiers (heat > 70 → +5 aggression
    / −5 composure). ELO rankings (K=32, zero-sum). Gameplan
    learning (winner updates preferred_gameplans; loser updates
    bad_matchup_tags). Per-fight data persisted in 3 normalized
    tables (fight_beats, fight_rounds, commentary_segments).
11. **4-zone Fight Night UI.** WMMA5's fight night is a flat text
    feed. Ours is a 4-zone fixed grid: Commentary Feed / Fight
    Status / Fight Tracker / Key Moments. 3-phase state machine
    (Pre-fight → Live → Recap). Speed controls 1x/2x/4x/Pause/
    Skip-to-Finish.
12. **Replay fights.** `navigate('fight_resolution', {fight_id})`
    reads existing beats from DB. WMMA5 doesn't have fight replay.
13. **News engine depth.** 4 551-line news engine. 48 headline
    templates. 15 small-reward templates (prospect spotted, veteran
    comeback, gym producing talent, champion decline, etc.).
    Memory resurfacing ("Last met six years ago"). Cross-promo
    news. Bankruptcy/rebuild narrative. Career arc decline news.
    WMMA5's news is generic by comparison.
14. **Voice layer discipline (CONVENTIONS §14).** 500+ attribute
    descriptor strings, 400+ personality descriptor strings, 40
    show-rating descriptors, 224 SHORT voice phrases for narrow UI
    contexts. NO raw attribute values, potential numbers, age-as-
    int, or streak counts in any player-facing text. WMMA5 has
    nothing this systematic.
15. **Memory resurfacing engine.** Surfaces 0–4 memories per fight
    (previous_fight, shared_gym, former_teammate, injury_history).
    Voice phrases: "Last met three years ago", "Former training
    partners", "Split decision", "near return", "long road back",
    "indefinite". The "every fight feels meaningful" directive.
16. **Social media system.** Fighter-driven posts with personality-
    driven voice. Callouts, trash-talk, brags, challenges,
    apologies. Beefs build into rivalries. 7-day cooldown per
    fighter. Cross-promo callouts (5% chance, same-WC only). WMMA5
    has nothing like this.
17. **Echoes engine (player decisions resurface).** 4 echo types:
    SIGNING_ECHO, CUT_ECHO, BOOKING_ECHO, SCOUTING_ECHO. Surfaces
    2–3 per Advance Day. "Since you signed [Fighter] in [Month],
    he's won [N] straight." This is the Agency reward the Soul doc
    says we should optimize for.
18. **Agent offers (mystery box gamble).** Agent periodically calls
    with vague voice-only description + asking price. 5 offer
    types: unknown_talent / washout_veteran / style_specialist /
    contender_release / prospect_gamble. 14-day expiry. The Talent
    Hunter fantasy's signature feature. **(Note: backend exists
    but UI not yet wired — see §5.)**
19. **Rival AI depth.** Explicit archetypes (regional/major/
    developmental). Imperfection engine (AI makes personality-
    driven mistakes). Budget manager. Cutting agent. Signing
    agent. Staff manager. The bidding-war mechanic is player-
    facing (`bidding_alerts` + `counter_offer`).
20. **Natural career arc engine.** Monthly tick. Growth (18–27),
    prime (28–29), decline (30+) with age-graded decay. "Father
    time catches up" + "still going strong at 38" stories emerge
    organically.
21. **Morale + dynamic meta-fields.** fighter_personality.morale
    (0–100, clamped [10,95]) + 7 dynamic fields (marketability,
    fan_friendliness, consistency, clutch_factor, promo_boost,
    injury_proneness, weight_cut_difficulty). Subscribes to 6
    events. Weekly drift, ring rust, win-streak bonus, birthday-
    based aging.
22. **Reputation system.** promotions.reputation + gyms.reputation
    dynamically updated by show ratings, title changes, drug-test
    suspensions, bankruptcy. 4-tier show-rating deltas. Clamped
    [10, 95].
23. **Player ticket-price + marketing + PPV-price levers.** WMMA5
    has none of these — ticket pricing is automatic. We give the
    player 3 financial levers + an explicit venue picker
    (capacity / rental / venue_type).
24. **Finance transaction ledger.** `finance_transactions` table —
    11 transaction types, one row per transaction. Full audit
    trail. (Not yet surfaced in UI — see §5.)
25. **Sim Week + Skip to Show + Advance Day controls with
    processing overlay.** Random fighter snapshot cycle every 10s
    during sim. Cancel button works between days.
26. **Auto-save on window close.** WMMA5 doesn't auto-save.

---

## 5. Where CAGE EMPIRE is WORSE than WMMA5

In rough priority order (most-impactful first):

1. **No Finance screen.** "The Books" nav item is a placeholder.
    The backend (`finance.py` 1 360 lines, `finance_transactions`
    table, `_BROADCAST_REVENUE` model, etc.) is fully built. The
    UI exposes only `get_player_cash()` for the top bar. The
    player can't browse transaction history, see expense breakdowns
    over time, or review their promotion's financial trajectory.
    The Empire Builder fantasy is **underserved**. **WMMA5 has a
    full finance screen.**
2. **No Scouting screen.** "Scouting" nav item is a placeholder.
    The backend (`scouting.py` 752 lines, `scouting_reports` table,
    Gaussian accuracy model, 3 bias types, 5 mistake types) is
    fully built. The Fighter Profile has a Scout action button but
    there's no dedicated screen to browse scouting assignments,
    active reports, stale reports, or scout staff. The Talent
    Hunter fantasy is **the most underserved of the 5 fantasies**.
    **WMMA5 has a scouting screen.**
3. **No Hall of Fame / Legends screen.** "Legends" nav item is a
    placeholder. The backend (`hof_svc.py` 601 lines, 60 seeded
    legends, induction on retirement, career_summary +
    career_highlights) is fully built. The player can't browse
    retired legends. The Historian fantasy is **underserved**.
    **WMMA5 has a HoF screen.**
4. **No Record Book screen.** "The Record Book" nav item is a
    placeholder. No `get_records_data` API. No `records.js`. The
    player can't see all-time leaders (most wins, most title
    defenses, longest reigns, etc.). The Historian fantasy is
    **doubly underserved**.
5. **No Rivalries / Bad Blood screen.** "Bad Blood" nav item is a
    placeholder. The backend (`rivalries.py` 1 052 lines, heat
    escalation + decay, 7 rivalry types, same-roster restrictions)
    is fully built. There's a `get_rivalry_partners(fighter_id)`
    API used by Matchmaking's Fan Pulse, but no browseable
    rivalries screen. The Puppet Master fantasy is **underserved**.
6. **No Training Camps / Gyms screen.** "Training Camps" nav item
    is a placeholder. The backend (`training_camps` table,
    `tick_processor._check_training_camps`, `services/training_svc`)
    is fully built. The player can't see their fighters' camp
    schedules, gym assignments, or camp outcomes. The Talent
    Hunter + Empire Builder fantasies are both underserved here.
7. **No Contracts / Deals screen.** "Deals" nav item is a
    placeholder. `contracts.py` (326 lines) handles sign_free_agent
    + counter_offer + extensions, but there's no UI to browse
    expiring contracts, contract history, or salary commitments.
8. **Agent Offers not wired to UI.** `agent_offers.py` (893 lines,
    5 offer types, 14-day expiry, weekly tick generation) exists
    but is **not exposed on the Api class, not in bridge.js, not
    in any UI screen**. This is the Talent Hunter fantasy's
    signature feature and it's dark. (Confirmed by grep: no
    `get_active_offers` or `resolve_offer` in `app_web.py`.)
9. **No Hype slider per fight.** WMMA5's None/Small/Medium/Large
    slider that pushes marketing weight behind one fighter. Risk/
    reward popularity lever. We have nothing equivalent.
10. **No Booking Adviser.** WMMA5's tabs surfacing opportunities
    (hometown fighters for a regional show, debuts, #1-contender
    fights, win streaks). We have a "Hometown" roster filter but
    no tabbed adviser.
11. **No Inducements system.** WMMA5's 4-category personality-
    driven extra-cost demands (training-time, opponent-specific,
    difficulty, weight-class). Fighters don't demand extra money
    for tough/short-notice bouts — they either accept or refuse
    outright. We're missing the financial middle ground.
12. **No Replacement Offers.** WMMA5's signature narrative
    feature — when a booked fighter withdraws, eligible fighters
    privately self-offer to step in via email, won't turn down if
    accepted within 7 days. Generates underdog stories + short-
    notice heroics. We have nothing.
13. **No Event Disruption penalty.** WMMA5 penalizes up to −15%
    Commercial Rating for severely disrupted shows (main-event
    injuries hurt most). We have no penalty model for late card
    changes.
14. **No Absences panel.** WMMA5's single place to see who's
    unavailable and why (dev-journal #144). Injured/suspended
    fighters just disappear from our roster; no UI to review.
15. **No Quick Move Fight.** WMMA5's button to move a booked fight
    to another scheduled event without cancel/rebook (dev-journal
    #22). We require cancel + rebook.
16. **Per-beat commentary variety is thin.** 7 fixed templates
    today (`_BEAT_COMMENTARY_TEMPLATES`). The 100–200 non-
    highlight beats per fight have no prose. Per CONVENTIONS §14
    needs ≥8 variants per template. Action-type-specific prose,
    phase-specific prose, momentum-aware prose all missing. WMMA5
    has more varied per-beat prose.
17. **Commentator personality not used.** `staff.pundit_bias`
    schema column exists but the commentary generator doesn't
    read it. WMMA5 uses its broadcast-team system.
18. **No top-bar kebab menu (Save/Settings/Mods).** NAV_BUTTONS
    _AUDIT.md B9: only logo + date + cash + Advance Day button.
    Save/Load is only reachable programmatically. WMMA5 ships a
    menu.
19. **No breadcrumb component.** NAV_BUTTONS_AUDIT.md B8: no
    breadcrumb host in `index.html`. WMMA5 doesn't have this
    either, but modern sports games do.
20. **In-memory subscriber state not preserved on load.** After
    `load_game`, morale/rival_ai/career_arc may carry stale per-
    fighter caches. Safest path is to restart the process or
    call `reset_bus()` + `register_all_subscribers()` again.
21. **`Api.conn` reference after `load_game` is fragile.** `Api`
    discards the new connection and keeps using `self.conn`.
    SQLite WAL re-reads the file header so reads work, but open
    transaction state may be stale.
22. **Dashboard fighter hyperlinks may be dead-click.**
    NAV_BUTTONS_AUDIT.md B1 flagged this; fighter_profile.js
    does exist and is wired via `navigate('fighter_profile',
    {fighter_id})`, but the audit's specific complaint about
    Dashboard's `console.log`-only click handler (dashboard.js
    lines 419–429) needs verification that it's been fixed.

---

## 6. Screens / Features still MISSING (placeholder audit)

Methodology: Read `src/web/js/app.js` NAV_GROUPS (lines 29–59) and
the `navigate()` switch (lines 600–720). Compared against the JS
module files actually present in `src/web/js/`. A nav item is
"placeholder" if `navigate()` has no explicit case for it AND no
`window.CE.<screenName>` module is loaded.

### 6.1 Sidebar nav items (19 total)

| Group | Item | Nav ID | Has JS module? | Has API method? | Status |
|---|---|---|---|---|---|
| HOME | The Empire | `dashboard` | ✅ dashboard.js (739) | ✅ get_dashboard_data | **WIRED** |
| HOME | Calendar | `schedule` | ✅ calendar.js (515) | ✅ get_calendar_data | **WIRED** |
| HOME | The Wire | `news` | ✅ wire.js (380) | ✅ get_wire_data | **WIRED** |
| FIGHTERS | The Stable | `roster` | ✅ roster.js (443) | ✅ get_roster_data | **WIRED** |
| FIGHTERS | Open Market | `free_agents` | ✅ free_agents.js (970) | ✅ get_free_agents | **WIRED** |
| FIGHTERS | Scouting | `scouting` | ❌ | ❌ | **PLACEHOLDER** |
| FIGHTERS | Legends | `hall_of_fame` | ❌ | ❌ | **PLACEHOLDER** |
| EVENTS | Stack a Card | `event_builder` | ✅ event_builder.js (1 269) | ✅ get_event_builder_data | **WIRED** |
| EVENTS | Matchmaking | `matchmaking` | ✅ matchmaking.js (1 964) | ✅ get_matchmaking_data | **WIRED** |
| EVENTS | The Archive | `past_events` | ✅ archive.js (lines TBD) | ✅ get_archive_data | **WIRED** |
| BUSINESS | The Books | `finance` | ❌ | ❌ (only `get_player_cash`) | **PLACEHOLDER** |
| BUSINESS | Deals | `contracts` | ❌ | ❌ | **PLACEHOLDER** |
| BUSINESS | Staff Market | `staff_market` | ✅ staff_market.js (721) | ✅ get_staff_market_data | **WIRED** |
| BUSINESS | The Competition | `rival_promotions` | ✅ rival_promotions.js (484) | ✅ get_rival_promotions | **WIRED** |
| BUSINESS | Training Camps | `gyms` | ❌ | ❌ | **PLACEHOLDER** |
| WORLD | The Rankings | `rankings` | ✅ rankings.js (396) | ✅ get_rankings_data | **WIRED** |
| WORLD | Belts | `titles` | ✅ titles.js (341) | ✅ get_titles_data | **WIRED** |
| WORLD | Bad Blood | `rivalries` | ❌ | ❌ (only `get_rivalry_partners`) | **PLACEHOLDER** |
| WORLD | The Record Book | `records` | ❌ | ❌ | **PLACEHOLDER** |

### 6.2 Tally

- **12 of 19 sidebar screens are WIRED** (63%)
- **7 of 19 sidebar screens are PLACEHOLDERS** (37%)
- **Plus 1 destination screen (Fight Night) wired but not in sidebar** — `fight_resolution` nav ID, handled in `navigate()` via `window.CE.fightNight` (fight_night.js, 1 410 lines). Not in sidebar by design (it's a destination, not a starting point — per GUI_PLAN §10.3).
- **Plus 1 destination screen (Fighter Profile) wired but not in sidebar** — `fighter_profile` nav ID, handled via `window.CE.fighterProfile` (fighter_profile.js, 970 lines). Also by design.

### 6.3 Backend-rich but UI-dark (the 7 placeholders)

These 7 placeholders are the critical gap. Each has substantial
backend machinery already built — the work remaining is wiring, not
new systems:

| Placeholder | Backend module(s) | Lines of code | Soul fantasy served |
|---|---|---|---|
| **Scouting** | `scouting.py` (752) + `scouting_svc.py` (22) | 774 | Talent Hunter |
| **Legends (HoF)** | `services/hof_svc.py` (601) + `interpretation/legacy_engine.py` (708) | 1 309 | Historian |
| **The Books (Finance)** | `finance.py` (1 360) + `finance_svc.py` (24) + `finance_transactions` table | 1 384 | Empire Builder |
| **Deals (Contracts)** | `services/contracts.py` (326) | 326 | Empire Builder |
| **Training Camps (Gyms)** | `services/training_svc.py` (46) + `tick_processor._check_training_camps` + `training_camps` table | ~46+ | Talent Hunter + Empire Builder |
| **Bad Blood (Rivalries)** | `rivalries.py` (1 052) + `services/rivalries_svc.py` (25) | 1 077 | Puppet Master |
| **The Record Book (Records)** | (queries against existing tables — no new module needed) | 0 | Historian |

**Plus the dark-but-built system:**

| System | Backend module(s) | Lines | Status |
|---|---|---|---|
| Agent Offers (mystery box) | `agent_offers.py` (893) | 893 | **NOT in Api, NOT in bridge.js, NOT in any UI** |

### 6.4 Soul fantasy coverage matrix

Mapping the 5 core fantasies to their primary screens:

| Fantasy | Primary screens | Wired? | Status |
|---|---|---|---|
| **Talent Hunter** | Scouting, Training Camps, (Agent Offers), Free Agents | 1 of 3 wired (Free Agents only) | **Underserved — 2 placeholders + 1 dark** |
| **Empire Builder** | The Books, Deals, Staff Market, Rival Promotions, Stack a Card | 3 of 5 wired | **Partially underserved — 2 placeholders** |
| **Kingmaker** | Matchmaking, Rankings, Belts, The Wire, Stack a Card | 5 of 5 wired | **Fully served** ✅ |
| **Historian** | Legends (HoF), The Record Book, The Archive | 1 of 3 wired (Archive only) | **Underserved — 2 placeholders** |
| **Puppet Master** | Bad Blood (Rivalries), Rival Promotions, Training Camps | 1 of 3 wired (Rival Promotions only) | **Underserved — 2 placeholders** |

**Verdict:** Of the 5 core fantasies, **only Kingmaker is fully
served by wired screens.** The other 4 fantasies each have 2
placeholder screens. The Kingmaker loop (Stack a Card → Matchmaking
→ Fight Night → Archive) is the heartbeat and it works end-to-end.
The other 4 fantasies have rich backends but the player can't
reach them through dedicated UIs.

---

## 7. Recommendations — Priority Order

These are the highest-leverage next actions, in priority order. The
guiding principle: **wire the rich backends to UI before building
new systems.** Each of the top 7 items is "backend exists, UI
doesn't" — that's the lowest-effort, highest-impact work.

### P0 — Wire the 4 missing core-fantasy screens

These are the screens that close 4 of the 5 Soul fantasies. Each
has a fully-built backend. Each is a 1–3 day UI build (new JS
module + bridge method + Api wrapper + navigate() case).

1. **Build the Scouting screen** (Talent Hunter).
   - Backend: `scouting.py` + `scouting_reports` table.
   - Needed: `get_scouting_data(promo_id)` API (active assignments,
     recent reports, scout staff list with eye_for_talent etc.),
     `assign_scout(scout_id, fighter_id)` API (already exists in
     scouting.py), `scouting.js` screen with 3 panels: My Scouts /
     Active Assignments / Recent Reports. Wire the existing Scout
     action button on Fighter Profile to call `assign_scout`.
   - Soul impact: **the most underserved fantasy gets its primary
     UI**.

2. **Build the Legends (HoF) screen** (Historian).
   - Backend: `services/hof_svc.py` + `hall_of_fame` table (60
     seeded legends + inductees from gameplay).
   - Needed: `get_hof_data(filters)` API (inductees with
     career_summary, career_highlights, induction date, sortable
     by era/weight class/promotion), `hof.js` screen with filterable
     inductee cards + click into a retired fighter's profile.
   - Soul impact: "The world remembers what I built" — gives the
     long-arc payoff the Soul doc says is the whole point.

3. **Build the Books (Finance) screen** (Empire Builder).
   - Backend: `finance.py` + `finance_transactions` table.
   - Needed: `get_finance_data(promo_id, time_range)` API
     (transactions in date range, grouped by type; monthly P&L
     summary; cash trajectory), `finance.js` screen with revenue/
     expense breakdowns + transaction log + cash-over-time chart.
   - Soul impact: "My promotion dominates the sport" — Empire
     Builder's primary strategic screen.

4. **Build the Bad Blood (Rivalries) screen** (Puppet Master).
   - Backend: `rivalries.py` + `rivalries` table.
   - Needed: `get_rivalries_data(filters)` API (active rivalries
     with heat level, type, origin narrative, head-to-head record;
     dormant rivalries; sortable by heat), `rivalries.js` screen
     with rivalry cards + click into a fight pair's history.
   - Soul impact: "The sport evolves because of my decisions" —
     surfaces the conflict the player has been brewing.

### P1 — Wire the agent_offers system (Talent Hunter signature feature)

5. **Expose agent_offers to the UI.** Backend exists (893 lines, 5
   offer types, weekly tick generation, 14-day expiry). Just needs:
   - `get_active_offers()` Api wrapper (already exists in
     `agent_offers.py`)
   - `resolve_offer(offer_id, accept)` Api wrapper (already exists)
   - `bridge.getActiveOffers()` + `bridge.resolveOffer()` methods
   - UI surface: either a dedicated "The Inbox" screen, or a panel
     on the Dashboard, or a modal triggered by an alert badge on
     the top bar. (Recommend: top-bar alert badge + modal —
     cheapest to build, highest dopamine.)
   - Soul impact: **the Talent Hunter's signature dopamine loop
     (mystery box gamble) is currently dark.** Wiring this is
     probably the single highest dopamine-per-line-of-code change
     in the whole project.

### P2 — Build the remaining 3 missing screens

6. **Build the Record Book screen** (Historian).
   - No new backend needed — pure SQL against existing tables
     (fighter_career, fight_history, title_reigns, hall_of_fame).
   - Needed: `get_records_data(category)` API (all-time leaders:
     most wins, most KO wins, most sub wins, most title defenses,
     longest reign, most fights, etc.), `records.js` screen with
     category tabs + top-10 lists.
   - Soul impact: completes the Historian fantasy (alongside HoF).

7. **Build the Training Camps (Gyms) screen** (Talent Hunter +
   Empire Builder).
   - Backend: `training_camps` table + `tick_processor._check_
     training_camps` + `gyms` table.
   - Needed: `get_gyms_data(promo_id)` API (player's fighters'
     current camp assignments, gym reputations, camp outcomes
     history), `gyms.js` screen with camp schedule + gym list +
     assign-fighter-to-gym flow.
   - Soul impact: completes the Talent Hunter development loop
     (scout → sign → assign to camp → watch growth).

8. **Build the Deals (Contracts) screen** (Empire Builder).
   - Backend: `services/contracts.py` (326 lines).
   - Needed: `get_contracts_data(promo_id, filter)` API (active
     contracts with salary + end_date + bonus_structure; expiring
     within 90 days; renegotiation candidates), `contracts.js`
     screen with contract table + offer-extension flow.
   - Soul impact: completes the Empire Builder financial picture
     (alongside The Books).

### P3 — Add the missing WMMA5 matchmaking features

9. **Hype slider per fight** (None / Light / Heavy). Risk/reward
   popularity lever. Backend: add `hype_level` column to `fights`
   table + apply in morale.py + show_rating.py. Frontend: slider
   per booked fight in matchmaking.js. **High story-generation
   value** ("I hyped Watson to the moon and she got KO'd in 14
   seconds").
10. **Booking Adviser** (4 tabs: Hometown / Win Streaks / Debuts /
    Title Picture). Opportunity-surfacing panel, not auto-book.
    Backend: SQL queries (mostly exist as roster filters already).
    Frontend: collapsible side panel in matchmaking.js.
11. **Inducements** (4 categories: training-time / opponent /
    difficulty / weight-class). Per-fight personality-driven
    extra-cost demands. Backend: compute inducement cost in
    `book_fight` + add to projected expenses. Frontend: inducement
    icons per booked fight. **Closes the gap between outright
    rejection (MM3.3) and unconditional acceptance.**
12. **Replacement Offers** (when booked fighter withdraws). Backend:
    on injury during camp, trigger private offers from eligible
    rostered fighters via news system. Frontend: accept/reject via
    news item. **High story-generation value** (underdog stories,
    short-notice heroics).
13. **Event Disruption penalty** (up to −15% Commercial Rating).
    Backend: add `event_disruption_score` column to events; apply
    in show_rating.py. Frontend: surface current disruption score
    on matchmaking screen once event is within 7 days.
14. **Absences panel** (single list of unavailable fighters +
    reason + return date). Backend: SQL query (already exists in
    `_get_available_fighters_for_card` filter logic). Frontend:
    collapsible panel in matchmaking.js.
15. **Quick Move Fight** (button per booked fight to move to
    another scheduled event). Backend: new API method. Frontend:
    icon button per fight card.

### P4 — Improve the fight engine's commentary variety

16. **Per-beat commentary expansion.** Replace the 7 fixed
    templates with action-type × phase × outcome × momentum_band
    template matrix (per `RESEARCH_FIGHT_NIGHT.md` §7.1). Generate
    one `commentary_segments` row per beat with `segment_type='beat'`.
    Target: ≥8 variants per template per CONVENTIONS §14.
17. **Read `staff.pundit_bias` in commentary generator.** Named-
    pundit interjections. The schema column exists; the wrapper
    comment explicitly defers this. Wire it.

### P5 — UI/UX polish

18. **Top-bar kebab menu** (Save / Settings / Mods). NAV_BUTTONS
    _AUDIT.md B9. The save/load APIs exist; just needs a dropdown
    UI affordance in the top bar.
19. **Breadcrumb component.** NAV_BUTTONS_AUDIT.md B8. "The Stable
    / John Vale" pattern. Add breadcrumb host to `index.html`.
20. **Verify Dashboard fighter hyperlinks are live.** NAV_BUTTONS
    _AUDIT.md B1. The audit flagged `console.log`-only handlers;
    fighter_profile.js exists and is wired — confirm the Dashboard
    click handlers now call `navigate('fighter_profile',
    {fighter_id})`.

### P6 — Save/load robustness

21. **Fix in-memory subscriber state on load.** After `load_game`,
    either restart the process, or call `reset_bus()` +
    `register_all_subscribers()` again. Document this in
    `save_load.py`.
22. **Fix `Api.conn` reference after `load_game`.** Either swap to
    the new connection, or document the WAL-mode workaround + add
    a re-navigate-to-Dashboard step in the JS after load.

### P7 — Cage heatmap / damage silhouette

23. **Cage heatmap visualization.** GUI_PLAN §7.1 calls for this.
    Derive position from `phase` + `initiator_fighter_id`. Render
    as a canvas/SVG overlay in the Fight Night UI. The Soul doc
    emphasizes visual storytelling; this is the natural extension
    of the 4-zone Fight Night screen.

---

## 8. The One-Sentence Verdict

**CAGE EMPIRE has built a deeper, more story-rich simulation than
WMMA5 — but WMMA5 ships more of its simulation to the player.** The
matchmaking loop (Kingmaker fantasy) is fully wired and better than
WMMA5's; the other 4 fantasies have rich backends waiting behind 7
placeholder screens. Wire those 7 screens (and the dark agent_offers
system) and CAGE EMPIRE becomes the better game across the board.

The work that remains is mostly wiring, not new systems.

---

## 9. Cross-References

- `docs/CAGE_EMPIRE_SOUL.md` — 5 core fantasies, prime directive
- `docs/RESEARCH_WMMA5_MATCHMAKING.md` — WMMA5 matchmaking deep-dive (999 lines)
- `docs/RESEARCH_WMMA5_FM_V2.md` — WMMA5 + FM V2, 5 user complaints mapped (762 lines)
- `docs/RESEARCH_FIGHT_NIGHT.md` — fight engine audit + recommendations (844 lines)
- `docs/RESEARCH_MATCHMAKING_CURRENT_STATE.md` — current state analysis (500 lines)
- `docs/RESEARCH_MATCHMAKING_SHOWRATING.md` — show-rating research (851 lines)
- `docs/NAV_BUTTONS_AUDIT.md` — nav wiring audit (415 lines)
- `docs/MASTER_PLAN_MATCHMAKING_V2.md` — the V2 plan that closed FM_V2's 5 priorities
- `docs/REWARD_REVIEW.md` — 5 player rewards (Ownership / Agency / Discovery / Mastery / Anticipation)
- `docs/RESEARCH_FIGHTERGEN_RIVALAI_STAFFLIFE.md` — fighter gen + rival AI + staff life research

---

*End of comparison document. Total source files read: 25+ Python
modules, 15 JS screen modules, 7 research docs, 1 soul doc. File
written to `docs/REVIEW_WMMA5_COMPARISON.md`.*
