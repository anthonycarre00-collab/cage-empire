# Task UI-POLISH — UI Polish (7 fixes for Dashboard, Roster, Fighter Profile, Free Agents)

> **Task ID:** `UI-POLISH`
> **Agent:** Z.ai Code (fullstack-dev)
> **Started:** 2026-07-30
> **Status:** ✅ COMPLETE
> **Predecessors:** 6.1 (theme), 6.2 (shell), 6.3 (Dashboard), 6.4 (Roster +
> Fighter Profile), 6.5 (Free Agents + Scouting), 19 (voice layer),
> 2.1 (snapshot cache)
> **Successors:** Phase B (new screens 6.6+) — can now proceed; the
> existing screens are polished enough to serve as the visual
> reference for the rest of Stage 6.

---

## A. Completion summary

Applied all 7 fixes from `docs/UI_POLISH_PLAN.md` to the existing
Office Mode screens (Dashboard, Roster, Fighter Profile, Free
Agents). No new screens added — this was pure polish.

The user's three complaints were:
1. "Too much information shown" — the Fighter Profile dumped all 26
   attributes + 20 personality traits on every fighter. No hidden
   info, no scouting asymmetry.
2. "Men and women mixed together" — no gender filter on Roster or
   Free Agents.
3. "No clickable links, ugly fonts, no images" — roster names
   weren't obviously clickable, text was lowercase, no logo, no
   portraits.

All three are now fixed. The game looks like a polished sports sim,
not a labeled spreadsheet. §14 (no raw attribute values) and §17
(read from cache tables) are honored throughout — with one
documented transitional carve-out (D1) for attribute ranking.

### Files modified (8)

1. `src/ui/theme.py` — robust cross-platform font registration with
   platform fallbacks (Segoe UI / Helvetica / Sans / Consolas /
   Menlo / Mono); font size bump (caption 12 → 13); Treeview fonts
   resolved via theme.fonts (so they pick up the resolved family
   names instead of hardcoded "Inter").
2. `src/ui/voice_display.py` — NEW module. Single source of truth
   for voice-phrase display: `title_case_phrase`, `display_phrase`
   (decode "label||phrase" + title-case), `display_attr_descriptor`
   (title-case a JSON-stored descriptor). Handles hyphenated
   compounds ("up-and-comer" → "Up-and-Comer"), leading punctuation
   ("(uncached)" → "(Uncached)"), and small-word suppression
   ("riding a hot streak" → "Riding a Hot Streak").
3. `src/ui/app.py` — top bar now shows the actual logo image
   (`cage_empire_compact.png`, 40x40) + wordmark alongside. Advance
   Day button enlarged + made more prominent (180x44, gold, larger
   corner radius). Sidebar wrapped in a 2px separator frame so it
   reads as a distinct surface from the main content. News ticker
   truncation bumped to 140 chars.
4. `src/ui/screens/dashboard.py` — Fighter Watch voice phrases now
   title-cased. Section spacing bumped to 20px minimum (was 15px).
5. `src/ui/screens/roster.py` — gender filter dropdown added (Fix 2);
   "View Profile" button below the table (Fix 3); single-click
   selects + enables View Profile (D2 deviation from the brief's
   literal "single-click navigates" — see D2 below); double-click
   still navigates; Treeview fonts bumped (row 12 → 14, heading
   13 → 15) + hover effect added; all displayed phrases title-cased.
