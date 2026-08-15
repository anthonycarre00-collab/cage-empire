> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — REPLAN-A Gap Analysis (Brutally Honest)

> **Task ID:** REPLAN-A
> **Agent:** Gap Analysis (general-purpose)
> **Date:** 2026-08-02
> **Mode:** RESEARCH + ANALYSIS ONLY. No code changes were made.
> **Audience:** Supervisor (the user) + the next planning agent.
> **Verdict in one sentence:** The plan is excellent, the components are
> well-built, the theme system is solid — **but the data feeding the
> UI is broken, the cache is stale, the news feed is empty, there are
> zero scheduled events, and 98.3% of fighters share 3 momentum
> phrases.** The user is right to be frustrated. The fix is mostly
> DATA + CACHE, not more UI code.

---

## 0. Executive Summary

After fully ingesting every planning doc, the Soul doc, the 519-page
spec PDF (810 KB of text), the current dashboard/theme/app/component
code, and the live production DB, the picture is clear:

**The visual redesign plan was sound. The components are built. The
dashboard imports + uses 16 of the 24 components correctly. The fonts
finally resolve in the test environment. The CTk theme override was
removed.** All of that is real and verified in code.

**BUT** — and this is the brutal part — the user is still seeing a
lifeless screen because:

1. **The `news_items` table is EMPTY (0 rows).** The Dashboard's
   "Recent News" section ALWAYS shows the EmptyState card. The user's
   complaint "no data was being pulled through" was **literally
   correct** — not a perception issue, not a wiring issue. The data
   does not exist.
2. **`daily_headlines` has 4 rows, all from world-seed day.** The Top
   Story card shows the same 4 headlines forever ("Daniel Gonzalez is
   sliding fast", "Hiroki Nakamura is rising fast", "The prodigy turns
   heads again", "Jack Taylor stuns Silvio Guerra"). They never
   regenerate.
3. **`events` table has 1,884 events, ALL with `status='completed'`.**
   ZERO scheduled events. So the "Next Event" card always falls back
   to the "no upcoming events — here's your last card" branch. There
   is never a countdown. There is never a "Build Card" CTA in
   context of a real upcoming date.
4. **`fighter_descriptors.snapshot_version = 1` for ALL 4,450
   fighters.** The cache was built once at world seed and never
   refreshed. The audit's P0 fix (bump `ENGINE_VERSION` from 1.5.0 →
   1.6.0) was **never applied** — there is no `interpretation_engine_meta`
   table at all. The 8-variant `_EXT` phrase banks exist in the code
   but never reached the DB.
5. **98.3% of fighters (4,376 / 4,450) have `momentum='stable'`** and
   they share only 3 phrase variants:
   - "neither hot nor cold right now" (1,501×)
   - "holding steady" (1,459×)
   - "form has been consistent" (1,416×)
   
   The Fighter Watch cards fall back to these momentum phrases. So
   three different fighters on three different cards read the same
   string. The Soul doc's "translate simulation into emotion" directive
   is **functionally dead** at the data layer.

**This is not a UI problem. This is a content + cache problem.** The
user has been told the dashboard was rewritten 3+ times. They couldn't
see a difference because the DATA flowing through the rewritten
components was identical across iterations.

The plan asked for "polished, with fighter profiles, rich event
narration, social media, news, and visual presentation." The spec
PDF (page 1) said the game should feel like a "professional management
tool, not a web page crammed into a window" with "real-life glamour"
for events. The current build delivers the visual scaffolding for
that — but the simulation has not actually been run. The world was
seeded on 2026-07-29 and the clock has not advanced meaningfully.

**Top 3 actions for the supervisor (in priority order):**

1. **Run the simulation forward 30-60 in-game days** so news_items,
   scheduled events, finance_transactions, and fresh daily_headlines
   populate. (Effort: 1 hour, script-only, no UI changes.)
2. **Apply the audit's P0 fix** (bump ENGINE_VERSION → 1.6.0) so the
   8-variant phrase banks finally reach the cache. (Effort: 1 line of
   code.)
3. **Give the user a non-techy cache-clear instruction** + verify
   fonts load on their actual Windows machine (the test env shows
   ✓ but Windows may behave differently).

Everything else in this doc supports these three actions.

---

## 1. Documents Ingested

### Planning docs (read in full, every line)

| Document | Lines | Where | Verdict |
|---|---|---|---|
| `upload/UI_REDESIGN_VISUAL_PLAN.md` | 2,424 | upload/ + docs/ | Excellent. 4-tier depth system, 15-component library, 12-col grid, 8-point spacing, voice register table, asset inventory, 6-phase rollout. The plan is sound. |
| `upload/UI_REDESIGN_INTERPRETATION_AUDIT.md` | 1,346 | upload/ + docs/ | Excellent + damning. Confirmed "8 variants per label" claim was misleading (4 modules have 8, 4 have 1-3), the `_EXT` banks never reached the DB (ENGINE_VERSION not bumped), and 98.3% of fighters share 3 phrases. **The P0 fix it recommended was never applied.** |
| `upload/UI_POLISH_PLAN.md` | 88 | upload/ + docs/ | Older, mostly superseded. 7 fixes (hidden attrs, gender filter, clickable names, portrait placeholder, font caps, logo image, news ticker). All addressed in later phases. |
| `cage_empire/docs/CAGE_EMPIRE_SOUL.md` | 149 | docs/ | The prime directive. 5 core fantasies (Talent Hunter, Empire Builder, Kingmaker, Historian, Puppet Master), anticipation is the real dopamine, "translate simulation into emotion", "the player collects stories, not fighters". |
| `upload/Cage Empire Soul.txt` | 299 | upload/ | The user's original Soul text. Identical content to CAGE_EMPIRE_SOUL.md but in the user's own voice. Useful for tone calibration. |

### Spec PDF (the original vision)

| Document | Pages | Text chars | Source |
|---|---|---|---|
| `upload/Cage empire spec chat.pdf` | 519 | 810,903 chars (37,118 lines after pdfminer extraction) | The user's original chat with an AI about what the game should be. |

Extracted via `pdfminer.high_level.extract_text` (pypdf failed with
`'bbox'` errors on every page — the PDF is image-heavy).

### Current build state

| File | Lines | Read |
|---|---|---|
| `src/ui/screens/dashboard.py` | 2,305 | Full read |
| `src/ui/theme.py` | 1,899 | Full read |
| `src/ui/app.py` | 1,121 | First 650 lines (shell + top bar + sidebar) |
| `src/ui/screens/roster.py` | 1,942 | `_query_roster` + pagination (lines 1594-1723, 1821-1822) |
| `src/ui/widgets/components/gradient_card.py` | 185 | Full read |
| `src/ui/widgets/components/__init__.py` + 24 component files | 28 files, ~5,800 LOC total per worklog | Listed, sampled |
| `worklog.md` (last 350 lines) | 350 | Full read |
| `data/cage_empire.db` | — | Queried news_items, daily_headlines, fighter_descriptors, events, finance_transactions, fighters, titles, promotions |

---

## 2. The Spec PDF — What the User Originally Envisioned

The spec PDF is a 519-page chat transcript where the user described
their vision to an AI over many sessions. Key insights that have
**drifted** from the current build:

### 2.1 The user's original words (page 1)

> "With AI help gonna build an mma booking game similar to wMma5
> mostly text based but **polished** and with good fighter pics and
> profiles, a realistic believable fight play-by-play engine and
> commentary, show bookings and options, fighter personality
> attributes social media and beefs and lots more options."

