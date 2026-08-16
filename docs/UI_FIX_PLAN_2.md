> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — UI Fix Plan 2 (v1.0)

> **Status:** PLANNING ONLY — awaiting supervisor sign-off. NO CODING done.
> **Source:** `/home/z/my-project/upload/Instructions.txt` (20 instructions from user)
> **Analysed by:** Plan subagent (architecture role) + Supervisor review

## Executive Summary

20 instructions → 6 workstreams:

| Workstream | Instructions | Risk |
|---|---|---|
| **A. Asset pipeline** (logos, icons, gym icons, portraits) | 1, 9, 15, 17 | Medium |
| **B. Voice/identity rewrites** | 2, 6, 11c, 12, 19 | Low |
| **C. Dashboard redesign** | 3, 4, 5, 7, 8 | Medium |
| **D. Table redesign** (replace ttk.Treeview) | 11, 11b, 11c, 12b, 13 | **HIGH** |
| **E. Fighter Profile overhaul** | 14, 15, 16, 17, 18, 19 | Medium |
| **F. Calendar + performance** | 3, 20 | Low/Medium |

## Execution Order

### Phase 1 — Foundations (do first)
- 14 (nav back-stack — unblocks 5, 7, 13)
- 5 (HyperlinkLabel widget — unblocks 7, 13)
- 18 (hide Fighter Profile from nav)
- 3 (Week → January)
- 8 (Dashboard scrollable)
- 10 (Roster default to Male)

### Phase 2 — Asset pipeline (parallel to Phase 1)
- 1 (10 promotion logos via image-generation)
- 9 (Roster small promo logo)
- 15 (Portrait 256×256 + smart-crop)
- 17 (Gym icons — procedural, NOT image-gen)
- ~20 section/status icons (instructions 4, 7, 12b, 16, 19)

### Phase 3 — Screen redesigns (depends on Phase 1 + 2)
- 11 (FighterTable widget — the big one)
- 11b (column changes: remove nickname, add age, abbreviate WC)
- 11c (column renames: "Stage", "Form", remove "Narrative")
- 13 (Roster hyperlinks)
- 12 + 12b (Free Agents rename + table redesign)
- 2 + 6 (voice renames)
- 4 (Top Story styling + icon)
- 7 (Promotion Status icons + champion hyperlinks)
- 16 (Fighter Profile modern styling)
- 19 (interpretation layer phrase expansion)

### Phase 4 — Performance (do last)
- 20 (profile + optimise: lazy refresh, debounce search, portrait cache, index audit)

## Key Architecture Decisions

### AD-1: Hyperlinks in CTk
Build `HyperlinkLabel` widget (`src/ui/widgets/hyperlink.py`). Subclass `CTkLabel` with gold text, hand cursor, hover effect, click → navigate to Fighter Profile.

### AD-2: Navigation back-stack
Add `_nav_stack: list[str]` to `GameState`. `set_active_screen` pushes previous screen. `go_back()` pops. Fighter Profile's back button calls `go_back()` with fallback to Roster.

### AD-3: Hidden Fighter Profile
Remove from `NAV_GROUPS` (sidebar). Keep screen registered with GameState. Accessible only via hyperlinks from Roster, Open Market, Dashboard, etc.

### AD-4: Gym icons (procedural)
300 gyms → procedurally generated via PIL. Octagonal shape (matches CAGE EMPIRE brand), deterministic color from gym_id hash, white initials. NOT image-gen (would take 5+ hours, inconsistent, illegible at 24×24).

### AD-5: Table redesign (FighterTable)
Replace ttk.Treeview with custom `FighterTable` widget (`src/ui/widgets/fighter_table.py`). Container = CTkScrollableFrame; rows = CTkFrame per fighter; cells = CTkLabel/HyperlinkLabel. Supports sorting, pagination, selection, hover, alternating colors, per-cell rich content. Keep Treeview as fallback flag.

### AD-6: Calendar change (Week → Month)
Safe — `simulation_clock` already stores `current_month` + `current_year`. "Week N" display is purely cosmetic, no logic reads it. Change is display-only.

### AD-7: Portrait sizing (256×256)
Confirmed good. Power-of-2, clean downsample from 512×512, reuse across screens (256 hero / 64 watch card / 32 table thumbnail). Add center-crop before resize for non-square source images.

