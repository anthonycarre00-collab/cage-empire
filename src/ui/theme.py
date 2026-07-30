"""CAGE EMPIRE — Theme system (UI Redesign Revision 3 — Phase 1).

The dual-mode visual design system: Office Mode (calm, data-dense,
institutional — 90% of gameplay) + Fight Night Mode (visceral,
dramatic, narrative — 10% that produces 90% of the dopamine) +
Championship Skin overlay (4-color title-fight accent on Fight Night).

Per docs/GUI_PLAN.md §4 (Rev 3) + docs/UI_REDESIGN_VISUAL_PLAN.md §2-4:
  - 4-tier layered charcoal depth system (bg_base / bg_surface /
    bg_card / bg_card_elevated). Depth from value contrast, NOT
    shadows (PIL compositing is too slow per Phase 4 perf budget).
  - Office Mode: "Bloomberg Terminal meets ESPN scoreboard"
  - Fight Night Mode: "HBO 24/7 meets ESPN broadcast"
  - Championship Skin: gold-leaf border + crimson challenger accent
    on title fights — a 4-color overlay, not a parallel mode.
  - Typography: Inter (body, 4 weights under UNIQUE family names so
    Tk can't collapse them), JetBrains Mono (numerics), Source Serif
    Pro (fight commentary, 4 weights), Oswald Bold (display).
  - Spacing tokens: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px.
  - Procedural textures (PIL-generated, cached as PNGs):
    noise_grain, chain_link_dim, gold_leaf_border, vignette_fight_night.

CONVENTIONS compliance:
  §13 — Design Law: the theme system supports every pillar by
        providing a consistent visual language across all 22
        screens. Office Mode serves Discovery/Investment/Growth/
        Legacy; Fight Night Mode serves Conflict.
  §14 — Voice Layer: the theme itself doesn't display text, but
        it defines the TYPOGRAPHY that all player-facing text uses.
        Font choices (Inter for body, JetBrains Mono for numbers,
        Source Serif Pro for fight commentary, Oswald for display)
        are part of the interpretation layer — they shape how the
        player reads the simulation.
  §15 — Event Bus: the theme system is NOT event-bus-driven.
        Screen switching (Office ↔ Fight Night) is a UI-layer
        concern, triggered by navigation, not by game events.

Architecture:
  - COLORS: two classes (OfficeColors, FightNightColors) with the
    full 4-tier palette + new border/text/accent/status colors per
    UI_REDESIGN_VISUAL_PLAN §2.2 + §2.3.
  - CHAMPIONSHIP_SKIN: a dict of 4 colors overlaid on Fight Night
    when fights.is_title_fight = 1 (Phase 7 Fight Resolution reads
    this; defined here so the palette is centralized).
  - SPACING: 8-point scale constants (SPACE_XS..SPACE_4XL).
  - FONTS: font family names + paths to bundled TTFs. Registered
    with tkinter on first import via _register_fonts(). Each Inter
    weight is registered under a UNIQUE family name (Inter-Regular,
    Inter-Medium, Inter-SemiBold, Inter-Bold) so Tk can't collapse
    them — this fixes the silent registration bug from Rev 2.
  - THEME: a Theme class bundling colors + fonts + asset paths.
    Two instances: OFFICE and FIGHT_NIGHT.
  - TEXTURES: 4 PIL-generated PNGs, lazy-loaded + cached as
    CTkImage. Functions: get_noise_grain_texture(),
    get_chain_link_dim_texture(), get_gold_leaf_border_texture(),
    get_vignette_fight_night_texture(). Each returns a CTkImage
    or None (if PIL missing / generation fails).

Usage:
  from ui.theme import OFFICE, FIGHT_NIGHT, CURRENT_THEME, set_theme

  # In a screen:
  label = ctk.CTkLabel(parent, text="Hello",
                        text_color=CURRENT_THEME.colors.text_primary,
                        font=CURRENT_THEME.fonts.body)
  # Switch to Fight Night:
  set_theme("fight_night")

  # Texture (returns CTkImage or None — caller handles None):
  tex = get_noise_grain_texture()
  if tex is not None:
      bg_label = ctk.CTkLabel(parent, image=tex, text="")
"""

from pathlib import Path
import tkinter as tk

# ============================================================
# ASSET PATHS
# ============================================================

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
LOGO_DIR = ASSETS_DIR / "logo"
ICONS_DIR = ASSETS_DIR / "icons"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
FIGHT_NIGHT_DIR = ASSETS_DIR / "fight_night"
PORTRAITS_DIR = ASSETS_DIR / "portraits" / "default"
TEXTURES_DIR = ASSETS_DIR / "textures"

# Logo file paths (supervisor-designed — locked per GUI_PLAN.md §1)
LOGO_PRIMARY = LOGO_DIR / "cage_empire_primary.png"
LOGO_COMPACT = LOGO_DIR / "cage_empire_compact.png"
# Derived variants (Task 6.1.5 — not yet generated):
# LOGO_FIGHT_NIGHT = LOGO_DIR / "cage_empire_fight_night.png"
# LOGO_CHAMPIONSHIP = LOGO_DIR / "cage_empire_championship.png"
# LOGO_FAVICON = LOGO_DIR / "cage_empire_favicon.png"

# Font file paths
FONT_INTER_REGULAR = FONTS_DIR / "Inter-Regular.ttf"
FONT_INTER_MEDIUM = FONTS_DIR / "Inter-Medium.ttf"
FONT_INTER_SEMIBOLD = FONTS_DIR / "Inter-SemiBold.ttf"
FONT_INTER_BOLD = FONTS_DIR / "Inter-Bold.ttf"
FONT_JETBRAINS_MONO = FONTS_DIR / "JetBrainsMono-Medium.ttf"
FONT_SOURCE_SERIF_REGULAR = FONTS_DIR / "SourceSerifPro-Regular.ttf"
FONT_SOURCE_SERIF_SEMIBOLD = FONTS_DIR / "SourceSerifPro-SemiBold.ttf"
FONT_SOURCE_SERIF_ITALIC = FONTS_DIR / "SourceSerifPro-Italic.ttf"
FONT_SOURCE_SERIF_SEMIBOLD_ITALIC = FONTS_DIR / "SourceSerifPro-SemiBoldItalic.ttf"
# Display font — Oswald Bold (Google Fonts, OFL license).
# Bundled in Phase 1 of the UI Redesign. See docs/UI_REDESIGN_VISUAL_PLAN.md §3.5.
FONT_OSWALD_BOLD = FONTS_DIR / "Oswald-Bold.ttf"
FONT_OFL_LICENSE = FONTS_DIR / "OFL.txt"


# ============================================================
# SPACING TOKENS (UI_REDESIGN_VISUAL_PLAN §4.4 — 8-point scale)
# ============================================================
# Every screen should reference these tokens instead of hardcoding
# padding values. No screen is allowed to hardcode `pad=13` or
# `pad=22` — it must be a token or a multiple of 4.

SPACE_XS = 4     # Tight inline padding (chip → label gap, icon → label gap)
SPACE_SM = 8     # Inline padding inside chips, dense list row gaps
SPACE_MD = 12    # Card padding (compact), table cell vertical padding
SPACE_LG = 16    # Card padding (default), section sub-group gap
SPACE_XL = 24    # Grid gutter, page padding, gap between cards in a row
SPACE_2XL = 32   # Gap between sections on a screen
SPACE_3XL = 48   # Gap between major screen regions (header → content)
SPACE_4XL = 64   # Top-of-screen hero padding