> "Realistic fun and believable with better features and fight engine
> than wMma5. Search GitHub or internet for a code base or shell we
> could use for this or convert from a different type — **this Game
> shouldn't be too complex to build.**"

**Two critical signals the build has drifted from:**

1. **"POLISHED" is the user's word, not the AI's.** It appears in the
   very first message. The user wanted polish from day 1. The current
   build's visual polish is real (gradient cards, momentum rings,
   form meters, gold accents) but it sits on top of EMPTY data tables.
2. **"Shouldn't be too complex to build."** The user wanted a focused,
   shippable game. The build has accumulated 4,450 fighters, 1,884
   events, 30+ services, 24 components, 22 planned screens, 6 phases,
   12 open supervisor questions. The complexity has outpaced the
   visible polish. The user is right to feel the project is spinning.

### 2.2 The user's UI direction (page 12 of the chat, ~line 2203)

> "Art style palette layout ui etc - probably PythonUI - modern
> desktop windows app - modern mma styling, readable relevant fonts
> icons and screen rules, background images etc - suggestions?"

The AI's response (line 2268):

> "For a modern desktop Windows app, I'd avoid 'plain Tkinter look'
> and go with a polished Python desktop stack such as CustomTkinter
> or a styled ttk approach, because modern GUI guidance strongly
> favors consistent typography, spacing, and restrained color
> systems for readability. A good desktop sports sim UI should feel
> like a professional management tool, not a web page crammed into
> a window."

> "Palette: dark charcoal, muted steel, off-white text, one strong
> accent color, and a second warning color."
> "Accent ideas: MMA red, electric teal, gold for titles, yellow for
> warnings."
> "Fonts: Inter, Segoe UI, or a similar clean sans-serif."
> "Layout: left nav, central content, right-side context panel,
> bottom event feed."
> "Icons: simple line icons for contracts, belts, news, injuries,
> gym, social, scouting."

**Drift check:** The build's palette matches (charcoal + gold +
crimson). The fonts match (Inter + JetBrains Mono + Source Serif
Pro + Oswald). The layout matches (left nav + central content —
though the right-side context panel was dropped, which is fine).
**Icons are still missing** — `STATUS_ICONS` and `NAV_ICONS` dicts
point at empty files per the visual plan's §8.1 audit. This is a
P0 blocker the plan identified but was deferred.

### 2.3 The user's vision for fight presentation (line 5009)

> "We want TV style commentary with visual elements and momentum
> maps/stats/fatigue and pundit analysis and comments. We need
> 'betting odds' and instant matchup/booking analysis."

> "We want events to feel like events with real life glamour."

**Drift check:** The Fight Resolution screen is **not built**.
Per GUI_PLAN §7.1, it's deferred to Phase 7+ (post-redesign). The
user has been testing the Office Mode screens (Dashboard, Roster,
Profile, Free Agents) for weeks. **They have never seen the
marquee screen.** The dopamine moment the Soul doc promises
("anticipation is the real dopamine") requires the Fight Night
screen — without it, the game is a management dashboard with no
payoff.

### 2.4 The user's voice register (line 5063-5071)

> "A rookie who grows from 62 to 68 in grappling should not just
> have a silent number change; the game should say they are beginning
> to look dangerous in scrambles, or that their top control is
> finally catching up to their athleticism."

**Drift check:** The interpretation layer was built to deliver this.
The `voice.py` ATTRIBUTE_DESCRIPTORS bank has phrases like "carries
real knockout power" / "fight-ending power in both hands" / "heavy
hands that end careers" for the elite tier. **BUT** the cache stores
only 1 variant per fighter (deterministic, RNG-seeded by
`fighter_id * 31 + 17`) and never rotates. So a fighter's attribute
descriptor reads identically on every visit. The Soul doc's
" translate simulation into emotion" is reduced to "the same string
forever per fighter."

### 2.5 The user's voice (page 5 of the chat, the Soul text)

> "The fighter is not the reward. The STORY is the reward."
> "Nobody remembers: Striking = 87. Five years later. They remember:
> 'That kid I found in Mexico. Nobody wanted him. He became a
> champion. Retired undefeated. Now his son is fighting.'"

**Drift check:** Compare this voice to the actual daily_headlines
in the DB:

| Source | Phrase |
|---|---|
| Soul doc (target) | "That kid I found in Mexico. Nobody wanted him. He became a champion." |
| DB (actual) | "Daniel Gonzalez is sliding fast" |
| DB (actual) | "Hiroki Nakamura is rising fast" |
| DB (actual) | "The prodigy turns heads again" |
| DB (actual) | "Jack Taylor stuns Silvio Guerra" |

The DB phrases are sports-page clichés. The Soul doc's voice is
promoter-flavored, past-tense narrative, specific imagery. The
gap is enormous. The headline_engine has 1 hardcoded template per
family — there is no variation, no specificity, no promoter flavor.

---

## 3. Gap Analysis Tables (Plan vs Build vs Gap)

### A. Voice + Tone

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| Soul doc: "Translate simulation into emotion." Voice phrases should be promoter-flavored, past-tense, specific imagery. | 5 random news headlines sampled from DB: ALL 4 daily_headlines use 1-template-per-family sports-page clichés ("X is sliding fast", "X is rising fast", "The prodigy turns heads again"). news_items table is EMPTY (0 rows). | The voice is functionally dead. The user sees the same 4 cliché headlines forever. The headline_engine needs the 8-variant-per-(type, family) expansion the audit's P1 fix promised. **The 5 Soul doc phrases ("That kid I found in Mexico", "His best years may be behind him", "the wunderkind everyone's talking about", etc.) do not appear anywhere in the production DB.** |
| Audit: 8-variant `_EXT` banks for momentum/pressure/trajectory/career_phase. | 5 random fighter_descriptors sampled: ALL show `stable||neither hot nor cold right now` or `stable||holding steady` or `stable||form has been consistent`. 4,376 / 4,450 fighters (98.3%) are `stable` with 3 phrase variants. | The 8-variant banks exist in `context_engine.py` lines 204-260 but the cache was never rebuilt. `fighter_descriptors.snapshot_version = 1` for all 4,450 fighters. The audit's P0 fix (bump ENGINE_VERSION 1.5.0 → 1.6.0) was never applied. There is no `interpretation_engine_meta` table. |
| GUI_PLAN §10.2: "Promoter-flavored, not journalist-neutral. 'The matchmakers can't ignore him anymore' beats 'He is highly ranked.'" | The actual phrases in the DB ("holding steady", "neither hot nor cold right now", "form has been consistent") are journalist-neutral, not promoter-flavored. | The voice that's shipping reads like a database admin tool, not HBO 24/7. The Soul doc's reference phrases ("the wunderkind everyone's talking about") are nowhere to be seen in production data. |
| Soul doc: "Anticipation is the real dopamine. Players should constantly have: the prospect I just signed, the champion nearing retirement, the rivalry exploding..." | The Fighter Watch cards show 3 fighters (Top Prospect, Hottest Streak, Biggest Fall). All 3 fall back to momentum_phrase because narrative_family is NULL for 99.3% of fighters. So all 3 cards show "Holding Steady" or "Neither Hot Nor Cold Right Now". | Three different fighters on three different cards read the same string. There is no anticipation because there is no variation. The Soul doc's "something is always coming, something is always unresolved" is reduced to "nothing is happening, repeatedly." |

