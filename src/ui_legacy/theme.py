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
import json

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

# Custom CTk theme JSON path (UI-REDESIGN-DASH-V2 Fix #1).
# Replaces CTk's built-in dark-blue theme with our OfficeColors
# palette so EVERY widget (buttons, entries, frames, scrollbars)
# uses our branded colors by default — not just the ones that
# explicitly pass fg_color=.
CTK_THEME_JSON_PATH = ASSETS_DIR / "cage_empire_theme.json"


# ============================================================
# FIX #1 (UI-REDESIGN-DASH-V2): CUSTOM CTk THEME
# ============================================================
# CTk's set_default_color_theme("dark-blue") overrides our custom
# palette for any widget that doesn't explicitly pass fg_color=. By
# writing our own theme JSON matching OfficeColors + loading it via
# set_default_color_theme(path), every widget defaults to branded
# colors: gold buttons, bg_card frames, gold progress bars, etc.

_CTk_THEME_DATA = {
    "CTk": {
        "fg_color": "#0a0c10",
    },
    "CTkToplevel": {
        "fg_color": "#1c2028",
    },
    "CTkFrame": {
        "corner_radius": 6,
        "border_width": 1,
        "fg_color": "#1c2028",
        "top_fg_color": "#262a30",  # warmer bg_card_elevated (Fix #6)
        "border_color": "#2a2f38",
    },
    "CTkButton": {
        "corner_radius": 10,  # Fix #6: rounded buttons
        "border_width": 0,
        "fg_color": "#e0a957",         # gold
        "hover_color": "#f5c878",      # gold_bright
        "border_color": "#2a2f38",
        "text_color": "#1a1410",       # text_on_gold
        "text_color_disabled": "#6b7280",
    },
    "CTkLabel": {
        "corner_radius": 0,
        "border_width": 0,
        "fg_color": "transparent",
        "border_color": "#2a2f38",
        "text_color": "#e8eaed",
    },
    "CTkEntry": {
        "corner_radius": 6,
        "border_width": 1,
        "fg_color": "#252a33",
        "border_color": "#2a2f38",
        "text_color": "#e8eaed",
        "placeholder_text_color": "#6b7280",
    },
    "CTkCheckBox": {
        "corner_radius": 4,
        "border_width": 2,
        "fg_color": "#e0a957",
        "border_color": "#3a4049",
        "hover_color": "#f5c878",
        "checkmark_color": "#1a1410",
        "text_color": "#e8eaed",
        "text_color_disabled": "#6b7280",
    },
    "CTkSwitch": {
        "corner_radius": 1000,
        "border_width": 2,
        "button_length": 0,
        "fg_color": "#2a2f38",
        "progress_color": "#e0a957",
        "button_color": "#e8eaed",
        "button_hover_color": "#f5c878",
        "text_color": "#e8eaed",
        "text_color_disabled": "#6b7280",
    },
    "CTkRadioButton": {
        "corner_radius": 1000,
        "border_width_checked": 2,
        "border_width_unchecked": 2,
        "fg_color": "#e0a957",
        "border_color": "#3a4049",
        "hover_color": "#f5c878",
        "text_color": "#e8eaed",
        "text_color_disabled": "#6b7280",
    },
    "CTkProgressBar": {
        "corner_radius": 4,
        "border_width": 0,
        "fg_color": "#2a2f38",
        "progress_color": "#e0a957",
        "border_color": "#2a2f38",
    },
    "CTkSlider": {
        "corner_radius": 1000,
        "button_corner_radius": 1000,
        "border_width": 6,
        "button_length": 0,
        "fg_color": "#2a2f38",
        "progress_color": "#e0a957",
        "button_color": "#e0a957",
        "button_hover_color": "#f5c878",
    },
    "CTkOptionMenu": {
        "corner_radius": 6,
        "fg_color": "#252a33",
        "button_color": "#2a2f38",
        "button_hover_color": "#3a4049",
        "text_color": "#e8eaed",
        "text_color_disabled": "#6b7280",
    },
    "CTkComboBox": {
        "corner_radius": 6,
        "border_width": 1,
        "fg_color": "#252a33",
        "border_color": "#2a2f38",
        "button_color": "#2a2f38",
        "button_hover_color": "#3a4049",
        "text_color": "#e8eaed",
        "text_color_disabled": "#6b7280",
    },
    "CTkScrollbar": {
        "corner_radius": 1000,
        "border_spacing": 4,
        "fg_color": "transparent",
        "button_color": "#3a4049",
        "button_hover_color": "#4a5059",
    },
    "CTkSegmentedButton": {
        "corner_radius": 6,
        "border_width": 1,
        "fg_color": "#252a33",
        "selected_color": "#e0a957",
        "selected_hover_color": "#f5c878",
        "unselected_color": "#252a33",
        "unselected_hover_color": "#2a2f38",
        "text_color": "#1a1410",
        "text_color_disabled": "#6b7280",
    },
    "CTkTextbox": {
        "corner_radius": 6,
        "border_width": 1,
        "fg_color": "#252a33",
        "border_color": "#2a2f38",
        "text_color": "#e8eaed",
        "scrollbar_button_color": "#3a4049",
        "scrollbar_button_hover_color": "#4a5059",
    },
    "CTkScrollableFrame": {
        "label_fg_color": "#252a33",
    },
    "DropdownMenu": {
        "fg_color": "#252a33",
        "hover_color": "#2a2f38",
        "text_color": "#e8eaed",
    },
    "CTkFont": {
        "family": "Inter",
        "size": 13,
        "weight": "normal",
    },
}


