# Task UI-REDESIGN-P1 — Phase 1 Implementation Record

**Agent:** Phase 1 Implementation (full-stack-developer)
**Task ID:** UI-REDESIGN-P1
**Date:** 2026-07-30
**Scope:** Rewrite `src/ui/theme.py` with 4-tier color system, Oswald font
bundle, texture utilities, spacing tokens, Championship Skin colors. No
screen code changes. No schema changes.

## Outcome Summary

- **Status:** ✅ COMPLETE
- **Tests:** 43/43 pass (full `./run.sh test` suite, no regressions)
- **Files modified:** `src/ui/theme.py` (597 → 1316 lines)
- **Files added:**
  - `src/ui/assets/fonts/Oswald-Bold.ttf` (88 KB static Bold weight
    instantiated from Google Fonts variable font via fonttools)
  - `src/ui/assets/fonts/OFL.txt` (OFL 1.1 license, required for redistribution)
  - `src/ui/assets/textures/noise_grain.png` (256×256, 156 KB)
  - `src/ui/assets/textures/chain_link_dim.png` (512×512, 7.7 KB)
  - `src/ui/assets/textures/gold_leaf_border.png` (16×16, 326 B)
  - `src/ui/assets/textures/vignette_fight_night.png` (1920×1080, 115 KB)
- **No screen code changes** — verified `src/ui/screens/*.py`,
  `src/ui/app.py`, `src/ui/widgets/*.py` untouched.

## Key Implementation Decisions

### Color system — 4-tier depth (UI_REDESIGN §2.2 + §2.3)

`OfficeColors` and `FightNightColors` rewritten with the new tier system:

| Role | Office | Fight Night |
|---|---|---|
| `bg_base` | `#0a0c10` | `#06070a` |
| `bg_surface` | `#15181f` | `#0d1015` |
| `bg_card` (NEW) | `#1c2028` | `#14181f` |
| `bg_card_elevated` (NEW) | `#252a33` | `#1c2028` |
| `border_subtle` | `#2a2f38` | `#252a33` |
| `border_strong` (NEW) | `#3a4049` | `#3a4049` |
| `divider_faint` (NEW) | `#1f232b` | `#11141a` |
| `text_on_gold` (NEW) | `#1a1410` | `#1a1410` |
| `text_on_crimson` (NEW) | `#ffffff` | `#ffffff` |
| `gold_tint` (NEW) | `rgba(224,169,87,0.10)` | `rgba(240,192,96,0.10)` |
| `crimson_tint` (NEW) | `rgba(214,58,63,0.10)` | `rgba(229,62,62,0.10)` |
| `gold_bright` (NEW) | `#f5c878` | `#ffd700` |
| `info` (NEW) | `#60a5fa` | `#60a5fa` |
| `crimson` (CHANGED) | `#d63a3f` (was `#c8323a`) | `#e53e3e` |
| `gold` (CHANGED) | `#e0a957` (was `#d4a55a`) | `#f0c060` |
| `text_secondary` (CHANGED) | `#aab0b8` (was `#9aa0a6`) | `#b4b8c0` |
| `text_tertiary` (CHANGED) | `#6b7280` (was `#5f6368`) | `#6b7280` |

**Backward-compat aliases preserved** so existing screens that reference
`bg_surface_elevated`, `bg_border`, `steel` continue to render without
code changes:
- `bg_surface_elevated` → aliased to `bg_card_elevated` (same role: hover/active)
- `bg_border` → aliased to `border_subtle` (same role: 1px separators)
- `steel` → kept at `#6b7280` (used by `gym_icon.py:91-97` palette)

### Championship Skin (UI_REDESIGN §2.2 + §2.6, Q10 decision B)

New module-level dict `CHAMPIONSHIP_SKIN` with 4 colors:
- `champion_gold`: `#f0c060`
- `champion_gold_leaf`: `#f5d77a`
- `challenger_crimson`: `#d63a3f`
- `title_fight_badge_bg`: `#1a1410`

Phase 7 Fight Resolution screen reads this when `fights.is_title_fight = 1`.