### B. Visual Richness

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| Visual plan §5: 15 components with gradients, sparklines, momentum rings, form meters, trend indicators, stat tiles. Dashboard uses 16 of 24. | Verified in `dashboard.py` lines 152-166: GradientHeader, GradientCard, Card, SectionHeader, DataChip, StatTile, NewsCard, EmptyState, Button, HyperlinkLabel, PortraitFrame, MomentumRing, FormMeter are all imported AND USED. The render methods (`_render_watch_card` line 1886, `_refresh_promotion_status`, etc.) actually pack these components with real data. | Components ARE used. This is real. **BUT** — the data flowing through is broken: the Sparkline gets only 1-2 distinct finance_transaction values (all on 2026-01-01), so it shows a flat line. The MomentumRing tier for 98.3% of fighters is "stable" (the same color). The FormMeter pulls from `fight_history` which has 3,598 rows — this DOES work and should show varied W/L blocks. **The visual richness library is intact; the data feeding it is monotonous.** |
| Visual plan §2.2: 4-tier depth system with luminance deltas visible to the eye. bg_base #0a0c10 (lum ~5) / bg_surface #15181f (lum ~24) / bg_card #1c2028 (lum ~32) / bg_card_elevated #252a33 (lum ~42). | Verified in `theme.py` lines 109-253: the _CTk_THEME_DATA JSON has the correct hex values. The OfficeColors class (line 1108+ per the docstring) defines them. The CTk theme JSON is installed via `install_ctk_theme()` called from `app.py` line 69. | The depth system IS built. **BUT** the worklog (line 13368-13378) reveals a previous regression: Phase 1.5 accidentally made cards DARKER than the shell (delta 8 instead of 18) because the subagent confused `bg_surface` with `bg_surface_elevated`. This was fixed in commit f48ec52 by changing 20 card constructions from `bg_card` → `bg_card_elevated`. **The contrast bug is fixed in the code, but if the user's `__pycache__` is stale, they're still running the broken Phase 1.5 code.** |
| Visual plan §3.2: Oswald display font, Inter per-weight, JetBrains Mono, Source Serif Pro. "Stadium scoreboard feel." | Verified in `theme.py` lines 317-330 (font file paths) + lines 900-955 (registration logic). The worklog (line 13605) claims "all 7 families now resolve ✓" after the slant="normal"→"roman" fix + `_install_fonts_to_user_dir()` copying TTFs to `~/.fonts/` (Linux) / `%LOCALAPPDATA%/Fonts/` (Windows). | **Test environment shows ✓ for all 7 fonts.** BUT this was tested on Linux with Xvfb + `fc-cache -f`. On Windows, the `_install_fonts_to_user_dir()` function copies files to `%LOCALAPPDATA%/Fonts/` but does NOT call the Win32 `AddFontResource` API or broadcast `WM_FONTCHANGE`. Windows may not pick up the fonts until next session restart — or at all, depending on the Tk version. **The user's "better fonts would do us a world of good but seems to keep failing" complaint is consistent with Windows silently falling back to system sans.** |
| Visual plan §4.6: Textures (noise_grain, chain_link_dim, gold_leaf_border, vignette_fight_night) "should be felt, not seen." | Verified: 6 PNG textures exist in `src/ui/assets/textures/` (noise_grain.png, chain_link_dim.png, gold_leaf_border.png, vignette_fight_night.png, cage_watermark.png, glove_icon.png, belt_icon.png). `theme.py` has generator functions + `_load_or_generate` lazy-load cache. `app.py` `_build_main_content()` applies `get_noise_grain_texture(size=(1920, 1080))` as a background label. | Textures ARE built and applied. This is real. **BUT** the noise_grain is 3% opacity (alpha 5-12 out of 255). That is below the threshold of perception on most monitors, especially with the dark palette. The user's complaint "need textures or backgrounds" is consistent with the texture being TOO subtle. The plan said "felt, not seen" — but if the user can't see it, they don't feel it either. |

### C. MMA Atmosphere

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| User: "maybe some MMA elements/visuals that shows its a MMA sim" | `theme.py` has `get_glove_icon()`, `get_belt_icon()`, `get_cage_watermark()`, `get_chain_link_dim_texture()`. `gradient_header.py` accepts `show_cage_motif=True` (chain-link overlay at 8% opacity on right half) + `show_logo=True` (32×32 compact logo). Dashboard's GradientHeader uses both. SectionHeader accepts `icon_ctk_image=` prop — wired to FIGHTER WATCH (glove), YOUR CHAMPIONS (belt), RECENT RESULTS (belt). Cage watermark (CE monogram in octagon, 5% opacity) placed bottom-right of main_content. | MMA visuals ARE present: cage motif on header, glove + belt icons on section headers, watermark in corner. This is real. **BUT** — the chain-link motif is 8% opacity (barely visible), the watermark is 5% opacity (invisible on most monitors), and the icons are 20×20 pixels (tiny). The user has to squint to see them. **The MMA visuals are technically present but visually recessive.** What's MISSING from the docs: a full-bleed cage-fence background texture on the Dashboard, a hero portrait of an actual fighter, a belt graphic for champions, an octagon-shaped frame for fight cards. The plan promised these as P1 (post-redesign) but they were never built. |
| Visual plan §8.2 P0: 32 icons (nav icons × 14, status icons × 8, topic icons × 10) in Lucide/Phosphor outlined style. | The visual plan's §8.1 audit (line 1962) found: "Icons | 0 (paths only) | STATUS_ICONS + NAV_ICONS dicts in `theme.py:527-564` point at empty files. **This is a P0 blocker.**" | **STATUS: STILL UNBUILT.** The sidebar is text-only. The nav items have no icons. This is the single most fixable "database tool" tell — and it was identified as a P0 blocker in the plan but was deferred. The user's "still something missing to give it a friendlier feel" is consistent with a text-only sidebar. |
| Visual plan §8.2 P1: 8 weight-class belts (front + side, 512×256 PNG). | 0 belt graphics. | Champions are shown as DataChip + HyperlinkLabel text. There is no visual belt. The "Kingmaker" fantasy (the player creates stars who hold belts) has no visual payoff. |