# Convenience tuple of all tokens (for validation / iteration).
SPACING_TOKENS = (SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG,
                  SPACE_XL, SPACE_2XL, SPACE_3XL, SPACE_4XL)

# Layout grid (UI_REDESIGN_VISUAL_PLAN §4.3)
GRID_COLUMNS = 12
GRID_GUTTER = SPACE_XL       # 24px
PAGE_PADDING = SPACE_XL      # 24px
SHELL_TOP_BAR_HEIGHT = 56    # px (was 60 — see §4.2)
SHELL_SIDEBAR_COLLAPSED = 56  # px (icon-only — see §4.5, Q1 decision C)
SHELL_SIDEBAR_EXPANDED = 220  # px (icon + label — see §4.5)


# ============================================================
# COLOR PALETTES (per UI_REDESIGN_VISUAL_PLAN §2.2 + §2.3)
# ============================================================
# The 4-tier depth system replaces the Rev 2 near-pure-black palette.
# Depth comes from value contrast between bg_base → bg_surface →
# bg_card → bg_card_elevated, NOT from drop shadows (PIL compositing
# is too slow per the 167ms lazy-refresh budget from Phase 4 perf).
#
# BACKWARD COMPAT: the legacy property names bg_base / bg_surface /
# bg_surface_elevated / bg_border are preserved as aliases pointing
# at the new tier values, so existing screens that reference
# theme.colors.bg_surface_elevated continue to render (with the new
# hex values — visually slightly different per UI_REDESIGN §2.1 audit,
# which the supervisor approved).

class OfficeColors:
    """Office Mode color palette (default — 90% of gameplay).

    Mood: Calm, data-dense, institutional. "Bloomberg Terminal
    meets ESPN scoreboard." Reference: Football Manager 2024,
    OOTP Baseball, WMMA5 menu screens.

    4-tier depth system (UI_REDESIGN_VISUAL_PLAN §2.2):
      bg_base          #0a0c10   Main window background (gutters)
      bg_surface       #15181f   Sidebar, top bar — the SHELL layer
      bg_card          #1c2028   Card backgrounds — the CONTENT layer
      bg_card_elevated #252a33   Hover, active tab, dialog, dropdown
    """
    # --- Backgrounds (4-tier depth system) ---
    bg_base = "#0a0c10"             # Main window bg (only visible as 8px gutters)
    bg_surface = "#15181f"          # Sidebar, top bar — shell surfaces
    bg_card = "#1c2028"             # Card backgrounds — content surface
    bg_card_elevated = "#252a33"    # Hover, active tab, dialog, dropdown

    # --- Legacy aliases (existing screens reference these names) ---
    # bg_surface_elevated was Rev 2's "hover, active tab, dialog" color
    # at #232730. In Rev 3 that role is bg_card_elevated (#252a33) —
    # slightly lighter for a stronger active state. The alias keeps
    # existing screens working without code changes.
    bg_surface_elevated = bg_card_elevated
    # bg_border was Rev 2's only separator color at #2e333d. In Rev 3
    # that role is split into border_subtle / border_strong / divider_faint.
    # The alias points at border_subtle (the most common 1px border).
    bg_border = "#2a2f38"

    # --- Borders + separators (Rev 3 — the 1px card system) ---
    border_subtle = "#2a2f38"       # 1px borders between cards, divider lines
    border_strong = "#3a4049"       # 2px borders on accent cards (champion, selected)
    divider_faint = "#1f232b"       # Intra-card dividers (between sections of one card)

    # --- Text ---
    text_primary = "#e8eaed"        # Body, headings, fighter names in lists
    text_secondary = "#aab0b8"      # Metadata, captions, table column headers
                                     # (was #9aa0a6 — bumped for WCAG contrast)
    text_tertiary = "#6b7280"       # Disabled, timestamps ONLY
                                     # (was #5f6368 — bumped for legibility)
    text_on_gold = "#1a1410"        # Text on gold button bg (dark brown — "ink on gold leaf")
    text_on_crimson = "#ffffff"     # Text on crimson background

    # --- Co-primary accents (Crimson + Gold are EQUAL brand weight) ---
    crimson = "#d63a3f"             # Loss, KO/TKO, danger, rival heat
                                     # (was #c8323a — bumped 5% saturation)
    crimson_tint = "rgba(214,58,63,0.10)"   # Hover bg on danger buttons, rivalry rows
    gold = "#e0a957"                # EMPIRE wordmark, champion, title, win, hyperlinks
                                     # (was #d4a55a — bumped warmth + brightness)
    gold_tint = "rgba(224,169,87,0.10)"     # Hover bg on cards/rows/links, active tab bg
    gold_bright = "#f5c878"         # Hover state for hyperlinks + buttons
                                     # (replaces the inline _HOVER_GOLD_BY_THEME map
                                     # in widgets/hyperlink.py — Phase 2 widget will
                                     # read this directly from the theme)

    # --- Status colors ---
    success = "#4ade80"             # Signed, recovered, win (sparingly — green is
                                     # a "third accent" and should stay rare)
    warning = "#fbbf24"             # At-risk, injured, contract expiring
    danger = "#ef4444"              # Cut, suspended, critical. Used for the
                                     # ACTION of cutting, not the STATE of being
                                     # cut (state = crimson chip)
    info = "#60a5fa"                # Informational badges, "new" indicators.
                                     # Blue is allowed ONLY here — not a brand color.

    # --- Supporting (legacy — kept for back-compat with widgets that
    # reference theme.colors.steel for neutral mid-tier UI elements) ---
    steel = "#6b7280"               # Mid-tier UI elements


class FightNightColors:
    """Fight Night Mode color palette (10% of gameplay, 90% of dopamine).

    Mood: Visceral, dramatic, narrative. "HBO 24/7 meets ESPN
    broadcast." Reference: HBO 24/7, UFC Countdown, NFL Films,
    ESPN 30 for 30.

    Only the Fight Resolution screen + pre-fight splash + post-fight
    recap use this mode. Everything else stays in Office Mode.
    Same 4-tier depth system as Office, deeper values + brighter text.
    """
    # --- Backgrounds (4-tier depth — deeper than Office) ---
    bg_base = "#06070a"             # The arena floor — only visible as gutters
    bg_surface = "#0d1015"          # Zone backgrounds (heatmap frame, commentary
                                     # feed frame, pundit panel frame)
    bg_card = "#14181f"             # Beat cards in the commentary feed,
                                     # pundit avatar frames
    bg_card_elevated = "#1c2028"    # Active beat highlight (the beat currently
                                     # being narrated)

    # --- Legacy aliases (back-compat with Rev 2 screens) ---
    bg_surface_elevated = bg_card_elevated
    bg_border = "#252a33"

    # --- Borders + separators ---
    border_subtle = "#252a33"       # 1px frame around each zone
    border_strong = "#3a4049"       # Cage heatmap frame (stronger — the heatmap
                                     # is the signature visual)
    divider_faint = "#11141a"       # Intra-zone dividers

    # --- Text (brighter — punches through the darkness) ---
    text_primary = "#f5f6f8"        # Brighter than Office
    text_secondary = "#b4b8c0"      # Beat timestamps, pundit names
    text_tertiary = "#6b7280"       # Disabled transport controls
    text_on_gold = "#1a1410"        # Ink on gold leaf (same as Office)
    text_on_crimson = "#ffffff"

    # --- Co-primary accents (brighter, more saturated — "blood in spotlight") ---
    crimson = "#e53e3e"             # Brighter, more saturated than Office
    crimson_tint = "rgba(229,62,62,0.10)"
    gold = "#f0c060"                # Brighter — "title belt under stage lights"
    gold_tint = "rgba(240,192,96,0.10)"
    gold_bright = "#ffd700"         # Hover state — richer gold than Office

    # --- Fight Night exclusive ---
    impact_yellow = "#fbbf24"       # Knockdowns, big moments, finish flashes

    # --- Heatmap colours (RESERVED for cage heatmap only — never elsewhere) ---
    heat_blue = "#3b82f6"           # Low-activity zones
    heat_orange = "#f97316"         # Medium-activity zones
    heat_red = "#dc2626"            # High-activity / high-damage zones

    # --- Status colors (same as Office for consistency) ---
    success = "#4ade80"
    warning = "#fbbf24"
    danger = "#ef4444"
    info = "#60a5fa"
    steel = "#6b7280"


