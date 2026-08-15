> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Screen Data Audit (SCREEN-DATA-AUDIT)

> **Task ID:** SCREEN-DATA-AUDIT · **Mode:** RESEARCH ONLY — no code changes
> **Scope:** For each of the 4 screens being rebuilt (Dashboard, Roster, Free Agents, Fighter Profile), document what data is available in the live DB, what interpretation-layer fields exist, what should be displayed / hidden / collapsible, and what voice phrases (SHORT vs LONG) each screen needs.
> **Source DB:** `data/cage_empire.db` (engine_version `1.8.0`, 4 464 fighters, sim date `2026-10-30`)
> **Cross-refs:** `docs/GUI_PLAN.md` §6 (screen specs), `docs/CAGE_EMPIRE_SOUL.md`, `upload/VOICE_ENFORCEMENT.md`, `src/app_web.py`, `src/web/js/dashboard.js`

---

## 0. Executive Summary (read this first)

| Screen | API status today | DB data available | Interpretation gaps blocking redesign |
|---|---|---|---|
| Dashboard | ✅ Implemented (`get_dashboard_data`, 8 sections in `dashboard.js`) | Rich, **except** 1-row `finance_transactions` for promo 1 (sparkline flat), 0 scheduled events for promo 1 (Next Event empty state) | `potential_desc` NULL for 100% of fighters (no blocker — Dashboard doesn't use it) |
| Roster | ❌ Placeholder (`get_roster_data` returns stub) | Full coverage: 60 fighters in promo 1, all `fighter_descriptors` populated | `narrative_family` NULL for 99.4% of roster; "Narrative" column would be empty for nearly every row |
| Free Agents | ❌ Placeholder (`get_free_agents` returns stub) | 4 082 active FAs, but **`scouting_reports` table is 0 rows** | **CRITICAL:** ceiling display has no source data — every FA shows `????`. Estimated-cost calc has no `contract_cost_estimate` source. Must derive from `agent_offers.asking_price` (also nearly empty: 2 expired rows for promo 1) |
| Fighter Profile | ❌ Placeholder (`get_fighter_profile` returns stub) | Rich join: fighters + descriptors + career + bios + fight_history + titles + rankings + rivalries + contracts | Same interpretation gaps + `fighter_memory_links` covers only 215 of 4 464 fighters (5%) — "Memory Links" section will be sparse |

### Critical interpretation-layer NULL counts (across 4 464 fighters)

| Column | NULL count | % NULL | Notes |
|---|---|---|---|
| `potential_desc` | 4 464 | **100%** | Column exists, never populated by interpretation engine |
| `public_narrative` | 4 464 | **100%** | Same |
| `narrative_family` | 4 423 | 99.4% | Only 27 fighters have a value (25 veterans, 13 prodigies, 2 cinderella, 1 fallen_champion) |
| `career_health_desc` | 0 | 0% | ✅ Full coverage |
| `overall_desc` | 0 | 0% | ✅ Full coverage |
| `career_stage` | 0 | 0% | ✅ Full coverage |
| `momentum` | 0 | 0% | ✅ Full coverage |

### Voice variant coverage (VOICE_ENFORCEMENT §5.1)

| Label column | Distinct labels | Worst coverage | Bar (≥8 variants) |
|---|---|---|---|
| `momentum_short` | 5 | `collapsing`=8 ✅ | ✅ PASS |
| `pressure_short` | 3 | `minimal`=8 ✅ | ✅ PASS |
| `career_phase_short` | 6 | `declining`=8 ✅ | ✅ PASS |
| `legacy_state_short` | 4 | `legendary`=1 ❌ | ❌ FAIL — legendary is the Hall-of-Fame tier, only 1 phrase |
| `narrative_family_short` | 4 | `fallen_champion`=1, `cinderella_story`=2 ❌ | ❌ FAIL — but 99.4% NULL anyway |
| `momentum` (LONG) | 5 | `collapsing`=6 ❌ | ❌ FAIL (was 8 in §3 bar) |
| `career_phase` (LONG) | 6 | `declining`=7 ❌ | ❌ borderline |
| `legacy_state` (LONG) | 4 | `legendary`=1 ❌ | ❌ FAIL |

### Tabloid-cliché sweep (VOICE_ENFORCEMENT §5.4)

```sql
SELECT headline FROM news_items
WHERE headline LIKE '%SCANDAL%' OR headline LIKE '%stunning development%'
   OR headline LIKE '%Storm:%';
```
**Result: 0 rows.** ✅ P0 from VOICE_ENFORCEMENT is RESOLVED in production.

### Headline repetition check (VOICE_ENFORCEMENT §5.2)

Top 3 most-repeated `daily_headlines.headline_text` (26 sim-days of data):

| Headline | Times shown | Span | Verdict |
|---|---|---|---|
| `"The bottom has dropped out, and fast"` | 6 | 2026-10-21 → 2026-11-11 | ⚠️ Repeats across 3-week span, but not 2 consecutive days for same fighter |
| `"The kind of upset that defines a week"` | 5 | 2026-10-20 → 2026-11-11 | ⚠️ Same pattern |
| `"The division's brightest young talent, surging"` | 5 | 2026-10-28 → 2026-11-10 | ⚠️ Same |

Verdict: voice variety has improved since VOICE_ENFORCEMENT was written (12-19 distinct phrases per headline_type over 26 days), but ≥8-variant threshold is still missed for `legendary`, `collapsing`, `declining`, `cinderella_story`, `fallen_champion` labels.

---

## 1. Screen 1 — Dashboard ("The Empire")

### 1.1 Current implementation status

- **Python API:** `app_web.py:381 get_dashboard_data(promo_id)` — fully implemented, returns a dict with 13 top-level keys (`promo_id`, `promo_name`, `promo_logo_b64`, `sim_date`, `month_name`, `year`, `cash`, `reputation`, `reputation_phrase`, `fan_trust`, `fan_trust_phrase`, `size_tier`, `broadcast_tier`, `roster_count`, `champ_count`, `total_wcs`, `top_story`, `next_event`, `fighter_watch`, `champions`, `recent_results`, `recent_news`).
- **JS renderer:** `web/js/dashboard.js` (451 lines, 8 sections rendered — see lines 119-389).
- **GUI_PLAN §6.1 spec:** 6 sections (Top Story, Promotion Status, Next Event, Fighter Watch, Champions, Recent News).
- **Discrepancy:** Dashboard ships 8 sections today (Welcome, Gradient Header, Top Story, Promotion Status, Next Event, Fighter Watch, Champions, Recent Results, Recent News). GUI_PLAN calls for 6. The redesign should drop "Welcome" + "Gradient Header" (decorative) and merge "Recent Results" into a tighter card.

### 1.2 What data is available (live DB)

| GUI_PLAN section | DB table(s) | Live data status | Sample |
|---|---|---|---|
| Top Story | `daily_headlines WHERE headline_type='top_story'` | ✅ 26 rows (1 per sim-day) | `"The prodigy turns heads again"` (fighter 143, 2026-11-14) |
| Promotion Status (5 tiles) | `promotions` (cash, reputation, fan_trust, size_tier, broadcast_tier) + `fighters` (roster_count) + `titles` (champ_count) | ✅ Full coverage | promo 1: cash=$50M, rep=85, fan_trust=75, roster=60, champs=6 of 10 WCs |
| Cash sparkline (data viz) | `finance_transactions WHERE promotion_id=? GROUP BY transaction_date` | ⚠️ **Only 1 row for promo 1** ($80M sponsorship on 2026-01-01) — sparkline will render flat. Most finance activity is on promo 4. Need either a multi-promo query OR a synthetic 7-day rolling balance. | promo 1 net cash by day = 1 entry |
| Next Event | `events WHERE status='scheduled' AND promotion_id=? ORDER BY event_date` | ⚠️ **0 scheduled events for promo 1** (player's default promo). 7 scheduled events total exist (promos 3, 6, 7, 9, 10). For promo 1, the empty state fires: *"No events scheduled. Time to build a card."* | promo 10: `"French Savate Championship 81"` on 2026-11-01 |
| Fighter Watch (3 cards) | `daily_headlines WHERE headline_type IN ('fastest_rising','biggest_fall')` + `fighter_descriptors` (momentum_short, pressure_short, career_phase_short) + `fight_history` (last5) | ✅ 4 headline types exist: top_story, fastest_rising, biggest_fall, upset_of_week (unused). The "HOTTEST STREAK" card uses a fallback query: `WHERE momentum LIKE 'very_high||%'` (14 fighters qualify, e.g. Cristiano Cardim, Sora Yamashita) | sample: `"The matchmakers can't ignore him anymore"` (fighter 1317) |
| Champions strip | `titles WHERE promotion_id=? AND is_vacant=0` joined to `fighters` + `weight_classes` | ✅ 6 held titles for promo 1 (Heavyweight=48, LHW=26, MW=30, WW=43, LW=45; 3 vacant) | fighter 48 Alexander Pavlov 'Tao' = HW champ since 2026-03-13, 2 reigns, 0 defenses |
| Recent News (last 5) | `news_items ORDER BY published_at DESC LIMIT 5` | ✅ 4 500+ news items, 19 topics | latest: `"Kenji Mori makes weight"` (2027-05-30) |
| Recent Results (last 4) | `events WHERE status='completed'` JOIN `show_ratings` | ✅ 1 974 completed events, 86 with show_ratings. Voice phrase from `rating_description` column: `"a highly entertaining show that delivered on expectations"` | event 2042: overall_rating=84 |

### 1.3 Interpretation-layer fields used

| Field | Where read | Display use | Voice variant |
|---|---|---|---|
| `momentum` (LONG `label\|\|phrase`) | Fighter Watch card phrase | Quote text on watch card | LONG |
| `momentum_short` | Watch card label-derived color ring | Active-dot color + ring fill % | SHORT (used for label only) |
| `career_phase` (LONG) | Watch card chip ("Career phase: Champion") | First word capitalized as chip | LONG → first word |
| `pressure_short` (SHORT) | Watch card danger chip | Pressure chip text | SHORT |
| `career_stage` | (available, not currently displayed) | Could add to watch card subtitle | LONG |
| `overall_desc` | (available, not currently displayed) | Could be the "Read full story" tooltip | LONG |
| `legacy_state_short` | (available, not currently displayed) | Could be a 4th watch card "LEGEND IN THE MAKING" | SHORT |

### 1.4 What should be displayed (per GUI_PLAN §6.1)

6 sections above the fold at 1920×1080:
1. **Top Story** — Card/Accent (gold border, 12-col). LONG headline + 2-line body. Topic chip. "Read full story" hyperlink.
2. **Promotion Status** — Card/Flat (6-col). 5 rows: Cash (with sparkline), Reputation (voice band), Fan Trust (voice band), Roster count, Champions count.
3. **Next Event** — Card/Flat (6-col). Date + name + main event + title fight indicator. Buttons: "Build Card" (Primary) + "Matchmaking" (Secondary).
4. **Fighter Watch** — 3 WatchCards (4-col each). Top Prospect (gold), Hottest Streak (gold), Biggest Fall (crimson). 64px portrait + LONG voice phrase + context line.
5. **Champions** — horizontal strip of champion chips (max 8).
6. **Recent News** — vertical list of NewsCards (last 5).

### 1.5 What should be HIDDEN

Per Soul doc + CONVENTIONS §14:
- **Raw attribute numbers** (the 26 attributes in `fighter_attributes`) — never read by the Dashboard. Already enforced: `get_dashboard_data` docstring says "NEVER reads fighter_attributes / fighter_personality."
- **Cash breakdown** (the underlying `finance_transactions` rows) — only the sparkline + total are shown. Players don't see `fighter_purse -$30K`, only the rolling net.
- **`potential_desc`** — currently NULL for everyone; even if populated, would be HIDDEN on the Dashboard (potential is a Kingmaker/Talent-Hunter detail, not an Empire-Builder headline).
- **`potential` integer** from `fighter_career` — never shown to player (CONVENTIONS §14).
- **`ai_archetype`, `ai_spending_style`, `ai_aggression`** from `promotions` — these are AI-promo internals; only shown for the player's promo is forbidden (would reveal AI strategy).
- **`fighter_descriptors.snapshot_version`, `updated_at`** — cache internals.

### 1.6 What should be COLLAPSABLE

- The 5 Promotion Status tiles could collapse into a compact strip ("$50M · 85 REP · 60 ROSTER · 6 CHAMPS") when the viewport shrinks below 1200px. (Not in current spec but worth flagging.)
- Recent News: show 5 by default with a "Show all 50 of today" expansion. (Currently capped at 5 with no expansion.)
- Fighter Watch cards: the LONG voice phrase should be the always-visible "hook"; the LONGER `overall_desc` and `career_health_desc` should be available on hover/expand.

### 1.7 Voice phrases to use

| UI element | SHORT (≤3 words) | LONG (8-15 words) | Source |
|---|---|---|---|
| Top Story headline | n/a | `daily_headlines.headline_text` (already LONG) | `headline_engine` |
| Top Story body | n/a | `daily_headlines.body_text` | `headline_engine` |
| Watch card phrase | n/a | `fighter_descriptors.momentum` (decoded `phrase` part) | `context_engine` |
| Watch card "Career phase" chip | `career_phase_short` (e.g. "champion", "rising_contender") | n/a | `context_engine` |
| Watch card "Pressure" chip | `pressure_short` (e.g. "real pressure", "stay on track") | n/a | `context_engine` |
| Promotion Status Reputation tile | `_reputation_phrase()` returns "Highly Respected" / "Respected" / "Established" / "Emerging" / "Unknown" | n/a | `app_web.py:165` |
| Promotion Status Fan Trust tile | `_fan_trust_phrase()` returns "Strong" / "Moderate" / "Strained" / "Weak" | n/a | `app_web.py:173` |
| Recent Results tier phrase | `ratingTier()` (in JS) returns "a spectacular night of fights" etc. | matches `show_ratings.rating_description` column | `app_web.py:180` + `show_rating.py` |
| Champion chip | WC name + reign length ("1y 2m") + defenses count | n/a | `app_web.py:153` `_reign_length()` |

### 1.8 Data gaps for Dashboard

1. **Cash sparkline is flat for promo 1.** Only 1 `finance_transactions` row exists for promo 1 (the starting $80M sponsorship). The sparkline SVG in `dashboard.js` is currently **hardcoded** (see line 187: a static polyline `0,20 20,18 40,16 60,14 80,12 100,10 120,8`). The redesign needs to either (a) query the last 7 sim-days of `finance_transactions` per promo and render a real polyline, or (b) compute a derived 7-day rolling balance from `promotions.current_cash` snapshots.
2. **Next Event for promo 1 is empty.** 0 scheduled events for the player's promo. Matchmaking screen must land before the Dashboard's "Next Event" section is meaningful.
3. **Upset-of-week headline type unused.** `daily_headlines` ships 4 types (`top_story`, `fastest_rising`, `biggest_fall`, `upset_of_week`) but `get_dashboard_data` only reads `top_story`, `fastest_rising`, `biggest_fall`. Consider adding a 4th watch card "UPSET OF THE WEEK" (crimson accent) — data already exists.

---

## 2. Screen 2 — Roster ("The Stable")

### 2.1 Current implementation status

- **Python API:** `app_web.py:624 get_roster_data(promo_id, page=1, filters=None)` — **STUB**. Returns `{"placeholder": True, "message": "Roster screen will be implemented in the next phase."}`.
- **JS renderer:** none (no `roster.js` exists yet).
- **GUI_PLAN §6.2 spec:** SectionHeader + filter row + table card + weight class distribution viz.

### 2.2 What data is available (live DB, promo 1 sample)

| GUI_PLAN column | DB column(s) | Live data status | Sample (promo 1, top by wins) |
|---|---|---|---|
| Active dot (gold/crimson/neutral) | Derived from `fighters.is_active` (always 1 for roster) + `injuries.is_active` (active injury = crimson) + `suspensions.is_active` (suspended = crimson) + `fighter_descriptors.momentum_short` label (very_high=gold, collapsing=crimson, else neutral) | ✅ All derivable. Injuries/suspensions tables exist; need to join. | fighter 48 = neutral (stable momentum, no injury) |
| Name (hyperlink, gold) | `fighters.first_name` + `last_name` + `nickname` | ✅ Full coverage | "Alexander Pavlov 'Tao'" |
| Age (mono) | derived from `fighters.date_of_birth` and `simulation_clock.current_date` | ✅ Full coverage | fighter 48 = 37 (DOB 1989-05-02, sim date 2026-10-30) |
| WC (mono, uppercase) | `weight_classes.name` joined via `fighters.weight_class_id` | ✅ 10 WCs (8 male + 2 female) | "HEAVYWEIGHT" |
| Stage (SHORT career_phase, italic) | `fighter_descriptors.career_phase_short` | ✅ Full coverage, 8 variants per label | "champion\|\|king of the division" → "king of the division" |
| Form (SHORT momentum, italic) | `fighter_descriptors.momentum_short` | ✅ Full coverage, 8 variants per label | "stable\|\|no real swing" → "no real swing" |
| Record (mono "W-L-D") | `fighter_career.record_wins`, `record_losses`, `record_draws` | ✅ Full coverage | fighter 48 = 11-13-0 |
| Gym (text) | `gyms.name` joined via `fighters.current_gym_id` | ✅ 50 distinct gyms for promo 1's roster | "Apex Fight Team" |
| Nat (3-letter code) | `nations.name` joined via `fighters.birth_nation_id` — **NO 3-letter ISO code column exists**. Need a `nations.iso3` column OR a Python-side lookup. | ⚠️ Gap: only `name` exists. Will display full nation name until a mapping is added. | "Russia" (would need → "RUS") |

### 2.3 Interpretation-layer fields used

| Field | Display use | Voice variant |
|---|---|---|
| `career_phase_short` | "Stage" column (italic descriptor) | SHORT |
| `momentum_short` | "Form" column (italic descriptor) + Active-dot color | SHORT |
| `pressure_short` | (available — could be a hover tooltip) | SHORT |
| `legacy_state_short` | (available — could be a sort filter "Show only building/established/forgotten") | SHORT |
| `overall_desc` | (available — could be the row's tooltip on hover) | LONG |
| `career_health_desc` | (available — could drive an "INJURED" / "BEATEN UP" badge) | SHORT |

### 2.4 What should be displayed (per GUI_PLAN §6.2)

**Table columns (9):**
1. Active dot — colored indicator
2. Name — gold hyperlink → Fighter Profile
3. Age — mono
4. WC — mono, uppercase
5. Stage — SHORT `career_phase_short` phrase, italic
6. Form — SHORT `momentum_short` phrase, italic
7. Record — mono "W-L-D"
8. Gym — text
9. Nat — 3-letter code (or full name until iso3 column added)

**Filter row:** WC dropdown · Gender dropdown · Stage dropdown · Search entry (200px, 200ms debounce — already shipped in Phase 4) · Clear button.

**Pagination:** 20 rows/page. "Showing 1-20 of 60" + prev/numbered/next.

**Data viz:** Weight Class Distribution — horizontal bar chart, one bar per WC, sorted by `weight_classes.display_order`, fill = `gold` for player's promo.

### 2.5 What should be HIDDEN

Per CONVENTIONS §14 (raw attributes forbidden in player-facing UI) + Soul doc ("info asymmetry is the fun"):

- **All 26 `fighter_attributes` columns** (punch_power, cardio, fight_iq, chin, etc.) — these are the 0-100 raw numbers. The API must NEVER read `fighter_attributes` for the Roster. Voice phrases from `fighter_descriptors.attribute_descriptors` JSON are the only allowable representation (e.g. "serviceable striking" instead of `punch_power=58`).
- **All 20 `fighter_personality` columns** — same rule.
- **`fighter_career.potential`** integer (0-100) — never shown. (Already NULL at the descriptor-text level — see §0.)
- **`fighters.injury_proneness`, `weight_cut_difficulty`, `consistency`, `clutch_factor`, `marketability`, `fan_friendliness`, `promo_boost`** — all 0-100 internal ratings. These are engine internals; the player sees them only via interpretation phrases (e.g. `marketability=90` for fighter 48 should surface as a "draws a crowd" chip, not the number 90).
- **`fighters.preferred_gameplans`, `bad_matchup_tags`** — AI matchmaker internals.
- **`fighters.fight_style_archetype_id`, `personality_archetype_id`** — show the archetype NAME (e.g. "Striker", "Quiet Professional") not the integer.
- **`fighter_contracts.salary`, `buyout_clause`** — these belong on Fighter Profile, not the Roster table (contract info is per-fighter detail, not a sortable column).
- **`rankings.rating`** (ELO float) — show the rank position (1, 2, 3…) not the rating number.

### 2.6 What should be COLLAPSABLE

- **"Show all 26 attributes" toggle** per fighter row (when expanded, shows the full `attribute_descriptors` JSON as a StatBar grid in a row-expansion panel). Default: hidden. (Note: this matches GUI_PLAN §6.3 Fighter Profile Attributes tab — but the Roster could optionally allow inline expansion for power users.)
- **Show / hide inactive fighters** toggle (default: hide `is_active=0`).
- **Show / hide retired fighters** toggle (default: hide).

### 2.7 Voice phrases to use

| Column | SHORT (table cell) | LONG (row expansion / tooltip) |
|---|---|---|
| Stage | `career_phase_short` (e.g. "king of the division", "the buzz is real") | `career_phase` (LONG, e.g. "the king of the division") |
| Form | `momentum_short` (e.g. "no real swing", "can't miss right now") | `momentum` (LONG, e.g. "form has been consistent") |
| Pressure (hover) | `pressure_short` (e.g. "real pressure") | `pressure` (LONG, e.g. "the heat is on") |
| Legacy (hover) | `legacy_state_short` (e.g. "the book unfinished") | `legacy_state` (LONG, e.g. "the story is just beginning") |
| Career health (chip) | `career_health_desc` (e.g. "showing signs of age", "in peak condition") | n/a |
| Overall (tooltip) | n/a | `overall_desc` (e.g. "Alexander Pavlov 'Tao' is a striker, with serviceable timing and average kick accuracy, currently current titleholder.") |

### 2.8 Data gaps for Roster

1. **`nations.iso3` column missing.** GUI_PLAN calls for "3-letter code" but `nations` only has `name` + `language`. Either add the column with a migration OR maintain a Python-side `name → iso3` lookup.
2. **`narrative_family` is NULL for 99.4% of roster.** GUI_PLAN's Roster spec doesn't list a "Narrative" column (good — avoids the gap), but if any future column wants to use it, the interpretation engine must populate it for non-veteran fighters.
3. **No "is_on_card" flag.** GUI_PLAN §6.2 mentions a right-click context menu item "Add to Card" (P1). This requires knowing whether a fighter is already booked on an upcoming event. There's no `fighter.is_booked` column — would need a JOIN against `fights` WHERE `event_id IN (SELECT event_id FROM events WHERE status='scheduled')` AND (`winner_fighter_id` IS NULL — i.e. fight not yet resolved).

---

## 3. Screen 3 — Free Agents ("Open Market")

### 3.1 Current implementation status

- **Python API:** `app_web.py:642 get_free_agents(page=1, filters=None)` — **STUB**. Returns placeholder.
- **JS renderer:** none.
- **GUI_PLAN §6.4 spec:** SectionHeader + filter row + table card + sticky sign bar + ceiling distribution viz.

### 3.2 What data is available (live DB)

**4 082 active free agents** ( fighters where `current_promotion_id IS NULL AND is_active=1`). 635 have `potential ≥ 70` (high-potential pool).

| GUI_PLAN column | DB column(s) | Live data status | Sample (top by potential) |
|---|---|---|---|
| Name (hyperlink, gold) | `fighters.first_name` + `last_name` + `nickname` | ✅ Full | "Judy Kelly 'The Steel Gargoyle'" (fighter 1970, potential=92) |
| Age (mono) | derived from `date_of_birth` | ✅ Full | varies |
| WC (mono) | `weight_classes.name` | ✅ Full | "FLYWEIGHT" |
| Stage (SHORT) | `fighter_descriptors.career_phase_short` | ✅ Full | "rising_contender\|\|the buzz is real" |
| Ceiling (voice phrase or `????`) | **`scouting_reports.estimated_ceiling`** — **TABLE IS EMPTY (0 rows)** | ❌ **CRITICAL GAP** | "????" for every FA |
| Record (mono) | `fighter_career.record_wins` etc. | ✅ Full but most FAs are 0-0 (regen prospects) | 0-0-0 typical |
| Gym (text) | `gyms.name` | ✅ Full | varies |
| Nat (3-letter code) | `nations.name` | ⚠️ Same `iso3` gap as Roster | "USA" needed |
| Estimated cost (sticky sign bar) | **`scouting_reports.contract_cost_estimate`** — also empty. **Fallback: `agent_offers.asking_price`** — has only 2 expired rows for promo 1. | ❌ **CRITICAL GAP** | unknown |
| Scout confidence (sticky sign bar) | `scouting_reports.scout_confidence` | ❌ Empty | unknown |

### 3.3 Interpretation-layer fields used

| Field | Display use | Voice variant |
|---|---|---|
| `career_phase_short` | "Stage" column | SHORT |
| `career_stage` | (LONG alternative for hover) | LONG |
| `momentum_short` | (could be a column — "Form" like Roster) | SHORT |
| `potential_desc` | "Ceiling" column voice phrase — **NULL for everyone** | LONG (if populated) |
| `overall_desc` | (available — for FA profile drill-in) | LONG |
| `career_health_desc` | "Injury risk" chip ("showing signs of age" → red chip) | SHORT |

### 3.4 What should be displayed (per GUI_PLAN §6.4)

**Table columns (8):** Name · Age · WC · Stage (SHORT) · Ceiling (voice phrase or `????`) · Record · Gym · Nat. (No active dot — these aren't your fighters.)

**Sticky sign bar (bottom):** Selected fighter + estimated cost + Sign button (Primary).

**Data viz:** Talent Pool by Ceiling — horizontal bar chart, one bar per ceiling tier. Bar fill = `gold` for elite/high, `bg_card_elevated` for avg/below, `text_tertiary` for unknown.

### 3.5 What should be HIDDEN

Per Soul doc "Unknown fighters is a key early-game state — info asymmetry is the fun":

- **`fighter_career.potential`** integer — **NEVER shown**. This is the most important "hide" on this screen. The Soul doc's Fantasy 1 (Talent Hunter) explicitly depends on the player NOT knowing potential until scouted.
- **All 26 `fighter_attributes` columns** — same as Roster.
- **All 20 `fighter_personality` columns** — same.
- **`fighters.consistency`, `clutch_factor`, `marketability`, `fan_friendliness`, `promo_boost`, `injury_proneness`, `weight_cut_difficulty`** — hidden internals.
- **`scouting_reports.estimated_potential` and `estimated_floor`** integers — even when populated, only show as voice phrases (`estimated_ceiling` voice tier: "Elite"/"High"/"Above-Avg"/"Avg"/"Below-Avg"/"Low"/"Unknown").
- **`scouting_reports.report_text`** — only shown on Fighter Profile, NOT in the FA table.
- **`agent_offers.fighter_description`** — this is a rich voice-phrased blurb (e.g. "Veteran fighter, rising prospect, available on the cheap. The miles are on him but the can catch a sub hasn't gone anywhere."). Reserved for the sticky sign bar's "Why sign?" expandable, NOT in the table.

### 3.6 What should be COLLAPSABLE

- **Scouting report card** (when a fighter has been scouted) — collapsed by default behind a "View scout's notes ▾" toggle in the sticky sign bar.
- **Filter row** — collapsed by default behind a "Filters ▾" button (frees vertical space for the table).
- **"Show only scouted"** filter chip — quick toggle to hide the 4 082 `????` rows.

### 3.7 Voice phrases to use

| UI element | SHORT (table cell) | LONG (sign bar) |
|---|---|---|
| Ceiling column | voice phrase from `scouting_reports.estimated_ceiling` OR `????` for unscouted | `scouting_reports.report_text` (hedged: "reportedly shows…", "could develop into…") |
| Estimated cost | `"$56K"` (formatted `asking_price`) | `"Estimated signing cost: $56,470 — based on ceiling, age, momentum, market"` |
| Stage column | `career_phase_short` | `career_phase` (LONG) |
| Why sign? (expandable) | n/a | `agent_offers.fighter_description` (already voice-phrased by `agent_offers` engine) |
| Scout confidence | `"Low/Med/High confidence"` derived from `scout_confidence` int (0-100) | n/a |

### 3.8 Data gaps for Free Agents

1. **`scouting_reports` table is 100% empty.** No FA has ever been scouted. The GUI_PLAN's ceiling display has no source data — every FA shows `????`. This is actually **correct behavior for an unstarted game** (the Soul doc wants unknowns), but it means the Talent Hunter fantasy has no on-ramp until a Scout action exists. **Action:** the matchmaking/scouting pipeline must land before this screen ships, OR the GUI must explicitly show an empty-state `"No scouting reports on file. Send a scout to gather intel."`
2. **No `agent_offers` pipeline producing active offers.** Only 2 expired offers exist for promo 1. The "estimated cost" in the sticky sign bar cannot rely on `agent_offers.asking_price` until the AI promo-offer generator runs more often. **Action:** either (a) implement the `agent_offers` generator, or (b) derive estimated cost from a formula: `cost = f(potential, age, momentum_short, market_size)` — but this REQUIRES reading `fighter_career.potential` server-side (never sent to JS as a raw int — only the derived cost).
3. **No `ceiling_tier` voice-phrasing engine.** `scouting_reports.estimated_ceiling` is a free-text field. There's no enum mapping `potential >= 85 → "Elite"`, `75-84 → "High"`, etc. **Action:** either add a Python-side `_ceiling_phrase(potential)` helper (mirroring `_reputation_phrase()`) or document the existing voice phrasing in `scout_engine.py`.
4. **`potential_desc` is NULL for everyone** (see §0) — the interpretation engine's potential-to-phrase mapper is unimplemented. This is the bigger interpretation-layer gap blocking ceiling voice display.

---

## 4. Screen 4 — Fighter Profile

### 4.1 Current implementation status

- **Python API:** `app_web.py:634 get_fighter_profile(fighter_id)` — **STUB**. Returns placeholder.
- **JS renderer:** none.
- **GUI_PLAN §6.3 spec:** Header card (Accent, 12-col) + TabBar (6 tabs) + tab content.

### 4.2 What data is available (live DB, fighter 48 sample)

#### Fighter 48 — Alexander Pavlov 'Tao' (Heavyweight champion, promo 1)

| Section | DB source | Live data |
|---|---|---|
| **Header card** | | |
| 256×320 portrait | `ui/assets/portraits/` (none shipped — placeholder PNG) | ⚠️ No portrait files exist; placeholder renders first letter |
| Name + nickname | `fighters.first_name` + `last_name` + `nickname` | ✅ "Alexander Pavlov 'Tao'" |
| Age + WC + promo + gym | derived + `weight_classes.name` + `promotions.name` + `gyms.name` | ✅ "37 · Heavyweight · Alpha Combat Federation · Apex Fight Team" |
| Identity strip (LONG variants): Career Phase / Momentum / Pressure / Narrative / Legacy / Trajectory | `fighter_descriptors.{field}` | ⚠️ **5 of 6 populated**; `narrative_family` is NULL — the "Narrative" segment is empty. `public_narrative` also NULL (could be the "Trajectory" segment). |
| Action buttons | context-dependent: Cut Fighter (if on roster) / Offer Extension (if contract expiring) / Book Next Fight / Scout (if not on roster) | ✅ Contract data exists for fighter 48 (active contract, end_date 2027-07-20, salary $50K) |
| **Tab 1 — Overview** | | |
| Bio (8-col) | `fighter_bios.bio_text` | ✅ Full coverage (4 464 rows). Tone tags: `unproven_prospect`, `mid_carder`, `grizzled_veteran`, `journeyman`, etc. Sample: *"There's a version of MMA history you can't write without Alexander Pavlov. Over 31 fights, the striker from Harbor Performance has been the test opponents either pass or fail. At 37, the 13-18 veteran…"* |
| Career stats (4-col) | `fighter_career` (record_wins, losses, draws, win_streak, loss_streak, career_health, title_reigns) + `rankings` (rating, fights_count, last_fight_date) | ✅ Full. fighter 48: 11-13-0, win_streak=1, career_health=82, title_reigns=2, rating=982.0 |
| Recent Fights timeline (12-col) | `fight_history` joined to opponent fighters | ✅ 24 fights for fighter 48. Sample (latest): 2026-02-04 vs Ronald Bailey — W (unanimous_decision, R3 5:00). **Outcomes are lowercase** (`win`/`loss`/`draw`/`nc`) — JS badge logic `outcome[0].toUpperCase()` correctly produces "W"/"L"/"D"/"N". |
| **Tab 2 — Attributes** | | |
| 26 StatBars (2 cols of 13) | `fighter_descriptors.attribute_descriptors` JSON | ✅ Full coverage. Each attribute has a voice phrase: `punch_power: "serviceable striking"`, `cardio: "serviceable stamina"`, `fight_iq: "average fight IQ"`, `chin: "can be rocked by big shots"`, etc. Top 6 shown by default, "Show all 26" toggle. |
| **Tab 3 — Personality** | | |
| 20 StatBars (2 cols of 10) | `fighter_descriptors.personality_descriptors` JSON | ✅ Full coverage. Sample: `aggression: "measured aggression"`, `composure: "above-average poise"`, `killer_instinct: "above-average killer instinct"`, `loyalty: "goes where the money is"`, etc. |
| **Tab 4 — Career** | | |
| Full fight history table | `fight_history` (all 24 rows) | ✅ See Tab 1 |
| Title reigns timeline | `titles WHERE current_champion_fighter_id=48 OR (title_reigns_count > 0 AND ... )` | ✅ fighter 48: HW champ since 2026-03-13, 2 reigns, 0 defenses. Reign-length helper: `_reign_length(since, sim_date)` returns "7m" (2026-03-13 → 2026-10-30). |
| Career arc visualization (P1) | `fighter_descriptors.career_stage` + `career_health_desc` + `legacy_state` | ✅ Data exists: career_stage="reigning champion", career_health_desc="showing signs of age", legacy_state="building" |
| **Tab 5 — Fights** | | |
| Same as Overview's Recent Fights but full history | `fight_history` | ✅ 24 rows |
| **Tab 6 — News** (P1) | `news_items WHERE fighter_id=48 ORDER BY published_at DESC` | ✅ 4 500+ news items exist, filterable by fighter_id |
| **Scouting report card** (for non-roster fighters) | `scouting_reports WHERE target_fighter_id=?` | ❌ **Empty** — no fighter has a scouting report today |
| **Memory links card** (P1 future) | `rivalries` + `fighter_memory_links` + common-opponents derived from `fight_history` | ⚠️ fighter 48 has 1 active rivalry (Ronald Bailey, 8 fights, 5-3, heat=42) but **0 memory_links rows**. `fighter_memory_links` table has only 215 rows total (5% coverage). |

### 4.3 Interpretation-layer fields used

| Field | Section | Voice variant |
|---|---|---|
| `overall_desc` | Header card subtitle (or "About" tooltip) | LONG |
| `career_stage` | Header card "Career Stage" badge | LONG |
| `career_health_desc` | Header card "Health" chip | SHORT |
| `momentum` (LONG) | Identity strip — Momentum segment | LONG |
| `momentum_short` | Identity strip — Momentum compact | SHORT |
| `pressure` (LONG) | Identity strip — Pressure segment | LONG |
| `pressure_short` | Identity strip — Pressure compact | SHORT |
| `career_phase` (LONG) | Identity strip — Career Phase segment | LONG |
| `career_phase_short` | Identity strip — Career Phase compact | SHORT |
| `narrative_family` (LONG) | Identity strip — Narrative segment | LONG (**NULL for 99.4% of fighters**) |
| `legacy_state` (LONG) | Identity strip — Legacy segment | LONG |
| `legacy_state_short` | Identity strip — Legacy compact | SHORT |
| `potential_desc` | (would be Identity strip — Trajectory segment) | LONG (**NULL for 100% of fighters**) |
| `attribute_descriptors` JSON (26 entries) | Tab 2 — each StatBar's label | SHORT |
| `personality_descriptors` JSON (20 entries) | Tab 3 — each StatBar's label | SHORT |
| `public_narrative` | (would be Tab 1 — Bio expansion / quote pull) | LONG (**NULL for 100% of fighters**) |

### 4.4 What should be displayed (per GUI_PLAN §6.3)

**Header card (12-col Accent):**
- 256×320 Hero portrait (gold border if champion, gold-leaf texture overlay)
- Name + nickname + age + WC + promo + gym
- Identity strip: Career Phase / Momentum / Pressure / Narrative / Legacy / Trajectory — all LONG variants
- Action buttons: Cut Fighter (if on roster) · Offer Extension (if expiring) · Book Next Fight · Scout (if not on roster)

**6 tabs:**
1. Overview (default): Bio (8-col) + Career stats (4-col) + Recent Fights timeline (12-col)
2. Attributes: 26 StatBars (2 cols of 13). **Top 6 shown by default, "Show all 26" toggle.**
3. Personality: 20 StatBars (2 cols of 10)
4. Career: Full fight history + title reigns timeline + career arc viz (P1)
5. Fights: full fight history
6. News (P1)

**Scouting report card** (for non-roster fighters): below header card. Scout's name + report date + voice-phrased notes (hedged register). If no report: EmptyState *"No scouting report on file. Send a scout to gather intel."*

**Memory links card** (P1): below Recent Fights. Past rivalries (crimson "BAD BLOOD" chip + hyperlink to rival) + common opponents (3-5 fighters with W/L record vs each) + gym history.

### 4.5 What should be HIDDEN

Per CONVENTIONS §14 + Soul doc:

- **All 26 `fighter_attributes` integer columns** — the JSON in `fighter_descriptors.attribute_descriptors` is the ONLY allowable representation. Never read `fighter_attributes` directly in the API.
- **All 20 `fighter_personality` integer columns** — same rule, use the JSON.
- **`fighter_career.potential`** integer — NEVER shown. The voice-phrased `potential_desc` (currently NULL) is the only display-allowable form. (For a champion like fighter 48, even `potential_desc` should be hidden — "potential" is a prospect concept, not a champion concept. The Talent Hunter fantasy's info-asymmetry rule applies even here.)
- **`rankings.rating`** (ELO float) — show rank position (1st, 2nd) not the rating number.
- **`fighters.injury_proneness`, `weight_cut_difficulty`, `consistency`, `clutch_factor`, `marketability`, `fan_friendliness`, `promo_boost`** — engine internals.
- **`fighters.preferred_gameplans`, `bad_matchup_tags`** — AI matchmaker internals (could be revealed via a "Scout's tactical notes" card for scouted non-roster fighters only).
- **`fighters.fight_style_archetype_id`, `personality_archetype_id`** integers — show archetype NAME ("Striker", "Quiet Professional") from `style_archetypes`/`personality_archetypes` joined tables.
- **`fighter_contracts.buyout_clause`** — could be shown on the contract card but only if `contracts.status='active'` AND the player's promo ≠ the fighter's promo (revealing buyout for own fighters is pointless; revealing it for rival-promo fighters requires scouting).
- **`training_camps.attribute_changes`** JSON — engine internals of camp outcomes; show only the summary `camp_result_summary` text.
- **`fights.winner_fighter_id`, `loser_fighter_id`** raw ints — display as W/L badge derived from `fight_history.outcome` instead.

### 4.6 What should be COLLAPSABLE

- **Attributes tab: top 6 by default, "Show all 26" toggle.** GUI_PLAN §6.3 explicitly specifies this. Implementation: sort the 26 attributes by an "importance" rank (e.g. derived from `style_archetypes.attribute_bias` — for a Striker, the top 6 are `punch_power`, `kick_power`, `punch_accuracy`, `head_movement`, `kick_accuracy`, `footwork`). Default-show those 6; the remaining 20 collapse behind a toggle.
- **Personality tab: top 6 by default, "Show all 20" toggle.** Same pattern. Default top 6: `aggression`, `composure`, `killer_instinct`, `discipline`, `patience`, `ego` (the ones that drive in-cage behavior).
- **Recent Fights timeline: 5 by default, "Show full history (24 fights)" toggle.**
- **Career stats: show 4 primary (Record, Win Streak, Career Health, Title Reigns) by default, "Show all 9" toggle.**
- **News tab: 5 by default, "Show all 47 mentions" toggle.**
- **Memory links card: 3 common opponents by default, "Show all 12 common opponents" toggle.**

### 4.7 Voice phrases to use

| Section | SHORT (chips, badges, StatBars) | LONG (prose, identity strip) |
|---|---|---|
| Identity strip — Career Phase | `career_phase_short` | `career_phase` |
| Identity strip — Momentum | `momentum_short` | `momentum` |
| Identity strip — Pressure | `pressure_short` | `pressure` |
| Identity strip — Narrative | `narrative_family_short` (NULL for most → fallback to "—") | `narrative_family` (NULL for most → fallback to `overall_desc`) |
| Identity strip — Legacy | `legacy_state_short` | `legacy_state` |
| Identity strip — Trajectory | (no SHORT variant — would need adding) | `potential_desc` (currently NULL) OR `public_narrative` (also NULL) |
| Attribute StatBar | `attribute_descriptors[key]` (e.g. "serviceable striking") | n/a |
| Personality StatBar | `personality_descriptors[key]` (e.g. "measured aggression") | n/a |
| Health chip | `career_health_desc` (e.g. "showing signs of age", "in peak condition") | n/a |
| Style chip | `style_archetypes.name` (e.g. "Striker") | `style_archetypes.description` ("Stand-up specialist") |
| Bio (Overview tab) | n/a | `fighter_bios.bio_text` (LONG prose) |
| Recent Fights result badge | `outcome[0].toUpperCase()` → "W"/"L"/"D"/"N" | `result_type` (e.g. "unanimous_decision" → "UD"; "ko_tko" → "KO/TKO"; "submission" → "SUB") |
| Scouting report notes | `scouting_reports.estimated_ceiling` voice phrase | `scouting_reports.report_text` (hedged: "reportedly shows…", "could develop into…") |

### 4.8 Action buttons / levers (per GUI_PLAN §6.3 header card)

| Button | Condition | API/service to call | Data needed |
|---|---|---|---|
| Cut Fighter | `fighters.current_promotion_id = player_promotion_id` AND `is_active=1` | `services.contracts.cut_fighter(conn, fighter_id)` (TBD — likely exists) | Active `contracts` row to terminate |
| Offer Extension | `contracts.end_date` within 90 days of `simulation_clock.current_date` | `services.contracts.offer_extension(conn, fighter_id, new_end_date, new_salary)` (TBD) | `contracts.end_date`, `contracts.salary` |
| Book Next Fight | fighter is on player's promo AND not currently in `training_camps` for an upcoming event | `services.matchmaking.book_fight(conn, fighter_id, opponent_id, event_id)` (TBD) | List of `events WHERE status='scheduled' AND promotion_id=player_promo_id` |
| Scout | `fighters.current_promotion_id != player_promotion_id` (or IS NULL for free agents) | `services.scouting.send_scout(conn, fighter_id, scout_id)` (TBD) | List of `staff WHERE role_type LIKE '%scout%'` |
| Sign (free agents only) | `fighters.current_promotion_id IS NULL` | `services.contracts.sign_free_agent(conn, fighter_id, promotion_id, start_date)` | `agent_offers.asking_price` (or derived estimate) |

### 4.9 Data gaps for Fighter Profile

1. **`potential_desc` and `public_narrative` are NULL for 100% of fighters.** The interpretation engine has these columns but never populates them. Either (a) implement the populator in `src/interpretation/`, or (b) drop these segments from the identity strip in the redesign (show only 4 segments instead of 6: Career Phase / Momentum / Pressure / Legacy).
2. **`narrative_family` is NULL for 99.4% of fighters.** The "Narrative" identity-strip segment will be empty for nearly every profile. Either populate the engine or omit the segment.
3. **`fighter_memory_links` table covers only 5% of roster (215/4464).** The Memory Links card will be sparse. Either (a) populate the table from `rivalries` + `fight_history` common opponents as a backfill, or (b) derive common-opponents live in the API from `fight_history` (slower but accurate).
4. **`scouting_reports` table is empty.** The Scouting Report card will always show the EmptyState. (Same as Free Agents §3.8.)
5. **No portrait assets.** `ui/assets/portraits/` directory does not exist. Placeholder will render the first letter of the fighter's last name in gold. Acceptable for MVP but flagged.
6. **`legacy_state_short = "legendary"` has only 1 phrase.** Hall-of-Fame fighters will all show the same legacy phrase. VOICE_ENFORCEMENT §3 bar (≥8 variants) is failed.
7. **No "is_booked" flag.** Book Next Fight button needs to know if fighter is already on an upcoming card. Derivable via JOIN against `fights` WHERE `event_id IN (SELECT event_id FROM events WHERE status='scheduled')` AND (`winner_fighter_id IS NULL`).

---

## 5. Cross-Screen Findings

### 5.1 Voice variant gaps (per VOICE_ENFORCEMENT §3 ≥8-variant bar)

| Label column | Labels failing ≥8 bar | Affected fighters | Priority |
|---|---|---|---|
| `legacy_state` (LONG) | `legendary`=1 | 1 (Hall of Fame tier — currently 0 inducted) | P1 — fix before HoF becomes a real screen |
| `legacy_state_short` (SHORT) | `legendary`=1 | 1 | P1 |
| `narrative_family` (LONG) | `cinderella_story`=2, `fallen_champion`=1 | 3 | P2 — only 27 fighters have any narrative_family at all (99.4% NULL is the bigger issue) |
| `narrative_family_short` (SHORT) | `cinderella_story`=2, `fallen_champion`=1 | 3 | P2 |
| `momentum` (LONG) | `collapsing`=6 | 17 | P1 — `collapsing` is the decline state, frequently shown |
| `career_phase` (LONG) | `declining`=7 | 20 | P2 |

### 5.2 Cache freshness (per VOICE_ENFORCEMENT §5.3)

```sql
SELECT * FROM interpretation_cache_meta;
-- {"engine_version": "1.8.0", "last_built_date": "2026-10-30",
--  "last_built_fighter_count": 4450, "updated_at": "2026-08-02 15:07:25"}
```

Engine version is **1.8.0** — newer than the VOICE_ENFORCEMENT reference (1.6.0). Cache is fresh. The 14 fighters with NULL `momentum_short`/`pressure_short`/`career_phase_short` (visible in label-coverage query) are likely the 14 retired fighters (`is_retired=1`) who don't get re-cached.

### 5.3 Empty interpretation-related tables

| Table | Rows | Impact |
|---|---|---|
| `scouting_reports` | 0 | Blocks Free Agents ceiling display + Fighter Profile scouting card |
| `division_descriptors` | 0 | Unused — could power a "division narrative" widget (e.g. "The Lightweight division is on fire") |
| `gym_descriptors` | 0 | Unused — could power a "Gym Profile" screen (P2+) |
| `promotion_descriptors` | 0 | Unused — could power AI-promo narrative ("Rival Fight League is making a push") |
| `fighter_memory_links` | 215 | Sparse — Memory Links card on Fighter Profile will be empty for most fighters |

### 5.4 Player-promo-specific gaps (promo 1 = Alpha Combat Federation)

| Gap | Impact | Workaround |
|---|---|---|
| 0 scheduled events for promo 1 | Dashboard "Next Event" section always shows EmptyState | Player must use Matchmaking screen (not yet built) to schedule first event |
| 1 row in `finance_transactions` for promo 1 | Cash sparkline is flat / hardcoded SVG | Use rolling 7-day balance derivation OR multi-promo aggregate |
| 0 active `agent_offers` for promo 1 | Free Agents sign bar shows no pre-made offers | Derive estimated cost from formula (requires server-side read of `potential`) |

### 5.5 Schema notes for the API designer

- **`fight_history.outcome` is lowercase** (`win`/`loss`/`draw`/`nc`). The dashboard.js `outcome[0].toUpperCase()` produces correct "W"/"L"/"D"/"N" badges. Any SQL aggregation must use lowercase: `SUM(outcome='win')`, not `SUM(outcome='W')`.
- **`fights` table uses `winner_fighter_id`/`loser_fighter_id`**, NOT `fighter_a_id`/`fighter_b_id`. Use `fight_history` (which has `fighter_id` + `opponent_id`) for the fighter-profile fight list, NOT `fights`.
- **`staff.role_type`** is the column name (not `role`). Filter `WHERE role_type LIKE '%scout%'` to find scouting staff.
- **`fighter_contracts.contract_type`** is on the `fighter_contracts` table, not `contracts`. JOIN through `fighter_contracts.contract_id → contracts.contract_id` for full contract info.
- **`nations` has no `iso3` column.** Roster/Free Agents "Nat" column needs either a migration OR a Python lookup table.
- **`weight_classes` has 10 rows** (8 male + 2 female). Display order is 1-10. Heavyweight through Flyweight (male) then Featherweight + Bantamweight (female).

---

## 6. Recommendations for the Redesign

### 6.1 P0 — must fix before any screen ships

1. **Populate `potential_desc` and `narrative_family`** in the interpretation engine. These are NULL for 99-100% of fighters and would leave identity strips and ceiling columns empty.
2. **Implement a scouting pipeline** that writes rows to `scouting_reports`. Without it, the Free Agents ceiling column and the Fighter Profile scouting card are both permanently in EmptyState.
3. **Derive an estimated-cost formula** as a fallback when `agent_offers` has no active offer: `cost = base_fee + potential_factor + age_factor + momentum_factor + market_factor`. Compute server-side (where `potential` is readable) and return only the formatted cost to JS.
4. **Add `nations.iso3` column** (migration) OR a Python `name → iso3` lookup. Roster and Free Agents both need 3-letter nationality codes.

### 6.2 P1 — should fix during Phase 1 of the redesign

5. **Backfill `fighter_memory_links`** from `rivalries` + `fight_history` common opponents. Or derive common opponents live in `get_fighter_profile`.
6. **Expand `legacy_state` "legendary" phrase bank** from 1 → 8 variants (VOICE_ENFORCEMENT §3 bar).
7. **Expand `momentum` "collapsing" LONG phrase bank** from 6 → 8 variants.
8. **Implement a real cash sparkline** for the Dashboard. Either query `finance_transactions` for the last 7 sim-days (currently flat for promo 1) or compute a 7-day rolling balance from `promotions.current_cash` snapshots.
9. **Implement a real 4th Watch Card** for "UPSET OF THE WEEK" — data already exists in `daily_headlines WHERE headline_type='upset_of_week'` (26 rows unused).

### 6.3 P2 — nice-to-have

10. **Populate `division_descriptors`, `gym_descriptors`, `promotion_descriptors`** tables for future division/gym/promo narrative screens.
11. **Add an `is_booked` flag** (or a derived view) for Roster and Fighter Profile's "Book Next Fight" button enablement.
12. **Move phrase banks to an `interpretation_phrases` DB table** (VOICE_ENFORCEMENT §6 P2) so content editors can update phrases without redeploys.

---

## 7. Per-Screen Field Inventory (summary tables)

### 7.1 Dashboard — total fields available

| Section | Fields shown to player | Fields read from DB | Fields hidden |
|---|---|---|---|
| Top Story | headline, body, fighter hyperlink, topic chip | `daily_headlines.headline_text/body_text/fighter_id` (top_story type) | `headline_id`, `snapshot_version`, `created_at` |
| Promotion Status | cash, reputation_phrase, fan_trust_phrase, roster_count, champ_count, size_tier, broadcast_tier | `promotions.current_cash/reputation/fan_trust/size_tier/broadcast_tier`, `fighters` count, `titles` count | `promotions.starting_budget/ownership_type/ai_*` |
| Cash sparkline | 7-point polyline | `finance_transactions.amount` by date | (none — gap: only 1 row for promo 1) |
| Next Event | event_date, promo_name, event_name | `events.event_date/event_name`, `promotions.name` | `events.venue_id/market_id/event_type` |
| Fighter Watch (3 cards) | name, momentum_phrase, career_phase chip, pressure chip, last5 form blocks, fighter hyperlink | `fighters.first/last_name`, `fighter_descriptors.momentum/momentum_short/career_phase_short/pressure_short`, `fight_history.outcome` last 5 | all `fighter_attributes`, all `fighter_personality`, `fighter_career.potential` |
| Champions strip | WC name, fighter name, reign length, defenses, reigns count | `titles`, `fighters`, `weight_classes` | `titles.title_id`, `is_vacant` (implied) |
| Recent News (5) | headline, body, topic badge, published_at, fighter hyperlink | `news_items` | `news_items.news_source_id/event_id/fight_id/promotion_id` |
| Recent Results (4) | promo_name, event_name, event_date, rating_phrase | `events`, `promotions`, `show_ratings` | `show_ratings.fan_rating/commercial_rating/excitement_rating/quality_rating` (raw ints) |

### 7.2 Roster — total fields available

| Column | Shown | Read from DB | Hidden |
|---|---|---|---|
| Active dot | color | derived from `momentum_short` label + `injuries.is_active` + `suspensions.is_active` | (none) |
| Name | gold hyperlink | `fighters.first_name/last_name/nickname` | `fighters.fighter_id` (used for hyperlink only) |
| Age | mono int | derived from `date_of_birth` + `simulation_clock.current_date` | `date_of_birth` (raw) |
| WC | mono uppercase | `weight_classes.name` via `weight_class_id` | `weight_class_id`, `min_weight_kg/max_weight_kg` |
| Stage | italic SHORT phrase | `fighter_descriptors.career_phase_short` | `career_phase` (LONG, available on hover) |
| Form | italic SHORT phrase | `fighter_descriptors.momentum_short` | `momentum` (LONG, available on hover) |
| Record | mono "W-L-D" | `fighter_career.record_wins/losses/draws` | `fighter_career.potential/career_health/win_streak/loss_streak/title_reigns` |
| Gym | text | `gyms.name` via `current_gym_id` | `gyms.reputation/membership_cost/facility_quality/medical_support/sparring_depth/development_focus/culture_tone/weight_cut_support` |
| Nat | 3-letter code | `nations.name` via `birth_nation_id` (iso3 missing) | `nations.language`, `birth_city_id`, `residence_city_id`, `residence_nation_id` |

**Total table columns: 9.** Collapsable: row-expansion shows top 6 attribute phrases.

### 7.3 Free Agents — total fields available

| Column | Shown | Read from DB | Hidden |
|---|---|---|---|
| Name | gold hyperlink | `fighters.first_name/last_name/nickname` | `fighter_id` (hyperlink only) |
| Age | mono int | derived | `date_of_birth` (raw) |
| WC | mono uppercase | `weight_classes.name` | `weight_class_id` |
| Stage | italic SHORT phrase | `fighter_descriptors.career_phase_short` | `career_phase` LONG |
| Ceiling | voice phrase OR `????` | `scouting_reports.estimated_ceiling` (currently empty → `????`) | `fighter_career.potential` integer (NEVER shown) |
| Record | mono "W-L-D" | `fighter_career.record_*` | `potential`, `career_health` |
| Gym | text | `gyms.name` | gym internals |
| Nat | 3-letter code | `nations.name` | nation internals |
| Sign bar — estimated cost | `"$56K"` | `agent_offers.asking_price` (or derived) | `scouting_reports.contract_cost_estimate` (empty), derivation formula's `potential` input |
| Sign bar — scout confidence | `"Low/Med/High"` | `scouting_reports.scout_confidence` (0-100 → bucketed) | raw int |
| Sign bar — why sign? (expandable) | voice-phrased blurb | `agent_offers.fighter_description` (when available) OR derived from `overall_desc` + `career_phase_short` | n/a |

**Total table columns: 8.** Collapsable: scouting report card (when populated) + filter row + "Show only scouted" toggle.

### 7.4 Fighter Profile — total fields available

| Section | Shown | Read from DB | Hidden |
|---|---|---|---|
| Header card — portrait | 256×320 image | (none — no portrait assets) | n/a |
| Header card — name + nickname | text | `fighters.first_name/last_name/nickname` | n/a |
| Header card — age + WC + promo + gym | text | derived + `weight_classes.name` + `promotions.name` + `gyms.name` | IDs |
| Identity strip — Career Phase | LONG phrase | `fighter_descriptors.career_phase` | `career_phase_short` (SHORT available) |
| Identity strip — Momentum | LONG phrase | `fighter_descriptors.momentum` | `momentum_short` |
| Identity strip — Pressure | LONG phrase | `fighter_descriptors.pressure` | `pressure_short` |
| Identity strip — Narrative | LONG phrase (NULL for 99.4%) | `fighter_descriptors.narrative_family` | `narrative_family_short` |
| Identity strip — Legacy | LONG phrase | `fighter_descriptors.legacy_state` | `legacy_state_short` |
| Identity strip — Trajectory | LONG phrase (NULL for 100%) | `fighter_descriptors.potential_desc` OR `public_narrative` | n/a |
| Action buttons | Cut / Extend / Book / Scout / Sign | derived from `current_promotion_id` + `contracts.end_date` + `training_camps.is_active` + `scouting_reports` existence | n/a |
| Tab 1 — Bio | LONG prose | `fighter_bios.bio_text` + `bio_tone` | n/a |
| Tab 1 — Career stats | record, streak, career_health, title_reigns, ranking | `fighter_career` + `rankings` | `rankings.rating` (raw ELO float), `fighter_career.potential` |
| Tab 1 — Recent Fights timeline (5) | W/L badge, opponent hyperlink, method caption, round/time, title fight chip | `fight_history` + opponent `fighters` | `fight_history.fight_id/event_id/weight_class_id/score_margin` |
| Tab 2 — Attributes (26 StatBars) | voice phrase per attribute | `fighter_descriptors.attribute_descriptors` JSON | `fighter_attributes.*` raw ints (NEVER read) |
| Tab 3 — Personality (20 StatBars) | voice phrase per trait | `fighter_descriptors.personality_descriptors` JSON | `fighter_personality.*` raw ints (NEVER read) |
| Tab 4 — Full fight history | same as Recent Fights | `fight_history` (all rows) | n/a |
| Tab 4 — Title reigns timeline | reign start/end, defenses | `titles` history (only current reign stored — no historical reigns table) | n/a |
| Tab 4 — Career arc viz (P1) | career_stage + career_health + legacy_state plotted | `fighter_descriptors` | n/a |
| Tab 5 — Fights | same as Tab 4 history | n/a | n/a |
| Tab 6 — News (P1) | NewsCards | `news_items WHERE fighter_id=?` | n/a |
| Scouting report card | scout name, date, voice-phrased notes | `scouting_reports` (currently empty) | `scout_confidence` raw int, `estimated_potential/floor` raw text |
| Memory links card (P1) | rival name + "BAD BLOOD" chip, common opponents, gym history | `rivalries` + `fighter_memory_links` + derived common opponents | `rivalry_heat` raw int (show as heat-tier phrase) |

**Total tabs: 6.** Collapsable: Attributes (top 6 of 26), Personality (top 6 of 20), Recent Fights (5 of N), Career stats (4 of 9), News (5 of N), Memory links (3 of N common opponents).

---

## 8. Verification queries re-run summary (per VOICE_ENFORCEMENT §5)

All queries in this audit were run against `data/cage_empire.db` on 2026-08-02. The DB is the live production save with `engine_version=1.8.0`, sim date `2026-10-30`, 4 464 fighters, 4 082 active free agents, 1 974 completed events, 7 scheduled events, 4 500+ news items, 26 days of daily headlines, 215 memory links, 0 scouting reports, 0 division/gym/promotion descriptors.

**§5.1 variant coverage:** PASS for SHORT columns except `legacy_state_short.legendary`=1. FAIL for LONG columns: `momentum.collapsing`=6, `career_phase.declining`=7, `legacy_state.legendary`=1, `narrative_family.cinderella_story`=2, `narrative_family.fallen_champion`=1.

**§5.2 headline repetition:** improved since VOICE_ENFORCEMENT was written (12-19 distinct phrases per type over 26 days) but ≥8-variant threshold still missed for rare labels.

**§5.3 cache freshness:** ✅ `engine_version=1.8.0` matches/ships newer than VOICE_ENFORCEMENT's 1.6.0 reference.

**§5.4 tabloid cliché sweep:** ✅ 0 rows. P0 RESOLVED.

---

*End of audit. Authored 2026-08-02 by SCREEN-DATA-AUDIT subagent. Mode: RESEARCH ONLY — no code or DB changes were made.*
