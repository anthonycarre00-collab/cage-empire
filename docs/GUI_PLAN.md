> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — GUI Phase Plan (Revision 3)

> **Status:** Strategic plan, Revision 3. **Awaiting supervisor sign-off
> on the 12 open questions in §11 before any code work begins.**
> **Mode:** PLANNING ONLY. No code or DB changes have been made for
> this revision.
>
> **Supersedes:** Revision 2 (2026-07-25). Revision 2's still-correct
> sections are preserved (logo system §3, framework choice §4, fight
> resolution screen §7.7). Revision 2's failed sections are replaced
> (visual design system §5, screen inventory §8, asset inventory §9,
> build order §10).
>
> **Authored:** 2026-07-30, after a deep collaborative planning phase
> involving two parallel subagent audits:
> - `docs/UI_REDESIGN_INTERPRETATION_AUDIT.md` (1,346 lines) — why the
>   interpretation layer still shows repetition despite the "8 variants
>   per label" claim, plus a comprehensive short/long variant proposal
> - `docs/UI_REDESIGN_VISUAL_PLAN.md` (2,424 lines) — ground-up redesign
>   of the 4 existing screens + theming plan for all other screens +
>   15-component library + 6-phase rollout
>
> **Decision owner:** Supervisor (user). The supervisor's role in this
> revision is to mark decisions on §11 (12 questions) so Phase 1 can
> begin.
>
> **Prime directive:** `docs/CAGE_EMPIRE_SOUL.md` remains the
> philosophical north star. Every decision in this plan traces back
> to one of the 5 core fantasies (Talent Hunter, Empire Builder,
> Kingmaker, Historian, Puppet Master) or the "anticipation is the
> real dopamine" principle.

---

## 0. What's New in Revision 3

Revision 2 (2026-07-25) was written **before** any UI code existed.
Since then, the project has shipped:

- Stage 6 Tasks 6.0-6.5 (app shell, dashboard, roster, fighter profile,
  free agents, scouting, save/load)
- UI Polish round (7 fixes: hidden attributes, gender filter, clickable
  names, portrait placeholder, font capitalisation, logo image, news
  ticker)
- UI Fix Plan 2 (26 fixes across 3 phases: nav back-stack, HyperlinkLabel,
  FighterTable widget, voice renames, promotion logos, gym icons)
- UI Implementation Plan v3 (14 fixes: P0 hyperlink navigation, P1
  dashboard hyperlinks + roster nationality, P2 visual texture)
- Phase 4 Performance (lazy refresh + debounce + portrait/query cache +
  12 DB indexes, schema v3.13.0)

**What the user told us after testing:** "We still have a lot of work
on the look/feel and presentation... I don't even like the palette we
are using or the fonts... we are now in a deep collaborative planning
and UI redesign phase, no coding just comprehensive planning." The user
labeled two screenshots "GUI mess" — VLM analysis confirmed: void-like
black backgrounds, no accent visibility, system default fonts, no icons,
no data viz, no MMA atmosphere.

**What this revision does about it:**

1. **Re-states the visual design system** with a 4-tier depth system
   (replacing the flat near-pure-black palette), a real display font
   (Oswald), a 15-component library, and 5 enforceable design principles.
   Detailed in `UI_REDESIGN_VISUAL_PLAN.md` §1-§5.
