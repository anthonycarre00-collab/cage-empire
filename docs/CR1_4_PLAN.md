> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Change Requests CR-1..4 (User Feedback Round 1)

> **Status:** ACTIVE — planning + implementation tracker for the 4
> change requests raised after testing Phase R + Phase E1.
> **Source:** user feedback in IM chat 2026-08-03.
> **Supervisor:** main agent. Two parallel subagents will implement.
> **Source of truth for:** promo-name substitution, attribute
> progress/decay indicators, gender separation, Open Market filters.

---

## 0. Summary of user feedback

> "OK this is very good but some minor changes. Its hard to tell which
> promotion the play is in control of — mentions of 'your promotion'
> need to changed to be player's actual promotion. Fighter profile
> screens are good but we need some progress/decay indicators on
> attributes using standard green>red gradients — this will also help
> prove that attributes are growing or decaying as intended by design
> and shows progress to player. Also, the weight classes and various
> text descriptions need to be separated by gender or using a gender
> flag. Open market screen main table needs filters/sort and various
> search options that don't break our later scouting services. Plan
> and implement those changes then proceed with next phase, next
> screens. Act as supervisor."

Four discrete change requests:

| # | Title | Files touched | Subagent |
|---|---|---|---|
| CR-1 | Replace "your promotion" with actual promo name | dashboard.js, fighter_profile.js | A (dashboard) + B (fighter_profile) |
| CR-2 | Attribute progress/decay indicators (green→red gradient) | fighter_profile.js, app_web.py, fighter_profile.css | B |
| CR-3 | Gender separation (weight classes + pronouns) | roster.js, free_agents.js, fighter_profile.js, app_web.py | A (roster) + B (free_agents + fighter_profile) |
| CR-4 | Open Market filters/sort/search (scouting-safe) | free_agents.js, app_web.py, free_agents.css | B |

---

## 1. CR-1 — Promo name substitution

### 1.1 Problem
Two places in the UI say "YOUR PROMOTION" / "your promotion" instead
of the player's actual promotion name. This makes it hard to tell
which promotion the player is controlling, especially after switching
promos or testing multiple saves.

### 1.2 Specific locations

**dashboard.js:229** — section header `YOUR PROMOTION'S HEALTH`
- Replace with: `[PROMO_NAME]'S HEALTH` (e.g., "ALPHA COMBAT FEDERATION'S HEALTH")
- The promo name is already in scope: `d.promo_name` (see dashboard.js:142)
- Implementation: `'<span class="ce-sec-title ce-sec-title-green">' + escapeHtml(d.promo_name.toUpperCase()) + "'S HEALTH</span>"`

**fighter_profile.js:153** — header promo line `Fights for YOUR promotion · Trains at [gym]`
- Replace with: `Fights for [PROMO_NAME] · Trains at [gym]`
- The promo name is already in scope: `h.promo_name` (see fighter_profile.js:156 — already used for non-roster case)
- Implementation: `promoLine = 'Fights for ' + escapeHtml(h.promo_name) + ' · Trains at ' + escapeHtml(h.gym_name);`

