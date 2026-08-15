> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — UI Visual Redesign Plan (Ground-Up)

> **Task ID:** UI-REDESIGN-B
> **Agent:** Visual Redesign Expert (frontend-styling-expert)
> **Date:** 2026-07-30
> **Mode:** RESEARCH + PLANNING ONLY. No code or DB files modified.
> **Status:** Draft v1 — awaits supervisor sign-off before any code work begins.
> **Supersedes (in part):** `docs/GUI_PLAN.md` §3 (Visual Design System).
  The Soul doc (`CAGE_EMPIRE_SOUL.md`) remains the prime directive; this
  plan refines how that soul is *visualized* in light of the VLM critiques
  of the screenshots the user labeled "GUI mess."

---

## 0. Executive Summary

This plan is opinionated. The user asked for "meticulous detail, voice and
styling guidance" — not a menu of options. The headline recommendations:

1. **Keep the dual-mode split (Office + Fight Night) but tighten it.** Add a
   third, very narrow **Championship Mode** layer (a *skin*, not a full
   mode) that activates only during title fights on Fight Night. This
   gives the dopamine spike the user wants without a parallel design
   system. (§1.2)

2. **Replace the near-pure-black palette with a *layered charcoal*
   system.** 4 z-levels of background + a real card system with 1px
   borders + simulated shadows (no PIL drop-shadow compositing — too slow
   per the existing 167ms-to-1384ms refresh budget documented in the
   worklog). The "void" the VLM flagged is fixed by *depth*, not by
   brightening. (§2.2)

3. **Bundle a real display font: Oswald (Google Fonts, OFL license).**
   It's free, single-weight download, ~120 KB, and gives us the stadium-
   scoreboard condensed sans-serif the VLM specifically asked for. We
   ALSO keep Inter / JetBrains Mono / Source Serif Pro but fix the
   registration path that's silently failing (the resolved family check
   in `theme.py:347-358` is the prime suspect). (§3.2)

4. **Restructure the shell.** Drop the 32px bottom news ticker bar (it's
   noise on Office screens — the player already has the News Feed). Top
   bar goes from 60px to 56px with a *real* logo mark + branded wordmark
   + clean date/cash/Advance-Day grouping. Sidebar goes from 220px to
   **56px collapsed (icon-only, default) + 220px expanded (icon+label,
   on hover or pin)**. (§4.2)

5. **Adopt a 12-column grid + 4/8/12/16/24/32/48/64 spacing scale.**
   Every screen has at least one data visualization. Every nav item has
   an icon. (§4.3, §4.5)

6. **Build 15 reusable components first**, then redesign the 4 existing
   screens on top of them. The current screens were built bespoke per
   screen — that's why they look inconsistent. (§5)

7. **The FighterTable widget is the riskiest refactor** (it's used by 2
   of the 4 live screens). Wrap the new one behind a feature flag for
   one release before removing the old. (§9.3)

8. **Asset count grows from ~110 to ~165.** Most of the delta is the
   icon set (the icon paths in `theme.py:527-564` are currently pointing
   at empty files — they were placeholders). 32 P0 assets must land for
   the redesign launch. (§8)

The plan is structured so the supervisor can sign off on each section
independently — §1 sets the philosophy, §2-§4 are the design tokens,
§5 is the component library, §6 is the 4 redesigns, §7 is the 18 other
screens, §8-§10 are assets + sequencing + open questions.

---

## 1. Revised Design Philosophy

### 1.1 Re-stating "Calm Empire, Violent Canvas"

The GUI_PLAN §3.1 framed the duality as **Office Mode (90% of gameplay,
calm/institutional)** vs **Fight Night Mode (10% of gameplay, visceral/
narrative)**. That split is correct *as a structural decision* but the
implementation has failed the brief on both sides:

- **Office Mode reads as "void," not "calm."** The VLM critique is
  accurate: near-pure-black backgrounds (`#0f1115`) with no card
  system, no depth, no textures, no data viz, no iconography. Calm ≠
  empty. Calm = *quiet confidence* — Bloomberg Terminal, the FM2024
  sidebar, OOTP's standings grid. Those interfaces are *dense* but
  *ordered*. The current Dashboard is neither.

- **Fight Night Mode doesn't exist yet.** The Fight Resolution screen
  (the entire reason dual-mode exists) is not built. So Office Mode is
  carrying 100% of the visual weight with a palette designed to *contrast*
  with Fight Night — without Fight Night to contrast against, the palette
  reads as flat darkness.

**The revised philosophy:**

> **Calm Empire is the control room. Violent Canvas is the ring.**
> The control room is not a void — it's a Bloomberg Terminal lit by a
> desk lamp at 2 a.m., with three monitors of data, a single ticker
> scrolling, and a half-drunk coffee. It feels *occupied*. It feels
> like work is being done. The ring is bright, loud, and short —
> everything the control room isn't. The contrast between them is the
> whole emotional arc of the game.

This means Office Mode needs *more* density, *more* texture, *more*
incidentals — not less. The user's "SAP/Excel" complaint is the symptom
of "Office Mode without enough to look at." Density with discipline is
the fix.

### 1.2 Decision: keep dual-mode, add a Championship *skin*

**Recommendation:** Keep the Office + Fight Night dual-mode architecture.
Do NOT unify them — the user explicitly wants the contrast (HBO 24/7 vs
ESPN scoreboard). Unifying would flatten the dopamine arc.

**Add a narrow third layer: Championship Skin.** This is *not* a full
mode — it's a 4-color overlay applied to the Fight Night palette when
the fight being resolved is a title fight. It adds:

- Gold-leaf accent border on the cage heatmap
- Champion vs Challenger corner color swap (champion = gold corner,
  challenger = crimson corner — the standard boxing/MMA convention)
- Belt graphic displayed during pre-fight build-up and post-fight recap
- "TITLE FIGHT" badge on the top bar (replaces the standard "PPV #237")
- Slightly brighter accent saturation (5% lift on crimson + gold)

**Why this matters:** The Soul doc says the player collects stories.
Title fights are the *biggest* stories. Without a distinct visual
treatment, every Fight Night feels the same — and a 12-round decision
for a regional belt looks identical to a heavyweight championship KO.
Championship Skin gives the marquee moment marquee visual weight.

### 1.3 Five design principles (every screen must follow)

These are *rules*, not guidelines. A screen that violates any of them
fails review.

1. **Pure black is forbidden.** Minimum background `#0a0c10` (Office
   bg_base, §2.2) or `#06070a` (Fight Night bg_base). Pure `#000000`
   reads as a void and breaks the layered-charcoal depth system. The
   only place pure black is allowed is the Fight Night vignette overlay
   (a single PNG, not a background fill).

2. **Every screen has at least one data visualization.** A table is
   *not* a data viz. A bar chart, sparkline, heatmap, timeline, ring
   meter, or treemap counts. Roster gets a weight-class distribution
   bar. Dashboard gets a cash-flow sparkline. Free Agents gets a
   ceiling-vs-cost scatter plot. Fighter Profile gets an attribute
   radar. (Full list in §6 + §7.) This is the single biggest fix for
   the "SAP/Excel" complaint.

3. **Every nav item has an icon.** No exceptions. The current sidebar
   is text-only — this is the single most fixable "database tool"
   tell. (Asset list in §8.2.)

4. **Every clickable element has a hover state.** The VLM specifically
   called out "non-interactive look." Hover = lighter bg + cursor
   change + (for primary buttons) a subtle gold underline. No silent
   clickables.

5. **No raw attribute numbers in player-facing UI.** Per CONVENTIONS
   §14. Numbers (cash, dates, records, ranking position) are OK —
   those are game state, not fighter attributes. The line is: if it
   comes from `fighter_attributes`, `fighter_personality`, or
   `fighter_career.potential`, it must be voice-phrased. The redesign
   reinforces this by making voice phrases *visually distinct* from
   numeric values — phrases get a `descriptor` italic style, numbers
   get a `mono` style. The player should never confuse "18-5-0" with
   "carries real knockout power."

### 1.4 Reference products + what we steal from each

