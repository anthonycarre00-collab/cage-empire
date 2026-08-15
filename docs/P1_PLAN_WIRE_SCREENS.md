> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# P1 Plan: Wire 4 Screens with Existing Backends

> **Status:** ACTIVE — implementation plan for P1.
> **Source:** `docs/COMPREHENSIVE_REVIEW.md` P1 + `docs/REVIEW_P1_SCREEN_BACKENDS.md`
> **Pattern to follow:** `staff_market.js` (most recent screen exemplar)

---

## 0. Scope

4 screens with full backends but no UI. Each needs: 1 API method + 1 bridge wrapper + 1 JS renderer + 1 CSS file + nav wiring.

| Screen | Nav ID | Backend | Data | Effort |
|---|---|---|---|---|
| Scouting | `scouting` | `src/scouting.py` (752 lines) | 0 reports (needs seed or player action) | Medium |
| Bad Blood | `rivalries` | `src/rivalries.py` (1053 lines) | 390 rivalries (286 active) | Low |
| Legends | `hall_of_fame` | `src/services/hof_svc.py` (602 lines) | 2 inductees | Low |
| Training Camps | `gyms` | `src/services/training_svc.py` + `src/tick_processor.py` | 300 gyms, 138 active camps | Medium |

---

## 1. Bad Blood (Rivalries) — LOW effort, HIGH reward

**API:** `get_rivalries_data(page, filters)` — paginated rivalries, filterable by type + heat level.

**UI:**
- Section header: "BAD BLOOD" (red accent) + subtitle "X active rivalries"
- Filter bar: type dropdown (All / Bad Blood / Title Rivalry / Rematch Hungry / Callout) + heat toggle (All / Simmering / Boiling / Cold)
- Rivalry cards: both fighters (names clickable → Fighter Profile), heat meter (visual bar 0-100, color-coded), H2H record, rivalry type chip, last escalation date
- Click rivalry → expand to show fight history between the two
- Voice phrases for heat: "simmering" (20-39), "heating up" (40-59), "boiling over" (60-79), "ready to explode" (80-100)

## 2. Legends (Hall of Fame) — LOW effort

**API:** `get_hof_data(page)` — paginated HoF inductees.

**UI:**
- Section header: "LEGENDS" (gold accent) + subtitle "X inductees"
- Grid of legend cards: portrait, name, nickname, career summary (voice phrase), career stats (record, title reigns, KO rate), induction date, weight class
- Click legend → expand to show full career highlights + key fights
- Empty state: "No legends have been inducted yet. Greatness takes time."

## 3. Scouting — MEDIUM effort

**API:** 
- `get_scouting_data()` — returns: player's scouts (staff WHERE role_type='scout' AND promotion_id=player), recent scouting_reports, eligible fighters to scout (free agents + rival promo fighters)
- `assign_scout(scout_id, fighter_id)` — assigns scout to evaluate a fighter
- `get_scouting_report(report_id)` — full report details

**UI:**
- Section header: "SCOUTING" (gold accent) + subtitle "X scouts on staff"
- Two tabs: "My Scouts" + "Reports"
- My Scouts tab: list of scouts with skill phrase, current assignment, assignment button
- Reports tab: list of recent scouting reports with fighter name, estimated ceiling (voice phrase), confidence (voice phrase), date
- Click report → expand to show full report (fighter assessment, style notes, potential estimate with uncertainty)
- Assign flow: click "Assign" on a scout → modal with fighter picker (search + filter by WC) → confirm → scout assigned (report generates after 7 sim days)

## 4. Training Camps (Gyms) — MEDIUM effort

**API:**
- `get_gyms_data(page, filters)` — returns: gyms (filterable by region/quality), active training camps for player's fighters, completed camps history
- `get_gym_detail(gym_id)` — gym info + fighters training there + camp history

**UI:**
- Section header: "TRAINING CAMPS" (gold accent) + subtitle "X active camps"
- Two tabs: "Active Camps" + "Gym Directory"
- Active Camps tab: list of player's fighters currently in camp, with fighter name, gym name, camp focus, start/end dates, fatigue/morale/injury risk, attribute changes so far
- Gym Directory tab: grid of gym cards (name, region, facility quality, development focus, number of fighters training there)
- Click gym → expand to show fighters training there + gym details
- Voice phrases for gym quality: "world-class" (90+), "elite" (75-89), "solid" (60-74), "adequate" (40-59), "bare-bones" (<40)

---

## 2. Implementation

Single subagent builds all 4 screens. Pattern: `staff_market.js` (IIFE, bridge methods, CSS, nav wiring).

Files to create:
- `src/web/js/scouting.js` + `src/web/css/scouting.css`
- `src/web/js/rivalries.js` + `src/web/css/rivalries.css`
- `src/web/js/hall_of_fame.js` + `src/web/css/hall_of_fame.css`
- `src/web/js/gyms.js` + `src/web/css/gyms.css`

Files to modify:
- `src/web/index.html` — add 8 script/link tags
- `src/web/js/app.js` — wire 4 nav items in navigate() + navigateBack()
- `src/web/js/bridge.js` — add bridge methods
- `src/app_web.py` — add 4+ API methods

## 3. Voice + design rules
- No raw potential/attribute numbers — voice phrases
- Heat/confidence/camp-state are OK as raw integers (per CONVENTIONS §14)
- Gold accents, dark bg, section headers with accent bars
- Ownership language where appropriate
- Empty states with voice-appropriate phrases