def install_ctk_theme():
    """Install our custom CTk theme — NUCLEAR approach.

    Replaces CTk's built-in "dark-blue" theme with our OfficeColors
    palette. Every CTk widget (CTkButton, CTkFrame, CTkEntry, etc.)
    that doesn't explicitly pass fg_color= will use our branded colors.

    APPROACH (Task THEME-FONT-FIX-V4 — the NUCLEAR fix):
    The prior approach relied on ctk.set_default_color_theme(path) which
    loads a JSON file. This SILENTLY FAILS on some platforms (Python 3.14
    on Windows, certain CTk versions, path issues with backslashes). The
    user has reported "still default dark blue" across 5+ iterations.

    The NUCLEAR approach: after trying set_default_color_theme(path),
    DIRECTLY MODIFY the ThemeManager.theme dict in memory. This bypasses
    all file/JSON/path issues — it's a pure Python dict assignment that
    CANNOT fail silently. Even if set_default_color_theme doesn't work,
    the direct dict modification WILL apply our colors.

    This is belt + suspenders:
    - Belt: set_default_color_theme(path) — the official CTk way
    - Suspenders: direct ThemeManager.theme modification — guaranteed

    Returns:
        True if the theme was applied (either method), False only if
        BOTH methods fail (which would indicate a CTk import error).
    """
    try:
        import customtkinter as ctk
        from customtkinter import ThemeManager
    except ImportError:
        print("[theme.py] CRITICAL: customtkinter not installed", flush=True)
        return False

    # --- BELT: try the official set_default_color_theme(path) ---
    json_loaded = False
    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        need_write = True
        if CTK_THEME_JSON_PATH.exists():
            try:
                existing = CTK_THEME_JSON_PATH.read_text()
                if existing == json.dumps(_CTk_THEME_DATA, indent=2):
                    need_write = False
            except Exception:
                pass
        if need_write:
            CTK_THEME_JSON_PATH.write_text(
                json.dumps(_CTk_THEME_DATA, indent=2), encoding="utf-8")
        ctk.set_default_color_theme(str(CTK_THEME_JSON_PATH))
        json_loaded = True
    except Exception as e:
        print(f"[theme.py] set_default_color_theme failed (will use "
              f"NUCLEAR approach): {e}", flush=True)

    # --- SUSPENDERS: directly modify ThemeManager.theme dict ---
    # This is the GUARANTEED method. We directly set every widget's
    # color properties in the in-memory theme dict. No file loading,
    # no JSON parsing, no path issues. Pure Python dict assignment.
    # This CANNOT silently fail — if the dict exists, the assignment
    # works. If CTk reads from this dict when creating widgets (which
    # it does), our colors WILL be applied.
    # Each widget type is wrapped in its own try/except so one missing
    # key (e.g. CTkTabview on CTk 6.0) doesn't block the others.
    t = ThemeManager.theme
    nuclear_ok = True

    def _set(widget_key, props):
        """Set theme properties for a widget, ignoring missing keys."""
        nonlocal nuclear_ok
        try:
            w = t[widget_key]
            for k, v in props.items():
                w[k] = v
        except KeyError:
            pass  # Widget type doesn't exist in this CTk version — skip
        except Exception as e:
            print(f"[theme.py] Theme set failed for {widget_key}: {e}", flush=True)
            nuclear_ok = False

    _set("CTk", {"fg_color": "#0a0c10"})
    _set("CTkFrame", {"corner_radius": 6, "border_width": 0, "fg_color": "#1c2028", "top_fg_color": "#262a30", "border_color": "#2a2f38"})
    _set("CTkButton", {"corner_radius": 10, "border_width": 0, "fg_color": "#e0a957", "hover_color": "#f5c878", "border_color": "#2a2f38", "text_color": "#1a1410", "text_color_disabled": "#6b7280"})
    _set("CTkLabel", {"corner_radius": 0, "border_width": 0, "fg_color": "transparent", "border_color": "#2a2f38", "text_color": "#e8eaed"})
    _set("CTkEntry", {"corner_radius": 6, "border_width": 1, "fg_color": "#252a33", "border_color": "#2a2f38", "text_color": "#e8eaed", "placeholder_text_color": "#6b7280"})
    _set("CTkCheckBox", {"corner_radius": 4, "border_width": 2, "fg_color": "#e0a957", "border_color": "#3a4049", "hover_color": "#f5c878", "checkmark_color": "#1a1410", "text_color": "#e8eaed", "text_color_disabled": "#6b7280"})
    _set("CTkSwitch", {"corner_radius": 1000, "border_width": 2, "progress_color": "#e0a957", "fg_color": "#2a2f38", "border_color": "#3a4049", "hover_color": "#f5c878", "text_color": "#e8eaed", "text_color_disabled": "#6b7280"})
    _set("CTkProgressBar", {"corner_radius": 4, "border_width": 0, "fg_color": "#2a2f38", "progress_color": "#e0a957"})
    _set("CTkSlider", {"corner_radius": 4, "fg_color": "#2a2f38", "progress_color": "#e0a957", "button_color": "#e0a957", "button_hover_color": "#f5c878"})
    _set("CTkOptionMenu", {"corner_radius": 6, "fg_color": "#252a33", "button_color": "#2a2f38", "button_hover_color": "#3a4049", "text_color": "#e8eaed", "text_color_disabled": "#6b7280"})
    _set("CTkComboBox", {"corner_radius": 6, "border_width": 1, "fg_color": "#252a33", "border_color": "#2a2f38", "button_color": "#2a2f38", "button_hover_color": "#3a4049", "text_color": "#e8eaed", "text_color_disabled": "#6b7280"})
    _set("CTkScrollableFrame", {"corner_radius": 6, "border_width": 1, "fg_color": "#1c2028", "border_color": "#2a2f38", "label_fg_color": "#262a30"})
    _set("CTkSegmentedButton", {"corner_radius": 6, "border_width": 0, "fg_color": "#2a2f38", "selected_color": "#e0a957", "selected_hover_color": "#f5c878", "unselected_color": "#252a33", "unselected_hover_color": "#2a2f38", "text_color": "#e8eaed", "text_color_disabled": "#6b7280"})
    _set("CTkTextbox", {"corner_radius": 6, "border_width": 1, "fg_color": "#252a33", "border_color": "#2a2f38", "text_color": "#e8eaed"})
    _set("CTkTabview", {"corner_radius": 6, "border_width": 1, "fg_color": "#1c2028", "border_color": "#2a2f38", "segmented_button_fg_color": "#2a2f38", "segmented_button_selected_color": "#e0a957", "segmented_button_selected_hover_color": "#f5c878", "segmented_button_unselected_color": "#252a33", "segmented_button_unselected_hover_color": "#2a2f38"})
    _set("CTkToplevel", {"fg_color": "#1c2028"})
    _set("CTkMenu", {"corner_radius": 6, "fg_color": "#252a33", "hover_color": "#2a2f38", "text_color": "#e8eaed"})

    # --- VERIFY ---
    try:
        button_color = ThemeManager.theme.get("CTkButton", {}).get("fg_color")
        expected_gold = "#e0a957"
        color_str = str(button_color)
        if expected_gold in color_str:
            method = "JSON + NUCLEAR" if json_loaded else "NUCLEAR only"
            print(f"[theme.py] CTk theme APPLIED via {method}: \u2713 "
                  f"(CTkButton fg_color = {button_color} = our gold)",
                  flush=True)
            return True
        else:
            print(f"[theme.py] CTk theme FAILED: CTkButton fg_color = "
                  f"{button_color!r}, expected {expected_gold!r}",
                  flush=True)
            return False
    except Exception as e:
        print(f"[theme.py] CTk theme verification error: {e}", flush=True)
        return False

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
    # Fix #6 (UI-REDESIGN-DASH-V2): warmer tint (was #252a33).
    # The original was slightly cool (blue-leaning). #262a30 has more
    # red + less blue, giving the elevated surfaces a warmer, more
    # inviting feel without breaking the palette system.
    bg_card_elevated = "#262a30"    # Hover, active tab, dialog, dropdown

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
    DISPLAY_SMALL = 24   # Phase 1.5 — screen H1 titles + top bar wordmark
                         # (Oswald Bold — the "stadium scoreboard" feel per
                         # UI_REDESIGN_VISUAL_PLAN §3.3. Smaller than DISPLAY
                         # so it fits in the 60px top bar + reads as a title,
                         # not a splash.)
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