### D. Fonts + Typography

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| Visual plan §3.2: Oswald (display), Inter per-weight (body, 4 unique family names so Tk can't collapse them), JetBrains Mono (numbers), Source Serif Pro (fight commentary). | `theme.py` lines 317-330 define all 9 TTF paths. `_register_fonts()` lines 900-955 registers each Inter weight under a UNIQUE family name (`Inter-Regular`, `Inter-Medium`, etc.) — this fixes the Rev 2 collapse bug. `OfficeFonts` class lines 1102-1118 uses the per-weight RESOLVED family names with weight="normal" (the family name encodes the weight). | The font registration logic is correct + well-engineered. **BUT** the worklog (line 13605) says the slant="normal"→"roman" fix was needed for Tk 9.0. The Linux test env now shows ✓ for all 7. **The user's Windows machine may still fail silently** because: (a) Tk on Windows uses GDI privately, not fontconfig, (b) `_install_fonts_to_user_dir()` copies files to `%LOCALAPPDATA%/Fonts/` but doesn't call `AddFontResource` or broadcast `WM_FONTCHANGE`, (c) Windows may require a session restart or even a service restart to pick up new fonts in a Tk app. **Verification method:** ship a one-line debug script that prints `tk.fontFamilies()` to a file, ask the user to run it + send back the file. If "Inter" / "Oswald" / "JetBrains Mono" / "Source Serif Pro" are NOT in the list, the fonts are NOT loading on Windows. |
| GUI_PLAN §10.1: 5 voice registers (Statboard, UI label, Voice phrase short, Voice phrase long, Pundit). Each visually distinct. | `OfficeFonts` defines display, display_small, h1, h2, h3, body, body_small, caption, mono, descriptor, commentary. `FightNightFonts` adds pundit + beat_timestamp. The font tuples are correctly wired. | The font ROLES are well-defined. The issue is that the user can't perceive the difference if the fonts aren't loading. Even when they DO load, the difference between Inter-Regular and Inter-Medium is subtle (Medium is ~5% heavier). The user wants DRAMATIC font differentiation — Oswald display vs Inter body vs JetBrains Mono numbers vs Source Serif Pro commentary. **The plan delivers this in code, but the visual payoff requires the fonts to actually render.** |

### E. Color Palette + Depth

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| Visual plan §2.2: 4-tier depth with luminance deltas of ~18 between shell and card. Pure black forbidden. | `_CTk_THEME_DATA` JSON (theme.py lines 109-253) has the correct hex values: bg_base #0a0c10, bg_surface #15181f, bg_card #1c2028, bg_card_elevated #262a30 (changed from #252a33 to #262a30 per Fix #6 — "warmer, more red, less blue"). | **The contrast bug from Phase 1.5 (cards darker than shell) IS fixed in code.** Verified by the worklog line 13373: "changed 20 card constructions across 5 files from bg_card → bg_card_elevated. Restored contrast to delta 18 (2.25x better than broken Phase 1.5)." **BUT** — `bg_card_elevated` was changed from `#252a33` → `#262a30` per Fix #6. Let me compute the actual luminance: #252a33 = (37, 42, 51) → lum ~42. #262a30 = (38, 42, 48) → lum ~42. **The "warmer" change is a luminance delta of ZERO. It's purely a hue shift (slightly more red, slightly less blue).** The user's complaint "styling rarely changes much in each iteration" is literally true at the pixel level — the warmth shift is below the threshold of perception. |
| Visual plan §2.2: "Depth from value contrast, NOT shadows (PIL compositing is too slow per Phase 4 perf budget)." | No shadows. 1px borders only. | Correct. But the depth delta of 18 (lum 24 shell → lum 42 card) is on the edge of perception. The visual plan's §3.1 "Office Mode reads as void, not calm" critique of the OLD design is partially still true — delta 18 is visible but not dramatic. **The user wants DRAMATIC change, not subtle improvement.** A delta of 30-40 (e.g., shell #0a0c10 lum 5, card #2a2f38 lum 45) would be visibly richer. |

### F. Data Wiring

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| User: "no data was being pulled through to the new dashboard design, so wiring and integration is incomplete" | Worklog line 13630: "Data wiring status: VERIFIED. All 9 sections render with real data (verified via debug logging, not just 'no crash'). Debug logging (CAGE_EMPIRE_DASH_DEBUG=1) confirms: 4 daily_headlines, $50M cash, 60 fighters, 6 champions, 5 completed events, fastest_rising=fighter 1, biggest_fall=fighter 14." | **Both statements are true.** The wiring IS complete — every component receives data from a query. **BUT** the data itself is sparse + stale: `news_items` table is EMPTY (0 rows), so the News section ALWAYS shows the EmptyState card. `daily_headlines` has 4 rows from world-seed day. `events` table has 1,884 events ALL with `status='completed'`, ZERO scheduled — so the Next Event section ALWAYS shows the "no upcoming events" fallback. `finance_transactions` has 10 rows ALL on 2026-01-01 (opening balance) — so the cash sparkline is a flat line. **The user's "no data was being pulled through" complaint is CORRECT for the News section (literally 0 items) and SEMANTICALLY CORRECT for Next Event (no scheduled events = no countdown = no dopamine hook).** The debug logging isn't lying — it's just that "0 items" is a valid query result that produces an empty UI. |
| The wiring path DB → query → component → screen is: SQLite conn (app.py:161) → conn.execute(SQL) in dashboard.py's `_query_*` methods → `_refresh_*` methods that destroy+recreate widgets with the query results → widgets packed into SectionHeader containers in self._scroll. | Verified in dashboard.py: `_refresh_news` (line 2207) queries `SELECT headline, body, topic, published_at, fighter_id FROM news_items ORDER BY published_at DESC LIMIT 5` → iterates rows → builds NewsCard components. The query returns 0 rows → falls through to EmptyState branch (line 2243). | The wiring is correct. The data is the problem. **Running the simulation forward 30-60 in-game days would populate news_items, scheduled events, finance_transactions, and fresh daily_headlines.** This is a 1-hour script run, not a UI rewrite. |

### G. The 5 Core Fantasies (from Soul doc)

| Fantasy | What the docs promise | What's actually built | The gap |
|---|---|---|---|
| **Talent Hunter** | "I find greatness before anyone else." Scouting, hidden potential, uncertain reports, regional networks. | Scouting screen exists (`scouting.py`). Free Agents screen has ceiling column with "????" for unscouted fighters (per visual plan §6.4). | The information asymmetry is built. **BUT** the scouting reports are not visualized richly (just a Card/Flat with text). The "discovery dopamine" requires more visual weight — a scouting report should feel like a dossier, not a database row. **Medium gap.** |
| **Empire Builder** | "My promotion dominates the sport." Prestige, finances, market expansion, TV deals, champions. | Dashboard's Promotion Status section shows Cash (with sparkline), Reputation (voice band), Fan Trust (voice band), Roster count, Champions count. | The Empire Builder hooks ARE on the Dashboard. **BUT** the sparkline is flat (10 finance_transactions all on the same day). The "growth" fantasy requires visible growth — a sparkline that trends up over weeks. **The data isn't there to feed the fantasy.** |
| **Kingmaker** | "I create stars." Promotion, matchmaking, hype, rankings, media. | Matchmaking screen NOT BUILT. Rankings screen NOT BUILT. Titles screen NOT BUILT. Fight Night screen NOT BUILT. | **Zero of the Kingmaker screens exist.** The user has been testing 4 Office Mode screens (Dashboard, Roster, Profile, Free Agents). The Kingmaker fantasy has NO visual representation in the current build. **Critical gap.** |
| **Historian** | "The world remembers what I built." Hall of fame, records, memories, historical comparisons, legacy. | Hall of Fame screen NOT BUILT. Records screen NOT BUILT. Rivalries screen NOT BUILT. Past Events screen NOT BUILT. | **Zero of the Historian screens exist.** The Soul doc says "nobody remembers Striking = 87 five years later" — but the game has no Hall of Fame to remember anything. The Legacy Engine has 3 variants per label (`building`, `established`, `legendary`, `forgotten`) but 99.5% of fighters are `legacy_state='building'`. **Critical gap.** |
| **Puppet Master** | "The sport evolves because of my decisions." Rivalries, gym ecosystems, promotion ecosystems, career arcs. | Rivalries screen NOT BUILT. Gyms screen NOT BUILT. Rival Promotions screen NOT BUILT. | **Zero of the Puppet Master screens exist.** The career_arc + rivalries + rival_ai services exist in code but have no UI. **Critical gap.** |

**Summary: 4 of 5 fantasies have ZERO visual representation in the current build.** The user has been testing the Talent Hunter + Empire Builder scaffolding. The other 3 fantasies are deferred to Phase 7+ (post-redesign). The Soul doc's "anticipation is the real dopamine" requires ALL 5 fantasies to be visible — the player needs to see the rivalry brewing, the legend in decline, the gym producing talent, the prospect rising. **Right now, the player sees none of that.**

### H. Anticipation + Dopamine

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| Soul doc: "Players should constantly have: the prospect I just signed, the champion nearing retirement, the rivalry exploding, the gym producing talent, the event next month, the young heavyweight everyone is talking about." | Dashboard has: Top Story (1 stale headline), Next Event (always fallback to most recent completed), Fighter Watch (3 cards with same momentum phrase), Champions (6 chips), Recent News (EmptyState). | **ZERO anticipation hooks work.** The prospect card shows "Holding Steady" — no anticipation. The champion nearing retirement — no such card exists. The rivalry exploding — no rivalries screen. The gym producing talent — no gyms screen. The event next month — ZERO scheduled events. The young heavyweight everyone is talking about — same "Holding Steady" phrase. **The Soul doc's core dopamine loop is functionally absent from the Dashboard.** |
| Soul doc: "The addiction comes from: 'I wonder what happens next.'" | The Advance Day button exists (top bar, gold, 180×44, prominent). It calls `services.clock.advance_day` which runs `tick_processor.run_tick`. | The button IS there. **BUT** — when the user clicks it, what changes? The daily_headlines regenerate (but they're 1-template-per-family, so "X is rising fast" → "Y is rising fast"). The news_items should populate (but the news engine may not be generating items if there are no scheduled events to write about). The cash sparkline gets 1 new point (but it's still mostly flat). **The dopamine payoff of clicking Advance Day is minimal because the simulation produces minimal VISIBLE change.** |

### I. Performance

| What the docs promise | What's actually built | The gap + why it matters |
|---|---|---|
| User noted (per task brief): "the Roster table loads the full DB then filters." | `roster.py` lines 1594-1718: `_query_roster` builds a WHERE clause with `current_promotion_id = ?` AND `is_active = 1` (+ optional weight_class_id, gender, search). The SQL is `SELECT ... FROM fighters f LEFT JOIN ... WHERE {where_sql} ORDER BY f.fighter_id ASC` — there is NO LIMIT/OFFSET clause. | **The user's complaint is PARTIALLY correct.** The WHERE clause IS applied in SQL (so it doesn't load ALL 4,450 fighters — it loads only the player's promotion's fighters, e.g., 60 for promo 1). **BUT** there is NO LIMIT/OFFSET — all matching rows are fetched, then pagination (PAGE_SIZE=20) is applied client-side at line 1821: `start = (self._current_page - 1) * PAGE_SIZE; end = start + PAGE_SIZE`. For 60 fighters this is fine. For 1,000+ fighters (a major promotion in late-game), this would fetch 1,000 rows then display 20. **The fix is trivial: add `LIMIT ? OFFSET ?` to the SQL.** This connects to the parallel performance analysis subagent. |
| Dashboard refresh budget: 500ms per the worklog. | Worklog line 13604: "Refresh performance: 452ms median (5 iterations, warm cache). Budget was 500ms." Phase 2.5 was 228ms. | 452ms is within budget but the ~200ms increase from Phase 2.5 is concerning — it's from the Recent Results section (5 cards × 3 labels) + chain-link gradient compositing + noise_grain tiling. **If the user adds more components per screen (Roster, Profile), the refresh will exceed budget.** The destroy+recreate refresh pattern (D10) is the simplest but most expensive — every refresh destroys all widgets + rebuilds them. Phase 3+ should switch to component `update()` methods. |