## Voice Recommendations

### Screen/nav renames
| Current | Recommended |
|---|---|
| Dashboard | **The Empire** |
| Roster | **The Stable** |
| Free Agents | **Open Market** |
| Schedule | **Calendar** |
| News Feed | **The Wire** |
| Hall of Fame | **Legends** |
| Event Builder | **Build a Card** |
| Fight Resolution | **Fight Night** |
| Past Events | **The Archive** |
| Finance | **The Books** |
| Contracts | **Deals** |
| Rival Promotions | **The Competition** |
| Gyms | **Training Camps** |
| Titles | **Belts** |
| Rivalries | **Bad Blood** |
| Records | **The Record Book** |

### Column header renames
| Current | Recommended |
|---|---|
| Career Phase | **Stage** |
| Momentum | **Form** |
| Potential | **Ceiling** |
| Narrative | *(removed — discover on Fighter Profile)* |

### Section renames
| Current | Recommended |
|---|---|
| "PROMOTION STATUS" | **"The Empire"** |
| "── BIO ──" | **"Bio"** (drop ── decoration) |
| "── CAREER ──" | **"Career"** |
| "── RECENT FIGHTS ──" | **"Recent Fights"** |
| "── YOUR CHAMPIONS ──" | **"Your Champions"** |
| "── OTHER HEADLINES ──" | **"More Headlines"** |

## New Assets Needed

### Promotion logos (10 promotions × 2 sizes = 20 PNGs)
Generated via image-generation skill. Style: "Brutalist Luxury" — deep black background, metallic silver/gold accents, octagonal shield motif. Per-promotion differentiation:
- ACF (major, USA): gold + crimson, eagle crest, "ACF" monogram
- RFL (mid, USA): red + black, aggressive X motif, "RFL"
- PRC (mid, Japan): red + white, rising sun, "PRC"
- EFN (mid, UK): navy + gold, crown/lion, "EFN"
- SAW (small, Brazil): green + yellow, jaguar, "SAW"
- MBB (small, Mexico): red + green, eagle + snake, "MBB"
- NFN (small, Sweden): blue + silver, hammer, "NFN"
- EBC (small, Russia): red + gold, bear/star, "EBC"
- AOF (small, Australia): ochre + black, kangaroo, "AOF"
- FSC (small, France): blue + white, fleur-de-lis, "FSC"

### Section/status icons (~20 icons at 16×16 + 32×32)
top_story, cash, reputation, fan_trust, roster_count, champions_count, champion_belt, open_market, identity, bio, career, recent_fights, attributes, personality, stage, momentum_flame, pressure_weight, narrative_book, legacy_crown, trajectory_arrow

### Gym icons (300 — procedural, NOT image-gen)
Generated on-demand by `src/ui/widgets/gym_icon.py`. Octagonal shape, deterministic color, white initials.

### Portrait assets
User will upload 512×512 portraits. Code crops to square + resizes to 256×256. No asset gen needed.

## Performance Plan (Instruction 20)

1. **Profile first** — add timing decorator to key functions, click Advance Day 3x, observe log
2. **Lazy refresh** — only refresh visible screen + Dashboard (not all 6+ screens)
3. **Debounce search** — 200ms delay on Roster search keystrokes
4. **Portrait cache** — module-level LRU cache (200 entries)
5. **Cache hot queries** — _find_hottest_streak_fighter result cached until next Advance Day
6. **Index audit** — add missing indexes on hot columns (current_promotion_id, is_active, champion_fighter_id, fight_history.fighter_id, daily_headlines.headline_date)
7. **Verify interpretation pass <1s** — profile if needed

## Open Questions for Supervisor

1. Promotion logo style — match the per-promotion differentiation above? Or more uniform?
2. Voice renames — approve the recommendations? Any rejections?
3. Column headers — "Stage" / "Form" / "Ceiling" — too short? Alternatives?
4. FighterTable — confirm full Treeview replacement (vs re-skin)?
5. Gym icons procedural — acceptable? Or commission 300 image-gen icons?
6. Portrait size 256×256 — confirmed?
7. Performance profiling first — confirmed?
8. Asset generation — one batch or multiple sessions?