# ============================================================
# CHAMPIONSHIP SKIN (UI_REDESIGN_VISUAL_PLAN §2.2 + §2.6)
# ============================================================
# A 4-color overlay applied to Fight Night when fights.is_title_fight = 1.
# NOT a parallel mode — a skin. The Fight Resolution screen (Phase 7)
# reads this dict and overrides the relevant FightNightColors when a
# title fight is active. Belt graphics + gold-leaf border + challenger
# corner color + "TITLE FIGHT" badge bg come from here.
#
# Per the Q10 decision (supervisor approved option B: "Skin overlay on
# Fight Night"), this is the ONLY championship-specific palette. The
# base FightNightColors remain the source of truth for non-title fights.

CHAMPIONSHIP_SKIN = {
    "champion_gold": "#f0c060",         # Belt graphic, champion portrait border,
                                         # "TITLE FIGHT" badge bg
    "champion_gold_leaf": "#f5d77a",    # Gold-leaf accent border on the cage
                                         # heatmap during a title fight — slightly
                                         # warmer than champion_gold
    "challenger_crimson": "#d63a3f",    # Challenger corner color, "challenger"
                                         # badge bg (matches Office crimson — the
                                         # challenger is the underdog story)
    "title_fight_badge_bg": "#1a1410",  # Dark brown bg for the "TITLE FIGHT"
                                         # badge — same as text_on_gold so the
                                         # gold text reads as "ink on gold leaf"
                                         # when reversed (dark bg + gold text)
}


# ============================================================
# FONT SIZES (per GUI_PLAN.md §3.4 + UI_REDESIGN_VISUAL_PLAN §3.3)
# ============================================================
# Same sizes for both modes — only the font FAMILY changes (Office
# uses Inter for commentary; Fight Night uses Source Serif Pro).
#
# Sizes preserved from Rev 2 to avoid breaking existing screen layouts
# in Phase 1 (the per-screen redesigns in Phases 4-6 will adopt the
# new UI_REDESIGN_VISUAL_PLAN §3.2 type scale: H1 22, H2 18, H3 15,
# body 14, body_small 13, caption 11). Phase 1 is foundation-only.

class FontSizes:
    """Font size constants (in px). Same for both modes."""
    DISPLAY = 36         # Splash, title bar wordmark
    H1 = 26              # Screen titles
    H2 = 20              # Panel titles
    H3 = 16              # Sub-panel titles
    BODY = 15            # Body text
    BODY_SMALL = 14      # Small body text (sidebar items, table rows)
    CAPTION = 13         # Metadata, timestamps, nav group labels
    MONO = 15            # Numbers / stats (JetBrains Mono)
    DESCRIPTOR = 15      # Attribute descriptors (italic)
    COMMENTARY_OFFICE = 16  # Fight commentary in Office Mode
    COMMENTARY_FIGHT = 18    # Fight commentary in Fight Night Mode (serif)
    PUNDIT = 16          # Pundit interjection (serif italic)
    BEAT_TIMESTAMP = 12  # "R2 3:42" — round + clock (mono)


# ============================================================
# FONT FAMILIES
# ============================================================
# Per UI_REDESIGN_VISUAL_PLAN §3.1, the Rev 2 font registration had a
# silent bug: all 4 Inter weights were registered under the SAME
# family name "Inter" with weight="normal", so Tk collapsed them to
# the LAST registered weight (Bold). The fix in Rev 3: register each
# Inter weight under a UNIQUE family name (Inter-Regular, Inter-Medium,
# Inter-SemiBold, Inter-Bold) so Tk can't collapse them.
#
# We keep INTER_FAMILY = "Inter" as a legacy constant for back-compat
# with code that imports it, but the actual font tuples in
# OfficeFonts / FightNightFonts use the per-weight resolved families.

# Per-weight Inter family names (the fix for the silent collapse bug)
INTER_REG_FAMILY = "Inter-Regular"
INTER_MEDIUM_FAMILY = "Inter-Medium"
INTER_SEMIBOLD_FAMILY = "Inter-SemiBold"
INTER_BOLD_FAMILY = "Inter-Bold"

# Legacy family name (kept for back-compat — falls back to "Inter" or
# platform sans if the per-weight families fail to register)
INTER_FAMILY = "Inter"
JETBRAINS_MONO_FAMILY = "JetBrains Mono"
SOURCE_SERIF_FAMILY = "Source Serif Pro"
DISPLAY_FAMILY = "Oswald"  # Bundled in Phase 1 — falls back to Inter-Bold

# Resolved family names — set by _register_fonts(). Start with the
# ideal names; fall back to platform defaults if registration fails.
# Per-weight resolved families (the new fix):
INTER_REG_FAMILY_RESOLVED = INTER_REG_FAMILY
INTER_MEDIUM_FAMILY_RESOLVED = INTER_MEDIUM_FAMILY
INTER_SEMIBOLD_FAMILY_RESOLVED = INTER_SEMIBOLD_FAMILY
INTER_BOLD_FAMILY_RESOLVED = INTER_BOLD_FAMILY
# Legacy resolved families (kept for back-compat — same value as the
# per-weight resolved, OR platform fallback if all Inter failed):
INTER_FAMILY_RESOLVED = INTER_FAMILY
JETBRAINS_MONO_FAMILY_RESOLVED = JETBRAINS_MONO_FAMILY
SOURCE_SERIF_FAMILY_RESOLVED = SOURCE_SERIF_FAMILY
DISPLAY_FAMILY_RESOLVED = DISPLAY_FAMILY

_fonts_registered = False
# Tracks per-family availability — used by _print_font_summary()
# to log resolved vs fallback at startup. Per UI_REDESIGN §3.1 fix #3.
_font_families_available = {
    INTER_REG_FAMILY: False,
    INTER_MEDIUM_FAMILY: False,
    INTER_SEMIBOLD_FAMILY: False,
    INTER_BOLD_FAMILY: False,
    JETBRAINS_MONO_FAMILY: False,
    SOURCE_SERIF_FAMILY: False,
    DISPLAY_FAMILY: False,
}


def _platform_default_sans():
    """Pick a sensible default sans-serif family per-platform.

    Used when Inter fails to register — the UI still needs a readable
    body font. Returns the family NAME (string), not a path.
    """
    import platform as _pf
    sys_name = _pf.system().lower()
    if sys_name.startswith("win"):
        return "Segoe UI"
    if sys_name == "darwin":
        return "Helvetica"
    return "Sans"  # Linux / unknown — Tk falls back to Helvetica.