---

## 4. "Why the User Sees No Difference" — Ranked Diagnosis

The user has tested 3+ iterations and reports seeing no difference. Here are the most likely reasons, ranked by probability with evidence:

### #1. The data flowing through the UI is broken/empty/stale (PROBABILITY: VERY HIGH)

**Evidence:**
- `news_items` table: **0 rows**. The News section ALWAYS shows EmptyState.
- `daily_headlines` table: **4 rows, all from world-seed day**. The Top Story card shows the same 4 headlines forever.
- `events` table: **1,884 rows, ALL status='completed'**. ZERO scheduled events. The Next Event section ALWAYS shows the "no upcoming events" fallback.
- `finance_transactions` table: **10 rows, ALL on 2026-01-01** (opening balance). The cash sparkline is a flat line.
- `fighter_descriptors.snapshot_version = 1` for ALL 4,450 fighters. The cache was built once at world seed and never refreshed.
- 98.3% of fighters have `momentum='stable'` with only 3 phrase variants.

**Why it matters:** The user has been told the dashboard was rewritten 3+ times. Each rewrite changed the rendering layer (Phase 2.5 → DASH-V2 → DASH-V2 SIGNOFF) but the DATA was identical across all three. **The user sees no difference because the data produces the same UI.** A GradientCard with empty data looks identical to a Card with empty data looks identical to a CTkFrame with empty data.

**Verification method:** Run the simulation forward 30 in-game days. If the Dashboard changes visibly (news items appear, scheduled events appear, cash sparkline trends, daily_headlines rotate), this is confirmed as the #1 cause.

**Proposed fix:** 1-hour script run. No UI changes needed.

### #2. The user's `__pycache__` is stale (PROBABILITY: HIGH)

**Evidence:**
- Worklog line 13372: "Also identified: __pycache__ may be stale on user's machine, causing old code to run even after git pull."
- Worklog line 13376: "Cleared __pycache__ in repo + documented the cache-clear procedure for the user in the commit message."
- The user said: "either my cache didnt clear in which case give me a non techy simple way to clear it - or your changes didnt work because i see no difference in this latest build"

**Why it matters:** Python caches compiled bytecode in `__pycache__/` directories. If the user did `git pull` without deleting `__pycache__/`, Python may load the OLD compiled dashboard.py instead of the new one. The Phase 1.5 contrast regression (cards darker than shell) would persist on the user's machine even after the fix shipped.

**Verification method:** Add a version stamp visible in the UI (e.g., a tiny "v2.5.1" label in the bottom-right corner of the Dashboard). Ask the user what version they see. If it's an old version number, `__pycache__` is stale.

**Proposed fix:** Ship a `clear_cache.bat` (Windows) / `clear_cache.sh` (Mac/Linux) that deletes all `__pycache__/` directories + runs the app. The supervisor is already planning to give the user a non-techy cache-clear instruction.

### #3. Fonts may not be loading on the user's Windows machine (PROBABILITY: MEDIUM-HIGH)

**Evidence:**
- Test env (Linux + Xvfb + `~/.fonts/` + `fc-cache -f`) shows ✓ for all 7 fonts.
- Worklog line 13605: "Font health check: all 7 families now resolve ✓ — Inter-Regular, Inter-Medium, Inter-SemiBold, Inter-Bold, JetBrains Mono, Source Serif Pro, Oswald. Root cause was Tk 9.0 expecting slant='roman' not 'normal'."
- BUT the user said: "better fonts would do us a world of good but seems to keep failing"
- The `_install_fonts_to_user_dir()` function copies TTFs to `%LOCALAPPDATA%/Fonts/` on Windows but does NOT call the Win32 `AddFontResource` API or broadcast `WM_FONTCHANGE`. Windows may not pick up the fonts until next session restart — or at all, depending on the Tk version.

**Why it matters:** If fonts aren't loading on Windows, the user sees system sans (Segoe UI) for everything. The "stadium scoreboard feel" from Oswald never materializes. The italic voice phrases from Inter Italic render as upright system text. The mono numbers from JetBrains Mono render as proportional system text. **The visual differentiation the plan promised is invisible.**

**Verification method:** Ship a one-line debug script that prints `tk.fontFamilies()` to a file. Ask the user to run it + send back the file. If "Inter" / "Oswald" / "JetBrains Mono" / "Source Serif Pro" are NOT in the list, the fonts are NOT loading on Windows.

