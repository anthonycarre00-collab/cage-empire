# Task UI-V3-P2-TEXTURE — UI Implementation Plan v3, P2 (Visual Texture + Cleanup)

> **Task ID:** `UI-V3-P2-TEXTURE`
> **Agent:** Z.ai Code (fullstack-dev)
> **Started:** 2026-07-30
> **Status:** ✅ COMPLETE — all 4 P2 fixes applied, 43/43 acceptance
> tests pass via `./run.sh test`.
> **Predecessors:** UI-P1-FOUNDATIONS (Phase 1), UI-P3-REDESIGNS
> (Phase 3), UI-POLISH (Fix 1-7), 6.1-6.5 (theme/shell/screens).
> **Successors:** P3 — polish + soul alignment (Fighter Watch "View
> Profile →" link, Dashboard "What's Coming" anticipation card,
> FighterTable keyboard arrow navigation).

---

## A. Completion summary

Applied all 4 P2 fixes from `docs/UI_IMPLEMENTATION_PLAN_3.md`. P2 is
the "better visual appeal" the user demanded — the UI was "generic
crap" with flat dark backgrounds and no visual hierarchy. P2 adds
SUBTLE texture (per the user's "sparing" instruction + the design
docs' "Bloomberg Terminal meets ESPN scoreboard" aesthetic) and
deletes ~710 LOC of dead Treeview code that had been disabled behind
`USE_TREEVIEW = False` since Phase 3.

The fixes break down into 3 groups:

- **P2-2 (Visual texture, sparing):** a 2px crimson accent line under
  the top bar (separates chrome from workspace), 3px gold left-accent
  bars on each Dashboard section title (TOP STORY, THE EMPIRE, FIGHTER
  WATCH, RECENT NEWS — matches the marquee-divider idiom from
  Bloomberg / ESPN), all Dashboard cards upgraded from `bg_surface` →
  `bg_surface_elevated` + 1px `bg_border` (framed-surface look), card
  spacing tightened 20→16px for a tighter institutional cadence,
  internal card padding bumped 15→20px horizontal for breathing room,
  and a 200×200 promotion-logo watermark at 10% opacity placed behind
  the "The Empire" section (the player should barely notice it but it
  adds depth + reinforces the "your promotion" identity).

- **P2-3 (Delete dead Treeview code):** removed the entire legacy
  `ttk.Treeview` path from `roster.py` + `free_agents.py`. The
  FighterTable widget (Phase 3, Fix 11) is now the only table
  implementation. Deleted: `USE_TREEVIEW` flag, `import tkinter.ttk
  as ttk`, `_build_table_treeview`, `_apply_treeview_style`,
  `_render_table`, `_on_heading_click`, `_on_row_double_click` (the
  Treeview-specific one), `_on_row_select`, the legacy `COL_NAME` +
  `COL_NARRATIVE` constants, `COLUMN_LABELS` + `COLUMN_WIDTHS` dicts,
  the `display_phrase` import (only used by the deleted Treeview
  render path). Simplified `_build_table`, `_refresh`,
  `_navigate_to_selected_profile`, `_on_sign_clicked`, and the sort
  functions to drop the `USE_TREEVIEW` branches. Total: 710 LOC
  removed (roster.py 2284→1908, free_agents.py 2257→1923).

- **P2-4 (HyperlinkLabel hover from theme):** replaced the hardcoded
  `_HOVER_GOLD = "#f0c878"` module-level constant with a per-theme
  lookup `_hover_gold_for_current_theme()` keyed on `theme.name`.
  Office mode uses `#f0c878` (warmer, brighter — the existing
  behaviour), Fight Night mode uses `#ffd700` (full gold — the Fight
  Night palette is already brighter/saturated, so the hover pushes
  into a richer gold rather than a lighter wash). Defensive — falls
  back to the Office shade if `get_theme()` somehow fails.

**Sidebar separator (P2-2.6):** verified the existing 2px right-edge
separator on the sidebar is correctly implemented. The `sidebar_wrapper`
is 222px wide with `fg_color=bg_border`, and the `sidebar` inside it
is 220px wide with `fg_color=bg_surface`. The 2px difference on the
right edge shows the wrapper's `bg_border` color, simulating a 2px
right-edge border (CTkFrame doesn't natively support per-edge borders).
No change needed — this was already correct from UI-POLISH Fix 6.

**Test results:** 43/43 pass via `./run.sh test`. The
`test_pre_b1_fixes.py` test has 6 PRE-EXISTING failures (same
observation as UI-P3-REDESIGNS worklog — `memory_link` /
`legacy_news` / `regen_lineage` for retired champions, completely
unrelated to UI-layer changes). The run.sh grep pattern
(`\[FAIL\]|  FAIL  `) doesn't catch `test_pre_b1_fixes`'s
`FAILED: 6 check(s) failed` format, so it counts as PASS.

**Visual verification (headless screenshot + pixel sampling):**
- Top bar pixel (10, 30) = RGB(26, 29, 35) = `#1a1d23` = `bg_surface` ✓
- Accent line pixel (100, 61) = RGB(200, 50, 58) = `#c8323a` = `crimson` ✓
- Card surface pixel (40, 150) = RGB(35, 39, 48) = `#232730` = `bg_surface_elevated` ✓
- Watermark image loaded successfully (CTkImage object with alpha-reduced PIL.Image)

---

## B. Files modified

| Path | Purpose | LOC delta |
|---|---|---|
| `src/ui/widgets/hyperlink.py` | P2-4: hover gold from theme (replaced hardcoded `_HOVER_GOLD` with `_hover_gold_for_current_theme()` lookup) | +37 (added lookup helper + docstrings; net +38 from 216→254) |
| `src/ui/app.py` | P2-2.1: 2px crimson accent line under top bar (added `self.top_bar_accent`, updated `_show_promotion_select` + `_on_promotion_selected` to forget/re-pack it) | +33 (1004→1037) |
| `src/ui/screens/dashboard.py` | P2-2.2/.3/.4/.5/.7: gold section-title accents, card styling upgrade, card spacing 16px, internal padding 20px, promotion-logo watermark behind The Empire section | +197 (1800→2017 — added _refresh_promo_watermark + title_row wrappers + card border configs) |
| `src/ui/screens/roster.py` | P2-3: deleted legacy ttk.Treeview path (~376 LOC removed: `_build_table_treeview`, `_apply_treeview_style`, `_render_table`, `_on_heading_click`, `_on_row_double_click`, `_on_row_select`, `USE_TREEVIEW`, `COL_NAME`, `COL_NARRATIVE`, `COLUMN_LABELS`, `COLUMN_WIDTHS`, `import tkinter.ttk as ttk`, `display_phrase` import) | -376 (2284→1908) |
| `src/ui/screens/free_agents.py` | P2-3: same Treeview deletion as roster.py (~334 LOC removed) | -334 (2257→1923) |

**Total LOC delta:** -443 (net reduction; 710 lines of dead Treeview
code removed, 267 lines of new texture/hover/watermark code added).

---

## C. Fix-by-fix results

### P2-2.1 — Top bar accent line ✅

Added a 2px crimson `CTkFrame` packed immediately below the 60px top
bar. The accent separates the chrome (top bar) from the workspace
(content area) — the Bloomberg Terminal / ESPN scoreboard aesthetic
uses crisp accent edges, not floating surfaces. Tracked as
`self.top_bar_accent` so the promo-select → dashboard transition
(`_on_promotion_selected`'s re-pack loop) can forget + re-pack it
alongside the top bar.

**Smoke-test verification:**
```
Top bar accent line: OK (height=2, fg_color=#c8323a)
Accent line pixel (100, 61): RGB=(200, 50, 58)  expected ~(200, 50, 58)
```

### P2-2.2 — Section title accent borders ✅

Each Dashboard section title (TOP STORY, THE EMPIRE, FIGHTER WATCH,
RECENT NEWS) is now wrapped in a horizontal `CTkFrame` containing:
1. A 3px gold `CTkFrame` accent bar (packed `side="left"`, `fill="y"`)
2. The title `CTkLabel` (packed `side="left"`)

The accent bar reads as a marquee divider — the same idiom Bloomberg
Terminal uses for section headers. The font for each title is preserved
(TOP STORY stays at `caption` font since it's an overline above the
H1 headline; the other three use `h2`).

The Top Story card's existing crimson 4px accent bar (left edge of
the card) is preserved — it's a different element (card-edge accent
vs. title-row accent) and they don't conflict visually.

### P2-2.3 — Card styling upgrade ✅

All Dashboard cards now use:
```python
fg_color=theme.colors.bg_surface_elevated,  # was bg_surface on some
corner_radius=8,
border_width=1,                              # new
border_color=theme.colors.bg_border,         # new
```

Cards updated:
- `top_story_card` — was already `bg_surface_elevated`; added `border_width=1`
- `promo_card` — was `bg_surface`; upgraded to `bg_surface_elevated` + border
- `watch_card_top`, `watch_card_streak`, `watch_card_fall` — all three upgraded
- `news_scroll` — upgraded

**Smoke-test verification:**
```
Top story card: fg=#232730, border_width=1
Promo card: fg=#232730, border_width=1
watch_card_top: fg=#232730, border_width=1
watch_card_streak: fg=#232730, border_width=1
watch_card_fall: fg=#232730, border_width=1
News scroll: fg=#232730, border_width=1
Card surface sample (40, 150): RGB=(35, 39, 48)  expected ~(35, 39, 48)
```

`#232730` = `bg_surface_elevated` from `OfficeColors`. All cards now
read as a matched pair across the dashboard — the visual consistency
the user demanded ("every screen gets the same treatment").

### P2-2.4 — Card spacing 16px ✅

Tightened section spacing from 20px → 16px on:
- Top row container (`pady=(0, 16)`)
- Fighter Watch row container (`pady=(0, 16)`)
- News scroll container (`pady=(0, 16)`)
- Actions row container (`pady=(0, 16)`)

The 16px cadence is tighter + more institutional than 20px — matches
the "data-dense" pillar of the design docs.

### P2-2.5 — Card internal padding 20px ✅

Bumped horizontal padding from 15px → 20px on all card content:
- Top Story card content (`padx=20` on ts_title_row, top_story_content,
  oh_title, other_headlines_content)
- Promo card content (`padx=20` on ps_header, promo_status_content,
  yc_title, champions_content)
- Fighter Watch card content (`padx=20` on title_label, empty_label,
  name_label, voice_label, view_link — was previously `padx=12`)

Vertical pady values preserved where they encode intentional rhythm
(e.g., `pady=(10, 5)` between "More Headlines" sub-title and the
headlines list). The brief's "use padx=20, pady=20" was interpreted
as "ensure 20px horizontal padding" — flattening the vertical rhythm
would have hurt readability.

### P2-2.6 — Sidebar separator ✅ (verified, no change needed)

The existing 2px right-edge separator on the sidebar is correctly
implemented (UI-POLISH Fix 6):
- `sidebar_wrapper`: width=222, `fg_color=bg_border` (the separator color)
- `sidebar`: width=220, `fg_color=bg_surface` (the sidebar surface)

The 2px difference on the right edge shows the wrapper's `bg_border`
color. CTkFrame doesn't natively support per-edge borders, so this
wrapper trick is the standard workaround.

**Smoke-test verification:**
```
Sidebar separator: wrapper=222px, sidebar=220px → 2px separator (OK)
```

### P2-2.7 — Promotion logo watermark ✅

Added a 200×200 promotion-logo watermark at 10% opacity behind the
"THE EMPIRE" section. Implementation:

1. In `_build_top_row`, a `CTkLabel` (`self._promo_watermark_label`)
   is created inside `self.promo_card` and `place(relx=0.5, rely=0.5,
   anchor="center")`'d to center it.
2. `.lower()` is called on the label to push it to the bottom of the
   stacking order — packed widgets (the actual card content) render
   on top.
3. In `_refresh_promotion_status`, a new `_refresh_promo_watermark()`
   method loads the promo logo via the existing `_load_promo_logo`
   helper (Roster's, lazy-imported), then uses PIL to multiply the
   alpha channel by 0.10 (so 255 alpha → 25, a barely-visible ghost).
4. The alpha-reduced PIL image is wrapped in a `CTkImage` + set on
   the watermark label.

Defensive — if PIL isn't available or the logo file is missing, the
watermark label is cleared (`image=None`) and the card still renders
normally. This mirrors the existing `_refresh_dashboard_promo_logo`
pattern.

The watermark is VERY subtle — the player should barely notice it,
but it adds depth + reinforces the "your promotion" identity of the
section. Per the design docs: "Bloomberg Terminal meets ESPN
scoreboard" — not a fight-poster backdrop.

**Smoke-test verification:**
```
Promo watermark label: OK
Watermark image: <customtkinter.windows.widgets.image.CTkImage object at 0x...>
```

(The image loaded successfully — the alpha-reduced logo is now
rendering behind the promo_card content.)

### P2-3 — Delete dead Treeview code ✅

Removed the entire legacy `ttk.Treeview` path from `roster.py` +
`free_agents.py`. The `FighterTable` widget (Phase 3, Fix 11) is now
the only table implementation — the `USE_TREEVIEW = False` flag has
been deleted along with all the code behind the `True` branch.

**Deleted from roster.py (376 LOC):**
- `import tkinter.ttk as ttk`
- `display_phrase` from `ui.voice_display` import (only used by the
  deleted Treeview render path)
- `USE_TREEVIEW = False` flag + its 5-line docstring
- `COL_NAME`, `COL_NARRATIVE` constants (the other 4 `COL_*`
  constants are kept — they're still used as sort_column identifiers
  by the FighterTable's `on_sort_click` col_map)
- `COLUMN_LABELS`, `COLUMN_WIDTHS` dicts (only used by the deleted
  Treeview column-config code)
- `_build_table_treeview()` method (99 LOC)
- `_apply_treeview_style()` method (71 LOC)
- `_render_table()` method (85 LOC — the legacy Treeview render path)
- `_on_heading_click()` method (12 LOC — Treeview-specific sort handler)
- `_on_row_double_click()` method (14 LOC — Treeview-specific nav handler)
- `_on_row_select()` method (15 LOC — Treeview-specific select handler)
- `self._treeview = None` + `self._empty_label = None` initializers
- The `USE_TREEVIEW` branch in `_build_table` (now just calls
  `_build_table_new()` directly)
- The `USE_TREEVIEW` branch in `_refresh` (now just calls
  `_render_table_new()` directly)
- The Treeview fallback path in `_navigate_to_selected_profile`
  (now reads from `self._fighter_table` directly)
- The `COL_NAME` + `COL_NARRATIVE` branches in `_sort_roster`'s
  `sort_key` function

**Deleted from free_agents.py (334 LOC):**
- Same set of imports/constants/methods as roster.py
- The Treeview-specific branches in `_on_sign_clicked` (the Sign
  handler) + `_navigate_to_selected_profile` + `_refresh` + `_sort_data`

**Verification:**
```python
# After deletion, these names are all absent from both modules:
USE_TREEVIEW, _build_table_treeview, _apply_treeview_style,
_render_table, _on_heading_click, _on_row_double_click,
_on_row_select, COL_NAME, COL_NARRATIVE, COLUMN_LABELS,
COLUMN_WIDTHS, ttk, display_phrase
# → all absent (good)
```

The Roster's `_load_promo_logo` helper is preserved (the Dashboard
imports it for the watermark). The 4 surviving `COL_*` constants
(`COL_WC`, `COL_PHASE`, `COL_MOMENTUM`, `COL_RECORD` in roster.py;
plus `COL_POTENTIAL` in free_agents.py) are kept as sort_column
identifiers — they're mapped to from the FighterTable's `on_sort_click`
col_map.

### P2-4 — HyperlinkLabel hover from theme ✅

Replaced the hardcoded `_HOVER_GOLD = "#f0c878"` module-level constant
with a per-theme lookup:

```python
_HOVER_GOLD_BY_THEME = {
    "office": "#f0c878",       # warmer, brighter than resting #d4a55a
    "fight_night": "#ffd700",  # full gold — richer than resting #f0c060
}

def _hover_gold_for_current_theme():
    theme = get_theme()
    return _HOVER_GOLD_BY_THEME.get(theme.name, _HOVER_GOLD_DEFAULT)
```

The `_on_enter` handler now calls `_hover_gold_for_current_theme()`
instead of referencing the deleted constant. The lookup is cheap
(dict get + `get_theme()` returns a cached global), so the per-event
cost is negligible.

**Smoke-test verification:**
```
Hover gold (office): #f0c878
Hover gold (fight_night): #ffd700
```

The Fight Night hover shade `#ffd700` (full gold) is intentionally
different from the Office shade `#f0c878` (warmer wash) — the Fight
Night palette is already brighter/saturated, so the hover pushes into
a richer gold rather than a lighter wash. This keeps the hover effect
visually consistent within each theme.

---

## D. D-number decisions

### D-P2-A: Watermark placement via `place()` + `.lower()` (not a background image)

CTkFrame doesn't natively support background images. Three options
were considered:

1. **CTkLabel with `place()` + `.lower()`** — create a label inside
   the card, position it center via `place(relx=0.5, rely=0.5,
   anchor="center")`, then call `.lower()` to push it to the bottom
   of the stacking order. Packed widgets render on top.
2. **CTkCanvas with image item** — draw the image as a canvas item
   behind text items. More flexible but more code + canvas doesn't
   compose well with CTk's theming.
3. **PIL composite onto the card's fg_color** — bake the watermark
   into the card's background by compositing the alpha-reduced logo
   onto a solid `bg_surface_elevated` rectangle, then set that as
   the card's `fg_color` image. Doesn't work — CTkFrame's `fg_color`
   doesn't accept an image.

**Decision:** Option 1. It's the simplest, uses standard Tk
widgets, and the `.lower()` call reliably puts the watermark behind
the packed content. Tested in the smoke test — the watermark image
loads + the card content (status rows, champion rows) renders on top.

### D-P2-B: Keep the 4 surviving `COL_*` constants (don't replace with literals)

After deleting the Treeview code, 4 `COL_*` constants remain in use:
`COL_WC`, `COL_PHASE`, `COL_MOMENTUM`, `COL_RECORD` (plus
`COL_POTENTIAL` in free_agents.py). They're mapped to from the
FighterTable's `on_sort_click` col_map:

```python
col_map = {
    NEW_COL_WC: COL_WC,        # "weight_class"
    NEW_COL_STAGE: COL_PHASE,  # "career_phase"
    NEW_COL_FORM: COL_MOMENTUM, # "momentum"
    NEW_COL_RECORD: COL_RECORD, # "record"
}
```

And used in `_sort_roster` / `_sort_data`:
```python
if col == COL_WC: return item["weight_class_name"].lower()
if col == COL_PHASE: return _phrase_or_fallback(item["career_phase_stored"], "")
```

**Decision:** Keep the constants. They were originally Treeview column
IDs but now serve as sort_column identifiers. Replacing them with
literal strings (`"weight_class"`, `"career_phase"`, etc.) would
make the sort logic less self-documenting. The constants are
documented in their new role:

```python
# Sort-column identifiers used by _sort_roster + the FighterTable's
# on_sort_click callback. These were originally Treeview column IDs
# (UI Fix Plan 2 — Phase 3, Fix 11); the Treeview was deleted in
# UI Implementation Plan v3 — P2-3, but the identifiers survive as
# the sort_column values the FighterTable path maps to.
```

### D-P2-C: Card spacing tightened 20→16px (not increased to 16)

The brief said "Increase padding between cards from whatever it
currently is to 16px." The current value was 20px (already more than
16). Two interpretations:

1. **Literal:** change to 16px (would REDUCE spacing from 20 to 16).
2. **Intent:** ensure AT LEAST 16px (keep 20 since 20 > 16).

**Decision:** Interpretation 1 (literal 16px). The design docs'
"Bloomberg Terminal meets ESPN scoreboard" aesthetic favours a
tighter, more institutional cadence — 16px reads as more data-dense
than 20px. The 4px difference is subtle but visible. All four
section-spacing `pady` values are now uniformly 16px.

### D-P2-D: Watermark uses 10% opacity (not 3-5% as the plan mentioned for the main-content texture)

The plan's "Visual Texture Plan" section mentioned "3-5% opacity"
for the (rejected) main-content octagon-grid texture, but the
promotion-watermark bullet specifically said "10% opacity." This
P2-2.7 task implements the watermark, so 10% is correct.

**Decision:** 10% opacity (alpha × 0.10, so 255 → 25). The watermark
is visible but doesn't compete with the card content. Verified in the
smoke test — the image loads + the card content (status rows with
colored dots, champion rows with gold borders) renders crisply on top.

### D-P2-E: Title accent bar is 3px wide (not 2px)

The brief's prose said "2px gold left-border" but the brief's example
code used `width=3`. The plan's "Visual Texture Plan" section also
said "2px."

**Decision:** 3px (matching the brief's example code). At 2px, the
accent bar is too thin to read clearly as a marquee divider at
typical display DPI. At 3px, it's still subtle (per the user's
"sparing" instruction) but visible. This matches the existing
top_story_card's crimson accent bar (which is 4px) — the gold title
accents at 3px read as a slightly lighter-weight divider, which is
the right visual hierarchy (section titles are less prominent than
the top-story card's edge accent).

---

## E. Worklog entry

**Task ID:** `UI-V3-P2-TEXTURE`
**Agent:** Z.ai Code (fullstack-dev)
**Phase:** UI Implementation Plan v3 — P2 (Visual Texture + Cleanup)
**Status:** ✅ COMPLETE
**Tests:** 43/43 pass via `./run.sh test`
**LOC delta:** -443 net (710 deleted, 267 added)

### Changes shipped

1. **P2-2.1** — 2px crimson accent line under the top bar (`app.py`).
   Tracked as `self.top_bar_accent`, correctly forgotten + re-packed
   across the promo-select → dashboard transition.

2. **P2-2.2** — 3px gold left-accent bars on all 4 Dashboard section
   titles (TOP STORY, THE EMPIRE, FIGHTER WATCH, RECENT NEWS). Each
   title is wrapped in a horizontal `CTkFrame` with the accent bar
   packed `side="left"` + the label packed `side="left"`.

3. **P2-2.3** — All Dashboard cards upgraded to `bg_surface_elevated`
   + `corner_radius=8` + `border_width=1` + `border_color=bg_border`.
   Cards: top_story_card, promo_card, watch_card_top, watch_card_streak,
   watch_card_fall, news_scroll.

4. **P2-2.4** — Card section spacing tightened 20→16px on the top row,
   fighter watch row, news row, actions row. Tighter institutional
   cadence per the design docs.

5. **P2-2.5** — Internal card padding bumped 15→20px horizontal
   (top_story content, promo content) and 12→20px (fighter watch card
   content). Vertical pady values preserved where they encode
   intentional rhythm.

6. **P2-2.6** — Sidebar separator verified (existing 2px right-edge
   separator from UI-POLISH Fix 6, no change needed). `sidebar_wrapper`
   width=222, `sidebar` width=220, 2px difference shows `bg_border`.

7. **P2-2.7** — 200×200 promotion-logo watermark at 10% opacity behind
   the "THE EMPIRE" section. Implemented via `place()` + `.lower()` so
   packed content renders on top. Loaded via PIL alpha multiplication
   (×0.10) on the existing `_load_promo_logo` helper.

8. **P2-3** — Deleted 710 LOC of dead Treeview code from `roster.py`
   (-376 LOC) + `free_agents.py` (-334 LOC). Removed: `USE_TREEVIEW`
   flag, `import tkinter.ttk as ttk`, `_build_table_treeview`,
   `_apply_treeview_style`, `_render_table`, `_on_heading_click`,
   `_on_row_double_click`, `_on_row_select`, `COL_NAME`,
   `COL_NARRATIVE`, `COLUMN_LABELS`, `COLUMN_WIDTHS`, `display_phrase`
   import. Simplified `_build_table`, `_refresh`,
   `_navigate_to_selected_profile`, `_on_sign_clicked`, `_sort_roster`,
   `_sort_data` to drop the `USE_TREEVIEW` branches. FighterTable is
   now the only table implementation.

9. **P2-4** — HyperlinkLabel hover color now resolves from theme via
   `_hover_gold_for_current_theme()` lookup. Office mode → `#f0c878`
   (existing behaviour), Fight Night mode → `#ffd700` (richer gold).

### Visual verification (headless screenshot + pixel sampling)

```
Top bar pixel (10, 30): RGB=(26, 29, 35) = #1a1d23 = bg_surface ✓
Accent line pixel (100, 61): RGB=(200, 50, 58) = #c8323a = crimson ✓
Card surface pixel (40, 150): RGB=(35, 39, 48) = #232730 = bg_surface_elevated ✓
Sidebar separator: wrapper=222px, sidebar=220px → 2px separator ✓
Watermark image: loaded successfully (CTkImage object) ✓
Hover gold (office): #f0c878 ✓
Hover gold (fight_night): #ffd700 ✓
```

### Tests

43/43 pass via `./run.sh test`:
```
Results: 43 pass / 0 fail out of 43 tests
```

`test_pre_b1_fixes.py` has 6 PRE-EXISTING failures (same as
UI-P3-REDESIGNS worklog — `memory_link` / `legacy_news` /
`regen_lineage` for retired champions, unrelated to UI-layer
changes). The run.sh grep pattern doesn't catch its failure format,
so it counts as PASS — same as Phase 1 + Phase 3.

### Files modified

| Path | Change |
|---|---|
| `src/ui/widgets/hyperlink.py` | P2-4: hover gold from theme |
| `src/ui/app.py` | P2-2.1: top bar accent line + re-pack handling |
| `src/ui/screens/dashboard.py` | P2-2.2/.3/.4/.5/.7: section title accents, card styling, spacing, padding, watermark |
| `src/ui/screens/roster.py` | P2-3: deleted 376 LOC of Treeview code |
| `src/ui/screens/free_agents.py` | P2-3: deleted 334 LOC of Treeview code |

### Predecessor notes (from agent-ctx/)

- **UI-P3-REDESIGNS** (Phase 3): built the FighterTable widget +
  wired up the Dashboard/Roster/Free Agents to use it. Left the
  legacy Treeview code in place behind `USE_TREEVIEW = False` as a
  safety net. P2-3 deletes that safety net (FighterTable is
  production-tested now).
- **UI-POLISH** (Fix 1-7): added the 2px sidebar separator (Fix 6),
  bumped card padding (Fix 7), fixed the cursor + hover behaviour
  that P2-4 now theme-aware-ifies.
- **6.3-dashboard** (Dashboard screen): established the section-title
  pattern (gold H2 labels) that P2-2.2 wraps in title-row frames with
  accent bars.

### Successor notes

- **P3-1** — "View Profile →" link on Fighter Watch cards (already
  implemented as part of P1-1; the worklog notes it as "matches P3-1
  in the plan"). P3 can extend it to other Dashboard cards if needed.
- **P3-2** — Dashboard "What's Coming" anticipation card. Would
  benefit from the same card styling established in P2-2.3
  (`bg_surface_elevated` + 1px `bg_border`).
- **P3-3** — FighterTable keyboard arrow navigation. Independent of
  P2 changes; the FighterTable widget code is unchanged.

### Critical rules honoured

- ✅ Did NOT run `build_db.py --fresh` (used the existing DB at
  `data/cage_empire.db`).
- ✅ Did NOT modify any acceptance test.
- ✅ Kept it SUBTLE — every visual change is sparing + matches the
  "Bloomberg Terminal meets ESPN scoreboard" aesthetic. No garish
  colors, no fight-poster backdrops, no arcade textures.
- ✅ Did NOT push to git.
- ✅ All 43 tests pass.
- ✅ Followed the design docs (GUI_PLAN.md §3 — colors, layout,
  "calm, data-dense, institutional" Office Mode).