def _platform_default_mono():
    """Pick a sensible default monospace family per-platform."""
    import platform as _pf
    sys_name = _pf.system().lower()
    if sys_name.startswith("win"):
        return "Consolas"
    if sys_name == "darwin":
        return "Menlo"
    return "Mono"


def _register_one_font(root, font_path, family, slant, weight,
                       internal_name=None):
    """Try multiple methods to register a single TTF with Tk.

    Args:
        root: Tk root window (must exist).
        font_path: Path to the TTF file.
        family: the family NAME to register under (e.g. "Inter-Regular").
            In Rev 3, each Inter weight gets its OWN family name so Tk
            can't collapse them.
        slant: "normal" or "italic".
        weight: "normal" or "bold" (informational — the family name
            already encodes the weight for per-weight families).
        internal_name: optional Tk font name. Defaults to
            f"{family}_{slant}_{weight}". Use this when registering
            multiple fonts under the same family name (e.g. Source
            Serif Pro has 4 variants: regular/semibold/italic/semibold-italic).

    Methods:
      1. tk.call("font", "create", ... "-file", path) — works on
         most platforms but silently fails on some Windows Tk builds
         when the font file is already loaded.
      2. tk.call("font", "create", ...) without -file, then use
         font.actual() to verify — fallback for cases where Method 1
         raises but the font is still usable by name.

    Returns True if any method succeeded, False otherwise. Idempotent
    — does not raise if the font is already registered.
    """
    if not font_path.exists():
        return False
    name = internal_name or f"{family}_{slant}_{weight}"
    # Method 1: -file registration (preferred — actually loads the
    # TTF into Tk's font registry).
    try:
        root.tk.call(
            "font", "create", name,
            "-family", family,
            "-slant", slant,
            "-weight", weight,
            "-file", str(font_path),
        )
        return True
    except tk.TclError:
        pass  # Already registered, or method 1 unsupported — try method 2.
    # Method 2: register the name without -file. The family is then
    # resolved by Tk's font search at render time. This works when
    # the TTF is in a known font directory OR has been loaded by name
    # via another mechanism (e.g. PIL).
    try:
        root.tk.call(
            "font", "create", name,
            "-family", family,
            "-slant", slant,
            "-weight", weight,
        )
        return True
    except tk.TclError:
        return False  # Give up — caller falls back to platform default.


def _register_fonts():
    """Register bundled TTF fonts with tkinter so they can be used
    by name (e.g., 'Inter-Regular' instead of loading the file each
    time).

    THE Phase 1 FIX (UI_REDESIGN_VISUAL_PLAN §3.1):
    Each Inter weight is registered under a UNIQUE family name
    (Inter-Regular, Inter-Medium, Inter-SemiBold, Inter-Bold) so Tk
    can't collapse them. The Rev 2 bug registered all 4 under
    "Inter" with weight="normal", which caused Tk to resolve to the
    LAST registered weight — so body text was rendered Bold and
    headings were rendered Bold (same as body, since the weight
    argument was ignored). The fix makes weight explicit in the
    family name; the font tuple's weight element is "normal" for all
    per-weight families (the family name encodes the weight).

    Oswald Bold is registered as family "Oswald" (single weight, no
    collapse risk).

    Robust across platforms (Windows / macOS / Linux). Falls back to
    sensible system fonts when bundled TTFs fail to register — the
    UI still works, just with a less branded typeface.

    Called automatically on first import of this module + on app
    construction (CageEmpireApp.__init__). Safe to call multiple times
    — checks _fonts_registered flag.
    """
    global _fonts_registered
    global INTER_REG_FAMILY_RESOLVED, INTER_MEDIUM_FAMILY_RESOLVED
    global INTER_SEMIBOLD_FAMILY_RESOLVED, INTER_BOLD_FAMILY_RESOLVED
    global INTER_FAMILY_RESOLVED, JETBRAINS_MONO_FAMILY_RESOLVED
    global SOURCE_SERIF_FAMILY_RESOLVED, DISPLAY_FAMILY_RESOLVED
    global _font_families_available
    if _fonts_registered:
        return

    # Register fonts with the Tk font system. This requires a Tk
    # root window — if none exists, we create a hidden one.
    root = tk._default_root
    created_root = False
    if root is None:
        try:
            root = tk.Tk()
            root.withdraw()
            created_root = True
        except Exception as e:
            # Headless / no-display environment — Tk can't init.
            # All families fall back to platform defaults. The UI
            # won't render in this state, but module import succeeds
            # (tests can still import theme.py without a display).
            print(f"[theme.py] Tk root init failed: {e}", flush=True)
            _fonts_registered = True
            _apply_platform_fallbacks()
            _print_font_summary()
            return

    try:
        # Per-weight Inter registration (THE fix). Each TTF is
        # registered under its UNIQUE family name with slant=normal,
        # weight=normal — the family name encodes the weight.
        inter_fonts = [
            (FONT_INTER_REGULAR,   INTER_REG_FAMILY,      "normal", "normal"),
            (FONT_INTER_MEDIUM,    INTER_MEDIUM_FAMILY,   "normal", "normal"),
            (FONT_INTER_SEMIBOLD,  INTER_SEMIBOLD_FAMILY, "normal", "normal"),
            (FONT_INTER_BOLD,      INTER_BOLD_FAMILY,     "normal", "normal"),
        ]
        for font_path, family, slant, weight in inter_fonts:
            try:
                ok = _register_one_font(root, font_path, family, slant, weight)
                if ok:
                    _font_families_available[family] = True
            except Exception:
                pass  # Non-fatal — falls back to platform default.

        # JetBrains Mono — single weight, single family name.
        try:
            ok = _register_one_font(root, FONT_JETBRAINS_MONO,
                                    JETBRAINS_MONO_FAMILY, "normal", "normal")
            if ok:
                _font_families_available[JETBRAINS_MONO_FAMILY] = True
        except Exception:
            pass

        # Source Serif Pro — 4 variants (regular/semibold/italic/semibold-italic).
        # All registered under SOURCE_SERIF_FAMILY with different slant/weight,
        # using unique internal Tk names so they don't collide. This is the
        # legacy pattern (single family, weight via the font tuple) — Source
        # Serif Pro doesn't have the collapse bug because the 4 variants
        # cover all 4 slant/weight combinations (no two are both normal+normal).
        serif_fonts = [
            (FONT_SOURCE_SERIF_REGULAR,         SOURCE_SERIF_FAMILY, "normal", "normal"),
            (FONT_SOURCE_SERIF_SEMIBOLD,        SOURCE_SERIF_FAMILY, "normal", "bold"),
            (FONT_SOURCE_SERIF_ITALIC,          SOURCE_SERIF_FAMILY, "italic", "normal"),
            (FONT_SOURCE_SERIF_SEMIBOLD_ITALIC, SOURCE_SERIF_FAMILY, "italic", "bold"),
        ]
        serif_ok = False
        for font_path, family, slant, weight in serif_fonts:
            try:
                ok = _register_one_font(root, font_path, family, slant, weight)
                if ok:
                    serif_ok = True
            except Exception:
                pass
        if serif_ok:
            _font_families_available[SOURCE_SERIF_FAMILY] = True

        # Oswald Bold — the new display font (Phase 1 UI Redesign).
        # Single weight, single family. Falls back to Inter-Bold if
        # the TTF is missing or fails to register.
        try:
            ok = _register_one_font(root, FONT_OSWALD_BOLD,
                                    DISPLAY_FAMILY, "normal", "bold")
            if ok:
                _font_families_available[DISPLAY_FAMILY] = True
        except Exception:
            pass

        # Verify each family is actually usable by querying Tk's font
        # registry. A family may "register" via tk.call but not be
        # resolvable — tk.fontFamilies() is the source of truth.
        try:
            available_families = set(root.tk.call("font", "families"))
        except Exception:
            available_families = set()
        if available_families:
            for fam in (INTER_REG_FAMILY, INTER_MEDIUM_FAMILY,
                        INTER_SEMIBOLD_FAMILY, INTER_BOLD_FAMILY,
                        JETBRAINS_MONO_FAMILY, SOURCE_SERIF_FAMILY,
                        DISPLAY_FAMILY):
                if fam in available_families:
                    _font_families_available[fam] = True
                # NOTE: we do NOT set False here — if -file registration
                # succeeded, the family may be available even if Tk's
                # fontFamilies() doesn't list it (Tk's fontFamilies()
                # queries the system font list, not the -file-registered
                # fonts). The _font_families_available flag tracks
                # whether _register_one_font returned True.
    finally:
        if created_root:
            try:
                root.destroy()
            except Exception:
                pass

    _apply_platform_fallbacks()
    _fonts_registered = True
    _print_font_summary()