**Proposed fix:** Call `AddFontResource` via ctypes on Windows in `_install_fonts_to_user_dir()`. Broadcast `WM_FONTCHANGE` so other apps pick up the change. This is a 5-line code change.

### #4. The visual changes are too subtle to perceive (PROBABILITY: MEDIUM-HIGH)

**Evidence:**
- `bg_card_elevated` changed from `#252a33` → `#262a30` per Fix #6 "warmer, more red, less blue." Luminance delta: ZERO (both are ~lum 42). The change is a hue shift of ~5° — invisible to the human eye.
- `noise_grain.png` is 3% opacity (alpha 5-12 out of 255). Below threshold of perception on most monitors.
- `chain_link_dim.png` is 8% opacity on the GradientHeader. Barely visible.
- `cage_watermark.png` is 5% opacity in the bottom-right corner. Invisible.
- The depth delta between shell (lum 24) and card (lum 42) is 18 — visible but not dramatic.
- The font differentiation between Inter-Regular and Inter-Medium is ~5% weight — barely perceptible.

**Why it matters:** The user said "need textures or backgrounds or both and rounded buttons to give it a polished look." Each of these changes IS technically present (textures applied, button corner_radius 4→10), but the magnitudes are below the threshold of perception. The user is looking for DRAMATIC change, not subtle improvement.

**Verification method:** Compare screenshots from before Phase 2.5 vs after DASH-V2 SIGNOFF. If the differences are imperceptible, this is confirmed.