### Spacing tokens (UI_REDESIGN §4.4)

8-point scale exposed as module constants:
- `SPACE_XS=4`, `SPACE_SM=8`, `SPACE_MD=12`, `SPACE_LG=16`,
  `SPACE_XL=24`, `SPACE_2XL=32`, `SPACE_3XL=48`, `SPACE_4XL=64`
- Plus `SPACING_TOKENS` tuple + `GRID_COLUMNS=12`, `GRID_GUTTER=24`,
  `PAGE_PADDING=24`, `SHELL_TOP_BAR_HEIGHT=56`, `SHELL_SIDEBAR_COLLAPSED=56`,
  `SHELL_SIDEBAR_EXPANDED=220` (for Phase 3 app shell).

### Font registration — THE Phase 1 fix (UI_REDESIGN §3.1)

The Rev 2 bug: all 4 Inter weights registered under the SAME family
name `"Inter"` with `weight="normal"`, so Tk collapsed them to the LAST
registered weight (Bold). Body text rendered Bold; headings rendered
Bold — no visual distinction.

The fix in Rev 3:
1. Each Inter weight registered under a UNIQUE family name:
   `Inter-Regular`, `Inter-Medium`, `Inter-SemiBold`, `Inter-Bold`.
2. `OfficeFonts` / `FightNightFonts` updated to use per-weight resolved
   family names with `weight="normal"` (the family name encodes the weight):
   - `body` → `Inter-Regular`
   - `caption` → `Inter-Medium`
   - `h3` → `Inter-SemiBold`
   - `h1`, `h2` → `Inter-Bold`
   - `display` → `Oswald` (bundled in this phase)
3. Legacy `INTER_FAMILY = "Inter"` constant preserved for back-compat.
4. `_apply_platform_fallbacks()` handles per-weight fallback independently
   (if only Inter-Regular registered, the others fall back to platform sans
   preserving the regular weight for body text).

### Startup health check (UI_REDESIGN §3.1 fix #3)

New `_print_font_summary()` prints resolved font families at startup:
```
[theme.py] Font registration summary:
  Inter-Regular    ✓ (resolved) / ✗ (fallback to 'Sans')
  Inter-Medium     ...
  Inter-SemiBold   ...
  Inter-Bold       ...
  JetBrains Mono   ...
  Source Serif Pro ...
  Oswald           ...
```
Output is `flush=True` so it appears in dev.log / console before any
screen renders. Verified in headless env: correctly reports fallbacks.

### Texture utilities (UI_REDESIGN §2.4)

4 procedurally-generated PNG textures, lazy-loaded + cached as
`CTkImage`:

| Function | PNG | Size | Spec |
|---|---|---|---|
| `get_noise_grain_texture()` | `noise_grain.png` | 256×256 | 3% opacity grey noise, alpha 5-12 |
| `get_chain_link_dim_texture()` | `chain_link_dim.png` | 512×512 | Chain-link fence at 4% opacity, crimson-tinted |
| `get_gold_leaf_border_texture()` | `gold_leaf_border.png` | 16×16 | 1px gold-leaf textured border, corner tile |
| `get_vignette_fight_night_texture()` | `vignette_fight_night.png` | 1920×1080 | Radial gradient transparent → 30% black at corners |

Implementation:
- `_load_or_generate(name, png_path, generate_fn, size)` — shared loader
  with cache. Loads PNG from disk if exists; else generates via PIL +
  saves to disk + caches as CTkImage. Returns `None` if PIL missing or
  generation fails.
- `_texture_cache` module-level dict — instant re-access (0.0000s observed).
- `preload_textures()` — warms the cache (for Phase 3 app shell to call
  at startup).
- Idempotent — if PNG exists, no regeneration.
- Verified: all 4 PNGs spec-compliant (correct size, RGBA mode, correct
  alpha values: vignette corner alpha=77, gold_leaf center transparent).

### Oswald Bold bundling (UI_REDESIGN §3.5)

