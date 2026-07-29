"""CAGE EMPIRE — Theme system (Stage 6 — Task 6.1).

The dual-mode visual design system: Office Mode (calm, data-dense,
institutional — 90% of gameplay) + Fight Night Mode (visceral,
dramatic, narrative — 10% that produces 90% of the dopamine).

Per docs/GUI_PLAN.md §3:
  - Office Mode: "Bloomberg Terminal meets ESPN scoreboard"
  - Fight Night Mode: "HBO 24/7 meets ESPN broadcast"

CONVENTIONS compliance:
  §13 — Design Law: the theme system supports every pillar by
        providing a consistent visual language across all 22
        screens. Office Mode serves Discovery/Investment/Growth/
        Legacy; Fight Night Mode serves Conflict.
  §14 — Voice Layer: the theme itself doesn't display text, but
        it defines the TYPOGRAPHY that all player-facing text uses.
        Font choices (Inter for body, JetBrains Mono for numbers,
        Source Serif Pro for fight commentary) are part of the
        interpretation layer — they shape how the player reads
        the simulation.
  §15 — Event Bus: the theme system is NOT event-bus-driven.
        Screen switching (Office ↔ Fight Night) is a UI-layer
        concern, triggered by navigation, not by game events.

Architecture:
  - COLORS: two dicts (OFFICE_COLORS, FIGHT_NIGHT_COLORS) with
    the full palette from GUI_PLAN.md §3.3.
  - FONTS: font family names + paths to bundled TTFs. Registered
    with tkinter on first import via _register_fonts().
  - THEME: a Theme class bundling colors + font sizes + asset
    paths. Two instances: OFFICE and FIGHT_NIGHT.
  - Asset paths: constants pointing to logo, icon, background,
    and font files under src/ui/assets/.

Usage:
  from ui.theme import OFFICE, FIGHT_NIGHT, CURRENT_THEME, set_theme

  # In a screen:
  label = ctk.CTkLabel(parent, text="Hello",
                        text_color=CURRENT_THEME.colors.text_primary,
                        font=CURRENT_THEME.fonts.body)
  # Switch to Fight Night:
  set_theme("fight_night")
"""

from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

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


# ============================================================
# COLOR PALETTES (per GUI_PLAN.md §3.3)
# ============================================================

class OfficeColors:
    """Office Mode color palette (default — 90% of gameplay).

    Mood: Calm, data-dense, institutional. "Bloomberg Terminal
    meets ESPN scoreboard." Reference: Football Manager 2024,
    OOTP Baseball, WMMA5 menu screens.
    """
    # Backgrounds
    bg_base = "#0f1115"          # Main window background
    bg_surface = "#1a1d23"       # Cards, panels, sidebar
    bg_surface_elevated = "#232730"  # Hover, active tab, dialog
    bg_border = "#2e333d"        # Subtle 1px separators

    # Text
    text_primary = "#e8eaed"     # Body, headings
    text_secondary = "#9aa0a6"   # Captions, metadata
    text_tertiary = "#5f6368"    # Disabled, timestamps

    # Co-primary accents (Crimson + Gold are EQUAL brand weight)
    crimson = "#c8323a"          # CAGE wordmark, loss, KO/TKO, injury, rival heat
    gold = "#d4a55a"             # EMPIRE wordmark, champion, title, win, HoF

    # Supporting
    steel = "#6b7280"            # Mid-tier UI elements
    success = "#4ade80"          # Signed, recovered
    warning = "#fbbf24"          # At-risk
    danger = "#ef4444"           # Cut, suspended, critical


class FightNightColors:
    """Fight Night Mode color palette (10% of gameplay, 90% of dopamine).

    Mood: Visceral, dramatic, narrative. "HBO 24/7 meets ESPN
    broadcast." Reference: HBO 24/7, UFC Countdown, NFL Films,
    ESPN 30 for 30.

    Only the Fight Resolution screen + pre-fight splash + post-fight
    recap use this mode. Everything else stays in Office Mode.
    """
    # Backgrounds (deeper — the arena goes dark)
    bg_base = "#08090c"          # Deeper black
    bg_surface = "#11141a"       # Slightly darker than Office
    bg_surface_elevated = "#1c2028"  # Active beat highlight
    bg_border = "#2a2f3a"

    # Text (brighter — punches through the darkness)
    text_primary = "#f5f6f8"     # Brighter
    text_secondary = "#b4b8c0"
    text_tertiary = "#6b7280"

    # Co-primary accents (brighter, more saturated — blood in spotlight)
    crimson = "#e53e3e"          # Brighter, more saturated
    gold = "#f0c060"             # Brighter — title belt under stage lights

    # Fight Night exclusive colours
    impact_yellow = "#fbbf24"    # Knockdowns, big moments, finish flashes

    # Heatmap colours (reserved exclusively for the cage heatmap widget)
    heat_blue = "#3b82f6"        # Low-activity zones
    heat_orange = "#f97316"      # Medium-activity zones
    heat_red = "#dc2626"         # High-activity / high-damage zones

    # Supporting (same as Office for consistency)
    steel = "#6b7280"
    success = "#4ade80"
    warning = "#fbbf24"
    danger = "#ef4444"