**Proposed fix:** Increase magnitudes — noise_grain to 8% opacity, chain_link to 15% opacity, cage_watermark to 12% opacity, depth delta to 30+ (e.g., shell #0a0c10 lum 5, card #2a2f38 lum 45). The user wants to SEE the change, not feel it.

### #5. The cache rebuild for the interpretation layer never fired (PROBABILITY: HIGH)

**Evidence:**
- The audit doc (UI_REDESIGN_INTERPRETATION_AUDIT.md §2.1) identified: "The '8 variants per label' expansion in the code has NOT propagated to the production DB. The cache still uses the original 3-variant picker output."
- Root cause: `snapshot_cache.ENGINE_VERSION` was NOT bumped from "1.5.0" when the `_EXT` pickers were added.
- DB query confirms: there is NO `interpretation_engine_meta` table at all. There is no `snapshot_cache_state` table. The `fighter_descriptors.snapshot_version = 1` for ALL 4,450 fighters.
- The audit's P0 fix was: "Bump `snapshot_cache.ENGINE_VERSION` from '1.5.0' to '1.6.0' (or '2.0.0') to force cache rebuild with existing `_EXT` pickers. 1 line of code."
- The GUI_PLAN §9.1 Phase 0 says: "Phase 0: P0 Interpretation Fix (Effort: S, 1 hour). Bump `snapshot_cache.ENGINE_VERSION` from '1.5.0' to '1.6.0'. Forces cache rebuild on next Advance Day."
- **This was never done.** The Phase 0 fix is the single highest-impact, lowest-effort change in the entire plan, and it was skipped.

**Why it matters:** Even if the user runs the simulation forward 30 days, the cache won't rebuild with the new 8-variant phrases unless ENGINE_VERSION is bumped. The user will see "Holding Steady" 1,459 times forever.

**Verification method:** Query `fighter_descriptors` for distinct momentum phrases. If only 15 distinct phrases appear (the original 3-variant × 5 labels), the cache is stale. (Confirmed: this is the current state.)

**Proposed fix:** 1-line code change. Bump ENGINE_VERSION. Force rebuild on next Advance Day.

### #6. Components built but the visual richness isn't reaching the screen (PROBABILITY: LOW)

**Evidence:**
- Verified in dashboard.py: 16 of 24 components are imported AND USED. The render methods pack them with real data.
- The Sparkline component is wired to `_query_cash_history` (7-day cash) — but only 10 finance_transactions exist, all on 2026-01-01, so the sparkline shows a flat line.
- The MomentumRing is wired to `fighter_descriptors.momentum` label — but 98.3% are "stable" so the ring is the same color for all 3 watch cards.
- The FormMeter is wired to `fight_history.outcome` — 3,598 rows exist, so this DOES show varied W/L blocks. (This is the one component that works as designed.)

**Why it matters:** The components ARE used. The issue isn't "built but not used" — it's "used but fed monotonic data." This is the same root cause as #1.

**Verification method:** Run with `CAGE_EMPIRE_DASH_DEBUG=1` and check the log output. If the queries return varied data but the components render identically, this is a component bug. If the queries return monotonic data, this is #1.

### #7. The fundamental CTk approach can't deliver the visual richness (PROBABILITY: LOW)

**Evidence:**
- The user linked a CTk demo GIF showing gradients, smooth animations, polished transitions.
- The current build uses PIL compositing for gradients (GradientCard, GradientHeader), PIL for sparklines/rings/form blocks, and CTk Canvas for animations (AttributeBar 400ms ease-out, BeatBar 1s pulse).
- The visual plan §10 Q3 explicitly rejected real drop shadows via PIL compositing per-frame ("~15ms × 30 cards = 450ms per refresh — over budget") in favor of 1px borders + 4-tier bg depth.

**Why it matters:** This is the strategic question. If CTk can't deliver, the project should pivot frameworks. **But the evidence suggests CTk CAN deliver** — the demo GIF the user linked almost certainly uses the same techniques we're already using (Canvas drawing, PIL compositing, custom-drawn widgets). The issue isn't the framework; it's the execution (subtle magnitudes, broken data, stale cache).

**Verification method:** Build ONE screen (the Dashboard) with DRAMATIC visual richness — full-bleed cage-fence background at 15% opacity, hero portrait of an actual fighter, 30+ luminance delta between shell and card, animated gold gradient on the Top Story card. If the user still says "no difference," CTk is the wrong framework. If the user says "wow," CTk is fine — the issue was execution.

**Proposed fix:** See §4 of this doc (the "WOW" items). Stay with CTk.

---

## 5. "What Would Actually Make the User Say WOW" — 10 Concrete Items

Based on the Soul doc, the spec PDF, and the user's complaints, here are 10 specific things that would make the user feel genuine improvement. Each is concrete (not "better visuals" but a specific change), tied to a Soul fantasy, addressing a specific complaint, with estimated effort.

### 1. Run the simulation forward 30 in-game days (Effort: S, 1 hour)

**What:** Execute a script that calls `services.clock.advance_day(conn)` 30 times, populating `news_items`, `events` (with `status='scheduled'` for future events), `finance_transactions` (with daily cash flows), `fight_history` (with weekly fight results), and `daily_headlines` (with fresh headlines).

**Soul fantasy served:** All 5 (anticipation requires the world to be alive + changing).

**User complaint addressed:** "no data was being pulled through to the new dashboard design" — this is the LITERAL fix.

**Why it matters:** The Dashboard's News section is currently EmptyState. After this run, it'll have 5+ news items. The Next Event section will show a real upcoming event with countdown. The cash sparkline will trend. The daily_headlines will rotate. **This single 1-hour script run will produce more visible change than the last 3 UI rewrites combined.**

### 2. Bump ENGINE_VERSION to force cache rebuild (Effort: S, 1 line of code)

**What:** Add a line to `snapshot_cache.py` (or wherever ENGINE_VERSION is defined) that bumps it from "1.5.0" to "1.6.0". On the next Advance Day, the interpretation layer will rebuild all 4,450 fighter_descriptors with the 8-variant `_EXT` phrase banks.

**Soul fantasy served:** All 5 (variety is the substrate of "translate simulation into emotion").

**User complaint addressed:** "the four screens remain exactly the same so diagnose why" — the cache rebuild will change the phrases visible on the Fighter Watch cards + Roster table.

**Why it matters:** Cuts perceived repetition ~60% for momentum/pressure/career_phase. The audit's #1 recommendation. **This was supposed to be Phase 0 of the visual redesign. It was skipped.**

### 3. A full-bleed cage-fence background texture on the Dashboard at 15% opacity (Effort: S, 1 hour)

**What:** Tile `chain_link_dim.png` (or a new higher-contrast variant) across the Dashboard's `bg_base` at 15% opacity (up from 3% for noise_grain + 8% for chain_link on header). Add a vignette darkening the edges (use the existing `vignette_fight_night.png`). Make the player feel like they're looking at a promoter's desk in an arena.

**Soul fantasy served:** Empire Builder (the control room metaphor from GUI_PLAN §4.1).

**User complaint addressed:** "need textures or backgrounds or both" + "still something missing to give it a friendlier feel."

**Why it matters:** The current 3% opacity noise_grain is below the threshold of perception. 15% opacity chain-link is visible without being distracting. The texture makes the screen feel like a real surface, not a flat fill.

### 4. A real scheduled event with a countdown timer (Effort: M, 2-3 hours)

**What:** After running the simulation forward (item #1), the Next Event section should show a real upcoming event with: event name, date, main event matchup, title fight indicator (if applicable), and a live countdown ("3 days, 14 hours until fight night"). Add a "Build Card" CTA if no event is scheduled within 14 days.

**Soul fantasy served:** All 5 (anticipation is the real dopamine — the event next month is one of the 6 anticipation hooks the Soul doc lists).

**User complaint addressed:** "no data was being pulled through" + "still something missing."

**Why it matters:** The Next Event card is the Dashboard's primary anticipation hook. Currently it always shows the fallback (most recent completed event). A real countdown gives the player a reason to click Advance Day.

### 5. A hero "Top Story" with a real fighter portrait (Effort: M, 3-4 hours)

**What:** Replace the GradientCard-wrapped Top Story text with a hero card: full-bleed gradient background, 96×96 portrait (procedurally generated initials-based — the visual plan §8.2 P1 promised this script), fighter name in Oswald display font, LONG variant headline ("the wunderkind everyone's talking about"), 2-sentence body in Inter italic, topic chips (DataChip with topic icons once P0 icons ship).

**Soul fantasy served:** Talent Hunter (the prospect I just signed) + Kingmaker (I create stars).

**User complaint addressed:** "maybe some MMA elements/visuals that shows its a MMA sim" + "still something missing to give it a friendlier feel."

**Why it matters:** The Top Story is the first thing the player sees. Currently it's a stale 1-template headline with no portrait. A hero card with portrait + LONG variant headline + topic chips would be the single most visible "wow" change.

### 6. Increase luminance delta between shell and cards to 30+ (Effort: S, 1 hour)

**What:** Change `bg_card_elevated` from `#262a30` (lum ~42) to `#2f343d` (lum ~50) or even `#343a45` (lum ~55). Keep `bg_surface` at `#15181f` (lum ~24). Delta goes from 18 → 26-31. Visible richness without being garish.

**Soul fantasy served:** Empire Builder (the control room should feel like a Bloomberg Terminal, not a void).

**User complaint addressed:** "styling rarely changes much in each iteration" — this WILL be visibly different.

**Why it matters:** The current delta of 18 is on the edge of perception. A delta of 30+ is unambiguously visible. The user will see "depth" instead of "flat darkness."

### 7. A pre-fight build-up screen (Phase 7a — Effort: L, 5-7 days)

**What:** Build just the Pre-Fight Build-Up phase of the Fight Resolution screen (per GUI_PLAN §7.1). Tale of Tape (two fighter portraits side-by-side with stats comparison), pundit predictions (3 named pundits with headshots + 1-sentence prediction each), memory setup (gold-tinted card showing prior meetings between these two fighters), storyline context (rivalry heat meter + history blurb). NO live fight yet — just the buildup. End with a "▶ Start Fight" button that's a placeholder for Phase 7b.

**Soul fantasy served:** All 5 (the marquee dopamine moment the Soul doc promises).

**User complaint addressed:** "the four screens remain exactly the same" — this is a FIFH screen, not a rewrite of an existing one. Visible change guaranteed.

**Why it matters:** The user has been testing Office Mode for weeks. The Fight Night screen is the payoff. Even just the Pre-Fight Build-Up (no live fight) would give the user a taste of the marquee moment + validate the visual richness library at full intensity.

### 8. Verify fonts load on the user's Windows machine (Effort: S, 30 minutes)

**What:** Ship a one-line debug script: `import tkinter; root = tkinter.Tk(); root.withdraw(); print(sorted(root.tk.call("font", "families"))); root.destroy()`. Save output to `font_check.txt`. Ask the user to run it + send back the file.

**Soul fantasy served:** All 5 (typography is the substrate of voice).

**User complaint addressed:** "better fonts would do us a world of good but seems to keep failing."

**Why it matters:** If "Inter" / "Oswald" / "JetBrains Mono" / "Source Serif Pro" are NOT in the user's font list, every "font fix" we ship is invisible. **We need to know if the fonts are actually loading on the user's machine before shipping any more font-related changes.**

### 9. Generate the 32 P0 icons (Effort: M, 2-3 days)

**What:** Commission or AI-generate 32 icons (14 nav + 8 status + 10 topic) in Lucide/Phosphor outlined style, 2px stroke, single-color (gold). Wire them into the sidebar (nav icons), the FighterRow (status icons: champion = gold star, injured = red cross), and the NewsCard (topic icons).

**Soul fantasy served:** All 5 (icons are the single most fixable "database tool" tell).

**User complaint addressed:** "still something missing to give it a friendlier feel" + "are we still using default customtkinter themes because the styling rarely changes much in each iteration."

**Why it matters:** The visual plan §8.1 identified this as a P0 BLOCKER. The sidebar is text-only. Adding icons is the single highest-impact visual change for the lowest effort.

### 10. A "Fighter of the Week" spotlight with rotating voice (Effort: M, 3-4 hours)

**What:** A new Dashboard section between Top Story and Promotion Status. Each week (in-game), the spotlight rotates to a different fighter — could be a champion, a rising prospect, a veteran in decline, a rivalry participant. The spotlight shows: hero portrait, fighter name in Oswald, a 3-sentence LONG-variant narrative (champion reads differently from prospect reads differently from veteran), career stats (record, ranking, title reign), and a "View Profile" CTA.

**Soul fantasy served:** Historian (the player remembers arcs) + Talent Hunter (the prospect I just signed) + Kingmaker (the star I created).

**User complaint addressed:** "the four screens remain exactly the same" — this is a new section that ROTATES, so it visibly changes weekly.

**Why it matters:** The Soul doc says "nobody remembers Striking = 87 five years later. They remember: 'That kid I found in Mexico.'" The Fighter of the Week spotlight is the machinery that creates those memories. It requires the LONG-variant system (item #2 + the audit's P1 fix).

---

## 6. Framework Pivot Recommendation

**Recommendation: STAY with CustomTkinter. Do NOT pivot.**

### Reasoning

**Can CTk deliver the visual richness the user wants?** YES, based on:

1. **Gradients:** Already implemented via PIL compositing in `GradientCard`, `GradientHeader`, `MomentumRing`, `FormMeter`, `Sparkline`. The `_pil_utils.py` (21 KB) has 4 cached primitives (gradient, sparkline, momentum_ring, form_block) with a two-level cache. This is the same technique the user's linked CTk demo GIF almost certainly uses.

2. **Animations:** `AttributeBar` (400ms ease-out fill, 60fps, verified in worklog line 13515) + `BeatBar` (1s pulse cycle, gold↔gold_bright) both work. CTk's `after()` method supports frame-rate animations.

3. **Polished transitions:** Screen fade-ins are NOT implemented, but they're possible via CTk's `after()` + opacity manipulation. Hover effects ARE implemented (every component has hover states).

4. **Custom-drawn visualizations:** The `Sparkline`, `MomentumRing`, and `FormMeter` are custom-drawn via PIL. The cage heatmap (planned for Fight Night Phase 7b) would use the same Canvas widget technique.

**The CTk demo GIF the user linked almost certainly uses:**
- PIL compositing for gradients (we do this)
- Canvas drawing for custom visualizations (we do this in _pil_utils.py)
- `after()` callbacks for animations (we do this in AttributeBar/BeatBar)
- Custom widget subclasses (we have 24 of these)

**We are NOT missing any techniques.** The issue is execution, not framework.

### Why NOT pivot to PyQt6 / pywebview / DearPyGui?

1. **Migration cost:** 6-12 weeks of rewrite. The user is already frustrated with the pace. A pivot would extend the timeline by 3+ months.

2. **No guarantee of better results:** The user's complaints (no data, stale cache, subtle visuals, fonts not loading) are FRAMEWORK-AGNOSTIC. PyQt6 would have the same data issues. pywebview would have the same font loading issues. DearPyGui would have the same subtle-magnitude issues.

3. **The visual plan §3 explicitly rejected alternatives:** "Rejected alternatives (no change): PySide6/PyQt6 (license/size), pywebview (two-language overhead), Flet (maturity), DearPyGui (wrong paradigm), Kivy (touch-first), PyGObject (painful cross-platform)."

4. **The supervisor already locked the framework:** GUI_PLAN §3 says "Status: Locked. No changes."

### What we SHOULD do instead

1. **Fix the data** (items #1 + #2 above). This is the single biggest lever.
2. **Verify fonts load on Windows** (item #8). If they don't, fix the Windows font registration (call `AddFontResource` via ctypes).
3. **Increase visual magnitudes** (items #3, #6, #9). The current visuals are too subtle.
4. **Build the Pre-Fight Build-Up screen** (item #7). Give the user a taste of the marquee moment.
5. **Give the user a non-techy cache-clear instruction.** The supervisor is already planning this.

If after items #1-#5 the user STILL says "no difference," THEN consider a pivot. But the evidence strongly suggests the issue is execution, not framework.

---

## 7. The Single Most Important Thing the Supervisor Should Do Next

**Run the simulation forward 30 in-game days + bump ENGINE_VERSION.**

This is 1 hour of script-running + 1 line of code. It will produce more visible change than the last 3 UI rewrites combined. It addresses the user's #1 complaint ("no data was being pulled through") directly. It enables every other "WOW" item in this doc (the sparkline needs cash history, the Next Event needs scheduled events, the Fighter Watch needs varied momentum phrases, the Top Story needs fresh headlines).

**After this is done**, the supervisor should:
1. Give the user a non-techy cache-clear instruction (already planned).
2. Ship the font-check debug script (item #8).
3. Wait for user feedback. If the user says "wow, this is different," the diagnosis was correct. If the user STILL says "no difference," the issue is fonts on Windows (item #8 will confirm) OR stale `__pycache__` (item #2 will confirm).

**Do NOT start Phase 3 (App Shell Rewrite) or any new screen until the data + cache + font verification is done.** The current 4 screens are sufficient to validate the visual richness library. Adding more screens on top of broken data will just produce more "no difference" feedback.

---

## 8. Appendix: DB State Snapshot (2026-08-02)

| Table | Row count | Notes |
|---|---|---|
| `news_items` | **0** | EMPTY. The Dashboard's News section ALWAYS shows EmptyState. |
| `daily_headlines` | **4** | All from world-seed day. Same 4 headlines forever. |
| `fighter_descriptors` | 4,450 | All `snapshot_version=1`. Cache never rebuilt. 98.3% `momentum='stable'` with 3 phrase variants. |
| `fighters` | 4,450 | 3,999 male + 451 female. |
| `events` | 1,884 | ALL `status='completed'`. ZERO scheduled. |
| `fights` | 1,799 | — |
| `fight_history` | 3,598 | — |
| `finance_transactions` | **10** | ALL on 2026-01-01 (opening balance). Cash sparkline is flat. |
| `titles` | (not queried for count) | 6 active champions per worklog. |
| `promotions` | 10+ | Player can pick from 10. Promo 1 (Alpha Combat Federation) has $50M cash, 85 reputation, 75 fan_trust. |

### Top 10 momentum phrases in production DB

```
1501x  'neither hot nor cold right now'
1459x  'holding steady'
1416x  'form has been consistent'
  15x  'needs to turn things around'
  11x  'trending upward fast'
  11x  'sliding in the wrong direction'
   7x  'form is dipping'
   6x  'the wheels are coming off'
   5x  'building serious momentum'
   4x  'riding a hot streak'
```

**The top 3 phrases account for 4,376 / 4,450 = 98.3% of all fighters.** The 8-variant `_EXT` phrases (e.g., "scorching the earth on the way to a title shot", "white-hot and nobody's got the answer", "the slide is on and the camp knows it") appear NOWHERE in the cache.

### The 4 daily_headlines in production DB

```
[top_story]      "The prodigy turns heads again"
                 "Hiroki Nakamura keeps proving the hype is real. The division's brightest young talent continues to surge."

[fastest_rising] "Hiroki Nakamura is rising fast"
                 "The hottest hand in the division belongs to Hiroki Nakamura. The surge continues — opponents take notice."

[biggest_fall]   "Daniel Gonzalez is sliding fast"
                 "The fall continues for Daniel Gonzalez. Once a name to fear — now a fighter searching for answers."

[upset_of_week]  "Jack Taylor stuns Silvio Guerra"
                 "Jack Taylor pulled off a heavy underdog this week, finishing Silvio Guerra by unanimous decision. The division takes notice."
```

**Compare to the Soul doc's voice:**
- Soul: "That kid I found in Mexico. Nobody wanted him. He became a champion. Retired undefeated. Now his son is fighting."
- DB: "Hiroki Nakamura is rising fast"

The gap is enormous. The DB phrases are sports-page clichés. The Soul doc's voice is promoter-flavored, past-tense narrative, specific imagery. **The headline_engine needs the 8-variant-per-(type, family) expansion the audit's P1 fix promised — AND the variants need to be re-authored in the CAGE EMPIRE voice, not the journalist-neutral voice.**

---

## 9. End of Analysis

This document is brutally honest by design. The supervisor needs the truth, not reassurance. The current approach is NOT failing — the visual redesign plan is sound, the components are well-built, the theme system is solid. **What's failing is the data layer + the cache + the font verification on Windows.** Fix those three things (1 hour + 1 line + 1 debug script) before writing any more UI code.

The user is right to be frustrated. The user is right to halt and re-plan. The user is right to demand a non-techy cache-clear instruction. **The user is NOT wrong about the visuals being subtle — they ARE subtle. The user is NOT wrong about the data being missing — it IS missing.**

Listen to the user. Fix the data first. Then judge the visuals.

---

*End of REPLAN-A Gap Analysis. Authored 2026-08-02. No code changes were made. Awaits supervisor review.*