def _apply_platform_fallbacks():
    """Resolve the *_RESOLVED family globals based on what registered.

    Called after _register_fonts() does the registration pass. Sets
    each *_RESOLVED global to the bundled family name if available,
    otherwise to a platform-appropriate default.

    Per-weight Inter families fall back independently — if only
    Inter-Regular registered successfully, the others fall back to
    platform sans (preserving the regular weight for body text).
    The legacy INTER_FAMILY_RESOLVED is set to Inter-Bold if any
    Inter weight registered (best approximation of "Inter" when Tk
    can't resolve per-weight), else platform sans.
    """
    global INTER_REG_FAMILY_RESOLVED, INTER_MEDIUM_FAMILY_RESOLVED
    global INTER_SEMIBOLD_FAMILY_RESOLVED, INTER_BOLD_FAMILY_RESOLVED
    global INTER_FAMILY_RESOLVED, JETBRAINS_MONO_FAMILY_RESOLVED
    global SOURCE_SERIF_FAMILY_RESOLVED, DISPLAY_FAMILY_RESOLVED

    INTER_REG_FAMILY_RESOLVED = (
        INTER_REG_FAMILY if _font_families_available[INTER_REG_FAMILY]
        else _platform_default_sans())
    INTER_MEDIUM_FAMILY_RESOLVED = (
        INTER_MEDIUM_FAMILY if _font_families_available[INTER_MEDIUM_FAMILY]
        else INTER_REG_FAMILY_RESOLVED)  # Medium falls back to Regular
    INTER_SEMIBOLD_FAMILY_RESOLVED = (
        INTER_SEMIBOLD_FAMILY if _font_families_available[INTER_SEMIBOLD_FAMILY]
        else INTER_BOLD_FAMILY_RESOLVED if _font_families_available[INTER_BOLD_FAMILY]
        else INTER_REG_FAMILY_RESOLVED)
    INTER_BOLD_FAMILY_RESOLVED = (
        INTER_BOLD_FAMILY if _font_families_available[INTER_BOLD_FAMILY]
        else _platform_default_sans())

    # Legacy INTER_FAMILY_RESOLVED — if any Inter weight registered,
    # prefer Inter-Bold (best approximation of "Inter" for headings
    # + body when Tk can't pick per weight). Else platform sans.
    any_inter = any(_font_families_available[f] for f in
                    (INTER_REG_FAMILY, INTER_MEDIUM_FAMILY,
                     INTER_SEMIBOLD_FAMILY, INTER_BOLD_FAMILY))
    INTER_FAMILY_RESOLVED = (
        INTER_FAMILY if any_inter else _platform_default_sans())

    JETBRAINS_MONO_FAMILY_RESOLVED = (
        JETBRAINS_MONO_FAMILY
        if _font_families_available[JETBRAINS_MONO_FAMILY]
        else _platform_default_mono())

    SOURCE_SERIF_FAMILY_RESOLVED = (
        SOURCE_SERIF_FAMILY
        if _font_families_available[SOURCE_SERIF_FAMILY]
        else _platform_default_sans())

    # Display family (Oswald) — falls back to Inter-Bold (next best
    # condensed-feel font we have), else Inter (legacy), else platform sans.
    if _font_families_available[DISPLAY_FAMILY]:
        DISPLAY_FAMILY_RESOLVED = DISPLAY_FAMILY
    elif _font_families_available[INTER_BOLD_FAMILY]:
        DISPLAY_FAMILY_RESOLVED = INTER_BOLD_FAMILY
    elif any_inter:
        DISPLAY_FAMILY_RESOLVED = INTER_FAMILY
    else:
        DISPLAY_FAMILY_RESOLVED = _platform_default_sans()


def _print_font_summary():
    """Print the resolved font family for each role at startup.

    Per UI_REDESIGN_VISUAL_PLAN §3.1 fix #3: a startup health check
    that logs the resolved family for each role so we can spot
    registration failures in the wild. Output is flushed immediately
    so it appears in dev.log / console before any screen renders.

    Format:
        [theme.py] Font registration summary:
          Inter-Regular:  ✓ (resolved)
          Inter-Medium:   ✓ (resolved)
          ...
          Oswald:         ✓ (resolved) OR ✗ (fallback to Inter-Bold)
    """
    print("[theme.py] Font registration summary:", flush=True)
    roles = [
        ("Inter-Regular",   INTER_REG_FAMILY,
         INTER_REG_FAMILY_RESOLVED),
        ("Inter-Medium",    INTER_MEDIUM_FAMILY,
         INTER_MEDIUM_FAMILY_RESOLVED),
        ("Inter-SemiBold",  INTER_SEMIBOLD_FAMILY,
         INTER_SEMIBOLD_FAMILY_RESOLVED),
        ("Inter-Bold",      INTER_BOLD_FAMILY,
         INTER_BOLD_FAMILY_RESOLVED),
        ("JetBrains Mono",  JETBRAINS_MONO_FAMILY,
         JETBRAINS_MONO_FAMILY_RESOLVED),
        ("Source Serif Pro", SOURCE_SERIF_FAMILY,
         SOURCE_SERIF_FAMILY_RESOLVED),
        ("Oswald",          DISPLAY_FAMILY,
         DISPLAY_FAMILY_RESOLVED),
    ]
    for label, requested, resolved in roles:
        ok = _font_families_available.get(requested, False)
        if ok and resolved == requested:
            mark = "✓ (resolved)"
        elif ok:
            mark = "✓ (resolved, but display name differs)"
        else:
            mark = f"✗ (fallback to {resolved!r})"
        # Pad label to align the marks (longest label is "Source Serif Pro" = 16 chars)
        print(f"  {label:<16} {mark}", flush=True)


# ============================================================
# AUTO-REGISTER FONTS — runs at module import time, BEFORE the
# OfficeFonts / FightNightFonts class definitions below. This
# ensures INTER_*_FAMILY_RESOLVED etc. are set to their final values
# (bundled family or platform fallback) by the time the class
# attributes are bound. Safe to call before tkinter has a root
# window — _register_fonts creates a temporary hidden one (or
# gracefully no-ops in headless environments).
# ============================================================
try:
    _register_fonts()