# ============================================================
# FONT SIZES (per GUI_PLAN.md §3.4)
# ============================================================

class FontSizes:
    """Font size constants (in px). Same for both modes — only the
    font FAMILY changes (Office uses Inter for commentary; Fight
    Night uses Source Serif Pro).

    Sizes increased for desktop readability — WMMA5/FM use 14-16px
    body text minimum. Body=15, captions bumped to 13 (was 12) per
    UI Polish Task UI-POLISH (user feedback: "text is too small").
    """
    DISPLAY = 36         # Splash, title bar
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

# Font family names (registered with tkinter via _register_fonts)
INTER_FAMILY = "Inter"
JETBRAINS_MONO_FAMILY = "JetBrains Mono"
SOURCE_SERIF_FAMILY = "Source Serif Pro"

# Eurostile Bold Extended is commercial — use Oswald (free, Google Fonts)
# as the display font. Oswald is a condensed geometric sans-serif that
# evokes stadium scoreboard / sports broadcast aesthetics.
# TODO (Task 6.1.5): download Oswald or commission a custom display font.
DISPLAY_FAMILY = "Oswald"  # fallback to Inter Bold if not available

_fonts_registered = False
_font_families_available = {
    INTER_FAMILY: False,
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


# Resolved family names — set by _register_fonts(). Start with the
# ideal names; fall back to platform defaults if registration fails.
INTER_FAMILY_RESOLVED = INTER_FAMILY
JETBRAINS_MONO_FAMILY_RESOLVED = JETBRAINS_MONO_FAMILY
SOURCE_SERIF_FAMILY_RESOLVED = SOURCE_SERIF_FAMILY
DISPLAY_FAMILY_RESOLVED = DISPLAY_FAMILY


def _register_one_font(root, font_path, family, slant, weight):
    """Try multiple methods to register a single TTF with Tk.

    Method 1: tk.call("font", "create", ... "-file", path) — works on
              most platforms but silently fails on some Windows Tk
              builds when the font file is already loaded.
    Method 2: tk.call("font", "create", ...) without -file, then use
              font.actual() to verify — fallback for cases where
              Method 1 raises but the font is still usable by name.
    Method 3: PIL ImageFont.truetype load test — if PIL can parse the
              TTF, we trust Tk to find it by family name (Tk 8.6+
              searches bundled TTFs in some configurations).

    Returns True if any method succeeded, False otherwise. Idempotent
    — does not raise if the font is already registered.
    """
    if not font_path.exists():
        return False
    name = f"{family}_{slant}_{weight}"
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
    by name (e.g., 'Inter' instead of loading the file each time).

    Robust across platforms (Windows / macOS / Linux). Falls back to
    sensible system fonts when bundled TTFs fail to register — the
    UI still works, just with a less branded typeface.

    Called automatically on first import of this module + on app
    construction (CageEmpireApp.__init__). Safe to call multiple times
    — checks _fonts_registered flag.
    """
    global _fonts_registered
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
        root = tk.Tk()
        root.withdraw()
        created_root = True

    # Track which families registered successfully. Each TTF is
    # registered under its family name with the appropriate slant +
    # weight; the SAME family name is used for all weights of Inter
    # (Regular, Medium, SemiBold, Bold) — Tk resolves the weight at
    # render time via the font tuple's weight element.
    try:
        font_files = [
            (FONT_INTER_REGULAR, INTER_FAMILY, "normal", "normal"),
            (FONT_INTER_MEDIUM, INTER_FAMILY, "normal", "normal"),
            (FONT_INTER_SEMIBOLD, INTER_FAMILY, "normal", "normal"),
            (FONT_INTER_BOLD, INTER_FAMILY, "normal", "normal"),
            (FONT_JETBRAINS_MONO, JETBRAINS_MONO_FAMILY, "normal", "normal"),
            (FONT_SOURCE_SERIF_REGULAR, SOURCE_SERIF_FAMILY, "normal", "normal"),
            (FONT_SOURCE_SERIF_SEMIBOLD, SOURCE_SERIF_FAMILY, "normal", "bold"),
            (FONT_SOURCE_SERIF_ITALIC, SOURCE_SERIF_FAMILY, "italic", "normal"),
            (FONT_SOURCE_SERIF_SEMIBOLD_ITALIC, SOURCE_SERIF_FAMILY, "italic", "bold"),
        ]
        for font_path, family, slant, weight in font_files:
            try:
                ok = _register_one_font(root, font_path, family, slant, weight)
                if ok:
                    _font_families_available[family] = True
            except Exception:
                # Individual font registration failure is non-fatal —
                # we fall back to platform defaults below.
                pass

        # Verify each family is actually usable by querying Tk's font
        # registry. A family may "register" via tk.call but not be
        # resolvable — tk.fontFamilies() is the source of truth.
        try:
            available_families = set(root.tk.call("font", "families"))
        except Exception:
            available_families = set()
        for fam in (INTER_FAMILY, JETBRAINS_MONO_FAMILY,
                    SOURCE_SERIF_FAMILY, DISPLAY_FAMILY):
            if fam in available_families:
                _font_families_available[fam] = True
            else:
                # Mark as unavailable so we fall back.
                _font_families_available[fam] = False
    finally:
        if created_root:
            root.destroy()

    # Resolve the family names: use the bundled family if available,
    # otherwise fall back to a platform-appropriate default. The
    # resolved names are what OfficeFonts / FightNightFonts use for
    # font tuples (set below in the FONTS RESOLUTION section).
    INTER_FAMILY_RESOLVED = (INTER_FAMILY
                             if _font_families_available[INTER_FAMILY]
                             else _platform_default_sans())
    JETBRAINS_MONO_FAMILY_RESOLVED = (
        JETBRAINS_MONO_FAMILY
        if _font_families_available[JETBRAINS_MONO_FAMILY]
        else _platform_default_mono())
    SOURCE_SERIF_FAMILY_RESOLVED = (
        SOURCE_SERIF_FAMILY
        if _font_families_available[SOURCE_SERIF_FAMILY]
        else _platform_default_sans())
    # Display family (Oswald) is rarely bundled — fall back to
    # Inter-Bold or the platform sans if not available.
    DISPLAY_FAMILY_RESOLVED = (DISPLAY_FAMILY
                               if _font_families_available[DISPLAY_FAMILY]
                               else (INTER_FAMILY
                                     if _font_families_available[INTER_FAMILY]
                                     else _platform_default_sans()))

    _fonts_registered = True


# ============================================================
# AUTO-REGISTER FONTS — runs at module import time, BEFORE the
# OfficeFonts / FightNightFonts class definitions below. This
# ensures INTER_FAMILY_RESOLVED etc. are set to their final values
# (bundled family or platform fallback) by the time the class
# attributes are bound. Safe to call before tkinter has a root
# window — _register_fonts creates a temporary hidden one.
# ============================================================
try:
    _register_fonts()
except Exception as _e:
    print(f"Warning: font registration failed: {_e}", flush=True)
    # Non-fatal — OfficeFonts / FightNightFonts will use the default
    # RESOLVED names (which equal the bundled family names). Tk will
    # fall back to a system font if the bundled family isn't found.


# ============================================================
# FONT TUPLES (for CTk widgets)
# ============================================================

class OfficeFonts:
    """Font tuples for Office Mode (Inter for everything except
    numbers which use JetBrains Mono).

    CTk expects fonts as tuples: (family, size, weight).

    Uses the RESOLVED family names (INTER_FAMILY_RESOLVED etc.) so
    the UI gracefully falls back to platform defaults (Segoe UI on
    Windows, Helvetica on Mac, Sans on Linux) when bundled TTFs
    fail to register — see _register_fonts().
    """
    display = (DISPLAY_FAMILY_RESOLVED, FontSizes.DISPLAY, "bold")
    h1 = (INTER_FAMILY_RESOLVED, FontSizes.H1, "bold")
    h2 = (INTER_FAMILY_RESOLVED, FontSizes.H2, "bold")
    h3 = (INTER_FAMILY_RESOLVED, FontSizes.H3, "bold")
    body = (INTER_FAMILY_RESOLVED, FontSizes.BODY, "normal")
    body_small = (INTER_FAMILY_RESOLVED, FontSizes.BODY_SMALL, "normal")
    caption = (INTER_FAMILY_RESOLVED, FontSizes.CAPTION, "normal")
    mono = (JETBRAINS_MONO_FAMILY_RESOLVED, FontSizes.MONO, "normal")
    descriptor = (INTER_FAMILY_RESOLVED, FontSizes.DESCRIPTOR, "normal")
    commentary = (INTER_FAMILY_RESOLVED, FontSizes.COMMENTARY_OFFICE, "normal")


class FightNightFonts:
    """Font tuples for Fight Night Mode.

    Same as Office EXCEPT commentary switches to Source Serif Pro
    (serif feels like documentary narration, not UI text) and
    pundit interjections use Source Serif Pro SemiBold Italic.

    Uses RESOLVED family names — falls back to platform defaults
    when Source Serif Pro isn't registered.
    """
    display = (DISPLAY_FAMILY_RESOLVED, FontSizes.DISPLAY, "bold")
    h1 = (INTER_FAMILY_RESOLVED, FontSizes.H1, "bold")
    h2 = (INTER_FAMILY_RESOLVED, FontSizes.H2, "bold")
    h3 = (INTER_FAMILY_RESOLVED, FontSizes.H3, "bold")
    body = (INTER_FAMILY_RESOLVED, FontSizes.BODY, "normal")
    body_small = (INTER_FAMILY_RESOLVED, FontSizes.BODY_SMALL, "normal")
    caption = (INTER_FAMILY_RESOLVED, FontSizes.CAPTION, "normal")
    mono = (JETBRAINS_MONO_FAMILY_RESOLVED, FontSizes.MONO, "normal")
    descriptor = (INTER_FAMILY_RESOLVED, FontSizes.DESCRIPTOR, "normal")
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
# ICON PATHS (Task 6.1c — not yet generated)
# ============================================================

# Status icons (16x16 + 32x32). Files will be generated in Task 6.1c.
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