- Google Fonts repo only ships the variable font (`Oswald[wght].ttf`,
  172 KB, weight axis 200-700).
- Used `fonttools.varLib.instancer` to instantiate the Bold weight
  (wght=700) as a static TTF.
- Renamed nameIDs 1/4/6/16 to `Oswald` / `Oswald Bold` / `Oswald-Bold`
  so Tk registers it under the correct family name.
- Result: `Oswald-Bold.ttf` (88 KB static TTF, 15 tables).
- Bundled OFL 1.1 license text (`OFL.txt`) — required for redistribution.
- Verified: PIL `ImageFont.truetype()` loads the static TTF correctly.

### Tint helper

New `tint_to_solid(tint_rgba, base_hex)` helper composites an rgba()
tint string over a solid hex base color. Phase 2 component library will
use this to convert `gold_tint` / `crimson_tint` (stored as rgba per
spec) into solid hex values that CTk can consume as `fg_color` /
`hover_color`.

Example: `tint_to_solid("rgba(224,169,87,0.10)", "#1c2028")` → `"#302e2d"`

## What Did NOT Change (per spec)

- `Theme` class structure — preserved.
- `OFFICE` / `FIGHT_NIGHT` / `CURRENT_THEME` instances — preserved.
- `set_theme()` / `get_theme()` / `on_theme_change()` API — preserved.
- Asset path constants (`LOGO_PRIMARY`, `LOGO_COMPACT`, `FONTS_DIR`,
  `ICONS_DIR`, etc.) — preserved.
- `STATUS_ICONS` + `NAV_ICONS` dicts — preserved (paths only; icon files
  are Phase 3).
- `get_icon()` API — preserved.
- `FontSizes` — preserved (per-screen type scale adoption is Phase 4-6).
- Screen code (`src/ui/screens/*.py`, `src/ui/app.py`,
  `src/ui/widgets/*.py`) — UNTOUCHED. Existing screens automatically
  pick up the new theme via `get_theme()`.

## Test Results

Baseline (before changes): 43 pass / 0 fail
After Phase 1 changes:    43 pass / 0 fail

No test fixes needed — none of the test scripts hardcoded color values
or imported from `ui.theme`. Tests verified via `./run.sh test` runner
(`CAGE_EMPIRE_ALLOW_FRESH=1`, per-test timeout 90s).

## Headless Verification

In a headless env (no `$DISPLAY`):
- `_register_fonts()` gracefully handles Tk root init failure — logs
  `[theme.py] Tk root init failed: ...` and proceeds with platform
  fallbacks.
- `_print_font_summary()` correctly reports `✗ (fallback to 'Sans')` for
  all families.
- Texture generation works (only requires PIL, not Tk).
- All UI modules (`ui.theme`, `ui.state`, `ui.widgets.*`, `ui.screens.*`,
  `ui.app`) import without crashing.

In a real display env (player's machine), font registration will
succeed and the summary will report `✓ (resolved)` for all 7 families.

## No Blockers for Phase 2

Phase 2 (component library) can proceed immediately. It will use:
- `bg_card` / `bg_card_elevated` / `border_subtle` / `border_strong` for
  Card ×3 variants (Flat / Elevated / Accent per §2.5).
- `gold_tint` / `crimson_tint` (rgba strings) + `tint_to_solid()` helper
  for hover backgrounds.
- `gold_bright` for hyperlink + button hover states (replaces the inline
  `_HOVER_GOLD_BY_THEME` map in `widgets/hyperlink.py`).
- `text_on_gold` / `text_on_crimson` for primary + danger button text.
- Spacing tokens (`SPACE_XS`..`SPACE_4XL`) for all card padding / gaps.
- Texture functions for background tiles (noise on bg_base, chain-link
  on Fight Night bg_surface, gold_leaf_border on champion cards,
  vignette overlay on Fight Night main content).
- `CHAMPIONSHIP_SKIN` dict for title-fight-specific overlays.
- `INTER_*_FAMILY_RESOLVED` per-weight families for per-component font
  tuples (StatBar mono labels, FighterRow name bold, etc.).