# CRITICAL FIX (Task THEME-FONT-FIX-V2): The prior approach registered
# each Inter weight under a UNIQUE family name ("Inter-Regular",
# "Inter-Medium", etc.) via tk.call('font', 'create', ...). This was
# WRONG — GDI (via AddFontResourceW) registers the font under its
# REAL internal family name: just "Inter". So Tk looked for
# "Inter-Regular" in GDI, didn't find it, fell back to Arial.
#
# The fix: use the REAL GDI family name "Inter" for ALL weights.
# Tk resolves weights via the 'weight' parameter in font tuples
# ("normal" vs "bold"), NOT via family names. For Medium/SemiBold,
# we use "normal" weight (Tk doesn't support Medium/SemiBold as
# weight values — only normal/bold). The visual difference between
# Regular and Medium is minimal; Bold is correctly distinguished.
#
# We keep the per-weight constants as ALIASES pointing at "Inter" for
# backward compat with code that references them, but they ALL
# resolve to "Inter" now.
INTER_REG_FAMILY = "Inter"
INTER_MEDIUM_FAMILY = "Inter"
INTER_SEMIBOLD_FAMILY = "Inter"
INTER_BOLD_FAMILY = "Inter"

# Legacy family name — same as the per-weight names now
INTER_FAMILY = "Inter"
JETBRAINS_MONO_FAMILY = "JetBrains Mono"
SOURCE_SERIF_FAMILY = "Source Serif Pro"
DISPLAY_FAMILY = "Oswald"

# Resolved family names — set by _register_fonts().
INTER_REG_FAMILY_RESOLVED = INTER_REG_FAMILY
INTER_MEDIUM_FAMILY_RESOLVED = INTER_MEDIUM_FAMILY
INTER_SEMIBOLD_FAMILY_RESOLVED = INTER_SEMIBOLD_FAMILY
INTER_BOLD_FAMILY_RESOLVED = INTER_BOLD_FAMILY
INTER_FAMILY_RESOLVED = INTER_FAMILY
JETBRAINS_MONO_FAMILY_RESOLVED = JETBRAINS_MONO_FAMILY
SOURCE_SERIF_FAMILY_RESOLVED = SOURCE_SERIF_FAMILY
DISPLAY_FAMILY_RESOLVED = DISPLAY_FAMILY

