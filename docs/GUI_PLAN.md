# CAGE EMPIRE — GUI Phase Plan

> **Status:** Strategic proposal (Revision 2). Awaits supervisor
> approval before any GUI code is written.
> **Authored:** 2026-07-25 (pre-Stage 6 planning).
> **Revised:** 2026-07-25 — supervisor pushed back on the original
> "calm-only" design direction. The fight resolution / play-by-play
> screen is a first-class gameplay centrepiece that must outdo
> WMMA5, and the design system must embrace the violence of fight
> night, not just the calm of the front office. See §1.5 for the
> supervisor's correction and §3 for the revised dual-mode design.
> **Decision owner:** Supervisor (user).
> **Replaces:** The 7700-line `src/app.py` Tkinter prototype (lines
> 6980–7693 contain a primitive `ttk`-only UI that the user has
> explicitly rejected as "ugly and not very flexible").

This document records four major design decisions, per
`docs/CONVENTIONS.md §9`:

- **D-GUI-1:** Logo direction.
- **D-GUI-2:** GUI framework choice.
- **D-GUI-3:** Visual design system (palette, typography, motif) —
  revised to a dual-mode "Office + Fight Night" system.
- **D-GUI-4 (NEW):** Fight Resolution screen as a first-class
  design centrepiece, with beat-synced commentary, named pundit
  interjections, memory resurfacing, heatmaps, and damage
  visualisation.

It also inventories the screens and assets the GUI phase will need
to produce, informed by the 54-table schema and the CAGE EMPIRE
Soul document's prime directive ("the player collects stories, not
fighters").

---

## 0. Pre-flight Verification

Before drafting this plan, the supervisor's machine was verified:

- **CONVENTIONS.md** re-read in full (818 lines, all 16 sections).
  Key rules that bind the GUI phase:
  - §13.1 Design Law — every screen must strengthen one of the 5
    pillars (Discovery / Investment / Growth / Conflict / Legacy).
    The Fight Resolution screen is the purest expression of the
    **Conflict** pillar.
  - §14 Interpretation Layer — **no raw attribute values appear in
    the player-facing UI.** Every number routes through
    `src/voice.py`. This is non-negotiable for the GUI, including
    the fight resolution screen (raw damage numbers must become
    prose — "He's hurt! That left hook landed clean!" — not
    "-23 HP").
  - §15 Event Bus — GUI must NOT add new inline side effects to
    `resolve_next_fight` or `run_tick`. GUI is a reader, not a
    writer. The fight resolution screen *plays back* the
    pre-resolved `fight_beats` rows; it does not compute them.
  - §6 Smoke test — every GUI build must keep `build_db.py` +
    `seed_data.py` + `tick_processor.py` + 38 acceptance tests green.
- **Latest build** confirmed: schema `3.7.0`, 54 tables, 16
  migrations, all 38 acceptance tests pass (~2,350+ sub-checks).
- **Working tree** is clean modulo the long-standing local doc
  edits. Last committed work: Task ID FIX-Critical (rival AI
  single-night resolution, probability-based retirement, 215 event
  themes, gym upgrades, promotion tier evolution) — supervisor
  sign-off APPROVED.
- **Beat engine verified**: `fight_beats` table is the source of
  truth for play-by-play. Each row = one beat (strike, takedown
  attempt, clinch, knockdown, finish, etc.). The GUI fight
  resolution screen reads `fight_beats` for a given `fight_id`,
  joins to `commentary_segments` and `fight_rounds`, and plays
  them back in chronological order. This is exactly how WMMA5
  does it — but with our deeper interpretation layer on top.

---

## 1. Logo Analysis (D-GUI-1)

### 1.1 Inputs reviewed

The supervisor supplied two batches of concepts:

- **Batch 1 (supervisor-supplied reference grids):**
  - `/home/z/my-project/upload/pasted_image_1784933961307.png`
    (Concept A — multi-variant grid)
  - `/home/z/my-project/upload/pasted_image_1784933971681.png`
    (Concept B — multi-variant grid)
- **Batch 2 (AI-generated via image-generation skill):**
  - `docs/logo_concepts/concept_1_the_strike.png`
  - `docs/logo_concepts/concept_2_crowned_cage.png`
  - `docs/logo_concepts/concept_3_impact_monogram.png`
  - `docs/logo_concepts/concept_4_punch_crown.png`
  - `docs/logo_concepts/concept_5_cage_door.png`
  - `docs/logo_concepts/concept_6_lineage.png`
  - `docs/logo_concepts/concept_7_data_cage.png`

The supervisor rejected all 7 AI-generated concepts as "cheap
looking" and **designed their own logo**. The supervisor's
design is now the official CAGE EMPIRE brand.

### 1.2 The official logo (supervisor-designed, locked)

| File | Size | Use |
|---|---|---|
| `docs/logo_concepts/supervisor_final/cage_empire_primary_1536x1024.png` | 1536×1024 | Primary lockup — splash screen, marketing, title bar |
| `docs/logo_concepts/supervisor_final/cage_empire_compact_450x300.png` | 450×300 | Compact variant — taskbar, Steam library, in-app corner badge |

VLM analysis: `/home/z/my-project/tool-results/supervisor_logo_analysis.json`.

### 1.3 VLM verdict on the supervisor's logo

The vision model scored the supervisor's design highly:

| Dimension | Score |
|---|---|
| Dual messaging (institutional empire + violent cage) | **9/10** |
| Overall fit for a "Football Manager of MMA" premium desktop software product | **8.5/10** |
| Small-size legibility | Good (with caveats — see §1.5) |

VLM summary, verbatim:

> "The logo projects a 'Brutalist Luxury' or 'Industrial
> Sovereignty' aesthetic. It successfully bridges the gap
> between the boardroom (symmetry, gold/silver palette, crown =
> institutional power, financial strategy, empire-building) and
> the arena (chain-link texture, octagonal shape, floodlights,
> distressed metal = visceral combat, sweat, blood, high-impact
> entertainment). It feels premium, masculine, and
> authoritative. It avoids the 'cartoonish' trap common in
> sports games and instead leans into a cinematic, almost
> HBO/ESPN broadcast quality."

### 1.4 Visual elements (per VLM analysis)

- **Primary container:** Octagonal shield mimicking the MMA
  cage geometry. Heavy industrial metal frame with visible
  corner bolts. Chain-link fence texture fills the interior.