2. **Diagnoses the interpretation layer's repetition problem** — the
   "8 variants per label" claim from prior worklogs was misleading
   because (a) the 8-variant `_EXT` banks never reached the production
   DB (ENGINE_VERSION wasn't bumped), and (b) 98% of fighters share
   the same momentum label, so even 8 variants means ~547 fighters
   per phrase. Detailed in `UI_REDESIGN_INTERPRETATION_AUDIT.md`.
3. **Specifies a ground-up redesign** of the 4 existing screens
   (Dashboard, Roster, Fighter Profile, Free Agents) using the new
   component library + grid system. Detailed in
   `UI_REDESIGN_VISUAL_PLAN.md` §6.
4. **Provides a theming plan** for the 18 not-yet-built screens so
   every future screen inherits the same voice + styling. Detailed
   in `UI_REDESIGN_VISUAL_PLAN.md` §7.
5. **Surfaces 12 open questions** (§11) where the supervisor's
   decision is required before code work begins.

**What this revision does NOT do:**

- Does not change the framework (CustomTkinter + Pillow + ttkbootstrap-
  Treeview — still the right choice).
- Does not change the logo (supervisor-designed, locked per §3).
- Does not change the dual-mode architecture (Office + Fight Night —
  still correct, just better implemented).
- Does not change the Fight Resolution screen vision (§7.7 — still the
  centerpiece, still 4 zones, still targeting WMMA5-outdoing quality).
- Does not commit to any code changes — this is a planning doc. Code
  begins after §11 sign-off.

---

## 1. Soul Doc Alignment (unchanged)

Per `docs/CAGE_EMPIRE_SOUL.md`:

> The player does not collect fighters. The player collects stories.
> Every major system must contribute to: Discovery, Investment,
> Growth, Conflict, Legacy.

The 5 core fantasies:

1. **Talent Hunter** — "I find greatness before anyone else."
2. **Empire Builder** — "My promotion dominates the sport."
3. **Kingmaker** — "I create stars."
4. **Historian** — "The world remembers what I built."
5. **Puppet Master** — "The sport evolves because of my decisions."

**Anticipation is the real dopamine.** Players should constantly have:
the prospect I just signed, the champion nearing retirement, the
rivalry exploding, the gym producing talent, the event next month, the
young heavyweight everyone is talking about.

The Interpretation Layer's real purpose: **translate simulation into
emotion.** Raw `Age 37, Losses 4, Durability down 12%` becomes `His
best years may be behind him.`

**Traceability:** every design decision in this plan traces to one of
the 5 fantasies. See `UI_REDESIGN_VISUAL_PLAN.md` Appendix A for the
full traceability matrix.

---

## 2. Logo System (preserved from Rev 2 §1)

**Status:** Locked. Supervisor-designed. No changes.

| File | Size | Use |
|---|---|---|
| `docs/logo_concepts/supervisor_final/cage_empire_primary_1536x1024.png` | 1536×1024 | Primary lockup — splash, title bar, marketing |
| `docs/logo_concepts/supervisor_final/cage_empire_compact_450x300.png` | 450×300 | Compact — taskbar, Steam library, in-app corner badge |

**Brand system (5 variants, ~30 files total):**

| Variant | Status | Use case |
|---|---|---|
| Primary lockup | ✅ shipped | Splash, title bar, marketing |
| Compact lockup | ✅ shipped | Taskbar, in-app corner badge |
| Fight Night variant | ❌ P0 (redesign) | Pre-fight splash, Fight Resolution header |
| Championship variant | ❌ P1 (post-redesign) | Title fight screens, champion profile |
| Favicon / compact mark | ❌ P0 (redesign) | 16×16 favicon, mobile app icon |

The Fight Night + Favicon variants are needed for the redesign launch
(see §9 Asset Inventory). The Championship variant can ship later
(Phase 7+). All variants must work in: full colour, monochrome white,
monochrome black.

VLM verdict on the supervisor's logo (preserved from Rev 2):
"Brutalist Luxury / Industrial Sovereignty aesthetic. Premium, masculine,
authoritative. Avoids the cartoonish trap common in sports games."

---

## 3. Framework Choice (preserved from Rev 2 §2)

**Status:** Locked. No changes.

- **Primary:** `customtkinter>=5.2.0` — solves the "ugly tkinter"
  complaint, MIT-licensed, ~5 MB, cross-platform pixel-identical.
- **Secondary:** `Pillow>=10.0.0` — portraits, event posters, logo
  loading, heatmap composition, damage visualisation overlays.
- **Tertiary:** `ttkbootstrap>=1.10` — Treeview theming only (we
  currently use a custom FighterTable widget instead, but ttkbootstrap
  remains available as a fallback if the custom widget proves brittle).
- **Fight Night additional:** `Pillow + Canvas` — cage heatmap and
  fighter silhouette damage overlay widgets. No new dependencies.

Rejected alternatives (no change): PySide6/PyQt6 (license/size),
pywebview (two-language overhead), Flet (maturity), DearPyGui (wrong
paradigm), Kivy (touch-first), PyGObject (painful cross-platform).

---

## 4. Visual Design System (REVISED)

> Detailed spec: `docs/UI_REDESIGN_VISUAL_PLAN.md` §1-§5. This section
> is the strategic summary.

### 4.1 The corrected aesthetic

Revision 2 framed the duality as **Office Mode (90%, calm/institutional)**
vs **Fight Night Mode (10%, visceral/narrative)**. The split is correct
*as a structural decision* but the implementation failed on both sides:

- **Office Mode reads as "void," not "calm."** Near-pure-black
  backgrounds with no card system, no depth, no textures, no data viz.
  Calm ≠ empty. Calm = quiet confidence — Bloomberg Terminal, FM2024
  sidebar, OOTP standings grid. Those interfaces are dense but ordered.
- **Fight Night Mode doesn't exist yet.** The Fight Resolution screen
  is not built. So Office Mode is carrying 100% of the visual weight
  with a palette designed to *contrast* with Fight Night — without
  Fight Night to contrast against, the palette reads as flat darkness.

**The revised philosophy:**

> **Calm Empire is the control room. Violent Canvas is the ring.**
> The control room is not a void — it's a Bloomberg Terminal lit by
> a desk lamp at 2 a.m., with three monitors of data, a single
> ticker scrolling, and a half-drunk coffee. It feels *occupied*. It
> feels like work is being done. The ring is bright, loud, and short
> — everything the control room isn't. The contrast between them is
> the whole emotional arc of the game.

Office Mode needs *more* density, *more* texture, *more* incidentals —
not less. The user's "SAP/Excel" complaint is the symptom of "Office
Mode without enough to look at." Density with discipline is the fix.

### 4.2 Five design principles (every screen must follow)

These are *rules*, not guidelines. A screen that violates any of them
fails review.

1. **Pure black is forbidden.** Minimum background `#0a0c10` (Office)
   or `#06070a` (Fight Night). Pure `#000000` reads as a void and
   breaks the layered-charcoal depth system.
2. **Every screen has at least one data visualization.** A table is
   *not* a data viz. A bar chart, sparkline, heatmap, timeline, ring
   meter, or treemap counts. This is the single biggest fix for the
   "SAP/Excel" complaint.
3. **Every nav item has an icon.** No exceptions. The current sidebar
   is text-only — this is the single most fixable "database tool" tell.
4. **Every clickable element has a hover state.** Hover = lighter bg
   + cursor change + (for primary buttons) a subtle gold underline.
   No silent clickables.
5. **No raw attribute numbers in player-facing UI.** Per CONVENTIONS
   §14. Cash, dates, records, ranking position are OK (game state).
   Fighter attributes (0-100) must be voice-phrased. The redesign
   makes voice phrases *visually distinct* from numeric values —
   phrases get italic `descriptor` style, numbers get `mono` style.

### 4.3 Reference products

| Reference | What we steal | What we don't steal |
|---|---|---|
| Bloomberg Terminal | 4-zone top bar, dense-but-ordered card grid, "every pixel earns its place" | Amber-on-black palette (we use crimson+gold) |
| Football Manager 2024 | Sidebar-with-icons, "every screen has a sidebar of contextual actions", dark-mode palette, gold-hyperlinked player names | Vast sea of small text — too dense for our use case |
| ESPN scorestrip | Horizontal scrollable strip of "current scores" — used for Fight Night transport bar | Bright blue accent |
| HBO 24/7 | Serif typography for fight commentary, slow-pan documentary feel, quoted pundit lines with attribution | Video content (we're a text sim) |
| WMMA5 | Fighter Profile structure (headshot + bio + attributes + recent fights) — genre standard | Flat text feed for play-by-play (we replace with 4-zone Fight Night) |
| Crusader Kings 3 | "Every character has a portrait + traits + relationships" — traits as small iconified chips | 3D character models |
| OOTP Baseball | Hall-of-fame "compare to current player" mode | Baseball jargon |

### 4.4 Dual-mode + Championship Skin

**Keep the Office + Fight Night dual-mode architecture.** Do NOT unify
them — the user explicitly wants the contrast (HBO 24/7 vs ESPN
scoreboard).

**Add a narrow third layer: Championship Skin.** This is *not* a full
mode — it's a 4-color overlay applied to the Fight Night palette when
the fight being resolved is a title fight (`fights.is_title_fight = 1`).
It adds:

- Gold-leaf accent border on the cage heatmap
- Champion vs Challenger corner color swap (champion = gold corner,
  challenger = crimson corner — the standard boxing/MMA convention)
- Belt graphic displayed during pre-fight build-up and post-fight recap
- "TITLE FIGHT" badge on the top bar (replaces the standard "PPV #237")
- 5% brighter accent saturation

**Why this matters:** Title fights are the biggest stories. Without a
distinct visual treatment, every Fight Night feels the same.

### 4.5 Color system — 4-tier depth (the key fix)

The current 3-tier system (`bg_base` / `bg_surface` / `bg_surface_elevated`)
collapses "shell" and "card" into the same value, which is why the
sidebar visually merges with the main content. The revised 4-tier
system splits them, creating the z-depth the VLM demanded.

**Office Mode:**

| Role | Hex | Use |
|---|---|---|
| `bg_base` | `#0a0c10` | Main window background — only visible as 8px gutters between cards |
| `bg_surface` | `#15181f` | Sidebar, top bar — the *shell* surfaces |
| `bg_card` | `#1c2028` | Card backgrounds — every discrete panel |
| `bg_card_elevated` | `#252a33` | Hover, active tab, dialog, dropdown |
| `border_subtle` | `#2a2f38` | 1px card borders, divider lines |
| `border_strong` | `#3a4049` | 2px accent card borders (champion, selected) |
| `text_primary` | `#e8eaed` | Body, headings |
| `text_secondary` | `#aab0b8` | Metadata, captions, table column headers |
| `text_tertiary` | `#6b7280` | Disabled, timestamps only. NEVER for content |
| `text_on_gold` | `#1a1410` | Text on gold button bg (dark brown — "ink on gold leaf") |
| `crimson` | `#d63a3f` | Loss, KO/TKO, danger, rival heat — IMPACT moments only |
| `crimson_tint` | `rgba(214,58,63,0.10)` | Hover bg on danger buttons, "rivalry" row tint |
| `gold` | `#e0a957` | EMPIRE wordmark, champion, primary actions, hyperlinks, win |
| `gold_tint` | `rgba(224,169,87,0.10)` | Hover bg on cards/rows/links, active tab bg, "selected" row bg |
| `gold_bright` | `#f5c878` | Hover state for hyperlinks + buttons |
| `success` | `#4ade80` | Signed, recovered (sparingly — green is a "third accent") |
| `warning` | `#fbbf24` | At-risk, injured, contract expiring |
| `danger` | `#ef4444` | Cut, suspended, critical (the *action*, not the *state*) |
| `info` | `#60a5fa` | Informational badges, "new" indicators (blue allowed ONLY here) |

**Fight Night Mode:** Same 4-tier depth system, deeper values
(`bg_base=#06070a`, `bg_surface=#0d1015`, `bg_card=#14181f`,
`bg_card_elevated=#1c2028`). Brighter text (`text_primary=#f5f6f8`).
Brighter accents (`crimson=#e53e3e`, `gold=#f0c060`). Plus
`impact_yellow=#fbbf24` (knockdowns) and the reserved heatmap palette
(`heat_blue/orange/red` — **never used outside the cage heatmap**).

**Championship Skin overlay:** `champion_gold=#f0c060`,
`champion_gold_leaf=#f5d77a` (slightly warmer, for the heatmap border),
`challenger_crimson=#d63a3f`.

Full palette + justification per color: see
`UI_REDESIGN_VISUAL_PLAN.md` §2.

### 4.6 Texture system

Textures are subtle. The rule: a texture should be *felt*, not *seen*.
If the player notices the texture, it's too loud.

| Texture | Where | Spec |
|---|---|---|
| `noise_grain.png` | Tiled across `bg_base` (Office + Fight Night) | 256×256 PNG, 3% opacity grey noise |
| `chain_link_dim.png` | Tiled across `bg_surface` on Fight Night only | 512×512 PNG, chain-link at 4% opacity, crimson-tinted |
| `gold_leaf_border.png` | 9-slice border on champion cards | 16×16 PNG corner tile, 1px gold-leaf textured border |
| `paper_grain.png` | Background of memory bubble on Fight Night | 256×256 PNG, off-white paper grain at 8% opacity, gold-tinted |
| `vignette_fight_night.png` | Single overlay PNG on Fight Night main content | 1920×1080, radial gradient transparent → 30% black at corners |

All textures are PIL-generated (no image-gen needed). Performance
impact: <2ms per textured frame, cached at app startup.

### 4.7 Card / Depth system

**3 card variants. No more.** No shadows (PIL compositing is too slow
against the 167ms lazy-refresh budget). Depth comes from the 4-tier bg
system + 1px borders.

| Variant | bg | border | radius | When |
|---|---|---|---|---|
| Flat | `bg_card` | `border_subtle` 1px | 6px | Default content blocks |
| Elevated | `bg_card_elevated` | `border_subtle` 1px | 6px | Hover, modal, dropdown, active tab |
| Accent | `bg_card` | `border_strong` 2px (gold) | 6px | "This matters" cards — Top Story, profile header, champion chips, rivalry cards |

Corner radius: 6px cards, 4px chips, 0px tables (sharp "ledger" edges),
8px modal dialogs.

### 4.8 Typography system

**Bundle Oswald** (Google Fonts, OFL license, free, ~120 KB) as the
display font. Fixes the silent font registration failure where Inter
is registered 4× under the same family name and Tk collapses it.

| Role | Family | Size | Weight | Tracking | When |
|---|---|---|---|---|---|
| `display` | Oswald | 36px | 600 | +0.02em | Splash, "CAGE EMPIRE" wordmark, "ROUND 2" overlay |
| `display_small` | Oswald | 24px | 600 | +0.02em | Screen titles ("The Empire", "The Stable"), section eyebrows |
| `h1` | Inter | 22px | 700 | -0.01em | Page H1 (one per screen) |
| `h2` | Inter | 18px | 700 | -0.005em | Card/section titles |
| `h3` | Inter | 15px | 600 | 0 | Sub-section titles, tab labels |
| `body` | Inter | 14px | 400 | 0 | Default body text |
| `body_small` | Inter | 13px | 400 | 0 | Table rows, dense lists, sidebar items |
| `caption` | Inter | 11px | 500 | +0.04em | Metadata, timestamps, ALL UPPERCASE labels |
| `descriptor` | Inter Italic | 14px | 400 | 0 | Voice phrases — italic = "this is voice, not data" |
| `descriptor_small` | Inter Italic | 12px | 400 | 0 | Compact voice phrases in table cells |
| `mono` | JetBrains Mono | 14px | 500 | 0 | Numbers, records, dates ("$50.0M", "18-5-0") |
| `mono_small` | JetBrains Mono | 11px | 500 | 0 | Beat timestamps ("R2 3:42") |
| `commentary_fight` | Source Serif Pro | 17px | 400 | 0 | Fight Night commentary — THE key Fight Night font change |
| `pundit` | Source Serif Pro SemiBold Italic | 14px | 600 italic | 0 | Named pundit interjections |

**Type scale:** Modular ratio 1.2 (minor third). Smaller than typical
1.25 because management-sim screens are dense.

**Font registration fix:** Register each Inter weight under a UNIQUE
family name (`Inter-Regular`, `Inter-Medium`, etc.) so Tk can't
collapse them. Add a startup health check that logs the resolved family
for each role.

### 4.9 Layout system

**Shell (revised):**

```
┌─ TOP BAR (56px) ────────────────────────────────────────────────────┐
│ [mark] CAGE EMPIRE  ·  Mon 14 Sep 2026, Y1 W37  ·  $50.0M ↑  [▶]  │
├───┬─────────────────────────────────────────────────────────────────┤
│ S │                                                                 │
│ I │              MAIN CONTENT (12-col grid, 24px gutters)           │
│ D │                                                                 │
│ E │                                                                 │
│ B │                                                                 │
│ A │                                                                 │
│ R │                                                                 │
├───┴─────────────────────────────────────────────────────────────────┤
│ (no bottom bar — removed)                                          │
└────────────────────────────────────────────────────────────────────┘
```

**Changes from current:**

1. **Top bar: 60px → 56px.** Removed news ticker (it duplicates News
   Feed — that's content, not chrome).
2. **Top bar layout: 3 zones.** Left = logo mark (32×32) + wordmark
   "CAGE EMPIRE" (Oswald). Center = sim date + week/year + cash (all
   `mono`, with a tiny green/red delta arrow showing today's P&L).
   Right = global actions: "Advance" primary button (gold, 88×40) +
   kebab menu (⚙) for Save/Settings/Mods. The kebab removes 3 items
   from the sidebar.
3. **Sidebar: 220px text → 56px collapsed icon-only (default) + 220px
   expanded icon+label (on hover or pin).** VS Code / Linear pattern.
   Pin toggle at top of sidebar for players who prefer always-labeled.
4. **Sidebar content: 19 items → 14 items.** Removed Settings, Save/
   Load, Mods (moved to top-bar kebab). Fighter Profile already not
   in sidebar (AD-3 decision).
5. **Bottom bar: removed.** 32px reclaimed for main content. News
   ticker moves to News Feed. Next-event countdown moves to Dashboard
   "Next Event" card.

**Grid:** 12-column, 24px gutters, 24px page padding.

**Spacing tokens (8-point scale):** `4 / 8 / 12 / 16 / 24 / 32 / 48 /
64` px. Exposed as constants in `theme.py`. No screen hardcodes `pad=13`
— must be a token or multiple of 4.

**Responsive:**
- 1920×1080+ → everything expanded
- 1440×900 → everything expanded (1232px content)
- 1280×720 (min supported) → sidebar auto-collapses to 56px, grid
  reduces to 8-col with 16px gutters
- Below 1280×720 → NOT SUPPORTED, shows "please resize" placeholder

**Window chrome:** ship with OS title bar first. Borderless mode
(`overrideredirect(True)`) ships later as a Settings toggle (off by
default) — it's brittle on Linux.

### 4.10 Component library — 15 components

Every screen is built from these. No screen rolls its own bespoke
widget.

1. **Card** (Flat / Elevated / Accent) — base surface
2. **SectionHeader** — title + gold left-accent bar + right metadata
3. **DataChip** — status pill (Default / Champion / Danger / Info)
4. **StatBar** — horizontal voice-encoded attribute bar (7 tiers, NOT
   raw 0-100 numbers)
5. **FighterRow** — one row in a FighterTable (36px height, gold-tint
   hover, 2px gold left border on selected, champion/injured/streak
   variants)
6. **NewsCard** — topic badge + headline + body + date
7. **WatchCard** — Dashboard Fighter Watch card (Accent variant, 64px
   portrait, voice phrase, context line)
8. **PortraitFrame** — Hero (256×320) / Watch (64×80) / Row (28×36) /
   Mini (20×25). Gold border if champion, dashed if scouted
9. **HyperlinkLabel** — gold text, gold_bright hover, 1px underline
   on hover
10. **Button** — Primary (gold) / Secondary (outline) / Danger (crimson)
    / Ghost. At most 1 Primary per screen.
11. **TabBar** — sub-navigation within a screen (gold bottom border on
    active tab)
12. **CalendarStrip** — horizontal scrollable date strip for Schedule
13. **Breadcrumb** — "The Stable / John Vale" trail
14. **EmptyState** — personality, not "No data" (each screen gets a
    unique voice-phrased empty state)
15. **ModalDialog** — confirmations (sign/cut actions), 8px radius,
    slide-in 150ms

Full visual spec + states + voice/type per component: see
`UI_REDESIGN_VISUAL_PLAN.md` §5.

**Coverage validation:** Appendix B of the visual plan confirms all 22
screens are covered by these 15 components without needing a 16th
bespoke widget.

---

## 5. Interpretation Layer Integration (NEW)

> Detailed audit: `docs/UI_REDESIGN_INTERPRETATION_AUDIT.md`. This
> section is the strategic summary.

### 5.1 The problem

The user said: "I think [the interpretation layer] lacks variety as
many repeats are seen in game." The audit confirmed this is true, and
identified THREE root causes:

1. **The "8 variants per label" claim was misleading.** The `_EXT`
   8-variant banks exist for `momentum`, `pressure`, `trajectory`, and
   `career_phase` — but NOT for `narrative_families` (3 variants),
   `legacy_engine` (3 variants), `headline_engine` (1 per family), or
   `voice.py` attribute descriptors (2-3 per tier).
2. **The 8-variant banks NEVER reached the production DB.** When the
   `_EXT` pickers were added, `snapshot_cache.ENGINE_VERSION` was NOT
   bumped. The version-mismatch rebuild logic never triggered. The
   cache is stale — `last_built_date='2026-07-20'`, 8+ days old.
3. **Even with 8 variants, repetition is severe** because label rules
   are heavily skewed: 98.3% of fighters are `momentum='stable'`,
   93.1% `pressure='moderate'`, 75.9% `career_phase='rising_contender'`,
   99.5% `legacy_state='building'`. ~547 fighters per phrase for the
   heaviest bucket.

### 5.2 The fix — phased

| Priority | Change | Effort | Impact |
|---|---|---|---|
| **P0** | Bump `ENGINE_VERSION` from `"1.5.0"` to `"1.6.0"` (or `"2.0.0"`) to force cache rebuild with existing `_EXT` pickers | 1 line of code | Cuts perceived repetition ~60% for momentum/pressure/career_phase |
| **P0** | Add `_EXT` 8-variant banks for `narrative_families` + `legacy_engine` (matching the context_engine pattern) | ~200 lines | Brings those 2 modules up to 8 variants |
| **P1** | Add SHORT vs LONG variant split + per-screen picker. 12 new columns on `fighter_descriptors` (`*_short` + `*_long` per interpretation column) | ~500 lines + ~440 new phrases | Eliminates Roster "every row reads the same" problem; gives Profile depth |
| **P1** | Expand `headline_engine` from 1 to 8 variants per (type, family) | ~300 lines + ~256 new phrases | Eliminates "30 days of identical headlines" |
| **P2** | Move phrase banks to new `interpretation_phrases` DB table (so editors can add variants without code changes) | ~400 lines + migration script | Content editors can tune without code changes |
| **P2** | Expand `voice.py` attribute descriptors from 2-3 to 5-10 per tier | ~1,200 new phrases | Cuts attribute descriptor repetition ~60% |
| **P3** | Add conditional triggers (career phase, recent fight, title holder) | ~200 lines | Layered voice — champion reads differently from prospect |
| **P3** | Add more narrative_family archetypes (10 candidates documented) | ~500 lines + phrases | Cuts the 99.3% NULL rate to ~50% |

### 5.3 Variety selection algorithm

Replace the current `rng = random.Random(fighter_id * 31 + 17)` with:

1. **Per-fighter-per-week deterministic hash** (MD5 of
   `fighter_id|label|tick_bucket`) — same fighter, same week, same
   phrase. Next week, different phrase (if bank has > 1 variant).
2. **Screen-context-aware bank selection** — table cells get SHORT
   bank, profile gets LONG bank.
3. **No-repeat-within-N cache** — per-screen-render in-memory cache
   tracking last N=3 phrases shown, advances to next variant if the
   picked phrase is in the cache.
4. **Conditional overrides** — career phase, recent fight outcome,
   title holder status can override the default bank selection (e.g.,
   a champion always gets the LONG legacy phrase).

### 5.4 Where each variant length is used

| Variant length | Where used | Why |
|---|---|---|
| **SHORT** (2-4 words) | FighterRow Stage/Form cells, DataChip status, CalendarStrip event labels | Compact — fits in 140-200px column widths |
| **MEDIUM** (5-8 words) | NewsCard headline, Dashboard Top Story headline, WatchCard voice phrase | Reads at a glance — 1 line max |
| **LONG** (8-15 words) | Fighter Profile identity strip, NewsCard body, WatchCard context line, Fight Night commentary, Hall of Fame epitaph, Rivalry narrative | Reads as prose — 2-3 lines |

### 5.5 Schema impact

- **P0:** No schema change (just ENGINE_VERSION bump).
- **P1:** 12 new TEXT columns on `fighter_descriptors`
  (`momentum_short`, `momentum_long`, `pressure_short`, `pressure_long`,
  `career_phase_short`, `career_phase_long`, `narrative_family_short`,
  `narrative_family_long`, `legacy_state_short`, `legacy_state_long`,
  `trajectory_short`, `trajectory_long`). Each stores `"label||phrase"`.
  Existing columns kept for backward compat. ~10 MB additional cache.
- **P2:** 1 new table `interpretation_phrases` (~2,000 rows, ~200 KB).
  Schema: `(phrase_id, engine, column_name, label, length, phrase_text,
  weight, is_active, created_at, updated_at)`.

### 5.6 Hard prerequisite for the redesign

The visual redesign's StatBar tooltips, NewsCard bodies, and WatchCard
context lines all assume LONG variants exist. The audit's P0 fix
(ENGINE_VERSION bump) must land BEFORE the visual redesign — otherwise
the redesign will surface the same 3-variant repetition the audit
identified.

**Recommended sequence:**
1. P0 interpretation fix (1 line, ships immediately, takes effect on
   next Advance Day)
2. Phase 1 visual redesign (theme + fonts, 2-3 days)
3. P1 interpretation short/long split (parallel to Phase 2-3 visual
   work, ~1 week)
4. Phase 4-6 visual redesign (Dashboard, Roster+Free Agents, Fighter
   Profile)

---

## 6. Ground-Up Redesign of the 4 Existing Screens

> Detailed wireframes + specs: `docs/UI_REDESIGN_VISUAL_PLAN.md` §6.
> This section is the strategic summary.

Each of the 4 existing screens gets a ground-up redesign using the new
component library (§4.10) + 12-col grid system (§4.9). The redesigns
are NOT incremental patches — they are full rewrites that replace the
current implementations.

### 6.1 Dashboard ("The Empire")

**6 visible sections above the fold at 1920×1080:**

1. **Top Story** — Card/Accent (gold border, 12-col). LONG voice
   variant headline + 2-line body. Topic chips. "Read full story"
   hyperlink. Source: `daily_headlines` `top_story` row.
2. **Promotion Status** — Card/Flat (6-col). 5 rows: Cash (with 7-day
   sparkline — the screen's data viz), Reputation (voice band), Fan
   Trust (voice band), Roster count, Champions count.
3. **Next Event** — Card/Flat (6-col). Event date + name + main event
   + title fight indicator. Buttons: "Build Card" (Primary) +
   "Matchmaking" (Secondary).
4. **Fighter Watch** — 3 WatchCards (4-col each, Accent variant). Top
   Prospect (gold accent), Hottest Streak (gold accent), Biggest Fall
   (crimson accent). 64px portrait + LONG voice phrase + context line.
5. **Champions** — horizontal strip of champion chips (DataChip +
   HyperlinkLabel). 8 max (one per WC).
6. **Recent News** — vertical list of NewsCards (12-col each). Last 5
   items.

**Dopamine hooks:**
- Top Story headline changes daily (LONG variant = different headline
  for same fighter 3 days running)
- Fighter Watch cards update with new fighters
- Cash sparkline grows (Empire Builder)
- Champions strip updates on title changes
- Next Event countdown

### 6.2 Roster ("The Stable")

**Layout:** SectionHeader + filter row (12-col) + table card (12-col,
sharp corners — "ledger" feel) + weight class distribution viz (12-col).

**Columns:** Active dot (gold/crimson/neutral) · Name (hyperlink, gold)
· Age (mono) · WC (mono, uppercase) · Stage (SHORT career_phase variant,
italic) · Form (SHORT momentum variant, italic) · Record (mono "W-L-D")
· Gym (text) · Nat (3-letter code).

**Filter row:** WC dropdown · Gender dropdown · Stage dropdown · Search
entry (200px, 200ms debounce — already shipped in Phase 4) · Clear
button (×, ghost).

**Pagination:** 20 rows/page. Bottom-right. "Showing 1-20 of 1,002"
+ prev ◀ + numbered pages (current ±2, ellipsis for gaps) + next ▶.
Current page = gold bg.

**Row interactions:** Hover = `gold_tint` bg. Single click = select
(gold left border). Double click = navigate to Fighter Profile. Right
click = context menu (P1: Sign / View Profile / Add to Watchlist /
Add to Card).

**Data viz:** Weight Class Distribution — horizontal bar chart, 12-col,
one bar per WC sorted by display_order. Bar fill = `gold` for player's
promo. This satisfies the "every screen has ≥1 data viz" rule.

**Empty states:** "No fighters match your filters" (with Clear Filters
CTA) when filter returns 0; "Your stable is empty" (with Browse Open
Market CTA) when literal 0 fighters.

### 6.3 Fighter Profile (the most complex screen)

**Layout:** Header card (Accent, 12-col) + TabBar (6 tabs) + tab
content.

**Header card:** 256×320 Hero portrait (gold border if champion, with
gold-leaf texture overlay) + name + nickname + age + WC + promo + gym +
identity strip (Career Phase / Momentum / Pressure / Narrative /
Legacy / Trajectory — all LONG variants) + action buttons (Cut Fighter
if on roster, Offer Extension if expiring, Book Next Fight, Scout if
not on roster).

**6 tabs:**
1. **Overview** (default): Bio (8-col) + Career stats (4-col) + Recent
   Fights timeline (12-col)
2. **Attributes**: 26 StatBars (2 columns of 13). Top 6 shown by
   default with "Show all 26" toggle.
3. **Personality**: 20 StatBars (2 columns of 10).
4. **Career**: Full fight history (table) + title reigns timeline +
   career arc visualization (P1).
5. **Fights**: Same as Overview's Recent Fights but full history.
6. **News**: NewsCards mentioning this fighter (P1 future — needs
   `news_items` filter by fighter_id).

**Recent Fights = TIMELINE, not table.** Vertical, with W/L badge
(gold W or crimson L, 24×24) + opponent hyperlink + method caption +
round/time (mono_small) + title fight chip + replay link (▶ ghost).

**Why timeline not table:** A table treats all fights as equal. A
timeline shows progression — the player can see the win streak, the
loss that broke it, the title fight that capped it. This serves the
Historian fantasy.

**Attribute visualization = StatBars, NOT radar.** A radar chart shows
all attributes at once but at low resolution (each axis is a thin
sliver). For a game where the player needs to *read* each attribute's
voice phrase, the StatBar grid is better. Radar is a P2 "nice to have"
thumbnail for the Overview tab.

**Scouting report** (for fighters NOT on player's promotion): Card/Flat
below the header card. Scout's name + report date + voice-phrased notes
(hedged register: "reportedly shows", "could develop into"). If no
report: EmptyState "No scouting report on file. Send a scout to gather
intel."

**Memory links** (P1 future): "Fighter History" card below Recent
Fights. Past rivalries (crimson "BAD BLOOD" chip + hyperlink to rival)
+ common opponents (3-5 fighters with W/L record vs each) + gym
history. This is the Soul doc's "the player collects stories" made
literal — every fighter is a node in a story graph.

### 6.4 Free Agents ("Open Market")

**Layout:** SectionHeader + filter row + table card + sticky sign bar
(12-col, bottom of viewport) + ceiling distribution viz (12-col).

**Differs from Roster in 4 ways:**

1. **Ceiling column** instead of Form column. Ceiling = scouted
   projection of peak potential. Voice phrase ("Elite", "High",
   "Above-Avg", "Avg", "Below-Avg", "Low", "Unknown"). For unscouted
   fighters: "????" (4 question marks in mono) — WMMA5-style
   information asymmetry the Soul doc endorses.
2. **Estimated cost** in the sticky sign bar. When a fighter is
   selected, sign bar shows projected signing cost (based on ceiling,
   age, momentum, market). This is the Empire Builder dopamine — "can
   I afford this kid?"
3. **No active dot** in the row (these aren't your fighters).
4. **Sticky sign bar** at the bottom. Shows selected fighter + estimated
   cost + Sign button (Primary). Makes the signing action feel weighty.

**Sign flow:**
1. Click row → row selected, sign bar updates with fighter details +
   estimated cost
2. Click "Sign for $X" → ModalDialog opens with contract details
3. On confirm: `services.contracts.sign_free_agent(conn, fighter_id,
   promotion_id, start_date)` called. Modal closes. NewsCard generated.

**Data viz:** Talent Pool by Ceiling — horizontal bar chart, 12-col,
one bar per ceiling tier. Bar fill = `gold` for elite/high (desirable),
`bg_card_elevated` for avg/below (filler), `text_tertiary` for unknown.
Visualizes the *quality* of the current market — "is this a good time
to sign?"

---

## 7. Theming Plan for All Other Screens (18 screens)

> Detailed specs: `docs/UI_REDESIGN_VISUAL_PLAN.md` §7. This section
> is the strategic summary.

Each of the 18 not-yet-built screens inherits the design system from
§4 + uses the component library from §4.10. Each gets: purpose (1
sentence), primary layout, key components, voice guidance, data
visualization, navigation entry.

### 7.1 Fight Resolution (THE Fight Night screen — preserved from Rev 2 §4)

**Status:** Vision preserved. Implementation pending Phase 7+.

The single biggest visual moment in the game. Must outdo WMMA5.

**Design goal:** "HBO 24/7 meets a live ESPN broadcast, narrated by
documentary-grade prose, with pundits who argue, memories that
resurface at the perfect moment, and a cage heatmap that shows you
exactly where the fight was won."

**3-phase structure:**
1. **Pre-Fight Build-Up** (~15-30s at 1x): Tale of Tape, Pundit
   Predictions, Memory Setup, Storyline Context
2. **Live Fight** (variable, 2-10min at 1x): 4 live zones
   - Zone A: Cage Heatmap (Canvas widget, top-down octagon, heat
     accumulates per beat)
   - Zone B: Fighter Damage Silhouettes (Canvas ×2, head/body/legs/
     arms glow on impact, persists as bruising)
   - Zone C: Commentary Feed (scrollable, serif typography, beat
     timestamp + action prose + pundit interjection + memory bubble)
   - Zone D: Pundit Panel (right rail, 2-3 named pundits, mood
     indicator, last interjection summary)
3. **Post-Fight Recap** (~20-40s at 1x): Result card, Pundit grades,
   Final heatmap (annotated with decisive moments), Final damage
   silhouettes (with medical suspension indicator), Memory creation,
   News generation, Storyline hooks

**Championship Skin overlay** (§4.4): activates on `fights.is_title_fight
= 1`. Gold-leaf heatmap border, champion/challenger corner colors, belt
graphic, "TITLE FIGHT" badge.

**Performance budget:** 60fps on mid-range laptop. Heatmap redraw =
changed zones only. Damage silhouettes = pre-rendered sprite sheets.
Commentary feed = append-only, cap visible beats at 200. Pundit
interjections = pre-generated at fight resolution time, stored in
`commentary_segments`, revealed in sequence.

### 7.2 Other 17 screens — summary

| Screen | Purpose | Layout | Data viz |
|---|---|---|---|
| Schedule ("Calendar") | Calendar of all scheduled events | CalendarStrip + day-detail panel + upcoming list | Calendar dots + 30-day density sparkline |
| News Feed ("The Wire") | Chronological news with filters | Filter row + vertical NewsCards (infinite scroll) | Topic-distribution bar |
| Scouting | Scout assignments, hidden-potential reports | Scout panel (4-col) + targets table (8-col) | Active-scouts-per-region bar |
| Hall of Fame ("Legends") | Inductees by year, compare mode | Year selector + inductee grid (3-col Hero cards) | Inductee timeline |
| Event Builder ("Build a Card") | Schedule event, build card of 5-13 fights | 3-panel split (config / builder / projection) | Card-strength meter + buyrate projection sparkline |
| Matchmaking | Pick two fighters → tale-of-tape + analysis | 3-column split (Red corner / analysis / Blue corner) | Tale-of-tape dual StatBars + win probability bar |
| Past Events ("The Archive") | Historical events with results, replays | TabBar (List/Calendar) + event detail | Attendance/buyrate trend sparkline |
| Finance ("The Books") | Income, expenses, forecast | TabBar (Income/Expenses/Forecast) + summary + transactions | 30-day cash flow + 90-day forecast + expense donut |
| Contracts ("Deals") | Active contracts, expiring, negotiation | Filter row + contract table | 90-day expiration timeline + payroll bar |
| Rival Promotions ("The Competition") | Other promos' rosters, champions, prestige | Promo selector + selected promo detail | Prestige comparison bar + roster-by-WC stacked bar |
| Gyms ("Training Camps") | Gyms, their fighters, camp scheduling | Gym selector (4-col) + gym detail (8-col) | Gym prestige bar + 12-week camp Gantt (P1) |
| Rankings ("The Rankings") | Divisional rankings, rank movement | WC selector + ranked fighter list | Rank-movement sparkline per fighter |
| Titles ("Belts") | All belts, current champions, reign lengths, history | Belt grid (12-col, 2-3 columns) | Title-history timeline + longest-reigning leaderboard |
| Rivalries ("Bad Blood") | Active rivalries, history, heat level | Rivalry list (4-col) + rivalry detail (8-col) | Heat-level meter + rivalry fight timeline |
| Records ("The Record Book") | All-time leaders: KOs, subs, defenses, reigns | Category selector + record table | Record progression sparkline (P1) |
| Settings | Game options | TabBar (Display/Audio/Gameplay/Mods) | n/a |
| Save/Load | Multiple save slots, autosave config | Save slot grid + actions | n/a |
| Mods | Load/manage mod packs | Mod list + actions | n/a |

Full per-screen specs (purpose, layout, components, voice guidance, data
viz, nav entry): see `UI_REDESIGN_VISUAL_PLAN.md` §7.

---

## 8. Asset Inventory (REVISED)

> Detailed list: `docs/UI_REDESIGN_VISUAL_PLAN.md` §8. This section
> is the strategic summary.

### 8.1 Current state

| Asset type | Current count | Status |
|---|---|---|
| Promo logos | 10 | ✅ Generated. OK for launch. |
| Fighter portraits | 1 (placeholder) | ❌ Need many more. P0 = 1 default, P1 = procedural, P2 = AI-gen. |
| Fonts | 9 (Inter×4, JetBrains Mono×1, Source Serif Pro×4) | ❌ Missing Oswald (display). |
| Logo variants | 2 (primary + compact) | ❌ Need 6 more (mark, wordmark, fight night, championship, favicon, monochrome). |
| Icons | 0 (paths only — empty files) | ❌ **P0 BLOCKER.** STATUS_ICONS + NAV_ICONS point at empty files. |
| Backgrounds / textures | 0 | ❌ All proposed textures unbuilt. |
| Pundit avatars | 0 | P2 (procedural). |
| Memory bubble textures | 0 | P1. |
| Belt graphics | 0 | P1. |
| Cage heatmap base | 0 | P1. |
| Damage silhouettes | 0 | P1. |

### 8.2 Revised asset list — priority tiers

**P0 = must-have for redesign launch. P1 = ship 2-4 weeks after. P2 =
future.**

#### P0 — 43 new files

| Asset | Count | Method | Effort |
|---|---|---|---|
| Nav icons (14) | 14 PNG + 14 SVG = 28 files | Commission or AI image-gen (Lucide/Phosphor outlined style, 2px stroke, single-color `gold`) | 2-3 days |
| Status icons (8) | 8 PNG + 8 SVG = 16 files | Same style as nav | (included above) |
| Topic icons (10) | 10 PNG + 10 SVG = 20 files | For news topics: SIGNING, INJURY, RESULT, RIVALRY, RUMOR, RETIREMENT, TITLE, SUSPENSION, DEBUT, COMEBACK | (included above) |
| Logo variants (6 new) | 6 PNG | Image-gen from supervisor-final source: mark (32×32), wordmark (200×40), fight night variant, championship variant, favicon (16/32/64), monochrome | 1 day |
| Oswald Bold font | 1 TTF | Download from Google Fonts (OFL, free, ~120 KB) | 5 minutes |
| Textures (4) | 4 PNG | Procedural via PIL: `noise_grain.png`, `chain_link_dim.png`, `gold_leaf_border.png`, `vignette_fight_night.png` | 1 day |

**P0 total: 43 new files. ~3-5 days of focused asset work.**

#### P1 — 28 new files (+ ~4500 generated)

| Asset | Count | Method | Effort |
|---|---|---|---|
| Initials-based portraits | 1 script, generates ~4500 PNGs | Procedural via PIL: gradient bg (WC-tinted), 2-letter initials in Oswald Bold 96px white, gold-leaf border if champion | 1 day for script, ~30s to generate all 4500 |
| Cage heatmap base texture | 1 PNG (1024×1024) | AI image-gen | 1 day |
| Damage silhouette sprite sheets | 2 PNG (512×512) | AI image-gen | 1 day |
| Round transition overlay | 1 PNG (1920×1080) | Image-gen or PIL | 0.5 day |
| Knockdown flash overlay | 1 PNG (1920×1080) | PIL (single-frame crimson flash) | 0.5 day |
| Finish banner | 1 PNG (1920×400) | Image-gen or PIL | 0.5 day |
| Pundit avatar dot template | 1 PNG (64×64) | Procedural via PIL | 0.5 day |
| Memory bubble textures (4 tints) | 4 PNG (256×256) | Procedural via PIL | 0.5 day |
| Belt graphics (8 WCs × front+side) | 16 PNG (512×256) | AI image-gen or commission | 2-3 days |

**P1 total: 28 files + ~4500 generated. ~5-7 days of asset work.**

#### P2 — 12+ files

| Asset | Count | Method |
|---|---|---|
| Pundit avatars (12 colored circles with initials) | 12 PNG (64×64) | Procedural via PIL |
| Future assets TBD | — | — |

### 8.3 Total asset count

| Tier | Count | Cumulative |
|---|---|---|
| Current | ~110 files | 110 |
| P0 (redesign launch) | +43 files | 153 |
| P1 (post-launch) | +28 files (+ ~4500 generated) | 181 (+ 4500) |
| P2 (future) | +12+ files | 193+ |

**Generation method summary:**

| Asset type | Method | Effort |
|---|---|---|
| Icons (P0) | Commission or AI image-gen | 2-3 days |
| Logo variants (P0) | Image-gen from existing source | 1 day |
| Oswald font (P0) | Download (free, OFL) | 5 minutes |
| Textures (P0) | Procedural via PIL | 1 day |
| Portraits (P1) | Procedural via PIL script | 1 day |
| Fight Night assets (P1) | AI image-gen | 3-4 days |
| Belts (P1) | AI image-gen or commission | 2-3 days |
| Pundit avatars (P2) | Procedural via PIL | 0.5 day |

**Estimated total asset effort:** ~2-3 weeks of focused work, parallel
to the code work in §10.

---

## 9. Implementation Sequencing (REVISED)

> Detailed phase plan: `docs/UI_REDESIGN_VISUAL_PLAN.md` §9. This
> section is the strategic summary.

### 9.1 Phase plan — 7 phases

**Phase 0: P0 Interpretation Fix (Effort: S, 1 hour)**

- Bump `snapshot_cache.ENGINE_VERSION` from `"1.5.0"` to `"1.6.0"`
- Forces cache rebuild on next Advance Day
- Cuts perceived repetition ~60% for momentum/pressure/career_phase
- **Dependencies:** None.
- **Shippable:** Immediate — players see variety improvement on next
  Advance Day.
- **Risk:** None. Single-line change, no schema impact.

**Phase 1: Theme + Font Bundle (Effort: S, 2-3 days)**

- Rewrite `theme.py` with 4-tier color system, 3 card variants, new
  font registration (unique family names per weight), Oswald bundling,
  spacing tokens, texture-loading utilities (PIL-based, cached)
- Add startup health check that logs resolved font families
- **Dependencies:** None (Phase 0 can ship in parallel).
- **Shippable:** New theme applies to existing screens immediately —
  they look better even without structural changes.
- **Risk:** Font registration changes could break existing tests.
  Mitigation: run test suite after change, fix failures before merge.

**Phase 2: Component Library (Effort: M, 5-7 days)**

- Build all 15 components in `src/ui/widgets/components/` as a new
  package
- Each component is a standalone CTkFrame subclass with its own test
- **Dependencies:** Phase 1 (theme).
- **Shippable:** Components exist but aren't used by any screen yet.
  No visual change for the player. This is the foundation.
- **Risk:** Component API design. Mitigation: design APIs in
  `UI_REDESIGN_VISUAL_PLAN.md` §5 first, get supervisor sign-off,
  then build.

**Phase 3: App Shell Rewrite (Effort: M, 4-5 days)**

- Rewrite `app.py` shell: new top bar (56px, 3 zones), new sidebar
  (56px collapsed / 220px expanded, icon+label, pin toggle), remove
  bottom bar
- Bundle the 14 nav icons (P0 from §8)
- Borderless window mode ships later (Settings toggle, off by default)
- **Dependencies:** Phase 1 (theme) + Phase 2 (components: Button,
  HyperlinkLabel).
- **Shippable:** New shell looks dramatically better. Existing screens
  render inside it.
- **Risk:** Sidebar collapse-on-hover could feel janky. Mitigation:
  default to expanded, only collapse if player explicitly pins it.

**Phase 4: Dashboard Redesign (Effort: M, 4-5 days)**

- Rewrite `dashboard.py` using new components + grid system
- Build the 6 sections per §6.1
- Add the cash sparkline (P0 data viz)
- **Dependencies:** Phase 2 (components) + Phase 3 (shell).
- **Shippable:** Dashboard is the first screen to fully adopt the new
  design. Player sees the new look immediately on launch.
- **Risk:** Section density — too many cards could feel cramped. Target
  6 visible sections above the fold at 1920×1080.

**Phase 5: Roster + Free Agents Redesign (Effort: L, 6-8 days — HIGHEST RISK)**

- Rewrite `fighter_table.py` as new `FighterTableV2` (behind feature
  flag — old widget stays until new one is proven)
- Rewrite `roster.py` and `free_agents.py` using FighterTableV2 + new
  components + grid system
- Add weight class distribution viz (Roster) + ceiling distribution
  viz (Free Agents)
- Add sticky sign bar (Free Agents)
- **Dependencies:** Phase 2 (components) + Phase 3 (shell) + Phase 4
  (proves the redesign pattern on a simpler screen).
- **Shippable:** Both table-based screens adopt the new design.
- **Risk:** **HIGHEST RISK.** FighterTable is used by 2 live screens +
  4 future screens. Breaking it breaks everything. Mitigation: build
  V2 in parallel, ship behind `USE_FIGHTER_TABLE_V2 = True/False` flag,
  flip per screen during testing, remove old widget only after both
  screens ship V2 + tested for a week.

**Phase 6: Fighter Profile Redesign (Effort: L, 7-9 days)**

- Rewrite `fighter_profile.py` using new components + grid system
- Build the 6-tab TabBar
- Build StatBar-based attribute + personality grids
- Build recent fights timeline
- Build champion-variant PortraitFrame with gold-leaf border
- **Dependencies:** Phase 2 (components) + Phase 3 (shell) + Phase 5
  (proves the complex-screen pattern).
- **Shippable:** The most complex screen adopts the new design. All 4
  existing screens now redesigned.
- **Risk:** Tab content loading — switching tabs should be instant.
  Mitigation: pre-render all tab contents on screen load, hide/show
  via `pack_forget` / `pack`.

**Phase 7+: Other 18 screens (Effort: ~6-8 weeks, out of scope for this redesign)**

- Build per the specs in §7. Each screen follows the same pattern:
  Phase 2 components + Phase 3 shell + per-screen layout.
- Effort: S-M per screen, depending on complexity.
- **Out of scope for this redesign.** This plan's scope is the 4
  existing screens + the theming system that the other 18 will follow.

### 9.2 Total estimated effort

| Phase | Effort | Days |
|---|---|---|
| 0. P0 Interpretation Fix | S | 1 hour |
| 1. Theme + Fonts | S | 2-3 |
| 2. Component Library | M | 5-7 |
| 3. App Shell | M | 4-5 |
| 4. Dashboard | M | 4-5 |
| 5. Roster + Free Agents | L | 6-8 |
| 6. Fighter Profile | L | 7-9 |
| **Total (Phases 0-6)** | | **28-37 days (~6-8 weeks of focused work)** |

Asset work (§8) runs in parallel — ~2-3 weeks of focused asset work,
overlapping Phases 1-3.

### 9.3 Riskiest changes

1. **FighterTable rewrite (Phase 5).** Used by 2 live screens + 4
   future screens. Mitigation: feature flag, parallel V2, gradual
   rollout.
2. **Font registration changes (Phase 1).** Silently failing currently.
   Fixing it could change every screen's appearance simultaneously.
   Mitigation: log resolved families, test on Win/Mac/Linux before
   merge.
3. **Borderless window mode (Phase 3, P1).** `overrideredirect(True)`
   is brittle on Linux. Mitigation: ship with OS title bar first,
   add borderless as Settings toggle (off by default) in polish phase.
4. **Fight Night screen (Phase 7+, post-redesign).** Biggest single
   screen. 4 zones, beat-synced, 60fps target. Per §7.1, performance
   budget is tight. Mitigation: build incrementally — 7a = pre-fight
   build-up only, 7b = live fight with heatmap only, 7c = add damage
   silhouettes, 7d = add pundit panel + memory bubble.
5. **Voice phrase variety (cross-cutting).** Audit doc found severe
   phrase repetition. The redesign can't fix this alone — the
   interpretation layer needs the proposed short/long variant system.
   Mitigation: Phase 0 P0 fix lands first; the redesign's StatBar
   tooltips + WatchCard voice phrases rely on LONG variants existing.

---

## 10. Voice + Styling Guidance (NEW — meticulous detail per user request)

This section provides the explicit voice + styling rules the supervisor
asked for. Every screen, every component, every text element.

### 10.1 Voice register — 5 registers, used consistently

| Register | When | Example | Typography |
|---|---|---|---|
| **Statboard** | Numeric values, dates, records | "$50.0M", "18-5-0", "Mon 14 Sep 2026" | `mono` (JetBrains Mono) |
| **UI label** | Nav items, column headers, button labels | "The Stable", "Sign Fighter", "AGE" | `body_small` (sentence case) or `caption` (UPPERCASE + tracked) |
| **Voice phrase (short)** | Table cells, chips, compact cards | "rising contender", "holding steady" | `descriptor_small` (Inter Italic 12px) |
| **Voice phrase (long)** | Profile prose, news body, commentary | "A rising contender climbing the ranks with the division on notice..." | `descriptor` (Inter Italic 14px) or `commentary_fight` (Source Serif Pro 17px) |
| **Pundit** | Named interjections on Fight Night | "That's the third body shot in 90 seconds." | `pundit` (Source Serif Pro SemiBold Italic 14px) |

**The rule:** a player should never confuse "18-5-0" (statboard) with
"carries real knockout power" (voice phrase). The typography makes the
distinction visible at a glance.

### 10.2 Voice phrases — CAGE EMPIRE voice characteristics

The Soul doc reference phrases:
- "That kid I found in Mexico. Nobody wanted him. He became a champion."
- "His best years may be behind him."
- "the wunderkind everyone's talking about"

**Characteristics of the CAGE EMPIRE voice:**

1. **Promoter-flavored, not journalist-neutral.** "The matchmakers
   can't ignore him anymore" beats "He is highly ranked."
2. **Past-tense narrative, not present-tense report.** "He's found
   the version of himself the division was always afraid of" beats
   "He is fighting well."
3. **Specific imagery, not generic praise.** "Scorching the earth on
   the way to a title shot" beats "On a winning streak."
4. **Hedged uncertainty for scouting.** "Reportedly shows", "could
   develop into", "the scouts are whispering" — incomplete info is
   the feature, not the bug.
5. **Dramatic register for rivalries + Fight Night.** "Bad blood
   brewing", "the division on notice", "the kind of run that defines
   a career."
6. **Elegiac register for legends + declining fighters.** "His best
   years may be behind him", "the long goodbye", "father time is
   winning."

**Forbidden patterns:**
- Generic sports-page clichés without specificity ("riding a hot
  streak" alone — needs the "on the way to a title shot" qualifier)
- Raw attribute numbers in player-facing UI (CONVENTIONS §14)
- Generic empty states ("No data found", "Loading...")
- System-font typography for voice phrases (must be italic Inter or
  serif Source Serif Pro)

### 10.3 Button + nav guidance

**Buttons:**

| Variant | When | Color | Max per screen |
|---|---|---|---|
| Primary (gold) | The single most important action on a screen | `gold` bg, `text_on_gold` text | 1 |
| Secondary (outline) | Alternative actions | transparent bg, `border_subtle` 1px, `text_primary` text | unlimited |
| Danger (crimson) | Destructive actions (Cut Fighter, Cancel Event) | `crimson` bg, `text_on_crimson` text | 1 per destructive action |
| Ghost | Tertiary actions (Cancel in modal, Dismiss on card) | transparent bg, `text_secondary` text | unlimited |

**Rule:** A screen should have AT MOST ONE Primary button visible at a
time. Multiple primaries compete for attention and dilute the call to
action.

**Nav:**

| Element | Style | Behavior |
|---|---|---|
| Sidebar item (default) | `body_small` (Inter 13px), `text_secondary`, icon 20×20 outlined | Hover → `gold_tint` bg + `text_primary` |
| Sidebar item (active) | `body_small` Bold, `text_primary`, `gold_tint` bg, 3px gold left border | Stays active until navigation |
| Sidebar group label | `caption` (Inter 11px UPPERCASE +0.04em), `text_tertiary` | Not clickable |
| Top-bar kebab (⚙) | Ghost button, 24×24 | Opens dropdown: Save / Settings / Mods |
| Breadcrumb segment | `body_small`, `text_secondary` | Hover → `text_primary` + gold underline. Last segment = Bold, not clickable. |

**Voice renames (preserved from UI Fix Plan 2 Phase 3):**

| Screen name (key) | Display name | Voice rationale |
|---|---|---|
| dashboard | The Empire | "Empire" reinforces the Empire Builder fantasy |
| roster | The Stable | "Stable" = horse-racing term for a fighter roster |
| free_agents | Open Market | "Open Market" = the signing pool |
| scouting | Scouting | (unchanged — already correct) |
| fighter_profile | (hidden from sidebar — accessible via hyperlinks) | "Fighter Profile" is a destination, not a starting point |
| hall_of_fame | Legends | "Legends" = the Historian fantasy |
| event_builder | Build a Card | "Build a Card" = promoter action verb |
| matchmaking | Matchmaking | (unchanged) |
| fight_resolution | Fight Night | "Fight Night" = the visceral moment |
| past_events | The Archive | "Archive" = the Historian's records |
| finance | The Books | "Books" = promoter slang for finances |
| contracts | Deals | "Deals" = the negotiation table |
| rival_promotions | The Competition | "Competition" = the Empire Builder's rivals |
| gyms | Training Camps | "Training Camps" = the Investment/Growth pillars |
| rankings | The Rankings | (unchanged) |
| titles | Belts | "Belts" = the Kingmaker's prize |
| rivalries | Bad Blood | "Bad Blood" = the Puppet Master's conflict |
| records | The Record Book | "Record Book" = the Historian's archive |
| settings | Settings | (unchanged — utility) |
| save_load | Save / Load | (unchanged — utility) |
| mods | Mods | (unchanged — utility) |

### 10.4 Empty state voice phrases (per screen)

Each screen gets a UNIQUE empty-state voice phrase. The "No data"
pattern is banned.

| Screen | Empty-state headline | Empty-state body |
|---|---|---|
| Dashboard news | "The newswire is quiet." | "No stories have broken in the last 24 hours. Advance a day to see what develops." |
| Roster | "Your stable is empty." | "Sign fighters from the Open Market to fill out your roster." |
| Free Agents | "The market is quiet." | "No unsigned fighters match your filters. Try widening your search." |
| Fighter Watch | "No one's making moves today." | "The divisions are resting. Check back after the next event." |
| Past Events | "No events in the archive yet." | "Once you run your first card, it'll show up here." |
| Hall of Fame | "No legends yet." | "Retirees with distinguished careers will be inducted here." |
| Rivalries | "No bad blood brewing." | "Rivalries develop over time as fighters meet repeatedly." |
| Schedule | "No events scheduled." | "Build a card to give the fans something to remember." |
| Matchmaking | "Pick two fighters." | "Select a fighter from each corner to see the tale of the tape." |
| Scouting | "No scouts assigned." | "Assign a scout to a region to start uncovering hidden talent." |

---

## 11. Open Questions for the Supervisor (12 questions)

> The supervisor must mark decisions on these 12 questions before
> Phase 1 code work begins. Each question has 2-4 options with the
> recommended option marked **[RECOMMENDED]**.
>
> Detailed option rationales: `docs/UI_REDESIGN_VISUAL_PLAN.md` §10.

### Visual decisions (6 questions)

**Q1. Sidebar collapse behavior**
- A. 220px text+label always (current). Simple, but VLM says too wide.
- B. 56px icon-only always. Maximum content space, but labels hidden.
- C. 56px collapsed (default) + 220px on hover, pin to keep expanded. **[RECOMMENDED]** — VS Code/Linear pattern, gives players both modes.
- D. Auto-collapse based on window size (collapse below 1280px width).

**Q2. Display font**
- A. Bundle Oswald (OFL, free, ~120 KB). **[RECOMMENDED]** — stadium-scoreboard feel, free, single weight suffices.
- B. Commission a custom stencil font ($500-$2000, 4-8 weeks). Unique, on-brand, but out of scope for this redesign timeline.
- C. Use Inter Bold with -0.02em tracking + 10% horizontal stretch. Already bundled, no new asset, but doesn't achieve the scoreboard feel.
- D. Bebas Neue (free, OFL). More dramatic, but ALL CAPS only — limits reuse.

**Q3. Card shadows**
- A. Real drop shadows via PIL compositing (per-frame). Looks best, but ~15ms × 30 cards = 450ms per refresh — over budget.
- B. 1px border + 4-tier bg depth system (no shadows). **[RECOMMENDED]** — depth comes from value contrast, not blur. 0ms cost.
- C. Single static shadow rendered once per card variant (pre-baked PNG). Middle ground, but limits dynamic resizing.
- D. CTk's native `border_width` + `border_color` only (current approach, refined). Essentially B but with stronger borders.

**Q4. Bottom news ticker bar**
- A. Keep it (32px, current). Player sees news without navigating.
- B. Remove it entirely. **[RECOMMENDED]** — duplicates News Feed, reclaims 32px, removes a "database tool" visual element.
- C. Replace with a thin "next event countdown" strip (16px). Compromise.
- D. Make it toggleable in Settings.

**Q5. Borderless window (custom title bar)**
- A. Full borderless on launch. Most immersive, but `overrideredirect(True)` is brittle on Linux.
- B. OS title bar on launch, borderless as a Settings toggle (off by default). **[RECOMMENDED]** — safe default, players who want immersion can opt in.
- C. OS title bar always (current). Safest, but keeps the "amateurish Windows chrome" the VLM flagged.
- D. Borderless on Windows + macOS only, OS chrome on Linux. Platform-aware, but adds complexity.

**Q6. StatBar visualization for attributes**
- A. Horizontal bars only (per §4.10 StatBar). **[RECOMMENDED]** — readable, voice-phrase-friendly, fits the grid.
- B. Radar/spider chart. Compact, shows all attributes at once, but at low resolution per axis.
- C. Hex grid (each attribute = a hexagonal cell, color-coded by tier). Visually striking, but unconventional.
- D. Both: bars by default, radar as a toggle. Best of both, but doubles the work.

### Interpretation decisions (3 questions)

**Q7. P0 interpretation fix — bump ENGINE_VERSION immediately?**
- A. Yes, ship the 1-line fix NOW (before the visual redesign). **[RECOMMENDED]** — takes effect on next Advance Day, cuts perceived repetition ~60%, no risk.
- B. Wait and bundle with the P1 short/long variant system. Slower, but bigger impact when it lands.
- C. Don't bump — leave the cache as-is and let the P1 work handle it. Risks the redesign launching with stale 3-variant phrases.

**Q8. Short/long variant system — schema approach**
- A. Add 12 new columns to `fighter_descriptors` (`*_short` + `*_long` per interpretation column). **[RECOMMENDED]** — simpler SQL, easier migration, backward-compatible.
- B. Move phrase banks to new `interpretation_phrases` DB table (content editors can tune without code changes). More flexible, but ~400 lines of migration code.
- C. Both: 12 new columns for the cache + DB table for the source-of-truth phrase banks. Most flexible, but most work.
- D. Neither — keep the current single-phrase-per-column system and just expand the variant count. Doesn't solve the short/long screen-context problem.

**Q9. Conditional voice triggers (champion reads differently from prospect)**
- A. Add in P1 (parallel to the short/long variant system). **[RECOMMENDED]** — layered voice is the Soul doc's "translate simulation into emotion" directive made literal.
- B. Defer to P3 (after the redesign ships). Simpler P1, but the redesign launches without the champion/prospect distinction.
- C. Don't add — the deterministic hash + screen-context picker is enough. Simpler, but loses the "champion always gets the LONG legacy phrase" rule.

### Scope decisions (3 questions)

**Q10. Championship Mode (3rd mode)**
- A. Add it as a full 3rd mode with its own palette. Most distinct, but triples the design surface area.
- B. Add it as a "skin" overlay on Fight Night (per §4.4). **[RECOMMENDED]** — 4-color overlay, activates only on title fights, minimal extra design work.
- C. Don't add it. Title fights use the standard Fight Night palette. Simpler, but loses the "marquee moment" visual weight.
- D. Add it later (P2 future). Defer the decision.

**Q11. Recent Fights visualization on Fighter Profile**
- A. Timeline view (per §6.3). **[RECOMMENDED]** — shows progression, serves Historian fantasy.
- B. Table view (current). Denser, treats all fights equally.
- C. Both: timeline by default, table as a tab toggle. Best of both, but adds complexity.
- D. Cards (one card per fight). Most visual, but takes the most vertical space.

**Q12. Fighter Profile tab structure**
- A. 6 tabs: Overview / Attributes / Personality / Career / Fights / News (per §6.3). **[RECOMMENDED]** — comprehensive, matches the genre standard.
- B. 4 tabs: Overview / Attributes / Career / Fights. Simpler, but merges Personality into Attributes (loses the distinction).
- C. No tabs — single long scroll. Simpler, but overwhelming for a screen with 26 attributes + 20 traits + 5 recent fights + bio + career stats.
- D. 8 tabs: add Scouting + Contracts + Injuries + Social. Most granular, but only relevant for some fighters.

---

## 12. Decision Log Entries (to append to MASTER_PLAN.md §10)

Once the supervisor approves §11, the following entries will be added
to `docs/MASTER_PLAN.md §10 Decision Log`:

```
- 2026-07-30 (UI redesign planning, Rev 3) — Visual design system
  REVISED to 4-tier depth system (bg_base / bg_surface / bg_card /
  bg_card_elevated). Pure black forbidden. 15-component library
  adopted. Oswald (OFL, free) bundled as display font. Source Serif
  Pro retained for Fight Night commentary. See docs/GUI_PLAN.md §4
  + docs/UI_REDESIGN_VISUAL_PLAN.md §1-§5.

- 2026-07-30 (UI redesign planning, Rev 3) — Interpretation layer
  audit found "8 variants per label" claim was misleading (4
  modules have 8, 4 have 1-3) AND the 8-variant banks never reached
  the production DB (ENGINE_VERSION not bumped). P0 fix: bump
  ENGINE_VERSION 1.5.0 → 1.6.0 to force cache rebuild. P1: add 12
  new columns to fighter_descriptors for short/long variant split.
  See docs/GUI_PLAN.md §5 + docs/UI_REDESIGN_INTERPRETATION_AUDIT.md.

- 2026-07-30 (UI redesign planning, Rev 3) — Ground-up redesign of
  4 existing screens (Dashboard, Roster, Fighter Profile, Free
  Agents) specified. Each uses the new 15-component library + 12-col
  grid + voice-phrase typography. FighterTable rewrite is the
  highest-risk change — ships behind USE_FIGHTER_TABLE_V2 feature
  flag. See docs/GUI_PLAN.md §6 + docs/UI_REDESIGN_VISUAL_PLAN.md §6.

- 2026-07-30 (UI redesign planning, Rev 3) — App shell restructured:
  top bar 60→56px (3 zones: logo / status / action), sidebar 220→
  56/220px (collapsed icon-only default, expanded icon+label on
  hover/pin), bottom bar removed (news ticker moves to News Feed).
  See docs/GUI_PLAN.md §4.9 + docs/UI_REDESIGN_VISUAL_PLAN.md §4.

- 2026-07-30 (UI redesign planning, Rev 3) — Championship Skin
  added as a 4-color overlay on Fight Night (not a full 3rd mode).
  Activates on fights.is_title_fight=1. Gold-leaf heatmap border,
  champion/challenger corner colors, belt graphic, "TITLE FIGHT"
  badge. See docs/GUI_PLAN.md §4.4.

- 2026-07-30 (UI redesign planning, Rev 3) — Asset inventory grows
  from ~110 to ~165 files. P0 = 43 new (32 icons, 6 logo variants,
  1 font, 4 textures). P1 = 28 new (fight night assets, belts,
  procedural portraits script). P2 = 12+ (pundit avatars). See
  docs/GUI_PLAN.md §8 + docs/UI_REDESIGN_VISUAL_PLAN.md §8.

- 2026-07-30 (UI redesign planning, Rev 3) — 6-phase implementation
  plan: Phase 0 (P0 interpretation fix, 1hr) → Phase 1 (theme+fonts,
  2-3d) → Phase 2 (component library, 5-7d) → Phase 3 (app shell,
  4-5d) → Phase 4 (Dashboard, 4-5d) → Phase 5 (Roster+Free Agents,
  6-8d, HIGHEST RISK) → Phase 6 (Fighter Profile, 7-9d). Total 28-37
  days. See docs/GUI_PLAN.md §9.
```

---

## 13. Next Steps

1. **Supervisor reviews §11 (12 open questions)** + marks decisions.
   Recommended: review Q1-Q6 first (visual), then Q7-Q9 (interpretation),
   then Q10-Q12 (scope).
2. **Supervisor approves/edits the design system** in §4 (color palette,
   typography, layout, components). Any edits to hex codes, font
   choices, or component specs go back into `UI_REDESIGN_VISUAL_PLAN.md`.
3. **Phase 0 ships immediately** (1-line ENGINE_VERSION bump) — takes
   effect on next Advance Day, gives the user immediate variety
   improvement while the visual redesign is being built.
4. **Phase 1 begins** (theme.py rewrite + Oswald bundle + texture
   utilities). Ships in 2-3 days. Existing screens immediately look
   better.
5. **Asset work begins in parallel** with Phase 1 (icons, logo variants,
   textures — ~3-5 days of focused work).
6. **Phases 2-6 follow** per the sequencing in §9.

**Out of scope for this revision:**
- The 18 not-yet-built screens (§7) — they ship in Phase 7+ after the
  4 existing screens are redesigned and the theming system is proven.
- The Fight Resolution screen (§7.1) — the biggest single screen,
  ships incrementally in Phase 7a-7d.
- Fighter portraits (P1) — procedural generation script ships in
  parallel with Phase 5.
- Belt graphics, fight-night textures (P1) — ship in parallel with
  Phase 7.

---

*End of GUI_PLAN.md Revision 3. Awaits supervisor sign-off on §11
before any code work begins.*