### 1.3 Acceptance criteria
- [ ] Dashboard section title shows the actual promo name + "'S HEALTH" (all caps, gold accent)
- [ ] Fighter Profile header for player-roster fighters shows "Fights for [PROMO_NAME]" not "Fights for YOUR promotion"
- [ ] No regression: non-roster fighters still show their actual promo name (no change)
- [ ] Pre-game screen "Choose Your Promotion" is unchanged (that's player-facing selection, not ownership)

---

## 2. CR-2 — Attribute progress/decay indicators

### 2.1 Problem
Fighter Profile's Attributes tab shows 26 StatBars with voice phrases
("elite", "serviceable", "limited") but NO indicator of whether each
attribute is currently growing, stable, or decaying. The user wants
to see at a glance which attributes are improving vs decaying, both
to prove the simulation is working and to give the player a
progression signal.

### 2.2 Data sources available

1. **`training_camps.attribute_changes`** (JSON column) — records
   per-camp deltas as `{"punch_power": 2, "cardio": 1, ...}`. Already
   populated for every completed camp. This is the primary source
   for "recent growth".

2. **`fighter_attributes.updated_at`** — timestamp of last change.
   Lets us detect "stale" attributes (not trained recently).

3. **`effective_ceiling`** calculation in `tick_processor.py:674`:
   `effective_ceiling = potential × age_factor × health_factor ×
   personality_factor`. When `effective_ceiling < current_value`,
   the fighter is in theoretical decline (their ceiling has dropped
   below their current attribute level due to age/health). This is
   the primary source for "decay trajectory".

### 2.3 Design — Trajectory Indicator

Each StatBar gets a small **trajectory chip** appended to the right
of the phrase text. Five states, color-graded green → red:

| State | Condition | Color | Icon | Tooltip |
|---|---|---|---|---|
| `surging` | Last 90d net gain ≥ +5 | bright green (#3fcc6e) | ▲▲ | "Surging — gained +N in last 90 days" |
| `growing` | Last 90d net gain +1 to +4 | light green (#7dd99a) | ▲ | "Growing — gained +N in last 90 days" |
| `stable` | Last 90d net change = 0 AND effective_ceiling ≥ current | gray (#9aa3ad) | → | "Stable — no recent change" |
| `declining` | effective_ceiling < current (ceiling dropped below current due to age/health) OR last 90d net change ≤ -1 | orange (#e8a04a) | ▼ | "Declining — ceiling has dropped below current level" |
| `decaying` | effective_ceiling < current AND age ≥ 33 | red (#d64545) | ▼▼ | "Decaying — age-related decline" |

The chip is a small rounded badge (24×18px) with the icon + color.
On hover, shows the tooltip with the specific delta + reason.

### 2.4 Implementation

**Backend (app_web.py):**
- Augment `get_fighter_profile_data(fighter_id)` to compute a new
  `attribute_trajectory` dict in the payload:
  ```python
  "attribute_trajectory": {
      "punch_power": {"state": "growing", "delta_90d": 3, "reason": "Last 90d: +3 from 2 camps"},
      "cardio": {"state": "stable", "delta_90d": 0, "reason": "No recent training camps"},
      "chin": {"state": "declining", "delta_90d": 0, "reason": "Ceiling dropped below current (age 34)"},
      ...
  }
  ```
- New helper function `_compute_attribute_trajectory(conn, fighter_id)`
  that:
  1. Queries the last 90 days of `training_camps.attribute_changes`
     for this fighter. Sums per-attribute deltas.
  2. Computes `effective_ceiling` using the same formula as
     `tick_processor.py:674` (age_factor × health_factor ×
     personality_factor × potential).
  3. For each attribute: compare current value vs effective_ceiling
     vs delta_90d → assign state per the table above.
  4. Returns the dict.

**Frontend (fighter_profile.js):**
- Modify `renderStatBar(key, phrase)` to accept a 3rd argument
  `trajectory` and render the chip after the phrase.
- The chip HTML:
  ```html
  <span class="ce-fp-trajectory ce-fp-trajectory--growing" title="Growing — gained +3 in last 90 days">▲</span>
  ```
- CSS classes: `ce-fp-trajectory--surging`, `--growing`, `--stable`,
  `--declining`, `--decaying`. Each sets background-color + text-color
  per the table in §2.3.

**CSS (fighter_profile.css):**
- Add `.ce-fp-trajectory` base styles (inline-block, rounded, 24×18px,
  font-size 11px, font-weight bold, text-align center, line-height 18px,
  margin-left 6px, cursor help).
- Add the 5 state modifier classes with their colors.

### 2.5 Acceptance criteria
- [ ] Each of the 26 attribute StatBars shows a trajectory chip
- [ ] Chip color matches the state per §2.3 table
- [ ] Hover tooltip shows the reason ("Growing — gained +N in last 90 days" etc.)
- [ ] A 20-year-old prospect with recent camps shows mostly green chips
- [ ] A 36-year-old veteran shows mostly orange/red chips
- [ ] A plateaued mid-career fighter shows mostly gray chips
- [ ] No raw potential integer is exposed (only the trajectory state + delta)

---

## 3. CR-3 — Gender separation

### 3.1 Problem
Weight classes are not visually separated by gender in the filter
dropdowns. Text descriptions use male pronouns ("HE", "HIS", "HIM")
even for female fighters. The schema already has `fighters.gender`
and `weight_classes.gender` columns — we just need to use them in
the UI.

### 3.2 Weight class dropdown grouping

In roster.js (line 88) and free_agents.js, the weight class `<select>`
currently shows all classes flat. Group them:

```
All Weight Classes
— Men's —
  HEAVYWEIGHT (8)
  LIGHT HEAVYWEIGHT (12)
  ...
— Women's —
  FEATHERWEIGHT (5)
  BANTAMWEIGHT (3)
  ...
```

Implementation: use `<optgroup label="Men's">...</optgroup>` for the
gender grouping. The weight_classes payload from
`get_roster_data` and `get_free_agents` needs to include the `gender`
field per class.

**Backend changes (app_web.py):**
- `get_roster_data` weight_classes query (line 972): add `wc.gender`
  to the SELECT + include `"gender": w[3]` in the dict.
- `get_free_agents` weight_classes query: same change.

**Frontend (roster.js + free_agents.js):**
- Render `<optgroup>` per gender when building the WC `<select>`.

### 3.3 Gender-correct pronouns

Audit ALL UI labels with gendered pronouns. Substitute based on the
fighter's gender (already in the API payload as `header.gender` for
fighter_profile, and per-row for roster/free_agents tables).

**Pronoun mapping:**

| Male | Female | Neutral (use if gender unknown) |
|---|---|---|
| HE | SHE | THEY |
| HIS | HER | THEIR |
| HIM | HER | THEM |
| HE'S | SHE'S | THEY'RE |

**Specific labels to fix (per REWARD_REVIEW.md §4 + audit):**

**roster.js:**
- Column "WHERE HE IS" → dynamic: `WHERE HE IS` / `WHERE SHE IS` / `WHERE THEY ARE`
- Column "RIGHT NOW" — no pronoun, OK
- Button "Open His Dossier" → `Open His Dossier` / `Open Her Dossier` / `Open Their Dossier`
- Empty state "No one in your stable matches that." — gender-neutral, OK

But wait — column headers apply to ALL rows in the table, which may
have mixed genders. So column headers should be GENDER-NEUTRAL:
- "WHERE HE IS" → "WHERE THEY ARE" (column header — applies to all rows)
- "Open His Dossier" button — applies to the SELECTED row only, so
  this CAN be gendered. But to keep it simple, make it gender-neutral:
  "Open Dossier" or "Open Their Dossier".

**Decision:** Column headers → gender-neutral ("WHERE THEY ARE",
"WHAT THEY'RE DOING LATELY"). Per-row actions (button on selected
row) → can use the selected fighter's gender. But to avoid
complexity, use gender-neutral for buttons too.

**fighter_profile.js:** Per-fighter, so CAN use gendered pronouns.
- "WHO HE IS" → `WHO HE IS` / `WHO SHE IS` (based on `h.gender`)
- "HIS CAREER SO FAR" → `HIS CAREER SO FAR` / `HER CAREER SO FAR`
- "WHAT HE'S DONE LATELY" → `WHAT HE'S DONE LATELY` / `WHAT SHE'S DONE LATELY`
- "WHAT HE BRINGS TO THE CAGE" → `WHAT HE BRINGS` / `WHAT SHE BRINGS`
- "WHO HE IS WHEN THE DOOR CLOSES" → `WHO HE IS WHEN THE DOOR CLOSES` / `WHO SHE IS WHEN THE DOOR CLOSES`
- "BELTS HE'S WON FOR YOU" → `BELTS HE'S WON FOR YOU` / `BELTS SHE'S WON FOR YOU`
- "THE FIGHTS THAT DEFINED HIM" → `THE FIGHTS THAT DEFINED HIM` / `THE FIGHTS THAT DEFINED HER`
- "WHAT THEY'RE SAYING ABOUT HIM" → `...ABOUT HIM` / `...ABOUT HER`
- "Fights for [PROMO]" — no pronoun, OK
- "28 years old · Your Lightweight" — no pronoun, OK
- Empty states: "We don't have a read on him yet." → `...on him` / `...on her`
- "He hasn't made his walk yet." → `He hasn't made his walk` / `She hasn't made her walk`

**free_agents.js:** Per-row, but column headers are shared. Make
column headers gender-neutral. Sign modal is per-fighter — can be
gendered.
- Modal "Bring [Name] into your stable?" — no pronoun, OK
- Modal "Your signing will be announced as news." — no pronoun, OK

### 3.4 Acceptance criteria
- [ ] Roster weight class dropdown shows Men's / Women's optgroups
- [ ] Free Agents weight class dropdown shows Men's / Women's optgroups
- [ ] Column headers in roster + free_agents are gender-neutral
- [ ] Fighter Profile section titles use correct pronoun for the fighter's gender
- [ ] Empty states use correct pronoun
- [ ] A female fighter's profile shows "WHO SHE IS", "HER CAREER SO FAR", etc.
- [ ] A male fighter's profile shows "WHO HE IS", "HIS CAREER SO FAR", etc.

---

## 4. CR-4 — Open Market filters/sort/search

### 4.1 Problem
Open Market (free_agents.js) currently has filters for WC, Ceiling,
and Search — but NO sort columns (all marked `sortable: false` on
line 60-67), NO gender filter, and the pagination is basic. The user
wants the same level of filter/sort as the Roster screen.

### 4.2 Scouting safety rule (CRITICAL)

**Per docs/SCREEN_DATA_AUDIT.md §3 + free_agents.js:14-18:**
- Ceiling display: voice phrase ("Elite", "High") if scouted, else "????"
- NEVER displays raw potential integer
- Sort by ceiling must NOT expose unscouted fighters' true ceiling

**Implementation rule:** when sorting by ceiling, unscouted fighters
("????") always sort LAST regardless of sort direction. This prevents
the player from inferring "????" fighters' true ceiling by sorting
ascending vs descending.

### 4.3 New filters/sort to add

**Filters (add to state.filters):**
- `gender: 'all'` — All / Men / Women (mirror roster.js pattern)
- `age_range: 'all'` — All / Prospects (≤25) / Prime (26-32) / Veterans (33+)
- `nationality: 'all'` — populated from DB (top 20 nations by FA count)

**Sort columns (set `sortable: true`):**
- `name` (asc/desc) — alphabetical
- `age` (asc/desc) — numeric
- `wc` (asc/desc) — by weight class name
- `ceiling` (asc/desc) — by scouted ceiling phrase tier (unscouted LAST)
- `record` (asc/desc) — by win percentage

**Search improvements:**
- Search by name (existing) — keep
- Search by nationality (new) — matches `nat_code` or `nat_name`
- 200ms debounce (already exists via `_searchTimer`)

**Pagination:**
- Already exists at 20 rows/page — keep
- Add "Page X of Y" indicator (currently only shows prev/next buttons)

### 4.4 Backend changes (app_web.py `get_free_agents`)

The existing `get_free_agents` already supports `filters` dict. Add
support for the new keys:
- `gender` — `WHERE f.gender = ?` when not 'all'
- `age_range` — `WHERE f.date_of_birth <= ? AND f.date_of_birth >= ?`
- `nationality` — `WHERE f.nation_id = ?`
- `sort_col` + `sort_dir` — apply to ORDER BY (with the ceiling-sort
  unscouted-last rule)

Add to the payload:
- `weight_classes` (already there) — add `gender` field per class
- `nationalities` — new: list of `{id, name, count}` for top 20 nations

### 4.5 Frontend changes (free_agents.js)

- Add gender filter `<select>` (mirror roster.js:106-111)
- Add age range filter `<select>`
- Add nationality filter `<select>`
- Update COLUMNS to set `sortable: true` for name/age/wc/ceiling/record
- Update header click handler to toggle sort_col + sort_dir + refetch
- Add "Page X of Y" indicator next to pagination buttons
- Ensure ceiling sort puts "????" rows last

### 4.6 Acceptance criteria
- [ ] Gender filter works (All / Men / Women)
- [ ] Age range filter works (Prospects / Prime / Veterans)
- [ ] Nationality filter works (top 20 nations)
- [ ] Sort by name asc/desc works
- [ ] Sort by age asc/desc works
- [ ] Sort by wc asc/desc works
- [ ] Sort by ceiling asc/desc works (unscouted "????" always last)
- [ ] Sort by record asc/desc works (by win %)
- [ ] Page X of Y indicator shows correct count
- [ ] Search by name + nationality works (200ms debounce)
- [ ] Weight class dropdown shows Men's / Women's optgroups
- [ ] NO raw potential integer is ever exposed

---

## 5. Subagent assignments

### Subagent A — Dashboard + Roster (CR-1 dashboard + CR-3 roster)
**Task ID:** CR-A-DASHBOARD-ROSTER
**Files owned:** `src/web/js/dashboard.js`, `src/web/js/roster.js`,
`src/app_web.py` (only `get_roster_data` weight_classes query),
`src/web/css/roster.css` (minor).
**Scope:**
- CR-1 in dashboard.js:229 — replace "YOUR PROMOTION'S HEALTH" with promo_name
- CR-3a in roster.js — weight class dropdown grouped by gender (optgroup)
- CR-3a in app_web.py `get_roster_data` — add `wc.gender` to weight_classes payload
- CR-3b in roster.js — make column headers gender-neutral ("WHERE THEY ARE")

### Subagent B — Fighter Profile + Open Market (CR-1 fp + CR-2 + CR-3 fp+fa + CR-4)
**Task ID:** CR-B-FIGHTERPROFILE-MARKET
**Files owned:** `src/web/js/fighter_profile.js`, `src/web/js/free_agents.js`,
`src/app_web.py` (only `get_fighter_profile_data` + `get_free_agents`),
`src/web/css/fighter_profile.css`, `src/web/css/free_agents.css`.
**Scope:**
- CR-1 in fighter_profile.js:153 — replace "YOUR promotion" with promo_name
- CR-2 in fighter_profile.js — trajectory chip on StatBars
- CR-2 in app_web.py `get_fighter_profile_data` — compute `attribute_trajectory` dict
- CR-2 in fighter_profile.css — `.ce-fp-trajectory--*` classes (5 states)
- CR-3a in free_agents.js — weight class dropdown grouped by gender
- CR-3a in app_web.py `get_free_agents` — add `wc.gender` to weight_classes payload
- CR-3b in fighter_profile.js — gendered pronouns in section titles + empty states
- CR-3b in free_agents.js — gender-neutral column headers
- CR-4 in free_agents.js — gender/age/nationality filters + sort columns + page indicator
- CR-4 in app_web.py `get_free_agents` — support new filter keys + sort_col/sort_dir
- CR-4 in free_agents.css — minor filter styling

### Why split this way
- fighter_profile.js is touched by CR-1 + CR-2 + CR-3b — all owned by Subagent B to avoid conflicts
- free_agents.js is touched by CR-3a + CR-3b + CR-4 — all owned by Subagent B
- roster.js is touched only by CR-3 — owned by Subagent A
- dashboard.js is touched only by CR-1 — owned by Subagent A
- app_web.py is touched by both — but they touch DIFFERENT methods (roster_data vs fighter_profile_data vs free_agents), so no conflict

Both subagents can run in parallel without file-level conflicts.

---

## 6. Out of scope (defer to later phases)

- Phase E2 (real PPV/broadcast model) — next phase after CR-1..4
- Phase E3 (player financial levers)
- Phase E4 (Staff Market screen)
- New screens (Calendar, News, Scouting, etc.) — Phase S
- Attribute history table (proper snapshotting) — could be Phase E5 if needed
- Replacing the fake cash sparkline — Phase R follow-up

---

## 7. After CR-1..4 ship

Per `docs/MASTER_PLAN.md`:
- **Phase E2** (real PPV/broadcast revenue model) is the next planned phase.
- Estimated 3-4 dev-days.
- Replaces the flat `$500k for ppv_global` lookup with `buyrate × price × households`, scales with card quality.
- Source doc: `docs/ECON_STAFF_PLAN.md` §3.