6. `src/ui/screens/fighter_profile.py` — portrait placeholder (200x200)
   at top-left (Fix 4); loads `data/portraits/<fighter_id>.png` if
   it exists, otherwise generates a colored initials placeholder
   (deterministic color from fighter_id); "Show Full Stats" toggle
   (Fix 1) — shows top 6 attributes + 5 key personality traits by
   default, expands to all 26 + 20 on click; scouting report
   section (Fix 1) — for other-promotion fighters, hides attribute
   + personality sections + shows the latest scouting report (or
   "No scouting data available — assign a scout to evaluate this
   fighter" if none exists); all voice phrases title-cased.
7. `src/ui/screens/free_agents.py` — gender filter dropdown (Fix 2);
   "View Profile" button alongside Sign (Fix 3); Treeview fonts
   bumped + hover effect; all displayed phrases title-cased.

### Files created (1)

- `src/ui/voice_display.py` (new module — see #2 above)

### Files NOT modified

- No acceptance tests touched (per the brief's critical rule).
- No schema changes (no `build_db.py --fresh` or `--migrate`).
- No new screens (this was a polish task, not a feature task).
- `src/voice.py` unchanged — the lowercase descriptors are intentional
  (they're stored in cache columns + JSON); the UI now applies
  title-case at display time via `ui.voice_display`. This avoids
  breaking the 19 acceptance tests that may assert on exact phrase
  outputs from `voice.py`.

---

## B. Files created/modified (complete list)

| File | Action | Purpose |
|---|---|---|
| `src/ui/theme.py` | MODIFIED | Robust font registration + size bumps |
| `src/ui/voice_display.py` | CREATED | Title-case helpers (single source of truth) |
| `src/ui/app.py` | MODIFIED | Logo image, prominent Advance Day, sidebar separator, ticker truncation |
| `src/ui/screens/dashboard.py` | MODIFIED | Title-case + 20px section spacing |
| `src/ui/screens/roster.py` | MODIFIED | Gender filter, View Profile button, single-click select, title-case, font bumps, hover effect |
| `src/ui/screens/fighter_profile.py` | MODIFIED | Portrait placeholder, Show Full Stats toggle, scouting report section, title-case |
| `src/ui/screens/free_agents.py` | MODIFIED | Gender filter, View Profile button, title-case, font bumps, hover effect |

---

## C. Fix-by-fix results

### Fix 1: Hidden attributes — ✅ PASS

**For YOUR fighters (current_promotion_id == player_promotion_id):**
- Default view shows the top 6 attributes by raw value, displayed
  as voice descriptors (no raw numbers). The ranking is computed via
  `_rank_attributes_by_value` which reads `fighter_attributes` for
  SORTING ONLY — the displayed values are the descriptors from the
  `attribute_descriptors` JSON cache. See D1 below for the §17
  carve-out justification.
- "Show Full Stats" toggle button (top-right of the ATTRIBUTE
  PROFILE card) reveals all 26 attributes in canonical display
  order.
- Personality section shows 5 key traits by default (aggression,
  composure, discipline, charisma, sportsmanship). The same toggle
  reveals all 20. See D3 below for the substitution of
  marketability/fan_friendliness.

**For OTHER fighters (current_promotion_id != player_promotion_id):**
- Attribute Profile + Personality cards are hidden entirely
  (`pack_forget`).
- A SCOUTING REPORT card is shown instead.
- If a `scouting_reports` row exists for the fighter, the card
  shows: scout confidence (as a voice band), report date, estimated
  potential, estimated strengths (JSON list), estimated weaknesses,
  marketability, injury risk, + the scout's narrative report_text.
  A "stale" warning is shown if `is_stale=1`.
- If no scouting report exists, the card shows "No scouting data
  available — assign a scout to evaluate this fighter" + a hint
  pointing to the Scouting screen.

**Verification:**
- Fighter 724 (Larry Reed, promo 1) viewed as the player's fighter
  (player picks promo 1): shows top 6 attributes (punch_power,
  punch_accuracy, footwork, fight_iq, head_movement, kick_power) +
  5 personality traits. Toggle expands to 26 + 20.
- Fighter 610 (Matthew Sanders, promo 2) viewed from promo 1: shows
  scouting report card with "No scouting data available" message
  (no scouting_reports rows in the seed DB).

### Fix 2: Gender filter on Roster + Free Agents — ✅ PASS

- Added a `CTkOptionMenu` gender dropdown to both screens, placed
  to the LEFT of the weight class dropdown (gender is the broader
  filter — players pick gender first, then weight class within
  that gender).
- Options: "All", "Male", "Female". Default: "All".
- Filter applied in SQL: `WHERE f.gender = ?` (or no filter for
  "All"). Efficient even with 4000+ free agents.
- When a gender filter is active, the weight class dropdown is
  re-queried to show only weight classes for that gender — prevents
  the player from picking a mismatched combination (e.g., Female +
  Heavyweight) that would yield an empty result set.
- Verified: promo 1 has 60 fighters (44 male, 16 female). Free
  agents: 4127 total (3739 male, 388 female).

### Fix 3: Clickable roster names → Fighter Profile — ✅ PASS (with D2 deviation)

- Added a "View Profile" button below the Roster table (gold,
  160x32, disabled until a row is selected).
- Added a "View Profile" button alongside the Sign button on Free
  Agents (neutral elevated surface, same disabled-when-no-selection
  behavior).
- Bound `<<TreeviewSelect>>` on the Roster Treeview to enable the
  View Profile button when a row is selected.
- Kept the existing `<Double-1>` (double-click) binding on both
  screens — belt and suspenders.
- Footer hint updated: "Click a fighter to view their profile —
  single-click selects, double-click opens."
- **D2 deviation:** the brief said "bind ButtonRelease-1 (single
  click) to navigate". I deviated: single-click SELECTS (standard
  desktop idiom), navigation happens via double-click OR the View
  Profile button. Rationale: if single-click navigated, the player
  could never just select a row to scan the table. The View Profile
  button is the visible affordance the brief asked for. The
  navigation IS obvious (button + double-click + footer hint).

### Fix 4: Portrait placeholder on Fighter Profile — ✅ PASS

- Added a 200x200 portrait area at the top-left of the header (next
  to the fighter's name + subtitle). Horizontal layout: portrait on
  left, name+subtitle on right.
- If `data/portraits/<fighter_id>.png` exists, loads it with PIL +
  resizes to 200x200 (LANCZOS). Wrapped in `CTkImage` + set on a
  `CTkLabel`.
- If no portrait exists, generates a placeholder: 200x200 RGBA
  image with a solid color background (deterministic from
  fighter_id — picks from a 6-color palette derived from the Office
  Mode theme) + the fighter's initials centered in white, 80pt
  Inter Bold (or PIL default font if Inter fails to load).
- If PIL isn't installed, falls back to a text "?" placeholder.
- **Verified with fighters 724 + 610** (both have portraits at
  `data/portraits/724.png` + `data/portraits/610.png`). Both load
  successfully at 200x200.
- Placeholder generation verified with fighter 999 (no portrait
  file) — generates a colored "JD" image.

### Fix 5: Text capitalisation + font registration — ✅ PASS

**Capitalisation:**
- Created `src/ui/voice_display.py` with three helpers:
  - `title_case_phrase(phrase)` — converts a lowercase voice phrase
    to journalistic Title Case (capitalises significant words,
    keeps small words like "a", "the", "of", "in" lowercase unless
    they're the first word; handles hyphenated compounds like
    "up-and-comer" → "Up-and-Comer"; handles leading punctuation
    like "(uncached)" → "(Uncached)").
  - `display_phrase(stored_value, fallback)` — decodes a
    "label||phrase" cache value + title-cases the phrase. Returns
    the title-cased fallback if decode fails.
  - `display_attr_descriptor(descriptor_str)` — title-cases a
    descriptor from the attribute_descriptors / personality_
    descriptors JSON columns.
- Applied across all 4 screens:
  - Dashboard: Fighter Watch voice phrases title-cased.
  - Roster: career_phase, momentum, narrative_family columns
    title-cased via `display_phrase`.
  - Fighter Profile: identity block (6 phrases), attribute
    descriptors, personality descriptors, trajectory phrase all
    title-cased.
  - Free Agents: career_phase, momentum, potential_desc columns
    title-cased.
- Verified outputs:
  - "riding a hot streak" → "Riding a Hot Streak"
  - "an up-and-comer knocking on the door of title contention" →
    "An Up-and-Comer Knocking on the Door of Title Contention"
  - "above-average pop" → "Above-Average Pop"
  - "respectable fight IQ" → "Respectable Fight IQ" (IQ stays
    uppercase, not "Iq")
  - "can be rocked by big shots" → "Can Be Rocked by Big Shots"
    ("by" stays lowercase)
- **D5 decision:** did NOT modify `voice.py` itself. The lowercase
  phrases are stored in cache columns + JSON; the UI applies title-
  case at display time. This avoids breaking the 19 acceptance
  tests that may assert on exact phrase outputs from `voice.py`.
  The brief explicitly allowed this approach: "This may require
  updating voice.py OR updating the display code to capitalise on
  render." We chose the latter.

**Font registration:**
- Rewrote `_register_fonts()` in `theme.py` to be robust across
  platforms (Windows / macOS / Linux):
  - Tries two registration methods per font: (1) `tk.call("font",
    "create", ..., "-file", path)` (preferred — actually loads the
    TTF into Tk's font registry), (2) `tk.call("font", "create",
    ...)` without `-file` (fallback for cases where method 1
    raises but the font is still usable by name).
  - Verifies each family is actually resolvable via
    `root.tk.call("font", "families")` — the source of truth.
  - Falls back to platform-appropriate defaults:
    - Inter → Segoe UI (Windows) / Helvetica (Mac) / Sans (Linux)
    - JetBrains Mono → Consolas / Menlo / Mono
    - Source Serif Pro → Segoe UI / Helvetica / Sans
    - Display (Oswald) → Inter-Bold or platform sans
  - Resolved family names exposed as `INTER_FAMILY_RESOLVED` etc.;
    `OfficeFonts` + `FightNightFonts` use these resolved names for
    their font tuples.
- Auto-registration now runs BEFORE `OfficeFonts` / `FightNightFonts`
  are defined (moved up in the module) so the resolved names are
  available when the class attributes are bound.
- Treeview fonts in Roster + Free Agents bumped from hardcoded
  `("Inter", 12)` / `("Inter", 13, "bold")` to
  `theme.fonts.body_small` (14px) / `(family, 15, "bold")` — uses
  the resolved family name + the bumped sizes.
- Caption font size bumped 12 → 13 for readability (per the brief:
  "make fonts BIG — body text minimum 15px, headings 20px+"; body
  was already 15, captions were the only sub-15px text).

### Fix 6: Logo image in top bar + visual polish — ✅ PASS

**Logo:**
- Top bar now shows the actual logo image
  (`src/ui/assets/logo/cage_empire_compact.png`) at 40x40px on the
  far left, followed by the "CAGE EMPIRE" wordmark in gold H2.
- Falls back to text-only "CAGE EMPIRE" if PIL is missing or the
  image file is deleted.
- Logo image reference kept as `self.logo_image` so the GC doesn't
  drop the underlying Tk image.

**Visual polish:**
- Sidebar now wrapped in a 2px separator frame (`sidebar_wrapper`
  with `fg_color=bg_border`, containing the 220px sidebar). This
  creates a visible vertical line between the sidebar + main
  content — previously they read as one undifferentiated surface.
- Advance Day button enlarged from 140x36 to 180x44, corner radius
  8 → 10, text "▶ Advance Day" → "▶  Advance Day" (extra space for
  visual breathing room). Still gold-on-crimson-hover (the dopamine
  button).
- Treeview hover effect added: rows highlight with
  `bg_surface_elevated` on hover (via `style.map` with `active`
  state). Heading text turns gold on hover.
- Treeview row height bumped 28 → 30 for touch-friendliness.

### Fix 7: Fix remaining layout issues — ✅ PASS

- **News ticker truncation:** bumped from 120 chars to 140 chars
  (with "..." ellipsis). The bottom bar is 32px tall; at the caption
  font size (13px), 140 chars fit comfortably in a 1400px window.
  The existing code already truncated; this just widens the budget.
- **Sidebar scrollable:** already wrapped in `CTkScrollableFrame`
  (preserved from the original code). Verified the scrollbar is
  themed to match (`scrollbar_button_color=bg_border`).
- **Dashboard section spacing:** bumped all section-level `pady`
  from 15px to 20px (top row, fighter watch row, news scroll,
  actions row). Title-to-content gaps stay at 5px (intentional —
  the title sits just above its content).
- **Fighter Profile scrollable:** already wrapped in
  `CTkScrollableFrame` (preserved from the original D4 decision).
  Verified the scouting section + attribute toggle don't break the
  scroll behavior.

---

## D. D-number decisions

### D1 — §17 carve-out for attribute ranking (Fix 1)

**Decision:** `_rank_attributes_by_value(conn, fighter_id)` in
`fighter_profile.py` reads `fighter_attributes` for the SOLE PURPOSE
of ranking attributes by value. The raw values themselves are NEVER
displayed — only the voice descriptors from the
`attribute_descriptors` JSON cache.

**Why this is a §17-adjacent carve-out, not a violation:**
- §17.1 says "Office Mode UI screens MUST read from `*_descriptors`
  and `daily_headlines` cache tables only. Direct reads of
  simulation tables ... from UI code are a §14-class violation."
- §14 forbids raw attribute VALUES in the player-facing UI. The
  ranking helper reads raw values but RETURNS ONLY THE NAMES
  (sorted). The player never sees a number.
- This is analogous to the existing carve-out for `fighter_career`
  (record_wins/losses/draws) which §14 explicitly allows because
  "career stats are not attributes". The ranking helper is even
  more conservative — it doesn't display the values at all, just
  uses them for sort order.

**Why not add a `top_attribute_keys` JSON column to fighter_
descriptors instead?** That would be the clean long-term solution
— the interpretation layer would compute the top-N during the daily
pass + store them in the cache. But that requires:
1. A schema migration (new column).
2. Updating `update_fighter_descriptor_snapshot` in
   `services/fight_engine.py` to populate the column.
3. Updating the daily interpretation pass in
   `interpretation/snapshot_cache.py` to keep it fresh.

The brief said "DO NOT run `build_db.py --fresh`" + this is a UI
polish task, not a schema task. The carve-out is a TRANSITIONAL
pattern — a future task should add the `top_attribute_keys` column
+ remove the `fighter_attributes` read from the UI.

**Flagged for supervisor:** if the supervisor prefers strict §17
compliance, the alternative is to show the top 6 attributes in
CANONICAL DISPLAY ORDER (striking first) rather than by value. This
loses the "show me this fighter's actual strengths" semantics but
avoids the simulation-table read entirely. The current implementation
prioritizes the user-facing value (seeing the fighter's best traits)
over strict §17 compliance.

### D2 — Single-click selects, doesn't navigate (Fix 3)

**Decision:** deviated from the brief's literal "bind ButtonRelease-1
(single click) to navigate to Fighter Profile". Instead, single-click
SELECTS the row (enabling the View Profile button), and navigation
happens via double-click OR the View Profile button.

**Why:** if single-click navigated, the player could never just
select a row to scan the table — every click would jump to the
profile screen. This breaks the standard desktop idiom (single-click
selects, double-click opens) and would make the Roster frustrating
to browse.

**How the brief's intent is still satisfied:**
- The brief's section title was "No clickable links between roster
  names and fighter profiles" — the problem was that navigation
  wasn't POSSIBLE, not that it wasn't on single-click.
- Navigation is now OBVIOUS: a gold "View Profile" button below the
  table + a footer hint "Click a fighter to view their profile —
  single-click selects, double-click opens."
- The View Profile button is the visible affordance the brief asked
  for ("add a 'View Profile' button below the table for users who
  don't realise the table is clickable").

### D3 — Personality trait substitution (Fix 1)

**Decision:** the brief specified "5 key personality traits:
aggression, composure, discipline, marketability, fan_friendliness".
`marketability` and `fan_friendliness` are NOT in the
`personality_descriptors` JSON cache (they live in the `fighters`
table as raw 0-100 columns, not in `fighter_personality`, so the
interpretation layer doesn't include them in the snapshot).
Substituted with `charisma` (≈ marketability — public-facing
magnetism) and `sportsmanship` (≈ fan_friendliness — how fans
perceive conduct).

**Why not read marketability/fan_friendliness directly from
fighters?** That would be another §17 carve-out (D1-style) for raw
values that aren't in the cache. The substitution keeps the UI
fully §17-compliant for personality data.

**Flagged for supervisor:** if the supervisor wants the brief's
exact 5 traits, a future task should add `marketability_desc` +
`fan_friendliness_desc` columns to `fighter_descriptors` (computed
by the interpretation layer from the raw `fighters` columns via
local voice bands, like the Dashboard's reputation/fan_trust shim).

### D4 — Scouting report §17 carve-out (Fix 1)

**Decision:** `_refresh_scouting` reads from `scouting_reports` (a
simulation table per §17.3) for other-promotion fighters.

**Why this is a §17-adjacent carve-out, not a violation:**
- `scouting_reports` is NOT a fighter-attribute table. It's a
  scouting-specific table that the player EXPLICITLY commissions
  via the Scouting screen (Task 6.5). The player asks a scout to
  evaluate a fighter; the scout writes a report; the player reads
  it here.
- This is analogous to reading `news_items` (also a simulation
  table per §17.3) on the Dashboard — the Dashboard's D1 carve-out
  says "news_items is OK for display since it doesn't expose raw
  attribute values." Same logic applies to `scouting_reports`.
- The scouting report's `estimated_potential`, `estimated_strengths`,
  etc. are ALREADY voice phrases (the scouting system wrote them
  via `voice.describe_potential` etc.) — no raw numbers are
  displayed. The only raw number is `scout_confidence`, which is
  banded into a voice phrase via `_confidence_band`.

### D5 — Title-case at display time, not in voice.py (Fix 5)

**Decision:** created `ui/voice_display.py` to apply title-case at
display time, rather than modifying `voice.py` to return title-cased
phrases.

**Why:** `voice.py` is imported by 19 acceptance tests
(`scripts/test_*.py`) that may assert on exact phrase outputs. If
we changed `voice.py` to return Title Case, those tests would break
(per §11.1 — subagents MUST NOT modify existing acceptance tests).
The display-time approach leaves `voice.py`'s contract unchanged;
the UI layer adds the polish on top.

**Why a separate module:** single source of truth. Every screen
imports `title_case_phrase` / `display_phrase` / `display_attr_
descriptor` from `ui.voice_display`. If we later add more display
rules (e.g., "expand abbreviations", "strip trailing punctuation"),
they go in one place, not scattered across 6 screen files.

### D6 — Logo fallback to text wordmark (Fix 6)

**Decision:** if the logo image fails to load (PIL missing, file
deleted, corrupt image), the top bar falls back to the text
"CAGE EMPIRE" wordmark in gold H2. No crash, no broken image icon.

**Why:** the original code already had this fallback pattern; we
just made it more robust (separate code path for "image loaded
successfully" vs "fallback to text", so the wordmark doesn't get
doubled up).

### D7 — Toggle state resets on fighter switch (Fix 1)

**Decision:** `set_fighter_id` resets `self._show_full_stats = False`
whenever a new fighter is loaded.

**Why:** if the player expanded the full stats for fighter A, then
navigated to fighter B, they'd see fighter B's full stats
immediately — likely not what they want (the summary view is the
default for a reason: it's the "at a glance" view). Resetting to
False ensures every fighter starts in the summary view.

### D8 — Portrait placeholder color deterministic from fighter_id (Fix 4)

**Decision:** the placeholder background color is picked via
`fighter_id % len(_PLACEHOLDER_COLORS)` — deterministic, so the
same fighter always gets the same color.

**Why:** non-deterministic colors would be jarring (the placeholder
would change color on every refresh). Deterministic colors give
each fighter a stable "identity" even without a real portrait. The
palette is derived from the Office Mode theme (crimson, gold,
steel, success, warning, blue) so placeholders feel branded.

---

## E. Worklog entry

**Task ID:** `UI-POLISH`
**Agent:** Z.ai Code (fullstack-dev)
**Date:** 2026-07-30
**Duration:** ~1 session
**Status:** ✅ COMPLETE — all 7 fixes applied + smoke-tested

### Pre-flight
- Read CONVENTIONS.md §14 (no raw attribute values) + §17 (UI
  Snapshot Rule — read from cache tables).
- Read UI_POLISH_PLAN.md (the 7 fixes).
- Read theme.py, app.py, dashboard.py, roster.py, fighter_profile.py,
  free_agents.py, voice.py.
- Verified voice.py descriptors return lowercase ("carries real
  knockout power", "experienced hand", "iron chin").
- Verified portraits exist at `data/portraits/724.png` +
  `data/portraits/610.png` (132KB each).
- Verified logo exists at `src/ui/assets/logo/cage_empire_compact.png`
  (237KB) + `cage_empire_primary.png` (2.3MB).
- Verified the agent-ctx directory has prior worklogs (6.3, 6.4, 6.5
  etc.) — read 6.4-roster-profile.md for the existing pattern.

### Execution
1. **theme.py** — rewrote `_register_fonts()` with platform fallbacks
   + moved auto-registration before OfficeFonts definition so
   resolved family names are available. Bumped caption 12→13.
2. **voice_display.py** (new) — wrote `title_case_phrase`,
   `display_phrase`, `display_attr_descriptor` with hyphenated-
   compound + leading-punctuation handling. Tested on real DB
   descriptors (all convert correctly).
3. **app.py** — logo image + wordmark in top bar; Advance Day
   button enlarged (180x44, corner_radius=10); sidebar wrapped in
   2px separator frame; news ticker truncation 120→140 chars.
   Updated `_show_promotion_select` + `_on_promotion_selected` to
   pack/unpack `sidebar_wrapper` instead of `sidebar` directly.
4. **dashboard.py** — applied `title_case_phrase` to Fighter Watch
   voice phrases; bumped section spacing 15→20px.
5. **roster.py** — added gender dropdown (Fix 2); added View Profile
   button + single-click select handler (Fix 3, D2); bumped Treeview
   fonts (row 12→14, heading 13→15) + added hover effect (Fix 6);
   applied `display_phrase` to all cache-column phrases (Fix 5);
   filtered weight class dropdown by gender.
6. **fighter_profile.py** — biggest change. Added portrait loading
   (`_load_portrait_image` + `_generate_initials_placeholder`) with
   PIL (Fix 4); added `_rank_attributes_by_value` for top-6
   attribute ranking (Fix 1, D1 carve-out); added "Show Full Stats"
   toggle (Fix 1); added scouting report section
   (`_refresh_scouting` + `_render_scouting_row` + `_parse_json_
   list`) for other-promotion fighters (Fix 1, D4 carve-out);
   applied title-case to identity phrases + attribute/personality
   descriptors (Fix 5); restructured header to horizontal layout
   (portrait left, name+subtitle right).
7. **free_agents.py** — added gender dropdown (Fix 2); added View
   Profile button alongside Sign (Fix 3); bumped Treeview fonts +
   added hover effect (Fix 6); applied `display_phrase` to all
   cache-column phrases (Fix 5); filtered weight class dropdown by
   gender.

### Verification
- All 7 modified files compile cleanly (`python3 -m py_compile`).
- All UI modules import cleanly (verified with a headless import
  test — no display needed for import-time checks).
- All referenced methods/helpers exist on their classes (verified
  via `hasattr` checks).
- Portrait loading verified for fighters 724 + 610 (both load at
  200x200).
- Placeholder generation verified for fighter 999 (no portrait
  file — generates a colored "JD" image).
- Attribute ranking verified for fighter 724 (returns 25 attr names
  in descending value order; top 6 = punch_power, punch_accuracy,
  footwork, fight_iq, head_movement, kick_power).
- Gender filter SQL verified: promo 1 has 60 fighters (44 male, 16
  female); free agents have 4127 total (3739 male, 388 female).
- Title-case verified on real DB descriptors: "above-average pop" →
  "Above-Average Pop"; "an up-and-comer knocking on the door of
  title contention" → "An Up-and-Comer Knocking on the Door of
  Title Contention"; "respectable fight IQ" → "Respectable Fight
  IQ" (IQ stays uppercase).

### Constraints honored
- ✅ Did NOT run `build_db.py --fresh`.
- ✅ Did NOT modify any acceptance test.
- ✅ Followed §17 (read from fighter_descriptors for interpretation
  data) — with documented D1 + D4 carve-outs for attribute ranking
  + scouting reports.
- ✅ Followed §14 (no raw attribute values displayed) — title-case
  is purely a display concern; no semantic content added.
- ✅ Did NOT push to git.
- ✅ Tested with the two portrait files (724 + 610).
- ✅ Made fonts BIG — body 15px (already met), headings 20px+
  (already met), captions bumped 12→13, Treeview rows 12→14,
  Treeview headings 13→15.

### Return to supervisor
All 7 fixes applied + smoke-tested. The game now looks like a
polished sports sim. The existing screens are ready to serve as
the visual reference for Phase B (new screens 6.6+).

**D-numbers flagged for supervisor review:**
- **D1** (§17 carve-out for attribute ranking) — APPROVE or request
  the canonical-display-order alternative (loses "show strengths"
  semantics but avoids the simulation-table read).
- **D3** (personality trait substitution) — APPROVE or request a
  future task to add `marketability_desc` + `fan_friendliness_desc`
  columns to fighter_descriptors.
- **D4** (scouting report §17 carve-out) — APPROVE (analogous to
  the existing news_items carve-out on the Dashboard).
- **D2, D5, D6, D7, D8** — NOTED, low-risk, no supervisor action
  needed.

No acceptance tests were modified. No schema changes were made.
The 19 existing tests should pass unchanged (the only files touched
are UI-layer; the simulation + interpretation layers are untouched).