- **Crown:** Large 3D-rendered gold crown at the apex. Sharp
  aggressive points, hammered/worn gold texture suggesting
  both royalty and battle-worn status.
- **Championship belt:** Small detailed belt icon at the
  bottom centre, reinforcing "Empire" + prize-fighting.
- **Stadium floodlights:** Two floodlight arrays flank the
  upper corners — "fight night" atmosphere + volumetric depth.
- **Wordmark:** "CAGE" in heavy slab-serif with distressed
  cold-rolled steel texture; "EMPIRE" in same font but rich
  textured gold. Creates clear hierarchy: CAGE = gritty
  reality, EMPIRE = aspirational value.
- **Tagline:** "BUILD THE PROMOTION. CREATE THE LEGENDS." in
  clean bold grotesque, white + gold, on a black banner plate.
- **Palette:** Deep black `#0A0A0A` background, industrial
  silver/grey for CAGE + frame, championship gold for EMPIRE
  + crown + belt, warm white/yellow for floodlights.

### 1.5 Small-size legibility (the 450×300 compact variant)

VLM analysis of the compact variant:

- **Survives perfectly:** The "CAGE EMPIRE" wordmark remains
  highly legible. Silver-vs-gold contrast holds. Octagonal
  silhouette unmistakable.
- **Degraded at thumbnail size:** chain-link texture becomes
  moiré noise; distressed scratches on letters disappear;
  tagline becomes illegible below ~100px wide; championship
  belt becomes a gold smudge; floodlights survive as small
  white dots.

**Implication:** the compact variant is good for taskbar /
Steam library use (where the silhouette + wordmark carry the
brand). For favicon (16×16) we still need a separate
monogram-only mark (see §1.6).

### 1.6 The brand system (5 variants, all derived from the supervisor's design)

The supervisor's logo is the **primary lockup**. The brand
system extends it into 5 variants, each for a specific UI
context. Per the VLM's recommendations:

| Variant | Source | Use case | Required sizes |
|---|---|---|---|
| **Primary lockup** | supervisor's design as-is | Splash screen (Office Mode), title bar, marketing, docs | 1536, 1024, 512, 256 |
| **Compact lockup** | supervisor's design, smaller | Taskbar, Steam library, in-app corner badge | 450, 256, 128 |
| **Fight Night variant** | derived — flatten to 2D vector, drop the 3D bevel, add subtle motion-blur glow on the gold + a hairline crack through the octagon border | Pre-fight splash, Fight Resolution screen header, fight-night marketing | 1024, 512, 256 |
| **Championship variant** | derived — primary lockup + replace the small belt icon with weight-class-specific championship icons (8 male + 8 female = 16 belt variants) | Title fight screens, champion profile, hall of fame | 1024, 512, 256 |
| **Favicon / compact mark** | derived — crown + octagon silhouette only (no text, no texture), single-colour gold on transparent | Favicon (16×16), mobile app icon (32×32, 64×64) | 64, 32, 16 |

The Fight Night, Championship, and Favicon variants will be
commissioned as a **post-Task-6.1 design task** (likely
Task 6.1.5 — "extend primary logo into full brand system").
Task 6.1 ships with just the primary + compact variants; the
derived variants land before Task 6.7 (Fight Resolution
screen) needs them.

All variants must work in: full colour, monochrome (white on
transparent), monochrome (black on transparent). Total asset
count for the full brand system: **~30 PNG/SVG files**.

### 1.7 The supervisor's earlier correction (recorded per CONVENTIONS §9, retained for history)

> "We haven't designed the fight resolution play-by-play / fight
> commentary screens yet but these are a BIG part of the game —
> WMMA5 has a play-by-play fight system, Football Manager has its
> matches played out — we MUST deliver a better-than-WMMA5 version
> as we always planned to with intelligent play-by-play commentary
> that resurfaces relevant memories and has named pundit
> interjections / arguments and is perfectly timed to the 'beats'
> of the fight with a coherent story — we haven't even planned it
> yet, it's on the todo list — but the point is that violence IS
> a part of this game and should be in the logo / marketing /
> design strategy — also means big images and heatmaps and stats
> and stuff."

This correction drove Rev 2 of the plan (dual-mode design
system). The supervisor's logo design delivers on this
correction directly — the chain-link + floodlights + steel
texture telegraph the violence, while the crown + gold +
symmetry telegraph the empire.

---

## 2. GUI Framework Choice (D-GUI-2)