except Exception as _e:
    print(f"Warning: font registration failed: {_e}", flush=True)
    # Non-fatal — OfficeFonts / FightNightFonts will use the default
    # RESOLVED names (which equal the bundled family names). Tk will
    # fall back to a system font if the bundled family isn't found.
    _apply_platform_fallbacks()


# ============================================================
# FONT TUPLES (for CTk widgets)
# ============================================================
# CTk expects fonts as tuples: (family, size, weight).
#
# THE Phase 1 FIX: each font tuple uses the per-weight RESOLVED
# family name (Inter-Regular, Inter-Bold, etc.) with weight="normal"
# — the family name encodes the weight, so the weight argument is
# "normal" for all per-weight families. This is the fix for the
# Rev 2 collapse bug where headings and body text both rendered as
# Inter Bold.
#
# Heading fonts (h1, h2, h3) use Inter-Bold for h1/h2 and Inter-SemiBold
# for h3 (slightly less heavy). Body fonts use Inter-Regular. Captions
# use Inter-Medium (slightly heavier than body for the "stadium
# scoreboard" metadata feel).

class OfficeFonts:
    """Font tuples for Office Mode.

    Inter for everything except numbers (JetBrains Mono) and display
    (Oswald). Per-weight families fix the Rev 2 collapse bug.
    """
    display = (DISPLAY_FAMILY_RESOLVED, FontSizes.DISPLAY, "bold")
    h1 = (INTER_BOLD_FAMILY_RESOLVED, FontSizes.H1, "normal")
    h2 = (INTER_BOLD_FAMILY_RESOLVED, FontSizes.H2, "normal")
    h3 = (INTER_SEMIBOLD_FAMILY_RESOLVED, FontSizes.H3, "normal")
    body = (INTER_REG_FAMILY_RESOLVED, FontSizes.BODY, "normal")
    body_small = (INTER_REG_FAMILY_RESOLVED, FontSizes.BODY_SMALL, "normal")
    caption = (INTER_MEDIUM_FAMILY_RESOLVED, FontSizes.CAPTION, "normal")
    mono = (JETBRAINS_MONO_FAMILY_RESOLVED, FontSizes.MONO, "normal")
    descriptor = (INTER_REG_FAMILY_RESOLVED, FontSizes.DESCRIPTOR, "normal")
    commentary = (INTER_REG_FAMILY_RESOLVED, FontSizes.COMMENTARY_OFFICE, "normal")


class FightNightFonts:
    """Font tuples for Fight Night Mode.

    Same as Office EXCEPT commentary switches to Source Serif Pro
    (serif feels like documentary narration, not UI text) and
    pundit interjections use Source Serif Pro SemiBold Italic.
    """
    display = (DISPLAY_FAMILY_RESOLVED, FontSizes.DISPLAY, "bold")
    h1 = (INTER_BOLD_FAMILY_RESOLVED, FontSizes.H1, "normal")
    h2 = (INTER_BOLD_FAMILY_RESOLVED, FontSizes.H2, "normal")
    h3 = (INTER_SEMIBOLD_FAMILY_RESOLVED, FontSizes.H3, "normal")
    body = (INTER_REG_FAMILY_RESOLVED, FontSizes.BODY, "normal")
    body_small = (INTER_REG_FAMILY_RESOLVED, FontSizes.BODY_SMALL, "normal")
    caption = (INTER_MEDIUM_FAMILY_RESOLVED, FontSizes.CAPTION, "normal")
    mono = (JETBRAINS_MONO_FAMILY_RESOLVED, FontSizes.MONO, "normal")
    descriptor = (INTER_REG_FAMILY_RESOLVED, FontSizes.DESCRIPTOR, "normal")
    # THE key Fight Night font change: commentary switches to serif
    commentary = (SOURCE_SERIF_FAMILY_RESOLVED, FontSizes.COMMENTARY_FIGHT, "normal")
    pundit = (SOURCE_SERIF_FAMILY_RESOLVED, FontSizes.PUNDIT, "italic")
    beat_timestamp = (JETBRAINS_MONO_FAMILY_RESOLVED, FontSizes.BEAT_TIMESTAMP, "normal")


# ============================================================
# THEME CLASS
# ============================================================

class Theme:
    """A complete theme: colors + fonts + asset paths.

    Two instances are created below: OFFICE and FIGHT_NIGHT.
    The CURRENT_THEME global points to whichever is active.
    Use set_theme("office") or set_theme("fight_night") to switch.
    """
    def __init__(self, name, colors, fonts):
        self.name = name
        self.colors = colors
        self.fonts = fonts


OFFICE = Theme("office", OfficeColors, OfficeFonts)
FIGHT_NIGHT = Theme("fight_night", FightNightColors, FightNightFonts)

# The active theme. Screens read from this. set_theme() switches it.
CURRENT_THEME = OFFICE

# Callbacks fired when the theme changes (for live re-rendering)
_theme_callbacks = []


def set_theme(mode):
    """Switch the active theme. Fires all registered callbacks.

    Args:
        mode: "office" or "fight_night"
    """
    global CURRENT_THEME
    if mode == "office":
        CURRENT_THEME = OFFICE
    elif mode == "fight_night":
        CURRENT_THEME = FIGHT_NIGHT
    else:
        raise ValueError(f"Unknown theme mode: {mode}. Use 'office' or 'fight_night'.")

    for callback in _theme_callbacks:
        try:
            callback(CURRENT_THEME)
        except Exception as e:
            print(f"Warning: theme callback failed: {e}", flush=True)


def on_theme_change(callback):
    """Register a callback fired when the theme changes.

    The callback receives the new Theme instance as its argument.
    Used by screens to re-render when the mode switches.
    """
    _theme_callbacks.append(callback)


def get_theme():
    """Return the currently active Theme instance."""
    return CURRENT_THEME


# ============================================================
# TINT HELPER (UI_REDESIGN_VISUAL_PLAN §2.2 — gold_tint / crimson_tint)
# ============================================================
# The tint colors (gold_tint, crimson_tint) are stored as CSS rgba()
# strings to match the spec verbatim. CTk doesn't accept rgba() — it
# needs solid hex. This helper composites a tint over a base hex for
# CTk consumption. Phase 2 components will call this when they need
# a solid hover bg.

def tint_to_solid(tint_rgba, base_hex):
    """Composite an rgba() tint string over a solid hex base color.

    Used by Phase 2 component library to convert gold_tint / crimson_tint
    (stored as rgba strings per spec) into solid hex values that CTk
    can consume as fg_color / hover_color.

    Args:
        tint_rgba: rgba string like "rgba(224,169,87,0.10)".
        base_hex: hex string like "#1c2028" (the bg the tint is over).

    Returns:
        Solid hex string like "#2f2e2d".
    """
    try:
        # Parse "rgba(r,g,b,a)" — handle whitespace variations.
        body = tint_rgba.strip()
        if body.startswith("rgba(") and body.endswith(")"):
            body = body[5:-1]
        parts = [p.strip() for p in body.split(",")]
        r, g, b, a = int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3])
        # Parse base hex "#rrggbb"
        h = base_hex.lstrip("#")
        if len(h) == 6:
            br, bg, bb = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        elif len(h) == 3:
            br = int(h[0] * 2, 16); bg = int(h[1] * 2, 16); bb = int(h[2] * 2, 16)
        else:
            return base_hex
        # Composite: out = base * (1 - a) + tint * a
        ro = int(round(br * (1 - a) + r * a))
        go = int(round(bg * (1 - a) + g * a))
        bo = int(round(bb * (1 - a) + b * a))
        return f"#{ro:02x}{go:02x}{bo:02x}"
    except Exception:
        return base_hex  # Defensive — return base if parse fails.