_fonts_registered = False
# Tracks per-family availability — used by _print_font_summary()
# to log resolved vs fallback at startup. Per UI_REDESIGN §3.1 fix #3.
# HONEST VERIFICATION (Task THEME-FONT-FIX): this dict is set to True
# ONLY when Tk can actually resolve the family (verified via
# font.actual('family')). Prior versions set True whenever
# _register_one_font returned True, which was misleading because
# Method 2 (without -file) returns True even for non-existent families.
# CRITICAL: since all Inter weights now share the family name "Inter",
# the _font_families_available dict only needs ONE entry for Inter.
# We test "Inter" (the GDI family), not "Inter-Regular" (the fake name).
_font_families_available = {
    INTER_FAMILY: False,          # "Inter" — all 4 weights share this
    JETBRAINS_MONO_FAMILY: False,  # "JetBrains Mono"
    SOURCE_SERIF_FAMILY: False,    # "Source Serif Pro"
    DISPLAY_FAMILY: False,         # "Oswald"
}
# Tracks what Tk ACTUALLY resolved each family to (for diagnostic).
# If a family is available, this is the family name Tk returned.
# If not, this is the fallback family Tk used (e.g. 'fixed', 'Segoe UI').
_font_families_actual: dict[str, str] = {}


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
        slant: "normal" or "italic". NOTE: Tk 9.0 expects "roman" for
            upright; Tk 8.6 expects "normal". We try BOTH internally
            so this works on either version.
        weight: "normal" or "bold" (informational — the family name
            already encodes the weight for per-weight families).
        internal_name: optional Tk font name. Defaults to
            f"{family}_{slant}_{weight}". Use this when registering
            multiple fonts under the same family name (e.g. Source
            Serif Pro has 4 variants: regular/semibold/italic/semibold-italic).

    Methods (tried in order):
      1. tk.call("font", "create", ... "-file", path) — works on
         older Tk builds (Tk 8.x). Tk 9.0 removed the -file option,
         so this method fails with "bad option '-file'" on Tk 9.0.
         We try it first for backward compat.
      2. tk.call("font", "create", ...) without -file — creates a
         named font with the given family/slant/weight. The family
         is resolved by Tk's font search at render time. This works
         when the TTF is in a known font directory (installed via
         _install_fonts_to_user_dir + _register_fonts_windows_native
         on Windows, or fc-cache on Linux) OR has been loaded by
         name via another mechanism.
      3. If slant="normal" failed, retry with slant="roman" (and
         vice-versa) — Tk 9.0 expects "roman" for upright, Tk 8.6
         expects "normal". Without this retry, the font_create call
         silently fails on whichever Tk version uses the "wrong" word.

    Returns True if any method succeeded, False otherwise. Idempotent
    — does not raise if the font is already registered.
    """
    if not font_path.exists():
        return False
    # Tk 9.0 expects "roman" for upright slant; Tk 8.6 expects "normal".
    # Try BOTH slant names — whichever one this Tk version accepts.
    tk_slants = []
    if slant == "normal":
        tk_slants = ["roman", "normal"]  # Tk 9.0 first, Tk 8.6 fallback
    elif slant == "italic":
        tk_slants = ["italic"]  # Same on both versions
    else:
        tk_slants = [slant]
    name = internal_name or f"{family}_{slant}_{weight}"

    # Method 1: -file registration (Tk 8.x only — Tk 9.0 removed this
    # option). Actually loads the TTF into Tk's font registry on
    # platforms that support it.
    for tk_slant in tk_slants:
        try:
            root.tk.call(
                "font", "create", name,
                "-family", family,
                "-slant", tk_slant,
                "-weight", weight,
                "-file", str(font_path),
            )
            return True
        except tk.TclError:
            pass  # Already registered, or method 1 unsupported — try next.

    # Method 2: register the name without -file. The family is then
    # resolved by Tk's font search at render time. This works when
    # the TTF is in a known font directory OR has been loaded by name
    # via another mechanism (e.g. AddFontResourceW on Windows).
    for tk_slant in tk_slants:
        try:
            root.tk.call(
                "font", "create", name,
                "-family", family,
                "-slant", tk_slant,
                "-weight", weight,
            )
            return True
        except tk.TclError:
            continue
    return False  # Give up — caller falls back to platform default.


def _register_fonts_windows_native(font_dir=None):
    """On Windows, register bundled TTFs with the OS font system.

    THE WINDOWS-SPECIFIC FIX (Task THEME-FONT-FIX):
    Just copying TTFs to %LOCALAPPDATA%\\Fonts does NOT register them
    with Windows GDI. Tk on Windows uses GDI to enumerate fonts, so
    a TTF placed in an arbitrary folder is invisible to Tk — Tk falls
    back to platform default fonts (Segoe UI), which is exactly the
    "boring fonts" the user sees.

    The RELIABLE way to make Tk find a font by family name on Windows
    is to call the Win32 API:
      1. AddFontResourceW(path)  — registers the TTF with GDI for the
         current session. Returns the number of fonts added.
      2. SendMessageTimeoutW(HWND_BROADCAST, WM_FONTCHANGE, ...)
         — broadcasts a message so all running apps (including our
         Tk process) refresh their font list.
      3. Write the font to HKCU\\SOFTWARE\\Microsoft\\Windows NT\\
         CurrentVersion\\Fonts in the registry — makes the
         registration persistent across reboots.

    Args:
        font_dir: the directory containing the TTFs to register.
            Defaults to the bundled FONTS_DIR.

    Returns:
        Number of fonts successfully registered via AddFontResourceW
        (0 on non-Windows platforms, 0 if all calls fail).
    """
    import platform
    if platform.system().lower() != "windows":
        return 0

    # Late imports — only loaded on Windows. These are stdlib on
    # Windows but not available on Linux/Mac, so importing them at
    # module level would break cross-platform dev.
    import ctypes
    import os
    import shutil
    import winreg  # type: ignore[import-not-found]
    from ctypes import wintypes

    if font_dir is None:
        font_dir = FONTS_DIR
    font_dir = Path(font_dir)
    if not font_dir.exists():
        return 0

    # Win32 API bindings.
    # AddFontResourceW(path): makes a font available to all apps in
    # the current session. Returns the number of fonts added (0 = fail).
    # https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-addfontresourcew
    gdi32 = ctypes.windll.gdi32
    gdi32.AddFontResourceW.argtypes = [wintypes.LPCWSTR]
    gdi32.AddFontResourceW.restype = ctypes.c_int

    # SendMessageTimeoutW: broadcasts WM_FONTCHANGE so running apps
    # (including Tk) refresh their font list. We pass NULL for the
    # result pointer (we don't care about the return value).
    # NOTE: we deliberately do NOT set argtypes here — on Python 3.14
    # ctypes.wintypes doesn't have DWORD_PTR, and the strict argtypes
    # caused a crash. Without argtypes, ctypes auto-converts the args,
    # which works fine for this simple broadcast.
    # https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw
    user32 = ctypes.windll.user32

    WM_FONTCHANGE = 0x001D
    HWND_BROADCAST = 0xFFFF
    SMTO_ABORTIFHUNG = 0x0002

    # User font dir — we also copy the TTF here so the registry entry
    # has a stable path (the bundled dir may move if the app is
    # relocated).
    user_font_dir = Path(os.environ.get(
        "LOCALAPPDATA", str(Path.home()))) / "Fonts"
    try:
        user_font_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[theme.py] Warning: could not create user font dir "
              f"{user_font_dir}: {e}", flush=True)
        user_font_dir = None

    count_added = 0
    registry_entries = 0
    for ttf in font_dir.glob("*.ttf"):
        # Step 1: copy to user font dir (for registry persistence).
        # WinError 32 FIX: if the file already exists at the dest, skip
        # the copy. AddFontResourceW from a PREVIOUS app launch may still
        # have the source file locked (GDI keeps file handles open until
        # the process fully exits). Re-copying is unnecessary — the file
        # is already there from a prior launch. Just use it.
        dest_path = None
        if user_font_dir is not None:
            dest_path = user_font_dir / ttf.name
            if not dest_path.exists():
                # File doesn't exist yet — try to copy. If the source is
                # locked (WinError 32), fall back to the bundled path.
                try:
                    shutil.copy2(ttf, dest_path)
                except Exception as e:
                    print(f"[theme.py] Warning: could not copy font "
                          f"{ttf.name} to user dir: {e}", flush=True)
                    dest_path = None  # Fall back to bundled path.
            # If dest already exists, skip the copy silently (no warning).

        # Step 2: AddFontResourceW — make available to GDI this session.
        # Prefer the user-font-dir copy (registry entry will point at it).
        register_path = str(dest_path) if dest_path else str(ttf)
        try:
            added = gdi32.AddFontResourceW(register_path)
            if added > 0:
                count_added += added
            else:
                print(f"[theme.py] AddFontResourceW returned 0 for "
                      f"{ttf.name} (may already be registered, or "
                      f"the TTF is invalid)", flush=True)
        except Exception as e:
            print(f"[theme.py] AddFontResourceW failed for "
                  f"{ttf.name}: {e}", flush=True)
            continue

        # Step 3: register in HKCU registry so the font persists
        # across reboots. The registry value name is the human-
        # readable font name + " (TrueType)"; the value is the path.
        if dest_path is not None:
            try:
                # Use the TTF stem (without weight suffix) as the
                # registry value name. E.g. "Inter-Regular" -> "Inter Regular".
                font_name = ttf.stem.replace("-", " ")
                with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER,
                    "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Fonts",
                    0, winreg.KEY_SET_VALUE,
                ) as key:
                    winreg.SetValueEx(
                        key, f"{font_name} (TrueType)", 0,
                        winreg.REG_SZ, str(dest_path),
                    )
                registry_entries += 1
            except Exception as e:
                # Registry write failed — non-fatal. The font is still
                # available this session via AddFontResourceW.
                print(f"[theme.py] Warning: registry write failed for "
                      f"{ttf.name}: {e}", flush=True)

    # Step 4: broadcast WM_FONTCHANGE so Tk refreshes its font list
    # immediately (without this, Tk won't see the new fonts until the
    # app is restarted). We pass 0 (NULL) for the result pointer — we
    # don't care about the return value. ctypes auto-converts ints to
    # the right pointer type when argtypes aren't set.
    if count_added > 0:
        try:
            user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_FONTCHANGE, 0, 0,
                SMTO_ABORTIFHUNG, 1000, 0,
            )
            print(f"[theme.py] Windows font registration: "
                  f"AddFontResourceW added {count_added} font(s), "
                  f"WM_FONTCHANGE broadcast, {registry_entries} "
                  f"registry entries written.", flush=True)
        except Exception as e:
            print(f"[theme.py] Warning: WM_FONTCHANGE broadcast "
                  f"failed: {e} (fonts are still available this "
                  f"session, but other running apps won't see them "
                  f"until restart)", flush=True)
    else:
        print(f"[theme.py] Windows font registration: 0 fonts added "
              f"via AddFontResourceW (all calls returned 0 — fonts "
              f"may already be installed, or the TTFs are invalid).",
              flush=True)

    return count_added


def _install_fonts_to_user_dir():
    """Copy bundled TTFs to the user's font directory (Fix #2).

    tk.call('font', 'create', ..., '-file', ...) is unreliable on many
    platforms — Tk's font registry sometimes loses the family name and
    tk.call('font', 'families') doesn't list them. The RELIABLE way
    to make Tk find a font by family name is to install it in the
    OS's user font directory:
      - Linux:   ~/.fonts/      (+ run fc-cache -f)
      - macOS:   ~/Library/Fonts/  (auto-detected on next launch)
      - Windows: %LOCALAPPDATA%/Fonts/  (REQUIRES AddFontResourceW +
                  WM_FONTCHANGE broadcast — see
                  _register_fonts_windows_native(). Just copying
                  the file does NOT register it with GDI.)

    On Windows, this function ALSO calls
    _register_fonts_windows_native() — without that call, Tk on
    Windows will NOT see the fonts by family name, no matter how
    many times we copy the TTFs. This was THE bug causing the user
    to see "boring fonts" on Windows despite prior commits claiming
    fonts resolved (the prior commits were tested only on Linux+Xvfb,
    which is not representative of Windows behavior).

    Idempotent: only copies if the destination doesn't exist OR is
    older than the source. Returns the number of fonts copied.
    """
    import platform
    import shutil
    import subprocess
    import os

    system = platform.system().lower()
    if system == "windows":
        font_dir = Path(os.environ.get(
            "LOCALAPPDATA", str(Path.home()))) / "Fonts"
    elif system == "darwin":
        font_dir = Path.home() / "Library" / "Fonts"
    else:  # Linux
        font_dir = Path.home() / ".fonts"

    try:
        font_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[theme.py] Warning: could not create font dir "
              f"{font_dir}: {e}", flush=True)
        # On Windows we can still try AddFontResourceW on the bundled
        # TTFs (they don't need to be in the user font dir for that).
        if system == "windows":
            try:
                _register_fonts_windows_native(FONTS_DIR)
            except Exception as e2:
                print(f"[theme.py] Windows native font registration "
                      f"also failed: {e2}", flush=True)
        return 0

    bundled_dir = FONTS_DIR
    if not bundled_dir.exists():
        return 0

    copied = 0
    for ttf in bundled_dir.glob("*.ttf"):
        dest = font_dir / ttf.name
        # WinError 32 FIX: skip copy if dest already exists. On Windows,
        # AddFontResourceW from a previous launch may have the SOURCE
        # file locked (GDI keeps handles open). Re-copying is unnecessary
        # + produces scary WinError 32 warnings. Just use the existing copy.
        if dest.exists():
            continue
        try:
            shutil.copy2(ttf, dest)
            copied += 1
        except Exception as e:
            # WinError 32 (file in use) is EXPECTED on Windows if a
            # previous app instance is still running or GDI hasn't
            # released the handle. Don't print a warning — just skip.
            # The font is already registered via AddFontResourceW from
            # the _register_fonts_windows_native call below.
            pass

    # Run fc-cache on Linux so the new fonts are picked up immediately.
    if system != "windows" and system != "darwin":
        try:
            subprocess.run(
                ["fc-cache", "-f", str(font_dir)],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass  # Non-fatal — fonts may still be found on next launch.

    # WINDOWS-SPECIFIC FIX (Task THEME-FONT-FIX):
    # On Windows, copying the TTF is NOT enough. We MUST also call
    # AddFontResourceW + broadcast WM_FONTCHANGE so Tk (which uses
    # GDI) picks up the fonts by family name in the CURRENT session.
    # Without this, the user sees "boring fonts" (Segoe UI fallback)
    # on Windows even though the TTFs are in %LOCALAPPDATA%\\Fonts.
    # On macOS, the system auto-detects fonts in ~/Library/Fonts.
    if system == "windows":
        try:
            _register_fonts_windows_native(bundled_dir)
        except Exception as e:
            print(f"[theme.py] Windows native font registration "
                  f"failed: {e}", flush=True)
            import traceback
            traceback.print_exc()

    return copied


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
    global _font_families_actual
    if _fonts_registered:
        return

    # Fix #2 (UI-REDESIGN-DASH-V2): copy bundled TTFs to the user's
    # font directory BEFORE any Tk font registration. tk.call('font',
    # 'create', ..., '-file', ...) is unreliable — Tk's font registry
    # sometimes loses the family name. Installing the TTFs in
    # ~/.fonts/ (Linux), ~/Library/Fonts/ (Mac), or
    # %LOCALAPPDATA%/Fonts/ (Windows) makes Tk's font search find
    # them by family name. This is the BELT; the tk.call approach
    # below is the SUSPENDERS.
    try:
        _install_fonts_to_user_dir()
    except Exception as e:
        print(f"[theme.py] Warning: font install to user dir failed: "
              f"{e}", flush=True)

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
        # CRITICAL FIX (Task THEME-FONT-FIX-V2): we NO LONGER use
        # tk.call('font', 'create', ...) to register named fonts. The
        # prior approach created named fonts with fake family names
        # ('Inter-Regular', 'Inter-Medium', etc.) that didn't match
        # GDI's real family name ('Inter'). Tk fell back to Arial.
        #
        # Instead, we rely ENTIRELY on the OS font system:
        # - Windows: AddFontResourceW (called from _install_fonts_to_user_dir)
        # - Linux: fc-cache after copying to ~/.fonts/
        # - Mac: auto-detect after copying to ~/Library/Fonts/
        #
        # After the OS registers the fonts, Tk can find them by family
        # name via font.actual('family'). The font tuples in OfficeFonts
        # / FightNightFonts use the real family names ('Inter', 'Oswald',
        # etc.) + specify weight ('normal'/'bold') in the tuple. Tk
        # resolves the correct weight from the OS font system.
        #
        # We still call _register_one_font as a FALLBACK (it tries to
        # load the TTF directly via tk.call's -file option). This helps
        # on platforms where the OS font system isn't set up (e.g.
        # headless Linux/Xvfb). But the primary path is the OS font system.
        inter_fonts = [
            (FONT_INTER_REGULAR,   INTER_FAMILY, "normal", "normal"),
            (FONT_INTER_BOLD,      INTER_FAMILY, "normal", "bold"),
        ]
        for font_path, family, slant, weight in inter_fonts:
            try:
                _register_one_font(root, font_path, family, slant, weight)
            except Exception:
                pass  # Non-fatal — OS font system is the primary path.

        # JetBrains Mono
        try:
            _register_one_font(root, FONT_JETBRAINS_MONO,
                               JETBRAINS_MONO_FAMILY, "normal", "normal")
        except Exception:
            pass

        # Source Serif Pro — 4 variants
        serif_fonts = [
            (FONT_SOURCE_SERIF_REGULAR,         SOURCE_SERIF_FAMILY, "normal", "normal"),
            (FONT_SOURCE_SERIF_SEMIBOLD,        SOURCE_SERIF_FAMILY, "normal", "bold"),
            (FONT_SOURCE_SERIF_ITALIC,          SOURCE_SERIF_FAMILY, "italic", "normal"),
            (FONT_SOURCE_SERIF_SEMIBOLD_ITALIC, SOURCE_SERIF_FAMILY, "italic", "bold"),
        ]
        for font_path, family, slant, weight in serif_fonts:
            try:
                _register_one_font(root, font_path, family, slant, weight)
            except Exception:
                pass

        # Oswald Bold
        try:
            _register_one_font(root, FONT_OSWALD_BOLD,
                               DISPLAY_FAMILY, "normal", "bold")
        except Exception:
            pass

        # Verify each family is ACTUALLY resolvable by Tk — not just
        # "registered" via tk.call (which can succeed even when the
        # family doesn't exist, because Method 2 just creates a named
        # font pointing at a family string).
        #
        # THE BUG THIS FIXES (Task THEME-FONT-FIX):
        # Prior commits claimed "ALL 7 FONTS RESOLVE ✓" based on
        # _register_one_font returning True. But Method 2 (without
        # -file) returns True even when it just creates an empty
        # named font pointing at a family Tk can't find. The actual
        # rendering falls back to a system default. The ✓ was a lie.
        #
        # The HONEST verification: create a font with family=<fam>,
        # then check font.actual('family'). If Tk returns the SAME
        # family name, the font is loaded. If Tk returns a DIFFERENT
        # name (e.g. 'fixed', 'nimbus sans l', 'Segoe UI'), Tk fell
        # back — the family is NOT actually resolvable.
        try:
            import tkinter.font as tkfont
        except Exception:
            tkfont = None
        # Test each UNIQUE family name. Since all Inter weights now share
        # "Inter", we only test it once. Deduplicate via dict.fromkeys.
        families_to_test = dict.fromkeys([
            INTER_FAMILY,  # "Inter" — all 4 weights share this
            JETBRAINS_MONO_FAMILY,
            SOURCE_SERIF_FAMILY,
            DISPLAY_FAMILY,
        ])
        for fam in families_to_test:
            actually_resolvable = False
            if tkfont is not None:
                try:
                    probe = tkfont.Font(root, family=fam, size=15)
                    actual_family = probe.actual("family")
                    # Tk may normalize the family name (lowercase, etc.).
                    # Accept case-insensitive match OR substring match.
                    if (isinstance(actual_family, str)
                            and (actual_family.lower() == fam.lower()
                                 or fam.lower() in actual_family.lower()
                                 or actual_family.lower() in fam.lower())):
                        actually_resolvable = True
                    else:
                        # Tk returned a DIFFERENT family — it fell back.
                        # Record this for the diagnostic.
                        _font_families_actual[fam] = actual_family
                    # Clean up the probe font.
                    try:
                        probe.delete()
                    except Exception:
                        pass
                except Exception:
                    pass
            if actually_resolvable:
                _font_families_available[fam] = True
            else:
                # HONEST VERDICT: the family is NOT resolvable by Tk.
                # Setting False here means _apply_platform_fallbacks()
                # will use a platform default font, and the summary
                # will print ✗. This is the truth — a False ✓ is worse
                # than an honest ✗ because it hides the problem.
                _font_families_available[fam] = False
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

    # All Inter weights now share the single "Inter" GDI family.
    # If "Inter" is available, ALL weights resolve to it. Tk distinguishes
    # bold from normal via the weight parameter in font tuples.
    inter_available = _font_families_available.get(INTER_FAMILY, False)
    inter_resolved = INTER_FAMILY if inter_available else _platform_default_sans()

    INTER_REG_FAMILY_RESOLVED = inter_resolved
    INTER_MEDIUM_FAMILY_RESOLVED = inter_resolved
    INTER_SEMIBOLD_FAMILY_RESOLVED = inter_resolved
    INTER_BOLD_FAMILY_RESOLVED = inter_resolved
    INTER_FAMILY_RESOLVED = inter_resolved

    JETBRAINS_MONO_FAMILY_RESOLVED = (
        JETBRAINS_MONO_FAMILY
        if _font_families_available.get(JETBRAINS_MONO_FAMILY, False)
        else _platform_default_mono())

    SOURCE_SERIF_FAMILY_RESOLVED = (
        SOURCE_SERIF_FAMILY
        if _font_families_available.get(SOURCE_SERIF_FAMILY, False)
        else _platform_default_sans())

    # Display family (Oswald) — falls back to Inter, else platform sans.
    if _font_families_available.get(DISPLAY_FAMILY, False):
        DISPLAY_FAMILY_RESOLVED = DISPLAY_FAMILY
    elif inter_available:
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
    # CRITICAL FIX: test the REAL GDI family name "Inter", not the fake
    # per-weight names. All 4 Inter weights share the "Inter" GDI family.
    # Tk resolves weight via the weight= param in font tuples, not family.
    roles = [
        ("Inter",           INTER_FAMILY,
         INTER_FAMILY_RESOLVED),
        ("JetBrains Mono",  JETBRAINS_MONO_FAMILY,
         JETBRAINS_MONO_FAMILY_RESOLVED),
        ("Source Serif Pro", SOURCE_SERIF_FAMILY,
         SOURCE_SERIF_FAMILY_RESOLVED),
        ("Oswald",          DISPLAY_FAMILY,
         DISPLAY_FAMILY_RESOLVED),
    ]
    for label, requested, resolved in roles:
        ok = _font_families_available.get(requested, False)
        actual = _font_families_actual.get(requested)
        if ok and resolved == requested:
            mark = "✓ (resolved)"
        elif ok:
            mark = "✓ (resolved, but display name differs)"
        else:
            # HONEST FAILURE REPORT (Task THEME-FONT-FIX):
            # Show what Tk ACTUALLY resolved the family to, so the
            # user/developer can see exactly what's happening. Prior
            # versions just said "fallback to 'Sans'" which hid the
            # real issue (Tk was falling back to legacy X11 fonts
            # like 'fixed' or 'nimbus sans l' on Linux, or 'Segoe UI'
            # on Windows, because the bundled TTFs were never
            # registered with the OS font system).
            if actual and actual != resolved:
                mark = (f"✗ (Tk resolved to {actual!r}, "
                        f"using fallback {resolved!r})")
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
    display_small = (DISPLAY_FAMILY_RESOLVED, FontSizes.DISPLAY_SMALL, "bold")
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
    display_small = (DISPLAY_FAMILY_RESOLVED, FontSizes.DISPLAY_SMALL, "bold")
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
# 256×256 PNG, 8% opacity grey noise. Tiled across bg_base (Office +
# Fight Night). Adds the "this is a real surface, not a flat fill"
# feel — VISIBLE as a faint grain, not a flat fill (UI-PHASE-3:
# opacity bumped 3% → 8% so the player can actually perceive the
# texture; the previous 3% was below the threshold of perception).
NOISE_GRAIN_PATH = TEXTURES_DIR / "noise_grain.png"
NOISE_GRAIN_SIZE = (256, 256)


def _generate_noise_grain():
    """Generate 256×256 8% opacity grey noise via PIL.

    UI-PHASE-3: opacity bumped from 3% (alpha 5-12) to 8% (alpha
    18-26) so the grain is faintly visible as a "real surface"
    texture instead of imperceptible.
    """
    try:
        from PIL import Image
        import random
    except ImportError:
        return None
    w, h = NOISE_GRAIN_SIZE
    # Start with a transparent image.
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    # 8% opacity ≈ alpha 20 (out of 255). Grey noise = r=g=b=random.
    # The noise is subtle — only the alpha channel varies the visibility.
    for y in range(h):
        for x in range(w):
            v = random.randint(110, 140)  # neutral grey
            # Vary alpha slightly to avoid a uniform grey wash.
            a = random.randint(18, 26)  # ~7-10% opacity (UI-PHASE-3)
            px[x, y] = (v, v, v, a)
    return img


def get_noise_grain_texture(size=None):
    """Return the noise_grain CTkImage, or None.

    Tiles an 8% opacity grey noise across bg_base. Cached at module
    level after first call.

    Args:
        size: optional (width, height) tuple. If larger than the
            base 256×256 tile, the noise is TILED across the larger
            canvas via PIL (not stretched). This is the Fix #3
            implementation for the main window background — we tile
            the 256×256 noise across a 1920×1080 canvas so the
            grain covers the full viewport without stretching
            artifacts.
    """
    if size is None:
        return _load_or_generate("noise_grain", NOISE_GRAIN_PATH,
                                 _generate_noise_grain, NOISE_GRAIN_SIZE)
    # Custom size — tile the noise across a larger canvas.
    cache_key = f"noise_grain_{size[0]}x{size[1]}"
    if cache_key in _texture_cache:
        return _texture_cache[cache_key]
    try:
        import customtkinter as ctk
        from PIL import Image
    except ImportError:
        _texture_cache[cache_key] = None
        return None
    try:
        # Load or generate the base 256×256 tile.
        if NOISE_GRAIN_PATH.exists():
            base = Image.open(NOISE_GRAIN_PATH).convert("RGBA")
        else:
            base = _generate_noise_grain()
            if base is None:
                _texture_cache[cache_key] = None
                return None
            base = base.convert("RGBA")
            try:
                _ensure_textures_dir()
                base.save(NOISE_GRAIN_PATH, "PNG")
            except Exception:
                pass
        # Tile across the target canvas.
        tw, th = size
        bw, bh = base.size
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        for y in range(0, th, bh):
            for x in range(0, tw, bw):
                canvas.paste(base, (x, y))
        ctk_img = ctk.CTkImage(light_image=canvas, dark_image=canvas,
                               size=(tw, th))
        _texture_cache[cache_key] = ctk_img
        return ctk_img
    except Exception as e:
        print(f"[theme.py] Warning: noise_grain tile failed: {e}",
              flush=True)
        _texture_cache[cache_key] = None
        return None


# ----- chain_link_dim.png -----
# 512×512 PNG, chain-link fence pattern at 12% opacity, slightly
# crimson-tinted. Tiled across bg_surface on Fight Night + composited
# onto the GradientHeader banner on every screen — the "cage" metaphor
# made literal. UI-PHASE-3: opacity bumped 4% → 12% so the chain-link
# pattern is VISIBLE as a subtle MMA motif (the previous 4% was below
# the threshold of perception).
CHAIN_LINK_DIM_PATH = TEXTURES_DIR / "chain_link_dim.png"
CHAIN_LINK_DIM_SIZE = (512, 512)


def _generate_chain_link_dim():
    """Generate 512×512 chain-link fence pattern at 12% opacity,
    crimson-tinted, via PIL.

    UI-PHASE-3: opacity bumped from 4% (alpha 10) to 12% (alpha 31)
    so the cage motif is faintly visible on Fight Night surfaces and
    the GradientHeader banner.
    """
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
    # UI-PHASE-3: alpha 10 → 31 (4% → ~12% opacity). The crimson tint
    # is now noticeable as a subtle MMA cage motif.
    line_color = (214, 58, 63, 31)  # crimson at ~12% opacity
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

    Tiles a 12% opacity crimson-tinted chain-link fence pattern across
    bg_surface on Fight Night + composited onto the GradientHeader
    banner. Cached at module level after first call.

    UI-PHASE-3: opacity bumped 4% → 12% so the chain-link motif is
    actually visible.
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
# MMA VISUAL ICONS (Fix #4 — UI-REDESIGN-DASH-V2)
# ============================================================
# Procedurally-generated MMA-specific icons:
#   - glove_icon: a boxing glove (gold) — for Fighter Watch section
#   - belt_icon: a championship belt (gold) — for Champions section
#   - cage_watermark: large faded logo mark — bottom-right watermark
#
# Each is a PIL-rendered CTkImage, cached after first generation.
# These give the Dashboard unmistakable MMA flavor without requiring
# external image assets.

_GLOVE_ICON_PATH = TEXTURES_DIR / "glove_icon.png"
_GLOVE_ICON_SIZE = (20, 20)

_BELT_ICON_PATH = TEXTURES_DIR / "belt_icon.png"
_BELT_ICON_SIZE = (20, 20)

_WATERMARK_PATH = TEXTURES_DIR / "cage_watermark.png"
_WATERMARK_SIZE = (192, 192)


def _generate_glove_icon(size=_GLOVE_ICON_SIZE):
    """Generate a boxing-glove icon (gold) via PIL.

    A simplified boxing glove: rounded-rect body + small thumb strap
    on the side. Solid gold with a darker outline.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    w, h = size
    # 4× supersample for AA.
    ss = 4
    big = (w * ss, h * ss)
    img = Image.new("RGBA", big, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    gold = (224, 169, 87, 255)        # #e0a957
    gold_dark = (180, 130, 60, 255)   # darker outline
    cuff = (40, 30, 20, 255)          # dark cuff

    # Glove body: a fat rounded rectangle taking up most of the icon.
    body_bbox = [ss, ss * 2, big[0] - ss * 2, big[1] - ss]
    draw.rounded_rectangle(body_bbox, radius=ss * 4, fill=gold,
                            outline=gold_dark, width=ss)

    # Thumb: a smaller rounded bump on the right side.
    thumb_bbox = [big[0] - ss * 5, big[1] - ss * 8,
                  big[0] - ss, big[1] - ss * 3]
    draw.rounded_rectangle(thumb_bbox, radius=ss * 3, fill=gold,
                            outline=gold_dark, width=ss)

    # Cuff (wrist strap) at the bottom.
    cuff_bbox = [ss * 2, big[1] - ss * 4,
                 big[0] - ss * 2, big[1] - ss]
    draw.rounded_rectangle(cuff_bbox, radius=ss * 2, fill=cuff)

    # Downsample.
    return img.resize((w, h), Image.LANCZOS)


def get_glove_icon():
    """Return the boxing-glove CTkImage (20×20, gold), or None."""
    return _load_or_generate("glove_icon", _GLOVE_ICON_PATH,
                             _generate_glove_icon, _GLOVE_ICON_SIZE)


def _generate_belt_icon(size=_BELT_ICON_SIZE):
    """Generate a championship-belt icon (gold) via PIL.

    A simplified championship belt: horizontal rounded-rect strap +
    a circular center plate. Solid gold with darker outline.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    w, h = size
    ss = 4
    big = (w * ss, h * ss)
    img = Image.new("RGBA", big, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    gold = (224, 169, 87, 255)
    gold_dark = (180, 130, 60, 255)
    plate_gold = (245, 200, 120, 255)  # brighter for the center plate
    leather = (60, 45, 30, 255)        # dark leather strap

    # Leather strap: horizontal rounded rectangle.
    strap_bbox = [ss, ss * 4, big[0] - ss, big[1] - ss * 4]
    draw.rounded_rectangle(strap_bbox, radius=ss * 2, fill=leather)

    # Center plate: a filled circle in the middle.
    cx, cy = big[0] // 2, big[1] // 2
    plate_r = min(big) // 3
    draw.ellipse([cx - plate_r, cy - plate_r,
                  cx + plate_r, cy + plate_r],
                 fill=plate_gold, outline=gold_dark, width=ss)

    # Inner plate detail: a smaller circle inside.
    inner_r = plate_r - ss * 2
    draw.ellipse([cx - inner_r, cy - inner_r,
                  cx + inner_r, cy + inner_r],
                 outline=gold_dark, width=ss)

    # Side studs: small gold circles on the strap.
    for sx in (ss * 3, big[0] - ss * 3):
        draw.ellipse([sx - ss, cy - ss, sx + ss, cy + ss], fill=gold)

    return img.resize((w, h), Image.LANCZOS)


def get_belt_icon():
    """Return the championship-belt CTkImage (20×20, gold), or None."""
    return _load_or_generate("belt_icon", _BELT_ICON_PATH,
                             _generate_belt_icon, _BELT_ICON_SIZE)


def _generate_watermark(size=_WATERMARK_SIZE):
    """Generate a large faded cage-empire watermark for the bottom-right.

    A simplified "CE" monogram inside an octagon (the MMA cage shape)
    at low opacity (10%). Used as a subtle branded paper feel.

    UI-PHASE-3: opacity bumped from 5% (alpha 12) to 10% (alpha 26)
    so the CE monogram in the bottom-right corner is faintly visible
    as a branded watermark (the previous 5% was below perception).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import math
    except ImportError:
        return None
    w, h = size
    ss = 4
    big = (w * ss, h * ss)
    img = Image.new("RGBA", big, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # UI-PHASE-3: alpha 12 → 26 (5% → ~10% opacity). The gold CE
    # monogram is now faintly visible as a branded watermark in the
    # bottom-right corner of the main window.
    gold_faded = (224, 169, 87, 26)

    # Octagon (MMA cage shape) outline.
    cx, cy = big[0] // 2, big[1] // 2
    r = min(big) // 2 - ss * 2
    points = []
    for i in range(8):
        angle = math.pi / 8 + i * math.pi / 4
        px = cx + r * math.cos(angle)
        py = cy + r * math.sin(angle)
        points.append((px, py))
    draw.polygon(points, outline=gold_faded, width=ss * 2)

    # "CE" monogram in the center (try Oswald, fall back to default).
    try:
        font = ImageFont.truetype(str(FONT_OSWALD_BOLD), r)
    except Exception:
        try:
            font = ImageFont.truetype(str(FONT_INTER_BOLD), r)
        except Exception:
            font = ImageFont.load_default()

    text = "CE"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw // 2
    ty = cy - th // 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=gold_faded)

    return img.resize((w, h), Image.LANCZOS)


def get_cage_watermark():
    """Return the cage watermark CTkImage (192×192, faded gold), or None."""
    return _load_or_generate("cage_watermark", _WATERMARK_PATH,
                             _generate_watermark, _WATERMARK_SIZE)


def get_logo_compact_ctk(size=(32, 32)):
    """Return the compact logo as a CTkImage, or None.

    Loads cage_empire_compact.png + scales it to the requested size.
    Used by GradientHeader for the brand mark on the left.
    """
    cache_key = f"logo_compact_{size[0]}x{size[1]}"
    if cache_key in _texture_cache:
        return _texture_cache[cache_key]
    try:
        import customtkinter as ctk
        from PIL import Image
    except ImportError:
        _texture_cache[cache_key] = None
        return None
    try:
        if not LOGO_COMPACT.exists():
            _texture_cache[cache_key] = None
            return None
        pil = Image.open(LOGO_COMPACT).convert("RGBA")
        pil = pil.resize(size, Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                               size=size)
        _texture_cache[cache_key] = ctk_img
        return ctk_img
    except Exception as e:
        print(f"[theme.py] Warning: logo compact load failed: {e}",
              flush=True)
        _texture_cache[cache_key] = None
        return None


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