> **No change from Revision 1.** The supervisor confirmed the
> tech stack ("ok I'm in complete agreement about the techy
> stuff"). Summary preserved below for completeness.

### 2.1 Recommendation: **CustomTkinter + Pillow + ttkbootstrap (Treeview only)**

#### Primary framework: `customtkinter>=5.2.0`

Already the project's stated direction in `requirements.txt`.
Solves the "ugly tkinter" complaint directly. MIT-licensed, ~5 MB
install, drop-in upgrade from existing tkinter code, cross-platform
pixel-identical, familiar event model. Adequate for our data
density (4000-fighter roster is the heaviest view).

#### Secondary: `Pillow>=10.0.0`

For fighter portraits, event posters, logo loading, heatmap
composition, damage visualisation overlays. Already in
`requirements.txt`.

#### Tertiary: `ttkbootstrap>=1.10` (Treeview theming only)

CustomTkinter does not ship a polished `Treeview` widget. For
tables (roster, rankings, finances, fight history) we use
`ttk.Treeview` styled by `ttkbootstrap` to match the CTk dark
theme. We do **not** use ttkbootstrap for any other widget —
only the Treeview.

#### Fight Night Mode additional dependency: `Pillow + Canvas`

The Fight Resolution screen uses tkinter's `Canvas` widget for
the cage heatmap and fighter silhouette damage overlay. Pillow
composites the heatmap gradients and damage sprites in real time
as beats play. No additional dependencies required — Canvas and
Pillow are already in the stack.

### 2.2 Rejected alternatives (no change from Revision 1)

- **PySide6 / PyQt6** — license complexity, 150 MB install, full
  rewrite required.
- **Flet** — DataTable widget still maturing; 50 MB install.
- **DearPyGui** — wrong paradigm (immediate-mode, weak for forms).
- **pywebview + HTML** — two-language project; IPC overhead.
- **Kivy** — touch-first, weak tables.
- **PyGObject (GTK)** — painful on Win/Mac.

### 2.3 What this means for `app.py`

The current `src/app.py` is a **7700-line monolith** mixing game
logic, DB plumbing, and a primitive tkinter UI. **This must be
split before the GUI phase begins** (Task 6.0). Target structure:

```
src/
├── app.py            ← becomes a 30-line launcher only
├── build_db.py       ← unchanged
├── seed_data.py      ← unchanged
├── tick_processor.py ← unchanged
├── services/         ← NEW: extracted game logic
│   ├── __init__.py
│   ├── fight_engine.py    (resolve_next_fight + beat engine)
│   ├── clock.py           (advance_day, get_clock)
│   ├── matchmaking.py     (card building, matchup analysis)
│   ├── contracts.py       (signing, expiry, agent offers)
│   ├── scouting_svc.py    (scout reports, hidden potential)
│   ├── finance_svc.py     (transactions, projections)
│   ├── news_svc.py        (news generation, feed)
│   ├── rivalries_svc.py   (heat, decay, confrontation)
│   ├── training_svc.py    (camps, weight cuts)
│   ├── injuries_svc.py    (creation, recovery)
│   ├── retirement_svc.py  (probability, hall of fame)
│   ├── punditry_svc.py    (named pundit interjections for fight screen)
│   ├── memory_svc.py      (memory resurfacing for fight screen)
│   └── ...
├── ui/               ← NEW: the GUI
│   ├── __init__.py
│   ├── app.py              (CageEmpireApp — main CTk window)
│   ├── theme.py            (colours, fonts, asset paths, mode switcher)
│   ├── widgets/            (reusable CTk widgets)
│   │   ├── fighter_card.py
│   │   ├── attribute_radar.py
│   │   ├── tale_of_tape.py
│   │   ├── news_feed.py
│   │   ├── calendar_strip.py
│   │   ├── cage_heatmap.py        (NEW: fight-night canvas widget)
│   │   ├── damage_silhouette.py   (NEW: fight-night canvas widget)
│   │   ├── beat_commentary.py     (NEW: fight-night scroll feed)
│   │   ├── pundit_panel.py        (NEW: fight-night named-pundit rail)
│   │   ├── memory_resurface.py    (NEW: fight-night memory bubble)
│   │   └── ...
│   ├── screens/            (one file per major screen)
│   │   ├── dashboard.py
│   │   ├── roster.py
│   │   ├── fighter_profile.py
│   │   ├── free_agents.py
│   │   ├── scouting.py
│   │   ├── matchmaking.py
│   │   ├── event_builder.py
│   │   ├── event_resolution.py     ← THE FIGHT RESOLUTION SCREEN (D-GUI-4)
│   │   ├── rankings.py
│   │   ├── titles.py
│   │   ├── rivalries.py
│   │   ├── finance.py
│   │   ├── hall_of_fame.py
│   │   ├── news.py
│   │   ├── rival_promotions.py
│   │   ├── gyms.py
│   │   ├── schedule.py
│   │   ├── records.py
│   │   ├── settings.py
│   │   ├── save_load.py
│   │   └── mods.py
│   ├── nav.py              (sidebar + topbar + bottombar)
│   └── assets/             (PNG/SVG icons, backgrounds, logos)
│       ├── logo/
│       ├── icons/
│       ├── backgrounds/
│       ├── fight_night/            (NEW: heatmaps, damage sprites, vignettes)
│       └── portraits/default/
└── voice.py          ← unchanged (the interpretation layer)
```

---

## 3. Visual Design System (D-GUI-3, REVISED)

### 3.1 The corrected aesthetic: **"Calm Empire, Violent Canvas"**

The game has two distinct emotional registers, and the design
system must serve both:

| Mode | When | Mood | Reference |
|---|---|---|---|
| **Office Mode** | 90% of gameplay — dashboard, roster, scouting, finance, contracts, world screens | Calm, data-dense, institutional. "Bloomberg Terminal meets ESPN scoreboard." | Football Manager 2024, OOTP Baseball, WMMA5 menu screens |
| **Fight Night Mode** | 10% of gameplay — the Fight Resolution screen, pre-fight splash, post-fight recap | Visceral, dramatic, narrative. "HBO pay-per-view broadcast meets documentary film." | HBO 24/7, UFC Countdown, NFL Films, ESPN 30 for 30 |

The original Revision 1 plan only designed for Office Mode. That
was wrong. The dopamine engine of a management sim is the moment
of resolution — the fight itself. We must outdo WMMA5's
play-by-play, and that means the Fight Night visual language must
be **as carefully designed as the Office Mode**, not an
afterthought.

### 3.2 Mode switching

The `ui/theme.py` module exposes two theme objects: `OFFICE` and
`FIGHT_NIGHT`. Screens declare which mode they want. The
transition is animated (300ms crossfade on background, 150ms on
accent colours) when the player enters or leaves the Fight
Resolution screen.

The top bar and sidebar remain in Office Mode throughout — they
are the "stadium infrastructure" that doesn't change. Only the
main content area transitions.

### 3.3 Colour palette — DUAL MODE

#### Office Mode (default)

| Role | Hex | Use |
|---|---|---|
| Background base | `#0f1115` | Main window background |
| Surface | `#1a1d23` | Cards, panels, sidebar |
| Surface elevated | `#232730` | Hover, active tab, dialog |
| Border / divider | `#2e333d` | Subtle 1px separators |
| Text primary | `#e8eaed` | Body, headings |
| Text secondary | `#9aa0a6` | Captions, metadata |
| Text tertiary | `#5f6368` | Disabled, timestamps |
| **Crimson (co-primary)** | `#c8323a` | CAGE wordmark, loss, KO/TKO, injury, rival heat, violence indicators |
| **Empire Gold (co-primary)** | `#d4a55a` | EMPIRE wordmark, champion, title, win, hall of fame |
| Neutral Steel | `#6b7280` | Mid-tier UI elements |
| Success | `#4ade80` | Signed, recovered |
| Warning | `#fbbf24` | At-risk |
| Danger | `#ef4444` | Cut, suspended, critical |

**Critical change from Revision 1:** Crimson and Gold are
**co-primary**, not "accents." Both carry equal brand weight. The
"two-accent rule" is preserved (no other saturated colours) but
crimson is no longer subordinate to gold. This is what the
supervisor's correction demands.

#### Fight Night Mode

| Role | Hex | Use |
|---|---|---|
| Background base | `#08090c` | Deeper black — the arena goes dark |
| Surface | `#11141a` | Slightly darker than Office Mode |
| Surface elevated | `#1c2028` | Active beat highlight |
| Border / divider | `#2a2f3a` | |
| Text primary | `#f5f6f8` | Brighter — punches through the darkness |
| Text secondary | `#b4b8c0` | |
| **Crimson (visceral)** | `#e53e3e` | Brighter, more saturated — blood in spotlight |
| **Empire Gold (champion)** | `#f0c060` | Brighter — title belt under stage lights |
| **Impact Yellow** | `#fbbf24` | NEW — knockdowns, big moments, finish flashes |
| **Heat Blue** | `#3b82f6` | NEW — low-activity heatmap zones |
| **Heat Orange** | `#f97316` | NEW — medium-activity heatmap zones |
| **Heat Red** | `#dc2626` | NEW — high-activity / high-damage heatmap zones |

The heatmap colours (blue → orange → red) are reserved
exclusively for the cage heatmap widget on the Fight Resolution
screen. They do NOT appear in Office Mode. This keeps the Office
Mode palette disciplined while giving Fight Night Mode the full
visual vocabulary it needs.

### 3.4 Typography

| Role | Font | Size | Weight |
|---|---|---|---|
| Display (splash, title bar) | Eurostile Bold Extended | 28–48 | 700 |
| H1 (screen titles) | Inter | 22 | 700 |
| H2 (panel titles) | Inter | 16 | 600 |
| H3 (sub-panel) | Inter | 13 | 600 |
| Body | Inter | 12 | 400 |
| Body small | Inter | 11 | 400 |
| Caption / metadata | Inter | 10 | 500 |
| Numbers / stats (mono) | JetBrains Mono | 12 | 500 |
| Attribute descriptors | Inter | 12 | 500 italic |
| **Fight commentary (Office)** | Inter | 13 | 400 | 
| **Fight commentary (Fight Night)** | **Source Serif Pro** | 15 | 400 | NEW — switch to serif for fight prose to feel like a book / documentary narration |
| **Pundit interjection** | **Source Serif Pro** | 13 | 600 italic | NEW — pundits sound like journalists, not UI labels |
| **Beat timestamp** | JetBrains Mono | 10 | 500 | "R2 3:42" — round + clock |

**Why Source Serif Pro for fight commentary?** Sans-serif feels
like UI text. Serif feels like narrative prose — like a book or
a long-form sports essay. The Fight Resolution screen's
commentary must read like HBO 24/7 narration, not like a tooltip.
The font switch is the single biggest cue that the player has
entered a different mode.

### 3.5 Layout motif — DUAL MODE

#### Office Mode shell (default)

```
┌─────────────────────────────────────────────────────────────────┐
│ TOP BAR: [CE mark] CAGE EMPIRE  |  Mon 14 Sep 2026  |  $12.4M   │
│                                  Week 37, Year 1       ↑ +$2.1M │
│                                          [Advance Day ▶]        │
├──────────┬──────────────────────────────────────────────────────┤
│          │                                                      │
│  SIDE    │            MAIN CONTENT AREA                         │
│  BAR     │            (Office Mode — scrollable)                │
│          │                                                      │
│  Home    │                                                      │
│  Roster  │                                                      │
│  Events  │                                                      │
│  Scouting│                                                      │
│  Finance │                                                      │
│  World   │                                                      │
│  HoF     │                                                      │
│  Settings│                                                      │
│          │                                                      │
├──────────┴──────────────────────────────────────────────────────┤
│ BOTTOM BAR: news ticker · next event countdown                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Fight Night Mode shell (Fight Resolution screen only)

```
┌─────────────────────────────────────────────────────────────────┐
│ TOP BAR: [CE mark + crack overlay] CAGE EMPIRE | Sat 19 Sep 2026│
│                                  [PPV #237]    [Exit Fight ◀]   │
├──────────┬──────────────────────────────────────────────────────┤
│          │ ┌───────────────────────────────────────────────────┐│
│  SIDE    │ │  PRE-FIGHT BUILD-UP (auto-advances to live)       ││
│  BAR     │ │  Tale of Tape · Pundit predictions · Memory setup ││
│  (dimmed)│ ├───────────────────────────────────────────────────┤│
│          │ │                                                   ││
│  Home    │ │   ╔═══════════════════╗   ┌──────────────────┐  ││
│  Roster  │ │   ║   CAGE HEATMAP    ║   │  COMMENTARY FEED │  ││
│  Events  │ │   ║   (live, beat-    ║   │  (scroll, serif) │  ││
│  ●FIGHT◀ │ │   ║    synced)        ║   │                  │  ││
│  Scouting│ │   ╚═══════════════════╝   │  R2 3:42 — ...   │  ││
│  Finance │ │   ┌────────┐  ┌────────┐  │                  │  ││
│  World   │ │   │ FIGHTER│  │ FIGHTER│  │  PUNDIT PANEL    │  ││
│  HoF     │ │   │   A    │  │   B    │  │  (named,         │  ││
│  Settings│ │   │ (dmg)  │  │ (dmg)  │  │   interjects)    │  ││
│          │ │   └────────┘  └────────┘  │                  │  ││
│          │ │                            │  MEMORY BUBBLE   │  ││
│          │ │   ROUND/CLOCK · SCORECARD  │  (resurfaces)    │  ││
│          │ └───────────────────────────────────────────────────┘│
├──────────┴──────────────────────────────────────────────────────┤
│ BOTTOM BAR: live · beat 47/127 · [Pause] [Speed 1x] [Skip]      │
└─────────────────────────────────────────────────────────────────┘
```

Key Fight Night layout decisions:

- **Sidebar dims to 40% opacity** — the player is in the arena
  now, navigation is suspended. The "Events" item glows crimson
  with a small "FIGHT" badge to indicate where they are.
- **Top bar** swaps the "Advance Day" button for "Exit Fight"
  (return to event summary). The logo mark gains the crack
  overlay. The date becomes the event date.
- **Main content** becomes a fixed-size grid (no scroll) with
  four zones: (1) pre-fight build-up → live fight → post-fight
  recap (one zone, three states); (2) cage heatmap; (3) two
  fighter damage silhouettes side-by-side; (4) commentary feed
  + pundit panel + memory bubble in a right rail.
- **Bottom bar** becomes a transport control: beat counter,
  pause, speed (0.5x / 1x / 2x / 4x), skip to finish.

### 3.6 The interpretation layer in the UI (no change from Revision 1)

Per CONVENTIONS §14, **no raw attribute numbers appear in the
player-facing UI**. The GUI calls `src/voice.py` for every
displayed value. The Fight Resolution screen applies this rule
to **damage numbers** too: a fighter who takes a -23 HP shot
does NOT see "-23" — the commentary reads "He's hurt! That left
hook landed clean!" The numeric damage is stored in `fight_beats`
for the engine and post-fight stats, but the player sees prose.

The one place raw numbers appear: the optional "Stats" sub-tab
on the fighter profile (player opts in by clicking).

---

## 4. Fight Resolution Screen (D-GUI-4, NEW)

> This section is the heart of Revision 2. The Fight Resolution
> screen is the single biggest visual moment in the game. It is
> where the dopamine lives. It must outdo WMMA5.

### 4.1 The design goal

**"HBO 24/7 meets a live ESPN broadcast, narrated by
documentary-grade prose, with pundits who argue, memories that
resurface at the perfect moment, and a cage heatmap that shows
you exactly where the fight was won."**

WMMA5's play-by-play is functional but flat — a text feed with
basic round scoring. Football Manager's match engine is visual
but the commentary is generic. We do both better:

- **Prose quality** better than WMMA5 (serif typography,
  interpretation layer, no raw numbers, beat-tied narrative).
- **Visual richness** better than FM (heatmap + damage
  silhouettes + scorecard + memory bubbles, not just a 2D pitch).
- **Pundit personality** unique to CAGE EMPIRE (named pundits
  with archetypes, voice, biases — they argue with each other).
- **Memory resurfacing** that no competitor has (the
  interpretation layer pulls relevant past fights / rivalries /
  career arcs and surfaces them at the moment they matter).

### 4.2 Three-phase structure

The Fight Resolution screen has three phases, played in sequence:

#### Phase 1: Pre-Fight Build-Up (~15–30 seconds at 1x speed)

- **Tale of the Tape** — both fighters' measurements, records,
  rankings, current form (last 5 fights W/L), injury status.
  Descriptive prose under each (per the interpretation layer).
- **Pundit Predictions** — 2–3 named pundits give their pick +
  reasoning. Each pundit has a voice (the cynic, the
  technician, the romantic). They sometimes disagree.
- **Memory Setup** — the system pre-loads 3–5 memories that
  *might* be relevant (past meetings, common opponents, career
  arcs). They are queued but not yet displayed. Example: "These
  two met in 2023 — Vega Reyes won by split decision in a
  fight many scored for the challenger."
- **Storyline Context** — if this fight is a rivalry, a title
  fight, a comeback, a debut, a retirement tour — one paragraph
  of context. Sourced from `rivalries`, `titles`,
  `fighter_career`, `fighter_memory_links`.
- **Tale-of-tape widget** renders this in two columns (Red
  Corner / Blue Corner) with the descriptive prose between them.

#### Phase 2: Live Fight (variable — typically 2–10 minutes at 1x speed)

This is where the beat engine plays back. The screen has four
live zones:

##### Zone A: Cage Heatmap (Canvas widget)

A top-down view of the octagon. As beats play, the heatmap
accumulates "heat" in the zones where action happened:

- Blue corner zone (left) — fighter A's territory.
- Red corner zone (right) — fighter B's territory.
- Centre — neutral exchanges.
- Cage wall zones — clinch / pressure fighting.

Each beat adds a coloured circle to the heatmap at its location.
Colour intensity grows with each subsequent beat in the same
zone. By the end of the fight, the heatmap tells the story of
*where* the fight was fought — grappler who dragged it to the
cage, striker who kept it in centre, etc.

This is the visual the player will screenshot and share. It is
the signature element.

##### Zone B: Fighter Damage Silhouettes (Canvas widget, ×2)

Two fighter silhouettes (one per corner), front-facing. As
beats play, damage zones light up:

- Head (red glow on impact, persisting bruising after)
- Body (liver kicks, body shots)
- Legs (calf kicks, leg kicks)
- Arms (blocking damage)

The intensity of the glow scales with the `damage` value stored
in `fight_beats`. The glow fades over 3–5 seconds but leaves a
faint persistent marker — by round 3, a fighter who's eaten
many leg kicks has visibly bruised legs.

This is **not** a health bar (CONVENTIONS §14 forbids raw
numbers). It's a visual prose layer — "Look at the damage to
his lead leg. He can't put weight on it." The commentary
references the visible damage.

##### Zone C: Commentary Feed (scrollable, serif typography)

The main narrative feed. Each beat produces 1–3 sentences of
prose. The feed auto-scrolls but the player can scroll back.

Format per beat:

```
R2 3:42  —  Vega Reyes lands a crisp left hook to the body.
            Martinez winces and backs away. The crowd groans.

         [PUNDIT · Marco Bianchi]
         "That's the third body shot in 90 seconds. He's
          setting up the upstairs shot."

         [MEMORY · 2023]
         Reyes did the same thing to Saito in their title
         fight — body work paid off in round 4.
```

- **Beat timestamp** in JetBrains Mono — "R2 3:42" = Round 2,
  3:42 remaining. Readable at a glance.
- **Action prose** in Source Serif Pro — narrative voice,
  past tense, sensory. Sourced from `commentary_segments`
  joined to `fight_beats`.
- **Pundit interjection** (when triggered) in italic serif,
  with the pundit's name + coloured avatar dot. Pundits
  interject on average every 5–15 beats, more on big moments
  (knockdowns, near-submissions, controversial moments).
- **Memory bubble** (when triggered) in a tinted box with the
  year. Memories surface on average every 20–40 beats, only
  when the system finds a relevant link (past fight, common
  opponent, career arc, rivalry beat).

The feed is the player's primary read on the fight. The
heatmap and silhouettes are glance-able context; the feed is
the story.

##### Zone D: Pundit Panel (right rail)

A vertical strip showing the 2–3 named pundits covering this
fight. Each pundit has:

- Avatar dot in their personal colour.
- Name + role ("Marco Bianchi · colour commentator").
- Live mood indicator (a small emoji-free glyph: calm /
  excited / shocked / arguing).
- Their last interjection (1-line summary).

When two pundits disagree, the panel shows a small "ARGUING"
indicator between them and the commentary feed surfaces their
disagreement as a short back-and-forth.

Pundits are sourced from `staff` table where
`staff_role = 'broadcast'`. Their personality (from
`fighter_personality` if they're an ex-fighter, or a generic
`personality_archetypes` row) determines their voice and bias.

##### Transport controls (bottom)

- Beat counter: "Beat 47 / 127"
- Round + clock: "R2 · 3:42"
- Pause / Play
- Speed: 0.5x / 1x / 2x / 4x / Instant
- Skip to Round / Skip to Finish
- "Show stats" toggle — opens a small overlay with strike
  counts, takedown counts, control time (per round). This is
  the one place raw numbers appear during the live fight, but
  only on player request.

#### Phase 3: Post-Fight Recap (~20–40 seconds at 1x speed)

- **Result card** — winner, method, round, time. Big
  typography. Gold accent for winner, crimson for loser (if
  by KO/TKO), neutral for decision.
- **Pundit grades** — each pundit gives the fight a letter
  grade (A+ to F) and a 1-paragraph summary of their take.
  These are stored in `show_ratings` for future reference.
- **Final heatmap** — the completed cage heatmap, now
  annotated with the 3–5 most decisive moments (knockdowns,
  near-submissions, the finishing sequence).
- **Final damage silhouettes** — both fighters' accumulated
  damage, with medical suspension indicator if applicable
  (sourced from `suspensions`).
- **Memory creation** — the system writes 1–3 new
  `fighter_memory_links` rows based on what happened. These
  will resurface in future fights.
- **News generation** — `news_items` row(s) created for the
  fight result. Player sees a preview of the headline.
- **Storyline hooks** — if the fight triggers a rivalry, a
  title change, a retirement consideration, a comeback — the
  recap screen surfaces these as "What this means" cards. This
  is the prime anticipation-driver.

### 4.3 Memory resurfacing — how it works

The `memory_svc.py` (new service) maintains a queue of
candidate memories for each fight before it starts. Candidates
are sourced from:

- `fighter_memory_links` for both fighters (past fights,
  career milestones, gym history).
- `rivalries` involving either fighter.
- `fight_history` for both fighters vs common opponents.
- `hall_of_fame` for retired legends with similar style or
  trajectory.

During the live fight, the system watches for "trigger beats"
that match a queued memory's trigger condition:

- Body-shot-heavy fight → resurfaces memory of past body-shot
  KO by either fighter.
- Knockdown in round 2 → resurfaces memory of past comebacks
  from knockdowns.
- Title-fight going to decision → resurfaces memory of past
  controversial decisions involving these fighters or this
  referee.
- Fighter getting dominated → resurfaces memory of past
  upset wins by that fighter (the "he's been here before"
  narrative).

Each resurfacing is shown once, in the memory bubble format
above. The system tracks which memories have been shown to
avoid repetition.

This is the system no competitor has. It is the deepest
expression of the Soul document's "the player collects stories"
directive.

### 4.4 Named pundit interjections — how they work

Pundits are not just labels on a paragraph. They are
simulated personalities with:

- **Voice** — word choice, sentence length, technical depth.
  Sourced from `personality_archetypes` joined to `staff`.
- **Bias** — favour strikers / grapplers / veterans / prospects
  / specific nations / specific gyms. Stored as a JSON column
  on `staff` (new column — minor schema bump, see §6).
- **Mood** — calm / excited / shocked / arguing / bored. Updated
  live based on what's happening in the fight. A pundit's mood
  affects their interjection frequency and tone.
- **Relationships** — pundits who dislike each other argue more.
  Pundits who are ex-training-partners with a fighter are
  slightly biased toward that fighter.

The `punditry_svc.py` (new service) generates interjections on
trigger beats, using:

- The current beat's content.
- The pundit's voice + bias + mood.
- The fight's narrative arc so far.
- Memory context (pundits reference past fights too).

When two pundits disagree on a close round or a controversial
moment, the system generates a short back-and-forth (3–5 lines
of dialogue). This is the "argument" the supervisor asked for.

### 4.5 Performance budget

The Fight Resolution screen must run smoothly at 60fps on a
mid-range laptop. Key constraints:

- Heatmap redraw: only redraw changed zones, not full canvas.
- Damage silhouette: pre-rendered sprite sheets per body zone,
  composited at runtime. No per-pixel work during beats.
- Commentary feed: append-only, never full re-render. Cap
  visible beats at 200 (older beats scroll into a virtualised
  buffer).
- Pundit interjections: pre-generated at fight resolution time
  (not during playback), stored in `commentary_segments`, just
  revealed in sequence during playback.

The fight engine itself (resolve_next_fight) runs in <100ms for
a 5-round fight. The screen plays back the pre-resolved beats
with synthetic delays (300ms–2s per beat at 1x speed) to create
the live-fight feel.

---

## 5. Screen Inventory (revised)

Informed by the 54-table schema. **22 screens** (was 21 — added
the Fight Resolution screen as a first-class entry, even though
it was implicitly part of "Event Resolution" in Revision 1).

### 5.1 HOME group

| Screen | Purpose | Primary tables |
|---|---|---|
| **Dashboard** | "What's happening now" — today's date, key alerts, finance snapshot, recent news, next event card | `simulation_clock`, `news_items`, `finance_transactions`, `events`, `event_cards` |
| **Schedule** | Calendar view (month/week) of all scheduled events (player + AI promotions) | `events` |
| **News Feed** | Chronological news feed with filters | `news_items`, `news_sources` |

### 5.2 FIGHTERS group

| Screen | Purpose | Primary tables |
|---|---|---|
| **Roster** | Sortable/filterable table of player's promotion fighters | `fighters`, `fighter_attributes`, `fighter_contracts`, `rankings` |
| **Free Agents** | Unsigned fighters available to sign | `fighters` (where `current_promotion_id IS NULL`), `scouting_reports` |
| **Scouting** | Regional scouting targets, scout assignments, hidden-potential reports | `scouting_reports`, `fighters`, `regions` |
| **Fighter Profile** | The big profile screen — headshot + bio + 28 attributes (descriptors) + personality + career record + recent fights + contracts + injuries + social posts + memory links + training camp | `fighters`, `fighter_attributes`, `fighter_personality`, `fighter_bios`, `fighter_career`, `fight_history`, `fighter_contracts`, `injuries`, `scouting_reports`, `social_posts`, `fighter_memory_links`, `training_camps`, `fighter_descriptors` |
| **Hall of Fame** | Inductees by year, search/filter, compare-to-current mode | `hall_of_fame`, `fighters` |

### 5.3 EVENTS group

| Screen | Purpose | Primary tables |
|---|---|---|
| **Event Builder** | Schedule new event: venue, market, date; build card of 5–13 fights; main event; projected buyrate/attendance | `events`, `event_cards`, `venues`, `markets`, `fights`, `weight_classes`, `titles` |
| **Matchmaking** | Pick two fighters → tale-of-tape + matchup analysis + projected odds + storyline context | `matchup_analyses`, `fighters`, `fighter_attributes`, `fight_history` |
| **Fight Resolution** ★ | **THE FIGHT NIGHT SCREEN** — pre-fight build-up, live beat-by-beat commentary, cage heatmap, damage silhouettes, named pundit panel, memory resurfacing, post-fight recap. See §4. | `fight_beats`, `fight_rounds`, `commentary_segments`, `fighters`, `fighter_attributes`, `fighter_memory_links`, `rivalries`, `staff`, `titles`, `show_ratings`, `suspensions`, `news_items` |
| **Past Events** | Archive of completed events, click to view full card + results + show rating | `events` (status=completed), `fights`, `fight_history` |

### 5.4 BUSINESS group

| Screen | Purpose | Primary tables |
|---|---|---|
| **Finance** | Current cash, projected income/expenses, transaction log, broadcast deals | `finance_transactions`, `broadcast_contracts`, `contracts` |
| **Contracts** | All active contracts (fighter + staff + broadcast), expirations, renewals | `fighter_contracts`, `staff_contracts`, `broadcast_contracts` |
| **Rival Promotions** | All other promotions, their prestige/roster size/finances/recent events | `promotions`, `fighters`, `events`, `finance_transactions` |
| **Gyms** | All gyms in the world, their quality/reputation/fighters produced | `gyms`, `fighters`, `staff` |

### 5.5 WORLD group

| Screen | Purpose | Primary tables |
|---|---|---|
| **Rankings** | Per weight class, per promotion, P4P; click row → fighter profile | `rankings`, `fighters`, `weight_classes` |
| **Titles** | Current champions across all promotions + lineage history per title | `titles`, `fighters`, `fight_history` |
| **Rivalries** | Active rivalries with heat meter, history of confrontations | `rivalries`, `fighters`, `fight_history` |
| **Records** | All-time leaders: KOs, submissions, title defenses, longest reigns | `fighters`, `fight_history`, `titles`, `hall_of_fame` |

### 5.6 SETTINGS group

| Screen | Purpose | Primary tables |
|---|---|---|
| **Settings** | Game options: naming style, difficulty, theme (dark/light), font size, fight playback speed | `player_settings` |
| **Save/Load** | Multiple save slots, autosave config, export/import | filesystem + `saves/` |
| **Mods** | Load/manage mod packs, view installed mods | `mods/` directory |

### 5.7 Total scope (revised)

- **22 screens** across 6 nav groups.
- **Largest screen**: Fight Resolution (~12 tables joined live, 4
  canvas widgets, 3-phase playback). This is also the most
  complex screen to build — Task 6.7 in §7.
- **Highest-traffic screen**: Roster.
- **Most novel screen**: Fight Resolution — this is where CAGE
  EMPIRE differentiates from WMMA5 most viscerally.

---

## 6. Asset Inventory (revised)

All assets live under `src/ui/assets/`. Total estimated count:
**~110 files** (was ~80 — added fight-night-specific assets).

### 6.1 Logo system (24 files, was 18)

Per §1.6. Five variants × multiple sizes + monochrome versions.

### 6.2 Icon set (32 files, no change)

Status icons (16×16 + 32×32 PNG + SVG source) for: champion,
contender, prospect, veteran, rookie, injured, suspended,
retired, deceased, cut, scouted, hidden_potential, rivalry,
media_star, fan_favourite, gym_leader, on_win_streak,
on_loss_streak, title_defense, comeback. Plus 12 nav icons.

### 6.3 Backgrounds & textures (12 files, was 8)

Added:
- Fight Night Mode background (1920×1080) — deeper black with
  a subtle vignette around the cage area.
- Cage heatmap base texture (1024×1024 PNG) — the empty octagon
  top-down view with corner labels (Red / Blue).
- Damage silhouette sprite sheets (2 files, one per fighter
  pose) — pre-rendered body zones with damage states 0–4.
- Round transition overlay (1920×1080) — "ROUND 2" big text
  card, fades in/out.
- Knockdown flash overlay (1920×1080) — single-frame impact
  flash, crimson, 200ms.
- Finish banner (1920×400) — "WINNER" gold banner shown at the
  end of the fight.

### 6.4 Default portrait (4 files, no change)

### 6.5 Belt graphics (16 files, no change)

### 6.6 Font files (8 files, was 6)

Added:
- Source Serif Pro Regular + SemiBold Italic (2 files, ~600 KB)
  for fight commentary and pundit interjections.

### 6.7 Pundit avatar dots (12 files, NEW)

12 coloured circular avatars (64×64 PNG) for the named pundit
panel. Each pundit in the `staff` table is assigned a colour
on first broadcast appearance; the avatar is a simple coloured
circle with their initials in white.

### 6.8 Memory bubble texture (4 files, NEW)

4 tinted background textures (256×256 tileable) for the memory
bubble, varying by memory type: past-meeting (gold tint),
career-arc (blue tint), rivalry (red tint), common-opponent
(grey tint).

---

## 7. Recommended Build Order (revised)

The GUI phase is large enough to warrant its own Stage (Stage 6)
with sub-tasks. Recommended task breakdown:

| Task | Description | Schema impact |
|---|---|---|
| 6.0 | **Decouple UI from game logic** — extract services from `app.py` into `src/services/`, leaving `app.py` as a 30-line launcher. All 38 tests must still pass. | None |
| 6.1 | **Theme + asset pipeline + logo lock** — implement `ui/theme.py` with dual-mode (Office + Fight Night), install CTk + Pillow + ttkbootstrap, bundle fonts (incl. Source Serif Pro), commission final logo set from Concept 3, generate icon set + fight-night textures. | None |
| 6.2 | **App shell + navigation + mode switcher** — top bar, sidebar, bottom bar, screen router, dark/light toggle, Office↔Fight Night transition animation. No screens yet. | None |
| 6.3 | **Dashboard + News Feed** — the player's home. Forces the news_svc + finance_svc extraction. | None |
| 6.4 | **Roster + Fighter Profile** — the highest-traffic Office Mode screens. Forces voice.py UI integration. | None |
| 6.5 | **Scouting + Free Agents** — scout report rendering, hidden potential UI. | None |
| 6.6 | **Event Builder + Matchmaking** — card builder, tale-of-tape widget. | None |
| 6.7 ★ | **Fight Resolution Screen** — THE big one. Pre-fight, live fight (4 zones: heatmap + damage silhouettes + commentary + pundit panel + memory bubble), post-fight recap. Forces punditry_svc + memory_svc extraction. Schema bump: add `staff.pundit_bias` JSON column (MINOR). | Minor: +1 column on `staff` |
| 6.8 | **Past Events + Schedule** — archive + calendar. | None |
| 6.9 | **Rankings + Titles + Rivalries + Records** — the "world" screens. | None |
| 6.10 | **Finance + Contracts + Rival Promotions + Gyms** — the "business" screens. | None |
| 6.11 | **Hall of Fame** — the "legacy" screen. | None |
| 6.12 | **Settings + Save/Load + Mods** — utility screens. | None |
| 6.13 | **Polish pass** — keyboard shortcuts, tooltips, empty states, error dialogs, accessibility, fight replay scrubbing. | None |
| 6.14 | **Smoke tests for GUI** — headless CTk smoke test pattern (run app, click each nav item, assert no crash, verify mode switching). | None |

No schema changes during the GUI phase except Task 6.7's single
new column (`staff.pundit_bias` JSON, default NULL). That bump
will be a MINOR version (3.7.0 → 3.8.0) per CONVENTIONS §1.1.

---

## 8. Open Questions for the Supervisor (revised)

1. **Logo direction (§1.4):** Concept 3 (Impact Monogram) is the
   VLM's clear winner (9.5/10 fit) and my recommendation. Are you
   happy to lock Concept 3 as the primary, with Concept 2's
   crown integrated as a championship overlay? Or do you want a
   fresh round of 3–4 concepts in the same direction before
   committing?

2. **Fight Resolution scope (§4):** The four live zones (heatmap
   + 2 damage silhouettes + commentary feed + pundit panel +
   memory bubble) is an ambitious single screen. Are you happy
   with this scope, or do you want to defer the pundit panel +
   memory resurfacing to a later iteration and ship the heatmap
   + silhouettes + commentary first? (My recommendation: ship
   all four together — they reinforce each other and the
   memory resurfacing is the system that differentiates us
   from WMMA5.)

3. **Pundit bias column (§7, Task 6.7):** Adding
   `staff.pundit_bias` JSON is the only schema change in the
   GUI phase. The bias lets pundits favour strikers/grapplers/
   veterans/prospects/nations/gyms. Approve this minor schema
   bump (3.7.0 → 3.8.0)?

4. **Fight playback speed:** Default 1x = ~3–8 minutes for a
   typical fight. Players can speed up to 4x or skip to finish.
   Is 1x the right default, or should the default be 2x (faster
   dopamine) or "instant" (skip playback, show recap)?

5. **Memory resurfacing frequency (§4.3):** I've targeted
   1 memory per 20–40 beats (so ~3–6 memories per typical
   fight). Too frequent = gimmicky. Too rare = misses the
   moments that matter. Approve this tuning, or want it more
   conservative (1 per 30–60 beats, ~2–4 per fight)?

6. **Task 6.0 refactor prerequisite (no change from Revision 1):**
   Are you OK with the GUI phase starting with a refactor task
   that splits `app.py` into `services/` + `ui/`? This is the
   single biggest de-risking step for the whole phase.

7. **Portrait generation (no change from Revision 1):** The
   world seed ships 4000 fighters with no portraits. Default
   silhouette stopgap, or commission 4000 unique portraits via
   image-gen (100+ hours of generation) as a separate post-GUI
   task?

8. **Player-controlled promotion (no change from Revision 1):**
   Confirm — the player runs ONE promotion and the GUI shows
   the world from that promotion's perspective? (I've assumed
   yes, per the Soul document's "Empire Builder" fantasy.)

---

## 9. Decision Log Entries (to be appended to MASTER_PLAN.md §10)

Once the supervisor approves, the following entries will be added
to `docs/MASTER_PLAN.md §10 Decision Log`:

```
- 2026-07-25 (pre-Stage 6, Rev 2) — GUI framework decision:
  CustomTkinter + Pillow + ttkbootstrap-Treeview. Rejected
  PySide6 (license/size), pywebview (two-language overhead),
  Flet (maturity), DearPyGui (wrong paradigm). See
  docs/GUI_PLAN.md §2.

- 2026-07-25 (pre-Stage 6, Rev 2) — Visual design direction
  REVISED to dual-mode "Calm Empire, Violent Canvas". Office
  Mode (90% of gameplay, calm data-dense institutional) +
  Fight Night Mode (10% of gameplay, visceral dramatic
  narrative). Crimson and Gold elevated to co-primary
  colours. Source Serif Pro added for fight commentary.
  See docs/GUI_PLAN.md §3.

- 2026-07-25 (pre-Stage 6, Rev 2) — Logo direction: Concept 3
  (Impact Monogram, CE inside gold-trimmed octagon with three
  impact slashes) as primary mark. Concept 2's crown element
  integrated as championship overlay. Fight Night variant adds
  crack + glow overlay. See docs/GUI_PLAN.md §1.4.

- 2026-07-25 (pre-Stage 6, Rev 2) — Fight Resolution screen
  declared a first-class design centrepiece (D-GUI-4). Four
  live zones: cage heatmap + fighter damage silhouettes +
  beat-synced commentary feed + named pundit panel with
  memory resurfacing. Goal: outdo WMMA5's play-by-play. See
  docs/GUI_PLAN.md §4.

- 2026-07-25 (pre-Stage 6, Rev 2) — app.py refactor prerequisite
  retained: split 7700-line app.py into src/services/ + src/ui/
  before any GUI code is written. See docs/GUI_PLAN.md §2.3.
```