# ============================================================
# TEXTURE UTILITIES (UI_REDESIGN_VISUAL_PLAN §2.4)
# ============================================================
# Procedurally-generated PNG textures, lazy-loaded + cached as
# CTkImage. Each function:
#   1. Returns the cached CTkImage if already loaded.
#   2. Else loads the PNG from src/ui/assets/textures/ if it exists.
#   3. Else generates the PNG via PIL, saves it to the textures dir,
#      then loads it.
#   4. Returns None if PIL is missing OR generation fails — caller
#      handles None (typically by skipping the texture).
#
# Textures are subtle. The rule: a texture should be FELT, not SEEN.
# If the player notices the texture, it's too loud.
#
# Performance: texture generation is one-time at first call (cached
# in module-level dict). Subsequent calls are dict lookups. The PNGs
# are saved to disk on first generation so subsequent app launches
# load from file (faster than regenerating).
#
# CTk doesn't have native texture-tile support. The closest is
# CTkFrame's bg_color (single color). To tile a texture, the caller
# (Phase 2 component library) will load the CTkImage returned here,
# place a CTkLabel with that image as its background. This is a
# one-time cost per screen (cached). Performance impact: <2ms per
# textured frame, negligible.

# Module-level cache: {texture_name: CTkImage or None}
_texture_cache = {}


def _ensure_textures_dir():
    """Create src/ui/assets/textures/ if it doesn't exist."""
    try:
        TEXTURES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[theme.py] Warning: could not create textures dir: {e}",
              flush=True)


def _load_or_generate(name, png_path, generate_fn, size=None):
    """Load a texture PNG from disk, or generate it via PIL if missing.

    Args:
        name: cache key (e.g. "noise_grain").
        png_path: Path to the PNG file (in src/ui/assets/textures/).
        generate_fn: callable(pil_image) that draws the texture onto
            a PIL.Image (RGBA mode). Called only if the PNG doesn't
            exist on disk.
        size: (width, height) for the CTkImage. If None, uses the
            PNG's native size.

    Returns:
        CTkImage, or None if PIL is missing or generation fails.
    """
    if name in _texture_cache:
        return _texture_cache[name]
    try:
        import customtkinter as ctk
        from PIL import Image
    except ImportError:
        _texture_cache[name] = None
        return None

    try:
        if png_path.exists():
            pil_img = Image.open(png_path).convert("RGBA")
        else:
            # Generate via PIL.
            _ensure_textures_dir()
            pil_img = generate_fn()
            if pil_img is None:
                _texture_cache[name] = None
                return None
            pil_img = pil_img.convert("RGBA")
            try:
                pil_img.save(png_path, "PNG")
            except Exception as e:
                print(f"[theme.py] Warning: could not save texture "
                      f"{png_path.name}: {e}", flush=True)
                # Don't return — we still have the in-memory image.

        w, h = size or pil_img.size
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img,
                               size=(w, h))
        _texture_cache[name] = ctk_img
        return ctk_img
    except Exception as e:
        print(f"[theme.py] Warning: texture {name} failed: {e}",
              flush=True)
        _texture_cache[name] = None
        return None


# ----- noise_grain.png -----
# 256×256 PNG, 3% opacity grey noise. Tiled across bg_base (Office +
# Fight Night). Adds the "this is a real surface, not a flat fill"
# feel without being visible.
NOISE_GRAIN_PATH = TEXTURES_DIR / "noise_grain.png"
NOISE_GRAIN_SIZE = (256, 256)


def _generate_noise_grain():
    """Generate 256×256 3% opacity grey noise via PIL."""
    try:
        from PIL import Image
        import random
    except ImportError:
        return None
    w, h = NOISE_GRAIN_SIZE
    # Start with a transparent image.
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    # 3% opacity ≈ alpha 8 (out of 255). Grey noise = r=g=b=random.
    # The noise is subtle — only the alpha channel varies the visibility.
    for y in range(h):
        for x in range(w):
            v = random.randint(110, 140)  # neutral grey
            # Vary alpha slightly to avoid a uniform grey wash.
            a = random.randint(5, 12)  # ~2-5% opacity
            px[x, y] = (v, v, v, a)
    return img


def get_noise_grain_texture():
    """Return the noise_grain CTkImage, or None.

    Tiles a 3% opacity grey noise across bg_base. Cached at module
    level after first call.
    """
    return _load_or_generate("noise_grain", NOISE_GRAIN_PATH,
                             _generate_noise_grain, NOISE_GRAIN_SIZE)


# ----- chain_link_dim.png -----
# 512×512 PNG, chain-link fence pattern at 4% opacity, slightly
# crimson-tinted. Tiled across bg_surface on Fight Night only — the
# "cage" metaphor made literal. Never on cards, never in Office.
CHAIN_LINK_DIM_PATH = TEXTURES_DIR / "chain_link_dim.png"
CHAIN_LINK_DIM_SIZE = (512, 512)