| Reference | What we steal | What we explicitly don't steal |
|---|---|---|
| **Bloomberg Terminal** | The 4-zone top-bar (logo / status / data / action), the dense-but-ordered card grid, the principle that "every pixel earns its place" | The amber-on-black palette (too drab — we use crimson+gold co-primaries) |
| **Football Manager 2024** | The sidebar-with-icons pattern, the "every screen has a sidebar of contextual actions" pattern, the dark-mode palette, the way player names are always gold hyperlinks | The vast sea of small text — FM2024 is *too* dense for our use case. We cap text density at ~70% of FM2024's |
| **ESPN scorestrip** | The horizontal scrollable strip of "current scores" — we use this pattern for the **Fight Night transport bar** (beat counter + round clock + speed controls) and for a future "live across the league" widget on Dashboard | The bright blue accent |
| **HBO 24/7 (documentary)** | The serif typography for fight commentary, the slow-pan documentary feel, the use of **quoted** pundit lines with attribution, the way each episode has a "previously on" cold open | The actual video content (we're a text sim) |
| **WMMA5** | The Fighter Profile's structure (headshot + bio + attributes + recent fights) — this is the genre-standard layout, players expect it | The flat text feed for play-by-play (we replace with the 4-zone Fight Night screen per GUI_PLAN §4) |
| **Crusader Kings 3** | The "every character has a portrait + traits + relationships" profile model — the way traits are visualized as small iconified chips, not numbers | The 3D character models |
| **OOTP Baseball** | The hall-of-fame "compare to current player" mode — we use this pattern for Legends screen | The baseball-specific jargon |

---

## 2. Revised Color System

### 2.1 Audit of current palette (vs VLM critiques)

The current `OfficeColors` in `theme.py:87-113` has the *right colors*
but uses them at the *wrong intensity*. Specifically:

| Current role | Current hex | VLM critique | Verdict |
|---|---|---|---|
| `bg_base` | `#0f1115` | "near-pure black, void" | Slightly too dark for Office — keep but add a layered surface system on top so it's no longer the dominant visual |
| `bg_surface` | `#1a1d23` | "sidebar barely distinguishable from main" | Wrong delta — only ~7% lighter than bg_base. Need a wider value step (§2.2) |
| `bg_surface_elevated` | `#232730` | "active sidebar item indistinguishable" | Used for hover/active but only ~5% lighter than bg_surface. Need a strong active state with a *gold-tinted* bg, not just a value step |
| `bg_border` | `#2e333d` | "no card system, no z-depth" | Borders are correct idea but at 1px on dark bg they're invisible. Use 1px borders ONLY on cards, and use a 4-step bg depth system for z-hierarchy |
| `crimson` | `#c8323a` | "barely visible" | Slightly desaturated. Bump to `#d63a3f` and reserve for *impact* moments (loss, KO, danger). For "active" UI use a *crimson-tinted* bg, not full crimson |
| `gold` | `#d4a55a` | "barely visible" | Correct hue, slightly muddied. Bump to `#e0a957` and use as the SOLE accent for clickable/hover/active states. Use a *gold-tinted* bg (`rgba(224,169,87,0.08)`) for hover, not full gold |
| `text_primary` | `#e8eaed` | OK | Keep |
| `text_secondary` | `#9aa0a6` | "washed out, low contrast" | Bump to `#aab0b8` (better WCAG contrast vs bg_surface) |
| `text_tertiary` | `#5f6368` | "illegible" | OK for disabled/timestamp only. For ALL metadata, use `text_secondary` instead |

The Fight Night palette is broadly correct but needs the same depth
system applied. And the heatmap colors (`heat_blue/orange/red`) should
be **reserved exclusively for the cage heatmap** — they currently bleed
into other UI in the form of generic status colors. We separate them.

### 2.2 Revised Office Mode palette

All hex codes are the new spec. Hex codes marked **[NEW]** are roles
that didn't exist before; **[CHANGED]** means a value was modified.

#### Backgrounds (4-tier depth system — THE key fix)

| Role | Hex | Use | Justification |
|---|---|---|---|
| `bg_base` | `#0a0c10` **[CHANGED]** | Main window background — only visible as 8px gutters between cards | A 4% darker charcoal than `#0f1115`. Reads as "arena floor at night" rather than "void." The wider gap from `bg_surface` (next) is what creates depth |
| `bg_surface` | `#15181f` **[CHANGED]** | Sidebar, top bar, bottom bar — the *shell* surfaces | 8% lighter than bg_base. The shell reads as a separate layer, not the same plane |
| `bg_card` | `#1c2028` **[NEW]** | Card backgrounds — every discrete panel inside the main content | 5% lighter than bg_surface. This is the *card layer* — the surface that holds content. Without it, cards don't read as cards |
| `bg_card_elevated` | `#252a33` **[NEW]** | Hover, active tab, dialog, dropdown | 5% lighter than bg_card. Used for interactive lift, not for resting surfaces |

**Why a 4-tier system, not the current 3-tier:** The current system
collapses "shell" and "card" into the same `bg_surface` value, which is
why the sidebar visually merges with the main content. Splitting them
creates the z-depth the VLM demanded.

#### Borders + separators

| Role | Hex | Use | Justification |
|---|---|---|---|
| `border_subtle` | `#2a2f38` | 1px borders between cards, divider lines | Slightly warmer than current `#2e333d`. Visible at 1px on `bg_card` without being shouty |
| `border_strong` | `#3a4049` **[NEW]** | 2px borders on accent cards (champion cards, selected rows) | Stronger visual edge for "this matters" cards |
| `divider_faint` | `#1f232b` **[NEW]** | Intra-card dividers (between sections of one card) | Barely visible — just enough to suggest structure |

#### Text

| Role | Hex | Use |
|---|---|---|
| `text_primary` | `#e8eaed` | Body, headings, fighter names in lists |
| `text_secondary` | `#aab0b8` **[CHANGED]** | Metadata, captions, table column headers, "WC · Promo · Gym" subtitle |
| `text_tertiary` | `#6b7280` **[CHANGED]** | Disabled, timestamps only. NEVER for content the player needs to read |
| `text_on_gold` | `#1a1410` **[NEW]** | Text rendered on a gold button background (very dark brown — reads as "ink on gold leaf") |
| `text_on_crimson` | `#ffffff` | Text rendered on a crimson background |

#### Accents (CO-PRIMARY, per GUI_PLAN §3.3)

| Role | Hex | Use | Justification |
|---|---|---|---|
| `crimson` | `#d63a3f` **[CHANGED]** | Loss indicators, KO/TKO result chips, danger buttons, rival heat indicators | Bumped 5% saturation. "Blood on canvas" — but reserved for impact moments only |
| `crimson_tint` | `rgba(214,58,63,0.10)` **[NEW]** | Hover bg on danger buttons, tinted bg for "rivalry" rows in tables | The tinted-bg pattern lets us use crimson without screaming |
| `gold` | `#e0a957` **[CHANGED]** | EMPIRE wordmark, champion indicators, primary action buttons, hyperlinks, "win" indicators | Slightly warmer + brighter than current `#d4a55a` — reads as "brass under tungsten light" rather than "mud" |
| `gold_tint` | `rgba(224,169,87,0.10)` **[NEW]** | Hover bg on cards/rows/links, active tab bg, "selected" row bg | The key fix for "active sidebar item is invisible." A 10% gold tint on `bg_card` is unmistakable |
| `gold_bright` | `#f5c878` **[NEW]** | Hover state for hyperlinks + buttons (replaces the inline `_HOVER_GOLD_BY_THEME` map in `hyperlink.py:67-74`) | Brighter shade of gold — gives the "pressing" feedback the VLM wanted |

#### Status colors

| Role | Hex | Use |
|---|---|---|
| `success` | `#4ade80` | Signed, recovered, win (sparingly — green is a "third accent" and should stay rare) |
| `warning` | `#fbbf24` | At-risk, injured, contract expiring (note: warning = gold-adjacent; use very sparingly to avoid clashing with the gold accent) |
| `danger` | `#ef4444` | Cut, suspended, critical. Used for the *action* of cutting, not for the *state* of being cut (state = crimson chip) |
| `info` | `#60a5fa` **[NEW]** | Informational badges, "new" indicators. Blue is allowed ONLY here — it's not a brand color |

#### Champion + title colors (Championship Mode skin)

| Role | Hex | Use |
|---|---|---|
| `champion_gold` | `#f0c060` | Belt graphic, champion portrait border, "TITLE FIGHT" badge bg |
| `champion_gold_leaf` | `#f5d77a` **[NEW]** | The gold-leaf accent border on the cage heatmap during a title fight — slightly warmer than `champion_gold` |
| `challenger_crimson` | `#d63a3f` | Challenger corner color, "challenger" badge bg |

### 2.3 Revised Fight Night Mode palette

Same 4-tier depth system, deeper values.

| Role | Hex | Use |
|---|---|---|
| `bg_base` | `#06070a` | The arena floor — only visible as gutters between zones |
| `bg_surface` | `#0d1015` | Zone backgrounds (heatmap frame, commentary feed frame, pundit panel frame) |
| `bg_card` | `#14181f` | Beat cards in the commentary feed, pundit avatar frames |
| `bg_card_elevated` | `#1c2028` | Active beat highlight (the beat currently being narrated) |
| `border_subtle` | `#252a33` | 1px frame around each zone |
| `border_strong` | `#3a4049` | Cage heatmap frame (stronger — the heatmap is the signature visual) |
| `text_primary` | `#f5f6f8` | Brighter — punches through the darkness |
| `text_secondary` | `#b4b8c0` | Beat timestamps, pundit names |
| `text_tertiary` | `#6b7280` | Disabled transport controls |
| `crimson` | `#e53e3e` | Brighter, more saturated — "blood in spotlight" |
| `gold` | `#f0c060` | Brighter — "title belt under stage lights" |
| `impact_yellow` | `#fbbf24` | Knockdowns, big moments, finish flashes |
| `heat_blue` / `heat_orange` / `heat_red` | `#3b82f6` / `#f97316` / `#dc2626` | **RESERVED for cage heatmap only** — never used elsewhere |

### 2.4 Texture system

Textures are subtle. The rule: a texture should be *felt*, not *seen*.
If the player notices the texture, it's too loud. All textures are PNG
tiles loaded once at app startup and cached.

| Texture | Where | Spec |
|---|---|---|
| `noise_grain.png` | Tiled across `bg_base` (Office + Fight Night) | 256×256 PNG, 3% opacity grey noise. Adds the "this is a real surface, not a flat fill" feel without being visible |
| `chain_link_dim.png` | Tiled across `bg_surface` on Fight Night only | 512×512 PNG, chain-link fence pattern at 4% opacity, slightly crimson-tinted. The "cage" metaphor made literal — but only on Fight Night, only on shell surfaces, never on cards |
| `gold_leaf_border.png` | 9-slice border on champion cards (Dashboard champion chips, Fighter Profile portrait when fighter is a champion, Titles screen belt cards) | 16×16 PNG corner tile, 1px gold-leaf textured border. Applied via CTk's `border_width=2` + `border_color` lookup |
| `paper_grain.png` | Background of memory bubble on Fight Night | 256×256 PNG, off-white paper grain at 8% opacity, slightly gold-tinted (the "old newspaper clipping" feel for a resurfaced memory) |
| `vignette_fight_night.png` | Single overlay PNG, 1920×1080, on Fight Night main content | Radial gradient from transparent center to 30% black at corners. Focuses the eye on the center action |

**Implementation note:** CTk doesn't have native texture-tile support.
The closest is `CTkFrame`'s `bg_color` (single color) — to tile a
texture, we need to (a) load the PNG via PIL, (b) create a `CTkImage`
tiled, (c) place a `CTkLabel` with that image as its background. This
is a one-time cost per screen (cached). Performance impact: <2ms per
textured frame, negligible.

### 2.5 Card / Depth system

**3 card variants.** This is the *complete* set — no more variants or
the system fragments.

| Variant | bg | border | corner_radius | shadow | When to use |
|---|---|---|---|---|---|
| **Card / Flat** | `bg_card` | `border_subtle` 1px | 6px | none | The default surface for content blocks — section panels, table wrappers, news items, watch cards |
| **Card / Elevated** | `bg_card_elevated` | `border_subtle` 1px | 6px | none | Hover state of Flat cards, modal dialogs, dropdown menus, "active" tab content |
| **Card / Accent** | `bg_card` | `border_strong` 2px (gold) | 6px | none | "This matters" cards — the Top Story on Dashboard, the currently-viewed fighter's profile header, champion chips on Titles screen, rivalry cards on Bad Blood screen |

**Shadow spec:** NONE. Real drop shadows require per-frame PIL
compositing, which adds ~15ms per shadow per refresh. With 30+ cards on
a Dashboard refresh, that's 450ms — over the entire 167ms lazy-refresh
budget. The depth illusion comes from the 4-tier bg system + 1px borders,
NOT from shadows.

**Corner radius:** 6px for all cards. 4px for chips, pills, badges. 0px
for tables (sharp edges on data tables — the "ledger" feel). 8px for
modal dialogs (slightly softer = slightly more important).

### 2.6 Decision: do we need a 3rd mode?

**Yes — but as a skin, not a mode.** See §1.2. Championship Skin is
a 4-color overlay on Fight Night, not a parallel design system. It
activates only when the Fight Resolution screen is showing a fight where
`fights.is_title_fight = 1`.

---

## 3. Revised Typography System

### 3.1 Audit of current font registration

The current `_register_fonts()` in `theme.py:290-386` does the right
things — registers TTFs via `tk.call("font", "create", ...)`, queries
`tk.fontFamilies()` to verify, falls back to platform defaults on
failure. But the VLM says fonts "look like system defaults." Likely
causes:

1. **The verification query at line 349 may be returning an empty set**
   on some Tk builds (the `tk.call("font", "families")` call can fail
   silently in try/except). When it does, ALL families fall back to
   platform defaults — but the failure is logged only via a `print()`
   to stderr.

2. **The Inter family is registered 4 times with the SAME family name
   but DIFFERENT weights** (Regular, Medium, SemiBold, Bold all
   registered as `"Inter"` with `"normal"` weight — line 325-328).
   Tk's font registry doesn't always resolve weight-by-name correctly
   when registered this way; it can collapse to the LAST registered
   weight, which means Inter Bold is being treated as Inter Regular.

3. **No display font is bundled.** `DISPLAY_FAMILY = "Oswald"` (line
   197) but Oswald is never registered (it's not in the `font_files`
   list at line 324-334) and `_font_families_available[DISPLAY_FAMILY]`
   is always False, so it falls back to Inter. The display font
   doesn't exist on the player's machine — it must be bundled.

**Fix:** (a) register each Inter weight under a UNIQUE family name
(`Inter-Regular`, `Inter-Medium`, etc.) so Tk can't collapse them, (b)
bundle Oswald (OFL license, free, ~120 KB), (c) add a startup health
check that logs the resolved family for each role so we can spot
registration failures in the wild.

### 3.2 Revised type system

| Role | Family | Size | Weight | Tracking | Line height | When to use |
|---|---|---|---|---|---|---|
| `display` | Oswald | 36px | 600 | +0.02em | 1.1 | Splash screen, "CAGE EMPIRE" wordmark in top bar, "ROUND 2" overlay on Fight Night |
| `display_small` | Oswald | 24px | 600 | +0.02em | 1.15 | Screen titles ("The Empire", "The Stable"), section group labels |
| `h1` | Inter | 22px | 700 | -0.01em | 1.2 | Page H1 (one per screen) |
| `h2` | Inter | 18px | 700 | -0.005em | 1.25 | Card/section titles within a screen |
| `h3` | Inter | 15px | 600 | 0 | 1.3 | Sub-section titles, tab labels |
| `body` | Inter | 14px | 400 | 0 | 1.5 | Default body text |
| `body_small` | Inter | 13px | 400 | 0 | 1.45 | Table rows, dense lists, sidebar items |
| `caption` | Inter | 11px | 500 | +0.04em (uppercase) | 1.3 | Metadata, timestamps, "WC · PROMO · GYM" subtitle, captions. ALWAYS UPPERCASE |
| `descriptor` | Inter Italic | 14px | 400 | 0 | 1.5 | Voice phrases from the interpretation layer ("a rising contender climbing the ranks"). Italic = "this is voice, not data" |
| `descriptor_small` | Inter Italic | 12px | 400 | 0 | 1.4 | Compact voice phrases in table cells (Roster, Free Agents) |
| `mono` | JetBrains Mono | 14px | 500 | 0 | 1.4 | Numbers, records, dates ("$50.0M", "18-5-0", "Mon 14 Sep 2026"). NEVER for prose |
| `mono_small` | JetBrains Mono | 11px | 500 | 0 | 1.3 | Beat timestamps ("R2 3:42"), small numeric badges |
| `commentary_office` | Inter | 14px | 400 | 0 | 1.6 | Fight commentary on Office Mode (News Feed recap, Past Events summary) — sans-serif, like a wire story |
| `commentary_fight` | Source Serif Pro | 17px | 400 | 0 | 1.6 | Fight commentary on Fight Night Mode — serif, like a documentary narration. THE key Fight Night font change |
| `pundit` | Source Serif Pro SemiBold Italic | 14px | 600 italic | 0 | 1.5 | Named pundit interjections ("That's the third body shot in 90 seconds") — italic serif, attributed |
| `beat_timestamp` | JetBrains Mono | 11px | 500 | +0.05em | 1.2 | "R2 3:42" — round + clock. Mono + tracked out for the "scoreboard" feel |

### 3.3 Type scale

**Modular scale ratio: 1.2 (minor third).** Smaller than the typical
1.25 because management-sim screens are dense; a 1.25 scale would push
body text to 16px which is too large for table rows.

| Step | Size | Used by |
|---|---|---|
| -3 | 9px | (reserved — not used) |
| -2 | 11px | `caption`, `mono_small`, `beat_timestamp` |
| -1 | 13px | `body_small`, `descriptor_small` |
| 0 | 14px | `body`, `descriptor`, `mono`, `commentary_office`, `pundit` |
| +1 | 17px | `commentary_fight` |
| +2 | 18px | `h2` |
| +3 | 22px | `h1` |
| +4 | 24px | `display_small` (slight manual bump from scale, +2px) |
| +5 | 36px | `display` (manual bump from scale, +6px for splash impact) |

### 3.4 Letter-spacing rules

- **ALL UPPERCASE labels** (captions, nav group headers like "FIGHTERS",
  "EVENTS", section eyebrows): **+0.04em to +0.05em**. This is the
  "stadium scoreboard" tracking — letters need room to breathe when
  they're all caps.
- **Display + display_small** (Oswald): **+0.02em**. Oswald is already
  condensed; a touch of extra tracking prevents the letters from
  feeling cramped.
- **All H1/H2/H3 headings** (Inter): **-0.005em to -0.01em**. Inter at
  headline sizes benefits from tight tracking — feels more "designed,"
  less "system font."
- **All body + descriptor + commentary**: **0em**. Default Inter
  tracking is fine.
- **All mono numerics**: **0em**. JetBrains Mono is already wide; extra
  tracking breaks number alignment in tables.
- **Beat timestamps** ("R2 3:42"): **+0.05em**. The scoreboard feel
  demands it.

### 3.5 Display font decision

**Recommendation: bundle Oswald (Google Fonts, OFL 1.1 license, free
for commercial use).** Specifically the Oswald Bold weight (~120 KB).

**Why Oswald over the alternatives:**

| Font | Pros | Cons | Verdict |
|---|---|---|---|
| **Oswald** (recommended) | Free, OFL, condensed sans-serif, stadium-scoreboard feel, single weight suffices, ~120 KB | Slightly overused (it's in a lot of sports blogs) | ✅ Bundle |
| Bebas Neue | Free, OFL, more dramatic stencil feel | ALL CAPS only — can't be used for sentence-case text, limits reuse | ❌ Too restrictive |
| Custom stencil font | Unique, on-brand | Costs $500-$2000 to commission, 4-8 week timeline | ❌ Out of scope for this redesign |
| Inter Bold + letter-spacing | Already bundled, no new asset | Doesn't achieve the "stadium scoreboard" feel — Inter at large sizes still reads as "system sans" | ❌ Fallback only |

**Install/licensing story:** Oswald is SIL Open Font License 1.1 — free
for commercial use, free to redistribute, free to bundle. Download
`Oswald-Bold.ttf` (~120 KB) from Google Fonts, drop into
`src/ui/assets/fonts/`, register in `theme.py:_register_fonts()` with
the family name `"Oswald"`. Done. No payment, no commission, no legal
review needed.

**Fallback chain if Oswald fails to register:** Inter Bold at -0.01em
tracking + 10% horizontal stretch via CTkImage transform. Visually
inferior but functional.

---

## 4. Revised Layout System

### 4.1 Audit of current shell

The current shell (`app.py:279-282`) is:

- **Top bar (60px):** logo + date + cash + Advance Day button, all in
  one cramped row.
- **Sidebar (220px):** 6 nav groups × 3-4 items each = 19 items, all
  text-only, no icons, no badges.
- **Main content (flexible):** one screen at a time, scrollable.
- **Bottom bar (32px):** news ticker + next-event countdown.

**VLM critique summary:** "80/20 split of death" (sidebar too wide),
"cramped sidebar" (items stacked too tight), "header chaos" (logo +
date + cash all crammed into 60px), "wasted header space" (top bar has
no global actions).

### 4.2 Revised shell

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOP BAR (56px)                                                       │
│ ┌──[mark]──┐  CAGE EMPIRE  ·  Mon 14 Sep 2026, Y1 W37  ·  $50.0M ↑  │
│ │  32x32   │                                              [▶ Advance] │
│ └──────────┘                                                          │
├────┬─────────────────────────────────────────────────────────────────┤
│ S  │                                                                 │
│ I  │              MAIN CONTENT (12-col grid, 24px gutters)           │
│ D  │                                                                 │
│ E  │                                                                 │
│ B  │                                                                 │
│ A  │                                                                 │
│ R  │                                                                 │
│    │                                                                 │
│ 56 │                                                                 │
│ px │                                                                 │
│ or │                                                                 │
│ 220│                                                                 │
│ px │                                                                 │
├────┴─────────────────────────────────────────────────────────────────┤
│ (no bottom bar — removed)                                            │
└──────────────────────────────────────────────────────────────────────┘
```

**Changes from current:**

1. **Top bar: 60px → 56px.** Smaller because we removed the news ticker
   (the news ticker moved to the News Feed screen where it belongs —
   it's content, not chrome). The 4px savings compounds across the
   screen height.

2. **Top bar layout: 3 zones, not 1.** Left = logo mark (32×32) + wordmark
   "CAGE EMPIRE" (Oswald). Center = sim date + week/year + cash (all in
   `mono`, with a tiny green/red delta arrow showing today's P&L).
   Right = global actions: a single "Advance" primary button (gold,
   88×40) + a kebab menu (⚙) for Save / Settings / Mods. The kebab
   removes 3 items from the sidebar.

3. **Sidebar: 220px text → 56px collapsed icon-only (default) + 220px
   expanded icon+label (on hover or pin).** This is the VS Code /
   Linear pattern. The player gets the horizontal real estate back by
   default; on hover the sidebar expands to reveal labels + sub-labels.
   A pin toggle (top of sidebar) keeps it expanded for players who
   prefer the always-labeled mode.

4. **Sidebar content: 19 items → 14 items.** Removed: Settings, Save/
   Load, Mods (moved to the top-bar kebab menu). Removed: Fighter
   Profile (already not in sidebar per the AD-3 decision in
   `app.py:91-99`). That leaves the 14 nav destinations the player
   actually navigates between during play.

5. **Bottom bar: removed.** The 32px news ticker was duplicating the
   News Feed screen's content. The next-event countdown moves to the
   Dashboard's "Next Event" card (where it belongs — it's content, not
   chrome). The 32px of vertical real estate is reclaimed for the main
   content area.

### 4.3 Grid system

**12-column grid, 24px gutters, 24px page padding.** This is the
Bloomberg / FM2024 standard. The 12-col grid is fine-grained enough for
complex dashboards but coarse enough that the player doesn't see "the
grid" — they see cards.

**Column spans (the standard set every screen uses):**

| Span | Width at 1280px content | Use |
|---|---|---|
| 12 (full) | 1232px | Hero cards (Dashboard Top Story), full-width tables (Roster) |
| 8 | 816px | Wide content cards (Fighter Profile header, Fight Night commentary feed) |
| 6 | 608px | Half-width cards (Dashboard Promotion Status, News Feed main column) |
| 4 | 400px | Standard card (Watch Cards, fighter attribute groups) |
| 3 | 296px | Narrow card (champion chips, stat tiles) |
| 2 | 192px | Sidebar-width card (next-event mini-card, finance sparkline) |

**Row height:** Auto. CTk's grid manager handles this natively. We
specify `minsize` only where a card needs a minimum (e.g., Fighter
Profile portrait column = 280px min height).

### 4.4 Spacing tokens

**8-point scale:** `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64` px.

| Token | Value | Use |
|---|---|---|
| `space_xs` | 4px | Tight inline padding (chip → label gap, icon → label gap) |
| `space_sm` | 8px | Inline padding inside chips, dense list row gaps |
| `space_md` | 12px | Card padding (compact), table cell vertical padding |
| `space_lg` | 16px | Card padding (default), section sub-group gap |
| `space_xl` | 24px | Grid gutter, page padding, gap between cards in a row |
| `space_2xl` | 32px | Gap between sections on a screen |
| `space_3xl` | 48px | Gap between major screen regions (header → content) |
| `space_4xl` | 64px | Top-of-screen hero padding |

**Implementation:** expose as constants in `theme.py` so every screen
references the same tokens. No screen is allowed to hardcode `pad=13`
or `pad=22` — it must be a token or a multiple of 4.

### 4.5 Sidebar decision: icon+text vs icon-only vs text-only

**Recommendation: icon+label, with collapse-to-icon-only on hover-out.**

| Mode | Width | When | Labels |
|---|---|---|---|
| Expanded (default) | 220px | Always (unless player pins collapsed) | Icon + label + count badge |
| Collapsed | 56px | On hover-out OR if player clicks the pin toggle | Icon only + tooltip on hover (250ms delay) |
| Pinned expanded | 220px | Player clicks the pin at the top of the sidebar | Always expanded, even on hover-out |

**Per nav group, the icon+label decision:**

| Group | Items | Icon style | Recommendation |
|---|---|---|---|
| HOME | The Empire, Calendar, The Wire | Filled, 20×20, gold-tinted | Icon + label |
| FIGHTERS | The Stable, Open Market, Scouting, Legends | Outlined, 20×20, neutral | Icon + label |
| EVENTS | Build a Card, Matchmaking, Fight Night, The Archive | Outlined, 20×20, neutral | Icon + label |
| BUSINESS | The Books, Deals, The Competition, Training Camps | Outlined, 20×20, neutral | Icon + label |
| WORLD | The Rankings, Belts, Bad Blood, The Record Book | Outlined, 20×20, neutral | Icon + label |

**Fight Night special case:** when the player is on the Fight
Resolution screen, the sidebar dims to 40% opacity (per GUI_PLAN §3.5)
and the "Fight Night" item in EVENTS group glows crimson with a small
"FIGHT" badge. This is the only "active state" that uses crimson instead
of gold — it's the violence moment.

### 4.6 Responsive behavior

| Window size | What collapses first |
|---|---|
| 1920×1080+ (default) | Everything expanded. 12-col grid at full width |
| 1440×900 (typical laptop) | Everything expanded. 12-col grid at full width (1232px content) |
| 1280×720 (min supported) | Sidebar auto-collapses to 56px icon-only. Grid reduces to 8-col with 16px gutters. Card spans halve (12→6, 6→4, etc.) |
| Below 1280×720 | NOT SUPPORTED. The app shows a "Please resize your window" placeholder. Don't try to be responsive below this — the data density requires it |

**Window chrome:** the app should run **borderless** (custom title bar
integrated into the top bar — the "CAGE EMPIRE" wordmark area becomes
the draggable region). The OS minimize/maximize/close buttons are
replaced with custom-styled equivalents in the top-right corner of the
top bar. This removes the "amateurish Windows title bar" the VLM
flagged.

**CTk feasibility:** borderless mode is supported via
`overrideredirect(True)` on the CTk root. Window dragging is handled by
binding `<Button-1>` + `<B1-Motion>` on the top-bar frame. Custom
minimize/maximize/close buttons are CTkButtons with OS API calls
(`self.iconify()`, `self.state("zoomed")`, `self.destroy()`). This is a
P1 polish item — ship the redesign with the OS title bar first, then
add borderless in the polish phase.

---

## 5. Component Library

15 reusable components. Every screen is built from these. No screen
is allowed to roll its own bespoke widget — if a screen needs something
new, it goes through the component library first.

Components are listed in dependency order (later components depend on
earlier ones).

### 5.1 Card

**Purpose:** The base surface for every content block. 3 variants.

**Visual spec:**

| Variant | bg | border | radius | padding | Min size |
|---|---|---|---|---|---|
| Flat | `bg_card` | `border_subtle` 1px | 6px | 16px | 200×100 |
| Elevated | `bg_card_elevated` | `border_subtle` 1px | 6px | 16px | 200×100 |
| Accent | `bg_card` | `border_strong` 2px (gold) | 6px | 16px | 200×100 |

**States:** Flat (resting) → Elevated (hover, 100ms transition) → Accent
(when "selected" or "marked important" by parent screen).

**Voice/type:** Card title uses `h2` (Inter 18px Bold). Card body uses
`body` (Inter 14px). Card caption uses `caption` (Inter 11px uppercase
+0.04em).

**When to use:** Default for ALL content blocks. The screen is a grid
of Cards. The ONLY things on a screen that aren't Cards are: the
screen H1, the filter row, the table (which is a Card variant with
sharp corners), and the action bar.

**When NOT to use:** For modal dialogs (use ModalDialog, §5.16), for
table rows (use FighterRow, §5.5), for chips (use DataChip, §5.4).

### 5.2 SectionHeader

**Purpose:** A section title with a gold left-accent bar. Refines the
"gold left-accent bar from P2-2" mentioned in the task brief.

**Visual spec:**

```
█▌ THE EMPIRE — Top Story                              Mon 14 Sep ▶
```

- Left accent bar: 3px wide × 20px tall, gold (`gold`), vertically centered with the title text
- Title: `display_small` (Oswald 24px, +0.02em tracking), `text_primary`
- Right metadata: `caption` (Inter 11px uppercase), `text_secondary`
- Container: transparent bg, no border, 0px corner radius, 8px bottom margin

**States:** None. Static component.

**Voice/type:** The title is ALWAYS uppercase. The right metadata is
ALWAYS uppercase + tracked.

**When to use:** Top of every major section within a screen. A typical
screen has 3-6 SectionHeaders. The accent bar is the visual anchor
that tells the player "this is a new section."

### 5.3 DataChip

**Purpose:** Small status pill for "champion", "injured", "on streak",
etc. Replaces the inline text badges currently scattered across screens.

**Visual spec:**

| Variant | bg | text | border | radius | padding | Icon |
|---|---|---|---|---|---|---|
| Default | `bg_card_elevated` | `text_secondary` | none | 4px | 4px×8px | optional 12×12 |
| Champion | `gold_tint` | `gold` | `gold` 1px | 4px | 4px×8px | mandatory belt icon |
| Danger | `crimson_tint` | `crimson` | `crimson` 1px | 4px | 4px×8px | mandatory warning icon |
| Info | `rgba(96,165,250,0.10)` | `info` | `info` 1px | 4px | 4px×8px | optional |

**Text:** `caption` (Inter 11px uppercase +0.04em). ALWAYS UPPERCASE.

**States:** Default → hover (Elevated bg, 100ms) → pressed (slightly darker).

**When to use:** Inline with fighter names (champion chip), in tables
(injured chip), on Dashboard watch cards (streak chip), on news cards
(topic chip).

**When NOT to use:** For primary actions (use Button, §5.10). For
section labels (use SectionHeader, §5.2).

### 5.4 StatBar

**Purpose:** Horizontal bar for attribute visualization. Voice-encoded,
NOT raw numbers. Per CONVENTIONS §14, the bar shows the *voice tier*
(7 tiers: abysmal → elite), not the 0-100 value.

**Visual spec:**

```
Striking Power      ████████████████░░░░░░  carries real knockout power
```

- Label (left, 140px): `body_small` (Inter 13px), `text_secondary`
- Bar (center, fills available): 8px tall, `bg_card_elevated` track, fill = `gold` (default) or `crimson` (if tier is abysmal/poor) or `info` (if tier is elite/exceptional — use sparingly to avoid green-vs-blue confusion)
- Bar fill width: tier-based (abysmal=8%, poor=22%, below_avg=36%, avg=50%, above_avg=64%, good=78%, elite=92%, exceptional=100%)
- Voice phrase (right, 200px): `descriptor_small` (Inter 12px italic), `text_primary`

**States:** Hover → show tooltip with the FULL long-form descriptor (the
`describe_attribute` "long" variant from the audit doc §3). This is
where the proposed short/long variant system pays off — short variant
on the bar, long variant in the tooltip.

**Voice/type:** Bar label is sentence case. Voice phrase is sentence
case italic. Tooltip is sentence case.

**When to use:** Fighter Profile attribute grid (26 bars). Also on
Scouting Reports (with a "scouted vs reported" dual-bar variant — out
of scope for this redesign, P1 future).

**When NOT to use:** For numeric values (cash, record, ranking position)
— use plain `mono` text. StatBar is for ATTRIBUTE TIERS, not numbers.

### 5.5 FighterRow

**Purpose:** One row in a FighterTable. Refines the current row widget
in `fighter_table.py`.

**Visual spec:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ● John Vale              28  LW  Rising Contender │ Steady   18-5-0   ▶│
└─────────────────────────────────────────────────────────────────────────┘
```

- Height: 36px (current 28px is too cramped — VLM called out "cramped sidebar")
- Row bg: alternating `bg_card` / `bg_card_elevated`
- Hover bg: `gold_tint` (replaces the current steel-tinted hover)
- Selected bg: `gold_tint` + 2px gold left border
- Active fighter indicator (left, 6px): dot or chevron — gold if champion, crimson if on losing streak, neutral otherwise
- Cell padding: 8px vertical × 12px horizontal
- Cell fonts: Name = `body_small` Bold (gold if hyperlink), Age/WC = `mono_small`, Stage/Form = `descriptor_small` italic, Record = `mono_small`

**States:**

- Default: alternating bg
- Hover: `gold_tint` bg, cursor = hand2
- Selected: `gold_tint` + gold left border, cursor = hand2
- Champion variant: gold dot + bolded name + "CHAMP" chip in WC column
- Injured variant: crimson dot + "(INJ)" chip appended to name
- On streak variant: small flame icon (P1) or chip "W3" / "L2"

**When to use:** Roster, Free Agents, Matchmaking (fighter picker), Past
Events (fight card list), Training Camps (roster view). Anywhere a
list of fighters is shown.

### 5.6 NewsCard

**Purpose:** One news item with topic badge + headline + date. Replaces
the current Dashboard news list's plain text rows.

**Visual spec:**

```
┌─ Card / Flat ─────────────────────────────────────────────┐
│ [SIGNING]                                       2h ago     │
│                                                            │
│ John Vale signs with Pacific Rim Championship             │
│                                                            │
│ The 28-year-old lightweight leaves the open market after  │
│ a six-week bidding war. Pacific Rim reportedly won with a  │
│ three-fight deal worth $1.2M guaranteed.                  │
└───────────────────────────────────────────────────────────┘
```

- Card variant: Flat, full-width (12-col)
- Topic badge (top-left): DataChip with the news topic ("SIGNING", "INJURY", "RESULT", "RIVALRY", "RUMOR")
- Timestamp (top-right): `caption`, `text_tertiary`, relative ("2h ago", "yesterday", "3d ago")
- Headline (below topic): `h3` (Inter 15px Bold), `text_primary`, hyperlinked if it references a fighter
- Body (below headline): `body` (Inter 14px), `text_secondary`, 2-line max with ellipsis
- Right-side chevron (▶) if the card has a detail view

**States:** Hover → Elevated bg + show chevron.

**Voice/type:** Headlines use the headline_engine's voice phrases
(short variant). Body uses the body_text (long variant, when available
per the audit doc's proposed system).

**When to use:** Dashboard Recent News section, News Feed screen,
Fighter Profile "In the News" section (future), Past Events recap.

### 5.7 WatchCard

**Purpose:** One of the 3 Fighter Watch cards on Dashboard (Top Prospect
/ Hottest Streak / Biggest Fall).

**Visual spec:**

```
┌─ Card / Accent (gold border for Top Prospect, crimson for Biggest Fall) ─┐
│ TOP PROSPECT                                                 ▲ +12    │
│                                                                          │
│ ┌──────┐                                                                 │
│ │ 64px │   John Vale                                                     │
│ │ port │   18-5-0 · LW · 28yo                                            │
│ └──────┘                                                                 │
│                                                                          │
│ "the wunderkind everyone's talking about"                                │
│                                                                          │
│ Signed 6 weeks ago. Three wins in a row. Promoters are circling.         │
└──────────────────────────────────────────────────────────────────────────┘
```

- Card variant: Accent (gold border for Top Prospect + Hottest Streak, crimson border for Biggest Fall)
- Section eyebrow (top-left): `caption` (Inter 11px uppercase), `gold` or `crimson`
- Delta indicator (top-right): `mono_small`, green ▲ or red ▼ (the trend)
- Portrait (left, 64×64): PortraitFrame mini variant
- Name (right of portrait): `h3` (Inter 15px Bold), gold hyperlink
- Stats line: `body_small` (Inter 13px), `text_secondary`, mono for record
- Voice phrase (centered, italicized): `descriptor` (Inter 14px italic), `text_primary`
- Context line (bottom): `body_small` (Inter 13px), `text_secondary`

**States:** Hover → Elevated bg (the accent border stays). Click →
navigates to Fighter Profile.

**Voice/type:** The voice phrase is the LONG variant from the proposed
short/long system (audit doc §3). The context line is a 1-sentence
summary generated from `daily_headlines.body_text` (truncated to ~80
chars).

**When to use:** Dashboard Fighter Watch section. Only 3 instances at a
time. The visual weight is intentional — these are the 3 stories the
player should care about today.

### 5.8 PortraitFrame

**Purpose:** 256px portrait with gold/crimson border. Refines the
current `fighter_profile.py` portrait.

**Visual spec:**

| Variant | Size | Border | Border width | Corner | When |
|---|---|---|---|---|---|
| Hero (profile) | 256×320 | `gold` (champion) or `border_subtle` (default) | 3px | 8px | Fighter Profile header |
| Watch (card) | 64×80 | `gold` (champion) or none | 2px | 6px | Dashboard WatchCard |
| Row (table) | 28×36 | none | 0 | 4px | Future: in-table portrait (P1) |
| Mini (chip) | 20×25 | none | 0 | 4px | Future: avatar in comments (P2) |

**Champion variant:** Gold border + subtle gold-leaf texture overlay
(9-slice `gold_leaf_border.png` from §2.4) on the border.

**Scouted variant (Free Agents):** border is dashed `border_subtle`
(indicates "incomplete info"). Once scouted, becomes solid.

**States:** Hover → 100ms gold-tint overlay (subtle). Click → navigates
to Fighter Profile.

**Voice/type:** None — this is purely visual.

**When to use:** Fighter Profile (Hero), Dashboard WatchCard (Watch),
eventually Roster (Row, P1 future).

### 5.9 HyperlinkLabel

**Purpose:** Refines the gold-text clickable label.

**Visual spec:**

- Default text color: `gold` (`#e0a957`)
- Hover text color: `gold_bright` (`#f5c878`)
- Underline: 1px, `gold_tint` (40% opacity), appears on hover only
- Cursor: `hand2` on hover
- Font: inherits parent context (usually `body_small` Bold for fighter names)

**States:** Default → hover (color + underline, 100ms) → pressed (color
briefly drops to `gold` with -10% lightness for "press" feedback) →
visited (kept at default `gold` — no visited state, to avoid clutter).

**Voice/type:** Whatever the parent context dictates. Usually a fighter
name (sentence case) or a section title (uppercase).

**When to use:** Fighter names everywhere. Card titles that link to
detail views. "View all" links at the bottom of card sections.

**When NOT to use:** For buttons (use Button, §5.10). For tabs (use
TabBar, §5.11).

### 5.10 Button

**Purpose:** 4 variants.

**Visual spec:**

| Variant | bg | text | border | radius | padding | Icon |
|---|---|---|---|---|---|---|
| Primary (gold) | `gold` | `text_on_gold` | none | 4px | 10px×20px | optional 16×16 |
| Secondary (outline) | transparent | `text_primary` | `border_subtle` 1px | 4px | 10px×20px | optional 16×16 |
| Danger (crimson) | `crimson` | `text_on_crimson` | none | 4px | 10px×20px | optional 16×16 |
| Ghost | transparent | `text_secondary` | none | 4px | 8px×12px | optional 16×16 |

**States:**

- Default (resting)
- Hover: Primary → `gold_bright`; Secondary → `bg_card_elevated`; Danger → slightly brighter crimson; Ghost → `text_primary`
- Pressed: scale 98% (CTk doesn't support CSS transform; closest is a 100ms darker bg flash)
- Disabled: 40% opacity on text + bg, cursor = arrow
- Loading (future, P1): spinner replaces text, button becomes non-interactive

**Font:** `body_small` Bold (Inter 13px). For primary action buttons on
Fight Night (Exit Fight, Skip to Finish), use `display_small` (Oswald
24px) — bigger = more important.

**When to use:**

- Primary: the single most important action on a screen ("Sign Fighter", "Advance Day", "Exit Fight")
- Secondary: alternative actions ("View Profile", "Compare", "Filter")
- Danger: destructive actions ("Cut Fighter", "Cancel Event")
- Ghost: tertiary actions ("Cancel" in a modal, "Dismiss" on a card)

**Rule:** A screen should have AT MOST ONE Primary button visible at a
time. Multiple primaries compete for attention and dilute the call to
action.

### 5.11 TabBar

**Purpose:** Sub-navigation within a screen (e.g., Fighter Profile:
Overview / Attributes / Personality / Career / Fights / News).

**Visual spec:**

- Container: transparent bg, 1px `border_subtle` bottom border
- Tab (resting): `body_small` (Inter 13px), `text_secondary`, padding 8px×16px
- Tab (hover): `text_primary`, `gold_tint` bg (subtle)
- Tab (active): `text_primary` Bold, 3px gold bottom border (replaces the 1px container border for the active tab)
- Tab (disabled): `text_tertiary`, cursor = arrow

**States:** As above. Tabs do NOT have a "selected bg" — the gold
bottom border is the indicator.

**When to use:** Fighter Profile (6 tabs), Finance (3 tabs: Income /
Expenses / Forecast), Past Events (2 tabs: List / Calendar), Settings
(4 tabs: Display / Audio / Gameplay / Mods).

### 5.12 CalendarStrip

**Purpose:** Horizontal scrollable strip of dates for the Schedule screen.

**Visual spec:**

```
┌────────────────────────────────────────────────────────────────────┐
│ ◀  Mon 14    Tue 15    Wed 16   ●Thu 17   Fri 18   ...          ▶ │
│     Sep      Sep      Sep      Sep       Sep                      │
│                                          ▲ NEXT EVENT             │
└────────────────────────────────────────────────────────────────────┘
```

- Container: Card / Flat, 12-col, 64px tall
- Date cell (resting): 60×48, transparent bg, day-of-week `caption` (uppercase), date `mono` 14px
- Date cell (today): `gold_tint` bg, gold left border 2px
- Date cell (selected): `bg_card_elevated`, gold left border 3px
- Date cell (has event): small gold dot (6×6) below the date number
- Date cell (next event): gold ▲ marker + "NEXT EVENT" caption
- Left/right scroll arrows: ghost buttons at the edges

**States:** Hover → `gold_tint` bg. Click → selected state + shows
events for that date below.

**When to use:** Schedule screen (primary), Past Events calendar tab,
Event Builder date picker (modal variant).

### 5.13 Breadcrumb

**Purpose:** "Home > Fighters > John Vale" navigation trail.

**Visual spec:**

```
The Stable  /  John Vale
```

- Container: transparent bg, 24px tall, sits below the top bar
- Segment (resting): `body_small` (Inter 13px), `text_secondary`
- Segment (hover): `text_primary`, gold underline (1px)
- Separator: ` / ` in `text_tertiary`
- Last segment (current page): `text_primary` Bold, no hover (not clickable)

**When to use:** Fighter Profile (above the H1), Scouting Report detail,
Past Events event detail, Hall of Fame inductee detail. Anywhere the
player has drilled 2+ levels deep.

**When NOT to use:** On top-level nav destinations (Dashboard, Roster,
Free Agents, etc.) — the sidebar already indicates location.

### 5.14 EmptyState

**Purpose:** When no data, show personality, not "No data."

**Visual spec:**

```
┌─ Card / Flat ────────────────────────────────────────┐
│                                                       │
│                   [48×48 icon, gold]                  │
│                                                       │
│              The newswire is quiet.                   │
│                                                       │
│       No stories have broken in the last 24 hours.    │
│       Advance a day to see what develops.             │
│                                                       │
│                  [▶ Advance Day]                      │
│                                                       │
└───────────────────────────────────────────────────────┘
```

- Container: Card / Flat, centered, max 600×400
- Icon (top-center): 48×48, gold, custom per empty-state type (P0 = generic news icon, P1 = per-screen custom icons)
- Headline (center): `h2` (Inter 18px Bold), `text_primary`
- Body (center, max 400px wide): `body` (Inter 14px), `text_secondary`
- CTA (center, optional): Primary Button

**Voice/type:** Each empty state gets a UNIQUE voice phrase per screen.
The "No data" pattern is banned. Examples:

| Screen | Empty-state headline | Empty-state body |
|---|---|---|
| Dashboard news | "The newswire is quiet." | "No stories have broken in the last 24 hours. Advance a day to see what develops." |
| Roster | "Your stable is empty." | "Sign fighters from the Open Market to fill out your roster." |
| Free Agents | "The market is quiet." | "No unsigned fighters match your filters. Try widening your search." |
| Fighter Watch | "No one's making moves today." | "The divisions are resting. Check back after the next event." |
| Past Events | "No events in the archive yet." | "Once you run your first card, it'll show up here." |
| Hall of Fame | "No legends yet." | "Retirees with distinguished careers will be inducted here." |
| Rivalries | "No bad blood brewing." | "Rivalries develop over time as fighters meet repeatedly." |

**When to use:** Every screen that can be empty MUST have an empty
state. No blank voids.

### 5.15 LoadingState

**Purpose:** Skeleton screens for async loads (Fight Night pre-fight
build-up, save/load, mod install).

**Visual spec:**

- Card / Flat with the SAME structure as the loaded content, but with:
  - All text replaced with `bg_card_elevated` rectangles at the right height
  - A subtle pulse animation (opacity 50% → 100% → 50%, 1.2s loop, sine wave)
  - No icons, no buttons
- A small branded spinner in the corner: gold square (16×16) rotating
  45° every 600ms (CTk can do this via `.after()` callbacks)

**When to use:** Fight Night pre-fight build-up (while memory queue
loads), Save/Load file IO, any screen refresh that takes >300ms. The
skeleton prevents the "blank void" flash that the VLM flagged.

**When NOT to use:** For normal screen refreshes (<300ms). Skeletons
on fast loads cause a flash that's worse than no skeleton. Threshold:
show skeleton only if load >300ms.

### 5.16 ModalDialog

**Purpose:** Confirmations, sign/cut actions, settings changes.

**Visual spec:**

```
┌─ Modal overlay (semi-transparent black, 40% opacity) ───────────────┐
│                                                                       │
│        ┌─ Card / Elevated (8px radius) ──────────────────┐           │
│        │                                                  │           │
│        │  SIGN FIGHTER                                    │           │
│        │                                                  │           │
│        │  You're about to sign John Vale to a 3-fight     │           │
│        │  deal worth $1.2M guaranteed. This will deduct   │           │
│        │  $1.2M from your promotion's cash balance.       │           │
│        │                                                  │           │
│        │  ┌─────────────────┐  ┌─────────────────┐        │           │
│        │  │ Cancel          │  │ Sign for $1.2M  │        │           │
│        │  └─────────────────┘  └─────────────────┘        │           │
│        │                                                  │           │
│        └──────────────────────────────────────────────────┘           │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

- Overlay: `bg_base` at 40% opacity, covers entire window, blocks all interaction underneath
- Modal: Card / Elevated, 8px radius, max 600×400, centered, 24px padding
- Title (top): `display_small` (Oswald 24px), `text_primary`
- Body: `body` (Inter 14px), `text_secondary`
- Action buttons (bottom-right): Secondary (Cancel) + Primary (action verb) — gap of 12px
- Close X (top-right): Ghost button, 16×16, only on non-critical modals (critical = no X, force a choice)

**States:** Modal slides in from top (translateY -20px → 0, 150ms). Overlay
fades in (0% → 40%, 100ms). On close, reverse.

**When to use:** Sign Fighter (with contract details), Cut Fighter
(with confirmation), Cancel Event (with downstream impact list),
Advance Day confirmation (only if there's an unresolved event that
day), Settings changes that require restart.

**When NOT to use:** For inline confirmations (use a toast notification
instead — P1 future). For long forms (use a dedicated screen).

---

## 6. Ground-Up Redesign of the 4 Existing Screens

For each screen: wireframe (ASCII), section-by-section spec, density
target, dopamine hooks, interpretation-layer integration.

### 6.1 Dashboard ("The Empire")

#### Wireframe (1920×1080)

```
┌─ TOP BAR (56px) ──────────────────────────────────────────────────────────────────┐
│ [mark] CAGE EMPIRE  ·  Mon 14 Sep 2026, Y1 W37  ·  $50.0M ↑ +$2.1M  [▶ Advance] │
├───┬───────────────────────────────────────────────────────────────────────────────┤
│   │ Breadcrumb: The Empire                                                        │
│   │                                                                                │
│ S │ █▌ THE EMPIRE — Today's Stories                              Mon 14 Sep 2026  │
│ I │ ┌─ Card / Accent (gold border) ─── 12-col ─────────────────────────────────┐  │
│ D │ │ TOP STORY                                                                │  │
│ E │ │ "The prodigy turns heads again"                                          │  │
│ B │ │ John Vale keeps proving the hype is real. The division's brightest       │  │
│ A │ │ young talent continues to surge.                                         │  │
│ R │ │ [PRODIGY] [LW]                                  [Read full story ▶]      │  │
│   │ └──────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                │
│   │ ┌─ Card / Flat (6-col) ────────────┐  ┌─ Card / Flat (6-col) ────────────┐  │
│   │ │ █▌ PROMOTION STATUS              │  │ █▌ NEXT EVENT                    │  │
│   │ │                                  │  │                                  │  │
│   │ │ Cash       $50.0M ▂▃▅▆▇█        │  │ Sat 19 Sep 2026                  │  │
│   │ │ Reputation Highly Respected      │  │ Pacific Rim Championship #237   │  │
│   │ │ Fan Trust  Strong                │  │                                  │  │
│   │ │ Roster     1,002 fighters        │  │ Main Event:                     │  │
│   │ │ Champions  3 of 8 belts          │  │ John Vale vs Marcus Stone       │  │
│   │ │                                  │  │ LW Title Fight                  │  │
│   │ │ [View The Books ▶]               │  │                                  │  │
│   │ └──────────────────────────────────┘  │ [Build Card ▶] [Matchmaking ▶]  │  │
│   │                                        └──────────────────────────────────┘  │
│   │                                                                                │
│   │ █▌ FIGHTER WATCH                                                              │
│   │ ┌─ WatchCard (4-col, Accent gold) ─┐ ┌─ WatchCard (4-col, Accent gold) ┐ ...│
│   │ │ TOP PROSPECT              ▲ +12  │ │ HOTTEST STREAK              ▲ +5  │  │
│   │ │ [64px] John Vale                  │ │ [64px] Vega Reyes                │  │
│   │ │ 18-5-0 · LW · 28yo                │ │ 22-3-0 · BW · 31yo              │  │
│   │ │ "the wunderkind everyone's        │ │ "scorching the earth on the     │  │
│   │ │  talking about"                   │ │  way to a title shot"           │  │
│   │ │ Signed 6 weeks ago. Three wins.   │ │ 5-fight win streak.             │  │
│   │ └──────────────────────────────────┘ └──────────────────────────────────┘  │
│   │                                                                                │
│   │ █▌ CHAMPIONS                                                                   │
│   │ [CHAMP● HW] Andrei Volkov  · [CHAMP● LHW] Maria Santos  · [CHAMP● LW] ...    │
│   │                                                                                │
│   │ █▌ RECENT NEWS                                                                 │
│   │ ┌─ NewsCard (12-col) ─────────────────────────────────────────────────────┐  │
│   │ │ [SIGNING]                                          2h ago              │  │
│   │ │ John Vale signs with Pacific Rim Championship                            │  │
│   │ │ The 28-year-old lightweight leaves the open market after a six-week     │  │
│   │ │ bidding war. Pacific Rim reportedly won with a three-fight deal...      │  │
│   │ └────────────────────────────────────────────────────────────────────────┘  │
│   │ ┌─ NewsCard ────────────────────────────────────────────────────────────┐  │
│   │ │ [RESULT]                                          yesterday            │  │
│   │ │ ...                                                                      │  │
│   │ └────────────────────────────────────────────────────────────────────────┘  │
└───┴────────────────────────────────────────────────────────────────────────────────┘
```

#### Section-by-section spec

1. **Top Story** — Card/Accent (gold border, 12-col). Eyebrow "TOP
   STORY" (caption, gold). Headline (h2). Body (body, 2-line max).
   Topic chips + weight class chip at bottom-left. "Read full story"
   hyperlink at bottom-right. Source: `daily_headlines` row with
   `headline_type='top_story'`. Uses LONG voice variant.

2. **Promotion Status** — Card/Flat (6-col). 5 rows of label + value.
   Cash row has a 7-day sparkline (P0 — use a Canvas widget with 7
   bars). Reputation + Fan Trust show voice bands (per current D2 shim
   in `dashboard.py:99-110`). Roster + Champions counts. "View The
   Books" hyperlink.

3. **Next Event** — Card/Flat (6-col). Event date + name + main event
   fight + title fight indicator. Two buttons: "Build Card" (Primary)
   + "Matchmaking" (Secondary). If no event scheduled, shows
   EmptyState: "No events booked. Time to build a card."

4. **Fighter Watch** — 3 WatchCards in a row (4-col each). Top Prospect
   (gold accent), Hottest Streak (gold accent), Biggest Fall (crimson
   accent). Source: `daily_headlines` rows for fastest_rising +
   biggest_fall + a custom query for hottest streak (per current D3
   in `dashboard.py:111-119`).

5. **Champions** — horizontal strip of champion chips. Each chip =
   DataChip(champion variant) + HyperlinkLabel(name). 8 max (one per
   weight class). Sorted by weight class display_order (per current D9).

6. **Recent News** — vertical list of NewsCards (12-col each). Shows
   last 5 news items. "View all" hyperlink at the bottom navigates to
   News Feed. Source: `news_items` ordered by `published_at DESC`.

#### Information density target

At 1920×1080 with 24px gutters: **6 visible sections above the fold**
(Top Story + Promotion Status + Next Event + Fighter Watch + Champions
+ 1-2 NewsCards). The player sees the whole game state without
scrolling. Scrolling reveals more NewsCards.

#### Dopamine hooks (why the player clicks Advance Day)

1. **Top Story headline changes daily.** The LONG voice variant means
   the same fighter can be top story 3 days in a row with different
   headlines. This is the #1 anticipation driver per the Soul doc.
2. **Fighter Watch cards update with new fighters.** The Top Prospect
   today might be the Hottest Streak tomorrow — the player wants to
   see who's rising.
3. **Cash sparkline grows.** A 7-day upward trend is deeply satisfying
   (Empire Builder fantasy).
4. **Champions strip updates on title changes.** A new champion =
   visible gold chip appears.
5. **Next Event countdown.** The date is in the future, the player
   wants to reach it.

#### Interpretation-layer integration

- Top Story: LONG headline variant (proposed by audit doc §3)
- WatchCard voice phrase: LONG variant (audit doc §3)
- Promotion Status reputation/trust: voice bands (current D2 shim)
- NewsCard body: body_text from headline_engine (audit doc §3.6)
- Champions: just names (no interpretation needed)

### 6.2 Roster ("The Stable")

#### Wireframe

```
┌─ TOP BAR ──────────────────────────────────────────────────────────────────────────┐
├───┬─────────────────────────────────────────────────────────────────────────────────┤
│   │ Breadcrumb: The Stable                                                          │
│   │                                                                                  │
│ S │ █▌ THE STABLE                                                  1,002 fighters    │
│ I │                                                                                  │
│ D │ ┌─ Filter row (12-col) ──────────────────────────────────────────────────────┐  │
│ E │ │ WC: [All ▼]  Gender: [All ▼]  Stage: [All ▼]  [🔍 Search by name...]  [×]│  │
│ B │ └──────────────────────────────────────────────────────────────────────────┘  │
│ A │                                                                                  │
│ R │ ┌─ Card / Flat (12-col, sharp corners, 0px radius — table wrapper) ────────┐  │
│   │ │ Name              Age  WC  Stage                    Form       Record  ▶│  │
│   │ │ ────────────────────────────────────────────────────────────────────────│  │
│   │ │ ● John Vale        28  LW  Rising Contender          Steady     18-5-0  │  │
│   │ │   Maria Santos     31  BW  Veteran                   Sliding    22-8-0  │  │
│   │ │ ● Andrei Volkov    34  HW  Champion                  Dominant   28-2-0  │  │
│   │ │   ...                                                                     │  │
│   │ │                                                                           │  │
│   │ │ Showing 1-20 of 1,002                       [◀ Prev]  1 2 3 ... 51 [▶] │  │
│   │ └───────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                  │
│   │ ┌─ Card / Flat (12-col — weight class distribution viz) ───────────────────┐  │
│   │ │ █▌ WEIGHT CLASS DISTRIBUTION                                              │  │
│   │ │ HW ████████ 126          LHW ██████ 98          MW ████████ 122          │  │
│   │ │ WW ████████████ 165       LW █████████████ 184    FW ███████ 110         │  │
│   │ │ BW ██████ 92              FL █████ 85            SWStaw ███ 52           │  │
│   │ └───────────────────────────────────────────────────────────────────────────┘  │
└───┴──────────────────────────────────────────────────────────────────────────────┘
```

#### Column spec

| Column | Width | Anchor | Voice phrase per cell | Notes |
|---|---|---|---|---|
| Active dot | 24px | center | n/a | Gold if champion, crimson if on loss streak, neutral otherwise |
| Name | 220px | w | (fighter name, hyperlinked) | Bold, gold. Hover = gold_bright |
| Age | 50px | center | (mono numeric) | |
| WC | 60px | center | (weight class code) | Mono, uppercase |
| Stage | 200px | w | SHORT career_phase variant | Italic, descriptor_small |
| Form | 140px | w | SHORT momentum variant | Italic, descriptor_small |
| Record | 80px | center | (mono "W-L-D") | |

#### Filter row spec

- Position: directly below the SectionHeader, full-width (12-col)
- Layout: 3 dropdown filters (WC, Gender, Stage) + 1 search entry + 1
  clear button. All in a single Card/Flat row, 48px tall.
- WC dropdown: All / HW / LHW / MW / WW / LW / FW / BW / FL / SWStaw
- Gender dropdown: All / Men / Women
- Stage dropdown: All / Prospect / Rising Contender / Champion /
  Veteran / Gatekeeper / Declining (uses the canonical labels, NOT
  the voice phrases — these are filter selectors, not display)
- Search: 200px wide, placeholder "Search by name...", debounce 200ms
  (already implemented per Phase 4 perf work)
- Clear button (×): ghost button, appears only when any filter is active

#### Pagination spec

- Page size: 20 rows (current — keep)
- Pagination bar: bottom of table card, right-aligned
- Format: "Showing 1-20 of 1,002" (caption, left) + page buttons (right)
- Page buttons: prev ◀ + numbered pages (current + 2 on each side, ellipsis for gaps) + next ▶
- Current page: gold bg + `text_on_gold`
- Jump-to-page: click any page number. NO "jump to page N" input field
  (overkill for ~50 pages)

#### Row interaction spec

- Hover: `gold_tint` bg, cursor = hand2 (already current behavior)
- Single click: selects row, fires `on_row_click` (highlights the row)
- Double click: navigates to Fighter Profile (current behavior — keep)
- Right click: shows context menu (P1 future) — Sign/View Profile/
  Add to Watchlist/Add to Card

#### Empty state

When roster is empty (filter returns 0 rows):

> "No fighters match your filters."
> "Try widening your search — clear the WC filter or search by partial name."
> [Clear all filters] (Primary button)

When the player's promotion has 0 fighters (literal empty roster):

> "Your stable is empty."
> "Sign fighters from the Open Market to fill out your roster."
> [Browse Open Market ▶] (Primary button)

#### Data visualization

**Weight Class Distribution** — horizontal bar chart at the bottom of
the screen, 12-col. One bar per weight class, sorted by display_order.
Bar fill = `gold` for the player's promotion, `bg_card_elevated` track.
Bar length = fighter count (normalized to max). This is the
"every screen has at least one data viz" rule satisfied.

### 6.3 Fighter Profile

The most complex screen. Gets the most detail.

#### Wireframe

```
┌─ TOP BAR ──────────────────────────────────────────────────────────────────────────┐
├───┬─────────────────────────────────────────────────────────────────────────────────┤
│   │ Breadcrumb: The Stable / John Vale                                              │
│ S │                                                                                  │
│ I │ ┌─ Card / Accent (gold border — champion) ─── 12-col ───────────────────────┐  │
│ D │ │ ┌──────────┐  John Vale                              [CHAMP●] [W3]       │  │
│ E │ │ │ 256×320  │  "Iron Hand" · 28yo · LW · Pacific Rim · Iron Fist Gym       │  │
│ B │ │ │ Hero     │                                                            │  │
│ A │ │ │ portrait │  ┌─ identity strip ──────────────────────────────────────┐ │  │
│ R │ │ │          │  │ Career Phase: a rising contender climbing the ranks   │ │  │
│   │ │ │          │  │ Momentum:     holding steady                          │ │  │
│   │ │ │          │  │ Pressure:     moderate                                │ │  │
│   │ │ └──────────┘  │ Narrative:    the wunderkind everyone's talking about  │ │  │
│   │ │                │ Legacy:       still building a legacy                 │ │  │
│   │ │                │ Trajectory:   trending upward                         │ │  │
│   │ │                └──────────────────────────────────────────────────────┘ │  │
│   │ │                                                            [Cut Fighter] │  │
│   │ └────────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                  │
│   │ [Overview] [Attributes] [Personality] [Career] [Fights] [News]                  │
│   │ ━━━━━━━━                                                                         │
│   │                                                                                  │
│   │ ┌─ Card / Flat (8-col) ─────────────────┐  ┌─ Card / Flat (4-col) ──────────┐ │
│   │ │ █▌ BIO                                 │  │ █▌ CAREER                       │ │
│   │ │                                        │  │                                 │ │
│   │ │ John Vale grew up in Tijuana, where    │  │ Record      18-5-0              │ │
│   │ │ he learned to box in his uncle's gym.  │  │ Win streak  3                    │ │
│   │ │ ...                                    │  │ Title reigns 0                   │ │
│   │ │                                        │  │ Debut       2024                 │ │
│   │ └────────────────────────────────────────┘  └─────────────────────────────────┘ │
│   │                                                                                  │
│   │ ┌─ Card / Flat (12-col) ────────────────────────────────────────────────────┐  │
│   │ │ █▌ RECENT FIGHTS — last 5                                                 │  │
│   │ │                                                                            │  │
│   │ │ 2026-08-14  W  vs Marcus Stone    KO/TKO  R2 3:42      [TITLE]            │  │
│   │ │ 2026-07-03  W  vs Diego Reyes     Decision  Unan            ▶             │  │
│   │ │ 2026-05-21  W  vs Liam O'Brien    KO/TKO  R1 1:18            ▶           │  │
│   │ │ 2026-04-09  L  vs Vega Saito      Submission  R3 2:55         ▶          │  │
│   │ │ 2026-03-15  W  vs Tom Harris      Decision  Split             ▶          │  │
│   │ └────────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                  │
│   │ ┌─ Card / Flat (12-col) ────────────────────────────────────────────────────┐  │
│   │ │ █▌ ATTRIBUTE PROFILE — top 6 shown                  [Show all 26 ▼]      │  │
│   │ │                                                                            │  │
│   │ │ Striking Power    ████████████████░░░░  carries real knockout power       │  │
│   │ │ Striking Acc      ████████████░░░░░░░░  technical and precise             │  │
│   │ │ Takedown Off      ██████████░░░░░░░░░░  functional wrestler                │  │
│   │ │ Submission Off    ████░░░░░░░░░░░░░░░░  rarely threatens subs             │  │
│   │ │ Takedown Def      ███████████████░░░░░  stuffs most takedowns             │  │
│   │ │ Cardio            ██████████████████░░  relentless pace                    │  │
│   │ └────────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                  │
│   │ ┌─ Card / Flat (12-col) ────────────────────────────────────────────────────┐  │
│   │ │ █▌ PERSONALITY — top 6 shown                         [Show all 20 ▼]     │  │
│   │ │                                                                            │  │
│   │ │ Aggression      ████████████████░░░░  measured aggression                 │  │
│   │ │ Composure       ██████████████████░░  ice in his veins                     │  │
│   │ │ Fight IQ        █████████████████░░░  high-level adaptability              │  │
│   │ │ ...                                                                       │  │
│   │ └────────────────────────────────────────────────────────────────────────────┘  │
└───┴──────────────────────────────────────────────────────────────────────────────┘
```

#### Section order (top to bottom)

1. **Header card** (Accent, gold border if champion) — portrait + name
   + nickname + age + WC + promo + gym + identity strip + action
   buttons
2. **TabBar** — Overview / Attributes / Personality / Career / Fights / News
3. **Overview tab** (default): Bio (8-col) + Career stats (4-col) +
   Recent Fights timeline (12-col)
4. **Attributes tab**: full 26-attribute StatBar grid (2 columns of 13)
5. **Personality tab**: full 20-trait StatBar grid (2 columns of 10)
6. **Career tab**: full fight history (table), title reigns timeline,
   career arc visualization (P1)
7. **Fights tab**: same as Overview's Recent Fights but full history
8. **News tab**: NewsCards mentioning this fighter (P1 future — needs
   news_items filter by fighter_id)

#### Portrait treatment

- Hero size: 256×320 (current — keep)
- Border: 3px gold if champion, 2px `border_subtle` otherwise
- Champion variant: gold-leaf texture overlay on border (9-slice
  `gold_leaf_border.png` from §2.4)
- Status badges (top-right of portrait, stacked):
  - `[CHAMP●]` chip if champion (DataChip champion variant)
  - `[W3]` / `[L2]` chip if on streak (DataChip default variant)
  - `[INJ]` chip if injured (DataChip danger variant)
  - `[SUS]` chip if suspended (DataChip danger variant)

#### Attribute visualization

**StatBar (per §5.4).** Top 6 shown by default with a "Show all 26"
toggle (current behavior — keep). 2-column layout when expanded.

**No radar chart.** Reasoning: a radar chart shows all attributes at
once but at low resolution (each axis is a thin sliver). For a game
where the player needs to *read* each attribute's voice phrase, the
StatBar grid is better. Radar is a P2 "nice to have" for the overview
tab — a small thumbnail that complements the StatBars.

#### Personality visualization

Same StatBar component, 2-column grid. 20 traits. Each trait has a
voice descriptor (per `voice.PERSONALITY_DESCRIPTORS` in the audit
doc §1.7).

#### Recent fights

**Timeline view** (vertical, NOT a table). Each fight is a row:

- Date (caption, left, 100px)
- W/L indicator (large colored letter — gold W or crimson L, 24×24)
- Opponent name (HyperlinkLabel, gold)
- Method (decision / KO/TKO / submission — caption, secondary)
- Round + time (mono_small, e.g., "R2 3:42")
- Badge if title fight (`[TITLE]` chip, gold)
- Replay link (▶, ghost button, navigates to Fight Resolution replay
  — P1 future)

**Why timeline not table:** A table treats all fights as equal. A
timeline shows progression — the player can see the win streak, the
loss that broke it, the title fight that capped it. This serves the
Historian fantasy.

#### Scouting report (when shown)

For fighters NOT on the player's promotion (e.g., viewing a rival's
fighter), the Overview tab shows a Scouting Report card INSTEAD of the
identity strip:

- Source: `scouting_reports` table
- Display: Card/Flat (12-col) below the header card
- Content: scout's name + report date + scouting notes (voice phrases
  for hidden potential, projected ceiling, etc.)
- Voice: "scouting report" register — slightly hedged, slightly
  uncertain ("could develop into...", "reportedly shows...")
- If no scouting report: EmptyState ("No scouting report on file.
  Send a scout to gather intel.")

#### Memory links

**Memory card** (P1 future, not in scope for redesign launch but the
component design accommodates it). Below the Recent Fights card, a
"Fighter History" card showing:

- Past rivalries (DataChip crimson "BAD BLOOD" + HyperlinkLabel to
  rival fighter)
- Common opponents (list of 3-5 fighters with W/L record vs each)
- Gym history (list of gyms this fighter has trained at, with dates)

This is the Soul doc's "the player collects stories" made literal —
every fighter is a node in a story graph.

#### Action buttons

In the header card, top-right:

- **Primary**: "Cut Fighter" (Danger) — only shown if fighter is on
  player's roster. Opens ModalDialog confirmation.
- **Secondary**: "Offer Extension" — only shown if fighter is on
  player's roster and contract is expiring within 90 days
- **Secondary**: "Book Next Fight" — navigates to Matchmaking with
  this fighter pre-selected
- **Secondary**: "Scout" — only shown if fighter is NOT on player's
  roster. Navigates to Scouting.

### 6.4 Free Agents ("Open Market")

#### Wireframe

```
┌─ TOP BAR ──────────────────────────────────────────────────────────────────────────┐
├───┬─────────────────────────────────────────────────────────────────────────────────┤
│   │ Breadcrumb: Open Market                                                          │
│ S │                                                                                  │
│ I │ █▌ OPEN MARKET                                                247 free agents    │
│ D │                                                                                  │
│ E │ ┌─ Filter row ──────────────────────────────────────────────────────────────┐  │
│ B │ │ WC: [All ▼]  Ceiling: [All ▼]  [🔍 Search by name...]              [×]   │  │
│ A │ └──────────────────────────────────────────────────────────────────────────┘  │
│ R │                                                                                  │
│   │ ┌─ Card / Flat (12-col, table) ────────────────────────────────────────────┐  │
│   │ │ Name              Age  WC  Stage                    Ceiling   Record      │  │
│   │ │ ────────────────────────────────────────────────────────────────────────│  │
│   │ │   Diego Reyes     27  LW  Rising Contender          ????      14-3-0     │  │
│   │ │ ● Liam O'Brien    31  MW  Veteran                   High      22-8-0     │  │
│   │ │   ...                                                                     │  │
│   │ └───────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                  │
│   │ ┌─ Sign bar (12-col, sticky bottom of viewport) ───────────────────────────┐  │
│   │ │ Selected: Diego Reyes (LW, 27yo, Rising Contender)                        │  │
│   │ │ Estimated cost: $850K (3-fight deal, 18 months)        [Sign for $850K]  │  │
│   │ └───────────────────────────────────────────────────────────────────────────┘  │
│   │                                                                                  │
│   │ ┌─ Card / Flat (12-col — ceiling distribution viz) ───────────────────────┐  │
│   │ │ █▌ TALENT POOL BY CEILING                                                 │  │
│   │ │ Elite        ██ 8         Above-Avg  ████████████ 42                       │  │
│   │ │ High       █████ 18       Avg        ██████████████████ 68                 │  │
│   │ │ ...                                                                       │  │
│   │ └───────────────────────────────────────────────────────────────────────────┘  │
└───┴──────────────────────────────────────────────────────────────────────────────┘
```

#### How it differs from Roster

1. **Ceiling column** instead of Form column. Ceiling = the scouted
   projection of the fighter's peak potential. Shown as a voice phrase
   ("Elite", "High", "Above-Avg", "Avg", "Below-Avg", "Low",
   "Unknown"). For unscouted fighters, shows "????" (4 question marks
   in mono) — this is the WMMA5-style information asymmetry the Soul
   doc endorses (per current D1 in `free_agents.py:99-110`).

2. **Estimated cost** in the sign bar. When a fighter is selected, the
   sign bar shows the projected signing cost (based on ceiling, age,
   momentum, current market). This is the Empire Builder dopamine —
   "can I afford this kid?"

3. **No active dot** in the row (these aren't your fighters).

4. **Sign bar** at the bottom (sticky). The current Free Agents screen
   has a "Sign Selected Fighter" button below the table — we elevate
   it to a sticky bar that shows the selected fighter + estimated cost
   + the Sign button. This makes the signing action feel weighty.

#### Sign flow

1. Player clicks a row → row is selected, sign bar updates with
   fighter details + estimated cost
2. Player clicks "Sign for $X" → ModalDialog opens:
   - Title: "SIGN FIGHTER"
   - Body: "You're about to sign Diego Reyes to a 3-fight deal worth
     $850K guaranteed. This will deduct $850K from your promotion's
     cash balance."
   - Buttons: "Cancel" (Secondary) + "Sign for $850K" (Primary)
3. On confirm: `services.contracts.sign_free_agent(conn, fighter_id,
   promotion_id, start_date)` is called (current behavior). Modal
   closes. Toast notification (P1 future) appears: "Diego Reyes
   signed." NewsCard is generated (existing behavior).

#### Empty state

When 0 free agents match filters:

> "The market is quiet."
> "No unsigned fighters match your filters. Try widening your search."

When literally 0 free agents exist (impossible in the current world
seed, but defensive):

> "The market has dried up."
> "Every fighter in the world is under contract. Check back after the
> next event cycle."

#### Data visualization

**Talent Pool by Ceiling** — horizontal bar chart at the bottom, 12-col.
One bar per ceiling tier. Bar fill = `gold` for elite/high (the
desirable tiers), `bg_card_elevated` for avg/below (the filler tiers),
`text_tertiary` for unknown. This visualizes the *quality* of the
current market — the player can see at a glance "is this a good time
to sign?"

---

## 7. Theming Plan for All Other Screens

19 screens. Each gets: purpose (1 sentence), primary layout, key
components, voice guidance, data visualization, navigation entry.

### 7.1 Schedule ("Calendar")

- **Purpose:** Calendar view of all scheduled events (player + AI promotions).
- **Layout:** CalendarStrip (top, full-width) + day-detail panel below
  (8-col) + upcoming events list (4-col right rail).
- **Components:** CalendarStrip, Card/Flat, NewsCard (for event
  previews), EmptyState.
- **Voice:** Event names + main event headlines (short variant). No
  interpretation-layer data on this screen.
- **Data viz:** Calendar dots (gold for player's events, crimson for
  rival promo events) + a small 30-day event density sparkline at the
  top.
- **Nav entry:** Sidebar HOME group → "Calendar".

### 7.2 News Feed ("The Wire")

- **Purpose:** Chronological news feed with filters.
- **Layout:** Filter row (12-col) + vertical list of NewsCards (12-col
  each, infinite scroll).
- **Components:** NewsCard, DataChip (topic filter), HyperlinkLabel.
- **Voice:** Headlines (short) + body text (long) from `headline_engine`
  + `news_items`. This is THE screen where the interpretation-layer
  variety matters most — the audit doc's proposed 8-10 long variants
  per headline family is critical here.
- **Data viz:** A small topic-distribution bar at the top (how many
  SIGNING / RESULT / INJURY / RIVALRY / RUMOR items in the last 30 days).
- **Nav entry:** Sidebar HOME group → "The Wire".

### 7.3 Scouting

- **Purpose:** Regional scouting targets, scout assignments, hidden-
  potential reports.
- **Layout:** Scout assignment panel (4-col left) + scouting targets
  table (8-col right).
- **Components:** Card/Flat, FighterTable (variant with "scouted"
  column), DataChip (scouting status), StatBar (projected ceiling vs
  reported ceiling — dual-bar variant, P1).
- **Voice:** Scouting report prose (LONG variant, hedged register:
  "reportedly shows", "could develop into"). Uncertainty is the
  feature here — per the Soul doc, "Talent Hunter" fantasy is about
  finding greatness before anyone else, which requires incomplete info.
- **Data viz:** A small regional-talent heatmap (world map with hot
  zones — P2 future). P0 = a bar chart of "active scouts per region."
- **Nav entry:** Sidebar FIGHTERS group → "Scouting".

### 7.4 Hall of Fame ("Legends")

- **Purpose:** Inductees by year, search/filter, compare-to-current mode.
- **Layout:** Year selector (top) + inductee grid (12-col, 3 columns
  of Hero portrait cards).
- **Components:** Card/Accent (gold border for legends), PortraitFrame
  (Hero variant), HyperlinkLabel.
- **Voice:** Legacy phrases (LONG variant from `legacy_engine`). "The
  story is just beginning" → "his legacy was cemented the night he
  beat Saito." Each legend gets a 2-sentence epitaph.
- **Data viz:** A timeline of inductees by year (horizontal bar). A
  "eras of greatness" visualization (P2 future — show which 5-year
  windows produced the most HoF inductees).
- **Nav entry:** Sidebar FIGHTERS group → "Legends".

### 7.5 Event Builder ("Build a Card")

- **Purpose:** Schedule new event, build card of 5-13 fights.
- **Layout:** 3-panel split — event config (4-col left), card builder
  (4-col center), projected buyrate/attendance (4-col right).
- **Components:** Card/Flat, FighterRow (draggable, P1 future),
  Button, ModalDialog (confirm event), DataChip (title fight indicator).
- **Voice:** Projected buyrate + attendance are voice-phrased
  ("Strong card — projected 180K buys", "Weak main event — projected
  40K buys"). No raw numbers in the projection (the underlying
  calculation uses raw numbers, but the display is voice-phrased).
- **Data viz:** A card-strength meter (vertical bar, fills as fights
  are added). A buyrate projection sparkline (how the projection
  changes as you add/remove fights).
- **Nav entry:** Sidebar EVENTS group → "Build a Card". Also from
  Dashboard Next Event card.

### 7.6 Matchmaking

- **Purpose:** Pick two fighters → tale-of-tape + matchup analysis +
  projected odds + storyline context.
- **Layout:** 3-column split — Red corner fighter picker (4-col left),
  tale-of-tape + analysis (4-col center), Blue corner fighter picker
  (4-col right).
- **Components:** FighterRow (in picker modal), Card/Accent (corner
  headers), StatBar (tale-of-tape comparison), DataChip (style
  matchup indicator: "Striker vs Grappler", "Veteran vs Prospect").
- **Voice:** Matchup analysis prose (LONG variant, pundit register:
  "Vale's boxing should test Reyes's takedown defense, but if Reyes
  can drag this to the mat..."). Sourced from a future
  `matchup_analysis_engine` (not yet built).
- **Data viz:** Tale-of-tape comparison (dual StatBars side-by-side).
  Projected win probability (a 50/50 horizontal bar — red side vs
  blue side).
- **Nav entry:** Sidebar EVENTS group → "Matchmaking". Also from
  Fighter Profile "Book Next Fight" button + Event Builder.

### 7.7 Fight Resolution (THE Fight Night screen)

- **Purpose:** Pre-fight build-up, live beat-by-beat, post-fight recap.
  Per GUI_PLAN §4. THE big screen.
- **Layout:** Fixed 4-zone grid (no scroll). Cage heatmap (top-left,
  8-col), damage silhouettes (top-right, 4-col, 2 stacked), commentary
  feed (bottom-left, 8-col), pundit panel + memory bubble (bottom-right,
  4-col). See GUI_PLAN §4.2 for full spec.
- **Components:** Card/Accent (championship variant — gold border on
  all zones during title fights), HyperlinkLabel (fighter names in
  commentary), DataChip (knockdown indicator, near-submission
  indicator), LoadingState (during pre-fight build-up).
- **Voice:** Commentary (LONG variant, serif typography). Pundit
  interjections (italic serif, attributed). Memory bubble (italic
  serif, gold-tinted card with paper texture). This screen is where
  the proposed LONG variant system pays off the most — every beat
  needs unique prose.
- **Data viz:** Cage heatmap (the signature visual). Damage
  silhouettes. Round-by-round scorecard (small bar chart in the
  pundit panel).
- **Championship Skin:** when `fights.is_title_fight = 1`, all zone
  borders swap to `champion_gold_leaf`, belt graphic appears in
  pre-fight, "TITLE FIGHT" badge on top bar.
- **Nav entry:** Auto-navigated when player clicks "Watch Fight" on
  a scheduled event. Sidebar EVENTS group → "Fight Night" shows the
  most recent / next scheduled fight (read-only mode if no live fight).

### 7.8 Past Events ("The Archive")

- **Purpose:** Historical events with results, replays, news.
- **Layout:** TabBar (List / Calendar) + either an event list (table)
  or a calendar view. Click an event → detail view with fight card,
  results, news recap.
- **Components:** FighterTable (variant with W/L column), Card/Flat,
  TabBar, CalendarStrip (calendar tab).
- **Voice:** Event recap headlines (LONG variant from
  `headline_engine`'s past-event templates — P1 future). Results
  shown as "W (KO/TKO R2 3:42)" — voice-phrased method, mono
  round/time.
- **Data viz:** A historical attendance/buyrate trend chart (sparkline
  of player's last 20 events). P2 future: a "rivalry map" showing
  which fighters have met most often.
- **Nav entry:** Sidebar EVENTS group → "The Archive".

### 7.9 Finance ("The Books")

- **Purpose:** Income, expenses, forecast.
- **Layout:** TabBar (Income / Expenses / Forecast) + summary cards
  (top) + transaction table (bottom).
- **Components:** Card/Flat (summary), FighterTable (transactions),
  StatBar (budget allocation), DataChip (transaction type).
- **Voice:** All numbers shown in `mono`. Budget health voice-phrased
  ("Comfortable", "Tight", "Critical"). Per CONVENTIONS §14, cash +
  budgets are game-state (OK to display as numbers).
- **Data viz:** A 30-day cash flow bar chart (income vs expenses per
  day). A 90-day forecast sparkline (projection based on scheduled
  events + contracts). A expense breakdown donut chart (fighter
  salaries / venue costs / marketing / staff).
- **Nav entry:** Sidebar BUSINESS group → "The Books". Also from
  Dashboard Promotion Status card.

### 7.10 Contracts ("Deals")

- **Purpose:** Active contracts, expiring soon, negotiation queue.
- **Layout:** Filter row + contract table (12-col).
- **Components:** FighterTable (variant with contract columns:
  fighter, signed, expires, value, status), DataChip (expiring /
  negotiating / signed), Button (Offer Extension).
- **Voice:** Contract values in `mono`. Status voice-phrased
  ("Healthy", "Expiring", "Negotiating"). Per §14, contract values
  are game-state (OK as numbers).
- **Data viz:** A 90-day expiration timeline (horizontal bar showing
  which fighters' contracts expire when). A payroll bar chart (top
  10 highest-paid fighters).
- **Nav entry:** Sidebar BUSINESS group → "Deals".

### 7.11 Rival Promotions ("The Competition")

- **Purpose:** Other promotions in the world, their rosters, champions,
  prestige.
- **Layout:** Promo selector (top, horizontal scroll of promo logos)
  + selected promo detail (12-col, multi-section).
- **Components:** Card/Flat (promo logo + name + stats), PortraitFrame
  (their champions), FighterTable (their roster, read-only), StatBar
  (prestige comparison).
- **Voice:** Promo descriptions (LONG variant, journalistic register:
  "Pacific Rim Championship has built a reputation for developing
  lighter-weight talent..."). Per CONVENTIONS, promo stats are
  game-state (OK as numbers).
- **Data viz:** A prestige comparison bar chart (player's promo vs
  all rivals). A roster-size-by-weight-class stacked bar.
- **Nav entry:** Sidebar BUSINESS group → "The Competition".

### 7.12 Gyms ("Training Camps")

- **Purpose:** Gyms, their fighters, training camp scheduling.
- **Layout:** Gym selector (left, 4-col) + gym detail (8-col right):
  roster, training camp schedule, camp effects.
- **Components:** Card/Flat (gym card), FighterTable (gym's fighters),
  CalendarStrip (camp schedule), DataChip (camp type: "Striking
  Camp", "Conditioning Camp", etc.).
- **Voice:** Gym reputation voice-phrased ("Elite gym", "Respected
  regional gym"). Camp effects voice-phrased ("Striking improvement
  likely", "Cardio boost expected"). Per §14, no raw attribute gains
  shown — the camp's effect is a voice phrase.
- **Data viz:** A gym-prestige bar (where this gym ranks among all
  gyms). A 12-week camp schedule Gantt chart (P1 future).
- **Nav entry:** Sidebar BUSINESS group → "Training Camps".

### 7.13 Rankings ("The Rankings")

- **Purpose:** Divisional rankings, top contenders, rank movement.
- **Layout:** Weight class selector (top) + ranked fighter list (12-col
  table).
- **Components:** FighterTable (variant with rank + movement columns),
  DataChip (movement: ▲ rising, ▼ falling, ● steady).
- **Voice:** No interpretation-layer data — rankings are objective.
  Rank movement voice-phrased in the rank-change tooltip ("Vale jumped
  from #4 to #2 after his win over Stone").
- **Data viz:** A rank-movement sparkline per fighter (their rank
  over the last 12 months). This is the Historian fantasy — see how
  a fighter climbed (or fell).
- **Nav entry:** Sidebar WORLD group → "The Rankings".

### 7.14 Titles ("Belts")

- **Purpose:** All title belts, current champions, reign lengths,
  title history.
- **Layout:** Belt grid (12-col, 2-3 columns of belt cards).
- **Components:** Card/Accent (gold border, championship variant),
  PortraitFrame (champion hero), DataChip (reign length, defense count).
- **Voice:** Champion descriptions (LONG variant, regal register:
  "Volkov has held the belt for 18 months, defending it 4 times...").
  Per §14, reign length + defense count are career stats (OK as numbers).
- **Data viz:** A title-history timeline per belt (every champion
  the belt has ever had, with reign length). A "longest reigning
  champions" leaderboard.
- **Nav entry:** Sidebar WORLD group → "Belts".

### 7.15 Rivalries ("Bad Blood")

- **Purpose:** Active rivalries, their history, their heat level.
- **Layout:** Rivalry list (left, 4-col) + rivalry detail (8-col right):
  timeline, fight history, narrative context.
- **Components:** Card/Accent (crimson border for hot rivalries),
  FighterRow (the two rivals), DataChip (heat level: "Simmering",
  "Boiling", "Explosive"), HyperlinkLabel (fight replays).
- **Voice:** Rivalry narrative (LONG variant, dramatic register:
  "These two first met in 2024, when Stone called Vale out at the
  post-fight press conference..."). Sourced from a future
  `rivalry_narrative_engine` (P1).
- **Data viz:** A rivalry heat timeline (how the heat level has
  changed over time). A "fights between these two" timeline (W/L for
  each meeting).
- **Nav entry:** Sidebar WORLD group → "Bad Blood".

### 7.16 Records ("The Record Book")

- **Purpose:** All-time records — longest win streak, most title
  defenses, fastest KO, etc.
- **Layout:** Category selector (top) + record table (12-col).
- **Components:** Card/Flat (record holder card), FighterRow (top 10
  per record), DataChip (record type).
- **Voice:** Record descriptions (LONG variant, legendary register:
  "Volkov's 11-fight win streak is the longest in heavyweight
  history, surpassing..."). Per §14, the streak COUNT is a career
  stat (OK as number).
- **Data viz:** A "records broken this year" counter at the top.
  P2 future: a "records graph" showing how the all-time streak record
  has evolved.
- **Nav entry:** Sidebar WORLD group → "The Record Book".

### 7.17 Settings

- **Purpose:** Display, audio, gameplay, mods settings.
- **Layout:** TabBar (Display / Audio / Gameplay / Mods) + settings
  form (12-col).
- **Components:** Card/Flat (setting group), Button (apply), toggle
  switches (CTkSwitch).
- **Voice:** Settings labels in `caption` (uppercase). Descriptions
  in `body_small` (sentence case).
- **Data viz:** None required (settings don't need viz). Exception to
  the "every screen has a data viz" rule for utility screens.
- **Nav entry:** Top-bar kebab menu → "Settings".

### 7.18 Save / Load

- **Purpose:** Save game, load game, manage save slots.
- **Layout:** Save slot list (12-col, 3-6 slots visible).
- **Components:** Card/Flat (save slot — date, promotion name,
  in-game date, file size), Button (Save Here / Load / Delete),
  ModalDialog (overwrite confirmation).
- **Voice:** Save slot metadata in `caption` (uppercase). Auto-save
  indicator: DataChip info "AUTO".
- **Data viz:** A playtime sparkline per save slot (how much time
  the player has invested). P2 future.
- **Nav entry:** Top-bar kebab menu → "Save / Load".

### 7.19 Mods

- **Purpose:** Browse, install, manage mods.
- **Layout:** Mod list (left, 4-col) + mod detail (8-col right).
- **Components:** Card/Flat (mod card), DataChip (installed / available
  / update available), Button (Install / Enable / Disable), LoadingState
  (during install).
- **Voice:** Mod descriptions in `body` (sentence case). Compatibility
  warnings voice-phrased ("This mod may conflict with...").
- **Data viz:** A mod dependency graph (which mods require which).
  P2 future.
- **Nav entry:** Top-bar kebab menu → "Mods".

---

## 8. Asset Inventory (Revised)

### 8.1 Audit of current assets

Per `cage_empire/src/ui/assets/`:

| Asset type | Current count | Notes |
|---|---|---|
| Promo logos | 10 | Generated. OK for launch. |
| Fighter portraits | 1 (placeholder) | Need many more. P0 = 1 default portrait (current), P1 = procedurally generated initials-based portraits, P2 = AI-generated. |
| Fonts | 9 | Inter (4 weights), JetBrains Mono (1), Source Serif Pro (4). Missing: Oswald (display). |
| Logo variants | 2 (primary + compact) | Per GUI_PLAN §1, 5 variants × multiple sizes = 24 files expected. We have 2. |
| Icons | 0 (paths only) | `STATUS_ICONS` + `NAV_ICONS` dicts in `theme.py:527-564` point at empty files. **This is a P0 blocker.** |
| Backgrounds / textures | 0 | All proposed in §2.4 are unbuilt. |
| Pundit avatars | 0 | Proposed in GUI_PLAN §6.7. Unbuilt. |
| Memory bubble textures | 0 | Proposed in GUI_PLAN §6.8. Unbuilt. |
| Belt graphics | 0 | Proposed in GUI_PLAN §6.5. Unbuilt. |
| Cage heatmap base | 0 | Proposed in GUI_PLAN §6.3. Unbuilt. |
| Damage silhouettes | 0 | Proposed in GUI_PLAN §6.3. Unbuilt. |

### 8.2 Revised asset list (priority tiers)

**P0 = must-have for redesign launch. P1 = nice-to-have, ship 2-4 weeks
after. P2 = future, ship when bandwidth allows.**

#### Icons (P0 — 32 assets)

| Asset | Format | Dimensions | Style | Priority |
|---|---|---|---|---|
| Nav icons (14) | PNG + SVG | 20×20, 32×32 | Single-color (`gold`), outlined, Lucide/Phosphor style | P0 |
| Status icons (8) | PNG + SVG | 16×16, 32×32 | Single-color (`gold` for champion, `crimson` for danger, etc.) | P0 |
| Topic icons (10) | PNG + SVG | 16×16 | For news topics: SIGNING, INJURY, RESULT, RIVALRY, RUMOR, RETIREMENT, TITLE, SUSPENSION, DEBUT, COMEBACK | P0 |

**Style guidance:** All icons follow the Lucide/Phosphor outlined style
— 2px stroke weight, single-color (no gradients), transparent background.
Outlined (not filled) for default state; filled for active state. SVG
source is the source of truth; PNG exports at 16/20/32px for runtime.

**Total: 32 icons × 2 sizes = 64 PNG files + 32 SVG sources = 96 files.**

#### Logo variants (P0 — 8 assets)

| Asset | Format | Dimensions | Priority |
|---|---|---|---|
| Logo primary (existing) | PNG | 1536×1024 (current) | Already have |
| Logo compact (existing) | PNG | 450×300 (current) | Already have |
| Logo mark (NEW — 32×32 for top bar) | PNG | 32×32, 64×64 | P0 |
| Logo wordmark only (NEW — for top bar) | PNG | 200×40 | P0 |
| Logo fight night variant (crimson-tinted) | PNG | 1536×1024 | P0 |
| Logo championship variant (gold-leaf) | PNG | 1536×1024 | P0 |
| Logo favicon | PNG + ICO | 16×16, 32×32, 64×64 | P0 |
| Logo monochrome (for dark/light bg) | PNG | 200×40 | P0 |

**Total: 8 files (6 new).**

#### Fonts (P0 — 1 new asset)

| Asset | Format | Size | Priority |
|---|---|---|---|
| Oswald Bold | TTF | ~120 KB | P0 |

**Total: 1 new file.** (Inter, JetBrains Mono, Source Serif Pro already
bundled.)

#### Backgrounds / textures (P0 — 4 assets)

| Asset | Format | Dimensions | Priority |
|---|---|---|---|
| `noise_grain.png` (Office + Fight Night bg tile) | PNG | 256×256 | P0 |
| `chain_link_dim.png` (Fight Night shell texture) | PNG | 512×512 | P0 |
| `gold_leaf_border.png` (9-slice for champion cards) | PNG | 16×16 | P0 |
| `vignette_fight_night.png` (overlay) | PNG | 1920×1080 | P0 |

**Total: 4 files.** All procedurally generated via PIL (no image-gen
needed).

#### Fighter portraits (P1 — procedural generation)

| Asset | Format | Dimensions | Priority |
|---|---|---|---|
| Default portrait (existing) | PNG | 256×320 | Already have |
| Initials-based portraits (procedural) | PNG | 256×320 | P1 — script generates 1 per fighter using PIL: gradient bg (gold/crimson tinted), 2-letter initials in Oswald Bold |

**Total: ~4500 portraits (1 per fighter), generated at seed time.**
**Style guidance:** Gradient background based on fighter's weight class
(HW = darker, FL = lighter). Initials in Oswald Bold 96px, white. A
subtle gold-leaf border if champion. No AI image generation needed —
procedural is sufficient and fast.

#### Fight Night specific (P1 — 8 assets)

| Asset | Format | Dimensions | Priority |
|---|---|---|---|
| Cage heatmap base texture | PNG | 1024×1024 | P1 |
| Damage silhouette sprite sheet A | PNG | 512×512 | P1 |
| Damage silhouette sprite sheet B | PNG | 512×512 | P1 |
| Round transition overlay ("ROUND 2") | PNG | 1920×1080 | P1 |
| Knockdown flash overlay | PNG | 1920×1080 | P1 |
| Finish banner ("WINNER") | PNG | 1920×400 | P1 |
| Pundit avatar dot template | PNG | 64×64 | P1 |
| Memory bubble texture (4 tints) | PNG | 256×256 ×4 | P1 |

**Total: 11 files (4 memory bubble textures counted as 4).** All need
image generation OR commission. Style: cinematic, slightly desaturated,
gold/crimson palette, documentary feel.

#### Belt graphics (P1 — 16 assets)

| Asset | Format | Dimensions | Priority |
|---|---|---|---|
| 8 weight class belts (front + side) | PNG | 512×256 | P1 |

**Total: 16 files.** Need commission or AI image generation. Style:
realistic championship belts, gold + leather, weight-class-specific
motifs (HW = eagle, LW = lightning, etc.).

#### Pundit avatars (P2 — 12 assets)

| Asset | Format | Dimensions | Priority |
|---|---|---|---|
| 12 colored circle avatars with initials | PNG | 64×64 | P2 |

**Total: 12 files.** Procedurally generated via PIL.

#### Champion card gold-leaf accent (P0 — 1 asset, already counted)

Already counted in §8.2 Backgrounds.

### 8.3 Total asset count

| Tier | Count | Notes |
|---|---|---|
| P0 | 32 icons + 6 logo variants + 1 font + 4 textures = **43 new files** | Must-have for redesign launch |
| P1 | 1 portrait script + 11 fight night + 16 belts = **28 files** (+ ~4500 generated portraits) | Ship 2-4 weeks after |
| P2 | 12 pundit avatars + future assets = **12+ files** | Future |
| **TOTAL new** | **~83 files** (+ ~4500 procedurally generated portraits) | Up from current ~110 to ~165 (mostly icon set + textures) |

### 8.4 Generation method

| Asset type | Method | Effort |
|---|---|---|
| Icons (P0) | **Commission or AI image generation.** Style: Lucide/Phosphor outlined. Source: prompt each icon with a 1-sentence description, generate as SVG, manually clean up. | 2-3 days for 32 icons |
| Logo variants (P0) | **Image generation.** Use the supervisor-final logo as source, generate variants via image_gen skill or manual design. | 1 day |
| Oswald font (P0) | **Download from Google Fonts.** Free, OFL license. | 5 minutes |
| Textures (P0) | **Procedural via PIL.** Noise = random grey pixels at 3% opacity. Chain link = simple repeating pattern. Gold leaf = gradient + noise. Vignette = radial gradient. | 1 day for all 4 |
| Portraits (P1) | **Procedural via PIL script.** Generate at seed time. | 1 day for the script, runs in ~30 seconds for 4500 fighters |
| Fight Night assets (P1) | **AI image generation.** Use image_gen skill with detailed prompts. | 3-4 days |
| Belts (P1) | **AI image generation or commission.** | 2-3 days |
| Pundit avatars (P2) | **Procedural via PIL.** | 0.5 days |

**Estimated total effort:** ~2-3 weeks of focused asset work, parallel
to the code work in §9.

---

## 9. Implementation Sequencing

### 9.1 Phase plan

**6 phases, sequenced. Each phase is shippable.**

#### Phase 1: Theme + Font Bundle (Effort: S, 2-3 days)

- Rewrite `theme.py` with the new 4-tier color system, 3 card variants,
  new font registration (unique family names per weight), Oswald
  bundling, spacing tokens.
- Add the startup health check that logs resolved font families.
- Add the texture-loading utilities (PIL-based, cached).
- **Dependencies:** None.
- **Shippable:** New theme applies to existing screens (they look
  better immediately, even without structural changes). No new
  components yet.
- **Risk:** Font registration changes could break existing tests.
  Mitigation: run the test suite after the change, fix any failures
  before merging.

#### Phase 2: Component Library (Effort: M, 5-7 days)

- Build all 15 components in `src/ui/widgets/components/` as a new
  package. Each component is a standalone CTkFrame subclass with its
  own test.
- Components: Card, SectionHeader, DataChip, StatBar, FighterRow,
  NewsCard, WatchCard, PortraitFrame, HyperlinkLabel (refactor existing),
  Button, TabBar, CalendarStrip, Breadcrumb, EmptyState, LoadingState,
  ModalDialog.
- **Dependencies:** Phase 1 (theme).
- **Shippable:** Components exist but aren't used by any screen yet.
  No visual change for the player. This is the foundation.
- **Risk:** Component API design. Mitigation: design APIs in this plan
  doc first, get supervisor sign-off, then build.

#### Phase 3: App Shell Rewrite (Effort: M, 4-5 days)

- Rewrite `app.py` shell: new top bar (56px, 3 zones), new sidebar
  (56px collapsed / 220px expanded, icon+label, pin toggle), remove
  bottom bar.
- Bundle the 14 nav icons (P0).
- Implement the borderless window mode (P1 — ship with OS title bar
  first, add borderless as a polish item).
- **Dependencies:** Phase 1 (theme) + Phase 2 (components: Button,
  HyperlinkLabel).
- **Shippable:** New shell looks dramatically better. Existing screens
  still render inside it (they look slightly better just by virtue of
  the new shell).
- **Risk:** Sidebar collapse-on-hover could feel janky. Mitigation:
  default to expanded, only collapse if the player explicitly pins it.

#### Phase 4: Dashboard Redesign (Effort: M, 4-5 days)

- Rewrite `dashboard.py` using the new components + grid system.
- Build the 6 sections per §6.1.
- Add the cash sparkline (P0 data viz).
- **Dependencies:** Phase 2 (components) + Phase 3 (shell).
- **Shippable:** Dashboard is the first screen to fully adopt the new
  design. Player sees the new look immediately on launch.
- **Risk:** Section density — too many cards could feel cramped. Target
  6 visible sections above the fold at 1920×1080.

#### Phase 5: Roster + Free Agents Redesign (Effort: L, 6-8 days)

- Rewrite `fighter_table.py` as a new `FighterTableV2` (behind a
  feature flag — old widget stays until the new one is proven).
- Rewrite `roster.py` and `free_agents.py` using FighterTableV2 + new
  components + grid system.
- Add weight class distribution viz (Roster) + ceiling distribution
  viz (Free Agents).
- Add the sticky sign bar (Free Agents).
- **Dependencies:** Phase 2 (components) + Phase 3 (shell) + Phase 4
  (proves the redesign pattern on a simpler screen).
- **Shippable:** Both table-based screens adopt the new design. The
  feature flag lets us A/B test against the old widget.
- **Risk:** **HIGHEST RISK** — FighterTable is used by 2 screens + 4
  future screens. Breaking it breaks everything. Mitigation: build V2
  in parallel, ship behind `USE_FIGHTER_TABLE_V2 = True/False` flag,
  flip the flag per screen during testing, remove old widget only
  after both screens have shipped V2 + been tested for a week.

#### Phase 6: Fighter Profile Redesign (Effort: L, 7-9 days)

- Rewrite `fighter_profile.py` using the new components + grid system.
- Build the 6-tab TabBar.
- Build the StatBar-based attribute + personality grids.
- Build the recent fights timeline.
- Build the champion-variant PortraitFrame with gold-leaf border.
- **Dependencies:** Phase 2 (components) + Phase 3 (shell) + Phase 5
  (proves the complex-screen pattern).
- **Shippable:** The most complex screen adopts the new design. All 4
  existing screens are now redesigned.
- **Risk:** Tab content loading — switching tabs should be instant.
  Mitigation: pre-render all tab contents on screen load, hide/show
  via `pack_forget` / `pack`.

#### Phase 7 (future, post-redesign): Other 18 screens

- Build per the specs in §7. Each screen follows the same pattern:
  Phase 2 components + Phase 3 shell + per-screen layout.
- Effort: S-M per screen, depending on complexity. Total ~6-8 weeks
  for all 18.
- **Out of scope for this redesign.** This plan's scope is the 4
  existing screens + the theming system that the other 18 will follow.

### 9.2 Total estimated effort

| Phase | Effort | Days |
|---|---|---|
| 1. Theme + Fonts | S | 2-3 |
| 2. Component Library | M | 5-7 |
| 3. App Shell | M | 4-5 |
| 4. Dashboard | M | 4-5 |
| 5. Roster + Free Agents | L | 6-8 |
| 6. Fighter Profile | L | 7-9 |
| **Total** | | **28-37 days (~6-8 weeks of focused work)** |

### 9.3 Riskiest changes

1. **FighterTable rewrite (Phase 5).** Used by 2 live screens + 4
   future screens. Mitigation: feature flag, parallel V2, gradual
   rollout. (Already discussed.)

2. **Font registration changes (Phase 1).** The current registration
   is silently failing. Fixing it could change the appearance of every
   screen simultaneously. Mitigation: log resolved families, test on
   all 3 platforms (Win/Mac/Linux) before merge.

3. **Borderless window mode (Phase 3, P1).** `overrideredirect(True)`
   is brittle on Linux (some WMs don't play nice). Mitigation: ship
   with OS title bar first, add borderless as a Settings toggle (off
   by default) in the polish phase.

4. **Fight Night screen (Phase 7, post-redesign).** The biggest single
   screen in the project. 4 zones, beat-synced, 60fps target. Per
   GUI_PLAN §4.5, the performance budget is tight. Mitigation: build
   incrementally — Phase 7a = pre-fight build-up only, Phase 7b = live
   fight with heatmap only, Phase 7c = add damage silhouettes, Phase
   7d = add pundit panel + memory bubble.

5. **Voice phrase variety (cross-cutting).** The audit doc found the
   interpretation layer has severe phrase repetition. The redesign
   can't fix this alone — the interpretation layer needs the proposed
   short/long variant system. Mitigation: this redesign assumes the
   audit's P0 fix (ENGINE_VERSION bump) lands first; the redesign's
   StatBar tooltips + WatchCard voice phrases rely on LONG variants
   existing.

---

## 10. Open Questions for the Supervisor

10 questions. Each has 2-4 options with the recommended option marked
**[RECOMMENDED]**.

### Q1. Sidebar collapse behavior

- **A.** 220px text+label always (current). Simple, but VLM says too wide.
- **B.** 56px icon-only always. Maximum content space, but labels hidden.
- **C.** 56px collapsed (default) + 220px on hover, pin to keep expanded. **[RECOMMENDED]** — VS Code/Linear pattern, gives players both modes.
- **D.** Auto-collapse based on window size (collapse below 1280px width).

### Q2. Display font

- **A.** Bundle Oswald (OFL, free, ~120 KB). **[RECOMMENDED]** — stadium-scoreboard feel, free, single weight suffices.
- **B.** Commission a custom stencil font ($500-$2000, 4-8 weeks). Unique, on-brand, but out of scope for this redesign timeline.
- **C.** Use Inter Bold with -0.02em tracking + 10% horizontal stretch. Already bundled, no new asset, but doesn't achieve the scoreboard feel.
- **D.** Bebas Neue (free, OFL). More dramatic, but ALL CAPS only — limits reuse.

### Q3. Card shadows

- **A.** Real drop shadows via PIL compositing (per-frame). Looks best, but ~15ms × 30 cards = 450ms per refresh — over budget.
- **B.** 1px border + 4-tier bg depth system (no shadows). **[RECOMMENDED]** — depth comes from value contrast, not blur. 0ms cost. The VLM's "no z-depth" critique is fixed by the bg system, not by shadows.
- **C.** Single static shadow rendered once per card variant (pre-baked PNG). Middle ground — gives shadow look without per-frame cost, but limits dynamic resizing.
- **D.** CTk's native `border_width` + `border_color` only (current approach, refined). Essentially B but with stronger borders.

### Q4. Bottom news ticker bar

- **A.** Keep it (32px, current). Player sees news without navigating.
- **B.** Remove it entirely. **[RECOMMENDED]** — duplicates News Feed, reclaims 32px of vertical space, removes a "database tool" visual element.
- **C.** Replace with a thin "next event countdown" strip (16px). Compromise — keeps the countdown but drops the news ticker.
- **D.** Make it toggleable in Settings.

### Q5. Borderless window (custom title bar)

- **A.** Full borderless on launch. Most immersive, but `overrideredirect(True)` is brittle on Linux.
- **B.** OS title bar on launch, borderless as a Settings toggle (off by default). **[RECOMMENDED]** — safe default, players who want immersion can opt in.
- **C.** OS title bar always (current). Safest, but keeps the "amateurish Windows chrome" the VLM flagged.
- **D.** Borderless on Windows + macOS only, OS chrome on Linux. Platform-aware, but adds complexity.

### Q6. StatBar visualization for attributes

- **A.** Horizontal bars only (per §5.4). **[RECOMMENDED]** — readable, voice-phrase-friendly, fits the grid.
- **B.** Radar/spider chart. Compact, shows all attributes at once, but at low resolution per axis.
- **C.** Hex grid (each attribute = a hexagonal cell, color-coded by tier). Visually striking, but unconventional and harder to read individual attributes.
- **D.** Both: bars by default, radar as a toggle. Best of both, but doubles the work.

### Q7. Championship Mode (3rd mode)

- **A.** Add it as a full 3rd mode with its own palette. Most distinct, but triples the design surface area.
- **B.** Add it as a "skin" overlay on Fight Night (per §1.2). **[RECOMMENDED]** — 4-color overlay, activates only on title fights, minimal extra design work.
- **C.** Don't add it. Title fights use the standard Fight Night palette. Simpler, but loses the "marquee moment" visual weight.
- **D.** Add it later (P2 future). Defer the decision.

### Q8. Recent Fights visualization on Fighter Profile

- **A.** Timeline view (per §6.3). **[RECOMMENDED]** — shows progression, serves Historian fantasy.
- **B.** Table view (current). Denser, treats all fights equally.
- **C.** Both: timeline by default, table as a tab toggle. Best of both, but adds complexity.
- **D.** Cards (one card per fight). Most visual, but takes the most vertical space.

### Q9. Empty state personality

- **A.** Generic "No data found" + icon. Safest, but boring.
- **B.** Unique voice-phrased empty state per screen (per §5.14). **[RECOMMENDED]** — reinforces the CAGE EMPIRE voice, makes empty states feel intentional.
- **C.** Empty states with a CTA button only (no voice phrase). Functional, but flat.
- **D.** Procedurally generated empty-state phrases (random per visit). Maximum variety, but risks tonal inconsistency.

### Q10. Icon style

- **A.** Lucide/Phosphor outlined (2px stroke, single-color). **[RECOMMENDED]** — modern, consistent with Linear/Notion/Vercel aesthetic, easy to generate.
- **B.** Filled icons (solid shapes, single-color). More visual weight, better for active states, but heavier overall.
- **C.** Custom hand-drawn icons. Most unique, but requires commission.
- **D.** Material Icons (Google's set). Massive library, free, but reads as "default Android" — the opposite of the brand.

### Q11. Color palette — keep the dual crimson+gold co-primary system?

- **A.** Keep crimson + gold as co-primaries (per GUI_PLAN §3.3). **[RECOMMENDED]** — the supervisor already pushed back on the original "calm-only" direction. The dual co-primary system is the brand.
- **B.** Demote crimson to a "danger only" color, gold becomes the sole accent. Cleaner, but loses the violence/empire duality.
- **C.** Add a 3rd co-primary (e.g., steel blue for "info" / "neutral"). More visual vocabulary, but dilutes the brand.
- **D.** Replace gold with a cooler accent (e.g., silver/platinum). More "premium" feel, but loses the warmth.

### Q12. Fighter Profile tab structure

- **A.** 6 tabs: Overview / Attributes / Personality / Career / Fights / News (per §6.3). **[RECOMMENDED]** — comprehensive, matches the genre standard.
- **B.** 4 tabs: Overview / Attributes / Career / Fights. Simpler, but merges Personality into Attributes (loses the distinction).
- **C.** No tabs — single long scroll. Simpler, but overwhelming for a screen with 26 attributes + 20 traits + 5 recent fights + bio + career stats.
- **D.** 8 tabs: add Scouting + Contracts + Injuries + Social. Most granular, but only relevant for some fighters.

---

## Appendix A: Traceability Matrix (Design Decision → Soul Fantasy)

Every major design decision traces back to one of the 5 core fantasies
from the Soul doc.

| Decision | Primary fantasy served | How |
|---|---|---|
| 4-tier depth system (§2.2) | Empire Builder | Density + order = the "control room" feel of running an empire |
| Championship Skin (§1.2) | Kingmaker | Title fights get marquee visual weight — the player makes stars |
| Voice-phrase typography (§3.2, `descriptor` italic) | Historian | Voice phrases are visually distinct from numbers — reinforces "stories, not stats" |
| Fighter Watch cards (§5.7, §6.1) | Talent Hunter | 3 daily stories = the player's curated discoveries |
| StatBar with voice phrases (§5.4) | All | No raw attribute numbers — the simulation is translated to emotion |
| Recent Fights timeline (§6.3) | Historian | Shows progression, not just results — the player remembers arcs |
| Memory bubble on Fight Night (§7.7) | Historian + Puppet Master | Past stories resurface at the moment they matter |
| Rivalries screen with crimson accent (§7.15) | Puppet Master | Bad blood is visible — the player shapes conflict |
| Hall of Fame with gold-leaf border (§7.4) | Historian | Legends get the most premium visual treatment |
| Scouting with "?" ceiling (§6.4) | Talent Hunter | Incomplete info = the dopamine of discovery |
| Anticipation hooks on Dashboard (§6.1) | All | Top Story + Next Event + Fighter Watch = the player wants to click Advance Day |
| Borderless window (§4.6) | All | Immersion — the player is in the world, not in a database tool |

---

## Appendix B: Component → Screen Coverage Matrix

Which components each of the 4 redesigned + 18 future screens use. "✓"
= used, "—" = not used. Helps validate that the 15-component library
covers all needs without bloat.

| Component | Dashboard | Roster | Profile | Free Agents | Other 18 |
|---|---|---|---|---|---|
| Card | ✓ | ✓ | ✓ | ✓ | all |
| SectionHeader | ✓ | ✓ | ✓ | ✓ | all |
| DataChip | ✓ | ✓ | ✓ | ✓ | all |
| StatBar | — | — | ✓ | — | 12 |
| FighterRow | — | ✓ | — | ✓ | 8 |
| NewsCard | ✓ | — | ✓ | — | 4 |
| WatchCard | ✓ | — | — | — | 0 |
| PortraitFrame | ✓ | — | ✓ | — | 6 |
| HyperlinkLabel | ✓ | ✓ | ✓ | ✓ | all |
| Button | ✓ | — | ✓ | ✓ | all |
| TabBar | — | — | ✓ | — | 8 |
| CalendarStrip | — | — | — | — | 3 |
| Breadcrumb | — | — | ✓ | — | 6 |
| EmptyState | ✓ | ✓ | — | ✓ | all |
| LoadingState | — | — | — | — | 4 |
| ModalDialog | — | — | ✓ | ✓ | 8 |

**Coverage:** 15 components cover all 22 screens. No screen needs a
16th bespoke component. The library is right-sized.

---

## Appendix C: Voice Phrase Length Variants (cross-reference to audit doc)

This plan assumes the interpretation layer delivers the short/long
variant system proposed in `docs/UI_REDESIGN_INTERPRETATION_AUDIT.md`.
Where each variant length is used:

| Variant length | Where used | Why |
|---|---|---|
| **SHORT** (2-4 words) | FighterRow Stage/Form cells, DataChip status, CalendarStrip event labels | Compact — fits in 140-200px column widths |
| **MEDIUM** (5-8 words) | NewsCard headline, Dashboard Top Story headline, WatchCard voice phrase | Reads at a glance — 1 line max |
| **LONG** (8-15 words) | Fighter Profile identity strip, NewsCard body, WatchCard context line, Fight Night commentary, Hall of Fame epitaph, Rivalry narrative | Reads as prose — 2-3 lines |

**Implementation dependency:** The redesign's StatBar tooltips, NewsCard
bodies, and WatchCard context lines all assume LONG variants exist.
The audit doc's P0 fix (bump `ENGINE_VERSION` from "1.5.0" to "1.6.0")
is a hard prerequisite — without it, the redesign will surface the
same 3-variant repetition the audit identified.

---

**END OF PLAN.**

*Authored by the Visual Redesign Expert (frontend-styling-expert) for
Task UI-REDESIGN-B. Awaits supervisor sign-off before any code work
begins. Recommended next step: supervisor reviews §10 Open Questions,
marks decisions, then Phase 1 (theme + fonts) can begin.*