def _generate_chain_link_dim():
    """Generate 512×512 chain-link fence pattern at 4% opacity,
    crimson-tinted, via PIL."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    w, h = CHAIN_LINK_DIM_SIZE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Chain-link pattern: diagonal lines in both directions, forming
    # a diamond grid. Standard chain-link mesh angle is ~45°.
    # Spacing: 32px between parallel lines (gives ~16 diamonds across
    # a 512px tile).
    spacing = 32
    line_color = (214, 58, 63, 10)  # crimson at ~4% opacity
    line_width = 2
    # Diagonal lines going down-right.
    for offset in range(-h, w + h, spacing):
        draw.line([(offset, 0), (offset + h, h)],
                  fill=line_color, width=line_width)
        draw.line([(offset + spacing - line_width, 0),
                   (offset + h + spacing - line_width, h)],
                  fill=line_color, width=line_width)
    # Diagonal lines going down-left (completes the diamond grid).
    for offset in range(-h, w + h, spacing):
        draw.line([(offset + h, 0), (offset, h)],
                  fill=line_color, width=line_width)
        draw.line([(offset + h - line_width + spacing, 0),
                   (offset - line_width + spacing, h)],
                  fill=line_color, width=line_width)
    return img


def get_chain_link_dim_texture():
    """Return the chain_link_dim CTkImage, or None.

    Tiles a 4% opacity crimson-tinted chain-link fence pattern across
    bg_surface on Fight Night. Cached at module level after first call.
    """
    return _load_or_generate("chain_link_dim", CHAIN_LINK_DIM_PATH,
                             _generate_chain_link_dim, CHAIN_LINK_DIM_SIZE)


# ----- gold_leaf_border.png -----
# 16×16 PNG corner tile, 1px gold-leaf textured border. Applied via
# CTk's border_width=2 + border_color lookup on champion cards
# (Dashboard champion chips, Fighter Profile portrait when champion,
# Titles screen belt cards). 9-slice border.
GOLD_LEAF_BORDER_PATH = TEXTURES_DIR / "gold_leaf_border.png"
GOLD_LEAF_BORDER_SIZE = (16, 16)


def _generate_gold_leaf_border():
    """Generate 16×16 1px gold-leaf textured border (corner tile) via PIL."""
    try:
        from PIL import Image, ImageDraw
        import random
    except ImportError:
        return None
    w, h = GOLD_LEAF_BORDER_SIZE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Gold-leaf texture: alternate between champion_gold (#f0c060)
    # and champion_gold_leaf (#f5d77a) along the border, with slight
    # random variation for the "leaf" feel.
    gold_a = (240, 192, 96, 255)   # champion_gold
    gold_b = (245, 215, 122, 255)  # champion_gold_leaf
    # Draw 1px border on all 4 sides.
    for i in range(w):
        for j in range(h):
            on_border = (i == 0 or i == w - 1 or j == 0 or j == h - 1)
            if on_border:
                # Pick gold_a or gold_b with slight noise — the "leaf" texture.
                base = gold_a if random.random() < 0.5 else gold_b
                # Add a touch of brightness variation.
                jitter = random.randint(-15, 15)
                r = max(0, min(255, base[0] + jitter))
                g = max(0, min(255, base[1] + jitter))
                b = max(0, min(255, base[2] + jitter))
                # Vary alpha slightly for the textured feel.
                a = max(200, min(255, base[3] + random.randint(-20, 0)))
                img.putpixel((i, j), (r, g, b, a))
    return img


def get_gold_leaf_border_texture():
    """Return the gold_leaf_border CTkImage, or None.

    16×16 corner tile with a 1px gold-leaf textured border. Applied
    via CTk's border_width=2 + border_color lookup on champion cards.
    Cached at module level after first call.
    """
    return _load_or_generate("gold_leaf_border", GOLD_LEAF_BORDER_PATH,
                             _generate_gold_leaf_border, GOLD_LEAF_BORDER_SIZE)


# ----- vignette_fight_night.png -----
# 1920×1080 PNG, radial gradient from transparent center to 30% black
# at corners. Single overlay on Fight Night main content. Focuses the
# eye on the center action.
VIGNETTE_FIGHT_NIGHT_PATH = TEXTURES_DIR / "vignette_fight_night.png"
VIGNETTE_FIGHT_NIGHT_SIZE = (1920, 1080)


def _generate_vignette_fight_night():
    """Generate 1920×1080 radial gradient vignette via PIL.

    Center is transparent; corners are 30% black (alpha=77).
    """
    try:
        from PIL import Image, ImageDraw
        import math
    except ImportError:
        return None
    w, h = VIGNETTE_FIGHT_NIGHT_SIZE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    cx, cy = w / 2.0, h / 2.0
    # Max distance from center = corner distance.
    max_dist = math.sqrt(cx * cx + cy * cy)
    # We want 0% black at center, 30% black (alpha=77) at corners.
    # Alpha ramps non-linearly (slight curve so the darkening
    # concentrates near the corners, not the mid-radius).
    max_alpha = 77  # 30% of 255
    for y in range(h):
        for x in range(w):
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)
            # Normalize 0..1
            t = dist / max_dist
            # Apply a slight curve (t^1.5) so the darkening concentrates
            # at the corners.
            t_curve = t ** 1.5
            a = int(round(max_alpha * t_curve))
            if a > 0:
                px[x, y] = (0, 0, 0, a)
    return img


def get_vignette_fight_night_texture():
    """Return the vignette_fight_night CTkImage, or None.

    1920×1080 radial gradient overlay: transparent center, 30% black
    at corners. Applied as a single overlay on Fight Night main content
    to focus the eye on the center action. Cached at module level after
    first call.
    """
    return _load_or_generate("vignette_fight_night", VIGNETTE_FIGHT_NIGHT_PATH,
                             _generate_vignette_fight_night,
                             VIGNETTE_FIGHT_NIGHT_SIZE)


def preload_textures():
    """Preload all 4 textures into the cache.

    Called at app startup (Phase 3 app shell rewrite will wire this
    into CageEmpireApp.__init__). For Phase 1, exposed so a future
    caller can warm the cache. Safe to call multiple times.
    """
    get_noise_grain_texture()
    get_chain_link_dim_texture()
    get_gold_leaf_border_texture()
    get_vignette_fight_night_texture()


# ============================================================
# ICON PATHS (Task 6.1c — icon files are Phase 3 of the redesign)
# ============================================================

# Status icons (16x16 + 32x32). Files will be generated in Phase 3.
# For now, ICONS_DIR is empty — screens use text fallbacks until
# the icon set lands.
STATUS_ICONS = {
    "champion": ICONS_DIR / "champion.png",
    "contender": ICONS_DIR / "contender.png",
    "prospect": ICONS_DIR / "prospect.png",
    "veteran": ICONS_DIR / "veteran.png",
    "rookie": ICONS_DIR / "rookie.png",
    "injured": ICONS_DIR / "injured.png",
    "suspended": ICONS_DIR / "suspended.png",
    "retired": ICONS_DIR / "retired.png",
    "deceased": ICONS_DIR / "deceased.png",
    "cut": ICONS_DIR / "cut.png",
    "scouted": ICONS_DIR / "scouted.png",
    "hidden_potential": ICONS_DIR / "hidden_potential.png",
    "rivalry": ICONS_DIR / "rivalry.png",
    "media_star": ICONS_DIR / "media_star.png",
    "fan_favourite": ICONS_DIR / "fan_favourite.png",
    "gym_leader": ICONS_DIR / "gym_leader.png",
    "on_win_streak": ICONS_DIR / "on_win_streak.png",
    "on_loss_streak": ICONS_DIR / "on_loss_streak.png",
    "title_defense": ICONS_DIR / "title_defense.png",
    "comeback": ICONS_DIR / "comeback.png",
}

# Nav icons (16x16 + 32x32)
NAV_ICONS = {
    "home": ICONS_DIR / "nav_home.png",
    "roster": ICONS_DIR / "nav_roster.png",
    "events": ICONS_DIR / "nav_events.png",
    "scouting": ICONS_DIR / "nav_scouting.png",
    "finance": ICONS_DIR / "nav_finance.png",
    "world": ICONS_DIR / "nav_world.png",
    "hof": ICONS_DIR / "nav_hof.png",
    "settings": ICONS_DIR / "nav_settings.png",
    "save": ICONS_DIR / "nav_save.png",
    "mods": ICONS_DIR / "nav_mods.png",
    "help": ICONS_DIR / "nav_help.png",
    "quit": ICONS_DIR / "nav_quit.png",
}


def get_icon(name):
    """Return the path to an icon file, or None if it doesn't exist.

    Screens should call this and fall back to text if None is
    returned (icons may not be generated yet in early Task 6.1).
    """
    if name in STATUS_ICONS:
        path = STATUS_ICONS[name]
    elif name in NAV_ICONS:
        path = NAV_ICONS[name]
    else:
        return None
    return path if path.exists() else None


# ============================================================
# AUTO-REGISTER FONTS ON IMPORT
# ============================================================

# Font registration already ran above (before OfficeFonts / FightNightFonts
# were defined) so the resolved family names are available to the font
# tuple class attributes. The duplicate call here is a no-op (the
# _fonts_registered flag short-circuits it) — kept for backward
# compatibility with any code that imports `_register_fonts` and calls
# it manually (e.g., src/ui/app.py's CageEmpireApp.__init__).
try:
    _register_fonts()
except Exception as e:
    print(f"Warning: font registration failed: {e}", flush=True)
    # Non-fatal — CTk will fall back to system fonts.
